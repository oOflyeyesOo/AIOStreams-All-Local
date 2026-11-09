"""Bounded internal search gateway. Keys and query text are never logged."""
import collections
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
import hashlib
import http.client
import http.server
import json
import os
import threading
import time

class SearchCache:
    def __init__(self, fetch, *, workers=4, ttl=60, cooldown=120, byte_limit=32*1024*1024, max_entries=256, wait=12):
        self.fetch=fetch;self.ttl=ttl;self.cooldown=cooldown;self.byte_limit=byte_limit;self.max_entries=max_entries;self.wait=wait
        self.pool=ThreadPoolExecutor(max_workers=workers);self.slots=threading.BoundedSemaphore(workers)
        self.lock=threading.Lock();self.cache=collections.OrderedDict();self.pending={};self.bytes=0
        self.metrics=collections.Counter()
    def get(self,path,headers):
        # Partition by credentials as well as target, without retaining either in cache keys.
        key=hashlib.sha256(json.dumps([path,sorted((k.lower(),v) for k,v in headers.items() if k.lower() in ('authorization','x-api-key'))]).encode()).digest()
        with self.lock:
            entry=self.cache.get(key)
            if entry and entry[0]>time.monotonic():
                self.metrics['cacheHits']+=1;self.cache.move_to_end(key);return entry[1]
            if entry:self.bytes-=len(self.cache.pop(key)[1][2])
            future=self.pending.get(key)
            if future is not None:self.metrics['coalesced']+=1
            else:
                if not self.slots.acquire(blocking=False):
                    self.metrics['busy']+=1;return 503,{'Retry-After':'2'},b'Search capacity reached'
                future=Future();self.pending[key]=future
                self.pool.submit(self._fetch,key,future,path,dict(headers))
        try:return future.result(timeout=self.wait)
        except TimeoutError:return 504,{'Retry-After':str(self.cooldown)},b'Search deadline reached'
    def _fetch(self,key,future,path,headers):
        failed=False
        try:
            with self.lock:self.metrics['upstreamCalls']+=1
            response=self.fetch(path,headers)
            failed=response[0]>=500
            if len(response[2])>self.byte_limit:raise ValueError('Response too large')
        except Exception:
            response=(504,{'Retry-After':str(self.cooldown)},b'Upstream search timed out or failed');failed=True
        with self.lock:
            if failed:self.metrics['upstreamFailures']+=1
            # Retain a short failure cooldown so late upstream work is not multiplied.
            if failed or response[0]==200:
                lifetime=self.cooldown if failed else self.ttl
                self.cache[key]=(time.monotonic()+lifetime,response);self.bytes+=len(response[2])
                while self.bytes>self.byte_limit or len(self.cache)>self.max_entries:
                    _,old=self.cache.popitem(last=False);self.bytes-=len(old[1][2])
            self.pending.pop(key,None)
        future.set_result(response);self.slots.release()
    def status(self):
        with self.lock:return {'status':'ok','inFlight':len(self.pending),'cacheEntries':len(self.cache),'cacheBytes':self.bytes,**self.metrics}
    def close(self):self.pool.shutdown(wait=True)

class IndexerFilter:
    """Discovers and caches healthy Prowlarr indexers, excluding degraded ones."""
    def __init__(self, host, port, refresh_interval=30):
        self.host = host
        self.port = port
        self.refresh_interval = refresh_interval
        self.last_refresh = 0
        self.healthy_ids = None
        self.lock = threading.Lock()

    def get_healthy_ids(self, api_key):
        now = time.monotonic()
        with self.lock:
            if self.healthy_ids is not None and (now - self.last_refresh) < self.refresh_interval:
                return self.healthy_ids

        try:
            headers = {"X-Api-Key": api_key}
            # Query disabled/degraded status
            conn = http.client.HTTPConnection(self.host, self.port, timeout=3)
            conn.request("GET", "/api/v1/indexerstatus", headers=headers)
            res = conn.getresponse()
            disabled_ids = set()
            if res.status == 200:
                data = json.loads(res.read().decode())
                for d in data:
                    disabled_ids.add(d.get("indexerId"))
            conn.close()

            # Query all indexers
            conn = http.client.HTTPConnection(self.host, self.port, timeout=3)
            conn.request("GET", "/api/v1/indexer", headers=headers)
            res2 = conn.getresponse()
            healthy = []
            if res2.status == 200:
                indexers = json.loads(res2.read().decode())
                for idx in indexers:
                    iid = idx.get("id")
                    if idx.get("enable", True) and iid not in disabled_ids:
                        healthy.append(iid)
            conn.close()

            with self.lock:
                if healthy:
                    self.healthy_ids = healthy
                    self.last_refresh = now
                return self.healthy_ids
        except Exception:
            with self.lock:
                return self.healthy_ids

UPSTREAM=os.environ.get('SEARCH_UPSTREAM_HOST','prowlarr')
PORT=int(os.environ.get('SEARCH_UPSTREAM_PORT','9696'))
TIMEOUT=float(os.environ.get('SEARCH_TIMEOUT','8'))
MAX_BODY=4*1024*1024
INDEXER_FILTER = IndexerFilter(UPSTREAM, PORT)

def fetch(path,headers):
    # Auto-inject healthy indexer IDs into general broadcast searches to avoid stalling on degraded trackers
    if '/api/v1/search' in path and 'indexerIds=' not in path:
        api_key = headers.get('x-api-key') or headers.get('X-Api-Key')
        if not api_key and 'apikey=' in path:
            try:
                import urllib.parse
                parsed = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
                api_key = parsed.get('apikey', [None])[0]
            except Exception:
                pass
        if api_key:
            healthy = INDEXER_FILTER.get_healthy_ids(api_key)
            if healthy:
                param = '&'.join(f'indexerIds={i}' for i in healthy)
                delimiter = '&' if '?' in path else '?'
                path = f"{path}{delimiter}{param}"

    connection=http.client.HTTPConnection(UPSTREAM,PORT,timeout=TIMEOUT)
    try:
        connection.request('GET',path,headers={k:v for k,v in headers.items() if k.lower() not in ('host','connection','accept-encoding')})
        response=connection.getresponse();body=response.read(MAX_BODY+1)
        if len(body)>MAX_BODY:raise ValueError('Oversized search result')
        return response.status,{k:v for k,v in response.getheaders() if k.lower() in ('content-type','retry-after')},body
    finally:connection.close()

class Handler(http.server.BaseHTTPRequestHandler):
    cache=None
    def log_message(self,*args):pass
    def do_GET(self):
        if self.path in ('/healthz','/status'):
            status=200;headers={'Content-Type':'application/json'};body=json.dumps(self.cache.status()).encode()
        elif len(self.path)>16384:
            status,headers,body=414,{},b'Request too long'
        else:status,headers,body=self.cache.get(self.path,dict(self.headers))
        self.send_response(status)
        for k,v in headers.items():self.send_header(k,v)
        self.send_header('Content-Length',str(len(body)));self.end_headers()
        try:self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError):pass

if __name__=='__main__':
    Handler.cache=SearchCache(fetch,workers=int(os.environ.get('SEARCH_WORKERS','4')),ttl=int(os.environ.get('SEARCH_CACHE_TTL','60')),cooldown=int(os.environ.get('SEARCH_FAILURE_COOLDOWN','120')),wait=TIMEOUT+2)
    http.server.ThreadingHTTPServer(('0.0.0.0',8091),Handler).serve_forever()
