"""Credential-free portal acceptance for an explicitly disposable release stack.

Run prepare, restart the portal from the host, then run verify with the same state.
This checks setup outputs and native player launch HTML, not paid streaming or browser decoding.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request

FIXTURE_PASSWORD = 'package-test-only-password'
SETTINGS = {'ENABLE_TORRENTIO': 'false', 'ENABLE_DMM': 'false',
            'ENABLE_REMUXDB': 'false', 'ENABLE_ANIME_SOURCES': 'false',
            'JELLYFIN_ENABLED': 'true'}
PRIVATE_FIELDS = ('USENET_USER_B64', 'USENET_PASS_B64', 'EASYNEWS_USER', 'EASYNEWS_PASSWORD', 'USENET_USER', 'USENET_PASS',
                  'DISCORD_WEBHOOK_URL', 'CLOUDFLARE_TUNNEL_TOKEN', 'ANILIST_TOKEN',
                  'USENET_EXTRA_SERVERS', 'USENET_EXTRA_SERVERS_B64',
                  'USENET_EXTRA_INDEXERS', 'USENET_EXTRA_INDEXERS_B64')


class AcceptanceError(RuntimeError):
    """An actionable check failure with a credential-free, controlled message."""


def saved_values(root):
    result = {}
    for line in (root / '.env').read_text(encoding='utf-8').splitlines():
        key, sep, value = line.partition('=')
        if sep and not key.lstrip().startswith('#'):
            result[key.strip()] = value.strip().strip('\"').strip("'")
    return result


def require_fixture(root, environment):
    if environment.get('AIO_FRESH_INSTALL_TEST') != 'true':
        raise AcceptanceError('Explicit disposable acceptance opt-in required')
    if environment.get('AIO_FRESH_INSTALL_TEST_PROJECT') not in ('aio-release', 'aio-fresh-install'):
        raise AcceptanceError('Disposable acceptance project required')
    saved = saved_values(root)
    for values in (environment, saved):
        if values.get('ADDON_PASSWORD') != FIXTURE_PASSWORD:
            raise AcceptanceError('Fixture password required')
        for key, value in values.items():
            if value and ((key.endswith('_API_KEY') and key != 'PROWLARR_API_KEY')
                          or key in PRIVATE_FIELDS):
                raise AcceptanceError('Refusing configured external credentials')
    return saved


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, origin):
        parsed = urllib.parse.urlsplit(origin)
        if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost') or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username:
            raise ValueError('Acceptance must target the local portal')
        self.origin = origin.rstrip('/')
        self.auth = 'Basic ' + base64.b64encode(('admin:' + FIXTURE_PASSWORD).encode()).decode()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, path, payload=None, authenticated=True):
        headers = {'Origin': self.origin, 'Content-Type': 'application/json'}
        if authenticated:
            headers['Authorization'] = self.auth
        request = urllib.request.Request(self.origin + path, headers=headers,
                  data=None if payload is None else json.dumps(payload).encode())
        try:
            with self.opener.open(request, timeout=30) as response:
                return response.status, response.read(2 * 1024 * 1024), response.headers
        except urllib.error.HTTPError as error:
            return error.code, b'', error.headers

    def player(self, path):
        if not path.startswith('/jellyfin/') or '?' in path or '#' in path:
            raise AcceptanceError('Invalid native player path')
        request = urllib.request.Request('http://aiostreams:3000' + path)
        with self.opener.open(request, timeout=30) as response:
            return response.status, response.read(2 * 1024 * 1024), response.headers

    def json(self, path, payload=None):
        status, body, _ = self.request(path, payload)
        if status != 200:
            raise AcceptanceError('Portal JSON request failed: ' + path + ' HTTP ' + str(status))
        return json.loads(body)


def profile_digest(info):
    identity = [info.get('uuid'), info.get('encryptedPassword')]
    if not all(isinstance(value, str) and value for value in identity):
        raise AcceptanceError('Provisioned profile identity missing')
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def inspect_portal(client):
    if client.request('/api/env', authenticated=False)[0] != 401:
        raise AcceptanceError('Portal settings are not protected')
    env = client.json('/api/env')
    if any(env.get(key) != value for key, value in SETTINGS.items()):
        raise AcceptanceError('Portal did not retain acceptance settings')
    info = client.json('/api/manifest-info')
    digest = profile_digest(info)
    manifest = client.json('/api/export-manifest')
    if not manifest.get('id') or not isinstance(manifest.get('resources'), list) or not manifest['resources']:
        raise AcceptanceError('Provisioned manifest is invalid')
    if info.get('watchUrl') != '/watch/':
        raise AcceptanceError('Player URL is not the portal-local alias')
    status, _, headers = client.request('/watch/')
    target = info.get('jellyfinWebPlayer')
    if status != 302 or not target or headers.get('Location') != target:
        raise AcceptanceError('Native player launch redirect is invalid')
    parts = [info['uuid'], info['encryptedPassword']]
    if any(urllib.parse.quote(part, safe='') != part for part in parts):
        raise AcceptanceError('Invalid native player identity')
    expected_path = '/jellyfin/' + '/'.join(parts) + '/web/'
    parsed = urllib.parse.urlsplit(target)
    if parsed.path != expected_path or parsed.query or parsed.fragment:
        raise AcceptanceError('Native player redirect path is invalid')
    # Never follow the public hostname supplied by configuration; address the
    # known internal service and only the exact expected provisioned route.
    status, body, headers = client.player(expected_path)
    if status != 200 or 'text/html' not in headers.get('Content-Type', '') or b'<html' not in body.lower():
        raise AcceptanceError('Native player HTML is unavailable')
    return {'profileDigest': digest, 'manifestId': manifest['id'], 'settings': SETTINGS}


def run(phase, root, state, client, environment):
    require_fixture(root, environment)
    if not state.resolve().is_relative_to((root / 'data').resolve()):
        raise AcceptanceError('Acceptance state must be inside disposable runtime data')
    if phase == 'prepare':
        client.json('/api/save-env', SETTINGS)
        observed = inspect_portal(client)
        if any(saved_values(root).get(key) != value for key, value in SETTINGS.items()):
            raise AcceptanceError('Settings were not persisted to disk')
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps(observed), encoding='utf-8')
        state.chmod(0o600)
    else:
        expected = json.loads(state.read_text(encoding='utf-8'))
        if inspect_portal(client) != expected:
            raise AcceptanceError('Profile or settings changed across restart')
        if any(saved_values(root).get(key) != value for key, value in SETTINGS.items()):
            raise AcceptanceError('Saved settings changed across restart')
    print('PASS: ' + phase + ' portal settings, manifest, native player launch and profile identity', flush=True)
    print('NOT TESTED: paid provider authentication, metadata preset save, video decoding', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', required=True, choices=('prepare', 'verify'))
    parser.add_argument('--origin', default='http://127.0.0.1:8088')
    parser.add_argument('--root', type=Path, default=Path('/app'))
    parser.add_argument('--state', type=Path, default=Path('/app/data/fresh-install-acceptance.json'))
    args = parser.parse_args()
    try:
        run(args.phase, args.root, args.state, Client(args.origin), os.environ)
        return 0
    except AcceptanceError as error:
        print("FAIL: fresh-install " + args.phase + ": " + str(error), file=sys.stderr)
        return 1
    except Exception as error:
        # Never print response bodies, URLs, or exception details containing secrets.
        print('FAIL: fresh-install ' + args.phase + ' (' + type(error).__name__ + ')', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
