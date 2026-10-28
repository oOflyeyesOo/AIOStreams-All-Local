import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class EntrypointTests(unittest.TestCase):
    def run_entrypoint(self, secret):
        with tempfile.TemporaryDirectory() as directory:
            node = Path(directory) / "node"
            node.write_text('#!/bin/sh\nprintf "BASE=%s\\n" "$BASE_URL"\n')
            node.chmod(0o755)
            env = dict(os.environ, PATH=directory + ":" + os.environ["PATH"],
                       SECRET_KEY=secret, BASE_URL="example.org/", ADDON_PASSWORD="test")
            script = Path(__file__).resolve().parents[1] / "docker/aiostreams/entrypoint.sh"
            return subprocess.run(["sh", str(script)], env=env, capture_output=True, timeout=5)

    def test_invalid_secret_fails_without_logging_it(self):
        result = self.run_entrypoint("private-invalid-secret")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(b"private-invalid-secret", result.stdout + result.stderr)

    def test_valid_secret_and_base_url_start(self):
        result = self.run_entrypoint("a" * 64)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"BASE=https://example.org", result.stdout)

    def test_quoted_valid_secret_starts(self):
        self.assertEqual(self.run_entrypoint('"' + "b" * 64 + '"').returncode, 0)
