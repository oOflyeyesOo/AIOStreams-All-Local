import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "bootstrap", Path(__file__).resolve().parents[1] / "init/bootstrap/setup_stack.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class BootstrapTests(unittest.TestCase):
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
        with patch.dict(bootstrap.os.environ, {"AIOMETADATA_PROFILE_UUID": ""}), patch.object(bootstrap, "make_request", return_value=response) as request, patch.object(bootstrap, "update_env_file"):
            result = bootstrap.setup_aiometadata_tamtaro()
            self.assertEqual(result, bootstrap.AIOMETADATA_URL + "/stremio/test-id/manifest.json")
            self.assertEqual(request.call_args.kwargs["data"]["addonPassword"], bootstrap.ADDON_PASSWORD)

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

    def test_unreachable_custom_addons_omitted_from_presets_in_core_profile(self):
        # In core profile, debrid-search, sootio, etc. are not running.
        # Ensure build_default_config omits unreachable custom addons so AIOStreams
        # doesn't reject the profile with USER_INVALID_CONFIG.
        def mock_reachable(url, timeout=1.0):
            return "comet" in url or "aiometadata" in url

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
