// running-engine.js: a running, cut-open inline four for a teaching app.
//
// The same engine as the car page's "See it run" (pipeline/realcar/page/car.html),
// lifted out as a module: pistons on a true slider-crank (piston height
// r·cos a + √(l² − r²·sin²a)), the crank turning, two camshafts at half crank
// speed lifting the valves on their strokes, the timing chain's sprockets,
// and each cylinder firing at the top of its compression stroke, in the
// order 1-3-4-2. The block and head are cut open at the front so the bores
// show. Our own geometry and motion. ExpertCarCheck; proprietary.
//
//   import { createRunningEngine } from './running-engine.js';
//   const eng = createRunningEngine(THREE);
//   scene.add(eng.group);                 // renderer.localClippingEnabled = true for the cut
//   // each frame:  eng.update(dtSeconds)
//
// Frame: metres, +Y up, the crank along X, the open (cut) side towards +Z.

export const STROKES = [
  { id: 'intake', label: 'Intake', colour: '#1f8f4a' },
  { id: 'compression', label: 'Compression', colour: '#1f5fbf' },
  { id: 'power', label: 'Power', colour: '#c8102e' },
  { id: 'exhaust', label: 'Exhaust', colour: '#595f66' },
];

export const SYSTEMS = [
  { id: 'air', label: 'Air', text: 'Air is drawn through the intake runners and past the open intake valve into the cylinder on the intake stroke.' },
  { id: 'fuel', label: 'Fuel', text: 'Petrol is sprayed into the intake air by the injectors; the mix is what burns.' },
  { id: 'spark', label: 'Spark', text: 'The coil fires the spark plug at the top of the compression stroke to light the mix.' },
  { id: 'exhaust', label: 'Exhaust', text: 'Burnt gas is pushed out past the exhaust valve into the headers on the exhaust stroke.' },
  { id: 'cooling', label: 'Cooling', text: 'Coolant flows through the jacket around the bores to carry heat away.' },
  { id: 'oil', label: 'Oil', text: 'Oil is pumped up to the crank journals, the rod bearings and the camshafts.' },
];

// the parts a learner can point at, with what each one does
export const ENGINE_PARTS = [
  { id: 'block', label: 'Cylinder block', text: 'The cast body of the engine. The four bores the pistons run in are machined into it, with a coolant jacket round them.' },
  { id: 'head', label: 'Cylinder head', text: 'Closes the top of the bores. It carries the valves, the camshafts and the spark plugs.' },
  { id: 'piston', label: 'Pistons', text: 'Pushed down by the burning mix on the power stroke; their rings seal against the bore.' },
  { id: 'rod', label: 'Connecting rods', text: 'Link each piston to the crankshaft, turning up-and-down into round-and-round.' },
  { id: 'crank', label: 'Crankshaft', text: 'Turns once for every two piston strokes. Cylinders 1 and 4 are up together, 2 and 3 together.' },
  { id: 'flywheel', label: 'Flywheel', text: 'Its weight smooths the pulses between firing strokes and carries the clutch.' },
  { id: 'cam', label: 'Camshafts', text: 'Turn at half crank speed. One lobe per valve opens it at the right moment in the cycle.' },
  { id: 'valve', label: 'Valves', text: 'Intake valves let the mix in; exhaust valves let the burnt gas out. Springs close them.' },
  { id: 'plug', label: 'Spark plugs', text: 'Fire once every two turns of the crank, at the top of each cylinder’s compression stroke.' },
  { id: 'chain', label: 'Timing chain', text: 'Drives the camshafts from the crank at exactly half speed. If it slips, valves can hit pistons.' },
  { id: 'sump', label: 'Sump', text: 'Holds the engine oil under the crank; the oil pump draws from it.' },
];

export function createRunningEngine(THREE, { coarse = false } = {}) {
  const R = {
    play: true, speed: 0.26, strip: 0, theta: 0, sys: 'none', revPerSec: 0,
    pistons: [], rods: [], crank: null, cams: [], valves: [], sprockets: [], plugs: [], flashes: [],
  };
  const EG = { s: 0.112, rb: 0.0425, r: 0.0425, l: 0.136 };
  EG.cx = [-1.5, -0.5, 0.5, 1.5].map(k => k * EG.s);
  EG.phase = [0, Math.PI, Math.PI, 0];               // 1 and 4 up together, 2 and 3 down
  EG.cycle = [0, 180, 540, 360];                      // place in the 720° cycle: power on 1, then 3, 4, 2
  const localCut = new THREE.Plane(new THREE.Vector3(0, 0, -1), 0.004);   // keep the back half
  const cut = localCut.clone();
  const allMats = [];
  const emat = (hex, m, ro, clip) => {
    const mat = new THREE.MeshStandardMaterial({ color: hex, metalness: m, roughness: ro });
    if (clip) { mat.clippingPlanes = [cut]; mat.side = THREE.DoubleSide; }
    mat.userData.base = new THREE.Color(hex);
    allMats.push(mat);
    return mat;
  };
  const tag = (o, part) => { o.traverse(c => { c.userData.part = part; }); return o; };
  const seg = coarse ? 20 : 36, G = new THREE.Group();
  G.name = 'running_engine';
  const mBlock = emat(0x8a9099, 0.55, 0.5, true), mHead = emat(0x767c85, 0.55, 0.5, true);
  const mBore = emat(0x3b3f45, 0.3, 0.7, true);
  const mPiston = emat(0xc6cacf, 0.9, 0.3), mRod = emat(0x9aa0a6, 0.9, 0.34), mCrank = emat(0x6d7278, 0.95, 0.3);
  const mSteel = emat(0xb9bdc2, 1, 0.25), mSprocket = emat(0xb9bdc2, 1, 0.25);
  const mValves = { in: emat(0xcacdd1, 0.95, 0.28), ex: emat(0xcacdd1, 0.95, 0.28) };
  const mSprings = { in: emat(0x55595e, 0.8, 0.4), ex: emat(0x55595e, 0.8, 0.4) };
  const mPlug = emat(0xd9b24a, 0.7, 0.35), mChain = emat(0x5b6066, 0.9, 0.45);
  const halfX = (EG.cx[3] - EG.cx[0]) / 2 + EG.s * 0.7, zB = 0.052;
  const M = (geo, mat) => new THREE.Mesh(geo, mat);

  // block: back wall and deck, cut so the front is open and the bores show
  const block = new THREE.Group();
  const deck = M(new THREE.BoxGeometry(halfX * 2, 0.014, zB * 2), mBlock); deck.position.y = EG.r + 0.064;
  const backWall = M(new THREE.BoxGeometry(halfX * 2, 0.26, 0.012), mBlock); backWall.position.set(0, 0, -zB);
  block.add(deck, backWall);
  for (const i of [-1, 1]) { const end = M(new THREE.BoxGeometry(0.012, 0.26, zB * 2), mBlock); end.position.x = i * halfX; block.add(end); }
  const deckTopY = deck.position.y;
  for (const x of EG.cx) {
    const bore = M(new THREE.CylinderGeometry(EG.rb * 1.06, EG.rb * 1.06, 0.13, seg, 1, true), mBore);
    bore.position.set(x, deckTopY - 0.072, 0); block.add(bore);
  }
  G.add(tag(block, 'block'));
  const sump = M(new THREE.BoxGeometry(halfX * 1.7, 0.05, zB * 1.6), mBlock); sump.position.y = -EG.r - 0.055;
  G.add(tag(sump, 'sump'));

  // crankshaft: turns about X; a pin at radius r on each throw
  const crank = new THREE.Group();
  const main = M(new THREE.CylinderGeometry(0.019, 0.019, halfX * 2, seg), mCrank); main.rotation.z = Math.PI / 2; crank.add(main);
  EG.cx.forEach((x, i) => {
    const ph = EG.phase[i];
    const web1 = M(new THREE.BoxGeometry(0.012, EG.r * 2.3, 0.05), mCrank), web2 = web1.clone();
    web1.position.x = x - 0.02; web2.position.x = x + 0.02;
    for (const w of [web1, web2]) { w.rotation.x = ph; w.position.y = Math.cos(ph) * EG.r * 0.5; w.position.z = Math.sin(ph) * EG.r * 0.5; crank.add(w); }
    const pin = M(new THREE.CylinderGeometry(0.014, 0.014, 0.05, seg), mCrank);
    pin.rotation.z = Math.PI / 2; pin.position.set(x, Math.cos(ph) * EG.r, Math.sin(ph) * EG.r); crank.add(pin);
  });
  tag(crank, 'crank');
  const fly = M(new THREE.CylinderGeometry(0.09, 0.09, 0.022, seg), mCrank); fly.rotation.z = Math.PI / 2; fly.position.x = -halfX - 0.02;
  crank.add(tag(fly, 'flywheel'));
  G.add(crank); R.crank = crank;

  // pistons and rods
  EG.cx.forEach(x => {
    const p = M(new THREE.CylinderGeometry(EG.rb, EG.rb, 0.055, seg), mPiston); p.position.set(x, 0, 0); G.add(tag(p, 'piston')); R.pistons.push(p);
    const rod = M(new THREE.CylinderGeometry(0.009, 0.012, EG.l, seg), mRod); G.add(tag(rod, 'rod')); R.rods.push(rod);
  });

  // head, cut like the block
  const head = new THREE.Group(), headY = deckTopY + 0.055;
  const headBox = M(new THREE.BoxGeometry(halfX * 2, 0.07, zB * 1.7), mHead); headBox.position.y = headY; head.add(tag(headBox, 'head'));
  G.add(head);
  for (const side of [-1, 1]) {
    const cam = new THREE.Group(); cam.position.set(0, headY + 0.03, side * 0.028);
    const shaft = M(new THREE.CylinderGeometry(0.01, 0.01, halfX * 2, seg), mSteel); shaft.rotation.z = Math.PI / 2; cam.add(shaft);
    EG.cx.forEach(x => {
      const lobe = M(new THREE.CylinderGeometry(0.016, 0.016, 0.016, seg), mSteel); lobe.scale.y = 1.5; lobe.rotation.z = Math.PI / 2; lobe.position.x = x; cam.add(lobe);
    });
    cam.userData.y0 = cam.position.y;
    head.add(tag(cam, 'cam')); R.cams.push(cam);
    const kind = side < 0 ? 'in' : 'ex';
    EG.cx.forEach((x, i) => {
      const v = new THREE.Group(); v.position.set(x, headY - 0.01, side * 0.028);
      v.add(M(new THREE.CylinderGeometry(0.006, 0.006, 0.07, 12), mValves[kind]));
      const face = M(new THREE.CylinderGeometry(0.018, 0.012, 0.012, seg), mValves[kind]); face.position.y = -0.04; v.add(face);
      const spring = M(new THREE.CylinderGeometry(0.013, 0.013, 0.03, 12, 1, true), mSprings[kind]); spring.position.y = 0.012; v.add(spring);
      head.add(tag(v, 'valve')); R.valves.push({ g: v, cyl: i, kind, y0: v.position.y });
    });
  }
  EG.cx.forEach(x => {
    const plug = M(new THREE.CylinderGeometry(0.006, 0.006, 0.03, 12), mPlug); plug.position.set(x, headY - 0.028, 0); head.add(tag(plug, 'plug')); R.plugs.push(plug);
    const flashMat = new THREE.MeshBasicMaterial({ color: 0xffe08a, transparent: true, opacity: 0, depthWrite: false });
    const flash = M(new THREE.SphereGeometry(EG.rb * 0.8, 16, 12), flashMat); flash.position.set(x, deckTopY - 0.03, 0); G.add(flash);
    R.flashes.push({ m: flashMat, k: 0, prev: undefined });
  });

  // timing chain: sprockets on the crank and cam noses, a loop over them
  const nose = halfX + 0.012;
  const sCrank = M(new THREE.CylinderGeometry(0.028, 0.028, 0.012, seg), mSprocket); sCrank.rotation.z = Math.PI / 2; sCrank.position.set(nose, 0, 0);
  G.add(tag(sCrank, 'chain')); R.sprockets.push({ m: sCrank, ratio: 1 });
  for (const side of [-1, 1]) {
    const sc = M(new THREE.CylinderGeometry(0.04, 0.04, 0.012, seg), mSprocket); sc.rotation.z = Math.PI / 2; sc.position.set(nose, headY + 0.03, side * 0.028);
    G.add(tag(sc, 'chain')); R.sprockets.push({ m: sc, ratio: 0.5 });
  }
  const cp = [new THREE.Vector3(nose, -0.028, -0.028), new THREE.Vector3(nose, -0.028, 0.028), new THREE.Vector3(nose, headY + 0.07, 0.028), new THREE.Vector3(nose, headY + 0.07, -0.028)];
  G.add(tag(M(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(cp, true), 60, 0.006, 6, true), mChain), 'chain'));

  // intake (−z, blue) and exhaust (+z, rust) manifolds, shown with the systems
  const manifolds = new THREE.Group(); manifolds.visible = false;
  const runner = (x, side, col) => {
    const a = new THREE.Vector3(x, headY + 0.02, side * 0.03), b = new THREE.Vector3(x, headY + 0.06, side * 0.08), c = new THREE.Vector3(x, headY + 0.03, side * 0.14);
    const t = M(new THREE.TubeGeometry(new THREE.CatmullRomCurve3([a, b, c]), 16, 0.013, 10), emat(col, 0.3, 0.5));
    t.userData.sys = side < 0 ? 'air' : 'exhaust'; manifolds.add(t);
  };
  EG.cx.forEach(x => { runner(x, -1, 0x3b6fb0); runner(x, 1, 0x9a4a2a); });
  const rail = M(new THREE.CylinderGeometry(0.016, 0.016, halfX * 2, seg), emat(0x3b6fb0, 0.3, 0.5)); rail.rotation.z = Math.PI / 2; rail.position.set(0, headY + 0.08, -0.14); rail.userData.sys = 'air'; manifolds.add(rail);
  const coll = M(new THREE.CylinderGeometry(0.02, 0.02, halfX * 1.6, seg), emat(0x9a4a2a, 0.3, 0.5)); coll.rotation.z = Math.PI / 2; coll.position.set(0, headY - 0.01, 0.16); coll.userData.sys = 'exhaust'; manifolds.add(coll);
  G.add(manifolds);

  const sysTag = { air: [], fuel: [], spark: [], exhaust: [], cooling: [], oil: [] };
  R.valves.forEach(v => sysTag[v.kind === 'in' ? 'air' : 'exhaust'].push(v.g));
  R.plugs.forEach(p => sysTag.spark.push(p));
  sysTag.oil.push(crank, sump); R.cams.forEach(c => sysTag.oil.push(c));
  sysTag.cooling.push(block);
  manifolds.children.forEach(m => { if (m.userData.sys) sysTag[m.userData.sys].push(m); });
  sysTag.fuel = sysTag.air.slice();
  G.position.y = EG.r + EG.l + 0.09;

  const strokeOf = (cyl, theta) => {
    const phi = (((theta * 180 / Math.PI) + EG.cycle[cyl]) % 720 + 720) % 720;
    return { i: Math.floor(phi / 180), phi };
  };
  const up = new THREE.Vector3(0, 1, 0), top = new THREE.Vector3(), bot = new THREE.Vector3(), d = new THREE.Vector3();
  const setSpeed = s => { R.speed = Math.min(1, Math.max(0, s)); R.revPerSec = 0.12 + R.speed * 0.95; };
  setSpeed(R.speed);

  function update(dt = 0) {
    G.updateMatrixWorld(true);
    cut.copy(localCut).applyMatrix4(G.matrixWorld);        // the cut follows the engine wherever it is placed
    if (R.play) R.theta += dt * R.revPerSec * Math.PI * 2;
    const th = R.theta;
    R.pistons.forEach((p, i) => {
      const a = th + EG.phase[i], sinA = Math.sin(a);
      const yp = EG.r * Math.cos(a) + Math.sqrt(Math.max(1e-6, EG.l * EG.l - (EG.r * sinA) ** 2));
      const strip = R.strip * (0.10 + i * 0.015);
      p.position.set(EG.cx[i], yp + 0.03 + strip, 0);
      top.set(EG.cx[i], yp + strip, 0); bot.set(EG.cx[i], EG.r * Math.cos(a), EG.r * sinA);
      const rod = R.rods[i];
      rod.position.copy(top).add(bot).multiplyScalar(0.5);
      rod.quaternion.setFromUnitVectors(up, d.copy(bot).sub(top).normalize());
      rod.scale.y = Math.max(0.001, bot.distanceTo(top) / EG.l);
    });
    R.crank.rotation.x = th; R.crank.position.y = -R.strip * 0.16;
    R.cams.forEach(c => { c.rotation.x = th / 2; c.position.y = c.userData.y0 + R.strip * 0.14; });
    R.sprockets.forEach(s => { s.m.rotation.x = th * s.ratio; });
    R.valves.forEach(v => {
      const { phi } = strokeOf(v.cyl, th);
      let lift = 0;
      if (v.kind === 'in' && phi < 200) lift = Math.sin(Math.PI * Math.min(phi, 180) / 180);
      if (v.kind === 'ex' && phi > 520) lift = Math.sin(Math.PI * (Math.min(phi, 720) - 540) / 180);
      v.g.position.y = v.y0 - Math.max(0, lift) * 0.016 + R.strip * 0.22;
      v.g.position.z = (v.kind === 'in' ? -1 : 1) * (0.028 + R.strip * 0.05);
    });
    R.flashes.forEach((f, i) => {
      const { phi } = strokeOf(i, th);
      if (R.play && f.prev !== undefined && f.prev < 360 && (phi >= 360 || phi < f.prev)) f.k = 1;
      f.prev = phi;
      f.k = Math.max(0, f.k - dt * 6);
      f.m.opacity = f.k * 0.8;
    });
  }

  function setSystem(sys) {
    R.sys = sys || 'none';
    manifolds.visible = R.sys !== 'none';
    const on = new Set();
    for (const g of sysTag[R.sys] || []) g.traverse(o => { if (o.isMesh) on.add(o); });
    for (const mat of allMats) {
      mat.emissive.setRGB(0, 0, 0);
      mat.color.copy(mat.userData.base);
      if (R.sys !== 'none') mat.color.lerp(new THREE.Color(0x2a2c30), 0.5);
    }
    on.forEach(o => { o.material.color.copy(o.material.userData.base); o.material.emissive.set(0x2f6fe0); o.material.emissiveIntensity = 0.6; });
    return SYSTEMS.find(s => s.id === R.sys) || null;
  }

  update(0);
  return {
    group: G,
    cutPlane: cut,
    update,
    get play() { return R.play; },
    set play(v) { R.play = !!v; },
    setSpeed,                                            // 0..1
    rpm: () => Math.round((700 + R.speed * 2300) / 50) * 50,   // what the slider stands for; the motion is slowed to follow
    setStrip: t => { R.strip = Math.min(1, Math.max(0, t)); update(0); },   // 0 built .. 1 apart
    setSystem,                                           // 'air' | 'fuel' | 'spark' | 'exhaust' | 'cooling' | 'oil' | 'none'
    showManifolds: v => { manifolds.visible = !!v; },
    strokes: () => [0, 1, 2, 3].map(i => ({ cylinder: i + 1, ...STROKES[strokeOf(i, R.theta).i] })),
    crankDeg: () => ((R.theta * 180 / Math.PI) % 720 + 720) % 720,
    firingOrder: '1-3-4-2',
    parts: ENGINE_PARTS,
    dispose() { G.traverse(o => { if (o.isMesh) o.geometry.dispose(); }); allMats.forEach(m => m.dispose()); },
  };
}
