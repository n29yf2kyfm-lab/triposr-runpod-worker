# Alam-3D v2 — OUR OWN MODEL (owner directive 2026-08-15)

Owner's words: "This is gonna be our own fucking model. Not gonna be no asset
model." This document is the re-engineering plan. v1 exists (`Alamj/alam-3d-v1`,
a TRELLIS.2 fine-tune on 366 cars) and hit the melt ceiling. v2 changes the two
things the record says were wrong, and nothing else.

## Why v1 was soft — measured, not guessed

1. **Wrong conditioning.** v1 conditioned on RGB images. The Hi3DGen experiment
   (2026-08-15) proved the sharpness lever is NORMAL-MAP conditioning on the
   same backbone: crease_density 145–183 vs 37–39, the first generated bonnet
   shut line ever seen in this project. The backbone was never the problem.
2. **Dirty data.** 366 uncurated assets; the Stage-C/D audits later found junk
   in the pool. We now hold **1,026 approved cars** that have passed the full
   material-gate stack — 2.8x the data, all clean.

## The v2 recipe

- **Base weights**: Hi3DGen (`Stable-X/trellis-normal-v0-1`) — TRELLIS-1
  architecture, the sharpest open checkpoint measured on cars.
- **Training code**: microsoft/TRELLIS `train.py` (MIT, verified public
  2026-08-15) — flow-model fine-tune configs included. Hi3DGen's weights are
  that architecture, so they load into that trainer.
- **Conditioning**: GROUND-TRUTH normal maps rendered from our own GLBs
  (16 views/car). No StableNormal in the training loop — our meshes ARE the
  truth. At inference the deployed carglb chain already turns photos into
  normals via StableNormal, so the serving path is unchanged.
- **Data**: the 1,026 approved catalogue cars. Excluded by construction:
  everything in REJECTS.json, everything quarantined (354), replaced/rejected.
  `pipeline/finetune/curation/v2_split.json` freezes the train/eval split.
- **What trains**: the SLat flow model only, short schedule, low LR (adapter
  or short-schedule full — decided by Stage B smoke). Sparse-structure flow
  and VAEs stay frozen at first. Texture models untouched — geometry was
  always the complaint.

## The honest bet, stated up front

Fine-tuning cannot raise the grid resolution — the voxel wall stands. The bet
is different: a model that has only ever seen 1,026 clean cars spends its
resolution ON CARS (creases, arch lips, shut-line shadows) instead of
averaging over 500k generic objects. Hi3DGen stock already proves the
architecture can spend resolution well; v2 teaches it to spend ours on our
domain. If the bet fails the eval below says so in numbers, and the route is
closed for good with evidence.

## Pre-registered eval (decided before training, so no vibes)

Held-out set (24 cars, in v2_split.json) + the Golf GTI photo set + the Ford
Kuga listing photos (unseen make). Base Hi3DGen vs v2, same seeds, same rig:
- `mesh_forensics` sharp_share / crease_density: v2 must BEAT stock Hi3DGen
  (2.07% / 145) on held-out cars, not merely match it;
- carglb gates must still pass end to end (panes, wheels, respray);
- owner eyeballs the sheets — final word, per the standing standard.
Degradation on the unseen make = overfit = stop.

## Staged budget (balance was $20.09 on 2026-08-15 — stages gate spend)

| Stage | What | Est. cost | Funded today? |
|---|---|---|---|
| A2 | dataset: 1,026 GLBs -> TRELLIS-1 latents + 16-view normal conds | $10–20 | just barely |
| B | smoke: weights load in trainer, loss falls, 1-car overfit | $10–15 | NO — needs top-up |
| C | short fine-tune, 24–48h on 1x A100 80GB | $45–120 | NO |
| D | eval renders + A/B sheets | ~$5 | NO |

**Total to a go/no-go verdict: roughly $70–160. Owner top-up needed: ~$150**
to see the whole thing through without stopping mid-stage.

## Deployment when it wins

Private HF repo `Alamj/alam-3d-v2`. carglb's shape pod points at it instead of
stock Hi3DGen (one line in shape_boot.sh). Everything downstream — fit_panes,
wheel donors, photo texture, gates, orientation — is already built and gated.

## Stop rules

- Stage B: weights don't load / loss flat after config triage -> stop, record,
  fall back is stock Hi3DGen (already deployed).
- Stage C: eval loses to stock on held-out cars -> stop. Weights are kept,
  route closed with numbers.
- No stage starts until the previous one's artefact is verified in the bucket
  (the pod-monitoring rules in CLAUDE.md apply — artefacts, never desiredStatus).
