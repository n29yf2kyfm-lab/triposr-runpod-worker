// qa_glb.mjs: a built car's shape checked from its file, for the 1,000-vehicle run.
//
//   node pipeline/realcar/review/qa_glb.mjs web.glb      -> one JSON line: {"issues": [...], ...}
//
// Issues: a wheel outside the body (its outer face more than 6 cm past the
// body's side, or past its nose or tail), a part lying away from the car
// (its box more than 25 cm outside the body's), and a body far from a car's
// proportions (wider than 2.3 m, or narrower than 1.3 m). The doors and lids
// are checked shut, as built.
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const require = createRequire(path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..') + '/');
const { NodeIO, getBounds } = require('@gltf-transform/core');
const { ALL_EXTENSIONS } = require('@gltf-transform/extensions');
const { MeshoptDecoder } = require('meshoptimizer');

await MeshoptDecoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({ 'meshopt.decoder': MeshoptDecoder });
const doc = await io.read(process.argv[2]);
const scene = doc.getRoot().listScenes()[0];
const named = {};
scene.traverse(n => { named[n.getName()] = n; });
const box = n => { const b = getBounds(n); return isFinite(b.min[0]) ? b : null; };
const issues = [];
const body = named.body && box(named.body);
if (!body) {
  console.log(JSON.stringify({ issues: ['no body found'] }));
  process.exit(0);
}
const [bx0, , bz0] = body.min, [bx1, by1, bz1] = body.max;
const width = bx1 - bx0, length = bz1 - bz0;
for (const w of ['wheel_fl', 'wheel_fr', 'wheel_rl', 'wheel_rr']) {
  const b = named[w] && box(named[w]);
  if (!b) { issues.push(`${w} missing`); continue; }
  const out = Math.max(b.max[0] - bx1, bx0 - b.min[0], b.max[2] - bz1, bz0 - b.min[2]);
  if (out > 0.06) issues.push(`${w} ${Math.round(out * 100)} cm outside the body`);
}
// parts away from the car: any mesh node whose box lies mostly outside the body's
for (const n of doc.getRoot().listNodes()) {
  if (!n.getMesh()) continue;
  let p = n, inScene = false;
  while (p) { if (p === named.body || scene.listChildren().includes(p)) { inScene = true; break; } p = p.getParentNode(); }
  const b = box(n);
  if (!b) continue;
  const gap = Math.max(bx0 - b.max[0], b.min[0] - bx1, bz0 - b.max[2], b.min[2] - bz1, b.min[1] - by1);
  if (gap > 0.25) issues.push(`${n.getName() || 'a part'} lies ${Math.round(gap * 100)} cm away from the body`);
}
if (width > 2.3) issues.push(`body ${width.toFixed(2)} m wide`);
if (width < 1.3) issues.push(`body only ${width.toFixed(2)} m wide`);
console.log(JSON.stringify({ issues: [...new Set(issues)].slice(0, 12), width: +width.toFixed(3), length: +length.toFixed(3) }));
