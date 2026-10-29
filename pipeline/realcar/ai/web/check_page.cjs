// check_page.cjs: the phone page's answers on some pictures, from a real browser (Chromium, with Playwright).
//   node check_page.cjs URL PICTURES.json OUT.json [CDN_DIR]
// PICTURES.json: {"read": ["pic", ...], "check": [["photo", "build", standin], ...]}, paths under URL.
// CDN_DIR: local copies of the page's jsDelivr scripts (served in their place, so no network is needed).
// Run by check.py, which compares the answers with the Python model's.
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

(async () => {
  const [url, picsFile, outFile, cdnDir] = process.argv.slice(2);
  const pics = JSON.parse(fs.readFileSync(picsFile, "utf8"));
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", e => errors.push(String(e)));
  page.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
  if (cdnDir) {
    await page.route("https://cdn.jsdelivr.net/**", route => {
      const f = path.join(cdnDir, path.basename(new URL(route.request().url()).pathname));
      if (!fs.existsSync(f)) return route.abort();
      route.fulfill({ body: fs.readFileSync(f), contentType: "text/javascript", headers: { "access-control-allow-origin": "*" } });
    });
  }
  // the fonts are not the model: an empty sheet in their place
  await page.route(/fonts\.(googleapis|gstatic)\.com/, route => route.fulfill({ body: "", contentType: "text/css" }));
  await page.goto(url);
  const t0 = Date.now();
  const out = await page.evaluate(async pics => {
    const file = async p => { const b = await (await fetch(p)).blob(); return new File([b], p.split("/").pop(), { type: b.type }); };
    const res = { read: {}, check: [], features: {} };
    const t = performance.now();
    await window.vehicleAI.load();
    res.load_ms = performance.now() - t;
    const feats = async p => { const f = await window.vehicleAI.features(await file(p)); return { e: Array.from(f.e), ef: Array.from(f.ef), h: Array.from(f.h) }; };
    for (const p of pics.read) {
      const t1 = performance.now();
      res.features[p] = { ...(await feats(p)), ms: performance.now() - t1 };
      const q = await window.vehicleAI.prepare(await file(p));
      res.features[p].prep = { w: q.w, h: q.hh, sum: q.x.reduce((s, v) => s + v, 0), sample: pics.sample.map(i => q.x[i]) };
      res.read[p] = await window.vehicleAI.read(await file(p));
    }
    for (const [a, b, st] of pics.check) {
      const c = { photo: a, build: b, standin: !!st, result: await window.vehicleAI.check(await file(a), await file(b), !!st) };
      if (!res.features[a]) c.photo_features = await feats(a);
      if (!res.features[b]) c.build_features = await feats(b);
      res.check.push(c);
    }
    res.sheet = document.getElementById("sheet").innerText.slice(0, 400);
    res.status = document.getElementById("status").innerText;
    return res;
  }, pics);
  out.errors = errors;
  out.total_ms = Date.now() - t0;
  fs.writeFileSync(outFile, JSON.stringify(out));
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
