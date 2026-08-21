# GLB INTEGRITY GATE — Stages 1-6 (diagnosis + repair agent)

SOURCE (never modified): scratchpad/integrity/SOURCE_LOCKED/GOLF_ALL_GATES_SOURCE.glb
sha256 400d994a9fd034cc55d64cf340ec70eedb0d5fa93c188e739da03a787b21084f  (VERIFIED at start)
Bucket prefix: car-meshes/staging/integrity/

## STATUS
- [x] Stage 0 (coordinator) — validator 0 err / 0 warn / 1 info / 273 hints. 83 nodes, 107 prims, 22 mats.
- [x] Stage 1 — DONE. evidence/integrity_before.json (83 objects, 12 s). 10/10 negative controls fire.
- [x] Stage 2 — DIAGNOSED **and REPAIRED**. work/car_wheels_fixed.glb (bucket-backed).

### STAGE 2 REPAIR RESULT (verified on the EXPORTED file, validator PASS)
One approved assembly (donor FR: Tyre+Rim+Disc) instanced x4 by ROTATION ONLY.
  radius spread      0.000 mm      (identical BY CONSTRUCTION - shared mesh data)
  hub symmetry       0.001 mm front / 0.000 mm rear   (threshold 2 mm)
  tyre bottom        -0.000 mm all four               (threshold +-1 mm)
  toe / camber       -0.026 / -0.064 deg all four     (ZERO BY CONSTRUCTION)
  world determinant  +1.0000 all four, negative_scale FALSE all four
  validator          0 errors / 0 warnings / 0 infos / 0 hints (source: 1 info, 273 hints)
  KHR extensions     clearcoat + transmission + ior ALL PRESERVED through Blender export
  duplicate triples  924 -> 0 ; index-degenerate 4 -> 0   (the 928 delta, REPAIRED)
  triangles 887,879 -> 786,276. The -101,603 is EXACTLY the instancing win
  (12 wheel meshes -> 3 shared; 137,919 - 36,316 = 101,603, arithmetic checked).
  NOT lost geometry. File 25.68 MB -> 20.09 MB.
  HUB and CALIPER are ABSENT from the source and were NOT fabricated.
Visual: renders/wheels_after/ left pair now clean multi-spoke alloys.

### INSTRUMENT DEFECT #2 FOUND (Blender, this container)
`ob.matrix_world = numpy_matrix.tolist()` STORES THE TRANSPOSE. Proven with a
30 deg control: readback -30 deg, vertex (1,0,0) -> (0.866,-0.5,0). In the first
repair run this DOUBLED the donor's -3.43 deg camber to -6.98 deg instead of
cancelling it, and put the wheels 42 mm through the floor. NOTHING RAISED.
Fixed by `set_world()`, which transposes on the way in and ASSERTS the readback.

### ANGLE ESTIMATOR CALIBRATION (injection ladder on the real car, FR corner)
  camber |slope| 0.9824 (linear range 0.9688), residual rms 0.0134 deg -> FAITHFUL
  toe    |slope| 0.7739 full ladder BUT 1.0174 within +-1 deg, rms 0.0173 deg
         -> faithful near zero, DEGRADES beyond -1 deg. Stated, not hidden.
  Sign convention: rotation about +axis reports NEGATIVE. Magnitude is the
  instrument; a slope of -1 is faithful with an opposite label, not blind.
  ABSOLUTE accuracy on the SOURCE tyres is NOT +-0.1 deg: band-definition spread
  is toe 3.3-7.2 deg, camber 1.6-6.2 deg, because the tyres are 3.1-3.4 mm rms
  out of round. So on the source, toe/camber are NOT MEASURABLE at +-0.1.
  On the REBUILD they are exact by construction, and the residual is fit noise.

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
- [~] Stage 4 — glazing MEASURED (evidence/glass_audit_before.json)
    total surface 91.7446 m2 | glass 2.9594 m2 = 3.226% (catalogue band 1.0-13.0%, p10 2.62)
    Windscreen 0.98944 | Side_L 0.79029 | Side_R 0.76708 | Backlight 0.38770
    Quarter_L 0.01296 | Glass_Rear 0.01189
    ONE glass material, factor-transparent AND matching the worker's override
    regex -> glass_probe would say clear/proven, and the SHEET IS INADMISSIBLE
    for glazing. Verdict is paired with the AREA figure, per the standing rule.
    * NO Glass_Quarter_R node. NOT simply missing glass: Side_R spans x -0.729..1.152
      (1.88 m) against Side_L's -0.694..0.758 (1.45 m), so the right quarter is
      MERGED into Side_R. Areas 0.767 vs 0.803 (L side+quarter) = 4.5% apart.
      This is a node-PARTITIONING asymmetry, not absent glazing.
    * Glass_Rear vs Glass_Backlight overlap 99.71% of the shorter along X, same
      Z band -> Glass_Rear is 187 tris / 25 components / 0.0119 m2 of DEBRIS
      lying in the rear screen. Prime Stage 6 candidate.
    * Body_Glass_Reverted: 0.3291 m2 / 10,107 tris of `carpaint` in the greenhouse
      band (z 0.815-1.338, full car length). Named as a deliberate glass->body
      revert. Plausibly pillars/surrounds; FLAGGED for the eye, not asserted.
    * PER-DOOR separation: Side_L is ONE node (30 components) spanning both doors.
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
