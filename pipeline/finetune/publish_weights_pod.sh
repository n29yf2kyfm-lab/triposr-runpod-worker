#!/bin/bash
# publish_weights_pod.sh — archive Alam-3D Stage C v1 weights to the owner's
# PRIVATE Hugging Face repo, with a model card and a provenance manifest.
#
# WHY THIS EXISTS AT ALL: the checkpoints live in exactly one place, on the
# network volume that has already truncated one file mid-save (step 1250, 3264MB
# against a healthy 5169MB, killed by a full volume). A single copy of an
# unreproducible artefact is not storage, it is a countdown.
#
# This is a rewrite. The previous version would have done three separate kinds
# of damage, all of them silent:
#
#   1. It pointed at /workspace/alam3d_stage_c — the v0 run directory, which was
#      purged on 2026-07-28 to reclaim the volume. Same hardcoded-v0-path bug as
#      the eval script's M5, in two places, one of which was NOT the $CKPTS var.
#   2. It uploaded sorted(...)[:1] with reverse=True — the HIGHEST step. That is
#      step 1250, the corrupt one. It would have archived a truncated file and
#      labelled it the evaluated weights.
#   3. create_repo(private=True, exist_ok=True) does NOT make an existing public
#      repo private. It returns happily and the upload proceeds. Against the
#      owner's standing instruction — "make sure is private no one cud acess it
#      without me" — that is the worst failure in the file, so privacy is now
#      READ BACK from the API and proven before a single byte of weights moves.
#
# The card is also built from what the pod can READ, not from what the author
# remembered. The old card asserted "LR 1e-5"; the optimizer in that run was
# actually on 1e-4, because trainer.args.learning_rate is decorative and
# trainer.args.optimizer.args.lr is the real one. A card that states unverified
# hyperparameters is the same lie in a more permanent place.
#
# Secrets: HF_TOKEN via pod env only. No secrets in this file.
RUNDIR=${PUBLISH_RUN_DIR:-/workspace/alam3d_stage_c_v1}
CKPTS="$RUNDIR/ckpts"
OUT=/workspace/alam3d_publish
REPO=${HF_REPO:-Alamj/alam-3d-v1}
KEEPER=${PUBLISH_KEEPER_STEP:-500}

mkdir -p "$OUT/logs"
( cd "$OUT/logs" && python3 -m http.server 8000 >/dev/null 2>&1 & )
RUN_LOG="publish_$(hostname)_$(date -u +%Y%m%dT%H%M%SZ).log"
ln -sf "$RUN_LOG" "$OUT/logs/stage_b.log"   # launcher polls this name
exec > >(tee -a "$OUT/logs/$RUN_LOG") 2>&1
status(){ printf '{"step":"%s","at":"%s"}\n' "$1" "$(date -u +%FT%TZ)" > "$OUT/logs/status.json"; echo "===== $1 ====="; }

status boot
[ -f /etc/rp_environment ] && source /etc/rp_environment
export HF_TOKEN HUGGING_FACE_HUB_TOKEN
[ -n "$HF_TOKEN" ] && echo "HF token: present (${#HF_TOKEN} chars)" \
  || { echo "HF token MISSING"; status FATAL-no-token; sleep infinity; }
echo "run dir: $RUNDIR    repo: $REPO    keeper step: $KEEPER"
# The python heredocs below are quoted ('PY'), so nothing is interpolated into
# them by the shell — deliberately, so a path can never be spliced into code.
# They read these instead, which means the value the shell resolved is the exact
# value python sees.
export CKPTS_DIR="$CKPTS" RUN_DIR="$RUNDIR" KEEPER_STEP="$KEEPER" HF_REPO="$REPO"
pip install -q "huggingface_hub>=0.26" hf_transfer pandas || true
export HF_HUB_ENABLE_HF_TRANSFER=1
ls -la "$CKPTS" || { echo "no ckpts at $CKPTS"; status FATAL-no-ckpts; sleep infinity; }

# ----------------------------------------------------------------- PRIVACY
# Proven BEFORE the card is built and long before any weights upload. If this
# repo is public, or becomes public, the run stops here having leaked nothing.
status privacy-gate
python3 - <<'PY' || { echo "PRIVACY GATE FAILED"; status FATAL-not-private; sleep infinity; }
import os, sys
from huggingface_hub import HfApi
api = HfApi(token=os.environ["HF_TOKEN"])
repo = os.environ.get("HF_REPO", "Alamj/alam-3d-v1")
api.create_repo(repo, repo_type="model", private=True, exist_ok=True)
# exist_ok=True means create_repo is a NO-OP on an existing repo — including an
# existing PUBLIC one. Its success proves nothing about visibility. Ask.
info = api.repo_info(repo, repo_type="model")
print(f"repo {repo}: private={info.private}")
if not info.private:
    print("FATAL: repo is PUBLIC. Refusing to upload weights.")
    print("       Set it private in the HF UI, or publish to a new repo name.")
    sys.exit(1)
print("privacy confirmed: repo is private")
PY

# ------------------------------------------------------- CHECKPOINT INTEGRITY
status verify-ckpts
python3 - <<'PY' || { echo "NO INTACT CHECKPOINT"; status FATAL-ckpt-integrity; sleep infinity; }
import glob, json, os, re, sys, zipfile
ck_dir = os.environ.get("CKPTS_DIR")
paths = sorted(glob.glob(f"{ck_dir}/denoiser_ema*step*.pt"))
if not paths:
    print(f"FATAL: no EMA checkpoints in {ck_dir}"); sys.exit(1)
good, bad = [], []
for p in paths:
    step = int(re.search(r"step0*(\d+)", os.path.basename(p)).group(1))
    mb = os.path.getsize(p) // (1024 * 1024)
    try:
        # A .pt is a zip. Truncation by a full volume shows up here and nowhere
        # else until something tries to load it — which on 2026-07-28 was four
        # checkpoints into a GPU sweep.
        with zipfile.ZipFile(p):
            pass
        good.append({"step": step, "file": os.path.basename(p), "mb": mb})
        print(f"  ok      step {step:>5}  {mb}MB")
    except Exception as e:
        bad.append({"step": step, "file": os.path.basename(p), "mb": mb,
                    "error": type(e).__name__})
        print(f"  CORRUPT step {step:>5}  {mb}MB  {type(e).__name__}")
if not good:
    print("FATAL: every checkpoint is unreadable"); sys.exit(1)
keeper = int(os.environ.get("KEEPER_STEP", "500"))
if keeper not in [g["step"] for g in good]:
    print(f"FATAL: keeper step {keeper} is missing or corrupt — that is the one "
          f"the eval chose, so there is nothing worth publishing without it.")
    sys.exit(1)
json.dump({"good": good, "bad": bad, "keeper": keeper},
          open("/workspace/alam3d_publish/ckpt_integrity.json", "w"), indent=1)
print(f"{len(good)} intact, {len(bad)} corrupt; keeper step {keeper} is intact")
PY

status build-card
python3 - <<'PY' || { echo "CARD BUILD FAILED"; status FATAL-card; sleep infinity; }
import csv, glob, json, os, re, sys, collections
root = "/workspace/alamcars"
out = "/workspace/alam3d_publish"
rundir = os.environ["RUN_DIR"]
integ = json.load(open(f"{out}/ckpt_integrity.json"))

# ---- hyperparameters: read them, never recite them ----------------------
cfg_path = f"{root}/stage_c_v1_cfg.json"
if not os.path.exists(cfg_path):
    print(f"FATAL: {cfg_path} missing — cannot state the run's hyperparameters "
          f"without reading them, and will not guess."); sys.exit(1)
cfg = json.load(open(cfg_path))["trainer"]["args"]
cfg_lr = float(cfg["optimizer"]["args"]["lr"])
bs_gpu = cfg.get("batch_size_per_gpu")
bsplit = cfg.get("batch_split")

# ---- the trainer's own banner: the only end-to-end proof of the real LR --
logs = sorted(glob.glob(f"{rundir}/logs/*.log"), key=os.path.getmtime)
banner_lr, instances = None, None
for lp in reversed(logs):
    txt = open(lp, errors="ignore").read()
    if banner_lr is None:
        m = re.findall(r"^\s*-\s*Learning rate:\s*(\S+)", txt, re.M)
        if m:
            banner_lr = m[-1]
    if instances is None:
        m = re.findall(r"Total instances:\s*(\d+)", txt)
        if m:
            instances = int(m[-1])
    if banner_lr and instances:
        break
if banner_lr is None:
    print("FATAL: no 'Learning rate:' banner found in any run log. The whole "
          "point of this card is that the recorded LR is the one the optimizer "
          "used; without the banner that cannot be stated."); sys.exit(1)
if abs(float(banner_lr) - cfg_lr) > 1e-12:
    print(f"FATAL: config lr {cfg_lr} but trainer banner says {banner_lr}. "
          f"These weights were not trained at the rate the config claims."); sys.exit(1)
print(f"verified LR {banner_lr} (config and trainer banner agree); "
      f"instances={instances}")

# ---- provenance ---------------------------------------------------------
rows = []
try:
    with open(f"{root}/metadata.csv") as f:
        rows = list(csv.DictReader(f))
except Exception as e:
    print("FATAL: metadata read failed:", e); sys.exit(1)
lic = collections.Counter((r.get("licence") or "unknown") for r in rows)
makes = collections.Counter((r.get("make") or "?").lower() for r in rows)
with open(f"{out}/training_data_provenance.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["sha256", "make", "model", "licence", "source_url"])
    for r in rows:
        w.writerow([r.get("sha256"), r.get("make"), r.get("model"),
                    r.get("licence"), r.get("source_url")])

keeper = integ["keeper"]
good_steps = ", ".join(str(g["step"]) for g in integ["good"])
corrupt = ("none" if not integ["bad"] else
           ", ".join(f"step {b['step']} ({b['mb']}MB, {b['error']})"
                     for b in integ["bad"]))
inst = instances if instances is not None else "not recorded in the run log"

card = f"""---
license: other
license_name: trellis2-mit-derivative
tags: [3d-generation, image-to-3d, automotive, trellis]
base_model: microsoft/TRELLIS.2-4B
library_name: trellis2
---

# Alam-3D v1 (Stage C)

Domain fine-tune of the TRELLIS.2 **shape** flow model
(`slat_flow_img2shape_dit_1_3B_512`) for car and van reconstruction from
photographs. Built by ExpertCarCheck to generate GLB vehicle models offline for
a UK vehicle-check product.

**Private repository — not for redistribution.** See Licence below.

## What this is

| | |
|---|---|
| Base | `microsoft/TRELLIS.2-4B` (MIT), shape stage only |
| Trained stage | `shape_slat_flow_model_512` (1.29B params) |
| Untouched | sparse-structure stage, 1024 refiner, **both texture stages** |
| Learning rate | **{banner_lr}** — read from the trainer's own banner and cross-checked against `optimizer.args.lr` in the config on disk |
| Batch | {bs_gpu} per GPU, batch_split {bsplit} |
| Precision | bf16 AMP |
| Training instances | {inst} |
| Init | released TRELLIS.2-4B shape-flow weights |
| Checkpoints here | EMA (0.9999) at steps {good_steps} |
| **Recommended** | **step {keeper}** |
| Excluded as corrupt | {corrupt} |

### On the learning rate

Every earlier run in this project recorded an LR it did not use.
`trainer.args.learning_rate` is decorative; the optimizer reads
`trainer.args.optimizer.args.lr`. v0 (nominally 1e-5) and Stage D (nominally
8e-6) both actually trained at the stock 1e-4, which voids every conclusion
drawn from them. This run sets the real key, and the value above was taken from
the trainer's runtime banner rather than from the config or from memory.

## Why step {keeper}

Same-photo, same-seed, same-render A/B of stock TRELLIS.2 against checkpoints
250 / 500 / 750 / 1000, two vehicles:

- **VW Golf GTI** (in-domain): visible gain by step 250 — defined lower bumper
  intakes, resolved headlight shapes, a defined sill where stock has a smooth
  slab. Best at step 500, which additionally resolves the red GTI grille stripe
  that stock omits.
- **Nissan Qashqai** (make/model outside the training distribution): flat across
  all checkpoints. No gain, and no degradation either — no evidence of
  catastrophic forgetting.
- **Steps 750 and 1000 regress.** Bonnet surfaces develop ripple and denting on
  the in-domain car. At ~16 shapes/step the model had already made roughly 25
  passes over the pool by step 500; past that it memorises.

**Limits of that evaluation, stated plainly: 2 vehicles, 1 camera angle, 1 seed.**
It is a signal, not a proof. It has not been repeated at scale.

## Training data

{len(rows)} curated vehicle GLBs, rendered through the upstream `data_toolkit`
pipeline, filtered by a per-shape human cull verdict (476 keep / 474 cull / 14
ungraded across 964 audited shapes).

Licence mix: {dict(lic)}
Top makes: {', '.join(f'{k} ({v})' for k, v in makes.most_common(10))}

Per-asset provenance (sha256, make, model, licence, source URL) is in
`training_data_provenance.csv` in this repo.

## Intended use and limits

Offline generation of vehicle GLBs for a curated catalogue, with human visual
review before anything ships. Not a vehicle *recognition* model: it does not
identify make or model, and must not be used to assert vehicle identity.

Two known limits, neither addressed by these weights:

- **Texture is unchanged from base.** Neither texture stage has been trained.
  Soft grille meshes, flat headlight internals and undefined shut lines are
  texture-stage problems and this model does not touch them.
- **Output is a single fused shell** with no separate body-paint material, so
  generated vehicles cannot be recoloured by material name.

## Licence

Base weights are MIT (TRELLIS.2), which permits fine-tuning and redistribution.
The training assets are predominantly CC-BY 3D models; attribution obligations
for *derived weights* are legally untested. This repository is therefore
**private** pending legal review. The image conditioner (`facebook/dinov3-*`)
is downloaded separately by the user under Meta's own DINOv3 licence and is not
redistributed here.
"""
open(f"{out}/README.md", "w").write(card)
print(f"card + provenance written; {len(rows)} assets")
PY

status upload
python3 - <<'PY' || { echo "PUBLISH FAILED"; status FATAL-publish; sleep infinity; }
import glob, json, os, sys
from huggingface_hub import HfApi
api = HfApi(token=os.environ["HF_TOKEN"])
repo = os.environ["HF_REPO"]
out = "/workspace/alam3d_publish"
ck_dir = os.environ["CKPTS_DIR"]
integ = json.load(open(f"{out}/ckpt_integrity.json"))

# Re-assert privacy immediately before the weights move. Cheap, and the gap
# between the first check and this upload is minutes of wall time on a repo the
# owner can toggle.
if not api.repo_info(repo, repo_type="model").private:
    print("FATAL: repo went public between the gate and the upload"); sys.exit(1)

for f in ("README.md", "training_data_provenance.csv", "ckpt_integrity.json"):
    api.upload_file(path_or_fileobj=f"{out}/{f}", path_in_repo=f, repo_id=repo)
    print("uploaded", f, flush=True)

# Every intact checkpoint, keeper first. They are all single-copy artefacts of
# an unreproducible run; the keeper is the one to load, the others are the only
# evidence that would let a larger eval later disagree with an n=2 verdict.
order = sorted(integ["good"], key=lambda g: (g["step"] != integ["keeper"], g["step"]))
sent = []
for g in order:
    p = os.path.join(ck_dir, g["file"])
    tag = "  <- KEEPER" if g["step"] == integ["keeper"] else ""
    print(f"uploading {g['file']} ({g['mb']}MB){tag} ...", flush=True)
    api.upload_file(path_or_fileobj=p, path_in_repo=f"ckpts/{g['file']}",
                    repo_id=repo)
    sent.append(g["file"])
    print(f"  uploaded ({len(sent)}/{len(order)})", flush=True)

cfg = "/workspace/alamcars/stage_c_v1_cfg.json"
if os.path.exists(cfg):
    api.upload_file(path_or_fileobj=cfg, path_in_repo="stage_c_v1_config.json",
                    repo_id=repo)
    print("uploaded config", flush=True)

# Prove the archive from the far side: list what the repo actually holds now.
# "upload_file returned" is not the same claim as "the file is in the repo".
files = set(api.list_repo_files(repo, repo_type="model"))
missing = [f"ckpts/{n}" for n in sent if f"ckpts/{n}" not in files]
if missing:
    print("FATAL: uploaded but absent from the repo listing:", missing); sys.exit(1)
print(f"verified in repo: {len([f for f in files if f.startswith('ckpts/')])} checkpoints")
print("PUBLISH_OK", repo)
PY

status DONE
sleep infinity
