# TRELLIS material-split (multi-view Grounded-SAM back-projection)

Turns a single-mesh TRELLIS car GLB (one fused material, glass/wheels baked into
the body texture) into a **recolourable** GLB with separate `body`, `glass` and
`trim` materials — so DVLA colour swaps land cleanly on paint only, glass is
see-through, and wheels/interior are never painted.

This is an **offline gap-filler** for cars with no CC-BY sourced model. It fixes
*materials*, not TRELLIS's soft *geometry*, so it never goes on the serving path.

## Pipeline (CPU does the 3D, GPU does only the 2D masks)
```
render_views.py   Blender: clean geometry (merge/loose/normals), export cleaned.glb,
                  render 15 ring views, dump per-face projection + occlusion.
masks_and_vote.py Grounded-SAM masks per view (GSAM_EP set) or classical HSV
                  fallback -> occlusion-aware vote fused with a geometry prior
                  -> per-face labels. Unseen interior faces -> trim (neutral
                  behind glass). SAM masks cached to <work>/gmask_*.png.
assign_materials.py Blender: smooth + hole-fill labels, build body/glass/trim
                  materials, optional flat paint, export recolourable GLB.
```

Run it all:
```
GSAM_EP=<runpod endpoint id> RUNPOD_KEY=<key> \
  segment.sh raw_trellis.glb out_recolourable.glb
```
Then the normal render/ingest path recolours the named `body` material per DVLA
colour (bake_colour.py) exactly as it does for sourced models.

## Grounded-SAM endpoint
GPU worker in `../groundedsam/` (Grounding DINO + SAM, Apache-2.0/UK-safe). It is
parked at `workersMax 0` (scale-to-zero, £0 idle). To run a batch: bump the live
render endpoint 10->9 and gsam 0->1 (10-worker account cap), segment, then
restore. Without `GSAM_EP` the pipeline falls back to the classical HSV masker.

## Known limits (measured, not guessed)
- **Body, wheels, side glass: premium.** Uniform recolour, distinct window panes
  on SAM's crisp boundaries, wheels excluded with calipers intact.
- **Raked windshield/backlight: imperfect.** Grounding DINO can't mask a
  foreshortened screen from the ring and doesn't recognise glass from overhead,
  so the windscreen speckles from the front-3/4. It reads clean from the side /
  hero turntable angle. This is a ceiling of segmenting soft single-mesh geometry
  from renders — the durable fix is a sourced model, which the library prefers.
