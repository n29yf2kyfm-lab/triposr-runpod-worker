# CHECKPOINT — merge operator (Gate 6 stance -> Gate 7+8 rebound base)

## STATE: COMPLETE. Deliverable bucket-backed, all acceptance checks pass.

**Deliverable** `car-meshes/staging/merge/glb/` — `car_merged.glb`,
28,703,236 bytes, sha256
`09897d2037a4566bd447f1fc80fb07b4d818c757e756760bfdbcb1723ae25e8d`,
stored as 2 parts + MANIFEST.txt. Re-downloaded from the bucket and compared
byte-for-byte with the local file: identical. Prefix listed and verified.
Full report: `car-meshes/staging/merge/MERGE_REPORT.md` (also in-repo at
`pipeline/machine/merge/MERGE_REPORT.md`).

## Headline
tyre bottoms **FL +0.000000 · FR -0.000000 · RL -0.000000 · RR -0.000000 mm**
(tol +-0.5 mm; before: +183.2 / +189.6 / +0.3 / +14.7 mm).
All four Gate 7+8 properties survived: glass_probe clear/proven · tyres black ·
respray control holds (carpaint moves 175-215 sRGB, tyres 1.1-1.4, glass
5.7-21.4, rims 5.6-7.9, tail lamps 0.1-0.2) · Khronos 0 errors 0 warnings.
Material table diff EMPTY, binding diff EMPTY, 30/30 primitives carry NORMAL.

## CORRECTION TO THE BRIEF
The brief's tyre-bottom figures (-0.3067 / -0.3233 / -0.3241) are the wheel
meshes' **node-local** minima; the wheel nodes carry real translations. In world
space the front tyres were 183/190 mm IN THE AIR, i.e. Gate 6's own baseline,
not 324 mm below the floor. local+nodeT reproduces the brief's numbers exactly.

## Route: (B) re-apply Gate 6's operations to the base's own geometry
Not (A) transplant — Gate 6's wheels are four-material mixtures cut from a fused
shell, its file is texture-reduced, and (A) does not generalise to the v7 output.

## What was deliberately NOT carried across, with evidence
Wheel AXIS SQUARING, width equalisation, and Gate 6's literal track numbers.
`merge_calib.py` injection ladders: toe response slope FL +0.770, FR **-0.735**,
RL +0.967, RR **-0.400** — on two of four corners the probe reports an injected
rotation as a rotation the OTHER WAY. Four independent axis estimators disagree
by up to 11.15 deg. The squaring build was made and measured: it left residual
toe +1.287/+0.636/+0.057/**-1.132** deg, RR overshooting and changing sign.
Available behind `--square-axes` / `--equalise-width` / `--track-mode gate6`.

## Tools (pipeline/machine/merge/, branch claude/lovable-connection-ki7jch)
glb_io.py · wheel_probe.py · merge_op.py · verify_merge.py · merge_calib.py ·
merge_views.py · control_numbers.py · sb_chunk.py · selftest.py

## Reuse on the Gate 3 v7 front-rebuild output
```
python3 pipeline/machine/merge/merge_op.py V7.glb OUT.glb \
    --pose-mode record --pose-json op_pose.json --report R.json
python3 pipeline/machine/merge/verify_merge.py V7.glb OUT.glb \
    --merge-report R.json --controls
```
`selftest.py` proves this rather than asserting it: on a v7-SHAPED input (fascia
nodes renamed, grille rebound to a new 12th material) the wheel plan is
identical to the reference run, worst delta 0.000e+00; renamed nodes and the new
material survive; all four ground; and the three refusal paths all fire.

## Verification status
verify_merge.py: ALL_OK true, CONTROLS_OK true (6/6 negative controls fire).
selftest.py: SELFTEST_OK true.
