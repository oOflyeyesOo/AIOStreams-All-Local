const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('docker/stremio-web/bootstrap.js', 'utf8');

function run(existing, options = {}) {
  const store = new Map();
  if (existing === undefined) existing = {auth: null, addons: [], settings: {language: 'eng', interfaceScale: 1}};
  if (existing) store.set('profile', JSON.stringify(existing));
  if (options.seeded) store.set('aio_profile_seeded', '1');
  const defaults = {schema_version: 16, profile: {auth: null, addons: [], settings: {language: 'eng'}}};
  const seed = {profile: {addons: options.pending ? [] : [{manifest: {id: 'aio'}, transportUrl: 'http://server:3000/manifest.json'}], settings: {}}};
  class Request {
    open(method, path) { this.path = path; }
    send() { this.status = options.failed ? 503 : 200; this.responseText = JSON.stringify(this.path.includes('defaults') ? defaults : seed); }
  }
  vm.runInNewContext(source, {XMLHttpRequest: Request, document: {readyState: 'loading'}, setTimeout() {}, console: {warn() {}}, location: {origin: 'http://server:8082', reload() {}},
    localStorage: {getItem(key) { return store.get(key) ?? null; }, setItem(key, value) { store.set(key, value); }}});
  return store;
}

test('initialized guest gets local addon and same-origin streaming engine', () => {
  const store = run();
  const profile = JSON.parse(store.get('profile'));
  assert.equal(profile.addons[0].manifest.id, 'aio');
  assert.equal(profile.settings.language, 'eng');
  assert.equal(profile.settings.streamingServerUrl, 'http://server:8082/');
  assert.equal(profile.settings.interfaceScale, 1);
});
test('first visit fills the complete image defaults and required interface scale', () => {
  const store = run(null);
  const profile = JSON.parse(store.get('profile'));
  assert.equal(profile.settings.interfaceScale, 1);
  assert.equal(store.get('schema_version'), '16');
});
test('signed-in profile stays unchanged', () => {
  const profile = {auth: {key: 'test'}, addons: [], settings: {}};
  assert.deepEqual(JSON.parse(run(profile).get('profile')), profile);
});
test('existing guest keeps preferences and installed addons', () => {
  const profile = {auth: null, addons: [{manifest: {id: 'custom'}}], settings: {language: 'fra'}};
  const result = JSON.parse(run(profile).get('profile'));
  assert.equal(result.settings.language, 'fra');
  assert.deepEqual(result.addons.map(addon => addon.manifest.id), ['aio', 'custom']);
});
test('already seeded guest is unchanged', () => {
  const profile = {auth: null, addons: [], settings: {}};
  assert.deepEqual(JSON.parse(run(profile, {seeded: true}).get('profile')), profile);
});
test('pending setup and failed requests leave browser storage unchanged', () => {
  assert.equal(run(null, {pending: true}).size, 0);
  assert.equal(run(null, {failed: true}).size, 0);
});
