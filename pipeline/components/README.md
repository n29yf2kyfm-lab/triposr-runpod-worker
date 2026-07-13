pipeline/components/*.glb  # drop-in high-quality component assets (wheel/mirror/light/grille/badge/handle/interior/engine_bay)

Provide free/licensed GLBs named by slot:
  wheel.glb  mirror.glb  headlight.glb  taillight.glb  grille.glb
  badge.glb  handle.glb  interior.glb  engine_bay.glb
process_candidate.py imports and swaps in any that exist; missing ones keep the
TRELLIS.2-generated part and are flagged. These are the reusable assets that lift
a generated body to premium — sourced once, reused across every car.
