// node slim.mjs IN.glb OUT.glb [RATIO]
// An image-to-3D car (a million vertices) slimmed for a phone: welded and simplified with meshoptimizer
// (UVs kept: the texture still lines up). Its 4K textures are cut down by ai_parts.py --texture.
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { weld, simplify, prune, dedup } from '@gltf-transform/functions';
import { MeshoptSimplifier } from 'meshoptimizer';
const [,, src, dst, ratio = '0.15'] = process.argv;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS);
const doc = await io.read(src);
await MeshoptSimplifier.ready;
const count = () => doc.getRoot().listMeshes().reduce((n, m) => n + m.listPrimitives().reduce((k, p) => k + (p.getIndices() ? p.getIndices().getCount() / 3 : p.getAttribute('POSITION').getCount() / 3), 0), 0);
const before = count();
await doc.transform(
  weld(),
  simplify({ simplifier: MeshoptSimplifier, ratio: +ratio, error: 0.0008, lockBorder: false }),
  dedup(), prune(),
);
await io.write(dst, doc);
console.log(JSON.stringify({ triangles_before: Math.round(before), triangles_after: Math.round(count()) }));
