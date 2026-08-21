#!/usr/bin/env python3
"""lineup.py — several cars in ONE scene, at ONE scale, under ONE camera.

WHY THIS AND NOT THREE SEPARATE RENDERS. studio_hero.py derives its camera from
each mesh's own bounding box, so every car fills the frame regardless of its
actual size. That is right for looking at one car and WRONG for comparing
several: it silently normalises away scale, and the meshes here are not at the
same scale at all — the Pixal car is metric (4.234 m), while the Omni and hybrid
outputs come back normalised (1.999 m and 1.002 m). Three auto-framed renders
make them look comparable when they are not.

So: every car is scaled to the SAME true length, grounded on the SAME plane,
spaced along Z, and shot with ONE camera. Whatever differs in the image after
that is the mesh.

The lighting is deliberately the three-point rig from studio_hero rather than a
single key. This project has a documented false-defect class where a one-sided
key made a MAJORITY of good cars read as having a 2-vs-2 brightness split by
side; a fill at roughly a third of the key removes it.

Standard view transform, never AgX — AgX has produced false verdicts three times
here, once clipping 42.58% of car pixels.

Run: blender -b --python lineup.py -- out.png L=4.284 a.glb b.glb c.glb
Env: LINE_RES (2600), LINE_SAMPLES (72), LINE_AZ (215), LINE_EL (7)
"""
import math
import os
import sys

import bpy
import mathutils

argv = sys.argv[sys.argv.index("--") + 1:]
OUT = argv[0]
TARGET_L = float(argv[1].split("=")[1]) if argv[1].startswith("L=") else 4.284
GLBS = argv[2:]
RES = int(os.environ.get("LINE_RES", "2600"))
SAMPLES = int(os.environ.get("LINE_SAMPLES", "72"))
AZ = math.radians(float(os.environ.get("LINE_AZ", "215")))
EL = math.radians(float(os.environ.get("LINE_EL", "7")))

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene


def bounds(objs):
    lo = [1e18] * 3
    hi = [-1e18] * 3
    for o in objs:
        for c in o.bound_box:
            w = o.matrix_world @ mathutils.Vector(c)
            for i in range(3):
                lo[i] = min(lo[i], w[i])
                hi[i] = max(hi[i], w[i])
    return lo, hi


loaded = []
for g in GLBS:
    before = set(sc.objects)
    bpy.ops.import_scene.gltf(filepath=g)
    objs = [o for o in set(sc.objects) - before if o.type == "MESH"]
    if not objs:
        print(f"LINEUP_SKIP {g} — no mesh objects")
        continue
    loaded.append((os.path.basename(g), objs))

if not loaded:
    raise SystemExit("LINEUP_FAIL: nothing loaded")

# One empty per car so a whole car scales and moves as a unit. Parenting rather
# than editing vertices keeps every material and node name untouched, which
# matters because these files are the actual deliverables.
pitch = TARGET_L * 1.28
rigs = []
for idx, (name, objs) in enumerate(loaded):
    lo, hi = bounds(objs)
    length = max(hi[0] - lo[0], hi[1] - lo[1])   # longest horizontal axis
    s = TARGET_L / length if length > 1e-9 else 1.0
    piv = bpy.data.objects.new(f"rig_{idx}", None)
    sc.collection.objects.link(piv)
    for o in objs:
        if o.parent is None:
            o.parent = piv
            o.matrix_parent_inverse = piv.matrix_world.inverted()
    piv.scale = (s, s, s)
    bpy.context.view_layer.update()
    lo2, hi2 = bounds(objs)
    ctr = [(lo2[i] + hi2[i]) / 2 for i in range(3)]
    # centre on X and Y, sit on Z=0, then step along Y so the row runs across
    # the frame rather than into it
    piv.location = (piv.location[0] - ctr[0],
                    piv.location[1] - ctr[1] + (idx - (len(loaded) - 1) / 2) * pitch,
                    piv.location[2] - lo2[2])
    bpy.context.view_layer.update()
    lo3, hi3 = bounds(objs)
    rigs.append((name, s, length, lo3, hi3))
    print(f"LINEUP_FIT {name}  native_len={length:.3f}  scale={s:.4f}  "
          f"z_min={lo3[2]:+.4f}")

lo, hi = bounds([o for _n, objs in loaded for o in objs])
ctr = [(lo[i] + hi[i]) / 2 for i in range(3)]
span = max(hi[i] - lo[i] for i in range(3))

bpy.ops.mesh.primitive_plane_add(size=span * 6, location=(ctr[0], ctr[1], 0))
fl = bpy.context.object
fm = bpy.data.materials.new("Backdrop")
fm.use_nodes = True
b = fm.node_tree.nodes["Principled BSDF"]
b.inputs["Base Color"].default_value = (0.33, 0.335, 0.345, 1)
b.inputs["Roughness"].default_value = 0.62
fl.data.materials.append(fm)

w = bpy.data.worlds.new("W")
sc.world = w
w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.215, 0.218, 0.225, 1)


def light(nm, loc, energy, size):
    d = bpy.data.lights.new(nm, type="AREA")
    d.energy, d.size = energy, size
    ob = bpy.data.objects.new(nm, d)
    sc.collection.objects.link(ob)
    ob.location = loc
    v = mathutils.Vector((ctr[0] - loc[0], ctr[1] - loc[1], ctr[2] - loc[2]))
    ob.rotation_euler = v.to_track_quat("-Z", "Y").to_euler()


key = span * span * 22
light("Key", (ctr[0] + span * 0.8, ctr[1] - span * 0.8, span * 0.75), key, span * 0.7)
light("Fill", (ctr[0] - span * 0.9, ctr[1] - span * 0.6, span * 0.5), key * 0.34, span * 0.9)
light("Rim", (ctr[0] - span * 0.35, ctr[1] + span * 0.9, span * 0.65), key * 0.5, span * 0.6)

cd = bpy.data.cameras.new("C")
cd.lens = 78          # long enough that the far car is not perspective-shrunk
cam = bpy.data.objects.new("C", cd)
sc.collection.objects.link(cam)
sc.camera = cam
r = span * 1.42
cam.location = (ctr[0] + r * math.cos(AZ) * math.cos(EL),
                ctr[1] + r * math.sin(AZ) * math.cos(EL),
                (hi[2] - lo[2]) * 0.55 + r * math.sin(EL))
look = mathutils.Vector((ctr[0], ctr[1], (hi[2] - lo[2]) * 0.42))
cam.rotation_euler = (look - cam.location).to_track_quat("-Z", "Y").to_euler()

sc.render.engine = "CYCLES"
sc.cycles.device = "CPU"
sc.cycles.samples = SAMPLES
try:
    sc.cycles.use_denoising = True
    sc.cycles.denoiser = "OPENIMAGEDENOISE"
    sc.view_layers[0].cycles.use_denoising = True
    print("LINEUP_DENOISE: ON")
except Exception as e:
    sc.cycles.use_denoising = False
    print(f"LINEUP_DENOISE: OFF — {type(e).__name__}: {e}")

sc.render.resolution_x = RES
sc.render.resolution_y = int(RES * 0.40)
sc.view_settings.view_transform = "Standard"
sc.render.image_settings.file_format = "PNG"
if os.path.exists(OUT):
    os.remove(OUT)          # a stale frame from a died render reads as success
sc.render.filepath = OUT
bpy.ops.render.render(write_still=True)
print("LINEUP_DONE", OUT)
