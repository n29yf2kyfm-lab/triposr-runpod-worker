#!/usr/bin/env python3
"""studio_hero.py — a presentable studio render, not a diagnostic one.

eyeball_views.py exists to JUDGE a mesh: black background, flat key, no ground.
That is the right rig for finding defects and the wrong one for looking at a
car. This is the other one — neutral grey backdrop, a ground plane that takes a
contact shadow, a three-light setup, and the denoiser doing the heavy lifting.

WHY IT CAN EXIST NOW. Every render this project made before 2026-08-21 was
undenoised, because the container's Blender 4.0.2 is a stripped build with no
OpenImageDenoise on disk. 4.5.12 LTS ships it, so a clean image no longer costs
50+ samples. Measured on the merged Golf: 16 samples denoised beat 52 samples
undenoised. This rig therefore spends its budget on resolution and lighting
rather than on grinding out noise.

CAMERA IS DERIVED FROM THE MESH BBOX, never from the catalogue azimuth
convention — that convention is written for length-on-X catalogue cars and has
produced upside-down and side-on sheets twice. Which azimuth shows the front
differs per mesh; this file's `--az` is measured off the render, not assumed.
On the merged Golf the nose is at -X, so az 180 is the front and 215/225 are
the front three-quarters.

Standard view transform, never AgX: AgX has produced false verdicts three times
on this project, once clipping 42.58% of car pixels on an agent's first tiles.
The world background is 0.22 linear, which lands near sRGB 130 — check it if a
measurement is ever taken off these frames.

Run: blender -b --python studio_hero.py -- <in.glb> <outdir> [az1,az2,...]
Env: HERO_RES (1600), HERO_SAMPLES (64), HERO_EL (6 degrees)
"""
import math
import os
import sys

import bpy
import mathutils

argv = sys.argv[sys.argv.index("--") + 1:]
GLB, OUTD = argv[0], argv[1]
AZS = [float(a) for a in (argv[2].split(",") if len(argv) > 2 else ["215", "180", "270"])]
RES = int(os.environ.get("HERO_RES", "1600"))
SAMPLES = int(os.environ.get("HERO_SAMPLES", "64"))
EL = math.radians(float(os.environ.get("HERO_EL", "6")))

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
ctr = [(lo[i] + hi[i]) / 2 for i in range(3)]
ext = [hi[i] - lo[i] for i in range(3)]
diag = math.sqrt(sum(e * e for e in ext))
ground = lo[2]          # Blender is Z-up after the glTF import's Y-up convert

# BACKDROP. A plane rather than a world colour, so the car casts a real contact
# shadow — the single thing that stops a render looking like a cut-out. Sized
# off the mesh so it never runs out from under a long car.
bpy.ops.mesh.primitive_plane_add(size=diag * 12, location=(ctr[0], ctr[1], ground))
floor = bpy.context.object
fm = bpy.data.materials.new("Backdrop")
fm.use_nodes = True
bsdf = fm.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (0.34, 0.34, 0.35, 1)
bsdf.inputs["Roughness"].default_value = 0.62
floor.data.materials.append(fm)

world = bpy.data.worlds.new("W")
sc.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.22, 0.22, 0.23, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 1.0


def light(name, loc, energy, size):
    d = bpy.data.lights.new(name, type="AREA")
    d.energy = energy
    d.size = size
    ob = bpy.data.objects.new(name, d)
    sc.collection.objects.link(ob)
    ob.location = loc
    # aim at the car
    v = mathutils.Vector((ctr[0] - loc[0], ctr[1] - loc[1], ctr[2] - loc[2]))
    ob.rotation_euler = v.to_track_quat("-Z", "Y").to_euler()
    return ob


# Three-light studio. The key is deliberately NOT one-sided-hard: this project
# has a documented false-defect class where a one-sided key made a MAJORITY of
# cars read as having a 2-vs-2 brightness split by side, and those were all fine.
# A fill of roughly a third of the key kills that artefact.
key = diag * diag * 26
light("Key", (ctr[0] + diag, ctr[1] - diag, ground + diag * 1.15), key, diag * 0.9)
light("Fill", (ctr[0] - diag * 1.1, ctr[1] - diag * 0.7, ground + diag * 0.75), key * 0.34, diag * 1.2)
light("Rim", (ctr[0] - diag * 0.4, ctr[1] + diag * 1.2, ground + diag * 0.95), key * 0.5, diag * 0.8)

cam_d = bpy.data.cameras.new("C")
cam_d.lens = 60          # 85 cropped the car at this distance; 60 frames it
                         # whole without the nose distortion a wide lens gives
cam = bpy.data.objects.new("C", cam_d)
sc.collection.objects.link(cam)
sc.camera = cam

sc.render.engine = "CYCLES"
sc.cycles.device = "CPU"
sc.cycles.samples = SAMPLES
# Probe, don't assume — the stripped 4.0.2 raises here with an EMPTY enum, and a
# silent fallback would look identical to a successful upgrade in the frames.
try:
    sc.cycles.use_denoising = True
    sc.cycles.denoiser = "OPENIMAGEDENOISE"
    sc.view_layers[0].cycles.use_denoising = True
    print("HERO_DENOISE: ON")
except Exception as e:
    sc.cycles.use_denoising = False
    print(f"HERO_DENOISE: OFF — {type(e).__name__}: {e}")

sc.render.resolution_x = RES
sc.render.resolution_y = int(RES * 0.62)
sc.render.image_settings.file_format = "PNG"
sc.view_settings.view_transform = "Standard"
sc.render.film_transparent = False

os.makedirs(OUTD, exist_ok=True)
r = diag * 1.95   # 1.35 put the camera inside the framing and cropped
                  # the car — measured off the first render, not guessed
for az in AZS:
    a = math.radians(az)
    cam.location = (ctr[0] + r * math.cos(a) * math.cos(EL),
                    ctr[1] + r * math.sin(a) * math.cos(EL),
                    ground + ext[2] * 0.52 + r * math.sin(EL))
    look = mathutils.Vector((ctr[0], ctr[1], ground + ext[2] * 0.42))
    cam.rotation_euler = (look - cam.location).to_track_quat("-Z", "Y").to_euler()
    out = os.path.join(OUTD, f"hero_{int(az):03d}.png")
    if os.path.exists(out):
        os.remove(out)          # a stale frame from a died render reads as success
    sc.render.filepath = out
    bpy.ops.render.render(write_still=True)
    print(f"HERO_VIEW az={az:.0f} -> {out}")

print("STUDIO_HERO_DONE")
