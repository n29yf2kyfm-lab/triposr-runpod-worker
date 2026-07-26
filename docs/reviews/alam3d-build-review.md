# Alam-3D build — resume review & API/endpoint inventory

**Date:** 2026-07-26 · **Branch:** `claude/lovable-connection-review-tefew6`
**Purpose:** pick the Alam-3D fine-tune back up — establish exactly where it
stands, inventory every API/endpoint/repo it touches, and lay out a go/no-go
resume plan. Sources: `docs/alam3d-finetune-plan.md`,
`docs/alam3d-forensic-report.md`, `pipeline/finetune/*`, `trellis/*`, and a live
Hugging Face query (authenticated as **Alamj**). No RunPod/Supabase queries were
possible — see "Credentials" below.

---

## TL;DR — where it actually is

- **Stage A (data toolkit): ✅ complete.** The full AlamCars training set lives
  on RunPod network volume **`yiv4apiad7`** (`alam3d-data`, EU-RO-1, 250 GB):
  366 raw GLBs, mesh/pbr dumps, dual-grid O-Voxel 256/512/1024, 16-view cond
  renders, shape + ss latents. **Known gap:** `voxelize_pbr` produced no records
  (`enc_pbr KeyError 'pbr_voxelized'`) → **texture-model training is blocked**;
  shape-first is unblocked (the plan defers texture anyway).
- **Stage B (smoke train): built and run.** `stage_b_pod.sh` exists; Stage C's
  bootstrap even exports the Stage B smoke loss curve at boot, implying it ran.
- **Stage C (real shape fine-tune): built, bootstrapped, eval iterated to v3 —
  but outcome unrecorded.** `stage_c_pod.sh` fine-tunes
  `shape_slat_flow_model_512` (6000 steps, LR 1e-5, bs4 via grad-accum on a
  single A100 80 GB), initialised from the released
  `microsoft/TRELLIS.2-4B/ckpts/slat_flow_img2shape_dit_1_3B_512_bf16`.
  `stage_c_eval_pod.sh` generates 6 GLBs (base vs alam3d × golf/model3/escape)
  and uploads them to `car-meshes/eval/<RUNID>/`.
- **🚩 The weights were never published.** `Alamj/alam-3d-v0` exists (private,
  created 24 Jul) but is **empty — only `.gitattributes`.** Any Stage C
  checkpoint lives on volume `yiv4apiad7` at `/workspace/alam3d_stage_c/ckpts/`,
  not on HF.
- **🚩 Production still runs the base model.** `trellis/handler.py:62`
  `IMAGE_MODEL = "microsoft/TRELLIS.2-4B"`. Nothing has flipped to Alam-3D.
- **🚩 The eval verdict is not in the repo.** Whether the fine-tune beat base on
  the fixed set is unknown from here — it's in the pod logs / the eval GLBs in
  `car-meshes/eval/`, both behind credentials this sandbox doesn't have.

**Net:** the pipeline is fully built and was exercised through Stage C + eval;
the build is parked at the **Stage C go/no-go gate** with the decision unmade
and nothing deployed.

---

## API & endpoint inventory

### 1. RunPod

**Serverless endpoints** — `POST https://api.runpod.ai/v2/{ENDPOINT_ID}/run`,
poll `.../status/{jobId}`; header `Authorization: Bearer $RUNPOD_API_KEY`.

| Purpose | Endpoint ID | Image | Notes |
|---|---|---|---|
| **Render** (hero studio) | **`ng8oiz4p2l0xa0`** (name `render-v2`; `RUNPOD_RENDER_ENDPOINT`, default in `platform/pipeline/config.py:32`) | `alamk123/ai-mechanic:render-latest` | RTX 4090, workersMax=2, idle 15s, execTimeout 600s, no network volume |
| **TRELLIS.2 generation** | **`nd0fagqlr5z2ur`** (name `trellis2-v2`) | `alamk123/ai-mechanic:trellis2-latest` | RTX A5000, network volume `kyh32l0npu` (hunyuan3d-models, EU-SE-1), idle 30s, execTimeout 1800s. ⚠️ **`workersMax=0` — currently disabled; will not serve until raised** |
| **Grounded-SAM** (part seg) | env **`GSAM_EP`** (no live endpoint found on the account) | `alamk123/ai-mechanic:gsam-latest` | optional; `segment/masks_and_vote.py:30` |
| Hunyuan3D 2.1 | — | — | **endpoints DELETED** (UK-excluded licence, retired) |
| TRELLIS v1 (legacy) | — | `:trellis-latest` / `:trellis-v1` | superseded by v2 |

**Live account state (2026-07-26, via `rest.runpod.io/v1`):** only the two
endpoints above exist. **All pods are EXITED — nothing is billing.** The
`alam3d-stage-a` pod (`r0uucvv8f3wkf3`, vol `yiv4apiad7`) is retained but stopped;
Stage B/C/eval pods are gone (the launcher auto-deletes on terminal state), so
the Stage C outcome is not recoverable from the pod list — only from the volume.
Network volumes: **`yiv4apiad7`** `alam3d-data` 250 GB EU-RO-1 (the training
set + any checkpoint); `kyh32l0npu` hunyuan3d-models 200 GB EU-SE-1; three
50 GB scratch volumes.

- **Account cap: 10 serverless workers across ALL endpoints** (CLAUDE.md).
- **List endpoints live:** `GET https://rest.runpod.io/v1/endpoints`
  (Bearer key). Can't run here — no key in env.

**Pods (fine-tune) REST API** — `https://rest.runpod.io/v1/pods`
(`POST` create, `DELETE {id}`); Bearer `RUNPOD_API_KEY`. Driver:
`pipeline/finetune/launch_pod.py`.
- Pod status is served from inside the pod at
  `https://{podId}-8000.proxy.runpod.net/status.json` (+ `/stage_b.log`).
  ⚠️ Poll with **curl**, not urllib — the sandbox egress proxy 403s urllib for
  `*.proxy.runpod.net` (`launch_pod.py:105`).
- **Network volume `yiv4apiad7`** (`alam3d-data`, EU-RO-1, 250 GB) mounted at
  `/workspace`; holds the training set **and** any Stage C checkpoints.
- GPU tiers (`launch_pod.py:24`): `80gb` (A100/H100 — required, 24 GB OOMs the
  1.3B trainer) for training; `render` (A5000/3090/A6000/L40S/4090) for
  encode/render backfill.
- Bootstrap scripts are curled from Supabase, not baked into the image:
  `.../car-renders/finetune/<script>.sh`.

### 2. Hugging Face  (queried live as **Alamj**)

| Repo | Type | State | Role |
|---|---|---|---|
| [`microsoft/TRELLIS.2-4B`](https://hf.co/microsoft/TRELLIS.2-4B) | model | public, MIT | base weights; init from `ckpts/slat_flow_img2shape_dit_1_3B_512_bf16` |
| [`Alamj/alam-3d-v0`](https://hf.co/Alamj/alam-3d-v0) | model | **private, EMPTY (only `.gitattributes`)** | intended target for the fine-tuned weights — **nothing pushed yet** |
| [`ZhengPeng7/BiRefNet`](https://hf.co/ZhengPeng7/BiRefNet) | model | public, MIT | background removal (config default `briaai/RMBG-2.0` is gated + non-commercial → patched out, `trellis/handler.py:123`) |
| DINOv3 (via transformers) | model | **gated** | image conditioner — needs `HF_TOKEN` |
| [`Alamj/car-damage-models`](https://hf.co/Alamj/car-damage-models) | model | private | ⚠️ **separate car-damage workstream — HANDS OFF** (CLAUDE.md) |
| [`Alamj/car-damage-merged-v2`](https://hf.co/datasets/Alamj/car-damage-merged-v2) | dataset | private | ⚠️ car-damage workstream — HANDS OFF |

- **The AlamCars training set is NOT on HF** — it lives only on RunPod volume
  `yiv4apiad7`. There is no Hub backup.
- Upstream training code: **microsoft/TRELLIS.2 GitHub @ commit `75fbf01`**
  (pinned in the Dockerfile), not the Hub.
- API used: `models.from_pretrained` / HF hub download; token via
  `HF_TOKEN` = `HUGGING_FACE_HUB_TOKEN`.

### 3. Supabase (serving project)

- Project ref **`tfkvthprsntexrcuqpyd`** → `https://tfkvthprsntexrcuqpyd.supabase.co`
  (object base `/storage/v1/object`).
- Buckets:
  - **`car-renders`** (public read): `resolver/catalogue.v2.json`,
    `catalogue.json`, `reports/`, and the fine-tune area
    **`finetune/`** — bootstrap scripts + **`finetune/eval_inputs/{golf,escape,model3}`**.
  - **`car-meshes`**: GLBs, incl. **eval outputs at `eval/<RUNID>/`**.
- Auth: `SB_KEY` / `SUPABASE_SERVICE_KEY` (service role) for writes; public GET
  for reads.
- The Lovable **app** project is a different Supabase (`ghglvtwohetcrrswvqhp`,
  per CLAUDE.md) — not part of this build.

### 4. Docker Hub — `alamk123/ai-mechanic`

Tags: `trellis2-latest` / `trellis2-<sha>`, `render-latest`, `gsam-latest`,
`hunyuan21-latest` (retired), `trellis-latest` / `trellis-v1` (legacy). Built by
CI on push to `main` and `claude/lovable-connection-ki7jch`.

### 5. Adjacent APIs (not on the Alam-3D hot path)

- **DVSA MOT History**: `https://history.mot.api.gov.uk/v1/trade/vehicles/registration`
  via OAuth client-credentials (`login.microsoftonline.com`); secrets `DVSA_*`.
  Used by the `dvsa-lookup` edge function.
- **Replicate** (Seedance video worker): on branch `claude/review-crfuui`
  (PR #14), not in this branch.
- Rodin / Hyper3D and Hunyuan 3.x cloud clients exist
  (`pipeline/generators/*_api.py`) but are dormant (Rodin needs a Business key).

---

## Credentials

This sandbox has **none** of `RUNPOD_API_KEY`, `SB_KEY`/`SUPABASE_SERVICE_KEY`,
`HF_TOKEN`. The Hugging Face **MCP** is authenticated as `Alamj` (read-only Hub
access — that's how the repo states above were confirmed). Consequences:

- I **can** read HF repos (done).
- I **cannot** list live RunPod endpoints/pods, check volume `yiv4apiad7`, or
  fetch the eval GLBs from `car-meshes/eval/` — all need the keys in the env.

To resume the actual build, set in this environment: `RUNPOD_API_KEY` (`rpa_…`),
`HF_TOKEN` (gated DINOv3 + private push), `SB_KEY` (eval upload/fetch).

---

## Open questions blocking a decision

1. Did Stage C training finish 6000 steps and leave EMA checkpoints at
   `/workspace/alam3d_stage_c/ckpts/denoiser_ema0.9999_step*.pt` on the volume?
2. What is the Stage C loss curve (down vs flat/diverged)?
3. Did the eval run, and **did Alam-3D beat base** on golf + model3 + the
   *unseen* escape/kuga, without degrading the unseen one? (GLBs in
   `car-meshes/eval/<RUNID>/`.)
4. Is any pod still alive/billing? (Volumes persist; `launch_pod.py` auto-deletes
   pods on every terminal path, but a manual/`--keep` pod could linger.)

## Recommended resume plan (go/no-go gated, per the plan doc)

1. **Restore creds** (`RUNPOD_API_KEY`, `HF_TOKEN`, `SB_KEY`) to the env; confirm
   no pod is left billing (`GET rest.runpod.io/v1/pods`).
2. **Verify the checkpoint** exists on volume `yiv4apiad7`: launch a cheap
   `--tier render` pod (or re-run `stage_c_eval_pod.sh`), `ls .../ckpts`, and
   recover the loss curve. If no checkpoint → re-run Stage C.
3. **Collect the eval**: fetch the 6 GLBs (or re-run eval), render 4-angle sheets,
   run `pipeline/qc/asset_audit.py` on each, owner eyeball per the visual-review
   standard.
4. **Decide:**
   - **Win** (alam3d sharper/proportionally better, unseen car not degraded) →
     push the checkpoint to `Alamj/alam-3d-v0` (private), set
     `trellis/handler.py:62` `IMAGE_MODEL`, rebuild `:trellis2-latest`, A/B once
     more from the live endpoint, then flip.
   - **No win** → stop per the plan; keep base TRELLIS.2 + the Meshy/assembly
     path shipping. Consider Stage D (1024-cascade extension) only if C is
     promising-but-marginal.

## A strategic note (from the forensic report, worth re-reading before spending)

`docs/alam3d-forensic-report.md` argues the real differentiator is **not** the
weights but the **owned assembly stage** (glass split, parametric interior,
proportion fix, wheel replacement) + the **five-gate QC** — a fine-tune is
listed there as *step 5, optional, only if Rodin disappoints*. Two cheaper
levers are only partly pulled:
- **Free worker-quality knobs (F4):** `pipeline_type='1536_cascade'` is now the
  default (`trellis/handler.py:196`), but `num_samples` is still 1 (plan wanted
  3) and `texture_size` defaults to 2048 (max 4096). Bumping these is the
  cheapest quality win in the stack and needs no training.
- **Assembly stage** (`pipeline/blender/cabin_assembly.py`, `prop_fix`,
  `wheel_replace`) is the piece that first passed all five audit gates.

Recommend confirming the Stage C eval outcome **before** any further GPU spend —
if the fine-tune didn't clearly win, the higher-ROI work is the worker knobs and
the assembly stage, not Stage D.
