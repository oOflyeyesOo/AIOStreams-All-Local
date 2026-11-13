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
ENV_PATH = os.path.join(WEB_ROOT, ".env")
ENV_EXAMPLE_PATH = os.path.join(WEB_ROOT, ".env.example")
APP_VERSION = os.environ.get("APP_VERSION", "1.2.0")
if WEB_ROOT not in sys.path:
    sys.path.insert(0, WEB_ROOT)
from init.service_inventory import APPLICATION_SERVICE_COUNT, INTEGRATIONS
from tools.usenet_config import form_updates, public_settings, credential
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
    if os.environ.get("COMPOSE_CONTROL_SOCKET"):
        return control_request("GET", "/status")[1]
    with SETUP_LOCK:
        return {**SETUP_JOB, "logs": list(SETUP_JOB["logs"])}


def launch_setup():
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
                                         ("Stremio Web Pre-Seed", "Connecting your players"), ("Test ", "Checking the result")):
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
    "subsense": 3100, "infinidysk": 3005, "stremthru": 8080, "stremio-web": 8082,
    "nuvio": 8085, "slicksync": 8086
}

def probe_integration(item):
    import socket
    name, host, port, group = item
    env_vars = read_saved_env()
    profiles = {p.strip() for p in env_vars.get("COMPOSE_PROFILES", "scrapers").split(",") if p.strip()}
    enabled = True
    if host == "nuvio" and "nuvio" not in profiles and "all" not in profiles:
        enabled = False
    elif host == "infinidysk" and env_vars.get("USENET_ENABLED", "false") != "true" and env_vars.get("STREAMING_MODE") == "debrid":
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


def read_saved_env():
    values = {}
    source = ENV_PATH if os.path.isfile(ENV_PATH) else ENV_EXAMPLE_PATH
    if os.path.isfile(source):
        with open(source, "r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    values[key.strip()] = value.strip().strip("\"'")
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
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.load(resp)
                    streams = data.get("streams", [])
            except Exception:
                pass

        if not streams:
            try:
                req = urllib.request.Request(f"{aio_url}/stremio/u/local/stream/{sample_kind}/{sample_id}.json", headers={"User-Agent": "AIO-Playback-Test/1.0"})
                with urllib.request.urlopen(req, timeout=8) as resp:
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

    # Step 3: Media Range Read & Codec Probe
    media_step = {"name": "Media Range Read & Codec Probe", "status": "pending", "detail": ""}
    if overall_success and resolved_candidate and resolved_candidate.get("url"):
        target_url = resolved_candidate["url"]
        parsed = urllib.parse.urlsplit(target_url)
        ports = {None: ("aiostreams", 3000), 3000: ("aiostreams", 3000), 3001: ("aiostreams", 3000), 8080: ("stremthru", 8080)}
        if parsed.hostname in ("localhost", "127.0.0.1", "aio.yourdomain.com") and parsed.port in ports:
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
                container = "Matroska/WebM" if is_matroska else ("MP4" if is_mp4 else "Stream")
                if resp.status in (200, 206) and len(block) > 0:
                    media_step.update(
                        status="pass",
                        detail=f"Received {len(block)} bytes in {elapsed}s (HTTP {resp.status}, {container} verified). Instant playback confirmed."
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
        "stream_url": target_url if (overall_success and target_url) else (resolved_candidate.get("url") if overall_success and resolved_candidate else None),
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
        with urllib.request.urlopen(url, timeout=12) as response:
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

    if install_uuid:
        for pw in ("admin_local_secret", os.environ.get("ADDON_PASSWORD", "admin")):
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
            if os.environ.get(key) or read_saved_env().get(key)
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


def public_service_urls(base_url):
    parsed = urllib.parse.urlsplit(base_url)
    host = parsed.hostname or "localhost"
    try:
        is_local = ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        is_local = host == "localhost" or "." not in host or host.endswith((".local", ".lan"))
    if ":" in host:
        host = f"[{host}]"
    ports = {"NUVIO_ORIGIN": 8085, "KITSU_URL": 7005}
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
                "url": url or "http://localhost:8082",
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

class AppliancePortalHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_ROOT, **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def request_origin_is_local(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host", "")
        try:
            return urllib.parse.urlsplit(origin).netloc.lower() == host.lower()
        except ValueError:
            return False

    def authorize(self):
        auth_required = (os.environ.get("PORTAL_AUTH_REQUIRED") or read_saved_env().get("PORTAL_AUTH_REQUIRED", "false")).lower() in ("true", "1", "yes")
        if not auth_required:
            return True
        password = os.environ.get("ADDON_PASSWORD") or read_saved_env().get("ADDON_PASSWORD") or "admin"
        client = self.client_address[0]
        now = time.monotonic()
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
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length > 0:
                try:
                    self.rfile.read(min(length, 65536))
                except Exception:
                    pass
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="AIOStreams Portal"')
        self.end_headers()
        return False

    def send_head(self):
        # SimpleHTTPRequestHandler otherwise exposes .env, databases and .git,
        # including through HEAD requests, encoded paths and symbolic links.
        target = pathlib.Path(self.translate_path(self.path)).resolve()
        root = pathlib.Path(WEB_ROOT).resolve()
        try:
            relative = target.relative_to(root)
        except ValueError:
            self.send_error(404)
            return None
        allowed = (relative.as_posix() in ("index.html", "dashboard.html")
                   or (relative.parts and relative.parts[0] in ("assets", "templates")
                       and target.suffix.lower() in (".json", ".png", ".jpg", ".jpeg", ".svg", ".webp", ".css", ".js")))
        if not allowed or not target.is_file() or any(p.startswith(".") for p in relative.parts):
            self.send_error(404)
            return None
        return super().send_head()

    def do_OPTIONS(self):
        url_parts = urllib.parse.urlsplit(self.path)
        path = url_parts.path
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

        if path in ("/api/aniskip", "/aniskip"):
            query = urllib.parse.parse_qs(url_parts.query)
            raw_id = (query.get("id") or [""])[0].strip()
            try:
                season = int((query.get("season") or ["1"])[0] or 1)
            except (ValueError, TypeError):
                season = 1
            try:
                episode = int((query.get("episode") or ["1"])[0] or 1)
            except (ValueError, TypeError):
                episode = 1
            try:
                duration = float((query.get("duration") or ["0"])[0] or 0)
                if math.isnan(duration) or math.isinf(duration) or duration < 0:
                    duration = 0
            except (ValueError, TypeError):
                duration = 0

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
        if path == "/api/integrations":
            with ThreadPoolExecutor(max_workers=10) as pool:
                integrations = list(pool.map(probe_integration, INTEGRATIONS))
            self.json_response({"integrations": integrations})
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
                addon_pw = env_vars.get("ADDON_PASSWORD", os.environ.get("ADDON_PASSWORD", "admin"))
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
                    tmpl_name = env_vars.get("AIOMETADATA_TEMPLATE", "tamtaro-aiometadata-with-anime.json")
                    tmpl_path = os.path.join(WEB_ROOT, "templates", "aiometadata-configs", tmpl_name)
                    if not os.path.isfile(tmpl_path):
                        tmpl_path = os.path.join(WEB_ROOT, "templates", "aiometadata-configs", "tamtaro-aiometadata-with-anime.json")
                    if not os.path.isfile(tmpl_path):
                        repo_candidate = Path(__file__).resolve().parents[2] / "templates" / "aiometadata-configs" / tmpl_name
                        if not repo_candidate.is_file():
                            repo_candidate = Path(__file__).resolve().parents[2] / "templates" / "aiometadata-configs" / "tamtaro-aiometadata-with-anime.json"
                        if repo_candidate.is_file():
                            tmpl_path = str(repo_candidate)
                    if os.path.isfile(tmpl_path):
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
            except Exception as e:
                self.json_response({"error": f"AIOMetadata configuration export failed: {e}"}, 503)
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
            host = self.headers.get("Host", "localhost:3000").split(":")[0]
            target = f"http://{host}:3000/stremio/u/local/manifest.json"
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

        return super().do_GET()

    def do_POST(self):
        url_parts = urllib.parse.urlparse(self.path)
        path = url_parts.path
        if not self.authorize():
            return
        if not self.request_origin_is_local():
            try:
                cl = int(self.headers.get("Content-Length", 0) or 0)
                if cl > 0:
                    self.rfile.read(cl)
            except Exception:
                pass
            self.send_error(403, "Cross-origin configuration changes are not allowed")
            return
        if path == "/api/webhook-test":
            try:
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")) or 0)
                payload = json.loads(body.decode("utf-8")) if body else {}
                if not isinstance(payload, dict):
                    self.json_response({"success": False, "error": "Request body must be a JSON object."}, 400)
                    return
                url = payload.get("url") or read_saved_env().get("DISCORD_WEBHOOK_URL", "")
                if not url:
                    self.json_response({"success": False, "error": "No webhook URL provided"}, 400)
                    return
                success, msg = dispatch_webhook_notification(url, "Simulcast Alert Test", "Your AIO Local Simulcast Airing Alert webhook is active and verified! 🎉")
                self.json_response({"success": success, "message": msg}, 200 if success else 400)
            except Exception as e:
                self.json_response({"success": False, "error": str(e)}, 500)
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
        if path == "/api/validate-provider":
            try:
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0")) or 0) or b"{}")
                if not isinstance(payload, dict):
                    self.json_response({"status": "invalid", "detail": "Request body must be a JSON object."}, 400)
                    return
                self.json_response(validate_provider(payload.get("provider"), payload.get("key")))
            except (json.JSONDecodeError, TypeError):
                self.json_response({"status": "invalid", "detail": "Request body must be JSON."}, 400)
            return
        if path == "/api/smoke-test":
            try:
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0")) or 0) or b"{}")
                if not isinstance(payload, dict):
                    self.json_response({"status": "invalid", "detail": "Request body must be a JSON object."}, 400)
                    return
                self.json_response(run_smoke_test(payload.get("kind"), payload.get("id")))
            except (json.JSONDecodeError, TypeError):
                self.json_response({"status": "invalid", "detail": "Request body must be JSON."}, 400)
            return
        if path == "/api/test-playback":
            try:
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0")) or 0) or b"{}")
                if not isinstance(payload, dict):
                    self.json_response({"status": "invalid", "detail": "Request body must be a JSON object."}, 400)
                    return
                self.json_response(run_playback_test(payload.get("mode"), payload.get("content_id"), payload.get("kind")))
            except (json.JSONDecodeError, TypeError):
                self.json_response({"status": "invalid", "detail": "Request body must be JSON."}, 400)
            return
        if path == "/api/config-import":
            try:
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0")) or 0) or b"{}")
                if payload.get("format") != "aio-local-config-v1" or not isinstance(payload.get("values"), dict):
                    self.json_response({"error": "Use an aio-local-config-v1 export and provide values."}, 400)
                    return
                allowed = {
                    "BASE_URL", "AIOMETADATA_HOST", "AIOMETADATA_TEMPLATE", "COMPOSE_PROFILES",
                    "ENABLE_ANIME_SOURCES", "STREAMING_MODE", "BACKUP_SCHEDULE",
                    "ENABLE_TORRENTIO", "TORRENTIO_URL", "ENABLE_DMM", "ENABLE_REMUXDB",
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
                    if not profiles or not profiles.issubset({"core", "scrapers", "nuvio", "proxies", "web", "usenet", "tunnel", "all"}):
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

        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": "Endpoint not found"}).encode("utf-8"))

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
            "stremio_web": safe_port(env_vars.get("PORT_STREMIO_WEB") or os.environ.get("PORT_STREMIO_WEB"), 8082),
            "nuvio": safe_port(env_vars.get("PORT_NUVIO") or os.environ.get("PORT_NUVIO"), 8085),
            "portal": safe_port(env_vars.get("PORT_PORTAL") or os.environ.get("PORT_PORTAL"), 8088),
            "aiostreams": safe_port(env_vars.get("PORT_AIOSTREAMS") or os.environ.get("PORT_AIOSTREAMS"), 3001),
            "aiometadata": safe_port(env_vars.get("PORT_AIOMETADATA") or os.environ.get("PORT_AIOMETADATA"), 4005),
            "slicksync": safe_port(env_vars.get("PORT_SLICKSYNC") or os.environ.get("PORT_SLICKSYNC"), 8086),
        }
        for port_key in ("PORT_STREMIO_WEB", "PORT_NUVIO", "PORT_PORTAL", "PORT_AIOSTREAMS", "PORT_AIOMETADATA", "PORT_SLICKSYNC"):
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
            print(f"[Portal] Note updating env key {key}: {e}", flush=True)

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

        base_url = normalize_base_url(env_vars.get("BASE_URL") or os.environ.get("BASE_URL", "http://localhost:3000"))
        raw_uuid = install_info.get("uuid") or env_vars.get("DEFAULT_AIO_UUID")
        raw_enc = install_info.get("encrypted_password") or install_info.get("encryptedPassword") or env_vars.get("DEFAULT_AIO_ENCRYPTED_PASSWORD")

        uuid = str(raw_uuid).strip() if raw_uuid and str(raw_uuid).strip() not in ("null", "None", "") else None
        encrypted_password = str(raw_enc).strip() if raw_enc and str(raw_enc).strip() not in ("null", "None", "") else None

        direct_manifest = f"{base_url}/stremio/{uuid}/{encrypted_password}/manifest.json" if uuid and encrypted_password else None
        alias_manifest = f"{base_url}/stremio/u/local/manifest.json"

        # AIOMetadata public subdomain and manifest
        aiom_profile = env_vars.get("AIOMETADATA_PROFILE_UUID") or "a7543d89-6f1a-47d1-abd1-a627e14dbbcb"
        aiom_host = derive_aiometadata_host(base_url, env_vars.get("AIOMETADATA_HOST") or os.environ.get("AIOMETADATA_HOST"))
        aiom_manifest = f"{aiom_host}/stremio/{aiom_profile}/manifest.json" if aiom_profile else f"{aiom_host}/manifest.json"

        resp = {
            "success": True,
            "uuid": uuid,
            "encryptedPassword": encrypted_password,
            "baseUrl": base_url,
            "directManifest": direct_manifest,
            "aliasManifest": alias_manifest,
            "aiometadataHost": aiom_host,
            "aiometadataManifest": aiom_manifest
        }
        self.json_response(resp)

    def handle_api_logs(self):
        url_parts = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(url_parts.query)
        container = (query.get("container") or [""])[0].strip()

        safe_containers = {
            "aiostreams", "portal", "controller", "flaresolverr", "comet",
            "infinidysk", "prowlarr", "zilean", "shared-postgres", "shared-redis",
            "stremio-web", "nuvio"
        }

        if container and container in safe_containers:
            try:
                tail = int((query.get("tail") or ["60"])[0] or 60)
            except (ValueError, TypeError):
                tail = 60
            tail = max(1, min(tail, 500))

            # 1. Try Docker CLI if available
            try:
                res = subprocess.run(["docker", "logs", "--tail", str(min(tail, 200)), container],
                                     capture_output=True, text=True, timeout=4)
                if res.returncode == 0 and (res.stdout or res.stderr):
                    self.json_response({"container": container, "logs": (res.stdout or res.stderr).strip()})
                    return
            except Exception:
                pass

            # 2. Try log files in /var/log/
            log_path = f"/var/log/{container}.log"
            if os.path.isfile(log_path):
                try:
                    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                        self.json_response({"container": container, "logs": "".join(lines[-tail:]).strip()})
                        return
                except Exception:
                    pass

            self.json_response({
                "container": container,
                "logs": f"[{container}] Service monitored. Direct container log streaming is unavailable in this environment."
            })
            return

        logs = {}
        for name, path in [("dockerd", "/var/log/dockerd.log"), ("portal", "/var/log/portal_server.log")]:
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                        logs[name] = "".join(lines[-100:])
                except Exception as e:
                    logs[name] = f"Error reading log: {e}"
            else:
                logs[name] = "Log file not found."

        self.json_response(logs)

    def handle_api_flaresolverr(self):
        flaresolverr_url = os.environ.get("FLARESOLVERR_URL", "http://flaresolverr:8191").rstrip("/")
        try:
            req = urllib.request.Request(f"{flaresolverr_url}/", headers={"User-Agent": "AIO-Local-Stack/1.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode())
                version = data.get("version", "v3.3+")
                self.json_response({
                    "status": "online",
                    "reachable": True,
                    "version": version,
                    "url": flaresolverr_url,
                    "message": f"FlareSolverr ({version}) is active and ready to bypass Cloudflare challenges for scrapers."
                })
        except Exception as e:
            self.json_response({
                "status": "offline",
                "reachable": False,
                "url": flaresolverr_url,
                "message": f"FlareSolverr is not responding at {flaresolverr_url}: {e}"
            }, 503)

    def handle_api_benchmark(self):
        results = {}
        targets = [
            ("aiostreams", os.environ.get("AIOSTREAMS_URL", "http://aiostreams:3000").rstrip("/") + "/manifest.json"),
            ("aiometadata", os.environ.get("AIOMETADATA_URL", "http://aiometadata:4005").rstrip("/") + "/manifest.json"),
            ("flaresolverr", os.environ.get("FLARESOLVERR_URL", "http://flaresolverr:8191").rstrip("/") + "/"),
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
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length < 0 or content_length > 65536:
                self.send_error(413, "Configuration body is too large")
                return
            body = self.rfile.read(content_length).decode("utf-8")
            data = json.loads(body) if body else {}
            if not isinstance(data, dict):
                raise ValueError("Configuration must be a JSON object")
            data=form_updates(data,read_saved_env())
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
            for bkey in ('ENABLE_TORRENTIO', 'ENABLE_DMM', 'ENABLE_REMUXDB'):
                if bkey in keys_to_update and keys_to_update[bkey].lower() not in ('true', 'false', '1', '0'):
                    raise ValueError(f'{bkey} must be true or false')
            port_keys = ('PORT_PORTAL', 'PORT_AIOSTREAMS', 'PORT_AIOMETADATA', 'PORT_STREMIO_WEB', 'PORT_NUVIO', 'PORT_SLICKSYNC', 'PORT_SUBSENSE', 'USENET_PORT')
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
                if not re.fullmatch(r"[A-Za-z0-9_.-]+", tmpl):
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
            self.send_error(400, str(e))
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))

    def handle_api_restart(self):
        try:
            subprocess.Popen(["docker", "compose", "restart"], cwd=WEB_ROOT)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "message": "Stack restart initiated."}).encode("utf-8"))
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))

    def handle_api_templates(self):
        templates_dir = os.path.join(WEB_ROOT, "templates")
        result = []
        if os.path.isdir(templates_dir):
            for root, _, files in os.walk(templates_dir):
                for file in files:
                    if file.endswith(".json"):
                        rel_path = os.path.relpath(os.path.join(root, file), WEB_ROOT).replace("\\", "/")
                        result.append({"name": file, "path": rel_path})

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"templates": result}).encode("utf-8"))

    def handle_api_backup(self):
        try:
            backup_dir = Path(WEB_ROOT) / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            sys.path.insert(0, str(WEB_ROOT))
            import tools.backup as stack_backup
            archive = stack_backup.create_backup(backup_dir, Path(WEB_ROOT), keep_last=5)

            size = archive.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", "application/gzip")
            self.send_header("Content-Disposition", f'attachment; filename="{archive.name}"')
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with open(archive, "rb") as f:
                shutil.copyfileobj(f, self.wfile)
        except Exception as e:
            self.send_error(500, f"Backup creation failed: {e}")

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
        except Exception as e:
            self.json_response({"success": False, "error": str(e)}, 500)

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
        except Exception as e:
            self.json_response({"success": False, "error": str(e)}, 500)

    def handle_api_zilean_stats(self):
        try:
            sys.path.insert(0, str(WEB_ROOT))
            import tools.watchdog as stack_watchdog
            stats = stack_watchdog.get_zilean_stats()
            self.json_response({"success": True, "stats": stats})
        except Exception as e:
            self.json_response({"success": False, "error": str(e)}, 500)

    def handle_api_backups_list(self):
        try:
            sys.path.insert(0, str(WEB_ROOT))
            import tools.backup as stack_backup
            telemetry = stack_backup.get_backup_telemetry(Path(WEB_ROOT) / "backups", Path(WEB_ROOT))
            self.json_response(telemetry)
        except Exception as e:
            self.json_response({"success": False, "error": str(e)}, 500)

    def handle_api_backups_prune(self):
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            body = self.rfile.read(length) if length > 0 else b"{}"
            payload = json.loads(body.decode("utf-8")) if body else {}
            if not isinstance(payload, dict):
                self.json_response({"success": False, "error": "Request body must be a JSON object."}, 400)
                return
            try:
                keep_last = int(payload.get("keep_last", 5))
                if keep_last < 1:
                    keep_last = 1
            except (ValueError, TypeError):
                self.json_response({"success": False, "error": "keep_last must be a positive integer."}, 400)
                return
            sys.path.insert(0, str(WEB_ROOT))
            import tools.backup as stack_backup
            res = stack_backup.prune_backups(Path(WEB_ROOT) / "backups", keep_last=keep_last, root=Path(WEB_ROOT))
            self.json_response(res)
        except Exception as e:
            self.json_response({"success": False, "error": str(e)}, 500)

    def handle_api_resources(self):
        try:
            sys.path.insert(0, str(WEB_ROOT))
            import tools.resources as stack_res
            stats = stack_res.get_stack_resources(filter_aio=True)
            self.json_response(stats)
        except Exception as e:
            self.json_response({"success": False, "error": str(e)}, 500)

    def handle_api_clean_cache(self):
        try:
            sys.path.insert(0, str(WEB_ROOT))
            import tools.clean_cache as stack_cleaner
            res = stack_cleaner.clean_stack_cache(Path(WEB_ROOT))
            self.json_response(res)
        except Exception as e:
            self.json_response({"success": False, "error": str(e)}, 500)

class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

def run():
    server_address = ("0.0.0.0", PORT)
    httpd = ThreadingHTTPServer(server_address, AppliancePortalHandler)
    print(f"[PORTAL] Serving AIOStreams Appliance Portal on 0.0.0.0:{PORT} from {WEB_ROOT}...", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()

if __name__ == "__main__":
    run()
