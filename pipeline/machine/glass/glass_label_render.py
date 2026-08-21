#!/usr/bin/env python3
"""glass_label_render.py — deterministic PER-NODE label render for glazing evidence.

Run:  blender -b -P glass_label_render.py -- --in car.glb --out dir --tag v0

Why not a beauty render:  the production worker force-writes transmission=1.0 onto any
material whose NAME matches /glass|window|screen/ (render/handler.py), so a studio tile
of a car whose nodes are called Glass_* tells you nothing about its glazing.  And a
LOCAL beauty render of BLEND glass dithers at low sample counts (CLAUDE.md, machine v6).
A flat-emission label render has neither problem: AA off, 1 Cycles sample, one exact
colour per node, so every pixel is one label and a mask cut from it is exact.

Cameras are ORTHOGRAPHIC and fixed from the mesh bounds, so a before/after pair taken
with the same --frame file is pixel-comparable.  Container facts honoured: CYCLES only,
NO denoising (this build has no OpenImageDenoiser and use_denoising=True kills the
render AFTER "Blender quit" prints), Standard view transform (never AgX), and the
script writes its OWN done-marker so a stale frame can never read as a fresh one.

glTF is Y-up; Blender's importer maps glTF (x,y,z) -> Blender (x,-z,y).  All camera
maths below is in BLENDER space and the axis names in --views are glTF names.
"""
import json
import math
import os
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]


def arg(f, d=None):
    return argv[argv.index(f) + 1] if f in argv else d


SRC = arg("--in")
OUT = arg("--out", "/tmp/labels")
TAG = arg("--tag", "v")
RES = int(arg("--res", "1100"))
FRAME = arg("--frame")            # json with a locked camera frame, for before/after
WRITE_FRAME = arg("--write-frame")

# glTF-space view directions (the direction the camera looks FROM), nose at -X.
VIEWS = {
    "front":    (-1.0, 0.18, 0.0),
    "front34L": (-0.80, 0.22, -0.58),
    "sideL":    (0.0, 0.10, -1.0),
    "sideR":    (0.0, 0.10, 1.0),
    "rear34R":  (0.80, 0.22, 0.58),
    "rear":     (1.0, 0.18, 0.0),
    "top":      (0.0, 1.0, 0.02),
}

# widely separated flat colours; glazing nodes get the hot hues so spill is unmissable
KEY = {
    "Glass_Windscreen": (0.00, 0.45, 1.00),
    "Glass_Rear":       (0.00, 1.00, 0.35),
    "Glass_Side_L":     (1.00, 0.00, 0.85),
    "Glass_Side_R":     (1.00, 0.55, 0.00),
    "_body":            (0.32, 0.32, 0.32),
    "_wheel":           (0.06, 0.06, 0.06),
    "_lamp":            (0.85, 0.85, 0.10),
    "_interior":        (0.10, 0.10, 0.28),
}


def classify(name):
    if name in KEY:
        return name
    n = name.lower()
    if "wheel" in n:
        return "_wheel"
    if "lamp" in n:
        return "_lamp"
    if n.startswith("interior"):
        return "_interior"
    return "_body"


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)
objs = [o for o in bpy.data.objects if o.type == "MESH"]
assert objs, "no meshes imported"

mats = {}
for k, c in KEY.items():
    m = bpy.data.materials.new(f"LBL_{k}")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    e = nt.nodes.new("ShaderNodeEmission")
    e.inputs[0].default_value = (c[0], c[1], c[2], 1.0)
    e.inputs[1].default_value = 1.0
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(e.outputs[0], o.inputs[0])
    m.blend_method = "OPAQUE"
    mats[k] = m

counts = {}
for o in objs:
    k = classify(o.name)
    counts[k] = counts.get(k, 0) + 1
    o.data.materials.clear()
    o.data.materials.append(mats[k])
print("LABEL ASSIGNMENT:", json.dumps(counts, sort_keys=True))

# ---- scene bounds in Blender space -----------------------------------------
mn = Vector((1e9, 1e9, 1e9))
mx = Vector((-1e9, -1e9, -1e9))
for o in objs:
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c)
        mn = Vector((min(mn[i], w[i]) for i in range(3)))
        mx = Vector((max(mx[i], w[i]) for i in range(3)))
ctr = (mn + mx) / 2
diag = (mx - mn).length

if FRAME and os.path.exists(FRAME):
    fr = json.load(open(FRAME))
    ctr = Vector(fr["centre"]); diag = fr["diag"]
    print(f"CAMERA FRAME LOCKED from {FRAME}: centre={list(ctr)} diag={diag}")
if WRITE_FRAME:
    json.dump({"centre": list(ctr), "diag": diag}, open(WRITE_FRAME, "w"))
    print(f"wrote camera frame {WRITE_FRAME}")

sc = bpy.context.scene
sc.render.engine = "CYCLES"
sc.cycles.samples = 1
sc.cycles.use_denoising = False              # this build has NO OpenImageDenoiser
sc.cycles.max_bounces = 0
sc.render.filter_size = 0.0                  # AA off -> one label per pixel
sc.view_settings.view_transform = "Standard"  # never AgX
sc.view_settings.look = "None"
sc.view_settings.exposure = 0.0
sc.render.resolution_x = sc.render.resolution_y = RES
sc.render.image_settings.file_format = "PNG"
sc.render.film_transparent = False
w = bpy.data.worlds.new("W")
w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (1, 1, 1, 1)
w.node_tree.nodes["Background"].inputs[1].default_value = 1.0
sc.world = w

cam_d = bpy.data.cameras.new("C")
cam_d.type = "ORTHO"
cam_d.ortho_scale = diag * 0.62
cam = bpy.data.objects.new("C", cam_d)
sc.collection.objects.link(cam)
sc.camera = cam

os.makedirs(OUT, exist_ok=True)
done = []
for name, gv in VIEWS.items():
    # glTF (x,y,z) -> Blender (x,-z,y)
    d = Vector((gv[0], -gv[2], gv[1])).normalized()
    cam.location = ctr + d * diag * 1.6
    up = Vector((0, 0, 1)) if abs(d.z) < 0.95 else Vector((1, 0, 0))
    fwd = -d
    right = fwd.cross(up).normalized()
    trueup = right.cross(fwd).normalized()
    cam.matrix_world = __import__("mathutils").Matrix((
        (right.x, trueup.x, -fwd.x, cam.location.x),
        (right.y, trueup.y, -fwd.y, cam.location.y),
        (right.z, trueup.z, -fwd.z, cam.location.z),
        (0, 0, 0, 1)))
    p = os.path.join(OUT, f"{TAG}_{name}.png")
    if os.path.exists(p):
        os.remove(p)                          # never let a stale frame read as fresh
    sc.render.filepath = p
    bpy.ops.render.render(write_still=True)
    done.append(name)
    print(f"RENDERED {name} -> {p}", flush=True)

print("GLASS_LABEL_RENDER_DONE " + ",".join(done))
