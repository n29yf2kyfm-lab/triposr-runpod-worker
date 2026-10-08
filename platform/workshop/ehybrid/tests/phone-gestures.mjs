import puppeteer from 'puppeteer-core';
const b = await puppeteer.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome', args: ['--no-sandbox','--use-gl=swiftshader','--enable-unsafe-swiftshader'], protocolTimeout: 600000 });
const p = await b.newPage(); await p.setViewport({ width: 390, height: 844, deviceScaleFactor: 1, isMobile: true, hasTouch: true });
p.on('pageerror', e => console.log('pageerror: '+e.message));
await p.goto('http://localhost:8765/index.html?debug', { waitUntil: 'domcontentloaded' });
await p.waitForFunction(() => window.__ws?.TRN, { timeout: 240000 });
await new Promise(r => setTimeout(r, 1500));
const cam = () => p.evaluate(() => { const w = window.__ws; return { y: +w.camera.position.y.toFixed(3), t: w.controls.target.toArray().map(v => +v.toFixed(2)), sheet: document.documentElement.style.getPropertyValue('--sheet-h') }; });
const drag = async (x0, y0, x1, y1, n = 12) => { await p.touchscreen.touchStart(x0, y0); for (let i = 1; i <= n; i++) { await p.touchscreen.touchMove(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n); await new Promise(r => setTimeout(r, 30)); } await p.touchscreen.touchEnd(); };
// open the card to its middle height first, so we can see it drop away while turning
await p.evaluate(() => window.__ws.W.sheet(1)); await new Promise(r => setTimeout(r, 400));
console.log('start', JSON.stringify(await cam()));
await p.touchscreen.touchStart(200, 400); for (let i = 1; i <= 10; i++) { await p.touchscreen.touchMove(200, 400 - i * 30); await new Promise(r => setTimeout(r, 30)); }
console.log('mid-drag (sheet should be small)', JSON.stringify(await cam()));
await p.touchscreen.touchEnd(); await new Promise(r => setTimeout(r, 1600));
console.log('after drag up (camera must stay above floor; sheet back)', JSON.stringify(await cam()));
for (let k = 0; k < 3; k++) await drag(200, 300, 200, 650);
await new Promise(r => setTimeout(r, 800)); console.log('after hard drags', JSON.stringify(await cam()));
// double-tap on the car
await p.evaluate(() => { const w = window.__ws; w.camera.position.set(4.6, 2.6, 4.8); w.controls.target.set(0, 0.55, 0.2); });
await new Promise(r => setTimeout(r, 600));
await p.touchscreen.tap(200, 560); await new Promise(r => setTimeout(r, 120)); await p.touchscreen.tap(200, 560);
await new Promise(r => setTimeout(r, 2500));
console.log('after double-tap on the car (target moves to the tapped point)', JSON.stringify(await cam()));
await p.touchscreen.tap(60, 200); await new Promise(r => setTimeout(r, 120)); await p.touchscreen.tap(60, 200);
await new Promise(r => setTimeout(r, 2500));
console.log('after double-tap on empty floor (back to the car)', JSON.stringify(await cam()));
// single tap selects
await p.touchscreen.tap(240, 600); await new Promise(r => setTimeout(r, 900));
console.log('single tap selected:', await p.evaluate(() => document.querySelector('#ce-name').textContent || '(nothing)'));
await p.screenshot({ path: '../m_after.png' });
await b.close();
