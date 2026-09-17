import puppeteer from 'puppeteer-core';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';

const ROOT = process.argv[2], SHOT = process.argv[3];
const MIME = {'.html':'text/html','.glb':'model/gltf-binary','.wasm':'application/wasm','.js':'text/javascript',
              '.png':'image/png','.json':'application/json'};
const srv = http.createServer((q,s)=>{
  const f = path.join(ROOT, q.url === '/' ? 'golf-bay.html' : decodeURIComponent(q.url.split('?')[0]));
  if (!fs.existsSync(f)) { s.writeHead(404); return s.end('nope'); }
  s.writeHead(200, {'Content-Type': MIME[path.extname(f)] || 'application/octet-stream',
                    'Content-Length': fs.statSync(f).size});
  fs.createReadStream(f).pipe(s);
});
await new Promise(r => srv.listen(8931, '127.0.0.1', r));

const b = await puppeteer.launch({
  executablePath:'/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
  headless:true,
  args:['--no-sandbox','--disable-dev-shm-usage','--use-gl=angle','--use-angle=swiftshader',
        '--enable-unsafe-swiftshader','--window-size=1440,900']
});
const p = await b.newPage();
await p.setViewport({width:1440,height:900,deviceScaleFactor:1});
const errs=[], logs=[];
p.on('console', m => { const t=m.text();
  if (m.type()==='error') errs.push('CONSOLE '+t); else logs.push(m.type()+': '+t); });
p.on('pageerror', e => errs.push('PAGEERROR '+e.message));
p.on('requestfailed', r => errs.push('REQFAIL '+r.url().slice(0,90)+' :: '+r.failure()?.errorText));

await p.goto('http://127.0.0.1:8931/', {waitUntil:'load', timeout:90000});

// wait for the car to finish loading (the overlay hides when carReady)
const t0=Date.now();
const ready = await p.waitForFunction(
  () => window.__carReady === true ||
        /not loaded/i.test(document.getElementById('loading').textContent),
  {timeout:420000, polling:1000}).then(()=>true).catch(()=>false);
const loadSecs = ((Date.now()-t0)/1000).toFixed(1);

const state = await p.evaluate(() => ({
  title: document.title,
  tabs: [...document.querySelectorAll('.tab')].map(t=>t.textContent),
  loadingHidden: document.getElementById('loading').hidden,
  loadingText: document.getElementById('loading').textContent.trim().slice(0,120),
  canvasOK: (()=>{const c=document.getElementById('c'); return c.width>0&&c.height>0})(),
  carReady: window.__carReady===true,
  loadingHiddenComputed: getComputedStyle(document.getElementById('loading')).display,
  panelLen: document.getElementById('panel').innerHTML.length
}));

const bays=['strip','door','starter','engine','brakes','bench'];
if(!state.tabs.length) errs.push('FATAL: no tabs rendered — module script never ran');
const shots={};
for (const m of bays){
  const okTab = await p.evaluate(x=>{const b=document.querySelector(`[data-m="${x}"]`);
    if(!b) return false; b.click(); return true}, m);
  if(!okTab){ errs.push('NO TAB '+m); continue; }
  await new Promise(r=>setTimeout(r,2600));
  const f=`${SHOT}/${m}.png`;
  await p.screenshot({path:f});
  shots[m]=await p.evaluate(()=>({
    panel:document.getElementById('panel').innerHTML.length,
    manuals:document.querySelectorAll('details.manual').length,
    hud:document.querySelectorAll('#hud .chip').length,
    caption:document.getElementById('caption').hidden?null:document.getElementById('caption').textContent
  }));
}
// exercise the interactions that could throw
await p.evaluate(()=>document.querySelector('[data-m="strip"]').click());
await new Promise(r=>setTimeout(r,600));
for (const sel of ['[data-x="door:fl"]','[data-x="wheel:fl"]','[data-x="tail"]']){
  await p.evaluate(s=>document.querySelector(s)?.click(), sel);
  await new Promise(r=>setTimeout(r,900));
}
await p.screenshot({path:`${SHOT}/strip_opened.png`});
await p.evaluate(()=>document.querySelector('[data-a="xray"]')?.click());
await new Promise(r=>setTimeout(r,1400));
await p.screenshot({path:`${SHOT}/strip_xray.png`});
await p.evaluate(()=>document.querySelector('[data-a="xray"]')?.click());
await p.evaluate(()=>document.querySelector('[data-a="explode"]')?.click());
await new Promise(r=>setTimeout(r,1400));
await p.screenshot({path:`${SHOT}/strip_exploded.png`});
await p.evaluate(()=>document.querySelector('[data-a="reset"]')?.click());
await new Promise(r=>setTimeout(r,900));
await p.screenshot({path:`${SHOT}/strip_after_reset.png`});
await p.evaluate(()=>document.querySelector('[data-m="door"]').click());
await new Promise(r=>setTimeout(r,500));
await p.evaluate(()=>{const s=document.querySelector('[data-x="win"]'); if(s){s.value=70;
  s.dispatchEvent(new Event('input',{bubbles:true}))}});
await p.evaluate(()=>document.querySelector('[data-x="dcard"]')?.click());
await new Promise(r=>setTimeout(r,900));
await p.screenshot({path:`${SHOT}/door_open.png`});
await p.evaluate(()=>document.querySelector('[data-m="starter"]').click());
await new Promise(r=>setTimeout(r,400));
await p.evaluate(()=>document.querySelector('[data-x="skey"]')?.click());
await new Promise(r=>setTimeout(r,1800));
await p.screenshot({path:`${SHOT}/starter_cranking.png`});
await p.evaluate(()=>document.querySelector('[data-m="bench"]').click());
await new Promise(r=>setTimeout(r,400));
await p.evaluate(()=>{document.querySelector('[data-x="ign:2"]')?.click();});
await p.evaluate(()=>{document.querySelector('[data-x="lamps"]')?.click();});
await p.evaluate(()=>{document.querySelector('[data-x="fault:earth"]')?.click();});
await new Promise(r=>setTimeout(r,700));
await p.screenshot({path:`${SHOT}/bench_earth_fault.png`});
const bench = await p.evaluate(()=>document.getElementById('panel').textContent.match(/Earth volt drop[\s\S]{0,40}/)?.[0]);

console.log(JSON.stringify({ready,loadSecs,state,shots,bench,errors:errs,
  warnSample:logs.filter(l=>/warn/i.test(l)).slice(0,6)}, null, 1));
await b.close(); srv.close();
