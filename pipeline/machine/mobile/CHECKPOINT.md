# CHECKPOINT — MOBILE-PERFORMANCE GATE

*(the repo-root `CHECKPOINT.md` belongs to Gate 3 v7; this file is the mobile gate's)*

**State: tool built, committed, pushed and VALIDATED IN BOTH DIRECTIONS;
artefacts bucket-backed; full ladder + negative-control run executing.**

## Rule Zero — nothing that matters is local-only

Verified by LISTING each prefix, not by trusting an upload status.

| bucket object | bytes |
|---|---|
| `car-meshes/staging/mobile/glb/car_rebound_mobile_draco.glb` | 3,654,488 — sha256 `fe93a1cd0286c6c2036d3dd0a378830b974ba34a52e1a43112ab634b319135fa` |
| `car-meshes/staging/mobile/tool/` (4 .py + README.md) | 105,364 across 5 objects |
| `car-meshes/staging/mobile/evidence/` | z-fight pair render, respray validation JSON both directions |

Tool source is also in git (`pipeline/machine/mobile/`) on
`claude/lovable-connection-ki7jch`. Origin and the bucket are the only two things
that have survived all six rollbacks. Nothing produced here exceeds the ~22 MB
part cap; `sbput.py` in the scratchpad chunks with a MANIFEST above it.

## Subject

`car_rebound.glb`, sha256 `5380761c…c88e0`, 28,703,944 B — hash-verified on fetch.
`car_merged.glb` (sha `09897d20…`, 28,703,236 B) also fetched, reassembled from
its two parts, hash-verified, and measured as the re-runnability proof.

## Measured

* **100.0 % geometry, 0 images, 0 textures** — the inverse of the file
  `mobile_export.py` was calibrated on; every texture stage there is a no-op.
* 985,227 tri · 702,178 vert · **30 draw calls** · 11 materials · 30 named nodes ·
  **28.67 MB of GPU-resident buffers** (unchanged by codec).
* All indices are uint32 (2,955,681 = 11.82 MB), though most primitives are under
  65,536 vertices.
* World extents **4.2825 × 1.4554 × 1.7887 m**. The 1.7798 height quoted in the
  brief is the RAW union with node transforms ignored — 22 % too tall.
* Glass 3.1742 m² = **5.0 % of 63.6342 m²** total area — the catalogue median is
  5.75 % (CLAUDE.md 2026-08-19 calibration).
* Validator on the master: **0 errors, 0 warnings**, 2 infos (4 degenerate
  triangles), 90 hints (BUFFER_VIEW_TARGET_MISSING).
* Grounding, WORLD space: **FL +183.2 mm, FR +189.6 mm, RL +0.3 mm, RR +14.7 mm
  → 4.07° nose-up.** Reproduced independently; matches the coordinator's
  correction. The model bbox min-Y is +0.3 mm, so a bbox grounding check passes
  this car with two wheels in the air — which is what `viewer_check.py` does.
  `car_merged.glb` measures 0.000 mm on all four and has its node transforms
  baked (raw extents == world extents).
* Draco baseline **28.70 MB → 3,654,488 B (7.85×)**, reproducing Gate 7+8 exactly.
  30/30 nodes, 11/11 materials, 30/30 NORMAL, validator 0 errors,
  PSNR vs master **min 39.81 dB / mean 41.28 dB** over 11 cameras, geometry
  retention 100.0 % on every material. The minimum came from a CLOSE-UP
  (cu_lamp 39.81) rather than any full-car view (40.45).
* **Load time, measured** (Chromium + SwiftShader, desktop CPU, CDP-emulated link,
  median of cold loads, cache disabled): Draco 3.654 MB →
  wifi 50 Mbit/s **1.66 s** (transfer 0.72 / decode 0.94);
  typical 4G 8 Mbit/s **4.72 s** (transfer 3.87 / decode 0.85).
  JS heap delta 34.1 MB. Transfer sanity: 29.24 Mbit / 8 Mbit/s = 3.66 s + RTT ≈
  measured 3.87 s.
* Hidden-interior cull: 331,014 interior faces, 224 cameras, 61.93 % have
  line-of-sight (70.71 % by area); after a 2-ring dilate **98,480 faces (29.75 %
  of the interior, 10.0 % of the whole car) have no sightline from any camera**
  and are free to delete. 985,227 → 886,747 tri, all 30 nodes/materials/NORMALs
  intact.

## Instruments proven to fire

* **NC3 / respray** — `Tyre_Rubber` re-bound to `carpaint`: FAIL, on the
  phantom-material line. The real car's Draco export: PASS (carpaint 100.0 %
  moved; tyres 0.0 %, rims 0.6 %, lamps 0.1 % changed).
* NC1 (over-decimation) and NC2 (glazing gutted, material table untouched) are
  built and asserted by every run of `mobile_gate.py`; a run whose controls do
  not fire reports **BLOCKED**, never PASS.

## Findings that belong to other gates

* **Interior-shell z-fighting.** Removing the `Interior` node removes the black
  speckle over the paint: **5.73 % of car pixels across 8 views** are dark in the
  master and red paint with the interior gone (per view 2.65 %–7.35 %). Upper
  bound — some of those pixels are legitimately cabin-through-glass — but the
  bonnet/roof speckle in `evidence/INTERIOR_ZFIGHT_PAIR.png` is unambiguous.
  Depth precision is typically *worse* on mobile GPUs. The same coincidence shows
  up in the respray control as `Interior_Plastic` 24.7 % and `Arch_Liner` 18.9 %
  change on tiny samples.
* **There is no mobile serving path at all.**
  `platform/resolver/index.ts:217` — `glbUrl = variantKey ? variants[variantKey]
  : a.desktopGlbUrl` — the desktop asset, for every device. `mobileGlbUrl` is
  only echoed at :231, and in `catalogue.v2.json` **1,042 of 1,043 approved
  entries have `mobileGlbUrl` identical to `desktopGlbUrl`** (the one exception
  points at an `_uc.glb` of identical size). Approved asset sizes: median
  10.1 MB, p90 34.0 MB, max 47.9 MB; **64.3 % over 5 MB, 29.8 % over 20 MB**.
  1,007 approved entries carry colourVariants = **8,056 variant GLBs**, sampled
  8/8 each within ±1 % of its base size.

## Corrections made in flight

1. The brief's "not grounded, tyres y −0.3067 / −0.3241" is node-LOCAL. The truth
   is the opposite: rear tyres on the ground, front tyres ~185 mm in the air.
2. Three respray instruments withdrawn before one worked — see the commit
   `64d26c8` message for the mechanism of each.
3. First close-up cameras unioned multiple nodes and framed the whole car; the
   lamp camera then sat inside the nose.
4. `hidden_face_mask()` keys on the trimesh MESH name, `apply_face_cull()` on the
   MATERIAL name.
