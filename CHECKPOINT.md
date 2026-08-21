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

## STATE
* v1 built, assembled, chunked and UPLOADED to `staging/rear_v2/glb/`
  (rear2_v1.glb.part_000..003 + MANIFEST, 68,018,280 B, listing verified, bytes match).
* glass_probe on v1: clear / proven, flat_shell False, alpha_shell False.
* Provenance test PASSED with its negative control: rebuilt panels 0.00% coincident
  with source vertices; renamed melt (`Rear_Upper_Legacy_Melt`) 100.00%.
* v2 pending: sliver-row fix in the aperture grid.

## OPEN
* gltf-transform validate on the 68 MB file not yet completed (slow, CPU contended).
* Render batch 1 in flight (cavity proof, shaded/matid/clay, blue respray control).
