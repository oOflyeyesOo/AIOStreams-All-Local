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
import platform
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
APP_VERSION = os.environ.get("APP_VERSION", "1.2.0")
if WEB_ROOT not in sys.path:
    sys.path.insert(0, WEB_ROOT)
from init.service_inventory import APPLICATION_SERVICE_COUNT, INTEGRATIONS
from tools.usenet_config import EXTRA_SOURCES, extra_sources, form_updates, public_settings, credential
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
        try:
            process = subprocess.Popen(
                [sys.executable, "-u", os.path.join(WEB_ROOT, "init/bootstrap/setup_stack.py")],
                cwd=WEB_ROOT, env=dict(os.environ), stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True)
            for line in process.stdout:
                with SETUP_LOCK:
                    SETUP_JOB["logs"].append(line.rstrip())
                    for marker, step in (("Prowlarr", "Connecting public indexers"), 
                                         ("AIOMetadata Setup", "Preparing metadata"), ("AIOStreams Setup", "Building your manifest"),
                                         ("Test ", "Checking the result")):
                        if marker in line:
                            SETUP_JOB["step"] = step
            code = process.wait()
            with SETUP_LOCK:
                SETUP_JOB.update(status="complete" if code == 0 else "failed", exit_code=code,
                                 step="Your manifest is ready" if code == 0 else "Setup needs attention")
        except Exception:
            with SETUP_LOCK:
                SETUP_JOB.update(status="failed", step="Could not start setup", exit_code=-1)
    threading.Thread(target=worker, daemon=True).start()
    return True


HOST_PORT_MAP = {
    "aiostreams": 3001, "aiometadata": 4005, "comet": 8000, "zilean": 8181,
    "prowlarr": 9696, "flaresolverr": 8191, "anime-kitsu": 7005, "postersplus": 9039,
    "subsense": 3100, "infinidysk": 3005, "stremthru": 8080, "slicksync": 8086
}
SERVICE_UI_PATHS = {
    "aiostreams": "/stremio/configure", "aiometadata": "/configure",
    "comet": "/configure", "prowlarr": "/", "infinidysk": "/",
    "subsense": "/configure", "postersplus": "/admin", "stremthru": "/",
    "anime-kitsu": "/", "slicksync": "/",
}

INTERNAL_SERVICE_TARGETS = {
    "aiostreams": ("aiostreams", 3000, 3001),
    "aiometadata": ("aiometadata", 4005, 4005),
    "prowlarr": ("prowlarr", 9696, 9696),
    "zilean": ("zilean", 8181, 8181),
    "comet": ("comet", 8000, 8000),
    "slicksync": ("slicksync", 3000, 8086),
    "stremio-web": ("stremio-web", 8080, 8082),
    "nuvio": ("nuvio-web", 3000, 8085),
    "flaresolverr": ("flaresolverr", 8191, 8191),
    "postersplus": ("postersplus", 8000, 9039),
    "subsense": ("stremio-subsense", 3100, 3100),
    "stremthru": ("stremthru", 8080, 8080),
    "anime-kitsu": ("anime-kitsu", 7000, 7005),
    "infinidysk": ("infinidysk", 3000, 3005),
}

class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

_PROXY_OPENER = urllib.request.build_opener(NoRedirectHandler)

def probe_integration(item):
    import socket
    name, host, port, group = item
    env_vars = read_saved_env()
    profiles = {p.strip() for p in env_vars.get("COMPOSE_PROFILES", "scrapers").split(",") if p.strip()}
    service_profiles = {
        "comet": {"core", "scrapers", "all"},
        "aiometadata": {"core", "scrapers", "all"},
        "postersplus": {"core", "scrapers", "all"},
        "subsense": {"core", "scrapers", "all"},
    }
    enabled = host == "aiostreams" or bool(profiles & service_profiles.get(host, {"scrapers", "all"}))
    if host == "infinidysk" and env_vars.get("USENET_ENABLED", "false") != "true" and env_vars.get("STREAMING_MODE", "debrid") == "debrid":
        enabled = False

    reachable = False
    if enabled:
        try:
            with socket.create_connection((host, port), timeout=1.5):
                reachable = True
        except OSError:
            custom_port_var = f"PORT_{host.upper().replace('-', '_')}"
            host_port = int(env_vars.get(custom_port_var) or os.environ.get(custom_port_var) or HOST_PORT_MAP.get(host, 0))
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


def validate_provider(provider, key=None):
    provider = str(provider or "").lower().strip()
    if provider == "usenet":
        env_vars = read_saved_env()
        host = env_vars.get("USENET_HOST", "")
        port = int(env_vars.get("USENET_PORT", 563) or 563)
        user = credential(env_vars, "USENET_USER")
        password = credential(env_vars, "USENET_PASS")
        use_ssl = env_vars.get("USENET_SSL", "true").lower() != "false"
        if not host or not user or not password:
            return {"status": "invalid", "detail": "Usenet host, user, or password is not configured."}
        ok, msg = test_nntp_login(host, port, user, password, use_ssl)
        return {"status": "valid" if ok else "rejected", "detail": f"Usenet NNTP server ({host}:{port}): {msg}"}

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
    try:
        raw_sock = socket.create_connection((host, int(port)), timeout=timeout)
        if use_ssl:
            ctx = ssl.create_default_context()
            sock = ctx.wrap_socket(raw_sock, server_hostname=host)
        else:
            sock = raw_sock
        f = sock.makefile("rwb")
        welcome = f.readline().decode("utf-8", errors="ignore")
        if not welcome.startswith(("200", "201")):
            sock.close()
            return False, f"Server banner error: {welcome.strip()}"
        f.write(f"AUTHINFO USER {user}\r\n".encode("utf-8"))
        f.flush()
        user_resp = f.readline().decode("utf-8", errors="ignore")
        if user_resp.startswith("381"):
            f.write(f"AUTHINFO PASS {password}\r\n".encode("utf-8"))
            f.flush()
            pass_resp = f.readline().decode("utf-8", errors="ignore")
            sock.close()
            if pass_resp.startswith("281"):
                return True, "Authentication accepted"
            return False, f"Authentication rejected: {pass_resp.strip()}"
        elif user_resp.startswith("281"):
            sock.close()
            return True, "Authentication accepted"
        sock.close()
        return False, f"Unexpected server response: {user_resp.strip()}"
    except Exception as e:
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
        if not item.get("enabled", True):
            status = "off"
        elif item["reachable"]:
            status = "ready"
        else:
            status = "optional" if item["name"] == "SubSense" else "waiting"
        checks.append({"name": item["name"], "status": status})
    # Port acceptance alone does not mean the selected application path is usable.
    env = read_saved_env()
    aio_url = os.environ.get("AIOSTREAMS_URL", "http://aiostreams:3000").rstrip("/")
    targets = [("Configured streaming manifest", aio_url + "/stremio/u/local/manifest.json", True)]
    profiles = set(env.get("COMPOSE_PROFILES", "scrapers").split(","))
    if profiles & {"core", "scrapers", "all"}:
        targets += [("Search broker", "http://search-broker:8091/healthz", False),
                    ("Comet manifest", "http://comet:8000/manifest.json", True)]
    if env.get("STREAMING_MODE") in ("usenet", "hybrid") or env.get("USENET_ENABLED") == "true":
        targets.append(("Usenet backend", "http://infinidysk:3000/healthz", False))
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

    sample_id = content_id.strip() if content_id and isinstance(content_id, str) and content_id.strip() else "tt1375666"
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
        port = int(env_vars.get("USENET_PORT", 563) or 563)
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
                debrid_results.append((prov, res["status"] == "valid", res["detail"]))

        host = env_vars.get("USENET_HOST", "")
        user = credential(env_vars, "USENET_USER")
        password = credential(env_vars, "USENET_PASS")
        port = int(env_vars.get("USENET_PORT", 563) or 563)
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
        if install_info and install_info.get("uuid"):
            pw = install_info.get("encrypted_password") or install_info.get("encryptedPassword") or ""
            target = f"{aio_url}/stremio/{install_info['uuid']}/{pw}/stream/{sample_kind}/{sample_id}.json"
            try:
                req = urllib.request.Request(target, headers={"User-Agent": "AIO-Playback-Test/1.0"})
                with urllib.request.urlopen(req, timeout=25) as resp:
                    data = json.load(resp)
                    streams = data.get("streams", [])
            except Exception:
                pass

        if not streams:
            try:
                req = urllib.request.Request(f"{aio_url}/stremio/u/local/stream/{sample_kind}/{sample_id}.json", headers={"User-Agent": "AIO-Playback-Test/1.0"})
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
                troubleshoot = "Check your Prowlarr NZB indexer configuration and reachability."
            else:
                stream_step.update(status="fail", detail="Scrapers returned no stream results for sample title.")
                troubleshoot = "Ensure Comet or Torrentio is enabled and scrapers can reach public trackers."
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


def probe_comet_scraper_pipeline(sample_id="tt1375666", kind="movie"):
    """
    Executes a timed Comet scrape request and isolated probes to Comet's dependencies:
    Prowlarr, Zilean, and Debrid (e.g. Premiumize).
    Performs delay attribution to determine if Prowlarr, Zilean, or Premiumize/Debrid
    is bottlenecking or failing Comet's scraper pipeline.
    """
    env = read_saved_env()
    sample_id = (sample_id or "tt1375666").strip()
    kind = (kind or "movie").strip().lower()

    # 1. Prowlarr Probe
    prowlarr_url = os.environ.get("PROWLARR_URL", "http://prowlarr:9696").rstrip("/")
    prowlarr_api_key = os.environ.get("PROWLARR_API_KEY") or env.get("PROWLARR_API_KEY", "prowlarr_internal_secret_key_99")
    prowlarr_res = {"latency_ms": None, "status": "pending", "result_count": 0, "error": None}

    t0_prow = time.monotonic()
    try:
        search_query = urllib.parse.quote("Inception" if sample_id == "tt1375666" else sample_id)
        prow_req = urllib.request.Request(
            f"{prowlarr_url}/api/v1/search?query={search_query}&type=search",
            headers={"X-Api-Key": prowlarr_api_key, "Accept": "application/json"}
        )
        with urllib.request.urlopen(prow_req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            prowlarr_ms = round((time.monotonic() - t0_prow) * 1000, 1)
            count = len(data) if isinstance(data, list) else 0
            prowlarr_res.update({
                "latency_ms": prowlarr_ms,
                "status": "ok" if prowlarr_ms < 5000 else "slow",
                "result_count": count
            })
    except Exception as e:
        try:
            t0_ping = time.monotonic()
            ping_req = urllib.request.Request(
                f"{prowlarr_url}/api/v1/system/status",
                headers={"X-Api-Key": prowlarr_api_key, "Accept": "application/json"}
            )
            with urllib.request.urlopen(ping_req, timeout=3) as resp:
                prowlarr_ms = round((time.monotonic() - t0_ping) * 1000, 1)
                prowlarr_res.update({
                    "latency_ms": prowlarr_ms,
                    "status": "ok" if prowlarr_ms < 5000 else "slow",
                    "result_count": 0,
                    "error": f"Search unavailable ({type(e).__name__}); status OK"
                })
        except Exception as e2:
            elapsed = round((time.monotonic() - t0_prow) * 1000, 1)
            prowlarr_res.update({
                "latency_ms": elapsed,
                "status": "unreachable",
                "error": str(e)
            })

    # 2. Zilean Probe
    zilean_url = os.environ.get("ZILEAN_URL", "http://zilean:8181").rstrip("/")
    zilean_res = {"latency_ms": None, "status": "pending", "hash_count": 0, "error": None}

    t0_zil = time.monotonic()
    try:
        zil_query = urllib.parse.quote("Inception" if sample_id == "tt1375666" else sample_id)
        zil_req = urllib.request.Request(
            f"{zilean_url}/dmm/filtered?query={zil_query}",
            headers={"Accept": "application/json"}
        )
        with urllib.request.urlopen(zil_req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            zilean_ms = round((time.monotonic() - t0_zil) * 1000, 1)
            count = len(data) if isinstance(data, list) else 0
            zilean_res.update({
                "latency_ms": zilean_ms,
                "status": "ok" if zilean_ms < 3000 else "slow",
                "hash_count": count
            })
    except Exception as e:
        elapsed = round((time.monotonic() - t0_zil) * 1000, 1)
        zilean_res.update({
            "latency_ms": elapsed,
            "status": "unreachable",
            "error": str(e)
        })

    # 3. Debrid Probe (Premiumize prioritized, or configured debrid)
    debrid_prov = "premiumize" if env.get("PREMIUMIZE_API_KEY") else None
    if not debrid_prov:
        for prov in ("realdebrid", "torbox", "alldebrid", "debridlink", "easydebrid"):
            key_name = PROVIDER_VALIDATORS.get(prov, (None,))[0]
            if key_name and env.get(key_name):
                debrid_prov = prov
                break

    debrid_res = {"provider": debrid_prov or "none", "latency_ms": None, "status": "not_configured", "error": None}
    if debrid_prov:
        key_name = PROVIDER_VALIDATORS[debrid_prov][0]
        api_key = env.get(key_name, "")
        t0_deb = time.monotonic()
        try:
            if debrid_prov == "premiumize":
                deb_req = urllib.request.Request(
                    f"https://www.premiumize.me/api/account/info?apikey={urllib.parse.quote(api_key)}",
                    headers={"User-Agent": "AIO-CometProbe/1.0"}
                )
            else:
                tmpl = PROVIDER_VALIDATORS[debrid_prov][1]
                deb_req = urllib.request.Request(
                    tmpl.format(key=urllib.parse.quote(api_key)),
                    headers={"User-Agent": "AIO-CometProbe/1.0"}
                )
            with urllib.request.urlopen(deb_req, timeout=8) as resp:
                resp.read(512)
                debrid_ms = round((time.monotonic() - t0_deb) * 1000, 1)
                debrid_res.update({
                    "latency_ms": debrid_ms,
                    "status": "ok" if debrid_ms < 4000 else "slow"
                })
        except Exception as e:
            elapsed = round((time.monotonic() - t0_deb) * 1000, 1)
            debrid_res.update({
                "latency_ms": elapsed,
                "status": "unreachable",
                "error": str(e)
            })

    # 4. Comet End-to-End Direct Scrape Probe
    comet_url = os.environ.get("COMET_URL", "http://comet:8000").rstrip("/")
    comet_res = {"latency_ms": None, "status": "pending", "stream_count": 0, "error": None}

    debrid_services = []
    if debrid_prov and env.get(PROVIDER_VALIDATORS[debrid_prov][0]):
        debrid_services.append({
            "service": debrid_prov,
            "apiKey": env.get(PROVIDER_VALIDATORS[debrid_prov][0])
        })

    cfg = {
        "maxResultsPerResolution": 0, "maxSize": 0, "cachedOnly": False, "removeTrash": True,
        "resultFormat": ["all"],
        "debridServices": debrid_services,
        "enableTorrent": False, "scrapeDebridAccountTorrents": False, "debridStreamProxyPassword": "",
        "languages": {"required": [], "exclude": [], "preferred": []}, "resolutions": {},
        "options": {"remove_ranks_under": -10000000000, "allow_english_in_languages": False, "remove_unknown_languages": False}
    }
    b64_cfg = base64.b64encode(json.dumps(cfg).encode()).decode()
    target_comet_url = f"{comet_url}/{b64_cfg}/stream/{kind}/{sample_id}.json"

    t0_comet = time.monotonic()
    streams_found = []
    try:
        req = urllib.request.Request(target_comet_url, headers={"User-Agent": "AIO-CometProbe/1.0", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            comet_ms = round((time.monotonic() - t0_comet) * 1000, 1)
            if isinstance(data, dict):
                streams_found = data.get("streams", [])
            comet_res.update({
                "latency_ms": comet_ms,
                "status": "ok" if comet_ms < 20000 else "slow",
                "stream_count": len(streams_found)
            })
    except Exception as e:
        elapsed = round((time.monotonic() - t0_comet) * 1000, 1)
        comet_res.update({
            "latency_ms": elapsed,
            "status": "timeout" if isinstance(e, (socket.timeout, TimeoutError)) or "timed out" in str(e).lower() else "unreachable",
            "error": str(e)
        })

    # 5. Delay Attribution Analysis
    culprit = "none"
    reasons = []

    prow_lat = prowlarr_res.get("latency_ms") or 0
    zil_lat = zilean_res.get("latency_ms") or 0
    deb_lat = debrid_res.get("latency_ms") or 0
    com_lat = comet_res.get("latency_ms") or 0

    is_healthy = True

    if comet_res["status"] in ("timeout", "unreachable"):
        is_healthy = False
        if prowlarr_res["status"] == "unreachable":
            culprit = "prowlarr"
            reasons.append(f"Prowlarr is unreachable ({prowlarr_res.get('error')})")
        elif zilean_res["status"] == "unreachable":
            culprit = "zilean"
            reasons.append(f"Zilean hash cache is unreachable ({zilean_res.get('error')})")
        elif debrid_res["status"] == "unreachable":
            culprit = debrid_prov or "debrid"
            reasons.append(f"{debrid_prov.capitalize() if debrid_prov else 'Debrid'} API is unreachable ({debrid_res.get('error')})")
        elif com_lat >= 20000:
            max_lat = max(prow_lat, zil_lat, deb_lat)
            if max_lat == prow_lat and prow_lat > 4000:
                culprit = "prowlarr"
                reasons.append(f"Prowlarr took {prow_lat}ms, bottlenecking Comet indexer searches")
            elif max_lat == deb_lat and deb_lat > 3000:
                culprit = debrid_prov or "debrid"
                reasons.append(f"{debrid_prov.capitalize() if debrid_prov else 'Debrid'} API took {deb_lat}ms for cache checks")
            elif max_lat == zil_lat and zil_lat > 2500:
                culprit = "zilean"
                reasons.append(f"Zilean took {zil_lat}ms for DMM hash lookup")
            else:
                culprit = "comet"
                reasons.append(f"Comet direct scrape timed out after {com_lat}ms")
        else:
            culprit = "comet"
            reasons.append(f"Comet returned error: {comet_res.get('error')}")
    else:
        if com_lat > 8000:
            if prow_lat > 4000:
                culprit = "prowlarr"
                reasons.append(f"Prowlarr search delay ({prow_lat}ms)")
            elif deb_lat > 3000:
                culprit = debrid_prov or "debrid"
                reasons.append(f"{debrid_prov.capitalize() if debrid_prov else 'Debrid'} API response delay ({deb_lat}ms)")
            elif zil_lat > 2500:
                culprit = "zilean"
                reasons.append(f"Zilean hash cache delay ({zil_lat}ms)")
            else:
                culprit = "comet"
                reasons.append(f"Comet internal aggregation delay ({com_lat}ms)")
        else:
            attribution = f"Comet scraper pipeline is healthy and responsive ({com_lat}ms). Prowlarr ({prow_lat}ms), Zilean ({zil_lat}ms), and {debrid_prov or 'Debrid'} ({deb_lat}ms) all within normal thresholds."

    if culprit != "none":
        attribution = f"Delay / issue attributed to {culprit.upper()}: " + "; ".join(reasons)
        if comet_res["stream_count"] > 0:
            attribution += f" ({comet_res['stream_count']} streams resolved in {com_lat}ms)"
    elif not is_healthy:
        attribution = "Comet pipeline check failed: " + "; ".join(reasons)
    elif "attribution" not in locals():
        attribution = f"Comet scraper pipeline is healthy ({com_lat}ms)."

    return {
        "healthy": is_healthy and (comet_res["status"] == "ok"),
        "primary_bottleneck": culprit,
        "attribution": attribution,
        "comet": comet_res,
        "prowlarr": prowlarr_res,
        "zilean": zilean_res,
        "debrid": debrid_res,
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }


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
    candidates = [
        os.path.join(WEB_ROOT, "data", "aiostreams", "aiostreams_install.json"),
        os.path.join(WEB_ROOT, "data", "stremio-web", "aiostreams_install.json"),
        os.path.join(WEB_ROOT, "data", "aiostreams_install.json"),
        "/data/aiostreams/aiostreams_install.json",
        "/data/stremio-web/aiostreams_install.json",
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
            try:
                auth = base64.b64encode(f"{install_uuid}:{pw}".encode()).decode("ascii")
                req = urllib.request.Request(
                    f"{aiostreams_url}/api/v1/user",
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
    if kind == "caddy":
        return f"{base_url.replace('https://', '').replace('http://', '')} {{\n  reverse_proxy aiostreams:3000\n}}\n\n{aiometa.replace('https://', '').replace('http://', '')} {{\n  reverse_proxy aiometadata:4005\n}}"
    if kind == "nginx":
        return f"location / {{\n  proxy_pass http://aiostreams:3000;\n  proxy_set_header Host $host;\n  proxy_set_header X-Forwarded-Proto $scheme;\n  proxy_read_timeout 3600s;\n  proxy_buffering off;\n}}\n\n# AIOMetadata host: {aiometa}"
    if kind == "traefik":
        return f"labels:\n  - traefik.enable=true\n  - traefik.http.routers.aiostreams.rule=Host(`{hostname}`)\n  - traefik.http.services.aiostreams.loadbalancer.server.port=3000"
    if kind == "cloudflare":
        return f"tunnel: aio-local\ncredentials-file: /etc/cloudflared/credentials.json\n\ningress:\n  - hostname: {base_url.split('://', 1)[-1].split(':', 1)[0]}\n    service: http://aiostreams:3000\n  - hostname: {aiometa.split('://', 1)[-1].split(':', 1)[0]}\n    service: http://aiometadata:4005\n  - service: http_status:404"
    raise ValueError("Unsupported proxy format")


def save_env_updates(updates):
    """Serialize concurrent portal writes and replace the file only when complete."""
    with ENV_LOCK:
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
        descriptor, temporary = tempfile.mkstemp(prefix=".env-", dir=os.path.dirname(ENV_PATH))
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                output.write("\n".join(result) + "\n")
            os.replace(temporary, ENV_PATH)
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
_INFINIDYSK_SESSION = None

def get_infinidysk_session_cookie(force_refresh=False):
    global _INFINIDYSK_SESSION
    if _INFINIDYSK_SESSION and not force_refresh:
        return _INFINIDYSK_SESSION
    env = read_saved_env()
    addon_pw = env.get("ADDON_PASSWORD") or os.environ.get("ADDON_PASSWORD") or "admin"
    configured_url = os.environ.get("INFINIDYSK_URL", "http://infinidysk:3000").rstrip("/")
    candidates = [configured_url, "http://127.0.0.1:3005", "http://localhost:3005"]
    seen = set()
    unique_candidates = [c for c in candidates if not (c in seen or seen.add(c))]

    login_payload = urllib.parse.urlencode({"username": "admin", "password": addon_pw}).encode("utf-8")
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(NoRedirect)

    for base in unique_candidates:
        login_url = f"{base}/login"
        req = urllib.request.Request(
            login_url,
            data=login_payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        try:
            try:
                resp = opener.open(req, timeout=3)
                headers = resp.headers
            except urllib.error.HTTPError as e:
                headers = e.headers

            cookie_header = headers.get("Set-Cookie")
            if cookie_header:
                match = re.search(r"(__session=[^;]+)", cookie_header)
                if match:
                    _INFINIDYSK_SESSION = match.group(1)
                    return _INFINIDYSK_SESSION
        except Exception:
            continue
    return _INFINIDYSK_SESSION


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
        auth_required = (os.environ.get("PORTAL_AUTH_REQUIRED") or read_saved_env().get("PORTAL_AUTH_REQUIRED", "false")).lower() in ("true", "1", "yes")
        if not auth_required:
            return True
        password = read_saved_env().get("ADDON_PASSWORD") or os.environ.get("ADDON_PASSWORD") or "admin"
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
            self.send_error(404)
            return None
        return super().send_head()

    def proxy_to_service(self, service, subpath, query="", is_alias=False):
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

        normalized_subpath = "/" + subpath.lstrip("/") if subpath else "/"
        query_str = f"?{query}" if query else ""
        # Prowlarr is configured with urlBase=/service-proxy/prowlarr, so it
        # expects the full prefixed path in every request (not just the subpath).
        if service == "prowlarr" and not normalized_subpath.startswith("/service-proxy/prowlarr"):
            rel_url = f"/service-proxy/prowlarr{normalized_subpath}{query_str}"
        else:
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

        infinidysk_auto_cookie = None
        if service == "infinidysk":
            existing_cookie = self.headers.get("Cookie", "")
            if "__session" not in existing_cookie:
                infinidysk_auto_cookie = get_infinidysk_session_cookie()
                if infinidysk_auto_cookie:
                    forward_headers["Cookie"] = f"{existing_cookie}; {infinidysk_auto_cookie}".strip("; ") if existing_cookie else infinidysk_auto_cookie

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
                    base_href = "/jellyfin/web/" if "/web" in normalized_subpath else "/jellyfin/"
                else:
                    base_href = f"/service-proxy/{service}/"

                # Prowlarr now uses urlBase natively; no HTML rewriting needed.
                # Other services still get a <base> tag injected if missing.
                if "<base" not in html_text.lower() and service != "prowlarr":
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

        # initialize.json: Prowlarr returns correct urlBase/apiRoot now that urlBase is set in config.xml

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

            if service == "infinidysk":
                # Intercept redirects back to login (indicating stale/expired session)
                if status_code in (302, 303, 307) and location and "/login" in location:
                    _INFINIDYSK_SESSION = None
                    fresh_cookie = get_infinidysk_session_cookie(force_refresh=True)
                    if fresh_cookie:
                        infinidysk_auto_cookie = fresh_cookie

            if service == "infinidysk" and infinidysk_auto_cookie:
                self.send_header("Set-Cookie", f"{infinidysk_auto_cookie}; Path=/service-proxy/infinidysk/; SameSite=Lax")

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

    def check_proxy_referer_fallback(self, path, query=""):
        referer = self.headers.get("Referer", "")
        if not referer:
            return False
        match = re.search(r"/service-proxy/([a-zA-Z0-9_-]+)(?:/|$)", referer)
        if match:
            service = match.group(1)
            if service in INTERNAL_SERVICE_TARGETS:
                self.proxy_to_service(service, path, query, is_alias=False)
                return True
        elif "/jellyfin" in referer and "aiostreams" in INTERNAL_SERVICE_TARGETS:
            self.proxy_to_service("aiostreams", path, query, is_alias=True)
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

    def do_GET(self):
        url_parts = urllib.parse.urlparse(self.path)
        path = url_parts.path

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

        if path == "/healthz":
            self.json_response({"status": "ok", "service": "portal"})
            return
        if path == "/version":
            self.json_response({"version": APP_VERSION, "service": "aio-local-portal"})
            return
        if path == "/ready":
            try:
                base = os.environ.get("AIOSTREAMS_URL", "http://aiostreams:3000").rstrip("/")
                with urllib.request.urlopen(base + "/api/v1/status", timeout=2):
                    pass
                self.json_response({"status": "ready", "dependencies": {"aiostreams": "ready"}})
            except (OSError, ValueError, urllib.error.URLError):
                self.json_response({"status": "starting", "dependencies": {"aiostreams": "unavailable"}}, 503)
            return
        if path == "/manifest-ready":
            try:
                base = os.environ.get("AIOSTREAMS_URL", "http://aiostreams:3000").rstrip("/")
                manifest_url = base + "/stremio/u/local/manifest.json"
                with urllib.request.urlopen(manifest_url, timeout=3) as response:
                    manifest = json.load(response)
                if not isinstance(manifest, dict) or not manifest.get("id") or not manifest.get("resources"):
                    raise ValueError("Manifest is incomplete")
                self.json_response({"status": "ready", "manifest": manifest.get("id")})
            except (OSError, ValueError, TypeError, json.JSONDecodeError, urllib.error.URLError):
                self.json_response({"status": "starting", "manifest": "unavailable"}, 503)
            return
        if path.startswith("/api/v1/") and self.check_proxy_referer_fallback(path, url_parts.query):
            return
        if (path.startswith("/api/") or path in ("/", "/index.html", "/dashboard", "/dashboard.html")) and not self.authorize():
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
                try:
                    req = urllib.request.urlopen(base + "/stremio/u/local/manifest.json", timeout=5)
                except Exception:
                    req = urllib.request.urlopen("http://localhost:3001/stremio/u/local/manifest.json", timeout=5)
                with req as response:
                    manifest = json.load(response)
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
            self.json_response(playback_readiness())
            return
        if path == "/api/integrations":
            with ThreadPoolExecutor(max_workers=10) as pool:
                integrations = list(pool.map(probe_integration, INTEGRATIONS))
            env = read_saved_env()
            for item, (_, service, _, _) in zip(integrations, INTEGRATIONS):
                if item.get("enabled", True):
                    ui_url = service_ui_url(service, self.headers.get("Host", "localhost"), env)
                    if ui_url:
                        item["uiUrl"] = ui_url
                    proxy_path = SERVICE_UI_PATHS.get(service, "/")
                    if service == "postersplus":
                        p_key = env.get("POSTERSPLUS_ACCESS_KEY") or env.get("ADDON_PASSWORD", "admin")
                        if p_key:
                            proxy_path = f"/admin?access_key={urllib.parse.quote(p_key)}"
                    item["proxyUrl"] = f"/service-proxy/{service}{proxy_path}"
            self.json_response({"integrations": integrations})
            return
        if path == "/api/comet-check":
            query = urllib.parse.parse_qs(url_parts.query)
            sample_id = query.get("id", ["tt1375666"])[0]
            kind = query.get("kind", ["movie"])[0]
            self.json_response(probe_comet_scraper_pipeline(sample_id=sample_id, kind=kind))
            return
        if path == "/api/maintenance":
            self.json_response(maintenance_snapshot())
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
            self.json_response(diagnostics_snapshot())
            return
        if path == "/api/config-export":
            self.json_response(config_export())
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
                    try:
                        req = urllib.request.Request(
                            f"{aiom_base}/api/config/load/{profile_uuid}",
                            data=json.dumps({"password": addon_pw, "addonPassword": addon_pw}).encode(),
                            headers={"Content-Type": "application/json"}
                        )
                        with urllib.request.urlopen(req, timeout=5) as resp:
                            res = json.load(resp)
                            if isinstance(res, dict) and res.get("success") and isinstance(res.get("config"), dict):
                                config_data = res.get("config")
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
            profile = "core" if memory_gb and memory_gb < 4 else "scrapers" if memory_gb < 8 else "all"
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
        elif path == "/dashboard":
            self.path = "/dashboard.html"
            return super().do_GET()
        elif path == "/manifest.json":
            # If client requests root manifest on appliance portal, redirect to AIOStreams master manifest
            env_vars = read_saved_env()
            base_url = env_vars.get("BASE_URL") or os.environ.get("BASE_URL")
            if base_url and not any(h in base_url for h in ("localhost:3000", "127.0.0.1:3000", "aiostreams:3000")):
                target = f"{base_url.rstrip('/')}/stremio/u/local/manifest.json"
            else:
                raw_host = self.headers.get("Host", "localhost").split(":")[0]
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
        elif path in ("/api/zilean", "/api/zilean-stats"):
            self.handle_api_zilean_stats()
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

        if self.check_proxy_referer_fallback(path, url_parts.query):
            return

        return super().do_GET()

    def do_POST(self):
        url_parts = urllib.parse.urlsplit(self.path)
        path = url_parts.path
        if path.startswith("/service-proxy") or path == "/jellyfin" or path.startswith("/jellyfin/"):
            self.handle_proxy_route(path, url_parts.query)
            return
        if path.startswith("/api/v1/") and self.check_proxy_referer_fallback(path, url_parts.query):
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

                api_keys = tmpl_cfg.setdefault("apiKeys", {})
                for k, env_k in [("tmdb", "TMDB_API_KEY"), ("tvdb", "TVDB_API_KEY"), ("mdblist", "MDBLIST_API_KEY"),
                                 ("rpdb", "RPDB_API_KEY"), ("fanart", "FANART_API_KEY"), ("gemini", "GEMINI_API_KEY")]:
                    val = env_vars.get(env_k) or os.environ.get(env_k)
                    if val:
                        api_keys[k] = val

                save_data = json.dumps({"config": tmpl_cfg, "password": addon_pw, "addonPassword": addon_pw}).encode()
                endpoint = f"{aiom_base}/api/config/update/{existing_profile}" if existing_profile else f"{aiom_base}/api/config/save"
                req_method = "PUT" if existing_profile else "POST"
                req = urllib.request.Request(endpoint, data=save_data, method=req_method, headers={"Content-Type": "application/json"})
                aiom_res = {}
                try:
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        aiom_res = json.load(resp)
                except Exception as e:
                    if existing_profile:
                        req_fb = urllib.request.Request(f"{aiom_base}/api/config/save", data=save_data, method="POST", headers={"Content-Type": "application/json"})
                        try:
                            with urllib.request.urlopen(req_fb, timeout=10) as resp:
                                aiom_res = json.load(resp)
                        except Exception as e2:
                            self.json_response({"success": False, "error": f"Failed to contact AIOMetadata: {e2}"}, 502)
                            return
                    else:
                        self.json_response({"success": False, "error": f"Failed to contact AIOMetadata: {e}"}, 502)
                        return

                user_uuid = aiom_res.get("userUUID") or aiom_res.get("uuid") or existing_profile
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
            except Exception as e:
                self.json_response({"success": False, "error": str(e)}, 500)
            return
        if path == "/api/validate-provider":
            try:
                payload = self.read_json_body()
                self.json_response(validate_provider(payload.get("provider"), payload.get("key")))
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
        if path == "/api/comet-check":
            try:
                payload = self.read_json_body()
            except Exception:
                payload = {}
            sample_id = payload.get("id") or "tt1375666"
            kind = payload.get("kind") or "movie"
            self.json_response(probe_comet_scraper_pipeline(sample_id=sample_id, kind=kind))
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
                    profiles = {profile.strip() for profile in supplied["COMPOSE_PROFILES"].split(",") if profile.strip()}
                    if not profiles or not profiles.issubset({"core", "scrapers", "proxies", "web", "usenet", "tunnel", "all"}):
                        self.json_response({"error": "COMPOSE_PROFILES contains an unsupported profile."}, 400)
                        return
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
        elif path == "/api/backups/prune":
            self.handle_api_backups_prune()
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
                for endpoint in [aio_url + "/api/v1/status"]:
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
        base_val = normalize_base_url(env_vars.get("BASE_URL") or os.environ.get("BASE_URL"))
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
            "slicksync": safe_port(env_vars.get("PORT_SLICKSYNC") or os.environ.get("PORT_SLICKSYNC"), 8086),
        }
        for port_key in ("PORT_PORTAL", "PORT_AIOSTREAMS", "PORT_AIOMETADATA", "PORT_SLICKSYNC"):
            val = env_vars.get(port_key) or os.environ.get(port_key)
            if val:
                resp_env[port_key] = val
        resp_env["ports"] = ports

        resp = {
            "appliance": True,
            "status": "online",
            "docker_ready": docker_ready,
            "aggregator_ready": aggregator_ready,
            "version": "1.1.0",
            "ports": ports,
            "env": resp_env
        }
        self.json_response(resp_env if env_only else resp)

    def update_env_key(self, key, value):
        try:
            save_env_updates({key: value})
        except Exception as e:
            log_key = "[REDACTED]" if re.search(r"KEY|PASS|TOKEN|SECRET", key) else key
            print(f"[Portal] Note updating env key {log_key}: {type(e).__name__}", flush=True)

    def handle_api_manifest_info(self):
        install_info = {}
        candidates = [
            os.path.join(WEB_ROOT, "data", "aiostreams", "aiostreams_install.json"),
            os.path.join(WEB_ROOT, "data", "stremio-web", "aiostreams_install.json"),
            os.path.join(WEB_ROOT, "data", "aiostreams_install.json"),
            "/data/aiostreams/aiostreams_install.json",
            "/data/stremio-web/aiostreams_install.json",
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
        jellyfin_web_player_proxy = f"/service-proxy/aiostreams/jellyfin/{uuid}/{encrypted_password}/web/" if uuid and encrypted_password else "/service-proxy/aiostreams/jellyfin/web/"
        jellyfin_server_proxy = f"/service-proxy/aiostreams/jellyfin/{uuid}/{encrypted_password}" if uuid and encrypted_password else "/service-proxy/aiostreams/jellyfin"
        resp = {
            "success": True,
            "uuid": uuid,
            "encryptedPassword": encrypted_password,
            "baseUrl": base_url,
            "directManifest": direct_manifest,
            "aliasManifest": alias_manifest,
            "aiostreamsConfigure": f"{base_url}/stremio/u/local/configure" if direct_manifest else f"{base_url}/stremio/configure",
            "aiostreamsDashboard": f"{base_url}/dashboard",
            "jellyfinServer": jellyfin_server,
            "jellyfinWebPlayer": jellyfin_web_player,
            "jellyfinWebPlayerProxy": jellyfin_web_player_proxy,
            "jellyfinServerProxy": jellyfin_server_proxy,
            "jellyfinQuickConnect": f"{base_url}/jellyfin/quickconnect",
            "officialWebPlayer": "https://web.aiostreams.org",
            "jellyfinEnabled": jellyfin_enabled_val,
            "aiometadataHost": aiom_host,
            "aiometadataConfigure": f"{aiom_host}{aiom_path}/configure",
            "aiometadataManifest": aiom_manifest,
            "aiometadataProfileUuid": aiom_profile or None,
            "aiometadataTemplate": env_vars.get("AIOMETADATA_TEMPLATE") or os.environ.get("AIOMETADATA_TEMPLATE") or "tamtaro-aiometadata-with-anime.json",
        }
        self.json_response(resp)

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
            "aiostreams", "portal", "controller", "flaresolverr", "comet",
            "infinidysk", "prowlarr", "zilean", "shared-postgres", "shared-redis",
            "postersplus", "anime-kitsu", "subsense",
            "stremthru", "aiometadata", "slicksync", "setup"
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
                        logs[name] = "".join(lines[-100:])
                except Exception:
                    logs[name] = "Error reading log."
            else:
                logs[name] = "Log file not found."

        self.json_response(logs)

    def handle_api_flaresolverr(self):
        flaresolverr_url = os.environ.get("FLARESOLVERR_URL", "http://flaresolverr:8191").rstrip("/")
        try:
            req = urllib.request.Request(f"{flaresolverr_url}/", headers={"User-Agent": "AIO-Local-Stack/1.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                raw_bytes = resp.read()
                version = "v3.3+"
                try:
                    data = json.loads(raw_bytes.decode("utf-8", errors="ignore"))
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
        except Exception:
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
            ("comet", os.environ.get("COMET_URL", "http://comet:8000").rstrip("/") + "/manifest.json"),
            ("zilean", os.environ.get("ZILEAN_URL", "http://zilean:8181").rstrip("/") + "/dmm/filtered?query=Inception"),
            ("prowlarr", "http://prowlarr:9696/ping")
        ]
        for name, url in targets:
            t0 = time.monotonic()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "AIO-Benchmark/1.0"})
                with urllib.request.urlopen(req, timeout=2) as resp:
                    resp.read(256)
                    ms = round((time.monotonic() - t0) * 1000, 1)
                    results[name] = {"status": "ok", "latency_ms": ms}
            except Exception as e:
                results[name] = {"status": "unreachable", "error": type(e).__name__}

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
            for bkey in ('ENABLE_TORRENTIO', 'ENABLE_DMM', 'ENABLE_REMUXDB', 'JELLYFIN_ENABLED'):
                if bkey in keys_to_update and keys_to_update[bkey].lower() not in ('true', 'false', '1', '0'):
                    raise ValueError(f'{bkey} must be true or false')
            port_keys = ('PORT_PORTAL', 'PORT_AIOSTREAMS', 'PORT_AIOMETADATA', 'PORT_SLICKSYNC', 'PORT_SUBSENSE', 'USENET_PORT')
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
                old_urls = public_service_urls(normalize_base_url(existing.get("BASE_URL")))
                for key, url in public_service_urls(keys_to_update["BASE_URL"]).items():
                    current = existing.get(key, "")
                    current_host = urllib.parse.urlsplit(current).hostname
                    if key not in keys_to_update and (not current or current == old_urls[key] or current_host in ("localhost", "127.0.0.1")):
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
            self.send_error(500, "Backup creation failed")

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

    def handle_api_zilean_stats(self):
        try:
            sys.path.insert(0, str(WEB_ROOT))
            import tools.watchdog as stack_watchdog
            stats = stack_watchdog.get_zilean_stats()
            self.json_response({"success": True, "stats": stats})
        except Exception:
            self.json_response({"success": False, "error": "Internal server error occurred while retrieving Zilean statistics."}, 500)

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
