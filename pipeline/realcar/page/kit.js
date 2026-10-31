// kit.js: the drawing kit shared by the parts pages: materials (with their cast, plastic and rubber surfaces)
// and the shapes parts are drawn from. Inlined into page/parts.html by the page writers.
const TAU = Math.PI * 2;

// ── materials ──
const mat = (color, roughness, metalness, extra = {}) => new THREE.MeshStandardMaterial({ color, roughness, metalness, ...extra });
// A real part's surface is not one flat colour. A noise in the part's own space (so it stays put when the part
// moves) gives a casting its sand grain, mottles its colour and shine, and leaves its machined faces smooth:
// GRAIN bumps per metre and how steep (DEPTH); MOTTLE patches per metre and how much they shade it (TINT);
// RUST a colour and how much of it; RMOT how much the patches change the shine; MACH how smooth a face is that
// looks straight up or down (a machined deck or joint face).
const SURF_PARS = /* glsl */`
varying vec3 vSP; varying vec3 vSN; varying vec3 vNM0; varying vec3 vNM1; varying vec3 vNM2;
uniform vec4 uGrain; uniform vec4 uRust; uniform vec2 uShine;
float sHash(vec3 p) { p = fract(p * 0.1031); p += dot(p, p.zyx + 31.32); return fract((p.x + p.y) * p.z); }
float sNoise(vec3 p) {
  vec3 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(sHash(i), sHash(i + vec3(1, 0, 0)), f.x), mix(sHash(i + vec3(0, 1, 0)), sHash(i + vec3(1, 1, 0)), f.x), f.y),
             mix(mix(sHash(i + vec3(0, 0, 1)), sHash(i + vec3(1, 0, 1)), f.x), mix(sHash(i + vec3(0, 1, 1)), sHash(i + vec3(1, 1, 1)), f.x), f.y), f.z);
}
// three octaves; an octave finer than a pixel fades out, so a far-off casting does not sparkle
float sFbm(vec3 p, float fw) {
  float a = 0.5, s = 0.0;
  for (int k = 0; k < 3; k++) { s += a * clamp(1.4 - fw, 0.0, 1.0) * (sNoise(p) - 0.5); p = p * 2.03 + 17.1; fw *= 2.03; a *= 0.5; }
  return s * 1.6;
}
`;
const surfaces = [];
function surf(m, o) {
  const u = { uGrain: { value: new THREE.Vector4(o.grain || 2000, o.depth || 0, o.mottle || 10, o.tint || 0) },
    uRust: { value: new THREE.Vector4(...new THREE.Color(o.rust ? o.rust[0] : 0).toArray(), o.rust ? o.rust[1] : 0) },
    uShine: { value: new THREE.Vector2(o.rmot || 0, o.mach || 0) } };
  m.userData.surf = u;
  m.onBeforeCompile = SURF_COMPILE;
  surfaces.push(m);
  return m;
}
function SURF_COMPILE(shader) {
  Object.assign(shader.uniforms, this.userData.surf);
  shader.vertexShader = shader.vertexShader
    .replace('#include <common>', '#include <common>\nvarying vec3 vSP; varying vec3 vSN; varying vec3 vNM0; varying vec3 vNM1; varying vec3 vNM2;')
    .replace('#include <begin_vertex>', '#include <begin_vertex>\nvSP = position; vSN = normal; vNM0 = normalMatrix[0]; vNM1 = normalMatrix[1]; vNM2 = normalMatrix[2];');
  shader.fragmentShader = shader.fragmentShader
    .replace('#include <common>', '#include <common>\n' + SURF_PARS)
    .replace('#include <color_fragment>', `#include <color_fragment>
      vec3 sFw = fwidth(vSP); float sPix = length(sFw);
      float sMot = sFbm(vSP * uGrain.z + 3.7, sPix * uGrain.z);
      float sMach = uShine.y * smoothstep(0.93, 0.995, abs(normalize(vSN).y));
      diffuseColor.rgb *= 1.0 + uGrain.w * sMot * 2.0 * (1.0 - sMach);
      diffuseColor.rgb = mix(diffuseColor.rgb, uRust.rgb, clamp(uRust.a * (0.6 + sMot * 3.5), 0.0, 1.0) * (1.0 - sMach));`)
    .replace('#include <roughnessmap_fragment>', `#include <roughnessmap_fragment>
      roughnessFactor = clamp(roughnessFactor * (1.0 - 0.5 * sMach) + uShine.x * sMot * 2.0, 0.06, 1.0);`)
    .replace('#include <normal_fragment_maps>', `#include <normal_fragment_maps>
      if (uGrain.y > 0.0) {
        vec3 sP = vSP * uGrain.x; float sF = sPix * uGrain.x, e = 0.3, h0 = sFbm(sP, sF);
        vec3 g = vec3(sFbm(sP + vec3(e, 0, 0), sF) - h0, sFbm(sP + vec3(0, e, 0), sF) - h0, sFbm(sP + vec3(0, 0, e), sF) - h0) / e;
        g *= uGrain.y * (1.0 - 0.85 * sMach);
        vec3 gv = mat3(vNM0, vNM1, vNM2) * g;
        normal = normalize(normal - (gv - dot(gv, normal) * normal));
      }`);
}
const M = {
  // grey cast iron, bare: the block, its caps
  iron: surf(mat(0x55585b, 0.76, 0.6), { grain: 1500, depth: 0.32, mottle: 9, tint: 0.2, rust: [0x5b3b27, 0.07], rmot: 0.22, mach: 0.9 }),
  ironDark: surf(mat(0x3f4245, 0.58, 0.65), { grain: 1700, depth: 0.2, mottle: 12, tint: 0.14, rmot: 0.18, mach: 0.85 }),
  // wrought or machined aluminium (the alternator's case), sand-cast aluminium (the head, covers, housings)
  alu: surf(mat(0xc5c8ca, 0.36, 0.88), { grain: 3200, depth: 0.05, mottle: 14, tint: 0.07, rmot: 0.12 }),
  aluCast: surf(mat(0xadafad, 0.56, 0.78), { grain: 1900, depth: 0.15, mottle: 10, tint: 0.13, rust: [0x6f6a5c, 0.06], rmot: 0.2, mach: 0.85 }),
  steel: surf(mat(0xaeb3b7, 0.34, 0.95), { grain: 4500, depth: 0.025, mottle: 22, tint: 0.05, rmot: 0.12 }),
  forged: surf(mat(0x6c7176, 0.4, 0.92), { grain: 2400, depth: 0.1, mottle: 16, tint: 0.14, rmot: 0.22, mach: 0.6 }),
  bolt: surf(mat(0x3a3d41, 0.42, 0.86), { grain: 5000, depth: 0.04, mottle: 30, tint: 0.1, rmot: 0.15 }),
  zinc: surf(mat(0xc2bfae, 0.34, 0.88), { grain: 5000, depth: 0.03, mottle: 30, tint: 0.08, rmot: 0.12 }),
  brass: mat(0xc9a066, 0.28, 0.9, { side: THREE.DoubleSide }),
  rubber: surf(mat(0x161719, 0.86, 0.0), { grain: 5200, depth: 0.08, mottle: 9, tint: 0.1, rmot: 0.08 }),
  seal: surf(mat(0x5a2f22, 0.7, 0.0), { grain: 5000, depth: 0.04, mottle: 20, tint: 0.08 }),
  gasket: surf(mat(0x5c6168, 0.4, 0.82), { grain: 4000, depth: 0.05, mottle: 18, tint: 0.1, rmot: 0.12 }),
  fibre: surf(mat(0x7a6650, 0.86, 0.05), { grain: 4500, depth: 0.12, mottle: 25, tint: 0.12 }),
  // black moulded plastic with its fine texture (the timing covers, caps)
  plastic: surf(mat(0x1c1e21, 0.6, 0.0), { grain: 7000, depth: 0.1, mottle: 6, tint: 0.06, rmot: 0.06 }),
  belt: surf(mat(0x141517, 0.82, 0.0), { grain: 6000, depth: 0.12, mottle: 10, tint: 0.08 }),
  chain: mat(0x8d949a, 0.35, 0.9),
  copper: surf(mat(0x8f5634, 0.5, 0.85), { grain: 4000, depth: 0.02, mottle: 25, tint: 0.12 }),
  filter: surf(mat(0x1f4d8c, 0.42, 0.3), { grain: 6000, depth: 0.02, mottle: 12, tint: 0.05 }),
  yellow: mat(0xe2b316, 0.5, 0.05),
  blackPaint: surf(mat(0x1f2124, 0.5, 0.35), { grain: 3000, depth: 0.05, mottle: 12, tint: 0.08, rmot: 0.1 }),
  piston: surf(mat(0xc3c7cb, 0.34, 0.78), { grain: 3000, depth: 0.04, mottle: 14, tint: 0.06 }),
  // hot cast iron, rusted: the exhaust manifold and the turbo's turbine housing
  rusty: surf(mat(0x433b36, 0.88, 0.5), { grain: 1300, depth: 0.32, mottle: 7, tint: 0.24, rust: [0x5e3f2b, 0.15], rmot: 0.12 }),
};
M.turbine = M.rusty;
// the big castings and covers: see-through in X-ray
const SHELL = [M.iron, M.aluCast, M.plastic, M.blackPaint];

// ── geometry helpers ──
const V2 = (x, y) => new THREE.Vector2(x, y);
const nonIdx = g => (g.index ? g.toNonIndexed() : g);
function merge(...gs) {
  const list = gs.flat().filter(Boolean).map(g => { const n = nonIdx(g); n.clearGroups(); return n; });
  const m = mergeGeometries(list, false);
  if (!m) throw new Error('merge failed');
  return m;
}
function cylX(r, len, x0 = 0, y = 0, z = 0, seg = 20, rb = r) {    // from x0 to x0 + len along x
  const g = new THREE.CylinderGeometry(r, rb, len, seg); g.rotateZ(-Math.PI / 2); g.translate(x0 + len / 2, y, z); return g;
}
function cylY(r, len, y0 = 0, x = 0, z = 0, seg = 20, rb = r) {
  const g = new THREE.CylinderGeometry(r, rb, len, seg); g.translate(x, y0 + len / 2, z); return g;
}
function cylZ(r, len, z0 = 0, x = 0, y = 0, seg = 20) {
  const g = new THREE.CylinderGeometry(r, r, len, seg); g.rotateX(Math.PI / 2); g.translate(x, y, z0 + len / 2); return g;
}
function box(w, h, d, x = 0, y = 0, z = 0) { const g = new THREE.BoxGeometry(w, h, d); g.translate(x, y, z); return g; }
function latheY(pts, seg = 24) { return new THREE.LatheGeometry(pts.map(([r, y]) => V2(Math.max(r, 1e-5), y)), seg); }
function latheX(pts, seg = 24) { const g = latheY(pts, seg); g.rotateZ(-Math.PI / 2); return g; }
function torusX(r, tube, x = 0, y = 0, z = 0, arc = TAU) {
  const g = new THREE.TorusGeometry(r, tube, 8, 36, arc); g.rotateY(Math.PI / 2); g.translate(x, y, z); return g;
}
function torusY(r, tube, x = 0, y = 0, z = 0) { const g = new THREE.TorusGeometry(r, tube, 8, 32); g.rotateX(Math.PI / 2); g.translate(x, y, z); return g; }
// a shape drawn in the world's (z, y) plane, extruded along x from x0
const dedupe = pts => pts.filter((p, i) => { const q = pts[(i + 1) % pts.length]; return Math.hypot(p[0] - q[0], p[1] - q[1]) > 1e-7; });
function zyShape(outline, holes = []) {
  const s = new THREE.Shape(dedupe(outline).map(([z, y]) => V2(-z, y)));
  for (const h of holes) { const p = new THREE.Path(); p.absarc(-h.z, h.y, h.r, 0, TAU, true); s.holes.push(p); }
  return s;
}
function extrudeX(shape, depth, x0 = 0, curveSegments = 20) {
  const g = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: false, curveSegments }); g.rotateY(Math.PI / 2); g.translate(x0, 0, 0); return g;
}
// a shape in the world's (x, z) plane, extruded up from y0
function xzShape(outline, holes = []) {
  const s = new THREE.Shape(dedupe(outline).map(([x, z]) => V2(x, -z)));
  for (const h of holes) { const p = new THREE.Path(); p.absarc(h.x, -h.z, h.r, 0, TAU, true); s.holes.push(p); }
  return s;
}
function extrudeY(shape, depth, y0 = 0, opts = {}) {
  const g = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: false, curveSegments: 20, ...opts }); g.rotateX(-Math.PI / 2); g.translate(0, y0, 0); return g;
}
const rect = (a0, b0, a1, b1) => [[a0, b0], [a1, b0], [a1, b1], [a0, b1]];
function arcPts(cz, cy, r, t0, t1, n = 16) {        // points on a circle in the (z, y) plane, z = cz + r cos t
  return Array.from({ length: n + 1 }, (_, k) => { const t = t0 + (t1 - t0) * k / n; return [cz + r * Math.cos(t), cy + r * Math.sin(t)]; });
}
function rrect(w, h, r, n = 5) {                      // a rounded rectangle about the origin
  const out = [];
  for (const [cx, cy, a] of [[w / 2 - r, h / 2 - r, 0], [-w / 2 + r, h / 2 - r, 90], [-w / 2 + r, -h / 2 + r, 180], [w / 2 - r, -h / 2 + r, 270]])
    for (let k = 0; k <= n; k++) { const t = (a + 90 * k / n) * Math.PI / 180; out.push([cx + r * Math.cos(t), cy + r * Math.sin(t)]); }
  return out;
}
class Helix extends THREE.Curve {
  constructor(r, h, turns) { super(); this.r = r; this.h = h; this.turns = turns; }
  getPoint(u, out = new THREE.Vector3()) { const a = u * this.turns * TAU; return out.set(this.r * Math.cos(a), this.h * u, this.r * Math.sin(a)); }
}
function springG(r, h, wire, turns) { return new THREE.TubeGeometry(new Helix(r, h, turns), Math.ceil(turns * 22), wire / 2, 6, false); }
function tubeG(points, r, seg = 40, rs = 10) {
  return new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points.map(p => new THREE.Vector3(...p))), seg, r, rs, false);
}
// a rubber hose along a smooth path, its ends closed (an open tube's end shows as a thin ribbon)
function hoseG(points, r, seg = 40, rs = 18) {
  const pts = new THREE.CatmullRomCurve3(points.map(p => new THREE.Vector3(...p))).getPoints(seg).map(v => v.toArray());
  return sweepG(pts, pts.map(() => r), rs, true);
}
// a hexagon prism along y with its top edge chamfered, as a spanner sees a bolt head or nut
const flat = g => { const n = g.toNonIndexed(); n.computeVertexNormals(); return n; };
function hexY(r, h, y0 = 0) {
  return flat(latheY([[0.0001, y0], [r, y0], [r, y0 + h - r * 0.16], [r * 0.84, y0 + h], [0.0001, y0 + h]], 6));
}
// a bolt along +y: its head on y 0..h, its washer under it, its shank down to -len
function boltG(len, d, head = 6, washer = true) {
  const hr = d * 0.86, hh = d * 0.65;
  const out = [head === 6 ? hexY(hr, hh) : flat(latheY([[0.0001, 0], [hr, 0], [hr, hh * 0.8], [hr * 0.8, hh], [0.0001, hh]], 12))];
  out.push(washer ? cylY(hr * 1.3, d * 0.13, -d * 0.13, 0, 0, 20) : cylY(hr * 1.12, d * 0.1, -d * 0.02, 0, 0, 20));
  out.push(cylY(d / 2, len, -len, 0, 0, 10));
  return merge(out);
}
function nutG(d) { return merge(hexY(d * 0.86, d * 0.8), cylY(d * 1.1, d * 0.12, -d * 0.12, 0, 0, 18)); }
// a slab in plan from y0 to y1 with every edge rounded by r (and rt top and bottom): its outline a rectangle
// x0..x1, z0..z1 with corners of radius rc; HOLES ({x, z, r}) through it come out at their size
function slabY(x0, z0, x1, z1, y0, y1, r, rc = r, holes = [], rt = r, seg = 3) {
  const w = x1 - x0 - 2 * r, d = z1 - z0 - 2 * r;
  const pts = rrect(w, d, Math.max(0.0002, rc - r), 4).map(([a, b]) => [a + (x0 + x1) / 2, b + (z0 + z1) / 2]);
  return extrudeY(xzShape(pts, holes.map(h => ({ ...h, r: h.r + r }))), Math.max(0.0002, y1 - y0 - 2 * rt), y0 + rt,
    { bevelEnabled: true, bevelThickness: rt, bevelSize: r, bevelSegments: seg, curveSegments: 18 });
}
// the same across x: a plate in the (z, y) plane from x0 to x1, its outline z0..z1, y0..y1
function slabX(x0, x1, z0, z1, y0, y1, r, rc = r, holes = []) {
  const w = z1 - z0 - 2 * r, h = y1 - y0 - 2 * r;
  const pts = rrect(w, h, Math.max(0.0002, rc - r), 4).map(([a, b]) => [a + (z0 + z1) / 2, b + (y0 + y1) / 2]);
  const g = new THREE.ExtrudeGeometry(zyShape(pts, holes.map(o => ({ ...o, r: o.r + r }))),
    { depth: Math.max(0.0002, x1 - x0 - 2 * r), bevelEnabled: true, bevelThickness: r, bevelSize: r, bevelSegments: 3, curveSegments: 18 });
  g.rotateY(Math.PI / 2); g.translate(x0 + r, 0, 0); return g;
}
// and along z: a pad in the (x, y) plane from z0 to z1
function slabZ(z0, z1, x0, x1, y0, y1, r, rc = r) {
  const pts = rrect(x1 - x0 - 2 * r, y1 - y0 - 2 * r, Math.max(0.0002, rc - r), 4);
  const s = new THREE.Shape(dedupe(pts).map(([a, b]) => V2(a + (x0 + x1) / 2, b + (y0 + y1) / 2)));
  const g = new THREE.ExtrudeGeometry(s, { depth: Math.max(0.0002, z1 - z0 - 2 * r), bevelEnabled: true, bevelThickness: r, bevelSize: r, bevelSegments: 3, curveSegments: 12 });
  return g.translate(0, 0, z0 + r);
}
// a tube along a path whose thickness changes: rings of RS points round each point of PTS ([x, y, z]), radius RADII[i]
function sweepG(pts, radii, rs = 16, capped = true) {
  const P = pts.map(p => new THREE.Vector3(...p)), n = P.length, pos = [], idx = [];
  let ref = new THREE.Vector3(1, 0, 0);
  const T = P.map((p, i) => P[Math.min(n - 1, i + 1)].clone().sub(P[Math.max(0, i - 1)]).normalize());
  if (Math.abs(T[0].dot(ref)) > 0.9) ref = new THREE.Vector3(0, 1, 0);
  let N0 = new THREE.Vector3().crossVectors(T[0], ref).normalize();
  for (let i = 0; i < n; i++) {
    if (i) { const B = new THREE.Vector3().crossVectors(T[i - 1], T[i]); if (B.length() > 1e-6) N0.applyAxisAngle(B.normalize(), Math.acos(Math.min(1, Math.max(-1, T[i - 1].dot(T[i]))))); }
    const B2 = new THREE.Vector3().crossVectors(T[i], N0).normalize();
    for (let k = 0; k < rs; k++) { const a = k / rs * TAU, v = N0.clone().multiplyScalar(Math.cos(a)).add(B2.clone().multiplyScalar(Math.sin(a))).multiplyScalar(radii[i]).add(P[i]); pos.push(v.x, v.y, v.z); }
  }
  for (let i = 0; i < n - 1; i++) for (let k = 0; k < rs; k++) {
    const a = i * rs + k, b = i * rs + (k + 1) % rs, c = a + rs, d = b + rs; idx.push(a, c, b, b, c, d);
  }
  if (capped) for (const [i, s] of [[0, -1], [n - 1, 1]]) {
    const c = pos.length / 3; pos.push(...P[i].toArray());
    for (let k = 0; k < rs; k++) { const a = i * rs + k, b = i * rs + (k + 1) % rs; if (s > 0) idx.push(c, a, b); else idx.push(c, b, a); }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(new Array(pos.length / 3 * 2).fill(0), 2));
  g.setIndex(idx); g.computeVertexNormals();
  return g;
}
// a turbo's scroll (volute) about the x axis at X: it winds once round, from radius r0 and tube t0 to r1 and t1
function voluteG(x, y, z, r0, r1, t0, t1, a0 = 0, turn = 0.92, steps = 40) {
  const pts = [], radii = [];
  for (let k = 0; k <= steps; k++) {
    const f = k / steps, a = a0 + f * turn * TAU, rr = r0 + (r1 - r0) * f;
    pts.push([x, y + rr * Math.sin(a), z + rr * Math.cos(a)]); radii.push(t0 + (t1 - t0) * f);
  }
  return sweepG(pts, radii, 18);
}
// a toothed pulley about the x axis: TEETH teeth on radius r, width w, centred on x 0; a sintered sprocket's
// rim, a thinner web with HOLES lightening holes, and its hub
function sprocketG(r, teeth, w, holes = 0) {
  const pts = [];
  for (let i = 0; i < teeth; i++) {
    const a = i / teeth * TAU, s = TAU / teeth;
    for (const [f, rr] of [[0, r * 0.94], [0.12, r * 0.955], [0.26, r], [0.56, r], [0.7, r * 0.955], [0.84, r * 0.94]]) pts.push([rr * Math.cos(a + f * s), rr * Math.sin(a + f * s)]);
  }
  if (r < 0.04) {                      // a small one is solid
    return merge(extrudeX(zyShape(pts, [{ z: 0, y: 0, r: r * 0.24 }]), w, -w / 2, 6), latheX([[r * 0.24, -w * 0.75], [r * 0.42, -w * 0.75], [r * 0.46, -w * 0.6], [r * 0.46, w * 0.6], [r * 0.24, w * 0.6]], 24));
  }
  const ring = extrudeX(zyShape(pts, [{ z: 0, y: 0, r: r * 0.8 }]), w, -w / 2, 6);
  const hs = [{ z: 0, y: 0, r: r * 0.16 }];
  for (let k = 0; k < holes; k++) { const a = k / holes * TAU + 0.3; hs.push({ z: r * 0.56 * Math.cos(a), y: r * 0.56 * Math.sin(a), r: r * 0.15 }); }
  const web = extrudeX(zyShape(arcPts(0, 0, r * 0.81, 0, TAU, 48).slice(0, -1), hs), w * 0.36, -w * 0.18, 16);
  const hub = latheX([[r * 0.16, -w * 0.72], [r * 0.3, -w * 0.72], [r * 0.33, -w * 0.62], [r * 0.33, w * 0.5], [r * 0.16, w * 0.5]], 32);
  const lip = latheX([[r * 0.78, -w * 0.5], [r * 0.83, -w * 0.5], [r * 0.83, w * 0.5], [r * 0.78, w * 0.5]], 48);
  return merge(ring, web, hub, lip);
}
// a poly-V (ribbed) pulley about x: radius r, RIBS grooves
function ribbedG(r, w, ribs = 5, hub = 0.4) {
  const pts = [[r * hub, -w / 2], [r * 1.04, -w / 2]];
  const step = w / (ribs + 1);
  for (let k = 0; k < ribs; k++) { const y = -w / 2 + step * (k + 0.5); pts.push([r, y], [r * 0.955, y + step / 2]); }
  pts.push([r, w / 2 - step / 2], [r * 1.04, w / 2], [r * hub, w / 2]);
  return latheX(pts, 48);
}
function convexHull(pts) {
  const p = pts.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lo = [], up = [];
  for (const q of p) { while (lo.length >= 2 && cross(lo[lo.length - 2], lo[lo.length - 1], q) <= 0) lo.pop(); lo.push(q); }
  for (const q of p.slice().reverse()) { while (up.length >= 2 && cross(up[up.length - 2], up[up.length - 1], q) <= 0) up.pop(); up.push(q); }
  return lo.slice(0, -1).concat(up.slice(0, -1));
}

// ── belts and chains: a closed path round pulleys in the (z, y) plane, counter-clockwise; a pulley the belt's
//    back runs on (a tensioner, an idler) has a negative radius ──
function beltPath(pulleys) {
  const n = pulleys.length, leave = [];
  for (let i = 0; i < n; i++) {
    const a = pulleys[i], b = pulleys[(i + 1) % n];
    const dz = b.z - a.z, dy = b.y - a.y, d = Math.hypot(dz, dy), ph = Math.atan2(dy, dz);
    const c = Math.acos(Math.max(-1, Math.min(1, (a.r - b.r) / d)));
    let best = null;
    for (const s of [1, -1]) {
      const t = ph + s * c, nz = Math.cos(t), ny = Math.sin(t);
      const p1 = [a.z + a.r * nz, a.y + a.r * ny], p2 = [b.z + b.r * nz, b.y + b.r * ny];
      if ((p2[0] - p1[0]) * -ny + (p2[1] - p1[1]) * nz > 0) best = t;
    }
    leave.push(best);
  }
  const pts = [];
  for (let i = 0; i < n; i++) {
    const p = pulleys[i]; let a0 = leave[(i - 1 + n) % n], a1 = leave[i];
    if (p.r > 0) { while (a1 < a0) a1 += TAU; } else { while (a1 > a0) a1 -= TAU; }
    const steps = Math.max(2, Math.ceil(Math.abs(a1 - a0) / 0.06));
    for (let k = 0; k <= steps; k++) { const a = a0 + (a1 - a0) * k / steps; pts.push([p.z + p.r * Math.cos(a), p.y + p.r * Math.sin(a)]); }
  }
  // evenly spaced
  const len = [0];
  for (let i = 1; i <= pts.length; i++) { const a = pts[i - 1], b = pts[i % pts.length]; len.push(len[i - 1] + Math.hypot(b[0] - a[0], b[1] - a[1])); }
  const total = len[len.length - 1], ds = 0.0025, out = [];
  let j = 0;
  for (let s = 0; s < total; s += ds) {
    while (len[j + 1] < s) j++;
    const a = pts[j], b = pts[(j + 1) % pts.length], f = (s - len[j]) / Math.max(1e-9, len[j + 1] - len[j]);
    out.push([a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f]);
  }
  return { pts: out, total };
}
// the belt: a band WIDTH wide and THICK thick on the path's outside, TEETH every pitch on its inside (or ribs)
function beltG(path, x, width, thick, teeth = 0.0095, ribs = 0) {
  const P2 = path.pts, n = P2.length, pos = [];
  const frame = i => {
    const a = P2[(i - 1 + n) % n], b = P2[(i + 1) % n], tz = b[0] - a[0], ty = b[1] - a[1], l = Math.hypot(tz, ty);
    return { t: [tz / l, ty / l], o: [ty / l, -tz / l] };   // tangent; outward normal (the loop is counter-clockwise)
  };
  const quad = (A, B, C, Dd) => pos.push(...A, ...B, ...C, ...A, ...C, ...Dd);
  for (let i = 0; i < n; i++) {
    const i2 = (i + 1) % n, f1 = frame(i), f2 = frame(i2), p1 = P2[i], p2 = P2[i2];
    const in1 = [p1[0], p1[1]], out1 = [p1[0] + f1.o[0] * thick, p1[1] + f1.o[1] * thick];
    const in2 = [p2[0], p2[1]], out2 = [p2[0] + f2.o[0] * thick, p2[1] + f2.o[1] * thick];
    const v = (zy, xx) => [xx, zy[1], zy[0]];
    const x0 = x - width / 2, x1 = x + width / 2;
    quad(v(out1, x0), v(out2, x0), v(out2, x1), v(out1, x1));      // back
    quad(v(in1, x1), v(in2, x1), v(in2, x0), v(in1, x0));          // inside
    quad(v(in1, x0), v(in2, x0), v(out2, x0), v(out1, x0));        // edges
    quad(v(out1, x1), v(out2, x1), v(in2, x1), v(in1, x1));
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(new Array(pos.length / 3 * 2).fill(0), 2));
  g.computeVertexNormals();
  const parts = [g];
  if (teeth) {
    const every = Math.max(1, Math.round(teeth / 0.0025));
    for (let i = 0; i < n; i += every) {
      const f = frame(i), p = P2[i], tb = new THREE.BoxGeometry(width, thick * 0.9, teeth * 0.45);
      tb.rotateX(Math.atan2(-f.t[1], f.t[0]));
      tb.translate(x, p[1] - f.o[1] * thick * 0.45, p[0] - f.o[0] * thick * 0.45);
      parts.push(tb);
    }
  }
  for (let k = 0; k < ribs; k++) {
    const xr = x - width / 2 + width * (k + 0.5) / ribs, rib = [];
    // a rib: a narrow band on the inside
    for (let i = 0; i < n; i += 2) {
      const f = frame(i), p = P2[i], tb = new THREE.BoxGeometry(width / ribs * 0.55, thick * 0.6, 0.0055);
      tb.rotateX(Math.atan2(-f.t[1], f.t[0]));
      tb.translate(xr, p[1] - f.o[1] * thick * 0.3, p[0] - f.o[0] * thick * 0.3);
      rib.push(tb);
    }
    parts.push(merge(rib));
  }
  return merge(parts);
}
function chainG(path, x, pitch = 0.008) {
  const P2 = path.pts, n = P2.length, every = Math.max(1, Math.round(pitch / 0.0025)), parts = [];
  for (let i = 0; i < n; i += every) {
    const a = P2[(i - 1 + n) % n], b = P2[(i + 1) % n], ang = Math.atan2(-(b[1] - a[1]), b[0] - a[0]), p = P2[i];
    for (const dx of [-0.0045, 0.0045]) { const pl = new THREE.BoxGeometry(0.0012, 0.0065, pitch * 1.25); pl.rotateX(ang); pl.translate(x + dx, p[1], p[0]); parts.push(pl); }
    parts.push(cylX(0.0022, 0.009, x - 0.0045, p[1], p[0], 8));
  }
  return merge(parts);
}
