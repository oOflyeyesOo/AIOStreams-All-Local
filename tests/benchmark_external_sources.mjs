// Pipe into the retained AIOStreams container. No configuration writes or external credentials.
import fs from 'node:fs';
import {performance} from 'node:perf_hooks';
const output=process.stdout.write.bind(process.stdout);
for(const name of ['log','info','warn','error','debug'])console[name]=()=>{};
const endpoints={torrentio:'https://torrentio.strem.fun',knightcrawler:'https://knightcrawler.elfhosted.com'};
const report={scope:'public discovery; local Comet comparison; optional cache checks only against official Premiumize API; no configuration changes or media decoding',sources:{},cases:[]};
async function read(url){
  const start=performance.now();
  let status,type;
  try{
    const response=await fetch(url,{signal:AbortSignal.timeout(20000)});
    status=response.status;type=response.headers.get('content-type');
    const value=await response.json();
    return {value,summary:{http:response.status,seconds:+((performance.now()-start)/1000).toFixed(3)}};
  }catch(error){return {value:{},summary:{http:status,contentType:type,seconds:+((performance.now()-start)/1000).toFixed(3),errorType:error.name}};}
}
for(const [name,url] of Object.entries(endpoints)){
  const {value,summary}=await read(url+'/manifest.json');
  report.sources[name]={...summary,id:value.id||null,name:value.name||null};
}
let cometToken,providerKey;
try{
  const install=JSON.parse(fs.readFileSync('/data/aiostreams_install.json','utf8'));
  const r=await fetch('http://127.0.0.1:3000/api/v1/user',{headers:{Authorization:'Basic '+Buffer.from(install.uuid+':admin_local_secret').toString('base64')}});
  const user=(await r.json()).data.userData;
  const services=user.services.filter(s=>s.enabled&&s.id==='premiumize'&&s.credentials?.apiKey);
  providerKey=services[0]?.credentials.apiKey;
  cometToken=Buffer.from(JSON.stringify({debridServices:services.map(s=>({service:s.id,apiKey:s.credentials.apiKey})),
    enableTorrent:true,scrapeDebridAccountTorrents:false,cachedOnly:false,removeTrash:true,maxResultsPerResolution:0,maxSize:0,resultFormat:['all']})).toString('base64');
}catch{report.localComparisonUnavailable=true;}
for(const [kind,id] of [['movie','tt15239678'],['series','tt0944947:2:2'],['movie','tt1375666'],['series','tt0903747:1:1']]){
  const row={case:kind,id,sources:{}};const sets={};
  for(const [name,base] of Object.entries({...endpoints,...(cometToken?{comet:'http://comet:8000/'+cometToken}:{})})){
    const {value,summary}=await read(base+'/stream/'+kind+'/'+id+'.json');
    const rows=(value.streams||[]).filter(s=>s.infoHash||s.url);
    const hashes=new Set();
    for(const stream of rows){
      let text=stream.infoHash||'';
      try{text+=' '+decodeURIComponent(stream.url||'');}catch{}
      for(const match of text.matchAll(/(?:^|[^a-f0-9])([a-f0-9]{40})(?=$|[^a-f0-9])/gi))hashes.add(match[1].toLowerCase());
    }
    const providers={};
    for(const stream of rows){
      const label=(stream.title||stream.description||'').match(/⚙[\ufe0f]?\s*([^\n]+)/)?.[1]?.trim();
      if(label&&/^[a-z0-9 ._-]{1,40}$/i.test(label))providers[label]=(providers[label]||0)+1;
    }
    sets[name]=hashes;row.sources[name]={...summary,candidates:rows.length,hashes:hashes.size,...(name==='torrentio'?{providers}:{} )};
  }
  if(sets.knightcrawler&&sets.comet)row.knightcrawlerHashesAbsentFromComet=[...sets.knightcrawler].filter(h=>!sets.comet.has(h)).length;
  if(sets.torrentio&&sets.comet)row.torrentioHashesAbsentFromComet=[...sets.torrentio].filter(h=>!sets.comet.has(h)).length;
  if(sets.torrentio&&sets.knightcrawler)row.knightcrawlerHashesAbsentFromTorrentio=[...sets.knightcrawler].filter(h=>!sets.torrentio.has(h)).length;
  if(process.env.BENCH_CACHE==='true'&&providerKey){
    try{
      const all=[...new Set(Object.values(sets).flatMap(s=>[...s]))],cached=new Set();
      for(let start=0;start<all.length;start+=100){
        const batch=all.slice(start,start+100),body=new URLSearchParams({apikey:providerKey});
        for(const hash of batch)body.append('items[]',hash);
        const response=await fetch('https://www.premiumize.me/api/cache/check',{method:'POST',body,signal:AbortSignal.timeout(15000)});
        const value=await response.json();
        if(!response.ok||value.status!=='success'||!Array.isArray(value.response)||value.response.length!==batch.length)throw Error('Cache check unavailable');
        batch.forEach((hash,i)=>{if(value.response[i])cached.add(hash);});
      }
      row.cachedHashes=Object.fromEntries(Object.entries(sets).map(([name,hashes])=>[name,[...hashes].filter(h=>cached.has(h)).length]));
      row.torrentioCachedHashesAbsentFromComet=[...sets.torrentio].filter(h=>cached.has(h)&&!sets.comet?.has(h)).length;
    }catch{row.cacheCheckUnavailable=true;}
  }
  report.cases.push(row);
}
output(JSON.stringify(report,null,2)+'\n');
