# VERIFIER CHECKPOINT — Stages 7/8/9

Agent: INDEPENDENT glTF QA VERIFIER. Owns Stages 7, 8, 9.
Working dir: `.../scratchpad/integrity/verify/` — never enters `.../integrity/work/`.

## Status
- 18:55 Source sha256 re-verified OK: `400d994a...b21084f` (25,684,968 bytes).
- 18:55 Blender 4.5.12 LTS present at /usr/local/bin/blender. Disk 9.0 GB free.
- 18:55 Stage 0 evidence read. Baseline: validator 0/0/1/273; 83 nodes/83 meshes/107 prims/22 mats/0 tex/0 cams; 0 negative scales; world z-min -0.004587 m; unexplained 928-tri delta.
- BUILDING RIGS on the locked source (baseline column) while the repair agent works.

## Next
1. audit.py — full integrity audit (Blender), transformed-vertex measurement.
2. neutral_mats.py — Stage 7 diagnostic material set + reveal-not-conceal diff.
3. cameras.py — Stage 8 eight canonical cams, world-direction assertion, occupancy.
4. controls.py — injected negative controls for every check.
5. Baseline run on SOURCE_LOCKED -> evidence/*_before.json
