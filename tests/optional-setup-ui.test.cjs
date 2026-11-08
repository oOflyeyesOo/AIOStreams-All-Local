const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('assets/app.js','utf8');

function form(saved){
  const nodes=new Map(),calls=[];
  const document={getElementById(id){
    if(!nodes.has(id))nodes.set(id,{value:'',checked:false,handlers:{},addEventListener(type,handler){this.handlers[type]=handler;}});
    return nodes.get(id);
  }};
  const context=vm.createContext({document,URL,location:new URL('http://server:8088'),
    providers:[['PROVIDER_KEY']],fields:[['PROVIDER_KEY'],['NZB_INDEXER_API_KEY']],savedKeys:new Set(),
    usenetPasswordSaved:false,deriveAiometaHost:()=>'',setProgress:()=>{},pollSetup:async()=>{},
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
  const env=form({USENET_ENABLED:'true',USENET_HOST:'news.fixture',USENET_PORT:'563',USENET_USER:'fixture-user',USENET_CONNECTIONS:'10',USENET_SSL:'true',USENET_PASSWORD_SAVED:true,MEDIAFUSION_REPLICAS:'0',configuredKeys:['NZB_INDEXER_API_KEY']});
  await vm.runInContext('loadSettings()',env.context);
  assert.equal(env.nodes.get('usenet-host').value,'news.fixture');assert.equal(env.nodes.get('usenet-pass').value,'');
  assert.match(env.nodes.get('usenet-pass').placeholder,/Saved/);
  assert.equal(env.nodes.get('enable-usenet').checked,true);assert.equal(env.nodes.get('enable-mediafusion').checked,false);
  await env.nodes.get('setup-form').handlers.submit({preventDefault(){}});
  const save=env.calls.find(c=>c.path==='/api/save-env').payload;
  assert.equal(save.USENET_ENABLED,'true');assert.equal(save.USENET_SSL,'true');assert.equal(save.MEDIAFUSION_REPLICAS,'0');
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
