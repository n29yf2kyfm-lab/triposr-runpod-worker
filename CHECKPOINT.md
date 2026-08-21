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
`car-meshes/staging/rear_v2/glb/rear2_v3.glb.part_000..003` + `MANIFEST_rear2_v3.glb.txt`
66,536,096 B. Uploaded AND verified by listing the prefix; part bytes total matches
the local file exactly. v1's parts were deleted so the prefix is unambiguous.

## MEASURED ON v3
* 26 named meshes. glass_probe clear / PROVEN, flat_shell False, alpha_shell False.
* glb_assert on the WRITTEN file: 26/26 NORMAL, 0 zero-length, 0 non-unit,
  0 loose verts, 0 zero-area faces.
* Provenance, with its negative control: every rebuilt panel 0.00% coincident with a
  source vertex; every inherited/renamed component 100.00% at 0.000 mm.
* Panel waviness (same estimator as the melt it replaces): hatch 0.23 mm rms,
  bumper 0.12 mm rms, against the melt's 2.39 / 2.29 mm rms.
* Gate 4's lamps: hatch units 0.00% buried on the rebuilt skin (min clear +4.7/+1.9 mm);
  outer units and both quarters byte-identical to source (0.0 micron).

## OPEN
* gltf-transform validate on the 66 MB file is very slow under six-agent CPU
  contention; not yet completed.
* Renders in flight; hole probe being re-run after its control exposed two flaws in it.
* KNOWN RESIDUAL: rebuilt bumper's +z LOWER corner falls up to 79 mm short of the
  source outline at y=0.26 (envelope clamp + outline theta range), leaving legacy melt.
