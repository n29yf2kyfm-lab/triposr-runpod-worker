# CHECKPOINT — REAR GATE v2 (rear surfaces) — in flight

Agent: REAR GATE v2. Branch `claude/lovable-connection-ki7jch`.
Scratchpad: `/tmp/.../scratchpad/rear2`. Tools: `pipeline/machine/rear2/`.
Bucket: `car-meshes/staging/rear_v2/`.

## INPUT CHOSEN
`car-meshes/staging/gate4_rear/glb/rear_v3.glb.part_*` (65,349,280 B,
sha256 734542a2e302d25376780d2a89195d441a3d5f05e4366dda657c640660447862 — matches
Gate 4's manifest). Chosen because acceptance criterion 4 requires Gate 4's four
lamp solids intact, and they exist ONLY in this file; `car_rebound` / `car_merged`
carry the ORIGINAL MELT under the names TailLamp_L/R.
Risk accepted: rear_v3 has Gate 4's material table (carpaint textured, metallic 1.0)
rather than Gate 7+8's rebind, and it is NOT grounded/de-pitched.

## VERIFIED CORRECTIONS TO THE BRIEF
* `rear_v3.glb` node transforms are ALL EXACTLY IDENTITY — max |world-local| =
  0.000000000 over every vertex, 22/22 nodes. Local==world on this file, so the
  transform trap does not apply here (it does apply to car_rebound/car_merged).
* Tyre contact heights on rear_v3, world: RL +11.5 mm, FL +193.8, FR +204.4 —
  front up, rear down, nose UP. The brief's "tyres y -0.3067/-0.3241" is wrong
  for this file too. Grounding is another gate's scope; recorded only.
* az 090 = straight rear CONFIRMED by render (tailgate, screen, tail lamps).

## DELIVERABLE (current)
`car-meshes/staging/rear_v2/glb/rear2_v4.glb.part_000..003` + `MANIFEST_rear2_v4.glb.txt`
66,485,700 B. Uploaded AND verified by listing; part bytes total matches the local file
exactly. v1 and v3 parts deleted so the prefix is unambiguous.
Report at `car-meshes/staging/rear_v2/REAR2_REPORT.md`; 32 measurement JSONs at
`car-meshes/staging/rear_v2/measurements/`.

## MEASURED ON THE DELIVERED FILE (v4)
* 26 named meshes, 1,046,660 faces. `gltf-transform validate`: 0 errors, 0 warnings,
  0 infos (HINTs only, as on the source).
* Re-read of the WRITTEN file: 26/26 NORMAL, 0 zero-length, 0 non-unit, 0 loose verts,
  0 zero-area faces. Fresh Blender process: 26 objects, 1,045,089 tris, 0 loose.
* glass_probe clear / PROVEN, flat_shell False, alpha_shell False.
* Provenance (with negative control): rebuilt panels 0.00% coincident with any source
  vertex; renamed melt 100.00% at 0.000 mm.
* Waviness, same estimator both sides: rebuilt hatch 0.23 mm rms, bumper 0.12 mm rms,
  against melt 2.39 / 2.29 mm rms.
* Melt within 100 mm behind the new skin: hatch 1.92%, bumper 3.61% (was 97.5-100%).
* Holes, 15 directions, 29,040 rays: 36 rays lost the surface entirely (0.162%).
  Negative control fires: injected 90 mm through-hole moves 3.26% -> 4.50%.
* Gate 4 lamps: hatch units 0.00% buried, min clear +4.65/+1.86 mm; outer units and both
  quarters byte-identical to source (0.0 micron).

## RESIDUALS (in the report, not hidden)
* Tailgate rebuilt to y=1.300 only; above it and at the two upper D-pillar corners the
  melt survives as `Rear_Upper_Legacy_Melt` (the +z corner is a cliff where x(y,z) has no
  measurable value).
* Rebuilt bumper's +z LOWER corner 79 mm short of the source outline at y=0.26.
* `Rear_Valance` below y=0.23 unchanged torn melt (inherited, out of scope).
* Car not grounded/de-pitched — merge operator must re-apply grounding on top of this file.
