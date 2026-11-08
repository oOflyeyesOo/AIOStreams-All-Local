"""Usenet form validation and private controller-only provider configuration."""
import base64
import ipaddress
import json
import re
from urllib.parse import urlsplit

def credential(values,name):
    encoded=values.get(name+'_B64','')
    try:return base64.b64decode(encoded,validate=True).decode('utf-8') if encoded else values.get(name,'')
    except (ValueError,UnicodeError):raise ValueError('Invalid stored Usenet credential') from None

def enabled(values):
    complete=bool(values.get('USENET_HOST') and credential(values,'USENET_USER') and credential(values,'USENET_PASS'))
    return values.get('USENET_ENABLED','true' if complete else 'false')=='true'

def provider_config(values):
    if not enabled(values):return {'Providers':[]}
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
    return {'Providers':[{'Type':1,'Host':host,'Port':port,'UseSsl':values.get('USENET_SSL','true')=='true','User':user,'Pass':password,'MaxConnections':connections}]}

def form_updates(submitted,existing):
    updates=dict(submitted)
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
    if values.get('NZB_INDEXER_URL'):
        url=urlsplit(values['NZB_INDEXER_URL'])
        if url.scheme not in ('http','https') or not url.hostname or url.username or url.password or url.query or url.fragment:raise ValueError('Use an HTTP(S) NZB indexer base address without credentials or a query')
    return updates

def public_settings(values):
    return {'USENET_ENABLED':'true' if enabled(values) else 'false','USENET_HOST':values.get('USENET_HOST',''),
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
