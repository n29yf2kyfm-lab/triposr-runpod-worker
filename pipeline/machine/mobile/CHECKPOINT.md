# CHECKPOINT — MOBILE-PERFORMANCE GATE

*(the repo-root `CHECKPOINT.md` belongs to Gate 3 v7; this file is the mobile gate's)*

**State: COMPLETE. Verdict MOBILE GATE — FAIL. Tool built, validated in both
directions, committed and pushed; every artefact bucket-backed and verified by
listing.**

## Verdict

`car_rebound.glb` cannot be served to a phone as it stands, and the blocker is
**not** file size — it is that the only lever which would fix the triangle count
costs more fidelity than any threshold worth defending.

| candidate | MB | triangles | draw calls | GPU buffers | PSNR min | glass | tyres | validator | verdict |
|---|---|---|---|---|---|---|---|---|---|
| master | 28.704 | 985,227 | 30 | 28.67 MB | — | clear/proven | PASS | 0 err | over budget |
| **draco** | **3.654** | 985,204 | 30 | 26.29 MB | **39.81 dB** | clear/proven | PASS | 0 err | all gates PASS, **over budget** on triangles + GPU bytes |
| dec30 | 1.792 | 294,133 | 30 | 10.22 MB | 24.57 dB | clear/proven | PASS | 0 err | FAIL fidelity |
| dec20 | 1.286 | 196,193 | 30 | 6.89 MB | 21.73 dB | clear/proven | PASS | 0 err | FAIL fidelity |
| cull30 | 1.669 | 265,228 | 30 | 9.30 MB | 24.54 dB | clear/proven | PASS | 0 err | FAIL fidelity |

## The decimation curve — the reason for the verdict

| ratio | triangles | MB (draco) | PSNR min | IoU min |
|---|---|---|---|---|
| 1.00 | 985,204 | 3.654 | **39.81** | 0.99762 |
| 0.95 | 935,906 | 3.543 | 35.96 | 0.99571 |
| 0.90 | 886,412 | 3.434 | 34.10 | 0.97594 |
| 0.80 | 788,049 | 3.206 | 33.87 | 0.97433 |
| 0.65 | 639,508 | 2.839 | 33.21 | 0.98985 |
| 0.50 | 492,018 | 2.446 | 29.92 | 0.96576 |
| 0.30 | 294,133 | 1.792 | 24.57 | 0.97683 |
| 0.20 | 196,193 | 1.286 | 21.73 | 0.94617 |
| NC1 ~0.077 | 76,029 | — | 15.45 | 0.87926 |

**Removing the first 5% of triangles costs 3.85 dB.** The mechanism is visible in
`evidence/DEC30_DIFFMAP.png`: the change is not on the silhouette, it is the
clearcoat specular highlight breaking up across the big smooth panels. 64% of
large-delta pixels sit on painted body against a 31% base rate.

**The IoU column is non-monotonic and that settles the metric argument in our own
data**: dec30 at 294,133 triangles scores min IoU **0.97683**, *higher* than
r090 at 886,412 triangles (0.97594) — an IoU gate would prefer the file with two
thirds fewer triangles and 9.5 dB worse appearance.

## Four must-not-break properties — every written output

G1 glazing `clear/proven` **and** glass area retained 100.0% · G2 tyres
`Tyre_Rubber` baseColor 0.0275, black · G3 respray PASS (carpaint 100% moved;
tyres 0.0%, rims 0.8%, lamps 0.1%) · G4 validator **0 errors** · plus 30/30
NORMAL accessors, 30/30 node names, 11/11 material names on the re-read file.

## Negative controls — all three FIRED

* **NC1** over-decimated to 76,029 tri → PSNR 15.45 dB, appearance FAIL.
* **NC2** glazing geometry gutted to **2.5% of its area**, material table
  untouched → `glass_probe` still returns **clear / proven**, and
  geometry_retention FAILS. The probe's blind spot, demonstrated.
* **NC3** tyre primitives re-bound to `carpaint` → respray FAIL on the
  phantom-material line (`Tyre_Rubber` in the table, `<model-viewer>` reports it
  NOT LOADED).

## Load time — measured, not derived

Chromium + SwiftShader, desktop x86, CDP-emulated link, cache disabled, median of
3 cold loads. Decode is a LOWER BOUND for a phone; fps and VRAM NOT TESTED.

| candidate | wifi 50/20 | typical4G 8/100 | busy4G 3/200 | JS heap |
|---|---|---|---|---|
| draco 3.654 MB | 2.19 s (0.84 tx / 1.33 dec) | **4.87 s** (3.86 / 1.01) | 10.46 s (9.98 / 0.45) | 35.8 MB |
| dec30 1.792 MB | 1.49 s | 2.80 s | 5.33 s | — |
| dec20 1.286 MB | 1.24 s | 2.10 s | 3.82 s | 8.8 MB |
| cull30 1.669 MB | 1.24 s | 2.51 s | 4.91 s | 12.3 MB |

## Bucket — verified by LISTING each prefix

`car-meshes/staging/mobile/` — `glb/` 5 objects 12,055,712 B ·
`evidence/` 7 objects 2,370,366 B · `tool/` 5 objects 105,364 B ·
`MOBILE_GATE_rebound.json` 196,638 B · `FIDELITY_SWEEP.json` 1,017 B.

## Findings owned by other gates

* **Front tyres 183.2 / 189.6 mm in the air, 4.07° nose-up** on `car_rebound.glb`
  (world space, transforms applied). `car_merged.glb` measures 0.000 mm on all
  four — resolved there, and its budget numbers are identical (985,227 tri,
  30 nodes, 11 materials, 100% geometry).
  **`viewer_check.py` PASSES this car's `on_ground` check** because it tests the
  whole-model bbox min-Y, which is +0.3 mm. `mobile_metrics.tyreNodeMinY` is the
  per-tyre replacement.
* **Interior-shell z-fighting**: 5.73% of car pixels across 8 views are dark in
  the master and red paint with the `Interior` node removed. See
  `evidence/INTERIOR_ZFIGHT_PAIR.png`. It also shows up in the respray control as
  `Interior_Plastic` 11.8% and `Arch_Liner` 5.0% change on small samples.
* **There is no mobile serving path.** `platform/resolver/index.ts:217` serves
  `desktopGlbUrl` to every device; **1,042 of 1,043 approved catalogue entries
  have `mobileGlbUrl` identical to `desktopGlbUrl`**. Approved sizes: median
  10.1 MB, p90 34.0 MB, max 47.9 MB; 64.3% over 5 MB, 29.8% over 20 MB. 1,007
  entries carry colourVariants = 8,056 variant GLBs, sampled 8/8 within ±1% of
  base size.

## Corrections made in flight

1. The brief's "not grounded, tyres y −0.3067 / −0.3241" is node-LOCAL; the truth
   is front tyres ~185 mm in the AIR.
2. **Four respray instruments; three withdrawn**, each having produced a
   confident false failure — tone-mapped ID colours, a brightness threshold that
   caught specular highlights (masks overlapped 2.2×), and a camera-dependent
   phantom check that condemned two intact lamps at an end-on view. Mechanisms in
   commits `64d26c8` and the one after it.
3. Close-up cameras first unioned multiple nodes and framed the whole car; the
   lamp camera then sat inside the nose.
4. `hidden_face_mask()` keys on the MESH name, `apply_face_cull()` on the
   MATERIAL name.
