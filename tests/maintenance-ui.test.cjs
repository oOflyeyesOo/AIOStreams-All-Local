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

test('preview-cache runs dry_run without confirmation and forwards include_poster_cache toggle',async()=>{
 const calls=[];
 const env=environment(async(path,options)=>{
  calls.push({path,body:JSON.parse(options.body)});
  return {success:true,dry_run:true,freed_mb:12.5,total_files:42,details:[{target:'Posters+ Image Cache',size_bytes:13107200,file_count:42,status:'dry-run'}]};
 });
 await vm.runInContext('runOperations()',env.context);
 env.document.getElementById('clean-cache-posters').checked=true;
 const previewBtn=env.document.getElementById('preview-cache');
 await previewBtn.handlers.click({currentTarget:previewBtn});
 assert.equal(calls.length,1);
 assert.equal(calls[0].path,'/api/clean-cache');
 assert.deepEqual(calls[0].body,{dry_run:true,include_poster_cache:true});
 assert.equal(previewBtn.disabled,false);
 assert.match(env.nodes.get('cache-output').textContent,/Preview: 12\.5 MB recoverable \(42 files\)/);
 assert.match(env.nodes.get('cache-output').textContent,/Posters\+ Image Cache/);
});

test('clean-cache forwards include_poster_cache when poster toggle is checked',async()=>{
 const calls=[];
 const env=environment(async(path,options)=>{
  calls.push({path,body:JSON.parse(options.body)});
  return {success:true,freed_mb:8.2};
 },()=>true);
 await vm.runInContext('runOperations()',env.context);
 env.document.getElementById('clean-cache-posters').checked=true;
 const button=env.document.getElementById('clean-cache');
 await button.handlers.click({currentTarget:button});
 assert.deepEqual(calls,[{path:'/api/clean-cache',body:{dry_run:false,include_poster_cache:true}}]);
 assert.match(env.nodes.get('cache-output').textContent,/Cleared 8\.2 MB/);
});

test('backup browser renders escaped archives, postgres badges, retention prune, and confirmed restore',async()=>{
 const nodes=new Map();
 const calls=[];
 let confirmed=false;
 const makeNode=(id)=>({id,textContent:'',innerHTML:'',value:'',disabled:false,handlers:{},dataset:{},addEventListener(t,h){this.handlers[t]=h;},querySelectorAll(){return [];}});
 const document={
  getElementById(id){if(!nodes.has(id))nodes.set(id,makeNode(id));return nodes.get(id);},
  querySelectorAll(){return [];}
 };
 const context=vm.createContext({
  document,
  confirm:()=>confirmed,
  notify:()=>{},
  api:async(path,options)=>{
   const body=options?.body?JSON.parse(options.body):null;
   calls.push({path,method:options?.method||'GET',body});
   if(path==='/api/backups'){
    return {count:2,total_size_mb:15.5,archives:[
     {name:'aio-backup-2026.tar.gz',size_mb:10.25,mtime:'2026-11-25T12:00:00Z',postgresIncluded:true},
     {name:'<img src=x onerror=alert(1)>.tar.gz',size_mb:5.25,mtime:'2026-11-24T12:00:00Z',postgresIncluded:false}
    ]};
   }
   if(path==='/api/backups/prune')return {retained:['aio-backup-2026.tar.gz'],pruned:['old.tar.gz'],keep_last:body.keep_last};
   if(path==='/api/backups/restore')return {success:true,filename:body.filename,message:'Restored '+body.filename};
   return {success:true};
  }
 });
 const escape=source.match(/function escapeHtml\(str\) \{[\s\S]*?\n\}/)[0];
 const backupCode=source.slice(source.indexOf('function renderBackupArchives('),source.indexOf('async function refreshMaintenance('));
 vm.runInContext(escape+'\n'+backupCode,context);

 await vm.runInContext('refreshBackupsList()',context);
 const listHtml=nodes.get('backup-archives-list').innerHTML;
 assert.match(listHtml,/aio-backup-2026\.tar\.gz/);
 assert.match(listHtml,/10\.25 MB/);
 assert.match(listHtml,/Postgres Included/);
 assert.match(listHtml,/No Postgres/);
 assert.doesNotMatch(listHtml,/<img/);
 assert.match(listHtml,/&lt;img/);

 const pruneBtn=makeNode('prune-btn');
 await context.pruneBackups('10',pruneBtn);
 assert.equal(pruneBtn.disabled,false);
 const pruneCall=calls.find(c=>c.path==='/api/backups/prune');
 assert.equal(pruneCall.body.keep_last,10);

 const restoreBtn=makeNode('restore-btn');
 restoreBtn.textContent='Restore ↺';
 confirmed=false;
 assert.equal(await context.restoreBackupArchive('aio-backup-2026.tar.gz',restoreBtn),false);
 assert.equal(calls.some(c=>c.path==='/api/backups/restore'),false);

 confirmed=true;
 let resolveRestore;
 const origApi=context.api;
 context.api=(path,options)=>path==='/api/backups/restore'
  ?(calls.push({path,method:options.method,body:JSON.parse(options.body)}),new Promise(r=>{resolveRestore=r;}))
  :origApi(path,options);
 const restoring=context.restoreBackupArchive('aio-backup-2026.tar.gz',restoreBtn);
 assert.equal(restoreBtn.disabled,true);
 assert.equal(restoreBtn.textContent,'Restoring…');
 resolveRestore({success:true,message:'Restored aio-backup-2026.tar.gz'});
 assert.equal(await restoring,true);
 assert.equal(restoreBtn.disabled,false);
 assert.equal(restoreBtn.textContent,'Restore ↺');
 assert.match(nodes.get('maintenance-output').textContent,/Restored aio-backup-2026\.tar\.gz/);
});

test('safe stack restart requires confirmation and disables button in flight',async()=>{
 let calls=0,resolve;
 const env=environment((path,options)=>{
  assert.equal(path,'/api/restart');
  assert.equal(options.method,'POST');
  calls++;
  return new Promise(r=>resolve=r);
 });
 await vm.runInContext('runOperations()',env.context);
 const button=env.document.getElementById('btn-restart-stack');
 await button.handlers.click({currentTarget:button});
 assert.equal(calls,0);
 env.context.confirm=()=>true;
 const req=button.handlers.click({currentTarget:button});
 assert.equal(button.disabled,true);
 assert.equal(calls,1);
 resolve({success:true,message:'Stack restart initiated.'});
 await req;
 assert.equal(button.disabled,false);
 assert.match(env.nodes.get('readiness-output').textContent,/Stack restart initiated/);
});

test('backup, cache preview, and stack restart handlers release busy states on 502 errors and escape untrusted metadata', async () => {
 const nodes = new Map();
 const notices = [];
 const makeNode = (id) => ({
  id,
  textContent: '',
  innerHTML: '',
  value: '',
  disabled: false,
  attrs: {},
  handlers: {},
  dataset: {},
  setAttribute(k, v) { this.attrs[k] = v; },
  removeAttribute(k) { delete this.attrs[k]; },
  addEventListener(t, h) { this.handlers[t] = h; },
  querySelectorAll() { return []; }
 });
 const document = {
  getElementById(id) {
   if (!nodes.has(id)) nodes.set(id, makeNode(id));
   return nodes.get(id);
  },
  querySelectorAll() { return []; }
 };
 const context = vm.createContext({
  document,
  confirm: () => true,
  notify: (msg, isErr) => notices.push({ msg, isErr }),
  api: async () => { throw new Error('The server returned 502. Check setup details and retry.'); }
 });
 const escape = source.match(/function escapeHtml\(str\) \{[\s\S]*?\n\}/)[0];
 const backupCode = source.slice(source.indexOf('function renderBackupArchives('), source.indexOf('async function refreshMaintenance('));
 const opsFn = source.match(/async function runOperations\(\) \{[\s\S]*?\n\}/)[0];
 vm.runInContext(escape + '\n' + backupCode + '\n' + opsFn, context);
 await vm.runInContext('runOperations()', context);

 // Invalid mtime never shows "Invalid Date" and aria-label escapes XSS payload
 context.renderBackupArchives({
  archives: [{ name: '<svg onload=alert(1)>.tar.gz', size_mb: 1.5, mtime: 'not-a-date', postgresIncluded: null }]
 });
 const listHtml = nodes.get('backup-archives-list').innerHTML;
 assert.doesNotMatch(listHtml, /<svg|Invalid Date/);
 assert.match(listHtml, /&lt;svg onload=alert\(1\)&gt;\.tar\.gz/);
 assert.match(listHtml, /aria-label="Restore backup &lt;svg/);
 assert.match(listHtml, /Unknown date/);

 // Refresh backups releases disabled/aria-busy on 502
 const refreshBtn = document.getElementById('btn-refresh-backups');
 refreshBtn.textContent = 'Refresh archives ↻';
 await refreshBtn.handlers.click({ currentTarget: refreshBtn });
 assert.equal(refreshBtn.disabled, false);
 assert.equal(refreshBtn.attrs['aria-busy'], undefined);
 assert.equal(refreshBtn.textContent, 'Refresh archives ↻');
 assert.match(nodes.get('maintenance-output').textContent, /502/);

 // Prune backups releases disabled/aria-busy/textContent on 502
 const pruneBtn = makeNode('btn-maintenance-prune-backups');
 pruneBtn.textContent = 'Prune old backups ⤓';
 await context.pruneBackups('5', pruneBtn);
 assert.equal(pruneBtn.disabled, false);
 assert.equal(pruneBtn.attrs['aria-busy'], undefined);
 assert.equal(pruneBtn.textContent, 'Prune old backups ⤓');
 assert.match(nodes.get('maintenance-output').textContent, /Prune failed:.*502/);

 // Restore backup releases disabled/aria-busy/textContent on 502
 const restoreBtn = makeNode('restore-btn');
 restoreBtn.textContent = 'Restore ↺';
 const ok = await context.restoreBackupArchive('aio-backup.tar.gz', restoreBtn);
 assert.equal(ok, false);
 assert.equal(restoreBtn.disabled, false);
 assert.equal(restoreBtn.attrs['aria-busy'], undefined);
 assert.equal(restoreBtn.textContent, 'Restore ↺');
 assert.match(nodes.get('maintenance-output').textContent, /Restore failed:.*502/);

 // Preview cache releases disabled/aria-busy/textContent on 502
 const previewBtn = document.getElementById('preview-cache');
 previewBtn.textContent = 'Preview Cache 🔍';
 await previewBtn.handlers.click({ currentTarget: previewBtn });
 assert.equal(previewBtn.disabled, false);
 assert.equal(previewBtn.attrs['aria-busy'], undefined);
 assert.equal(previewBtn.textContent, 'Preview Cache 🔍');
 assert.match(nodes.get('cache-output').textContent, /502/);

 // Stack restart releases disabled/aria-busy/textContent on 502
 const restartBtn = document.getElementById('btn-restart-stack');
 restartBtn.textContent = 'Safe Stack Restart ↻';
 await restartBtn.handlers.click({ currentTarget: restartBtn });
 assert.equal(restartBtn.disabled, false);
 assert.equal(restartBtn.attrs['aria-busy'], undefined);
 assert.equal(restartBtn.textContent, 'Safe Stack Restart ↻');
 assert.match(nodes.get('readiness-output').textContent, /Stack restart failed:.*502/);
 assert.ok(notices.some(n => n.isErr && /502/.test(n.msg)));
});

test('player login copies the provisioned identity and never a guessed password', async()=>{
 const copied=[], notices=[];
 const context=vm.createContext({cachedManifestInfo:{uuid:'fixture-profile-id',jellyfinUser:'admin'}, window:{},
   document:{getElementById:()=>null}, copyToClipboard:(...args)=>{copied.push(args);return true;}, notify:(...args)=>notices.push(args)});
 vm.runInContext(source.slice(source.indexOf('function playerLoginIdentity('),source.indexOf("document.getElementById('test-saved-usenet-btn')")),context);
 assert.equal(vm.runInContext("copyPlayerCred('user')",context),true);
 assert.equal(copied[0][0],'fixture-profile-id');
 vm.runInContext("copyPlayerCred('pass'); copyPlayerCred('both')",context);
 assert.equal(copied.length,1);
 assert.equal(notices.length,2);
 context.cachedManifestInfo={jellyfinUser:'admin'};
 assert.equal(vm.runInContext("copyPlayerCred('user')",context),false);
 assert.equal(copied.length,1);
});

test('player helper no longer advertises default credentials or password copying',()=>{
 const html=fs.readFileSync('index.html','utf8');
 assert.doesNotMatch(html,/id="player-helper-(?:user|pass)">admin/);
 assert.doesNotMatch(html,/id="copy-jellyfin-password"|copyPlayerCred\('(?:pass|both)'\)/);
 assert.match(html,/Copy player ID/);
 assert.match(html,/UUID or alias/);
});

test('diagnostics show problems first and collapse passed and untested checks',()=>{
 const context=vm.createContext({escapeHtml:s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')});
 vm.runInContext(source.slice(source.indexOf('function renderReachabilityResults('),source.indexOf('async function runReachabilityCheck(')),context);
 context.results={style:{},innerHTML:''};context.summary={innerHTML:''};
 vm.runInContext(`renderReachabilityResults({ok:false,checks:[
 {name:'Healthy',status:'ok',category:'internal'},
 {name:'Failure',status:'fail',category:'remote',remediation:'Retry after setup'},
 {name:'Unverified',status:'skipped',category:'host_port',remediation:'Do not show a warning box'}
 ]},results,summary,null)`,context);
 assert.ok(context.results.innerHTML.indexOf('Needs attention')<context.results.innerHTML.indexOf('Passed checks'));
 assert.match(context.results.innerHTML,/<details class="reachability-section" data-reachability-section="passed">/);
 assert.match(context.results.innerHTML,/<details class="reachability-section" data-reachability-section="skipped">/);
 assert.doesNotMatch(context.results.innerHTML,/Do not show a warning box/);
 assert.match(context.summary.innerHTML,/1 not tested/);
 assert.doesNotMatch(context.summary.innerHTML,/All checked targets reachable/);
});
