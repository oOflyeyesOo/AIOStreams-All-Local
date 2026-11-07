const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const vm = require('vm');
const source=fs.readFileSync('assets/app.js','utf8');
function environment(api,confirm=()=>false) {
 const nodes=new Map();
 const document={getElementById(id){if(!nodes.has(id))nodes.set(id,{textContent:'',disabled:false,handlers:{},addEventListener(type,handler){this.handlers[type]=handler;}});return nodes.get(id);}};
 const context=vm.createContext({document,api,confirm,notify:()=>{}});
 const functions=['refreshMaintenance','runOperations'].map(name=>source.match(new RegExp('async function '+name+'\\(\\) \\{[\\s\\S]*?\\n\\}'))[0]).join('\n');
 vm.runInContext(functions,context);
 return {context,nodes,document};
}
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
