# BuildScan AI — training datasets

Licence-clear datasets for training/fine-tuning the models in `models/vendor/`.
Fetch with [`download.sh`](./download.sh) → lands in `datasets/data/` (git-ignored,
too large / licence-restricted to commit). URLs verified 2026-07-18.

## Licence tiers — read before training a commercial model

- **✅ OPEN** (CC-BY / OGL / ODC-BY): usable commercially with attribution.
- **⚠️ RESEARCH-ONLY / NON-COMMERCIAL**: fine to prototype and benchmark, **not** to
  ship a trained model. The pretrained Mask3D / PTv3 weights inherit this because
  they were trained on ScanNet/S3DIS — that's why those two need retraining on open
  or self-collected data.

## Datasets by BuildScan module

### Defect / damp / crack screening (Area 7) → fine-tune SAM2 / GroundingDINO / Detectron2
| Dataset | Licence | Size | Content |
|---|---|---|---|
| **Özgenel Concrete Cracks** | ✅ CC BY 4.0 | ~241 MB | 40k 227×227 crack / no-crack images (classification) |
| **SDNET2018** | ✅ CC-BY | ~2 GB | 56k+ labelled concrete crack patches (classification) |
| **MBDD2025** | ✅ open (Nature Sci Data) | ~3 GB | 14,471 UAV building-defect images, 5 classes (detection) — auth |
| **CODEBRIM / SODA** | research | — | multi-class concrete defect (reference only) |

> None are UK-interior-specific. Use them to bootstrap, then **collect + label UK
> housing imagery** — this is one of the three must-train gaps.

### Structured digital twin / segmentation (Area 2) → Mask3D / PointTransformerV3
| Dataset | Licence | Size | Content |
|---|---|---|---|
| **ScanNet / ScanNet200** | ⚠️ RESEARCH ONLY | ~1.3 TB | indoor RGB-D scans (sign ToU) |
| **S3DIS** | ⚠️ RESEARCH ONLY | ~6 GB | Stanford indoor 3D, 13 classes |
| **Structured3D** | ⚠️ NON-COMMERCIAL | ~20 GB | synthetic indoor structured 3D |

> All research-licensed → prototype only. A commercial twin needs your own
> annotated building scans (RoomPlan/LiDAR captures labelled with wall/floor/opening/etc.).

### Image → 3D concept visualisation (Area 3) → TRELLIS / TripoSR / InstantMesh
| Dataset | Licence | Size | Content |
|---|---|---|---|
| **Objaverse (1.0 / XL)** | ✅ ODC-BY | large | 800k+ 3D objects for fine-tuning (`pip install objaverse`) |

### UK property valuation / AVM (Area 8) → gradient boosting (XGBoost/LightGBM)
| Dataset | Licence | Size | Content |
|---|---|---|---|
| **HM Land Registry Price Paid** | ✅ OGL | ~150 MB/yr, ~5 GB all | every England/Wales sale since 1995 (target variable) |
| **EPC register** | ✅ OGL-style | ~2 GB | energy rating, floor area, property attributes — register once |
| **OS OpenData (Boundary/Code-Point)** | ✅ OGL | varies | geocoding, UPRN linkage |
| **Planning data** | ✅ OGL | varies | planning.data.gov.uk |
| **Environment Agency flood risk** | ✅ OGL | varies | flood/environmental adjustment features |

> The AVM is fully buildable from **open** data — Land Registry (price) joined to
> EPC (floor area + attributes) is the classic hedonic feature set.

## Quick start
```bash
./datasets/download.sh                       # list everything, download nothing
./datasets/download.sh landregistry_2023     # ~150MB, real UK sales, open licence
./datasets/download.sh cracks_ozgenel        # 40k crack images to fine-tune a defect model
./datasets/download.sh all                   # every openly-downloadable set (large)
```

## The honest gap
Everything **✅ OPEN** above lets you build the AVM and a *generic* crack screener today.
The parts with **no ready open dataset** — UK-interior damp/thermal/defect detection and
survey-grade dimensional ground truth — require your own data-collection programme
(rough order: a few thousand labelled UK images per defect class to start).
