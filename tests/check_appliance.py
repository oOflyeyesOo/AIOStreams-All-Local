"""Exercise the real docker-run appliance with disposable data and no provider keys."""
import subprocess
import sys
import time


def run(args, timeout=60):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def main():
    image = sys.argv[1]
    name = 'aio-appliance-smoke'
    created = run(['docker', 'run', '-d', '--privileged', '--name', name,
                   '-e', 'COMPOSE_PROFILES=core', '-e', 'ADDON_PASSWORD=appliance-test-password',
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
for host in ('aiostreams', 'comet', 'aiometadata', 'postersplus', 'subsense'):
    socket.getaddrinfo(host, None)
urllib.request.urlopen('http://aiostreams:3000/api/v1/status', timeout=5).close()
job=p.setup_snapshot()
assert job['status'] == 'complete', job['status']
print('PASS: internal DNS, core HTTP, persisted settings, controller and provisioning')
'''
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            result = run(['docker', 'exec', name, 'docker', 'compose', 'exec', '-T', 'portal', 'python3', '-c', probe])
            if result.returncode == 0:
                print(result.stdout)
                return
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
