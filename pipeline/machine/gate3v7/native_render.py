#!/usr/bin/env python3
"""native_render.py -- render a GLB with ITS OWN materials.

    blender -b --python native_render.py -- <in.glb> <out.png> <az> [res] [samples]

WHY THIS EXISTS.  gate3v6/rig.py has no material-preserving pass: its `matte`
AND `beauty` branches both call `assign_all(vis, NEUTRAL_MATTE)`, so every
surface renders as the same grey clay.  That is correct for judging SURFACE --
and it is exactly wrong for judging whether a headlamp reads as a headlamp,
because a lamp reads by being dark and glossy against paint.  I assumed
"beauty" preserved materials, rendered one, and got clay; that assumption is
withdrawn and this file replaces it.

It deliberately keeps the rig's other disciplines: Cycles (no EGL here so EEVEE
cannot initialise), view transform Standard and never AgX, no denoising (this
container has no OpenImageDenoiser and enabling it kills the render AFTER
"Blender quit" prints), and the frame is unlinked before rendering so a stale
image can never be mistaken for a fresh one.
"""
import os
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
INP, OUT = argv[0], argv[1]
AZ = float(argv[2]) if len(argv) > 2 else 270.0
RES = int(argv[3]) if len(argv) > 3 else 1800
SAMP = int(argv[4]) if len(argv) > 4 else 40
STOPS = float(argv[5]) if len(argv) > 5 else 0.0
# LIGHT power, not exposure, is the right lever. Pulling `view_settings.exposure`
# darkens the BACKGROUND along with the car, so the 0.22 world no longer lands at
# sRGB 129 and the frame can no longer be checked against a known value. Measured:
# at -2.2 stops the background fell to 63 and the car still clipped 9.2%.
LSCALE = float(argv[6]) if len(argv) > 6 else 1.0

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=INP)
objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if not objs:
    raise SystemExit("no meshes imported")

import mathutils
lo = mathutils.Vector((1e9, 1e9, 1e9))
hi = mathutils.Vector((-1e9, -1e9, -1e9))
for o in objs:
    for c in o.bound_box:
        w = o.matrix_world @ mathutils.Vector(c)
        lo = mathutils.Vector((min(lo[i], w[i]) for i in range(3)))
        hi = mathutils.Vector((max(hi[i], w[i]) for i in range(3)))
centre = (lo + hi) / 2.0
diag = (hi - lo).length

# world: mid grey, so nothing is hidden by a dark background
w = bpy.data.worlds.new("W")
w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.22, 0.22, 0.22, 1)
w.node_tree.nodes["Background"].inputs[1].default_value = 1.0
bpy.context.scene.world = w

import math
for name, (ax, ay, az_, pw) in {
    "key": ((1.0, -1.6, 1.1), None, None, 1.0),
}.items():
    pass
def area(nm, loc, power, size):
    d = bpy.data.lights.new(nm, "AREA")
    d.energy = power
    d.size = size
    ob = bpy.data.objects.new(nm, d)
    bpy.context.collection.objects.link(ob)
    ob.location = loc
    dirv = centre - mathutils.Vector(loc)
    ob.rotation_euler = dirv.to_track_quat("-Z", "Y").to_euler()
    return ob


R = diag
area("key", (centre.x - 0.7 * R, centre.y - 1.5 * R, centre.z + 1.1 * R), LSCALE * 900 * R * R, R)
area("fill", (centre.x + 1.4 * R, centre.y - 1.1 * R, centre.z + 0.5 * R), LSCALE * 320 * R * R, R)
area("top", (centre.x, centre.y - 0.3 * R, centre.z + 2.0 * R), LSCALE * 500 * R * R, 1.5 * R)

cam_d = bpy.data.cameras.new("C")
cam_d.type = "ORTHO"
cam = bpy.data.objects.new("C", cam_d)
bpy.context.collection.objects.link(cam)
a = math.radians(AZ)
cam.location = (centre.x + R * 3 * math.sin(a), centre.y - R * 3 * math.cos(a), centre.z)
cam.rotation_euler = (centre - cam.location).to_track_quat("-Z", "Y").to_euler()
bpy.context.scene.camera = cam
bpy.context.view_layer.update()

# ortho fit from the projected bbox
from bpy_extras.object_utils import world_to_camera_view
cam_d.ortho_scale = diag
us, vs = [], []
for o in objs:
    for c in o.bound_box:
        p = world_to_camera_view(bpy.context.scene, cam, o.matrix_world @ mathutils.Vector(c))
        us.append(p.x)
        vs.append(p.y)
span = max(max(us) - min(us), max(vs) - min(vs))
cam_d.ortho_scale = diag * span / 0.92
cam_d.shift_x -= ((max(us) + min(us)) / 2 - 0.5)
cam_d.shift_y -= ((max(vs) + min(vs)) / 2 - 0.5)

sc = bpy.context.scene
sc.render.engine = "CYCLES"
sc.cycles.samples = SAMP
sc.cycles.use_denoising = False          # no OpenImageDenoiser in this container
sc.render.resolution_x = RES
sc.render.resolution_y = int(RES * 0.75)
sc.render.image_settings.file_format = "PNG"
sc.view_settings.view_transform = "Standard"   # never AgX
sc.view_settings.exposure = STOPS
sc.render.filepath = OUT
if os.path.exists(OUT):
    os.remove(OUT)
bpy.ops.render.render(write_still=True)

# MEASURE the exposure rather than asserting it. The first version of this file
# ran ~2 stops hot and clipped 17.8% of the car; a render that clips is not
# evidence, it is a white shape. The numbers are printed so the claim in the
# report is the measurement.
img = bpy.data.images.load(OUT)
px = list(img.pixels)
w, h = img.size
import numpy as _np
A = _np.asarray(px, dtype=_np.float32).reshape(h, w, 4)[:, :, :3]
srgb = _np.where(A <= 0.0031308, A * 12.92, 1.055 * _np.maximum(A, 0) ** (1 / 2.4) - 0.055)
srgb8 = _np.clip(_np.rint(srgb * 255), 0, 255).astype(int)
bg = srgb8[2, 2]
nonbg = (_np.abs(srgb8 - bg).sum(2) > 12)
clip = (srgb8 >= 254).all(2)
print("NATIVE_EXPOSURE stops=%.2f lscale=%.3f bg_srgb=%d expected=129 "
      "car_frac=%.3f clipped_frame=%.5f clipped_car=%.5f"
      % (STOPS, LSCALE, int(bg[0]), float(nonbg.mean()), float(clip.mean()),
         float(clip[nonbg].mean()) if nonbg.any() else 0.0))
print("NATIVE_RENDER_DONE", OUT, os.path.getsize(OUT) if os.path.exists(OUT) else "MISSING")
