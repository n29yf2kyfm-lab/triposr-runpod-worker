# App integration — TRELLIS.2 worker output

How the Expert Car Check app should consume this worker's output for the
best-looking result. Everything here runs in the app's viewer; nothing
changes on the worker.

## Endpoint I/O quick reference

Request (`POST /run` on the endpoint):

```json
{
  "input": {
    "vehicle": {"make": "Audi", "model": "Q7", "year": 2024, "color": "district green metallic"},
    "pipeline_type": "1536_cascade",
    "oem_paint":   {"name": "District Green Metallic"},
    "wheel_swap":  true,
    "panel_detail": true
  }
}
```

- `wheel_swap` / `panel_detail` default ON for generated (text/vehicle) cars —
  send `false` to opt out. `wheel_swap` accepts `{"style": "audi"}` to force a
  rim style; by default the style follows `vehicle.make`.
- Output: `glb_url` (Supabase, permanent), `image_url` (the generated
  reference image), `glass` (bool — model ships with real alpha windows),
  `wheels` / `panel_detail` / `oem_paint` (per-stage reports or null).

## Glass: swap to a physical shader in the viewer (biggest win)

The GLB's windows use alpha transparency (`alphaMode: BLEND`), which reads
as tinted film. Real glass needs refraction + fresnel — a renderer feature,
not a texture feature, so it can't be baked into the file. In the app's
three.js viewer, swap translucent materials for `MeshPhysicalMaterial` with
transmission:

```js
// after GLTFLoader loads the scene:
scene.traverse((node) => {
  if (!node.isMesh || !node.material) return;
  const m = node.material;
  const translucent = m.transparent || m.alphaTest > 0 ||
                      (m.name || "").toLowerCase().includes("glass");
  if (!translucent) return;
  node.material = new THREE.MeshPhysicalMaterial({
    map: m.map,                    // keep the baked tint
    transmission: 0.92,            // real refraction
    roughness: 0.06,
    ior: 1.52,                     // automotive glass
    thickness: 0.02,
    color: new THREE.Color(0x223333),
    envMap: m.envMap ?? scene.environment,
    envMapIntensity: 1.4,
    side: THREE.DoubleSide,
  });
});
```

Notes:
- Requires a `WebGLRenderer` with `antialias: true` and an environment map
  (`scene.environment` from `RoomEnvironment` or an HDRI) — transmission
  samples it for the refraction.
- The worker's wheel materials are named `wheel_*` and are opaque — the
  traverse above never touches them.
- Keep `renderer.toneMapping = THREE.ACESFilmicToneMapping` for the paint
  and metals to read correctly.

## Normal maps

`panel_detail` attaches `material.normalTexture`. three.js (r118+) and
Blender handle tangent-less normal maps automatically — nothing to do in
the app. If the viewer pins an older three.js, call
`geometry.computeTangents()` after load or upgrade.

## Model size

Premium-tier GLBs run 20–40 MB. For the in-app viewer, either load the URL
directly (Supabase serves range requests) or run a one-off Draco/meshopt
compression step server-side. Don't recompress textures — the WebP PBR maps
are already the small form.
