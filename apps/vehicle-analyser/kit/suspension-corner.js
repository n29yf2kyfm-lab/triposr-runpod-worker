// suspension-corner.js: a working front corner (MacPherson strut) for a
// teaching app: see a spring, a damper, a lower arm and a hub carrier do
// their jobs, then take them apart.
//
// The geometry is solved every frame, not played back: the lower arm swings
// about its two inner bushes, the ball joint at its end follows; the strut
// always runs from the ball joint's knuckle to the fixed top mount, so it
// shortens in bump and the coil spring between its seats squashes; the
// knuckle, hub, disc, caliper and wheel ride with it; the driveshaft runs
// from the fixed gearbox output to the hub and changes length (the inner
// joint plunges). Steering turns the knuckle about the strut's axis, the
// kingpin. The ride is a quarter car: the road pushes the wheel up, the
// spring and damper decide how the body follows. A worn damper keeps
// bouncing.
//
//   import { createSuspensionCorner } from './suspension-corner.js';
//   const s = createSuspensionCorner(THREE);
//   scene.add(s.group);
//   s.setMode('bump');            // 'static' | 'bump' | 'manual'
//   // each frame: s.update(dtSeconds)
//
// Frame: metres; +Y up, +Z forward, +X outboard (a left-hand corner, the
// car's centre line at x = 0), the ground at y = 0. Our own geometry and
// motion. ExpertCarCheck; proprietary.

export const CORNER_PARTS = [
  { id: 'top_mount', label: 'Top mount', system: 'Suspension', text: 'Bolts the top of the strut to the body. A bearing inside lets the strut turn when you steer.' },
  { id: 'spring', label: 'Coil spring', system: 'Suspension', text: 'Carries the car’s weight and stores the energy of a bump. It sets how far the car sinks and how quickly it bounces.' },
  { id: 'damper_rod', label: 'Damper rod', system: 'Suspension', text: 'Slides into the damper body. Oil forced through valves in its piston slows the movement.' },
  { id: 'damper', label: 'Damper (shock absorber)', system: 'Suspension', text: 'Turns movement into heat so the spring does not keep bouncing. A worn one lets the car wallow and the tyre skip.' },
  { id: 'bump_stop', label: 'Bump stop', system: 'Suspension', text: 'A rubber or foam stop on the rod that cushions the last part of the travel.' },
  { id: 'knuckle', label: 'Hub carrier (knuckle)', system: 'Suspension', text: 'Clamped to the strut. It carries the wheel bearing and hub, the brake caliper and the steering arm.' },
  { id: 'lower_arm', label: 'Lower arm (wishbone)', system: 'Suspension', text: 'Locates the bottom of the knuckle. It pivots on two rubber bushes on the subframe.' },
  { id: 'ball_joint', label: 'Ball joint', system: 'Suspension', text: 'Joins the lower arm to the knuckle and lets it swing and steer. A worn one knocks over bumps.' },
  { id: 'arm_bushes', label: 'Lower arm bushes', system: 'Suspension', text: 'Rubber pivots that let the arm swing and soak up vibration. Cracked bushes cause clunks and wander.' },
  { id: 'subframe', label: 'Subframe', system: 'Suspension', text: 'A steel frame bolted under the car that the arms, steering rack and engine mounts hang from.' },
  { id: 'anti_roll_bar', label: 'Anti-roll bar', system: 'Suspension', text: 'A torsion bar linking left and right. It twists when one side rises, keeping the car flatter in corners.' },
  { id: 'drop_link', label: 'Drop link', system: 'Suspension', text: 'Joins the anti-roll bar to the strut. A worn drop link rattles over small bumps.' },
  { id: 'track_rod', label: 'Track rod', system: 'Steering', text: 'Pushes and pulls the steering arm as the rack moves, which turns the wheel.' },
  { id: 'track_rod_end', label: 'Track rod end', system: 'Steering', text: 'A small ball joint at the end of the track rod. It is adjusted to set the wheel alignment (toe).' },
  { id: 'driveshaft', label: 'Driveshaft', system: 'Transmission', text: 'Carries the drive from the gearbox to the wheel while the wheel moves up and down and steers.' },
  { id: 'cv_joints', label: 'CV joints and boots', system: 'Transmission', text: 'Constant-velocity joints let the shaft bend without the speed pulsing. A split boot lets the grease out.' },
  { id: 'hub', label: 'Wheel hub and bearing', system: 'Suspension', text: 'The wheel bolts to the hub, which turns in the bearing in the knuckle. A worn bearing hums with speed.' },
  { id: 'disc', label: 'Brake disc', system: 'Brakes', text: 'Turns with the wheel. The pads clamp it to slow the car, turning movement into heat.' },
  { id: 'caliper', label: 'Brake caliper', system: 'Brakes', text: 'Fixed to the knuckle. Brake fluid pressure pushes its piston, squeezing the pads onto the disc.' },
  { id: 'pads', label: 'Brake pads', system: 'Brakes', text: 'The friction material that wears. Replace before the backing plate touches the disc.' },
  { id: 'wheel', label: 'Wheel', system: 'Wheels', text: 'Bolted to the hub. Its offset sets where the tyre sits relative to the hub face.' },
  { id: 'tyre', label: 'Tyre', system: 'Wheels', text: 'The only part touching the road. Its own flex is the first spring in the system.' },
];

export function createSuspensionCorner(THREE, { coarse = false } = {}) {
  const V = (x, y, z) => new THREE.Vector3(x, y, z);
  const seg = coarse ? 20 : 40;
  const G = new THREE.Group(); G.name = 'suspension_corner';
  const mats = [];
  const mat = (hex, metal, rough, extra = {}) => {
    const m = new THREE.MeshStandardMaterial({ color: hex, metalness: metal, roughness: rough, ...extra });
    m.userData.base = new THREE.Color(hex); mats.push(m); return m;
  };
  const M = {
    body: mat(0x2b2e33, 0.4, 0.55), steel: mat(0x8d939a, 0.9, 0.35), dark: mat(0x3a3d42, 0.7, 0.45),
    spring: mat(0xf2c200, 0.3, 0.38), chrome: mat(0xd9dde2, 1.0, 0.12), rubber: mat(0x141416, 0.0, 0.9),
    alloy: mat(0xb8bdc3, 0.9, 0.28, { side: THREE.DoubleSide }), disc: mat(0x7d8288, 0.95, 0.42), caliper: mat(0xc8102e, 0.3, 0.4),
    pad: mat(0x4a4038, 0.1, 0.85), boot: mat(0x1b1c1f, 0.0, 0.7), road: mat(0x3a3a3c, 0.0, 0.95),
  };
  const parts = {};
  const part = id => {
    if (!parts[id]) {
      const g = new THREE.Group(); g.name = id; g.userData.part = id; G.add(g);
      parts[id] = { g, explode: V(0, 0, 0) };
    }
    return parts[id];
  };
  const mesh = (id, geo, m) => {
    const o = new THREE.Mesh(geo, m); o.userData.part = id; o.castShadow = true; o.receiveShadow = true;
    part(id).g.add(o); return o;
  };
  const up = V(0, 1, 0);
  // a unit cylinder (height 1 along Y) placed from a to b
  const placeRod = (o, a, b) => {
    const d = b.clone().sub(a), L = d.length();
    o.position.copy(a).addScaledVector(d, 0.5);
    o.quaternion.setFromUnitVectors(up, d.normalize());
    o.scale.set(1, Math.max(L, 1e-4), 1);
  };
  const rodGeo = (r, r1 = r) => new THREE.CylinderGeometry(r1, r, 1, seg / 2);
  const lathe = (profile, n = seg) => new THREE.LatheGeometry(profile.map(([r, y]) => new THREE.Vector2(r, y)), n);

  // ── fixed points (the body and subframe) ─────────────────────────────
  const T0 = V(0.536, 0.953, -0.056);                 // top mount, in the body turret
  const PF = V(0.30, 0.17, 0.12), PR = V(0.32, 0.18, -0.25);   // lower arm bushes, front and rear
  const B0 = V(0.70, 0.17, 0.0);                       // ball joint at rest
  const GB = V(0.20, 0.31, 0.0);                       // gearbox output (inner CV joint)
  const RACK = V(0.28, 0.27, -0.17);                   // steering rack end
  const ARB_C = V(0.0, 0.29, 0.22), ARB_E = V(0.44, 0.29, 0.22);   // anti-roll bar, centre to bend
  const pivotAxis = PR.clone().sub(PF).normalize();

  // the subframe and turret, fixed
  const sf = mesh('subframe', new THREE.BoxGeometry(0.40, 0.06, 0.52), M.body); sf.position.set(0.12, 0.16, -0.06);
  const turret = mesh('top_mount', lathe([[0.0, 0.0], [0.085, 0.0], [0.09, 0.012], [0.06, 0.04], [0.0, 0.045]]), M.dark);
  const topBearing = mesh('top_mount', rodGeo(0.045), M.rubber);
  // lower arm: two tubes from the bushes to the ball joint, the bushes, the ball joint
  const armF = mesh('lower_arm', rodGeo(0.022), M.steel), armR = mesh('lower_arm', rodGeo(0.022), M.steel);
  for (const p of [PF, PR]) {
    const b = mesh('arm_bushes', rodGeo(0.034), M.rubber); placeRod(b, p.clone().addScaledVector(pivotAxis, -0.03), p.clone().addScaledVector(pivotAxis, 0.03));
  }
  const bj = mesh('ball_joint', new THREE.SphereGeometry(0.03, seg / 2, seg / 4), M.dark);
  const bjBoot = mesh('ball_joint', lathe([[0.03, 0], [0.034, 0.02], [0.018, 0.045], [0.012, 0.05]]), M.boot);
  // strut: damper body (clamped in the knuckle), rod, bump stop, spring seats, spring
  const damper = mesh('damper', rodGeo(0.034), M.dark);
  const rod = mesh('damper_rod', rodGeo(0.011), M.chrome);
  const bumpStop = mesh('bump_stop', rodGeo(0.022, 0.016), M.rubber);
  const seatLo = mesh('spring', lathe([[0.03, 0], [0.085, 0], [0.085, 0.008], [0.03, 0.008]]), M.dark);
  const seatHi = mesh('spring', lathe([[0.03, 0], [0.08, 0], [0.08, 0.008], [0.03, 0.008]]), M.dark);
  const COILS = 5.5, SPR_R = 0.068, WIRE = 0.0115;
  const helix = (() => {
    const pts = [];
    for (let i = 0; i <= 220; i++) { const t = i / 220, a = t * COILS * Math.PI * 2; pts.push(V(Math.cos(a) * SPR_R, t, Math.sin(a) * SPR_R)); }
    return new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), 440, WIRE, 10, false);
  })();
  const spring = mesh('spring', helix, M.spring);
  // knuckle: a group that is the hub carrier's own frame (y up the strut, x outboard)
  const K = new THREE.Group(); K.name = 'knuckle_frame'; G.add(K);
  const kn = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.30, 0.09), M.steel); kn.userData.part = 'knuckle'; kn.position.set(0.03, 0.12, 0); kn.castShadow = true;
  const clamp = new THREE.Mesh(rodGeo(0.045), M.steel); clamp.userData.part = 'knuckle'; clamp.scale.y = 0.09; clamp.position.set(0, 0.25, 0);
  const steerArm = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.035, 0.15), M.steel); steerArm.userData.part = 'knuckle'; steerArm.position.set(0.0, 0.10, -0.09);
  K.add(kn, clamp, steerArm);
  part('knuckle').g.add(K);                               // one group per part for explode and pick
  // the hub, disc, caliper, pads and wheel hang off the hub centre, in the knuckle frame
  const HUB_LOCAL = V(0.075, 0.128, 0);                // hub centre in the knuckle frame
  const W = new THREE.Group(); W.position.copy(HUB_LOCAL); K.add(W);          // the non-spinning hub frame
  const spin = new THREE.Group(); W.add(spin);                                // what turns with the wheel
  const axle = g => { g.rotateZ(-Math.PI / 2); return g; };                   // lathe/cylinder axis Y -> X (outboard)
  const hub = new THREE.Mesh(axle(new THREE.CylinderGeometry(0.06, 0.06, 0.05, seg)), M.steel); hub.userData.part = 'hub'; hub.position.x = 0.025; spin.add(hub);
  const bearing = new THREE.Mesh(axle(new THREE.CylinderGeometry(0.05, 0.05, 0.05, seg)), M.dark); bearing.userData.part = 'hub'; bearing.position.x = -0.02; W.add(bearing);
  const disc = new THREE.Mesh(axle(lathe([[0.07, -0.013], [0.142, -0.013], [0.142, 0.013], [0.07, 0.013]], 64)), M.disc); disc.userData.part = 'disc'; disc.position.x = 0.0; spin.add(disc);
  for (let k = 0; k < 6; k++) {                        // drilled/ventilated look: radial grooves
    const groove = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.004, 0.0035), M.dark); groove.userData.part = 'disc';
    const a = k / 6 * Math.PI * 2; groove.position.set(0.0137, Math.cos(a) * 0.11, Math.sin(a) * 0.11); groove.rotation.x = -a; spin.add(groove);
  }
  const caliper = new THREE.Mesh(new THREE.BoxGeometry(0.075, 0.11, 0.06), M.caliper); caliper.userData.part = 'caliper';
  caliper.position.set(0.0, 0.0, -0.118); W.add(caliper);
  const padIn = new THREE.Mesh(new THREE.BoxGeometry(0.009, 0.085, 0.045), M.pad), padOut = padIn.clone();
  padIn.userData.part = padOut.userData.part = 'pads'; W.add(padIn, padOut);
  // the wheel: an open barrel round the brake, its face outboard on the hub flange
  const WHEEL_X = -0.01, TYRE_X = -0.022, SPOKE_X = 0.058;
  const rimGeo = axle(lathe([[0.196, -0.106], [0.203, -0.098], [0.203, 0.085], [0.19, 0.095], [0.09, 0.07], [0.06, 0.06], [0.04, 0.06]], 64));
  const rim = new THREE.Mesh(rimGeo, M.alloy); rim.userData.part = 'wheel'; rim.position.x = WHEEL_X; spin.add(rim);
  for (let k = 0; k < 5; k++) {                         // five spokes
    const s = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.15, 0.036), M.alloy); s.userData.part = 'wheel';
    const a = k / 5 * Math.PI * 2; s.position.set(SPOKE_X, Math.cos(a) * 0.11, Math.sin(a) * 0.11); s.rotation.x = -a; spin.add(s);
  }
  const tyreProf = [];
  for (let i = 0; i <= 24; i++) {
    const t = -Math.PI / 2 + Math.PI * i / 24, c = Math.cos(t), s = Math.sin(t);
    tyreProf.push([0.203 + 0.113 * Math.abs(c) ** 0.6, 0.1025 * Math.sign(s) * Math.abs(s) ** 0.7]);   // bead to crown to bead
  }
  const tyre = new THREE.Mesh(axle(lathe(tyreProf, 72)), M.rubber); tyre.userData.part = 'tyre'; tyre.position.x = TYRE_X; spin.add(tyre);
  for (const o of [hub, bearing, disc, caliper, padIn, padOut, rim, tyre]) { o.castShadow = true; }
  // hand the wheel-side meshes to their part groups for pick and explode, keeping their frames:
  // they stay in the knuckle frame; the part groups carry only an explode offset that we add to W
  // driveshaft with its joints and boots, the anti-roll bar, drop link, track rod
  const shaft = mesh('driveshaft', rodGeo(0.016), M.steel);
  const cvIn = mesh('cv_joints', lathe([[0.045, 0], [0.05, 0.03], [0.03, 0.08], [0.018, 0.1]]), M.boot);
  const cvOut = mesh('cv_joints', lathe([[0.045, 0], [0.05, 0.03], [0.03, 0.08], [0.018, 0.1]]), M.boot);
  const arbBar = mesh('anti_roll_bar', rodGeo(0.012), M.dark), arbArm = mesh('anti_roll_bar', rodGeo(0.012), M.dark);
  const drop = mesh('drop_link', rodGeo(0.008), M.steel);
  const dropBallA = mesh('drop_link', new THREE.SphereGeometry(0.016, 16, 10), M.dark), dropBallB = dropBallA.clone(); part('drop_link').g.add(dropBallB);
  const trackRod = mesh('track_rod', rodGeo(0.011), M.steel);
  const tre = mesh('track_rod_end', new THREE.SphereGeometry(0.02, 16, 10), M.dark);
  const road = mesh('road', new THREE.BoxGeometry(0.7, 0.04, 1.4), M.road);
  part('road').g.userData.part = null; road.userData.part = null;

  const meshes = [];
  G.traverse(o => {
    if (!o.isMesh) return;
    const base = o.material.userData.base;
    o.material = o.material.clone(); o.material.userData.base = base.clone();
    meshes.push(o);
  });
  const discMeshes = meshes.filter(o => o.userData.part === 'disc');

  // explode directions for teardown, per part (outboard, up, back)
  const EX = {
    top_mount: V(0, 0.45, 0), spring: V(0.25, 0.25, 0), damper_rod: V(0.05, 0.35, 0), damper: V(0.35, 0.10, 0),
    bump_stop: V(0.15, 0.3, 0), knuckle: V(0.45, 0, 0), lower_arm: V(0.1, -0.25, 0), ball_joint: V(0.25, -0.2, 0),
    arm_bushes: V(-0.05, -0.3, 0), subframe: V(-0.25, -0.15, 0), anti_roll_bar: V(-0.1, 0, 0.35), drop_link: V(0, 0.1, 0.35),
    track_rod: V(-0.1, 0, -0.35), track_rod_end: V(0.05, 0, -0.4), driveshaft: V(-0.1, 0.05, 0.2), cv_joints: V(-0.15, 0.1, 0.25),
    hub: V(0.45, 0, 0), disc: V(0.4, 0, 0), caliper: V(0.3, 0, -0.28), pads: V(0.35, 0.05, -0.36), wheel: V(0.55, 0, 0), tyre: V(0.7, 0, 0),
  };
  for (const [id, v] of Object.entries(EX)) part(id).explode = v;

  // ── state ────────────────────────────────────────────────────────────
  const S = {
    mode: 'static', travel: 0, steer: 0, brake: 0, speed: 0, explode: 0, damping: 0.3,
    // quarter car: the body (z) on spring and damper over the road (r); travel = r - z
    t: 0, r: 0, rv: 0, z: 0, zv: 0, wheelAngle: 0, highlight: null, lastTravel: 0, damperSpeed: 0,
  };
  const OMEGA = 2 * Math.PI * 1.25;                    // body bounce, about 1.25 Hz, as on a road car
  const TRAVEL = 0.085;                                // metres of wheel travel each way
  const bump = t => {                                  // a 60 mm bump, 0.25 s across, every 3.2 s
    const c = t % 3.2;
    return c < 0.25 ? 0.06 * Math.sin(Math.PI * c / 0.25) : 0;
  };

  const tmp = V(0, 0, 0), q = new THREE.Quaternion(), basis = new THREE.Matrix4();
  function solve() {
    // arm angle from travel: rotate the ball joint about the bush axis until the hub has risen `travel`
    const a = S.travel * TRAVEL / 0.37;               // the arm is 0.37 m long
    q.setFromAxisAngle(pivotAxis, -a);
    const B = B0.clone().sub(PF).applyQuaternion(q).add(PF);
    // the strut runs from the knuckle to the top mount; the knuckle's y is that axis
    const u = T0.clone().sub(B).normalize();
    let xk = V(1, 0, 0).addScaledVector(u, -u.x).normalize();
    let zk = new THREE.Vector3().crossVectors(xk, u).normalize();
    // steering turns the knuckle about the kingpin (the strut axis), 30° at full lock
    const st = S.steer * THREE.MathUtils.degToRad(30);
    xk.applyAxisAngle(u, st); zk.applyAxisAngle(u, st);
    basis.makeBasis(xk, u, zk);
    K.position.copy(B); K.quaternion.setFromRotationMatrix(basis);
    // arm tubes, ball joint
    placeRod(armF, PF, B); placeRod(armR, PR, B);
    bj.position.copy(B); bjBoot.position.copy(B); bjBoot.quaternion.copy(K.quaternion);
    // strut: body from 0.22 to 0.52 up the axis, rod from there to the top mount
    const at = s => B.clone().addScaledVector(u, s);
    placeRod(damper, at(0.22), at(0.52));
    placeRod(rod, at(0.50), T0);
    const len = T0.distanceTo(B);
    placeRod(bumpStop, at(Math.max(0.53, len - 0.12)), at(Math.max(0.58, len - 0.06)));
    const lo = at(0.44), hi = T0.clone().addScaledVector(u, -0.05);
    seatLo.position.copy(lo); seatLo.quaternion.setFromUnitVectors(up, u);
    seatHi.position.copy(hi); seatHi.quaternion.setFromUnitVectors(up, u);
    spring.position.copy(lo).addScaledVector(u, 0.008); spring.quaternion.setFromUnitVectors(up, u);
    spring.scale.set(1, lo.distanceTo(hi) - 0.016, 1);
    turret.position.copy(T0); turret.quaternion.setFromUnitVectors(up, u);
    placeRod(topBearing, T0.clone().addScaledVector(u, -0.02), T0.clone().addScaledVector(u, 0.02));
    // hub centre in the world, the driveshaft to it
    K.updateMatrixWorld(true);
    const H = W.getWorldPosition(V(0, 0, 0));
    const hubIn = H.clone().addScaledVector(xk, -0.05);
    placeRod(shaft, GB.clone().addScaledVector(xk, 0.06), hubIn.clone().addScaledVector(xk, -0.07));
    cvIn.position.copy(GB); cvIn.quaternion.setFromUnitVectors(up, hubIn.clone().sub(GB).normalize());
    cvOut.position.copy(hubIn); cvOut.quaternion.setFromUnitVectors(up, GB.clone().sub(hubIn).normalize());
    // anti-roll bar: the bar fixed, its arm pivots so the drop link keeps its length
    const D = at(0.31).addScaledVector(zk, 0.065);              // drop link's top, on the strut body
    const armEnd = V(ARB_E.x + 0.04, D.y - 0.17, D.z);
    placeRod(arbBar, ARB_C, ARB_E); placeRod(arbArm, ARB_E, armEnd);
    placeRod(drop, armEnd, D); dropBallA.position.copy(D); dropBallB.position.copy(armEnd);
    // track rod: rack end slides inboard/outboard with the steering, to the steering arm's ball
    const S_ARM = K.localToWorld(V(0.0, 0.10, -0.165));
    const rackEnd = RACK.clone().add(V(-S.steer * 0.035, 0, 0));
    placeRod(trackRod, rackEnd, S_ARM); tre.position.copy(S_ARM);
    // the road under the tyre
    const tc = W.localToWorld(V(TYRE_X, 0, 0));
    road.position.set(tc.x, tc.y - 0.318 - 0.02, tc.z);
    // brakes: the pads close on the disc as the pedal goes down
    const gap = 0.006 * (1 - S.brake);
    padIn.position.set(-0.0175 - gap, 0, -0.118); padOut.position.set(0.0175 + gap, 0, -0.118);
    const glow = S.highlight === 'disc' ? null : 0.55 * S.brake * Math.min(1, S.speed / 8);
    if (glow !== null) for (const o of discMeshes) o.material.emissive.setRGB(glow, glow * 0.22, 0);
    spin.rotation.x = S.wheelAngle;
    // teardown: each part's group moves along its own direction
    for (const [id, p] of Object.entries(parts)) {
      if (id === 'knuckle') continue;
      p.g.position.copy(p.explode).multiplyScalar(S.explode);
    }
    // the knuckle frame carries the hub, disc, caliper, pads and wheel: explode them inside it
    const e = S.explode;
    K.position.addScaledVector(EX.knuckle, e);
    hub.position.x = 0.025 + EX.hub.x * e * 0.5; bearing.position.x = -0.02 + EX.hub.x * e * 0.45;
    disc.position.x = EX.disc.x * e * 0.6;
    caliper.position.set(EX.caliper.x * e * 0.5, 0, -0.118 + EX.caliper.z * e);
    padIn.position.x += EX.pads.x * e * 0.4; padOut.position.x += EX.pads.x * e * 0.45; padIn.position.z += EX.pads.z * e; padOut.position.z += EX.pads.z * e;
    rim.position.x = WHEEL_X + EX.wheel.x * e; tyre.position.x = TYRE_X + EX.tyre.x * e;
    spin.children.forEach(o => { if (o.userData.part === 'wheel' && o !== rim) o.position.x = SPOKE_X + EX.wheel.x * e; if (o.userData.part === 'tyre' && o !== tyre) o.position.x = TYRE_X + EX.tyre.x * e; });
    if (e > 0) road.visible = false; else road.visible = true;
  }

  function update(dt = 0) {
    dt = Math.min(dt, 0.05);
    S.t += dt;
    if (S.mode === 'bump') {
      // quarter car, integrated in small steps: z'' = ω²(r - z) + 2ζω(r' - z')
      const n = Math.max(1, Math.ceil(dt / 0.002)), h = dt / n;
      for (let i = 0; i < n; i++) {
        const tt = S.t - dt + (i + 1) * h, r = bump(tt);
        S.rv = (r - S.r) / h; S.r = r;
        const acc = OMEGA * OMEGA * (S.r - S.z) + 2 * S.damping * OMEGA * (S.rv - S.zv);
        S.zv += acc * h; S.z += S.zv * h;
      }
      S.travel = Math.max(-1, Math.min(1, (S.r - S.z) / TRAVEL));
      if (S.speed === 0) S.speed = 6;
    } else if (S.mode === 'static') {
      S.travel += (0 - S.travel) * Math.min(1, dt * 6);
    }
    S.damperSpeed = dt > 0 ? (S.travel - S.lastTravel) * TRAVEL / dt : 0;
    S.lastTravel = S.travel;
    // wheel speed (m/s of tread); brakes slow it
    if (S.brake > 0) S.speed = Math.max(0, S.speed - S.brake * 9 * dt);
    S.wheelAngle += dt * S.speed / 0.318;
    solve();
  }

  function highlight(id) {
    S.highlight = id || null;
    const dim = new THREE.Color(0x1d1f22);
    for (const o of meshes) {
      const m = o.material;
      m.color.copy(m.userData.base); m.emissive.setRGB(0, 0, 0); m.emissiveIntensity = 1;
      if (!id || !o.userData.part) continue;
      if (o.userData.part === id) { m.emissive.set(0xf2c200); m.emissiveIntensity = 0.35; }
      else m.color.lerp(dim, 0.6);
    }
  }

  function anchor(id) {
    const box = new THREE.Box3();
    G.traverse(o => { if (o.isMesh && o.userData.part === id) box.expandByObject(o); });
    return box.isEmpty() ? null : box.getCenter(V(0, 0, 0));
  }

  update(0);
  return {
    group: G,
    parts: CORNER_PARTS,
    update,
    setMode(m) { S.mode = m; S.z = S.zv = S.r = S.rv = 0; if (m === 'bump') S.t = 0; },   // 'static' | 'bump' | 'manual'
    setTravel(t) { S.mode = 'manual'; S.travel = Math.max(-1, Math.min(1, t)); solve(); },   // -1 full droop .. +1 full bump
    setDamping(z) { S.damping = Math.max(0.02, Math.min(1, z)); },   // 0.3 healthy, 0.05 a worn-out damper
    setSteer(s) { S.steer = Math.max(-1, Math.min(1, s)); solve(); },  // -1 full lock right .. +1 full lock left
    setSpeed(v) { S.speed = Math.max(0, v); },          // tread speed, m/s
    setBrake(b) { S.brake = Math.max(0, Math.min(1, b)); },
    setExplode(e) { S.explode = Math.max(0, Math.min(1, e)); solve(); },
    highlight, anchor,
    readout: () => ({
      travel_mm: Math.round(S.travel * TRAVEL * 1000),
      spring_length_mm: Math.round((spring.scale.y) * 1000),
      damper_speed_mm_s: Math.round(S.damperSpeed * 1000),
      steer_deg: Math.round(S.steer * 30),
      wheel_rpm: Math.round(S.speed / (2 * Math.PI * 0.318) * 60),
    }),
    dispose() { G.traverse(o => { if (o.isMesh) o.geometry.dispose(); }); mats.forEach(m => m.dispose()); },
  };
}
