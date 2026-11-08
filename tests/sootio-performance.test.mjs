import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {createRunner} from '../docker/sootio/bounded-curl.mjs';
import {patchSource} from '../docker/sootio/patch-scrapers.mjs';

const payload=JSON.stringify([{info_hash:'a'.repeat(40),name:'Fixture.Movie.2026.1080p.English'}]);
async function server(handler){
  const s=http.createServer(handler);await new Promise(r=>s.listen(0,'127.0.0.1',r));
  return {url:`http://127.0.0.1:${s.address().port}`,close:()=>new Promise(r=>{s.closeAllConnections();s.close(r);})};
}
const command=url=>`curl -s '${url}'`;

test('valid JSON survives the real curl and promise contract',async()=>{
  const s=await server((q,r)=>r.end(payload));
  try{const runner=createRunner();const r=await runner.run(command(s.url+'/api.php'));
    assert.deepEqual(JSON.parse(r.stdout),JSON.parse(payload));assert.equal(r.stderr,'');assert.doesNotMatch(r.stdout,/AIO_SCRAPER_HTTP/);
  }finally{await s.close();}
});
test('identical concurrent public searches share one request',async()=>{
  let calls=0;const s=await server((q,r)=>{calls++;setTimeout(()=>r.end(payload),50);});
  try{const runner=createRunner();const results=await Promise.all(Array.from({length:8},()=>runner.run(command(s.url+'/api.php'))));
    assert.equal(calls,1);assert.equal(runner.stats().coalesced,7);assert.ok(results.every(r=>r.stdout===payload));
  }finally{await s.close();}
});
test('real curl deadline cancels slow responses and leaves no in-flight work',async()=>{
  let closed=false;const s=await server((q,r)=>r.on('close',()=>{closed=true;}));
  try{const runner=createRunner({requestMs:200,connectMs:100});const start=Date.now();
    await assert.rejects(runner.run(command(s.url+'/search')),/source unavailable/);
    assert.ok(Date.now()-start<1500);assert.equal(runner.stats().inFlight,0);
    await new Promise(r=>setTimeout(r,50));assert.ok(closed);
  }finally{await s.close();}
});
test('failed sources back off across titles, recover after cooldown and hide responses',async()=>{
  let calls=0,now=0;const s=await server((q,r)=>{calls++;if(calls===1){r.statusCode=503;r.end('fixture-private-marker');}else r.end(payload);});
  try{const runner=createRunner({now:()=>now,cooldownMs:100});
    await assert.rejects(runner.run(command(s.url+'/api.php?q=first')),error=>!error.message.includes('fixture-private-marker'));
    await assert.rejects(runner.run(command(s.url+'/api.php?q=second')));assert.equal(calls,1);
    now=101;assert.equal((await runner.run(command(s.url+'/api.php?q=third'))).stdout,payload);assert.equal(calls,2);
  }finally{await s.close();}
});
test('HTML on a JSON endpoint fails soft and triggers backoff',async()=>{
  const runner=createRunner({execute:async()=>({stdout:'<html>unusable page</html>\n__AIO_SCRAPER_HTTP__200'})});
  await assert.rejects(runner.run(command('https://fixture.invalid/api.php')));
  assert.equal(runner.stats().failures,1);
});
test('separate BTDig cookie sessions are not mixed',async()=>{
  let calls=0;const runner=createRunner({execute:async()=>{calls++;await new Promise(r=>setTimeout(r,10));return {stdout:'fixture\n__AIO_SCRAPER_HTTP__200'};}});
  await Promise.all(['one','two'].map(id=>runner.run(`curl -s -c '/tmp/${id}' 'https://fixture.invalid/search'`)));
  assert.equal(calls,2);
});
test('patching fails closed on upstream drift and preserves unrelated scrapers',()=>{
  const original="export async function other(){return execPromise('other');}\n"+['searchBtdig','searchMagnetDL','searchMagnetDLMovie'].map(n=>`export async function ${n}(){${n==='searchBtdig'?'allPageResults.push(...batchResults);':''}return execPromise('fixture');}`).join('\n');
  const changed=patchSource(original);assert.match(changed,/other\(\)\{return execPromise/);assert.match(changed,/batchResults.every/);
  assert.throws(()=>patchSource('unsupported vendor source'));assert.throws(()=>patchSource(changed));
});
test('one unavailable scraper does not discard valid results from the other',async()=>{
  let failedCalls=0;const bad=await server((q,r)=>{failedCalls++;r.statusCode=503;r.end('unavailable');});
  const good=await server((q,r)=>r.end(payload));
  const intervals=[];const originalInterval=globalThis.setInterval;
  globalThis.setInterval=(...args)=>{const handle=originalInterval(...args);intervals.push(handle);return handle;};
  try{
    const {orchestrateScrapers}=await import('/app/lib/util/scraper-selector.js');
    const rows=await orchestrateScrapers({type:'movie',imdbId:'fixture',searchKey:'Fixture partial',baseSearchKey:'Fixture partial',
      signal:new AbortController().signal,logPrefix:'FIXTURE',selectedLanguages:['en'],
      userConfig:{Scrapers:['btdig','magnetdl'],IndexerScrapers:[],BTDIG_URL:bad.url,MAGNETDL_URL:good.url,BTDIG_MAX_PAGES:5,Languages:['en']}});
    assert.equal(rows.flat().filter(x=>x.InfoHash==='a'.repeat(40)).length,1);
    assert.ok(failedCalls>=1&&failedCalls<=2,'Only the first BTDig batch may launch; cooldown may suppress its second request');
  }finally{for(const handle of intervals)clearInterval(handle);globalThis.setInterval=originalInterval;await bad.close();await good.close();}
});
test('actual patched vendor retains deep-page results and valid MagnetDL JSON',async()=>{
  const intervals=[];const originalInterval=globalThis.setInterval;
  globalThis.setInterval=(...args)=>{const handle=originalInterval(...args);intervals.push(handle);return handle;};
  const pages=[];const hash='b'.repeat(40);
  const s=await server((req,res)=>{
    const url=new URL(req.url,'http://fixture');
    if(url.pathname==='/api.php'){res.end(payload);return;}
    const page=Number(url.searchParams.get('p')||0);pages.push(page);
    res.end(page===4?`<div class="one_result"><div class="torrent_name"><a>Fixture.Movie.2026.1080p.English</a></div><div class="torrent_size">1 GB</div><div class="torrent_magnet"><a href="magnet:?xt=urn:btih:${hash}">magnet</a></div></div>`:'<html>Search results</html>');
  });
  try{
    const vendor=await import('/app/lib/common/scrapers.js');
    const cfg={BTDIG_URL:s.url,MAGNETDL_URL:s.url,BTDIG_MAX_PAGES:5,Languages:['en']};
    const b=await vendor.searchBtdig('Fixture deep page',new AbortController().signal,'FIXTURE',cfg);
    assert.equal(b.length,1);assert.equal(b[0].InfoHash,hash);assert.deepEqual(pages,[0,1,2,3,4]);
    const m=await vendor.searchMagnetDL('Fixture valid JSON',new AbortController().signal,'FIXTURE',cfg);
    assert.equal(m.length,1);assert.equal(m[0].InfoHash,'a'.repeat(40));
  }finally{for(const handle of intervals)clearInterval(handle);globalThis.setInterval=originalInterval;await s.close();}
});
