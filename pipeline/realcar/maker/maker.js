// GLB Maker — the GLB machine's front door. Type a car (make, model, year,
// colour, doors, spec), press Build: the machine finds it in the catalogue
// and builds the GLB (POST /v1/cars), this page waits for it and shows it
// with its doors, bonnet and tailgate open. Spin it, flip it over to see the
// engine, exhaust and floor, save a picture, download the GLB.
// ExpertCarCheck. Proprietary: see ../LICENSE.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';

const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const norm = s => String(s || '').toLowerCase().replace(/[^a-z0-9]/g, '');
const BUDGET = 120;            // seconds: the machine's promise

// DVLA colour names, painted as make.py paints them
const COLOURS = [
  ['white', [236, 236, 233]], ['black', [16, 16, 18]], ['silver', [186, 189, 192]], ['grey', [108, 111, 115]],
  ['blue', [24, 52, 118]], ['red', [152, 16, 22]], ['green', [28, 78, 44]], ['yellow', [232, 190, 28]],
  ['orange', [222, 98, 20]], ['brown', [84, 54, 34]], ['beige', [201, 186, 150]], ['cream', [236, 226, 196]],
  ['gold', [182, 150, 80]], ['bronze', [140, 100, 60]], ['maroon', [88, 14, 24]], ['purple', [78, 30, 92]],
  ['pink', [220, 120, 160]], ['turquoise', [28, 140, 140]],
];
const PART_NAMES = { door_fl: 'Front left door', door_fr: 'Front right door', door_rl: 'Rear left door',
  door_rr: 'Rear right door', bonnet: 'Bonnet', tailgate: 'Tailgate' };
const STEPS = [['download', '#4aa8e8'], ['decode', '#6cc070'], ['rig', '#ffe45c'], ['finish', '#ff8c42'],
  ['validate', '#b07be0'], ['encode', '#2fb8a6'], ['render', '#8b939c']];

const S = { colour: '', doors: '', cat: [], job: null, t0: 0, tick: 0, poll: 0, car: null, blob: null,
  name: '', mixer: null, clips: {}, actions: {}, open: { doors: false, bonnet: false, tailgate: false },
  flipped: false, flip: null, home: null };

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

// ── form ─────────────────────────────────────────────────────────────────
const sw = $('#swatches');
for (const [name, rgb] of [['', null], ...COLOURS]) {
  const b = document.createElement('button');
  b.type = 'button'; b.setAttribute('role', 'radio'); b.dataset.c = name;
  b.title = name ? name[0].toUpperCase() + name.slice(1) : 'As modelled';
  b.setAttribute('aria-label', b.title);
  b.setAttribute('aria-checked', String(name === ''));
  if (rgb) b.style.background = `rgb(${rgb.join(',')})`; else b.className = 'none';
  sw.append(b);
}
sw.setAttribute('role', 'radiogroup');
sw.addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  S.colour = b.dataset.c;
  sw.querySelectorAll('button').forEach(x => x.setAttribute('aria-checked', String(x === b)));
  $('#colourName').textContent = S.colour || 'as modelled';
  ask();
});
$('#doors').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  S.doors = b.dataset.v;
  $('#doors').querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
  ask();
});

// a two-digit UK plate is a year: 02-29 that March, 51-79 that September
function year() {
  const v = $('#year').value.trim();
  if (/^(19[5-9]\d|20[0-3]\d)$/.test(v)) return { year: +v };
  if (/^\d\d$/.test(v)) {
    const n = +v, yy = new Date().getFullYear() % 100;
    if (n >= 2 && n <= yy) return { year: 2000 + n, plate: v };
    if (n >= 51 && n <= yy + 50) return { year: 1950 + n, plate: v };
  }
  return v ? { bad: true } : {};
}
function request() {
  const y = year();
  return [$('#make').value.trim(), $('#model').value.trim(), y.year || '', S.colour,
    S.doors ? `${S.doors} door` : ''].filter(Boolean).join(' ');
}
function ask() {
  const r = request(), spec = $('#spec').value.trim();
  $('#ask').textContent = r ? r + (spec ? `  · spec ${spec}` : '') : 'nothing yet';
  const y = year();
  $('#year').classList.toggle('bad', !!y.bad);
  hint(y);
}
function makeOf(v) { const n = norm(v); return S.cat.find(m => norm(m.make) === n); }
function hint(y) {
  const h = $('#modelHint'), mk = makeOf($('#make').value), mv = norm($('#model').value);
  const plate = y && y.plate ? ` · ${y.plate} plate = ${y.year}` : '';
  if (y && y.bad) { h.innerHTML = 'The year is four digits (2012) or a plate (12, 62).'; return; }
  if (!$('#make').value.trim()) { h.textContent = 'Start typing: the lists show what the catalogue has.' + plate; return; }
  if (!mk) { h.textContent = 'Not a make the catalogue knows: it will still be searched.' + plate; return; }
  const m = mk.models.find(x => norm(x.model) === mv);
  if (m) {
    h.innerHTML = `In the catalogue: <b>${esc(mk.make)} ${esc(m.model)}</b>` +
      (m.years ? ` ${m.years[0]}${m.years[1] !== m.years[0] ? '–' + m.years[1] : ''}` : '') + esc(plate);
  } else {
    h.textContent = `${mk.models.length} ${mk.make} models in the catalogue` + plate;
  }
}
$('#make').addEventListener('input', () => {
  const mk = makeOf($('#make').value), dl = $('#models');
  dl.textContent = '';
  for (const m of (mk ? mk.models : [])) {
    const o = document.createElement('option'); o.value = m.model;
    if (m.years) o.label = m.years[0] === m.years[1] ? String(m.years[0]) : `${m.years[0]}–${m.years[1]}`;
    dl.append(o);
  }
  ask();
});
for (const id of ['#model', '#year', '#spec']) $(id).addEventListener('input', ask);

async function loadCatalogue() {
  try {
    S.cat = await (await api('/v1/catalogue')).json();
    const dl = $('#makes');
    for (const m of S.cat) { const o = document.createElement('option'); o.value = m.make; dl.append(o); }
  } catch (e) { toast('The catalogue list did not load: ' + e.message, true); }
}

// ── build ────────────────────────────────────────────────────────────────
$('#form').addEventListener('submit', async e => {
  e.preventDefault();
  if (!$('#model').value.trim()) { $('#model').classList.add('bad'); $('#model').focus(); toast('Type the model', true); return; }
  if (year().bad) { $('#year').focus(); return; }
  $('#model').classList.remove('bad');
  const body = { request: request(), spec: $('#spec').value.trim(), sheet: $('#sheet').checked };
  $('#buildBtn').disabled = true;
  try {
    const j = await (await api('/v1/cars', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body) })).json();
    S.t0 = performance.now();
    follow(j.id, true);
  } catch (err) {
    toast('Not started: ' + err.message, true);
    $('#buildBtn').disabled = false;
  }
});

function status(state, text) {
  $('#status').hidden = false;
  const p = $('#statePill'); p.className = 'pill ' + state;
  p.textContent = { queued: 'Queued', building: 'Building', done: 'Ready', check: 'Ready: check', failed: 'Not built' }[state] || state;
  $('#stateText').textContent = text;
}
const mmss = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
function clock(sec, final) {
  $('#clock').textContent = mmss(sec);
  const m = $('#meter');
  m.style.width = Math.min(100, sec / BUDGET * 100) + '%';
  m.className = final || '';
}

async function follow(id, fresh) {
  clearInterval(S.tick); clearTimeout(S.poll);
  S.job = { id };
  setUrl(id);
  $('#reportCard').hidden = true;
  if (fresh) {
    status('queued', 'Waiting for a free builder');
    clock(0);
    S.tick = setInterval(() => clock((performance.now() - S.t0) / 1000), 500);
  }
  let job;
  for (;;) {
    try { job = await (await api('/v1/cars/' + id)).json(); } catch (e) {
      clearInterval(S.tick); $('#buildBtn').disabled = false;
      return toast('That car is not here: ' + e.message, true);
    }
    if (S.job.id !== id) return;                     // another car was asked for meanwhile
    if (job.status === 'queued') status('queued', 'Waiting for a free builder');
    else if (job.status === 'building') status('building', 'Catalogue model → doors, bonnet, tailgate → engine, exhaust, paint → GLB');
    else break;
    if (!fresh) { clock((Date.now() / 1000 - job.asked_at)); }
    await new Promise(r => { S.poll = setTimeout(r, 1000); });
  }
  clearInterval(S.tick);
  $('#buildBtn').disabled = false;
  const secs = (job.finished_at || 0) - (job.asked_at || 0);
  const q = job.status === 'done' ? (job.quality === 'check' ? 'check' : 'done') : 'failed';
  clock(secs > 0 ? secs : (performance.now() - S.t0) / 1000, q === 'failed' ? 'failed' : 'done');
  status(q, q === 'failed' ? 'See below' : `Built in ${Math.round(secs)} s` + (secs <= BUDGET ? ', inside the 2 minutes' : ''));
  report(job);
  recent();
  if (job.status === 'done') await showCar(job);
}

// ── report ───────────────────────────────────────────────────────────────
function report(job) {
  const rep = job.report || {}, res = rep.result || {}, fin = res.finish || {}, cr = res.credit || {};
  const rows = [];
  const row = (k, v, cls = '') => rows.push(`<dt>${esc(k)}</dt><dd class="${cls}">${v}</dd>`);
  $('#reportCard').hidden = false;
  if (job.status !== 'done') {
    $('#repTitle').textContent = 'Not built';
    row('Asked', esc(job.request) + (job.spec ? ' · ' + esc(job.spec) : ''));
    row('Why', esc(rep.error || job.error || 'the build stopped'), 'warn');
    if (rep.error && rep.match) row('Search', esc(rep.match));
    if (rep.catalogue_has && rep.catalogue_has.length) {
      row('The catalogue has', '<div class="chips">' + rep.catalogue_has.map(m =>
        `<button type="button" data-model="${esc(m)}">${esc(m)}</button>`).join('') + '</div>');
    }
    if (rep.nearest && rep.nearest.length) row('Nearest', esc(rep.nearest.join(', ')), 'mono');
    if ((rep.passed_over || []).length) row('Passed over', rep.passed_over.map(x => `${esc(x.source || x.asset)} <span class="faint">(${esc(x.why)})</span>`).join('<br>'));
    $('#report').innerHTML = rows.join('');
    $('#links').textContent = '';
    return;
  }
  $('#repTitle').textContent = 'Built';
  row('Car', `${esc(rep.source || rep.asset)}<br><span class="faint mono">${esc(rep.asset)}</span>`);
  row('Match', esc(rep.match || ''), /nearest/.test(rep.match || '') ? 'warn' : '');
  if (rep.spec_note) row('Spec', esc(rep.spec_note));
  if ((rep.passed_over || []).length) row('Passed over', rep.passed_over.map(x =>
    `${esc(x.source || x.asset)} <span class="faint">(${esc(x.why === 'no wheels named' ? 'its wheels and doors are not separate parts' : x.why)})</span>`).join('<br>'));
  if (rep.doors_note) row('Doors', esc(rep.doors_note), /\(/.test(rep.doors_note) ? 'warn' : '');
  const opens = fin.opens || [];
  row('Opens', '<div class="chips">' + (opens.map(p => `<span>${esc(PART_NAMES[p] || p)}</span>`).join('') || 'nothing') + '</div>');
  if ((res.missing || []).length) row('Missing', esc(res.missing.join(', ')) + ' (fix it in Studio)', 'warn');
  const asked = (rep.asked || {}).colour;
  row('Paint', asked ? esc(asked[0].toUpperCase() + asked.slice(1)) : 'as modelled');
  if (fin.engine_pack) row('Engine bay', 'engine, gearbox, cooling, battery and exhaust fitted');
  const lic = esc(cr.licence || 'not given');
  row('Model credit', `${esc(cr.title || '')}${cr.author ? ' by ' + esc(cr.author) : ''}<br><span class="faint">${lic}` +
    ` · commercial use ${cr.commercial ? 'allowed with the credit' : '<b class="warn">not allowed</b>'}</span>` +
    (cr.url ? `<br><a href="${esc(cr.url)}" target="_blank" rel="noopener">source page</a>` : ''));
  const t = res.timings_s || {}, total = STEPS.reduce((a, [k]) => a + (t[k] || 0), 0) || 1;
  row('Time', `${Math.round((job.finished_at - job.asked_at) || res.seconds || 0)} s in all` +
    `<div class="times">${STEPS.filter(([k]) => t[k]).map(([k, c]) => `<i style="flex:${t[k] / total};background:${c}" title="${k} ${t[k]} s"></i>`).join('')}</div>` +
    `<div class="times-key">${STEPS.filter(([k]) => t[k]).map(([k, c]) => `<span><b style="background:${c}"></b>${k} ${t[k]}s</span>`).join('')}</div>`);
  if (res.web_bytes) row('File', `${(res.web_bytes / 1048576).toFixed(1)} MB GLB (meshopt)`, 'mono');
  $('#report').innerHTML = rows.join('');
  const key = `${job.id}/${rep.asset}`;
  $('#studioTab').href = '/studio/?car=' + encodeURIComponent(key);
  $('#links').innerHTML = `<a class="ghost" href="/studio/?car=${encodeURIComponent(key)}">Fix a part in Studio</a>` +
    ((job.files || {}).sheet ? '<button class="ghost" type="button" id="sheetBtn">Four-view picture</button>' : '');
  const sb = $('#sheetBtn');
  if (sb) sb.onclick = async () => {
    const w = window.open('', '_blank');
    const b = await (await api(job.files.sheet)).blob();
    if (w) w.location = URL.createObjectURL(b);
  };
}
$('#report').addEventListener('click', e => {
  const b = e.target.closest('button[data-model]'); if (!b) return;
  $('#model').value = b.dataset.model; ask(); $('#model').focus();
});

// ── recent cars ──────────────────────────────────────────────────────────
async function recent() {
  let list = [];
  try { list = await (await api('/v1/cars')).json(); } catch { return; }
  const ul = $('#recent');
  if (!list.length) { ul.innerHTML = '<li class="faint">No cars yet.</li>'; return; }
  ul.innerHTML = list.map(j => {
    const st = j.status === 'done' ? (j.quality === 'check' ? 'check' : 'done') : j.status;
    const ago = j.asked_at ? since(j.asked_at) : '';
    return `<li><button type="button" data-id="${esc(j.id)}" class="${S.job && S.job.id === j.id ? 'on' : ''}">` +
      `<span class="n">${esc(j.request)}${j.spec ? ' · ' + esc(j.spec) : ''}</span><span class="pill ${st}">${esc(st)}</span>` +
      `<span class="a">${esc(j.asset || '—')} · ${esc(ago)}</span></button></li>`;
  }).join('');
}
function since(t) {
  const s = Date.now() / 1000 - t;
  if (s < 90) return 'just now';
  if (s < 5400) return Math.round(s / 60) + ' min ago';
  if (s < 129600) return Math.round(s / 3600) + ' h ago';
  return new Date(t * 1000).toLocaleDateString();
}
$('#recent').addEventListener('click', e => {
  const b = e.target.closest('button[data-id]'); if (!b) return;
  S.t0 = performance.now();
  $('#status').hidden = true;
  follow(b.dataset.id, false);
  $('#recent').querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
});
function setUrl(id) {
  const u = new URL(location.href); u.searchParams.set('car', id);
  history.replaceState(null, '', u);
}

// ── viewer ───────────────────────────────────────────────────────────────
const canvas = $('#c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.0;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.shadowMap.autoUpdate = false;                   // only when the car moves: see the loop
const scene = new THREE.Scene();
scene.background = (() => {           // a studio wall: lighter at the top
  const c = document.createElement('canvas'); c.width = 2; c.height = 256;
  const g = c.getContext('2d'), gr = g.createLinearGradient(0, 0, 0, 256);
  gr.addColorStop(0, '#30353c'); gr.addColorStop(0.62, '#1c1f23'); gr.addColorStop(1, '#141619');
  g.fillStyle = gr; g.fillRect(0, 0, 2, 256);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
})();
scene.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = 0.9;
scene.add(new THREE.HemisphereLight(0xdfe8f2, 0x202326, 0.5));
const sun = new THREE.DirectionalLight(0xffffff, 1.6);
sun.position.set(3, 7, 4); sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, { left: -4, right: 4, top: 4, bottom: -4, near: 0.5, far: 20 });
sun.shadow.bias = -0.0004;
scene.add(sun);
const floor = new THREE.Group();
{
  const c = document.createElement('canvas'); c.width = c.height = 256;
  const g = c.getContext('2d'), gr = g.createRadialGradient(128, 128, 0, 128, 128, 128);
  gr.addColorStop(0, 'rgba(70,76,84,0.55)'); gr.addColorStop(0.7, 'rgba(50,55,61,0.25)'); gr.addColorStop(1, 'rgba(40,44,49,0)');
  g.fillStyle = gr; g.fillRect(0, 0, 256, 256);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  const disc = new THREE.Mesh(new THREE.CircleGeometry(7, 64), new THREE.MeshBasicMaterial({ map: t, transparent: true, depthWrite: false }));
  disc.rotation.x = -Math.PI / 2;
  const shadow = new THREE.Mesh(new THREE.CircleGeometry(7, 64), new THREE.ShadowMaterial({ opacity: 0.42 }));
  shadow.rotation.x = -Math.PI / 2; shadow.position.y = 0.002; shadow.receiveShadow = true;
  floor.add(disc, shadow);
}
scene.add(floor);
const pivot = new THREE.Group(); scene.add(pivot);       // the car turns over about its own middle
const camera = new THREE.PerspectiveCamera(32, 1, 0.05, 200);
camera.position.set(5, 2.2, 6);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.maxPolarAngle = Math.PI;                          // all the way round, underneath too
controls.autoRotateSpeed = 1.6;
const clock3 = new THREE.Clock();

// drawn only when something changes (the camera, a part opening, the
// flip): a still car costs nothing, which phones and laptops notice
let frames = 2;
const wake = (shadow = false) => { frames = 2; if (shadow) renderer.shadowMap.needsUpdate = true; };
controls.addEventListener('change', () => wake());
function resize() {
  const r = canvas.parentElement.getBoundingClientRect();
  renderer.setSize(r.width, r.height, false);
  camera.aspect = r.width / Math.max(r.height, 1); camera.updateProjectionMatrix();
  wake();
}
new ResizeObserver(resize).observe(canvas.parentElement);
resize();
renderer.setAnimationLoop(() => {
  const dt = Math.min(clock3.getDelta(), 0.1);
  if (S.mixer && Object.values(S.actions).some(a => a.isRunning())) { S.mixer.update(dt); wake(true); }
  if (S.flip) {
    const f = S.flip, k = Math.min(1, (performance.now() - f.t0) / f.ms), e = k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2;
    pivot.rotation.z = f.from + (f.to - f.from) * e;
    if (k >= 1) { S.flip = null; floor.visible = !S.flipped; }
    wake(true);
  }
  controls.update();                                       // damping and Spin fire 'change'
  if (frames > 0) { frames--; renderer.render(scene, camera); }
});

const loader = new GLTFLoader().setMeshoptDecoder(MeshoptDecoder);
async function showCar(job) {
  busy('Loading the car');
  try {
    const buf = await (await api(`/v1/cars/${job.id}/car.glb`)).arrayBuffer();
    if (S.job.id !== job.id) return;
    S.blob = new Blob([buf], { type: 'model/gltf-binary' });
    const gltf = await new Promise((res, rej) => loader.parse(buf, '', res, rej));
    if (S.car) { pivot.remove(S.car); dispose(S.car); }
    S.car = gltf.scene;
    S.car.traverse(o => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = false; } });
    // stand it on the floor, centred; the pivot sits at the car's middle
    pivot.rotation.set(0, 0, 0); S.flipped = false; S.flip = null; floor.visible = true;
    const b = new THREE.Box3().setFromObject(S.car), size = b.getSize(new THREE.Vector3()), c = b.getCenter(new THREE.Vector3());
    pivot.position.set(0, size.y / 2, 0);
    S.car.position.set(-c.x, -b.min.y - size.y / 2, -c.z);
    pivot.add(S.car);
    const r = size.length() / 2;
    S.home = { r, h: size.y };
    controls.minDistance = r * 0.5; controls.maxDistance = r * 7;
    camera.near = r / 100; camera.far = r * 40; camera.updateProjectionMatrix();
    home();
    wake(true);
    // the clips: each door, the bonnet, the tailgate
    S.mixer = new THREE.AnimationMixer(S.car); S.actions = {};
    S.clips = { doors: gltf.animations.filter(a => /^door_..?_open$/.test(a.name)),
      bonnet: gltf.animations.filter(a => a.name === 'bonnet_open'),
      tailgate: gltf.animations.filter(a => a.name === 'tailgate_open') };
    S.open = { doors: false, bonnet: false, tailgate: false };
    const rep = job.report || {};
    S.name = slug(job.request + (job.spec ? ' ' + job.spec : '')) || rep.asset || 'car';
    $('#carName').innerHTML = esc(rep.source || rep.asset) + (job.quality === 'check' ? ' <span class="pill check">check</span>' : '');
    $('#carName').hidden = false; $('#empty').hidden = true; $('#toolbar').hidden = false;
    for (const btn of $('#opens').querySelectorAll('button')) {
      const p = btn.dataset.part;
      btn.disabled = p !== 'all' && !S.clips[p].length;
    }
    $('#spinBtn').setAttribute('aria-pressed', 'false'); controls.autoRotate = false;
    $('#flipBtn').setAttribute('aria-pressed', 'false');
    syncOpens();
    setTimeout(() => setOpen('all', true), 450);           // the doors, bonnet and tailgate open on arrival
  } catch (e) {
    toast('The car did not load: ' + e.message, true);
  } finally { busy(''); }
}
function dispose(o) {
  o.traverse(x => {
    if (x.geometry) x.geometry.dispose();
    for (const m of [].concat(x.material || [])) { for (const k in m) if (m[k] && m[k].isTexture) m[k].dispose(); m.dispose(); }
  });
}
const slug = s => String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 80);
function home() {
  // far enough back that the car fits the narrower way of the screen too (a phone held upright)
  if (!S.home) return;
  const { r, h } = S.home, v = THREE.MathUtils.degToRad(camera.fov / 2);
  const half = Math.min(v, Math.atan(Math.tan(v) * camera.aspect));
  const d = r / Math.sin(half) * 0.92;
  camera.position.set(d * 0.62, h * 0.55 + d * 0.22, d * 0.78);
  controls.target.set(0, h * 0.42, 0);
  controls.update(); wake();
}

function play(clip, open) {
  let a = S.actions[clip.name];
  if (!a) { a = S.mixer.clipAction(clip); a.setLoop(THREE.LoopOnce, 1); a.clampWhenFinished = true; S.actions[clip.name] = a; }
  if (a.isRunning()) { a.timeScale = open ? 1 : -1; return; }
  const at = a.enabled && a.time > 0 ? a.time : 0;        // where a finished clip was left
  a.reset();
  a.time = open ? Math.min(at, clip.duration) : (at || clip.duration);
  a.timeScale = open ? 1 : -1;
  a.play();
  wake(true);
}
function setOpen(part, open) {
  if (!S.mixer) return;
  for (const p of part === 'all' ? ['doors', 'bonnet', 'tailgate'] : [part]) {
    if (!S.clips[p].length || S.open[p] === open) continue;
    S.open[p] = open;
    S.clips[p].forEach(c => play(c, open));
  }
  syncOpens();
}
function syncOpens() {
  const have = ['doors', 'bonnet', 'tailgate'].filter(p => S.clips[p] && S.clips[p].length);
  for (const btn of $('#opens').querySelectorAll('button')) {
    const p = btn.dataset.part;
    btn.setAttribute('aria-pressed', String(p === 'all' ? have.length > 0 && have.every(x => S.open[x]) : !!S.open[p]));
  }
}
$('#opens').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b || b.disabled) return;
  const p = b.dataset.part;
  setOpen(p, b.getAttribute('aria-pressed') !== 'true');
});
$('#spinBtn').onclick = () => {
  controls.autoRotate = !controls.autoRotate;
  $('#spinBtn').setAttribute('aria-pressed', String(controls.autoRotate));
};
function flip(to) {
  S.flipped = to;
  S.flip = { from: pivot.rotation.z, to: to ? Math.PI : 0, t0: performance.now(), ms: matchMedia('(prefers-reduced-motion: reduce)').matches ? 1 : 1100 };
  if (to) floor.visible = false;
  $('#flipBtn').setAttribute('aria-pressed', String(to));
}
$('#flipBtn').onclick = () => S.car && flip(!S.flipped);
$('#resetBtn').onclick = () => {
  controls.autoRotate = false; $('#spinBtn').setAttribute('aria-pressed', 'false');
  if (S.flipped) flip(false);
  home();
};
$('#picBtn').onclick = () => {
  renderer.render(scene, camera);
  canvas.toBlob(b => save(b, S.name + '.png'), 'image/png');
};
$('#dlBtn').onclick = () => S.blob && save(S.blob, S.name + '.glb');
function save(blob, name) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = name;
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  toast('Saved ' + name);
}

// ── small things ─────────────────────────────────────────────────────────
function busy(text) { $('#busy').hidden = !text; if (text) $('#busyText').textContent = text; }
let toastT = 0;
function toast(text, bad = false) {
  const t = $('#toast'); t.textContent = text; t.classList.toggle('bad', bad); t.hidden = false;
  clearTimeout(toastT); toastT = setTimeout(() => { t.hidden = true; }, bad ? 7000 : 3000);
}
async function health() {
  try {
    const h = await (await fetch('/health')).json();
    $('#health').textContent = 'machine ' + h.version; $('#health').className = 'health ok';
  } catch { $('#health').textContent = 'machine not answering'; $('#health').className = 'health bad'; }
}

health();
ask();
loadCatalogue().then(() => recent()).then(() => {
  const id = new URLSearchParams(location.search).get('car');
  if (id && /^[0-9a-f]{12}$/.test(id)) { S.t0 = performance.now(); follow(id, false); }
});
window.maker = { S, setOpen, flip, controls, camera, wake };     // for tests and the console
