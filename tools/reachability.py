"""
End-to-End Stack & Cloudflare Origin Reachability Verification
==============================================================
Probes:
1. Internal Docker-network service endpoints for active COMPOSE_PROFILES.
2. Published host ports (e.g. 127.0.0.1:3001, :4005, :8088, etc.).
3. Portal routes (/healthz, /ready, /watch/).
4. Cloudflare tunnel origin target reachability & topology validation
   (flagging unreachable aiostreams:3000 on external connectors vs working :3001).
5. Optional public BASE_URL / AIOMETADATA_HOST HTTP reachability.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from init.service_inventory import (
    HEALTH_PROBES,
    INTEGRATIONS,
    SERVICE_PORT_MAP,
    is_service_active,
    parse_compose_profiles,
)
from tools.cloudflare_helper import (
    check_cloudflare_containers,
    recommend_cloudflare_origin,
    validate_service_url,
)


HOST_EXPOSED_SERVICES = {
    "aiostreams",
    "aiometadata",
    "prowlarr",
    "zilean",
    "stremthru",
    "postersplus",
    "subsense",
    "flaresolverr",
    "anime-kitsu",
    "jikan-api",
}

ALL_INTERFACE_SERVICES = {"aiostreams", "aiometadata", "portal"}

SERVICE_REACHABILITY_SPECS = {
    "aiostreams": {"name": "AIOStreams", "path": "/api/v1/status", "critical": True},
    "aiometadata": {"name": "AIOMetadata", "path": "/health/live", "critical": True},
    "prowlarr": {"name": "Prowlarr", "path": "/ping", "critical": False},
    "zilean": {"name": "Zilean", "path": "/dmm/filtered?query=ping", "critical": False},
    "stremthru": {"name": "StremThru", "path": "/v0/health", "critical": False},
    "postersplus": {"name": "Posters+", "path": "/health", "critical": False},
    "subsense": {"name": "SubSense", "path": "/", "critical": False},
    "lumiere-db": {"name": "LumiereDB", "path": "/health", "critical": False},
    "flaresolverr": {"name": "FlareSolverr", "path": "/", "critical": False},
    "anime-kitsu": {"name": "Anime Kitsu", "path": "/manifest.json", "critical": False},
    "jikan-api": {"name": "Jikan API", "path": "/v4", "critical": False},
}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirect)


def _in_container() -> bool:
    return os.path.exists("/.dockerenv") or os.environ.get("AIO_CONTAINER_ENV", "").lower() == "true"


def _is_dns_error(exc: Exception) -> bool:
    if isinstance(exc, socket.gaierror):
        return True
    reason = getattr(exc, "reason", None)
    if isinstance(reason, socket.gaierror):
        return True
    msg = str(reason if reason is not None else exc).lower()
    return any(
        ind in msg
        for ind in (
            "name has no usable address",
            "name or service not known",
            "getaddrinfo failed",
            "nodename nor servname provided",
            "errno -5",
            "errno -2",
            "errno 11001",
            "eai_noname",
            "eai_again",
            "eai_nodata",
            "eai_addrfamily",
            "gaierror",
        )
    )


def _is_connect_or_dns_error(exc: Exception) -> bool:
    """Return True for DNS lookup or socket connection failures (excluding HTTP 4xx/5xx or TLS errors)."""
    if isinstance(exc, urllib.error.HTTPError):
        return False
    if _is_dns_error(exc):
        return True
    reason = getattr(exc, "reason", None)
    target = reason if reason is not None else exc
    if isinstance(target, ConnectionError):
        return True
    if isinstance(target, OSError) and not isinstance(target, (urllib.error.URLError, ssl.SSLError)):
        return True
    msg = str(target).lower()
    return any(
        ind in msg
        for ind in (
            "connection refused",
            "errno 111",
            "errno 10061",
            "cannot assign requested address",
            "network is unreachable",
            "no route to host",
        )
    )


def _parse_port(value, default: int) -> int:
    try:
        p = int(value)
        return p if 1 <= p <= 65535 else default
    except (TypeError, ValueError):
        return default


def _service_ports(service: str, env_vars: dict) -> tuple[int, int]:
    """Return (internal_port, host_port) for an inventoried service."""
    if service == "portal":
        p = _parse_port(env_vars.get("PORT_PORTAL") or os.environ.get("PORT_PORTAL"), 8088)
        return p, p
    internal_port, default_host_port, env_var = SERVICE_PORT_MAP[service]
    host_port = _parse_port(env_vars.get(env_var) or os.environ.get(env_var), default_host_port)
    return internal_port, host_port


def _is_public_url(url_str: str) -> bool:
    if not url_str or not isinstance(url_str, str):
        return False
    raw = url_str.strip()
    if not raw or "://" not in raw:
        return False
    parsed = urllib.parse.urlsplit(raw)
    host = (parsed.hostname or "").lower()
    if not host or host in ("localhost", "127.0.0.1", "::1", "0.0.0.0", "aiostreams", "aiometadata"):
        return False
    if host == "yourdomain.com" or host.endswith(".yourdomain.com") or host.endswith((".local", ".internal", ".lan", ".home.arpa", ".test", ".example")):
        return False
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    except ValueError:
        pass
    return "." in host


def _probe_http(url: str, timeout: float = 2.5, follow_redirects: bool = False) -> tuple[bool, int | None, float, str, Exception | None]:
    """Probe an HTTP(S) URL. Returns (ok, status_code, latency_ms, detail, exc)."""
    t0 = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": "AIO-Reachability/1.0", "Accept-Encoding": "identity"})
    opener = urllib.request.urlopen if follow_redirects else _NO_REDIRECT_OPENER.open
    try:
        with opener(req, timeout=timeout) as resp:
            code = getattr(resp, "status", 200) or 200
            ms = round((time.monotonic() - t0) * 1000, 1)
            return (code < 500), code, ms, f"HTTP {code}", None
    except urllib.error.HTTPError as err:
        ms = round((time.monotonic() - t0) * 1000, 1)
        return (err.code < 500), err.code, ms, f"HTTP {err.code}", err
    except Exception as exc:
        ms = round((time.monotonic() - t0) * 1000, 1)
        reason = getattr(exc, "reason", None)
        detail = f"{type(exc).__name__}: {reason or exc}"
        return False, None, ms, detail, exc


def _probe_tcp(host: str, port: int, timeout: float = 1.5) -> tuple[bool, float, str, Exception | None]:
    t0 = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            ms = round((time.monotonic() - t0) * 1000, 1)
            return True, ms, f"TCP {host}:{port} open", None
    except Exception as exc:
        ms = round((time.monotonic() - t0) * 1000, 1)
        return False, ms, f"{type(exc).__name__}: {exc}", exc


def _make_check(
    check_id: str,
    name: str,
    category: str,
    target: str,
    ok: bool,
    status: str,
    required: bool,
    latency_ms: float | None,
    detail: str,
    remediation: str | None = None,
) -> dict:
    return {
        "id": check_id,
        "name": name,
        "category": category,
        "target": target,
        "ok": bool(ok),
        "status": status,
        "required": bool(required),
        "latency_ms": latency_ms,
        "detail": detail,
        "remediation": remediation,
    }


def active_reachability_services(env_vars: dict = None) -> list[str]:
    """Return ordered list of active services for current COMPOSE_PROFILES."""
    env_map = env_vars if isinstance(env_vars, dict) else {}
    raw_profiles = env_map.get("COMPOSE_PROFILES") or os.environ.get("COMPOSE_PROFILES") or "core"
    profiles = parse_compose_profiles(raw_profiles)
    ordered = [host for _, host, _, _ in INTEGRATIONS] + ["jikan-api"]
    return [svc for svc in ordered if is_service_active(svc, profiles)]


def _check_internal_service(service: str, env_vars: dict, timeout: float, inside_container: bool) -> dict:
    spec = SERVICE_REACHABILITY_SPECS[service]
    internal_port, _ = _service_ports(service, env_vars)
    path = spec["path"]
    hosts = [service]
    if service == "subsense":
        hosts.append("stremio-subsense")

    last_detail = ""
    last_exc = None
    total_ms = 0.0
    primary_url = f"http://{service}:{internal_port}{path}"
    for h in hosts:
        url = f"http://{h}:{internal_port}{path}"
        ok, _, ms, detail, exc = _probe_http(url, timeout=timeout)
        total_ms = ms
        if ok:
            return _make_check(
                f"internal:{service}",
                f"{spec['name']} (Internal Docker)",
                "internal",
                url,
                True,
                "ok",
                spec["critical"],
                ms,
                detail,
            )
        last_detail = detail
        last_exc = exc

    if not inside_container and last_exc is not None and _is_dns_error(last_exc):
        return _make_check(
            f"internal:{service}",
            f"{spec['name']} (Internal Docker)",
            "internal",
            primary_url,
            True,
            "skipped",
            False,
            total_ms,
            "Internal Docker DNS unavailable from host outside stremio-net",
        )

    return _make_check(
        f"internal:{service}",
        f"{spec['name']} (Internal Docker)",
        "internal",
        primary_url,
        False,
        "fail",
        spec["critical"],
        total_ms,
        last_detail or "Unreachable",
        f"Ensure container '{service}' is running and healthy on stremio-net port {internal_port}.",
    )


def _check_host_port(service: str, env_vars: dict, timeout: float, inside_container: bool, internal_ok: bool) -> dict:
    spec = SERVICE_REACHABILITY_SPECS.get(service, {"name": "Portal", "path": "/healthz", "critical": True})
    _, host_port = _service_ports(service, env_vars)
    path = spec["path"]
    primary_target = f"127.0.0.1:{host_port}"
    http_url = f"http://{primary_target}{path}"

    ok, _, ms, detail, _ = _probe_http(http_url, timeout=timeout)
    if ok:
        return _make_check(
            f"host:{service}",
            f"{spec['name']} Host Port (:{host_port})",
            "host_port",
            http_url,
            True,
            "ok",
            spec["critical"],
            ms,
            detail,
        )

    # Fallback TCP probe on 127.0.0.1 (some services return 404/401 or non-HTTP on root)
    tcp_ok, tcp_ms, tcp_detail, _ = _probe_tcp("127.0.0.1", host_port, timeout=min(timeout, 1.5))
    if tcp_ok:
        return _make_check(
            f"host:{service}",
            f"{spec['name']} Host Port (:{host_port})",
            "host_port",
            primary_target,
            True,
            "ok",
            spec["critical"],
            tcp_ms,
            tcp_detail,
        )

    # Inside a bridge container, host-published ports on 0.0.0.0 are reached via host.docker.internal
    if inside_container and service in ALL_INTERFACE_SERVICES:
        gw_url = f"http://host.docker.internal:{host_port}{path}"
        gw_ok, _, gw_ms, gw_detail, _ = _probe_http(gw_url, timeout=timeout)
        if gw_ok:
            return _make_check(
                f"host:{service}",
                f"{spec['name']} Host Port (:{host_port})",
                "host_port",
                gw_url,
                True,
                "ok",
                spec["critical"],
                gw_ms,
                gw_detail,
            )

    if inside_container and service not in ALL_INTERFACE_SERVICES and internal_ok:
        return _make_check(
            f"host:{service}",
            f"{spec['name']} Host Port (:{host_port})",
            "host_port",
            primary_target,
            True,
            "skipped",
            False,
            ms,
            "Loopback-bound on Docker host (verified via internal network)",
        )

    return _make_check(
        f"host:{service}",
        f"{spec['name']} Host Port (:{host_port})",
        "host_port",
        http_url,
        False,
        "fail",
        spec["critical"],
        ms,
        detail or tcp_detail,
        f"Verify '{service}' host port mapping :{host_port} in Docker Compose and check container logs.",
    )


def _check_portal_routes(portal_base_url: str, timeout: float) -> list[dict]:
    base = portal_base_url.rstrip("/")
    routes = [
        ("/healthz", "Portal Health (/healthz)", True, (200,)),
        ("/ready", "Portal Readiness (/ready)", True, (200,)),
        ("/watch/", "Portal Watch Alias (/watch/)", False, (200, 302, 503)),
    ]
    checks = []
    for path, label, required, expected_codes in routes:
        url = f"{base}{path}"
        ok, code, ms, detail, _ = _probe_http(url, timeout=timeout, follow_redirects=False)
        if code is not None and code in expected_codes:
            if path == "/watch/" and code == 503:
                checks.append(_make_check(
                    f"portal:{path}",
                    label,
                    "portal",
                    url,
                    True,
                    "warn",
                    False,
                    ms,
                    "HTTP 503 (Setup incomplete or Jellyfin disabled)",
                    "Complete initial stack setup so /watch/ has AIOStreams credentials.",
                ))
            else:
                checks.append(_make_check(f"portal:{path}", label, "portal", url, True, "ok", required, ms, detail))
        elif code == 503 and path == "/ready":
            checks.append(_make_check(
                f"portal:{path}",
                label,
                "portal",
                url,
                False,
                "fail",
                required,
                ms,
                detail,
                "AIOStreams dependency is not ready yet; wait for aiostreams healthcheck.",
            ))
        else:
            checks.append(_make_check(
                f"portal:{path}",
                label,
                "portal",
                url,
                False,
                "fail",
                required,
                ms,
                detail,
                f"Check portal server route {path} on {base}.",
            ))
    return checks


def _check_cloudflare_origin(
    env_vars: dict,
    origin_url: str | None,
    timeout: float,
    inside_container: bool,
) -> tuple[dict, dict]:
    containers = check_cloudflare_containers()
    topology = recommend_cloudflare_origin(containers, env_vars=env_vars)
    recommended = topology["recommended_origin"]
    connector_mode = topology["connector_mode"]
    aio_port = topology["aiostreams_port"]

    if origin_url and str(origin_url).strip():
        try:
            target_origin = validate_service_url(str(origin_url))
        except ValueError as exc:
            chk = _make_check(
                "cloudflare:origin",
                "Cloudflare Tunnel Origin Target",
                "cloudflare",
                str(origin_url),
                False,
                "fail",
                True,
                None,
                str(exc),
                f"Set a valid origin URL such as {recommended}.",
            )
            return chk, topology
    else:
        target_origin = topology.get("detected_origin") or recommended

    parsed = urllib.parse.urlsplit(target_origin)
    host = (parsed.hostname or "").lower()
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    # Explicitly flag unreachable aiostreams:3000 when connector is external / outside stremio-net
    if host == "aiostreams" and port == 3000 and connector_mode != "local_tunnel":
        chk = _make_check(
            "cloudflare:origin",
            "Cloudflare Tunnel Origin Target",
            "cloudflare",
            target_origin,
            False,
            "fail",
            True,
            None,
            "Origin 'http://aiostreams:3000' only resolves inside Docker network stremio-net; external connectors cannot reach it.",
            f"Update Cloudflare Tunnel Public Hostname service URL to {recommended} (port {aio_port}).",
        )
        return chk, topology

    # Explicitly flag wrong port :3000 on host/bridge addresses when AIOStreams is published on :3001
    if host in ("localhost", "127.0.0.1", "host.docker.internal") and port == 3000 and aio_port != 3000:
        chk = _make_check(
            "cloudflare:origin",
            "Cloudflare Tunnel Origin Target",
            "cloudflare",
            target_origin,
            False,
            "fail",
            True,
            None,
            f"Origin '{target_origin}' targets port 3000, but AIOStreams is mapped on host port {aio_port}.",
            f"Update Cloudflare Tunnel Public Hostname service URL to {recommended}.",
        )
        return chk, topology

    probe_url = f"{target_origin.rstrip('/')}/api/v1/status"
    ok, _, ms, detail, exc = _probe_http(probe_url, timeout=timeout)
    if ok:
        chk = _make_check(
            "cloudflare:origin",
            "Cloudflare Tunnel Origin Target",
            "cloudflare",
            target_origin,
            True,
            "ok",
            True,
            ms,
            f"Reachable ({detail})",
        )
        return chk, topology

    # Fallback when portal container checks host.docker.internal or loopback (127.0.0.1/localhost) from inside container
    if inside_container and host in ("host.docker.internal", "127.0.0.1", "localhost") and port == aio_port:
        if exc is not None and _is_connect_or_dns_error(exc):
            if host in ("127.0.0.1", "localhost"):
                gw_url = f"http://host.docker.internal:{aio_port}/api/v1/status"
                gw_ok, _, gw_ms, gw_detail, gw_exc = _probe_http(gw_url, timeout=timeout)
                if gw_ok:
                    chk = _make_check(
                        "cloudflare:origin",
                        "Cloudflare Tunnel Origin Target",
                        "cloudflare",
                        target_origin,
                        True,
                        "ok",
                        True,
                        gw_ms,
                        f"Host port :{aio_port} reachable via host.docker.internal ({gw_detail}); container loopback differs from host loopback",
                    )
                    return chk, topology
                if gw_exc is not None and isinstance(gw_exc, urllib.error.HTTPError):
                    chk = _make_check(
                        "cloudflare:origin",
                        "Cloudflare Tunnel Origin Target",
                        "cloudflare",
                        target_origin,
                        False,
                        "fail",
                        True,
                        gw_ms,
                        gw_detail,
                        f"AIOStreams on port {aio_port} returned {gw_detail}; check AIOStreams container health and logs.",
                    )
                    return chk, topology

            fb_ok, _, fb_ms, fb_detail, _ = _probe_http("http://aiostreams:3000/api/v1/status", timeout=timeout)
            if fb_ok:
                chk = _make_check(
                    "cloudflare:origin",
                    "Cloudflare Tunnel Origin Target",
                    "cloudflare",
                    target_origin,
                    True,
                    "warn",
                    False,
                    fb_ms,
                    f"Target {target_origin} was not directly reachable from inside aio-portal container; internal AIOStreams is up on stremio-net ({fb_detail})",
                    f"Ensure your external Cloudflare connector can reach '{host}:{port}' (or use host LAN IP :{aio_port}).",
                )
                return chk, topology

    chk = _make_check(
        "cloudflare:origin",
        "Cloudflare Tunnel Origin Target",
        "cloudflare",
        target_origin,
        False,
        "fail",
        True,
        ms,
        detail,
        f"Ensure AIOStreams is running on port {aio_port} and set Cloudflare Public Hostname to {recommended}.",
    )
    return chk, topology


def _check_remote_urls(env_vars: dict, timeout: float) -> list[dict]:
    checks = []
    base_url = (env_vars.get("BASE_URL") or os.environ.get("BASE_URL") or "").strip().rstrip("/")
    aiom_host = (env_vars.get("AIOMETADATA_HOST") or os.environ.get("AIOMETADATA_HOST") or "").strip().rstrip("/")

    if _is_public_url(base_url):
        target = f"{base_url}/api/v1/status"
        ok, code, ms, detail, _ = _probe_http(target, timeout=timeout, follow_redirects=True)
        if ok:
            checks.append(_make_check("remote:base_url", "Public BASE_URL", "remote", base_url, True, "ok", False, ms, detail))
        else:
            checks.append(_make_check(
                "remote:base_url",
                "Public BASE_URL",
                "remote",
                base_url,
                False,
                "fail",
                False,
                ms,
                detail,
                "Verify Cloudflare DNS CNAME, tunnel connector status, and that Public Hostname points to port 3001 (not aiostreams:3000) for external connectors.",
            ))
    else:
        checks.append(_make_check(
            "remote:base_url",
            "Public BASE_URL",
            "remote",
            base_url or "unset",
            True,
            "skipped",
            False,
            None,
            "No public BASE_URL configured (local access mode)",
        ))

    if _is_public_url(aiom_host):
        target = f"{aiom_host}/health/live"
        ok, _, ms, detail, _ = _probe_http(target, timeout=timeout, follow_redirects=True)
        if ok:
            checks.append(_make_check("remote:aiometadata", "Public AIOMetadata Host", "remote", aiom_host, True, "ok", False, ms, detail))
        else:
            checks.append(_make_check(
                "remote:aiometadata",
                "Public AIOMetadata Host",
                "remote",
                aiom_host,
                False,
                "warn",
                False,
                ms,
                detail,
                "Optional: only required for remote native Stremio apps. Point AIOMetadata Public Hostname to port 4005.",
            ))
    return checks


def _parse_mem_limit_mb(raw) -> int | None:
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if not text:
        return None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([kmg]?i?b?)?", text)
    if not m:
        return None
    val = float(m.group(1))
    unit = (m.group(2) or "").rstrip("b").rstrip("i")
    if unit == "g":
        return int(val * 1024)
    if unit == "m":
        return int(val)
    if unit == "k":
        return max(1, int(val // 1024))
    if val >= 1024 * 1024:
        return int(val // (1024 * 1024))
    return int(val)


def _probe_http_details(url: str, headers: dict = None, timeout: float = 2.5) -> tuple[bool, int | None, float, dict, bytes, str]:
    """Probe an HTTP(S) URL without following redirects, returning headers and body snippet."""
    t0 = time.monotonic()
    req_headers = {"User-Agent": "AIO-Reachability/1.0", "Accept-Encoding": "identity"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    try:
        with _NO_REDIRECT_OPENER.open(req, timeout=timeout) as resp:
            code = getattr(resp, "status", 200) or 200
            body = resp.read(16384)
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            ms = round((time.monotonic() - t0) * 1000, 1)
            return (code < 500), code, ms, resp_headers, body, f"HTTP {code}"
    except urllib.error.HTTPError as err:
        ms = round((time.monotonic() - t0) * 1000, 1)
        body = b""
        try:
            body = err.read(4096)
        except Exception:
            pass
        resp_headers = {k.lower(): v for k, v in err.headers.items()} if err.headers else {}
        return (err.code < 500), err.code, ms, resp_headers, body, f"HTTP {err.code}"
    except Exception as exc:
        ms = round((time.monotonic() - t0) * 1000, 1)
        reason = getattr(exc, "reason", None)
        return False, None, ms, {}, b"", f"{type(exc).__name__}: {reason or exc}"


def _probe_http_keepalive(target_origin: str, path: str = "/api/v1/health", timeout: float = 2.5) -> tuple[bool, float, str]:
    """Send two sequential HTTP/1.1 requests over one socket to confirm keep-alive connection reuse."""
    parsed = urllib.parse.urlsplit(target_origin)
    host = parsed.hostname
    if not host:
        return False, 0.0, "Invalid origin URL for keep-alive probe"
    is_https = parsed.scheme == "https"
    port = parsed.port or (443 if is_https else 80)
    t0 = time.monotonic()
    conn = None
    try:
        conn = http.client.HTTPSConnection(host, port, timeout=timeout) if is_https else http.client.HTTPConnection(host, port, timeout=timeout)
        headers = {"Connection": "keep-alive", "User-Agent": "AIO-Reachability/1.0"}
        conn.request("GET", path, headers=headers)
        r1 = conn.getresponse()
        r1.read()
        if r1.status >= 500:
            ms = round((time.monotonic() - t0) * 1000, 1)
            return False, ms, f"First request returned HTTP {r1.status}"
        conn_tokens = [t.strip() for t in (r1.getheader("Connection") or "").lower().split(",") if t.strip()]
        if r1.will_close or "close" in conn_tokens:
            ms = round((time.monotonic() - t0) * 1000, 1)
            return False, ms, "Origin closed HTTP/1.1 connection instead of keeping alive"
        conn.request("GET", path, headers=headers)
        r2 = conn.getresponse()
        r2.read()
        ms = round((time.monotonic() - t0) * 1000, 1)
        if r2.status >= 500:
            return False, ms, f"Reused keep-alive request returned HTTP {r2.status}"
        return True, ms, f"HTTP/1.1 keep-alive reused cleanly ({r1.status}, {r2.status})"
    except Exception as exc:
        ms = round((time.monotonic() - t0) * 1000, 1)
        return False, ms, f"{type(exc).__name__}: {exc}"
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def check_streaming_and_cloudflare_health(
    env_vars: dict = None,
    origin_url: str = None,
    timeout: float = 2.5,
) -> list[dict]:
    """Verify memory headroom, proxy URL consistency, keep-alive reuse, Jellyfin Web headers, and Usenet stream route."""
    env_map = dict(env_vars) if isinstance(env_vars, dict) else {}
    topology = recommend_cloudflare_origin(env_vars=env_map)
    recommended = topology["recommended_origin"]
    raw_origin = str(origin_url).strip() if origin_url and str(origin_url).strip() else (topology.get("detected_origin") or recommended)
    try:
        target_origin = validate_service_url(str(raw_origin))
    except ValueError as exc:
        return [_make_check(
            "stream:origin",
            "Streaming Origin URL",
            "streaming",
            str(raw_origin),
            False,
            "fail",
            True,
            None,
            str(exc),
            f"Set a valid origin URL such as {recommended}.",
        )]

    checks = []
    usenet_enabled = str(env_map.get("USENET_ENABLED") or os.environ.get("USENET_ENABLED") or "false").strip().lower() == "true"
    raw_mem = env_map.get("AIOSTREAMS_MEM_LIMIT") or os.environ.get("AIOSTREAMS_MEM_LIMIT") or "1024m"
    mem_mb = _parse_mem_limit_mb(raw_mem)
    if usenet_enabled and mem_mb is not None and mem_mb <= 512:
        checks.append(_make_check(
            "stream:memory",
            "AIOStreams Memory Limit",
            "streaming",
            str(raw_mem),
            False,
            "fail",
            True,
            None,
            f"AIOSTREAMS_MEM_LIMIT={raw_mem} is too small for native Usenet NNTP/yEnc buffering (~305 MiB idle baseline)",
            "Set AIOSTREAMS_MEM_LIMIT=1024m (or higher) and USENET_PERFORMANCE_PROFILE=conservative.",
        ))
    else:
        checks.append(_make_check(
            "stream:memory",
            "AIOStreams Memory Limit",
            "streaming",
            str(raw_mem),
            True,
            "ok",
            False,
            None,
            f"Configured memory limit {raw_mem} has sufficient headroom",
        ))

    base_url = (env_map.get("BASE_URL") or os.environ.get("BASE_URL") or "http://localhost:3001").strip().rstrip("/")
    force_proxy_url = (env_map.get("FORCE_PROXY_URL") or os.environ.get("FORCE_PROXY_URL") or base_url).strip().rstrip("/")
    cf_public_host = (env_map.get("CLOUDFLARE_PUBLIC_HOST") or os.environ.get("CLOUDFLARE_PUBLIC_HOST") or "").strip()
    aio_port = topology.get("aiostreams_port", 3001)
    force_parsed = urllib.parse.urlsplit(force_proxy_url) if "://" in force_proxy_url else None
    if force_parsed and (force_parsed.hostname or "").lower() in ("localhost", "127.0.0.1", "aiostreams") and force_parsed.port == 3000 and aio_port != 3000:
        checks.append(_make_check(
            "stream:proxy_urls",
            "Stream & Proxy Base URL",
            "streaming",
            force_proxy_url,
            False,
            "fail",
            True,
            None,
            f"FORCE_PROXY_URL '{force_proxy_url}' targets port 3000 while AIOStreams is mapped on {aio_port}",
            f"Update FORCE_PROXY_URL and BASE_URL to match port {aio_port} or your public HTTPS domain.",
        ))
    elif usenet_enabled and (cf_public_host or topology.get("detected_origin")) and not _is_public_url(base_url):
        checks.append(_make_check(
            "stream:proxy_urls",
            "Stream & Proxy Base URL",
            "streaming",
            base_url,
            True,
            "warn",
            False,
            None,
            f"BASE_URL is '{base_url}' while Cloudflare routing is configured; native Usenet stream URLs use BASE_URL",
            "Set BASE_URL=https://<your-cloudflare-domain> in .env so Usenet and BuiltinProxy stream URLs route via HTTPS.",
        ))
    else:
        checks.append(_make_check(
            "stream:proxy_urls",
            "Stream & Proxy Base URL",
            "streaming",
            base_url,
            True,
            "ok",
            False,
            None,
            f"BASE_URL ({base_url}) and FORCE_PROXY_URL ({force_proxy_url}) are aligned",
        ))

    ka_ok, ka_ms, ka_detail = _probe_http_keepalive(target_origin, timeout=timeout)
    checks.append(_make_check(
        "stream:keepalive",
        "Origin HTTP Keep-Alive Reuse",
        "cloudflare",
        target_origin,
        ka_ok,
        "ok" if ka_ok else "fail",
        True,
        ka_ms,
        ka_detail,
        None if ka_ok else "Ensure AIOStreams entrypoint tunes server.keepAliveTimeout above Cloudflare Tunnel keepAliveTimeout (120s > 60s).",
    ))

    base_parsed = urllib.parse.urlsplit(base_url) if "://" in base_url else None
    fwd_headers = {}
    expect_https_origin = False
    if _is_public_url(base_url) and base_parsed and base_parsed.hostname:
        fwd_headers = {
            "Host": base_parsed.netloc,
            "X-Forwarded-Proto": base_parsed.scheme or "https",
        }
        expect_https_origin = (base_parsed.scheme == "https")

    jellyfin_enabled = str(env_map.get("JELLYFIN_ENABLED") or os.environ.get("JELLYFIN_ENABLED") or "true").strip().lower() != "false"
    if not jellyfin_enabled:
        checks.append(_make_check(
            "cloudflare:jellyfin_web",
            "Jellyfin Web & Forwarded Headers",
            "cloudflare",
            f"{target_origin.rstrip('/')}/jellyfin/web/",
            True,
            "skipped",
            False,
            None,
            "Jellyfin Web Player is disabled (JELLYFIN_ENABLED=false)",
        ))
    else:
        web_ok, web_code, web_ms, _, _, web_detail = _probe_http_details(
            f"{target_origin.rstrip('/')}/jellyfin/web/", headers=fwd_headers, timeout=timeout
        )
        info_ok, _, info_ms, _, info_body, info_detail = _probe_http_details(
            f"{target_origin.rstrip('/')}/jellyfin/System/Info/Public", headers=fwd_headers, timeout=timeout
        )
        jf_ok = bool(web_ok and web_code == 200 and info_ok)
        jf_detail = f"/jellyfin/web/ {web_detail}, /System/Info/Public {info_detail}"
        jf_rem = None
        if jf_ok and expect_https_origin:
            try:
                info_json = json.loads(info_body.decode("utf-8", errors="replace"))
                local_addr = str(info_json.get("LocalAddress") or "")
                if not local_addr.startswith("https://"):
                    jf_ok = False
                    jf_detail = f"Expected HTTPS LocalAddress behind X-Forwarded-Proto=https, got '{local_addr}'"
                    jf_rem = "Ensure TRUSTED_IPS includes your Cloudflare connector (loopback,linklocal,uniquelocal)."
            except Exception as exc:
                jf_ok = False
                jf_detail = f"Invalid JSON from /jellyfin/System/Info/Public: {exc}"
        elif not jf_ok:
            jf_rem = "Check AIOStreams Jellyfin Web routing and forwarded-header trust settings."

        checks.append(_make_check(
            "cloudflare:jellyfin_web",
            "Jellyfin Web & Forwarded Headers",
            "cloudflare",
            f"{target_origin.rstrip('/')}/jellyfin/web/",
            jf_ok,
            "ok" if jf_ok else "fail",
            True,
            round((web_ms + info_ms) / 2, 1),
            jf_detail,
            jf_rem,
        ))

    if usenet_enabled:
        u_ok, u_code, u_ms, _, _, u_detail = _probe_http_details(
            f"{target_origin.rstrip('/')}/api/v1/usenet/stream/reachability-probe",
            headers=fwd_headers,
            timeout=timeout,
        )
        route_ok = bool(u_ok and u_code is not None and u_code < 500 and u_code != 404)
        checks.append(_make_check(
            "stream:usenet_route",
            "Native Usenet Stream Route",
            "streaming",
            f"{target_origin.rstrip('/')}/api/v1/usenet/stream/",
            route_ok,
            "ok" if route_ok else "fail",
            True,
            u_ms,
            u_detail,
            None if route_ok else "Verify AIOStreams /api/v1/usenet/stream endpoint and container health.",
        ))

    return checks


def run_reachability_checks(
    env_vars: dict = None,
    origin_url: str = None,
    portal_base_url: str = None,
    include_internal: bool = True,
    include_host_ports: bool = True,
    include_portal: bool = True,
    include_cloudflare: bool = True,
    include_remote: bool = True,
    include_streaming: bool = True,
    timeout: float = 2.5,
) -> dict:
    """Run comprehensive stack and Cloudflare origin reachability checks."""
    env_map = dict(env_vars) if isinstance(env_vars, dict) else {}
    inside_container = _in_container()
    services = active_reachability_services(env_map)
    checks = []

    internal_results = {}
    if include_internal:
        with ThreadPoolExecutor(max_workers=8) as pool:
            internal_list = list(pool.map(
                lambda svc: _check_internal_service(svc, env_map, timeout, inside_container),
                services,
            ))
        for item in internal_list:
            svc = item["id"].split(":", 1)[1]
            internal_results[svc] = item["ok"]
            checks.append(item)

    if include_host_ports:
        exposed = ["portal"] + [svc for svc in services if svc in HOST_EXPOSED_SERVICES]
        with ThreadPoolExecutor(max_workers=8) as pool:
            host_list = list(pool.map(
                lambda svc: _check_host_port(
                    svc,
                    env_map,
                    timeout,
                    inside_container,
                    internal_results.get(svc, False),
                ),
                exposed,
            ))
        checks.extend(host_list)

    if include_portal:
        _, portal_port = _service_ports("portal", env_map)
        base = portal_base_url or f"http://127.0.0.1:{portal_port}"
        checks.extend(_check_portal_routes(base, timeout))

    topology = None
    if include_cloudflare:
        cf_check, topology = _check_cloudflare_origin(env_map, origin_url, timeout, inside_container)
        checks.append(cf_check)
    else:
        topology = recommend_cloudflare_origin(env_vars=env_map)

    if include_remote:
        checks.extend(_check_remote_urls(env_map, timeout))

    if include_streaming:
        checks.extend(check_streaming_and_cloudflare_health(env_map, origin_url=origin_url, timeout=timeout))

    passed = sum(1 for c in checks if c["status"] == "ok")
    failed = sum(1 for c in checks if c["status"] == "fail")
    warnings = sum(1 for c in checks if c["status"] == "warn")
    skipped = sum(1 for c in checks if c["status"] == "skipped")
    overall_ok = failed == 0

    return {
        "success": True,
        "ok": overall_ok,
        "status": "ok" if overall_ok else "fail",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "recommended_origin": topology.get("recommended_origin"),
        "connector_mode": topology.get("connector_mode"),
        "summary": {
            "total": len(checks),
            "passed": passed,
            "failed": failed,
            "warnings": warnings,
            "skipped": skipped,
        },
        "checks": checks,
    }
