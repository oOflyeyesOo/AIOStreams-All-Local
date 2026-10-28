"""Bounded, read-only playback-origin probe. Does not print credential-bearing URLs."""
import json
from pathlib import Path
import urllib.parse
import urllib.request

info = json.loads(Path('/app/data/aiostreams/aiostreams_install.json').read_text())
url = 'http://aiostreams:3000/stremio/{}/{}/stream/movie/tt1375666.json'.format(
    info['uuid'], info.get('encrypted_password') or info.get('encryptedPassword'))
try:
    with urllib.request.urlopen(url, timeout=60) as response:
        streams = json.load(response).get('streams', [])
    candidates = [stream for stream in streams if stream.get('url') and 'AVC' in stream.get('description', stream.get('title', ''))]
    if not candidates:
        raise ValueError('No browser-compatible codec candidate')
    candidate = min(candidates, key=lambda stream: stream.get('behaviorHints', {}).get('videoSize', 1e15))
    parsed = urllib.parse.urlsplit(candidate['url'])
    target = candidate['url']
    if parsed.hostname in ('localhost', '127.0.0.1') and parsed.port == 55771:
        target = urllib.parse.urlunsplit(('http', 'sootio:55771', parsed.path, parsed.query, ''))
    elif parsed.hostname in ('aio.yourdomain.com', 'localhost') and parsed.port in (3000, 3001, None):
        target = urllib.parse.urlunsplit(('http', 'aiostreams:3000', parsed.path, parsed.query, ''))
    request = urllib.request.Request(target, headers={'Range': 'bytes=0-1023'})
    with urllib.request.urlopen(request, timeout=45) as response:
        block = response.read(1024)
        print('Origin status:', response.status)
        print('Content type:', response.headers.get('Content-Type'))
        print('Media bytes received:', len(block))
        print('Origin host:', urllib.parse.urlsplit(response.url).hostname)
        print('Container signature:', 'Matroska/WebM' if block.startswith(bytes.fromhex('1a45dfa3')) else 'other')
except Exception as error:
    print('Playback origin probe failed:', type(error).__name__)
