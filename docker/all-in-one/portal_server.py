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
import subprocess
import hmac
import pathlib
import re
import tempfile
import threading
import ipaddress
import socket
import http.client
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
ENV_LOCK = threading.RLock()
SETUP_LOCK = threading.Lock()
SETUP_JOB = {"status": "idle", "step": "Ready to configure", "logs": deque(maxlen=80), "exit_code": None}


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


INTEGRATIONS = [
    ("AIOStreams", "aiostreams", 3000, "Core"), ("Comet", "comet", 8000, "Scrapers"),
    ("MediaFusion", "mediafusion", 8000, "Scrapers"), ("Sootio", "sootio", 55771, "Scrapers"),
    ("Prowlarr", "prowlarr", 9696, "Indexers"), ("FlareSolverr", "flaresolverr", 8191, "Indexers"),
    ("Zilean", "zilean", 8181, "Indexers"), ("AIOMetadata", "aiometadata", 4005, "Metadata"),
    ("Anime Kitsu", "anime-kitsu", 7000, "Metadata"), ("Posters+", "postersplus", 8000, "Metadata"),
    ("SubSense", "subsense", 3100, "Subtitles"), ("Debrid Search", "debrid-search", 3001, "Library"),
    ("InfiniDysk", "infinidysk", 3000, "Usenet"), ("StremThru", "stremthru", 8080, "Proxies"),
    ("MediaFlow", "mediaflow", 8888, "Proxies"), ("Stremio Web", "stremio-web", 8080, "Players"),
    ("Nuvio", "nuvio", 3000, "Players"), ("SlickSync", "slicksync", 3000, "Sync"),
]


def probe_integration(item):
    import socket
    name, host, port, group = item
    try:
        with socket.create_connection((host, port), timeout=1.5):
            reachable = True
    except OSError:
        reachable = False
    return {"name": name, "group": group, "reachable": reachable}


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
             "NUVIO_ORIGIN": 8085, "KITSU_URL": 7005, "DEBRID_SEARCH_URL": 3011}
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
        super().end_headers()

    def authorize(self):
        password = os.environ.get("ADDON_PASSWORD")
        if not password:
            self.send_error(503, "Portal password is not configured")
            return False
        expected = "Basic " + base64.b64encode(
            ("admin:" + password).encode()
        ).decode()
        if hmac.compare_digest(self.headers.get("Authorization", "").encode(), expected.encode()):
            return True
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
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        url_parts = urllib.parse.urlparse(self.path)
        path = url_parts.path

        if path == "/healthz":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
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

        return super().do_GET()

    def do_POST(self):
        url_parts = urllib.parse.urlparse(self.path)
        path = url_parts.path
        if not self.authorize():
            return
        origin = self.headers.get("Origin")
        if origin and urllib.parse.urlsplit(origin).netloc != self.headers.get("Host"):
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

        if path in ("/api/save-env", "/api/quick-setup", "/api/settings", "/api/env", "/api/save"):
            self.handle_api_save_env()
            return
        elif path == "/api/restart":
            self.handle_api_restart()
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
                                     if value and re.search(r"KEY|PASSWORD|TOKEN|SECRET", key))
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
        aiom_profile = env_vars.get("AIOMETADATA_PROFILE_UUID")
        aiom_host = derive_aiometadata_host(base_url, env_vars.get("AIOMETADATA_HOST") or os.environ.get("AIOMETADATA_HOST"))
        aiom_manifest = f"{aiom_host}/stremio/{aiom_profile}/manifest.json" if aiom_profile else None

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
