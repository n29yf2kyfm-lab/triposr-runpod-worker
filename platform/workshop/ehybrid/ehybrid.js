import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { FLEET, classifyMesh } from './fleet.js';
import { measureCar, buildPowertrain } from './powertrain.js';
import { buildEngineBayDetail } from './engine-bay-detail.js';
import { buildInnerApron } from './engine-bay-shell.js';
import { buildTransmission } from './transmission-detail.js';
import { extractFrontBumper } from './front-bumper.js';
import { buildHybrid, buildEngineStrip } from './hybrid-parts.js';

/* Golf Mk8 eHybrid workshop. Built on the Golf Workshop's real Mk8 body
   (2021 Volkswagen Golf GTI by Ddiaz Design, Sketchfab, CC BY-NC-SA 4.0),
   its constructed engine bay and DSG, and the eHybrid parts in hybrid-parts.js.
   Frame: +X is the car's LEFT, +Y up, +Z the nose, metres. */

const $ = s => document.querySelector(s);
const V = (x, y, z) => new THREE.Vector3(x, y, z);
const DEG = Math.PI / 180;
const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;

/* ───────── renderer, scene ───────── */
const stage = $('#stage');
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.NeutralToneMapping;
renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
stage.append(renderer.domElement);
const scene = new THREE.Scene();
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = 0.9;
const camera = new THREE.PerspectiveCamera(34, 1, 0.02, 80);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true; controls.dampingFactor = 0.09; controls.screenSpacePanning = true;
controls.minDistance = 0.6; controls.maxDistance = 14; controls.maxPolarAngle = Math.PI * 0.6;
const key = new THREE.DirectionalLight(0xffffff, 1.6); key.position.set(4, 7, 5); key.castShadow = true;
key.shadow.mapSize.set(2048, 2048); Object.assign(key.shadow.camera, { left: -4, right: 4, top: 4, bottom: -4, near: 1, far: 20 }); scene.add(key);
scene.add(new THREE.HemisphereLight(0xdfe8f2, 0x3a3f46, 0.5));
const floor = new THREE.Mesh(new THREE.CircleGeometry(9, 64), new THREE.MeshStandardMaterial({ color: 0x8c949b, roughness: 0.92, metalness: 0 }));
floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);
const grid = new THREE.GridHelper(18, 72, 0x5f6870, 0x737c84); grid.position.y = 0.001; grid.material.transparent = true; grid.material.opacity = 0.25; scene.add(grid);

function materialFactory(color, options = {}, finish = 'cast') {
  const m = new THREE.MeshPhysicalMaterial({ color, ...options });
  if (finish === 'paint') { m.clearcoat = 0.75; m.clearcoatRoughness = 0.2; }
  return m;
}

/* ───────── parts registry ─────────
   Every part: one group in the scene, a home position, an explode vector,
   service-step offsets that tween, and the facts shown when it is picked. */
const SYS = {
  body: 'Body and panels', interior: 'Interior', wheels: 'Wheels and brakes', susp: 'Suspension and steering',
  bay: 'Engine bay (EA211 1.4 TSI)', strip: 'Engine internals (strip-down)', gearbox: 'DQ400e gearbox and drive shafts',
  hybrid: 'Hybrid drive and high voltage', fuel: 'Fuel and exhaust',
};
const SYS_COLOR = { body: '#8aa0b4', interior: '#5a5148', wheels: '#9aa0a6', susp: '#3f464d', bay: '#6c757d', strip: '#a6afb5', gearbox: '#737874', hybrid: '#ff6a00', fuel: '#7a6a5a' };
const parts = [], byId = {};
function register(p) {
  p.home = p.obj.position.clone(); p.svc = V(0, 0, 0); p.svcT = V(0, 0, 0); p.hideT = !!p.hidden; p.vis = true;
  p.obj.traverse(o => { if (o.isMesh) o.userData.pid = p.id; });
  parts.push(p); byId[p.id] = p; return p;
}
const info = (o = {}) => ({ qty: 1, mat: '', size: '', conf: 'est', note: '', tags: [], ...o });

/* ───────── the real car ───────── */
const GOLF = FLEET.golf;
const CAR_PARTS = {
  body: ['Body shell, roof, wings and sills', 'body', [0, 0, 0], { mat: 'Painted steel (real model geometry)', conf: 'model', note: 'Real Golf Mk8 geometry from the source model. Bonnet, wings and roof come from one welded mesh in that file.' }],
  bumper_f: ['Front bumper cover and grille', 'body', [0, 0, 0.95], { tags: ['bumper'], conf: 'model', note: 'Cut out of the body mesh. This is the GTI front: the eHybrid’s bumper and grille differ in detail.' }],
  panel_bonnet: ['Bonnet', 'body', [0, 0.95, 0.35], { tags: ['bonnet'], conf: 'model' }],
  tailgate: ['Tailgate', 'body', [0, 0.55, -0.75], { conf: 'model' }],
  door_fl: ['Front-left door and mirror', 'body', [1.0, 0, 0.1], { conf: 'model' }], door_fr: ['Front-right door', 'body', [-1.0, 0, 0.1], { conf: 'model' }],
  door_rl: ['Rear-left door', 'body', [1.0, 0, -0.1], { conf: 'model' }], door_rr: ['Rear-right door', 'body', [-1.0, 0, -0.1], { conf: 'model' }],
  glazing: ['Glazing (windscreen, side and rear glass)', 'body', [0, 0.4, 0], { conf: 'model' }],
  wheel_fl: ['Wheel and tyre, front-left', 'wheels', [0.95, 0, 0], { conf: 'model', tags: ['wheel'] }], wheel_fr: ['Wheel and tyre, front-right', 'wheels', [-0.95, 0, 0], { conf: 'model', tags: ['wheel'] }],
  wheel_rl: ['Wheel and tyre, rear-left', 'wheels', [0.95, 0, 0], { conf: 'model', tags: ['wheel'] }], wheel_rr: ['Wheel and tyre, rear-right', 'wheels', [-0.95, 0, 0], { conf: 'model', tags: ['wheel'] }],
  rotor_fl: ['Front brake disc, left', 'wheels', [0.62, 0, 0], { conf: 'model' }], rotor_fr: ['Front brake disc, right', 'wheels', [-0.62, 0, 0], { conf: 'model' }],
  caliper_fl: ['Front brake caliper, left', 'wheels', [0.72, 0.15, 0], { conf: 'model' }], caliper_fr: ['Front brake caliper and rear brakes', 'wheels', [-0.72, 0.15, 0], { conf: 'model' }],
  seats: ['Seats', 'interior', [0, 0.95, 0], { conf: 'model', note: 'The eHybrid’s rear bench sits over the HV battery (layout estimated).' }],
  steering: ['Steering wheel', 'interior', [0, 0.55, 0.35], { conf: 'model' }],
  cabin: ['Dashboard, trim, carpets and headlining', 'interior', [0, 0.65, 0], { conf: 'model' }],
};
const HINGE = { door_fl: { axis: 'y', ang: -64 }, door_fr: { axis: 'y', ang: 64 }, door_rl: { axis: 'y', ang: -64 }, door_rr: { axis: 'y', ang: 64 }, panel_bonnet: { axis: 'x', ang: -52 }, tailgate: { axis: 'x', ang: 62 } };
const carRoot = new THREE.Group(); scene.add(carRoot);
let bodyMats = [];

function buildCar(root) {
  carRoot.add(root); carRoot.updateMatrixWorld(true);
  try { extractFrontBumper(root); } catch (e) { console.warn('front bumper not split', e); }
  const by = {}, meshes = [];
  root.traverse(o => { if (o.isMesh) meshes.push(o); });
  for (const o of meshes) {
    const id = /^Panel_Bumper_Front/.test(o.name) ? 'bumper_f' : classifyMesh(GOLF, o);
    (by[id] ||= []).push(o); o.castShadow = id !== 'glazing'; o.receiveShadow = true;
  }
  const boxes = {};
  for (const id in by) { const b = new THREE.Box3(); by[id].forEach(m => b.expandByObject(m)); boxes[id] = b; }
  const meas = measureCar(boxes);
  for (const id in by) {
    const c = boxes[id].getCenter(V(0, 0, 0)), hg = GOLF.hinge[id];
    const g = new THREE.Group(); g.position.copy(hg ? V(hg.x, hg.y || c.y, hg.z) : c); carRoot.add(g); g.updateMatrixWorld(true);
    by[id].forEach(m => g.attach(m));
    const d = CAR_PARTS[id] || [id, 'body', [0, 0, 0], {}];
    register({ id, name: d[0], sys: d[1], obj: g, ex: V(...d[2]), ...info(d[3]) });
  }
  // see-through control acts on the shell and its panels
  const seen = new Set();
  for (const id of ['body', 'bumper_f', 'panel_bonnet', 'tailgate', 'door_fl', 'door_fr', 'door_rl', 'door_rr', 'cabin']) {
    byId[id]?.obj.traverse(o => { if (!o.isMesh) return; o.material = [].concat(o.material).map(m => { const c = m.clone(); c.userData.op0 = c.opacity; c.userData.tr0 = c.transparent; seen.add(c); return c; }); if (o.material.length === 1) o.material = o.material[0]; });
  }
  bodyMats = [...seen];
  return meas;
}

/* ───────── constructed engine bay, gearbox, suspension ───────── */
const BAY_INFO = {
  'engine-long-block': ['Engine long block (one piece in the bay)', { tags: ['pt', 'engine', 'longblock'], note: 'Shown whole in the car. On the bench it is replaced by the strip-down set, piece by piece.' }, [0, 0, 0]],
  'moulded-four-coil-valve-cover': ['Camshaft cover (bay view)', { tags: ['pt', 'engine', 'longblock'] }, [0, 0.55, 0]],
  'four-coil-ignition-assembly': ['Ignition coils', { qty: 4, tags: ['pt', 'engine', 'longblock'] }, [0, 0.75, 0]],
  'cosmetic-engine-cover-removable': ['Engine cover', { tags: ['cover'] }, [0, 0.95, 0]],
  'intake-manifold': ['Intake manifold with water-cooled intercooler', { tags: ['pt', 'engine', 'longblock'], note: 'The intercooler is built into the intake manifold on the EA211 (published).' }, [0, 0.30, -0.45]],
  'airbox-assembly': ['Air filter box', { tags: ['airbox'] }, [0.45, 0.70, 0]],
  'airbox-to-throttle-duct': ['Air intake duct', { tags: ['airbox'] }, [0.35, 0.60, -0.1]],
  'battery-assembly': ['12 V battery', { tags: ['battery12'], note: 'Disconnected before any work. The eHybrid keeps a 12 V battery for the car’s low-voltage systems.' }, [0.55, 0.45, 0]],
  'battery-positive-cable-to-starter': ['12 V positive cable', { tags: ['battery12'], note: 'The eHybrid has no conventional starter: the e-motor starts the engine (published). This cable is the Golf bay’s and is kept for its 12 V feed.' }, [0.3, 0.35, 0]],
  'battery-negative-earth-lead': ['12 V earth lead', { tags: ['battery12'] }, [0.45, 0.35, 0]],
  'engine-wiring-harness': ['Engine wiring harness', { tags: ['pt', 'engine', 'longblock'] }, [0, 0.65, -0.1]],
  'accessory-drive': ['Auxiliary drive pulleys and belt', { tags: ['pt', 'engine', 'longblock'] }, [0.45, 0, 0]],
  'radiator-condenser-cooling-pack': ['Radiator, condenser and fans', { tags: ['coolpack'] }, [0, 0.05, 0.75]],
  'radiator-upper-hose': ['Radiator hose, upper', { tags: ['hose'] }, [0, 0.3, 0.4]],
  'radiator-lower-hose': ['Radiator hose, lower', { tags: ['hose'] }, [0, -0.2, 0.4]],
  'coolant-expansion-reservoir': ['Coolant expansion tank', { tags: ['reservoir'] }, [-0.45, 0.55, 0]],
  'coolant-degas-hose': ['Coolant degas hose', { tags: ['reservoir'] }, [-0.35, 0.5, 0]],
  'engine-bay-structure': ['Front crossmember and lock carrier', {}, [0, 0, 0]],
};
const TX_INFO = {
  'gearbox-case': ['DQ400e gearcase (6-speed wet dual clutch)', { tags: ['pt', 'gearbox'], conf: 'pub', note: 'Six-speed wet dual-clutch gearbox with the hybrid module between it and the engine (published layout). Casting shape from the Golf bay, not CAD.' }, [-0.55, 0, 0]],
  'bellhousing': ['Clutch housing and engine flange (12 bolts)', { tags: ['pt', 'gearbox'] }, [-0.42, 0, 0]],
  'mechatronic-cover': ['Mechatronic unit and cover', { tags: ['pt', 'gearbox'], note: 'The gearbox’s hydraulic and electronic control unit, with its gasket and ten bolts.' }, [-0.55, 0, -0.35]],
  'transmission-oil-filter': ['Gearbox oil filter housing', { tags: ['pt', 'gearbox'] }, [-0.45, 0.45, 0]],
  'transmission-oil-cooler': ['Gearbox oil cooler', { tags: ['pt', 'gearbox'] }, [-0.35, 0.5, 0]],
  'integrated-front-differential': ['Front differential', { tags: ['pt', 'gearbox'] }, [-0.5, -0.25, 0]],
  'cv-output-left': ['Drive flange, right-hand side', { tags: ['pt', 'gearbox'] }, [-0.65, -0.1, 0]],
  'cv-output-right': ['Drive flange, left-hand side', { tags: ['pt', 'gearbox'] }, [0.2, -0.1, 0]],
  'driveshaft-left': ['Drive shaft and CV joints, short side', { tags: ['ds'] }, [-0.45, -0.25, 0]],
  'driveshaft-right': ['Drive shaft and CV joints, long side', { tags: ['ds'] }, [0.45, -0.25, 0]],
};
function buildBay(meas) {
  const bay = buildEngineBayDetail({ materialFactory });
  const bayG = new THREE.Group(); bayG.name = 'golf-bay'; carRoot.add(bayG);
  bayG.add(bay.group);
  try { bayG.add(buildInnerApron(1, materialFactory), buildInnerApron(-1, materialFactory)); } catch (e) { /* dressing */ }
  bay.group.getObjectByName('bellhousing-starter-interface')?.removeFromParent();   // no starter on the eHybrid
  bayG.updateMatrixWorld(true);
  for (const c of [...bay.group.children]) {
    const d = BAY_INFO[c.name] || [c.name.replace(/-/g, ' '), {}, [0, 0, 0]];
    bayG.attach(c);
    register({ id: c.name, name: d[0], sys: 'bay', obj: c, ex: V(...d[2]), ...info({ note: 'Constructed teaching geometry from the Golf Workshop bay, not OEM CAD.', ...d[1] }) });
  }
  const tx = buildTransmission({ materialFactory });
  bayG.add(tx.group); bayG.updateMatrixWorld(true);
  for (const c of [...tx.group.children]) {
    const d = TX_INFO[c.name] || [c.name.replace(/-/g, ' '), {}, [-0.4, 0, 0]];
    bayG.attach(c);
    register({ id: c.name, name: d[0], sys: c.name.startsWith('driveshaft') ? 'gearbox' : 'gearbox', obj: c, ex: V(...d[2]), ...info({ note: 'Constructed teaching geometry: dimensions and routing illustrative, not OEM CAD.', ...d[1] }) });
  }
  if (meas) {
    const pt = buildPowertrain({ engine: 'I4', mount: 'trans', drive: 'FWD', front: 'strut', rear: 'multilink', turbo: true }, meas, { engine: true, rotors: true });
    const front = new THREE.Group(), rear = new THREE.Group(); carRoot.add(front, rear);
    for (const c of [...pt.suspension.children]) { const b = new THREE.Box3().setFromObject(c); (b.getCenter(V(0, 0, 0)).z > 0 ? front : rear).add(c); }
    register({ id: 'susp_front', name: 'Front suspension: MacPherson struts, springs, lower arms, subframe', sys: 'susp', obj: front, ex: V(0, -0.45, 0.15), ...info({ tags: ['frontsusp'], note: 'Constructed to the car’s measured wheels and track. Layout typical for the Mk8 Golf; parts simplified.' }) });
    register({ id: 'susp_rear', name: 'Rear suspension: multi-link, springs, dampers, subframe', sys: 'susp', obj: rear, ex: V(0, -0.45, -0.15), ...info({ note: 'The eHybrid uses the multi-link rear (est. for this trim). Constructed geometry.' }) });
  }
}

/* ───────── eHybrid parts and the engine strip set ───────── */
function buildHybridParts() {
  const hy = buildHybrid(materialFactory);
  for (const p of hy.parts) { carRoot.add(p.obj); register({ ...p, ...info({ ...p, tags: p.tags }) }); }
  const st = buildEngineStrip(materialFactory, hy.M);
  for (const p of st.parts) { carRoot.add(p.obj); register({ ...p, ...info({ ...p, tags: p.tags }), hidden: true }); }
}

/* ───────── service procedure: engine out, strip, refit ───────── */
const has = (p, t) => p.tags.includes(t);
const TAG_MOVE = (tag, v, s) => parts.forEach(p => { if (has(p, tag)) s[p.id].o.add(v); });
const TAG_HIDE = (tag, s) => parts.forEach(p => { if (has(p, tag)) s[p.id].h = true; });
const STEPS = [
  { t: 'Car in the workshop', d: 'Everything fitted, bonnet up. Next takes the engine, hybrid module and gearbox out the way VW workshops do it on a transverse Golf: down and out from underneath, with the front end in its service position.', f: () => {} },
  { t: 'Make the high-voltage system safe', hv: true, d: 'Everything in orange carries high voltage. Before any work in the bay, the HV system is switched off and locked out, then the 12 V battery is disconnected.', f: () => {} },
  { t: 'Bonnet, bumper and engine cover off', d: 'Remove the bonnet for access, take off the front bumper cover, then lift off the engine cover.', f: s => { TAG_MOVE('bonnet', V(0, 0.6, 0), s); TAG_HIDE('bonnet', s); TAG_MOVE('bumper', V(0, 0, 0.6), s); TAG_HIDE('bumper', s); TAG_MOVE('cover', V(0, 0.5, 0), s); TAG_HIDE('cover', s); } },
  { t: 'Air box, 12 V battery and coolant tank out', d: 'Drain the coolant. Remove the air filter box and intake duct, the 12 V battery with its cables, and the coolant expansion tank.', f: s => { for (const t of ['airbox', 'battery12', 'reservoir']) { TAG_MOVE(t, V(0, 0.5, 0), s); TAG_HIDE(t, s); } } },
  { t: 'Cooling pack to service position', d: 'Disconnect the radiator hoses. Pull the radiator and condenser pack forward on its carrier so the engine has room to drop.', f: s => { TAG_MOVE('hose', V(0, 0.3, 0.2), s); TAG_HIDE('hose', s); TAG_MOVE('coolpack', V(0, 0, 0.5), s); } },
  { t: 'Disconnect HV cables and exhaust', hv: true, d: 'With the system made safe, unplug the HV cable at the inverter. Split the downpipe from the turbocharger and drop the front of the exhaust.', f: s => { TAG_MOVE('hvcable', V(0, -0.06, 0), s); TAG_MOVE('exhaust', V(0, -0.12, 0), s); } },
  { t: 'Raise the car, drive shafts out', lift: true, d: 'Raise the car on the lift. Undo the drive-shaft flange bolts at the gearbox and the hub bolts, swing the wheel bearing housings out and pull both shafts.', f: s => { parts.forEach(p => { if (has(p, 'ds')) { s[p.id].o.add(V(p.id.endsWith('right') ? 0.55 : -0.55, -0.05, 0)); s[p.id].h = true; } }); } },
  { t: 'Lower engine, hybrid module and gearbox', d: 'Support the assembly on an engine table, take out the pendulum support and the engine and gearbox mounts, and lower it out of the bay.', f: s => TAG_MOVE('pt', V(0, -0.78, 0), s) },
  { t: 'Roll it out', d: 'Roll the table forward, clear of the car.', f: s => TAG_MOVE('pt', V(0, 0, 2.0), s) },
  { t: 'Split engine from hybrid module and gearbox', d: 'Undo the twelve engine-to-module flange bolts, slide the engine off and mount it on an engine stand. Replace the module O-rings on refit.', f: s => TAG_MOVE('engine', V(0.55, 0.55, 0), s) },
  { t: 'Strip the engine', d: 'Set the intake manifold, coils, harness and auxiliary drive aside, then take it down: cam cover, camshafts, timing belt, cylinder head, sump, pistons and crankshaft, each laid out with its bolts and seals. Green parts are seals and gaskets, gold are fasteners: renew every seal and every stretch bolt. Refit is this list in reverse, with torque values from erWin.', f: s => { parts.forEach(p => { if (has(p, 'longblock')) s[p.id].h = true; if (has(p, 'strip')) { s[p.id].h = false; s[p.id].o.add(p.stripEx); } }); } },
];
let step = 0, reversing = false, liftT = 0, liftY = 0;
const LIFT = 0.95;
function applyStep() {
  const s = {}; parts.forEach(p => s[p.id] = { o: V(0, 0, 0), h: !!p.hidden });
  for (let i = 0; i <= step; i++) STEPS[i].f(s);
  parts.forEach(p => { p.svcT.copy(s[p.id].o); p.hideT = s[p.id].h; });
  $('#stepn').textContent = `Step ${step + 1} of ${STEPS.length}${reversing ? ' · refitting' : ''}`;
  $('#stept').textContent = STEPS[step].t; $('#stepd').textContent = STEPS[step].d;
  $('#hvnote').hidden = !STEPS[step].hv;
  $('#prev').disabled = step === 0 && !reversing;
  $('#next').textContent = step === STEPS.length - 1 && !reversing ? 'Start refit' : reversing ? (step === 0 ? 'Refitted' : 'Refit next') : 'Next step';
  $('#next').disabled = reversing && step === 0;
  hvPulse = STEPS[step].hv;
  liftT = STEPS.slice(0, step + 1).some(x => x.lift) ? LIFT : 0;
}
$('#next').onclick = () => { if (!reversing && step === STEPS.length - 1) reversing = true; if (reversing) step = Math.max(0, step - 1); else step++; applyStep(); };
$('#prev').onclick = () => { if (reversing) { step = Math.min(STEPS.length - 1, step + 1); if (step === STEPS.length - 1) reversing = false; } else step = Math.max(0, step - 1); applyStep(); };
$('#reset').onclick = () => { reversing = false; step = 0; applyStep(); };

/* ───────── parts list, selection ───────── */
let selected = null;
const confTag = c => c === 'pub' ? '<span class="conf pub">published</span>' : c === 'model' ? '<span class="conf model">real model</span>' : '<span class="conf est">estimated</span>';
function buildTree() {
  const tree = $('#tree'); tree.textContent = '';
  let total = 0;
  for (const [k, label] of Object.entries(SYS)) {
    const list = parts.filter(p => p.sys === k); if (!list.length) continue;
    const n = list.reduce((a, p) => a + p.qty, 0); total += n;
    const d = document.createElement('details'); d.className = 'sys'; d.open = k === 'hybrid' || k === 'strip';
    const sm = document.createElement('summary');
    sm.innerHTML = `<i class="dot" style="background:${SYS_COLOR[k]}"></i><span></span><span class="n">${n}</span>`; sm.children[1].textContent = label; d.append(sm);
    for (const p of list) {
      const r = document.createElement('div'); r.className = 'row'; r.id = 'row_' + p.id;
      const cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = true; cb.id = 'cb_' + p.id; cb.setAttribute('aria-label', 'Show ' + p.name); cb.onchange = () => { p.vis = cb.checked; };
      const b = document.createElement('button'); b.textContent = p.name; b.onclick = () => select(p.id, true);
      const q = document.createElement('span'); q.className = 'q'; q.textContent = p.qty > 1 ? '×' + p.qty : '';
      if (has(p, 'seal')) b.classList.add('isseal'); if (has(p, 'fastener')) b.classList.add('isbolt'); if (has(p, 'hv')) b.classList.add('ishv');
      r.append(cb, b, q); d.append(r);
    }
    tree.append(d);
  }
  $('#count').textContent = `${total} parts`;
}
const HL = new THREE.Color(0x2f8cff);
function setHighlight(id, on) {
  const p = byId[id]; if (!p) return;
  p.obj.traverse(o => { if (!o.isMesh) return;
    if (on) { o.userData.m0 = o.material; o.material = [].concat(o.material).map(m => { const c = m.clone(); if (c.emissive) { c.emissive = HL; c.emissiveIntensity = 0.5; } return c; }); if (o.material.length === 1) o.material = o.material[0]; }
    else if (o.userData.m0) { o.material = o.userData.m0; delete o.userData.m0; } });
}
function select(id, frame) {
  if (selected) { setHighlight(selected, false); $('#row_' + selected)?.classList.remove('sel'); }
  selected = id; const p = byId[id]; if (!p) return;
  setHighlight(id, true);
  const row = $('#row_' + id); if (row) { row.classList.add('sel'); row.closest('details').open = true; row.scrollIntoView({ block: 'nearest' }); }
  const box = $('#info'); box.textContent = '';
  const h = document.createElement('div'); h.className = 'pname'; h.textContent = p.name; box.append(h);
  const dl = document.createElement('dl'); dl.className = 'kv';
  for (const [k, v] of [['System', SYS[p.sys]], ['Quantity', String(p.qty)], ['Material', p.mat || '—'], ['Size', p.size || '—'], ['OEM part no.', 'not included'], ['Torque', 'not included (erWin)']]) {
    const dt = document.createElement('dt'); dt.textContent = k; const dd = document.createElement('dd'); dd.textContent = v; dl.append(dt, dd);
  }
  const dt = document.createElement('dt'); dt.textContent = 'Source'; const dd = document.createElement('dd'); dd.innerHTML = confTag(p.conf); dl.append(dt, dd);
  box.append(dl);
  const n = document.createElement('p'); n.className = 'note'; n.textContent = p.note || 'Shape and position estimated.'; box.append(n);
  if (frame) { const b = new THREE.Box3().setFromObject(p.obj); if (!b.isEmpty()) { const c = b.getCenter(V(0, 0, 0)), r = Math.max(0.35, b.getSize(V(0, 0, 0)).length()); flyTo(c.clone().add(V(r * 1.1, r * 0.7, r * 1.3)), c); } }
}
$('#isolate').onclick = () => { if (!selected) return; const s = byId[selected].sys; parts.forEach(p => { p.vis = p.sys === s; $('#cb_' + p.id).checked = p.vis; }); };
$('#showall').onclick = () => parts.forEach(p => { p.vis = true; $('#cb_' + p.id).checked = true; });
const ray = new THREE.Raycaster(), ptr = new THREE.Vector2(); let down = null;
renderer.domElement.addEventListener('pointerdown', e => down = [e.clientX, e.clientY]);
renderer.domElement.addEventListener('pointerup', e => {
  if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;
  const r = renderer.domElement.getBoundingClientRect(); ptr.set((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1);
  ray.setFromCamera(ptr, camera);
  const xr = +$('#xray').value < 0.5;
  const objs = parts.filter(p => p.obj.visible && !(xr && ['body', 'glazing', 'cabin', 'panel_bonnet', 'tailgate', 'bumper_f'].includes(p.id) || p.id.startsWith('door_') && xr)).map(p => p.obj);
  const hit = ray.intersectObjects(objs, true).find(h => h.object.userData.pid);
  if (hit) select(hit.object.userData.pid, false);
});

/* ───────── view controls ───────── */
let explode = 0, hvPulse = false;
$('#explode').oninput = e => explode = +e.target.value;
$('#xray').oninput = e => setOpacity(+e.target.value);
function setOpacity(v) { for (const m of bodyMats) { m.transparent = v < 0.999 || m.userData.tr0; m.opacity = Math.min(m.userData.op0, v); m.depthWrite = v > 0.6; m.needsUpdate = true; } }
const VIEWS = { iso: [[4.6, 2.6, 4.8], [0, 0.55, 0.2]], side: [[6.4, 1.1, 0.1], [0, 0.6, 0]], bay: [[1.9, 1.9, 3.3], [-0.05, 0.55, 1.5]], under: [[2.4, -0.4, 2.2], [0, 0.35, 0.3]], top: [[0.01, 7.5, 0.2], [0, 0, 0.2]], bench: [[3.4, 1.9, 4.4], [0.3, 0.95, 3.45]] };
let fly = null;
function flyTo(pos, tgt) { fly = { p: pos.clone(), t: tgt.clone() }; }
document.querySelectorAll('[data-v]').forEach(b => b.onclick = () => { const [p, t] = VIEWS[b.dataset.v], up = b.dataset.v === 'bench' || b.dataset.v === 'top' ? 0 : liftT; flyTo(V(p[0], p[1] + up, p[2]), V(t[0], t[1] + up, t[2])); });
camera.position.set(...VIEWS.iso[0]); controls.target.set(...VIEWS.iso[1]);

/* ───────── loop ───────── */
const clock = new THREE.Clock();
function resize() { const w = stage.clientWidth, h = stage.clientHeight; if (renderer.domElement.width !== Math.floor(w * renderer.getPixelRatio()) || renderer.domElement.height !== Math.floor(h * renderer.getPixelRatio())) { renderer.setSize(w, h, false); camera.aspect = w / Math.max(h, 1); camera.updateProjectionMatrix(); } }
const HVC = new THREE.Color(0xff6a00);
function tick() {
  resize();
  const dt = Math.min(clock.getDelta(), 0.05), k = REDUCED ? 1 : 1 - Math.pow(0.0015, dt);
  liftY += (liftT - liftY) * k; carRoot.position.y = liftY;
  for (const p of parts) {
    p.svc.lerp(p.svcT, k);
    p.obj.position.copy(p.home).add(p.svc).addScaledVector(p.ex, has(p, 'strip') ? 0 : explode);
    const gone = p.hideT && p.svc.distanceTo(p.svcT) < 0.02;
    p.obj.visible = p.vis && !gone;
  }
  if (hvPulse) { const a = 0.35 + 0.35 * Math.sin(performance.now() / 220); parts.forEach(p => { if (has(p, 'hv') && p.id !== selected) p.obj.traverse(o => { if (o.isMesh && o.material.emissive) { if (!o.userData.hvm) { o.userData.hvm = o.material; o.material = o.material.clone(); } o.material.emissive = HVC; o.material.emissiveIntensity = a; } }); }); }
  else parts.forEach(p => { if (has(p, 'hv')) p.obj.traverse(o => { if (o.isMesh && o.userData.hvm) { o.material = o.userData.hvm; delete o.userData.hvm; } }); });
  if (fly) { const f = REDUCED ? 1 : 1 - Math.pow(0.02, dt); camera.position.lerp(fly.p, f); controls.target.lerp(fly.t, f); if (camera.position.distanceTo(fly.p) < 0.01) fly = null; }
  controls.update(); renderer.render(scene, camera); requestAnimationFrame(tick);
}

/* ───────── load ───────── */
const loader = new GLTFLoader(); loader.setMeshoptDecoder(MeshoptDecoder);
loader.load(GOLF.url, gltf => {
  try {
    $('#loadtext').textContent = 'Fitting the engine bay, gearbox and hybrid parts…';
    const meas = buildCar(gltf.scene);
    buildBay(meas);
    buildHybridParts();
    // bonnet up by default, so the bay reads at a glance
    const bon = byId.panel_bonnet; if (bon) bon.obj.rotation.x = HINGE.panel_bonnet.ang * DEG;
    buildTree(); applyStep(); setOpacity(+$('#xray').value); select('emotor', false);
    $('#loading').hidden = true;
  } catch (e) { console.error(e); $('#loadtext').textContent = 'The car loaded but could not be assembled. Reload to try again.'; }
}, x => { const t = x.total || 6570544; $('#loadtext').textContent = `Loading the Golf · ${(x.loaded / 1048576).toFixed(1)} of ${(t / 1048576).toFixed(1)} MB`; $('#bar').style.transform = `scaleX(${Math.min(1, x.loaded / t).toFixed(3)})`; },
  e => { console.error(e); $('#loadtext').textContent = 'The Golf could not be loaded. Check the connection and reload.'; });
tick();
