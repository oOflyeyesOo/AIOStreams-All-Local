#!/usr/bin/env python3
"""
AIOStreams All-Local Unified Stack Bootstrapper & Auto-Provisioner
Automates zero-touch configuration across all stack services upon launch:
1. Prowlarr: Registers FlareSolverr Cloudflare bypass and auto-seeds top public torrent trackers.
3. Comet & InfiniDysk: Validates connectivity and internal routing.
4. AIOStreams: Automatically compiles and registers our ready-to-stream 'All-Local Self-Hosted'
   template (Comet, Torrentio, AIOMetadata, SubSense, InfiniDysk,
   and Debrid Search) with Premiumize & InfiniDysk credentials, mapped to alias '/stremio/u/local/manifest.json'.
5. Stremio Web: Pre-seeds local storage so the AIOStreams super-addon is already installed out-of-the-box.
6. Diagnostic Verification: Tests manifest and stream resolution on the internal Stremio engine.
"""
import os
import sys
import time
import json
import base64
import builtins
import re
import urllib.request
import urllib.error
import urllib.parse
import tempfile

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

PROWLARR_URL = os.environ.get("PROWLARR_URL", "http://prowlarr:9696").rstrip("/")
PROWLARR_API_KEY = os.environ.get("PROWLARR_API_KEY", "prowlarr_internal_secret_key_99")
FLARESOLVERR_URL = os.environ.get("FLARESOLVERR_URL", "http://flaresolverr:8191").rstrip("/")
COMET_URL = os.environ.get("COMET_URL", "http://comet:8000").rstrip("/")
INFINIDYSK_URL = os.environ.get("INFINIDYSK_URL", "http://infinidysk:3000").rstrip("/")
AIOSTREAMS_URL = os.environ.get("AIOSTREAMS_URL", "http://aiostreams:3000").rstrip("/")
STREMIO_WEB_URL = os.environ.get("STREMIO_WEB_URL", "http://stremio-web:8080").rstrip("/")
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
    update_env_file("AIOMETADATA_HOST", derived_aiom_url)

ADDON_PASSWORD = os.environ.get("ADDON_PASSWORD", "admin")
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

DATA_STREMIO_WEB = resolve_path("data/stremio-web", "/data/stremio-web")
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
    "kickasstorrents-ws",
    "badass-torrents",
    "torrentdownload",
    "nyaasi",
    "tokyotosho"
]

def make_request(url, method="GET", data=None, headers=None, timeout=12):
    default_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    if headers:
        default_headers.update(headers)
    body = json.dumps(data).encode("utf-8") if (data is not None and not isinstance(data, (bytes, bytearray))) else data
    req = urllib.request.Request(url, data=body, headers=default_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
            return json.loads(content) if content.strip().startswith(("{", "[")) else {"status": resp.status, "text": content}
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="ignore")
        return {"error": e.code, "message": err_msg}
    except Exception as e:
        return {"error": -1, "message": str(e)}

def is_url_reachable(url, timeout=2.0):
    if not url:
        return False
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AIOStreams-Probe/1.0", "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status in (200, 301, 302)
    except Exception:
        return False

# ==============================================================================
# 1. PROWLARR PROVISIONING
# ==============================================================================
def wait_for_prowlarr(max_attempts=15, interval=2):
    print(f"[Prowlarr Setup] Waiting for Prowlarr at {PROWLARR_URL}...", flush=True)
    headers = {"X-Api-Key": PROWLARR_API_KEY}
    for attempt in range(1, max_attempts + 1):
        res = make_request(f"{PROWLARR_URL}/api/v1/system/status", headers=headers, timeout=2)
        if isinstance(res, dict) and "version" in res:
            print(f"[Prowlarr Setup] ✓ Prowlarr v{res.get('version')} is online! (attempt {attempt})", flush=True)
            return True
        if attempt == 3 and not is_url_reachable(PROWLARR_URL, timeout=1.0):
            print("[Prowlarr Setup] ℹ️ Prowlarr is not active in current profile. Skipping...", flush=True)
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
                print(f"[Prowlarr Setup] ✓ Prowlarr authentication method updated to 'external': {res.get('authenticationMethod')}", flush=True)
            else:
                print("[Prowlarr Setup] ✓ Prowlarr authentication method is already external.", flush=True)
    except Exception as e:
        print(f"[Prowlarr Setup] Note on auth bypass check: {e}", flush=True)

def setup_prowlarr_flaresolverr():
    headers = {"X-Api-Key": PROWLARR_API_KEY}
    proxies = make_request(f"{PROWLARR_URL}/api/v1/indexerproxy", headers=headers)
    if isinstance(proxies, list):
        for p in proxies:
            if p.get("implementation", "").lower() == "flaresolverr" or "flaresolverr" in p.get("name", "").lower():
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
            {"name": "requestTimeout", "value": 60}
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

    for target in target_list:
        target_lower = target.lower()
        if any(target_lower in d for d in existing_definitions):
            continue

        matched_schema = None
        for schema in schemas:
            s_def = schema.get("definitionName", "").lower()
            s_name = schema.get("name", "").lower()
            if s_def == target_lower or s_name == target_lower:
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
        torznab_schema = next((s for s in schemas if s.get("implementation") == "Torznab"), None)
        if torznab_schema:
            z_payload = dict(torznab_schema)
            z_payload["name"] = "Zilean DMM (Local)"
            z_payload["enable"] = os.environ.get("ENABLE_DMM", os.environ.get("ZILEAN_ENABLE_SCRAPING", "true")).lower() != "false"
            z_payload["priority"] = 1
            z_payload["appProfileId"] = 1
            for f in z_payload.get("fields", []):
                if f.get("name") == "baseUrl":
                    f["value"] = "http://zilean:8181/torznab"
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
    disabled_names = ["limetorrents", "tokyo toshokan", "acg.rip"]
    priority_map = {
        "zilean": 1,
        "animetosho": 5,
        "althub": 5,
        "the pirate bay": 10,
        "nyaa": 10,
        "yts": 10,
        "subsplease": 15,
        "mikan": 15,
        "shana project": 15,
        "nekobt": 20,
        "anibt": 20,
        "dmhy": 20,
        "torrentdownload": 30,
    }
    for idx in active_indexers:
        name_lower = idx.get("name", "").lower()
        updated = False
        if any(d in name_lower for d in disabled_names):
            if idx.get("enable"):
                idx["enable"] = False
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
    base=os.environ.get('NZB_INDEXER_URL','').rstrip('/')
    key=os.environ.get('NZB_INDEXER_API_KEY','')
    active=os.environ.get('USENET_ENABLED','false')=='true'
    if active and (not base or not key):
        return
    headers={'X-Api-Key':PROWLARR_API_KEY}
    existing=make_request(f'{PROWLARR_URL}/api/v1/indexer',headers=headers)
    if not isinstance(existing,list):raise RuntimeError('Prowlarr indexer inventory is unavailable')
    owned=next((item for item in existing if item.get('implementation')=='Newznab' and item.get('name')=='AIO Local Usenet'),None)
    if not active:
        if owned and owned.get('enable'):
            payload=dict(owned,enable=False)
            result=make_request(f"{PROWLARR_URL}/api/v1/indexer/{owned['id']}",method='PUT',headers=headers,data=payload)
            if not isinstance(result,dict) or not result.get('id'):raise RuntimeError('Prowlarr could not disable the managed NZB indexer')
        return
    prior=owned or next((item for item in existing if item.get('implementation')=='Newznab' and any(f.get('name')=='baseUrl' and str(f.get('value','')).rstrip('/')==base for f in item.get('fields',[]))),None)
    schemas=make_request(f'{PROWLARR_URL}/api/v1/indexer/schema',headers=headers)
    schema=next((item for item in schemas if item.get('implementation')=='Newznab'),None) if isinstance(schemas,list) else None
    if not schema:raise RuntimeError('Prowlarr Newznab support is unavailable')
    import copy
    payload=copy.deepcopy(prior or schema)
    payload.update(name=prior.get('name') if prior else 'AIO Local Usenet',enable=True,appProfileId=payload.get('appProfileId') or 1)
    for field in payload.get('fields',[]):
        if field.get('name')=='baseUrl':field['value']=base
        elif field.get('name')=='apiKey':field['value']=key
    if not prior:payload.pop('id',None)
    path=f"{PROWLARR_URL}/api/v1/indexer"+(f"/{prior['id']}" if prior else '')
    result=make_request(path,method='PUT' if prior else 'POST',headers=headers,data=payload,timeout=30)
    if not isinstance(result,dict) or not result.get('id'):raise RuntimeError('Prowlarr could not validate the NZB indexer; check its address and key')
    print('[Usenet Setup] NZB indexer configured in Prowlarr.',flush=True)


# ==============================================================================
# 2. COMET & INFINIDYSK STATUS
# ==============================================================================
def wait_for_comet(max_attempts=15, interval=2):
    print(f"[Comet Setup] Checking Comet status at {COMET_URL}...", flush=True)
    for attempt in range(1, max_attempts + 1):
        res = make_request(f"{COMET_URL}/manifest.json")
        if isinstance(res, dict) and ("id" in res or "name" in res):
            print(f"[Comet Setup] ✓ Comet is online with auto-proxying and Prowlarr/Zilean integrations! (attempt {attempt})", flush=True)
            return True
        time.sleep(interval)
    print("[Comet Setup] Note: Comet is booting up in background.", flush=True)
    return False


def wait_for_postersplus(max_attempts=20, interval=2):
    print(f"[Posters+ Setup] Waiting for Posters+ at {POSTERSPLUS_URL}...", flush=True)
    for attempt in range(1, max_attempts + 1):
        res = make_request(f"{POSTERSPLUS_URL}/?access_key={ADDON_PASSWORD}")
        if not isinstance(res, dict) or res.get("error") != -1 or "detail" in res or "access_key" in str(res):
            print(f"[Posters+ Setup] ✓ Posters+ is online and ready! (attempt {attempt})", flush=True)
            return True
        if attempt == 3 and not is_url_reachable(POSTERSPLUS_URL, timeout=1.0):
            print("[Posters+ Setup] ℹ️ Posters+ is not active in current profile. Skipping...", flush=True)
            return False
        time.sleep(interval)
    print("[Posters+ Setup] Note: Posters+ is still starting up...", flush=True)
    return False

def wait_for_aiometadata(max_attempts=30, interval=2):
    print(f"[AIOMetadata Setup] Waiting for AIOMetadata at {AIOMETADATA_URL}...", flush=True)
    for attempt in range(1, max_attempts + 1):
        # An error dictionary is truthy; liveness also precedes manifest readiness.
        res = make_request(f"{AIOMETADATA_URL}/manifest.json")
        if isinstance(res, dict) and not res.get("error") and res.get("id"):
            print(f"[AIOMetadata Setup] ✓ AIOMetadata is online and ready! (attempt {attempt})", flush=True)
            return True
        if attempt == 3 and not is_url_reachable(AIOMETADATA_URL, timeout=1.0):
            print("[AIOMetadata Setup] ℹ️ AIOMetadata is not active in current profile. Skipping...", flush=True)
            return False
        time.sleep(interval)
    print("[AIOMetadata Setup] Note: AIOMetadata is still starting up...", flush=True)
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
        loaded = make_request(f"{AIOMETADATA_URL}/api/config/load/{existing_profile}", method="POST",
                              data={"password": ADDON_PASSWORD, "addonPassword": ADDON_PASSWORD})
        if not isinstance(loaded, dict) or not loaded.get("success") or not isinstance(loaded.get("config"), dict):
            raise RuntimeError("Existing metadata profile could not be loaded; refusing to overwrite linked accounts.")
        existing_cfg = loaded["config"]
        if "catalogs" in config:
            existing_cfg["catalogs"] = config["catalogs"]
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
    for catalog in config.get("catalogs", []):
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
    poster_key = os.environ.get("POSTERSPLUS_ACCESS_KEY", "")
    poster_url = f"{POSTERSPLUS_URL}/poster?stremio_id={{id}}&type={{type}}&shape={{shape}}"
    if poster_key:
        poster_url += '&access_key=' + urllib.parse.quote(poster_key, safe='')
    config["customPosterUrl"] = poster_url
    config["enableRatingPostersForLibrary"] = True
    config.setdefault("customArt", {})["posterUrl"] = poster_url
    config["customArt"]["proxy"] = True

    # Configure art providers with Fanart.tv ClearLogos & backdrops
    art_providers = config.setdefault("artProviders", {})
    for kind in ("movie", "series", "anime"):
        kind_cfg = art_providers.setdefault(kind, {})
        kind_cfg["logo"] = "fanart"
        kind_cfg["background"] = "fanart"
        kind_cfg["poster"] = "custom"

    config["castCount"] = 15
    config["animeEpisodeDates"] = "earliest"
    config.setdefault("search", {})["ai_enabled"] = True
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
        raise RuntimeError("AIOMetadata rejected its configuration. Check its API keys and addon password.")
    if res.get("userUUID"):
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
    if not wait_for_postersplus():
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
        if isinstance(res, dict) and ("status" in res or "version" in res or res.get("success")):
            print(f"[AIOStreams Setup] ✓ AIOStreams is online and ready! (attempt {attempt})", flush=True)
            return True
        time.sleep(interval)
    print("[AIOStreams Setup] ⚠️ Timed out waiting for AIOStreams status. Trying user endpoint anyway...", flush=True)
    return False

def build_default_config(aiometadata_manifest=None, *, probe_services=True):
    """Builds our comprehensive Tamtaro All-Local Self-Hosted configuration dictionary."""
    reachable = is_url_reachable if probe_services else lambda *args, **kwargs: True
    template_data = {}
    chosen_template_path = TEMPLATE_PATH
    usenet_active = (os.environ.get('USENET_ENABLED', 'true') != 'false' and os.environ.get('USENET_HOST')
                     and (os.environ.get('USENET_USER') or os.environ.get('USENET_USER_B64'))
                     and (os.environ.get('USENET_PASS') or os.environ.get('USENET_PASS_B64')))
    has_debrid = any(k for k in (REALDEBRID_API_KEY, PREMIUMIZE_API_KEY, TORBOX_API_KEY, ALLDEBRID_API_KEY, DEBRIDLINK_API_KEY, EASYDEBRID_API_KEY, OFFCLOUD_API_KEY, SEEDR_API_KEY))
    streaming_mode = os.environ.get("STREAMING_MODE", "").lower()
    if streaming_mode == "usenet" or os.environ.get("AIOMETADATA_TEMPLATE") in ("usenet-only.json", "usenet-only", "tamtaro-usenet-only.json") or (usenet_active and not has_debrid):
        u_cand = resolve_path("templates/builtin/usenet-only.json", "/templates/builtin/usenet-only.json")
        if os.path.exists(u_cand):
            chosen_template_path = u_cand
    if os.path.exists(chosen_template_path):
        try:
            with open(chosen_template_path, "r", encoding="utf-8") as f:
                template_data = json.load(f)
        except Exception as e:
            print(f"[AIOStreams Setup] Note loading template file: {e}", flush=True)

    base_config = template_data.get("config", {})

    # Ensure services are populated with InfiniDysk nzbdav and any provided Debrid keys
    nzbdav_key = SECRET_KEY if SECRET_KEY else "e2c019d4536f9a039b56f8f1dfba8919634e2c8846bb1999252c79213bc01b09"
    services = [
        {
            "id": "nzbdav",
            "enabled": True,
            "credentials": {
                "apiKey": nzbdav_key,
                "url": "http://infinidysk:3000",
                "username": "admin",
                "password": ADDON_PASSWORD
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
            "type": "comet",
            "instanceId": "comet-local",
            "enabled": True,
            "options": {
                "name": "Comet (Local)",
                "url": "http://comet:8000",
                "timeout": 8000,
                "resources": ["stream"],
                "includeP2P": False,
                "removeTrash": True,
                "mediaTypes": []
            }
        },
        {
            "type": "knaben",
            "instanceId": "knaben-scraper",
            "enabled": False,
            "options": {
                "name": "Knaben (Built-in)",
                "timeout": 8000,
                "resources": ["stream"],
                "mediaTypes": [],
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
                "timeout": 8000,
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
                "timeout": 8000,
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
                "timeout": 8000,
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
        }
    ])


    # Ensure knaben is present but disabled by default to prevent slow public tracker debrid cache timeouts
    if not any(p.get("type") == "knaben" for p in presets):
        presets.insert(2, {
            "type": "knaben",
            "instanceId": "knaben-scraper",
            "enabled": False,
            "options": {
                "name": "Knaben (Built-in)",
                "timeout": 7000,
                "resources": ["stream"],
                "mediaTypes": [],
                "useMultipleInstances": False
            }
        })

    # Ensure anime & usenet presets are guaranteed to be present
    anime_and_usenet = [
        {
            "type": "anime-tosho-new",
            "instanceId": "anime-tosho-new",
            "enabled": True,
            "options": {
                "name": "Anime Tosho",
                "timeout": 8000,
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
                "timeout": 8000,
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
                "timeout": 8000,
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
                "timeout": 8000,
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

    if any(s.get('enabled') and s.get('id') not in ('nzbdav', 'easynews') for s in services):
        if not any(p.get("type") == "stremthruStore" for p in presets):
            presets.append({
                "type": "stremthruStore",
                "instanceId": "stremthru-store-local",
                "enabled": True,
                "options": {
                    "name": "StremThru Store (Local)",
                    "url": f"{STREMTHRU_URL}/stremio/store/",
                    "timeout": 8000,
                    "resources": ["catalog", "meta", "stream"],
                    "mediaTypes": [],
                    "hideStreams": False,
                    "webDl": False,
                    "usenet": False
                }
            })

    subtitle_config = {"languages": ["eng"]}
    for env_key, config_key in (("SUBDL_API_KEY", "subdlApiKey"), ("SUBSOURCE_API_KEY", "subsourceApiKey"), ("WYZIE_API_KEY", "wyzieApiKey")):
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
        ptype = p.get("type")
        pid = p.get("instanceId", "")
        opts = p.setdefault("options", {})
        if ptype == "torrentio":
            if not any(s.get('enabled') and s.get('id') not in ('nzbdav','easynews') for s in services):
                continue
            opts["name"] = "Torrentio"
            opts["timeout"] = 8000
            custom_url = os.environ.get("TORRENTIO_URL") or os.environ.get("KNIGHTCRAWLER_URL", "")
            if custom_url:
                opts["url"] = custom_url
                opts["name"] = "Torrentio (custom)"
            enable_t = os.environ.get("ENABLE_TORRENTIO", os.environ.get("ENABLE_KNIGHTCRAWLER", "true")).lower() != "false"
            p["enabled"] = enable_t
            validated_presets.append(p)
        elif ptype == "comet":
            if not any(s.get('enabled') and s.get('id') not in ('nzbdav', 'easynews') for s in services):
                continue
            curr_timeout = int(opts.get("timeout") or 10000)
            if curr_timeout > 8000 or curr_timeout < 5000:
                opts["timeout"] = 8000
            manifest_url = opts.get("manifestUrl", f"{COMET_URL}/manifest.json")
            if reachable(manifest_url, timeout=1.0):
                p["enabled"] = True
                print("[AIOStreams Setup] ✓ Comet (Local) is online and active.", flush=True)
                validated_presets.append(p)
            else:
                print("[AIOStreams Setup] ℹ️ Comet not active in current profile; preset disabled.", flush=True)
        elif ptype == "stremthruStore":
            if not any(s.get('enabled') and s.get('id') not in ('nzbdav', 'easynews') for s in services):
                continue
            curr_timeout = int(opts.get("timeout") or 8000)
            if curr_timeout > 8000 or curr_timeout < 5000:
                opts["timeout"] = 8000
            if reachable(f"{STREMTHRU_URL}/stremio/store/manifest.json", timeout=1.0):
                p["enabled"] = True
                print("[AIOStreams Setup] ✓ StremThru Store (Debrid Cloud Library) is online and active.", flush=True)
                validated_presets.append(p)
            else:
                p["enabled"] = False
                print("[AIOStreams Setup] ℹ️ StremThru Store not active in current profile; preset disabled.", flush=True)
                validated_presets.append(p)
        elif ptype in ("knaben", "stremthruTorz"):
            p["enabled"] = False
            curr_timeout = int(opts.get("timeout") or 7000)
            if curr_timeout < 18000:
                opts["timeout"] = 18000
            validated_presets.append(p)
        elif ptype == "easynews-search":
            p["enabled"] = bool(EASYNEWS_USER and EASYNEWS_PASSWORD)
            # Direct EasyNews delivery owns this account.
            opts['services']=['easynews']
            opts['useMultipleInstances']=False
            opts['paginate']=False
            curr_timeout = int(opts.get("timeout") or 15000)
            opts["timeout"] = 8000
            opts["services"] = ["easynews"]
            if p["enabled"]:
                print("[AIOStreams Setup] ✓ Easynews Search (Built-in) is active.", flush=True)
            else:
                print("[AIOStreams Setup] ℹ️ Easynews credentials not provided; preset disabled.", flush=True)
            validated_presets.append(p)
        elif ptype in ("anime-tosho-new", "tsukihime", "neko-bt"):
            compatible={'alldebrid','debrider','debridlink','easydebrid','offcloud','premiumize','pikpak','realdebrid','torbox','torrin'}
            if ptype=='tsukihime':compatible.add('nzbdav')
            selected=[s['id'] for s in services if s.get('enabled') and s['id'] in compatible]
            p["enabled"] = os.environ.get('ENABLE_ANIME_SOURCES','false')=='true' and bool(selected)
            opts['services']=selected
            opts['mediaTypes']=['anime']
            opts['useMultipleInstances']=False
            curr_timeout = int(opts.get("timeout") or 15000)
            opts["timeout"] = 8000
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
                    print(f"[AIOStreams Setup] ℹ️ SubSense not reachable in current profile; omitting from active presets.", flush=True)
            elif pid == "anime-kitsu-local":
                opts["resources"] = ["catalog", "meta"]
                murl = opts.get("manifestUrl", "http://anime-kitsu:7000/manifest.json")
                if reachable(murl, timeout=1.0):
                    p["enabled"] = True
                    print(f"[AIOStreams Setup] ✓ Anime Kitsu (Local) is online and active.", flush=True)
                    validated_presets.append(p)
                else:
                    print(f"[AIOStreams Setup] ℹ️ Anime Kitsu not reachable; omitting from active presets.", flush=True)
            else:
                murl = opts.get("manifestUrl")
                if murl and reachable(murl, timeout=1.0):
                    print(f"[AIOStreams Setup] ✓ Custom addon '{pid}' ({murl}) is online and active.", flush=True)
                    validated_presets.append(p)
                else:
                    print(f"[AIOStreams Setup] ℹ️ Custom addon '{pid}' ({murl}) is unreachable; omitting from active presets.", flush=True)
        else:
            validated_presets.append(p)

    config = dict(base_config)
    # Configure BuiltinProxy so internal Docker scraper streams (Comet)
    # resolve and stream properly through AIOStreams over the single public port (3001)
    existing_proxy = base_config.get("proxy") if isinstance(base_config.get("proxy"), dict) else {}
    proxy_creds = existing_proxy.get("credentials") or (f"admin:{ADDON_PASSWORD}" if ADDON_PASSWORD else "admin:admin")
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
        "url": existing_proxy.get("url") or BASE_URL or "http://aiostreams:3000",
        "credentials": proxy_creds,
        "proxiedServices": ["realdebrid", "premiumize", "alldebrid", "torbox", "debridlink", "easynews", "nzbdav", "none"]
    }

    config["addonName"] = "AIOStreams (All-Local Self-Hosted - Tamtaro SEL)"
    config["accessKey"] = ADDON_PASSWORD
    config["addonDescription"] = "Unified all-in-one local scraper & debrid super-addon powered by Tamtaro SEL sorting, Vidhin regexes, Seadex, Posters+, and local containers."
    config["services"] = services
    config["presets"] = validated_presets
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
    # Background prefetch adds another episode search; keep it explicitly opt-in.
    config["precacheNextEpisode"] = os.environ.get('AIO_PRECACHE_NEXT_EPISODE','false') == 'true'
    config.pop('precacheSelector',None)
    config.pop('precacheCondition',None)
    config.pop('alwaysPrecache',None)
    has_debrid_active = any(s.get('enabled') and s.get('id') not in ('nzbdav', 'easynews') for s in services)
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

    # Inject metadata API keys into AIOStreams user configuration
    global TMDB_API_KEY, TVDB_API_KEY
    if not (TMDB_API_KEY and TVDB_API_KEY):
        load_env_file()
        TMDB_API_KEY = os.environ.get("TMDB_API_KEY", TMDB_API_KEY)
        TVDB_API_KEY = os.environ.get("TVDB_API_KEY", TVDB_API_KEY)

    if TMDB_API_KEY:
        config["tmdbApiKey"] = TMDB_API_KEY
        for feature in ('titleMatching','yearMatching'):
            config[feature]['enabled']=True
    else:
        for feature in ('titleMatching','yearMatching','digitalReleaseFilter'):
            if isinstance(config.get(feature),dict):
                config[feature]['enabled']=False
        if isinstance(config.get('bitrate'),dict):
            config['bitrate']['useMetadataRuntime']=False
    # Failover remains sequential; prefetch must not create hidden extra calls.
    if isinstance(config.get('failover'),dict):
        config['failover']['parallel']=1
        config['failover']['precacheFailover']=config['precacheNextEpisode']
    # TVDB is consumed by AIOMetadata. Do not make AIOStreams registration
    # depend on an optional TVDB endpoint or key being reachable.

    return config

def get_aiostreams_auth_headers():
    auth_bytes = f"admin:{ADDON_PASSWORD}".encode("utf-8")
    headers = {
        "Authorization": f"Basic {base64.b64encode(auth_bytes).decode('ascii')}",
        "Content-Type": "application/json"
    }
    try:
        login_url = f"{AIOSTREAMS_URL}/api/v1/auth/login"
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

def setup_aiostreams_default_user(aiometadata_manifest=None):
    print("[AIOStreams Setup] Configuring default out-of-the-box configuration with Tamtaro & Debrid...", flush=True)

    auth_headers = get_aiostreams_auth_headers()

    uuid = None
    encrypted_password = None

    # Check candidates for existing install info
    for candidate in [
        os.path.join(DATA_AIOSTREAMS, "aiostreams_install.json"),
        os.path.join(DATA_STREMIO_WEB, "aiostreams_install.json"),
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
            "password": "admin_local_secret"
        }

        res = make_request(f"{AIOSTREAMS_URL}/api/v1/user", method="POST", data=create_payload)
        if isinstance(res, dict) and res.get("success") and "data" in res:
            uuid = res["data"].get("uuid")
            encrypted_password = res["data"].get("encryptedPassword") or res["data"].get("encrypted_password")
            print(f"[AIOStreams Setup] ✓ Default user configuration registered successfully!", flush=True)
            print(f"[AIOStreams Setup]   UUID: {uuid}", flush=True)
        else:
            err = res.get("message", res) if isinstance(res, dict) else res
            print(f"[AIOStreams Setup] Note registering default user: {err}. Attempting fallback registration with standard tamtaro formatter...", flush=True)
            config["formatter"] = {"id": "tamtaro"}
            create_payload["config"] = config
            res2 = make_request(f"{AIOSTREAMS_URL}/api/v1/user", method="POST", data=create_payload)
            if isinstance(res2, dict) and res2.get("success") and "data" in res2:
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
            user_auth = base64.b64encode(f"{uuid}:admin_local_secret".encode()).decode("ascii")
            u_headers = {
                "Authorization": f"Basic {user_auth}",
                "Content-Type": "application/json"
            }
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
                "password": "admin_local_secret",
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
            os.path.join(DATA_STREMIO_WEB, "aiostreams_install.json"),
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
# 5. PRE-SEED STREMIO WEB LOCAL STORAGE (ADDON ALREADY INSTALLED)
# ==============================================================================
def preseed_stremio_web(config_info, aiometadata_manifest=None):
    manifest_urls = config_info.get("manifest_urls", [])
    primary_manifest = manifest_urls[1] if len(manifest_urls) > 1 else (manifest_urls[0] if manifest_urls else f"{BASE_URL}/stremio/u/local/manifest.json")
    local_manifest = f"{AIOSTREAMS_URL}/stremio/u/local/manifest.json"

    print(f"[Stremio Web Pre-Seed] Pre-installing AIOStreams and AIOMetadata into Stremio Web...", flush=True)
    print(f"[Stremio Web Pre-Seed] Target AIOStreams manifest: {primary_manifest}", flush=True)

    # Browser clients cannot resolve Docker service names. Install one real
    # aggregator manifest, which already includes the metadata/catalog addons.
    uuid = config_info.get("uuid")
    encrypted = config_info.get("encrypted_password")
    actual_manifest = make_request(f"{AIOSTREAMS_URL}/stremio/{uuid}/{encrypted}/manifest.json")
    if not isinstance(actual_manifest, dict) or not actual_manifest.get("id"):
        raise RuntimeError("Cannot seed Stremio Web without a valid aggregator manifest")
    addons_list = [{"manifest": actual_manifest, "transportUrl": primary_manifest,
                    "flags": {"official": False, "protected": False}}]

    local_storage_payload = {
        "profile": {
            "auth": None,
            "addons": addons_list,
            "addonsLocked": False,
            "settings": {
                "interfaceLanguage": "eng",
                "streamingServerUrl": "http://127.0.0.1:11470/",
                "playerType": None,
                "bingeWatching": True,
                "playInBackground": True,
                "hardwareDecoding": True,
                "frameRateMatchingStrategy": "FrameRateOnly",
                "nextVideoNotificationDuration": 35000,
                "audioPassthrough": False,
                "audioLanguage": "eng",
                "subtitlesLanguage": "eng",
                "subtitlesSize": 100,
                "subtitlesFont": "Roboto",
                "subtitlesTextColor": "#FFFFFFFF",
                "streamingServerWarningDismissed": "2075-02-13T17:43:53.678Z"
            }
        },
        "streaming_server_urls": {
            "items": {
                "http://127.0.0.1:11470/": "2026-10-15T22:00:00.000Z"
            }
        }
    }

    try:
        os.makedirs(DATA_STREMIO_WEB, exist_ok=True)
        target_path = os.path.join(DATA_STREMIO_WEB, "localStorage.json")
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(local_storage_payload, f, indent=2)
        print(f"[Stremio Web Pre-Seed] ✓ Successfully saved pre-seeded library to {target_path}", flush=True)

        uuid = config_info.get("uuid")
        enc = config_info.get("encrypted_password")
        if uuid and enc and str(uuid).strip() not in ("null", "None", "") and str(enc).strip() not in ("null", "None", ""):
            install_info = dict(config_info)
            if aiometadata_manifest:
                install_info["aiometadata_manifest"] = aiometadata_manifest
            install_info["saved_at"] = time.time()
            install_info["base_url"] = BASE_URL

            # Save to stremio-web directory
            info_path = os.path.join(DATA_STREMIO_WEB, "aiostreams_install.json")
            with open(info_path, "w", encoding="utf-8") as f:
                json.dump(install_info, f, indent=2)
            print(f"[Stremio Web Pre-Seed] ✓ Saved installation metadata to {info_path}", flush=True)

            # Save to aiostreams data volume directory for entrypoint auto-hydration
            for candidate_dir in [
                DATA_AIOSTREAMS,
                "/data/aiostreams",
                "/data",
                "/app/data/aiostreams",
                "/app/data",
                DATA_ROOT
            ]:
                try:
                    if os.path.isdir(candidate_dir):
                        dest = os.path.join(candidate_dir, "aiostreams_install.json")
                        with open(dest, "w", encoding="utf-8") as f:
                            json.dump(install_info, f, indent=2)
                        print(f"[Setup] ✓ Synced install metadata to {dest}", flush=True)
                except Exception:
                    pass
        else:
            print(f"[Setup] ℹ️ AIOStreams user profile not yet registered (uuid={uuid}). Purging any invalid metadata.", flush=True)
            for candidate_dir in [DATA_STREMIO_WEB, DATA_AIOSTREAMS, "/data/aiostreams", "/data", "/app/data/aiostreams", "/app/data", DATA_ROOT]:
                try:
                    target_file = os.path.join(candidate_dir, "aiostreams_install.json")
                    if os.path.isfile(target_file):
                        with open(target_file, "r", encoding="utf-8") as f:
                            c_data = json.load(f)
                        if not c_data.get("uuid") or c_data.get("uuid") in ("null", "None"):
                            os.remove(target_file)
                            print(f"[Setup] 🧹 Purged invalid metadata file: {target_file}", flush=True)
                except Exception:
                    pass
    except Exception as e:
        print(f"[Stremio Web Pre-Seed] Notice writing local storage: {e}", flush=True)

# ==============================================================================
# 6. DIAGNOSTIC STREAM VERIFICATION TEST
# ==============================================================================
def run_stream_diagnostics(config_info, aiometadata_manifest=None):
    print("==================================================", flush=True)
    print("   Running Verification Test On Internal Server   ", flush=True)
    print("==================================================", flush=True)

    # 1. Test Stremio Web UI / Streaming Server
    print(f"[Test 1/5] Testing internal Stremio server ({STREMIO_WEB_URL})...", flush=True)
    s_res = make_request(f"{STREMIO_WEB_URL}/")
    if not isinstance(s_res, dict) or s_res.get("error") not in [-1]:
        print(f"[Test 1/5] ✓ Internal Stremio Web server is reachable and active!", flush=True)
    else:
        print(f"[Test 1/5] ℹ️ Stremio Web server status: {s_res}", flush=True)

    # 2. Test Posters+ Server
    print(f"[Test 2/5] Testing Posters+ server ({POSTERSPLUS_URL})...", flush=True)
    p_res = make_request(f"{POSTERSPLUS_URL}/?access_key={ADDON_PASSWORD}")
    if not isinstance(p_res, dict) or p_res.get("error") not in [-1] or "access_key" in str(p_res):
        print(f"[Test 2/5] ✓ Posters+ server is reachable and active!", flush=True)
    else:
        print(f"[Test 2/5] ℹ️ Posters+ server status: {p_res}", flush=True)

    # 3. Test AIOMetadata Manifest
    aiom_target = aiometadata_manifest or f"{AIOMETADATA_URL}/manifest.json"
    print(f"[Test 3/5] Testing AIOMetadata manifest ({aiom_target})...", flush=True)
    aiom_res = make_request(aiom_target)
    if isinstance(aiom_res, dict) and "name" in aiom_res:
        print(f"[Test 3/5] ✓ AIOMetadata manifest verified: '{aiom_res.get('name')}' (v{aiom_res.get('version')})", flush=True)
    else:
        print(f"[Test 3/5] ℹ️ AIOMetadata manifest response: {aiom_res}", flush=True)

    # 4. Test AIOStreams Manifest Availability (Both Direct & Alias)
    uuid = config_info.get("uuid")
    enc = config_info.get("encrypted_password")

    if uuid and enc:
        print(f"[Test 4/5] Testing Direct Canonical Manifest (/stremio/{uuid}/{enc[:8]}.../manifest.json)...", flush=True)
        direct_manifest = make_request(f"{AIOSTREAMS_URL}/stremio/{uuid}/{enc}/manifest.json")
        if isinstance(direct_manifest, dict) and "name" in direct_manifest:
            print(f"[Test 4/5] ✓ Direct UUID Manifest verified: '{direct_manifest.get('name')}' (v{direct_manifest.get('version')})", flush=True)
        else:
            print(f"[Test 4/5] Note retrieving direct manifest: {direct_manifest}", flush=True)

    print(f"[Test 4/5] Testing Vanity Alias Manifest (/stremio/u/local/manifest.json)...", flush=True)
    manifest = make_request(f"{AIOSTREAMS_URL}/stremio/u/local/manifest.json")
    if isinstance(manifest, dict) and "name" in manifest:
        print(f"[Test 4/5] ✓ Alias manifest successfully retrieved: '{manifest.get('name')}' (v{manifest.get('version')})", flush=True)
        print(f"[Test 4/5]   Supported resources: {manifest.get('resources')}", flush=True)
        print(f"[Test 4/5]   Supported types: {manifest.get('types')}", flush=True)
    else:
        print(f"[Test 4/5] Note on alias manifest (active after AIOStreams reload): {manifest}", flush=True)

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

    # 2. Comet & InfiniDysk
    try:
        wait_for_comet()
    except Exception as e:
        print(f"[Scraper Checks] Note: {e}", flush=True)

    # 4. Posters+ & AIOMetadata (Tamtaro + Posters+)
    aiometadata_manifest = None
    try:
        aiometadata_manifest = setup_optional_metadata()
    except Exception as e:
        print(f"[AIOMetadata/Posters+ Setup] Error: {e}", flush=True)
        print("[AIOMetadata/Posters+ Setup] ℹ️ Continuing with AIOStreams providers only.", flush=True)

    # 5. AIOStreams Default User & Addon Configuration (Tamtaro All-Local)
    config_info = {}
    try:
        wait_for_aiostreams()
        config_info = setup_aiostreams_default_user(aiometadata_manifest=aiometadata_manifest)
    except Exception as e:
        print(f"[AIOStreams Setup] Error: {e}", flush=True)

    if not config_info or not config_info.get("uuid") or not config_info.get("encrypted_password"):
        print("[Setup] ERROR: AIOStreams profile was not provisioned. Fix the error and rerun stack-bootstrap.", flush=True)
        return 1

    # 6. Pre-seed Stremio Web
    try:
        preseed_stremio_web(config_info, aiometadata_manifest=aiometadata_manifest)
    except Exception as e:
        print(f"[Stremio Web Pre-Seed] Error: {e}", flush=True)

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
