---
type: "query"
date: "2026-08-25T19:29:03.893657+00:00"
question: "How should respray/colour variants work on a textured generated car?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["colour_variants.py", "recolour_audit.py", "PRESERVE_PLAN.md"]
---

# Q: How should respray/colour variants work on a textured generated car?

## Answer

REBAKE PER VARIANT, never factor-multiply (ox review 2026-08-25): baseColorFactor multiplies ALL carpaint texels so badge/plate decals share UV space and a red respray turns chrome pink; multiplication cannot exceed texel luminance. Rasterise the carpaint CLASS MASK into UV space, recolour those pixels in the albedo PNG, ship one variant GLB per colour, factor stays (1,1,1). Matches the existing 8-variant-file serving model. Glass must be a FLAT override (no texture) or baked sky shows through BLEND as milky grey.

## Outcome

- Signal: useful

## Source Nodes

- colour_variants.py
- recolour_audit.py
- PRESERVE_PLAN.md