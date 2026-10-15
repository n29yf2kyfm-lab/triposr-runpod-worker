// One-time master preparation: meshopt + quantized -> plain float GLB.
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { dequantize } from '@gltf-transform/functions';
import { MeshoptDecoder } from 'meshoptimizer';
const [,, src, dst] = process.argv;
await MeshoptDecoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({ 'meshopt.decoder': MeshoptDecoder });
const doc = await io.read(src);
await doc.transform(dequantize());
for (const ext of doc.getRoot().listExtensionsUsed()) {
  if (['EXT_meshopt_compression', 'KHR_mesh_quantization'].includes(ext.extensionName)) ext.dispose();
}
await io.write(dst, doc);
console.log('wrote', dst);
