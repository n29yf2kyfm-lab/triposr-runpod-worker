# Digital Architect — Build Plan

**Goal:** an app that scans a real building and reconstructs a true 1:1 digital twin —
inside and out — including the pipes and wires behind the walls, the measured floor plan,
a priced job, and a condition audit of what is broken.

Four modes, one model:

| Mode | What it does | Who it's for |
|---|---|---|
| **Open Scan** | Capture at first fix — pipes and cables exposed, before plasterboard | Builder, on site |
| **Closed Scan** | Capture the finished building, aligned to the open scan → see through walls | Anyone, any time |
| **Price Mode** | Scan a job → quantities → priced quote | Estimating a job |
| **Condition Mode** | Find damp, leaks, cracked tiles, defects → pin them in 3D → price the fix | Surveys, snagging, audits |

This document is the decided tech stack and build order.

---

## 1. The core idea: scan before the plasterboard

Cameras and LiDAR cannot see through plasterboard. That is physics. But **you do not need
to see through it if you scanned the wall before it was closed up.**

At first fix, every pipe, cable, junction box, waste run and stud is exposed. Scan then,
and you have the exact 3D position of everything — permanently. Board it, plaster it,
paint it, and the record still stands.

```
   OPEN SCAN                    CLOSED SCAN                   RESULT
   first fix                    after plastering              X-ray view
   ┌──────────┐                 ┌──────────┐                  ┌──────────┐
   │ ║ ║  ●   │                 │          │                  │ ║ ║  ●   │
   │ ║ ║══╪═  │       +         │  finished│        =         │ ║ ║══╪═  │
   │ ║ ║  │   │                 │   wall   │                  │ ║ ║  │   │
   └──────────┘                 └──────────┘                  └──────────┘
   pipes + cables               what you see                  what's behind it
   measured exactly             today                         at real coordinates
```

The two scans register to each other on the shared geometry — floor, ceiling, corners,
door openings, window reveals. Once aligned, the app draws the recorded services onto
the finished wall. Point the phone at the plaster, see the pipe.

**Why this matters commercially:**

- **Nobody drills through a pipe again.** Point the phone at the wall before you cut.
- **Legal record.** Dated, geometric proof of what was installed and where.
- **Handover pack.** Hand the client an X-ray of their own house.
- **Building control / warranty evidence.** Shows the first fix was done correctly.
- **Next trade in ten years** knows exactly what is behind the wall.

This is the feature the whole product is built around. Construction progress-capture
platforms (OpenSpace, Buildots) already prove the workflow — 360° walkthroughs at each
stage, before drywall — but they document *for the main contractor*. Nobody has turned it
into a **measured MEP record with an X-ray view** for the person actually doing the work.

### Where inference is still needed

For **existing buildings** with no open scan, hidden services are still unknown. There the
app falls back to inference: fixtures are known endpoints (every tap, toilet, radiator,
socket, switch and vent), routes follow building-regs safe zones, and thermal imaging
picks up hot water and heating runs. Every inferred element is marked and coloured
differently from measured ones. **A guess never gets presented as a survey.**

---

## 2. Pipeline

```
 CAPTURE          RECONSTRUCT        STRUCTURE          SYSTEMS         OUTPUTS
 open scan   ->   point cloud   ->   walls/slabs/  ->   pipes &    ->   X-ray view
 closed scan      + splat            openings/          cables          floor plans
 thermal          registered         rooms              measured        priced quote
 RGB              to each other      = IFC/BIM          + inferred      defect report
                                                                        IFC/DXF/PDF
```

Everything converges on **IFC** — the open BIM standard. One decision, and the scan, the
plan, the services, the price and the defect list all live in the same model instead of
five tools that don't talk to each other.

---

## 3. The stack

### 3.1 Capture — iOS app (Swift)

| Need | Using |
|---|---|
| Interior rooms | **Apple RoomPlan** — LiDAR, returns *parametric* walls, doors, windows, openings. Not a mesh: labelled building elements with dimensions. |
| Raw depth + poses | **ARKit** — depth maps, camera poses, world tracking |
| Open scan (first fix) | Same hardware, slower pass, higher point density. Studs and services are thin — needs close range and good coverage. |
| Exterior shell | Guided video walk-around, ARKit poses + GPS |
| Thermal (condition mode) | **FLIR One** / **Seek Thermal** clip-on, or standalone FLIR, frames registered to RGB |
| Moisture readings | Manual probe, tap to pin the reading at a 3D location |
| Non-LiDAR devices | Plain video → feed-forward reconstruction, with a mandatory scale reference |

RoomPlan needs a LiDAR iPhone/iPad Pro and caps at ~5 minutes per session, so capture is
**room by room** and stitched — which doubles as a natural progress UI.

### 3.2 Reconstruct — GPU worker (RunPod)

Reuses this repo's existing serverless worker pattern (`handler.py` + `Dockerfile`).
New worker directory: `building/`.

| Stage | Using | Why |
|---|---|---|
| Fast poses + dense point map | **VGGT** / **MASt3R** / **MapAnything** | Seconds not hours; MapAnything gives metric scale directly |
| High-accuracy refinement | **COLMAP** | For survey-grade jobs |
| Photoreal twin | **3D Gaussian Splatting** (`gsplat` / Nerfstudio) | What makes it look real in the viewer |
| Point cloud processing | **Open3D**, **PDAL** (`.e57` / `.xyz` / `.ply`) | Standard interchange |
| **Open↔closed registration** | **ICP** on shared geometry + fiducial markers | The critical step — this is what makes the X-ray work |
| Inside↔outside registration | ICP + GPS + footprint constraint | Makes it one building, not a pile of rooms |

**Registration accuracy is the make-or-break number.** If the open and closed scans align
to 1 cm, the X-ray is trustworthy. If they drift 10 cm, someone drills into a pipe. So:
leave small permanent fiducial markers at first fix (a sticker in each room corner, or
recorded socket-box positions) to anchor the alignment, and always display the alignment
confidence with the overlay.

### 3.3 Structure — the true building

| Need | Using |
|---|---|
| Point cloud → walls, slabs, windows, doors, rooms → **IFC** | **Cloud2BIM** — density analysis + morphological ops, handles non-orthogonal geometry |
| IFC read/write/convert | **IfcOpenShell** |
| Floor plan vectorization | Iterative **RANSAC line segmentation** on the wall slice → closed room polygons → dimensioned plan |
| Room semantics | `IfcSpace` per room with area, ceiling height, name |
| Georeference | Footprint + height from open GIS (OSM / GeoLibre / national data) |

### 3.4 Systems — pipes and cables

From the **open scan** (measured, exact):

| Need | Using |
|---|---|
| Extract pipe/conduit runs | **RANSAC cylinder fitting** + region growing (Open3D / PCL / CGAL) |
| Complex or occluded runs | **DeepPipes**-style learned reconstruction, deep completion for gaps |
| Build connected runs | Skeletonize → centerline graph → fit elbows, tees, reducers |
| Cables and boxes | Thin-structure detection; socket/switch/junction boxes as fixture objects |
| Studs and noggins | Plane + line fitting — **the fixing map: where you can actually screw into** |
| Classify | Diameter, material, colour, context → water / waste / gas / heating / HVAC / electrical / fire |
| Write to BIM | `IfcPipeSegment`, `IfcDuctSegment`, `IfcCableCarrierSegment`, `IfcPipeFitting`, grouped as colour-coded `IfcSystem` |

The stud map is an underrated win — knowing where the timber is matters as much as knowing
where the pipes are.

### 3.5 Price Mode — scan a job, price a job

Quantities come straight out of the model. No tape measure, no scale rule, no missed items.

| Quantity | From |
|---|---|
| Wall area (plaster, paint, board) | `IfcWall` surfaces minus openings |
| Floor / ceiling area (tiles, screed, boards) | `IfcSlab` and `IfcSpace` |
| Linear metres of pipe / cable / skirting / coving | Run centerlines and room perimeters |
| Counts — sockets, switches, rads, doors, windows | Fixture objects |
| Volumes — muck away, concrete, insulation | Solid geometry |
| Openings — lintels, cutting, making good | `IfcOpeningElement` |

Then:

```
  quantities  ×  rate card  +  waste %  +  labour hours  +  prelims  +  margin  =  quote
```

- **Rate card is the user's own**, editable, versioned — a builder knows their own prices
  better than any book. Optionally seeded from published data (**SPON's**, **BCIS**) and
  structured to **NRM2** so the output is professionally recognisable.
- **Quantity takeoff** engine: **QTO Buccaneer** (Python, IFC-native, YAML-defined rules)
  as the base, extended with trade-specific rules.
- Output: itemised quote PDF, bill of quantities, materials order list, labour programme.
- Re-scan mid-job → **variations priced automatically** against the original scan.

This mode is the fastest route to something people pay for, and it's what the very first
reference searched for: *AI construction takeoff*.

### 3.6 Condition Mode — what's broken, and what it costs to fix

| Defect | Detected by |
|---|---|
| **Damp / moisture** | Thermal imaging — damp reads cooler from evaporative cooling — plus pinned moisture-meter readings |
| **Leaks** | Thermal anomalies along pipe runs, cross-checked against the known MEP model |
| **Cracked / broken tiles, missing grout** | RGB segmentation model on close-range imagery |
| **Cracks in walls** | Crack-segmentation CNN, width measured against the metric model |
| **Mould / staining** | RGB colour + texture classification |
| **Cold spots / missing insulation** | Thermal survey against expected U-values |
| **Spalling, render failure, roof defects** | Exterior RGB + drone capture |

Every defect becomes a **3D pin** on the model carrying: photo, thermal frame, severity,
measured extent (m² of damp, mm crack width, count of tiles), likely cause, recommended
remedy — **and a price, from Price Mode.** Find it and cost it in one pass.

Reports out: pre-purchase survey, snagging/handover list, dilapidations schedule,
insurance claim pack, post-build audit.

**Time series.** Re-scan the same property later and the app diffs it: the crack widened
2 mm, the damp patch grew 400 mm. That comparison is worth more than any single survey.

### 3.7 Design — extensions and new build

| Need | Using |
|---|---|
| Extensions from footprint | Procedural **shape-grammar** generation (the CityEngine/CGA approach); open reference **Random3Dcity** |
| Parametric editing | Direct IFC editing via IfcOpenShell — move a wall, plan and model update together |
| AI layouts | Floor plans constrained to the *measured* footprint and real structural walls |
| Feasibility checks | Does it hit a drain run, breach the boundary, block a window, need a lintel |

Because the design sits on the measured as-built — and knows where the services are — an
extension snaps to real walls at real dimensions and warns you before it crosses a soil pipe.

### 3.8 Export

| Format | For |
|---|---|
| **IFC** | BIM — architects, engineers, Revit/ArchiCAD |
| **DXF** | CAD drawings |
| **PDF** | Plan sheets, quotes, survey reports |
| **glTF/GLB** | Web viewer |
| **USDZ** | On-site AR — stand in the room and see the pipes in the wall at 1:1 |
| **CSV / Excel** | Quantities and quotes into existing estimating software |

### 3.9 App surfaces

- **iOS capture app** — Swift, RoomPlan + ARKit, live coverage guidance, AR X-ray overlay
- **Web app** — React + **three.js**, **web-ifc / IFC.js** for BIM viewing, layer toggles
  per service, measurement tools, rate card editor, quote builder, defect register
- **Backend** — RunPod serverless GPU workers (this repo's pattern), object storage,
  job queue, per-property project database with scan history

---

## 4. Build order

Each phase ships something usable on its own.

**Phase 0 — Foundations.** Scaffold `building/` worker beside `trellis/` and `trellis2/`.
Job contract: capture bundle in (video / images / RoomPlan USDZ + poses + GPS), point
cloud + metadata out. Reuse the existing Docker and handler pattern.

**Phase 1 — Reconstruction.** Capture → registered, metric-scaled point cloud + splat.
*Ships:* walk a property, get a scaled 3D model with a tape measure.

**Phase 2 — Price Mode (quick win).** Areas, lengths and counts straight from RoomPlan's
parametric output → rate card → itemised quote PDF. **This does not need the full BIM
pipeline** — RoomPlan already gives wall and floor areas — so it ships early.
*Ships:* scan a room, price the plastering, painting, flooring and tiling. **First thing
people pay for.**

**Phase 3 — Structure.** Cloud2BIM → IFC. Floor plan vectorization → dimensioned plans.
Inside/outside registration. Export IFC/DXF/PDF.
*Ships:* real measured drawings, and Price Mode gets accurate across every trade.

**Phase 4 — Open/Closed scan + X-ray.** The core feature. Open-scan capture, service
extraction, open↔closed registration, AR overlay.
*Ships:* point the phone at a wall, see the pipes. **The thing nobody else has.**

**Phase 5 — Condition Mode.** Thermal integration, defect detection models, 3D defect
register, survey reports, defect→price linkage, re-scan diffing.
*Ships:* damp, leak and snagging surveys with costed remedies.

**Phase 6 — Design.** Parametric extensions, procedural massing, AI layouts, clash checks
against real services.

**Phase 7 — Polish.** Multi-storey stitching, collaboration, client portal, scan history.

---

## 5. Risk register

| Risk | Mitigation |
|---|---|
| **Open↔closed registration drift** → X-ray points at the wrong spot → someone drills a pipe | Fiducial markers at first fix; always show alignment confidence; never display the overlay below a confidence threshold; "verify before you cut" on every view |
| **Scale drift** without LiDAR | Force a scale reference; refuse to export dimensions from an unscaled model |
| **Thin services are hard to reconstruct** — cables and small-bore pipe are near the resolution limit | Close-range capture protocol for open scans; learned completion; accept that ≥15 mm is the reliable floor |
| **Messy scan → clean walls** is the hard research problem | Cloud2BIM does the heavy lifting; budget real time here |
| **Wrong price on a quote** loses the user money | Rate card is theirs and versioned; quantities shown with the geometry they came from so every line is auditable; confidence flags on inferred quantities |
| **False negative on a defect** — missed damp in a survey | Present as decision support, never as a certified survey; surface uncertainty; keep the raw thermal and RGB evidence attached |
| **GPU cost per scan** | Feed-forward for the fast path, COLMAP + splat only on demand |
| **Liability** — someone builds or cuts based on a wrong number | Confidence on every dimension; measured vs inferred always distinguished; explicit verification notice on every export |

---

## 6. Component sources

| Component | Source |
|---|---|
| Cloud2BIM — point cloud → IFC | https://github.com/VaclavNezerka/Cloud2BIM |
| QTO Buccaneer — IFC quantity takeoff | https://github.com/simondilhas/qto_buccaneer |
| OpenConstructionERP — estimating / BOQ | https://community.osarch.org/discussion/3437 |
| Random3Dcity — procedural buildings | https://github.com/tudelft3d/Random3Dcity |
| scan_to_bim_pipeline — Open3D reference | https://github.com/mac999/scan_to_bim_pipeline |
| Scan-to-BIM — ML instance segmentation | https://github.com/LTTM/Scan-to-BIM |
| procedural-buildings — CGA shape grammar | https://github.com/santipaprika/procedural-buildings |
| IfcOpenShell — IFC read/write | https://ifcopenshell.org |
| Open3D — point cloud processing | https://www.open3d.org |
| COLMAP — structure from motion | https://colmap.github.io |
| gsplat / Nerfstudio — Gaussian splatting | https://docs.nerf.studio |
| Apple RoomPlan — LiDAR room capture | https://developer.apple.com/augmented-reality/roomplan |
| web-ifc / IFC.js — browser BIM viewer | https://ifcjs.github.io/info |
| SPON's / BCIS / NRM2 — UK cost data + standards | https://www.bcis.co.uk |

Licences vary (MIT through GPL/AGPL). Worth review before commercial release, not a
blocker on building and testing.

---

## 7. Next step

Build **Phase 0 + Phase 1**: the `building/` RunPod worker that takes a capture bundle and
returns a registered, metric-scaled point cloud, reusing this repo's Docker and handler
pattern. That proves the core loop before investing in the modes above it.
