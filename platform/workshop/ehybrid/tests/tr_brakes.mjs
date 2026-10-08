import puppeteer from 'puppeteer-core';
const b = await puppeteer.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome', args: ['--no-sandbox','--use-gl=swiftshader','--enable-unsafe-swiftshader'], protocolTimeout: 900000 });
const p = await b.newPage(); await p.setViewport({ width: 1280, height: 800 }); await p.emulateMediaFeatures([{name:'prefers-reduced-motion',value:'reduce'}]);
p.on('pageerror', e => console.log('pageerror: '+e.message)); p.on('console', m => { if (m.type()==='error' && !/404|CERT/.test(m.text())) console.log('console: '+m.text()); });
await p.goto('http://localhost:8765/index.html?debug', { waitUntil: 'domcontentloaded' });
await p.waitForFunction(() => window.__ws?.TRN, { timeout: 240000 });
const out = await p.evaluate(async () => {
  const w = window.__ws, $ = s => document.querySelector(s), card = () => $('#card-train'), log = [];
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const opt = t => [...card().querySelectorAll('.opt')].find(x => x.textContent.includes(t));
  const clickOpt = async t => { const x = opt(t); if (!x) throw new Error('no option: ' + t); x.click(); await sleep(60); };
  const next = async () => { const x = [...card().querySelectorAll('.btn.pri')].find(x => /Next stage|Finish/.test(x.textContent)); if (!x) throw new Error('no next at ' + card().querySelector('h2')?.textContent + ' | ' + card().querySelector('.fb')?.textContent); x.click(); await sleep(80); };
  const tool = k => $(`.tool[data-tool="${k}"]`).click();
  const sel = id => { w.select(id, false, true); w.TRN.changed(); };
  const selBtn = t => { const x = [...card().querySelectorAll('.trsel button')].find(x => x.textContent.includes(t)); if (!x) throw new Error('no sel button ' + t + ' on ' + w.W.selectedPart()?.id); x.click(); };
  const tq = n => { const i = $('#tqn'); i.value = n; i.dispatchEvent(new Event('input')); };
  const ang = d => { const s = $('#ang'); s.value = String(d); s.dispatchEvent(new Event('change')); };
  const fasten = (id, k, nm, deg) => { sel(id); selBtn('Fit'); tool(k); selBtn('on all'); tool('tq'); tq(nm); selBtn('on all'); if (deg) { tool('ang'); ang(deg); selBtn('on all'); } };
  const undo = (id, k) => { sel(id); tool(k); selBtn('on all'); };
  w.setMode('train'); w.TRN.open('brakes'); const st = w.TRN.run.st;
  log.push('conditions: worn=' + st.worn + ' pad=' + st.pad);
  // 1 lift: a trap and an early step, then the right order
  await clickOpt('floor pan'); await clickOpt('Lift arms'); await clickOpt('Slacken'); await clickOpt('Lift arms'); await clickOpt('Raise it'); await sleep(1500); await next();
  // 2 wheel off: wrong socket, and a part outside the job
  sel('fix_wheel_fl'); tool('s13'); selBtn('on all'); tool('s17'); selBtn('on all'); sel('caliper_fl'); selBtn('Take it off'); sel('wheel_fl'); selBtn('Take it off'); await next();
  // 3 measure and decide
  await clickOpt('Pad gauge'); for (const c of ['A', 'B', 'C']) await clickOpt('Micrometer, point ' + c); await clickOpt(st.worn ? 'New pads and discs' : 'New pads, the discs stay'); await next();
  // 4 caliper
  undo('bolts_caliper_fl', 's13'); sel('caliper_fl'); selBtn('Take it off'); await next();
  await clickOpt('Hung from the spring'); await next();
  // 6 pads (and disc)
  sel('pads_fl'); selBtn('Take it off'); if (st.disc) { undo('bolts_carrier_fl', 's21'); sel('carrier_fl'); selBtn('Take it off'); undo('screw_disc_fl', 't30'); sel('disc_fl'); selBtn('Take it off'); } await next();
  await clickOpt(st.disc ? 'Clean the hub face' : 'Check the fluid level'); await next();
  // 8 refit, with one over-torque
  if (st.disc) { sel('disc_fl'); selBtn('Put it back'); fasten('screw_disc_fl', 't30', 4.5); sel('carrier_fl'); selBtn('Put it back'); fasten('bolts_carrier_fl', 's21', 200); }
  sel('pads_fl'); selBtn('Put it back'); sel('caliper_fl'); selBtn('Put it back');
  sel('bolts_caliper_fl'); selBtn('Fit'); tool('s13'); selBtn('on all'); tool('tq'); tq(40); selBtn('on all'); tq(35); selBtn('on all');
  sel('wheel_fl'); selBtn('Put it back'); fasten('fix_wheel_fl', 's17', 120); await next();
  // 9 star, 10 quiz
  for (const k of [0, 2, 4, 1, 3]) card().querySelectorAll('.pent button')[k].click(); await next();
  await clickOpt('Pump the pedal'); await next();
  log.push('report: ' + card().querySelector('h2').textContent);
  log.push(...[...card().querySelectorAll('.log li')].map(li => ' - ' + li.textContent));
  log.push('removed left on car: ' + w.parts.filter(q => q.removed).length + ' | progress: ' + localStorage.getItem('ehy-training-progress'));
  return log.join('\n');
});
console.log(out);
await p.screenshot({ path: '../t_report.png' });
await b.close();
