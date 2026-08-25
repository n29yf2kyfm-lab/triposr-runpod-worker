---
type: "query"
date: "2026-08-25T22:47:37.112915+00:00"
question: "What is the grey blob on the Yaris front-left corner?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["eyeball_views.py"]
---

# Q: What is the grey blob on the Yaris front-left corner?

## Answer

A SOURCE defect in the raw Pixal3D mesh, not machine-introduced — proved by rendering input and output at the same camera: the same sphere sits on the front-left bumper corner in BOTH. Only visible once the eyeball sheet went from 1000px to 1200px, which is itself the lesson: the 1000px sheets had been hiding it. The machine does render it flatter (partly reclassified off carpaint) so it reads slightly more conspicuously, but the geometry is the generator's. Fix belongs to sourcing/regeneration, not the material chain.

## Outcome

- Signal: useful

## Source Nodes

- eyeball_views.py