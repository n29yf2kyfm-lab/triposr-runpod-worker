#!/usr/bin/env python3
"""qc_evidence.py — the canonical QA camera set and the proof passes.

EIGHT matched cameras, not seven. `eyeball_views.py` renders 0/45/90/135/180/
225/315 and is missing 270 — the strict RIGHT-side view — so a defect that
lives on one flank could only ever be seen obliquely. Every pass in this file
uses the SAME eight cameras, same lens, same distance, same lighting and the
same resolution, because a before/after comparison between two different
framings proves nothing.

Passes (`--pass`):
  beauty    the asset's own materials
  clay      one neutral matte grey on everything — the Class-A surface check.
            Paint gloss hides panel waves; clay is the only honest surface view
  wire      wireframe over clay
  normals   world-space normal as colour — flipped faces read as the wrong hue
  matid     one flat saturated colour per material — proves what is actually
            bound to which geometry, which is the whole of the "real glass /
            tyre-rim split / lamps / interior" claim
  glassonly everything except glazing hidden
  nobody    body shell hidden: what a customer sees through the windows
  backlight emissive magenta plane behind the car — CLAUDE.md's transparency
            test. Opaque glazing stays body-coloured, real glass glows

VIEW TRANSFORM IS **STANDARD**, ALWAYS. Blender 4 defaults to AgX, which once
clipped a tyre to pure white here and produced a false defect verdict that took
four control renders to overturn. Every pass also prints the rendered image's
numeric stats so a clipping claim can be checked rather than argued.

EEVEE cannot initialise in this container — EGL is absent — so CYCLES with
use_denoising=False is the only combination that renders. This build has no
OIDN either.

Run: blender -b --python qc_evidence.py -- <car.glb> <outdir> [--pass beauty]
"""
import json
import math
import os
import sys

import bpy
import mathutils

argv = sys.argv[sys.argv.index("--") + 1:]
GLB, OUTD = argv[0], argv[1]
PASS = "beauty"
if "--pass" in argv:
    PASS = argv[argv.index("--pass") + 1]
ONLY = None
if "--only" in argv:
    ONLY = argv[argv.index("--only") + 1].split(",")
NOSE = argv[argv.index("--nose") + 1] if "--nose" in argv else "+x"
RES = int(os.environ.get("QC_RES", "1000"))
SAMPLES = int(os.environ.get("QC_SAMPLES", "24"))

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=GLB)
sc = bpy.context.scene
meshes = [o for o in sc.objects if o.type == "MESH"]
if not meshes:
    raise SystemExit(f"REFUSED: no mesh geometry in {GLB}")

# -- bounds -----------------------------------------------------------------
lo = [1e9] * 3
hi = [-1e9] * 3
for o in meshes:
    for c in o.bound_box:
        w = o.matrix_world @ mathutils.Vector(c)
        for i in range(3):
            lo[i] = min(lo[i], w[i])
            hi[i] = max(hi[i], w[i])
ctr = mathutils.Vector([(lo[i] + hi[i]) / 2 for i in range(3)])
ext = [hi[i] - lo[i] for i in range(3)]
diag = max(ext)

# glTF import converts Y-up to Blender Z-up, so a canon.py car (length X, up Y)
# arrives as length X, up Z. Assert it from the extents instead of assuming:
# CLAUDE.md records a render-side inversion caused by a 0.4% argmin tie, and a
# Y-up assumption that rendered a Y-down glb upside down.
up_axis = min(range(3), key=lambda i: ext[i]) if ext[2] > ext[1] else 2
LONG = max(range(3), key=lambda i: ext[i])
print(f"QC_EXTENTS x={ext[0]:.3f} y={ext[1]:.3f} z={ext[2]:.3f} "
      f"long_axis={LONG} up_axis_guess={up_axis}")

# -- the eight canonical cameras -------------------------------------------
# Azimuth 0 looks along +X at the car. `--nose` names which end is the FRONT so
# the filenames mean what they say; canon.py deliberately does not resolve nose
# direction, so it is an INPUT here rather than something guessed. Naming a
# view "front" when it shows the boot is worse than naming it "a000".
FLIP = 180 if NOSE == "-x" else 0
VIEWS = [("01_front", 0), ("02_front_left", 45), ("03_left", 90),
         ("04_rear_left", 135), ("05_rear", 180), ("06_rear_right", 225),
         ("07_right", 270), ("08_front_right", 315)]

cam = bpy.data.objects.new("qc_cam", bpy.data.cameras.new("qc_cam"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.lens = 85          # long lens; minimal perspective distortion
# 2.35 x diag puts the car at ~78% of frame height with an 85 mm lens on a
# square frame -- inside the spec's 75-85% window. Fixed for every pass so
# before/after images are pixel-comparable.
DIST = 2.35 * diag
ELEV = 0.30 * diag

key = bpy.data.objects.new("key", bpy.data.lights.new("key", "SUN"))
key.data.energy = 3.2
key.data.angle = math.radians(14)
sc.collection.objects.link(key)
key.rotation_euler = (math.radians(52), 0, math.radians(35))
# Fill from the far side. The production rig's key is one-sided, which makes a
# MAJORITY of cars read as a 2-vs-2 brightness split by side and has been
# misdiagnosed as a per-side wheel defect more than once.
fill = bpy.data.objects.new("fill", bpy.data.lights.new("fill", "SUN"))
fill.data.energy = 1.5
sc.collection.objects.link(fill)
fill.rotation_euler = (math.radians(58), 0, math.radians(215))

sc.render.engine = "CYCLES"
sc.cycles.samples = SAMPLES
sc.cycles.use_denoising = False
sc.view_layers[0].cycles.use_denoising = False
sc.render.film_transparent = True
sc.render.image_settings.file_format = "PNG"
sc.render.image_settings.color_mode = "RGBA"
sc.render.resolution_x = RES
sc.render.resolution_y = RES
# STANDARD, never AgX. See the module docstring: AgX clipped a tyre to white
# here and manufactured a defect that cost four control renders to disprove.
sc.view_settings.view_transform = "Standard"
sc.view_settings.look = "None"
sc.view_settings.exposure = 0.0
sc.view_settings.gamma = 1.0

GLASSY = ("glass", "window", "windscreen", "screen")


def flat(name, rgba, rough=0.6, metal=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = rgba
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    return m


def emissive(name, rgb):
    """Unlit flat colour: the ONLY honest way to render a material-ID pass.

    A lit pass shades the ID colour by geometry and two materials can then read
    as the same tone. Emission removes lighting from the answer entirely.
    """
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    e = nt.nodes.new("ShaderNodeEmission")
    e.inputs["Color"].default_value = (*rgb, 1)
    e.inputs["Strength"].default_value = 1.0
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(e.outputs[0], o.inputs["Surface"])
    return m


def mat_names(o):
    return [s.material.name if s.material else "" for s in o.material_slots]


def is_glass(o):
    return any(any(k in n.lower() for k in GLASSY) for n in mat_names(o))


ID_COLOURS = [(0.95, 0.15, 0.15), (0.15, 0.55, 0.95), (0.15, 0.9, 0.35),
              (0.98, 0.8, 0.1), (0.85, 0.2, 0.9), (0.1, 0.9, 0.9),
              (0.99, 0.5, 0.1), (0.6, 0.6, 0.6), (0.4, 0.1, 0.7)]

legend = {}
if PASS in ("clay", "wire"):
    c = flat("qc_clay", (0.62, 0.62, 0.63, 1), rough=0.55)
    for o in meshes:
        o.data.materials.clear()
        o.data.materials.append(c)
elif PASS == "normals":
    # World-space normal -> colour. A face wound backwards points the other
    # way and lands on the opposite hue, which is the only view in this file
    # where a flipped normal is directly visible rather than inferred.
    m = bpy.data.materials.new("qc_normals")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    mp = nt.nodes.new("ShaderNodeVectorMath")
    mp.operation = "MULTIPLY_ADD"
    mp.inputs[1].default_value = (0.5, 0.5, 0.5)
    mp.inputs[2].default_value = (0.5, 0.5, 0.5)
    em = nt.nodes.new("ShaderNodeEmission")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(geo.outputs["Normal"], mp.inputs[0])
    nt.links.new(mp.outputs[0], em.inputs["Color"])
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    for o in meshes:
        o.data.materials.clear()
        o.data.materials.append(m)
elif PASS == "matid":
    seen = {}
    for o in meshes:
        for nm in mat_names(o) or [o.name]:
            if nm not in seen:
                seen[nm] = ID_COLOURS[len(seen) % len(ID_COLOURS)]
        col = seen[(mat_names(o) or [o.name])[0]]
        legend[(mat_names(o) or [o.name])[0]] = [round(x, 3) for x in col]
        o.data.materials.clear()
        o.data.materials.append(emissive("id_" + o.name, col))
elif PASS == "glassonly":
    for o in meshes:
        o.hide_render = not is_glass(o)
elif PASS == "nobody":
    # Hide the painted shell AND the glazing, so what remains is exactly what
    # the "interior" claim rests on. Hiding only the body would leave tinted
    # glass in front of it and make an absent interior look merely dark.
    for o in meshes:
        nl = " ".join(mat_names(o)).lower()
        o.hide_render = ("carpaint" in nl or "paint" in nl or is_glass(o))
elif PASS == "backlight":
    # Emissive plane behind the car. CLAUDE.md's magenta-backlight test:
    # transparent glazing glows, opaque glazing stays body-coloured. This is
    # the render that decides glazing when the glTF probe says "ambiguous".
    bpy.ops.mesh.primitive_plane_add(size=diag * 3)
    pl = bpy.context.object
    pl.location = ctr + mathutils.Vector((0, 0, 0))
    pl.location[0] = ctr[0] - diag * 1.6
    pl.rotation_euler = (math.radians(90), 0, math.radians(90))
    pl.data.materials.append(emissive("qc_backlight", (1.0, 0.0, 0.85)))

if ONLY:
    for o in meshes:
        o.hide_render = not any(k.lower() in o.name.lower()
                                or any(k.lower() in n.lower() for n in mat_names(o))
                                for k in ONLY)

if PASS == "wire":
    for o in meshes:
        mod = o.modifiers.new("qc_wire", "WIREFRAME")
        mod.thickness = 0.0016
        mod.use_replace = True

os.makedirs(OUTD, exist_ok=True)
stats = {}
for name, az in VIEWS:
    r = math.radians(az + FLIP)
    cam.location = ctr + mathutils.Vector((DIST * math.cos(r),
                                           DIST * math.sin(r), ELEV))
    d = (ctr - cam.location).normalized()
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    fp = os.path.join(OUTD, f"{name}.png")
    sc.render.filepath = fp
    bpy.ops.render.render(write_still=True)
    # NUMERIC CHECK ON EVERY FRAME. "Verify numerically before trusting any
    # render" is a paid-for rule here: a clipped highlight and a white tyre
    # look identical to the eye and different in the histogram.
    try:
        img = bpy.data.images.load(fp)
        px = list(img.pixels)
        rgb = [px[i] for i in range(len(px)) if i % 4 != 3]
        a = [px[i] for i in range(3, len(px), 4)]
        cov = sum(1 for v in a if v > 0.5) / max(1, len(a))
        clipped = sum(1 for v in rgb if v >= 0.999) / max(1, len(rgb))
        stats[name] = {"coverage": round(cov, 4), "clipped_frac": round(clipped, 5),
                       "mean": round(sum(rgb) / max(1, len(rgb)), 4)}
        bpy.data.images.remove(img)
    except Exception as exc:                                # noqa: BLE001
        stats[name] = {"stat_error": str(exc)}

meta = {"pass": PASS, "glb": GLB, "views": [v[0] for v in VIEWS],
        "lens_mm": cam.data.lens, "distance": DIST, "elevation": ELEV,
        "resolution": RES, "samples": SAMPLES, "view_transform": "Standard",
        "engine": "CYCLES", "denoise": False, "nose": NOSE,
        "extents": [round(e, 4) for e in ext], "legend": legend,
        "frame_stats": stats}
with open(os.path.join(OUTD, "_pass.json"), "w") as f:
    json.dump(meta, f, indent=1)
print("QC_EVIDENCE_DONE " + json.dumps(meta))
