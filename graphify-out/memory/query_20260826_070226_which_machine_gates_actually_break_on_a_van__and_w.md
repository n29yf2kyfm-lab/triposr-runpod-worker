---
type: "query"
date: "2026-08-26T07:02:26.394643+00:00"
question: "Which machine gates actually break on a van, and which only look like they will?"
contributor: "graphify"
outcome: "corrected"
correction: "Do not predict which gate breaks on a new body style — measure the body against the gate. I named geom_audit as the van-breaker and it passes all three vehicles; the actual breaker was a pane-count floor two stages away."
source_nodes: ["glass_stage.py", "geom_audit.py"]
---

# Q: Which machine gates actually break on a van, and which only look like they will?

## Answer

MEASURED 2026-08-26 on two real vans (Sprinter, Renault Master) against the Yaris as car control. geom_audit does NOT break: Sprinter h/l=0.344 tob=1.000, Master h/l=0.444 tob=0.809, Yaris h/l=0.420 tob=0.793 — all verdict OK. The tob=1.000 confirms a van's near-constant-width box body but it sits well under the >1.20 wide-top/cage reject, so my prediction that geom_audit would reject vans was WRONG. The real breaker is glass_stage's pane floor: '4 <= len(panes) <= 12' refuses a PANEL VAN, which correctly has THREE panes (windscreen + one door window per flank). Fixed by encoding the floor's own stated intent — catch an unsplit blob — as 'at least one side pane per flank plus >=2 total', which is body-agnostic. Table-tested 11/11 including blob, soup, half-merged, pickup, 5-door and the Yaris L3/R4 regression; only the panel van changes verdict.

## Outcome

- Signal: corrected
- Correction: Do not predict which gate breaks on a new body style — measure the body against the gate. I named geom_audit as the van-breaker and it passes all three vehicles; the actual breaker was a pane-count floor two stages away.

## Source Nodes

- glass_stage.py
- geom_audit.py