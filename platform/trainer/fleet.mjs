/* Does the SECOND CAR actually come apart?
   Asserts on STATE and on MOVEMENT, never on a screenshot — this app has
   already shipped a version where every teardown action hit `if(!p) return`
   and the render looked flawless.
   For each of doors / bonnet / tailgate / wheels / interior it checks the
   part EXISTS, then MOVES it and requires the transform to change. */
import puppeteer from 'puppeteer-core';
import http from 'node:http'; import fs from 'node:fs'; import path from 'node:path';
const ROOT=process.argv[2], OUT=process.argv[3], CAR=process.argv[4]||'xc90';
const MIME={'.html':'text/html','.js':'text/javascript','.wasm':'application/wasm','.png':'image/png'};
const srv=http.createServer((q,s)=>{
  /* STRIP THE QUERY FIRST. `?car=xc90` is the whole point of this harness
     and the old line tested `q.url==='/'` BEFORE removing it, so the page
     request fell through to serving the ROOT DIRECTORY and 404'd. The app
     never loaded, __carReady never appeared, and the run hung for ten
     minutes with no output looking exactly like a broken app. */
  const u=decodeURIComponent(q.url.split('?')[0]);
  const f=path.join(ROOT, u==='/'?'golf-bay.html':u);
  if(!fs.existsSync(f)||fs.statSync(f).isDirectory()){s.writeHead(404);return s.end()}
  s.writeHead(200,{'Content-Type':MIME[path.extname(f)]||'application/octet-stream',
                   'Content-Length':fs.statSync(f).size});
  fs.createReadStream(f).pipe(s)});
await new Promise(r=>srv.listen(9021,'127.0.0.1',r));
const b=await puppeteer.launch({executablePath:'/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
  headless:true,protocolTimeout:0,args:['--no-sandbox','--disable-dev-shm-usage',
  '--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const p=await b.newPage();
await p.setViewport({width:1440,height:900,deviceScaleFactor:1});
const errs=[],info=[];
p.on('console',m=>{ const t=m.text();
  if(m.type()==='error') errs.push('CONSOLE '+t); else if(/\[fleet\]/.test(t)) info.push(t); });
p.on('pageerror',e=>errs.push('PAGEERROR '+e.message));
p.on('requestfailed',r=>{ if(!/fonts\.googleapis/.test(r.url())) errs.push('REQFAIL '+r.url().slice(0,70)); });

const fails=[]; const ok=(c,m)=>{ if(!c) fails.push(m); return c; };
const wait=ms=>new Promise(r=>setTimeout(r,ms));
await p.goto(`http://127.0.0.1:9021/?car=${CAR}`,{waitUntil:'load',timeout:120000});
await p.waitForFunction(()=>window.__carReady===true,{timeout:300000,polling:500});
/* rAF can sit dead for >10s under swiftshader, and every tween below needs
   frames to run — so wait for real frames, never for wall time */
await p.evaluate(()=>{window.__f=0;const c=()=>{window.__f++;requestAnimationFrame(c)};requestAnimationFrame(c)});
await p.waitForFunction(()=>window.__f>10,{timeout:180000,polling:300}).catch(()=>fails.push('rAF never started'));

const out={car:CAR};
out.groups = await p.evaluate(()=>window.__groups());
const ids = Object.keys(out.groups);
out.partIds = ids.length;
console.log(`\n${CAR}: ${ids.length} part groups`);
for (const id of ids.sort()) console.log(`   ${id.padEnd(18)} ${String(out.groups[id].meshes).padStart(4)} meshes  ${String(out.groups[id].tris).padStart(7)} tris`);

/* ── the six things the owner asked for ── */
for (const d of ['door_fl','door_fr','door_rl','door_rr'])
  ok(ids.includes(d), `missing ${d}`);
ok(ids.includes('panel_bonnet')||ids.includes('hood'), 'missing bonnet');
ok(ids.includes('tailgate'), 'missing tailgate');
for (const w of ['wheel_fl','wheel_fr','wheel_rl','wheel_rr'])
  ok(ids.includes(w), `missing ${w}`);
ok(ids.includes('cabin')||ids.includes('seats'), 'missing interior');
ok(ids.includes('glazing'), 'missing glazing');

/* helper: read a part's live world transform */
const xf = id => p.evaluate(i=>{ const g=window.__part(i); return g&&
  {pos:g.pos, rot:g.rot}; }, id);

/* NEVER WAIT A FIXED TIME FOR A TWEEN. Measured here: rAF fires at about
   ONE FRAME PER SECOND under software rendering, so a 640 ms door tween
   takes ~3.6 s of wall clock. A 2.5 s wait read three parts as STUCK on a
   car that was working perfectly — the same wall-clock trap this repo
   already documented in clcool.mjs, walked into again. Poll for the
   CHANGE, with a long ceiling, and fail only if it never arrives. */
async function moves(id, act, label){
  const before = await xf(id);
  if (!before) { fails.push(`${label}: no part ${id}`); return; }
  await p.evaluate(act);
  let after = before, d = 0;
  const t0 = Date.now();
  while (Date.now() - t0 < 90000){
    await wait(800);
    after = await xf(id);
    d = Math.abs(after.pos[0]-before.pos[0])+Math.abs(after.pos[1]-before.pos[1])
      + Math.abs(after.pos[2]-before.pos[2])
      + Math.abs(after.rot[0]-before.rot[0])+Math.abs(after.rot[1]-before.rot[1])
      + Math.abs(after.rot[2]-before.rot[2]);
    if (d > 0.05){
      /* let it finish so the number reported is the settled one */
      await p.waitForFunction(()=>window.__door().anims===0,{timeout:60000,polling:400}).catch(()=>{});
      after = await xf(id);
      break;
    }
  }
  out[label]={before,after,delta:+d.toFixed(4),secs:+((Date.now()-t0)/1000).toFixed(1)};
  ok(d>0.05, `${label}: ${id} did not move in 90s (delta ${d.toFixed(4)})`);
  console.log(`   ${label.padEnd(22)} ${id.padEnd(13)} delta ${d.toFixed(3)}  ${d>0.05?'MOVED':'STUCK'}  after ${out[label].secs}s`);
}
console.log('\nactions:');
await moves('door_fl', ()=>window.__act('door','fl'), 'door opens');
await moves('door_rr', ()=>window.__act('door','rr'), 'rear door opens');
await moves('panel_bonnet', ()=>window.__act('bonnet'), 'bonnet up');
await moves('tailgate', ()=>window.__act('tail'), 'tailgate up');
await moves('wheel_fl', ()=>window.__act('wheel','fl'), 'wheel comes off');

await p.screenshot({path:`${OUT}/FLEET_${CAR}_open.png`});
await p.evaluate(()=>window.__act('iso',['cabin','seats','steering','glazing','body']));
await wait(2000);
await p.screenshot({path:`${OUT}/FLEET_${CAR}_interior.png`});

console.log('\nfleet log:', info.join(' | ')||'(none)');
console.log('errors:', errs.length?errs:'none');
console.log(fails.length? `\nFAILED ${fails.length}:\n  `+fails.join('\n  ') : '\nALL PASS');
fs.writeFileSync(`${OUT}/fleet_${CAR}.json`, JSON.stringify({out,fails,errs,info},null,1));
await b.close(); srv.close();
