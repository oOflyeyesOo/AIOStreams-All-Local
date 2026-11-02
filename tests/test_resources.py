#!/usr/bin/env python3
"""
Unit tests for tools/resources.py
"""

import unittest
from unittest.mock import MagicMock, patch

from tools.resources import parse_bytes, get_stack_resources


class TestResources(unittest.TestCase):
    def test_parse_bytes(self):
        self.assertEqual(parse_bytes("512MiB"), 512.0)
        self.assertEqual(parse_bytes("1GiB"), 1024.0)
        self.assertEqual(parse_bytes("1.5GiB"), 1536.0)
        self.assertEqual(parse_bytes("1024KiB"), 1.0)
        self.assertEqual(parse_bytes("invalid"), 0.0)

    @patch("subprocess.run")
    def test_get_stack_resources(self, mock_run):
        mock_output = (
            "aiostreams\t0.5%\t120.5MiB / 15.57GiB\t0.75%\t10MB / 5MB\t11\n"
            "unrelated-container\t0.1%\t50MiB / 15.57GiB\t0.31%\t1MB / 1MB\t4\n"
            "stremthru\t1.2%\t80MiB / 15.57GiB\t0.50%\t20MB / 10MB\t15\n"
        )
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = mock_output
        mock_run.return_value = mock_proc

        # Filtered to AIO
        res = get_stack_resources(filter_aio=True)
        self.assertTrue(res["success"])
        self.assertEqual(res["container_count"], 2)
        names = [c["name"] for c in res["containers"]]
        self.assertIn("aiostreams", names)
        self.assertIn("stremthru", names)
        self.assertNotIn("unrelated-container", names)
        self.assertEqual(res["total_mem_mb"], 120.5 + 80.0)

        # Unfiltered
        res_all = get_stack_resources(filter_aio=False)
        self.assertEqual(res_all["container_count"], 3)


if __name__ == "__main__":
    unittest.main()
