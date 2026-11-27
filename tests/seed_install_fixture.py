"""Seed a credential-free native profile in the isolated post-setup fixture only.

Run inside compose.acceptance.yml portal before restarting AIOStreams to hydrate
its local alias. This deliberately bypasses bootstrap and is not a setup test.
"""
import json
import os
from pathlib import Path
import sys
import urllib.request

from check_fresh_install_live import FIXTURE_PASSWORD, NoRedirect, require_fixture


ROOT = Path('/app')
INSTALL = ROOT / 'data/aiostreams/aiostreams_install.json'


def main():
    try:
        require_fixture(ROOT, os.environ)
        if os.environ.get('AIO_FRESH_INSTALL_TEST_PROJECT') != 'aio-fresh-install':
            raise RuntimeError('Isolated post-setup project required')
        if INSTALL.exists():
            raise RuntimeError('Fixture profile already exists; use a fresh disposable volume')
        config = {
            'addonName': 'Post-setup acceptance fixture',
            'accessKey': FIXTURE_PASSWORD,
            'presets': [{'type': 'custom', 'instanceId': 'local-acceptance-fixture',
                'enabled': True, 'options': {'name': 'Local fixture',
                'manifestUrl': 'http://media-fixture:8099/manifest.json',
                'resources': ['catalog', 'meta', 'stream'], 'timeout': 5000}}], 'services': [],
            'formatter': {'id': 'tamtaro'},
            'sortCriteria': {'global': []},
            'proxy': {'id': 'builtin', 'enabled': False},
            'titleMatching': {'enabled': False},
            'yearMatching': {'enabled': False},
            'precacheNextEpisode': False,
            'preloadStreams': {'enabled': False},
            'enableSeadex': False,
            'remuxDb': {'enabled': False},
        }
        request = urllib.request.Request('http://aiostreams:3000/api/v1/user',
            data=json.dumps({'config': config, 'password': FIXTURE_PASSWORD}).encode(),
            headers={'Content-Type': 'application/json'})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=30) as response:
            result = json.load(response)
        if not result.get('success'):
            raise RuntimeError('Native fixture registration rejected')
        data = result['data']
        uuid, token = data.get('uuid'), data.get('encryptedPassword')
        if not isinstance(uuid, str) or not uuid or not isinstance(token, str) or not token:
            raise RuntimeError('Native fixture identity missing')
        INSTALL.parent.mkdir(parents=True, exist_ok=True)
        # Runtime-only credential material stays on isolated named fixture volume.
        descriptor = os.open(INSTALL, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
            json.dump({'uuid': uuid, 'encrypted_password': token,
                       'password': FIXTURE_PASSWORD}, output)
        print('PASS: credential-free native fixture created; restart AIOStreams to hydrate alias')
        return 0
    except Exception as error:
        print('FAIL: fixture seed (' + type(error).__name__ + ')', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
