# GLB INTEGRITY GATE — Stages 1-6 (diagnosis + repair agent)

SOURCE (never modified): scratchpad/integrity/SOURCE_LOCKED/GOLF_ALL_GATES_SOURCE.glb
sha256 400d994a9fd034cc55d64cf340ec70eedb0d5fa93c188e739da03a787b21084f  (VERIFIED at start)
Bucket prefix: car-meshes/staging/integrity/

## STATUS
- [x] Stage 0 (coordinator) — validator 0 err / 0 warn / 1 info / 273 hints. 83 nodes, 107 prims, 22 mats.
- [x] Stage 1 — DONE. evidence/integrity_before.json (83 objects, 12 s). 10/10 negative controls fire.
- [~] Stage 2 — DIAGNOSED. Repair pending.

### STAGE 2 ROOT CAUSE (measured + rendered, not inferred)
The four wheels are FOUR DIFFERENT MESHES of two different qualities:
  RIGHT side (-Y): Wheel_FR_*, Wheel_RR_*  -> clean 10-SPOKE ALLOYS
  LEFT  side (+Y): Wheel_FL_*, Wheel_RL_*  -> TORN MELT, no spokes, large ragged holes
Renders: renders/corner_{FL,FR,RL,RR}/, renders/wheels_before/.
RULED OUT, each with a measurement:
  * negative scale / mirroring - 0 objects, 0 mirrored determinants (Stage 0 + Stage 1)
  * inverted normals          - rims report 0 inverted components
  * backface culling          - cullON vs cullOFF moves mean sRGB by <0.1; nothing vanishes
  * missing materials         - all four rims carry Rim_Alloy, 0 empty material slots
  * intersecting tyre/rim     - present but not the mechanism; the faces are ABSENT under cullOFF
CONFIRMED CAUSE: defective SOURCE GEOMETRY on the left pair. Not a transform, not a
material, not a render artefact.

### INSTRUMENT DEFECT FOUND AND WITHDRAWN
`material.use_backface_culling` DOES NOTHING IN CYCLES. test_culling.py: all four
cells 0.44696 with the flag; the shader Geometry->Backfacing + Transparent mix gives
0.00033 for the culled cell. My FIRST wheels cull-pair was rendered off that flag and
was therefore a check that could never fire -- WITHDRAWN and re-rendered.
Also fixed in the same instrument: the control's own lit/dark threshold was guessed at
0.5 while a lit frame measures 0.447, so the control reported "culling is broken" on a
working culler. Threshold now calibrated against the measured lit reference.
- [ ] Stage 3 — body geometry
- [ ] Stage 4 — glass / apertures
- [ ] Stage 5 — interior containment
- [ ] Stage 6 — rear quarter

## OPEN FINDINGS HANDED OVER BY STAGE 0 — BOTH RESOLVED
1. TRIANGLE DELTA 928 = 4 index-degenerate + 924 DUPLICATE VERTEX-TRIPLES.
   Confirmed by THREE independent methods (coordinator binary parse; my gltf_facts
   index reader; my per-mesh file-vs-Blender diff). 4+924=928 exactly.
   Mechanism: BMesh refuses a 2nd face on a triple that already carries one, so
   Blender's importer DROPS it. Nothing is missing from the import — but the 924
   DO ship to the viewer and z-fight. Validator flags only 1 of the 928.
   Cluster: Interior 679, Arch_Liner 75, Underbody 56, wheels 81, rest small.
   -> REPAIR ITEM (dedupe index buffer, re-count after export).
2. GROUND z-min -0.004587 m OWNER = **Arch_Liner** (99,395 tris). All four tyres
   sit at z=0.000000. Grounding is CORRECT; the arch liner protrudes 4.587 mm
   through the contact plane. Stage 5 containment item, NOT a grounding fix.

## STAGE 1 HEADLINES (measured)
- 83 mesh objects, 22 materials, 0 cameras, 0 lights, 0 hidden, 0 images.
- 0 negative scales, 0 mirrored determinants, 0 objects outside vehicle bounds.
- ALL 83 objects have ZERO UVs (validator maxUVs=0 agrees). 0 empty material slots.
- 0 invalid texture refs (file has 0 textures / 0 images).
- boundary_edges 314,441 across 39,017 OPEN components -> the car is fragment soup.
- nonmanifold_edges 3,183 · inconsistent_winding_edges 180
- inverted_components 57 (2,418 faces) — 53 of them in `Interior`.
- loose_vertices 1 · loose_edges 0 · zero-area 0 · Blender-visible duplicate faces 0
  (that predicate CANNOT fire on an imported GLB — file-level counter is authority).
- self-intersection NOT TESTED on Arch_Liner / Body_Shell / Interior (over 40k cap).
- 247 inter-object intersecting pairs. Top: Body_Shell/Interior 2568,
  Arch_Liner/Body_Shell 2232, Glass_Backlight/Hatch_Inner 1722.
- WHEELS ARE FOUR DIFFERENT MESHES, not one instanced assembly:
  Rim tris FL 20211 / FR 24528 / RL 18447 / RR 20830
  Tyre tris FL 9264 / FR 9176 / RL 13813 / RR 12589
  Disc tris FL 3245 / FR 2612 / RL 1658 / RR 1546 ; NO hub, NO caliper nodes exist.
- Glazing nodes present: Glass_Windscreen, Glass_Side_L, Glass_Side_R,
  Glass_Quarter_L, Glass_Rear (187 tris), Glass_Backlight. NO Glass_Quarter_R.
  Plus `Body_Glass_Reverted` (10,108 tris) carrying carpaint — suspected
  body-coloured glazing, the documented glass_probe blind spot. Stage 4 item.

## LOG
- start: source sha verified, Blender 4.5.12 present, branch claude/lovable-connection-ki7jch, all 4 creds present.
