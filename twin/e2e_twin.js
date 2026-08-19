/* Stages 2-5 end to end, in a real browser, against the real server.
 *
 * This is the brief's SUCCESS TEST, driven: postcode -> real property ->
 * 3D -> measure -> select a wall -> 4 m extension -> geometry changes ->
 * plan changes -> area recalculates -> shadow recalculates -> compare
 * before/after -> undo.
 */
const { chromium } = require('playwright');
const BASE = process.env.TWIN_BASE || 'http://127.0.0.1:8772';
const results = [];
const check = (name, cond, detail = '') =>
  results.push({ name, ok: !!cond, detail: String(detail).slice(0, 150) });

(async () => {
  const browser = await chromium.launch({
    executablePath: '/opt/pw-browsers/chromium',
    args: ['--no-sandbox', '--use-gl=swiftshader'],
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  /* A REFUSED EDIT IS A 422 AND THAT IS CORRECT. The test below
   * deliberately sends an impossible command, so the browser logs a
   * failed-resource error for it; counting that as a page error would
   * mean the harness fails whenever the validation works. */
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    if (/422 \(UNPROCESSABLE/.test(m.text())) return;
    errors.push(m.text());
  });

  await page.goto(BASE, { waitUntil: 'networkidle' });

  // 1-5: postcode -> the real property, selected.
  await page.fill('#q', 'B8 3AY');
  await page.click('#go');
  await page.waitForSelector('.res', { timeout: 40000 });
  await page.click('.res');
  await page.waitForFunction(
    () => window.__twin.buildings.data &&
          window.__twin.buildings.data.features.length > 0, null,
    { timeout: 90000 });

  const pt = await page.evaluate(async () => {
    const eng = await import('./engine.js');
    const f = window.__twin.buildings.data.features
      .map((x) => ({ f: x, a: eng.geometryArea(x.geometry) }))
      .filter((x) => x.a > 45 && x.a < 300)
      .sort((a, b) => a.a - b.a)[0].f;
    const c = eng.bboxOf(f.geometry);
    for (let t = 1; t < 40; t++) {
      const p = [c[0] + (c[2] - c[0]) * (t / 40), (c[1] + c[3]) / 2];
      if (eng.pointInGeometry(p[0], p[1], f.geometry)) return p;
    }
    return null;
  });
  check('a real building is selectable', !!pt);

  // 6: open the twin (Stage 2 join).
  await page.evaluate((p) => window.__twinUI.openTwin(p[1], p[0]), pt);
  await page.waitForFunction(() => window.__twinUI.project, null,
                             { timeout: 180000 });
  await page.waitForTimeout(1500);

  const before = await page.evaluate(
    () => window.__twinUI.project.building.measurements);
  check('the twin is built from the REAL footprint',
        before.footprint_m2 > 20 && before.footprint_m2 < 400,
        `${before.footprint_m2} m2`);
  check('and it reports a floor area and a ridge height',
        before.gia_m2 > 0 && before.ridge_height_m > before.eaves_height_m,
        JSON.stringify(before));

  // 7: 3D exists and has real geometry (Stage 3).
  const gl = await page.evaluate(() => ({
    ok: !!window.__twinUI.viewer,
    verts: window.__twinUI.viewer ? window.__twinUI.viewer.vertices : 0,
  }));
  check('the 3D viewer builds real geometry', gl.ok && gl.verts > 30,
        `${gl.verts} vertices`);

  // 8-10: extension by command; geometry must actually change (Stage 4).
  await page.fill('#extDepth', '4');
  await page.selectOption('#extEdge', 'rear');
  await page.click('#extendBtn');
  await page.waitForFunction(
    (b) => window.__twinUI.project.building.measurements.footprint_m2 > b + 3,
    before.footprint_m2, { timeout: 60000 });
  const after = await page.evaluate(
    () => window.__twinUI.project.building.measurements);
  const blocks = await page.evaluate(
    () => window.__twinUI.project.building.blocks.length);
  check('a 4 m rear extension is added as its own block', blocks === 2, blocks);
  const grew = after.footprint_m2 - before.footprint_m2;
  const width = await page.evaluate(
    () => window.__twinUI.project.building.blocks[0].width);
  check('the footprint grows by depth x wall length, to the centimetre',
        Math.abs(grew - 4 * width) < 0.05,
        `grew ${grew.toFixed(2)} vs ${(4 * width).toFixed(2)}`);
  check('and the 3D rebuilt with more geometry',
        (await page.evaluate(() => window.__twinUI.viewer.vertices)) > gl.verts);

  // 11-12: the floor plan is the SAME model (Stage 5).
  await page.click('#tabs button[data-tab="plan"]');
  await page.waitForTimeout(600);
  const planState = await page.evaluate(() => {
    const p = window.__twinUI.plan;
    const L = p.levelData();
    return { levels: window.__twinUI.project.plan.levels.length,
             blocks: L.blocks.length, walls: L.walls.length,
             area: L.area_m2 };
  });
  check('the floor plan shows both blocks on the ground floor',
        planState.blocks === 2, JSON.stringify(planState));
  check('and its area equals the model footprint — one geometry, not two',
        Math.abs(planState.area - after.footprint_m2) < 0.02,
        `plan ${planState.area} vs model ${after.footprint_m2}`);

  // 2D -> 3D: drag a wall in the plan, 3D and totals must follow.
  const dragged = await page.evaluate(async () => {
    const p = window.__twinUI.plan;
    const L = p.levelData();
    const w = L.walls.find((x) => x.edge === 'rear' && x.external);
    const beforeArea = window.__twinUI.project.building.measurements.footprint_m2;
    await window.__twinUI.applyCommand({
      kind: 'move_wall', block_id: w.block, edge: 'rear', by_m: 1.0,
      label: 'rear wall +1 m' });
    return { beforeArea,
             afterArea: window.__twinUI.project.building.measurements.footprint_m2 };
  });
  check('dragging a plan wall changes the one shared model',
        dragged.afterArea > dragged.beforeArea + 0.5,
        JSON.stringify(dragged));

  // 13: shadow model recalculates from real coordinates.
  const sun = await page.evaluate(() => {
    const a = window.__twinUI.project.building.anchor;
    const noon = window.__twinUI.viewer.setSun(a.lat, a.lon,
                                               new Date(Date.UTC(2026, 5, 21, 12)));
    const eve = window.__twinUI.viewer.setSun(a.lat, a.lon,
                                              new Date(Date.UTC(2026, 5, 21, 19)));
    return { noon, eve };
  });
  check('the sun is higher at midsummer noon than at 7pm',
        sun.noon.altitude_deg > sun.eve.altitude_deg + 10,
        `noon ${sun.noon.altitude_deg.toFixed(1)} eve ${sun.eve.altitude_deg.toFixed(1)}`);
  check('and midsummer noon in Birmingham is about 61 degrees',
        Math.abs(sun.noon.altitude_deg - 61) < 4,
        sun.noon.altitude_deg.toFixed(1));

  // Regulations + quantities came from the real engine (Stage 2).
  await page.waitForFunction(
    () => document.getElementById('assess').innerText.includes('m²'), null,
    { timeout: 90000 });
  const assess = await page.innerText('#assess');
  check('the regulations gate reports a verdict',
        /MASSING|PASSES|REFUSED/.test(assess), assess.slice(0, 80));
  check('a real bill of quantities is shown',
        /Facing bricks|Roof covering|Plasterboard/.test(assess),
        assess.slice(0, 120));

  // 16-17: before/after.
  await page.click('#tabs button[data-tab="3d"]');
  await page.waitForTimeout(400);
  await page.screenshot({ path: '/tmp/twin_3d_after.png' });
  const vAfter = await page.evaluate(() => window.__twinUI.viewer.vertices);
  await page.check('#beforeAfter');
  await page.waitForTimeout(600);
  const vBefore = await page.evaluate(() => window.__twinUI.viewer.vertices);
  check('before/after switches to the as-found building',
        vBefore < vAfter, `before ${vBefore} after ${vAfter}`);
  await page.screenshot({ path: '/tmp/twin_3d_before.png' });
  await page.uncheck('#beforeAfter');
  await page.waitForTimeout(400);

  // Undo takes it back, exactly.
  await page.click('#undo');
  await page.waitForFunction(
    (a) => window.__twinUI.project.building.measurements.footprint_m2 < a,
    dragged.afterArea, { timeout: 30000 });
  await page.click('#undo');
  await page.waitForTimeout(800);
  const undone = await page.evaluate(
    () => window.__twinUI.project.building.measurements);
  check('undo returns the model to exactly as found',
        Math.abs(undone.footprint_m2 - before.footprint_m2) < 0.01,
        `${undone.footprint_m2} vs ${before.footprint_m2}`);

  // A refused command must not corrupt the model.
  const refused = await page.evaluate(async () => {
    const b = window.__twinUI.project.building.measurements.footprint_m2;
    await window.__twinUI.applyCommand({ kind: 'extend', block_id: 'existing',
                                         edge: 'rear', depth_m: -3 });
    return { b, a: window.__twinUI.project.building.measurements.footprint_m2,
             msg: document.getElementById('tstatus').textContent };
  });
  check('an impossible edit is refused with a reason, model untouched',
        Math.abs(refused.a - refused.b) < 1e-6 && /REFUSED/.test(refused.msg),
        refused.msg.slice(0, 90));

  await page.click('#tabs button[data-tab="plan"]');
  await page.waitForTimeout(700);
  await page.screenshot({ path: '/tmp/twin_plan.png' });

  check('no page errors', errors.length === 0, errors.slice(0, 2).join(' | '));
  await browser.close();

  const failed = results.filter((r) => !r.ok);
  for (const r of results) {
    console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.name}${r.detail ? '  — ' + r.detail : ''}`);
  }
  console.log(`\n${results.length - failed.length}/${results.length} passed`);
  process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error('HARNESS ERROR', e); process.exit(2); });
