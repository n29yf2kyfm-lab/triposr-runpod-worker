// app_hero.mjs: a studio picture of each vehicle in an app pack, for the
// garage screen, so the app can show every vehicle before it loads any 3D.
// Transparent background, the vehicle three-quarter from the front left,
// a soft shadow under it. Headless Chromium (swiftshader), our three.js.
//
//   node pipeline/realcar/app_hero.mjs PACK_DIR [id ...]   -> PACK_DIR/<id>.png
//
// ExpertCarCheck. Proprietary: see LICENSE.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import puppeteer from 'puppeteer-core';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PACK = path.resolve(process.argv[2] || '.');
const index = JSON.parse(fs.readFileSync(path.join(PACK, 'index.json'), 'utf8'));
const want = process.argv.slice(3);
const vehicles = index.vehicles.filter(v => !want.length || want.includes(v.id));

const PAGE = `<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0;background:transparent;overflow:hidden}</style>
<script type="importmap">{"imports":{"three":"/three/build/three.module.js","three/addons/":"/three/examples/jsm/"}}</script>
</head><body><script type="module">
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
const q = new URLSearchParams(location.search);
const W = innerWidth, H = innerHeight;
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
renderer.setSize(W, H); renderer.setPixelRatio(1);
renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 0.88;
renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.setClearColor(0x000000, 0);
document.body.appendChild(renderer.domElement);
const scene = new THREE.Scene();
const pm = new THREE.PMREMGenerator(renderer);
scene.environment = pm.fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = 0.75;
const key = new THREE.DirectionalLight(0xffffff, 2.6);
key.castShadow = true; key.shadow.mapSize.set(2048, 2048); key.shadow.radius = 8; key.shadow.bias = -0.0004;
scene.add(key, key.target);
const camera = new THREE.PerspectiveCamera(28, W / H, 0.05, 200);
const gltf = await new GLTFLoader().setMeshoptDecoder(MeshoptDecoder).loadAsync('/pack/' + q.get('f'));
const car = gltf.scene;
car.traverse(o => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = false; } });
scene.add(car);
const box = new THREE.Box3().setFromObject(car), size = box.getSize(new THREE.Vector3()), c = box.getCenter(new THREE.Vector3());
const ground = new THREE.Mesh(new THREE.PlaneGeometry(40, 40), new THREE.ShadowMaterial({ opacity: 0.32 }));
ground.rotation.x = -Math.PI / 2; ground.position.y = box.min.y + 0.001; ground.receiveShadow = true; scene.add(ground);
const sc = key.shadow.camera, ext = Math.max(size.x, size.z) * 0.9;
sc.left = -ext; sc.right = ext; sc.top = ext; sc.bottom = -ext; sc.near = 0.1; sc.far = 40; sc.updateProjectionMatrix();
key.position.set(c.x + 2.5, c.y + 9, c.z + 3.5); key.target.position.copy(c);
// three-quarter from the front left (left is +X, the nose +Z), a little above
const dir = new THREE.Vector3(0.78, 0.30, 1).normalize();
const r = 0.5 * Math.hypot(size.x, size.y, size.z);
const dist = r / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2)) * 0.64;
camera.position.copy(c).addScaledVector(dir, dist); camera.lookAt(c.x, c.y - size.y * 0.06, c.z);
renderer.render(scene, camera);
window.__done = true;
</script></body></html>`;

const MIME = { '.js': 'text/javascript', '.glb': 'model/gltf-binary', '.wasm': 'application/wasm' };
const server = http.createServer((req, res) => {
  const url = decodeURIComponent(req.url.split('?')[0]);
  let file = null;
  if (url === '/' || url === '/index.html') { res.writeHead(200, { 'content-type': 'text/html' }); return res.end(PAGE); }
  if (url.startsWith('/three/')) file = path.join(HERE, 'node_modules', 'three', url.slice(7));
  if (url.startsWith('/pack/')) file = path.join(PACK, path.basename(url));
  if (!file || !fs.existsSync(file)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { 'content-type': MIME[path.extname(file)] || 'application/octet-stream' });
  fs.createReadStream(file).pipe(res);
});
await new Promise(r => server.listen(0, r));
const port = server.address().port;
const browser = await puppeteer.launch({ executablePath: process.env.CHROME_PATH || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
  args: ['--no-sandbox', '--use-gl=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
for (const v of vehicles) {
  const t = Date.now();
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000 });
  page.on('pageerror', e => console.log(v.id, 'pageerror:', e.message));
  await page.goto(`http://localhost:${port}/?f=${encodeURIComponent(v.glb)}`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => window.__done, { timeout: 300000 });
  const out = path.join(PACK, `${v.id}.png`);
  await page.screenshot({ path: out, omitBackground: true });
  await page.close();
  console.log(JSON.stringify({ id: v.id, wrote: out, seconds: +((Date.now() - t) / 1000).toFixed(1) }));
}
await browser.close();
server.close();
