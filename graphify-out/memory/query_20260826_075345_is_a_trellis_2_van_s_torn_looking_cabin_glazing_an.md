---
type: "query"
date: "2026-08-26T07:53:45.214787+00:00"
question: "Is a TRELLIS.2 van's torn-looking cabin glazing an aperture or a surface?"
contributor: "graphify"
outcome: "corrected"
correction: "My FIRST measurement said 265,972 boundary edges and I almost reported the van as shredded. That was the split-vertex trap already in CLAUDE.md — a GLB stores 3 unique verts per face, so an unwelded boundary-edge count is meaningless. ALWAYS coordinate-weld before any topology count."
source_nodes: ["glass_stage.py", "geom_audit.py"]
---

# Q: Is a TRELLIS.2 van's torn-looking cabin glazing an aperture or a surface?

## Answer

A SURFACE. Measured 2026-08-26 on the TRELLIS.2 Ford Transit Custom: after a coordinate-quantised weld (1e-5 x diag) the mesh has ZERO boundary edges — 244,052 welded verts, 492,240 faces, watertight. The render shows what looks like a torn window full of black debris; it is crumpled, self-intersecting CLOSED skin, not an opening. Same behaviour CLAUDE.md records for Hi3DGen ('the skin wraps THROUGH the window apertures into a modelled cabin — watertight, 0 boundary loops. Glass must be CONSTRUCTED, never detected'). Consequence: glass_stage CAN attach because it works on labelled faces not apertures, but there is nothing to fit a pane INTO — the pane must be constructed over the labelled region. The real risk is whether seg labels the crumpled region as glass at all.

## Outcome

- Signal: corrected
- Correction: My FIRST measurement said 265,972 boundary edges and I almost reported the van as shredded. That was the split-vertex trap already in CLAUDE.md — a GLB stores 3 unique verts per face, so an unwelded boundary-edge count is meaningless. ALWAYS coordinate-weld before any topology count.

## Source Nodes

- glass_stage.py
- geom_audit.py