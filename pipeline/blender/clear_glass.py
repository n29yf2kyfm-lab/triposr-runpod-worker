"""clear_glass.py — give a library model's glass materials REAL transparency
so the interior reads through the windows (renders AND the in-app viewer).

Many sourced models ship 'glass' as opaque near-black paint. This sets each
named glass material to alpha-BLEND with a light smoky tint: windscreen
lightest, side/privacy glass darker, roof darker still — matching how a real
car reads. Materials keep their names so the render worker's glass exclusion
and the QC G2 gate both still recognise them.

Run: blender -b -noaudio --python clear_glass.py -- in.glb out.glb
     (or python3 with a pip bpy wheel)
Optional: --front 0.32 --side 0.55 --roof 0.6  (alpha, lower = clearer)
"""
import re
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, DST = argv[0], argv[1]


def _opt(flag, default):
    return float(argv[argv.index(flag) + 1]) if flag in argv else default


A_FRONT = _opt("--front", 0.32)   # windscreen / front side glass
A_SIDE = _opt("--side", 0.55)     # privacy / rear side glass (darker tint)
A_ROOF = _opt("--roof", 0.60)     # panoramic roof

FRONT_RE = re.compile(r"front|windscreen|windshield", re.I)
ROOF_RE = re.compile(r"roof|sunroof|pano", re.I)
GLASS_RE = re.compile(r"glass|window|screen", re.I)
# never touch interior parts — 'int_screen' is the cockpit touchscreen, not a window
SKIP_RE = re.compile(r"^int[_\s-]|interior|dash|cluster", re.I)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)

done = []
for m in bpy.data.materials:
    n = m.name or ""
    if not (m.use_nodes and GLASS_RE.search(n)) or SKIP_RE.search(n):
        continue
    b = next((x for x in m.node_tree.nodes if x.type == "BSDF_PRINCIPLED"), None)
    if not b:
        continue
    alpha = A_FRONT if FRONT_RE.search(n) else (A_ROOF if ROOF_RE.search(n) else A_SIDE)
    # cut any baked texture off Base Color: the smoky tint must be uniform
    for lnk in list(b.inputs["Base Color"].links):
        m.node_tree.links.remove(lnk)
    b.inputs["Base Color"].default_value = (0.02, 0.025, 0.03, 1)
    for name, val in (("Alpha", alpha), ("Roughness", 0.04), ("Metallic", 0.0)):
        inp = b.inputs.get(name)
        if inp is not None:
            for lnk in list(inp.links):
                m.node_tree.links.remove(lnk)
            inp.default_value = val
    m.blend_method = "BLEND"
    done.append((n, alpha))

print("GLASS cleared:", done)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=DST, export_format="GLB", export_apply=True,
                          export_yup=True, export_normals=True,
                          export_materials="EXPORT")
print("CLEAR_GLASS_OK" if done else "CLEAR_GLASS_SKIP", DST)
