"""Read-only internal endpoint checks; run via docker compose --profile test run --rm stack-check."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import socket
import sys
import urllib.request

from init.service_inventory import TCP_PORTS

HTTP_CHECKS = {
    "portal": ("http://portal:8088/healthz", False),
    "aiostreams": ("http://aiostreams:3000/api/v1/status", False),
    "anime-kitsu": ("http://anime-kitsu:7000/manifest.json", True),
    "aiometadata": ("http://aiometadata:4005/health/live", False),
    "prowlarr": ("http://prowlarr:9696/ping", False),
}
TCP_CHECKS = {"shared-postgres": 5432, "shared-redis": 6379, **{
    host: TCP_PORTS[host] for host in (
        "stremthru", "flaresolverr", "subsense",
        "postersplus", "zilean",
    )
}}


ANIME_PROFILES = {"anime", "anime-db", "scrapers", "all"}


def parse_profiles(raw_profiles):
    cleaned = (raw_profiles or "core").split("#", 1)[0].strip().strip("\"'")
    profiles = {p.strip().strip("\"'").lower() for p in cleaned.split(",") if p.strip().strip("\"'")}
    return profiles or {"core"}


def active_checks(profiles=None):
    selected = parse_profiles(os.environ.get("COMPOSE_PROFILES")) if profiles is None else profiles
    http_names = [
        name for name in HTTP_CHECKS
        if name != "anime-kitsu" or bool(selected.intersection(ANIME_PROFILES))
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


if __name__ == "__main__":
    checks = active_checks()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(check, checks))
    for name, passed, detail in results:
        print(f"{name}: {'PASS' if passed else 'FAIL'} ({detail})")
    print(f"{sum(item[1] for item in results)}/{len(results)} internal endpoint checks passed.")
    sys.exit(0 if all(item[1] for item in results) else 1)
