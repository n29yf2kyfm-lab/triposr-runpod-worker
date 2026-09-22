/* One car, the owner's checklist, asserted on STATE then shown for the eye:
   doors / bonnet / boot / wheel move, paint list non-empty, then two
   screenshots with everything open and the body resprayed blue. */
import puppeteer from 'puppeteer-core';
import http from 'node:http'; import fs from 'node:fs'; import path from 'node:path';
const ROOT=process.argv[2], OUT=process.argv[3], CAR=process.argv[4], PORT=9030+Math.floor(Math.random()*400);
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
const errs=[]; p.on('pageerror',e=>errs.push(e.message));
const res={car:CAR,fails:[]};
try{
await p.goto(`http://127.0.0.1:${PORT}/?car=${CAR}`,{waitUntil:'load',timeout:120000});
await p.waitForFunction(()=>window.__carReady===true,{timeout:300000,polling:500});
await p.evaluate(()=>{window.__f=0;const c=()=>{window.__f++;requestAnimationFrame(c)};requestAnimationFrame(c)});
const frames=async n=>{const f0=await p.evaluate(()=>window.__f);
  await p.waitForFunction(t=>window.__f>t,{timeout:180000,polling:300},f0+n);};
await frames(6);
const g=await p.evaluate(()=>window.__groups()); res.groups=Object.keys(g).sort();
res.paint=await p.evaluate(()=>window.__paint());
const xf=id=>p.evaluate(i=>{const q=window.__part(i);return q&&[...q.pos,...q.rot]},id);
const acts=[['door_fl',()=>window.__act('door','fl')],['door_fr',()=>window.__act('door','fr')],
  ['door_rl',()=>window.__act('door','rl')],['door_rr',()=>window.__act('door','rr')],
  ['panel_bonnet',()=>window.__act('bonnet')],['tailgate',()=>window.__act('tail')],
  ['wheel_fl',()=>window.__act('wheel','fl')]];
res.moved={}; const before={};
for(const [id,f] of acts){ before[id]=await xf(id); if(before[id]) await p.evaluate(f); }
await frames(12); await p.waitForFunction(()=>window.__door().anims===0,{timeout:120000,polling:500}).catch(()=>{});
for(const [id] of acts){ const a=before[id]; if(!a){res.moved[id]='ABSENT';continue}
  const z=await xf(id); const d=z.reduce((s,v,i)=>s+Math.abs(v-a[i]),0);
  res.moved[id]=d>0.05?'moved':'STUCK'; if(d<=0.05) res.fails.push(id+' stuck'); }
await p.evaluate(()=>window.__setPaint(0x163f8c)); await frames(4);
await p.evaluate(()=>window.__fly([0,.65,0],[4.2,2.0,5.0])); await frames(4);
await p.screenshot({path:`${OUT}/CHK_${CAR}_a.png`});
await p.evaluate(()=>window.__fly([0,.65,0],[3.6,2.4,-5.2])); await frames(4);
await p.screenshot({path:`${OUT}/CHK_${CAR}_b.png`});
}catch(e){res.fails.push(String(e).slice(0,160))}
res.errors=errs.slice(0,3);
fs.writeFileSync(`${OUT}/chk_${CAR}.json`,JSON.stringify(res,null,1));
console.log(JSON.stringify({car:CAR,groups:res.groups?.length,moved:res.moved,paint:res.paint?.parts,fails:res.fails,errors:res.errors}));
await b.close(); srv.close();
