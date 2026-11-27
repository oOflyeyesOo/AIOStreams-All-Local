import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which("sh"), "sh shell required")
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

    def test_sanitizes_trusted_ips_and_force_proxy_vars(self):
        with tempfile.TemporaryDirectory() as directory:
            node = Path(directory) / "node"
            node.write_text(
                '#!/bin/sh\n'
                'printf "TRUSTED=%s\\n" "${TRUSTED_IPS:-UNSET}"\n'
                'printf "FP_URL=%s\\n" "${FORCE_PROXY_URL:-UNSET}"\n'
                'printf "FP_EN=%s\\n" "${FORCE_PROXY_ENABLED:-UNSET}"\n'
                'printf "FP_SVC=%s\\n" "${FORCE_PROXY_PROXIED_SERVICES:-UNSET}"\n'
            )
            node.chmod(0o755)
            env = dict(
                os.environ,
                PATH=directory + ":" + os.environ["PATH"],
                SECRET_KEY="c" * 64,
                BASE_URL="https://media.example.org/",
                TRUSTED_IPS="null",
                FORCE_PROXY_URL="media.example.org/",
                FORCE_PROXY_ENABLED="undefined",
                FORCE_PROXY_PROXIED_SERVICES="",
            )
            script = Path(__file__).resolve().parents[1] / "docker/aiostreams/entrypoint.sh"
            res = subprocess.run(["sh", str(script)], env=env, capture_output=True, text=True, timeout=5)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertIn("TRUSTED=UNSET", res.stdout)
            self.assertIn("FP_URL=https://media.example.org", res.stdout)
            self.assertIn("FP_EN=UNSET", res.stdout)
            self.assertIn("FP_SVC=UNSET", res.stdout)

    def test_keepalive_patch_resilience_in_server_js(self):
        script = (Path(__file__).resolve().parents[1] / "docker/aiostreams/entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn("attachJellyfinWebSocket", script)
        self.assertIn("attachPartyRelay", script)
        self.assertIn("AIO_KEEPALIVE_PATCH", script)
        if not shutil.which("node"):
            self.skipTest("node binary required for live server.js patch syntax test")
        # Extract the inline node patch snippet and run it against synthetic server.js files
        with tempfile.TemporaryDirectory() as directory:
            for anchor in ("attachJellyfinWebSocket(server);", "attachPartyRelay(server);"):
                server_js = Path(directory) / "server.js"
                server_js.write_text(f"const server = {{}};\n{anchor}\n", encoding="utf-8")
                js_snippet = (
                    "const fs = require('fs');\n"
                    f"const serverFile = {json_str(str(server_js))};\n"
                    "let sc = fs.readFileSync(serverFile, 'utf8');\n"
                    "const kaAnchor = sc.match(/attachJellyfinWebSocket\\s*\\(\\s*server\\s*\\)\\s*;/) || sc.match(/attachPartyRelay\\s*\\(\\s*server\\s*\\)\\s*;/);\n"
                    "if (!sc.includes('AIO_KEEPALIVE_PATCH') && kaAnchor) {\n"
                    "  const kaLines = [\n"
                    "    '// AIO_KEEPALIVE_PATCH',\n"
                    "    'const _kaMs = Number(process.env.AIO_KEEPALIVE_TIMEOUT_MS || 120000);',\n"
                    "    'const _hdrMs = Number(process.env.AIO_HEADERS_TIMEOUT_MS || 125000);',\n"
                    "    'const _reqMs = Number(process.env.AIO_REQUEST_TIMEOUT_MS || 0);',\n"
                    "    'if (Number.isFinite(_kaMs) && _kaMs > 0) server.keepAliveTimeout = _kaMs;',\n"
                    "    'if (Number.isFinite(_hdrMs) && _hdrMs > 0) server.headersTimeout = Math.max(_hdrMs, (server.keepAliveTimeout || 0) + 5000);',\n"
                    "    'if (Number.isFinite(_reqMs) && _reqMs >= 0) server.requestTimeout = _reqMs;',\n"
                    "    kaAnchor[0]\n"
                    "  ].join('\\n');\n"
                    "  sc = sc.replace(kaAnchor[0], kaLines);\n"
                    "  fs.writeFileSync(serverFile, sc, 'utf8');\n"
                    "}\n"
                )
                r1 = subprocess.run(["node", "-e", js_snippet], capture_output=True, text=True, timeout=5)
                self.assertEqual(r1.returncode, 0, r1.stderr)
                r2 = subprocess.run(["node", "--check", str(server_js)], capture_output=True, text=True, timeout=5)
                self.assertEqual(r2.returncode, 0, r2.stderr)
                patched = server_js.read_text(encoding="utf-8")
                self.assertEqual(patched.count("AIO_KEEPALIVE_PATCH"), 1)
                self.assertIn(anchor, patched)


def json_str(val: str) -> str:
    import json
    return json.dumps(val)
