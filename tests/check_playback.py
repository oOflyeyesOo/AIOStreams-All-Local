"""Bounded media-range probe; success does not verify browser video decoding.

Run inside the portal after provisioning. Never print credential-bearing URLs.
"""
import json
from pathlib import Path
import urllib.parse
import urllib.request

INSTALL_INFO = Path('/app/data/aiostreams/aiostreams_install.json')


def probe(info):
    token = info.get('encrypted_password') or info.get('encryptedPassword')
    if not info.get('uuid') or not token:
        raise ValueError('Missing provisioned profile')
    url = 'http://aiostreams:3000/stremio/{}/{}/stream/movie/tt1375666.json'.format(
        urllib.parse.quote(str(info['uuid']), safe=''),
        urllib.parse.quote(str(token), safe=''))
    with urllib.request.urlopen(url, timeout=60) as response:
        streams = json.load(response).get('streams', [])
    candidates = [stream for stream in streams if stream.get('url') and 'AVC' in stream.get('description', stream.get('title', ''))]
    if not candidates:
        raise ValueError('No browser-compatible codec candidate')
    candidate = min(candidates, key=lambda stream: stream.get('behaviorHints', {}).get('videoSize') or 1e15)
    parsed = urllib.parse.urlsplit(candidate['url'])
    target = candidate['url']
    if parsed.hostname in ('aio.yourdomain.com', 'localhost') and parsed.port in (3000, 3001, None):
        target = urllib.parse.urlunsplit(('http', 'aiostreams:3000', parsed.path, parsed.query, ''))
    request = urllib.request.Request(target, headers={'Range': 'bytes=0-1023'})
    with urllib.request.urlopen(request, timeout=45) as response:
        block = response.read(1024)
        media = (block.startswith(bytes.fromhex('1a45dfa3')) or
                 b'ftyp' in block[:32] or
                 (len(block) > 376 and block[0] == block[188] == block[376] == 0x47))
        if response.status not in (200, 206) or len(block) < 1024 or not media:
            raise ValueError('Origin did not return a valid media range')
        return {'status': response.status, 'bytes': len(block)}


def main():
    try:
        result = probe(json.loads(INSTALL_INFO.read_text()))
        print('Media range probe passed: HTTP {}, {} bytes. Browser decoding not verified.'.format(
            result['status'], result['bytes']))
        return 0
    except Exception as error:
        # Exception messages can include signed playback URLs and provider keys.
        print('Media range probe failed:', type(error).__name__)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
