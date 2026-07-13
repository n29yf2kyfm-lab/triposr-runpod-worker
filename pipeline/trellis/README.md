# TRELLIS.2 → Blender car pipeline

Base-mesh generation with **TRELLIS.2-4B** (image-to-3D), then **Blender** as the
correction / assembly / optimisation stage. All tooling is free/open-source. This
is the "prove it properly before licensing a full vehicle" route.

**Not claimed:** OEM accuracy. Nothing here is called OEM-accurate until it is
measured against real dimensions + reference imagery (stage QC-13).

Endpoint: RunPod `nd0fagqlr5z2ur` (TRELLIS.2-4B) — image-to-3D, PBR out.

---

## Dependencies (all free / OSS)

| Tool | Licence | Install | Stage |
|---|---|---|---|
| pillow, numpy, scipy | PIL/BSD | `pip install pillow numpy scipy` | prep, score |
| rembg (u2net / BiRefNet) | MIT / Apache | `pip install rembg onnxruntime` | image prep |
| trimesh | MIT | `pip install trimesh` | scoring |
| TRELLIS.2-4B (RunPod) | MIT | already deployed (endpoint above) | generation |
| Blender + bpy | GPL | `apt install blender` | correction/assembly |
| Instant Meshes | BSD | GitHub binary (manual) | retopo (human step) |
| glTF-Transform | MIT | `npm i @gltf-transform/cli` | optimise |
| gltf-validator | Apache | `npm i gltf-validator` | QC |

---

## Stage-by-stage — exact commands, settings, limitations

### 1–2  Reference images + clean background
```bash
python pipeline/trellis/prep_images.py --in refs/ --out pipeline/build/prepped \
    --model birefnet-general --min-cov 0.18
```
- **Ideal input:** clean/neutral background, even light, car filling ~80% of frame,
  3/4 front and 3/4 rear. RGBA cutout is passed straight to TRELLIS.2 (its own
  bg-removal is skipped when alpha is present).
- **Limitation:** glossy paint mirrors the sky → free matte-cutout leaks
  reflections. BiRefNet-general is the best free model; chrome/glass may still need
  a manual mask touch-up in GIMP/Krita. Car-park phone snaps are *marginal* — the
  cleaner the shot, the better the mesh.

### 3  Generate TRELLIS.2 candidates
```bash
python pipeline/trellis/generate.py --in pipeline/build/prepped \
    --out pipeline/build/candidates --seeds 0,1,2,3 --texture 2048 --decimate 500000
```
- **Settings:** `seed` (vary for candidates), `texture_size` 1024 mobile / **2048**
  default / 4096 hero, `decimation_target` 200k web / **500k** default / 800k detail.
- **Limitation:** this handler is **single-image per call** — no multi-view fusion
  yet, so the unseen back/underside is hallucinated. Generate several seeds/angles
  and pick the best. Multi-image fusion = a TRELLIS.2 `multiimage` upgrade to
  `trellis/handler.py` (scoped, not wired). Cold start minutes; ~2–6 min/candidate.

### 4  Automated scoring / rejection
```bash
python pipeline/trellis/score.py --dir pipeline/build/candidates --min 0.62
```
- Scores **symmetry, proportions (vs Golf 4.26×1.79×1.45 m), roundness (wheels),
  cleanliness (melt/blob)**; prints ACCEPT/reject, writes `scores.json`.
- **Limitation:** heuristics, not a trained critic — catches gross failures; a human
  still eyeballs the winner.

### 5–9  Blender correction + assembly
```bash
blender -b -noaudio --python pipeline/blender/process_candidate.py -- \
   --in pipeline/build/candidates/<winner>.glb \
   --panels pipeline/blender/golf_panels_ref.json \
   --components pipeline/components --out pipeline/build/golf_trellis.glb
```
- Does: symmetry mirror, corrective smooth, weighted normals, merge/normals;
  component replacement from `pipeline/components/{wheel,mirror,headlight,taillight,
  grille,badge,handle}.glb`; panel separation by reference bbox; interior/engine-bay
  asset import.
- **Limitations:** symmetry mirroring assumes one clean half; **panel cuts are by
  bounding-region, not true shut-lines** (ragged unless loops exist → clean cuts are
  manual); **retopology to quads is a separate human step** (Instant Meshes /
  QuadRemesh); component replacement needs a **hand-made/licensed component
  library** — without it the weak generated wheels/lights remain.

### 10  Rigging
```bash
blender -b -noaudio --python pipeline/blender/rig_panels.py -- \
   --in pipeline/build/golf_trellis.glb --spec pipeline/build/panels.json \
   --out pipeline/build/golf_trellis_rigged.glb
```
Origin→hinge + open/close clips for the separated panels (proven: 3 clips, 0/0).

### 11  LOD
`process_candidate.py` also writes `_lod1` (≈40% decimate). Add a 512-texture
mobile tier via glTF-Transform `resize`.

### 12  Validated, compressed export
```bash
node pipeline/validate.js pipeline/build/golf_trellis.glb        # 0 errors required
bash pipeline/optimise.sh pipeline/build/golf_trellis.glb pipeline/build golf_trellis
```
→ Draco + Meshopt, WebP (KTX2 when `toktx` installed). Keep the uncompressed master.

### QC-13  Accuracy check (before any "accurate" claim)
- Overlay renders against the reference photos at matched camera angles.
- Compare bbox to published Golf dims (4.26 × 1.79 × 1.45 m); flag >5% deviation.
- Only then may the asset be described as *reference-matched* — never "OEM" without
  measured proof.

---

## Honest overall expectation
TRELLIS.2 + this pipeline can get a **recognisable, riggable, web-optimised** Golf
that beats the sourced mesh **if** (a) inputs are clean multi-angle, (b) a component
library exists for wheels/lights/mirrors, and (c) a human does the retopo + shut-line
cuts. It will **not**, on its own, reach configurator/OEM accuracy from phone photos.
That remains the licensed-model route — but this pipeline is the honest way to test
how close free tooling gets first.
