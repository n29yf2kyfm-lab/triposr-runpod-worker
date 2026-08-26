---
type: "query"
date: "2026-08-26T06:28:12.698027+00:00"
question: "What did testing a function against ALL its inputs catch that the happy path missed?"
contributor: "graphify"
outcome: "corrected"
correction: "Test a new function against every input class before believing it, including the boundary/degenerate ones. Both bugs sat on paths the happy-path test never reached."
source_nodes: ["eyeball_views.py", "seg_boundary.py"]
---

# Q: What did testing a function against ALL its inputs catch that the happy path missed?

## Answer

Two real bugs in one session, both in code I had just written and believed correct (2026-08-26). (1) _pick_device: EYEBALL_DEVICE=OPTIX returned CPU SILENTLY because the early return on missing cycles prefs skipped the notice that only existed on the loop fall-through — asking for a backend and not getting it looked like success. (2) majority_smooth: gated on total>=3 neighbours, so a tooth on a mesh boundary or corner has only 2 and was never cleaned — 1 of 6 planted teeth survived. Both found by a table test over every input, not by the one case I had in mind.

## Outcome

- Signal: corrected
- Correction: Test a new function against every input class before believing it, including the boundary/degenerate ones. Both bugs sat on paths the happy-path test never reached.

## Source Nodes

- eyeball_views.py
- seg_boundary.py