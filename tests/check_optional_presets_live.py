"""Native preset/schema acceptance only. No searches or paid authentication.

Pipe inside a disposable package portal. Fixture credentials must never be used
to request streams; these tests fetch only generated manifests.
"""
import base64
import json
import os
import time
import urllib.error
import urllib.request

assert os.environ.get('ADDON_PASSWORD')=='package-test-only-password','Fixture deployment required'
ORIGIN='http://aiostreams:3000'
def request(path,data=None,method=None,auth=None):
    headers={'Content-Type':'application/json'}
    if auth:headers['Authorization']='Basic '+auth
    try:
        with urllib.request.urlopen(urllib.request.Request(ORIGIN+path,data=None if data is None else json.dumps(data).encode(),headers=headers,method=method),timeout=30) as response:return json.load(response)
    except urllib.error.HTTPError as error:
        value=json.load(error)
        raise AssertionError(value.get('error',{}).get('message','Native preset validation failed')) from None

cases=[('native anime',[{'id':'premiumize','enabled':True,'credentials':{'apiKey':'fixture-not-a-provider-key'}}],['anime-tosho-new','neko-bt','tsukihime']),
       ('direct EasyNews',[{'id':'easynews','enabled':True,'credentials':{'username':'fixture-not-an-account','password':'fixture-not-a-password'}}],['easynews-search']),
       ('disabled unsupported sources',[],['anime-tosho-new','neko-bt','tsukihime'])]
for name,services,types in cases:
    # Preserve the default five user-API calls per five seconds protection.
    time.sleep(6)
    presets=[{'type':kind,'instanceId':kind,'enabled':bool(services),'options':{
        'name':kind,'resources':['stream'],'timeout':15000,'mediaTypes':['anime'] if kind!='easynews-search' else [],
        'services':[s['id'] for s in services],'useMultipleInstances':False,**({'paginate':False} if kind=='easynews-search' else {})}} for kind in types]
    config={'addonName':'Native optional preset fixture','accessKey':os.environ['ADDON_PASSWORD'],
            'presets':presets,'services':services,'formatter':{'id':'tamtaro'},'sortCriteria':{'global':[]},'proxy':{'id':'builtin','enabled':False},'precacheNextEpisode':False}
    result=request('/api/v1/user',{'config':config,'password':'optional-preset-fixture'})
    assert result.get('success'),'Native preset registration failed'
    user=result['data'];auth=base64.b64encode((user['uuid']+':optional-preset-fixture').encode()).decode()
    try:
        manifest=request('/stremio/'+user['uuid']+'/'+user['encryptedPassword']+'/manifest.json')
        assert manifest.get('id'),'Native manifest was not generated'
        saved=request('/api/v1/user',auth=auth)['data']['userData']
        assert sum(bool(p.get('enabled')) for p in saved['presets'])==(len(types) if services else 0)
        print('PASS: '+name+' native configuration and manifest; paid access not tested',flush=True)
    finally:request('/api/v1/user',method='DELETE',auth=auth)
