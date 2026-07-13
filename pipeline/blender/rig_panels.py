"""rig_panels.py — set hinge pivots and bake open/close animations for
separable car panels (doors, bonnet, boot), then export a rigged GLB.

IMPORTANT (honest boundary): this tool rigs panels that are ALREADY separate
mesh objects. Cutting clean door/bonnet/boot panels out of a welded body — with
proper shut-lines and capped apertures — is manual automotive modelling and must
be done first in Blender by a human. This tool then automates the repetitive
part: origin-to-hinge, animation clips, export. It never cuts geometry.

Spec file (JSON): a list of panels ->
  [{ "object": "Door_FL", "part": "door_front_left",
     "hinge_axis": "z", "hinge_at": [0.15, 0.5, 0.9], "open_deg": 62 }, ...]
  hinge_at = fraction [x,y,z] inside the panel's bounding box where the hinge sits
  hinge_axis = local axis the panel swings about (x/y/z)

Run:
  blender -b -noaudio --python pipeline/blender/rig_panels.py -- \
    --in pipeline/build/golf_clean.glb --spec pipeline/build/golf_panels.json \
    --out pipeline/build/golf_rigged.glb
"""
import bpy, json, sys, os, math, mathutils

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def arg(f, d=None): return argv[argv.index(f) + 1] if f in argv else d
IN, SPEC, OUT = arg("--in"), arg("--spec"), arg("--out")
if not (IN and SPEC and OUT and os.path.exists(IN) and os.path.exists(SPEC)):
    print("RIG_ERROR need --in, --spec, --out (existing in+spec)"); sys.exit(1)
panels = json.load(open(SPEC))
os.makedirs(os.path.dirname(OUT), exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=IN)
scene = bpy.context.scene
scene.frame_start = 0; scene.frame_end = 30

def set_origin_to_hinge(o, frac):
    """Move object origin to a point inside its bbox (the hinge line)."""
    coords = [o.matrix_world @ mathutils.Vector(c) for c in o.bound_box]
    lo = mathutils.Vector((min(c.x for c in coords), min(c.y for c in coords), min(c.z for c in coords)))
    hi = mathutils.Vector((max(c.x for c in coords), max(c.y for c in coords), max(c.z for c in coords)))
    hinge = mathutils.Vector((lo.x + (hi.x - lo.x) * frac[0],
                              lo.y + (hi.y - lo.y) * frac[1],
                              lo.z + (hi.z - lo.z) * frac[2]))
    scene.cursor.location = hinge
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True); bpy.context.view_layer.objects.active = o
    bpy.ops.object.origin_set(type="ORIGIN_CURSOR")

rigged = []
AXIS = {"x": 0, "y": 1, "z": 2}
for spec in panels:
    o = bpy.data.objects.get(spec["object"])
    if not o:
        print(f"RIG_SKIP missing object {spec['object']}"); continue
    set_origin_to_hinge(o, spec.get("hinge_at", [0.1, 0.5, 0.9]))
    ax = AXIS[spec.get("hinge_axis", "z")]
    ang = math.radians(spec.get("open_deg", 60))
    # keyframe closed (f0) -> open (f30) about the chosen local axis
    o.rotation_mode = "XYZ"
    o.rotation_euler[ax] = 0.0; o.keyframe_insert("rotation_euler", frame=0)
    o.rotation_euler[ax] = ang; o.keyframe_insert("rotation_euler", frame=30)
    if o.animation_data and o.animation_data.action:
        o.animation_data.action.name = spec["part"] + "_open"
        for fc in o.animation_data.action.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = "BEZIER"; kp.easing = "EASE_IN_OUT"
    rigged.append(spec["part"])
    o.rotation_euler[ax] = 0.0     # leave closed at export

bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(
    filepath=OUT, export_format="GLB", use_selection=False,
    export_apply=False, export_animations=True, export_animation_mode="ACTIONS",
    export_normals=True, export_tangents=True, export_extras=True, export_yup=True)
print(f"RIG_OK wrote {OUT} — rigged panels: {rigged}")
