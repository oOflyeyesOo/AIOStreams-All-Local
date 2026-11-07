import http.server
import json
import threading
import unittest
import urllib.request
from unittest.mock import patch
from tools import trace_proxy

class TraceProxyTests(unittest.TestCase):
    def test_trace_counts_requests_without_recording_secrets(self):
        class Upstream(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                body=b'{"streams":[]}'
                self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        upstream=http.server.ThreadingHTTPServer(('127.0.0.1',0),Upstream)
        proxy=http.server.ThreadingHTTPServer(('127.0.0.1',0),trace_proxy.Handler)
        threads=[threading.Thread(target=s.serve_forever,daemon=True) for s in (upstream,proxy)]
        for t in threads:t.start()
        try:
            with patch.dict(trace_proxy.TARGETS,{'fixture':upstream.server_address}):
                base=f'http://127.0.0.1:{proxy.server_port}'
                urllib.request.urlopen(base+'/__trace/reset').close()
                with urllib.request.urlopen(base+'/fixture/private-config/stream/movie/tt1.json?apikey=must-stay-private') as response:
                    self.assertEqual(json.load(response),{'streams':[]})
                with urllib.request.urlopen(base+'/__trace/report') as response:events=json.load(response)
                self.assertEqual(len(events),1)
                self.assertEqual(events[0]['resource'],'stream')
                self.assertEqual(events[0]['status'],200)
                self.assertNotIn('must-stay-private',json.dumps(events))
                self.assertNotIn('private-config',json.dumps(events))
                proxy.trace_edge={'service':'fixture','caller':'aiostreams'}
                urllib.request.urlopen(base+'/__trace/reset').close()
                with urllib.request.urlopen(base+'/private-native-config/stream/series/tt1:2:2.json') as response:
                    self.assertEqual(json.load(response),{'streams':[]})
                with urllib.request.urlopen(base+'/__trace/report') as response:events=json.load(response)
                self.assertEqual(events[0]['caller'],'aiostreams')
                self.assertEqual(events[0]['resource'],'stream')
                self.assertNotIn('private-native-config',json.dumps(events))
        finally:
            for server in (proxy,upstream):server.shutdown();server.server_close()
            for t in threads:t.join()
