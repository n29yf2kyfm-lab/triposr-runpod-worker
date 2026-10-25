// sports.mjs — a 600 cc supersport motorbike modelled in code (three.js
// geometry, written as glTF by gltf-transform, as cruiser.mjs): no
// downloaded model, so the file is wholly ExpertCarCheck's. Its sizes are a
// real bike's published figures (the SUPERSPORT preset, an R6-style 600:
// wheelbase, length, rake, trail, seat height, tyre sizes); its parts move:
//   wheels_spin   both wheels turn (a loop)
//   steer_left    the fork, clip-on bars, front wheel, discs and calipers
//   steer_right   turn about the raked steering axis (the fairing does not)
//   stand_down    the side stand swings down
// With --parts every piece is its own named node (twin-spar frame,
// swingarm, monoshock, the inline four's crankcase, block, head and covers,
// radiator, exhaust, chain, fairings, tank, seats, lamps ...), each under
// the pivot it moves with, so a trainer can take any one off.
// No maker's badge or lettering is modelled.
//
//   node pipeline/realcar/bikes/sports.mjs out.glb [--paint=#1b3a8c] [--name="..."] [--parts]
//
// Frame: +Y up, nose +Z, the rider's left +X, metres, ground at y = 0.
// ExpertCarCheck. Proprietary: see ../LICENSE.
import * as THREE from 'three';
import { ParametricGeometry } from 'three/addons/geometries/ParametricGeometry.js';
import { cli, V, UPY, rod, tube, ball, aroundX, roundedBox, sidePanel, lofted, beam, sprocketOutline, helix, sweptBox,
  hex, tyreOf, tyreGeometry, castWheel, brakeDisc, writeBike } from './kit.mjs';

// ── the bike's figures ───────────────────────────────────────────────────
// a 599 cc inline-four supersport of the 2017-on R6 kind, from the maker's
// published specification: 1,375 mm wheelbase, 2,040 mm long, 24 deg rake,
// 97 mm trail, 850 mm seat, 120/70ZR17 front and 180/55ZR17 rear tyres
export const SUPERSPORT = {
  name: 'Supersport (600 cc inline four)', wheelbase: 1.375, length: 2.040, rake: 24, trail: 0.097,
  seat: 0.850, rim: 17, front_tyre: [120, 70], rear_tyre: [180, 55],
};

const { out: OUT, args } = cli('usage: node sports.mjs out.glb [--paint=#hex] [--name=...] [--parts]');
const B = { ...SUPERSPORT, ...(args.name ? { name: args.name } : {}) };

const TF = tyreOf(B.rim, B.front_tyre), TR = tyreOf(B.rim, B.rear_tyre);
const ZF = B.wheelbase / 2, ZR = -B.wheelbase / 2;
const AF = V(0, TF.R, ZF), AR = V(0, TR.R, ZR);                       // axles
// the steering axis meets the ground TRAIL ahead of the front contact patch
const rk = THREE.MathUtils.degToRad(B.rake);
const U = V(0, Math.cos(rk), -Math.sin(rk)), N = V(0, Math.sin(rk), Math.cos(rk));
const G = V(0, 0, ZF + B.trail);
const axisAt = t => G.clone().addScaledVector(U, t);
const forkAt = (s, x) => V(x, AF.y, AF.z).addScaledVector(U, s);   // a fork leg's centre line (offset built in)
const T_HEAD0 = 0.80, T_HEAD1 = 0.96;
const S_CLAMP0 = (axisAt(T_HEAD0).y - AF.y) / U.y, S_CLAMP1 = (axisAt(T_HEAD1).y - AF.y) / U.y;
const FORK_X = 0.105;
const SP = V(0, 0.42, -0.11);                                         // swingarm pivot

// ── materials ────────────────────────────────────────────────────────────
const MATS = {
  paint: { color: hex(args.paint || '#1b3a8c'), metal: 0.0, rough: 0.25, clearcoat: 1 },
  white: { color: hex('#e9eaec'), metal: 0.0, rough: 0.3, clearcoat: 1 },
  black: { color: [0.018, 0.018, 0.02], metal: 0.2, rough: 0.5 },
  gloss_black: { color: [0.01, 0.01, 0.012], metal: 0.0, rough: 0.15, clearcoat: 1 },
  frame_alloy: { color: [0.62, 0.63, 0.65], metal: 1, rough: 0.38 },
  cast: { color: [0.16, 0.16, 0.17], metal: 0.7, rough: 0.5 },
  alloy: { color: [0.80, 0.81, 0.82], metal: 1, rough: 0.3 },
  gold: { color: [0.83, 0.62, 0.22], metal: 1, rough: 0.28 },
  chrome: { color: [0.92, 0.92, 0.93], metal: 1, rough: 0.07 },
  steel: { color: [0.55, 0.50, 0.46], metal: 1, rough: 0.35 },
  titanium: { color: [0.48, 0.48, 0.50], metal: 1, rough: 0.25 },
  spring: { color: [0.85, 0.12, 0.08], metal: 0.3, rough: 0.35 },
  radiator: { color: [0.08, 0.08, 0.09], metal: 0.6, rough: 0.6 },
  rubber: { color: [0.025, 0.025, 0.027], metal: 0, rough: 0.92 },
  seat: { color: [0.03, 0.03, 0.032], metal: 0, rough: 0.7 },
  lamp: { color: [0.9, 0.92, 0.95], metal: 0, rough: 0.05, emissive: [1, 0.98, 0.92], strength: 2 },
  red_lens: { color: [0.55, 0.02, 0.02], metal: 0, rough: 0.1, emissive: [0.6, 0.0, 0.0], strength: 1 },
  amber_lens: { color: [0.9, 0.42, 0.02], metal: 0, rough: 0.1, emissive: [0.5, 0.2, 0.0], strength: 1 },
  mirror: { color: [0.95, 0.95, 0.97], metal: 1, rough: 0.02 },
  screen: { color: [0.12, 0.13, 0.15], metal: 0, rough: 0.05, alpha: 0.45 },
  plate: { color: [0.93, 0.93, 0.90], metal: 0, rough: 0.4 },
};

// ── pieces: [part, material, geometry in world space, piece name] ───────
const parts = [];
let SUB = null;
const add = (part, mat, g) => { parts.push([part, mat, g, SUB]); return g; };
const turnTo = (g, dir, at) => {                       // a +Y-built shape stood along dir, at a point
  g.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(UPY, dir.clone().normalize())); g.translate(at.x, at.y, at.z); return g;
};

// ── wheels ───────────────────────────────────────────────────────────────
function wheel(part, A, T, rimHalf) {
  SUB = 'tyre'; add(part, 'rubber', tyreGeometry(A, T));
  const [hub, rim, spokes] = castWheel(A, T, rimHalf, 5, true);
  SUB = 'rim'; add(part, 'black', rim); add(part, 'black', spokes); add(part, 'alloy', hub);
}
wheel('wheel_f', AF, TF, 0.045);
wheel('wheel_r', AR, TR, 0.070);
// twin 320 mm front discs inside the fork legs; a 220 mm rear disc on the right
SUB = 'disc';
for (const sx of [-1, 1]) {
  add('wheel_f', 'chrome', brakeDisc(AF, sx * 0.068, 0.160, 0.118));
  add('wheel_f', 'gold', aroundX([[0.06, -0.003], [0.118, -0.003], [0.118, 0.003], [0.06, 0.003]], sx * 0.064, AF.y, AF.z, 48));
}
add('wheel_r', 'chrome', brakeDisc(AR, -0.082, 0.110, 0.070));
// the rear sprocket on the left, 43 teeth
SUB = 'sprocket_r';
add('wheel_r', 'alloy', sidePanel(sprocketOutline(AR.z, AR.y, 0.112, 43), 0.084, 0.007, 1, 0.0015));

// ── the front end (steers) ───────────────────────────────────────────────
// upside-down fork: the thick gold tubes on top in the clamps, the thin
// chrome stanchions below into the axle clamps
for (const sx of [-1, 1]) {
  const x = sx * FORK_X;
  SUB = 'fork';
  add('steer', 'chrome', rod(forkAt(0.02, x), forkAt(0.25, x), 0.0215, 28));
  add('steer', 'gold', rod(forkAt(0.22, x), forkAt(S_CLAMP1 + 0.035, x), 0.029, 32));
  add('steer', 'black', rod(forkAt(-0.035, x), forkAt(0.055, x), 0.027, 24));           // axle clamp
  add('steer', 'alloy', ball(forkAt(S_CLAMP1 + 0.04, x), 0.02, 1, 0.5, 1));            // preload adjuster
  // radial calipers bolted to the back of each axle clamp, over the disc
  SUB = 'caliper_front';
  const c = AF.clone().add(V(sx * 0.068, 0.095, -0.075));
  const cal = roundedBox(0.032, 0.115, 0.05, 0.01, V(0, 0, 0));
  cal.rotateX(-0.75); cal.translate(c.x, c.y, c.z);
  add('steer', 'gold', cal);
}
SUB = 'fork';
add('steer', 'alloy', rod(V(-FORK_X - 0.035, AF.y, AF.z), V(FORK_X + 0.035, AF.y, AF.z), 0.012));   // axle
for (const s of [S_CLAMP0, S_CLAMP1]) {                                                      // triple clamps
  const c = forkAt(s, 0).addScaledVector(N, -0.02);
  const g = roundedBox(2 * FORK_X + 0.085, 0.03, 0.09, 0.012, V(0, 0, 0));
  g.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(UPY, U)); g.translate(c.x, c.y, c.z);
  add('steer', s === S_CLAMP1 ? 'alloy' : 'black', g);
}
// clip-on bars under the top clamp: short, low, swept back and down
{
  SUB = 'handlebar';
  for (const sx of [-1, 1]) {
    const p0 = forkAt(S_CLAMP1 - 0.035, sx * FORK_X), p1 = p0.clone().add(V(sx * 0.20, -0.035, -0.085));
    add('steer', 'alloy', rod(p0, p0.clone().add(V(sx * 0.04, -0.004, -0.015)), 0.034, 20));      // the clamp
    add('steer', 'black', rod(p0.clone().add(V(sx * 0.035, -0.003, -0.012)), p1, 0.011, 16));
    add('steer', 'rubber', rod(p0.clone().lerp(p1, 0.45), p1.clone().add(V(sx * 0.03, -0.006, -0.012)), 0.017, 18));  // grip
    add('steer', 'black', roundedBox(0.045, 0.04, 0.055, 0.01, p0.clone().lerp(p1, 0.32).add(V(0, 0.012, 0.01))));  // switches
    add('steer', 'alloy', tube([p0.clone().lerp(p1, 0.3).add(V(0, 0.015, 0.035)), p0.clone().lerp(p1, 0.7).add(V(0, 0.01, 0.075)),
      p1.clone().add(V(sx * 0.03, 0.0, 0.06))], 0.006, 16, 8));                                   // levers
    if (sx < 0) add('steer', 'black', rod(p0.clone().lerp(p1, 0.3).add(V(0, 0.02, 0.02)), p0.clone().lerp(p1, 0.3).add(V(0, 0.08, 0.03)), 0.018, 16)); // brake reservoir
  }
}
// the short front mudguard between the legs
{
  SUB = 'mudguard_front';
  const r0 = TF.R + 0.018, w = 0.068, prof = [];
  for (let i = 0; i <= 12; i++) { const a = -w + 2 * w * i / 12; prof.push([r0 + 0.01 * (1 - (a / w) ** 2), a]); }
  add('steer', 'paint', aroundX(prof, AF.x, AF.y, AF.z, 48, -Math.PI * 0.80, Math.PI * 0.55));
}

// ── the frame: twin aluminium spars round the engine ────────────────────
const headTop = axisAt(T_HEAD1), headBot = axisAt(T_HEAD0);
SUB = 'frame';
add('body', 'frame_alloy', rod(headBot.clone().addScaledVector(U, -0.025), headTop.clone().addScaledVector(U, 0.025), 0.034, 28));  // steering head
for (const sx of [-1, 1]) {
  add('body', 'frame_alloy', sweptBox([V(sx * 0.03, 0.82, 0.40), V(sx * 0.13, 0.80, 0.30), V(sx * 0.175, 0.75, 0.12),
    V(sx * 0.17, 0.66, -0.03), V(sx * 0.135, 0.55, -0.10), V(sx * 0.125, 0.43, -0.115)], 0.045, 0.11, 90));
  add('body', 'frame_alloy', sweptBox([V(sx * 0.03, 0.74, 0.43), V(sx * 0.12, 0.62, 0.33), V(sx * 0.15, 0.52, 0.22)], 0.035, 0.06, 40)); // engine hanger
  add('body', 'frame_alloy', roundedBox(0.03, 0.22, 0.12, 0.012, V(sx * 0.13, 0.42, -0.11)));       // pivot plate
}
add('body', 'frame_alloy', rod(V(-0.15, 0.62, -0.06), V(0.15, 0.62, -0.06), 0.02, 16));               // cross member
SUB = 'subframe';
for (const sx of [-1, 1]) {
  add('body', 'black', tube([V(sx * 0.12, 0.76, -0.08), V(sx * 0.10, 0.82, -0.40), V(sx * 0.07, 0.88, -0.78)], 0.012, 40, 10));
  add('body', 'black', tube([V(sx * 0.13, 0.56, -0.13), V(sx * 0.11, 0.70, -0.36), V(sx * 0.08, 0.84, -0.60)], 0.010, 40, 10));
}
// the braced swingarm, the axle in its ends
SUB = 'swingarm';
for (const sx of [-1, 1]) {
  add('body', 'frame_alloy', beam(V(sx * 0.115, SP.y, SP.z), V(sx * 0.11, AR.y, AR.z + 0.02), 0.035, 0.085));
  add('body', 'black', roundedBox(0.04, 0.05, 0.07, 0.012, V(sx * 0.11, AR.y, AR.z)));             // chain adjuster
}
add('body', 'frame_alloy', beam(V(-0.10, SP.y + 0.02, SP.z - 0.16), V(-0.10, AR.y + 0.10, AR.z + 0.20), 0.025, 0.045));  // the brace, right
add('body', 'frame_alloy', rod(V(-0.12, SP.y - 0.01, SP.z - 0.12), V(0.12, SP.y - 0.01, SP.z - 0.12), 0.028, 16));
add('body', 'alloy', rod(V(-0.15, SP.y, SP.z), V(0.15, SP.y, SP.z), 0.012));                        // pivot spindle
add('body', 'alloy', rod(V(-0.135, AR.y, AR.z), V(0.135, AR.y, AR.z), 0.011));                      // rear axle
// the monoshock, upright behind the engine, on its rising-rate linkage
SUB = 'rear_shock';
{
  const lo = V(0, 0.33, -0.17), hi = V(0, 0.63, -0.10);
  add('body', 'black', rod(lo, hi, 0.022, 20));
  add('body', 'spring', helix(lo.clone().lerp(hi, 0.18), lo.clone().lerp(hi, 0.82), 0.033, 0.0055, 8));
  add('body', 'gold', rod(hi.clone().lerp(lo, 0.05), hi.clone().lerp(lo, 0.35), 0.026, 20));       // the body
  add('body', 'black', rod(V(-0.05, 0.31, -0.20), V(0.05, 0.31, -0.20), 0.012));
  add('body', 'black', beam(V(0, 0.31, -0.20), V(0, 0.37, -0.05), 0.04, 0.03));                    // linkage
}

// ── the inline four: cylinders leaning forward 30 degrees ───────────────
const TILT = THREE.MathUtils.degToRad(30), D = V(0, Math.cos(TILT), Math.sin(TILT));
const CB = V(0, 0.40, 0.14);                                     // the block's base on the crankcase
const along = s => CB.clone().addScaledVector(D, s);
const leaning = (w, h, d, r, s) => { const g = roundedBox(w, h, d, r, V(0, 0, 0)); g.rotateX(TILT); const c = along(s); g.translate(c.x, c.y, c.z); return g; };
SUB = 'crankcase';
add('body', 'cast', roundedBox(0.42, 0.21, 0.34, 0.05, V(0, 0.33, 0.07)));
SUB = 'gearbox';
add('body', 'cast', roundedBox(0.30, 0.19, 0.20, 0.04, V(0, 0.35, -0.10)));
SUB = 'sump';
add('body', 'black', roundedBox(0.30, 0.07, 0.24, 0.02, V(0, 0.20, 0.10)));
add('body', 'alloy', rod(V(0, 0.16, 0.08), V(0, 0.18, 0.08), 0.012, 12));                           // drain plug
SUB = 'cylinder_block';
add('body', 'cast', leaning(0.36, 0.16, 0.13, 0.02, 0.08));
for (let k = 0; k < 6; k++) add('body', 'cast', leaning(0.37, 0.006, 0.14, 0.002, 0.025 + k * 0.022));
SUB = 'cylinder_head';
add('body', 'cast', leaning(0.37, 0.085, 0.15, 0.02, 0.205));
SUB = 'cam_cover';
add('body', 'gloss_black', leaning(0.33, 0.055, 0.13, 0.022, 0.27));
SUB = 'spark_plugs';
for (const x of [-0.135, -0.045, 0.045, 0.135]) add('body', 'black', rod(along(0.29).add(V(x, 0, 0)), along(0.32).add(V(x, 0, 0)), 0.014, 14));
SUB = 'clutch_cover';
add('body', 'cast', aroundX([[0, -0.018], [0.10, -0.018], [0.112, -0.004], [0.112, 0.012], [0.098, 0.018], [0, 0.018]], -0.228, 0.34, -0.06, 48));
SUB = 'alternator_cover';
add('body', 'cast', aroundX([[0, -0.016], [0.078, -0.016], [0.088, -0.002], [0.088, 0.01], [0.076, 0.016], [0, 0.016]], 0.226, 0.34, 0.12, 48));
SUB = 'oil_filter';
add('body', 'black', turnTo(new THREE.CylinderGeometry(0.035, 0.035, 0.085, 32), V(0, -0.4, 1), V(0.08, 0.235, 0.245)));
SUB = 'sprocket_front';
add('body', 'alloy', sidePanel(sprocketOutline(-0.03, 0.36, 0.036, 16), 0.084, 0.007, 1, 0.0015));
add('body', 'black', roundedBox(0.02, 0.11, 0.13, 0.015, V(0.11, 0.36, -0.03)));                   // sprocket cover
// air: four throttle bodies from the head's back up into the airbox under the tank
SUB = 'throttle_bodies';
for (const x of [-0.135, -0.045, 0.045, 0.135]) add('body', 'alloy', rod(along(0.21).add(V(x, 0.01, -0.07)), V(x, 0.72, 0.10), 0.019, 16));
SUB = 'airbox';
add('body', 'black', roundedBox(0.32, 0.12, 0.27, 0.04, V(0, 0.775, 0.09)));
// cooling: the radiator behind the front wheel, its hoses to the head
SUB = 'radiator';
{
  const r = roundedBox(0.40, 0.27, 0.04, 0.01, V(0, 0, 0)); r.rotateX(-0.30); r.translate(0, 0.60, 0.385);
  add('body', 'radiator', r);
  for (const sx of [-1, 1]) add('body', 'black', roundedBox(0.012, 0.29, 0.06, 0.004, V(sx * 0.205, 0.60, 0.385)));    // side tanks
}
SUB = 'coolant_hoses';
add('body', 'black', tube([V(0.14, 0.72, 0.36), V(0.15, 0.70, 0.30), along(0.22).add(V(0.17, 0, 0.02))], 0.013, 24, 10));
add('body', 'black', tube([V(-0.14, 0.48, 0.38), V(-0.17, 0.40, 0.30), V(-0.20, 0.36, 0.20)], 0.013, 24, 10));
// exhaust: four headers forward and down round the front, a collector
// under the engine and a short silencer up on the right
SUB = 'exhaust_headers';
for (const [i, x] of [-0.135, -0.045, 0.045, 0.135].entries()) {
  const port = along(0.21).add(V(x, -0.02, 0.07));
  add('body', 'steel', tube([port, port.clone().add(V(0, -0.06, 0.05)), V(x * 0.95, 0.38, 0.37), V(x * 0.8, 0.22, 0.33 - 0.01 * i),
    V(x * 0.45, 0.13, 0.20), V(x * 0.15, 0.12, 0.04), V(-0.02, 0.13, -0.04)], 0.018, 80, 12));
}
SUB = 'silencer';
add('body', 'steel', tube([V(-0.02, 0.13, -0.04), V(-0.10, 0.15, -0.14), V(-0.16, 0.22, -0.22)], 0.026, 30, 12));
add('body', 'titanium', rod(V(-0.165, 0.24, -0.23), V(-0.19, 0.40, -0.52), 0.056, 40, 0.05));
{ const cap = new THREE.CylinderGeometry(0.05, 0.057, 0.03, 40); turnTo(cap, V(-0.025, 0.16, -0.29), V(-0.19, 0.405, -0.53)); add('body', 'gloss_black', cap); }
// the chain on the left, from the front sprocket round the rear
SUB = 'chain';
{
  const f = V(0.088, 0.36, -0.03), rr = 0.112, fr = 0.036, pts = [];
  const ang = Math.atan2(f.y - AR.y, f.z - AR.z), d = Math.hypot(f.y - AR.y, f.z - AR.z);
  const tilt = Math.asin((rr - fr) / d);
  for (let i = 0; i <= 24; i++) { const a = ang + Math.PI / 2 + tilt + (Math.PI - 2 * tilt) * i / 24; pts.push(V(0.088, AR.y + rr * Math.sin(a), AR.z + rr * Math.cos(a))); }
  for (let i = 0; i <= 12; i++) { const a = ang - Math.PI / 2 - tilt + (Math.PI + 2 * tilt) * i / 12; pts.push(V(0.088, f.y + fr * Math.sin(a), f.z + fr * Math.cos(a))); }
  pts.push(pts[0].clone());
  add('body', 'black', tube(pts, 0.005, 200, 6));
}

// ── bodywork ─────────────────────────────────────────────────────────────
// the nose: a shell over the steering head, closed over the top up to the
// screen, open behind it (the cockpit: the clamps and the dash show)
SUB = 'fairing_upper';
const NOSE = z => {                                  // the fairing's section at z
  const t = Math.min(1, Math.max(0, (0.90 - z) / 0.28));          // 0 at the tip, 1 by the screen base
  return { w: 0.05 + 0.21 * t ** 0.55, yt: 0.85 + 0.13 * t ** 0.6, yb: 0.78 - 0.13 * t ** 0.8, e: 0.72 };
};
add('body', 'paint', lofted(u => { const z = 0.90 - 0.42 * u; return { z, ...NOSE(z), a0: -0.35, a1: Math.PI + 0.35 }; }, 36, 44));
SUB = 'headlamps';
for (const sx of [-1, 1]) {
  const l = ball(V(sx * 0.072, 0.805, 0.84), 0.045, 1.15, 0.40, 0.55); l.rotateY(-sx * 0.40); l.translate(0, 0, 0); add('body', 'lamp', l);
}
SUB = 'windscreen';
add('body', 'screen', new ParametricGeometry((u, v, t) => {
  const x = (u - 0.5) * 0.30 * (1 - 0.35 * v), z = 0.74 - 0.24 * v, y = 0.975 + 0.15 * v + 0.025 * Math.cos(Math.PI * (u - 0.5));
  t.set(x, y, z);
}, 24, 12));
SUB = 'dash';
add('body', 'gloss_black', roundedBox(0.16, 0.07, 0.05, 0.012, V(0, 0.99, 0.50)));
SUB = 'mirrors';
for (const sx of [-1, 1]) {
  add('body', 'black', rod(V(sx * 0.25, 0.96, 0.58), V(sx * 0.30, 1.01, 0.56), 0.008, 10));
  add('body', 'paint', ball(V(sx * 0.32, 1.02, 0.555), 0.05, 1.2, 0.6, 0.45));
  const m = new THREE.CircleGeometry(0.04, 24); m.scale(1.15, 0.6, 1); m.rotateY(Math.PI); m.translate(sx * 0.32, 1.02, 0.535);
  add('body', 'mirror', m);
}
SUB = 'indicators_front';
for (const sx of [-1, 1]) add('body', 'amber_lens', ball(V(sx * 0.205, 0.83, 0.62), 0.022, 0.6, 0.5, 1.4));
// the lowers, left and right: curved shells round the radiator and the
// headers from the nose back past the cylinders; the engine's covers show
// (seen from the side: the front edge slopes back down behind the front
// wheel, the top rises to the tank, the back edge leans forward)
const lerpIn = (t, ks) => {                          // piecewise-linear through [t, value] knots
  for (let i = 1; i < ks.length; i++) if (t <= ks[i][0]) {
    const [t0, v0] = ks[i - 1], [t1, v1] = ks[i]; return v0 + (v1 - v0) * (t - t0) / (t1 - t0);
  }
  return ks[ks.length - 1][1];
};
const LOWER = z => {
  const t = (0.62 - z) / 0.52;                       // 0 at the front, 1 at the back
  return { w: 0.20 + 0.05 * Math.sin(Math.PI * Math.min(1, t * 1.3)) ** 0.5,
    yt: lerpIn(t, [[0, 0.80], [0.2, 0.86], [0.75, 0.86], [1, 0.70]]),
    yb: lerpIn(t, [[0, 0.70], [0.18, 0.42], [0.4, 0.24], [0.8, 0.24], [1, 0.36]]), e: 0.75 };
};
for (const [nm, a0, a1] of [['fairing_left', -1.30, 0.62], ['fairing_right', Math.PI - 0.62, Math.PI + 1.30]]) {
  SUB = nm;
  add('body', 'paint', lofted(u => { const z = 0.62 - 0.52 * u; return { z, ...LOWER(z), a0, a1 }; }, 40, 30));
  // a white flash along it
  add('body', 'white', lofted(u => {
    const z = 0.50 - 0.30 * u, L = LOWER(z), yc = (L.yt + L.yb) / 2;
    return { z, w: L.w + 0.003, yt: yc + 0.03 - 0.06 * u, yb: yc - 0.05 - 0.05 * u, e: 0.75, a0: a0 + 0.55 * (a0 < 1 ? 1 : 0), a1: a1 - 0.55 * (a0 < 1 ? 0 : 1) };
  }, 16, 10));
}
SUB = 'belly_pan';
add('body', 'paint', lofted(u => ({ z: 0.36 - 0.40 * u, w: 0.17 - 0.05 * u, yt: 0.24 - 0.04 * u, yb: 0.10 + 0.02 * u, e: 0.5 }), 24, 32, true));
// the tank over the spars, the rider's seat, the pillion cowl
SUB = 'tank';
add('body', 'paint', lofted(u => {
  const z = 0.33 - 0.52 * u;
  return { z, w: 0.09 + 0.11 * Math.sin(Math.PI * Math.min(1, 0.15 + u * 0.95)) ** 0.7, yt: 0.90 + 0.12 * Math.sin(Math.PI * (0.2 + 0.8 * u)) ** 0.6 - 0.06 * u,
    yb: 0.80 - 0.01 * u, e: 0.55 };
}, 40, 40, true));
SUB = 'fuel_cap';
add('body', 'alloy', turnTo(new THREE.CylinderGeometry(0.035, 0.037, 0.01, 32), V(0, 1, 0.25), V(0, 1.025, 0.16)));
SUB = 'seat';
add('body', 'seat', lofted(u => ({ z: -0.17 - 0.30 * u, w: 0.135 - 0.03 * u, yt: B.seat + 0.005 + 0.02 * u, yb: 0.79 + 0.01 * u, e: 0.45 }), 24, 32, true));
SUB = 'tail_unit';
add('body', 'paint', lofted(u => {
  const z = -0.42 - 0.58 * u;
  return { z, w: 0.15 - 0.10 * u ** 0.8, yt: 0.90 + 0.08 * Math.min(1, u * 1.5), yb: 0.77 + 0.14 * u, e: 0.6 };
}, 32, 36, true));
// the side covers under the seat, over the subframe and the battery
for (const [nm, a0, a1] of [['side_cover_left', -1.1, 0.75], ['side_cover_right', Math.PI - 0.75, Math.PI + 1.1]]) {
  SUB = nm;
  add('body', 'paint', lofted(u => {
    const z = -0.14 - 0.36 * u;
    return { z, w: 0.135 - 0.03 * u, yt: 0.80 + 0.02 * u, yb: 0.62 + 0.14 * u ** 1.4, e: 0.7, a0, a1 };
  }, 20, 16));
}
SUB = 'pillion_seat';
add('body', 'seat', lofted(u => ({ z: -0.50 - 0.20 * u, w: 0.10 - 0.02 * u, yt: 0.955 + 0.015 * u, yb: 0.93, e: 0.4 }), 16, 28, true));
SUB = 'tail_lamp';
add('body', 'red_lens', roundedBox(0.09, 0.03, 0.03, 0.01, V(0, 0.935, -0.99)));
SUB = 'number_plate';
add('body', 'black', tube([V(0, 0.84, -0.80), V(0, 0.76, -0.93), V(0, 0.70, -1.00)], 0.012, 20, 8));
{ const pl = roundedBox(0.20, 0.15, 0.006, 0.01, V(0, 0, 0)); pl.rotateX(-0.25); pl.translate(0, 0.64, -1.015); add('body', 'plate', pl); }
SUB = 'indicators_rear';
for (const sx of [-1, 1]) {
  add('body', 'black', rod(V(sx * 0.03, 0.72, -0.98), V(sx * 0.11, 0.73, -0.99), 0.006, 8));
  add('body', 'amber_lens', ball(V(sx * 0.125, 0.73, -0.995), 0.018, 1, 0.8, 1.4));
}
SUB = 'hugger';
{
  const r0 = TR.R + 0.02, w = 0.10, prof = [];
  for (let i = 0; i <= 12; i++) { const a = -w + 2 * w * i / 12; prof.push([r0 + 0.008 * (1 - (a / w) ** 2), a]); }
  add('body', 'black', aroundX(prof, AR.x, AR.y, AR.z, 40, -Math.PI * 0.85, Math.PI * 0.42));
}
// rearsets and controls
for (const sx of [-1, 1]) {
  SUB = 'footpegs';
  add('body', 'alloy', roundedBox(0.012, 0.11, 0.09, 0.004, V(sx * 0.15, 0.45, -0.15)));        // heel plate
  add('body', 'alloy', rod(V(sx * 0.15, 0.40, -0.13), V(sx * 0.22, 0.40, -0.135), 0.011, 14));
  add('body', 'alloy', rod(V(sx * 0.12, 0.55, -0.38), V(sx * 0.19, 0.55, -0.39), 0.009, 12));   // pillion pegs
}
SUB = 'brake_pedal';
add('body', 'alloy', tube([V(-0.16, 0.40, -0.12), V(-0.18, 0.37, -0.02), V(-0.19, 0.38, 0.06)], 0.007, 16, 8));
SUB = 'gear_lever';
add('body', 'alloy', tube([V(0.16, 0.42, -0.12), V(0.18, 0.40, -0.02), V(0.19, 0.42, 0.06)], 0.007, 16, 8));
SUB = 'caliper_rear';
add('body', 'black', roundedBox(0.03, 0.06, 0.07, 0.01, V(-0.095, AR.y + 0.085, AR.z + 0.055)));
SUB = 'battery';
add('body', 'black', roundedBox(0.09, 0.09, 0.15, 0.008, V(0, 0.73, -0.30)));
for (const sx of [-1, 1]) add('body', sx > 0 ? 'red_lens' : 'black', rod(V(sx * 0.025, 0.775, -0.25), V(sx * 0.025, 0.79, -0.25), 0.007, 10));

// the side stand, on the left
const STAND_PIVOT = V(0.13, 0.30, -0.05);
const STAND_FOLDED = V(0.10, 0.05, -1).normalize(), STAND_DOWN = V(0.32, -0.92, 0.22).normalize();
SUB = 'side_stand';
add('stand', 'black', rod(STAND_PIVOT, STAND_PIVOT.clone().addScaledVector(STAND_FOLDED, 0.30), 0.011));
add('stand', 'black', ball(STAND_PIVOT.clone().addScaledVector(STAND_FOLDED, 0.31), 0.02, 1.3, 0.6, 1.3));
add('stand', 'alloy', rod(STAND_PIVOT.clone().add(V(-0.015, 0, 0)), STAND_PIVOT.clone().add(V(0.015, 0, 0)), 0.016));

// ── hierarchy and clips ─────────────────────────────────────────────────
const PIVOT = { steer: axisAt(T_HEAD0 + 0.08), wheel_f: AF.clone(), wheel_r: AR.clone(), stand: STAND_PIVOT.clone() };
const PARENT = { steer: null, wheel_f: 'steer', wheel_r: null, stand: null };
const SPLIT = !!args.parts;
const pieceName = (part, sub) => part.startsWith('wheel_') && ['tyre', 'rim', 'disc'].includes(sub) ? `${sub}_${part.slice(-1)}` : sub;
const X = V(1, 0, 0);
const STEER = 28;
const { tris } = await writeBike({
  out: OUT, scale: +(args.scale || 1), sceneName: 'sports', mats: MATS, pieces: parts, pivots: PIVOT, parents: PARENT, split: SPLIT, pieceName,
  doubleSided: ['screen', 'white'],
  extras: { kind: 'motorbike', model: B.name, wheelbase_m: B.wheelbase, length_m: B.length, rake_deg: B.rake, trail_m: B.trail,
    tyres: [`${B.front_tyre[0]}/${B.front_tyre[1]}ZR${B.rim}`, `${B.rear_tyre[0]}/${B.rear_tyre[1]}ZR${B.rim}`],
    clips: ['wheels_spin', 'steer_left', 'steer_right', 'stand_down'], generator: 'bikes/sports.mjs',
    engine_note: 'Modelled in code by the machine: a liquid-cooled inline four, its cylinders leaning forward, with the gearbox '
      + 'behind the crank in the same cases, a chain to the rear wheel, the radiator in front and a four-into-one exhaust.',
    pivots: { steer: 'the fork, clip-on bars, front wheel, discs and calipers turn about the raked steering axis (the fairing stays)',
      wheel_f: 'the front wheel turns on its axle', wheel_r: 'the rear wheel turns on its axle', stand: 'the side stand swings down' } },
  order: ['steer', 'wheel_r', 'wheel_f', 'stand'], meshOrder: ['body', 'steer', 'wheel_f', 'wheel_r', 'stand'],
  clips: (nodes, clip, q) => {
    const spin = [0, 90, 180, 270, 360].map(d => q(X, d));
    clip('wheels_spin', [[nodes.wheel_f, [0, 0.25, 0.5, 0.75, 1], spin], [nodes.wheel_r, [0, 0.25, 0.5, 0.75, 1], spin]]);
    clip('steer_left', [[nodes.steer, [0, 1], [q(U, 0), q(U, STEER)]]]);
    clip('steer_right', [[nodes.steer, [0, 1], [q(U, 0), q(U, -STEER)]]]);
    clip('stand_down', [[nodes.stand, [0, 1], [[0, 0, 0, 1], new THREE.Quaternion().setFromUnitVectors(STAND_FOLDED, STAND_DOWN).toArray()]]]);
  },
  copyright: `${B.name}: modelled in code by the ExpertCarCheck GLB machine (bikes/sports.mjs), to the published sizes. No maker's model, badge or lettering.`,
});
const L = (AF.z + TF.R + 0.02) - (-1.02);
console.log(JSON.stringify({ wrote: OUT, triangles: Math.round(tris), parts: [...new Set(parts.map(p => p[0]))],
  pieces: SPLIT ? [...new Set(parts.map(p => pieceName(p[0], p[3] || p[0])))] : undefined,
  front_tyre_d_m: +(2 * TF.R).toFixed(3), rear_tyre_d_m: +(2 * TR.R).toFixed(3), length_m: +L.toFixed(3),
  fork_offset_m: +new THREE.Vector3().subVectors(AF, G).dot(N).toFixed(3) }));
