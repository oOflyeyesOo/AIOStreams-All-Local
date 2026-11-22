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
  vm.runInContext(load+'\n'+submit,context);
  return {context,nodes,calls,document};
}

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

test('copy buttons for guide player url and proxy config trigger instant feedback', async () => {
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
  assert.equal(copyGuideBtn.textContent, 'Copied! ✓');
  await new Promise(resolve => setImmediate(resolve));
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


