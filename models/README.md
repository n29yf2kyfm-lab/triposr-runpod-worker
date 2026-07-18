# BuildScan AI — open-source model & tooling manifest

The licence-clear open-source building blocks behind BuildScan AI. Run
[`clone_models.sh`](./clone_models.sh) to fetch them into `models/vendor/`
(git-ignored). Pinned commits are in [`versions.lock`](./versions.lock).

> **What you can clone vs. what you can't.** Everything below is free/open source
> and forkable. The **iOS LiDAR capture layer (Apple RoomPlan / ARKit / RealityKit)
> is a proprietary Apple SDK** — there is no source to clone or upgrade. You consume
> it inside a native iOS app (Swift) with an Apple Developer account. It is the one
> hard dependency with no open-source substitute.

## Cloned repos

| Model | Repo | Licence | Role in BuildScan | Commercial-safe? |
|---|---|---|---|---|
| **TRELLIS** | microsoft/TRELLIS | MIT | Image→3D (GLB) for **concept-design visualisation only** — never measurement | ✅ code MIT; ⚠️ 2 CUDA submodules (diffoctreerast, modified Flexicubes) carry own licences — review before shipping |
| **TripoSR** | VAST-AI-Research/TripoSR | MIT | Fast single-image→3D; basis of this repo's RunPod worker | ✅ |
| **Mask3D** | JonasSchult/Mask3D | MIT | 3D instance segmentation: mesh/point-cloud → semantic building elements | ⚠️ code MIT, but released **weights are trained on ScanNet/S3DIS (research-only data)** — retrain on licence-clear data before commercial use |
| **PointTransformerV3** | Pointcept/PointTransformerV3 | MIT | SOTA point-cloud semantic-segmentation backbone (77.6% mIoU ScanNet) | ⚠️ same weights caveat as Mask3D |
| **IfcOpenShell** | IfcOpenShell/IfcOpenShell | LGPL-3.0 | IFC read/write, geometry engine, quantity take-off; `IfcConvert` for IFC→GLB | ✅ safe as a library (LGPL — dynamic linking is fine; don't statically fold into closed source) |

## Defect-screening stack (Area 7) — vendored, all Apache-2.0 (no AGPL trap)

Cloned into `models/vendor/`. These stack into one pipeline: Grounding DINO finds
regions by text prompt → SAM2 segments them → Detectron2 trains the final detector.

| Model | Path | Licence | Role |
|---|---|---|---|
| **SAM2** | `vendor/SAM2/` | Apache-2.0 | Promptable segmentation (crack/damp region masks) |
| **GroundingDINO** | `vendor/GroundingDINO/` | Apache-2.0 | Open-vocabulary detection ("find damp stain", "crack") |
| **Detectron2** | `vendor/Detectron2/` | Apache-2.0 | Detection/segmentation training framework |
| **InstantMesh** | `vendor/InstantMesh/` | Apache-2.0 | Alt image→3D (multiview → mesh), pairs with TRELLIS |

> Deliberately avoided **Ultralytics YOLO (AGPL-3.0)** — it would force you to open-source
> your server or buy a commercial licence. The Apache-2.0 stack above does the same job.

## Not cloned (install as libraries)

| Tool | How | Licence | Role |
|---|---|---|---|
| **Open3D** | `pip install open3d` | MIT | ICP registration + deviation mapping (planned-vs-actual) |
| **Three.js / DRACOLoader** | `npm i three` | MIT | Web 3D viewer + Draco compression |
| **glTF-Pipeline** | `npm i gltf-pipeline` | Apache-2.0 | Draco-compress GLBs for web delivery |
| **PDAL** | system pkg | BSD | Point-cloud processing pipeline |
| **CloudCompare** | system pkg | GPL | Manual deviation-map inspection |

## Detection/segmentation models for defect screening — clone with LICENCE CARE

These are for Functional Area 7 (defect/damp/thermal). **Check the licence before
building a commercial product on them** — one is a real trap:

| Model | Repo | Licence | Note |
|---|---|---|---|
| **SAM2** | facebookresearch/sam2 | Apache-2.0 | ✅ safe; promptable segmentation |
| **Grounding DINO** | IDEA-Research/GroundingDINO | Apache-2.0 | ✅ safe; open-vocabulary detection |
| **Detectron2** | facebookresearch/detectron2 | Apache-2.0 | ✅ safe; detection/segmentation framework |
| **YOLO (Ultralytics)** | ultralytics/ultralytics | **AGPL-3.0** | ⚠️ **copyleft trap** — AGPL requires releasing your source (incl. server-side) or buying a commercial licence. Prefer SAM2/Detectron2, or budget for the Ultralytics Enterprise licence |

## Fine-tuning datasets (licence-clear starting points)

| Dataset | Licence | Content | Limitation |
|---|---|---|---|
| **SDNET2018** | CC-BY-4.0 | 56k+ concrete crack/non-crack images | classification only (no localisation); concrete, not UK interiors |
| **MBDD2025** | open (Nature Sci Data) | 14,471 UAV building-defect images, 5 classes | UAV/exterior, not UK housing interiors |

## Upgrading a model

```bash
# get everything at latest
./models/clone_models.sh

# reproducible checkout of the pinned commits
./models/clone_models.sh --pinned

# upgrade one and re-pin
cd models/vendor/TRELLIS && git pull && git rev-parse HEAD   # paste SHA into versions.lock
```

## The three "must-train / must-collect" gaps (no drop-in model exists)

1. **Survey-grade dimensional correction** — iPad LiDAR is ~1–2 cm off vs a terrestrial
   laser scanner; no model closes this. Solution is calibration + Bluetooth laser
   reference measurement, not a download.
2. **UK-housing defect/damp/thermal detection** — public datasets are concrete/exterior;
   you must collect and label UK interior imagery.
3. **UK AVM (valuation)** — no open model. Build from HM Land Registry Price Paid + EPC
   (both Open Government Licence) with gradient boosting (XGBoost/LightGBM).
