---
type: "query"
date: "2026-08-25T22:47:37.018837+00:00"
question: "Can EEVEE run in this container, and is eyeball_views stuck on CPU?"
contributor: "graphify"
outcome: "corrected"
correction: "Re-test inherited environment limitations after any upgrade. 'X cannot work here' aged into folklore and blocked a capability for months; it cost three apt packages to disprove."
source_nodes: ["install_blender.sh", "eyeball_views.py", "handler.py"]
---

# Q: Can EEVEE run in this container, and is eyeball_views stuck on CPU?

## Answer

BOTH inherited claims were wrong, corrected 2026-08-25. (1) 'No EGL in this container, EEVEE cannot initialise' was true of the container AS SHIPPED and was never re-tested after 4.5.12 landed. Three apt packages fix it — libegl1 + libegl-mesa0 + libgl1-mesa-dri give software EGL and EEVEE Next renders. Verified BY PIXELS (160px factory-startup frame, 132 unique colours, std 21, default cube visible); EGL_BAD_MATCH warnings print and are non-fatal. install_blender.sh now installs EGL on BOTH script paths and asserts EEVEE by pixel range, not exit code. (2) eyeball_views.py hardcoded cycles CPU, so the same sheet took minutes here that render/handler.py takes seconds for on the worker's OPTIX. Now probes OPTIX->CUDA->CPU like the handler and prints which branch ran. Still pinned to 4.5.12 LTS; 5.0 NOT installed. CYCLES remains the verdict engine — every material ruling in CLAUDE.md was calibrated on it, so EEVEE is a preview only.

## Outcome

- Signal: corrected
- Correction: Re-test inherited environment limitations after any upgrade. 'X cannot work here' aged into folklore and blocked a capability for months; it cost three apt packages to disprove.

## Source Nodes

- install_blender.sh
- eyeball_views.py
- handler.py