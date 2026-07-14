"""decimate_heavy.py — geometry reduction for over-budget sourced models.

Protected-region strategy: only meshes above --min-faces are decimated
(badges, mirrors, grille pieces, handles are usually separate small objects
and are left untouched); each large mesh is decimated toward its share of
the global triangle budget with a hard ratio floor so nothing melts.

blender -b -noaudio --python pipeline/optimisation/decimate_heavy.py -- \
  --in in.glb --out out.glb [--budget 450000] [--min-faces 20000] [--floor 0.15]
"""
import bpy, sys

argv = sys.argv[sys.argv.index("--") + 1:]
IN = argv[argv.index("--in") + 1]; OUT = argv[argv.index("--out") + 1]
BUDGET = int(argv[argv.index("--budget") + 1]) if "--budget" in argv else 450_000
MIN_FACES = int(argv[argv.index("--min-faces") + 1]) if "--min-faces" in argv else 20_000
FLOOR = float(argv[argv.index("--floor") + 1]) if "--floor" in argv else 0.15

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=IN)

meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
total = sum(len(o.data.polygons) for o in meshes)
big = [o for o in meshes if len(o.data.polygons) >= MIN_FACES]
small_faces = total - sum(len(o.data.polygons) for o in big)
big_budget = max(50_000, BUDGET - small_faces)
big_total = sum(len(o.data.polygons) for o in big)

print(f"DECIMATE total={total} big_meshes={len(big)} big_total={big_total} "
      f"target_big={big_budget}")

if big_total > big_budget:
    ratio_global = big_budget / big_total
    for o in big:
        r = max(FLOOR, ratio_global)
        d = o.modifiers.new("Decimate", "DECIMATE")
        d.ratio = r
        d.use_collapse_triangulate = True
        print(f"  {o.name}: {len(o.data.polygons)} faces -> ratio {r:.2f}")

bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", use_selection=False,
    export_apply=True, export_yup=True, export_normals=True, export_materials="EXPORT")
print("DECIMATE_OK", OUT)
