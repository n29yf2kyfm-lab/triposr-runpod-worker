# CHECKPOINT — MOBILE-PERFORMANCE GATE

*(the repo-root `CHECKPOINT.md` belongs to Gate 3 v7; this file is the mobile gate's)*

**State: tool built, committed and pushed; artefacts bucket-backed; full gate run
in progress.**

## Rule Zero — nothing that matters is local-only

Verified by LISTING the prefix, not by trusting an upload status.

| bucket object | bytes | note |
|---|---|---|
| `car-meshes/staging/mobile/glb/car_rebound_mobile_draco.glb` | 3,654,488 | sha256 `fe93a1cd0286c6c2036d3dd0a378830b974ba34a52e1a43112ab634b319135fa` |
| `car-meshes/staging/mobile/tool/*.py`, `README.md` | 105,364 | 5 objects |
| `car-meshes/staging/mobile/evidence/*` | — | render evidence |

Tool source also lives in git (`pipeline/machine/mobile/`), pushed to
`claude/lovable-connection-ki7jch`. Origin and the bucket are the only two things
that have survived all six rollbacks.

Nothing produced here exceeds the ~22 MB part cap, so no chunking has been
needed yet; `sbput.py` in the scratchpad chunks and writes a MANIFEST
automatically above the cap.

## Subject

`car_rebound.glb`, sha256 `5380761c01dded53b286fafec22255237042d7d2effcd1192e79f10f374c88e0`,
28,703,944 bytes — fetched and hash-verified. The merged/grounded
`car_merged.glb` (sha `09897d20…`, 28,703,236 B) was also fetched, reassembled
from its two parts and hash-verified, and is used as the re-runnability proof.

## Measured, and reproducible

* **100.0 % geometry, 0 textures.** The inverse of the file `mobile_export.py`
  was calibrated on; every texture stage there is a no-op here.
* 985,227 triangles · 702,178 vertices · **30 draw calls** · 11 materials ·
  30 named nodes · 28.67 MB of GPU-resident buffers.
* WORLD extents **4.2825 × 1.4554 × 1.7887 m**. The 1.7798 height in the brief is
  the RAW union with node transforms ignored and is 22 % too tall.
* Grounding, world space: **FL +183.2 mm, FR +189.6 mm, RL +0.3 mm, RR +14.7 mm
  — 4.07° nose-up.** Independently reproduced; matches the coordinator's
  correction. The model bbox min-Y is +0.3 mm, so a bbox-based grounding check
  passes this car with two wheels in the air.
* Draco baseline **28.70 MB → 3.654 MB**, 30/30 node names, 30/30 material
  bindings, 30/30 NORMAL accessors, validator 0 errors / 0 warnings,
  PSNR vs master **min 40.45 dB** over 11 cameras, geometry retention 100.0 % on
  every material.
* **Measured load times** (Chromium + SwiftShader, desktop CPU, CDP-emulated
  link, median of cold loads): Draco 3.654 MB → wifi 50 Mbit/s **1.66 s**
  (transfer 0.72 / decode 0.94); typical 4G 8 Mbit/s **4.72 s** (transfer 3.87 /
  decode 0.85). JS heap delta 34.1 MB.

## Findings that belong to other gates

* **Interior-shell z-fighting.** Removing the `Interior` node removes the black
  speckling over the paint: **5.73 % of car pixels across 8 views** are dark in
  the master and red paint with the interior gone. Upper bound — some of those
  pixels are legitimately cabin-through-glass — but the bonnet/roof speckle in
  `evidence/INTERIOR_ZFIGHT_PAIR.png` is unambiguous. Depth precision is
  typically *worse* on mobile GPUs, so this will not improve on a phone.
* **There is no mobile serving path at all.** `platform/resolver/index.ts:217`
  sets `glbUrl = variantKey ? variants[variantKey] : a.desktopGlbUrl` — the
  desktop asset, for every device. `mobileGlbUrl` is only echoed at line 231, and
  in `catalogue.v2.json` **1,042 of 1,043 approved entries have
  `mobileGlbUrl` identical to `desktopGlbUrl`**. Approved "mobile" asset sizes:
  median 10.1 MB, p90 34.0 MB, max 47.9 MB; **64.3 % exceed 5 MB, 29.8 % exceed
  20 MB.**

## Next

Finish the ladder + negative-control run, run the tool over `car_merged.glb` as
the reusability proof, upload the report, hand over.
