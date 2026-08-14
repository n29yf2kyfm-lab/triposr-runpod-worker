# Vision — software a professional architect can use

Stated by the owner, 2026-08-14: the goal is software that does what a
professional architect does — end to end, to a standard where the
outputs stand on their own. Every module is judged against that bar.

## The whole job, one pipeline

    address → correct house verified → measured model (GLB/OBJ/IFC)
    → design (extension or new build) gated by buildability + regs
    → services designed (heat, ventilation, electrics)
    → drawings an architect would sign (plans, elevations, sections,
      schedules, title blocks, true scale)
    → photoreal visuals a homeowner can't tell from a photo
    → bill of quantities and a priced, buildable package

## Standing rules (the owner's standards)

1. MEASURED, NEVER IMAGINED. AI may paint pixels; it never decides a
   dimension. Every number traces to geometry or a cited document.
2. The code never argues with the document it came from — primary
   sources in building/docs govern; corrections lists are work orders.
3. Refuse to render the unbuildable. The gate (buildable.check + regs)
   runs before anything is shown or exported.
4. Honest uncertainty: estimates say ESTIMATE, assumptions are tagged,
   waste is explicit, "the chart governs" where a chart governs.
5. Extension shown WITH its existing house; context always modelled.
6. The bar for visuals: a homeowner cannot tell it from a photo.

## Knowledge base (learned from primary sources, dated)

docs/UK_COMPLIANCE_KNOWLEDGE.md — regs A–S, planning, councils, RIBA.
docs/DRAWING_CONVENTIONS.md — how drawings are actually drawn.
docs/DESIGN_LANGUAGE.md — Georgian/vernacular pattern rules, archviz.
docs/MATERIALS_AND_COST.md — materials, merchants, build economics.
docs/GROUND_AND_FLOW.md — soil, foundations, site, space syntax.
docs/ESTIMATING_RATES.md — every quantity rate with its source.

## Current build queue (from the corrections/work orders)

1. Part O completion (room limits, cross-vent test, free areas).
2. flow.py — space-syntax metrics on the circulation graph.
3. Drawing issue: dimension lines, title block, sections, schedules,
   true-scale sheet export.
4. groundworks.py — foundation selector + muck-away quantities.
5. materials.py — bond/skin/covering catalogue driving viewer+pricing.
6. NDSS + M4(2) rule pack; climate lookup for design temperatures.
7. Georgian facade mode; street-level and golden-hour presets.

A professional-grade claim is earned per module: coded from the primary
source, tested against longhand arithmetic, and cross-checked against a
real-world anchor (e.g. 3-bed ≈ 8,000 bricks). Anything that hasn't
earned it is labelled an estimate.
