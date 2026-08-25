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

CORRECTED 2026-08-25: "no EGL, so EEVEE cannot initialise" was true of the
container as shipped and is no longer true. install_blender.sh now installs
libegl1 + mesa, and EEVEE Next renders here — verified by pixels, not by exit
code (a 160px factory-startup frame came back with 132 unique colours and the
default cube visible; EGL_BAD_MATCH warnings print and are non-fatal). CYCLES
remains the engine THIS rig uses, because it is the verdict rig and its output
is what every material ruling in CLAUDE.md was calibrated against. EEVEE is now
available for a fast preview, not a swap-in for the eye.

WHAT DID CHANGE (2026-08-21): denoising is now ON when the binary supports it.
The container's system Blender 4.0.2 is a STRIPPED build with no
OpenImageDenoise on disk at all, so this file hardcoded `use_denoising = False`
and every render this project ever produced was undenoised — which is why the
sample counts here were 40-52 and the results were still grainy. 4.5.12 LTS
(pipeline/machine/install_blender.sh) ships OIDN, and measured on the merged
Golf through this very rig: 16 samples DENOISED is visibly cleaner than 52
samples undenoised, i.e. a 3.25x sample cut AND a better image.

It is probed, not assumed, and it falls back silently: a container that has not
run install_blender.sh still has the 4.0.2 binary, where setting the denoiser
raises and the render would otherwise die AFTER "Blender quit" prints, leaving
STALE FRAMES that read as a successful run. That failure mode is why this is a
try/except around a real assignment rather than a version check.

Run: blender -b --python eyeball_views.py -- <canon.glb> <outdir>
Env: EYEBALL_RES, EYEBALL_SAMPLES, EYEBALL_DENOISE=0 to force off
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

# A MISSING FILE DOES NOT SAY SO. Blender 5.2's glTF importer answers a
# nonexistent path with "Error: Please select a file", which reads like a
# changed operator signature rather than a missing file -- it cost three rounds
# of probing import_scene.gltf's parameters here before the file turned out to
# have been wiped by a container rollback. Check first and say what is wrong.
if not os.path.exists(GLB):
    raise SystemExit(f"REFUSED: no such file: {GLB}")
if os.path.getsize(GLB) < 64:
    raise SystemExit(f"REFUSED: {GLB} is {os.path.getsize(GLB)} bytes -- truncated or empty")
with open(GLB, "rb") as _f:
    if _f.read(4) != b"glTF":
        raise SystemExit(f"REFUSED: {GLB} is not a GLB (bad magic)")

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

# CYCLES DEVICE: GPU where one exists, CPU where one does not, decided by
# PROBING rather than by assuming (2026-08-25). This rig was hardcoded to CPU,
# which is correct for this container and wrong everywhere else — the RunPod
# render worker has OPTIX and render/handler.py has always used it, so the same
# sheet took minutes here that it takes seconds there, for no reason but a
# constant.
#
# Same OPTIX -> CUDA -> CPU order as render/handler.py:_enable_gpu, and the same
# reason for the order: OPTIX uses the RT cores and beats CUDA on this scene
# class. Falls back silently and prints which branch ran — a silent fallback and
# a working GPU produce identical frames, so the log line is the only evidence.
# EYEBALL_DEVICE=CPU forces CPU for an A/B.
def _pick_device():
    want = os.environ.get("EYEBALL_DEVICE", "AUTO").upper()
    if want == "CPU":
        return "CPU"
    try:
        bpy.ops.preferences.addon_enable(module="cycles")
    except Exception:
        pass
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
    except Exception:
        return "CPU"
    for dt in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = dt
            prefs.get_devices()
            on = False
            for d in prefs.devices:
                d.use = (d.type == dt)
                on = on or d.use
            if on:
                return dt
        except Exception:
            continue
    return "CPU"


_dev = _pick_device()
sc.cycles.device = "GPU" if _dev in ("OPTIX", "CUDA") else "CPU"
print(f"EYEBALL_DEVICE: {_dev} (cycles.device={sc.cycles.device})")
# PROBE, don't assume. On the stripped 4.0.2 this assignment raises and we fall
# back to the old undenoised path; on 4.5.12 it takes and the render is cleaner
# at a third of the samples. Printing which branch ran matters — a silent
# fallback would look identical to a successful upgrade in the output frames.
DENOISE = os.environ.get("EYEBALL_DENOISE", "1") == "1"
if DENOISE:
    try:
        sc.cycles.use_denoising = True
        sc.cycles.denoiser = "OPENIMAGEDENOISE"
        sc.view_layers[0].cycles.use_denoising = True
        print("EYEBALL_DENOISE: ON (OpenImageDenoise)")
    except Exception as e:
        sc.cycles.use_denoising = False
        sc.view_layers[0].cycles.use_denoising = False
        print(f"EYEBALL_DENOISE: OFF — {type(e).__name__}: {e}")
else:
    sc.cycles.use_denoising = False
    sc.view_layers[0].cycles.use_denoising = False
    print("EYEBALL_DENOISE: OFF (forced by env)")
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
