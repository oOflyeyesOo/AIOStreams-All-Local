"""Native AIOStreams addon discovery on a disposable package; no provider keys.

Creates and deletes a temporary profile. Counts results, never prints URLs.
"""
import base64
import json
import os
import time
import urllib.request
import urllib.error

assert os.environ.get('ADDON_PASSWORD')=='package-test-only-password','Fixture deployment required'
origin='http://aiostreams:3000'
def request(path,payload=None,method=None,auth=None):
    headers={'Content-Type':'application/json'}
    if auth:headers['Authorization']='Basic '+auth
    data=json.dumps(payload).encode() if payload is not None else None
    try:
        with urllib.request.urlopen(urllib.request.Request(origin+path,data=data,headers=headers,method=method),timeout=40) as r:return json.load(r)
    except urllib.error.HTTPError as error:
        value=json.load(error)
        raise AssertionError(value.get('error',{}).get('message','Native addon request failed')) from None

config={'addonName':'Native public discovery test','accessKey':os.environ['ADDON_PASSWORD'],
        'presets':[{'type':'torrentio','instanceId':'torrentio-test','enabled':True,'options':{
            'name':'Torrentio','url':'https://torrentio.strem.fun','resources':['stream'],'providers':[],'useMultipleInstances':False,'timeout':18000}}],
        'services':[],'formatter':{'id':'tamtaro'},'proxy':{'id':'builtin','enabled':False},'sortCriteria':{'global':[]},
        'precacheNextEpisode':False,'cacheAndPlay':{'enabled':True,'streamTypes':['torrent','usenet']},
        'remuxDb':{'enabled':True},'titleMatching':{'enabled':False},'yearMatching':{'enabled':False},
        'seasonEpisodeMatching':{'enabled':True,'strict':False},'episodeTitleMatching':{'enabled':True,'similarityThreshold':.8},
        'languageInference':{'enabled':True,'sources':['title','episodeTitle']},
        'failover':{'enabled':True,'contentTypes':['debrid','usenet'],'allowCrossType':True,'maxAttempts':3,'parallel':1,'precacheFailover':False}}
created=request('/api/v1/user',{'config':config,'password':'native-discovery-fixture'})
assert created.get('success'),'Native profile registration failed'
user=created['data'];auth=base64.b64encode((user['uuid']+':native-discovery-fixture').encode()).decode()
try:
    saved=request('/api/v1/user',auth=auth)['data']['userData']
    for feature in ('cacheAndPlay','remuxDb','seasonEpisodeMatching','episodeTitleMatching','languageInference','failover'):
        assert saved.get(feature,{}).get('enabled'), 'Feature did not survive native validation: '+feature
    report=[]
    for kind,id in [('movie','tt15239678'),('series','tt0944947:2:2')]:
        start=time.monotonic()
        value=request('/stremio/'+user['uuid']+'/'+user['encryptedPassword']+'/stream/'+kind+'/'+id+'.json')
        rows=[s for s in value.get('streams',[]) if s.get('url') or s.get('infoHash')]
        assert rows,'Native Torrentio returned no playable-shaped candidates'
        hashes={s['infoHash'].lower() for s in rows if s.get('infoHash')}
        report.append({'case':kind,'seconds':round(time.monotonic()-start,3),'candidates':len(rows),'p2pHashes':len(hashes)})
    print(json.dumps({'scope':'native parsing/discovery and saved feature settings; no paid playback','results':report},indent=2))
finally:request('/api/v1/user',method='DELETE',auth=auth)
