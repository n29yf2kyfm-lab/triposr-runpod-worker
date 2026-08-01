# Digital Architect — Build Plan

**Goal:** an app that scans a real place and reconstructs a true 1:1 digital twin of the
building — inside and out — with a measured floor plan and the pipe/duct (MEP) systems,
then lets you design a new build or extension on top of it and export real CAD.

This document is the decided tech stack and build order.

---

## 1. What "1:1" actually means (read this first)

Three honest constraints shape every decision below:

**Accuracy is achievable.** With LiDAR capture, 1–3 cm accuracy on walls, rooms and
openings is realistic. That is good enough for planning permission drawings and for
sizing an extension. Photogrammetry from a normal camera has no inherent scale — it needs
either LiDAR depth, a GPS baseline, or a known reference object in frame — so the app
must force one of those or the model will be a nice-looking wrong size.

**Pipes inside walls cannot be scanned by a camera.** No camera and no LiDAR sees through
plasterboard. This is physics, not a software gap. So the MEP layer splits in two, and the
app must always show which is which:

| | How | Trust |
|---|---|---|
| **Measured MEP** | Visible runs — basement, plant room, riser cupboards, exposed ceilings, under-sink | Real geometry, survey-grade |
| **Inferred MEP** | Hidden runs — reconstructed from fixture positions + routing rules + building regs | An informed guess, labelled as such |

Anything better than inference needs extra hardware (thermal camera, ground-penetrating
radar, acoustic pipe locator). Those are a later add-on, not v1.

**MEP is the hardest part of the whole system.** It is built last, on top of a working
BIM model. Building it first is the way this project stalls.

---

## 2. The pipeline

```
 CAPTURE            RECONSTRUCT           STRUCTURE            SYSTEMS          DESIGN           EXPORT
 iOS LiDAR    ->    point cloud     ->    walls/slabs/   ->    pipes &     ->   extensions  ->   IFC
 + video            + gaussian            openings/            ducts            & new build      DXF
 inside & out       splat                 rooms                (MEP)                             PDF
                                          = IFC/BIM                                              GLB/USDZ
                                          + floor plan
```

Everything converges on **IFC** (Industry Foundation Classes, the open BIM standard).
That single decision is what makes scan → plan → design → MEP → CAD one connected model
instead of five disconnected tools. `IfcOpenShell` is the library that reads and writes it.

---

## 3. The stack

### 3.1 Capture — iOS app (Swift)

| Need | Using |
|---|---|
| Interior rooms | **Apple RoomPlan** — LiDAR, returns *parametric* walls, doors, windows, openings, furniture. Not a mesh — actual labelled building elements. Huge head start. |
| Raw depth + poses | **ARKit** — depth maps, camera poses, world tracking, exported alongside RoomPlan output |
| Exterior shell | Guided video walk-around, ARKit poses + GPS per frame |
| Non-LiDAR devices | Plain video → feed-forward reconstruction (§3.2), with a mandatory scale reference (A4 sheet or a measured door) |

Two RoomPlan limits to design around: it needs a LiDAR device (iPhone/iPad Pro), and a
session caps at ~5 minutes. So the app captures **room by room** and stitches them — which
also gives a natural progress UI ("3 of 7 rooms done").

Output per scan: `USDZ` (parametric room) + point cloud + poses + GPS.

### 3.2 Reconstruct — GPU worker (RunPod)

Reuses this repo's existing serverless worker pattern (`handler.py` + `Dockerfile`) —
that infrastructure carries straight over. New worker directory: `building/`.

| Stage | Using | Why |
|---|---|---|
| Fast poses + dense point map | **VGGT** / **MASt3R** / **MapAnything** (feed-forward transformers) | Seconds, not hours. MapAnything gives metric scale directly. |
| High-accuracy refinement | **COLMAP** | Slower, run when the user wants survey quality |
| Photoreal visual twin | **3D Gaussian Splatting** (`gsplat` / Nerfstudio) | This is what makes it *look* real in the viewer |
| Point cloud handling | **Open3D**, **PDAL**, **CloudCompare** formats (`.e57` / `.xyz` / `.ply`) | Standard interchange |
| Inside ↔ outside alignment | **ICP** registration + GPS + footprint constraint | Fuses interior room scans into the exterior shell — this is what makes it one building, not a pile of rooms |

### 3.3 Structure — the "true building"

| Need | Using |
|---|---|
| Point cloud → walls, slabs, windows, doors, rooms → **IFC** | **Cloud2BIM** (density analysis + morphological ops; handles non-orthogonal geometry, no RANSAC calibration hell) |
| IFC read/write/convert | **IfcOpenShell** |
| Floor plan vectorization | Iterative **RANSAC line segmentation** on the wall slice → closed room polygons → dimensioned 2D plan |
| Room semantics | `IfcSpace` per room, with area, ceiling height, name |
| Georeference | Building footprint + height from open GIS data (**GeoLibre** / OSM / national datasets) |

This is the step that turns a messy scan into an *editable, measurable building*. It is
the core of the product.

### 3.4 Systems — pipes and ducts (MEP)

For **visible** runs:

| Need | Using |
|---|---|
| Extract cylinders from point cloud | **RANSAC cylinder fitting** + region growing (Open3D / PCL / CGAL) |
| Complex/occluded runs | **DeepPipes**-style learned pipe reconstruction; deep completion for gaps |
| Connect into runs | Skeletonization → centerline graph → fit elbows, tees, reducers |
| Classify system type | Diameter + material + color + context → water / waste / gas / HVAC duct / electrical conduit / fire suppression |
| Write to BIM | `IfcPipeSegment`, `IfcDuctSegment`, `IfcCableCarrierSegment`, `IfcPipeFitting`, grouped into `IfcSystem` with the standard color coding |

For **hidden** runs: infer from fixture positions (every toilet, tap, radiator, socket and
vent is a known endpoint), route through wall cavities and floor voids using building-regs
rules, and flag every inferred element with a distinct property and color in the viewer.

The color-coded MEP model is the end state — the thing in the reference image.

### 3.5 Design — the digital architect

| Need | Using |
|---|---|
| Extensions / new massing from footprint | Procedural **shape-grammar** generation — the CityEngine/CGA approach (footprint polygon + rules → detailed 3D building). Open reference: TU Delft **Random3Dcity** |
| Parametric editing | Direct IFC element editing via IfcOpenShell — move a wall, the plan and model update together |
| AI layout generation | Floor plan generation constrained to the *actual* measured footprint and structural walls |
| Clash / feasibility checks | Does the extension hit a drain run, breach a boundary, block a window |

Because the design sits on the measured as-built model, an extension snaps to real walls
at real dimensions — which is the entire point over a generic design tool.

### 3.6 Export

| Format | For |
|---|---|
| **IFC** | BIM — architects, engineers, Revit/ArchiCAD |
| **DXF** | CAD drawings |
| **PDF** | Dimensioned plan sheets for planning applications |
| **glTF/GLB** | Web 3D viewer |
| **USDZ** | iOS AR — walk the design at 1:1 on site |

### 3.7 App surfaces

- **iOS capture app** — Swift, RoomPlan + ARKit, live coverage guidance
- **Web app** — React + **three.js**, with **web-ifc / IFC.js** for BIM viewing, layer toggles
  per MEP system, measurement tools, the plan editor
- **Backend** — RunPod serverless GPU workers (this repo's pattern), object storage for
  scans, job queue, per-scan project database

---

## 4. Build order

Each phase ends with something that works on its own.

**Phase 0 — Foundations**
Scaffold `building/` worker beside the existing `trellis/` and `trellis2/`. Define the job
contract: input = video / image set / RoomPlan USDZ + poses + GPS; output = point cloud +
metadata. Reuse the existing Docker + handler pattern.

**Phase 1 — Reconstruction**
Video or LiDAR capture → registered, metric-scaled point cloud + Gaussian splat.
*Ships:* walk around a house, get a viewable scaled 3D model with a tape-measure tool.

**Phase 2 — Structure (the true building)**
Cloud2BIM → walls, slabs, windows, doors, rooms → IFC. Floor plan vectorization → 2D plan.
Interior-to-exterior registration.
*Ships:* a real dimensioned floor plan and an editable BIM model of an existing house.

**Phase 3 — Export**
IFC / DXF / PDF / GLB / USDZ out.
*Ships:* drawings you can hand to a planner or builder. **This is the first genuinely
sellable product.**

**Phase 4 — Design**
Parametric extensions, procedural massing, AI layouts constrained to the real footprint.
*Ships:* the digital architect.

**Phase 5 — MEP**
Visible pipe/duct extraction first, then inferred hidden routing, then the color-coded
systems viewer.
*Ships:* the full reference-image capability.

**Phase 6 — Polish**
Native capture app refinement, live scan guidance, multi-storey stitching, collaboration.

---

## 5. Risk register

| Risk | Mitigation |
|---|---|
| **Scale drift** without LiDAR | Force a scale reference in capture; refuse to export dimensions from an unscaled model |
| **Messy scan → clean walls** is the hard research problem | Cloud2BIM does the heavy lifting; budget real time here, it is where scan-to-BIM products earn their keep |
| **Hidden pipes are unknowable** from camera data | Split measured vs inferred in the data model from day one; never present a guess as a survey |
| **GPU cost per scan** | Feed-forward models for the fast path, COLMAP + splat only on demand for the quality path |
| **Multi-room drift** across RoomPlan's 5-min sessions | Stitch with ICP against the exterior shell; use the footprint as a global constraint |
| **Liability** — someone builds from a wrong measurement | Confidence values on every dimension; "verify on site before construction" on every export |

---

## 6. Component sources

| Component | Repo / source |
|---|---|
| Cloud2BIM — point cloud → IFC | https://github.com/VaclavNezerka/Cloud2BIM |
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

Licences vary across these (MIT through GPL). Worth a review before commercial release,
but not a blocker on building and testing.

---

## 7. Next step

Build **Phase 0 + Phase 1**: the `building/` RunPod worker that takes a capture and returns
a registered, scaled point cloud — reusing this repo's Docker and handler pattern. That
proves the core loop end to end before investing in structuring, design and MEP.
