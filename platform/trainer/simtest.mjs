// Walks every simulator job end to end in headless Chromium, deliberately making
// one wrong move per job first, and checks the stage gate records it.
//   node simtest.mjs http://localhost:8765/manual.html OUT_DIR
import { chromium } from 'playwright';
const [, , url, out] = process.argv;
const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome', args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const p = await b.newPage({ viewport: { width: 1000, height: 760 }, ignoreHTTPSErrors: true });
// software GL draws the full car at well under 1 fps; a click waits for frames, so allow for it
p.setDefaultTimeout(180000);
const errs = []; p.on('pageerror', e => errs.push(e.message)); p.on('console', m => { if (m.type() === 'error') errs.push('console: ' + m.text()); });
const sleep = ms => p.waitForTimeout(ms);
const st = () => p.evaluate(() => ({ idx: __sim.run.idx, faults: __sim.run.faults, st: JSON.parse(JSON.stringify(__sim.run.st, (k, v) => v instanceof Set ? [...v] : v)), done: __sim.api.done }));
const click = async t => { await p.locator('#sim-panel button', { hasText: t.startsWith('^') ? new RegExp(t) : t }).first().click(); await sleep(150); };
const next = async () => { const s = await st(); if (!s.done) throw new Error('stage not passed: ' + s.idx + ' ' + await p.textContent('#sim-panel .fb')); await p.locator('#sim-panel .pf button').first().click(); await sleep(250); };
const ready = () => p.waitForSelector('#sim-panel .ph', { timeout: 90000 });
async function solveOrder(maxWait = 30000) {
  await ready();
  for (let guard = 0; guard < 60; guard++) {
    if ((await st()).done) return;
    const btns = p.locator('#sim-panel .opts .opt');
    const n = await btns.count();
    let progressed = false;
    for (let i = 0; i < n; i++) {
      const before = (await st()).faults;
      const bt = btns.nth(i); if (!(await bt.isVisible())) continue;
      const txt = await bt.textContent();
      await bt.click(); await sleep(80);
      const after = (await st()).faults;
      if (after === before) { // accepted: wait for its animation to finish
        const t0 = Date.now(); while (await p.evaluate(() => __sim.api.busy) && Date.now() - t0 < maxWait) await sleep(200);
        progressed = true; break;
      }
      if (await btns.count() !== n) { progressed = true; break; }   // a trap was removed: indexes shifted, rescan
    }
    if (!progressed) throw new Error('order stage stuck');
  }
}
const report = [];
async function job(id, fn) {
  await p.goto(url + '#sim-' + id);
  await p.waitForFunction(() => window.__sim && window.__sim.run, null, { timeout: 60000 }); await sleep(600);
  const title = await p.textContent('#sim-title');
  await fn();
  const s = await st(); const txt = await p.textContent('#sim-panel h2');
  report.push(`${id}: "${title}" -> ${txt} | faults recorded ${s.faults}`);
}
await p.goto(url + '#sim'); await sleep(2500);
await p.screenshot({ path: out + '/home.png', fullPage: true, timeout: 180000 });

await job('misfire', async () => {
  await solveOrder(); await p.screenshot({ path: out + '/car-bonnet.png', timeout: 180000 }); await next(); await ready();
  await click('Start engine'); await click('Live data'); await sleep(3500);
  let s = await st(); const wrong = s.st.cyl % 4 + 1;
  await click('Cylinder ' + wrong);                  // deliberate wrong answer
  await click('Cylinder ' + s.st.cyl); await p.screenshot({ path: out + '/misfire1.png', timeout: 180000 }); await next();
  s = await st();
  if (s.st.cause === 'coil') { await click('Swap the coil'); await sleep(7000); await click('Ignition coil'); }
  if (s.st.cause === 'plug') { await click('Remove and inspect'); await sleep(7000); await click('^Spark plug$'); }
  if (s.st.cause === 'injector') { await click('Injector balance'); await click('^Injector$'); }
  await p.screenshot({ path: out + '/misfire2.png', timeout: 180000 }); await next();
  await solveOrder(); await next();
  await click('Clear fault'); await click('Run at idle'); await sleep(2300); await click('Road test'); await sleep(1800); await next();
  console.log('misfire cause', s.st.cause, 'cyl', s.st.cyl);
});
await job('starter', async () => {
  await solveOrder(); await next(); await ready();
  await click('Turn key'); await sleep(3200); await click('The solenoid plunger'); await next();
  await click('Starter faulty');                     // no evidence yet: must be refused
  await click('Terminal 30'); await sleep(1300); await click('Terminal 50'); await sleep(1300);
  await click('Starter faulty'); await p.screenshot({ path: out + '/starter2.png', timeout: 180000 }); await next();
  await solveOrder(); await p.screenshot({ path: out + '/starter3.png', timeout: 180000 }); await next();
  await solveOrder(); await next();
});
await job('alternator', async () => {
  await solveOrder(); await next(); await ready();
  await click('Real part'); await sleep(1500); await p.screenshot({ path: out + '/alt-real.png', timeout: 180000 }); await click('Cutaway');
  await click('Start engine'); await p.locator('#sim-panel .chip').first().click(); await sleep(800);
  await p.screenshot({ path: out + '/alt1.png', timeout: 180000 });
  await click('In the stator'); await next();
  let s = await st();
  if (!s.st.running) await click('Start engine');
  await click('B+ stud');                            // reading with no evidence set yet
  await click('Nothing wrong');                      // wrong: refused, no evidence
  await click('DC volts'); await click('battery posts'); await click('B+ stud'); await click('AC volts'); await click('B+ stud');
  const map = { brushes: 'No field', diode: 'Rectifier diode', cable: 'High resistance' };
  await click(map[s.st.fault]); await p.screenshot({ path: out + '/alt2.png', timeout: 180000 }); await next();
  await solveOrder(); await next();
  await click('Start engine');
  if (await p.locator('#sim-panel .chip').first().getAttribute('aria-pressed') !== 'true') await p.locator('#sim-panel .chip').first().click();
  await click('DC volts'); await click('battery posts'); await click('AC volts'); await click('B+ stud'); await next();
  console.log('alternator fault', s.st.fault);
});
await job('brakes', async () => {
  await solveOrder(); await sleep(1200); await p.screenshot({ path: out + '/car-brake.png', timeout: 180000 }); await next();
  await click('Pad gauge'); await click('Vernier'); await click('New pads and discs');   // refused: vernier only
  await click('point A'); await click('point B'); await click('point C');
  const s = await st(); await click(s.st.worn ? 'New pads and discs' : 'New pads only'); await next();
  await solveOrder(); await p.screenshot({ path: out + '/brakes3.png', timeout: 180000 }); await next();
  await solveOrder(); await next();
  await solveOrder(); await next();
  const pent = p.locator('#sim-panel .pent button');
  await pent.nth(0).click(); await pent.nth(1).click();                                   // next bolt round: refused
  for (const k of [0, 2, 4, 1, 3]) { await pent.nth(k).click(); await sleep(60); }
  await p.screenshot({ path: out + '/brakes6.png', timeout: 180000 }); await next();
  await click('Pump the pedal'); await next();
  console.log('brakes worn disc', s.st.worn);
});
await job('airbag', async () => {
  await solveOrder(15000); await p.screenshot({ path: out + '/car-door.png', timeout: 180000 }); await next();
  await solveOrder(); await p.screenshot({ path: out + '/airbag2.png', timeout: 180000 }); await next();
  await solveOrder(); await next();
});
await p.screenshot({ path: out + '/report.png', timeout: 180000 });
await p.goto(url + '#sim'); await sleep(800); await p.screenshot({ path: out + '/home2.png', fullPage: true, timeout: 180000 });
const m = await b.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, colorScheme: 'dark', ignoreHTTPSErrors: true });
await m.goto(url + '#sim-brakes'); await m.waitForTimeout(2500); await m.screenshot({ path: out + '/mobile.png', fullPage: true, timeout: 180000 });
const sw = await m.evaluate(() => document.documentElement.scrollWidth); if (sw > 390) errs.push('mobile overflow ' + sw);
console.log(report.join('\n'));
console.log(errs.length ? 'ERRORS:\n' + errs.join('\n') : 'NO PAGE ERRORS');
await b.close();
