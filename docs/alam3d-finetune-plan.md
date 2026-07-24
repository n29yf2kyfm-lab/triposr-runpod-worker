# Alam-3D — fine-tuning TRELLIS.2-4B on the car library (task #27)

Goal: our own published weights ("Alam-3D"), specialised for car reconstruction,
served by our existing worker. MIT-licensed upstream permits fine-tune + rename +
redistribution. **No GPU spend happens until each stage's go/no-go is passed.**

## What already exists (all committed)

| Piece | Where |
|---|---|
| Upstream training code (`train.py`, fine-tune configs, `data_toolkit/`) | microsoft/TRELLIS.2 @ **75fbf01** (Dockerfile now pinned to it) |
| Our inference overlay (multi-view conditioning) | `trellis/handler.py`, `trellis/alam3d_multiview.py` |
| Dataset staging (library → toolkit contract) | `pipeline/finetune/prepare_dataset.py` (smoke-tested) |
| Weight swap point | `handler.py:24` `IMAGE_MODEL` → point at `Alamj/alam-3d-*` on HF, rebuild |

## Dataset

- Source: the **approved** curated library (366 GLBs; optionally add recovered
  orphans later after visual QC). `prepare_dataset.py` emits the toolkit contract:
  `raw/<sha256>.glb` + `metadata.csv` + `AlamCars.py` subset shim.
- Then the unchanged upstream steps (CPU-heavy, GPU-light):
  `dump_mesh` → `dump_pbr` → `dual_grid --resolution 256,512,1024` →
  `voxelize_pbr` → `render_cond --num_views 16` → `encode_*_latent`.
- ⚠️ **Licence check before any release**: most assets are CC-BY. Fine-tuning on
  them is defensible; *distributing* the resulting weights may carry attribution
  obligations. Keep weights **private on HF** until this is resolved.
- ⚠️ 366 assets is small for a 4B model: the plan is a **short, low-LR
  domain fine-tune** (adapter/short-schedule), not full training — the risk is
  overfitting and forgetting, which the eval below is designed to catch.

## Fine-tune strategy (smallest thing that can prove value)

1. Fine-tune **shape_slat_flow_model_512 only**, short schedule, low LR.
   Texture models untouched at first (texture was never our complaint — melted
   *geometry* was).
2. If shape improves → extend to the 1024 cascade stage; only then consider tex.

## Eval protocol (decided before training, so no vibes)

Fixed input set, base model vs fine-tuned, same seeds:
- auto.dev 2019 Golf SE (4-view) — the proven clean input
- Tesla Model 3 side photo (single view)
- Ford Kuga listing photos (4-view, unseen make in eval)
Render 4-angle sheets of each; owner eyeballs per the visual-review standard;
`asset_audit.py` gates (proportions/glass/wheels) run on both. Ship only if the
fine-tune wins visibly without degrading the unseen car.

## Staged budget (estimates — firm up on the pod; each stage gates the next)

| Stage | What | Hardware | Est. cost |
|---|---|---|---|
| A | data_toolkit over 366 assets | CPU pod (+small GPU for encode/render) | ~$5–20 |
| B | smoke run: loss goes down, checkpoints load, 1-car overfit sanity | 1× A100 80GB, 4–8 h | ~$15–30 |
| C | short shape fine-tune + eval | 4× A100/H100, 24–48 h | ~$250–900 |
| D | (only if C wins) 1024-cascade extension | larger | costed after C |

Failure at any gate = stop, keep the Meshy pipeline as the production path.
Meshy remains the shipping route regardless — Alam-3D is the strategic bet on
owning the engine, not a blocker for the catalogue.

## Deployment when it wins

Push checkpoint to HF (`Alamj/alam-3d-v0`, **private**), set `IMAGE_MODEL`,
rebuild the pinned Docker image, A/B on the eval set once more from the live
endpoint, then flip.
