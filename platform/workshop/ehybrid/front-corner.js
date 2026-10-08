import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

/* ═════════════════════════════════════════════════════════════════════
   Front corner of the Golf Mk8 / Audi A3 8Y 1.4 eHybrid, modelled from
   photos of a complete removed passenger-side (near-side) corner: MacPherson
   strut with coil spring, gaiter and top mount; cast-aluminium wheel bearing
   housing with a pinch-clamp for the strut; pressed-steel lower link with a
   horizontal front bush and a vertical rear bush; bolted-on swivel joint;
   wheel bearing unit; ventilated disc; floating single-piston caliper on a
   bolted carrier; splash plate; ABS sensor; brake hose on a strut bracket;
   drive shaft with both CV joints. Plus the subframe, steering rack and
   anti-roll bar it hangs off.
   Sizes are educated measurements scaled to the car's measured wheels:
   not OEM CAD. Built for the left side (+X) and mirrored for the right.
   Frame: +X is the car's LEFT, +Y up, +Z the nose, metres.
   ═══════════════════════════════════════════════════════════════════ */

const V = (x, y, z) => new THREE.Vector3(x, y, z);
const UP = V(0, 1, 0), XA = V(1, 0, 0);

/* geometry helpers */
const latheX = (pts, seg = 40) => { const g = new THREE.LatheGeometry(pts.map(([r, x]) => new THREE.Vector2(r, x)), seg); g.rotateZ(-Math.PI / 2); return g; };   // revolve about +X
const latheY = (pts, seg = 40) => new THREE.LatheGeometry(pts.map(([r, y]) => new THREE.Vector2(r, y)), seg);
const ringX = (r0, r1, x0, x1, seg = 48) => latheX([[r0, x0], [r1, x0], [r1, x1], [r0, x1], [r0, x0]], seg);
const cylX = (r, x0, x1, seg = 32) => { const g = new THREE.CylinderGeometry(r, r, x1 - x0, seg); g.rotateZ(-Math.PI / 2); g.translate((x0 + x1) / 2, 0, 0); return g; };
/* a shape drawn in the disc plane: u is "round the clock" (toward the rear), v is up; extruded toward +X */
function discPlane(shape, depth, x0, bevel = 0) {
  const g = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: bevel > 0, bevelThickness: bevel, bevelSize: bevel, bevelSegments: 2, curveSegments: 24 });
  g.rotateY(Math.PI / 2); g.translate(x0, 0, 0); return g;   // (u, v, w) → (w, v, -u)
}
const polar = (r, a) => new THREE.Vector2(r * Math.sin(a), r * Math.cos(a));   // a from 12 o'clock toward the rear
function sector(r0, r1, a0, a1, n = 28) {
  const s = new THREE.Shape(); for (let i = 0; i <= n; i++) { const p = polar(r1, a0 + (a1 - a0) * i / n); i ? s.lineTo(p.x, p.y) : s.moveTo(p.x, p.y); }
  for (let i = n; i >= 0; i--) { const p = polar(r0, a0 + (a1 - a0) * i / n); s.lineTo(p.x, p.y); } return s;
}
const circle = (r, cx = 0, cy = 0, hole = false) => { const p = hole ? new THREE.Path() : new THREE.Shape(); p.absarc(cx, cy, r, 0, Math.PI * 2, hole); return p; };
function roundRect(w, h, r) {
  const s = new THREE.Shape(), x = -w / 2, y = -h / 2; r = Math.min(r, w / 2, h / 2);
  s.moveTo(x + r, y); s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r); s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r); s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y); return s;
}
/* a pressed or cast member from a to b: rounded section w (across) × h (up) */
function beam(a, b, w, h, r = 0.008) {
  const d = b.clone().sub(a), L = d.length();
  const g = new THREE.ExtrudeGeometry(roundRect(L + w * 0.6, w, r), { depth: h, bevelEnabled: true, bevelThickness: Math.min(0.004, h / 4), bevelSize: Math.min(0.004, w / 6), bevelSegments: 2 });
  g.translate(0, 0, -h / 2); g.rotateX(-Math.PI / 2);           // length along X, height along Y
  const q = new THREE.Quaternion().setFromUnitVectors(XA, d.normalize());
  g.applyQuaternion(q); g.translate((a.x + b.x) / 2, (a.y + b.y) / 2, (a.z + b.z) / 2); return g;
}
/* round bar from a to b, tapering r0 → r1 */
function rod(a, b, r0, r1 = r0, seg = 18) {
  const d = b.clone().sub(a), g = new THREE.CylinderGeometry(r1, r0, d.length(), seg);
  g.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(UP, d.normalize())); g.translate((a.x + b.x) / 2, (a.y + b.y) / 2, (a.z + b.z) / 2); return g;
}
const tube = (pts, r, seg = 64, rs = 10) => new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), seg, r, rs, false);
const ball = (p, r) => { const g = new THREE.SphereGeometry(r, 18, 12); g.translate(p.x, p.y, p.z); return g; };
/* rubber gaiter: convolutions between r_in and r_out over length L, along +Y from y0 */
function gaiter(rIn, rOut, y0, L, n, rEnd0 = rIn, rEnd1 = rIn) {
  const pts = [[rEnd0 * 0.92, y0], [rEnd0, y0 + 0.004]];
  for (let i = 0; i <= n * 2; i++) { const t = i / (n * 2), env = 0.55 + 0.45 * Math.sin(Math.PI * Math.min(1, t * 1.15)); pts.push([i % 2 ? rOut * env + rIn * (1 - env) : rIn + (rOut - rIn) * 0.18, y0 + 0.008 + t * (L - 0.016)]); }
  pts.push([rEnd1, y0 + L - 0.004], [rEnd1 * 0.92, y0 + L]); return latheY(pts, 36);
}
function coil(y0, y1, R, wire, turns) {
  const pts = [], n = Math.round(turns * 36);
  for (let i = 0; i <= n; i++) {
    const t = i / n, a = t * turns * Math.PI * 2;
    // closed, ground ends: the first and last ¾ turn barely rise
    const e = 0.75 / turns, s = t < e ? (t / e) * 0.35 * e : t > 1 - e ? 1 - ((1 - t) / e) * 0.35 * e : 0.35 * e + (t - e) / (1 - 2 * e) * (1 - 0.7 * e);
    pts.push(V(Math.cos(a) * R, y0 + wire + s * (y1 - y0 - 2 * wire), Math.sin(a) * R));
  }
  return new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), n * 2, wire, 10, false);
}
const merge = gs => mergeGeometries(gs.map(g => g.index ? g.toNonIndexed() : g), false);

/* fasteners: head toward `dir`, shank the other way. Optional nut on the far end. */
const R = { y: [0, 0, 0], '-y': [Math.PI, 0, 0], x: [0, 0, -Math.PI / 2], '-x': [0, 0, Math.PI / 2], z: [Math.PI / 2, 0, 0], '-z': [-Math.PI / 2, 0, 0] };
function fastener(M, g, p, dia, len, dir, { nut = false, endNut = false, mat, flange = true, socket = false } = {}) {
  const b = new THREE.Group(), m = mat || M.zinc, add = (geo, mm = m) => { const x = new THREE.Mesh(geo, mm); x.castShadow = true; b.add(x); };
  const af = dia * 1.6, h = nut ? dia * 0.8 : dia * 0.62;
  if (socket) { const c = new THREE.CylinderGeometry(dia * 0.75, dia * 0.75, h, 24); c.translate(0, h / 2 + 0.0005, 0); add(c); const s = new THREE.CylinderGeometry(dia * 0.38, dia * 0.38, 0.002, 6); s.translate(0, h + 0.001, 0); add(s, M.black); }
  else { const hx = new THREE.CylinderGeometry(af / Math.sqrt(3), af / Math.sqrt(3), h, 6); hx.translate(0, h / 2 + dia * 0.1, 0); add(hx); }
  if (flange) { const f = new THREE.CylinderGeometry(dia * 1.05, dia * 1.05, dia * 0.12, 24); f.translate(0, dia * 0.06, 0); add(f); }
  const s = new THREE.CylinderGeometry(dia / 2, dia / 2, len, 14); s.translate(0, -len / 2, 0); add(s, nut ? M.zinc : m);
  if (endNut) { const n = new THREE.CylinderGeometry(af / Math.sqrt(3), af / Math.sqrt(3), dia * 0.8, 6); n.translate(0, -len + dia * 0.55, 0); add(n, M.zinc); }
  b.rotation.set(...R[dir]); b.position.copy(p); g.add(b); return b;
}

export function buildFrontCorners(materialFactory, { centres, flanges }) {
  const mf = materialFactory;
  const M = {
    alu: mf(0xa7abae, { metalness: 0.55, roughness: 0.52 }, 'cast'),                 // cast-aluminium bearing housing
    iron: mf(0x8b8f93, { metalness: 0.72, roughness: 0.36 }, 'brushed'),              // machined disc faces
    ironRust: mf(0x6c5a4e, { metalness: 0.35, roughness: 0.8 }, 'cast'),              // disc hat and vanes, light surface rust
    caliper: mf(0x3a3c3f, { metalness: 0.45, roughness: 0.6 }, 'cast'),               // cast-iron caliper, unpainted
    carrier: mf(0x46423e, { metalness: 0.45, roughness: 0.66 }, 'cast'),
    black: mf(0x1c1e20, { metalness: 0.35, roughness: 0.55 }, 'cast'),                // e-coated pressed steel
    strut: mf(0x222426, { metalness: 0.45, roughness: 0.42 }, 'brushed'),
    spring: mf(0x2d3034, { metalness: 0.5, roughness: 0.4 }, 'brushed'),
    chrome: mf(0xd6d9dc, { metalness: 1, roughness: 0.12 }, 'brushed'),
    rubber: mf(0x141516, { metalness: 0, roughness: 0.86 }, 'rubber'),
    steel: mf(0x75797e, { metalness: 0.85, roughness: 0.34 }, 'brushed'),
    shaft: mf(0x4f5357, { metalness: 0.75, roughness: 0.42 }, 'brushed'),
    zinc: mf(0xb8bec4, { metalness: 0.9, roughness: 0.32 }, 'brushed'),
    yzinc: mf(0xc9b46a, { metalness: 0.85, roughness: 0.36 }, 'brushed'),           // yellow-passivated hose fittings
    pad: mf(0x2b2a28, { metalness: 0.1, roughness: 0.92 }, 'rubber'),
    plastic: mf(0x202020, { metalness: 0, roughness: 0.7 }, 'plastic'),
    shield: mf(0x5d6166, { metalness: 0.6, roughness: 0.5 }, 'cast'),
  };
  const out = [];
  const mesh = (g, geo, mat, cast = true) => { const m = new THREE.Mesh(geo, mat); m.castShadow = cast; m.receiveShadow = true; g.add(m); return m; };

  /* ── subframe, steering rack and anti-roll bar (one each, across the car) ── */
  {
    const g = new THREE.Group(); g.name = 'subframe_f';
    for (const sx of [1, -1]) {
      mesh(g, beam(V(sx * 0.30, 0.205, 1.43), V(sx * 0.30, 0.215, 1.0), 0.07, 0.055), M.black);
      mesh(g, beam(V(sx * 0.3, 0.238, 1.06), V(sx * 0.4, 0.238, 1.06), 0.07, 0.012), M.black);
      mesh(g, rod(V(sx * 0.30, 0.23, 1.42), V(sx * 0.30, 0.32, 1.42), 0.026), M.black);   // front body mounting towers
      mesh(g, rod(V(sx * 0.30, 0.23, 1.02), V(sx * 0.30, 0.31, 1.02), 0.026), M.black);
      // lower link brackets: a U for the front bush, a pad for the rear one
      for (const dz of [-0.035, 0.035]) mesh(g, new THREE.BoxGeometry(0.06, 0.06, 0.006).translate(sx * 0.36, 0.205, 1.335 + dz), M.black);
      mesh(g, new THREE.CylinderGeometry(0.05, 0.05, 0.012, 24).translate(sx * 0.40, 0.235, 1.06), M.black);
      // rack gaiter and inner track rod out to the track rod end
      mesh(g, gaiter(0.012, 0.03, 0, 0.1, 6, 0.028, 0.011).applyQuaternion(new THREE.Quaternion().setFromUnitVectors(UP, V(sx, 0, 0))).translate(sx * 0.33, 0.245, 1.15), M.rubber);
      mesh(g, rod(V(sx * 0.42, 0.24, 1.152), V(sx * 0.585, 0.226, 1.162), 0.0095), M.steel);
      // anti-roll bar rubber mounts
      mesh(g, new THREE.BoxGeometry(0.045, 0.04, 0.05).translate(sx * 0.3, 0.255, 1.08), M.rubber);
      mesh(g, new THREE.BoxGeometry(0.05, 0.012, 0.07).translate(sx * 0.3, 0.282, 1.08), M.black);
    }
    mesh(g, beam(V(-0.3, 0.215, 1.405), V(0.3, 0.215, 1.405), 0.06, 0.05), M.black);
    mesh(g, beam(V(-0.3, 0.22, 1.02), V(0.3, 0.22, 1.02), 0.08, 0.045), M.black);
    mesh(g, cylX(0.028, -0.33, 0.33).translate(0, 0.245, 1.15), M.alu);             // rack housing
    mesh(g, cylX(0.045, -0.08, 0.06).translate(0, 0.255, 1.15), M.alu);             // EPS motor and gear
    mesh(g, rod(V(-0.04, 0.27, 1.15), V(-0.04, 0.45, 1.05), 0.012), M.steel);       // pinion to the column
    out.push({ id: 'subframe_f', name: 'Front subframe with steering rack and track rods', sys: 'susp', obj: g, ex: V(0, -0.35, 0), tags: ['frontsusp'], conf: 'est', mat: 'Pressed and welded steel; aluminium rack housing', note: 'The base the lower links, rack and anti-roll bar fit to. Shape simplified: it carries the pendulum support and engine loads in the real car (subframe bolts 70 Nm + 180°, renew, in the manual data).' });

    const a = new THREE.Group(); a.name = 'arb_f';
    const P = [V(0.565, 0.335, 1.205), V(0.47, 0.30, 1.13), V(0.36, 0.272, 1.085), V(0, 0.272, 1.08)];
    mesh(a, tube([...P.map(p => V(-p.x, p.y, p.z)), ...P.slice(0, 3).reverse()], 0.0105, 120), M.black);
    for (const sx of [1, -1]) mesh(a, new THREE.SphereGeometry(0.016, 14, 10).translate(sx * 0.565, 0.335, 1.205), M.black);
    out.push({ id: 'arb_f', name: 'Front anti-roll bar with rubber bushes', sys: 'susp', obj: a, ex: V(0, -0.25, -0.15), tags: ['frontsusp'], conf: 'est', mat: 'Spring steel, rubber bushes', note: 'Comes out with the subframe lowered (manual chapter). Bush clamp bolts 20 Nm + 90°, renew; tighten evenly.' });
  }

  /* ── one corner, built on the left; the right is the mirror image ── */
  for (const k of ['fl', 'fr']) {
    const sx = k === 'fl' ? 1 : -1, side = sx > 0 ? 'left' : 'right', SIDE = sx > 0 ? 'front-left' : 'front-right';
    const C = centres[k].clone(); C.x = Math.abs(C.x);                              // hub centre, built on +X
    const XF = C.x + 0.024;                                                         // wheel mounting face
    const groups = [];
    const part = (id, name, sys, ex, extra = {}) => { const g = new THREE.Group(); g.name = id + '_' + k; groups.push(g); out.push({ id: id + '_' + k, name: `${name}, ${side}`, sys, obj: g, ex: V(ex[0] * sx, ex[1], ex[2]), tags: [], conf: 'est', ...extra }); return g; };
    const fset = (id, host, extra = {}) => { const g = new THREE.Group(); g.name = id + '_' + k; groups.push(g); out.push({ id: id + '_' + k, host: host + '_' + k, sys: 'susp', obj: g, tags: ['fastener'], conf: 'pub', ...extra }); return g; };
    const at = (r, a) => V(0, C.y + r * Math.cos(a), C.z - r * Math.sin(a));       // a point in the wheel plane, a from 12 o'clock toward the rear

    /* wheel bearing housing (knuckle) */
    const THC = 75 * Math.PI / 180;                                                 // caliper sits trailing, just above the centre line
    const B = V(0.635, 0.485, C.z + 0.006), T = V(0.575, 0.905, C.z - 0.024);       // strut: clamp centre and top-mount centre
    const A = T.clone().sub(B).normalize(), qA = new THREE.Quaternion().setFromUnitVectors(UP, A);
    const J = V(0.69, 0.24, C.z + 0.002);                                           // swivel joint stud in the housing
    const E = V(0.64, 0.255, C.z - 0.15);                                           // steering arm eye
    {
      const g = part('knuckle', 'Wheel bearing housing (cast aluminium)', 'susp', [0.35, 0, 0], { mat: 'Cast aluminium', note: 'Cast-aluminium housing as on the removed corner in the photos: pinch-clamp at the top for the strut, swivel joint at the bottom, steering arm trailing low, two carrier lugs. Different versions exist (ETKA).' });
      const boss = new THREE.Shape(); { const n = 48; for (let i = 0; i <= n; i++) { const a = i / n * Math.PI * 2, r = 0.074 + 0.012 * Math.max(0, Math.cos(4 * (a - Math.PI / 4))) ** 6; const p = polar(r, a); i ? boss.lineTo(p.x, p.y) : boss.moveTo(p.x, p.y); } }
      boss.holes.push(circle(0.047, 0, 0, true));
      for (let i = 0; i < 4; i++) { const p = polar(0.066, Math.PI / 4 + i * Math.PI / 2); boss.holes.push(circle(0.0065, p.x, p.y, true)); }
      mesh(g, discPlane(boss, 0.022, 0.688, 0.002).translate(0, C.y, C.z), M.alu);
      mesh(g, ringX(0.047, 0.056, 0.672, 0.69).translate(0, C.y, C.z), M.alu);    // inboard collar round the bearing
      // upper arm up to the strut clamp, with a web
      const top = B.clone().addScaledVector(A, -0.045);
      mesh(g, beam(V(0.7, C.y + 0.065, C.z), top.clone().add(V(0.005, 0, 0)), 0.034, 0.028), M.alu);
      mesh(g, beam(V(0.693, C.y + 0.04, C.z - 0.04), top.clone().add(V(0.008, -0.01, -0.02)), 0.012, 0.03), M.alu);
      // pinch clamp: split sleeve with two ears on the inboard side
      const sl = latheY([[0.026, -0.045], [0.037, -0.045], [0.037, 0.045], [0.026, 0.045], [0.026, -0.045]], 36); sl.applyQuaternion(qA); sl.translate(B.x, B.y, B.z);
      mesh(g, sl, M.alu);
      for (const dz of [-0.026, 0.026]) mesh(g, new THREE.BoxGeometry(0.03, 0.06, 0.016).translate(B.x - 0.036, B.y, B.z + dz), M.alu);
      // lower leg to the swivel joint boss
      mesh(g, beam(V(0.698, C.y - 0.06, C.z), V(J.x, J.y + 0.02, J.z), 0.036, 0.03), M.alu);
      mesh(g, new THREE.CylinderGeometry(0.022, 0.024, 0.032, 24).translate(J.x, J.y + 0.016, J.z), M.alu);
      // steering arm, trailing and low, to the track rod end eye
      mesh(g, beam(V(0.695, C.y - 0.045, C.z - 0.055), E, 0.026, 0.024), M.alu);
      mesh(g, new THREE.CylinderGeometry(0.018, 0.018, 0.026, 20).translate(E.x, E.y, E.z), M.alu);
      // two lugs for the brake carrier
      for (const t of [-0.07, 0.07]) { const p = at(0.105, THC); const tg = V(0, Math.sin(THC), Math.cos(THC)); p.addScaledVector(tg, t); p.x = 0.696;
        mesh(g, beam(V(0.693, C.y + (p.y - C.y) * 0.45, C.z + (p.z - C.z) * 0.45), p, 0.026, 0.022), M.alu);
        mesh(g, cylX(0.016, 0.686, 0.704).translate(0, p.y, p.z), M.alu); }
      // ABS sensor bore boss
      const sp = at(0.06, 0.7); mesh(g, cylX(0.015, 0.664, 0.69).translate(0, sp.y, sp.z), M.alu);
    }

    /* wheel bearing unit and hub flange */
    {
      const g = part('bearing', 'Wheel bearing unit with hub', 'susp', [0.55, 0, 0], { tags: ['bearing'], mat: 'Steel, sealed for life; ABS sensor ring built in', note: 'Wheel bearing and hub in one unit, cannot be repaired (manual). The ABS sensor ring is integrated in the bearing.' });
      mesh(g, cylX(0.046, 0.672, 0.768).translate(0, C.y, C.z), M.steel);
      mesh(g, ringX(0.03, 0.046, 0.668, 0.673).translate(0, C.y, C.z), M.rubber);    // inboard seal and encoder
      const fl = new THREE.Shape(); { const n = 64; for (let i = 0; i <= n; i++) { const a = i / n * Math.PI * 2, r = 0.058 + 0.016 * Math.max(0, Math.cos(2 * a)) ** 3; const p = polar(r, a + Math.PI / 4); i ? fl.lineTo(p.x, p.y) : fl.moveTo(p.x, p.y); } }
      for (let i = 0; i < 4; i++) { const p = polar(0.066, Math.PI / 4 + i * Math.PI / 2); fl.holes.push(circle(0.0065, p.x, p.y, true)); }
      fl.holes.push(circle(0.03, 0, 0, true));
      mesh(g, discPlane(fl, 0.01, 0.71, 0.0015).translate(0, C.y, C.z), M.steel);   // mounting flange against the housing
      const hub = new THREE.Shape(); { const n = 80; for (let i = 0; i <= n; i++) { const a = i / n * Math.PI * 2, r = 0.062 + 0.01 * Math.cos(5 * a); const p = polar(r, a); i ? hub.lineTo(p.x, p.y) : hub.moveTo(p.x, p.y); } }
      for (let i = 0; i < 5; i++) { const p = polar(0.056, i / 5 * Math.PI * 2); hub.holes.push(circle(0.0068, p.x, p.y, true)); }
      hub.holes.push(circle(0.016, 0, 0, true));
      mesh(g, discPlane(hub, 0.01, XF - 0.018, 0.001).translate(0, C.y, C.z), M.steel);
      mesh(g, ringX(0.016, 0.0322, XF - 0.008, XF + 0.012).translate(0, C.y, C.z), M.steel);   // centring spigot
    }

    /* ventilated disc 340 × 30 (estimated) */
    {
      const g = part('disc', 'Brake disc, ventilated', 'wheels', [0.62, 0, 0], { tags: ['wear'], mat: 'Grey cast iron', size: '≈ 340 × 30 mm (est.)', note: 'Internally ventilated. Always renew on both sides of an axle. Remove brake caliper and carrier first; never force a disc off the hub, use penetrating fluid (manual). Diameter estimated from the car’s model; the Golf GTE parts lists show 312 × 25 and 340 × 30 options: check by PR code.' });
      const X0 = XF - 0.066, RO = 0.17, RI = 0.105;
      mesh(g, ringX(RI, RO, X0, X0 + 0.009, 72).translate(0, C.y, C.z), M.iron);
      mesh(g, ringX(RI, RO, X0 + 0.021, X0 + 0.030, 72).translate(0, C.y, C.z), M.iron);
      const vanes = []; for (let i = 0; i < 37; i++) { const a = i / 37 * Math.PI * 2, v = new THREE.BoxGeometry(0.012, RO - RI - 0.004, 0.0042); v.translate(X0 + 0.015, (RO + RI) / 2, 0); v.rotateX(a); vanes.push(v); }
      mesh(g, merge(vanes).translate(0, C.y, C.z), M.ironRust);
      mesh(g, latheX([[RI, X0 + 0.004], [0.084, X0 + 0.012], [0.084, XF - 0.008], [0.089, XF - 0.008], [0.089, X0 + 0.02], [RI + 0.002, X0 + 0.024]], 64).translate(0, C.y, C.z), M.ironRust);
      const hat = circle(0.089); hat.holes.push(circle(0.0328, 0, 0, true));
      for (let i = 0; i < 5; i++) { const p = polar(0.056, i / 5 * Math.PI * 2); hat.holes.push(circle(0.0072, p.x, p.y, true)); }
      const s = polar(0.04, Math.PI / 5); hat.holes.push(circle(0.004, s.x, s.y, true));
      mesh(g, discPlane(hat, 0.008, XF - 0.008).translate(0, C.y, C.z), M.ironRust);
    }

    /* splash plate */
    {
      const g = part('splash', 'Splash plate', 'wheels', [0.42, 0, 0], { mat: 'Pressed steel', note: 'Sits behind the disc on the bearing housing. Bolts 12 Nm (manual).' });
      const s = sector(0.09, 0.168, THC + 1.0, THC + Math.PI * 2 - 1.0, 64);
      mesh(g, discPlane(s, 0.0015, XF - 0.084).translate(0, C.y, C.z), M.shield);
      mesh(g, discPlane(sector(0.164, 0.17, THC + 1.0, THC + Math.PI * 2 - 1.0, 64), 0.014, XF - 0.084).translate(0, C.y, C.z), M.shield);   // turned-out lip
    }

    /* brake carrier, pads and the floating caliper */
    const calG = (name, mat) => { const r = new THREE.Group(); r.rotation.x = -THC; r.position.set(0, C.y, C.z); return r; };
    const calPt = (x, r, t) => V(x, r, t).applyAxisAngle(XA, -THC).add(V(0, C.y, C.z));
    {
      const g = part('carrier', 'Brake carrier', 'wheels', [0.68, 0.05, -0.05], { mat: 'Cast iron', note: 'Bolted to the bearing housing with two ribbed-collar bolts, 200 Nm; clean them if reused. Thin coat of lithium grease G 052150 A2 on the pad guide surfaces (manual).' });
      const r = calG(); g.add(r);
      for (const t of [-0.07, 0.07]) {
        mesh(r, new THREE.BoxGeometry(0.016, 0.07, 0.024).translate(0.709, 0.13, t), M.carrier);         // inboard legs on the lugs
        mesh(r, new THREE.BoxGeometry(XF - 0.012 - 0.7, 0.018, 0.022).translate((XF - 0.012 + 0.7) / 2, 0.181, t), M.carrier);   // bridges over the disc
        mesh(r, new THREE.BoxGeometry(0.012, 0.05, 0.02).translate(XF - 0.018, 0.155, t), M.carrier);     // outboard ears
      }
      mesh(r, new THREE.BoxGeometry(0.014, 0.022, 0.16).translate(0.709, 0.1, 0), M.carrier);
    }
    {
      const g = part('pads', 'Brake pads (inner and outer)', 'wheels', [0.8, 0.12, -0.05], { qty: 2, tags: ['wear'], mat: 'Friction material on steel backplates', size: '14 mm new, wear limit 2 mm (not incl. backplate)', note: 'Always renew on both sides of an axle. The front-right pad carries the wear indicator (manual).' });
      const r = calG(); g.add(r);
      const shp = sector(0.118, 0.168, -0.36, 0.36, 18);
      for (const [x0, dir] of [[XF - 0.066 - 0.0125, 1], [XF - 0.036, -1]]) {
        mesh(r, discPlane(shp, 0.0105, dir > 0 ? x0 : x0 + 0.0005), M.pad);
        mesh(r, discPlane(sector(0.114, 0.172, -0.4, 0.4, 18), 0.004, dir > 0 ? x0 - 0.004 : x0 + 0.011), M.steel);
      }
    }
    {
      const g = part('caliper', 'Brake caliper (single piston, floating)', 'wheels', [0.78, 0.18, -0.05], { mat: 'Cast iron', note: 'Floating caliper with one piston, on two guide pins. Do not disconnect the brake hose when changing pads: hang the caliper on wire, never on the hose. Guide bolts are self-locking: renew, 35 Nm (manual).' });
      const r = calG(); g.add(r);
      mesh(r, cylX(0.033, 0.666, 0.704).translate(0, 0.143, 0), M.caliper);                                 // piston bore
      mesh(r, latheX([[0, 0.66], [0.026, 0.66], [0.033, 0.668]], 32).translate(0, 0.143, 0), M.caliper);
      mesh(r, new THREE.BoxGeometry(0.034, 0.062, 0.1).translate(0.687, 0.15, 0), M.caliper);              // housing
      mesh(r, new THREE.BoxGeometry(XF - 0.01 - 0.69, 0.026, 0.104).translate((XF - 0.01 + 0.69) / 2, 0.188, 0), M.caliper);   // bridge over the disc
      for (const t of [-0.026, 0.026]) mesh(r, new THREE.BoxGeometry(0.014, 0.058, 0.036).translate(XF - 0.015, 0.158, t), M.caliper);   // outer fingers
      for (const t of [-0.078, 0.078]) {
        mesh(r, cylX(0.012, 0.672, 0.698).translate(0, 0.15, t), M.caliper);                                 // guide pin bosses
        mesh(r, new THREE.BoxGeometry(0.024, 0.03, 0.03).translate(0.686, 0.15, t * 0.8), M.caliper);
        mesh(r, cylX(0.0095, 0.698, 0.701).translate(0, 0.15, t), M.rubber);                                // guide pin seal
        mesh(r, new THREE.BoxGeometry(0.016, 0.03, 0.026).translate(0.709, 0.15, t), M.carrier);            // carrier boss the pin slides in
      }
      mesh(r, new THREE.CylinderGeometry(0.0045, 0.0045, 0.022, 10).translate(0.686, 0.178, -0.03), M.steel);   // bleed nipple
      mesh(r, new THREE.CylinderGeometry(0.006, 0.006, 0.006, 12).translate(0.686, 0.191, -0.03), M.rubber);
      mesh(r, cylX(0.01, 0.66, 0.67).translate(0, 0.165, 0.03), M.caliper);                                 // banjo boss
    }

    /* brake hose: banjo at the caliper, up to the strut bracket, steel line to the inner wing */
    const banjo = calPt(0.655, 0.165, 0.03);
    const SB = (y) => B.clone().addScaledVector(A, y);                             // a point on the strut axis
    const hoseBr = SB(0.06).add(V(0.03, 0, -0.03));
    {
      const g = part('hose', 'Brake hose with banjo union', 'wheels', [0.5, 0.25, -0.1], { mat: 'Rubber hose, steel fittings', note: 'Banjo bolt 35 Nm with new sealing washers; bracket on the strut 8 Nm (manual). Bleed the brakes after opening the hydraulics.' });
      mesh(g, cylX(0.012, banjo.x - 0.004, banjo.x + 0.004).translate(0, banjo.y, banjo.z), M.yzinc);
      const p0 = banjo.clone().add(V(-0.005, 0.016, 0)), p3 = hoseBr.clone().add(V(0, -0.02, 0));
      mesh(g, tube([p0, p0.clone().add(V(-0.03, 0.04, -0.02)), V((p0.x + p3.x) / 2 - 0.02, (p0.y + p3.y) / 2 + 0.01, p3.z - 0.05), p3.clone().add(V(0, -0.05, -0.02)), p3], 0.0055), M.rubber);
      mesh(g, rod(p3, p3.clone().add(V(0, 0.03, 0)), 0.0065), M.yzinc);
      mesh(g, new THREE.BoxGeometry(0.004, 0.03, 0.032).translate(hoseBr.x + 0.004, hoseBr.y, hoseBr.z), M.black);   // bracket tab
      const q0 = hoseBr.clone().add(V(0, 0.02, 0));
      mesh(g, tube([q0, q0.clone().add(V(-0.01, 0.06, -0.02)), V(q0.x - 0.04, q0.y + 0.13, q0.z - 0.08), V(q0.x - 0.06, 0.78, q0.z - 0.12)], 0.0024, 48, 6), M.yzinc);
    }

    /* ABS speed sensor and its lead, clipped up the strut */
    {
      const g = part('abs', 'ABS wheel speed sensor with lead', 'wheels', [0.45, 0.12, -0.12], { mat: 'Plastic sensor, PVC lead', note: 'Reads the sensor ring in the wheel bearing unit. Clean the bore and coat it with high-temperature paste G 052 112 A3 before fitting. Bolt 8 Nm (manual).' });
      const sp = at(0.06, 0.7);
      mesh(g, cylX(0.0085, 0.648, 0.686).translate(0, sp.y, sp.z), M.plastic);
      mesh(g, new THREE.BoxGeometry(0.006, 0.026, 0.016).translate(0.662, sp.y + 0.014, sp.z), M.plastic);
      const l0 = V(0.646, sp.y, sp.z);
      mesh(g, tube([l0, V(0.62, sp.y + 0.03, sp.z - 0.01), SB(0.02).add(V(0.035, 0, -0.02)), SB(0.08).add(V(0.03, 0, -0.035)), SB(0.2).add(V(0.0, 0, -0.06)), V(0.53, 0.8, C.z - 0.12)], 0.0032, 64, 8), M.plastic);
      for (const y of [0.08, 0.2]) mesh(g, new THREE.BoxGeometry(0.012, 0.01, 0.012).translate(...SB(y).add(V(y < 0.1 ? 0.03 : 0, 0, y < 0.1 ? -0.035 : -0.06)).toArray()), M.rubber);
    }

    /* MacPherson strut: damper, spring, gaiter, top mount */
    {
      const g = part('strut', 'Suspension strut with coil spring and top mount', 'susp', [0.25, 0.4, 0], { mat: 'Steel damper, spring steel, rubber mount', note: 'Comes out as one unit. Undoing the piston rod nut (60 Nm, renew) needs a spring compressor. Coil spring surface must not be damaged. Different damper and spring versions (ETKA).' });
      const s = new THREE.Group(); s.quaternion.copy(qA); s.position.copy(B); g.add(s);
      mesh(s, latheY([[0, -0.06], [0.021, -0.06], [0.0245, -0.052], [0.0245, 0.205], [0, 0.205]], 32), M.strut);
      mesh(s, latheY([[0.024, 0.178], [0.05, 0.182], [0.079, 0.19], [0.082, 0.2], [0.076, 0.203], [0.03, 0.2]], 48), M.strut);   // lower spring seat
      mesh(s, coil(0.2, 0.395, 0.068, 0.0118, 4.6), M.spring);
      mesh(s, new THREE.CylinderGeometry(0.011, 0.011, 0.24, 18).translate(0, 0.325, 0), M.chrome);
      mesh(s, gaiter(0.022, 0.034, 0.212, 0.165, 9, 0.026, 0.02), M.rubber);
      mesh(s, latheY([[0.02, 0.395], [0.086, 0.395], [0.088, 0.405], [0.06, 0.41], [0.02, 0.41]], 48), M.plastic);   // upper seat
      mesh(s, latheY([[0.03, 0.41], [0.062, 0.41], [0.062, 0.418], [0.03, 0.418]], 40), M.steel);                     // thrust bearing
      mesh(s, latheY([[0.012, 0.418], [0.078, 0.418], [0.08, 0.428], [0.07, 0.442], [0.04, 0.446], [0.012, 0.446]], 48), M.rubber);   // top mount
      mesh(s, latheY([[0.012, 0.442], [0.074, 0.442], [0.074, 0.446], [0.012, 0.446]], 48), M.black);
      mesh(s, new THREE.CylinderGeometry(0.026, 0.028, 0.016, 24).translate(0, 0.454, 0), M.plastic);                  // cover over the rod nut
      // drop link bracket and brake hose bracket welded to the tube
      const db = SB(0.12), dl = db.clone().add(V(-0.04, 0, -0.04));
      mesh(g, beam(db, dl, 0.016, 0.03, 0.004), M.strut);
      mesh(g, beam(SB(0.06), hoseBr, 0.012, 0.022, 0.003), M.strut);
    }

    /* drop link (coupling rod) */
    const dTop = SB(0.12).add(V(-0.04, 0, -0.04)), dBot = V(0.565, 0.335, 1.205);
    {
      const g = part('droplink', 'Coupling rod (drop link)', 'susp', [0.2, 0.1, -0.12], { mat: 'Steel rod, two ball joints', note: 'Joins the anti-roll bar to the strut. Nuts 65 Nm, renew; counterhold on the joint stub’s multi-point socket (manual).' });
      mesh(g, rod(dBot.clone().add(V(0, 0.03, 0)), dTop.clone().add(V(0, -0.03, 0)), 0.008), M.black);
      for (const [p, s] of [[dBot.clone().add(V(0, 0.02, 0)), 1], [dTop.clone().add(V(0, -0.02, 0)), -1]]) {
        mesh(g, new THREE.SphereGeometry(0.017, 16, 12).translate(p.x, p.y, p.z), M.black);
        mesh(g, new THREE.CylinderGeometry(0.012, 0.016, 0.014, 16).translate(p.x, p.y - s * 0.016, p.z), M.rubber);
      }
    }

    /* track rod end */
    {
      const g = part('tre', 'Track rod end', 'susp', [0.25, -0.05, -0.15], { mat: 'Forged steel ball joint', note: 'Screwed onto the inner track rod with a lock nut: count the turns or set the toe after (wheel alignment). Nut to the steering arm 20 Nm + 90°, renew (manual).' });
      const h = V(E.x, E.y - 0.032, E.z);
      mesh(g, new THREE.CylinderGeometry(0.019, 0.017, 0.028, 20).translate(h.x, h.y, h.z), M.steel);
      mesh(g, new THREE.CylinderGeometry(0.014, 0.017, 0.012, 18).translate(h.x, h.y + 0.019, h.z), M.rubber);
      mesh(g, rod(h, V(0.585, 0.226, 1.162), 0.011), M.steel);
      mesh(g, cylX(0.012, 0.598, 0.61).translate(0, h.y - 0.001, (h.z + 1.162) / 2), M.zinc);
    }

    /* swivel joint (lower ball joint) */
    {
      const g = part('bj', 'Swivel joint (lower ball joint)', 'susp', [0.3, -0.22, 0], { mat: 'Forged housing, sealed', note: 'Bolted to the lower link with three nuts, 40 Nm + 45°, renew, in the unladen position; stud nut into the housing 60 Nm, renew (manual).' });
      mesh(g, new THREE.CylinderGeometry(0.023, 0.026, 0.05, 24).translate(J.x, 0.175, J.z), M.steel);
      const tri = new THREE.Shape(); for (let i = 0; i <= 3; i++) { const a = i / 3 * Math.PI * 2 + Math.PI / 6; const p = new THREE.Vector2(Math.cos(a) * 0.04, Math.sin(a) * 0.04); i ? tri.lineTo(p.x, p.y) : tri.moveTo(p.x, p.y); }
      const tg = new THREE.ExtrudeGeometry(tri, { depth: 0.006, bevelEnabled: true, bevelSize: 0.008, bevelThickness: 0.002, bevelSegments: 2 }); tg.rotateX(Math.PI / 2); tg.translate(J.x, 0.198, J.z);
      mesh(g, tg, M.steel);
      mesh(g, latheY([[0.024, 0], [0.026, 0.006], [0.02, 0.016], [0.011, 0.022], [0.01, 0.026]], 28).translate(J.x, 0.2, J.z), M.rubber);
      mesh(g, new THREE.CylinderGeometry(0.008, 0.011, 0.04, 16).translate(J.x, J.y + 0.0, J.z), M.steel);
    }

    /* lower link */
    const F = V(0.365, 0.205, C.z + 0.02), Rb = V(0.40, 0.215, 1.06);
    {
      const g = part('arm', 'Lower suspension link', 'susp', [0.2, -0.32, 0], { mat: 'Pressed steel, black e-coat', note: 'Pressed-steel L-shaped link: horizontal bonded front bush, large rear bush with vertical axis. Bolts to the subframe 70 Nm + 180°, renew, tightened in the unladen position (manual). Bushes are renewed with a press.' });
      mesh(g, beam(V(0.725, 0.172, J.z), V(F.x + 0.02, F.y - 0.005, F.z), 0.062, 0.026, 0.012), M.black);
      mesh(g, beam(V(0.62, 0.178, J.z - 0.02), V(Rb.x + 0.01, Rb.y - 0.02, Rb.z + 0.03), 0.054, 0.026, 0.012), M.black);
      mesh(g, beam(V(0.6, 0.176, J.z + 0.005), V(0.47, 0.192, 1.2), 0.03, 0.022, 0.01), M.black);
      const bushF = latheY([[0.012, -0.03], [0.029, -0.03], [0.031, 0], [0.029, 0.03], [0.012, 0.03]], 28); bushF.rotateX(Math.PI / 2); bushF.translate(F.x, F.y, F.z);
      mesh(g, bushF, M.rubber);
      mesh(g, latheY([[0.03, -0.034], [0.034, -0.034], [0.034, 0.034], [0.03, 0.034]], 28).rotateX(Math.PI / 2).translate(F.x, F.y, F.z), M.black);
      mesh(g, latheY([[0.012, -0.024], [0.04, -0.024], [0.046, 0], [0.04, 0.024], [0.012, 0.024]], 32).translate(Rb.x, Rb.y - 0.01, Rb.z), M.rubber);
      mesh(g, latheY([[0.045, -0.026], [0.05, -0.026], [0.05, 0.026], [0.045, 0.026]], 32).translate(Rb.x, Rb.y - 0.01, Rb.z), M.black);
    }

    /* drive shaft: inner flange joint, boots, bar, outer CV joint, stub through the bearing */
    {
      const inner = flanges[k];                                                     // inner flange face, signed X in the car
      const xi = inner * sx;                                                        // same, in this corner's built-on-the-left frame
      const long = XF - xi > 0.6;
      const g = part('ds', `Drive shaft, ${long ? 'long' : 'short'} side`, 'gearbox', [0.15, -0.2, 0], { tags: ['ds'], mat: 'Steel shaft, CV joints, Hytrel boots', note: `Flange-type inner joint bolted to the gearbox, outer CV joint splined into the hub and held by the hub bolt (200 Nm + 180°, renew; clean the thread with a tap). Don’t let it hang on its inner joint. Boots: check for splits; clamps are renewed.${long ? ' The long shaft carries a vibration damper.' : ' The constructed gearbox sits further outboard than the real DQ400e, so this short shaft is drawn compact.'}` });
      const j0 = xi + 0.026, j1 = j0 + (long ? 0.034 : 0.026), bell0 = long ? 0.622 : 0.648, bell1 = 0.672;
      mesh(g, latheX([[0.014, j0], [0.046, j0], [0.048, j0 + 0.006], [0.048, j1 - 0.006], [0.036, j1], [0.016, j1]], 40).translate(0, C.y, C.z), M.steel);
      mesh(g, ringX(0.042, 0.049, j1 - 0.004, j1).translate(0, C.y, C.z), M.rubber);
      const bootIn0 = j1, bootIn1 = long ? j1 + 0.1 : bell0;
      mesh(g, gaiter(0.013, 0.036, 0, bootIn1 - bootIn0, long ? 6 : 2, 0.038, 0.013).rotateZ(-Math.PI / 2).translate(bootIn0, C.y, C.z), M.rubber);
      if (long) {
        const bo0 = bell0 - 0.078;
        mesh(g, cylX(0.0125, bootIn1 - 0.004, bo0 + 0.004).translate(0, C.y, C.z), M.shaft);
        mesh(g, latheX([[0.013, 0.17], [0.024, 0.176], [0.025, 0.226], [0.013, 0.232]], 28).translate(0, C.y, C.z), M.rubber);   // damper weight
        mesh(g, gaiter(0.013, 0.038, 0, 0.078, 6, 0.013, 0.036).rotateZ(-Math.PI / 2).translate(bo0, C.y, C.z), M.rubber);
        for (const x of [bootIn1 - 0.004, bo0 + 0.004]) mesh(g, ringX(0.0128, 0.0155, x - 0.004, x + 0.004).translate(0, C.y, C.z), M.zinc);
      }
      mesh(g, ringX(0.036, 0.04, bell0 + 0.002, bell0 + 0.01).translate(0, C.y, C.z), M.zinc);
      mesh(g, ringX(0.036, 0.04, j1 + 0.002, j1 + 0.01).translate(0, C.y, C.z), M.zinc);
      mesh(g, latheX([[0.03, bell0], [0.043, bell0 + 0.012], [0.046, bell0 + 0.03], [0.04, bell1 - 0.004], [0.024, bell1]], 40).translate(0, C.y, C.z), M.steel);   // outer CV bell
      mesh(g, cylX(0.0175, bell1, XF - 0.004).translate(0, C.y, C.z), M.shaft);    // splined stub, inside the bearing
    }

    /* ── fasteners ── */
    const fx = (id, host, fill) => fill(fset(id, host));
    fx('bolts_caliper', 'caliper', g => { for (const t of [-0.078, 0.078]) fastener(M, g, calPt(0.669, 0.15, t), 0.008, 0.04, '-x', { mat: M.zinc }); });
    fx('bolts_carrier', 'carrier', g => { for (const t of [-0.07, 0.07]) fastener(M, g, calPt(0.684, 0.105, t), 0.012, 0.032, '-x', { mat: M.black }); });   // through the housing lugs
    fx('screw_disc', 'disc', g => { const p = polar(0.04, Math.PI / 5); fastener(M, g, V(XF, C.y + p.y, C.z - p.x), 0.0055, 0.012, 'x', { socket: true, flange: false }); });
    fx('bolts_splash', 'splash', g => { for (const a of [THC + 1.6, THC + 3.1, THC + 4.6]) { const p = at(0.1, a); fastener(M, g, V(XF - 0.083, p.y, p.z), 0.006, 0.012, 'x', { socket: true }); } });
    fx('bolt_hub', 'ds', g => fastener(M, g, V(XF + 0.012, C.y, C.z), 0.016, 0.07, 'x', { mat: M.black }));
    fx('bolts_bearing', 'bearing', g => { for (let i = 0; i < 4; i++) { const p = polar(0.066, Math.PI / 4 + i * Math.PI / 2); fastener(M, g, V(0.686, C.y + p.y, C.z - p.x), 0.012, 0.04, '-x', { mat: M.black }); } });
    fx('bolt_abs', 'abs', g => { const sp = at(0.06, 0.7); fastener(M, g, V(0.669, sp.y + 0.024, sp.z), 0.006, 0.014, '-x', { socket: true }); });
    fx('bolt_banjo', 'hose', g => fastener(M, g, banjo.clone().setX(banjo.x - 0.005), 0.01, 0.022, '-x', { mat: M.yzinc }));
    fx('bolt_hosebracket', 'hose', g => fastener(M, g, hoseBr.clone().add(V(0.008, 0, 0)), 0.006, 0.014, 'x'));
    fx('bolt_strutclamp', 'strut', g => fastener(M, g, V(B.x - 0.036, B.y, B.z - 0.036), 0.012, 0.075, '-z', { endNut: true, mat: M.black }));
    fx('bolts_topmount', 'strut', g => { const s = new THREE.Object3D(); s.quaternion.copy(qA); s.position.copy(B); s.updateMatrixWorld(true);
      for (let i = 0; i < 3; i++) { const a = i / 3 * Math.PI * 2 + 0.5; fastener(M, g, V(Math.cos(a) * 0.058, 0.447, Math.sin(a) * 0.058).applyMatrix4(s.matrixWorld), 0.01, 0.03, 'y'); } });
    fx('nut_bj', 'bj', g => fastener(M, g, V(J.x, J.y + 0.035, J.z), 0.012, 0.012, 'y', { nut: true }));
    fx('nuts_bj', 'bj', g => { for (let i = 0; i < 3; i++) { const a = i / 3 * Math.PI * 2 + Math.PI / 6; fastener(M, g, V(J.x + Math.cos(a) * 0.034, 0.158, J.z - Math.sin(a) * 0.034), 0.01, 0.012, '-y', { nut: true }); } });
    fx('nut_tre', 'tre', g => fastener(M, g, V(E.x, E.y + 0.014, E.z), 0.012, 0.012, 'y', { nut: true }));
    fx('nuts_droplink', 'droplink', g => { fastener(M, g, dTop.clone().add(V(0, 0.0, 0)).setY(dTop.y + 0.018), 0.01, 0.012, 'y', { nut: true }); fastener(M, g, dBot.clone().setY(dBot.y - 0.012), 0.01, 0.012, '-y', { nut: true }); });
    fx('bolts_arm', 'arm', g => { fastener(M, g, V(F.x, F.y, F.z + 0.045), 0.012, 0.1, 'z', { endNut: true, mat: M.black }); fastener(M, g, V(Rb.x, Rb.y - 0.04, Rb.z), 0.012, 0.07, '-y', { mat: M.black }); });
    fx('bolts_dsflange', 'ds', g => { const xi = flanges[k] * sx + 0.026 + (XF - flanges[k] * sx > 0.6 ? 0.034 : 0.026); for (let i = 0; i < 6; i++) { const a = i / 6 * Math.PI * 2; fastener(M, g, V(xi + 0.001, C.y + Math.sin(a) * 0.036, C.z + Math.cos(a) * 0.036), 0.007, 0.04, 'x', { socket: true, flange: false, mat: M.black }); } });

    // mirror the left-hand build to the right
    if (sx < 0) for (const g of groups) g.scale.x = -1;
  }
  return out;
}
