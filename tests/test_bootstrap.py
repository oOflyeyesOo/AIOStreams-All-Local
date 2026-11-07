import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "bootstrap", Path(__file__).resolve().parents[1] / "init/bootstrap/setup_stack.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        # Unit tests model availability explicitly; DNS/network delays belong in E2E checks.
        probe = patch.object(bootstrap, "is_url_reachable", return_value=True)
        probe.start()
        self.addCleanup(probe.stop)
        requests = patch.object(bootstrap, "make_request", return_value={})
        requests.start()
        self.addCleanup(requests.stop)

    def test_update_env_file_replaces_existing_key_without_duplicates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text("BASE_URL=http://old.example\nBASE_URL=http://duplicate.example\n", encoding="utf-8")
            self.assertTrue(bootstrap.update_env_file(
                "BASE_URL", "https://new.example", candidates=[str(env_path)]
            ))
            self.assertEqual(env_path.read_text(encoding="utf-8"), "BASE_URL=https://new.example\n")

    def test_optional_metadata_is_skipped_when_dependencies_are_unavailable(self):
        with patch.object(bootstrap, "wait_for_postersplus", return_value=False), \
             patch.object(bootstrap, "wait_for_aiometadata") as wait_metadata, \
             patch.object(bootstrap, "setup_aiometadata_tamtaro") as configure_metadata:
            self.assertIsNone(bootstrap.setup_optional_metadata())
        wait_metadata.assert_not_called()
        configure_metadata.assert_not_called()

    def test_optional_metadata_configures_only_after_both_dependencies_are_ready(self):
        with patch.object(bootstrap, "wait_for_postersplus", return_value=True), \
             patch.object(bootstrap, "wait_for_aiometadata", return_value=True), \
             patch.object(bootstrap, "setup_aiometadata_tamtaro", return_value="http://aiometadata:4005/manifest.json") as configure_metadata:
            self.assertEqual(
                bootstrap.setup_optional_metadata(),
                "http://aiometadata:4005/manifest.json",
            )
        configure_metadata.assert_called_once_with()

    def test_prowlarr_indexer_setup_skips_existing_definitions(self):
        schemas = [
            {"definitionName": "1337x", "name": "1337x"},
            {"definitionName": "yts", "name": "YTS"},
        ]
        requests = []

        def request(url, method="GET", data=None, headers=None, timeout=12):
            if url.endswith("/api/v1/indexer") and method == "GET":
                return [{"definitionName": "1337x", "name": "Existing 1337x", "id": 7}]
            if url.endswith("/api/v1/indexer/schema"):
                return schemas
            if method == "POST":
                requests.append((url, data))
                return {"id": 8}
            raise AssertionError(f"Unexpected request: {method} {url}")

        with patch.object(bootstrap, "make_request", side_effect=request):
            with patch.object(bootstrap, "TARGET_INDEXERS", ["1337x", "yts"]):
                bootstrap.setup_prowlarr_indexers()

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0][1]["definitionName"], "yts")

    def test_error_entries_are_not_playable(self):
        self.assertEqual(bootstrap.playable_streams({"streams": [{"name": "Error", "title": "Invalid Api Key"}]}), [])
        self.assertEqual(bootstrap.playable_streams({"streams": [{"url": "https://comet.feels.legal/", "title": "Invalid Api Key"}]}), [])

    def test_readiness_rejects_truthy_error_responses(self):
        with patch.object(bootstrap, "make_request", return_value={"error": 503}), patch.object(bootstrap.time, "sleep"):
            self.assertFalse(bootstrap.wait_for_aiometadata(max_attempts=2, interval=0))

    def test_readiness_accepts_manifest(self):
        with patch.object(bootstrap, "make_request", return_value={"id": "metadata"}):
            self.assertTrue(bootstrap.wait_for_aiometadata(max_attempts=1))

    def test_metadata_save_supplies_addon_password_and_uses_install_path(self):
        response = {"success": True, "userUUID": "test-id", "installUrl": "http://localhost:4005/stremio/test-id/manifest.json"}
        with patch.dict(bootstrap.os.environ, {"AIOMETADATA_PROFILE_UUID": "", "SIMKL_CLIENT_ID": "my-simkl-client-id", "ANILIST_TOKEN": "my-anilist-token"}), patch.object(bootstrap, "make_request", return_value=response) as request, patch.object(bootstrap, "update_env_file"):
            result = bootstrap.setup_aiometadata_tamtaro()
            self.assertEqual(result, bootstrap.AIOMETADATA_URL + "/stremio/test-id/manifest.json")
            self.assertEqual(request.call_args.kwargs["data"]["addonPassword"], bootstrap.ADDON_PASSWORD)
            saved_config = request.call_args.kwargs["data"]["config"]
            self.assertNotIn("simklTokenId",saved_config["apiKeys"])
            self.assertNotIn("anilistTokenId",saved_config["apiKeys"])

    def test_metadata_repeat_setup_preserves_linked_accounts(self):
        existing={"apiKeys":{"simklTokenId":"linked-simkl-record","anilistTokenId":"linked-anilist-record"}}
        responses=[{"success":True,"config":existing},{"success":True,"userUUID":"existing"}]
        with patch.dict(bootstrap.os.environ,{"AIOMETADATA_PROFILE_UUID":"existing","SIMKL_CLIENT_ID":"client-not-token"}), patch.object(bootstrap,"make_request",side_effect=responses) as request, patch.object(bootstrap,"update_env_file"):
            bootstrap.setup_aiometadata_tamtaro()
        payload=request.call_args.kwargs['data']['config']
        self.assertEqual(payload['apiKeys']['simklTokenId'],'linked-simkl-record')
        self.assertEqual(payload['apiKeys']['anilistTokenId'],'linked-anilist-record')
        self.assertEqual(request.call_args.kwargs['method'],'PUT')

    def test_metadata_load_failure_does_not_overwrite_existing_profile(self):
        with patch.dict(bootstrap.os.environ,{"AIOMETADATA_PROFILE_UUID":"existing"}), patch.object(bootstrap,"make_request",return_value={"error":401}) as request:
            with self.assertRaises(RuntimeError):bootstrap.setup_aiometadata_tamtaro()
        self.assertEqual(request.call_count,1)

    def test_metadata_rejection_is_not_reported_as_saved(self):
        with patch.object(bootstrap, "make_request", return_value={"error": 401}):
            with self.assertRaises(RuntimeError):
                bootstrap.setup_aiometadata_tamtaro()

    def test_empty_and_failed_responses_are_not_playable(self):
        for value in ({"error": 500}, {"streams": []}, None):
            self.assertEqual(bootstrap.playable_streams(value), [])

    def test_playable_candidates_are_counted(self):
        response = {"streams": [{"url": "https://example.org/video.mp4"}, {"infoHash": "hash"}, {"title": "Error"}]}
        self.assertEqual(len(bootstrap.playable_streams(response)), 2)

    def test_core_smoke_cases_cover_movie_and_episode(self):
        self.assertEqual(
            bootstrap.CORE_SMOKE_CASES,
            (("movie", "tt1375666", "movie"), ("series", "tt0903747:1:1", "episode")),
        )

    def test_subtitles_use_configured_path_even_without_optional_keys(self):
        with patch.dict(bootstrap.os.environ,{"SOOTIO_MODE":"off"}),patch.object(bootstrap,"make_request",return_value={}):
            config=bootstrap.build_default_config(probe_services=False)
        subtitle=next(p for p in config['presets'] if p['instanceId']=='subsense-local')
        self.assertNotEqual(subtitle['options']['manifestUrl'],'http://subsense:3100/manifest.json')
        self.assertEqual(subtitle['options']['resources'],['subtitles'])
        self.assertFalse(any(p['instanceId']=='aiometadata-local' for p in config['presets']))

    def test_sootio_is_sequential_fallback_not_parallel_default(self):
        with patch.dict(bootstrap.os.environ,{"SOOTIO_MODE":"fallback"}):
            config=bootstrap.build_default_config(probe_services=False)
        self.assertEqual(config['groups']['behaviour'],'sequential')
        self.assertEqual(config['groups']['groupings'][1]['addons'],['sootio-local'])
        self.assertEqual(config['groups']['groupings'][1]['condition'],'count(cached(totalStreams)) == 0')
        anime=next(p for p in config['presets'] if p['instanceId']=='anime-kitsu-local')
        self.assertEqual(anime['options']['resources'],['catalog','meta'])

    def test_unreachable_custom_addons_omitted_from_presets_in_core_profile(self):
        # In core profile, debrid-search, sootio, etc. are not running.
        # Ensure build_default_config omits unreachable custom addons so AIOStreams
        # doesn't reject the profile with USER_INVALID_CONFIG.
        def mock_reachable(url, timeout=1.0):
            return "aiometadata" in url

        with patch.object(bootstrap, "is_url_reachable", side_effect=mock_reachable):
            config = bootstrap.build_default_config(aiometadata_manifest="http://aiometadata:4005/stremio/test/manifest.json")
            presets = config.get("presets", [])
            preset_ids = [p.get("instanceId") for p in presets]
            # Reachable ones kept
            self.assertIn("aiometadata-local", preset_ids)
            # Unreachable custom addons omitted
            self.assertNotIn("debrid-search-local", preset_ids)
            self.assertNotIn("sootio-local", preset_ids)
            self.assertNotIn("anime-kitsu-local", preset_ids)
            self.assertNotIn("comet-local", preset_ids)

    def test_builtin_proxy_is_disabled_for_local_base_url(self):
        with patch.object(bootstrap, "BASE_URL", "http://localhost:3001"):
            config = bootstrap.build_default_config()
        self.assertFalse(config["proxy"]["enabled"])

    def test_builtin_proxy_is_enabled_for_public_base_url(self):
        with patch.object(bootstrap, "BASE_URL", "https://aio.example.test"):
            config = bootstrap.build_default_config()
        self.assertTrue(config["proxy"]["enabled"])

    def test_optional_tvdb_key_does_not_block_aiostreams_config(self):
        with patch.object(bootstrap, "TVDB_API_KEY", "optional-tvdb-key"):
            config = bootstrap.build_default_config()
        self.assertNotEqual(config.get("tvdbApiKey"), "optional-tvdb-key")
