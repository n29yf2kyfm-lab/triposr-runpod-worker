import * as THREE from 'three';

/* ═════════════════════════════════════════════════════════════════════
   Golf Mk8 eHybrid: the parts the GTI file and the Golf bay do not have.
   CONSTRUCTED training geometry to published figures where they exist
   (EA211 1.4 TSI: bore 74.5 mm, stroke 80.0 mm, 1,395 cc; e-motor 85 kW;
   13 kWh battery; 40 L tank) and educated estimates everywhere else.
   Not OEM CAD. No torque values or part numbers: those need erWin / ETKA.
   Frame: +X is the car's LEFT, +Y up, +Z the nose, ground at Y=0, metres.
   ═══════════════════════════════════════════════════════════════════ */

const V = (x, y, z) => new THREE.Vector3(x, y, z);

export function buildHybrid(materialFactory) {
  const M = {
    cast: materialFactory(0x737874, { metalness: .58, roughness: .7 }, 'cast'),
    alu: materialFactory(0xa6afb5, { metalness: .85, roughness: .38 }, 'brushed'),
    steel: materialFactory(0x4d5359, { metalness: .86, roughness: .45 }, 'brushed'),
    dark: materialFactory(0x24292e, { metalness: .2, roughness: .7 }, 'plastic'),
    plastic: materialFactory(0x15191d, { metalness: .03, roughness: .85 }, 'plastic'),
    hv: materialFactory(0xff6a00, { metalness: .05, roughness: .55 }, 'plastic'),
    copper: materialFactory(0xb87333, { metalness: .9, roughness: .32 }, 'brushed'),
    seal: materialFactory(0x1f9d5a, { metalness: 0, roughness: .8 }, 'rubber'),
    bolt: materialFactory(0xd4b13f, { metalness: .9, roughness: .3 }, 'brushed'),
    rubber: materialFactory(0x111316, { metalness: 0, roughness: .95 }, 'rubber'),
    exh: materialFactory(0x7a6a5a, { metalness: .7, roughness: .55 }, 'cast'),
    tank: materialFactory(0x1d2024, { metalness: .02, roughness: .9 }, 'plastic'),
    cell: materialFactory(0x3a4049, { metalness: .4, roughness: .5 }, 'brushed'),
  };
  const parts = [];
  const mesh = (geo, mat, p = [0, 0, 0], r = [0, 0, 0]) => { const o = new THREE.Mesh(geo, mat); o.position.set(...p); o.rotation.set(...r); o.castShadow = o.receiveShadow = true; return o; };
  const cylX = (r, l, mat, p, seg = 32) => mesh(new THREE.CylinderGeometry(r, r, l, seg), mat, p, [0, 0, Math.PI / 2]);
  const cylY = (r, l, mat, p, seg = 24) => mesh(new THREE.CylinderGeometry(r, r, l, seg), mat, p);
  const cylZ = (r, l, mat, p, seg = 24) => mesh(new THREE.CylinderGeometry(r, r, l, seg), mat, p, [Math.PI / 2, 0, 0]);
  const box = (w, h, d, mat, p) => mesh(new THREE.BoxGeometry(w, h, d), mat, p);
  const torusX = (R, t, mat, p) => mesh(new THREE.TorusGeometry(R, t, 8, 48), mat, p, [0, Math.PI / 2, 0]);
  const torusY = (R, t, mat, p) => mesh(new THREE.TorusGeometry(R, t, 8, 40), mat, p, [Math.PI / 2, 0, 0]);
  const tube = (pts, r, mat) => mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts.map(p => V(...p))), 80, r, 10, false), mat);
  // a hex-head bolt pointing along `dir` ('x','-x','y','-y','z','-z'); dia in metres
  const boltAt = (g, p, dia, len, dir = 'y') => {
    const b = new THREE.Group();
    b.add(mesh(new THREE.CylinderGeometry(dia * .95, dia * .95, dia * .65, 6), M.bolt, [0, dia * .33, 0]));
    b.add(mesh(new THREE.CylinderGeometry(dia / 2, dia / 2, len, 10), M.bolt, [0, -len / 2, 0]));
    const R = { y: [0, 0, 0], '-y': [Math.PI, 0, 0], x: [0, 0, -Math.PI / 2], '-x': [0, 0, Math.PI / 2], z: [Math.PI / 2, 0, 0], '-z': [-Math.PI / 2, 0, 0] }[dir];
    b.rotation.set(...R); b.position.set(...p); g.add(b); return b;
  };
  const part = (id, name, sys, obj, o = {}) => { obj.name = id; parts.push({ id, name, sys, obj, ex: V(...(o.ex || [0, 0, 0])), stripEx: o.stripEx ? V(...o.stripEx) : null, tags: o.tags || [], qty: o.qty || 1, mat: o.mat || '', size: o.size || '', conf: o.conf || 'est', note: o.note || '', hidden: !!o.hidden }); return obj; };
  const grp = (...kids) => { const g = new THREE.Group(); for (const k of kids) g.add(k); return g; };

  /* ───────── hybrid drive: e-motor module, inverter, HV cabling, battery ───────── */
  // the DQ400e puts the e-motor and its K0 clutch between the engine and the gearbox:
  // drawn as a ribbed housing around the bellhousing position of the Golf bay
  const EM = V(-0.312, 0.456, 1.495);
  {
    const g = new THREE.Group(); g.position.copy(EM);
    g.add(cylX(0.176, 0.105, M.cast, [0, 0, 0], 48));
    for (let i = 0; i < 6; i++) g.add(torusX(0.177, 0.005, M.alu, [-0.045 + i * 0.018, 0, 0]));
    g.add(cylX(0.150, 0.004, M.copper, [0.054, 0, 0], 48));
    const conn = box(0.07, 0.05, 0.09, M.hv, [0, 0.19, -0.02]); g.add(conn);
    g.add(cylY(0.012, 0.03, M.hv, [-0.02, 0.225, -0.04]), cylY(0.012, 0.03, M.hv, [0.02, 0.225, -0.04]));
    part('emotor', 'E-motor and K0 disconnect clutch (DQ400e hybrid module)', 'hybrid', g,
      { ex: [-0.35, 0.05, -0.15], tags: ['pt', 'hv', 'gearbox'], mat: 'Cast aluminium housing, copper stator', size: 'Ø ≈ 350 mm, ≈ 105 mm deep (est.)', conf: 'pub',
        note: 'Permanent-magnet synchronous motor, 85 kW (published). The K0 clutch couples the petrol engine to the e-motor or lets the car drive on electricity alone. Position and size estimated.' });
    const s = new THREE.Group(); s.position.copy(EM);
    s.add(torusX(0.168, 0.004, M.seal, [0.056, 0, 0])); s.add(torusX(0.168, 0.004, M.seal, [-0.056, 0, 0]));
    part('seal_emotor', 'E-motor housing O-rings, engine and gearbox side', 'hybrid', s, { ex: [-0.48, 0.05, -0.15], tags: ['pt', 'gearbox', 'seal'], qty: 2, mat: 'FKM / EPDM rubber (est.)', note: 'Replace whenever the module is split from the engine or gearbox.' });
    const b = new THREE.Group(); b.position.copy(EM);
    for (let i = 0; i < 8; i++) { const a = i / 8 * Math.PI * 2 + 0.2; boltAt(b, [-0.06, Math.sin(a) * 0.165, Math.cos(a) * 0.165], 0.010, 0.05, 'x'); }
    part('bolts_emotor', 'Hybrid module to gearbox bolts', 'hybrid', b, { ex: [-0.62, 0.05, -0.15], tags: ['pt', 'gearbox', 'fastener'], qty: 8, size: 'M10 est.', note: 'Torque: erWin. Engine-to-module flange bolts are the twelve on the bellhousing flange.' });
  }
  {
    const g = new THREE.Group(); g.position.set(-0.42, 0.765, 1.63);
    g.add(box(0.22, 0.07, 0.25, M.alu, [0, 0, 0]));
    for (let i = 0; i < 9; i++) g.add(box(0.21, 0.008, 0.006, M.cast, [0, 0.039, -0.11 + i * 0.0275]));
    g.add(box(0.06, 0.04, 0.05, M.hv, [-0.07, 0.01, -0.13]), box(0.05, 0.035, 0.04, M.hv, [0.07, 0.01, -0.13]));
    g.add(cylX(0.009, 0.05, M.dark, [0.13, -0.01, 0.06]), cylX(0.009, 0.05, M.dark, [0.13, -0.01, 0.1]));
    part('inverter', 'Power electronics (inverter and DC/DC converter)', 'hybrid', g,
      { ex: [-0.25, 0.55, 0.15], tags: ['pt', 'hv', 'gearbox'], mat: 'Aluminium, liquid-cooled', size: '≈ 220 × 70 × 250 mm (est.)', note: 'Turns the battery’s DC into three-phase AC for the e-motor and feeds the 12 V system through a DC/DC converter. Position estimated.' });
    const b = new THREE.Group(); b.position.set(-0.42, 0.80, 1.63);
    for (const [x, z] of [[0.1, 0.115], [-0.1, 0.115], [0.1, -0.115], [-0.1, -0.115], [0.1, 0], [-0.1, 0]]) boltAt(b, [x, 0, z], 0.008, 0.03, 'y');
    part('bolts_inverter', 'Inverter mounting bolts', 'hybrid', b, { ex: [-0.25, 0.72, 0.15], tags: ['pt', 'gearbox', 'fastener'], qty: 6, size: 'M8 est.' });
    const s = new THREE.Group(); s.position.set(-0.42, 0.765, 1.63);
    s.add(box(0.226, 0.003, 0.256, M.seal, [0, -0.037, 0]));
    part('seal_inverter', 'Inverter coolant and housing seals', 'hybrid', s, { ex: [-0.25, 0.42, 0.15], tags: ['pt', 'gearbox', 'seal'], note: 'Coolant connections use O-rings: replace on refit (est.).' });
  }
  part('hv_cable_motor', 'HV cable, inverter to e-motor', 'hybrid',
    tube([[-0.47, 0.74, 1.51], [-0.43, 0.70, 1.47], [-0.36, 0.66, 1.475]], 0.011, M.hv),
    { ex: [-0.3, 0.35, 0], tags: ['pt', 'hv', 'gearbox'], note: 'Three-phase cable. Orange insulation marks high voltage on every car.' });
  part('hv_cable_battery', 'HV cable, battery to inverter', 'hybrid',
    tube([[-0.37, 0.74, 1.51], [-0.42, 0.58, 1.20], [-0.33, 0.30, 0.98], [-0.14, 0.17, 0.55], [-0.13, 0.165, -0.10], [-0.12, 0.20, -0.36]], 0.012, M.hv),
    { ex: [0, -0.25, 0], tags: ['hv', 'hvcable'], size: 'twin core, ≈ 24 mm sheath (est.)', note: 'Runs down the bulkhead and back along the transmission tunnel to the battery (routing estimated).' });
  part('charge_socket', 'Charging socket and lead to on-board charger', 'hybrid',
    grp(cylX(0.034, 0.03, M.dark, [-0.80, 0.80, 1.58]), cylX(0.026, 0.01, M.hv, [-0.818, 0.80, 1.58]),
      tube([[-0.785, 0.79, 1.58], [-0.70, 0.76, 1.66], [-0.55, 0.77, 1.68], [-0.53, 0.77, 1.66]], 0.009, M.hv)),
    { ex: [-0.4, 0.2, 0.2], tags: ['hv'], mat: 'Type 2 AC socket', note: 'The Golf 8 eHybrid charges through a Type 2 socket in the right front wing (position estimated). AC only.' });
  {
    const g = new THREE.Group(); g.position.set(0, 0.265, -0.68);
    g.add(box(1.10, 0.20, 0.56, M.steel, [0, 0, 0]));
    g.add(box(1.08, 0.012, 0.54, M.hv, [0, 0.106, 0]));
    for (let i = 0; i < 8; i++) g.add(box(0.11, 0.012, 0.5, M.cell, [-0.45 + i * 0.128, 0.115, 0]));
    g.add(box(0.12, 0.06, 0.08, M.hv, [-0.12, 0.08, 0.30]));
    part('hv_battery', 'High-voltage battery, 13 kWh', 'hybrid', g,
      { ex: [0, -0.65, 0], tags: ['hv', 'battery'], mat: 'Steel housing, lithium-ion cells (96 cells, est.)', size: '≈ 1,100 × 200 × 560 mm (est.)', conf: 'pub',
        note: '13 kWh gross (published), under the rear seat. Liquid-cooled. Removal needs a battery lift table and an HV-qualified technician.' });
    const b = new THREE.Group(); b.position.set(0, 0.165, -0.68);
    for (const x of [-0.53, -0.18, 0.18, 0.53]) for (const z of [-0.26, 0.26]) boltAt(b, [x, 0, z], 0.010, 0.05, '-y');
    part('bolts_battery', 'HV battery mounting bolts', 'hybrid', b, { ex: [0, -0.85, 0], tags: ['battery', 'fastener'], qty: 8, size: 'M10 est.' });
    const s = new THREE.Group(); s.position.set(0, 0.367, -0.68); s.add(box(1.09, 0.003, 0.55, M.seal, [0, 0, 0]));
    part('seal_battery', 'HV battery lid seal', 'hybrid', s, { ex: [0, -0.35, 0], tags: ['battery', 'seal'], note: 'Keeps water out of the pack. Never opened outside a specialist battery workshop.' });
  }

  /* ───────── fuel and exhaust ───────── */
  {
    const g = new THREE.Group(); g.position.set(0, 0.49, -1.18);
    g.add(box(0.86, 0.20, 0.36, M.tank, [0, 0, 0]));
    g.add(cylY(0.04, 0.03, M.dark, [0.25, 0.11, 0]));
    g.add(tube([[0.42, 0.06, 0.05], [0.62, 0.22, 0.05], [0.74, 0.58, 0.05]], 0.016, M.dark));
    part('fuel_tank', 'Fuel tank, 40 litres, with filler neck', 'fuel', g,
      { ex: [0, 0.55, 0], conf: 'pub', mat: 'HDPE plastic (est.)', note: '40 litre capacity on the eHybrid (published), smaller than the GTI’s because the HV battery takes the space under the rear seat. Shape estimated.' });
    const b = new THREE.Group(); b.position.set(0, 0.39, -1.18);
    for (const x of [-0.38, 0.38]) boltAt(b, [x, 0, 0], 0.008, 0.04, '-y');
    part('bolts_tank', 'Fuel tank strap bolts', 'fuel', b, { ex: [0, 0.35, 0], tags: ['fastener'], qty: 2, size: 'M8 est.' });
  }
  part('exhaust_front', 'Downpipe with catalytic converter and particulate filter', 'fuel',
    grp(tube([[0.05, 0.46, 1.77], [0.07, 0.28, 1.80], [0.06, 0.17, 1.62], [0.03, 0.16, 1.15], [0.05, 0.16, 0.80]], 0.03, M.exh),
      cylZ(0.065, 0.24, M.exh, [0.06, 0.18, 1.40], 28)),
    { ex: [0, -0.35, 0.2], tags: ['exhaust', 'pt'], note: 'Close-coupled catalytic converter and petrol particulate filter (layout estimated for this bay).' });
  part('exhaust_rear', 'Centre pipe and rear silencer', 'fuel',
    grp(tube([[0.05, 0.16, 0.80], [0.10, 0.165, 0.10], [0.24, 0.18, -0.80], [0.38, 0.27, -1.55], [0.45, 0.28, -1.80]], 0.028, M.exh),
      box(0.36, 0.15, 0.30, M.exh, [0.40, 0.27, -1.85]), cylZ(0.035, 0.12, M.steel, [0.50, 0.26, -2.03])),
    { ex: [0, -0.45, -0.1], tags: ['exhaust'] });
  {
    const g = new THREE.Group(); g.position.set(0.06, 0.17, 0.80); g.add(torusX(0.033, 0.006, M.seal, [0, 0, 0])); g.rotation.y = Math.PI / 2;
    part('seal_exhaust', 'Exhaust clamp and sealing ring', 'fuel', g, { ex: [0, -0.4, 0], tags: ['exhaust', 'seal'], note: 'Replace the clamp and ring whenever the joint is split.' });
  }
  return { parts, M };
}

/* ───────── EA211 1.4 TSI, built in pieces for the strip-down ─────────
   Sits where the Golf bay draws its one-piece long block, and replaces it
   on the bench. Cylinders along X (transverse), crank at CRANK. */
export function buildEngineStrip(materialFactory, M) {
  const parts = [];
  const BORE = 0.0745, STROKE = 0.080, PITCH = 0.082;           // bore and stroke published; pitch est.
  const XC = -0.02, ZC = 1.545, CRANK = 0.37, DECK = 0.60;
  const CX = [-1.5, -0.5, 0.5, 1.5].map(k => XC + k * PITCH);
  const mesh = (geo, mat, p = [0, 0, 0], r = [0, 0, 0]) => { const o = new THREE.Mesh(geo, mat); o.position.set(...p); o.rotation.set(...r); o.castShadow = o.receiveShadow = true; return o; };
  const box = (w, h, d, mat, p) => mesh(new THREE.BoxGeometry(w, h, d), mat, p);
  const cylX = (r, l, mat, p, seg = 28) => mesh(new THREE.CylinderGeometry(r, r, l, seg), mat, p, [0, 0, Math.PI / 2]);
  const cylY = (r, l, mat, p, seg = 24) => mesh(new THREE.CylinderGeometry(r, r, l, seg), mat, p);
  const torusX = (R, t, mat, p) => mesh(new THREE.TorusGeometry(R, t, 8, 40), mat, p, [0, Math.PI / 2, 0]);
  const boltAt = (g, p, dia, len, dir = 'y') => {
    const b = new THREE.Group();
    b.add(mesh(new THREE.CylinderGeometry(dia * .95, dia * .95, dia * .65, 6), M.bolt, [0, dia * .33, 0]));
    b.add(mesh(new THREE.CylinderGeometry(dia / 2, dia / 2, len, 10), M.bolt, [0, -len / 2, 0]));
    const R = { y: [0, 0, 0], '-y': [Math.PI, 0, 0], x: [0, 0, -Math.PI / 2], '-x': [0, 0, Math.PI / 2] }[dir];
    b.rotation.set(...R); b.position.set(...p); g.add(b);
  };
  const part = (id, name, obj, stripEx, o = {}) => { obj.name = id; parts.push({ id, name, sys: 'strip', obj, ex: V(...stripEx), stripEx: V(...stripEx), tags: ['pt', 'engine', 'strip', ...(o.tags || [])], qty: o.qty || 1, mat: o.mat || '', size: o.size || '', conf: o.conf || 'est', note: o.note || '', hidden: true }); };
  const holeRing = (y, mat) => { const g = new THREE.Group(); for (const x of CX) g.add(mesh(new THREE.CircleGeometry(BORE / 2, 32), mat, [x, y, ZC], [-Math.PI / 2, 0, 0])); return g; };
  const dark = materialFactory(0x0d0f12, { roughness: .9, metalness: .1 }, 'cast');

  // block with its bores showing on the deck
  {
    const g = new THREE.Group();
    g.add(box(0.40, DECK - 0.33, 0.22, M.cast, [XC, (DECK + 0.33) / 2, ZC]));
    g.add(holeRing(DECK + 0.0005, dark));
    g.add(box(0.10, 0.12, 0.05, M.cast, [XC + 0.09, 0.45, ZC + 0.13]));          // oil filter / cooler boss
    part('blk', 'Cylinder block (aluminium, cast-iron liners)', g, [0, 0, 0], { mat: 'Die-cast aluminium, thin cast-iron liners', size: 'Bore 74.5 mm, stroke 80.0 mm, 1,395 cc', conf: 'pub', note: 'Bore, stroke and capacity are published EA211 figures. External shape simplified.' });
  }
  // crankshaft with throws, and the main bearing ladder
  {
    const g = new THREE.Group();
    g.add(cylX(0.024, 0.46, M.steel, [XC, CRANK, ZC]));
    CX.forEach((x, i) => { const up = (i === 0 || i === 3) ? 1 : -1;
      g.add(box(0.016, 0.10, 0.07, M.steel, [x - 0.03, CRANK + up * 0.02, ZC]), box(0.016, 0.10, 0.07, M.steel, [x + 0.03, CRANK + up * 0.02, ZC]));
      g.add(cylX(0.021, 0.05, M.alu, [x, CRANK + up * STROKE / 2, ZC])); });
    part('crankshaft', 'Crankshaft', g, [0, -0.20, 0.25], { mat: 'Forged steel (est.)', size: 'Stroke 80.0 mm (published)', note: 'Five main bearings (est.). Throws shown for cylinders 1 and 4 up, 2 and 3 down.' });
  }
  {
    const g = new THREE.Group(); g.add(box(0.40, 0.03, 0.20, M.cast, [XC, CRANK - 0.045, ZC]));
    const b = new THREE.Group(); for (let i = 0; i < 5; i++) for (const dz of [-0.06, 0.06]) boltAt(b, [XC - 0.164 + i * PITCH, CRANK - 0.06, ZC + dz], 0.009, 0.08, '-y');
    part('ladder', 'Main bearing ladder frame', g, [0, -0.28, 0.25], { mat: 'Aluminium (est.)' });
    part('bolts_main', 'Main bearing bolts', b, [0, -0.36, 0.25], { tags: ['fastener'], qty: 10, size: 'M9 est.', note: 'Stretch bolts: replace. Torque and angle: erWin.' });
  }
  // pistons and connecting rods
  {
    const g = new THREE.Group();
    CX.forEach((x, i) => { const up = (i === 0 || i === 3) ? 1 : -1, pinY = DECK - 0.06 + (up > 0 ? 0 : -STROKE);
      g.add(cylY(BORE / 2 * 0.985, 0.05, M.alu, [x, pinY + 0.02, ZC], 32));
      for (const dy of [0.038, 0.030, 0.022]) g.add(mesh(new THREE.TorusGeometry(BORE / 2 * 0.99, 0.0012, 4, 32), M.steel, [x, pinY + dy, ZC], [Math.PI / 2, 0, 0]));
      const rodLen = pinY - (CRANK + up * STROKE / 2);
      g.add(box(0.016, rodLen, 0.022, M.steel, [x, pinY - rodLen / 2, ZC])); });
    part('pistons', 'Pistons, rings and connecting rods', g, [0, 0.22, -0.40], { qty: 4, mat: 'Aluminium pistons, steel rods', size: 'Ø 74.5 mm (published)', note: 'Three rings per piston: two compression, one oil control. Rods shown simplified.' });
  }
  // crank seals
  {
    const a = new THREE.Group(); a.add(torusX(0.034, 0.005, M.seal, [XC + 0.215, CRANK, ZC]));
    part('seal_crank_belt', 'Crankshaft oil seal, timing-belt end', a, [0.40, -0.20, 0.25], { tags: ['seal'], mat: 'PTFE lip seal (est.)', note: 'Replace whenever the timing belt sprocket comes off.' });
    const b = new THREE.Group(); b.add(torusX(0.046, 0.005, M.seal, [XC - 0.215, CRANK, ZC]));
    part('seal_crank_fly', 'Crankshaft oil seal, flywheel end', b, [-0.40, -0.20, 0.25], { tags: ['seal'], mat: 'PTFE lip seal with carrier (est.)' });
  }
  // sump, oil pump, sealant line
  {
    const g = new THREE.Group(); g.add(box(0.38, 0.11, 0.21, M.alu, [XC, 0.27, ZC])); g.add(cylY(0.011, 0.012, M.steel, [XC - 0.12, 0.21, ZC + 0.05], 6));
    part('sump', 'Oil sump with drain plug', g, [0, -0.46, 0.25], { mat: 'Aluminium upper / steel lower (est.)', note: 'Capacity about 4 litres with filter (est.; check the service data).' });
    const s = new THREE.Group(); s.add(box(0.38, 0.003, 0.21, M.seal, [XC, 0.327, ZC]));
    part('seal_sump', 'Sump sealant bead', s, [0, -0.40, 0.25], { tags: ['seal'], note: 'Liquid sealant, not a cut gasket (est.). Clean both faces and apply a fresh bead on refit.' });
    const b = new THREE.Group(); for (let i = 0; i < 8; i++) for (const dz of [-0.095, 0.095]) boltAt(b, [XC - 0.17 + i * 0.0486, 0.22, ZC + dz], 0.006, 0.03, '-y');
    part('bolts_sump', 'Sump bolts', b, [0, -0.54, 0.25], { tags: ['fastener'], qty: 16, size: 'M6 est.' });
    const p = new THREE.Group(); p.add(box(0.09, 0.05, 0.08, M.cast, [XC + 0.08, 0.30, ZC + 0.03]));
    part('oil_pump', 'Oil pump (chain-driven, in the sump)', p, [0.15, -0.40, 0.45], { mat: 'Cast aluminium', note: 'Variable-displacement vane pump driven by a short chain from the crank (est. for EA211).' });
  }
  // head gasket, head with valves and camshafts
  {
    const hg = new THREE.Group(); hg.add(box(0.40, 0.003, 0.22, M.seal, [XC, DECK + 0.0015, ZC]));
    part('head_gasket', 'Cylinder head gasket', hg, [0, 0.22, 0], { tags: ['seal'], mat: 'Multi-layer steel', note: 'Always replaced when the head comes off.' });
    const h = new THREE.Group(); h.add(box(0.40, 0.11, 0.22, M.cast, [XC, DECK + 0.058, ZC]));
    h.add(box(0.30, 0.05, 0.03, M.cast, [XC, DECK + 0.05, ZC - 0.125]));                 // exhaust manifold integrated in head
    part('head', 'Cylinder head (exhaust manifold cast in)', h, [0, 0.36, 0], { mat: 'Aluminium', note: 'DOHC, four valves per cylinder (published). On the EA211 the exhaust manifold is cast into the head.' });
    const v = new THREE.Group();
    CX.forEach(x => { for (const dx of [-0.017, 0.017]) for (const dz of [-0.03, 0.03]) {
      v.add(cylY(0.0025, 0.10, M.steel, [x + dx, DECK + 0.07, ZC + dz], 8));
      v.add(cylY(0.012, 0.002, M.steel, [x + dx, DECK + 0.02, ZC + dz], 16));
      v.add(mesh(new THREE.TorusGeometry(0.008, 0.002, 4, 12), M.steel, [x + dx, DECK + 0.10, ZC + dz], [Math.PI / 2, 0, 0])); } });
    part('valves', 'Valves, springs and stem seals', v, [0, 0.50, 0], { qty: 16, mat: 'Steel', note: 'Four valves per cylinder (published). Stem seals are replaced whenever the valves come out.' });
    const c = new THREE.Group();
    for (const dz of [-0.03, 0.03]) { c.add(cylX(0.013, 0.42, M.steel, [XC, DECK + 0.125, ZC + dz])); CX.forEach(x => { for (const dx of [-0.017, 0.017]) c.add(mesh(new THREE.CylinderGeometry(0.019, 0.019, 0.012, 16), M.alu, [x + dx, DECK + 0.128, ZC + dz], [0, 0, Math.PI / 2])); }); }
    part('camshafts', 'Camshafts, intake and exhaust (in a cam housing)', c, [0, 0.60, 0], { qty: 2, mat: 'Assembled steel camshafts (est.)', note: 'On the EA211 the camshafts sit in a separate housing bolted to the head (est.).' });
    const b = new THREE.Group(); for (let i = 0; i < 5; i++) for (const dz of [-0.085, 0.085]) boltAt(b, [XC - 0.164 + i * PITCH, DECK + 0.118, ZC + dz], 0.010, 0.14, 'y');
    part('bolts_head', 'Cylinder head bolts', b, [0, 0.70, 0], { tags: ['fastener'], qty: 10, size: 'M10 stretch bolts (est.)', note: 'Torque-to-yield: always replace. Tightening sequence and angle: erWin.' });
    const cg = new THREE.Group(); cg.add(box(0.39, 0.003, 0.21, M.seal, [XC, DECK + 0.150, ZC]));
    part('seal_cam', 'Camshaft cover sealant', cg, [0, 0.78, 0], { tags: ['seal'], note: 'Liquid sealant on the cam housing (est.).' });
    const cc = new THREE.Group(); cc.add(box(0.39, 0.04, 0.21, M.dark, [XC, DECK + 0.172, ZC]));
    part('cam_cover', 'Camshaft cover', cc, [0, 0.90, 0], { mat: 'Plastic composite (est.)' });
    const cb = new THREE.Group(); for (let i = 0; i < 7; i++) for (const dz of [-0.095, 0.095]) boltAt(cb, [XC - 0.18 + i * 0.06, DECK + 0.193, ZC + dz], 0.006, 0.03, 'y');
    part('bolts_cam', 'Camshaft cover bolts', cb, [0, 1.02, 0], { tags: ['fastener'], qty: 14, size: 'M6 est.' });
    const sp = new THREE.Group(); CX.forEach(x => { sp.add(cylY(0.007, 0.06, M.alu, [x, DECK + 0.21, ZC], 12)); sp.add(cylY(0.011, 0.012, M.steel, [x, DECK + 0.185, ZC], 6)); });
    part('spark_plugs', 'Spark plugs', sp, [0, 1.14, 0], { qty: 4, mat: 'Iridium tip (est.)', note: 'Change interval: service schedule.' });
    const inj = new THREE.Group(); CX.forEach(x => inj.add(mesh(new THREE.CylinderGeometry(0.007, 0.007, 0.08, 10), M.steel, [x, DECK + 0.04, ZC + 0.125], [-0.9, 0, 0])));
    part('injectors', 'Direct fuel injectors and seals', inj, [0, 0.42, 0.30], { qty: 4, note: 'High-pressure direct injection (published for TSI). Each injector has a combustion seal ring: replace on refit.' });
  }
  // timing belt, sprockets, tensioner, cover; coolant pump and thermostat
  {
    const g = new THREE.Group(); const xb = XC + 0.225;
    g.add(cylX(0.028, 0.025, M.steel, [xb, CRANK, ZC]));
    for (const dz of [-0.03, 0.03]) g.add(cylX(0.05, 0.022, M.steel, [xb, DECK + 0.125, ZC + dz]));
    g.add(cylX(0.022, 0.02, M.alu, [xb, 0.50, ZC + 0.06]));
    const belt = mesh(new THREE.TorusGeometry(0.15, 0.004, 4, 60), M.dark, [xb + 0.004, 0.52, ZC], [0, Math.PI / 2, 0]); belt.scale.set(1, 1.6, 0.9); g.add(belt);
    part('timing', 'Timing belt, sprockets and tensioner', g, [0.36, 0.10, 0], { mat: 'Reinforced rubber belt', note: 'EA211 uses a toothed timing belt (published). Belt, tensioner and idler are replaced as a kit at the service interval.' });
    const c = new THREE.Group(); c.add(box(0.02, 0.36, 0.20, M.dark, [xb + 0.03, 0.53, ZC]));
    part('timing_cover', 'Timing belt cover', c, [0.52, 0.10, 0], { mat: 'Plastic (est.)' });
    const w = new THREE.Group(); w.add(box(0.07, 0.07, 0.06, M.dark, [XC - 0.16, DECK + 0.02, ZC - 0.14]));
    part('coolant_pump', 'Coolant pump and thermostat housing', w, [-0.25, 0.25, -0.30], { note: 'On the EA211 the coolant pump sits in a combined housing driven by a small belt from the exhaust camshaft (published).' });
    const o = new THREE.Group(); o.add(torusX(0.026, 0.003, M.seal, [XC - 0.16, DECK + 0.02, ZC - 0.10]));
    part('seal_coolant_pump', 'Coolant pump housing O-ring', o, [-0.25, 0.25, -0.18], { tags: ['seal'] });
  }
  return { parts };
}
