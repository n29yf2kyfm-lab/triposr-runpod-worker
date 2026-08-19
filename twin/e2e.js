/* Stage 1 end-to-end, in a real browser against the real server.
 *
 * This drives the actual UI — types in the search box, clicks the map,
 * reads the DOM — and asserts against ENGINE STATE, not against a
 * screenshot. A screenshot proves something was painted; only the state
 * proves the right building was selected.
 */
const { chromium } = require('playwright');

const BASE = process.env.TWIN_BASE || 'http://127.0.0.1:8767';
const results = [];
function check(name, cond, detail = '') {
  results.push({ name, ok: !!cond, detail: String(detail).slice(0, 160) });
}

(async () => {
  const browser = await chromium.launch({
    executablePath: '/opt/pw-browsers/chromium',
    args: ['--no-sandbox', '--use-gl=swiftshader'],
  });
  const page = await browser.newPage({
    viewport: { width: 1280, height: 860 }, deviceScaleFactor: 2,
  });
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  // Nothing may be fetched from a third party: the CSP says so, and this
  // proves the page obeys it.
  const offsite = [];
  await page.route('**', (route) => {
    const u = route.request().url();
    if (!u.startsWith(BASE) && !u.startsWith('data:')) { offsite.push(u); return route.abort(); }
    return route.continue();
  });

  await page.goto(BASE, { waitUntil: 'networkidle' });
  check('page loads and the engine boots',
        await page.evaluate(() => !!window.__twin && !!window.__twin.map));

  // --- geodesy parity: the JS must agree with the server ---------------
  const parity = await page.evaluate(async () => {
    const { map } = window.__twin;
    const eng = await import('./engine.js');
    // A 20 m square built in the browser, measured both sides.
    const lat = 52.4856, lon = -1.8476;
    const mLat = 111132.92 - 559.82 * Math.cos(2 * lat * Math.PI / 180)
      + 1.175 * Math.cos(4 * lat * Math.PI / 180);
    const mLon = 111412.84 * Math.cos(lat * Math.PI / 180)
      - 93.5 * Math.cos(3 * lat * Math.PI / 180);
    const ring = [[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]
      .map(([x, y]) => [lon + x / mLon, lat + y / mLat]);
    const geom = { type: 'Polygon', coordinates: [ring] };
    const client = eng.geometryArea(geom);
    const r = await fetch('/api/measure', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ geometry: geom }) });
    const server = (await r.json()).area_m2;
    return { client, server };
  });
  check('client and server areas agree to 0.1%',
        Math.abs(parity.client - parity.server) / parity.server < 0.001,
        `client ${parity.client.toFixed(2)} server ${parity.server}`);
  check('and both land on the true 400 m2',
        Math.abs(parity.server - 400) < 1, `server ${parity.server}`);

  // --- search ----------------------------------------------------------
  await page.fill('#q', 'B8 3AY');
  await page.click('#go');
  await page.waitForSelector('.res', { timeout: 30000 });
  const first = await page.textContent('.res');
  check('a real UK postcode returns a real result', /B8 3AY/i.test(first), first);
  check('and it declares its accuracy rather than implying a house',
        /±\d+ m/.test(first), first);

  await page.click('.res');
  await page.waitForTimeout(2500);
  const view = await page.evaluate(() => window.__twin.map.viewState());
  check('the map flies to the postcode',
        Math.abs(view.centre[1] - 52.4856) < 0.01 &&
        Math.abs(view.centre[0] + 1.8476) < 0.01,
        JSON.stringify(view.centre));
  check('at a zoom where buildings are legible', view.zoom >= 17, view.zoom);

  // --- footprints ------------------------------------------------------
  await page.waitForFunction(
    () => window.__twin.buildings.data &&
          window.__twin.buildings.data.features.length > 0,
    { timeout: 45000 });
  const feats = await page.evaluate(
    () => window.__twin.buildings.data.features.length);
  check('real building footprints load', feats > 3, `${feats} features`);

  const areas = await page.evaluate(async () => {
    const eng = await import('./engine.js');
    return window.__twin.buildings.data.features
      .map((f) => eng.geometryArea(f.geometry));
  });
  check('every footprint has a plausible real-world area',
        areas.every((a) => a > 2 && a < 20000),
        `min ${Math.min(...areas).toFixed(1)} max ${Math.max(...areas).toFixed(1)}`);

  // --- selection: the rule that must never pick the neighbour ----------
  const sel = await page.evaluate(async () => {
    const eng = await import('./engine.js');
    const { map, buildings } = window.__twin;
    const feats = buildings.data.features;
    const f = feats
      .map((x) => ({ f: x, a: eng.geometryArea(x.geometry) }))
      .filter((x) => x.a > 40 && x.a < 400)
      .sort((a, b) => a.a - b.a)[0].f;
    /* A point genuinely INSIDE the polygon. The bbox centre is outside
     * for any L-plan or concave footprint, so scan the mid-latitude line
     * until the polygon actually contains the point — this is the same
     * class of mistake the selection rule exists to avoid. */
    const c = eng.bboxOf(f.geometry);
    let inside = null;
    for (let t = 1; t < 40 && !inside; t++) {
      const p = [c[0] + (c[2] - c[0]) * (t / 40), (c[1] + c[3]) / 2];
      if (eng.pointInGeometry(p[0], p[1], f.geometry)) inside = p;
    }
    const hitInside = inside && map.hitTest(inside[0], inside[1]);

    /* Open ground: a point NO footprint contains. In a dense terrace the
     * naive "300 m north" lands on another roof, which is a fact about
     * Birmingham, not a failure — so search for a genuinely empty point
     * and assert the rule against that. */
    let empty = null;
    const b = map.bounds();
    for (let i = 0; i < 400 && !empty; i++) {
      const p = [b[0] + (b[2] - b[0]) * ((i * 37 % 100) / 100),
                 b[1] + (b[3] - b[1]) * ((i * 61 % 100) / 100)];
      if (!feats.some((x) => eng.pointInGeometry(p[0], p[1], x.geometry))) {
        empty = p;
      }
    }
    return {
      insideId: hitInside && hitInside.feature.id,
      target: f.id,
      inside,
      emptyFound: !!empty,
      emptyHit: empty ? !!map.hitTest(empty[0], empty[1]) : null,
      centre: inside,
    };
  });
  check('a tap inside a footprint selects THAT building',
        sel.insideId === sel.target, `${sel.insideId} vs ${sel.target}`);
  check('a point in no footprint selects nothing — never the nearest',
        sel.emptyFound && sel.emptyHit === false,
        `found=${sel.emptyFound} hit=${sel.emptyHit}`);

  // --- property panel --------------------------------------------------
  await page.evaluate((c) => window.__twin.selectProperty(c[0], c[1]),
                      sel.centre);
  await page.waitForFunction(
    () => document.getElementById('prop').style.display === 'block' &&
          document.getElementById('prop').innerText.length > 80,
    { timeout: 40000 });
  const panel = await page.innerText('#prop');
  check('the panel reports a measured footprint area',
        /Footprint area[\s\S]{0,20}[\d.]+\s*m²/.test(panel),
        JSON.stringify(panel.slice(0, 400)));
  check('every fact carries a provenance disclosure',
        (await page.locator('#prop details').count()) >= 2);
  check('unavailable layers say DATA NOT AVAILABLE, not zero',
        /DATA NOT AVAILABLE/.test(panel));
  check('the capability matrix is shown to the user',
        /RESTRICTED|LIMITED|AVAILABLE/.test(panel));
  check('OpenStreetMap is attributed as its licence requires',
        /OpenStreetMap/.test(await page.innerText('#attrib')));

  // --- scale bar honesty ----------------------------------------------
  const scale = await page.evaluate(() => {
    const t = document.getElementById('scaleTxt').textContent;
    const px = parseFloat(document.getElementById('bar').style.width);
    const mpp = window.__twin.map.metresPerPixel();
    const m = parseFloat(t);
    return { labelled: t.includes('km') ? m * 1000 : m, actual: px * mpp };
  });
  check('the scale bar measures what its label says',
        Math.abs(scale.labelled - scale.actual) / scale.labelled < 0.02,
        `label ${scale.labelled} actual ${scale.actual.toFixed(1)}`);

  await page.screenshot({ path: '/tmp/twin_property.png' });
  await page.evaluate(() => window.__twin.map.setView(null, 16.2));
  await page.waitForTimeout(2000);
  await page.screenshot({ path: '/tmp/twin_area.png' });

  check('no third-party request was attempted',
        offsite.length === 0, offsite.slice(0, 3).join(' '));
  check('no page errors', errors.length === 0, errors.slice(0, 2).join(' | '));

  await browser.close();
  const failed = results.filter((r) => !r.ok);
  for (const r of results) {
    console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.name}${r.detail ? '  — ' + r.detail : ''}`);
  }
  console.log(`\n${results.length - failed.length}/${results.length} passed`);
  process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error('HARNESS ERROR', e); process.exit(2); });
