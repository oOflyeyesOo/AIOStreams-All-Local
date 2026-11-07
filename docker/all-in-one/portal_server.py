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
import shutil
import time
import re
import tempfile
import threading
import ipaddress
import socket
import http.client
import platform
from concurrent.futures import ThreadPoolExecutor
from collections import deque

# Ensure unbuffered logging
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(line_buffering=True)

PORT = int(os.environ.get("PORTAL_PORT", "8088"))
WEB_ROOT = os.environ.get("WEB_ROOT", "/app")
ENV_PATH = os.path.join(WEB_ROOT, ".env")
ENV_EXAMPLE_PATH = os.path.join(WEB_ROOT, ".env.example")
APP_VERSION = os.environ.get("APP_VERSION", "1.2.0")
if WEB_ROOT not in sys.path:
    sys.path.insert(0, WEB_ROOT)
from init.service_inventory import APPLICATION_SERVICE_COUNT, INTEGRATIONS
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
                    for marker, step in (("Prowlarr", "Connecting public indexers"), ("MediaFusion Setup", "Configuring scrapers"),
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


def probe_integration(item):
    import socket
    name, host, port, group = item
    try:
        with socket.create_connection((host, port), timeout=1.5):
            reachable = True
    except OSError:
        reachable = False
    return {"name": name, "group": group, "reachable": reachable}


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


def diagnostics_snapshot():
    env_vars = read_saved_env()
    required_keys = ("BASE_URL", "TMDB_API_KEY")
    provider_keys = (
        "REALDEBRID_API_KEY", "TORBOX_API_KEY", "ALLDEBRID_API_KEY",
        "PREMIUMIZE_API_KEY", "DEBRIDLINK_API_KEY", "EASYDEBRID_API_KEY",
        "OFFCLOUD_API_KEY", "SEEDR_API_KEY",
    )
    configured = {key: bool(env_vars.get(key)) for key in required_keys + provider_keys}
    checks = [
        {"name": "portal", "status": "ready", "detail": "Portal process is responding"},
        {"name": "configuration", "status": "ready" if all(configured[key] for key in required_keys) else "attention",
         "detail": "Base URL and TMDB are configured" if all(configured[key] for key in required_keys)
         else "BASE_URL and TMDB_API_KEY are required for the core path"},
        {"name": "provider", "status": "ready" if any(configured[key] for key in provider_keys) else "attention",
         "detail": "At least one debrid provider is configured" if any(configured[key] for key in provider_keys)
         else "Configure one debrid provider API key"},
    ]
    with ThreadPoolExecutor(max_workers=10) as pool:
        integrations = list(pool.map(probe_integration, INTEGRATIONS))
    reachable = sum(1 for item in integrations if item["reachable"])
    checks.append({
        "name": "integrations",
        "status": "ready" if reachable else "attention",
        "detail": f"{reachable}/{len(integrations)} application services reachable",
    })
    return {
        "checks": checks,
        "configuredKeys": sorted(key for key, value in configured.items() if value),
        "integrations": integrations,
        "setup": setup_snapshot(),
    }


PROVIDER_VALIDATORS = {
    "tmdb": ("TMDB_API_KEY", "https://api.themoviedb.org/3/configuration?api_key={key}"),
    "realdebrid": ("REALDEBRID_API_KEY", "https://api.real-debrid.com/rest/1.0/user"),
    "premiumize": ("PREMIUMIZE_API_KEY", "https://www.premiumize.me/api/account/info?apikey={key}"),
    "torbox": ("TORBOX_API_KEY", "https://api.torbox.app/v1/api/user/me?token={key}"),
}


def validate_provider(provider, key):
    provider = str(provider or "").lower().strip()
    if provider not in PROVIDER_VALIDATORS or not isinstance(key, str) or not key.strip():
        return {"status": "invalid", "detail": "Choose a supported provider and enter a key."}
    _, template = PROVIDER_VALIDATORS[provider]
    request = urllib.request.Request(template.format(key=urllib.parse.quote(key.strip(), safe="")), headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            body = json.load(response)
        valid = isinstance(body, dict) and not body.get("error") and not body.get("success") is False
        return {"status": "valid" if valid else "rejected", "detail": "Provider accepted the credentials." if valid else "Provider rejected the credentials."}
    except urllib.error.HTTPError as error:
        return {"status": "rejected", "detail": f"Provider returned HTTP {error.code}."}
    except (OSError, ValueError, json.JSONDecodeError):
        return {"status": "unavailable", "detail": "Provider could not be reached for validation."}


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
    }
    return {
        "format": "aio-local-config-v1",
        "baseUrl": env_vars.get("BASE_URL", ""),
        "profile": env_vars.get("COMPOSE_PROFILES", "all"),
        "values": values,
        "configuredKeys": sorted(key for key, value in env_vars.items() if value and re.search(r"KEY|PASSWORD|TOKEN|SECRET|CLIENT_ID|_ID", key)),
        "secrets": {key: bool(value) for key, value in env_vars.items() if re.search(r"KEY|PASSWORD|TOKEN|SECRET|CLIENT_ID|_ID", key)},
    }


def optimized_profile_export():
    """Build the same local profile used by bootstrap for authenticated download."""
    import importlib.util
    path = os.path.join(WEB_ROOT, "init", "bootstrap", "setup_stack.py")
    if not os.path.isfile(path):
        path = os.path.join(os.path.dirname(__file__), "..", "..", "init", "bootstrap", "setup_stack.py")
    spec = importlib.util.spec_from_file_location("aio_profile_builder", path)
    if not spec or not spec.loader:
        raise RuntimeError("Profile builder is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {
        "format": "aio-local-optimized-profile-v1",
        "profile": "all",
        "providerKeys": sorted(
            key for key in ("REALDEBRID_API_KEY", "TORBOX_API_KEY", "ALLDEBRID_API_KEY",
                            "PREMIUMIZE_API_KEY", "DEBRIDLINK_API_KEY", "EASYDEBRID_API_KEY",
                            "OFFCLOUD_API_KEY", "SEEDR_API_KEY", "TMDB_API_KEY", "TVDB_API_KEY")
            if os.environ.get(key) or read_saved_env().get(key)
        ),
        "config": module.build_default_config(probe_services=False),
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
    ports = {"SOOTIO_URL": 55771, "MEDIAFUSION_HOST_URL": 8001,
             "NUVIO_ORIGIN": 8085, "KITSU_URL": 7005, "DEBRID_SEARCH_URL": 3001}
    urls = {key: f"{parsed.scheme}://{host}:{port}" for key, port in ports.items()}
    if is_local:
        urls["AIOMETADATA_HOST"] = f"{parsed.scheme}://{host}:4005"
    else:
        urls["AIOMETADATA_HOST"] = derive_aiometadata_host(base_url)
    return urls

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
        try:
            return urllib.parse.urlsplit(origin).netloc.lower() == self.headers.get("Host", "").lower()
        except ValueError:
            return False

    def authorize(self):
        password = os.environ.get("ADDON_PASSWORD")
        if not password:
            self.send_error(503, "Portal password is not configured")
            return False
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
        if not self.request_origin_is_local():
            self.send_error(403, "Cross-origin requests are not allowed")
            return
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        url_parts = urllib.parse.urlparse(self.path)
        path = url_parts.path

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
                with urllib.request.urlopen(base + "/stremio/u/local/manifest.json", timeout=10) as response:
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
            self.send_error(403, "Cross-origin configuration changes are not allowed")
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
                self.json_response(validate_provider(payload.get("provider"), payload.get("key")))
            except (json.JSONDecodeError, TypeError):
                self.json_response({"status": "invalid", "detail": "Request body must be JSON."}, 400)
            return
        if path == "/api/smoke-test":
            try:
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0")) or 0) or b"{}")
                self.json_response(run_smoke_test(payload.get("kind"), payload.get("id")))
            except (json.JSONDecodeError, TypeError):
                self.json_response({"status": "invalid", "detail": "Request body must be JSON."}, 400)
            return
        if path == "/api/config-import":
            try:
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0")) or 0) or b"{}")
                if payload.get("format") != "aio-local-config-v1" or not isinstance(payload.get("values"), dict):
                    self.json_response({"error": "Use an aio-local-config-v1 export and provide values."}, 400)
                    return
                allowed = {"BASE_URL", "AIOMETADATA_HOST", "COMPOSE_PROFILES", "TMDB_API_KEY", "REALDEBRID_API_KEY", "TORBOX_API_KEY", "PREMIUMIZE_API_KEY", "ALLDEBRID_API_KEY"}
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
                    if not profiles or not profiles.issubset({"core", "scrapers", "proxies", "web", "tunnel", "all"}):
                        self.json_response({"error": "COMPOSE_PROFILES contains an unsupported profile."}, 400)
                        return
                updates = supplied
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

        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": "Endpoint not found"}).encode("utf-8"))

    def json_response(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

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
        resp_env = {
            "BASE_URL": base_val,
            "AIOMETADATA_HOST": aiom_val,
            "configuredKeys": sorted(key for key, value in env_vars.items()
                                     if value and re.search(r"KEY|PASSWORD|TOKEN|SECRET|CLIENT_ID|_ID", key))
        }

        resp = {
            "appliance": True,
            "status": "online",
            "docker_ready": docker_ready,
            "aggregator_ready": aggregator_ready,
            "version": "1.1.0",
            "env": resp_env
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(resp_env if env_only else resp).encode("utf-8"))

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
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(resp).encode("utf-8"))

    def handle_api_logs(self):
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

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(logs).encode("utf-8"))

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
            for key, value in data.items():
                if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
                    raise ValueError("Invalid environment variable name")
                if value is not None and (not isinstance(value, (str, int, float, bool))
                        or any(c in str(value) for c in "\r\n\x00$'\"")):
                    raise ValueError("Values must be single-line scalars without quotes or dollar interpolation")

            keys_to_update = {str(k): str(v).strip() for k, v in data.items() if v is not None}
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
            archive = stack_backup.create_backup(backup_dir, Path(WEB_ROOT))

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
