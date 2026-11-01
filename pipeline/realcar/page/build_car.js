// build_car.js: the rest of the car, part by part: its interior, suspension and steering, brakes and wheels,
// wiring and lights, exhaust and fuel tank, round its engine (build_engine.js's, drawn here in one piece) and
// gearbox, inside a see-through body. Its measurements are the car's published ones (CFG.car); the parts are
// drawn to fit them. Defines CAR for page/parts.html.
// The car's axes: x forward, y up, z to the right; the ground at y 0, the middle between the axles at x 0.
const CAR = (() => {
  const C = CFG.car;
  const LEN = C.length, WID = C.width, HGT = C.height, WBASE = C.wheelbase, TF = C.track_front, TRK = C.track_rear;
  const RT = C.tyre_radius, TYW = C.tyre_width, YW = RT;
  const FX = WBASE / 2, RX = -WBASE / 2, XN = FX + C.front_overhang, XB = RX - C.rear_overhang;
  const DS = C.drive_side === 'left' ? -1 : 1;          // the driver's side
  const XBH = FX - 0.335;                              // the bulkhead between the engine and the cabin
  const HW = WID / 2;
  const EX = FX + 0.17, EY = 0.40, EZ = 0.13;          // the engine's crank, its middle
  const GZ0 = EZ - 0.24;                               // the gearbox's face against the engine
  const HUBF = TF / 2 + C.wheel_offset, HUBR = TRK / 2 + C.wheel_offset;   // the hubs' faces

  // ── materials of the rest of the car ──
  const glass = (color, opacity, rough = 0.05) => { const m = mat(color, rough, 0.0, { transparent: true, opacity, depthWrite: false, side: THREE.DoubleSide }); m.userData.glass = opacity; m.userData.side = THREE.DoubleSide; return m; };
  Object.assign(M, {
    eblack: surf(mat(0x1d1e20, 0.52, 0.5), { grain: 3200, depth: 0.06, mottle: 14, tint: 0.12, rmot: 0.15 }),
    paintBlack: surf(mat(0x151617, 0.36, 0.45), { grain: 4000, depth: 0.03, mottle: 18, tint: 0.06, rmot: 0.08 }),
    chrome: mat(0xd6d9dc, 0.12, 1.0),
    disc: surf(mat(0x8d9093, 0.34, 0.9), { grain: 3800, depth: 0.04, mottle: 30, tint: 0.1, rust: [0x5f4433, 0.05], rmot: 0.12 }),
    caliper: surf(mat(0x3f3b37, 0.72, 0.55), { grain: 1800, depth: 0.25, mottle: 12, tint: 0.2, rust: [0x6a4129, 0.16], rmot: 0.15 }),
    tyre: surf(mat(0x171717, 0.9, 0.0), { grain: 8000, depth: 0.1, mottle: 6, tint: 0.06 }),
    wheelSteel: surf(mat(0x878b90, 0.45, 0.65, { side: THREE.DoubleSide }), { grain: 4000, depth: 0.03, mottle: 16, tint: 0.06 }),
    trimSilver: surf(mat(0xb7bbbf, 0.3, 0.55), { grain: 6000, depth: 0.02, mottle: 20, tint: 0.04 }),
    exhaust: surf(mat(0x77797a, 0.58, 0.8), { grain: 3000, depth: 0.08, mottle: 8, tint: 0.2, rust: [0x5c3d28, 0.12], rmot: 0.2 }),
    shield: surf(mat(0xb6b9bb, 0.42, 0.85), { grain: 700, depth: 0.55, mottle: 10, tint: 0.08 }),
    dash: surf(mat(0x27292c, 0.74, 0.0), { grain: 9000, depth: 0.22, mottle: 10, tint: 0.05 }),
    trimGrey: surf(mat(0x45484d, 0.76, 0.0), { grain: 9000, depth: 0.2, mottle: 10, tint: 0.05 }),
    cloth: surf(mat(0x3a3e45, 0.96, 0.0), { grain: 14000, depth: 0.35, mottle: 40, tint: 0.1 }),
    carpet: surf(mat(0x232427, 1.0, 0.0), { grain: 16000, depth: 0.5, mottle: 20, tint: 0.12 }),
    clothInsert: surf(mat(0x4a4f58, 0.97, 0.0), { grain: 20000, depth: 0.45, mottle: 160, tint: 0.22 }),
    leather: surf(mat(0x1b1c1e, 0.55, 0.0), { grain: 12000, depth: 0.25, mottle: 20, tint: 0.05 }),
    loom: surf(mat(0x121314, 0.62, 0.0), { grain: 2600, depth: 0.6, mottle: 10, tint: 0.05 }),
    wireRed: surf(mat(0x8a1d18, 0.5, 0.0), { grain: 6000, depth: 0.05, mottle: 20, tint: 0.05 }),
    wireBrown: surf(mat(0x4b331f, 0.55, 0.3), { grain: 5000, depth: 0.25, mottle: 20, tint: 0.08 }),
    connector: surf(mat(0x2a2c2f, 0.55, 0.0), { grain: 7000, depth: 0.04, mottle: 20, tint: 0.05 }),
    connGrey: surf(mat(0x878a8d, 0.55, 0.0), { grain: 7000, depth: 0.04, mottle: 20, tint: 0.05 }),
    tank: surf(mat(0x202123, 0.6, 0.0), { grain: 5000, depth: 0.08, mottle: 8, tint: 0.06 }),
    lens: glass(0xeef3f6, 0.28),
    lensRed: glass(0xa3121a, 0.72, 0.1),
    lensAmber: glass(0xd98012, 0.7, 0.1),
    tankWhite: glass(0xe7e2d4, 0.82, 0.4),
    reflector: mat(0xe3e6e9, 0.07, 1.0),
    bulb: mat(0xfff6dc, 0.2, 0.0, { emissive: 0xfff0c8, emissiveIntensity: 0.25 }),
    redBtn: mat(0xb3161c, 0.45, 0.0),
    paint: surf(new THREE.MeshPhysicalMaterial({ color: 0xa6abb0, metalness: 0.6, roughness: 0.34, clearcoat: 1, clearcoatRoughness: 0.07, side: THREE.DoubleSide }),
      { grain: 2600, depth: 0.006, mottle: 5, tint: 0.012 }),
    glassSide: glass(0x121a1f, 0.62, 0.04),
    glassScreen: glass(0x1b272e, 0.45, 0.03),
    underseal: surf(mat(0x2a2b2d, 0.85, 0.1, { side: THREE.DoubleSide }), { grain: 2000, depth: 0.3, mottle: 10, tint: 0.1 }),
    trimBlack: surf(mat(0x151617, 0.58, 0.0, { side: THREE.DoubleSide }), { grain: 9000, depth: 0.12, mottle: 10, tint: 0.05 }),
    plateWhite: mat(0xf2f2ee, 0.4, 0.0), plateYellow: mat(0xf0c21a, 0.4, 0.0),
    fuseBlue: mat(0x2554b8, 0.4, 0.0), fuseRed: mat(0xc0281e, 0.4, 0.0), fuseYellow: mat(0xd9b21a, 0.4, 0.0),
  });
  M.reflector.side = THREE.DoubleSide;
  for (const m of Object.values(M)) if (m.side === THREE.DoubleSide) m.userData.side = THREE.DoubleSide;
  const ghost = mat(0x93a8bc, 0.25, 0.25, { transparent: true, opacity: 0.06, depthWrite: false, side: THREE.DoubleSide });
  ghost.userData.glass = 0.06; ghost.userData.side = THREE.DoubleSide;
  ghost.onBeforeCompile = sh => {
    sh.fragmentShader = sh.fragmentShader.replace('#include <color_fragment>', `#include <color_fragment>
      float rimF = 1.0 - abs(dot(normalize(vNormal), normalize(vViewPosition)));
      diffuseColor.a = clamp(diffuseColor.a + pow(rimF, 3.0) * 0.32, 0.0, 0.45);`);
  };

  // ── shapes ──
  const V3 = (x, y, z) => new THREE.Vector3(x, y, z);
  const UP = V3(0, 1, 0);
  const latheZ = (pts, seg = 32) => latheY(pts, seg).rotateX(Math.PI / 2);          // about the z axis, outward along +z
  const torusZ = (r, tube, x = 0, y = 0, z = 0, rs = 8, ts = 36) => new THREE.TorusGeometry(r, tube, rs, ts).translate(x, y, z);
  // a shape made along +y from 0, set from A towards B
  function along(g, A, B) {
    const a = V3(...A), d = V3(...B).sub(a).normalize();
    g.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(UP, d)); g.translate(a.x, a.y, a.z); return g;
  }
  const dist = (A, B) => V3(...A).distanceTo(V3(...B));
  const rodG = (A, B, r, seg = 12) => along(cylY(r, dist(A, B), 0, 0, 0, seg), A, B);
  // a rounded box, its rounding no more than its sizes allow
  function rbox(x0, x1, y0, y1, z0, z1, r) {
    const m = 0.45 * Math.min(x1 - x0, y1 - y0, z1 - z0);
    r = Math.min(r, m);
    return slabY(x0, z0, x1, z1, y0, y1, r, r, [], r);
  }
  // rubber bellows (a boot) along +y: LEN long, from radius R0 to R1, RIBS folds
  function bellowsG(r0, r1, len, ribs) {
    const pts = [[0.0001, 0], [r0, 0]];
    for (let k = 0; k <= ribs * 2; k++) { const f = k / (ribs * 2), r = r0 + (r1 - r0) * f; pts.push([r * (k % 2 ? 1.16 : 1), len * (0.04 + 0.92 * f)]); }
    pts.push([r1, len], [0.0001, len]);
    return latheY(pts, 28);
  }
  // a part built about +z (outward) at the origin, turned for side S (the left side faces -z)
  const sideZ = (g, s) => (s < 0 ? g.rotateY(Math.PI) : g);
  // a coil spring from A to B
  const coilG = (A, B, r, wire, turns) => along(springG(r, dist(A, B), wire, turns), A, B);
  // a frame round a wheel: radial u at angle T (from forward, toward up), tangential v, and the axle's z
  function wheelFrame(cx, cy, T) {
    const u = V3(Math.cos(T), Math.sin(T), 0), v = V3(-Math.sin(T), Math.cos(T), 0);
    return new THREE.Matrix4().makeBasis(u, v, V3(0, 0, 1)).setPosition(cx, cy, 0);
  }

  const GROUPS = ['Body panels', 'Glass', 'Body trim', 'Engine and gearbox', 'Cooling and air', 'Front suspension', 'Rear suspension', 'Steering', 'Driveshafts',
    'Brakes', 'Wheels and tyres', 'Seats and belts', 'Dashboard and controls', 'Pedals and levers', 'Trim and carpet', 'Heater',
    'Battery and power', 'Harnesses', 'Lights', 'Switches, relays and fuses', 'Wipers', 'Exhaust', 'Fuel tank and lines'];
  const SYSTEMS = [
    { key: 'body', label: 'Body and glass', groups: ['Body panels', 'Glass', 'Body trim'] },
    { key: 'interior', label: 'Interior', groups: ['Seats and belts', 'Dashboard and controls', 'Pedals and levers', 'Trim and carpet', 'Heater'] },
    { key: 'susp', label: 'Suspension and steering', groups: ['Front suspension', 'Rear suspension', 'Steering', 'Driveshafts'] },
    { key: 'brakes', label: 'Brakes and wheels', groups: ['Brakes', 'Wheels and tyres'] },
    { key: 'wiring', label: 'Wiring and lights', groups: ['Battery and power', 'Harnesses', 'Lights', 'Switches, relays and fuses', 'Wipers'] },
    { key: 'exhaust', label: 'Exhaust', groups: ['Exhaust'] },
    { key: 'fuel', label: 'Fuel tank', groups: ['Fuel tank and lines'] },
    { key: 'engine', label: 'Engine and gearbox', groups: ['Engine and gearbox', 'Cooling and air'] },
  ];
  const sideName = s => (s > 0 ? 'right' : 'left');
  const extras = [];
  const engMat = new THREE.Matrix4().set(0, 0, -1, EX, 0, 1, 0, EY, -1, 0, 0, EZ, 0, 0, 0, 1);   // the engine's axes to the car's
  const toCar = v => V3(...v).applyMatrix4(engMat);
  const wheelSpin = (p, s) => a => { p.obj.rotation.z = -a * 0.5; };

  // ── the body: one surface lofted from nose to tail, cut into its panels along their shut lines. Each section
  //    is a fixed run of points round its right half (t): 0 to 0.08 under the sill, to 0.16 its corner, to 0.42
  //    the lower side up to the shoulder, to 0.58 up to the waist, to 0.82 the glasshouse's side (or the wing's
  //    top, ahead of the windscreen), to 0.9 the roof's edge, to 1 across the roof (or the bonnet) to the middle ──
  function curve(keys) {                   // a smooth curve through KEYS [x, v] (monotone cubic)
    const k = keys.slice().sort((a, b) => a[0] - b[0]), n = k.length, d = [], m = [];
    for (let i = 0; i < n - 1; i++) d.push((k[i + 1][1] - k[i][1]) / (k[i + 1][0] - k[i][0]));
    for (let i = 0; i < n; i++) m.push(i === 0 ? d[0] : i === n - 1 ? d[n - 2] : (d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2));
    for (let i = 0; i < n - 1; i++) {
      if (d[i] === 0) { m[i] = m[i + 1] = 0; continue; }
      const a = m[i] / d[i], b = m[i + 1] / d[i], q = a * a + b * b;
      if (q > 9) { const tq = 3 / Math.sqrt(q); m[i] = tq * a * d[i]; m[i + 1] = tq * b * d[i]; }
    }
    return x => {
      if (x <= k[0][0]) return k[0][1];
      if (x >= k[n - 1][0]) return k[n - 1][1];
      let i = 0; while (x > k[i + 1][0]) i++;
      const h = k[i + 1][0] - k[i][0], s = (x - k[i][0]) / h, s2 = s * s, s3 = s2 * s;
      return (2 * s3 - 3 * s2 + 1) * k[i][1] + (s3 - 2 * s2 + s) * h * m[i] + (-2 * s3 + 3 * s2) * k[i + 1][1] + (s3 - s2) * h * m[i + 1];
    };
  }
  // the Mk4's lines: the top along the middle (nose, bonnet, windscreen, roof, rear window, tail), the bottom,
  // the shoulder, the waist (the windows' bottom, the wings' top), the roof's (or bonnet's) half-width
  const TOP = curve([[XN, 0.6], [XN - 0.03, 0.68], [XN - 0.08, 0.745], [XN - 0.14, 0.775], [XN - 0.4, 0.85], [FX, 0.897], [0.97, 0.948], [0.885, 0.968],
    [0.84, 0.993], [0.22, 1.39], [0.12, 1.418], [-0.1, 1.438], [-0.35, HGT], [-0.7, 1.433], [-1.0, 1.408], [-1.25, 1.372], [-1.42, 1.34], [-1.52, 1.312], [-1.58, 1.288], [-1.84, 1.005], [-1.9, 0.99], [XB + 0.03, 0.96], [XB, 0.93]]);
  const BOT = curve([[XN, 0.36], [XN - 0.05, 0.3], [XN - 0.2, 0.26], [FX + 0.4, 0.24], [FX, 0.21], [0.5, 0.2], [-0.8, 0.2], [RX, 0.21], [RX - 0.4, 0.27], [XB + 0.1, 0.32], [XB, 0.38]]);
  const SHY = curve([[XN, 0.56], [XN - 0.3, 0.68], [FX, 0.74], [0, 0.76], [RX, 0.8], [XB, 0.8]]);
  const WAIST = curve([[XN, 0.56], [XN - 0.14, 0.73], [FX, 0.85], [0.97, 0.91], [0.85, 0.955], [0.3, 0.955], [-0.5, 0.97], [-1.2, 0.995], [-1.5, 1.0], [-1.84, 1.0], [XB, 0.92]]);
  const ROOFW = curve([[XN, 0.62], [FX, 0.72], [0.95, 0.74], [0.85, 0.7], [0.22, 0.6], [-0.6, 0.62], [-1.42, 0.58], [-1.84, 0.62], [XB, 0.62]]);
  const LN = 0.42, LT = 0.2;               // how far back the nose rounds, and forward the tail, in plan
  const plan = x => {
    let f = 1;
    if (x > XN - LN) { const u = Math.min(1, (x - (XN - LN)) / LN); f = Math.pow(Math.max(0, 1 - Math.pow(u, 2.8)), 1 / 2.8); }
    else if (x < XB + LT) { const u = Math.min(1, (XB + LT - x) / LT); f = Math.pow(Math.max(0, 1 - Math.pow(u, 3)), 1 / 3); }
    return HW * f;
  };
  function section(x, t) {                 // the right half's point T round the section at X: [z, y]
    const W = plan(x), k = W / HW, yt = TOP(x), yb = BOT(x);
    const belt = Math.min(WAIST(x), yt - 0.012), ysh = Math.min(SHY(x), belt - 0.04), y1 = Math.min(yb + 0.06, ysh - 0.03);
    const wb = W - 0.045 * k, wbelt = W - 0.03 * k, wr = Math.min(ROOFW(x) * k, wbelt - 0.05 * k), zA = Math.max(0, wb - 0.16 * k);
    const yE = yt - Math.min(0.035, (yt - belt) * 0.5), rz = Math.min(0.045 * k, Math.max(0, wbelt - wr));
    const seg = (t0, t1) => (t - t0) / (t1 - t0);
    let s;
    if (t < 0.08) { s = seg(0, 0.08); return [zA + (wb - 0.04 * k - zA) * s, yb]; }
    if (t < 0.16) { s = seg(0.08, 0.16) * Math.PI / 2; return [wb - 0.04 * k + 0.04 * k * Math.sin(s), yb + (y1 - yb) * (1 - Math.cos(s))]; }
    if (t < 0.42) { s = seg(0.16, 0.42); return [wb + (W - wb) * Math.sin(s * Math.PI / 2), y1 + (ysh - y1) * s]; }
    if (t < 0.58) { s = seg(0.42, 0.58); return [W - (W - wbelt) * (1 - Math.cos(s * Math.PI / 2)), ysh + (belt - ysh) * s]; }
    if (t < 0.82) { s = seg(0.58, 0.82); return [wbelt + (wr + rz - wbelt) * s + 0.01 * k * Math.sin(s * Math.PI), belt + (yE - belt) * s]; }
    if (t < 0.9) { s = seg(0.82, 0.9) * Math.PI / 2; return [wr + rz * Math.cos(s), yE + (yt - yE) * Math.sin(s)]; }
    s = seg(0.9, 1.0); return [wr * (1 - s), yt + 0.016 * k * (1 - (1 - s) * (1 - s))];
  }
  const SP3 = (x, t) => { const [z, y] = section(x, t); return [x, y, z]; };
  const NX = 330, NT = 84;
  const XS = Array.from({ length: NX + 1 }, (_, i) => XN + (XB - XN) * (1 - Math.cos(Math.PI * i / NX)) / 2);
  const TS = Array.from({ length: NT + 1 }, (_, j) => j / NT);
  const GRID = XS.map(x => TS.map(t => SP3(x, t)));
  function surfNormal(x, t) {              // outward, from the surface's slopes
    const dx = 0.002, dt = 0.002;
    const xa = Math.min(XN, x + dx), xb = Math.max(XB, x - dx), ta = Math.min(1, t + dt), tb = Math.max(0, t - dt);
    const px = V3(...SP3(xa, t)).sub(V3(...SP3(xb, t))), pt = V3(...SP3(x, ta)).sub(V3(...SP3(x, tb)));
    const n = pt.clone().cross(px);
    const p = V3(...SP3(x, t));
    if (n.lengthSq() < 1e-12) n.set(x > 0 ? 1 : -1, 0, 0);
    n.normalize();
    if (n.dot(p.clone().sub(V3(Math.max(XB + 0.3, Math.min(XN - 0.3, x)), 0.7, 0))) < 0) n.negate();
    return n;
  }
  // the surface where REGION(p, x, t) holds (the right half), its edges trimmed to the region's
  function patch(region) {
    const inside = GRID.map((row, i) => row.map((p, j) => (region(p, XS[i], TS[j]) ? 1 : 0)));
    const pos = [], nor = [];
    const cross = (a, b) => {               // where the region ends between params A (in) and B (out)
      let lo = 0, hi = 1;
      for (let it = 0; it < 12; it++) { const m = (lo + hi) / 2, x = a[0] + (b[0] - a[0]) * m, t = a[1] + (b[1] - a[1]) * m; if (region(SP3(x, t), x, t)) lo = m; else hi = m; }
      return [a[0] + (b[0] - a[0]) * lo, a[1] + (b[1] - a[1]) * lo];
    };
    for (let i = 0; i < NX; i++) for (let j = 0; j < NT; j++) {
      const c = [[i, j], [i + 1, j], [i + 1, j + 1], [i, j + 1]], ins = c.map(([a, b]) => inside[a][b]);
      if (!ins[0] && !ins[1] && !ins[2] && !ins[3]) continue;
      const poly = [];
      for (let e = 0; e < 4; e++) {
        const A = c[e], B2 = c[(e + 1) % 4], pa = [XS[A[0]], TS[A[1]]], pb = [XS[B2[0]], TS[B2[1]]];
        if (ins[e]) poly.push(pa);
        if (ins[e] !== ins[(e + 1) % 4]) poly.push(ins[e] ? cross(pa, pb) : cross(pb, pa));
      }
      if (poly.length < 3) continue;
      const P = poly.map(([x, t]) => SP3(x, t)), Nn = poly.map(([x, t]) => surfNormal(x, t));
      for (let q = 1; q < poly.length - 1; q++) {
        let tri = [0, q, q + 1];
        const a = V3(...P[0]), b = V3(...P[q]), cc = V3(...P[q + 1]);
        const fn = b.clone().sub(a).cross(cc.clone().sub(a));
        if (fn.dot(Nn[0].clone().add(Nn[q]).add(Nn[q + 1])) < 0) tri = [0, q + 1, q];
        for (const v of tri) { pos.push(...P[v]); nor.push(Nn[v].x, Nn[v].y, Nn[v].z); }
      }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3));
    return g;
  }
  // the left side's: mirrored across the middle, its triangles turned to face out again
  function mirrorZ(g) {
    const m = g.clone(), p = m.attributes.position.array, n = m.attributes.normal.array;
    for (let i = 0; i < p.length; i += 9) {
      for (let v = 0; v < 3; v++) { p[i + v * 3 + 2] *= -1; n[i + v * 3 + 2] *= -1; }
      for (let c = 0; c < 3; c++) { const a = i + 3 + c, b = i + 6 + c; [p[a], p[b]] = [p[b], p[a]]; [n[a], n[b]] = [n[b], n[a]]; }
    }
    m.attributes.position.needsUpdate = true; m.attributes.normal.needsUpdate = true;
    return m;
  }
  const both = g => merge(g, mirrorZ(g));
  // a panel's turned-in edge: along every edge only one triangle has, a strip D deep into the car, so the shut
  // lines between panels show as gaps with depth, and a panel taken off has its thickness
  function hem(g, d = 0.012) {
    const p = g.attributes.position.array, n = g.attributes.normal.array, k = i => `${Math.round(p[i] * 1e5)},${Math.round(p[i + 1] * 1e5)},${Math.round(p[i + 2] * 1e5)}`;
    const count = new Map(), edges = [];
    for (let i = 0; i < p.length; i += 9) for (let e = 0; e < 3; e++) {
      const a = i + e * 3, b = i + ((e + 1) % 3) * 3, ka = k(a), kb = k(b), key = ka < kb ? ka + '|' + kb : kb + '|' + ka;
      count.set(key, (count.get(key) || 0) + 1); edges.push([a, b, key]);
    }
    const pos = [], nor = [];
    for (const [a, b, key] of edges) {
      if (count.get(key) !== 1) continue;
      const A = V3(p[a], p[a + 1], p[a + 2]), B = V3(p[b], p[b + 1], p[b + 2]), na = V3(n[a], n[a + 1], n[a + 2]), nb = V3(n[b], n[b + 1], n[b + 2]);
      if (A.distanceToSquared(B) < 1e-12) continue;
      const A2 = A.clone().addScaledVector(na, -d), B2 = B.clone().addScaledVector(nb, -d);
      const out = na.clone().add(nb).normalize().cross(B.clone().sub(A)).normalize().negate();
      for (const v of [A, A2, B, B, A2, B2]) { pos.push(v.x, v.y, v.z); nor.push(out.x, out.y, out.z); }
    }
    const h = new THREE.BufferGeometry();
    h.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    h.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3));
    return merge(g, h);
  }
  const offsetG = (g, d) => { const m = g.clone(), p = m.attributes.position.array, n = m.attributes.normal.array; for (let i = 0; i < p.length; i++) p[i] += n[i] * d; m.attributes.position.needsUpdate = true; return m; };
  // where the surface is: its side's z at (x, y); its front's and back's x at (y, z)
  function sideZAt(x, y) {
    let i = 0; while (i < NX && XS[i] > x) i++;
    let best = null;
    for (let j = Math.round(NT * 0.16); j <= Math.round(NT * 0.82); j++) { const p = GRID[i][j]; if (!best || Math.abs(p[1] - y) < Math.abs(best[1] - y)) best = p; }
    return best[2];
  }
  function endX(y, z, front) {
    let best = null;
    for (let i = 0; i <= NX; i++) for (let j = 0; j <= NT; j++) {
      const p = GRID[i][j]; if (Math.abs(p[1] - y) > 0.012 || Math.abs(p[2] - Math.abs(z)) > 0.012) continue;
      if (!best || (front ? p[0] > best : p[0] < best)) best = p[0];
    }
    return best ?? (front ? XN : XB);
  }
  // the panels, as regions of the surface (right half; z >= 0), E shrinks a region by E (half the shut line)
  const GAP = 0.0025, dT = e => e / 1.9;
  const inArch = (x, y, t, e) => t < 0.62 && (Math.hypot(x - FX, y - YW) < 0.365 + e || Math.hypot(x - RX, y - YW) < 0.365 + e);
  const xRear = t => (t < 0.6 ? -1.06 : -1.06 + (t - 0.6) / 0.2 * 0.24);      // the rear door's back edge, up the C-pillar
  const REG = {
    grille: (p, x, t, e) => x > XN - 0.16 && p[2] < 0.245 - e && p[1] > 0.585 + e && p[1] < 0.725 - e,
    grilleLow: (p, x, t, e) => x > XN - 0.14 && p[2] < 0.42 - e && p[1] > 0.30 + e && p[1] < 0.37 - e,
    headlight: (p, x, t, e) => x > FX + 0.45 && p[1] > 0.585 + e && p[1] < 0.745 - e && p[2] > 0.255 + e && p[2] < 0.79 - e && t > 0.2,
    bumperF: (p, x, t, e) => x > FX + 0.3 + e && p[1] < 0.565 - e && !inArch(x, p[1], t, -e) && !REG.grilleLow(p, x, t, -e),
    bonnet: (p, x, t, e) => t > 0.8 + dT(e) && x > 0.905 + e && p[1] > 0.75 + e && !REG.headlight(p, x, t, -e) && !REG.grille(p, x, t, -e),
    wing: (p, x, t, e) => x > 0.935 + e && t > 0.17 + dT(e) && t < 0.8 - dT(e) && p[2] > 0.6 && !inArch(x, p[1], t, -e) && !REG.bumperF(p, x, t, -e) && !REG.headlight(p, x, t, -e),
    windscreen: (p, x, t, e) => t > 0.87 + dT(e) && x < 0.885 - e && x > 0.21 + e,
    scuttle: (p, x, t, e) => t > 0.8 + dT(e) && x > 0.885 + e && x < 0.905 - e,      // the black plenum cover under the windscreen's foot
    glassF: (p, x, t, e) => t > 0.6 + dT(e) && t < 0.775 - dT(e) && x < 0.9 - e && x > -0.115 + e,
    glassR: (p, x, t, e) => t > 0.6 + dT(e) && t < 0.775 - dT(e) && x < -0.275 - e && x > xRear(t) + 0.035 + e,
    bpF: (p, x, t, e) => t > 0.6 + dT(e) && t < 0.8 - dT(e) && x < -0.115 - e && x > -0.165 + e,      // the B-pillar's black trims, one on each door
    bpR: (p, x, t, e) => t > 0.6 + dT(e) && t < 0.8 - dT(e) && x < -0.205 - e && x > -0.275 + e,
    doorF: (p, x, t, e) => x < 0.935 - e && x > -0.165 + e && t > 0.17 + dT(e) && t < 0.8 - dT(e) && !inArch(x, p[1], t, -e) && !REG.glassF(p, x, t, -e) && !REG.bpF(p, x, t, -e),
    doorR: (p, x, t, e) => x < -0.205 - e && x > xRear(t) + e && t > 0.17 + dT(e) && t < 0.8 - dT(e) && !inArch(x, p[1], t, -e) && !REG.glassR(p, x, t, -e) && !REG.bpR(p, x, t, -e),
    taillight: (p, x, t, e) => x < XB + 0.26 && p[1] > 0.74 + e && p[1] < 0.99 - e && p[2] > 0.52 + e,
    tailgate: (p, x, t, e) => x < -1.42 - e && p[2] < 0.5 - e && p[1] > 0.535 + e && (t > 0.8 + dT(e) || x < XB + 0.22) && !REG.rearGlass(p, x, t, -e),
    rearGlass: (p, x, t, e) => x < -1.47 - e && p[2] < 0.46 - e && p[1] > 1.04 + e && t > 0.86,
    bumperR: (p, x, t, e) => x < RX - 0.3 - e && p[1] < 0.535 - e && !inArch(x, p[1], t, -e),
    flap: (p, x, t, e) => p[2] > 0.3 && t > 0.3 && t < 0.6 && Math.hypot(x + 1.46, p[1] - 0.84) < 0.065 - e,
  };
  const CUTOUT = ['grille', 'grilleLow', 'headlight', 'bumperF', 'bonnet', 'wing', 'windscreen', 'scuttle', 'glassF', 'glassR', 'doorF', 'doorR', 'taillight', 'tailgate', 'rearGlass', 'bumperR'];
  const shellRegion = withFlap => (p, x, t) => !inArch(x, p[1], t, 0) && !CUTOUT.some(k => REG[k](p, x, t, -GAP)) && !(withFlap && REG.flap(p, x, t, -GAP));
  const panel = k => (p, x, t) => REG[k](p, x, t, GAP);

  function buildCar() {
    // ── kinds: [key, name, group, which way it comes off, how far] ──
    // engine and gearbox, cooling
    kind('engine', 'Engine: 1.9 TDI', 'Engine and gearbox', [0, 1, 0], 0.75);
    kind('gearbox', 'Gearbox (5-speed manual)', 'Engine and gearbox', [0, -0.4, -1], 0.4);
    kind('mount', 'Engine and gearbox mount', 'Engine and gearbox', [0, 1, 0], 0.12);
    kind('gear_cable', 'Gear-change cable', 'Engine and gearbox', [0, -1, 0], 0.12);
    kind('radiator', 'Radiator', 'Cooling and air', [1, 0.3, 0], 0.35);
    kind('fan', 'Radiator fan and cowl', 'Cooling and air', [-0.2, 1, 0], 0.3);
    kind('condenser', 'Air-conditioning condenser', 'Cooling and air', [1, 0, 0], 0.4);
    kind('rad_hose', 'Radiator hose', 'Cooling and air', [0, 1, 0], 0.15);
    kind('exp_tank', 'Coolant expansion tank', 'Cooling and air', [0, 1, 0], 0.2);
    kind('exp_cap', 'Coolant expansion tank cap', 'Cooling and air', [0, 1, 0], 0.12);
    kind('air_box', 'Air filter box', 'Cooling and air', [0, 1, 0], 0.25);
    kind('air_hose', 'Air intake hose', 'Cooling and air', [0, 1, 0], 0.2);
    // suspension and steering
    kind('subframe', 'Front subframe', 'Front suspension', [0, -1, 0], 0.3);
    kind('arm', 'Front lower control arm', 'Front suspension', [0, -0.5, 1], 0.25);
    kind('arm_bush_f', 'Control arm front bush', 'Front suspension', [0, -1, 0], 0.1);
    kind('arm_bush_r', 'Control arm rear bush', 'Front suspension', [0, -1, 0], 0.1);
    kind('ball_joint', 'Ball joint', 'Front suspension', [0, -1, 0], 0.08);
    kind('knuckle', 'Steering knuckle (hub carrier)', 'Front suspension', [0, 0, 1], 0.3);
    kind('hub_f', 'Front hub and bearing', 'Front suspension', [0, 0, 1], 0.24);
    kind('strut', 'Front strut (shock absorber)', 'Front suspension', [0, 1, 0.3], 0.35);
    kind('spring_f', 'Front coil spring', 'Front suspension', [0, 1, 0.5], 0.3);
    kind('top_mount', 'Strut top mount and bearing', 'Front suspension', [0, 1, 0], 0.25);
    kind('boot_f', 'Strut bump stop and dust boot', 'Front suspension', [0, 1, 0.3], 0.2);
    kind('arb', 'Front anti-roll bar', 'Front suspension', [0, -1, 0], 0.25);
    kind('arb_bush', 'Anti-roll bar bush and clamp', 'Front suspension', [0, -1, 0], 0.12);
    kind('drop_link', 'Anti-roll bar link', 'Front suspension', [0, -1, 0.3], 0.12);
    kind('link_bolt', 'Anti-roll bar link bolt', 'Front suspension', [0, -1, 0], 0.08);
    kind('beam', 'Rear axle (twist beam)', 'Rear suspension', [0, -1, 0], 0.3);
    kind('beam_bush', 'Rear axle mounting bush', 'Rear suspension', [0, -1, 0], 0.12);
    kind('spring_r', 'Rear coil spring', 'Rear suspension', [0, -1, 0.3], 0.25);
    kind('shock_r', 'Rear shock absorber', 'Rear suspension', [0, -1, 0.4], 0.3);
    kind('stub_axle', 'Rear stub axle', 'Rear suspension', [0, 0, 1], 0.22);
    kind('hub_r', 'Rear hub and bearing', 'Rear suspension', [0, 0, 1], 0.25);
    kind('rack', 'Steering rack (power assisted)', 'Steering', [0, -1, 0], 0.3);
    kind('rack_boot', 'Steering rack boot', 'Steering', [0, -1, 0], 0.1);
    kind('tie_rod', 'Track rod (inner)', 'Steering', [0, -0.3, 1], 0.14);
    kind('tie_end', 'Track rod end', 'Steering', [0, -0.3, 1], 0.12);
    kind('column', 'Steering column and shafts', 'Steering', [-1, 0.3, 0], 0.3);
    kind('ps_hose', 'Power steering hose', 'Steering', [0, 1, 0], 0.15);
    kind('ps_tank', 'Power steering fluid reservoir', 'Steering', [0, 1, 0], 0.2);
    kind('driveshaft', 'Driveshaft (axle assembly)', 'Driveshafts', [0, -0.4, 1], 0.3);
    kind('cv_boot', 'CV joint boot', 'Driveshafts', [0, -1, 0], 0.08);
    kind('cv_circlip', 'Driveshaft snap ring', 'Driveshafts', [0, 0, 1], 0.06);
    kind('axle_nut', 'Driveshaft nut', 'Driveshafts', [0, 0, 1], 0.08);
    // brakes and wheels
    kind('trim', 'Wheel trim', 'Wheels and tyres', [0, 0, 1], 0.3);
    kind('wheel_bolt', 'Wheel bolt', 'Wheels and tyres', [0, 0, 1], 0.2);
    kind('wheel', 'Wheel (steel)', 'Wheels and tyres', [0, 0, 1], 0.42);
    kind('tyre', 'Tyre 195/65 R15', 'Wheels and tyres', [0, 0, 1], 0.22);
    kind('caliper', 'Brake caliper', 'Brakes', [0, 0.3, 1], 0.2);
    kind('guide_bolt', 'Caliper guide bolt', 'Brakes', [0, 0, -1], 0.06);
    kind('pad_clip', 'Brake pad retaining clip', 'Brakes', [0, 0, 1], 0.1);
    kind('pad', 'Brake pad', 'Brakes', [0, 0.6, 1], 0.18);
    kind('carrier', 'Caliper carrier (bracket)', 'Brakes', [0, 0.4, 1], 0.16);
    kind('carrier_bolt', 'Caliper carrier bolt', 'Brakes', [0, 0, -1], 0.07);
    kind('disc_f', 'Front brake disc (vented)', 'Brakes', [0, 0, 1], 0.3);
    kind('disc_r', 'Rear brake disc', 'Brakes', [0, 0, 1], 0.3);
    kind('caliper_r', 'Rear brake caliper (with handbrake lever)', 'Brakes', [0, 0.3, 1], 0.2);
    kind('shield_f', 'Brake disc splash shield', 'Brakes', [0, 0, 1], 0.2);
    kind('brake_hose', 'Brake hose', 'Brakes', [0, 1, 0], 0.08);
    kind('brake_line', 'Brake pipe', 'Brakes', [0, -1, 0], 0.1);
    kind('hb_cable', 'Handbrake cable', 'Brakes', [0, -1, 0], 0.12);
    kind('servo', 'Brake servo and master cylinder', 'Brakes', [1, 0.4, 0], 0.25);
    kind('abs', 'ABS pump and control unit', 'Brakes', [0, 1, 0], 0.25);
    // interior
    kind('seat_f', 'Front seat', 'Seats and belts', [0, 0.25, 1], 0.9);
    kind('headrest', 'Head restraint', 'Seats and belts', [0, 1, 0], 0.25);
    kind('seat_rail', 'Seat runners', 'Seats and belts', [0, 0.2, 1], 0.6);
    kind('rear_cushion', 'Rear seat cushion', 'Seats and belts', [0, 0.4, 1], 0.8);
    kind('rear_back', 'Rear seat backrest (split)', 'Seats and belts', [0, 0.4, 1], 0.9);
    kind('belt', 'Seat belt', 'Seats and belts', [0, 0, 1], 0.2);
    kind('buckle', 'Seat belt buckle', 'Seats and belts', [0, 1, 0], 0.15);
    kind('dash', 'Dashboard', 'Dashboard and controls', [-1, 0.25, 0], 0.65);
    kind('cluster', 'Instrument cluster', 'Dashboard and controls', [-1, 0.3, 0], 0.25);
    kind('wheel_s', 'Steering wheel', 'Dashboard and controls', [-1, 0.2, 0], 0.3);
    kind('airbag', 'Driver’s airbag', 'Dashboard and controls', [-1, 0, 0], 0.15);
    kind('shroud', 'Steering column shroud and stalks', 'Dashboard and controls', [-1, 0, 0], 0.2);
    kind('radio', 'Radio', 'Dashboard and controls', [-1, 0, 0], 0.2);
    kind('hvac_ctl', 'Heater controls', 'Dashboard and controls', [-1, 0, 0], 0.18);
    kind('glovebox', 'Glovebox lid', 'Dashboard and controls', [-1, -0.3, 0], 0.18);
    kind('console', 'Centre console', 'Pedals and levers', [0, 1, 0], 0.4);
    kind('gear_lever', 'Gear lever, knob and gaiter', 'Pedals and levers', [0, 1, 0], 0.3);
    kind('handbrake', 'Handbrake lever', 'Pedals and levers', [0, 1, 0], 0.3);
    kind('pedal', 'Pedal', 'Pedals and levers', [-1, 0, 0], 0.25);
    kind('carpet', 'Carpet', 'Trim and carpet', [0, 1, 0], 0.5);
    kind('door_card', 'Door trim panel', 'Trim and carpet', [0, 0, 1], 0.4).only = true;
    kind('parcel', 'Parcel shelf', 'Trim and carpet', [0, 1, 0], 0.4);
    kind('mirror_i', 'Rear-view mirror', 'Trim and carpet', [0, -1, 0], 0.15);
    kind('visor', 'Sun visor', 'Trim and carpet', [0, -1, 0], 0.15);
    kind('heater', 'Heater box and blower', 'Heater', [-1, -0.3, 0], 0.5);
    // wiring and lights
    kind('battery', 'Battery', 'Battery and power', [0, 1, 0], 0.35);
    kind('batt_tray', 'Battery tray', 'Battery and power', [0, 1, 0], 0.25);
    kind('batt_fuse', 'Battery fuse box', 'Battery and power', [0, 1, 0], 0.15);
    kind('batt_cable', 'Battery positive cable', 'Battery and power', [0, 1, 0], 0.15);
    kind('earth', 'Earth strap', 'Battery and power', [0, 1, 0], 0.12);
    kind('starter', 'Starter motor', 'Battery and power', [1, 0, 0], 0.25);
    kind('starter_sol', 'Starter solenoid', 'Battery and power', [1, 0, 0], 0.12);
    kind('ecu', 'Engine control unit', 'Battery and power', [0, 1, 0], 0.25);
    kind('loom', 'Wiring harness', 'Harnesses', [0, 1, 0], 0.12);
    kind('abs_lead', 'ABS sensor lead', 'Harnesses', [0, 1, 0], 0.08);
    kind('headlight', 'Headlight', 'Lights', [1, 0, 0], 0.35);
    kind('taillight', 'Rear light', 'Lights', [-1, 0, 0], 0.3);
    kind('repeater', 'Side indicator repeater', 'Lights', [0, 0, 1], 0.12);
    kind('plate_lamp', 'Number plate light', 'Lights', [-1, 0, 0], 0.12);
    kind('brake_lamp', 'High-level brake light', 'Lights', [-1, 0, 0], 0.15);
    kind('horn', 'Horn', 'Lights', [1, 0, 0], 0.15);
    kind('fuse_box', 'Fuse box', 'Switches, relays and fuses', [-1, 0, 0], 0.2);
    kind('fuse', 'Fuses', 'Switches, relays and fuses', [-1, 0, 0], 0.1);
    kind('relay_plate', 'Relay carrier', 'Switches, relays and fuses', [0, -1, 0], 0.2);
    kind('relay_acc', 'Accessory power relay', 'Switches, relays and fuses', [0, -1, 0], 0.1);
    kind('relay_start', 'Starter relay', 'Switches, relays and fuses', [0, -1, 0], 0.1);
    kind('ign_switch', 'Ignition switch', 'Switches, relays and fuses', [-1, 0, 0], 0.12);
    kind('lock_cyl', 'Ignition lock cylinder', 'Switches, relays and fuses', [-1, 0, 0], 0.1);
    kind('col_lock', 'Steering column lock', 'Switches, relays and fuses', [-1, 0, 0], 0.12);
    kind('light_switch', 'Headlamp switch', 'Switches, relays and fuses', [-1, 0, 0], 0.12);
    kind('clutch_switch', 'Clutch starter safety switch', 'Switches, relays and fuses', [-1, 0, 0], 0.1);
    kind('wiper_motor', 'Wiper motor and linkage', 'Wipers', [0, 1, 0], 0.2);
    kind('wiper_arm', 'Wiper arm', 'Wipers', [0, 1, 0], 0.18);
    kind('wiper_blade', 'Wiper blade', 'Wipers', [0, 1, 0], 0.12);
    kind('wiper_cap', 'Wiper arm cap', 'Wipers', [0, 1, 0], 0.08);
    // exhaust, fuel
    kind('heat_shield', 'Heat shield', 'Exhaust', [0, -1, 0], 0.2);
    kind('exh_gasket', 'Exhaust gasket', 'Exhaust', [0, -1, 0], 0.08);
    kind('exh_nut', 'Exhaust flange nut', 'Exhaust', [0, -1, 0], 0.06);
    kind('downpipe', 'Downpipe', 'Exhaust', [0, -1, 0], 0.3);
    kind('front_pipe', 'Front pipe, flexible joint and catalytic converter', 'Exhaust', [0, -1, 0], 0.32);
    kind('mid_box', 'Centre pipe and middle silencer', 'Exhaust', [0, -1, 0], 0.32);
    kind('rear_box', 'Rear silencer and tailpipe', 'Exhaust', [0, -1, -0.2], 0.35);
    kind('exh_clamp', 'Exhaust clamp', 'Exhaust', [0, -1, 0], 0.1);
    kind('hanger', 'Exhaust rubber hanger', 'Exhaust', [0, -1, 0], 0.1);
    kind('fuel_tank', 'Fuel tank', 'Fuel tank and lines', [0, -1, 0], 0.4);
    kind('tank_strap', 'Fuel tank strap', 'Fuel tank and lines', [0, -1, 0], 0.25);
    kind('strap_spacer', 'Fuel tank strap spacer', 'Fuel tank and lines', [0, -1, 0], 0.15);
    kind('sender', 'Fuel pump and sender', 'Fuel tank and lines', [0, 1, 0], 0.25);
    kind('tank_seal', 'Fuel sender seal', 'Fuel tank and lines', [0, 1, 0], 0.14);
    kind('lock_ring', 'Fuel tank lock ring', 'Fuel tank and lines', [0, 1, 0], 0.19);
    kind('gravity_valve', 'Gravity (roll-over) valve', 'Fuel tank and lines', [0, 1, 0], 0.12);
    kind('filler', 'Filler neck', 'Fuel tank and lines', [0, -0.4, 1], 0.25);
    kind('fuel_cap', 'Fuel filler cap', 'Fuel tank and lines', [0, 0, 1], 0.15);
    kind('fuel_line', 'Fuel line', 'Fuel tank and lines', [0, -1, 0], 0.1);
    kind('fuel_filter', 'Fuel filter', 'Fuel tank and lines', [0, 1, 0], 0.18);
    kind('filter_plate', 'Fuel filter retainer plate', 'Fuel tank and lines', [0, 1, 0], 0.12);
    if (CFG.engine_url) TYPES.engine.link = ['Open the engine on its own, every part of it', CFG.engine_url];
    TYPES.engine.note = 'Drawn here in one piece; its own page takes it apart.';

    // ── the body and its glass ──
    kind('body_shell', 'Body shell (roof, pillars, sills, rear quarters, floor, bulkhead)', 'Body panels', [0, 0, 0], 0);
    kind('bonnet', 'Bonnet', 'Body panels', [0.25, 1, 0], 0.6);
    kind('wing', 'Front wing', 'Body panels', [0.15, 0.1, 1], 0.5);
    kind('bumper_f', 'Front bumper', 'Body panels', [1, -0.1, 0], 0.5);
    kind('grille', 'Radiator grille', 'Body panels', [1, 0.1, 0], 0.35);
    kind('grille_low', 'Lower grille', 'Body panels', [1, -0.2, 0], 0.15);
    kind('door_f', 'Front door', 'Body panels', [0, 0, 1], 0.6);
    kind('door_r', 'Rear door', 'Body panels', [0, 0, 1], 0.6);
    kind('tailgate', 'Tailgate', 'Body panels', [-1, 0.6, 0], 0.55);
    kind('bumper_r', 'Rear bumper', 'Body panels', [-1, -0.1, 0], 0.5);
    kind('fuel_flap', 'Fuel filler flap', 'Body panels', [0, 0, 1], 0.15);
    kind('windscreen', 'Windscreen', 'Glass', [0.4, 1, 0], 0.55);
    kind('door_glass', 'Door window', 'Glass', [0, 1, 0], 0.32);
    kind('rear_glass', 'Rear window (heated)', 'Glass', [-1, 0.5, 0], 0.25);
    kind('mirror', 'Door mirror', 'Body trim', [0, 0.3, 1], 0.25);
    kind('handle', 'Door handle', 'Body trim', [0, 0, 1], 0.12);
    kind('rub_strip', 'Door rubbing strip', 'Body trim', [0, 0, 1], 0.12);
    kind('arch_liner', 'Wheel arch liner', 'Body trim', [0, -0.3, 1], 0.35);
    kind('plate', 'Number plate', 'Body trim', [1, 0, 0], 0.15);
    kind('aerial', 'Aerial', 'Body trim', [0, 1, 0], 0.15);
    kind('b_trim', 'B-pillar trim', 'Body trim', [0, 0, 1], 0.1);
    kind('scuttle', 'Scuttle panel (plenum cover)', 'Body trim', [0, 1, 0], 0.2);
    {
      // the shell: everything the panels are not, its floor pan with the tunnel the exhaust runs in, the bulkhead,
      // the towers the struts' tops sit in
      const shell = hem(merge(patch(shellRegion(true)), mirrorZ(patch(shellRegion(false)))), 0.015);
      const tunnel = y0 => [[-0.74, y0], [-0.16, y0], [-0.11, 0.4], [0.11, 0.4], [0.16, y0], [0.74, y0]];
      const plateX = (pts, x0, x1, th) => extrudeX(zyShape([...pts, ...pts.map(([z, y]) => [z, y - th]).reverse()]), x1 - x0, x0, 4);
      const floorG = [plateX(tunnel(0.255), -0.62, XBH, 0.004), rbox(-0.624, -0.618, 0.25, 0.426, -0.74, 0.74, 0.001), rbox(-1.18, -0.62, 0.421, 0.426, -0.62, 0.62, 0.001),
        rbox(XB + 0.06, -1.18, 0.416, 0.421, -0.5, 0.5, 0.001),
        extrudeX(zyShape([[-0.74, 0.255], [-0.16, 0.255], [-0.11, 0.4], [0.11, 0.4], [0.16, 0.255], [0.74, 0.255], [0.74, 0.93], [-0.74, 0.93]]), 0.004, XBH, 4)];
      const towers = [-1, 1].map(s => latheY([[0.098, 0], [0.1, 0], [0.1, 0.2], [0.04, 0.205], [0.04, 0.2], [0.096, 0.196]], 32).translate(FX - 0.04, 0.635, s * 0.56));
      add('body_shell', 'Body shell', group([shell, M.paint], [merge(floorG), M.underseal], [merge(towers), M.paint]));
      add('bonnet', 'Bonnet', mesh(hem(both(patch(panel('bonnet')))), M.paint));
      const bf = add('bumper_f', 'Front bumper', mesh(hem(both(patch(panel('bumperF'))), 0.02), M.paint));
      add('grille_low', 'Lower grille', mesh(both(patch(panel('grilleLow'))), M.trimBlack), { parent: bf });
      const gr = both(patch(panel('grille'))), slats = [];
      for (const y of [0.615, 0.65, 0.685]) { const xg = endX(y, 0, true); slats.push(rbox(xg - 0.03, xg + 0.004, y - 0.006, y + 0.006, -0.235, 0.235, 0.004)); }
      add('grille', 'Radiator grille', group([gr, M.trimBlack], [merge(slats), M.trimBlack]));
      add('windscreen', 'Windscreen', mesh(both(patch(panel('windscreen'))), M.glassScreen));
      add('scuttle', 'Scuttle panel (plenum cover)', mesh(hem(both(patch(panel('scuttle'))), 0.02), M.trimBlack));
      const tg = add('tailgate', 'Tailgate', mesh(hem(both(patch(panel('tailgate')))), M.paint));
      add('rear_glass', 'Rear window (heated)', mesh(both(patch(panel('rearGlass'))), M.glassSide), { parent: tg });
      add('bumper_r', 'Rear bumper', mesh(hem(both(patch(panel('bumperR'))), 0.02), M.paint));
      add('fuel_flap', 'Fuel filler flap', mesh(hem(patch(panel('flap')), 0.006), M.paint));
      // plates: front white on the bumper, rear yellow on the tailgate
      const xf = endX(0.455, 0, true), xr = endX(0.625, 0, false);
      add('plate', 'Number plate, front', mesh(rbox(xf + 0.001, xf + 0.008, 0.4, 0.511, -0.26, 0.26, 0.003), M.plateWhite), { parent: bf });
      add('plate', 'Number plate, rear', mesh(rbox(xr - 0.008, xr - 0.001, 0.57, 0.681, -0.26, 0.26, 0.003), M.plateYellow), { parent: tg, dir: [-1, 0, 0] });
      const ay = TOP(-1.3) + 0.012;
      add('aerial', 'Aerial', group([rbox(-1.34, -1.26, ay - 0.004, ay + 0.012, -0.018, 0.018, 0.006), M.trimBlack], [rodG([-1.3, ay + 0.01, 0], [-1.62, ay + 0.2, 0], 0.003), M.trimBlack]));
      // each side: its wing, doors with their windows, handles and strips, its mirror, its arch liners
      const sideOf = (gR, s) => (s > 0 ? gR : mirrorZ(gR));
      const wingR = hem(patch(panel('wing'))), dfR = hem(patch(panel('doorF'))), drR = hem(patch(panel('doorR'))), gfR = patch(panel('glassF')), grR = patch(panel('glassR')), bfR = hem(patch(panel('bpF')), 0.006), brR = hem(patch(panel('bpR')), 0.006);
      for (const s of [-1, 1]) {
        const side = sideName(s), dz = [0, 0, s];
        add('wing', `Front wing, ${side}`, mesh(sideOf(wingR, s), M.paint), { dir: [0.15, 0.1, s] });
        const dF = add('door_f', `Front door, ${side}`, mesh(sideOf(dfR, s), M.paint), { dir: dz });
        const dR = add('door_r', `Rear door, ${side}`, mesh(sideOf(drR, s), M.paint), { dir: dz });
        add('door_glass', `Door window, front ${side}`, mesh(sideOf(gfR, s), M.glassSide), { parent: dF });
        add('door_glass', `Door window, rear ${side}`, mesh(sideOf(grR, s), M.glassSide), { parent: dR });
        add('b_trim', `B-pillar trim, front door ${side}`, mesh(sideOf(bfR, s), M.trimBlack), { parent: dF, dir: dz });
        add('b_trim', `B-pillar trim, rear door ${side}`, mesh(sideOf(brR, s), M.trimBlack), { parent: dR, dir: dz });
        for (const [d, x0, x1, hx] of [[dF, 0.88, -0.12, -0.075], [dR, -0.26, -1.02, -0.955]]) {
          const zs = sideZAt((x0 + x1) / 2, 0.6), zh = sideZAt(hx, 0.915);
          add('rub_strip', `Door rubbing strip, ${d === dF ? 'front' : 'rear'} ${side}`, mesh(sideOf(rbox(Math.min(x0, x1), Math.max(x0, x1), 0.583, 0.617, zs - 0.006, zs + 0.012, 0.007), s), M.trimBlack), { parent: d, dir: dz });
          add('handle', `Door handle, ${d === dF ? 'front' : 'rear'} ${side}`, mesh(sideOf(rbox(hx - 0.065, hx + 0.065, 0.9, 0.93, zh - 0.006, zh + 0.017, 0.009), s), M.paint), { parent: d, dir: dz });
        }
        const zm = sideZAt(0.86, 0.97);
        add('mirror', `Door mirror, ${side}`, group([sideOf(merge(rbox(0.83, 0.89, 0.95, 0.985, zm - 0.01, zm + 0.07, 0.01), rbox(0.8, 0.925, 0.95, 1.065, zm + 0.05, zm + 0.205, 0.035)), s), M.paint],
          [sideOf(rbox(0.794, 0.802, 0.958, 1.057, zm + 0.058, zm + 0.197, 0.008), s), M.reflector]), { parent: dF, dir: [0, 0.3, s] });
        for (const [ax, nm] of [[FX, 'front'], [RX, 'rear']]) {
          const liner = new THREE.CylinderGeometry(0.37, 0.37, 0.23, 40, 1, true, Math.PI - 1.95, 3.9).rotateX(Math.PI / 2).translate(ax, YW, s * 0.725);
          add('arch_liner', `Wheel arch liner, ${nm} ${side}`, mesh(liner, M.trimBlack), { dir: [0, -0.3, s] });
        }
      }
    }
    // the body's outline, see-through, while another part of the car is shown on its own
    extras.push({ label: 'Outline', obj: outline(), on: true, when: k => k !== 'all' && k !== 'body' });

    // ── engine (the engine page's, put together) and gearbox ──
    const engine = collect(() => ENGINE.build());
    engine.matrixAutoUpdate = false; engine.matrix.copy(engMat);
    const engObj = new THREE.Group(); engObj.add(engine);
    add('engine', 'Engine: 1.9 TDI (everything on it)', engObj);
    {
      const bell = latheZ([[0.05, -0.17], [0.112, -0.17], [0.125, -0.12], [0.158, -0.035], [0.168, -0.012], [0.166, 0], [0.05, 0]], 40).translate(EX, EY, GZ0);
      const diff = latheZ([[0.0001, -0.27], [0.06, -0.27], [0.09, -0.24], [0.1, -0.2], [0.1, -0.05], [0.075, -0.02], [0.0001, -0.02]], 36).translate(FX, YW, GZ0);
      const caseG = rbox(FX - 0.04, EX + 0.1, EY - 0.1, EY + 0.11, GZ0 - 0.4, GZ0 - 0.14, 0.03);
      const endCap = latheZ([[0.0001, -0.43], [0.07, -0.43], [0.085, -0.415], [0.085, -0.39], [0.0001, -0.39]], 32).translate(EX - 0.01, EY, GZ0);
      const ribs = [];
      for (let k = 0; k < 5; k++) ribs.push(rbox(FX + 0.02 + k * 0.05, FX + 0.028 + k * 0.05, EY - 0.115, EY + 0.12, GZ0 - 0.36, GZ0 - 0.15, 0.003));
      const tower = rbox(FX + 0.03, FX + 0.13, EY + 0.1, EY + 0.16, GZ0 - 0.32, GZ0 - 0.22, 0.012);
      const flanges = [latheZ([[0.0001, 0], [0.05, 0], [0.05, 0.018], [0.0001, 0.018]], 24).translate(FX, YW, GZ0 + 0.0),
        latheZ([[0.0001, 0], [0.05, 0], [0.05, 0.018], [0.0001, 0.018]], 24).translate(FX, YW, GZ0 - 0.29)];
      const bolts = [];
      for (let k = 0; k < 10; k++) { const a = k / 10 * TAU; bolts.push(hexY(0.0075, 0.008).rotateX(Math.PI / 2).translate(EX + 0.162 * Math.cos(a), EY + 0.162 * Math.sin(a), GZ0 - 0.008)); }
      add('gearbox', 'Gearbox, 5-speed manual (with its final drive)', group([merge(bell, diff, caseG, endCap, ...ribs, tower, ...flanges), M.aluCast], [merge(bolts), M.zinc]));
      // two cables from the lever forward under the car to the gearbox's change tower
      for (const [dz, nm] of [[-0.02, 'select'], [0.02, 'shift']]) {
        add('gear_cable', `Gear-change cable (${nm})`, mesh(hoseG([[0.13, 0.36, dz], [0.35, 0.27, dz], [0.75, 0.25, dz - 0.05], [FX - 0.15, 0.32, GZ0 - 0.2 + dz], [FX + 0.06, EY + 0.17, GZ0 - 0.27 + dz]], 0.0055, 60, 8), M.rubber));
      }
      // mounts: the timing-belt end's on top, the gearbox's, and the pendulum mount under it to the subframe
      add('mount', 'Engine mount (timing belt end)', group([merge(rbox(EX - 0.08, EX + 0.06, EY + 0.26, EY + 0.3, EZ + 0.2, EZ + 0.46, 0.008), rbox(EX - 0.05, EX + 0.03, EY + 0.3, EY + 0.36, EZ + 0.38, EZ + 0.5, 0.01)), M.aluCast],
        [latheY([[0.0001, 0], [0.04, 0], [0.042, 0.03], [0.035, 0.06], [0.0001, 0.06]], 24).translate(EX - 0.01, EY + 0.3, EZ + 0.44), M.rubber]));
      add('mount', 'Gearbox mount', group([rbox(FX - 0.02, FX + 0.12, EY + 0.11, EY + 0.17, GZ0 - 0.42, GZ0 - 0.32, 0.01), M.aluCast],
        [latheY([[0.0001, 0], [0.04, 0], [0.042, 0.03], [0.035, 0.05], [0.0001, 0.05]], 24).translate(FX + 0.05, EY + 0.17, GZ0 - 0.37), M.rubber]));
      add('mount', 'Pendulum mount (gearbox to subframe)', group([merge(rodG([FX - 0.02, 0.24, GZ0 - 0.06], [FX - 0.32, 0.24, -0.03], 0.012), cylZ(0.022, 0.03, GZ0 - 0.075, FX - 0.02, 0.24, 20)), M.forged],
        [cylZ(0.026, 0.035, -0.0475, FX - 0.32, 0.24, 20), M.rubber]));
    }
    // ── cooling and air: radiator, its fans, the condenser in front; the expansion tank; the air box ──
    {
      const x0 = XN - 0.36, rad = [rbox(x0, x0 + 0.032, 0.3, 0.7, -0.31, 0.31, 0.003)];
      const fins = [];
      for (let k = 0; k < 90; k++) fins.push(box(0.034, 0.39, 0.0012, x0 + 0.016, 0.5, -0.3 + k * 0.6 / 89));
      const tanks = [rbox(x0 - 0.01, x0 + 0.045, 0.28, 0.72, -0.37, -0.31, 0.01), rbox(x0 - 0.01, x0 + 0.045, 0.28, 0.72, 0.31, 0.37, 0.01),
        cylZ(0.016, 0.04, 0.37, x0 + 0.02, 0.66, 16), cylZ(0.016, 0.04, -0.41, x0 + 0.02, 0.34, 16)];
      add('radiator', 'Radiator', group([merge(rad), M.alu], [merge(fins), M.aluCast], [merge(tanks), M.plastic]));
      const cond = [rbox(x0 + 0.06, x0 + 0.078, 0.31, 0.66, -0.33, 0.3, 0.002)];
      for (let k = 0; k < 70; k++) cond.push(box(0.02, 0.34, 0.001, x0 + 0.069, 0.485, -0.32 + k * 0.6 / 69));
      add('condenser', 'Air-conditioning condenser', group([merge(cond), M.alu], [merge(cylY(0.014, 0.33, 0.32, x0 + 0.069, 0.31, 14), rodG([x0 + 0.069, 0.62, 0.31], [x0 - 0.2, 0.75, 0.42], 0.006)), M.aluCast]));
      const shroud = rbox(x0 - 0.065, x0 - 0.01, 0.31, 0.69, -0.3, 0.3, 0.015);
      const fanG = [];
      for (const [fz, fr] of [[-0.14, 0.13], [0.15, 0.11]]) {
        fanG.push(latheX([[0.0001, -0.03], [0.04, -0.03], [0.045, 0.0], [0.0001, 0.0]], 24).translate(x0 - 0.04, 0.5, fz));
        for (let b = 0; b < 7; b++) { const g = box(0.006, fr - 0.04, 0.035); g.translate(0, (fr + 0.04) / 2, 0); g.rotateY(0.5); g.rotateX(b / 7 * TAU); g.translate(x0 - 0.035, 0.5, fz); fanG.push(g); }
      }
      add('fan', 'Radiator fans and cowl', group([shroud, M.plastic], [merge(fanG), M.blackPaint]));
      // radiator hoses: the top from the thermostat housing on the engine's front, the bottom to the water pump
      add('rad_hose', 'Radiator hose (top)', mesh(merge(hoseG([[x0 - 0.01, 0.66, 0.39], [x0 - 0.12, 0.7, 0.36], [FX + 0.38, 0.62, 0.26], [FX + 0.3, 0.5, 0.2]], 0.018, 40, 16),
        torusX(0.02, 0.003, x0 - 0.02, 0.66, 0.39).rotateY(0)), M.rubber));
      add('rad_hose', 'Radiator hose (bottom)', mesh(hoseG([[x0 - 0.01, 0.34, -0.41], [x0 - 0.12, 0.3, -0.36], [FX + 0.36, 0.34, -0.05], [FX + 0.3, 0.4, 0.02]], 0.018, 40, 16), M.rubber));
      const tk = add('exp_tank', 'Coolant expansion tank', group([rbox(XBH + 0.12, XBH + 0.3, 0.71, 0.85, 0.42, 0.6, 0.025), M.tankWhite],
        [hoseG([[XBH + 0.2, 0.71, 0.5], [XBH + 0.28, 0.64, 0.4], [FX + 0.05, 0.62, 0.32]], 0.008, 20, 10), M.rubber]));
      add('exp_cap', 'Coolant expansion tank cap', mesh(merge(latheY([[0.0001, 0], [0.028, 0], [0.03, 0.006], [0.03, 0.022], [0.026, 0.026], [0.0001, 0.026]], 24),
        ...Array.from({ length: 10 }, (_, k) => box(0.004, 0.018, 0.006, 0.03 * Math.cos(k / 10 * TAU), 0.012, 0.03 * Math.sin(k / 10 * TAU)))), M.plastic), { parent: tk, pos: [XBH + 0.2, 0.85, 0.5] });
      // the air box: the filter inside it, its intake from behind the headlight, its hose to the turbo
      const ab = [rbox(XN - 0.62, XN - 0.38, 0.62, 0.74, -0.62, -0.36, 0.02), rbox(XN - 0.62, XN - 0.38, 0.74, 0.82, -0.62, -0.36, 0.025),
        hoseG([[XN - 0.4, 0.7, -0.58], [XN - 0.3, 0.72, -0.62], [XN - 0.22, 0.74, -0.64]], 0.035, 16, 16)];
      add('air_box', 'Air filter box (filter inside)', mesh(merge(ab), M.plastic));
      const hoseEnd = toCar([0.24, YH0 - 0.1 + 0.16, 0.205 + 0.08]);
      add('air_hose', 'Air intake hose (air box to turbo)', mesh(hoseG([[XN - 0.5, 0.8, -0.36], [XN - 0.58, 0.83, -0.25], [FX + 0.1, 0.84, -0.18], [hoseEnd.x + 0.05, hoseEnd.y + 0.04, hoseEnd.z - 0.02], [hoseEnd.x, hoseEnd.y, hoseEnd.z]], 0.03, 50, 18), M.rubber));
    }

    // ── front suspension, each side ──
    for (const s of [-1, 1]) {
      const side = sideName(s), z = v => s * v;
      const ball = [FX + 0.005, 0.2, z(0.69)];
      const strutB = [FX - 0.012, 0.47, z(0.655)], strutT = [FX - 0.04, 0.84, z(0.56)];
      // the knuckle: bearing housing, up to the strut's clamp, down to the ball joint, back to the steering arm
      {
        const bearing = sideZ(latheZ([[0.035, -0.03], [0.062, -0.03], [0.066, -0.022], [0.066, 0.02], [0.035, 0.02]], 32), s).translate(FX, YW, z(0.705));
        const body = merge(hoseG([[ball[0], ball[1] + 0.02, ball[2]], [FX, YW - 0.05, z(0.7)], [FX - 0.005, YW + 0.06, z(0.69)], [strutB[0], strutB[1] - 0.01, z(0.665)]], 0.022, 20, 12),
          hoseG([[FX - 0.03, YW + 0.02, z(0.69)], [FX - 0.1, YW + 0.03, z(0.675)], [FX - 0.14, YW + 0.035, z(0.66)]], 0.015, 16, 10));
        const clamp = along(latheY([[0.03, 0], [0.036, 0], [0.036, 0.085], [0.03, 0.085]], 24), strutB, strutT);
        const ears = rbox(FX - 0.13, FX - 0.08, YW - 0.06, YW + 0.07, z(0.68) - 0.012, z(0.68) + 0.012, 0.006);
        add('knuckle', `Steering knuckle, ${side}`, mesh(merge(bearing, body, clamp, ears), M.caliper));
      }
      // the hub and bearing in it
      add('hub_f', `Front hub and bearing, ${side}`, mesh(sideZ(latheZ([[0.0001, -0.07], [0.034, -0.07], [0.034, -0.012], [0.068, -0.012], [0.068, 0], [0.03, 0], [0.03, 0.012], [0.0001, 0.012]], 32), s), M.forged),
        { pos: [FX, YW, z(HUBF)], anim: null });
      // the strut: damper, spring seat, spring, bump stop and boot, top mount
      const axis = V3(...strutT).sub(V3(...strutB)), L1 = axis.length();
      const at = f => V3(...strutB).addScaledVector(axis, f / L1).toArray();
      const sTop = L1 - 0.06, sSeat = 0.2;
      add('strut', `Front strut, ${side}`, group([merge(along(cylY(0.026, 0.235, 0, 0, 0, 24), strutB, strutT), along(latheY([[0.026, 0], [0.083, 0.004], [0.083, 0.012], [0.03, 0.016]], 32), at(sSeat), strutT)), M.paintBlack],
        [along(cylY(0.0105, sTop - 0.22, 0.225, 0, 0, 12), strutB, strutT), M.chrome]));
      add('spring_f', `Front coil spring, ${side}`, mesh(coilG(at(sSeat + 0.016), at(sTop), 0.07, 0.0125, 4.6), M.paintBlack));
      add('boot_f', `Strut bump stop and dust boot, ${side}`, mesh(along(bellowsG(0.024, 0.03, sTop - 0.25, 6), at(0.245), strutT), M.rubber));
      add('top_mount', `Strut top mount and bearing, ${side}`, group([along(latheY([[0.0001, 0], [0.085, 0], [0.088, 0.01], [0.07, 0.03], [0.04, 0.045], [0.0001, 0.045]], 32), at(sTop), strutT), M.rubber],
        [merge(along(latheY([[0.0001, 0.045], [0.06, 0.045], [0.06, 0.052], [0.0001, 0.052]], 32), at(sTop), strutT),
          ...[0, 1, 2].map(k => { const a = k / 3 * TAU; return rodG([strutT[0] + 0.045 * Math.cos(a), strutT[1] + 0.005, strutT[2] + 0.045 * Math.sin(a)], [strutT[0] + 0.045 * Math.cos(a), strutT[1] + 0.035, strutT[2] + 0.045 * Math.sin(a)], 0.004, 8); }),
          hexY(0.011, 0.012).translate(strutT[0], strutT[1] + 0.012, strutT[2])), M.zinc]));
      // the lower arm: pressed steel, its two bushes, its ball joint
      {
        const o = [[FX + 0.045, z(0.665)], [FX + 0.05, z(0.42)], [FX + 0.035, z(0.315)], [FX - 0.005, z(0.315)], [FX - 0.07, z(0.43)],
          [FX - 0.24, z(0.36)], [FX - 0.305, z(0.385)], [FX - 0.27, z(0.45)], [FX - 0.07, z(0.62)], [FX - 0.03, z(0.715)]];
        const arm = extrudeY(xzShape(o), 0.016, 0.205, { bevelEnabled: true, bevelThickness: 0.006, bevelSize: 0.006, bevelSegments: 2 });
        add('arm', `Front lower control arm, ${side}`, mesh(arm, M.eblack));
        add('arm_bush_f', `Control arm front bush, ${side}`, group([cylX(0.03, 0.06, FX - 0.01, 0.222, z(0.315), 24), M.rubber], [cylX(0.012, 0.075, FX - 0.0175, 0.222, z(0.315), 12), M.zinc]));
        add('arm_bush_r', `Control arm rear bush, ${side}`, group([cylY(0.036, 0.045, 0.2, FX - 0.27, z(0.4), 24), M.rubber],
          [merge(rbox(FX - 0.32, FX - 0.22, 0.245, 0.255, z(0.4) - 0.05, z(0.4) + 0.05, 0.004), hexY(0.009, 0.01, 0.255).translate(FX - 0.3, 0, z(0.37)), hexY(0.009, 0.01, 0.255).translate(FX - 0.24, 0, z(0.43))), M.eblack]));
        add('ball_joint', `Ball joint, ${side}`, group([merge(cylY(0.024, 0.02, 0.195, ball[0], ball[2], 20), new THREE.SphereGeometry(0.017, 16, 12).translate(ball[0], 0.222, ball[2]), cylY(0.008, 0.05, 0.222, ball[0], ball[2], 10, 0.01)), M.forged],
          [merge(...[-1, 1].map(k => hexY(0.007, 0.007, 0.235).translate(ball[0] + k * 0.025, 0, ball[2] - s * 0.01))), M.zinc],
          [latheY([[0.012, 0], [0.024, 0.006], [0.02, 0.016], [0.01, 0.022]], 20).translate(ball[0], 0.228, ball[2]), M.rubber]));
      }
      // the anti-roll bar's link down to the arm, and its bolt
      add('drop_link', `Anti-roll bar link, ${side}`, group([rodG([FX - 0.11, 0.24, z(0.585)], [FX - 0.11, 0.3, z(0.585)], 0.007), M.forged],
        [merge(cylY(0.013, 0.012, 0.236, FX - 0.11, z(0.585), 16), cylY(0.013, 0.012, 0.292, FX - 0.11, z(0.585), 16)), M.rubber]));
      add('link_bolt', `Anti-roll bar link bolt, ${side}`, mesh(boltG(0.06, 0.01, 6, true).rotateX(Math.PI).translate(FX - 0.11, 0.232, z(0.585)), M.zinc));
    }
    // the subframe, the anti-roll bar and its bushes
    {
      const sf = [];
      for (const s of [-1, 1]) sf.push(rbox(FX - 0.44, FX + 0.12, 0.23, 0.285, s * 0.36 - 0.04, s * 0.36 + 0.04, 0.014));
      sf.push(rbox(FX - 0.47, FX - 0.37, 0.24, 0.3, -0.4, 0.4, 0.016), rbox(FX + 0.06, FX + 0.12, 0.235, 0.27, -0.36, 0.36, 0.012));
      const mounts = [];
      for (const [x, s] of [[FX + 0.09, -1], [FX + 0.09, 1], [FX - 0.42, -1], [FX - 0.42, 1]]) mounts.push(cylY(0.03, 0.03, 0.285, x, s * 0.37, 20), hexY(0.012, 0.012, 0.315).translate(x, 0, s * 0.37));
      add('subframe', 'Front subframe', group([merge(sf), M.eblack], [merge(mounts), M.zinc]));
      const bar = hoseG([[FX - 0.11, 0.3, -0.585], [FX - 0.2, 0.31, -0.52], [FX - 0.25, 0.31, -0.38], [FX - 0.26, 0.31, 0], [FX - 0.25, 0.31, 0.38], [FX - 0.2, 0.31, 0.52], [FX - 0.11, 0.3, 0.585]], 0.0105, 60, 12);
      add('arb', 'Front anti-roll bar', mesh(bar, M.eblack));
      for (const s of [-1, 1]) add('arb_bush', `Anti-roll bar bush and clamp, ${sideName(s)}`, group([cylZ(0.022, 0.04, s * 0.3 - 0.02, FX - 0.26, 0.31, 20), M.rubber],
        [merge(latheZ([[0.024, -0.022], [0.028, -0.022], [0.028, 0.022], [0.024, 0.022]], 20).translate(FX - 0.26, 0.31, s * 0.3), rbox(FX - 0.3, FX - 0.22, 0.292, 0.298, s * 0.3 - 0.025, s * 0.3 + 0.025, 0.002)), M.zinc]));
    }
    // ── steering: the rack on the subframe, its boots, the track rods; the column up to the wheel; the hoses ──
    {
      const RXr = FX - 0.24, RY = 0.335;
      const rack = [cylZ(0.025, 0.56, -0.28, RXr, RY, 24), latheZ([[0.0001, -0.03], [0.04, -0.03], [0.042, 0.03], [0.0001, 0.03]], 24).translate(RXr, RY, DS * 0.22),
        rbox(RXr - 0.04, RXr + 0.02, RY - 0.03, RY + 0.06, DS * 0.22 - 0.035, DS * 0.22 + 0.035, 0.01)];
      for (const s of [-1, 1]) rack.push(rbox(RXr - 0.03, RXr + 0.03, RY - 0.06, RY - 0.02, s * 0.12 - 0.02, s * 0.12 + 0.02, 0.006));
      add('rack', 'Steering rack (power assisted)', group([merge(rack), M.aluCast],
        [merge(...[-1, 1].map(s => cylZ(0.006, 0.06, s * 0.12 - 0.03, RXr - 0.035, RY - 0.06, 8))), M.zinc]));
      for (const s of [-1, 1]) {
        const side = sideName(s);
        add('rack_boot', `Steering rack boot, ${side}`, mesh(bellowsG(0.024, 0.016, 0.1, 6).rotateX(s * Math.PI / 2).translate(RXr, RY, s * 0.28), M.rubber));
        const inner = [RXr, RY, s * 0.38], end = [FX - 0.14, 0.36, s * 0.62];
        add('tie_rod', `Track rod (inner), ${side}`, mesh(rodG(inner, end, 0.008), M.forged));
        add('tie_end', `Track rod end, ${side}`, group([merge(rodG([FX - 0.15, 0.357, s * 0.585], end, 0.011), new THREE.SphereGeometry(0.02, 14, 10).translate(...end), cylY(0.008, 0.05, 0.36, end[0], end[2], 10, 0.01)), M.forged],
          [hexY(0.012, 0.01).rotateX(Math.PI / 2).translate(FX - 0.152, 0.357, s * 0.58), M.zinc]));
      }
      // the column: the shaft from the rack's pinion through the bulkhead, its universal joints, up to the wheel
      const pin = [RXr - 0.01, RY + 0.06, DS * 0.22], uj1 = [XBH + 0.02, 0.56, DS * 0.3], uj2 = [XBH - 0.08, 0.66, DS * 0.34], wc = [0.47, 0.93, DS * 0.36];
      const ujG = p => merge(new THREE.SphereGeometry(0.018, 12, 10).translate(...p), cylX(0.008, 0.05, p[0] - 0.025, p[1], p[2], 8));
      add('column', 'Steering column and shafts', group([merge(rodG(pin, uj1, 0.009), rodG(uj1, uj2, 0.01), rodG(uj2, wc, 0.012), along(cylY(0.024, 0.28, 0.08, 0, 0, 20), uj2, wc)), M.forged],
        [merge(ujG(uj1), ujG(uj2)), M.zinc]));
      add('ps_hose', 'Power steering return hose', mesh(hoseG([[RXr + 0.02, RY + 0.06, DS * 0.25], [RXr + 0.08, 0.5, DS * 0.15], [FX - 0.02, 0.74, -0.2], [FX + 0.02, 0.805, -0.26]], 0.008, 40, 10), M.rubber));
      add('ps_hose', 'Power steering pressure hose', mesh(hoseG([[RXr + 0.02, RY + 0.06, DS * 0.19], [RXr + 0.1, 0.45, DS * 0.08], [FX + 0.32, 0.5, 0.3]], 0.008, 40, 10), M.rubber));
      add('ps_tank', 'Power steering fluid reservoir', group([merge(cylY(0.045, 0.1, 0.755, FX + 0.02, -0.26, 28), latheY([[0.0001, 0], [0.025, 0], [0.025, 0.018], [0.0001, 0.018]], 20).translate(FX + 0.02, 0.855, -0.26)), M.tankWhite],
        [latheY([[0.0001, 0], [0.027, 0], [0.027, 0.014], [0.0001, 0.014]], 20).translate(FX + 0.02, 0.857, -0.26), M.plastic]));
    }
    // ── driveshafts, each side: flange joint at the gearbox, the shaft, the outer joint in the hub ──
    for (const s of [-1, 1]) {
      const side = sideName(s), z0 = s > 0 ? GZ0 + 0.018 : GZ0 - 0.29, z1 = s * 0.7;
      const zIn = z0 + s * 0.045, zOut = z1 - s * 0.08;
      const shaft = [cylZ(0.0125, Math.abs(zOut - zIn), Math.min(zIn, zOut), FX, YW, 14),
        sideZ(latheZ([[0.0001, 0], [0.05, 0], [0.05, 0.022], [0.035, 0.035], [0.02, 0.045], [0.0001, 0.045]], 28), s).translate(FX, YW, z0),
        sideZ(latheZ([[0.0001, -0.06], [0.015, -0.06], [0.032, -0.05], [0.046, -0.03], [0.046, 0.0], [0.028, 0.02], [0.0001, 0.06]], 28), s).translate(FX, YW, z1 - s * 0.01)];
      const bolts = [];
      for (let k = 0; k < 6; k++) { const a = k / 6 * TAU; bolts.push(cylZ(0.0055, 0.03, z0 + (s > 0 ? 0.0 : -0.03), FX + 0.04 * Math.cos(a), YW + 0.04 * Math.sin(a), 6)); }
      add('driveshaft', `Driveshaft, ${side} (axle assembly)`, group([merge(shaft), M.forged], [merge(bolts), M.zinc]));
      add('cv_boot', `CV joint boot, ${side}, inner`, mesh(sideZ(bellowsG(0.04, 0.016, 0.1, 5).rotateX(Math.PI / 2), s).translate(FX, YW, zIn - s * 0.0), M.rubber));
      add('cv_boot', `CV joint boot, ${side}, outer`, mesh(sideZ(bellowsG(0.016, 0.044, 0.1, 5).rotateX(Math.PI / 2), s).translate(FX, YW, zOut - s * 0.1), M.rubber));
      add('cv_circlip', `Driveshaft snap ring, ${side}`, mesh(torusZ(0.014, 0.0016, FX, YW, zIn + s * 0.006, 6, 20), M.steel));
      add('axle_nut', `Driveshaft nut, ${side}`, mesh(hexY(0.017, 0.016).rotateX(s * Math.PI / 2).translate(FX, YW, s * (HUBF + 0.012)), M.zinc));
    }

    // ── rear suspension: the twist beam, its bushes, springs and shock absorbers, stub axles and hubs ──
    {
      const beam = [];
      const v = new THREE.Shape([V2(-0.045, 0.045), V2(0, -0.035), V2(0.045, 0.045), V2(0.034, 0.05), V2(0, -0.012), V2(-0.034, 0.05)]);
      const cross = new THREE.ExtrudeGeometry(v, { depth: 1.12, bevelEnabled: false }); cross.translate(RX + 0.24, 0.3, -0.56);
      beam.push(cross);
      for (const s of [-1, 1]) {
        beam.push(hoseG([[RX + 0.46, 0.3, s * 0.6], [RX + 0.25, 0.3, s * 0.6], [RX + 0.05, 0.31, s * 0.62], [RX - 0.02, YW, s * 0.63]], 0.032, 24, 14));
        beam.push(latheY([[0.0001, 0], [0.065, 0], [0.065, 0.01], [0.0001, 0.01]], 28).translate(RX + 0.05, 0.335, s * 0.55));
        beam.push(rbox(RX - 0.08, RX - 0.02, 0.24, 0.29, s * 0.6 - 0.025, s * 0.6 + 0.025, 0.006));
        beam.push(rbox(RX - 0.06, RX + 0.07, YW - 0.07, YW + 0.07, s * 0.635 - 0.008, s * 0.635 + 0.008, 0.008));
      }
      add('beam', 'Rear axle (twist beam)', mesh(merge(beam), M.eblack));
      for (const s of [-1, 1]) {
        const side = sideName(s);
        add('beam_bush', `Rear axle mounting bush, ${side}`, group([cylZ(0.04, 0.06, s * 0.6 - 0.03, RX + 0.47, 0.3, 24), M.rubber],
          [merge(rbox(RX + 0.42, RX + 0.53, 0.33, 0.37, s * 0.6 - 0.05, s * 0.6 + 0.05, 0.006), rbox(RX + 0.44, RX + 0.51, 0.26, 0.35, s * 0.6 - 0.045, s * 0.6 - 0.035, 0.003),
            rbox(RX + 0.44, RX + 0.51, 0.26, 0.35, s * 0.6 + 0.035, s * 0.6 + 0.045, 0.003), cylZ(0.008, 0.12, s * 0.6 - 0.06, RX + 0.47, 0.3, 8)), M.eblack]));
        add('spring_r', `Rear coil spring, ${side}`, mesh(coilG([RX + 0.05, 0.345, s * 0.55], [RX + 0.05, 0.58, s * 0.55], 0.062, 0.0115, 6), M.paintBlack));
        const sb = [RX - 0.05, 0.265, s * 0.6], st = [RX - 0.11, 0.66, s * 0.57];
        add('shock_r', `Rear shock absorber, ${side}`, group([merge(along(cylY(0.023, 0.26, 0, 0, 0, 20), sb, st), along(cylY(0.012, 0.03, -0.02, 0, 0, 12), sb, st)), M.paintBlack],
          [along(cylY(0.009, 0.16, 0.25, 0, 0, 10), sb, st), M.chrome], [along(bellowsG(0.018, 0.018, 0.12, 6).translate(0, 0.26, 0), sb, st), M.rubber]));
        add('stub_axle', `Rear stub axle, ${side}`, mesh(sideZ(latheZ([[0.0001, -0.03], [0.07, -0.03], [0.07, -0.02], [0.02, -0.018], [0.018, 0.05], [0.0001, 0.05]], 28), s).translate(RX, YW, s * 0.64), M.forged));
        add('hub_r', `Rear hub and bearing, ${side}`, mesh(sideZ(latheZ([[0.0001, -0.055], [0.036, -0.055], [0.036, -0.01], [0.062, -0.01], [0.062, 0], [0.026, 0], [0.026, 0.01], [0.0001, 0.01]], 32), s), M.forged), { pos: [RX, YW, s * HUBR] });
      }
    }

    // ── brakes: discs, calipers, carriers, pads, clips, bolts, hoses; pipes, servo, ABS, handbrake cables ──
    for (const [ax, s, front] of [[FX, -1, true], [FX, 1, true], [RX, -1, false], [RX, 1, false]]) {
      const side = `${front ? 'front' : 'rear'} ${sideName(s)}`, hubZ = front ? HUBF : HUBR;
      const R = front ? 0.14 : 0.116, thick = front ? 0.022 : 0.009, dIn = 0.006;     // the disc: radius, thickness; its hat
      const zf = d => s * (hubZ - d);                                                  // a depth inboard of the hub's face
      // the disc, about its own axle (so it turns with the wheel)
      {
        const g = [], d0 = 0.024, d1 = d0 + thick;
        if (front) {
          g.push(sideZ(latheZ([[0.075, -d1], [R, -d1], [R, -d1 + 0.0075], [0.075, -d1 + 0.0075]], 64), s), sideZ(latheZ([[0.075, -d0 - 0.0075], [R, -d0 - 0.0075], [R, -d0], [0.075, -d0]], 64), s));
          for (let k = 0; k < 36; k++) { const a = k / 36 * TAU, vb = box(R - 0.085, 0.004, thick - 0.012); vb.translate((R + 0.085) / 2, 0, 0); vb.rotateZ(a); vb.translate(0, 0, -s * (d0 + thick / 2)); g.push(vb); }
        } else g.push(sideZ(latheZ([[0.07, -d1], [R, -d1], [R, -d0], [0.07, -d0]], 64), s));
        const hat = sideZ(latheZ([[0.0001, -dIn - 0.002], [0.072, -dIn - 0.002], [0.072, -d0 - 0.002], [0.08, -d0 - 0.002], [0.08, 0], [0.0001, 0]], 48), s);
        const disc = add(front ? 'disc_f' : 'disc_r', `${front ? 'Front' : 'Rear'} brake disc, ${sideName(s)}`, group([merge(g), M.disc], [hat, M.caliper]), { pos: [ax, YW, s * hubZ] });
        disc.anim = wheelSpin(disc, s);
      }
      // caliper, carrier and pads at the disc's back edge, a little above the axle
      const F = wheelFrame(ax, YW, front ? 2.85 : 2.9), P = (r, t, d) => V3(r, t, zf(d)).applyMatrix4(F);
      const inFrame = g => g.applyMatrix4(F);
      const fBox = (r0, r1, t0, t1, d0, d1, rr) => { const za = zf(d0), zb = zf(d1); return inFrame(rbox(r0, r1, t0, t1, Math.min(za, zb), Math.max(za, zb), rr)); };
      const fCylZ = (rad, r, t, d0, d1, seg = 20) => { const za = zf(d0), zb = zf(d1); return inFrame(cylZ(rad, Math.abs(zb - za), Math.min(za, zb), r, t, seg)); };
      const d0 = 0.024, d1 = d0 + thick, pr = R - 0.03;
      if (front) {
        const cal = add('caliper', `Brake caliper, ${side}`, group([merge(fBox(pr - 0.035, R + 0.022, -0.05, 0.05, d1 + 0.012, d1 + 0.045, 0.012), fBox(R - 0.01, R + 0.024, -0.042, 0.042, d0 - 0.012, d1 + 0.04, 0.008),
          fBox(pr - 0.025, R + 0.012, -0.045, 0.045, d0 - 0.02, d0 - 0.01, 0.008), fCylZ(0.027, pr - 0.005, 0, d1 + 0.04, d1 + 0.055, 28)), M.caliper],
          [merge(fCylZ(0.008, pr - 0.04, -0.055, d1 + 0.02, d1 + 0.06, 10), fCylZ(0.008, pr - 0.04, 0.055, d1 + 0.02, d1 + 0.06, 10)), M.rubber]));
        for (const t of [-0.055, 0.055]) add('guide_bolt', `Caliper guide bolt, ${side}`, mesh(fCylZ(0.0065, pr - 0.04, t, d1 + 0.055, d1 + 0.07, 6), M.zinc), { parent: cal });
        add('pad_clip', `Brake pad retaining clip, ${side}`, mesh(inFrame(new THREE.TorusGeometry(0.03, 0.0016, 6, 20, Math.PI).rotateZ(-Math.PI / 2).translate(pr - 0.005, 0, zf(d0 - 0.018))), M.steel), { parent: cal });
        for (const [dd, nm] of [[d0 - 0.002, 'outer'], [d1 + 0.002, 'inner']]) {
          const back = fBox(pr - 0.03, R - 0.002, -0.048, 0.048, dd - (nm === 'outer' ? 0.0045 : 0), dd + (nm === 'outer' ? 0 : 0.0045), 0.004);
          const lining = fBox(pr - 0.027, R - 0.005, -0.045, 0.045, nm === 'outer' ? dd : dd - 0.0105, nm === 'outer' ? dd + 0.0105 : dd, 0.003);
          add('pad', `Brake pad, ${side}, ${nm}`, group([back, M.steel], [lining, M.fibre]));
        }
        add('carrier', `Caliper carrier, ${side}`, mesh(merge(fBox(pr - 0.05, pr - 0.025, -0.075, 0.075, d1 + 0.004, d1 + 0.02, 0.005), fBox(pr - 0.05, R + 0.004, -0.075, -0.055, d0 - 0.008, d1 + 0.02, 0.005),
          fBox(pr - 0.05, R + 0.004, 0.055, 0.075, d0 - 0.008, d1 + 0.02, 0.005)), M.caliper));
        for (const t of [-0.065, 0.065]) add('carrier_bolt', `Caliper carrier bolt, ${side}`, mesh(inFrame(hexY(0.0095, 0.009).rotateX(s * Math.PI / 2).translate(pr - 0.06, t, zf(d1 + 0.02))), M.zinc));
        add('shield_f', `Brake disc splash shield, ${side}`, mesh(sideZ(latheZ([[0.07, -0.06], [R + 0.01, -0.06], [R + 0.015, -0.05], [0.07, -0.058]], 48), s).translate(ax, YW, s * hubZ), M.zinc));
        const hb = P(pr - 0.01, -0.03, d1 + 0.05);
        add('brake_hose', `Brake hose, ${side}`, mesh(hoseG([hb.toArray(), [ax - 0.06, YW + 0.2, s * 0.66], [ax - 0.04, 0.62, s * 0.62]], 0.0055, 30, 10), M.rubber));
      } else {
        add('caliper_r', `Rear brake caliper, ${side}`, group([merge(fBox(pr - 0.03, R + 0.02, -0.04, 0.04, d1 + 0.008, d1 + 0.04, 0.01), fBox(R - 0.01, R + 0.022, -0.035, 0.035, d0 - 0.01, d1 + 0.035, 0.007),
          fBox(pr - 0.02, R + 0.01, -0.036, 0.036, d0 - 0.016, d0 - 0.008, 0.006), fCylZ(0.022, pr, 0, d1 + 0.035, d1 + 0.06, 24)), M.caliper],
          [merge(fBox(pr - 0.01, pr + 0.01, -0.06, 0.0, d1 + 0.058, d1 + 0.064, 0.002)), M.steel]));
        const hb = P(pr - 0.05, -0.06, d1 + 0.06);
        add('brake_hose', `Brake hose, ${side}`, mesh(hoseG([P(pr, 0.02, d1 + 0.05).toArray(), [ax + 0.02, YW + 0.12, s * 0.6], [ax + 0.1, 0.36, s * 0.5]], 0.005, 24, 10), M.rubber));
        add('hb_cable', `Handbrake cable, ${sideName(s)}`, mesh(hoseG([[-0.15, 0.25, 0.0], [-0.55, 0.22, s * 0.1], [-0.95, 0.24, s * 0.4], [hb.x + 0.05, hb.y - 0.01, hb.z - s * 0.02], hb.toArray()], 0.004, 60, 8), M.rubber));
      }
    }
    // the servo and master cylinder on the bulkhead on the driver's side; the ABS unit; the pipes
    {
      const sv = [latheX([[0.0001, 0], [0.11, 0], [0.12, 0.02], [0.12, 0.1], [0.11, 0.12], [0.0001, 0.12]], 40).translate(XBH, 0.8, DS * 0.36)];
      const mc = merge(cylX(0.022, 0.15, XBH + 0.12, 0.8, DS * 0.36, 20), rbox(XBH + 0.15, XBH + 0.24, 0.825, 0.88, DS * 0.36 - 0.05, DS * 0.36 + 0.05, 0.012));
      add('servo', 'Brake servo and master cylinder', group([merge(sv), M.paintBlack], [mc, M.aluCast], [latheY([[0.0001, 0], [0.022, 0], [0.022, 0.012], [0.0001, 0.012]], 20).translate(XBH + 0.2, 0.88, DS * 0.36), M.plastic]));
      add('abs', 'ABS pump and control unit', group([rbox(FX - 0.2, FX - 0.1, 0.5, 0.6, -0.5, -0.38, 0.01), M.aluCast], [merge(rbox(FX - 0.2, FX - 0.1, 0.6, 0.65, -0.5, -0.38, 0.012), cylZ(0.03, 0.06, -0.38, FX - 0.15, 0.53, 20)), M.plastic]));
      const absP = [FX - 0.15, 0.55, -0.38];
      for (const s of [-1, 1]) add('brake_line', `Brake pipe to the front ${sideName(s)}`, mesh(hoseG([absP, [FX - 0.12, 0.6, s * 0.1], [FX - 0.07, 0.64, s * 0.55], [FX - 0.04, 0.62, s * 0.62]], 0.0025, 40, 6), M.zinc));
      add('brake_line', 'Brake pipes to the rear', mesh(merge(...[-0.012, 0.012].map(dz => hoseG([[absP[0], 0.5, absP[2] + dz], [XBH + 0.08, 0.23, -0.2 + dz], [0.0, 0.22, -0.2 + dz], [-0.9, 0.24, -0.25 + dz], [RX + 0.1, 0.36, -0.5 + dz * 30]], 0.0025, 80, 6))), M.zinc));
      add('brake_line', 'Servo to master cylinder pipes', mesh(hoseG([[XBH + 0.2, 0.83, DS * 0.36], [XBH + 0.18, 0.62, 0.0], [absP[0], 0.6, absP[2]]], 0.0028, 40, 6), M.zinc));
    }

    // ── wheels and tyres, each corner: steel wheel, its trim, its bolts, the tyre ──
    for (const [ax, s, front] of [[FX, -1, true], [FX, 1, true], [RX, -1, false], [RX, 1, false]]) {
      const side = `${front ? 'front' : 'rear'} ${sideName(s)}`, hubZ = front ? HUBF : HUBR, off = C.wheel_offset;
      // the wheel built about its own centre (the hub's face at +off outward), turned for its side
      const rim = latheZ([[0.2, -0.078 - off], [0.198, -0.072 - off], [0.19, -0.068 - off], [0.19, -0.045 - off], [0.17, -0.034 - off], [0.17, 0.018 - off], [0.19, 0.03 - off],
        [0.19, 0.068 - off], [0.198, 0.072 - off], [0.2, 0.078 - off]], 64);
      const dish = latheZ([[0.032, 0], [0.09, 0], [0.11, -0.01], [0.15, -0.032], [0.172, -0.035]], 48);
      const vents = [];
      for (let k = 0; k < 8; k++) { const a = k / 8 * TAU; vents.push(new THREE.CircleGeometry(0.016, 16).scale(1.6, 1, 1).rotateZ(a).translate(0.13 * Math.cos(a), 0.13 * Math.sin(a), -0.015)); }
      const W = add('wheel', `Wheel, ${side}`, group([sideZ(merge(rim, dish), s), M.wheelSteel], [sideZ(merge(vents), s), M.blackPaint]), { pos: [ax, YW, s * hubZ] });
      W.anim = wheelSpin(W, s);
      // the tyre: its section, the tread's grooves
      const tp = [[0.19, -0.08], [0.24, -0.097], [0.29, -0.098], [0.309, -0.088], [RT, -0.07]];
      for (const g of [-0.052, -0.022, 0.022, 0.052]) tp.push([RT, g - 0.006], [RT - 0.008, g - 0.004], [RT - 0.008, g + 0.004], [RT, g + 0.006]);
      tp.push([RT, 0.07], [0.309, 0.088], [0.29, 0.098], [0.24, 0.097], [0.19, 0.08]);
      const tread = [];
      for (let k = 0; k < 72; k++) { const a = k / 72 * TAU; const b = box(0.012, 0.004, 0.024); b.translate(RT - 0.0015, 0, 0); b.rotateZ(a); b.translate(0, 0, (k % 2 ? 0.037 : -0.037)); tread.push(b); }
      const T = add('tyre', `Tyre 195/65 R15, ${side}`, group([sideZ(latheZ(tp.map(([r, a]) => [r, a - off]), 96), s), M.tyre], [sideZ(merge(tread).translate(0, 0, -off), s), M.rubber]), { parent: W, pos: [ax, YW, s * hubZ] });
      T.anim = wheelSpin(T, s);
      // the trim: a silver dish with ten spokes over the steel wheel
      const trimG = [latheZ([[0.188, -0.014], [0.196, -0.012], [0.193, 0.0], [0.17, 0.012], [0.06, 0.026], [0.045, 0.03], [0.0001, 0.03]], 64)];
      for (let k = 0; k < 10; k++) { const a = (k + 0.5) / 10 * TAU, b = box(0.1, 0.022, 0.012); b.translate(0.12, 0, 0.024 - 0.0001); b.rotateZ(a); trimG.push(b); }
      const holes = [];
      for (let k = 0; k < 10; k++) { const a = k / 10 * TAU; holes.push(new THREE.CircleGeometry(0.03, 3).scale(1.6, 0.9, 1).rotateZ(a).translate(0.12 * Math.cos(a), 0.12 * Math.sin(a), 0.0255)); }
      const Tr = add('trim', `Wheel trim, ${side}`, group([sideZ(merge(trimG), s), M.trimSilver], [sideZ(merge(holes), s), M.blackPaint]), { parent: W, pos: [ax, YW, s * (hubZ + 0.03)] });
      Tr.anim = wheelSpin(Tr, s);
      for (let k = 0; k < 5; k++) {
        const a = k / 5 * TAU + 0.3, b = sideZ(boltG(0.03, 0.014, 6, true).rotateX(Math.PI / 2).translate(0.05 * Math.cos(a), 0.05 * Math.sin(a), 0.0165), s);
        const bp = add('wheel_bolt', `Wheel bolt, ${side}`, mesh(b, M.zinc), { parent: W, pos: [ax, YW, s * hubZ] });
        bp.anim = wheelSpin(bp, s);
      }
    }

    // ── interior ──
    const FLOOR = 0.27;
    {
      // the dashboard: its section drawn across the car, rounded at the ends; the cluster's hood, the centre stack's vents
      const prof = [[XBH + 0.03, 0.93], [0.84, 0.965], [0.78, 0.99], [0.7, 0.99], [0.62, 0.975], [0.58, 0.96], [0.555, 0.935], [0.555, 0.86], [0.59, 0.74], [0.66, 0.66], [0.8, 0.62], [XBH, 0.62]];
      const dshape = new THREE.Shape(prof.map(([x, y]) => V2(x, y)));
      const dashG = new THREE.ExtrudeGeometry(dshape, { depth: 1.36, bevelEnabled: true, bevelThickness: 0.02, bevelSize: 0.015, bevelSegments: 4, curveSegments: 8 }).translate(0, 0, -0.68);
      const hoodS = new THREE.Shape([V2(0.6, 1.062), V2(0.61, 1.085), V2(0.64, 1.096), V2(0.7, 1.086), V2(0.72, 1.07), V2(0.72, 1.06), V2(0.7, 1.075), V2(0.64, 1.084), V2(0.614, 1.074), V2(0.608, 1.062)]);
      const hood = new THREE.ExtrudeGeometry(hoodS, { depth: 0.3, bevelEnabled: true, bevelThickness: 0.015, bevelSize: 0.004, bevelSegments: 3 }).translate(0, 0, DS * 0.36 - 0.15);
      const vents = [];
      for (const z of [-0.1, 0.1]) { vents.push(rbox(0.545, 0.56, 0.885, 0.945, z - 0.07, z + 0.07, 0.008)); }
      for (const s of [-1, 1]) vents.push(rbox(0.565, 0.58, 0.9, 0.96, s * 0.62 - 0.05, s * 0.62 + 0.05, 0.01));
      const slats = [];
      for (const z of [-0.1, 0.1, -0.62, 0.62]) for (let k = 0; k < 4; k++) slats.push(box(0.004, 0.004, 0.12, Math.abs(z) > 0.5 ? 0.562 : 0.543, 0.895 + k * 0.014, z));
      add('dash', 'Dashboard', group([merge(dashG, hood), M.dash], [merge(vents), M.blackPaint], [merge(slats), M.trimGrey]));
      // the cluster: the speedometer and rev counter, fuel and temperature, blue-lit numbers and red needles
      const tex = clusterTexture();
      const n = V3(-0.95, 0.3, 0).normalize(), ux = V3(0, 0, 1), uy = n.clone().cross(ux).normalize();
      const faceM = new THREE.Matrix4().makeBasis(ux, uy, n);
      const face = new THREE.PlaneGeometry(0.27, 0.09).applyMatrix4(faceM).translate(0.645, 1.02, DS * 0.36);
      const cm = new THREE.MeshStandardMaterial({ map: tex, emissiveMap: tex, emissive: 0x9ab8ff, emissiveIntensity: 0.55, roughness: 0.35, metalness: 0.0 });
      M.gauges = cm;
      const glassF = new THREE.PlaneGeometry(0.28, 0.095).applyMatrix4(faceM).translate(0.638, 1.022, DS * 0.36);
      add('cluster', 'Instrument cluster', group([face, cm], [glassF, M.lens], [rbox(0.668, 0.72, 0.95, 1.062, DS * 0.36 - 0.145, DS * 0.36 + 0.145, 0.01), M.blackPaint]));
      // the steering wheel: four spokes, its rim in leather; the airbag in the middle
      const wc = V3(0.47, 0.93, DS * 0.36), aDir = V3(0.86, -0.5, 0).normalize(), q = new THREE.Quaternion().setFromUnitVectors(UP, aDir);
      const sw = [new THREE.TorusGeometry(0.183, 0.0155, 12, 72).rotateX(Math.PI / 2)];
      for (const a of [0, Math.PI, -Math.PI * 0.62, -Math.PI * 0.38]) { const b = box(0.15, 0.012, 0.03); b.translate(0.085, 0.01, 0); b.rotateY(a + Math.PI / 2); sw.push(b); }
      sw.push(latheY([[0.0001, 0.035], [0.05, 0.035], [0.055, 0.0], [0.0001, 0.0]], 24));
      const swG = merge(sw).applyQuaternion(q).translate(wc.x, wc.y, wc.z);
      add('wheel_s', 'Steering wheel', mesh(swG, M.leather));
      const bag = rbox(-0.065, 0.065, -0.042, -0.002, -0.05, 0.05, 0.02).applyQuaternion(q).translate(wc.x, wc.y, wc.z);
      add('airbag', 'Driver’s airbag', mesh(bag, M.dash));
      // the shroud round the column, its stalks; the ignition lock on it
      const shroud = rbox(-0.05, 0.05, 0.07, 0.25, -0.045, 0.045, 0.02).applyQuaternion(q).translate(wc.x, wc.y, wc.z);
      const stalks = [-1, 1].map(k => rodG(wc.clone().addScaledVector(aDir, 0.11).toArray(), wc.clone().addScaledVector(aDir, 0.09).add(V3(-0.03, 0.01, k * 0.16)).toArray(), 0.0065));
      add('shroud', 'Steering column shroud and stalks', group([shroud, M.dash], [merge(stalks), M.blackPaint]));
      const ign = wc.clone().addScaledVector(aDir, 0.17).add(V3(0, 0, DS * 0.06));
      add('lock_cyl', 'Ignition lock cylinder', group([cylX(0.012, 0.03, ign.x - 0.03, ign.y, ign.z, 18), M.chrome], [box(0.004, 0.02, 0.004, ign.x - 0.032, ign.y, ign.z), M.blackPaint]));
      add('ign_switch', 'Ignition switch', mesh(cylX(0.018, 0.04, ign.x, ign.y, ign.z, 18), M.plastic));
      add('col_lock', 'Steering column lock', mesh(rbox(ign.x + 0.04, ign.x + 0.1, ign.y - 0.03, ign.y + 0.02, ign.z - DS * 0.04 - 0.03, ign.z - DS * 0.04 + 0.03, 0.008), M.aluCast));
      // the radio and the heater's three knobs in the centre stack; the glovebox
      add('radio', 'Radio', group([rbox(0.545, 0.556, 0.79, 0.86, -0.09, 0.09, 0.004), M.blackPaint], [merge(rbox(0.54, 0.546, 0.8, 0.815, -0.06, 0.06, 0.002), cylX(0.009, 0.01, 0.535, 0.84, -0.07, 16), cylX(0.009, 0.01, 0.535, 0.84, 0.07, 16)), M.trimGrey]));
      add('hvac_ctl', 'Heater controls', group([rbox(0.555, 0.565, 0.7, 0.77, -0.11, 0.11, 0.006), M.blackPaint],
        [merge(...[-0.07, 0, 0.07].map(z => latheX([[0.0001, -0.022], [0.016, -0.022], [0.018, 0], [0.0001, 0]], 20).translate(0.555, 0.735, z))), M.trimGrey]));
      add('glovebox', 'Glovebox lid', group([rbox(0.575, 0.6, 0.72, 0.87, -DS * 0.62, -DS * 0.2, 0.012).rotateZ(0), M.dash], [rbox(0.568, 0.578, 0.84, 0.855, -DS * 0.45, -DS * 0.37, 0.004), M.trimGrey]));
      // the headlamp switch on the dash outboard of the wheel
      add('light_switch', 'Headlamp switch', group([rbox(0.575, 0.585, 0.82, 0.9, DS * 0.6 - 0.04, DS * 0.6 + 0.04, 0.006), M.blackPaint], [latheX([[0.0001, -0.02], [0.022, -0.02], [0.024, 0], [0.0001, 0]], 24).translate(0.575, 0.86, DS * 0.6), M.trimGrey]));
      // the heater box behind the dash, its blower on the passenger's side
      add('heater', 'Heater box and blower', group([merge(rbox(0.66, 0.9, 0.64, 0.95, -0.25, 0.2, 0.03), latheX([[0.0001, 0], [0.09, 0], [0.09, 0.13], [0.0001, 0.13]], 32).translate(0.7, 0.76, -DS * 0.38)), M.plastic],
        [merge(hoseG([[0.66, 0.9, 0], [0.6, 0.93, 0]], 0.03, 6, 12), hoseG([[0.68, 0.92, -0.2], [0.62, 0.94, -0.55]], 0.03, 10, 12), hoseG([[0.68, 0.92, 0.18], [0.62, 0.94, 0.55]], 0.03, 10, 12)), M.trimGrey]));
      // the centre console; the gear lever with its gaiter; the handbrake
      add('console', 'Centre console', mesh(merge(rbox(-0.42, 0.5, FLOOR + 0.14, FLOOR + 0.24, -0.11, 0.11, 0.025), rbox(0.42, 0.56, FLOOR + 0.14, 0.7, -0.1, 0.1, 0.03)), M.dash));
      const gb = [0.17, FLOOR + 0.24, 0], gk = [0.1, 0.72, 0];
      add('gear_lever', 'Gear lever, knob and gaiter', group([rodG(gb, gk, 0.007), M.chrome], [along(latheY([[0.0001, 0], [0.026, 0], [0.03, 0.03], [0.026, 0.055], [0.0001, 0.064]], 24), [gk[0] + 0.004, gk[1] - 0.01, 0], [gk[0] - 0.01, gk[1] + 0.05, 0]), M.leather],
        [along(bellowsG(0.075, 0.012, 0.16, 6), gb, gk), M.leather]));
      add('handbrake', 'Handbrake lever', group([merge(rodG([-0.08, FLOOR + 0.2, 0], [-0.36, FLOOR + 0.32, 0], 0.012), rbox(-0.11, -0.05, FLOOR + 0.14, FLOOR + 0.22, -0.02, 0.02, 0.005)), M.forged],
        [merge(rodG([-0.24, FLOOR + 0.27, 0], [-0.38, FLOOR + 0.33, 0], 0.017), cylX(0.007, 0.02, -0.4, FLOOR + 0.335, 0, 12)), M.leather]));
      // the pedals on the driver's side: clutch, brake, accelerator
      const pv = 0.81;
      for (const [pz, nm, yb] of [[0.24, 'Clutch pedal', 0.4], [0.37, 'Brake pedal', 0.39], [0.49, 'Accelerator pedal', 0.36]]) {
        const z = DS * pz, pad = nm.startsWith('Acc') ? rbox(0.67, 0.69, yb - 0.06, yb + 0.05, z - 0.03, z + 0.03, 0.006) : rbox(0.66, 0.68, yb - 0.035, yb + 0.03, z - 0.035, z + 0.035, 0.008);
        add('pedal', nm, group([merge(hoseG([[pv, 0.74, z], [0.76, 0.6, z], [0.69, yb + 0.01, z]], 0.008, 16, 8), cylZ(0.012, 0.03, z - 0.015, pv, 0.74, 12)), M.eblack], [pad, M.rubber]));
      }
      add('clutch_switch', 'Clutch starter safety switch', mesh(merge(cylX(0.009, 0.04, pv - 0.06, 0.7, DS * 0.24 - 0.02, 12), rbox(pv - 0.02, pv + 0.01, 0.69, 0.71, DS * 0.24 - 0.035, DS * 0.24 - 0.005, 0.003)), M.connector));
      // the seats: the fronts on their runners, the rear bench and its split backrest; belts and buckles
      for (const s of [-1, 1]) {
        const zc = s * 0.37, side = s === DS ? 'driver’s' : 'passenger’s';
        const cushion = merge(rbox(-0.32, 0.22, 0.42, 0.53, zc - 0.25, zc + 0.25, 0.04), rbox(-0.3, 0.22, 0.46, 0.575, zc - 0.25, zc - 0.17, 0.035), rbox(-0.3, 0.22, 0.46, 0.575, zc + 0.17, zc + 0.25, 0.035));
        const back = merge(rbox(-0.06, 0.04, 0, 0.62, -0.25, 0.25, 0.04), rbox(-0.05, 0.08, 0.05, 0.56, -0.26, -0.17, 0.035), rbox(-0.05, 0.08, 0.05, 0.56, 0.17, 0.26, 0.035)).rotateZ(0.36).translate(-0.3, 0.5, zc);
        const knob = cylZ(0.02, 0.02, s * 0.62 - 0.01, -0.29, 0.47, 16);
        const ins = merge(rbox(-0.28, 0.18, 0.525, 0.535, zc - 0.16, zc + 0.16, 0.004), rbox(0.035, 0.045, 0.06, 0.56, -0.16, 0.16, 0.004).rotateZ(0.36).translate(-0.3, 0.5, zc));
        const seat = add('seat_f', `Front seat, ${side}`, group([merge(cushion, back), M.cloth], [ins, M.clothInsert], [knob, M.blackPaint], [rbox(-0.3, 0.2, 0.36, 0.42, zc - 0.22, zc + 0.22, 0.01), M.eblack]));
        const hrTop = V3(0, 0.62, 0).applyAxisAngle(V3(0, 0, 1), 0.36).add(V3(-0.3, 0.5, zc));
        add('headrest', `Head restraint, ${side}`, group([rbox(hrTop.x - 0.06, hrTop.x + 0.05, hrTop.y + 0.05, hrTop.y + 0.22, zc - 0.13, zc + 0.13, 0.04), M.cloth],
          [merge(rodG([hrTop.x, hrTop.y - 0.02, zc - 0.07], [hrTop.x - 0.01, hrTop.y + 0.08, zc - 0.07], 0.006), rodG([hrTop.x, hrTop.y - 0.02, zc + 0.07], [hrTop.x - 0.01, hrTop.y + 0.08, zc + 0.07], 0.006)), M.chrome]), { parent: seat });
        add('seat_rail', `Seat runners, ${side}`, mesh(merge(rbox(-0.38, 0.32, FLOOR + 0.0, FLOOR + 0.04, zc - 0.21, zc - 0.17, 0.006), rbox(-0.38, 0.32, FLOOR + 0.0, FLOOR + 0.04, zc + 0.17, zc + 0.21, 0.006),
          rbox(-0.32, 0.25, FLOOR + 0.04, 0.37, zc - 0.2, zc - 0.18, 0.004), rbox(-0.32, 0.25, FLOOR + 0.04, 0.37, zc + 0.18, zc + 0.2, 0.004)), M.steel), { parent: seat });
        // the front belt down the centre pillar, its buckle on the seat's inner side
        const bz = s * 0.685;
        add('belt', `Seat belt, front ${sideName(s)}`, group([merge(rbox(-0.37, -0.32, FLOOR + 0.05, 1.18, bz - 0.006, bz + 0.0, 0.002), rbox(-0.4, -0.32, 0.3, 0.4, bz - 0.04, bz + 0.0, 0.01)), M.blackPaint],
          [merge(rbox(-0.37, -0.33, 1.15, 1.2, bz - 0.012, bz - 0.006, 0.004), rbox(-0.37, -0.33, 0.62, 0.68, bz - 0.014, bz - 0.006, 0.003)), M.chrome]));
        add('buckle', `Seat belt buckle, front ${sideName(s)}`, group([merge(rodG([-0.27, FLOOR + 0.05, s * 0.12], [-0.25, 0.5, s * 0.12], 0.008), rbox(-0.27, -0.21, 0.49, 0.56, s * 0.12 - 0.014, s * 0.12 + 0.014, 0.008)), M.blackPaint],
          [rbox(-0.235, -0.215, 0.53, 0.55, s * 0.12 - 0.009, s * 0.12 + 0.009, 0.003), M.redBtn]));
      }
      add('rear_cushion', 'Rear seat cushion', mesh(merge(rbox(-1.2, -0.64, 0.43, 0.55, -0.66, 0.66, 0.05), rbox(-1.15, -0.66, 0.53, 0.58, -0.62, 0.62, 0.04)), M.cloth));
      for (const [z0, z1, nm] of [[-0.66, -0.135, 'one-third'], [-0.125, 0.66, 'two-thirds']]) {
        const rb = rbox(-0.07, 0.03, 0, 0.56, z0, z1, 0.04).rotateZ(0.42).translate(-1.15, 0.53, 0);
        add('rear_back', `Rear seat backrest, ${nm}`, mesh(rb, M.cloth));
      }
      for (const z of [-0.44, 0, 0.44]) {
        const top = V3(0, 0.56, 0).applyAxisAngle(V3(0, 0, 1), 0.42).add(V3(-1.15, 0.53, 0));
        add('headrest', `Head restraint, rear ${z < 0 ? 'left' : z > 0 ? 'right' : 'middle'}`, group([rbox(top.x - 0.06, top.x + 0.04, top.y + 0.04, top.y + 0.15, z - 0.12, z + 0.12, 0.035), M.cloth],
          [merge(rodG([top.x, top.y, z - 0.06], [top.x - 0.01, top.y + 0.06, z - 0.06], 0.005), rodG([top.x, top.y, z + 0.06], [top.x - 0.01, top.y + 0.06, z + 0.06], 0.005)), M.chrome]));
        add('buckle', `Seat belt buckle, rear ${z < 0 ? 'left' : z > 0 ? 'right' : 'middle'}`, group([rbox(-0.7, -0.66, 0.53, 0.59, z + 0.1 - 0.014, z + 0.1 + 0.014, 0.008), M.blackPaint], [rbox(-0.665, -0.655, 0.55, 0.57, z + 0.1 - 0.009, z + 0.1 + 0.009, 0.003), M.redBtn]));
      }
      for (const s of [-1, 1]) add('belt', `Seat belt, rear ${sideName(s)}`, group([rbox(-1.52, -1.47, 0.55, 1.12, s * 0.66 - 0.006, s * 0.66, 0.002), M.blackPaint], [rbox(-1.52, -1.47, 0.62, 0.68, s * 0.66 - 0.014, s * 0.66 - 0.006, 0.003), M.chrome]));
      // the carpet over the floor and the tunnel, up the bulkhead under the dash
      const cp = [[-0.69, FLOOR], [-0.15, FLOOR], [-0.12, FLOOR + 0.15], [0.12, FLOOR + 0.15], [0.15, FLOOR], [0.69, FLOOR]];
      const cpts = [...cp.map(([z, y]) => [z, y + 0.012]).reverse(), ...cp];
      const carpetS = new THREE.Shape(cpts.map(([z, y]) => V2(z, y)));
      const floorC = new THREE.ExtrudeGeometry(carpetS, { depth: XBH - 0.05 - (-1.2), bevelEnabled: false }).rotateY(-Math.PI / 2).translate(XBH - 0.05, 0, 0);
      const toe = rbox(XBH - 0.06, XBH + 0.0, FLOOR, 0.62, -0.69, 0.69, 0.005);
      add('carpet', 'Carpet', mesh(merge(floorC, toe), M.carpet));
      // the door panels, their armrests, pulls and speaker grilles
      for (const s of [-1, 1]) for (const [x0, x1, nm] of [[-0.24, XBH - 0.05, 'front'], [-1.1, -0.27, 'rear']]) {
        const zi = s * 0.712, dz = s * 0.02;
        const card = rbox(x0, x1, 0.3, 1.0, Math.min(zi, zi + s * 0.02), Math.max(zi, zi + s * 0.02), 0.01);
        const arm = rbox(x0 + 0.12, x1 - (nm === 'front' ? 0.25 : 0.12), 0.6, 0.66, Math.min(zi - s * 0.05, zi), Math.max(zi - s * 0.05, zi), 0.015);
        const insert = rbox(x0 + 0.06, x1 - 0.06, 0.68, 0.92, Math.min(zi - s * 0.005, zi), Math.max(zi - s * 0.005, zi), 0.008);
        const grille = new THREE.CircleGeometry(0.065, 32).rotateY(-s * Math.PI / 2).translate(x1 - 0.15, 0.42, zi - s * 0.003);
        const pull = rbox(x1 - 0.2, x1 - 0.12, 0.72, 0.75, Math.min(zi - s * 0.012, zi), Math.max(zi - s * 0.012, zi), 0.006);
        add('door_card', `Door trim panel, ${nm} ${sideName(s)}`, group([merge(card, arm), M.trimGrey], [insert, M.cloth], [grille, M.blackPaint], [pull, M.chrome]), { dir: [0, 0.1, s] });
        void dz;
      }
      add('parcel', 'Parcel shelf', mesh(rbox(XB + 0.12, -1.32, 0.955, 0.972, -0.62, 0.62, 0.006), M.carpet));
      add('mirror_i', 'Rear-view mirror', group([merge(rodG([0.3, 1.33, 0], [0.27, 1.3, 0], 0.006), rbox(0.245, 0.27, 1.25, 1.3, -0.12, 0.12, 0.012)), M.blackPaint], [rbox(0.241, 0.246, 1.255, 1.295, -0.115, 0.115, 0.004), M.reflector]));
      for (const s of [-1, 1]) add('visor', `Sun visor, ${sideName(s)}`, mesh(rbox(0.04, 0.2, 1.37, 1.385, Math.min(s * 0.1, s * 0.52), Math.max(s * 0.1, s * 0.52), 0.006), M.trimGrey));
    }

    // ── wiring and lights ──
    {
      // the battery over the gearbox, its tray and clamp, the fuse box on its positive post; the cables and earths
      const bx0 = FX - 0.02, bx1 = FX + 0.26, by0 = EY + 0.185, bz0 = -0.66, bz1 = -0.485;
      add('batt_tray', 'Battery tray', mesh(merge(rbox(bx0 - 0.02, bx1 + 0.02, by0 - 0.02, by0 + 0.003, bz0 - 0.02, bz1 + 0.02, 0.006), rbox(bx0 - 0.02, bx1 + 0.02, by0 - 0.02, by0 + 0.03, bz1 + 0.012, bz1 + 0.02, 0.003)), M.plastic));
      const bat = add('battery', 'Battery (12 V)', group([rbox(bx0, bx1, by0, by0 + 0.175, bz0, bz1, 0.008), M.plastic], [rbox(bx0 + 0.005, bx1 - 0.005, by0 + 0.17, by0 + 0.19, bz0 + 0.005, bz1 - 0.005, 0.006), M.blackPaint],
        [merge(cylY(0.009, 0.02, by0 + 0.19, bx1 - 0.03, bz1 - 0.03, 14), cylY(0.009, 0.02, by0 + 0.19, bx0 + 0.03, bz1 - 0.03, 14)), M.zinc]));
      add('batt_fuse', 'Battery fuse box', mesh(rbox(bx1 - 0.08, bx1 + 0.01, by0 + 0.19, by0 + 0.24, bz1 - 0.08, bz1 + 0.0, 0.008), M.plastic), { parent: bat });
      const plus = [bx1 - 0.03, by0 + 0.24, bz1 - 0.03], minus = [bx0 + 0.03, by0 + 0.21, bz1 - 0.03];
      const stP = [EX + 0.12, EY + 0.08, GZ0 - 0.12], alt = toCar([XA + 0.139, 0.018, -0.185]);
      add('batt_cable', 'Battery positive cable (starter and alternator)', mesh(merge(hoseG([plus, [plus[0], plus[1] + 0.012, plus[2] + 0.08], [EX + 0.05, EY + 0.2, -0.3], stP], 0.011, 40, 12),
        hoseG([stP, [EX + 0.2, EY + 0.1, GZ0 + 0.1], [alt.x + 0.05, alt.y + 0.05, alt.z - 0.05], alt.toArray()], 0.007, 40, 10)), M.wireRed));
      add('earth', 'Earth strap (battery to body)', mesh(hoseG([minus, [minus[0] - 0.02, minus[1] + 0.03, minus[2] - 0.05], [bx0 - 0.03, by0 + 0.05, -0.72]], 0.008, 20, 10), M.wireBrown));
      add('earth', 'Earth strap (gearbox to body)', mesh(hoseG([[FX + 0.1, EY + 0.12, GZ0 - 0.41], [FX + 0.1, EY + 0.14, -0.62], [FX + 0.1, EY + 0.1, -0.72]], 0.008, 16, 10), M.wireBrown));
      // the starter on the gearbox's bellhousing, its solenoid
      const st = add('starter', 'Starter motor', group([merge(cylZ(0.042, 0.14, GZ0 - 0.2, EX + 0.12, EY + 0.0, 28), latheZ([[0.0001, 0], [0.042, 0], [0.04, 0.02], [0.0001, 0.025]], 24).translate(EX + 0.12, EY, GZ0 - 0.225)), M.blackPaint],
        [cylZ(0.035, 0.06, GZ0 - 0.06, EX + 0.12, EY, 24), M.aluCast]));
      add('starter_sol', 'Starter solenoid', mesh(merge(cylZ(0.024, 0.09, GZ0 - 0.16, EX + 0.12, EY + 0.065, 20), cylZ(0.004, 0.015, GZ0 - 0.175, EX + 0.12, EY + 0.075, 8)), M.zinc), { parent: st });
      // the engine control unit, under the windscreen in the plenum
      const ecu = [XBH + 0.12, 0.895, -0.3];
      add('ecu', 'Engine control unit', group([rbox(ecu[0] - 0.08, ecu[0] + 0.08, ecu[1] - 0.02, ecu[1] + 0.02, ecu[2] - 0.11, ecu[2] + 0.11, 0.006), M.alu],
        [rbox(ecu[0] - 0.09, ecu[0] - 0.075, ecu[1] - 0.015, ecu[1] + 0.015, ecu[2] - 0.08, ecu[2] + 0.08, 0.004), M.connector]));
      // the fuse box at the dash's end, the relay carrier under the column; the catalogue's two relays on it
      const fz = DS * 0.665;
      const fb = add('fuse_box', 'Fuse box', mesh(rbox(0.58, 0.64, 0.76, 0.93, fz - 0.03, fz + 0.03, 0.006), M.connector));
      const fuses = [], fm = [M.fuseBlue, M.fuseRed, M.fuseYellow];
      const fz2 = DS * 0.64;
      for (let k = 0; k < 18; k++) fuses.push(box(0.012, 0.008, 0.016, 0.576, 0.78 + (k % 9) * 0.016, fz2 + (k < 9 ? -0.01 : 0.01)));
      add('fuse', 'Fuses', group(...fm.map((m, i) => [merge(fuses.filter((_, k) => k % 3 === i)), m])), { parent: fb });
      const rp = [0.62, 0.66, DS * 0.22];
      const plate = add('relay_plate', 'Relay carrier', mesh(rbox(rp[0] - 0.06, rp[0] + 0.06, rp[1] - 0.008, rp[1], rp[2] - 0.1, rp[2] + 0.1, 0.004), M.connector));
      add('relay_acc', 'Accessory power relay', mesh(rbox(rp[0] - 0.02, rp[0] + 0.02, rp[1] - 0.042, rp[1] - 0.008, rp[2] - 0.07, rp[2] - 0.03, 0.004), M.connGrey), { parent: plate });
      add('relay_start', 'Starter relay', mesh(rbox(rp[0] - 0.02, rp[0] + 0.02, rp[1] - 0.042, rp[1] - 0.008, rp[2] + 0.0, rp[2] + 0.04, 0.004), M.connGrey), { parent: plate });
      // looms: corrugated conduit with its plugs at the ends
      const loom = (nm, pts, r = 0.011, plugs = []) => {
        const g = [hoseG(pts, r, Math.max(20, pts.length * 14), 12)];
        const pl = plugs.map(p => rbox(p[0] - 0.015, p[0] + 0.015, p[1] - 0.012, p[1] + 0.012, p[2] - 0.02, p[2] + 0.02, 0.004));
        add('loom', nm, group([merge(g), M.loom], ...(pl.length ? [[merge(pl), M.connector]] : [])));
      };
      const pump = toCar([XF + 0.09, 0.24, -0.145]), glowEnd = toCar([cxi(3) + 0.03, YH0 + 0.07, 0.12]), glowStart = toCar([cxi(0) + 0.0, YH0 + 0.07, 0.12]);
      loom('Engine harness (control unit to the injection pump)', [ecu, [ecu[0] - 0.02, ecu[1] - 0.06, -0.1], [FX - 0.1, 0.86, 0.05], [FX + 0.12, 0.8, 0.18], [pump.x, pump.y + 0.06, pump.z], pump.toArray()], 0.012, [pump.toArray()]);
      loom('Engine harness (glow plugs)', [[FX - 0.1, 0.86, 0.05], [glowStart.x - 0.02, glowStart.y + 0.04, glowStart.z], [glowEnd.x - 0.02, glowEnd.y + 0.04, glowEnd.z]], 0.008, [[glowEnd.x - 0.02, glowEnd.y + 0.04, glowEnd.z]]);
      loom('Engine harness (alternator and starter)', [[FX - 0.1, 0.84, 0.0], [EX + 0.04, EY + 0.22, -0.15], [alt.x + 0.04, alt.y + 0.06, alt.z - 0.04], [stP[0], stP[1] + 0.05, stP[2]]], 0.008, [[stP[0], stP[1] + 0.05, stP[2]]]);
      const hl = s => [XN - 0.2, 0.68, s * 0.55], tl = s => [XB + 0.12, 0.88, s * 0.62];
      loom('Front harness (lights, horn, fans)', [[XBH + 0.02, 0.76, -0.55], [FX + 0.05, 0.8, -0.68], [XN - 0.32, 0.78, -0.6], hl(-1), [XN - 0.3, 0.76, -0.3], [XN - 0.3, 0.76, 0.3], hl(1)], 0.01, [hl(-1), hl(1)]);
      loom('Dashboard harness', [[0.7, 0.86, -0.66], [0.72, 0.9, -0.3], [0.72, 0.92, 0], [0.7, 0.95, DS * 0.36], [0.72, 0.9, 0.66 * DS]], 0.014, [[0.7, 0.98, DS * 0.36]]);
      loom('Body harness (along the sill to the rear lights and tailgate)', [[0.6, 0.62, -DS * 0.0 - 0.6], [0.55, 0.32, -0.66], [-0.4, 0.3, -0.67], [-1.25, 0.32, -0.67], [-1.6, 0.6, -0.66], tl(-1), [XB + 0.12, 0.92, 0], tl(1), [XB + 0.22, 1.02, 0.5], [-1.62, 1.2, 0.3], [-1.6, 1.23, 0.14]], 0.012, [tl(-1), tl(1)]);
      loom('Fuel pump harness', [[-0.6, 0.3, -0.66], [-0.75, 0.38, -0.45], [-0.86, 0.47, -0.25]], 0.006, [[-0.86, 0.47, -0.25]]);
      for (const s of [-1, 1]) for (const [x, nm] of [[XBH - 0.03, 'front'], [-0.26, 'rear']]) {
        add('loom', `Door harness, ${nm} ${sideName(s)}`, group([hoseG([[x, 0.8, s * 0.64], [x - 0.04, 0.8, s * 0.7], [x - 0.1, 0.8, s * 0.74]], 0.008, 10, 10), M.loom],
          [along(bellowsG(0.016, 0.016, 0.07, 6), [x - 0.005, 0.8, s * 0.66], [x - 0.07, 0.8, s * 0.73]), M.rubber]));
      }
      for (const [ax, s, front] of [[FX, -1, true], [FX, 1, true], [RX, -1, false], [RX, 1, false]]) {
        const pts = front ? [[ax - 0.03, YW + 0.06, s * 0.68], [ax - 0.04, 0.6, s * 0.63], [ax - 0.05, 0.78, s * 0.62]] : [[ax + 0.05, YW + 0.06, s * 0.63], [ax + 0.12, 0.38, s * 0.58], [ax + 0.2, 0.36, s * 0.6]];
        add('abs_lead', `ABS sensor lead, ${front ? 'front' : 'rear'} ${sideName(s)}`, group([hoseG(pts, 0.004, 20, 8), M.loom], [cylY(0.008, 0.025, pts[0][1] - 0.01, pts[0][0], pts[0][2], 12), M.connector]));
      }
      // the lights, in the body's openings: clear lenses over twin round reflectors and the indicator; rear
      // lights in red with their amber band; repeaters on the wings; the plate lights; the third brake light
      const lensR = patch(panel('headlight'));
      const nearN = (g, P) => { const p = g.attributes.position.array, n = g.attributes.normal.array; let bi = 0, bd = 1e9;
        for (let i = 0; i < p.length; i += 3) { const d = (p[i] - P.x) ** 2 + (p[i + 1] - P.y) ** 2 + (p[i + 2] - P.z) ** 2; if (d < bd) { bd = d; bi = i; } } return V3(n[bi], n[bi + 1], n[bi + 2]); };
      const bowl = (r, depth) => latheY([[0.0001, 0], [r * 0.5, depth * 0.25], [r * 0.85, depth * 0.7], [r, depth]], 40);
      const hlg = { refl: [], amber: [], bulbs: [], bezel: [] };
      for (const [zb, r, kind2] of [[0.37, 0.068, 'refl'], [0.56, 0.072, 'refl'], [0.71, 0.04, 'amber']]) {
        const yb = kind2 === 'amber' ? 0.64 : 0.665, xs = endX(yb, zb, true), P = V3(xs, yb, zb), n = nearN(lensR, P);
        const q = new THREE.Quaternion().setFromUnitVectors(UP, n), rim = P.clone().addScaledVector(n, -0.022), base = rim.clone().addScaledVector(n, -0.042);
        hlg[kind2].push(bowl(r, 0.042).applyQuaternion(q).translate(base.x, base.y, base.z));
        hlg.bezel.push(new THREE.RingGeometry(r, r + 0.014, 40).rotateX(-Math.PI / 2).applyQuaternion(q).translate(rim.x, rim.y, rim.z));
        const f = base.clone().addScaledVector(n, 0.02);
        hlg.bulbs.push(new THREE.SphereGeometry(kind2 === 'amber' ? 0.008 : 0.01, 12, 8).translate(f.x, f.y, f.z));
        if (kind2 === 'refl') { const c = base.clone().addScaledVector(n, 0.03); hlg.bulbs.push(new THREE.SphereGeometry(0.017, 20, 10, 0, TAU, 0, Math.PI / 2).applyQuaternion(q).translate(c.x, c.y, c.z)); }
      }
      const hlParts = [[lensR, M.lens], [offsetG(lensR, -0.075), M.plastic], [merge(hlg.refl), M.reflector], [merge(hlg.amber), M.lensAmber], [merge(hlg.bulbs), M.bulb], [merge(hlg.bezel), M.trimSilver]];
      const tRed = patch((p, x, t) => REG.taillight(p, x, t, GAP) && !(p[1] > 0.845 && p[1] < 0.895)), tAmb = patch((p, x, t) => REG.taillight(p, x, t, GAP) && p[1] > 0.849 && p[1] < 0.891);
      const tBulbs = [0.8, 0.94].map(y => { const x = endX(y, 0.68, false) + 0.035; return new THREE.SphereGeometry(0.011, 10, 8).translate(x, y, 0.66); });
      const tlParts = [[tRed, M.lensRed], [tAmb, M.lensAmber], [offsetG(merge(tRed, tAmb), -0.05), M.plastic], [merge(tBulbs), M.bulb]];
      for (const s of [-1, 1]) {
        const sideOf = g => (s > 0 ? g : mirrorZ(g));
        add('headlight', `Headlight, ${sideName(s)}`, group(...hlParts.map(([g, m]) => [sideOf(g), m])), { dir: [1, 0, s * 0.2] });
        add('taillight', `Rear light, ${sideName(s)}`, group(...tlParts.map(([g, m]) => [sideOf(g), m])), { dir: [-1, 0, s * 0.2] });
        const zr = sideZAt(FX + 0.53, 0.755);
        add('repeater', `Side indicator repeater, ${sideName(s)}`, mesh(sideOf(rbox(FX + 0.5, FX + 0.56, 0.745, 0.766, zr - 0.004, zr + 0.006, 0.004)), M.lensAmber), { dir: [0, 0, s] });
        const xp = endX(0.69, 0.15, false);
        add('plate_lamp', `Number plate light, ${sideName(s)}`, mesh(sideOf(rbox(xp - 0.006, xp + 0.004, 0.684, 0.696, 0.12, 0.18, 0.003)), M.lens));
      }
      const yb3 = TOP(-1.5) - 0.035;
      add('brake_lamp', 'High-level brake light', group([rbox(-1.53, -1.47, yb3 - 0.012, yb3 + 0.013, -0.15, 0.15, 0.008), M.plastic], [rbox(-1.534, -1.526, yb3 - 0.009, yb3 + 0.01, -0.14, 0.14, 0.003), M.lensRed]));
      add('horn', 'Horn', group([latheX([[0.0001, 0], [0.045, 0], [0.045, 0.02], [0.03, 0.03], [0.0001, 0.03]], 28).translate(XN - 0.2, 0.42, -0.42), M.paintBlack], [rbox(XN - 0.18, XN - 0.15, 0.4, 0.44, -0.44, -0.4, 0.004), M.steel]));
      // the wipers: the motor and its linkage under the scuttle, two arms and blades on the windscreen
      const spindles = [[0.905, 0.958, DS * 0.5], [0.905, 0.958, -DS * 0.06]];
      // (in the plenum under the scuttle panel: only the spindles come up through it)
      add('wiper_motor', 'Wiper motor and linkage', group([merge(cylZ(0.035, 0.09, -0.045 + DS * 0.25, XBH + 0.07, 0.85, 24), rbox(XBH + 0.03, XBH + 0.11, 0.81, 0.885, DS * 0.25 - 0.03, DS * 0.25 + 0.03, 0.01)), M.paintBlack],
        [merge(rodG([XBH + 0.07, 0.89, DS * 0.25], [spindles[0][0], 0.935, spindles[0][2]], 0.005), rodG([XBH + 0.07, 0.89, DS * 0.25], [spindles[1][0], 0.935, spindles[1][2]], 0.005),
          ...spindles.map(p => cylY(0.012, 0.06, 0.93, p[0], p[2], 16))), M.zinc]));
      const wd = V3(-0.045, 0.03, -DS).normalize();
      for (const [i, p] of spindles.entries()) {
        const who = i === 0 ? 'driver’s' : 'passenger’s', len = i === 0 ? 0.5 : 0.46;
        const base = V3(p[0], p[1] + 0.02, p[2]), tip = base.clone().addScaledVector(wd, len);
        const arm = add('wiper_arm', `Wiper arm, ${who}`, mesh(merge(rodG(base.toArray(), tip.toArray(), 0.006), rbox(base.x - 0.02, base.x + 0.02, base.y - 0.005, base.y + 0.02, base.z - 0.02, base.z + 0.02, 0.006)), M.paintBlack));
        add('wiper_cap', `Wiper arm cap, ${who}`, mesh(latheY([[0.0001, 0], [0.013, 0], [0.012, 0.012], [0.0001, 0.015]], 16).translate(base.x, base.y + 0.02, base.z), M.plastic), { parent: arm });
        const b0 = tip.clone().addScaledVector(wd, -len * 0.92).add(V3(0.01, -0.012, 0)), b1 = tip.clone().addScaledVector(wd, 0.03).add(V3(0.01, -0.012, 0));
        add('wiper_blade', `Wiper blade, ${who}`, mesh(merge(rodG(b0.toArray(), b1.toArray(), 0.005), rodG(b0.clone().add(V3(0.004, -0.006, 0)).toArray(), b1.clone().add(V3(0.004, -0.006, 0)).toArray(), 0.0025)), M.rubber), { parent: arm });
      }
    }

    // ── exhaust: from the turbo back, under the car, to the tailpipe ──
    {
      const out = toCar([-0.062, YH0 - 0.1, 0.205]);
      const p0 = [out.x, out.y, out.z + 0.006];
      const dp = [p0, [p0[0], p0[1] - 0.01, p0[2] + 0.06], [FX - 0.07, 0.43, 0.29], [FX - 0.15, 0.32, 0.25], [FX - 0.3, 0.27, 0.13], [FX - 0.46, 0.245, 0.07]];
      add('exh_gasket', 'Exhaust gasket (turbo to downpipe)', mesh(torusZ(0.03, 0.004, p0[0], p0[1], p0[2] - 0.003, 6, 24), M.gasket));
      for (let k = 0; k < 3; k++) { const a = k / 3 * TAU + 0.5; add('exh_nut', 'Exhaust flange nut (turbo)', mesh(hexY(0.0065, 0.008).rotateX(Math.PI / 2).translate(p0[0] + 0.029 * Math.cos(a), p0[1] + 0.029 * Math.sin(a), p0[2] + 0.012), M.zinc)); }
      add('downpipe', 'Downpipe', mesh(merge(hoseG(dp, 0.028, 60, 18), latheZ([[0.028, 0], [0.042, 0], [0.042, 0.01], [0.028, 0.01]], 24).translate(p0[0], p0[1], p0[2])), M.rusty));
      // the flexible joint, the converter
      const fx0 = FX - 0.46, fx1 = FX - 0.66, cx0 = FX - 0.7, cx1 = FX - 1.06, ey = 0.245, ez = 0.07;
      const flex = [];
      for (let k = 0; k < 24; k++) flex.push(torusX(0.03, 0.0035, fx0 - 0.006 - k * (fx0 - fx1 - 0.012) / 23, ey, ez));
      const cat = latheX([[0.0001, cx1 - 0.05], [0.026, cx1 - 0.05], [0.026, cx1], [0.068, cx1 + 0.04], [0.068, cx0 - 0.04], [0.026, cx0], [0.026, fx1], [0.0001, fx1]], 40);
      cat.translate(0, ey, ez);
      add('front_pipe', 'Front pipe, flexible joint and catalytic converter', group([merge(cat.scale(1, 0.78, 1).translate(0, ey * 0.22, 0)), M.exhaust], [merge(flex, cylX(0.031, fx0 - fx1, fx1, ey, ez, 24)), M.steel],
        [merge(latheX([[0.028, -0.005], [0.04, -0.005], [0.04, 0.005], [0.028, 0.005]], 24).translate(fx0 + 0.005, ey, ez)), M.rusty]));
      add('exh_gasket', 'Exhaust gasket (downpipe to front pipe)', mesh(torusX(0.032, 0.004, fx0 + 0.012, ey, ez), M.gasket));
      // the centre pipe and middle silencer, over toward the right; the rear pipe over the axle; the rear silencer
      const mx0 = -0.22, mx1 = -0.66;
      const mid = [hoseG([[cx1 - 0.05, ey, ez], [cx1 - 0.3, ey, ez], [mx0 + 0.04, ey, ez + 0.02], [mx0, ey, ez + 0.03]], 0.026, 30, 14),
        latheX([[0.0001, mx1], [0.03, mx1], [0.075, mx1 + 0.03], [0.075, mx0 - 0.03], [0.03, mx0], [0.0001, mx0]], 40).scale(1, 0.75, 1).translate(0, ey, ez + 0.03),
        hoseG([[mx1, ey, ez + 0.03], [mx1 - 0.15, ey, ez + 0.08], [-0.98, 0.3, 0.3], [RX + 0.2, 0.41, 0.36]], 0.025, 40, 14)];
      add('mid_box', 'Centre pipe and middle silencer', mesh(merge(mid), M.exhaust));
      const rb = [hoseG([[RX + 0.2, 0.41, 0.36], [RX - 0.02, 0.41, 0.38], [RX - 0.2, 0.36, 0.34], [-1.55, 0.33, 0.26]], 0.025, 40, 14),
        rbox(-1.86, -1.55, 0.25, 0.4, -0.38, 0.32, 0.06),
        hoseG([[-1.76, 0.29, -0.36], [-1.8, 0.29, -0.42], [-1.92, 0.28, -0.43], [XB + 0.03, 0.28, -0.43]], 0.025, 20, 14)];
      const seams = [latheZ([[0.0001, 0], [0.002, 0], [0.002, 0.004], [0.0001, 0.004]], 4)];
      for (const z of [-0.38, 0.32]) seams.push(rbox(-1.865, -1.545, 0.245, 0.405, z - 0.004, z + 0.004, 0.01));
      add('rear_box', 'Rear silencer and tailpipe', group([merge(rb), M.exhaust], [merge(seams.slice(1)), M.steel], [latheX([[0.022, -0.06], [0.03, -0.06], [0.03, 0.0], [0.022, 0.0]], 24).translate(XB + 0.03, 0.28, -0.43), M.chrome]));
      for (const x of [cx1 - 0.1, RX + 0.2]) add('exh_clamp', 'Exhaust clamp', mesh(merge(torusX(0.029, 0.005, x, x > -1 ? ey : 0.41, x > -1 ? ez : 0.36), hexY(0.006, 0.008).translate(x, (x > -1 ? ey : 0.41) + 0.03, x > -1 ? ez : 0.36)), M.zinc));
      // the rubber hangers on their hooks
      const hang = (nm, x, y, z) => add('hanger', nm, group([torusX(0.018, 0.006, x, y + 0.05, z), M.rubber], [merge(rodG([x, y, z], [x, y + 0.035, z], 0.004), rodG([x, y + 0.065, z], [x, y + 0.1, z], 0.004)), M.steel]));
      hang('Exhaust rubber hanger (converter)', cx1 - 0.15, ey + 0.02, ez);
      hang('Exhaust rubber hanger (middle silencer)', mx1 - 0.08, ey + 0.02, ez + 0.06);
      hang('Exhaust rubber hanger (rear silencer, left)', -1.7, 0.39, -0.32);
      hang('Exhaust rubber hanger (rear silencer, right)', -1.7, 0.39, 0.27);
      // heat shields above them, embossed aluminium
      const hs1 = new THREE.CylinderGeometry(0.12, 0.12, cx0 - cx1 + 0.3, 24, 1, true, 0, Math.PI).rotateZ(Math.PI / 2).translate((cx0 + cx1) / 2, ey + 0.03, ez);
      const hs2 = new THREE.CylinderGeometry(0.12, 0.12, mx0 - mx1 + 0.2, 24, 1, true, 0, Math.PI).rotateZ(Math.PI / 2).translate((mx0 + mx1) / 2, ey + 0.03, ez + 0.03);
      M.shield.side = THREE.DoubleSide; M.shield.userData.side = THREE.DoubleSide;
      add('heat_shield', 'Heat shield (converter)', mesh(hs1, M.shield));
      add('heat_shield', 'Heat shield (middle silencer)', mesh(hs2, M.shield));
      add('heat_shield', 'Heat shield (rear silencer)', mesh(rbox(-1.9, -1.5, 0.45, 0.455, -0.42, 0.36, 0.002), M.shield));
    }

    // ── fuel: the tank under the rear seat, its straps, the sender, filler, lines and filter ──
    {
      const tx0 = -1.14, tx1 = -0.62, ty0 = 0.2, ty1 = 0.41, tz0 = -0.64, tz1 = 0.14;
      const tank = add('fuel_tank', 'Fuel tank (55 litres)', mesh(merge(rbox(tx0, tx1, ty0 + 0.03, ty1, tz0, tz1, 0.04), rbox(tx0 + 0.04, tx1 - 0.04, ty0, ty0 + 0.06, tz0 + 0.04, tz1 - 0.06, 0.03)), M.tank));
      void tank;
      for (const x of [-0.72, -1.04]) {
        add('tank_strap', 'Fuel tank strap', mesh(merge(rbox(x - 0.02, x + 0.02, ty0 - 0.006, ty0 - 0.0, tz0 - 0.02, tz1 + 0.02, 0.002), rbox(x - 0.02, x + 0.02, ty0 - 0.006, ty1 + 0.03, tz0 - 0.026, tz0 - 0.02, 0.002),
          rbox(x - 0.02, x + 0.02, ty0 - 0.006, ty1 + 0.03, tz1 + 0.02, tz1 + 0.026, 0.002), hexY(0.009, 0.008, ty1 + 0.03).translate(x, 0, tz0 - 0.023), hexY(0.009, 0.008, ty1 + 0.03).translate(x, 0, tz1 + 0.023)), M.zinc));
        add('strap_spacer', 'Fuel tank strap spacer', mesh(rbox(x - 0.025, x + 0.025, ty0 - 0.012, ty0 - 0.006, -0.3, -0.2, 0.002), M.rubber));
      }
      const sx = -0.86, sz = -0.25;
      const snd = add('sender', 'Fuel pump and sender', group([merge(latheY([[0.0001, 0], [0.06, 0], [0.06, 0.01], [0.045, 0.02], [0.0001, 0.02]], 32), cylY(0.04, 0.18, -0.18, 0, 0, 24)).translate(sx, ty1, sz), M.plastic],
        [merge(cylY(0.006, 0.03, ty1 + 0.015, sx + 0.025, sz, 10), cylY(0.006, 0.03, ty1 + 0.015, sx - 0.025, sz, 10), rbox(sx - 0.015, sx + 0.015, ty1 + 0.015, ty1 + 0.035, sz + 0.02, sz + 0.05, 0.004)), M.connGrey]));
      add('tank_seal', 'Fuel sender seal', mesh(torusY(0.062, 0.004, sx, ty1 + 0.002, sz), M.rubber), { parent: snd });
      add('lock_ring', 'Fuel tank lock ring', mesh(merge(latheY([[0.06, 0], [0.078, 0], [0.078, 0.008], [0.06, 0.008]], 40), ...Array.from({ length: 8 }, (_, k) => box(0.01, 0.012, 0.012, 0.072 * Math.cos(k / 8 * TAU), 0.006, 0.072 * Math.sin(k / 8 * TAU)))).translate(sx, ty1 + 0.004, sz), M.zinc));
      add('gravity_valve', 'Gravity (roll-over) valve', mesh(merge(latheY([[0.0001, 0], [0.02, 0], [0.022, 0.03], [0.012, 0.05], [0.0001, 0.05]], 20), cylX(0.004, 0.04, 0.0, 0.035, 0, 8)).translate(tx0 + 0.08, ty1, tz1 - 0.08), M.plastic));
      const zFl = sideZAt(-1.46, 0.84), fpts = [[tx0 + 0.06, ty1 - 0.03, tz1 - 0.02], [-1.25, 0.46, 0.36], [-1.4, 0.75, zFl - 0.2], [-1.46, 0.84, zFl - 0.05]];
      add('filler', 'Filler neck', mesh(merge(hoseG(fpts, 0.026, 40, 16), hoseG([[tx0 + 0.1, ty1, tz1 - 0.05], [-1.22, 0.5, 0.4], [-1.42, 0.8, zFl - 0.09]], 0.006, 30, 8)), M.rubber));
      add('fuel_cap', 'Fuel filler cap', mesh(merge(latheZ([[0.0001, 0], [0.034, 0], [0.036, 0.008], [0.034, 0.016], [0.0001, 0.016]], 28), box(0.05, 0.012, 0.012, 0, 0, 0.02)).translate(-1.46, 0.84, zFl - 0.04), M.plastic));
      // feed and return along the floor to the filter in the engine bay, then to the injection pump
      const filt = [FX - 0.14, 0.75, 0.48], pump = toCar([XF + 0.12, 0.17 + 0.05, -0.12]);
      for (const [dz, nm] of [[-0.012, 'feed'], [0.012, 'return']]) {
        add('fuel_line', `Fuel line (${nm})`, mesh(hoseG([[sx, ty1 + 0.035, sz + dz], [sx + 0.1, 0.32, -0.3 + dz], [-0.4, 0.22, -0.32 + dz], [0.7, 0.22, -0.32 + dz], [XBH + 0.08, 0.22, -0.34 + dz], [FX - 0.22, 0.5, 0.3 + dz], [filt[0] - 0.02, filt[1] - 0.12, filt[2] + dz]], 0.004, 120, 8), M.zinc));
      }
      add('fuel_line', 'Fuel line (filter to the injection pump)', mesh(hoseG([[filt[0], filt[1] + 0.09, filt[2]], [filt[0] + 0.08, filt[1] + 0.06, filt[2] - 0.05], [pump.x, pump.y + 0.08, pump.z], pump.toArray()], 0.005, 40, 8), M.rubber));
      const ff = add('fuel_filter', 'Fuel filter', group([merge(cylY(0.045, 0.16, filt[1] - 0.09, filt[0], filt[2], 32), latheY([[0.0001, 0], [0.045, 0], [0.04, 0.012], [0.0001, 0.014]], 28).translate(filt[0], filt[1] + 0.07, filt[2])), M.alu],
        [merge(cylY(0.007, 0.03, filt[1] + 0.07, filt[0] + 0.02, filt[2], 10), cylY(0.007, 0.03, filt[1] + 0.07, filt[0] - 0.02, filt[2], 10)), M.plastic]));
      add('filter_plate', 'Fuel filter retainer plate', mesh(merge(latheY([[0.046, 0], [0.052, 0], [0.052, 0.03], [0.046, 0.03]], 32).translate(filt[0], filt[1] - 0.02, filt[2]), rbox(filt[0] - 0.01, filt[0] + 0.01, filt[1] - 0.02, filt[1] + 0.01, filt[2] + 0.05, filt[2] + 0.1, 0.003)), M.steel), { parent: ff });
    }
  }

  // ── the cluster's face, drawn: two big dials, two small, blue numbers and red needles ──
  function clusterTexture() {
    const cv = document.createElement('canvas'); cv.width = 1024; cv.height = 440;
    const g = cv.getContext('2d');
    g.fillStyle = '#08090b'; g.fillRect(0, 0, cv.width, cv.height);
    const dial = (cx, cy, r, max, step, label, needle) => {
      g.strokeStyle = '#2a2f38'; g.lineWidth = 6; g.beginPath(); g.arc(cx, cy, r, 0, TAU); g.stroke();
      const a0 = Math.PI * 0.75, a1 = Math.PI * 2.25;
      g.fillStyle = '#a9c8ff'; g.strokeStyle = '#a9c8ff'; g.font = `600 ${Math.round(r * 0.16)}px sans-serif`; g.textAlign = 'center'; g.textBaseline = 'middle';
      for (let v = 0; v <= max; v += step / 2) {
        const a = a0 + (a1 - a0) * v / max, big = Math.abs(v / step - Math.round(v / step)) < 1e-6;
        g.lineWidth = big ? 5 : 2; g.beginPath(); g.moveTo(cx + Math.cos(a) * r * 0.93, cy + Math.sin(a) * r * 0.93); g.lineTo(cx + Math.cos(a) * r * (big ? 0.8 : 0.86), cy + Math.sin(a) * r * (big ? 0.8 : 0.86)); g.stroke();
        if (big) g.fillText(String(v), cx + Math.cos(a) * r * 0.64, cy + Math.sin(a) * r * 0.64);
      }
      g.font = `500 ${Math.round(r * 0.1)}px sans-serif`; g.fillText(label, cx, cy + r * 0.42);
      const a = a0 + (a1 - a0) * needle;
      g.strokeStyle = '#ff3a22'; g.lineWidth = 7; g.beginPath(); g.moveTo(cx - Math.cos(a) * r * 0.12, cy - Math.sin(a) * r * 0.12); g.lineTo(cx + Math.cos(a) * r * 0.86, cy + Math.sin(a) * r * 0.86); g.stroke();
      g.fillStyle = '#16181c'; g.beginPath(); g.arc(cx, cy, r * 0.1, 0, TAU); g.fill();
    };
    dial(330, 230, 190, 240, 20, 'km/h', 0.0);
    dial(780, 230, 160, 6, 1, '×1000 /min', 0.12);
    const small = (cx, cy, r, lab, f) => { g.strokeStyle = '#a9c8ff'; g.lineWidth = 3; g.beginPath(); g.arc(cx, cy, r, Math.PI * 1.15, Math.PI * 1.85); g.stroke();
      g.fillStyle = '#a9c8ff'; g.font = '600 26px sans-serif'; g.textAlign = 'center'; g.fillText(lab, cx, cy + 10);
      const a = Math.PI * (1.15 + 0.7 * f); g.strokeStyle = '#ff3a22'; g.lineWidth = 5; g.beginPath(); g.moveTo(cx, cy); g.lineTo(cx + Math.cos(a) * r, cy + Math.sin(a) * r); g.stroke(); };
    small(80, 330, 60, 'FUEL', 0.62); small(960, 330, 55, '°C', 0.5);
    const tex = new THREE.CanvasTexture(cv); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 4;
    return tex;
  }

  // ── the body's outline: its whole surface, see-through ──
  function outline() {
    const shell = new THREE.Mesh(both(patch(() => true)), ghost); shell.userData.noAO = true; shell.renderOrder = 2;
    const grp = new THREE.Group(); grp.add(shell);
    return grp;
  }

  return {
    groups: GROUPS, systems: SYSTEMS, openGroups: [],
    cat: {
      wheel: /^wheel, steel$|^wheel$/i, driveshaft: /^axle assembly$|^drive ?shaft$/i, cv_circlip: /drive ?shaft snap ring/i,
      tank_strap: /fuel tank strap$/i, strap_spacer: /strap spacer/i, sender: /fuel pump and sender/i, tank_seal: /fuel pump tank seal|^seal \(fuel/i,
      lock_ring: /fuel tank lock ring/i, gravity_valve: /gravity valve/i, fuel_cap: /fuel tank cap|^cap \(fuel/i, fuel_filter: /^fuel filter$/i, filter_plate: /fuel filter retainer plate/i,
      relay_acc: /accessory power relay/i, relay_start: /starter relay/i, light_switch: /headlamp switch/i, ign_switch: /^ignition switch$/i,
      lock_cyl: /ignition lock cylinder/i, col_lock: /steering column lock/i, starter_sol: /starter solenoid/i, clutch_switch: /clutch starter safety switch/i,
      wiper_motor: /wiper motor/i, wiper_arm: /^wiper arm$|wiper arm washer|wiper arm grommet|^gasket \(wiper/i, wiper_blade: /wiper blade/i, wiper_cap: /wiper arm cap/i,
      caliper: /^disc brake caliper$/i, carrier_bolt: /caliper bracket mounting bolt/i, pad: /brake pads? front|^front pads$/i, pad_clip: /pad retaining clip/i,
      disc_f: /^disc brake rotor( front)?$/i, disc_r: /rotor rear/i, arm_bush_r: /lower control arm rear bushing/i, beam_bush: /axle beam (rubber )?mount/i,
      link_bolt: /stabili[sz]er bar link bolt/i, ps_hose: /power steering (return )?hose/i, condenser: /a\/c condenser/i,
      exp_cap: /^cap \(radiators\)|radiator cap/i, rad_hose: /radiator coolant hose$/i, air_box: /air filter$/i, air_hose: /intake hose|hose sleeve/i,
    },
    // a catalogue row of the engine's systems is the engine's (drawn in one piece here), unless drawn on its own above
    catRow: r => ((CFG.engine_systems || []).includes(r.system) && !/air filter|radiator|coolant hose|fuel filter|intake hose|hose sleeve/i.test(r.name) ? 'engine' : null),
    shell: [M.paint, M.underseal, M.trimBlack, M.dash, M.trimGrey, M.cloth, M.carpet, M.leather, M.iron, M.aluCast, M.plastic, M.blackPaint, M.tank],
    fixed: ['body_shell'],
    ao: 0.11,
    floorY: 0,
    cut: [0, 0, DS],
    runSpeed: 7, runPeriod: Math.PI * 4,
    homeMin: 0.95,
    views: { front: ['Front', [1, 0.35, 0.65]], side: ['Side', [0.05, 0.25, 1]], rear: ['Rear', [-1, 0.4, -0.6]], top: ['Top', [0.05, 1, 0.08]], under: ['Underneath', [0.3, -0.9, 0.4]] },
    firstDir: [0.9, 0.38, 0.72],
    build: buildCar,
    extras,
    ui(tools) {
      const sel = document.createElement('select'); sel.setAttribute('aria-label', 'Paint');
      sel.style.cssText = 'font: 600 .95rem/1 var(--display); border-radius: 8px; border: 1px solid var(--line); background: var(--surface); color: var(--ink); padding: 10px 8px; min-height: 42px';
      for (const [nm, hex] of [['Reflex silver', 0xa6abb0], ['Tornado red', 0xa3141a], ['Indigo blue', 0x1f2f55], ['Black magic', 0x141518], ['Candy white', 0xe9eae6]]) {
        const o = document.createElement('option'); o.textContent = nm; o.value = String(hex); sel.append(o);
      }
      sel.addEventListener('change', () => { M.paint.color.setHex(+sel.value); M.paint.metalness = +sel.value === 0xe9eae6 || +sel.value === 0xa3141a ? 0.15 : 0.6; needs = 3; });
      tools.append(sel);
    },
    steps: () => [
      ['The number plates and the aerial', ['plate', 'aerial'], 'body'], ['The mirrors, door handles, rubbing strips and B-pillar trims', ['mirror', 'handle', 'rub_strip', 'b_trim'], 'body'],
      ['The door windows', ['door_glass'], 'body'], ['The doors', ['door_f', 'door_r'], 'body'], ['The bonnet', ['bonnet'], 'body'],
      ['The grilles and the front bumper', ['grille', 'grille_low', 'bumper_f'], 'body'], ['The wings and the wheel arch liners', ['wing', 'arch_liner'], 'body'],
      ['The rear window and the tailgate', ['rear_glass', 'tailgate'], 'body'], ['The rear bumper and the fuel flap', ['bumper_r', 'fuel_flap'], 'body'], ['The scuttle panel', ['scuttle'], 'body'], ['The windscreen', ['windscreen'], 'body'],
      ['The wheel trims', ['trim'], 'brakes'], ['The wheel bolts', ['wheel_bolt'], 'brakes'], ['The wheels', ['wheel'], 'brakes'], ['The tyres off the wheels', ['tyre'], 'brakes'],
      ['The pad clips and caliper guide bolts', ['pad_clip', 'guide_bolt'], 'brakes'], ['The calipers', ['caliper', 'caliper_r'], 'brakes'], ['The pads', ['pad'], 'brakes'],
      ['The carriers and their bolts', ['carrier_bolt', 'carrier'], 'brakes'], ['The brake discs', ['disc_f', 'disc_r'], 'brakes'], ['The splash shields', ['shield_f'], 'brakes'],
      ['The brake hoses and pipes', ['brake_hose', 'brake_line'], 'brakes'], ['The handbrake cables', ['hb_cable'], 'brakes'], ['The ABS unit', ['abs'], 'brakes'], ['The servo and master cylinder', ['servo'], 'brakes'],
      ['The driveshaft nuts and snap rings', ['axle_nut', 'cv_circlip'], 'susp'], ['The anti-roll bar link bolts and links', ['link_bolt', 'drop_link'], 'susp'],
      ['The track rod ends', ['tie_end'], 'susp'], ['The ball joints', ['ball_joint'], 'susp'], ['The driveshafts and their boots', ['cv_boot', 'driveshaft'], 'susp'],
      ['The struts: top mounts, boots, springs, dampers', ['top_mount', 'boot_f', 'spring_f', 'strut'], 'susp'], ['The hubs and knuckles', ['hub_f', 'knuckle'], 'susp'],
      ['The lower arms and their bushes', ['arm_bush_f', 'arm_bush_r', 'arm'], 'susp'], ['The anti-roll bar', ['arb_bush', 'arb'], 'susp'],
      ['The steering: track rods, boots, hoses, column, rack', ['tie_rod', 'rack_boot', 'ps_hose', 'ps_tank', 'column', 'rack'], 'susp'], ['The subframe', ['subframe'], 'susp'],
      ['The rear springs and shock absorbers', ['spring_r', 'shock_r'], 'susp'], ['The rear hubs and stub axles', ['hub_r', 'stub_axle'], 'susp'], ['The rear axle and its bushes', ['beam_bush', 'beam'], 'susp'],
      ['The heat shields', ['heat_shield'], 'exhaust'], ['The rear clamp and hangers', ['exh_clamp', 'hanger'], 'exhaust'], ['The rear silencer', ['rear_box'], 'exhaust'],
      ['The centre pipe and middle silencer', ['mid_box'], 'exhaust'], ['The front pipe and converter', ['front_pipe'], 'exhaust'], ['The flange nuts, the downpipe, the gaskets', ['exh_nut', 'downpipe', 'exh_gasket'], 'exhaust'],
      ['The filler cap and filler neck', ['fuel_cap', 'filler'], 'fuel'], ['The lock ring, sender and its seal', ['lock_ring', 'sender', 'tank_seal'], 'fuel'], ['The gravity valve', ['gravity_valve'], 'fuel'],
      ['The tank straps and spacers', ['tank_strap', 'strap_spacer'], 'fuel'], ['The tank', ['fuel_tank'], 'fuel'], ['The fuel filter and lines', ['filter_plate', 'fuel_filter', 'fuel_line'], 'fuel'],
      ['The head restraints', ['headrest'], 'interior'], ['The front seats on their runners', ['seat_rail', 'seat_f'], 'interior'], ['The rear seat cushion and backrests', ['rear_cushion', 'rear_back'], 'interior'],
      ['The belts and buckles', ['belt', 'buckle'], 'interior'], ['The parcel shelf, mirror and visors', ['parcel', 'mirror_i', 'visor'], 'interior'], ['The door panels', ['door_card'], 'interior'],
      ['The airbag and steering wheel', ['airbag', 'wheel_s'], 'interior'], ['The column shroud and stalks', ['shroud'], 'interior'], ['The gear lever and handbrake', ['gear_lever', 'handbrake'], 'interior'],
      ['The centre console', ['console'], 'interior'], ['The radio, heater controls and glovebox lid', ['radio', 'hvac_ctl', 'glovebox'], 'interior'], ['The instrument cluster', ['cluster'], 'interior'],
      ['The dashboard', ['dash'], 'interior'], ['The heater box', ['heater'], 'interior'], ['The pedals', ['pedal'], 'interior'], ['The carpet', ['carpet'], 'interior'],
      ['The battery: earth strap, positive cable, fuse box, battery, tray', ['earth', 'batt_cable', 'batt_fuse', 'battery', 'batt_tray'], 'wiring'],
      ['The wiper arms, blades and caps; the wiper motor', ['wiper_cap', 'wiper_blade', 'wiper_arm', 'wiper_motor'], 'wiring'], ['The lights', ['headlight', 'taillight', 'repeater', 'plate_lamp', 'brake_lamp', 'horn'], 'wiring'],
      ['The fuses, relays and their carriers', ['fuse', 'relay_acc', 'relay_start', 'relay_plate', 'fuse_box'], 'wiring'], ['The switches and the ignition lock', ['light_switch', 'clutch_switch', 'lock_cyl', 'ign_switch', 'col_lock'], 'wiring'],
      ['The engine control unit', ['ecu'], 'wiring'], ['The starter and its solenoid', ['starter_sol', 'starter'], 'wiring'], ['The harnesses and ABS leads', ['abs_lead', 'loom'], 'wiring'],
      ['The air box and hose', ['air_hose', 'air_box'], 'engine'], ['The expansion tank, radiator hoses, fans, radiator and condenser', ['exp_cap', 'exp_tank', 'rad_hose', 'fan', 'radiator', 'condenser'], 'engine'],
      ['The gear-change cables', ['gear_cable'], 'engine'], ['The mounts', ['mount'], 'engine'], ['The gearbox', ['gearbox'], 'engine'], ['The engine', ['engine'], 'engine'],
    ],
    words(c) {
      const base = { thing: 'car', bare: 'Stripped to the shell', all: 'The whole car', intro: 'Pick a part of the car above, then tap any part, or a part’s name below. It comes off and goes back on.',
        unlisted: 'Not in your catalogue’s list for this car: drawn so the car is whole.', about: 'About this car', elsewhere: 'In your catalogue for this car, but not drawn here', stage: 'The car' };
      if (!c) return base;
      const listed = c.catRows.length;
      return { ...base, title: `${CFG.make} ${CFG.model} ${C.generation}, part by part`,
        kicker: `From your parts catalogue: ${CFG.make} ${CFG.model} ${C.generation}, ${CFG.words}` + (CFG.asked_year && String(CFG.asked_year) !== String(CFG.year) ? ` (your catalogue lists it to ${CFG.year}; you asked for ${CFG.asked_year})` : ` (${CFG.year})`),
        lede: `The whole car round its ${C.engine_name}: body and glass, interior, suspension and steering, brakes and wheels, wiring and lights, exhaust and fuel tank. ${c.pieceCount} pieces of ${c.kinds} kinds, each its own part: pick a part of the car, tap a piece to take it off and put it back, or strip it down in workshop order. ${listed} of your catalogue’s parts for it are listed.`,
        facts: C.facts,
        honest: `Drawn to the car’s published measurements (length, width, height, wheelbase, tracks, tyre size) and its lines; the body and the parts are drawn by the machine to fit them, not scanned from this car. ${DS > 0 ? 'Right-hand drive, as in the UK.' : 'Left-hand drive.'} Your catalogue has no exhaust or interior parts for this car (it has none for any Volkswagen), so those carry no OEM numbers; the brakes, suspension bushes, driveshafts, wheels, fuel tank parts, relays, switches and wipers it lists carry theirs, and the engine carries the engine’s.` };
    },
  };
})();
