"""Refresh packaged UI/configuration while preserving saved keys and application data."""
import os
from pathlib import Path
import tempfile


def atomic_write(target, content):
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=target.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(content)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def seed(source, destination, environment):
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.rglob('*'):
        if item.is_file():
            atomic_write(destination / item.relative_to(source), item.read_bytes())
    env_path = destination / '.env'
    values = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            key, separator, value = line.partition('=')
            if separator and not key.startswith('#'):
                values[key] = value
    # Manager settings remain authoritative; provider keys are edited in the UI.
    # Reject dotenv syntax in these settings instead of changing its meaning.
    for key in ('ADDON_PASSWORD', 'AIO_IMAGE_TAG', 'AIO_IMAGE_PREFIX', 'PORT_PORTAL', 'INTERNAL_BIND_IP', 'BASE_URL', 'AIOMETADATA_HOST', 'DOCKER_SOCKET'):
        value = environment.get(key)
        if value:
            if any(char in value for char in ('\n', '\r', '$', '"', "'", '#')):
                raise ValueError(f'{key} contains unsupported configuration characters')
            values[key] = value
    content = ''.join(f'{key}={value}\n' for key, value in values.items())
    atomic_write(env_path, content.encode())


if __name__ == '__main__':
    seed(Path('/opt/aio'), Path('/app'), os.environ)
    os.execvp('python3', ['python3', '-u', '/usr/local/lib/aio/portal_server.py'])
