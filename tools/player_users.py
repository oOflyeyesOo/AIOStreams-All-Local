"""Admin-only adapter for native isolated player profiles; no separate account store."""
import base64
import copy
import hashlib
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

_LOCK = threading.Lock()
_REQUEST_LOCK = threading.Lock()
_NEXT_USER_REQUEST = 0.0

class PlayerUsersError(RuntimeError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

_OPENER = urllib.request.build_opener(_NoRedirect)

def _request(uuid, password, path, payload=None, _retried=False):
    origin = os.environ.get('AIOSTREAMS_URL', 'http://aiostreams:3000').rstrip('/')
    auth = base64.b64encode(f'{uuid}:{password}'.encode()).decode()
    req = urllib.request.Request(origin + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Authorization': 'Basic ' + auth, 'Content-Type': 'application/json'},
        method='PUT' if payload is not None else 'GET')
    # Native defaults allow five user-API calls per five seconds. Pace our
    # own reads and writes; never replay a mutation after an ambiguous failure.
    if path.startswith('/api/v1/user'):
        global _NEXT_USER_REQUEST
        with _REQUEST_LOCK:
            delay = max(0.0, _NEXT_USER_REQUEST - time.monotonic())
            if delay:
                time.sleep(delay)
            _NEXT_USER_REQUEST = time.monotonic() + 1.1
    try:
        with _OPENER.open(req, timeout=15) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 429 and payload is None and not _retried:
            try:
                delay = float(error.headers.get('Retry-After', '5'))
            except (ValueError, TypeError):
                delay = 5
            if 0 <= delay <= 5:
                time.sleep(delay + 0.1)
                return _request(uuid, password, path, _retried=True)
        if error.code == 429:
            raise PlayerUsersError('AIOStreams is limiting requests. Wait a minute, then refresh users.', 429) from None
        if error.code in (401, 403):
            raise PlayerUsersError('The saved profile password was rejected. Apply your stack password in setup first.', 409) from None
        raise PlayerUsersError('AIOStreams rejected the request. Refresh users before trying again.', 502) from None
    except Exception:
        raise PlayerUsersError('Could not reach AIOStreams. Check that setup has completed.', 503) from None
    if not isinstance(result, dict) or result.get('success') is not True:
        raise PlayerUsersError('AIOStreams did not accept the request. Refresh users before trying again.', 502)
    return result.get('data') or {}

def _base(base):
    p = urllib.parse.urlsplit(base)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.query or p.fragment or p.path not in ('', '/'):
        raise PlayerUsersError('Set a valid public AIOStreams base address in setup first.')
    return base.rstrip('/')

def _revision(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def _load(uuid, password):
    if not uuid or not password:
        raise PlayerUsersError('Complete stack setup before adding player users.', 409)
    status = _request(uuid, password, '/api/v1/status')
    caps = (status.get('settings') or {}).get('jellyfin') or {}
    config = _request(uuid, password, '/api/v1/user?raw=true').get('userData')
    if not isinstance(config, dict):
        raise PlayerUsersError('AIOStreams returned no saved configuration.', 502)
    jf = config.get('jellyfin') or {}
    if not isinstance(jf, dict) or not isinstance(jf.get('personas', []), list):
        raise PlayerUsersError('This AIOStreams version has an unsupported profile format.', 409)
    if 'profiles' in config and not isinstance(config['profiles'], list):
        raise PlayerUsersError('Unsupported player profile format.', 409)
    return config, caps

def _people(config):
    # Recent AIOStreams moved jellyfin.personas to top-level profiles, including
    # an owner row with id="". Read the stored format without inventing an owner.
    return config['profiles'] if 'profiles' in config else (config.get('jellyfin') or {}).get('personas', [])

def _isolated(person):
    return (isinstance(person, dict) and bool(person.get('id')) and person.get('hidden') is True
            and bool(re.fullmatch('[a-z0-9]{10,32}', str(person.get('address', '')))))

def _view(config, caps, base):
    users = []
    for person in _people(config):
        if not isinstance(person, dict) or not person.get('id'):
            continue
        isolated = _isolated(person)
        server = f"{base}/jellyfin/p/{person['address']}" if isolated else None
        users.append({'id': person['id'], 'name': person.get('name', person['id']),
                      'isolated': isolated, 'history': person.get('history'), 'hasPin': bool(person.get('lock')),
                      'inviteUrl': server + '/web/' if server else None, 'serverUrl': server})
    return {'success': True, 'revision': _revision(config), 'users': users,
            'enabled': caps.get('enabled') is True, 'pinSignInEnabled': caps.get('pinSignIn') is True,
            'maxUsers': caps.get('maxProfiles', caps.get('maxPersonas'))}

def list_users(uuid, password, base_url):
    config, caps = _load(uuid, password)
    return _view(config, caps, _base(base_url))

def mutate_user(uuid, password, base_url, payload):
    if not isinstance(payload, dict):
        raise PlayerUsersError('Expected a player user action.')
    action = payload.get('action')
    if action not in ('create', 'reset_pin', 'replace_link', 'remove'):
        raise PlayerUsersError('Unknown player user action.')
    base = _base(base_url)
    with _LOCK:
        config, caps = _load(uuid, password)
        if payload.get('expectedRevision') != _revision(config):
            raise PlayerUsersError('Users or configuration changed. Refresh users and try again.', 409)
        if action != 'remove' and (caps.get('enabled') is not True or caps.get('pinSignIn') is not True):
            raise PlayerUsersError('Enable JELLYFIN_PIN_SIGN_IN and recreate AIOStreams before managing invitations.', 409)
        updated = copy.deepcopy(config)
        if 'profiles' in updated or 'maxProfiles' in caps:
            people = updated.setdefault('profiles', [])
        else:
            jf = updated.get('jellyfin') or {}
            updated['jellyfin'] = jf
            people = jf.setdefault('personas', [])
        pin = None
        if action == 'create':
            name = payload.get('name')
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 32 or any(ord(c) < 32 for c in name):
                raise PlayerUsersError('Enter a name between 1 and 32 characters.')
            name = name.strip()
            if any(str(p.get('name', '')).casefold() == name.casefold() for p in people) or name.casefold() == str(updated.get('addonName', '')).casefold():
                raise PlayerUsersError('A player with that name already exists.')
            limit = caps.get('maxProfiles', caps.get('maxPersonas'))
            if not isinstance(limit, int) or isinstance(limit, bool) or sum(bool(p.get('id')) for p in people) >= limit:
                raise PlayerUsersError('The player profile limit is reached or unavailable.', 409)
            person = {'id': 'guest-' + secrets.token_hex(6), 'name': name, 'history': 'own',
                      'hidden': True, 'address': secrets.token_hex(16)}
            people.append(person)
        else:
            person = next((p for p in people if isinstance(p, dict) and p.get('id') == payload.get('id')), None)
            if not person or not _isolated(person):
                raise PlayerUsersError('Select an isolated invited user. Owner and household profiles are managed in AIOStreams.', 404)
        person_id = person['id']
        if action in ('create', 'reset_pin'):
            pin = ''.join(str(secrets.randbelow(10)) for _ in range(8))
            person['lock'] = pin
        if action == 'replace_link':
            person['address'] = secrets.token_hex(16)
        if action == 'remove':
            people.remove(person)
        # Recheck just before saving; the native API has no atomic If-Match support.
        current = _request(uuid, password, '/api/v1/user?raw=true').get('userData')
        if not isinstance(current, dict) or _revision(current) != _revision(config):
            raise PlayerUsersError('Configuration changed while editing. Refresh users and try again.', 409)
        # Compose's configuration write key is the stack password. GET omits it.
        updated['accessKey'] = password
        _request(uuid, password, '/api/v1/user', {'config': updated})
        # GET removes the write access key and returns the canonical revision.
        saved = _request(uuid, password, '/api/v1/user?raw=true').get('userData')
        if not isinstance(saved, dict):
            raise PlayerUsersError('Save completed but could not be verified. Refresh users before another change.', 502)
        new_caps = caps
        view = _view(saved, new_caps, base)
        saved_person = next((p for p in _people(saved) if p.get('id') == person_id), None)
        valid = saved_person is None if action == 'remove' else (
            saved_person is not None and _isolated(saved_person) and saved_person.get('address') == person.get('address')
            and saved_person.get('history') == person.get('history') and bool(saved_person.get('lock')))
        if not valid:
            raise PlayerUsersError('AIOStreams did not retain the requested user settings. Refresh and check its version.', 502)
        view.update(action=action, userId=person_id)
        if pin:
            view['pin'] = pin
        if saved_person:
            view['inviteUrl'] = f"{base}/jellyfin/p/{saved_person['address']}/web/"
        return view
