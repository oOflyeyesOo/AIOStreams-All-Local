"""Usenet form validation and private controller-only provider configuration."""
import base64
import ipaddress
import json
import re
from urllib.parse import urlsplit
from uuid import uuid4

EXTRA_SOURCES = {
    'USENET_EXTRA_SERVERS': 'password',
    'USENET_EXTRA_INDEXERS': 'apiKey',
}


def extra_sources(values, field):
    encoded = values.get(field + '_B64', '')
    if not encoded:
        return []
    try:
        rows = json.loads(base64.b64decode(encoded, validate=True))
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError
        return rows
    except (ValueError, UnicodeError):
        raise ValueError('Invalid stored Usenet sources') from None


def indexer_address(value):
    value = value.strip().rstrip('/')
    url = urlsplit(value)
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('Use an HTTP(S) NZB indexer base address without credentials or a query')
    return value


def newznab_indexers(values):
    rows = extra_sources(values, 'USENET_EXTRA_INDEXERS')
    if values.get('NZB_INDEXER_URL') and values.get('NZB_INDEXER_API_KEY'):
        rows.insert(0, {'id': '', 'url': indexer_address(values['NZB_INDEXER_URL']), 'apiKey': values['NZB_INDEXER_API_KEY']})
    return rows

def credential(values,name):
    encoded=values.get(name+'_B64','')
    try:return base64.b64decode(encoded,validate=True).decode('utf-8') if encoded else values.get(name,'')
    except (ValueError,UnicodeError):raise ValueError('Invalid stored Usenet credential') from None

def enabled(values):
    complete=bool(values.get('USENET_HOST') and credential(values,'USENET_USER') and credential(values,'USENET_PASS'))
    return values.get('USENET_ENABLED','true' if complete else 'false')=='true'

def server_config(values, kind=1):
    host=values.get('USENET_HOST','').strip()
    try:ipaddress.ip_address(host.strip('[]'))
    except ValueError:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}',host):raise ValueError('Enter a Usenet server hostname or IP address')
    user,password=credential(values,'USENET_USER'),credential(values,'USENET_PASS')
    if not user or not password:raise ValueError('Usenet needs a server, username and password')
    if any(ord(c)<32 or ord(c)==127 for c in user+password) or len(user)>400 or len(password)>400:
        raise ValueError('Usenet credentials must contain no control characters and be at most 400 characters')
    try:port=int(values.get('USENET_PORT') or 563);connections=int(values.get('USENET_CONNECTIONS') or 10)
    except ValueError:raise ValueError('Usenet port and connection count must be numbers') from None
    if not 1<=port<=65535 or not 1<=connections<=1000:raise ValueError('Invalid Usenet port or connection count')
    if values.get('USENET_SSL','true') not in ('true','false'):raise ValueError('Usenet TLS must be true or false')
    return {'Type':kind,'Host':host.strip('[]'),'Port':port,'UseSsl':values.get('USENET_SSL','true')=='true','User':user,'Pass':password,'MaxConnections':connections}


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
        if not isinstance(row, dict):
            raise ValueError('Invalid Usenet source row')
        row_id = row.get('id')
        if row_id and (not isinstance(row_id, str) or row_id not in previous or row_id in ids):
            raise ValueError('Usenet source list changed. Reload the page and retry.')
        old = previous.get(row_id) if row_id else None
        row_id = row_id or uuid4().hex
        ids.add(row_id)
        value = row.get(secret) or (old or {}).get(secret, '')
        if not isinstance(value, str) or not value or len(value) > 400 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('Every added source needs a valid password or API key')
        if secret == 'password':
            if not all(isinstance(row.get(key, ''), str) for key in ('host', 'port', 'username', 'connections')):
                raise ValueError('Invalid Usenet server fields')
            if not all(isinstance(row.get(key, default), bool) for key, default in (('tls', True), ('backupOnly', False))):
                raise ValueError('Invalid Usenet server options')
            normalized = {key: row.get(key, default) for key, default in (
                ('host', ''), ('port', '563'), ('username', ''), ('connections', '10'), ('tls', True), ('backupOnly', False))}
            normalized['password'] = value
            extra_server(normalized)
        else:
            if not isinstance(row.get('url'), str):
                raise ValueError('Enter an NZB indexer base address')
            normalized = {'url': indexer_address(row['url']), 'apiKey': value}
        saved.append({'id': row_id, **normalized})
    updates[encoded_field] = base64.b64encode(json.dumps(saved).encode()).decode()

def form_updates(submitted,existing):
    updates=dict(submitted)
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
    if len({url.lower() for url in urls}) != len(urls):
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

def apply_to_compose(config,values):
    # Keep installations configured outside the portal unchanged until explicitly managed.
    if values.get('USENET_MANAGED')=='1' or enabled(values):
        text=json.dumps(provider_config(values),separators=(',',':')).replace('$','$$')
        service=config['services'].get('infinidysk')
        if service is None:raise ValueError('Usenet downloader is missing from this stack')
        service.setdefault('environment',{})['NZBDAV_CONFIG__USENET__PROVIDERS']=text
    return config
