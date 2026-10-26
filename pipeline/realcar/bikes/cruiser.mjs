// cruiser.mjs — a heavy cruiser motorbike modelled in code (three.js geometry,
// written as glTF by gltf-transform): no downloaded model, no Blender, so the
// file is wholly ExpertCarCheck's. Its sizes are a real bike's published
// figures (the FATBOY preset: wheelbase, length, rake, trail, tyre sizes,
// seat height); its parts move:
//   wheels_spin   both wheels turn (a loop)
//   steer_left    the bars, fork, lamp and front wheel turn about the
//   steer_right   steering axis (raked, as the real one is)
//   stand_down    the side stand swings down
// With --bagger it is a touring bike instead (an Electra Glide's kind): the
// TOURING chassis's figures, hard panniers and its fairing: --bagger=batwing
// (a fairing on the fork), sharknose (on the frame, twin lamps) or screen (a
// windscreen over the lamp nacelle, passing lamps); --tourpak adds a top box,
// --lowers the leg shields, --wheels=19 the 19/18 in wheels (else 17/16).
// With --parts every piece is its own named node (frame, swingarm, engine
// parts, exhaust, tank, seat, mudguards, fork, bars, tyres, rims, discs,
// calipers...), each under the pivot it moves with, so a trainer can take
// any one off. Without it the output is as before: body, steer, two wheels
// and the stand.
// No maker's badge or lettering is modelled.
//
//   node pipeline/realcar/bikes/cruiser.mjs out.glb [--paint=#101012] [--name="..."] [--parts]
//        [--bagger=batwing|sharknose|screen [--tourpak] [--lowers] [--wheels=17|19]]
//
// Frame: +Y up, nose +Z, the rider's left +X, metres, ground at y = 0
// (the machine's rig frame).
// ExpertCarCheck. Proprietary: see ../LICENSE.
import * as THREE from 'three';
import { ParametricGeometry } from 'three/addons/geometries/ParametricGeometry.js';
import { cli, V, UPY, rod, tube, ball, aroundX, roundedBox, sidePanel, lofted, hex, writeBike } from './kit.mjs';

// ── the bike's figures ───────────────────────────────────────────────────
// a 2018-on 114 cu in heavy cruiser of the Fat Boy kind, from the maker's
// published specification: 1,665 mm wheelbase, 2,370 mm long, 30 deg rake,
// 132 mm trail, 675 mm seat, 160/60R18 front and 240/40R18 rear tyres
export const FATBOY = {
  name: 'Heavy cruiser (Fat Boy-style)', wheelbase: 1.665, length: 2.370, rake: 30, trail: 0.132,
  seat: 0.675, rim: 18, front_tyre: [160, 60], rear_tyre: [240, 40],
};

// Harley-Davidson's touring chassis (2017 on), from the maker's published
// figures: 1,625 mm wheelbase, 26 deg rake, 170 mm trail; the Electra Glide,
// Ultra Limited and Road King on 130/80B17 and 180/65B16 tyres (2,415 mm long
// without a top box), the Street and Road Glide on 130/60B19 and 180/55B18
export const TOURING = {
  17: { name: 'Touring bagger (Electra Glide-style)', wheelbase: 1.625, length: 2.415, rake: 26, trail: 0.170,
    seat: 0.690, rim: [17, 16], front_tyre: [130, 80], rear_tyre: [180, 65] },
  19: { name: 'Touring bagger (Street Glide-style)', wheelbase: 1.625, length: 2.400, rake: 26, trail: 0.170,
    seat: 0.690, rim: [19, 18], front_tyre: [130, 60], rear_tyre: [180, 55] },
};

const { out: OUT, args } = cli('usage: node cruiser.mjs out.glb [--paint=#hex] [--name=...] [--parts] [--bagger=batwing|sharknose|screen]');
const BAG = typeof args.bagger === 'string' ? args.bagger : null;
if (BAG && !['batwing', 'sharknose', 'screen'].includes(BAG)) { console.error(`unknown --bagger=${BAG}`); process.exit(2); }
const B = { ...(BAG ? TOURING[+args.wheels === 19 ? 19 : 17] : FATBOY), ...(args.name ? { name: args.name } : {}) };

// tyre sizes to metres: radius, width (a rim size each end: 17 in and 16 in)
const RIMS = Array.isArray(B.rim) ? B.rim : [B.rim, B.rim];
const RIM_F = RIMS[0] * 0.0254 / 2, RIM_RR = RIMS[1] * 0.0254 / 2;
const tyre = ([w, ar], rimR) => ({ R: rimR + w * ar / 100 / 1000, W: w / 1000 });
const TF = tyre(B.front_tyre, RIM_F), TR = tyre(B.rear_tyre, RIM_RR);
const ZF = B.wheelbase / 2, ZR = -B.wheelbase / 2;
const AF = new THREE.Vector3(0, TF.R, ZF), AR = new THREE.Vector3(0, TR.R, ZR);   // axles

// the steering axis: it meets the ground TRAIL ahead of the front contact
// patch and leans back RAKE degrees from upright
const rk = THREE.MathUtils.degToRad(B.rake);
const U = new THREE.Vector3(0, Math.cos(rk), -Math.sin(rk));          // up the axis
const N = new THREE.Vector3(0, Math.sin(rk), Math.cos(rk));           // forward, square to it
const G = new THREE.Vector3(0, 0, ZF + B.trail);
const axisAt = t => G.clone().addScaledVector(U, t);                   // a point on the axis
const forkAt = (s, x) => new THREE.Vector3(x, AF.y, AF.z).addScaledVector(U, s);   // a fork leg's centre line
const T_HEAD0 = 0.90, T_HEAD1 = 1.06;                                  // head tube along the axis
const HEAD = axisAt(T_HEAD0);
const S_CLAMP0 = (HEAD.y - AF.y) / U.y, S_CLAMP1 = (axisAt(T_HEAD1).y - AF.y) / U.y;
const FORK_X = 0.118;

// ── materials ────────────────────────────────────────────────────────────
const MATS = {
  paint: { color: hex(args.paint || '#121214'), metal: 0.0, rough: 0.28, clearcoat: 1 },
  chrome: { color: [0.92, 0.92, 0.93], metal: 1, rough: 0.07 },
  alloy: { color: [0.80, 0.81, 0.82], metal: 1, rough: 0.30 },
  fins: { color: [0.55, 0.56, 0.57], metal: 0.9, rough: 0.42 },
  black: { color: [0.018, 0.018, 0.02], metal: 0.2, rough: 0.45 },
  gloss_black: { color: [0.01, 0.01, 0.012], metal: 0.0, rough: 0.15, clearcoat: 1 },
  rubber: { color: [0.025, 0.025, 0.027], metal: 0, rough: 0.92 },
  leather: { color: [0.03, 0.026, 0.024], metal: 0, rough: 0.62 },
  lamp: { color: [0.9, 0.92, 0.95], metal: 0, rough: 0.05, emissive: [1, 0.98, 0.92], strength: 2 },
  red_lens: { color: [0.55, 0.02, 0.02], metal: 0, rough: 0.1, emissive: [0.6, 0.0, 0.0], strength: 1 },
  amber_lens: { color: [0.9, 0.42, 0.02], metal: 0, rough: 0.1, emissive: [0.5, 0.2, 0.0], strength: 1 },
  mirror: { color: [0.95, 0.95, 0.97], metal: 1, rough: 0.02 },
  screen: { color: [0.16, 0.17, 0.19], metal: 0, rough: 0.04, alpha: 0.45 },
};

// ── parts: [part, material, geometry in world space] ───────────────────
const parts = [];
let SUB = null;                                  // the named piece being modelled (--parts)
const add = (part, mat, g) => { parts.push([part, mat, g, SUB]); return g; };

// ── wheels ───────────────────────────────────────────────────────────────
function wheel(part, A, T, rimHalf, side, RIM_R) {
  // the tyre: a squarish section, the rim's bead to the crown
  const rIn = RIM_R - 0.004, rc = (rIn + T.R) / 2, hr = (T.R - rIn) / 2, ha = T.W / 2;
  const prof = [];
  for (let i = 0; i <= 40; i++) {
    const th = -Math.PI / 2 + Math.PI * i / 40;      // from one bead, over the crown, to the other
    const c = Math.cos(th), s = Math.sin(th), e = 2 / 3.2;
    const r = rc + hr * Math.sign(c) * Math.abs(c) ** e;
    const a = ha * Math.sign(s) * Math.abs(s) ** e * (0.86 + 0.14 * (r - rIn) / (2 * hr));
    prof.push([Math.max(r, rIn), a]);
  }
  SUB = 'tyre';
  add(part, 'rubber', aroundX(prof, A.x, A.y, A.z, 96));
  // a solid disc wheel, faintly dished, with its rim lip and two machined rings
  const disc = [[0.035, -rimHalf * 0.9], [0.07, -0.042], [0.15, -0.050], [RIM_R - 0.03, -0.056], [RIM_R - 0.012, -rimHalf],
    [RIM_R + 0.008, -rimHalf], [RIM_R + 0.008, rimHalf], [RIM_R - 0.012, rimHalf], [RIM_R - 0.03, 0.056],
    [0.15, 0.050], [0.07, 0.042], [0.035, rimHalf * 0.9]];
  SUB = 'rim';
  add(part, 'alloy', aroundX(disc, A.x, A.y, A.z, 96));
  for (const r of [0.115, 0.185]) for (const sx of [-1, 1]) {
    const t = new THREE.TorusGeometry(r, 0.0025, 8, 96); t.rotateY(Math.PI / 2); t.translate(A.x + sx * (0.047 + r * 0.03), A.y, A.z);
    add(part, 'chrome', t);
  }
  for (const sx of [-1, 1]) {                         // hub caps
    const cap = new THREE.CylinderGeometry(0.035, 0.04, 0.03, 32); cap.rotateZ(Math.PI / 2); cap.translate(A.x + sx * (rimHalf * 0.9 + 0.012), A.y, A.z);
    add(part, 'chrome', cap);
  }
  // the brake disc on the right
  SUB = 'disc';
  const bd = aroundX([[0.11, -0.003], [0.15, -0.003], [0.15, 0.003], [0.11, 0.003]], A.x + side * (rimHalf * 0.9 + 0.01), A.y, A.z, 72);
  add(part, 'chrome', bd);
}
// the rim's half width: the tyre's section (a 240 rear tyre's rim is wider)
wheel('wheel_f', AF, TF, BAG ? 0.050 : 0.062, -1, RIM_F);
wheel('wheel_r', AR, TR, BAG ? 0.078 : 0.105, -1, RIM_RR);
// the rear wheel's belt pulley, on the left
SUB = 'pulley';
add('wheel_r', 'black', aroundX([[0.06, -0.012], [0.172, -0.012], [0.172, 0.012], [0.06, 0.012]], AR.x + 0.125, AR.y, AR.z, 72));
add('wheel_r', 'chrome', aroundX([[0.12, -0.014], [0.15, -0.014], [0.15, 0.014], [0.12, 0.014]], AR.x + 0.127, AR.y, AR.z, 72));

// ── the front end (steers) ───────────────────────────────────────────────
for (const sx of [-1, 1]) {
  const x = sx * FORK_X;
  SUB = 'fork';
  add('steer', 'alloy', rod(forkAt(-0.03, x), forkAt(0.30, x), 0.030));            // lower legs
  add('steer', 'chrome', rod(forkAt(0.27, x), forkAt(S_CLAMP1 + 0.01, x), 0.043, 28)); // the wide shrouds
  add('steer', 'black', rod(forkAt(-0.02, x).add(V(sx * 0.012, 0, 0)), forkAt(0.02, x).add(V(sx * 0.012, 0, 0)), 0.034)); // axle clamp
}
// the axle through both legs
SUB = 'fork';
add('steer', 'chrome', rod(V(-FORK_X - 0.04, AF.y, AF.z), V(FORK_X + 0.04, AF.y, AF.z), 0.012));
// triple clamps: plates square to the axis joining both legs and the stem
for (const s of [S_CLAMP0, S_CLAMP1]) {
  const c = forkAt(s, 0).addScaledVector(N, -0.025);
  const g = roundedBox(2 * FORK_X + 0.10, 0.035, 0.10, 0.012, V(0, 0, 0));
  g.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(UPY, U)); g.translate(c.x, c.y, c.z);
  add('steer', s === S_CLAMP1 ? 'chrome' : 'black', g);
}
// the lamp nacelle between the shrouds and the round lamp (a frame-mounted
// fairing carries its own lamps; a fork fairing hides the nacelle)
const LAMP_C = forkAt(S_CLAMP0 + 0.06, 0).addScaledVector(N, 0.175);
if (BAG !== 'sharknose') {
  SUB = 'headlamp';
  const c = forkAt(S_CLAMP0 + 0.05, 0).addScaledVector(N, 0.07);
  if (BAG !== 'batwing') add('steer', 'paint', ball(c, 0.12, 1.05, 0.62, 0.9));
  const lampC = forkAt(S_CLAMP0 + 0.06, 0).addScaledVector(N, 0.175);
  const bucket = new THREE.CylinderGeometry(0.098, 0.085, 0.09, 48); bucket.rotateX(Math.PI / 2);
  bucket.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(V(0, 0, 1), N)); bucket.translate(lampC.x, lampC.y, lampC.z);
  add('steer', 'chrome', bucket);
  const lens = new THREE.CircleGeometry(0.09, 48); lens.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(V(0, 0, 1), N));
  const lc = lampC.clone().addScaledVector(N, 0.046); lens.translate(lc.x, lc.y, lc.z); add('steer', 'lamp', lens);
  const ring = new THREE.TorusGeometry(0.075, 0.006, 8, 64); ring.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(V(0, 0, 1), N));
  const rc = lampC.clone().addScaledVector(N, 0.05); ring.translate(rc.x, rc.y, rc.z); add('steer', 'chrome', ring);
  for (const sx of BAG === 'batwing' ? [] : [-1, 1]) {   // the front turn signals on the lower clamp
    SUB = 'indicators_front';
    const p = forkAt(S_CLAMP0 - 0.02, sx * (FORK_X + 0.07)).addScaledVector(N, 0.05);
    add('steer', 'chrome', rod(forkAt(S_CLAMP0 - 0.02, sx * FORK_X), p, 0.007));
    add('steer', 'amber_lens', ball(p.clone().addScaledVector(N, 0.02), 0.025, 1, 1, 1.3));
  }
}
// risers and the wide, pulled-back bar
{
  SUB = 'handlebar';
  const top = forkAt(S_CLAMP1, 0).addScaledVector(N, -0.025);
  const up = top.clone().addScaledVector(U, 0.11);
  for (const sx of [-1, 1]) add('steer', 'chrome', rod(top.clone().add(V(sx * 0.05, 0, 0)), up.clone().add(V(sx * 0.05, 0, 0)), 0.016));
  const bar = [];
  for (const sx of [-1, 1]) {
    SUB = 'handlebar';
    const side = [V(0, up.y + 0.01, up.z + 0.005), V(sx * 0.16, up.y + 0.015, up.z - 0.005), V(sx * 0.30, up.y + 0.045, up.z - 0.09),
      V(sx * 0.40, up.y + 0.06, up.z - 0.17), V(sx * 0.47, up.y + 0.062, up.z - 0.20)];
    add('steer', 'chrome', tube(side, 0.0125, 48, 12));
    bar.push(side);
    const g0 = side[3], g1 = side[4].clone().add(V(sx * 0.03, 0.002, -0.01));
    add('steer', 'rubber', rod(g0.clone().lerp(g1, 0.05), g1, 0.018, 20));          // grips
    add('steer', 'black', roundedBox(0.05, 0.045, 0.06, 0.012, side[3].clone().add(V(-sx * 0.04, 0.01, 0.0)))); // switches
    add('steer', 'chrome', tube([side[3].clone().add(V(-sx * 0.03, 0.015, 0.02)), side[3].clone().add(V(sx * 0.03, 0.0, 0.07)),
      side[4].clone().add(V(sx * 0.02, -0.01, 0.07))], 0.006, 16, 8));                // levers
    SUB = 'mirrors';
    const m0 = side[2].clone().add(V(sx * 0.01, 0.01, 0)), m1 = m0.clone().add(V(sx * 0.12, 0.15, 0.02));
    add('steer', 'chrome', tube([m0, m0.clone().add(V(sx * 0.05, 0.09, 0.01)), m1], 0.006, 20, 8));   // mirror stalks
    const mh = new THREE.CylinderGeometry(0.055, 0.055, 0.025, 32); mh.rotateX(Math.PI / 2); mh.rotateY(-sx * 0.25); mh.translate(m1.x, m1.y + 0.03, m1.z);
    add('steer', 'chrome', mh);
    const mg = new THREE.CircleGeometry(0.05, 32); mg.rotateY(Math.PI - sx * 0.25); mg.translate(m1.x, m1.y + 0.03, m1.z - 0.0135);
    add('steer', 'mirror', mg);
  }
}
// the short front mudguard, hugging the tyre
{
  SUB = 'mudguard_front';
  const r0 = TF.R + 0.03, w = 0.105;
  const prof = [];
  for (let i = 0; i <= 12; i++) { const a = -w + 2 * w * i / 12; prof.push([r0 + 0.012 * (1 - (a / w) ** 2), a]); }
  // aroundX's angle: 0 points forward (+z), -PI/2 straight up
  add('steer', 'paint', aroundX(prof, AF.x, AF.y, AF.z, 48, -Math.PI * 0.62, Math.PI * 0.44));
}

// ── the frame ────────────────────────────────────────────────────────────
const headTop = axisAt(T_HEAD1), headBot = axisAt(T_HEAD0);
SUB = 'frame';
add('body', 'black', rod(headBot.clone().addScaledVector(U, -0.02), headTop.clone().addScaledVector(U, 0.02), 0.032, 24));   // head tube
add('body', 'black', tube([headTop, V(0, 0.86, 0.30), V(0, 0.80, 0.05), V(0, 0.73, -0.22), V(0, 0.66, -0.42)], 0.024));       // backbone
for (const sx of [-1, 1]) {
  const x = sx * 0.075;
  add('body', 'black', tube([headBot.clone().add(V(x * 0.5, 0, 0)), V(x, 0.62, 0.43), V(x, 0.34, 0.37), V(x, 0.16, 0.25),
    V(x, 0.12, 0.05), V(x, 0.13, -0.20), V(x * 1.2, 0.30, -0.27), V(x * 1.35, 0.55, -0.33), V(x * 1.5, 0.64, -0.45),
    V(x * 1.7, 0.68, -0.80)], 0.019, 120));                                           // downtube, cradle, seat rail
  SUB = 'swingarm';
  const p0 = V(sx * 0.150, 0.34, -0.26), p1 = V(sx * 0.150, AR.y, AR.z);
  add('body', 'black', tube([p0, V(sx * 0.152, 0.335, -0.55), p1], 0.022, 40));        // swingarm, lower
  add('body', 'black', tube([V(sx * 0.15, 0.52, -0.33), V(sx * 0.152, 0.45, -0.55), p1.clone().add(V(0, 0.03, 0.04))], 0.017, 40)); // upper
  SUB = 'rear_shocks';
  add('body', 'black', rod(V(sx * 0.15, 0.33, -0.48), V(sx * 0.152, 0.47, -0.50), 0.012));
  SUB = 'swingarm';
  SUB = 'swingarm';
  add('body', 'chrome', rod(V(sx * 0.145, AR.y, AR.z), V(sx * 0.175, AR.y, AR.z), 0.022));   // axle ends
}
SUB = 'swingarm';
add('body', 'black', rod(V(-0.16, 0.34, -0.26), V(0.16, 0.34, -0.26), 0.024));          // swingarm pivot
add('body', 'chrome', rod(V(-0.16, AR.y, AR.z), V(0.16, AR.y, AR.z), 0.011));

// ── the V-twin ───────────────────────────────────────────────────────────
const CR = V(0, 0.30, 0.06);                                                              // crank
SUB = 'crankcase';
add('body', 'alloy', roundedBox(0.22, 0.22, 0.34, 0.06, V(0, 0.27, 0.05)));               // crankcase
SUB = 'gearbox';
add('body', 'black', roundedBox(0.18, 0.17, 0.24, 0.04, V(0, 0.27, -0.20)));              // gearbox
for (const [tilt, base] of [[+22.5, V(0, 0.37, 0.12)], [-22.5, V(0, 0.37, -0.01)]]) {
  const th = THREE.MathUtils.degToRad(tilt), d = V(0, Math.cos(th), Math.sin(th));
  const at = s => base.clone().addScaledVector(d, s);
  SUB = 'cylinders';
  SUB = 'cylinders';
  add('body', 'fins', rod(at(0), at(0.24), 0.058, 32));                                  // barrel
  for (let k = 0; k < 15; k++) add('body', 'fins', rod(at(0.012 + k * 0.0145), at(0.017 + k * 0.0145), 0.088, 40));   // fins
  SUB = 'cylinder_heads';
  add('body', 'alloy', rod(at(0.24), at(0.33), 0.074, 32));                              // head
  SUB = 'cylinder_heads';
  for (let k = 0; k < 5; k++) add('body', 'fins', rod(at(0.248 + k * 0.016), at(0.254 + k * 0.016), 0.094, 40));
  SUB = 'rocker_covers';
  add('body', 'chrome', ball(at(0.355), 0.078, 1.15, 0.45, 1.25));                       // rocker cover
  SUB = 'pushrod_tubes';
  for (const ox of [-0.022, 0.022]) add('body', 'chrome', rod(V(-0.075 + ox * 0.3, 0.30, 0.05 + ox), at(0.27).add(V(-0.07, 0, ox)), 0.009, 12)); // pushrod tubes
  SUB = 'spark_plugs';
  add('body', 'chrome', ball(at(0.29).add(V(0.10, 0, 0)), 0.018));                       // spark plug cap
}
// the primary cover on the left, a kidney of two rounds
{
  const s = new THREE.Shape();
  SUB = 'primary_cover';
  const c1 = [0.09, 0.30], r1 = 0.075, c2 = [-0.20, 0.32], r2 = 0.13;                  // (z, y): engine sprocket, clutch
  s.absarc(c1[0], c1[1], r1, -Math.PI / 2, Math.PI / 2, false);
  s.absarc(c2[0], c2[1], r2, Math.PI / 2, Math.PI * 1.5, false);
  s.closePath();
  const g = new THREE.ExtrudeGeometry(s, { depth: 0.02, bevelEnabled: true, bevelThickness: 0.015, bevelSize: 0.012, bevelSegments: 5, curveSegments: 32 });
  g.rotateY(-Math.PI / 2); g.translate(0.125, 0, 0);
  add('body', 'chrome', g);
  const derby = new THREE.CylinderGeometry(0.085, 0.09, 0.02, 48); derby.rotateZ(Math.PI / 2); derby.translate(0.168, 0.32, -0.20);
  add('body', 'chrome', derby);
}
// the round air cleaner on the right, in the V
{
  SUB = 'air_cleaner';
  const ac = new THREE.CylinderGeometry(0.118, 0.12, 0.075, 64); ac.rotateZ(Math.PI / 2); ac.translate(-0.17, 0.57, 0.055);
  add('body', 'chrome', ac);
  const face = new THREE.CylinderGeometry(0.09, 0.11, 0.012, 64); face.rotateZ(Math.PI / 2); face.translate(-0.214, 0.57, 0.055);
  add('body', 'black', face);
  add('body', 'chrome', rod(V(-0.13, 0.57, 0.055), V(-0.05, 0.56, 0.055), 0.05, 24));
}
// the shotgun exhaust on the right: two pipes, two stacked silencers (a
// bagger's: true duals, a silencer low under each pannier)
if (BAG) {
  SUB = 'exhaust';
  add('body', 'chrome', tube([V(-0.05, 0.60, 0.30), V(-0.15, 0.52, 0.36), V(-0.20, 0.33, 0.27), V(-0.205, 0.23, 0.05),
    V(-0.22, 0.23, -0.30), V(-0.235, 0.26, -0.52)], 0.022, 80));
  add('body', 'chrome', tube([V(-0.05, 0.62, -0.13), V(-0.15, 0.58, -0.19), V(-0.20, 0.40, -0.30), V(-0.222, 0.27, -0.45)], 0.022, 60));
  add('body', 'chrome', tube([V(-0.15, 0.53, 0.35), V(-0.20, 0.36, 0.28), V(-0.205, 0.28, 0.10)], 0.031, 30));   // heat shield
  add('body', 'black', tube([V(-0.205, 0.22, -0.02), V(0, 0.17, -0.10), V(0.20, 0.21, -0.22), V(0.235, 0.26, -0.52)], 0.02, 60)); // crossover
  for (const sx of [-1, 1]) {
    add('body', 'chrome', rod(V(sx * 0.235, 0.26, -0.52), V(sx * 0.245, 0.27, -1.12), 0.048, 40, 0.052));
    const tip = new THREE.CircleGeometry(0.048, 40); tip.rotateY(Math.PI); tip.translate(sx * 0.245, 0.27, -1.121);
    add('body', 'black', tip);
  }
} else {
  SUB = 'exhaust';
  const fp = [V(-0.05, 0.60, 0.30), V(-0.15, 0.52, 0.36), V(-0.20, 0.33, 0.27), V(-0.205, 0.25, 0.05), V(-0.21, 0.27, -0.30), V(-0.215, 0.30, -0.52)];
  const rp = [V(-0.05, 0.62, -0.13), V(-0.15, 0.58, -0.19), V(-0.20, 0.47, -0.32), V(-0.215, 0.42, -0.50)];
  add('body', 'chrome', tube(fp, 0.022, 80));
  add('body', 'chrome', tube(rp, 0.022, 60));
  add('body', 'chrome', tube([V(-0.15, 0.53, 0.35), V(-0.20, 0.36, 0.28), V(-0.205, 0.28, 0.10)], 0.031, 30));   // heat shield
  for (const [y, z0] of [[0.30, -0.52], [0.42, -0.50]]) {
    add('body', 'chrome', rod(V(-0.215, y, z0), V(-0.22, y + 0.01, -1.02), 0.048, 40, 0.05));
    const tip = new THREE.CircleGeometry(0.048, 40); tip.rotateY(Math.PI); tip.translate(-0.22, y + 0.01, -1.021);
    add('body', 'black', tip);
  }
}
// the belt, on the left, and its guard
{
  SUB = 'belt';
  const p0 = V(0.125, 0.30, -0.20), r0 = 0.07, r1 = 0.17;
  for (const sgn of [1, -1]) add('body', 'black', rod(V(0.125, p0.y + sgn * r0, p0.z), V(0.125, AR.y + sgn * r1, AR.z), 0.007, 8));
  add('body', 'chrome', tube([V(0.13, p0.y + r0 + 0.03, p0.z), V(0.13, AR.y + r1 + 0.025, -0.60), V(0.13, AR.y + r1 + 0.02, AR.z + 0.05)], 0.012, 24, 8));
}

// ── tank, seat, mudguard, lamps ──────────────────────────────────────────
// the fat tank: a teardrop seen from above, a flat underside on the backbone
SUB = 'tank';
add('body', 'paint', new ParametricGeometry((u, v, target) => {
  const z = 0.43 - 0.56 * u;                                   // nose to tail
  const w = 0.19 * Math.sin(Math.PI * (0.18 + 0.82 * u)) ** 0.55 * (1 - 0.22 * u);   // half width
  const h = 0.12 * Math.sin(Math.PI * (0.12 + 0.88 * u)) ** 0.5;                     // height above the base
  const a = Math.PI * 2 * v, c = Math.cos(a), s = Math.sin(a);
  const sq = (t, e) => Math.sign(t) * Math.abs(t) ** e;
  const y0 = 0.79 + 0.035 * u;
  target.set(w * sq(c, 0.7), y0 + (s > 0 ? h * sq(s, 0.75) : 0.02 * s), z);
}, 64, 48));
SUB = 'speedo';
add('body', 'chrome', roundedBox(0.075, 0.012, 0.42, 0.005, V(0, 0.918, 0.18)));        // the console on the tank
{
  const sp = new THREE.CylinderGeometry(0.045, 0.048, 0.018, 48); sp.translate(0, 0.927, 0.10); add('body', 'chrome', sp);
  const face = new THREE.CircleGeometry(0.038, 40); face.rotateX(-Math.PI / 2); face.translate(0, 0.937, 0.10); add('body', 'gloss_black', face);
  SUB = 'fuel_cap';
  const cap = new THREE.CylinderGeometry(0.03, 0.032, 0.012, 32); cap.translate(0.08, 0.905, 0.30); add('body', 'chrome', cap);
}
// the seat: a deep rider's dish and a pillion pad
SUB = 'seat';
add('body', 'leather', new ParametricGeometry((u, v, target) => {
  const z = -0.10 - 0.70 * u;
  const rider = u < 0.62;
  const w = (rider ? 0.07 + 0.11 * Math.sin(Math.PI * Math.min(1, u / 0.62 * 0.9 + 0.1)) : 0.12 - 0.04 * (u - 0.62) / 0.38);
  const top = rider ? B.seat + 0.03 + 0.05 * (u / 0.62) ** 3 : B.seat + 0.075 + 0.01 * Math.sin(Math.PI * (u - 0.62) / 0.38);
  const a = Math.PI * 2 * v, c = Math.cos(a), s = Math.sin(a);
  target.set(w * Math.sign(c) * Math.abs(c) ** 0.6, s > 0 ? top + 0.02 * s ** 0.5 : top - 0.045 + 0.02 * s, z);
}, 64, 40));
// the wide rear mudguard and its struts
{
  SUB = 'mudguard_rear';
  const r0 = TR.R + 0.035, w = 0.155, prof = [];
  for (let i = 0; i <= 14; i++) { const a = -w + 2 * w * i / 14; prof.push([r0 + 0.02 * (1 - (a / w) ** 2), a]); }
  add('body', 'paint', aroundX(prof, AR.x, AR.y, AR.z, 64, -Math.PI * 1.05, Math.PI * 0.70));   // over the top, down behind
  for (const sx of [-1, 1]) add('body', 'chrome', tube([V(sx * 0.16, 0.66, -0.55), V(sx * 0.17, 0.62, -0.85), V(sx * 0.165, 0.50, -1.08)], 0.011, 32, 8));
  SUB = 'tail_lamp';
  const tl = roundedBox(0.12, 0.035, 0.05, 0.012, V(0, 0.47, -1.20)); add('body', 'red_lens', tl);
  for (const sx of [-1, 1]) {
    SUB = 'indicators_rear';
    if (BAG) {                                       // on the panniers' tails
      add('body', 'amber_lens', ball(V(sx * 0.31, 0.50, -1.105), 0.024, 1.3, 1, 1));
      continue;
    }
    add('body', 'chrome', rod(V(sx * 0.165, 0.52, -1.05), V(sx * 0.24, 0.53, -1.08), 0.006));
    add('body', 'amber_lens', ball(V(sx * 0.255, 0.53, -1.09), 0.022, 1, 1, 1.3));
  }
}
// floorboards, pedals, pillion pegs
for (const sx of [-1, 1]) {
  SUB = 'footboards';
  add('body', 'chrome', roundedBox(0.13, 0.02, 0.30, 0.008, V(sx * 0.31, 0.30, 0.31)));
  add('body', 'rubber', roundedBox(0.11, 0.008, 0.27, 0.003, V(sx * 0.31, 0.314, 0.31)));
  add('body', 'black', rod(V(sx * 0.10, 0.20, 0.30), V(sx * 0.25, 0.29, 0.30), 0.012));
  if (BAG) {                                         // the passenger's boards, ahead of the panniers
    add('body', 'black', rod(V(sx * 0.15, 0.40, -0.36), V(sx * 0.23, 0.41, -0.38), 0.012));
    add('body', 'chrome', roundedBox(0.10, 0.02, 0.18, 0.008, V(sx * 0.28, 0.41, -0.39)));
    add('body', 'rubber', roundedBox(0.085, 0.008, 0.16, 0.003, V(sx * 0.28, 0.422, -0.39)));
    continue;
  }
  add('body', 'chrome', rod(V(sx * 0.16, 0.42, -0.62), V(sx * 0.27, 0.40, -0.64), 0.012));
  add('body', 'rubber', rod(V(sx * 0.23, 0.40, -0.64), V(sx * 0.30, 0.40, -0.645), 0.016));
}
SUB = 'brake_pedal';
add('body', 'chrome', tube([V(-0.15, 0.24, 0.12), V(-0.25, 0.26, 0.30), V(-0.29, 0.30, 0.47)], 0.009, 20, 8));   // brake pedal
SUB = 'gear_lever';
add('body', 'chrome', tube([V(0.15, 0.27, 0.10), V(0.24, 0.29, 0.30), V(0.28, 0.32, 0.47)], 0.009, 20, 8));     // gear lever
SUB = 'caliper_rear';
add('body', 'black', roundedBox(0.04, 0.06, 0.05, 0.01, V(-0.14, AR.y + 0.05, AR.z + 0.09)));                     // rear caliper

// the side stand, on the left: folded back along the frame
const STAND_PIVOT = V(0.165, 0.20, 0.10);
const STAND_FOLDED = V(0.06, 0.10, -1).normalize(), STAND_DOWN = V(0.30, -0.93, 0.21).normalize();
SUB = 'side_stand';
add('stand', 'black', rod(STAND_PIVOT, STAND_PIVOT.clone().addScaledVector(STAND_FOLDED, 0.29), 0.012));
add('stand', 'black', ball(STAND_PIVOT.clone().addScaledVector(STAND_FOLDED, 0.30), 0.022, 1.3, 0.6, 1.3));
add('stand', 'chrome', rod(STAND_PIVOT.clone().add(V(-0.02, 0, 0)), STAND_PIVOT.clone().add(V(0.02, 0, 0)), 0.018));
// the front brake caliper rides on the right fork leg (steers, does not spin)
{
  SUB = 'caliper_front';
  const c = forkAt(0.05, -FORK_X).add(V(0.02, 0, 0)).addScaledVector(N, -0.11);
  add('steer', 'black', roundedBox(0.04, 0.10, 0.06, 0.012, c));
}

// ── a bagger's fairing, panniers, top box and lowers ────────────────────
// a windscreen: a clear sheet rising from its base line, raked back and
// wrapped round at the sides (one surface: drawn both sides)
function windscreen(part, base, halfW, h, rake, wrap) {
  return add(part, 'screen', new ParametricGeometry((u, v, target) => {
    const w = halfW * (1 - 0.22 * v ** 2.5), x = (2 * u - 1) * w * (1 - 0.25 * (v > 0.85 ? (v - 0.85) / 0.15 : 0) ** 2 * Math.abs(2 * u - 1) ** 6);
    target.set(base.x + x, base.y + h * v, base.z - rake * h * v - wrap * (x / halfW) ** 2);
  }, 32, 16));
}
// a fairing lofted from its back (wide) to its nose (narrower), raked back
// by TILT about its centre C
function fairingShell(part, C, depth, back, front, tilt) {
  const g = lofted(u => {
    const k = u ** 1.4;
    return { z: C.z - depth / 2 + depth * u, w: back.w + (front.w - back.w) * k, yt: C.y + back.yt + (front.yt - back.yt) * k,
      yb: C.y + back.yb + (front.yb - back.yb) * k, e: back.e + (front.e - back.e) * u };
  }, 40, 56, true);
  g.translate(-C.x, -C.y, -C.z); g.rotateX(-tilt); g.translate(C.x, C.y, C.z);
  return add(part, 'paint', g);
}
const lens = (part, c, r, mat = 'lamp') => {        // a round lamp facing forward, in its chrome ring
  const l = new THREE.CircleGeometry(r, 40); l.translate(c.x, c.y, c.z + 0.002); add(part, mat, l);
  const ring = new THREE.TorusGeometry(r, 0.008, 8, 48); ring.translate(c.x, c.y, c.z); add(part, 'chrome', ring);
  const cup = new THREE.CylinderGeometry(r + 0.004, r * 0.8, 0.05, 40); cup.rotateX(Math.PI / 2); cup.translate(c.x, c.y, c.z - 0.025);
  add(part, 'chrome', cup);
};
if (BAG === 'batwing') {
  // a fairing on the fork (it steers): wide wings, the round lamp in its nose,
  // the indicators at its lower corners, a short screen on top and the dash behind
  SUB = 'fairing';
  const C = LAMP_C.clone().add(V(0, 0.02, -0.12));
  fairingShell('steer', C, 0.24, { w: 0.46, yt: 0.18, yb: -0.24, e: 0.42 }, { w: 0.25, yt: 0.06, yb: -0.14, e: 0.75 }, 0.22);
  SUB = 'windscreen';
  windscreen('steer', C.clone().add(V(0, 0.15, -0.02)), 0.33, 0.22, 0.55, 0.10);
  SUB = 'dash';
  add('steer', 'gloss_black', roundedBox(0.40, 0.13, 0.05, 0.02, C.clone().add(V(0, 0.05, -0.15))));
  SUB = 'indicators_front';
  for (const sx of [-1, 1]) add('steer', 'amber_lens', ball(C.clone().add(V(sx * 0.34, -0.12, 0.04)), 0.026, 1.3, 1, 1));
} else if (BAG === 'sharknose') {
  // a fairing on the frame (it does not steer): a pointed nose with two lamps
  SUB = 'fairing';
  const C = LAMP_C.clone().add(V(0, 0.03, -0.06));
  fairingShell('body', C, 0.30, { w: 0.45, yt: 0.17, yb: -0.17, e: 0.32 }, { w: 0.30, yt: 0.05, yb: -0.11, e: 0.55 }, 0.12);
  SUB = 'headlamp';
  for (const sx of [-1, 1]) lens('body', C.clone().add(V(sx * 0.11, -0.04, 0.165)), 0.062);
  SUB = 'windscreen';
  windscreen('body', C.clone().add(V(0, 0.13, 0.02)), 0.30, 0.14, 0.9, 0.08);
  SUB = 'indicators_front';
  for (const sx of [-1, 1]) add('body', 'amber_lens', ball(C.clone().add(V(sx * 0.38, -0.08, 0.06)), 0.026, 1.3, 1, 1));
} else if (BAG === 'screen') {
  // a tall screen over the nacelle, and two passing lamps on a bar below it
  SUB = 'windscreen';
  windscreen('steer', LAMP_C.clone().add(V(0, 0.09, -0.04)), 0.27, 0.44, 0.30, 0.10);
  for (const sx of [-1, 1]) add('steer', 'chrome', rod(forkAt(S_CLAMP1 - 0.02, sx * FORK_X), LAMP_C.clone().add(V(sx * 0.22, 0.10, -0.06)), 0.006));
  SUB = 'passing_lamps';
  const bar = forkAt(S_CLAMP0 - 0.12, 0).addScaledVector(N, 0.07);
  add('steer', 'chrome', rod(bar.clone().add(V(-0.21, 0, 0)), bar.clone().add(V(0.21, 0, 0)), 0.011));
  for (const sx of [-1, 1]) lens('steer', bar.clone().add(V(sx * 0.21, 0.02, 0.05)), 0.055);
}
if (BAG) {
  // the hard panniers: a D in side view (flat lid, round tail), each with its
  // lid's seam and a chrome latch
  for (const sx of [-1, 1]) {
    SUB = 'panniers';
    const D = [[-0.50, 0.67], [-0.96, 0.67], [-1.03, 0.655], [-1.075, 0.62], [-1.10, 0.57], [-1.105, 0.51], [-1.09, 0.45],
      [-1.06, 0.40], [-1.01, 0.37], [-0.95, 0.36], [-0.58, 0.36], [-0.53, 0.38], [-0.505, 0.42], [-0.50, 0.47]];
    add('body', 'paint', sidePanel(D, 0.20, 0.21, sx, 0.03));
    add('body', 'black', sidePanel([[-0.495, 0.604], [-1.085, 0.604], [-1.085, 0.596], [-0.495, 0.596]], 0.205, 0.207, sx, 0.002));
    add('body', 'chrome', roundedBox(0.012, 0.05, 0.10, 0.004, V(sx * 0.412, 0.585, -0.80)));
  }
  if (args.tourpak) {
    // the top box on its rack behind the pillion, a backrest on its front and its lamps on the back
    SUB = 'top_box';
    add('body', 'paint', roundedBox(0.44, 0.30, 0.40, 0.07, V(0, 0.99, -1.00)));
    add('body', 'black', roundedBox(0.445, 0.012, 0.405, 0.005, V(0, 1.035, -1.00)));
    add('body', 'leather', roundedBox(0.30, 0.20, 0.07, 0.03, V(0, 0.96, -0.79)));
    for (const sx of [-1, 1]) {
      add('body', 'chrome', rod(V(sx * 0.17, 0.66, -0.84), V(sx * 0.17, 0.85, -0.86), 0.010));
      add('body', 'chrome', rod(V(sx * 0.17, 0.66, -1.12), V(sx * 0.17, 0.85, -1.12), 0.010));
      add('body', 'red_lens', roundedBox(0.11, 0.035, 0.02, 0.008, V(sx * 0.14, 0.95, -1.205)));
    }
  }
  if (args.lowers) {
    // the leg shields either side of the cylinders
    SUB = 'lowers';
    for (const sx of [-1, 1]) add('body', 'paint', ball(V(sx * 0.27, 0.52, 0.40), 0.15, 0.42, 1.0, 0.62));
  }
}

// ── hierarchy: one pivot per moving part ─────────────────────────────────
const PIVOT = { steer: axisAt(T_HEAD0 + 0.08), wheel_f: AF.clone(), wheel_r: AR.clone(), stand: STAND_PIVOT.clone() };
const PARENT = { steer: null, wheel_f: 'steer', wheel_r: null, stand: null };

const SPLIT = !!args.parts;
// a piece's node name: the wheels' tyre, rim, disc and pulley take the end
// they belong to (tyre_f, rim_r); every other piece is named once
const pieceName = (part, sub) => part.startsWith('wheel_') ? `${sub}_${part.slice(-1)}` : sub;
const X = V(1, 0, 0);
const { tris } = await writeBike({
  out: OUT, scale: +(args.scale || 1), sceneName: BAG ? 'bagger' : 'cruiser', mats: MATS, pieces: parts, pivots: PIVOT, parents: PARENT,
  split: SPLIT, pieceName, doubleSided: ['screen'],
  extras: { kind: 'motorbike', model: B.name, wheelbase_m: B.wheelbase, length_m: B.length, rake_deg: B.rake, trail_m: B.trail,
    tyres: [`${B.front_tyre[0]}/${B.front_tyre[1]}R${RIMS[0]}`, `${B.rear_tyre[0]}/${B.rear_tyre[1]}R${RIMS[1]}`],
    sizes_note: args.sizes || null, clips: ['wheels_spin', 'steer_left', 'steer_right', 'stand_down'] },
  order: ['steer', 'wheel_r', 'wheel_f', 'stand'], meshOrder: ['body', 'steer', 'wheel_f', 'wheel_r', 'stand'],
  clips: (nodes, clip, q) => {
    const spin = [0, 90, 180, 270, 360].map(d => q(X, d));
    clip('wheels_spin', [[nodes.wheel_f, [0, 0.25, 0.5, 0.75, 1], spin], [nodes.wheel_r, [0, 0.25, 0.5, 0.75, 1], spin]]);
    clip('steer_left', [[nodes.steer, [0, 1], [q(U, 0), q(U, 32)]]]);
    clip('steer_right', [[nodes.steer, [0, 1], [q(U, 0), q(U, -32)]]]);
    const sq = new THREE.Quaternion().setFromUnitVectors(STAND_FOLDED, STAND_DOWN).toArray();
    clip('stand_down', [[nodes.stand, [0, 1], [[0, 0, 0, 1], sq]]]);
  },
  copyright: `${B.name}: modelled in code by the ExpertCarCheck GLB machine (bikes/cruiser.mjs), ${args.sizes || "to its preset's published sizes"}. No maker's model, badge or lettering.`,
});
const L = Math.max(AF.z + TF.R, 0) - Math.min(-1.215, AR.z - TR.R, BAG ? -1.125 : 0);
console.log(JSON.stringify({ wrote: OUT, triangles: Math.round(tris), parts: [...new Set(parts.map(p => p[0]))],
  pieces: SPLIT ? [...new Set(parts.map(p => pieceName(p[0], p[3] || p[0])))] : undefined,
  front_tyre_d_m: +(2 * TF.R).toFixed(3), rear_tyre_d_m: +(2 * TR.R).toFixed(3), length_m: +L.toFixed(3),
  fork_offset_m: +new THREE.Vector3().subVectors(AF, G).dot(N).toFixed(3) }));
