# CHECKPOINT — merge operator (Gate 6 stance -> Gate 7+8 rebound base)

## STATE: deliverable BUILT, GATED and BUCKET-BACKED. Verification in progress.

**Deliverable** `car-meshes/staging/merge/glb/` — 2 parts + MANIFEST.txt,
`car_merged.glb`, 28,703,236 bytes,
sha256 `09897d2037a4566bd447f1fc80fb07b4d818c757e756760bfdbcb1723ae25e8d`.
Round-tripped from the bucket and compared byte-for-byte: identical.

## Inputs
* BASE  `staging/gate78/car_rebound.glb` sha `5380761c…c88e0` (matches brief)
* DONOR `staging/gate6/car_gate6_repaired_TEXTURES-REDUCED.glb` + Gate 6's
  op_pose.json / op_wheels*.json / TRANSFORM_TABLE / ACCEPTANCE (records only —
  no geometry taken from the donor; see route decision).

## CORRECTION TO THE BRIEF (measured, first thing done)
The brief states the base's tyre bottoms are y = RL −0.3067 · RR −0.3067 ·
FL −0.3233 · FR −0.3241 and the contact plane is ~324 mm below y=0. Those are
the wheel meshes' **node-local** accessor minima. The wheel nodes carry real
translations, and composed to world the bottoms are
**FL +0.1832 · FR +0.1896 · RL +0.0003 · RR +0.0147** — i.e. the front tyres are
183/190 mm IN THE AIR, which is Gate 6's own recorded baseline, not 324 mm under
the floor. local_min + nodeT reproduces the brief's four numbers exactly.
The base's world AABB is 4.282490 × 1.455398 × 1.788713 = Gate 6's recorded
`aabb_before` to six decimals, so the base sits in Gate 6's input frame.

## Route chosen: (B) re-apply Gate 6's OPERATIONS to the base's own geometry
Route A (transplanting Gate 6's wheel geometry) rejected: Gate 6's wheels were
cut from a fused shell and carry four-material mixtures against the base's clean
three-node-per-corner scheme; its shippable file is texture-reduced; and it does
not generalise to the v7 front-rebuild output.

## Tools (pipeline/machine/merge/, branch claude/lovable-connection-ki7jch)
* `glb_io.py`      glTF-level read/write — POSITION+NORMAL accessors only, so
                   the material table is preserved BY CONSTRUCTION
* `wheel_probe.py` geometric wheel identification + cylinder metrology
* `merge_op.py`    THE OPERATOR: pose (rigid) + per-wheel scale/place/ground
* `merge_views.py` matched-camera orthographic evidence renders
* `sb_chunk.py`    chunked bucket upload + paged listing + verified round trip

## Results so far
* tyre bottoms after merge: **FL +0.00000 · FR −0.00000 · RL −0.00000 ·
  RR −0.00000 mm** (measured from the written file, not the plan)
* glass_probe **clear / proven** (unchanged from base), flat_shell false,
  alpha_shell false
* Khronos validator 2.0.0-dev.3.10: **0 errors, 0 warnings**, 2 infos, 90 hints
  — identical to the base's own recorded report
* NORMAL accessor on 30/30 primitives, 0 zero-length normals
* material table diff EMPTY, binding table diff EMPTY (enforced by the operator,
  which refuses to write if either is non-empty)
* radius spread 16.1 mm -> 0.99 mm; all node transforms baked to identity

## Open at this checkpoint
red/blue respray control render, matched before/after sheet, injection-ladder
calibration report, rigidity proof file, final report.

## Decision recorded: wheel AXES ARE NOT ROTATED
Four independent estimators of the same wheel axis (tread-cylinder fit, brake-disc
PCA, brake-disc area-weighted face normals, rim PCA) disagree by **1.2–10.9°** on
this melt geometry, a contact-patch estimator is incoherent across thresholds, and
the closed-loop response of a full squaring correction measured **0.26–1.57** (on
RR it overshot and flipped the sign of the toe). Grounding, radius equalisation and
hub symmetry are measurable and were applied; squaring is behind `--square-axes`.
