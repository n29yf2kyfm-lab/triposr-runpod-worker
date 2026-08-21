# WORLDWIDE SOURCES — open / freely-obtainable routes to premium car geometry

Research pass, 2026-08-21. Scope: worldwide and non-English open-source **sources of car
geometry, generators, and surfacing tooling**. Everything below was fetched and checked from
this container unless explicitly marked NOT REACHABLE, NOT ESTABLISHED or INFERRED.

---

## THE ANSWER FIRST

**No free source anywhere in the world gives us a premium model of a specific real nameplate.**
The 2026-08-13 RCA already concluded that a premium modern volume car is a paid asset class; a
deliberate worldwide sweep including Chinese platforms does not overturn it. Every free
real-nameplate supply channel found is the same class already mined on Sketchfab, or scans.

**But three things do change the picture at the margin, and all three are cheap to settle:**

1. There is now an open, MIT-licensed **1024³ mesh reconstruction VAE** (TripoSF / SparseFlex,
   VAST-AI). It lets us test the *representation* separately from the *generator* for the first
   time — a question this project has never isolated and which governs everything else.
2. Tencent has open-weighted a generator that takes a **point cloud, voxel grid or bounding box
   as the control signal** instead of a photo (Hunyuan3D-Omni). That is the first tested-able
   answer to the recorded perspective-bake blocker, and it is dimension-drivable.
3. The **DrivAer** body — built by TU Munich with Audi and BMW — is free in **STEP and IGES**,
   i.e. actual NURBS automotive surfaces. It is a generic body, not a nameplate, so it is a
   calibration target and a blockout base, not catalogue supply.

**And one correction to the brief that matters more than any of them:** on this project's own
recorded evidence, surfacing is *no longer* uniformly the blocker, and the Nyquist argument is
half wrong. See "WHERE THIS CONTRADICTS THE FRAMING" at the end. Read that before spending.

---

## THE SINGLE CHEAPEST DECISIVE TEST

**One pod. One point cloud. Two models. ≤ $0.60. It closes or opens the whole open-source
surfacing question.**

Sample a point cloud from a catalogue car whose sharpness is *already measured* — the Kia
Sportage at **crease density 270.7**, top of the recorded catalogue band 162–271 — and put that
same point cloud through both:

| leg | model | what it answers |
|---|---|---|
| A | **TripoSF** VAE, 1024³ reconstruction | **Can a 1024³ sparse representation HOLD a real car's sharpness at all?** This is the ceiling — reconstruction, not imagination. |
| B | **Hunyuan3D-Omni**, `--control_type point` | **Can a 3D-conditioned generator PRODUCE it?** This is what you would actually ship. |

Pre-register the gate before running (this project's own rule):
* **PASS** = crease-density retention ≥ 80% of the 270.7 input, **and** the door shut line
  visible in a locked-camera render at the production azimuth.
* **FAIL on leg A** = no open model in this family can ever emit a premium car surface, because
  the representation cannot even carry one that is handed to it. Surfacing is then closed for
  open source and the money goes to sourcing or licensed heroes. That is a real, cheap, negative
  result and it is worth $0.60 to have it in writing.
* **PASS on A, FAIL on B** = the representation is fine and the generator prior is the limit,
  which points at conditioning/fine-tuning rather than at another generator.

Why this and not "run another generator": every measurement in this project's history has
conflated *"the model can't imagine sharp panels"* with *"the representation can't hold them"*.
Leg A separates them for the first time, has a built-in ground truth, needs only **12 GB VRAM**
(the cheapest GPU tier), and both legs take the same point-cloud input so they share one harness
and one pod.

Second test, only if leg A passes: **Direct3D-S2** on the same input cutout every other
generator has been run on, scored against the same crease ladder (Hunyuan-2.1 43.0 · Hi3DGen 145
· Pixal3D 271.6 · catalogue 162–271). ~$0.30–0.50 on 24 GB.

---

## RANKED SHORTLIST

Ranked by **testability** — cheapest decisive experiment first, as the brief asks.

### 1. TripoSF / SparseFlex — 1024³ sharp-feature mesh reconstruction VAE

* **Who / where:** VAST-AI Research (Chinese; the research arm behind Tripo3D).
  Code <https://github.com/VAST-AI-Research/TripoSF> · weights <https://huggingface.co/VAST-AI/TripoSF>
  · paper <https://arxiv.org/abs/2503.21732>
* **What it outputs:** **not a generator.** A VAE that takes a **point cloud** (sampled from a
  mesh) and decodes SparseFlex parameters to a mesh. `inference.py --mesh-path assets/examples/jacket.obj`
  — mesh in, mesh out. Config exposes `resolution: 1024 # Options: 256, 512, 1024`.
* **Quality read:** claims **~82% Chamfer-Distance reduction and ~88% F-score increase** over
  previous methods, and reconstruction at up to 1024³ — verified in the arXiv abstract. It is
  built on **Flexicubes**, which VAST's own release note describes as differentiably extracting
  meshes *with sharp features*. **INFERRED (moderate-high confidence), not measured here:** that
  lineage places extracted vertices *inside* a cell rather than at cell corners, so an edge can
  land sub-voxel — which is exactly why this is the right instrument for the Nyquist question.
* **Obtainable:** yes. **MIT**, weights public on HF, **≥12 GB VRAM at 1024³**.
* **Cheapest decisive test:** leg A above. Round-trip the Sportage point cloud; measure crease
  retention against 270.7.
* **Honest limit:** a reconstruction VAE **cannot add detail that is not in the input**. Its
  value is as a *ceiling measurement* and possibly as a re-mesher — never as a source of cars.

### 2. Hunyuan3D-Omni — generation controlled by point cloud / voxel / bounding box

* **Who / where:** Tencent Hunyuan. <https://github.com/Tencent-Hunyuan/Hunyuan3D-Omni> ·
  weights <https://huggingface.co/tencent/Hunyuan3D-Omni> (16.9K downloads, 182 likes) ·
  paper <https://arxiv.org/abs/2509.21245>
* **What it outputs:** a 3D shape, but conditioned on **3D**, not on a photograph. Abstract,
  verbatim: *"accepts point clouds, voxels, bounding boxes, and skeletal pose priors as
  conditioning signals, enabling precise control over geometry, topology, and pose."*
  Usage is literally `python3 inference.py --control_type point|voxel|bbox|pose`.
* **Why it is structurally different from everything tested here:** every generator this project
  has run (TRELLIS.2, PartCrafter, Hunyuan3D-2, Hi3DGen, Pixal3D) is conditioned on **one image**.
  CLAUDE.md's Hi3DGen entry names the consequence and the fix in the same paragraph — *"the photo's
  perspective enters the geometry… the fix is TRUE MULTI-VIEW conditioning, which Hi3DGen does not
  have"*. A point cloud or a bounding box is not a viewpoint, so it cannot bake perspective, and
  `bbox` control is a **dimension-driven** lever.
* **Obtainable:** yes. Weights public, **10 GB VRAM**, licence recorded as `other` (Tencent
  community terms) — recorded as a field, per standing instruction, not chased.
* **Cheapest decisive test:** leg B above, sharing leg A's point cloud.
* **Honest caveat, stated up front:** control fixes *shape and proportion*; the **surface prior is
  still Hunyuan's**, which is the softest thing on this project's ladder (**crease 43.0**). It is
  entirely possible this fixes dimensions and does nothing for surfacing. That is precisely why it
  is run against a known-sharp input — a soft output from a sharp input kills it in one run.

### 3. Direct3D-S2 — native 1024³ generation with Spatial Sparse Attention

* **Who / where:** DreamTech (Chinese). NeurIPS 2025.
  <https://github.com/DreamTechAI/Direct3D-S2> · weights <https://huggingface.co/wushuang98/Direct3D-S2>
  (subfolder `direct3d-s2-v-1-1`) · paper <https://arxiv.org/abs/2505.17412>
* **What it outputs:** **geometry only**, OBJ, from a single image. No texture stage.
* **Quality read / why it is not just another generator:** it is a sparse-volume DiT with a
  purpose-built sparse attention mechanism (3.9× forward / 9.6× backward speedup) and a unified
  sparse VAE, which is what lets it *train* at 1024³ on 8 GPUs. That is a different architecture
  from the structured-latent (TRELLIS/Pixal), the normal-bridged (Hi3DGen) and the part-native
  (PartCrafter) families already measured. Its README explicitly discourages 512 — *"we don't
  recommend generating models at 512 resolution, as it's just an intermediate step"* — i.e. 1024
  is the intended operating point, not a stretch mode.
* **Obtainable:** yes. **MIT** code and weights, **~24 GB VRAM at 1024**.
* **Cheapest decisive test:** the same input cutout as every prior generator, crease density +
  the eye. Run **only after leg A passes** — if a 1024³ representation cannot hold a sharp car,
  a 1024³ generator certainly will not make one.

### 4. DrivAer CAD (TU Munich + Audi + BMW) — free NURBS car surfaces, STEP and IGES

* **Where:** <https://www.epc.ed.tum.de/en/aer/research-groups/automotive/drivaer/geometry/> →
  download page offers `STEP_complete.zip`, `IGES_complete.zip`, `STL_complete.zip`.
* **What it outputs:** a real, modular car body in **B-rep CAD** — three rear ends (fastback,
  notchback, estateback), 18 configurations, with wheels/mirrors/underbody variants. This is the
  only genuinely CAD-surfaced car body I could verify as free anywhere in the world.
* **Quality read:** designed to *"close the gap between strongly simplified models such as the
  Ahmed body and highly complex production cars"* — so: real automotive surfacing discipline,
  aero-grade, but **no shut lines, no lamp internals, no grille detail, and it is not a nameplate.**
  It cannot become a Ford Puma.
* **Its actual value here, and it is real:** a **calibration target**. Every "premium bar" number
  this project uses is derived from sourced Sketchfab cars. Measuring crease density and surface
  continuity on a body co-developed by Audi and BMW gives an honest yardstick for the first time —
  and it is a legitimate blockout/base for hand-building a generic hatch/saloon.
* **Obtainable:** free, **registration required** (`/restricted/DrivAER/` paths). I did not
  register — standing instruction not to sign up. **Owner or a human needs to fill one form.**
* **Licence:** the page states no explicit terms beyond free-with-registration. Recorded as a
  field.

### 5. 3DRealCar — 2,500 real cars, ~200 dense 360° RGB-D views each, Apache-2.0

* **Who / where:** Univ. of Queensland + UTS + **Li Auto (理想汽车)** + Peking University. ICCV 2025.
  <https://github.com/xiaobiaodu/3DRealCar_Toolkit> · <https://arxiv.org/abs/2406.04875> ·
  project page <https://xiaobiaodu.github.io/3drealcar/>
* **What it outputs:** RGB-D image sets and point clouds — **no meshes confirmed** — with
  **real-world dimensions**, 100+ brands, three lighting conditions, and (a first) 3D car parsing
  map annotations.
* **Quality read as a SOURCE: fails.** Smartphone scans. This project has already established
  that photogrammetry scans mean soft panels, baked lighting and windows as holes.
* **Quality read as CONDITIONING or TRAINING DATA: genuinely different.** It is the only large,
  **Apache-2.0**, real-car, dense multi-view capture set found anywhere. It bears on two recorded
  items: the perspective-bake fix ("true multi-view conditioning"), and the fine-tune section's
  own precondition for reopening — *"a dataset in the thousands, not tens"*. 2,500 cars is
  thousands.
* **Obtainable:** download is via the project page. **NOT VERIFIED from here** — the README points
  at a download page and does not state format or size, and I did not confirm the mechanism.
* **Cheapest decisive test:** pull one car, check whether the 200 views are calibrated (poses +
  intrinsics) and whether the point cloud is dense enough to drive item 2's `--control_type point`.
  Free, no GPU.

### 6. Step1X-3D — open geometry + texture, Apache-2.0

* **Who / where:** StepFun (Chinese). <https://github.com/stepfun-ai/Step1X-3D> ·
  <https://huggingface.co/stepfun-ai/Step1X-3D> · <https://arxiv.org/abs/2505.07747>
* **What it outputs:** two-stage — hybrid VAE-DiT geometry (watertight TSDF, with **"sharp edge
  sampling for detail preservation"**) then SD-XL-based texture synthesis. Weights **and training
  code** released May 2025, Apache-2.0.
* **Quality read:** the sharp-edge sampling is the interesting bit, but architecturally this sits
  much closer to what has already been measured than items 1–3 do. **Lower priority.** Run only
  if item 3 clears, as a second opinion.

### 7. Shut lines as projected decals, not as generated geometry — a technique, not a repo

Not a source; a way of making the Nyquist problem irrelevant. The DCC world does not model a
2–4 mm panel gap as geometry — it **projects a mesh decal carrying baked normal + AO** onto the
surfaced body. The mature tools are the Blender panel/decal ecosystem (DECALmachine, Panel
Cutter, easy.panelling, GFM Editor, Fluent — Fluent ships localised in Chinese, Japanese and
Russian, which is how it stays invisible to English search). **Costing that tooling is the other
agent's lane and I have not priced it.** The point that is mine: this project already has a
texture-projection stage (`photo_project.py`) and a verified normals discipline
(`normals_fix.py`), so the *machinery* for decal-projected shut lines mostly exists. If leg A
fails, this is the route that still produces a shut line.

---

## RESEARCHED AND REJECTED — with the reason, so nobody re-runs these

| candidate | verdict | why |
|---|---|---|
| **CARLA vehicle assets** | reject | Their own authoring spec: *"Vehicles should have between 50,000 and 100,000 faces"* — game/physics budgets, an order below this catalogue (500k–1M). The 8-part material scheme (Bodywork / Glass_Ext / Glass_Int / Lights / LightGlass ×2 / LicensePlate / Interior) is a decent structure reference and nothing more. |
| **ApolloCar3D (Baidu)** | reject for now | 79 "industry-grade" CAD models with absolute size, real nameplates — but mostly older Chinese-market cars, and they are **pose-fitting shape models re-saved to pkl**, not visual assets. The download host (`ad-apolloscape.*.bcebos.com`) returns **403 from this container** so I could not measure one. |
| **DrivAerNet / DrivAerNet++** | reject as supply | 8,150 designs — but all **morphs of the one generic DrivAer body** via 26 aero parameters. **CC BY-NC**, ~39 TB on Harvard Dataverse, and the HF mirror `MoElrefaie/DrivAerNet` is **gated** (could not inspect). It has 29 part labels incl. doors and mirrors, which is interesting; it still cannot produce a named car. Use the parent DrivAer CAD (item 4) instead. |
| **Sparc3D** | **RE-CHECKED, unchanged** | Repo is still `assets/images/`, `.gitignore`, `README.md` and nothing else. CLAUDE.md's 2026-08-13 finding stands — no code, no weights. |
| **Seed3D 1.0 / 2.0 (ByteDance Seed)** | reject | Simulation-ready assets from one image, shipped on **Volcano Engine (API)**. No open weights found. Commercial/cloud tier, same bucket as Hunyuan 3.x Pro / Rodin / Tripo, all of which the owner already declined. |
| **Hunyuan3D 2.1** | no change | Already this project's fine-tune base (crease 43.0). The only *newer* open Tencent geometry releases are Hunyuan3D-Part (tested, cannot separate glazing — settled) and Hunyuan3D-Omni (item 2). Hunyuan 3.x remains API-only. |
| **Artist-mesh generators** (MeshAnything V2, DeepMesh, Nautilus, EdgeRunner) | reject | Structurally attractive — they emit artist-style topology with sharp edges — but the face budgets are fatal: **MeshAnything V2 up to 1,600 faces; DeepMesh up to ~30k**. A premium car here is 500k–1M. |
| **Mesh → B-rep / NURBS** (Point2CAD, ComplexGen, SED-Net, ParSeNet) | reject | Aimed at mechanical CAD — planes, cylinders, segmented primitive fitting. Point2CAD does add freeform neural patches, but **nothing demonstrates any of them on a full freeform car body**, and no maintained open implementation was found for that use. Commercial equivalents exist (Cyborg3D MeshToCAD) and are not open. |
| **Chinese CAD kernels** (AMCAX / 九韶) | reject | The **application** (九韶精灵 / AMCAX-Daemon) is open; the **kernel is not**. No open Chinese geometry kernel found that does Class-A surfacing. OpenCASCADE remains the only serious open B-rep kernel and it is not a Class-A tool. |
| **Free 3D marketplaces** (BlenderKit, Free3D, Open3dModel, TurboSquid free tier, Hum3D free) | reject | Same supply class already mined on Sketchfab. The recorded RCA applies unchanged: free supply concentrates on halo/classics; modern volume cars are scans or converter-clay. Nothing here is a new channel. |
| **ModelScope (魔搭)** | reject as a distinct source | **Reachable and searchable via its API** — I ran EN and Chinese queries (`3D generation`, `image to 3D`, `mesh generation`, `三维生成`, `3D资产`, `网格生成`, `汽车 3D`, `点云 重建`). Everything 3D-geometry-native on it is a **mirror** of HF/GitHub (Tencent-Hunyuan 2 / 2.1 / 2mv / 2mini / Part / Omni, microsoft/TRELLIS.2-4B, AI-ModelScope re-uploads). The Chinese-original content in that space is image-generation LoRAs, not geometry. **This is the direct answer to "look at Chinese hosting": the Chinese 3D-geometry frontier is published on HuggingFace and GitHub, not hidden on ModelScope.** |

---

## NOT REACHABLE FROM THIS CONTAINER (recorded, not guessed)

| host | result |
|---|---|
| `ad-apolloscape.cdn.bcebos.com` / `.bj.bcebos.com` | **403** — ApolloCar3D data cannot be pulled or measured here |
| `grabcad.com` | **403** to both curl and WebFetch — could not survey its free STEP car library |
| `turbosquid.com`, `free3d.com`, `hum3d.com`, `aigei.com` | **403** |
| `cgmodel.com`, `3dxy.com` | connection failed (000) |
| `dspace.lib.cranfield.ac.uk` (Cranfield DrivAer CAD packs) | Anubis bot wall |
| `huggingface.co/datasets/MoElrefaie/DrivAerNet` | **gated** — structure and schema unreadable |
| `openxlab.org.cn`, `wisemodel.cn` | **reachable (200) but client-rendered SPAs** — I could not enumerate their catalogues, and my guessed API endpoints 404/500. Treat as UNSURVEYED, not as empty. |
| `modelscope.cn`, `gitee.com`, `csdn.net`, `zhihu.com`, `3ddd.ru`, `cgtrader.com`, `3d66.com`, `blenderkit.com`, `carbodydesign.com` | reachable |

---

## WHAT I COULD NOT ESTABLISH

* **Whether any of items 1, 2, 3 or 6 produces a good CAR.** None has been run on a vehicle here.
  Every quality claim above is the authors', or an architectural argument. That is exactly why the
  deliverable is a $0.60 test and not a recommendation to switch anything.
* **ApolloCar3D mesh quality** — download host 403. Face counts, part separation and whether the
  glazing is separate geometry: **NOT ESTABLISHED**.
* **3DRealCar download mechanism, file format and total size** — **NOT ESTABLISHED** (README
  points at a project page and states nothing).
* **DrivAer surface continuity class** — whether the STEP/IGES surfaces are true Class-A
  (curvature-continuous) or merely tangent-continuous aero surfaces: **NOT ESTABLISHED**, needs the
  file, which needs the registration form.
* **Whether OpenXLab or WiseModel host anything unique** — unsurveyed, see above. Low expected
  value given the ModelScope result, but stated as unknown rather than as zero.
* **Sub-voxel edge placement in Flexicubes-family extraction** — INFERRED from the method family
  and VAST's own description, **not measured**. Leg A of the test measures it directly.

---

## WHERE THIS CONTRADICTS THE FRAMING

Two things in the brief are, on this project's own recorded evidence, not right. Both change what
the money should do, so they are stated plainly.

### 1. "Every generator fails on melted panels and absent shut lines — including Pixal3D"

CLAUDE.md says the opposite about Pixal3D, twice, with numbers:

* **2026-08-15** — *"the first generated car in this project's history to reach catalogue-grade
  geometry"*: crease/diag **271.6**, sharp_share 5.07%, against a catalogue band of **162–271**
  (Sportage 270.7). Renders showed *"headlamp internals, grille slats, a door shut line, formed
  mirrors, real wheel spokes"*. The entry's own conclusion: *"This overturns 'every open model hits
  the same ceiling' — the ceiling was the CONDITIONING, not the resolution."*
* **2026-08-19** — the Pixal Yaris: *"the first generated car that looks like a real car: Toyota
  badge on the grille, headlamp units with internal structure, door shut lines, door handles,
  formed mirrors, alloy spokes, number plate, tail lamps."*

The blockers recorded *after* Pixal3D are not melt. They are **front/rear component kits (the
fascia is named the dominant defect), doors not separate, ragged aperture silhouettes**, plus the
non-geometry ones — no mobile serving path, `glass_probe`'s area blind spot. Those are
**construction and pipeline** problems, and the machine (`premium.py`, 12 PASS / 0 FAIL / 5 OPEN)
is already aimed at them.

**Consequence for spend:** buying a *fourth* generator is a lower-value move than the brief
implies. If leg A of the test passes, the honest ranking is: finish the component kits > try
3D-conditioned generation (item 2, which fixes proportions/dimensions rather than surfaces) >
try another generator.

### 2. "A shut line is 2–4 mm and Pixal at 1536 is ~2.5 mm/voxel, so Nyquist is violated by construction"

Half right, and the wrong half is load-bearing.

* **Right** about a shut line as a **groove**. Two edges 2–4 mm apart cannot be resolved by a
  2.5–4 mm grid. No amount of resolution tuning gets you a real panel gap with a floor and two
  walls.
* **Wrong** as a bound on a sharp **crease**. These models do not read geometry off voxel corners;
  the Flexicubes/dual-contouring extraction layer places each vertex **anywhere inside its cell**,
  so a single sharp edge can land sub-voxel. (INFERRED from the method family — VAST describe
  Flexicubes as differentiably extracting meshes *with sharp features* — and consistent with this
  project's own observation of a visible door shut line on Pixal3D at 1536.)

**Consequence:** "Nyquist forbids it" should not be used to close the surfacing question. It
forbids the *groove*, which is why item 7 (project the shut line as a normal-mapped decal rather
than generating it) is the sane response, and it does not forbid a crisp panel crease, which is
what the eye is actually reading in the owner's rubric ("door and bonnet shut lines not defined").

---

## ONE-LINE NOTES FOR THE OTHER TWO AGENTS (not pursued here)

* **To the OEM-dimension agent:** Hunyuan3D-Omni's `--control_type bbox` makes published overall
  L/W/H a *generation control*, not just a post-hoc validation target — worth knowing when you
  cost dimensional data.
* **To the tooling/reference agent:** the shut-line problem has a mature paid Blender toolchain
  (DECALmachine, Panel Cutter, easy.panelling, GFM Editor, Fluent — the last localised in Chinese /
  Japanese / Russian, which is why English searches miss it). Pricing it is yours; I have only
  noted that the technique is decal projection, not modelled geometry.

---

## SOURCES (all fetched and verified from this container unless noted)

* TripoSF — <https://github.com/VAST-AI-Research/TripoSF> · <https://huggingface.co/VAST-AI/TripoSF> · <https://arxiv.org/abs/2503.21732>
* Hunyuan3D-Omni — <https://github.com/Tencent-Hunyuan/Hunyuan3D-Omni> · <https://huggingface.co/tencent/Hunyuan3D-Omni> · <https://arxiv.org/abs/2509.21245>
* Direct3D-S2 — <https://github.com/DreamTechAI/Direct3D-S2> · <https://huggingface.co/wushuang98/Direct3D-S2> · <https://arxiv.org/abs/2505.17412>
* Step1X-3D — <https://github.com/stepfun-ai/Step1X-3D> · <https://huggingface.co/stepfun-ai/Step1X-3D> · <https://arxiv.org/abs/2505.07747>
* DrivAer geometry — <https://www.epc.ed.tum.de/en/aer/research-groups/automotive/drivaer/geometry/> and its download page
* DrivAerNet++ — <https://github.com/Mohamedelrefaie/DrivAerNet> · <https://arxiv.org/pdf/2406.09624> · HF mirror gated
* 3DRealCar — <https://github.com/xiaobiaodu/3DRealCar_Toolkit> · <https://arxiv.org/abs/2406.04875>
* ApolloCar3D — <https://github.com/ApolloScapeAuto/dataset-api> (`car_instance/README.md`, `car_models.py` read; data host 403)
* CARLA vehicle authoring spec — <https://carla.readthedocs.io/en/latest/tuto_content_authoring_vehicles/>
* Sparc3D (re-check) — <https://github.com/lizhihao6/Sparc3D>
* Seed3D — <https://seed.bytedance.com/en/public_papers/seed3d-1-0-from-images-to-high-fidelity-simulation-ready-3d-assets>
* ModelScope — searched live via `https://www.modelscope.cn/api/v1/dolphin/models` (EN + Chinese queries)
