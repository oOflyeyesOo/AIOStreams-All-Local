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
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request


def parse_tunnel_token(token: str) -> dict:
    """
    Parses a Cloudflare Zero-Trust Tunnel token (Base64-encoded JSON)
    to extract account tag, tunnel UUID, and canonical CNAME target.
    """
    if not token or not isinstance(token, str):
        return {"valid": False}
    token = token.strip()
    padded = token + "=" * ((4 - len(token) % 4) % 4)
    try:
        decoded = base64.b64decode(padded).decode("utf-8")
        data = json.loads(decoded)
        if isinstance(data, dict) and "t" in data:
            tunnel_id = str(data.get("t", "")).strip()
            account_id = str(data.get("a", "")).strip()
            if tunnel_id:
                return {
                    "valid": True,
                    "account_id": account_id,
                    "tunnel_id": tunnel_id,
                    "cname_target": f"{tunnel_id}.cfargotunnel.com"
                }
    except Exception:
        pass
    return {"valid": False}


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
            external_connectors.append(entry)

    return {
        "available": True,
        "local_tunnel": local_tunnel or {"name": "aio-tunnel", "status": "Not created", "state": "none", "is_local": True},
        "external_connectors": external_connectors,
        "has_external": len(external_connectors) > 0
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
        "record_id": record_info.get("id"),
        "proxied": True,
        "ingress_configured": ingress_configured,
        "message": msg
    }


def manage_local_tunnel(action: str, cwd: str = None) -> dict:
    """
    Controls the local cloudflared container via Docker Compose.
    Supported actions: 'start', 'stop', 'restart', 'status'.
    """
    action = (action or "").strip().lower()
    if action not in ("start", "stop", "restart", "status"):
        return {"success": False, "error": f"Invalid tunnel action '{action}'. Use start, stop, restart, or status."}

    cmd = ["docker", "compose", "--profile", "tunnel"]
    if action == "start":
        cmd.extend(["up", "-d", "cloudflared"])
    elif action == "stop":
        cmd.extend(["stop", "cloudflared"])
    elif action == "restart":
        cmd.extend(["restart", "cloudflared"])
    elif action == "status":
        cmd.extend(["ps", "cloudflared", "--format", "json"])

    try:
        res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=30)
        output = (res.stdout or res.stderr or "").strip()
        return {
            "success": res.returncode == 0,
            "action": action,
            "output": output,
            "error": None if res.returncode == 0 else output
        }
    except Exception as e:
        return {"success": False, "action": action, "error": str(e)}
