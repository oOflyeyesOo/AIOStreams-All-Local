"""Offline generated-video addon; only for the isolated acceptance Compose project."""
import http.server
import json
import os
from pathlib import Path
import re

MEDIA = Path('/media/fixture.webm')
META = {'id': 'tt0000001', 'type': 'movie', 'name': 'Generated acceptance video',
        'description': 'Synthetic test pattern and tone; no external media.'}

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/media/fixture.webm':
            size = MEDIA.stat().st_size
            start, end = 0, size - 1
            range_header = self.headers.get('Range')
            if range_header:
                match = re.fullmatch(r'bytes=(\d+)-(\d*)', range_header)
                if not match or int(match[1]) >= size:
                    self.send_response(416)
                    self.send_header('Content-Range', f'bytes */{size}')
                    self.end_headers()
                    return
                start = int(match[1])
                end = min(int(match[2]) if match[2] else end, end)
                if end < start:
                    self.send_error(416)
                    return
            self.send_response(206 if range_header else 200)
            self.send_header('Content-Type', 'video/webm')
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Access-Control-Allow-Origin', '*')
            if range_header:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.send_header('Content-Length', str(end-start+1))
            self.end_headers()
            with MEDIA.open('rb') as source:
                source.seek(start)
                self.wfile.write(source.read(end-start+1))
            return
        if path == '/player':
            body = b'<!doctype html><html><body><h1>Browser decode fixture</h1><video id="video" controls muted></video></body></html>'
            kind = 'text/html'
        else:
            if path == '/manifest.json':
                data = {'id': 'local.generated.media', 'name': 'Generated fixture', 'version': '1.0.0',
                        'description': 'Offline fixture', 'types': ['movie'], 'resources': ['catalog','meta','stream'],
                        'catalogs': [{'type': 'movie', 'id': 'fixture', 'name': 'Acceptance video'}]}
            elif path.startswith('/catalog/movie/fixture'):
                data = {'metas': [META]}
            elif path == '/meta/movie/tt0000001.json':
                data = {'meta': META}
            elif path == '/stream/movie/tt0000001.json':
                data = {'streams': [{'name': 'Generated fixture', 'title': 'Generated video 180p VP8',
                    'url': 'http://media-fixture:8099/media/fixture.webm',
                    'behaviorHints': {'notWebReady': False, 'filename': 'fixture.webm', 'videoSize': MEDIA.stat().st_size}}]}
            elif path == '/health':
                data = {'ready': MEDIA.is_file()}
            else:
                self.send_error(404)
                return
            body = json.dumps(data).encode()
            kind = 'application/json'
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

if __name__ == '__main__':
    if os.environ.get('AIO_FRESH_INSTALL_TEST') != 'true':
        raise SystemExit('Disposable fixture opt-in required')
    http.server.ThreadingHTTPServer(('0.0.0.0', 8099), Handler).serve_forever()
