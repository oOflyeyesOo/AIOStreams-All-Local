"""Run inside a disposable package portal; never use a personal installation.

Exercises real Compose interpolation, InfiniDysk NNTP authentication and Prowlarr
Newznab provisioning. This does not simulate article decoding or paid playback.
"""
import base64
import http.server
import json
import os
import socketserver
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

assert os.environ.get('ADDON_PASSWORD')=='package-test-only-password','Fixture deployment required'
PROJECT=os.environ.get('AIO_OPTIONAL_TEST_PROJECT','aio-package')
assert PROJECT in ('aio-package','aio-release'),'Disposable project required'
PASSWORD='fixture$pass\'"#'
USER='fixture$reader'
counts={'authenticated':0,'rejected':0,'indexerRequests':0}
auth=base64.b64encode(b'admin:package-test-only-password').decode()

def request(url,data=None,headers=None,method=None):
    if isinstance(data,dict):data=json.dumps(data).encode()
    with urllib.request.urlopen(urllib.request.Request(url,data=data,headers=headers or {},method=method),timeout=45) as r:
        raw=r.read();return json.loads(raw) if raw else None

def portal(path,data=None):
    return request('http://127.0.0.1:8088'+path,data,{'Authorization':'Basic '+auth,'Content-Type':'application/json'})

def container(service):
    names=subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.project='+PROJECT,'--filter','label=com.docker.compose.service='+service],text=True).split()
    assert len(names)==1,'Fixture service must have exactly one container: '+service
    return json.loads(subprocess.check_output(['docker','inspect',names[0]]))[0]

def apply():
    assert portal('/api/setup',{})['success']
    deadline=time.monotonic()+720
    while time.monotonic()<deadline:
        job=portal('/api/setup-status')
        if job['status']=='complete':return
        if job['status']=='failed':raise AssertionError('Fixture apply failed; inspect locally, do not publish raw logs')
        time.sleep(2)
    raise AssertionError('Fixture apply timed out')

def installed_profile():
    install=json.loads(Path('/app/data/aiostreams/aiostreams_install.json').read_text())
    user_auth=base64.b64encode((install['uuid']+':admin_local_secret').encode()).decode()
    return request('http://aiostreams:3000/api/v1/user',headers={'Authorization':'Basic '+user_auth})['data']['userData']

class Nntp(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(15);self.wfile.write(b'200 NNTP fixture ready\r\n');user=''
        while True:
            try:line=self.rfile.readline()
            except (TimeoutError,ConnectionError):return
            if not line:return
            command=line.decode().rstrip('\r\n');upper=command.upper()
            if upper.startswith('AUTHINFO USER '):user=command[14:];reply=b'381 Password required\r\n'
            elif upper.startswith('AUTHINFO PASS '):
                okay=user==USER and command[14:]==PASSWORD
                counts['authenticated' if okay else 'rejected']+=1
                reply=b'281 Authentication accepted\r\n' if okay else b'481 Authentication rejected\r\n'
            elif upper=='CAPABILITIES':reply=b'101 Capabilities follow\r\nVERSION 2\r\nREADER\r\nAUTHINFO USER\r\n.\r\n'
            elif upper=='QUIT':self.wfile.write(b'205 Bye\r\n');return
            elif upper=='MODE READER':reply=b'200 Reader mode\r\n'
            elif upper=='DATE':reply=b'111 20260101000000\r\n'
            else:reply=b'500 Unsupported fixture command\r\n'
            self.wfile.write(reply)

class Newznab(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        counts['indexerRequests']+=1
        q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        if q.get('t')==['caps']:
            body='''<caps><server version="1.0" title="Fixture"/><limits max="100" default="100"/><registration available="no" open="no"/>
<searching><search available="yes" supportedParams="q"/><tv-search available="yes" supportedParams="q,imdbid,season,ep"/><movie-search available="yes" supportedParams="q,imdbid,tmdbid"/></searching>
<categories><category id="2000" name="Movies"><subcat id="2040" name="HD"/></category><category id="5000" name="TV"><subcat id="5040" name="HD"/></category></categories></caps>'''
        else:
            body='''<rss version="2.0" xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/"><channel><title>Fixture</title><description>Isolated fixture</description><link>http://portal:18884</link><newznab:response offset="0" total="1"/><item><title>Fixture.Movie.2026.1080p.WEB-DL</title><guid isPermaLink="false">fixture-one</guid><link>http://portal:18884/fixture.nzb</link><pubDate>Fri, 06 Nov 2026 12:00:00 +0000</pubDate><enclosure url="http://portal:18884/fixture.nzb" length="1234567890" type="application/x-nzb"/><newznab:attr name="category" value="2040"/><newznab:attr name="size" value="1234567890"/><newznab:attr name="usenetdate" value="Fri, 06 Nov 2026 12:00:00 +0000"/></item></channel></rss>'''
        content=body.encode();self.send_response(200);self.send_header('Content-Type','application/xml');self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)

nntp=socketserver.ThreadingTCPServer(('0.0.0.0',18883),Nntp)
nntp.daemon_threads=True
nzb=http.server.ThreadingHTTPServer(('0.0.0.0',18884),Newznab)
for server in (nntp,nzb):threading.Thread(target=server.serve_forever,daemon=True).start()
try:
    # Remove only stale indexers from this exact isolated fixture address.
    indexer_headers={'X-Api-Key':'prowlarr_internal_secret_key_99'}
    for item in request('http://prowlarr:9696/api/v1/indexer',headers=indexer_headers):
        if item.get('implementation')=='Newznab' and any(f.get('name')=='baseUrl' and f.get('value')=='http://portal:18884' for f in item.get('fields',[])):
            request('http://prowlarr:9696/api/v1/indexer/'+str(item['id']),headers=indexer_headers,method='DELETE')
    values={'USENET_ENABLED':'true','USENET_HOST':'portal','USENET_PORT':'18883','USENET_USER':USER,'USENET_PASS':PASSWORD,
            'USENET_SSL':'false','USENET_CONNECTIONS':'2','NZB_INDEXER_URL':'http://portal:18884','NZB_INDEXER_API_KEY':'fixture-indexer-key'}
    assert portal('/api/save-env',values)['success']
    saved=portal('/api/env');assert saved['USENET_PASSWORD_SAVED'] and PASSWORD not in json.dumps(saved) and 'USENET_PASS_B64' not in saved
    assert PASSWORD not in Path('/app/.env').read_text()
    apply()
    config=installed_profile()
    route=next(p for p in config['presets'] if p['instanceId']=='prowlarr-usenet')
    assert route['options']['sources']==['usenet'] and route['options']['services']==['nzbdav']
    assert not any(p['type'] in ('torrentio','comet','mediafusion') for p in config['presets'])
    env=dict(line.split('=',1) for line in container('infinidysk')['Config']['Env'])
    provider=json.loads(env['NZBDAV_CONFIG__USENET__PROVIDERS'])['Providers'][0]
    assert provider['User']==USER and provider['Pass']==PASSWORD and provider['MaxConnections']==2
    key=env['NZBDAV_CONFIG__API__KEY']
    effective=request('http://infinidysk:3000/api/get-config',urllib.parse.urlencode({'config-keys':'usenet.providers'}).encode(),{'x-api-key':key,'Content-Type':'application/x-www-form-urlencoded'})
    items=effective.get('configItems') or effective.get('ConfigItems')
    assert items,'InfiniDysk must expose effective saved settings'
    item=items[0];p=json.loads(item.get('configValue') or item['ConfigValue'])['Providers'][0]
    assert p['Host']=='portal' and p['Port']==18883
    test=request('http://infinidysk:3000/api/test-usenet-connection',urllib.parse.urlencode({'host':p['Host'],'port':p['Port'],'user':p['User'],'pass':p['Pass'],'use-ssl':'false'}).encode(),{'x-api-key':key,'Content-Type':'application/x-www-form-urlencoded'})
    assert test.get('connected') or test.get('Connected'),'NNTP fixture authentication failed'
    assert counts['authenticated']>=1 and counts['rejected']==0
    print('PASS: real InfiniDysk accepts saved credentials containing dollar signs and quotes',flush=True)
    def indexers():return request('http://prowlarr:9696/api/v1/indexer',headers={'X-Api-Key':'prowlarr_internal_secret_key_99'})
    matches=lambda:[x for x in indexers() if x.get('implementation')=='Newznab' and any(f.get('name')=='baseUrl' and f.get('value')=='http://portal:18884' for f in x.get('fields',[]))]
    assert len(matches())==1 and matches()[0]['protocol']=='usenet','Exactly one NZB indexer required'
    assert portal('/api/save-env',{'USENET_ENABLED':'true','USENET_USER':USER,'MEDIAFUSION_REPLICAS':'1'})['success']
    apply()
    container('mediafusion')
    assert sum(p['type']=='mediafusion' for p in installed_profile()['presets'])==1
    assert len(matches())==1
    print('PASS: repeated setup retains password, does not duplicate Newznab, and starts optional MediaFusion',flush=True)
    assert portal('/api/save-env',{'USENET_ENABLED':'false'})['success']
    apply()
    env=dict(line.split('=',1) for line in container('infinidysk')['Config']['Env'])
    assert json.loads(env['NZBDAV_CONFIG__USENET__PROVIDERS'])=={'Providers':[]}
    assert portal('/api/env')['USENET_PASSWORD_SAVED']
    assert not any(p['type']=='mediafusion' or p['instanceId']=='prowlarr-usenet' for p in installed_profile()['presets'])
    assert len(matches())==1 and not matches()[0]['enable'],'Disabled managed NZB indexer must not poll in the background'
    assert not subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.project='+PROJECT,'--filter','label=com.docker.compose.service=mediafusion']).strip()
    print('PASS: disabling stops optional service and NNTP provider while retaining credentials',flush=True)
    print(json.dumps({'scope':'fixture NNTP authentication and indexer setup, not article playback','counts':counts}),flush=True)
finally:
    nntp.shutdown();nntp.server_close();nzb.shutdown();nzb.server_close()
