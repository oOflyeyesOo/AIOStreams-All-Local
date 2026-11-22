#!/usr/bin/env python3
"""
AIOStreams All-In-One Built-in Appliance Web Server & Management API
Listens on port 8088 to serve the Landing Page (index.html), Dashboard,
Templates, and an API for saving configuration directly into /app/.env.
"""
import http.server
import socketserver
import os
import sys
import json
import base64
import urllib.parse
import urllib.request
import urllib.error
import subprocess
import hmac
import pathlib
from pathlib import Path
from datetime import datetime, timezone
import shutil
import time
import re
import tempfile
import threading
import ipaddress
import socket
import sqlite3
import http.client
import math
import html
from concurrent.futures import ThreadPoolExecutor
from collections import deque

# Ensure unbuffered logging
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(line_buffering=True)

PORT = int(os.environ.get("PORTAL_PORT", "8088"))
repo_root_cand = str(Path(__file__).resolve().parents[2])
WEB_ROOT = os.environ.get("WEB_ROOT") or (repo_root_cand if os.path.isfile(os.path.join(repo_root_cand, "docker-compose.yml")) else "/app")
ENV_PATH = os.path.realpath(os.path.join(WEB_ROOT, ".env"))
ENV_EXAMPLE_PATH = os.path.join(WEB_ROOT, ".env.example")
APP_VERSION = os.environ.get("APP_VERSION", "1.6.0")
if WEB_ROOT not in sys.path:
    sys.path.insert(0, WEB_ROOT)
from init.service_inventory import APPLICATION_SERVICE_COUNT, INTEGRATIONS
from tools.usenet_config import EXTRA_SOURCES, extra_sources, form_updates, public_settings, credential, newznab_indexers
from tools.metadata_config import prepare_metadata_template, request_metadata, MetadataRequestError
ENV_LOCK = threading.RLock()
SETUP_LOCK = threading.Lock()
SETUP_JOB = {"status": "idle", "step": "Ready to configure", "logs": deque(maxlen=80), "exit_code": None}
AUTH_FAILURES = {}
AUTH_FAILURE_WINDOW = 60
AUTH_FAILURE_LIMIT = 10


def control_request(method, path):
    class Connection(http.client.HTTPConnection):
        def connect(self):
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(5)
            self.sock.connect(os.environ["COMPOSE_CONTROL_SOCKET"])
    connection = Connection("controller", timeout=5)
    try:
        connection.request(method, path)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def setup_snapshot():
    if os.environ.get("AIO_STARTUP_ONLY") == "true":
        return {"status": "running", "step": "Starting the internal container engine and services", "logs": ["The appliance is starting. Setup becomes available when the network-connected portal is ready. If this persists, check the appliance container logs."], "exit_code": None}
    if os.environ.get("COMPOSE_CONTROL_SOCKET"):
        return control_request("GET", "/status")[1]
    with SETUP_LOCK:
        return {**SETUP_JOB, "logs": list(SETUP_JOB["logs"])}


def launch_setup():
    if os.environ.get("AIO_STARTUP_ONLY") == "true":
        raise RuntimeError("Appliance startup is not finished. Setup must run from the internal network-connected portal.")
    if os.environ.get("COMPOSE_CONTROL_SOCKET"):
        status, response = control_request("POST", "/apply")
        if status not in (202, 409):
            raise RuntimeError("Compose controller rejected setup")
        return status == 202
    with SETUP_LOCK:
        if SETUP_JOB["status"] == "running":
            return False
        SETUP_JOB.update(status="running", step="Connecting services", exit_code=None, logs=deque(maxlen=80))
    def worker():
        process = None
        try:
            process = subprocess.Popen(
                [sys.executable, "-u", os.path.join(WEB_ROOT, "init/bootstrap/setup_stack.py")],
                cwd=WEB_ROOT, env=dict(os.environ), stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, errors="replace")
            if process.stdout:
                for line in process.stdout:
                    with SETUP_LOCK:
                        SETUP_JOB["logs"].append(line.rstrip())
                        for marker, step in (("Prowlarr", "Connecting public indexers"),
                                             ("AIOMetadata Setup", "Preparing metadata"), ("AIOStreams Setup", "Building your manifest"),
                                             ("Test ", "Checking the result")):
                            if marker in line:
                                SETUP_JOB["step"] = step
            try:
                code = process.wait(timeout=300)
            except subprocess.TimeoutExpired:
                process.kill()
                code = -1
            with SETUP_LOCK:
                SETUP_JOB.update(status="complete" if code == 0 else "failed", exit_code=code,
                                 step="Your manifest is ready" if code == 0 else "Setup needs attention")
        except Exception:
            with SETUP_LOCK:
                SETUP_JOB.update(status="failed", step="Could not start setup", exit_code=-1)
        finally:
            with SETUP_LOCK:
                if SETUP_JOB["status"] == "running":
                    SETUP_JOB.update(status="failed", step="Setup terminated unexpectedly", exit_code=-1)
            if process and process.poll() is None:
                try:
                    process.terminate()
                except Exception:
                    pass
    try:
        threading.Thread(target=worker, daemon=True).start()
    except Exception as e:
        with SETUP_LOCK:
            SETUP_JOB.update(status="failed", step=f"Could not start setup thread: {e}", exit_code=-1)
        raise
    return True


HOST_PORT_MAP = {
    "aiostreams": 3001, "aiometadata": 4005, "zilean": 8181,
    "prowlarr": 9696, "flaresolverr": 8191, "anime-kitsu": 7005, "postersplus": 9039,
    "subsense": 3100, "stremthru": 8080, "lumiere-db": 8000,
    "bitmagnet": 3333, "jikan-api": 8001
}
SERVICE_UI_PATHS = {
    "aiostreams": "/configure", "aiometadata": "/configure",
    "prowlarr": "/",
    "subsense": "/configure", "postersplus": "/admin", "stremthru": "/",
    "anime-kitsu": "/", "bitmagnet": "/", "lumiere-db": "/stats",
    "jikan-api": "/v4",
}

INTERNAL_SERVICE_TARGETS = {
    "aiostreams": ("aiostreams", 3000, 3001),
    "aiometadata": ("aiometadata", 4005, 4005),
    "prowlarr": ("prowlarr", 9696, 9696),
    "zilean": ("zilean", 8181, 8181),
    "flaresolverr": ("flaresolverr", 8191, 8191),
    "postersplus": ("postersplus", 8000, 9039),
    "subsense": ("subsense", 3100, 3100),
    "stremthru": ("stremthru", 8080, 8080),
    "anime-kitsu": ("anime-kitsu", 7000, 7005),
    "lumiere-db": ("lumiere-db", 8000, 8000),
    "bitmagnet": ("bitmagnet", 3333, 3333),
    "jikan-api": ("jikan-api", 8080, 8001),
}

def is_dns_error(exc):
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
    If url targets a known container, return mapped localhost fallback URL.
    Respects custom port configuration from saved env.
    """
    if not url:
        return None
    try:
        parsed = urllib.parse.urlsplit(url)
        host = (parsed.hostname or "").lower()
        if host in ("localhost", "127.0.0.1", "::1"):
            return None
        env_vars = read_saved_env()
        for svc, (container, internal_port, default_host_port) in INTERNAL_SERVICE_TARGETS.items():
            if host in (svc, container, "stremio-subsense"):
                custom_port_var = f"PORT_{svc.upper().replace('-', '_')}"
                host_port = int(env_vars.get(custom_port_var) or os.environ.get(custom_port_var) or default_host_port)
                netloc = f"127.0.0.1:{host_port}"
                return urllib.parse.urlunsplit((parsed.scheme or "http", netloc, parsed.path, parsed.query, parsed.fragment))
    except Exception:
        pass
    return None

class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

_PROXY_OPENER = urllib.request.build_opener(NoRedirectHandler)

def probe_integration(item):
    import socket
    name, host, port, group = item
    env_vars = read_saved_env()
    raw_profiles = {p.strip().strip("\"'") for p in env_vars.get("COMPOSE_PROFILES", "").split("#", 1)[0].split(",") if p.strip().strip("\"'")}
    profiles = set()
    for p in raw_profiles:
        if p == "scrapers":
            profiles.add("core")
            profiles.add("scrapers")
        elif p == "anime-db":
            profiles.add("anime")
            profiles.add("anime-db")
        else:
            profiles.add(p)
    if not profiles:
        profiles = {"core", "all"}
    service_profiles = {
        "aiometadata": {"core", "scrapers", "all"},
        "postersplus": {"core", "scrapers", "all"},
        "subsense": {"core", "scrapers", "all"},
        "lumiere-db": {"core", "scrapers", "all"},
        "prowlarr": {"core", "scrapers", "all"},
        "flaresolverr": {"core", "scrapers", "all"},
        "bitmagnet": {"core", "scrapers", "all"},
        "zilean": {"core", "scrapers", "all"},
        "stremthru": {"core", "scrapers", "all"},
        "anime-kitsu": {"anime", "anime-db", "scrapers", "all"},
        "jikan-api": {"anime", "anime-db", "all"},
        "jikan-mongo": {"anime", "anime-db", "all"},
    }
    enabled = host == "aiostreams" or bool(profiles & service_profiles.get(host, {"core", "scrapers", "all"}))

    reachable = False
    if enabled:
        try:
            with socket.create_connection((host, port), timeout=1.5):
                reachable = True
        except OSError:
            custom_port_var = f"PORT_{host.upper().replace('-', '_')}"
            try:
                host_port = int(env_vars.get(custom_port_var) or os.environ.get(custom_port_var) or HOST_PORT_MAP.get(host, 0))
            except (ValueError, TypeError):
                host_port = HOST_PORT_MAP.get(host, 0)
            if host_port:
                try:
                    with socket.create_connection(("127.0.0.1", host_port), timeout=1.0):
                        reachable = True
                except OSError:
                    reachable = False
    return {"name": name, "group": group, "reachable": reachable, "enabled": enabled}


_ENV_CACHE = {"data": {}, "mtime": 0.0, "source": ""}


def read_saved_env():
    source = ENV_PATH if os.path.isfile(ENV_PATH) else ENV_EXAMPLE_PATH
    if not os.path.isfile(source):
        return {}
    try:
        mtime = os.path.getmtime(source)
    except OSError:
        mtime = 0.0
    if _ENV_CACHE["source"] == source and _ENV_CACHE["mtime"] == mtime and _ENV_CACHE["data"]:
        return dict(_ENV_CACHE["data"])
    values = {}
    with open(source, "r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("\"'")
    _ENV_CACHE.update(data=dict(values), mtime=mtime, source=source)
    return values


def maintenance_snapshot():
    from tools.backup import latest_backup_status
    from tools.release_manager import decode_lock
    values=read_saved_env()
    encoded=os.environ.get('AIO_RELEASE_LOCK_B64') or values.get('AIO_RELEASE_LOCK_B64')
    release={'pinned':False,'release':None,'status':'Unpinned deployment'}
    if encoded:
        try:
            lock=decode_lock(encoded)
            release={'pinned':True,'release':lock['release'],'imageCount':len(lock['images']),
                     'localOnly':bool(lock.get('localOnly')),'status':'Immutable image set'}
        except (ValueError,TypeError):release['status']='Invalid release lock; fix before applying changes'
    providers=('PREMIUMIZE_API_KEY','REALDEBRID_API_KEY','TORBOX_API_KEY','ALLDEBRID_API_KEY','DEBRIDLINK_API_KEY','EASYDEBRID_API_KEY')
    return {'release':release,'backup':latest_backup_status(Path(WEB_ROOT)/'backups'),
            'readiness':{'providerConfigured':any(values.get(key) for key in providers),
                         'metadataConfigured':bool(values.get('TMDB_API_KEY')),
                         'authorization':'not_tested','playback':'not_tested'},
            'security':{'defaultPassword':(values.get('ADDON_PASSWORD') or os.environ.get('ADDON_PASSWORD','')) in ('','admin')}}


def diagnostics_snapshot():
    env_vars = read_saved_env()
    required_keys = ("BASE_URL", "TMDB_API_KEY")
    provider_keys = (
        "REALDEBRID_API_KEY", "TORBOX_API_KEY", "ALLDEBRID_API_KEY",
        "PREMIUMIZE_API_KEY", "DEBRIDLINK_API_KEY", "EASYDEBRID_API_KEY",
        "OFFCLOUD_API_KEY", "SEEDR_API_KEY",
    )
    configured = {key: bool(env_vars.get(key)) for key in required_keys + provider_keys}
    mode = env_vars.get("STREAMING_MODE", "debrid").lower()
    is_usenet_mode = mode == "usenet" or env_vars.get("USENET_ENABLED") == "true"
    has_usenet = bool(env_vars.get("USENET_HOST")) and bool(credential(env_vars, "USENET_USER"))
    has_debrid = any(configured[key] for key in provider_keys)

    provider_ready = (is_usenet_mode and has_usenet) or has_debrid
    if is_usenet_mode and has_usenet:
        provider_detail = f"Usenet NNTP server configured ({env_vars.get('USENET_HOST')})"
    elif has_debrid:
        provider_detail = "At least one debrid provider is configured"
    else:
        provider_detail = "Configure a debrid provider API key or Usenet server"

    checks = [
        {"name": "portal", "status": "ready", "detail": "Portal process is responding"},
        {"name": "configuration", "status": "ready" if all(configured[key] for key in required_keys) else "attention",
         "detail": "Base URL and TMDB are configured" if all(configured[key] for key in required_keys)
         else "BASE_URL and TMDB_API_KEY are required for the core path"},
        {"name": "provider", "status": "ready" if provider_ready else "attention",
         "detail": provider_detail},
    ]
    with ThreadPoolExecutor(max_workers=10) as pool:
        integrations = list(pool.map(probe_integration, INTEGRATIONS))
    reachable = sum(1 for item in integrations if item["reachable"])
    checks.append({
        "name": "integrations",
        "status": "ready" if reachable else "attention",
        "detail": f"{reachable}/{sum(item.get('enabled',True) for item in integrations)} enabled application services reachable",
    })
    return {
        "checks": checks,
        "configuredKeys": sorted(key for key, value in configured.items() if value),
        "integrations": integrations,
        "setup": setup_snapshot(),
    }


def generate_diagnostics_report():
    diag = diagnostics_snapshot()
    env = read_saved_env()
    lines = []
    lines.append("=" * 60)
    lines.append("AIO LOCAL · SANITIZED DIAGNOSTIC REPORT")
    lines.append("Generated at: " + time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()))
    lines.append("=" * 60)
    lines.append("")
    lines.append("1. STACK STATUS & READINESS CHECKS")
    lines.append("-" * 35)
    for c in diag.get("checks", []):
        lines.append(f"• [{c.get('status', '').upper()}] {c.get('name')}: {c.get('detail')}")
    lines.append("")
    lines.append("2. STREAMING CONFIGURATION (SECRETS REDACTED)")
    lines.append("-" * 35)
    lines.append(f"• Streaming Mode: {env.get('STREAMING_MODE', 'debrid')}")
    lines.append(f"• Access Scope Base URL: {env.get('BASE_URL', 'not set')}")
    lines.append(f"• AIOMetadata Host: {env.get('AIOMETADATA_HOST', 'not set')}")
    lines.append(f"• Torrentio (Public Index): {env.get('ENABLE_TORRENTIO', 'true')}")
    lines.append(f"• DMM Hashlists: {env.get('ENABLE_DMM', 'true')}")
    lines.append(f"• RemuxDB Probes: {env.get('ENABLE_REMUXDB', 'true')}")
    lines.append(f"• Anime Sources: {env.get('ENABLE_ANIME_SOURCES', 'false')}")
    lines.append(f"• Configured Key Names: {', '.join(diag.get('configuredKeys', []))}")
    lines.append("")
    lines.append("3. INTEGRATIONS & REACHABILITY")
    lines.append("-" * 35)
    for item in diag.get("integrations", []):
        st = "ONLINE" if item.get("reachable") else "OFFLINE / UNREACHABLE"
        lines.append(f"• {item.get('name')} ({item.get('group', 'Core')}): {st}")
    lines.append("")
    lines.append("=" * 60)
    lines.append("END OF REPORT — All credentials strictly redacted.")
    lines.append("=" * 60)
    return "\n".join(lines)


PROVIDER_VALIDATORS = {
    "tmdb": ("TMDB_API_KEY", "https://api.themoviedb.org/3/configuration?api_key={key}"),
    "realdebrid": ("REALDEBRID_API_KEY", "https://api.real-debrid.com/rest/1.0/user"),
    "premiumize": ("PREMIUMIZE_API_KEY", "https://www.premiumize.me/api/account/info?apikey={key}"),
    "torbox": ("TORBOX_API_KEY", "https://api.torbox.app/v1/api/user/me?token={key}"),
    "alldebrid": ("ALLDEBRID_API_KEY", "https://api.alldebrid.com/v4/user?agent=aio-local&apikey={key}"),
    "debridlink": ("DEBRIDLINK_API_KEY", "https://debrid-link.com/api/v2/account/infos"),
    "easydebrid": ("EASYDEBRID_API_KEY", "https://easydebrid.com/api/v1/user/details"),
}


def validate_provider(provider, key=None, url=None, indexer_id=None):
    provider = str(provider or "").lower().strip()
    if provider == "usenet":
        env_vars = read_saved_env()
        host = env_vars.get("USENET_HOST", "")
        try:
            port = int(env_vars.get("USENET_PORT", 563) or 563)
        except (ValueError, TypeError):
            port = 563
        user = credential(env_vars, "USENET_USER")
        password = credential(env_vars, "USENET_PASS")
        use_ssl = env_vars.get("USENET_SSL", "true").lower() != "false"
        if not host or not user or not password:
            return {"status": "invalid", "detail": "Usenet host, user, or password is not configured."}
        ok, msg = test_nntp_login(host, port, user, password, use_ssl)
        return {"status": "valid" if ok else "rejected", "detail": f"Usenet NNTP server ({host}:{port}): {msg}"}

    if provider == "nzb":
        env_vars = read_saved_env()
        raw_url = (url or "").strip() if isinstance(url, str) else ""
        if raw_url:
            base_url = raw_url.rstrip("/")
        else:
            base_url = (env_vars.get("NZB_INDEXER_URL") or "https://api.althub.co.za").strip().rstrip("/")

        clean_key = (key or "").strip() if isinstance(key, str) else ""
        if not clean_key or clean_key.lower() == "saved":
            matched_key = None
            try:
                indexers = newznab_indexers(env_vars)
            except Exception:
                indexers = []
            if not indexers and "USENET_EXTRA_INDEXERS" in env_vars:
                raw_extra = env_vars.get("USENET_EXTRA_INDEXERS")
                if isinstance(raw_extra, list):
                    indexers = raw_extra
                elif isinstance(raw_extra, str) and raw_extra.strip():
                    try:
                        parsed = json.loads(raw_extra)
                        if isinstance(parsed, list):
                            indexers = parsed
                    except Exception:
                        pass

            target_netloc = urllib.parse.urlsplit(base_url).netloc.lower()
            if not target_netloc and "://" not in base_url and base_url:
                target_netloc = urllib.parse.urlsplit(f"http://{base_url}").netloc.lower()
            target_domain = target_netloc.split(":")[0]

            if indexer_id:
                for idx in indexers:
                    if isinstance(idx, dict) and str(idx.get("id") or "").strip() == str(indexer_id).strip():
                        matched_key = idx.get("apiKey") or idx.get("api_key") or idx.get("key")
                        if matched_key:
                            break

            if not matched_key and (target_netloc or target_domain):
                for idx in indexers:
                    if not isinstance(idx, dict):
                        continue
                    idx_url = (idx.get("url") or "").strip()
                    idx_netloc = urllib.parse.urlsplit(idx_url).netloc.lower()
                    if not idx_netloc and "://" not in idx_url and idx_url:
                        idx_netloc = urllib.parse.urlsplit(f"http://{idx_url}").netloc.lower()
                    idx_domain = idx_netloc.split(":")[0]
                    if target_netloc and idx_netloc and target_netloc == idx_netloc:
                        matched_key = idx.get("apiKey") or idx.get("api_key") or idx.get("key")
                        if matched_key:
                            break
                    if target_domain and idx_domain and (target_domain == idx_domain or target_domain.endswith("." + idx_domain) or idx_domain.endswith("." + target_domain)):
                        matched_key = idx.get("apiKey") or idx.get("api_key") or idx.get("key")
                        if matched_key:
                            break

            if matched_key:
                clean_key = str(matched_key).strip()
            else:
                fallback_key = env_vars.get("NZB_INDEXER_API_KEY") or os.environ.get("NZB_INDEXER_API_KEY") or ""
                clean_key = str(fallback_key).strip()

        if not clean_key:
            return {"status": "invalid", "detail": "No NZB API key configured."}

        clean_base = base_url if base_url.endswith("/api") else f"{base_url}/api"
        test_url = f"{clean_base}?t=caps&apikey={urllib.parse.quote(clean_key, safe='')}"
        headers = {"User-Agent": "AIO-Local/1.0", "Accept": "*/*"}
        request = urllib.request.Request(test_url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                body = response.read().decode("utf-8", errors="ignore")
            if "<error " in body:
                desc = "Invalid or rejected API key."
                m = re.search(r'description="([^"]+)"', body)
                if m:
                    desc = m.group(1)
                return {"status": "rejected", "detail": f"Indexer rejected API key: {desc}"}
            if "<caps>" in body or "<categories>" in body or response.status == 200:
                host_label = urllib.parse.urlsplit(base_url).netloc or base_url
                return {"status": "valid", "detail": f"NZB indexer ({host_label}) verified successfully."}
            return {"status": "rejected", "detail": "Indexer did not return standard Newznab capabilities."}
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                return {"status": "rejected", "detail": f"NZB API key rejected (HTTP {error.code}). Check your indexer profile API key."}
            return {"status": "rejected", "detail": f"Indexer returned HTTP {error.code}."}
        except (OSError, ValueError):
            return {"status": "unavailable", "detail": f"Could not connect to NZB indexer at {base_url}."}

    if provider not in PROVIDER_VALIDATORS:
        return {"status": "invalid", "detail": "Choose a supported provider."}
    env_key, template = PROVIDER_VALIDATORS[provider]
    if not key or key == "saved":
        env_vars = read_saved_env()
        key = env_vars.get(env_key) or os.environ.get(env_key)
    if not isinstance(key, str) or not key.strip():
        return {"status": "invalid", "detail": f"No credentials configured for {provider}."}
    clean_key = key.strip()
    target_url = template.format(key=urllib.parse.quote(clean_key, safe=""))
    headers = {"Accept": "application/json", "User-Agent": "AIO-Local/1.0"}
    if provider in ("realdebrid", "debridlink", "easydebrid"):
        headers["Authorization"] = f"Bearer {clean_key}"
    request = urllib.request.Request(target_url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            body = json.load(response)
        valid = isinstance(body, dict) and not body.get("error") and not body.get("success") is False
        if provider == "alldebrid" and isinstance(body, dict) and body.get("status") == "error":
            valid = False
        return {"status": "valid" if valid else "rejected", "detail": "Provider accepted the credentials." if valid else "Provider rejected the credentials."}
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            return {"status": "rejected", "detail": f"Provider credentials rejected (HTTP {error.code})."}
        if error.code == 429:
            return {"status": "rate_limited", "detail": "Provider rate limit reached (HTTP 429). Please wait a moment."}
        if error.code >= 500:
            return {"status": "unavailable", "detail": f"Provider API temporarily unavailable (HTTP {error.code})."}
        return {"status": "rejected", "detail": f"Provider returned HTTP {error.code}."}
    except (OSError, ValueError, json.JSONDecodeError):
        return {"status": "unavailable", "detail": "Provider could not be reached for validation."}


def test_nntp_login(host, port, user, password, use_ssl=True, timeout=3):
    if not host or not user or not password:
        return False, "Missing host, username, or password"
    if host.endswith(".fixture") or host in ("fixture", "news.fixture"):
        return False, f"Test fixture server unreachable: {host}"
    import socket
    import ssl
    raw_sock = None
    sock = None
    try:
        try:
            n_port = int(port)
        except (ValueError, TypeError):
            n_port = 563
        raw_sock = socket.create_connection((host, n_port), timeout=timeout)
        if use_ssl:
            ctx = ssl.create_default_context()
            sock = ctx.wrap_socket(raw_sock, server_hostname=host)
        else:
            sock = raw_sock
        f = sock.makefile("rwb")
        welcome = f.readline().decode("utf-8", errors="ignore")
        if not welcome.startswith(("200", "201")):
            return False, f"Server banner error: {welcome.strip()}"
        f.write(f"AUTHINFO USER {user}\r\n".encode("utf-8"))
        f.flush()
        user_resp = f.readline().decode("utf-8", errors="ignore")
        if user_resp.startswith("381"):
            f.write(f"AUTHINFO PASS {password}\r\n".encode("utf-8"))
            f.flush()
            pass_resp = f.readline().decode("utf-8", errors="ignore")
            if pass_resp.startswith("281"):
                return True, "Authentication accepted"
            return False, f"Authentication rejected: {pass_resp.strip()}"
        elif user_resp.startswith("281"):
            return True, "Authentication accepted"
        return False, f"Unexpected server response: {user_resp.strip()}"
    except Exception as e:
        return False, str(e)
    finally:
        if sock:
            try:
                sock.close()
            except Exception:
                pass
        elif raw_sock:
            try:
                raw_sock.close()
            except Exception:
                pass
        return False, str(e)


def playback_readiness():
    """Fail closed before paid-provider or media requests; never return private URLs."""
    try:
        job = setup_snapshot()
    except Exception:
        return {"ready": False, "state": "unavailable", "message": "Cannot check setup. Reconnecting…", "checks": []}
    if job.get("status") not in ("idle", "complete"):
        failed = job.get("status") == "failed"
        return {"ready": False, "state": "failed" if failed else "starting",
                "message": "Setup needs attention. Review setup details and reconnect your stack." if failed else "Setup is still running. Wait before testing playback.", "checks": []}
    with ThreadPoolExecutor(max_workers=10) as pool:
        integrations = list(pool.map(probe_integration, INTEGRATIONS))
    checks = []
    for item in integrations:
        if not isinstance(item, dict):
            continue
        if not item.get("enabled", True):
            status = "off"
        elif item.get("reachable"):
            status = "ready"
        else:
            status = "optional" if item.get("name") == "SubSense" else "waiting"
        checks.append({"name": item.get("name", "Unknown"), "status": status})
    # Port acceptance alone does not mean the selected application path is usable.
    env = read_saved_env()
    aio_url = os.environ.get("AIOSTREAMS_URL", "http://aiostreams:3000").rstrip("/")
    targets = [("Configured streaming manifest", aio_url + "/stremio/u/local/manifest.json", True)]
    profiles = {p.strip().strip("\"'") for p in env.get("COMPOSE_PROFILES", "core").split("#", 1)[0].split(",") if p.strip().strip("\"'")}
    if profiles & {"core", "scrapers", "all"}:
        targets += [("Prowlarr", "http://prowlarr:9696/ping", False)]
    def check_http(target):
        name, url, manifest = target
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if manifest:
                    data = json.load(response)
                    resources = data.get("resources", [])
                    names = [r.get("name") if isinstance(r, dict) else r for r in resources]
                    if not data.get("id") or "stream" not in names:
                        raise ValueError("Streaming manifest is not ready")
            return {"name": name, "status": "ready"}
        except Exception:
            return {"name": name, "status": "waiting"}
    with ThreadPoolExecutor(max_workers=4) as pool:
        checks.extend(pool.map(check_http, targets))
    remux_enabled = env.get("ENABLE_REMUXDB", "true").lower() not in ("false", "0", "no")
    checks.append({"name": "RemuxDB & MediaInfo Probes", "status": "ready" if remux_enabled else "off"})
    # Setup may have begun while network probes were running.
    try:
        stable = setup_snapshot().get("status") in ("idle", "complete")
    except Exception:
        stable = False
    ready = stable and all(c["status"] in ("ready", "off", "optional") for c in checks)
    return {"ready": ready, "state": "ready" if ready else "waiting",
            "message": "Services are ready for a playback test. Playback has not been verified." if ready else "Waiting for enabled services and your streaming manifest. Testing is locked until these checks pass.",
            "checks": checks}


def run_playback_test(mode=None, content_id=None, kind=None):
    env_vars = read_saved_env()
    if not mode:
        mode = env_vars.get("STREAMING_MODE", "debrid").lower()

    raw_id = content_id.strip() if content_id and isinstance(content_id, str) and content_id.strip() else "tt1375666"
    if not re.fullmatch(r"[a-zA-Z0-9:_.-]{1,100}", raw_id):
        raw_id = "tt1375666"
    sample_id = urllib.parse.quote(raw_id, safe=":")
    sample_kind = kind.strip().lower() if kind and isinstance(kind, str) and kind.strip().lower() in ("movie", "series", "anime") else "movie"

    steps = []
    overall_success = True
    troubleshoot = None
    stream_title = None
    target_url = None

    # Step 1: Upstream Provider / Auth Health
    auth_step = {"name": "Provider Authentication", "status": "pending", "detail": ""}
    if mode == "usenet":
        host = env_vars.get("USENET_HOST", "")
        try:
            port = int(env_vars.get("USENET_PORT", 563) or 563)
        except (ValueError, TypeError):
            port = 563
        user = credential(env_vars, "USENET_USER")
        password = credential(env_vars, "USENET_PASS")
        if not host or not user or not password:
            auth_step.update(status="fail", detail="Usenet NNTP server, username, or password is missing in setup.")
            troubleshoot = "Fill in your Usenet NNTP Host, User, and Password in the Setup form."
            overall_success = False
        else:
            nntp_ok, nntp_msg = test_nntp_login(host, port, user, password, env_vars.get("USENET_SSL", "true") != "false")
            if nntp_ok:
                auth_step.update(status="pass", detail=f"NNTP login passed to {host}:{port}.")
            else:
                auth_step.update(status="fail", detail=f"NNTP login failed: {nntp_msg}")
                troubleshoot = f"Verify your Usenet server address ({host}) and credentials with your Usenet provider."
                overall_success = False
    elif mode == "hybrid":
        debrid_results = []
        for prov in ("realdebrid", "premiumize", "torbox"):
            env_key = PROVIDER_VALIDATORS[prov][0]
            if env_vars.get(env_key):
                res = validate_provider(prov, env_vars[env_key])
                debrid_results.append((prov, res.get("status") == "valid", res.get("detail", "")))

        host = env_vars.get("USENET_HOST", "")
        user = credential(env_vars, "USENET_USER")
        password = credential(env_vars, "USENET_PASS")
        try:
            port = int(env_vars.get("USENET_PORT", 563) or 563)
        except (ValueError, TypeError):
            port = 563
        usenet_ok = False
        if host and user and password:
            usenet_ok, _ = test_nntp_login(host, port, user, password, env_vars.get("USENET_SSL", "true") != "false")

        valid_debrids = [p.capitalize() for p, ok, _ in debrid_results if ok]
        if valid_debrids or usenet_ok:
            details = []
            if valid_debrids:
                details.append(f"Debrid ({', '.join(valid_debrids)}) verified")
            if usenet_ok:
                details.append(f"NNTP login to {host} passed")
            auth_step.update(status="pass", detail="; ".join(details) + ".")
        else:
            auth_step.update(status="fail", detail="Neither Debrid nor Usenet credentials passed validation.")
            troubleshoot = "Check your Debrid API key and Usenet login in the setup form."
            overall_success = False
    else:  # debrid mode
        debrid_results = []
        for prov in ("realdebrid", "premiumize", "torbox"):
            env_key = PROVIDER_VALIDATORS[prov][0]
            if env_vars.get(env_key):
                res = validate_provider(prov, env_vars[env_key])
                debrid_results.append((prov, res["status"] == "valid", res["detail"]))
        if not debrid_results:
            auth_step.update(status="fail", detail="No debrid provider key is configured.")
            troubleshoot = "Enter your Real-Debrid, Premiumize, or TorBox API key in the Setup form."
            overall_success = False
        elif any(ok for _, ok, _ in debrid_results):
            valid_names = [p.capitalize() for p, ok, _ in debrid_results if ok]
            auth_step.update(status="pass", detail=f"{', '.join(valid_names)} API key verified.")
        else:
            auth_step.update(status="fail", detail="Configured debrid provider key was rejected.")
            troubleshoot = "Your debrid provider API key may be expired. Check your debrid account status."
            overall_success = False
    steps.append(auth_step)

    # Step 2: Stream Resolution
    stream_step = {"name": "Stream Resolution", "status": "pending", "detail": ""}
    resolved_candidate = None
    if overall_success:
        install_info = None
        for p in ("/app/data/aiostreams/aiostreams_install.json", "data/aiostreams/aiostreams_install.json"):
            if os.path.isfile(p):
                try:
                    install_info = json.loads(Path(p).read_text(encoding="utf-8"))
                    break
                except Exception:
                    pass

        streams = []
        aio_url = os.environ.get("AIOSTREAMS_URL", "http://aiostreams:3000").rstrip("/")
        aio_urls = [aio_url]
        fb_aio = get_service_fallback_url(aio_url)
        if fb_aio and fb_aio not in aio_urls:
            aio_urls.append(fb_aio)
        for cur_aio in aio_urls:
            if streams:
                break
            if install_info and install_info.get("uuid"):
                pw = install_info.get("encrypted_password") or install_info.get("encryptedPassword") or ""
                target = f"{cur_aio}/stremio/{install_info['uuid']}/{pw}/stream/{sample_kind}/{sample_id}.json"
                try:
                    req = urllib.request.Request(target, headers={"User-Agent": "AIO-Playback-Test/1.0"})
                    with urllib.request.urlopen(req, timeout=25) as resp:
                        data = json.load(resp)
                        streams = data.get("streams", [])
                except Exception:
                    pass

            if not streams:
                try:
                    req = urllib.request.Request(f"{cur_aio}/stremio/u/local/stream/{sample_kind}/{sample_id}.json", headers={"User-Agent": "AIO-Playback-Test/1.0"})
                    with urllib.request.urlopen(req, timeout=25) as resp:
                        data = json.load(resp)
                        streams = data.get("streams", [])
                except Exception:
                    pass

        if streams:
            candidates = [s for s in streams if s.get("url")]
            if candidates:
                resolved_candidate = candidates[0]
                stream_title = resolved_candidate.get("title") or resolved_candidate.get("name") or "Movie Stream"
                stream_title = stream_title.split("\n")[0][:45]
                stream_step.update(status="pass", detail=f"Resolved {len(streams)} streams. Candidate: {stream_title}.")
            else:
                stream_step.update(status="attention", detail=f"Found {len(streams)} stream items, but none have instant playback URLs.")
                troubleshoot = "Streams were discovered but none are cached for instant playback."
                overall_success = False
        else:
            if mode == "usenet":
                stream_step.update(status="fail", detail="The NZB indexer returned no results for sample query.")
                troubleshoot = "Check your NZB indexer URL and API key configuration in Portal settings / AIOStreams direct Newznab presets."
            else:
                stream_step.update(status="fail", detail="Scrapers returned no stream results for sample title.")
                troubleshoot = "Ensure Prowlarr or Torrentio is enabled and scrapers can reach public trackers."
            overall_success = False
    else:
        stream_step.update(status="skipped", detail="Skipped due to upstream auth failure.")
    steps.append(stream_step)

    # Step 3: Media transport probe. Player decoding is checked separately.
    media_step = {"name": "Media Range Read", "status": "pending", "detail": ""}
    client_stream_url = None
    if overall_success and resolved_candidate and resolved_candidate.get("url"):
        client_stream_url = resolved_candidate["url"]
        target_url = client_stream_url
        parsed = urllib.parse.urlsplit(target_url)
        ports = {None: ("aiostreams", 3000), 3000: ("aiostreams", 3000), 3001: ("aiostreams", 3000), 8080: ("stremthru", 8080)}
        base_host = urllib.parse.urlsplit(env_vars.get("BASE_URL", "")).hostname
        if (parsed.hostname in ("localhost", "127.0.0.1", "aio.yourdomain.com", base_host) or parsed.port in (3000, 3001)) and parsed.port in ports:
            h, pt = ports[parsed.port]
            target_url = urllib.parse.urlunsplit(("http", f"{h}:{pt}", parsed.path, parsed.query, ""))

        t0 = time.monotonic()
        try:
            req = urllib.request.Request(target_url, headers={"Range": "bytes=0-1023", "User-Agent": "AIO-Playback-Test/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                block = resp.read(1024)
                elapsed = round(time.monotonic() - t0, 3)
                is_matroska = block.startswith(bytes.fromhex("1a45dfa3"))
                is_mp4 = b"ftyp" in block[:32]
                content_type = resp.headers.get_content_type()
                if content_type.startswith("text/") or content_type in ("application/json", "application/problem+json", "application/xhtml+xml"):
                    media_step.update(status="fail", detail="The origin returned a text or error response instead of media.")
                    troubleshoot = "Check whether the provider or proxy is returning a login or error page."
                    overall_success = False
                elif resp.status in (200, 206) and block:
                    container = "Matroska/WebM header" if is_matroska else ("MP4 header" if is_mp4 else "media response")
                    media_step.update(
                        status="pass",
                        detail=f"Received {len(block)} bytes in {elapsed}s (HTTP {resp.status}, {container})."
                    )
                else:
                    media_step.update(
                        status="fail",
                        detail=f"Origin returned HTTP {resp.status} with {len(block)} bytes."
                    )
                    troubleshoot = "Media stream origin did not return partial content."
                    overall_success = False
        except Exception as e:
            media_step.update(status="fail", detail=f"Byte-range origin read failed: {type(e).__name__}")
            troubleshoot = "Video stream could not be read from BuiltinProxy. Check proxy connectivity and provider CDN status."
            overall_success = False
    elif overall_success:
        media_step.update(status="pass", detail="Sample media transport verified.")
    else:
        media_step.update(status="skipped", detail="Skipped due to earlier failure.")
    steps.append(media_step)

    steps_dict = {
        "auth": auth_step,
        "stream_resolution": stream_step,
        "media_read": media_step
    }
    return {
        "success": overall_success,
        "overall_success": overall_success,
        "status": "ok" if overall_success else ("warning" if any(s.get("status") in ("attention", "warning") for s in steps) else "failed"),
        "mode": mode,
        "steps": steps,
        "steps_dict": steps_dict,
        "stream_url": client_stream_url if overall_success else None,
        "stream_title": stream_title if resolved_candidate else None,
        "content_id": sample_id,
        "kind": sample_kind,
        "troubleshoot": troubleshoot,
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }


def run_smoke_test(kind, content_id):
    kind = str(kind or "").lower()
    content_id = str(content_id or "").strip()
    if kind not in ("movie", "series") or not content_id:
        return {"status": "invalid", "detail": "Use movie or series with a content ID."}
    base = os.environ.get("AIOSTREAMS_URL", "http://aiostreams:3000").rstrip("/")
    url = f"{base}/stremio/u/local/stream/{kind}/{urllib.parse.quote(content_id, safe='')}.json"
    try:
        with urllib.request.urlopen(url, timeout=25) as response:
            payload = json.load(response)
        streams = payload.get("streams", []) if isinstance(payload, dict) else []
        playable = [item for item in streams if isinstance(item, dict) and (item.get("url") or item.get("infoHash")) and "error" not in str(item.get("title", "")).lower()]
        return {"status": "pass" if playable else "attention", "kind": kind, "contentId": content_id, "streamCount": len(streams), "playableCount": len(playable)}
    except (OSError, ValueError, TypeError, json.JSONDecodeError, urllib.error.URLError):
        return {"status": "unavailable", "kind": kind, "contentId": content_id, "streamCount": 0, "playableCount": 0}


def config_export():
    env_vars = read_saved_env()
    values = {
        "BASE_URL": env_vars.get("BASE_URL", ""),
        "COMPOSE_PROFILES": env_vars.get("COMPOSE_PROFILES", "all"),
        "ENABLE_ANIME_SOURCES": env_vars.get("ENABLE_ANIME_SOURCES", "false"),
    }
    return {
        "format": "aio-local-config-v1",
        "baseUrl": env_vars.get("BASE_URL", ""),
        "profile": env_vars.get("COMPOSE_PROFILES", "all"),
        "values": values,
        "configuredKeys": sorted(key for key, value in env_vars.items() if value and re.search(r"KEY|PASSWORD|TOKEN|SECRET|CLIENT_ID|_ID|MANIFEST_URL", key)),
        "secrets": {key: bool(value) for key, value in env_vars.items() if re.search(r"KEY|PASSWORD|TOKEN|SECRET|CLIENT_ID|_ID|MANIFEST_URL", key)},
    }


def optimized_profile_export():
    """Build the same local profile used by bootstrap for authenticated download,
    preferring live user configuration from AIOStreams when available.
    """
    import importlib.util
    path = os.path.join(WEB_ROOT, "init", "bootstrap", "setup_stack.py")
    if not os.path.isfile(path):
        path = os.path.join(os.path.dirname(__file__), "..", "..", "init", "bootstrap", "setup_stack.py")
    spec = importlib.util.spec_from_file_location("aio_profile_builder", path)
    if not spec or not spec.loader:
        raise RuntimeError("Profile builder is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    live_config = None
    aiostreams_url = os.environ.get("AIOSTREAMS_URL", "http://aiostreams:3000").rstrip("/")
    aio_candidates = [aiostreams_url]
    fb_aio = get_service_fallback_url(aiostreams_url)
    if fb_aio and fb_aio not in aio_candidates:
        aio_candidates.append(fb_aio)
    candidates = [
        os.path.join(WEB_ROOT, "data", "aiostreams", "aiostreams_install.json"),
        os.path.join(WEB_ROOT, "data", "aiostreams_install.json"),
        "/data/aiostreams/aiostreams_install.json",
        "/data/aiostreams_install.json",
    ]
    install_uuid = None
    for c in candidates:
        if os.path.isfile(c):
            try:
                with open(c, "r", encoding="utf-8") as f:
                    idata = json.load(f)
                    if idata.get("uuid"):
                        install_uuid = idata["uuid"]
                        break
            except Exception:
                pass

    saved_env = read_saved_env()
    if install_uuid:
        for pw in (saved_env.get("ADDON_PASSWORD") or os.environ.get("ADDON_PASSWORD") or "admin", "admin_local_secret"):
            if live_config:
                break
            for cur_aio in aio_candidates:
                try:
                    auth = base64.b64encode(f"{install_uuid}:{pw}".encode()).decode("ascii")
                    req = urllib.request.Request(
                        f"{cur_aio}/api/v1/user",
                        headers={"Authorization": f"Basic {auth}", "Accept": "application/json"}
                    )
                    with urllib.request.urlopen(req, timeout=3) as resp:
                        res = json.load(resp)
                        if isinstance(res, dict) and res.get("success") and "userData" in res.get("data", {}):
                            live_config = res["data"]["userData"]
                            break
                except Exception:
                    pass

    return {
        "format": "aio-local-optimized-profile-v1",
        "profile": "all",
        "providerKeys": sorted(
            key for key in ("REALDEBRID_API_KEY", "TORBOX_API_KEY", "ALLDEBRID_API_KEY",
                            "PREMIUMIZE_API_KEY", "DEBRIDLINK_API_KEY", "EASYDEBRID_API_KEY",
                            "OFFCLOUD_API_KEY", "SEEDR_API_KEY", "TMDB_API_KEY", "TVDB_API_KEY")
            if os.environ.get(key) or saved_env.get(key)
        ),
        "config": live_config if live_config is not None else module.build_default_config(probe_services=False),
    }
def proxy_config(kind, base_url):
    base_url = normalize_base_url(base_url or "https://aio.yourdomain.com")
    aiometa = derive_aiometadata_host(base_url)
    hostname = urllib.parse.urlsplit(base_url).hostname or "aio.yourdomain.com"
    meta_host = urllib.parse.urlsplit(aiometa).hostname or "aiometa.yourdomain.com"
    aio_host = base_url.split('://', 1)[-1].split(':', 1)[0]
    meta_slug = aiometa.split('://', 1)[-1].split(':', 1)[0]

    if kind == "caddy":
        caddy_aio = base_url.replace('https://', '').replace('http://', '').rstrip('/')
        caddy_meta = aiometa.replace('https://', '').replace('http://', '').rstrip('/')
        return (
            f"# ==============================================================================\n"
            f"# Caddy Ingress: Web Player & AIOStreams (Single Host)\n"
            f"# ==============================================================================\n"
            f"{caddy_aio} {{\n"
            f"  # Optional: redirect root visits directly to the embedded Web Player\n"
            f"  @root path /\n"
            f"  redir @root /jellyfin/web/ 302\n\n"
            f"  reverse_proxy aiostreams:3000\n"
            f"}}\n\n"
            f"# AIOMetadata Ingress (Optional: only needed if using native Stremio app remotely)\n"
            f"# Note: Keep local when using the Web Player! AIOMetadata stays private on stremio-net.\n"
            f"{caddy_meta} {{\n"
            f"  reverse_proxy aiometadata:4005\n"
            f"}}"
        )
    if kind == "nginx":
        return (
            f"# ==============================================================================\n"
            f"# Nginx Ingress: Web Player & AIOStreams (Single Host)\n"
            f"# ==============================================================================\n"
            f"server {{\n"
            f"  server_name {hostname};\n"
            f"  listen 443 ssl http2;\n\n"
            f"  # Optional: redirect root visits directly to the embedded Web Player\n"
            f"  location = / {{\n"
            f"    return 302 /jellyfin/web/;\n"
            f"  }}\n\n"
            f"  location / {{\n"
            f"    proxy_pass http://aiostreams:3000;\n"
            f"    proxy_set_header Host $host;\n"
            f"    proxy_set_header X-Forwarded-Proto $scheme;\n"
            f"    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
            f"    proxy_read_timeout 3600s;\n"
            f"    proxy_buffering off;\n"
            f"  }}\n"
            f"}}\n\n"
            f"# AIOMetadata host (Optional: only needed if using native Stremio app remotely):\n"
            f"# server {{ server_name {meta_host}; listen 443 ssl http2; location / {{ proxy_pass http://aiometadata:4005; }} }}"
        )
    if kind == "traefik":
        return (
            f"# ==============================================================================\n"
            f"# Traefik Ingress Labels: Web Player & AIOStreams (Single Host)\n"
            f"# ==============================================================================\n"
            f"labels:\n"
            f"  - traefik.enable=true\n"
            f"  - traefik.http.routers.aiostreams.rule=Host(`{hostname}`)\n"
            f"  - traefik.http.services.aiostreams.loadbalancer.server.port=3000\n"
            f"  # AIOMetadata stays private on stremio-net. If native external Stremio is needed:\n"
            f"  # - traefik.http.routers.aiometadata.rule=Host(`{meta_host}`)\n"
            f"  # - traefik.http.services.aiometadata.loadbalancer.server.port=4005"
        )
    if kind == "cloudflare":
        subdomain = aio_host.split('.')[0] if '.' in aio_host else 'watch'
        domain_part = '.'.join(aio_host.split('.')[1:]) if '.' in aio_host else aio_host
        return (
            f"# ==============================================================================\n"
            f"# Cloudflare Zero Trust Tunnel Setup (Recommended — Zero Open Router Ports!)\n"
            f"# ==============================================================================\n"
            f"# 1. In Cloudflare Zero Trust Dashboard (dash.teams.cloudflare.com):\n"
            f"#    Navigate to Networks -> Tunnels -> 'Add a tunnel'.\n"
            f"# 2. Name your tunnel (e.g. 'aio-player') and copy the Tunnel Token.\n"
            f"# 3. Add to your .env file:\n"
            f"#    CLOUDFLARE_TUNNEL_TOKEN=<your-token-here>\n"
            f"#    and start with: docker compose --profile tunnel up -d\n"
            f"#\n"
            f"# 4. In Cloudflare Dashboard, add 1 Public Hostname under your tunnel:\n"
            f"#    • Subdomain: {subdomain}\n"
            f"#    • Domain: {domain_part}\n"
            f"#    • Type: HTTP\n"
            f"#    • URL: aiostreams:3000 (or http://localhost:3001)\n"
            f"#\n"
            f"# 5. Access your Web Player anywhere:\n"
            f"#    https://{aio_host}/jellyfin/web/\n"
            f"#    (AIOMetadata, Prowlarr, Zilean, and Portal remain 100% LOCAL & private!)\n"
            f"# ==============================================================================\n"
            f"# Alternative: Local config.yml ingress rules (CLI / self-managed cloudflared)\n"
            f"# ==============================================================================\n"
            f"tunnel: aio-local\n"
            f"credentials-file: /etc/cloudflared/credentials.json\n\n"
            f"ingress:\n"
            f"  # Web Player & AIOStreams Ingress (Single Host)\n"
            f"  - hostname: {aio_host}\n"
            f"    service: http://aiostreams:3000\n"
            f"  # Optional: only if using native Stremio app remotely outside your home network\n"
            f"  - hostname: {meta_slug}\n"
            f"    service: http://aiometadata:4005\n"
            f"  - service: http_status:404"
        )
    raise ValueError("Unsupported proxy format")


def save_env_updates(updates):
    """Serialize concurrent portal writes and replace the file only when complete."""
    with ENV_LOCK:
        if "COMPOSE_PROFILES" in updates:
            raw = str(updates["COMPOSE_PROFILES"]).split("#", 1)[0]
            normalized = []
            for p in raw.split(","):
                p = p.strip().strip("\"'")
                if not p:
                    continue
                norm = "core" if p == "scrapers" else ("anime" if p == "anime-db" else p)
                if norm not in normalized:
                    normalized.append(norm)
            if normalized:
                updates = {**updates, "COMPOSE_PROFILES": ",".join(normalized)}
        if "ADDON_PASSWORD" in updates:
            saved = read_saved_env()
            prior = saved.get("ADDON_PASSWORD") or os.environ.get("ADDON_PASSWORD") or "admin"
            if prior != updates["ADDON_PASSWORD"] or saved.get("AIO_PORTAL_MANAGED_PASSWORD") != "true":
                if saved.get("AIO_PASSWORD_PREVIOUS") and prior != updates["ADDON_PASSWORD"]:
                    raise ValueError("Finish applying the previous password change before entering another password")
                updates = {**updates,
                           "AIO_PORTAL_MANAGED_PASSWORD": "true",
                           "AIO_PASSWORD_PREVIOUS": saved.get("AIO_PASSWORD_PREVIOUS") or prior}
        target = ENV_PATH if os.path.isfile(ENV_PATH) else ENV_EXAMPLE_PATH
        lines = []
        if os.path.isfile(target):
            with open(target, encoding="utf-8") as source:
                lines = source.read().splitlines()
        result, found = [], set()
        for line in lines:
            key = line.strip().lstrip("#").strip().split("=", 1)[0]
            if key in updates:
                if key not in found:
                    result.append(f"{key}={updates[key]}")
                    found.add(key)
            else:
                result.append(line)
        result.extend(f"{key}={value}" for key, value in updates.items() if key not in found)
        target_path = os.path.realpath(ENV_PATH)
        target_dir = os.path.dirname(target_path) or os.path.dirname(ENV_PATH)
        descriptor, temporary = tempfile.mkstemp(prefix=".env-", dir=target_dir)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                output.write("\n".join(result) + "\n")
            os.replace(temporary, target_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        os.environ.update(updates)
        _ENV_CACHE.update(data={}, mtime=0.0, source="")

def normalize_base_url(url_str):
    if not url_str:
        return "http://localhost:3000"
    value = str(url_str).strip().rstrip("/")
    if "://" in value:
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Use an HTTP or HTTPS server address without login details, queries or fragments")
        parsed.port  # Validate the port range.
        return value
    parsed = urllib.parse.urlsplit("//" + value)
    host = parsed.hostname or ""
    if not host or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Invalid server address")
    try:
        local = ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = host == "localhost" or "." not in host or host.endswith((".local", ".lan"))
    port = parsed.port
    if local:
        authority = parsed.netloc if port else parsed.netloc + ":3000"
        return "http://" + authority + parsed.path
    return "https://" + value


def derive_aiometadata_host(base_url, explicit_host=None):
    if explicit_host and str(explicit_host).strip() not in ("http://localhost:4005", "http://127.0.0.1:4005", "http://aiometadata:4005", ""):
        host_str = str(explicit_host).strip().rstrip("/")
        if "yourdomain.com" not in host_str:
            return host_str
    if not base_url:
        return "http://localhost:4005"
    try:
        parsed = urllib.parse.urlsplit(base_url)
        scheme = parsed.scheme or "https"
        host = parsed.hostname or ""
        if host:
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
            else:
                return f"{scheme}://{host}:4005"
    except Exception:
        pass
    return "http://localhost:4005"


def dashboard_origin(configured, request_host, port, default_port, public_fallback=None):
    """Use the public address when set, otherwise use the portal's host and service port."""
    if configured:
        try:
            origin = normalize_base_url(configured)
        except ValueError:
            origin = "http://localhost"
        host = urllib.parse.urlsplit(origin).hostname
        if host not in ("localhost", "127.0.0.1", "::1", "aiostreams", "aiometadata") and not (
                host == "yourdomain.com" or host.endswith(".yourdomain.com")):
            return origin
    if public_fallback:
        return public_fallback
    try:
        parsed = urllib.parse.urlsplit(normalize_base_url("http://" + request_host))
        host = parsed.hostname if not parsed.path else "localhost"
    except ValueError:
        host = "localhost"
    if ":" in host:
        host = f"[{host}]"
    try:
        port = int(port)
        if not 1 <= port <= 65535:
            raise ValueError("Invalid port")
    except (TypeError, ValueError):
        port = default_port
    return f"http://{host}:{port}"


def service_ui_url(service, request_host, env):
    path = SERVICE_UI_PATHS.get(service)
    if path is None:
        return None
    suffix = service.upper().replace("-", "_")
    override = env.get(f"UI_{suffix}_URL") or os.environ.get(f"UI_{suffix}_URL")
    if override:
        try:
            return normalize_base_url(override)
        except ValueError:
            pass
    if service == "aiometadata":
        aiom_profile = env.get("AIOMETADATA_PROFILE_UUID") if "AIOMETADATA_PROFILE_UUID" in env else os.environ.get("AIOMETADATA_PROFILE_UUID")
        if aiom_profile and str(aiom_profile).strip():
            path = f"/stremio/{urllib.parse.quote(str(aiom_profile).strip(), safe='')}/configure"
        else:
            path = "/configure"
    elif service == "aiostreams":
        aios_uuid = env.get("DEFAULT_AIO_UUID") or os.environ.get("DEFAULT_AIO_UUID")
        if aios_uuid:
            path = "/stremio/u/local/configure"
    address_key = {"aiostreams": "BASE_URL", "aiometadata": "AIOMETADATA_HOST"}.get(service)
    address = (env.get(address_key) or os.environ.get(address_key)) if address_key else None
    port = env.get(f"PORT_{suffix}") or os.environ.get(f"PORT_{suffix}")
    return dashboard_origin(address, request_host, port, HOST_PORT_MAP[service]) + path


def public_service_urls(base_url):
    parsed = urllib.parse.urlsplit(base_url)
    host = parsed.hostname or "localhost"
    try:
        is_local = ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        is_local = host == "localhost" or "." not in host or host.endswith((".local", ".lan"))
    if ":" in host:
        host = f"[{host}]"
    ports = {"KITSU_URL": 7005}
    urls = {key: f"{parsed.scheme}://{host}:{port}" for key, port in ports.items()}
    if is_local:
        urls["AIOMETADATA_HOST"] = f"{parsed.scheme}://{host}:4005"
    else:
        urls["AIOMETADATA_HOST"] = derive_aiometadata_host(base_url)
    return urls


ANISKIP_CACHE = {}
ANIME_ID_MAP_CACHE = {}

def resolve_mal_id(raw_id, season=1):
    cache_key = (raw_id, int(season))
    if cache_key in ANIME_ID_MAP_CACHE:
        return ANIME_ID_MAP_CACHE[cache_key]

    db_path = os.path.join(WEB_ROOT, "data", "postersplus", "anime_ids.db")
    if not os.path.isfile(db_path):
        return None
    try:
        clean_path = os.path.abspath(db_path).replace("\\", "/")
        if not clean_path.startswith("/"):
            clean_path = "/" + clean_path
        uri_path = f"file:{clean_path}?immutable=1"
        conn = sqlite3.connect(uri_path, uri=True)
        cur = conn.cursor()
        if raw_id.startswith("kitsu:"):
            k_id = int(raw_id.split(":")[1])
            cur.execute("SELECT mal_id FROM anime_mal_map WHERE kitsu_id = ?", (k_id,))
            row = cur.fetchone()
            mal_id = row[0] if row else None
            ANIME_ID_MAP_CACHE[cache_key] = mal_id
            return mal_id

        cur.execute("SELECT namespace, anime_id FROM anime_id_map WHERE imdb_id = ? AND season = ?", (raw_id, int(season)))
        row = cur.fetchone()
        if not row:
            cur.execute("SELECT namespace, anime_id FROM anime_id_map WHERE imdb_id = ?", (raw_id,))
            row = cur.fetchone()
        if not row:
            return None

        ns, aid = row[0], row[1]
        if ns == "kitsu":
            cur.execute("SELECT mal_id FROM anime_mal_map WHERE kitsu_id = ?", (aid,))
        elif ns == "anilist":
            cur.execute("SELECT mal_id FROM anime_mal_map WHERE anilist_id = ?", (aid,))
        res = cur.fetchone()
        mal_id = res[0] if res else None
        ANIME_ID_MAP_CACHE[cache_key] = mal_id
        return mal_id
    except Exception:
        return None

def get_aniskip_times(mal_id, episode=1, duration=0):
    cache_key = (mal_id, int(episode))
    now = time.monotonic()
    if cache_key in ANISKIP_CACHE:
        stamp, data = ANISKIP_CACHE[cache_key]
        if now - stamp < 86400:
            return data

    url = f"https://api.aniskip.com/v2/skip-times/{mal_id}/{episode}?types[]=op&types[]=ed&types[]=mixed-op&types[]=mixed-ed&types[]=recap&episodeLength={int(duration)}"
    req = urllib.request.Request(url, headers={"User-Agent": "AIO-Local-Stack/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode())
            ANISKIP_CACHE[cache_key] = (now, data)
            return data
    except Exception:
        res = {"found": False}
        ANISKIP_CACHE[cache_key] = (now, res)
        return res

def dispatch_webhook_notification(webhook_url, title, message, url=None):
    if not webhook_url:
        return False, "No webhook URL provided"
    try:
        payload = {
            "content": f"**[AIO Simulcast Alert]** {title}\n{message}" + (f"\nWatch: {url}" if url else ""),
            "embeds": [{
                "title": title,
                "description": message,
                "url": url or os.environ.get("BASE_URL", "http://localhost:3001"),
                "color": 15115627,
                "footer": {"text": "AIO Local • Simulcast Alerts"}
            }]
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(webhook_url, data=data, headers={"Content-Type": "application/json", "User-Agent": "AIO-Stack-Notifier/1.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            return True, f"Delivered (HTTP {resp.status})"
    except Exception as e:
        return False, str(e)

_STATUS_PROBE_CACHE = {"docker_ready": False, "aggregator_ready": False, "timestamp": 0.0}


PORTAL_API_GET_PATHS = {
    "/api/setup-status", "/api/export-manifest", "/api/playback-readiness",
    "/api/integrations", "/api/maintenance", "/api/search-status",
    "/api/diagnostics/export", "/api/diagnostics-export", "/api/diagnostics",
    "/api/config-export", "/api/export-profile", "/api/export-aiometadata",
    "/api/profile-recommendation", "/api/update-plan", "/api/proxy-config",
    "/api/status", "/api/manifest-info", "/api/env", "/api/logs",
    "/api/templates", "/api/backup", "/api/resources", "/api/health-stats",
    "/api/watchdog", "/api/zilean", "/api/zilean-stats",
    "/api/lumiere/stats", "/api/lumiere-stats", "/api/backups",
    "/api/lumiere/search", "/api/lumiere-search",
    "/api/flaresolverr", "/api/benchmark", "/api/clean-cache",
    "/api/aniskip", "/api/health-stream", "/api/player-preferences",
    "/api/config-bundle-raw", "/api/cloudflare/status",
}

PORTAL_API_POST_PATHS = {
    "/api/webhook-test", "/api/setup", "/api/aiometadata/apply-template",
    "/api/validate-provider", "/api/test-provider", "/api/smoke-test", "/api/test-playback",
    "/api/config-import", "/api/save-env", "/api/quick-setup",
    "/api/settings", "/api/env", "/api/save", "/api/restart",
    "/api/clean-cache", "/api/watchdog", "/api/backups/prune",
    "/api/lumiere/rebuild", "/api/aniskip", "/api/player-preferences",
    "/api/cloudflare/push-dns", "/api/cloudflare/tunnel",
}

_TELEMETRY_CACHE = {"data": None, "timestamp": 0.0, "lock": threading.Lock()}

def get_cached_watchdog_telemetry(max_age=3.0):
    """Retrieve cached watchdog probe results to prevent thundering herd on live SSE streams."""
    now = time.monotonic()
    with _TELEMETRY_CACHE["lock"]:
        if _TELEMETRY_CACHE["data"] is not None and (now - _TELEMETRY_CACHE["timestamp"]) < max_age:
            return _TELEMETRY_CACHE["data"]
        try:
            sys.path.insert(0, str(WEB_ROOT))
            import tools.watchdog as stack_watchdog
            data = stack_watchdog.probe_all_services(auto_restart=False)
            _TELEMETRY_CACHE["data"] = data
            _TELEMETRY_CACHE["timestamp"] = now
            return data
        except Exception as e:
            if _TELEMETRY_CACHE["data"] is not None:
                return _TELEMETRY_CACHE["data"]
            return {"healthy_count": 0, "total_probed": 0, "services": [], "error": str(e)}

PREFERENCES_FILE = os.path.join(WEB_ROOT, "data/player_preferences.json")
_PLAYER_PREFS_MEMORY_CACHE = None

def get_player_preferences():
    global _PLAYER_PREFS_MEMORY_CACHE
    if _PLAYER_PREFS_MEMORY_CACHE is not None:
        return dict(_PLAYER_PREFS_MEMORY_CACHE)
    data = {}
    if os.path.isfile(PREFERENCES_FILE):
        try:
            with open(PREFERENCES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
    audio = data.get("audioLanguage") or data.get("audio_language") or "eng"
    audio_fb = data.get("audioFallback") or data.get("audio_fallback") or "jpn"
    sub_mode = data.get("subtitleMode") or data.get("subtitle_mode") or "forced"
    sub_lang = data.get("subtitleLanguage") or data.get("subtitle_language") or "eng"
    font_scale = data.get("fontScale") or data.get("font_scale") or 100

    normalized = {
        "audioLanguage": audio,
        "audio_language": audio,
        "audioFallback": audio_fb,
        "audio_fallback": audio_fb,
        "subtitleMode": sub_mode,
        "subtitle_mode": sub_mode,
        "subtitleLanguage": sub_lang,
        "subtitle_language": sub_lang,
        "fontScale": font_scale,
        "font_scale": font_scale,
    }
    _PLAYER_PREFS_MEMORY_CACHE = normalized
    return dict(normalized)

def save_player_preferences(prefs):
    global _PLAYER_PREFS_MEMORY_CACHE
    audio = prefs.get("audioLanguage") or prefs.get("audio_language") or "eng"
    audio_fb = prefs.get("audioFallback") or prefs.get("audio_fallback") or "jpn"
    sub_mode = prefs.get("subtitleMode") or prefs.get("subtitle_mode") or "forced"
    sub_lang = prefs.get("subtitleLanguage") or prefs.get("subtitle_language") or "eng"
    font_scale = prefs.get("fontScale") or prefs.get("font_scale") or 100

    normalized = {
        "audioLanguage": audio,
        "audio_language": audio,
        "audioFallback": audio_fb,
        "audio_fallback": audio_fb,
        "subtitleMode": sub_mode,
        "subtitle_mode": sub_mode,
        "subtitleLanguage": sub_lang,
        "subtitle_language": sub_lang,
        "fontScale": font_scale,
        "font_scale": font_scale,
    }
    _PLAYER_PREFS_MEMORY_CACHE = normalized
    try:
        os.makedirs(os.path.dirname(PREFERENCES_FILE), exist_ok=True)
        with open(PREFERENCES_FILE, "w", encoding="utf-8") as f:
            json.dump(normalized, f, indent=2)
    except OSError:
        pass

    # Asynchronously sync language preferences to AIOStreams if running
    def _sync_to_aiostreams():
        try:
            aio_url = os.environ.get("AIOSTREAMS_URL", "http://aiostreams:3000").rstrip("/")
            auth_bytes = f"admin:{read_saved_env().get('ADDON_PASSWORD', 'admin')}".encode("utf-8")
            headers = {
                "Authorization": f"Basic {base64.b64encode(auth_bytes).decode('ascii')}",
                "Content-Type": "application/json"
            }
            req_data = json.dumps({
                "preferredLanguages": [audio],
                "preferredSubtitleLanguages": [sub_lang]
            }).encode("utf-8")
            req = urllib.request.Request(f"{aio_url}/api/v1/user", data=req_data, headers=headers, method="PATCH")
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass
    threading.Thread(target=_sync_to_aiostreams, daemon=True).start()

    return dict(normalized)


class AppliancePortalHandler(http.server.SimpleHTTPRequestHandler):
    server_version = "AIO-Portal"
    sys_version = ""

    def version_string(self):
        return "AIO-Portal"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_ROOT, **kwargs)

    def end_headers(self):
        if getattr(self, "_is_proxy_response", False):
            super().end_headers()
            return
        if hasattr(self, "path") and self.path in ("/", "/index.html", "/dashboard", "/admin", "/dashboard.html"):
            self.send_header("Set-Cookie", "active_service_proxy=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob: http: https:; frame-src 'self' http: https: data: blob:; frame-ancestors 'none'; object-src 'none'; base-uri 'self';")
        super().end_headers()

    def read_json_body(self, max_size=65536):
        """Safely read and parse JSON request body with strict boundary limits."""
        raw_len = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_len or 0)
        except (ValueError, TypeError):
            raise ValueError("Invalid Content-Length header")
        if length < 0:
            raise ValueError("Content-Length cannot be negative")
        if length > max_size:
            try:
                drain = min(length, 1024 * 1024)
                while drain > 0:
                    chunk = self.rfile.read(min(drain, 65536))
                    if not chunk:
                        break
                    drain -= len(chunk)
            except Exception:
                pass
            raise ValueError("Request body is too large")
        if length == 0:
            return {}
        try:
            body = self.rfile.read(length)
        except (OSError, ConnectionError) as e:
            raise ValueError("Failed to read request body") from e
        if not body or not body.strip():
            return {}
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ValueError("Request body must be valid JSON") from e
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        return payload

    def request_origin_is_local(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = (self.headers.get("X-Forwarded-Host") or self.headers.get("Host", "")).split(",")[0].strip().lower()
        try:
            origin_split = urllib.parse.urlsplit(origin)
            origin_netloc = origin_split.netloc.lower()
            if origin_netloc == host:
                return True
            # Normalize implicit vs explicit standard HTTP/HTTPS ports (80/443)
            clean_host = host.split(":")[0] if (host.endswith(":80") or host.endswith(":443")) else host
            clean_origin = origin_netloc.split(":")[0] if (origin_netloc.endswith(":80") or origin_netloc.endswith(":443")) else origin_netloc
            return clean_origin == clean_host
        except ValueError:
            return False

    def authorize(self):
        auth_required = (os.environ.get("PORTAL_AUTH_REQUIRED") or read_saved_env().get("PORTAL_AUTH_REQUIRED", "true")).lower() in ("true", "1", "yes")
        if not auth_required:
            return True
        password = read_saved_env().get("ADDON_PASSWORD") or os.environ.get("ADDON_PASSWORD")
        if not password:
             # If auth is required but no password is set, fail.
             self.send_error(401, "No authentication password configured.")
             return False
        client = self.client_address[0]
        now = time.monotonic()
        if len(AUTH_FAILURES) > 100:
            for ip in list(AUTH_FAILURES.keys()):
                stamps = [s for s in AUTH_FAILURES[ip] if now - s < AUTH_FAILURE_WINDOW]
                if stamps:
                    AUTH_FAILURES[ip] = stamps
                else:
                    AUTH_FAILURES.pop(ip, None)
        recent = [stamp for stamp in AUTH_FAILURES.get(client, []) if now - stamp < AUTH_FAILURE_WINDOW]
        if len(recent) >= AUTH_FAILURE_LIMIT:
            self.send_error(429, "Too many authentication attempts")
            return False
        expected = "Basic " + base64.b64encode(
            ("admin:" + password).encode()
        ).decode()
        if hmac.compare_digest(self.headers.get("Authorization", "").encode(), expected.encode()):
            AUTH_FAILURES.pop(client, None)
            return True
        recent.append(now)
        AUTH_FAILURES[client] = recent
        if self.command == "POST":
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
                if 0 < length <= 65536:
                    self.rfile.read(length)
                elif length > 65536:
                    self.rfile.read(65536)
            except Exception:
                pass
        self.close_connection = True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="AIOStreams Portal"')
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()
        return False

    def send_head(self):
        # SimpleHTTPRequestHandler otherwise exposes .env, databases and .git,
        # including through HEAD requests, encoded paths and symbolic links.
        try:
            clean_path = urllib.parse.unquote(self.path.split("?", 1)[0].split("#", 1)[0])
            if "\x00" in clean_path or any(ord(c) < 32 for c in clean_path):
                self.send_error(404)
                return None
            target = pathlib.Path(self.translate_path(self.path)).resolve()
            root = pathlib.Path(WEB_ROOT).resolve()
            relative = target.relative_to(root)
        except (ValueError, OSError):
            self.send_error(404)
            return None
        allowed = (relative.as_posix() in ("index.html", "dashboard.html")
                   or (relative.parts and relative.parts[0] in ("assets", "templates")
                       and target.suffix.lower() in (".json", ".png", ".jpg", ".jpeg", ".svg", ".webp", ".css", ".js")))
        if not allowed or not target.is_file() or any(p.startswith(".") for p in relative.parts):
            url_parts = urllib.parse.urlsplit(self.path)
            if self.check_proxy_referer_fallback(url_parts.path, url_parts.query):
                return None
            self.send_error(404)
            return None
        return super().send_head()

    def proxy_to_service(self, service, subpath, query="", is_alias=False, watch_base=None):
        if service not in INTERNAL_SERVICE_TARGETS:
            self.send_error(404, f"Service '{service}' not found")
            return

        container, internal_port, default_host_port = INTERNAL_SERVICE_TARGETS[service]
        env_vars = read_saved_env()
        custom_port_var = f"PORT_{service.upper().replace('-', '_')}"
        host_port = int(env_vars.get(custom_port_var) or os.environ.get(custom_port_var) or default_host_port)

        candidates = []
        for c in (f"http://{container}:{internal_port}", f"http://127.0.0.1:{host_port}"):
            if c not in candidates:
                candidates.append(c)
        if service == "subsense":
            alt = f"http://stremio-subsense:{internal_port}"
            if alt not in candidates:
                candidates.insert(1, alt)

        normalized_subpath = "/" + subpath.lstrip("/") if subpath else "/"
        query_str = f"?{query}" if query else ""
        rel_url = f"{normalized_subpath}{query_str}"

        if service == "postersplus" and "access_key" not in query and normalized_subpath in ("/", "/admin", "/admin/"):
            p_key = env_vars.get("POSTERSPLUS_ACCESS_KEY") or env_vars.get("ADDON_PASSWORD", "admin")
            if p_key:
                qs = f"access_key={urllib.parse.quote(p_key)}"
                if query:
                    qs = f"{query}&{qs}"
                self.send_response(302)
                self.send_header("Location", f"/service-proxy/postersplus/admin?{qs}")
                self.end_headers()
                return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except (ValueError, TypeError):
            content_length = 0
        if content_length > 32 * 1024 * 1024:
            self.send_error(413, "Request body too large")
            return
        body = self.rfile.read(content_length) if content_length > 0 else None

        hop_by_hop = {
            "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
            "te", "trailers", "transfer-encoding", "upgrade", "host"
        }
        forward_headers = {k: v for k, v in self.headers.items() if k.lower() not in hop_by_hop}
        forward_headers["X-Forwarded-For"] = self.client_address[0]
        forward_headers["X-Forwarded-Proto"] = "http"
        forward_headers["X-Forwarded-Host"] = self.headers.get("Host", "localhost")
        forward_headers["Accept-Encoding"] = "identity"

        if service == "prowlarr":
            if "x-api-key" not in [k.lower() for k in forward_headers]:
                prowlarr_key = env_vars.get("PROWLARR_API_KEY") or os.environ.get("PROWLARR_API_KEY") or "prowlarr_internal_secret_key_99"
                forward_headers["X-Api-Key"] = prowlarr_key

        status_code = None
        resp_headers = None
        response_data = None
        last_error = None

        for base in candidates:
            target_url = f"{base}{rel_url}"
            try:
                req = urllib.request.Request(
                    target_url,
                    data=body,
                    headers=forward_headers,
                    method=self.command
                )
                try:
                    with _PROXY_OPENER.open(req, timeout=10) as resp:
                        status_code = resp.status
                        resp_headers = resp.headers
                        response_data = resp.read()
                        break
                except urllib.error.HTTPError as e:
                    status_code = e.code
                    resp_headers = e.headers
                    response_data = e.read()
                    break
            except Exception as e:
                last_error = e
                continue

        if status_code is None:
            self._is_proxy_response = True
            try:
                self.send_response(502)
                self.send_header("X-Frame-Options", "SAMEORIGIN")
                accept = self.headers.get("Accept", "")
                if "application/json" in accept and "text/html" not in accept:
                    self.send_header("Content-Type", "application/json")
                    err_bytes = json.dumps({
                        "error": "Bad Gateway",
                        "service": service,
                        "detail": f"Could not connect to {service} internally: {type(last_error).__name__}"
                    }).encode()
                    self.send_header("Content-Length", str(len(err_bytes)))
                    self.end_headers()
                    self.wfile.write(err_bytes)
                else:
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    html_msg = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{html.escape(service)} Initializing</title>
<style>
body {{ background: #0b0f19; color: #e2e8f0; font-family: system-ui, -apple-system, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
.card {{ background: #131b2e; border: 1px solid #1e293b; border-radius: 12px; padding: 32px; max-width: 440px; text-align: center; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
h2 {{ margin-top: 0; color: #38bdf8; font-size: 1.25rem; font-weight: 700; }}
p {{ color: #94a3b8; font-size: 0.9rem; line-height: 1.5; }}
.spinner {{ width: 32px; height: 32px; border: 3px solid #334155; border-top-color: #38bdf8; border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 16px; }}
@keyframes spin {{ to {{ transform: rotate(360deg); }} }}
button {{ background: #0284c7; color: #fff; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer; font-weight: 600; margin-top: 14px; }}
button:hover {{ background: #0369a1; }}
</style></head>
<body><div class="card"><div class="spinner"></div><h2>Connecting to {html.escape(service)}</h2><p>The container is currently initializing on the internal Docker network. Please wait a moment and retry.</p><button onclick="location.reload()">Retry Connection</button></div></body></html>"""
                    err_bytes = html_msg.encode("utf-8")
                    self.send_header("Content-Length", str(len(err_bytes)))
                    self.end_headers()
                    self.wfile.write(err_bytes)
            finally:
                self._is_proxy_response = False
            return

        location = resp_headers.get("Location")
        if location and status_code in (301, 302, 303, 307, 308):
            parsed_loc = urllib.parse.urlsplit(location)
            if not parsed_loc.netloc or parsed_loc.netloc in (f"{container}:{internal_port}", f"127.0.0.1:{host_port}", f"localhost:{host_port}"):
                loc_path = parsed_loc.path or "/"
                if is_alias:
                    if loc_path.startswith("/jellyfin"):
                        new_loc = loc_path
                    else:
                        new_loc = "/jellyfin" + ("/" + loc_path.lstrip("/") if loc_path else "/")
                elif service == "prowlarr" and loc_path.startswith("/service-proxy/prowlarr"):
                    # Prowlarr already includes its urlBase in Location headers; pass through as-is.
                    new_loc = loc_path
                else:
                    new_loc = f"/service-proxy/{service}" + ("/" + loc_path.lstrip("/") if loc_path else "/")
                if parsed_loc.query:
                    new_loc += f"?{parsed_loc.query}"
                location = new_loc

        content_type = resp_headers.get("Content-Type", "")
        if response_data and "text/html" in content_type.lower():
            try:
                encoding = "utf-8"
                match = re.search(r"charset=([a-zA-Z0-9_-]+)", content_type, re.I)
                if match:
                    encoding = match.group(1)
                html_text = response_data.decode(encoding, errors="replace")
                if is_alias:
                    if watch_base:
                        base_href = watch_base
                    else:
                        base_href = "/jellyfin/web/" if "/web" in normalized_subpath else "/jellyfin/"
                else:
                    base_href = f"/service-proxy/{service}/"

                if service == "prowlarr":
                    html_text = re.sub(r"(urlBase:\s*['\"])(['\"])", r"\1/service-proxy/prowlarr\2", html_text)
                    html_text = re.sub(r'((?:href|src)=["\'])/(Content/|index-[^"\']+)', r'\1/service-proxy/prowlarr/\2', html_text)

                if "<base" not in html_text.lower():
                    base_tag = f'<base href="{base_href}">'
                    if "<head" in html_text.lower():
                        html_text = re.sub(r"(<head[^>]*>)", r"\1" + base_tag, html_text, count=1, flags=re.I)
                    elif "<html" in html_text.lower():
                        html_text = re.sub(r"(<html[^>]*>)", r"\1<head>" + base_tag + "</head>", html_text, count=1, flags=re.I)
                    else:
                        html_text = base_tag + html_text
                    response_data = html_text.encode(encoding)
            except Exception:
                pass

        if response_data and service == "prowlarr" and (normalized_subpath == "/initialize.json" or normalized_subpath.startswith("/initialize.json")):
            try:
                init_data = json.loads(response_data.decode("utf-8"))
                if isinstance(init_data, dict):
                    if not init_data.get("urlBase"):
                        init_data["urlBase"] = "/service-proxy/prowlarr"
                    if not init_data.get("apiRoot", "").startswith("/service-proxy/prowlarr"):
                        init_data["apiRoot"] = "/service-proxy/prowlarr/api/v1"
                    response_data = json.dumps(init_data).encode("utf-8")
            except Exception:
                pass

        self._is_proxy_response = True
        try:
            self.send_response(status_code)
            for k, v in resp_headers.items():
                k_lower = k.lower()
                if k_lower in ("transfer-encoding", "content-length", "connection", "accept-ranges"):
                    continue
                if k_lower == "x-frame-options":
                    self.send_header("X-Frame-Options", "SAMEORIGIN")
                    continue
                if k_lower == "content-security-policy":
                    v = re.sub(r"frame-ancestors\s+[^;]+;?", "frame-ancestors 'self';", v, flags=re.I)
                    self.send_header(k, v)
                    continue
                if k_lower == "location" and location:
                    self.send_header("Location", location)
                    continue
                self.send_header(k, v)

            self.send_header("Set-Cookie", f"active_service_proxy={service}; Path=/service-proxy/; SameSite=Lax")

            if "x-frame-options" not in [k.lower() for k in resp_headers.keys()]:
                self.send_header("X-Frame-Options", "SAMEORIGIN")

            if response_data is not None:
                self.send_header("Content-Length", str(len(response_data)))
            self.end_headers()

            if self.command != "HEAD" and response_data:
                self.wfile.write(response_data)
        finally:
            self._is_proxy_response = False

    def handle_proxy_route(self, path, query=""):
        if path in ("/service-proxy", "/service-proxy/"):
            self.send_error(404, "Specify a service: /service-proxy/<service>/")
            return
        if path.startswith("/service-proxy/"):
            rest = path[len("/service-proxy/"):]
            service, sep, subpath = rest.partition("/")
            if not sep:
                qs = f"?{query}" if query else ""
                self.send_response(302)
                self.send_header("Location", f"/service-proxy/{service}/{qs}")
                self.end_headers()
                return
            self.proxy_to_service(service, "/" + subpath, query, is_alias=False)
            return
        if path == "/jellyfin" or path.startswith("/jellyfin/"):
            self.proxy_to_service("aiostreams", path, query, is_alias=True)
            return

    def get_active_service_from_request(self):
        clean_path = urllib.parse.urlsplit(self.path).path
        if (clean_path.startswith("/assets/") or clean_path.startswith("/templates/")
                or clean_path in ("/", "/index.html", "/dashboard", "/admin", "/dashboard.html", "/app.webmanifest", "/favicon.ico")
                or clean_path in PORTAL_API_GET_PATHS or clean_path in PORTAL_API_POST_PATHS):
            return None, False
        referer = self.headers.get("Referer", "")
        if referer:
            match = re.search(r"/service-proxy/([a-zA-Z0-9_-]+)(?:/|$)", referer)
            if match and match.group(1) in INTERNAL_SERVICE_TARGETS:
                return match.group(1), False
            if "/jellyfin" in referer and "aiostreams" in INTERNAL_SERVICE_TARGETS:
                return "aiostreams", True
        cookie_header = self.headers.get("Cookie", "")
        if cookie_header:
            match = re.search(r"(?:^|;\s*)active_service_proxy=([a-zA-Z0-9_-]+)", cookie_header)
            if match and match.group(1) in INTERNAL_SERVICE_TARGETS:
                return match.group(1), False
        return None, False

    def check_proxy_referer_fallback(self, path, query=""):
        service, is_alias = self.get_active_service_from_request()
        if service:
            self.proxy_to_service(service, path, query, is_alias=is_alias)
            return True
        return False

    def do_OPTIONS(self):
        url_parts = urllib.parse.urlsplit(self.path)
        path = url_parts.path
        if path.startswith("/service-proxy") or path == "/jellyfin" or path.startswith("/jellyfin/"):
            self.handle_proxy_route(path, url_parts.query)
            return
        if self.check_proxy_referer_fallback(path, url_parts.query):
            return
        if path in ("/api/aniskip", "/aniskip"):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            return
        if not self.request_origin_is_local():
            self.send_error(403, "Cross-origin requests are not allowed")
            return
        self.send_response(200)
        self.end_headers()

    def _get_jellyfin_credentials(self):
        """Return (uuid, encrypted_password) from install data or env, or (None, None)."""
        install_info = {}
        candidates = [
            os.path.join(WEB_ROOT, "data", "aiostreams_install.json"),
            "/data/aiostreams/aiostreams_install.json",
            "/data/aiostreams_install.json",
        ]
        for c in candidates:
            if os.path.isfile(c):
                try:
                    with open(c, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    enc_cand = data.get("encrypted_password") or data.get("encryptedPassword")
                    if data.get("uuid") and enc_cand:
                        install_info = data
                        break
                    elif not install_info:
                        install_info = data
                except Exception:
                    pass
        env_vars = read_saved_env()
        raw_uuid = install_info.get("uuid") or env_vars.get("DEFAULT_AIO_UUID")
        raw_enc = (install_info.get("encrypted_password") or install_info.get("encryptedPassword")
                   or env_vars.get("DEFAULT_AIO_ENCRYPTED_PASSWORD"))
        uuid = str(raw_uuid).strip() if raw_uuid and str(raw_uuid).strip() not in ("null", "None", "") else None
        enc = str(raw_enc).strip() if raw_enc and str(raw_enc).strip() not in ("null", "None", "") else None
        return uuid, enc

    def handle_watch_route(self, subpath, query):
        """Serve /watch[/...] as a credential-free alias for the Jellyfin web player.

        The browser address bar stays at /watch/... throughout; the uid and
        encrypted password are resolved internally and never appear in any
        redirected URL or base-href injected into HTML responses.
        """
        jellyfin_enabled = (
            read_saved_env().get("JELLYFIN_ENABLED") or
            os.environ.get("JELLYFIN_ENABLED", "true")
        ).lower() not in ("false", "0", "no")

        if not jellyfin_enabled:
            body = (
                b"<!DOCTYPE html><html lang=en><head><meta charset=utf-8>"
                b"<meta name=viewport content='width=device-width,initial-scale=1.0'>"
                b"<title>Media Player Offline</title><style>"
                b"body{background:#0b0f17;color:#e2e8f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:1.5rem;box-sizing:border-box;}"
                b".card{background:#151e2a;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:2.5rem;max-width:480px;text-align:center;box-shadow:0 12px 32px rgba(0,0,0,0.5);}"
                b"h2{margin:0 0 1rem;color:#f8fafc;font-size:1.4rem;}"
                b"p{color:#94a3b8;font-size:0.95rem;line-height:1.5;margin:0 0 1.75rem;}"
                b"a.btn{display:inline-block;background:#3b82f6;color:#fff;padding:0.7rem 1.4rem;border-radius:8px;text-decoration:none;font-weight:500;font-size:0.95rem;transition:background 0.2s;}"
                b"a.btn:hover{background:#2563eb;}"
                b"</style></head><body><div class=card>"
                b"<h2>Media Player Disabled</h2>"
                b"<p>The integrated media player is currently disabled in your AIO stack settings. Enable Jellyfin in the portal settings to activate it.</p>"
                b"<a href='/' class=btn>Return to Portal &rarr;</a>"
                b"</div></body></html>"
            )
            self.send_response(503)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        uuid, encrypted_password = self._get_jellyfin_credentials()

        if not uuid or not encrypted_password:
            # Credentials not ready yet — stack may not be set up
            body = (
                b"<!DOCTYPE html><html lang=en><head><meta charset=utf-8>"
                b"<meta name=viewport content='width=device-width,initial-scale=1.0'>"
                b"<title>Media Player Setup Required</title><style>"
                b"body{background:#0b0f17;color:#e2e8f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:1.5rem;box-sizing:border-box;}"
                b".card{background:#151e2a;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:2.5rem;max-width:480px;text-align:center;box-shadow:0 12px 32px rgba(0,0,0,0.5);}"
                b"h2{margin:0 0 1rem;color:#f8fafc;font-size:1.4rem;}"
                b"p{color:#94a3b8;font-size:0.95rem;line-height:1.5;margin:0 0 1.75rem;}"
                b"a.btn{display:inline-block;background:#3b82f6;color:#fff;padding:0.7rem 1.4rem;border-radius:8px;text-decoration:none;font-weight:500;font-size:0.95rem;transition:background 0.2s;}"
                b"a.btn:hover{background:#2563eb;}"
                b"</style></head><body><div class=card>"
                b"<h2>Stack Setup Not Complete</h2>"
                b"<p>Initial stack setup has not been finalized yet. Complete your setup in the AIO portal to provision your media credentials.</p>"
                b"<a href='/' class=btn>Open Setup Portal &rarr;</a>"
                b"</div></body></html>"
            )
            self.send_response(503)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # Redirect /watch to native Jellyfin Web Player on the AIOStreams port (3001)
        env_vars = read_saved_env()
        base_url = env_vars.get("BASE_URL") or os.environ.get("BASE_URL")
        host_hdr = (self.headers.get("X-Forwarded-Host") or self.headers.get("Host", "localhost")).split(",")[0].strip()
        raw_host = host_hdr[:host_hdr.rfind("]") + 1] if (host_hdr.startswith("[") and "]" in host_hdr) else (host_hdr.rsplit(":", 1)[0] if ":" in host_hdr else host_hdr)
        aio_port = env_vars.get("PORT_AIOSTREAMS") or os.environ.get("PORT_AIOSTREAMS", "3001")
        proto = "https" if (self.headers.get("X-Forwarded-Proto") == "https" or (base_url and base_url.startswith("https://"))) else "http"

        if base_url and not any(h in base_url for h in ("localhost:3000", "127.0.0.1:3000", "aiostreams:3000")):
            aio_base = base_url.rstrip("/")
        else:
            aio_base = f"{proto}://{raw_host}:{aio_port}"

        qs = f"?{query}" if query else ""
        sub = subpath.lstrip("/")
        if not sub or sub == "web" or sub == "web/":
            target = f"{aio_base}/jellyfin/{uuid}/{encrypted_password}/web/{qs}"
        else:
            stripped = re.sub(r"^web(?=/|$)", "", sub).lstrip("/")
            target = f"{aio_base}/jellyfin/{uuid}/{encrypted_password}/web/{stripped}{qs}"

        self.send_response(302)
        self.send_header("Location", target)
        self.end_headers()
        return

    def do_GET(self):
        url_parts = urllib.parse.urlparse(self.path)
        path = url_parts.path

        # /watch — credential-free Jellyfin web player alias
        if path == "/watch":
            qs = f"?{url_parts.query}" if url_parts.query else ""
            self.send_response(302)
            self.send_header("Location", f"/watch/{qs}")
            self.end_headers()
            return
        if path.startswith("/watch/"):
            subpath = path[len("/watch"):]  # e.g. "/" or "/Items/..."
            self.handle_watch_route(subpath or "/", url_parts.query)
            return

        if path.startswith("/service-proxy") or path == "/jellyfin" or path.startswith("/jellyfin/"):
            self.handle_proxy_route(path, url_parts.query)
            return

        if path in ("/api/aniskip", "/aniskip"):
            query = urllib.parse.parse_qs(url_parts.query)
            raw_id = (query.get("id") or [""])[0].strip()
            if len(raw_id) > 100 or not re.fullmatch(r"[a-zA-Z0-9:_.-]*", raw_id):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"found": False, "reason": "No anime ID mapping"}).encode())
                return
            try:
                season = int((query.get("season") or ["1"])[0] or 1)
            except (ValueError, TypeError):
                season = 1
            season = max(1, min(season, 10000))
            try:
                episode = int((query.get("episode") or ["1"])[0] or 1)
            except (ValueError, TypeError):
                episode = 1
            episode = max(1, min(episode, 100000))
            try:
                duration = float((query.get("duration") or ["0"])[0] or 0)
                if math.isnan(duration) or math.isinf(duration) or duration < 0:
                    duration = 0.0
            except (ValueError, TypeError):
                duration = 0.0
            duration = min(duration, 86400.0)

            if ":" in raw_id:
                parts = raw_id.split(":")
                if raw_id.startswith("kitsu:"):
                    raw_id = f"kitsu:{parts[1]}"
                    if len(parts) >= 3:
                        try:
                            episode = int(parts[2])
                        except ValueError:
                            pass
                else:
                    raw_id = parts[0]
                    if len(parts) >= 3:
                        try:
                            season = int(parts[1])
                            episode = int(parts[2])
                        except ValueError:
                            pass

            mal_id = resolve_mal_id(raw_id, season)
            if not mal_id:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"found": False, "reason": "No anime ID mapping"}).encode())
                return

            skip_data = get_aniskip_times(mal_id, episode, duration)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            resp = dict(skip_data)
            resp["malId"] = mal_id
            self.wfile.write(json.dumps(resp).encode())
            return

        if path == "/app.webmanifest":
            manifest = {
                "name": "AIOStreams Local Appliance",
                "short_name": "AIOStreams",
                "description": "All-In-One Local Stremio & Media Engine Hub",
                "start_url": "/dashboard",
                "display": "standalone",
                "background_color": "#0b0f17",
                "theme_color": "#1e293b",
                "icons": [
                    {
                        "src": "/assets/favicon.ico",
                        "sizes": "64x64 32x32 24x24 16x16",
                        "type": "image/x-icon"
                    }
                ]
            }
            body = json.dumps(manifest, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/manifest+json; charset=utf-8")
            self.send_header("Cache-Control", "public, max-age=86400")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/healthz":
            self.json_response({"status": "ok", "service": "portal"})
            return
        if path == "/version":
            self.json_response({"version": APP_VERSION, "service": "aio-local-portal"})
            return
        if path == "/ready":
            try:
                base = os.environ.get("AIOSTREAMS_URL", "http://aiostreams:3000").rstrip("/")
                endpoints = [base + "/api/v1/status"]
                fb = get_service_fallback_url(endpoints[0])
                if fb and fb not in endpoints:
                    endpoints.append(fb)
                success = False
                for ep in endpoints:
                    try:
                        with urllib.request.urlopen(ep, timeout=2):
                            success = True
                            break
                    except Exception:
                        pass
                if not success:
                    raise OSError("aiostreams not ready")
                self.json_response({"status": "ready", "dependencies": {"aiostreams": "ready"}})
            except (OSError, ValueError, urllib.error.URLError):
                self.json_response({"status": "starting", "dependencies": {"aiostreams": "unavailable"}}, 503)
            return
        if path == "/manifest-ready":
            try:
                base = os.environ.get("AIOSTREAMS_URL", "http://aiostreams:3000").rstrip("/")
                manifest_url = base + "/stremio/u/local/manifest.json"
                endpoints = [manifest_url]
                fb = get_service_fallback_url(manifest_url)
                if fb and fb not in endpoints:
                    endpoints.append(fb)
                manifest = None
                for ep in endpoints:
                    try:
                        with urllib.request.urlopen(ep, timeout=3) as response:
                            manifest = json.load(response)
                            if isinstance(manifest, dict) and manifest.get("id") and manifest.get("resources"):
                                break
                    except Exception:
                        pass
                if not isinstance(manifest, dict) or not manifest.get("id") or not manifest.get("resources"):
                    raise ValueError("Manifest is incomplete")
                self.json_response({"status": "ready", "manifest": manifest.get("id")})
            except (OSError, ValueError, TypeError, json.JSONDecodeError, urllib.error.URLError):
                self.json_response({"status": "starting", "manifest": "unavailable"}, 503)
            return
        if path.startswith("/api/") and path not in PORTAL_API_GET_PATHS:
            if self.check_proxy_referer_fallback(path, url_parts.query):
                return
        if (path.startswith("/api/") or path in ("/", "/index.html", "/dashboard", "/admin", "/dashboard.html")) and not self.authorize():
            return
        if path == "/api/setup-status":
            try:
                self.json_response(setup_snapshot())
            except (OSError, ValueError):
                self.json_response({"error": "Compose controller is not available yet."}, 503)
            return
        if path == "/api/export-manifest":
            try:
                base = os.environ.get("AIOSTREAMS_URL", "http://aiostreams:3000").rstrip("/")
                manifest_url = base + "/stremio/u/local/manifest.json"
                endpoints = [manifest_url]
                fb = get_service_fallback_url(manifest_url)
                if fb and fb not in endpoints:
                    endpoints.append(fb)
                manifest = None
                for ep in endpoints:
                    try:
                        with urllib.request.urlopen(ep, timeout=5) as response:
                            manifest = json.load(response)
                            if isinstance(manifest, dict) and manifest.get("id"):
                                break
                    except Exception:
                        pass
                if not isinstance(manifest, dict) or not manifest.get("id"):
                    raise ValueError("Manifest not ready")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Disposition", 'attachment; filename="aio-local-manifest.json"')
                self.end_headers()
                self.wfile.write(json.dumps(manifest, indent=2).encode())
            except Exception:
                self.json_response({"error": "The manifest is not ready. Complete setup first."}, 503)
            return
        if path == "/api/playback-readiness":
            try:
                self.json_response(playback_readiness())
            except Exception:
                self.json_response({"error": "Internal server error occurred while checking playback readiness."}, 500)
            return
        if path == "/api/integrations":
            try:
                with ThreadPoolExecutor(max_workers=10) as pool:
                    integrations = list(pool.map(probe_integration, INTEGRATIONS))
                env = read_saved_env()
                for item, (_, service, _, _) in zip(integrations, INTEGRATIONS):
                    if item.get("enabled", True):
                        ui_url = service_ui_url(service, self.headers.get("Host", "localhost"), env)
                        if ui_url:
                            item["uiUrl"] = ui_url
                        proxy_path = SERVICE_UI_PATHS.get(service)
                        if proxy_path is not None:
                            if service == "postersplus":
                                p_key = env.get("POSTERSPLUS_ACCESS_KEY") or env.get("ADDON_PASSWORD", "admin")
                                if p_key:
                                    proxy_path = f"/admin?access_key={urllib.parse.quote(p_key)}"
                            item["proxyUrl"] = f"/service-proxy/{service}{proxy_path}"
                self.json_response({"integrations": integrations})
            except Exception:
                self.json_response({"error": "Internal server error occurred while checking integrations."}, 500)
            return
        if path == "/api/maintenance":
            try:
                self.json_response(maintenance_snapshot())
            except Exception:
                self.json_response({"error": "Internal server error occurred while retrieving maintenance snapshot."}, 500)
            return
        if path == "/api/search-status":
            try:
                with urllib.request.urlopen('http://search-broker:8091/status', timeout=2) as response:
                    self.json_response(json.load(response))
            except Exception:
                try:
                    with urllib.request.urlopen('http://127.0.0.1:8091/status', timeout=2) as response:
                        self.json_response(json.load(response))
                except Exception:
                    self.json_response({'status': 'unavailable'}, 503)
            return
        if path in ("/api/diagnostics/export", "/api/diagnostics-export"):
            report_text = generate_diagnostics_report()
            body = report_text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="aio-diagnostics-report.txt"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/diagnostics":
            try:
                self.json_response(diagnostics_snapshot())
            except Exception:
                self.json_response({"error": "Internal server error occurred while retrieving diagnostics."}, 500)
            return
        if path == "/api/config-export":
            try:
                self.json_response(config_export())
            except Exception:
                self.json_response({"error": "Internal server error occurred while exporting config."}, 500)
            return
        if path == "/api/export-profile":
            try:
                body = json.dumps(optimized_profile_export(), indent=2).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Disposition", 'attachment; filename="aio-local-optimized-profile.json"')
                self.end_headers()
                self.wfile.write(body)
            except (OSError, RuntimeError, TypeError, ValueError):
                self.json_response({"error": "The optimized profile is not available yet."}, 503)
            return
        if path == "/api/export-aiometadata":
            try:
                aiom_base = os.environ.get("AIOMETADATA_URL", "http://aiometadata:4005").rstrip("/")
                env_vars = read_saved_env()
                profile_uuid = env_vars.get("AIOMETADATA_PROFILE_UUID")
                addon_pw = env_vars.get("ADDON_PASSWORD") or os.environ.get("ADDON_PASSWORD") or "admin"
                config_data = None
                if profile_uuid:
                    candidates = [f"{aiom_base}/api/config/load/{profile_uuid}"]
                    fb = get_service_fallback_url(candidates[0])
                    if fb and fb not in candidates:
                        candidates.append(fb)
                    for target_url in candidates:
                        try:
                            req = urllib.request.Request(
                                target_url,
                                data=json.dumps({"password": addon_pw, "addonPassword": addon_pw}).encode(),
                                headers={"Content-Type": "application/json"}
                            )
                            with urllib.request.urlopen(req, timeout=5) as resp:
                                res = json.load(resp)
                                if isinstance(res, dict) and res.get("success") and isinstance(res.get("config"), dict):
                                    config_data = res.get("config")
                                    break
                        except Exception:
                            pass

                if not config_data:
                    raw_tmpl = env_vars.get("AIOMETADATA_TEMPLATE", "tamtaro-aiometadata-with-anime.json")
                    tmpl_name = os.path.basename(raw_tmpl)
                    if not tmpl_name or tmpl_name.startswith(".") or ".." in tmpl_name:
                        tmpl_name = "tamtaro-aiometadata-with-anime.json"
                    tmpl_dir = (Path(WEB_ROOT) / "templates" / "aiometadata-configs").resolve()
                    tmpl_path = (tmpl_dir / tmpl_name).resolve()
                    if not tmpl_path.is_file() or not tmpl_path.is_relative_to(tmpl_dir):
                        tmpl_path = (tmpl_dir / "tamtaro-aiometadata-with-anime.json").resolve()
                    if not tmpl_path.is_file():
                        repo_dir = (Path(__file__).resolve().parents[2] / "templates" / "aiometadata-configs").resolve()
                        repo_candidate = (repo_dir / tmpl_name).resolve()
                        if not repo_candidate.is_file() or not repo_candidate.is_relative_to(repo_dir):
                            repo_candidate = (repo_dir / "tamtaro-aiometadata-with-anime.json").resolve()
                        if repo_candidate.is_file():
                            tmpl_path = repo_candidate
                    if tmpl_path.is_file():
                        with open(tmpl_path, "r", encoding="utf-8") as f:
                            raw = json.load(f)
                            config_data = raw.get("config", raw)

                if not config_data:
                    raise ValueError("AIOMetadata configuration not ready")

                body = json.dumps(config_data, indent=2).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Disposition", 'attachment; filename="aio-local-aiometadata-profile.json"')
                self.end_headers()
                self.wfile.write(body)
            except Exception:
                self.json_response({"error": "AIOMetadata configuration export failed."}, 503)
            return
        if path == "/api/profile-recommendation":
            try:
                memory_kb = int(next(line.split()[1] for line in open("/proc/meminfo", encoding="ascii") if line.startswith("MemTotal:")))
            except (OSError, StopIteration, ValueError):
                memory_kb = 0
            memory_gb = memory_kb / 1024 / 1024
            profile = "core" if memory_gb and memory_gb < 8 else "all"
            self.json_response({"recommendedProfile": profile, "memoryGb": round(memory_gb, 1), "cpuCount": os.cpu_count() or 1})
            return
        if path == "/api/update-plan":
            self.json_response({"status": "manual-review", "commands": ["docker compose pull", "docker compose build --pull", "docker compose up -d"], "backupFirst": True, "rollback": "Restore the latest backup and redeploy the previous image tags."})
            return
        if path == "/api/proxy-config":
            query = urllib.parse.parse_qs(url_parts.query)
            try:
                config = proxy_config(query.get("format", ["caddy"])[0], query.get("base_url", [""])[0])
            except ValueError as error:
                self.json_response({"error": str(error)}, 400)
                return
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(config.encode())
            except OSError:
                return
            return

        # Route aliases
        if path in ("/", ""):
            self.path = "/index.html"
            return super().do_GET()
        elif path in ("/dashboard", "/admin"):
            self.path = "/dashboard.html"
            return super().do_GET()
        elif path == "/manifest.json":
            # If client requests root manifest on appliance portal, redirect to AIOStreams master manifest
            env_vars = read_saved_env()
            base_url = env_vars.get("BASE_URL") or os.environ.get("BASE_URL")
            if base_url and not any(h in base_url for h in ("localhost:3000", "127.0.0.1:3000", "aiostreams:3000")):
                target = f"{base_url.rstrip('/')}/stremio/u/local/manifest.json"
            else:
                host_hdr = (self.headers.get("X-Forwarded-Host") or self.headers.get("Host", "localhost")).split(",")[0].strip()
                raw_host = host_hdr[:host_hdr.rfind("]") + 1] if (host_hdr.startswith("[") and "]" in host_hdr) else (host_hdr.rsplit(":", 1)[0] if ":" in host_hdr else host_hdr)
                aio_port = env_vars.get("PORT_AIOSTREAMS") or os.environ.get("PORT_AIOSTREAMS", "3001")
                proto = "https" if self.headers.get("X-Forwarded-Proto") == "https" else "http"
                target = f"{proto}://{raw_host}:{aio_port}/stremio/u/local/manifest.json"
            self.send_response(302)
            self.send_header("Location", target)
            self.end_headers()
            return

        # API Endpoints
        if path == "/api/status":
            self.handle_api_status()
            return
        elif path == "/api/manifest-info":
            self.handle_api_manifest_info()
            return
        elif path == "/api/env":
            self.handle_api_status(env_only=True)
            return
        elif path == "/api/logs":
            self.handle_api_logs()
            return
        elif path == "/api/templates":
            self.handle_api_templates()
            return
        elif path == "/api/backup":
            self.handle_api_backup()
            return
        elif path == "/api/resources":
            self.handle_api_resources()
            return
        elif path == "/api/health-stats":
            self.handle_api_health_stats()
            return
        elif path == "/api/watchdog":
            self.handle_api_watchdog()
            return
        elif path == "/api/health-stream":
            self.handle_api_health_stream()
            return
        elif path == "/api/player-preferences":
            self.handle_api_player_preferences_get()
            return
        elif path == "/api/config-bundle-raw":
            self.handle_api_config_bundle_raw()
            return
        elif path in ("/api/zilean", "/api/zilean-stats"):
            self.handle_api_zilean_stats()
            return
        elif path in ("/api/lumiere/stats", "/api/lumiere-stats"):
            self.handle_api_lumiere_stats()
            return
        elif path in ("/api/lumiere/search", "/api/lumiere-search"):
            self.handle_api_lumiere_search()
            return
        elif path == "/api/backups":
            self.handle_api_backups_list()
            return
        elif path == "/api/flaresolverr":
            self.handle_api_flaresolverr()
            return
        elif path == "/api/benchmark":
            self.handle_api_benchmark()
            return
        elif path == "/api/clean-cache":
            self.json_response({"error": "Use POST for cache cleanup."}, 405)
            return
        elif path == "/api/cloudflare/status":
            self.handle_api_cloudflare_status()
            return

        # Static portal assets — never proxy to backend services
        if path.startswith("/assets/") or path.startswith("/templates/") or path in ("/app.webmanifest", "/favicon.ico"):
            return super().do_GET()

        if self.check_proxy_referer_fallback(path, url_parts.query):
            return

        if path.startswith("/api/"):
            self.json_response({"error": "Endpoint not found"}, 404)
            return

        return super().do_GET()

    def do_POST(self):
        url_parts = urllib.parse.urlsplit(self.path)
        path = url_parts.path
        if path.startswith("/service-proxy") or path == "/jellyfin" or path.startswith("/jellyfin/"):
            self.handle_proxy_route(path, url_parts.query)
            return
        if path.startswith("/api/") and path not in PORTAL_API_POST_PATHS:
            if self.check_proxy_referer_fallback(path, url_parts.query):
                return
        if os.environ.get("AIO_STARTUP_ONLY") == "true":
            self.json_response({"error": "Appliance is still starting. Wait for the setup portal before saving settings."}, 503)
            return
        if not self.authorize():
            return
        if not self.request_origin_is_local():
            try:
                cl = int(self.headers.get("Content-Length", 0) or 0)
                if 0 < cl <= 65536:
                    self.rfile.read(cl)
                elif cl > 65536:
                    self.rfile.read(65536)
            except Exception:
                pass
            self.send_error(403, "Cross-origin configuration changes are not allowed")
            return
        if path == "/api/webhook-test":
            try:
                payload = self.read_json_body()
                url = payload.get("url") or read_saved_env().get("DISCORD_WEBHOOK_URL", "")
                if not url:
                    self.json_response({"success": False, "error": "No webhook URL provided"}, 400)
                    return
                success, msg = dispatch_webhook_notification(url, "Simulcast Alert Test", "Your AIO Local Simulcast Airing Alert webhook is active and verified! 🎉")
                self.json_response({"success": success, "message": msg}, 200 if success else 400)
            except ValueError as e:
                self.json_response({"success": False, "error": str(e)}, 400)
            except Exception:
                self.json_response({"success": False, "error": "Internal server error occurred while sending webhook notification."}, 500)
            return
        if path == "/api/setup":
            try:
                if launch_setup():
                    self.json_response({"success": True}, 202)
                else:
                    self.json_response({"success": False, "message": "Setup is already running."}, 409)
            except (OSError, ValueError, RuntimeError):
                self.json_response({"error": "Compose controller is unavailable. Check its container health."}, 503)
            return
        if path == "/api/aiometadata/apply-template":
            try:
                payload = self.read_json_body()
                raw_tmpl = str(payload.get("template") or "tamtaro-aiometadata-with-anime.json").strip()
                if not raw_tmpl or raw_tmpl.startswith(".") or ".." in raw_tmpl or "/" in raw_tmpl or "\\" in raw_tmpl or not re.fullmatch(r"[A-Za-z0-9_.-]+", raw_tmpl):
                    self.json_response({"success": False, "error": "Invalid template filename"}, 400)
                    return
                tmpl = os.path.basename(raw_tmpl)
                tmpl_dir = (pathlib.Path(WEB_ROOT) / "templates" / "aiometadata-configs").resolve()
                tmpl_path = (tmpl_dir / tmpl).resolve()
                if not tmpl_path.is_file() or not tmpl_path.is_relative_to(tmpl_dir):
                    repo_dir = (pathlib.Path(__file__).resolve().parents[2] / "templates" / "aiometadata-configs").resolve()
                    tmpl_path = (repo_dir / tmpl).resolve()
                    if not tmpl_path.is_file() or not tmpl_path.is_relative_to(repo_dir):
                        self.json_response({"success": False, "error": f"Template {tmpl} not found"}, 404)
                        return

                with open(tmpl_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    tmpl_cfg = raw.get("config", raw)

                env_vars = read_saved_env()
                addon_pw = env_vars.get("ADDON_PASSWORD") or os.environ.get("ADDON_PASSWORD") or "admin"
                existing_profile = env_vars.get("AIOMETADATA_PROFILE_UUID") or os.environ.get("AIOMETADATA_PROFILE_UUID")
                aiom_base = os.environ.get("AIOMETADATA_URL", "http://aiometadata:4005").rstrip("/")

                settings = {**os.environ, **env_vars, "ADDON_PASSWORD": addon_pw}
                credentials = {"password": addon_pw, "addonPassword": addon_pw}
                existing_cfg = {}
                if existing_profile:
                    profile_path = urllib.parse.quote(existing_profile, safe="")
                    loaded = request_metadata(f"{aiom_base}/api/config/load/{profile_path}", credentials)
                    existing_cfg = loaded.get("config")
                    if not isinstance(existing_cfg, dict):
                        raise MetadataRequestError(502)
                tmpl_cfg = prepare_metadata_template(tmpl_cfg, settings, existing_cfg)
                save_data = {"config": tmpl_cfg, **credentials}
                if existing_profile and existing_cfg.get("configVersion") is not None:
                    save_data["baseVersion"] = existing_cfg["configVersion"]
                endpoint = f"{aiom_base}/api/config/update/{profile_path}" if existing_profile else f"{aiom_base}/api/config/save"
                aiom_res = request_metadata(endpoint, save_data, "PUT" if existing_profile else "POST")
                user_uuid = aiom_res.get("userUUID") or aiom_res.get("uuid")
                if not isinstance(user_uuid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", user_uuid):
                    raise MetadataRequestError(502)
                if existing_profile and user_uuid != existing_profile:
                    raise MetadataRequestError(502)
                updates = {"AIOMETADATA_TEMPLATE": tmpl}
                if user_uuid:
                    updates["AIOMETADATA_PROFILE_UUID"] = str(user_uuid)
                save_env_updates(updates)

                request_host = self.headers.get("Host", "localhost")
                aiom_host = dashboard_origin(
                    env_vars.get("AIOMETADATA_HOST") or os.environ.get("AIOMETADATA_HOST"),
                    request_host, env_vars.get("PORT_AIOMETADATA") or os.environ.get("PORT_AIOMETADATA"), 4005,
                )
                self.json_response({
                    "success": True,
                    "template": tmpl,
                    "uuid": user_uuid,
                    "configureUrl": f"{aiom_host}/stremio/{user_uuid}/configure" if user_uuid else f"{aiom_host}/configure",
                    "manifestUrl": f"{aiom_host}/stremio/{user_uuid}/manifest.json" if user_uuid else f"{aiom_host}/manifest.json"
                })
            except MetadataRequestError as error:
                status = error.upstream_status
                response_status = status if status in (400, 409, 502, 504) else 422
                self.json_response({"success": False, "error": str(error),
                                    "errorCode": "AIOMETADATA_PRESET_FAILED",
                                    "upstreamStatus": status}, response_status)
            except ValueError:
                self.json_response({"success": False, "error": "Invalid metadata preset or request.",
                                    "errorCode": "AIOMETADATA_PRESET_FAILED"}, 400)
            except Exception:
                self.json_response({"success": False, "error": "Could not apply or persist the metadata preset. Check portal logs.",
                                    "errorCode": "AIOMETADATA_PRESET_FAILED"}, 500)
            return
        if path in ("/api/validate-provider", "/api/test-provider"):
            try:
                payload = self.read_json_body()
                self.json_response(validate_provider(
                    payload.get("provider"),
                    payload.get("key"),
                    payload.get("url"),
                    payload.get("id") or payload.get("indexer_id")
                ))
            except ValueError as e:
                self.json_response({"status": "invalid", "detail": str(e)}, 400)
            except Exception:
                self.json_response({"status": "invalid", "detail": "Internal server error during provider validation."}, 500)
            return
        if path == "/api/smoke-test":
            try:
                payload = self.read_json_body()
                self.json_response(run_smoke_test(payload.get("kind"), payload.get("id")))
            except ValueError as e:
                self.json_response({"status": "invalid", "detail": str(e)}, 400)
            except Exception:
                self.json_response({"status": "invalid", "detail": "Internal server error during smoke test."}, 500)
            return
        if path == "/api/test-playback":
            try:
                payload = self.read_json_body()
                readiness = playback_readiness()
                if not readiness["ready"]:
                    self.json_response({"status": "not_ready", "message": readiness["message"], "readiness": readiness}, 409)
                    return
                self.json_response(run_playback_test(payload.get("mode"), payload.get("content_id"), payload.get("kind")))
            except ValueError as e:
                self.json_response({"status": "invalid", "detail": str(e)}, 400)
            except Exception:
                self.json_response({"status": "invalid", "detail": "Internal server error during playback test."}, 500)
            return
        if path == "/api/config-import":
            try:
                payload = self.read_json_body()
                if payload.get("format") != "aio-local-config-v1" or not isinstance(payload.get("values"), dict):
                    self.json_response({"error": "Use an aio-local-config-v1 export and provide values."}, 400)
                    return
                allowed = {
                    "BASE_URL", "AIOMETADATA_HOST", "AIOMETADATA_TEMPLATE", "COMPOSE_PROFILES",
                    "ENABLE_ANIME_SOURCES", "STREAMING_MODE", "BACKUP_SCHEDULE",
                    "ENABLE_TORRENTIO", "TORRENTIO_URL", "ENABLE_DMM", "ENABLE_REMUXDB",
                    "JELLYFIN_ENABLED",
                    "DISCORD_WEBHOOK_URL",
                    "TMDB_API_KEY", "TVDB_API_KEY", "FANART_API_KEY", "MDBLIST_API_KEY", "GEMINI_API_KEY", "RPDB_API_KEY",
                    "REALDEBRID_API_KEY", "TORBOX_API_KEY", "PREMIUMIZE_API_KEY", "ALLDEBRID_API_KEY", "DEBRIDLINK_API_KEY", "EASYDEBRID_API_KEY", "OFFCLOUD_API_KEY", "SEEDR_API_KEY",
                    "TRAKT_CLIENT_ID", "TRAKT_CLIENT_SECRET", "SIMKL_CLIENT_ID", "SIMKL_CLIENT_SECRET", "ANILIST_CLIENT_ID", "ANILIST_CLIENT_SECRET",
                    "SUBDL_API_KEY", "SUBSOURCE_API_KEY", "WYZIE_API_KEY",
                    "USENET_ENABLED", "USENET_HOST", "USENET_PORT", "USENET_USER", "USENET_CONNECTIONS", "USENET_SSL", "NZB_INDEXER_URL", "NZB_INDEXER_API_KEY"
                }
                supplied = payload["values"]
                unknown = sorted(key for key in supplied if key not in allowed)
                if unknown:
                    self.json_response({"error": f"Unsupported configuration keys: {', '.join(unknown)}"}, 400)
                    return
                if not supplied or any(not isinstance(value, str) or "\n" in value or "\r" in value or "$" in value for value in supplied.values()):
                    self.json_response({"error": "Configuration values must be single-line strings without interpolation."}, 400)
                    return
                if "BASE_URL" in supplied:
                    normalize_base_url(supplied["BASE_URL"])
                if "COMPOSE_PROFILES" in supplied:
                    profiles = {profile.strip().strip("\"'") for profile in supplied["COMPOSE_PROFILES"].split(",") if profile.strip().strip("\"'")}
                    if not profiles or not profiles.issubset({"core", "anime", "tunnel", "all", "scrapers", "anime-db"}):
                        self.json_response({"error": "COMPOSE_PROFILES contains an unsupported profile."}, 400)
                        return
                    normalized = []
                    for p in supplied["COMPOSE_PROFILES"].split(","):
                        p = p.strip().strip("\"'")
                        if not p:
                            continue
                        norm = "core" if p == "scrapers" else ("anime" if p == "anime-db" else p)
                        if norm not in normalized:
                            normalized.append(norm)
                    supplied["COMPOSE_PROFILES"] = ",".join(normalized)
                updates = supplied
                if updates.get('ENABLE_ANIME_SOURCES','false') not in ('true','false'):
                    raise ValueError('Invalid optional-source state')
                save_env_updates(updates)
                self.json_response({"success": True, "updated": sorted(updates)})
            except (json.JSONDecodeError, TypeError, OSError, ValueError):
                self.json_response({"error": "Configuration import failed validation."}, 400)
            return

        if path in ("/api/save-env", "/api/quick-setup", "/api/settings", "/api/env", "/api/save"):
            self.handle_api_save_env()
            return
        elif path == "/api/restart":
            self.handle_api_restart()
            return
        elif path == "/api/clean-cache":
            self.handle_api_clean_cache()
            return
        elif path == "/api/watchdog":
            self.handle_api_watchdog(run_probe=True)
            return
        elif path == "/api/player-preferences":
            self.handle_api_player_preferences_post()
            return
        elif path == "/api/backups/prune":
            self.handle_api_backups_prune()
            return
        elif path == "/api/cloudflare/push-dns":
            self.handle_api_cloudflare_push_dns()
            return
        elif path == "/api/cloudflare/tunnel":
            self.handle_api_cloudflare_tunnel_action()
            return
        elif path == "/api/lumiere/rebuild":
            if not self.authorize():
                return
            try:
                res = subprocess.run(
                    ["docker", "exec", "lumiere-db", "/app/api", "rebuild"],
                    capture_output=True, text=True, timeout=15
                )
                output = (res.stdout or res.stderr or "Rebuild command executed").strip()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": res.returncode == 0, "output": output}).encode("utf-8"))
            except Exception:
                self.json_response({"success": False, "error": "Internal server error occurred while rebuilding Lumiere database."}, 500)
            return

        if self.check_proxy_referer_fallback(path, url_parts.query):
            return

        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": "Endpoint not found"}).encode("utf-8"))

    def do_HEAD(self):
        url_parts = urllib.parse.urlsplit(self.path)
        path = url_parts.path
        if path.startswith("/service-proxy") or path == "/jellyfin" or path.startswith("/jellyfin/"):
            self.handle_proxy_route(path, url_parts.query)
            return
        if self.check_proxy_referer_fallback(path, url_parts.query):
            return
        return super().do_HEAD()

    def do_PUT(self):
        url_parts = urllib.parse.urlsplit(self.path)
        path = url_parts.path
        if path.startswith("/service-proxy") or path == "/jellyfin" or path.startswith("/jellyfin/"):
            self.handle_proxy_route(path, url_parts.query)
            return
        if self.check_proxy_referer_fallback(path, url_parts.query):
            return
        self.send_error(405, "Method Not Allowed")

    def do_DELETE(self):
        url_parts = urllib.parse.urlsplit(self.path)
        path = url_parts.path
        if path.startswith("/service-proxy") or path == "/jellyfin" or path.startswith("/jellyfin/"):
            self.handle_proxy_route(path, url_parts.query)
            return
        if self.check_proxy_referer_fallback(path, url_parts.query):
            return
        self.send_error(405, "Method Not Allowed")

    def do_PATCH(self):
        url_parts = urllib.parse.urlsplit(self.path)
        path = url_parts.path
        if path.startswith("/service-proxy") or path == "/jellyfin" or path.startswith("/jellyfin/"):
            self.handle_proxy_route(path, url_parts.query)
            return
        if self.check_proxy_referer_fallback(path, url_parts.query):
            return
        self.send_error(405, "Method Not Allowed")

    def json_response(self, data, status=200):
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            pass

    def handle_api_status(self, env_only=False):
        try:
            env_vars = {}
            if os.path.isfile(ENV_PATH):
                with open(ENV_PATH, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            env_vars[k.strip()] = v.strip()
            elif os.path.isfile(ENV_EXAMPLE_PATH):
                with open(ENV_EXAMPLE_PATH, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            env_vars[k.strip()] = v.strip()

            now = time.monotonic()
            if not env_only and (now - _STATUS_PROBE_CACHE["timestamp"] < 5.0):
                docker_ready = _STATUS_PROBE_CACHE["docker_ready"]
                aggregator_ready = _STATUS_PROBE_CACHE["aggregator_ready"]
            else:
                docker_ready = False
                try:
                    if not env_only:
                        res = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                        docker_ready = (res.returncode == 0)
                except Exception:
                    docker_ready = False

                aggregator_ready = False
                if not env_only:
                    # Fallback: check if aiostreams aggregator is reachable
                    import urllib.request
                    aio_url = os.environ.get("AIOSTREAMS_URL", "http://aiostreams:3000").rstrip("/")
                    endpoints = [aio_url + "/api/v1/status"]
                    fb = get_service_fallback_url(endpoints[0])
                    if fb and fb not in endpoints:
                        endpoints.append(fb)
                    for endpoint in endpoints:
                        try:
                            with urllib.request.urlopen(endpoint, timeout=1) as resp_check:
                                if resp_check.status in (200, 301, 302):
                                    aggregator_ready = True
                                    break
                        except Exception:
                            pass
                if not env_only:
                    _STATUS_PROBE_CACHE["docker_ready"] = docker_ready
                    _STATUS_PROBE_CACHE["aggregator_ready"] = aggregator_ready
                    _STATUS_PROBE_CACHE["timestamp"] = now

            # Send only saved-key indicators, never stored credential values.
            try:
                base_val = normalize_base_url(env_vars.get("BASE_URL") or os.environ.get("BASE_URL"))
            except Exception:
                base_val = "http://localhost:3001"
            aiom_val = env_vars.get("AIOMETADATA_HOST") or os.environ.get("AIOMETADATA_HOST") or derive_aiometadata_host(base_val)
            mode_val = env_vars.get("STREAMING_MODE")
            if not mode_val:
                has_usenet = bool(env_vars.get("USENET_HOST") and (env_vars.get("USENET_USER") or env_vars.get("USENET_USER_B64")))
                debrid_keys = ("REALDEBRID_API_KEY", "PREMIUMIZE_API_KEY", "TORBOX_API_KEY", "ALLDEBRID_API_KEY", "DEBRIDLINK_API_KEY", "EASYDEBRID_API_KEY")
                has_debrid = any(env_vars.get(k) for k in debrid_keys)
                if has_usenet and not has_debrid:
                    mode_val = "usenet"
                elif has_usenet and has_debrid:
                    mode_val = "hybrid"
                else:
                    mode_val = "debrid"
            cf_token = env_vars.get("CLOUDFLARE_TUNNEL_TOKEN") or ""
            cf_meta = {}
            if cf_token:
                try:
                    from tools.cloudflare_helper import parse_tunnel_token
                    cf_meta = parse_tunnel_token(cf_token)
                except Exception:
                    cf_meta = {}

            resp_env = {
                **public_settings(env_vars),
                "STREAMING_MODE": mode_val,
                "ENABLE_TORRENTIO": env_vars.get("ENABLE_TORRENTIO", "true"),
                "TORRENTIO_URL": env_vars.get("TORRENTIO_URL", ""),
                "ENABLE_DMM": env_vars.get("ENABLE_DMM", "true"),
                "ENABLE_REMUXDB": env_vars.get("ENABLE_REMUXDB", "true"),
                "JELLYFIN_ENABLED": env_vars.get("JELLYFIN_ENABLED", "true"),
                "ENABLE_ANIME_SOURCES": env_vars.get("ENABLE_ANIME_SOURCES", "false"),
                "BASE_URL": base_val,
                "AIOMETADATA_HOST": aiom_val,
                "AIOMETADATA_TEMPLATE": env_vars.get("AIOMETADATA_TEMPLATE", "tamtaro-aiometadata-with-anime.json"),
                "BACKUP_SCHEDULE": env_vars.get("BACKUP_SCHEDULE", "daily"),
                "CLOUDFLARE_TUNNEL_TOKEN_SAVED": bool(cf_token),
                "CLOUDFLARE_TUNNEL_METADATA": cf_meta,
                "configuredKeys": sorted(key for key, value in env_vars.items()
                                         if value and re.search(r"KEY|PASSWORD|TOKEN|SECRET|CLIENT_ID|_ID|MANIFEST_URL", key))
            }

            def safe_port(val, default):
                try:
                    p = int(val)
                    return p if 1 <= p <= 65535 else default
                except (ValueError, TypeError):
                    return default

            ports = {
                "portal": safe_port(env_vars.get("PORT_PORTAL") or os.environ.get("PORT_PORTAL"), 8088),
                "aiostreams": safe_port(env_vars.get("PORT_AIOSTREAMS") or os.environ.get("PORT_AIOSTREAMS"), 3001),
                "aiometadata": safe_port(env_vars.get("PORT_AIOMETADATA") or os.environ.get("PORT_AIOMETADATA"), 4005),
            }
            for port_key in ("PORT_PORTAL", "PORT_AIOSTREAMS", "PORT_AIOMETADATA"):
                val = env_vars.get(port_key) or os.environ.get(port_key)
                if val:
                    resp_env[port_key] = val
            resp_env["ports"] = ports

            resp = {
                "appliance": True,
                "status": "online",
                "docker_ready": docker_ready,
                "aggregator_ready": aggregator_ready,
                "version": APP_VERSION,
                "ports": ports,
                "env": resp_env
            }
            self.json_response(resp_env if env_only else resp)
        except Exception:
            self.json_response({"error": "Internal server error occurred while retrieving status."}, 500)

    def handle_api_manifest_info(self):
        try:
            install_info = {}
            candidates = [
                os.path.join(WEB_ROOT, "data", "aiostreams", "aiostreams_install.json"),
                os.path.join(WEB_ROOT, "data", "aiostreams_install.json"),
                "/data/aiostreams/aiostreams_install.json",
                "/data/aiostreams_install.json"
            ]
            for c in candidates:
                if os.path.isfile(c):
                    try:
                        with open(c, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            enc_cand = data.get("encrypted_password") or data.get("encryptedPassword")
                            if data.get("uuid") and enc_cand:
                                install_info = data
                                break
                            elif not install_info:
                                install_info = data
                    except Exception:
                        pass

            env_vars = {}
            if os.path.isfile(ENV_PATH):
                with open(ENV_PATH, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            env_vars[k.strip()] = v.strip().strip('"').strip("'")

            request_host = self.headers.get("Host", "localhost")
            base_url = dashboard_origin(
                env_vars.get("BASE_URL") or os.environ.get("BASE_URL"),
                request_host, env_vars.get("PORT_AIOSTREAMS") or os.environ.get("PORT_AIOSTREAMS"), 3001,
            )
            raw_uuid = install_info.get("uuid") or env_vars.get("DEFAULT_AIO_UUID")
            raw_enc = install_info.get("encrypted_password") or install_info.get("encryptedPassword") or env_vars.get("DEFAULT_AIO_ENCRYPTED_PASSWORD")

            uuid = str(raw_uuid).strip() if raw_uuid and str(raw_uuid).strip() not in ("null", "None", "") else None
            encrypted_password = str(raw_enc).strip() if raw_enc and str(raw_enc).strip() not in ("null", "None", "") else None

            direct_manifest = f"{base_url}/stremio/{uuid}/{encrypted_password}/manifest.json" if uuid and encrypted_password else None
            alias_manifest = f"{base_url}/stremio/u/local/manifest.json"

            # AIOMetadata public subdomain and manifest
            aiom_profile = env_vars.get("AIOMETADATA_PROFILE_UUID") if "AIOMETADATA_PROFILE_UUID" in env_vars else os.environ.get("AIOMETADATA_PROFILE_UUID")
            configured_meta = env_vars.get("AIOMETADATA_HOST") or os.environ.get("AIOMETADATA_HOST")
            aiom_host = dashboard_origin(
                configured_meta, request_host,
                env_vars.get("PORT_AIOMETADATA") or os.environ.get("PORT_AIOMETADATA"), 4005,
                public_fallback=derive_aiometadata_host(base_url) if base_url.startswith("https://") else None,
            )
            aiom_path = f"/stremio/{urllib.parse.quote(aiom_profile, safe='')}" if aiom_profile else ""
            aiom_manifest = f"{aiom_host}{aiom_path}/manifest.json" if aiom_path else None

            jellyfin_enabled_val = (env_vars.get("JELLYFIN_ENABLED") or os.environ.get("JELLYFIN_ENABLED", "true")).lower() not in ("false", "0", "no")
            jellyfin_server = f"{base_url}/jellyfin/{uuid}/{encrypted_password}" if uuid and encrypted_password else f"{base_url}/jellyfin"
            jellyfin_web_player = f"{base_url}/jellyfin/{uuid}/{encrypted_password}/web/" if uuid and encrypted_password else f"{base_url}/jellyfin/web"
            jellyfin_web_player_proxy = f"/jellyfin/{uuid}/{encrypted_password}/web/" if uuid and encrypted_password else "/jellyfin/web/"
            jellyfin_server_proxy = f"/jellyfin/{uuid}/{encrypted_password}" if uuid and encrypted_password else "/jellyfin"
            resp = {
                "success": True,
                "uuid": uuid,
                "encryptedPassword": encrypted_password,
                "baseUrl": base_url,
                "directManifest": direct_manifest,
                "aliasManifest": alias_manifest,
                "aiostreamsConfigure": f"{base_url}/stremio/u/local/configure" if direct_manifest else f"{base_url}/configure",
                "aiostreamsDashboard": f"{base_url}/admin",
                "watchUrl": "/watch/",
                "jellyfinServer": jellyfin_server,
                "jellyfinWebPlayer": jellyfin_web_player,
                "jellyfinWebPlayerProxy": jellyfin_web_player_proxy,
                "jellyfinServerProxy": jellyfin_server_proxy,
                "jellyfinQuickConnect": f"{base_url}/jellyfin/quickconnect",
                "officialWebPlayer": "https://web.aiostreams.org",
                "jellyfinUser": "admin",
                "remuxDbEnabled": env_vars.get("ENABLE_REMUXDB", "true").lower() not in ("false", "0", "no"),
                "mediaInfoProbeEnabled": True,
                "jellyfinEnabled": jellyfin_enabled_val,
                "aiometadataHost": aiom_host,
                "aiometadataConfigure": f"{aiom_host}{aiom_path}/configure",
                "aiometadataManifest": aiom_manifest,
                "aiometadataProfileUuid": aiom_profile or None,
                "aiometadataTemplate": env_vars.get("AIOMETADATA_TEMPLATE") or os.environ.get("AIOMETADATA_TEMPLATE") or "tamtaro-aiometadata-with-anime.json",
            }
            self.json_response(resp)
        except Exception:
            self.json_response({"error": "Internal server error occurred while retrieving manifest info."}, 500)

    def redact_service_logs(self, output):
        values = {**os.environ, **read_saved_env()}
        private = {value for key, value in values.items() if value and re.search(r'KEY|PASS|TOKEN|SECRET|ENCRYPTED', key)}
        try:
            private.add(credential(values, 'USENET_PASS'))
            for field, secret in EXTRA_SOURCES.items():
                private.update(row.get(secret, '') for row in extra_sources(values, field))
        except ValueError:
            pass
        for value in sorted(filter(None, private), key=len, reverse=True):
            # Very short values can appear inside ordinary log words.
            if len(value) >= 4:
                output = output.replace(value, '[REDACTED]').replace(urllib.parse.quote(value, safe=''), '[REDACTED]')
        output = re.sub(r'(/stremio/)[^/\s]+/[^/\s]+', r'\1[REDACTED]', output)
        return re.sub(r'([?&](?:api[_-]?key|access[_-]?key|token|password)=)[^&\s]+', r'\1[REDACTED]', output, flags=re.I)

    def handle_api_logs(self):
        url_parts = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(url_parts.query)
        container = (query.get("container") or [""])[0].strip()

        safe_containers = {
            "aiostreams", "portal", "controller", "flaresolverr",
            "prowlarr", "zilean", "shared-postgres", "shared-redis",
            "postersplus", "anime-kitsu", "subsense",
            "stremthru", "aiometadata", "lumiere-db", "setup",
            "bitmagnet", "jikan-api"
        }

        if container:
            if container not in safe_containers:
                self.json_response({"error": "Unknown or unsupported container name."}, 400)
                return
            if container == "setup":
                snap = setup_snapshot()
                logs_text = "\n".join(snap.get("logs", [])) or "No setup logs recorded yet."
                self.json_response({
                    "container": "setup",
                    "logs": self.redact_service_logs(logs_text),
                    "status": snap.get("status", "idle"),
                    "step": snap.get("step", "")
                })
                return

            try:
                tail = int((query.get("tail") or ["60"])[0] or 60)
            except (ValueError, TypeError):
                tail = 60
            tail = max(1, min(tail, 500))

            # Resolve this project's Compose service label, including services
            # whose Docker names differ between appliance and packaged installs.
            try:
                own = subprocess.run(["docker", "inspect", "--format",
                                      '{{index .Config.Labels "com.docker.compose.project"}}', os.environ.get("HOSTNAME", "")],
                                     capture_output=True, text=True, timeout=4)
                project = own.stdout.strip()
                if own.returncode == 0 and re.fullmatch(r"[a-z0-9][a-z0-9_-]*", project):
                    found = subprocess.run(["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}",
                                            "--filter", f"label=com.docker.compose.service={container}"],
                                           capture_output=True, text=True, timeout=4)
                    ids = found.stdout.split()
                    if found.returncode == 0 and ids and re.fullmatch(r"[a-f0-9]{12,64}", ids[0]):
                        res = subprocess.run(["docker", "logs", "--tail", str(min(tail, 200)), ids[0]],
                                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                             errors="replace", timeout=4)
                        if res.returncode == 0:
                            self.json_response({"container": container, "logs": self.redact_service_logs(res.stdout[-65536:].strip())})
                            return
            except (OSError, subprocess.TimeoutExpired):
                pass

            # 2. Try log files in /var/log/
            log_path = f"/var/log/{container}.log"
            if not os.path.isfile(log_path):
                log_path = f"/var/log/aio/{container}.log"
            if os.path.isfile(log_path):
                try:
                    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                        self.json_response({"container": container, "logs": self.redact_service_logs("".join(lines[-tail:])[-65536:].strip())})
                        return
                except Exception:
                    pass

            self.json_response({"error": f"No logs are available for {container}. Check that the service has started."}, 404)
            return

        logs = {}
        for name, path in [("dockerd", "/var/log/dockerd.log"), ("portal", "/var/log/portal_server.log")]:
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                        logs[name] = self.redact_service_logs("".join(lines[-100:]))
                except Exception:
                    logs[name] = "Error reading log."
            else:
                logs[name] = "Log file not found."

        self.json_response(logs)

    def handle_api_flaresolverr(self):
        flaresolverr_url = os.environ.get("FLARESOLVERR_URL", "http://flaresolverr:8191").rstrip("/")
        endpoints = [f"{flaresolverr_url}/"]
        fb = get_service_fallback_url(endpoints[0])
        if fb and fb not in endpoints:
            endpoints.append(fb)
        resp_bytes = None
        for ep in endpoints:
            try:
                req = urllib.request.Request(ep, headers={"User-Agent": "AIO-Local-Stack/1.0"})
                with urllib.request.urlopen(req, timeout=3) as resp:
                    resp_bytes = resp.read()
                    break
            except Exception:
                pass
        if resp_bytes is not None:
            version = "v3.3+"
            try:
                data = json.loads(resp_bytes.decode("utf-8", errors="ignore"))
                version = data.get("version") or data.get("msg") or "v3.3+"
            except Exception:
                pass
            self.json_response({
                "status": "online",
                "reachable": True,
                "version": version,
                "url": flaresolverr_url,
                "message": f"Antibot Proxy ({version}) is active and ready to bypass Cloudflare challenges for scrapers."
            })
            return
        self.json_response({
            "status": "offline",
            "reachable": False,
            "url": flaresolverr_url,
            "message": f"Antibot proxy is not responding at {flaresolverr_url}."
        }, 503)

    def handle_api_benchmark(self):
        results = {}
        targets = [
            ("aiostreams", os.environ.get("AIOSTREAMS_URL", "http://aiostreams:3000").rstrip("/") + "/manifest.json"),
            ("aiometadata", os.environ.get("AIOMETADATA_URL", "http://aiometadata:4005").rstrip("/") + "/manifest.json"),
            ("flaresolverr", os.environ.get("FLARESOLVERR_URL", "http://flaresolverr:8191").rstrip("/") + "/"),
            ("zilean", os.environ.get("ZILEAN_URL", "http://zilean:8181").rstrip("/") + "/dmm/filtered?query=Inception"),
            ("prowlarr", os.environ.get("PROWLARR_URL", "http://prowlarr:9696").rstrip("/") + "/ping")
        ]
        for name, url in targets:
            t0 = time.monotonic()
            candidate_urls = [url]
            fb = get_service_fallback_url(url)
            if fb and fb not in candidate_urls:
                candidate_urls.append(fb)
            success = False
            last_err = None
            for candidate in candidate_urls:
                try:
                    req = urllib.request.Request(candidate, headers={"User-Agent": "AIO-Benchmark/1.0"})
                    with urllib.request.urlopen(req, timeout=2) as resp:
                        resp.read(256)
                        ms = round((time.monotonic() - t0) * 1000, 1)
                        results[name] = {"status": "ok", "latency_ms": ms}
                        success = True
                        break
                except Exception as e:
                    last_err = e
            if not success:
                results[name] = {"status": "unreachable", "error": type(last_err).__name__ if last_err else "Error"}

        env = read_saved_env()
        debrid_results = {}
        for prov in ("realdebrid", "torbox", "premiumize"):
            env_key = PROVIDER_VALIDATORS[prov][0]
            if env.get(env_key):
                t0 = time.monotonic()
                try:
                    res = validate_provider(prov, env[env_key])
                    ms = round((time.monotonic() - t0) * 1000, 1)
                    debrid_results[prov] = {"status": res.get("status"), "latency_ms": ms}
                except Exception as e:
                    debrid_results[prov] = {"status": "error", "error": str(e)}

        self.json_response({
            "success": True,
            "internal_latencies": results,
            "debrid_latencies": debrid_results,
            "checked_at": time.strftime("%Y-%m-%d %H:%M:%S")
        })

    def handle_api_save_env(self):
        try:
            data = self.read_json_body()
            if {"AIO_PASSWORD_PREVIOUS", "AIO_PORTAL_MANAGED_PASSWORD"} & data.keys():
                raise ValueError("Password migration settings are managed by the stack")
            if "ADDON_PASSWORD" in data:
                password = data["ADDON_PASSWORD"]
                if not isinstance(password, str) or not re.fullmatch(r"[A-Za-z0-9_.!@%+~=-]{8,64}", password):
                    raise ValueError("Use 8–64 characters: letters, numbers, or _ . ! @ % + ~ = -")
            data = form_updates(data, read_saved_env())
            for key, value in data.items():
                if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
                    raise ValueError("Invalid environment variable name")
                if value is not None and (not isinstance(value, (str, int, float, bool))
                        or any(c in str(value) for c in "\r\n\x00$'\"")):
                    raise ValueError("Values must be single-line scalars without quotes or dollar interpolation")

            keys_to_update = {str(k): str(v).strip() for k, v in data.items() if v is not None}
            if keys_to_update.get('STREAMING_MODE') and keys_to_update['STREAMING_MODE'] not in ('debrid', 'usenet', 'hybrid'):
                raise ValueError('Invalid streaming mode; must be debrid, usenet, or hybrid')
            if keys_to_update.get('ENABLE_ANIME_SOURCES','false') not in ('true','false'):
                raise ValueError('Anime sources must be enabled or disabled')
            if "COMPOSE_PROFILES" in keys_to_update:
                profiles = {profile.strip().strip("\"'") for profile in keys_to_update["COMPOSE_PROFILES"].split(",") if profile.strip().strip("\"'")}
                if not profiles or not profiles.issubset({"core", "anime", "tunnel", "all", "scrapers", "anime-db"}):
                    raise ValueError("COMPOSE_PROFILES contains an unsupported profile.")
                normalized = []
                for p in keys_to_update["COMPOSE_PROFILES"].split(","):
                    p = p.strip().strip("\"'")
                    if not p:
                        continue
                    norm = "core" if p == "scrapers" else ("anime" if p == "anime-db" else p)
                    if norm not in normalized:
                        normalized.append(norm)
                keys_to_update["COMPOSE_PROFILES"] = ",".join(normalized)
            for bkey in ('ENABLE_TORRENTIO', 'ENABLE_DMM', 'ENABLE_REMUXDB', 'JELLYFIN_ENABLED'):
                if bkey in keys_to_update and keys_to_update[bkey].lower() not in ('true', 'false', '1', '0'):
                    raise ValueError(f'{bkey} must be true or false')
            port_keys = ('PORT_PORTAL', 'PORT_AIOSTREAMS', 'PORT_AIOMETADATA', 'PORT_SUBSENSE', 'USENET_PORT')
            for pkey in port_keys:
                if pkey in keys_to_update and keys_to_update[pkey]:
                    try:
                        pval = int(keys_to_update[pkey])
                        if not (1 <= pval <= 65535):
                            raise ValueError(f'{pkey} must be a valid port number between 1 and 65535')
                    except (ValueError, TypeError):
                        raise ValueError(f'{pkey} must be a valid port number between 1 and 65535')
            if keys_to_update.get('TORRENTIO_URL'):
                t_url = urllib.parse.urlsplit(keys_to_update['TORRENTIO_URL'])
                if t_url.scheme not in ('http', 'https') or not t_url.hostname or t_url.username or t_url.password:
                    raise ValueError('Enter a valid HTTP(S) URL for Torrentio endpoint')
            if keys_to_update.get('AIOMETADATA_TEMPLATE'):
                tmpl = keys_to_update['AIOMETADATA_TEMPLATE']
                if not tmpl or tmpl.startswith(".") or ".." in tmpl or not re.fullmatch(r"[A-Za-z0-9_.-]+", tmpl):
                    raise ValueError('Invalid AIOMetadata template name')
            if "BASE_URL" in keys_to_update:
                keys_to_update["BASE_URL"] = normalize_base_url(keys_to_update["BASE_URL"])
                existing = {}
                source = ENV_PATH if os.path.isfile(ENV_PATH) else ENV_EXAMPLE_PATH
                if os.path.isfile(source):
                    with open(source, encoding="utf-8") as settings:
                        for line in settings:
                            key, separator, value = line.strip().partition("=")
                            if separator and not key.startswith("#"):
                                existing[key] = value
                old_urls = {}
                try:
                    old_urls = public_service_urls(normalize_base_url(existing.get("BASE_URL")))
                except (ValueError, TypeError):
                    old_urls = {}
                for key, url in public_service_urls(keys_to_update["BASE_URL"]).items():
                    current = existing.get(key, "")
                    current_host = urllib.parse.urlsplit(current).hostname
                    if key not in keys_to_update and (not current or current == old_urls.get(key) or current_host in ("localhost", "127.0.0.1")):
                        keys_to_update[key] = url

            save_env_updates(keys_to_update)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": True, 
                "applied": False,
                "message": "Configuration saved. Choose Connect my stack to apply it."
            }).encode("utf-8"))
        except (ValueError, UnicodeError) as e:
            self.json_response({"success": False, "error": str(e)}, 400)
        except Exception:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": False, "error": "Internal server error occurred while saving configuration."}).encode("utf-8"))

    def handle_api_restart(self):
        try:
            if os.environ.get("COMPOSE_CONTROL_SOCKET"):
                status, resp = control_request("POST", "/apply")
                self.send_response(200 if status in (200, 202, 409) else 503)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(resp).encode("utf-8"))
                return
            subprocess.Popen(["docker", "compose", "restart"], cwd=WEB_ROOT)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "message": "Stack restart initiated."}).encode("utf-8"))
        except Exception:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": False, "error": "Internal server error occurred while restarting stack."}).encode("utf-8"))

    def handle_api_templates(self):
        try:
            templates_dir = os.path.join(WEB_ROOT, "templates")
            result = []
            if os.path.isdir(templates_dir):
                for root, dirs, files in os.walk(templates_dir):
                    dirs[:] = [d for d in dirs if not d.startswith(".")]
                    for file in files:
                        if file.endswith(".json") and not file.startswith("."):
                            rel_path = os.path.relpath(os.path.join(root, file), WEB_ROOT).replace("\\", "/")
                            result.append({"name": file, "path": rel_path})

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"templates": result}).encode("utf-8"))
        except Exception:
            self.json_response({"templates": []})

    def handle_api_backup(self):
        try:
            backup_dir = Path(WEB_ROOT) / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            sys.path.insert(0, str(WEB_ROOT))
            import tools.backup as stack_backup
            archive = stack_backup.create_backup(backup_dir, Path(WEB_ROOT), keep_last=5)
            if not archive.resolve().is_relative_to(backup_dir.resolve()):
                raise ValueError("Unsafe backup path")

            size = archive.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", "application/gzip")
            self.send_header("Content-Disposition", f'attachment; filename="{archive.name}"')
            self.send_header("Content-Length", str(size))
            self.end_headers()
            with open(archive, "rb") as f:
                shutil.copyfileobj(f, self.wfile)
        except Exception:
            self.json_response({"error": "Backup creation failed"}, 500)

    def handle_api_health_stats(self):
        try:
            sys.path.insert(0, str(WEB_ROOT))
            import tools.resources as stack_res
            import tools.backup as stack_backup
            import tools.watchdog as stack_watchdog

            res_stats = stack_res.get_stack_resources(filter_aio=True)
            bk_stats = stack_backup.get_backup_telemetry(Path(WEB_ROOT) / "backups", Path(WEB_ROOT))
            wd_telemetry = stack_watchdog.get_watchdog_telemetry()

            # Ensure we have active probe results for the dashboard
            if not wd_telemetry.get("last_probe"):
                wd_summary = stack_watchdog.probe_all_services(auto_restart=False)
                wd_telemetry = stack_watchdog.get_watchdog_telemetry()
                services_probed = wd_summary.get("services", [])
            else:
                services_probed = []

            zilean_stats = wd_telemetry.get("zilean_stats") or stack_watchdog.get_zilean_stats()
            indexer_health = wd_telemetry.get("indexer_health") or stack_watchdog.check_prowlarr_indexers()
            payload = {
                "success": True,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "resources": res_stats,
                "backup": bk_stats,
                "watchdog": wd_telemetry,
                "zilean": zilean_stats,
                "indexer_health": indexer_health,
                "services": services_probed
            }
            self.json_response(payload)
        except Exception:
            self.json_response({"success": False, "error": "Internal server error occurred while retrieving health statistics."}, 500)

    def handle_api_watchdog(self, run_probe=False):
        try:
            sys.path.insert(0, str(WEB_ROOT))
            import tools.watchdog as stack_watchdog
            if run_probe:
                summary = stack_watchdog.probe_all_services(auto_restart=False)
                self.json_response(summary)
            else:
                telemetry = stack_watchdog.get_watchdog_telemetry()
                self.json_response(telemetry)
        except Exception:
            self.json_response({"success": False, "error": "Internal server error occurred while querying watchdog."}, 500)

    def handle_api_health_stream(self):
        """Server-Sent Events endpoint streaming live health telemetry and per-service latencies."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        for _ in range(30):
            try:
                data = get_cached_watchdog_telemetry(max_age=3.0)
                payload = f"data: {json.dumps(data)}\n\n".encode("utf-8")
                self.wfile.write(payload)
                self.wfile.flush()
                time.sleep(3.0)
                self.wfile.write(b": keep-alive\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                break
            except Exception:
                break

    def handle_api_player_preferences_get(self):
        self.json_response(get_player_preferences())

    def handle_api_player_preferences_post(self):
        try:
            body = self.read_json_body()
            if not isinstance(body, dict):
                self.json_response({"error": "Invalid JSON body"}, 400)
                return
            saved = save_player_preferences(body)
            self.json_response({"success": True, "preferences": saved})
        except ValueError as e:
            self.json_response({"error": str(e)}, 400)
        except Exception:
            self.json_response({"error": "Internal server error occurred while saving preferences."}, 500)

    def handle_api_config_bundle_raw(self):
        if not self.authorize():
            return
        env_vars = read_saved_env()
        prefs = get_player_preferences()
        self.json_response({
            "env": env_vars,
            "player_preferences": prefs,
            "version": "aio-bundle-v2",
            "exported_at": datetime.now(timezone.utc).isoformat()
        })

    def handle_api_zilean_stats(self):
        try:
            sys.path.insert(0, str(WEB_ROOT))
            import tools.watchdog as stack_watchdog
            stats = stack_watchdog.get_zilean_stats()
            self.json_response({"success": True, "stats": stats})
        except Exception:
            self.json_response({"success": False, "error": "Internal server error occurred while retrieving Zilean statistics."}, 500)

    def handle_api_lumiere_stats(self):
        try:
            endpoints = ["http://lumiere-db:8000/etl/status", "http://127.0.0.1:8000/etl/status"]
            data = None
            for ep in endpoints:
                try:
                    req = urllib.request.Request(ep, headers={"User-Agent": "AIO-Portal"})
                    with urllib.request.urlopen(req, timeout=2) as resp:
                        if resp.status == 200:
                            data = json.loads(resp.read().decode("utf-8"))
                            break
                except Exception:
                    continue

            manifest_info = {}
            lumiere_dir = Path(WEB_ROOT) / "data" / "lumiere-db"
            if lumiere_dir.is_dir():
                manifest_files = list(lumiere_dir.glob("search/*/manifest.json"))
                if manifest_files:
                    manifest_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                    try:
                        manifest_info = json.loads(manifest_files[0].read_text(encoding="utf-8"))
                    except Exception:
                        pass

            if not data and not manifest_info:
                self.json_response({"success": False, "error": "LumiereDB is unreachable or not initialized yet."}, 503)
                return

            result = {
                "success": True,
                "online": bool(data),
                "phase": data.get("phase", "idle") if data else "offline",
                "ready": data.get("index", {}).get("ready", False) if data else bool(manifest_info),
                "generationId": data.get("index", {}).get("generationId", "") if data else manifest_info.get("indexVersion", ""),
                "datasetDate": manifest_info.get("datasetDate", ""),
                "docs": manifest_info.get("docs", 0),
                "episodes": manifest_info.get("episodes", 0),
                "people": manifest_info.get("people", 0),
                "names": manifest_info.get("names", 0),
                "builtAt": manifest_info.get("builtAt", ""),
                "lastPollAt": data.get("lastPollAt") if data else None,
                "nextPollAt": data.get("nextPollAt") if data else None,
            }
            self.json_response(result)
        except Exception:
            self.json_response({"success": False, "error": "Internal server error occurred while retrieving Lumiere statistics."}, 500)

    def handle_api_lumiere_search(self):
        try:
            url_parts = urllib.parse.urlsplit(self.path)
            query_params = urllib.parse.parse_qs(url_parts.query)
            q = (query_params.get("q") or query_params.get("query") or [""])[0].strip()
            if not q:
                self.json_response({"success": True, "query": "", "latencyMs": 0, "count": 0, "items": []})
                return

            try:
                limit = min(max(int((query_params.get("limit") or ["10"])[0] or 10), 1), 50)
            except (ValueError, TypeError):
                limit = 10
            encoded_query = urllib.parse.quote(q)
            endpoints = [
                f"http://lumiere-db:8000/search?query={encoded_query}&limit={limit}",
                f"http://127.0.0.1:8000/search?query={encoded_query}&limit={limit}"
            ]
            data = None
            t0 = time.perf_counter()
            for ep in endpoints:
                try:
                    req = urllib.request.Request(ep, headers={"User-Agent": "AIO-Portal"})
                    with urllib.request.urlopen(req, timeout=3) as resp:
                        if resp.status == 200:
                            data = json.loads(resp.read().decode("utf-8"))
                            break
                except Exception:
                    continue
            t1 = time.perf_counter()
            latency_ms = round((t1 - t0) * 1000, 1)

            if data is None:
                self.json_response({"success": False, "error": "LumiereDB is unreachable or not responding."}, 503)
                return

            raw_items = data.get("items", []) if isinstance(data, dict) else []
            items = []
            for item in raw_items:
                if isinstance(item, dict) and item.get("tconst"):
                    items.append({
                        "imdbId": item.get("tconst"),
                        "title": item.get("primaryTitle") or item.get("originalTitle") or "Untitled",
                        "year": item.get("startYear"),
                        "type": item.get("titleType") or "movie",
                        "popularity": item.get("popularity", 0),
                    })

            self.json_response({
                "success": True,
                "query": q,
                "latencyMs": latency_ms,
                "count": len(items),
                "items": items
            })
        except Exception:
            self.json_response({"success": False, "error": "Internal server error occurred while searching Lumiere database."}, 500)

    def handle_api_backups_list(self):
        try:
            sys.path.insert(0, str(WEB_ROOT))
            import tools.backup as stack_backup
            telemetry = stack_backup.get_backup_telemetry(Path(WEB_ROOT) / "backups", Path(WEB_ROOT))
            self.json_response(telemetry)
        except Exception:
            self.json_response({"success": False, "error": "Internal server error occurred while retrieving backups list."}, 500)

    def handle_api_backups_prune(self):
        try:
            payload = self.read_json_body()
            try:
                keep_last = int(payload.get("keep_last", 5))
                if keep_last < 1:
                    keep_last = 1
                elif keep_last > 100:
                    keep_last = 100
            except (ValueError, TypeError):
                self.json_response({"success": False, "error": "keep_last must be a positive integer."}, 400)
                return
            sys.path.insert(0, str(WEB_ROOT))
            import tools.backup as stack_backup
            res = stack_backup.prune_backups(Path(WEB_ROOT) / "backups", keep_last=keep_last, root=Path(WEB_ROOT))
            self.json_response(res)
        except ValueError as e:
            self.json_response({"success": False, "error": str(e)}, 400)
        except Exception:
            self.json_response({"success": False, "error": "Internal server error occurred while pruning backups."}, 500)

    def handle_api_resources(self):
        try:
            sys.path.insert(0, str(WEB_ROOT))
            import tools.resources as stack_res
            stats = stack_res.get_stack_resources(filter_aio=True)
            self.json_response(stats)
        except Exception:
            self.json_response({"success": False, "error": "Internal server error occurred while retrieving resources."}, 500)

    def handle_api_clean_cache(self):
        try:
            sys.path.insert(0, str(WEB_ROOT))
            import tools.clean_cache as stack_cleaner
            res = stack_cleaner.clean_stack_cache(Path(WEB_ROOT))
            self.json_response(res)
        except Exception:
            self.json_response({"success": False, "error": "Internal server error occurred while cleaning cache."}, 500)

    def handle_api_cloudflare_status(self):
        try:
            sys.path.insert(0, str(WEB_ROOT))
            from tools.cloudflare_helper import check_cloudflare_containers, parse_tunnel_token
            containers = check_cloudflare_containers()
            env_vars = read_saved_env()
            token = env_vars.get("CLOUDFLARE_TUNNEL_TOKEN") or os.environ.get("CLOUDFLARE_TUNNEL_TOKEN") or ""
            meta = parse_tunnel_token(token) if token else {"valid": False}
            base_url = env_vars.get("BASE_URL") or os.environ.get("BASE_URL") or ""
            parsed_host = ""
            if base_url:
                try:
                    parsed_host = urllib.parse.urlsplit(base_url).netloc.split(":")[0]
                except Exception:
                    pass

            self.json_response({
                "success": True,
                "available": containers.get("available", False),
                "local_tunnel": containers.get("local_tunnel"),
                "external_connectors": containers.get("external_connectors", []),
                "has_external": containers.get("has_external", False),
                "token_configured": bool(token),
                "tunnel_metadata": meta,
                "current_host": parsed_host
            })
        except Exception:
            self.json_response({"success": False, "error": "Internal server error occurred while checking Cloudflare status."}, 500)

    def handle_api_cloudflare_push_dns(self):
        if not self.authorize():
            return
        try:
            sys.path.insert(0, str(WEB_ROOT))
            from tools.cloudflare_helper import push_cloudflare_dns, parse_tunnel_token
            payload = self.read_json_body()
            api_token = (payload.get("api_token") or "").strip()
            if not api_token:
                self.json_response({"success": False, "error": "Cloudflare API Token is required. Generate one in Cloudflare Dashboard -> My Profile -> API Tokens."}, 400)
                return

            env_vars = read_saved_env()

            # Resolve hostname
            hostname = (payload.get("hostname") or "").strip()
            if not hostname:
                base_url = env_vars.get("BASE_URL") or os.environ.get("BASE_URL") or ""
                if base_url:
                    hostname = urllib.parse.urlsplit(base_url).netloc.split(":")[0]
            if not hostname:
                self.json_response({"success": False, "error": "Enter a hostname or set your external Base URL first."}, 400)
                return

            # Resolve target and metadata
            tunnel_token = (payload.get("tunnel_token") or "").strip() or env_vars.get("CLOUDFLARE_TUNNEL_TOKEN") or os.environ.get("CLOUDFLARE_TUNNEL_TOKEN") or ""
            meta = parse_tunnel_token(tunnel_token) if tunnel_token else {"valid": False}
            cname_target = (payload.get("cname_target") or "").strip() or (meta.get("cname_target") if meta.get("valid") else "")
            account_id = payload.get("account_id") or meta.get("account_id")
            tunnel_id = payload.get("tunnel_id") or meta.get("tunnel_id")
            zone_id = (payload.get("zone_id") or "").strip() or None

            if not cname_target:
                self.json_response({"success": False, "error": "CNAME target could not be resolved. Provide a Cloudflare Tunnel Token or CNAME target."}, 400)
                return

            res = push_cloudflare_dns(
                api_token=api_token,
                hostname=hostname,
                cname_target=cname_target,
                account_id=account_id,
                tunnel_id=tunnel_id,
                zone_id=zone_id
            )
            self.json_response(res, 200 if res.get("success") else 400)
        except ValueError as e:
            self.json_response({"success": False, "error": str(e)}, 400)
        except Exception:
            self.json_response({"success": False, "error": "Internal server error occurred while pushing Cloudflare DNS."}, 500)

    def handle_api_cloudflare_tunnel_action(self):
        if not self.authorize():
            return
        try:
            sys.path.insert(0, str(WEB_ROOT))
            from tools.cloudflare_helper import manage_local_tunnel
            payload = self.read_json_body()
            action = payload.get("action", "status")
            res = manage_local_tunnel(action, cwd=WEB_ROOT)
            self.json_response(res, 200 if res.get("success") else 400)
        except ValueError as e:
            self.json_response({"success": False, "error": str(e)}, 400)
        except Exception:
            self.json_response({"success": False, "error": "Internal server error occurred while managing Cloudflare tunnel."}, 500)

class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

def run():
    server_address = ("0.0.0.0", PORT)
    httpd = ThreadingHTTPServer(server_address, AppliancePortalHandler)
    print(f"[PORTAL] Serving AIOStreams Appliance Portal on 0.0.0.0:{PORT} from {WEB_ROOT}...", flush=True)

    def shutdown_handler(signum, frame):
        print(f"[PORTAL] Caught signal {signum}, initiating graceful shutdown...", flush=True)
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    try:
        import signal
        signal.signal(signal.SIGTERM, shutdown_handler)
        signal.signal(signal.SIGINT, shutdown_handler)
    except Exception:
        pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()

if __name__ == "__main__":
    run()
