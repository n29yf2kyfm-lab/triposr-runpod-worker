# GLB INTEGRITY GATE — Stages 1-6 (diagnosis + repair agent)

SOURCE (never modified): scratchpad/integrity/SOURCE_LOCKED/GOLF_ALL_GATES_SOURCE.glb
sha256 400d994a9fd034cc55d64cf340ec70eedb0d5fa93c188e739da03a787b21084f  (VERIFIED at start)
Bucket prefix: car-meshes/staging/integrity/

## STATUS
- [x] Stage 0 (coordinator) — validator 0 err / 0 warn / 1 info / 273 hints. 83 nodes, 107 prims, 22 mats.
- [ ] Stage 1 — automated integrity diagnosis -> evidence/integrity_before.json   IN PROGRESS
- [ ] Stage 2 — wheel inconsistency
- [ ] Stage 3 — body geometry
- [ ] Stage 4 — glass / apertures
- [ ] Stage 5 — interior containment
- [ ] Stage 6 — rear quarter

## OPEN FINDINGS HANDED OVER BY STAGE 0
1. TRIANGLE DELTA 928 (file 888,807 vs Blender 887,879) — mechanism NOT yet explained.
2. GROUND: world z-min -0.004587 m, and it is NOT a tyre. Object unidentified.

## LOG
- start: source sha verified, Blender 4.5.12 present, branch claude/lovable-connection-ki7jch, all 4 creds present.
