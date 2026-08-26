---
type: "query"
date: "2026-08-26T06:28:12.583772+00:00"
question: "Was the EEVEE 'verified by pixels' assertion actually valid?"
contributor: "graphify"
outcome: "corrected"
correction: "When asserting on pixels, mask to RGB. Alpha is constant on an opaque render and silently satisfies any range test."
source_nodes: ["install_blender.sh"]
---

# Q: Was the EEVEE 'verified by pixels' assertion actually valid?

## Answer

NO — the mechanism was wrong even though the conclusion was right. bpy img.pixels is interleaved RGBA and alpha is 1.0 on every opaque pixel, so min/max over the raw list is pinned at ..1.000 BY ALPHA. The quoted 'range=0.220..1.000' had a meaningless upper bound and a uniform grey frame would have passed. Measured after review: ALPHA is 1.000..1.000, RGB alone is 0.220..0.737. EEVEE does genuinely work (a separate PIL check showed 132 unique colours), but the assert was the exact silent-no-op class it was written to prevent. Fixed by masking px[0::n]+px[1::n]+px[2::n]. ALSO: the assert ran under LIBGL_ALWAYS_SOFTWARE=1 unconditionally, which made its own comment about vendor libEGL taking precedence false — a GPU host would never exercise the real driver path. Now conditional on nvidia-smi.

## Outcome

- Signal: corrected
- Correction: When asserting on pixels, mask to RGB. Alpha is constant on an opaque render and silently satisfies any range test.

## Source Nodes

- install_blender.sh