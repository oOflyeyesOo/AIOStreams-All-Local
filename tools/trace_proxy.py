"""Opt-in internal HTTP tracing. Never records URLs, queries, headers or bodies."""
import collections
import http.client
import http.server
import json
import hashlib
import hmac
import secrets
import os
import threading
import time
import urllib.parse

TARGETS = {'comet':('comet',8000),
           'prowlarr':('prowlarr',9696), 'zilean':('zilean',8181),
           'aiometadata':('aiometadata',4005), 'subsense':('subsense',3100),
           'anime-kitsu':('anime-kitsu',7000), 'postersplus':('postersplus',8000),
           'search-broker':('search-broker',8091)}
LOCK = threading.Lock()
EVENTS = []
FINGERPRINT_KEY = secrets.token_bytes(32)
HOP = {'connection','transfer-encoding','keep-alive','proxy-authenticate','proxy-authorization','te','trailer','upgrade','host'}

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self): self.forward()
    def do_POST(self): self.forward()
    def forward(self):
        if self.path in ('/__trace/report','/__trace/reset'):
            with LOCK:
                if self.path.endswith('reset'): EVENTS.clear()
                body=json.dumps(list(EVENTS)).encode()
            self.send_response(200); self.send_header('Content-Length',str(len(body))); self.end_headers();self.wfile.write(body);return
        edge=getattr(self.server,'trace_edge',None)
        if edge:
            service=edge['service'];path=self.path
        else:
            service, _, rest=self.path.lstrip('/').partition('/');path='/'+rest
        if service not in TARGETS: self.send_error(404);return
        clean=urllib.parse.urlsplit(path).path
        category=next((name for name in ('stream','manifest','catalog','meta','subtitles') if '/'+name+'/' in clean or clean.endswith('/'+name+'.json')), 'api')
        started=time.monotonic();status=502
        event={'service':service,'resource':category,'method':self.command,'status':None,'seconds':None,'finished':False,'requestFingerprint':hmac.new(FINGERPRINT_KEY,(self.command+' '+service+' '+path).encode(),hashlib.sha256).hexdigest()[:24]}
        if edge:event['caller']=edge['caller']
        with LOCK:
            if len(EVENTS)>=10000:del EVENTS[:1000]
            EVENTS.append(event)
        connection=http.client.HTTPConnection(*TARGETS[service],timeout=150)
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length>2*1024*1024: self.send_error(413);return
            body=self.rfile.read(length) if length else None
            headers={k:v for k,v in self.headers.items() if k.lower() not in HOP}
            connection.request(self.command,path,body,headers)
            response=connection.getresponse();status=response.status
            self.send_response(status)
            for k,v in response.getheaders():
                if k.lower() not in HOP and k.lower()!='content-length':self.send_header(k,v)
            self.end_headers()
            while chunk:=response.read(65536): self.wfile.write(chunk)
        except (OSError,http.client.HTTPException):
            if status==502:self.send_error(502)
        finally:
            connection.close()
            with LOCK: event.update(status=status,seconds=round(time.monotonic()-started,3),finished=True)

if __name__=='__main__':
    # Separate internal listeners preserve native addon paths and attribute callers.
    # Example: [{"port":8101,"service":"comet","caller":"aiostreams"}]
    for edge in json.loads(os.environ.get('TRACE_EDGES_JSON','[]')):
        if edge['service'] not in TARGETS or not str(edge['caller']).replace('-','').isalnum():
            raise ValueError('Invalid trace edge')
        server=http.server.ThreadingHTTPServer(('0.0.0.0',int(edge['port'])),Handler)
        server.trace_edge=edge
        threading.Thread(target=server.serve_forever,daemon=True).start()
    http.server.ThreadingHTTPServer(('0.0.0.0',8090),Handler).serve_forever()
