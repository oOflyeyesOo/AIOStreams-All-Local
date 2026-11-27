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
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request


def _extract_compose_project_label(labels_l: str) -> str:
    """Extract the lowercase com.docker.compose.project value from docker ps labels."""
    if "com.docker.compose.project=" not in labels_l:
        return ""
    for lbl in labels_l.split(","):
        lbl = lbl.strip()
        if lbl.startswith("com.docker.compose.project="):
            return lbl.split("=", 1)[1].strip()
    return ""


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


def _parse_port(value, default: int) -> int:
    try:
        port = int(value)
        return port if 1 <= port <= 65535 else default
    except (TypeError, ValueError):
        return default


def _detect_lan_ip() -> str:
    """Best-effort local LAN IPv4 address discovery without external network traffic."""
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.2)
        sock.connect(("10.255.255.255", 1))
        ip = sock.getsockname()[0]
        if ip and not ip.startswith("127.") and not ip.startswith("169.254."):
            return ip
    except Exception:
        pass
    finally:
        if sock:
            try:
                sock.close()
            except Exception:
                pass
    return ""


def _classify_networks(raw_networks: str, cid: str = "") -> tuple[list[str], str]:
    """Return (networks_list, network_mode) from docker ps {{.Networks}} output."""
    networks = [n.strip() for n in (raw_networks or "").split(",") if n.strip()]
    if not networks and cid:
        try:
            insp = subprocess.run(
                ["docker", "inspect", "-f", "{{.HostConfig.NetworkMode}}", cid],
                capture_output=True, text=True, timeout=4
            )
            mode = (insp.stdout or "").strip()
            if insp.returncode == 0 and mode:
                networks = [mode]
        except Exception:
            pass

    lowered = [n.lower() for n in networks]
    if any(n == "host" for n in lowered):
        return networks, "host"
    if any(n == "stremio-net" or n.endswith("_stremio-net") or n.endswith("-stremio-net") for n in lowered):
        return networks, "stremio-net"
    if any(n == "none" for n in lowered):
        return networks, "none"
    if networks:
        return networks, "bridge"
    return [], "unknown"


def validate_service_url(service_url: str) -> str:
    """Validate and normalize a Cloudflare tunnel ingress origin URL (scheme://host[:port])."""
    if not isinstance(service_url, str) or not service_url.strip():
        raise ValueError("Origin service URL cannot be empty.")
    raw = service_url.strip()
    if any(c.isspace() or c in "$'\"`\\" or ord(c) < 32 or ord(c) == 127 for c in raw):
        raise ValueError("Origin service URL must not contain whitespace, quotes, shell metacharacters, or control characters.")
    if "://" not in raw:
        raw = "http://" + raw
    parsed = urllib.parse.urlsplit(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise ValueError("Origin service URL must use http:// or https://.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Origin service URL must not include credentials, query strings, or fragments.")
    if parsed.path not in ("", "/"):
        raise ValueError("Origin service URL must be a base host:port URL without a path.")
    host = (parsed.hostname or "").strip()
    if not host:
        raise ValueError("Origin service URL is missing a hostname or IP.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Origin service URL has an invalid port number.") from exc
    if port is not None and not (1 <= port <= 65535):
        raise ValueError("Origin service URL port must be between 1 and 65535.")
    try:
        ip_obj = ipaddress.ip_address(host)
        if ip_obj.is_link_local or ip_obj.is_unspecified or ip_obj.is_multicast:
            raise ValueError("Origin service URL cannot target link-local, unspecified, or multicast IP addresses.")
    except ValueError as exc:
        if "Origin service URL" in str(exc):
            raise
    host_fmt = f"[{host}]" if ":" in host and not host.startswith("[") else host
    netloc = f"{host_fmt}:{port}" if port is not None else host_fmt
    return f"{scheme}://{netloc}"


def _derive_aiometadata_origin(aio_origin: str, aiom_port: int = 4005) -> str:
    """Derive the corresponding AIOMetadata origin URL for a given AIOStreams origin URL."""
    aiom_port = _parse_port(aiom_port, 4005)
    try:
        parsed = urllib.parse.urlsplit(aio_origin)
        host = (parsed.hostname or "").lower()
        scheme = parsed.scheme or "http"
        if host == "aiostreams":
            return f"{scheme}://aiometadata:{aiom_port}"
        if host:
            host_fmt = f"[{host}]" if ":" in host and not host.startswith("[") else host
            return f"{scheme}://{host_fmt}:{aiom_port}"
    except Exception:
        pass
    return f"http://host.docker.internal:{aiom_port}"


def check_cloudflare_containers() -> dict:
    """
    Scans the Docker daemon for Cloudflare Tunnel / connector containers.
    Distinguishes between this stack's own tunnel container and external/other
    Cloudflare connector containers running on the host, including network topology.
    """
    try:
        res = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.State}}\t{{.Command}}\t{{.Labels}}\t{{.Networks}}"],
            capture_output=True, text=True, timeout=8
        )
        if res.returncode != 0:
            return {"available": False, "error": res.stderr.strip() or "Docker ps command failed", "containers": []}
    except Exception as e:
        return {"available": False, "error": str(e), "containers": []}

    local_tunnel = None
    external_connectors = []
    project = (
        os.environ.get("AIO_PROJECT_NAME", "").strip()
        or os.environ.get("COMPOSE_PROJECT_NAME", "").strip()
    ).lower()
    lines = res.stdout.strip().splitlines()
    if not project:
        hostname = os.environ.get("HOSTNAME", "").strip().lower()
        if hostname:
            for line in lines:
                parts = line.split("\t")
                if len(parts) < 7:
                    continue
                cid_l = parts[0].strip().lower()
                if cid_l and (cid_l.startswith(hostname) or hostname.startswith(cid_l)):
                    found = _extract_compose_project_label(parts[6].lower())
                    if found:
                        project = found
                        break

    for line in lines:
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        cid, name, image, status, state = parts[0], parts[1], parts[2], parts[3], parts[4]
        cmd = parts[5] if len(parts) > 5 else ""
        labels = parts[6] if len(parts) > 6 else ""
        raw_networks = parts[7] if len(parts) > 7 else ""

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

        proj_label = _extract_compose_project_label(labels_l)
        same_project = (not project) or (not proj_label) or (proj_label == project)
        is_local = same_project and (
            name in ("aio-tunnel", "cloudflared")
            or "com.docker.compose.service=cloudflared" in labels_l
        )

        has_networks_col = len(parts) >= 8
        networks, network_mode = _classify_networks(raw_networks, cid if has_networks_col and not raw_networks.strip() else "")
        if network_mode == "unknown" and is_local:
            network_mode = "stremio-net"

        entry = {
            "id": cid,
            "name": name,
            "image": image,
            "status": status,
            "state": state,
            "is_local": is_local,
            "networks": networks,
            "network_mode": network_mode,
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
        "local_tunnel": local_tunnel or {"name": "aio-tunnel", "status": "Not created", "state": "none", "is_local": True, "networks": [], "network_mode": "stremio-net"},
        "external_connectors": external_connectors,
        "active_external_connectors": active_external,
        "has_external": len(active_external) > 0
    }


def recommend_cloudflare_origin(
    containers_info: dict = None,
    aio_port: int = None,
    aiom_port: int = None,
    env_vars: dict = None,
) -> dict:
    """
    Determine the recommended Cloudflare Tunnel origin URL and connector topology.

    - In-network `aio-tunnel` (or external connector attached to `stremio-net`):
      `http://aiostreams:3000`
    - External host-network connector:
      `http://127.0.0.1:{PORT_AIOSTREAMS}` (default 3001)
    - External bridge/non-`stremio-net` connector or AIO DinD / unconfigured external:
      `http://host.docker.internal:{PORT_AIOSTREAMS}` (default 3001)
    """
    env_map = env_vars if isinstance(env_vars, dict) else {}
    resolved_aio_port = _parse_port(
        aio_port or env_map.get("PORT_AIOSTREAMS") or os.environ.get("PORT_AIOSTREAMS"),
        3001,
    )
    resolved_aiom_port = _parse_port(
        aiom_port or env_map.get("PORT_AIOMETADATA") or os.environ.get("PORT_AIOMETADATA"),
        4005,
    )

    if containers_info is None:
        containers_info = check_cloudflare_containers()

    local_tunnel = (containers_info or {}).get("local_tunnel") or {}
    local_state = str(local_tunnel.get("state") or "").lower()
    local_status = str(local_tunnel.get("status") or "").lower()
    local_running = local_state in ("running", "restarting") or local_status.startswith("up")
    local_net_mode = str(local_tunnel.get("network_mode") or "stremio-net").lower()

    active_external = (containers_info or {}).get("active_external_connectors")
    if active_external is None:
        active_external = [
            c for c in ((containers_info or {}).get("external_connectors") or [])
            if c.get("is_active", True)
        ]

    saved_origin = (env_map.get("CLOUDFLARE_ORIGIN_URL") or os.environ.get("CLOUDFLARE_ORIGIN_URL") or "").strip() or None
    saved_token = (env_map.get("CLOUDFLARE_TUNNEL_TOKEN") or os.environ.get("CLOUDFLARE_TUNNEL_TOKEN") or "").strip()
    token_meta = parse_tunnel_token(saved_token) if saved_token else {"valid": False}
    has_run_token = bool(token_meta.get("is_run_token"))

    origin_warning = None
    if active_external:
        primary = active_external[0]
        primary_name = primary.get("name") or "external-cloudflared"
        ext_mode = str(primary.get("network_mode") or "bridge").lower()
        if ext_mode == "host":
            connector_mode = "external_host"
            recommended_origin = f"http://127.0.0.1:{resolved_aio_port}"
            origin_warning = (
                f"External host-network connector '{primary_name}' cannot resolve Docker DNS 'aiostreams:3000'. "
                f"Use {recommended_origin}."
            )
        elif ext_mode == "stremio-net":
            connector_mode = "external_stremio_net"
            recommended_origin = "http://aiostreams:3000"
        else:
            connector_mode = "external_bridge"
            recommended_origin = f"http://host.docker.internal:{resolved_aio_port}"
            origin_warning = (
                f"External Cloudflare connector '{primary_name}' is outside stremio-net and cannot reach 'aiostreams:3000'. "
                f"Use {recommended_origin} (or http://127.0.0.1:{resolved_aio_port} for host-network connectors)."
            )
    elif local_running:
        if local_net_mode == "host":
            connector_mode = "external_host"
            recommended_origin = f"http://127.0.0.1:{resolved_aio_port}"
        else:
            connector_mode = "local_tunnel"
            recommended_origin = "http://aiostreams:3000"
    elif has_run_token:
        connector_mode = "local_tunnel"
        recommended_origin = "http://aiostreams:3000"
    else:
        connector_mode = "none"
        recommended_origin = f"http://host.docker.internal:{resolved_aio_port}"

    if saved_origin:
        try:
            saved_parsed = urllib.parse.urlsplit(validate_service_url(saved_origin))
            saved_host = (saved_parsed.hostname or "").lower()
            saved_port = saved_parsed.port or (443 if saved_parsed.scheme == "https" else 80)
            if saved_host == "aiostreams" and saved_port == 3000 and connector_mode in ("external_host", "external_bridge", "none"):
                origin_warning = (
                    f"Saved Cloudflare origin '{saved_origin}' targets aiostreams:3000, which is unreachable from "
                    f"external connectors. Update to {recommended_origin}."
                )
            elif saved_host in ("localhost", "127.0.0.1", "host.docker.internal") and saved_port == 3000 and resolved_aio_port != 3000:
                origin_warning = (
                    f"Saved Cloudflare origin '{saved_origin}' targets port 3000, but AIOStreams is mapped to host port "
                    f"{resolved_aio_port}. Update to {recommended_origin}."
                )
        except ValueError:
            pass

    candidates = [
        {
            "label": f"Docker Host Bridge (External container / AIO DinD) — :{resolved_aio_port}",
            "url": f"http://host.docker.internal:{resolved_aio_port}",
        },
        {
            "label": f"Host Loopback (Host-network / bare-metal cloudflared) — :{resolved_aio_port}",
            "url": f"http://127.0.0.1:{resolved_aio_port}",
        },
    ]
    lan_ip = _detect_lan_ip()
    if lan_ip:
        candidates.append({
            "label": f"Host LAN ({lan_ip}) — :{resolved_aio_port}",
            "url": f"http://{lan_ip}:{resolved_aio_port}",
        })
    candidates.append({
        "label": "Internal Docker Network (built-in aio-tunnel on stremio-net only) — :3000",
        "url": "http://aiostreams:3000",
    })

    return {
        "recommended_origin": recommended_origin,
        "detected_origin": saved_origin,
        "connector_mode": connector_mode,
        "origin_warning": origin_warning,
        "origin_candidates": candidates,
        "aiostreams_port": resolved_aio_port,
        "aiometadata_port": resolved_aiom_port,
        "aiometadata_origin": _derive_aiometadata_origin(recommended_origin, resolved_aiom_port),
    }


DEFAULT_TUNNEL_ORIGIN_REQUEST = {
    "connectTimeout": 30,
    "keepAliveTimeout": 60,
    "keepAliveConnections": 100,
    "noHappyEyeballs": True,
}


def build_tunnel_origin_request(existing: dict = None) -> dict:
    """
    Build Cloudflare Zero Trust tunnel originRequest parameters tuned to prevent
    502 keep-alive races and IPv6 dial stalls against AIOStreams.

    Keeps keepAliveTimeout <= 90s (default 60s), strictly below AIOStreams'
    120s Node HTTP keepAliveTimeout so cloudflared closes idle sockets first.
    """
    merged = dict(DEFAULT_TUNNEL_ORIGIN_REQUEST)
    if isinstance(existing, dict):
        for key, value in existing.items():
            if value is not None:
                merged[key] = value
        # Guard against zero or >= 120s keepAliveTimeout reintroducing the 502 race
        ka = merged.get("keepAliveTimeout")
        if not isinstance(ka, (int, float)) or isinstance(ka, bool) or ka <= 0 or ka > 90:
            merged["keepAliveTimeout"] = DEFAULT_TUNNEL_ORIGIN_REQUEST["keepAliveTimeout"]
    return merged


def _origin_request_needs_tuning(existing: dict) -> bool:
    if not isinstance(existing, dict):
        return False
    ka = existing.get("keepAliveTimeout")
    return isinstance(ka, (int, float)) and not isinstance(ka, bool) and (ka <= 0 or ka > 90)


def _upsert_ingress_rule(ingress_rules: list, hostname: str, service_url: str) -> tuple[str, str | None]:
    """Insert or update a hostname ingress rule in place; return (action, previous_service)."""
    clean_host = hostname.strip().lower()
    target = service_url.strip().rstrip("/")
    existing_idx = next(
        (i for i, r in enumerate(ingress_rules) if isinstance(r, dict) and (r.get("hostname") or "").strip().lower() == clean_host),
        None,
    )
    if existing_idx is not None:
        previous = ingress_rules[existing_idx].get("service")
        prev_norm = (previous or "").strip().rstrip("/")
        if prev_norm == target:
            return "unchanged", previous
        ingress_rules[existing_idx] = {**ingress_rules[existing_idx], "hostname": clean_host, "service": target}
        return "repaired", previous

    new_rule = {"hostname": clean_host, "service": target}
    if ingress_rules and isinstance(ingress_rules[-1], dict) and not ingress_rules[-1].get("hostname"):
        ingress_rules.insert(len(ingress_rules) - 1, new_rule)
    else:
        ingress_rules.append(new_rule)
        if not any(isinstance(r, dict) and not r.get("hostname") for r in ingress_rules):
            ingress_rules.append({"service": "http_status:404"})
    return "created", None


def _clean_public_hostname(hostname: str) -> str:
    clean_host = (hostname or "").strip().lower()
    if "://" in clean_host:
        parsed = urllib.parse.urlsplit(clean_host)
        clean_host = parsed.netloc or parsed.path
    return clean_host.split(":")[0].strip().rstrip(".")


def push_cloudflare_dns(
    api_token: str,
    hostname: str,
    cname_target: str,
    account_id: str = None,
    tunnel_id: str = None,
    zone_id: str = None,
    service_url: str = None,
    aiometadata_hostname: str = None,
    aiometadata_service_url: str = None,
) -> dict:
    """
    Creates or updates a DNS CNAME record in Cloudflare pointing hostname to cname_target (proxied).
    Configures or repairs public hostname ingress rules to the resolved origin URL when tunnel
    credentials and permissions exist.
    """
    api_token = (api_token or "").strip()
    if not api_token:
        return {"success": False, "error": "Cloudflare API Token is required. Generate one in Cloudflare Dashboard -> My Profile -> API Tokens."}

    # Clean hostname (remove http(s):// scheme and trailing slashes)
    clean_host = _clean_public_hostname(hostname)

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

    # Validate or recommend origin service_url
    if service_url and str(service_url).strip():
        try:
            target_service_url = validate_service_url(str(service_url))
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
    else:
        target_service_url = recommend_cloudflare_origin()["recommended_origin"]

    clean_aiom_host = _clean_public_hostname(aiometadata_hostname) if aiometadata_hostname else ""
    if clean_aiom_host and "." not in clean_aiom_host:
        return {"success": False, "error": f"Enter a valid AIOMetadata domain or subdomain (received '{clean_aiom_host}')."}
    if aiometadata_service_url and str(aiometadata_service_url).strip():
        try:
            target_aiom_url = validate_service_url(str(aiometadata_service_url))
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
    else:
        target_aiom_url = _derive_aiometadata_origin(target_service_url)

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

    # 3. Optional: Configure or repair public hostname ingress rule if account_id and tunnel_id are available
    ingress_configured = False
    ingress_error = None
    ingress_action = "skipped"
    repaired = False
    previous_service_url = None
    if account_id and tunnel_id:
        cfg_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations"
        try:
            cfg_req = urllib.request.Request(cfg_url, headers=headers, method="GET")
            with urllib.request.urlopen(cfg_req, timeout=10) as c_resp:
                cfg_data = json.loads(c_resp.read().decode("utf-8"))
            if cfg_data.get("success"):
                current_cfg = cfg_data.get("result", {}).get("config", {}) or {}
                ingress_rules = list(current_cfg.get("ingress", []))

                ingress_action, previous_service_url = _upsert_ingress_rule(
                    ingress_rules, clean_host, target_service_url
                )
                aiom_action = "unchanged"
                if clean_aiom_host and clean_aiom_host != clean_host:
                    aiom_action, _ = _upsert_ingress_rule(
                        ingress_rules, clean_aiom_host, target_aiom_url
                    )

                origin_needs_tuning = _origin_request_needs_tuning(current_cfg.get("originRequest"))
                if ingress_action in ("created", "repaired") or aiom_action in ("created", "repaired") or origin_needs_tuning:
                    tuned_origin_request = build_tunnel_origin_request(current_cfg.get("originRequest"))
                    update_payload = {
                        "config": {
                            **current_cfg,
                            "originRequest": tuned_origin_request,
                            "ingress": ingress_rules,
                        }
                    }
                    put_req = urllib.request.Request(
                        cfg_url,
                        data=json.dumps(update_payload).encode("utf-8"),
                        headers=headers,
                        method="PUT",
                    )
                    with urllib.request.urlopen(put_req, timeout=10) as p_resp:
                        p_data = json.loads(p_resp.read().decode("utf-8"))
                        if p_data.get("success"):
                            ingress_configured = True
                            repaired = (ingress_action == "repaired") or origin_needs_tuning
                            if origin_needs_tuning and ingress_action == "unchanged":
                                ingress_action = "repaired"
                        else:
                            ingress_action = "failed"
                            errs = p_data.get("errors") or []
                            ingress_error = "; ".join(e.get("message", "") for e in errs if isinstance(e, dict)) or "Cloudflare rejected tunnel ingress update"
                else:
                    ingress_configured = True
            else:
                ingress_action = "failed"
                errs = cfg_data.get("errors") or []
                ingress_error = "; ".join(e.get("message", "") for e in errs if isinstance(e, dict)) or "Failed to read tunnel configuration"
        except urllib.error.HTTPError as he:
            ingress_action = "failed"
            ingress_error = f"HTTP {he.code}"
        except Exception as ex:
            ingress_action = "failed"
            ingress_error = str(ex)

    msg = f"✓ Successfully {action} Cloudflare CNAME: {clean_host} ➜ {clean_target} (Proxied: ON) in zone '{zone_name}'."
    if ingress_configured:
        if repaired and previous_service_url:
            msg += f" Repaired stale ingress route ({previous_service_url} ➜ {target_service_url})!"
        elif ingress_action == "unchanged":
            msg += f" Ingress route already points to {target_service_url}."
        else:
            msg += f" Ingress route to {target_service_url} configured automatically!"
    elif ingress_error:
        msg += f" Note: Cloudflare Ingress rule could not be auto-updated ({ingress_error}). Ensure Public Hostname points to {target_service_url} in Zero Trust dashboard."

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
        "service_url": target_service_url,
        "ingress_configured": ingress_configured,
        "ingress_action": ingress_action,
        "repaired": repaired,
        "previous_service_url": previous_service_url,
        "ingress_error": ingress_error,
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
    project = (
        os.environ.get("AIO_PROJECT_NAME", "").strip()
        or os.environ.get("COMPOSE_PROJECT_NAME", "").strip()
    )
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

        result = {
            "success": True,
            "action": action,
            "output": output,
            "error": None
        }
        if action == "status":
            tunnel_status = "not_created"
            for line in output.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    info = json.loads(line)
                    if isinstance(info, list) and info:
                        info = info[0]
                    if isinstance(info, dict):
                        st = str(info.get("State") or info.get("Status") or "").strip().lower()
                        if st:
                            tunnel_status = st
                            break
                except Exception:
                    pass
            result["status"] = tunnel_status
        return result
    except Exception as e:
        return {"success": False, "action": action, "error": str(e)}
