"""Inspect the configured local profile without printing credential-bearing URLs."""
import json
from pathlib import Path
import urllib.parse
import urllib.request

info = json.loads(Path('/app/data/aiostreams/aiostreams_install.json').read_text())
url = 'http://aiostreams:3000/stremio/{}/{}/stream/movie/tt1375666.json'.format(
    info['uuid'], info.get('encrypted_password') or info.get('encryptedPassword'))
try:
    with urllib.request.urlopen(url, timeout=60) as response:
        data = json.load(response)
    streams = data.get('streams', [])
    print('Returned stream entries:', len(streams))
    for stream in streams[:5]:
        parsed = urllib.parse.urlsplit(stream.get('url', ''))
        print(json.dumps({'title': stream.get('title') or stream.get('description'),
                          'urlHost': parsed.hostname,
                          'infoHashPresent': bool(stream.get('infoHash')),
                          'behaviorHints': list(stream.get('behaviorHints', {}))}))
except Exception as error:
    print('Stream request failed:', type(error).__name__)
