# CHECKPOINT — SIX-GATE MERGE (build_golf.py) — in flight

Agent: MERGE COORDINATOR. Branch `claude/lovable-connection-ki7jch`.
Scratchpad: `/tmp/.../scratchpad/build`. Tools: `pipeline/machine/buildstages/`.
Bucket target: `car-meshes/staging/final/`.

## DONE
* **cabin gate tools RECOVERED into git** (`pipeline/machine/cabin/`). The brief said
  all six gates' tools are in git; cabin's were NOT — bucket only (`staging/cabin/tools/`).
* `buildstages/glbmeas.py` — pure-bytes measurement (no trimesh, so the instrument
  cannot alter what it measures). Reproduces every published figure independently on
  `car_rebound.glb`: sha 5380761c…, 985,227 faces, `Glass_Windscreen` 0.162244 m²,
  `Tyre_Rubber` 0.02745, tyre-node world minima FL +183.2 / FR +189.6 / RL +0.3 / RR +14.7 mm.
* `buildstages/render.py` — locked-camera Cycles rig (CPU, no OIDN, Standard transform,
  own DONE marker, frames deleted first). **az 270 = FRONT, az 090 = REAR confirmed by render.**
* `buildstages/gates.py` — the must-not-break panel + 5 injected negative controls.
  **ALL FIVE FIRE; base clean.** Notably `glass_cut` reproduces the documented blind spot:
  glazing geometry cut to 1.1% of area, `glass_probe` STILL clear/proven → only the paired
  area figure catches it.
  CORRECTION recorded in code: I predicted `tyre_bound_to_paint` would be caught by the
  respray gate. It was NOT (a material bound to nothing owns no pixels); the binding half
  of `tyres_black` caught it. Respray gate now also requires Tyre_Rubber+glass present.

## HARD JOIN — DECIDED, on measurement
`rear_v3.glb` (Gate 4) and `car_rebound.glb` are **the same car in the same world frame**:
identical bbox min, identical height, tail profile agreeing to <2 mm at every height
sampled (the 16.8 mm at y=0.375 and 4.4 mm at y=0.875 are Gate 4's constructed plate/lamp
solids standing proud). So rear2's world-space band constants transfer directly.
DECISION: **REPLAY rear2's operations on the rebound lineage**, not transplant.
Reason: rear_v3 carries Gate 4's material table (no KHR extensions at all, textured
carpaint metallic 1.0) and has NO per-corner wheel nodes, so `merge_op` could not pose it.

## NEXT
build_golf.py orchestrator + stages: glass → front(v7) → rear(replay) → cabin → skin →
pose → finish → mobile → sheet. Chunk+upload to `staging/final/` the moment the GLB validates.
