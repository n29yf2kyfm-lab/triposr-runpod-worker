"""front_diag.py -- Gate 3 FRONT-FASCIA diagnostic renderer.

DIAGNOSTIC-FIRST gate: clay + material-ID + shaded, framed on the NOSE
(not the car centre, which averages component failures away).

Azimuth convention for a length-on-X y-up car (glTF X -> Blender X,
glTF Z -> Blender -Y):  az 0/180 = SIDE, az 90/270 = END-ON,
az 90/270 = END-ON.  *** ON THIS CAR THE NOSE IS AT -X *** (verified by
render: the -X end carries the VW badge, DRL bar and plate; the +X end is
the hatch + spoiler).  So the straight-front view is az 270 and the front
3/4s are az 215 and 305 -- the INVERSE of the machine's canon frame, where
front_kit.py builds at XMAX.  DO NOT rediscover this.

Blender here is 4.0.2: CYCLES only, and there is NO OpenImageDenoiser --
use_denoising MUST stay False or the render dies after "Blender quit".
Wait on the FRONT_DIAG_DONE marker this script prints, never on Blender.

Run: blender -b --python front_diag.py -- <in.glb> <outdir> <tag> [passes]
     passes: csv of clay,matid,shade  (default clay,matid)
"""
import bpy
import sys
import os
import math
import mathutils

argv = sys.argv[sys.argv.index("--") + 1:]
INP, OUT, TAG = argv[0], argv[1], argv[2]
PASSES = (argv[3] if len(argv) > 3 else "clay,matid").split(",")
VIEWS = argv[4] if len(argv) > 4 else "front,f34r,f34l,lowq"
DROP = [d for d in (argv[5] if len(argv) > 5 else "").split(",") if d]
os.makedirs(OUT, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=INP)
for o in list(bpy.data.objects):
    if o.type == 'MESH' and any(k.lower() in o.name.lower() for k in DROP):
        print("DROPPED", o.name)
        bpy.data.objects.remove(o, do_unlink=True)
meshes = [o for o in bpy.data.objects if o.type == 'MESH']
print("OBJECTS:", sorted(o.name for o in meshes))

mn = mathutils.Vector((1e9,) * 3)
mx = mathutils.Vector((-1e9,) * 3)
for o in meshes:
    for c in o.bound_box:
        w = o.matrix_world @ mathutils.Vector(c)
        mn = mathutils.Vector(map(min, mn, w))
        mx = mathutils.Vector(map(max, mx, w))
ctr = (mn + mx) / 2
size = max(mx - mn)
# nose target: 0.5 m back from the +X extreme, at mid-fascia height
nose = mathutils.Vector((mn.x + 0.45, ctr.y, mn.z + 0.36 * (mx.z - mn.z)))
lampR = mathutils.Vector((mn.x + 0.30, ctr.y + 0.60 * (mx.y - ctr.y), mn.z + 0.40 * (mx.z - mn.z)))
print(f"BBOX min {tuple(round(v,3) for v in mn)} max {tuple(round(v,3) for v in mx)}")

scn = bpy.context.scene
scn.render.engine = 'CYCLES'
scn.cycles.device = 'CPU'
scn.cycles.samples = 40
scn.cycles.use_denoising = False          # NO OIDN in this container
scn.view_settings.view_transform = 'Standard'
scn.render.resolution_x = 1000
scn.render.resolution_y = 700

world = bpy.data.worlds.new("w")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.62, 0.62, 0.64, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.55
scn.world = world
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
scn.collection.objects.link(sun)
sun.data.energy = 2.0
sun.data.angle = math.radians(8)
sun.rotation_euler = (math.radians(48), 0, math.radians(40))
fill = bpy.data.objects.new("fill", bpy.data.lights.new("fill", "SUN"))
scn.collection.objects.link(fill)
fill.data.energy = 0.6
fill.rotation_euler = (math.radians(60), 0, math.radians(-120))

cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
scn.collection.objects.link(cam)
scn.camera = cam
cam.data.type = 'ORTHO'                    # ortho: zero perspective, exact zoom

# (name, azimuth, elevation, ortho_scale_m, aim)  -- ortho: scale = metres across
ALLVIEWS = {
    "front": (270, 4, 2.30, "nose"),
    "f34r": (305, 10, 2.60, "nose"),
    "f34l": (215, 10, 2.60, "nose"),
    "lowq": (285, -8, 2.20, "nose"),
    "topq": (280, 45, 2.40, "nose"),
    "closeR": (290, 4, 1.30, "lampR"),
    "side": (0, 2, 4.70, "ctr"),
    "endP": (90, 2, 2.30, "ctr"),
    "endM": (270, 2, 2.30, "ctr"),
    "rear": (90, 8, 2.60, "ctr"),
}
WANT = [v for v in VIEWS.split(",") if v in ALLVIEWS]


def clay_material():
    m = bpy.data.materials.new("qc_clay")
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.50, 0.50, 0.50, 1)
    b.inputs["Roughness"].default_value = 0.55
    b.inputs["Metallic"].default_value = 0.0
    return m


PALETTE = {
    "carpaint": (0.85, 0.10, 0.10), "glass": (0.10, 0.45, 0.95),
    "Tyre_Rubber": (0.06, 0.06, 0.06), "Rim_Alloy": (0.95, 0.75, 0.10),
    "Lamp_Lens": (0.95, 0.35, 0.75), "interior": (0.10, 0.75, 0.35),
    # Gate 3 constructed components
    "Head_Lens_R": (1.00, 0.55, 0.00), "Head_Lens_L": (1.00, 0.80, 0.30),
    "Head_Housing_R": (0.55, 0.25, 0.00), "Head_Housing_L": (0.55, 0.40, 0.15),
    "Grille_Upper": (0.00, 0.90, 0.90), "Grille_Lower": (0.00, 0.55, 0.85),
    "Grille_Mesh": (0.00, 0.35, 0.55),
    "Intake_L": (0.60, 0.00, 0.85), "Intake_R": (0.85, 0.00, 0.60),
    "Front_Plate": (1.00, 1.00, 1.00), "Plate_Recess": (0.45, 0.30, 0.10),
    "Front_Badge": (1.00, 0.95, 0.20),
    "Head_Housing_R": (0.55, 0.20, 0.00), "Head_Housing_L": (0.75, 0.45, 0.15),
    "Head_Inner_R": (1.00, 0.30, 0.55), "Head_Inner_L": (1.00, 0.60, 0.75),
    "Grille_Frame": (0.00, 0.85, 0.85), "Grille_Back": (0.00, 0.30, 0.45),
    "Grille_Slat_0": (0.30, 1.00, 0.60), "Grille_Slat_1": (0.10, 0.80, 0.40),
    "Grille_Slat_2": (0.50, 1.00, 0.80),
    "Intake_Frame": (0.60, 0.00, 0.95), "Intake_Back": (0.25, 0.00, 0.45),
    "Intake_Slat_0": (0.85, 0.45, 1.00), "Intake_Slat_1": (0.65, 0.25, 0.90),
    "Intake_Corner_R": (1.00, 1.00, 0.55), "Intake_Corner_L": (0.80, 0.80, 0.25),
}


def render_pass(tag, override):
    scn.view_layers[0].material_override = override
    for name in WANT:
        az, el, df, aim = ALLVIEWS[name]
        a, e = math.radians(az), math.radians(el)
        target = {"nose": nose, "ctr": ctr, "lampR": lampR}[aim]
        cam.data.ortho_scale = df
        d = size * 2.2
        cam.location = (target.x + d * math.cos(e) * math.sin(a),
                        target.y - d * math.cos(e) * math.cos(a),
                        target.z + d * math.sin(e))
        cam.rotation_euler = (mathutils.Vector(target) - cam.location
                              ).to_track_quat('-Z', 'Y').to_euler()
        fp = os.path.join(OUT, f"{TAG}_{tag}_{name}.png")
        scn.render.filepath = fp
        bpy.ops.render.render(write_still=True)
        print("WROTE", fp)


if "clay" in PASSES:
    render_pass("clay", clay_material())
if "shade" in PASSES:
    render_pass("shade", None)
if "matid" in PASSES:
    for mat in bpy.data.materials:
        col = PALETTE.get(mat.name.split(".")[0])
        if col is None:
            print("MATID_UNMAPPED:", mat.name)
            col = (0.5, 0.5, 0.5)
        mat.use_nodes = True
        nt = mat.node_tree
        nt.nodes.clear()
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs["Color"].default_value = (*col, 1)
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(em.outputs[0], out.inputs["Surface"])
    render_pass("matid", None)

print("FRONT_DIAG_DONE")
