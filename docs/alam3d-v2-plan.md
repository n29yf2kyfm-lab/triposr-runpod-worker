# Alam-3D v2 — superseded same day by the settled MACHINE_PLAN route

**Read `pipeline/trellis/MACHINE_PLAN.md` instead. That is the plan of record.**

This document was written 2026-08-15 in response to the owner's directive
("make me my own model") — and then the branch rebase surfaced a parallel
session from 2026-08-14 that had already taken the same directive further,
with owner decisions recorded:

- **Owner decision 2026-08-14: own weights, no API.** Already ruled.
- **Base settled by three-way shootout: Hunyuan3D-2.1** — best geometry AND
  the only official fine-tune path. This document proposed fine-tuning
  Hi3DGen via the microsoft/TRELLIS trainer; that is STRUCK — the other
  session verified Hi3DGen's repo is inference-only, and its high crease
  score (92.4) is substantially NOISE (ragged borders), which is why it lost
  the shootout despite the number.
- **Trainer smoke already PASSED** (Phase 2a-0, 10.28GB checkpoint, every
  env fix permanent in `hy21_smoke.sh`).
- **"Train on all 1,026" was measured HALF WRONG** before any spend: one in
  three catalogue cars is SOFTER than what 2.1 already generates and would
  teach softness. Curation by crease density is mandatory
  (`TRAINSET_SCORES.jsonl`, 1,019 scored). This document's v2_split.json
  (all-approved split) is superseded by the curated pilot list
  (`pipeline/finetune/curation/pilot200.json`).

What survives from this document into the plan of record:

1. **Held-out eval discipline**: keep unseen cars AND an unseen make out of
   training; judge base-vs-pilot on them with mesh_forensics + the eye.
   (Folded into the Phase 2b gate.)
2. **The normal-conditioning evidence**: on the same backbone, normal-map
   conditioning measurably sharpens output (Hi3DGen vs TRELLIS, crease 145
   vs 37). Parked as a LATER conditioning lever for the 2.1 fine-tune
   (Hunyuan3D-Omni is the natural vehicle — already noted in MACHINE_PLAN).
3. Balance as of 2026-08-15: **$20.09** — funds Phase 2a (~$2–8) only.
   Phase 2b (~$150–400) needs an owner top-up.
