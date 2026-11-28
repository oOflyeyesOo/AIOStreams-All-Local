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
  const validation=source.slice(source.indexOf('const SUPPORTED_VALIDATION_PROVIDERS ='),source.indexOf('function renderFields('));
  const load=source.match(/async function loadSettings\(options\) \{[\s\S]*?\n\}/)[0];
  const submit=source.slice(source.indexOf("document.getElementById('setup-form').addEventListener('submit'"),source.indexOf("document.getElementById('refresh-services').addEventListener"));
  vm.runInContext(source.match(/function escapeHtml\(str\) \{[\s\S]*?\n\}/)[0],context);
  const state=source.slice(source.indexOf('let settingsEditRevision ='),source.indexOf('async function loadSettings('));
  const dirty=source.match(/function setFormDirty\(dirty\) \{[\s\S]*?\n\}/)[0];
  vm.runInContext(validation+'\n'+state+'\n'+dirty+'\n'+load+'\n'+submit,context);
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
  const env=form({configuredKeys:['REALDEBRID_API_KEY']});
  env.context.fields.push(['REALDEBRID_API_KEY']);
  await vm.runInContext('loadSettings()',env.context);
  assert.equal(env.nodes.get('REALDEBRID_API_KEY-saved').textContent,'SAVED');
  assert.equal(env.nodes.get('REALDEBRID_API_KEY-test').hidden,false);
  assert.equal(env.nodes.get('REALDEBRID_API_KEY-remove').hidden,false);
});

test('unsupported saved keys like OPENSUBTITLES_API_KEY keep -test hidden while supported provider keys reveal it',async()=>{
  const supportedKeys=[
    'TMDB_API_KEY',
    'REALDEBRID_API_KEY',
    'PREMIUMIZE_API_KEY',
    'TORBOX_API_KEY',
    'ALLDEBRID_API_KEY',
    'DEBRIDLINK_API_KEY',
    'EASYDEBRID_API_KEY',
    'NZB_INDEXER_API_KEY'
  ];
  const env=form({configuredKeys:[...supportedKeys,'OPENSUBTITLES_API_KEY']});
  for(const key of [...supportedKeys,'OPENSUBTITLES_API_KEY']){
    if(!env.context.fields.some(([existing])=>existing===key))env.context.fields.push([key]);
  }
  await vm.runInContext('loadSettings()',env.context);
  assert.equal(env.nodes.get('OPENSUBTITLES_API_KEY-saved').textContent,'SAVED');
  assert.equal(env.nodes.get('OPENSUBTITLES_API_KEY-remove').hidden,false);
  assert.equal(env.nodes.get('OPENSUBTITLES_API_KEY-test').hidden,true);
  for(const key of supportedKeys){
    assert.equal(env.nodes.get(`${key}-test`).hidden,false,`${key}-test should be visible when saved`);
  }

  const createdIds=[];
  const makeNode=(tag)=>({
    tagName:tag,
    children:[],
    style:{},
    setAttribute(){},
    addEventListener(){},
    append(...kids){
      for(const kid of kids){
        if(kid&&typeof kid==='object'){
          this.children.push(kid);
          if(kid.id)createdIds.push(kid.id);
        }
      }
    }
  });
  const target=makeNode('div');
  const renderCtx=vm.createContext({
    document:{
      getElementById:id=>(id==='test-fields'?target:null),
      createElement:tag=>makeNode(tag),
      createTextNode:text=>({text})
    },
    savedKeys:new Set(),
    api:async()=>({}),
    notify:()=>{},
    setFormDirty:()=>{}
  });
  const validation=source.slice(source.indexOf('const SUPPORTED_VALIDATION_PROVIDERS ='),source.indexOf('function renderFields('));
  const renderFn=source.slice(source.indexOf('function renderFields('),source.indexOf("renderFields('provider-fields'"));
  vm.runInContext(validation+'\n'+renderFn,renderCtx);
  renderCtx.renderFields('test-fields',[['REALDEBRID_API_KEY','Real-Debrid','R'],['OPENSUBTITLES_API_KEY','OpenSubtitles subtitles','OS']]);
  assert.equal(createdIds.includes('REALDEBRID_API_KEY-test'),true);
  assert.equal(createdIds.includes('OPENSUBTITLES_API_KEY-test'),false);
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

test('setup-form loads and saves COMPOSE_PROFILES, OpenSubtitles, EasyNews, precache, and Jellyfin without blank-overwriting secrets',async()=>{
  assert.match(source,/\['OPENSUBTITLES_API_KEY'/,'OPENSUBTITLES_API_KEY should be in extras/fields');
  const env=form({
    COMPOSE_PROFILES:'scrapers,anime-db',
    configuredKeys:['PROVIDER_KEY','OPENSUBTITLES_API_KEY'],
    OPENSUBTITLES_API_KEY_SAVED:true,
    EASYNEWS_USER:'en-user',
    EASYNEWS_PASSWORD_SAVED:true,
    AIO_PRECACHE_NEXT_EPISODE:'true',
    JELLYFIN_ENABLED:'false'
  });
  env.context.fields.push(['OPENSUBTITLES_API_KEY']);
  await vm.runInContext('loadSettings()',env.context);

  assert.equal(env.nodes.get('compose-profiles').value,'core,anime');
  assert.equal(env.nodes.get('OPENSUBTITLES_API_KEY').value,'');
  assert.equal(env.nodes.get('OPENSUBTITLES_API_KEY').placeholder,'Saved · enter to replace');
  assert.equal(env.nodes.get('easynews-user').value,'en-user');
  assert.equal(env.nodes.get('easynews-pass').value,'');
  assert.equal(env.nodes.get('easynews-pass').placeholder,'Saved · enter to replace');
  assert.equal(env.nodes.get('aio-precache-next-episode').checked,true);
  assert.equal(env.nodes.get('jellyfin-enabled').checked,false);

  // Submit with blank secrets: must preserve OPENSUBTITLES_API_KEY and EASYNEWS_PASSWORD
  await env.nodes.get('setup-form').handlers.submit({preventDefault(){}});
  const save1=env.calls.find(c=>c.path==='/api/save-env').payload;
  assert.equal(save1.COMPOSE_PROFILES,'core,anime');
  assert.equal(save1.EASYNEWS_USER,'en-user');
  assert.equal(save1.AIO_PRECACHE_NEXT_EPISODE,'true');
  assert.equal(save1.JELLYFIN_ENABLED,'false');
  assert.equal('OPENSUBTITLES_API_KEY' in save1,false);
  assert.equal('EASYNEWS_PASSWORD' in save1,false);

  // Submit with newly entered secrets and toggled controls
  env.calls.length=0;
  env.nodes.get('OPENSUBTITLES_API_KEY').value='os-new-key';
  env.nodes.get('easynews-pass').value='en-new-pass';
  env.nodes.get('aio-precache-next-episode').checked=false;
  env.nodes.get('jellyfin-enabled').checked=true;
  env.nodes.get('compose-profiles').value='core,tunnel';
  await env.nodes.get('setup-form').handlers.submit({preventDefault(){}});
  const save2=env.calls.find(c=>c.path==='/api/save-env').payload;
  assert.equal(save2.OPENSUBTITLES_API_KEY,'os-new-key');
  assert.equal(save2.EASYNEWS_PASSWORD,'en-new-pass');
  assert.equal(save2.AIO_PRECACHE_NEXT_EPISODE,'false');
  assert.equal(save2.JELLYFIN_ENABLED,'true');
  assert.equal(save2.COMPOSE_PROFILES,'core,tunnel');
});

test('btn-stop-cf-tunnel and btn-restart-cf-tunnel call /api/cloudflare/tunnel and refresh status',async()=>{
  const notices=[];
  const env=form({USENET_ENABLED:'false',configuredKeys:['PROVIDER_KEY']});
  env.context.notify=(msg,isErr)=>notices.push({msg,isErr});
  const cfBlock=source.slice(source.indexOf('// Cloudflare Tunnel & Automated DNS Management'),source.lastIndexOf("document.querySelectorAll('.streaming-mode-section"));
  vm.runInContext(cfBlock,env.context);

  let statusRefreshes=0;
  const origApi=env.context.api;
  env.context.api=async(path,opts)=>{
    if(path==='/api/cloudflare/status'){statusRefreshes++;return {local_tunnel:{state:'exited'}};}
    return origApi(path,opts);
  };

  const stopBtn=env.nodes.get('btn-stop-cf-tunnel');
  await stopBtn.handlers.click({currentTarget:stopBtn});
  assert.equal(env.calls.some(c=>c.path==='/api/cloudflare/tunnel'&&c.payload.action==='stop'),true);
  assert.equal(stopBtn.disabled,false);

  const restartBtn=env.nodes.get('btn-restart-cf-tunnel');
  await restartBtn.handlers.click({currentTarget:restartBtn});
  assert.equal(env.calls.some(c=>c.path==='/api/cloudflare/tunnel'&&c.payload.action==='restart'),true);
  assert.equal(restartBtn.disabled,false);
  assert.equal(statusRefreshes,2);
  assert.ok(notices.some(n=>/stopped/i.test(n.msg)));
  assert.ok(notices.some(n=>/restarted/i.test(n.msg)));
});

test('playback test forwards selected kind and content_id',async()=>{
  const env=form({});
  const fnPlayback=source.match(/async function runPlaybackTest\(\) \{[\s\S]*?\n\}/)[0];
  env.context.notify=()=>{};
  vm.runInContext(fnPlayback,env.context);
  env.document.getElementById('playback-test-kind').value='anime';
  env.document.getElementById('playback-test-id').value='tt9335498';
  await vm.runInContext('runPlaybackTest()',env.context);
  const call=env.calls.find(c=>c.path==='/api/test-playback');
  assert.equal(call.payload.kind,'anime');
  assert.equal(call.payload.content_id,'tt9335498');
});

test('index.html exposes required diagnostics, log containers, playback inputs, and maintenance controls',()=>{
  const html=fs.readFileSync('index.html','utf8');
  for(const val of ['alldebrid','debridlink','easydebrid','usenet','nzb']){
    assert.match(html,new RegExp(`id="provider-check"[\\s\\S]*?value="${val}"`));
  }
  for(const val of ['shared-postgres','shared-redis','jikan-api']){
    assert.match(html,new RegExp(`id="logs-container-select"[\\s\\S]*?value="${val}"`));
  }
  assert.match(html,/id="smoke-kind"[\s\S]*?value="anime"/);
  for(const id of ['playback-test-kind','playback-test-id','compose-profiles','easynews-user','easynews-pass','aio-precache-next-episode','jellyfin-enabled','backup-keep-last','backup-archives-list','btn-maintenance-prune-backups','preview-cache','clean-cache-posters','btn-stop-cf-tunnel','btn-restart-cf-tunnel','btn-restart-stack','cf-origin-preset','cf-origin-target','cf-origin-candidates','cf-origin-warning','btn-test-cf-reachability','cf-reachability-results','card-reachability','btn-test-reachability','reachability-summary','reachability-results']){
    assert.match(html,new RegExp(`id="${id}"`));
  }
});

test('refreshCloudflareStatus prefills :3001 recommended_origin for external connectors, warns on :3000, and submits service_url on btn-push-cf-dns', async () => {
  let lastNotification = '';
  const env = form({
    USENET_ENABLED: 'false',
    configuredKeys: ['PROVIDER_KEY'],
    CLOUDFLARE_ZONE_ID: 'zone-ext',
    CLOUDFLARE_API_TOKEN_SAVED: true,
    CLOUDFLARE_TUNNEL_METADATA: {
      valid: true,
      tunnel_id: 'ext-tunnel-id',
      cname_target: 'ext-tunnel-id.cfargotunnel.com'
    }
  });
  env.context.notify = (msg) => { lastNotification = msg; };

  const origApi = env.context.api;
  env.context.api = async (path, options) => {
    if (path === '/api/cloudflare/status') {
      return {
        has_external: true,
        connector_mode: 'external_bridge',
        recommended_origin: 'http://host.docker.internal:3001',
        detected_origin: 'http://aiostreams:3000',
        origin_warning: 'External connector cannot reach aiostreams:3000 on stremio-net',
        origin_candidates: [
          { label: 'External Bridge / DinD (:3001)', url: 'http://host.docker.internal:3001' },
          { label: 'Host-Network Connector (:3001)', url: 'http://127.0.0.1:3001' }
        ],
        external_connectors: [{ name: 'cloudflared-host', image: 'cloudflare/cloudflared', status: 'Up 2 hours' }],
        token_configured: true
      };
    }
    if (path === '/api/cloudflare/push-dns') {
      const payload = options?.body ? JSON.parse(options.body) : null;
      env.calls.push({ path, payload });
      return {
        success: true,
        message: 'DNS and ingress updated',
        hostname: payload.hostname,
        cname_target: payload.cname_target,
        zone_name: 'customdomain.org',
        service_url: payload.service_url,
        repaired: true,
        ingress_action: 'repaired',
        previous_service_url: 'http://aiostreams:3000',
        tunnel_started: false
      };
    }
    return origApi(path, options);
  };

  const cfBlock = source.slice(source.indexOf('// Cloudflare Tunnel & Automated DNS Management'), source.lastIndexOf("document.querySelectorAll('.streaming-mode-section"));
  vm.runInContext(cfBlock, env.context);
  await vm.runInContext('loadSettings()', env.context);
  await vm.runInContext('refreshCloudflareStatus()', env.context);

  const originInput = env.nodes.get('cf-origin-target');
  const warnBox = env.nodes.get('cf-origin-warning');
  assert.equal(originInput.value, 'http://host.docker.internal:3001');
  assert.equal(warnBox.style.display, 'block');
  assert.match(warnBox.innerHTML, /Stale :3000 Origin Detected/i);
  assert.match(warnBox.innerHTML, /http:\/\/aiostreams:3000/);

  // Typing :3000 manually triggers immediate unreachable-origin warning
  originInput.value = 'http://aiostreams:3000';
  await originInput.handlers.input({ currentTarget: originInput });
  assert.match(warnBox.innerHTML, /Unreachable Origin \(:3000\)/i);

  // Restore :3001 via preset selector "Auto"
  env.nodes.get('cf-origin-preset').value = '';
  await env.nodes.get('cf-origin-preset').handlers.change({ currentTarget: env.nodes.get('cf-origin-preset') });
  assert.equal(originInput.value, 'http://host.docker.internal:3001');

  // Push DNS forwards service_url and renders repaired ingress banner
  env.calls.length = 0;
  env.nodes.get('base-url').value = 'https://watch.customdomain.org';
  await env.nodes.get('btn-push-cf-dns').handlers.click({ currentTarget: env.nodes.get('btn-push-cf-dns') });
  const pushCall = env.calls.find(c => c.path === '/api/cloudflare/push-dns');
  assert.ok(pushCall);
  assert.equal(pushCall.payload.service_url, 'http://host.docker.internal:3001');
  const dnsHtml = env.nodes.get('cf-dns-result').innerHTML;
  assert.match(dnsHtml, /Repaired stale Cloudflare ingress rule/i);
  assert.match(dnsHtml, /http:\/\/host\.docker\.internal:3001/);
  assert.match(lastNotification, /Cloudflare DNS CNAME pushed/i);
});

test('Test Reachability renders checks, highlights unreachable targets, and escapes untrusted output', async () => {
  const evil = '<img src=x onerror=alert(1)>';
  const env = form({ USENET_ENABLED: 'false', configuredKeys: ['PROVIDER_KEY'] });
  env.context.notify = () => {};

  const origApi = env.context.api;
  env.context.api = async (path, options) => {
    if (path === '/api/reachability') {
      const payload = options?.body ? JSON.parse(options.body) : null;
      env.calls.push({ path, payload });
      return {
        success: true,
        ok: false,
        status: 'fail',
        recommended_origin: 'http://host.docker.internal:3001',
        connector_mode: 'external_bridge',
        summary: { total: 3, passed: 1, failed: 1, warnings: 1, skipped: 0 },
        checks: [
          {
            id: 'host_3001',
            name: 'AIOStreams Host Port',
            category: 'host_port',
            target: 'http://127.0.0.1:3001/health',
            ok: true,
            status: 'ok',
            latency_ms: 4.5,
            detail: 'HTTP 200 OK',
            remediation: null
          },
          {
            id: 'cf_origin',
            name: `Cloudflare Origin ${evil}`,
            category: 'cloudflare',
            target: `http://aiostreams:3000/${evil}`,
            ok: false,
            status: 'fail',
            latency_ms: 12.2,
            detail: `Connection refused ${evil}`,
            remediation: `Point Cloudflare tunnel to http://host.docker.internal:3001 ${evil}`
          },
          {
            id: 'remote_base',
            name: 'Public BASE_URL',
            category: 'remote',
            target: 'https://watch.example.com',
            ok: false,
            status: 'warn',
            latency_ms: 88.0,
            detail: 'Returned 502 Bad Gateway',
            remediation: 'Verify tunnel ingress rule points to :3001'
          }
        ]
      };
    }
    return origApi(path, options);
  };

  const cfBlock = source.slice(source.indexOf('// Cloudflare Tunnel & Automated DNS Management'), source.lastIndexOf("document.querySelectorAll('.streaming-mode-section"));
  const opsFn = source.match(/async function runOperations\(\) \{[\s\S]*?\n\}/)[0];
  vm.runInContext(cfBlock + '\n' + opsFn, env.context);
  await vm.runInContext('runOperations()', env.context);

  env.nodes.get('cf-origin-target').value = 'http://host.docker.internal:3001';
  const btn = env.nodes.get('btn-test-reachability');
  await btn.handlers.click({ currentTarget: btn });

  const reachCall = env.calls.find(c => c.path === '/api/reachability');
  assert.ok(reachCall);
  assert.equal(reachCall.payload.origin_url, 'http://host.docker.internal:3001');
  assert.equal(reachCall.payload.include_remote, true);

  const summaryHtml = env.nodes.get('reachability-summary').innerHTML;
  const resultsHtml = env.nodes.get('reachability-results').innerHTML;
  assert.match(summaryHtml, /1 unreachable target/i);
  assert.match(summaryHtml, /1 passed/);
  assert.match(resultsHtml, /reachability-item reachability-ok/);
  assert.match(resultsHtml, /reachability-item reachability-fail/);
  assert.match(resultsHtml, /reachability-item reachability-warn/);
  assert.match(resultsHtml, /✗ Unreachable/);
  assert.match(resultsHtml, /4\.5 ms/);
  assert.match(resultsHtml, /Next step:/);
  assert.ok(!resultsHtml.includes('<img'), 'Untrusted HTML must be escaped');
  assert.ok(resultsHtml.includes('&lt;img'), 'Escaped tag text should be preserved');

  // Remote Access quick Reachability button also works
  const cfBtn = env.nodes.get('btn-test-cf-reachability');
  await cfBtn.handlers.click({ currentTarget: cfBtn });
  assert.equal(env.nodes.get('cf-reachability-results').style.display, 'block');
  assert.match(env.nodes.get('cf-reachability-results').innerHTML, /reachability-item reachability-fail/);
});

test('btn-push-cf-dns confirms external connector without Start Local Tunnel warning when external_connector_active is true', async () => {
  let lastNotification = '';
  const env = form({
    USENET_ENABLED: 'false',
    configuredKeys: ['PROVIDER_KEY'],
    CLOUDFLARE_ZONE_ID: 'zone-ext',
    CLOUDFLARE_API_TOKEN_SAVED: true,
    CLOUDFLARE_TUNNEL_METADATA: {
      valid: true,
      tunnel_id: 'ext-tunnel-id',
      cname_target: 'ext-tunnel-id.cfargotunnel.com'
    }
  });
  env.context.notify = (msg) => { lastNotification = msg; };

  const origApi = env.context.api;
  env.context.api = async (path, options) => {
    if (path === '/api/cloudflare/status') {
      return {
        has_external: true,
        connector_mode: 'external_host',
        recommended_origin: 'http://127.0.0.1:3001',
        external_connectors: [{ name: 'host-cf', image: 'cloudflare/cloudflared', status: 'Up 2 hours' }],
        token_configured: true
      };
    }
    if (path === '/api/cloudflare/push-dns') {
      const payload = options?.body ? JSON.parse(options.body) : null;
      env.calls.push({ path, payload });
      return {
        success: true,
        message: 'DNS and ingress updated',
        hostname: payload.hostname,
        cname_target: payload.cname_target,
        zone_name: 'customdomain.org',
        service_url: payload.service_url,
        tunnel_started: false,
        external_connector_active: true
      };
    }
    return origApi(path, options);
  };

  const cfBlock = source.slice(source.indexOf('// Cloudflare Tunnel & Automated DNS Management'), source.lastIndexOf("document.querySelectorAll('.streaming-mode-section"));
  vm.runInContext(cfBlock, env.context);
  await vm.runInContext('loadSettings()', env.context);
  await vm.runInContext('refreshCloudflareStatus()', env.context);

  env.nodes.get('base-url').value = 'https://watch.customdomain.org';
  await env.nodes.get('btn-push-cf-dns').handlers.click({ currentTarget: env.nodes.get('btn-push-cf-dns') });

  const dnsHtml = env.nodes.get('cf-dns-result').innerHTML;
  assert.doesNotMatch(dnsHtml, /502 Bad Gateway Prevention/i);
  assert.doesNotMatch(dnsHtml, /Start Local Tunnel/i);
  assert.match(dnsHtml, /external connector/i);
  assert.match(dnsHtml, /without starting a duplicate <code>aio-tunnel<\/code>/i);
  assert.match(lastNotification, /external connector/i);
});

test('api handles non-JSON 502/503 HTML gateway errors via response.clone() without body-stream errors or leaking HTML/stack traces', async () => {
  const html502 = '<!doctype html><html><head><title>502 Bad Gateway</title></head><body><h1>502 Bad Gateway</h1></body></html>';
  const trace503 = 'Traceback (most recent call last):\n  File "portal_server.py", line 10, in handle\nRuntimeError: boom';
  for (const [status, body] of [[502, html502], [503, trace503]]) {
    let bodyConsumed = false;
    const context = vm.createContext({
      URL,
      location: new URL('http://server:8088'),
      fetch: async () => ({
        ok: false,
        status,
        clone() {
          return {
            async text() {
              return body;
            }
          };
        },
        async json() {
          if (bodyConsumed) throw new TypeError('body stream already read');
          bodyConsumed = true;
          throw new SyntaxError('Unexpected token <');
        },
        async text() {
          if (bodyConsumed) throw new TypeError('body stream already read');
          bodyConsumed = true;
          return body;
        }
      })
    });
    vm.runInContext(source.slice(source.indexOf('async function api('), source.indexOf('function notify(')), context);
    await assert.rejects(
      vm.runInContext("api('/api/backups/prune',{method:'POST'})", context),
      (err) => {
        assert.match(err.message, new RegExp(`server returned ${status}`));
        assert.doesNotMatch(err.message, /<html|<title|Traceback|portal_server\.py/i);
        return true;
      }
    );
  }

  // Unexpected 200 HTML response also yields a clean non-JSON error
  const okHtmlCtx = vm.createContext({
    URL,
    location: new URL('http://server:8088'),
    fetch: async () => ({
      ok: true,
      status: 200,
      async json() { throw new SyntaxError('Unexpected token <'); }
    })
  });
  vm.runInContext(source.slice(source.indexOf('async function api('), source.indexOf('function notify(')), okHtmlCtx);
  await assert.rejects(
    vm.runInContext("api('/api/reachability',{method:'POST'})", okHtmlCtx),
    /unexpected non-JSON response/i
  );
});

test('renderReachabilityResults groups streaming checks alongside other categories, displays remediation, and escapes XSS payloads', async () => {
  const evil = '<img src=x onerror=alert(1)>';
  const env = form({ USENET_ENABLED: 'true', configuredKeys: ['PROVIDER_KEY'] });
  env.context.notify = () => {};
  const origApi = env.context.api;
  env.context.api = async (path, options) => {
    if (path === '/api/reachability') {
      return {
        success: true,
        ok: false,
        status: 'fail',
        recommended_origin: `http://host.docker.internal:3001/${evil}`,
        connector_mode: `external_bridge ${evil}`,
        summary: { total: 8, passed: 4, failed: 3, warnings: 1, skipped: 0 },
        checks: [
          { id: 'internal:aiostreams', name: 'AIOStreams (Internal)', category: 'internal', target: 'http://aiostreams:3000/health', ok: true, status: 'ok', latency_ms: 2.1, detail: 'HTTP 200', remediation: null },
          { id: 'host:aiostreams', name: 'AIOStreams Host Port', category: 'host_port', target: '127.0.0.1:3001', ok: true, status: 'ok', latency_ms: 3.4, detail: 'HTTP 200', remediation: null },
          { id: 'portal:healthz', name: 'Portal Healthz', category: 'portal', target: 'http://127.0.0.1:8088/healthz', ok: true, status: 'ok', latency_ms: 1.8, detail: 'HTTP 200', remediation: null },
          { id: 'stream:memory', name: 'AIOStreams Memory Limit', category: 'streaming', target: '512m', ok: false, status: 'fail', latency_ms: null, detail: `AIOSTREAMS_MEM_LIMIT=512m too small ${evil}`, remediation: `Set AIOSTREAMS_MEM_LIMIT=1024m for memory headroom ${evil}` },
          { id: 'stream:proxy_urls', name: 'Stream & Proxy Base URL', category: 'streaming', target: 'http://localhost:3001', ok: true, status: 'warn', latency_ms: null, detail: 'BASE_URL mismatch while Cloudflare active', remediation: 'Set BASE_URL=https://watch.example.com' },
          { id: 'stream:usenet_route', name: 'Native Usenet Stream Route', category: 'streaming', target: 'http://127.0.0.1:3001/api/v1/usenet/stream/', ok: true, status: 'ok', latency_ms: 5.5, detail: 'HTTP 404', remediation: null },
          { id: 'stream:keepalive', name: 'Origin HTTP Keep-Alive Reuse', category: 'cloudflare', target: 'http://host.docker.internal:3001', ok: false, status: 'fail', latency_ms: 11.2, detail: 'Connection reset on reuse', remediation: 'Tune keepAliveTimeout above 60s (120s)' },
          { id: 'cloudflare:jellyfin_web', name: 'Jellyfin Web & Forwarded Headers', category: 'cloudflare', target: 'http://host.docker.internal:3001/jellyfin/web/', ok: false, status: 'fail', latency_ms: 9.7, detail: 'Expected HTTPS LocalAddress behind /jellyfin/web/', remediation: 'Ensure TRUSTED_IPS includes connector subnet' },
          { id: 'remote:base', name: 'Public BASE_URL', category: 'remote', target: 'https://watch.example.com', ok: true, status: 'ok', latency_ms: 42.0, detail: 'HTTP 200', remediation: null }
        ]
      };
    }
    return origApi(path, options);
  };

  const cfBlock = source.slice(source.indexOf('// Cloudflare Tunnel & Automated DNS Management'), source.lastIndexOf("document.querySelectorAll('.streaming-mode-section"));
  const opsFn = source.match(/async function runOperations\(\) \{[\s\S]*?\n\}/)[0];
  vm.runInContext(cfBlock + '\n' + opsFn, env.context);
  await vm.runInContext('runOperations()', env.context);

  const btn = env.nodes.get('btn-test-reachability');
  await btn.handlers.click({ currentTarget: btn });

  const summaryHtml = env.nodes.get('reachability-summary').innerHTML;
  const resultsHtml = env.nodes.get('reachability-results').innerHTML;
  assert.match(resultsHtml, /reachability-group-streaming/);
  assert.match(resultsHtml, /Streaming &amp; Proxy/);
  assert.match(resultsHtml, /Cloudflare Origin/);
  assert.match(resultsHtml, /Host Port/);
  assert.match(resultsHtml, /Portal Route/);
  assert.match(resultsHtml, /Internal/);
  assert.match(resultsHtml, /Public URL/);
  assert.match(resultsHtml, /keepAliveTimeout/i);
  assert.match(resultsHtml, /BASE_URL mismatch/i);
  assert.match(resultsHtml, /memory headroom/i);
  assert.match(resultsHtml, /\/jellyfin\/web\//);
  assert.ok(!resultsHtml.includes('<img') && !summaryHtml.includes('<img'), 'XSS payload must be escaped');
  assert.ok(resultsHtml.includes('&lt;img') && summaryHtml.includes('&lt;img'));
  assert.equal(btn.disabled, false);
});

test('btn-push-cf-dns surfaces base_url_mismatch sync button, saves BASE_URL via /api/save-env, and handles 502 errors cleanly', async () => {
  const notices = [];
  const syncBtnNode = {
    textContent: 'Sync BASE_URL to https://watch.customdomain.org',
    disabled: false,
    dataset: { recommendedBaseUrl: 'https://watch.customdomain.org' },
    attrs: {},
    handlers: {},
    setAttribute(k, v) { this.attrs[k] = v; },
    removeAttribute(k) { delete this.attrs[k]; },
    getAttribute(k) { return this.attrs[k]; },
    addEventListener(t, h) { this.handlers[t] = h; }
  };
  const mismatchBoxNode = { className: '', innerHTML: '' };
  const mismatchStatusNode = { textContent: '', innerHTML: '' };
  const env = form({
    USENET_ENABLED: 'true',
    BASE_URL: 'http://localhost:3001',
    configuredKeys: ['PROVIDER_KEY'],
    CLOUDFLARE_ZONE_ID: 'zone-sync',
    CLOUDFLARE_API_TOKEN_SAVED: true,
    CLOUDFLARE_TUNNEL_METADATA: { valid: true, tunnel_id: 'sync-tun', cname_target: 'sync-tun.cfargotunnel.com' }
  });
  env.context.notify = (msg, isErr) => notices.push({ msg, isErr });
  const dnsResultNode = env.document.getElementById('cf-dns-result');
  dnsResultNode.querySelector = (sel) => {
    if (sel === '#btn-sync-cf-base-url') return syncBtnNode;
    if (sel === '#cf-base-url-mismatch-box') return mismatchBoxNode;
    if (sel === '#cf-base-url-mismatch-status') return mismatchStatusNode;
    return null;
  };

  let failSaveEnv = true;
  const origApi = env.context.api;
  env.context.api = async (path, options) => {
    if (path === '/api/cloudflare/status') {
      return {
        has_external: false,
        connector_mode: 'local',
        recommended_origin: 'http://aiostreams:3000',
        token_configured: true,
        local_tunnel: { state: 'running', status: 'Up 1 minute' }
      };
    }
    if (path === '/api/cloudflare/push-dns') {
      const payload = JSON.parse(options.body);
      env.calls.push({ path, payload });
      return {
        success: true,
        message: 'DNS record updated',
        hostname: 'watch.customdomain.org',
        cname_target: 'sync-tun.cfargotunnel.com',
        zone_name: 'customdomain.org',
        service_url: payload.service_url,
        tunnel_started: true,
        base_url_mismatch: true,
        current_base_url: 'http://localhost:3001',
        recommended_base_url: 'https://watch.customdomain.org',
        base_url_synced: false
      };
    }
    if (path === '/api/save-env') {
      if (failSaveEnv) throw new Error('The server returned 502. Check setup details and retry.');
      const payload = JSON.parse(options.body);
      env.calls.push({ path, payload });
      return { success: true };
    }
    return origApi(path, options);
  };

  const cfBlock = source.slice(source.indexOf('// Cloudflare Tunnel & Automated DNS Management'), source.lastIndexOf("document.querySelectorAll('.streaming-mode-section"));
  vm.runInContext(cfBlock, env.context);
  await vm.runInContext('loadSettings()', env.context);
  await vm.runInContext('refreshCloudflareStatus()', env.context);

  env.nodes.get('base-url').value = 'https://watch.customdomain.org';
  await env.nodes.get('btn-push-cf-dns').handlers.click({ currentTarget: env.nodes.get('btn-push-cf-dns') });

  assert.match(dnsResultNode.innerHTML, /BASE_URL Mismatch Detected/i);
  assert.match(dnsResultNode.innerHTML, /btn-sync-cf-base-url/);
  assert.match(dnsResultNode.innerHTML, /http:\/\/localhost:3001/);
  assert.ok(syncBtnNode.handlers.click, 'Expected one-click sync button click handler');

  // First click fails with 502 -> button must re-enable and show error without clearing button
  await syncBtnNode.handlers.click({ currentTarget: syncBtnNode });
  assert.equal(syncBtnNode.disabled, false);
  assert.equal(syncBtnNode.attrs['aria-busy'], undefined);
  assert.match(mismatchStatusNode.innerHTML, /502/);

  // Retry succeeds -> saves BASE_URL and updates inputs & confirmation box
  failSaveEnv = false;
  await syncBtnNode.handlers.click({ currentTarget: syncBtnNode });
  const saveCall = env.calls.find(c => c.path === '/api/save-env');
  assert.ok(saveCall);
  assert.equal(saveCall.payload.BASE_URL, 'https://watch.customdomain.org');
  assert.equal(env.nodes.get('base-url').value, 'https://watch.customdomain.org');
  assert.equal(env.nodes.get('proxy-url').value, 'https://watch.customdomain.org');
  assert.equal(env.nodes.get('guide-player-preview').textContent, 'https://watch.customdomain.org');
  assert.equal(mismatchBoxNode.className, 'cf-base-url-sync-ok');
  assert.match(mismatchBoxNode.innerHTML, /Saved <code>BASE_URL<\/code> as <code>https:\/\/watch\.customdomain\.org<\/code>/);
  assert.equal(syncBtnNode.disabled, false);
});

test('tunnel and reachability buttons always release busy/disabled state on non-JSON 502 errors and escape error text', async () => {
  const notices = [];
  const env = form({ USENET_ENABLED: 'false', configuredKeys: ['PROVIDER_KEY'] });
  env.context.notify = (msg, isErr) => notices.push({ msg, isErr });
  env.context.api = async () => {
    throw new Error('The server returned 502. <script>alert(1)</script>');
  };

  const cfBlock = source.slice(source.indexOf('// Cloudflare Tunnel & Automated DNS Management'), source.lastIndexOf("document.querySelectorAll('.streaming-mode-section"));
  const opsFn = source.match(/async function runOperations\(\) \{[\s\S]*?\n\}/)[0];
  vm.runInContext(cfBlock + '\n' + opsFn, env.context);
  await vm.runInContext('runOperations()', env.context);

  const stopBtn = env.nodes.get('btn-stop-cf-tunnel');
  stopBtn.textContent = 'Stop Tunnel ■';
  await stopBtn.handlers.click({ currentTarget: stopBtn });
  assert.equal(stopBtn.disabled, false);
  assert.equal(stopBtn.textContent, 'Stop Tunnel ■');

  const restartBtn = env.nodes.get('btn-restart-cf-tunnel');
  restartBtn.textContent = 'Restart Tunnel ↻';
  await restartBtn.handlers.click({ currentTarget: restartBtn });
  assert.equal(restartBtn.disabled, false);
  assert.equal(restartBtn.textContent, 'Restart Tunnel ↻');

  const reachBtn = env.nodes.get('btn-test-reachability');
  reachBtn.textContent = 'Test Reachability 🌐';
  await reachBtn.handlers.click({ currentTarget: reachBtn });
  assert.equal(reachBtn.disabled, false);
  assert.equal(reachBtn.textContent, 'Test Reachability 🌐');
  assert.doesNotMatch(env.nodes.get('reachability-results').innerHTML, /<script>/);
  assert.match(env.nodes.get('reachability-results').innerHTML, /&lt;script&gt;/);

  env.document.getElementById('base-url').value = 'https://watch.customdomain.org';
  env.document.getElementById('cf-api-token').value = 'cf-api-tok';
  const pushBtn = env.document.getElementById('btn-push-cf-dns');
  pushBtn.textContent = 'Push DNS to Cloudflare 🚀';
  await pushBtn.handlers.click({ currentTarget: pushBtn });
  assert.equal(pushBtn.disabled, false);
  assert.equal(pushBtn.textContent, 'Push DNS to Cloudflare 🚀');
  assert.doesNotMatch(env.nodes.get('cf-dns-result').innerHTML, /<script>/);
  assert.match(env.nodes.get('cf-dns-result').innerHTML, /&lt;script&gt;/);
  assert.ok(notices.some(n => n.isErr && /502/.test(n.msg)));
});
