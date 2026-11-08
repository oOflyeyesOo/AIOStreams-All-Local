import {exec} from 'node:child_process';
import {promisify} from 'node:util';
import {createHash} from 'node:crypto';

const nativeExecute=promisify(exec);
const number=(value,fallback,min,max)=>Number.isFinite(Number(value))&&value!==''&&value!==undefined?Math.min(max,Math.max(min,Number(value))):fallback;
const unavailable=()=>Object.assign(new Error('Public scraper source unavailable; retry after cooldown'),{code:'SOOTIO_SOURCE_UNAVAILABLE'});

export function createRunner({execute=nativeExecute,now=Date.now,requestMs=5000,connectMs=2000,cooldownMs=120000,maxPending=8}={}){
  const pending=new Map(),blocked=new Map();
  const counters={requests:0,coalesced:0,cooldownHits:0,failures:0,busy:0};
  async function run(command,options={}){
    if(!/^curl\s/.test(command))throw new Error('Expected a public scraper curl command');
    const targets=[...command.matchAll(/'(https?:\/\/[^']+)'/g)];
    if(!targets.length)throw new Error('Scraper target could not be identified');
    const target=new URL(targets.at(-1)[1]);
    const origin=target.origin;
    if((blocked.get(origin)||0)>now()){counters.cooldownHits++;throw unavailable();}
    blocked.delete(origin);
    const cookies=[...command.matchAll(/(?:^|\s)-(?:b|c)\s+'([^']+)'/g)].map(m=>m[1]).join(':');
    const key=createHash('sha256').update(target.href+'\n'+cookies).digest('hex');
    if(pending.has(key)){counters.coalesced++;return pending.get(key);}
    if(pending.size>=maxPending){counters.busy++;throw new Error('Public scraper request capacity reached');}
    const task=(async()=>{
      counters.requests++;
      try{
        const bounded=command.replace(/^curl\s/,`curl --connect-timeout ${connectMs/1000} --max-time ${requestMs/1000} --retry 0 `)+" -w '\\n__AIO_SCRAPER_HTTP__%{http_code}'";
        const result=await execute(bounded,{...options,encoding:'utf8',timeout:requestMs+1000,maxBuffer:4*1024*1024});
        const match=String(result.stdout||'').match(/\n__AIO_SCRAPER_HTTP__(\d{3})$/);
        const body=String(result.stdout||'').replace(/\n__AIO_SCRAPER_HTTP__\d{3}$/,'');
        if(!match||Number(match[1])!==200)throw unavailable();
        if(/g-recaptcha|hcaptcha\.com|cf-chl-|id=["']challenge-form/i.test(body))throw unavailable();
        if(target.pathname.endsWith('/api.php')){
          const data=JSON.parse(body);
          if(!data||typeof data!=='object')throw unavailable();
          const entries=Object.values(data);
          if(entries.length&&!entries.some(item=>item?.info_hash&&item?.name))throw unavailable();
        }
        return {stdout:body,stderr:''};
      }catch{
        counters.failures++;
        // Keep only origin/deadline, never request URLs, credentials or response bodies.
        blocked.set(origin,now()+cooldownMs);
        while(blocked.size>64)blocked.delete(blocked.keys().next().value);
        throw unavailable();
      }
    })();
    pending.set(key,task);
    try{return await task;}finally{pending.delete(key);}
  }
  return {run,stats:()=>({...counters,inFlight:pending.size,cooldownSources:blocked.size})};
}

const runner=createRunner({
  requestMs:number(process.env.SOOTIO_CURL_TIMEOUT_MS,5000,1000,15000),
  connectMs:number(process.env.SOOTIO_CONNECT_TIMEOUT_MS,2000,500,5000),
  cooldownMs:number(process.env.SOOTIO_SOURCE_COOLDOWN_MS,120000,5000,900000),
});
export const run=runner.run;
export const stats=runner.stats;
