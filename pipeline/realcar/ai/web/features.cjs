// features.cjs: the phone page's own reading of every picture (the encoder's numbers and the colour
// histogram), made in a real browser (Chromium, with Playwright) by the page's code and engine.
//   node features.cjs URL LIST.json OUT.jsonl [CDN_DIR] [PAGES]
// LIST.json: picture paths under URL. One line a picture: {"path", "e", "ef", "h"} or {"path", "error"}.
// The heads for the page are trained on these (web/features.py), so the page answers on the very kind of
// numbers it learned from: its engine's 8-bit arithmetic is not quite the Python one's.
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

(async () => {
  const [url, listFile, outFile, cdnDir, pagesArg] = process.argv.slice(2);
  const list = JSON.parse(fs.readFileSync(listFile, "utf8"));
  const done = new Set();
  if (fs.existsSync(outFile)) for (const l of fs.readFileSync(outFile, "utf8").split("\n")) if (l) done.add(JSON.parse(l).path);
  const todo = list.filter(p => !done.has(p));
  const out = fs.createWriteStream(outFile, { flags: "a" });
  const browser = await chromium.launch();
  const n = Math.max(1, Number(pagesArg || 3));
  let next = 0, count = 0;
  const t0 = Date.now();
  async function worker() {
    const page = await browser.newPage();
    if (cdnDir) await page.route("https://cdn.jsdelivr.net/**", route => {
      const f = path.join(cdnDir, path.basename(new URL(route.request().url()).pathname));
      route.fulfill({ body: fs.readFileSync(f), contentType: "text/javascript", headers: { "access-control-allow-origin": "*" } });
    });
    await page.route(/fonts\.(googleapis|gstatic)\.com/, route => route.fulfill({ body: "", contentType: "text/css" }));
    await page.goto(url);
    await page.evaluate(() => window.vehicleAI.load());
    while (next < todo.length) {
      const p = todo[next++];
      const r = await page.evaluate(async p => {
        try {
          const b = await (await fetch(p)).blob();
          const f = await window.vehicleAI.features(new File([b], p.split("/").pop(), { type: b.type }));
          return { path: p, e: Array.from(f.e), ef: Array.from(f.ef), h: Array.from(f.h) };
        } catch (e) { return { path: p, error: String(e.message || e) }; }
      }, p);
      out.write(JSON.stringify(r) + "\n");
      if (++count % 50 === 0) console.log(`${count}/${todo.length} (${Math.round((Date.now() - t0) / 1000)} s)`);
    }
    await page.close();
  }
  await Promise.all(Array.from({ length: n }, worker));
  out.end();
  await browser.close();
  console.log(`${count} pictures read`);
})().catch(e => { console.error(e); process.exit(1); });
