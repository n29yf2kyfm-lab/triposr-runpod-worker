"""clean_export.py — safe automated cleanup + hierarchy-preserving GLB export.

Runs ONLY the non-destructive fixes that never damage automotive detail:
  • merge vertices by a tiny distance (welds cracks, keeps panel gaps)
  • delete degenerate (zero-area) faces
  • delete loose vertices
  • recalculate normals outside (fixes the inward-facing faces the audit finds)
  • optional shade-smooth with an angle split so sharp panel edges stay sharp

It does NOT decimate, retopologise, boolean, or merge panels — those need a
human. It ALWAYS writes to a NEW file and never overwrites the master, and it
preserves object names + parent hierarchy so doors/bonnet/boot stay separate
for animation.

Run:
    blender -b -noaudio --python pipeline/blender/clean_export.py -- \
        --in  pipeline/masters/golf_master.glb \
        --out pipeline/build/golf_clean.glb \
        --merge 0.0002 --smooth-angle 35
"""
import bpy, sys, os, math

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def arg(f, d=None): return argv[argv.index(f) + 1] if f in argv else d
IN  = arg("--in"); OUT = arg("--out")
MERGE = float(arg("--merge", "0.0002"))        # ~0.2mm on a 4.5m car — welds cracks only
SMOOTH = float(arg("--smooth-angle", "35"))     # deg; edges sharper than this stay hard
if not IN or not OUT or not os.path.exists(IN):
    print("CLEAN_ERROR need --in existing and --out"); sys.exit(1)
os.makedirs(os.path.dirname(OUT), exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=IN)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
print(f"imported {len(meshes)} mesh objects from {os.path.basename(IN)}")

fixed = dict(merged=0, degenerate=0, loose=0, recalc=0)
for o in meshes:
    bpy.context.view_layer.objects.active = o
    o.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    # 1) weld cracks (tiny epsilon keeps panel gaps intact)
    bpy.ops.mesh.remove_doubles(threshold=MERGE)
    # 2) drop zero-area faces + loose geometry
    bpy.ops.mesh.dissolve_degenerate(threshold=1e-6)
    bpy.ops.mesh.delete_loose(use_verts=True, use_edges=True, use_faces=False)
    # 3) make all normals face outward (fixes inward/flipped faces)
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    # 4) auto-smooth: smooth shading but split hard edges so panels stay crisp
    for p in o.data.polygons: p.use_smooth = True
    try:  # Blender 4.0 API
        o.data.use_auto_smooth = True
        o.data.auto_smooth_angle = math.radians(SMOOTH)
    except Exception:
        m = o.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL"); m.keep_sharp = True
    o.select_set(False)
    fixed["recalc"] += 1

# preserve exact transforms / origins; export keeping names + hierarchy + anims
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(
    filepath=OUT, export_format="GLB",
    use_selection=False,
    export_apply=False,               # keep pivots/hierarchy intact for animation
    export_yup=True,
    export_normals=True,
    export_tangents=False,
    export_materials="EXPORT",
    export_animations=True,
    export_extras=True,               # keep custom object names/props
)
print(f"CLEAN_OK wrote {OUT}  ({os.path.getsize(OUT)//1024} KB)  normals-recalc on {fixed['recalc']} objects")
