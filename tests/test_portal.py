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
    def test_usenet_password_is_saved_privately_and_not_returned_by_env(self):
        status,_,_=self.request('/api/save-env','POST',{'USENET_ENABLED':'true','USENET_HOST':'news.fixture','USENET_USER':'fixture-user','USENET_PASS':'fixture$private\'"'},auth=True)
        self.assertEqual(status,200)
        status,body,_=self.request('/api/env',auth=True)
        self.assertEqual(status,200);self.assertNotIn('fixture$private',body.decode())
        result=json.loads(body);self.assertTrue(result['USENET_PASSWORD_SAVED']);self.assertEqual(result['USENET_USER'],'fixture-user')

    def test_optional_mediafusion_scale_is_limited_to_off_or_on(self):
        status,_,_=self.request('/api/save-env','POST',{'MEDIAFUSION_REPLICAS':'10'},auth=True)
        self.assertEqual(status,400)

    def test_integration_probes_use_container_ports(self):
        self.assertEqual(portal.APPLICATION_SERVICE_COUNT, 17)
        expected = {
            "anime-kitsu": 7000,
            "postersplus": 8000,
            "stremio-web": 8080,
            "nuvio": 3000,
            "slicksync": 3000,
        }
        actual = {host: port for _, host, port, _ in portal.INTEGRATIONS}
        self.assertEqual({host: actual[host] for host in expected}, expected)

    def test_diagnostics_redacts_provider_values(self):
        with patch.object(portal, "probe_integration", return_value={
            "name": "Comet", "group": "Scrapers", "reachable": True,
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

    def setUp(self):
        portal.AUTH_FAILURES.clear()

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
             patch("tools.watchdog.get_watchdog_telemetry", return_value={"status": "active", "healthy_count": 14, "total_services": 14, "last_probe": "2026-11-09T00:00:00Z"}):
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


if __name__ == "__main__":
    unittest.main()
