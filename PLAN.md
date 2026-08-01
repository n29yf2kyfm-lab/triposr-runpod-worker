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

### 3.1 First refactor: extract `common/`

`upload_to_supabase()`, the error handler, input validation and the GLB read/write helpers
are duplicated or about to be. Before adding a third worker, lift them into `common/` with
tests. Small job, compounding payoff — and it stops the building worker re-learning the
RunPod output-cap lesson the hard way.

---

## Part 4 — Architecture

```
repo/
├── common/                  # NEW — shared worker library
│   ├── delivery.py          #   supabase upload + size-gated inline
│   ├── validation.py        #   input parsing, clamping, errors
│   └── progress.py          #   staged progress updates
├── handler.py               # TripoSR (legacy)
├── trellis/                 # TRELLIS v1 (superseded)
├── trellis2/                # TRELLIS.2 — vehicles (current product)
└── building/                # NEW — building scanner
    ├── handler.py           #   job router: reconstruct | structure | price | condition
    ├── Dockerfile
    ├── reconstruct.py       #   VGGT/MASt3R fast path, COLMAP quality path, gsplat
    ├── register.py          #   ICP: open↔closed, room↔room, inside↔outside
    ├── structure.py         #   Cloud2BIM wrap → IFC
    ├── services.py          #   pipe/cable extraction → IfcPipeSegment etc.
    ├── takeoff.py           #   IFC → quantities → priced quote
    ├── condition.py         #   thermal + RGB defect detection → 3D pins
    ├── vendor/Cloud2BIM/    #   vendored at a pinned commit
    ├── preload_models.py
    └── test_handler.py
```

### 4.1 Stack

**Capture (iOS, Swift):** Apple **RoomPlan** for interiors — LiDAR, returns *parametric*
walls, doors, windows, openings with dimensions, not just a mesh. **ARKit** for depth and
poses. Guided video walk-around plus GPS for exteriors. **FLIR One**/**Seek** clip-on for
thermal. RoomPlan needs a LiDAR iPhone/iPad Pro and caps at ~5 min per session, so capture
is room-by-room and stitched — which doubles as a natural progress UI.

**Reconstruct (GPU worker):** **VGGT** / **MASt3R** / **MapAnything** feed-forward for the
fast path (seconds, and MapAnything gives metric scale directly); **COLMAP** for
survey-grade refinement; **3D Gaussian Splatting** (`gsplat`/Nerfstudio) for the photoreal
twin; **Open3D**/**PDAL** for cloud handling; **ICP** for all registration.

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

## Part 5 — Build order

**Phase 0 — Platform prep.** Extract `common/`. Scaffold `building/` with handler,
Dockerfile, CI workflow, test file — copying the `trellis2/` patterns. Define the job
contract: capture bundle in (video / images / RoomPlan USDZ + poses + GPS), point cloud +
metadata out.
*Ships:* a deployable worker skeleton that echoes a validated job.

**Phase 1 — Reconstruction.** Feed-forward path first, COLMAP + splat behind a quality
flag. Metric scale enforced.
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
| **Liability** — someone builds or cuts on a wrong number | Confidence on every dimension; measured vs inferred always distinguished; verification notice on every export |

---

## Part 7 — Sources

| Component | Source |
|---|---|
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

**Phase 0.** Extract `common/` from `trellis2/handler.py`, then scaffold `building/` with
its handler, Dockerfile, CI workflow and test file following the `trellis2/` patterns. That
gives a deployable worker skeleton to build Phase 1 into — and pays back immediately by
stopping the new worker from re-learning the RunPod output-cap and CUDA-build lessons the
hard way.
