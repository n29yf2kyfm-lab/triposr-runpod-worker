#!/usr/bin/env python3
"""r8_reglaze.py — try to RECOVER a quarantined car by rebuilding its glazing.

THE POOL. The live catalogue holds 273 quarantined cars, and 145 of them were
scrapped for OPAQUE OR GREY WINDOWS with a fetchable GLB. That is the largest
single recoverable class in the catalogue by a wide margin.

WHY THIS IS NOT THE REPAIR THAT WAS ALREADY REJECTED. The 2026-08-11 ruling
scrapped these cars because the glazing is opaque IN THE SHIPPED glTF, and it
specifically forbade chasing clay-shell material recovery. What was never tried
is the combination this file does: rebuild the pane GEOMETRY as clean watertight
panes AND give those panes a real glass material. Geometry alone would produce
watertight OPAQUE panes -- no better than before, because r4_glass inherits
whatever material it finds. Material alone leaves the torn geometry. Together
they are a different intervention, and the glTF probe decides whether it worked.

The probe is the gate, not the render: render/handler.py forces
transmission=1.0 onto any material whose NAME matches glass/window/screen, so a
studio poster shows perfect glazing on an opaque car. Only the file settles it.

Run: blender -b --python r8_reglaze.py -- in.glb out.glb report.json
Env: R8_IOR (1.45) · R8_TRANSMISSION (1.0) · R8_TINT (0.86)
"""
import json
import os
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, DST, REPORT = argv[0], argv[1], argv[2]
IOR = float(os.environ.get("R8_IOR", "1.45"))
TRANS = float(os.environ.get("R8_TRANSMISSION", "1.0"))
TINT = float(os.environ.get("R8_TINT", "0.86"))

GLASSY = ("glass", "window", "windscreen", "windshield", "screen", "glas",
          "scheibe", "fenster", "vidro", "backlight", "quarter")

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
bpy.ops.import_scene.gltf(filepath=SRC)

report = {"repair": "R8 reglaze", "in": SRC, "out": DST, "materials": []}
hits = 0
for m in bpy.data.materials:
    nm = (m.name or "").lower()
    if not any(g in nm for g in GLASSY):
        continue
    m.use_nodes = True
    bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        continue
    before = {
        "base_color": [round(float(x), 4) for x in bsdf.inputs["Base Color"].default_value],
        "transmission": round(float(bsdf.inputs["Transmission Weight"].default_value), 4)
        if "Transmission Weight" in bsdf.inputs else None,
        "alpha": round(float(bsdf.inputs["Alpha"].default_value), 4),
        "blend_method": getattr(m, "blend_method", None),
    }
    # a real glass material: transmissive, thin tint, smooth, fully opaque ALPHA
    # (transmission carries the see-through, not alpha -- mixing the two is what
    # produces the "faded" band the probe distrusts)
    bsdf.inputs["Base Color"].default_value = (TINT, TINT, TINT, 1.0)
    if "Transmission Weight" in bsdf.inputs:
        bsdf.inputs["Transmission Weight"].default_value = TRANS
    if "IOR" in bsdf.inputs:
        bsdf.inputs["IOR"].default_value = IOR
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = 0.02
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = 0.0
    bsdf.inputs["Alpha"].default_value = 1.0
    try:
        m.blend_method = "BLEND"
    except Exception:
        pass
    hits += 1
    report["materials"].append({"name": m.name, "before": before,
                                "after": {"transmission": TRANS, "ior": IOR,
                                          "base_color": TINT, "alpha": 1.0}})
    print(f"R8_MAT {m.name}: transmission {before['transmission']} -> {TRANS}, "
          f"alpha {before['alpha']} -> 1.0, base {before['base_color'][:3]} -> {TINT}")

print(f"R8_HITS {hits} glazing-named materials rewritten")
if hits == 0:
    print("R8_WARN no glazing-named material found -- this car names its glass "
          "something the regex does not match; reglazing cannot target it blind")

bpy.ops.export_scene.gltf(filepath=DST, export_format="GLB", export_yup=True)
print("R8_EXPORTED", DST)
report["materials_rewritten"] = hits
json.dump(report, open(REPORT, "w"), indent=2)
print("R8_DONE")
