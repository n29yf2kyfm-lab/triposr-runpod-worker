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

  // Pricing: a priced estimate, a range, and an honest sanity verdict.
  await page.waitForFunction(
    () => /£[\d,]+/.test(document.getElementById('assess').innerText), null,
    { timeout: 60000 });
  const money = await page.innerText('#assess');
  check('the estimate shows a price with VAT',
        /£[\d,]+\s*incl VAT/.test(money.replace(/\n/g, ' ')),
        money.slice(0, 90));
  check('and a range, not a single number',
        /realistic range £[\d,]+ – £[\d,]+/.test(money.replace(/\n/g, ' ')));
  check('and a £/m2 figure with a verdict on it',
        /\/ m²/.test(money) && /band/.test(money));
  check('and it says how much of itself is indicative',
        /indicative/.test(money), money.slice(0, 60));

  // Calibrating to a real rate must move the price and the verdict.
  const beforeCal = await page.evaluate(async () => {
    const r = await fetch(`/api/project/${window.__twinUI.project.project_id}/assess`);
    return (await r.json()).estimate.totals.gross;
  });
  await page.fill('#calRate', '2200');
  await page.dispatchEvent('#calRate', 'change');
  await page.waitForFunction(
    (b) => {
      const t = document.getElementById('assess').innerText;
      return /inside the usual/.test(t);
    }, beforeCal, { timeout: 60000 });
  const afterCal = await page.evaluate(async () => {
    const r = await fetch(`/api/project/${window.__twinUI.project.project_id}` +
                          `/assess?calibrate_per_m2=2200`);
    const j = await r.json();
    return { gross: j.estimate.totals.gross,
             per_m2: j.estimate.per_m2.gross_per_m2,
             verdict: j.estimate.per_m2.verdict };
  });
  check('calibrating to your own rate lands the £/m2 on it',
        Math.abs(afterCal.per_m2 - 2200) < 60, afterCal.per_m2);
  check('and the sanity verdict then reads as in-band',
        /inside the usual/.test(afterCal.verdict), afterCal.verdict.slice(0, 60));
  check('and the price moved because of it',
        afterCal.gross > beforeCal * 1.5,
        `${Math.round(beforeCal)} -> ${Math.round(afterCal.gross)}`);

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

  /* --- rooms: what turns MASSING into a verdict ----------------------- */
  const massing = await page.evaluate(
    () => document.getElementById('assess').innerText);
  check('with no rooms drawn the gate says MASSING, not "illegal"',
        /MASSING/.test(massing), massing.slice(0, 40).replace(/\n/g, ' '));

  // Put the extension back — the knock-through is the job this is for.
  await page.evaluate(() => window.__twinUI.applyCommand({
    kind: 'extend', block_id: 'existing', edge: 'rear',
    depth_m: 4.0, storeys: 1 }));
  await page.waitForFunction(
    () => window.__twinUI.project.building.blocks.length === 2, null,
    { timeout: 30000 });

  await page.click('#layoutBtn');
  await page.waitForFunction(
    () => (window.__twinUI.project.plan.levels[0].rooms || []).length > 1,
    null, { timeout: 30000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: '/tmp/twin_plan_rooms.png' });

  const laid = await page.evaluate(() => {
    const L = window.__twinUI.project.plan.levels;
    return { ground: L[0].rooms.length,
             levels: L.length,
             bare: L.filter((l) => !(l.rooms || []).length).length,
             blocks: new Set(L[0].rooms.map((r) => r.block_id)).size,
             roomArea: L[0].room_area_m2, area: L[0].area_m2,
             names: L[0].rooms.map((r) => r.name).join(', ') };
  });
  check('one click lays out the whole house, not one floor of one block',
        laid.ground >= 4 && laid.bare === 0 && laid.blocks === 2,
        `${laid.ground} rooms, ${laid.levels} level(s), ` +
        `${laid.bare} left bare, ${laid.blocks} blocks`);
  check('the rooms fill the plan with no gaps left over',
        Math.abs(laid.roomArea - laid.area) < 0.2,
        `rooms ${laid.roomArea} of ${laid.area} m2`);
  check('and they are named as a person would name them',
        /Hall/.test(laid.names) && /Kitchen/.test(laid.names),
        laid.names.slice(0, 70));

  await page.waitForFunction(
    () => !/MASSING/.test(document.getElementById('assess').innerText),
    null, { timeout: 60000 });
  const withRooms = await page.evaluate(
    () => document.getElementById('assess').innerText);
  check('with rooms drawn the gate gives a real verdict, not MASSING',
        !/MASSING/.test(withRooms),
        withRooms.slice(0, 60).replace(/\n/g, ' '));
  check('and it now finds the inner room the layout actually has',
        /inner room|rooms deep/i.test(withRooms));

  // Select a room by clicking it on the plan, exactly as a user would.
  const picked = await page.evaluate(() => {
    const p = window.__twinUI.plan;
    const L = window.__twinUI.project.plan.levels[0];
    const r = L.rooms.find((x) => x.kind === 'kitchen');
    const s = p.toPx(r.x + r.width / 2, r.y + r.depth / 2);
    const b = p.canvas.getBoundingClientRect();
    return { x: b.left + s[0] / p.pixelRatio,
             y: b.top + s[1] / p.pixelRatio, id: r.id };
  });
  await page.mouse.click(picked.x, picked.y);
  await page.waitForTimeout(300);
  const panelShown = await page.evaluate(
    () => getComputedStyle(document.getElementById('roomPanel')).display);
  check('clicking a room on the plan selects it', panelShown !== 'none',
        panelShown);

  await page.fill('#roomName', 'Kitchen/diner');
  await page.click('#roomApply');
  await page.waitForFunction(
    () => (window.__twinUI.project.plan.levels[0].rooms || [])
      .some((r) => r.name === 'Kitchen/diner'), null, { timeout: 30000 });
  check('renaming a room writes through the same command path', true);

  /* THE KNOCK-THROUGH. What is asserted here is what is TRUE OF EVERY
   * BUILDING: two rooms become one, the floor area is conserved, and
   * the verdict is recomputed from the new layout.
   *
   * What is NOT asserted here is that it clears the inner-room refusal.
   * That depends on where the hall reaches in the particular house
   * Overpass returns, so it made this check pass or fail on which
   * building came back — a test that reports the weather. The claim is
   * worth making, so it is made where the geometry is controlled:
   * TestRooms.test_the_knock_through_clears_the_inner_room_refusal. */
  const preMerge = await page.evaluate(() => {
    const L = window.__twinUI.project.plan.levels[0];
    return { rooms: L.rooms.length, area: L.room_area_m2,
             verdict: document.getElementById('assess').innerText };
  });
  await page.mouse.click(picked.x, picked.y);
  await page.waitForTimeout(300);
  await page.click('#roomMerge');
  const merged = await page.waitForFunction(
    (n) => window.__twinUI.project.plan.levels[0].rooms.length === n - 1,
    preMerge.rooms, { timeout: 30000 }).then(() => true).catch(() => false);
  const postMerge = await page.evaluate(() => {
    const L = window.__twinUI.project.plan.levels[0];
    const big = L.rooms.reduce((a, b) => (b.area_m2 > a.area_m2 ? b : a));
    return { rooms: L.rooms.length, area: L.room_area_m2,
             biggest: `${big.name} ${big.area_m2} m²` };
  });
  check('knocking through makes one room out of two',
        merged && postMerge.rooms === preMerge.rooms - 1,
        `${preMerge.rooms} rooms -> ${postMerge.rooms}, now ${postMerge.biggest}`);
  check('and the floor area is conserved by the knock-through',
        Math.abs(postMerge.area - preMerge.area) < 0.05,
        `${preMerge.area} -> ${postMerge.area} m²`);
  const reassessed = await page.waitForFunction(
    (v) => document.getElementById('assess').innerText !== v,
    preMerge.verdict, { timeout: 60000 }).then(() => true).catch(() => false);
  check('and the verdict is recomputed from the new layout', reassessed);

  await page.screenshot({ path: '/tmp/twin_plan_merged.png' });

  // And the rooms survive an undo/redo round trip with the same ids —
  // replay mints them from a seed, not a fresh uuid.
  const ids = await page.evaluate(
    () => window.__twinUI.project.plan.levels[0].rooms
      .map((r) => r.id).sort().join(','));
  await page.click('#undo');
  await page.waitForTimeout(900);
  await page.click('#redo');
  await page.waitForFunction(
    (s) => window.__twinUI.project.plan.levels[0].rooms
      .map((r) => r.id).sort().join(',') === s, ids, { timeout: 30000 })
    .then(() => check('undo and redo bring the same rooms back, same ids', true))
    .catch(() => check('undo and redo bring the same rooms back, same ids',
                       false, 'ids changed on replay'));

  /* After a layout, the OUTSIDE wall must still be draggable. Room
   * edges lying on the envelope used to be emitted as partitions, and
   * the picker preferred them, so every envelope drag became a
   * move_partition the server refused. */
  const envelope = await page.evaluate(() => {
    const p = window.__twinUI.plan;
    const L = p.levelData();
    const w = L.walls.find((x) => x.edge === 'rear' && x.external);
    const [a, b] = w.points;
    const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    const hit = p.pick(mid[0], mid[1]);
    return { picked: hit ? { room: hit.room || null, block: hit.block || null,
                             external: hit.external === true } : null,
             mid, wall: w.id };
  });
  check('the outside wall is still what the plan picks after a layout',
        envelope.picked && !envelope.picked.room && !!envelope.picked.block,
        JSON.stringify(envelope.picked));

  const envDrag = await page.evaluate(async (mid) => {
    const p = window.__twinUI.plan;
    /* Record what the canvas actually decides, so a failure here says
     * WHY — picked nothing, read it as a tap, or the command refused. */
    window.__dragLog = [];
    const od = p.onDrag;
    p.onDrag = (w, by) => { window.__dragLog.push(['drag', w.id, by]);
                            return od(w, by); };
    const orm = p.onRoom;
    p.onRoom = (r) => { window.__dragLog.push(['room', r.id]);
                        return orm(r); };
    const before = window.__twinUI.project.building.measurements.footprint_m2;
    const b = p.canvas.getBoundingClientRect();
    const s0 = p.toPx(mid[0], mid[1]);
    const s1 = p.toPx(mid[0], mid[1] + 1.0);
    const pt = (s) => ({ x: b.left + s[0] / p.pixelRatio,
                         y: b.top + s[1] / p.pixelRatio });
    return { before, from: pt(s0), to: pt(s1) };
  }, envelope.mid);
  await page.mouse.move(envDrag.from.x, envDrag.from.y);
  await page.mouse.down();
  await page.mouse.move(envDrag.to.x, envDrag.to.y, { steps: 8 });
  await page.mouse.up();
  await page.waitForFunction(
    (b) => window.__twinUI.project.building.measurements.footprint_m2 > b + 0.5,
    envDrag.before, { timeout: 30000 }).catch(() => {});
  const envAfter = await page.evaluate(
    () => window.__twinUI.project.building.measurements.footprint_m2);
  const dragLog = await page.evaluate(() => window.__dragLog);
  check('dragging it grows the building instead of being refused',
        envAfter > envDrag.before + 0.5,
        `${envDrag.before} -> ${envAfter} · canvas saw ` +
        `${JSON.stringify(dragLog)} · status ` +
        (await page.evaluate(
          () => document.getElementById('tstatus').textContent)));

  const roomsFollow = await page.evaluate((blockId) => {
    const L = window.__twinUI.plan.levelData();
    const blk = L.blocks.find((b) => b.id === blockId);
    const rear = Math.max(...blk.ring.map((p) => p[1]));
    const touching = (L.rooms || []).filter(
      (r) => Math.abs(r.y + r.depth - rear) < 0.02);
    return { block: blockId, rear, touching: touching.length,
             roomArea: L.room_area_m2, area: L.area_m2 };
  }, envelope.picked.block);
  check('and the rooms on that wall came with it',
        roomsFollow.touching > 0 &&
        Math.abs(roomsFollow.roomArea - roomsFollow.area) < 0.2,
        JSON.stringify(roomsFollow));

  await page.click('#undo');
  await page.waitForTimeout(700);

  /* --- real ground under the model ------------------------------------ */
  /* Tolerant of the data, strict about the CODE: the LIDAR service can
   * be down and a house can be outside coverage, so either the imagery
   * arrives with its attribution on the frame, or the panel says in
   * words why it did not. Silence is the only failure. */
  const ground = await page.waitForFunction(
    () => {
      const n = document.getElementById('groundNote').innerText;
      return (window.__twinUI.viewer && window.__twinUI.viewer.groundTex)
        || /not|no |unreachable|coverage|key/i.test(n);
    }, null, { timeout: 120000 }).then(() => true).catch(() => false);
  const gInfo = await page.evaluate(() => ({
    tex: !!(window.__twinUI.viewer && window.__twinUI.viewer.groundTex),
    note: document.getElementById('groundNote').innerText,
    credit: document.getElementById('groundCredit').innerText,
    shown: getComputedStyle(
      document.getElementById('groundCredit')).display !== 'none',
    corners: window.__twinUI.viewer && window.__twinUI.viewer.groundQuad,
  }));
  check('the ground either loads or says why not', ground,
        gInfo.note.slice(0, 90));
  if (gInfo.tex) {
    check('imagery carries its attribution ON the frame',
          gInfo.shown && gInfo.credit.length > 8, gInfo.credit.slice(0, 70));
    check('and it is placed in the building frame, rotated with the house',
          Array.isArray(gInfo.corners) && gInfo.corners.length === 4 &&
          gInfo.corners.every((c) => Math.abs(c[0]) < 500 &&
                                     Math.abs(c[1]) < 500),
          JSON.stringify(gInfo.corners));
  }

  await page.selectOption('#ground', 'off');
  await page.waitForFunction(
    () => !window.__twinUI.viewer.groundTex, null, { timeout: 20000 });
  check('turning the ground off clears the texture', true);
  await page.selectOption('#ground', 'mapbox-satellite');
  await page.waitForFunction(
    () => /MAPBOX_TOKEN|key/i.test(
      document.getElementById('groundNote').innerText), null,
    { timeout: 30000 })
    .then(() => check('a source with no key says which key it needs', true))
    .catch(() => check('a source with no key says which key it needs', false,
                       'no mention of the token'));

  /* --- the drawing set: a real PDF, at a real scale ------------------- */
  await page.selectOption('#paper', 'A3');
  await page.selectOption('#sheetScale', '');
  const sheetSet = await page.evaluate(async () => {
    const id = window.__twinUI.project.project_id;
    const m = await (await fetch(`/api/project/${id}/sheets?paper=A3`)).json();
    const r = await fetch(`/api/project/${id}/sheets.pdf?paper=A3`);
    const buf = new Uint8Array(await r.arrayBuffer());
    const head = String.fromCharCode(...buf.slice(0, 8));
    const tail = String.fromCharCode(...buf.slice(-8));
    return { manifest: m.manifest, problems: m.problems, type:
             r.headers.get('content-type'), bytes: buf.length, head, tail };
  });
  check('the drawing set is a real PDF served as one',
        /^%PDF-1\./.test(sheetSet.head) && /%%EOF/.test(sheetSet.tail) &&
        /application\/pdf/.test(sheetSet.type || ''),
        `${sheetSet.type} ${sheetSet.bytes} bytes`);
  const kinds = new Set((sheetSet.manifest || []).map((m) => m.number.slice(0, 2)));
  check('and it holds plans, sections, elevations and schedules',
        ['PL', 'SE', 'EL', 'SC'].every((k) => kinds.has(k)),
        (sheetSet.manifest || []).map((m) => m.number).join(' '));
  check('every drawn sheet is at the same standard scale',
        new Set((sheetSet.manifest || []).filter((m) => m.scale)
          .map((m) => m.scale)).size === 1,
        JSON.stringify((sheetSet.manifest || []).map((m) => m.scale)));
  check('nothing in the set failed to draw silently',
        Array.isArray(sheetSet.problems) && sheetSet.problems.length === 0,
        JSON.stringify(sheetSet.problems));

  await page.click('#sheetsBtn');
  await page.waitForFunction(
    () => /PL-01/.test(document.getElementById('sheetList').innerText), null,
    { timeout: 30000 });
  check('the sheet list is shown before the PDF opens', true);

  const tooBig = await page.evaluate(async () => {
    const id = window.__twinUI.project.project_id;
    const r = await fetch(`/api/project/${id}/sheets.pdf?paper=A4&scale=20`);
    return { status: r.status, body: await r.text() };
  });
  check('a scale that will not fit is refused with a reason, not shrunk',
        tooBig.status === 422 && /not fit|standard scale/.test(tooBig.body),
        tooBig.body.slice(0, 90));

  check('no page errors', errors.length === 0, errors.slice(0, 2).join(' | '));
  await browser.close();

  const failed = results.filter((r) => !r.ok);
  for (const r of results) {
    console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.name}${r.detail ? '  — ' + r.detail : ''}`);
  }
  console.log(`\n${results.length - failed.length}/${results.length} passed`);
  process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error('HARNESS ERROR', e); process.exit(2); });
