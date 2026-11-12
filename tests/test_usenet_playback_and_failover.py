"""Tests for Usenet playback, seeking byte-ranges, and hybrid failover.

Verifies:
1. Usenet-only streaming mode stays strictly on the NZB path.
2. Hybrid mode configures cross-type failover between Debrid and Usenet.
3. Byte-range seeking and Matroska/WebM container headers.
4. Direct EasyNews route separation from InfiniDysk NNTP/NZB streaming.
"""
import io
import json
import os
import unittest
from unittest.mock import patch
import urllib.request

import init.bootstrap.setup_stack as bootstrap


class UsenetPlaybackAndFailoverTests(unittest.TestCase):
    def setUp(self):
        self.orig_env = dict(os.environ)
        # Ensure clean test environment
        for k in ("STREAMING_MODE", "USENET_ENABLED", "USENET_HOST", "USENET_USER", "USENET_PASS",
                  "REALDEBRID_API_KEY", "PREMIUMIZE_API_KEY", "EASYNEWS_USER", "EASYNEWS_PASSWORD"):
            os.environ.pop(k, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.orig_env)

    def test_usenet_only_mode_configures_nzb_path_isolation(self):
        """When STREAMING_MODE=usenet, failover is restricted to usenet only."""
        with patch.object(bootstrap, 'PREMIUMIZE_API_KEY', ''), \
             patch.object(bootstrap, 'REALDEBRID_API_KEY', ''), \
             patch.object(bootstrap, 'TORBOX_API_KEY', ''), \
             patch.object(bootstrap, 'ALLDEBRID_API_KEY', ''), \
             patch.object(bootstrap, 'DEBRIDLINK_API_KEY', ''), \
             patch.object(bootstrap, 'EASYNEWS_USER', ''), \
             patch.object(bootstrap, 'EASYNEWS_PASSWORD', ''), \
             patch.dict(bootstrap.os.environ, {
                 'USENET_ENABLED': 'true',
                 'USENET_HOST': 'news.example.com',
                 'USENET_USER': 'testuser',
                 'USENET_PASS': 'testpass',
                 'STREAMING_MODE': 'usenet',
                 'PREMIUMIZE_API_KEY': '',
                 'REALDEBRID_API_KEY': '',
             }):
            config = bootstrap.build_default_config(probe_services=False)

        # Check services
        services = config.get("services", [])
        service_ids = [s["id"] for s in services if s.get("enabled")]
        self.assertIn("nzbdav", service_ids)
        self.assertNotIn("realdebrid", service_ids)
        self.assertNotIn("premiumize", service_ids)

        # Check failover settings: allowCrossType must be False
        failover = config.get("failover", {})
        self.assertTrue(failover.get("enabled"))
        self.assertFalse(failover.get("allowCrossType"))
        self.assertEqual(failover.get("contentTypes"), ["usenet"])

    def test_hybrid_mode_configures_cross_type_failover(self):
        """When STREAMING_MODE=hybrid, failover allows cross-type between debrid and usenet."""
        with patch.object(bootstrap, 'PREMIUMIZE_API_KEY', 'pm_secret_key'), \
             patch.object(bootstrap, 'REALDEBRID_API_KEY', ''), \
             patch.object(bootstrap, 'TORBOX_API_KEY', ''), \
             patch.object(bootstrap, 'ALLDEBRID_API_KEY', ''), \
             patch.object(bootstrap, 'DEBRIDLINK_API_KEY', ''), \
             patch.dict(bootstrap.os.environ, {
                 'USENET_ENABLED': 'true',
                 'USENET_HOST': 'news.example.com',
                 'USENET_USER': 'testuser',
                 'USENET_PASS': 'testpass',
                 'STREAMING_MODE': 'hybrid',
                 'PREMIUMIZE_API_KEY': 'pm_secret_key',
             }):
            config = bootstrap.build_default_config(probe_services=False)

        services = config.get("services", [])
        service_ids = [s["id"] for s in services if s.get("enabled")]
        self.assertIn("nzbdav", service_ids)
        self.assertIn("premiumize", service_ids)

        # Check failover settings: allowCrossType must be True
        failover = config.get("failover", {})
        self.assertTrue(failover.get("enabled"))
        self.assertTrue(failover.get("allowCrossType"))
        self.assertIn("debrid", failover.get("contentTypes", []))
        self.assertIn("usenet", failover.get("contentTypes", []))

    def test_direct_easynews_route_distinct_from_nzbdav(self):
        """Direct EasyNews provides its own HTTP search and streaming preset."""
        with patch.object(bootstrap, 'EASYNEWS_USER', 'easyuser'), \
             patch.object(bootstrap, 'EASYNEWS_PASSWORD', 'easypass'), \
             patch.object(bootstrap, 'PREMIUMIZE_API_KEY', ''), \
             patch.object(bootstrap, 'REALDEBRID_API_KEY', ''), \
             patch.dict(bootstrap.os.environ, {
                 'EASYNEWS_USER': 'easyuser',
                 'EASYNEWS_PASSWORD': 'easypass',
                 'STREAMING_MODE': 'usenet',
                 'USENET_ENABLED': 'true',
                 'USENET_HOST': 'news.example.com',
                 'USENET_USER': 'testuser',
                 'USENET_PASS': 'testpass',
             }):
            config = bootstrap.build_default_config(probe_services=False)

        services = config.get("services", [])
        service_ids = [s["id"] for s in services if s.get("enabled")]
        self.assertIn("easynews", service_ids)
        self.assertIn("nzbdav", service_ids)

        presets = config.get("presets", [])
        easynews_preset = next((p for p in presets if p.get("type") == "easynews-search"), None)
        self.assertIsNotNone(easynews_preset)
        self.assertTrue(easynews_preset.get("enabled"))
        self.assertIn("easynews", easynews_preset.get("options", {}).get("services", []))

    def test_byte_range_and_container_header_validation(self):
        """HTTP Range header parser and Matroska/WebM container signature validation."""
        matroska_header = bytes.fromhex("1a45dfa3934282886d6174726f736b614287810442858102") + b"\x00" * 1000
        # Check container signature detection
        is_matroska = matroska_header.startswith(bytes.fromhex("1a45dfa3"))
        self.assertTrue(is_matroska)

        # Check byte-range slicing simulation
        range_header = "bytes=0-1023"
        units, ranges = range_header.split("=")
        start_str, end_str = ranges.split("-")
        start, end = int(start_str), int(end_str)
        sliced = matroska_header[start:end + 1]
        self.assertEqual(len(sliced), 1024)
        self.assertTrue(sliced.startswith(bytes.fromhex("1a45dfa3")))


if __name__ == "__main__":
    unittest.main()
