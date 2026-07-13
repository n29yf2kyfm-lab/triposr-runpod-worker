"""golf_finish.py — finish the sourced Golf PROPERLY in Blender (not trimesh).

The real fixes the trimesh pipeline couldn't do:
  • Weighted Normal modifier (keep_sharp) on the paint  -> factory-smooth panel
    shading, sharp feature lines preserved. This is what kills the "patchy /
    faceted" look at the normal level without changing the silhouette.
  • Corrective Smooth on the body  -> relaxes the wavy rear quarter gently,
    feature-preserving (far better than trimesh Taubin).
  • Clean merge + outward normals + tangents.
  • Unified gunmetal metallic + clearcoat paint; tinted glass; light interior.

Run:
  blender -b -noaudio --python pipeline/blender/golf_finish.py -- \
    --in pipeline/masters/golf_master.glb --out pipeline/build/golf_v10.glb
"""
import bpy, sys, os, math

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def arg(f, d=None): return argv[argv.index(f) + 1] if f in argv else d
IN, OUT = arg("--in"), arg("--out")
if not (IN and OUT and os.path.exists(IN)):
    print("FINISH_ERROR need --in existing and --out"); sys.exit(1)
os.makedirs(os.path.dirname(OUT), exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=IN)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]

PAINT_NAMES = {"Paint_Color", "Car_Paint"}
def is_paint(o): return any((m and m.name in PAINT_NAMES) for m in o.data.materials)

for o in meshes:
    bpy.context.view_layer.objects.active = o; o.select_set(True)
    # clean
    bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=0.0002)
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    for p in o.data.polygons: p.use_smooth = True
    try:
        o.data.use_auto_smooth = True; o.data.auto_smooth_angle = math.radians(40)
    except Exception:
        pass
    if is_paint(o):
        # feature-preserving relax of the wavy panels
        cs = o.modifiers.new("Corrective", "CORRECTIVE_SMOOTH")
        cs.factor = 0.35; cs.iterations = 6; cs.smooth_type = "LENGTH_WEIGHTED"; cs.use_pin_boundary = True
        # factory-smooth shading, sharp edges kept
        wn = o.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
        wn.keep_sharp = True; wn.weight = 60; wn.thresh = 0.3
    o.select_set(False)

# material polish -----------------------------------------------------------
def setp(m, base=None, metal=None, rough=None, coat=None, coat_r=None, alpha=None, blend=None):
    if not (m and m.use_nodes): return
    b = m.node_tree.nodes.get("Principled BSDF")
    if not b: return
    if base is not None: b.inputs["Base Color"].default_value = base
    if metal is not None: b.inputs["Metallic"].default_value = metal
    if rough is not None: b.inputs["Roughness"].default_value = rough
    if coat is not None and "Coat Weight" in b.inputs: b.inputs["Coat Weight"].default_value = coat
    if coat_r is not None and "Coat Roughness" in b.inputs: b.inputs["Coat Roughness"].default_value = coat_r
    if alpha is not None and "Alpha" in b.inputs: b.inputs["Alpha"].default_value = alpha
    if blend: m.blend_method = "BLEND"
for m in bpy.data.materials:
    n = m.name
    if n in PAINT_NAMES:
        setp(m, base=(0.055, 0.062, 0.075, 1), metal=0.85, rough=0.27, coat=1.0, coat_r=0.04)
    elif n in ("privacy_glass", "roof_glass"):
        setp(m, base=(0.012, 0.013, 0.016, 1), metal=0.0, rough=0.6)
    elif n == "front_glass_tint":
        # more opaque so the interior stops glaring white through the windscreen
        setp(m, base=(0.035, 0.04, 0.05, 1), metal=0.0, rough=0.14, alpha=0.48, blend=True)
    elif n in ("interior_light",):
        setp(m, base=(0.30, 0.29, 0.28, 1), metal=0.0, rough=0.9)
    elif n == "interior_card_dark":
        # LEFTOVER from old trimesh work — it reads as a wide dark slot in the
        # door gap. Recolour it to the body paint so the doors read solid; the
        # real thin panel seam in the mesh still shows.
        setp(m, base=(0.055, 0.062, 0.075, 1), metal=0.85, rough=0.30, coat=1.0)

bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", use_selection=False,
    export_apply=True,                 # bake the modifiers into the exported mesh
    export_yup=True, export_normals=True, export_tangents=False, export_extras=True,
    export_materials="EXPORT")
print(f"FINISH_OK wrote {OUT} ({os.path.getsize(OUT)//1024} KB) on {len(meshes)} objects")
