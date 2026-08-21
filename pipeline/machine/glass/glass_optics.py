#!/usr/bin/env python3
"""glass_optics.py — the two RENDER controls the glazing gate is allowed to trust.

blender -b -P glass_optics.py -- --in car.glb --out dir --tag v3 [--mode backlight|respray]

WHY THESE TWO AND NOTHING ELSE.  A production studio tile cannot witness glazing on this
car: render/handler.py force-writes transmission=1.0 onto any material NAMED glass-ish
and this car's glazing material is literally called `glass`, so the worker would
manufacture the very property under test (CLAUDE.md, 2026-08-11 owner ruling).  These two
controls are immune because neither asks the renderer what the material is:

  BACKLIGHT  an emissive MAGENTA plane behind the car.  Transparent glazing glows
             magenta; opaque glazing stays body-coloured.  Nothing about the material
             name enters it.
  RESPRAY    rewrite ONLY the material named `carpaint` to blue and re-render.  Body goes
             blue; glazing and tyres must not.  This is the arbiter CLAUDE.md installed
             after glass_probe passed a Pixal car whose windows were body texels
             ("gates + eye + texture all agreed and all three were wrong").

RIG DISCIPLINE, all of it paid for by this project already:
  * CYCLES only, and NO denoising -- this build has no OpenImageDenoiser and
    use_denoising=True raises AFTER "Blender quit" prints, leaving STALE FRAMES.  Target
    frames are deleted first and the script prints its OWN done marker.
  * view transform STANDARD, never AgX (AgX has produced false white-tyre verdicts three
    times here).  Exposure is verified NUMERICALLY: a 0.22 world background must land
    near sRGB 130, and the clipped fraction is reported, not assumed.
  * BLEND glazing dithers in a local Cycles render at low sample counts (machine v6), so
    samples default to 96, not 1.
  * The car is NOT grounded and is pitched nose-up ~4.1 deg (rear tyres y~0.000/0.015,
    front y~0.183/0.190 -- measured with node transforms APPLIED).  The backlight plane
    is therefore placed from the mesh bounds, never from an assumed y=0 ground.
"""
import json
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

argv = sys.argv[sys.argv.index("--") + 1:]


def arg(f, d=None):
    return argv[argv.index(f) + 1] if f in argv else d


SRC = arg("--in"); OUT = arg("--out", "/tmp/optics"); TAG = arg("--tag", "v")
MODE = arg("--mode", "backlight")
RES = int(arg("--res", "1000"))
SAMPLES = int(arg("--samples", "96"))

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)
objs = [o for o in bpy.data.objects if o.type == "MESH"]

mn = Vector((1e9,) * 3); mx = Vector((-1e9,) * 3)
for o in objs:
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c)
        mn = Vector((min(mn[i], w[i]) for i in range(3)))
        mx = Vector((max(mx[i], w[i]) for i in range(3)))
ctr = (mn + mx) / 2
diag = (mx - mn).length
print(f"BOUNDS blender-space min={list(mn)} max={list(mx)}")

sc = bpy.context.scene
sc.render.engine = "CYCLES"
sc.cycles.samples = SAMPLES
sc.cycles.use_denoising = False              # NO OpenImageDenoiser in this container
sc.cycles.max_bounces = 8
sc.cycles.transmission_bounces = 12
sc.cycles.transparent_max_bounces = 16
sc.view_settings.view_transform = "Standard"  # never AgX
sc.view_settings.look = "None"
sc.view_settings.exposure = 0.0
sc.render.resolution_x = sc.render.resolution_y = RES
sc.render.image_settings.file_format = "PNG"
sc.render.film_transparent = False

w = bpy.data.worlds.new("W")
w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.22, 0.22, 0.22, 1)
w.node_tree.nodes["Background"].inputs[1].default_value = 1.0
sc.world = w

if MODE == "respray":
    hit = []
    for m in bpy.data.materials:
        if m.name.split(".")[0] == "carpaint" and m.use_nodes:
            for n in m.node_tree.nodes:
                if n.type == "BSDF_PRINCIPLED":
                    n.inputs["Base Color"].default_value = (0.03, 0.08, 0.75, 1.0)
                    hit.append(m.name)
    print("RESPRAY applied to materials:", hit)
    assert hit, "no material named carpaint -- respray control cannot run"
else:
    # magenta emissive backdrop BEHIND the car, sized from the mesh bounds
    bpy.ops.mesh.primitive_plane_add(size=diag * 2.0)
    pl = bpy.context.object
    pl.name = "BACKLIGHT"
    pl.location = (ctr.x, mn.y - diag * 0.30, ctr.z)
    pl.rotation_euler = (math.radians(90), 0, 0)
    m = bpy.data.materials.new("BL")
    m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    e = nt.nodes.new("ShaderNodeEmission")
    e.inputs[0].default_value = (1.0, 0.0, 1.0, 1.0)
    e.inputs[1].default_value = 6.0
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(e.outputs[0], o.inputs[0])
    pl.data.materials.append(m)
    print(f"BACKLIGHT plane at y={pl.location.y:.3f}, size {diag*2:.2f}")

# key light so the body is readable without blowing out (verified numerically below)
sun = bpy.data.lights.new("K", type="SUN"); sun.energy = 2.2
so = bpy.data.objects.new("K", sun); sc.collection.objects.link(so)
so.rotation_euler = (math.radians(52), 0, math.radians(35))

cam_d = bpy.data.cameras.new("C"); cam_d.type = "ORTHO"; cam_d.ortho_scale = diag * 0.60
cam = bpy.data.objects.new("C", cam_d); sc.collection.objects.link(cam); sc.camera = cam

VIEWS = {"front34L": (-0.80, 0.22, -0.58), "sideL": (0.0, 0.10, -1.0),
         "front": (-1.0, 0.16, 0.0), "rear34R": (0.80, 0.22, 0.58)}
os.makedirs(OUT, exist_ok=True)
done = []
for name, gv in VIEWS.items():
    d = Vector((gv[0], -gv[2], gv[1])).normalized()
    cam.location = ctr + d * diag * 1.6
    fwd = -d
    up = Vector((0, 0, 1))
    right = fwd.cross(up).normalized()
    trueup = right.cross(fwd).normalized()
    cam.matrix_world = Matrix((
        (right.x, trueup.x, -fwd.x, cam.location.x),
        (right.y, trueup.y, -fwd.y, cam.location.y),
        (right.z, trueup.z, -fwd.z, cam.location.z),
        (0, 0, 0, 1)))
    p = os.path.join(OUT, f"{TAG}_{MODE}_{name}.png")
    if os.path.exists(p):
        os.remove(p)
    sc.render.filepath = p
    bpy.ops.render.render(write_still=True)
    done.append(name)
    print(f"RENDERED {name} -> {p}", flush=True)

print("GLASS_OPTICS_DONE " + ",".join(done))
