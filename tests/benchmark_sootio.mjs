// Pipe into a separate Node process INSIDE the retained Sootio container.
// Never exports credentials, titles, torrent hashes or signed media URLs.
import cp from 'node:child_process';
import {syncBuiltinESMExports} from 'node:module';
import {promisify} from 'node:util';
import {createHash} from 'node:crypto';
const source=process.env.BENCH_SOURCE||'btdig';
const variant=process.env.BENCH_VARIANT||'baseline';
const kind=process.env.BENCH_CASE||'movie';
if(!['btdig','magnetdl','premiumize','streams'].includes(source)||!['baseline','pages2','fast','optimized'].includes(variant)||!['movie','episode'].includes(kind))throw Error('Invalid fixture');
const output=process.stdout.write.bind(process.stdout);
for(const name of ['log','info','warn','error','debug','time','timeEnd'])console[name]=()=>{};
process.env.MONGO_CACHE_ENABLED='false'; // Process-local; shared server is unchanged.
const intervals=[];const interval=globalThis.setInterval;
globalThis.setInterval=(...args)=>{const h=interval(...args);intervals.push(h);return h;};
const children=new Set();const replies=[];let curlCalls=0,curlFailures=0,curlSeconds=0;
const original=cp.exec;
cp.exec=function(command,options,callback){
  const isCurl=command.startsWith('curl ');const start=performance.now();
  if(isCurl){
    curlCalls++;
    if(variant==='fast')command=command.replace(/^curl /,'curl --connect-timeout 2 --max-time 3 --retry 0 ');
    if(variant!=='optimized')command+=" -w '\\n__AIO_STATUS__%{http_code}'";
  }
  const child=original.call(this,command,options,(error,stdout,stderr)=>{
    if(isCurl){
      curlSeconds+=(performance.now()-start)/1000;if(error)curlFailures++;
      const status=String(stdout||'').match(/\n__(?:AIO_STATUS|AIO_SCRAPER_HTTP)__(\d{3})$/);
      if(variant!=='optimized')stdout=String(stdout||'').replace(/\n__AIO_STATUS__\d{3}$/,'');
      let kind=stdout?'other':'empty',records=0;
      const preview=String(stdout||'').replace(/\n__AIO_SCRAPER_HTTP__\d{3}$/,'');
      try{const value=JSON.parse(preview);kind='json';records=Object.values(value).filter(x=>x?.info_hash).length;}catch{if(/^\s*</.test(preview))kind='html';}
      replies.push({http:status?Number(status[1]):null,kind,records,captcha:/g-recaptcha|captcha|security check|just a moment/i.test(stdout)});
    }
    callback(error,stdout,stderr);
  });
  children.add(child);child.once('close',()=>children.delete(child));return child;
};
// Preserve Node's exec promisification contract: callers expect {stdout,stderr}.
cp.exec[promisify.custom]=(command,options)=>new Promise((resolve,reject)=>cp.exec(command,options,(error,stdout,stderr)=>error?reject(error):resolve({stdout,stderr})));
syncBuiltinESMExports();
let wrapperUrl;
if(variant==='optimized'){
  if(!process.env.BENCH_WRAPPER_B64||!process.env.BENCH_PATCH_B64)throw Error('Candidate source required');
  wrapperUrl='data:text/javascript;base64,'+process.env.BENCH_WRAPPER_B64;
  const patchUrl='data:text/javascript;base64,'+process.env.BENCH_PATCH_B64;
  const {register}=await import('node:module');
  const loader=`import {patchSource} from '${patchUrl}';export async function load(url,context,next){const r=await next(url,context);if(url==='file:///app/lib/common/scrapers.js')return {...r,source:patchSource(String(r.source),${JSON.stringify(wrapperUrl)})};return r;}`;
  register('data:text/javascript;base64,'+Buffer.from(loader).toString('base64'),'file:///app/');
}
const config={Languages:['en'],Scrapers:['magnetdl','btdig'],IndexerScrapers:[],
              BTDIG_MAX_PAGES:Number(process.env.BENCH_PAGES)||(variant==='baseline'?5:variant==='pages2'?2:1),
              BTDIG_LIMIT:50,BTDIG_USE_PROXIES:false,SCRAPER_TIMEOUT:variant==='fast'?3000:5000};
const fixtures={movie:{type:'movie',id:'tt15239678',query:'Dune Part Two 2024'},
                episode:{type:'series',id:'tt0944947:2:2',query:'Game of Thrones s02e02'}};
const fixture=fixtures[kind];let run;
const report={source,variant,case:kind,cachePolicy:'fresh worker process; no shared-cache flush',measurements:[]};
report.pageLimit=config.BTDIG_MAX_PAGES;
try{
  if(source==='premiumize'||source==='streams'){
    const key=process.env.PREMIUMIZE_API_KEY;
    if(!key)throw Error('Provider unavailable');
    if(source==='premiumize'){
      const provider=(await import('/app/lib/premiumize.js')).default;
      run=()=>provider.search(key,fixture.type,fixture.id,config);
    }else{
      Object.assign(config,{DebridServices:[{provider:'Premiumize',apiKey:key}],DebridProvider:'Premiumize',DebridApiKey:key,Resolutions:['4k','1080p','720p'],ShowCatalog:false});
      const provider=(await import('/app/lib/stream-provider.js')).default;
      run=()=>provider[kind==='movie'?'getMovieStreams':'getSeriesStreams'](config,fixture.type,fixture.id);
    }
  }else{
    const scrapers=await import('/app/lib/common/scrapers.js');
    run=()=>scrapers[source==='btdig'?'searchBtdig':'searchMagnetDL'](fixture.query,new AbortController().signal,'BENCH',config);
  }
  for(const mode of ['fresh-process','warm']){
    if(mode==='warm'&&!report.measurements[0].results&&variant!=='optimized')break;
    const before=curlCalls;const start=performance.now();
    const rows=await run();
    const hashes=[...new Set(rows.map(r=>r.InfoHash||r.infoHash).filter(Boolean))];
    const identity=rows.map(r=>JSON.stringify([r.name,r.title,r.behaviorHints?.bingeGroup,r.behaviorHints?.filename])).sort();
    report.measurements.push({mode,seconds:+((performance.now()-start)/1000).toFixed(3),results:rows.length,
      uniqueHashes:hashes.length,curlCalls:curlCalls-before,
      identityDigest:createHash('sha256').update(JSON.stringify(identity)).digest('hex'),
      hashFingerprints:hashes.map(h=>createHash('sha256').update(h.toLowerCase()).digest('hex')).sort()});
  }
}catch(error){report.errorType=error.name;}
// Upstream coordinator timeouts do not cancel work. Keep the worker alive until
// its curl children finish, rather than orphaning a request when the result returns.
const deadline=Date.now()+45000;
while(children.size&&Date.now()<deadline)await new Promise(r=>setTimeout(r,100));
report.curl={calls:curlCalls,failures:curlFailures,totalSeconds:+curlSeconds.toFixed(3),remaining:children.size,replies};
if(wrapperUrl)report.bounded=(await import(wrapperUrl)).stats();
for(const handle of intervals)clearInterval(handle);
output(JSON.stringify(report)+'\n');
if(children.size)process.exitCode=1;
