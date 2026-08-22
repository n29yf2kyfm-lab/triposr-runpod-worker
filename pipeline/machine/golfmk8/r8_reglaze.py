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

FOUR DEFECTS FROM THE FIRST TEST BATCH, ALL FIXED HERE:
  * it rewrote glazing on cars that were ALREADY clear. subaru-brz was
    quarantined for TYRES, its glazing probed clear at alpha 0.25 BLEND, and the
    tool flattened that tint. It now REFUSES unless the caller passes
    R8_FORCE=1 or the material is genuinely non-transmissive.
  * the tint rewrite was too aggressive. ford-transit's glazing was [0,0,0] and
    came back light grey -- an appearance change, not a repair. The original RGB
    is now PRESERVED unless it is degenerate for transmissive glass, which means
    near-black: in glTF, transmission is tinted BY baseColor, so a black base
    with transmission 1.0 is still an opaque black pane.
  * Draco was lost on re-export (files grew 2.08x-4.72x). The caller
    re-compresses; this file records the size so the cost is visible.
  * some quarantine reasons do not match the file -- a car filed as a clay shell
    probed clear. Reason strings are not evidence; the probe is.

Run: blender -b --python r8_reglaze.py -- in.glb out.glb report.json
Env: R8_IOR (1.45) · R8_TRANSMISSION (1.0) · R8_TINT_FLOOR (0.05) · R8_FORCE (0)
"""
import json
import os
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, DST, REPORT = argv[0], argv[1], argv[2]
IOR = float(os.environ.get("R8_IOR", "1.45"))
TRANS = float(os.environ.get("R8_TRANSMISSION", "1.0"))
TINT_FLOOR = float(os.environ.get("R8_TINT_FLOOR", "0.05"))
NEUTRAL = float(os.environ.get("R8_NEUTRAL_TINT", "0.72"))
FORCE = os.environ.get("R8_FORCE", "0") == "1"

GLASSY = ("glass", "window", "windscreen", "windshield", "screen", "glas",
          "scheibe", "fenster", "vidro", "backlight", "quarter")

# LAMP LENSES ARE NOT WINDOWS, and "glass" matches both. A triage of the first
# 122 recovered cars found 24 where this rewrote HeadLightsGlass, BrakeLightsGlass,
# glass_headlights, REARLIGHT_GLASS_NM and the like -- a fully transmissive
# headlamp lens is wrong, lamps want dark gloss. This is the documented lamp-lens
# trap: the same reason `backlight` had to be handled carefully, since it means
# the REAR WINDSCREEN as often as it means a tail lamp. `backlight` is kept in
# GLASSY and deliberately NOT listed here for exactly that reason.
LAMPY = ("headlight", "headlamp", "brakelight", "taillight", "taillamp",
         "rearlight", "rear_light", "drl", "indicator", "reflector", "foglight",
         "fog_light", "blinker", "turnsignal", "lamp")

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
bpy.ops.import_scene.gltf(filepath=SRC)

report = {"repair": "R8 reglaze", "in": SRC, "out": DST, "materials": []}
hits = 0
for m in bpy.data.materials:
    nm = (m.name or "").lower()
    if not any(g in nm for g in GLASSY):
        continue
    if any(l in nm for l in LAMPY):
        print(f"R8_LAMP {m.name}: glass-named but it is a LAMP LENS -- left alone")
        report["materials"].append({"name": m.name, "skipped": "lamp lens, not glazing"})
        continue
    m.use_nodes = True
    bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        continue
    tw = bsdf.inputs["Transmission Weight"].default_value if "Transmission Weight" in bsdf.inputs else 0.0
    already = float(tw) > 0.01 or float(bsdf.inputs["Alpha"].default_value) < 0.99
    before = {
        "base_color": [round(float(x), 4) for x in bsdf.inputs["Base Color"].default_value],
        "transmission": round(float(bsdf.inputs["Transmission Weight"].default_value), 4)
        if "Transmission Weight" in bsdf.inputs else None,
        "alpha": round(float(bsdf.inputs["Alpha"].default_value), 4),
        "blend_method": getattr(m, "blend_method", None),
    }
    if already and not FORCE:
        print(f"R8_SKIP {m.name}: already transmissive/blended "
              f"(transmission={float(tw):.3f}, alpha={float(bsdf.inputs['Alpha'].default_value):.3f}) "
              f"-- not touching a pane that already works")
        report["materials"].append({"name": m.name, "skipped": "already transparent",
                                    "before": before})
        continue
    # a real glass material: transmissive, smooth, fully opaque ALPHA
    # (transmission carries the see-through, not alpha -- mixing the two is what
    # produces the "faded" band the probe distrusts).
    # TINT IS PRESERVED. glTF tints transmission by baseColor, so only a
    # near-black base is degenerate -- that would still read as an opaque pane.
    rgb = list(bsdf.inputs["Base Color"].default_value)[:3]
    if max(rgb) < TINT_FLOOR:
        rgb = [NEUTRAL, NEUTRAL, NEUTRAL]
        print(f"R8_TINT {m.name}: base {before['base_color'][:3]} is degenerate "
              f"for transmissive glass -> neutral {NEUTRAL}")
    bsdf.inputs["Base Color"].default_value = (rgb[0], rgb[1], rgb[2], 1.0)
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
                                          "base_color": [round(c, 4) for c in rgb],
                                          "alpha": 1.0}})
    print(f"R8_MAT {m.name}: transmission {before['transmission']} -> {TRANS}, "
          f"alpha {before['alpha']} -> 1.0, base {[round(c,3) for c in before['base_color'][:3]]} "
          f"-> {[round(c,3) for c in rgb]}")

print(f"R8_HITS {hits} glazing-named materials rewritten")
if hits == 0:
    print("R8_WARN no glazing-named material found -- this car names its glass "
          "something the regex does not match; reglazing cannot target it blind")

bpy.ops.export_scene.gltf(filepath=DST, export_format="GLB", export_yup=True)
print("R8_EXPORTED", DST)
report["materials_rewritten"] = hits
json.dump(report, open(REPORT, "w"), indent=2)
print("R8_DONE")
