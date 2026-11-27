"""Real portal HTTP setup lifecycle against isolated controller/process fixtures.

This checks setup orchestration contracts, not provisioning upstream services.
"""
import base64
from collections import deque
import http.client
import http.server
import importlib.util
import json
import os
from pathlib import Path
import socket
import socketserver
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('setup_acceptance_portal', ROOT / 'docker/all-in-one/portal_server.py')
portal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(portal)


class QuietPortal(portal.AppliancePortalHandler):
    def log_message(self, *args):
        pass


class SetupAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / '.env').write_text('ADDON_PASSWORD=setup-fixture-only\n')
        self.settings = patch.multiple(portal, WEB_ROOT=str(self.root), ENV_PATH=str(self.root / '.env'))
        self.settings.start()
        self.environment = patch.dict(os.environ, {'ADDON_PASSWORD': 'setup-fixture-only',
            'PORTAL_AUTH_REQUIRED': 'true', 'COMPOSE_CONTROL_SOCKET': '', 'AIO_STARTUP_ONLY': ''})
        self.environment.start()
        portal.SETUP_JOB.update(status='idle', step='Ready', logs=deque(maxlen=80), exit_code=None)
        portal.AUTH_FAILURES.clear()
        self.server = portal.ThreadingHTTPServer(('127.0.0.1', 0), QuietPortal)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        # Release any fixture child even if an assertion failed.
        (self.root / 'release').touch()
        deadline = time.monotonic() + 6
        while portal.SETUP_JOB['status'] == 'running' and time.monotonic() < deadline:
            time.sleep(.02)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.environment.stop()
        self.settings.stop()
        self.temp.cleanup()

    def request(self, path, method='GET', authenticated=True, origin=None):
        headers = {'Content-Type': 'application/json'}
        if authenticated:
            headers['Authorization'] = 'Basic ' + base64.b64encode(b'admin:setup-fixture-only').decode()
        if origin:
            headers['Origin'] = origin
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            connection.request(method, path, '{}' if method == 'POST' else None, headers)
            response = connection.getresponse()
            body = response.read()
            return response.status, json.loads(body) if response.getheader('Content-Type', '').startswith('application/json') else {}
        finally:
            connection.close()

    def wait_status(self, expected):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            status, body = self.request('/api/setup-status')
            self.assertEqual(status, 200)
            if body.get('status') == expected:
                return body
            time.sleep(.02)
        self.fail('Setup did not reach ' + expected)

    def install_child(self):
        script = self.root / 'init/bootstrap/setup_stack.py'
        script.parent.mkdir(parents=True)
        script.write_text("""from pathlib import Path
import sys,time
print('[AIOStreams Setup] fixture manifest provisioning',flush=True)
Path('started').touch()
deadline=time.monotonic()+5
while not Path('release').exists() and time.monotonic()<deadline: time.sleep(.01)
sys.exit(int(Path('result').read_text()))
""")
        (self.root / 'result').write_text('0')

    def test_real_child_running_duplicate_completion_and_repeat_failure(self):
        self.install_child()
        self.assertEqual(self.request('/api/setup', 'POST')[0], 202)
        self.wait_status('running')
        self.assertEqual(self.request('/api/setup', 'POST')[0], 409)
        (self.root / 'release').touch()
        done = self.wait_status('complete')
        self.assertEqual(done['exit_code'], 0)
        self.assertTrue(any('fixture manifest provisioning' in line for line in done['logs']))
        (self.root / 'release').unlink()
        (self.root / 'result').write_text('7')
        self.assertEqual(self.request('/api/setup', 'POST')[0], 202)
        self.wait_status('running')
        (self.root / 'release').touch()
        failed = self.wait_status('failed')
        self.assertEqual(failed['exit_code'], 7)
        self.assertEqual(failed['step'], 'Setup needs attention')

    def test_silent_child_times_out_and_can_be_retried(self):
        script = self.root / 'init/bootstrap/setup_stack.py'
        script.parent.mkdir(parents=True)
        script.write_text('import time; time.sleep(30)')
        with patch.object(portal, 'SETUP_TIMEOUT_SECONDS', .2):
            self.assertEqual(self.request('/api/setup', 'POST')[0], 202)
            failed = self.wait_status('failed')
        self.assertEqual(failed['exit_code'], -1)
        self.assertTrue(any('timed out' in line for line in failed['logs']))
        script.write_text('print("[AIOStreams Setup] retry complete")')
        self.assertEqual(self.request('/api/setup', 'POST')[0], 202)
        self.assertEqual(self.wait_status('complete')['exit_code'], 0)

    def test_unauthorized_and_foreign_origin_never_start_child(self):
        self.install_child()
        self.assertEqual(self.request('/api/setup', 'POST', authenticated=False)[0], 401)
        self.assertEqual(self.request('/api/setup', 'POST', origin='https://foreign.invalid')[0], 403)
        self.assertEqual(self.request('/api/setup-status')[1]['status'], 'idle')
        self.assertFalse((self.root / 'started').exists())

    @unittest.skipUnless(hasattr(socketserver, 'UnixStreamServer'), 'Unix controller socket requires Linux')
    def test_controller_socket_running_complete_failure_and_unavailable(self):
        state = {'status': 'idle', 'step': 'Ready', 'logs': [], 'exit_code': None}
        calls = []
        lock = threading.Lock()

        class Controller(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, body):
                encoded = json.dumps(body).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def do_GET(self):
                with lock:
                    calls.append(('GET', self.path))
                    self.reply(200, dict(state))

            def do_POST(self):
                with lock:
                    calls.append(('POST', self.path))
                    if state['status'] == 'running':
                        self.reply(409, {'success': False})
                    else:
                        state.update(status='running', step='Fixture applying', exit_code=None)
                        self.reply(202, {'success': True})

        path = str(self.root / 'controller.sock')
        controller = socketserver.UnixStreamServer(path, Controller)
        worker = threading.Thread(target=controller.serve_forever, daemon=True)
        worker.start()
        try:
            with patch.dict(os.environ, {'COMPOSE_CONTROL_SOCKET': path}):
                self.assertEqual(self.request('/api/setup', 'POST')[0], 202)
                self.assertEqual(self.request('/api/setup-status')[1]['status'], 'running')
                self.assertEqual(self.request('/api/setup', 'POST')[0], 409)
                with lock:
                    state.update(status='complete', step='Fixture done', exit_code=0)
                self.assertEqual(self.request('/api/setup-status')[1]['status'], 'complete')
                self.assertEqual(self.request('/api/setup', 'POST')[0], 202)
                with lock:
                    state.update(status='failed', step='Fixture failed', exit_code=9)
                self.assertEqual(self.request('/api/setup-status')[1]['exit_code'], 9)
                self.assertEqual(calls.count(('POST', '/apply')), 3)
                self.assertIn(('GET', '/status'), calls)
            with patch.dict(os.environ, {'COMPOSE_CONTROL_SOCKET': str(self.root / 'absent.sock')}):
                self.assertEqual(self.request('/api/setup', 'POST')[0], 503)
                self.assertEqual(self.request('/api/setup-status')[0], 503)
        finally:
            controller.shutdown()
            controller.server_close()
            worker.join(timeout=3)
