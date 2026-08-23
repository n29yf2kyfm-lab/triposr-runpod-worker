#!/usr/bin/env python3
"""gen_plate.py — one clean reference frame for an image-to-3D model.

An image-to-3D model wants the object CENTRED on a plain field. A studio plate
with a floor hands it a slab to reconstruct: the Objaverse screen in this repo
turned up photogrammetry scans that had baked their own tarmac into the mesh,
and giving a generator the same thing invites the same result. So: no ground
plane, no contact shadow, flat neutral world, long lens.

Kept in the repo because the container has rolled back six times in one session
and taken every scratchpad script with it.

Run: blender -b --python gen_plate.py -- <car.glb> <out.png> <azimuth>
Env: PLATE_RES (768) · PLATE_SAMPLES (40)
"""
import math
import os
import sys

import bpy
import mathutils

argv = sys.argv[sys.argv.index("--") + 1:]
GLB, OUT = argv[0], argv[1]
AZ = float(argv[2]) if len(argv) > 2 else 215.0
RES = int(os.environ.get("PLATE_RES", "768"))
SAMPLES = int(os.environ.get("PLATE_SAMPLES", "40"))

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=GLB)
sc = bpy.context.scene

lo = [1e9] * 3
hi = [-1e9] * 3
for o in sc.objects:
    if o.type != "MESH":
        continue
    for c in o.bound_box:
        w = o.matrix_world @ mathutils.Vector(c)
        for i in range(3):
            lo[i] = min(lo[i], w[i])
            hi[i] = max(hi[i], w[i])
if lo[0] > hi[0]:
    raise SystemExit(f"REFUSED: no mesh geometry in {GLB}")
ctr = mathutils.Vector([(lo[i] + hi[i]) / 2 for i in range(3)])
diag = max(hi[i] - lo[i] for i in range(3))

cam = bpy.data.objects.new("c", bpy.data.cameras.new("c"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.lens = 60
# a non-metric model (centimetres, or a 0.05-unit export) renders BLANK against
# Blender's default 100m clip end -- that has cost a wasted render here before
cam.data.clip_end = diag * 60
r = math.radians(AZ)
cam.location = ctr + mathutils.Vector((2.0 * diag * math.cos(r),
                                       2.0 * diag * math.sin(r),
                                       0.30 * diag))
cam.rotation_euler = (ctr - cam.location).normalized().to_track_quat("-Z", "Y").to_euler()

world = bpy.data.worlds.new("w")
sc.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.55, 0.55, 0.55, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 1.0

for nm, rot, energy in (("key", (math.radians(52), 0, math.radians(40)), 3.2),
                        ("fill", (math.radians(62), 0, math.radians(215)), 1.5)):
    L = bpy.data.objects.new(nm, bpy.data.lights.new(nm, "SUN"))
    L.data.energy = energy
    L.data.angle = math.radians(14)
    sc.collection.objects.link(L)
    L.rotation_euler = rot

sc.render.engine = "CYCLES"
sc.cycles.device = "CPU"
sc.cycles.samples = SAMPLES
try:
    sc.cycles.use_denoising = True
    sc.cycles.denoiser = "OPENIMAGEDENOISE"
    sc.view_layers[0].cycles.use_denoising = True
except Exception as e:
    print(f"PLATE_DENOISE off: {type(e).__name__}")
sc.view_settings.view_transform = "Standard"     # never AgX
sc.render.film_transparent = False
sc.render.resolution_x = sc.render.resolution_y = RES
sc.render.image_settings.file_format = "PNG"
sc.render.filepath = OUT
bpy.ops.render.render(write_still=True)
print("PLATE_DONE", OUT)
