"""Live manifest/stream/range acceptance. Output contains no credentials or signed URLs.
Run inside the portal after setup: python3 /app/tests/check_release.py
Decode the private candidates with tests/decode_playback.cjs in the web-player container.
"""
import json
import os
from pathlib import Path
import time
import urllib.request
import urllib.parse

ROOT = Path(os.environ.get('WEB_ROOT', Path(__file__).resolve().parent.parent))
CASES = [('movie', 'tt1375666'), ('series', 'tt0944947:1:1')]


def request(url, timeout=90):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def internal_url(url):
    parsed = urllib.parse.urlsplit(url)
    # Translate only loopback publication to the matching container endpoint.
    ports = {3001: ('aiostreams', 3000), 13001: ('aiostreams', 3000),
             8000: ('comet', 8000), 18000: ('comet', 8000)}
    if parsed.hostname in ('localhost', '127.0.0.1') and parsed.port in ports:
        host, port = ports[parsed.port]
        return urllib.parse.urlunsplit((parsed.scheme, f'{host}:{port}', parsed.path, parsed.query, ''))
    return url


def main():
    report, candidates = [], []
    try:
        info = json.loads((ROOT/'data/aiostreams/aiostreams_install.json').read_text())
        token = info.get('encrypted_password') or info.get('encryptedPassword')
        base = f"http://aiostreams:3000/stremio/{info['uuid']}/{token}"
        manifest = request(base+'/manifest.json')
        report.append({'check': 'personalized manifest', 'passed': bool(manifest.get('id') and manifest.get('resources'))})
        alias = request('http://aiostreams:3000/stremio/u/local/manifest.json')
        report.append({'check': 'stable alias', 'passed': alias.get('id') == manifest.get('id')})
        for kind, media_id in CASES:
            try:
                started = time.monotonic()
                data = request(base+f'/stream/{kind}/{media_id}.json', 120)
                streams = [s for s in data.get('streams', []) if s.get('url')]
                elapsed = round(time.monotonic()-started, 2)
                urls = [s['url'] for s in streams]
                report.append({'check': kind+' stream lookup', 'passed': bool(streams),
                               'seconds': elapsed, 'playableCandidates': len(streams),
                               'duplicateUrls': len(urls)-len(set(urls))})
                ordered = sorted(streams, key=lambda s: (not any(c in str(s) for c in ('AVC','H.264','H264')), s.get('behaviorHints',{}).get('videoSize') or 10**15))
                passed = False
                for candidate in ordered[:3]:
                    try:
                        target = internal_url(candidate['url'])
                        with urllib.request.urlopen(urllib.request.Request(target, headers={'Range':'bytes=0-65535'}), timeout=45) as response:
                            block = response.read(65536)
                            media = block.startswith(bytes.fromhex('1a45dfa3')) or b'ftyp' in block[:32] or block[:1] == b'G'
                            passed = response.status in (200,206) and len(block) >= 1024 and media
                            if passed:
                                candidates.append({'kind':kind,'url':target})
                                report.append({'check':kind+' media range','passed':True,'status':response.status,'bytes':len(block)})
                                break
                    except Exception:
                        continue
                if not passed:report.append({'check':kind+' media range','passed':False})
                started=time.monotonic();again=request(base+f'/stream/{kind}/{media_id}.json',120)
                report.append({'check':kind+' repeated lookup','passed':any(s.get('url') for s in again.get('streams', [])),'seconds':round(time.monotonic()-started,2)})
            except Exception as error:
                report.append({'check':kind,'passed':False,'errorType':type(error).__name__})
    except Exception as error:
        report.append({'check':'profile readiness','passed':False,'errorType':type(error).__name__})
    # These URLs are private runtime data, never a source artifact or console output.
    output = ROOT/'data/stremio-web/playback-candidates.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(candidates))
    try:
        os.chmod(output,0o600)
    except OSError:
        pass
    print(json.dumps(report,indent=2))
    return 0 if report and all(row['passed'] for row in report) else 1


if __name__ == '__main__':
    raise SystemExit(main())
