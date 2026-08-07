# PartField segmentation trial — 2026-08-07

**Question:** can PartField (via 3DAIGC-API, template `bb0j8jta3y`) rescue cars
scrapped because their body material covers wheels/trim, i.e. create the real
material split the render pipeline needs?

**Test asset:** the E53 X5 scrapped as F19/`7w2jvl6quxds-bmw X5` — cov 0.856,
mats 1, wheels demonstrably body-coloured on the audit sheet. Worst case in the
wave.

**Setup:** RunPod pod, RTX A5000 ($0.27/hr), image `fishwowater/3daigc-api-runpod`.
~50 min image pull, then `POST /api/v1/mesh-segmentation/segment-mesh`
(`partfield_mesh_segmentation`). 56 seconds per car per run, at any num_parts.

## Results

| num_parts | outcome |
|---|---|
| 12 | 46 jumbled meshes -> 12 parts. Wheels separated. Windscreen fused with front clip. |
| 20 | + door/rear glass clean, tyres clean. Windscreen still fused. |
| 32 | + roof rails, mirrors separate. **Windscreen STILL fused.** |

Renders: scratchpad `seg/x5_parts.png` (part view), `x5_rescued2.png`,
`x5_rescued3.png` (classified + resprayed red).

## VERDICT — FAILED THE AUDIT BAR (owner ruling, 2026-08-07)

The owner reviewed the rescued renders and ruled the rescue a FAIL, verbatim:
"windscreen lights grill painted so fail audit. Even the glass." That is the
per-car rubric applied correctly: the windscreen stays body-colour at any
num_parts, and the lights, grille and glass sit on the body material, so a
recolour paints them all. Wheels alone being fixed does not make a shippable
car. The apparent clean glass in the demo renders came from the trial's own
hand-written part classifier, not from a material split the pipeline could
trust.

Segmentation rescue is therefore NOT adopted. "Don't fix, just scrap" stands.
The sections below are the raw findings, kept for reference only.

## Conclusions

1. **The fatal defect is fixed.** Wheels/tyres stop being body. The exact
   failure that scrapped F04/F19/H005/P024 does not survive segmentation.
2. **Part classification is ours to do.** PartField returns unnamed geometric
   parts; a ~30-line bounds heuristic (ground contact + height + length share)
   correctly labelled wheels/glass/trim on attempt two. Face-level slope rules
   would improve it.
3. **The ceiling: geometry-fused windscreens.** Where the modeller made the
   glass continuous with the shell (no boundary edge), PartField never splits
   it, even at the 32-part maximum. A rescued car then shows a body-colour
   windscreen — not shippable premium. Needs a per-face pass (large sloped
   upper surfaces -> glass) on top of part labels; local CPU work, no GPU.
4. **Cost:** ~$0.004/car marginal once warm; the pull dominates (~$0.25). Total
   trial spend ~$0.60 across both pod attempts.

## Standing-rule note

This is a FIX pipeline. The owner's standing rule is "don't fix, just scrap";
adopting segmentation rescue at batch scale is therefore an owner decision, not
a default. If adopted, the 242-row heavy-flag pool and the older single-mesh
library cars become candidates rather than scrap.
