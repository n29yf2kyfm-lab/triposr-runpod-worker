/* engine + suspension, LOOKED at: bonnet up and x-ray on, then from low
   at the side with a wheel off. Prints the measured sizes it fitted to. */
import puppeteer from 'puppeteer-core';
import http from 'node:http'; import fs from 'node:fs'; import path from 'node:path';
const ROOT=process.argv[2], OUT=process.argv[3], CAR=process.argv[4], PORT=9500+Math.floor(Math.random()*400);
const MIME={'.html':'text/html','.js':'text/javascript','.wasm':'application/wasm'};
const srv=http.createServer((q,s)=>{ const u=decodeURIComponent(q.url.split('?')[0]);
  const f=path.join(ROOT,u==='/'?'golf-bay.html':u);
  if(!fs.existsSync(f)||fs.statSync(f).isDirectory()){s.writeHead(404);return s.end()}
  s.writeHead(200,{'Content-Type':MIME[path.extname(f)]||'application/octet-stream','Content-Length':fs.statSync(f).size});
  fs.createReadStream(f).pipe(s)});
await new Promise(r=>srv.listen(PORT,'127.0.0.1',r));
const b=await puppeteer.launch({executablePath:'/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
  headless:true,protocolTimeout:0,args:['--no-sandbox','--disable-dev-shm-usage','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const p=await b.newPage(); await p.setViewport({width:1400,height:820});
const errs=[]; p.on('pageerror',e=>errs.push(e.message)); p.on('console',m=>{if(m.type()==='error')errs.push(m.text())});
await p.goto(`http://127.0.0.1:${PORT}/?car=${CAR}`,{waitUntil:'load',timeout:120000});
await p.waitForFunction(()=>window.__carReady===true,{timeout:300000,polling:500});
await p.evaluate(()=>{window.__f=0;const c=()=>{window.__f++;requestAnimationFrame(c)};requestAnimationFrame(c)});
const frames=async n=>{const f0=await p.evaluate(()=>window.__f);
  await p.waitForFunction(t=>window.__f>t,{timeout:180000,polling:300},f0+n);};
await frames(6);
console.log(CAR, JSON.stringify(await p.evaluate(()=>window.__ptInfo)));
await p.evaluate(()=>{window.__act('bonnet'); window.__act('wheel','fl');}); await frames(14);
await p.evaluate(()=>window.__fly([0,.6,1.0],[2.2,2.3,3.6])); await frames(4);
await p.screenshot({path:`${OUT}/PT_${CAR}_bay.png`});
await p.evaluate(()=>window.__setXray(true)); await p.evaluate(()=>window.__fly([0,.45,0],[4.6,1.0,1.2])); await frames(4);
await p.screenshot({path:`${OUT}/PT_${CAR}_xray.png`});
console.log('errors', errs.filter(e=>!/fonts|alt\.glb|404/.test(e)).slice(0,3));
await b.close(); srv.close();
