// kit.mjs — what the bikes modelled in code share (cruiser.mjs, sports.mjs,
// scooter.mjs): the command line, the geometry helpers, the materials, the
// cast wheel and tyre, and the writer that turns a list of pieces into a
// glTF with one pivot node per moving part, every piece its own named node
// (with --parts) and the baked clips.
//
// Frame: +Y up, nose +Z, the rider's left +X, metres, ground at y = 0.
// ExpertCarCheck. Proprietary: see ../LICENSE.
import * as THREE from 'three';
import { mergeGeometries, mergeVertices } from 'three/addons/utils/BufferGeometryUtils.js';
import { Document, NodeIO } from '@gltf-transform/core';
import { KHRMaterialsClearcoat, KHRMaterialsEmissiveStrength } from '@gltf-transform/extensions';

// ── the command line: out.glb [--paint=#hex] [--name=...] [--parts] ─────
export function cli(usage) {
  const args = Object.fromEntries(process.argv.slice(3).filter(a => a.startsWith('--')).map(a => {
    const [k, ...v] = a.slice(2).split('='); return [k, v.join('=') || true];
  }));
  const out = process.argv[2];
  if (!out) { console.error(usage); process.exit(2); }
  return { out, args };
}

// ── geometry ─────────────────────────────────────────────────────────────
export const V = (x, y, z) => new THREE.Vector3(x, y, z);
export const UPY = V(0, 1, 0);

export function along(g, p0, p1) {                // a Y-axis primitive laid from p0 to p1
  const d = p1.clone().sub(p0), L = d.length();
  g.scale(1, L / (g.userData.h || 1), 1);
  g.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(UPY, d.normalize()));
  g.translate(...p0.clone().add(p1).multiplyScalar(0.5).toArray());
  return g;
}
export const rod = (p0, p1, r, seg = 20, r1 = r) => {
  const g = new THREE.CylinderGeometry(r1, r, 1, seg, 1, false); g.userData.h = 1; return along(g, p0, p1);
};
export const tube = (pts, r, seg = 64, rad = 14) => new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), seg, r, rad, false);
export const ball = (p, r, sx = 1, sy = 1, sz = 1) => { const g = new THREE.SphereGeometry(r, 24, 16); g.scale(sx, sy, sz); g.translate(p.x, p.y, p.z); return g; };
// a body of revolution about the X axis (the axles), from a (radius, along-x) profile
export function aroundX(profile, cx, cy, cz, seg = 72, phi0 = 0, phiL = Math.PI * 2) {
  const g = new THREE.LatheGeometry(profile.map(([r, a]) => new THREE.Vector2(r, a)), seg, phi0, phiL);
  g.rotateZ(-Math.PI / 2);                        // lathe axis Y -> X
  g.translate(cx, cy, cz);
  return g;
}
export function roundedBox(w, h, d, r, at) {      // w along x, h along y, d along z
  const s = new THREE.Shape(), x = d / 2 - r, y = h / 2 - r;
  s.moveTo(-x, -h / 2); s.lineTo(x, -h / 2); s.quadraticCurveTo(d / 2, -h / 2, d / 2, -y);
  s.lineTo(d / 2, y); s.quadraticCurveTo(d / 2, h / 2, x, h / 2); s.lineTo(-x, h / 2);
  s.quadraticCurveTo(-d / 2, h / 2, -d / 2, y); s.lineTo(-d / 2, -y); s.quadraticCurveTo(-d / 2, -h / 2, -x, -h / 2);
  const g = new THREE.ExtrudeGeometry(s, { depth: w - 2 * r, bevelEnabled: true, bevelThickness: r, bevelSize: r * 0.9, bevelSegments: 4, curveSegments: 10 });
  g.translate(0, 0, -(w - 2 * r) / 2); g.rotateY(Math.PI / 2);      // extrusion along x
  g.translate(at.x, at.y, at.z);
  return g;
}
// a side panel: a closed outline of (z, y) points, `w` thick across and
// rounded at its edges, its inner face `x0` from the middle on the left
// (sign +1) or the right (sign -1)
export function sidePanel(outline, x0, w, sign, bevel = 0.008) {
  const s = new THREE.Shape(outline.map(([z, y]) => new THREE.Vector2(z, y)));
  const g = new THREE.ExtrudeGeometry(s, { depth: Math.max(w - 2 * bevel, 0.001), bevelEnabled: true, bevelThickness: bevel,
    bevelSize: bevel * 0.9, bevelSegments: 3, curveSegments: 16 });
  g.rotateY(-Math.PI / 2);                        // shape x -> world z; the extrusion runs bevel .. -(w - bevel) in x
  g.translate(sign > 0 ? x0 + w - bevel : -x0 - bevel, 0, 0);
  return g;
}
// a body from a run of cross-sections along z: each section a super-
// ellipse of half width w, top yt and bottom yb at z, centred at x (u in
// 0..1), or the arc of it from angle a0 to a1 (0 is the left, +X; a
// fairing's side panel); `caps` closes both ends (a tank, a seat)
export function lofted(section, nu = 48, nv = 40, caps = false) {
  const pos = [], idx = [];
  for (let i = 0; i <= nu; i++) {
    const { z, w, yt, yb, e = 0.6, x = 0, a0 = 0, a1 = Math.PI * 2 } = section(i / nu);
    const yc = (yt + yb) / 2, h = (yt - yb) / 2;
    for (let j = 0; j <= nv; j++) {
      const a = a0 + (a1 - a0) * j / nv, c = Math.cos(a), s = Math.sin(a);
      pos.push(x + w * Math.sign(c) * Math.abs(c) ** e, yc + h * Math.sign(s) * Math.abs(s) ** e, z);
    }
  }
  for (let i = 0; i < nu; i++) for (let j = 0; j < nv; j++) {
    const a = i * (nv + 1) + j, b = a + nv + 1;
    idx.push(a, b, a + 1, b, b + 1, a + 1);
  }
  if (caps) {
    for (const [i, flip] of [[0, true], [nu, false]]) {
      const c0 = pos.length / 3, ring = i * (nv + 1);
      let cx = 0, cy = 0, cz = 0;
      for (let j = 0; j < nv; j++) { cx += pos[3 * (ring + j)]; cy += pos[3 * (ring + j) + 1]; cz += pos[3 * (ring + j) + 2]; }
      pos.push(cx / nv, cy / nv, cz / nv);
      for (let j = 0; j < nv; j++) flip ? idx.push(c0, ring + j + 1, ring + j) : idx.push(c0, ring + j, ring + j + 1);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setIndex(idx); g.computeVertexNormals();
  return g;
}
// a box beam from p0 to p1 (both at the same x: a swingarm's arm), w across,
// h deep, its corners rounded
export function beam(p0, p1, w, h, r = 0.008) {
  const d = p1.clone().sub(p0), L = d.length();
  const g = roundedBox(w, h, L, Math.min(r, h / 2 - 1e-3, w / 2 - 1e-3), V(0, 0, 0));
  g.rotateX(Math.atan2(-d.y, d.z));
  const m = p0.clone().add(p1).multiplyScalar(0.5); g.translate(m.x, m.y, m.z);
  return g;
}
// a toothed wheel's outline in the (z, y) plane round (cz, cy): n teeth
export function sprocketOutline(cz, cy, r, n, depth = 0.006) {
  const pts = [];
  for (let k = 0; k < n * 4; k++) {
    const a = 2 * Math.PI * k / (n * 4), rr = k % 4 < 2 ? r : r - depth;
    pts.push([cz + rr * Math.cos(a), cy + rr * Math.sin(a)]);
  }
  return pts;
}
// a coil spring round the line p0 -> p1: radius rc, wire r, turns
export function helix(p0, p1, rc, r, turns) {
  const d = p1.clone().sub(p0), L = d.length(), ax = d.clone().normalize();
  const u = Math.abs(ax.x) < 0.9 ? V(1, 0, 0) : V(0, 1, 0);
  const e1 = u.clone().cross(ax).normalize(), e2 = ax.clone().cross(e1);
  const pts = [], n = Math.round(turns * 24);
  for (let i = 0; i <= n; i++) {
    const t = i / n, a = 2 * Math.PI * turns * t;
    pts.push(p0.clone().addScaledVector(ax, L * t).addScaledVector(e1, rc * Math.cos(a)).addScaledVector(e2, rc * Math.sin(a)));
  }
  return tube(pts, r, n * 2, 8);
}
// a rounded-rectangle section (w across x, h tall) swept along a path of
// points (a twin-spar frame's beams)
export function sweptBox(pts, w, h, steps = 80) {
  const s = new THREE.Shape(), r = Math.min(w, h) * 0.25;
  s.moveTo(-w / 2 + r, -h / 2); s.lineTo(w / 2 - r, -h / 2); s.quadraticCurveTo(w / 2, -h / 2, w / 2, -h / 2 + r);
  s.lineTo(w / 2, h / 2 - r); s.quadraticCurveTo(w / 2, h / 2, w / 2 - r, h / 2); s.lineTo(-w / 2 + r, h / 2);
  s.quadraticCurveTo(-w / 2, h / 2, -w / 2, h / 2 - r); s.lineTo(-w / 2, -h / 2 + r); s.quadraticCurveTo(-w / 2, -h / 2, -w / 2 + r, -h / 2);
  return new THREE.ExtrudeGeometry(s, { steps, bevelEnabled: false, extrudePath: new THREE.CatmullRomCurve3(pts) });
}

// ── materials ────────────────────────────────────────────────────────────
export const hex = h => { const c = new THREE.Color(h); return [c.r, c.g, c.b]; };   // sRGB in, linear out

// ── tyres and cast wheels ────────────────────────────────────────────────
// tyre sizes to metres: [width mm, aspect %] on a rim of `rim` inches
export const tyreOf = (rim, [w, ar]) => ({ R: rim * 0.0254 / 2 + w * ar / 100 / 1000, W: w / 1000, RIM_R: rim * 0.0254 / 2 });
// the tyre: a rounded section from one bead over the crown to the other
// (a motorbike tyre's crown is round: it leans on it)
export function tyreGeometry(A, T, round = 2 / 3.2, seg = 96) {
  const rIn = T.RIM_R - 0.004, rc = (rIn + T.R) / 2, hr = (T.R - rIn) / 2, ha = T.W / 2;
  // from the bead up the sidewall (a spoked wheel shows it all), over the crown, down to the other bead
  const prof = [[rIn, -0.80 * ha], [rIn + 0.45 * (rc - rIn), -0.95 * ha]];
  for (let i = 0; i <= 40; i++) {
    const th = -Math.PI / 2 + Math.PI * i / 40;
    const c = Math.cos(th), s = Math.sin(th);
    const r = rc + hr * Math.sign(c) * Math.abs(c) ** round;
    const a = ha * Math.sign(s) * Math.abs(s) ** round * (0.86 + 0.14 * (r - rIn) / (2 * hr));
    prof.push([Math.max(r, rIn), a]);
  }
  prof.push([rIn + 0.45 * (rc - rIn), 0.95 * ha], [rIn, 0.80 * ha]);
  return aroundX(prof, A.x, A.y, A.z, seg);
}
// a cast wheel: hub, rim (two flanges and the well) and `n` spokes, each a
// swept bar from the hub to the rim (split in two when `split`, the sports
// bike's Y-spokes); returns [hub, rim, spokes] geometries
export function castWheel(A, T, rimHalf, n, split = false, hubR = 0.055, hubHalf = rimHalf * 0.8) {
  const R = T.RIM_R;
  const rim = aroundX([[R - 0.022, -rimHalf], [R + 0.006, -rimHalf], [R + 0.010, -rimHalf + 0.006], [R - 0.004, -rimHalf + 0.012],
    [R - 0.014, -rimHalf * 0.4], [R - 0.016, 0], [R - 0.014, rimHalf * 0.4], [R - 0.004, rimHalf - 0.012],
    [R + 0.010, rimHalf - 0.006], [R + 0.006, rimHalf], [R - 0.022, rimHalf]], A.x, A.y, A.z, 96);
  const hub = aroundX([[0.012, -hubHalf], [hubR, -hubHalf], [hubR + 0.006, -hubHalf * 0.6], [hubR + 0.006, hubHalf * 0.6],
    [hubR, hubHalf], [0.012, hubHalf]], A.x, A.y, A.z, 48);
  const spokes = [];
  for (let k = 0; k < n; k++) {
    for (const off of split ? [-0.10, 0.10] : [0]) {
      const a0 = 2 * Math.PI * k / n, a1 = a0 + off;
      const p0 = V(A.x, A.y + (hubR + 0.004) * Math.sin(a0), A.z + (hubR + 0.004) * Math.cos(a0));
      const pm = V(A.x, A.y + (R * 0.55) * Math.sin(a0 + off * 0.4), A.z + (R * 0.55) * Math.cos(a0 + off * 0.4));
      const p1 = V(A.x, A.y + (R - 0.016) * Math.sin(a1), A.z + (R - 0.016) * Math.cos(a1));
      const g = tube([p0, pm, p1], split ? 0.0085 : 0.012, 16, 10);
      // flatten across the wheel: a cast spoke is wider than it is thick
      const pos = g.attributes.position;
      for (let i = 0; i < pos.count; i++) pos.setX(i, A.x + (pos.getX(i) - A.x) * (split ? 1.4 : 1.6));
      g.computeVertexNormals();
      spokes.push(g);
    }
  }
  return [hub, rim, mergeGeometries(spokes, false)];
}
// a brake disc about the axle at x, with its carrier ring (drilled look by a
// ring of small bosses)
export function brakeDisc(A, x, rOut, rIn, t = 0.0025) {
  return aroundX([[rIn, -t], [rOut, -t], [rOut, t], [rIn, t]], x, A.y, A.z, 96);
}

// ── the writer ───────────────────────────────────────────────────────────
// pieces: [part, material, geometry (world space), piece name]; pivots:
// {part: world point}; parents: {part: parent part or null}; order: the
// pivots in the order their nodes are made; meshOrder: the parts in the
// order their meshes are written; clips(nodes, clip, q): makes the clips;
// pivotExtras: {part: extras} (a hinge's axis and angle, as a car's)
export async function writeBike({ out, sceneName, extras, mats: MATS, pieces, pivots, parents, order, meshOrder,
  split, pieceName, clips, copyright, doubleSided = [], pivotExtras = {}, scale = 1 }) {
  const doc = new Document();
  const buf = doc.createBuffer();
  const clear = doc.createExtension(KHRMaterialsClearcoat);
  const glow = doc.createExtension(KHRMaterialsEmissiveStrength);
  const mats = {};
  for (const [k, m] of Object.entries(MATS)) {
    const mt = doc.createMaterial(k).setBaseColorFactor([...m.color, m.alpha ?? 1]).setMetallicFactor(m.metal).setRoughnessFactor(m.rough);
    if (m.alpha !== undefined && m.alpha < 1) mt.setAlphaMode('BLEND');
    if (k === 'mirror' || k === 'lamp' || k === 'red_lens' || k === 'amber_lens') mt.setDoubleSided(true);
    if (k === 'paint' || k === 'leather' || doubleSided.includes(k)) mt.setDoubleSided(true);
    if (m.clearcoat) mt.setExtension('KHR_materials_clearcoat', clear.createClearcoat().setClearcoatFactor(1).setClearcoatRoughnessFactor(0.04));
    if (m.emissive) {
      mt.setEmissiveFactor(m.emissive);
      if (m.strength > 1) mt.setExtension('KHR_materials_emissive_strength', glow.createEmissiveStrength().setEmissiveStrength(m.strength));
    }
    mats[k] = mt;
  }
  const clean = g => {                              // position + normal only, indexed
    let x = g.index ? g : mergeVertices(g, 1e-6);
    for (const a of Object.keys(x.attributes)) if (a !== 'position' && a !== 'normal') x.deleteAttribute(a);
    if (!x.attributes.normal) x.computeVertexNormals();
    return x;
  };
  const scene = doc.createScene(sceneName);
  // SCALE (--scale on the command line): the whole bike to another bike's
  // wheelbase, on the root node, so a preset serves bikes of its kind near
  // its size; the sizes it reports are scaled with it
  if (scale !== 1) extras = { ...Object.fromEntries(Object.entries(extras).map(([k, v]) => [k, k.endsWith('_m') && typeof v === 'number' ? +(v * scale).toFixed(3) : v])),
    scaled: +scale.toFixed(4) };
  const root = doc.createNode(sceneName).setExtras(extras);
  if (scale !== 1) root.setScale([scale, scale, scale]);
  scene.addChild(root);
  const nodes = { body: root };
  const worldPivot = p => pivots[p] || V(0, 0, 0);
  for (const p of order) {
    const parent = parents[p] ? nodes[parents[p]] : root;
    const rel = worldPivot(p).clone().sub(parents[p] ? worldPivot(parents[p]) : V(0, 0, 0));
    const n = doc.createNode(p).setTranslation(rel.toArray());
    if (pivotExtras[p]) n.setExtras(pivotExtras[p]);
    parent.addChild(n);
    nodes[p] = n;
  }
  let tris = 0;
  for (const part of meshOrder) {
    const subs = split ? [...new Set(pieces.filter(p => p[0] === part).map(p => p[3]))] : [undefined];
    for (const sub of subs) {
      const byMat = {};
      for (const [pp, m, g, ss] of pieces) if (pp === part && (!split || ss === sub)) (byMat[m] ||= []).push(clean(g));
      if (!Object.keys(byMat).length) continue;
      const off = part === 'body' ? V(0, 0, 0) : worldPivot(part);
      const name = split ? pieceName(part, sub || part) : part;
      const mesh = doc.createMesh(name);
      for (const [m, gs] of Object.entries(byMat)) {
        const g = mergeGeometries(gs, false); g.translate(-off.x, -off.y, -off.z);
        const pos = doc.createAccessor().setArray(new Float32Array(g.attributes.position.array)).setType('VEC3').setBuffer(buf);
        const nor = doc.createAccessor().setArray(new Float32Array(g.attributes.normal.array)).setType('VEC3').setBuffer(buf);
        const idx = doc.createAccessor().setArray(new Uint32Array(g.index.array)).setType('SCALAR').setBuffer(buf);
        tris += g.index.count / 3;
        mesh.addPrimitive(doc.createPrimitive().setAttribute('POSITION', pos).setAttribute('NORMAL', nor).setIndices(idx).setMaterial(mats[m]));
      }
      const holder = split ? doc.createNode(name) : part === 'body' ? doc.createNode('body') : doc.createNode(part + '_mesh');
      holder.setMesh(mesh);
      if (split) holder.setExtras({ moves_with: part });
      (part === 'body' ? root : nodes[part]).addChild(holder);
    }
  }
  const q = (axis, deg) => new THREE.Quaternion().setFromAxisAngle(axis.clone().normalize(), THREE.MathUtils.degToRad(deg)).toArray();
  const clip = (name, channels) => {
    const a = doc.createAnimation(name);
    for (const [node, times, values, path = 'rotation'] of channels) {
      const s = doc.createAnimationSampler()
        .setInput(doc.createAccessor().setArray(new Float32Array(times)).setType('SCALAR').setBuffer(buf))
        .setOutput(doc.createAccessor().setArray(new Float32Array(values.flat())).setType(path === 'rotation' ? 'VEC4' : 'VEC3').setBuffer(buf))
        .setInterpolation('LINEAR');
      a.addSampler(s).addChannel(doc.createAnimationChannel().setTargetNode(node).setTargetPath(path).setSampler(s));
    }
  };
  clips(nodes, clip, q);
  doc.getRoot().getAsset().copyright = copyright;
  await new NodeIO().registerExtensions([KHRMaterialsClearcoat, KHRMaterialsEmissiveStrength]).write(out, doc);
  return { tris };
}
