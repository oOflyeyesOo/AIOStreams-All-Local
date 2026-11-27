import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tests import check_fresh_install_live as acceptance


class FreshInstallAcceptanceTests(unittest.TestCase):
    def fixture(self, root):
        (root / '.env').write_text('ADDON_PASSWORD=' + acceptance.FIXTURE_PASSWORD + '\n')
        return {'AIO_FRESH_INSTALL_TEST': 'true', 'AIO_FRESH_INSTALL_TEST_PROJECT': 'aio-release',
                'ADDON_PASSWORD': acceptance.FIXTURE_PASSWORD}

    def test_guard_rejects_real_credentials_in_either_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = self.fixture(root)
            acceptance.require_fixture(root, env)
            for key in ('TMDB_API_KEY', 'PREMIUMIZE_API_KEY', 'USENET_EXTRA_SERVERS_B64', 'USENET_PASS', 'USENET_USER_B64', 'USENET_PASS_B64'):
                with self.subTest(key=key):
                    with self.assertRaises(RuntimeError):
                        acceptance.require_fixture(root, {**env, key: 'private-fixture'})
                    (root / '.env').write_text('ADDON_PASSWORD=' + acceptance.FIXTURE_PASSWORD + '\n' + key + '=private-fixture\n')
                    with self.assertRaises(RuntimeError):
                        acceptance.require_fixture(root, env)
                    self.fixture(root)
            for key in ('AIO_FRESH_INSTALL_TEST', 'AIO_FRESH_INSTALL_TEST_PROJECT', 'ADDON_PASSWORD'):
                with self.assertRaises(RuntimeError):
                    acceptance.require_fixture(root, {**env, key: 'wrong'})

    def test_client_rejects_nonlocal_destinations(self):
        for url in ('https://example.org', 'http://portal:8088', 'http://localhost:8088/evil', 'http://user@localhost:8088'):
            with self.assertRaises(ValueError):
                acceptance.Client(url)

    def test_prepare_verify_and_changed_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = self.fixture(root)
            state = root / 'data/acceptance.json'

            class Client:
                token = 'fixture-install-token'
                def json(self, path, payload=None):
                    if path == '/api/save-env':
                        with (root / '.env').open('a') as output:
                            output.write(''.join(key + '=' + value + '\n' for key, value in payload.items()))
                        return payload
                    if path == '/api/env':
                        return acceptance.saved_values(root)
                    if path == '/api/manifest-info':
                        return {'uuid': 'fixture-id', 'encryptedPassword': self.token, 'watchUrl': '/watch/',
                                'jellyfinWebPlayer': 'http://localhost:3001/jellyfin/fixture-id/' + self.token + '/web/'}
                    return {'id': 'fixture-manifest', 'resources': ['stream']}
                def request(self, path, authenticated=True):
                    if not authenticated:
                        return 401, b'', {}
                    return 302, b'', {'Location': 'http://localhost:3001/jellyfin/fixture-id/' + self.token + '/web/'}
                def player(self, path):
                    if path != '/jellyfin/fixture-id/' + self.token + '/web/':
                        raise AssertionError('Unexpected internal path')
                    return 200, b'<html><body>Player</body></html>', {'Content-Type': 'text/html'}

            client = Client()
            acceptance.run('prepare', root, state, client, env)
            self.assertNotIn(client.token, state.read_text())
            acceptance.run('verify', root, state, client, env)
            with patch.object(client, 'request', side_effect=lambda path, authenticated=True: (401, b'', {}) if not authenticated else (302, b'', {'Location': 'http://private.example/'})), patch.object(client, 'player') as fetch:
                with self.assertRaises(RuntimeError):
                    acceptance.inspect_portal(client)
                fetch.assert_not_called()
            original_json = client.json
            with patch.object(client, 'json', side_effect=lambda path, payload=None: {} if path == '/api/export-manifest' else original_json(path, payload)):
                with self.assertRaises(RuntimeError):
                    acceptance.inspect_portal(client)
            saved = (root / '.env').read_text()
            (root / '.env').write_text(saved.replace('ENABLE_TORRENTIO=false', 'ENABLE_TORRENTIO=true'))
            with self.assertRaises(RuntimeError):
                acceptance.run('verify', root, state, client, env)
            (root / '.env').write_text(saved)
            def invalid_player_info(path, payload=None):
                result = original_json(path, payload)
                if path == '/api/manifest-info':
                    result['jellyfinWebPlayer'] = 'http://localhost:3001/wrong-path'
                return result
            with patch.object(client, 'json', side_effect=invalid_player_info), patch.object(client, 'request', side_effect=lambda path, authenticated=True: (401, b'', {}) if not authenticated else (302, b'', {'Location': 'http://localhost:3001/wrong-path'})), patch.object(client, 'player') as fetch:
                with self.assertRaises(RuntimeError):
                    acceptance.inspect_portal(client)
                fetch.assert_not_called()
            client.token = 'changed'
            with self.assertRaises(RuntimeError):
                acceptance.run('verify', root, state, client, env)
            with self.assertRaises(RuntimeError):
                acceptance.run('prepare', root, root / 'unsafe.json', client, env)
