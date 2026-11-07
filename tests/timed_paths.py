"""Read-only timed audit. Run inside the existing portal; never export profile secrets."""
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import time
import urllib.parse
import urllib.request
import urllib.error

assert os.environ.get('AIO_READONLY_AUDIT')=='true','Explicit read-only audit flag required'
install=json.loads(Path('/app/data/aiostreams/aiostreams_install.json').read_text())
auth=base64.b64encode((install['uuid']+':admin_local_secret').encode()).decode()
def get(url,headers=None,timeout=40,limit=8*1024*1024):
 start=time.monotonic()
 with urllib.request.urlopen(urllib.request.Request(url,headers=headers or {}),timeout=timeout) as response:
  ttfb=time.monotonic()-start;body=response.read(limit)
  return response.status,body,round(ttfb,3),round(time.monotonic()-start,3),response.headers.get('Content-Type','')
_,body,_,_,_=get('http://aiostreams:3000/api/v1/user',{'Authorization':'Basic '+auth})
profile=json.loads(body)['data']['userData']
report={'scope':'existing installation; configuration unchanged; credentials stay in container memory',
        'cachePolicy':'first-observed/warm/concurrent; shared caches are not cleared',
        'routes':[],'measurements':[],'limits':['No forced cache flush in existing installation','Transport health is not media decoding','No exact external request-count claim']}
custom={}
for preset in profile.get('presets',[]):
 opts=preset.get('options',{});entry={'instance':preset.get('instanceId'),'type':preset.get('type'),'enabled':bool(preset.get('enabled')),'resources':opts.get('resources',[])}
 report['routes'].append(entry)
 if entry['enabled'] and entry['type']=='custom' and opts.get('manifestUrl'):custom[entry['instance']]=opts['manifestUrl'].rsplit('/manifest.json',1)[0]
base='http://aiostreams:3000/stremio/{}/{}'.format(install['uuid'],install.get('encrypted_password') or install.get('encryptedPassword'))

def measure(label,url,mode='first-observed',headers=None,limit=8*1024*1024):
 row={'path':label,'mode':mode}
 try:
  code,body,ttfb,total,kind=get(url,headers,limit=limit)
  row.update(http=code,ttfbSeconds=ttfb,totalSeconds=total,bytes=len(body))
  try:
   value=json.loads(body)
   if isinstance(value,list):count=len(value);playable=None
   else:
    values=value.get('streams',value.get('metas',value.get('subtitles',[])))
    count=len(values);playable=sum(bool(s.get('url') or s.get('externalUrl') or s.get('infoHash')) for s in value.get('streams',[]))
   row.update(items=count,playable=playable,successful=code==200 and (count>0 or bool(isinstance(value,dict) and (value.get('meta') or value.get('id')))))
  except (ValueError,TypeError):row['successful']=code in (200,206) and kind.startswith('image/') and bool(body)
 except urllib.error.HTTPError as error:row.update(successful=False,error=type(error).__name__,http=error.code)
 except Exception as error:row.update(successful=False,error=type(error).__name__)
 return row

cases=[('movie','tt15239678'),('series','tt0944947:2:2')]
for kind,ident in cases:
 url=base+f'/stream/{kind}/{ident}.json'
 for mode in ('first-observed','warm'):report['measurements'].append(measure('AIOStreams '+kind,url,mode))
 with ThreadPoolExecutor(max_workers=2) as pool:
  report['measurements'].extend(pool.map(lambda _:measure('AIOStreams '+kind,url,'concurrent-2'),range(2)))
 # Direct custom requests use exactly the applied profile's manifest configuration.
 for instance,prefix in custom.items():
  allowed={'sootio-local','debrid-search-local'}
  if instance in allowed:report['measurements'].append(measure(instance+' direct '+kind,prefix+f'/stream/{kind}/{ident}.json'))

services=[s for s in profile.get('services',[]) if s.get('enabled') and s.get('credentials',{}).get('apiKey') and s.get('id')!='nzbdav']
if services:
 comet={'debridServices':[{'service':s['id'],'apiKey':s['credentials']['apiKey']} for s in services],
        'enableTorrent':False,'scrapeDebridAccountTorrents':False,'cachedOnly':False,'removeTrash':True,
        'maxResultsPerResolution':0,'maxSize':0,'resultFormat':['all']}
 token=base64.b64encode(json.dumps(comet).encode()).decode()
 for kind,ident in cases:report['measurements'].append(measure('Comet direct '+kind,'http://comet:8000/'+token+f'/stream/{kind}/{ident}.json'))

for query in ('Dune Part Two','Game of Thrones S02E02'):
 report['measurements'].append(measure('Zilean hash lookup','http://zilean:8181/dmm/filtered?'+urllib.parse.urlencode({'query':query})))
if 'subsense-local' in custom:
 report['measurements'].append(measure('SubSense subtitles',custom['subsense-local']+'/subtitles/movie/tt1375666.json'))
report['measurements'].append(measure('Kitsu anime metadata','http://anime-kitsu:7000/meta/anime/kitsu:1.json'))
subtitle_config=urllib.parse.quote(json.dumps({'languages':['eng']},separators=(',',':')),safe='')
report['measurements'].append(measure('SubSense corrected configured route','http://subsense:3100/'+subtitle_config+'/subtitles/movie/tt1375666.json'))
saved={}
if Path('/app/.env').is_file():
 saved=dict(line.split('=',1) for line in Path('/app/.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
poster_key=os.environ.get('POSTERSPLUS_ACCESS_KEY') or saved.get('POSTERSPLUS_ACCESS_KEY','')
poster_url='http://postersplus:8000/poster?'+urllib.parse.urlencode({'stremio_id':'tt1375666',**({'access_key':poster_key} if poster_key else {})})
report['measurements'].append(measure('Posters corrected query route',poster_url,limit=256*1024))
for name,url in [('StremThru transport health','http://stremthru:8080/v0/health'),('MediaFlow transport health','http://mediaflow:8888/health')]:
 row=measure(name,url);row['scope']='health only';row['successful']=row.get('http')==200;report['measurements'].append(row)
for kind,ident in cases:
 row={'path':'AIOStreams '+kind+' media range','scope':'1024-byte origin read; not media decode'}
 start=time.monotonic()
 try:
  _,body,_,_,_=get(base+f'/stream/{kind}/{ident}.json')
  candidates=[s for s in json.loads(body).get('streams',[]) if s.get('url')]
  assert candidates
  target=candidates[0]['url'];parsed=urllib.parse.urlsplit(target)
  ports={None:('aiostreams',3000),3000:('aiostreams',3000),3001:('aiostreams',3000),55771:('sootio',55771),8080:('stremthru',8080)}
  if parsed.hostname in ('localhost','127.0.0.1','aio.yourdomain.com') and parsed.port in ports:
   host,port=ports[parsed.port];target=urllib.parse.urlunsplit(('http',f'{host}:{port}',parsed.path,parsed.query,''));row['addressOverride']='internal service address; public hostname not validated'
  code,body,ttfb,total,kind_header=get(target,{'Range':'bytes=0-1023'},timeout=45,limit=1024)
  row.update(http=code,bytes=len(body),ttfbSeconds=ttfb,totalSeconds=round(time.monotonic()-start,3),successful=code in (200,206) and len(body)==1024 and not kind_header.startswith(('text/','application/json')))
 except Exception as error:row.update(successful=False,error=type(error).__name__,totalSeconds=round(time.monotonic()-start,3))
 report['measurements'].append(row)
print(json.dumps(report,indent=2))
