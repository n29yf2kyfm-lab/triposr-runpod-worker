import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { RGBELoader } from 'three/addons/loaders/RGBELoader.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { GTAOPass } from 'three/addons/postprocessing/GTAOPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { FLEET, classifyMesh } from './fleet.js?v=11';
import { measureCar, buildPowertrain } from './powertrain.js?v=11';
import { buildEngineBayDetail } from './engine-bay-detail.js?v=11';
import { buildInnerApron } from './engine-bay-shell.js?v=11';
import { buildTransmission } from './transmission-detail.js?v=11';
import { extractFrontBumper } from './front-bumper.js?v=11';
import { buildHybrid, buildEngineStrip, buildDGEAExternals } from './hybrid-parts.js?v=11';
import { TOOLS, SPEC, toolLabel, buildCarFasteners } from './jobs.js?v=11';
import { buildFrontCorners } from './front-corner.js?v=11';
import { createTraining } from './training.js?v=11';

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
const TOUCH = matchMedia('(pointer: coarse)').matches;
controls.enableDamping = true; controls.dampingFactor = 0.12; controls.screenSpacePanning = true; controls.zoomToCursor = true;
controls.rotateSpeed = TOUCH ? 0.6 : 0.9; controls.panSpeed = 0.8; controls.zoomSpeed = TOUCH ? 0.9 : 1;
controls.minDistance = 0.35; controls.maxDistance = 8; controls.maxPolarAngle = Math.PI * 0.95;
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
/* photo studio: a seamless cyclorama, the floor sweeping up into the wall in one curve,
   as cars are photographed, so no corner shows in the paint's reflections */
const cyc = (() => {
  const pts = [new THREE.Vector2(0, 0), new THREE.Vector2(6.2, 0)];
  for (let i = 1; i <= 18; i++) { const t = i / 18 * Math.PI / 2; pts.push(new THREE.Vector2(6.2 + 2.4 * Math.sin(t), 2.4 - 2.4 * Math.cos(t))); }
  const floor = new THREE.Mesh(new THREE.LatheGeometry(pts, 128), new THREE.MeshStandardMaterial({ color: 0xd2d5d8, roughness: 0.92, metalness: 0, side: THREE.DoubleSide }));
  floor.position.y = -0.002; floor.receiveShadow = true; scene.add(floor);
  // the wall above the cove is lit from behind, like a studio's light wall: it glows and wraps the paint in soft highlights
  const wall = new THREE.Mesh(new THREE.CylinderGeometry(8.6, 8.6, 11, 128, 1, true), new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xf4f6f8, emissiveIntensity: 0.85, roughness: 1, side: THREE.DoubleSide }));
  wall.position.y = 2.4 + 5.5; scene.add(wall);
  // overhead softbox, for photos only (it would block the top view)
  const box = new THREE.Mesh(new THREE.PlaneGeometry(4.2, 2.6), new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffffff, emissiveIntensity: 2.6, side: THREE.DoubleSide }));
  box.rotation.x = Math.PI / 2; box.position.set(0, 5.4, 0.2); box.visible = false; scene.add(box);
  return { floor, wall, box };
})();
const glow = flat(new THREE.PlaneGeometry(16, 16), new THREE.MeshBasicMaterial({ map: radialTexture([[0, 'rgba(255,255,255,.18)'], [0.5, 'rgba(255,255,255,.06)'], [1, 'rgba(255,255,255,0)']]), transparent: true, depthWrite: false }), 0);
const shadowPlane = flat(new THREE.PlaneGeometry(30, 30), new THREE.ShadowMaterial({ opacity: 0.45, depthWrite: false }), 0.001); shadowPlane.receiveShadow = true;
const contact = flat(new THREE.PlaneGeometry(2.3, 5.0), new THREE.MeshBasicMaterial({ map: radialTexture([[0, 'rgba(0,0,0,.7)'], [0.55, 'rgba(0,0,0,.38)'], [1, 'rgba(0,0,0,0)']]), transparent: true, depthWrite: false }), 0.003);

/* studio light: a real photo-studio HDRI (Poly Haven, CC0) replaces the synthetic room once it arrives */
const ENV_ROT = 2.2;
new RGBELoader().load('./studio.hdr.wasm', t => {
  t.mapping = THREE.EquirectangularReflectionMapping; scene.environment = t; scene.environmentIntensity = 0.95; scene.environmentRotation.y = ENV_ROT;
  key.intensity = 1.25; fill.intensity = 0.2; rim.intensity = 0.45; poke();
}, undefined, e => console.warn('studio HDRI not loaded; the room light stays', e));

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

/* the source model's materials, corrected to real-world values: clear-coated paint,
   rubber and leather that are not metal, screens that glow */
const NONMETAL = /leather|fabric|carpet|airbag|speaker|seat|til|phong3|^tire$|_ST$|badge/i;
function realMaterials(root) {
  const done = new Set();
  root.traverse(o => { if (!o.isMesh) return; for (const m of [].concat(o.material)) { if (done.has(m)) continue; done.add(m);
    if (m.name === 'CarPaint') Object.assign(m, { metalness: 0.42, roughness: 0.3, clearcoat: 1, clearcoatRoughness: 0.03 });
    else if (/^tire$/i.test(m.name)) Object.assign(m, { metalness: 0, roughness: 0.84 });
    else if (/^display/i.test(m.name)) Object.assign(m, { metalness: 0, roughness: 0.1, emissive: new THREE.Color(0xffffff), emissiveMap: m.map, emissiveIntensity: 0.5 });
    else if (NONMETAL.test(m.name)) { m.metalness = 0; if (/leather/i.test(m.name)) m.roughness = 0.52; }
    else if (m.name === 'Atlas') m.metalness = Math.min(m.metalness, 0.45);
    m.needsUpdate = true; } });
}
/* the model ships meshopt-compressed with packed integer vertices; unpack them to plain
   floats so the path tracer (which merges raw arrays) reads true positions and normals */
function unpackVertices(root) {
  const G = ['getX', 'getY', 'getZ', 'getW'];
  root.traverse(o => { if (!o.isMesh) return; const g = o.geometry;
    for (const [name, a] of Object.entries(g.attributes)) {
      if (!a.isInterleavedBufferAttribute && !a.normalized && a.array instanceof Float32Array) continue;
      const n = a.count, k = a.itemSize, out = new Float32Array(n * k);
      for (let i = 0; i < n; i++) for (let c = 0; c < k; c++) out[i * k + c] = a[G[c]](i);
      g.setAttribute(name, new THREE.BufferAttribute(out, k));
    } });
}
function buildCar(root) {
  unpackVertices(root); realMaterials(root);
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
  for (const id of ['body', 'bumper_f', 'panel_bonnet', 'tailgate', 'door_fl', 'door_fr', 'door_rl', 'door_rr', 'cabin', 'wheel_fl', 'wheel_fr', 'wheel_rl', 'wheel_rr']) {
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
  if (byId.spark_plugs) { byId.spark_plugs.tags.push('incar'); BLOCK.spark_plugs = ['dgea_coils']; }
  Object.assign(BLOCK, { dgea_intake: ['bolts_intake', 'dgea_airbox', 'dgea_chargepipe'], dgea_mount: ['bolts_mount'], dgea_coils: ['dgea_airbox'], dgea_turbo: ['dgea_airbox', 'dgea_chargepipe'], dgea_chargepipe: ['dgea_airbox'], dgea_filler: ['dgea_airbox'] });
}

/* ───────── charging socket behind its flap, at the back of the front wing ─────────
   Found by casting a ray at the body, so it sits on the real panel surface. The flap is
   body-coloured and hinges at its front edge; the Type 2 socket sits in a recess behind it. */
let chargeLocal = null;
function buildChargePort() {
  const body = byId.body; if (!body) return;
  const meshes = []; body.obj.traverse(o => { if (o.isMesh) meshes.push(o); }); carRoot.updateMatrixWorld(true);
  let P = V(-0.865, 0.722, 1.065), n = V(-1, 0, 0);
  const hit = new THREE.Raycaster(V(-1.6, 0.722, 1.065), V(1, 0, 0), 0, 1.2).intersectObjects(meshes, false)[0];
  if (hit) { P = hit.point.clone(); n = hit.face.normal.clone().transformDirection(hit.object.matrixWorld); if (n.x > 0) n.negate(); n.y = Math.max(-0.3, Math.min(0.3, n.y)); n.normalize(); }
  const up = V(0, 1, 0).addScaledVector(n, -n.y).normalize(), fwd = new THREE.Vector3().crossVectors(up, n).normalize();
  const basis = new THREE.Matrix4().makeBasis(fwd, up, n), q = new THREE.Quaternion().setFromRotationMatrix(basis);
  const W = 0.15, H = 0.11, RR = 0.03;
  const rr = (w, h, r) => { const s = new THREE.Shape(), x = -w / 2, y = -h / 2; s.moveTo(x + r, y); s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r); s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h); s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r); s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y); return s; };
  const black = materialFactory(0x15171a, { metalness: 0, roughness: 0.7 }, 'plastic'), grey = materialFactory(0x2c2f33, { metalness: 0.05, roughness: 0.55 }, 'plastic');
  // recess and Type 2 socket
  const sg = new THREE.Group(), local = new THREE.Group(); local.position.copy(P); local.quaternion.copy(q); sg.add(local);
  const add = (g, geo, mat, z = 0, x = 0, y = 0) => { const m = new THREE.Mesh(geo, mat); m.position.set(x, y, z); m.castShadow = m.receiveShadow = true; g.add(m); return m; };
  // dark surround on the panel (the recess, seen with the flap open)
  add(local, new THREE.ExtrudeGeometry(rr(W - 0.006, H - 0.006, RR - 0.002), { depth: 0.0012, bevelEnabled: false, curveSegments: 12 }), black, 0.0008);
  const lip = rr(W - 0.006, H - 0.006, RR - 0.002); lip.holes.push(rr(W - 0.016, H - 0.016, RR - 0.007));
  add(local, new THREE.ExtrudeGeometry(lip, { depth: 0.003, bevelEnabled: false, curveSegments: 12 }), grey, 0.0008);
  const face = new THREE.Shape(); face.absarc(0, 0, 0.034, -Math.PI * 0.29, Math.PI * 1.29, false); face.closePath();
  const pins = [[-0.009, 0.019, 0.0035], [0.009, 0.019, 0.0035], [-0.019, 0.0, 0.0055], [0.019, 0.0, 0.0055], [0, 0, 0.0055], [-0.011, -0.018, 0.0055], [0.011, -0.018, 0.0055]];
  for (const [x, y, r] of pins) { const h = new THREE.Path(); h.absarc(x, y, r, 0, Math.PI * 2, true); face.holes.push(h); }
  add(local, new THREE.ExtrudeGeometry(face, { depth: 0.006, bevelEnabled: true, bevelThickness: 0.0015, bevelSize: 0.0015, bevelSegments: 2, curveSegments: 32 }), grey, 0.002);
  for (const [x, y, r] of pins) add(local, new THREE.CylinderGeometry(r * 0.45, r * 0.45, 0.004, 10).rotateX(Math.PI / 2), materialFactory(0xc9a050, { metalness: 0.9, roughness: 0.3 }, 'brushed'), 0.005, x, y);
  add(local, new THREE.TorusGeometry(0.039, 0.0016, 8, 40), new THREE.MeshStandardMaterial({ color: 0x9cff9c, emissive: 0x3cff6a, emissiveIntensity: 0.7 }), 0.004);
  chargeLocal = local; local.visible = false;            // only seen with the flap open
  const lead = [P.clone().addScaledVector(n, -0.07), V(-0.76, 0.73, 1.13), V(-0.7, 0.75, 1.38), V(-0.6, 0.77, 1.6), V(-0.53, 0.775, 1.66)];
  const hv = new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(lead), 60, 0.009, 10, false), materialFactory(0xff6a00, { metalness: 0.02, roughness: 0.6 }, 'plastic')); hv.castShadow = true; sg.add(hv);
  carRoot.add(sg);
  register({ id: 'charge_socket', name: 'Charging socket (Type 2) with lead to the on-board charger', sys: 'hybrid', obj: sg, ex: V(-0.45, 0.1, 0), needOpen: 'charge_flap', ...info({ tags: ['hv'], mat: 'Type 2 AC socket in a plastic recess', conf: 'pub', note: 'The Golf 8 eHybrid charges on AC through a Type 2 socket under a flap in the front wing, just above the wheel (owner and charging guides). Side and exact position estimated on this model.' }) });
  // body-coloured flap, hinged at its front edge
  const paint = (() => { let m = null; body.obj.traverse(o => { if (!m && o.isMesh && [].concat(o.material).some(x => /CarPaint/.test(x.name))) m = [].concat(o.material).find(x => /CarPaint/.test(x.name)); }); return m; })();
  const fm = paint ? paint.clone() : materialFactory(0xc8102e, { metalness: 0.4, roughness: 0.3 }, 'paint'); fm.userData.op0 = fm.opacity; fm.userData.tr0 = fm.transparent; bodyMats.push(fm);
  const hingePt = P.clone().addScaledVector(fwd, W / 2 - 0.004).addScaledVector(n, 0.004);
  const fg = new THREE.Group(); fg.position.copy(hingePt); const fl = new THREE.Group(); fl.quaternion.copy(q); fg.add(fl);
  const plate = add(fl, new THREE.ExtrudeGeometry(rr(W, H, RR), { depth: 0.004, bevelEnabled: true, bevelThickness: 0.0012, bevelSize: 0.0012, bevelSegments: 2, curveSegments: 16 }), fm, -0.003, -(W / 2 - 0.004));
  add(fl, new THREE.ExtrudeGeometry(rr(W - 0.03, H - 0.03, RR - 0.01), { depth: 0.008, bevelEnabled: false }), black, -0.011, -(W / 2 - 0.004));
  carRoot.add(fg);
  HINGE.charge_flap = { axis: 'y', ang: 105 };
  register({ id: 'charge_flap', name: 'Charging flap', sys: 'body', obj: fg, ex: V(-0.3, 0, 0), ...info({ conf: 'model', mat: 'Painted plastic flap', note: 'Tap it to open. Body-coloured, hinged at the front edge; the socket is behind it.' }) });
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
  { t: 'Strip the engine on the stand', strip: true, d: 'The turbo, charge pipe, intake manifold and intercooler, coils, filler cap, mount bracket, pulley, flywheel, thermostat housing, oil filter, electric pump and loom are set aside. Now take the engine down part by part: tap a part, then Remove. It will tell you what has to come off first. Or use Strip in order to watch the sequence. Renew every seal and every stretch bolt on rebuild; torque values come from erWin.', f: s => { parts.forEach(p => { if (has(p, 'longblock')) s[p.id].h = true; if (has(p, 'strip')) s[p.id].h = false; }); } },
];
let step = 0, reversing = false, liftT = 0, liftY = 0;
const LIFT = 0.95;
function applyStep() {
  poke();
  const s = {}; parts.forEach(p => s[p.id] = { o: V(0, 0, 0), h: !!p.hidden });
  for (let i = 0; i <= step; i++) STEPS[i].f(s);
  parts.forEach(p => { p.svcT.copy(s[p.id].o); p.hideT = s[p.id].h; });
  $('#stepn').textContent = `Step ${step + 1} of ${STEPS.length}${reversing ? ' · putting it back' : ''}`; $('#stepbar').style.width = `${(step + 1) / STEPS.length * 100}%`;
  $('#stept').textContent = STEPS[step].t; $('#stepd').textContent = STEPS[step].d;
  $('#hvnote').hidden = !STEPS[step].hv;
  $('#prev').disabled = step === 0 && !reversing;
  $('#next').textContent = step === STEPS.length - 1 && !reversing ? 'Put it back' : reversing ? (step === 0 ? 'All back in' : 'Next step') : 'Next step';
  $('#next').disabled = reversing && step === 0;
  hvPulse = STEPS[step].hv;
  liftT = STEPS.slice(0, step + 1).some(x => x.lift) ? LIFT : 0;
  const onStand = !!STEPS[step].strip;
  if (!onStand) parts.forEach(p => { if (has(p, 'strip') && p.removed) { p.removed = false; } });
  $('#stripbtns').hidden = !onStand;
  refreshRows(); renderCard();
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
  const need = p.fx?.needOpen || p.needOpen;
  if (need && byId[need] && Math.abs(byId[need].angT) < 0.01) return `Open the ${nameOf(need).toLowerCase()} first${p.fx ? ', and support it' : ''}.`;
  if (FIXED.has(p.id)) return `${p.name} stays put: it is the base the other parts are fitted to.`;
  if (has(p, 'strip') && !has(p, 'incar') && !STEPS[step].strip) return 'Engine internals come out on the engine stand. Run the engine job to the last step first.';
  if (has(p, 'hv') && step < 1) return 'High voltage. Make the system safe first: Engine job, step 2.';
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
let TRN = null;
const refuse = m => { toast(m, true); TRN?.fault(m); return false; };
function boltAction(p, b, quiet) {
  const st = b.userData.state, need = p.fx.tool, say = (m, w) => { if (!quiet) { toast(m, w); if (w) TRN?.fault(m); } return false; };
  if (TRN?.active) { const m = TRN.allowed(p); if (m) return say(m, true); }
  if (st === 'in') {
    if (tool === 'tq' || tool === 'ang') return say('That fastener is already tight. Pick the tool that undoes it: ' + toolLabel(need) + '.', true);
    if (tool !== need) return say(`Wrong tool. ${p.fx.label.replace(/,.*$/, '')} need the ${toolLabel(need)}: a near-fit socket or bit rounds the head off.`, true);
    const why = whyNotRemove(p); if (why) return say(why, true);
    b.userData.state = 'out'; b.userData.t = 0; paintBolt(b); poke(); TRN?.changed();
    if (allOut(p)) { p.removed = true; refreshRows(); say(`${p.fx.label}: all ${p.bolts.length} out.` + (p.fx.renew ? ' These are renewed: new ones go in on refit.' : '')); }
    return true;
  }
  if (st === 'loose') {
    if (tool === 'tq' || tool === 'ang') return say('Run it in first with the ' + toolLabel(need) + ', then torque it.', true);
    if (tool !== need) return say(`Wrong tool: use the ${toolLabel(need)}.`, true);
    b.userData.state = 'snug'; paintBolt(b); poke(); TRN?.changed(); return true;
  }
  if (st === 'snug') {
    if (tool !== 'tq') return say('Snug. Now the torque wrench' + (p.fx.nm ? `, set to ${p.fx.nm} Nm.` : '.'), true);
    if (p.fx.nm == null) { b.userData.state = p.fx.deg ? 'torqued' : 'in'; paintBolt(b); poke(); return say('No torque value for these in the data: take the figure from erWin for this car.'), true; }
    if (Math.abs(tqSet - p.fx.nm) > 0.25) return say(tqSet > p.fx.nm ? `STOP: ${tqSet} Nm is over the ${p.fx.nm} Nm spec. Over-torque stretches the bolt or strips the thread.` : `Under-torqued: ${tqSet} Nm. The spec is ${p.fx.nm} Nm.`, true);
    b.userData.state = p.fx.deg ? 'torqued' : 'in'; paintBolt(b); poke(); TRN?.changed(); return true;
  }
  if (st === 'torqued') {
    if (tool !== 'ang') return say(`Torque stage done. Now the angle gauge: a further ${p.fx.deg}°.`, true);
    if (angSet !== p.fx.deg) return say(`Set the angle gauge to ${p.fx.deg}°, not ${angSet}°.`, true);
    b.userData.state = 'in'; paintBolt(b); poke(); TRN?.changed(); return true;
  }
  return false;
}
function fitBolts(p) {
  if (TRN?.active) { const m = TRN.allowed(p); if (m) return refuse(m); }
  const why = whyNotRefit(p); if (why) return refuse(why);
  p.bolts.forEach(b => { b.userData.state = 'loose'; b.userData.t = 0; paintBolt(b); });
  p.removed = false; poke(); refreshRows();
  toast((p.fx.renew ? 'New bolts fitted by hand. ' : 'Bolts started by hand. ') + `Now run them in with the ${toolLabel(p.fx.tool)}, then torque${p.fx.nm ? ' to ' + p.fx.nm + ' Nm' : ''}${p.fx.deg ? ' + ' + p.fx.deg + '°' : ''}.`);
}
function allBolts(p) { let n = 0; for (const b of p.bolts) if (b.userData.state !== 'out' && boltAction(p, b, true)) n++; if (!n) { const b = p.bolts.find(x => x.userData.state !== 'out'); if (b) boltAction(p, b, false); } else toast(`${n} done with the ${toolLabel(tool)}.`); renderSheet(p.id); }
let manual = false;
function syncTray() { $('#tray').querySelectorAll('.tool').forEach(x => x.setAttribute('aria-pressed', String(x.dataset.tool === tool))); $('#tqbox').hidden = tool !== 'tq'; $('#angbox').hidden = tool !== 'ang'; $('#tq').value = tqSet; $('#tqv').textContent = tqSet; $('#tqn').value = tqSet; $('#ang').value = String(angSet); }
function buildTray() {
  const tray = $('#tray'); tray.textContent = '';
  for (const t of TOOLS) {
    const b = document.createElement('button'); b.className = 'tool'; b.dataset.tool = t.k; b.textContent = t.label; b.setAttribute('aria-pressed', String(t.k === tool));
    b.onclick = () => { tool = t.k; syncTray(); };
    tray.append(b);
  }
  $('#tq').oninput = e => { tqSet = +e.target.value; $('#tqv').textContent = tqSet; $('#tqn').value = tqSet; };
  $('#tqn').oninput = e => { const v = Math.max(2, Math.min(220, Math.round(+e.target.value * 2) / 2)); if (Number.isFinite(v)) { tqSet = v; $('#tq').value = v; } };
  $('#ang').onchange = e => { angSet = +e.target.value; };
}
let toastT = 0;
function toast(msg, warn) { const t = $('#toast'); t.textContent = msg; t.className = 'glass' + (warn ? ' warn' : ''); t.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => t.hidden = true, 3600); }
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
  if (TRN?.active) { const m = TRN.allowed(p); if (m) return quiet ? false : refuse(m); }
  const why = whyNotRemove(p); if (why) { if (!quiet) { refuse(why); flash(BLOCK[id] || []); } return false; }
  if (p.hinge) p.angT = 0;
  if (!has(p, 'strip')) floorSpot(p);
  p.removed = true; poke(); refreshRows();
  if (!quiet) toast(`${p.name}: removed.` + (has(p, 'seal') ? ' Fit a new one on rebuild.' : /stretch/.test(p.size + p.note) ? ' Stretch bolts: fit new ones on rebuild.' : ''));
  return true;
}
function refitPart(id, quiet) {
  const p = byId[id]; if (!p || !p.removed) return false;
  if (TRN?.active) { const m = TRN.allowed(p); if (m) return quiet ? false : refuse(m); }
  const why = whyNotRefit(p); if (why) { if (!quiet) refuse(why); return false; }
  p.removed = false; poke(); refreshRows();
  if (!quiet) toast(`${p.name}: refitted.` + (has(p, 'seal') ? ' New seal fitted.' : has(p, 'fastener') ? ' Torque to the erWin value.' : ''));
  return true;
}
function refitEverything() { parts.forEach(p => { p.removed = false; if (p.bolts) p.bolts.forEach(b => { b.userData.state = 'in'; paintBolt(b); }); if (p.hinge) p.angT = p.id === 'panel_bonnet' ? HINGE.panel_bonnet.ang * DEG : 0; }); poke(); refreshRows(); }
function flash(ids) { ids.forEach(id => { const r = $('#row_' + id); if (r) { r.classList.add('flash'); setTimeout(() => r.classList.remove('flash'), 1500); } }); }
function toggleHinge(id) { const p = byId[id]; if (!p?.hinge || p.removed || p.hideT) return; p.angT = Math.abs(p.angT) > 0.01 ? 0 : p.hinge.ang * DEG; poke(); renderCard(); TRN?.changed(); }
let seq = null;
function runSequence(kind) {
  clearInterval(seq);
  const strip = parts.filter(p => has(p, 'strip') && !FIXED.has(p.id));
  seq = setInterval(() => {
    const next = kind === 'strip' ? strip.find(p => !p.removed && !whyNotRemove(p)) : [...strip].reverse().find(p => p.removed && !whyNotRefit(p));
    if (!next) { clearInterval(seq); toast(kind === 'strip' ? 'Engine stripped. Seals and stretch bolts are marked for renewal.' : 'Engine rebuilt. Torque every fastener to the erWin value.'); return; }
    if (next.fx) { if (kind === 'strip') { next.bolts.forEach(b => { b.userData.state = 'out'; paintBolt(b); }); next.removed = true; } else { next.bolts.forEach(b => { b.userData.state = 'in'; paintBolt(b); }); next.removed = false; } refreshRows(); poke(); }
    else kind === 'strip' ? removePart(next.id, true) : refitPart(next.id, true);
    select(next.id, false, true);
  }, REDUCED ? 30 : 420);
}
$('#stripall').onclick = () => runSequence('strip');
$('#rebuildall').onclick = () => runSequence('rebuild');
$('#refitall').onclick = () => { clearInterval(seq); refitEverything(); renderCard(); toast('Everything is back on the car.'); };

/* ───────── parts list, selection ───────── */
let selected = null;
const confTag = c => c === 'pub' ? '<span class="conf pub">published</span>' : c === 'model' ? '<span class="conf model">real model</span>' : '<span class="conf est">estimated</span>';
function buildTree() {
  const tree = $('#tree'); tree.textContent = '';
  let total = 0;
  for (const [k, label] of Object.entries(SYS)) {
    const list = parts.filter(p => p.sys === k); if (!list.length) continue;
    const n = list.reduce((a, p) => a + p.qty, 0); total += n;
    const d = document.createElement('details'); d.className = 'sys';
    const sm = document.createElement('summary');
    sm.innerHTML = `<i class="dot" style="background:${SYS_COLOR[k]}"></i><span></span><span class="n">${n}</span>`; sm.children[1].textContent = label; d.append(sm);
    for (const p of list) {
      const r = document.createElement('div'); r.className = 'prow'; r.id = 'row_' + p.id; r.dataset.name = p.name.toLowerCase();
      const b = document.createElement('button'); b.textContent = p.name; b.onclick = () => { select(p.id, true); if (matchMedia('(max-width: 819px)').matches) panel('parts', false); };
      r.append(b);
      if (has(p, 'hv')) { const t = document.createElement('span'); t.className = 'tag hv'; t.textContent = 'HV'; r.append(t); }
      if (has(p, 'seal')) { const t = document.createElement('span'); t.className = 'tag seal'; t.textContent = 'renew'; r.append(t); }
      if (p.qty > 1) { const q = document.createElement('span'); q.className = 'q'; q.textContent = '×' + p.qty; r.append(q); }
      d.append(r);
    }
    tree.append(d);
  }
  $('#count').textContent = `${total}`;
}
$('#psearch').oninput = e => {
  const q = e.target.value.trim().toLowerCase();
  document.querySelectorAll('#tree .sys').forEach(d => { let any = false; d.querySelectorAll('.prow').forEach(r => { const hit = !q || r.dataset.name.includes(q); r.hidden = !hit; any ||= hit; }); d.hidden = !any; d.open = !!q && any; });
};
const HL = new THREE.Color(0x2f8cff);
function setHighlight(id, on) {
  const p = byId[id]; if (!p) return;
  p.obj.traverse(o => { if (!o.isMesh) return;
    if (on) { o.userData.m0 = o.material; o.material = [].concat(o.material).map(m => { const c = m.clone(); if (c.emissive) { c.emissive = HL; c.emissiveIntensity = ['body', 'interior'].includes(p.sys) ? 0.12 : 0.45; } return c; }); if (o.material.length === 1) o.material = o.material[0]; }
    else if (o.userData.m0) { o.material = o.userData.m0; delete o.userData.m0; } });
}
function refreshRows() { TRN?.changed(); parts.forEach(p => { const r = $('#row_' + p.id); if (r) r.classList.toggle('gone', p.removed || (p.hideT && !has(p, 'strip'))); }); const n = parts.filter(p => p.removed).length; $('#removed').textContent = n ? `${n} parts are off the car.` : 'Everything is on the car.'; }

/* ───────── the card: one clear next step for the selected part ─────────
   Guided by default: the button picks the right tool, torque and angle itself.
   "Choose tools myself" in View brings back the tool tray for practice. */
const isOpen = q => Math.abs(q.angT) > 0.01;
function blockersOff(p) {
  const ids = [], need = p.fx?.needOpen || p.needOpen;
  if (need && byId[need] && !isOpen(byId[need])) ids.push(need);
  for (const b of BLOCK[p.id] || []) if (byId[b] && !offCar(byId[b])) ids.push(b);
  return ids;
}
const blockersOn = p => Object.entries(BLOCK).filter(([id, bs]) => bs.includes(p.id) && byId[id]?.removed).map(([id]) => id);
const verbFor = id => { const q = byId[id]; return q.hinge && !isOpen(q) && !q.fx ? 'open the' : q.fx ? 'undo the' : 'take off the'; };
const lc = s => /^[A-Z]{2}/.test(s) ? s : s.charAt(0).toLowerCase() + s.slice(1);
const listOf = ids => { const n = ids.map(id => lc(nameOf(id))); return n.length > 3 ? `${n.slice(0, 3).join(', ')} and ${n.length - 3} more` : n.join(', '); };
function drive(p, from, toolKey) {
  tool = toolKey; syncTray();
  let k = 0; for (const b of p.bolts) if (b.userData.state === from && boltAction(p, b, true)) k++;
  if (!k) { const b = p.bolts.find(x => x.userData.state === from); if (b) boltAction(p, b, false); return; }
  const n = p.fx.label.replace(/,.*$/, '');
  if (from === 'in') toast(`${n}: ${k} out.` + (p.fx.renew ? ' Fit new ones when it goes back.' : ''));
  else if (from === 'loose') toast(`${n}: snug. Now torque them.`);
  else if (from === 'snug') toast(p.fx.deg ? `${p.fx.nm} Nm done. Now a further ${p.fx.deg}°.` : p.fx.nm != null ? `${n}: torqued to ${p.fx.nm} Nm.` : `${n}: tight. Take the torque value from erWin.`);
  else toast(`${n}: fully tightened.`);
}
function nextAction(p) {
  if (FIXED.has(p.id)) return { label: 'Fixed in place', hint: 'Other parts are fitted to this one, so it stays on.', off: true };
  if (p.hideT && !p.removed && !has(p, 'strip')) return { label: 'Set aside by the engine job', hint: 'Go back in the engine job to bring it back.', off: true };
  const chainOff = bl => ({ label: `First, ${verbFor(bl[0])} ${lc(nameOf(bl[0]))}`, go: bl[0], hint: `In the way: ${listOf(bl)}.`, warn: true, chain: 'off' });
  const chainOn = bl => ({ label: `First, put back the ${lc(nameOf(bl[0]))}`, go: bl[0], hint: `Goes back first: ${listOf(bl)}.`, warn: true, chain: 'on' });
  if (p.fx) {
    const c = k => p.bolts.filter(b => b.userData.state === k).length, T = toolLabel(p.fx.tool), n = p.bolts.length;
    if (c('loose')) return { label: `Run them in with the ${T}`, run: () => drive(p, 'loose', p.fx.tool) };
    if (c('snug')) return { label: p.fx.nm != null ? `Torque to ${p.fx.nm} Nm` : 'Tighten them', hint: p.fx.nm != null ? 'With the torque wrench.' : 'No torque value in the data: take it from erWin.', run: () => { tqSet = p.fx.nm ?? tqSet; drive(p, 'snug', 'tq'); } };
    if (c('torqued')) return { label: `Turn a further ${p.fx.deg}°`, hint: 'With the angle gauge.', run: () => { angSet = p.fx.deg; drive(p, 'torqued', 'ang'); } };
    if (c('out') === n) { const bl = blockersOn(p); if (bl.length) return chainOn(bl); return { label: p.fx.renew ? 'Fit new bolts' : 'Fit the bolts', hint: 'Started by hand, then run in and torqued.', run: () => fitBolts(p) }; }
    const bl = blockersOff(p); if (bl.length) return chainOff(bl);
    const why = whyNotRemove(p); if (why) return { label: 'Not yet', hint: why, off: true, warn: true };
    const k = c('in'); return { label: k === 1 ? `Undo it with the ${T}` : `Undo all ${k} with the ${T}`, run: () => drive(p, 'in', p.fx.tool) };
  }
  if (p.removed) { const bl = blockersOn(p); if (bl.length) return chainOn(bl); return { label: 'Put it back', run: () => refitPart(p.id) }; }
  const bl = blockersOff(p); if (bl.length) return chainOff(bl);
  const why = whyNotRemove(p); if (why) return { label: 'Not yet', hint: why, off: true, warn: true };
  return { label: 'Take it off', run: () => removePart(p.id) };
}
// everything that has to happen, in order, to take a part off (or put it back)
function plan(id, dir, out = [], seen = new Set()) {
  if (seen.has(id)) return out; seen.add(id);
  const p = byId[id]; if (!p) return out;
  if (dir === 'off') {
    if (offCar(p)) return out;
    const need = p.fx?.needOpen || p.needOpen;
    if (need && byId[need] && !isOpen(byId[need]) && !out.includes('open:' + need)) out.push('open:' + need);
    for (const b of BLOCK[p.id] || []) if (byId[b] && !offCar(byId[b])) plan(b, 'off', out, seen);
    out.push(id); return out;
  }
  // back on: what sits under it first, then the part, then whatever came off to free it, last-off first
  for (const b of blockersOn(p)) plan(b, 'on', out, seen);
  if (p.removed) out.push(id);
  for (const b of [...(BLOCK[id] || [])].reverse()) if (byId[b]?.removed) plan(b, 'on', out, seen);
  return out;
}
function doAll(id, dir, sync) {
  clearInterval(seq);
  const steps = plan(id, dir); let i = 0, n = 0, halted = false;
  const stop = q => { halted = true; clearInterval(seq); select(q.id, false); toast(`Stopped at ${lc(nameOf(q.id))}: ${whyNotRemove(q) || whyNotRefit(q) || 'it cannot move yet.'}`, true); };
  const one = () => {
    if (halted) return;
    if (i >= steps.length) { clearInterval(seq); select(id, false); toast(dir === 'off' ? `Done in ${n} steps, every bolt with the right tool.` : `Back together in ${n} steps, every bolt torqued to spec.`); return; }
    const tok = steps[i++]; n++;
    if (tok.startsWith('open:')) { const h = tok.slice(5); if (!isOpen(byId[h])) toggleHinge(h); select(h, false, true); return; }
    const q = byId[tok];
    if (dir === 'off') {
      if (q.fx) { tool = q.fx.tool; q.bolts.forEach(b => { if (b.userData.state !== 'out') boltAction(q, b, true); }); if (!allOut(q)) return stop(q); }
      else if (!removePart(q.id, true)) return stop(q);
    } else {
      if (q.fx) { if (whyNotRefit(q)) return stop(q); fitBolts(q); q.bolts.forEach(b => { b.userData.state = 'in'; paintBolt(b); }); }
      else if (!refitPart(q.id, true)) return stop(q);
    }
    refreshRows(); select(q.id, false, true); poke();
  };
  if (sync) { while (i < steps.length && !halted) one(); if (!halted) one(); return; }
  seq = setInterval(one, REDUCED ? 40 : 380);
}
function stateOf(p) {
  if (p.fx) { const n = p.bolts.length, tight = p.bolts.filter(b => b.userData.state === 'in').length, out = p.bolts.filter(b => b.userData.state === 'out').length;
    return out === n ? ['All out', 'off'] : tight === n ? ['All tight', 'ok'] : [`${tight} of ${n} tight`, 'off']; }
  if (p.removed) return ['Off the car', 'off'];
  if (p.hideT && !has(p, 'strip')) return ['Set aside', 'off'];
  if (p.hinge && isOpen(p)) return ['Open', ''];
  return [has(p, 'hv') ? 'High voltage' : 'Fitted', has(p, 'hv') ? 'hv' : 'ok'];
}
function renderCard() {
  const p = selected && byId[selected];
  $('#ce-empty').hidden = !!p; $('#ce-part').hidden = !p;
  const jobOn = step > 0 || reversing; $('#ce-job').hidden = !jobOn || mode !== 'explore';
  if (jobOn) $('#ce-jobtext').textContent = `Engine job: step ${step + 1} of ${STEPS.length}`;
  if (!p) return;
  $('#ce-dot').style.background = SYS_COLOR[p.sys]; $('#ce-sys').textContent = SYS[p.sys];
  const [st, cls] = stateOf(p); const pill = $('#ce-state'); pill.textContent = st; pill.className = 'pill ' + cls;
  $('#ce-name').textContent = p.name;
  const specs = $('#ce-specs'); specs.textContent = '';
  const spec = (t, c) => { const e = document.createElement('span'); e.className = 'spec' + (c ? ' ' + c : ''); e.textContent = t; specs.append(e); };
  if (p.fx) { spec(toolLabel(p.fx.tool)); spec(p.fx.nm != null ? `${p.fx.nm} Nm${p.fx.deg ? ' + ' + p.fx.deg + '°' : ''}` : 'Torque: erWin'); if (p.fx.renew) spec('Renew every time', 'renew'); if (p.qty > 1) spec(`${p.qty} off`); }
  else { if (p.qty > 1) spec(`${p.qty} off`); if (has(p, 'seal')) spec('Renew every time', 'renew'); const held = (BLOCK[p.id] || []).map(x => byId[x]).find(q => q?.fx); if (held) spec(`Held by ${lc(held.fx.label.replace(/,.*$/, ''))}`); }
  specs.hidden = !specs.children.length;
  const a = nextAction(p), main = $('#ce-main'), hint = $('#ce-hint');
  main.textContent = a.label; main.className = 'btn big ' + (a.off ? '' : a.warn ? 'warn' : 'pri'); main.setAttribute('aria-disabled', String(!!a.off));
  main.onclick = () => { if (a.off) return; if (a.go) { select(a.go, true); return; } a.run(); renderCard(); };
  hint.textContent = a.hint || ''; hint.hidden = !a.hint; hint.className = 'hint' + (a.warn ? ' warn' : '');
  const more = $('#ce-more'); more.textContent = '';
  const btn = (label, fn) => { const e = document.createElement('button'); e.className = 'btn'; e.textContent = label; e.onclick = fn; more.append(e); };
  if (a.chain) btn(a.chain === 'off' ? 'Do every step' : 'Put it all back', () => doAll(p.id, a.chain));
  else if (p.removed && !FIXED.has(p.id) && plan(p.id, 'on').length > 1) btn('Put it all back', () => doAll(p.id, 'on'));
  if (p.hinge && !p.removed && !p.hideT) btn(isOpen(p) ? 'Close' : 'Open', () => toggleHinge(p.id));
  btn($('#ce-details').hidden ? 'Details' : 'Hide details', () => { $('#ce-details').hidden = !$('#ce-details').hidden; renderCard(); setDetent($('#ce-details').hidden ? 0 : 2); });
  const det = $('#ce-details');
  if (!det.hidden) {
    det.textContent = '';
    const dl = document.createElement('dl'); dl.className = 'kv';
    const src = p.fx ? (p.fx.src === 'man' ? 'VW manual data' : p.fx.src === 'class' ? 'Typical value' : 'Estimate') : p.conf === 'pub' ? 'Published' : p.conf === 'model' ? 'Real car model' : 'Estimated';
    for (const [k, v] of [['Material', p.mat], ['Size', p.fx ? '' : p.size], ['Source', src], ['OEM part no.', 'Not included']]) { if (!v) continue; const dt = document.createElement('dt'); dt.textContent = k; const dd = document.createElement('dd'); dd.textContent = v; dl.append(dt, dd); }
    const n = document.createElement('p'); n.className = 'note'; n.textContent = p.note || 'Shape and position estimated.';
    det.append(dl, n);
  }
}
function select(id, frame, keepMode) {
  poke();
  if (selected) { setHighlight(selected, false); $('#row_' + selected)?.classList.remove('sel'); }
  selected = id; const p = byId[id];
  if (!keepMode && mode !== 'explore' && p) setMode('explore');
  if (!p) { if (focus) { focus = false; setOpacity(seeThrough()); } renderCard(); return; }
  setHighlight(id, true);
  const row = $('#row_' + id); if (row) { row.classList.add('sel'); const d = row.closest('details'); if (d) d.open = true; }
  renderCard(); if (mode === 'explore') setDetent($('#ce-details').hidden ? 0 : 2);
  const inner = !['body', 'interior'].includes(p.sys) && !/^wheel_/.test(p.id);
  if (frame) { focus = inner; setOpacity(seeThrough()); const b = new THREE.Box3().setFromObject(p.obj); if (!b.isEmpty()) { const c = b.getCenter(V(0, 0, 0)), r = Math.max(0.45, b.getSize(V(0, 0, 0)).length()); flyTo(c.clone().add(V(Math.sign(c.x || 1) * r * 1.4, r * 0.8, r * 1.2)), c); } }
  else if (focus && !inner) { focus = false; setOpacity(seeThrough()); }
}
function renderSheet() { renderCard(); }

/* ───────── modes and panels ───────── */
let mode = 'explore', training = false, trayWanted = false;
function markLeak(side) {
  for (const k of ['fl', 'fr']) { const s = byId['strut_' + k]?.obj.children[0]; s?.getObjectByName('leak')?.removeFromParent(); }
  if (!side) return; const s = byId['strut_' + side]?.obj.children[0]; if (!s) return;
  const g = new THREE.Group(); g.name = 'leak';
  const oil = new THREE.MeshPhysicalMaterial({ color: 0x1d1810, roughness: 0.12, metalness: 0.2, clearcoat: 1, clearcoatRoughness: 0.08 });
  const dirt = new THREE.MeshStandardMaterial({ color: 0x4a3c2a, roughness: 0.95 });
  const sheet = new THREE.Mesh(new THREE.CylinderGeometry(0.0262, 0.0262, 0.2, 24, 1, true, -0.6, 2.6), oil); sheet.position.y = 0.09; g.add(sheet);
  for (let i = 0; i < 9; i++) { const d = new THREE.Mesh(new THREE.SphereGeometry(0.004 + Math.random() * 0.004, 8, 6), dirt); const a = -0.4 + Math.random() * 2.2, y = -0.02 + Math.random() * 0.17; d.position.set(Math.cos(a) * 0.026, y, Math.sin(a) * 0.026); d.scale.set(1, 1.8, 1); g.add(d); }
  const drip = new THREE.Mesh(new THREE.SphereGeometry(0.0045, 10, 8), oil); drip.position.set(0.02, -0.06, 0.016); drip.scale.set(1, 1.6, 1); g.add(drip);
  g.traverse(o => { if (o.isMesh) o.userData.pid = 'strut_' + side; });
  s.add(g); poke();
}
const W = {
  get byId() { return byId; }, get parts() { return parts; }, nameOf: id => byId[id]?.name || id,
  flyTo: (p, t) => flyTo(V(p[0], p[1] + liftT, p[2]), V(t[0], t[1] + liftT, t[2])), setLift: on => { liftT = on ? LIFT : 0; poke(); },   // views follow the lift
  flash: id => { if (id === selected) return; setHighlight(id, true); setTimeout(() => { if (id !== selected) setHighlight(id, false); poke(); }, 900); poke(); },
  selectedPart: () => selected && byId[selected], stateText: p => stateOf(p)[0],
  fitBolts: p => { fitBolts(p); renderCard(); }, allBolts: p => allBolts(p), toolName: () => toolLabel(tool), toolLabel,
  removePart: id => removePart(id), refitPart: id => refitPart(id), isFixed: id => FIXED.has(id), toggleHinge, isOpen,
  markLeak, focus: on => { focus = on; setOpacity(seeThrough()); poke(); },
  trainingActive: on => { training = on; trayWanted = false; $('.toolbar').hidden = !manual; if (on) tool = 'hand'; syncTray(); },
  showTray: on => { trayWanted = on; $('.toolbar').hidden = !(on || manual); document.body.classList.toggle('tray-on', !$('.toolbar').hidden); updateViewOffset(); },
  sheet: i => setDetent(i),
  resetCar: () => { clearInterval(seq); markLeak(null); refitEverything(); reversing = false; step = 0; applyStep(); liftT = 0; focus = false; setOpacity(seeThrough()); parts.forEach(p => { p.vis = true; }); select(null, false, true); },
  openDemo: () => setMode('job'),
};
function setMode(m) {
  mode = m;
  document.querySelectorAll('[data-mode]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.mode === m)));
  $('#card-explore').hidden = m !== 'explore'; $('#card-job').hidden = m !== 'job'; $('#card-photo').hidden = m !== 'photo'; $('#card-train').hidden = m !== 'train';
  document.querySelectorAll('[data-mode]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.mode === (m === 'job' ? 'train' : m))));
  if (m === 'train' && TRN && !TRN.run) TRN.list();
  if (m !== 'train' && training) { TRN?.run?.job.cleanup?.(); TRN?.list(); }
  if (m !== 'photo') stopPhoto();
  renderCard(); setDetent(m === 'explore' ? 0 : 1);
}
document.querySelectorAll('[data-mode]').forEach(b => b.onclick = () => setMode(b.dataset.mode));
function panel(which, open) {
  const el = $('#' + which), btn = $(which === 'parts' ? '#openparts' : '#openview');
  open ??= el.hidden; el.hidden = !open; btn.setAttribute('aria-expanded', String(open)); document.body.classList.toggle('parts-open', which === 'parts' ? open : !$('#parts').hidden && !open ? true : false);
  if (open) { const other = which === 'parts' ? 'viewpanel' : 'parts'; $('#' + other).hidden = true; $(other === 'parts' ? '#openparts' : '#openview').setAttribute('aria-expanded', 'false'); if (which === 'parts') $('#psearch').focus({ preventScroll: true }); }
}
$('#openparts').onclick = () => panel('parts'); $('#closeparts').onclick = () => panel('parts', false);
$('#openview').onclick = () => panel('viewpanel'); $('#closeview').onclick = () => panel('viewpanel', false);
$('#browse').onclick = () => panel('parts', true);
$('#gojob').onclick = () => setMode('train'); $('#jobback').onclick = () => setMode('train'); $('#ce-jobgo').onclick = () => setMode('job');
$('#ce-close').onclick = () => select(null);
$('#manual').onchange = e => { manual = e.target.checked; $('.toolbar').hidden = !manual && !(training && trayWanted); document.body.classList.toggle('tray-on', !$('.toolbar').hidden); updateViewOffset(); if (manual) syncTray(); toast(manual ? 'Pick a tool, then tap each bolt. The card still shows the spec.' : 'Guided: the card picks the right tool for you.'); };
document.addEventListener('keydown', e => { if (e.key === 'Escape') { panel('parts', false); panel('viewpanel', false); } });
$('#isolate').onclick = () => { poke(); if (!selected) { toast('Tap a part first, then show only its system.', true); return; } const s = byId[selected].sys; parts.forEach(p => { p.vis = p.sys === s; }); };
$('#showall').onclick = () => { poke(); parts.forEach(p => { p.vis = true; }); };
const ray = new THREE.Raycaster(), ptr = new THREE.Vector2(); let down = null, lastTap = null;
renderer.domElement.addEventListener('pointerdown', e => { down = [e.clientX, e.clientY, e.timeStamp, e.isPrimary]; if ($('.views').classList.contains('open')) { $('.views').classList.remove('open'); $('#openviews').setAttribute('aria-expanded', 'false'); } });
renderer.domElement.addEventListener('pointerup', e => {
  if (!down || !down[3] || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > (e.pointerType === 'touch' ? 12 : 5) || e.timeStamp - down[2] > 600) return;
  const now = e.timeStamp, dbl = lastTap && now - lastTap[0] < 330 && Math.hypot(e.clientX - lastTap[1], e.clientY - lastTap[2]) < 30;
  lastTap = dbl ? null : [now, e.clientX, e.clientY];
  if (dbl) {
    const r = renderer.domElement.getBoundingClientRect(); ptr.set((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1); ray.setFromCamera(ptr, camera);
    const h2 = ray.intersectObjects(parts.filter(p => p.obj.visible).map(p => p.obj), true).find(x => x.object.userData.pid);
    if (h2) { const off = camera.position.clone().sub(controls.target), d = Math.min(off.length(), 1.6); flyTo(h2.point.clone().add(off.setLength(d)), h2.point); } else recenter();
    return;
  }
  const r = renderer.domElement.getBoundingClientRect(); ptr.set((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1);
  ray.setFromCamera(ptr, camera);
  const objs = parts.filter(p => p.obj.visible && !(seeThrough() < 0.5 && (['body', 'glazing', 'cabin', 'panel_bonnet', 'tailgate', 'bumper_f', 'charge_flap'].includes(p.id) || /^(door|wheel)_/.test(p.id)))).map(p => p.obj);
  const hit = ray.intersectObjects(objs, true).find(h => h.object.userData.pid);
  if (hit) {
    const id = hit.object.userData.pid, p = byId[id];
    if (TRN?.pick(id)) return;
    const keep = mode === 'train';
    let o = hit.object; while (o && o.userData.bi === undefined && o.parent) o = o.parent;
    if (p.fx && o && o.userData.bi !== undefined) {
      select(id, false, keep);
      if (!manual && !training) { const st = o.userData.state; if (st === 'out') { renderCard(); return; } tool = st === 'snug' ? 'tq' : st === 'torqued' ? 'ang' : p.fx.tool; if (st === 'snug' && p.fx.nm != null) tqSet = p.fx.nm; if (st === 'torqued') angSet = p.fx.deg; syncTray(); }
      boltAction(p, o); renderCard(); TRN?.changed(); return;
    }
    select(id, false, keep); if (p.hinge && !keep) toggleHinge(id); TRN?.changed();
  } else if (selected) { select(null, false, mode === 'train'); TRN?.changed(); }
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
$('#xray').oninput = () => { setOpacity(seeThrough()); poke(); };
let focus = false;
const seeThrough = () => focus ? Math.min(0.22, +$('#xray').value) : +$('#xray').value;
function setOpacity(v) { for (const m of bodyMats) { m.transparent = v < 0.999 || m.userData.tr0; m.opacity = Math.min(m.userData.op0, v); m.depthWrite = v > 0.6; m.needsUpdate = true; } }
const VIEWS = { iso: [[4.6, 2.6, 4.8], [0, 0.55, 0.2]], side: [[6.4, 1.1, 0.1], [0, 0.6, 0]], bay: [[1.9, 1.9, 3.3], [-0.05, 0.55, 1.5]], under: [[2.4, -0.4, 2.2], [0, 0.35, 0.3]], top: [[0.01, 7.5, 0.2], [0, 0, 0.2]], bench: [[2.0, 2.15, 7.0], [0.4, 1.12, 3.45]], corner: [[2.3, 0.95, 2.6], [0.7, 0.42, 1.3]] };
let fly = null;
function flyTo(pos, tgt) { fly = { p: pos.clone(), t: tgt.clone() }; }
// on a portrait phone the preset views step back a little so the whole subject fits
const fit = (p, t) => { if (camera.aspect >= 1) return p; const o = p.clone().sub(t), k = Math.min(1.25, 7.6 / Math.max(o.length(), 0.01)); return t.clone().add(o.multiplyScalar(Math.max(1, k))); };
document.querySelectorAll('[data-v]').forEach(b => b.onclick = () => { if (b.dataset.v === 'under' && liftT === 0 && !training) { liftT = LIFT; toast('Car raised on the lift to look underneath.'); }
  const [p, t] = VIEWS[b.dataset.v], up = b.dataset.v === 'bench' || b.dataset.v === 'top' ? 0 : liftT, tt = V(t[0], t[1] + up, t[2]); flyTo(fit(V(p[0], p[1] + up, p[2]), tt), tt); });
camera.position.set(...VIEWS.iso[0]); controls.target.set(...VIEWS.iso[1]);

/* ───────── navigation: stay above the floor and near the car ───────── */
const TMIN = V(-2.6, -0.2, -3.6), TMAX = V(2.6, 2.8, 3.8), FLOOR = 0.08;
function keepCameraSane() {
  const t = controls.target, c = t.clone().clamp(TMIN, TMAX).sub(t);
  if (c.lengthSq() > 0) { t.add(c); camera.position.add(c); }
  const d = camera.position.distanceTo(t);
  controls.maxPolarAngle = Math.acos(Math.max(-1, Math.min(1, (FLOOR - t.y) / Math.max(d, 1e-3))));
}
function recenter() { const [p, t] = VIEWS.iso, tt = V(t[0], t[1] + liftT, t[2]); flyTo(fit(V(p[0], p[1] + liftT, p[2]), tt), tt); }

/* ───────── phone sheet: three heights, drag or tap the handle; the 3D view re-centres in the gap ───────── */
const sheet = $('#sheet'), isPhone = () => matchMedia('(max-width: 819px)').matches;
let det = 0, autoDet = null;
const detents = () => { const top = $('.bar').getBoundingClientRect().bottom; return [212, Math.round(innerHeight * 0.46), Math.round(innerHeight - top - 26)]; };
function setDetent(i, auto) {
  if (!isPhone()) { sheet.style.removeProperty('height'); document.documentElement.style.removeProperty('--sheet-h'); return; }
  det = Math.max(0, Math.min(2, i)); if (!auto) autoDet = null;
  document.documentElement.style.setProperty('--sheet-h', detents()[det] + 'px');
}
function updateViewOffset() {
  const w = stage.clientWidth, h = stage.clientHeight;
  if (!isPhone() || !w || !h) { if (camera.view?.enabled) { camera.clearViewOffset(); poke(); } return; }
  const top = $('.bar').getBoundingClientRect().bottom + (document.body.classList.contains('tray-on') ? 52 : 0), bot = sheet.getBoundingClientRect().top;
  const shift = Math.round(h / 2 - (top + Math.max(top + 80, bot)) / 2);
  if (!camera.view || camera.view.offsetY !== shift || camera.view.fullWidth !== w || camera.view.fullHeight !== h) { camera.setViewOffset(w, h, 0, shift, w, h); poke(); }
}
new ResizeObserver(updateViewOffset).observe(sheet);
addEventListener('resize', () => { setDetent(det); updateViewOffset(); });
{ let y0 = null, h0 = 0, moved = false;
  const grab = $('#grab');
  grab.addEventListener('pointerdown', e => { if (!isPhone()) return; y0 = e.clientY; h0 = sheet.getBoundingClientRect().height; moved = false; sheet.classList.add('dragging'); grab.setPointerCapture(e.pointerId); });
  grab.addEventListener('pointermove', e => { if (y0 == null) return; const dy = e.clientY - y0; if (Math.abs(dy) > 4) moved = true; const [a, , c] = detents(); document.documentElement.style.setProperty('--sheet-h', Math.max(a - 40, Math.min(c, h0 - dy)) + 'px'); });
  grab.addEventListener('pointerup', e => { if (y0 == null) return; sheet.classList.remove('dragging'); const hNow = sheet.getBoundingClientRect().height; y0 = null;
    if (!moved) return setDetent((det + 1) % 3);
    const ds = detents(); let best = 0; ds.forEach((v, i) => { if (Math.abs(v - hNow) < Math.abs(ds[best] - hNow)) best = i; }); setDetent(best); });
  grab.addEventListener('pointercancel', () => { y0 = null; sheet.classList.remove('dragging'); setDetent(det); });
}
// while turning the car the sheet drops out of the way, and comes back after
controls.addEventListener('start', () => { fly = null; if (isPhone() && det > 0 && autoDet == null) { autoDet = det; setDetent(0, true); } });
controls.addEventListener('end', () => { if (autoDet != null) { const back = autoDet; setTimeout(() => { if (autoDet === back) { setDetent(back); } }, 900); } });
$('#recenter').onclick = () => { recenter(); };
$('#openviews').onclick = e => { const v = $('.views'), open = !v.classList.contains('open'); v.classList.toggle('open', open); e.currentTarget.setAttribute('aria-expanded', String(open)); };
document.querySelectorAll('.views .chip').forEach(b => b.addEventListener('click', () => { $('.views').classList.remove('open'); $('#openviews').setAttribute('aria-expanded', 'false'); }));

/* ───────── loop ───────── */
const clock = new THREE.Clock();
function resize() { const w = stage.clientWidth, h = stage.clientHeight; if (renderer.domElement.width !== Math.floor(w * renderer.getPixelRatio()) || renderer.domElement.height !== Math.floor(h * renderer.getPixelRatio())) { renderer.setSize(w, h, false); camera.aspect = w / Math.max(h, 1); camera.fov = camera.aspect < 1 ? Math.min(56, 34 / Math.max(camera.aspect, 0.5) * 0.8) : 34; camera.updateProjectionMatrix(); if (composer) composer.setSize(w, h); poke(); } }
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
  if (photo.on) { photoFrame(); requestAnimationFrame(tick); return; }
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
  if (chargeLocal && byId.charge_flap) chargeLocal.visible = Math.abs(byId.charge_flap.ang) > 0.08;
  if (hvPulse) { const a = 0.35 + 0.35 * Math.sin(performance.now() / 220); parts.forEach(p => { if (has(p, 'hv') && p.id !== selected) p.obj.traverse(o => { if (o.isMesh && o.material.emissive) { if (!o.userData.hvm) { o.userData.hvm = o.material; o.material = o.material.clone(); } o.material.emissive = HVC; o.material.emissiveIntensity = a; } }); }); }
  else parts.forEach(p => { if (has(p, 'hv')) p.obj.traverse(o => { if (o.isMesh && o.userData.hvm) { o.material = o.userData.hvm; delete o.userData.hvm; } }); });
  if (fly) { const f = REDUCED ? 1 : 1 - Math.pow(0.02, dt); camera.position.lerp(fly.p, f); controls.target.lerp(fly.t, f); if (camera.position.distanceTo(fly.p) < 0.01) fly = null; }
  keepCameraSane();
  controls.update();
  let moving = moved || !!fly || hvPulse || Math.abs(liftT - liftY) > 1e-4;
  if (!moving) for (const p of parts) if (p.svc.distanceToSquared(p.svcT) > 1e-9) { moving = true; break; }
  const now = performance.now();
  if (moving) poke();
  if (now - idleSince < 200 || aoOff) { renderer.render(scene, camera); }
  else if (!polished) { try { if (!composer) makeComposer(); composer.render(); } catch (e) { console.warn('ambient occlusion off on this GPU', e); aoOff = true; renderer.render(scene, camera); } polished = true; }
  requestAnimationFrame(tick);
}

/* ───────── photoreal: progressive path tracing of the current view ─────────
   Loaded on first use. Every sample traces light bouncing round the studio, so
   shadows, reflections and bounced light are physically based; it sharpens the
   longer it runs. Any interaction hands back to the live model. */
const photo = { on: false, busy: false, pt: null, cam: null, dl: null, save: false, max: 1200, keep: null };
const RASTER_ONLY = [glow, shadowPlane, contact];
const photoBtn = $('#photo'), saveBtn = $('#savephoto'), badge = $('#photobadge');
(async () => { try { if (!window.claude?.use) return; photo.dl = await window.claude.use('downloads'); saveBtn.hidden = !photo.dl; } catch (e) { /* saving not offered here */ } })();
const nextFrame = () => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
function photoCamera() {
  const c = photo.cam; c.fov = camera.fov; c.aspect = camera.aspect; c.near = camera.near; c.far = camera.far;
  c.position.copy(camera.position); c.quaternion.copy(camera.quaternion);
  const v = camera.view; if (v?.enabled) c.setViewOffset(v.fullWidth, v.fullHeight, v.offsetX, v.offsetY, v.width, v.height); else c.clearViewOffset();
  c.updateProjectionMatrix(); c.updateMatrixWorld(true);
  c.focusDistance = camera.position.distanceTo(controls.target);
  if ($('#dof').checked) c.fStop = 2.8; else c.bokehSize = 0;
}
async function startPhoto() {
  if (photo.on || photo.busy) return;
  photo.busy = true; clearInterval(seq); fly = null;
  photoBtn.disabled = true; photoBtn.textContent = 'Setting up the studio…';
  await nextFrame();
  try {
    if (!photo.pt) {
      const { WebGLPathTracer, PhysicalCamera } = await import('three-gpu-pathtracer');
      photo.pt = new WebGLPathTracer(renderer);
      Object.assign(photo.pt, { bounces: 6, filteredGlossyFactor: 0.5, minSamples: 2, fadeDuration: 350, renderDelay: 0, renderScale: Math.min(1, 1.5 / renderer.getPixelRatio()) });
      photo.pt.tiles.set(2, 2); photo.cam = new PhysicalCamera();
    }
    if (selected) setHighlight(selected, false);
    photo.keep = { bg: scene.background, li: [key, fill, rim, under].map(l => l.intensity) };
    RASTER_ONLY.forEach(m => m.visible = false); cyc.box.visible = true;
    scene.background = new THREE.Color(0xd2d5d8);
    key.intensity *= 0.3; fill.intensity = rim.intensity = under.intensity = 0;   // the light wall, softbox and HDRI do the lighting
    photoCamera();
    photo.pt.setScene(scene, photo.cam);
    photo.on = true; badge.hidden = false; saveBtn.disabled = true; $('.toolbar').hidden = true; $('#sheet').hidden = false;
    $('#photon').textContent = 'Photoreal'; $('#photos').textContent = 'starting';
    photoBtn.textContent = 'Stop';
  } catch (e) {
    console.error(e); restoreLive(); toast('Photoreal rendering is not available on this device or browser.', true);
  }
  photoBtn.disabled = false; photo.busy = false;
}
function restoreLive() {
  if (photo.keep) { scene.background = photo.keep.bg; [key, fill, rim, under].forEach((l, i) => l.intensity = photo.keep.li[i]); photo.keep = null; }
  RASTER_ONLY.forEach(m => m.visible = true); cyc.box.visible = false;
  photo.on = false; badge.hidden = true; saveBtn.disabled = true; $('.toolbar').hidden = !manual && !(training && trayWanted); photoBtn.textContent = 'Take photo';
  if (selected) setHighlight(selected, true); poke();
}
function stopPhoto() { if (photo.on) restoreLive(); }
function photoFrame() {
  const pt = photo.pt;
  if (pt.samples < photo.max || photo.save) pt.renderSample();
  const n = Math.floor(pt.samples);
  $('#photos').textContent = n < photo.max ? `sharpening · ${n}` : `finished · ${n}`;
  saveBtn.disabled = n < 24;
  if (photo.save) {
    photo.save = false;
    const b64 = renderer.domElement.toDataURL('image/png').split(',')[1], bin = atob(b64), bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    photo.dl.save({ filename: 'golf-mk8-ehybrid-photoreal.png', data: new Blob([bytes], { type: 'image/png' }) })
      .then(r => { if (r.status === 'saved') toast('Photo saved.'); })
      .catch(e => { if (e?.code === 'declined') return; toast(e?.code === 'rate_limited' ? 'A save is already waiting for your answer.' : 'The photo could not be saved in this view.', true); });
  }
}
photoBtn.onclick = () => photo.on ? stopPhoto() : startPhoto();
saveBtn.onclick = () => { if (photo.on && photo.dl) photo.save = true; };
$('#dof').onchange = () => { if (!photo.on) return; photoCamera(); photo.pt.updateCamera(); };
controls.addEventListener('start', stopPhoto);
document.addEventListener('pointerdown', e => { if (photo.on && !e.target.closest('#photo, #savephoto, label[for="dof"], #photobadge')) stopPhoto(); }, true);
document.addEventListener('keydown', e => { if (photo.on && e.key === 'Escape') stopPhoto(); });

/* ───────── load ───────── */
const loader = new GLTFLoader(); loader.setMeshoptDecoder(MeshoptDecoder);
loader.load(GOLF.url, gltf => {
  try {
    $('#loadtext').textContent = 'Fitting the engine bay, gearbox and hybrid parts…';
    const meas = buildCar(gltf.scene);
    buildBay(meas);
    buildHybridParts();
    buildCorners();
    buildChargePort();
    for (const f of buildCarFasteners(byId, materialFactory)) { carRoot.add(f.obj); register({ ...f, ex: byId[f.host].ex.clone(), ...info(f) }); BLOCK[f.host] = [...(BLOCK[f.host] || []), f.id]; }
    BLOCK.timing_cover = ['bolts_timing_cover'];
    // bonnet up by default, so the bay reads at a glance
    const bon = byId.panel_bonnet; if (bon) { bon.ang = bon.angT = HINGE.panel_bonnet.ang * DEG; bon.obj.rotation.x = bon.ang; }
    buildTree(); buildTray(); applyStep(); refreshRows(); setOpacity(+$('#xray').value); renderCard();
    TRN = createTraining(W);
    setDetent(0); updateViewOffset(); if (camera.aspect < 1) { camera.position.copy(fit(camera.position, controls.target)); }
    $('#loading').hidden = true;
    if (new URLSearchParams(location.search).has('debug')) window.__ws = { parts, byId, BLOCK, THREE, camera, controls, flyTo, photo, doAll, plan, setMode, get TRN() { return TRN; }, W, startPhoto, stopPhoto, scene, renderer, select, removePart, refitPart, boltAction, fitBolts, setTool: k => { tool = k; }, setTq: (n, a) => { tqSet = n; if (a) angSet = a; } };
  } catch (e) { console.error(e); $('#loadtext').textContent = 'The car loaded but could not be assembled. Reload to try again.'; }
}, x => { const t = x.total || 6570544; $('#loadtext').textContent = `Loading the Golf · ${(x.loaded / 1048576).toFixed(1)} of ${(t / 1048576).toFixed(1)} MB`; $('#bar').style.transform = `scaleX(${Math.min(1, x.loaded / t).toFixed(3)})`; },
  e => { console.error(e); $('#loadtext').textContent = 'The Golf could not be loaded. Check the connection and reload.'; });
tick();
