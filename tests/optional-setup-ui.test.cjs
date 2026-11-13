const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('assets/app.js','utf8');

function form(saved){
  const nodes=new Map(),calls=[];
  const document={
    querySelectorAll(){ return []; },
    getElementById(id){
      if(!nodes.has(id))nodes.set(id,{value:'',checked:false,style:{},handlers:{},addEventListener(type,handler){this.handlers[type]=handler;}});
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
  const load=source.match(/async function loadSettings\(\) \{[\s\S]*?\n\}/)[0];
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

test('custom ports update player-link and nuvio-player-link hrefs',async()=>{
  const env=form({PORT_STREMIO_WEB:'18082',PORT_NUVIO:'18085',ports:{stremio_web:18082,nuvio:18085},configuredKeys:[]});
  await vm.runInContext('loadSettings()',env.context);
  assert.equal(env.nodes.get('player-link').href,'http://server:18082');
  assert.equal(env.nodes.get('player-link').textContent,'Launch Stremio Web (:18082) ↗');
  assert.equal(env.nodes.get('nuvio-player-link').href,'http://server:18085');
  assert.equal(env.nodes.get('nuvio-player-link').textContent,'Launch Nuvio Web (:18085) ↗');
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

test('updateStatusOverview merges health and integrations data and updates overview card elements',async()=>{
  const env=form({});
  const fnStatus = source.match(/function updateStatusOverview\([^\)]*\) \{[\s\S]*?\n\}/)[0];
  vm.runInContext('let lastHealthData = null, lastIntegrations = null;\n' + fnStatus, env.context);
  const integrations = [
    { name: 'AIOStreams', group: 'Core', reachable: true, enabled: true },
    { name: 'Stremio Web', group: 'Core', reachable: true, enabled: true },
    { name: 'Comet', group: 'Scrapers', reachable: false, enabled: true },
  ];
  const healthData = {
    watchdog: { overall: 'healthy', healthy_count: 14, total_services: 14 },
    backup: { count: 3, total_size_mb: 42 }
  };
  vm.runInContext('updateStatusOverview(' + JSON.stringify(healthData) + ', ' + JSON.stringify(integrations) + ')', env.context);
  assert.equal(env.nodes.get('overview-services').textContent, '2/3 Online');
  assert.equal(env.nodes.get('overview-watchdog').textContent, '14/14 Healthy');
  assert.equal(env.nodes.get('overview-backup').textContent, '3 Saved (42 MB)');
});

function readinessUI() {
  const env = form({});
  const readinessCode = source.slice(source.indexOf('let playbackReadiness ='), source.indexOf('async function runPlaybackTest()'));
  vm.runInContext(readinessCode, env.context);
  return env;
}

test('startup gates both buttons, respects unapplied edits, and fails closed on lost connection', async () => {
  const env = readinessUI();
  vm.runInContext('renderPlaybackReadiness()', env.context);
  assert.equal(env.nodes.get('btn-test-playback').disabled, true);
  env.context.api = async () => ({ready:true, message:'Ready to test', checks:[]});
  await vm.runInContext('refreshPlaybackReadiness()', env.context);
  assert.equal(env.nodes.get('btn-test-playback').disabled, false);
  vm.runInContext('setupFormDirty = true; renderPlaybackReadiness()', env.context);
  assert.equal(env.nodes.get('overview-test-playback-btn').disabled, true);
  vm.runInContext('setupFormDirty = false; lastJobStatus = "running"; renderPlaybackReadiness()', env.context);
  assert.equal(env.nodes.get('btn-test-playback').disabled, true);
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
