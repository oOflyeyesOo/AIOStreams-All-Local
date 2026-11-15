"""Exercise the real docker-run appliance with disposable data and no provider keys."""
import subprocess
import sys
import time
import urllib.request


def run(args, timeout=60):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def main():
    image = sys.argv[1]
    name = 'aio-appliance-smoke'
    created = run(['docker', 'run', '-d', '--privileged', '--name', name,
                   '-p', '127.0.0.1::8082', '-p', '127.0.0.1::9696',
                   '-e', 'COMPOSE_PROFILES=scrapers', '-e', 'ADDON_PASSWORD=appliance-test-password',
                   '-e', 'BASE_URL=http://127.0.0.1:3001', image])
    if created.returncode:
        raise RuntimeError('Could not start disposable appliance')
    try:
        probe = '''import importlib.util, os, socket, urllib.request
s=importlib.util.spec_from_file_location('portal','/app/docker/all-in-one/portal_server.py')
p=importlib.util.module_from_spec(s); s.loader.exec_module(p)
assert os.environ.get('COMPOSE_CONTROL_SOCKET') == '/runtime/control.sock'
assert os.environ.get('AIO_STARTUP_ONLY') != 'true'
assert os.path.realpath('/app/.env') == '/data/.env'
for host in ('aiostreams', 'comet', 'aiometadata', 'postersplus', 'subsense', 'prowlarr', 'infinidysk', 'stremthru', 'zilean'):
    socket.getaddrinfo(host, None)
for url in ('http://aiostreams:3000/api/v1/status', 'http://prowlarr:9696/ping', 'http://infinidysk:3000/healthz'):
    urllib.request.urlopen(url, timeout=5).close()
job=p.setup_snapshot()
if job['status'] == 'failed':
    print(*job.get('logs', [])[-24:], sep=chr(10), flush=True)
    raise SystemExit(42)
assert job['status'] == 'complete', job['status']
print('PASS: internal DNS, core HTTP, persisted settings, controller and provisioning')
'''
        metadata_probe = '''import importlib.util, json, os, urllib.request
os.environ.update(AIO_SKIP_ENV_FILE='true', TMDB_API_KEY='fixture-not-a-provider-key',
                  FANART_API_KEY='', AIOMETADATA_PROFILE_UUID='')
s=importlib.util.spec_from_file_location('bootstrap','/app/init/bootstrap/setup_stack.py')
b=importlib.util.module_from_spec(s); s.loader.exec_module(b)
saved={}
b.update_env_file=lambda key, value: saved.update({key: value})
url=b.setup_aiometadata_tamtaro()
assert saved.get('AIOMETADATA_PROFILE_UUID'), 'No metadata profile saved'
with urllib.request.urlopen(url, timeout=10) as response:
    assert json.load(response).get('id'), 'Metadata manifest missing ID'
print('PASS: AIOMetadata profile save and manifest without Fanart')
'''
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            result = run(['docker', 'exec', name, 'docker', 'compose', 'exec', '-T', 'portal', 'python3', '-c', probe])
            if result.returncode == 0:
                print(result.stdout)
                for port, path in ((8082, '/'), (9696, '/ping')):
                    mapping = run(['docker', 'port', name, f'{port}/tcp'])
                    if mapping.returncode:
                        raise RuntimeError(f'Appliance did not publish port {port}')
                    with urllib.request.urlopen('http://' + mapping.stdout.strip() + path, timeout=15) as response:
                        assert response.status == 200, f'Published service on {port} is unavailable'
                print('PASS: published Stremio Web and Prowlarr ports are reachable')
                metadata = run(['docker', 'exec', name, 'docker', 'compose',
                                'exec', '-T', 'portal', 'python3', '-c', metadata_probe])
                if metadata.returncode:
                    print(metadata.stderr[-2000:])
                    raise RuntimeError('Metadata profile save or manifest verification failed')
                print(metadata.stdout.splitlines()[-1])
                return
            if result.returncode == 42:
                print(result.stdout[-4000:])
                break
            state = run(['docker', 'inspect', '--format', '{{.State.Running}}', name])
            if state.stdout.strip() != 'true':
                break
            time.sleep(10)
        # This is a disposable fixture, never an installation with user credentials.
        print(run(['docker', 'logs', '--tail', '100', name]).stdout)
        print(run(['docker', 'exec', name, 'docker', 'compose', 'ps', '-a']).stdout)
        print(result.stderr[-2000:])
        raise RuntimeError('Appliance network/controller provisioning did not become ready')
    finally:
        run(['docker', 'rm', '-f', '-v', name])


if __name__ == '__main__':
    main()
