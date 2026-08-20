"""control_respray.py -- Gate 3 criterion 6: do the components hold their own
colour through a body respray?

This is the test label-paint can never pass.  It reproduces what production
actually does: the render worker / colour_variants target the material NAMED
`carpaint` and set its colour.  Here the carpaint Principled BSDF is driven to
a flat colour with its baked texture DISCONNECTED -- a respray to a solid
colour -- and the fascia is then measured, not eyeballed.

The car's own baked texture is RED, so red is useless as a control colour;
BLUE is used (and magenta for the second control), per the project's own
"nothing on a car is magenta" reasoning.

Camera is ORTHOGRAPHIC at az 270 (the straight-front view on this car -- the
nose is at -X), elevation 0, so world (glTF y,z) maps linearly to pixels and
sample boxes can be given in metres.

Run: blender -b --python control_respray.py -- <in.glb> <outdir> <tag> <r,g,b>
"""
import bpy
import sys
import os
import json
import math
import mathutils

argv = sys.argv[sys.argv.index("--") + 1:]
INP, OUT, TAG = argv[0], argv[1], argv[2]
COL = tuple(float(v) for v in (argv[3] if len(argv) > 3 else "0.03,0.09,0.65").split(","))
os.makedirs(OUT, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=INP)
meshes = [o for o in bpy.data.objects if o.type == 'MESH']

resprayed = []
for m in bpy.data.materials:
    if m.name.split(".")[0] != "carpaint":
        continue
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    if b is None:
        continue
    for lk in list(b.inputs["Base Color"].links):
        m.node_tree.links.remove(lk)
    b.inputs["Base Color"].default_value = (*COL, 1)
    b.inputs["Metallic"].default_value = 0.0
    b.inputs["Roughness"].default_value = 0.26
    resprayed.append(m.name)
print("RESPRAYED:", resprayed)

mn = mathutils.Vector((1e9,) * 3)
mx = mathutils.Vector((-1e9,) * 3)
for o in meshes:
    for c in o.bound_box:
        w = o.matrix_world @ mathutils.Vector(c)
        mn = mathutils.Vector(map(min, mn, w))
        mx = mathutils.Vector(map(max, mx, w))

scn = bpy.context.scene
scn.render.engine = 'CYCLES'
scn.cycles.device = 'CPU'
scn.cycles.samples = 48
scn.cycles.use_denoising = False
scn.view_settings.view_transform = 'Standard'
W, HH = 1000, 700
scn.render.resolution_x, scn.render.resolution_y = W, HH

world = bpy.data.worlds.new("w")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.55, 0.55, 0.57, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.6
scn.world = world
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
scn.collection.objects.link(sun)
sun.data.energy = 2.2
sun.rotation_euler = (math.radians(46), 0, math.radians(35))

cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
scn.collection.objects.link(cam)
scn.camera = cam
cam.data.type = 'ORTHO'
SCALE = 2.30
cam.data.ortho_scale = SCALE
# glTF -> Blender is (x, y, z) -> (x, -z, y); nose is at glTF -X
TGT_GY = mn.z + 0.36 * (mx.z - mn.z)      # Blender z == glTF y
TGT_GZ = 0.0
cam.location = (mn.x - 3.0, -TGT_GZ, TGT_GY)
cam.rotation_euler = (math.radians(90), 0, math.radians(-90))
fp = os.path.join(OUT, f"{TAG}_respray.png")
scn.render.filepath = fp
bpy.ops.render.render(write_still=True)

# ---- measure, do not eyeball -------------------------------------------
s = SCALE / W                              # metres per pixel


def box(gy0, gy1, gz0, gz1):
    u0 = int(W / 2 + gz0 / s); u1 = int(W / 2 + gz1 / s)
    v0 = int(HH / 2 - gy1 / s + TGT_GY / s); v1 = int(HH / 2 - gy0 / s + TGT_GY / s)
    return max(min(u0, u1), 0), max(min(v0, v1), 0), min(max(u0, u1), W), min(max(v0, v1), HH)


SAMPLES = {
    # body reference points, chosen to sit on shell that no component covers
    "body_bonnet":   (0.88, 0.95, -0.15, 0.15),
    "body_wing":     (0.700, 0.735, 0.50, 0.64),
    "body_bumperout": (0.610, 0.660, 0.34, 0.44),
    # components
    "lamp_R":        (0.775, 0.805, 0.42, 0.58),
    "lamp_L":        (0.775, 0.805, -0.58, -0.42),
    "grille_floor":  (0.790, 0.800, -0.20, -0.10),
    "grille_slat":   (0.7745, 0.7785, -0.20, -0.10),
    "badge":         (0.780, 0.808, -0.030, 0.030),
    "plate":         (0.610, 0.660, -0.18, 0.18),
    "intake":        (0.480, 0.530, -0.30, 0.30),
}
img = bpy.data.images.load(fp)
px = list(img.pixels)
res = {}
for name, (gy0, gy1, gz0, gz1) in SAMPLES.items():
    u0, v0, u1, v1 = box(gy0, gy1, gz0, gz1)
    acc = [0.0, 0.0, 0.0]
    n = 0
    for v in range(v0, v1):
        row = HH - 1 - v                  # Blender image origin is bottom-left
        for u in range(u0, u1):
            i = (row * W + u) * 4
            acc[0] += px[i]; acc[1] += px[i + 1]; acc[2] += px[i + 2]
            n += 1
    if n == 0:
        continue
    rgb = [round(255 * (c / n) ** (1 / 2.2), 1) for c in acc]
    # "control excess" = how far this patch moved toward the control colour,
    # measured against the OTHER two channels.  Works for blue and magenta.
    ci = max(range(3), key=lambda k: COL[k])
    other = [k for k in range(3) if k != ci]
    exc = round(rgb[ci] - (rgb[other[0]] + rgb[other[1]]) / 2, 1)
    res[name] = {"rgb": rgb, "control_excess": exc, "px": n}
    print(f"  {name:14s} sRGB {rgb}  control-excess {exc:+.1f}")

json.dump({"colour": COL, "resprayed": resprayed, "samples": res},
          open(os.path.join(OUT, f"{TAG}_respray.json"), "w"), indent=1)
print("CONTROL_DONE")
