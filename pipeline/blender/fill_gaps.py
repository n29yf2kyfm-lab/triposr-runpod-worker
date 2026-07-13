"""Fill door/panel shut-lines: Solidify the paint skin inward so every gap
shows a body-coloured groove wall instead of a see-through dark slot.
blender -b -noaudio --python /tmp/fill_gaps.py -- --in <glb> --out <glb> [--t 0.007]
"""
import bpy, sys

argv = sys.argv[sys.argv.index("--") + 1:]
IN = argv[argv.index("--in") + 1]; OUT = argv[argv.index("--out") + 1]
T = float(argv[argv.index("--t") + 1]) if "--t" in argv else 0.007

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=IN)

done = []
for o in bpy.context.scene.objects:
    if o.type != "MESH":
        continue
    if any((m and m.name in ("Paint_Color", "Car_Paint")) for m in o.data.materials):
        s = o.modifiers.new("GapFill", "SOLIDIFY")
        s.solidify_mode = "NON_MANIFOLD"          # robust on messy meshes
        s.nonmanifold_thickness_mode = "FIXED"    # no even-offset spikes
        s.thickness = T
        s.offset = -1.0            # extrude inward only
        done.append((o.name, len(o.data.polygons)))

bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", use_selection=False,
    export_apply=True, export_yup=True, export_normals=True, export_materials="EXPORT")
print(f"GAPS_OK {OUT} t={T} solidified={done}")
