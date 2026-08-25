---
type: "query"
date: "2026-08-25T21:45:24.216346+00:00"
question: "What caused the dark smudge along the bonnet lip on the machine's Yaris?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["seg_boundary.py", "seg_assemble.py", "seg_masks.py"]
---

# Q: What caused the dark smudge along the bonnet lip on the machine's Yaris?

## Answer

WHEEL label on the NOSE. Found by rendering a colour-coded matID map (ox's Phase 0.5 gate) rather than guessing: an orange wheel band sat across the bonnet lip. seg_assemble splits wheel into tyre/rim by radius, so a stray wheel face there becomes Tyre_Rubber and renders as black rubber on white paint. DINO's wheel/tire prompts match the grille slat pattern and the round badge; nothing questioned it because WHEEL had no zone rule while LAMP did. FIX: distance-from-hub eviction in seg_boundary — locate the four hubs from unambiguously low wheel faces (yf<0.35), evict wheel label further than 1.25x the p95 seed distance. Evicted 638 of 14,801 (4.3%), 625 of them at xf>0.9. A HEIGHT cut was measured and rejected: 99% of real wheel faces are below yf 0.473, but cutting at 0.45 also clips 2.6% off the tops of the real tyres.

## Outcome

- Signal: useful

## Source Nodes

- seg_boundary.py
- seg_assemble.py
- seg_masks.py