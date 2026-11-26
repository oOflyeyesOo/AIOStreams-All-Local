"""Usenet form validation and private controller-only provider configuration."""
import base64
from collections.abc import Mapping
import ipaddress
import json
import re
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

EXTRA_SOURCES = {
    'USENET_EXTRA_SERVERS': 'password',
    'USENET_EXTRA_INDEXERS': 'apiKey',
}


def extra_sources(values, field):
    if not isinstance(values, Mapping):
        return []
    encoded = values.get(field + '_B64', '')
    if not encoded:
        raw = values.get(field)
        if isinstance(raw, list) and all(isinstance(row, Mapping) for row in raw):
            return list(raw)
        if isinstance(raw, str) and raw.strip():
            try:
                rows = json.loads(raw)
                if isinstance(rows, list) and all(isinstance(row, Mapping) for row in rows):
                    return rows
            except (ValueError, TypeError):
                pass
            try:
                rows = json.loads(base64.b64decode(raw, validate=True))
                if isinstance(rows, list) and all(isinstance(row, Mapping) for row in rows):
                    return rows
            except (ValueError, TypeError, UnicodeError):
                pass
        return []
    try:
        if not isinstance(encoded, (str, bytes)):
            raise ValueError
        rows = json.loads(base64.b64decode(encoded, validate=True))
        if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
            raise ValueError
        return rows
    except (ValueError, TypeError, UnicodeError):
        raise ValueError('Invalid stored Usenet sources') from None


def indexer_address(value):
    if not isinstance(value, str):
        raise ValueError('Use an HTTP(S) NZB indexer base address without credentials or a query')
    value = value.strip().rstrip('/')
    if len(value) > 2000 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('Use an HTTP(S) NZB indexer base address without credentials or a query')
    url = urlsplit(value)
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('Use an HTTP(S) NZB indexer base address without credentials or a query')
    try:
        url.port
    except ValueError:
        raise ValueError('Use an HTTP(S) NZB indexer base address without credentials or a query')
    return value


def newznab_endpoint(value):
    """Canonical API identity; preserve path case because paths can be distinct."""
    parsed = urlsplit(indexer_address(value))
    host = parsed.hostname.lower()
    if ':' in host:
        host = '[' + host + ']'
    default_port = 443 if parsed.scheme == 'https' else 80
    if parsed.port is not None and parsed.port != default_port:
        host += ':' + str(parsed.port)
    path = parsed.path.rstrip('/')
    if not path.endswith('/api'):
        path += '/api'
    return urlunsplit((parsed.scheme, host, path, '', ''))


def newznab_indexers(values):
    rows = extra_sources(values, 'USENET_EXTRA_INDEXERS')
    if values.get('NZB_INDEXER_URL') and values.get('NZB_INDEXER_API_KEY'):
        try:
            addr = indexer_address(values['NZB_INDEXER_URL'])
            rows.insert(0, {'id': '', 'url': addr, 'apiKey': values['NZB_INDEXER_API_KEY']})
        except ValueError:
            pass
    return rows

def credential(values, name):
    if not isinstance(values, Mapping):
        return ''
    encoded = values.get(name + '_B64', '')
    try:
        if encoded:
            if not isinstance(encoded, (str, bytes)):
                raise ValueError
            return base64.b64decode(encoded, validate=True).decode('utf-8')
        val = values.get(name, '')
        return str(val) if val is not None else ''
    except (ValueError, TypeError, UnicodeError):
        raise ValueError('Invalid stored Usenet credential') from None

def enabled(values):
    complete = bool(values.get('USENET_HOST') and credential(values, 'USENET_USER') and credential(values, 'USENET_PASS'))
    return values.get('USENET_ENABLED', 'true' if complete else 'false') == 'true'

def server_config(values, kind=1):
    if not isinstance(values, Mapping):
        raise ValueError('Invalid configuration values')
    host = str(values.get('USENET_HOST') or '').strip()
    try:
        ipaddress.ip_address(host.strip('[]'))
    except ValueError:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', host):
            raise ValueError('Enter a Usenet server hostname or IP address')
    user, password = credential(values, 'USENET_USER'), credential(values, 'USENET_PASS')
    if not user or not password:
        raise ValueError('Usenet needs a server, username and password')
    if any(ord(c) < 32 or ord(c) == 127 for c in user + password) or len(user) > 400 or len(password) > 400:
        raise ValueError('Usenet credentials must contain no control characters and be at most 400 characters')
    try:
        port = int(values.get('USENET_PORT') or 563)
        connections = int(values.get('USENET_CONNECTIONS') or 10)
    except (ValueError, TypeError):
        raise ValueError('Usenet port and connection count must be numbers') from None
    if not 1 <= port <= 65535 or not 1 <= connections <= 1000:
        raise ValueError('Invalid Usenet port or connection count (connections must be 1..1000)')
    if values.get('USENET_SSL', 'true') not in ('true', 'false'):
        raise ValueError('Usenet TLS must be true or false')
    return {'Type': kind, 'Host': host.strip('[]'), 'Port': port, 'UseSsl': values.get('USENET_SSL', 'true') == 'true', 'User': user, 'Pass': password, 'MaxConnections': connections}


def extra_server(row):
    return server_config({
        'USENET_HOST': row.get('host', ''),
        'USENET_PORT': row.get('port'),
        'USENET_USER': row.get('username', ''),
        'USENET_PASS': row.get('password', ''),
        'USENET_SSL': 'true' if row.get('tls', True) else 'false',
        'USENET_CONNECTIONS': row.get('connections'),
    }, kind=3 if row.get('backupOnly') else 1)


def provider_config(values):
    if not enabled(values):
        return {'Providers': []}
    servers = [server_config(values)]
    servers.extend(extra_server(row) for row in extra_sources(values, 'USENET_EXTRA_SERVERS'))
    identities = {(p['Host'].lower().rstrip('.'), p['Port'], p['User']) for p in servers}
    if len(identities) != len(servers):
        raise ValueError('A Usenet server account appears more than once')
    return {'Providers': servers}


def update_sources(updates, existing, field, secret):
    encoded_field = field + '_B64'
    if encoded_field in updates:
        raise ValueError('Submit Usenet sources as rows')
    if field not in updates:
        return
    rows = updates.pop(field)
    if not isinstance(rows, list) or len(rows) > 12:
        raise ValueError('Enter up to 12 additional sources of each type')
    previous = {row['id']: row for row in extra_sources(existing, field)}
    saved = []
    ids = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError('Invalid Usenet source row')
        row_id = row.get('id')
        if row_id and (not isinstance(row_id, str) or row_id in ids):
            raise ValueError('Usenet source list changed. Reload the page and retry.')
        old = previous.get(row_id) if row_id else None
        if row_id and old is None and not row.get(secret):
            raise ValueError('Usenet source list changed. Reload the page and retry.')
        row_id = (row_id if old is not None else None) or uuid4().hex
        ids.add(row_id)
        value = row.get(secret) or (old or {}).get(secret, '')
        if isinstance(value, str) and secret != 'password':
            value = value.strip()
        if not isinstance(value, str) or not value or len(value) > 400 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('Every added source needs a valid password or API key')
        if secret == 'password':
            if not all(isinstance(row.get(key, ''), str) for key in ('host', 'port', 'username', 'connections')):
                raise ValueError('Invalid Usenet server fields')
            if not all(isinstance(row.get(key, default), bool) for key, default in (('tls', True), ('backupOnly', False))):
                raise ValueError('Invalid Usenet server options')
            normalized = {key: (row.get(key, default).strip() if isinstance(row.get(key), str) else row.get(key, default)) for key, default in (
                ('host', ''), ('port', '563'), ('username', ''), ('connections', '10'), ('tls', True), ('backupOnly', False))}
            normalized['password'] = value
            normalized['username'] = row.get('username', '')
            extra_server(normalized)
        else:
            if not isinstance(row.get('url'), str):
                raise ValueError('Enter an NZB indexer base address')
            normalized = {'url': indexer_address(row['url']), 'apiKey': value}
        saved.append({'id': row_id, **normalized})
    updates[encoded_field] = base64.b64encode(json.dumps(saved).encode()).decode()

def form_updates(submitted, existing):
    if not isinstance(submitted, Mapping) or not isinstance(existing, Mapping):
        raise ValueError('Form updates require dictionaries')
    updates = dict(submitted)
    for field, secret in EXTRA_SOURCES.items():
        update_sources(updates, existing, field, secret)
    for name in ('USENET_USER','USENET_PASS'):
        if name in updates and updates[name] is not None:
            value=updates[name]
            if not isinstance(value,str) or len(value)>400 or any(ord(c)<32 or ord(c)==127 for c in value):raise ValueError('Invalid Usenet credential')
            updates[name+'_B64']=base64.b64encode(value.encode()).decode() if value else ''
            updates[name]='' # Clear legacy plaintext; base64 is encoding, not encryption.
    values={**existing,**{k:str(v) for k,v in updates.items() if v is not None}}
    # Reject corrupted encoded inputs even while disabled, before saving them.
    for name in ('USENET_USER','USENET_PASS'):
        value=credential(values,name)
        if len(value)>400 or any(ord(c)<32 or ord(c)==127 for c in value):raise ValueError('Invalid Usenet credential')
    if values.get('USENET_ENABLED','false') not in ('true','false'):raise ValueError('Usenet must be enabled or disabled')
    names={'USENET_ENABLED','USENET_HOST','USENET_PORT','USENET_USER','USENET_PASS','USENET_SSL','USENET_CONNECTIONS'}
    if names.intersection(submitted) and (existing.get('USENET_MANAGED')=='1' or enabled(values) or values.get('USENET_HOST') or credential(values,'USENET_USER') or credential(values,'USENET_PASS')):updates['USENET_MANAGED']='1'
    if enabled(values):provider_config(values)
    urls = [row['url'] for row in extra_sources(values, 'USENET_EXTRA_INDEXERS')]
    if values.get('NZB_INDEXER_URL'):
        urls.append(indexer_address(values['NZB_INDEXER_URL']))
    if len({newznab_endpoint(url) for url in urls}) != len(urls):
        raise ValueError('An NZB indexer address appears more than once')
    return updates

def public_settings(values):
    extra = {}
    for field, secret in EXTRA_SOURCES.items():
        extra[field] = [{**{key: value for key, value in row.items() if key != secret},
                         'secretSaved': bool(row.get(secret))} for row in extra_sources(values, field)]
    return {**extra, 'USENET_ENABLED':'true' if enabled(values) else 'false','USENET_HOST':values.get('USENET_HOST',''),
            'USENET_PORT':values.get('USENET_PORT') or '563','USENET_USER':credential(values,'USENET_USER'),
            'USENET_SSL':values.get('USENET_SSL','true'),'USENET_CONNECTIONS':values.get('USENET_CONNECTIONS') or '10',
            'USENET_PASSWORD_SAVED':bool(credential(values,'USENET_PASS')),'NZB_INDEXER_URL':values.get('NZB_INDEXER_URL','')}

