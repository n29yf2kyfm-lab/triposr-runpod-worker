import puppeteer from 'puppeteer-core';
// node view.mjs W H out1:query1 out2:query2 ...  (shots of the same file share one page load)
const [,, W, H, ...shots] = process.argv;
const port = process.env.VIEW_PORT || 8790;
const b = await puppeteer.launch({ executablePath: process.env.CHROME_PATH || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome', args: ['--no-sandbox', '--use-gl=swiftshader', '--enable-unsafe-swiftshader'] });
let p = null, file = null;
for (const s of shots) {
  const i = s.indexOf(':'); const out = s.slice(0, i), qs = s.slice(i + 1);
  const f = new URLSearchParams(qs).get('f');
  if (f !== file) {
    if (p) await p.close();
    p = await b.newPage(); await p.setViewport({ width: +W, height: +H });
    p.on('pageerror', e => console.log('pageerror: ' + e.message));
    await p.goto(`http://localhost:${port}/index.html?` + qs, { waitUntil: 'domcontentloaded' });
    await p.waitForFunction(() => window.__done, { timeout: 240000 });
    file = f;
  } else {
    await p.evaluate(q => window.__apply(q), '?' + qs);
  }
  await p.screenshot({ path: out }); console.log('wrote', out);
}
await b.close();
