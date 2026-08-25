---
type: "query"
date: "2026-08-25T19:29:03.962598+00:00"
question: "Where did the seg-labelled Yaris input (polished_f34r.glb) go?"
contributor: "graphify"
outcome: "corrected"
correction: "Purge only bucket-verified files: list the prefix and confirm the object exists before rm. Enforce upload-on-completion in the runner, not by discipline."
source_nodes: ["machine.py", "seg_boundary.py"]
---

# Q: Where did the seg-labelled Yaris input (polished_f34r.glb) go?

## Answer

DELETED un-uploaded during a disk purge at 96% full — violated the 'upload the artefact, not the evidence' rule. Rebuild via machine.py seg chain on car-meshes/pixal_test/pixal_golf.glb (which IS the Yaris — misnamed file). ~30 min CPU.

## Outcome

- Signal: corrected
- Correction: Purge only bucket-verified files: list the prefix and confirm the object exists before rm. Enforce upload-on-completion in the runner, not by discipline.

## Source Nodes

- machine.py
- seg_boundary.py