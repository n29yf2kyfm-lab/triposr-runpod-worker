#!/bin/bash
# publish_weights_pod.sh — publish Alam-3D weights from the training volume to
# the owner's PRIVATE Hugging Face repo, with a model card and a provenance
# manifest (the document a licensing conversation will need).
#
# Publishes the EMA checkpoint — that is the one the eval judged and the one
# inference should load. Repo stays private until the CC-BY attribution
# question is cleared with a lawyer (see the card's Licence section).
# Secrets: HF_TOKEN via pod env only. No secrets in this file.
OUT=/workspace/alam3d_publish
CKPTS=/workspace/alam3d_stage_c/ckpts
REPO=${HF_REPO:-Alamj/alam-3d-v0}
mkdir -p "$OUT/logs"
( cd "$OUT/logs" && python3 -m http.server 8000 >/dev/null 2>&1 & )
RUN_LOG="publish_$(hostname)_$(date -u +%Y%m%dT%H%M%SZ).log"
ln -sf "$RUN_LOG" "$OUT/logs/stage_b.log"   # launcher polls this name
exec > >(tee -a "$OUT/logs/$RUN_LOG") 2>&1
status(){ printf '{"step":"%s","at":"%s"}\n' "$1" "$(date -u +%FT%TZ)" > "$OUT/logs/status.json"; echo "===== $1 ====="; }

status boot
[ -f /etc/rp_environment ] && source /etc/rp_environment
export HF_TOKEN HUGGING_FACE_HUB_TOKEN
[ -n "$HF_TOKEN" ] && echo "HF token: present (${#HF_TOKEN} chars)" || { echo "HF token MISSING"; status FATAL-no-token; sleep infinity; }
pip install -q "huggingface_hub>=0.26" hf_transfer || true
export HF_HUB_ENABLE_HF_TRANSFER=1
ls -la "$CKPTS" || { status FATAL-no-ckpts; sleep infinity; }

status build-card
python3 - <<'PY'
import csv, glob, json, os, collections
root="/workspace/alamcars"; out="/workspace/alam3d_publish"
os.makedirs(out, exist_ok=True)

# provenance: what the model was actually trained on, from the dataset metadata
rows=[]
try:
    with open(f"{root}/metadata.csv") as f:
        rows=list(csv.DictReader(f))
except Exception as e:
    print("metadata read failed:", e)
lic=collections.Counter((r.get("licence") or "unknown") for r in rows)
makes=collections.Counter((r.get("make") or "?").lower() for r in rows)
cond=sum(1 for r in rows if str(r.get("cond_rendered")).lower() in ("true","1"))

with open(f"{out}/training_data_provenance.csv","w",newline="") as f:
    w=csv.writer(f); w.writerow(["sha256","make","model","licence","source_url"])
    for r in rows:
        w.writerow([r.get("sha256"), r.get("make"), r.get("model"),
                    r.get("licence"), r.get("source_url")])

steps=sorted(int(os.path.basename(p).split("step")[-1].split(".")[0])
             for p in glob.glob("/workspace/alam3d_stage_c/ckpts/denoiser_ema*step*.pt"))
card=f"""---
license: other
license_name: trellis2-mit-derivative
tags: [3d-generation, image-to-3d, automotive, trellis]
base_model: microsoft/TRELLIS.2-4B
library_name: trellis2
---

# Alam-3D v0

Domain fine-tune of the TRELLIS.2 shape flow model (`slat_flow_img2shape_dit_1_3B_512`)
for **car and van reconstruction from photographs**. Built by ExpertCarCheck to
generate premium GLB vehicle models offline for a UK vehicle-check product.

**Private repository — not for redistribution.** See Licence below.

## What this is

| | |
|---|---|
| Base | `microsoft/TRELLIS.2-4B` (MIT), shape stage only |
| Trained stage | `shape_slat_flow_model_512` (1.29B params) |
| Untouched | sparse-structure stage, 1024 refiner, texture stages |
| Schedule | {max(steps) if steps else '?'} steps, LR 1e-5, effective batch 4, bf16 AMP, 1x A100 80GB |
| Init | released TRELLIS.2-4B shape-flow weights |
| Checkpoints | EMA (0.9999) at steps {', '.join(map(str,steps)) or 'n/a'} |

## Training data

{len(rows)} curated vehicle GLBs ({cond} with 16-view conditioning renders),
rendered through the upstream `data_toolkit` pipeline.

Licence mix: {dict(lic)}
Top makes: {', '.join(f'{k} ({v})' for k,v in makes.most_common(10))}

Per-asset provenance (sha256, make, model, licence, source URL) is in
`training_data_provenance.csv` in this repo.

## Evaluation

Same-seed A/B against the unmodified base model, full 1024-cascade pipeline,
three fixed cases: VW Golf (4 dealer photos), Tesla Model 3 (single side photo),
Ford Escape (4 photos, make absent from training). Findings:

- **Single-photo input:** clearest improvement — sharper front-end structure,
  better-resolved lights and wheels than base.
- **Multi-photo input:** roughly at parity with base at full cascade; the
  untuned 1024 refiner re-imposes its own detailing over the tuned 512 stage.
- **Unseen make:** no degradation — no evidence of catastrophic forgetting.

## Intended use and limits

Offline generation of vehicle GLBs for a curated catalogue, with human visual
review before anything ships. Not a vehicle *recognition* model: it does not
identify make or model, and must not be used to assert vehicle identity.
Texture quality is unchanged from base (texture stages were not trained).

## Licence

Base weights are MIT (TRELLIS.2), which permits fine-tuning and redistribution.
The training assets are predominantly CC-BY 3D models; attribution obligations
for *derived weights* are legally untested. This repository is therefore
**private** pending legal review. The image conditioner (`facebook/dinov3-*`)
is downloaded separately by the user under Meta's own DINOv3 licence and is not
redistributed here.
"""
open(f"{out}/README.md","w").write(card)
print("card + provenance written;", len(rows), "assets")
PY

status upload
python3 - <<'PY'
import glob, os
from huggingface_hub import HfApi
api=HfApi(token=os.environ["HF_TOKEN"])
repo=os.environ.get("HF_REPO","Alamj/alam-3d-v0")
api.create_repo(repo, repo_type="model", private=True, exist_ok=True)
out="/workspace/alam3d_publish"
for f in ("README.md","training_data_provenance.csv"):
    api.upload_file(path_or_fileobj=f"{out}/{f}", path_in_repo=f, repo_id=repo)
    print("uploaded", f)
# the evaluated weights: EMA checkpoints (largest step first)
ck=sorted(glob.glob("/workspace/alam3d_stage_c/ckpts/denoiser_ema*step*.pt"), reverse=True)
if not ck:
    raise SystemExit("no EMA checkpoint found")
for p in ck[:1]:                        # ship the evaluated checkpoint
    name=os.path.basename(p)
    print(f"uploading {name} ({os.path.getsize(p)/1e9:.2f}GB) ...", flush=True)
    api.upload_file(path_or_fileobj=p, path_in_repo=f"ckpts/{name}", repo_id=repo)
    print("uploaded", name)
cfg="/workspace/alamcars/stage_c_cfg.json"
if os.path.exists(cfg):
    api.upload_file(path_or_fileobj=cfg, path_in_repo="stage_c_config.json", repo_id=repo)
    print("uploaded config")
print("PUBLISH_OK", repo)
PY
[ $? -ne 0 ] && { echo "PUBLISH FAILED"; status FATAL-publish; sleep infinity; }

status DONE
sleep infinity
