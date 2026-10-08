import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { GTAOPass } from 'three/addons/postprocessing/GTAOPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { FLEET, classifyMesh } from './fleet.js';
import { measureCar, buildPowertrain } from './powertrain.js';
import { buildEngineBayDetail } from './engine-bay-detail.js';
import { buildInnerApron } from './engine-bay-shell.js';
import { buildTransmission } from './transmission-detail.js';
import { extractFrontBumper } from './front-bumper.js';
import { buildHybrid, buildEngineStrip, buildDGEAExternals } from './hybrid-parts.js';
import { TOOLS, SPEC, toolLabel, buildCarFasteners } from './jobs.js';
import { buildFrontCorners } from './front-corner.js';

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
/* studio rig from the Golf Workshop garage: key with soft shadows, cool fill, warm rim */
const key = new THREE.DirectionalLight(0xffffff, 1.7); key.position.set(4.5, 7.5, 5.5); key.castShadow = true;
key.shadow.mapSize.set(2048, 2048); Object.assign(key.shadow.camera, { left: -5, right: 5, top: 5, bottom: -5, near: 0.5, far: 26 });
key.shadow.bias = -0.0012; key.shadow.normalBias = 0.02; key.shadow.radius = 6;
const fill = new THREE.DirectionalLight(0xbfd4ff, 0.42); fill.position.set(-6, 4.6, -4);
const rim = new THREE.DirectionalLight(0xffe9cf, 0.65); rim.position.set(-2, 3.8, -7);
const under = new THREE.DirectionalLight(0xffffff, 0.35); under.position.set(1, -4, 2);   // a work lamp under the lift
scene.add(key, fill, rim, under, new THREE.AmbientLight(0xffffff, 0.12));
function radialTexture(stops) {
  const c = document.createElement('canvas'); c.width = c.height = 256;
  const g = c.getContext('2d'), gr = g.createRadialGradient(128, 128, 0, 128, 128, 128);
  for (const [at, col] of stops) gr.addColorStop(at, col);
  g.fillStyle = gr; g.fillRect(0, 0, 256, 256);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}
const flat = (geo, mat, y) => { const m = new THREE.Mesh(geo, mat); m.rotation.x = -Math.PI / 2; m.position.y = y; m.renderOrder = -1; scene.add(m); return m; };
flat(new THREE.CircleGeometry(9, 64), new THREE.MeshStandardMaterial({ color: 0x7d858c, roughness: 0.86, metalness: 0.05 }), -0.002).receiveShadow = true;
flat(new THREE.PlaneGeometry(16, 16), new THREE.MeshBasicMaterial({ map: radialTexture([[0, 'rgba(255,255,255,.18)'], [0.5, 'rgba(255,255,255,.06)'], [1, 'rgba(255,255,255,0)']]), transparent: true, depthWrite: false }), 0);
flat(new THREE.PlaneGeometry(30, 30), new THREE.ShadowMaterial({ opacity: 0.45, depthWrite: false }), 0.001).receiveShadow = true;
const contact = flat(new THREE.PlaneGeometry(2.3, 5.0), new THREE.MeshBasicMaterial({ map: radialTexture([[0, 'rgba(0,0,0,.7)'], [0.55, 'rgba(0,0,0,.38)'], [1, 'rgba(0,0,0,0)']]), transparent: true, depthWrite: false }), 0.003);

/* workshop surfaces (from the Golf Workshop): fine grain and casting pores in the
   roughness and normal maps, so cast alloy, machined faces and plastics read apart */
function surfaceMaps(seed, repeat) {
  const n = 64, rough = new Uint8Array(n * n * 4), norm = new Uint8Array(n * n * 4);
  let st = seed >>> 0; const rr = () => ((st = (st * 1664525 + 1013904223) >>> 0) / 4294967295);
  for (let i = 0; i < n * n; i++) {
    const grain = rr() - 0.5, pore = rr() < 0.035 ? -34 : 0, v = Math.max(80, Math.min(245, 190 + grain * 44 + pore));
    rough.set([v, v, v, 255], i * 4); norm.set([128 + Math.round(grain * 18), 128 + Math.round((rr() - 0.5) * 18), 255, 255], i * 4);
  }
  const out = {};
  for (const [k, d] of [['roughness', rough], ['normal', norm]]) {
    const t = new THREE.DataTexture(d, n, n, THREE.RGBAFormat); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(repeat, repeat);
    t.colorSpace = THREE.NoColorSpace; t.needsUpdate = true; out[k] = t;
  }
  return out;
}
let SURF = null;
function materialFactory(color, options = {}, finish = 'cast') {
  SURF ||= { cast: surfaceMaps(0x5ca57, 7), plastic: surfaceMaps(0x91a57, 9), brushed: surfaceMaps(0xb4a55, 12), rubber: surfaceMaps(0x7abb3, 8) };
  const maps = SURF[finish] || SURF.cast, m = new THREE.MeshPhysicalMaterial({ color, ...options });
  if (!m.transparent) { m.roughnessMap = maps.roughness; m.normalMap = maps.normal; const k = finish === 'cast' ? 0.24 : finish === 'plastic' ? 0.13 : finish === 'rubber' ? 0.18 : 0.08; m.normalScale.set(k, k); }
  if (finish === 'paint') { m.clearcoat = 0.78; m.clearcoatRoughness = 0.19; }
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
  p.rem = V(0, 0, 0); p.removed = false; p.box = new THREE.Box3().setFromObject(p.obj);
  const hg = HINGE[p.id]; if (hg) { p.hinge = hg; p.ang = 0; p.angT = 0; }
  if (SPEC[p.id]) {
    p.fx = SPEC[p.id]; p.bolts = [...p.obj.children];
    p.bolts.forEach((b, i) => { b.userData.bi = i; b.userData.base = b.position.clone(); b.userData.state = 'in'; b.userData.t = 0;
      b.userData.axis = new THREE.Vector3(0, 1, 0).applyEuler(b.rotation).normalize(); b.traverse(o => { if (o.isMesh) o.userData.real = o.material; }); });
  }
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
  // the model's front brakes are the GTI's (red four-pot look, big disc): the eHybrid corner in front-corner.js replaces them
  for (const id of ['rotor_fl', 'rotor_fr', 'caliper_fl', 'caliper_fr']) { (by[id] || []).forEach(m => m.removeFromParent()); delete by[id]; }
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
  try { const ap = new THREE.Group(); ap.add(buildInnerApron(1, materialFactory), buildInnerApron(-1, materialFactory)); carRoot.add(ap);
    register({ id: 'inner_wings', name: 'Inner wings and strut towers', sys: 'body', obj: ap, ex: V(0, 0.3, 0), ...info({ note: 'Constructed teaching geometry from the Golf Workshop bay. The strut top mounts bolt up through the tower tops.' }) }); } catch (e) { /* dressing */ }
  bay.group.getObjectByName('bellhousing-starter-interface')?.removeFromParent();   // no starter on the eHybrid
  bayG.updateMatrixWorld(true);
  // the bay's one-piece engine and its covers give way to the DGEA built in pieces
  const REPLACED = ['engine-long-block', 'moulded-four-coil-valve-cover', 'four-coil-ignition-assembly', 'cosmetic-engine-cover-removable', 'intake-manifold', 'airbox-assembly', 'airbox-to-throttle-duct', 'engine-wiring-harness', 'accessory-drive', 'battery-positive-cable-to-starter'];
  for (const c of [...bay.group.children]) {
    if (REPLACED.includes(c.name)) { c.removeFromParent(); continue; }
    const d = BAY_INFO[c.name] || [c.name.replace(/-/g, ' '), {}, [0, 0, 0]];
    bayG.attach(c);
    register({ id: c.name, name: d[0], sys: 'bay', obj: c, ex: V(...d[2]), ...info({ note: 'Constructed teaching geometry from the Golf Workshop bay, not OEM CAD.', ...d[1] }) });
  }
  const tx = buildTransmission({ materialFactory });
  bayG.add(tx.group); bayG.updateMatrixWorld(true);
  for (const c of [...tx.group.children]) {
    if (c.name.startsWith('driveshaft')) { c.removeFromParent(); continue; }   // replaced by the photo-modelled shafts in front-corner.js
    const d = TX_INFO[c.name] || [c.name.replace(/-/g, ' '), {}, [-0.4, 0, 0]];
    bayG.attach(c);
    register({ id: c.name, name: d[0], sys: c.name.startsWith('driveshaft') ? 'gearbox' : 'gearbox', obj: c, ex: V(...d[2]), ...info({ note: 'Constructed teaching geometry: dimensions and routing illustrative, not OEM CAD.', ...d[1] }) });
  }
  if (meas) {
    const pt = buildPowertrain({ engine: 'I4', mount: 'trans', drive: 'FWD', front: 'strut', rear: 'multilink', turbo: true }, meas, { engine: true, rotors: true });
    const rear = new THREE.Group(); carRoot.add(rear);
    // the generic front struts give way to the corners modelled from the removed eHybrid corner
    for (const c of [...pt.suspension.children]) { const b = new THREE.Box3().setFromObject(c); if (b.getCenter(V(0, 0, 0)).z <= 0) rear.add(c); }
    register({ id: 'susp_rear', name: 'Rear suspension: multi-link, springs, dampers, subframe', sys: 'susp', obj: rear, ex: V(0, -0.45, -0.15), ...info({ note: 'The eHybrid uses the multi-link rear (est. for this trim). Constructed geometry.' }) });
  }
}

/* ───────── eHybrid parts and the engine strip set ───────── */
function buildHybridParts() {
  const hy = buildHybrid(materialFactory);
  for (const p of hy.parts) { carRoot.add(p.obj); register({ ...p, ...info({ ...p, tags: p.tags }) }); }
  const st = buildEngineStrip(materialFactory, hy.M);
  for (const p of st.parts) { carRoot.add(p.obj); register({ ...p, ...info({ ...p, tags: p.tags }), hidden: false }); }
  for (const p of buildDGEAExternals(materialFactory, hy.M).parts) { carRoot.add(p.obj); register({ ...p, ...info({ ...p, tags: p.tags }) }); }
  byId.blk.note = 'Engine code DGEA on the Golf 8 / Leon Mk4 eHybrid (check the code label on the block). ' + byId.blk.note;
  Object.assign(BLOCK, { dgea_intake: ['bolts_intake', 'dgea_airbox'], dgea_mount: ['bolts_mount'], dgea_coils: ['dgea_airbox'], dgea_turbo: ['dgea_airbox'] });
}

/* ───────── front corners: strut, housing, link, bearing, brake, drive shaft ───────── */
function buildCorners() {
  const ctr = k => byId['wheel_' + k] ? byId['wheel_' + k].box.getCenter(V(0, 0, 0)) : V(k === 'fl' ? 0.764 : -0.764, 0.315, 1.3157);
  const fb = id => byId[id] ? new THREE.Box3().setFromObject(byId[id].obj) : null;
  const r = fb('cv-output-right'), l = fb('cv-output-left');
  const flanges = { fl: r ? r.min.x + 0.011 : -0.276, fr: l ? l.max.x - 0.011 : -0.575 };
  for (const p of buildFrontCorners(materialFactory, { centres: { fl: ctr('fl'), fr: ctr('fr') }, flanges })) {
    carRoot.add(p.obj);
    if (p.host) {
      const f = SPEC[p.id], h = byId[p.host];
      register({ ...p, ex: h.ex.clone(), ...info({ name: f.label, qty: p.obj.children.length, size: toolLabel(f.tool), conf: 'pub', note: f.note, tags: h.tags.includes('ds') ? ['fastener', 'ds'] : ['fastener'] }) });
    } else register({ ...p, ...info(p) });
  }
  for (const k of ['fl', 'fr']) {
    const K = id => id + '_' + k, W = 'wheel_' + k;
    Object.assign(BLOCK, {
      [K('caliper')]: [W, K('bolts_caliper')], [K('pads')]: [K('caliper')], [K('carrier')]: [K('caliper'), K('pads'), K('bolts_carrier')],
      [K('disc')]: [K('carrier'), K('screw_disc')], [K('hose')]: [K('bolt_banjo'), K('bolt_hosebracket')], [K('abs')]: [K('bolt_abs')],
      [K('splash')]: [K('disc'), K('bolts_splash')], [K('bearing')]: [K('disc'), K('splash'), K('bolts_bearing'), K('bolt_hub'), K('abs')],
      [K('ds')]: [K('bolt_hub'), K('bolts_dsflange'), K('nuts_bj')],
      [K('knuckle')]: [K('bearing'), K('carrier'), K('abs'), K('bolt_strutclamp'), K('nut_bj'), K('nut_tre')],
      [K('bj')]: [K('nuts_bj'), K('nut_bj')], [K('tre')]: [K('nut_tre')], [K('droplink')]: [K('nuts_droplink')], [K('arm')]: [K('bolts_arm'), K('nuts_bj')],
      [K('strut')]: [W, K('bolts_topmount'), K('bolt_strutclamp'), K('nuts_droplink'), K('bolt_hosebracket')],
      // fasteners you can only reach with something else off
      [K('bolts_caliper')]: [W], [K('bolt_hub')]: [W], [K('bolts_carrier')]: [K('caliper')], [K('screw_disc')]: [W], [K('bolts_splash')]: [K('disc')],
      [K('bolts_bearing')]: [K('bolt_hub'), K('disc')], [K('bolt_abs')]: [W], [K('bolt_banjo')]: [W], [K('bolt_hosebracket')]: [W],
      [K('bolt_strutclamp')]: [W], [K('nut_bj')]: [W], [K('nuts_bj')]: [W], [K('nut_tre')]: [W], [K('nuts_droplink')]: [W],
    });
  }
  BLOCK.arb_f = ['droplink_fl', 'droplink_fr'];
}

/* ───────── service procedure: engine out, strip, refit ───────── */
const has = (p, t) => p.tags.includes(t);
const TAG_MOVE = (tag, v, s) => parts.forEach(p => { if (has(p, tag)) s[p.id].o.add(v); });
const TAG_HIDE = (tag, s) => parts.forEach(p => { if (has(p, tag)) s[p.id].h = true; });
const STEPS = [
  { t: 'Car in the workshop', d: 'Everything fitted, bonnet up. Next takes the engine, hybrid module and gearbox out the way VW workshops do it on a transverse Golf: down and out from underneath, with the front end in its service position.', f: () => {} },
  { t: 'Make the high-voltage system safe', hv: true, d: 'Everything in orange carries high voltage. Before any work in the bay, the HV system is switched off and locked out, then the 12 V battery is disconnected.', f: () => {} },
  { t: 'Bonnet and bumper off', d: 'Remove the bonnet for access and take off the front bumper cover. The DGEA has no separate engine cover: the air box sits on top.', f: s => { TAG_MOVE('bonnet', V(0, 0.6, 0), s); TAG_HIDE('bonnet', s); TAG_MOVE('bumper', V(0, 0, 0.6), s); TAG_HIDE('bumper', s); TAG_MOVE('cover', V(0, 0.5, 0), s); TAG_HIDE('cover', s); } },
  { t: 'Air box, 12 V battery and coolant tank out', d: 'Drain the coolant. Remove the air filter box and intake duct, the 12 V battery with its cables, and the coolant expansion tank.', f: s => { for (const t of ['airbox', 'battery12', 'reservoir']) { TAG_MOVE(t, V(0, 0.5, 0), s); TAG_HIDE(t, s); } } },
  { t: 'Cooling pack to service position', d: 'Disconnect the radiator hoses. Pull the radiator and condenser pack forward on its carrier so the engine has room to drop.', f: s => { TAG_MOVE('hose', V(0, 0.3, 0.2), s); TAG_HIDE('hose', s); TAG_MOVE('coolpack', V(0, 0, 0.5), s); } },
  { t: 'Disconnect HV cables and exhaust', hv: true, d: 'With the system made safe, unplug the HV cable at the inverter. Split the downpipe from the turbocharger and drop the front of the exhaust.', f: s => { TAG_MOVE('hvcable', V(0, -0.06, 0), s); TAG_MOVE('exhaust', V(0, -0.12, 0), s); } },
  { t: 'Raise the car, drive shafts out', lift: true, d: 'Raise the car on the lift. Undo the drive-shaft flange bolts at the gearbox and the hub bolts, swing the wheel bearing housings out and pull both shafts.', f: s => { parts.forEach(p => { if (has(p, 'ds')) { s[p.id].o.add(V(p.id.endsWith('_fl') ? 0.12 : -0.12, -0.3, 0)); s[p.id].h = true; } }); } },
  { t: 'Lower engine, hybrid module and gearbox', d: 'Support the assembly on an engine table, take out the pendulum support and the engine and gearbox mounts, and lower it out of the bay.', f: s => TAG_MOVE('pt', V(0, -0.78, 0), s) },
  { t: 'Roll it out', d: 'Roll the table forward, clear of the car.', f: s => TAG_MOVE('pt', V(0, 0, 2.0), s) },
  { t: 'Split engine from hybrid module and gearbox', d: 'Undo the twelve engine-to-module flange bolts, slide the engine off and mount it on an engine stand. Replace the module O-rings on refit.', f: s => TAG_MOVE('engine', V(0.55, 0.55, 0), s) },
  { t: 'Strip the engine on the stand', strip: true, d: 'The turbo, intake manifold and intercooler, coils, filler cap, mount bracket, pulley, flywheel, electric pump and loom are set aside. Now take the engine down part by part: tap a part, then Remove. It will tell you what has to come off first. Or use Strip in order to watch the sequence. Renew every seal and every stretch bolt on rebuild; torque values come from erWin.', f: s => { parts.forEach(p => { if (has(p, 'longblock')) s[p.id].h = true; if (has(p, 'strip')) s[p.id].h = false; }); } },
];
let step = 0, reversing = false, liftT = 0, liftY = 0;
const LIFT = 0.95;
function applyStep() {
  poke();
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
  const onStand = !!STEPS[step].strip;
  if (!onStand) parts.forEach(p => { if (has(p, 'strip') && p.removed) { p.removed = false; } });
  $('#stripbtns').hidden = !onStand;
  refreshRows(); if (selected) renderSheet(selected);
}
$('#next').onclick = () => { if (!reversing && step === STEPS.length - 1) reversing = true; if (reversing) step = Math.max(0, step - 1); else step++; applyStep(); };
$('#prev').onclick = () => { if (reversing) { step = Math.min(STEPS.length - 1, step + 1); if (step === STEPS.length - 1) reversing = false; } else step = Math.max(0, step - 1); applyStep(); };
$('#reset').onclick = () => { reversing = false; step = 0; refitEverything(); applyStep(); };

/* ───────── remove and refit, in workshop order ─────────
   BLOCK[id] lists what has to come off before `id` can. Refit runs the same
   rules backwards: a part goes back on only once everything that sits under it
   is back. Removed parts are laid on the floor beside the car; engine parts on
   the stand are laid out round it. */
const FIXED = new Set(['body', 'inner_wings', 'glazing', 'cabin', 'engine-bay-structure', 'engine-long-block', 'gearbox-case', 'bellhousing', 'integrated-front-differential', 'blk', 'subframe_f', 'susp_rear', 'moulded-four-coil-valve-cover']);
const BLOCK = {
  // engine on the stand
  cam_cover: ['bolts_cam', 'spark_plugs'], seal_cam: ['cam_cover'], timing: ['timing_cover'], camshafts: ['cam_cover', 'timing'],
  valves: ['camshafts'], bolts_head: ['camshafts'], coolant_pump: ['timing'], seal_coolant_pump: ['coolant_pump'],
  head: ['bolts_head', 'valves', 'injectors', 'coolant_pump'], head_gasket: ['head'],
  sump: ['bolts_sump'], seal_sump: ['sump'], oil_pump: ['sump'], pistons: ['head_gasket', 'oil_pump'],
  seal_crank_belt: ['timing'], bolts_main: ['sump'], ladder: ['bolts_main'], crankshaft: ['ladder', 'pistons', 'seal_crank_belt', 'seal_crank_fly'],
  // hybrid and fuel
  inverter: ['bolts_inverter', 'hv_cable_motor'], seal_inverter: ['inverter'], emotor: ['bolts_emotor', 'hv_cable_motor'], seal_emotor: ['emotor'],
  hv_battery: ['bolts_battery', 'hv_cable_battery', 'seats'], seal_battery: ['hv_battery'], fuel_tank: ['bolts_tank', 'exhaust_rear'],
  // engine bay
  'battery-assembly': ['battery-negative-earth-lead', 'battery-positive-cable-to-starter'],
  'four-coil-ignition-assembly': ['cosmetic-engine-cover-removable'], 'intake-manifold': ['cosmetic-engine-cover-removable', 'airbox-to-throttle-duct'],
  'airbox-assembly': ['airbox-to-throttle-duct'], 'radiator-condenser-cooling-pack': ['radiator-upper-hose', 'radiator-lower-hose', 'bumper_f'],
  'coolant-expansion-reservoir': ['coolant-degas-hose'],
};
const offCar = p => p.removed || p.hideT;
const nameOf = id => byId[id]?.name.replace(/,.*$/, '') || id;
function whyNotRemove(p) {
  if (p.fx?.needOpen && byId[p.fx.needOpen] && Math.abs(byId[p.fx.needOpen].angT) < 0.01) return `Open the ${nameOf(p.fx.needOpen).toLowerCase()} first, and support it.`;
  if (FIXED.has(p.id)) return `${p.name} stays put: it is the base the other parts are fitted to.`;
  if (has(p, 'strip') && !STEPS[step].strip) return 'Engine internals come out on the engine stand. Run the job to the last step first.';
  if (has(p, 'hv') && step < 1) return 'High voltage: make the HV system safe first (job step 2).';
  const left = (BLOCK[p.id] || []).filter(b => byId[b] && !offCar(byId[b]));
  return left.length ? `Remove first: ${left.map(nameOf).join(', ')}.` : '';
}
function whyNotRefit(p) {
  const under = Object.entries(BLOCK).filter(([id, bs]) => bs.includes(p.id) && byId[id] && byId[id].removed).map(([id]) => id);
  return under.length ? `Refit first: ${under.map(nameOf).join(', ')}.` : '';
}
/* ───────── tools and individual fasteners ───────── */
let tool = 'hand', tqSet = 8, angSet = 90;
const STATE_MAT = {
  loose: new THREE.MeshStandardMaterial({ color: 0xf08a24, metalness: 0.6, roughness: 0.4, emissive: 0x3a1a00, emissiveIntensity: 0.5 }),
  snug: new THREE.MeshStandardMaterial({ color: 0xe6c534, metalness: 0.7, roughness: 0.35, emissive: 0x302600, emissiveIntensity: 0.4 }),
  torqued: new THREE.MeshStandardMaterial({ color: 0x7bd88f, metalness: 0.6, roughness: 0.4, emissive: 0x0d3318, emissiveIntensity: 0.4 }),
};
function paintBolt(b) { const st = b.userData.state; b.traverse(o => { if (o.isMesh) o.material = STATE_MAT[st] || o.userData.real; }); }
const allOut = p => p.bolts.every(b => b.userData.state === 'out');
const allIn = p => p.bolts.every(b => b.userData.state === 'in');
function boltAction(p, b, quiet) {
  const st = b.userData.state, need = p.fx.tool, say = (m, w) => { if (!quiet) toast(m, w); return false; };
  if (st === 'in') {
    if (tool === 'tq' || tool === 'ang') return say('That fastener is already tight. Pick the tool that undoes it: ' + toolLabel(need) + '.', true);
    if (tool !== need) return say(`Wrong tool: ${p.fx.label.toLowerCase()} take the ${toolLabel(need)}. A near-fit socket or bit rounds the head off.`, true);
    const why = whyNotRemove(p); if (why) return say(why, true);
    b.userData.state = 'out'; b.userData.t = 0; paintBolt(b); poke();
    if (allOut(p)) { p.removed = true; refreshRows(); say(`${p.fx.label}: all ${p.bolts.length} out.` + (p.fx.renew ? ' These are renewed: new ones go in on refit.' : '')); }
    return true;
  }
  if (st === 'loose') {
    if (tool === 'tq' || tool === 'ang') return say('Run it in first with the ' + toolLabel(need) + ', then torque it.', true);
    if (tool !== need) return say(`Wrong tool: use the ${toolLabel(need)}.`, true);
    b.userData.state = 'snug'; paintBolt(b); poke(); return true;
  }
  if (st === 'snug') {
    if (tool !== 'tq') return say('Snug. Now the torque wrench' + (p.fx.nm ? `, set to ${p.fx.nm} Nm.` : '.'), true);
    if (p.fx.nm == null) { b.userData.state = p.fx.deg ? 'torqued' : 'in'; paintBolt(b); poke(); return say('No torque value for these in the data: take the figure from erWin for this car.'), true; }
    if (Math.abs(tqSet - p.fx.nm) > 0.25) return say(tqSet > p.fx.nm ? `STOP: ${tqSet} Nm is over the ${p.fx.nm} Nm spec. Over-torque stretches the bolt or strips the thread.` : `Under-torqued: ${tqSet} Nm. The spec is ${p.fx.nm} Nm.`, true);
    b.userData.state = p.fx.deg ? 'torqued' : 'in'; paintBolt(b); poke(); return true;
  }
  if (st === 'torqued') {
    if (tool !== 'ang') return say(`Torque stage done. Now the angle gauge: a further ${p.fx.deg}°.`, true);
    if (angSet !== p.fx.deg) return say(`Set the angle gauge to ${p.fx.deg}°, not ${angSet}°.`, true);
    b.userData.state = 'in'; paintBolt(b); poke(); return true;
  }
  return false;
}
function fitBolts(p) {
  const why = whyNotRefit(p); if (why) { toast(why, true); return; }
  p.bolts.forEach(b => { b.userData.state = 'loose'; b.userData.t = 0; paintBolt(b); });
  p.removed = false; poke(); refreshRows();
  toast((p.fx.renew ? 'New bolts fitted by hand. ' : 'Bolts started by hand. ') + `Now run them in with the ${toolLabel(p.fx.tool)}, then torque${p.fx.nm ? ' to ' + p.fx.nm + ' Nm' : ''}${p.fx.deg ? ' + ' + p.fx.deg + '°' : ''}.`);
}
function allBolts(p) { let n = 0; for (const b of p.bolts) if (b.userData.state !== 'out' && boltAction(p, b, true)) n++; if (!n) { const b = p.bolts.find(x => x.userData.state !== 'out'); if (b) boltAction(p, b, false); } else toast(`${n} done with the ${toolLabel(tool)}.`); renderSheet(p.id); }
function buildTray() {
  const tray = $('#tray'); tray.textContent = '';
  for (const t of TOOLS) {
    const b = document.createElement('button'); b.className = 'tool'; b.dataset.tool = t.k; b.textContent = t.label; b.setAttribute('aria-pressed', String(t.k === tool));
    b.onclick = () => { tool = t.k; tray.querySelectorAll('.tool').forEach(x => x.setAttribute('aria-pressed', String(x.dataset.tool === tool))); $('#tqbox').hidden = tool !== 'tq'; $('#angbox').hidden = tool !== 'ang'; };
    tray.append(b);
  }
  $('#tq').oninput = e => { tqSet = +e.target.value; $('#tqv').textContent = tqSet; };
  $('#ang').onchange = e => { angSet = +e.target.value; };
}
let toastT = 0;
function toast(msg, warn) { const t = $('#toast'); t.textContent = msg; t.className = warn ? 'warn' : ''; t.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => t.hidden = true, 3600); }
function floorSpot(p) {
  // beside the car, on the side it comes off; each side fills slot by slot
  const c = p.box.getCenter(V(0, 0, 0)), sz = p.box.getSize(V(0, 0, 0));
  let L = V(p.ex.x, 0, p.ex.z); if (L.length() < 0.15) L.set(c.x >= 0 ? 1 : -1, 0, 0);
  const side = Math.abs(L.x) >= Math.abs(L.z) ? (L.x > 0 ? 'L' : 'R') : (L.z > 0 ? 'F' : 'B');
  const used = new Set(parts.filter(q => q.removed && q.side === side).map(q => q.slot));
  let slot = 0; while (used.has(slot)) slot++;
  p.side = side; p.slot = slot;
  const t = side === 'L' ? V(1.45 + sz.x / 2, 0, 1.9 - (slot % 7) * 0.62 - Math.floor(slot / 7) * 0.31) : side === 'R' ? V(-1.45 - sz.x / 2, 0, 1.9 - (slot % 7) * 0.62 - Math.floor(slot / 7) * 0.31)
    : side === 'F' ? V(-1.3 + (slot % 6) * 0.52, 0, 2.85 + sz.z / 2 + Math.floor(slot / 6) * 0.5) : V(-1.3 + (slot % 6) * 0.52, 0, -2.85 - sz.z / 2 - Math.floor(slot / 6) * 0.5);
  p.remBase = V(t.x - c.x, 0.012 - p.box.min.y, t.z - c.z);
}
function removePart(id, quiet) {
  const p = byId[id]; if (!p || p.removed) return false;
  const why = whyNotRemove(p); if (why) { if (!quiet) { toast(why, true); flash(BLOCK[id] || []); } return false; }
  if (p.hinge) p.angT = 0;
  if (!has(p, 'strip')) floorSpot(p);
  p.removed = true; poke(); refreshRows();
  if (!quiet) toast(`${p.name}: removed.` + (has(p, 'seal') ? ' Fit a new one on rebuild.' : /stretch/.test(p.size + p.note) ? ' Stretch bolts: fit new ones on rebuild.' : ''));
  return true;
}
function refitPart(id, quiet) {
  const p = byId[id]; if (!p || !p.removed) return false;
  const why = whyNotRefit(p); if (why) { if (!quiet) toast(why, true); return false; }
  p.removed = false; poke(); refreshRows();
  if (!quiet) toast(`${p.name}: refitted.` + (has(p, 'seal') ? ' New seal fitted.' : has(p, 'fastener') ? ' Torque to the erWin value.' : ''));
  return true;
}
function refitEverything() { parts.forEach(p => { p.removed = false; if (p.bolts) p.bolts.forEach(b => { b.userData.state = 'in'; paintBolt(b); }); if (p.hinge) p.angT = p.id === 'panel_bonnet' ? HINGE.panel_bonnet.ang * DEG : 0; }); poke(); refreshRows(); }
function flash(ids) { ids.forEach(id => { const r = $('#row_' + id); if (r) { r.classList.add('flash'); setTimeout(() => r.classList.remove('flash'), 1500); } }); }
function toggleHinge(id) { const p = byId[id]; if (!p?.hinge || p.removed || p.hideT) return; p.angT = Math.abs(p.angT) > 0.01 ? 0 : p.hinge.ang * DEG; poke(); if (selected === id) renderSheet(id); }
let seq = null;
function runSequence(kind) {
  clearInterval(seq);
  const strip = parts.filter(p => has(p, 'strip') && !FIXED.has(p.id));
  seq = setInterval(() => {
    const next = kind === 'strip' ? strip.find(p => !p.removed && !whyNotRemove(p)) : [...strip].reverse().find(p => p.removed && !whyNotRefit(p));
    if (!next) { clearInterval(seq); toast(kind === 'strip' ? 'Engine stripped. Seals and stretch bolts are marked for renewal.' : 'Engine rebuilt. Torque every fastener to the erWin value.'); return; }
    if (next.fx) { if (kind === 'strip') { next.bolts.forEach(b => { b.userData.state = 'out'; paintBolt(b); }); next.removed = true; } else { next.bolts.forEach(b => { b.userData.state = 'in'; paintBolt(b); }); next.removed = false; } refreshRows(); poke(); }
    else kind === 'strip' ? removePart(next.id, true) : refitPart(next.id, true);
    select(next.id, false);
  }, REDUCED ? 30 : 420);
}
$('#stripall').onclick = () => runSequence('strip');
$('#rebuildall').onclick = () => runSequence('rebuild');
$('#refitall').onclick = () => { clearInterval(seq); refitEverything(); toast('Everything refitted.'); };

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
      const cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = true; cb.id = 'cb_' + p.id; cb.setAttribute('aria-label', 'Show ' + p.name); cb.onchange = () => { p.vis = cb.checked; poke(); };
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
function renderSheet(id) {
  const p = byId[id], acts = $('#acts'); if (!p || !acts) return; acts.textContent = '';
  const b = (label, fn, pri) => { const e = document.createElement('button'); e.className = 'b' + (pri ? ' pri' : ''); e.textContent = label; e.onclick = fn; acts.append(e); };
  if (p.hinge && !p.removed && !p.hideT) b(Math.abs(p.angT) > 0.01 ? 'Close' : 'Open', () => toggleHinge(id));
  if (FIXED.has(id)) { const t = document.createElement('span'); t.className = 'small'; t.textContent = 'Fixed: the base other parts fit to.'; acts.append(t); return; }
  if (p.fx) {
    const n = k => p.bolts.filter(x => x.userData.state === k).length;
    const st = document.createElement('div'); st.className = 'boltstate';
    st.innerHTML = `<b>${toolLabel(p.fx.tool)}</b> · ${p.fx.nm != null ? p.fx.nm + ' Nm' : 'torque: erWin'}${p.fx.deg ? ' + ' + p.fx.deg + '°' : ''}${p.fx.renew ? ' · <span class="renew">renew</span>' : ''}<br>${n('in')} tight · ${n('out')} out${n('loose') ? ' · ' + n('loose') + ' loose' : ''}${n('snug') ? ' · ' + n('snug') + ' snug' : ''}${n('torqued') ? ' · ' + n('torqued') + ' need the angle' : ''}`;
    acts.append(st);
    if (allOut(p)) b(p.fx.renew ? 'Fit new bolts by hand' : 'Fit bolts by hand', () => { fitBolts(p); renderSheet(id); }, true);
    else b(`Use the ${toolLabel(tool)} on all`, () => allBolts(p), true);
    const t = document.createElement('span'); t.className = 'small'; t.textContent = 'Or pick a tool below the car and tap each fastener.'; acts.append(t);
    return;
  }
  if (p.removed) b('Refit', () => { refitPart(id); renderSheet(id); }, true); else if (!p.hideT) b('Remove', () => { removePart(id); renderSheet(id); }, true);
  const held = Object.entries(BLOCK).length && (BLOCK[id] || []).map(x => byId[x]).filter(q => q?.fx);
  for (const q of held || []) { const t = document.createElement('button'); t.className = 'b'; t.textContent = `${q.fx.label}: ${q.bolts.filter(x => x.userData.state !== 'out').length}/${q.bolts.length} in`; t.onclick = () => select(q.id, true); acts.append(t); }
}
function refreshRows() { parts.forEach(p => { const r = $('#row_' + p.id); if (r) r.classList.toggle('gone', p.removed || (p.hideT && !has(p, 'strip'))); }); const n = parts.filter(p => p.removed).length; $('#removed').textContent = n ? `${n} removed` : ''; }
function select(id, frame) {
  poke();
  if (selected) { setHighlight(selected, false); $('#row_' + selected)?.classList.remove('sel'); }
  selected = id; const p = byId[id]; if (!p) return;
  setHighlight(id, true);
  const row = $('#row_' + id); if (row) { row.classList.add('sel'); row.closest('details').open = true; row.scrollIntoView({ block: 'nearest' }); }
  const box = $('#info'); box.textContent = '';
  const h = document.createElement('div'); h.className = 'pname'; h.textContent = p.name; box.append(h);
  const dl = document.createElement('dl'); dl.className = 'kv';
  const tqTxt = p.fx ? (p.fx.nm != null ? `${p.fx.nm} Nm${p.fx.deg ? ' + ' + p.fx.deg + '°' : ''} (${p.fx.src === 'man' ? 'VW manual data' : p.fx.src === 'class' ? 'class value' : 'estimate'})` : 'not in the data: erWin') : (BLOCK[id] || []).some(x => byId[x]?.fx) ? 'on its bolts: see below' : 'not included (erWin)';
  for (const [k, v] of [['System', SYS[p.sys]], ['Quantity', String(p.qty)], ['Material', p.mat || '—'], [p.fx ? 'Tool' : 'Size', p.fx ? toolLabel(p.fx.tool) : (p.size || '—')], ['Torque', tqTxt], ['Renew', p.fx ? (p.fx.renew ? 'yes, every time' : 'no') : (has(p, 'seal') ? 'yes, every time' : '—')], ['OEM part no.', 'not included']]) {
    const dt = document.createElement('dt'); dt.textContent = k; const dd = document.createElement('dd'); dd.textContent = v; dl.append(dt, dd);
  }
  const dt = document.createElement('dt'); dt.textContent = 'Source'; const dd = document.createElement('dd'); dd.innerHTML = confTag(p.conf); dl.append(dt, dd);
  box.append(dl);
  const n = document.createElement('p'); n.className = 'note'; n.textContent = p.note || 'Shape and position estimated.'; box.append(n);
  const acts = document.createElement('div'); acts.className = 'btns acts'; acts.id = 'acts'; box.append(acts); renderSheet(id);
  if (frame) { const b = new THREE.Box3().setFromObject(p.obj); if (!b.isEmpty()) { const c = b.getCenter(V(0, 0, 0)), r = Math.max(0.35, b.getSize(V(0, 0, 0)).length()); flyTo(c.clone().add(V(r * 1.1, r * 0.7, r * 1.3)), c); } }
}
$('#isolate').onclick = () => { poke(); if (!selected) return; const s = byId[selected].sys; parts.forEach(p => { p.vis = p.sys === s; $('#cb_' + p.id).checked = p.vis; }); };
$('#showall').onclick = () => { poke(); parts.forEach(p => { p.vis = true; $('#cb_' + p.id).checked = true; }); };
const ray = new THREE.Raycaster(), ptr = new THREE.Vector2(); let down = null;
renderer.domElement.addEventListener('pointerdown', e => down = [e.clientX, e.clientY]);
renderer.domElement.addEventListener('pointerup', e => {
  if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;
  const r = renderer.domElement.getBoundingClientRect(); ptr.set((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1);
  ray.setFromCamera(ptr, camera);
  const xr = +$('#xray').value < 0.5;
  const objs = parts.filter(p => p.obj.visible && !(xr && ['body', 'glazing', 'cabin', 'panel_bonnet', 'tailgate', 'bumper_f'].includes(p.id) || p.id.startsWith('door_') && xr)).map(p => p.obj);
  const hit = ray.intersectObjects(objs, true).find(h => h.object.userData.pid);
  if (hit) {
    const id = hit.object.userData.pid, p = byId[id];
    let o = hit.object; while (o && o.userData.bi === undefined && o.parent) o = o.parent;
    if (p.fx && o && o.userData.bi !== undefined) { select(id, false); boltAction(p, o); renderSheet(id); return; }
    select(id, false); if (p.hinge) toggleHinge(id);
  }
});

/* realistic finishes by default; the switch paints seals green and fasteners gold */
const MARK = { seal: new THREE.MeshStandardMaterial({ color: 0x1fae62, roughness: 0.6, emissive: 0x0a3a20, emissiveIntensity: 0.4 }), fastener: new THREE.MeshStandardMaterial({ color: 0xe0b83a, metalness: 0.8, roughness: 0.3, emissive: 0x3a2a00, emissiveIntensity: 0.4 }) };
function setMarkers(on) {
  const sel = selected; if (sel) setHighlight(sel, false);
  for (const p of parts) { const k = has(p, 'seal') ? 'seal' : has(p, 'fastener') ? 'fastener' : null; if (!k) continue;
    p.obj.traverse(o => { if (!o.isMesh) return; if (on) { o.userData.real ||= o.material; o.material = MARK[k]; } else if (o.userData.real) { o.material = o.userData.real; delete o.userData.real; } }); }
  if (sel) setHighlight(sel, true); poke();
}
$('#markers').onchange = e => setMarkers(e.target.checked);

/* ───────── view controls ───────── */
let explode = 0, hvPulse = false;
$('#explode').oninput = e => { explode = +e.target.value; poke(); };
$('#xray').oninput = e => { setOpacity(+e.target.value); poke(); };
function setOpacity(v) { for (const m of bodyMats) { m.transparent = v < 0.999 || m.userData.tr0; m.opacity = Math.min(m.userData.op0, v); m.depthWrite = v > 0.6; m.needsUpdate = true; } }
const VIEWS = { iso: [[4.6, 2.6, 4.8], [0, 0.55, 0.2]], side: [[6.4, 1.1, 0.1], [0, 0.6, 0]], bay: [[1.9, 1.9, 3.3], [-0.05, 0.55, 1.5]], under: [[2.4, -0.4, 2.2], [0, 0.35, 0.3]], top: [[0.01, 7.5, 0.2], [0, 0, 0.2]], bench: [[2.0, 2.15, 7.0], [0.4, 1.12, 3.45]] };
let fly = null;
function flyTo(pos, tgt) { fly = { p: pos.clone(), t: tgt.clone() }; }
document.querySelectorAll('[data-v]').forEach(b => b.onclick = () => { const [p, t] = VIEWS[b.dataset.v], up = b.dataset.v === 'bench' || b.dataset.v === 'top' ? 0 : liftT; flyTo(V(p[0], p[1] + up, p[2]), V(t[0], t[1] + up, t[2])); });
camera.position.set(...VIEWS.iso[0]); controls.target.set(...VIEWS.iso[1]);

/* ───────── loop ───────── */
const clock = new THREE.Clock();
function resize() { const w = stage.clientWidth, h = stage.clientHeight; if (renderer.domElement.width !== Math.floor(w * renderer.getPixelRatio()) || renderer.domElement.height !== Math.floor(h * renderer.getPixelRatio())) { renderer.setSize(w, h, false); camera.aspect = w / Math.max(h, 1); camera.updateProjectionMatrix(); if (composer) composer.setSize(w, h); poke(); } }
const HVC = new THREE.Color(0xff6a00);
let composer = null, gtao = null, polished = false, idleSince = 0, aoOff = new URLSearchParams(location.search).has('plain'), lastMove = 1;
function poke() { polished = false; idleSince = performance.now(); }
controls.addEventListener('change', poke);
function makeComposer() {
  const size = renderer.getDrawingBufferSize(new THREE.Vector2());
  composer = new EffectComposer(renderer, new THREE.WebGLRenderTarget(size.x, size.y, { type: THREE.HalfFloatType, samples: 4 }));
  composer.setPixelRatio(renderer.getPixelRatio()); composer.setSize(stage.clientWidth, stage.clientHeight);
  composer.addPass(new RenderPass(scene, camera));
  gtao = new GTAOPass(scene, camera, size.x, size.y);
  gtao.updateGtaoMaterial({ radius: 0.28, distanceExponent: 1.6, thickness: 1.2, scale: 1.1, samples: 16, distanceFallOff: 1, screenSpaceRadius: false });
  gtao.updatePdMaterial({ lumaPhi: 10, depthPhi: 2, normalPhi: 3, radius: 5, rings: 2, samples: 16 });
  gtao.blendIntensity = 0.95;
  composer.addPass(gtao); composer.addPass(new OutputPass());
}
function tick() {
  resize();
  const dt = Math.min(clock.getDelta(), 0.05), k = REDUCED ? 1 : 1 - Math.pow(0.0015, dt);
  liftY += (liftT - liftY) * k; carRoot.position.y = liftY; contact.material.opacity = 1 - Math.min(1, liftY / 0.6);
  let moved = false;
  for (const p of parts) {
    p.svc.lerp(p.svcT, k);
    const want = !p.removed || p.fx ? V(0, 0, 0) : has(p, 'strip') ? p.stripEx.clone() : p.remBase.clone().sub(p.svc).add(V(0, -liftY, 0));
    p.rem.lerp(want, k); if (p.rem.distanceToSquared(want) > 1e-9) moved = true;
    if (p.bolts) for (const b of p.bolts) {
      const st = b.userData.state, tgt = st === 'out' ? 0.05 : st === 'loose' ? 0.012 : 0;
      b.userData.t += (tgt - b.userData.t) * k; if (Math.abs(tgt - b.userData.t) > 1e-5) moved = true;
      b.position.copy(b.userData.base).addScaledVector(b.userData.axis, b.userData.t);
      b.rotation.y = b.userData.t * 60;
      b.visible = !(st === 'out' && b.userData.t > 0.045);
    }
    if (p.hinge) { p.ang += (p.angT - p.ang) * k; p.obj.rotation[p.hinge.axis] = p.ang; if (Math.abs(p.angT - p.ang) > 1e-4) moved = true; }
    p.obj.position.copy(p.home).add(p.svc).add(p.rem).addScaledVector(p.ex, p.removed || (has(p, 'strip') && STEPS[step].strip) ? 0 : has(p, 'strip') ? explode * 0.6 : explode);
    const gone = p.hideT && p.svc.distanceTo(p.svcT) < 0.02;
    p.obj.visible = p.vis && !gone;
  }
  if (hvPulse) { const a = 0.35 + 0.35 * Math.sin(performance.now() / 220); parts.forEach(p => { if (has(p, 'hv') && p.id !== selected) p.obj.traverse(o => { if (o.isMesh && o.material.emissive) { if (!o.userData.hvm) { o.userData.hvm = o.material; o.material = o.material.clone(); } o.material.emissive = HVC; o.material.emissiveIntensity = a; } }); }); }
  else parts.forEach(p => { if (has(p, 'hv')) p.obj.traverse(o => { if (o.isMesh && o.userData.hvm) { o.material = o.userData.hvm; delete o.userData.hvm; } }); });
  if (fly) { const f = REDUCED ? 1 : 1 - Math.pow(0.02, dt); camera.position.lerp(fly.p, f); controls.target.lerp(fly.t, f); if (camera.position.distanceTo(fly.p) < 0.01) fly = null; }
  controls.update();
  let moving = moved || !!fly || hvPulse || Math.abs(liftT - liftY) > 1e-4;
  if (!moving) for (const p of parts) if (p.svc.distanceToSquared(p.svcT) > 1e-9) { moving = true; break; }
  const now = performance.now();
  if (moving) poke();
  if (now - idleSince < 200 || aoOff) { renderer.render(scene, camera); }
  else if (!polished) { try { if (!composer) makeComposer(); composer.render(); } catch (e) { console.warn('ambient occlusion off on this GPU', e); aoOff = true; renderer.render(scene, camera); } polished = true; }
  requestAnimationFrame(tick);
}

/* ───────── load ───────── */
const loader = new GLTFLoader(); loader.setMeshoptDecoder(MeshoptDecoder);
loader.load(GOLF.url, gltf => {
  try {
    $('#loadtext').textContent = 'Fitting the engine bay, gearbox and hybrid parts…';
    const meas = buildCar(gltf.scene);
    buildBay(meas);
    buildHybridParts();
    buildCorners();
    for (const f of buildCarFasteners(byId, materialFactory)) { carRoot.add(f.obj); register({ ...f, ex: byId[f.host].ex.clone(), ...info(f) }); BLOCK[f.host] = [...(BLOCK[f.host] || []), f.id]; }
    BLOCK.timing_cover = ['bolts_timing_cover'];
    // bonnet up by default, so the bay reads at a glance
    const bon = byId.panel_bonnet; if (bon) { bon.ang = bon.angT = HINGE.panel_bonnet.ang * DEG; bon.obj.rotation.x = bon.ang; }
    buildTree(); buildTray(); applyStep(); setOpacity(+$('#xray').value); select('emotor', false);
    $('#loading').hidden = true;
    if (new URLSearchParams(location.search).has('debug')) window.__ws = { parts, byId, BLOCK, THREE, camera, controls, flyTo, select, removePart, refitPart, boltAction, fitBolts, setTool: k => { tool = k; }, setTq: (n, a) => { tqSet = n; if (a) angSet = a; } };
  } catch (e) { console.error(e); $('#loadtext').textContent = 'The car loaded but could not be assembled. Reload to try again.'; }
}, x => { const t = x.total || 6570544; $('#loadtext').textContent = `Loading the Golf · ${(x.loaded / 1048576).toFixed(1)} of ${(t / 1048576).toFixed(1)} MB`; $('#bar').style.transform = `scaleX(${Math.min(1, x.loaded / t).toFixed(3)})`; },
  e => { console.error(e); $('#loadtext').textContent = 'The Golf could not be loaded. Check the connection and reload.'; });
tick();
