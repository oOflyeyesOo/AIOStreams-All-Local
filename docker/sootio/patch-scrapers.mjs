import fs from 'node:fs';
import {fileURLToPath} from 'node:url';

export function patchSource(source,moduleUrl='../util/bounded-curl.mjs'){
  if(source.includes('boundedExecPromise'))throw new Error('Sootio scraper source is already patched');
  let changed=0;
  for(const name of ['searchBtdig','searchMagnetDL','searchMagnetDLMovie']){
    const expression=new RegExp('(export async function '+name+'\\([^]*?)(?=\\nexport (?:async )?function |$)');
    const match=source.match(expression);
    if(!match||!match[0].includes('execPromise('))throw new Error('Unsupported Sootio scraper layout: '+name);
    source=source.replace(expression,text=>{
      let result=text.replace(/\bexecPromise\(/g,()=>{changed++;return 'boundedExecPromise(';});
      if(name==='searchBtdig'){
        const anchor='allPageResults.push(...batchResults);';
        if(!result.includes(anchor))throw new Error('Unsupported BTDig pagination layout');
        result=result.replace(anchor,anchor+'\n            if (batchResults.every(page => !page.html)) break;');
      }
      return result;
    });
  }
  if(changed<3)throw new Error('Sootio scraper hooks were not installed');
  return `import { run as boundedExecPromise } from '${moduleUrl}';\n`+source;
}

if(import.meta.url.startsWith('file:')&&process.argv[1]===fileURLToPath(import.meta.url)){
  const path=process.argv[2]||'/app/lib/common/scrapers.js';
  fs.writeFileSync(path,patchSource(fs.readFileSync(path,'utf8')));
}
