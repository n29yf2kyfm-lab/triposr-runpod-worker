---
type: "query"
date: "2026-08-25T21:13:05.456382+00:00"
question: "Did the PRESERVE slice work on the Yaris, and what is left?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["machine.py", "seg_assemble.py", "seg_boundary.py", "PRESERVE_PLAN.md"]
---

# Q: Did the PRESERVE slice work on the Yaris, and what is left?

## Answer

PARTIAL WIN 2026-08-25. machine.py (seg chain) is the RIGHT chain — seg_assemble already preserves the baked texture and renames body to carpaint; premium.py's construction stages were the destroyer. Slice result: badge/plate/grille texels SURVIVED (premium deleted them), glazing now genuinely transparent vs the input's baked sky reflections, glass_probe clear/proven/no-flat/no-alpha on the shipped file, GATES PASS. Labels: body 18.86%, glass 4.66% (in the 4-12% real-car band), wheel 1.61%, lamp 0.64%, unseen 74.23%. REMAINING DEFECT: label boundaries are RAGGED — the lamp class over-reaches onto wings/bonnet with jagged edges, glass leaves spill at the A-pillar. Exactly what ox predicted ('no label QA; misprojected boundary reproduces the torn symptom by another mechanism'). Fix = the Phase 0.5 label-QA gate + boundary refinement, NOT more construction.

## Outcome

- Signal: useful

## Source Nodes

- machine.py
- seg_assemble.py
- seg_boundary.py
- PRESERVE_PLAN.md