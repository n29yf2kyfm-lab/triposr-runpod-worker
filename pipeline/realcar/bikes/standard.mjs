// standard.mjs — the motorbikes that are neither a faired sports bike, a
// cruiser nor a scooter, modelled in code to one bike's published sizes:
// naked roadsters, commuters, adventure and trail bikes, retros, minis,
// tourers and sports tourers. As sports.mjs and cruiser.mjs: no downloaded
// model, so the file is wholly ExpertCarCheck's. A spec gives the bike's
// figures (wheelbase, length, seat height, rake, trail, tyre sizes, engine
// layout and size) and its kind; the kind gives what the spec leaves out
// (its frame, bars, lamp, fairing, exhaust, wheels, luggage), so a Tiger
// 800 and an MT-07 come out as the two kinds of bike they are, each at
// its own size. Its parts move as the others':
//   wheels_spin   both wheels turn (a loop)
//   steer_left    the fork, bars, front wheel, discs and calipers (and a
//   steer_right   fork-mounted lamp) turn about the raked steering axis
//   stand_down    the side stand swings down
// With --parts every piece is its own named node, under the pivot it moves
// with, so a trainer can take any one off. No maker's badge or lettering
// is modelled.
//
//   node pipeline/realcar/bikes/standard.mjs out.glb --spec=bike.json [--paint=#hex] [--name=...] [--parts]
//   node pipeline/realcar/bikes/standard.mjs out.glb --kind=adventure     # the kind's own figures
//
// Frame: +Y up, nose +Z, the rider's left +X, metres, ground at y = 0.
// ExpertCarCheck. Proprietary: see ../LICENSE.
import fs from 'node:fs';
import * as THREE from 'three';
import { ParametricGeometry } from 'three/addons/geometries/ParametricGeometry.js';
import { cli, V, UPY, rod, tube, ball, aroundX, roundedBox, sidePanel, lofted, beam, sprocketOutline, helix, sweptBox,
  hex, tyreOf, tyreGeometry, castWheel, brakeDisc, writeBike } from './kit.mjs';

// ── each kind's figures: a typical bike of the kind, used for whatever the
// spec does not give (sizes in metres, tyres as [rim in, width mm, aspect %])
export const KINDS = {
  naked: { name: 'Naked roadster (parallel twin)', wheelbase: 1.400, length: 2.085, seat: 0.805, rake: 24.8, trail: 0.090,
    front: [17, 120, 70], rear: [17, 180, 55], wheels: 'cast', layout: 'twin', cc: 690, cooling: 'liquid', tilt: 25,
    fairing: 'none', bars: 'upright', bar_half: 0.39, lamp: 'round', exhaust: 'under', tank: 'angular', saddle: 'stepped',
    frame: 'trellis', shock: 'mono', mudguard: 'low', fork: 'usd', luggage: 'none', head: 0.15, clearance: 0.14, travel: 0.13 },
  commuter: { name: 'Commuter (125 cc single)', wheelbase: 1.270, length: 2.010, seat: 0.790, rake: 26.5, trail: 0.092,
    front: [18, 80, 100], rear: [18, 100, 90], wheels: 'cast', layout: 'single', cc: 125, cooling: 'air', tilt: 15,
    fairing: 'none', bars: 'upright', bar_half: 0.34, lamp: 'square', exhaust: 'low', tank: 'angular', saddle: 'bench',
    frame: 'diamond', shock: 'twin', mudguard: 'low', fork: 'conventional', luggage: 'rack', head: 0.14, clearance: 0.16, travel: 0.12 },
  adventure: { name: 'Adventure bike', wheelbase: 1.530, length: 2.215, seat: 0.850, rake: 26.0, trail: 0.105,
    front: [19, 110, 80], rear: [17, 150, 70], wheels: 'spoked', layout: 'triple', cc: 800, cooling: 'liquid', tilt: 20,
    fairing: 'beak', bars: 'wide', bar_half: 0.43, lamp: 'twin', exhaust: 'low', tank: 'big', saddle: 'stepped', screen: 'tall',
    frame: 'trellis', shock: 'mono', mudguard: 'beak', fork: 'usd', luggage: 'panniers', head: 0.19, clearance: 0.20, travel: 0.20,
    guards: true },
  trail: { name: 'Trail bike (single)', wheelbase: 1.465, length: 2.200, seat: 0.895, rake: 27.0, trail: 0.110,
    front: [21, 90, 90], rear: [18, 120, 80], wheels: 'spoked', layout: 'single', cc: 300, cooling: 'liquid', tilt: 12,
    fairing: 'flyscreen', bars: 'wide', bar_half: 0.42, lamp: 'square', exhaust: 'high', tank: 'slim', saddle: 'flat',
    frame: 'cradle', shock: 'mono', mudguard: 'high', fork: 'conventional', gaiters: true, luggage: 'none', head: 0.16,
    clearance: 0.27, travel: 0.24 },
  retro: { name: 'Retro roadster (parallel twin)', wheelbase: 1.445, length: 2.170, seat: 0.790, rake: 25.5, trail: 0.105,
    front: [18, 100, 90], rear: [17, 150, 70], wheels: 'spoked', layout: 'twin', cc: 1200, cooling: 'air', tilt: 5,
    fairing: 'none', bars: 'upright', bar_half: 0.37, lamp: 'round', exhaust: 'twin_low', tank: 'teardrop', saddle: 'bench',
    frame: 'cradle', shock: 'twin', mudguard: 'retro', fork: 'conventional', luggage: 'none', head: 0.14, clearance: 0.14,
    travel: 0.12, clocks: 'twin_round' },
  mini: { name: 'Mini bike (125 cc single)', wheelbase: 1.145, length: 1.710, seat: 0.775, rake: 25.0, trail: 0.082,
    front: [12, 120, 70], rear: [12, 130, 70], wheels: 'cast', layout: 'single', cc: 125, cooling: 'air', tilt: 80,
    fairing: 'none', bars: 'upright', bar_half: 0.36, lamp: 'round', exhaust: 'high', tank: 'teardrop', saddle: 'bench',
    frame: 'spine', shock: 'twin', mudguard: 'retro', fork: 'usd', luggage: 'none', head: 0.10, clearance: 0.16, travel: 0.11 },
  tourer: { name: 'Touring motorbike', wheelbase: 1.600, length: 2.480, seat: 0.810, rake: 27.0, trail: 0.110,
    front: [17, 120, 70], rear: [17, 180, 55], wheels: 'cast', layout: 'boxer', cc: 1250, cooling: 'liquid', tilt: 0,
    fairing: 'touring', bars: 'upright', bar_half: 0.36, lamp: 'fairing', exhaust: 'low', tank: 'big', saddle: 'stepped',
    screen: 'tall', frame: 'beam', shock: 'mono', mudguard: 'low', fork: 'conventional', luggage: 'both', head: 0.18,
    clearance: 0.13, travel: 0.12 },
  sporttourer: { name: 'Sports tourer (triple)', wheelbase: 1.500, length: 2.160, seat: 0.850, rake: 25.0, trail: 0.108,
    front: [17, 120, 70], rear: [17, 180, 55], wheels: 'cast', layout: 'triple', cc: 890, cooling: 'liquid', tilt: 25,
    fairing: 'half', bars: 'upright', bar_half: 0.38, lamp: 'fairing', exhaust: 'under', tank: 'angular', saddle: 'stepped',
    screen: 'mid', frame: 'beam', shock: 'mono', mudguard: 'low', fork: 'usd', luggage: 'panniers', head: 0.16,
    clearance: 0.14, travel: 0.14 },
};

const { out: OUT, args } = cli('usage: node standard.mjs out.glb --spec=bike.json | --kind=naked [--paint=#hex] [--name=...] [--parts]');
const SPEC = args.spec ? JSON.parse(fs.readFileSync(args.spec, 'utf8')) : {};
const KIND = SPEC.kind || args.kind || 'naked';
if (!KINDS[KIND]) { console.error(`no kind ${KIND}: ${Object.keys(KINDS).join(', ')}`); process.exit(2); }
const B = { ...KINDS[KIND], ...Object.fromEntries(Object.entries(SPEC).filter(([, v]) => v !== null && v !== undefined)),
  ...(args.name ? { name: args.name } : {}) };
const clamp = (x, a, b) => Math.min(b, Math.max(a, x));

const TF = tyreOf(B.front[0], [B.front[1], B.front[2]]), TR = tyreOf(B.rear[0], [B.rear[1], B.rear[2]]);
const W = B.wheelbase, ZF = W / 2, ZR = -W / 2;
const AF = V(0, TF.R, ZF), AR = V(0, TR.R, ZR);
// the steering axis meets the ground TRAIL ahead of the front contact patch
const rk = THREE.MathUtils.degToRad(B.rake);
const U = V(0, Math.cos(rk), -Math.sin(rk)), N = V(0, Math.sin(rk), Math.cos(rk));
const G = V(0, 0, ZF + B.trail);
const axisAt = t => G.clone().addScaledVector(U, t);
const forkAt = (s, x) => V(x, AF.y, AF.z).addScaledVector(U, s);
// the steering head: its top a little above the seat (bars above it)
const HEAD_TOP_Y = B.seat + B.head, T_HEAD1 = HEAD_TOP_Y / U.y, T_HEAD0 = T_HEAD1 - 0.17;
const S_CLAMP0 = (axisAt(T_HEAD0).y - AF.y) / U.y, S_CLAMP1 = (axisAt(T_HEAD1).y - AF.y) / U.y;
const FORK_X = clamp(TF.W / 2 + 0.05, 0.085, 0.12);
const headTop = axisAt(T_HEAD1), headBot = axisAt(T_HEAD0);
// the swingarm pivot: about 40% of the wheelbase ahead of the rear axle
const SW_LEN = clamp(0.40 * W, 0.42, 0.66);
const SP = V(0, AR.y + 0.08 + 0.5 * (B.travel - 0.12), ZR + SW_LEN);
// the engine's size: its cases grow as the cube root of its capacity
const ES = clamp(Math.cbrt((B.cc || 600) / 700), 0.55, 1.22);
const ARM_X = TR.W / 2 + 0.035;

// ── materials ────────────────────────────────────────────────────────────
const MATS = {
  paint: { color: hex(args.paint || B.paint || '#1d3b6e'), metal: 0.0, rough: 0.25, clearcoat: 1 },
  black: { color: [0.018, 0.018, 0.02], metal: 0.2, rough: 0.5 },
  gloss_black: { color: [0.01, 0.01, 0.012], metal: 0.0, rough: 0.15, clearcoat: 1 },
  frame: { color: B.frame === 'trellis' ? hex('#8a1c1c') : B.frame === 'beam' ? [0.62, 0.63, 0.65] : [0.03, 0.03, 0.035],
    metal: B.frame === 'beam' ? 1 : 0.3, rough: B.frame === 'beam' ? 0.38 : 0.35, clearcoat: B.frame === 'trellis' ? 1 : 0 },
  cast: { color: B.cooling === 'air' && KIND === 'retro' ? [0.70, 0.71, 0.72] : [0.16, 0.16, 0.17], metal: 0.7, rough: 0.45 },
  alloy: { color: [0.80, 0.81, 0.82], metal: 1, rough: 0.3 },
  chrome: { color: [0.92, 0.92, 0.93], metal: 1, rough: 0.07 },
  steel: { color: [0.55, 0.50, 0.46], metal: 1, rough: 0.35 },
  gold: { color: [0.83, 0.62, 0.22], metal: 1, rough: 0.28 },
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
  luggage: { color: [0.07, 0.07, 0.075], metal: 0.3, rough: 0.55 },
};

// ── pieces: [part, material, geometry in world space, piece name] ───────
const parts = [];
let SUB = null;
const add = (part, mat, g) => { parts.push([part, mat, g, SUB]); return g; };
const turnTo = (g, dir, at) => {
  g.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(UPY, dir.clone().normalize())); g.translate(at.x, at.y, at.z); return g;
};

// ── wheels ───────────────────────────────────────────────────────────────
// a wire wheel: hub, rim and 36 spokes laced from the hub's two flanges
function spokedWheel(A, T, rimHalf, hubR = 0.05, hubHalf = 0.06) {
  const R = T.RIM_R;
  const rim = aroundX([[R - 0.016, -rimHalf], [R + 0.006, -rimHalf], [R + 0.009, -rimHalf + 0.005], [R - 0.004, -rimHalf + 0.010],
    [R - 0.010, 0], [R - 0.004, rimHalf - 0.010], [R + 0.009, rimHalf - 0.005], [R + 0.006, rimHalf], [R - 0.016, rimHalf]],
  A.x, A.y, A.z, 96);
  const hub = aroundX([[0.012, -hubHalf], [hubR + 0.012, -hubHalf], [hubR + 0.012, -hubHalf + 0.008], [hubR, -hubHalf + 0.012],
    [hubR, hubHalf - 0.012], [hubR + 0.012, hubHalf - 0.008], [hubR + 0.012, hubHalf], [0.012, hubHalf]], A.x, A.y, A.z, 40);
  const spokes = [];
  for (let k = 0; k < 36; k++) {
    const side = k % 2 ? 1 : -1, a0 = 2 * Math.PI * k / 36, a1 = a0 + (k % 4 < 2 ? 0.32 : -0.32);
    const p0 = V(A.x + side * (hubHalf - 0.004), A.y + (hubR + 0.008) * Math.sin(a0), A.z + (hubR + 0.008) * Math.cos(a0));
    const p1 = V(A.x + side * 0.006, A.y + (R - 0.012) * Math.sin(a1), A.z + (R - 0.012) * Math.cos(a1));
    spokes.push(rod(p0, p1, 0.0021, 6));
  }
  return [hub, rim, spokes];
}
function wheel(part, A, T, rimHalf, front) {
  SUB = 'tyre'; add(part, 'rubber', tyreGeometry(A, T, KIND === 'trail' ? 2 / 2.6 : 2 / 3.2));
  if (B.wheels === 'spoked') {
    const [hub, rim, spokes] = spokedWheel(A, T, rimHalf, front ? 0.045 : 0.055, front ? 0.055 : 0.07);
    SUB = 'rim'; add(part, 'alloy', rim); add(part, 'alloy', hub); for (const s of spokes) add(part, 'chrome', s);
  } else {
    const [hub, rim, spokes] = castWheel(A, T, rimHalf, KIND === 'mini' ? 5 : KIND === 'commuter' ? 5 : 6, KIND === 'naked');
    SUB = 'rim'; add(part, 'black', rim); add(part, 'black', spokes); add(part, 'alloy', hub);
  }
}
wheel('wheel_f', AF, TF, Math.max(0.03, TF.W * 0.33), true);
wheel('wheel_r', AR, TR, Math.max(0.035, TR.W * 0.36), false);
// front discs: two on the bigger bikes, one on the left of a small one
const DISC_F = clamp(TF.RIM_R * 0.74, 0.11, 0.165), TWIN_DISC = (B.cc || 0) >= 400 && KIND !== 'trail';
SUB = 'disc';
for (const sx of TWIN_DISC ? [-1, 1] : [1]) add('wheel_f', 'chrome', brakeDisc(AF, sx * (FORK_X - 0.035), DISC_F, DISC_F * 0.72));
add('wheel_r', 'chrome', brakeDisc(AR, -(ARM_X - 0.025), clamp(TR.RIM_R * 0.52, 0.085, 0.13), 0.06));
SUB = 'sprocket_r';
const SPR_R = clamp(TR.RIM_R * 0.48, 0.08, 0.12);
add('wheel_r', 'alloy', sidePanel(sprocketOutline(AR.z, AR.y, SPR_R, 42), ARM_X - 0.03, 0.007, 1, 0.0015));

// ── the front end (steers) ───────────────────────────────────────────────
const USD = B.fork === 'usd';
for (const sx of [-1, 1]) {
  const x = sx * FORK_X;
  SUB = 'fork';
  if (USD) {
    add('steer', 'chrome', rod(forkAt(0.02, x), forkAt(0.24 + B.travel * 0.6, x), 0.021, 24));
    add('steer', 'gold', rod(forkAt(0.20 + B.travel * 0.6, x), forkAt(S_CLAMP1 + 0.03, x), 0.028, 28));
  } else {
    add('steer', KIND === 'retro' ? 'alloy' : 'black', rod(forkAt(-0.03, x), forkAt(0.22 + B.travel * 0.5, x), 0.026, 24));   // slider
    add('steer', 'chrome', rod(forkAt(0.20 + B.travel * 0.5, x), forkAt(S_CLAMP1 + 0.03, x), 0.02, 24));                    // stanchion
    if (B.gaiters) add('steer', 'rubber', rod(forkAt(0.24 + B.travel * 0.5, x), forkAt(S_CLAMP0 - 0.02, x), 0.027, 20));
  }
  add('steer', 'black', rod(forkAt(-0.04, x), forkAt(0.05, x), 0.026, 20));            // the axle clamp
  SUB = 'caliper_front';
  if (TWIN_DISC || sx > 0) {
    const c = AF.clone().add(V(sx * (FORK_X - 0.035), DISC_F * 0.55, -DISC_F * 0.55));
    const cal = roundedBox(0.03, 0.10, 0.045, 0.01, V(0, 0, 0)); cal.rotateX(-0.75); cal.translate(c.x, c.y, c.z);
    add('steer', 'black', cal);
  }
}
SUB = 'fork';
add('steer', 'alloy', rod(V(-FORK_X - 0.03, AF.y, AF.z), V(FORK_X + 0.03, AF.y, AF.z), 0.011));
for (const s of [S_CLAMP0, S_CLAMP1]) {
  const c = forkAt(s, 0).addScaledVector(N, -0.02);
  const g = roundedBox(2 * FORK_X + 0.075, 0.028, 0.085, 0.012, V(0, 0, 0));
  g.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(UPY, U)); g.translate(c.x, c.y, c.z);
  add('steer', s === S_CLAMP1 ? 'alloy' : 'black', g);
}
// the bar: on risers on the top clamp, bent up and back to the grips
const TOPC = forkAt(S_CLAMP1, 0).addScaledVector(N, -0.025).add(V(0, 0.03, 0));
const RISE = B.bars === 'wide' ? 0.08 : 0.05, SWEEP = B.bars === 'wide' ? 0.07 : 0.10;
const BAR_C = TOPC.clone().add(V(0, RISE, -0.02));
const grip = sx => BAR_C.clone().add(V(sx * B.bar_half, 0.035, -SWEEP));
{
  SUB = 'handlebar';
  for (const sx of [-1, 1]) add('steer', 'alloy', rod(TOPC.clone().add(V(sx * 0.035, -0.01, 0)), BAR_C.clone().add(V(sx * 0.035, 0, 0)), 0.016, 14));
  add('steer', 'black', tube([grip(-1), BAR_C.clone().add(V(-0.20, 0.025, -0.02)), BAR_C.clone(), BAR_C.clone().add(V(0.20, 0.025, -0.02)), grip(1)],
    0.011, 48, 10));
  for (const sx of [-1, 1]) {
    const g = grip(sx), inb = g.clone().add(V(-sx * 0.12, -0.004, 0.012));
    add('steer', 'rubber', rod(inb, g.clone().add(V(sx * 0.01, 0, -0.002)), 0.017, 16));
    add('steer', 'black', roundedBox(0.04, 0.04, 0.05, 0.01, inb.clone().add(V(-sx * 0.03, 0.006, 0.005))));
    add('steer', 'alloy', tube([inb.clone().add(V(-sx * 0.03, 0.01, 0.03)), inb.clone().lerp(g, 0.5).add(V(0, 0.008, 0.07)),
      g.clone().add(V(sx * 0.01, 0, 0.065))], 0.006, 16, 8));
    if (B.luggage !== 'none' || KIND === 'adventure') add('steer', 'black', tube([inb.clone().add(V(-sx * 0.05, -0.01, 0.02)),
      g.clone().add(V(sx * 0.03, -0.01, 0.07)), g.clone().add(V(sx * 0.04, -0.03, 0.0))], 0.006, 16, 8));   // hand guard bar
  }
  add('steer', 'black', rod(grip(-1).clone().add(V(0.13, 0.015, 0.02)), grip(-1).clone().add(V(0.13, 0.07, 0.03)), 0.017, 14));  // brake reservoir
}
// mirrors on stalks from the bar (a fairing carries its own)
const MIRRORS_ON = B.fairing === 'half' || B.fairing === 'touring' ? 'body' : 'steer';
if (MIRRORS_ON === 'steer') {
  SUB = 'mirrors';
  for (const sx of [-1, 1]) {
    const b = grip(sx).clone().add(V(-sx * 0.14, 0.01, 0.02)), t = b.clone().add(V(sx * 0.07, 0.13, 0.01));
    add('steer', 'black', tube([b, b.clone().add(V(sx * 0.02, 0.07, 0.01)), t], 0.007, 16, 8));
    add('steer', 'black', ball(t.clone().add(V(sx * 0.03, 0.02, 0)), 0.05, 1.25, 0.65, 0.4));
    const m = new THREE.CircleGeometry(0.042, 24); m.scale(1.2, 0.62, 1); m.rotateY(Math.PI); m.translate(t.x + sx * 0.03, t.y + 0.02, t.z - 0.022);
    add('steer', 'mirror', m);
  }
}
// the front mudguard: low over the tyre on the fork, or high under the clamp
{
  SUB = 'mudguard_front';
  const prof = (r0, w) => { const p = []; for (let i = 0; i <= 12; i++) { const a = -w + 2 * w * i / 12; p.push([r0 + 0.01 * (1 - (a / w) ** 2), a]); } return p; };
  if (B.mudguard === 'high' || B.mudguard === 'beak') {
    const c = forkAt(S_CLAMP0 - 0.06, 0);
    add('steer', B.mudguard === 'beak' ? 'black' : 'paint', lofted(u => {
      const z = c.z + 0.30 - 0.52 * u;
      return { z, w: 0.07 - 0.02 * Math.abs(u - 0.45), yt: c.y + 0.02 - 0.12 * (u - 0.45) ** 2 * 4 * 0.25, yb: c.y - 0.01 - 0.10 * (u - 0.45) ** 2, e: 0.5,
        a0: 0, a1: Math.PI };
    }, 24, 16));
  }
  if (B.mudguard !== 'high') {
    const ang = B.mudguard === 'retro' ? [-Math.PI * 0.95, Math.PI * 0.75] : [-Math.PI * 0.80, Math.PI * 0.55];
    add('steer', B.mudguard === 'retro' ? 'chrome' : 'paint', aroundX(prof(TF.R + 0.02, TF.W / 2 + 0.012), AF.x, AF.y, AF.z, 48, ...ang));
  }
}
// the headlamp on the forks (round, square or twin), the clocks on the clamp
const LAMP_Y = forkAt(S_CLAMP0, 0).y - 0.03;
const LAMP_C = forkAt(S_CLAMP0, 0).addScaledVector(N, 0.09).add(V(0, -0.04, 0));
if (B.lamp === 'round' || B.lamp === 'square' || (B.lamp === 'twin' && B.fairing === 'none')) {
  SUB = 'headlamp';
  if (B.lamp === 'round') {
    const r = KIND === 'mini' ? 0.075 : KIND === 'retro' ? 0.092 : 0.085;
    const bowl = aroundX([[0.001, -0.10], [r * 0.55, -0.095], [r * 0.92, -0.05], [r, 0.0], [r * 1.01, 0.012], [0.001, 0.014]], 0, 0, 0, 40);
    bowl.rotateY(-Math.PI / 2); bowl.translate(LAMP_C.x, LAMP_C.y, LAMP_C.z);
    add('steer', KIND === 'retro' ? 'chrome' : 'black', bowl);
    const lens = new THREE.CircleGeometry(r * 0.94, 32); lens.translate(LAMP_C.x, LAMP_C.y, LAMP_C.z + 0.016);
    add('steer', 'lamp', lens);
    for (const sx of [-1, 1]) add('steer', 'black', rod(LAMP_C.clone().add(V(sx * r * 0.95, 0, -0.03)), forkAt(S_CLAMP0 - 0.06, sx * FORK_X), 0.008, 8));
  } else {
    const box = roundedBox(0.18, 0.10, 0.07, 0.02, LAMP_C.clone().add(V(0, 0, -0.01))); add('steer', 'black', box);
    const lens = roundedBox(0.16, 0.08, 0.01, 0.02, LAMP_C.clone().add(V(0, 0, 0.026))); add('steer', 'lamp', lens);
  }
  SUB = 'indicators_front';
  for (const sx of [-1, 1]) {
    add('steer', 'black', rod(LAMP_C.clone().add(V(sx * 0.07, -0.02, -0.06)), LAMP_C.clone().add(V(sx * 0.17, -0.02, -0.07)), 0.006, 8));
    add('steer', 'amber_lens', ball(LAMP_C.clone().add(V(sx * 0.185, -0.02, -0.07)), 0.02, 0.8, 0.7, 1.4));
  }
}
SUB = 'dash';
if (B.clocks === 'twin_round') {
  for (const sx of [-1, 1]) {
    const c = TOPC.clone().add(V(sx * 0.055, 0.06, 0.01));
    const g = aroundX([[0.001, -0.03], [0.045, -0.03], [0.048, 0.02], [0.001, 0.02]], 0, 0, 0, 32);
    g.rotateZ(Math.PI / 2); g.rotateX(-0.6); g.translate(c.x, c.y, c.z); add('steer', 'chrome', g);
  }
} else if (B.fairing === 'none' || B.fairing === 'flyscreen') {
  const g = roundedBox(0.15, 0.08, 0.035, 0.012, V(0, 0, 0)); g.rotateX(-0.75);
  const c = TOPC.clone().add(V(0, 0.07, 0.04)); g.translate(c.x, c.y, c.z); add('steer', 'gloss_black', g);
}
if (B.fairing === 'flyscreen') {
  SUB = 'windscreen';
  add('steer', 'paint', lofted(u => {
    const z = LAMP_C.z + 0.05 - 0.10 * u;
    return { z, w: 0.12 - 0.02 * u, yt: LAMP_C.y + 0.15 + 0.03 * u, yb: LAMP_C.y - 0.10 + 0.03 * u, e: 0.7, a0: -0.3, a1: Math.PI + 0.3 };
  }, 12, 20));
}

// ── the frame ────────────────────────────────────────────────────────────
// where the tank, seat and tail sit, along the bike
const TANK_Z0 = headTop.z - 0.085, TANK_Z1 = SP.z + 0.06 + (KIND === 'adventure' || KIND === 'tourer' ? 0.03 : 0);
const SEAT_Z0 = TANK_Z1 + 0.02, SEAT_Z1 = Math.max(AR.z + 0.12, SEAT_Z0 - (B.saddle === 'flat' ? 0.70 : 0.62) * W / 1.4);
const TAIL_Z = Math.min(SEAT_Z1 - 0.05, AR.z + (KIND === 'retro' || KIND === 'commuter' ? -0.10 : 0.02));
const RAIL_Y = B.seat - 0.13;                 // the frame rails under the tank and seat
SUB = 'frame';
add('body', 'frame', rod(headBot.clone().addScaledVector(U, -0.02), headTop.clone().addScaledVector(U, 0.02), 0.032, 24));
const ENG_FRONT_Z = Math.min(AF.z - TF.R - 0.05, SP.z + 0.03 + 0.50 * ES);
if (B.frame === 'beam') {
  for (const sx of [-1, 1]) {
    add('body', 'frame', sweptBox([V(sx * 0.03, headTop.y - 0.04, headTop.z - 0.02), V(sx * 0.13, RAIL_Y + 0.02, (headTop.z + SP.z) / 2 + 0.08),
      V(sx * 0.16, RAIL_Y - 0.04, SP.z + 0.10), V(sx * 0.13, SP.y + 0.04, SP.z + 0.01)], 0.045, 0.10, 80));
    add('body', 'frame', roundedBox(0.03, 0.22, 0.12, 0.012, V(sx * 0.13, SP.y, SP.z)));
  }
} else if (B.frame === 'spine') {
  add('body', 'frame', sweptBox([headBot.clone().add(V(0, 0.04, -0.02)), V(0, RAIL_Y - 0.06, (headTop.z + SP.z) / 2),
    V(0, SP.y + 0.10, SP.z + 0.04)], 0.08, 0.10, 60));
  for (const sx of [-1, 1]) add('body', 'frame', roundedBox(0.025, 0.16, 0.10, 0.01, V(sx * 0.11, SP.y + 0.02, SP.z)));
} else {
  const R = B.frame === 'trellis' ? 0.012 : 0.016;
  for (const sx of [-1, 1]) {
    const top = [V(sx * 0.035, headTop.y - 0.03, headTop.z - 0.02), V(sx * 0.10, RAIL_Y + 0.01, (headTop.z + SP.z) / 2 + 0.06),
      V(sx * 0.12, RAIL_Y - 0.03, SP.z + 0.06), V(sx * 0.12, SP.y + 0.05, SP.z + 0.01)];
    add('body', 'frame', tube(top, R, 60, 10));
    const low = [V(sx * 0.035, headBot.y + 0.02, headBot.z + 0.01), V(sx * 0.11, (headBot.y + SP.y) / 2 + 0.05, ENG_FRONT_Z - 0.02),
      V(sx * 0.12, SP.y + 0.02, SP.z + 0.10)];
    if (B.frame === 'trellis') {
      add('body', 'frame', tube(low, R, 40, 10));
      const tc = new THREE.CatmullRomCurve3(top), lc = new THREE.CatmullRomCurve3(low);
      for (let k = 0; k < 6; k++) {                                  // the trellis' diagonals
        const a = tc.getPoint(0.12 + 0.14 * k), b = lc.getPoint(0.10 + 0.15 * (k + (k % 2 ? 0 : 1)));
        add('body', 'frame', rod(a, b, R * 0.85, 10));
      }
    } else {
      // a cradle: down tubes in front of the engine and under it to the pivot
      const dn = [V(sx * 0.03, headBot.y + 0.01, headBot.z + 0.01), V(sx * 0.07, B.clearance + 0.22, ENG_FRONT_Z + 0.02),
        V(sx * 0.09, B.clearance + 0.02, ENG_FRONT_Z - 0.10), V(sx * 0.10, B.clearance + 0.01, SP.z + 0.05),
        V(sx * 0.12, SP.y - 0.04, SP.z + 0.01)];
      add('body', 'frame', tube(dn, R, 80, 10));
    }
    add('body', 'frame', roundedBox(0.025, 0.18, 0.10, 0.01, V(sx * 0.125, SP.y, SP.z)));
  }
  add('body', 'frame', rod(V(-0.12, RAIL_Y - 0.03, SP.z + 0.06), V(0.12, RAIL_Y - 0.03, SP.z + 0.06), 0.014, 12));
}
SUB = 'subframe';
for (const sx of [-1, 1]) {
  add('body', 'black', tube([V(sx * 0.11, RAIL_Y - 0.02, SP.z + 0.05), V(sx * 0.095, B.seat - 0.09, (SP.z + TAIL_Z) / 2), V(sx * 0.07, B.seat - 0.05, TAIL_Z + 0.04)],
    0.011, 40, 10));
  add('body', 'black', tube([V(sx * 0.12, SP.y + 0.08, SP.z - 0.01), V(sx * 0.10, (SP.y + B.seat) / 2, (SP.z + TAIL_Z) / 2 + 0.03),
    V(sx * 0.08, B.seat - 0.07, TAIL_Z + 0.10)], 0.009, 40, 10));
}

// ── the swingarm and rear suspension ─────────────────────────────────────
SUB = 'swingarm';
for (const sx of [-1, 1]) {
  add('body', B.frame === 'beam' || KIND === 'adventure' ? 'alloy' : 'black',
    beam(V(sx * (ARM_X + 0.01), SP.y, SP.z), V(sx * ARM_X, AR.y, AR.z + 0.02), 0.03, KIND === 'commuter' || KIND === 'mini' ? 0.05 : 0.07));
  add('body', 'black', roundedBox(0.035, 0.045, 0.06, 0.01, V(sx * ARM_X, AR.y, AR.z)));
}
add('body', 'black', rod(V(-ARM_X, SP.y, SP.z - 0.10), V(ARM_X, SP.y, SP.z - 0.10), 0.022, 14));
add('body', 'alloy', rod(V(-ARM_X - 0.03, SP.y, SP.z), V(ARM_X + 0.03, SP.y, SP.z), 0.011));
add('body', 'alloy', rod(V(-ARM_X - 0.02, AR.y, AR.z), V(ARM_X + 0.02, AR.y, AR.z), 0.010));
if (B.shock === 'twin') {
  SUB = 'rear_shocks';
  for (const sx of [-1, 1]) {
    const lo = V(sx * (ARM_X + 0.015), AR.y + 0.03, AR.z + 0.07), hi = V(sx * (ARM_X - 0.01), B.seat - 0.10, AR.z + 0.20);
    add('body', 'chrome', rod(lo, hi, 0.012, 14));
    add('body', KIND === 'retro' ? 'chrome' : 'spring', helix(lo.clone().lerp(hi, 0.12), lo.clone().lerp(hi, 0.80), 0.024, 0.004, 9));
    add('body', 'black', rod(hi.clone().lerp(lo, 0.02), hi.clone().lerp(lo, 0.30), 0.02, 14));
  }
} else {
  SUB = 'rear_shock';
  const lo = V(0, SP.y - 0.04, SP.z - 0.14), hi = V(0, RAIL_Y - 0.07, SP.z + 0.02);
  add('body', 'black', rod(lo, hi, 0.02, 18));
  add('body', 'spring', helix(lo.clone().lerp(hi, 0.18), lo.clone().lerp(hi, 0.82), 0.031, 0.005, 8));
  add('body', 'gold', rod(hi.clone().lerp(lo, 0.05), hi.clone().lerp(lo, 0.32), 0.024, 18));
}

// ── the engine ───────────────────────────────────────────────────────────
// the cases ahead of the swingarm pivot, the cylinders leaning forward by
// the kind's angle (a mini's lie almost flat, a boxer's stick out sideways)
const LAYOUT = B.layout, AIR = B.cooling === 'air';
const NCYL = { single: 1, twin: 2, vtwin: 2, boxer: 2, triple: 3, four: 4 }[LAYOUT] || 2;
const CASE_W = { single: 0.24, twin: 0.33, vtwin: 0.27, boxer: 0.30, triple: 0.38, four: 0.42 }[LAYOUT] * clamp(ES, 0.8, 1.1);
const CASE_L = 0.34 * ES, CASE_H = 0.21 * ES;
const CASE_C = V(0, Math.max(B.clearance + CASE_H / 2 + 0.03, SP.y - 0.02), Math.min(ENG_FRONT_Z - 0.10 * ES, SP.z + 0.04 + CASE_L / 2));
const CRANK = CASE_C.clone().add(V(0, 0.02, CASE_L * 0.15));
SUB = 'crankcase';
add('body', 'cast', roundedBox(CASE_W, CASE_H, CASE_L, 0.045 * ES, CASE_C));
SUB = 'gearbox';
add('body', 'cast', roundedBox(CASE_W * 0.75, CASE_H * 0.85, CASE_L * 0.45, 0.035 * ES, CASE_C.clone().add(V(0, 0.01, -CASE_L * 0.42))));
SUB = 'sump';
add('body', 'black', roundedBox(CASE_W * 0.7, 0.05 * ES, CASE_L * 0.65, 0.015, CASE_C.clone().add(V(0, -CASE_H / 2 - 0.015 * ES, CASE_L * 0.05))));
const cylinders = [];                             // [base point, direction, across width]
if (LAYOUT === 'vtwin') {
  for (const a of [B.tilt + 32, B.tilt - 32]) {
    const t = THREE.MathUtils.degToRad(a);
    cylinders.push([CRANK.clone().add(V(0, CASE_H * 0.35, Math.sin(t) * 0.03)), V(0, Math.cos(t), Math.sin(t)), 0.11 * ES]);
  }
} else if (LAYOUT === 'boxer') {
  for (const sx of [-1, 1]) cylinders.push([CRANK.clone().add(V(sx * CASE_W * 0.42, 0.03, 0.02)), V(sx, 0.08, 0.02).normalize(), 0.12 * ES]);
} else {
  const t = THREE.MathUtils.degToRad(B.tilt);
  cylinders.push([CRANK.clone().add(V(0, CASE_H * 0.40, 0)), V(0, Math.cos(t), Math.sin(t)), (0.06 + 0.075 * NCYL) * clamp(ES, 0.8, 1.1)]);
}
const BLOCK_H = (LAYOUT === 'single' ? 0.13 : 0.14) * ES, HEAD_H = 0.085 * ES;
const heads = [];
for (const [base, d, w] of cylinders) {
  const q = new THREE.Quaternion().setFromUnitVectors(UPY, d);
  const at = (s, g) => { g.applyQuaternion(q); const c = base.clone().addScaledVector(d, s); g.translate(c.x, c.y, c.z); return g; };
  const dep = 0.11 * ES;
  SUB = LAYOUT === 'vtwin' || LAYOUT === 'boxer' ? 'cylinders' : 'cylinder_block';
  add('body', 'cast', at(BLOCK_H / 2, roundedBox(w, BLOCK_H, dep, 0.015, V(0, 0, 0))));
  if (AIR) for (let k = 0; k < 7; k++) add('body', 'cast', at(0.015 + k * BLOCK_H / 7, roundedBox(w + 0.035, 0.005, dep + 0.035, 0.002, V(0, 0, 0))));
  SUB = LAYOUT === 'vtwin' || LAYOUT === 'boxer' ? 'cylinder_heads' : 'cylinder_head';
  add('body', 'cast', at(BLOCK_H + HEAD_H / 2, roundedBox(w + 0.01, HEAD_H, dep + 0.02, 0.018, V(0, 0, 0))));
  if (AIR) for (let k = 0; k < 3; k++) add('body', 'cast', at(BLOCK_H + 0.015 + k * 0.025, roundedBox(w + 0.04, 0.005, dep + 0.05, 0.002, V(0, 0, 0))));
  SUB = 'cam_cover';
  add('body', KIND === 'retro' ? 'alloy' : 'gloss_black', at(BLOCK_H + HEAD_H + 0.018, roundedBox(w * 0.92, 0.036, dep * 0.9, 0.015, V(0, 0, 0))));
  heads.push(base.clone().addScaledVector(d, BLOCK_H + HEAD_H * 0.5));
}
SUB = 'spark_plugs';
for (const [base, d, w] of cylinders) {
  const n = LAYOUT === 'vtwin' || LAYOUT === 'boxer' ? 1 : NCYL;
  for (let k = 0; k < n; k++) {
    const x = n === 1 ? 0 : (k - (n - 1) / 2) * (w / n);
    const p = base.clone().addScaledVector(d, BLOCK_H + HEAD_H + 0.03).add(V(LAYOUT === 'boxer' ? 0 : x, 0, 0));
    add('body', 'black', rod(p, p.clone().addScaledVector(d, 0.025), 0.012, 12));
  }
}
SUB = 'clutch_cover';
add('body', 'cast', aroundX([[0, -0.016], [0.085 * ES, -0.016], [0.095 * ES, -0.003], [0.095 * ES, 0.011], [0.082 * ES, 0.016], [0, 0.016]],
  -CASE_W / 2 - 0.012, CASE_C.y + 0.01, CASE_C.z - CASE_L * 0.18, 40));
SUB = 'alternator_cover';
add('body', 'cast', aroundX([[0, -0.014], [0.07 * ES, -0.014], [0.078 * ES, -0.002], [0.078 * ES, 0.01], [0.066 * ES, 0.014], [0, 0.014]],
  CASE_W / 2 + 0.010, CRANK.y, CRANK.z + 0.02, 40));
SUB = 'sprocket_front';
const FS = V(ARM_X - 0.03, SP.y + 0.015, SP.z + 0.075);
add('body', 'alloy', sidePanel(sprocketOutline(FS.z, FS.y, 0.034, 15), FS.x, 0.007, 1, 0.0015));
add('body', 'black', roundedBox(0.02, 0.10, 0.12, 0.012, V(FS.x + 0.02, FS.y, FS.z)));
// air in from under the tank
SUB = 'airbox';
add('body', 'black', roundedBox(clamp(CASE_W * 0.7, 0.18, 0.26), 0.08, 0.20, 0.03, V(0, RAIL_Y + 0.0, (TANK_Z0 + TANK_Z1) / 2 - 0.04)));
if (!AIR) {
  SUB = 'radiator';
  const rz = Math.min(ENG_FRONT_Z + 0.04, AF.z - TF.R - 0.03), rh = clamp(0.20 + 0.06 * NCYL, 0.22, 0.34), ry = clamp(heads[0].y + 0.02, CASE_C.y + 0.20, RAIL_Y - 0.03);
  const r = roundedBox(clamp(0.26 + 0.04 * NCYL, 0.28, 0.42), rh, 0.04, 0.01, V(0, 0, 0)); r.rotateX(-rk * 0.6); r.translate(0, ry, rz);
  add('body', 'radiator', r);
  SUB = 'coolant_hoses';
  add('body', 'black', tube([V(0.10, ry + rh * 0.35, rz - 0.02), V(0.12, ry + rh * 0.3, rz - 0.08), heads[0].clone().add(V(0.09, 0.02, 0))], 0.012, 24, 10));
  add('body', 'black', tube([V(-0.10, ry - rh * 0.4, rz - 0.02), V(-0.13, ry - rh * 0.5, rz - 0.08), CASE_C.clone().add(V(-CASE_W / 2, 0.04, CASE_L * 0.35))], 0.012, 24, 10));
}
// the exhaust: headers from the ports at the front of the head(s), down
// round the front of the cases, then under the engine (a stubby can), low
// along the right, high under the seat, or one each side (a retro's)
{
  SUB = 'exhaust_headers';
  const ports = [];
  for (const [base, d, w] of cylinders) {
    const n = LAYOUT === 'vtwin' || LAYOUT === 'boxer' ? 1 : NCYL;
    for (let k = 0; k < n; k++) {
      const x = n === 1 ? 0 : (k - (n - 1) / 2) * (w / n) * 1.1;
      const out = LAYOUT === 'boxer' ? V(0, -0.3, 1).normalize() : V(0, -Math.sin(Math.acos(d.y)) * 0.2, 1).normalize();
      ports.push([base.clone().addScaledVector(d, BLOCK_H + HEAD_H * 0.45).add(V(LAYOUT === 'boxer' ? 0 : x, 0, 0.04 * ES)), out]);
    }
  }
  const under = V(-0.02, B.clearance + 0.02, CASE_C.z - CASE_L * 0.1);
  const sides = B.exhaust === 'twin_low' ? ports.map(([p]) => (p.x >= 0 ? 1 : -1)) : ports.map(() => -1);
  if (B.exhaust === 'twin_low' && ports.length === 1) sides[0] = -1;
  ports.forEach(([p, o], i) => {
    const side = sides[i], fx = p.x;
    const front = V(fx * 0.9, Math.max(B.clearance + 0.12, p.y - 0.15), Math.min(p.z + 0.08, AF.z - TF.R - 0.01));
    if (B.exhaust === 'high') {
      add('body', 'steel', tube([p, p.clone().add(V(0, -0.04, 0.04)), front, V(-0.12, front.y + 0.02, CASE_C.z),
        V(-0.15, SP.y + 0.10, SP.z - 0.02)], 0.017, 60, 10));
    } else if (B.exhaust === 'twin_low') {
      add('body', 'chrome', tube([p, p.clone().add(V(0, -0.05, 0.04)), V(side * (Math.abs(fx) + 0.04), B.clearance + 0.12, front.z),
        V(side * (CASE_W / 2 + 0.05), B.clearance + 0.06, CASE_C.z), V(side * (ARM_X + 0.06), B.clearance + 0.10, SP.z - 0.02)], 0.019, 60, 10));
    } else {
      add('body', 'steel', tube([p, p.clone().add(V(0, -0.05, 0.04)), front, V(fx * 0.5, B.clearance + 0.04, CASE_C.z + CASE_L * 0.3), under],
        0.017, 60, 10));
    }
  });
  SUB = 'silencer';
  if (B.exhaust === 'under') {
    add('body', 'steel', rod(under, under.clone().add(V(-0.04, 0.03, -0.12)), 0.03, 20));
    add('body', 'black', roundedBox(0.16, 0.10, 0.20, 0.04, under.clone().add(V(-0.05, 0.03, -0.17))));
  } else if (B.exhaust === 'high') {
    add('body', 'titanium' in MATS ? 'titanium' : 'alloy', rod(V(-0.15, SP.y + 0.11, SP.z - 0.04), V(-0.135, B.seat - 0.10, AR.z + 0.10), 0.045, 28, 0.04));
  } else if (B.exhaust === 'twin_low') {
    for (const sx of [...new Set(sides)]) add('body', 'chrome',
      rod(V(sx * (ARM_X + 0.06), B.clearance + 0.10, SP.z - 0.04), V(sx * (ARM_X + 0.07), AR.y + 0.03, AR.z + 0.06), 0.042, 28, 0.045));
  } else {
    add('body', 'steel', tube([under, V(-0.12, B.clearance + 0.06, SP.z + 0.02), V(-(ARM_X + 0.06), SP.y - 0.05, SP.z - 0.10)], 0.024, 30, 12));
    add('body', 'alloy', rod(V(-(ARM_X + 0.06), SP.y - 0.04, SP.z - 0.12), V(-(ARM_X + 0.07), AR.y + 0.12, AR.z + 0.16), 0.055, 32, 0.05));
  }
}
// the chain on the left, from the front sprocket round the rear
SUB = 'chain';
{
  const x = FS.x, rr = SPR_R, fr = 0.034, pts = [];
  const ang = Math.atan2(FS.y - AR.y, FS.z - AR.z), d = Math.hypot(FS.y - AR.y, FS.z - AR.z);
  const tilt = Math.asin((rr - fr) / d);
  for (let i = 0; i <= 24; i++) { const a = ang + Math.PI / 2 + tilt + (Math.PI - 2 * tilt) * i / 24; pts.push(V(x, AR.y + rr * Math.sin(a), AR.z + rr * Math.cos(a))); }
  for (let i = 0; i <= 12; i++) { const a = ang - Math.PI / 2 - tilt + (Math.PI + 2 * tilt) * i / 12; pts.push(V(x, FS.y + fr * Math.sin(a), FS.z + fr * Math.cos(a))); }
  pts.push(pts[0].clone());
  add('body', 'black', tube(pts, 0.005, 200, 6));
}

// ── bodywork ─────────────────────────────────────────────────────────────
// the tank between the steering head and the seat, shaped by its kind
const TANK = {
  teardrop: u => ({ w: 0.06 + 0.10 * Math.sin(Math.PI * Math.min(1, 0.10 + u * 0.95)) ** 0.8, bulge: 0.035, e: 0.75 }),
  angular: u => ({ w: 0.11 + 0.07 * (1 - u) ** 0.6 + 0.02 * Math.sin(Math.PI * u), bulge: 0.015, e: 0.5 }),
  big: u => ({ w: 0.12 + 0.08 * Math.sin(Math.PI * Math.min(1, 0.2 + u * 0.9)) ** 0.6, bulge: 0.035, e: 0.55 }),
  slim: u => ({ w: 0.07 + 0.05 * (1 - u), bulge: 0.0, e: 0.6 }),
}[B.tank] || (u => ({ w: 0.14, bulge: 0.02, e: 0.6 }));
// its top from just under the steering head's top down to the seat's
// front; its bottom on the frame rails, higher at the front
const TANK_TOP = u => (headTop.y - 0.035) + ((B.seat + 0.075) - (headTop.y - 0.035)) * u ** 1.15 + TANK(u).bulge * Math.sin(Math.PI * u);
SUB = 'tank';
add('body', 'paint', lofted(u => {
  const z = TANK_Z0 - (TANK_Z0 - TANK_Z1) * u, t = TANK(u);
  const front = 0.55 + 0.45 * Math.sin(Math.PI / 2 * Math.min(1, u * 3.5));
  return { z, w: t.w * front, yt: TANK_TOP(u), yb: Math.min(TANK_TOP(u) - 0.09, headBot.y + 0.03 + (RAIL_Y - 0.01 - headBot.y - 0.03) * u ** 0.6), e: t.e };
}, 40, 40, true));
SUB = 'fuel_cap';
add('body', 'alloy', turnTo(new THREE.CylinderGeometry(0.032, 0.034, 0.012, 28), V(0, 1, 0.25),
  V(0, TANK_TOP(0.3) + 0.002, TANK_Z0 - (TANK_Z0 - TANK_Z1) * 0.3)));
// the seat: one bench, or the rider's and a raised pillion
SUB = 'seat';
const SEAT_W = KIND === 'tourer' ? 0.17 : KIND === 'trail' ? 0.10 : 0.135;
const SEAT_TOP = u => B.seat + 0.065 * Math.max(0, 1 - u / 0.3) ** 1.5;          // the published height: its lowest
const SEAT_WID = u => 0.08 + (SEAT_W - 0.08) * Math.min(1, u / 0.25) ** 0.6;
if (B.saddle === 'stepped') {
  const mid = SEAT_Z0 - (SEAT_Z0 - SEAT_Z1) * 0.52;
  add('body', 'seat', lofted(u => ({ z: SEAT_Z0 + 0.01 - (SEAT_Z0 + 0.01 - mid) * u, w: SEAT_WID(u), yt: SEAT_TOP(u * 0.55),
    yb: B.seat - 0.075, e: 0.45 }), 24, 28, true));
  SUB = 'pillion_seat';
  add('body', 'seat', lofted(u => ({ z: mid + 0.02 - (mid + 0.02 - SEAT_Z1) * u, w: SEAT_W * 0.85 - 0.025 * u,
    yt: B.seat + 0.045 + 0.012 * Math.sin(Math.PI * Math.min(1, u * 1.6)), yb: B.seat - 0.04, e: 0.45 }), 16, 28, true));
} else {
  add('body', 'seat', lofted(u => ({ z: SEAT_Z0 + 0.01 - (SEAT_Z0 + 0.01 - SEAT_Z1) * u, w: SEAT_WID(u * 1.4) - 0.02 * u,
    yt: SEAT_TOP(u * 0.5) + (B.saddle === 'flat' ? 0.0 : 0.015 * u), yb: B.seat - 0.075, e: 0.4 }), 28, 28, true));
}
// the side covers under the seat front, the tail behind
for (const [nm, a0, a1] of [['side_cover_left', -1.2, 0.8], ['side_cover_right', Math.PI - 0.8, Math.PI + 1.2]]) {
  SUB = nm;
  // a retro's or a commuter's covers fill the triangle under the seat; the others' are a strip under its edge
  const full = KIND === 'retro' || KIND === 'commuter';
  add('body', 'paint', lofted(u => {
    const z = SEAT_Z0 - 0.02 - (full ? 0.26 : 0.30) * u;
    return { z, w: 0.12, yt: B.seat - 0.06, yb: full ? SP.y + 0.10 + 0.08 * u : B.seat - 0.15 + 0.05 * u, e: 0.7, a0, a1 };
  }, 14, 12));
}
SUB = 'tail_unit';
if (KIND === 'retro' || KIND === 'commuter' || KIND === 'mini') {
  // a rear mudguard over the tyre on struts, the lamp and plate on its end
  SUB = 'mudguard_rear';
  const prof = [];
  for (let i = 0; i <= 12; i++) { const a = -(TR.W / 2 + 0.015) + (TR.W + 0.03) * i / 12; prof.push([TR.R + 0.03 + 0.008 * (1 - (2 * i / 12 - 1) ** 2), a]); }
  add('body', KIND === 'retro' ? 'paint' : 'black', aroundX(prof, AR.x, AR.y, AR.z, 48, -Math.PI * 1.03, Math.PI * 0.55));
} else {
  add('body', 'paint', lofted(u => {
    const z = SEAT_Z1 + 0.10 - (0.10 + 0.10) * u;
    return { z, w: 0.12 - 0.07 * u ** 0.8, yt: B.seat + 0.02 + (B.saddle === 'stepped' ? 0.03 : 0), yb: B.seat - 0.09 + 0.06 * u, e: 0.6 };
  }, 20, 28, true));
}
const LAMP_R = V(0, B.seat - (KIND === 'retro' || KIND === 'commuter' || KIND === 'mini' ? 0.12 : 0.03), Math.min(SEAT_Z1 - 0.06, AR.z - 0.02));
if (KIND === 'retro' || KIND === 'commuter' || KIND === 'mini') LAMP_R.set(0, AR.y + TR.R * 0.92, AR.z - TR.R * 0.55);
SUB = 'tail_lamp';
add('body', 'red_lens', roundedBox(0.10, 0.035, 0.035, 0.012, LAMP_R));
SUB = 'number_plate';
{
  const hang = LAMP_R.clone().add(V(0, -0.10, -0.06));
  add('body', 'black', tube([LAMP_R.clone().add(V(0, -0.02, 0.02)), LAMP_R.clone().add(V(0, -0.06, -0.03)), hang], 0.010, 20, 8));
  const pl = roundedBox(0.19, 0.14, 0.005, 0.01, V(0, 0, 0)); pl.rotateX(-0.2); pl.translate(hang.x, hang.y - 0.06, hang.z - 0.01); add('body', 'plate', pl);
  SUB = 'indicators_rear';
  for (const sx of [-1, 1]) {
    add('body', 'black', rod(hang.clone().add(V(sx * 0.03, 0.02, 0.02)), hang.clone().add(V(sx * 0.12, 0.03, 0.02)), 0.006, 8));
    add('body', 'amber_lens', ball(hang.clone().add(V(sx * 0.135, 0.03, 0.02)), 0.018, 0.8, 0.7, 1.4));
  }
}
SUB = 'hugger';
if (!(KIND === 'retro' || KIND === 'commuter' || KIND === 'mini')) {
  const prof = [];
  for (let i = 0; i <= 12; i++) { const a = -0.08 + 0.16 * i / 12; prof.push([TR.R + 0.02 + 0.008 * (1 - (a / 0.08) ** 2), a]); }
  add('body', 'black', aroundX(prof, AR.x, AR.y, AR.z, 40, -Math.PI * 0.85, Math.PI * 0.42));
}
// the fairings a kind carries: an adventure bike's beak and screen, a
// sports tourer's half fairing, a tourer's full one (all on the frame)
const NOSE_Z = LAMP_C.z + 0.10;
if (B.fairing === 'beak' || B.fairing === 'half' || B.fairing === 'touring') {
  SUB = 'fairing_upper';
  const big = B.fairing === 'touring' ? 1.25 : B.fairing === 'half' ? 1.05 : 0.95;
  add('body', 'paint', lofted(u => {
    const z = NOSE_Z - 0.30 * big * u, t = u ** 0.6;
    return { z, w: (0.08 + 0.16 * t) * big, yt: LAMP_C.y + 0.10 + 0.08 * t, yb: LAMP_C.y - 0.07 - 0.10 * t * big, e: 0.7, a0: -0.4, a1: Math.PI + 0.4 };
  }, 30, 36));
  SUB = 'headlamps';
  for (const sx of [-1, 1]) add('body', 'lamp', ball(V(sx * 0.055, LAMP_C.y + 0.01, NOSE_Z - 0.035), 0.042, 1.2, 0.55, 0.5));
  SUB = 'windscreen';
  const sh = { tall: 0.30, mid: 0.20 }[B.screen] || 0.14, sw = 0.16 * big;
  add('body', 'screen', new ParametricGeometry((u, v, t) => {
    const x = (u - 0.5) * 2 * sw * (1 - 0.25 * v), z = NOSE_Z - 0.12 - 0.16 * v, y = LAMP_C.y + 0.17 + sh * v + 0.02 * Math.cos(Math.PI * (u - 0.5));
    t.set(x, y, z);
  }, 20, 10));
  SUB = 'dash';
  const g = roundedBox(0.17, 0.10, 0.04, 0.012, V(0, 0, 0)); g.rotateX(-0.9); g.translate(0, LAMP_C.y + 0.17, NOSE_Z - 0.30);
  add('body', 'gloss_black', g);
  SUB = 'indicators_front';
  for (const sx of [-1, 1]) add('body', 'amber_lens', ball(V(sx * 0.19 * big, LAMP_C.y - 0.02, NOSE_Z - 0.20), 0.02, 0.6, 0.5, 1.4));
  if (B.fairing === 'beak') {
    SUB = 'beak';
    add('body', 'paint', lofted(u => {
      const z = NOSE_Z + 0.12 - 0.20 * u;
      return { z, w: 0.04 + 0.09 * u, yt: LAMP_C.y - 0.09 + 0.03 * u, yb: LAMP_C.y - 0.13 - 0.02 * u, e: 0.6 };
    }, 16, 20, true));
  }
  if (MIRRORS_ON === 'body') {
    SUB = 'mirrors';
    for (const sx of [-1, 1]) {
      const b = V(sx * 0.21 * big, LAMP_C.y + 0.12, NOSE_Z - 0.20), t = b.clone().add(V(sx * 0.07, 0.05, -0.02));
      add('body', 'black', rod(b, t, 0.008, 10));
      add('body', 'paint', ball(t.clone().add(V(sx * 0.02, 0, 0)), 0.05, 1.25, 0.65, 0.42));
    }
  }
  if (B.fairing === 'touring') {
    SUB = 'fairing_lower';
    for (const sx of [-1, 1]) add('body', 'paint', lofted(u => {
      const z = NOSE_Z - 0.20 - 0.30 * u;
      return { z, w: 0.26 - 0.03 * u, yt: LAMP_C.y - 0.08, yb: CASE_C.y + 0.02, e: 0.75, a0: sx > 0 ? -1.2 : Math.PI - 0.5, a1: sx > 0 ? 0.5 : Math.PI + 1.2 };
    }, 20, 20));
  }
}
// an adventure bike's crash bars round the engine and a plate under it
if (B.guards) {
  SUB = 'crash_bars';
  for (const sx of [-1, 1]) add('body', 'black', tube([V(sx * 0.10, RAIL_Y - 0.02, TANK_Z0 - 0.06), V(sx * (CASE_W / 2 + 0.10), CASE_C.y + 0.18, ENG_FRONT_Z - 0.02),
    V(sx * (CASE_W / 2 + 0.11), CASE_C.y - 0.02, CASE_C.z + CASE_L * 0.2), V(sx * 0.12, CASE_C.y - 0.05, SP.z + 0.06)], 0.012, 50, 10));
  SUB = 'sump_guard';
  add('body', 'alloy', lofted(u => ({ z: ENG_FRONT_Z + 0.02 - (ENG_FRONT_Z - SP.z) * u, w: CASE_W / 2 + 0.01, yt: B.clearance + 0.03, yb: B.clearance + 0.005, e: 0.3 }),
    16, 16, true));
}
// luggage: a rack, side cases and a top box
if (B.luggage === 'rack' || B.luggage === 'topbox' || B.luggage === 'both' || B.luggage === 'panniers') {
  SUB = 'rack';
  add('body', 'black', tube([V(0.09, B.seat + 0.02, SEAT_Z1 + 0.08), V(0.09, B.seat + 0.03, SEAT_Z1 - 0.12), V(-0.09, B.seat + 0.03, SEAT_Z1 - 0.12),
    V(-0.09, B.seat + 0.02, SEAT_Z1 + 0.08)], 0.009, 40, 8));
}
if (B.luggage === 'panniers' || B.luggage === 'both') {
  SUB = 'panniers';
  for (const sx of [-1, 1]) add('body', KIND === 'adventure' ? 'alloy' : 'luggage',
    roundedBox(0.16, 0.36, 0.46, 0.04, V(sx * (ARM_X + 0.18), AR.y + 0.24, AR.z + 0.10)));
}
if (B.luggage === 'topbox' || B.luggage === 'both') {
  SUB = 'top_box';
  add('body', 'luggage', roundedBox(0.36, 0.28, 0.36, 0.06, V(0, B.seat + 0.20, SEAT_Z1 - 0.06)));
}
// the battery under the seat; pegs and controls
SUB = 'battery';
add('body', 'black', roundedBox(0.08, 0.09, 0.13, 0.008, V(0, B.seat - 0.14, SEAT_Z0 - 0.18)));
const PEG = V(0, SP.y - 0.01, SP.z - 0.02);
for (const sx of [-1, 1]) {
  SUB = 'footpegs';
  add('body', 'alloy', roundedBox(0.012, 0.10, 0.08, 0.004, V(sx * 0.14, PEG.y + 0.04, PEG.z)));
  add('body', 'rubber', rod(V(sx * 0.14, PEG.y, PEG.z + 0.01), V(sx * 0.22, PEG.y, PEG.z + 0.005), 0.012, 12));
  add('body', 'alloy', rod(V(sx * 0.12, PEG.y + 0.10, PEG.z - 0.28), V(sx * 0.19, PEG.y + 0.10, PEG.z - 0.29), 0.009, 10));
}
SUB = 'brake_pedal';
add('body', 'alloy', tube([V(-0.15, PEG.y + 0.01, PEG.z), V(-0.17, PEG.y - 0.02, PEG.z + 0.10), V(-0.18, PEG.y - 0.01, PEG.z + 0.18)], 0.007, 16, 8));
SUB = 'gear_lever';
add('body', 'alloy', tube([V(0.15, PEG.y + 0.02, PEG.z), V(0.17, PEG.y, PEG.z + 0.10), V(0.18, PEG.y + 0.02, PEG.z + 0.18)], 0.007, 16, 8));
SUB = 'caliper_rear';
add('body', 'black', roundedBox(0.03, 0.06, 0.07, 0.01, V(-(ARM_X - 0.025), AR.y + 0.08, AR.z + 0.05)));

// the side stand, on the left
const STAND_PIVOT = V(0.13, B.clearance + 0.12, SP.z + 0.06);
const STAND_L = Math.hypot(STAND_PIVOT.y + 0.02, 0.12);
const STAND_FOLDED = V(0.10, 0.05, -1).normalize(), STAND_DOWN = V(0.32, -0.92, 0.22).normalize();
SUB = 'side_stand';
add('stand', 'black', rod(STAND_PIVOT, STAND_PIVOT.clone().addScaledVector(STAND_FOLDED, STAND_L), 0.011));
add('stand', 'black', ball(STAND_PIVOT.clone().addScaledVector(STAND_FOLDED, STAND_L + 0.01), 0.02, 1.3, 0.6, 1.3));
add('stand', 'alloy', rod(STAND_PIVOT.clone().add(V(-0.015, 0, 0)), STAND_PIVOT.clone().add(V(0.015, 0, 0)), 0.016));

// ── hierarchy and clips ─────────────────────────────────────────────────
const PIVOT = { steer: axisAt(T_HEAD0 + 0.08), wheel_f: AF.clone(), wheel_r: AR.clone(), stand: STAND_PIVOT.clone() };
const PARENT = { steer: null, wheel_f: 'steer', wheel_r: null, stand: null };
const SPLIT = !!args.parts;
const pieceName = (part, sub) => part.startsWith('wheel_') && ['tyre', 'rim', 'disc'].includes(sub) ? `${sub}_${part.slice(-1)}` : sub;
const X = V(1, 0, 0);
const STEER = KIND === 'trail' || KIND === 'adventure' ? 34 : 30;
// the bike's own size, as built (the stand folded)
const box = new THREE.Box3();
for (const [p, , g] of parts) if (p !== 'stand') { g.computeBoundingBox(); box.union(g.boundingBox); }
const ENGINE = { single: 'single-cylinder', twin: 'parallel twin', vtwin: 'V-twin', boxer: 'flat (boxer) twin', triple: 'inline triple', four: 'inline four' }[LAYOUT];
const tyreName = t => `${t[1]}/${t[2]}-${t[0]}`;
const { tris } = await writeBike({
  out: OUT, sceneName: KIND, mats: MATS, pieces: parts, pivots: PIVOT, parents: PARENT, split: SPLIT, pieceName,
  doubleSided: ['screen'],
  extras: { kind: 'motorbike', type: KIND, model: B.name, wheelbase_m: W, length_m: +(box.max.z - box.min.z).toFixed(3),
    height_m: +box.max.y.toFixed(3), width_m: +(box.max.x - box.min.x).toFixed(3), seat_m: B.seat, rake_deg: B.rake, trail_m: B.trail,
    tyres: [tyreName(B.front), tyreName(B.rear)], engine: `${Math.round(B.cc)} cc ${AIR ? 'air' : 'liquid'}-cooled ${ENGINE}`,
    sizes_note: args.sizes || null, clips: ['wheels_spin', 'steer_left', 'steer_right', 'stand_down'], generator: 'bikes/standard.mjs',
    engine_note: `Modelled in code by the machine: a representative ${AIR ? 'air' : 'liquid'}-cooled ${ENGINE} of about ${Math.round(B.cc)} cc `
      + 'with its gearbox in the same cases and a chain to the rear wheel. Not the maker\'s engine: its size and layout only.',
    pivots: { steer: 'the fork, bars, front wheel, discs and calipers turn about the raked steering axis',
      wheel_f: 'the front wheel turns on its axle', wheel_r: 'the rear wheel turns on its axle', stand: 'the side stand swings down' } },
  order: ['steer', 'wheel_r', 'wheel_f', 'stand'], meshOrder: ['body', 'steer', 'wheel_f', 'wheel_r', 'stand'],
  clips: (nodes, clip, q) => {
    const spin = [0, 90, 180, 270, 360].map(d => q(X, d));
    clip('wheels_spin', [[nodes.wheel_f, [0, 0.25, 0.5, 0.75, 1], spin], [nodes.wheel_r, [0, 0.25, 0.5, 0.75, 1], spin]]);
    clip('steer_left', [[nodes.steer, [0, 1], [q(U, 0), q(U, STEER)]]]);
    clip('steer_right', [[nodes.steer, [0, 1], [q(U, 0), q(U, -STEER)]]]);
    clip('stand_down', [[nodes.stand, [0, 1], [[0, 0, 0, 1], new THREE.Quaternion().setFromUnitVectors(STAND_FOLDED, STAND_DOWN).toArray()]]]);
  },
  copyright: `${B.name}: modelled in code by the ExpertCarCheck GLB machine (bikes/standard.mjs), ${args.sizes || "to the figures its spec gives, the rest its kind's typical ones"}. No maker's model, badge or lettering.`,
});
console.log(JSON.stringify({ wrote: OUT, kind: KIND, triangles: Math.round(tris), parts: [...new Set(parts.map(p => p[0]))],
  pieces: SPLIT ? [...new Set(parts.map(p => pieceName(p[0], p[3] || p[0])))] : undefined,
  front_tyre_d_m: +(2 * TF.R).toFixed(3), rear_tyre_d_m: +(2 * TR.R).toFixed(3), wheelbase_m: W,
  length_m: +(box.max.z - box.min.z).toFixed(3), height_m: +box.max.y.toFixed(3), width_m: +(box.max.x - box.min.x).toFixed(3),
  seat_m: B.seat, fork_offset_m: +new THREE.Vector3().subVectors(AF, G).dot(N).toFixed(3) }));
