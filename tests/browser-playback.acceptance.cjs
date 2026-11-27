'use strict';
// Actual Chromium decoding of a generated stream returned by AIOStreams.
// Signs in and starts the generated movie through the real native player UI.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
let stage = 'fixture validation';
(async () => {
  assert.equal(process.env.AIO_FRESH_INSTALL_TEST, 'true');
  const profile = JSON.parse(fs.readFileSync('/fixture/aiostreams_install.json', 'utf8'));
  assert.equal(profile.password, 'package-test-only-password');
  const token = profile.encrypted_password || profile.encryptedPassword;
  assert(profile.uuid && token);
  const base = `http://aiostreams:3000/stremio/${encodeURIComponent(profile.uuid)}/${encodeURIComponent(token)}`;
  stage = 'AIOStreams stream lookup';
  const response = await fetch(`${base}/stream/movie/tt0000001.json`, {signal: AbortSignal.timeout(30000)});
  assert.equal(response.status, 200);
  const data = await response.json();
  const stream = data.streams.find(item => item.url === 'http://media-fixture:8099/media/fixture.webm');
  assert(stream, 'Generated stream missing from AIOStreams');
  const browser = await chromium.launch({headless: true});
  try {
    const context = await browser.newContext();
    await context.route('**/*', route => {
      const u = new URL(route.request().url());
      if (['aiostreams', 'media-fixture'].includes(u.hostname)) return route.continue();
      return route.abort();
    });
    const page = await context.newPage();
    stage = 'native player document';
    const native = await page.goto(`http://aiostreams:3000/jellyfin/${encodeURIComponent(profile.uuid)}/${encodeURIComponent(token)}/web/`, {waitUntil:'domcontentloaded', timeout:30000});
    assert.equal(native.status(), 200);
    stage = 'native player sign-in';
    await page.getByRole('button', {name:/Post-setup acceptance fixture/}).click();
    await page.locator('input[type=password]').fill('package-test-only-password');
    await page.getByRole('button', {name:'Sign in', exact:true}).click();
    stage = 'native catalog and stream selection';
    await page.getByText('Generated acceptance video', {exact:true}).first().click();
    await page.getByRole('button', {name:'Play', exact:true}).click();
    await page.getByRole('button', {name:/Local fixture/}).click();
    stage = 'native browser media decode';
    await page.waitForFunction(() => {
      const v = document.querySelector('video');
      return v.currentTime > 2 && v.getVideoPlaybackQuality().totalVideoFrames > 10 && !v.error;
    }, null, {timeout:20000});
    const before = await page.evaluate(() => { const v=document.querySelector('video');v.pause();return v.currentTime; });
    await page.waitForTimeout(300);
    assert(Math.abs((await page.evaluate(() => document.querySelector('video').currentTime)) - before) < 0.1);
    await page.evaluate(() => { const v=document.querySelector('video');v.currentTime=6; });
    await page.waitForFunction(() => Math.abs(document.querySelector('video').currentTime-6)<0.3 && !document.querySelector('video').seeking);
    await page.evaluate(() => document.querySelector('video').play());
    await page.waitForFunction(() => document.querySelector('video').currentTime>7, null, {timeout:10000});
    const stats = await page.evaluate(() => {const v=document.querySelector('video');return {seconds: Math.round(v.currentTime*10)/10, frames:v.getVideoPlaybackQuality().totalVideoFrames,error:!!v.error};});
    assert(!stats.error);
    console.log(JSON.stringify({check:'Native AIOStreams player: sign-in, catalog, play, decode, pause, seek, resume',passed:true,...stats}));
  } finally { await browser.close(); }
})().catch(() => { console.error('FAIL: browser playback acceptance at ' + stage + '; credential-bearing details suppressed'); process.exitCode=1; });
