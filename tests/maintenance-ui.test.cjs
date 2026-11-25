const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const vm = require('vm');
const source=fs.readFileSync('assets/app.js','utf8');

function lumiereEnvironment(response) {
 const nodes = new Map();
 const document = {getElementById(id) {if (!nodes.has(id)) nodes.set(id, {innerHTML:'', value:'query', open:false}); return nodes.get(id);}};
 const context = vm.createContext({document, window:{}, api:async()=>response});
 const escape = source.match(/function escapeHtml\(str\) \{[\s\S]*?\n\}/)[0];
 vm.runInContext(escape + '\n' + source.slice(source.indexOf('function lumiereStatusLabel('), source.indexOf('function pollLumiereRebuildProgress(')), context);
 return {nodes, document, context};
}

test('Lumiere statistics preserve zero and never fabricate missing counts or progress', async()=>{
 const env = lumiereEnvironment({success:true, phase:'idle', docs:0, episodes:null, people:undefined, names:0});
 await vm.runInContext('showLumiereStats()',env.context);
 const html = env.nodes.get('lumiere-stats-content').innerHTML;
 assert.match(html, /lumiere-stat-num">0</);
 assert.match(html, /Not reported/);
 assert.doesNotMatch(html, /319,117|4,580,131|100%|65%|gen-2026|Optimal LSM|Hourly/);
});

test('Lumiere status distinguishes offline caches, unready idle and actual phases', async()=>{
 for (const [stats, expected] of [
  [{online:false,ready:false,phase:'offline'}, 'Offline · cached metrics only'],
  [{online:false,ready:true,phase:'idle'}, 'Offline · cached metrics only'],
  [{online:true,ready:false,phase:'idle'}, 'Not ready (idle)'],
  [{online:true,ready:true,phase:'idle'}, 'Ready (idle)'],
  [{online:true,ready:false,phase:'downloading'}, 'Reported phase: downloading']
 ]) {
  const env = lumiereEnvironment({success:true,...stats});
  await vm.runInContext('showLumiereStats()',env.context);
  assert.ok(env.nodes.get('lumiere-stats-content').innerHTML.includes(expected));
  assert.equal(vm.runInContext(`lumiereStatusLabel(${JSON.stringify(stats)})`,env.context),expected);
 }
});

test('Lumiere search renders malicious results and queries as text and validates IMDb links', async()=>{
 const evil = '<img src=x onerror=alert(1)>';
 const env = lumiereEnvironment({success:true,items:[{title:evil,type:evil,year:evil,imdbId:'tt1/" onmouseover="bad',popularity:evil},{title:'Safe',imdbId:'tt1234567'}],count:evil,latencyMs:evil});
 await vm.runInContext('handleLumiereSandboxSearch()',env.context);
 const html = env.nodes.get('lumiere-test-results').innerHTML;
 assert.doesNotMatch(html, /<img|onmouseover/);
 assert.match(html, /&lt;img/);
 assert.match(html, /href="https:\/\/www.imdb.com\/title\/tt1234567\/"/);
 env.context.api = async()=>({success:true,items:[],latencyMs:0});
 env.document.getElementById('lumiere-test-input').value = evil;
 await vm.runInContext('handleLumiereSandboxSearch()',env.context);
 assert.doesNotMatch(env.nodes.get('lumiere-test-results').innerHTML, /<img/);
 env.context.api = async()=>{throw Error(evil);};
 await vm.runInContext('showLumiereStats()',env.context);
 assert.doesNotMatch(env.nodes.get('lumiere-stats-content').innerHTML, /<img/);
});

test('clipboard feedback waits for success and failed fallback never marks button copied', async()=>{
 let resolve, removed=0;
 const notices=[];
 const button={innerHTML:'Copy',textContent:'Copy',classList:{add(){},remove(){}}};
 const context=vm.createContext({navigator:{clipboard:{writeText:()=>new Promise(r=>resolve=r)}},notify:(...args)=>notices.push(args),setTimeout:()=>{},button,
   document:{createElement:()=>({style:{},select(){},remove(){removed++;}}),body:{append(){}},execCommand:()=>false}});
 vm.runInContext(source.match(/async function copyToClipboard\(text, successMsg, triggerBtn\) \{[\s\S]*?\n\}/)[0],context);
 const copying=vm.runInContext("copyToClipboard('fixture','Copied fixture',button)",context);
 assert.equal(button.textContent,'Copy'); assert.equal(notices.length,0);
 resolve(); assert.equal(await copying,true); assert.equal(button.textContent,'Copied! ✓');
 button.textContent='Copy'; button._origContent=null;
 context.navigator.clipboard.writeText=async()=>{throw Error('permission denied');};
 assert.equal(await vm.runInContext("copyToClipboard('fixture','Copied fixture',button)",context),false);
 assert.equal(button.textContent,'Copy'); assert.equal(notices.at(-1)[1],true); assert.equal(removed,1);
});
function environment(api,confirm=()=>false) {
 const nodes=new Map();
 const document={getElementById(id){if(!nodes.has(id))nodes.set(id,{textContent:'',disabled:false,handlers:{},addEventListener(type,handler){this.handlers[type]=handler;}});return nodes.get(id);}};
 const context=vm.createContext({document,api,confirm,notify:()=>{}});
 const functions=['refreshMaintenance','runOperations'].map(name=>source.match(new RegExp('async function '+name+'\\(\\) \\{[\\s\\S]*?\\n\\}'))[0]).join('\n');
 vm.runInContext(functions,context);
 return {context,nodes,document};
}

function rebuildEnvironment(stats) {
 const timers=[], notices=[], calls=[];
 const button={disabled:false,textContent:'Rebuild index ↻'}, badge={textContent:''};
 const context=vm.createContext({window:{},button,badge,setTimeout:fn=>timers.push(fn),showToast:message=>notices.push(message),
  api:async(path,options)=>{calls.push({path,options}); return path.endsWith('/rebuild') ? {success:true} : stats();}});
 vm.runInContext(source.slice(source.indexOf('let lumiereRebuildPending ='),source.indexOf('async function showContainerLogs(')),context);
 return {context,button,badge,notices,calls,timers,
  start:()=>vm.runInContext('startLumiereRebuild(button,badge)',context),
  tick:async()=>{assert.ok(timers.length,'poll scheduled'); await timers.shift()();}};
}

test('rebuild unchanged idle never claims success and times out with uncertainty', async()=>{
 const env=rebuildEnvironment(()=>({success:true,online:true,ready:true,phase:'idle',generationId:'old'}));
 const result=env.start(); await new Promise(setImmediate);
 assert.equal(env.button.disabled,true);
 for(let n=0;n<60;n++) await env.tick();
 assert.equal(await result,false); assert.equal(env.button.disabled,false);
 assert.match(env.notices.at(-1),/Could not verify.*may still be running/);
 assert.ok(!env.notices.some(message=>message.includes('returned to ready')));
});

test('rebuild completion needs a changed generation or observed activity plus online ready idle', async()=>{
 for(const middle of [
  [{success:true,online:true,ready:true,phase:'idle',generationId:'new'}],
  [{success:true,online:true,ready:false,phase:'building',generationId:'old'},
   {success:true,online:true,ready:true,phase:'idle',generationId:'old'}]
 ]) {
  const responses=[{success:true,online:true,ready:true,phase:'idle',generationId:'old'},...middle];
  const env=rebuildEnvironment(()=>responses.shift());
  const result=env.start(); await new Promise(setImmediate);
  for(let n=0;n<middle.length;n++) await env.tick();
  assert.equal(await result,true); assert.equal(env.button.disabled,false);
  assert.match(env.notices.at(-1),/observed index update/);
 }
});

test('offline changed generation and unready idle cannot confirm a rebuild', async()=>{
 const responses=[{success:true,online:true,ready:true,phase:'idle',generationId:'old'},
  {success:true,online:false,ready:true,phase:'idle',generationId:'new'},
  {success:true,online:true,ready:false,phase:'idle',generationId:'new'},
  {success:true,online:true,ready:true,phase:'failed',generationId:'new'}];
 const env=rebuildEnvironment(()=>responses.shift());
 const result=env.start(); await new Promise(setImmediate);
 await env.tick(); assert.equal(env.button.disabled,true);
 await env.tick(); assert.equal(env.button.disabled,true);
 await env.tick(); assert.equal(await result,false);
 assert.match(env.notices.at(-1),/reports a failure/);
});

test('rebuild requests share a guard and never overlap status polls', async()=>{
 const env=rebuildEnvironment(()=>({success:true,online:true,ready:true,phase:'idle',generationId:'old'}));
 const result=env.start(); await new Promise(setImmediate);
 assert.equal(await env.start(),false);
 assert.equal(env.calls.filter(call=>call.path.endsWith('/rebuild')).length,1);
 let resolve;
 env.context.api=()=>new Promise(done=>resolve=done);
 const pending=env.tick(); assert.equal(env.timers.length,0);
 resolve({success:true,online:true,ready:true,phase:'idle',generationId:'new'});
 await pending; assert.equal(await result,true); assert.equal(env.timers.length,0);
});
test('configured keys are not presented as verified authorization or playback',async()=>{
 const env=environment(async()=>({release:{release:'fixture',status:'Immutable image set'},backup:{status:'partial'},readiness:{providerConfigured:true,metadataConfigured:false},security:{defaultPassword:true}}));
 await vm.runInContext('refreshMaintenance()',env.context);
 const readiness=env.nodes.get('readiness-output').textContent;
 assert.match(readiness,/Provider keys: configured/);assert.match(readiness,/Playback: not verified/);assert.match(readiness,/replace the default/);
 assert.match(env.nodes.get('maintenance-output').textContent,/Backup: partial/);
});
test('cache cleanup needs confirmation and is a single POST with a disabled button',async()=>{
 let calls=0,resolve;
 const env=environment(()=>{calls++;return new Promise(r=>resolve=r);});
 await vm.runInContext('runOperations()',env.context);
 const button=env.document.getElementById('clean-cache');
 await button.handlers.click({currentTarget:button});assert.equal(calls,0);
 env.context.confirm=()=>true;
 env.context.api=(path,options)=>{assert.equal(path,'/api/clean-cache');assert.equal(options.method,'POST');calls++;return new Promise(r=>resolve=r);};
 const request=button.handlers.click({currentTarget:button});assert.equal(button.disabled,true);assert.equal(calls,1);
 resolve({success:true,freed_mb:4});await request;assert.equal(button.disabled,false);assert.match(env.nodes.get('cache-output').textContent,/4 MB/);
});
