import puppeteer from 'puppeteer-core';
import http from 'node:http'; import fs from 'node:fs'; import path from 'node:path';
const ROOT=process.argv[2];
const MIME={'.html':'text/html','.glb':'model/gltf-binary','.js':'text/javascript'};
const srv=http.createServer((q,s)=>{const f=path.join(ROOT,q.url==='/'?'golf-bay.html':decodeURIComponent(q.url.split('?')[0]));
  if(!fs.existsSync(f)){s.writeHead(404);return s.end()}
  s.writeHead(200,{'Content-Type':MIME[path.extname(f)]||'application/octet-stream','Content-Length':fs.statSync(f).size});
  fs.createReadStream(f).pipe(s)});
await new Promise(r=>srv.listen(8932,'127.0.0.1',r));
const b=await puppeteer.launch({executablePath:'/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
  headless:true,args:['--no-sandbox','--disable-dev-shm-usage','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const p=await b.newPage(); await p.setViewport({width:1200,height:800});
const errs=[]; p.on('pageerror',e=>errs.push(e.message));
await p.goto('http://127.0.0.1:8932/',{waitUntil:'load'});
await p.waitForFunction(()=>window.__carReady===true,{timeout:300000,polling:500});
const step=async(label,fn)=>{ await fn(); await new Promise(r=>setTimeout(r,1200));
  console.log(label.padEnd(26), JSON.stringify(await p.evaluate(()=>window.__dbg()))); };
await step('after load', async()=>{});
await step('click panel FL door', async()=>{
  const found=await p.evaluate(()=>{const el=document.querySelector('[data-x="door:fl"]');
    if(!el) return 'SELECTOR NOT FOUND'; el.click(); return el.outerHTML.slice(0,60)});
  console.log('   selector ->', found); });
await step('click panel wheel FL', async()=>{
  await p.evaluate(()=>document.querySelector('[data-x="wheel:fl"]')?.click()); });
await step('click panel tailgate', async()=>{
  await p.evaluate(()=>document.querySelector('[data-x="tail"]')?.click()); });
await step('click HUD all doors', async()=>{
  await p.evaluate(()=>document.querySelector('[data-a="alldoors"]')?.click()); });
console.log('pageerrors:', errs.length ? errs : 'none');
await b.close(); srv.close();
