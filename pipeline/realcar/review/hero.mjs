// hero.mjs: the 1,000-vehicle run's picture of each built vehicle, the
// app's studio view (app_hero.mjs), from one browser kept open. Watches
// PENDING for <key>.glb, writes OUT/<key>.png and deletes the glb; stops
// when PENDING/STOP exists and nothing is left. Each picture's side (the
// way its photo's car points, F1K_HOME/photo_view.json) is logged to
// F1K_HOME/rendered.jsonl, so a picture taken from the wrong side is seen.
//   F1K_HOME=... node hero.mjs PENDING OUT [SHARD/OF]      e.g. 0/3, 1/3, 2/3: three side by side
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
const HERE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const F1K = process.env.F1K_HOME;
if (!F1K) { console.error('set F1K_HOME to the run\'s data folder'); process.exit(1); }
const puppeteer = createRequire(HERE + '/')('puppeteer-core');
const PEND = path.resolve(process.argv[2]), OUT = path.resolve(process.argv[3]);
const [SHARD, OF] = (process.argv[4] || '0/1').split('/').map(Number);
const mine = f => [...f].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7) % OF === SHARD;
fs.mkdirSync(OUT, { recursive: true });
const PAGE = `<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0;background:transparent;overflow:hidden}</style>
<script type="importmap">{"imports":{"three":"/three/build/three.module.js","three/addons/":"/three/examples/jsm/"}}</script>
</head><body><script type="module">
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
const q = new URLSearchParams(location.search);
// the studio's light, from tools/hero_settings.json at each picture (tuned so
// a paint shows as its own colour, as the real photo beside it shows it)
// and the side the photo's car points to (tools/photo_paint.py --view), the
// camera on that side so the two are seen alike
const S = Object.assign({ tone: 'neutral', exposure: 0.88, env: 0.75, key: 2.6 },
  await (await fetch('/settings?f=' + encodeURIComponent(q.get('f')))).json().catch(() => ({})));
const side = S.nose === 'right' ? -1 : 1;
const W = innerWidth, H = innerHeight;
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
renderer.setSize(W, H); renderer.setPixelRatio(1);
renderer.toneMapping = { neutral: THREE.NeutralToneMapping, aces: THREE.ACESFilmicToneMapping, agx: THREE.AgXToneMapping }[S.tone] || THREE.NeutralToneMapping;
renderer.toneMappingExposure = S.exposure;
renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.setClearColor(0x000000, 0);
document.body.appendChild(renderer.domElement);
const scene = new THREE.Scene();
const pm = new THREE.PMREMGenerator(renderer);
scene.environment = pm.fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = S.env;
const key = new THREE.DirectionalLight(0xffffff, S.key);
key.castShadow = true; key.shadow.mapSize.set(2048, 2048); key.shadow.radius = 8; key.shadow.bias = -0.0004;
scene.add(key, key.target);
const camera = new THREE.PerspectiveCamera(32, W / H, 0.05, 200);
const gltf = await new GLTFLoader().setMeshoptDecoder(MeshoptDecoder).loadAsync('/pack/' + q.get('f'));
const car = gltf.scene;
car.traverse(o => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = false; } });
// glass as a photo shows it from outside: above the beltline (the windows)
// dark, the sky in it, a little of the cabin through it; below it (the
// lamps' glass, often the same mesh) as it is. The file's own glass stays
// clear for the app: this is the picture only
const cb = new THREE.Box3().setFromObject(car), belt = cb.min.y + (cb.max.y - cb.min.y) * 0.6;
car.traverse(o => {
  if (!o.isMesh) return;
  for (const m of [].concat(o.material)) {
    const glassy = m.transmission > 0 || (m.transparent && m.opacity < 0.95) || /glass|window|windscreen|windshield/i.test(m.name || '');
    if (!glassy) continue;
    m.transmission = 0; m.transparent = true; m.depthWrite = false;
    m.onBeforeCompile = sh => {
      sh.uniforms.uBelt = { value: belt };
      sh.uniforms.uTint = { value: S.glassTint ?? 0.22 };
      sh.uniforms.uAlpha = { value: S.glassOpacity ?? 0.78 };
      sh.vertexShader = 'varying float vWorldY;\\n' + sh.vertexShader.replace('#include <project_vertex>',
        '#include <project_vertex>\\n  vWorldY = (modelMatrix * vec4(transformed, 1.0)).y;');
      sh.fragmentShader = 'varying float vWorldY;\\nuniform float uBelt, uTint, uAlpha;\\n' + sh.fragmentShader.replace('#include <opaque_fragment>',
        '#include <opaque_fragment>\\n  if (vWorldY > uBelt) { gl_FragColor.rgb *= uTint; gl_FragColor.a = max(gl_FragColor.a, uAlpha); }');
    };
    m.needsUpdate = true;
  }
});
scene.add(car);
const box = new THREE.Box3().setFromObject(car), size = box.getSize(new THREE.Vector3()), c = box.getCenter(new THREE.Vector3());
const ground = new THREE.Mesh(new THREE.PlaneGeometry(40, 40), new THREE.ShadowMaterial({ opacity: 0.32 }));
ground.rotation.x = -Math.PI / 2; ground.position.y = box.min.y + 0.001; ground.receiveShadow = true; scene.add(ground);
const sc = key.shadow.camera, ext = Math.max(size.x, size.z) * 0.9;
sc.left = -ext; sc.right = ext; sc.top = ext; sc.bottom = -ext; sc.near = 0.1; sc.far = 40; sc.updateProjectionMatrix();
key.position.set(c.x + 2.5 * side, c.y + 9, c.z + 3.5); key.target.position.copy(c);
// three-quarter from the front left (left is +X, the nose +Z; from the front
// right when the photo's car points right), from where a
// person stands to photograph a car: the camera about 1.4 m above the ground
// (the cars are to scale, in metres), as the real photo beside it was taken
const r = 0.5 * Math.hypot(size.x, size.y, size.z);
const dist = r / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2)) * 0.62;
const flat = new THREE.Vector3(0.78 * side, 0, 1).normalize();
const eye = box.min.y + Math.min(1.45, Math.max(1.1, size.y * 0.95));
camera.position.set(c.x + flat.x * dist, eye, c.z + flat.z * dist);
camera.lookAt(c.x, box.min.y + size.y * 0.42, c.z);
renderer.render(scene, camera);
window.__done = true;
</script></body></html>`;

const MIME = { '.js': 'text/javascript', '.glb': 'model/gltf-binary', '.wasm': 'application/wasm' };
const server = http.createServer((req, res) => {
  const url = decodeURIComponent(req.url.split('?')[0]);
  let file = null;
  if (url === '/' || url === '/index.html') { res.writeHead(200, { 'content-type': 'text/html' }); return res.end(PAGE); }
  if (url === '/settings') {
    const f = path.join(path.dirname(fileURLToPath(import.meta.url)), 'hero_settings.json');
    const S = fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, 'utf8')) : {};
    const v = path.join(F1K, 'photo_view.json'), k = path.basename(new URLSearchParams(req.url.split('?')[1] || '').get('f') || '', '.glb');
    try { S.nose = JSON.parse(fs.readFileSync(v, 'utf8'))[k] || null; } catch {}
    res.writeHead(200, { 'content-type': 'application/json' });
    return res.end(JSON.stringify(S));
  }
  if (url.startsWith('/three/')) file = path.join(HERE, 'node_modules', 'three', url.slice(7));
  if (url.startsWith('/pack/')) file = path.join(PEND, path.basename(url));
  if (!file || !fs.existsSync(file)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { 'content-type': MIME[path.extname(file)] || 'application/octet-stream' });
  fs.createReadStream(file).pipe(res);
});
await new Promise(r => server.listen(0, r));
const port = server.address().port;
let browser = null;
const launch = async () => puppeteer.launch({ executablePath: process.env.CHROME_PATH || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
  args: ['--no-sandbox', '--use-gl=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
browser = await launch();
for (;;) {
  const todo = fs.readdirSync(PEND).filter(f => f.endsWith('.glb') && !f.endsWith('.part.glb') && mine(f)).sort();
  if (!todo.length) {
    if (fs.existsSync(path.join(PEND, 'STOP'))) break;
    await new Promise(r => setTimeout(r, 3000));
    continue;
  }
  for (const f of todo) {
    const key = f.slice(0, -4), t = Date.now();
    let page = null;
    try {
      page = await browser.newPage();
      await page.setViewport({ width: 1600, height: 1000 });
      await page.goto(`http://localhost:${port}/?f=${encodeURIComponent(f)}`, { waitUntil: 'domcontentloaded' });
      await page.waitForFunction(() => window.__done, { timeout: 240000 });
      await page.screenshot({ path: path.join(OUT, key + '.png'), omitBackground: true });
      let nose = null;
      try { nose = JSON.parse(fs.readFileSync(path.join(F1K, 'photo_view.json'), 'utf8'))[key] || null; } catch {}
      fs.appendFileSync(path.join(F1K, 'rendered.jsonl'), JSON.stringify({ key, nose: nose || 'left', at: new Date().toISOString() }) + '\n');
      console.log(JSON.stringify({ key, nose, seconds: +((Date.now() - t) / 1000).toFixed(1) }));
    } catch (e) {
      console.log(JSON.stringify({ key, error: String(e.message || e).slice(0, 200) }));
      try { await browser.close(); } catch {}
      browser = await launch();
    }
    try { if (page) await page.close(); } catch {}
    fs.rmSync(path.join(PEND, f), { force: true });
  }
}
await browser.close();
server.close();
