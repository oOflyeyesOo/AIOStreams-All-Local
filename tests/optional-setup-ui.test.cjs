const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('assets/app.js','utf8');

test('preset rejection displays the safe service reason without retrying the write',async()=>{
  let calls=0;
  const context=vm.createContext({URL,location:new URL('http://server:8088'),
    fetch:async()=>{calls++;return {ok:false,status:400,json:async()=>({
      errorCode:'AIOMETADATA_PRESET_FAILED',error:'Save the required API key(s): TMDB.'
    })};}
  });
  vm.runInContext(source.slice(source.indexOf('async function api('),source.indexOf('function notify(')),context);
  await assert.rejects(vm.runInContext("api('/api/aiometadata/apply-template',{method:'POST'})",context),
    /required API key.*TMDB/);
  assert.equal(calls,1);
});

test('preset failure keeps a safe generic error for non-JSON gateway responses',async()=>{
  const context=vm.createContext({URL,location:new URL('http://server:8088'),
    fetch:async()=>({ok:false,status:502,json:async()=>{throw Error('html gateway body');}})
  });
  vm.runInContext(source.slice(source.indexOf('async function api('),source.indexOf('function notify(')),context);
  await assert.rejects(vm.runInContext("api('/api/aiometadata/apply-template',{method:'POST'})",context),
    /server returned 502/);
});

function form(saved){
  const nodes=new Map(),calls=[];
  const document={
    querySelectorAll(){ return []; },
    getElementById(id){
      if(!nodes.has(id))nodes.set(id,{value:'',checked:false,style:{},handlers:{},addEventListener(type,handler){this.handlers[type]=handler;},scrollIntoView(){},closest(){return this;}});
      return nodes.get(id);
    }
  };
  const context=vm.createContext({document,URL,location:new URL('http://server:8088'),
    providers:[['PROVIDER_KEY']],fields:[['PROVIDER_KEY'],['NZB_INDEXER_API_KEY']],savedKeys:new Set(),
    usenetPasswordSaved:false,deriveAiometaHost:()=>'',setProgress:()=>{},pollSetup:async()=>{},renderPlaybackReadiness:()=>{},playbackBusy:false,setupFormDirty:false,lastJobStatus:"complete",refreshPlaybackReadiness:async()=>({ready:true}),
    notify:message=>{throw Error(message);},api:async(path,options)=>{
      if(path==='/api/env')return saved;
      calls.push({path,payload:options.body?JSON.parse(options.body):null});return {success:true};
    }});
  const load=source.match(/async function loadSettings\(options\) \{[\s\S]*?\n\}/)[0];
  const submit=source.slice(source.indexOf("document.getElementById('setup-form').addEventListener('submit'"),source.indexOf("document.getElementById('refresh-services').addEventListener"));
  vm.runInContext(source.match(/function escapeHtml\(str\) \{[\s\S]*?\n\}/)[0],context);
  const state=source.slice(source.indexOf('let settingsEditRevision ='),source.indexOf('async function loadSettings('));
  const dirty=source.match(/function setFormDirty\(dirty\) \{[\s\S]*?\n\}/)[0];
  vm.runInContext(state+'\n'+dirty+'\n'+load+'\n'+submit,context);
  return {context,nodes,calls,document};
}

function deferred() {
  let resolve,reject;
  const promise=new Promise((res,rej)=>{resolve=res;reject=rej;});
  return {promise,resolve,reject};
}

test('pending save blocks duplicate submission and preserves newer edits and dirty state',async()=>{
  const env=form({configuredKeys:['PROVIDER_KEY'],BASE_URL:'http://saved.example'});
  await vm.runInContext('loadSettings()',env.context);
  const pending=deferred();
  const api=env.context.api;
  env.context.api=async(path,options)=>{
    const result=await api(path,options);
    if(path==='/api/save-env')await pending.promise;
    return result;
  };
  const submit=env.nodes.get('setup-form').handlers.submit;
  const first=submit({preventDefault(){}});
  env.nodes.get('base-url').value='http://newer-edit.example';
  vm.runInContext('setFormDirty(true)',env.context);
  await submit({preventDefault(){}});
  assert.equal(env.calls.filter(c=>c.path==='/api/save-env').length,1);
  pending.resolve();
  await first;
  assert.equal(env.nodes.get('base-url').value,'http://newer-edit.example');
  assert.equal(vm.runInContext('setupFormDirty',env.context),true);
  assert.equal(env.calls.filter(c=>c.path==='/api/setup').length,1);
  assert.equal(vm.runInContext('setupSaveInFlight',env.context),false);
});

test('settings response cannot overwrite an edit made during post-save reload',async()=>{
  const saved={configuredKeys:['PROVIDER_KEY'],BASE_URL:'http://saved.example'};
  const env=form(saved);
  await vm.runInContext('loadSettings()',env.context);
  const pending=deferred(),started=deferred();
  const api=env.context.api;
  env.context.api=async(path,options)=>{
    if(path==='/api/env'){started.resolve();return pending.promise;}
    return api(path,options);
  };
  const saving=env.nodes.get('setup-form').handlers.submit({preventDefault(){}});
  await started.promise;
  env.nodes.get('stack-admin-password').value='newer-unsaved-password';
  vm.runInContext('setFormDirty(true)',env.context);
  pending.resolve(saved);
  await saving;
  assert.equal(env.nodes.get('stack-admin-password').value,'newer-unsaved-password');
  assert.equal(vm.runInContext('setupFormDirty',env.context),true);
});

test('older settings response cannot overwrite a newer response',async()=>{
  const env=form({configuredKeys:[]});
  const older=deferred(),newer=deferred();
  let requests=0;
  env.context.api=()=>++requests===1?older.promise:newer.promise;
  const first=vm.runInContext('loadSettings()',env.context);
  const second=vm.runInContext('loadSettings()',env.context);
  newer.resolve({BASE_URL:'http://new.example',configuredKeys:[]});
  await second;
  older.resolve({BASE_URL:'http://old.example',configuredKeys:[]});
  assert.equal(await first,false);
  assert.equal(env.nodes.get('base-url').value,'http://new.example');
});

test('failed save remains dirty and releases the guard so the user can retry',async()=>{
  const env=form({configuredKeys:['PROVIDER_KEY']});
  await vm.runInContext('loadSettings()',env.context);
  const api=env.context.api,messages=[];
  env.context.notify=message=>messages.push(message);
  env.context.api=async(path,options)=>{
    if(path==='/api/save-env')throw Error('fixture save failure');
    return api(path,options);
  };
  const submit=env.nodes.get('setup-form').handlers.submit;
  await submit({preventDefault(){}});
  assert.equal(vm.runInContext('setupFormDirty',env.context),true);
  assert.equal(vm.runInContext('setupSaveInFlight',env.context),false);
  assert.equal(env.nodes.get('setup-button').disabled,false);
  assert.ok(messages.includes('fixture save failure'));
  env.context.api=api;
  await submit({preventDefault(){}});
  assert.equal(env.calls.filter(c=>c.path==='/api/save-env').length,1);
  assert.equal(vm.runInContext('setupFormDirty',env.context),false);
});

test('Usenet-only saved account reloads safely and resubmits without clearing its password',async()=>{
  const env=form({USENET_ENABLED:'true',USENET_HOST:'news.fixture',USENET_PORT:'563',USENET_USER:'fixture-user',USENET_CONNECTIONS:'10',USENET_SSL:'true',USENET_PASSWORD_SAVED:true,configuredKeys:['NZB_INDEXER_API_KEY']});
  await vm.runInContext('loadSettings()',env.context);
  assert.equal(env.nodes.get('usenet-host').value,'news.fixture');assert.equal(env.nodes.get('usenet-pass').value,'');
  assert.match(env.nodes.get('usenet-pass').placeholder,/Saved/);
  assert.equal(env.nodes.get('enable-usenet').checked,true);
  await env.nodes.get('setup-form').handlers.submit({preventDefault(){}});
  const save=env.calls.find(c=>c.path==='/api/save-env').payload;
  assert.equal(save.USENET_ENABLED,'true');assert.equal(save.USENET_SSL,'true');
  assert.equal('USENET_PASS' in save,false);assert.equal('NZB_INDEXER_API_KEY' in save,false);
  assert.equal(env.calls.filter(c=>c.path==='/api/setup').length,1);
});

test('replacement Usenet password is submitted exactly, including whitespace and special characters',async()=>{
  const env=form({USENET_ENABLED:'true',USENET_PASSWORD_SAVED:true,configuredKeys:[]});
  await vm.runInContext('loadSettings()',env.context);
  const value=' fixture$pass\'" ';
  env.nodes.get('usenet-pass').value=value;
  await env.nodes.get('setup-form').handlers.submit({preventDefault(){}});
  assert.equal(env.calls.find(c=>c.path==='/api/save-env').payload.USENET_PASS,value);
});

test('Usenet-only user can disable it without being forced to add a debrid key',async()=>{
  const env=form({USENET_ENABLED:'true',USENET_PASSWORD_SAVED:true,configuredKeys:[]});
  await vm.runInContext('loadSettings()',env.context);
  env.nodes.get('enable-usenet').checked=false;
  await env.nodes.get('setup-form').handlers.submit({preventDefault(){}});
  const payload=env.calls.find(c=>c.path==='/api/save-env').payload;
  assert.equal(payload.USENET_ENABLED,'false');assert.equal('USENET_PASS' in payload,false);
  assert.equal(env.calls.filter(c=>c.path==='/api/setup').length,1);
});

test('native anime switch reloads and is saved with the selected account',async()=>{
  const env=form({ENABLE_ANIME_SOURCES:'true',USENET_ENABLED:'false',configuredKeys:['PROVIDER_KEY']});
  await vm.runInContext('loadSettings()',env.context);
  assert.equal(env.nodes.get('enable-anime-sources').checked,true);
  await env.nodes.get('setup-form').handlers.submit({preventDefault(){}});
  assert.equal(env.calls.find(c=>c.path==='/api/save-env').payload.ENABLE_ANIME_SOURCES,'true');
});

test('saved keys reveal test button for validating credentials without re-entering them',async()=>{
  const env=form({configuredKeys:['PROVIDER_KEY']});
  await vm.runInContext('loadSettings()',env.context);
  assert.equal(env.nodes.get('PROVIDER_KEY-saved').textContent,'SAVED');
  assert.equal(env.nodes.get('PROVIDER_KEY-test').hidden,false);
  assert.equal(env.nodes.get('PROVIDER_KEY-remove').hidden,false);
});

test('local access scope configures direct host and port endpoints',async()=>{
  const env=form({BASE_URL:'',ports:{aiostreams:3001,aiometadata:4005},configuredKeys:[]});
  const fnScope = source.match(/function setAccessScope\([^\)]*\) \{[\s\S]*?\n\}/)[0];
  vm.runInContext(fnScope, env.context);
  vm.runInContext("setAccessScope('local')", env.context);
  assert.equal(env.nodes.get('base-url').value, 'http://server:3001');
  assert.equal(env.nodes.get('aiometadata-host').value, 'http://server:4005');
});

test('playback test executes multi-step verification and posts to /api/test-playback',async()=>{
  const env=form({});
  const fnPlayback = source.match(/async function runPlaybackTest\(\) \{[\s\S]*?\n\}/)[0];
  env.context.notify = () => {};
  vm.runInContext(fnPlayback, env.context);
  await vm.runInContext("runPlaybackTest()", env.context);
  const call = env.calls.find(c => c.path === '/api/test-playback');
  assert.ok(call, 'Expected /api/test-playback API call');
  assert.equal(call.payload.mode, 'debrid');
  assert.equal(env.nodes.get('playback-test-card').style.display, 'block');
});

test('playback test reveals inline video player preview when stream_url is returned',async()=>{
  const env=form({});
  env.context.api = async (path) => {
    if (path === '/api/test-playback') {
      return { success: true, status: 'ok', stream_url: 'http://server:3000/media/sample.mp4', steps_dict: {
        auth: { status: 'pass', detail: 'Auth ok' },
        stream_resolution: { status: 'pass', detail: 'Found stream' },
        media_read: { status: 'pass', detail: 'Read 1MB' }
      }};
    }
    return { success: true };
  };
  const fnPlayback = source.match(/async function runPlaybackTest\(\) \{[\s\S]*?\n\}/)[0];
  env.context.notify = () => {};
  vm.runInContext(fnPlayback, env.context);
  await vm.runInContext("runPlaybackTest()", env.context);
  assert.equal(env.nodes.get('playback-video-container').style.display, 'block');
  assert.equal(env.nodes.get('playback-video-preview').src, 'http://server:3000/media/sample.mp4');
  assert.equal(env.nodes.get('playback-direct-stream-link').href, 'http://server:3000/media/sample.mp4');
});

test('remote access scope updates helper text for reverse proxy / tunnel setup',async()=>{
  const env=form({BASE_URL:'https://my-aio.domain.com',configuredKeys:[]});
  const fnScope = source.match(/function setAccessScope\([^\)]*\) \{[\s\S]*?\n\}/)[0];
  vm.runInContext(fnScope, env.context);
  vm.runInContext("setAccessScope('remote')", env.context);
  assert.match(env.nodes.get('base-url-help').textContent, /reverse proxy/);
  assert.match(env.nodes.get('aiometa-url-help').textContent, /subdomain/);
});

function readinessUI() {
  const env = form({});
  const readinessCode = source.slice(source.indexOf('let playbackReadiness ='), source.indexOf('async function runPlaybackTest()'));
  vm.runInContext('let manifestLoaded = true; let currentManifest = null;\n' + readinessCode, env.context);
  return env;
}

test('the main status presents one clear next step and gates playback', async () => {
  const env = readinessUI();
  vm.runInContext('renderPlaybackReadiness()', env.context);
  assert.equal(env.nodes.get('btn-test-playback').disabled, true);
  assert.equal(env.nodes.get('startup-title').textContent, 'Finish setup');
  vm.runInContext('currentManifest = "https://test.invalid/manifest.json"', env.context);
  env.context.api = async () => ({ready:true, message:'Ready to test', checks:[]});
  await vm.runInContext('refreshPlaybackReadiness()', env.context);
  assert.equal(env.nodes.get('btn-test-playback').disabled, false);
  vm.runInContext('setupFormDirty = true; renderPlaybackReadiness()', env.context);
  assert.equal(env.nodes.get('ready-actions').hidden, true);
  assert.equal(env.nodes.get('startup-title').textContent, 'Apply your changes');
  vm.runInContext('setupFormDirty = false; lastJobStatus = "running"; renderPlaybackReadiness()', env.context);
  assert.equal(env.nodes.get('btn-test-playback').disabled, true);
  assert.equal(env.nodes.get('startup-title').textContent, 'Starting services');
  vm.runInContext('lastJobStatus = "failed"; renderPlaybackReadiness()', env.context);
  assert.equal(env.nodes.get('startup-title').textContent, 'Setup needs attention');
  vm.runInContext('lastJobStatus = "complete"', env.context);
  env.context.api = async () => {throw Error('offline');};
  await vm.runInContext('refreshPlaybackReadiness()', env.context);
  assert.equal(env.nodes.get('btn-test-playback').disabled, true);
  assert.match(env.nodes.get('startup-message').textContent, /Connection lost/);
});

test('early playback invocation cannot make a playback request', async () => {
  const env = readinessUI();
  const calls = [];
  env.context.api = async path => {calls.push(path); return {ready:false, message:'Starting', checks:[]};};
  vm.runInContext(source.match(/async function runPlaybackTest\(\) \{[\s\S]*?\n\}/)[0], env.context);
  await vm.runInContext('runPlaybackTest()', env.context);
  assert.deepEqual(calls, ['/api/playback-readiness']);
  assert.equal(env.nodes.get('btn-test-playback').disabled, true);
});

test('showContainerLogs opens the viewer for the requested service', async () => {
  const env = form({});
  const calls = [];
  env.context.api = async path => { calls.push(path); return { container: 'prowlarr', logs: 'Sample Prowlarr Log' }; };
  const showLogsCode = source.slice(source.indexOf('async function showContainerLogs('), source.indexOf('async function refreshServices()'));
  vm.runInContext(showLogsCode, env.context);
  const dialog = env.document.getElementById('service-log-dialog');
  dialog.showModal = () => { dialog.open = true; };
  const sel = env.document.getElementById('logs-container-select');
  sel.options = [{ value: 'aiostreams' }, { value: 'prowlarr' }];
  await vm.runInContext("showContainerLogs('prowlarr')", env.context);
  assert.equal(dialog.open, true);
  assert.equal(env.document.getElementById('advanced-tools').open, undefined);
  assert.equal(sel.value, 'prowlarr');
  assert.deepEqual(calls, ['/api/logs?container=prowlarr']);
  assert.equal(env.document.getElementById('container-logs-output').textContent, 'Sample Prowlarr Log');
});

test('aiometadata template selector updates description and links on change', async () => {
  const env = form({});
  const updateCode = source.slice(source.indexOf('function updateTemplateDisplay('), source.indexOf('function setFormDirty('));
  vm.runInContext(updateCode, env.context);

  const sel = env.document.getElementById('aiometadata-template');
  const desc = env.document.getElementById('template-description');
  const dl = env.document.getElementById('download-template-json');

  sel.value = 'grabberhawk-aiometadata-config.json';
  vm.runInContext('updateTemplateDisplay()', env.context);
  assert.match(desc.textContent, /Grabberhawk/i);
  assert.equal(dl.download, 'grabberhawk-aiometadata-config.json');

  sel.value = 'tamtaro-aiometadata-without-anime.json';
  vm.runInContext('updateTemplateDisplay()', env.context);
  assert.match(desc.textContent, /without anime/i);
  assert.equal(dl.download, 'tamtaro-aiometadata-without-anime.json');

  sel.value = 'tamtaro-aiometadata-with-anime.json';
  vm.runInContext('updateTemplateDisplay()', env.context);
  assert.match(desc.textContent, /20\+ Anime catalogs/i);
  assert.equal(dl.download, 'tamtaro-aiometadata-with-anime.json');
});

test('bidirectional sync between base-url and proxy-url updates preview and paired field', async () => {
  const env = form({});
  const syncCode = source.slice(source.indexOf('async function generateProxySnippet('), source.indexOf('let playbackReadiness = null'));
  vm.runInContext(syncCode, env.context);

  const baseInput = env.document.getElementById('base-url');
  const proxyInput = env.document.getElementById('proxy-url');
  const preview = env.document.getElementById('guide-player-preview');

  // 1. Updating base-url triggers syncBaseToProxy
  baseInput.value = 'https://stream.example.com';
  baseInput.handlers.input();
  assert.equal(proxyInput.value, 'https://stream.example.com');
  assert.equal(preview.textContent, 'https://stream.example.com');

  // 2. Updating proxy-url triggers syncProxyToBase
  proxyInput.value = 'https://custom-proxy.example.com';
  proxyInput.handlers.input();
  assert.equal(baseInput.value, 'https://custom-proxy.example.com');
  assert.equal(preview.textContent, 'https://custom-proxy.example.com');
});

test('remote access scope reveals guide and triggers automatic proxy snippet generation', async () => {
  const env = form({ BASE_URL: 'https://proxy.example.com', configuredKeys: [] });
  let fetchedUrl = null;
  env.context.fetch = async (url) => {
    fetchedUrl = url;
    return { ok: true, text: async () => 'sample proxy config' };
  };
  const fnScope = source.match(/function setAccessScope\([^\)]*\) \{[\s\S]*?\n\}/)[0];
  const fnGen = source.match(/async function generateProxySnippet\(\) \{[\s\S]*?\n\}/)[0];
  vm.runInContext(fnGen + '\n' + fnScope, env.context);

  const guide = env.document.getElementById('remote-access-guide');
  const baseInput = env.document.getElementById('base-url');
  baseInput.value = 'https://proxy.example.com';

  vm.runInContext("setAccessScope('remote')", env.context);
  assert.equal(guide.style.display, 'block');
  assert.equal(guide.hidden, false);
  assert.ok(fetchedUrl, 'Expected fetch to be called for snippet generation');
  assert.match(fetchedUrl, /\/api\/proxy-config\?format=.*base_url=https%3A%2F%2Fproxy\.example\.com/);
});

test('proxy format change auto-regenerates snippet and displays output', async () => {
  const env = form({});
  let fetchedFormat = null;
  env.context.fetch = async (url) => {
    const u = new URL(url, 'http://localhost');
    fetchedFormat = u.searchParams.get('format');
    return { ok: true, text: async () => `config for ${fetchedFormat}` };
  };
  const fnGen = source.match(/async function generateProxySnippet\(\) \{[\s\S]*?\n\}/)[0];
  vm.runInContext(fnGen, env.context);

  const formatEl = env.document.getElementById('proxy-format');
  const outputEl = env.document.getElementById('proxy-output');
  formatEl.value = 'traefik';

  await vm.runInContext('generateProxySnippet()', env.context);
  assert.equal(fetchedFormat, 'traefik');
  assert.equal(outputEl.textContent, 'config for traefik');
});

test('copy button for guide player url confirms successful clipboard write', async () => {
  const env = form({});
  let copiedText = null;
  env.context.navigator = {
    clipboard: {
      writeText: async (text) => { copiedText = text; }
    }
  };
  env.context.notify = (msg) => { env.context.lastNotification = msg; };

  const copyFn = source.slice(source.indexOf('async function copyToClipboard('), source.indexOf('document.getElementById(\'btn-test-playback\')'));
  const syncCode = source.slice(source.indexOf('async function generateProxySnippet('), source.indexOf('let playbackReadiness = null'));
  vm.runInContext(copyFn + '\n' + syncCode, env.context);

  const guidePreview = env.document.getElementById('guide-player-preview');
  guidePreview.textContent = 'https://watch.customdomain.com';
  const copyGuideBtn = env.document.getElementById('btn-copy-guide-player-url');

  copyGuideBtn.handlers.click({ currentTarget: copyGuideBtn });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(copyGuideBtn.textContent, 'Copied! ✓');
  assert.equal(copiedText, 'https://watch.customdomain.com');
  assert.equal(env.context.lastNotification, 'Remote Web Player URL copied!');
});

test('test-saved-nzb-btn calls /api/test-provider with nzb provider and notifies result', async () => {
  const env = form({});
  let notifyMessage = null;
  let notifyError = null;
  env.context.notify = (msg, isErr) => {
    notifyMessage = msg;
    notifyError = isErr;
  };
  const nzbBtnSlice = source.slice(
    source.indexOf("document.getElementById('test-saved-nzb-btn')"),
    source.indexOf("const setupFormEl = document.getElementById('setup-form')")
  );
  vm.runInContext(nzbBtnSlice, env.context);

  const nzbBtn = env.document.getElementById('test-saved-nzb-btn');
  assert.ok(nzbBtn.handlers.click, 'Expected click handler on test-saved-nzb-btn');

  env.context.api = async (path, opts) => {
    assert.equal(path, '/api/test-provider');
    const body = JSON.parse(opts.body);
    assert.equal(body.provider, 'nzb');
    return { status: 'valid', detail: 'NZB indexer (api.althub.co.za) verified successfully.' };
  };

  await nzbBtn.handlers.click({ currentTarget: nzbBtn });
  assert.match(notifyMessage, /✓ NZB indexer valid: NZB indexer/);
  assert.equal(notifyError, false);
});

test('detectIndexerName auto-detects known indexers and falls back to domain or generic', () => {
  const detectSlice = source.slice(
    source.indexOf('function detectIndexerName('),
    source.indexOf('function addUsenetSource(')
  );
  const context = vm.createContext({ URL });
  vm.runInContext(detectSlice, context);

  assert.equal(context.detectIndexerName('https://drunkenslug.com'), 'DrunkenSlug');
  assert.equal(context.detectIndexerName('https://api.althub.co.za'), 'altHUB');
  assert.equal(context.detectIndexerName('https://animetosho.org'), 'AnimeTosho');
  assert.equal(context.detectIndexerName('https://api.nzbgeek.info'), 'NZBGeek');
  assert.equal(context.detectIndexerName('https://nzbplanet.net'), 'NZBPlanet');
  assert.equal(context.detectIndexerName('https://nzbfinder.ws'), 'NZBFinder');
  assert.equal(context.detectIndexerName('https://ninja-central.com'), 'NinjaCentral');
  assert.equal(context.detectIndexerName('https://custom-index.org'), 'Custom-index');
  assert.equal(context.detectIndexerName(''), 'NZB Indexer');
});

test('individual NZB indexer test button passes url, key, and id, providing visual feedback', async () => {
  const nzbLogic = source.slice(
    source.indexOf('const extraUsenetSources = ['),
    source.indexOf('async function loadSettings(options) {')
  );

  let capturedApiCall = null;
  let notifiedMsg = null;
  let notifiedErr = null;

  const mockUrlInput = { value: 'https://drunkenslug.com', placeholder: '', dataset: { sourceField: 'url' }, addEventListener(t, h) { this['on' + t] = h; } };
  const mockKeyInput = { value: '', placeholder: 'Saved · enter to replace', dataset: { sourceField: 'apiKey' }, required: false, addEventListener(t, h) { this['on' + t] = h; } };
  const mockNameEl = { textContent: '' };
  const mockStatusBadge = { textContent: '', style: {} };
  const mockFeedbackEl = { textContent: '', style: {} };
  const mockTestBtn = { disabled: false, textContent: 'Test indexer', handlers: {}, addEventListener(t, h) { this.handlers[t] = h; } };
  const mockRemoveBtn = { handlers: {}, addEventListener(t, h) { this.handlers[t] = h; } };

  const mockRow = {
    dataset: { sourceId: 'slug-1' },
    querySelector(sel) {
      if (sel === '[data-source-field="url"]') return mockUrlInput;
      if (sel === '[data-source-field="apiKey"]') return mockKeyInput;
      if (sel === '[data-indexer-name]') return mockNameEl;
      if (sel === '[data-indexer-status]') return mockStatusBadge;
      if (sel === '[data-indexer-feedback]') return mockFeedbackEl;
      if (sel === '[data-test-indexer]') return mockTestBtn;
      if (sel === '[data-remove-source]') return mockRemoveBtn;
      return null;
    },
    querySelectorAll(sel) {
      if (sel.includes('[data-indexer-name]')) return [mockNameEl];
      if (sel === '[data-source-field]') return [mockUrlInput, mockKeyInput];
      return [];
    }
  };

  const list = { children: [], append(r) { this.children.push(r); }, replaceChildren() { this.children = []; } };
  const template = { content: { firstElementChild: { cloneNode: () => mockRow } } };

  const dom = {
    'extra-nzb-indexers': list,
    'add-nzb-indexer': { disabled: false, addEventListener() {} },
    'nzb-indexer-row': template,
    'nzb-indexer-url': { value: '' },
    'NZB_INDEXER_API_KEY': { value: '' }
  };

  const context = vm.createContext({
    URL,
    document: { getElementById: (id) => dom[id] || null },
    notify: (msg, isErr) => { notifiedMsg = msg; notifiedErr = isErr; },
    api: async (path, opts) => {
      capturedApiCall = { path, body: JSON.parse(opts.body) };
      return { status: 'valid', detail: 'NZB indexer (drunkenslug.com) verified successfully.' };
    },
    setFormDirty: () => {},
    savedKeys: new Set(['NZB_INDEXER_API_KEY'])
  });

  vm.runInContext(nzbLogic, context);

  // Add the row as saved secret
  const extraSources = vm.runInContext('extraUsenetSources', context);
  const row = context.addUsenetSource(extraSources.find(s => s.key === 'USENET_EXTRA_INDEXERS'), {
    id: 'slug-1',
    url: 'https://drunkenslug.com',
    secretSaved: true
  });

  assert.equal(mockNameEl.textContent, 'DrunkenSlug');
  assert.ok(mockTestBtn.handlers.click, 'Expected click handler on Test indexer button');

  // Trigger test click
  await mockTestBtn.handlers.click({ preventDefault() {} });

  assert.equal(capturedApiCall.path, '/api/test-provider');
  assert.equal(capturedApiCall.body.provider, 'nzb');
  assert.equal(capturedApiCall.body.url, 'https://drunkenslug.com');
  assert.equal(capturedApiCall.body.key, 'saved');
  assert.equal(capturedApiCall.body.id, 'slug-1');

  assert.equal(mockStatusBadge.textContent, 'VALID');
  assert.match(mockFeedbackEl.textContent, /drunkenslug\.com/);
  assert.match(notifiedMsg, /✓ DrunkenSlug valid: NZB indexer/);
  assert.equal(notifiedErr, false);
});

test('loadExtraUsenetSources and readExtraUsenetSources unify NZB indexers and preserve backward compatibility', () => {
  const nzbLogic = source.slice(
    source.indexOf('const extraUsenetSources = ['),
    source.indexOf('async function loadSettings(options) {')
  );

  const list = { children: [], append(r) { this.children.push(r); }, replaceChildren() { this.children = []; } };

  function makeMockRow(data = {}) {
    const urlInput = { value: data.url || '', dataset: { sourceField: 'url' }, placeholder: '', addEventListener() {} };
    const keyInput = { value: data.apiKey || '', dataset: { sourceField: 'apiKey' }, placeholder: '', required: false, addEventListener() {} };
    const nameEl = { textContent: '' };
    const badge = { textContent: '', style: {} };
    const feedback = { textContent: '', style: {} };
    const testBtn = { handlers: {}, addEventListener() {} };
    const removeBtn = { handlers: {}, addEventListener() {} };
    return {
      dataset: { ...(data.id ? { sourceId: data.id } : {}) },
      querySelector(sel) {
        if (sel === '[data-source-field="url"]') return urlInput;
        if (sel === '[data-source-field="apiKey"]') return keyInput;
        if (sel === '[data-indexer-name]') return nameEl;
        if (sel === '[data-indexer-status]') return badge;
        if (sel === '[data-indexer-feedback]') return feedback;
        if (sel === '[data-test-indexer]') return testBtn;
        if (sel === '[data-remove-source]') return removeBtn;
        return null;
      },
      querySelectorAll(sel) {
        if (sel.includes('[data-indexer-name]')) return [nameEl];
        if (sel === '[data-source-field]') return [urlInput, keyInput];
        return [];
      }
    };
  }

  const template = {
    content: {
      firstElementChild: {
        cloneNode: () => makeMockRow()
      }
    }
  };

  const hiddenUrl = { value: '' };
  const hiddenKey = { value: '' };
  const dom = {
    'extra-nzb-indexers': list,
    'add-nzb-indexer': { disabled: false, addEventListener() {} },
    'nzb-indexer-row': template,
    'nzb-indexer-url': hiddenUrl,
    'NZB_INDEXER_API_KEY': hiddenKey
  };

  const savedKeys = new Set(['NZB_INDEXER_API_KEY']);
  const context = vm.createContext({
    URL,
    document: { getElementById: (id) => dom[id] || null },
    notify: () => {},
    api: async () => ({ status: 'valid' }),
    setFormDirty: () => {},
    savedKeys
  });

  vm.runInContext(nzbLogic, context);

  // 1. Loading with NZB_INDEXER_URL and extra indexers
  context.loadExtraUsenetSources({
    NZB_INDEXER_URL: 'https://drunkenslug.com',
    configuredKeys: ['NZB_INDEXER_API_KEY'],
    USENET_EXTRA_INDEXERS: [
      { id: 'alt-id', url: 'https://api.althub.co.za', secretSaved: true }
    ]
  });

  assert.equal(list.children.length, 2);
  assert.equal(list.children[0].querySelector('[data-source-field="url"]').value, 'https://drunkenslug.com');
  assert.equal(list.children[0].querySelector('[data-indexer-name]').textContent, 'DrunkenSlug');
  assert.equal(list.children[1].querySelector('[data-source-field="url"]').value, 'https://api.althub.co.za');
  assert.equal(list.children[1].querySelector('[data-indexer-name]').textContent, 'altHUB');

  // 2. Saving unified indexers: row 0 -> NZB_INDEXER_URL, rows 1..N -> USENET_EXTRA_INDEXERS
  const payload = {};
  context.readExtraUsenetSources(payload);

  assert.equal(payload.NZB_INDEXER_URL, 'https://drunkenslug.com');
  assert.equal(hiddenUrl.value, 'https://drunkenslug.com');
  assert.equal('NZB_INDEXER_API_KEY' in payload, false, 'Saved key without replacement should be preserved');
  assert.equal(payload.USENET_EXTRA_INDEXERS.length, 1);
  assert.equal(payload.USENET_EXTRA_INDEXERS[0].id, 'alt-id');
  assert.equal(payload.USENET_EXTRA_INDEXERS[0].url, 'https://api.althub.co.za');

  // 3. Saving when all indexers removed
  list.children = [];
  const emptyPayload = {};
  context.readExtraUsenetSources(emptyPayload);
  assert.equal(emptyPayload.NZB_INDEXER_URL, '');
  assert.equal(emptyPayload.NZB_INDEXER_API_KEY, '');
  assert.equal(emptyPayload.USENET_EXTRA_INDEXERS.length, 0);
  assert.equal(savedKeys.has('NZB_INDEXER_API_KEY'), false);
});

test('extra NNTP form serialization preserves exact credentials while trimming server fields', () => {
  const logic = source.slice(source.indexOf('const extraUsenetSources = ['), source.indexOf('async function loadSettings(options) {'));
  const inputs = [
    {dataset:{sourceField:'username'},value:' user name '},
    {dataset:{sourceField:'password'},value:' secret $ value '},
    {dataset:{sourceField:'host'},value:' news.example.org '},
    {dataset:{sourceField:'port'},value:' 563 '},
    {dataset:{sourceField:'tls'},type:'checkbox',checked:true}
  ];
  const row = {dataset:{sourceId:'saved-server'},querySelectorAll:()=>inputs};
  const context = vm.createContext({URL,document:{getElementById:id=>id === 'extra-usenet-servers' ? {children:[row]} : null}});
  vm.runInContext(logic,context);
  const payload = {};
  context.readExtraUsenetSources(payload);
  const server = payload.USENET_EXTRA_SERVERS[0];
  assert.equal(server.id,'saved-server');
  assert.equal(server.username,' user name ');
  assert.equal(server.password,' secret $ value ');
  assert.equal(server.host,'news.example.org');
  assert.equal(server.port,'563');
  assert.equal(server.tls,true);
  inputs[1].value = '';
  const edit = {};
  context.readExtraUsenetSources(edit);
  assert.equal('password' in edit.USENET_EXTRA_SERVERS[0],false,'blank edit preserves saved password');
});

test('setup-form and loadSettings preserve saved Cloudflare credentials and submit newly entered tokens', async () => {
  const env = form({
    USENET_ENABLED: 'false',
    configuredKeys: ['PROVIDER_KEY'],
    CLOUDFLARE_ZONE_ID: 'zone-123',
    CLOUDFLARE_API_TOKEN_SAVED: true,
    CLOUDFLARE_TUNNEL_TOKEN_SAVED: true,
    CLOUDFLARE_TUNNEL_METADATA: {
      valid: true,
      tunnel_id: '84144369-15de-4d76-a2a5-48faea71a4f0',
      cname_target: '84144369-15de-4d76-a2a5-48faea71a4f0.cfargotunnel.com'
    }
  });

  await vm.runInContext('loadSettings()', env.context);
  assert.equal(env.nodes.get('cf-zone-id').value, 'zone-123');
  assert.equal(env.nodes.get('cf-api-token').placeholder, 'Saved · enter to replace');
  assert.equal(env.nodes.get('cf-tunnel-token').placeholder, 'Saved · enter to replace');
  assert.equal(env.nodes.get('cf-token-meta-preview').style.display, 'block');
  assert.match(env.nodes.get('cf-token-meta-text').textContent, /84144369-15de-4d76-a2a5-48faea71a4f0/);
  assert.equal(env.nodes.get('cf-cname-guide-card').style.display, 'block');
  assert.equal(env.nodes.get('cf-cname-target').textContent, '84144369-15de-4d76-a2a5-48faea71a4f0.cfargotunnel.com');

  // Submit without modifying tokens: saved tokens must not be wiped
  await env.nodes.get('setup-form').handlers.submit({ preventDefault() {} });
  const save1 = env.calls.find(c => c.path === '/api/save-env').payload;
  assert.equal(save1.CLOUDFLARE_ZONE_ID, 'zone-123');
  assert.equal('CLOUDFLARE_TUNNEL_TOKEN' in save1, false, 'Saved tunnel token should not be wiped');
  assert.equal('CLOUDFLARE_API_TOKEN' in save1, false, 'Saved API token should not be wiped');

  // Submit with newly typed tokens: should sanitize tunnel token and include both
  env.calls.length = 0;
  env.nodes.get('cf-tunnel-token').value = 'cloudflared.exe service install --token eyJhIjoiYWJjIn0=';
  env.nodes.get('cf-api-token').value = 'cf-api-token-new';
  await env.nodes.get('setup-form').handlers.submit({ preventDefault() {} });
  const save2 = env.calls.find(c => c.path === '/api/save-env').payload;
  assert.equal(save2.CLOUDFLARE_TUNNEL_TOKEN, 'eyJhIjoiYWJjIn0=');
  assert.equal(save2.CLOUDFLARE_API_TOKEN, 'cf-api-token-new');
});

test('btn-save-cf-token notifies when token is already saved or prompts when empty', async () => {
  let lastNotification = '';
  const env = form({
    USENET_ENABLED: 'false',
    configuredKeys: ['PROVIDER_KEY'],
    CLOUDFLARE_TUNNEL_TOKEN_SAVED: true
  });
  env.context.notify = (msg) => { lastNotification = msg; };
  const cfBlock = source.slice(source.indexOf('// Cloudflare Tunnel & Automated DNS Management'), source.lastIndexOf("document.querySelectorAll('.streaming-mode-section"));
  vm.runInContext(cfBlock, env.context);

  await vm.runInContext('loadSettings()', env.context);

  // 1. Empty input when already saved
  env.nodes.get('cf-tunnel-token').value = '';
  await env.nodes.get('btn-save-cf-token').handlers.click();
  assert.match(lastNotification, /already saved in configuration/);

  // 2. Empty input when not saved
  env.context.cachedEnv.CLOUDFLARE_TUNNEL_TOKEN_SAVED = false;
  env.nodes.get('cf-tunnel-token').placeholder = '';
  await env.nodes.get('btn-save-cf-token').handlers.click();
  assert.match(lastNotification, /Enter a Cloudflare Tunnel Token/);

  // 3. New token entered -> saves sanitized token
  env.calls.length = 0;
  env.nodes.get('cf-tunnel-token').value = '--token eyJhIjoiOTk5In0=';
  await env.nodes.get('btn-save-cf-token').handlers.click();
  const saveCall = env.calls.find(c => c.path === '/api/save-env');
  assert.equal(saveCall.payload.CLOUDFLARE_TUNNEL_TOKEN, 'eyJhIjoiOTk5In0=');
  assert.equal(env.nodes.get('cf-tunnel-token').placeholder, 'Saved · enter to replace');
});

test('btn-start-cf-tunnel saves new token or proceeds directly when token is already saved', async () => {
  let lastNotification = '';
  const env = form({
    USENET_ENABLED: 'false',
    configuredKeys: ['PROVIDER_KEY'],
    CLOUDFLARE_TUNNEL_TOKEN_SAVED: true
  });
  env.context.notify = (msg) => { lastNotification = msg; };
  const cfBlock = source.slice(source.indexOf('// Cloudflare Tunnel & Automated DNS Management'), source.lastIndexOf("document.querySelectorAll('.streaming-mode-section"));
  vm.runInContext(cfBlock, env.context);

  await vm.runInContext('loadSettings()', env.context);

  // 1. Token already saved and input empty: starts tunnel container directly
  env.calls.length = 0;
  env.nodes.get('cf-tunnel-token').value = '';
  await env.nodes.get('btn-start-cf-tunnel').handlers.click({ currentTarget: env.nodes.get('btn-start-cf-tunnel') });
  assert.equal(env.calls.some(c => c.path === '/api/cloudflare/tunnel' && c.payload.action === 'start'), true);
  assert.equal(env.calls.some(c => c.path === '/api/save-env'), false);

  // 2. New token typed in input: saves first, then starts tunnel container
  env.calls.length = 0;
  env.nodes.get('cf-tunnel-token').value = 'eyJ0IjoiMTIzIn0=';
  await env.nodes.get('btn-start-cf-tunnel').handlers.click({ currentTarget: env.nodes.get('btn-start-cf-tunnel') });
  assert.equal(env.calls[0].path, '/api/save-env');
  assert.equal(env.calls[0].payload.CLOUDFLARE_TUNNEL_TOKEN, 'eyJ0IjoiMTIzIn0=');
  assert.equal(env.calls.some(c => c.path === '/api/cloudflare/tunnel' && c.payload.action === 'start'), true);

  // 3. Not saved and input empty: prompts user to enter token
  env.calls.length = 0;
  env.context.cachedEnv.CLOUDFLARE_TUNNEL_TOKEN_SAVED = false;
  env.nodes.get('cf-tunnel-token').placeholder = '';
  env.nodes.get('cf-tunnel-token').value = '';
  await env.nodes.get('btn-start-cf-tunnel').handlers.click({ currentTarget: env.nodes.get('btn-start-cf-tunnel') });
  assert.match(lastNotification, /enter your Cloudflare Tunnel Token/i);
  assert.equal(env.calls.length, 0);
});

test('btn-push-cf-dns rejects private/local IP hostnames and resolves cname_target from metadata', async () => {
  let lastNotification = '';
  const env = form({
    USENET_ENABLED: 'false',
    configuredKeys: ['PROVIDER_KEY'],
    CLOUDFLARE_ZONE_ID: 'zone-xyz',
    CLOUDFLARE_TUNNEL_METADATA: {
      valid: true,
      tunnel_id: 'auto-tunnel-id',
      cname_target: 'auto-tunnel-id.cfargotunnel.com'
    }
  });
  env.context.notify = (msg) => { lastNotification = msg; };
  const cfBlock = source.slice(source.indexOf('// Cloudflare Tunnel & Automated DNS Management'), source.lastIndexOf("document.querySelectorAll('.streaming-mode-section"));
  vm.runInContext(cfBlock, env.context);

  await vm.runInContext('loadSettings()', env.context);

  // 1. Private/local IP rejection
  env.nodes.get('base-url').value = 'http://192.168.1.100:3001';
  env.nodes.get('cf-api-token').value = 'api-token-valid';
  await env.nodes.get('btn-push-cf-dns').handlers.click({ currentTarget: env.nodes.get('btn-push-cf-dns') });
  assert.match(lastNotification, /Cloudflare DNS requires a public domain name/);
  assert.equal(env.calls.length, 0);

  // 2. Localhost rejection
  lastNotification = '';
  env.nodes.get('base-url').value = 'http://localhost:8088';
  await env.nodes.get('btn-push-cf-dns').handlers.click({ currentTarget: env.nodes.get('btn-push-cf-dns') });
  assert.match(lastNotification, /Cloudflare DNS requires a public domain name/);
  assert.equal(env.calls.length, 0);

  // 3. Public domain with empty tunnel token input resolves cname_target from metadata
  env.calls.length = 0;
  env.nodes.get('base-url').value = 'https://watch.customdomain.org';
  env.nodes.get('cf-tunnel-token').value = '';
  await env.nodes.get('btn-push-cf-dns').handlers.click({ currentTarget: env.nodes.get('btn-push-cf-dns') });
  const pushCall = env.calls.find(c => c.path === '/api/cloudflare/push-dns');
  assert.ok(pushCall);
  assert.equal(pushCall.payload.hostname, 'watch.customdomain.org');
  assert.equal(pushCall.payload.cname_target, 'auto-tunnel-id.cfargotunnel.com');
  assert.equal(pushCall.payload.zone_id, 'zone-xyz');
});





test('Cloudflare preview escapes raw, encoded and saved tunnel metadata',()=>{
  const malicious='<img src=x onerror=alert(1)>';
  const nodes=new Map();
  const document={getElementById(id){
    if(!nodes.has(id)) nodes.set(id,{value:'',style:{},textContent:'',innerHTML:''});
    return nodes.get(id);
  }};
  const context=vm.createContext({document,URL,Buffer,cachedCloudflareStatus:null});
  vm.runInContext(source.match(/function escapeHtml\(str\) \{[\s\S]*?\n\}/)[0],context);
  vm.runInContext(source.slice(source.indexOf('function parseClientTunnelToken('),source.indexOf('async function refreshCloudflareStatus(')),context);
  for(const value of [JSON.stringify({t:malicious}),Buffer.from(JSON.stringify({t:malicious})).toString('base64')]){
    document.getElementById('cf-tunnel-token').value=value;
    vm.runInContext('updateClientTokenPreview()',context);
    const html=nodes.get('cf-token-meta-text').innerHTML;
    assert.ok(!html.includes('<img'));
    assert.ok(html.includes('&lt;img'));
  }
  document.getElementById('cf-tunnel-token').value='';
  context.cachedCloudflareStatus={tunnel_metadata:{valid:true,tunnel_id:malicious,cname_target:malicious}};
  vm.runInContext('updateClientTokenPreview()',context);
  assert.ok(!nodes.get('cf-token-meta-text').innerHTML.includes('<img'));
  assert.equal(nodes.get('cf-cname-target').textContent,malicious);
});
