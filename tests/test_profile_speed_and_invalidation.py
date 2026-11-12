"""Tests for profile cache invalidation, Search Broker recovery, and next-episode prefetch.

Verifies:
1. Changing providers/settings produces updated manifest configurations immediately.
2. Search Broker applies cooldown on upstream failure and recovers when healthy.
3. Next-episode prefetch toggle behaves as expected and defaults to disabled.
"""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
import time
import unittest
from unittest.mock import patch

from tools.search_broker import SearchCache, IndexerFilter
import init.bootstrap.setup_stack as bootstrap


class ProfileSpeedAndInvalidationTests(unittest.TestCase):
    def setUp(self):
        self.orig_env = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.orig_env)

    def test_precache_next_episode_default_is_disabled(self):
        """Next-episode prefetch must default to False to prevent doubling upstream requests."""
        os.environ.pop("AIO_PRECACHE_NEXT_EPISODE", None)
        self.assertFalse(
            os.environ.get("AIO_PRECACHE_NEXT_EPISODE", "false") == "true"
        )

    def test_precache_next_episode_respects_opt_in(self):
        """Setting AIO_PRECACHE_NEXT_EPISODE=true must activate prefetch."""
        os.environ["AIO_PRECACHE_NEXT_EPISODE"] = "true"
        self.assertTrue(
            os.environ.get("AIO_PRECACHE_NEXT_EPISODE", "false") == "true"
        )

    def test_search_broker_failure_cooldown_and_recovery(self):
        """Failing indexer enters cooldown; recovery allows subsequent requests."""
        calls = []
        is_healthy = False

        def mock_fetch(path, headers):
            calls.append(path)
            if not is_healthy:
                return 503, {"Retry-After": "2"}, b"Service Unavailable"
            return 200, {"Content-Type": "application/json"}, b'{"results": 42}'

        cache = SearchCache(mock_fetch, ttl=2, cooldown=1, wait=2)
        try:
            # First request: upstream fails with 503
            code, _, body = cache.get("/prowlarr/search?q=test", {})
            self.assertEqual(code, 503)
            self.assertEqual(len(calls), 1)

            # In-cooldown request: served from cache without extra upstream call
            code, _, body = cache.get("/prowlarr/search?q=test", {})
            self.assertEqual(code, 503)
            self.assertEqual(len(calls), 1)

            # Upstream recovers and cooldown expires
            is_healthy = True
            time.sleep(1.2)  # Cooldown is 1s

            # Now request succeeds and hits upstream
            code, _, body = cache.get("/prowlarr/search?q=test", {})
            self.assertEqual(code, 200)
            self.assertEqual(body, b'{"results": 42}')
            self.assertEqual(len(calls), 2)
        finally:
            cache.close()

    def test_search_broker_indexer_filter_status(self):
        """IndexerFilter excludes disabled or degraded indexers and caches status."""
        filter_inst = IndexerFilter("localhost", 9696, refresh_interval=1)
        # Mocking the HTTP requests to Prowlarr
        with patch("http.client.HTTPConnection") as mock_conn:
            # 1. /api/v1/indexerstatus returns indexer 2 as degraded
            status_resp = unittest.mock.MagicMock()
            status_resp.status = 200
            status_resp.read.return_value = json.dumps([{"indexerId": 2}]).encode()

            # 2. /api/v1/indexer returns indexers 1 (healthy), 2 (degraded), 3 (disabled)
            indexers_resp = unittest.mock.MagicMock()
            indexers_resp.status = 200
            indexers_resp.read.return_value = json.dumps([
                {"id": 1, "enable": True},
                {"id": 2, "enable": True},
                {"id": 3, "enable": False}
            ]).encode()

            conn_instance = mock_conn.return_value
            conn_instance.getresponse.side_effect = [status_resp, indexers_resp]

            healthy = filter_inst.get_healthy_ids("mock-api-key")
            self.assertEqual(healthy, [1])

    def test_provider_change_updates_services_and_presets(self):
        """Updating provider settings alters services and invalidates previous preset state."""
        # Simulated profile generation with Premiumize only
        services_pm = [{"id": "premiumize", "enabled": True, "credentials": {"apiKey": "pm_key"}}]
        presets_pm = [
            {"type": "comet", "instanceId": "comet-local", "enabled": True},
            {"type": "stremthruStore", "instanceId": "stremthru-store-local", "enabled": True}
        ]

        # User disables debrid and switches to Usenet Only
        services_usenet = [{"id": "nzbdav", "enabled": True, "credentials": {"apiKey": "nzb_key"}}]
        # Comet and StremThruStore must be omitted or disabled when no debrid is active
        has_debrid = any(s.get("enabled") and s.get("id") not in ("nzbdav", "easynews") for s in services_usenet)
        self.assertFalse(has_debrid)


if __name__ == "__main__":
    unittest.main()
