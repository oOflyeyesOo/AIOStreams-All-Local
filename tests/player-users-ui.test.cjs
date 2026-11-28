const test=require('node:test');const assert=require('node:assert/strict');const fs=require('fs');const vm=require('vm');
function harness(reply){
 class Node{constructor(){this.children=[];this.handlers={};this.value='';this.open=false;this.disabled=false;this.textContent='';}append(...items){this.children.push(...items)}replaceChildren(...items){this.children=items;this.textContent=''}setAttribute(){}focus(){}querySelectorAll(){return this.children.flatMap(c=>typeof c==='object'?[c,...c.querySelectorAll()]:[])}addEventListener(k,h){this.handlers[k]=h}}
 const nodes=new Map(['player-users','player-users-list','player-users-status','player-users-form','player-user-name','player-users-refresh','open-player-users'].map(id=>[id,new Node()]));
 nodes.get('player-users').children=[nodes.get('player-users-form'),nodes.get('player-users-list'),nodes.get('player-users-status'),nodes.get('player-users-refresh')];
 const calls=[],copied=[];const ctx={document:{getElementById:id=>nodes.get(id),createElement:()=>new Node()},URL,window:{confirm:()=>true},api:async(...args)=>{calls.push(args);return reply(...args)},copyToClipboard:(v)=>copied.push(v)};
 vm.runInNewContext(fs.readFileSync('assets/player-users.js','utf8'),ctx);
 return{nodes,calls,copied,async load(){nodes.get('player-users').open=true;await nodes.get('player-users').handlers.toggle()},async submit(name){nodes.get('player-user-name').value=name;return nodes.get('player-users-form').handlers.submit({preventDefault(){}})}};
}
const response={success:true,enabled:true,pinSignInEnabled:true,revision:'rev1',users:[]};
test('users load only on demand; creates include revision and display PIN only once',async()=>{
 const h=harness(async(path,opts)=>opts?{...response,pin:'12345678',inviteUrl:'https://watch.example/jellyfin/p/abc/web/'}:response);
 assert.equal(h.calls.length,0);await h.load();await h.submit('Alex');
 assert.deepEqual(JSON.parse(h.calls[1][1].body),{action:'create',name:'Alex',expectedRevision:'rev1'});
 assert.ok(h.nodes.get('player-users-status').children.some(x=>x.textContent==='12345678'));
 h.nodes.get('player-users').open=false;await h.nodes.get('player-users').handlers.toggle();assert.equal(h.nodes.get('player-users-status').children.length,0);
});
test('failed writes require refresh and never automatically retry',async()=>{
 const h=harness(async(p,o)=>{if(o)throw Error('Configuration changed');return response});await h.load();await h.submit('Alex');await h.submit('Alex');
 assert.equal(h.calls.length,2);assert.match(h.nodes.get('player-users-status').textContent,/Refresh/);
});
test('unsupported PIN sign-in cannot submit and invalid names never reach server',async()=>{
 const h=harness(async()=>({...response,pinSignInEnabled:false}));await h.load();await h.submit('Alex');assert.equal(h.calls.length,1);
 const valid=harness(async()=>response);await valid.load();await valid.submit('a'.repeat(33));assert.equal(valid.calls.length,1);
});
test('names are text, household profiles are read-only, and unsafe links are not copied',async()=>{
 const h=harness(async()=>({...response,users:[{id:'house',name:'<img src=x>',inviteUrl:'javascript:alert(1)',isolated:false}]}));await h.load();
 const row=h.nodes.get('player-users-list').children[0];assert.equal(row.children[0].textContent,'<img src=x>');
 assert.equal(row.children.find(x=>x.className==='player-user-actions').children.length,0);assert.deepEqual(h.copied,[]);
});
