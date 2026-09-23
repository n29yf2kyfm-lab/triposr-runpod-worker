/* Strip Bay Training Simulator.
 *
 * Five jobs on a Golf Mk8 GTI. Each job is a list of STAGES; a stage stays
 * open until the trainee gets it right, and the next one is locked until then.
 * Every wrong action is recorded as a fault with the reason, so the report at
 * the end is an assessor's record, not a score.
 *
 * Jobs start on the real Golf (golf.glb.wasm) where the file has the parts,
 * then move to teaching models for what it does not contain.
 *
 * Faults are drawn at random each run (which cylinder, which part, which
 * charging fault, disc worn or not), so a trainee cannot learn the answers,
 * only the method. Numbers shown by the meter and gauges are SIMULATION values
 * and say so on screen; the workshop data governs on a real car.
 */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';

const $ = s => document.querySelector(s);
const rnd = a => a[Math.floor(Math.random() * a.length)];
const shuffle = a => { a = a.slice(); for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
const wait = ms => new Promise(r => setTimeout(r, ms));
const f1 = v => v.toFixed(1), f2 = v => v.toFixed(2);
function h(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const k in attrs) {
    if (k === 'on') for (const ev in attrs.on) e.addEventListener(ev, attrs.on[ev]);
    else if (k === 'class') e.className = attrs[k];
    else if (k === 'text') e.textContent = attrs[k];
    else if (attrs[k] != null) e.setAttribute(k, attrs[k]);
  }
  for (const c of kids.flat()) if (c != null && c !== false) e.append(c.nodeType ? c : document.createTextNode(c));
  return e;
}

/* ───────────────────────── 3D stage ───────────────────────── */
const host = $('#sim-canvas');
const tip = $('#sim-tip');
let renderer = null;
try {
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
} catch (e) { renderer = null; }
if (!renderer) { $('#sim-nogl').hidden = false; }
else {
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  host.prepend(renderer.domElement);
}
const camera = new THREE.PerspectiveCamera(35, 4 / 3, 0.01, 100);
const controls = renderer ? new OrbitControls(camera, renderer.domElement) : null;
if (controls) { controls.enableDamping = true; controls.dampingFactor = 0.08; controls.minDistance = 0.25; controls.maxDistance = 9; }
const env = renderer ? new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture : null;
if (renderer) new ResizeObserver(() => {
  const w = host.clientWidth, hh = host.clientHeight;
  if (!w || !hh) return;
  renderer.setSize(w, hh, false); camera.aspect = w / hh; camera.updateProjectionMatrix();
}).observe(host);

/* materials: fixed colours are fine inside the 3D view, which has its own lit ground */
const MS = (color, metalness, roughness, extra = {}) => new THREE.MeshStandardMaterial({ color, metalness, roughness, ...extra });
const MAT = {
  steel: MS(0xc2c6cc, 1, 0.3), darkSteel: MS(0x55595f, 0.9, 0.45), alu: MS(0xcfd2d6, 0.85, 0.42),
  black: MS(0x17181b, 0.2, 0.55), plastic: MS(0x2a2c30, 0.1, 0.6), rubber: MS(0x141416, 0, 0.92),
  copper: MS(0xc9763a, 1, 0.32), carbon: MS(0x3a3a3c, 0, 0.85), yellow: MS(0xf1c21b, 0.1, 0.5),
  redCable: MS(0xd11f24, 0.1, 0.5), blkCable: MS(0x1c1c1e, 0.1, 0.5),
  caliper: new THREE.MeshPhysicalMaterial({ color: 0xc21a1f, metalness: 0.2, roughness: 0.3, clearcoat: 1, clearcoatRoughness: 0.1 }),
  disc: MS(0x9ea3a8, 1, 0.42), friction: MS(0x6b5a4a, 0, 0.95), ceramic: MS(0xf1efe9, 0, 0.35),
  glass: MS(0xbcc6d0, 0.6, 0.35, { transparent: true, opacity: 0.16, depthWrite: false }),
  glassDark: MS(0x8a939c, 0.5, 0.4, { transparent: true, opacity: 0.2, depthWrite: false }),
  lam: MS(0x6d7278, 0.95, 0.5), white: MS(0xf5f5f7, 0, 0.4, { emissive: 0xffffff, emissiveIntensity: 0.6 }),
};
const X = g => g.rotateZ(Math.PI / 2);          // cylinder axis → X
const Z = g => g.rotateX(Math.PI / 2);          // cylinder axis → Z
const cyl = (r, l, seg = 32, r2 = r, open = false) => new THREE.CylinderGeometry(r, r2, l, seg, 1, open);
function add(parent, geo, mat, o = {}) {
  const m = new THREE.Mesh(geo, mat);
  if (o.pos) m.position.set(...o.pos);
  if (o.rot) m.rotation.set(...o.rot);
  if (o.part) m.userData.part = o.part;
  if (o.nopick) m.userData.nopick = true;
  parent.add(m); return m;
}
function group(parent, o = {}) {
  const g = new THREE.Group();
  if (o.pos) g.position.set(...o.pos);
  if (o.rot) g.rotation.set(...o.rot);
  if (o.part) g.userData.part = o.part;
  parent.add(g); return g;
}
function tube(parent, pts, r, mat, o = {}) {
  const c = new THREE.CatmullRomCurve3(pts.map(p => new THREE.Vector3(...p)), !!o.closed);
  return add(parent, new THREE.TubeGeometry(c, o.seg || 64, r, 12, !!o.closed), mat, o);
}
function annulus(ri, ro, w, seg = 64) {          // solid ring, axis Y
  const pts = [new THREE.Vector2(ri, -w / 2), new THREE.Vector2(ro, -w / 2), new THREE.Vector2(ro, w / 2), new THREE.Vector2(ri, w / 2), new THREE.Vector2(ri, -w / 2)];
  return new THREE.LatheGeometry(pts, seg);
}
function gear(parent, r, w, teeth, mat, axis = 'x', o = {}) {
  const g = group(parent, o);
  add(g, axis === 'x' ? X(cyl(r, w)) : Z(cyl(r, w)), mat);
  for (let i = 0; i < teeth; i++) {
    const a = i / teeth * Math.PI * 2, t = add(g, new THREE.BoxGeometry(axis === 'x' ? w : r * 0.28, r * 0.28, axis === 'x' ? r * 0.28 : w), mat);
    if (axis === 'x') { t.position.set(0, Math.cos(a) * r, Math.sin(a) * r); t.rotation.x = -a; }
    else { t.position.set(Math.cos(a) * r, Math.sin(a) * r, 0); t.rotation.z = a; }
  }
  return g;
}
function shadow(scene, r, y) {
  const c = document.createElement('canvas'); c.width = c.height = 128;
  const x = c.getContext('2d'), g = x.createRadialGradient(64, 64, 0, 64, 64, 64);
  g.addColorStop(0, 'rgba(0,0,0,.32)'); g.addColorStop(1, 'rgba(0,0,0,0)');
  x.fillStyle = g; x.fillRect(0, 0, 128, 128);
  const m = add(scene, new THREE.PlaneGeometry(r * 2, r * 2), new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(c), transparent: true, depthWrite: false }), { pos: [0, y, 0], rot: [-Math.PI / 2, 0, 0], nopick: true });
  return m;
}

/* tweens: tween(obj, {x:..}, seconds) -> Promise */
const tweens = [];
function tween(obj, to, dur = 0.6) {
  return new Promise(res => { const from = {}; for (const k in to) from[k] = obj[k]; tweens.push({ obj, from, to, t: 0, dur, res }); });
}
function runTweens(dt) {
  for (let i = tweens.length - 1; i >= 0; i--) {
    const w = tweens[i]; w.t += dt;
    const k = Math.min(1, w.t / w.dur), e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
    for (const p in w.to) w.obj[p] = w.from[p] + (w.to[p] - w.from[p]) * e;
    if (k >= 1) { tweens.splice(i, 1); w.res(); }
  }
}
function camTo(pos, target, dur = 0.9) {
  return Promise.all([tween(camera.position, { x: pos[0], y: pos[1], z: pos[2] }, dur), tween(controls.target, { x: target[0], y: target[1], z: target[2] }, dur)]);
}

/* picking and hover labels */
const ray = new THREE.Raycaster(), ptr = new THREE.Vector2();
const shown = o => { for (; o; o = o.parent) if (!o.visible) return false; return true; };
function pickAt(ev) {
  if (!scene) return null;
  const r = renderer.domElement.getBoundingClientRect();
  ptr.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(ptr, camera);
  for (const hit of ray.intersectObjects(scene.children, true)) {
    let o = hit.object;
    if (o.userData.nopick || !shown(o)) continue;
    while (o && !o.userData.part) o = o.parent;
    if (o) return o.userData.part;
  }
  return null;
}
function showTip(ev, part) {
  const label = part && R && R.labels && R.labels[part];
  if (!label) { tip.hidden = true; renderer.domElement.style.cursor = ''; return; }
  const r = host.getBoundingClientRect();
  tip.textContent = label; tip.hidden = false;
  tip.style.left = Math.min(ev.clientX - r.left + 14, r.width - tip.offsetWidth - 8) + 'px';
  tip.style.top = Math.max(8, ev.clientY - r.top - 34) + 'px';
  renderer.domElement.style.cursor = 'pointer';
}
if (renderer) {
  let down = null;
  renderer.domElement.addEventListener('pointerdown', e => { down = [e.clientX, e.clientY]; });
  renderer.domElement.addEventListener('pointermove', e => { if (e.pointerType === 'mouse' && !e.buttons) showTip(e, pickAt(e)); });
  renderer.domElement.addEventListener('pointerleave', () => { tip.hidden = true; });
  renderer.domElement.addEventListener('pointerup', e => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 6) return;
    const part = pickAt(e); showTip(e, part);
    if (part && api && api.onPick && !api.done) api.onPick(part);
  });
}

/* ───────────────────────── the real car ─────────────────────────
 * golf.glb.wasm is the Strip Bay app's own Golf Mk8 GTI, copied server-side
 * from that artifact. The part rules, hinge points and the ".glb.wasm" trick
 * are taken from platform/trainer/golf-bay.html, where every one of them was
 * measured off this exact file. Frame: +X is the car's LEFT, +Y up, +Z the
 * nose, ground at Y=0. The file has NO engine, battery or ancillaries, so the
 * real car is used for what it genuinely contains (bonnet, doors, wheels,
 * brake discs and calipers, cabin) and the component jobs switch to teaching
 * models for the rest, saying so on screen. */
const gltf = new GLTFLoader(); gltf.setMeshoptDecoder(MeshoptDecoder);
const GOLF_RULES = [
  [/^Panel_Bonnet/, 'panel_bonnet'],
  // the mirror is its own part in the app; here it rides on the door it is bolted to
  [/^Asm_Mirror_FL|^Ext_Door_FL_|^Int_Door_FL_|^Ext_Door_Limiter_FL/, 'door_fl'],
  [/^Ext_Door_FR_|^Int_Door_FR_|^Ext_Door_Limiter_FR/, 'door_fr'],
  [/^Ext_Door_RL_|^Int_Door_RL_|^Ext_Door_Limiter_RL/, 'door_rl'],
  [/^Ext_Door_RR_|^Int_Door_RR_|^Ext_Door_Limiter_RR/, 'door_rr'],
  [/^Ext_Trunk_Lid|^Int_Trunk_Lid/, 'tailgate'],
  [/^Rim_FL|^Tire_FL/, 'wheel_fl'], [/^Rim_FR|^Tire_FR/, 'wheel_fr'],
  [/^Rim_RL|^Tire_RL/, 'wheel_rl'], [/^Rim_RR|^Tire_RR/, 'wheel_rr'],
  [/^Ext_Brake_FL_Rotor/, 'rotor_fl'], [/^Ext_Brake_FR_Rotor/, 'rotor_fr'],
  [/^Ext_Brake_FL_Caliper/, 'caliper_fl'], [/^Ext_Brake_FR/, 'caliper_fr'],
  [/^Int_Airbag/, 'airbags'], [/^Int_Seats|^seat_/, 'seats'], [/^Int_SW/, 'steering'],
  [/^Ext_Window|^Int_Window|^Int_Body_Window|^Ext_Body_Window|^Int_Glass_Clear|^Ext_Sunroof/, 'glazing'],
  [/^Int_/, 'cabin'], [/./, 'body']];
// three.js DELETES the colon from "G:Ext_…" (sanitizeNodeName), so test all three spellings
function classifyGolf(n) {
  const c = [n]; if (n.startsWith('G:')) c.push(n.slice(2)); if (/^G[A-Z]/.test(n)) c.push(n.slice(1));
  for (const [re, id] of GOLF_RULES) for (const x of c) if (re.test(x)) return id;
  return 'body';
}
const GOLF_HINGE = { door_fl: [0.772, 0, 0.870], door_fr: [-0.772, 0, 0.870], door_rl: [0.754, 0, -0.209], door_rr: [-0.754, 0, -0.209],
  tailgate: [0, 1.394, -1.472], panel_bonnet: [0, 0.975, 1.115] };
const BONNET_OPEN = 52 * Math.PI / 180, DOOR_OPEN = 64 * Math.PI / 180;
let carP = null, CAR = null;
function loadCar() {
  if (!carP) carP = new Promise((res, rej) => gltf.load('golf.glb.wasm', g => { CAR = buildGolf(g.scene); res(CAR); }, undefined, rej));
  return carP;
}
function buildGolf(root) {
  const sc = new THREE.Scene(); sc.environment = env;
  const key = new THREE.DirectionalLight(0xffffff, 1.4); key.position.set(3, 5, 4); sc.add(key);
  sc.add(new THREE.HemisphereLight(0xffffff, 0x3a3a44, 0.5));
  shadow(sc, 3.4, 0.002).scale.set(0.75, 1.3, 1);
  const car = new THREE.Group(); sc.add(car); car.add(root); car.updateMatrixWorld(true);
  const by = {};
  root.traverse(o => { if (o.isMesh) (by[classifyGolf(o.name || (o.parent && o.parent.name) || '')] ||= []).push(o); });
  const parts = {};
  for (const id in by) {
    const box = new THREE.Box3(); by[id].forEach(m => box.expandByObject(m));
    const c = box.getCenter(new THREE.Vector3());
    const pv = GOLF_HINGE[id] ? new THREE.Vector3(...GOLF_HINGE[id]) : c;
    const g = new THREE.Group(); g.position.copy(pv); car.add(g); g.updateMatrixWorld(true);
    by[id].forEach(m => g.attach(m));
    g.userData.part = id;
    parts[id] = { group: g, home: pv.clone(), centre: c };
  }
  // axle stand, placed under the front-left sill; hidden until the job puts it there
  const stand = group(car, { pos: [0.72, 0, 0.95], part: 'stand' });
  add(stand, cyl(0.03, 0.09, 24, 0.09), MAT.darkSteel, { pos: [0, 0.045, 0] });
  add(stand, cyl(0.018, 0.2), MAT.yellow, { pos: [0, 0.18, 0] });
  add(stand, new THREE.BoxGeometry(0.07, 0.025, 0.05), MAT.darkSteel, { pos: [0, 0.29, 0] });
  stand.visible = false;
  const labels = { panel_bonnet: 'Bonnet', door_fl: 'Driver’s door (front left: this car is left-hand drive)', door_fr: 'Front passenger door',
    door_rl: 'Rear door', door_rr: 'Rear door', tailgate: 'Tailgate', wheel_fl: 'Front-left wheel', wheel_fr: 'Front-right wheel',
    wheel_rl: 'Rear wheel', wheel_rr: 'Rear wheel', rotor_fl: 'Brake disc, front left (MIN TH stamped on the hat)', rotor_fr: 'Brake disc, front right',
    caliper_fl: 'Brake caliper, front left', caliper_fr: 'Brake caliper, front right', airbags: 'Airbags', seats: 'Seats',
    steering: 'Steering wheel (driver airbag in the hub)', glazing: 'Glass', cabin: 'Cabin trim', body: 'Body shell', stand: 'Axle stand' };
  return {
    scene: sc, parts, car, stand, labels, update() {},
    reset() {
      for (const id in parts) { parts[id].group.position.copy(parts[id].home); parts[id].group.rotation.set(0, 0, 0); }
      car.position.set(0, 0, 0); stand.visible = false;
    },
  };
}
const carPart = id => CAR && CAR.parts[id] ? CAR.parts[id].group : null;

/* ───────────────────────── stage engine ───────────────────────── */
const PROG = 'sb-sim-progress';
const loadProg = () => { try { return JSON.parse(localStorage.getItem(PROG) || '{}'); } catch (e) { return {}; } };
const saveProg = p => { try { localStorage.setItem(PROG, JSON.stringify(p)); } catch (e) { /* private window: progress simply isn't kept */ } };

let scene = null, job = null, R = null, run = null, api = null, ticks = [];
const panel = $('#sim-panel');

function openJob(id) {
  const def = JOBS.find(j => j.id === id);
  if (!def) { location.hash = '#sim'; return; }
  tweens.length = 0; ticks = [];
  job = def;
  run = { idx: 0, faults: 0, log: [], t0: Date.now(), st: def.init() };
  if (renderer) {
    scene = new THREE.Scene(); scene.environment = env;
    const key = new THREE.DirectionalLight(0xffffff, 1.5); key.position.set(2, 3, 2.5); scene.add(key);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x3a3a44, 0.55));
    R = def.build(scene, run.st);
    run.jobScene = scene; run.jobR = R; run.view = null;
    if (CAR) CAR.reset();
  } else { R = { labels: {}, update() {} }; run.jobR = R; }
  $('#sim-kind').textContent = def.kind; $('#sim-title').textContent = def.title;
  renderStage();
}

function renderStepper() {
  const ol = $('#sim-steps'); ol.textContent = '';
  job.stages.forEach((s, i) => {
    const state = i < run.idx ? 'done' : i === run.idx ? 'now' : 'locked';
    ol.append(h('li', { class: state, 'aria-current': state === 'now' ? 'step' : null },
      h('span', { class: 'dot' }, state === 'done' ? '✓' : String(i + 1)), h('span', {}, s.title),
      state === 'locked' ? h('span', { class: 'lock', 'aria-label': 'locked' }) : null));
  });
}

function renderStage() {
  renderStepper();
  panel.textContent = ''; ticks = [];
  const s = job.stages[run.idx];
  // real-car stages run on the Golf itself; everything else on the job's teaching model
  if (s.car && renderer && !run.noCar) {
    if (!CAR) {
      const me = run;
      panel.append(h('p', { class: 'small' }, 'Loading the real Golf (6.5 MB)…'));
      loadCar().then(() => { if (run === me) renderStage(); }, () => { me.noCar = true; if (run === me) renderStage(); });
      return;
    }
    if (run.view !== 'car') { CAR.reset(); scene = CAR.scene; R = CAR; run.view = 'car'; camera.position.set(...s.car.cam[0]); controls.target.set(...s.car.cam[1]); controls.update(); }
  } else if (renderer && run.view !== 'job') {
    scene = run.jobScene; R = run.jobR; run.view = 'job';
    camera.position.set(...job.cam.pos); controls.target.set(...job.cam.target); controls.update();
  }
  const head = h('div', { class: 'ph' }, h('span', {}, `Stage ${run.idx + 1} of ${job.stages.length}`), h('span', { class: 'fc', id: 'sim-fc' }, faultText()));
  const body = h('div', { class: 'pb' });
  const fb = h('div', { class: 'fb', role: 'status', 'aria-live': 'polite' });
  const foot = h('div', { class: 'pf' });
  panel.append(head, h('h2', {}, s.title), body, fb, foot);
  api = makeApi(fb, foot);
  if (s.car && run.noCar) body.append(h('p', { class: 'small' }, 'The real car could not load, so this stage runs without it. The steps are the same.'));
  s.render(body, api);
}
const faultText = () => run.faults ? `${run.faults} not accepted` : 'No faults';

function makeApi(fb, foot) {
  const a = {
    st: run.st, R, C: CAR, done: false, onPick: null,
    tween, wait, camTo,
    tick(fn) { ticks.push(fn); },
    say(kind, title, msg) {
      fb.className = 'fb ' + kind; fb.textContent = '';
      fb.append(h('b', {}, title), msg ? h('span', {}, ' ' + msg) : null);
    },
    info(msg) { a.say('info', '', msg); },
    clear() { fb.className = 'fb'; fb.textContent = ''; },
    fail(msg) {
      run.faults++; run.log.push({ stage: job.stages[run.idx].title, msg });
      a.say('bad', 'Not accepted.', msg);
      const fc = $('#sim-fc'); if (fc) fc.textContent = faultText();
    },
    pass(msg) {
      if (a.done) return; a.done = true;
      a.say('ok', 'Accepted.', msg || '');
      const last = run.idx === job.stages.length - 1;
      foot.append(h('button', { class: 'btn', type: 'button', on: { click: () => { run.idx++; last ? report() : renderStage(); } } }, last ? 'Finish job' : 'Next stage'));
      foot.querySelector('button').focus({ preventScroll: true });
    },
  };
  return a;
}

function report() {
  const secs = Math.round((Date.now() - run.t0) / 1000);
  const prog = loadProg(), prev = prog[job.id];
  prog[job.id] = { done: true, best: prev && prev.done ? Math.min(prev.best, run.faults) : run.faults, runs: (prev ? prev.runs || 0 : 0) + 1 };
  saveProg(prog);
  renderStepper();
  panel.textContent = ''; ticks = []; api = { done: true };
  panel.append(h('div', { class: 'ph' }, h('span', {}, 'Job complete'), h('span', {}, `${Math.floor(secs / 60)} min ${secs % 60} s`)),
    h('h2', {}, run.faults ? 'Signed off, with faults recorded' : 'Signed off. Clean run.'),
    h('p', {}, run.faults
      ? `${run.faults} action${run.faults > 1 ? 's were' : ' was'} not accepted. Each one is something that would have cost time, a part or an injury on a real car.`
      : 'Every stage right first time.'));
  if (run.log.length) panel.append(h('ol', { class: 'log' }, run.log.map(l => h('li', {}, h('b', {}, l.stage + ': '), l.msg))));
  panel.append(h('div', { class: 'pf' },
    h('button', { class: 'btn', type: 'button', on: { click: () => openJob(job.id) } }, 'Run again, new fault'),
    h('a', { class: 'btn ghost', href: '#sim' }, 'All simulations')));
}

/* ── stage factories ── */
// quiz: one question, one right answer; `demo` adds controls above; `need` gates the answer
function quiz({ title, lead, demo, q, opts, need, needMsg }) {
  return { title, render(b, a) {
    if (lead) b.append(h('p', {}, lead));
    if (demo) demo(b, a);
    b.append(h('p', { class: 'q' }, q));
    const box = h('div', { class: 'opts' }); b.append(box);
    shuffle(opts).forEach(o => {
      const bt = h('button', { class: 'opt', type: 'button' }, o.t);
      bt.addEventListener('click', () => {
        if (a.done) return;
        if (need && !need(a)) return a.fail(needMsg);
        if (o.ok) { bt.classList.add('ok'); a.pass(o.why); } else { bt.classList.add('no'); a.fail(o.why); }
      });
      box.append(bt);
    });
  } };
}
// order: steps must be done in sequence (steps sharing `g` may be done in any order
// among themselves). `early` is the consequence shown when a step is taken too soon,
// `traps` are plausible wrong actions, `pick` lets a 3D part stand in for the button.
function order({ title, lead, steps, traps = [], done: doneMsg, intro, car }) {
  return { title, car, render(b, a) {
    if (lead) b.append(h('p', {}, lead));
    if (intro) intro(b, a);
    const list = h('ol', { class: 'ticks' });
    const box = h('div', { class: 'opts' });
    b.append(h('p', { class: 'q' }, 'Choose the next action.'), box, h('p', { class: 'sub' }, 'Done'), list);
    const done = steps.map(() => false); let busy = false;
    const items = shuffle([...steps.map((s, i) => ({ s, i })), ...traps.map(t => ({ trap: t }))]);
    const btn = new Map();
    items.forEach(it => { const bt = h('button', { class: 'opt', type: 'button' }, it.trap ? it.trap.t : it.s.t); bt.addEventListener('click', () => act(it)); btn.set(it, bt); box.append(bt); });
    async function act(it) {
      if (a.done) return;
      if (busy) return a.info('Wait for the current action to finish.');
      if (it.trap) { btn.get(it).remove(); return a.fail(it.trap.why); }
      const { s, i } = it;
      for (let j = 0; j < i; j++) if (!done[j] && !(s.g && steps[j].g === s.g)) return a.fail(s.early || 'Out of order. Something has to happen before this step.');
      busy = a.busy = true; done[i] = true; btn.get(it).remove();
      list.append(h('li', {}, s.t)); a.clear();
      if (s.note) a.info(s.note);
      if (s.anim) await s.anim(a);
      busy = a.busy = false;
      if (done.every(Boolean)) a.pass(doneMsg);
    }
    a.onPick = part => {
      const it = items.find(x => x.s && !done[x.i] && x.s.pick === part)
        || items.find(x => x.trap && x.trap.pick === part && btn.get(x).isConnected);
      if (it) act(it);
    };
  } };
}
// simple meter readout widget
function meterBox() {
  const val = h('div', { class: 'mval' }, '—'), cap = h('div', { class: 'mcap' }, 'Choose a test point');
  return { el: h('div', { class: 'meter' }, val, cap), set(v, c) { val.textContent = v; cap.textContent = c; } };
}
const sim = t => h('span', { class: 'simtag' }, t || 'simulation value');

/* ── real-car stages shared by several jobs ── */
function bonnetStage(after) {
  return order({
    title: 'Bonnet up', car: { cam: [[2.4, 1.75, 3.9], [0, 0.72, 1.05]] },
    lead: 'This is the real Golf. Get the bonnet up and held before anything else.',
    steps: [
      { t: 'Pull the bonnet release inside the car' },
      { t: 'Release the safety catch at the front of the bonnet', pick: 'panel_bonnet' },
      { t: 'Lift it until it is held open', pick: 'panel_bonnet', anim: async () => { const g = carPart('panel_bonnet'); if (g) await tween(g.rotation, { x: -BONNET_OPEN }, 0.9); } },
    ],
    traps: [{ t: 'Lean in before checking the bonnet is held', why: 'A bonnet that drops is a head injury. Check it is held by its stay or struts before you lean in.' }],
    done: 'Bonnet up and held. ' + after,
  });
}
const TEACH = 'The next stages use a teaching model of the parts: this car’s 3D file has no engine or ancillaries inside it.';

/* ───────────────────────── JOB 1: MISFIRE ───────────────────────── */
const FIRE = { 1: 0, 3: 180, 4: 360, 2: 540 };
const misfire = {
  id: 'misfire', kind: 'Engine · diagnosis', title: 'Misfire diagnosis',
  blurb: 'Find the misfiring cylinder, prove the cause before you buy a part, fix it, prove the fix.',
  cam: { pos: [1.15, 0.85, 1.2], target: [0, 0.16, 0] },
  init() {
    return { cyl: 1 + Math.floor(Math.random() * 4), cause: rnd(['coil', 'plug', 'injector']), running: false, theta: 0,
      counters: [0, 0, 0, 0], unplug: 0, swap: null, fixed: false, ev: { drop: new Set() }, shake: 0 };
  },
  build(scene, st) {
    shadow(scene, 0.9, -0.3);
    const eng = group(scene);
    const xs = [-0.27, -0.09, 0.09, 0.27];
    add(eng, new THREE.BoxGeometry(0.8, 0.44, 0.34), MAT.glassDark, { pos: [0, 0, 0], part: 'block' });
    add(eng, new THREE.BoxGeometry(0.82, 0.12, 0.36), MAT.alu, { pos: [0, 0.28, 0], part: 'head' });
    add(eng, new THREE.BoxGeometry(0.78, 0.05, 0.3), MAT.plastic, { pos: [0, 0.365, 0], part: 'camcover' });
    add(eng, X(cyl(0.028, 0.84)), MAT.steel, { pos: [0, -0.17, 0], part: 'crank' });
    add(eng, X(cyl(0.012, 0.9)), MAT.steel, { pos: [0, 0.27, 0.2], part: 'rail' });
    const L = {
      block: 'Cylinder block (cut away)', head: 'Cylinder head', camcover: 'Cam cover', crank: 'Crankshaft', rail: 'High-pressure fuel rail',
    };
    const pistons = [], rods = [], flashes = [], coils = [], plugs = [];
    xs.forEach((x, i) => {
      const n = i + 1;
      add(eng, cyl(0.072, 0.3, 32, 0.072, true), MAT.glass, { pos: [x, 0.05, 0], nopick: true });
      pistons.push(add(eng, cyl(0.068, 0.07), MAT.alu, { part: 'piston' + n }));
      rods.push(add(eng, cyl(0.011, 1), MAT.steel, { nopick: true }));
      flashes.push(add(eng, new THREE.SphereGeometry(0.05, 16, 12), new THREE.MeshBasicMaterial({ color: 0xff8a2a, transparent: true, opacity: 0.85 }), { pos: [x, 0.19, 0], nopick: true }));
      const c = group(eng, { pos: [x, 0.46, 0], part: 'coil' + n });
      add(c, cyl(0.03, 0.17), MAT.black);
      add(c, new THREE.BoxGeometry(0.07, 0.04, 0.06), MAT.plastic, { pos: [0, 0.1, 0] });
      add(c, new THREE.BoxGeometry(0.035, 0.03, 0.03), MAT.darkSteel, { pos: [0, 0.1, 0.045] });
      c.userData.home = x; coils.push(c);
      const p = group(eng, { pos: [x, 0.3, 0], part: 'plug' + n }); p.visible = false;
      add(p, cyl(0.012, 0.08), MAT.ceramic, { pos: [0, 0.03, 0] });
      add(p, cyl(0.018, 0.03, 6), MAT.steel, { pos: [0, -0.02, 0] });
      add(p, cyl(0.007, 0.04), MAT.steel, { pos: [0, -0.05, 0] });
      plugs.push(p);
      add(eng, cyl(0.013, 0.12), MAT.darkSteel, { pos: [x, 0.25, 0.17], rot: [0.5, 0, 0], part: 'inj' + n });
      L['piston' + n] = 'Piston, cylinder ' + n; L['coil' + n] = 'Ignition coil, cylinder ' + n;
      L['plug' + n] = 'Spark plug, cylinder ' + n; L['inj' + n] = 'Injector, cylinder ' + n;
    });
    const up = new THREE.Vector3(0, 1, 0), tmp = new THREE.Vector3();
    const r = 0.055, l = 0.19, cy = -0.17;
    function place(theta) {
      xs.forEach((x, i) => {
        const n = i + 1, c = ((theta - FIRE[n]) % 720 + 720) % 720, p = (c % 360) * Math.PI / 180;
        const pinY = cy + r * Math.cos(p) + Math.sqrt(l * l - r * r * Math.sin(p) ** 2);
        pistons[i].position.set(x, pinY + 0.03, 0);
        const cp = new THREE.Vector3(x, cy + r * Math.cos(p), r * Math.sin(p)), pp = new THREE.Vector3(x, pinY, 0);
        tmp.subVectors(pp, cp);
        rods[i].position.copy(cp).addScaledVector(tmp, 0.5); rods[i].scale.y = tmp.length();
        rods[i].quaternion.setFromUnitVectors(up, tmp.normalize());
      });
    }
    // which cylinder misfires right now (the fault follows a swapped part)
    const faultAt = () => st.fixed ? 0 : (st.swap && st.swap.part === st.cause ? st.swap.to : st.cyl);
    const prevC = [0, 0, 0, 0];
    place(0); flashes.forEach(f => f.visible = false);
    return {
      labels: L, coils, plugs, eng, faultAt,
      update(dt) {
        if (st.running) {
          st.theta = (st.theta + dt * 430) % 720;
          xs.forEach((x, i) => {
            const n = i + 1, c = ((st.theta - FIRE[n]) % 720 + 720) % 720;
            if (c < prevC[i]) {                         // this cylinder just reached firing TDC
              const dead = n === faultAt() || n === st.unplug;
              // the animation runs far slower than a real idle, so each visible cycle stands for several real ones
              if (dead) { st.shake += 0.028; if (n === faultAt()) st.counters[i] += 3 + Math.floor(Math.random() * 4); }
              else if (Math.random() < 0.004) st.counters[i]++;
              flashes[i].userData.t = dead ? 0 : 0.09;
            }
            prevC[i] = c;
            const t = flashes[i].userData.t || 0; flashes[i].visible = t > 0; flashes[i].userData.t = Math.max(0, t - dt);
          });
          if (st.unplug) st.shake += dt * 0.25;
        } else flashes.forEach(f => f.visible = false);
        place(st.theta);
        st.shake *= Math.pow(0.02, dt);
        eng.rotation.z = Math.sin(performance.now() / 22) * Math.min(st.shake, 0.06);
      },
    };
  },
  stages: [],
};
function engineControls(b, a, live = true) {
  const st = a.st;
  const start = h('button', { class: 'btn sm', type: 'button' }, st.running ? 'Stop engine' : 'Start engine');
  start.addEventListener('click', () => { st.running = !st.running; start.textContent = st.running ? 'Stop engine' : 'Start engine'; });
  const row = h('div', { class: 'row' }, start);
  b.append(row);
  if (!live) return row;
  const grid = h('div', { class: 'counters' });
  const cells = [1, 2, 3, 4].map(n => { const v = h('b', {}, '0'); grid.append(h('div', {}, h('span', {}, 'Cyl ' + n), v)); return v; });
  const liveBtn = h('button', { class: 'btn sm ghost2', type: 'button' }, 'Live data: misfire counters');
  liveBtn.addEventListener('click', () => { grid.hidden = false; liveBtn.remove(); st.ev.live = true; });
  grid.hidden = !st.ev.live; if (st.ev.live) liveBtn.remove();
  row.append(liveBtn); b.append(grid);
  a.tick(() => cells.forEach((c, i) => { c.textContent = st.counters[i]; c.parentNode.classList.toggle('hot', st.counters[i] >= 3); }));
  return row;
}
misfire.stages = [
  bonnetStage(TEACH),
  quiz({
    title: 'Find the cylinder',
    lead: 'Job card: "It shakes at idle and the engine light flashes when I pull away." Connect the scan tool, then find which cylinder is not firing.',
    demo(b, a) {
      const st = a.st;
      const codes = h('div', { class: 'codes', hidden: '' }, h('div', {}, h('b', {}, 'P0300'), ' Random/multiple cylinder misfire detected'), h('div', { class: 'muted' }, 'No cylinder-specific code stored. You will have to find it.'));
      const scan = h('button', { class: 'btn sm ghost2', type: 'button', on: { click: () => { codes.hidden = false; scan.remove(); } } }, 'Read fault codes');
      const row = engineControls(b, a); row.prepend(scan); b.append(codes);
      b.append(h('p', { class: 'small' }, 'Two ways to find it: watch the misfire counters with the engine running, or tap each coil in the 3D view to unplug it for a moment. Unplugging a working cylinder makes the engine rougher; unplugging the dead one changes nothing. Keep it brief: unburnt fuel goes to the catalyst.'));
      a.onPick = async part => {
        const m = /^coil(\d)$/.exec(part); if (!m) return;
        if (!st.running) return a.info('Start the engine first. A drop test only tells you something with the engine running.');
        const n = +m[1]; if (st.unplug) return;
        st.unplug = n; st.ev.drop.add(n);
        const c = a.R.coils[n - 1]; await tween(c.position, { y: 0.5 }, 0.2);
        a.info(n === a.R.faultAt()
          ? `Coil ${n} unplugged: no change in the engine note. This cylinder was not doing any work.`
          : `Coil ${n} unplugged: the engine note drops and it shakes harder. This cylinder was working.`);
        await wait(2200); st.unplug = 0; await tween(c.position, { y: 0.46 }, 0.2);
      };
    },
    q: 'Which cylinder is misfiring?',
    opts: [1, 2, 3, 4].map(n => ({ t: 'Cylinder ' + n, n })),
    need: a => a.st.ev.live && a.st.counters.some(v => v >= 3) || a.st.ev.drop.size >= 2,
    needMsg: 'No evidence yet. Run the engine and read the counters, or drop-test the coils, before you name a cylinder.',
  }),
];
// the answer depends on the random fault, so patch the options at render time
{
  const q = misfire.stages[1], render = q.render;
  q.render = (b, a) => {
    render(b, a);
    [...b.querySelectorAll('.opts .opt')].forEach(bt => {
      const n = +bt.textContent.slice(-1);
      const fresh = bt.cloneNode(true); bt.replaceWith(fresh);
      fresh.addEventListener('click', () => {
        if (a.done) return;
        const st = a.st;
        if (!(st.ev.live && st.counters.some(v => v >= 3)) && st.ev.drop.size < 2) return a.fail('No evidence yet. Run the engine and read the counters, or drop-test the coils, before you name a cylinder.');
        if (n === st.cyl) { fresh.classList.add('ok'); st.running = false; a.pass(`Cylinder ${n} is the dead one. Now find out why, without guessing.`); }
        else { fresh.classList.add('no'); a.fail(`Cylinder ${n} is firing. Its counter is not climbing, and unplugging its coil makes the engine worse.`); }
      });
    });
  };
}
misfire.stages.push({
  title: 'Prove the cause',
  render(b, a) {
    const st = a.st, F = st.cyl, R = a.R;
    b.append(h('p', {}, `Cylinder ${F} is misfiring. Swap the cheap parts to another cylinder and see whether the misfire follows. Do not replace anything yet.`));
    engineControls(b, a);
    const others = [1, 2, 3, 4].filter(n => n !== F);
    const sel = h('select', { 'aria-label': 'Swap to cylinder' }, others.map(n => h('option', { value: n }, 'cylinder ' + n)));
    const tests = h('div', { class: 'opts' });
    b.append(h('p', { class: 'q' }, 'Tests'), h('div', { class: 'row' }, h('span', { class: 'small' }, 'Swap with'), sel), tests);
    let busy = false;
    async function swap(part) {
      const to = +sel.value;
      st.running = false; st.swap = null; st.counters = [0, 0, 0, 0];
      const A = R.coils[F - 1], B = R.coils[to - 1];
      await Promise.all([tween(A.position, { y: 0.62 }, 0.35), tween(B.position, { y: 0.62 }, 0.35)]);
      if (part === 'plug') { R.plugs[F - 1].visible = R.plugs[to - 1].visible = true; await Promise.all([tween(R.plugs[F - 1].position, { y: 0.52 }, 0.3), tween(R.plugs[to - 1].position, { y: 0.52 }, 0.3)]); await Promise.all([tween(R.plugs[F - 1].position, { x: B.userData.home }, 0.5), tween(R.plugs[to - 1].position, { x: A.userData.home }, 0.5)]); await Promise.all([tween(R.plugs[F - 1].position, { y: 0.3 }, 0.3), tween(R.plugs[to - 1].position, { y: 0.3 }, 0.3)]); R.plugs[F - 1].visible = R.plugs[to - 1].visible = false; R.plugs[F - 1].position.x = A.userData.home; R.plugs[to - 1].position.x = B.userData.home; }
      else await Promise.all([tween(A.position, { x: B.userData.home }, 0.5), tween(B.position, { x: A.userData.home }, 0.5)]);
      await Promise.all([tween(A.position, { y: 0.46 }, 0.3), tween(B.position, { y: 0.46 }, 0.3)]);
      st.swap = { part, to };
      st.running = true; a.info(`${part === 'coil' ? 'Coils' : 'Plugs'} ${F} and ${to} swapped. Engine running: watch the counters.`);
      await wait(2600);
      const moved = part === st.cause;
      st.ev[part + 'Swap'] = true; st.ev[part + 'Moved'] = moved;
      a.info(moved ? `The misfire moved to cylinder ${to}. It followed the ${part}.` : `The misfire stayed on cylinder ${F}. It did not follow the ${part}.`);
      st.running = false; st.swap = null;
      // swap back so the car is as found
      if (part === 'coil') { A.position.x = A.userData.home; B.position.x = B.userData.home; }
      st.counters = [0, 0, 0, 0];
    }
    const T = [
      ['Swap the coil', () => swap('coil')],
      ['Swap the spark plug', () => swap('plug')],
      ['Remove and inspect the spark plug', async () => {
        const c = R.coils[F - 1], p = R.plugs[F - 1];
        await tween(c.position, { y: 0.66, z: 0.14 }, 0.4); p.visible = true; await tween(p.position, { y: 0.56 }, 0.5);
        st.ev.plugLook = true;
        a.info(st.cause === 'plug'
          ? 'Plug from cylinder ' + F + ': electrode worn to a wide gap and a carbon track down the insulator. The spark is jumping to earth instead of across the gap.'
          : 'Plug from cylinder ' + F + ': light grey-tan tip, gap looks right, no tracking. The plug looks healthy.');
        await wait(2400); await tween(p.position, { y: 0.3 }, 0.4); p.visible = false; await tween(c.position, { y: 0.46, z: 0 }, 0.4);
      }],
      ['Injector balance test (scan tool)', async () => {
        st.ev.inj = true;
        const v = [1, 2, 3, 4].map(n => n === F && st.cause === 'injector' ? 24 + Math.round(Math.random() * 6) : Math.round(Math.random() * 6 - 3));
        a.info('Per-cylinder fuel correction: ' + v.map((x, i) => `cyl ${i + 1} ${x > 0 ? '+' : ''}${x}%`).join(' · ') + (st.cause === 'injector' ? '. One cylinder is being asked for far more fuel than the rest.' : '. All four are close together.'));
      }],
      ['Compression test', async () => {
        st.ev.comp = true;
        a.info('Compression: ' + [1, 2, 3, 4].map(n => `cyl ${n} ${f1(13.2 + Math.random() * 0.6)} bar`).join(' · ') + '. All even (simulation values). The engine is mechanically sound.');
      }],
    ];
    T.forEach(([t, fn]) => tests.append(h('button', { class: 'opt', type: 'button', on: { click: async () => { if (busy || a.done) return; busy = true; await fn(); busy = false; } } }, t)));
    b.append(h('p', { class: 'q' }, 'What is causing the misfire?'));
    const ans = h('div', { class: 'opts' }); b.append(ans);
    [['coil', 'Ignition coil'], ['plug', 'Spark plug'], ['injector', 'Injector'], ['mech', 'Mechanical (compression)']].forEach(([k, t]) => ans.append(h('button', { class: 'opt', type: 'button', on: { click: e => {
      if (a.done) return;
      if (busy) return a.info('Finish the current test first.');
      const ev = st.ev;
      const proof = { coil: ev.coilMoved, plug: ev.plugMoved || (ev.plugLook && st.cause === 'plug'), injector: ev.inj && st.cause === 'injector', mech: false };
      if (k === st.cause && proof[k]) { e.target.classList.add('ok'); return a.pass(`Proved: the ${t.toLowerCase()} on cylinder ${F}. One part, bought once.`); }
      if (k === st.cause) return a.fail('Right idea, no proof. Replacing parts on a guess is how a customer pays for three parts. Test it first.');
      e.target.classList.add('no');
      const why = {
        coil: ev.coilSwap ? `When you swapped the coil, the misfire stayed on cylinder ${F}. The coil is not the cause.` : 'You have not tested the coil. Swap it and see if the misfire follows.',
        plug: ev.plugSwap || ev.plugLook ? 'The plug checked out: the misfire did not follow it and it looks healthy.' : 'You have not tested the plug.',
        injector: ev.inj ? 'The injector balance test shows all four cylinders close together.' : 'You have not tested the injector.',
        mech: ev.comp ? 'Compression is even on all four. It is not mechanical.' : 'You have not checked compression, and a cheaper test would find this first.',
      };
      a.fail(why[k]);
    } } }, t)));
  },
});
misfire.stages.push({
  title: 'Fix it',
  render(b, a) {
    const st = a.st, F = st.cyl, R = a.R;
    const lift = async () => { await tween(R.coils[F - 1].position, { y: 0.7 }, 0.4); };
    const back = async () => { await tween(R.coils[F - 1].position, { y: 0.46 }, 0.4); };
    const sets = {
      coil: { steps: [
        { t: 'Ignition off, key out of the car' },
        { t: `Unplug the coil ${F} connector: press the lock, pull the body`, pick: 'coil' + F, early: 'The ignition is still on. Switch off before unplugging anything.' },
        { t: `Pull coil ${F} straight up and out`, anim: lift },
        { t: 'Fit the new coil and push it fully home', anim: back },
        { t: 'Connector on until it clicks' },
      ], traps: [{ t: 'Pull the coil out by its wiring', why: 'That tears the connector off the loom. Pull the coil body, never the wire.' }] },
      plug: { steps: [
        { t: 'Engine cold, ignition off' },
        { t: `Remove coil ${F}`, pick: 'coil' + F, anim: lift },
        { t: 'Blow the plug well clean with air', early: 'Blow the well out first, or grit falls into the cylinder when the plug comes out.' },
        { t: 'Remove the plug with a plug socket' },
        { t: 'Check the new plug is the specified type and gap' },
        { t: 'Start it by hand, then torque to the figure in the data' },
        { t: 'Refit the coil and the connector', anim: back },
      ], traps: [
        { t: 'Remove the plug with the engine hot', why: 'Plug threads in a hot aluminium head can pull out with the plug. Let it cool.' },
        { t: 'Run the new plug in with an impact gun', why: 'Cross-threading an aluminium head is a head off. Start plugs by hand.' },
      ] },
      injector: { steps: [
        { t: 'Ignition off; relieve the fuel pressure as the data says', early: 'This is a high-pressure direct-injection system. Pressure first.' },
        { t: 'Battery negative off' },
        { t: 'Remove the high-pressure lines and the fuel rail' },
        { t: `Pull injector ${F} with the correct puller`, pick: 'inj' + F },
        { t: 'Fit a new combustion seal and O-rings' },
        { t: 'Refit injector, rail and new line fittings to the data' },
        { t: 'Battery on, prime the system, check for leaks before starting' },
      ], traps: [{ t: 'Crack a high-pressure union with the engine running to bleed it', why: 'Direct injection runs at well over 100 bar. That is an injection injury, not a bleed.' }] },
    };
    const s = sets[st.cause];
    const o = order({ title: '', lead: `Replace the faulty ${st.cause === 'plug' ? 'spark plug' : st.cause} on cylinder ${F}.`, steps: s.steps, traps: s.traps, done: 'Part replaced. It is not fixed until you prove it.' });
    o.render(b, a);
    const pass = a.pass; a.pass = m => { st.fixed = true; pass(m); };
  },
});
misfire.stages.push({
  title: 'Prove the fix',
  render(b, a) {
    const st = a.st; let cleared = false, idle = false;
    b.append(h('p', {}, 'Clear the codes, then read the counters at idle and on a road test under load.'));
    engineControls(b, a);
    const o = h('div', { class: 'opts' }); b.append(o);
    const add = (t, fn) => o.append(h('button', { class: 'opt', type: 'button', on: { click: fn } }, t));
    add('Clear fault codes and counters', () => { if (a.done) return; cleared = true; st.counters = [0, 0, 0, 0]; a.info('Codes and counters cleared.'); });
    add('Run at idle for two minutes, read the counters', async () => {
      if (a.done) return;
      if (!cleared) return a.fail('The old codes are still stored. Clear them first, or you cannot tell a new misfire from the old one.');
      st.ev.live = true; st.running = true; await wait(1800); idle = true;
      a.info('Idle: every counter at zero. Smooth.');
    });
    add('Road test under load, read the counters', async () => {
      if (a.done) return;
      if (!idle) return a.fail('Check it at idle first, in the workshop.');
      st.running = true; await wait(1500);
      a.pass('Under load: every counter at zero, no codes returned. Fixed and proved.');
    });
  },
});

/* ───────────────────────── JOB 2: STARTER ───────────────────────── */
const starter = {
  id: 'starter', kind: 'Electrical · diagnosis and removal', title: 'Starter motor',
  blurb: 'See how it engages, prove it is faulty with a meter, then take it off in the only safe order.',
  cam: { pos: [2.6, 1.3, 3.0], target: [-0.1, -0.2, 0] },
  init() { return { removed: false }; },
  build(scene) {
    shadow(scene, 1.8, -1.35);
    const sm = group(scene, { part: 'starter' });
    const L = {};
    add(sm, X(cyl(0.34, 0.8, 40, 0.34, true)), MAT.glass, { pos: [-0.25, 0, 0], nopick: true });
    add(sm, X(cyl(0.34, 0.04)), MAT.darkSteel, { pos: [-0.67, 0, 0], part: 'endcap' });
    for (let k = 0; k < 4; k++) { const a0 = k * Math.PI / 2 + Math.PI / 4; add(sm, X(new THREE.CylinderGeometry(0.33, 0.33, 0.6, 16, 1, true, a0 - 0.5, 1)), MAT.darkSteel, { pos: [-0.25, 0, 0], part: 'magnets' }); }
    const arm = group(sm, { pos: [-0.25, 0, 0], part: 'armature' });
    add(arm, X(cyl(0.22, 0.55)), MAT.lam);
    for (let k = 0; k < 12; k++) { const a0 = k / 12 * Math.PI * 2; add(arm, new THREE.BoxGeometry(0.56, 0.03, 0.03), MAT.copper, { pos: [0, Math.cos(a0) * 0.22, Math.sin(a0) * 0.22] }); }
    const comm = add(arm, X(cyl(0.11, 0.14)), MAT.copper, { pos: [-0.38, 0, 0], part: 'commutator' });
    add(sm, new THREE.BoxGeometry(0.07, 0.08, 0.06), MAT.carbon, { pos: [-0.63, 0.15, 0], part: 'brushes' });
    add(sm, new THREE.BoxGeometry(0.07, 0.08, 0.06), MAT.carbon, { pos: [-0.63, -0.15, 0], part: 'brushes' });
    add(sm, X(cyl(0.035, 1.55)), MAT.steel, { pos: [0.1, 0, 0], nopick: true });
    add(sm, X(cyl(0.2, 0.34, 32, 0.2, true)), MAT.glass, { pos: [0.33, 0, 0], nopick: true });
    add(sm, new THREE.BoxGeometry(0.05, 0.9, 0.5), MAT.alu, { pos: [0.18, -0.05, 0], part: 'flange' });
    const bolts = [0.3, -0.38].map((y, i) => { const b = group(sm, { pos: [0.1, y, 0.17], part: 'bolt' + (i + 1) }); add(b, X(cyl(0.022, 0.3)), MAT.steel, { pos: [0.1, 0, 0] }); add(b, X(cyl(0.045, 0.05, 6)), MAT.steel); return b; });
    const pin = gear(sm, 0.09, 0.12, 11, MAT.steel, 'x', { pos: [0.44, 0, 0], part: 'pinion' });
    add(pin, X(cyl(0.06, 0.1)), MAT.darkSteel, { pos: [-0.11, 0, 0] });
    const sol = add(sm, X(cyl(0.14, 0.52, 32, 0.14, true)), MAT.glass, { pos: [-0.12, 0.48, 0], nopick: true });
    add(sm, X(cyl(0.14, 0.03)), MAT.alu, { pos: [-0.38, 0.48, 0], part: 'solenoid' });
    const plunger = add(sm, X(cyl(0.07, 0.3)), MAT.steel, { pos: [-0.02, 0.48, 0], part: 'plunger' });
    const cdisc = add(sm, X(cyl(0.1, 0.02)), MAT.copper, { pos: [-0.3, 0.48, 0], part: 'contact' });
    const lever = group(sm, { pos: [0.3, 0.26, 0], part: 'lever' });
    add(lever, new THREE.BoxGeometry(0.03, 0.46, 0.08), MAT.darkSteel);
    const t30 = group(sm, { pos: [-0.44, 0.56, 0.08], part: 't30' });
    add(t30, X(cyl(0.03, 0.14)), MAT.copper);
    const t30cable = tube(t30, [[-0.05, 0, 0], [-0.3, 0.05, 0], [-0.7, 0.3, -0.2], [-1.3, 0.5, -0.5]], 0.035, MAT.redCable);
    const t50 = group(sm, { pos: [-0.44, 0.4, 0.1], part: 't50' });
    add(t50, new THREE.BoxGeometry(0.08, 0.05, 0.05), MAT.plastic);
    tube(t50, [[-0.04, 0, 0], [-0.3, -0.05, 0.1], [-0.8, 0.2, 0.2]], 0.012, MAT.blkCable);
    // flywheel ring gear behind the bellhousing face
    const ring = group(scene, { pos: [0.64, -1.19, 0], part: 'ring' });
    add(ring, X(annulus(0.9, 1.08, 0.12)), MAT.darkSteel);
    for (let k = 0; k < 96; k++) { const a0 = k / 96 * Math.PI * 2; const t = add(ring, new THREE.BoxGeometry(0.12, 0.05, 0.035), MAT.steel, { pos: [0, Math.cos(a0) * 1.1, Math.sin(a0) * 1.1] }); t.rotation.x = -a0; }
    add(scene, new THREE.BoxGeometry(0.04, 2.6, 2.4), MAT.glass, { pos: [0.2, -0.6, 0], nopick: true });
    // battery
    const bat = group(scene, { pos: [-1.6, 0.4, -0.7] });
    add(bat, new THREE.BoxGeometry(0.7, 0.5, 0.4), MAT.black, { part: 'battery' });
    const neg = add(bat, cyl(0.04, 0.08), MAT.darkSteel, { pos: [-0.22, 0.29, 0], part: 'batneg' });
    add(bat, cyl(0.04, 0.08), MAT.copper, { pos: [0.22, 0.29, 0], part: 'batpos' });
    tube(bat, [[-0.22, 0.33, 0], [-0.3, 0.6, 0], [-0.6, 0.5, 0.3], [-0.7, -0.3, 0.4]], 0.025, MAT.blkCable, { part: 'batneg' });
    Object.assign(L, {
      endcap: 'Commutator end cap', magnets: 'Field magnets', armature: 'Armature', commutator: 'Commutator', brushes: 'Carbon brushes',
      flange: 'Mounting flange', bolt1: 'Flange bolt, upper', bolt2: 'Flange bolt, lower', pinion: 'Pinion and one-way clutch',
      solenoid: 'Solenoid', plunger: 'Solenoid plunger', contact: 'Main contact disc', lever: 'Shift lever',
      t30: 'Terminal 30: main feed, always live', t50: 'Terminal 50: start trigger', ring: 'Flywheel ring gear',
      battery: 'Battery', batneg: 'Battery negative', batpos: 'Battery positive', starter: 'Starter motor',
    });
    let spin = 0;
    const R = {
      labels: L, sm, bolts, t30, t50, neg,
      async key(works) {
        await Promise.all([tween(plunger.position, { x: -0.12 }, 0.18), tween(cdisc.position, { x: -0.4 }, 0.18), tween(lever.rotation, { z: 0.55 }, 0.18), tween(pin.position, { x: 0.58 }, 0.18)]);
        if (works) { cdisc.material = MAT.white; spin = 1; await wait(1800); spin = 0; cdisc.material = MAT.copper; }
        else await wait(700);
        await Promise.all([tween(plunger.position, { x: -0.02 }, 0.2), tween(cdisc.position, { x: -0.3 }, 0.2), tween(lever.rotation, { z: 0 }, 0.2), tween(pin.position, { x: 0.44 }, 0.2)]);
      },
      update(dt) { if (spin) { arm.rotation.x += dt * 26; pin.rotation.x += dt * 26; ring.rotation.x -= dt * 26 * 0.09 / 1.1; } },
    };
    return R;
  },
  stages: [
    bonnetStage('The starter sits low at the joint between engine and gearbox. ' + TEACH),
    quiz({
      title: 'How it engages',
      lead: 'Turn the key and watch. The solenoid does two jobs at once: it throws the pinion into the flywheel ring gear, and it closes the heavy contacts that feed the motor.',
      demo(b, a) {
        b.append(h('div', { class: 'row' }, h('button', { class: 'btn sm', type: 'button', on: { click: async e => { e.target.disabled = true; a.st.saw = true; await a.R.key(true); e.target.disabled = false; } } }, 'Turn key to START')));
      },
      need: a => a.st.saw, needMsg: 'Turn the key and watch it work first.',
      q: 'What pushes the pinion into mesh with the ring gear?',
      opts: [
        { t: 'The solenoid plunger, through the shift lever', ok: true, why: 'The plunger pulls in, the lever pivots and pushes the pinion forward, and only then do the main contacts close.' },
        { t: 'The motor spinning up flings it forward', why: 'That was the old inertia (Bendix) drive. On this starter the solenoid and lever move it before the motor turns.' },
        { t: 'A spring pushes it out whenever the ignition is on', why: 'The pinion stays back until you crank, or it would grind the ring gear.' },
      ],
    }),
    {
      title: 'Prove it is the starter',
      render(b, a) {
        const st = a.st;
        b.append(h('p', {}, 'Job card: "Turn the key, it clicks, nothing happens." The meter is on DC volts, with a helper holding the key at START. Take readings, then decide.'));
        const m = meterBox(); b.append(m.el);
        const pts = [
          ['Battery posts', '12.4 V', 'Barely drops while cranking: the battery is not being asked for current.', 'bat'],
          ['Terminal 30 to earth', '12.4 V', 'Full battery voltage is reaching the starter.', 't30'],
          ['Terminal 50 to earth', '11.9 V', 'The start signal is arriving.', 't50'],
          ['Starter body to battery negative', '0.05 V', 'Earth path is good: almost no voltage lost.', 'earth'],
        ];
        st.seen = st.seen || {};
        const o = h('div', { class: 'opts two' }); b.append(o);
        pts.forEach(([t, v, c, k]) => o.append(h('button', { class: 'opt', type: 'button', on: { click: async () => { st.seen[k] = true; m.set(v, t + ': ' + c); a.clear(); await a.R.key(false); } } }, t)));
        b.append(h('p', { class: 'small' }, 'Meter readings are simulation values. You will hear the solenoid click each time.'));
        b.append(h('p', { class: 'q' }, 'Verdict'));
        const v = h('div', { class: 'opts' }); b.append(v);
        [
          ['Battery flat: charge it', 'Twelve volts held while cranking. A flat battery would collapse under the load.'],
          ['Start signal missing: check the start circuit', 'Terminal 50 has 11.9 V. The signal is arriving.'],
          ['Bad earth: clean the earth strap', 'Only 0.05 V lost on the earth side. The earth is good.'],
          ['Starter faulty: solenoid contacts or motor', null],
        ].forEach(([t, why]) => v.append(h('button', { class: 'opt', type: 'button', on: { click: e => {
          if (a.done) return;
          if (!st.seen.t30 || !st.seen.t50) return a.fail('Not proved. Measure terminal 30 and terminal 50 while cranking before you condemn a starter.');
          if (why) { e.target.classList.add('no'); return a.fail(why); }
          e.target.classList.add('ok'); a.pass('Power in, signal in, good earth, nothing out: the fault is inside the starter. It comes off.');
        } } }, t)));
      },
    },
    order({
      title: 'Remove it safely',
      lead: 'Take the starter off. You can click parts in the 3D view or use the list.',
      steps: [
        { t: 'Look up the access route for this engine and gearbox' },
        { t: 'Battery negative off, lead secured', pick: 'batneg', anim: async a => { await tween(a.R.neg.position, { y: 0.45 }, 0.4); } },
        { t: 'Support the starter’s weight' },
        { t: 'Main cable off terminal 30, end insulated', pick: 't30', early: 'The battery is still connected. Your spanner touches the block: a dead short through the tool in your hand. It welds in place and the battery can vent.', anim: async a => { await tween(a.R.t30.position, { y: 0.8, x: -0.6 }, 0.5); } },
        { t: 'Trigger connector off terminal 50', pick: 't50', anim: async a => { await tween(a.R.t50.position, { x: -0.7, y: 0.3 }, 0.4); } },
        { t: 'Upper flange bolt out', pick: 'bolt1', g: 'b', early: 'The cables are still on. Take the bolts out first and the starter drops onto a live main cable.', anim: async a => { await tween(a.R.bolts[0].position, { x: -0.35 }, 0.4); } },
        { t: 'Lower flange bolt out', pick: 'bolt2', g: 'b', early: 'The cables are still on. Take the bolts out first and the starter drops onto a live main cable.', anim: async a => { await tween(a.R.bolts[1].position, { x: -0.35 }, 0.4); } },
        { t: 'Withdraw along its own axis', pick: 'starter', anim: async a => { await tween(a.R.sm.position, { x: -0.8 }, 0.7); await tween(a.R.sm.position, { y: -0.5 }, 0.5); } },
      ],
      traps: [
        { t: 'Battery positive off first', why: 'Undo positive first and every earthed surface your spanner touches is a short across the battery. Negative first.' },
        { t: 'Lever the starter out sideways', why: 'The nose is inside the bellhousing. It only comes out along its own axis.' },
      ],
      done: 'Starter off, battery isolated, no shorts, nothing dropped.',
    }),
    order({
      title: 'Refit and test',
      lead: 'A new starter goes in. Refit it and prove it cranks.',
      steps: [
        { t: 'Offer it up along its axis, pinion into the bellhousing', anim: async a => { await tween(a.R.sm.position, { y: 0 }, 0.5); await tween(a.R.sm.position, { x: 0 }, 0.6); } },
        { t: 'Upper flange bolt in, torqued to the data', g: 'b', pick: 'bolt1', anim: async a => { await tween(a.R.bolts[0].position, { x: 0.1 }, 0.4); } },
        { t: 'Lower flange bolt in, torqued to the data', g: 'b', pick: 'bolt2', anim: async a => { await tween(a.R.bolts[1].position, { x: 0.1 }, 0.4); } },
        { t: 'Trigger connector on terminal 50', pick: 't50', anim: async a => { await tween(a.R.t50.position, { x: -0.44, y: 0.4 }, 0.4); } },
        { t: 'Main cable on terminal 30, nut tight, boot over it', pick: 't30', anim: async a => { await tween(a.R.t30.position, { x: -0.44, y: 0.56 }, 0.5); } },
        { t: 'Battery negative on, last', pick: 'batneg', early: 'Reconnect the battery last. Until then, the main cable end is a live conductor on the loose.', anim: async a => { await tween(a.R.neg.position, { y: 0.29 }, 0.4); } },
        { t: 'Turn the key: check it cranks cleanly', anim: async a => { await a.R.key(true); } },
      ],
      traps: [{ t: 'Reconnect the battery to test the solenoid before the main cable is on', why: 'The loose main cable end is live the moment the battery goes on. One touch on the block is a short.' }],
      done: 'It cranks. Cables tight, boot on, battery last.',
    }),
  ],
};

/* ───────────────────────── JOB 3: ALTERNATOR ───────────────────────── */
const LOADS = [['Headlights', 10], ['Heater blower', 15], ['Heated rear screen', 12], ['Seat heaters', 8]];
const alternator = {
  id: 'alternator', kind: 'Electrical · diagnosis', title: 'Charging system',
  blurb: 'Load the car up, watch the alternator respond, and find a charging fault with a meter.',
  cam: { pos: [3.9, 1.5, 3.7], target: [-0.55, -0.75, -0.3] },
  init() { return { fault: rnd(['diode', 'brushes', 'cable']), fixed: false, running: false, loads: [false, false, false, false], seen: {} }; },
  build(scene, st) {
    shadow(scene, 2, -2.8);
    const L = {};
    const cutG = group(scene);   // the cutaway; swapped for the real part on request
    add(scene, X(cyl(0.045, 2.1)), MAT.steel, { pos: [-0.1, 0, 0], nopick: true });
    const pulley = group(scene, { pos: [0.88, 0, 0], part: 'pulley' });
    add(pulley, X(cyl(0.22, 0.2)), MAT.darkSteel);
    for (let k = 0; k < 5; k++) add(pulley, new THREE.TorusGeometry(0.225, 0.012, 8, 48), MAT.steel, { pos: [-0.08 + k * 0.04, 0, 0], rot: [0, Math.PI / 2, 0] });
    add(cutG, X(cyl(0.72, 0.5, 48, 0.72, true)), MAT.glass, { pos: [0.45, 0, 0], nopick: true });
    add(cutG, X(cyl(0.72, 0.45, 48, 0.72, true)), MAT.glass, { pos: [-0.45, 0, 0], nopick: true });
    add(cutG, X(annulus(0.52, 0.68, 0.36)), MAT.lam, { part: 'stator' });
    const bundles = [];
    for (let k = 0; k < 18; k++) {
      const a0 = k / 18 * Math.PI * 2;
      for (const x of [-0.22, 0.22]) {
        const m = add(cutG, new THREE.BoxGeometry(0.08, 0.1, 0.12), new THREE.MeshStandardMaterial({ color: 0xc9763a, metalness: 1, roughness: 0.35, emissive: 0xff6a10, emissiveIntensity: 0 }), { pos: [x, Math.cos(a0) * 0.55, Math.sin(a0) * 0.55], rot: [-a0, 0, 0], part: 'stator' });
        m.userData.phase = k % 3; bundles.push(m);
      }
    }
    const rotor = group(cutG, { part: 'rotor' });
    const field = add(rotor, X(cyl(0.28, 0.26)), new THREE.MeshStandardMaterial({ color: 0xc9763a, metalness: 1, roughness: 0.35, emissive: 0xff8a2a, emissiveIntensity: 0 }), { part: 'field' });
    add(rotor, X(cyl(0.46, 0.05)), MAT.darkSteel, { pos: [0.19, 0, 0] });
    add(rotor, X(cyl(0.46, 0.05)), MAT.darkSteel, { pos: [-0.19, 0, 0] });
    for (let k = 0; k < 12; k++) {
      const a0 = k / 12 * Math.PI * 2, side = k % 2 ? 1 : -1;
      add(rotor, new THREE.BoxGeometry(0.3, 0.05, 0.14), MAT.darkSteel, { pos: [side * 0.04, Math.cos(a0) * 0.44, Math.sin(a0) * 0.44], rot: [-a0, 0, side * 0.12] });
    }
    add(cutG, X(cyl(0.09, 0.05)), MAT.copper, { pos: [-0.75, 0, 0], part: 'slip' });
    add(cutG, X(cyl(0.09, 0.05)), MAT.copper, { pos: [-0.85, 0, 0], part: 'slip' });
    add(cutG, new THREE.BoxGeometry(0.05, 0.12, 0.05), MAT.carbon, { pos: [-0.75, 0.15, 0], part: 'brushes' });
    add(cutG, new THREE.BoxGeometry(0.05, 0.12, 0.05), MAT.carbon, { pos: [-0.85, 0.15, 0], part: 'brushes' });
    add(cutG, new THREE.BoxGeometry(0.3, 0.12, 0.34), MAT.plastic, { pos: [-0.8, 0.29, 0], part: 'regulator' });
    const rect = group(cutG, { pos: [-1.02, 0, 0], part: 'rectifier' });
    add(rect, X(cyl(0.6, 0.04)), MAT.darkSteel);
    for (let k = 0; k < 6; k++) { const a0 = k / 6 * Math.PI * 2 + 0.3; add(rect, X(cyl(0.05, 0.06)), MAT.steel, { pos: [-0.04, Math.cos(a0) * 0.42, Math.sin(a0) * 0.42] }); }
    const bplus = add(scene, X(cyl(0.04, 0.2)), MAT.copper, { pos: [-1.12, 0.5, 0.3], part: 'bplus' });
    tube(scene, [[-1.2, 0.5, 0.3], [-1.5, 0.85, 0.5], [-1.75, 0.7, 0.85], [-1.8, 0.38, 1.03]], 0.035, MAT.redCable, { part: 'cable' });
    const bat = group(scene, { pos: [-1.9, 0, 0.85], part: 'battery' });
    add(bat, new THREE.BoxGeometry(0.9, 0.6, 0.5), MAT.black);
    add(bat, cyl(0.05, 0.1), MAT.copper, { pos: [0.1, 0.35, 0.18] });
    add(bat, cyl(0.05, 0.1), MAT.darkSteel, { pos: [-0.3, 0.35, 0.18] });
    const crank = group(scene, { pos: [0.88, -2.2, 0], part: 'crankpulley' });
    add(crank, X(cyl(0.5, 0.2)), MAT.darkSteel);
    const belt = [];
    for (let k = 0; k <= 12; k++) { const t = Math.PI * k / 12; belt.push([0.88, Math.sin(t) * 0.235, Math.cos(t) * 0.235]); }
    for (let k = 0; k <= 12; k++) { const t = Math.PI + Math.PI * k / 12; belt.push([0.88, -2.2 + Math.sin(t) * 0.515, Math.cos(t) * 0.515]); }
    tube(scene, belt, 0.02, MAT.rubber, { closed: true, part: 'belt', seg: 120 });
    // THE REAL PART: the alternator modelled from a photograph for the Strip Bay app
    // (alt.glb.wasm). Its shaft is along Z with the cut end at -X once turned, as
    // measured in golf-bay.html; scaled to this scene's 1.44-unit case diameter.
    const real = group(scene, { part: 'realalt' }); real.visible = false;
    gltf.load('alt.glb.wasm', g => {
      const m = g.scene; m.rotation.y = -Math.PI / 2; m.updateMatrixWorld(true);
      let bb = new THREE.Box3().setFromObject(m);
      const d = Math.max(bb.max.y - bb.min.y, bb.max.z - bb.min.z);
      m.scale.setScalar(1.44 / d); m.updateMatrixWorld(true);
      bb = new THREE.Box3().setFromObject(m);
      m.position.sub(bb.getCenter(new THREE.Vector3())); m.position.x += 0.72 - (bb.max.x - bb.min.x) / 2;
      real.add(m);
    }, undefined, () => { st.noReal = true; });
    Object.assign(L, { realalt: 'The real alternator: cast housings, cooling slots, windings visible through them', pulley: 'Pulley', stator: 'Stator: output is generated here', rotor: 'Rotor: claw poles', field: 'Field winding', slip: 'Slip rings',
      brushes: 'Brushes', regulator: 'Regulator and brush holder', rectifier: 'Rectifier: six diodes', bplus: 'B+ output stud', cable: 'Main charging cable',
      battery: 'Battery', crankpulley: 'Crankshaft pulley', belt: 'Auxiliary belt' });
    let ang = 0;
    return {
      labels: L, bplus, cutG, real,
      update(dt) {
        const load = st.loads.reduce((s, on, i) => s + (on ? LOADS[i][1] : 0), 0);
        const noField = st.fault === 'brushes' && !st.fixed;
        const fld = st.running && !noField ? 0.35 + 0.65 * load / 45 : 0;
        if (st.running) { ang += dt * 14; rotor.rotation.x = ang; pulley.rotation.x = ang; crank.rotation.x = ang * 0.235 / 0.515; }
        field.material.emissiveIntensity = fld * 0.9;
        bundles.forEach(m => { m.material.emissiveIntensity = fld * Math.max(0, Math.sin(ang * 6 - m.userData.phase * 2.094)) * 1.4; });
      },
    };
  },
  stages: [],
};
function altReading(st, point, mode) {
  const load = st.loads.reduce((s, on, i) => s + (on ? LOADS[i][1] : 0), 0), loaded = load > 0;
  const j = () => (Math.random() - 0.5) * 0.02;
  if (!st.running) return mode === 'DC' ? 12.55 + j() : 0;
  const f = st.fixed ? 'none' : st.fault;
  let bat, bp, acB, acBat;
  if (f === 'none') { bat = bp = loaded ? 14.3 : 12.9; acB = 0.05; acBat = 0.02; }
  if (f === 'brushes') { bat = bp = 12.42 - load * 0.008; acB = 0.02; acBat = 0.01; }
  if (f === 'diode') { bp = loaded ? 13.5 : 12.95; bat = bp - 0.1; acB = loaded ? 1.3 : 0.35; acBat = loaded ? 0.45 : 0.12; }
  if (f === 'cable') { bp = loaded ? 14.5 : 13.0; bat = loaded ? 13.1 : 12.9; acB = 0.05; acBat = 0.02; }
  if (mode === 'DC') return (point === 'bat' ? bat : bp) + j();
  return Math.max(0, (point === 'bat' ? acBat : acB) + j() / 4);
}
function altBench(b, a, onRead) {
  const st = a.st;
  const eng = h('button', { class: 'btn sm', type: 'button' }, st.running ? 'Stop engine' : 'Start engine');
  eng.addEventListener('click', () => { st.running = !st.running; eng.textContent = st.running ? 'Stop engine' : 'Start engine'; });
  const loads = h('div', { class: 'chips' }, LOADS.map(([t, amps], i) => {
    const c = h('button', { class: 'chip', type: 'button', 'aria-pressed': String(st.loads[i]) }, `${t} · ${amps} A`);
    c.addEventListener('click', () => { st.loads[i] = !st.loads[i]; c.setAttribute('aria-pressed', String(st.loads[i])); st.touchedLoad = true; });
    return c;
  }));
  b.append(h('div', { class: 'row' }, eng), h('p', { class: 'sub' }, 'Electrical loads'), loads);
  if (!onRead) return;
  let mode = 'DC';
  const m = meterBox();
  const modes = h('div', { class: 'toggle' }, ['DC', 'AC'].map(k => { const t = h('button', { type: 'button', 'aria-pressed': String(k === mode) }, k + ' volts'); t.addEventListener('click', () => { mode = k; [...modes.children].forEach(x => x.setAttribute('aria-pressed', String(x === t))); }); return t; }));
  const probe = pt => {
    const v = altReading(st, pt, mode), load = st.loads.some(Boolean);
    m.set((mode === 'DC' ? f2(v) : f2(v)) + ' V ' + mode, `${pt === 'bat' ? 'Battery posts' : 'B+ stud to earth'} · engine ${st.running ? 'running' : 'off'} · ${load ? 'loads on' : 'no load'}`);
    onRead({ pt, mode, running: st.running, load, v });
  };
  b.append(h('p', { class: 'sub' }, 'Meter'), modes, m.el, h('div', { class: 'opts two' },
    h('button', { class: 'opt', type: 'button', on: { click: () => probe('bat') } }, 'Probe the battery posts'),
    h('button', { class: 'opt', type: 'button', on: { click: () => probe('bp') } }, 'Probe B+ stud to earth')));
  b.append(h('p', { class: 'small' }, 'You can also click the battery or the B+ stud in the 3D view. Readings are simulation values.'));
  a.onPick = part => { if (part === 'battery') probe('bat'); if (part === 'bplus') probe('bp'); };
}
alternator.stages = [
  bonnetStage(TEACH),
  quiz({
    title: 'How it makes power',
    lead: 'Start the engine and switch loads on. Watch the field winding and the stator: the regulator raises the field current as the demand rises, and the stator windings light up in three phases.',
    demo: (b, a) => {
      const view = h('div', { class: 'toggle' }, ['Cutaway', 'Real part'].map((t, i) => {
        const x = h('button', { type: 'button', 'aria-pressed': String(i === 0) }, t);
        x.addEventListener('click', () => {
          if (i === 1 && a.st.noReal) return a.info('The real alternator model could not load.');
          a.R.cutG.visible = i === 0; a.R.real.visible = i === 1;
          [...view.children].forEach(y => y.setAttribute('aria-pressed', String(y === x)));
        });
        return x;
      }));
      b.append(h('div', { class: 'row' }, h('span', { class: 'small' }, 'View'), view));
      altBench(b, a);
    },
    need: a => a.st.running && a.st.touchedLoad, needMsg: 'Run the engine and switch a load on first. Watch what the field does.',
    q: 'Where is the output current actually generated?',
    opts: [
      { t: 'In the stator windings, fixed in the housing', ok: true, why: 'The spinning field sweeps past three fixed windings. The rotor only carries the magnetism.' },
      { t: 'In the rotor, and collected by the brushes', why: 'The brushes only feed the field current in. Output comes from the stator.' },
      { t: 'In the rectifier diodes', why: 'The diodes only steer AC into DC. They do not generate anything.' },
    ],
  }),
  {
    title: 'Find the charging fault',
    render(b, a) {
      const st = a.st; st.seen = {};
      b.append(h('p', {}, 'Job card: "Battery light comes on at night and the car was flat this morning." Take your readings, then decide.'));
      altBench(b, a, r => {
        if (r.running && r.load && r.mode === 'DC') st.seen[r.pt + 'DC'] = true;
        if (r.running && r.mode === 'AC' && r.pt === 'bp') st.seen.ac = true;
        if (r.running && !r.load && r.mode === 'DC') st.seen.noload = true;
      });
      b.append(h('p', { class: 'q' }, 'Verdict'));
      const v = h('div', { class: 'opts' }); b.append(v);
      const opts = [
        ['brushes', 'No field: brushes or regulator worn'],
        ['diode', 'Rectifier diode failed'],
        ['cable', 'High resistance in the B+ cable or its connections'],
        ['battery', 'The battery is faulty: replace it'],
        ['smart', 'Nothing wrong: it is smart charging'],
      ];
      const why = {
        brushes: 'The voltage rises when the engine runs, so the field is working.',
        diode: 'The AC reading at B+ is low. The diodes are doing their job.',
        cable: 'Battery and B+ read the same. There is no voltage lost in the cable.',
        battery: 'The battery reads normally at rest. The problem only shows with the engine running.',
        smart: 'Smart charging lowers the voltage when the battery is full. It still rises to around 14 V under load, and this one does not behave like that.',
      };
      opts.forEach(([k, t]) => v.append(h('button', { class: 'opt', type: 'button', on: { click: e => {
        if (a.done) return;
        if (!st.seen.batDC || !st.seen.bpDC || !st.seen.ac) return a.fail('Not proved yet. You need, with the engine running: DC at the battery with loads on, DC at the B+ stud with loads on, and AC at the B+ stud.');
        if (k === st.fault) { e.target.classList.add('ok'); return a.pass({
          brushes: 'Running voltage sits at battery level and falls as you add load: no field, no output. Brushes or regulator.',
          diode: 'DC low under load and over a volt of AC at B+: one diode has failed and the output has a hole in it.',
          cable: 'The alternator makes about 14.5 V but the battery only sees about 13.1 V. The missing volt and a half is lost in the cable or its connections.',
        }[k]); }
        e.target.classList.add('no'); a.fail(why[k]);
      } } }, t)));
    },
  },
  {
    title: 'Repair',
    render(b, a) {
      const st = a.st;
      const sets = {
        diode: ['Battery negative off', 'Release the belt tensioner and slip the belt off', 'B+ nut and regulator connector off', 'Mounting bolts out, alternator out', 'Fit the new alternator, bolts torqued to the data', 'Regulator connector and B+ nut on', 'Belt on: check the routing and the tensioner', 'Battery negative on'],
        brushes: ['Battery negative off', 'Remove the rear cover', 'Unscrew the regulator and brush pack', 'Check the slip rings for wear and grooving', 'Fit the new regulator and brush pack', 'Cover on, battery negative on'],
        cable: ['Battery negative off', 'Undo the B+ stud and the battery end of the cable', 'Clean the terminals to bright metal, replace the cable if it is corroded inside', 'Refit and tighten both ends', 'Battery negative on'],
      };
      const o = order({
        title: '', lead: 'Make the repair your readings point to.',
        steps: sets[st.fault].map(t => ({ t, early: t.startsWith('Battery negative on') ? 'Reconnect the battery last.' : undefined })),
        traps: [
          { t: 'Disconnect the battery with the engine running to test the alternator', why: 'The old trick. On a modern car the voltage spike can destroy control units. Never.' },
          { t: st.fault === 'cable' ? 'Replace the alternator to be sure' : 'Fit a new battery to be sure', why: 'That part tested good. Replacing it spends the customer’s money and leaves the fault in the car.' },
        ],
        done: 'Repair done. Now prove it.',
      });
      o.render(b, a);
      const pass = a.pass; a.pass = m => { st.fixed = true; st.running = false; pass(m); };
    },
  },
  {
    title: 'Prove the repair',
    render(b, a) {
      const st = a.st; const seen = {};
      b.append(h('p', {}, 'Engine running with loads on: take DC at the battery and AC at the B+ stud.'));
      altBench(b, a, r => {
        if (r.running && r.load && r.mode === 'DC' && r.pt === 'bat') seen.dc = true;
        if (r.running && r.mode === 'AC' && r.pt === 'bp') seen.ac = true;
        if (seen.dc && seen.ac) a.pass('About 14.3 V at the battery under load and almost no AC at B+. Charging, and proved.');
      });
    },
  },
];

/* ───────────────────────── JOB 4: BRAKES ───────────────────────── */
const brakes = {
  id: 'brakes', kind: 'Chassis · service', title: 'Front brake pads',
  blurb: 'Wheel off, measure, caliper off, piston back, pads in, torque in a star, pedal firm.',
  cam: { pos: [0.85, 0.5, 1.0], target: [0, 0.08, 0] },
  init() { const worn = Math.random() < 0.5; return { worn, pad: f1(2 + Math.random() * 0.6), mic: [], disc: null }; },
  build(scene, st) {
    shadow(scene, 0.55, -0.34);
    const L = {};
    add(scene, Z(cyl(0.07, 0.06)), MAT.darkSteel, { pos: [0, 0, 0.0], part: 'hub' });
    const disc = group(scene, { part: 'disc' });
    add(disc, Z(annulus(0.075, 0.17, 0.009)), MAT.disc, { pos: [0, 0, 0.012] });
    add(disc, Z(annulus(0.075, 0.17, 0.009)), MAT.disc, { pos: [0, 0, -0.012] });
    for (let k = 0; k < 36; k++) { const a0 = k / 36 * Math.PI * 2; add(disc, new THREE.BoxGeometry(0.09, 0.005, 0.016), MAT.darkSteel, { pos: [Math.cos(a0) * 0.125, Math.sin(a0) * 0.125, 0], rot: [0, 0, a0] }); }
    add(disc, Z(cyl(0.085, 0.035)), MAT.disc, { pos: [0, 0, 0.03] });
    // carrier and pads (pads live in the carrier)
    add(scene, new THREE.BoxGeometry(0.2, 0.03, 0.07), MAT.darkSteel, { pos: [0, 0.2, -0.005], part: 'carrier' });
    const padIn = group(scene, { pos: [0, 0.145, -0.02], part: 'pads' });
    add(padIn, new THREE.BoxGeometry(0.12, 0.055, 0.004), MAT.darkSteel, { pos: [0, 0, -0.004] });
    const fIn = add(padIn, new THREE.BoxGeometry(0.11, 0.05, 0.004), MAT.friction, { pos: [0, 0, 0.0] });
    const padOut = group(scene, { pos: [0, 0.145, 0.02], part: 'pads' });
    add(padOut, new THREE.BoxGeometry(0.12, 0.055, 0.004), MAT.darkSteel, { pos: [0, 0, 0.004] });
    add(padOut, new THREE.BoxGeometry(0.11, 0.05, 0.004), MAT.friction, { pos: [0, 0, 0] });
    // caliper: inboard housing with piston, bridge, outboard fingers
    const cal = group(scene, { part: 'caliper' });
    add(cal, new THREE.BoxGeometry(0.17, 0.085, 0.032), MAT.caliper, { pos: [0, 0.15, -0.042] });
    add(cal, new THREE.BoxGeometry(0.15, 0.03, 0.12), MAT.caliper, { pos: [0, 0.2, -0.005] });
    add(cal, new THREE.BoxGeometry(0.14, 0.07, 0.02), MAT.caliper, { pos: [0, 0.155, 0.033] });
    const piston = add(cal, Z(cyl(0.026, 0.02)), MAT.steel, { pos: [0, 0.145, -0.021], part: 'piston' });
    const gbs = [-0.085, 0.085].map((x, i) => { const g = group(cal, { pos: [x, 0.16, -0.065], part: 'gb' + (i + 1) }); add(g, Z(cyl(0.008, 0.05)), MAT.steel, { pos: [0, 0, 0.02] }); add(g, Z(cyl(0.013, 0.012, 6)), MAT.steel); return g; });
    tube(cal, [[0, 0.19, -0.058], [0.02, 0.26, -0.1], [0.06, 0.35, -0.16], [0.08, 0.45, -0.2]], 0.006, MAT.rubber, { part: 'hose' });
    // strut spring to hang the caliper from
    const helix = []; for (let k = 0; k <= 160; k++) { const t = k / 160 * Math.PI * 2 * 5; helix.push([Math.cos(t) * 0.07 - 0.12, 0.34 + k / 160 * 0.24, Math.sin(t) * 0.07 - 0.16]); }
    tube(scene, helix, 0.008, MAT.darkSteel, { part: 'spring', seg: 400 });
    const hook = tube(scene, [[-0.07, 0.4, -0.16], [-0.07, 0.35, -0.16], [-0.05, 0.31, -0.15]], 0.003, MAT.steel, { nopick: true }); hook.visible = false;
    // wheel
    const wheel = group(scene, { pos: [0, 0, 0.075], part: 'wheel' });
    const tyre = add(wheel, new THREE.TorusGeometry(0.27, 0.06, 20, 64), MAT.rubber); tyre.scale.z = 1.6;
    add(wheel, Z(cyl(0.23, 0.19, 64, 0.23, true)), MAT.alu);
    for (let k = 0; k < 5; k++) { const a0 = k / 5 * Math.PI * 2 + Math.PI / 2; add(wheel, new THREE.BoxGeometry(0.2, 0.035, 0.02), MAT.alu, { pos: [Math.cos(a0) * 0.14, Math.sin(a0) * 0.14, 0.085], rot: [0, 0, a0] }); }
    add(wheel, Z(cyl(0.075, 0.03)), MAT.alu, { pos: [0, 0, 0.085] });
    const wb = [];
    for (let k = 0; k < 5; k++) { const a0 = Math.PI / 2 - k / 5 * Math.PI * 2; const b = group(wheel, { pos: [Math.cos(a0) * 0.056, Math.sin(a0) * 0.056, 0.1], part: 'wb' + k }); add(b, Z(cyl(0.011, 0.02, 6)), MAT.steel); wb.push(b); }
    Object.assign(L, { hub: 'Hub', disc: 'Brake disc (vented). MIN TH stamped on the hat', carrier: 'Caliper carrier (bolted to the hub)', pads: 'Brake pads', caliper: 'Caliper', piston: 'Caliper piston',
      gb1: 'Guide bolt', gb2: 'Guide bolt', hose: 'Flexible brake hose', spring: 'Road spring: hang the caliper here', wheel: 'Road wheel' });
    for (let k = 0; k < 5; k++) L['wb' + k] = 'Wheel bolt';
    wheel.position.z = 0.7; wheel.visible = false;   // the real car's wheel came off in stage 1
    return { labels: L, wheel, wb, cal, gbs, piston, padIn, padOut, fIn, disc, hook, update() {} };
  },
  stages: [],
};
const BRAKE_CAM = [[2.05, 0.62, 2.05], [0.78, 0.36, 1.3]];
brakes.stages = [
  order({
    title: 'Wheel off, safely', car: { cam: [[3.1, 1.2, 3.1], [0.5, 0.45, 1.0]] },
    lead: 'Job card: "Grinding from the front when braking." This is the real Golf on the workshop floor. Take the front-left wheel off.',
    steps: [
      { t: 'Slacken the front-left wheel bolts, car on the ground', pick: 'wheel_fl' },
      { t: 'Raise the car with the jack at the front-left lifting point', early: 'Slacken the bolts first. With the wheel in the air it just turns when you push on the bar.',
        anim: async a => { if (a.C) await tween(a.C.car.position, { y: 0.07 }, 0.9); } },
      { t: 'Axle stand under the lifting point, lower onto it', pick: 'body', anim: async a => { if (a.C) a.C.stand.visible = true; } },
      { t: 'Remove the bolts and the wheel', pick: 'wheel_fl', anim: async a => {
        const g = carPart('wheel_fl');
        if (g) await tween(g.position, { x: CAR.parts.wheel_fl.home.x + 0.85, y: CAR.parts.wheel_fl.home.y + 0.04 }, 0.9);
        if (a.C) await camTo(...BRAKE_CAM);
      } },
    ],
    traps: [{ t: 'Work with the car on the trolley jack alone', why: 'A trolley jack lifts. It never holds. Axle stands before anything comes off.' }],
    done: 'Wheel off, car on stands.',
  }),
  {
    title: 'Measure before you decide', car: { cam: BRAKE_CAM },
    render(b, a) {
      const st = a.st; st.mic = []; st.used = {};
      a.onPick = part => { if (part === 'rotor_fl') a.info('Real disc, front left. The hat is stamped MIN TH 22.0 mm (simulation value). Measure the swept face, not the rusty lip at the edge.'); };
      const minTh = 22.0;
      b.append(h('p', {}, `Pad friction material and disc thickness decide the job. The disc hat is stamped `, h('b', {}, `MIN TH ${f1(minTh)} mm`), ' ', sim(), '.'));
      const m = meterBox(); b.append(m.el);
      const base = st.worn ? 21.7 : 23.25;
      const o = h('div', { class: 'opts two' }); b.append(o);
      o.append(h('button', { class: 'opt', type: 'button', on: { click: () => { st.used.pad = true; m.set(st.pad + ' mm', 'Pad friction material, thinnest point. Service limit in this sim: 3.0 mm.'); } } }, 'Pad gauge on the inboard pad'));
      o.append(h('button', { class: 'opt', type: 'button', on: { click: () => { st.used.vern = true; m.set(f1(base + 0.8) + ' mm', 'Vernier caliper across the disc. It rests on the worn lip at the outer edge.'); } } }, 'Vernier caliper across the disc'));
      ['A', 'B', 'C'].forEach((p, i) => o.append(h('button', { class: 'opt', type: 'button', on: { click: () => { const v = base + (Math.random() - 0.5) * 0.12; st.mic[i] = v; m.set(f2(v) + ' mm', `Micrometer, point ${p}, on the swept face.`); } } }, `Micrometer at point ${p}`)));
      b.append(h('p', { class: 'q' }, 'What does this car need?'));
      const v = h('div', { class: 'opts' }); b.append(v);
      [['pads', 'New pads only'], ['both', 'New pads and discs'], ['none', 'Nothing yet: pads have life left']].forEach(([k, t]) => v.append(h('button', { class: 'opt', type: 'button', on: { click: e => {
        if (a.done) return;
        if (!st.used.pad) return a.fail('Measure the pads before you decide anything about them.');
        if (st.mic.filter(x => x != null).length < 3) return a.fail(st.used.vern ? 'The vernier reads the worn lip at the edge and gives you a thicker disc than you have. Measure the swept face with a micrometer at three points.' : 'Measure the disc with a micrometer at three points before you decide.');
        const right = st.worn ? 'both' : 'pads';
        if (k === right) { st.disc = k === 'both'; e.target.classList.add('ok'); return a.pass(st.worn ? 'The disc is under MIN TH at every point: pads and discs, both sides of the axle.' : 'Pads are under the limit, the disc is above MIN TH: new pads on both front wheels.'); }
        e.target.classList.add('no');
        a.fail(k === 'none' ? `The pads are at ${st.pad} mm, under the 3.0 mm limit.` : st.worn ? `Every micrometer reading is below MIN TH ${f1(minTh)} mm. The discs have to go.` : 'The disc is above MIN TH at every point. Replacing it spends money for nothing.');
      } } }, t)));
    },
  },
  order({
    title: 'Caliper off',
    lead: 'Get the caliper off the carrier without damaging the hose.',
    intro: (b, a) => { a.camTo([0.8, 0.55, -0.8], [-0.03, 0.17, -0.1]); b.append(h('p', { class: 'small' }, 'The view has turned to the inboard side, where the guide bolts are.')); },
    steps: [
      { t: 'Remove the upper guide bolt', g: 'gb', pick: 'gb2', anim: async a => { await tween(a.R.gbs[1].position, { z: -0.14 }, 0.4); a.R.gbs[1].visible = false; } },
      { t: 'Remove the lower guide bolt', g: 'gb', pick: 'gb1', anim: async a => { await tween(a.R.gbs[0].position, { z: -0.14 }, 0.4); a.R.gbs[0].visible = false; } },
      { t: 'Lift the caliper off the carrier', pick: 'caliper', early: 'Both guide bolts first. The caliper is still bolted to the carrier.', anim: async a => { await tween(a.R.cal.position, { y: 0.1 }, 0.5); } },
      { t: 'Hang it from the road spring with a hook', pick: 'spring', anim: async a => { await Promise.all([tween(a.R.cal.position, { x: -0.06, y: 0.16, z: -0.2 }, 0.7), tween(a.R.cal.rotation, { y: 0.9 }, 0.7)]); a.R.hook.visible = true; } },
    ],
    traps: [
      { t: 'Let it hang on the brake hose', why: 'The hose is a pressure part. Its weight damages the hose inside, where you cannot see it.' },
      { t: 'Lever the caliper off against the disc with a screwdriver', why: 'That scores the disc and chips the pad. The bolts come out and it lifts off.' },
    ],
    done: 'Caliper hung from the spring, hose slack and undamaged.',
  }),
  {
    title: 'Piston back, pads and disc',
    render(b, a) {
      const st = a.st, R = a.R;
      const pushed = async () => { await tween(R.piston.position, { z: -0.027 }, 1.1); };
      const padsOut = async () => { await Promise.all([tween(R.padIn.position, { y: 0.32 }, 0.5), tween(R.padOut.position, { y: 0.32 }, 0.5)]); };
      const padsIn = async () => { R.fIn.scale.z = 1.8; await Promise.all([tween(R.padIn.position, { y: 0.145 }, 0.5), tween(R.padOut.position, { y: 0.145 }, 0.5)]); };
      const discOff = async () => { await tween(R.disc.position, { z: 0.35 }, 0.7); };
      const discOn = async () => { await tween(R.disc.position, { z: 0 }, 0.7); };
      const steps = [
        { t: 'Check the fluid reservoir level first, rag under the cap' },
        { t: 'Push the piston straight back with a retraction tool', pick: 'piston', early: 'Check the reservoir first. Pushing the piston back sends the fluid up there, and it overflows onto the paint.', anim: pushed },
        { t: 'Remove the old pads', pick: 'pads', anim: padsOut },
      ];
      if (st.disc) steps.push(
        { t: 'Remove the carrier bolts and the carrier' },
        { t: 'Remove the disc retaining screw and the disc', pick: 'disc', anim: discOff },
        { t: 'Clean the rust off the hub face' },
        { t: 'Fit the new disc and its retaining screw', anim: discOn },
        { t: 'Carrier back on, bolts torqued to the data' });
      steps.push(
        { t: 'Clean the carrier slide points, fit new clips' },
        { t: 'Fit the new pads, grease only on the backing-plate contact points', anim: padsIn });
      order({
        title: '', lead: st.disc ? 'Pads and discs.' : 'Pads only: the disc stays.',
        steps,
        traps: [
          { t: 'Lever the piston back against the disc with a screwdriver', why: 'That damages the disc and can cock the piston in its bore. Use a retraction tool, square to the piston.' },
          { t: 'Wind the piston back clockwise with a wind-back tool', why: 'This front piston pushes straight back. Wind-back tools are for screw-type rear pistons, and this car’s rears are electric: they go back in service mode with a diagnostic tool.' },
          { t: 'Grease the friction face so the pads don’t squeal', why: 'Grease on the friction face destroys braking. Contact points only, never the friction material or the disc.' },
        ],
        done: 'New pads in, piston back, nothing on the friction faces.',
      }).render(b, a);
    },
  },
  order({
    title: 'Refit and torque',
    lead: 'Caliper back on, wheel back on.',
    intro: a0 => {},
    steps: [
      { t: 'Caliper off the hook and over the new pads', pick: 'caliper', anim: async a => { a.R.hook.visible = false; await Promise.all([tween(a.R.cal.position, { x: 0, y: 0, z: 0 }, 0.7), tween(a.R.cal.rotation, { y: 0 }, 0.7)]); } },
      { t: 'Both guide bolts in, torqued to the data', anim: async a => { a.R.gbs.forEach(g => { g.visible = true; }); await Promise.all(a.R.gbs.map(g => tween(g.position, { z: -0.065 }, 0.4))); } },
      { t: 'Wheel on, all five bolts started by hand', pick: 'wheel', early: 'The caliper is not bolted up yet.', anim: async a => { await a.camTo(brakes.cam.pos, brakes.cam.target); a.R.wheel.visible = true; await tween(a.R.wheel.position, { z: 0.075 }, 0.8); } },
    ],
    traps: [{ t: 'Run the wheel bolts in with an impact gun', why: 'Start every bolt by hand so you cannot cross-thread one. Final torque is always the torque wrench.' }],
    done: 'Wheel on, bolts started by hand.',
  }),
  {
    title: 'Torque in a star',
    render(b, a) {
      const R = a.R; let seq = [];
      b.append(h('p', {}, 'Click the five wheel bolts in the order you would torque them. Snug them in this order, lower the car, then torque in the same order.'));
      const pent = h('div', { class: 'pent' });
      const pos = [0, 1, 2, 3, 4].map(k => { const a0 = Math.PI / 2 - k / 5 * Math.PI * 2; return [50 + Math.cos(a0) * 38, 50 - Math.sin(a0) * 38]; });
      const btns = pos.map(([x, y], k) => { const bt = h('button', { type: 'button', style: `left:${x}%;top:${y}%`, 'aria-label': 'Bolt ' + (k + 1) }, ''); bt.addEventListener('click', () => hit(k)); pent.append(bt); return bt; });
      b.append(pent, h('p', { class: 'small' }, 'Or click the bolts on the wheel in the 3D view.'));
      function reset() { seq = []; btns.forEach(x => { x.textContent = ''; x.className = ''; }); R.wb.forEach(w => w.scale.set(1, 1, 1)); }
      function hit(k) {
        if (a.done || seq.includes(k)) return;
        if (seq.length >= 2) {
          const d1 = (seq[1] - seq[0] + 5) % 5, d = (k - seq[seq.length - 1] + 5) % 5;
          if (d !== d1) { a.fail('Not a star. Going round the circle pulls the wheel off-square as it seats. Start again.'); return reset(); }
        } else if (seq.length === 1) {
          const d = (k - seq[0] + 5) % 5;
          if (d === 1 || d === 4) { a.fail('That is the next bolt round. Cross the wheel: skip one each time.'); return reset(); }
        }
        seq.push(k); btns[k].textContent = seq.length; btns[k].className = 'on'; R.wb[k].scale.set(1.6, 1.6, 1.6);
        if (seq.length === 5) a.pass('Star order. Lower the car and torque them in the same star, to the figure in the data.');
      }
      a.onPick = part => { const m = /^wb(\d)$/.exec(part); if (m) hit(+m[1]); };
    },
  },
  quiz({
    title: 'Before it moves',
    lead: 'Both front wheels are done and the car is back on the ground.',
    q: 'What happens before the car moves an inch?',
    opts: [
      { t: 'Pump the pedal until it is firm, then check the fluid level', ok: true, why: 'The pistons are fully back. The first press only takes up the gap, so the first stop would have no brakes.' },
      { t: 'Drive it round the block to bed the pads in', why: 'Not until the pedal is firm. The first press only moves the pistons out to the pads.' },
      { t: 'Hand it back: the job card is complete', why: 'Pedal firm and fluid level checked first, then a road test.' },
    ],
  }),
];

/* ───────────────────────── JOB 5: AIRBAG ───────────────────────── */
const airbag = {
  id: 'airbag', kind: 'Chassis · safety-critical', title: 'Steering wheel and airbag',
  blurb: 'Isolate, wait, remove, refit. The order is a safety procedure.',
  cam: { pos: [0.7, 0.35, 1.15], target: [0.08, -0.05, 0] },
  init() { return {}; },
  build(scene) {
    shadow(scene, 0.5, -0.33);
    const L = {};
    const col = group(scene, { part: 'column' });
    add(col, Z(cyl(0.035, 0.5)), MAT.plastic, { pos: [0, 0, -0.33] });
    const clock = add(scene, Z(cyl(0.085, 0.035)), MAT.plastic, { pos: [0, 0, -0.06], part: 'clock' });
    add(scene, Z(cyl(0.02, 0.06)), MAT.steel, { pos: [0, 0, -0.02], part: 'splines' });
    const wheel = group(scene, { part: 'wheel' });
    add(wheel, new THREE.TorusGeometry(0.19, 0.021, 20, 72), MAT.black);
    [Math.PI / 2 + Math.PI, 0.15, Math.PI - 0.15].forEach(a0 => add(wheel, new THREE.BoxGeometry(0.15, 0.03, 0.02), MAT.black, { pos: [Math.cos(a0) * 0.11, Math.sin(a0) * 0.11, -0.005], rot: [0, 0, a0] }));
    add(wheel, Z(cyl(0.085, 0.04)), MAT.plastic, { pos: [0, 0, -0.01] });
    const bolt = add(wheel, Z(cyl(0.014, 0.02, 6)), MAT.steel, { pos: [0, 0, 0.018], part: 'cbolt' });
    const conn = add(wheel, new THREE.BoxGeometry(0.03, 0.018, 0.015), MAT.yellow, { pos: [0.03, -0.03, 0.02], part: 'conn' });
    const mod = group(scene, { pos: [0, 0, 0.035], part: 'module' });
    add(mod, Z(cyl(0.08, 0.035)), MAT.black);
    add(mod, new THREE.TorusGeometry(0.03, 0.004, 8, 32), MAT.steel, { pos: [0, 0, 0.018] });
    const marks = [add(wheel, new THREE.BoxGeometry(0.004, 0.02, 0.004), MAT.white, { pos: [0, 0.095, -0.03], nopick: true }), add(scene, new THREE.BoxGeometry(0.004, 0.02, 0.004), MAT.white, { pos: [0, 0.095, -0.08], nopick: true })];
    marks.forEach(m => m.visible = false);
    const bat = group(scene, { pos: [0.55, -0.2, -0.4] });
    add(bat, new THREE.BoxGeometry(0.2, 0.14, 0.12), MAT.black, { part: 'battery' });
    const neg = add(bat, cyl(0.012, 0.03), MAT.darkSteel, { pos: [-0.06, 0.085, 0], part: 'batneg' });
    Object.assign(L, { column: 'Steering column', clock: 'Clock spring', splines: 'Column splines', wheel: 'Steering wheel', cbolt: 'Centre bolt',
      conn: 'Airbag connector (yellow)', module: 'Driver airbag module', battery: 'Battery', batneg: 'Battery negative' });
    return { labels: L, wheel, mod, bolt, conn, marks, neg, clock, update() {} };
  },
  stages: [
    order({
      title: 'Isolate and wait', car: { cam: [[3.2, 1.55, 2.3], [0.45, 0.85, 0.4]] },
      lead: 'This is the real Golf. The airbag unit keeps a reserve charge so the bag still fires if a crash destroys the battery. That reserve is what can fire it on your bench.',
      steps: [
        { t: 'Look up the procedure and the stand-down time' },
        { t: 'Open the driver\u2019s door', pick: 'door_fl', anim: async a => { const g = carPart('door_fl'); if (g) await tween(g.rotation, { y: -DOOR_OPEN }, 0.8); if (a.C) await camTo([2.1, 1.35, -0.2], [0.36, 0.95, 0.6]); } },
        { t: 'Ignition off, key out of the car', early: 'Open the driver\u2019s door first.' },
        { t: 'Battery negative off and secured', anim: async () => {} },
        { t: 'Wait the stand-down time', note: 'Waiting. On the car, the time comes from the workshop data. This sim uses 10 seconds.', anim: async a => {
          for (let s = 10; s > 0; s--) { a.info(`Waiting: ${s} s. The reserve charge is draining. (Sim: 10 s. On the car, the time in the data.)`); await wait(1000); }
          a.clear();
        } },
      ],
      traps: [
        { t: 'Pull the airbag fuse and start straight away', why: 'The reserve charge is inside the airbag unit, after the fuse. Isolate, then wait the full time.' },
        { t: 'Open the front-right door to reach the wheel', pick: 'door_fr', why: 'This car is left-hand drive: the steering wheel is on the LEFT. Check the drive side of the car in front of you.' },
        { t: 'Check the airbag circuit with a multimeter to see if it is safe', why: 'A meter passes its own test current through the igniter. That can fire it. Never.' },
      ],
      done: 'Isolated and stood down.',
    }),
    order({
      title: 'Remove the wheel',
      lead: 'Take the airbag module and the steering wheel off.',
      steps: [
        { t: 'Wheels straight, steering centred and locked', pick: 'wheel' },
        { t: 'Release the airbag module clips', pick: 'module', anim: async a => { await tween(a.R.mod.position, { z: 0.09 }, 0.4); } },
        { t: 'Unlock and unplug the yellow airbag connector', pick: 'conn' },
        { t: 'Carry the module face up, set it down face up', anim: async a => { await Promise.all([tween(a.R.mod.position, { x: 0.38, y: -0.25, z: 0.15 }, 0.8), tween(a.R.mod.rotation, { x: -Math.PI / 2 }, 0.8)]); } },
        { t: 'Mark the wheel to the column', anim: async a => { a.R.marks.forEach(m => m.visible = true); } },
        { t: 'Remove the centre bolt', pick: 'cbolt', early: 'Mark the wheel to the column first, or it can go back on a spline out.', anim: async a => { await tween(a.R.bolt.position, { z: 0.12 }, 0.4); a.R.bolt.visible = false; } },
        { t: 'Lift the wheel off the splines', pick: 'wheel', anim: async a => { await tween(a.R.wheel.position, { z: 0.25 }, 0.7); } },
        { t: 'Tape the clock spring so it cannot turn', pick: 'clock' },
      ],
      traps: [
        { t: 'Set the module down face down on the bench', why: 'If it fires face down it launches itself off the bench. Face up, it inflates into the air.' },
        { t: 'Turn the wheel lock to lock to check the clock spring', why: 'With the wheel off, turning the column can wind the clock spring past its travel and tear it.' },
        { t: 'Pull the connector off by its wires', why: 'Unlock the connector first and pull the body. A damaged airbag connector is a warning lamp and a new loom.' },
      ],
      done: 'Wheel off, module face up, clock spring held centred.',
    }),
    order({
      title: 'Refit and prove',
      lead: 'Put it back and prove the airbag system is healthy.',
      steps: [
        { t: 'Check the clock spring is still centred', pick: 'clock' },
        { t: 'Wheel on with the marks aligned', pick: 'wheel', anim: async a => { await tween(a.R.wheel.position, { z: 0 }, 0.7); } },
        { t: 'New centre bolt, torque and angle from the data', pick: 'cbolt', anim: async a => { a.R.bolt.visible = true; await tween(a.R.bolt.position, { z: 0.018 }, 0.4); } },
        { t: 'Airbag connector on until it locks', pick: 'conn', anim: async a => { await Promise.all([tween(a.R.mod.position, { x: 0, y: 0, z: 0.09 }, 0.8), tween(a.R.mod.rotation, { x: 0 }, 0.8)]); } },
        { t: 'Module on until every clip engages', pick: 'module', anim: async a => { await tween(a.R.mod.position, { z: 0.035 }, 0.4); } },
        { t: 'Nobody in the car: battery negative on', pick: 'batneg', anim: async a => { await tween(a.R.neg.position, { y: 0.085 }, 0.4); } },
        { t: 'Ignition on from outside the airbag’s path: the warning lamp comes on, then goes out' },
      ],
      traps: [
        { t: 'Reuse the old centre bolt', why: 'Centre bolts are often single-use stretch bolts. The data says, and a new one is cheap.' },
        { t: 'Reconnect the battery with someone sitting in the driver’s seat', why: 'If anything is wrong, the first power-up is when it fires. Nobody in the airbag’s path.' },
      ],
      done: 'Warning lamp out, wheel straight, airbag system proved.',
    }),
  ],
};

const JOBS = [misfire, starter, alternator, brakes, airbag];

/* ───────────────────────── home tiles, routing, loop ───────────────────────── */
function renderTiles() {
  const box = $('#sim-tiles'); if (!box) return;
  const prog = loadProg(); box.textContent = '';
  JOBS.forEach(j => {
    const p = prog[j.id];
    box.append(h('a', { class: 'tile', href: '#sim-' + j.id },
      h('p', { class: 'eyebrow' }, j.kind), h('h3', {}, j.title), h('p', {}, j.blurb),
      h('span', { class: 'go' }, `${j.stages.length} stages`, p && p.done ? h('span', { class: 'badge' }, p.best ? `Done · best ${p.best} fault${p.best > 1 ? 's' : ''}` : 'Done · clean') : null)));
  });
}
let activeId = null;
function route() {
  const hsh = location.hash.slice(1);
  if (hsh === 'sim' || hsh === '') { activeId = null; renderTiles(); return; }
  if (hsh.startsWith('sim-')) { const id = hsh.slice(4); if (id !== activeId) { activeId = id; openJob(id); } return; }
  activeId = null;
}
window.addEventListener('hashchange', route);
$('#sim-ready').hidden = true;
// read-only handle for the automated walkthrough test (platform/trainer/simtest.mjs)
window.__sim = { get run() { return run; }, get api() { return api; }, get car() { return CAR; }, get tweens() { return tweens.length; }, get frames() { return frames; }, get active() { return [activeId, !!scene, document.hidden]; } };
route();

const clock = new THREE.Clock();
let frames = 0;
(function loop() {
  requestAnimationFrame(loop); frames++;
  const raw = clock.getDelta(), dt = Math.min(raw, 0.05);
  if (!activeId || !renderer || !scene || document.hidden) return;
  // tweens run on wall-clock time so a slow device finishes an action on time
  // (the engine and rotor animations keep the capped step so they never jump)
  runTweens(Math.min(raw, 1));
  if (R && R.update) R.update(dt);
  ticks.forEach(f => f());
  controls.update();
  renderer.render(scene, camera);
})();
