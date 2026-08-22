#!/usr/bin/env python3
"""r9_cabin.py — neutralise PLACEHOLDER colours that reglazing has exposed.

Turning opaque windows into real glass does not only recover a car; it reveals
whatever the opaque windows were hiding. ford-focus-w6 came back with a bright
green cabin, and the cause is in the SOURCE, not the repair: three materials
carry a near-pure green baseColorFactor [0, 0.8, 0.00]. No car interior is that
colour -- it is a modelling placeholder that was invisible while the glass was
solid.

THE AUTOMATIC RULE WAS TRIED AND DOES NOT WORK. DO NOT REBUILD IT.

The intended gate was: near-pure saturated colour AND geometry inside the cabin,
the second condition existing to stop the rule repainting a red car's body. Two
controls dismantled it.

  * TEXTURED MATERIALS CANNOT BE JUDGED THIS WAY. The colour is read from the
    Principled BSDF's Base Color socket, which is the material's colour only when
    nothing is plugged into it. With a baseColor texture connected the socket is
    an ignored multiplier: a control that set a textured `carpaint` to pure red
    exported it as [1,1,1] and the tool read saturation 0.000. Such materials are
    now skipped with a stated reason, never silently misjudged.

  * A BOUNDING BOX CANNOT SEPARATE CABIN FROM BODY. Measured on the Golf, the
    fraction of each material's vertices inside the glazing box:

        interior   0.455
        carpaint   0.404      <- the body shell

    The glazing box spans most of the car's length, so 40% of the exterior shell
    falls inside it. No threshold puts the interior in and the paint out.
    Dropping the box floor to reach cabin trim only raises both together.

So this file no longer guesses. It neutralises EXACTLY the materials named in
R9_MATERIALS and nothing else, which makes it a per-car instrument -- the honest
shape for a defect whose only reliable detector is a person looking at a render.

Run: blender -b --python r9_cabin.py -- in.glb out.glb report.json
Env: R9_MATERIALS (comma-separated, REQUIRED) · R9_NEUTRAL (0.10) · R9_DRYRUN
"""
import json
import os
import sys

import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, DST, REPORT = argv[0], argv[1], argv[2]
NEUTRAL = float(os.environ.get("R9_NEUTRAL", "0.10"))
DRY = os.environ.get("R9_DRYRUN", "0") == "1"
WANT = [x.strip() for x in os.environ.get("R9_MATERIALS", "").split(",") if x.strip()]
if not WANT:
    raise SystemExit("R9_FAIL: R9_MATERIALS is required -- this tool does not guess")

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
bpy.ops.import_scene.gltf(filepath=SRC)

report = {"repair": "R9 cabin placeholder colours (explicit list)",
          "requested": WANT, "changed": [], "not_found": [], "skipped": []}
for name in WANT:
    m = bpy.data.materials.get(name)
    if m is None or not m.use_nodes:
        report["not_found"].append(name)
        print(f"R9_MISSING {name}")
        continue
    b = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if b is None or b.inputs["Base Color"].is_linked:
        report["skipped"].append({"name": name,
                                  "why": "textured or no Principled BSDF"})
        print(f"R9_SKIP {name}: textured or no BSDF -- socket value is meaningless")
        continue
    before = [round(float(c), 4) for c in list(b.inputs["Base Color"].default_value)[:3]]
    if not DRY:
        b.inputs["Base Color"].default_value = (NEUTRAL, NEUTRAL, NEUTRAL, 1.0)
    report["changed"].append({"name": name, "before": before, "after": NEUTRAL})
    print(f"R9_FIX {name}: {before} -> neutral {NEUTRAL}")

print(f"R9_CHANGED {len(report['changed'])}  R9_MISSING {len(report['not_found'])}  "
      f"R9_SKIPPED {len(report['skipped'])}")
if not DRY:
    bpy.ops.export_scene.gltf(filepath=DST, export_format="GLB", export_yup=True)
    print("R9_EXPORTED", DST)
json.dump(report, open(REPORT, "w"), indent=2)
print("R9_DONE")
