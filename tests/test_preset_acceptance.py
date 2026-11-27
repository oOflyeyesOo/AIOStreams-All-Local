"""Portal Apply Preset contract tests over real local HTTP connections.

The metadata service below is a deterministic protocol fixture, not AIOMetadata.
These tests prove portal integration and state handling, not upstream compatibility
or validation of a real provider account.
"""
import base64
import copy
import http.client
import http.server
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('preset_acceptance_portal', ROOT / 'docker/all-in-one/portal_server.py')
portal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(portal)
PASSWORD = 'preset-fixture-password'
PROVIDER_KEY = 'preset-fixture-tmdb-key'
PROFILE = 'fixture-metadata-profile'


class MetadataFixture(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.dispatch()

    def do_PUT(self):
        self.dispatch()

    def dispatch(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        state = self.server.state
        state['calls'].append((self.command, self.path, copy.deepcopy(body)))
        failure = state.get('failure')
        if failure and self.path.startswith(failure['path']):
            status, result = failure['status'], failure['body']
        elif body.get('password') != PASSWORD or body.get('addonPassword') != PASSWORD:
            status, result = 401, {'error': 'fixture password mismatch'}
        elif self.path == '/api/config/save' and self.command == 'POST':
            state['creates'] += 1
            state['config'] = {**body['config'], 'configVersion': 1}
            status, result = 200, {'success': True, 'userUUID': PROFILE}
        elif self.path == '/api/config/load/' + PROFILE and self.command == 'POST':
            status, result = 200, {'success': True, 'config': state['config']}
        elif self.path == '/api/config/update/' + PROFILE and self.command == 'PUT':
            if body.get('baseVersion') != state['config']['configVersion']:
                status, result = 409, {'error': 'stale version'}
            else:
                state['updates'] += 1
                state['config'] = {**body['config'], 'configVersion': body['baseVersion'] + 1}
                status, result = 200, {'success': True, 'userUUID': PROFILE}
        else:
            status, result = 404, {'error': 'unknown fixture endpoint'}
        raw = result if isinstance(result, bytes) else json.dumps(result).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class QuietPortal(portal.AppliancePortalHandler):
    def log_message(self, *args):
        pass


class PresetHttpAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env_file = self.root / '.env'
        self.env_file.write_text('ADDON_PASSWORD=' + PASSWORD + '\nTMDB_API_KEY=' + PROVIDER_KEY + '\n')
        template_dir = self.root / 'templates/aiometadata-configs'
        template_dir.mkdir(parents=True)
        template = json.loads((ROOT / 'templates/aiometadata-configs/tamtaro-aiometadata-with-anime.json').read_text(encoding='utf-8'))
        config = template.get('config', template)
        config.update({'userUUID': 'foreign-identity', 'apiKeys': {'tmdb': 'foreign-key'},
                       'tokens': {'foreign': 'foreign-token'}, 'accounts': {'foreign': 'foreign-account'}})
        (template_dir / 'fixture.json').write_text(json.dumps(template))
        self.upstream = http.server.ThreadingHTTPServer(('127.0.0.1', 0), MetadataFixture)
        self.upstream.state = {'calls': [], 'config': None, 'creates': 0, 'updates': 0}
        self.start_server(self.upstream)
        self.environment = patch.dict(os.environ, {'PORTAL_AUTH_REQUIRED': 'true',
            'AIOMETADATA_URL': 'http://127.0.0.1:' + str(self.upstream.server_port)}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.paths = patch.multiple(portal, WEB_ROOT=str(self.root), ENV_PATH=str(self.env_file),
                                    ENV_EXAMPLE_PATH=str(self.root / '.env.example'))
        self.paths.start()
        self.addCleanup(self.paths.stop)
        portal.AUTH_FAILURES.clear()
        self.server = portal.ThreadingHTTPServer(('127.0.0.1', 0), QuietPortal)
        self.start_server(self.server)

    def start_server(self, server):
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def close():
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        self.addCleanup(close)

    def apply(self, authenticated=True, origin=None):
        headers = {'Content-Type': 'application/json'}
        if authenticated:
            headers['Authorization'] = 'Basic ' + base64.b64encode(('admin:' + PASSWORD).encode()).decode()
        if origin:
            headers['Origin'] = origin
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            connection.request('POST', '/api/aiometadata/apply-template', json.dumps({'template': 'fixture.json'}), headers)
            response = connection.getresponse()
            raw = response.read()
            return response.status, raw
        finally:
            connection.close()

    def assert_no_secrets(self, raw):
        for secret in (PASSWORD, PROVIDER_KEY, 'foreign-key', 'foreign-token', 'upstream-secret'):
            self.assertNotIn(secret.encode(), raw)

    def test_create_and_reapply_preserve_identity_credentials_and_user_accounts(self):
        for authenticated, origin, expected in ((False, None, 401), (True, 'https://foreign.invalid', 403)):
            status, _ = self.apply(authenticated, origin)
            self.assertEqual(status, expected)
        self.assertEqual(self.upstream.state['calls'], [])
        status, raw = self.apply()
        self.assertEqual(status, 200)
        self.assert_no_secrets(raw)
        self.assertEqual(json.loads(raw)['uuid'], PROFILE)
        self.assertEqual(portal.read_saved_env()['AIOMETADATA_PROFILE_UUID'], PROFILE)
        self.assertEqual(portal.read_saved_env()['AIOMETADATA_TEMPLATE'], 'fixture.json')
        config = self.upstream.state['config']
        self.assertEqual(config['apiKeys']['tmdb'], PROVIDER_KEY)
        self.assertNotIn('userUUID', config)
        self.assertNotIn('tokens', config)
        self.assertNotIn('accounts', config)
        # Simulate customization performed directly in the metadata dashboard.
        config['accounts'] = {'mine': 'saved-account'}
        config['tokens'] = {'mine': 'saved-token'}
        config['apiKeys']['traktTokenId'] = 'saved-trakt-link'
        config['configVersion'] = 9
        status, raw = self.apply()
        self.assertEqual(status, 200)
        self.assert_no_secrets(raw)
        self.assertEqual(json.loads(raw)['uuid'], PROFILE)
        self.assertEqual(self.upstream.state['creates'], 1)
        self.assertEqual(self.upstream.state['updates'], 1)
        calls = self.upstream.state['calls']
        self.assertEqual([(method, path) for method, path, _ in calls], [
            ('POST', '/api/config/save'), ('POST', '/api/config/load/' + PROFILE),
            ('PUT', '/api/config/update/' + PROFILE)])
        self.assertEqual(calls[-1][2]['baseVersion'], 9)
        self.assertEqual(self.upstream.state['config']['accounts'], {'mine': 'saved-account'})
        self.assertEqual(self.upstream.state['config']['tokens'], {'mine': 'saved-token'})
        self.assertEqual(self.upstream.state['config']['apiKeys']['traktTokenId'], 'saved-trakt-link')

    def test_upstream_failures_preserve_saved_identity_and_never_create_replacement(self):
        self.assertEqual(self.apply()[0], 200)
        before_env = self.env_file.read_bytes()
        before_config = copy.deepcopy(self.upstream.state['config'])
        for path, upstream_status, portal_status, body in (
            ('/api/config/load/', 401, 422, {'message': 'upstream-secret ' + PASSWORD}),
            ('/api/config/update/', 409, 409, {'message': 'upstream-secret ' + PROVIDER_KEY}),
            ('/api/config/update/', 400, 400, {'missingKeys': ['tmdb'], 'message': 'upstream-secret'}),
            ('/api/config/update/', 200, 502, b'<html>upstream-secret</html>'),
        ):
            with self.subTest(path=path, status=upstream_status):
                self.upstream.state['calls'].clear()
                self.upstream.state['failure'] = {'path': path, 'status': upstream_status, 'body': body}
                status, raw = self.apply()
                self.assertEqual(status, portal_status)
                self.assert_no_secrets(raw)
                self.assertEqual(json.loads(raw)['errorCode'], 'AIOMETADATA_PRESET_FAILED')
                self.assertEqual(self.env_file.read_bytes(), before_env)
                self.assertEqual(self.upstream.state['config'], before_config)
                self.assertEqual(self.upstream.state['creates'], 1)
                self.assertNotIn('/api/config/save', [entry[1] for entry in self.upstream.state['calls']])
                if upstream_status == 400:
                    self.assertIn(b'TMDB', raw)
