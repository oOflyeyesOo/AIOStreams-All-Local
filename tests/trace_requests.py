"""Collect sanitized per-case internal request traces from the opt-in trace proxy."""
import json
from pathlib import Path
import time
import urllib.request

def get(url,timeout=120):
 with urllib.request.urlopen(url,timeout=timeout) as response:return json.load(response)
p=json.loads(Path('/app/data/aiostreams/aiostreams_install.json').read_text())
base='http://aiostreams:3000/stremio/{}/{}'.format(p['uuid'],p.get('encrypted_password') or p.get('encryptedPassword'))
def drain():
 deadline=time.monotonic()+160
 while True:
  events=get('http://trace:8090/__trace/report')
  if all(e.get('finished',True) for e in events):return events
  if time.monotonic()>deadline:raise RuntimeError('Trace still has unfinished requests; refusing to mix cases')
  time.sleep(1)
results=[]
for kind,ident in [('movie','tt1375666'),('series','tt0944947:1:1')]:
 for attempt in (1,2):
  drain();get('http://trace:8090/__trace/reset');start=time.monotonic()
  try:
   payload=get(base+f'/stream/{kind}/{ident}.json');playable=sum(bool(s.get('url')) for s in payload.get('streams',[]));error=None
  except Exception as ex:playable=0;error=type(ex).__name__
  elapsed=round(time.monotonic()-start,3)
  # AIOStreams may cancel a scraper before its server finishes the HTTP request.
  events=drain()
  results.append({'kind':kind,'attempt':attempt,'seconds':elapsed,'playable':playable,'error':error,'events':events})
print(json.dumps(results,indent=2))
