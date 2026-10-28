// Upstream constructs Fanart's client at import time, crashing without a key.
// Keep Kitsu's normal artwork and Metahub fallback available without Fanart.
const fs = require('node:fs');
const file = 'lib/fanart.js';
let source = fs.readFileSync(file, 'utf8');
const constructor = 'const fanart = new FanartTvApi({ apiKey: process.env.FANART_APIKEY });';
const functionStart = 'function retrieveFanartImages(kitsuId, mappingInfo) {';
if (!source.includes(constructor) || !source.includes(functionStart)) {
  throw new Error('Upstream Fanart implementation changed; review the optional-key patch.');
}
source = source.replace(constructor,
  'const fanart = process.env.FANART_APIKEY ? new FanartTvApi({ apiKey: process.env.FANART_APIKEY }) : null;');
source = source.replace(functionStart,
  functionStart + '\n  if (!fanart) return Promise.resolve({});');
fs.writeFileSync(file, source);
