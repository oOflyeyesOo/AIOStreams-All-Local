"""Read-only internal endpoint checks; run via docker compose --profile test run --rm stack-check."""
from concurrent.futures import ThreadPoolExecutor
import json
import socket
import sys
import urllib.request

HTTP_CHECKS = {
    "portal": ("http://portal:8088/healthz", False),
    "aiostreams": ("http://aiostreams:3000/api/v1/status", False),
    "comet": ("http://comet:8000/manifest.json", True),
    "mediafusion": ("http://mediafusion:8000/manifest.json", True),
    "anime-kitsu": ("http://anime-kitsu:7000/manifest.json", True),
    "aiometadata": ("http://aiometadata:4005/health/live", False),
    "infinidysk": ("http://infinidysk:3000/healthz", False),
    "prowlarr": ("http://prowlarr:9696/ping", False),
    "stremio-web": ("http://stremio-web:8080/", False),
}
TCP_CHECKS = {"shared-postgres": 5432, "shared-redis": 6379,
              "stremthru": 8080, "mediaflow": 8888, "flaresolverr": 8191,
              "subsense": 3100, "debrid-search": 3001, "postersplus": 8000,
              "sootio": 55771, "slicksync": 3000, "nuvio": 3000, "zilean": 8181}


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
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(check, list(HTTP_CHECKS) + list(TCP_CHECKS)))
    for name, passed, detail in results:
        print(f"{name}: {'PASS' if passed else 'FAIL'} ({detail})")
    print(f"{sum(item[1] for item in results)}/{len(results)} internal endpoint checks passed.")
    sys.exit(0 if all(item[1] for item in results) else 1)
