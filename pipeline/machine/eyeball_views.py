#!/usr/bin/env python3
"""eyeball_views.py — seven views of a canonicalised car, for the EYE.

Every numeric gate in this project is documented as a candidate finder, never
a verdict: crease_density counts sharp geometry rather than good geometry, the
wave sheet forges clear glass onto any glass-NAMED material, and coverage is
anti-correlated with the tyre defect. The verdict is the render. This is the
cheapest honest render.

Camera is derived from the mesh bounding box rather than from the catalogue
azimuth convention, which is written for length-on-X catalogue cars and has
produced upside-down and side-on sheets twice. Seven azimuths so BOTH ends are
always visible: canon.py deliberately does not resolve nose direction, so
which azimuth shows the front differs per mesh and must be read off the sheet.

Kept in the REPO, not a scratchpad: the container has rolled back repeatedly
and taken scratchpad tooling with it. Anything worth running twice belongs in
git.

Blender here has no EGL, so EEVEE cannot initialise — CYCLES with denoising
OFF (this build has no OIDN either) is the only combination that renders.

Run: blender -b --python eyeball_views.py -- <canon.glb> <outdir>
"""
import bpy
import math
import os
import sys

import mathutils

argv = sys.argv[sys.argv.index("--") + 1:]
GLB, OUTD = argv[0], argv[1]
RES = int(os.environ.get("EYEBALL_RES", "1100"))
SAMPLES = int(os.environ.get("EYEBALL_SAMPLES", "40"))

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
cam.data.lens = 80          # long lens: minimal perspective distortion

key = bpy.data.objects.new("key", bpy.data.lights.new("key", "SUN"))
key.data.energy = 4.0
key.data.angle = math.radians(12)
sc.collection.objects.link(key)
key.rotation_euler = (math.radians(50), 0, math.radians(35))
# FILL FROM THE OTHER SIDE. The production rig's key is one-sided, which makes
# a MAJORITY of cars read as a 2-vs-2 brightness split by side and has been
# misread as a per-side wheel defect more than once. A fill kills that
# artefact at the source.
fill = bpy.data.objects.new("fill", bpy.data.lights.new("fill", "SUN"))
fill.data.energy = 1.6
sc.collection.objects.link(fill)
fill.rotation_euler = (math.radians(60), 0, math.radians(210))

sc.render.engine = "CYCLES"
sc.cycles.samples = SAMPLES
sc.cycles.use_denoising = False
sc.view_layers[0].cycles.use_denoising = False
sc.render.film_transparent = True
sc.render.image_settings.file_format = "PNG"
sc.render.image_settings.color_mode = "RGBA"
sc.render.resolution_x = RES
sc.render.resolution_y = RES

os.makedirs(OUTD, exist_ok=True)
for name, az, el in (("a000", 0, 0.22), ("a045", 45, 0.30),
                     ("a090", 90, 0.22), ("a135", 135, 0.30),
                     ("a180", 180, 0.22), ("a225", 225, 0.30),
                     ("a315", 315, 0.30)):
    r = math.radians(az)
    cam.location = ctr + mathutils.Vector((2.3 * diag * math.cos(r),
                                           2.3 * diag * math.sin(r),
                                           el * diag * 3))
    d = (ctr - cam.location).normalized()
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    sc.render.filepath = os.path.join(OUTD, name + ".png")
    bpy.ops.render.render(write_still=True)
print("EYEBALL_VIEWS_DONE")
