import * as THREE from 'three';
import { buildPiston, buildValveSpring, camLobeGeometry } from './engine-internals.js';

/* ═════════════════════════════════════════════════════════════════════
   Golf Mk8 eHybrid: the parts the GTI file and the Golf bay do not have.
   CONSTRUCTED training geometry. Published figures where they exist
   (EA211 1.4 TSI: bore 74.5 mm, stroke 80.0 mm, 1,395 cc, DOHC 16 valves,
   timing belt; e-motor 85 kW; 13 kWh battery; 40 L tank). Every shape,
   position and fastener size beyond that is an educated estimate.
   Not OEM CAD. No torque values or part numbers (those need erWin / ETKA).
   Frame: +X is the car's LEFT, +Y up, +Z the nose, ground at Y=0, metres.
   ═══════════════════════════════════════════════════════════════════ */

const V = (x, y, z) => new THREE.Vector3(x, y, z);

/* ───────── geometry helpers ───────── */
// a closed outline from [z, y] points, corners rounded by quadratic curves
function shapeZY(pts, round = 0.006) {
  const s = new THREE.Shape(), n = pts.length;
  for (let i = 0; i < n; i++) {
    const [ax, ay] = pts[(i + n - 1) % n], [bx, by] = pts[i], [cx, cy] = pts[(i + 1) % n];
    const d1 = Math.hypot(bx - ax, by - ay) || 1, d2 = Math.hypot(cx - bx, cy - by) || 1, r = Math.min(round, d1 / 2.2, d2 / 2.2);
    const p = [bx + (ax - bx) / d1 * r, by + (ay - by) / d1 * r], q = [bx + (cx - bx) / d2 * r, by + (cy - by) / d2 * r];
    if (i === 0) s.moveTo(...p); else s.lineTo(...p);
    s.quadraticCurveTo(bx, by, ...q);
  }
  s.closePath(); return s;
}
function roundRect(w, h, r, cx = 0, cy = 0) {
  const s = new THREE.Shape(), x = cx - w / 2, y = cy - h / 2; r = Math.min(r, w / 2, h / 2);
  s.moveTo(x + r, y); s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r); s.lineTo(x + w, y + h - r);
  s.quadraticCurveTo(x + w, y + h, x + w - r, y + h); s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r);
  s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y); return s;
}
const circlePath = (x, y, r, hole = true) => { const p = new THREE.Path(); p.absarc(x, y, r, 0, Math.PI * 2, hole); return p; };
// extrude a [z,y] profile along X, centred on X=0
function alongX(shape, len, bevel = 0.003, seg = 6) {
  const g = new THREE.ExtrudeGeometry(shape, { depth: Math.max(0.0005, len - bevel * 2), bevelEnabled: bevel > 0, bevelThickness: bevel, bevelSize: bevel, bevelSegments: 2, curveSegments: seg });
  g.translate(0, 0, -(len - bevel * 2) / 2); g.rotateY(-Math.PI / 2); return g;
}
// extrude an [x,z] plan downward from y=0 to y=-height
function downY(shape, height, bevel = 0.002, seg = 24) {
  const g = new THREE.ExtrudeGeometry(shape, { depth: Math.max(0.0005, height - bevel * 2), bevelEnabled: bevel > 0, bevelThickness: bevel, bevelSize: bevel, bevelSegments: 2, curveSegments: seg });
  g.rotateX(Math.PI / 2); g.translate(0, -bevel, 0); return g;
}
function rbox(w, h, d, r = 0.008) { const g = alongX(roundRect(d, h, r), w, Math.min(r, 0.004)); return g; }
// a flat ribbon following a closed path in the YZ plane at x, `width` wide along X
function ribbon(points, width, thick) {
  const n = points.length, pos = [], idx = [];
  const nrm = i => { const a = points[(i + n - 1) % n], b = points[(i + 1) % n]; const t = new THREE.Vector2(b.x - a.x, b.y - a.y).normalize(); return new THREE.Vector2(t.y, -t.x); };
  for (let i = 0; i < n; i++) {
    const p = points[i], o = nrm(i);
    for (const [dx, k] of [[-width / 2, 0], [width / 2, 0], [width / 2, thick], [-width / 2, thick]]) pos.push(dx, p.y + o.y * k, p.x + o.x * k);
  }
  for (let i = 0; i < n; i++) { const a = i * 4, b = ((i + 1) % n) * 4; for (let f = 0; f < 4; f++) { const f2 = (f + 1) % 4; idx.push(a + f, b + f, a + f2, a + f2, b + f, b + f2); } }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setIndex(idx); g.computeVertexNormals(); return g;
}
// convex hull of 2D points (Andrew's monotone chain), counter-clockwise
function hull(pts) {
  const p = [...pts].sort((a, b) => a.x - b.x || a.y - b.y), cr = (o, a, b) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
  const lo = [], up = [];
  for (const q of p) { while (lo.length >= 2 && cr(lo[lo.length - 2], lo[lo.length - 1], q) <= 0) lo.pop(); lo.push(q); }
  for (const q of p.reverse()) { while (up.length >= 2 && cr(up[up.length - 2], up[up.length - 1], q) <= 0) up.pop(); up.push(q); }
  up.pop(); lo.pop(); return lo.concat(up);
}
// resample a closed polyline to evenly spaced points
function resample(pts, step) {
  const out = [], n = pts.length; let carry = 0;
  for (let i = 0; i < n; i++) { const a = pts[i], b = pts[(i + 1) % n], L = a.distanceTo(b); let t = carry; while (t < L) { out.push(a.clone().lerp(b, t / L)); t += step; } carry = t - L; }
  return out;
}

export function makeMaterials(materialFactory) {
  return {
    castAlu: materialFactory(0x9ea5ab, { metalness: .55, roughness: .62 }, 'cast'),
    darkCast: materialFactory(0x5d6267, { metalness: .5, roughness: .68 }, 'cast'),
    machined: materialFactory(0xc6ccd1, { metalness: .92, roughness: .28 }, 'brushed'),
    bore: materialFactory(0x8b9196, { metalness: .9, roughness: .22 }, 'brushed'),
    forged: materialFactory(0x55595e, { metalness: .85, roughness: .42 }, 'brushed'),
    steel: materialFactory(0x6d7379, { metalness: .85, roughness: .38 }, 'brushed'),
    blackPlastic: materialFactory(0x16191c, { metalness: .02, roughness: .78 }, 'plastic'),
    greyPlastic: materialFactory(0x3a3f44, { metalness: .03, roughness: .74 }, 'plastic'),
    rubber: materialFactory(0x101214, { metalness: 0, roughness: .93 }, 'rubber'),
    belt: materialFactory(0x1b1d20, { metalness: 0, roughness: .86 }, 'rubber'),
    zinc: materialFactory(0xb8bec4, { metalness: .9, roughness: .32 }, 'brushed'),
    blackBolt: materialFactory(0x2a2c2f, { metalness: .7, roughness: .45 }, 'brushed'),
    gasket: materialFactory(0x4e5257, { metalness: .75, roughness: .45 }, 'brushed'),
    sealant: materialFactory(0x2b2d30, { metalness: 0, roughness: .7 }, 'rubber'),
    ptfe: materialFactory(0x5a4a3c, { metalness: 0, roughness: .6 }, 'rubber'),
    ceramic: materialFactory(0xeceae4, { metalness: 0, roughness: .35 }, 'plastic'),
    copper: materialFactory(0xb87333, { metalness: .9, roughness: .32 }, 'brushed'),
    hv: materialFactory(0xff6a00, { metalness: .02, roughness: .6 }, 'plastic'),
    ecoat: materialFactory(0x1f2225, { metalness: .35, roughness: .6 }, 'cast'),
    exhaust: materialFactory(0x8f877d, { metalness: .8, roughness: .5 }, 'cast'),
    catcan: materialFactory(0xa9adb1, { metalness: .85, roughness: .38 }, 'brushed'),
    tank: materialFactory(0x202326, { metalness: .02, roughness: .88 }, 'plastic'),
    dark: materialFactory(0x0b0c0e, { metalness: 0, roughness: .95 }, 'plastic'),
  };
}

/* fasteners: a flanged hex bolt pointing along `dir` */
function makeBolts(M) {
  const cache = {};
  const geo = (dia, len) => {
    const k = dia + ':' + len; if (cache[k]) return cache[k];
    const head = new THREE.CylinderGeometry(dia * .82, dia * .82, dia * .62, 6); head.translate(0, dia * .31 + dia * .12, 0);
    const flange = new THREE.CylinderGeometry(dia * 1.05, dia * 1.05, dia * .12, 20); flange.translate(0, dia * .06, 0);
    const shank = new THREE.CylinderGeometry(dia / 2, dia / 2, len, 12); shank.translate(0, -len / 2, 0);
    return (cache[k] = [head, flange, shank]);
  };
  const R = { y: [0, 0, 0], '-y': [Math.PI, 0, 0], x: [0, 0, -Math.PI / 2], '-x': [0, 0, Math.PI / 2], z: [Math.PI / 2, 0, 0], '-z': [-Math.PI / 2, 0, 0] };
  return (g, p, dia, len, dir = 'y', mat = M.zinc) => {
    const b = new THREE.Group();
    for (const gg of geo(dia, len)) { const m = new THREE.Mesh(gg, mat); m.castShadow = true; b.add(m); }
    b.rotation.set(...(Array.isArray(dir) ? dir : R[dir])); b.position.set(...p); g.add(b); return b;
  };
}

export function buildHybrid(materialFactory) {
  const M = makeMaterials(materialFactory), bolt = makeBolts(M);
  const parts = [];
  const mesh = (geo, mat, p = [0, 0, 0], r = [0, 0, 0]) => { const o = new THREE.Mesh(geo, mat); o.position.set(...p); o.rotation.set(...r); o.castShadow = o.receiveShadow = true; return o; };
  const cylX = (r, l, mat, p, seg = 40, r2 = r) => mesh(new THREE.CylinderGeometry(r, r2, l, seg), mat, p, [0, 0, Math.PI / 2]);
  const cylY = (r, l, mat, p, seg = 28, r2 = r) => mesh(new THREE.CylinderGeometry(r, r2, l, seg), mat, p);
  const cylZ = (r, l, mat, p, seg = 28, r2 = r) => mesh(new THREE.CylinderGeometry(r, r2, l, seg), mat, p, [Math.PI / 2, 0, 0]);
  const torusX = (R, t, mat, p, seg = 56) => mesh(new THREE.TorusGeometry(R, t, 10, seg), mat, p, [0, Math.PI / 2, 0]);
  const tube = (pts, r, mat, seg = 120) => mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts.map(p => V(...p))), seg, r, 12, false), mat);
  // corrugated HV conduit: a tube with ribs every 12 mm
  const conduit = (pts, r) => {
    const g = new THREE.Group(), c = new THREE.CatmullRomCurve3(pts.map(p => V(...p)));
    g.add(new THREE.Mesh(new THREE.TubeGeometry(c, 160, r * 0.9, 12, false), M.hv));
    const L = c.getLength(), ring = new THREE.TorusGeometry(r, r * 0.16, 6, 16);
    for (let s = 0.006; s < L; s += 0.012) { const t = s / L, m = new THREE.Mesh(ring, M.hv); m.position.copy(c.getPointAt(t)); m.lookAt(m.position.clone().add(c.getTangentAt(t))); g.add(m); }
    g.traverse(o => { if (o.isMesh) o.castShadow = true; }); return g;
  };
  const part = (id, name, sys, obj, o = {}) => { obj.name = id; parts.push({ id, name, sys, obj, ex: V(...(o.ex || [0, 0, 0])), stripEx: o.stripEx ? V(...o.stripEx) : null, tags: o.tags || [], qty: o.qty || 1, mat: o.mat || '', size: o.size || '', conf: o.conf || 'est', note: o.note || '', hidden: !!o.hidden }); return obj; };
  const grp = (...kids) => { const g = new THREE.Group(); for (const k of kids) g.add(k); return g; };

  /* ───────── hybrid module: e-motor and K0 clutch between engine and DSG ───────── */
  const EM = V(-0.312, 0.456, 1.495);
  {
    const g = new THREE.Group(); g.position.copy(EM);
    // turned housing profile (radius, x) revolved about X
    const prof = [[0.120, -0.058], [0.168, -0.058], [0.172, -0.052], [0.172, -0.040], [0.178, -0.036], [0.178, 0.036], [0.172, 0.040], [0.172, 0.052], [0.168, 0.058], [0.120, 0.058]].map(([r, x]) => new THREE.Vector2(r, x));
    const lathe = new THREE.LatheGeometry(prof, 72); lathe.rotateZ(-Math.PI / 2);
    g.add(mesh(lathe, M.castAlu));
    g.add(cylX(0.121, 0.112, M.darkCast, [0, 0, 0], 48));
    for (let i = 0; i < 14; i++) { const a = i / 14 * Math.PI * 2; const b = mesh(new THREE.BoxGeometry(0.06, 0.012, 0.016), M.castAlu, [0, Math.sin(a) * 0.183, Math.cos(a) * 0.183]); b.rotation.x = -a; g.add(b); }
    for (let i = 0; i < 12; i++) { const a = i / 12 * Math.PI * 2 + 0.13; g.add(cylX(0.011, 0.02, M.castAlu, [0.05, Math.sin(a) * 0.18, Math.cos(a) * 0.18], 16)); g.add(cylX(0.011, 0.02, M.castAlu, [-0.05, Math.sin(a) * 0.18, Math.cos(a) * 0.18], 16)); }
    // three-phase connector housing with cable glands
    const hous = mesh(rbox(0.09, 0.05, 0.075, 0.008), M.castAlu, [0, 0.198, -0.03]); g.add(hous);
    for (const dx of [-0.026, 0, 0.026]) { g.add(cylY(0.011, 0.018, M.hv, [dx, 0.232, -0.03], 20)); g.add(cylY(0.007, 0.012, M.blackPlastic, [dx, 0.245, -0.03], 16)); }
    // coolant ports
    g.add(cylZ(0.009, 0.04, M.castAlu, [-0.03, 0.12, 0.17], 16), cylZ(0.009, 0.04, M.castAlu, [0.03, 0.12, 0.17], 16));
    part('emotor', 'E-motor and K0 disconnect clutch (DQ400e hybrid module)', 'hybrid', g,
      { ex: [-0.35, 0.05, -0.15], tags: ['pt', 'hv', 'gearbox'], mat: 'Die-cast aluminium housing, copper stator, liquid-cooled', size: 'Ø ≈ 360 mm, ≈ 115 mm deep (est.)', conf: 'pub',
        note: 'Permanent-magnet synchronous motor, 85 kW (published). The K0 clutch inside couples the petrol engine to the e-motor, or lets the car drive on electricity alone. The motor also starts the engine: there is no separate starter. Housing shape estimated.' });
    const s = new THREE.Group(); s.position.copy(EM);
    s.add(torusX(0.170, 0.0025, M.rubber, [0.059, 0, 0], 96)); s.add(torusX(0.170, 0.0025, M.rubber, [-0.059, 0, 0], 96));
    part('seal_emotor', 'E-motor housing O-rings, engine and gearbox side', 'hybrid', s, { ex: [-0.48, 0.05, -0.15], tags: ['pt', 'gearbox', 'seal'], qty: 2, mat: 'FKM rubber (est.)', note: 'Replace whenever the module is split from the engine or the gearbox.' });
    const b = new THREE.Group(); b.position.copy(EM);
    for (let i = 0; i < 12; i++) { const a = i / 12 * Math.PI * 2 + 0.13; bolt(b, [-0.062, Math.sin(a) * 0.18, Math.cos(a) * 0.18], 0.010, 0.05, 'x'); }
    part('bolts_emotor', 'Hybrid module to gearbox bolts', 'hybrid', b, { ex: [-0.62, 0.05, -0.15], tags: ['pt', 'gearbox', 'fastener'], qty: 12, size: 'M10 est.', mat: 'Zinc-flake coated steel', note: 'Torque: erWin. The engine side uses the twelve bellhousing flange bolts.' });
  }
  /* ───────── power electronics ───────── */
  {
    const g = new THREE.Group(); g.position.set(-0.42, 0.765, 1.63);
    g.add(mesh(rbox(0.22, 0.055, 0.25, 0.014), M.castAlu, [0, -0.008, 0]));
    g.add(mesh(rbox(0.205, 0.016, 0.235, 0.01), M.darkCast, [0, 0.027, 0]));
    for (let i = 0; i < 11; i++) g.add(mesh(new THREE.BoxGeometry(0.004, 0.012, 0.2), M.darkCast, [-0.09 + i * 0.018, 0.04, 0]));
    const hvp = mesh(rbox(0.07, 0.035, 0.045, 0.006), M.hv, [-0.06, 0.0, -0.135]); g.add(hvp);
    g.add(mesh(rbox(0.05, 0.03, 0.04, 0.006), M.hv, [0.035, 0.0, -0.133]));
    g.add(mesh(rbox(0.04, 0.026, 0.035, 0.005), M.blackPlastic, [0.085, 0.0, -0.13]));
    g.add(cylX(0.008, 0.05, M.castAlu, [0.13, -0.015, 0.06], 16), cylX(0.008, 0.05, M.castAlu, [0.13, -0.015, 0.1], 16));
    part('inverter', 'Power electronics (inverter and DC/DC converter)', 'hybrid', g,
      { ex: [-0.25, 0.55, 0.15], tags: ['pt', 'hv', 'gearbox'], mat: 'Die-cast aluminium, liquid-cooled', size: '≈ 220 × 70 × 250 mm (est.)', note: 'Turns the battery’s direct current into three-phase AC for the e-motor, and feeds the 12 V system through its DC/DC converter. Position estimated.' });
    const b = new THREE.Group(); b.position.set(-0.42, 0.80, 1.63);
    for (const [x, z] of [[0.1, 0.115], [-0.1, 0.115], [0.1, -0.115], [-0.1, -0.115], [0.1, 0], [-0.1, 0], [0, 0.115], [0, -0.115]]) bolt(b, [x, 0, z], 0.006, 0.02, 'y');
    part('bolts_inverter', 'Inverter lid and mounting bolts', 'hybrid', b, { ex: [-0.25, 0.72, 0.15], tags: ['pt', 'gearbox', 'fastener'], qty: 8, size: 'M6 est.' });
    const s = new THREE.Group(); s.position.set(-0.42, 0.765, 1.63);
    const sh = roundRect(0.214, 0.244, 0.012); sh.holes.push(roundRect(0.204, 0.234, 0.008));
    s.add(mesh(downY(sh, 0.002, 0), M.rubber, [0, 0.0195, 0]));
    part('seal_inverter', 'Inverter lid seal and coolant O-rings', 'hybrid', s, { ex: [-0.25, 0.42, 0.15], tags: ['pt', 'gearbox', 'seal'], note: 'The lid seal keeps water out of the electronics. Coolant connections use O-rings: replace on refit (est.).' });
  }
  part('hv_cable_motor', 'HV cable, inverter to e-motor', 'hybrid',
    conduit([[-0.47, 0.745, 1.505], [-0.44, 0.72, 1.49], [-0.37, 0.69, 1.47], [-0.312, 0.69, 1.465]], 0.011),
    { ex: [-0.3, 0.35, 0], tags: ['pt', 'hv', 'gearbox'], note: 'Three-phase cable in corrugated conduit. Orange always means high voltage.' });
  part('hv_cable_battery', 'HV cable, battery to inverter', 'hybrid',
    conduit([[-0.37, 0.745, 1.505], [-0.42, 0.58, 1.20], [-0.33, 0.30, 0.98], [-0.14, 0.17, 0.55], [-0.13, 0.165, -0.10], [-0.12, 0.25, -0.36]], 0.013),
    { ex: [0, -0.25, 0], tags: ['hv', 'hvcable'], size: 'twin core, ≈ 26 mm conduit (est.)', note: 'Runs down the bulkhead and back along the transmission tunnel to the battery (routing estimated).' });
  {
    const g = new THREE.Group();
    g.add(cylX(0.036, 0.022, M.blackPlastic, [-0.80, 0.80, 1.58], 32));
    g.add(cylX(0.029, 0.008, M.greyPlastic, [-0.813, 0.80, 1.58], 32));
    for (let i = 0; i < 7; i++) { const a = i / 7 * Math.PI * 2; g.add(cylX(0.004, 0.012, M.dark, [-0.818, 0.80 + Math.sin(a) * (i ? 0.014 : 0), 1.58 + Math.cos(a) * (i ? 0.014 : 0)], 10)); }
    g.add(conduit([[-0.79, 0.79, 1.58], [-0.70, 0.76, 1.66], [-0.55, 0.77, 1.68], [-0.53, 0.775, 1.66]], 0.009));
    part('charge_socket', 'Charging socket (Type 2) and lead to the on-board charger', 'hybrid', g,
      { ex: [-0.4, 0.2, 0.2], tags: ['hv'], mat: 'Type 2 AC socket', note: 'The Golf 8 eHybrid charges on AC through a Type 2 socket in the front wing (position estimated).' });
  }
  /* ───────── high-voltage battery ───────── */
  {
    const g = new THREE.Group(); g.position.set(0, 0.265, -0.68);
    const plan = shapeZY([[-0.28, -0.55], [0.28, -0.55], [0.28, 0.55], [-0.28, 0.55]].map(([z, x]) => [x, z]), 0.03);
    const tray = mesh(downY(plan, 0.15, 0.006), M.ecoat, [0, 0.03, 0]); g.add(tray);
    const flangeS = roundRect(1.14, 0.60, 0.035); flangeS.holes.push(roundRect(1.10, 0.56, 0.03));
    g.add(mesh(downY(flangeS, 0.008, 0), M.ecoat, [0, 0.034, 0]));
    const lid = mesh(downY(roundRect(1.10, 0.56, 0.03), 0.07, 0.01), M.ecoat, [0, 0.10, 0]); g.add(lid);
    for (let i = 0; i < 9; i++) g.add(mesh(new THREE.BoxGeometry(0.012, 0.012, 0.50), M.ecoat, [-0.48 + i * 0.12, 0.104, 0]));
    g.add(mesh(rbox(0.11, 0.05, 0.07, 0.008), M.hv, [-0.12, 0.11, 0.30]));
    g.add(mesh(rbox(0.06, 0.04, 0.05, 0.006), M.hv, [0.12, 0.11, 0.30]));
    g.add(cylZ(0.009, 0.06, M.castAlu, [0.30, 0.0, 0.30], 16), cylZ(0.009, 0.06, M.castAlu, [0.35, 0.0, 0.30], 16));
    const lbl = mesh(new THREE.PlaneGeometry(0.16, 0.08), materialFactory(0xf2d21a, { roughness: .5 }, 'plastic'), [0.3, 0.1045, -0.1], [-Math.PI / 2, 0, 0]); g.add(lbl);
    part('hv_battery', 'High-voltage battery, 13 kWh', 'hybrid', g,
      { ex: [0, -0.65, 0], tags: ['hv', 'battery'], mat: 'E-coated steel housing, lithium-ion cells', size: '≈ 1,140 × 220 × 600 mm (est.)', conf: 'pub',
        note: '13 kWh gross (published), under the rear seat, liquid-cooled. Removal needs a battery lift table and an HV-qualified technician.' });
    const b = new THREE.Group(); b.position.set(0, 0.30, -0.68);
    for (const x of [-0.555, -0.28, 0, 0.28, 0.555]) for (const z of [-0.285, 0.285]) bolt(b, [x, 0, z], 0.010, 0.04, 'y', M.blackBolt);
    part('bolts_battery', 'HV battery mounting bolts', 'hybrid', b, { ex: [0, -0.85, 0], tags: ['battery', 'fastener'], qty: 10, size: 'M10 est.' });
    const s = new THREE.Group(); s.position.set(0, 0.367, -0.68);
    const ss = roundRect(1.09, 0.55, 0.03); ss.holes.push(roundRect(1.07, 0.53, 0.025)); s.add(mesh(downY(ss, 0.003, 0), M.rubber, [0, 0, 0]));
    part('seal_battery', 'HV battery lid seal', 'hybrid', s, { ex: [0, -0.35, 0], tags: ['battery', 'seal'], note: 'Keeps water out of the pack. Opened only in a specialist battery workshop.' });
  }
  /* ───────── fuel ───────── */
  {
    const g = new THREE.Group(); g.position.set(0, 0.49, -1.18);
    const prof = shapeZY([[-0.18, -0.10], [0.18, -0.10], [0.19, 0.06], [0.12, 0.10], [-0.12, 0.10], [-0.19, 0.04]], 0.05);
    g.add(mesh(alongX(prof, 0.86, 0.03, 10), M.tank));
    g.add(cylY(0.055, 0.02, M.blackPlastic, [0.22, 0.105, 0], 32));
    for (const x of [-0.25, 0.25]) g.add(mesh(new THREE.BoxGeometry(0.025, 0.004, 0.42), M.steel, [x, -0.102, 0]));
    g.add(tube([[0.42, 0.06, 0.05], [0.60, 0.20, 0.05], [0.72, 0.52, 0.05]], 0.017, M.blackPlastic));
    part('fuel_tank', 'Fuel tank, 40 litres, with sender and filler neck', 'fuel', g,
      { ex: [0, 0.55, 0], conf: 'pub', mat: 'Multi-layer HDPE (est.)', note: '40 litres on the eHybrid (published): smaller than the GTI’s, because the HV battery takes the space under the rear seat. Pressurised tank on plug-in hybrids (est.). Shape estimated.' });
    const b = new THREE.Group(); b.position.set(0, 0.388, -1.18);
    for (const x of [-0.25, 0.25]) for (const z of [-0.2, 0.2]) bolt(b, [x, 0, z], 0.008, 0.03, '-y', M.blackBolt);
    part('bolts_tank', 'Fuel tank strap bolts', 'fuel', b, { ex: [0, 0.35, 0], tags: ['fastener'], qty: 4, size: 'M8 est.' });
  }
  /* ───────── exhaust ───────── */
  {
    const g = new THREE.Group();
    g.add(tube([[0.05, 0.46, 1.77], [0.07, 0.30, 1.81], [0.065, 0.20, 1.72], [0.06, 0.18, 1.55]], 0.028, M.exhaust));
    const can = mesh(alongX(shapeZY([[-0.13, -0.045], [0.13, -0.045], [0.13, 0.045], [-0.13, 0.045]], 0.04), 0.13, 0.01, 16), M.catcan, [0.06, 0.18, 1.40]); can.rotation.y = Math.PI / 2; g.add(can);
    g.add(tube([[0.06, 0.18, 1.25], [0.05, 0.165, 1.10], [0.05, 0.16, 0.80]], 0.026, M.exhaust));
    for (let i = 0; i < 10; i++) g.add(mesh(new THREE.TorusGeometry(0.029, 0.003, 8, 32), M.catcan, [0.05, 0.163, 1.04 - i * 0.012]));
    part('exhaust_front', 'Downpipe, catalytic converter and particulate filter', 'fuel', g,
      { ex: [0, -0.35, 0.2], tags: ['exhaust', 'pt'], mat: 'Stainless steel', note: 'Close-coupled catalytic converter and petrol particulate filter, then a flexible joint (layout estimated for this bay).' });
  }
  {
    const g = new THREE.Group();
    g.add(tube([[0.05, 0.16, 0.80], [0.10, 0.165, 0.10], [0.24, 0.18, -0.80], [0.38, 0.27, -1.55], [0.42, 0.28, -1.72]], 0.026, M.exhaust));
    const sil = mesh(alongX(shapeZY([[-0.16, -0.075], [0.16, -0.075], [0.16, 0.075], [-0.16, 0.075]], 0.07), 0.40, 0.012, 16), M.catcan, [0.40, 0.27, -1.85]); g.add(sil);
    g.add(cylZ(0.04, 0.10, M.catcan, [0.52, 0.255, -2.03], 32), cylZ(0.034, 0.102, M.dark, [0.52, 0.255, -2.03], 32));
    for (const [x, y, z] of [[0.24, 0.20, -0.8], [0.25, 0.30, -1.85], [0.55, 0.30, -1.85]]) g.add(cylY(0.012, 0.05, M.rubber, [x, y + 0.03, z], 16));
    part('exhaust_rear', 'Centre pipe, rear silencer and tailpipe', 'fuel', g, { ex: [0, -0.45, -0.1], tags: ['exhaust'], mat: 'Stainless steel, rubber hangers' });
  }
  {
    const g = new THREE.Group(); g.position.set(0.05, 0.16, 0.80); g.add(mesh(new THREE.TorusGeometry(0.027, 0.004, 8, 32), M.gasket));
    part('seal_exhaust', 'Exhaust clamp sealing ring', 'fuel', g, { ex: [0, -0.4, 0], tags: ['exhaust', 'seal'], note: 'Replace the clamp and ring whenever the joint is split.' });
  }
  return { parts, M };
}

/* ═════════ EA211 1.4 TSI, in pieces for the strip-down ═════════
   Sits where the Golf bay draws its one-piece long block and replaces it
   on the stand. Cylinders along X (transverse), crank on Y = CRANK. */
export function buildEngineStrip(materialFactory, M) {
  const bolt = makeBolts(M), parts = [];
  const BORE = 0.0745, STROKE = 0.080, PITCH = 0.082;            // bore, stroke published; bore pitch est.
  const XC = -0.02, ZC = 1.545, CRANK = 0.37, DECK = 0.60, ROD = 0.140;
  const CX = [-1.5, -0.5, 0.5, 1.5].map(k => XC + k * PITCH);
  const UP = [1, -1, -1, 1];                                       // crank throws: 1 and 4 up, 2 and 3 down
  const CAMZ = [ZC - 0.052, ZC + 0.052], CAMY = DECK + 0.142;
  const mesh = (geo, mat, p = [0, 0, 0], r = [0, 0, 0]) => { const o = new THREE.Mesh(geo, mat); o.position.set(...p); o.rotation.set(...r); o.castShadow = o.receiveShadow = true; return o; };
  const cylX = (r, l, mat, p, seg = 40, r2 = r) => mesh(new THREE.CylinderGeometry(r, r2, l, seg), mat, p, [0, 0, Math.PI / 2]);
  const cylY = (r, l, mat, p, seg = 28, r2 = r) => mesh(new THREE.CylinderGeometry(r, r2, l, seg), mat, p);
  const torusX = (R, t, mat, p) => mesh(new THREE.TorusGeometry(R, t, 10, 56), mat, p, [0, Math.PI / 2, 0]);
  const part = (id, name, obj, stripEx, o = {}) => { obj.name = id; parts.push({ id, name, sys: 'strip', obj, ex: V(...stripEx), stripEx: V(...stripEx), tags: ['pt', 'engine', 'strip', ...(o.tags || [])], qty: o.qty || 1, mat: o.mat || '', size: o.size || '', conf: o.conf || 'est', note: o.note || '', hidden: true }); };

  /* cylinder block: crankcase extruded along the bank, cylinder section with real bores */
  {
    const g = new THREE.Group();
    const cc = shapeZY([[-0.105, 0.50], [0.105, 0.50], [0.112, 0.44], [0.128, CRANK + 0.01], [0.128, CRANK - 0.035], [-0.128, CRANK - 0.035], [-0.128, CRANK + 0.01], [-0.112, 0.44]], 0.012);
    const crankcase = mesh(alongX(cc, 0.39, 0.004), M.castAlu, [XC, 0, ZC]); g.add(crankcase);
    const deck = roundRect(0.39, 0.212, 0.016, XC, ZC);
    CX.forEach(x => deck.holes.push(circlePath(x, ZC, BORE / 2)));
    for (let i = 0; i < 5; i++) for (const dz of [-0.088, 0.088]) deck.holes.push(circlePath(XC - 2 * PITCH + i * PITCH, ZC + dz, 0.0056));
    g.add(mesh(downY(deck, 0.105, 0.003), M.castAlu, [0, DECK, 0]));
    CX.forEach(x => { const liner = mesh(new THREE.CylinderGeometry(BORE / 2, BORE / 2, 0.14, 48, 1, true), M.bore, [x, DECK - 0.07, ZC]); liner.material = M.bore.clone(); liner.material.side = THREE.BackSide; g.add(liner); });
    for (let i = 0; i < 3; i++) for (const s of [-1, 1]) g.add(mesh(new THREE.BoxGeometry(0.012, 0.15, 0.012), M.castAlu, [XC - PITCH + i * PITCH, 0.47, ZC + s * 0.114]));
    g.add(mesh(rbox(0.11, 0.09, 0.05, 0.01), M.castAlu, [XC + 0.09, 0.46, ZC + 0.13]));               // oil filter / cooler module boss
    g.add(cylX(0.02, 0.02, M.castAlu, [XC - 0.2, 0.45, ZC - 0.07], 20), cylX(0.02, 0.02, M.castAlu, [XC + 0.2, 0.47, ZC + 0.06], 20));
    part('blk', 'Cylinder block', g, [0, 0, 0], { mat: 'Die-cast aluminium, thin cast-iron liners', size: 'Bore 74.5 mm, stroke 80.0 mm, 1,395 cc', conf: 'pub', note: 'Bore, stroke and capacity are published EA211 figures. Ten head-bolt holes, four bores; external ribs and bosses are estimates.' });
  }
  /* crankshaft: five mains, four pins, eight shaped webs with counterweights */
  {
    const g = new THREE.Group();
    const web = new THREE.Shape(); web.absarc(0, 0, 0.044, Math.PI * 0.12, Math.PI * 0.88, true); web.lineTo(-0.018, STROKE / 2); web.absarc(0, STROKE / 2, 0.026, Math.PI, 0, true); web.closePath();
    const webGeo = alongX(web, 0.014, 0.002, 12);
    for (let i = 0; i < 5; i++) g.add(cylX(0.024, 0.021, M.machined, [XC - 2 * PITCH + i * PITCH, CRANK, ZC], 32));
    CX.forEach((x, i) => {
      for (const dx of [-0.0185, 0.0185]) { const w = mesh(webGeo, M.forged, [x + dx, CRANK, ZC]); w.rotation.x = UP[i] > 0 ? 0 : Math.PI; g.add(w); }
      g.add(cylX(0.0215, 0.023, M.machined, [x, CRANK + UP[i] * STROKE / 2, ZC], 32));
      g.add(mesh(new THREE.CircleGeometry(0.003, 10), M.dark, [x, CRANK + UP[i] * (STROKE / 2 + 0.0216), ZC], [-UP[i] * Math.PI / 2, 0, 0]));
    });
    g.add(cylX(0.019, 0.05, M.machined, [XC + 0.21, CRANK, ZC], 28));                                 // nose
    g.add(cylX(0.046, 0.012, M.forged, [XC - 0.205, CRANK, ZC], 48));                                  // flywheel flange
    for (let i = 0; i < 8; i++) { const a = i / 8 * Math.PI * 2; g.add(cylX(0.004, 0.013, M.dark, [XC - 0.205, CRANK + Math.sin(a) * 0.03, ZC + Math.cos(a) * 0.03], 10)); }
    part('crankshaft', 'Crankshaft', g, [0, -0.20, 0.25], { mat: 'Forged steel, induction-hardened journals (est.)', size: 'Stroke 80.0 mm (published)', note: 'Five main bearings and eight counterweighted webs (est.). Throws for cylinders 1 and 4 point up, 2 and 3 down: the firing order is 1-3-4-2.' });
  }
  /* main bearing ladder and its bolts */
  {
    const g = new THREE.Group();
    const lad = roundRect(0.39, 0.22, 0.012, XC, ZC);
    for (let i = 0; i < 4; i++) lad.holes.push(roundRect(0.058, 0.17, 0.012, CX[i], ZC));
    g.add(mesh(downY(lad, 0.022, 0.002), M.castAlu, [0, CRANK - 0.036, 0]));
    for (let i = 0; i < 5; i++) g.add(mesh(new THREE.CylinderGeometry(0.026, 0.026, 0.024, 32, 1, false, 0, Math.PI), M.castAlu, [XC - 2 * PITCH + i * PITCH, CRANK - 0.002, ZC], [0, 0, Math.PI / 2]));
    part('ladder', 'Main bearing ladder frame', g, [0, -0.28, 0.25], { mat: 'Aluminium (est.)', note: 'Holds the lower main bearing shells. Shells are renewed whenever the crank comes out.' });
    const b = new THREE.Group();
    for (let i = 0; i < 5; i++) for (const dz of [-0.072, 0.072]) bolt(b, [XC - 2 * PITCH + i * PITCH, CRANK - 0.06, ZC + dz], 0.009, 0.075, '-y', M.blackBolt);
    part('bolts_main', 'Main bearing bolts', b, [0, -0.36, 0.25], { tags: ['fastener'], qty: 10, size: 'M9 stretch bolts (est.)', mat: 'Black-oxide steel', note: 'Torque-to-yield: replace. Torque and angle: erWin.' });
  }
  /* pistons (the workshop's turned piston, scaled to 74.5 mm) and H-section rods */
  {
    const g = new THREE.Group();
    const rodS = new THREE.Shape(); rodS.absarc(0, 0, 0.031, Math.PI * 0.61, Math.PI * 0.39, false); rodS.lineTo(0.009, ROD - 0.014); rodS.absarc(0, ROD, 0.0135, -Math.PI / 3, Math.PI * 4 / 3, false); rodS.lineTo(-0.009, 0.034); rodS.closePath();
    rodS.holes.push(circlePath(0, 0, 0.0218), circlePath(0, ROD, 0.0098));
    const rodGeo = alongX(rodS, 0.020, 0.002, 24);
    const web = new THREE.Shape(); web.moveTo(-0.0055, 0.032); web.lineTo(0.0055, 0.032); web.lineTo(0.0055, ROD - 0.02); web.lineTo(-0.0055, ROD - 0.02); web.closePath();
    const recess = alongX(web, 0.022, 0, 2);
    CX.forEach((x, i) => {
      const pinY = CRANK + UP[i] * STROKE / 2 + ROD;
      const p = buildPiston(0.18, materialFactory); p.scale.setScalar(BORE / 0.36); p.position.set(x, pinY + 0.053 * BORE / 0.36, ZC); p.traverse(o => { if (o.isMesh) o.castShadow = true; }); g.add(p);
      const rod = mesh(rodGeo, M.forged, [x, CRANK + UP[i] * STROKE / 2, ZC]); g.add(rod);
      const rec = mesh(recess, M.darkCast, [x, CRANK + UP[i] * STROKE / 2, ZC]); rec.scale.set(1.0, 1, 0.5); g.add(rec);
      for (const dz of [-0.022, 0.022]) bolt(g, [x, CRANK + UP[i] * STROKE / 2 - 0.03, ZC + dz], 0.007, 0.05, 'y', M.blackBolt);
    });
    part('pistons', 'Pistons, rings, pins and connecting rods', g, [0, 0.22, -0.42], { qty: 4, mat: 'Cast aluminium pistons, forged steel rods', size: 'Ø 74.5 mm (published); rod ≈ 140 mm centres (est.)', note: 'Three rings each: two compression, one oil control. Rod cap bolts are stretch bolts: replace.' });
  }
  /* crankshaft oil seals */
  {
    const a = new THREE.Group(); a.add(torusX(0.026, 0.006, M.ptfe, [XC + 0.214, CRANK, ZC]), torusX(0.032, 0.003, M.steel, [XC + 0.214, CRANK, ZC]));
    part('seal_crank_belt', 'Crankshaft oil seal, timing-belt end', a, [0.40, -0.20, 0.25], { tags: ['seal'], mat: 'PTFE lip in a steel carrier (est.)', note: 'Replace whenever the crank sprocket comes off.' });
    const b = new THREE.Group(); b.add(torusX(0.044, 0.006, M.ptfe, [XC - 0.216, CRANK, ZC]), torusX(0.052, 0.003, M.steel, [XC - 0.216, CRANK, ZC]));
    part('seal_crank_fly', 'Crankshaft oil seal, flywheel end', b, [-0.40, -0.20, 0.25], { tags: ['seal'], mat: 'PTFE lip in a steel carrier (est.)' });
  }
  /* sump, sealant, bolts, oil pump */
  {
    const g = new THREE.Group();
    const upper = shapeZY([[-0.11, -0.04], [0.11, -0.04], [0.106, 0.0], [-0.106, 0.0]], 0.006);
    g.add(mesh(alongX(upper, 0.39, 0.003), M.castAlu, [XC, CRANK - 0.034, ZC]));
    const pan = shapeZY([[-0.104, 0], [0.104, 0], [0.09, -0.07], [-0.09, -0.07]], 0.02);
    g.add(mesh(alongX(pan, 0.27, 0.004, 12), M.steel, [XC - 0.05, CRANK - 0.074, ZC]));
    g.add(cylY(0.011, 0.01, M.zinc, [XC - 0.12, CRANK - 0.148, ZC + 0.03], 6));
    for (let i = 0; i < 6; i++) g.add(mesh(new THREE.BoxGeometry(0.008, 0.036, 0.004), M.castAlu, [XC - 0.16 + i * 0.064, CRANK - 0.055, ZC + 0.112]));
    part('sump', 'Oil sump with drain plug', g, [0, -0.46, 0.25], { mat: 'Aluminium upper section, pressed-steel lower pan (est.)', note: 'Oil capacity about 4 litres with filter (est.; check the service data).' });
    const s = new THREE.Group(); const ring = roundRect(0.385, 0.218, 0.014, XC, ZC); ring.holes.push(roundRect(0.375, 0.208, 0.01, XC, ZC));
    s.add(mesh(downY(ring, 0.002, 0), M.sealant, [0, CRANK - 0.034, 0]));
    part('seal_sump', 'Sump sealant bead', s, [0, -0.40, 0.25], { tags: ['seal'], mat: 'Silicone sealant', note: 'Liquid sealant, not a cut gasket (est.). Clean both faces and lay a fresh unbroken bead on refit.' });
    const b = new THREE.Group(); for (let i = 0; i < 8; i++) for (const dz of [-0.1, 0.1]) bolt(b, [XC - 0.17 + i * 0.0486, CRANK - 0.08, ZC + dz], 0.006, 0.025, '-y');
    part('bolts_sump', 'Sump bolts', b, [0, -0.54, 0.25], { tags: ['fastener'], qty: 16, size: 'M6 est.' });
    const p = new THREE.Group(); p.add(mesh(rbox(0.085, 0.05, 0.08, 0.01), M.castAlu, [XC + 0.08, CRANK - 0.07, ZC + 0.03]));
    p.add(cylX(0.022, 0.006, M.steel, [XC + 0.125, CRANK - 0.06, ZC + 0.03], 24));
    p.add(mesh(new THREE.TorusGeometry(0.045, 0.002, 4, 40), M.steel, [XC + 0.127, CRANK - 0.02, ZC + 0.015], [0, Math.PI / 2, 0]));
    part('oil_pump', 'Oil pump with drive chain', p, [0.15, -0.40, 0.45], { mat: 'Cast aluminium body, steel chain', note: 'Variable-flow vane pump driven by a short chain from the crankshaft (est. for EA211).' });
  }
  /* head gasket: multi-layer steel with bores, coolant passages and bolt holes */
  {
    const hg = roundRect(0.39, 0.212, 0.016, XC, ZC);
    CX.forEach(x => hg.holes.push(circlePath(x, ZC, BORE / 2 + 0.002)));
    for (let i = 0; i < 5; i++) for (const dz of [-0.088, 0.088]) hg.holes.push(circlePath(XC - 2 * PITCH + i * PITCH, ZC + dz, 0.0062));
    for (let i = 0; i < 4; i++) for (const dz of [-0.066, 0.066]) hg.holes.push(roundRect(0.022, 0.007, 0.003, CX[i] + 0.02, ZC + dz));
    const g = new THREE.Group(); g.add(mesh(downY(hg, 0.0016, 0), M.gasket, [0, DECK + 0.0016, 0]));
    CX.forEach(x => g.add(mesh(new THREE.TorusGeometry(BORE / 2 + 0.0035, 0.0012, 4, 48), M.steel, [x, DECK + 0.0018, ZC], [Math.PI / 2, 0, 0])));
    part('head_gasket', 'Cylinder head gasket', g, [0, 0.22, 0], { tags: ['seal'], mat: 'Multi-layer steel', note: 'Fire rings round each bore, coolant passages and ten bolt holes. Always replaced when the head comes off.' });
  }
  /* cylinder head: chambers, ports, plug wells, cam bearings, integrated exhaust manifold */
  {
    const g = new THREE.Group();
    const plan = roundRect(0.39, 0.212, 0.016, XC, ZC);
    CX.forEach(x => plan.holes.push(circlePath(x, ZC, 0.0105)));
    g.add(mesh(downY(plan, 0.112, 0.003), M.castAlu, [0, DECK + 0.115, 0]));
    CX.forEach(x => {
      g.add(mesh(new THREE.CylinderGeometry(0.0105, 0.0105, 0.11, 24, 1, true), M.darkCast, [x, DECK + 0.06, ZC]));
      g.add(mesh(new THREE.CircleGeometry(BORE / 2 - 0.002, 40), M.darkCast, [x, DECK + 0.0025, ZC], [Math.PI / 2, 0, 0]));
      for (let k = 0; k < 2; k++) { const port = mesh(new THREE.CircleGeometry(0.014, 24), M.dark, [x + (k ? 0.011 : -0.011), DECK + 0.055, ZC - 0.1065], [0, Math.PI, 0]); port.scale.set(0.8, 1.3, 1); g.add(port); }
    });
    const exh = shapeZY([[0, -0.04], [0.045, -0.03], [0.045, 0.03], [0, 0.04]], 0.012);
    g.add(mesh(alongX(exh, 0.26, 0.006, 12), M.castAlu, [XC, DECK + 0.058, ZC + 0.106]));
    g.add(mesh(rbox(0.09, 0.075, 0.012, 0.008), M.machined, [XC + 0.06, DECK + 0.058, ZC + 0.157]));
    for (const cz of CAMZ) for (let i = 0; i < 5; i++) { const sd = mesh(new THREE.CylinderGeometry(0.021, 0.021, 0.016, 28, 1, false, Math.PI / 2, Math.PI), M.castAlu, [XC - 2 * PITCH + i * PITCH, CAMY - 0.002, cz], [0, 0, Math.PI / 2]); g.add(sd); }
    part('head', 'Cylinder head with integrated exhaust manifold', g, [0, 0.36, 0], { mat: 'Die-cast aluminium', note: 'DOHC, four valves per cylinder (published). The EA211 casts its exhaust manifold into the head, so the turbocharger bolts straight onto it (published). Plug wells, ports and bearing saddles are shaped estimates.' });
  }
  /* valves, springs, retainers */
  {
    const g = new THREE.Group();
    const valve = (rHead) => new THREE.LatheGeometry([[0, 0], [rHead, 0], [rHead, 0.0016], [rHead * 0.55, 0.009], [0.0029, 0.022], [0.0029, 0.105], [0, 0.105]].map(([r, y]) => new THREE.Vector2(r, y)), 32);
    const vin = valve(0.0145), vex = valve(0.0125);
    const spring = buildValveSpring(M.steel);
    CX.forEach(x => { for (const k of [0, 1]) { const dx = k ? 0.0145 : -0.0145;
      for (const [cz, geo, ang] of [[ZC - 0.026, vin, 0.2], [ZC + 0.026, vex, -0.2]]) {
        const vv = new THREE.Group(); vv.position.set(x + dx, DECK + 0.004, cz); vv.rotation.x = ang;
        vv.add(new THREE.Mesh(geo, M.machined));
        const sp = spring.clone(); sp.scale.setScalar(0.27); sp.position.y = 0.035 - 0.082 * 0.27; vv.add(sp);
        const ret = new THREE.Mesh(new THREE.CylinderGeometry(0.0095, 0.007, 0.004, 20), M.steel); ret.position.y = 0.035 + 0.174 * 0.27; vv.add(ret);
        vv.traverse(o => { if (o.isMesh) o.castShadow = true; }); g.add(vv); } } });
    part('valves', 'Valves, springs, retainers and stem seals', g, [0, 0.50, 0], { qty: 16, mat: 'Steel valves (sodium-filled exhaust, est.), steel springs', size: 'Intake ≈ Ø 29 mm, exhaust ≈ Ø 25 mm (est.)', note: 'Four valves per cylinder (published). Stem seals are renewed whenever a valve comes out.' });
  }
  /* camshafts: lobes from the workshop's cam profile, journals, sprockets, intake phaser */
  {
    const g = new THREE.Group();
    const lobe = camLobeGeometry(); lobe.scale(0.32, 0.165, 0.165);
    CAMZ.forEach((cz, ci) => {
      g.add(cylX(0.0115, 0.40, M.machined, [XC, CAMY, cz], 24));
      for (let i = 0; i < 5; i++) g.add(cylX(0.0195, 0.016, M.machined, [XC - 2 * PITCH + i * PITCH, CAMY, cz], 28));
      CX.forEach((x, i) => { for (const dx of [-0.0145, 0.0145]) { const l = mesh(lobe, M.forged, [x + dx, CAMY, cz]); l.rotation.x = (i * 2 + (ci ? 1 : 0)) * Math.PI / 4; g.add(l); } });
    });
    g.add(cylX(0.032, 0.03, M.castAlu, [XC + 0.22, CAMY, CAMZ[0]], 40));                                  // intake cam phaser body
    part('camshafts', 'Camshafts, intake and exhaust, with cam phaser', g, [0, 0.60, 0], { qty: 2, mat: 'Assembled steel camshafts (est.)', note: 'Intake cam has a hydraulic phaser for variable timing (published for EA211). The cams run in a separate aluminium cam housing (est.).' });
  }
  /* cam housing, cover, sealant, bolts */
  {
    const s = new THREE.Group(); const ring = roundRect(0.385, 0.205, 0.014, XC, ZC); ring.holes.push(roundRect(0.375, 0.195, 0.01, XC, ZC));
    s.add(mesh(downY(ring, 0.002, 0), M.sealant, [0, DECK + 0.117, 0]));
    part('seal_cam', 'Cam housing sealant', s, [0, 0.74, 0], { tags: ['seal'], mat: 'Silicone sealant', note: 'Liquid sealant between head and cam housing (est.).' });
    const c = new THREE.Group();
    const prof = shapeZY([[-0.104, 0], [0.104, 0], [0.098, 0.04], [0.06, 0.068], [-0.06, 0.068], [-0.098, 0.04]], 0.02);
    const cov = alongX(prof, 0.39, 0.006, 14);
    c.add(mesh(cov, M.blackPlastic, [XC, DECK + 0.117, ZC]));
    CX.forEach(x => c.add(mesh(new THREE.CircleGeometry(0.0125, 28), M.dark, [x, DECK + 0.186, ZC], [-Math.PI / 2, 0, 0])));
    c.add(cylY(0.022, 0.016, M.blackPlastic, [XC - 0.15, DECK + 0.19, ZC + 0.045], 28));
    for (let i = 0; i < 6; i++) c.add(mesh(new THREE.BoxGeometry(0.004, 0.006, 0.12), M.blackPlastic, [XC - 0.13 + i * 0.052, DECK + 0.186, ZC]));
    part('cam_cover', 'Cam housing and cover with oil filler cap', c, [0, 0.90, 0], { mat: 'Aluminium cam housing, plastic cover (est.)', note: 'Four openings for the pencil ignition coils.' });
    const b = new THREE.Group(); for (let i = 0; i < 7; i++) for (const dz of [-0.098, 0.098]) bolt(b, [XC - 0.18 + i * 0.06, DECK + 0.158, ZC + dz], 0.006, 0.035, 'y');
    part('bolts_cam', 'Cam housing bolts', b, [0, 1.02, 0], { tags: ['fastener'], qty: 14, size: 'M6 est.' });
    const hb = new THREE.Group(); for (let i = 0; i < 5; i++) for (const dz of [-0.088, 0.088]) bolt(hb, [XC - 2 * PITCH + i * PITCH, DECK + 0.118, ZC + dz], 0.010, 0.16, 'y', M.blackBolt);
    part('bolts_head', 'Cylinder head bolts', hb, [0, 0.70, 0], { tags: ['fastener'], qty: 10, size: 'M10 stretch bolts (est.)', mat: 'Black-oxide steel', note: 'Torque-to-yield: always replace. Tightening sequence and angle: erWin.' });
  }
  /* spark plugs and injectors */
  {
    const sp = new THREE.Group();
    const plug = () => { const p = new THREE.Group();
      p.add(new THREE.Mesh(new THREE.CylinderGeometry(0.004, 0.004, 0.012, 12), M.steel).translateY(-0.022));
      p.add(new THREE.Mesh(new THREE.CylinderGeometry(0.006, 0.006, 0.019, 16), M.zinc).translateY(-0.006));
      p.add(new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.008, 0.008, 6), M.zinc).translateY(0.008));
      p.add(new THREE.Mesh(new THREE.CylinderGeometry(0.0055, 0.0065, 0.034, 20), M.ceramic).translateY(0.029));
      p.add(new THREE.Mesh(new THREE.CylinderGeometry(0.0025, 0.0025, 0.008, 10), M.steel).translateY(0.05)); return p; };
    CX.forEach(x => { const p = plug(); p.position.set(x, DECK + 0.03, ZC); sp.add(p); });
    part('spark_plugs', 'Spark plugs', sp, [0, 1.14, 0], { qty: 4, mat: 'Ceramic insulator, iridium tip (est.)', note: 'Change interval: service schedule.' });
    const inj = new THREE.Group();
    CX.forEach(x => { const j = new THREE.Group(); j.position.set(x, DECK + 0.035, ZC - 0.118); j.rotation.x = 0.9;
      j.add(new THREE.Mesh(new THREE.CylinderGeometry(0.004, 0.0045, 0.03, 14), M.steel).translateY(-0.03));
      j.add(new THREE.Mesh(new THREE.CylinderGeometry(0.0075, 0.0075, 0.04, 18), M.zinc));
      j.add(new THREE.Mesh(new THREE.BoxGeometry(0.014, 0.016, 0.01), M.blackPlastic).translateY(0.026));
      j.add(new THREE.Mesh(new THREE.TorusGeometry(0.0045, 0.0012, 6, 16), M.ptfe).translateY(-0.04).rotateX(Math.PI / 2));
      inj.add(j); });
    part('injectors', 'Direct fuel injectors with combustion seals', inj, [0, 0.42, -0.32], { qty: 4, note: 'High-pressure direct injection (published for TSI). Each injector’s PTFE combustion seal is renewed on refit.' });
  }
  /* timing belt drive: toothed belt around crank and cam sprockets, tensioner, idler; covers */
  {
    const g = new THREE.Group(), xb = XC + 0.232;
    const pulleys = [[ZC, CRANK, 0.0285], [CAMZ[0], CAMY, 0.046], [CAMZ[1], CAMY, 0.046], [ZC + 0.085, 0.50, 0.03], [ZC - 0.08, 0.47, 0.022]];
    const sprocket = (r, z, y, mat) => { const s = cylX(r, 0.024, mat, [xb, y, z], 48); g.add(s); g.add(cylX(r * 0.42, 0.03, M.machined, [xb, y, z], 24)); };
    sprocket(0.0285, ZC, CRANK, M.steel); sprocket(0.046, CAMZ[0], CAMY, M.steel); sprocket(0.046, CAMZ[1], CAMY, M.steel);
    g.add(cylX(0.03, 0.026, M.zinc, [xb, 0.50, ZC + 0.085], 40)); g.add(cylX(0.022, 0.026, M.zinc, [xb, 0.47, ZC - 0.08], 32));
    const pts = []; for (const [z, y, r] of pulleys) for (let i = 0; i < 48; i++) { const a = i / 48 * Math.PI * 2; pts.push(new THREE.Vector2(z + Math.cos(a) * (r + 0.001), y + Math.sin(a) * (r + 0.001))); }
    const path = resample(hull(pts), 0.004);
    g.add(mesh(ribbon(path, 0.022, 0.003), M.belt, [xb, 0, 0]));
    const tooth = new THREE.BoxGeometry(0.022, 0.0025, 0.0035), tp = resample(hull(pts), 0.0095);
    for (let i = 0; i < tp.length; i++) { const a = tp[i], b = tp[(i + 1) % tp.length]; const t = mesh(tooth, M.belt, [xb, a.y, a.x]); t.rotation.x = -Math.atan2(b.y - a.y, b.x - a.x); g.add(t); }
    part('timing', 'Timing belt, sprockets, tensioner and idler', g, [0.36, 0.10, 0], { mat: 'Glass-fibre reinforced toothed belt', note: 'EA211 uses a toothed timing belt (published). Belt, tensioner and idler are changed together at the service interval; the cams are locked with setting tools first.' });
    const c = new THREE.Group();
    const outline = hull(pts.map(p => p.clone().add(p.clone().sub(new THREE.Vector2(ZC, 0.5)).normalize().multiplyScalar(0.012))));
    const cs = new THREE.Shape(outline.map(p => new THREE.Vector2(p.x, p.y)));
    c.add(mesh(alongX(cs, 0.008, 0.002, 6), M.blackPlastic, [xb + 0.026, 0, 0]));
    const rim = new THREE.Shape(outline.map(p => new THREE.Vector2(p.x, p.y))); rim.holes.push(new THREE.Path(outline.map(p => new THREE.Vector2(ZC + (p.x - ZC) * 0.95, 0.5 + (p.y - 0.5) * 0.95))));
    c.add(mesh(alongX(rim, 0.03, 0.001, 6), M.blackPlastic, [xb + 0.008, 0, 0]));
    part('timing_cover', 'Timing belt covers', c, [0.95, -0.25, -0.2], { mat: 'Plastic (est.)' });
    const w = new THREE.Group();
    w.add(mesh(rbox(0.07, 0.07, 0.06, 0.012), M.blackPlastic, [XC - 0.165, DECK + 0.02, ZC - 0.14]));
    w.add(mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3([V(XC - 0.165, DECK + 0.05, ZC - 0.14), V(XC - 0.165, DECK + 0.09, ZC - 0.17), V(XC - 0.15, DECK + 0.1, ZC - 0.21)]), 20, 0.011, 12), M.blackPlastic));
    part('coolant_pump', 'Coolant pump and thermostat housing', w, [-0.25, 0.25, -0.30], { mat: 'Plastic housing (est.)', note: 'On the EA211 the coolant pump sits in a combined housing driven by a small toothed belt from the exhaust camshaft (published).' });
    const o = new THREE.Group(); o.add(torusX(0.026, 0.0025, M.rubber, [XC - 0.13, DECK + 0.02, ZC - 0.14]));
    part('seal_coolant_pump', 'Coolant pump housing O-ring', o, [-0.25, 0.25, -0.18], { tags: ['seal'], mat: 'EPDM rubber (est.)' });
  }
  return { parts };
}
