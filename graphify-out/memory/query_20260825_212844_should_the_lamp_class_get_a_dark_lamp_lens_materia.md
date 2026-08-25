---
type: "query"
date: "2026-08-25T21:28:44.269309+00:00"
question: "Should the LAMP class get a dark Lamp_Lens material override on a generated car?"
contributor: "graphify"
outcome: "corrected"
correction: "Fixing the lamp boundary SHAPE was treating the symptom. The real question was whether the class should be overridden at all. Ask 'does the input already have this?' before improving how a class is constructed."
source_nodes: ["seg_assemble.py", "seg_boundary.py"]
---

# Q: Should the LAMP class get a dark Lamp_Lens material override on a generated car?

## Answer

NO on a TEXTURED generated car — keep the baked texture, same rule the RIM already had. Measured on the Yaris 2026-08-25 across three gate-passing renders: lamp overridden with a raw projected boundary (ragged dark band across the nose), lamp overridden with the new stencil (better, still a dark band), lamp left TEXTURED (reads as the input's own lamp units, clean wings, no spill). Textured won clearly. Lamp_Lens is right for a MELT car where lamps are undifferentiated geometry; on a baked albedo that already carries headlamp internals it replaces real detail with a flat patch — the same error premium.py's 356-face grille made. LAMP_FLAT=1 restores the override. Kept as its OWN node, not merged into carpaint, so a per-variant respray rebake of carpaint can never paint the headlamps.

## Outcome

- Signal: corrected
- Correction: Fixing the lamp boundary SHAPE was treating the symptom. The real question was whether the class should be overridden at all. Ask 'does the input already have this?' before improving how a class is constructed.

## Source Nodes

- seg_assemble.py
- seg_boundary.py