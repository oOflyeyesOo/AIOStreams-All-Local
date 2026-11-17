import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from tools.metadata_config import prepare_metadata_template, request_metadata, MetadataRequestError


class MetadataConfigTests(unittest.TestCase):
    def test_optional_keys_and_poster_password_match_saved_settings(self):
        raw = {"apiKeys": {"fanart": "template-secret"},
               "artProviders": {"movie": {"logo": "fanart"}, "series": "fanart"},
               "search": {"ai_enabled": True},
               "catalogs": [{"id": "mdblist.test", "enabled": True}],
               "sessionId": "foreign", "configVersion": 123}
        config = prepare_metadata_template(raw, {"TMDB_API_KEY": "fixture", "ADDON_PASSWORD": "a&b"})
        self.assertEqual(config["apiKeys"], {"tmdb": "fixture"})
        self.assertEqual(config["artProviders"]["movie"]["logo"], "tmdb")
        self.assertEqual(config["artProviders"]["series"], "tmdb")
        self.assertFalse(config["search"]["ai_enabled"])
        self.assertFalse(config["catalogs"][0]["enabled"])
        self.assertIn("access_key=a%26b", config["customPosterUrl"])
        self.assertEqual(config["customArt"]["posterUrl"], config["customPosterUrl"])
        self.assertNotIn("sessionId", config)
        self.assertNotIn("configVersion", config)
        self.assertEqual(raw["apiKeys"]["fanart"], "template-secret")

    def test_preserves_local_accounts_and_profile_keys(self):
        previous = {"apiKeys": {"traktTokenId": "local-token", "fanart": "local-key"},
                    "jellyfinUsers": [{"id": "local-user"}], "linkedAccounts": {"test": "saved"}}
        config = prepare_metadata_template({"apiKeys": {"traktTokenId": "foreign"},
            "jellyfinUsers": [{"id": "foreign"}],
            "artProviders": {"movie": {"logo": "fanart"}}}, {"FANART_API_KEY": ""}, previous)
        self.assertEqual(config["apiKeys"], previous["apiKeys"])
        self.assertEqual(config["jellyfinUsers"], previous["jellyfinUsers"])
        self.assertEqual(config["linkedAccounts"], previous["linkedAccounts"])
        self.assertEqual(config["artProviders"]["movie"]["logo"], "fanart")

    def test_rejection_reports_missing_key_without_upstream_secrets(self):
        error = HTTPError("http://metadata/private", 400, "bad", {}, io.BytesIO(
            json.dumps({"missingKeys": ["tmdb"], "error": "secret-password"}).encode()))
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(MetadataRequestError) as caught:
                request_metadata("http://metadata/save", {})
        self.assertEqual(caught.exception.upstream_status, 400)
        self.assertIn("TMDB", str(caught.exception))
        self.assertNotIn("secret-password", str(caught.exception))

    def test_timeout_is_not_a_profile_creation_retry(self):
        with patch("urllib.request.urlopen", side_effect=TimeoutError) as opened:
            with self.assertRaises(MetadataRequestError) as caught:
                request_metadata("http://metadata/update", {})
        self.assertEqual(opened.call_count, 1)
        self.assertEqual(caught.exception.upstream_status, 504)

    def test_false_success_and_malformed_responses_are_rejected(self):
        for data in ({"success": False}, {}, [], {"uuid": "unconfirmed"}):
            with self.subTest(data=data), patch("urllib.request.urlopen",
                                               return_value=io.BytesIO(json.dumps(data).encode())):
                with self.assertRaises(MetadataRequestError):
                    request_metadata("http://metadata/save", {})
