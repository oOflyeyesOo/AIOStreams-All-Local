"""Read-only internal, host-port, portal-route, and Cloudflare origin reachability checks.

Run inside Compose test profile (`docker compose --profile test run --rm stack-check`)
or directly on the host (`python tests/check_stack.py --full`).
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

from init.service_inventory import SERVICE_PORT_MAP, TCP_PORTS

HTTP_CHECKS = {
    "portal": ("http://portal:8088/healthz", False),
    "aiostreams": ("http://aiostreams:3000/api/v1/status", False),
    "anime-kitsu": ("http://anime-kitsu:7000/manifest.json", True),
    "aiometadata": ("http://aiometadata:4005/health/live", False),
    "prowlarr": ("http://prowlarr:9696/ping", False),
    "jikan-api": ("http://jikan-api:8080/v4", False),
}
TCP_CHECKS = {"shared-postgres": 5432, "shared-redis": 6379, **{
    host: TCP_PORTS[host] for host in (
        "stremthru", "flaresolverr", "subsense",
        "postersplus", "zilean", "lumiere-db",
    )
}}

HOST_PORT_CHECKS = {
    "portal": ("/healthz", 8088, "PORT_PORTAL"),
    "aiostreams": ("/api/v1/status", SERVICE_PORT_MAP["aiostreams"][1], SERVICE_PORT_MAP["aiostreams"][2]),
    "aiometadata": ("/health/live", SERVICE_PORT_MAP["aiometadata"][1], SERVICE_PORT_MAP["aiometadata"][2]),
}

PORTAL_ROUTE_CHECKS = (
    ("/healthz", (200,)),
    ("/ready", (200,)),
    ("/watch/", (200, 302, 503)),
)


ANIME_PROFILES = {"anime", "anime-db", "scrapers", "all"}
JIKAN_PROFILES = {"anime", "anime-db", "all"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirect)


def parse_profiles(raw_profiles):
    cleaned = (raw_profiles or "core").split("#", 1)[0].strip().strip("\"'")
    profiles = {p.strip().strip("\"'").lower() for p in cleaned.split(",") if p.strip().strip("\"'")}
    return profiles or {"core"}


def active_checks(profiles=None):
    selected = parse_profiles(os.environ.get("COMPOSE_PROFILES")) if profiles is None else profiles
    http_names = [
        name for name in HTTP_CHECKS
        if (name != "anime-kitsu" or bool(selected.intersection(ANIME_PROFILES)))
        and (name != "jikan-api" or bool(selected.intersection(JIKAN_PROFILES)))
    ]
    return http_names + list(TCP_CHECKS)


def check(name):
    try:
        if name in HTTP_CHECKS:
            url, manifest = HTTP_CHECKS[name]
            with urllib.request.urlopen(url, timeout=10) as response:
                if manifest:
                    data = json.load(response)
                    if not isinstance(data, dict) or not data.get("id") or not data.get("resources"):
                        raise ValueError("Invalid Stremio manifest")
        else:
            with socket.create_connection((name, TCP_CHECKS[name]), timeout=5):
                pass
        return name, True, "HTTP/manifest passed" if name in HTTP_CHECKS else "TCP reachable"
    except Exception as error:
        return name, False, type(error).__name__


def check_host_port(name, host="127.0.0.1"):
    path, default_port, env_var = HOST_PORT_CHECKS[name]
    try:
        port = int(os.environ.get(env_var) or default_port)
    except (TypeError, ValueError):
        port = default_port
    url = f"http://{host}:{port}{path}"
    try:
        with _NO_REDIRECT_OPENER.open(url, timeout=5) as response:
            code = getattr(response, "status", 200) or 200
            return f"host:{name}:{port}", code < 500, f"HTTP {code}"
    except urllib.error.HTTPError as err:
        return f"host:{name}:{port}", err.code < 500, f"HTTP {err.code}"
    except Exception as error:
        return f"host:{name}:{port}", False, type(error).__name__


def check_portal_route(route_path, expected_codes, base_url=None):
    portal_port = os.environ.get("PORT_PORTAL", "8088")
    root = (base_url or os.environ.get("PORTAL_URL") or f"http://127.0.0.1:{portal_port}").rstrip("/")
    url = f"{root}{route_path}"
    try:
        with _NO_REDIRECT_OPENER.open(url, timeout=5) as response:
            code = getattr(response, "status", 200) or 200
            return f"portal:{route_path}", code in expected_codes, f"HTTP {code}"
    except urllib.error.HTTPError as err:
        return f"portal:{route_path}", err.code in expected_codes, f"HTTP {err.code}"
    except Exception as error:
        return f"portal:{route_path}", False, type(error).__name__


def check_cloudflare_origin(origin_url=None):
    target = (origin_url or os.environ.get("CLOUDFLARE_ORIGIN_URL") or "").strip()
    if not target:
        try:
            from tools.cloudflare_helper import recommend_cloudflare_origin
            target = recommend_cloudflare_origin()["recommended_origin"]
        except Exception:
            aio_port = os.environ.get("PORT_AIOSTREAMS", "3001")
            target = f"http://127.0.0.1:{aio_port}"
    parsed = urllib.parse.urlsplit(target)
    if (parsed.hostname or "").lower() == "aiostreams" and parsed.port == 3000 and not os.path.exists("/.dockerenv"):
        return f"cloudflare-origin:{target}", False, "aiostreams:3000 unreachable outside stremio-net (use :3001)"
    status_url = f"{target.rstrip('/')}/api/v1/status"
    try:
        with _NO_REDIRECT_OPENER.open(status_url, timeout=5) as response:
            code = getattr(response, "status", 200) or 200
            return f"cloudflare-origin:{target}", code < 500, f"HTTP {code}"
    except urllib.error.HTTPError as err:
        return f"cloudflare-origin:{target}", err.code < 500, f"HTTP {err.code}"
    except Exception as error:
        return f"cloudflare-origin:{target}", False, type(error).__name__


def run_stack_checks(mode="internal", host="127.0.0.1", portal_url=None, origin_url=None):
    results = []
    if mode in ("internal", "full"):
        checks = active_checks()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results.extend(pool.map(check, checks))
    if mode in ("host", "full"):
        for svc in HOST_PORT_CHECKS:
            results.append(check_host_port(svc, host=host))
        default_portal = portal_url or ("http://portal:8088" if mode == "internal" else f"http://{host}:{os.environ.get('PORT_PORTAL', '8088')}")
        for route_path, expected in PORTAL_ROUTE_CHECKS:
            results.append(check_portal_route(route_path, expected, base_url=default_portal))
        results.append(check_cloudflare_origin(origin_url=origin_url))
    elif mode == "internal":
        results.append(check_portal_route("/ready", (200,), base_url="http://portal:8088"))
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verify AIOStreams stack reachability.")
    parser.add_argument(
        "--mode",
        choices=("internal", "host", "full"),
        default=os.environ.get("STACK_CHECK_MODE", "internal"),
        help="Check mode: internal (Compose network), host (published ports + CF origin), or full (both).",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host address for published port checks.")
    parser.add_argument("--portal-url", default=None, help="Explicit portal base URL for route checks.")
    parser.add_argument("--origin-url", default=None, help="Explicit Cloudflare origin URL to probe.")
    args = parser.parse_args(argv)

    results = run_stack_checks(
        mode=args.mode,
        host=args.host,
        portal_url=args.portal_url,
        origin_url=args.origin_url,
    )
    for name, passed, detail in results:
        print(f"{name}: {'PASS' if passed else 'FAIL'} ({detail})")
    print(f"{sum(item[1] for item in results)}/{len(results)} stack reachability checks passed.")
    return 0 if all(item[1] for item in results) else 1


if __name__ == "__main__":
    sys.exit(main())
