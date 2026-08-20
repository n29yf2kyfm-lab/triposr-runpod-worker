#!/usr/bin/env python3
"""Deterministic label render: flat emission per label, AA off, 1 Cycles sample.

Every pixel comes out exactly one label's colour, so a mask cut from the image
has no sampling noise and its perimeter is a fair raggedness measure. A
point-sampled/splat renderer cannot do this job: where two labels' shells are
coincident it produces random speckle, which then reads as a ragged label when
the label is fine (and vice versa).

Both routes are put in a common frame (length->X, width->Y, up->Z) and orbited
by identical cameras, so masks from the two are directly comparable.

Run: blender -b -P bl_label_render.py -- --in x.glb --route pc|seg --az 55 \
         --el 14 --res 1200 --out p.png
"""
import bpy, sys, os, json
from mathutils import Vector, Matrix
import math

argv = sys.argv[sys.argv.index("--") + 1:]
def arg(f, d=None):
    return argv[argv.index(f) + 1] if f in argv else d

SRC = arg("--in"); ROUTE = arg("--route"); OUT = arg("--out")
AZ = float(arg("--az", "55")); EL = float(arg("--el", "14"))
RES = int(arg("--res", "1200"))

MAP_PC = {"Glass_Tint": "glass", "Wheel_Dark": "wheel", "Material_0": "body",
          "Lamp_Lens": "lamp", "Interior_Dark": "interior"}
MAP_SEG = {"glass": "glass", "Tyre_Rubber": "wheel", "Rim_Alloy": "wheel",
           "carpaint": "body", "Lamp_Lens": "lamp", "interior": "interior"}
MAPPING = MAP_PC if ROUTE == "pc" else MAP_SEG
# exact, widely-separated flat colours so label recovery is unambiguous
KEY = {"body": (1.0, 0.0, 0.0), "glass": (0.0, 0.0, 1.0),
       "wheel": (0.0, 1.0, 0.0), "lamp": (1.0, 1.0, 0.0),
       "interior": (0.0, 1.0, 1.0)}

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)
objs = [o for o in bpy.data.objects if o.type == "MESH"]
print("imported", len(objs), "objects")

# ---- common frame: length->X, width->Y, up->Z -------------------------------
# BOTH files are Y-up, and Blender's glTF importer converts Y-up to Z-up, so UP
# IS Z FOR BOTH — do not assume the file's own axis order here (CLAUDE.md's
# render-side inversion note is the same class of mistake). Length is then just
# whichever horizontal axis is longer; rotate 90 deg about Z if it is Y.
def world_ext():
    bpy.context.view_layer.update()
    mn = Vector((1e9,) * 3); mx = Vector((-1e9,) * 3)
    for o in objs:
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            for i in range(3):
                mn[i] = min(mn[i], w[i]); mx[i] = max(mx[i], w[i])
    return mn, mx

mn, mx = world_ext()
if (mx.y - mn.y) > (mx.x - mn.x):
    R = Matrix(((0, 1, 0, 0), (-1, 0, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)))
    for o in objs:
        o.matrix_world = R @ o.matrix_world
    print("yawed 90deg: length was on Y")
# optional 180 deg yaw to line the two routes' noses up
if arg("--yaw180", "0") == "1":
    R = Matrix(((-1, 0, 0, 0), (0, -1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)))
    for o in objs:
        o.matrix_world = R @ o.matrix_world

bpy.context.view_layer.update()
mn = Vector((1e9, 1e9, 1e9)); mx = Vector((-1e9, -1e9, -1e9))
for o in objs:
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c)
        for i in range(3):
            mn[i] = min(mn[i], w[i]); mx[i] = max(mx[i], w[i])
ctr = (mn + mx) / 2.0
ext = mx - mn
scale = 1.0 / max(ext)
print("bbox ext", [round(e, 4) for e in ext], "scale", round(scale, 5))

# ---- flat emission materials -----------------------------------------------
mats = {}
for lab, col in KEY.items():
    m = bpy.data.materials.new("L_" + lab)
    m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    e = nt.nodes.new("ShaderNodeEmission")
    e.inputs[0].default_value = (col[0], col[1], col[2], 1.0)
    e.inputs[1].default_value = 1.0
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(e.outputs[0], out.inputs[0])
    mats[lab] = m

unmapped = set()
for o in objs:
    lab = None
    if o.data.materials and o.data.materials[0] is not None:
        lab = MAPPING.get(o.data.materials[0].name)
    if lab is None:
        lab = MAPPING.get(o.name)
    if lab is None:
        unmapped.add(o.data.materials[0].name if o.data.materials else o.name)
        lab = "body"
    o.data.materials.clear()
    o.data.materials.append(mats[lab])
if unmapped:
    print("UNMAPPED (defaulted to body):", sorted(unmapped)[:10])

# ---- camera: identical orbit for both --------------------------------------
cam_data = bpy.data.cameras.new("cam"); cam_data.lens_unit = "FOV"
cam_data.angle = math.radians(30.0)
cam = bpy.data.objects.new("cam", cam_data)
bpy.context.scene.collection.objects.link(cam)
radius = ext.length * float(arg('--dist','1.95'))
a, e = math.radians(AZ), math.radians(EL)
# Z-UP orbit: az sweeps in the XY plane, el lifts along +Z
d = Vector((math.cos(a) * math.cos(e), math.sin(a) * math.cos(e), math.sin(e)))
cam.location = ctr + d * radius
z = (cam.location - ctr).normalized()
x = Vector((0, 0, 1)).cross(z).normalized()
y = z.cross(x)
cam.matrix_world = Matrix(((x.x, y.x, z.x, cam.location.x),
                           (x.y, y.y, z.y, cam.location.y),
                           (x.z, y.z, z.z, cam.location.z),
                           (0, 0, 0, 1)))
sc = bpy.context.scene
sc.camera = cam
sc.render.engine = "CYCLES"
sc.cycles.device = "CPU"
sc.cycles.samples = 1
sc.cycles.use_denoising = False
sc.cycles.max_bounces = 0
sc.cycles.transparent_max_bounces = 0
sc.render.filter_size = 0.01           # AA off -> pure flat label colours
sc.render.resolution_x = sc.render.resolution_y = RES
sc.render.image_settings.file_format = "PNG"
sc.render.image_settings.color_mode = "RGB"
sc.view_settings.view_transform = "Standard"   # never AgX for label colours
sc.render.film_transparent = True
sc.world = bpy.data.worlds.new("w")
sc.world.use_nodes = True
sc.render.filepath = OUT
bpy.ops.render.render(write_still=True)
print("WROTE", OUT)
