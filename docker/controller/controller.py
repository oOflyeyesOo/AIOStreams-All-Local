"""Authorized Compose controller. Only apply/status are exposed, over a Unix socket."""
import http.server
import json
import os
from pathlib import Path
import re
import socketserver
import subprocess
import tempfile
import threading
from collections import deque

ROOT = Path('/workspace')
COMPOSE_FILE = os.environ.get('AIO_COMPOSE_FILE', 'docker-compose.yml')
SOCKET = '/runtime/control.sock'
LOCK = threading.Lock()
JOB = {'status': 'idle', 'step': 'Ready to configure', 'logs': deque(maxlen=80), 'exit_code': None}


def host_path(path, host_root):
    if path == '/workspace' or path.startswith('/workspace/'):
        return host_root.rstrip('/') + path[len('/workspace'):]
    return path


def daemon_host_path(path):
    # Linux Compose inside the helper needs Docker Desktop's daemon-side path,
    # rather than interpreting a Windows drive as a relative Linux pathname.
    if re.match(r'^[A-Za-z]:[\\/]', path):
        tail = re.sub('/+', '/', path[2:].replace('\\', '/')).lstrip('/')
        return '/run/desktop/mnt/host/' + path[0].lower() + '/' + tail
    return path


def rewrite_mount_paths(config, host_root):
    """Translate host bind sources, never container destinations or environment values."""
    for service in config['services'].values():
        for mount in service.get('volumes', []):
            if mount.get('type') == 'bind':
                mount['source'] = host_path(mount['source'], host_root)
        build = service.get('build')
        if isinstance(build, dict) and build.get('context'):
            build['context'] = host_path(build['context'], host_root)
    return config


def command_json(arguments):
    result = subprocess.run(arguments, check=True, capture_output=True, text=True, timeout=30)
    return json.loads(result.stdout)


def project_identity(inspect):
    project = inspect['Config'].get('Labels', {}).get('com.docker.compose.project')
    host_root = next((mount['Source'] for mount in inspect['Mounts'] if mount['Destination'] == '/workspace'), None)
    if not project or not host_root:
        raise RuntimeError('Controller must be started by the project Compose file')
    return project, daemon_host_path(host_root)


def redact(line):
    try:
        for entry in (ROOT / '.env').read_text().splitlines():
            key, separator, value = entry.partition('=')
            if separator and len(value) >= 6 and any(item in key for item in ('KEY', 'PASSWORD', 'TOKEN', 'ENCRYPTED')):
                line = line.replace(value, '[REDACTED]')
    except OSError:
        pass
    return re.sub(r'(/stremio/)[^/\s]+/[^/\s]+', r'\1[REDACTED]', line.rstrip())


def log_command(arguments, step, timeout=900):
    with LOCK:
        JOB['step'] = step
    with tempfile.TemporaryFile(mode='w+t') as output:
        process = subprocess.Popen(arguments, stdout=output, stderr=subprocess.STDOUT, text=True)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise RuntimeError('Setup timed out; check service health and retry')
        output.seek(0)
        for line in output:
            with LOCK:
                JOB['logs'].append(redact(line))
        if code:
            raise RuntimeError(f'{step} failed; see setup details')


def apply():
    temporary = None
    try:
        own = command_json(['docker', 'inspect', os.environ['HOSTNAME']])[0]
        project, host_root = project_identity(own)
        if COMPOSE_FILE not in ('docker-compose.yml', 'compose.manager.yml'):
            raise RuntimeError('Unsupported Compose definition')
        compose = ['docker', 'compose', '-p', project, '--project-directory', str(ROOT), '-f', str(ROOT / COMPOSE_FILE)]
        rendered = rewrite_mount_paths(command_json(compose + ['config', '--format', 'json']), host_root)
        descriptor, temporary = tempfile.mkstemp(suffix='.json')
        with os.fdopen(descriptor, 'w') as output:
            json.dump(rendered, output)
        run = ['docker', 'compose', '-p', project, '-f', temporary]
        excluded = {'controller', 'stack-bootstrap'}
        # The manager owns the portal's published port and image version. It also
        # seeds the shared definition; replacing it here would race that write.
        if COMPOSE_FILE == 'compose.manager.yml':
            excluded.add('portal')
        profiles = {'all'}
        env_file = ROOT / '.env'
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith('COMPOSE_PROFILES='):
                    profiles = set(line.split('=', 1)[1].strip().strip("\"'").split(','))
        services = [name for name, service in rendered['services'].items()
                    if name not in excluded and (not service.get('profiles') or profiles.intersection(service['profiles']))
                    and service.get('restart') != 'no']
        databases = [name for name in ('shared-postgres', 'shared-redis', 'mediafusion-mongo') if name in services]
        up = ['up', '-d', '--no-deps', '--no-build', '--wait', '--wait-timeout', '600']
        if databases:
            log_command(run + up + databases, 'Applying database settings')
        for initializer in ('init-postgres', 'init-configs'):
            if initializer in rendered['services']:
                log_command(run + ['run', '--rm', '--no-deps', initializer], 'Preparing application storage')
        # --no-deps is essential: portal depends on controller, and following that
        # dependency could replace this very controller halfway through its job.
        applications = [name for name in services if name not in databases]
        if applications:
            log_command(run + up + applications, 'Applying keys and starting services')
        log_command(run + ['run', '--rm', '--no-deps', 'stack-bootstrap'],
                    'Connecting indexers, metadata, subtitles and players')
        with LOCK:
            JOB.update(status='complete', step='Your manifest is ready', exit_code=0)
    except Exception as error:
        with LOCK:
            JOB['logs'].append(redact(str(error)))
            JOB.update(status='failed', step='Setup needs attention', exit_code=1)
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def respond(self, status, value):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(value).encode())

    def do_GET(self):
        if self.path != '/status':
            self.respond(404, {'error': 'Unknown action'})
            return
        with LOCK:
            snapshot = {**JOB, 'logs': list(JOB['logs'])}
        self.respond(200, snapshot)

    def do_POST(self):
        if self.path != '/apply':
            self.respond(404, {'error': 'Unknown action'})
            return
        with LOCK:
            if JOB['status'] == 'running':
                self.respond(409, {'success': False, 'message': 'Setup is already running.'})
                return
            JOB.update(status='running', step='Applying configuration', exit_code=None, logs=deque(maxlen=80))
        threading.Thread(target=apply, daemon=True).start()
        self.respond(202, {'success': True})


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


if __name__ == '__main__':
    Path('/runtime').mkdir(parents=True, exist_ok=True)
    Path(SOCKET).unlink(missing_ok=True)
    with Server(SOCKET, Handler) as server:
        os.chmod(SOCKET, 0o600)
        server.serve_forever()
