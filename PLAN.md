# Digital Architect — Master Build Spec

Scan a real building. Reconstruct it 1:1, inside and out, including the pipes and cables
behind the walls. Price the job at live local material prices and order the materials.
Audit its condition. Design the extension. Export real CAD.

**Companion document:** [`COMPETITORS.md`](./COMPETITORS.md) — full competitor teardown,
capability matrix and patent intelligence.

---

# Part 1 — The product

## 1.1 Five modes, one model

| Mode | What it does | For |
|---|---|---|
| **Open Scan** | Capture at first fix — pipes and cables exposed, before plasterboard | Builder, on site |
| **Closed Scan** | Capture the finished building, registered to the open scan → X-ray view | Anyone, later |
| **Price Mode** | Scan a job → quantities → itemised quote | Estimating |
| **Supply Mode** | Quantities → live local merchant prices → basket → order | Buying materials |
| **Condition Mode** | Damp, leaks, cracked tiles, cracks → pinned in 3D → priced fix | Surveys, snagging, audits |
| **Design Mode** | Extensions and new build on the measured as-built, with planning checks | Digital architect |

Everything converges on **IFC** — the open BIM standard. One decision, and the scan, plan,
services, price, defects and design share a single model instead of six tools that don't
talk to each other.

## 1.2 The core idea: scan before the plasterboard

Cameras and LiDAR cannot see through plasterboard. That is physics. **But you do not need
to see through it if you scanned the wall before it was closed up.**

At first fix every pipe, cable, junction box, waste run and stud is exposed. Scan then and
the exact position of everything is recorded permanently. Board it, plaster it, paint it —
the record stands.

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
reveals. Once aligned, the app draws the recorded services onto the finished wall.

**Commercially:** nobody drills through a pipe again; there is dated geometric proof of what
was installed, for building control and warranty; the client gets an X-ray of their own
house at handover; and the next trade in ten years knows what is behind the wall.

**Where inference is still needed.** For existing buildings with no open scan, hidden
services stay unknown. There the app infers from fixture endpoints (every tap, toilet,
radiator, socket, switch, vent), regs safe zones, and thermal signatures of hot runs. Every
inferred element is coloured differently. **A guess is never presented as a survey.**

## 1.3 Price Mode

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

Rate card is the user's own, editable and versioned, optionally seeded from **SPON's** or
**BCIS** and structured to **NRM2**. Takeoff engine: **QTO Buccaneer** (Python, IFC-native).
Out: itemised quote PDF, bill of quantities, materials list. Re-scan mid-job and variations
price themselves.

**Required for insurance/restoration work:** Xactimate **ESX** export. magicplan, iGUIDE and
Hover all have it; it is the price of entry.

**Known gap:** we cannot read 2D drawings. Togal.AI does this at ~98% and most jobs arrive
with drawings. This needs adding.

## 1.4 Supply Mode — "Amazon for builders"

```
  scan ─► quantities ─► live local prices ─► basket ─► order ─► delivered
```

The market splits in two and neither half crosses the gap. **Scan-and-estimate tools**
(magicplan, Togal, Hover) end at a number priced off a static list. **Materials
marketplaces** (BuildBuddy, BuyMaterials.com, Materials Market, PriceNailer, Kojo) start
from a builder typing in what they need. The scan already knows the quantities.

**The honest obstacle.** No public API for Travis Perkins, Jewson or Screwfix, and scraping
breaches their terms. Worse, **trade pricing is account-specific and confidential** — trade
beats retail by 15–40% and every builder's number differs. There is no single "price of a
sheet of plasterboard".

Four legitimate routes, in build order:

| Route | How | Notes |
|---|---|---|
| **1. RFQ to merchant network** | Send the basket to local merchants; they quote | **No API needed.** Proven — this is how BuyMaterials.com works |
| **2. Invoice OCR price index** | Users photograph their own delivery notes and invoices → a real local **paid**-price index | **The moat.** Legally clean, compounds with every job |
| **3. Merchant partnerships / affiliate** | Formal integration, referral commission | The revenue mechanism |
| **4. Punchout catalogues (cXML/OCI)** | Standard e-procurement | Large merchants only |

Route 2 matters most: PriceNailer tracks *published* prices from 14 merchants; a corpus of
real *paid* prices is a different and better asset, and nobody can buy it.

**Revenue.** A builder spends tens of thousands a year on materials. A small commission
dwarfs a £40/month subscription. Software wins the customer; materials pay the bills — which
also means the app can be priced aggressively against magicplan without it hurting.

## 1.5 Condition Mode

| Defect | Detected by |
|---|---|
| Damp / moisture | Thermal (damp reads cooler from evaporative cooling) + pinned meter readings |
| Leaks | Thermal anomalies along pipe runs, cross-checked against the services model |
| Cracked tiles, missing grout | RGB segmentation |
| Wall cracks | Crack CNN, width measured against the metric model |
| Mould / staining | RGB colour + texture |
| Cold spots / missing insulation | Thermal vs expected U-values |
| Spalling, render, roof | Exterior RGB + drone |

Every defect becomes a **3D pin** carrying photo, thermal frame, severity, measured extent
(m² of damp, mm crack width, tile count), likely cause, remedy — **and a price from Supply
Mode at real local rates**.

Adopt from uSurv: a **Property Health Score /1000** and urgent-vs-routine severity grading.
Both are good product design.

**Re-scan diffing:** crack widened 2 mm, damp patch grew 400 mm. Worth more than any single
survey.

**Never sell this alone** — uSurv gives photo defect detection away free. Sell it bundled
with 3D location, measured extent, thermal, and services correlation.

## 1.6 Roof Mode — and why you probably don't need a drone

Roofing, fascia and guttering are big-ticket work, so roof geometry matters for pricing. The
cheapest route is also the best one, and it needs no aircraft.

**Three tiers, cheapest first:**

| Tier | Source | Cost | Covers |
|---|---|---|---|
| **1. Open LIDAR** | **EA National LIDAR Programme** | **Free** | **~99% of England**, 1 m resolution, **±15 cm vertical RMSE**, LAZ point cloud or GeoTIFF DSM/DTM, **no account needed** |
| 2. Ground | The exterior walk-around already planned | Free | Eaves, fascia, guttering, verges, lower roof |
| 3. Drone | **OpenDroneMap / WebODM** | Kit + licensing | Detail inspection, complex or steep roofs |

**Tier 1 is the unlock.** 1 m resolution with ±15 cm vertical accuracy is enough for **roof
pitch, plane areas, ridge/hip/valley lines and chimney positions** — enough to price a
re-roof — **from nothing but an address.** No site visit, no aircraft, no CAA paperwork, no
weather window. Fetch the tile, clip to the building footprint, RANSAC the planes, extract
the edges. **No model, no training** — it is open data plus plane fitting.

Note the 25 cm and 50 cm products were withdrawn from the portal; 1 m and 2 m remain.

**Why drone is last, not first.** UK rules from January 2026 require a Flyer ID (free) for
anything over 100 g and an Operator ID (£12.34/yr), with an **A2 CofC** (£70–100) for closer
work. The separation distances **"effectively prevent close façade, roof and
confined-structure surveys"** with legacy aircraft — A2 CofC holders keep **50 m from
uninvolved people**, and a UK2-class drone is needed to work at 30 m or 5 m. On an ordinary
terraced street, 50 m separation is not achievable. Drone stays supported and optional; it
is not the default.

**Competitive consequence.** EagleView and Hover charge per report for aerial roof
measurement — Hover is $999/yr plus per-project fees. **In England the underlying data is
free.** That is a structural cost advantage on every UK roof job, not a feature difference.

## 1.7 Design Mode

Procedural shape-grammar massing (the CityEngine/CGA approach: footprint + rules → 3D
building), parametric IFC editing via IfcOpenShell, AI layouts constrained to the *measured*
footprint and real structural walls.

**Feasibility and compliance — a genuine differentiator.** Because the as-built is measured,
UK **permitted development** rules can be checked automatically. They are precise and
machine-checkable, under the Town and Country Planning (GPD) (England) Order 2015:

- Side extension: max **half the width of the original house**; no two-storey side extensions
- Single-storey rear: **3 m** attached / **4 m** detached; **6 m / 8 m** under the Larger
  Home Extension Scheme
- Two-storey: minimum **2 m** from the boundary
- PD is a legal right, not approval — **breach one condition and the whole thing needs
  planning permission**

"Half the width of the *original* house" requires knowing the original house's actual
dimensions. **We measured them.** Nobody working from a sketch can check this properly.

Plus clash checks against real services: does the extension cross a soil pipe, need a
lintel, block a window.

---

# Part 2 — The platform

## 2.1 What this repo already is

The name says `triposr-runpod-worker`, but it has outgrown it. It is **a platform for
running heavy 3D/AI GPU jobs as RunPod serverless workers**, currently hosting one product
line (vehicle 3D generation) across three generations:

| Worker | Model | State |
|---|---|---|
| `handler.py` (root) | TripoSR | v10.1; its endpoint has been retired |
| `trellis/` | TRELLIS v1 | Superseded |
| `trellis2/` | TRELLIS.2-4B | **Current, ~3,400 lines, production-hardened** |

## 2.2 What `trellis2/` proves — and gives us free

Nearly every non-obvious line exists because a live run failed and the fix was written down:

- **RunPod silently drops large outputs.** Confirmed live: `COMPLETED` with `output=None`
  because the GLB exceeded the response cap. Solved via `upload_to_supabase()` as primary
  delivery, inline base64 only under 4 MB, loud warning when neither works. **Point clouds
  and IFC files are far bigger than GLBs — this would have bitten on day one.**
- **The CUDA build recipe.** Explicit `TORCH_CUDA_ARCH_LIST` (nvcc cannot autodetect on a
  GPU-less runner), `--no-build-isolation` for extensions importing torch, `setuptools>=64`
  upgraded *before* nvdiffrast (stock installed it as an empty package named "UNKNOWN"),
  `MAX_JOBS=4`, prebuilt wheels before source compile, and a refusal to install
  `pillow-simd` because its build lacked WebP. **COLMAP, Open3D, gsplat and PDAL need
  exactly this treatment.**
- **Staged progress** via `progress_update()` — essential for multi-minute scans.
- **Offline model preloading** — `HF_HOME` on network volume, `preload_models.py`,
  `OFFLINE=1` so cache misses fail fast.
- **GPU-free tests** — `test_handler.py` stubs heavy modules; 20 tests run in CI in seconds.
- **Vendoring discipline** — `UPSTREAM_COMMIT` + `WORKER_CHANGES.md`. **Exactly how
  Cloud2BIM should come in.**
- **`pod_setup.sh`** — bare pod to working worker with an end-to-end smoke test.
- **`training/`** — LoRA dataset/caption/training scaffolding, reusable for defect models.
- **Reference cache** (slug → stored asset) — reworks into the **property registry**.

## 2.3 Isolation — the vehicle product must not be touched

| Resource | Vehicle (do not touch) | Building (new) |
|---|---|---|
| RunPod endpoint | `nd0fagqlr5z2ur` (trellis2-v2), `ng8oiz4p2l0xa0` (render-v2) | **new endpoint** |
| Docker image | `alamk123/ai-mechanic:trellis2-*` | **`alamk123/building-scan:*`** |
| CI workflow | filter `trellis2/**` | **filter `building/**`** |
| Network volume | existing (region-locked) | **own volume** |
| Supabase bucket | existing | **own bucket** |
| Output dir | `/runpod-volume/outputs` | `/runpod-volume/building-outputs` |
| GPU pool | 48 GB | sized separately |

The existing workflow only triggers on `trellis2/**`, so a new `building/` directory cannot
rebuild the vehicle image — **as long as nothing edits `trellis2/`**.

**Therefore: copy the patterns into `building/`, do not extract them into a shared module.**
An earlier draft proposed a `common/` refactor; that would edit `trellis2/handler.py` and
redeploy the live vehicle image. A few hundred duplicated lines cost far less than breaking
a working product. **`trellis2/` stays byte-for-byte untouched.**

---

# Part 3 — Technical stack

## 3.1 The 3D engine

Two properties decide it: **metric scale** (a building model without real dimensions is
worthless) and **a licence that permits selling the product**.

| Model | Metric | Licence | Verdict |
|---|---|---|---|
| **MapAnything** (Meta) | **Yes, by design** | **Apache 2.0** code | **Primary.** Modular interface runs VGGT / DUSt3R / MASt3R / Pi3-X as swappable backends |
| **VGGT** | Up to scale | Code commercial-friendly; original checkpoint non-commercial, `VGGT-1B-Commercial` by application | Secondary backend. CVPR 2025 Best Paper; hundreds of views in seconds |
| **AMB3R** | **Yes** | **Undocumented — check** | Evaluate and promote if it wins. CVPR 2026 Highlight, VO/SLAM + SfM modes |
| **MASt3R / DUSt3R** | No | **Non-commercial** | Avoid as a dependency |
| **COLMAP** | With reference | **BSD** | Quality path |
| **gsplat / Nerfstudio** | Follows input | **Apache 2.0** | Photoreal twin, not a measurement source |

**Decision: MapAnything primary, COLMAP as the quality path.** MapAnything is the only
option that is Apache 2.0, metric by design, *and* an abstraction layer — so a better model
swaps in without a rewrite.

On aerial blocks, feed-forward models achieved **up to 50% better completeness than
COLMAP**, with VGGT best on efficiency. Feed-forward wins coverage and speed; COLMAP wins
raw accuracy. Hence both, behind a quality flag.

## 3.2 Full component list

| Job | Component | Licence |
|---|---|---|
| Interior capture | **Apple RoomPlan** — parametric walls/doors/windows | Apple SDK |
| Poses, depth | **ARKit** | Apple SDK |
| Reconstruction (fast) | **MapAnything** | Apache 2.0 |
| Reconstruction (quality) | **COLMAP** | BSD |
| Photoreal twin | **gsplat / Nerfstudio** | Apache 2.0 |
| Point cloud processing | **Open3D**, **PDAL** | MIT / BSD |
| Registration | **ICP** (Open3D) | MIT |
| Point cloud → IFC | **Cloud2BIM** | MIT |
| IFC read/write | **IfcOpenShell** | LGPL |
| Quantity takeoff | **QTO Buccaneer** | Open |
| Defect detection | **YOLOv11/YOLO-E → SAM 2** two-stage | Apache/AGPL — check |
| Reports, plan reading | **Qwen3-VL / Qwen2.5-VL** | Apache 2.0 |
| Segmentation | **BiRefNet** (already proven in `trellis2/`) | Public |
| Procedural massing | CGA-style; ref **Random3Dcity** | MIT |
| DXF export | **ezdxf** | MIT |
| Web BIM viewer | **web-ifc / IFC.js** + **three.js** | MPL / MIT |
| Thermal | FLIR One / Seek clip-on | Hardware |
| Roof (default) | **EA National LIDAR** — open data | Open Government Licence |
| Roof (drone) | **OpenDroneMap / WebODM** | AGPL / MPL |

The two-stage **YOLO → SAM 2** pattern is what the 2026 crack-segmentation literature
converged on, and published work already pairs **SAM 2 with Gaussian splatting** for defect
segmentation and 3D reconstruction of concrete. Condition Mode follows a proven path.

## 3.3 GPU sizing

RunPod serverless, 2026 rates:

| GPU | VRAM | ~$/hr | Use |
|---|---|---|---|
| **A6000 / A40** | 48 GB | **$1.22** | **Default** |
| L40S | 48 GB | ~$0.99 (pod) | Dev pod |
| A100 | 80 GB | $2.72 | Large properties |
| H100 | 80 GB | $4.55 | Only if throughput demands |

Start on 48 GB. Feed-forward reconstruction scales VRAM with frame count — cap frames per
job and tile large properties rather than reaching for 80 GB.

## 3.4 The AR X-ray — the hard engineering truth

Researched, and it constrains the product.

**ARKit relocalization is not exact.** Anchors restored in a later session commonly shift
**a few centimetres or more**. Accuracy depends on the original scan quality, large spaces
amplify pose error into visible drift, and sparse feature points in plain rooms — exactly
what a freshly plastered wall is — make it worse. Relocalization is probabilistic until
ARKit confirms visually.

**A pipe is 15–22 mm. A few centimetres of drift can put the overlay on the wrong side of
it.** So the X-ray must be engineered honestly:

| Mitigation | Why |
|---|---|
| **Physical fiducial markers at first fix** | Printed markers left in room corners give visual anchors far stronger than natural-feature relocalization |
| **ARWorldMap persistence** + Core Location for zone selection | The proven stack for spatial memory across sessions |
| **Dense capture protocol on open scans** | Insufficient point density is a primary relocalization failure cause |
| **Display live alignment confidence** | Never show the overlay below a threshold |
| **"Verify before you cut" on every view** | The overlay is a guide, not a permission |
| **Belt-and-braces** | Recommend a £100 wall scanner for the final check before cutting |

**State this plainly in the product.** An X-ray that claims millimetre precision and
delivers ±30 mm is worse than one that says ±30 mm and means it.

---

# Part 4 — Data strategy

## 4.1 What needs training — and what does not

| Stage | Trained? | Why |
|---|---|---|
| Reconstruction | **No** | Pretrained foundation models, zero-shot |
| Structure (Cloud2BIM) | **No** | Algorithmic, not learned |
| Quantity takeoff | **No** | Geometry and arithmetic |
| Defect detection | **Yes** — fine-tune | Open datasets exist |
| First-fix service recognition | **Yes** — and **no open data exists** | §4.3 |

## 4.2 Usable open datasets

| Dataset | Contents | Use |
|---|---|---|
| **ARKitScenes** | 5,047 captures / 1,661 scenes, **Apple LiDAR** | Same hardware as our app |
| **ScanNet++** | 460 scenes: sub-mm laser + DSLR + iPhone RGB-D, 3.7M frames | **Accuracy ground truth** |
| **Matterport3D** | 90 building-scale scenes | Whole-building scale |
| **S3DIS** | 271 rooms, 215M points, 13 classes | Semantic segmentation |
| **BIMNet** | openBIM scan-to-BIM benchmark, 14 IFC categories | **Benchmarks Phase 3 directly** |
| **SDNET2018** | 56,000+ images, cracks 0.06–25 mm | Crack detection |
| **CrackForest**, **BD3** | Crack/defect benchmarks | Validation |
| Yin et al. industrial plant | ibeam, pipe, pump, tank | Pipe geometry — industrial, **no electrical** |
| **ConSite** | Construction site point clouds | Closest to a live site |

## 4.3 The data gap is the moat

**No open dataset covers UK domestic first fix.** Nothing on 15 mm vs 22 mm copper,
push-fit, back boxes, consumer units, cable in safe zones, stud spacing, noggins. The
existing MEP datasets are **industrial plant**, and the largest **excludes electrical
entirely**.

That gap is the product's defence. Reconstruction models are free to everyone. Cloud2BIM is
MIT. Anyone can assemble this pipeline in a month. **What nobody can download is a labelled
corpus of real first-fix walls** — it exists only in the window before the plasterboard goes
up, and only a builder is standing there.

**Two compounding assets, both un-buyable:**
1. **First-fix walls** — capture from every job, starting now, before the pipeline can even
   process it. Raw video is enough; reprocess later.
2. **Real paid local material prices** — from invoice OCR, from day one of Supply Mode.

## 4.4 Scraped video is out

- **Legally:** downloading YouTube video breaches its terms; training on scraped copyrighted
  video is actively litigated. Different exposure from a licence choice.
- **Technically:** edited video is poor reconstruction input — cuts, zooms, motion blur, no
  depth, no intrinsics, no metric scale, and rarely the slow overlapping sweep of one wall
  that reconstruction needs.
- **Where frames do help:** 2D recognition training ("that's a back box", "that's 22 mm
  copper"). Licence footage from trade channels directly rather than scraping.

---

# Part 5 — Competitive position

Full teardown in [`COMPETITORS.md`](./COMPETITORS.md). Summary:

**Every mode is contested.** magicplan already ships scan → plan → takeoff → estimate.
iGUIDE explicitly markets *"see behind the walls"* renovation documentation. uSurv gives
away AI damp/mould/crack detection **free**. Through-wall radar (Resolv, Walabot, Bosch,
Hilti) reaches the X-ray outcome by another route — and **works on existing buildings with
no prior scan**, which we cannot serve at all.

**The defensible claim is narrower than "nobody does this":** no competitor combines the
modes on one measured model, and that combination makes each mode better than its standalone
rival.

- magicplan prices what it can see. **We price what's behind the wall** — "moving that soil
  stack costs £X".
- uSurv finds a damp patch. **We find it and know there's a pipe joint 400 mm behind it.**
- Radar says don't drill. **We say what the pipe is, where it runs, what it serves, and what
  it costs to move.**

**Consequence: the X-ray is the wedge, not Price Mode.** Early pricing revenue funds the
thing that actually distinguishes the product.

**Their advantages, honestly:** iGUIDE's 0.5% / 1 cm@40 m accuracy from dedicated hardware;
Matterport's 33-billion-sq-ft corpus; Hover's 50+ integrations; uSurv being free; Togal
reading 2D drawings at 98% (we can't read drawings at all); radar serving existing
buildings. **And all of them ship today. We ship nothing yet.**

---

# Part 6 — Patents

Reading patents is legal and intended — disclosure is the bargain. Implementing a live claim
is not. Full detail in `COMPETITORS.md` §5.

**Hover US20160224696A1 solves our metric-scale problem** — detect doors/windows/bricks,
measure width:height ratios in pixels, match a standards library within tolerance, derive
scale, weighted averaging across elements.

**The UK adaptation is better than theirs:**

| Reference | Dimension | Why |
|---|---|---|
| **Brick coursing** | **4 courses = 300 mm exactly** | Best scale reference in Britain — national standard, on nearly every house, and **measuring across 20 courses averages out error** |
| Socket height | **450 mm** (Part M) | **Regs-mandated interior anchor** — their exterior-focused patent doesn't cover it |
| Switch height | **1200 mm** (Part M) | Same |
| Internal door | 762×1981 mm | Near-universal |
| Plasterboard | 2400×1200 mm | On every first-fix site |

**Hover US11721066B2 is Supply Mode, patented, for exteriors** — recognise architectural
elements, extract dimensions, match to manufacturer product databases, convert to quantities
(1,000 sq ft roof → shingle bundles), auto-populate purchase orders. Ours differs: interior
and first-fix services, UK merchants, **live RFQ pricing rather than a manufacturer
catalogue**, and a real paid-price index. Still a design-around to raise with an attorney.

**Design-around position:** LiDAR is the primary scale source and touches none of these
claims; the known-object method is the non-LiDAR fallback only, built on UK standards and
multi-course averaging; photogrammetric scaling from known objects has decades of prior art.
**Get an attorney to clear it before commercial launch.** Filed ~2015, runs to ~2035, and
patents are jurisdictional — a US grant doesn't bind UK operation without UK/EP equivalents.

**Matterport's 64 patents** cluster on real-estate tour presentation — outside our
territory. **Planitar holds only 3**; their moat is hardware, not IP. Note **REA Group took
a majority stake in Planitar in October 2025**, which likely pulls iGUIDE further toward
real estate and away from trade.

---

# Part 7 — Architecture

```
repo/
├── handler.py               # TripoSR (legacy)          ─┐
├── trellis/                 # TRELLIS v1 (superseded)    │ UNTOUCHED
├── trellis2/                # TRELLIS.2 — vehicles, live ─┘
└── building/                # the building scanner, self-contained
    ├── handler.py           #   job router across all modes
    ├── validation.py        #   input parsing, clamping, errors   (copied)
    ├── delivery.py          #   storage upload + size gating      (copied)
    ├── progress.py          #   staged progress for long jobs
    │
    ├── osgb.py              # ✅ WGS84 ↔ British National Grid
    ├── roof.py              # ✅ Roof Mode — open LIDAR → takeoff
    ├── roof_geometry.py     # ✅ plane fitting, pitch, edges, quantities
    ├── solar.py             # ✅ Google Solar cross-check
    ├── scale.py             # ✅ metric scale, or refuse
    ├── reconstruct.py       # ⚠  frame selection ✅, model call UNTESTED
    ├── takeoff.py           # ✅ Price Mode — quantities → quote
    ├── prices.py            # ✅ three tiers, ranked sources, forecasting
    ├── regs.py              # ✅ UK Building Regs, uncertainty-aware
    ├── safety.py            # ✅ scaffolding, work at height, CDM
    ├── terrain.py           # ✅ levels, earthworks, drainage, foundations
    │
    ├── valuation.py         # ○ Land Registry + EPC
    ├── supply.py            # ✅ price-list import, multi-supplier, basket
    ├── structure.py         # ○ Cloud2BIM → IFC
    ├── services.py          # ○ pipe/cable extraction → the X-ray
    ├── condition.py         # ○ YOLO + SAM 2 defects
    ├── design.py            # ○ procedural massing + planning checks
    ├── vendor/Cloud2BIM/    # ○ vendored at a pinned commit
    └── web/index.html       # ✅ roof report UI

    ✅ built and tested   ⚠ written, unproven   ○ not started
```

Nothing in `building/` imports from `trellis2/`.

**Surfaces:** iOS capture app (Swift, RoomPlan + ARKit, AR X-ray overlay); web app (React +
three.js + web-ifc, layer toggles per service, measurement, rate card editor, quote builder,
defect register); RunPod serverless workers behind both.

**Exports:** IFC (BIM), DXF/DWG (CAD), PDF (plans, quotes, reports), glTF/GLB (web), USDZ
(on-site AR at 1:1), CSV/Excel, **ESX** (Xactimate).

---

# Part 8 — Build order

**Status at this commit: 611 tests passing, `trellis2/` untouched throughout.**

| | Phase | State |
|---|---|---|
| ✅ | 0 — scaffold, isolated | done |
| ✅ | 1b — Roof Mode | **works on real addresses** |
| ✅ | 1 — metric scale | done |
| ⚠ | 1 — reconstruction | orchestration done; **model call never run** |
| ✅ | 2 — Price Mode | done |
| ✅ | — material prices, 3 tiers, forecasting | done |
| ✅ | — Building Regs engine | done |
| ✅ | — safety, scaffolding, CDM | done |
| ✅ | — site levels, earthworks, foundations | done |
| ○ | — valuation (Land Registry + EPC) | researched, free |
| ✅ | 2b — Supply Mode: price-list import, multi-supplier, basket | done |
| ○ | 2b — Supply Mode: merchant RFQ round-trip | next |
| ○ | 3 — Structure → IFC | |
| ○ | 4 — **the X-ray** | the wedge |
| ○ | 5 — Condition Mode | |
| ○ | 6 — Design Mode | |
| ○ | 7 — 2D drawing takeoff, Xactimate ESX | the two competitor gaps |

**The one real blocker:** the reconstruction path needs a GPU to be proven.
CI only builds the image on `main`, so that needs either a merge or a pod build.
Every bug found so far in the roof path came from running against real data —
the reconstruction path has not had that yet, and should be expected to yield
the same crop.


**Phase 0 — Scaffold, isolated.** `building/` with handler, Dockerfile, own CI workflow
(`building/**` filter, `building-scan` tag), test file — **copying** `trellis2/` patterns.
New RunPod endpoint, volume, bucket. Job contract defined.
*Ships:* deployable skeleton on its own endpoint, `trellis2/` provably untouched.

**Phase 1 — Reconstruction.** MapAnything fast path, COLMAP + splat behind a quality flag,
metric scale enforced (LiDAR primary, UK anchors fallback). Benchmark AMB3R and promote if
it wins. **Validate accuracy against ScanNet++ laser ground truth and publish the number** —
iGUIDE claims 0.5% / 1 cm@40 m; we need our own figure before any 1:1 claim.
*Ships:* walk a property, get a scaled 3D model with a tape measure.

**Phase 1b — Roof Mode.** Fetch EA open LIDAR by address, clip to footprint, RANSAC roof
planes, extract ridge/hip/valley, output pitch and areas. OpenDroneMap path for optional
drone capture. **No model and no training — open data plus plane fitting.**
*Ships:* type an address, get a measured roof. **Free where EagleView and Hover charge per
report.**

**Phase 2 — Price Mode.** Areas, lengths and counts from RoomPlan's parametric output → rate
card → itemised quote PDF. **Does not need the full BIM pipeline.**
*Ships:* scan a room, price the plastering, painting, flooring, tiling. **First revenue.**

**Phase 2b — Supply Mode.** Quantities → basket → **RFQ to local merchants** (no APIs
needed) → order. Ship **invoice OCR price index** alongside from day one so the corpus
starts building.
*Ships:* real local prices, one-tap ordering. **This is what makes Price Mode more than a
magicplan clone — and opens materials commission.**

**Phase 3 — Structure.** Vendor Cloud2BIM. Point cloud → IFC. Floor plan vectorization.
Inside/outside registration. Export IFC/DXF/PDF/ESX.
*Ships:* real measured drawings; Price Mode goes accurate across every trade.

**Phase 4 — Open/Closed X-ray.** Open-scan capture protocol, fiducial markers, service
extraction, ARWorldMap persistence, confidence gating, AR overlay.
*Ships:* point the phone at a wall, see the pipes. **The wedge.**

**Phase 5 — Condition Mode.** Thermal, YOLO+SAM 2 defect models, 3D defect register, health
score, reports, defect→price linkage, re-scan diffing.
*Ships:* damp, leak and snagging surveys with costed remedies.

**Phase 6 — Design Mode.** Parametric extensions, procedural massing, **permitted-development
auto-check**, clash detection against real services.

**Phase 7 — Gap closing.** 2D drawing takeoff (the Togal capability), integrations,
multi-storey stitching, collaboration, client portal.

---

# Part 9 — Risks

| Risk | Mitigation |
|---|---|
| **AR relocalization drift (few cm)** → X-ray points at the wrong spot → someone drills a pipe | **Top risk.** Fiducial markers at first fix, ARWorldMap persistence, dense capture, live confidence display, suppress below threshold, "verify before you cut", recommend a wall scanner for the final check |
| **Scale drift** without LiDAR | UK brick coursing / socket-height anchors; refuse to export dimensions from an unscaled model |
| **Accuracy below iGUIDE's 0.5%** | Validate against ScanNet++ early; publish the real number; don't over-claim |
| **Thin services near resolution limit** — cable, small-bore pipe | Close-range open-scan protocol; learned completion; ≥15 mm is the honest floor |
| **Messy scan → clean walls** | Cloud2BIM does the heavy lifting; budget real time |
| **Wrong price on a quote** | User's own versioned rate card; every line traceable to its geometry; confidence flags |
| **Missed defect** | Decision support, never a certified survey; keep raw evidence attached |
| **Breaking the live vehicle product** | Total isolation; `trellis2/` never edited |
| **Model/patent licence blocks commercial use** | MapAnything (Apache 2.0); verify each *checkpoint* separately; attorney review of the scale fallback |
| **CUDA build failures** | `trellis2/` Dockerfile lessons apply; build on a pod before trusting CI |
| **Unbounded storage** — `trellis2` already notes outputs grow forever; scans are far larger | Retention policy **before** the first real user |
| **Liability** — someone builds or cuts on a wrong number | Confidence on every dimension; measured vs inferred always distinguished; verification notice on every export |

---

# Part 10 — Open decisions

1. **Do you have a LiDAR iPhone/iPad Pro?** Changes whether LiDAR or the UK-anchor fallback
   is the primary capture path in Phase 1.
2. **Tool for your own jobs, or product to sell?** Changes whether to invest early in
   multi-tenant, billing, and legal review.
3. **Attorney review of the scale fallback and Supply Mode** before commercial launch.

---

# Part 11 — Sources

| Component | Source |
|---|---|
| MapAnything | https://github.com/facebookresearch/map-anything |
| AMB3R | https://github.com/HengyiWang/amb3r |
| VGGT | https://github.com/facebookresearch/vggt |
| SAM 2 | https://github.com/facebookresearch/sam2 |
| Qwen-VL | https://github.com/QwenLM/Qwen3-VL |
| Cloud2BIM | https://github.com/VaclavNezerka/Cloud2BIM |
| QTO Buccaneer | https://github.com/simondilhas/qto_buccaneer |
| Random3Dcity | https://github.com/tudelft3d/Random3Dcity |
| scan_to_bim_pipeline | https://github.com/mac999/scan_to_bim_pipeline |
| BIMNet | https://github.com/LydJason/BIMNet |
| IfcOpenShell | https://ifcopenshell.org |
| Open3D | https://www.open3d.org |
| COLMAP | https://colmap.github.io |
| gsplat / Nerfstudio | https://docs.nerf.studio |
| Apple RoomPlan | https://developer.apple.com/augmented-reality/roomplan |
| EA National LIDAR (free, ~99% of England) | https://environment.data.gov.uk/survey |
| OpenDroneMap / WebODM | https://webodm.org |
| UK drone rules (CAA) | https://register-drones.caa.co.uk |
| ARKitScenes | https://github.com/apple/ARKitScenes |
| web-ifc / IFC.js | https://ifcjs.github.io/info |
| SPON's / BCIS / NRM2 | https://www.bcis.co.uk |
| Planning Portal (PD rules) | https://www.planningportal.co.uk |
| Hover scaling patent | https://patents.google.com/patent/US20160224696 |
| Hover materials patent | https://patents.google.com/patent/US11721066 |

Licences vary (MIT through AGPL). Review before commercial release; not a blocker on
building and testing.

---

# Part 12 — Next step

**Phase 0.** Scaffold `building/` — handler, Dockerfile, own CI workflow, tests — copying
the `trellis2/` patterns so the new worker inherits the solved problems without a single
edit to the live vehicle worker. Then stand up its own RunPod endpoint, volume and bucket.

**In parallel, and time-critical: film first fix.** Open-scan data is perishable — once the
plasterboard is on, it is gone. Raw phone video of any job at first fix is enough, and it is
the one asset a competitor cannot buy.
