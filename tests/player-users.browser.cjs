'use strict';
const assert=require('node:assert/strict');const fs=require('node:fs');const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1100,height:850}});
  const html=fs.readFileSync('/runner/ui/index.html','utf8');
  const block=html.slice(html.indexOf('<details id="player-users"'),html.indexOf('</details>',html.indexOf('<details id="player-users"'))+10);
  await page.setContent('<html><head><style>'+fs.readFileSync('/runner/ui/app.css','utf8')+'</style></head><body><main style="padding:20px">'+block+'</main></body></html>');
  await page.evaluate(()=>{
   window.calls=[];window.copies=[];let users=[];let rev=0;
   window.copyToClipboard=(value)=>window.copies.push(value);
   window.api=async(path,opts)=>{
    window.calls.push({path,opts});
    if(opts){const p=JSON.parse(opts.body);if(p.expectedRevision!==String(rev))throw Error('Stale revision');
     if(p.action==='create'){users=[{id:'guest1',name:p.name,isolated:true,inviteUrl:'https://watch.example/jellyfin/p/fixture123456/web/'}];rev++;return{success:true,enabled:true,pinSignInEnabled:true,revision:String(rev),users,pin:'12345678',inviteUrl:users[0].inviteUrl};}}
    return{success:true,enabled:true,pinSignInEnabled:true,revision:String(rev),users};};
  });
  await page.addScriptTag({path:'/runner/ui/player-users.js'});
  assert.equal(await page.evaluate(()=>calls.length),0);
  await page.locator('#player-users > summary').click();
  await page.locator('#player-user-name').fill('Alex');
  await page.getByRole('button',{name:'Add person',exact:true}).click();
  await page.getByText('PIN — copy it now:').waitFor();
  await page.getByRole('button',{name:'Copy PIN',exact:true}).click();
  assert.equal(await page.evaluate(()=>copies[0]),'12345678');
  await page.getByRole('button',{name:'Copy invite link',exact:true}).first().click();
  assert.equal(await page.evaluate(()=>copies[1]),'https://watch.example/jellyfin/p/fixture123456/web/');
  await page.screenshot({path:'/tmp/player-users-desktop.png'});
  await page.setViewportSize({width:390,height:850});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:'/tmp/player-users-mobile.png'});
  await page.locator('#player-users > summary').click();
  await page.waitForFunction(()=>document.getElementById('player-users-status').textContent==='');
  assert.equal(await page.locator('#player-users-status').textContent(),'');
  console.log('PASS: Users form, create, copy link/PIN, close clears PIN, desktop/mobile layout');
 } finally {await browser.close();}
})().catch(()=>{console.error('FAIL: Users browser acceptance');process.exitCode=1;});
