# Project Plan

## Part 0 — What this repo actually is

The name says `triposr-runpod-worker`, but the repo has outgrown it. What it really is:

> **A platform for running heavy 3D/AI GPU jobs as RunPod serverless workers, with the
> hard operational problems already solved.**

It currently hosts one product line — vehicle 3D generation for an AI-mechanic app — across
three generations of worker. This plan adds a second product line on the same platform:
**a building scanner that reconstructs a real property 1:1, inside and out, including the
pipes and wires behind the walls, and then prices work and audits condition.**

The two products share almost all of their infrastructure. That is the central point of
this document.

---

## Part 1 — What already exists

### 1.1 Three workers, one lineage

| Worker | Model | Does | State |
|---|---|---|---|
| `handler.py` (root) | TripoSR | Single image → GLB, ~100 lines | v10.1, deployed to endpoint `mj7aiqksmbnkw1` |
| `trellis/` | TRELLIS v1 | text + image → 3D, sparse-conv latents | Superseded |
| `trellis2/` | TRELLIS.2-4B | image → 3D with full PBR; text → 3D via built-in SDXL stage | **Current. ~3,400 lines. Production-hardened.** |

`trellis2/` is the serious one, and it is the template for everything that follows.

### 1.2 What `trellis2/` proves

Reading the code, this is not a prototype. Nearly every non-obvious line exists because a
live run failed and the fix was written down. Some highlights, because they are exactly
the problems the building worker will hit:

**RunPod silently drops large outputs.** Confirmed live: a job returned `COMPLETED` with
`output=None` because the GLB exceeded the response cap. The fix — `upload_to_supabase()`
as primary delivery, inline base64 only under `MAX_INLINE_BYTES` (4 MB), and a loud
warning when neither channel can deliver — is already written and tested. **Point clouds
and IFC models are far bigger than GLBs, so the building worker would have hit this on day
one.** It is already solved.

**Cold starts must not redownload multi-GB weights.** `HF_HOME=/runpod-volume/hf_cache`
puts the cache on the network volume; `preload_models.py` fetches every model in one shot
and reports precisely which gated licences still need accepting; `OFFLINE=1` then flips on
`HF_HUB_OFFLINE` so a cache miss fails fast instead of hanging on a download.

**CUDA extensions do not build themselves on a GPU-less CI runner.** The Dockerfile carries
a set of hard-won fixes: explicit `TORCH_CUDA_ARCH_LIST="8.0;8.6;8.9;9.0+PTX"` (nvcc cannot
autodetect with no GPU present), `--no-build-isolation` for extensions whose `setup.py`
imports torch, `setuptools>=64` upgraded *before* nvdiffrast (stock setuptools installed it
as an empty package named "UNKNOWN"), `MAX_JOBS=4` to cap parallel nvcc, prebuilt
flash-attn wheels tried before a source compile, and a deliberate refusal to install
`pillow-simd` because its build lacked WebP and broke GLB export. **COLMAP, Open3D, gsplat
and PDAL need exactly this treatment.**

**Long jobs need progress.** `runpod.serverless.progress_update()` publishes the
intermediate image the moment it exists, so the app shows something while the slow 3D stage
runs. A building scan takes minutes — this pattern is essential, and already proven.

**Tracebacks leak internals.** Errors return `{"error": str(e)}`; the full trace goes to
worker logs unless `DEBUG=1`.

**Input must be validated and clamped.** Bad types return a clear message; extreme
`texture_size`/`decimation_target` values are clamped so a caller cannot OOM the worker.

**Tests run without a GPU.** `test_handler.py` (674 lines, 20 tests) stubs the heavy
modules before importing the handler, so handler logic — validation, clamping, delivery,
size gating, every post-processing stage — is testable in CI in seconds.

**Vendoring beats cloning at build time.** TRELLIS.2's source is vendored into the repo at
a recorded `UPSTREAM_COMMIT` with a `WORKER_CHANGES.md` delta. Builds are reproducible, no
upstream drift, and modifications land through normal git history. **This is exactly how
Cloud2BIM should be brought in.**

**There is a route from a fresh pod to a smoke test.** `pod_setup.sh` bootstraps a bare
RunPod GPU pod into a working worker and runs a real end-to-end generation. Idempotent,
safe to re-run.

**There is a fine-tuning pipeline.** `training/` holds dataset spec, caption generation
from a CSV export, and a LoRA training script, with the inference hook (`T2I_LORA`) already
wired into the handler. **The defect-detection models in Condition Mode will need exactly
this scaffolding.**

### 1.3 Honest state

`trellis2/README.md` says plainly that the stack has not been GPU-build-tested in this
environment, and lists the three most likely first-build failures. That honesty is worth
preserving in the new work.

---

## Part 2 — The new product: building scanner

Four modes, one model.

| Mode | What it does | For |
|---|---|---|
| **Open Scan** | Capture at first fix — pipes and cables exposed, before plasterboard | Builder, on site |
| **Closed Scan** | Capture the finished building, registered to the open scan → X-ray view | Anyone, later |
| **Price Mode** | Scan a job → quantities → itemised quote | Estimating |
| **Condition Mode** | Find damp, leaks, cracked tiles, cracks → pin in 3D → price the fix | Surveys, snagging, audits |

### 2.1 The core idea: scan before the plasterboard

Cameras and LiDAR cannot see through plasterboard. That is physics. **But you do not need
to see through it if you scanned the wall before it was closed up.**

At first fix every pipe, cable, junction box, waste run and stud is exposed. Scan then and
the exact 3D position of everything is recorded permanently. Board it, plaster it, paint
it — the record stands.

```
   OPEN SCAN                  CLOSED SCAN                RESULT
   first fix                  after plastering           X-ray view
   ┌──────────┐               ┌──────────┐               ┌──────────┐
   │ ║ ║  ●   │               │          │               │ ║ ║  ●   │
   │ ║ ║══╪═  │      +        │ finished │      =        │ ║ ║══╪═  │
   │ ║ ║  │   │               │   wall   │               │ ║ ║  │   │
   └──────────┘               └──────────┘               └──────────┘
   measured exactly           what you see today         at real coordinates
```

The two scans register on shared geometry — floor, ceiling, corners, door openings, window
reveals. Once aligned, the app draws the recorded services onto the finished wall. Point
the phone at the plaster, see the pipe.

Why it matters commercially: nobody drills through a pipe again; there is dated geometric
proof of what was installed for building control and warranty; the client gets an X-ray of
their own house at handover; and the next trade in ten years knows what is behind the wall.

Progress-capture platforms (OpenSpace, Buildots) already prove people will do
walkthroughs before drywall — but they document *for the main contractor*. Nobody has
turned it into a **measured services record with an AR X-ray** for the person doing the work.

**Where inference is still needed.** For existing buildings with no open scan, hidden
services stay unknown. There the app infers: fixtures are known endpoints (every tap,
toilet, radiator, socket, switch, vent), routes follow regs safe zones, thermal picks up
hot water and heating runs. Every inferred element is marked and coloured differently.
**A guess is never presented as a survey.**

### 2.2 Price Mode

Quantities come out of the model — no tape measure, no missed items:

| Quantity | From |
|---|---|
| Wall area (plaster, paint, board) | `IfcWall` surfaces minus openings |
| Floor / ceiling area (tiles, screed) | `IfcSlab`, `IfcSpace` |
| Linear metres (pipe, cable, skirting, coving) | Run centerlines, room perimeters |
| Counts (sockets, rads, doors, windows) | Fixture objects |
| Volumes (muck away, concrete, insulation) | Solid geometry |
| Openings (lintels, cutting, making good) | `IfcOpeningElement` |

Then `quantities × rate card + waste % + labour + prelims + margin = quote`.

The **rate card is the user's own**, editable and versioned — a builder knows their prices
better than any book — optionally seeded from **SPON's**/**BCIS** and structured to
**NRM2** so output is professionally recognisable. Takeoff engine: **QTO Buccaneer**
(Python, IFC-native, YAML rules). Out: itemised quote PDF, bill of quantities, materials
list. Re-scan mid-job and variations price themselves against the original.

This is the fastest route to revenue, and it is what the very first reference searched for:
*AI construction takeoff*.

### 2.3 Condition Mode

| Defect | Detected by |
|---|---|
| Damp / moisture | Thermal — damp reads cooler from evaporative cooling — plus pinned meter readings |
| Leaks | Thermal anomalies along pipe runs, cross-checked against the known MEP model |
| Cracked tiles, missing grout | RGB segmentation |
| Wall cracks | Crack-segmentation CNN, width measured against the metric model |
| Mould / staining | RGB colour + texture classification |
| Cold spots / missing insulation | Thermal vs expected U-values |
| Spalling, render, roof defects | Exterior RGB + drone |

Every defect becomes a **3D pin** carrying photo, thermal frame, severity, measured extent
(m² of damp, mm crack width, tile count), likely cause, remedy — **and a price from Price
Mode**. Find it and cost it in one pass. Re-scan later and it diffs: crack widened 2 mm,
damp patch grew 400 mm. That comparison is worth more than any single survey.

Out: pre-purchase survey, snagging list, dilapidations schedule, insurance pack, post-build
audit.

### 2.4 Design

Procedural shape-grammar massing (the CityEngine/CGA approach — footprint + rules → 3D
building), parametric IFC editing via IfcOpenShell, AI layouts constrained to the
*measured* footprint and real structural walls, and feasibility checks against real
services (does the extension cross a soil pipe, breach the boundary, need a lintel).

---

## Part 3 — The platform: what carries over

This is why the building product is far cheaper to build than it looks.

| Existing asset | Reused for | Change needed |
|---|---|---|
| `upload_to_supabase()` + size gating | Delivering point clouds, IFC, splats — all bigger than GLBs | Lift to shared module |
| `progress_update()` staging | "uploading → poses → dense cloud → walls → IFC" | Same pattern, more stages |
| Input validation + clamping | Scan params, quality tiers | Same pattern |
| `OFFLINE=1` + `preload_models.py` | Reconstruction + defect model weights | Extend the manifest |
| `HF_HOME` on network volume | Same | None |
| Dockerfile CUDA build recipe | COLMAP, Open3D, gsplat, PDAL | Same flags, new deps |
| GitHub Actions workflow | `building/` image | Copy, change path filter + tag |
| `free-disk-space` CI step | The building image will be large too | None |
| SHA-tagged images | Forces RunPod to pull fresh | None |
| `pod_setup.sh` | Bootstrapping a scan-worker pod | Adapt the smoke test |
| `test_handler.py` stub pattern | Testing the scan handler with no GPU | Same pattern |
| Error handling + `DEBUG` gating | Same | Lift to shared |
| Reference cache (`slug → stored asset`) | **Property registry** — a scan keyed to an address, reused across visits | Rework as project store |
| Vendoring (`UPSTREAM_COMMIT` + `WORKER_CHANGES.md`) | **How Cloud2BIM comes in** | Same discipline |
| `training/` LoRA scaffolding | Training defect-detection models | New datasets, same shape |

**Genuinely new:** reconstruction (COLMAP/VGGT/splat), the Cloud2BIM wrap, open↔closed
registration, pipe/cable extraction, quantity takeoff, defect detection, the iOS capture
app, the web viewer.

Everything else is already written, already debugged, already tested.

### 3.1 Isolation: the vehicle product must not be touched

The vehicle worker is live and earning. **The building product ships as a completely
separate deployment, sharing nothing at runtime.**

| Resource | Vehicle (existing — do not touch) | Building (new) |
|---|---|---|
| RunPod endpoint | `mj7aiqksmbnkw1` | **new endpoint, own ID** |
| Docker image | `alamk123/ai-mechanic:trellis2-*` | **`alamk123/building-scan:*`** |
| CI workflow | `trellis2-docker-build.yml`, path filter `trellis2/**` | **`building-docker-build.yml`, path filter `building/**`** |
| Network volume | existing (region-locked) | **own volume** — or at minimum own paths |
| Supabase bucket | existing | **own bucket** |
| Output dir | `/runpod-volume/outputs` | `/runpod-volume/building-outputs` |
| GPU pool | 48 GB (L40S/A6000/A100) | sized separately (§4.2) |

The existing CI workflow only triggers on `trellis2/**`, so adding a `building/` directory
cannot rebuild the vehicle image. That isolation holds **as long as nothing edits
`trellis2/`**.

**Which is why the `common/` refactor is cancelled.** An earlier draft of this plan
proposed lifting `upload_to_supabase()` and friends into a shared `common/` module. That
would mean editing `trellis2/handler.py`, which would trigger a rebuild and redeploy of the
**live vehicle image** — exactly the risk we are avoiding. So instead:

> **Copy the patterns into `building/`. Do not extract them.**

A few hundred duplicated lines is a trivial price next to the risk of breaking a working
production worker. If the two products ever need to converge, do it later, deliberately,
when the building worker is itself stable. `trellis2/` stays byte-for-byte untouched.

---

## Part 4 — Architecture

```
repo/
├── handler.py               # TripoSR (legacy)          ─┐
├── trellis/                 # TRELLIS v1 (superseded)    │ UNTOUCHED
├── trellis2/                # TRELLIS.2 — vehicles, live ─┘
└── building/                # NEW — building scanner, fully self-contained
    ├── handler.py           #   job router: reconstruct | structure | price | condition
    ├── Dockerfile
    ├── delivery.py          #   supabase upload + size gating  (copied from trellis2)
    ├── validation.py        #   input parsing, clamping, errors (copied)
    ├── reconstruct.py       #   MapAnything fast path, COLMAP quality path, gsplat
    ├── register.py          #   ICP: open↔closed, room↔room, inside↔outside
    ├── structure.py         #   Cloud2BIM wrap → IFC
    ├── services.py          #   pipe/cable extraction → IfcPipeSegment etc.
    ├── takeoff.py           #   IFC → quantities → priced quote
    ├── condition.py         #   SAM 2 + YOLO defect detection → 3D pins
    ├── vendor/Cloud2BIM/    #   vendored at a pinned commit
    ├── preload_models.py
    ├── pod_setup.sh
    └── test_handler.py
```

Self-contained by design — see §3.1. Nothing in `building/` imports from `trellis2/`.

### 4.1 The 3D engine — what to use, and why

Researched against the 2025–26 state of the art. Two properties decide it: **metric scale**
(a building model without real dimensions is worthless) and **licence** (this is a product
to sell).

| Model | Metric | Licence | Verdict |
|---|---|---|---|
| **MapAnything** (Meta) | **Yes, by design** | **Apache 2.0** code | **Primary.** Universal feed-forward *metric* reconstruction, and a modular interface that runs VGGT / DUSt3R / MASt3R / MUSt3R / Pi3-X as swappable backends. Checkpoint licences vary by training data — check per weight. |
| **VGGT** (Meta/Oxford) | Up to scale | Code commercial-friendly; **original checkpoint non-commercial**, `VGGT-1B-Commercial` available by application | **Secondary backend** via MapAnything. CVPR 2025 Best Paper; hundreds of views in seconds; a May 2026 memory fix gives 2–3× more frames per GPU. |
| **AMB3R** | **Yes** | Not documented — **check before use** | **Evaluate for the accuracy path.** CVPR 2026 Highlight, "metric-scale with backend", ships VO/SLAM and SfM modes. Newest and likely most accurate. |
| **MASt3R / DUSt3R** (Naver) | No | **Non-commercial** | Avoid as a dependency. Reachable through MapAnything for testing only. |
| **COLMAP** | With reference | **BSD** | **Quality path.** The accuracy benchmark; slow. |
| **gsplat / Nerfstudio** | Follows input | **Apache 2.0** | **Photoreal twin.** Not a measurement source. |

**The decision: MapAnything as the primary engine, COLMAP as the quality path.**
MapAnything is the only option that is Apache 2.0, metric by design, *and* an abstraction
layer — so if AMB3R proves more accurate, or a better model lands next year, it swaps in
behind the same interface instead of forcing a rewrite. AMB3R gets evaluated in Phase 1 and
promoted if its licence permits.

Worth knowing: on aerial blocks these feed-forward models achieved **completeness gains up
to 50 % over COLMAP**, with VGGT best on efficiency and scalability. Feed-forward wins on
coverage and speed; COLMAP still wins on raw accuracy. Hence both, behind a quality flag.

### 4.2 The machine — GPU sizing

RunPod serverless, 2026 rates:

| GPU | VRAM | ~$/hr serverless | Use |
|---|---|---|---|
| **A6000 / A40** | 48 GB | **$1.22** | **Default.** Best value; matches what the vehicle worker already targets. |
| L40S | 48 GB | ~$0.99 (pod) | Ada; good for the dev pod |
| A100 | 80 GB | $2.72 | Large properties / many frames |
| H100 | 80 GB | $4.55 | Only if throughput demands it |

**Start on 48 GB (A6000/A40).** Feed-forward reconstruction scales VRAM with frame count,
so cap frames per job and tile large properties rather than reaching for an 80 GB card.
Promote to A100 only when a real scan proves it necessary — and keep the pool **separate
from the vehicle endpoint's**.

### 4.3 Open AI tooling — the rest of the pipeline

| Job | Model | Licence |
|---|---|---|
| **Defect segmentation** (cracks, damp, tiles, mould) | **SAM 2** + **YOLOv11 / YOLO-E** two-stage: YOLO locates, SAM 2 segments to pixel level | Apache 2.0 / AGPL — check YOLO variant |
| **Report writing, plan reading, defect classification** | **Qwen3-VL** / **Qwen2.5-VL** (strong on documents, diagrams, object localisation) or **InternVL3** | Apache 2.0 (Qwen) |
| **Background/segmentation** | **BiRefNet** — already proven in `trellis2/` as the non-gated alternative | Public |
| **Point cloud → BIM** | **Cloud2BIM** | MIT |
| **Quantity takeoff** | **QTO Buccaneer** | Open |
| **IFC read/write** | **IfcOpenShell** | LGPL |

The two-stage YOLO→SAM 2 pattern is exactly what the 2026 crack-segmentation literature
converged on, and there is already published work combining **SAM 2 with 3D Gaussian
splatting** for defect segmentation and 3D reconstruction of concrete structures — the same
architecture this plan proposes. Condition Mode is following a proven path, not inventing one.

### 4.4 Training data — what needs training, and what does not

**Most of this pipeline needs no training at all.** That is the single biggest cost saving
available, and it is easy to miss.

| Stage | Trained? | Why |
|---|---|---|
| Reconstruction (MapAnything, VGGT, AMB3R) | **No** | Pretrained foundation models. Zero-shot on scenes they have never seen. Use as-is. |
| Structure (Cloud2BIM) | **No** | Algorithmic — density analysis and morphological ops, not learned. |
| Quantity takeoff | **No** | Geometry and arithmetic. |
| Defect detection | **Yes** — fine-tune | Open datasets exist (below). |
| Service/first-fix recognition | **Yes** — and **no open data exists** | See §4.5. |

So the question is not "how do we train a 3D model" — it is "what do we fine-tune the two
recognition models on".

**Open datasets that are usable today:**

| Dataset | Contents | Use |
|---|---|---|
| **ARKitScenes** (Apple) | 5,047 captures / 1,661 scenes, **captured with Apple LiDAR** | Best match — literally the same capture hardware as the app. Development + validation. |
| **ScanNet++** | 460 scenes: sub-mm laser scanner + 33MP DSLR + **iPhone RGB-D**, 3.7M frames | The accuracy benchmark. Laser ground truth to measure our error against. |
| **Matterport3D** | 90 building-scale scenes, 194,400 RGB-D images | Whole-building scale. |
| **S3DIS** | 271 rooms, 6,000+ m², 215M points, instance-level labels, 13 classes | Semantic segmentation. |
| **BIMNet** | openBIM scan-to-BIM benchmark, IFC annotation, 14 IFC categories | **Directly benchmarks Phase 3** — point cloud → IFC. |
| **SDNET2018** | 56,000+ images, cracks 0.06–25 mm, with shadows/roughness/holes | Crack detection. Free. |
| **CrackForest (CFD)**, **BD3** | Crack and building-defect benchmarks | Cross-domain validation. |
| Yin et al. industrial plant | ibeam, pipe, pump, rbeam, tank | Pipe geometry — **but industrial, and excludes electrical**. |
| **ConSite** | Active construction site point clouds | Closest to a live site. |

### 4.5 The data gap — and why it is the moat

There is **no open dataset of UK domestic first fix**. Nothing covering 15 mm vs 22 mm
copper, plastic push-fit, socket back boxes, consumer units, cable runs in safe zones, stud
spacing, noggins, soil stacks. The MEP datasets that exist are **industrial plant** — big
pipes, pumps, tanks — and the largest one **excludes electrical entirely**.

That gap cuts both ways:

- It is why Condition Mode can lean on open data (cracks are cracks) but **Service Mode
  cannot**.
- It is also **the most defensible thing in this product.** Reconstruction models are
  free to everyone. Cloud2BIM is MIT. Anyone can assemble the same pipeline in a month.
  What nobody can download is a labelled corpus of real first-fix walls — because it only
  exists in the ninety minutes before the plasterboard goes on, and only a builder is
  standing there when it does.

**Strategy:** capture first-fix footage from every job, from day one, before the app can
even process it. Raw video is enough — it can be reprocessed as the pipeline matures. Every
job filmed is a permanent, appreciating asset that a competitor cannot buy.

### 4.6 On YouTube and scraped video

Tempting, and largely a dead end for the 3D work:

- **Legally:** downloading YouTube video without permission breaches its terms, and training
  on scraped copyrighted video is actively litigated. This is a different question from the
  MIT-vs-GPL one — that is a licence choice, this is copyright exposure on a product being sold.
- **Technically:** edited video is poor reconstruction input. Cuts, zooms, jump edits,
  motion blur, overlays, no depth, no camera intrinsics, no metric scale, and rarely the
  slow overlapping sweep of a single wall that reconstruction needs. A first-fix YouTube
  video is entertainment, not a scan.
- **Where it does work:** individual *frames* are reasonable training data for **2D
  recognition** — "that is a socket back box", "that is 22 mm copper". That is
  classification, not reconstruction. The clean route is licensing footage from a few trade
  channels directly rather than scraping.

Verdict: **do not build on scraped video.** Fine-tune defect models on the open datasets
above, and build the first-fix corpus from real jobs.

### 4.7 Stack

**Capture (iOS, Swift):** Apple **RoomPlan** for interiors — LiDAR, returns *parametric*
walls, doors, windows, openings with dimensions, not just a mesh. **ARKit** for depth and
poses. Guided video walk-around plus GPS for exteriors. **FLIR One**/**Seek** clip-on for
thermal. RoomPlan needs a LiDAR iPhone/iPad Pro and caps at ~5 min per session, so capture
is room-by-room and stitched — which doubles as a natural progress UI.

**Reconstruct (GPU worker):** **MapAnything** feed-forward for the fast path (metric by
design, Apache 2.0, swappable backends — see §4.1); **COLMAP** for survey-grade refinement;
**3D Gaussian Splatting** (`gsplat`/Nerfstudio) for the photoreal twin; **Open3D**/**PDAL**
for cloud handling; **ICP** for all registration.

**Structure:** **Cloud2BIM** (density analysis + morphological ops, handles non-orthogonal
geometry) → **IFC** via **IfcOpenShell**. Iterative **RANSAC line segmentation** for floor
plan vectorization.

**Services:** RANSAC cylinder fitting + region growing for pipes; **DeepPipes**-style
learned reconstruction for occluded runs; skeletonize → centerline graph → fit elbows and
tees; thin-structure detection for cables and boxes; plane/line fitting for the **stud map**
(where you can actually screw into — an underrated win). Written as `IfcPipeSegment`,
`IfcDuctSegment`, `IfcCableCarrierSegment` grouped into colour-coded `IfcSystem`s.

**Everything converges on IFC.** One decision, and scan, plan, services, price and defects
share a model instead of five tools that don't talk.

**Surfaces:** iOS capture app with AR X-ray overlay; web app in React + **three.js** with
**web-ifc/IFC.js** for BIM viewing, layer toggles per service, measurement, rate-card
editor, quote builder, defect register; RunPod serverless workers behind both.

**Export:** IFC (BIM), DXF (CAD), PDF (plans, quotes, reports), glTF/GLB (web), USDZ
(on-site AR at 1:1), CSV/Excel (into existing estimating software).

---

## Part 4.8 — Competitive landscape

Every mode in this plan is contested. Researched honestly, because the differentiation is
narrower than the first draft assumed.

**Scan → 3D / floor plan**

| Product | What it does | Threat |
|---|---|---|
| **magicplan** | AR/LiDAR room scan → measured floor plan → **takeoff → cost estimating** | **Highest.** Ships Phases 2–3 today, on phones, cheap. |
| Matterport | 3D tours, Cortex AI, floor plans | Real-estate focused, not trade |
| Polycam | Consumer/prosumer 3D capture, strong exports | Designers, not contractors |
| Canvas (Occipital) | Scan → CAD, as a paid service | Turnaround service, not instant |
| Cupix | Construction digital twins, imports any point cloud | Enterprise |
| Apple RoomPlan | Free, built into iOS | It's our own dependency |

**Progress capture / before drywall**

| Product | What it does | Threat |
|---|---|---|
| **iGUIDE** | Explicitly markets *"see behind the walls"* — captures plumbing, HVAC, framing and wiring before drywall, scanning at each stage to build a 3D record | **Closest to the core idea.** But it is a panoramic photo record for renovation documentation, not a measured MEP model with AR overlay. |
| OpenSpace / Buildots | 360° walkthroughs, AI maps to floor plan, compares to BIM and schedule | Enterprise, main-contractor focused |
| StructionSite / Disperse / Doxel / PlanRadar | Same category | Same |

**Seeing through finished walls — the hardware route**

| Product | What it does | Threat |
|---|---|---|
| **Resolv InSite Pro** | Radar wall imaging, annotate and export scans, builds a "living digital history of hidden structural details" | **Real.** Different technical route to the same outcome. |
| Walabot DIY | ~£100 consumer through-wall radar, ~100 mm depth | Cheap and good enough for "don't drill here" |
| Bosch D-tect / Hilti PS | Professional wall scanners | Established trade tools |

**This category deserves respect: radar works on *existing* buildings with no prior scan** —
the exact case our open/closed approach cannot serve. It is shallow, low-resolution and
gives no model, but it needs nothing captured in advance.

**Takeoff / estimating**

| Product | Price | Threat |
|---|---|---|
| **Togal.AI** | $299/user/month, ~98% on floor plans | 2D plans, not scans |
| **Hover** | $999/yr + per project — photos → measurements | Exterior; strong in roofing/siding |
| magicplan | Scan → takeoff → estimate | **Direct** |
| Kreo / Bluebeam / eTakeoff / Buildxact | Established estimating | Plan-based |

**Condition / defect survey**

| Product | What it does | Threat |
|---|---|---|
| **uSurv homeSurvey** | AI defect detection — damp, mould, cracks — **free on iOS and Android** | **High.** Free undercuts a paid defect feature. |
| Inspekt AI | Façade analysis, thermal, 3D | Commercial buildings |
| Pointivo | AI defect investigation | Enterprise |
| DampApp Pro | UK damp survey software and compliance | UK, established |

### What this means

**No competitor does all four modes on one measured model.** That is real, but it is a
weaker claim than "nobody does this".

The honest gaps:

1. **Price Mode is not open ground.** magicplan already does scan → plan → takeoff →
   estimate on a phone. Shipping a generic version of that competes with an established,
   cheap product. It needs a reason to exist.
2. **Condition Mode faces a free competitor.** uSurv gives away damp/mould/crack detection.
3. **The X-ray has the clearest gap** — but iGUIDE occupies the "record before drywall"
   idea, and radar tools occupy "see inside this wall". What neither does is
   **phone-only capture at first fix producing a measured, classified MEP model that
   overlays in AR on the finished wall.**

### The strategic answer: the modes are one product, not four

The differentiator is not any single mode — it is that **the services model makes the
pricing and condition modes better than a standalone tool can be.**

- magicplan prices what it can see. **This prices what is behind the wall too** — "moving
  that soil stack to fit the new bathroom costs £X" — because the pipe run is in the model.
- uSurv finds a damp patch. **This finds a damp patch and knows there is a pipe joint
  400 mm behind it**, and prices the repair.
- Radar tells you not to drill. **This tells you what the pipe is, where it runs, what it
  serves, and what it costs to move.**

That is defensible in a way that any one mode alone is not — and it rests on the first-fix
data corpus (§4.5), which is the one asset a competitor cannot download.

**Build-order consequence:** Phase 2 (Price Mode) remains the fastest revenue, but it is
**not** the differentiator and should not be marketed as one. The wedge is the X-ray. Treat
early pricing revenue as funding the thing that actually distinguishes the product.

---

## Part 5 — Build order

**Phase 0 — Scaffold, isolated.** Create `building/` with handler, Dockerfile, its own CI
workflow (`building/**` path filter, `building-scan` image tag) and test file, **copying**
the `trellis2/` patterns rather than extracting them (§3.1). Stand up a **new RunPod
endpoint, volume and bucket**. Define the job contract: capture bundle in (video / images /
RoomPlan USDZ + poses + GPS), point cloud + metadata out.
*Ships:* a deployable worker skeleton on its own endpoint that echoes a validated job —
with `trellis2/` provably untouched.

**Phase 1 — Reconstruction.** MapAnything fast path, COLMAP + splat behind a quality flag,
metric scale enforced. Benchmark **AMB3R** against MapAnything on a real property and
promote it if it wins and its licence permits.
*Ships:* walk a property, get a scaled 3D model with a tape measure.

**Phase 2 — Price Mode.** Areas, lengths and counts straight from RoomPlan's parametric
output → rate card → itemised quote PDF. **Does not need the full BIM pipeline** — RoomPlan
already carries wall and floor areas — so it ships early.
*Ships:* scan a room, price the plastering, painting, flooring, tiling. **First thing
anyone pays for.**

**Phase 3 — Structure.** Vendor Cloud2BIM. Point cloud → IFC. Floor plan vectorization.
Inside/outside registration. Export IFC/DXF/PDF.
*Ships:* real measured drawings; Price Mode goes accurate across every trade.

**Phase 4 — Open/Closed X-ray.** Open-scan capture protocol, service extraction,
open↔closed registration, AR overlay, confidence gating.
*Ships:* point the phone at a wall, see the pipes. **The thing nobody else has.**

**Phase 5 — Condition Mode.** Thermal integration, defect models (using the `training/`
scaffolding), 3D defect register, reports, defect→price linkage, re-scan diffing.
*Ships:* damp, leak and snagging surveys with costed remedies.

**Phase 6 — Design.** Parametric extensions, procedural massing, AI layouts, clash checks
against real services.

**Phase 7 — Polish.** Multi-storey stitching, collaboration, client portal, scan history.

---

## Part 6 — Risks

| Risk | Mitigation |
|---|---|
| **Open↔closed registration drift** → X-ray points at the wrong spot → someone drills a pipe | Fiducial markers at first fix; display alignment confidence; suppress the overlay below a threshold; "verify before you cut" on every view. **This is the top risk in the product.** |
| **Scale drift** without LiDAR | Force a scale reference; refuse to export dimensions from an unscaled model |
| **Thin services near the resolution limit** — cable and small-bore pipe | Close-range capture protocol for open scans; learned completion; accept ≥15 mm as the reliable floor and say so |
| **Messy scan → clean walls** is the hard research problem | Cloud2BIM does the heavy lifting; budget real time here |
| **Wrong price on a quote** loses the user money | Rate card is theirs and versioned; every line traceable to the geometry it came from; confidence flags on inferred quantities |
| **Missed defect** in a survey | Decision support, never a certified survey; surface uncertainty; keep raw thermal/RGB attached |
| **CUDA build failures** on new deps | The `trellis2/` Dockerfile lessons apply directly; build on a pod before trusting CI |
| **GPU cost per scan** | Feed-forward fast path; COLMAP + splat only on demand |
| **Unbounded storage** — `trellis2` already notes `/runpod-volume/outputs` grows forever; scans are much larger | Retention policy and pruning job **before** the first real user |
| **Breaking the live vehicle product** | Total deployment isolation (§3.1): own endpoint, image, workflow, volume, bucket. **`trellis2/` is never edited** — patterns are copied, not extracted. |
| **Model licence blocks commercial use** — several leading reconstruction models are non-commercial | MapAnything (Apache 2.0) as the primary engine; verify each *checkpoint* licence separately from the code licence; confirm AMB3R's before promoting it |
| **Liability** — someone builds or cuts on a wrong number | Confidence on every dimension; measured vs inferred always distinguished; verification notice on every export |

---

## Part 7 — Sources

| Component | Source |
|---|---|
| **MapAnything** — metric feed-forward reconstruction (primary engine) | https://github.com/facebookresearch/map-anything |
| **AMB3R** — metric feed-forward + backend (evaluate) | https://github.com/HengyiWang/amb3r |
| **VGGT** — feed-forward backend | https://github.com/facebookresearch/vggt |
| **SAM 2** — defect segmentation | https://github.com/facebookresearch/sam2 |
| **Qwen-VL** — report generation, plan reading | https://github.com/QwenLM/Qwen3-VL |
| Cloud2BIM — point cloud → IFC | https://github.com/VaclavNezerka/Cloud2BIM |
| QTO Buccaneer — IFC quantity takeoff | https://github.com/simondilhas/qto_buccaneer |
| OpenConstructionERP — estimating / BOQ | https://community.osarch.org/discussion/3437 |
| Random3Dcity — procedural buildings | https://github.com/tudelft3d/Random3Dcity |
| scan_to_bim_pipeline — Open3D reference | https://github.com/mac999/scan_to_bim_pipeline |
| Scan-to-BIM — ML instance segmentation | https://github.com/LTTM/Scan-to-BIM |
| procedural-buildings — CGA shape grammar | https://github.com/santipaprika/procedural-buildings |
| IfcOpenShell | https://ifcopenshell.org |
| Open3D | https://www.open3d.org |
| COLMAP | https://colmap.github.io |
| gsplat / Nerfstudio | https://docs.nerf.studio |
| Apple RoomPlan | https://developer.apple.com/augmented-reality/roomplan |
| web-ifc / IFC.js | https://ifcjs.github.io/info |
| SPON's / BCIS / NRM2 | https://www.bcis.co.uk |

Licences vary (MIT through GPL/AGPL). Worth review before commercial release, not a
blocker on building and testing.

---

## Part 8 — Next step

**Phase 0.** Scaffold `building/` — handler, Dockerfile, its own CI workflow and test file
— copying the `trellis2/` patterns so the new worker inherits the solved problems (RunPod's
output cap, the CUDA build recipe, offline preloading) without a single edit to the live
vehicle worker. Then stand up its own RunPod endpoint, volume and bucket.

That gives a deployable skeleton to build Phase 1 into, on infrastructure that cannot
affect the vehicle product.
