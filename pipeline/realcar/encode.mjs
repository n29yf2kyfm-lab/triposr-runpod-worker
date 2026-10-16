// Web copy: meshopt-compress a finished car (names and animations survive).
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS, EXTMeshoptCompression } from '@gltf-transform/extensions';
import { meshopt, prune, dedup } from '@gltf-transform/functions';
import { MeshoptEncoder, MeshoptDecoder } from 'meshoptimizer';
const [,, src, dst] = process.argv;
await MeshoptEncoder.ready; await MeshoptDecoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({ 'meshopt.encoder': MeshoptEncoder, 'meshopt.decoder': MeshoptDecoder });
const doc = await io.read(src);
await doc.transform(dedup(), prune({ keepLeaves: true }), meshopt({ encoder: MeshoptEncoder, level: 'medium' }));
await io.write(dst, doc);
console.log('wrote', dst);
