#!/usr/bin/env python3
"""class_a_views.py — the Class-A surface inspection rig: clay, zebra, normals,
through cameras that are LOCKED TO A FILE so before and after are identical.

WHY A NEW RIG WHEN qc_evidence.py EXISTS. Two reasons, both of which have cost
this project a wrong verdict before.

  1. qc_evidence derives its cameras from the MESH BOUNDING BOX. That is right
     for a QA pack of one car and WRONG for a repair loop: a repair moves
     vertices, the bbox moves with them, and the "after" camera is therefore
     not the "before" camera. The difference is small and it is exactly the
     size of the thing being judged, so a panel can appear to improve because
     the camera slid 3 mm. Here the camera solve runs ONCE, is written to a
     spec JSON, and every later render REPLAYS that spec verbatim. Identical
     framing is then a property of the file, not of a promise.
  2. A whole-car tile AVERAGES AWAY a panel defect — recorded in CLAUDE.md as
     the reason cosmetic passes kept passing my eye and failing the reviewer's.
     The owner's gate names NINE specific panels. This rig frames them
     individually, close enough that a 2 mm wave is several pixels.

THE THREE PASSES, and what each one can and cannot prove.

  clay    Matte neutral grey under long horizontal strip lights. No texture, no
          colour, no gloss. This is the pass the owner named. Shading is a pure
          function of the normal field, so a wave reads as a luminance wobble
          that paint would have hidden. It CANNOT be faked by shading tricks:
          the material has no map to hide behind.
  zebra   Chrome under hard-edged strips. A mirror multiplies angular error by
          two, so this is the most sensitive of the three. Reflection lines
          stay straight on a Class-A panel, kink at a G1 break, corner at a G2
          break, and shatter on chatter.
  normals World-space normal straight to emission, unlit. The rawest view of
          the quantity that actually decides the other two. Speckle here is
          chatter; a smooth gradient is a smooth panel.

The owner is explicit that smooth shading, weighted normals, subdivision and
glossy paint MAY NOT be used to pass this gate. This rig is built so they
cannot be: clay and zebra both read the geometry through the normal field at
grazing incidence, where a shading trick applied to bad geometry looks worse,
not better. `--flat` additionally renders with FLAT shading (per-face normals),
which removes vertex-normal interpolation from the answer entirely — the
honest way to show that a claimed geometry improvement is geometry.

Run:
  blender -b --python class_a_views.py -- <car.glb> <outdir> \
      [--spec spec.json] [--passes clay,zebra,normals] [--views all|a,b,c] \
      [--res 900] [--samples 32] [--flat]

First run writes <outdir>/_camera_spec.json unless --spec names an existing
file, in which case that file is REPLAYED and nothing is re-solved.
"""
import json
import math
import os
import sys

import bpy
import mathutils

# --------------------------------------------------------------------- args
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if len(argv) < 2:
    raise SystemExit("usage: ... -- <car.glb> <outdir> [opts]")
GLB, OUTD = argv[0], argv[1]


def opt(flag, default=None):
    return argv[argv.index(flag) + 1] if flag in argv else default


SPEC_IN = opt("--spec")
PASSES = (opt("--passes") or "clay,zebra,normals").split(",")
VIEWSEL = opt("--views") or "all"
RES = int(opt("--res") or 900)
SAMPLES = int(opt("--samples") or 32)
FLAT = "--flat" in argv
os.makedirs(OUTD, exist_ok=True)

# ------------------------------------------------------------------- views
# (name, u, v, azimuth_deg, elevation_deg, span_m, surf_off)
#
# AZIMUTH IS MEASURED FROM THE NOSE, and the nose direction is MEASURED from
# the glazing rather than assumed: az 0 = camera in front of the car looking
# back at it, az 90 = one flank, az 180 = tail-on, az 270 = the other flank.
# This convention is a constant in code, not a note in prose — CLAUDE.md
# records az mappings burning renders twice in one day while written down.
#
# u = along length 0 (nose) .. 1 (tail), v = up 0..1, both in the SPEC's bbox.
# surf_off pushes the aim point from the centreline out toward the camera by
# that fraction of the half-width, so a flank close-up is centred ON the flank
# instead of on the car's midline. span_m is the frame width, so it is also
# the resolution budget: 1.2 m across 900 px = 1.3 mm/px.
VIEWS = [
    # whole-car context, both flanks, so left/right symmetry is judgeable
    ("car_f34",     0.50, 0.45,   35.0, 12.0, 5.20, 0.00),
    ("car_r34",     0.50, 0.45,  215.0, 12.0, 5.20, 0.00),
    # the panels the gate names, one frame each
    ("bonnet",      0.22, 0.80,   28.0, 40.0, 1.90, 0.20),
    ("roof",        0.55, 1.00,  130.0, 55.0, 2.20, 0.10),
    ("door_front",  0.47, 0.42,   90.0,  8.0, 1.50, 0.90),
    ("door_rear",   0.64, 0.42,   90.0,  8.0, 1.50, 0.90),
    ("quarter",     0.80, 0.45,  125.0, 14.0, 1.60, 0.85),
    ("fender",      0.24, 0.45,   55.0, 14.0, 1.60, 0.85),
    ("pillar",      0.55, 0.72,  105.0, 26.0, 1.60, 0.70),
    ("rocker",      0.55, 0.13,   90.0, -6.0, 2.00, 0.95),
    ("bumper_rear", 0.97, 0.38,  165.0, 10.0, 2.00, 0.20),
    ("arch_front",  0.22, 0.28,   70.0,  4.0, 1.20, 0.90),
    ("arch_rear",   0.78, 0.28,  110.0,  4.0, 1.20, 0.90),
]

# --------------------------------------------------------------------- load
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=GLB)
sc = bpy.context.scene
meshes = [o for o in sc.objects if o.type == "MESH"]
if not meshes:
    raise SystemExit(f"REFUSED: no mesh geometry in {GLB}")


def world_bbox():
    lo = [1e18] * 3
    hi = [-1e18] * 3
    for o in meshes:
        for c in o.bound_box:
            p = o.matrix_world @ mathutils.Vector(c)
            for i in range(3):
                lo[i] = min(lo[i], p[i])
                hi[i] = max(hi[i], p[i])
    return lo, hi


# ---------------------------------------------------------------- the spec
if SPEC_IN and os.path.exists(SPEC_IN):
    spec = json.load(open(SPEC_IN))
    print(f"REPLAYING camera spec {SPEC_IN} "
          f"({len(spec['cams'])} cameras) — nothing re-solved")
else:
    lo, hi = world_bbox()
    ext = [hi[i] - lo[i] for i in range(3)]
    # Blender's glTF importer maps glTF Y-up to Blender Z-up, so after import
    # the car's up axis is +Z and its length is the longest horizontal extent.
    i_len = 0 if ext[0] >= ext[1] else 1
    i_wid = 1 - i_len
    ez = mathutils.Vector((0, 0, 1))
    exv = mathutils.Vector((1, 0, 0)) if i_len == 0 else mathutils.Vector((0, 1, 0))
    eyv = ez.cross(exv)

    # NOSE DIRECTION is read from the glazing, never assumed. On every body
    # style in this catalogue the greenhouse sits BEHIND the centre of the
    # car, because the bonnet is longer than the boot lid. So the cabin's
    # centroid is on the TAIL side of the bbox centre. This is measured and
    # printed; a car that breaks it is visible in the car_l34 tile.
    glass = [o for o in meshes if "glass" in o.name.lower()]
    src = glass or meshes
    n = 0
    acc = mathutils.Vector((0, 0, 0))
    for o in src:
        for c in o.bound_box:
            acc += o.matrix_world @ mathutils.Vector(c)
            n += 1
    cab = acc / max(n, 1)
    ctr = mathutils.Vector([(lo[i] + hi[i]) / 2 for i in range(3)])
    tail_sign = 1.0 if (cab - ctr).dot(exv) >= 0 else -1.0
    print(f"  bbox ext={[round(e,3) for e in ext]}  length axis={i_len}  "
          f"cabin offset along length={round((cab-ctr).dot(exv),3)}m  "
          f"=> tail is {'+' if tail_sign>0 else '-'}ve")

    lens, sensor = 85.0, 36.0
    # nose_v points from the centre of the car toward its NOSE; side_v is the
    # right-handed partner so azimuth increases nose -> flank -> tail.
    nose_v = exv * (-tail_sign)
    side_v = ez.cross(nose_v)
    half_w = ext[i_wid] * 0.5
    cams = {}
    for (name, u, v, az, el, span, surf) in VIEWS:
        base = (ctr
                + nose_v * (ext[i_len] * (0.5 - u))
                + ez * (ext[2] * (v - 0.5)))
        a, e = math.radians(az), math.radians(el)
        d = (nose_v * math.cos(a) + side_v * math.sin(a)) * math.cos(e) \
            + ez * math.sin(e)
        h = mathutils.Vector((d.x, d.y, d.z)) - ez * d.dot(ez)
        if h.length > 1e-9:
            h.normalize()
        t = base + h * (surf * half_w)
        dist = (span * 0.5) / math.tan(math.atan(sensor * 0.5 / lens))
        cams[name] = dict(loc=list(t + d * dist), target=list(t),
                          lens=lens, span=round(span, 3), az=az, el=el)
    spec = dict(cams=cams, up=[0, 0, 1], bbox=[lo, hi], i_len=i_len,
                source=os.path.basename(GLB), lens=lens, sensor=sensor)
    sp = SPEC_IN or os.path.join(OUTD, "_camera_spec.json")
    with open(sp, "w") as fh:
        json.dump(spec, fh, indent=1)
    print(f"  wrote camera spec {sp}")

ez = mathutils.Vector(spec["up"])

# ---------------------------------------------------------------- materials
def clay_mat():
    """Neutral grey studio clay: matte in COLOUR, with a controlled SHEEN.

    A perfectly Lambertian surface integrates the whole hemisphere and so
    AVERAGES A SMALL WAVE AWAY. That is physics, not a rig fault, and the first
    version of this pass proved it: the Golf's front door rendered as a
    featureless white field at mean sRGB 193 while the zebra pass of the SAME
    door, through the SAME camera, was a shattered marble. A fully Lambertian
    clay cannot be the inspection surface this gate asks for.

    Real studio clay is not Lambertian either -- it carries a low specular
    sheen, and that sheen is what makes strip lights legible on it. So the base
    colour stays flat neutral grey with no texture and no map (nothing for a
    shading trick to hide behind) and roughness is 0.34: matte to the eye, and
    still able to resolve the strips. That is a long way from the 0.03 of the
    zebra chrome and a long way from the glossy paint the owner ruled out.

    Base 0.34 rather than 0.55 because with the strips carrying most of the
    light a lighter base clips, and a clipped clay pass has thrown away exactly
    the gradient the gate is about. Verified numerically on every render.
    """
    m = bpy.data.materials.new("ca_clay")
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.34, 0.34, 0.35, 1)
    b.inputs["Metallic"].default_value = 0.0
    b.inputs["Roughness"].default_value = 0.34
    if "Specular IOR Level" in b.inputs:
        b.inputs["Specular IOR Level"].default_value = 0.5
    elif "Specular" in b.inputs:
        b.inputs["Specular"].default_value = 0.5
    return m


def chrome_mat():
    m = bpy.data.materials.new("ca_chrome")
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.87, 0.88, 0.91, 1)
    b.inputs["Metallic"].default_value = 1.0
    b.inputs["Roughness"].default_value = 0.03
    return m


def normal_mat():
    """World-space normal -> emission. Unlit, so the image is the normal field
    and nothing else."""
    m = bpy.data.materials.new("ca_norm")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    g = nt.nodes.new("ShaderNodeNewGeometry")
    vt = nt.nodes.new("ShaderNodeVectorMath")
    vt.operation = "MULTIPLY_ADD"
    vt.inputs[1].default_value = (0.5, 0.5, 0.5)
    vt.inputs[2].default_value = (0.5, 0.5, 0.5)
    e = nt.nodes.new("ShaderNodeEmission")
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(g.outputs["Normal"], vt.inputs[0])
    nt.links.new(vt.outputs[0], e.inputs["Color"])
    nt.links.new(e.outputs[0], o.inputs["Surface"])
    return m


def strip_lights(bbox, i_len, n=7, strength=17.0, width=0.16, radius_k=0.62,
                 span_k=1.7):
    """Long emissive tubes running along the car, at FINITE distance.

    THIS IS NOT INTERCHANGEABLE WITH AN ENVIRONMENT MAP, and finding that out
    cost two rebuilds of the clay pass. A world-based strip pattern is
    infinitely far away, so the reflected direction it is sampled by depends
    only on the surface NORMAL. A near-planar vertical door has almost constant
    normal, so it samples one narrow band of elevation and renders as a
    FEATURELESS FIELD — measured, mean sRGB 176 with no structure, on a door
    whose zebra pass through the same camera was a shattered marble.

    A real strip light is a finite tube a couple of metres away, so the
    reflection angle changes with POSITION as well as normal, and the band
    sweeps ACROSS the panel. That sweep is the whole diagnostic: on a Class-A
    panel its edges are straight and evenly spaced, and a wave bends them. It
    is also what the owner literally asked for — "long strip lights".

    Tubes run parallel to the car's length and are spaced around it on an arc,
    so every panel from rocker to roof gets a sweep.
    """
    lo, hi = bbox
    ctr = mathutils.Vector([(lo[i] + hi[i]) / 2 for i in range(3)])
    L = hi[i_len] - lo[i_len]
    i_wid = 1 - i_len
    W = max(hi[i_wid] - lo[i_wid], hi[2] - lo[2])
    R = (L * radius_k + W * 0.5)
    made = []
    for k in range(n):
        # -100 deg .. +100 deg about the length axis: below the beltline on
        # both sides, over the top, and never exactly at the camera azimuth
        phi = math.radians(-100.0 + 200.0 * k / max(n - 1, 1))
        d = mathutils.Vector((0, 0, 0))
        d[i_wid] = math.sin(phi)
        d[2] = math.cos(phi)
        loc = ctr + d * R
        m = bpy.data.meshes.new(f"ca_strip{k}")
        hl, hw = L * span_k * 0.5, width * 0.5
        vs = []
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            v = [0.0, 0.0, 0.0]
            v[i_len] = sx * hl
            # the tube's short axis lies in the plane perpendicular to its
            # own radius, so it always presents its face to the car
            t = mathutils.Vector((0, 0, 0))
            t[i_wid] = math.cos(phi)
            t[2] = -math.sin(phi)
            vs.append((loc[0] + v[0] + t.x * sy * hw,
                       loc[1] + v[1] + t.y * sy * hw,
                       loc[2] + v[2] + t.z * sy * hw))
        m.from_pydata(vs, [], [[0, 1, 2, 3]])
        m.update()
        o = bpy.data.objects.new(f"ca_strip{k}", m)
        bpy.context.scene.collection.objects.link(o)
        mat = bpy.data.materials.new(f"ca_strip_m{k}")
        mat.use_nodes = True
        nt = mat.node_tree
        nt.nodes.clear()
        e = nt.nodes.new("ShaderNodeEmission")
        e.inputs["Color"].default_value = (1, 1, 1, 1)
        e.inputs["Strength"].default_value = strength
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(e.outputs[0], out.inputs["Surface"])
        o.data.materials.append(mat)
        # the tubes light the car and reflect in it, but must not appear as
        # objects in the frame behind it
        o.visible_camera = False
        made.append(o)
    return made


def vcol_mat():
    """The mesh's own colour attribute, unlit. Used to render surface_map.py's
    sigma heat map through the SAME cameras as clay and zebra, so a hot region
    can be laid directly beside the reflection break it is meant to explain.
    Emission, not a lit shader: a lit ID pass shades the colour by geometry and
    two different values land on the same tone."""
    m = bpy.data.materials.new("ca_vcol")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    c = nt.nodes.new("ShaderNodeVertexColor")
    e = nt.nodes.new("ShaderNodeEmission")
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(c.outputs["Color"], e.inputs["Color"])
    nt.links.new(e.outputs[0], o.inputs["Surface"])
    return m


def strip_world(bands, hard, strength, floor):
    """Long horizontal strip lights, built from the ray direction's component
    along the CAR's up axis.

    Band count is set directly rather than through a wave texture: recorded in
    qc_evidence.py, ShaderNodeTexWave's Scale is not a band count and two
    attempts to use it failed in opposite directions, one rendering a flank as
    a fine scribble and one rendering it nearly white.
    """
    w = bpy.data.worlds.new("ca_strips")
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    tc = nt.nodes.new("ShaderNodeTexCoord")
    dot = nt.nodes.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    dot.inputs[1].default_value = (ez.x, ez.y, ez.z)
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    mul.inputs[1].default_value = float(bands)
    frac = nt.nodes.new("ShaderNodeMath")
    frac.operation = "FRACT"
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = "CONSTANT" if hard else "EASE"
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = (floor, floor, floor * 1.06, 1)
    ramp.color_ramp.elements[1].position = 0.5
    ramp.color_ramp.elements[1].color = (1, 1, 1, 1)
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = strength
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(tc.outputs["Generated"], dot.inputs[0])
    nt.links.new(dot.outputs["Value"], mul.inputs[0])
    nt.links.new(mul.outputs[0], frac.inputs[0])
    nt.links.new(frac.outputs[0], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs[0], out.inputs["Surface"])
    return w


# ---------------------------------------------------------------- rendering
cam = bpy.data.objects.new("ca_cam", bpy.data.cameras.new("ca_cam"))
sc.collection.objects.link(cam)
sc.camera = cam
sc.render.engine = "CYCLES"
sc.cycles.samples = SAMPLES
# This build has no OpenImageDenoiser: use_denoising=True raises RuntimeError
# and the render dies AFTER "Blender quit" prints, silently leaving stale
# frames. Recorded in CLAUDE.md; do not turn this on.
sc.cycles.use_denoising = False
sc.render.resolution_x = RES
sc.render.resolution_y = int(RES * 0.75)
sc.render.image_settings.file_format = "PNG"
sc.render.image_settings.color_mode = "RGBA"
# Transparent film: the world still lights the car and still reflects in the
# chrome, but the BACKDROP is alpha 0. That is what lets exposure_check
# separate car pixels from backdrop by alpha instead of by brightness.
sc.render.film_transparent = True
# Standard, never AgX: AgX once clipped a tyre to pure white and produced a
# false verdict on this project. Standard is linear-to-sRGB and nothing else,
# so a printed pixel value means what it says.
sc.view_settings.view_transform = "Standard"
sc.view_settings.look = "None"

if FLAT:
    # Remove vertex-normal interpolation from the answer entirely.
    for o in meshes:
        for p in o.data.polygons:
            p.use_smooth = False
    print("  FLAT shading forced: no vertex-normal interpolation in any pass")


def aim(loc, target):
    cam.location = loc
    f = (target - loc).normalized()
    r = f.cross(ez)
    if r.length < 1e-6:
        r = f.cross(mathutils.Vector((1, 0, 0)))
    r.normalize()
    u = r.cross(f)
    # Explicit basis rather than to_track_quat: track-quat picks its own roll
    # from world Z and has produced side-on sheets in this project twice.
    cam.rotation_euler = mathutils.Matrix((
        (r.x, u.x, -f.x), (r.y, u.y, -f.y), (r.z, u.z, -f.z))).to_euler()


def set_material(mat):
    for o in meshes:
        o.data.materials.clear()
        o.data.materials.append(mat)


PASS_CFG = {
    # name: (material factory, strip-world args or None)
    # Strengths are set so the CAR lands mid-range with headroom, verified
    # numerically below rather than by eye: AgX once clipped a tyre to pure
    # white on this project and produced a false verdict, and a clay pass that
    # clips has thrown away exactly the gradient the gate is about.
    # clay is lit by REAL STRIP LIGHTS (finite distance) rather than a strip
    # environment -- see strip_lights() for why an environment cannot work on a
    # near-planar panel. `None` here means "no strip world"; the lights are
    # created separately and a dim ambient fills the shadows.
    "clay":    (clay_mat,   None),
    "zebra":   (chrome_mat, dict(bands=9.0,  hard=True,  strength=1.30, floor=0.01)),
    "normals": (normal_mat, None),
    "map":     (vcol_mat,   None),
}


def exposure_check(path):
    """-> (mean sRGB of the car, % of car pixels clipped at 255).

    The car is separated from the backdrop by ALPHA, not by brightness: a clay
    car against a bright strip world overlaps the background in value, so a
    luminance threshold would measure the backdrop and call it the car. This
    is the same trap as the 'darkest pixel' tyre probe that confidently
    returned zero suspects for every car by measuring the black backdrop.
    """
    try:
        img = bpy.data.images.load(path)
        px = list(img.pixels)
        w, h = img.size
        n = w * h
        car = [(px[i * 4], px[i * 4 + 1], px[i * 4 + 2])
               for i in range(n) if px[i * 4 + 3] > 0.5]
        bpy.data.images.remove(img)
        if not car:
            return None, None, 0.0
        lin = [(r + g + b) / 3.0 for (r, g, b) in car]
        srgb = [(1.055 * (v ** (1 / 2.4)) - 0.055) if v > 0.0031308 else 12.92 * v
                for v in lin]
        mean = sum(srgb) / len(srgb) * 255.0
        clip = sum(1 for v in srgb if v >= 0.999) / len(srgb) * 100.0
        return round(mean, 1), round(clip, 3), len(car) / n * 100.0
    except Exception as exc:
        print(f"    exposure check failed: {exc}")
        return None, None, 0.0

strips = []
names = [v[0] for v in VIEWS]
want = names if VIEWSEL == "all" else [v for v in VIEWSEL.split(",")]
log = {}
for pname in PASSES:
    if pname not in PASS_CFG:
        print(f"  skipping unknown pass {pname!r}")
        continue
    matf, wargs = PASS_CFG[pname]
    set_material(matf())
    for o in list(strips):
        bpy.data.objects.remove(o, do_unlink=True)
    strips = []
    sc.world = strip_world(**wargs) if wargs else bpy.data.worlds.new("ca_dark")
    if wargs is None:
        sc.world.use_nodes = True
        # `map` and `normals` are unlit emission passes and want a black world;
        # clay wants a little ambient so the shadow side is not crushed, which
        # would hide a defect just as surely as clipping the highlight does.
        amb = 0.10 if pname == "clay" else 0.0
        sc.world.node_tree.nodes["Background"].inputs[1].default_value = amb
        if pname == "clay":
            strips = strip_lights(spec["bbox"], spec.get("i_len", 0))
            print(f"  {len(strips)} strip lights")
    d = os.path.join(OUTD, pname)
    os.makedirs(d, exist_ok=True)
    for vn in want:
        c = spec["cams"].get(vn)
        if c is None:
            print(f"  no camera {vn!r} in spec — skipped")
            continue
        cam.data.lens = c["lens"]
        aim(mathutils.Vector(c["loc"]), mathutils.Vector(c["target"]))
        sc.render.filepath = os.path.join(d, f"{vn}.png")
        bpy.ops.render.render(write_still=True)
        mean, clip, fill = exposure_check(sc.render.filepath)
        log[f"{pname}/{vn}"] = dict(bytes=os.path.getsize(sc.render.filepath),
                                    mean_srgb=mean, clip_pct=clip,
                                    fill_pct=round(fill, 1))
        flag = ""
        # Clipping is a DEFECT in clay/normals, where the whole signal is a
        # gradient, and it is BY DESIGN in zebra, whose white strips are white
        # on purpose — the information there lives in the strip BOUNDARY, not
        # in the strip. Flagging zebra for clipping would train the next reader
        # to dim the one pass whose contrast is the measurement.
        if clip is not None and clip > 1.0 and pname != "zebra":
            flag = "  <-- CLIPPED, gradient lost"
        if fill < 3.0:
            flag += "  <-- car barely in frame"
        print(f"    {pname}/{vn}.png  mean={mean} clip={clip}% "
              f"fill={fill:.1f}%{flag}")

with open(os.path.join(OUTD, "_render_log.json"), "w") as fh:
    json.dump(dict(glb=os.path.basename(GLB), passes=PASSES, views=want,
                   res=RES, samples=SAMPLES, flat=FLAT, files=log), fh, indent=1)
print(f"CLASS_A_VIEWS_DONE {len(log)} images -> {OUTD}")
