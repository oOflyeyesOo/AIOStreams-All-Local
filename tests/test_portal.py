import base64
import http.client
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "portal", Path(__file__).resolve().parents[1] / "docker/all-in-one/portal_server.py")
portal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(portal)


class PortalTests(unittest.TestCase):
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
        cls.auth_env = patch.dict(os.environ, {"ADDON_PASSWORD": "test-password"})
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

    def request(self, path, method="GET", data=None, auth=False, headers=None):
        request_headers = dict(headers or {})
        if auth:
            request_headers["Authorization"] = "Basic " + base64.b64encode(b"admin:test-password").decode()
        body = json.dumps(data) if data is not None else None
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        connection.request(method, path, body, request_headers)
        response = connection.getresponse()
        result = response.status, response.read(), dict(response.getheaders())
        connection.close()
        return result

    def test_public_health_and_pages(self):
        for path in ("/healthz", "/", "/dashboard", "/assets/test.png"):
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
        link.symlink_to(self.root / ".env")
        try:
            self.assertEqual(self.request("/assets/leak.png")[0], 404)
        finally:
            link.unlink()

    def test_api_requires_authentication(self):
        for path in ("/api/env", "/api/status", "/api/logs", "/api/manifest-info", "/api/templates", "/api/setup-status", "/api/integrations"):
            self.assertEqual(self.request(path)[0], 401)
        self.assertEqual(self.request("/api/save", "POST", {})[0], 401)
        self.assertEqual(self.request("/api/setup", "POST")[0], 401)

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
        portal.save_env_updates({"BASE_URL": "http://oldnas:3000", "SOOTIO_URL": "http://oldnas:55771", "NUVIO_ORIGIN": "https://player.example.org"})
        self.assertEqual(self.request("/api/save", "POST", {"BASE_URL": "http://newnas:3000"}, True)[0], 200)
        content = (self.root / ".env").read_text()
        self.assertIn("SOOTIO_URL=http://newnas:55771", content)
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
        portal.save_env_updates({"TEST_SECRET": "private-test-value", "PREMIUMIZE_API_KEY": "private-provider-key"})
        for path in ("/api/env", "/api/status"):
            with patch.object(portal.subprocess, "run", side_effect=OSError()), patch.object(portal.urllib.request, "urlopen", side_effect=OSError()):
                status, body, _ = self.request(path, auth=True)
            self.assertEqual(status, 200)
            self.assertNotIn(b"private-test-value", body)
            self.assertNotIn(b"private-provider-key", body)
            result = json.loads(body)
            state = result if path == "/api/env" else result["env"]
            self.assertIn("PREMIUMIZE_API_KEY", state["configuredKeys"])
            self.assertNotIn("PREMIUMIZE_API_KEY", state)

    def test_cross_origin_write_blocked(self):
        self.assertEqual(self.request("/api/save", "POST", {}, True,
                                      {"Origin": "https://untrusted.example"})[0], 403)

    def test_no_wildcard_cors_or_cache(self):
        headers = self.request("/healthz")[2]
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(headers["Cache-Control"], "no-store")

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
        portal.save_env_updates({"BASE_URL": "https://aio.example.com", "AIOMETADATA_PROFILE_UUID": "test-uuid-123"})
        status, body, _ = self.request("/api/manifest-info", auth=True)
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data.get("aiometadataHost"), "https://aiometa.example.com")
        self.assertEqual(data.get("aiometadataManifest"), "https://aiometa.example.com/stremio/test-uuid-123/manifest.json")

    def test_failed_replace_preserves_original(self):
        before = (self.root / ".env").read_bytes()
        with patch.object(portal.os, "replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                portal.save_env_updates({"DISK_TEST": "value"})
        self.assertEqual((self.root / ".env").read_bytes(), before)
        self.assertEqual(list(self.root.glob(".env-*")), [])


if __name__ == "__main__":
    unittest.main()
