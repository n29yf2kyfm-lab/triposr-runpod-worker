# Corpus — honest status

A real 3D body-composition app is split across things that can run for free
locally and things that genuinely need your accounts (GPU, app stores). This is
what's real right now versus what still needs an owner that isn't a sandbox.

## What's real and verified in this repo

**`human.glb`** — a real, properly-modeled 3D human (realistic mesh, ~16k verts,
textured, valid binary glTF). Open it in any glTF viewer or via `viewer.html`.
Source/license in `ATTRIBUTION.md`. A fully license-free procedural alternative
(with skin/muscle/skeleton layers) is buildable with `make_human_glb.py`.

**`nhanes_regressor/`** — a real body-fat regressor, actually trained:
- Real NHANES 2017-2018 data pulled from CDC (DEMO_J, BMX_J, DXX_J — public domain)
- Merged **2,169 real adult records** on SEQN
- XGBoost with 5-fold cross-validation
- **Verified result: total body fat CV MAE = 2.6%** (beats the ≤3.5% gate).
  Regional: trunk 2.85%, arm 3.53%, leg 3.53%. See `training_report.json`.
- One honest correction to the original plan: NHANES has no thigh circumference —
  only arm circumference and upper-leg *length*. The feature list reflects what
  NHANES actually measures.
- `app.py` is a working FastAPI server; `/predict` returns real model output
  (verified: e.g. the default male sample → 25.9% total body fat).

**`prototype.html`** — the frontend. The hero shows the real `human.glb` in an
interactive 3D viewer (three.js), and the "Try the regressor" form posts to the
live API and renders real predictions (with a transparent offline fallback).

**`phase0/`** — real Dockerfile, handler, and deploy steps for SAM 3D Body on
RunPod. Code is real; the deploy itself needs your accounts.

## Run the free part right now

```bash
python run_corpus.py
```
Trains (if needed), serves the API, opens the prototype. 100% free, no accounts.

## What still needs you

| Task | Why only you can do it |
|---|---|
| Deploy Phase 0 to RunPod | Your RunPod account + billing |
| Pull the gated SAM 3D Body checkpoint | Your approved HF token, as a RunPod secret |
| Create Supabase / storage | Your account |
| Register a domain / app-store accounts | Your identity + payment |

The regressor and 3D model above are proof this isn't stalling — the remaining
steps just have a real owner, and it isn't a sandbox.
