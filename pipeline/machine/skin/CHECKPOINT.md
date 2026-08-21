# CHECKPOINT — double-skin / speckle task (2026-08-21)

STATUS: **COMPLETE.** Deliverables are chunked, uploaded and verified by prefix
listing; a round-trip download reassembles byte-identically.

## What was delivered

| bucket path | what |
|---|---|
| `car-meshes/staging/skin/glb/car_deskin.glb.part{000,001}` | **primary** — grounded (`car_merged.glb`) + de-speckled. sha256 `2029b2ecdd2e6ffa984ba6c5915ef8f8e76b5a6493aeb77af6661234ec780095`, 28,709,336 bytes |
| `car-meshes/staging/skin/glb/car_deskin_rebound.glb.part{000,001}` | same fix on `car_rebound.glb` (the base my before/after evidence uses) |
| `car-meshes/staging/skin/glb/MANIFEST.txt` | part order, per-part sha256, reassembly command |
| `car-meshes/staging/skin/car_deskin_mobile.glb` | Draco mobile export, 3.68 MB |
| `car-meshes/staging/skin/SKIN_DIAGNOSIS.jpg` | the 6-render diagnosis chain |
| `car-meshes/staging/skin/SKIN_EVIDENCE.jpg` | before / after / clay floor / respray control |
| `car-meshes/staging/skin/CMP_GROUNDED.jpg`, `SKIN_ZOOM_BONNET.jpg` | matched pairs |
| `car-meshes/staging/skin/{deskin_final,deskin_rebound}.json`, `hole_test.log`, `HYPOTHESIS.md` | reports |

## Headline numbers

* Speckle, locked camera, matched pair on the grounded base
  (`car_merged.glb` → `car_deskin.glb`), dark specks as % of region:
  **roof 5.62% → 0.36%** (clay floor 0.49%), **bonnet 3.77% → 0.96%** (floor 0.45%),
  cowl 3.86% → 2.88% (floor 0.93%), flank 0.17% → 0.22% (floor 0.19%).
* `Interior_Plastic` visible on the body: **16,162 → 9,540 px (−41%)**;
  `carpaint` **+6,324 px**. Frozen materials move ≤ 8 px (AA noise).
* Geometry: face count **985,227 → 985,227**, area **63.630366 → 63.630366 m²**
  (Δ = 0.000000000), extents identical, **triangle multiset provably identical**,
  **0 new holes** across 15 ray directions, silhouette delta **0** in every one.
* Anti-parallel doubled-face census: **5.667% at 0.25 mm, unchanged** by the fix,
  because the fix touches no geometry — and that census is **not** the speckle
  (proven: its magenta diagnostic puts nothing on the bonnet or roof).

## Gates on `car_deskin.glb`

glazing `clear/proven`, BLEND alpha 0.161 + transmission 0.92 + IOR 1.45,
`flat_shell` False, `alpha_shell` False · tyres `Tyre_Rubber` 0.027 on all four ·
11/11 materials bound, 0 dead · blue respray: carpaint moves d=147.8, tyre 2.5,
rim 6.8, glass 17.7, lamps ≤ 8.5 · Khronos validator **0 errors, 0 warnings**
(2 pre-existing infos, 117 pre-existing hints) · Draco mobile 3.68 MB ·
NORMAL accessors on 57/57 primitives.

## Open / not done

* The **cowl/scuttle** keeps a residual dark blotch (2.88% vs a 0.93% clay floor).
  It is a connected dark network larger than the island threshold, plus the
  windscreen and A-pillar glass edge inside that crop. Absorbing it would need a
  rule that can tell a mislabelled network from a genuine black cowl panel; I did
  not build one, because on a real Golf that panel IS black and the owner's rule 1
  forbids painting over anything I have not proved is wrong.
* The doubled-face census (5.667% @0.25 mm, 1.07 m²) is left in place. It is
  dominated by `Interior`↔`Interior` inside the cabin and by the two sides of thin
  structure. Deleting from it was tried (`deskin.py`) and measurably made the
  render worse.

## Corrections I made mid-run

1. Withdrew my own v1 doubling detector (nearest-centroid) — it under-reports ~5×.
2. Withdrew the whole deletion route after building it, on measurement.
3. Corrected the brief's diagnosis (double skin / z-fighting → speckled material
   partition on one surface).
4. Confirmed the coordinator's grounding correction independently and switched to
   the grounded base for the primary deliverable.
