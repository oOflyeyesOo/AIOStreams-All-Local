// Run in stremio-web. Reads private runtime URLs; prints only bounded decode results.
const fs = require('fs');
const {spawnSync} = require('child_process');
const candidates = JSON.parse(fs.readFileSync('/aio-config/playback-candidates.json', 'utf8'));
let failed = candidates.length !== 2;
for (const item of candidates) {
  const result = spawnSync('ffmpeg', ['-nostdin', '-hide_banner', '-loglevel', 'error',
    '-rw_timeout', '30000000', '-i', item.url, '-t', '15', '-map', '0:v:0',
    '-map', '0:a:0?', '-f', 'null', '-'], {timeout: 90000, maxBuffer: 1024*1024});
  const passed = result.status === 0;
  console.log(JSON.stringify({check: item.kind + ' 15-second media decode', passed, exitCode: result.status}));
  failed ||= !passed;
}
process.exitCode = failed ? 1 : 0;
