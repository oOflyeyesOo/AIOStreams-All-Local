"""
Cloudflare Tunnel & DNS Automation Helper
==========================================
Provides utilities to:
1. Detect local and external Cloudflare connector (cloudflared) containers on the Docker host.
2. Parse Cloudflare Zero-Trust Tunnel tokens (extract account ID, tunnel ID, and CNAME target).
3. Automatically create/update Cloudflare DNS CNAME records and tunnel public hostname routing.
4. Manage the local aio-tunnel container lifecycle.
"""

import base64
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request


def normalize_tunnel_token(token: str) -> str:
    """Extract a token from pasted commands without exposing it in metadata."""
    if not token or not isinstance(token, str):
        return ""
    raw = token.strip()
    if not raw:
        return ""

    # Extract token if user pasted a shell command or flag like --token <token>
    token_match = re.search(r'(?:--token(?:\s+|=)|(?:^|\s)[A-Za-z_]*TOKEN=)(["\']?)([^"\'\s]+)\1', raw, re.IGNORECASE)
    if token_match:
        raw = token_match.group(2)
    else:
        raw = raw.strip("\"'")
        words = raw.split()
        if len(words) > 1:
            longest = max(words, key=len)
            if len(longest) >= 20:
                raw = longest

    raw = raw.strip("\"' \t\r\n")
    return raw


def parse_tunnel_token(token: str) -> dict:
    """Return public tunnel identifiers and capabilities, never credentials."""
    raw = normalize_tunnel_token(token)
    if not raw:
        return {"valid": False}

    # 1. Base64 JSON token (standard cloudflared token: eyJh...)
    normalized = raw.replace("-", "+").replace("_", "/")
    padded = normalized + "=" * ((4 - len(normalized) % 4) % 4)
    try:
        decoded = base64.b64decode(padded.encode("ascii")).decode("utf-8")
        data = json.loads(decoded)
        if isinstance(data, dict):
            tunnel_id = str(data.get("t") or data.get("tunnel_id") or data.get("TunnelID") or "").strip()
            account_id = str(data.get("a") or data.get("account_id") or data.get("AccountTag") or "").strip()
            has_secret = bool(data.get("s") or data.get("secret") or data.get("TunnelSecret"))
            if tunnel_id:
                return {
                    "valid": True,
                    "account_id": account_id,
                    "tunnel_id": tunnel_id,
                    "cname_target": f"{tunnel_id}.cfargotunnel.com",
                    "is_run_token": has_secret and bool(account_id)
                }
    except Exception:
        pass

    # 2. Full CNAME target (e.g. *.cfargotunnel.com or <uuid>.cfargotunnel.com)
    clean_target = raw.lower()
    if "://" in clean_target:
        clean_target = clean_target.split("://")[-1]
    clean_target = clean_target.split("/")[0].split(":")[0].strip().rstrip(".")
    if clean_target.endswith(".cfargotunnel.com") or ".cfargotunnel.com" in clean_target:
        cname_uuid_match = re.search(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{32})', clean_target)
        if cname_uuid_match:
            tunnel_id = cname_uuid_match.group(1).lower()
            return {
                "valid": True,
                "account_id": "",
                "tunnel_id": tunnel_id,
                "cname_target": f"{tunnel_id}.cfargotunnel.com",
                "is_run_token": False
            }
        prefix = clean_target.split(".cfargotunnel.com")[0].split(".")[-1].strip()
        if prefix:
            return {
                "valid": True,
                "account_id": "",
                "tunnel_id": prefix,
                "cname_target": f"{prefix}.cfargotunnel.com",
                "is_run_token": False
            }

    # 3. Raw tunnel UUID (e.g. 8-4-4-4-12 hex UUID or 32-char hex)
    uuid_match = re.fullmatch(r'([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|[0-9a-fA-F]{32})', raw)
    if uuid_match:
        tunnel_id = uuid_match.group(1).lower()
        return {
            "valid": True,
            "account_id": "",
            "tunnel_id": tunnel_id,
            "cname_target": f"{tunnel_id}.cfargotunnel.com",
            "is_run_token": False
        }

    return {"valid": False}


def fetch_cloudflare_tunnel_token(api_token: str, account_id: str, tunnel_id: str) -> dict:
    """
    Fetches the full cloudflared run token for a specific tunnel from the Cloudflare API.
    GET /client/v4/accounts/{account_id}/cfd_tunnel/{tunnel_id}/token
    Requires Cloudflare One Connectors / Tunnel read permissions on the API token.
    """
    api_token = (api_token or "").strip()
    account_id = (account_id or "").strip()
    tunnel_id = (tunnel_id or "").strip()
    if not api_token or not account_id or not tunnel_id:
        return {"success": False, "error": "api_token, account_id, and tunnel_id are all required."}

    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/cfd_tunnel/{tunnel_id}/token"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "User-Agent": "AIOStreams-Stack-Manager/1.0"
    }
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("success") and data.get("result"):
            return {"success": True, "token": str(data["result"]).strip()}
        errors = data.get("errors", [])
        msg = "; ".join(err.get("message", "") for err in errors if isinstance(err, dict)) or "Failed to retrieve tunnel token."
        return {"success": False, "error": msg}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        err_msg = f"Cloudflare API error ({e.code})"
        try:
            err_json = json.loads(body)
            if err_json.get("errors"):
                err_msg = "; ".join(err.get("message", "") for err in err_json["errors"] if err.get("message")) or err_msg
        except Exception:
            pass
        return {"success": False, "error": err_msg}
    except Exception as e:
        return {"success": False, "error": f"Failed to connect to Cloudflare API: {str(e)}"}


def check_cloudflare_containers() -> dict:
    """
    Scans the Docker daemon for Cloudflare Tunnel / connector containers.
    Distinguishes between this stack's own tunnel container and external/other
    Cloudflare connector containers running on the host.
    """
    try:
        res = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.State}}\t{{.Command}}\t{{.Labels}}"],
            capture_output=True, text=True, timeout=8
        )
        if res.returncode != 0:
            return {"available": False, "error": res.stderr.strip() or "Docker ps command failed", "containers": []}
    except Exception as e:
        return {"available": False, "error": str(e), "containers": []}

    local_tunnel = None
    external_connectors = []

    for line in res.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        cid, name, image, status, state = parts[0], parts[1], parts[2], parts[3], parts[4]
        cmd = parts[5] if len(parts) > 5 else ""
        labels = parts[6] if len(parts) > 6 else ""

        name_l = name.lower()
        image_l = image.lower()
        cmd_l = cmd.lower()
        labels_l = labels.lower()

        # Disregard FlareSolverr (antibot proxy for indexers, not a tunnel connector)
        if "flaresolverr" in name_l or "flaresolverr" in image_l:
            continue

        is_cf = (
            "cloudflared" in image_l
            or "cloudflared" in name_l
            or "cloudflare-tunnel" in name_l
            or "cf-tunnel" in name_l
            or "cloudflared" in cmd_l
            or "tunnel run" in cmd_l
            or "tunnel --config" in cmd_l
            or "docktun.provider=cloudflare" in labels_l
        )

        if not is_cf:
            continue

        is_local = (
            name in ("aio-tunnel", "cloudflared")
            or "com.docker.compose.service=cloudflared" in labels_l
        )

        entry = {
            "id": cid,
            "name": name,
            "image": image,
            "status": status,
            "state": state,
            "is_local": is_local
        }

        if is_local:
            local_tunnel = entry
        else:
            is_active = state.lower() in ("running", "restarting") or status.lower().startswith("up")
            entry["is_active"] = is_active
            external_connectors.append(entry)

    active_external = [c for c in external_connectors if c.get("is_active", True)]
    return {
        "available": True,
        "local_tunnel": local_tunnel or {"name": "aio-tunnel", "status": "Not created", "state": "none", "is_local": True},
        "external_connectors": external_connectors,
        "active_external_connectors": active_external,
        "has_external": len(active_external) > 0
    }


def push_cloudflare_dns(api_token: str, hostname: str, cname_target: str, account_id: str = None, tunnel_id: str = None, zone_id: str = None) -> dict:
    """
    Creates or updates a DNS CNAME record in Cloudflare pointing hostname to cname_target (proxied).
    Optionally configures public hostname ingress rules if tunnel credentials and permissions exist.
    """
    api_token = (api_token or "").strip()
    if not api_token:
        return {"success": False, "error": "Cloudflare API Token is required. Generate one in Cloudflare Dashboard -> My Profile -> API Tokens."}

    # Clean hostname (remove http(s):// scheme and trailing slashes)
    clean_host = hostname.strip().lower()
    if "://" in clean_host:
        parsed = urllib.parse.urlsplit(clean_host)
        clean_host = parsed.netloc or parsed.path
    clean_host = clean_host.split(":")[0].strip().rstrip(".")

    is_ip = False
    try:
        ipaddress.ip_address(clean_host)
        is_ip = True
    except ValueError:
        if re.match(r'^(?:\d{1,3}\.){3}\d{1,3}$', clean_host) or re.match(r'^(?:(?:\d{1,3}|x)\.){3}(?:\d{1,3}|x)$', clean_host, re.IGNORECASE):
            is_ip = True

    if clean_host == "localhost" or clean_host.startswith("localhost.") or clean_host.endswith(".localhost") or is_ip:
        return {
            "success": False,
            "error": "Cloudflare DNS requires a public domain name (e.g. watch.yourdomain.com), not a local IP address."
        }

    if not clean_host or "." not in clean_host:
        return {"success": False, "error": f"Enter a valid domain or subdomain (received '{clean_host}')."}

    # Clean target
    clean_target = cname_target.strip().lower().rstrip(".")
    if not clean_target:
        return {"success": False, "error": "CNAME target is required (e.g. <tunnel_id>.cfargotunnel.com). Enter a valid Tunnel Token first."}

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "User-Agent": "AIOStreams-Stack-Manager/1.0"
    }

    # 1. Resolve matching zone in Cloudflare
    zone_id = (zone_id or "").strip()
    zone_name = clean_host
    if not zone_id:
        zones_url = "https://api.cloudflare.com/client/v4/zones?per_page=50&status=active"
        try:
            req = urllib.request.Request(zones_url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            err_msg = f"Cloudflare API returned status {e.code}"
            try:
                err_json = json.loads(body)
                if err_json.get("errors"):
                    err_msg = "; ".join(err.get("message", "") for err in err_json["errors"] if err.get("message")) or err_msg
            except Exception:
                pass
            return {"success": False, "error": f"Cloudflare API Error ({e.code}): {err_msg}"}
        except Exception as e:
            return {"success": False, "error": f"Failed to connect to Cloudflare API: {str(e)}"}

        if not data.get("success"):
            errors = data.get("errors", [])
            msg = "; ".join(err.get("message", "") for err in errors if isinstance(err, dict)) or "Failed to list Cloudflare zones."
            return {"success": False, "error": msg}

        zones = data.get("result", [])
        if not zones:
            return {"success": False, "error": "No active domains/zones found in this Cloudflare account."}

        # Find longest matching zone name (e.g., 'sub.example.com' before 'example.com')
        matching_zone = None
        for zone in sorted(zones, key=lambda z: len(z.get("name", "")), reverse=True):
            zname = zone.get("name", "").lower().strip()
            if clean_host == zname or clean_host.endswith("." + zname):
                matching_zone = zone
                break

        if not matching_zone:
            available_names = [z.get("name") for z in zones if z.get("name")]
            return {
                "success": False,
                "error": f"No Cloudflare zone found for '{clean_host}'. Available domains in your Cloudflare account: {', '.join(available_names)}"
            }

        zone_id = matching_zone["id"]
        zone_name = matching_zone["name"]
        if not account_id and isinstance(matching_zone.get("account"), dict):
            account_id = matching_zone["account"].get("id") or account_id

    # 2. Check if a DNS record already exists for clean_host
    query_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records?name={urllib.parse.quote(clean_host)}&per_page=10"
    try:
        req = urllib.request.Request(query_url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=12) as resp:
            rec_data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"success": False, "error": f"Failed to query existing DNS records in zone '{zone_name}': {str(e)}"}

    existing_record = None
    if rec_data.get("success") and rec_data.get("result"):
        for rec in rec_data["result"]:
            if rec.get("name", "").lower() == clean_host:
                existing_record = rec
                break

    record_payload = {
        "type": "CNAME",
        "name": clean_host,
        "content": clean_target,
        "proxied": True,
        "ttl": 1,
        "comment": "Managed by AIO Local Stack"
    }

    if existing_record:
        rec_id = existing_record["id"]
        save_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{rec_id}"
        save_method = "PUT"
        action = "updated"
    else:
        save_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
        save_method = "POST"
        action = "created"

    try:
        req = urllib.request.Request(save_url, data=json.dumps(record_payload).encode("utf-8"), headers=headers, method=save_method)
        with urllib.request.urlopen(req, timeout=12) as resp:
            save_result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        err_msg = f"Cloudflare DNS save failed ({e.code})"
        try:
            err_json = json.loads(body)
            if err_json.get("errors"):
                err_msg = "; ".join(err.get("message", "") for err in err_json["errors"] if err.get("message")) or err_msg
        except Exception:
            pass
        return {"success": False, "error": err_msg}
    except Exception as e:
        return {"success": False, "error": f"Failed to save DNS record: {str(e)}"}

    if not save_result.get("success"):
        errors = save_result.get("errors", [])
        msg = "; ".join(err.get("message", "") for err in errors if isinstance(err, dict)) or "Failed to save DNS record."
        return {"success": False, "error": msg}

    record_info = save_result.get("result", {})

    # 3. Optional: Configure public hostname ingress rule if account_id and tunnel_id are available
    ingress_configured = False
    ingress_error = None
    if account_id and tunnel_id:
        cfg_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations"
        try:
            cfg_req = urllib.request.Request(cfg_url, headers=headers, method="GET")
            with urllib.request.urlopen(cfg_req, timeout=10) as c_resp:
                cfg_data = json.loads(c_resp.read().decode("utf-8"))
            if cfg_data.get("success"):
                current_cfg = cfg_data.get("result", {}).get("config", {}) or {}
                ingress_rules = list(current_cfg.get("ingress", []))
                
                # Check if rule for clean_host already exists
                has_rule = any(r.get("hostname", "").lower() == clean_host for r in ingress_rules)
                if not has_rule:
                    new_rule = {
                        "hostname": clean_host,
                        "service": "http://aiostreams:3000"
                    }
                    # Insert before catch-all
                    if ingress_rules and not ingress_rules[-1].get("hostname"):
                        ingress_rules.insert(len(ingress_rules) - 1, new_rule)
                    else:
                        ingress_rules.append(new_rule)
                        if not any(not r.get("hostname") for r in ingress_rules):
                            ingress_rules.append({"service": "http_status:404"})

                    update_payload = {"config": {**current_cfg, "ingress": ingress_rules}}
                    put_req = urllib.request.Request(cfg_url, data=json.dumps(update_payload).encode("utf-8"), headers=headers, method="PUT")
                    with urllib.request.urlopen(put_req, timeout=10) as p_resp:
                        p_data = json.loads(p_resp.read().decode("utf-8"))
                        if p_data.get("success"):
                            ingress_configured = True
                else:
                    ingress_configured = True
        except urllib.error.HTTPError as he:
            ingress_error = f"HTTP {he.code}"
        except Exception as ex:
            ingress_error = str(ex)

    msg = f"✓ Successfully {action} Cloudflare CNAME: {clean_host} ➜ {clean_target} (Proxied: ON) in zone '{zone_name}'."
    if ingress_configured:
        msg += " Ingress route to http://aiostreams:3000 configured automatically!"
    elif ingress_error:
        msg += f" Note: Cloudflare Ingress rule could not be auto-updated ({ingress_error}). Ensure Public Hostname points to http://aiostreams:3000 in Zero Trust dashboard."

    return {
        "success": True,
        "action": action,
        "hostname": clean_host,
        "cname_target": clean_target,
        "zone_name": zone_name,
        "zone_id": zone_id,
        "account_id": account_id,
        "tunnel_id": tunnel_id,
        "record_id": record_info.get("id"),
        "proxied": True,
        "ingress_configured": ingress_configured,
        "message": msg
    }


def manage_local_tunnel(action: str, cwd: str = None, token: str = None) -> dict:
    """
    Controls the local cloudflared container via Docker Compose.
    Supported actions: 'start', 'stop', 'restart', 'status'.
    """
    action = (action or "").strip().lower()
    if action not in ("start", "stop", "restart", "status"):
        return {"success": False, "error": f"Invalid tunnel action '{action}'. Use start, stop, restart, or status."}

    run_env = os.environ.copy()
    # Resolve token before starting
    if action in ("start", "restart"):
        env_token = (token or "").strip() or os.environ.get("CLOUDFLARE_TUNNEL_TOKEN", "").strip()
        if not env_token:
            search_paths = []
            if cwd:
                search_paths.append(Path(cwd) / ".env")
            search_paths.append(Path(".env"))
            for env_path in search_paths:
                if env_path.exists():
                    try:
                        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
                            line = line.strip()
                            if line.startswith("CLOUDFLARE_TUNNEL_TOKEN="):
                                env_token = line.split("=", 1)[1].strip().strip("\"'")
                                break
                    except Exception:
                        pass
                if env_token:
                    break

        if not env_token:
            return {
                "success": False,
                "action": action,
                "error": "Cloudflare Tunnel Token is not configured in .env. Enter your tunnel token first to start the connector."
            }
        run_env["CLOUDFLARE_TUNNEL_TOKEN"] = normalize_tunnel_token(env_token)

    compose = ["docker", "compose"]
    root = Path(cwd or ".")
    project = os.environ.get("AIO_PROJECT_NAME") or os.environ.get("COMPOSE_PROJECT_NAME")
    if project:
        compose.extend(["-p", project])
    if not (root / "docker-compose.yml").exists() and (root / "compose.manager.yml").exists():
        if not project:
            return {"success": False, "action": action,
                    "error": "Compose project name is unavailable. Recreate the portal from your Docker manager before starting a tunnel."}
        compose.extend(["-f", str((root / "compose.manager.yml").resolve())])
    compose.extend(["--profile", "tunnel"])
    cmd = list(compose)
    if action == "start":
        cmd.extend(["up", "-d", "cloudflared"])
    elif action == "stop":
        cmd.extend(["stop", "cloudflared"])
    elif action == "restart":
        # A plain restart retains the previous container command and old token.
        cmd.extend(["up", "-d", "--force-recreate", "cloudflared"])
    elif action == "status":
        cmd.extend(["ps", "cloudflared", "--format", "json"])

    try:
        res = subprocess.run(cmd, cwd=cwd, env=run_env, capture_output=True, text=True, timeout=30)
        output = (res.stdout or res.stderr or "").strip()
        if res.returncode != 0:
            return {"success": False, "action": action, "output": output, "error": output}

        if action in ("start", "restart"):
            time.sleep(1.0)
            selected = subprocess.run(
                compose + ["ps", "--all", "-q", "cloudflared"],
                cwd=cwd, env=run_env, capture_output=True, text=True, timeout=8
            )
            container_ids = (selected.stdout or "").strip().splitlines()
            if selected.returncode != 0 or len(container_ids) != 1:
                return {"success": False, "action": action, "status": "unknown",
                        "error": "Could not locate this stack's tunnel container. Check Docker access and retry."}
            container_id = container_ids[0]
            insp = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Status}} {{.State.Running}}", container_id],
                capture_output=True, text=True, timeout=8
            )
            insp_out = (insp.stdout or "").strip().lower()
            if insp.returncode != 0:
                return {"success": False, "action": action, "status": "unknown",
                        "error": "Could not verify the local tunnel container. Check Docker access and retry."}
            if insp_out != "running true":
                logs_res = subprocess.run(
                    ["docker", "logs", "--tail", "6", container_id],
                    capture_output=True, text=True, timeout=8
                )
                err_log = (logs_res.stdout or logs_res.stderr or "").strip()
                subprocess.run(compose + ["stop", "cloudflared"], cwd=cwd, env=run_env, capture_output=True, timeout=10)
                return {
                    "success": False,
                    "action": action,
                    "status": "failed",
                    "error": f"aio-tunnel container failed to run ({err_log or 'container exited immediately'}). Verify your Cloudflare Tunnel Token is valid."
                }
            return {
                "success": True,
                "action": action,
                "status": "running",
                "output": "aio-tunnel container is running. Cloudflare connectivity has not been verified."
            }

        return {
            "success": True,
            "action": action,
            "output": output,
            "error": None
        }
    except Exception as e:
        return {"success": False, "action": action, "error": str(e)}
