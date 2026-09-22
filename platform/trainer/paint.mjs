/* Does a respray paint the BODY and only the body? Asserts the paint list
   is non-empty and names the parts it reaches, then screenshots Original vs
   Blue from the same camera so the glass and tyres can be LOOKED at. */
import puppeteer from 'puppeteer-core';
import http from 'node:http'; import fs from 'node:fs'; import path from 'node:path';
const ROOT=process.argv[2], OUT=process.argv[3], CAR=process.argv[4];
const MIME={'.html':'text/html','.js':'text/javascript','.wasm':'application/wasm'};
const srv=http.createServer((q,s)=>{ const u=decodeURIComponent(q.url.split('?')[0]);
  const f=path.join(ROOT,u==='/'?'golf-bay.html':u);
  if(!fs.existsSync(f)||fs.statSync(f).isDirectory()){s.writeHead(404);return s.end()}
  s.writeHead(200,{'Content-Type':MIME[path.extname(f)]||'application/octet-stream','Content-Length':fs.statSync(f).size});
  fs.createReadStream(f).pipe(s)});
await new Promise(r=>srv.listen(9022,'127.0.0.1',r));
const b=await puppeteer.launch({executablePath:'/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
  headless:true,protocolTimeout:0,args:['--no-sandbox','--disable-dev-shm-usage','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const p=await b.newPage(); await p.setViewport({width:1100,height:760});
const errs=[]; p.on('pageerror',e=>errs.push(e.message));
await p.goto(`http://127.0.0.1:9022/?car=${CAR}`,{waitUntil:'load',timeout:120000});
await p.waitForFunction(()=>window.__carReady===true,{timeout:300000,polling:500});
await p.evaluate(()=>{window.__f=0;const c=()=>{window.__f++;requestAnimationFrame(c)};requestAnimationFrame(c)});
const frames=async n=>{const f0=await p.evaluate(()=>window.__f);
  await p.waitForFunction(t=>window.__f>t,{timeout:180000,polling:300},f0+n);};
await frames(8);
const info=await p.evaluate(()=>window.__paint()); console.log(CAR, JSON.stringify(info));
const shot=async(tag,t,c)=>{ await p.evaluate((t,c)=>window.__fly(t,c),t,c); await frames(4);
  await p.screenshot({path:`${OUT}/PAINT_${CAR}_${tag}.png`}); };
const T=[0,.7,0], C=[4.6,1.9,5.2];
await shot('orig',T,C);
await p.evaluate(()=>window.__setPaint(0x163f8c)); await frames(4); await shot('blue',T,C);
await p.evaluate(()=>window.__setPaint(0xa3141c)); await frames(4); await shot('red',T,C);
await p.evaluate(()=>window.__setPaint(null)); await frames(4);
const back=await p.evaluate(()=>window.__paint().paint); console.log('restored paint =',back);
console.log('errors',errs.length?errs:'none');
await b.close(); srv.close();
