// Open any catalogue GLB as plain geometry: Draco and meshopt decoded,
// quantized attributes made float. Licences: gltf-transform MIT,
// draco3dgltf Apache-2.0, meshoptimizer MIT.
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { dequantize } from '@gltf-transform/functions';
import { MeshoptDecoder } from 'meshoptimizer';
import draco3d from 'draco3dgltf';
const [,, src, dst] = process.argv;
await MeshoptDecoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({
  'draco3d.decoder': await draco3d.createDecoderModule(),
  'meshopt.decoder': MeshoptDecoder,
});
const doc = await io.read(src);
await doc.transform(dequantize());
for (const ext of doc.getRoot().listExtensionsUsed()) {
  if (['KHR_draco_mesh_compression', 'EXT_meshopt_compression', 'KHR_mesh_quantization'].includes(ext.extensionName)) ext.dispose();
}
await io.write(dst, doc);
console.log(JSON.stringify({ wrote: dst }));
