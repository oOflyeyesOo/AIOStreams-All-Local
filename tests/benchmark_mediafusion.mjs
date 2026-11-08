// Read-only audit inside the retained AIOStreams container. Credentials stay in memory.
import fs from 'node:fs';
import {performance} from 'node:perf_hooks';
const output=process.stdout.write.bind(process.stdout);
for(const name of ['log','info','warn','error','debug'])console[name]=()=>{};
const report={scope:'retained configuration unchanged; source-adapter comparison, not post-SEL playback',cases:[]};
try{
  const install=JSON.parse(fs.readFileSync('/data/aiostreams_install.json','utf8'));
  const r=await fetch('http://127.0.0.1:3000/api/v1/user',{headers:{Authorization:'Basic '+Buffer.from(install.uuid+':admin_local_secret').toString('base64')}});
  const user=(await r.json()).data.userData;
  const services=user.services.filter(s=>s.enabled&&s.id==='premiumize'&&s.credentials?.apiKey);
  if(!services.length)throw Error('Configured provider unavailable');
  const preset=user.presets.find(p=>p.type==='mediafusion');
  const options=preset?.options||{};
  const source=fs.readFileSync('/app/packages/core/dist/presets/mediafusion.js','utf8');
  const start=source.indexOf('static buildConfig('),end=source.lastIndexOf('\n}');
  if(start<0||end<start)throw Error('Unsupported native adapter');
  const build=Function('appConfig','constants','return (function '+source.slice(start+'static '.length,end)+')')(
    {presets:{mediafusion:{apiPassword:process.env.MEDIAFUSION_API_PASSWORD||process.env.ADDON_PASSWORD}}},
    {EASYNEWS_SERVICE:'easynews',PIKPAK_SERVICE:'pikpak'});
  const config=build.call({getServiceCredential:(id,u)=>u.services.find(s=>s.id===id)?.credentials.apiKey},user,options,services.map(s=>s.id));
  const token=Buffer.from(JSON.stringify(config)).toString('base64url');
  const comet={debridServices:services.map(s=>({service:s.id,apiKey:s.credentials.apiKey})),enableTorrent:false,
    scrapeDebridAccountTorrents:false,cachedOnly:false,removeTrash:true,maxResultsPerResolution:0,maxSize:0,resultFormat:['all']};
  const cometToken=Buffer.from(JSON.stringify(comet)).toString('base64');
  report.configuration={mediafusionPresetEnabled:!!preset?.enabled,liveSearch:config.live_search_streams,
    catalogsSelected:config.selected_catalogs.length,watchlistCatalogs:!!config.streaming_provider.enable_watchlist_catalogs};
  async function measure(url,headers={}){
    const start=performance.now();
    const response=await fetch(url,{headers,signal:AbortSignal.timeout(25000)});
    const value=await response.json();
    const rows=(value.streams||[]).filter(s=>s.url||s.infoHash);
    const hashes=new Set(),cachedHashes=new Set();let cached=0;
    for(const stream of rows){
      const isCached=stream.behaviorHints?.cached===true||/⚡|PM\+/.test(stream.name||'');
      if(isCached)cached++;
      let text=stream.infoHash||'';
      try{text+=' '+decodeURIComponent(stream.url||'');}catch{}
      const hash=text.match(/(?:^|[^a-f0-9])([a-f0-9]{40})(?:$|[^a-f0-9])/i)?.[1]?.toLowerCase();
      if(hash){hashes.add(hash);if(isCached)cachedHashes.add(hash);}
    }
    return {public:{http:response.status,seconds:+((performance.now()-start)/1000).toFixed(3),candidates:rows.length,cachedCandidates:cached,comparableHashes:hashes.size,comparableCachedHashes:cachedHashes.size},hashes,cachedHashes};
  }
  for(const [kind,id] of [['movie','tt15239678'],['series','tt0944947:2:2']]){
    const row={case:kind};
    try{
      const a=await measure('http://comet:8000/'+cometToken+'/stream/'+kind+'/'+id+'.json');
      const b=await measure('http://mediafusion:8000/stream/'+kind+'/'+id+'.json',{encoded_user_data:token});
      const warm=await measure('http://mediafusion:8000/stream/'+kind+'/'+id+'.json',{encoded_user_data:token});
      Object.assign(row,{comet:a.public,mediafusion:b.public,mediafusionWarm:warm.public,
        mediafusionKnownHashesAbsentFromComet:[...b.hashes].filter(h=>!a.hashes.has(h)).length,
        mediafusionKnownCachedHashesAbsentFromComet:[...b.cachedHashes].filter(h=>!a.hashes.has(h)).length});
    }catch(error){row.errorType=error.name;}
    report.cases.push(row);
  }
}catch(error){report.errorType=error.name;}
output(JSON.stringify(report,null,2)+'\n');
