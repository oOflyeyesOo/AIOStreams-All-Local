"""Deterministic routing acceptance. Pipe into the DISPOSABLE package portal only.

No live credentials or provider calls: tiny HTTP addons model primary/fallback sources.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
import http.server
import json
import os
import threading
import time
import urllib.request
import urllib.error

assert os.environ.get('ADDON_PASSWORD') == 'package-test-only-password', 'Fixture deployment required'
calls=[]
lock=threading.Lock()

class Fixture(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        bits=self.path.split('/');owner=bits[1]
        if self.path.endswith('manifest.json'):
            body={'id':'fixture.'+owner,'name':owner,'version':'1.0.0','description':'Routing fixture',
                  'types':['movie','series','anime'],'resources':['stream'],'catalogs':[]}
        else:
            with lock:calls.append(owner)
            time.sleep(.12 if owner=='primary' else .2)
            if 'unavailable' in self.path and owner=='primary':
                self.send_error(503);return
            empty=('empty' in self.path or 'tt0903747' in self.path) and owner=='primary'
            body={'streams':[] if empty else [{'name':'Fixture [PM+]','title':'Fixture.Movie.2026.1080p.WEB-DL',
                  'url':'http://portal:18881/media/'+owner+'.mp4',
                  'behaviorHints':{'service':'premiumize','cached':True,'filename':'Fixture.2026.1080p.mkv'}}]}
        encoded=json.dumps(body).encode();self.send_response(200)
        self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(encoded)))
        self.end_headers();self.wfile.write(encoded)

def request(url,payload=None,method=None,auth=None):
    headers={'Content-Type':'application/json'}
    if auth:headers['Authorization']='Basic '+auth
    data=None if payload is None else json.dumps(payload).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url,data=data,headers=headers,method=method),timeout=40) as r:
            return json.load(r)
    except urllib.error.HTTPError as error:
        if not users:print(error.read(4000).decode())  # Fixture registration only; contains no credentials.
        raise

server=http.server.ThreadingHTTPServer(('0.0.0.0',18881),Fixture)
threading.Thread(target=server.serve_forever,daemon=True).start()
users=[];report=[]
try:
    presets=[{'type':'custom','instanceId':owner,'enabled':True,'options':{
        'name':owner,'manifestUrl':'http://portal:18881/'+owner+'/manifest.json','resources':['stream'],'timeout':5000}}
        for owner in ('primary','fallback')]
    config={'addonName':'Private routing fixture','presets':presets,'formatter':{'id':'tamtaro'},'sortCriteria':{'global':[]},
            'proxy':{'id':'builtin','enabled':False},
            'groups':{'enabled':True,'behaviour':'sequential','onConditionFailure':'stop',
                      'groupings':[{'addons':['primary'],'condition':'true'},
                                   {'addons':['fallback'],'condition':'count(cached(totalStreams)) == 0'}]}}
    result=request('http://aiostreams:3000/api/v1/user',{'config':config,'password':'routing-fixture-only'})
    assert result.get('success'), 'Fixture profile creation failed'
    user=result['data'];uid=user['uuid'];token=user.get('encryptedPassword') or user.get('encrypted_password')
    auth=base64.b64encode((uid+':routing-fixture-only').encode()).decode();users.append(auth)
    prefix='http://aiostreams:3000/stremio/'+uid+'/'+token
    def fetch(ident,kind='movie'):
        start=time.monotonic();value=request(prefix+'/stream/'+kind+'/'+ident+'.json')
        result={'seconds':round(time.monotonic()-start,3),'streams':sum(bool(s.get('url')) for s in value.get('streams',[]))}
        if not result['streams']:result['messages']=[s.get('description',s.get('title',s.get('name'))) for s in value.get('streams',[])]
        return result
    for kind,ident,expected in [('movie','fixture-cached',{'primary':1,'fallback':0}),
                               ('movie','fixture-empty',{'primary':1,'fallback':1}),
                               ('series','tt0944947:2:2',{'primary':1,'fallback':0}),
                               ('series','tt0903747:2:2',{'primary':1,'fallback':1}),
                               ('movie','fixture-unavailable',{'primary':1,'fallback':1})]:
        # Keep the upstream's default 10 requests / 15 s protection enabled.
        time.sleep(16)
        with lock:calls.clear()
        cold=fetch(ident,kind)
        with lock:observed={name:calls.count(name) for name in expected}
        assert observed==expected,(ident,observed,cold)
        assert cold['streams']>0,(ident,cold)
        warm=fetch(ident,kind)
        with ThreadPoolExecutor(max_workers=4) as pool:concurrent=list(pool.map(lambda _:fetch(ident,kind),range(4)))
        assert warm['streams']>0 and all(item['streams']>0 for item in concurrent), 'Repeated fixture response lost streams'
        with lock:after={name:calls.count(name) for name in expected}
        assert after==expected,('Repeated upstream fixture calls',after)
        report.append({'case':kind+' '+ident,'cold':cold,'warm':warm,'concurrent4':concurrent,'upstreamCalls':after})
        print('PASS: '+kind+' '+ident,flush=True)
    time.sleep(16)
    with lock:calls.clear()
    with ThreadPoolExecutor(max_workers=4) as pool:concurrent=list(pool.map(lambda _:fetch('fixture-concurrent-cold'),range(4)))
    with lock:observed={name:calls.count(name) for name in ('primary','fallback')}
    assert observed=={'primary':1,'fallback':0}, ('Concurrent cold request duplication',observed)
    assert all(item['streams']>0 for item in concurrent), 'Concurrent cold fixture response lost streams'
    report.append({'case':'simultaneous cold viewers','concurrent4':concurrent,'upstreamCalls':observed})
    print(json.dumps({'scope':'deterministic AIOStreams routing; no external providers','results':report},indent=2))
finally:
    for auth in users:request('http://aiostreams:3000/api/v1/user',method='DELETE',auth=auth)
    server.shutdown();server.server_close()
