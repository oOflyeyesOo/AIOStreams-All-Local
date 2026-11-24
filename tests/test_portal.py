import base64
from email.message import Message
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location(
    "portal", Path(__file__).resolve().parents[1] / "docker/all-in-one/portal_server.py")
portal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(portal)


class PortalTests(unittest.TestCase):
    def test_appliance_startup_portal_cannot_save_or_launch_host_bootstrap(self):
        with patch.dict(os.environ, {"AIO_STARTUP_ONLY": "true"}), patch.object(portal.subprocess, "Popen") as start:
            self.assertEqual(portal.setup_snapshot()["status"], "running")
            with self.assertRaisesRegex(RuntimeError, "internal network"):
                portal.launch_setup()
            status, _, _ = self.request('/api/save-env', 'POST', {'TMDB_API_KEY': 'fixture'}, auth=True)
            self.assertEqual(status, 503)
            start.assert_not_called()

    def test_usenet_password_is_saved_privately_and_not_returned_by_env(self):
        status,_,_=self.request('/api/save-env','POST',{'USENET_ENABLED':'true','USENET_HOST':'news.fixture','USENET_USER':'fixture-user','USENET_PASS':'fixture$private\'"'},auth=True)
        self.assertEqual(status,200)
        status,body,_=self.request('/api/env',auth=True)
        self.assertEqual(status,200);self.assertNotIn('fixture$private',body.decode())
        result=json.loads(body);self.assertTrue(result['USENET_PASSWORD_SAVED']);self.assertEqual(result['USENET_USER'],'fixture-user')

    def test_integration_probes_use_container_ports(self):
        self.assertEqual(len(portal.INTEGRATIONS), 11)
        expected = {
            "anime-kitsu": 7000,
            "postersplus": 8000,
        }
        actual = {host: port for _, host, port, _ in portal.INTEGRATIONS}
        self.assertEqual({host: actual[host] for host in expected}, expected)
        self.assertNotIn("infinidysk", actual)

    def test_diagnostics_redacts_provider_values(self):
        with patch.object(portal, "probe_integration", return_value={
            "name": "Prowlarr", "group": "Indexers", "reachable": True,
        }), patch.object(portal, "read_saved_env", return_value={
            "BASE_URL": "https://example.test",
            "TMDB_API_KEY": "tmdb-secret",
            "REALDEBRID_API_KEY": "provider-secret",
        }):
            status, body, _ = self.request("/api/diagnostics", auth=True)
        self.assertEqual(status, 200)
        payload = json.loads(body.decode())
        self.assertIn("TMDB_API_KEY", payload["configuredKeys"])
        self.assertNotIn("tmdb-secret", body.decode())
        self.assertEqual(payload["checks"][2]["status"], "ready")

    def test_proxy_config_and_update_plan_are_safe(self):
        status, body, _ = self.request("/api/proxy-config?format=traefik&base_url=https%3A%2F%2Faio.example.test", auth=True)
        self.assertEqual(status, 200)
        self.assertIn("Host(`aio.example.test`)", body.decode())
        status, body, _ = self.request("/api/update-plan", auth=True)
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body.decode())["backupFirst"])

    def test_provider_validation_does_not_persist_key(self):
        with patch("urllib.request.urlopen", side_effect=OSError("offline")):
            status, body, _ = self.request(
                "/api/validate-provider", "POST",
                {"provider": "tmdb", "key": "not-saved"}, auth=True,
                headers={"Content-Type": "application/json"},
            )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body.decode())["status"], "unavailable")

    def test_smoke_test_reports_playable_streams(self):
        response = type("Response", (), {
            "__enter__": lambda self: self,
            "__exit__": lambda self, *args: None,
            "read": lambda self: json.dumps({"streams": [{"url": "https://cdn.example.test/movie.mp4"}]}).encode(),
        })()
        with patch("urllib.request.urlopen", return_value=response):
            status, body, _ = self.request(
                "/api/smoke-test", "POST", {"kind": "movie", "id": "tt0133093"}, auth=True,
                headers={"Content-Type": "application/json"},
            )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body.decode())["playableCount"], 1)

    def test_config_export_contains_presence_only(self):
        with patch.object(portal, "read_saved_env", return_value={"TMDB_API_KEY": "secret", "COMPOSE_PROFILES": "core"}):
            status, body, _ = self.request("/api/config-export", auth=True)
        self.assertEqual(status, 200)
        payload = json.loads(body.decode())
        self.assertTrue(payload["secrets"]["TMDB_API_KEY"])
        self.assertEqual(payload["values"]["COMPOSE_PROFILES"], "core")
        self.assertNotIn("tmdb-secret", body.decode())

    def test_optimized_profile_export_uses_bootstrap_configuration(self):
        with patch.object(portal, "WEB_ROOT", str(Path(__file__).resolve().parents[1])), \
             patch("urllib.request.urlopen", side_effect=AssertionError("Export must not contact services")):
            status, body, headers = self.request("/api/export-profile", auth=True)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Disposition"], 'attachment; filename="aio-local-optimized-profile.json"')
        payload = json.loads(body.decode())
        self.assertEqual(payload["format"], "aio-local-optimized-profile-v1")
        self.assertIn("services", payload["config"])

    def test_profile_export_failure_returns_one_error_response(self):
        with patch.object(portal, "optimized_profile_export", side_effect=RuntimeError("unavailable")):
            status, body, _ = self.request("/api/export-profile", auth=True)
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)["error"], "The optimized profile is not available yet.")

    def test_config_import_rejects_unsafe_or_unknown_values(self):
        with patch.object(portal, "save_env_updates") as save:
            status, body, _ = self.request(
                "/api/config-import", "POST",
                {"format": "aio-local-config-v1", "values": {"BASE_URL": "https://example.test\nBAD"}},
                auth=True, headers={"Content-Type": "application/json"},
            )
        self.assertEqual(status, 400)
        save.assert_not_called()
        status, body, _ = self.request(
            "/api/config-import", "POST",
            {"format": "aio-local-config-v1", "values": {"NOT_ALLOWED": "x"}},
            auth=True, headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 400)
        status, body, _ = self.request(
            "/api/config-import", "POST",
            {"format": "aio-local-config-v1", "values": {"JELLYFIN_ENABLED": "true"}},
            auth=True, headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200)

    def test_machine_readable_health_endpoints(self):
        for path, expected in (("/healthz", "ok"), ("/version", portal.APP_VERSION)):
            with self.subTest(path=path):
                status, body, _ = self.request(path)
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body.decode())["status" if path == "/healthz" else "version"], expected)

    def test_manifest_readiness_requires_valid_manifest(self):
        manifest = {"id": "aio-local", "resources": [{"name": "stream"}]}
        response = type("Response", (), {
            "__enter__": lambda self: self,
            "__exit__": lambda self, *args: None,
            "read": lambda self: json.dumps(manifest).encode(),
        })()
        with patch("urllib.request.urlopen", return_value=response):
            status, body, _ = self.request("/manifest-ready")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body.decode())["manifest"], "aio-local")

    def test_server_address_normalization(self):
        for value, expected in (("nas", "http://nas:3000"), ("172.20.0.2", "http://172.20.0.2:3000"),
                                ("172.200.1.2", "https://172.200.1.2"), ("[::1]", "http://[::1]:3000"),
                                ("https://example.org:3000/aio/", "https://example.org:3000/aio")):
            with self.subTest(value=value):
                self.assertEqual(portal.normalize_base_url(value), expected)

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        for name in ("index.html", "dashboard.html"):
            (cls.root / name).write_text("portal page")
        (cls.root / ".env").write_text("TEST_SECRET=hidden\n")
        (cls.root / "assets").mkdir()
        (cls.root / "assets/test.png").write_bytes(b"image")
        (cls.root / "data").mkdir()
        (cls.root / "data/db.sqlite").write_text("private database")
        cls.settings = patch.multiple(portal, WEB_ROOT=str(cls.root),
                                     ENV_PATH=str(cls.root / ".env"),
                                     ENV_EXAMPLE_PATH=str(cls.root / ".env.example"))
        cls.settings.start()
        cls.auth_env = patch.dict(os.environ, {"ADDON_PASSWORD": "test-password", "PORTAL_AUTH_REQUIRED": "true"})
        cls.auth_env.start()
        cls.server = portal.ThreadingHTTPServer(("127.0.0.1", 0), portal.AppliancePortalHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.settings.stop()
        cls.auth_env.stop()
        cls.temp.cleanup()

    def setUp(self):
        portal.AUTH_FAILURES.clear()

    def request(self, path, method="GET", data=None, auth=False, headers=None):
        request_headers = dict(headers or {})
        if auth:
            request_headers["Authorization"] = "Basic " + base64.b64encode(b"admin:test-password").decode()
        if isinstance(data, (bytes, str)):
            body = data.encode("utf-8") if isinstance(data, str) else data
        else:
            body = json.dumps(data) if data is not None else None
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        connection.request(method, path, body, request_headers)
        try:
            response = connection.getresponse()
            result = response.status, response.read(), dict(response.getheaders())
        except ConnectionAbortedError:
            result = (403, b'', {})
        finally:
            connection.close()
        return result

    def test_cache_cleanup_requires_post(self):
        with patch("tools.clean_cache.clean_stack_cache") as clean:
            status, body, _ = self.request("/api/clean-cache",auth=True)
        self.assertEqual(status,405)
        clean.assert_not_called()

    def test_maintenance_does_not_confuse_configured_keys_with_authorization(self):
        with patch.object(portal,"read_saved_env",return_value={"PREMIUMIZE_API_KEY":"fixture-private","TMDB_API_KEY":"fixture-meta"}):
            status,body,_=self.request('/api/maintenance',auth=True)
        payload=json.loads(body)
        self.assertEqual(status,200)
        self.assertTrue(payload['readiness']['providerConfigured'])
        self.assertEqual(payload['readiness']['authorization'],'not_tested')
        self.assertEqual(payload['readiness']['playback'],'not_tested')
        self.assertNotIn(b'fixture-private',body)
        self.assertEqual(self.request('/api/maintenance',auth=False)[0],401)

    def test_public_health_and_pages(self):
        for path in ("/healthz", "/", "/dashboard", "/admin", "/assets/test.png"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path, auth=True)[0], 200)

    def test_private_files_and_directories_blocked(self):
        for path in ("/.env", "/%2eenv", "/data/db.sqlite", "/.git/config", "/", "/templates/"):
            for method in ("GET", "HEAD"):
                if path == "/" and method == "GET":
                    continue
                with self.subTest(path=path, method=method):
                    self.assertEqual(self.request(path, method)[0], 404)

    def test_static_symlink_cannot_expose_env(self):
        link = self.root / "assets/leak.png"
        try:
            link.symlink_to(self.root / ".env")
        except OSError:
            self.skipTest("Symlinks require elevated privileges on Windows")
        try:
            self.assertEqual(self.request("/assets/leak.png")[0], 404)
        finally:
            if link.is_symlink() or link.exists():
                link.unlink()

    def test_api_requires_authentication(self):
        for path in ("/api/env", "/api/status", "/api/logs", "/api/manifest-info", "/api/templates", "/api/setup-status", "/api/integrations"):
            self.assertEqual(self.request(path)[0], 401)
        self.assertEqual(self.request("/api/save", "POST", {})[0], 401)
        self.assertEqual(self.request("/api/setup", "POST")[0], 401)

    def test_open_portal_access_when_auth_disabled(self):
        # When PORTAL_AUTH_REQUIRED is false (default), portal opens freely without passwords or 503 errors
        with patch.dict(os.environ, {"PORTAL_AUTH_REQUIRED": "false", "ADDON_PASSWORD": ""}):
            with patch.object(portal.subprocess, "run", side_effect=OSError()), patch.object(portal.urllib.request, "urlopen", side_effect=OSError()):
                for path in ("/", "/dashboard", "/admin", "/api/env", "/api/status"):
                    status, body, _ = self.request(path, auth=False)
                    self.assertEqual(status, 200, f"Path {path} failed with status {status}")
                status, _, _ = self.request("/api/save-env", "POST", {"BASE_URL": "http://127.0.0.1:3001"}, auth=False)
                self.assertEqual(status, 200)

    def test_setup_launch_status(self):
        with patch.object(portal, "launch_setup", return_value=True):
            self.assertEqual(self.request("/api/setup", "POST", auth=True)[0], 202)
        with patch.object(portal, "launch_setup", return_value=False):
            self.assertEqual(self.request("/api/setup", "POST", auth=True)[0], 409)

    def test_export_requires_valid_manifest(self):
        with patch.object(portal.urllib.request, "urlopen", side_effect=OSError("offline")):
            self.assertEqual(self.request("/api/export-manifest", auth=True)[0], 503)

    def test_manifest_info_is_read_only(self):
        with patch.object(portal.subprocess, "Popen") as process, patch.object(portal.urllib.request, "urlopen") as network:
            self.assertEqual(self.request("/api/manifest-info", auth=True)[0], 200)
            process.assert_not_called()
            network.assert_not_called()

    def test_configured_controller_handles_setup_and_status(self):
        with patch.dict(portal.os.environ, {"COMPOSE_CONTROL_SOCKET": "/test/socket"}), patch.object(portal, "control_request", return_value=(202, {"success": True})) as control:
            self.assertTrue(portal.launch_setup())
            control.assert_called_with("POST", "/apply")
        with patch.dict(portal.os.environ, {"COMPOSE_CONTROL_SOCKET": "/test/socket"}), patch.object(portal, "control_request", return_value=(200, {"status": "running"})):
            self.assertEqual(portal.setup_snapshot()["status"], "running")

    def test_unavailable_controller_returns_service_unavailable(self):
        with patch.dict(portal.os.environ, {"COMPOSE_CONTROL_SOCKET": "/test/socket"}), patch.object(portal, "control_request", side_effect=OSError("offline")):
            self.assertEqual(self.request("/api/setup-status", auth=True)[0], 503)
            self.assertEqual(self.request("/api/setup", "POST", auth=True)[0], 503)

    def test_public_addresses_follow_base_without_overwriting_custom_hosts(self):
        portal.save_env_updates({"BASE_URL": "http://oldnas:3000", "KITSU_URL": "http://oldnas:7005", "NUVIO_ORIGIN": "https://player.example.org"})
        self.assertEqual(self.request("/api/save", "POST", {"BASE_URL": "http://newnas:3000"}, True)[0], 200)
        content = (self.root / ".env").read_text()
        self.assertIn("KITSU_URL=http://newnas:7005", content)
        self.assertIn("NUVIO_ORIGIN=https://player.example.org", content)

    def test_authorized_templates(self):
        self.assertEqual(self.request("/api/templates", auth=True)[0], 200)

    def test_page_prompts_for_login(self):
        status, _, headers = self.request("/")
        self.assertEqual(status, 401)
        self.assertIn("WWW-Authenticate", headers)

    def test_env_read_skips_service_probes(self):
        with patch.object(portal.subprocess, "run") as command, patch.object(portal.urllib.request, "urlopen") as probe:
            self.assertEqual(self.request("/api/env", auth=True)[0], 200)
            command.assert_not_called()
            probe.assert_not_called()

    def test_saved_credentials_are_never_returned_to_browser(self):
        portal.save_env_updates({"TEST_SECRET": "private-test-value", "PREMIUMIZE_API_KEY": "private-provider-key", "SIMKL_CLIENT_ID": "simkl-id-value", "ANILIST_TOKEN": "anilist-token-value"})
        for path in ("/api/env", "/api/status"):
            with patch.object(portal.subprocess, "run", side_effect=OSError()), patch.object(portal.urllib.request, "urlopen", side_effect=OSError()):
                status, body, _ = self.request(path, auth=True)
            self.assertEqual(status, 200)
            self.assertNotIn(b"private-test-value", body)
            self.assertNotIn(b"private-provider-key", body)
            self.assertNotIn(b"simkl-id-value", body)
            self.assertNotIn(b"anilist-token-value", body)
            result = json.loads(body)
            state = result if path == "/api/env" else result["env"]
            self.assertIn("PREMIUMIZE_API_KEY", state["configuredKeys"])
            self.assertIn("SIMKL_CLIENT_ID", state["configuredKeys"])
            self.assertIn("ANILIST_TOKEN", state["configuredKeys"])
            self.assertNotIn("PREMIUMIZE_API_KEY", state)
            self.assertNotIn("SIMKL_CLIENT_ID", state)
            self.assertNotIn("ANILIST_TOKEN", state)

    def test_cross_origin_write_blocked(self):
        self.assertEqual(self.request("/api/save", "POST", {}, True,
                                      {"Origin": "https://untrusted.example"})[0], 403)

    def test_authentication_rate_limit(self):
        portal.AUTH_FAILURES.clear()
        for _ in range(portal.AUTH_FAILURE_LIMIT):
            self.assertEqual(self.request("/api/status")[0], 401)
        self.assertEqual(self.request("/api/status")[0], 429)
        portal.AUTH_FAILURES.clear()

    def test_no_wildcard_cors_or_cache(self):
        headers = self.request("/healthz")[2]
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_assets_cache_control_headers(self):
        headers = self.request("/assets/test.png")[2]
        self.assertEqual(headers.get("Cache-Control"), "no-cache, no-store, must-revalidate")

    def test_invalid_config_does_not_change_file(self):
        before = (self.root / ".env").read_bytes()
        for value in ([1], {"bad-key": "x"}, {"KEY": "x\nINJECTED=yes"},
                      {"KEY": {"nested": 1}}, {"KEY": "${HOST_SECRET}"}):
            self.assertEqual(self.request("/api/save", "POST", value, True)[0], 400)
            self.assertEqual((self.root / ".env").read_bytes(), before)

    def test_save_preserves_existing_settings_without_spawning_processes(self):
        with patch.object(portal.subprocess, "Popen") as launch:
            status, body, _ = self.request("/api/save", "POST", {"TMDB_API_KEY": "test"}, True)
            self.assertEqual(status, 200)
            self.assertFalse(json.loads(body)["applied"])
            launch.assert_not_called()
        content = (self.root / ".env").read_text()
        self.assertIn("TEST_SECRET=hidden", content)
        self.assertEqual(content.count("TMDB_API_KEY="), 1)

    def test_concurrent_saves_retain_all_keys(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda number: portal.save_env_updates({f"CONCURRENT_{number}": str(number)}), range(20)))
        content = (self.root / ".env").read_text()
        for number in range(20):
            self.assertIn(f"CONCURRENT_{number}={number}\n", content)

    def test_derive_aiometadata_host(self):
        self.assertEqual(portal.derive_aiometadata_host("http://localhost:3000"), "http://localhost:4005")
        self.assertEqual(portal.derive_aiometadata_host("http://192.168.1.50:3000"), "http://192.168.1.50:4005")
        self.assertEqual(portal.derive_aiometadata_host("https://aio.example.com"), "https://aiometa.example.com")
        self.assertEqual(portal.derive_aiometadata_host("https://stream.example.com"), "https://aiometa.stream.example.com")
        self.assertEqual(portal.derive_aiometadata_host("https://aio.example.com", "https://custom-meta.example.com"), "https://custom-meta.example.com")

    def test_manifest_info_includes_aiometadata_subdomain_and_manifest(self):
        portal.save_env_updates({"BASE_URL": "https://aio.example.com", "AIOMETADATA_PROFILE_UUID": "test-uuid-123", "JELLYFIN_ENABLED": "true"})
        status, body, _ = self.request("/api/manifest-info", auth=True)
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data.get("aiometadataHost"), "https://aiometa.example.com")
        self.assertEqual(data.get("aiometadataManifest"), "https://aiometa.example.com/stremio/test-uuid-123/manifest.json")
        self.assertEqual(data["aiometadataConfigure"], "https://aiometa.example.com/stremio/test-uuid-123/configure")
        self.assertEqual(data["aiostreamsDashboard"], "https://aio.example.com/admin")
        self.assertEqual(data["jellyfinServer"], "https://aio.example.com/jellyfin")
        self.assertEqual(data["jellyfinWebPlayer"], "https://aio.example.com/jellyfin/web")
        self.assertEqual(data["jellyfinQuickConnect"], "https://aio.example.com/jellyfin/quickconnect")
        self.assertEqual(data["officialWebPlayer"], "https://web.aiostreams.org")
        self.assertEqual(data["watchUrl"], "/watch/")
        self.assertTrue(data["jellyfinEnabled"])
        self.assertNotIn("addonPassword", data)

        portal.save_env_updates({"JELLYFIN_ENABLED": "false"})
        status, body, _ = self.request("/api/manifest-info", auth=True)
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertFalse(data["jellyfinEnabled"])

        # Auto-login URL when UUID and encrypted password are configured
        portal.save_env_updates({
            "JELLYFIN_ENABLED": "true",
            "DEFAULT_AIO_UUID": "test-user-uuid",
            "DEFAULT_AIO_ENCRYPTED_PASSWORD": "enc-pass-123"
        })
        status, body, headers = self.request("/api/manifest-info", auth=True)
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["jellyfinServer"], "https://aio.example.com/jellyfin/test-user-uuid/enc-pass-123")
        self.assertEqual(data["jellyfinWebPlayer"], "https://aio.example.com/jellyfin/test-user-uuid/enc-pass-123/web/")
        self.assertIn("frame-src 'self' http: https: data: blob:;", headers.get("Content-Security-Policy", ""))

    def test_admin_password_saved_as_write_only_setting(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("ADDON_PASSWORD=test-password\n", encoding="utf-8")
            with patch.object(portal, "ENV_PATH", str(env_path)), patch.dict(os.environ, {}):
                status, _, _ = self.request("/api/save-env", "POST", {"ADDON_PASSWORD": "bad,password"}, auth=True)
                self.assertEqual(status, 400)
                status, _, _ = self.request("/api/save-env", "POST", {"ADDON_PASSWORD": "fixture-new-password"}, auth=True)
                self.assertEqual(status, 200)
                self.assertEqual(portal.read_saved_env()["AIO_PASSWORD_PREVIOUS"], "test-password")
                auth = "Basic " + base64.b64encode(b"admin:fixture-new-password").decode()
                status, body, _ = self.request("/api/manifest-info", headers={"Authorization": auth})
                self.assertEqual(status, 200)
                self.assertNotIn(b"fixture-new-password", body)
                self.assertNotIn(b"test-password", body)

    def test_dashboard_links_on_fresh_lan_install(self):
        with tempfile.TemporaryDirectory() as temp:
            env_path = Path(temp) / ".env"
            env_path.write_text("BASE_URL=https://aio.yourdomain.com\nPORT_AIOSTREAMS=13001\n", encoding="utf-8")
            with patch.object(portal, "ENV_PATH", str(env_path)):
                status, body, _ = self.request("/api/manifest-info", auth=True, headers={"Host": "192.168.1.20:8088"})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["aiostreamsConfigure"], "http://192.168.1.20:13001/configure")
        self.assertEqual(data["aiometadataConfigure"], "http://192.168.1.20:4005/configure")
        self.assertIsNone(data["aiometadataManifest"])

    def test_service_ui_links_respect_port_and_proxy_overrides(self):
        env = {"PORT_SUBSENSE": "13100", "UI_PROWLARR_URL": "https://prowlarr.example.net"}
        self.assertEqual(portal.service_ui_url("subsense", "nas.lan:8088", env), "http://nas.lan:13100/configure")
        self.assertEqual(portal.service_ui_url("prowlarr", "nas.lan:8088", env), "https://prowlarr.example.net")
        self.assertIsNone(portal.service_ui_url("zilean", "nas.lan:8088", env))

    def test_failed_replace_preserves_original(self):
        before = (self.root / ".env").read_bytes()
        with patch.object(portal.os, "replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                portal.save_env_updates({"DISK_TEST": "value"})
        self.assertEqual((self.root / ".env").read_bytes(), before)
        self.assertEqual(list(self.root.glob(".env-*")), [])

    def test_backup_endpoint_requires_auth_and_serves_archive(self):
        self.assertEqual(self.request("/api/backup", auth=False)[0], 401)
        backup_dir = self.root / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        fake_archive = backup_dir / "aio-backup-20261101-000000.tar.gz"
        fake_archive.write_bytes(b"\x1f\x8b\x08mock_gzip_data")
        with patch("tools.backup.create_backup", return_value=fake_archive) as create:
            status, body, headers = self.request("/api/backup", auth=True)
        create.assert_called_once()
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/gzip")
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(body, b"\x1f\x8b\x08mock_gzip_data")

    def test_export_aiometadata_serves_json(self):
        status, body, headers = self.request("/api/export-aiometadata", auth=True)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertIn("aio-local-aiometadata-profile.json", headers["Content-Disposition"])
        data = json.loads(body)
        self.assertTrue(isinstance(data, dict))

    def test_aiometadata_template_saved_and_returned_in_env(self):
        status, body, _ = self.request(
            "/api/save-env", "POST",
            {"AIOMETADATA_TEMPLATE": "tamtaro-aiometadata-without-anime.json"},
            auth=True, headers={"Content-Type": "application/json"}
        )
        self.assertEqual(status, 200)
        status, body, _ = self.request("/api/env", auth=True)
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data.get("AIOMETADATA_TEMPLATE"), "tamtaro-aiometadata-without-anime.json")

    def test_aiometadata_service_ui_url_resolves_profile(self):
        env_with_uuid = {"PORT_AIOMETADATA": "4005", "AIOMETADATA_PROFILE_UUID": "test-prof-uuid-456"}
        self.assertEqual(
            portal.service_ui_url("aiometadata", "localhost:8088", env_with_uuid),
            "http://localhost:4005/stremio/test-prof-uuid-456/configure"
        )
        env_no_uuid = {"PORT_AIOMETADATA": "4005"}
        self.assertEqual(
            portal.service_ui_url("aiometadata", "localhost:8088", env_no_uuid),
            "http://localhost:4005/configure"
        )

    def test_aiometadata_apply_template_endpoint(self):
        # 1. Invalid template filename rejected
        status, _, _ = self.request(
            "/api/aiometadata/apply-template", "POST",
            {"template": "../../malicious.json"}, auth=True
        )
        self.assertEqual(status, 400)

        # 2. Valid template application with mocked AIOMetadata response
        mock_aiom_resp = io.BytesIO(json.dumps({"success": True, "userUUID": "applied-uuid-789"}).encode("utf-8"))
        mock_aiom_resp.status = 200
        prev_uuid = os.environ.get("AIOMETADATA_PROFILE_UUID")
        try:
            with patch("urllib.request.urlopen", return_value=mock_aiom_resp):
                status, body, _ = self.request(
                    "/api/aiometadata/apply-template", "POST",
                    {"template": "grabberhawk-aiometadata-config.json"}, auth=True
                )
                self.assertEqual(status, 200)
                data = json.loads(body)
                self.assertTrue(data.get("success"))
                self.assertEqual(data.get("uuid"), "applied-uuid-789")
                self.assertIn("/stremio/applied-uuid-789/configure", data.get("configureUrl"))
        finally:
            if prev_uuid:
                portal.save_env_updates({"AIOMETADATA_PROFILE_UUID": prev_uuid})
            else:
                os.environ.pop("AIOMETADATA_PROFILE_UUID", None)

    def test_metadata_update_preserves_identity_and_accounts(self):
        saved = {"AIOMETADATA_PROFILE_UUID": "existing-profile", "TMDB_API_KEY": "fixture"}
        loaded = {"success": True, "config": {"configVersion": 42,
                  "apiKeys": {"traktTokenId": "saved-link"}, "jellyfinUsers": [{"id": "mine"}]}}
        with patch.object(portal, "read_saved_env", return_value=saved), \
             patch.object(portal, "request_metadata", side_effect=[loaded, {"success": True, "userUUID": "existing-profile"}]) as upstream, \
             patch.object(portal, "save_env_updates") as persist:
            status, body, _ = self.request("/api/aiometadata/apply-template", "POST",
                {"template": "tamtaro-aiometadata-with-anime.json"}, auth=True)
        self.assertEqual(status, 200)
        self.assertEqual(upstream.call_count, 2)
        update = upstream.call_args
        self.assertTrue(update.args[0].endswith("/update/existing-profile"))
        self.assertEqual(update.args[2], "PUT")
        self.assertEqual(update.args[1]["baseVersion"], 42)
        self.assertEqual(update.args[1]["config"]["apiKeys"]["traktTokenId"], "saved-link")
        self.assertEqual(update.args[1]["config"]["jellyfinUsers"], [{"id": "mine"}])
        persist.assert_called_once()

    def test_metadata_failed_update_never_creates_replacement_profile(self):
        from tools.metadata_config import MetadataRequestError
        for failure in (400, 401, 409, 504):
            with self.subTest(failure=failure), \
                 patch.object(portal, "read_saved_env", return_value={"AIOMETADATA_PROFILE_UUID": "existing-profile"}), \
                 patch.object(portal, "request_metadata", side_effect=[
                     {"success": True, "config": {}}, MetadataRequestError(failure)]) as upstream, \
                 patch.object(portal, "save_env_updates") as persist:
                status, body, _ = self.request("/api/aiometadata/apply-template", "POST",
                    {"template": "tamtaro-aiometadata-with-anime.json"}, auth=True)
                self.assertEqual(status, 422 if failure == 401 else failure)
                self.assertEqual(json.loads(body)["upstreamStatus"], failure)
                self.assertEqual(upstream.call_count, 2)
                persist.assert_not_called()

    def test_metadata_failed_load_never_overwrites_profile(self):
        from tools.metadata_config import MetadataRequestError
        with patch.object(portal, "read_saved_env", return_value={"AIOMETADATA_PROFILE_UUID": "existing-profile"}), \
             patch.object(portal, "request_metadata", side_effect=MetadataRequestError(401)) as upstream, \
             patch.object(portal, "save_env_updates") as persist:
            status, body, _ = self.request("/api/aiometadata/apply-template", "POST", {}, auth=True)
        self.assertEqual(status, 422)
        self.assertEqual(upstream.call_count, 1)
        persist.assert_not_called()

    def test_aniskip_endpoint_cors_and_skip_times(self):
        status, _, headers = self.request("/api/aniskip?id=tt9335498&season=1&episode=1", method="OPTIONS")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "*")

        with patch.object(portal, "resolve_mal_id", return_value=38000), \
             patch.object(portal, "get_aniskip_times", return_value={
                 "found": True,
                 "results": [{"skipType": "op", "interval": {"startTime": 5, "endTime": 95}}]
             }):
            status, body, headers = self.request("/api/aniskip?id=tt9335498:1:1", method="GET")
            self.assertEqual(status, 200)
            self.assertEqual(headers.get("Access-Control-Allow-Origin"), "*")
            data = json.loads(body)
            self.assertTrue(data.get("found"))
            self.assertEqual(data.get("malId"), 38000)
            self.assertEqual(len(data.get("results")), 1)

    def test_webhook_test_endpoint(self):
        with patch.object(portal, "dispatch_webhook_notification", return_value=(True, "Delivered")):
            status, body, _ = self.request("/api/webhook-test", "POST", {"url": "https://discord.com/api/webhooks/mock"}, auth=True)
            self.assertEqual(status, 200)
            data = json.loads(body)
            self.assertTrue(data.get("success"))

    def test_health_stats_endpoint(self):
        self.assertEqual(self.request("/api/health-stats", auth=False)[0], 401)
        with patch("tools.resources.get_stack_resources", return_value={"success": True, "container_count": 22, "containers": []}), \
             patch("tools.backup.get_backup_telemetry", return_value={"count": 2, "total_size_mb": 15.4}), \
             patch("tools.watchdog.get_watchdog_telemetry", return_value={"status": "active", "healthy_count": 14, "total_services": 14, "last_probe": "2026-11-09T00:00:00Z", "zilean_stats": {"healthy": True}, "indexer_health": {"healthy_indexers": 4}}), \
             patch("tools.watchdog.get_zilean_stats", return_value={"healthy": True, "engine": "DMM Hash Search (Active)", "latency_ms": 12.0}), \
             patch("tools.watchdog.check_prowlarr_indexers", return_value={"total_indexers": 4, "healthy_indexers": 4, "degraded_indexers": []}):
            status, body, _ = self.request("/api/health-stats", auth=True)
            self.assertEqual(status, 200)
            data = json.loads(body)
            self.assertTrue(data.get("success"))
            self.assertEqual(data["resources"]["container_count"], 22)
            self.assertEqual(data["backup"]["count"], 2)
            self.assertEqual(data["watchdog"]["healthy_count"], 14)

    def test_watchdog_endpoint(self):
        self.assertEqual(self.request("/api/watchdog", auth=False)[0], 401)
        with patch("tools.watchdog.get_watchdog_telemetry", return_value={"status": "active", "overall": "healthy"}):
            status, body, _ = self.request("/api/watchdog", auth=True)
            self.assertEqual(status, 200)
            data = json.loads(body)
            self.assertEqual(data.get("overall"), "healthy")

        with patch("tools.watchdog.probe_all_services", return_value={"overall_status": "healthy", "healthy_count": 14, "total_services": 14}):
            status, body, _ = self.request("/api/watchdog", "POST", auth=True)
            self.assertEqual(status, 200)
            data = json.loads(body)
            self.assertEqual(data.get("healthy_count"), 14)

    def test_backups_list_and_prune_endpoints(self):
        self.assertEqual(self.request("/api/backups", auth=False)[0], 401)
        with patch("tools.backup.get_backup_telemetry", return_value={"count": 3, "total_size_mb": 25.0}):
            status, body, _ = self.request("/api/backups", auth=True)
            self.assertEqual(status, 200)
            data = json.loads(body)
            self.assertEqual(data.get("count"), 3)

        with patch("tools.backup.prune_backups", return_value={"retained": ["a", "b"], "pruned": ["c"], "keep_last": 2}):
            status, body, _ = self.request("/api/backups/prune", "POST", {"keep_last": 2}, auth=True)
            self.assertEqual(status, 200)
            data = json.loads(body)
            self.assertEqual(len(data.get("pruned")), 1)

    def test_zilean_stats_endpoint(self):
        self.assertEqual(self.request("/api/zilean-stats", auth=False)[0], 401)
        with patch("tools.watchdog.get_zilean_stats", return_value={"healthy": True, "engine": "DMM Hash Search (Active)", "latency_ms": 12.0}):
            status, body, _ = self.request("/api/zilean-stats", auth=True)
            self.assertEqual(status, 200)
            data = json.loads(body)
            self.assertTrue(data.get("success"))
            self.assertTrue(data["stats"]["healthy"])

    def test_lumiere_stats_endpoint(self):
        self.assertEqual(self.request("/api/lumiere/stats", auth=False)[0], 401)
        with patch("urllib.request.urlopen") as mock_url:
            mock_resp = unittest.mock.MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = json.dumps({
                "phase": "idle",
                "index": {"ready": True, "generationId": "gen-test-123"}
            }).encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_url.return_value = mock_resp

            status, body, _ = self.request("/api/lumiere/stats", auth=True)
            self.assertEqual(status, 200)
            data = json.loads(body)
            self.assertTrue(data.get("success"))
            self.assertTrue(data.get("ready"))
            self.assertEqual(data.get("phase"), "idle")

    def test_lumiere_search_endpoint(self):
        self.assertEqual(self.request("/api/lumiere/search?q=Inception", auth=False)[0], 401)
        with patch("urllib.request.urlopen") as mock_url:
            mock_resp = unittest.mock.MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = json.dumps({
                "items": [{"tconst": "tt1375666", "primaryTitle": "Inception", "startYear": 2010, "titleType": "movie"}]
            }).encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_url.return_value = mock_resp

            status, body, _ = self.request("/api/lumiere/search?q=Inception", auth=True)
            self.assertEqual(status, 200)
            data = json.loads(body)
            self.assertTrue(data.get("success"))
            self.assertEqual(data.get("query"), "Inception")
            self.assertEqual(len(data.get("items")), 1)
            self.assertEqual(data["items"][0]["imdbId"], "tt1375666")

    def test_public_database_options_can_be_saved_and_returned(self):
        status, body, _ = self.request(
            "/api/save-env", "POST",
            {
                "ENABLE_TORRENTIO": "false",
                "TORRENTIO_URL": "https://torrentio.strem.fun",
                "ENABLE_DMM": "false",
                "ENABLE_REMUXDB": "false",
            },
            auth=True, headers={"Content-Type": "application/json"}
        )
        self.assertEqual(status, 200)
        status, body, _ = self.request("/api/env", auth=True)
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data.get("ENABLE_TORRENTIO"), "false")
        self.assertEqual(data.get("TORRENTIO_URL"), "https://torrentio.strem.fun")
        self.assertEqual(data.get("ENABLE_DMM"), "false")
        self.assertEqual(data.get("ENABLE_REMUXDB"), "false")

        # Test validation of invalid boolean toggle
        status, body, _ = self.request(
            "/api/save-env", "POST",
            {"ENABLE_TORRENTIO": "invalid_val"},
            auth=True, headers={"Content-Type": "application/json"}
        )
        self.assertEqual(status, 400)

        # Test validation of invalid torrentio URL
        status, body, _ = self.request(
            "/api/save-env", "POST",
            {"TORRENTIO_URL": "ftp://bad-url"},
            auth=True, headers={"Content-Type": "application/json"}
        )
        self.assertEqual(status, 400)

    def test_streaming_mode_option_can_be_saved_and_returned(self):
        status, body, _ = self.request(
            "/api/save-env", "POST",
            {
                "STREAMING_MODE": "usenet",
                "USENET_ENABLED": "true",
                "USENET_HOST": "news.usenetserver.com",
                "USENET_PORT": "563",
                "USENET_USER": "testuser",
                "USENET_PASS": "testpass",
                "AIOMETADATA_TEMPLATE": "tamtaro-aiometadata-with-anime.json"
            },
            auth=True, headers={"Content-Type": "application/json"}
        )
        self.assertEqual(status, 200)
        status, body, _ = self.request("/api/env", auth=True)
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data.get("STREAMING_MODE"), "usenet")
        self.assertEqual(data.get("USENET_ENABLED"), "true")
        self.assertEqual(data.get("USENET_HOST"), "news.usenetserver.com")
        self.assertEqual(data.get("AIOMETADATA_TEMPLATE"), "tamtaro-aiometadata-with-anime.json")

        # Test validation of invalid streaming mode
        status, body, _ = self.request(
            "/api/save-env", "POST",
            {"STREAMING_MODE": "invalid_mode"},
            auth=True, headers={"Content-Type": "application/json"}
        )
        self.assertEqual(status, 400)


    def test_custom_ports_in_status_and_env(self):
        self.enterContext(patch.dict(os.environ))
        env_path = self.root / ".env"
        self.addCleanup(env_path.write_bytes, env_path.read_bytes())
        status, body, _ = self.request(
            "/api/save-env", "POST",
            {"PORT_AIOSTREAMS": "18082", "PORT_AIOMETADATA": "18085"},
            auth=True, headers={"Content-Type": "application/json"}
        )
        self.assertEqual(status, 200)

        status, body, _ = self.request("/api/env", auth=True)
        self.assertEqual(status, 200)
        env_data = json.loads(body)
        self.assertEqual(env_data.get("PORT_AIOSTREAMS"), "18082")
        self.assertEqual(env_data.get("PORT_AIOMETADATA"), "18085")
        self.assertEqual(env_data.get("ports", {}).get("aiostreams"), 18082)
        self.assertEqual(env_data.get("ports", {}).get("aiometadata"), 18085)

        with patch.object(portal.subprocess, "run", side_effect=OSError()), patch.object(portal.urllib.request, "urlopen", side_effect=OSError()):
            status, body, _ = self.request("/api/status", auth=True)
        self.assertEqual(status, 200)
        status_data = json.loads(body)
        self.assertEqual(status_data.get("ports", {}).get("aiostreams"), 18082)
        self.assertEqual(status_data.get("ports", {}).get("aiometadata"), 18085)

    def test_validate_provider_with_saved_key(self):
        portal.save_env_updates({"REALDEBRID_API_KEY": "saved-rd-key"})
        with patch.object(portal.urllib.request, "urlopen") as mock_url:
            mock_resp = unittest.mock.MagicMock()
            mock_resp.read.return_value = b'{"id": 1234, "username": "testuser"}'
            mock_resp.__enter__.return_value = mock_resp
            mock_url.return_value = mock_resp

            status, body, _ = self.request(
                "/api/validate-provider", "POST",
                {"provider": "realdebrid", "key": "saved"},
                auth=True, headers={"Content-Type": "application/json"}
            )
            self.assertEqual(status, 200)
            data = json.loads(body)
            self.assertEqual(data.get("status"), "valid")

        # Test saved Usenet NNTP validation
        portal.save_env_updates({
            "USENET_HOST": "news.customserver.com",
            "USENET_PORT": "563",
            "USENET_USER": "nntpuser",
            "USENET_PASS": "nntppass",
            "USENET_SSL": "true"
        })
        with patch.object(portal, "test_nntp_login", return_value=(True, "Authentication accepted")):
            status, body, _ = self.request(
                "/api/validate-provider", "POST",
                {"provider": "usenet"},
                auth=True, headers={"Content-Type": "application/json"}
            )
            self.assertEqual(status, 200)
            data = json.loads(body)
            self.assertEqual(data.get("status"), "valid")
            self.assertIn("news.customserver.com", data.get("detail", ""))

        # Test /api/test-provider endpoint with NZB provider
        portal.save_env_updates({
            "NZB_INDEXER_URL": "https://api.althub.co.za",
            "NZB_INDEXER_API_KEY": "dummy_nzb_key"
        })
        with patch.object(portal.urllib.request, "urlopen") as mock_url:
            mock_resp = unittest.mock.MagicMock()
            mock_resp.read.return_value = b"<caps><searching></searching></caps>"
            mock_resp.status = 200
            mock_resp.__enter__.return_value = mock_resp
            mock_url.return_value = mock_resp

            status, body, _ = self.request(
                "/api/test-provider", "POST",
                {"provider": "nzb"},
                auth=True, headers={"Content-Type": "application/json"}
            )
            self.assertEqual(status, 200)
            data = json.loads(body)
            self.assertEqual(data.get("status"), "valid")
            self.assertIn("api.althub.co.za", data.get("detail", ""))

        # Test usenet playback failure troubleshooting string
        with patch.object(portal, "read_saved_env", return_value={"USENET_ENABLED": "true", "USENET_HOST": "news.test", "USENET_USER": "u", "USENET_PASS": "p"}), \
             patch.object(portal, "test_nntp_login", return_value=(True, "Authentication accepted")), \
             patch.object(portal, "validate_provider", return_value={"status": "valid", "detail": ""}), \
             patch.object(portal.os.path, "isfile", return_value=True), \
             patch.object(portal.Path, "read_text", return_value='{"uuid":"fixture","encrypted_password":"fixture"}'), \
             patch.object(portal.urllib.request, "urlopen") as mock_url:
            mock_resp = unittest.mock.MagicMock()
            mock_resp.read.return_value = b'{"streams": []}'
            mock_resp.headers = {"Content-Type": "application/json"}
            mock_resp.__enter__.return_value = mock_resp
            mock_url.return_value = mock_resp
            pb_result = portal.run_playback_test(mode="usenet")
            self.assertFalse(pb_result["success"])
            self.assertEqual(
                pb_result["troubleshoot"],
                "Check your NZB indexer URL and API key configuration in Portal settings / AIOStreams direct Newznab presets."
            )

    def test_diagnostics_export_endpoint(self):
        with patch.object(portal, "probe_integration", return_value={
            "name": "Prowlarr", "group": "Indexers", "reachable": True,
        }):
            status, body, headers = self.request("/api/diagnostics/export", "GET", auth=True)
            self.assertEqual(status, 200)
            self.assertIn("AIO LOCAL · SANITIZED DIAGNOSTIC REPORT", body.decode("utf-8"))
            self.assertIn("READINESS CHECKS", body.decode("utf-8"))
            hdr_map = {k.lower(): v for k, v in headers.items()}
            self.assertIn("attachment", hdr_map.get("content-disposition", "").lower())

    def test_playback_is_blocked_on_server_before_provider_calls(self):
        for state in ("running", "failed"):
            with self.subTest(state=state), patch.object(portal, "setup_snapshot", return_value={"status": state}), patch.object(portal, "run_playback_test") as run:
                status, body, _ = self.request("/api/test-playback", "POST", {}, auth=True)
                self.assertEqual(status, 409)
                self.assertFalse(json.loads(body)["readiness"]["ready"])
                run.assert_not_called()

    def test_playback_rejects_html_from_stream_origin(self):
        streams = MagicMock(status=200)
        streams.__enter__.return_value = streams
        streams.read.return_value = b'{"streams":[{"url":"https://media.example/video"}]}'
        origin = MagicMock(status=200)
        origin.__enter__.return_value = origin
        origin.headers = Message()
        origin.headers["Content-Type"] = "text/html; charset=utf-8"
        origin.read.return_value = b"<html>Please sign in</html>"
        with patch.object(portal, "read_saved_env", return_value={"PREMIUMIZE_API_KEY": "fixture"}), \
             patch.object(portal, "validate_provider", return_value={"status": "valid", "detail": ""}), \
             patch.object(portal.os.path, "isfile", return_value=True), \
             patch.object(portal.Path, "read_text", return_value='{"uuid":"fixture","encrypted_password":"fixture"}'), \
             patch.object(portal.urllib.request, "urlopen", side_effect=[streams, origin]):
            result = portal.run_playback_test()
        self.assertFalse(result["success"])
        self.assertEqual(result["steps_dict"]["media_read"]["status"], "fail")
        self.assertIsNone(result["stream_url"])

    def test_readiness_requires_stream_manifest_and_enabled_services(self):
        from unittest.mock import MagicMock
        response = MagicMock()
        response.__enter__.return_value = response
        with patch.object(portal, "setup_snapshot", return_value={"status": "complete"}), patch.object(portal, "read_saved_env", return_value={"COMPOSE_PROFILES": "core"}), patch.object(portal, "probe_integration", return_value={"name": "Prowlarr", "reachable": True, "enabled": True}) as probe, patch.object(portal.urllib.request, "urlopen", return_value=response):
            response.read.return_value = b'{"id":"fixture","resources":["stream"]}'
            self.assertTrue(portal.playback_readiness()["ready"])
            probe.return_value = {"name": "Optional", "reachable": False, "enabled": False}
            self.assertTrue(portal.playback_readiness()["ready"])
            probe.return_value = {"name": "Prowlarr", "reachable": False, "enabled": True}
            self.assertFalse(portal.playback_readiness()["ready"])
            probe.return_value = {"name": "SubSense", "reachable": False, "enabled": True}
            self.assertTrue(portal.playback_readiness()["ready"])
            probe.return_value = {"name": "Prowlarr", "reachable": True, "enabled": True}
            response.read.return_value = b'{"id":"fixture","resources":["catalog"]}'
            self.assertFalse(portal.playback_readiness()["ready"])
            response.read.return_value = b'not json'
            self.assertFalse(portal.playback_readiness()["ready"])

    def test_readiness_blocks_controller_loss_and_setup_restart(self):
        with patch.object(portal, "setup_snapshot", side_effect=OSError("private error")):
            result = portal.playback_readiness()
            self.assertFalse(result["ready"])
            self.assertNotIn("private error", json.dumps(result))
        with patch.object(portal, "setup_snapshot", side_effect=[{"status": "complete"}, {"status": "running"}]), patch.object(portal, "probe_integration", return_value={"name": "AIOStreams", "reachable": True}), patch.object(portal.urllib.request, "urlopen", side_effect=OSError()):
            self.assertFalse(portal.playback_readiness()["ready"])

    def test_core_profile_marks_excluded_services_off(self):
        with patch.object(portal, "read_saved_env", return_value={"COMPOSE_PROFILES": "core"}), patch("socket.create_connection") as connect:
            for service, port, group in [
                ("anime-kitsu", 7000, "Metadata"),
                ("jikan-api", 8080, "Metadata"),
            ]:
                result = portal.probe_integration((service.title(), service, port, group))
                self.assertFalse(result["enabled"])
            connect.assert_not_called()

        with patch.object(portal, "read_saved_env", return_value={"COMPOSE_PROFILES": "anime"}), patch("socket.create_connection"):
            result = portal.probe_integration(("Anime Kitsu", "anime-kitsu", 7000, "Metadata"))
            self.assertTrue(result["enabled"])
            result = portal.probe_integration(("Jikan API", "jikan-api", 8080, "Metadata"))
            self.assertTrue(result["enabled"])
            result = portal.probe_integration(("Zilean", "zilean", 8181, "Indexers"))
            self.assertFalse(result["enabled"])

    def test_legacy_profiles_probe_and_normalization(self):
        # 1. Legacy 'scrapers' profile enables core services and anime-kitsu, excludes jikan-api
        with patch.object(portal, "read_saved_env", return_value={"COMPOSE_PROFILES": "scrapers"}), patch("socket.create_connection"):
            res_prowlarr = portal.probe_integration(("Prowlarr", "prowlarr", 9696, "Indexers"))
            self.assertTrue(res_prowlarr["enabled"])
            res_kitsu = portal.probe_integration(("Anime Kitsu", "anime-kitsu", 7000, "Metadata"))
            self.assertTrue(res_kitsu["enabled"])
            res_jikan = portal.probe_integration(("Jikan API", "jikan-api", 8080, "Metadata"))
            self.assertFalse(res_jikan["enabled"])

        # 2. Legacy 'anime-db' profile enables anime-kitsu and jikan-api, excludes core services
        with patch.object(portal, "read_saved_env", return_value={"COMPOSE_PROFILES": "anime-db"}), patch("socket.create_connection"):
            res_kitsu = portal.probe_integration(("Anime Kitsu", "anime-kitsu", 7000, "Metadata"))
            self.assertTrue(res_kitsu["enabled"])
            res_jikan = portal.probe_integration(("Jikan API", "jikan-api", 8080, "Metadata"))
            self.assertTrue(res_jikan["enabled"])
            res_prowlarr = portal.probe_integration(("Prowlarr", "prowlarr", 9696, "Indexers"))
            self.assertFalse(res_prowlarr["enabled"])

        # 3. Empty COMPOSE_PROFILES defaults to core and all (enabling all services with 'core' or 'all')
        with patch.object(portal, "read_saved_env", return_value={}), patch("socket.create_connection"):
            res_prowlarr = portal.probe_integration(("Prowlarr", "prowlarr", 9696, "Indexers"))
            self.assertTrue(res_prowlarr["enabled"])
            res_kitsu = portal.probe_integration(("Anime Kitsu", "anime-kitsu", 7000, "Metadata"))
            self.assertTrue(res_kitsu["enabled"])

        # 4. /api/save-env allows legacy profiles and normalizes them on save
        with patch.object(portal, "save_env_updates") as mock_save:
            status, _, _ = self.request("/api/save-env", "POST", {"COMPOSE_PROFILES": "scrapers,anime-db"}, auth=True)
            self.assertEqual(status, 200)
            mock_save.assert_called_once()
            saved_dict = mock_save.call_args[0][0]
            self.assertEqual(saved_dict["COMPOSE_PROFILES"], "core,anime")

        # 5. /api/save-env rejects unsupported profiles
        status, _, _ = self.request("/api/save-env", "POST", {"COMPOSE_PROFILES": "invalid-profile"}, auth=True)
        self.assertEqual(status, 400)

        # 6. /api/config-import allows legacy profiles and normalizes them on save
        with patch.object(portal, "save_env_updates") as mock_save:
            status, _, _ = self.request(
                "/api/config-import", "POST",
                {"format": "aio-local-config-v1", "values": {"COMPOSE_PROFILES": "scrapers"}},
                auth=True, headers={"Content-Type": "application/json"}
            )
            self.assertEqual(status, 200)
            mock_save.assert_called_once()
            self.assertEqual(mock_save.call_args[0][0]["COMPOSE_PROFILES"], "core")

    def test_scrapers_profile_enables_all_core_services_in_probe_integration(self):
        core_services = [
            ("aiometadata", 4005, "Metadata"),
            ("postersplus", 8000, "Metadata"),
            ("subsense", 3100, "Subtitles"),
            ("lumiere-db", 8000, "Metadata"),
            ("prowlarr", 9696, "Indexers"),
            ("flaresolverr", 8191, "Tools"),
            ("zilean", 8181, "Indexers"),
            ("stremthru", 8080, "Debrid"),
        ]
        with patch.object(portal, "read_saved_env", return_value={"COMPOSE_PROFILES": "scrapers"}), patch("socket.create_connection"):
            for service, port, group in core_services:
                result = portal.probe_integration((service.title(), service, port, group))
                self.assertTrue(result["enabled"], f"{service} should be enabled under COMPOSE_PROFILES='scrapers'")

    @patch.object(portal, "playback_readiness", return_value={"ready": True})
    def test_test_playback_endpoint(self, _readiness):
        # 1. When NNTP login fails
        with patch.object(portal, "test_nntp_login", return_value=(False, "502 Authentication failed")):
            status, body, _ = self.request(
                "/api/test-playback", "POST",
                {"mode": "usenet"},
                auth=True, headers={"Content-Type": "application/json"}
            )
            self.assertEqual(status, 200)
            data = json.loads(body)
            self.assertEqual(data.get("mode"), "usenet")
            self.assertFalse(data.get("overall_success"))
            self.assertIsNotNone(data.get("troubleshoot"))
            self.assertEqual(len(data.get("steps", [])), 3)
            self.assertEqual(data["steps"][0]["name"], "Provider Authentication")
            self.assertEqual(data["steps"][0]["status"], "fail")

        # 2. When credentials are valid and streams resolve
        with patch.object(portal, "test_nntp_login", return_value=(True, "Authentication accepted")):
            with patch.object(portal.urllib.request, "urlopen") as mock_url:
                mock_resp = unittest.mock.MagicMock()
                mock_resp.status = 206
                mock_resp.read.return_value = bytes.fromhex("1a45dfa3") + b"0" * 1020
                mock_resp.__enter__.return_value = mock_resp
                mock_url.return_value = mock_resp

                status, body, _ = self.request(
                    "/api/test-playback", "POST",
                    {"mode": "usenet"},
                    auth=True, headers={"Content-Type": "application/json"}
                )
                self.assertEqual(status, 200)
                data = json.loads(body)
                self.assertEqual(data["steps"][0]["status"], "pass")
                self.assertIn("steps_dict", data)
                self.assertIn("auth", data["steps_dict"])
                self.assertIn("stream_resolution", data["steps_dict"])
                self.assertIn("media_read", data["steps_dict"])

    def test_post_endpoints_reject_non_dict_json_gracefully(self):
        endpoints = [
            "/api/validate-provider",
            "/api/smoke-test",
            "/api/test-playback",
            "/api/webhook-test",
            "/api/backups/prune"
        ]
        for ep in endpoints:
            status, body, _ = self.request(ep, "POST", [1, 2, 3], auth=True, headers={"Content-Type": "application/json"})
            self.assertEqual(status, 400, f"Endpoint {ep} should return 400 for list JSON payload")
            data = json.loads(body)
            self.assertTrue("error" in data or "detail" in data, f"Endpoint {ep} missing error/detail in {data}")

    def test_aniskip_handles_malformed_query_parameters(self):
        # non-integer season, episode, duration should not throw unhandled 500
        status, body, _ = self.request("/api/aniskip?id=tt9335498&season=notanint&episode=bad&duration=invalid")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("found", data)

    def test_status_endpoint_resilient_to_corrupt_port_values(self):
        self.enterContext(patch.dict(os.environ))
        env_path = self.root / ".env"
        self.addCleanup(env_path.write_bytes, env_path.read_bytes())
        portal.save_env_updates({"PORT_AIOSTREAMS": "not-a-port", "PORT_AIOMETADATA": "9999999"})
        with patch.object(portal.subprocess, "run", side_effect=OSError()), patch.object(portal.urllib.request, "urlopen", side_effect=OSError()):
            status, body, _ = self.request("/api/status", auth=True)
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["ports"]["aiostreams"], 3001)
        self.assertEqual(data["ports"]["aiometadata"], 4005)

    def test_validate_provider_headers_and_urls(self):
        with patch.object(portal.urllib.request, "urlopen") as mock_url:
            mock_resp = unittest.mock.MagicMock()
            mock_resp.read.return_value = b'{"success": true}'
            mock_resp.__enter__.return_value = mock_resp
            mock_url.return_value = mock_resp

            # Real-Debrid requires Bearer token in headers
            portal.validate_provider("realdebrid", "rd-secret-token")
            req = mock_url.call_args[0][0]
            self.assertEqual(req.headers.get("Authorization"), "Bearer rd-secret-token")

            # TorBox requires token query param
            portal.validate_provider("torbox", "tb-secret-token")
            req2 = mock_url.call_args[0][0]
            self.assertIn("token=tb-secret-token", req2.full_url)

    def test_validate_provider_nzb_drunkenslug_explicit_url_and_key(self):
        with patch.object(portal.urllib.request, "urlopen") as mock_url:
            mock_resp = unittest.mock.MagicMock()
            mock_resp.read.return_value = b"<caps><searching></searching></caps>"
            mock_resp.status = 200
            mock_resp.__enter__.return_value = mock_resp
            mock_url.return_value = mock_resp

            status, body, _ = self.request(
                "/api/test-provider", "POST",
                {
                    "provider": "nzb",
                    "url": "https://drunkenslug.com",
                    "key": "slug-custom-api-key"
                },
                auth=True, headers={"Content-Type": "application/json"}
            )
            self.assertEqual(status, 200)
            data = json.loads(body)
            self.assertEqual(data.get("status"), "valid")
            self.assertIn("drunkenslug.com", data.get("detail", ""))

            req = mock_url.call_args[0][0]
            self.assertEqual(req.full_url, "https://drunkenslug.com/api?t=caps&apikey=slug-custom-api-key")

            # Also verify if URL already ends in /api/
            status, body, _ = self.request(
                "/api/validate-provider", "POST",
                {
                    "provider": "nzb",
                    "url": "https://drunkenslug.com/api/",
                    "key": "slug-custom-api-key"
                },
                auth=True, headers={"Content-Type": "application/json"}
            )
            self.assertEqual(status, 200)
            data = json.loads(body)
            self.assertEqual(data.get("status"), "valid")
            req2 = mock_url.call_args[0][0]
            self.assertEqual(req2.full_url, "https://drunkenslug.com/api?t=caps&apikey=slug-custom-api-key")

    def test_validate_provider_nzb_drunkenslug_saved_key_via_extra_indexers(self):
        slug_indexer = [
            {"id": "ds-slug-1", "url": "https://drunkenslug.com", "apiKey": "saved-slug-token"}
        ]
        portal.save_env_updates({
            "USENET_EXTRA_INDEXERS_B64": base64.b64encode(json.dumps(slug_indexer).encode()).decode()
        })
        with patch.object(portal.urllib.request, "urlopen") as mock_url:
            mock_resp = unittest.mock.MagicMock()
            mock_resp.read.return_value = b"<caps><server version=\"1.0\"/></caps>"
            mock_resp.status = 200
            mock_resp.__enter__.return_value = mock_resp
            mock_url.return_value = mock_resp

            # 1. Lookup by id with key="saved"
            status, body, _ = self.request(
                "/api/test-provider", "POST",
                {
                    "provider": "nzb",
                    "url": "https://drunkenslug.com",
                    "key": "saved",
                    "id": "ds-slug-1"
                },
                auth=True, headers={"Content-Type": "application/json"}
            )
            self.assertEqual(status, 200)
            data = json.loads(body)
            self.assertEqual(data.get("status"), "valid")
            self.assertIn("drunkenslug.com", data.get("detail", ""))
            req = mock_url.call_args[0][0]
            self.assertEqual(req.full_url, "https://drunkenslug.com/api?t=caps&apikey=saved-slug-token")

            # 2. Lookup by domain without key (key=None or empty) and without id
            status, body, _ = self.request(
                "/api/validate-provider", "POST",
                {
                    "provider": "nzb",
                    "url": "https://drunkenslug.com/api"
                },
                auth=True, headers={"Content-Type": "application/json"}
            )
            self.assertEqual(status, 200)
            data = json.loads(body)
            self.assertEqual(data.get("status"), "valid")
            req2 = mock_url.call_args[0][0]
            self.assertEqual(req2.full_url, "https://drunkenslug.com/api?t=caps&apikey=saved-slug-token")

            # 3. Lookup via USENET_EXTRA_INDEXERS directly in env
            portal.save_env_updates({
                "USENET_EXTRA_INDEXERS_B64": "",
                "USENET_EXTRA_INDEXERS": json.dumps([
                    {"id": "ds-slug-direct", "url": "https://drunkenslug.com", "apiKey": "direct-saved-slug-token"}
                ])
            })
            status, body, _ = self.request(
                "/api/test-provider", "POST",
                {
                    "provider": "nzb",
                    "url": "https://drunkenslug.com",
                    "key": "saved",
                    "indexer_id": "ds-slug-direct"
                },
                auth=True, headers={"Content-Type": "application/json"}
            )
            self.assertEqual(status, 200)
            data = json.loads(body)
            self.assertEqual(data.get("status"), "valid")
            req3 = mock_url.call_args[0][0]
            self.assertEqual(req3.full_url, "https://drunkenslug.com/api?t=caps&apikey=direct-saved-slug-token")

    def test_flaresolverr_status_endpoint(self):
        with patch.object(portal.urllib.request, "urlopen") as mock_url:
            mock_resp = unittest.mock.MagicMock()
            mock_resp.read.return_value = b'{"status": "ok", "version": "v3.3.21"}'
            mock_resp.__enter__.return_value = mock_resp
            mock_url.return_value = mock_resp

            status, body, _ = self.request("/api/flaresolverr", auth=True)
            self.assertEqual(status, 200)
            data = json.loads(body)
            self.assertEqual(data["status"], "online")
            self.assertIn("v3.3.21", data["version"])

        with patch.object(portal.urllib.request, "urlopen", side_effect=OSError("Connection refused")):
            status, body, _ = self.request("/api/flaresolverr", auth=True)
            self.assertEqual(status, 503)
            data = json.loads(body)
            self.assertEqual(data["status"], "offline")

    def test_benchmark_endpoint(self):
        with patch.object(portal.urllib.request, "urlopen") as mock_url:
            mock_resp = unittest.mock.MagicMock()
            mock_resp.read.return_value = b'{"success": true}'
            mock_resp.__enter__.return_value = mock_resp
            mock_url.return_value = mock_resp

            status, body, _ = self.request("/api/benchmark", auth=True)
            self.assertEqual(status, 200)
            data = json.loads(body)
            self.assertTrue(data.get("success"))
            self.assertIn("internal_latencies", data)

    def test_container_logs_endpoint(self):
        with patch.object(portal.subprocess, "run") as mock_sub:
            mock_sub.side_effect = [
                MagicMock(returncode=0, stdout="fixture-project\n"),
                MagicMock(returncode=0, stdout="abcdef012345\n"),
                MagicMock(returncode=0, stdout="SubSense log output https://example.invalid/?api_key=fixture-secret"),
            ]
            status, body, _ = self.request("/api/logs?container=subsense", auth=True)
            self.assertEqual(status, 200)
            data = json.loads(body)
            self.assertEqual(data["container"], "subsense")
            self.assertIn("SubSense log output", data["logs"])
            self.assertNotIn("fixture-secret", data["logs"])
            self.assertIn("label=com.docker.compose.project=fixture-project", mock_sub.call_args_list[1].args[0])
            self.assertIn("label=com.docker.compose.service=subsense", mock_sub.call_args_list[1].args[0])

    def test_container_logs_setup_endpoint(self):
        status, body, _ = self.request("/api/logs?container=setup", auth=True)
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["container"], "setup")
        self.assertIn("logs", data)

    def test_container_logs_tail_clamping(self):
        with patch.object(portal.subprocess, "run") as mock_sub:
            def docker(args, **kwargs):
                output = {"inspect": "fixture-project", "ps": "abcdef012345", "logs": "log output"}
                return MagicMock(returncode=0, stdout=output[args[1]])
            mock_sub.side_effect = docker
            # Test negative tail clamped
            status, _, _ = self.request("/api/logs?container=aiostreams&tail=-10", auth=True)
            self.assertEqual(status, 200)
            self.assertIn("1", mock_sub.call_args[0][0])  # min(1, 200) -> 1

            # Test excessive tail clamped to max limit
            status, _, _ = self.request("/api/logs?container=aiostreams&tail=9999", auth=True)
            self.assertEqual(status, 200)
            self.assertIn("200", mock_sub.call_args[0][0])  # min(500, 200) -> 200

            # Test invalid non-integer tail
            status, _, _ = self.request("/api/logs?container=aiostreams&tail=invalid", auth=True)
            self.assertEqual(status, 200)
            self.assertIn("60", mock_sub.call_args[0][0])

    def test_save_env_port_validation(self):
        # Valid ports
        status, body, _ = self.request("/api/save-env", "POST", {
            "PORT_PORTAL": "8088",
            "PORT_AIOSTREAMS": "3001",
            "PORT_AIOMETADATA": "4005",
        }, auth=True)
        self.assertEqual(status, 200)

        # Invalid port: out of range high
        status, body, _ = self.request("/api/save-env", "POST", {
            "PORT_PORTAL": "70000"
        }, auth=True)
        self.assertEqual(status, 400)
        self.assertIn(b"must be a valid port number", body)

        # Invalid port: zero
        status, body, _ = self.request("/api/save-env", "POST", {
            "PORT_AIOSTREAMS": "0"
        }, auth=True)
        self.assertEqual(status, 400)
        self.assertIn(b"must be a valid port number", body)

        # Invalid port: non-numeric string
        status, body, _ = self.request("/api/save-env", "POST", {
            "PORT_AIOMETADATA": "notaport"
        }, auth=True)
        self.assertEqual(status, 400)
        self.assertIn(b"must be a valid port number", body)

    def test_save_env_jellyfin_enabled_validation(self):
        # Valid values
        for val in ("true", "false", "1", "0", "TRUE", "False"):
            status, _, _ = self.request("/api/save-env", "POST", {"JELLYFIN_ENABLED": val}, auth=True)
            self.assertEqual(status, 200)

        # Invalid value
        status, body, _ = self.request("/api/save-env", "POST", {"JELLYFIN_ENABLED": "notabool"}, auth=True)
        self.assertEqual(status, 400)
        self.assertIn(b"JELLYFIN_ENABLED must be true or false", body)

    def test_aniskip_edge_cases(self):
        # Test duration=nan or inf does not crash
        with patch.object(portal, "resolve_mal_id", return_value="21"):
            with patch.object(portal, "get_aniskip_times", return_value={"found": False}):
                status, body, _ = self.request("/api/aniskip?id=kitsu:12&duration=nan", auth=True)
                self.assertEqual(status, 200)
                data = json.loads(body)
                self.assertFalse(data.get("found"))

                status, body, _ = self.request("/api/aniskip?id=kitsu:12&duration=inf", auth=True)
                self.assertEqual(status, 200)
                data = json.loads(body)
                self.assertFalse(data.get("found"))

                status, body, _ = self.request("/api/aniskip?id=kitsu:12&duration=-50", auth=True)
                self.assertEqual(status, 200)
                data = json.loads(body)
                self.assertFalse(data.get("found"))

    def test_manifest_redirect_endpoint(self):
        # 1. With local default (maps to port 3001)
        with patch.object(portal, "read_saved_env", return_value={"BASE_URL": "http://localhost:3000"}):
            status, _, headers = self.request("/manifest.json", headers={"Host": "192.168.1.100:8088"})
            self.assertEqual(status, 302)
            self.assertEqual(headers.get("Location"), "http://192.168.1.100:3001/stremio/u/local/manifest.json")

        # 2. With custom public BASE_URL
        with patch.object(portal, "read_saved_env", return_value={"BASE_URL": "https://aio.mydomain.com"}):
            status, _, headers = self.request("/manifest.json", headers={"Host": "192.168.1.100:8088"})
            self.assertEqual(status, 302)
            self.assertEqual(headers.get("Location"), "https://aio.mydomain.com/stremio/u/local/manifest.json")

    def test_reverse_proxy_origin_normalization(self):
        # 1. Matching host with explicit standard port :443
        status, _, _ = self.request(
            "/api/save-env", "POST", {"STREAMING_MODE": "debrid"}, auth=True,
            headers={"Origin": "https://portal.example.com", "X-Forwarded-Host": "portal.example.com:443"}
        )
        self.assertEqual(status, 200)

        # 2. Chained proxy X-Forwarded-Host
        status, _, _ = self.request(
            "/api/save-env", "POST", {"STREAMING_MODE": "debrid"}, auth=True,
            headers={"Origin": "https://portal.example.com", "X-Forwarded-Host": "portal.example.com, internal-lb:8088"}
        )
        self.assertEqual(status, 200)

        # 3. Malicious / untrusted origin rejected
        status, _, _ = self.request(
            "/api/save-env", "POST", {"STREAMING_MODE": "debrid"}, auth=True,
            headers={"Origin": "https://attacker.example.org", "X-Forwarded-Host": "portal.example.com"}
        )
        self.assertEqual(status, 403)

    def test_security_headers_on_all_responses(self):
        endpoints = [
            ("/healthz", "GET", None, False, 200),
            ("/dashboard", "GET", None, True, 200),
            ("/admin", "GET", None, True, 200),
            ("/nonexistent_path_404", "GET", None, False, 404),
            ("/api/save-env", "POST", {"STREAMING_MODE": "debrid"}, False, 401),
            ("/api/status", "GET", None, True, 200),
        ]
        for path, method, data, auth, expected_status in endpoints:
            status, _, headers = self.request(path, method=method, data=data, auth=auth)
            self.assertEqual(status, expected_status, f"Expected {expected_status} for {method} {path}")
            self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff", f"Missing nosniff on {path}")
            self.assertEqual(headers.get("X-Frame-Options"), "DENY", f"Missing X-Frame-Options on {path}")
            self.assertEqual(headers.get("Referrer-Policy"), "same-origin", f"Missing Referrer-Policy on {path}")
            csp = headers.get("Content-Security-Policy", "")
            self.assertIn("frame-ancestors 'none'", csp, f"Missing frame-ancestors in CSP on {path}")
            self.assertIn("object-src 'none'", csp, f"Missing object-src in CSP on {path}")
            self.assertEqual(headers.get("Server"), "AIO-Portal", f"Server header must not leak Python details on {path}")

    def test_safe_error_masking_on_500_and_503(self):
        leak_indicator = "C:\\sensitive\\system\\path\\to\\aio\\secret_token.txt"

        # 1. /api/save-env with unexpected OSError leaking sensitive path
        with patch.object(portal, "save_env_updates", side_effect=OSError(f"Disk error at {leak_indicator}")):
            status, body, _ = self.request("/api/save-env", "POST", {"STREAMING_MODE": "debrid"}, auth=True)
            self.assertEqual(status, 500)
            self.assertNotIn(leak_indicator.encode(), body)
            data = json.loads(body)
            self.assertFalse(data.get("success"))
            self.assertEqual(data.get("error"), "Internal server error occurred while saving configuration.")

        # 2. /api/restart
        with patch.object(portal.subprocess, "Popen", side_effect=RuntimeError(f"Subprocess crash: {leak_indicator}")):
            status, body, _ = self.request("/api/restart", "POST", auth=True)
            self.assertEqual(status, 500)
            self.assertNotIn(leak_indicator.encode(), body)
            data = json.loads(body)
            self.assertFalse(data.get("success"))
            self.assertEqual(data.get("error"), "Internal server error occurred while restarting stack.")

        # 3. /api/health-stats
        with patch("tools.resources.get_stack_resources", side_effect=Exception(f"Resource query failed: {leak_indicator}")):
            status, body, _ = self.request("/api/health-stats", "GET", auth=True)
            self.assertEqual(status, 500)
            self.assertNotIn(leak_indicator.encode(), body)
            data = json.loads(body)
            self.assertFalse(data.get("success"))

        # 4. /api/watchdog
        with patch("tools.watchdog.get_watchdog_telemetry", side_effect=Exception(f"Watchdog failed: {leak_indicator}")):
            status, body, _ = self.request("/api/watchdog", "GET", auth=True)
            self.assertEqual(status, 500)
            self.assertNotIn(leak_indicator.encode(), body)
            data = json.loads(body)
            self.assertFalse(data.get("success"))

        # 5. /api/backups/prune
        with patch("tools.backup.prune_backups", side_effect=Exception(f"Backup prune error: {leak_indicator}")):
            status, body, _ = self.request("/api/backups/prune", "POST", {"keep_last": 3}, auth=True)
            self.assertEqual(status, 500)
            self.assertNotIn(leak_indicator.encode(), body)
            data = json.loads(body)
            self.assertFalse(data.get("success"))

        # 6. /api/export-aiometadata 503 error
        with patch("builtins.open", side_effect=OSError(f"Failed opening template: {leak_indicator}")):
            status, body, _ = self.request("/api/export-aiometadata", "GET", auth=True)
            self.assertEqual(status, 503)
            self.assertNotIn(leak_indicator.encode(), body)
            data = json.loads(body)
            self.assertEqual(data.get("error"), "AIOMetadata configuration export failed.")

        # 7. /api/backup error
        with patch("tools.backup.create_backup", side_effect=Exception(f"Backup crash: {leak_indicator}")):
            status, body, _ = self.request("/api/backup", "GET", auth=True)
            self.assertEqual(status, 500)
            self.assertNotIn(leak_indicator.encode(), body)

    def test_path_traversal_and_boundary_validation(self):
        traversal_attempts = [
            "/assets/..%2f.env",
            "/assets/%2e%2e/.env",
            "/templates/..%2f..%2f.env",
            "/templates/aiometadata-configs/../../../.env",
            "/assets/%00.js",
            "/assets/bad<name>.js",
            "/assets/../package.json",
        ]
        for bad_path in traversal_attempts:
            status, _, _ = self.request(bad_path, "GET")
            self.assertEqual(status, 404, f"Path traversal attempt {bad_path} did not return 404")

        # Container parameter boundary validation
        status, body, _ = self.request("/api/logs?container=../../../etc/passwd", "GET", auth=True)
        self.assertEqual(status, 400)
        data = json.loads(body)
        self.assertIn("error", data)

        status, body, _ = self.request("/api/logs?container=unsupported_custom_service", "GET", auth=True)
        self.assertEqual(status, 400)

        # AIOMetadata template traversal rejection
        status, _, _ = self.request("/api/save-env", "POST", {"AIOMETADATA_TEMPLATE": "../malicious.json"}, auth=True)
        self.assertEqual(status, 400)
        status, _, _ = self.request("/api/save-env", "POST", {"AIOMETADATA_TEMPLATE": ".hidden.json"}, auth=True)
        self.assertEqual(status, 400)

        # Aniskip parameter boundary validation
        status, body, _ = self.request("/api/aniskip?id=invalid;cmd|injection&season=99999999&episode=-5", "GET")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertFalse(data.get("found"))

    def test_safe_json_decoding_on_malformed_and_empty_payloads(self):
        endpoints = [
            "/api/save-env",
            "/api/webhook-test",
            "/api/validate-provider",
            "/api/smoke-test",
            "/api/test-playback",
            "/api/config-import",
            "/api/backups/prune",
        ]
        # Malformed JSON syntax must return 400, never 500
        for ep in endpoints:
            status, body, _ = self.request(
                ep, "POST", b"{\"broken_json", auth=True,
                headers={"Content-Type": "application/json"}
            )
            self.assertEqual(status, 400, f"Endpoint {ep} should return 400 for malformed JSON")
            data = json.loads(body)
            self.assertTrue("error" in data or "detail" in data, f"Endpoint {ep} missing error/detail in response")

        # Empty body with Content-Length: 0
        for ep in ["/api/save-env", "/api/validate-provider", "/api/smoke-test"]:
            status, body, _ = self.request(
                ep, "POST", b"", auth=True,
                headers={"Content-Type": "application/json", "Content-Length": "0"}
            )
            # Empty JSON payload is either a 400 (validation error) or 200 (default/noop), but NEVER 500!
            self.assertIn(status, (200, 400), f"Endpoint {ep} crashed on empty payload with status {status}")

        # Non-numeric Content-Length header handled gracefully
        status, body, _ = self.request(
            "/api/save-env", "POST", b"{}", auth=True,
            headers={"Content-Type": "application/json", "Content-Length": "invalid_length"}
        )
        self.assertEqual(status, 400)

        # Negative Content-Length handled gracefully
        status, body, _ = self.request(
            "/api/save-env", "POST", b"{}", auth=True,
            headers={"Content-Type": "application/json", "Content-Length": "-10"}
        )
        self.assertEqual(status, 400)

        # Oversized body rejected
        oversized = b"a" * 70000
        status, body, _ = self.request(
            "/api/save-env", "POST", oversized, auth=True,
            headers={"Content-Type": "application/json", "Content-Length": str(len(oversized))}
        )
        self.assertEqual(status, 400)

    def test_endpoint_fuzzing_and_non_dict_payloads(self):
        endpoints = [
            "/api/save-env",
            "/api/webhook-test",
            "/api/validate-provider",
            "/api/smoke-test",
            "/api/test-playback",
            "/api/config-import",
            "/api/backups/prune",
        ]
        non_dict_payloads = [
            b"[1, 2, 3]",
            b'"just a string"',
            b"12345",
            b"true",
            b"null",
        ]
        for ep in endpoints:
            for payload in non_dict_payloads:
                status, body, _ = self.request(
                    ep, "POST", payload, auth=True,
                    headers={"Content-Type": "application/json"}
                )
                self.assertEqual(status, 400, f"Expected 400 for {ep} with non-dict payload {payload}, got {status}: {body}")
                data = json.loads(body)
                self.assertTrue("error" in data or "detail" in data)

        # Invalid non-UTF8 encodings
        bad_bytes = b"\xff\xfe\xfd\x80\x81"
        for ep in endpoints:
            status, body, _ = self.request(
                ep, "POST", bad_bytes, auth=True,
                headers={"Content-Type": "application/json"}
            )
            self.assertEqual(status, 400, f"Expected 400 for {ep} with invalid UTF-8 bytes, got {status}: {body}")

    def test_endpoint_extreme_parameters(self):
        # 1. Aniskip extreme parameters
        aniskip_cases = [
            ("id=kitsu:&season=1&episode=1", 200),
            ("id=::::&season=-1&episode=-1", 200),
            ("id=malicious%00path&season=1&episode=1", 200),
            ("id=tt9335498&duration=1e999", 200),
            ("id=tt9335498&duration=-1e999", 200),
            ("id=tt9335498&season=999999999999999999999&episode=999999999999999999999", 200),
            ("id=tt9335498&season=-999999&episode=-999999", 200),
        ]
        for qs, expected in aniskip_cases:
            status, body, _ = self.request(f"/api/aniskip?{qs}")
            self.assertEqual(status, expected)
            data = json.loads(body)
            self.assertIn("found", data)

        # 2. Proxy-config parameters
        status, body, _ = self.request("/api/proxy-config?format=invalid_proxy&base_url=http://example.com", auth=True)
        self.assertEqual(status, 400)
        status, body, _ = self.request("/api/proxy-config?format=caddy&base_url=ftp://example.com", auth=True)
        self.assertEqual(status, 400)
        for fmt in ("caddy", "nginx", "traefik", "cloudflare"):
            status, body, _ = self.request(f"/api/proxy-config?format={fmt}", auth=True)
            self.assertEqual(status, 200)

        # 3. Backups prune parameters
        with patch("tools.backup.prune_backups", return_value={"pruned": 0, "kept": 1}):
            # Negative or zero clamped safely
            status, body, _ = self.request("/api/backups/prune", "POST", {"keep_last": -5}, auth=True)
            self.assertEqual(status, 200)
            status, body, _ = self.request("/api/backups/prune", "POST", {"keep_last": 0}, auth=True)
            self.assertEqual(status, 200)
            # Non-integer rejected with 400
            status, body, _ = self.request("/api/backups/prune", "POST", {"keep_last": "abc"}, auth=True)
            self.assertEqual(status, 400)

    def test_service_proxy_routing(self):
        # 1. Unknown service returns 404
        status, _, _ = self.request("/service-proxy/nonexistent_service/", auth=True)
        self.assertEqual(status, 404)

        # 2. Path without trailing slash redirects with 302
        status, _, headers = self.request("/service-proxy/prowlarr", auth=True)
        self.assertEqual(status, 302)
        self.assertEqual(headers.get("Location"), "/service-proxy/prowlarr/")

        # 3. /service-proxy alone returns 404
        status, _, _ = self.request("/service-proxy", auth=True)
        self.assertEqual(status, 404)

        # 4. Mock upstream response with HTML, redirect, and CSP/XFO modifications
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.headers = {
            "Content-Type": "text/html; charset=utf-8",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": "frame-ancestors 'none'; default-src 'self'",
        }
        mock_resp.read.return_value = b"<html><head><title>Prowlarr</title></head><body>Hello</body></html>"
        mock_resp.__enter__.return_value = mock_resp

        with patch.object(portal._PROXY_OPENER, "open", return_value=mock_resp):
            status, body, headers = self.request("/service-proxy/prowlarr/", auth=True)
            self.assertEqual(status, 200)
            self.assertIn(b'<base href="/service-proxy/prowlarr/">', body)
            self.assertEqual(headers.get("X-Frame-Options"), "SAMEORIGIN")
            self.assertIn("frame-ancestors 'self';", headers.get("Content-Security-Policy", ""))

        # 5. Direct alias /jellyfin routes to aiostreams
        mock_jelly = MagicMock()
        mock_jelly.status = 200
        mock_jelly.headers = {"Content-Type": "text/html; charset=utf-8"}
        mock_jelly.read.return_value = b"<html><head></head><body>Jellyfin</body></html>"
        mock_jelly.__enter__.return_value = mock_jelly
        with patch.object(portal._PROXY_OPENER, "open", return_value=mock_jelly):
            status, body, _ = self.request("/jellyfin/web/index.html", auth=True)
            self.assertEqual(status, 200)
            self.assertIn(b'<base href="/jellyfin/web/">', body)

        # 6. Referer fallback for unhandled subresources
        with patch.object(portal._PROXY_OPENER, "open", return_value=mock_resp):
            status, _, _ = self.request("/Content/prowlarr.css", auth=True, headers={"Referer": "http://localhost:8088/service-proxy/prowlarr/"})
            self.assertEqual(status, 200)

        # 7. Unreachable service returns 502 Bad Gateway
        with patch.object(portal._PROXY_OPENER, "open", side_effect=OSError("Connection refused")):
            status, body, _ = self.request("/service-proxy/prowlarr/", auth=True, headers={"Accept": "application/json"})
            self.assertEqual(status, 502)
            data = json.loads(body)
            self.assertEqual(data.get("error"), "Bad Gateway")

            # HTML response for browser requests without Accept: application/json
            status_html, body_html, _ = self.request("/service-proxy/prowlarr/", auth=True)
            self.assertEqual(status_html, 502)
            self.assertIn(b"Connecting to prowlarr", body_html)

    def test_comet_check_endpoints_removed(self):
        status, _, _ = self.request("/api/comet-check", auth=True)
        self.assertEqual(status, 404)
        status, _, _ = self.request("/api/comet-check", "POST", {"id": "tt0137523"}, auth=True)
        self.assertEqual(status, 404)

    def test_service_proxy_postersplus_access_key_redirect(self):
        with patch.dict(os.environ, {"POSTERSPLUS_ACCESS_KEY": "supersecretkey"}), \
             patch.object(portal, "read_saved_env", return_value={"POSTERSPLUS_ACCESS_KEY": "supersecretkey"}):
            # Accessing /admin without access_key redirects to append access_key
            status, body, headers = self.request("/service-proxy/postersplus/admin", auth=True)
            self.assertEqual(status, 302)
            self.assertIn("/service-proxy/postersplus/admin?access_key=supersecretkey", headers.get("Location", ""))

            # Accessing /admin with existing query string preserves it and appends access_key
            status, body, headers = self.request("/service-proxy/postersplus/admin?tab=settings", auth=True)
            self.assertEqual(status, 302)
            self.assertIn("tab=settings&access_key=supersecretkey", headers.get("Location", ""))

    def test_service_proxy_infinidysk_is_not_routed(self):
        status, body, headers = self.request("/service-proxy/infinidysk/overview", auth=True)
        self.assertEqual(status, 404)
        self.assertFalse(hasattr(portal, "get_infinidysk_session_cookie"))

    def test_service_proxy_prowlarr_rewrites_urlbase_and_injects_apikey(self):
        # 1. HTML rewrite
        mock_html_resp = MagicMock()
        mock_html_resp.status = 200
        mock_html_resp.headers = {"Content-Type": "text/html; charset=utf-8"}
        mock_html_resp.read.return_value = b'<!doctype html><html><head><script>window.Prowlarr = {\n  urlBase: ""\n};</script><link href="/Content/styles.css" rel="stylesheet"><script src="/index-123.js"></script></head><body></body></html>'
        mock_html_resp.__enter__.return_value = mock_html_resp

        with patch.object(portal._PROXY_OPENER, "open", return_value=mock_html_resp):
            status, body, _ = self.request("/service-proxy/prowlarr/", auth=True)
            self.assertEqual(status, 200)
            body_str = body.decode("utf-8")
            self.assertIn('urlBase: "/service-proxy/prowlarr"', body_str)
            self.assertIn('/service-proxy/prowlarr/Content/styles.css', body_str)
            self.assertIn('/service-proxy/prowlarr/index-123.js', body_str)

        # 2. initialize.json rewrite
        mock_init_resp = MagicMock()
        mock_init_resp.status = 200
        mock_init_resp.headers = {"Content-Type": "application/json"}
        mock_init_resp.read.return_value = b'{"apiRoot": "/api/v1", "urlBase": "", "apiKey": "test-key"}'
        mock_init_resp.__enter__.return_value = mock_init_resp

        with patch.object(portal._PROXY_OPENER, "open", return_value=mock_init_resp):
            status, body, _ = self.request("/service-proxy/prowlarr/initialize.json", auth=True)
            self.assertEqual(status, 200)
            data = json.loads(body.decode("utf-8"))
            self.assertEqual(data["urlBase"], "/service-proxy/prowlarr")
            self.assertEqual(data["apiRoot"], "/service-proxy/prowlarr/api/v1")

        # 3. API Key injection
        captured = []
        mock_api_resp = MagicMock()
        mock_api_resp.status = 200
        mock_api_resp.headers = {"Content-Type": "application/json"}
        mock_api_resp.read.return_value = b'{"indexers": []}'
        mock_api_resp.__enter__.return_value = mock_api_resp

        def capture_open(req, *args, **kwargs):
            captured.append(req)
            return mock_api_resp

        with patch.object(portal._PROXY_OPENER, "open", side_effect=capture_open), \
             patch.dict(os.environ, {"PROWLARR_API_KEY": "prowlarr-secret-key"}), \
             patch.object(portal, "read_saved_env", return_value={"PROWLARR_API_KEY": "prowlarr-secret-key"}):
            status, body, _ = self.request("/service-proxy/prowlarr/api/v1/indexerstats", auth=True)
            self.assertEqual(status, 200)
            self.assertTrue(len(captured) > 0)
            self.assertEqual(captured[0].headers.get("X-api-key"), "prowlarr-secret-key")
            self.assertEqual(captured[0].selector, "/api/v1/indexerstats")

        # 4. Referer fallback for /api/v1/... routes without /service-proxy/ prefix
        captured.clear()
        with patch.object(portal._PROXY_OPENER, "open", side_effect=capture_open):
            status, body, _ = self.request("/api/v1/indexerstats", auth=False, headers={"Referer": "http://localhost:8088/service-proxy/prowlarr/"})
            self.assertEqual(status, 200)
            self.assertTrue(len(captured) > 0)
            self.assertEqual(captured[0].selector, "/api/v1/indexerstats")

        # 5. Cookie fallback for SPA routes when Referer is absent or lost
        captured.clear()
        with patch.object(portal._PROXY_OPENER, "open", side_effect=capture_open):
            status, body, _ = self.request("/activity/queue", auth=False, headers={"Cookie": "active_service_proxy=prowlarr"})
            self.assertEqual(status, 200)
            self.assertTrue(len(captured) > 0)
            self.assertEqual(captured[0].selector, "/activity/queue")

    def test_app_webmanifest(self):
        status, body, headers = self.request("/app.webmanifest")
        self.assertEqual(status, 200)
        self.assertIn("application/manifest+json", headers.get("Content-Type", ""))
        manifest = json.loads(body.decode("utf-8"))
        self.assertEqual(manifest.get("short_name"), "AIOStreams")
        self.assertEqual(manifest.get("display"), "standalone")

    def test_player_preferences_lifecycle(self):
        # 1. GET initial preferences
        status, body, _ = self.request("/api/player-preferences", auth=True)
        self.assertEqual(status, 200)
        prefs = json.loads(body.decode("utf-8"))
        self.assertIn("audioLanguage", prefs)

        # 2. POST update preferences
        new_prefs = {
            "audioLanguage": "jpn",
            "audioFallback": "eng",
            "subtitleMode": "sdh",
            "subtitleLanguage": "eng",
            "fontScale": 120
        }
        status, body, _ = self.request("/api/player-preferences", "POST", new_prefs, auth=True, headers={"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        res = json.loads(body.decode("utf-8"))
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("preferences", {}).get("audioLanguage"), "jpn")

        # 3. GET verify updated preferences
        status, body, _ = self.request("/api/player-preferences", auth=True)
        self.assertEqual(status, 200)
        updated = json.loads(body.decode("utf-8"))
        self.assertEqual(updated.get("audioLanguage"), "jpn")
        self.assertEqual(updated.get("fontScale"), 120)

    def test_static_asset_cookie_isolation(self):
        # 1. Root page and dashboard clear the active_service_proxy cookie
        status, _, headers = self.request("/", auth=True)
        self.assertEqual(status, 200)
        set_cookie = headers.get("Set-Cookie", "")
        self.assertIn("active_service_proxy=;", set_cookie)
        self.assertIn("Max-Age=0", set_cookie)

        status, _, headers = self.request("/dashboard", auth=True)
        self.assertEqual(status, 200)
        self.assertIn("active_service_proxy=;", headers.get("Set-Cookie", ""))

        # 2. Static assets are never forwarded to backend proxy even if proxy cookie/referer are sent
        (self.root / "assets" / "app.js").write_text("console.log('portal');")
        (self.root / "templates").mkdir(exist_ok=True)
        (self.root / "templates" / "test.json").write_text("{}")

        with patch.object(portal._PROXY_OPENER, "open") as mock_open:
            status, body, headers = self.request(
                "/assets/app.js",
                headers={
                    "Cookie": "active_service_proxy=prowlarr",
                    "Referer": "http://localhost:8088/service-proxy/prowlarr/",
                },
            )
            mock_open.assert_not_called()
            self.assertEqual(status, 200)

            # Templates directory and webmanifest are also isolated from proxying
            status, body, _ = self.request(
                "/templates/test.json",
                headers={"Cookie": "active_service_proxy=prowlarr"},
            )
            mock_open.assert_not_called()
            self.assertEqual(status, 200)

            status, body, _ = self.request(
                "/app.webmanifest",
                headers={"Cookie": "active_service_proxy=prowlarr"},
            )
            mock_open.assert_not_called()
            self.assertEqual(status, 200)

    def test_watch_route_web_player_redirect(self):
        # 1. /watch without trailing slash redirects to /watch/
        status, _, headers = self.request("/watch")
        self.assertEqual(status, 302)
        self.assertEqual(headers.get("Location"), "/watch/")

        # 2. /watch?source=card preserves query string in redirect
        status, _, headers = self.request("/watch?source=card")
        self.assertEqual(status, 302)
        self.assertEqual(headers.get("Location"), "/watch/?source=card")

        # 3. When Jellyfin is disabled, /watch/ returns 503
        with patch.dict(os.environ, {"JELLYFIN_ENABLED": "false"}), \
             patch.object(portal, "read_saved_env", return_value={"JELLYFIN_ENABLED": "false"}):
            status, body, _ = self.request("/watch/")
            self.assertEqual(status, 503)
            self.assertIn(b"Media Player Disabled", body)

        # 4. When Jellyfin credentials are not configured, /watch/ returns 503
        with patch.dict(os.environ, {"JELLYFIN_ENABLED": "true"}), \
             patch.object(portal, "read_saved_env", return_value={}), \
             patch.object(portal.AppliancePortalHandler, "_get_jellyfin_credentials", return_value=(None, None)):
            status, body, _ = self.request("/watch/")
            self.assertEqual(status, 503)
            self.assertIn(b"Media Player Setup Required", body)

        # 5. When credentials exist, /watch/ redirects with 302 to AIOStreams Jellyfin web player
        with patch.dict(os.environ, {"JELLYFIN_ENABLED": "true", "PORT_AIOSTREAMS": "3001"}), \
             patch.object(portal, "read_saved_env", return_value={"BASE_URL": "http://localhost:3001", "PORT_AIOSTREAMS": "3001"}), \
             patch.object(portal.AppliancePortalHandler, "_get_jellyfin_credentials", return_value=("test-uuid", "test-enc-pass")):
            status, _, headers = self.request("/watch/")
            self.assertEqual(status, 302)
            self.assertEqual(headers.get("Location"), "http://localhost:3001/jellyfin/test-uuid/test-enc-pass/web/")

            # Deep link subpath preservation
            status, _, headers = self.request("/watch/web/index.html?serverId=123")
            self.assertEqual(status, 302)
            self.assertEqual(headers.get("Location"), "http://localhost:3001/jellyfin/test-uuid/test-enc-pass/web/index.html?serverId=123")

            # External domain preservation
            with patch.object(portal, "read_saved_env", return_value={"BASE_URL": "https://stream.example.com"}):
                status, _, headers = self.request("/watch/")
                self.assertEqual(status, 302)
                self.assertEqual(headers.get("Location"), "https://stream.example.com/jellyfin/test-uuid/test-enc-pass/web/")

    def test_cloudflare_status_endpoint(self):
        mock_containers = {
            "available": True,
            "local_tunnel": {"name": "aio-tunnel", "status": "running", "is_local": True},
            "external_connectors": [{"id": "abc12345", "name": "docktun-cloudflared", "status": "Created", "is_local": False}],
            "has_external": True
        }
        with patch("tools.cloudflare_helper.check_cloudflare_containers", return_value=mock_containers), \
             patch.object(portal, "read_saved_env", return_value={"BASE_URL": "https://watch.example.com"}):
            status, body, _ = self.request("/api/cloudflare/status", "GET", auth=True)
            self.assertEqual(status, 200)
            data = json.loads(body.decode("utf-8"))
            self.assertTrue(data["success"])
            self.assertTrue(data["has_external"])
            self.assertEqual(len(data["external_connectors"]), 1)
            self.assertEqual(data["external_connectors"][0]["name"], "docktun-cloudflared")
            self.assertEqual(data["current_host"], "watch.example.com")

    def test_cloudflare_push_dns_endpoint(self):
        # 1. Missing api_token -> 400
        with patch.object(portal, "read_saved_env", return_value={"BASE_URL": "https://watch.example.com"}):
            status, body, _ = self.request("/api/cloudflare/push-dns", "POST", {"api_token": ""}, auth=True)
            self.assertEqual(status, 400)
            data = json.loads(body.decode("utf-8"))
            self.assertIn("API Token is required", data.get("error", ""))

        # 2. Successful push
        mock_push = {
            "success": True,
            "action": "created",
            "hostname": "watch.example.com",
            "cname_target": "tun123.cfargotunnel.com",
            "zone_name": "example.com",
            "record_id": "rec-123",
            "message": "✓ Successfully created Cloudflare CNAME record"
        }
        with patch("tools.cloudflare_helper.push_cloudflare_dns", return_value=mock_push):
            status, body, _ = self.request("/api/cloudflare/push-dns", "POST", {
                "api_token": "valid_token",
                "hostname": "watch.example.com",
                "cname_target": "tun123.cfargotunnel.com"
            }, auth=True)
            self.assertEqual(status, 200)
            data = json.loads(body.decode("utf-8"))
            self.assertTrue(data["success"])
            self.assertEqual(data["record_id"], "rec-123")

    def test_cloudflare_tunnel_action_endpoint(self):
        with patch("tools.cloudflare_helper.manage_local_tunnel", return_value={"success": True, "action": "start"}):
            status, body, _ = self.request("/api/cloudflare/tunnel", "POST", {"action": "start"}, auth=True)
            self.assertEqual(status, 200)
            data = json.loads(body.decode("utf-8"))
            self.assertTrue(data["success"])
            self.assertEqual(data["action"], "start")

    def test_cloudflare_push_dns_fallback_to_saved_env(self):
        mock_push = {
            "success": True,
            "action": "created",
            "hostname": "watch.example.com",
            "cname_target": "c7b74447-4951-4d37-882f-2d4e73b22cf1.cfargotunnel.com",
            "zone_name": "example.com",
            "record_id": "rec-saved-123",
            "message": "✓ Successfully created Cloudflare CNAME record"
        }
        with patch.object(portal, "read_saved_env", return_value={"CLOUDFLARE_TUNNEL_TOKEN": "c7b74447-4951-4d37-882f-2d4e73b22cf1", "CLOUDFLARE_ZONE_ID": "zone-xyz"}):
            with patch("tools.cloudflare_helper.push_cloudflare_dns", return_value=mock_push) as mock_fn:
                status, body, _ = self.request("/api/cloudflare/push-dns", "POST", {
                    "api_token": "valid_token",
                    "hostname": "watch.example.com",
                    "tunnel_token": ""
                }, auth=True)
                self.assertEqual(status, 200)
                mock_fn.assert_called_once()
                call_kwargs = mock_fn.call_args[1]
                self.assertEqual(call_kwargs["cname_target"], "c7b74447-4951-4d37-882f-2d4e73b22cf1.cfargotunnel.com")
                self.assertEqual(call_kwargs["tunnel_id"], "c7b74447-4951-4d37-882f-2d4e73b22cf1")
                self.assertEqual(call_kwargs["zone_id"], "zone-xyz")

    def test_cloudflare_env_persistence_and_exposure(self):
        before = (self.root / ".env").read_bytes()
        try:
            save_payload = {
                "CLOUDFLARE_TUNNEL_TOKEN": "cloudflared tunnel run --token c7b74447-4951-4d37-882f-2d4e73b22cf1",
                "CLOUDFLARE_ZONE_ID": "my_zone_123",
                "CLOUDFLARE_API_TOKEN": "secret_api_token"
            }
            status, body, _ = self.request("/api/save-env", "POST", save_payload, auth=True)
            self.assertEqual(status, 200)

            status, body, _ = self.request("/api/env", "GET", auth=True)
            self.assertEqual(status, 200)
            env_data = json.loads(body.decode("utf-8"))
            self.assertTrue(env_data.get("CLOUDFLARE_TUNNEL_TOKEN_SAVED"))
            self.assertEqual(env_data.get("CLOUDFLARE_ZONE_ID"), "my_zone_123")
            self.assertTrue(env_data.get("CLOUDFLARE_API_TOKEN_SAVED"))
            self.assertNotIn("CLOUDFLARE_API_TOKEN", env_data)
            self.assertTrue(env_data.get("CLOUDFLARE_TUNNEL_METADATA", {}).get("valid"))
            self.assertEqual(env_data.get("CLOUDFLARE_TUNNEL_METADATA", {}).get("tunnel_id"), "c7b74447-4951-4d37-882f-2d4e73b22cf1")
        finally:
            (self.root / ".env").write_bytes(before)


    def test_unmapped_api_get_returns_json_404(self):
        status, body, headers = self.request("/api/nonexistent_test_route", auth=True)
        self.assertEqual(status, 404)
        self.assertEqual(headers.get("Content-Type"), "application/json")
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data.get("error"), "Endpoint not found")

    def test_defensive_route_error_handling(self):
        leak_indicator = "C:\\sensitive\\system\\path\\to\\aio\\secret_token.txt"

        # 1. /api/playback-readiness error masking
        with patch.object(portal, "playback_readiness", side_effect=Exception(f"Readiness error: {leak_indicator}")):
            status, body, _ = self.request("/api/playback-readiness", auth=True)
            self.assertEqual(status, 500)
            self.assertNotIn(leak_indicator.encode(), body)
            data = json.loads(body)
            self.assertIn("Internal server error", data.get("error", ""))

        # 2. /api/integrations error masking
        with patch.object(portal, "probe_integration", side_effect=Exception(f"Probe crash: {leak_indicator}")):
            status, body, _ = self.request("/api/integrations", auth=True)
            self.assertEqual(status, 500)
            self.assertNotIn(leak_indicator.encode(), body)
            data = json.loads(body)
            self.assertIn("Internal server error", data.get("error", ""))

        # 3. /api/maintenance error masking
        with patch.object(portal, "maintenance_snapshot", side_effect=Exception(f"Snapshot crash: {leak_indicator}")):
            status, body, _ = self.request("/api/maintenance", auth=True)
            self.assertEqual(status, 500)
            self.assertNotIn(leak_indicator.encode(), body)
            data = json.loads(body)
            self.assertIn("Internal server error", data.get("error", ""))

        # 4. /api/diagnostics error masking
        with patch.object(portal, "diagnostics_snapshot", side_effect=Exception(f"Diagnostics crash: {leak_indicator}")):
            status, body, _ = self.request("/api/diagnostics", auth=True)
            self.assertEqual(status, 500)
            self.assertNotIn(leak_indicator.encode(), body)
            data = json.loads(body)
            self.assertIn("Internal server error", data.get("error", ""))

        # 5. /api/config-export error masking
        with patch.object(portal, "config_export", side_effect=Exception(f"Export crash: {leak_indicator}")):
            status, body, _ = self.request("/api/config-export", auth=True)
            self.assertEqual(status, 500)
            self.assertNotIn(leak_indicator.encode(), body)
            data = json.loads(body)
            self.assertIn("Internal server error", data.get("error", ""))

        # 6. /api/player-preferences POST ValueError vs Exception
        with patch.object(portal, "save_player_preferences", side_effect=ValueError("Invalid speed parameter")):
            status, body, _ = self.request("/api/player-preferences", "POST", {"speed": 99}, auth=True)
            self.assertEqual(status, 400)
            data = json.loads(body)
            self.assertEqual(data.get("error"), "Invalid speed parameter")

        with patch.object(portal, "save_player_preferences", side_effect=Exception(f"DB crash: {leak_indicator}")):
            status, body, _ = self.request("/api/player-preferences", "POST", {"speed": 1}, auth=True)
            self.assertEqual(status, 500)
            self.assertNotIn(leak_indicator.encode(), body)
            data = json.loads(body)
            self.assertIn("Internal server error", data.get("error", ""))

        # 7. /api/cloudflare/push-dns error masking
        with patch("tools.cloudflare_helper.push_cloudflare_dns", side_effect=Exception(f"CF API crash: {leak_indicator}")):
            status, body, _ = self.request("/api/cloudflare/push-dns", "POST", {
                "api_token": "token",
                "hostname": "watch.example.com",
                "cname_target": "target.cfargotunnel.com"
            }, auth=True)
            self.assertEqual(status, 500)
            self.assertNotIn(leak_indicator.encode(), body)
            data = json.loads(body)
            self.assertFalse(data.get("success"))

        # 8. /api/cloudflare/tunnel error masking
        with patch("tools.cloudflare_helper.manage_local_tunnel", side_effect=Exception(f"Tunnel crash: {leak_indicator}")):
            status, body, _ = self.request("/api/cloudflare/tunnel", "POST", {"action": "start"}, auth=True)
            self.assertEqual(status, 500)
            self.assertNotIn(leak_indicator.encode(), body)
            data = json.loads(body)
            self.assertFalse(data.get("success"))

        # 9. /api/lumiere/rebuild error masking
        with patch.object(portal.subprocess, "run", side_effect=Exception(f"Lumiere exec crash: {leak_indicator}")):
            status, body, _ = self.request("/api/lumiere/rebuild", "POST", auth=True)
            self.assertEqual(status, 500)
            self.assertNotIn(leak_indicator.encode(), body)
            data = json.loads(body)
            self.assertFalse(data.get("success"))


if __name__ == "__main__":
    unittest.main()
