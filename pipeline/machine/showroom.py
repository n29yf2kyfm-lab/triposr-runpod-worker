#!/usr/bin/env python3
"""showroom.py — beauty + diagnostic renders on a seamless studio cyclorama.

WHY THIS EXISTS. Every ad-hoc rig written in this project has repeated the
same three faults, and each one cost a review round:

  * FRAMING FROM THE BOUNDING SPHERE. The sphere's radius is set by the body
    diagonal and is far larger than the silhouette from any real camera
    angle, so the car lands tiny in the middle of the plate. Fit the car's
    own projected extent instead. (Same family as the recorded "a close-up
    is a narrower FOV, not a nearer camera" bug.)
  * EXPOSURE BY EYE. Lights scaled by some power of the scene size blow the
    paint to pure white, and the blown highlight then gets reported as a
    texture defect -- it has happened here twice (the AgX white-tyre episode
    and the Clio roof). This rig auto-exposes NUMERICALLY, in BOTH
    directions, targeting the specular tail just under clipping, and prints
    the clipped fraction for every frame it writes.
  * A FLAT GROUND PLANE, which puts a hard horizon line across the plate and
    reads as unfinished. A real studio uses a cyclorama: floor, a large
    fillet radius, and a wall, with no visible seam. Built here as a surface
    of revolution so it is seamless at EVERY azimuth, not just the first one.

DIAGNOSTIC PASSES are first-class, not an afterthought -- the production
brief requires them and a beauty render on a black car hides exactly the
defects worth finding (this is why "black paint conceals surface defects"
is a fair criticism of any beauty-only sheet):

  beauty  textured, studio lighting
  clay    one neutral matte material -- surface, waviness and topology show
  matid   flat emission per material -- which faces carry which label
  normal  world-space normal as colour -- normal/shading faults
  wire    clay + wireframe overlay -- topology density and flow

Run:
  blender -b --python showroom.py -- <in.glb> <outdir> [modes] [views]
    modes: comma list of beauty,clay,matid,normal,wire   (default: all)
    views: comma list of named views                     (default: all)
"""
import math
import os
import sys

import bpy
import mathutils

argv = sys.argv[sys.argv.index("--") + 1:]
INP, OUTD = argv[0], argv[1]
MODES = (argv[2].split(",") if len(argv) > 2
         else ["beauty", "clay", "matid", "normal", "wire"])
VIEW_FILTER = argv[3].split(",") if len(argv) > 3 else None

LENS = float(os.environ.get("SHOW_LENS", "58"))
MARGIN = float(os.environ.get("SHOW_MARGIN", "1.06"))   # 1.0 = car fills frame
CLIP_MAX = float(os.environ.get("SHOW_CLIP_MAX", "0.12"))
TARGET_P999 = float(os.environ.get("SHOW_TARGET", "0.90"))
SAMPLES = int(os.environ.get("SHOW_SAMPLES", "128"))
RES_X = int(os.environ.get("SHOW_RES_X", "1600"))
RES_Y = int(os.environ.get("SHOW_RES_Y", "1100"))

# EIGHT views, both sides. Six was one angle short of proving the car:
# a single front three-quarter is exactly the evidence standard this repo
# keeps failing on ("only one angle is proven"), and a one-sided set cannot
# show a left/right defect at all — which matters here, where the headlamp
# label is 2x better on the right than the left.
VIEWS = [("front34_R", 38, 10), ("side_R", 90, 4), ("rear34_R", 214, 11),
         ("rear", 180, 3), ("rear34_L", 146, 11), ("side_L", 270, 4),
         ("front34_L", 322, 10), ("front", 0, 3)]
if VIEW_FILTER:
    VIEWS = [v for v in VIEWS if v[0] in VIEW_FILTER]

# ---------------------------------------------------------------- scene ----
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=INP)

# HONOUR glTF SINGLE-SIDED. Cycles ignores use_backface_culling (recorded
# lesson), so every render this rig made showed backfaces a compliant viewer
# culls. That cut both ways on the v3.1 Golf: it painted a mirrored plate
# "defect" that customers never see, and it HID the hollow-cabin defect
# customers do see (far-side arch and backdrop visible through the glass).
# A render that does not match the serving viewer is not evidence. The only
# culling Cycles respects is a shader: mix Transparent on Backfacing, applied
# exactly where the importer set the culling flag from doubleSided=false.
_culled = 0
for _m in bpy.data.materials:
    if not _m.use_nodes or not getattr(_m, "use_backface_culling", False):
        continue
    _nt = _m.node_tree
    _out = next(n for n in _nt.nodes if n.type == "OUTPUT_MATERIAL"
                and n.inputs["Surface"].links)
    _src = _out.inputs["Surface"].links[0].from_node
    _geo = _nt.nodes.new("ShaderNodeNewGeometry")
    _tr = _nt.nodes.new("ShaderNodeBsdfTransparent")
    _mix = _nt.nodes.new("ShaderNodeMixShader")
    _nt.links.new(_geo.outputs["Backfacing"], _mix.inputs[0])
    _nt.links.new(_src.outputs[0], _mix.inputs[1])
    _nt.links.new(_tr.outputs[0], _mix.inputs[2])
    _nt.links.new(_mix.outputs[0], _out.inputs["Surface"])
    _culled += 1
print(f"BACKFACE CULLING honoured on {_culled} single-sided material(s)")
CAR = [o for o in bpy.data.objects if o.type == "MESH"]
pts = [o.matrix_world @ v.co for o in CAR for v in o.data.vertices]
mn = [min(p[i] for p in pts) for i in range(3)]
mx = [max(p[i] for p in pts) for i in range(3)]
ctr = [(a + b) / 2 for a, b in zip(mn, mx)]
sp = [mx[i] - mn[i] for i in range(3)]
L = max(sp[0], sp[1])
print(f"CAR extents {sp[0]:.3f} x {sp[1]:.3f} x {sp[2]:.3f}")

sc = bpy.context.scene
sc.render.engine = "CYCLES"
sc.cycles.samples = SAMPLES
try:
    sc.cycles.use_denoising = True
    print("DENOISE: ON")
except TypeError:
    print("DENOISE: OFF (no OIDN in this build)")
sc.view_settings.view_transform = "Standard"
sc.render.resolution_x, sc.render.resolution_y = RES_X, RES_Y
sc.render.film_transparent = False
sc.cycles.transparent_max_bounces = 24      # stacked glazing must not go black
sc.cycles.transmission_bounces = 16


def cyclorama(radius, height, fillet, segs=96, rings=24):
    """Surface of revolution: flat floor -> quarter-arc fillet -> wall.
    Seamless from every azimuth, which a plane + backdrop is not."""
    prof = []
    for i in range(6):                                   # floor
        prof.append((radius * i / 5.0, 0.0))
    for i in range(1, rings + 1):                        # fillet
        a = (math.pi / 2) * i / rings
        prof.append((radius + fillet * math.sin(a), fillet * (1 - math.cos(a))))
    for i in range(1, 7):                                # wall
        prof.append((radius + fillet, fillet + (height - fillet) * i / 6.0))
    verts, faces = [], []
    for s in range(segs):
        th = 2 * math.pi * s / segs
        cs, sn = math.cos(th), math.sin(th)
        for (r, y) in prof:
            verts.append((ctr[0] + r * cs, ctr[1] + r * sn, mn[2] + y))
    P = len(prof)
    for s in range(segs):
        s2 = (s + 1) % segs
        for k in range(P - 1):
            a = s * P + k
            b = s * P + k + 1
            c = s2 * P + k + 1
            d = s2 * P + k
            faces.append((a, b, c, d))
    me = bpy.data.meshes.new("cyc")
    me.from_pydata(verts, [], faces)
    me.validate()
    ob = bpy.data.objects.new("cyc", me)
    bpy.context.collection.objects.link(ob)
    for p in ob.data.polygons:
        p.use_smooth = True
    return ob


CYC = cyclorama(radius=L * 1.9, height=L * 2.2, fillet=L * 1.5)
cyc_mat = bpy.data.materials.new("cyc")
cyc_mat.use_nodes = True
cb = cyc_mat.node_tree.nodes["Principled BSDF"]
cb.inputs["Base Color"].default_value = (0.62, 0.62, 0.635, 1)
cb.inputs["Roughness"].default_value = 0.62
CYC.data.materials.append(cyc_mat)

wd = bpy.data.worlds.new("w")
sc.world = wd
wd.use_nodes = True
wd.node_tree.nodes["Background"].inputs[0].default_value = (0.34, 0.35, 0.37, 1)

LIGHTS = []


def area(name, loc, rot, size, energy):
    ld = bpy.data.lights.new(name, "AREA")
    ld.size = size
    ld.energy = energy
    ob = bpy.data.objects.new(name, ld)
    ob.location, ob.rotation_euler = loc, rot
    bpy.context.collection.objects.link(ob)
    LIGHTS.append(ld)
    return ob


# broad softboxes: a black car needs big sources or it reads as a silhouette
area("key", (ctr[0] + L * 1.1, ctr[1] - L * 1.2, ctr[2] + L * 1.3),
     (math.radians(50), 0, math.radians(43)), L * 2.4, L * L * 26)
area("fill", (ctr[0] - L * 1.4, ctr[1] - L * 1.0, ctr[2] + L * 0.8),
     (math.radians(66), 0, math.radians(-55)), L * 2.6, L * L * 11)
area("rim", (ctr[0] - L * 0.8, ctr[1] + L * 1.5, ctr[2] + L * 1.2),
     (math.radians(58), 0, math.radians(202)), L * 2.0, L * L * 16)
area("top", (ctr[0], ctr[1], ctr[2] + L * 1.9), (0, 0, 0), L * 2.6, L * L * 13)
BASE = [ld.energy for ld in LIGHTS]

cd = bpy.data.cameras.new("cam")
cd.lens = LENS
cam = bpy.data.objects.new("cam", cd)
bpy.context.collection.objects.link(cam)
sc.camera = cam

sensor = cd.sensor_width
aspect = RES_X / RES_Y
hfov = 2 * math.atan(sensor / (2 * LENS))
vfov = 2 * math.atan(math.tan(hfov / 2) / aspect)
aim_z = mn[2] + sp[2] * 0.47


def place(az, el):
    """Distance solved PER VIEW from the car's projected extent at that
    azimuth, so a side view (full length) pulls back and a front view
    (width only) comes in close. A single global distance framed the
    end-on views tiny."""
    a, e = math.radians(az), math.radians(el)
    # horizontal extent presented to the camera at this azimuth
    w = abs(sp[0] * math.sin(a)) + abs(sp[1] * math.cos(a))
    d = MARGIN * max(0.5 * w / math.tan(hfov / 2),
                     0.5 * sp[2] / math.tan(vfov / 2))
    cam.location = (ctr[0] + d * math.cos(e) * math.cos(a),
                    ctr[1] + d * math.cos(e) * math.sin(a),
                    aim_z + d * math.sin(e))
    look = mathutils.Vector([ctr[0] - cam.location[0],
                             ctr[1] - cam.location[1],
                             aim_z - cam.location[2]])
    cam.rotation_euler = look.to_track_quat('-Z', 'Y').to_euler()
    return d


def stats(path):
    img = bpy.data.images.load(path)
    px = img.pixels[:]
    lum = sorted(0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2]
                 for i in range(0, len(px), 4))
    n = len(lum)
    hot = sum(1 for v in lum if v >= 0.94)
    bpy.data.images.remove(img)
    return 100.0 * hot / n, lum[min(n - 1, int(0.999 * n))]


# ------------------------------------------------------- material passes ----
ORIG = {o.name: [m for m in o.data.materials] for o in CAR}
MAT_NAMES = sorted({m.name for o in CAR for m in o.data.materials if m})
PALETTE = [(0.90, 0.16, 0.20), (0.16, 0.48, 0.92), (0.20, 0.78, 0.35),
           (0.96, 0.72, 0.12), (0.78, 0.24, 0.86), (0.10, 0.82, 0.86),
           (0.98, 0.45, 0.10), (0.55, 0.55, 0.58)]


def flat(name, rgb, emission=True):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    if emission:
        sh = nt.nodes.new("ShaderNodeEmission")
        sh.inputs[0].default_value = (*rgb, 1)
        sh.inputs[1].default_value = 1.0
    else:
        sh = nt.nodes.new("ShaderNodeBsdfDiffuse")
        sh.inputs[0].default_value = (*rgb, 1)
    nt.links.new(sh.outputs[0], out.inputs["Surface"])
    return m


def clay_mat():
    m = bpy.data.materials.new("clay")
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.52, 0.52, 0.53, 1)
    b.inputs["Roughness"].default_value = 0.45
    b.inputs["Metallic"].default_value = 0.0
    return m


def normal_mat():
    m = bpy.data.materials.new("wnormal")
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    mul = nt.nodes.new("ShaderNodeVectorMath"); mul.operation = 'MULTIPLY'
    mul.inputs[1].default_value = (0.5, 0.5, 0.5)
    add = nt.nodes.new("ShaderNodeVectorMath"); add.operation = 'ADD'
    add.inputs[1].default_value = (0.5, 0.5, 0.5)
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(geo.outputs["Normal"], mul.inputs[0])
    nt.links.new(mul.outputs[0], add.inputs[0])
    nt.links.new(add.outputs[0], em.inputs[0])
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    return m


def wire_mat():
    m = bpy.data.materials.new("wire")
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    wf = nt.nodes.new("ShaderNodeWireframe")
    wf.use_pixel_size = True
    wf.inputs["Size"].default_value = 1.0
    base = nt.nodes.new("ShaderNodeBsdfDiffuse")
    base.inputs[0].default_value = (0.60, 0.60, 0.62, 1)
    ink = nt.nodes.new("ShaderNodeEmission")
    ink.inputs[0].default_value = (0.02, 0.02, 0.03, 1)
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(wf.outputs[0], mix.inputs[0])
    nt.links.new(base.outputs[0], mix.inputs[1])
    nt.links.new(ink.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    return m


def apply_mode(mode):
    """Returns True if the mode wants studio lighting (beauty/clay/wire)."""
    if mode == "beauty":
        for o in CAR:
            o.data.materials.clear()
            for m in ORIG[o.name]:
                o.data.materials.append(m)
        CYC.hide_render = False
        return True
    if mode == "matid":
        cmap = {n: flat(f"id_{n}", PALETTE[i % len(PALETTE)])
                for i, n in enumerate(MAT_NAMES)}
        print("MATID LEGEND: " + ", ".join(
            f"{n}={tuple(round(v,2) for v in PALETTE[i % len(PALETTE)])}"
            for i, n in enumerate(MAT_NAMES)))
        for o in CAR:
            names = [m.name if m else None for m in ORIG[o.name]]
            o.data.materials.clear()
            for nm in names:
                o.data.materials.append(cmap.get(nm, flat("id_none", (0, 0, 0))))
        CYC.hide_render = True
        return False
    single = {"clay": clay_mat, "normal": normal_mat, "wire": wire_mat}[mode]()
    for o in CAR:
        o.data.materials.clear()
        o.data.materials.append(single)
    CYC.hide_render = (mode == "normal")
    return mode in ("clay", "wire")


# --------------------------------------------------- exposure calibration ---
apply_mode("beauty")
scale = 1.0
probe = os.path.join(OUTD, "_probe.png")
os.makedirs(OUTD, exist_ok=True)
# calibration reads the specular TAIL, which converges long before the image
# does — running the probes at full sample count multiplied the cost of the
# whole sheet by up to six for no gain in the number being measured.
sc.cycles.samples = max(16, SAMPLES // 6)
for it in range(6):
    for ld, b in zip(LIGHTS, BASE):
        ld.energy = b * scale
    place(38, 10)
    sc.render.filepath = probe
    bpy.ops.render.render(write_still=True)
    pc, p999 = stats(probe)
    print(f"EXPOSURE iter {it}: scale {scale:.3f} clipped {pc:.3f}% p99.9 {p999:.3f}")
    if pc <= CLIP_MAX and abs(p999 - TARGET_P999) < 0.06:
        break
    if pc > CLIP_MAX:
        scale *= 0.72
    else:
        scale *= min(2.6, max(0.45, TARGET_P999 / max(p999, 1e-4)))
for ld, b in zip(LIGHTS, BASE):
    ld.energy = b * scale
print(f"EXPOSURE LOCKED scale {scale:.3f}")
if os.path.exists(probe):
    os.remove(probe)

# ------------------------------------------------------------------ render --
for mode in MODES:
    lit = apply_mode(mode)
    sc.cycles.samples = SAMPLES if lit else max(24, SAMPLES // 4)
    for ld, b in zip(LIGHTS, BASE):
        ld.energy = (b * scale) if lit else 0.0
    if not lit:
        wd.node_tree.nodes["Background"].inputs[0].default_value = (0.5, 0.5, 0.52, 1)
    else:
        wd.node_tree.nodes["Background"].inputs[0].default_value = (0.34, 0.35, 0.37, 1)
    d = os.path.join(OUTD, mode)
    os.makedirs(d, exist_ok=True)
    for name, az, el in VIEWS:
        dist = place(az, el)
        sc.render.filepath = os.path.join(d, f"{name}.png")
        bpy.ops.render.render(write_still=True)
        pc, _ = stats(sc.render.filepath)
        print(f"VIEW {mode}/{name} dist {dist:.2f} clipped {pc:.3f}%")
print("SHOWROOM_DONE")
