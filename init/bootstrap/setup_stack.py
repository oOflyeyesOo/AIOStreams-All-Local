#!/usr/bin/env python3
"""
AIOStreams All-Local Unified Stack Bootstrapper & Auto-Provisioner
Automates zero-touch configuration across all stack services upon launch:
1. Prowlarr: Registers FlareSolverr Cloudflare bypass and auto-seeds top public torrent trackers.
2. Usenet: Synchronizes native Usenet provider credentials with AIOStreams.
3. AIOStreams: Automatically compiles and registers our ready-to-stream 'All-Local Self-Hosted'
   template (Prowlarr, Knaben, Torrentio, AIOMetadata, SubSense,
   and StremThru Store) with Debrid & Usenet credentials, mapped to alias '/stremio/u/local/manifest.json'.
4. Diagnostic Verification: Tests manifest and stream resolution on the internal Stremio engine.
"""
import os
import sys
import time
import json
import hashlib
import base64
import builtins
import re
import urllib.request
import urllib.error
import urllib.parse
import tempfile
import copy
import socket
import ipaddress
from pathlib import Path

# Source Compose mounts the checkout at /app and the entry script at /init.
# The packaged bootstrap places the shared module beside the entry script.
for parent in (*Path(__file__).resolve().parents, Path('/app')):
    if (parent / 'tools' / 'usenet_config.py').is_file():
        sys.path.insert(0, str(parent))
        break
from tools.usenet_config import newznab_indexers, newznab_endpoint, credential, extra_sources

def load_env_file():
    if os.environ.get("AIO_SKIP_ENV_FILE") == "true":
        return
    for candidate in [
        os.path.join(os.getcwd(), ".env"),
        "/app/.env",
        os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
    ]:
        if os.path.isfile(candidate):
            try:
                with open(candidate, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip('"').strip("'")
                            if k and (k not in os.environ or not os.environ[k]):
                                os.environ[k] = v
            except Exception:
                pass
            break

if __name__ == "__main__":
    load_env_file()


def print(*values, **kwargs):
    """Keep provider keys and install tokens out of bootstrap container logs."""
    message = kwargs.pop("sep", " ").join(str(value) for value in values)
    for name, value in os.environ.items():
        if len(value) >= 6 and any(part in name for part in ("KEY", "PASSWORD", "TOKEN", "ENCRYPTED", "MANIFEST_URL", "USENET_PASS", "USENET_USER")):
            message = message.replace(value, "[REDACTED]")
    message = re.sub(r"(/stremio/)[^/\s]+/[^/\s]+", r"\1[REDACTED]", message)
    # Encode safely when stdout uses a narrow codec (e.g. cp1252 on Windows).
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        message.encode(enc)
    except (UnicodeEncodeError, LookupError):
        message = message.encode(enc, errors="replace").decode(enc, errors="replace")
    builtins.print(message, **kwargs)

def update_env_file(key, value, candidates=None):
    candidates = candidates or [
        "/app/.env",
        os.path.join(os.getcwd(), ".env"),
        os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".env")),
        "/data/.env"
    ]
    for target in candidates:
        target = os.path.realpath(target)
        temporary = None
        try:
            target_dir = os.path.dirname(target)
            if target_dir and not os.path.isdir(target_dir):
                continue
            lines = []
            if os.path.isfile(target):
                with open(target, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
            updated = []
            found = False
            for line in lines:
                stripped = line.strip()
                if stripped.startswith(f"{key}=") or stripped.startswith(f"#{key}=") or stripped.startswith(f"# {key}="):
                    if not found:
                        updated.append(f"{key}={value}\n")
                        found = True
                else:
                    updated.append(line)
            if not found:
                updated.append(f"{key}={value}\n")
            descriptor, temporary = tempfile.mkstemp(prefix=".env-", dir=target_dir or ".")
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                output.writelines(updated)
            os.replace(temporary, target)
            temporary = None
            os.environ[key] = value
            print(f"[Setup] ✓ Persisted {key} to {target}", flush=True)
            return True
        except (OSError, UnicodeError):
            continue
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
    return False

def resolve_path(relative_path, default_path):
    for candidate in [
        default_path,
        os.path.join(os.getcwd(), relative_path),
        os.path.join("/app", relative_path),
        os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", relative_path))
    ]:
        if os.path.exists(candidate):
            return candidate
    return default_path

SERVICE_PORT_MAP = {
    "postersplus": (8000, 9039, "PORT_POSTERSPLUS"),
    "aiometadata": (4005, 4005, "PORT_AIOMETADATA"),
    "aiostreams": (3000, 3001, "PORT_AIOSTREAMS"),
    "prowlarr": (9696, 9696, "PORT_PROWLARR"),
    "flaresolverr": (8191, 8191, "PORT_FLARESOLVERR"),
    "zilean": (8181, 8181, "PORT_ZILEAN"),
    "stremthru": (8080, 8080, "PORT_STREMTHRU"),
    "subsense": (3100, 3100, "PORT_SUBSENSE"),
    "stremio-subsense": (3100, 3100, "PORT_SUBSENSE"),
    "anime-kitsu": (7000, 7005, "PORT_ANIME_KITSU"),
    "lumiere-db": (8000, 8000, "PORT_LUMIERE_DB"),
    "jikan-api": (8080, 8001, "PORT_JIKAN_API"),
}

def is_dns_error(exc):
    """Check if exception is a DNS / getaddrinfo resolution failure."""
    if isinstance(exc, socket.gaierror):
        return True
    reason = getattr(exc, "reason", None)
    if isinstance(reason, socket.gaierror):
        return True
    msg = str(reason if reason is not None else exc).lower()
    return any(ind in msg for ind in (
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
    ))

def get_service_fallback_url(url):
    """
    If url targets a known container name, generate the mapped localhost fallback URL.
    E.g. http://postersplus:8000/... -> http://127.0.0.1:9039/...
         http://aiometadata:4005/... -> http://127.0.0.1:4005/...
    """
    if not url:
        return None
    try:
        parsed = urllib.parse.urlsplit(url)
        host = (parsed.hostname or "").lower()
        if host in ("localhost", "127.0.0.1", "::1"):
            return None
        if host in SERVICE_PORT_MAP:
            _, default_host_port, env_port_var = SERVICE_PORT_MAP[host]
            host_port = int(os.environ.get(env_port_var) or default_host_port)
            netloc = f"127.0.0.1:{host_port}"
            return urllib.parse.urlunsplit((parsed.scheme or "http", netloc, parsed.path, parsed.query, parsed.fragment))
    except Exception:
        pass
    return None

PROWLARR_URL = os.environ.get("PROWLARR_URL", "http://prowlarr:9696").rstrip("/")
ZILEAN_URL = os.environ.get("ZILEAN_URL", "http://zilean:8181").rstrip("/")
PROWLARR_API_KEY = os.environ.get("PROWLARR_API_KEY", "prowlarr_internal_secret_key_99")
FLARESOLVERR_URL = os.environ.get("FLARESOLVERR_URL", "http://flaresolverr:8191").rstrip("/")
AIOSTREAMS_URL = os.environ.get("AIOSTREAMS_URL", "http://aiostreams:3000").rstrip("/")
AIOMETADATA_URL = os.environ.get("AIOMETADATA_URL", "http://aiometadata:4005").rstrip("/")
POSTERSPLUS_URL = os.environ.get("POSTERSPLUS_URL", "http://postersplus:8000").rstrip("/")
STREMTHRU_URL = os.environ.get("STREMTHRU_URL", "http://stremthru:8080").rstrip("/")
BASE_URL = os.environ.get("BASE_URL", "http://localhost:3000").rstrip("/")

AIOMETADATA_HOST = os.environ.get("AIOMETADATA_HOST", "").rstrip("/")

def resolve_aiometadata_host_url(base_url, explicit_aiom_url=""):
    if explicit_aiom_url and explicit_aiom_url not in ("http://localhost:4005", "http://127.0.0.1:4005", "http://aiometadata:4005"):
        return explicit_aiom_url.rstrip("/")
    if not base_url:
        return "http://localhost:4005"
    try:
        parsed = urllib.parse.urlsplit(base_url)
        scheme = parsed.scheme or "http"
        host = parsed.hostname or ""
        if host and host not in ("localhost", "127.0.0.1"):
            try:
                is_local = ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
            except ValueError:
                is_local = host == "localhost" or "." not in host or host.endswith((".local", ".lan"))
            if not is_local:
                parts = host.split(".")
                if parts[0] in ("aio", "aiostreams", "stremio"):
                    parts[0] = "aiometa"
                    aiom_host = ".".join(parts)
                else:
                    aiom_host = "aiometa." + host
                return f"{scheme}://{aiom_host}"
    except Exception:
        pass
    return "http://localhost:4005"

derived_aiom_url = resolve_aiometadata_host_url(BASE_URL, AIOMETADATA_HOST)
if derived_aiom_url and derived_aiom_url != AIOMETADATA_HOST:
    AIOMETADATA_HOST = derived_aiom_url
    os.environ["AIOMETADATA_HOST"] = derived_aiom_url
    if os.environ.get("AIO_SKIP_ENV_FILE") != "true":
        update_env_file("AIOMETADATA_HOST", derived_aiom_url)

ADDON_PASSWORD = os.environ.get("ADDON_PASSWORD") or "admin"
SECRET_KEY = os.environ.get("SECRET_KEY", "e2c019d4536f9a039b56f8f1dfba8919634e2c8846bb1999252c79213bc01b09")
PREMIUMIZE_API_KEY = os.environ.get("PREMIUMIZE_API_KEY", "")
REALDEBRID_API_KEY = os.environ.get("REALDEBRID_API_KEY", "")
ALLDEBRID_API_KEY = os.environ.get("ALLDEBRID_API_KEY", "")
TORBOX_API_KEY = os.environ.get("TORBOX_API_KEY", "")
DEBRIDLINK_API_KEY = os.environ.get("DEBRIDLINK_API_KEY", "")
EASYDEBRID_API_KEY = os.environ.get("EASYDEBRID_API_KEY", "")
OFFCLOUD_API_KEY = os.environ.get("OFFCLOUD_API_KEY", "")
SEEDR_API_KEY = os.environ.get("SEEDR_API_KEY", "")
EASYNEWS_USER = os.environ.get("EASYNEWS_USER", "")
EASYNEWS_PASSWORD = os.environ.get("EASYNEWS_PASSWORD", "")
USENET_ENABLED = os.environ.get("USENET_ENABLED", "false").lower() == "true"
USENET_HOST = os.environ.get("USENET_HOST", "")
USENET_PORT = os.environ.get("USENET_PORT", "563")
USENET_USER = os.environ.get("USENET_USER", "")
USENET_PASS = os.environ.get("USENET_PASS", "")
USENET_SSL = os.environ.get("USENET_SSL", "true")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")
TVDB_API_KEY = os.environ.get("TVDB_API_KEY", "")
MDBLIST_API_KEY = os.environ.get("MDBLIST_API_KEY", "")
RPDB_API_KEY = os.environ.get("RPDB_API_KEY", "")
FANART_API_KEY = os.environ.get("FANART_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
SIMKL_CLIENT_ID = os.environ.get("SIMKL_CLIENT_ID", "")
ANILIST_TOKEN = os.environ.get("ANILIST_TOKEN", "")

DATA_AIOSTREAMS = resolve_path("data/aiostreams", "/data/aiostreams")
DATA_ROOT = resolve_path("data", "/data")
TEMPLATE_PATH = resolve_path("templates/builtin/all-local-selfhosted.json", "/templates/builtin/all-local-selfhosted.json")
AIOMETADATA_CONFIG_PATH = resolve_path("templates/aiometadata-configs/tamtaro-aiometadata-with-anime.json", "/templates/aiometadata-configs/tamtaro-aiometadata-with-anime.json")

def resolve_aiometadata_template_path(template_name=""):
    selected = (template_name or os.environ.get("AIOMETADATA_TEMPLATE") or "tamtaro-aiometadata-with-anime.json").strip()
    if selected in ("with-anime", "anime", "tamtaro-with-anime"):
        selected = "tamtaro-aiometadata-with-anime.json"
    elif selected in ("without-anime", "standard", "non-anime", "tamtaro-without-anime"):
        selected = "tamtaro-aiometadata-without-anime.json"
    elif selected in ("grabberhawk", "grabberhawk-config"):
        selected = "grabberhawk-aiometadata-config.json"
    elif selected in ("usenet", "usenet-only", "tamtaro-usenet-only", "usenet-only.json"):
        selected = "tamtaro-aiometadata-with-anime.json"

    candidates = [
        selected,
        resolve_path(f"templates/aiometadata-configs/{selected}", f"/templates/aiometadata-configs/{selected}"),
        resolve_path(f"templates/{selected}", f"/templates/{selected}"),
        resolve_path(selected, selected)
    ]
    for cand in candidates:
        if cand and os.path.isfile(cand):
            return cand
    return AIOMETADATA_CONFIG_PATH

TARGET_INDEXERS = [
    "bitsearch",
    "solidtorrents",
    "1337x",
    "yts",
    "eztv",
    "thepiratebay",
    "torrentgalaxy",
    "limetorrents",
    "magnetdl",
    "nyaasi",
    "tokyotosho"
]

SCRAPER_TIMEOUT_MS = int(os.environ.get("SCRAPER_TIMEOUT_MS", "3000"))

def make_request(url, method="GET", data=None, headers=None, timeout=12, max_redirects=5, allow_fallback=True):
    default_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    if headers:
        default_headers.update(headers)
    try:
        body = json.dumps(data).encode("utf-8") if (data is not None and not isinstance(data, (bytes, bytearray))) else data
        req = urllib.request.Request(url, data=body, headers=default_headers, method=method)
    except Exception as e:
        return {"error": -1, "message": f"Invalid request configuration: {e}"}

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
            if content.strip().startswith(("{", "[")):
                try:
                    return json.loads(content)
                except Exception:
                    return {"status": resp.status, "text": content}
            return {"status": resp.status, "text": content}
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 307, 308) and e.headers.get("Location") and max_redirects > 0:
            redirect_url = urllib.parse.urljoin(url, e.headers.get("Location"))
            return make_request(redirect_url, method=method, data=data, headers=headers, timeout=timeout, max_redirects=max_redirects - 1, allow_fallback=allow_fallback)
        err_msg = ""
        try:
            err_msg = e.read().decode("utf-8", errors="ignore")
        except Exception:
            err_msg = str(e)
        return {"error": e.code, "message": err_msg}
    except urllib.error.URLError as e:
        if allow_fallback:
            reason = getattr(e, "reason", None)
            is_conn_err = isinstance(reason, (ConnectionRefusedError, OSError)) or isinstance(e, (ConnectionRefusedError, OSError))
            if is_dns_error(e) or is_conn_err:
                fallback_url = get_service_fallback_url(url)
                if fallback_url and fallback_url != url:
                    try:
                        return make_request(fallback_url, method=method, data=data, headers=headers, timeout=timeout, max_redirects=max_redirects, allow_fallback=False)
                    except Exception:
                        pass
        reason = getattr(e, "reason", e)
        return {"error": -1, "message": f"Connection failed ({reason})"}
    except (TimeoutError, socket.timeout) as e:
        return {"error": -1, "message": f"Request timed out after {timeout}s: {e}"}
    except Exception as e:
        if allow_fallback:
            reason = getattr(e, "reason", None)
            is_conn_err = isinstance(reason, (ConnectionRefusedError, OSError)) or isinstance(e, (ConnectionRefusedError, OSError))
            if is_dns_error(e) or is_conn_err:
                fallback_url = get_service_fallback_url(url)
                if fallback_url and fallback_url != url:
                    try:
                        return make_request(fallback_url, method=method, data=data, headers=headers, timeout=timeout, max_redirects=max_redirects, allow_fallback=False)
                    except Exception:
                        pass
        return {"error": -1, "message": str(e)}

def is_url_reachable(url, timeout=2.0, allow_fallback=True):
    if not url or not isinstance(url, str):
        return False
    try:
        req = urllib.request.Request(url.strip(), headers={"User-Agent": "AIOStreams-Probe/1.0", "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status in (200, 301, 302)
    except Exception as e:
        if allow_fallback:
            reason = getattr(e, "reason", None)
            is_conn_err = isinstance(reason, (ConnectionRefusedError, OSError)) or isinstance(e, (ConnectionRefusedError, OSError))
            if is_dns_error(e) or is_conn_err:
                fallback_url = get_service_fallback_url(url)
                if fallback_url and fallback_url != url:
                    return is_url_reachable(fallback_url, timeout=timeout, allow_fallback=False)
        return False

DEFAULT_JIKAN_URL = "https://api.tenrai.org/v4"
LOCAL_JIKAN_URL = "http://jikan-api:8080/v4"

def resolve_jikan_api_base(configured_url="", probe_services=True):
    explicit = (configured_url or os.environ.get("JIKAN_API_BASE") or "").strip()
    if explicit and explicit != DEFAULT_JIKAN_URL:
        return explicit.rstrip("/")
    if probe_services:
        for candidate in (LOCAL_JIKAN_URL, "http://jikan-api:80/v4", "http://jikan-api/v4"):
            if is_url_reachable(candidate, timeout=1.0) or is_url_reachable(f"{candidate}/seasons/now", timeout=1.0):
                return candidate
    return explicit or DEFAULT_JIKAN_URL

JIKAN_API_BASE = os.environ.get("JIKAN_API_BASE") or DEFAULT_JIKAN_URL

# ==============================================================================
# 1. PROWLARR PROVISIONING
# ==============================================================================
def wait_for_prowlarr(max_attempts=20, interval=2):
    global PROWLARR_URL
    print(f"[Prowlarr Setup] Waiting for Prowlarr at {PROWLARR_URL}...", flush=True)
    headers = {"X-Api-Key": PROWLARR_API_KEY}
    for attempt in range(1, max_attempts + 1):
        res = make_request(f"{PROWLARR_URL}/api/v1/system/status", headers=headers, timeout=2)
        if isinstance(res, dict) and "version" in res:
            print(f"[Prowlarr Setup] ✓ Prowlarr v{res.get('version')} is online! (attempt {attempt})", flush=True)
            return True
        if not (isinstance(res, dict) and "version" in res) and not PROWLARR_URL.endswith("/service-proxy/prowlarr"):
            probe_url = f"{PROWLARR_URL}/service-proxy/prowlarr"
            probe_res = make_request(f"{probe_url}/api/v1/system/status", headers=headers, timeout=2)
            if isinstance(probe_res, dict) and "version" in probe_res:
                print(f"[Prowlarr Setup] ✓ Prowlarr v{probe_res.get('version')} is online with urlBase at {probe_url}! (attempt {attempt})", flush=True)
                PROWLARR_URL = probe_url
                return True
        if attempt >= 8 and not is_url_reachable(PROWLARR_URL, timeout=1.0):
            print("[Prowlarr Setup] ℹ️ Prowlarr is unreachable. Check its container, selected Compose profile, and Docker network. Indexer setup was not completed.", flush=True)
            return False
        time.sleep(interval)
    print("[Prowlarr Setup] ⚠️ Timed out waiting for Prowlarr. Continuing...", flush=True)
    return False

def setup_prowlarr_auth():
    headers = {"X-Api-Key": PROWLARR_API_KEY}
    try:
        host_cfg = make_request(f"{PROWLARR_URL}/api/v1/config/host", headers=headers)
        if isinstance(host_cfg, dict) and "id" in host_cfg:
            curr_auth = str(host_cfg.get("authenticationMethod", "")).lower()
            if curr_auth != "external":
                host_cfg["authenticationMethod"] = "external"
                host_cfg["authenticationRequired"] = "disabledForLocalAddresses"
                res = make_request(f"{PROWLARR_URL}/api/v1/config/host/{host_cfg['id']}", method="PUT", data=host_cfg, headers=headers)
                updated_auth = res.get('authenticationMethod') if isinstance(res, dict) else res
                print(f"[Prowlarr Setup] ✓ Prowlarr authentication method updated to 'external': {updated_auth}", flush=True)
            else:
                print("[Prowlarr Setup] ✓ Prowlarr authentication method is already external.", flush=True)
    except Exception as e:
        print(f"[Prowlarr Setup] Note on auth bypass check: {e}", flush=True)

def setup_prowlarr_flaresolverr():
    headers = {"X-Api-Key": PROWLARR_API_KEY}
    proxies = make_request(f"{PROWLARR_URL}/api/v1/indexerproxy", headers=headers)
    if isinstance(proxies, list):
        for p in proxies:
            if isinstance(p, dict) and (p.get("implementation", "").lower() == "flaresolverr" or "flaresolverr" in p.get("name", "").lower()):
                print("[Prowlarr Setup] ✓ FlareSolverr proxy is already registered.", flush=True)
                return

    payload = {
        "name": "FlareSolverr Local",
        "implementation": "FlareSolverr",
        "configContract": "FlareSolverrSettings",
        "enable": True,
        "tags": [],
        "fields": [
            {"name": "host", "value": FLARESOLVERR_URL},
            {"name": "requestTimeout", "value": 15}
        ]
    }
    res = make_request(f"{PROWLARR_URL}/api/v1/indexerproxy", method="POST", data=payload, headers=headers)
    if isinstance(res, dict) and "id" in res:
        print(f"[Prowlarr Setup] ✓ Successfully registered FlareSolverr proxy ({FLARESOLVERR_URL})!", flush=True)
    else:
        print(f"[Prowlarr Setup] Note adding FlareSolverr proxy: {res}", flush=True)

def setup_prowlarr_indexers():
    headers = {"X-Api-Key": PROWLARR_API_KEY}
    existing_indexers = make_request(f"{PROWLARR_URL}/api/v1/indexer", headers=headers)
    existing_definitions = set()
    if isinstance(existing_indexers, list):
        for idx in existing_indexers:
            if isinstance(idx, dict):
                def_name = idx.get("definitionName", "").lower()
                name = idx.get("name", "").lower()
                if def_name:
                    existing_definitions.add(def_name)
                if name:
                    existing_definitions.add(name)

    print(f"[Prowlarr Setup] Currently active indexers in Prowlarr: {len(existing_indexers) if isinstance(existing_indexers, list) else 0}", flush=True)
    schemas = make_request(f"{PROWLARR_URL}/api/v1/indexer/schema", headers=headers, timeout=60)
    if not isinstance(schemas, list):
        print(f"[Prowlarr Setup] Could not retrieve indexer schemas: {schemas}", flush=True)
        return

    added_count = 0
    extra_indexers_raw = os.environ.get("PROWLARR_EXTRA_INDEXERS", "")
    extra_indexers = [x.strip() for x in extra_indexers_raw.split(",") if x.strip()]
    target_list = list(TARGET_INDEXERS)
    for extra in extra_indexers:
        if extra.lower() not in [t.lower() for t in target_list]:
            target_list.append(extra)

    # Top anime trackers to register and seed if available in Prowlarr schemas
    anime_targets = [
        "subsplease",
        "animetosho-xyz",
        "anibt",
        "mikan",
        "nekobt",
        "dmhy",
        "shana-project",
        "anirena",
        "bakabt",
    ]
    for at in anime_targets:
        if at.lower() not in [t.lower() for t in target_list]:
            target_list.append(at)

    indexer_aliases = {
        "animetosho": "animetosho-xyz",
        "anime tosho": "animetosho-xyz",
        "animetosho-xyz": "animetosho-xyz",
        "tokyotoshokan": "tokyotosho",
        "tokyo toshokan": "tokyotosho",
        "thepiratebay": "thepiratebay",
        "the pirate bay": "thepiratebay",
        "tpb": "thepiratebay",
        "nyaa": "nyaasi",
        "nyaa.si": "nyaasi",
        "subsplease": "subsplease",
        "subs please": "subsplease",
        "anibt": "anibt",
        "ani bt": "anibt",
        "mikan": "mikan",
        "mikanani": "mikan",
        "nekobt": "nekobt",
        "neko bt": "nekobt",
        "dmhy": "dmhy",
        "shana-project": "shana-project",
        "shana project": "shana-project",
        "anirena": "anirena",
        "ani rena": "anirena",
        "bakabt": "bakabt",
        "baka bt": "bakabt",
    }

    for target in target_list:
        target_lower = target.lower().strip()
        target_lookup = indexer_aliases.get(target_lower, target_lower)
        if any(target_lower in d or target_lookup in d for d in existing_definitions):
            continue

        matched_schema = None
        for schema in schemas:
            if not isinstance(schema, dict):
                continue
            s_def = schema.get("definitionName", "").lower()
            s_name = schema.get("name", "").lower()
            if s_def in (target_lower, target_lookup) or s_name in (target_lower, target_lookup):
                matched_schema = schema
                break

        if matched_schema:
            indexer_payload = dict(matched_schema)
            indexer_payload["enable"] = True
            indexer_payload["priority"] = 25
            indexer_payload["appProfileId"] = 1

            res = make_request(f"{PROWLARR_URL}/api/v1/indexer", method="POST", data=indexer_payload, headers=headers)
            if isinstance(res, dict) and "id" in res:
                print(f"[Prowlarr Setup] ✓ Successfully provisioned public indexer: {matched_schema.get('name')}", flush=True)
                added_count += 1

    # Ensure Zilean local DMM Torznab indexer is provisioned for instant debrid cache hits
    if not any("zilean" in d for d in existing_definitions):
        torznab_schema = next((s for s in schemas if isinstance(s, dict) and s.get("implementation") == "Torznab"), None)
        if torznab_schema:
            z_payload = dict(torznab_schema)
            z_payload["name"] = "Zilean DMM (Local)"
            # AIOStreams queries Zilean directly; keep disabled in Prowlarr to avoid duplicate scraping
            z_payload["enable"] = False
            z_payload["priority"] = 1
            z_payload["appProfileId"] = 1
            for f in z_payload.get("fields", []):
                if isinstance(f, dict):
                    if f.get("name") == "baseUrl":
                        f["value"] = f"{ZILEAN_URL}/torznab"
                    elif f.get("name") == "apiPath":
                        f["value"] = "/api"
                    elif f.get("name") == "apiKey":
                        f["value"] = PROWLARR_API_KEY
            res = make_request(f"{PROWLARR_URL}/api/v1/indexer", method="POST", data=z_payload, headers=headers)
            if isinstance(res, dict) and "id" in res:
                print("[Prowlarr Setup] ✓ Successfully provisioned Zilean DMM local Torznab indexer.", flush=True)
                added_count += 1

    print(f"[Prowlarr Setup] Prowlarr indexer provisioning complete. Added {added_count} new indexers.", flush=True)

# ==============================================================================
def tune_prowlarr_indexers():
    """Tuning priorities for high-speed local and public indexers, auto-disabling broken trackers."""
    headers = {"X-Api-Key": PROWLARR_API_KEY}
    active_indexers = make_request(f"{PROWLARR_URL}/api/v1/indexer", headers=headers)
    if not isinstance(active_indexers, list):
        return
    disabled_names = ["acg.rip", "zilean"]
    priority_map = {
        "zilean": 1,
        "animetosho": 5,
        "animetosho-xyz": 5,
        "althub": 5,
        "the pirate bay": 10,
        "thepiratebay": 10,
        "nyaa": 10,
        "nyaasi": 10,
        "yts": 10,
        "1337x": 10,
        "eztv": 15,
        "torrentgalaxy": 15,
        "tokyo toshokan": 15,
        "tokyotosho": 15,
        "subsplease": 15,
        "mikan": 15,
        "shana project": 15,
        "shana-project": 15,
        "limetorrents": 20,
        "nekobt": 20,
        "anibt": 20,
        "dmhy": 20,
        "anirena": 20,
        "bakabt": 20,
        "torrentdownload": 30,
    }
    for idx in active_indexers:
        if not isinstance(idx, dict):
            continue
        name_lower = idx.get("name", "").lower()
        impl_lower = idx.get("implementation", "").lower()
        updated = False
        # Keep Prowlarr 100% dedicated to torrents: disable local scrapers and Newznab Usenet indexers
        if any(d in name_lower for d in disabled_names) or impl_lower == "newznab" or "aio local usenet" in name_lower or "althub" in name_lower:
            if idx.get("enable"):
                idx["enable"] = False
                updated = True
        elif not idx.get("enable") and any(essential in name_lower for essential in ["limetorrents", "tokyo tosho", "nyaa", "1337x", "pirate bay", "yts", "eztv", "animetosho", "subsplease", "anibt", "mikan", "anirena", "bakabt"]):
            idx["enable"] = True
            updated = True
        new_pri = 25
        for k, p in priority_map.items():
            if k in name_lower:
                new_pri = p
                break
        if idx.get("priority") != new_pri:
            idx["priority"] = new_pri
            updated = True
        if updated and "id" in idx:
            try:
                make_request(f"{PROWLARR_URL}/api/v1/indexer/{idx['id']}", method="PUT", data=idx, headers=headers)
            except Exception:
                pass

def setup_usenet_indexer():
    active = os.environ.get('USENET_ENABLED', 'false') == 'true'
    rows = newznab_indexers(os.environ) if active else []
    headers = {'X-Api-Key': PROWLARR_API_KEY}
    endpoint = f'{PROWLARR_URL}/api/v1/indexer'
    existing = make_request(endpoint, headers=headers)
    if not isinstance(existing, list):
        raise RuntimeError('Prowlarr indexer inventory is unavailable')
    indexers = [item for item in existing if isinstance(item, dict) and item.get('implementation') == 'Newznab']
    managed_name = 'AIO Local Usenet'
    owned = {item.get('name'): item for item in indexers
             if isinstance(item, dict) and item.get('name') and re.fullmatch(r'AIO Local Usenet(?: \[aio:[a-f0-9]{32}\])?', item.get('name', ''))}
    schemas = None
    errors = 0
    keep = set()

    def field(item, name):
        if not isinstance(item, dict):
            return None
        return next((entry.get('value') for entry in item.get('fields', []) if isinstance(entry, dict) and entry.get('name') == name), None)

    for row in rows:
        if not isinstance(row, dict):
            continue
        row_id = row.get('id')
        name = f"{managed_name} [aio:{row_id}]" if row_id else managed_name
        keep.add(name)
        prior = owned.get(name)
        base = row.get('url', '')
        api_key = row.get('apiKey', '')
        duplicate = next((item for item in indexers
                          if item is not prior and str(field(item, 'baseUrl') or '').rstrip('/').lower() == base.lower()
                          and item.get('enable') and item.get('name') not in owned), None)
        if duplicate:
            print('[Usenet Setup] NZB address already registered in Prowlarr; keeping its settings.', flush=True)
            continue
        if prior and not prior.get('enable') and field(prior, 'baseUrl') == base and field(prior, 'apiKey') == api_key:
            continue
        if prior is None:
            if schemas is None:
                schemas = make_request(endpoint + '/schema', headers=headers)
                if not isinstance(schemas, list):
                    raise RuntimeError('Prowlarr Newznab support is unavailable')
            domain = urllib.parse.urlsplit(base).netloc.lower().split(':')[0]
            for prefix in ('api.', 'www.', 'nzb.'):
                if domain.startswith(prefix):
                    domain = domain[len(prefix):]
            slug = domain.split('.')[0]
            matched = None
            if slug and len(slug) >= 3:
                matched = next((s for s in schemas if isinstance(s, dict) and s.get('implementation') == 'Newznab' and (
                    slug in s.get('definitionName', '').lower() or slug in s.get('name', '').lower()
                )), None)
            if matched is None:
                matched = next((s for s in schemas if isinstance(s, dict) and s.get('implementation') == 'Newznab' and (
                    'generic' in s.get('name', '').lower() or s.get('definitionName', '').lower() == 'newznab'
                )), None)
            if matched is None:
                matched = next((s for s in schemas if isinstance(s, dict) and s.get('implementation') == 'Newznab'), None)
            if matched is None:
                raise RuntimeError('Prowlarr Newznab support is unavailable')
            schema = matched
        payload = copy.deepcopy(prior or schema)
        # NZB indexers run as direct Newznab presets in AIOStreams for sub-second resolution.
        # Keep them disabled in Prowlarr so Prowlarr queries strictly torrents.
        payload.update(name=name, enable=False, appProfileId=payload.get('appProfileId') or 1)
        for entry in payload.get('fields', []):
            if isinstance(entry, dict):
                if entry.get('name') == 'baseUrl':
                    entry['value'] = base
                elif entry.get('name') == 'apiKey':
                    entry['value'] = api_key
        if not prior:
            payload.pop('id', None)
        path = f"{endpoint}/{prior.get('id')}" if (prior and prior.get('id')) else endpoint
        result = make_request(path, method='PUT' if prior else 'POST', headers=headers, data=payload, timeout=30)
        if not isinstance(result, dict) or not result.get('id'):
            errors += 1
            print(f"[Usenet Setup] Prowlarr could not configure indexer {base} ({name}): {result}", flush=True)

    for name, item in owned.items():
        if not isinstance(item, dict) or name in keep or not item.get('enable') or not item.get('id'):
            continue
        result = make_request(f"{endpoint}/{item['id']}", method='PUT', headers=headers, data=dict(item, enable=False))
        if not isinstance(result, dict) or not result.get('id'):
            errors += 1
            print(f"[Usenet Setup] Prowlarr could not disable retired indexer ({name}): {result}", flush=True)
    if errors:
        print(f"[Usenet Setup] ⚠️ Warning: Prowlarr could not apply {errors} NZB indexer change(s); check the addresses and API keys. Continuing with available indexers.", flush=True)
    if rows:
        print(f'[Usenet Setup] Configured NZB indexer setting(s) in Prowlarr ({len(rows) - errors}/{len(rows)} succeeded).', flush=True)


# ==============================================================================
# 2. AIOSTREAMS NATIVE USENET PROVIDER SYNC
# ==============================================================================
def sync_aiostreams_native_usenet():
    """Synchronizes Usenet NNTP provider credentials directly into AIOStreams native usenet engine."""
    candidates = [
        AIOSTREAMS_URL,
        "http://127.0.0.1:3001",
        "http://localhost:3001",
    ]
    seen = set()
    unique_candidates = [c for c in candidates if not (c in seen or seen.add(c))]

    aio_url = None
    for cand in unique_candidates:
        if is_url_reachable(cand, timeout=1.0):
            aio_url = cand
            break

    if not aio_url:
        return False

    active = (os.environ.get('USENET_ENABLED', 'true') != 'false' and os.environ.get('USENET_HOST')
              and (os.environ.get('USENET_USER') or os.environ.get('USENET_USER_B64'))
              and (os.environ.get('USENET_PASS') or os.environ.get('USENET_PASS_B64')))
    if not active:
        auth_headers = get_aiostreams_auth_headers(aio_url)
        make_request(f"{aio_url}/api/v1/dashboard/usenet/providers", method="PUT", headers=auth_headers, data={"providers": []}, timeout=5)
        return False

    host = os.environ.get('USENET_HOST', '').strip()
    user = credential(os.environ, 'USENET_USER') or os.environ.get('USENET_USER', '')
    password = credential(os.environ, 'USENET_PASS') or os.environ.get('USENET_PASS', '')
    if not host or not user or not password:
        auth_headers = get_aiostreams_auth_headers(aio_url)
        make_request(f"{aio_url}/api/v1/dashboard/usenet/providers", method="PUT", headers=auth_headers, data={"providers": []}, timeout=5)
        return False

    try:
        port = int(os.environ.get('USENET_PORT') or 563)
    except (ValueError, TypeError):
        port = 563

    try:
        max_connections = int(os.environ.get('USENET_CONNECTIONS') or 30)
    except (ValueError, TypeError):
        max_connections = 30
    max_connections = max(1, min(max_connections, 50))

    use_ssl = str(port) in ("563", "443") or os.environ.get('USENET_SSL', 'true').lower() == 'true'

    slug = host.split('.')[1] if '.' in host and len(host.split('.')) > 2 else host.split('.')[0]
    provider_id = slug.lower().replace('-', '_')

    providers = [
        {
            "id": provider_id,
            "name": f"{slug.capitalize()} High-Speed",
            "host": host,
            "port": port,
            "tls": use_ssl,
            "username": user,
            "password": password,
            "maxConnections": max_connections,
            "priority": 0,
            "isBackup": False,
            "enabled": True,
            "pipelineDepth": 2
        }
    ]

    # Handle any extra usenet servers
    try:
        extras = extra_sources(os.environ, 'USENET_EXTRA_SERVERS')
        for idx, ex in enumerate(extras):
            e_host = str(ex.get('host') or '').strip()
            e_user = str(ex.get('username') or '')
            e_pass = str(ex.get('password') or '')
            if not e_host or not e_user or not e_pass:
                continue
            try:
                e_port = int(ex.get('port') or 563)
            except (ValueError, TypeError):
                e_port = 563
            try:
                e_conns = int(ex.get('connections') or 10)
            except (ValueError, TypeError):
                e_conns = 10
            e_slug = e_host.split('.')[1] if '.' in e_host and len(e_host.split('.')) > 2 else e_host.split('.')[0]
            providers.append({
                "id": f"{e_slug.lower()}_{idx + 1}",
                "name": f"{e_slug.capitalize()} {'Backup' if ex.get('backupOnly') else 'Secondary'}",
                "host": e_host,
                "port": e_port,
                "tls": bool(ex.get('tls', True)),
                "username": e_user,
                "password": e_pass,
                "maxConnections": max(1, min(e_conns, 50)),
                "priority": 1 if ex.get('backupOnly') else 0,
                "isBackup": bool(ex.get('backupOnly', False)),
                "enabled": True,
                "pipelineDepth": 2
            })
    except Exception as e:
        print(f"[Usenet Setup] Note parsing extra usenet servers: {e}", flush=True)

    auth_headers = get_aiostreams_auth_headers(aio_url)
    payload = {"providers": providers}
    endpoint = f"{aio_url}/api/v1/dashboard/usenet/providers"
    res = make_request(endpoint, method="PUT", headers=auth_headers, data=payload, timeout=10)
    if isinstance(res, dict) and res.get("success"):
        print(f"[Usenet Setup] ✓ Synchronized {len(providers)} native Usenet provider(s) into AIOStreams engine.", flush=True)
        return True
    else:
        print(f"[Usenet Setup] Note syncing native Usenet providers: {res}", flush=True)
        return False


def wait_for_postersplus(max_attempts=20, interval=2):
    print(f"[Posters+ Setup] Waiting for Posters+ at {POSTERSPLUS_URL}...", flush=True)
    for attempt in range(1, max_attempts + 1):
        res = make_request(f"{POSTERSPLUS_URL}/?access_key={ADDON_PASSWORD}", timeout=2)
        if isinstance(res, dict) and (not res.get("error") or res.get("status") in (200, 301, 302) or "access_key" in str(res.get("text", "")) or "detail" in res or "access_key" in str(res)):
            print(f"[Posters+ Setup] ✓ Posters+ is online and ready! (attempt {attempt})", flush=True)
            return True
        if attempt >= 8 and not is_url_reachable(POSTERSPLUS_URL, timeout=1.0):
            print(f"[Posters+ Setup] ℹ️ Posters+ is unreachable at {POSTERSPLUS_URL}. Check its container, selected Compose profile, and Docker network.", flush=True)
            return False
        time.sleep(interval)
    print(f"[Posters+ Setup] ℹ️ Posters+ timed out while starting up at {POSTERSPLUS_URL}; continuing without optional rating posters.", flush=True)
    return False

def wait_for_aiometadata(max_attempts=30, interval=2):
    print(f"[AIOMetadata Setup] Waiting for AIOMetadata at {AIOMETADATA_URL}...", flush=True)
    for attempt in range(1, max_attempts + 1):
        res = make_request(f"{AIOMETADATA_URL}/manifest.json", timeout=2)
        if isinstance(res, dict) and not res.get("error") and res.get("id"):
            print(f"[AIOMetadata Setup] ✓ AIOMetadata is online and ready! (attempt {attempt})", flush=True)
            return True
        if attempt >= 8 and not is_url_reachable(AIOMETADATA_URL, timeout=1.0):
            print(f"[AIOMetadata Setup] ℹ️ AIOMetadata is unreachable at {AIOMETADATA_URL}. Check its container, selected Compose profile, and Docker network.", flush=True)
            return False
        time.sleep(interval)
    print(f"[AIOMetadata Setup] ℹ️ AIOMetadata timed out while starting up at {AIOMETADATA_URL}; continuing without optional metadata.", flush=True)
    return False

def setup_aiometadata_tamtaro():
    global TMDB_API_KEY, TVDB_API_KEY, MDBLIST_API_KEY, RPDB_API_KEY, FANART_API_KEY, GEMINI_API_KEY, SIMKL_CLIENT_ID, ANILIST_TOKEN
    template_path = resolve_aiometadata_template_path()
    template_name = os.path.basename(template_path)
    print(f"[AIOMetadata Setup] Configuring Tamtaro AIOMetadata profile ({template_name}) with Posters+ integration...", flush=True)
    config = {}
    if os.path.exists(template_path):
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
                config = raw.get("config", raw)
        except Exception as e:
            print(f"[AIOMetadata Setup] Note loading AIOMetadata template: {e}", flush=True)

    if not config:
        config = {
            "language": "en-US",
            "apiKeys": {},
            "artProviders": {
                "movie": {"poster": "custom", "background": "meta", "logo": "meta"},
                "series": {"poster": "custom", "background": "meta", "logo": "meta"},
                "anime": {"poster": "custom", "background": "meta", "logo": "meta"}
            }
        }

    existing_profile = os.environ.get("AIOMETADATA_PROFILE_UUID")
    if existing_profile:
        load_url = f"{AIOMETADATA_URL}/api/config/load/{existing_profile}"
        credentials = {"password": ADDON_PASSWORD, "addonPassword": ADDON_PASSWORD}
        loaded = make_request(load_url, method="POST", data=credentials)
        previous_password = os.environ.get("AIO_PASSWORD_PREVIOUS")
        if previous_password and isinstance(loaded, dict) and loaded.get("error") == 401:
            old_profile = make_request(load_url, method="POST",
                                       data={**credentials, "password": previous_password})
            if isinstance(old_profile, dict) and old_profile.get("success"):
                reset = make_request(
                    f"{AIOMETADATA_URL}/api/admin/users/{existing_profile}/reset-password",
                    method="POST", headers={"X-Admin-Key": SECRET_KEY},
                    data={"newPassword": ADDON_PASSWORD},
                )
                if not isinstance(reset, dict) or not reset.get("success"):
                    raise RuntimeError("AIOMetadata could not change the saved profile password")
                loaded = make_request(load_url, method="POST", data=credentials)
        if not isinstance(loaded, dict) or not loaded.get("success") or not isinstance(loaded.get("config"), dict):
            raise RuntimeError("Existing metadata profile could not be loaded; refusing to overwrite linked accounts.")
        existing_cfg = loaded["config"]
        existing_keys = existing_cfg.get("apiKeys", {}) if isinstance(existing_cfg, dict) else {}
        if isinstance(existing_keys, dict):
            for k, v in existing_keys.items():
                if "Token" in k or "token" in k or "Account" in k or "oauth" in k:
                    config.setdefault("apiKeys", {})[k] = v
        for field in ("tokens", "accounts", "oauth", "linkedAccounts"):
            if field in existing_cfg:
                config[field] = existing_cfg[field]
        saved_tmpl = os.environ.get("AIOMETADATA_TEMPLATE")
        if not saved_tmpl or saved_tmpl == template_name:
            if "catalogs" in config and not previous_password:
                existing_cfg["catalogs"] = config["catalogs"]
            if isinstance(config.get("apiKeys"), dict):
                for k, v in config.get("apiKeys", {}).items():
                    existing_cfg.setdefault("apiKeys", {})[k] = v
            config = existing_cfg

    # Refresh environment variables
    load_env_file()
    tmdb_key = os.environ.get("TMDB_API_KEY") or TMDB_API_KEY
    tvdb_key = os.environ.get("TVDB_API_KEY") or TVDB_API_KEY
    mdblist_key = os.environ.get("MDBLIST_API_KEY") or MDBLIST_API_KEY
    rpdb_key = os.environ.get("RPDB_API_KEY") or RPDB_API_KEY
    fanart_key = os.environ.get("FANART_API_KEY") or FANART_API_KEY
    gemini_key = os.environ.get("GEMINI_API_KEY") or GEMINI_API_KEY
    simkl_key = os.environ.get("SIMKL_CLIENT_ID") or SIMKL_CLIENT_ID
    anilist_key = os.environ.get("ANILIST_TOKEN") or ANILIST_TOKEN

    # Community presets include dozens of MDBList catalogs. Enable these only
    # when a key is supplied, instead of adding slow, unusable catalog requests.
    for catalog in (config.get("catalogs", []) if isinstance(config.get("catalogs"), list) else ()):
        if not isinstance(catalog, dict):
            continue
        src_id = str(catalog.get("source", catalog.get("id", ""))).lower()
        if not mdblist_key and "mdblist" in src_id:
            catalog["enabled"] = False
        if not simkl_key and "simkl" in src_id and "personal" in src_id:
            catalog["enabled"] = False

    # Inject user API keys
    api_keys = config.setdefault("apiKeys", {})
    if tmdb_key:
        api_keys["tmdb"] = tmdb_key
    if tvdb_key:
        api_keys["tvdb"] = tvdb_key
    if mdblist_key:
        api_keys["mdblist"] = mdblist_key
    if rpdb_key:
        api_keys["rpdb"] = rpdb_key
    if fanart_key:
        api_keys["fanart"] = fanart_key
    if gemini_key:
        api_keys["gemini"] = gemini_key
    # Account token-record IDs are created by AIOMetadata OAuth, never client IDs
    # or raw access tokens. Keep existing linked records loaded above.

    # Configure Posters+ Rating Poster Provider with multi-shape support
    config["usePosterProxy"] = True
    config["posterRatingProvider"] = "customArt"
    poster_key = os.environ.get("POSTERSPLUS_ACCESS_KEY") or os.environ.get("ADDON_PASSWORD") or "admin"
    internal_poster_base = os.environ.get("POSTERSPLUS_CONTAINER_URL") or "http://postersplus:8000"
    if "127.0.0.1" not in POSTERSPLUS_URL and "localhost" not in POSTERSPLUS_URL:
        internal_poster_base = POSTERSPLUS_URL
    poster_url = f"{internal_poster_base}/poster?stremio_id={{id}}&type={{type}}&shape={{shape}}"
    if poster_key:
        poster_url += '&access_key=' + urllib.parse.quote(poster_key, safe='')
    config["customPosterUrl"] = poster_url
    config["enableRatingPostersForLibrary"] = True
    config.setdefault("customArt", {})["posterUrl"] = poster_url
    config["customArt"]["proxy"] = True

    # Fanart is optional, but AIOMetadata requires its key if any slot selects it.
    art_source = "fanart" if str(api_keys.get("fanart") or "").strip() else "tmdb"
    art_providers = config.setdefault("artProviders", {})
    for kind in ("movie", "series", "anime"):
        kind_cfg = art_providers.get(kind)
        if not isinstance(kind_cfg, dict):
            kind_cfg = {}
            art_providers[kind] = kind_cfg
        kind_cfg["logo"] = art_source
        kind_cfg["background"] = art_source
        kind_cfg["poster"] = "custom"

    config["castCount"] = 15
    config["animeEpisodeDates"] = "earliest"
    config.setdefault("search", {})["ai_enabled"] = bool(str(api_keys.get("gemini") or "").strip())
    config["traktWatchTracking"] = True
    config["simklWatchTracking"] = True
    config["anilistWatchTracking"] = True
    config["malWatchTracking"] = True
    config["mdblistWatchTracking"] = True
    config["watchTracking"] = {
        "trakt": {"movie": True, "series": True},
        "simkl": {"movie": True, "series": True},
        "anilist": {"movie": True, "series": True},
        "mal": {"movie": True, "series": True},
        "mdblist": {"movie": True, "series": True}
    }

    current_jikan = resolve_jikan_api_base(os.environ.get("JIKAN_API_BASE"))
    if current_jikan != DEFAULT_JIKAN_URL:
        print(f"[AIOMetadata Setup] ✓ Local Jikan Anime DB detected ({current_jikan}).", flush=True)
    else:
        print(f"[AIOMetadata Setup] Using cloud Jikan endpoint ({DEFAULT_JIKAN_URL}).", flush=True)
    config["jikanApiBase"] = current_jikan
    config["jikanUrl"] = current_jikan

    # Register configuration in AIOMetadata
    save_payload = {
        "config": config,
        "password": ADDON_PASSWORD,
        "addonPassword": ADDON_PASSWORD
    }
    existing_profile = os.environ.get("AIOMETADATA_PROFILE_UUID")
    endpoint = f"{AIOMETADATA_URL}/api/config/update/{existing_profile}" if existing_profile else f"{AIOMETADATA_URL}/api/config/save"
    res = make_request(endpoint, method="PUT" if existing_profile else "POST", data=save_payload)
    if not isinstance(res, dict) or not res.get("success"):
        status = res.get("error") if isinstance(res, dict) else None
        detail = {
            -1: "Could not reach AIOMetadata while saving the profile.",
            401: "AIOMetadata refused the password. Verify that the stack password matches the addon and any existing profile.",
            403: "AIOMetadata denied permission to save this profile.",
            409: "The AIOMetadata profile changed during setup. Reload it and try again.",
        }.get(status) if isinstance(status, int) else None
        if status == 400:
            try:
                error_body = json.loads(res.get("message", ""))
            except (ValueError, TypeError):
                error_body = {}
            missing = error_body.get("missingKeys") if isinstance(error_body, dict) else None
            keys = [label for key, label in (("tmdb", "TMDB"), ("fanart", "Fanart")) if isinstance(missing, list) and key in missing]
            if keys:
                detail = f"AIOMetadata needs an API key for {', '.join(keys)}."
            elif isinstance(error_body, dict) and "maxCatalogs" in error_body:
                detail = "AIOMetadata rejected the preset because it exceeds the enabled catalog limit."
        if not detail:
            detail = f"AIOMetadata rejected the profile (HTTP {status})." if isinstance(status, int) and 400 <= status <= 599 else "AIOMetadata did not confirm that it saved the profile."
        raise RuntimeError(detail)
    if isinstance(res, dict) and res.get("userUUID"):
        update_env_file("AIOMETADATA_PROFILE_UUID", str(res["userUUID"]))
    update_env_file("AIOMETADATA_TEMPLATE", template_name)
    manifest_url = f"{AIOMETADATA_URL}/manifest.json"

    if isinstance(res, dict):
        uuid = res.get("userUUID") or res.get("uuid") or res.get("id")
        comp = res.get("compressedConfig") or res.get("config")
        if res.get("installUrl"):
            install_path = urllib.parse.urlsplit(res["installUrl"]).path
            manifest_url = f"{AIOMETADATA_URL}{install_path}"
            print("[AIOMetadata Setup] Personalized metadata manifest generated.", flush=True)
        elif uuid and comp:
            manifest_url = f"{AIOMETADATA_URL}/stremio/{uuid}/{comp}/manifest.json"
            print(f"[AIOMetadata Setup] ✓ Tamtaro + Posters+ manifest generated: {manifest_url}", flush=True)
        elif uuid:
            manifest_url = f"{AIOMETADATA_URL}/stremio/{uuid}/manifest.json"
            print(f"[AIOMetadata Setup] ✓ Tamtaro + Posters+ manifest generated: {manifest_url}", flush=True)
        elif "manifestUrl" in res:
            manifest_url = res["manifestUrl"]
            print(f"[AIOMetadata Setup] ✓ Tamtaro + Posters+ manifest generated: {manifest_url}", flush=True)
        else:
            print(f"[AIOMetadata Setup] Config saved. Default manifest: {manifest_url}", flush=True)
    else:
        print(f"[AIOMetadata Setup] Response from AIOMetadata: {res}", flush=True)

    return manifest_url


def setup_optional_metadata():
    """Configure the metadata addon only when its profile services are ready."""
    rotating_saved_profile = os.environ.get("AIO_PASSWORD_PREVIOUS") and os.environ.get("AIOMETADATA_PROFILE_UUID")
    if not rotating_saved_profile and not wait_for_postersplus():
        print("[AIOMetadata Setup] ℹ️ Posters+ is unavailable; continuing without optional metadata.", flush=True)
        return None
    if not wait_for_aiometadata():
        print("[AIOMetadata Setup] ℹ️ AIOMetadata is unavailable; continuing without optional metadata.", flush=True)
        return None
    return setup_aiometadata_tamtaro()

# ==============================================================================
# 4. AIOSTREAMS DEFAULT TEMPLATE & ADDON AUTO-CONFIGURATION
# ==============================================================================
def wait_for_aiostreams(max_attempts=30, interval=2):
    print(f"[AIOStreams Setup] Waiting for AIOStreams at {AIOSTREAMS_URL}...", flush=True)
    for attempt in range(1, max_attempts + 1):
        res = make_request(f"{AIOSTREAMS_URL}/api/v1/status")
        if isinstance(res, dict) and not res.get("error") and ("status" in res or "version" in res or res.get("success")):
            print(f"[AIOStreams Setup] ✓ AIOStreams is online and ready! (attempt {attempt})", flush=True)
            return True
        time.sleep(interval)
    print("[AIOStreams Setup] ⚠️ Timed out waiting for AIOStreams. Provisioning is blocked; check the container and Docker network before retrying.", flush=True)
    return False

DEPRECATED_PRESET_TARGETS = (
    "comet", "sootio", "debrid-search", "mediaflow", "mediafusion", "slicksync", "nuvio", "stremio-web", "bitmagnet"
)

def is_deprecated_preset(preset):
    """Detect whether a preset belongs to a deprecated or removed scraper/addon."""
    if not isinstance(preset, dict):
        return False
    ptype = str(preset.get("type") or "").lower()
    pid = str(preset.get("instanceId") or "").lower()
    opts = preset.get("options") if isinstance(preset.get("options"), dict) else {}
    name = str(opts.get("name") or "").lower()
    url = str(opts.get("url") or "").lower()
    manifest_url = str(opts.get("manifestUrl") or "").lower()
    torznab_url = str(opts.get("torznabUrl") or "").lower()

    for target in DEPRECATED_PRESET_TARGETS:
        if (target in ptype or target in pid or target in name or target in url or
                target in manifest_url or target in torznab_url):
            return True
    return False

def build_default_config(aiometadata_manifest=None, *, probe_services=True, base_config=None):
    """Builds our comprehensive Tamtaro All-Local Self-Hosted configuration dictionary."""
    reachable = is_url_reachable if probe_services else lambda *args, **kwargs: True
    usenet_active = (os.environ.get('USENET_ENABLED', 'true') != 'false' and os.environ.get('USENET_HOST')
                     and (os.environ.get('USENET_USER') or os.environ.get('USENET_USER_B64'))
                     and (os.environ.get('USENET_PASS') or os.environ.get('USENET_PASS_B64')))
    has_debrid = any(k for k in (REALDEBRID_API_KEY, PREMIUMIZE_API_KEY, TORBOX_API_KEY, ALLDEBRID_API_KEY, DEBRIDLINK_API_KEY, EASYDEBRID_API_KEY, OFFCLOUD_API_KEY, SEEDR_API_KEY))
    streaming_mode = os.environ.get("STREAMING_MODE", "").lower()
    is_usenet_only = streaming_mode == "usenet" or (usenet_active and not has_debrid) or os.environ.get("AIOMETADATA_TEMPLATE") in ("usenet-only.json", "usenet-only", "tamtaro-usenet-only.json")

    if base_config is None:
        template_data = {}
        chosen_template_path = TEMPLATE_PATH
        if is_usenet_only:
            u_cand = resolve_path("templates/builtin/usenet-only.json", "/templates/builtin/usenet-only.json")
            if os.path.exists(u_cand):
                chosen_template_path = u_cand
        elif streaming_mode in ("anime", "anime-only") or (os.environ.get("AIOMETADATA_TEMPLATE") or "").lower() in ("anime-only", "anime-only.json", "tamtaro-anime-only.json"):
            a_cand = resolve_path("templates/setup-templates/tamtaro-anime-only.json", "/templates/setup-templates/tamtaro-anime-only.json")
            if not os.path.exists(a_cand):
                a_cand = resolve_path("templates/builtin/tamtaro-anime-only.json", "/templates/builtin/tamtaro-anime-only.json")
            if os.path.exists(a_cand):
                chosen_template_path = a_cand
        if os.path.exists(chosen_template_path):
            try:
                with open(chosen_template_path, "r", encoding="utf-8") as f:
                    template_data = json.load(f)
            except Exception as e:
                print(f"[AIOStreams Setup] Note loading template file: {e}", flush=True)

        base_config = template_data.get("config", {})
    else:
        template_data = {}
        chosen_template_path = None
        base_config = copy.deepcopy(base_config)

    active_template_str = ""
    if chosen_template_path:
        active_template_str += " " + os.path.basename(chosen_template_path)
    if template_data:
        active_template_str += " " + str(template_data.get("metadata", {}).get("name", ""))
        active_template_str += " " + str(template_data.get("metadata", {}).get("id", ""))
        active_template_str += " " + str(template_data.get("name", ""))
    if isinstance(base_config, dict):
        active_template_str += " " + str(base_config.get("name", ""))
        active_template_str += " " + str(base_config.get("id", ""))
        active_template_str += " " + str(base_config.get("addonName", ""))
        active_template_str += " " + str(base_config.get("metadata", {}).get("name", ""))
        active_template_str += " " + str(base_config.get("metadata", {}).get("id", ""))
    is_anime_variant = not is_usenet_only and ("anime" in active_template_str.lower() or (
        isinstance(base_config, dict) and any(
            p.get("type") in ("anime-tosho-new", "tsukihime", "neko-bt") and p.get("enabled")
            for p in base_config.get("presets", [])
        )
    ))

    # Ensure services are populated with native AIOStreams usenet and any provided Debrid keys
    services = [
        {
            "id": "aiostreams",
            "enabled": True,
            "credentials": {
                "aiostreamsAuth": f"admin:{ADDON_PASSWORD}"
            }
        }
    ]
    if not usenet_active:
        services = []
    if PREMIUMIZE_API_KEY:
        services.insert(0, {
            "id": "premiumize",
            "enabled": True,
            "credentials": {
                "apiKey": PREMIUMIZE_API_KEY
            }
        })
    if REALDEBRID_API_KEY:
        services.append({
            "id": "realdebrid",
            "enabled": True,
            "credentials": {
                "apiKey": REALDEBRID_API_KEY
            }
        })
    if ALLDEBRID_API_KEY:
        services.append({
            "id": "alldebrid",
            "enabled": True,
            "credentials": {
                "apiKey": ALLDEBRID_API_KEY
            }
        })
    if TORBOX_API_KEY:
        services.append({
            "id": "torbox",
            "enabled": True,
            "credentials": {
                "apiKey": TORBOX_API_KEY
            }
        })
    if DEBRIDLINK_API_KEY:
        services.append({
            "id": "debridlink",
            "enabled": True,
            "credentials": {
                "apiKey": DEBRIDLINK_API_KEY
            }
        })
    if EASYDEBRID_API_KEY:
        services.append({
            "id": "easydebrid",
            "enabled": True,
            "credentials": {
                "apiKey": EASYDEBRID_API_KEY
            }
        })
    if OFFCLOUD_API_KEY:
        services.append({
            "id": "offcloud",
            "enabled": True,
            "credentials": {
                "apiKey": OFFCLOUD_API_KEY
            }
        })
    if SEEDR_API_KEY:
        services.append({
            "id": "seedr",
            "enabled": True,
            "credentials": {
                "apiKey": SEEDR_API_KEY
            }
        })
    if EASYNEWS_USER and EASYNEWS_PASSWORD:
        services.append({
            "id": "easynews",
            "enabled": True,
            "credentials": {
                "username": EASYNEWS_USER,
                "password": EASYNEWS_PASSWORD
            }
        })

    presets = base_config.get("presets", [
        {
            "type": "prowlarr",
            "instanceId": "prowlarr-scraper",
            "enabled": True,
            "options": {
                "name": "Prowlarr Torrents",
                "url": PROWLARR_URL,
                "prowlarrUrl": PROWLARR_URL,
                "prowlarrApiKey": PROWLARR_API_KEY,
                "sources": ["torrent"],
                "timeout": 4000,
                "resources": ["stream"],
                "mediaTypes": []
            }
        },
        {
            "type": "knaben",
            "instanceId": "knaben-scraper",
            "enabled": True,
            "options": {
                "name": "Knaben (Anime)",
                "timeout": 4000,
                "resources": ["stream"],
                "mediaTypes": ["anime"],
                "useMultipleInstances": False
            }
        },
        {
            "type": "stremthruTorz",
            "instanceId": "stremthru-local",
            "enabled": False,
            "options": {
                "name": "StremThru Torz (Local)",
                "url": f"{STREMTHRU_URL}/stremio/torz/",
                "timeout": 3000,
                "resources": ["stream"],
                "mediaTypes": [],
                "includeP2P": False,
                "useMultipleInstances": False
            }
        },
        {
            "type": "stremthruStore",
            "instanceId": "stremthru-store-local",
            "enabled": True,
            "options": {
                "name": "StremThru Store (Local)",
                "url": f"{STREMTHRU_URL}/stremio/store/",
                "timeout": 3000,
                "resources": ["catalog", "meta", "stream"],
                "mediaTypes": [],
                "hideStreams": False,
                "webDl": False,
                "usenet": False
            }
        },
        {
            "type": "torrentio",
            "instanceId": "torrentio-local",
            "enabled": True,
            "options": {
                "name": "Torrentio",
                "timeout": 3500,
                "resources": ["stream"],
                "providers": [],
                "useMultipleInstances": False
            }
        },
        {
            "type": "custom",
            "instanceId": "aiometadata-local",
            "enabled": True,
            "options": {
                "name": "AIOMetadata (Local)",
                "manifestUrl": "http://aiometadata:4005/manifest.json",
                "libraryAddon": False,
                "resultPassthrough": False,
                "forceToTop": False,
                "timeout": 10000
            }
        },
        {
            "type": "custom",
            "instanceId": "subsense-local",
            "enabled": True,
            "options": {
                "name": "SubSense Subtitles (Local)",
                "manifestUrl": "http://subsense:3100/manifest.json",
                "libraryAddon": False,
                "resultPassthrough": False,
                "forceToTop": False,
                "timeout": 10000
            }
        },
        {
            "type": "custom",
            "instanceId": "anime-kitsu-local",
            "enabled": True,
            "options": {
                "name": "Anime Kitsu (Local)",
                "manifestUrl": "http://anime-kitsu:7000/manifest.json",
                "libraryAddon": False,
                "resultPassthrough": False,
                "forceToTop": False,
                "timeout": 8000
            }
        },
        {
            "type": "custom",
            "instanceId": "bento-anime",
            "enabled": True,
            "options": {
                "name": "Bento (Unified Anime)",
                "manifestUrl": os.environ.get("BENTO_MANIFEST_URL", "https://bento.tweakapps.uk/eyJzb3VyY2VzIjp7Im55YWEiOnRydWUsImFuaWJ0Ijp0cnVlLCJhbmltZXRvc2hvIjpmYWxzZSwiYW5pcmVuYSI6ZmFsc2UsInNlYWRleCI6dHJ1ZSwidHN1a2loaW1lIjpmYWxzZSwidG9ycmVudGNsYXciOmZhbHNlLCJ0b2t5b3Rvc2hvIjpmYWxzZSwic3Vic3BsZWFzZSI6dHJ1ZSwibmVrb2J0IjpmYWxzZSwia25hYmVuIjp0cnVlLCJtaWthbiI6ZmFsc2UsImhpdmVpbmRleCI6dHJ1ZX19/manifest.json"),
                "libraryAddon": False,
                "resultPassthrough": False,
                "forceToTop": False,
                "mediaTypes": ["anime"],
                "timeout": 4000
            }
        }
    ])

    removed_preset_ids = set()
    renamed_preset_ids = {}
    cleaned_presets = []
    for p in presets:
        if is_deprecated_preset(p):
            if isinstance(p, dict):
                if p.get("instanceId"):
                    removed_preset_ids.add(p["instanceId"])
                if p.get("type"):
                    removed_preset_ids.add(p["type"])
        else:
            cleaned_presets.append(p)
    presets = cleaned_presets


    # Ensure knaben is present and enabled for anime
    if not any(p.get("type") == "knaben" for p in presets):
        presets.insert(2, {
            "type": "knaben",
            "instanceId": "knaben-scraper",
            "enabled": True,
            "options": {
                "name": "Knaben (Anime)",
                "timeout": 4000,
                "resources": ["stream"],
                "mediaTypes": ["anime"],
                "useMultipleInstances": False
            }
        })
    else:
        for p in presets:
            if p.get("type") == "knaben":
                p["enabled"] = True
                opts = p.setdefault("options", {})
                opts["name"] = "Knaben (Anime)"
                opts["mediaTypes"] = ["anime"]

    # Ensure anime & usenet presets are guaranteed to be present
    anime_and_usenet = [
        {
            "type": "anime-tosho-new",
            "instanceId": "anime-tosho-new",
            "enabled": True,
            "options": {
                "name": "Anime Tosho",
                "timeout": 4000,
                "resources": ["stream"],
                "mediaTypes": [],
                "useMultipleInstances": False
            }
        },
        {
            "type": "tsukihime",
            "instanceId": "tsukihime-scraper",
            "enabled": True,
            "options": {
                "name": "TsukiHime",
                "timeout": 4000,
                "resources": ["stream"],
                "mediaTypes": ["anime"],
                "useMultipleInstances": False
            }
        },
        {
            "type": "neko-bt",
            "instanceId": "neko-bt-scraper",
            "enabled": True,
            "options": {
                "name": "nekoBT",
                "timeout": 4000,
                "resources": ["stream"],
                "mediaTypes": [],
                "useMultipleInstances": False
            }
        },
        {
            "type": "easynews-search",
            "instanceId": "easynews-search",
            "enabled": bool(EASYNEWS_USER and EASYNEWS_PASSWORD),
            "options": {
                "name": "Easynews Search",
                "timeout": 4000,
                "resources": ["stream"],
                "mediaTypes": [],
                "services": ["easynews"],
                "useMultipleInstances": False
            }
        }
    ]
    for target in anime_and_usenet:
        if not any(p.get("type") == target["type"] for p in presets):
            presets.append(target)

    # Ensure Usenet indexers are provisioned as direct Newznab presets in AIOStreams.
    # Keep portal-managed identities stable when addresses change; custom presets
    # with unrelated endpoints remain under the user's control.
    active_managed_newznab_ids = set()
    if usenet_active:
        rows = newznab_indexers(os.environ)
        seen_endpoints = set()
        for row_number, row in enumerate(rows):
            raw_url = str(row.get('url') or '').strip().rstrip('/')
            if not raw_url:
                continue
            api_url = newznab_endpoint(raw_url)
            if api_url in seen_endpoints:
                continue
            seen_endpoints.add(api_url)
            parsed = urllib.parse.urlsplit(raw_url)
            domain = parsed.netloc.lower().split(':')[0]
            for prefix in ('api.', 'www.', 'nzb.'):
                if domain.startswith(prefix):
                    domain = domain[len(prefix):]
            slug = domain.split('.')[0] if domain else "indexer"
            port = parsed.port
            name_suffix = f" ({port})" if port and port not in (80, 443) else ""
            label = "altHUB" if "althub" in domain else ("DrunkenSlug" if "drunkenslug" in domain else ("Anime Tosho" if "animetosho" in domain else slug.capitalize()))
            if row_number == 0 and row.get('id') == '' and os.environ.get('NZB_INDEXER_URL') and os.environ.get('NZB_INDEXER_API_KEY'):
                instance_id = 'newznab-managed-primary'
            else:
                identity = 'row:' + str(row['id']) if row.get('id') else 'endpoint:' + api_url
                instance_id = 'newznab-managed-' + hashlib.sha256(identity.encode()).hexdigest()[:16]
            active_managed_newznab_ids.add(instance_id)
            existing = next((p for p in presets if p.get('type') == 'newznab' and p.get('instanceId') == instance_id), None)
            for candidate in presets if existing is None else []:
                if candidate.get('type') != 'newznab':
                    continue
                try:
                    candidate_url = newznab_endpoint(candidate.get('options', {}).get('api', {}).get('url', ''))
                except ValueError:
                    continue
                if candidate_url == api_url:
                    existing = candidate
                    break
            if not existing:
                presets.append({
                    "type": "newznab",
                    "instanceId": instance_id,
                    "enabled": True,
                    "options": {
                        "name": f"{label}{name_suffix} (Newznab Direct)",
                        "api": {
                            "url": api_url,
                            "apiKey": row.get('apiKey', '')
                        },
                        "services": ["aiostreams"],
                        "timeout": 8000,
                        "resources": ["stream"],
                        "useMultipleInstances": False
                    }
                })
            else:
                prior_id = existing.get('instanceId')
                if prior_id and prior_id != instance_id:
                    renamed_preset_ids[prior_id] = instance_id
                existing['instanceId'] = instance_id
                existing["enabled"] = True
                opts = existing.setdefault("options", {})
                opts["name"] = f"{label}{name_suffix} (Newznab Direct)"
                opts["api"] = {"url": api_url, "apiKey": row.get("apiKey", "")}
                opts["services"] = ["aiostreams"]
                opts["timeout"] = int(opts.get("timeout") or 8000)
                opts["resources"] = ["stream"]

    # Ensure Anime Kitsu is present for local Kitsu ID mapping
    if not any(p.get("instanceId") == "anime-kitsu-local" for p in presets):
        presets.append({
            "type": "custom",
            "instanceId": "anime-kitsu-local",
            "enabled": True,
            "options": {
                "name": "Anime Kitsu (Local)",
                "manifestUrl": "http://anime-kitsu:7000/manifest.json",
                "libraryAddon": False,
                "resultPassthrough": False,
                "forceToTop": False,
                "timeout": 8000
            }
        })

    # Ensure Bento (Unified Anime) preset is present
    bento_manifest_default = "https://bento.tweakapps.uk/eyJzb3VyY2VzIjp7Im55YWEiOnRydWUsImFuaWJ0Ijp0cnVlLCJhbmltZXRvc2hvIjpmYWxzZSwiYW5pcmVuYSI6ZmFsc2UsInNlYWRleCI6dHJ1ZSwidHN1a2loaW1lIjpmYWxzZSwidG9ycmVudGNsYXciOmZhbHNlLCJ0b2t5b3Rvc2hvIjpmYWxzZSwic3Vic3BsZWFzZSI6dHJ1ZSwibmVrb2J0IjpmYWxzZSwia25hYmVuIjp0cnVlLCJtaWthbiI6ZmFsc2UsImhpdmVpbmRleCI6dHJ1ZX19/manifest.json"
    bento_manifest = os.environ.get("BENTO_MANIFEST_URL", bento_manifest_default)
    if not any(p.get("instanceId") == "bento-anime" for p in presets):
        presets.append({
            "type": "custom",
            "instanceId": "bento-anime",
            "enabled": True,
            "options": {
                "name": "Bento (Unified Anime)",
                "manifestUrl": bento_manifest,
                "libraryAddon": False,
                "resultPassthrough": False,
                "forceToTop": False,
                "timeout": 4000
            }
        })

    if any(s.get('enabled') and s.get('id') not in ('aiostreams', 'easynews') for s in services):
        if not any(p.get("type") == "stremthruStore" for p in presets):
            presets.append({
                "type": "stremthruStore",
                "instanceId": "stremthru-store-local",
                "enabled": True,
                "options": {
                    "name": "StremThru Store (Local)",
                    "url": f"{STREMTHRU_URL}/stremio/store/",
                    "timeout": 3000,
                    "resources": ["catalog", "meta", "stream"],
                    "mediaTypes": [],
                    "hideStreams": False,
                    "webDl": False,
                    "usenet": False
                }
            })
        if not any(p.get("type") == "zilean" for p in presets):
            presets.append({
                "type": "zilean",
                "instanceId": "zilean-local",
                "enabled": os.environ.get("ENABLE_DMM", "true").lower() != "false",
                "options": {
                    "name": "Zilean DMM (Local)",
                    "url": ZILEAN_URL,
                    "timeout": 2500,
                    "resources": ["stream"],
                    "mediaTypes": [],
                    "useMultipleInstances": False
                }
            })

    subtitle_config = {"languages": ["eng"]}
    for env_key, config_key in (
        ("SUBDL_API_KEY", "subdlApiKey"),
        ("SUBSOURCE_API_KEY", "subsourceApiKey"),
        ("WYZIE_API_KEY", "wyzieApiKey"),
        ("OPENSUBTITLES_API_KEY", "openSubtitlesApiKey"),
    ):
        if os.environ.get(env_key):
            subtitle_config[config_key] = os.environ[env_key]
    # SubSense serves subtitle resources only beneath a configuration segment.
    subtitle_public = urllib.parse.quote(json.dumps({"languages": ["eng"]}), safe='')
    subtitle_url = f"http://subsense:3100/{subtitle_public}/manifest.json"
    if probe_services and reachable("http://subsense:3100/manifest.json", timeout=1.0):
        try:
            encrypted = make_request("http://subsense:3100/api/config/encrypt", method="POST", data={"config": subtitle_config})
            if isinstance(encrypted, dict) and encrypted.get("encrypted"):
                subtitle_url = f"http://subsense:3100/{urllib.parse.quote(encrypted['encrypted'], safe='')}/manifest.json"
        except Exception as e:
            print(f"[AIOStreams Setup] Note encrypting subtitle config: {e}", flush=True)


    # Post-process presets: verify reachability for custom manifests to prevent
    # AIOStreams from rejecting the profile with USER_INVALID_CONFIG on partial/core profiles.
    validated_presets = []
    for p in presets:
        if is_deprecated_preset(p):
            if isinstance(p, dict):
                if p.get("instanceId"):
                    removed_preset_ids.add(p["instanceId"])
                if p.get("type"):
                    removed_preset_ids.add(p["type"])
            continue
        ptype = p.get("type")
        pid = p.get("instanceId", "")
        opts = p.setdefault("options", {})
        if ptype == "torrentio":
            if not any(s.get('enabled') and s.get('id') not in ('aiostreams', 'easynews') for s in services):
                continue
            opts["name"] = "Torrentio"
            opts["timeout"] = SCRAPER_TIMEOUT_MS
            custom_url = os.environ.get("TORRENTIO_URL") or os.environ.get("KNIGHTCRAWLER_URL", "")
            if custom_url:
                opts["url"] = custom_url
                opts["name"] = "Torrentio (custom)"
            enable_t = os.environ.get("ENABLE_TORRENTIO", os.environ.get("ENABLE_KNIGHTCRAWLER", "true")).lower() != "false"
            p["enabled"] = enable_t
            validated_presets.append(p)
        elif ptype == "newznab":
            if not usenet_active:
                if pid:
                    removed_preset_ids.add(pid)
                continue
            if not str(pid or '').startswith('newznab-managed-'):
                validated_presets.append(p)
                continue
            if pid not in active_managed_newznab_ids:
                removed_preset_ids.add(pid)
                continue
            p["enabled"] = True
            opts["timeout"] = int(opts.get("timeout") or 8000)
            opts["services"] = ["aiostreams"]
            opts["resources"] = ["stream"]
            print(f"[AIOStreams Setup] ✓ Direct Newznab indexer active: {opts.get('name', pid)}", flush=True)
            validated_presets.append(p)
        elif ptype == "prowlarr":
            sources = opts.get("sources", [])
            if "torrent" in sources:
                if not any(s.get('enabled') and s.get('id') not in ('aiostreams', 'easynews') for s in services):
                    continue
                opts.setdefault("name", "Prowlarr Torrents")
                opts.setdefault("url", PROWLARR_URL)
                opts.setdefault("prowlarrUrl", PROWLARR_URL)
                opts.setdefault("prowlarrApiKey", PROWLARR_API_KEY)
                opts["sources"] = ["torrent"]
                opts["timeout"] = int(opts.get("timeout") or SCRAPER_TIMEOUT_MS)
                p["enabled"] = True
                print("[AIOStreams Setup] ✓ Prowlarr Torrents is active (dedicated to torrents).", flush=True)
                validated_presets.append(p)
            elif "usenet" in sources:
                is_u_enabled = os.environ.get("USENET_ENABLED", "false").lower() == "true" or bool(USENET_ENABLED)
                has_direct_newznab = any(p2.get("type") == "newznab" and p2.get("enabled") for p2 in presets)
                if not is_u_enabled:
                    if pid:
                        removed_preset_ids.add(pid)
                    continue
                if has_direct_newznab:
                    # Direct Newznab presets handle Usenet indexers ~60x faster.
                    # Move Usenet off Prowlarr to keep Prowlarr dedicated to torrents.
                    print("[AIOStreams Setup] Moving Usenet off Prowlarr onto direct Newznab presets for ~60x faster search.", flush=True)
                    if pid:
                        removed_preset_ids.add(pid)
                    continue
                p["enabled"] = True
                opts.setdefault("name", "Usenet (Prowlarr → AIOStreams)")
                opts.setdefault("prowlarrUrl", PROWLARR_URL)
                opts.setdefault("prowlarrApiKey", PROWLARR_API_KEY)
                opts.setdefault("services", ["aiostreams"])
                opts.setdefault("sources", ["usenet"])
                opts["timeout"] = int(opts.get("timeout") or SCRAPER_TIMEOUT_MS)
                validated_presets.append(p)
            else:
                validated_presets.append(p)
        elif ptype == "knaben":
            if not any(s.get('enabled') and s.get('id') not in ('aiostreams', 'easynews') for s in services):
                if pid:
                    removed_preset_ids.add(pid)
                continue
            p["enabled"] = True
            opts["name"] = "Knaben (Anime)"
            opts["mediaTypes"] = ["anime"]
            opts["timeout"] = int(opts.get("timeout") or SCRAPER_TIMEOUT_MS)
            validated_presets.append(p)
        elif ptype == "stremthruTorz":
            if pid:
                removed_preset_ids.add(pid)
            continue
        elif ptype == "stremthruStore":
            if not any(s.get('enabled') and s.get('id') not in ('aiostreams', 'easynews') for s in services):
                if pid:
                    removed_preset_ids.add(pid)
                continue
            opts["timeout"] = 2500
            if reachable(f"{STREMTHRU_URL}/stremio/store/manifest.json", timeout=1.0):
                p["enabled"] = True
                print("[AIOStreams Setup] ✓ StremThru Store (Debrid Cloud Library) is online and active.", flush=True)
                validated_presets.append(p)
            else:
                p["enabled"] = False
                print("[AIOStreams Setup] ℹ️ StremThru Store is unreachable; preset omitted. Check its container and Docker network.", flush=True)
                if pid:
                    removed_preset_ids.add(pid)
        elif ptype == "easynews-search":
            p["enabled"] = bool(EASYNEWS_USER and EASYNEWS_PASSWORD)
            # Direct EasyNews delivery owns this account.
            opts['services']=['easynews']
            opts['useMultipleInstances']=False
            opts['paginate']=False
            opts["timeout"] = int(opts.get("timeout") or SCRAPER_TIMEOUT_MS)
            opts["services"] = ["easynews"]
            if p["enabled"]:
                print("[AIOStreams Setup] ✓ Easynews Search (Built-in) is active.", flush=True)
            else:
                print("[AIOStreams Setup] ℹ️ Easynews credentials not provided; preset disabled.", flush=True)
            validated_presets.append(p)
        elif ptype in ("anime-tosho-new", "tsukihime", "neko-bt"):
            compatible={'alldebrid','debrider','debridlink','easydebrid','offcloud','premiumize','pikpak','realdebrid','torbox','torrin'}
            selected=[s['id'] for s in services if s.get('enabled') and s['id'] in compatible]
            anime_flag = (
                os.environ.get('ENABLE_ANIME_SOURCES', 'false').lower() == 'true'
                or 'anime' in (os.environ.get('AIOMETADATA_TEMPLATE') or '').lower()
                or is_anime_variant
            )
            anime_enabled = (
                anime_flag
                or (not is_usenet_only and bool(p.get("enabled", False)) and os.environ.get('ENABLE_ANIME_SOURCES', '').lower() != 'false')
            )
            p["enabled"] = bool(anime_enabled and selected)
            opts['services']=selected
            opts['mediaTypes']=['anime']
            opts['useMultipleInstances']=False
            opts["timeout"] = int(opts.get("timeout") or SCRAPER_TIMEOUT_MS)
            validated_presets.append(p)
        elif ptype == "zilean":
            if not any(s.get('enabled') and s.get('id') not in ('aiostreams', 'easynews') for s in services):
                if pid:
                    removed_preset_ids.add(pid)
                continue
            opts["url"] = ZILEAN_URL
            opts["timeout"] = int(opts.get("timeout") or 2000)
            dmm_enabled = os.environ.get("ENABLE_DMM", "true").lower() != "false"
            if dmm_enabled and (not probe_services or reachable(f"{ZILEAN_URL}/dmm/filtered?query=ping", timeout=1.0)):
                p["enabled"] = True
                print("[AIOStreams Setup] ✓ Zilean DMM (Local) is online and active.", flush=True)
                validated_presets.append(p)
            else:
                p["enabled"] = False
                print("[AIOStreams Setup] ℹ️ Zilean is unreachable or DMM disabled; preset omitted.", flush=True)
                if pid:
                    removed_preset_ids.add(pid)
        elif ptype == "torznab":
            if not any(s.get('enabled') and s.get('id') not in ('aiostreams', 'easynews') for s in services):
                if pid:
                    removed_preset_ids.add(pid)
                continue
            opts["timeout"] = int(opts.get("timeout") or SCRAPER_TIMEOUT_MS)
            api_sub = opts.get("api") if isinstance(opts.get("api"), dict) else {}
            torznab_url = api_sub.get("url") or opts.get("url") or opts.get("torznabUrl")
            if not torznab_url:
                if pid:
                    removed_preset_ids.add(pid)
                continue
            api_key = api_sub.get("apiKey") or opts.get("apiKey") or ""
            opts["api"] = {
                "url": torznab_url,
                "apiKey": api_key,
            }
            opts["url"] = torznab_url
            opts["torznabUrl"] = torznab_url

            if probe_services and not reachable(torznab_url, timeout=1.0):
                print(f"[AIOStreams Setup] ℹ️ Torznab indexer {opts.get('name') or pid} is unreachable; preset omitted.", flush=True)
                if pid:
                    removed_preset_ids.add(pid)
                continue

            p["enabled"] = True
            print(f"[AIOStreams Setup] ✓ Torznab preset ({opts.get('name') or pid}) is online and active.", flush=True)
            validated_presets.append(p)
        elif ptype == "custom":
            # For custom addons, verify reachability before sending to AIOStreams.
            # AIOStreams fetches manifests on startup/save and rejects the entire profile
            # with USER_INVALID_CONFIG if any custom manifest cannot be retrieved.
            if pid == "aiometadata-local" or ("aiometadata" in pid):
                if not aiometadata_manifest:
                    print("[AIOStreams Setup] AIOMetadata has no saved profile; omitting its unconfigured manifest.", flush=True)
                    continue
                opts["manifestUrl"] = aiometadata_manifest
                opts["resources"] = ["catalog", "meta"]
                if reachable(aiometadata_manifest, timeout=1.0):
                    p["enabled"] = True
                    print(f"[AIOStreams Setup] ✓ AIOMetadata (Local) is online and active: {aiometadata_manifest}", flush=True)
                    validated_presets.append(p)
                else:
                    print(f"[AIOStreams Setup] ℹ️ AIOMetadata manifest not reachable ({aiometadata_manifest}); omitting from active presets.", flush=True)
            elif pid == "subsense-local":
                opts["manifestUrl"] = subtitle_url
                opts["resources"] = ["subtitles"]
                if reachable(subtitle_url, timeout=1.0):
                    p["enabled"] = True
                    print(f"[AIOStreams Setup] ✓ SubSense Subtitles (Local) is online and active.", flush=True)
                    validated_presets.append(p)
                else:
                    print(f"[AIOStreams Setup] ℹ️ SubSense is unreachable; omitting from active presets. Check its container and Docker network.", flush=True)
            elif pid == "anime-kitsu-local":
                opts["resources"] = ["catalog", "meta"]
                murl = opts.get("manifestUrl", "http://anime-kitsu:7000/manifest.json")
                if reachable(murl, timeout=1.0):
                    p["enabled"] = True
                    print(f"[AIOStreams Setup] ✓ Anime Kitsu (Local) is online and active.", flush=True)
                    validated_presets.append(p)
                else:
                    print(f"[AIOStreams Setup] ℹ️ Anime Kitsu not reachable; omitting from active presets.", flush=True)
            elif pid == "bento-anime" or "bento" in pid:
                murl = opts.get("manifestUrl") or bento_manifest
                opts["manifestUrl"] = murl
                opts["resources"] = ["stream"]
                opts["resultPassthrough"] = False
                opts["mediaTypes"] = ["anime"]
                enable_bento = os.environ.get("ENABLE_BENTO", "true").lower() != "false"
                has_debrid = any(s.get('enabled') and s.get('id') not in ('aiostreams', 'easynews') for s in services)
                if not enable_bento:
                    print(f"[AIOStreams Setup] ℹ️ Bento Anime Indexer disabled via configuration.", flush=True)
                elif not has_debrid:
                    print(f"[AIOStreams Setup] ℹ️ Bento Anime Indexer requires debrid services; omitting preset.", flush=True)
                elif reachable(murl, timeout=2.0):
                    p["enabled"] = True
                    print(f"[AIOStreams Setup] ✓ Bento Anime Indexer is online and active.", flush=True)
                    validated_presets.append(p)
                else:
                    print(f"[AIOStreams Setup] ℹ️ Bento Anime Indexer manifest unreachable ({murl}); omitting from active presets.", flush=True)
            else:
                murl = opts.get("manifestUrl")
                if murl and reachable(murl, timeout=1.0):
                    print(f"[AIOStreams Setup] ✓ Custom addon '{pid}' ({murl}) is online and active.", flush=True)
                    validated_presets.append(p)
                else:
                    print(f"[AIOStreams Setup] ℹ️ Custom addon '{pid}' ({murl}) is unreachable; omitting from active presets.", flush=True)
        else:
            validated_presets.append(p)

    for p in presets:
        if p not in validated_presets and isinstance(p, dict):
            if p.get("instanceId"):
                removed_preset_ids.add(p["instanceId"])
            if p.get("type") and p.get("type") != "custom":
                removed_preset_ids.add(p["type"])

    validated_presets = [p for p in validated_presets if not is_deprecated_preset(p)]
    # Order Usenet presets first so NZB indexers are queried and resolved with priority
    usenet_presets = [p for p in validated_presets if p.get("type") == "newznab" or p.get("instanceId") == "prowlarr-usenet"]
    other_presets = [p for p in validated_presets if p not in usenet_presets]
    validated_presets = usenet_presets + other_presets
    valid_preset_ids = {p.get("instanceId") for p in validated_presets if isinstance(p, dict) and p.get("instanceId")}
    valid_preset_types = {p.get("type") for p in validated_presets if isinstance(p, dict) and p.get("type")}

    config = dict(base_config)
    # Configure BuiltinProxy so internal Docker scraper streams
    # resolve and stream properly through AIOStreams over the single public port (3001)
    existing_proxy = base_config.get("proxy") if isinstance(base_config.get("proxy"), dict) else {}
    if existing_proxy.get("credentials") in ("admin:admin", "admin:", "", None):
        proxy_creds = f"admin:{ADDON_PASSWORD}" if ADDON_PASSWORD else "admin:admin"
    else:
        proxy_creds = existing_proxy.get("credentials") or (f"admin:{ADDON_PASSWORD}" if ADDON_PASSWORD else "admin:admin")

    target_proxy_url = BASE_URL or "http://aiostreams:3000"
    if existing_proxy.get("url") in ("http://localhost:3001", "http://127.0.0.1:3001", "", None) and BASE_URL:
        proxy_url = BASE_URL
    else:
        proxy_url = existing_proxy.get("url") or target_proxy_url

    proxy_host = urllib.parse.urlsplit(BASE_URL or "").hostname
    proxy_is_public = bool(
        proxy_host
        and proxy_host not in ("localhost", "127.0.0.1", "aiostreams")
        and "." in proxy_host
        and not proxy_host.endswith((".local", ".lan"))
    )
    config["proxy"] = {
        "id": existing_proxy.get("id") or "builtin",
        "enabled": proxy_is_public,
        "url": proxy_url,
        "credentials": proxy_creds,
        "proxiedServices": ["realdebrid", "premiumize", "alldebrid", "torbox", "debridlink", "easynews", "aiostreams", "none"]
    }

    config["addonName"] = "AIOStreams (All-Local Self-Hosted - Tamtaro SEL)"
    config["accessKey"] = os.environ.get("CONFIG_ACCESS_KEY") or ADDON_PASSWORD
    config["addonDescription"] = "Unified all-in-one local scraper & debrid super-addon powered by Tamtaro SEL sorting, Vidhin regexes, Seadex, Posters+, and local containers."
    config["services"] = services
    config["presets"] = validated_presets

    # Clean and sanitize groups in user configuration
    if "groups" in config and isinstance(config["groups"], dict):
        groupings = config["groups"].get("groupings")
        if isinstance(groupings, list):
            def is_removed_addon(addon):
                if not addon:
                    return True
                addon_str = str(addon)
                addon_lower = addon_str.lower()
                for target in DEPRECATED_PRESET_TARGETS:
                    if target in addon_lower:
                        return True
                if addon_str in removed_preset_ids:
                    return True
                if valid_preset_ids and (addon_str not in valid_preset_ids and addon_str not in valid_preset_types):
                    return True
                return False

            updated_groupings = []
            for g in groupings:
                if not isinstance(g, dict):
                    continue
                addons = g.get("addons")
                if isinstance(addons, list):
                    remapped_addons = [renamed_preset_ids.get(a, a) if isinstance(a, str) else a for a in addons]
                    filtered_addons = [a for a in remapped_addons if not is_removed_addon(a)]
                    g["addons"] = filtered_addons
                    if not filtered_addons:
                        continue
                else:
                    continue
                updated_groupings.append(g)

            config["groups"]["groupings"] = updated_groupings
            if not updated_groupings:
                config["groups"]["enabled"] = False
        else:
            config["groups"]["groupings"] = []
            config["groups"]["enabled"] = False
    elif "groups" in config and not isinstance(config["groups"], dict):
        config.pop("groups", None)

    # Sanitize formatter to ensure compliance with AIOStreams schema
    if "formatter" in config and isinstance(config["formatter"], dict):
        f = config["formatter"]
        if "definition" in f and "definitions" not in f:
            f["definitions"] = {"custom": f.pop("definition")}
        elif "definitions" in f and isinstance(f["definitions"], dict) and "custom" in f["definitions"]:
            pass
        elif f.get("id") != "custom":
            pass
        else:
            f["id"] = "tamtaro"
            f.pop("definitions", None)
            f.pop("definition", None)

    # Ensure Tamtaro SEL & Regex URLs are present and verified
    config["syncedExcludedRegexUrls"] = ["https://raw.githubusercontent.com/Tam-Taro/SEL-Filtering-and-Sorting/refs/heads/main/AIOStreams-SyncedURLs/Tamtaro-synced-excluded-regex.json"]
    config["syncedRankedRegexUrls"] = ["https://raw.githubusercontent.com/Vidhin05/Releases-Regex/main/English/regexes.json"]
    config["syncedPreferredStreamExpressionUrls"] = ["https://raw.githubusercontent.com/Tam-Taro/SEL-Filtering-and-Sorting/refs/heads/main/AIOStreams-SyncedURLs/Tamtaro-synced-PSEs.json"]
    config["syncedExcludedStreamExpressionUrls"] = ["https://raw.githubusercontent.com/Tam-Taro/SEL-Filtering-and-Sorting/refs/heads/main/AIOStreams-SyncedURLs/Tamtaro-synced-ESEs-standard.json"]
    config["syncedRankedStreamExpressionUrls"] = ["https://raw.githubusercontent.com/Vidhin05/Releases-Regex/main/English/expressions.json"]
    config["enableSeadex"] = True

    # Activate AIOStreams upstream features
    # Warm search results only. An empty selector prevents automatic stream pings
    # and debrid downloads after the background search has completed.
    config["precacheNextEpisode"] = os.environ.get('AIO_PRECACHE_NEXT_EPISODE','true').strip().lower() == 'true'
    config["precacheSelector"] = "[]"
    config.pop('precacheCondition',None)
    config.pop('alwaysPrecache',None)
    has_debrid_active = any(s.get('enabled') and s.get('id') not in ('aiostreams', 'easynews') for s in services)
    if not has_debrid_active and usenet_active:
        config.setdefault("cacheAndPlay", {"enabled": True, "streamTypes": ["usenet"]})
    else:
        config.setdefault("cacheAndPlay", {"enabled": True, "streamTypes": ["torrent", "usenet"]})
    enable_remuxdb = os.environ.get("ENABLE_REMUXDB", "true").lower() != "false"
    config["remuxDb"] = {"enabled": enable_remuxdb}
    config.setdefault("titleMatching", {"enabled": True, "mode": "contains", "similarityThreshold": 0.85})
    config.setdefault("seasonEpisodeMatching", {"enabled": True, "strict": False})
    config.setdefault("episodeTitleMatching", {"enabled": True, "similarityThreshold": 0.8})
    config.setdefault("yearMatching", {"enabled": True, "tolerance": 1})
    config.setdefault("languageInference", {"enabled": True, "sources": ["title", "episodeTitle"]})
    if not has_debrid_active and usenet_active:
        config.setdefault("failover", {
            "enabled": True,
            "contentTypes": ["usenet"],
            "allowCrossType": False,
            "maxAttempts": 3,
            "includeExternalFailover": True,
            "precacheFailover": True,
        })
    else:
        config.setdefault("failover", {
            "enabled": True,
            "contentTypes": ["debrid", "usenet"],
            "allowCrossType": True,
            "maxAttempts": 3,
            "includeExternalFailover": True,
            "precacheFailover": True,
        })
    if "deduplicator" in config and isinstance(config["deduplicator"], dict):
        config["deduplicator"].setdefault("merge", {
            "enabled": True,
            "failoverVariants": True,
            "fields": ["languages", "seadex", "library", "subtitles", "sizes", "idMatched"],
        })

    # Ensure preferredStreamTypes prioritizes Usenet streams ahead of Debrid for playback stability
    config["preferredStreamTypes"] = ["usenet", "stremio-usenet", "debrid"]

    if "sortCriteria" in config and isinstance(config["sortCriteria"], dict):
        glob_sort = config["sortCriteria"].get("global", [])
        if isinstance(glob_sort, list):
            has_library = any(item.get("key") == "library" for item in glob_sort if isinstance(item, dict))
            if not has_library:
                cached_idx = -1
                for i, item in enumerate(glob_sort):
                    if isinstance(item, dict) and item.get("key") == "cached":
                        cached_idx = i
                        break
                library_entry = {"key": "library", "direction": "desc"}
                if cached_idx >= 0:
                    glob_sort.insert(cached_idx + 1, library_entry)
                else:
                    glob_sort.insert(0, library_entry)

            has_stream_type = any(item.get("key") == "streamType" for item in glob_sort if isinstance(item, dict))
            if not has_stream_type:
                ref_idx = -1
                for i, item in enumerate(glob_sort):
                    if isinstance(item, dict) and item.get("key") in ("library", "cached"):
                        ref_idx = i
                stream_type_entry = {"key": "streamType", "direction": "desc"}
                if ref_idx >= 0:
                    glob_sort.insert(ref_idx + 1, stream_type_entry)
                else:
                    glob_sort.insert(0, stream_type_entry)
            config["sortCriteria"]["global"] = glob_sort

    # Inject metadata API keys into AIOStreams user configuration
    global TMDB_API_KEY, TVDB_API_KEY
    if not (TMDB_API_KEY and TVDB_API_KEY):
        load_env_file()
        TMDB_API_KEY = os.environ.get("TMDB_API_KEY", TMDB_API_KEY)
        TVDB_API_KEY = os.environ.get("TVDB_API_KEY", TVDB_API_KEY)

    if TMDB_API_KEY:
        config["tmdbApiKey"] = TMDB_API_KEY
        for feature in ('titleMatching', 'yearMatching'):
            if isinstance(config.get(feature), dict):
                config[feature]['enabled'] = True
            else:
                config[feature] = {'enabled': True}
    else:
        config["precacheNextEpisode"] = False
        for feature in ('titleMatching','yearMatching','digitalReleaseFilter'):
            if isinstance(config.get(feature),dict):
                config[feature]['enabled']=False
        if isinstance(config.get('bitrate'),dict):
            config['bitrate']['useMetadataRuntime']=False
    # Probe 2 candidates concurrently on stream failover for rapid fallback recovery
    if isinstance(config.get('failover'),dict):
        config['failover']['parallel']=2
        config['failover']['precacheFailover']=False

    # Sync user player preferences (audio and subtitle languages)
    prefs_path = os.path.join(os.environ.get("WEB_ROOT", "."), "data", "player_preferences.json")
    if not os.path.isfile(prefs_path):
        prefs_path = os.path.join("data", "player_preferences.json")
    if os.path.isfile(prefs_path):
        try:
            with open(prefs_path, "r", encoding="utf-8") as pf:
                prefs_data = json.load(pf)
                user_audio = prefs_data.get("audioLanguage") or prefs_data.get("audio_language")
                user_sub = prefs_data.get("subtitleLanguage") or prefs_data.get("subtitle_language")
                aiostreams_lang_map = {
                    "english": "English", "eng": "English", "en": "English",
                    "japanese": "Japanese", "jpn": "Japanese", "ja": "Japanese",
                    "chinese": "Chinese", "chi": "Chinese", "zho": "Chinese", "zh": "Chinese",
                    "russian": "Russian", "rus": "Russian", "ru": "Russian",
                    "arabic": "Arabic", "ara": "Arabic", "ar": "Arabic",
                    "portuguese": "Portuguese", "por": "Portuguese", "pt": "Portuguese",
                    "portuguese (brazil)": "Portuguese (Brazil)", "pt-br": "Portuguese (Brazil)",
                    "spanish": "Spanish", "spa": "Spanish", "es": "Spanish",
                    "french": "French", "fre": "French", "fra": "French", "fr": "French",
                    "german": "German", "ger": "German", "deu": "German", "de": "German",
                    "italian": "Italian", "ita": "Italian", "it": "Italian",
                    "korean": "Korean", "kor": "Korean", "ko": "Korean",
                    "hindi": "Hindi", "hin": "Hindi", "hi": "Hindi",
                    "bengali": "Bengali", "ben": "Bengali", "bn": "Bengali",
                    "punjabi": "Punjabi", "pan": "Punjabi", "pa": "Punjabi",
                    "marathi": "Marathi", "mar": "Marathi", "mr": "Marathi",
                    "gujarati": "Gujarati", "guj": "Gujarati", "gu": "Gujarati",
                    "tamil": "Tamil", "tam": "Tamil", "ta": "Tamil",
                    "telugu": "Telugu", "tel": "Telugu", "te": "Telugu",
                    "kannada": "Kannada", "kan": "Kannada", "kn": "Kannada",
                    "malayalam": "Malayalam", "mal": "Malayalam", "ml": "Malayalam",
                    "thai": "Thai", "tha": "Thai", "th": "Thai",
                    "vietnamese": "Vietnamese", "vie": "Vietnamese", "vi": "Vietnamese",
                    "indonesian": "Indonesian", "ind": "Indonesian", "id": "Indonesian",
                    "turkish": "Turkish", "tur": "Turkish", "tr": "Turkish",
                    "hebrew": "Hebrew", "heb": "Hebrew", "he": "Hebrew",
                    "persian": "Persian", "fas": "Persian", "per": "Persian", "fa": "Persian",
                    "ukrainian": "Ukrainian", "ukr": "Ukrainian", "uk": "Ukrainian",
                    "greek": "Greek", "gre": "Greek", "ell": "Greek", "el": "Greek",
                    "lithuanian": "Lithuanian", "lit": "Lithuanian", "lt": "Lithuanian",
                    "latvian": "Latvian", "lav": "Latvian", "lv": "Latvian",
                    "estonian": "Estonian", "est": "Estonian", "et": "Estonian",
                    "polish": "Polish", "pol": "Polish", "pl": "Polish",
                    "czech": "Czech", "ces": "Czech", "cze": "Czech", "cs": "Czech",
                    "slovak": "Slovak", "slk": "Slovak", "slo": "Slovak", "sk": "Slovak",
                    "hungarian": "Hungarian", "hun": "Hungarian", "hu": "Hungarian",
                    "romanian": "Romanian", "ron": "Romanian", "rum": "Romanian", "ro": "Romanian",
                    "bulgarian": "Bulgarian", "bul": "Bulgarian", "bg": "Bulgarian",
                    "serbian": "Serbian", "srp": "Serbian", "sr": "Serbian",
                    "croatian": "Croatian", "hrv": "Croatian", "hr": "Croatian",
                    "slovenian": "Slovenian", "slv": "Slovenian", "sl": "Slovenian",
                    "dutch": "Dutch", "dut": "Dutch", "nld": "Dutch", "nl": "Dutch",
                    "danish": "Danish", "dan": "Danish", "da": "Danish",
                    "finnish": "Finnish", "fin": "Finnish", "fi": "Finnish",
                    "swedish": "Swedish", "swe": "Swedish", "sv": "Swedish",
                    "norwegian": "Norwegian", "nor": "Norwegian", "no": "Norwegian",
                    "malay": "Malay", "msa": "Malay", "may": "Malay", "ms": "Malay",
                    "latino": "Latino", "dual audio": "Dual Audio", "dubbed": "Dubbed",
                    "multi": "Multi", "original": "Original", "unknown": "Unknown"
                }
                if user_audio and isinstance(user_audio, str):
                    matched_audio = aiostreams_lang_map.get(user_audio.strip().lower())
                    if matched_audio:
                        config["preferredLanguages"] = [matched_audio]
                if user_sub and isinstance(user_sub, str):
                    matched_sub = aiostreams_lang_map.get(user_sub.strip().lower())
                    if matched_sub:
                        config["preferredSubtitleLanguages"] = [matched_sub]
        except Exception:
            pass

    # TVDB is consumed by AIOMetadata. Do not make AIOStreams registration
    # depend on an optional TVDB endpoint or key being reachable.

    return config

def get_aiostreams_auth_headers(base_url=None):
    target = (base_url or AIOSTREAMS_URL).rstrip("/")
    auth_bytes = f"admin:{ADDON_PASSWORD}".encode("utf-8")
    headers = {
        "Authorization": f"Basic {base64.b64encode(auth_bytes).decode('ascii')}",
        "Content-Type": "application/json"
    }
    try:
        login_url = f"{target}/api/v1/auth/login"
        login_payload = json.dumps({"username": "admin", "password": ADDON_PASSWORD}).encode("utf-8")
        req = urllib.request.Request(login_url, data=login_payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            set_cookies = resp.headers.get_all("Set-Cookie") or [resp.headers.get("Set-Cookie")]
            cookie_parts = [c.split(";")[0] for c in set_cookies if c]
            if cookie_parts:
                headers["Cookie"] = "; ".join(cookie_parts)
    except Exception:
        pass
    return headers

def aiostreams_profile_headers(uuid, password):
    encoded = base64.b64encode(f"{uuid}:{password}".encode()).decode("ascii")
    return {"Authorization": f"Basic {encoded}"}


def unlock_aiostreams_profile(uuid, encrypted_password):
    endpoint = f"{AIOSTREAMS_URL}/api/v1/user"
    previous = os.environ.get("AIO_PASSWORD_PREVIOUS")
    candidates = dict.fromkeys(filter(None, (ADDON_PASSWORD, previous, "admin_local_secret")))
    for password in candidates:
        headers = aiostreams_profile_headers(uuid, password)
        response = make_request(endpoint, headers=headers)
        if not isinstance(response, dict) or not response.get("success"):
            continue
        if not previous:
            return password, encrypted_password
        if password != ADDON_PASSWORD:
            response = make_request(endpoint + "/password", method="POST", headers=headers,
                                    data={"newPassword": ADDON_PASSWORD})
            if not isinstance(response, dict) or not response.get("success"):
                raise RuntimeError("AIOStreams could not change the saved profile password")
        token = (response.get("data") or {}).get("encryptedPassword")
        if not token:
            raise RuntimeError("AIOStreams did not return an updated profile link")
        return ADDON_PASSWORD, token
    raise RuntimeError("AIOStreams could not unlock the saved profile")


def setup_aiostreams_default_user(aiometadata_manifest=None):
    print("[AIOStreams Setup] Configuring default out-of-the-box configuration with Tamtaro & Debrid...", flush=True)

    auth_headers = get_aiostreams_auth_headers()

    uuid = None
    encrypted_password = None
    profile_password = ADDON_PASSWORD

    # Check candidates for existing install info
    for candidate in [
        os.path.join(DATA_AIOSTREAMS, "aiostreams_install.json"),
        "/data/aiostreams_install.json",
        "/data/aiostreams/aiostreams_install.json"
    ]:
        if os.path.isfile(candidate):
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                    enc_cand = cdata.get("encrypted_password") or cdata.get("encryptedPassword")
                    if cdata.get("uuid") and enc_cand:
                        uuid = cdata.get("uuid")
                        encrypted_password = enc_cand
                        break
            except Exception:
                pass

    if not uuid:
        # Check existing profiles in AIOStreams session
        existing_profiles = make_request(f"{AIOSTREAMS_URL}/api/v1/profiles", headers=auth_headers)
        p_list = []
        if isinstance(existing_profiles, dict):
            d_val = existing_profiles.get("data")
            p_list = d_val.get("profiles", []) if isinstance(d_val, dict) else (d_val if isinstance(d_val, list) else [])
        elif isinstance(existing_profiles, list):
            p_list = existing_profiles

        for p in p_list:
            if isinstance(p, dict) and p.get("uuid"):
                uuid = p.get("uuid")
                break

    # If still no user, create a new user configuration
    if not uuid or not encrypted_password:
        config = build_default_config(aiometadata_manifest=aiometadata_manifest)
        create_payload = {
            "config": config,
            "password": profile_password
        }

        res = make_request(f"{AIOSTREAMS_URL}/api/v1/user", method="POST", data=create_payload, headers=auth_headers)
        if isinstance(res, dict) and res.get("success") and isinstance(res.get("data"), dict):
            uuid = res["data"].get("uuid")
            encrypted_password = res["data"].get("encryptedPassword") or res["data"].get("encrypted_password")
            print(f"[AIOStreams Setup] ✓ Default user configuration registered successfully!", flush=True)
            print(f"[AIOStreams Setup]   UUID: {uuid}", flush=True)
        else:
            err = res.get("message", res) if isinstance(res, dict) else res
            print(f"[AIOStreams Setup] Note registering default user: {err}. Attempting fallback registration with standard tamtaro formatter...", flush=True)
            config["formatter"] = {"id": "tamtaro"}
            create_payload["config"] = config
            res2 = make_request(f"{AIOSTREAMS_URL}/api/v1/user", method="POST", data=create_payload, headers=auth_headers)
            if isinstance(res2, dict) and res2.get("success") and isinstance(res2.get("data"), dict):
                uuid = res2["data"].get("uuid")
                encrypted_password = res2["data"].get("encryptedPassword") or res2["data"].get("encrypted_password")
                print(f"[AIOStreams Setup] ✓ Fallback user configuration registered successfully!", flush=True)
                print(f"[AIOStreams Setup]   UUID: {uuid}", flush=True)
            else:
                print(f"[AIOStreams Setup] ⚠️ User registration failed: {res2}", flush=True)
    else:
        # Existing user detected: update configuration with latest 20s timeouts and service credentials
        try:
            print("[AIOStreams Setup] Updating existing user configuration with 20s scraper timeouts and service keys...", flush=True)
            config = build_default_config(aiometadata_manifest=aiometadata_manifest)
            profile_password, encrypted_password = unlock_aiostreams_profile(uuid, encrypted_password)
            u_headers = aiostreams_profile_headers(uuid, profile_password)
            u_res = make_request(f"{AIOSTREAMS_URL}/api/v1/user", method="PUT", data={"config": config}, headers=u_headers)
            if isinstance(u_res, dict) and u_res.get("success"):
                print("[AIOStreams Setup] ✓ User configuration successfully updated with 20s timeouts!", flush=True)
            else:
                print(f"[AIOStreams Setup] Note on updating user config: {u_res}", flush=True)
                return {}
        except Exception as e:
            print(f"[AIOStreams Setup] Note updating existing user: {e}", flush=True)
            return {}

    # Ensure profile exists in session and has alias 'local'
    if uuid:
        existing_profiles = make_request(f"{AIOSTREAMS_URL}/api/v1/profiles", headers=auth_headers)
        p_list = []
        if isinstance(existing_profiles, dict):
            d_val = existing_profiles.get("data")
            p_list = d_val.get("profiles", []) if isinstance(d_val, dict) else (d_val if isinstance(d_val, list) else [])
        elif isinstance(existing_profiles, list):
            p_list = existing_profiles

        prof_id = None
        current_alias = None
        for p in p_list:
            if isinstance(p, dict) and p.get("uuid") == uuid:
                prof_id = p.get("id")
                current_alias = p.get("alias")
                break

        if not prof_id:
            profile_payload = {
                "uuid": uuid,
                "password": profile_password,
                "label": "All-Local Default"
            }
            p_res = make_request(f"{AIOSTREAMS_URL}/api/v1/profiles", method="POST", data=profile_payload, headers=auth_headers)
            if isinstance(p_res, dict) and "data" in p_res and isinstance(p_res["data"], dict):
                prof_id = p_res["data"].get("profile", {}).get("id")
            elif isinstance(p_res, dict) and p_res.get("id"):
                prof_id = p_res.get("id")

        if prof_id and current_alias != "local":
            patch_res = make_request(
                f"{AIOSTREAMS_URL}/api/v1/profiles/{prof_id}",
                method="PATCH",
                data={"alias": "local"},
                headers=auth_headers
            )
            print(f"[AIOStreams Setup] ✓ Linked alias 'local' on profile {prof_id}: {patch_res}", flush=True)

    if uuid and encrypted_password:
        update_env_file("ALIASED_CONFIGURATIONS", f"local:{uuid}:{encrypted_password}")
        update_env_file("DEFAULT_AIO_UUID", uuid)
        update_env_file("DEFAULT_AIO_ENCRYPTED_PASSWORD", encrypted_password)
        install_record = {
            "uuid": uuid,
            "encrypted_password": encrypted_password,
            "encryptedPassword": encrypted_password,
            "alias": "local",
            "base_url": BASE_URL
        }
        for path in [
            os.path.join(DATA_AIOSTREAMS, "aiostreams_install.json"),
            "/data/aiostreams_install.json",
            "/data/aiostreams/aiostreams_install.json"
        ]:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(install_record, f, indent=2)
                print(f"[AIOStreams Setup] ✓ Persisted install metadata to {path}", flush=True)
            except Exception:
                pass

    canonical_direct_manifest = f"{BASE_URL}/stremio/{uuid}/{encrypted_password}/manifest.json" if uuid and encrypted_password else None
    alias_manifest = f"{BASE_URL}/stremio/u/local/manifest.json"

    manifest_urls = []
    if uuid and encrypted_password:
        manifest_urls.append(f"{AIOSTREAMS_URL}/stremio/{uuid}/{encrypted_password}/manifest.json")
        manifest_urls.append(canonical_direct_manifest)
    manifest_urls.append(f"{AIOSTREAMS_URL}/stremio/u/local/manifest.json")
    manifest_urls.append(alias_manifest)

    return {
        "uuid": uuid,
        "encrypted_password": encrypted_password,
        "canonical_direct_manifest": canonical_direct_manifest,
        "alias_manifest": alias_manifest,
        "manifest_urls": manifest_urls
    }

# ==============================================================================
# 5. DIAGNOSTIC STREAM VERIFICATION TEST
# ==============================================================================
def run_stream_diagnostics(config_info, aiometadata_manifest=None):
    print("==================================================", flush=True)
    print("   Running Verification Test On Internal Server   ", flush=True)
    print("==================================================", flush=True)

    # 2. Test Posters+ Server
    print(f"[Test 1/4] Testing Posters+ server ({POSTERSPLUS_URL})...", flush=True)
    p_res = make_request(f"{POSTERSPLUS_URL}/?access_key={ADDON_PASSWORD}", timeout=2)
    if isinstance(p_res, dict) and (not p_res.get("error") or p_res.get("status") in (200, 301, 302) or "access_key" in str(p_res.get("text", "")) or "detail" in p_res or "access_key" in str(p_res)):
        print(f"[Test 1/4] ✓ Posters+ server is reachable and active!", flush=True)
    elif isinstance(p_res, dict) and p_res.get("error") == -1:
        print(f"[Test 1/4] ℹ️ Posters+ server is starting up or unreachable (optional metadata badge provider).", flush=True)
    else:
        err_msg = p_res.get("message", str(p_res)) if isinstance(p_res, dict) else str(p_res)
        print(f"[Test 1/4] ℹ️ Posters+ server status: {err_msg} (optional service)", flush=True)

    # 3. Test AIOMetadata Manifest
    aiom_target = aiometadata_manifest or f"{AIOMETADATA_URL}/manifest.json"
    print(f"[Test 2/4] Testing AIOMetadata manifest ({aiom_target})...", flush=True)
    aiom_res = make_request(aiom_target, timeout=2)
    if isinstance(aiom_res, dict) and "name" in aiom_res:
        print(f"[Test 2/4] ✓ AIOMetadata manifest verified: '{aiom_res.get('name')}' (v{aiom_res.get('version', '')})", flush=True)
    elif not aiometadata_manifest:
        print(f"[Test 2/4] ℹ️ AIOMetadata is optional and not active; manifest verification skipped.", flush=True)
    elif isinstance(aiom_res, dict) and aiom_res.get("error") == -1:
        print(f"[Test 2/4] ℹ️ AIOMetadata manifest is currently unreachable or starting up.", flush=True)
    else:
        err_msg = aiom_res.get("message", str(aiom_res)) if isinstance(aiom_res, dict) else str(aiom_res)
        print(f"[Test 2/4] ℹ️ AIOMetadata manifest response: {err_msg} (optional service)", flush=True)

    # 4. Test AIOStreams Manifest Availability (Both Direct & Alias)
    uuid = config_info.get("uuid")
    enc = config_info.get("encrypted_password")

    if uuid and enc:
        print(f"[Test 3/4] Testing Direct Canonical Manifest (/stremio/{uuid}/{enc[:8]}.../manifest.json)...", flush=True)
        direct_manifest = make_request(f"{AIOSTREAMS_URL}/stremio/{uuid}/{enc}/manifest.json")
        if isinstance(direct_manifest, dict) and "name" in direct_manifest:
            print(f"[Test 3/4] ✓ Direct UUID Manifest verified: '{direct_manifest.get('name')}' (v{direct_manifest.get('version')})", flush=True)
        else:
            print(f"[Test 3/4] Note retrieving direct manifest: {direct_manifest}", flush=True)

    print(f"[Test 3/4] Testing Vanity Alias Manifest (/stremio/u/local/manifest.json)...", flush=True)
    manifest = make_request(f"{AIOSTREAMS_URL}/stremio/u/local/manifest.json")
    if isinstance(manifest, dict) and "name" in manifest:
        print(f"[Test 3/4] ✓ Alias manifest successfully retrieved: '{manifest.get('name')}' (v{manifest.get('version')})", flush=True)
        print(f"[Test 3/4]   Supported resources: {manifest.get('resources')}", flush=True)
        print(f"[Test 3/4]   Supported types: {manifest.get('types')}", flush=True)
    else:
        print(f"[Test 3/4] Note on alias manifest (active after AIOStreams reload): {manifest}", flush=True)

    # 5. Test movie and episode stream resolution with the configured provider.
    for kind, content_id, label in CORE_SMOKE_CASES:
        print(f"[Test 5/6] Testing stream resolution for {label} '{content_id}'...", flush=True)
        stream_res = make_request(
            f"{AIOSTREAMS_URL}/stremio/u/local/stream/{kind}/{content_id}.json",
            timeout=25,
        )
        if (not isinstance(stream_res, dict) or "streams" not in stream_res) and uuid and enc:
            stream_res = make_request(
                f"{AIOSTREAMS_URL}/stremio/{uuid}/{enc}/stream/{kind}/{content_id}.json",
                timeout=25,
            )
        streams = playable_streams(stream_res)
        if not streams:
            print(f"[Test 5/6] No playable {label} stream resolved.", flush=True)
            return False
        print(f"[Test 5/6] Resolved {len(streams)} playable {label} stream candidates.", flush=True)
    return True


def playable_streams(response):
    if not isinstance(response, dict):
        return []
    return [stream for stream in response.get("streams", [])
            if isinstance(stream, dict) and (stream.get("url") or stream.get("infoHash") or stream.get("ytId"))
            and stream.get("url", "").rstrip("/") != "https://comet.feels.legal"]


CORE_SMOKE_CASES = (
    ("movie", "tt1375666", "movie"),
    ("series", "tt0903747:1:1", "episode"),
)

# ==============================================================================
# MAIN WORKFLOW
# ==============================================================================
def main():
    print("==================================================", flush=True)
    print("  AIOStreams Stack Bootstrapper & Auto-Provisioner ", flush=True)
    print("==================================================", flush=True)

    # Do not rewrite a saved profile when core networking/startup is broken.
    if not wait_for_aiostreams():
        print("[Setup] ERROR: AIOStreams is unavailable. No profile changes were attempted. Run stack-bootstrap on the same Compose network as aiostreams.", flush=True)
        return 1

    # 1. Prowlarr
    if wait_for_prowlarr():
        try:
            setup_prowlarr_auth()
            setup_prowlarr_flaresolverr()
            setup_prowlarr_indexers()
            tune_prowlarr_indexers()
            setup_usenet_indexer()
        except Exception as e:
            print(f"[Prowlarr Setup] Error: {e}", flush=True)

    # 2. Native AIOStreams Usenet Provider Sync
    try:
        sync_aiostreams_native_usenet()
    except Exception as e:
        print(f"[Usenet Setup] Note: {e}", flush=True)

    # 3. Posters+ & AIOMetadata (Tamtaro + Posters+)
    aiometadata_manifest = None
    try:
        aiometadata_manifest = setup_optional_metadata()
    except Exception as e:
        print(f"[AIOMetadata/Posters+ Setup] Error: {e}", flush=True)
        print("[AIOMetadata/Posters+ Setup] ℹ️ Continuing with AIOStreams providers only.", flush=True)

    if os.environ.get("AIO_PASSWORD_PREVIOUS") and os.environ.get("AIOMETADATA_PROFILE_UUID") and not aiometadata_manifest:
        print("[Setup] ERROR: The saved AIOMetadata profile could not be updated. Check its setup output and retry the password change.", flush=True)
        return 1

    # 5. AIOStreams Default User & Addon Configuration (Tamtaro All-Local)
    config_info = {}
    try:
        config_info = setup_aiostreams_default_user(aiometadata_manifest=aiometadata_manifest)
    except Exception as e:
        print(f"[AIOStreams Setup] Error: {e}", flush=True)

    if not config_info or not config_info.get("uuid") or not config_info.get("encrypted_password"):
        print("[Setup] ERROR: AIOStreams profile was not provisioned. Fix the error and rerun stack-bootstrap.", flush=True)
        return 1

    if os.environ.get("AIO_PASSWORD_PREVIOUS"):
        update_env_file("AIO_PASSWORD_PREVIOUS", "")

    # 7. Verification Diagnostics
    try:
        run_stream_diagnostics(config_info, aiometadata_manifest=aiometadata_manifest)
    except Exception as e:
        print(f"[Diagnostics] Note: {e}", flush=True)

    print("==================================================", flush=True)
    print("  Provisioning finished. Review diagnostic results; playback is not verified.", flush=True)
    print("==================================================", flush=True)

if __name__ == "__main__":
    sys.exit(main())
