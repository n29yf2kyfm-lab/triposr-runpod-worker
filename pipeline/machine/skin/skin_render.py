#!/usr/bin/env python3
"""skin_render.py -- LOCKED-CAMERA Cycles renders for the double-skin before/after.

The camera solve happens ONCE and is written to a spec JSON; every later render
REPLAYS that spec verbatim.  A repair moves vertices, so a bbox-derived camera
would move with them by about the size of the thing being judged (the
class_a_views lesson).  Identical framing must be a property of a file.

Container facts honoured (CLAUDE.md):
  * CYCLES only -- EEVEE cannot initialise, there is no EGL.
  * use_denoising is NEVER set True: this Blender has no OpenImageDenoiser and
    it raises RuntimeError AFTER "Blender quit" prints, leaving STALE FRAMES.
    The script deletes its target file first and prints its OWN DONE marker.
  * view_transform Standard, never AgX.  Exposure is verified numerically by
    the caller: a 0.22 world background must land near sRGB 130 with 0% clipped.

glTF is Y-up; Blender's importer maps (x,y,z)_gltf -> (x,-z,y)_blender.  Camera
positions in the spec are given in GLTF coordinates and converted here, so the
spec is readable against the mesh measurements.

Run:
  blender -b --python skin_render.py -- <car.glb> <out.png> --spec <spec.json>
          [--samples 32] [--res 1400] [--bg 0.22]
"""
import json
import math
import os
import sys

import bpy
import mathutils

argv = sys.argv[sys.argv.index("--") + 1:]
CAR, OUT = argv[0], argv[1]


def opt(flag, default=None, cast=str):
    if flag in argv:
        return cast(argv[argv.index(flag) + 1])
    return default


SPEC = opt("--spec", "camera_spec.json")
SAMPLES = opt("--samples", 32, int)
RES = opt("--res", 1400, int)
BG = opt("--bg", 0.22, float)
KEY = opt("--key", 900.0, float)
FILL = opt("--fill", 500.0, float)
LABEL = "--label" in argv
HIDE = [x for x in opt("--hide", "").split(",") if x]
KEEPONLY = [x for x in opt("--only", "").split(",") if x]
BACKFACE = "--backface" in argv   # magenta where the ray hits a BACK face
CLEARN = "--clearnormals" in argv  # drop the file's authored split normals
CLAYMAT = "--claymat" in argv      # one neutral diffuse, no clearcoat, no colour
AODIST = opt("--ao", 0.0, float)   # >0: render an AO map at this distance (m)   # deterministic mesh-ID pass: 1 sample, AA off, no bounces

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)

bpy.ops.import_scene.gltf(filepath=CAR)
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
if HIDE or KEEPONLY:
    drop = [o for o in meshes
            if (HIDE and any(h in o.name for h in HIDE))
            or (KEEPONLY and not any(h in o.name for h in KEEPONLY))]
    dropped = [o.name for o in drop]
    for o in drop:
        bpy.data.objects.remove(o, do_unlink=True)
    print(f"[skin_render] BISECT removed {dropped}")
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
print(f"[skin_render] imported {len(meshes)} mesh objects")


def gl2bl(p):
    return mathutils.Vector((p[0], -p[2], p[1]))


if os.path.exists(SPEC):
    spec = json.load(open(SPEC))
    print(f"[skin_render] REPLAY spec {SPEC}")
else:
    lo = [1e9] * 3
    hi = [-1e9] * 3
    for o in meshes:
        for c in o.bound_box:
            w = o.matrix_world @ mathutils.Vector(c)
            for i in range(3):
                lo[i] = min(lo[i], w[i]); hi[i] = max(hi[i], w[i])
    ctr = [(lo[i] + hi[i]) / 2 for i in range(3)]
    diag = math.dist(lo, hi)
    spec = {"target_bl": ctr, "diag": diag,
            "views": {
                # gltf coords: x = length (NOSE AT -X), y = up, z = width
                "full34": {"eye_gl": [-5.6, 2.60, 4.60], "lens": 55},
                "f34": {"eye_gl": [-3.6, 2.05, 2.90], "lens": 85},
                "bonnet": {"eye_gl": [-3.9, 2.35, 1.35], "lens": 85},
                "roof": {"eye_gl": [-1.2, 4.20, 1.50], "lens": 70},
                "side": {"eye_gl": [0.15, 1.55, 6.60], "lens": 85},
            }}
    json.dump(spec, open(SPEC, "w"), indent=1)
    print(f"[skin_render] SOLVED spec -> {SPEC}  target {ctr} diag {diag:.3f}")

VIEW = opt("--view", "f34")
v = spec["views"][VIEW]
target = mathutils.Vector(spec["target_bl"])
eye = gl2bl(v["eye_gl"])

cam_d = bpy.data.cameras.new("cam")
cam_d.lens = v["lens"]
cam = bpy.data.objects.new("cam", cam_d)
bpy.context.collection.objects.link(cam)
cam.location = eye
d = (target - eye).normalized()
cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
bpy.context.scene.camera = cam

if CLEARN:
    n = 0
    for o in meshes:
        if o.data.has_custom_normals:
            bpy.context.view_layer.objects.active = o
            bpy.ops.mesh.customdata_custom_splitnormals_clear()
            n += 1
    print(f"[skin_render] CLEARED authored split normals on {n} objects")

if CLAYMAT:
    cm = bpy.data.materials.new("CLAY")
    cm.use_nodes = True
    b = cm.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (.55, .55, .55, 1)
    b.inputs["Roughness"].default_value = 0.85
    b.inputs["Metallic"].default_value = 0.0
    for o in meshes:
        o.data.materials.clear(); o.data.materials.append(cm)
    print("[skin_render] CLAY material on every object")

if AODIST > 0:
    # An AO shader at a few mm IS the double-skin detector, drawn: a point goes
    # dark exactly when another surface sits within AODIST of it.  Unlike a
    # geometric census it is measured in the same place the eye sees the defect.
    am = bpy.data.materials.new("AO_DIAG")
    am.use_nodes = True
    nt = am.node_tree; nt.nodes.clear()
    ao = nt.nodes.new("ShaderNodeAmbientOcclusion")
    ao.samples = 16
    ao.only_local = True
    ao.inputs["Distance"].default_value = AODIST
    em = nt.nodes.new("ShaderNodeEmission")
    out_ = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(ao.outputs["AO"], em.inputs[0])
    nt.links.new(em.outputs[0], out_.inputs[0])
    for o in meshes:
        o.data.materials.clear(); o.data.materials.append(am)
    print(f"[skin_render] AO diagnostic at {AODIST*1000:.1f} mm")

if BACKFACE:
    # Cycles has no backface culling; a Geometry->Backfacing mix is the honest
    # equivalent and it names the defect directly: any magenta pixel is a
    # surface whose normal points AWAY from the camera, i.e. an inner wall seen
    # from outside.
    bm = bpy.data.materials.new("BACKFACE_DIAG")
    bm.use_nodes = True
    nt = bm.node_tree; nt.nodes.clear()
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    e1 = nt.nodes.new("ShaderNodeEmission"); e1.inputs[0].default_value = (.55, .55, .55, 1)
    e2 = nt.nodes.new("ShaderNodeEmission"); e2.inputs[0].default_value = (1, 0, 1, 1)
    mx = nt.nodes.new("ShaderNodeMixShader")
    out_ = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(geo.outputs["Backfacing"], mx.inputs[0])
    nt.links.new(e1.outputs[0], mx.inputs[1])
    nt.links.new(e2.outputs[0], mx.inputs[2])
    nt.links.new(mx.outputs[0], out_.inputs[0])
    for o in meshes:
        o.data.materials.clear(); o.data.materials.append(bm)

w = bpy.data.worlds.new("W")
w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (BG, BG, BG, 1.0)
w.node_tree.nodes["Background"].inputs[1].default_value = 1.0
bpy.context.scene.world = w

# two soft area lights, one each side, so a dark speck on red paint is not a
# lighting shadow.  Energies chosen for Standard transform, verified by caller.
for name, loc, rot, sz, en in ([] if LABEL else [
    ("key", (-3.0, -3.0, 4.2), None, 6.0, KEY),
    ("fill", (3.4, 3.0, 3.4), None, 7.0, FILL),
]):
    ld = bpy.data.lights.new(name, "AREA")
    ld.size = sz
    ld.energy = en
    lo_ = bpy.data.objects.new(name, ld)
    bpy.context.collection.objects.link(lo_)
    lo_.location = loc
    dd = (target - mathutils.Vector(loc)).normalized()
    lo_.rotation_euler = dd.to_track_quat("-Z", "Y").to_euler()

sc = bpy.context.scene
sc.render.engine = "CYCLES"
try:
    sc.cycles.device = "CPU"
except Exception:
    pass
sc.cycles.samples = SAMPLES
sc.cycles.use_denoising = False          # NO OIDN in this container -- see docstring
sc.cycles.use_adaptive_sampling = False  # adaptive sampling hides speckle
sc.cycles.max_bounces = 8
sc.cycles.transmission_bounces = 12
sc.render.resolution_x = RES
sc.render.resolution_y = int(RES * 0.72)
sc.render.resolution_percentage = 100
sc.render.film_transparent = False
sc.render.image_settings.file_format = "PNG"
sc.render.image_settings.color_depth = "8"
sc.view_settings.view_transform = "Standard"
sc.view_settings.look = "None"
sc.view_settings.exposure = 0.0
sc.view_settings.gamma = 1.0
if LABEL:
    # CLAUDE.md: a point-sampled renderer cannot measure label boundaries --
    # flat emission, AA off, one sample, zero bounces, so every pixel is
    # exactly one mesh's colour and nothing bleeds between them.
    sc.cycles.samples = 1
    sc.cycles.max_bounces = 0
    sc.cycles.transmission_bounces = 0
    sc.cycles.transparent_max_bounces = 0
    sc.render.filter_size = 0.01
    w.node_tree.nodes["Background"].inputs[0].default_value = (0, 0, 0, 1)
sc.render.filepath = OUT

if os.path.exists(OUT):
    os.remove(OUT)                      # stale-frame guard
bpy.ops.render.render(write_still=True)
print(f"[skin_render] DONE_MARKER {OUT} view={VIEW} samples={SAMPLES}")
