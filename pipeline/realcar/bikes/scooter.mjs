// scooter.mjs — a 125 cc scooter modelled in code (three.js geometry,
// written as glTF by gltf-transform, as cruiser.mjs): no downloaded model,
// so the file is wholly ExpertCarCheck's. Its sizes are a real scooter's
// published figures (the SCOOTER125 preset, a PCX125-style: wheelbase,
// length, rake, trail, seat height, tyre sizes); its parts move:
//   wheels_spin         both wheels turn (a loop)
//   steer_left          the bars and their cover, the fork, the front wheel,
//   steer_right         disc and caliper turn about the raked steering axis
//   stand_down          the side stand swings down
//   centre_stand_down   the centre stand swings down
//   seat_open           the seat lifts on its front hinge over the storage bin
// With --parts every piece is its own named node (the step-through frame,
// the body panels, the floor and the fuel tank under it, the single-cylinder
// engine and its CVT case, the shocks, exhaust, lamps ...), each under the
// pivot it moves with, so a trainer can take any one off.
// No maker's badge or lettering is modelled.
//
//   node pipeline/realcar/bikes/scooter.mjs out.glb [--paint=#c8ccd2] [--name="..."] [--parts]
//
// Frame: +Y up, nose +Z, the rider's left +X, metres, ground at y = 0.
// ExpertCarCheck. Proprietary: see ../LICENSE.
import * as THREE from 'three';
import { cli, V, UPY, rod, tube, ball, aroundX, roundedBox, lofted, helix, hex, tyreOf, tyreGeometry, castWheel, brakeDisc,
  writeBike } from './kit.mjs';

// ── the scooter's figures ────────────────────────────────────────────────
// a 125 cc liquid-cooled scooter of the 2021-on PCX125 kind, from the
// maker's published specification: 1,315 mm wheelbase, 1,935 mm long,
// 27 deg rake, 86 mm trail, 764 mm seat, 110/70-14 front and 130/70-13 rear
export const SCOOTER125 = {
  name: 'Scooter (125 cc)', wheelbase: 1.315, length: 1.935, rake: 27, trail: 0.086, seat: 0.764,
  front_rim: 14, rear_rim: 13, front_tyre: [110, 70], rear_tyre: [130, 70],
};

const { out: OUT, args } = cli('usage: node scooter.mjs out.glb [--paint=#hex] [--name=...] [--parts]');
const B = { ...SCOOTER125, ...(args.name ? { name: args.name } : {}) };

const TF = tyreOf(B.front_rim, B.front_tyre), TR = tyreOf(B.rear_rim, B.rear_tyre);
const ZF = B.wheelbase / 2, ZR = -B.wheelbase / 2;
const AF = V(0, TF.R, ZF), AR = V(0, TR.R, ZR);
const rk = THREE.MathUtils.degToRad(B.rake);
const U = V(0, Math.cos(rk), -Math.sin(rk)), N = V(0, Math.sin(rk), Math.cos(rk));
const G = V(0, 0, ZF + B.trail);
const axisAt = t => G.clone().addScaledVector(U, t);
const forkAt = (s, x) => V(x, AF.y, AF.z).addScaledVector(U, s);
const T_HEAD0 = 0.76, T_HEAD1 = 0.95;
const S_CLAMP0 = (axisAt(T_HEAD0).y - AF.y) / U.y;
const FORK_X = 0.085;

// ── materials ────────────────────────────────────────────────────────────
const MATS = {
  paint: { color: hex(args.paint || '#c8ccd2'), metal: 0.4, rough: 0.28, clearcoat: 1 },
  plastic: { color: [0.035, 0.036, 0.04], metal: 0, rough: 0.6 },
  gloss_black: { color: [0.01, 0.01, 0.012], metal: 0.0, rough: 0.15, clearcoat: 1 },
  black: { color: [0.018, 0.018, 0.02], metal: 0.2, rough: 0.5 },
  steel: { color: [0.30, 0.30, 0.32], metal: 0.8, rough: 0.45 },
  cast: { color: [0.55, 0.56, 0.58], metal: 0.9, rough: 0.4 },
  alloy: { color: [0.80, 0.81, 0.82], metal: 1, rough: 0.3 },
  chrome: { color: [0.92, 0.92, 0.93], metal: 1, rough: 0.07 },
  spring: { color: [0.75, 0.10, 0.08], metal: 0.3, rough: 0.35 },
  rubber: { color: [0.025, 0.025, 0.027], metal: 0, rough: 0.92 },
  seat: { color: [0.03, 0.03, 0.032], metal: 0, rough: 0.7 },
  lamp: { color: [0.9, 0.92, 0.95], metal: 0, rough: 0.05, emissive: [1, 0.98, 0.92], strength: 2 },
  red_lens: { color: [0.55, 0.02, 0.02], metal: 0, rough: 0.1, emissive: [0.6, 0.0, 0.0], strength: 1 },
  amber_lens: { color: [0.9, 0.42, 0.02], metal: 0, rough: 0.1, emissive: [0.5, 0.2, 0.0], strength: 1 },
  mirror: { color: [0.95, 0.95, 0.97], metal: 1, rough: 0.02 },
  screen: { color: [0.12, 0.13, 0.15], metal: 0, rough: 0.05, alpha: 0.45 },
  plate: { color: [0.93, 0.93, 0.90], metal: 0, rough: 0.4 },
};

const parts = [];
let SUB = null;
const add = (part, mat, g) => { parts.push([part, mat, g, SUB]); return g; };

// ── wheels: small cast five-spokes; a disc in front, a drum in the rear hub
function wheel(part, A, T, rimHalf) {
  SUB = 'tyre'; add(part, 'rubber', tyreGeometry(A, T, 2 / 2.6));
  const [hub, rim, spokes] = castWheel(A, T, rimHalf, 5, false, 0.05);
  SUB = 'rim'; add(part, 'cast', rim); add(part, 'cast', spokes); add(part, 'alloy', hub);
}
wheel('wheel_f', AF, TF, 0.040);
wheel('wheel_r', AR, TR, 0.048);
SUB = 'disc';
add('wheel_f', 'chrome', brakeDisc(AF, 0.058, 0.110, 0.072));
SUB = 'drum';
add('wheel_r', 'cast', aroundX([[0.03, -0.035], [0.075, -0.035], [0.075, 0.0], [0.03, 0.0]], -0.045, AR.y, AR.z, 48));

// ── the front end (steers) ───────────────────────────────────────────────
for (const sx of [-1, 1]) {
  const x = sx * FORK_X;
  SUB = 'fork';
  add('steer', 'black', rod(forkAt(-0.03, x), forkAt(0.20, x), 0.024, 24));               // sliders
  add('steer', 'chrome', rod(forkAt(0.18, x), forkAt(S_CLAMP0 + 0.02, x), 0.016, 20));     // stanchions
}
SUB = 'fork';
add('steer', 'alloy', rod(V(-FORK_X - 0.03, AF.y, AF.z), V(FORK_X + 0.03, AF.y, AF.z), 0.01));
{
  const c = forkAt(S_CLAMP0, 0).addScaledVector(N, -0.025);
  const g = roundedBox(2 * FORK_X + 0.07, 0.03, 0.08, 0.012, V(0, 0, 0));
  g.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(UPY, U)); g.translate(c.x, c.y, c.z);
  add('steer', 'black', g);
  add('steer', 'steel', rod(axisAt(T_HEAD0 - 0.02), axisAt(1.13), 0.016, 16));             // steering stem
}
SUB = 'caliper_front';
add('steer', 'black', roundedBox(0.03, 0.09, 0.05, 0.01, AF.clone().add(V(0.058, 0.07, -0.085))));
SUB = 'mudguard_front';
{
  const r0 = TF.R + 0.02, w = 0.07, prof = [];
  for (let i = 0; i <= 12; i++) { const a = -w + 2 * w * i / 12; prof.push([r0 + 0.01 * (1 - (a / w) ** 2), a]); }
  add('steer', 'paint', aroundX(prof, AF.x, AF.y, AF.z, 48, -Math.PI * 0.85, Math.PI * 0.62));
}
// the bars under their cover, the dash on top, mirrors on stalks
const BAR = axisAt(1.15);
{
  SUB = 'handlebar';
  for (const sx of [-1, 1]) {
    const p0 = BAR.clone().add(V(sx * 0.10, 0.005, -0.03)), p1 = BAR.clone().add(V(sx * 0.33, 0.025, -0.11));
    add('steer', 'steel', rod(p0, p1, 0.011, 14));
    add('steer', 'rubber', rod(p0.clone().lerp(p1, 0.55), p1.clone().add(V(sx * 0.025, 0.003, -0.008)), 0.017, 18));
    add('steer', 'black', roundedBox(0.045, 0.045, 0.06, 0.01, p0.clone().lerp(p1, 0.38).add(V(0, 0.01, 0.01))));
    add('steer', 'alloy', tube([p0.clone().lerp(p1, 0.35).add(V(0, 0.015, 0.035)), p0.clone().lerp(p1, 0.75).add(V(0, 0.01, 0.075)),
      p1.clone().add(V(sx * 0.02, 0, 0.06))], 0.006, 16, 8));                                 // brake levers both sides
  }
  SUB = 'handlebar_cover';
  add('steer', 'paint', lofted(u => ({ z: BAR.z + 0.13 - 0.24 * u, w: 0.11 + 0.08 * Math.sin(Math.PI * u) ** 0.5,
    yt: BAR.y + 0.07 + 0.02 * Math.sin(Math.PI * u), yb: BAR.y - 0.10 + 0.03 * u, e: 0.6 }), 24, 32, true));
  SUB = 'dash';
  { const d = roundedBox(0.20, 0.02, 0.11, 0.008, V(0, 0, 0)); d.rotateX(-0.45); d.translate(BAR.x, BAR.y + 0.095, BAR.z - 0.01); add('steer', 'gloss_black', d); }
  SUB = 'mirrors';
  for (const sx of [-1, 1]) {
    const m0 = BAR.clone().add(V(sx * 0.20, 0.05, -0.06)), m1 = m0.clone().add(V(sx * 0.07, 0.15, 0.02));
    add('steer', 'black', tube([m0, m0.clone().add(V(sx * 0.03, 0.10, 0.0)), m1], 0.007, 16, 8));
    add('steer', 'black', ball(m1.clone().add(V(0, 0.03, 0)), 0.055, 1.25, 0.7, 0.4));
    const g = new THREE.CircleGeometry(0.045, 24); g.scale(1.25, 0.7, 1); g.rotateY(Math.PI); g.translate(m1.x, m1.y + 0.03, m1.z - 0.024);
    add('steer', 'mirror', g);
  }
}

// ── the step-through frame ───────────────────────────────────────────────
SUB = 'frame';
add('body', 'steel', rod(axisAt(T_HEAD0 - 0.03), axisAt(T_HEAD1 + 0.03), 0.026, 24));        // steering head
add('body', 'steel', tube([axisAt(T_HEAD0 + 0.04).add(V(0, 0, -0.03)), V(0, 0.55, 0.30), V(0, 0.30, 0.24), V(0, 0.20, 0.12)], 0.024, 50, 12));
for (const sx of [-1, 1]) {
  add('body', 'steel', tube([V(sx * 0.02, 0.21, 0.16), V(sx * 0.11, 0.19, 0.05), V(sx * 0.12, 0.19, -0.15),
    V(sx * 0.11, 0.30, -0.28), V(sx * 0.09, 0.55, -0.40), V(sx * 0.075, 0.64, -0.78)], 0.016, 90, 10));
}
add('body', 'steel', rod(V(-0.12, 0.19, -0.13), V(0.12, 0.19, -0.13), 0.013, 12));
add('body', 'steel', rod(V(-0.09, 0.55, -0.40), V(0.09, 0.55, -0.40), 0.012, 12));

// ── the engine: a single, its cylinder lying forward; the CVT case on the
// left runs back to the rear axle (the engine and case swing together, a
// "unit-swing" engine)
const CR = V(0, 0.30, -0.30);                                                    // crank
SUB = 'crankcase';
add('body', 'cast', roundedBox(0.22, 0.17, 0.17, 0.04, CR.clone()));
const D = V(0, 0.17, 0.985).normalize(), cyl = s => CR.clone().addScaledVector(D, s);
const lying = (w, h, d, r, s) => { const g = roundedBox(w, h, d, r, V(0, 0, 0)); g.rotateX(-Math.atan2(D.y, D.z)); const c = cyl(s); g.translate(c.x, c.y, c.z); return g; };
SUB = 'cylinder';
add('body', 'cast', lying(0.12, 0.12, 0.10, 0.02, 0.12));
SUB = 'cylinder_head';
add('body', 'cast', lying(0.13, 0.13, 0.07, 0.02, 0.205));
SUB = 'cam_cover';
add('body', 'gloss_black', lying(0.11, 0.11, 0.04, 0.015, 0.255));
SUB = 'spark_plug';
add('body', 'black', rod(cyl(0.21).add(V(0, 0.065, 0)), cyl(0.21).add(V(0, 0.11, 0.01)), 0.012, 12));
SUB = 'cvt_case';
add('body', 'cast', lofted(u => {
  const z = CR.z + 0.12 - (CR.z + 0.12 - AR.z + 0.10) * u;
  return { z, x: 0.135, w: 0.035, yt: 0.43 - 0.08 * u, yb: 0.19 + 0.0 * u, e: 0.5 };
}, 30, 24, true));
SUB = 'final_drive';
add('body', 'cast', aroundX([[0, -0.03], [0.07, -0.03], [0.08, 0.0], [0.07, 0.03], [0, 0.03]], 0.10, AR.y, AR.z, 40));
SUB = 'air_filter';
add('body', 'black', roundedBox(0.12, 0.12, 0.26, 0.03, V(0.10, 0.50, -0.44)));
add('body', 'black', tube([V(0.07, 0.47, -0.32), V(0.03, 0.42, -0.22), cyl(0.20).add(V(0, 0.06, 0))], 0.02, 20, 10));   // intake
SUB = 'radiator';
add('body', 'black', roundedBox(0.03, 0.15, 0.17, 0.012, V(-0.13, 0.31, -0.27)));
add('body', 'cast', aroundX([[0, -0.006], [0.06, -0.006], [0.06, 0.006], [0, 0.006]], -0.148, 0.31, -0.27, 32));   // fan cover
SUB = 'oil_filler';
add('body', 'black', rod(V(-0.11, 0.34, -0.18), V(-0.125, 0.40, -0.17), 0.012, 12));
// the exhaust: down from the head, back under the engine, up the right
SUB = 'exhaust';
add('body', 'steel', tube([cyl(0.22).add(V(-0.02, -0.06, 0)), cyl(0.20).add(V(-0.05, -0.12, 0.03)), V(-0.10, 0.13, -0.10),
  V(-0.15, 0.17, -0.40), V(-0.17, 0.25, -0.52)], 0.018, 60, 10));
add('body', 'black', rod(V(-0.17, 0.26, -0.50), V(-0.17, 0.40, -0.92), 0.052, 32, 0.045));
add('body', 'chrome', roundedBox(0.012, 0.09, 0.32, 0.01, V(-0.225, 0.34, -0.72)));                 // heat shield
// twin rear shocks from the case to the frame
SUB = 'rear_shocks';
for (const sx of [0.175, -0.125]) {
  const lo = V(sx, 0.30, AR.z + 0.06), hi = V(sx, 0.60, AR.z + 0.12);
  add('body', 'black', rod(lo, hi, 0.014, 16));
  add('body', 'spring', helix(lo.clone().lerp(hi, 0.25), lo.clone().lerp(hi, 0.85), 0.026, 0.005, 7));
}

// ── bodywork ─────────────────────────────────────────────────────────────
// the front cowl round the steering head, the headlamp in its face; the
// leg shield behind it; the floor; the fuel tank under the floor
SUB = 'front_cowl';
add('body', 'paint', lofted(u => {
  const z = 0.58 - 0.30 * u;
  return { z, w: 0.07 + 0.13 * Math.min(1, u * 1.8) ** 0.6, yt: 0.97 - 0.10 * (1 - u) ** 2, yb: 0.50 - 0.16 * u ** 0.8, e: 0.65 };
}, 30, 40, true));
SUB = 'headlamp';
add('body', 'lamp', ball(V(0, 0.80, 0.555), 0.06, 1.35, 0.55, 0.45));
SUB = 'indicators_front';
for (const sx of [-1, 1]) add('body', 'amber_lens', ball(V(sx * 0.125, 0.70, 0.49), 0.03, 0.7, 0.45, 1.2));
SUB = 'windscreen';
{ const s = roundedBox(0.24, 0.14, 0.006, 0.03, V(0, 0, 0)); s.rotateX(-0.60); s.translate(0, 0.995, 0.50); add('body', 'screen', s); }
SUB = 'leg_shield';
add('body', 'plastic', lofted(u => ({ z: 0.29 - 0.03 * u, w: 0.205, yt: 0.93, yb: 0.30, e: 0.8 }), 4, 40, true));
SUB = 'floorboard';
add('body', 'plastic', roundedBox(0.38, 0.025, 0.42, 0.01, V(0, 0.300, 0.05)));
add('body', 'rubber', roundedBox(0.34, 0.006, 0.38, 0.003, V(0, 0.315, 0.05)));
SUB = 'fuel_tank';
add('body', 'black', roundedBox(0.26, 0.09, 0.30, 0.03, V(0, 0.235, 0.10)));
add('body', 'alloy', rod(V(0, 0.28, 0.20), V(0, 0.33, 0.22), 0.02, 16));                          // filler neck, under its flap
for (const [nm, a0, a1] of [['floor_skirt_left', -1.4, 0.0], ['floor_skirt_right', Math.PI, Math.PI + 1.4]]) {
  SUB = nm;
  add('body', 'paint', lofted(u => ({ z: 0.30 - 0.48 * u, w: 0.20, yt: 0.31, yb: 0.13 + 0.02 * u, e: 0.7, a0, a1 }), 20, 12));
}
// the rear body: left and right panels round the storage bin, the tail
const REAR = z => {
  const t = Math.min(1, Math.max(0, (-0.08 - z) / 0.87));
  return { w: 0.19 - 0.11 * t ** 1.5, yt: 0.73 + 0.06 * t, yb: 0.34 + 0.30 * t ** 1.3, e: 0.7 };
};
for (const [nm, a0, a1] of [['body_left', -1.35, 1.35], ['body_right', Math.PI - 1.35, Math.PI + 1.35]]) {
  SUB = nm;
  add('body', 'paint', lofted(u => { const z = -0.10 - 0.84 * u; return { z, ...REAR(z), a0, a1 }; }, 40, 24));
}
SUB = 'tail_cowl';
add('body', 'paint', lofted(u => { const z = -0.86 - 0.10 * u; const r = REAR(z); return { z, ...r, w: r.w * (1 - 0.6 * u), yt: r.yt, yb: r.yb + 0.05 * u }; }, 10, 32, true));
SUB = 'storage_bin';
add('body', 'plastic', roundedBox(0.26, 0.20, 0.46, 0.03, V(0, 0.625, -0.38)));
SUB = 'battery';
add('body', 'black', roundedBox(0.10, 0.09, 0.13, 0.008, V(0, 0.62, -0.68)));
for (const sx of [-1, 1]) add('body', sx > 0 ? 'red_lens' : 'black', rod(V(sx * 0.025, 0.665, -0.66), V(sx * 0.025, 0.68, -0.66), 0.007, 10));
SUB = 'tail_lamp';
add('body', 'red_lens', roundedBox(0.14, 0.035, 0.03, 0.01, V(0, 0.75, -0.955)));
SUB = 'indicators_rear';
for (const sx of [-1, 1]) add('body', 'amber_lens', ball(V(sx * 0.07, 0.715, -0.95), 0.02, 1.1, 0.6, 0.8));
SUB = 'grab_rail';
for (const sx of [-1, 1]) add('body', 'alloy', tube([V(sx * 0.15, 0.80, -0.50), V(sx * 0.15, 0.82, -0.70), V(sx * 0.10, 0.83, -0.86), V(0, 0.83, -0.90)], 0.013, 30, 10));
SUB = 'rear_mudguard';
{
  const r0 = TR.R + 0.03, w = 0.08, prof = [];
  for (let i = 0; i <= 10; i++) { const a = -w + 2 * w * i / 10; prof.push([r0, a]); }
  add('body', 'plastic', aroundX(prof, AR.x, AR.y, AR.z, 40, -Math.PI * 1.15, Math.PI * 0.55));
}
SUB = 'number_plate';
add('body', 'plastic', roundedBox(0.16, 0.012, 0.16, 0.01, V(0, 0.55, -0.92)));
{ const pl = roundedBox(0.20, 0.15, 0.006, 0.01, V(0, 0, 0)); pl.rotateX(-0.15); pl.translate(0, 0.47, -1.005); add('body', 'plate', pl); }
SUB = 'footpegs';
for (const sx of [-1, 1]) add('body', 'black', roundedBox(0.07, 0.015, 0.05, 0.005, V(sx * 0.215, 0.36, -0.24)));   // pillion pegs, folded out
SUB = 'kick_panel';
add('body', 'plastic', roundedBox(0.30, 0.10, 0.03, 0.01, V(0, 0.20, -0.17)));

// the stands: a side stand on the left, a centre stand under the engine
const STAND_PIVOT = V(0.14, 0.19, -0.12);
const STAND_FOLDED = V(0.05, 0.15, -1).normalize(), STAND_DOWN = V(0.30, -0.93, 0.20).normalize();
SUB = 'side_stand';
add('stand', 'black', rod(STAND_PIVOT, STAND_PIVOT.clone().addScaledVector(STAND_FOLDED, 0.24), 0.01));
add('stand', 'black', ball(STAND_PIVOT.clone().addScaledVector(STAND_FOLDED, 0.25), 0.018, 1.3, 0.6, 1.3));
const CSP = V(0, 0.20, -0.26);
const CS_FOLDED = V(0, 0.25, -1).normalize(), CS_DOWN = V(0, -1, -0.12).normalize();
SUB = 'centre_stand';
for (const sx of [-1, 1]) add('centre_stand', 'black', rod(CSP.clone().add(V(sx * 0.10, 0, 0)), CSP.clone().add(V(sx * 0.13, 0, 0)).addScaledVector(CS_FOLDED, 0.205), 0.011));
add('centre_stand', 'black', rod(CSP.clone().add(V(-0.13, 0, 0)).addScaledVector(CS_FOLDED, 0.20), CSP.clone().add(V(0.13, 0, 0)).addScaledVector(CS_FOLDED, 0.20), 0.011));
add('centre_stand', 'black', rod(CSP.clone().add(V(-0.12, 0, 0)), CSP.clone().add(V(0.12, 0, 0)), 0.012));

// the seat: the rider's dip and the pillion, on a hinge at its front
const SEAT_PIVOT = V(0, 0.735, -0.06);
SUB = 'seat';
add('seat_hinge', 'seat', lofted(u => {
  const z = -0.05 - 0.78 * u, rider = u < 0.55;
  return { z, w: rider ? 0.14 + 0.03 * Math.sin(Math.PI * u / 0.55) : 0.15 - 0.06 * (u - 0.55) / 0.45,
    yt: rider ? B.seat + 0.01 * Math.sin(Math.PI * u / 0.55) ** 2 : B.seat + 0.035, yb: 0.735, e: 0.45 };
}, 40, 36, true));

// ── hierarchy and clips ─────────────────────────────────────────────────
const PIVOT = { steer: axisAt(T_HEAD0 + 0.08), wheel_f: AF.clone(), wheel_r: AR.clone(), stand: STAND_PIVOT.clone(),
  centre_stand: CSP.clone(), seat_hinge: SEAT_PIVOT.clone() };
const PARENT = { steer: null, wheel_f: 'steer', wheel_r: null, stand: null, centre_stand: null, seat_hinge: null };
const SPLIT = !!args.parts;
const pieceName = (part, sub) => part.startsWith('wheel_') && ['tyre', 'rim', 'disc', 'drum'].includes(sub) ? `${sub}_${part.slice(-1)}` : sub;
const X = V(1, 0, 0), SEAT_DEG = 70, STEER = 35;
const { tris } = await writeBike({
  out: OUT, scale: +(args.scale || 1), sceneName: 'scooter', mats: MATS, pieces: parts, pivots: PIVOT, parents: PARENT, split: SPLIT, pieceName,
  doubleSided: ['screen'], pivotExtras: { seat_hinge: { axis: [1, 0, 0], open_deg: SEAT_DEG } },
  extras: { kind: 'motorbike', model: B.name, wheelbase_m: B.wheelbase, length_m: B.length, rake_deg: B.rake, trail_m: B.trail,
    tyres: [`${B.front_tyre[0]}/${B.front_tyre[1]}-${B.front_rim}`, `${B.rear_tyre[0]}/${B.rear_tyre[1]}-${B.rear_rim}`],
    clips: ['wheels_spin', 'steer_left', 'steer_right', 'stand_down', 'centre_stand_down', 'seat_open'], generator: 'bikes/scooter.mjs',
    engine_note: 'Modelled in code by the machine: a liquid-cooled single, its cylinder lying forward, driving the rear wheel '
      + 'through a belt CVT in the case on the left; engine and case swing together with the rear wheel (a unit-swing engine).',
    pivots: { steer: 'the bars and their cover, the fork, front wheel, disc and caliper turn about the raked steering axis',
      wheel_f: 'the front wheel turns on its axle', wheel_r: 'the rear wheel turns on its axle',
      stand: 'the side stand swings down', centre_stand: 'the centre stand swings down',
      seat_hinge: 'the seat lifts on its front hinge over the storage bin' } },
  order: ['steer', 'wheel_r', 'wheel_f', 'stand', 'centre_stand', 'seat_hinge'],
  meshOrder: ['body', 'steer', 'wheel_f', 'wheel_r', 'stand', 'centre_stand', 'seat_hinge'],
  clips: (nodes, clip, q) => {
    const spin = [0, 90, 180, 270, 360].map(d => q(X, d));
    clip('wheels_spin', [[nodes.wheel_f, [0, 0.25, 0.5, 0.75, 1], spin], [nodes.wheel_r, [0, 0.25, 0.5, 0.75, 1], spin]]);
    clip('steer_left', [[nodes.steer, [0, 1], [q(U, 0), q(U, STEER)]]]);
    clip('steer_right', [[nodes.steer, [0, 1], [q(U, 0), q(U, -STEER)]]]);
    clip('stand_down', [[nodes.stand, [0, 1], [[0, 0, 0, 1], new THREE.Quaternion().setFromUnitVectors(STAND_FOLDED, STAND_DOWN).toArray()]]]);
    clip('centre_stand_down', [[nodes.centre_stand, [0, 1], [[0, 0, 0, 1], new THREE.Quaternion().setFromUnitVectors(CS_FOLDED, CS_DOWN).toArray()]]]);
    clip('seat_open', [[nodes.seat_hinge, [0, 1], [q(X, 0), q(X, SEAT_DEG)]]]);
  },
  copyright: `${B.name}: modelled in code by the ExpertCarCheck GLB machine (bikes/scooter.mjs), to the published sizes. No maker's model, badge or lettering.`,
});
const L = (AF.z + TF.R + 0.02) - (-1.01);
console.log(JSON.stringify({ wrote: OUT, triangles: Math.round(tris), parts: [...new Set(parts.map(p => p[0]))],
  pieces: SPLIT ? [...new Set(parts.map(p => pieceName(p[0], p[3] || p[0])))] : undefined,
  front_tyre_d_m: +(2 * TF.R).toFixed(3), rear_tyre_d_m: +(2 * TR.R).toFixed(3), length_m: +L.toFixed(3),
  fork_offset_m: +new THREE.Vector3().subVectors(AF, G).dot(N).toFixed(3) }));
