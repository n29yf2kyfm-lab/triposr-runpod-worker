// GLB Studio — fix what the GLB machine got wrong on a car, by hand.
// Open a rigged car, select a panel (it grows to the nearest crease or shut
// line), say what it is (bonnet, tailgate, a door, body, remove), choose
// where it hinges, build. The server applies the edits to the rigger's own
// parts (edits.py) and finishes the car again (finish.py).
// ExpertCarCheck. Proprietary: see ../LICENSE.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';

const $ = s => document.querySelector(s);
const enc = encodeURIComponent;

// ── parts ────────────────────────────────────────────────────────────────
// what a selection can become, with the colour it shows in and a key
const TARGETS = [            // id, button label, colour, key, full name
  ['panel_bonnet', 'Bonnet', '#ff8c42', 'B', 'Bonnet'],
  ['tailgate', 'Tailgate', '#4aa8e8', 'T', 'Tailgate'],
  ['door_fl', 'Door FL', '#6cc070', '1', 'Front left door'],
  ['door_fr', 'Door FR', '#b07be0', '2', 'Front right door'],
  ['door_rl', 'Door RL', '#2fb8a6', '3', 'Rear left door'],
  ['door_rr', 'Door RR', '#e077c0', '4', 'Rear right door'],
  ['body', 'Body', '#8b939c', '0', 'Body'],
  ['drop', 'Remove', '#ef5b5b', 'Del', 'Removed'],
];
const OTHER = [[/^wheel/, '#41464d'], [/^glazing/, '#a8d8ea'], [/^cabin|^steering/, '#7d7266'],
  [/^lamps/, '#e8dfb0'], [/^engine/, '#9b6b4a'], [/^brake/, '#7a4c4c']];
const SEL = [255, 228, 92];
const HINGE = {               // part -> [edges (first is the machine's default), default degrees]
  door: [['front', 'rear'], 65], panel_bonnet: [['rear', 'front'], 55], tailgate: [['top', 'bottom', 'left', 'right'], 75],
};
const hingeOf = p => p.startsWith('door_') ? HINGE.door : HINGE[p];
const hingeKey = p => p === 'panel_bonnet' ? 'bonnet' : p;   // the finisher's name

const ids = [], codes = new Map(), rgb = [];
function codeOf(id) {
  if (!codes.has(id)) {
    codes.set(id, ids.length); ids.push(id);
    const t = TARGETS.find(x => x[0] === id);
    const hex = t ? t[2] : (OTHER.find(([re]) => re.test(id)) || [0, '#70767d'])[1];
    const c = new THREE.Color(hex); rgb.push([c.r * 255, c.g * 255, c.b * 255].map(Math.round));
  }
  return codes.get(id);
}
TARGETS.forEach(t => codeOf(t[0]));
const labelOf = id => (TARGETS.find(t => t[0] === id) || [0, 0, 0, 0, id.replace(/^panel_/, '').replace(/_/g, ' ')
  .replace(/\b(f|r)(l|r)\b/, (m, a, b) => (a === 'f' ? 'front ' : 'rear ') + (b === 'l' ? 'L' : 'R'))
  .replace(/^./, c => c.toUpperCase())])[4];
const hexOf = id => '#' + rgb[codeOf(id)].map(v => v.toString(16).padStart(2, '0')).join('');

// ── state ────────────────────────────────────────────────────────────────
const S = {
  key: null, item: null, recs: [], groups: new Map(), mode: 'edit', look: 'car', tool: 'panel',
  crease: 30, sameMat: true, hinges: {}, hidden: new Set(), history: [], dirty: false,
  edit: null, result: null, mixer: null, actions: {}, carBuf: null,
  views: {},                  // each view keeps its own camera: the finisher moves and rescales the car
};

// ── API (with the licence key when the machine asks for one) ────────────
let KEY = '';
try { KEY = localStorage.getItem('glbKey') || ''; } catch { /* private window */ }
async function api(path, opt = {}) {
  const headers = Object.assign({}, opt.headers || {});
  if (KEY) headers.Authorization = 'Bearer ' + KEY;
  const r = await fetch(path, Object.assign({}, opt, { headers }));
  if (r.status === 401) { await askKey(); return api(path, opt); }
  if (!r.ok) {
    let e = r.statusText;
    try { e = (await r.json()).error || e; } catch { /* not JSON */ }
    throw new Error(e);
  }
  return r;
}
function askKey() {
  return new Promise(res => {
    const d = $('#keyDlg');
    d.onclose = () => { KEY = $('#keyInput').value.trim(); try { localStorage.setItem('glbKey', KEY); } catch { /* */ } res(); };
    d.showModal();
  });
}

// ── scene ────────────────────────────────────────────────────────────────
const canvas = $('#c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.toneMapping = THREE.ACESFilmicToneMapping;
const scene = new THREE.Scene();
scene.background = new THREE.Color('#202327');
scene.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;
const sun = new THREE.DirectionalLight(0xffffff, 1.3); sun.position.set(3, 6, 4); scene.add(sun);
const grid = new THREE.GridHelper(12, 24, 0x3a3f45, 0x2a2e33); scene.add(grid);
const camera = new THREE.PerspectiveCamera(35, 1, 0.02, 200);
camera.position.set(5, 3, 6);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
const partsMat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.7, metalness: 0, side: THREE.DoubleSide });
const overlayMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(...SEL.map(v => v / 255)), transparent: true, opacity: 0.55,
  depthTest: true, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
let overlay = null;
const gizmos = new THREE.Group(); gizmos.renderOrder = 10; scene.add(gizmos);
const clock = new THREE.Clock();

function resize() {
  const r = canvas.parentElement.getBoundingClientRect();
  renderer.setSize(r.width, r.height, false);
  camera.aspect = r.width / Math.max(r.height, 1); camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(canvas.parentElement);
resize();
renderer.setAnimationLoop(() => {
  const dt = clock.getDelta();
  if (S.mixer) S.mixer.update(dt);
  controls.update();
  renderer.render(scene, camera);
});

// ── UI helpers ───────────────────────────────────────────────────────────
function busy(text) { $('#busy').hidden = !text; if (text) $('#busyText').textContent = text; }
let toastT = 0;
function toast(text, bad = false) {
  const t = $('#toast'); t.textContent = text; t.classList.toggle('bad', bad); t.hidden = false;
  clearTimeout(toastT); toastT = setTimeout(() => { t.hidden = true; }, bad ? 7000 : 3500);
}
function hud() {
  const tip = {
    panel: '<b>Click a panel</b>: it grows to the nearest crease or shut line. Shift-click adds, Alt-click takes away.',
    piece: '<b>Click a piece</b>: the whole loose piece of the model. Shift-click adds, Alt-click takes away.',
    box: '<b>Drag a box</b> round what to select (faces turned away are left). Shift adds, Alt takes away. Right-drag turns the car.',
  }[S.tool];
  $('#hud').innerHTML = S.mode === 'edit' && S.recs.length
    ? `${tip} &nbsp;·&nbsp; Drag to turn, right-drag to move, wheel to zoom.`
    : (S.mode === 'result' ? 'The car as built. Open its parts on the right.' : '');
}

// ── library ──────────────────────────────────────────────────────────────
let LIB = [];
async function loadLibrary() {
  LIB = await (await api('/v1/library')).json();
  drawLibrary();
}
function statusOf(c) {
  if (!c.status) return ['', ''];
  if (c.status === 'done') return ['done', 'done'];
  if (c.status === 'check') return ['check', 'check'];
  return ['failed', 'failed'];
}
function drawLibrary() {
  const q = $('#libSearch').value.trim().toLowerCase();
  const ul = $('#libList'); ul.textContent = '';
  for (const c of LIB.filter(c => !q || (c.name + ' ' + c.asset).toLowerCase().includes(q))) {
    const li = document.createElement('li');
    const b = document.createElement('button');
    b.classList.toggle('on', c.key === S.key);
    const [cls, txt] = statusOf(c);
    b.innerHTML = `<span class="n"></span>${c.edited ? '<span class="pill edited">edited</span>' : (cls ? `<span class="pill ${cls}">${txt}</span>` : '<span></span>')}<span class="a"></span>${c.missing && c.missing.length ? '<span class="miss"></span>' : ''}`;
    b.querySelector('.n').textContent = c.name;
    b.querySelector('.a').textContent = c.asset;
    if (c.missing && c.missing.length) b.querySelector('.miss').textContent = 'Missing: ' + c.missing.join(', ');
    b.onclick = () => openCar(c.key);
    li.appendChild(b); ul.appendChild(li);
  }
}
$('#libSearch').oninput = drawLibrary;

// ── opening a car ────────────────────────────────────────────────────────
function disposeGroup(g) {
  if (!g) return;
  scene.remove(g);
  g.traverse(o => { if (o.geometry) o.geometry.dispose(); });
}
async function openCar(key) {
  if (S.dirty && !confirm('Leave this car without building it? The edits are lost.')) return;
  busy('Loading the car');
  try {
    disposeGroup(S.edit); disposeGroup(S.result); S.edit = S.result = null; S.mixer = null; S.carBuf = null; S.views = {}; S.mode = 'edit';
    S.recs = []; S.groups = new Map(); S.history = []; S.hidden = new Set(); S.dirty = false;
    S.key = key; S.item = LIB.find(c => c.key === key) || { name: key, asset: key };
    $('#empty').hidden = true;
    const buf = await (await api(`/v1/library/${enc(key)}/rig.glb`)).arrayBuffer();
    const gltf = await new GLTFLoader().parseAsync(buf, '');
    const edits = await (await api(`/v1/library/${enc(key)}/edits`)).json();
    S.edit = gltf.scene; scene.add(S.edit);
    buildRecords(gltf);
    applyEdits(edits);
    S.hinges = edits.hinges || {};
    S.dirty = false;
    frameCar(S.edit);
    setMode('edit');
    refreshAll();
    drawLibrary();
    $('#carName').textContent = S.item.name;
    showState();
    $('#resetBtn').disabled = !S.item.edited;
  } catch (e) {
    toast('Could not open the car: ' + e.message, true);
  } finally { busy(''); }
}

function showState() {
  const [cls, txt] = statusOf(S.item);
  $('#carState').hidden = !cls; $('#carState').className = 'pill ' + cls; $('#carState').textContent = txt;
}

// every primitive of the rig file becomes a record with per-triangle part
// and selection arrays; the geometry is made non-indexed so each triangle
// can carry its own colour
function buildRecords(gltf) {
  const json = gltf.parser.json, assoc = gltf.parser.associations;
  gltf.scene.updateMatrixWorld(true);
  const meshes = [];
  gltf.scene.traverse(o => { if (o.isMesh) meshes.push(o); });
  const byNode = new Map();
  for (const m of meshes) {
    const a = assoc.get(m) || {};
    const ni = a.nodes !== undefined ? a.nodes : (assoc.get(m.parent) || {}).nodes;
    const node = json.nodes[ni].name || '';
    const own = (node.match(/^SB_(.+?)(__\d+)?$/) || [0, 'body'])[1];
    const g0 = m.geometry;
    if (!g0.index) g0.setIndex([...Array(g0.attributes.position.count).keys()]);
    const idx = Uint32Array.from(g0.index.array);
    const pos0 = g0.attributes.position.array.slice();
    const n = idx.length / 3;
    const g1 = g0.toNonIndexed();
    g1.setAttribute('color', new THREE.BufferAttribute(new Uint8Array(n * 9), 3, true));
    m.geometry = g1; g0.dispose();
    const isCard = (m.material && m.material.name) === 'SB_door_inner';
    const P = g1.attributes.position.array, e = m.matrixWorld.elements;
    const cent = new Float32Array(n * 3), nrm = new Float32Array(n * 3), area = new Float32Array(n);
    const w = new Float32Array(9);
    for (let t = 0; t < n; t++) {
      for (let k = 0; k < 3; k++) {
        const x = P[9 * t + 3 * k], y = P[9 * t + 3 * k + 1], z = P[9 * t + 3 * k + 2];
        w[3 * k] = e[0] * x + e[4] * y + e[8] * z + e[12];
        w[3 * k + 1] = e[1] * x + e[5] * y + e[9] * z + e[13];
        w[3 * k + 2] = e[2] * x + e[6] * y + e[10] * z + e[14];
      }
      cent[3 * t] = (w[0] + w[3] + w[6]) / 3; cent[3 * t + 1] = (w[1] + w[4] + w[7]) / 3; cent[3 * t + 2] = (w[2] + w[5] + w[8]) / 3;
      const ax = w[3] - w[0], ay = w[4] - w[1], az = w[5] - w[2], bx = w[6] - w[0], by = w[7] - w[1], bz = w[8] - w[2];
      let cx = ay * bz - az * by, cy = az * bx - ax * bz, cz = ax * by - ay * bx;
      const l = Math.hypot(cx, cy, cz); area[t] = l / 2;
      if (l > 0) { cx /= l; cy /= l; cz /= l; }
      nrm[3 * t] = cx; nrm[3 * t + 1] = cy; nrm[3 * t + 2] = cz;
    }
    const rec = { mesh: m, node, prim: a.primitives || 0, own: codeOf(own), isCard, n, idx, pos0,
      part: new Uint8Array(n).fill(codeOf(own)), sel: new Uint8Array(n), selCount: 0, cent, nrm, area,
      carMat: m.material, matKey: m.material ? m.material.uuid : '', drawn: null, card: null, world: e.slice() };
    m.userData.rec = rec;
    S.recs.push(rec);
    if (!byNode.has(node)) byNode.set(node, []);
    byNode.get(node).push(rec);
  }
  // a door's dark inner card follows its skin, triangle for triangle
  for (const list of byNode.values()) {
    list.sort((a, b) => a.prim - b.prim);
    let skin = null;
    for (const r of list) {
      if (r.isCard && skin && skin.n === r.n) skin.card = r;
      else if (!r.isCard) skin = r;
    }
    S.groups.set(list[0].node, { recs: list.filter(r => !r.isCard), adj: null });
  }
}

function applyEdits(edits) {
  for (const a of edits.assign || []) {
    const r = S.recs.find(x => x.node === a.node && x.prim === a.prim && !x.isCard);
    if (!r) continue;
    for (const [s, c, p] of a.runs) {
      const code = codeOf(p);
      r.part.fill(code, s, Math.min(s + c, r.n));
      if (r.card) r.card.part.fill(code, s, Math.min(s + c, r.n));
    }
  }
}

function exportEdits() {
  const assign = [];
  for (const r of S.recs) {
    if (r.isCard) continue;
    const runs = [];
    for (let t = 0; t < r.n;) {
      if (r.part[t] === r.own) { t++; continue; }
      const p = r.part[t], s = t;
      while (t < r.n && r.part[t] === p) t++;
      runs.push([s, t - s, ids[p]]);
    }
    if (runs.length) assign.push({ node: r.node, prim: r.prim, runs });
  }
  const hinges = {};
  for (const [k, v] of Object.entries(S.hinges)) if (v && v.edge) hinges[k] = v;
  return { version: 1, assign, hinges };
}

function frameCar(obj) {
  const b = new THREE.Box3().setFromObject(obj), c = b.getCenter(new THREE.Vector3()), s = b.getSize(new THREE.Vector3());
  const d = Math.max(s.x, s.y, s.z) * 1.35;
  controls.target.copy(c);
  camera.position.set(c.x + d * 0.75, c.y + d * 0.42, c.z + d * 0.85);
  camera.near = d / 200; camera.far = d * 30; camera.updateProjectionMatrix();
  grid.position.y = b.min.y;
}

// ── drawing: colours, hidden parts, the selection overlay, hinge lines ──
const visibleCode = c => !(S.hidden.has(ids[c]) || (S.look === 'car' && ids[c] === 'drop'));
function paint(r) {
  const col = r.mesh.geometry.attributes.color.array;
  for (let t = 0; t < r.n; t++) {
    const c = r.sel[t] ? SEL : rgb[r.part[t]];
    for (let k = 0; k < 3; k++) { const o = 9 * t + 3 * k; col[o] = c[0]; col[o + 1] = c[1]; col[o + 2] = c[2]; }
  }
  r.mesh.geometry.attributes.color.needsUpdate = true;
}
function updateDraw(r) {
  let all = true;
  for (let t = 0; t < r.n; t++) if (!visibleCode(r.part[t])) { all = false; break; }
  const g = r.mesh.geometry;
  if (all) { if (g.index) g.setIndex(null); r.drawn = null; return; }
  const kept = [];
  for (let t = 0; t < r.n; t++) if (visibleCode(r.part[t])) kept.push(t);
  r.drawn = Uint32Array.from(kept);
  const ix = new Uint32Array(kept.length * 3);
  for (let i = 0; i < kept.length; i++) { ix[3 * i] = 3 * kept[i]; ix[3 * i + 1] = 3 * kept[i] + 1; ix[3 * i + 2] = 3 * kept[i] + 2; }
  g.setIndex(new THREE.BufferAttribute(ix, 1));
  r.mesh.visible = kept.length > 0;
}
function setLook(look) {
  S.look = look;
  for (const b of document.querySelectorAll('#lookSeg button')) b.classList.toggle('on', b.dataset.l === look);
  for (const r of S.recs) { r.mesh.material = look === 'parts' ? partsMat : r.carMat; updateDraw(r); }
  drawOverlay();
}
function drawOverlay() {
  if (overlay) { scene.remove(overlay); overlay.geometry.dispose(); overlay = null; }
  if (S.look !== 'car' || S.mode !== 'edit') return;
  let n = 0;
  for (const r of S.recs) n += r.selCount;
  if (!n) return;
  const P = new Float32Array(n * 9); let o = 0;
  for (const r of S.recs) {
    if (!r.selCount) continue;
    const src = r.mesh.geometry.attributes.position.array, e = r.world;
    for (let t = 0; t < r.n; t++) {
      if (!r.sel[t]) continue;
      for (let k = 0; k < 3; k++) {
        const x = src[9 * t + 3 * k], y = src[9 * t + 3 * k + 1], z = src[9 * t + 3 * k + 2];
        P[o++] = e[0] * x + e[4] * y + e[8] * z + e[12];
        P[o++] = e[1] * x + e[5] * y + e[9] * z + e[13];
        P[o++] = e[2] * x + e[6] * y + e[10] * z + e[14];
      }
    }
  }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(P, 3));
  overlay = new THREE.Mesh(g, overlayMat); overlay.renderOrder = 5; scene.add(overlay);
}

// the hinge each part will get, by the finisher's own rule (finish.hinge_line)
function hingeLine(part, lo, hi, edge, deg) {
  const [edges, d0] = hingeOf(part);
  edge = edge || edges[0]; deg = Math.abs(deg || d0);
  if (part.startsWith('door_')) {
    const left = (lo.x + hi.x) / 2 > 0, x = left ? hi.x - 0.03 : lo.x + 0.03, z = edge === 'rear' ? lo.z + 0.03 : hi.z - 0.03;
    return { a: new THREE.Vector3(x, lo.y, z), b: new THREE.Vector3(x, hi.y, z) };
  }
  if (part === 'tailgate') {
    if (edge === 'bottom') return { a: new THREE.Vector3(lo.x, lo.y + 0.01, lo.z + 0.01), b: new THREE.Vector3(hi.x, lo.y + 0.01, lo.z + 0.01) };
    if (edge === 'left' || edge === 'right') {
      const x = edge === 'left' ? hi.x - 0.02 : lo.x + 0.02;
      return { a: new THREE.Vector3(x, lo.y, lo.z + 0.02), b: new THREE.Vector3(x, hi.y, lo.z + 0.02) };
    }
    return { a: new THREE.Vector3(lo.x, hi.y - 0.01, hi.z - 0.01), b: new THREE.Vector3(hi.x, hi.y - 0.01, hi.z - 0.01) };
  }
  const z = edge === 'front' ? hi.z - 0.02 : lo.z + 0.02;
  return { a: new THREE.Vector3(lo.x, hi.y - 0.01, z), b: new THREE.Vector3(hi.x, hi.y - 0.01, z) };
}
function partBox(code) {
  const lo = new THREE.Vector3(Infinity, Infinity, Infinity), hi = new THREE.Vector3(-Infinity, -Infinity, -Infinity);
  let any = false;
  for (const r of S.recs) {
    const P = r.mesh.geometry.attributes.position.array, e = r.world;
    for (let t = 0; t < r.n; t++) {
      if (r.part[t] !== code) continue;
      any = true;
      for (let k = 0; k < 3; k++) {
        const x = P[9 * t + 3 * k], y = P[9 * t + 3 * k + 1], z = P[9 * t + 3 * k + 2];
        const wx = e[0] * x + e[4] * y + e[8] * z + e[12], wy = e[1] * x + e[5] * y + e[9] * z + e[13], wz = e[2] * x + e[6] * y + e[10] * z + e[14];
        lo.x = Math.min(lo.x, wx); lo.y = Math.min(lo.y, wy); lo.z = Math.min(lo.z, wz);
        hi.x = Math.max(hi.x, wx); hi.y = Math.max(hi.y, wy); hi.z = Math.max(hi.z, wz);
      }
    }
  }
  return any ? [lo, hi] : null;
}
function drawGizmos() {
  for (const c of [...gizmos.children]) { gizmos.remove(c); c.geometry.dispose(); c.material.dispose(); }
  if (S.mode !== 'edit') return;
  for (const part of ['panel_bonnet', 'tailgate', 'door_fl', 'door_fr', 'door_rl', 'door_rr']) {
    const box = partBox(codeOf(part));
    if (!box) continue;
    const h = S.hinges[hingeKey(part)] || {};
    const { a, b } = hingeLine(part, box[0], box[1], h.edge, h.deg);
    const len = a.distanceTo(b);
    if (!(len > 0)) continue;
    const mat = new THREE.MeshBasicMaterial({ color: hexOf(part), depthTest: false, transparent: true, opacity: 0.95 });
    const cyl = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, len, 10), mat);
    cyl.position.copy(a).add(b).multiplyScalar(0.5);
    cyl.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.clone().sub(a).normalize());
    cyl.renderOrder = 10;
    gizmos.add(cyl);
    for (const p of [a, b]) {
      const s = new THREE.Mesh(new THREE.SphereGeometry(0.025, 12, 8), mat.clone());
      s.position.copy(p); s.renderOrder = 10; gizmos.add(s);
    }
  }
}

// ── the parts list and the target buttons ───────────────────────────────
function counts() {
  const n = new Array(ids.length).fill(0);
  for (const r of S.recs) if (!r.isCard) for (let t = 0; t < r.n; t++) n[r.part[t]]++;
  return n;
}
function drawParts() {
  const n = counts();
  const ul = $('#partsList'); ul.textContent = '';
  const order = [...ids.keys()].filter(c => n[c] > 0 || ['panel_bonnet', 'tailgate'].includes(ids[c]))
    .sort((a, b) => (TARGETS.findIndex(t => t[0] === ids[a]) + 99) % 99 - (TARGETS.findIndex(t => t[0] === ids[b]) + 99) % 99 || n[b] - n[a]);
  for (const c of order) {
    const id = ids[c];
    const li = document.createElement('li');
    li.innerHTML = `<div class="ph"><span class="sw"></span><button class="name" title="Select all of it"></button><span class="cnt"></span><button class="eye" title="Show or hide">◉</button></div>`;
    li.querySelector('.sw').style.background = hexOf(id);
    li.querySelector('.name').textContent = labelOf(id);
    li.querySelector('.cnt').textContent = n[c] ? n[c].toLocaleString() : 'none';
    const eye = li.querySelector('.eye');
    eye.setAttribute('aria-pressed', String(!S.hidden.has(id)));
    eye.setAttribute('aria-label', (S.hidden.has(id) ? 'Show ' : 'Hide ') + labelOf(id));
    eye.onclick = () => { S.hidden.has(id) ? S.hidden.delete(id) : S.hidden.add(id); S.recs.forEach(updateDraw); drawParts(); };
    li.querySelector('.name').onclick = e => selectPart(c, mods(e));
    const hg = hingeOf(id);
    if (hg && n[c]) {
      const h = S.hinges[hingeKey(id)] || {};
      const row = document.createElement('div'); row.className = 'hinge';
      row.innerHTML = `Hinge <select aria-label="Hinge edge"></select><input type="number" min="5" max="120" step="5" aria-label="Opens by, degrees">°`;
      const sel = row.querySelector('select');
      for (const ed of hg[0]) { const o = document.createElement('option'); o.value = ed; o.textContent = ed + ' edge'; sel.appendChild(o); }
      sel.value = h.edge || hg[0][0];
      const deg = row.querySelector('input'); deg.value = h.deg || hg[1];
      const save = () => {
        S.hinges[hingeKey(id)] = { edge: sel.value, deg: Math.min(120, Math.max(5, +deg.value || hg[1])) };
        setDirty(); drawGizmos();
      };
      sel.onchange = save; deg.onchange = save;
      li.appendChild(row);
    }
    ul.appendChild(li);
  }
}
function drawTargets() {
  const box = $('#targets'); box.textContent = '';
  for (const [id, label, , k] of TARGETS) {
    const b = document.createElement('button');
    b.innerHTML = `<span class="sw"></span><span></span><kbd>${k}</kbd>`;
    b.querySelector('.sw').style.background = hexOf(id);
    b.querySelector('span:nth-child(2)').textContent = label;
    b.disabled = !selTotal();
    b.onclick = () => assign(id);
    box.appendChild(b);
  }
}
const selTotal = () => S.recs.reduce((s, r) => s + r.selCount, 0);
function drawSelInfo() {
  let n = 0, a = 0;
  for (const r of S.recs) if (r.selCount) for (let t = 0; t < r.n; t++) if (r.sel[t]) { n++; a += r.area[t]; }
  const el = $('#selCount');
  el.textContent = n ? `${n.toLocaleString()} faces · ${a.toFixed(2)} m²` : 'Nothing selected';
  el.classList.toggle('has', n > 0);
  $('#clearSel').disabled = !n;
  $('#undoBtn').disabled = !S.history.length;
  for (const b of document.querySelectorAll('#targets button')) b.disabled = !n;
}
function refreshAll() {
  for (const r of S.recs) { paint(r); updateDraw(r); r.mesh.material = S.look === 'parts' ? partsMat : r.carMat; }
  drawOverlay(); drawGizmos(); drawParts(); drawTargets(); drawSelInfo(); hud();
}
function setDirty() { S.dirty = true; $('#buildBtn').disabled = false; }

// ── selecting ────────────────────────────────────────────────────────────
const mods = e => (e.shiftKey ? 'add' : (e.altKey || e.ctrlKey || e.metaKey) ? 'remove' : 'replace');
function applySelection(list, op) {          // list: [[rec, Uint32Array of triangles], ...]
  if (op === 'replace') for (const r of S.recs) if (r.selCount) { r.sel.fill(0); r.selCount = 0; paint(r); }
  const v = op === 'remove' ? 0 : 1;
  for (const [r, tris] of list) {
    for (const t of tris) {
      if (r.sel[t] !== v) { r.sel[t] = v; r.selCount += v ? 1 : -1; }
    }
    paint(r);
  }
  drawOverlay(); drawSelInfo();
}
function clearSelection() { applySelection([], 'replace'); }
function selectPart(code, op) {
  const list = [];
  for (const r of S.recs) {
    if (r.isCard) continue;
    const tris = [];
    for (let t = 0; t < r.n; t++) if (r.part[t] === code) tris.push(t);
    if (tris.length) list.push([r, Uint32Array.from(tris)]);
  }
  applySelection(list, op);
}

// welded neighbours inside one node of the rig (the rigger's own objects):
// faces that share an edge, as Blender's islands and the rigger see them
function adjacency(G) {
  if (G.adj) return G.adj;
  const offs = []; let N = 0;
  for (const r of G.recs) { offs.push(N); N += r.n; }
  const vmap = new Map(); let nv = 0;
  const tv = new Uint32Array(N * 3);
  const q = v => Math.min(199999, Math.max(0, Math.round(v * 1e4) + 100000));
  G.recs.forEach((r, ri) => {
    const p = r.pos0, ix = r.idx;
    for (let t = 0; t < r.n; t++) for (let k = 0; k < 3; k++) {
      const v = ix[3 * t + k];
      const key = (q(p[3 * v]) * 200000 + q(p[3 * v + 1])) * 200000 + q(p[3 * v + 2]);
      let id = vmap.get(key);
      if (id === undefined) { id = nv++; vmap.set(key, id); }
      tv[(offs[ri] + t) * 3 + k] = id;
    }
  });
  const em = new Map(), pa = [], pb = [];
  for (let t = 0; t < N; t++) for (let k = 0; k < 3; k++) {
    const a = tv[3 * t + k], b = tv[3 * t + (k + 1) % 3];
    if (a === b) continue;
    const key = a < b ? a * nv + b : b * nv + a;
    const f = em.get(key);
    if (f === undefined) em.set(key, t); else { pa.push(f); pb.push(t); }
  }
  const deg = new Uint32Array(N + 1);
  for (let i = 0; i < pa.length; i++) { deg[pa[i] + 1]++; deg[pb[i] + 1]++; }
  for (let i = 0; i < N; i++) deg[i + 1] += deg[i];
  const nb = new Uint32Array(deg[N]), fill = deg.slice(0, N);
  for (let i = 0; i < pa.length; i++) { nb[fill[pa[i]]++] = pb[i]; nb[fill[pb[i]]++] = pa[i]; }
  const recOf = new Uint16Array(N);
  G.recs.forEach((r, ri) => recOf.fill(ri, offs[ri], offs[ri] + r.n));
  G.adj = { N, offs, deg, nb, recOf };
  return G.adj;
}
function grow(rec, tri, mode) {
  const G = S.groups.get(rec.node), A = adjacency(G);
  const ri0 = G.recs.indexOf(rec), seed = A.offs[ri0] + tri;
  const cos = Math.cos(S.crease * Math.PI / 180);
  const seen = new Uint8Array(A.N), queue = new Uint32Array(A.N);
  let head = 0, tail = 0;
  seen[seed] = 1; queue[tail++] = seed;
  while (head < tail) {
    const g = queue[head++];
    const ra = G.recs[A.recOf[g]], ta = g - A.offs[A.recOf[g]];
    for (let i = A.deg[g]; i < A.deg[g + 1]; i++) {
      const h = A.nb[i];
      if (seen[h]) continue;
      const rb = G.recs[A.recOf[h]], tb = h - A.offs[A.recOf[h]];
      if (!visibleCode(rb.part[tb])) continue;
      if (mode === 'panel') {
        if (S.sameMat && ra.matKey !== rb.matKey) continue;
        const d = ra.nrm[3 * ta] * rb.nrm[3 * tb] + ra.nrm[3 * ta + 1] * rb.nrm[3 * tb + 1] + ra.nrm[3 * ta + 2] * rb.nrm[3 * tb + 2];
        if (d < cos) continue;
      }
      seen[h] = 1; queue[tail++] = h;
    }
  }
  const out = new Map();
  for (let i = 0; i < tail; i++) {
    const g = queue[i], ri = A.recOf[g];
    if (!out.has(ri)) out.set(ri, []);
    out.get(ri).push(g - A.offs[ri]);
  }
  return [...out].map(([ri, l]) => [G.recs[ri], Uint32Array.from(l)]);
}

const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
function pickAt(cx, cy) {
  const r = canvas.getBoundingClientRect();
  ndc.set(((cx - r.left) / r.width) * 2 - 1, -((cy - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(ndc, camera);
  const hits = ray.intersectObjects(S.recs.filter(x => !x.isCard && x.mesh.visible).map(x => x.mesh), false);
  for (const h of hits) {
    const rec = h.object.userData.rec;
    const t = rec.drawn ? rec.drawn[h.faceIndex] : h.faceIndex;
    if (t !== undefined && visibleCode(rec.part[t])) return [rec, t];
  }
  return null;
}
function clickSelect(cx, cy, op) {
  const hit = pickAt(cx, cy);
  if (!hit) { if (op === 'replace') clearSelection(); return 0; }
  const list = grow(hit[0], hit[1], S.tool === 'piece' ? 'piece' : 'panel');
  applySelection(list, op);
  return list.reduce((s, [, l]) => s + l.length, 0);
}
function boxSelect(x0, y0, x1, y1, op) {
  const r = canvas.getBoundingClientRect();
  const [ax, bx] = [Math.min(x0, x1) - r.left, Math.max(x0, x1) - r.left], [ay, by] = [Math.min(y0, y1) - r.top, Math.max(y0, y1) - r.top];
  camera.updateMatrixWorld();
  const m = new THREE.Matrix4().multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse).elements;
  const cp = camera.position;
  const list = [];
  for (const rec of S.recs) {
    if (rec.isCard || !rec.mesh.visible) continue;
    const C = rec.cent, N = rec.nrm, tris = [];
    for (let t = 0; t < rec.n; t++) {
      if (!visibleCode(rec.part[t])) continue;
      const x = C[3 * t], y = C[3 * t + 1], z = C[3 * t + 2];
      if ((x - cp.x) * N[3 * t] + (y - cp.y) * N[3 * t + 1] + (z - cp.z) * N[3 * t + 2] >= 0) continue;
      const w = m[3] * x + m[7] * y + m[11] * z + m[15];
      if (w <= 0) continue;
      const sx = ((m[0] * x + m[4] * y + m[8] * z + m[12]) / w * 0.5 + 0.5) * r.width;
      const sy = (0.5 - (m[1] * x + m[5] * y + m[9] * z + m[13]) / w * 0.5) * r.height;
      if (sx >= ax && sx <= bx && sy >= ay && sy <= by) tris.push(t);
    }
    if (tris.length) list.push([rec, Uint32Array.from(tris)]);
  }
  applySelection(list, op);
  return list.reduce((s, [, l]) => s + l.length, 0);
}

// ── assigning, undo ──────────────────────────────────────────────────────
function assign(id) {
  const code = codeOf(id), changes = [];
  for (const r of S.recs) {
    if (!r.selCount) continue;
    const tris = [];
    for (let t = 0; t < r.n; t++) if (r.sel[t]) tris.push(t);
    const T = Uint32Array.from(tris), prev = new Uint8Array(T.length);
    T.forEach((t, i) => { prev[i] = r.part[t]; r.part[t] = code; if (r.card) r.card.part[t] = code; });
    r.sel.fill(0); r.selCount = 0;
    changes.push([r, T, prev]);
  }
  if (!changes.length) return;
  S.history.push(changes);
  setDirty(); refreshAll();
  toast(`${changes.reduce((s, c) => s + c[1].length, 0).toLocaleString()} faces are now ${labelOf(id).toLowerCase()}`);
}
function undo() {
  const changes = S.history.pop();
  if (!changes) return;
  for (const [r, T, prev] of changes) T.forEach((t, i) => { r.part[t] = prev[i]; if (r.card) r.card.part[t] = prev[i]; });
  setDirty(); refreshAll();
}

// ── building, resetting, the result ─────────────────────────────────────
async function build() {
  if (!S.key) return;
  busy('Building the car');
  try {
    const r = await (await api(`/v1/library/${enc(S.key)}/edits`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(exportEdits()) })).json();
    S.dirty = false; $('#buildBtn').disabled = true;
    S.lastBuild = r;
    await loadLibrary();
    S.item = LIB.find(c => c.key === S.key) || S.item;
    $('#resetBtn').disabled = !S.item.edited;
    showState();
    disposeGroup(S.result); S.result = null; S.carBuf = null; delete S.views.result;
    await setMode('result');
    const rec = r.record || {};
    toast(rec.status === 'done' ? `Built in ${r.seconds} s: everything opens` : `Built in ${r.seconds} s: ${rec.status}${rec.missing && rec.missing.length ? ', missing ' + rec.missing.join(', ') : ''}`, rec.status !== 'done');
  } catch (e) {
    toast('The build failed: ' + e.message, true);
  } finally { busy(''); }
}
async function resetCar() {
  if (!S.key || !confirm('Throw away every edit on this car and let the machine decide again?')) return;
  busy('Rebuilding without edits');
  try {
    await api(`/v1/library/${enc(S.key)}/reset`, { method: 'POST' });
    S.dirty = false;
    await loadLibrary();
    await openCar(S.key);
  } catch (e) { toast('Could not reset: ' + e.message, true); } finally { busy(''); }
}
async function loadResult() {
  if (S.result) return;
  busy('Loading the built car');
  try {
    if (!S.carBuf) S.carBuf = await (await api(`/v1/library/${enc(S.key)}/car.glb?t=${Date.now()}`)).arrayBuffer();
    const gltf = await new GLTFLoader().setMeshoptDecoder(MeshoptDecoder).parseAsync(S.carBuf.slice(0), '');
    S.result = gltf.scene; S.result.userData.clips = gltf.animations;
    S.mixer = new THREE.AnimationMixer(S.result); S.actions = {};
    const link = $('#download');
    link.href = URL.createObjectURL(new Blob([S.carBuf], { type: 'model/gltf-binary' }));
    link.download = (S.item.asset || 'car') + '.glb'; link.hidden = false;
  } finally { busy(''); }
}
async function drawResultPanel() {
  const box = $('#clips'); box.textContent = '';
  const clips = (S.result && S.result.userData.clips) || [];
  const order = ['all_open', 'doors_open', 'bonnet_open', 'tailgate_open', 'door_fl_open', 'door_fr_open', 'door_rl_open', 'door_rr_open'];
  const names = { all_open: 'Everything', doors_open: 'All doors', bonnet_open: 'Bonnet', tailgate_open: 'Tailgate',
    door_fl_open: 'Front L', door_fr_open: 'Front R', door_rl_open: 'Rear L', door_rr_open: 'Rear R' };
  for (const c of [...clips].sort((a, b) => (order.indexOf(a.name) + 99) % 99 - (order.indexOf(b.name) + 99) % 99)) {
    const b = document.createElement('button');
    b.textContent = names[c.name] || c.name; b.setAttribute('aria-pressed', 'false');
    b.onclick = () => toggleClip(c, b);
    box.appendChild(b);
  }
  if (!clips.length) box.textContent = 'Nothing opens on this car yet.';
  let rec = {};
  try { rec = await (await api(`/v1/library/${enc(S.key)}/record`)).json(); } catch { /* none yet */ }
  const fin = rec.finish || {};
  const rows = [
    ['Status', rec.status || '—'],
    ['Opens', (fin.opens || []).join(', ') || '—'],
    ['Missing', (rec.missing || []).join(', ') || 'nothing'],
    ['Set by hand', (fin.manual || (rec.edited && rec.edited.manual) || []).join(', ') || '—'],
    ['Size', rec.web_bytes ? (rec.web_bytes / 1048576).toFixed(1) + ' MB' : '—'],
    ['Model', rec.credit ? `${rec.credit.title} by ${rec.credit.author} (${rec.credit.licence})` : '—'],
  ];
  const dl = $('#report'); dl.textContent = '';
  for (const [k, v] of rows) {
    const dt = document.createElement('dt'); dt.textContent = k;
    const dd = document.createElement('dd'); dd.textContent = v;
    dl.append(dt, dd);
  }
}
function toggleClip(clip, btn) {
  let a = S.actions[clip.name];
  if (!a) { a = S.mixer.clipAction(clip); a.setLoop(THREE.LoopOnce); a.clampWhenFinished = true; S.actions[clip.name] = a; }
  const open = btn.getAttribute('aria-pressed') !== 'true';
  btn.setAttribute('aria-pressed', String(open));
  a.paused = false;
  a.timeScale = open ? 1 : -1;
  if (open) { if (!a.isRunning()) { a.reset(); a.play(); } }
  else { if (!a.isRunning()) { a.time = clip.duration; a.play(); } }
}

async function setMode(mode) {
  if (mode === 'result' && S.key) {
    try { await loadResult(); } catch (e) { toast('No built car yet: ' + e.message, true); mode = 'edit'; }
  }
  if (S.mode !== mode) S.views[S.mode] = [camera.position.clone(), controls.target.clone()];
  S.mode = mode;
  for (const b of document.querySelectorAll('#viewSeg button')) b.classList.toggle('on', b.dataset.v === mode);
  const v = S.views[mode];
  if (v) { camera.position.copy(v[0]); controls.target.copy(v[1]); }
  else if (mode === 'result' && S.result) frameCar(S.result);
  if (S.edit) S.edit.visible = mode === 'edit';
  if (S.result) { if (mode === 'result' && !S.result.parent) scene.add(S.result); S.result.visible = mode === 'result'; }
  $('#editPanel').hidden = mode !== 'edit';
  $('#resultPanel').hidden = mode !== 'result';
  if (mode === 'result') await drawResultPanel();
  drawOverlay(); drawGizmos(); hud();
}

// ── input ────────────────────────────────────────────────────────────────
for (const b of document.querySelectorAll('#viewSeg button')) b.onclick = () => S.key && setMode(b.dataset.v);
for (const b of document.querySelectorAll('#lookSeg button')) b.onclick = () => setLook(b.dataset.l);
for (const b of document.querySelectorAll('#toolSeg button')) b.onclick = () => setTool(b.dataset.t);
function setTool(t) {
  S.tool = t;
  for (const b of document.querySelectorAll('#toolSeg button')) b.classList.toggle('on', b.dataset.t === t);
  $('#creaseRow').style.visibility = t === 'panel' ? 'visible' : 'hidden';
  controls.mouseButtons = t === 'box'
    ? { LEFT: null, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.ROTATE }
    : { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN };
  hud();
}
$('#crease').oninput = e => { S.crease = +e.target.value; $('#creaseOut').textContent = S.crease + '°'; };
$('#sameMat').onchange = e => { S.sameMat = e.target.checked; };
$('#clearSel').onclick = clearSelection;
$('#undoBtn').onclick = undo;
$('#buildBtn').onclick = build;
$('#resetBtn').onclick = resetCar;

let down = null;
const rect = $('#boxRect');
canvas.addEventListener('pointerdown', e => {
  if (S.mode !== 'edit' || !S.recs.length) return;
  down = { x: e.clientX, y: e.clientY, button: e.button, op: mods(e) };
  if (S.tool === 'box' && e.button === 0) { canvas.setPointerCapture(e.pointerId); rect.hidden = false; drawRect(e); }
});
function drawRect(e) {
  const r = canvas.getBoundingClientRect();
  Object.assign(rect.style, { left: Math.min(down.x, e.clientX) - r.left + 'px', top: Math.min(down.y, e.clientY) - r.top + 'px',
    width: Math.abs(e.clientX - down.x) + 'px', height: Math.abs(e.clientY - down.y) + 'px' });
}
canvas.addEventListener('pointermove', e => { if (down && S.tool === 'box' && down.button === 0) drawRect(e); });
canvas.addEventListener('pointerup', e => {
  if (!down) return;
  const d = down; down = null;
  if (S.tool === 'box' && d.button === 0) {
    rect.hidden = true;
    if (Math.hypot(e.clientX - d.x, e.clientY - d.y) > 4) boxSelect(d.x, d.y, e.clientX, e.clientY, d.op);
    else if (d.op === 'replace') clearSelection();
    return;
  }
  if (d.button === 0 && Math.hypot(e.clientX - d.x, e.clientY - d.y) < 5) clickSelect(e.clientX, e.clientY, d.op);
});
addEventListener('keydown', e => {
  if (e.target.matches('input, select, textarea') || S.mode !== 'edit') return;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); undo(); return; }
  if (e.key === 'Escape') { clearSelection(); return; }
  if (!selTotal()) return;
  const k = e.key === 'Delete' || e.key === 'Backspace' ? 'Del' : e.key.toUpperCase();
  const t = TARGETS.find(x => x[3] === k);
  if (t) { e.preventDefault(); assign(t[0]); }
});
addEventListener('beforeunload', e => { if (S.dirty) { e.preventDefault(); e.returnValue = ''; } });

// ── start ────────────────────────────────────────────────────────────────
setTool('panel');
drawTargets(); drawSelInfo(); hud();
loadLibrary().then(() => {
  const want = new URLSearchParams(location.search).get('car');
  if (want) openCar(want);
}).catch(e => toast('Could not list the cars: ' + e.message, true));

// for tests and automation: the same actions a person takes
window.studio = { S, openCar, clickSelect, boxSelect, selectPart, assign, undo, build, setMode, setLook, setTool,
  exportEdits, camera, controls, canvas, codeOf, ids,
  setHinge: (part, edge, deg) => { S.hinges[hingeKey(part)] = { edge, deg }; setDirty(); drawGizmos(); drawParts(); } };
