"""Wait for the disposable release bootstrap to exit successfully before acceptance.

Container health only proves that dependencies are reachable; this one-shot job
must finish before profile/manifest assertions run. Never prints bootstrap logs.
"""
import argparse
import re
import subprocess
import sys


class BootstrapCompletionError(RuntimeError):
    """Controlled, credential-free diagnostic for a failed acceptance gate."""


def wait_for_bootstrap(project, compose, env_file, timeout=600):
    if project != 'aio-release':
        raise BootstrapCompletionError('Only the disposable aio-release project is supported')
    if not isinstance(timeout, int) or not 1 <= timeout <= 1800:
        raise BootstrapCompletionError('Bootstrap timeout must be between 1 and 1800 seconds')
    command = ['docker', 'compose', '-p', project, '--env-file', str(env_file),
               '-f', str(compose), 'ps', '--all', '--quiet', 'stack-bootstrap']
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        container = result.stdout.strip()
        if result.returncode or not re.fullmatch(r'[0-9a-f]{12,64}', container):
            raise BootstrapCompletionError('Expected exactly one release bootstrap container')
        result = subprocess.run(['docker', 'wait', container], capture_output=True,
                                text=True, timeout=timeout)
        if result.returncode:
            raise BootstrapCompletionError('Docker could not wait for release bootstrap completion')
        value = result.stdout.strip()
        if not re.fullmatch(r'\d+', value):
            raise BootstrapCompletionError('Docker returned an invalid bootstrap exit status')
        exit_code = int(value)
        if exit_code:
            raise BootstrapCompletionError('Release bootstrap failed with exit code ' + str(exit_code))
    except subprocess.TimeoutExpired:
        raise BootstrapCompletionError('Release bootstrap did not finish before the acceptance deadline') from None
    except OSError:
        raise BootstrapCompletionError('Docker is unavailable for the bootstrap completion check') from None
    return container


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, choices=('aio-release',))
    parser.add_argument('--compose', required=True)
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--timeout', type=int, default=600)
    args = parser.parse_args(argv)
    try:
        wait_for_bootstrap(args.project, args.compose, args.env_file, args.timeout)
    except BootstrapCompletionError as error:
        print('FAIL: ' + str(error), file=sys.stderr)
        return 1
    print('PASS: release bootstrap completed successfully; profile readiness can now be checked', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
