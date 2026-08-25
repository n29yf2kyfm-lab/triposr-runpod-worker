---
type: "query"
date: "2026-08-25T19:29:03.826966+00:00"
question: "Is the premium machine chain safe to run on a detailed generated car (Pixal3D class)?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["premium.py", "materials_pass", "front_kit.py", "PRESERVE_PLAN.md"]
---

# Q: Is the premium machine chain safe to run on a detailed generated car (Pixal3D class)?

## Answer

NO — measured net-negative on the Yaris XP130 (2026-08-25). materials_pass flattens to 0 textures (deletes badge/plate/grille identity), front/rear kits paste placeholder primitives (Grille_Upper 356 faces, Number_Plate 2 faces) over a detailed 324k-face nose, constructed glass panes under-reach apertures (torn DLO). Keep: component wheels, exact track/wheelbase, ground contact, transparent named glass. Fix plan: pipeline/machine/PRESERVE_PLAN.md (ox-reviewed). Evidence: car-meshes/staging/yaris_premium/YARIS_3WAY.png

## Outcome

- Signal: useful

## Source Nodes

- premium.py
- materials_pass
- front_kit.py
- PRESERVE_PLAN.md