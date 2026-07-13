# ExpertCarCheck — free/open-source car 3D pipeline

**Role split:** Claude is the coding lead — it generates the Blender Python,
shell commands, viewer code and QC gates in this folder. **A real Blender
environment / developer executes the geometry work.** Accurate automotive
panels, retopology and animation rigging are **manual human tasks**; the
automation here handles inspection, safe cleanup, validation, optimisation,
delivery and testing. No paid software or paid AI APIs are used.

> **Hard rules honoured:** never claims AI can produce OEM CAD accuracy; never
> replaces modelling with image generation; never downloads copyrighted models;
> keeps an untouched master; preserves door/bonnet/boot hierarchy and animation
> through optimisation; never optimises before geometry + animation are approved.

---

## 1. Tool table (approve before installing anything)

| Tool | Purpose | Licence | Install | Local | GPU | Commercial‑safe | Connects to | Risks / limits |
|---|---|---|---|---|---|---|---|---|
| **Blender** | Master modelling, retopo, UV, materials, rig, light, render, GLB export | GPL‑2.0+ | apt/brew | ✅ | opt (Cycles) | ✅ (GPL app; your assets are yours) | Everything; runs bpy scripts here | GPL is for the app, not your output — fine |
| **Blender Python (bpy)** | Automation of import/QC/clean/export | GPL‑2.0+ | ships with Blender | ✅ | – | ✅ | `blender -b --python …` | Don't auto‑model panels blindly |
| **MeshLab / PyMeshLab** | Inspect, clean, decimate, batch repair | GPL‑3.0 / LGPL | apt / `pip install pymeshlab` | ✅ | – | ✅ | Batch clean before Blender | Auto‑clean can damage sharp edges/badges |
| **Instant Meshes** | Retopo *starting point* for smooth panels | BSD‑style | GitHub binary | ✅ | – | ✅ | Feeds Blender retopo | Never trust on shut‑lines/grilles/lights |
| **Open3D** | Point clouds, scan align, measurement | MIT | `pip install open3d` | ✅ | opt | ✅ | Scan → Blender | Not an OEM‑finish generator |
| **Material Maker** | Node‑based PBR maps (paint/leather/rubber…) | MIT | GitHub binary | ✅ | ✅ | ✅ | Exports maps → Blender/glTF | Keep maps glTF‑compatible |
| **GIMP** | Texture/mask/decal editing | GPL‑3.0 | apt/brew | ✅ | – | ✅ | Edits texture PNGs | Never bake lighting into base‑colour |
| **Krita** | Hand‑painted texture detail | GPL‑3.0 | apt/brew | ✅ | – | ✅ | Texture maps | – |
| **Inkscape** | Vector badges/dash icons/decals | GPL‑3.0 | apt/brew | ✅ | – | ✅ | SVG → decal/texture | Convert vectors carefully |
| **glTF‑Transform** | Inspect + optimise GLB (dedup/prune/webp/draco/meshopt) | MIT | `npm i @gltf-transform/cli` | ✅ | – | ✅ | Post‑export CLI | Aggressive flags can drop data — checked |
| **meshoptimizer / gltfpack** | Geometry compression, quantise, vertex‑cache | MIT | `npm i gltfpack` | ✅ | – | ✅ | Compresses GLB | Verify small parts/normals survive |
| **Basis Universal / KTX2 (toktx)** | GPU texture compression, per‑device tiers | Apache‑2.0 | KTX‑Software release | ✅ | opt | ✅ | glTF‑Transform `uastc`/`etc1s` | Not installed yet → WebP fallback in use |
| **Khronos glTF Validator** | Spec compliance gate | Apache‑2.0 | `npm i gltf-validator` | ✅ | – | ✅ | `node validate.js` (CI gate) | Errors = release blocker |
| **Three.js** | Interactive web viewer engine | MIT | `npm i three` | ✅ | ✅ (client) | ✅ | `viewer/` | Bundle for prod (don't ship CDN) |
| **React Three Fiber + Drei** | React wrapper for the viewer | MIT | `npm i @react-three/fiber @react-three/drei` | ✅ | ✅ | ✅ | If app stays React | Only if it beats plain three |
| **Babylon.js (+ Sandbox)** | Alt engine / quick GLB inspection | Apache‑2.0 | web / npm | ✅ | ✅ | ✅ | QA inspection | Pick ONE engine — don't build twice |
| **model‑viewer** | Simple product viewer (current app) | Apache‑2.0 | npm/CDN | ✅ | ✅ | ✅ | Lovable app now | Too restrictive for per‑door interaction |
| **Playwright** | Automated browser/viewer testing | Apache‑2.0 | `npm i -D @playwright/test` | ✅ | – | ✅ | `testing/` | – |
| **Lighthouse** | Web performance budgets | Apache‑2.0 | `npm i -D lighthouse` | ✅ | – | ✅ | perf gate | – |
| **Spector.js** | WebGL frame/draw‑call inspection | MIT | browser ext / script | ✅ | – | ✅ | GPU debug | – |
| **Git / GitHub** | Version control (LFS for big GLB) | MIT/– | apt/brew | ✅ | – | ✅ | this repo | Use LFS/Supabase for large binaries |

**Engine decision:** the app is on **model‑viewer** today (fine for spin/zoom).
For per‑door/bonnet/boot interaction and a configurator, move to **Three.js**
(`viewer/`) — the code here is ready. Stay on one engine.

---

## 2. Folder structure
```
pipeline/
  masters/     # untouched source GLBs (never edited)         ← keep forever
  build/       # cleaned + optimised outputs (regenerable)
  reports/     # QC audits + validator + Lighthouse/Spector JSON
  blender/     # qc_audit.py, clean_export.py  (bpy, headless)
  viewer/      # Three.js viewer (car-viewer.js + index.html)
  testing/     # Playwright acceptance + PERF_PLAN.md
  install.sh   validate.js   optimise.sh   README.md
```

---

## 3. Recommended pipeline
```
source GLB → masters/
  → blender/qc_audit.py           (inspect: normals, manifold, hierarchy, tris)
  → MANUAL modelling in Blender   (panels, retopo, CUT doors/bonnet/boot apart)   ← human
  → blender/rig_panels.py         (auto: origin→hinge, open/close animation clips)
  → blender/clean_export.py       (safe weld + normals + tangents, hierarchy-preserving GLB)
  → node validate.js              (Khronos spec — 0 errors required)
  → optimise.sh                   (dedup/prune/webp → Draco + Meshopt variants)
  → node validate.js (outputs)    (re-check after compression)
  → viewer/ (Three.js)            (integrate)
  → testing/ (Playwright+Lighthouse+Spector)  (desktop + mid + low mobile)
  → visual compare vs reference   → release
```

---

## 4. Proven on the current Golf (real run, this repo)

| Stage | Result |
|---|---|
| QC audit (`qc_audit.py`) | 18 objects · 260,253 tris · degenerate 108 · **flipped 0** (per‑shell signed‑volume test); panels grouped by material, **doors/bonnet/boot NOT separable** |
| Safe clean (`clean_export.py`) | degenerate **108 → 0**, normals recalculated, **tangents exported**, hierarchy kept |
| Validate (`validate.js`) | **0 errors, 0 warnings** ✅ (tangents cleared the 6 warnings) |
| Optimise (`optimise.sh`) | clean → **Draco 1.0 MB** / Meshopt 1.9 MB (WebP textures) |
| Rig (`rig_panels.py`) | proven on a separable test car → **3 animation clips** (`bonnet_open`, `door_front_left_open`, `door_front_right_open`), validator 0/0 |
| Viewer (`viewer/`) | loaded a rigged GLB in real Chromium → WebGL render, contact shadow, **paint switch + door/bonnet/boot toggles + camera presets all working** |

**The normal metric is fixed:** the old "inward vs object‑centroid" test
false‑positived on interior concavity (reported 42k). The new **per‑shell
signed‑volume** test correctly reports **0** inverted shells on the Golf.

**What the automation cannot do (needs a human in Blender):** the Golf's panels
are welded per‑material, so **doors/bonnet/boot must be cut into separate meshes
first** (clean shut‑lines, capped apertures) — manual automotive modelling. Once
separated, `rig_panels.py` auto‑rigs them and `viewer/` drives the animations.
Soft rear quarter/skirts + true OEM accuracy also need a licensed base mesh.

---

## 5. Change log & rollback
- Masters in `masters/` are **never** modified — every stage writes a new file
  in `build/`. Rollback = delete `build/` and re‑run; the master is intact.
- Large GLBs should live in Git **LFS** or Supabase, not committed raw. This
  folder commits **scripts + reports**; sample build artifacts stay out of Git.
- Each release tags the git SHA and attaches the `reports/` JSON (QC +
  validation + Lighthouse) as the acceptance evidence.
