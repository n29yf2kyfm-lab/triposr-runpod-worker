#!/usr/bin/env python3
"""diag_render.py — diagnostic renders for the integrity gate.

Run:
  blender -b --python diag_render.py -- IN.glb OUTDIR --preset wheels
  ... --preset wheels|glass|rear|interior|body|full  [--only NAME,NAME]
      [--res 1600] [--samples 48]

NON-NEGOTIABLES BAKED IN, each of them already paid for by this project:

  * CYCLES ONLY. EEVEE cannot initialise in this container (no EGL) and on 4.5
    dies without even raising a Python exception.
  * STANDARD view transform, NEVER AgX. AgX produced three false verdicts here
    and once clipped 42.58% of a tile's car pixels to white.
  * EXPOSURE IS VERIFIED NUMERICALLY and the clipped fraction is REPORTED with
    every frame. A render nobody measured is not evidence.
  * ORTHOGRAPHIC for any view a measurement is read off. A perspective camera
    makes a symmetric car photograph asymmetric.
  * DENOISING is probed, never assumed: a REAL assignment inside try/except that
    PRINTS which branch ran. Six rigs in this repo still hardcode
    `use_denoising = False` with a comment about a denoiser the container has
    had since 2026-08-21; a silent fallback looks identical to success.
  * BACKFACE CULLING is a first-class switch, because "does this disappear when
    culling is on" is the actual question for an inverted-normal defect -- and
    because culling must never be used to HIDE missing geometry, only to expose
    it. Both states are always rendered as a pair.

Neutral clay is the default surface: albedo carries no information about
integrity, and this project has repeatedly mistaken a material for a geometry
defect (and vice versa). `--shading keep` retains the file's own materials.
"""
import json
import math
import os
import sys

import bpy
import numpy as np

PRESETS = {
    "wheels": ["Wheel_"],
    "glass": ["Glass_", "Body_Glass_"],
    "rear": ["Hatch", "TailLamp_", "Glass_Backlight", "Glass_Rear",
             "Bumper_Rear", "Plate_Rear", "Glass_Quarter_"],
    "interior": ["Cabin_"],
    "body": ["Body_Shell", "Bumper_", "Hatch", "Valance_", "Underbody"],
    "full": [""],
}


def argv():
    a = sys.argv
    return a[a.index("--") + 1:] if "--" in a else []


def opt(a, flag, default=None, cast=str):
    return cast(a[a.index(flag) + 1]) if flag in a else default


def setup_engine(samples, res, denoise=True):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    sc.render.resolution_x = res
    sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = False
    # STANDARD, never AgX.
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.view_settings.exposure = 0.0
    sc.view_settings.gamma = 1.0
    # Probe the denoiser with a REAL assignment; print the branch that ran.
    try:
        sc.cycles.use_denoising = True
        sc.cycles.denoiser = "OPENIMAGEDENOISE"
        print("DIAG_DENOISE: ON (OpenImageDenoise)")
    except Exception as e:
        sc.cycles.use_denoising = False
        print(f"DIAG_DENOISE: OFF (fallback) — {type(e).__name__}: {e}")


def world_grey(v=0.22):
    w = bpy.data.worlds.new("w")
    bpy.context.scene.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (v, v, v, 1.0)
    bg.inputs[1].default_value = 1.0
    return v


def add_shader_culling(m):
    """Make BACKFACES genuinely invisible in CYCLES.

    `material.use_backface_culling` is an EEVEE/viewport flag and CYCLES
    IGNORES IT COMPLETELY -- proven by test_culling.py, whose four cells all
    read 0.44696 with the flag and 0.00033 for the culled cell with this node
    network. An earlier pass of this gate rendered a cullON/cullOFF pair off
    that flag; the two frames were statistically identical and the "no wheel
    disappears under culling" criterion was unfalsifiable. That pair was
    withdrawn.

    So culling is done in the shader: Geometry->Backfacing drives a MixShader
    between the real surface and a Transparent BSDF."""
    nt = m.node_tree
    out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
    if out is None or not out.inputs["Surface"].links:
        return False
    src = out.inputs["Surface"].links[0].from_socket
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(geo.outputs["Backfacing"], mix.inputs["Fac"])
    nt.links.new(src, mix.inputs[1])
    nt.links.new(tr.outputs["BSDF"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return True


def clay(objs, culling):
    """One neutral clay material on everything. Albedo hides nothing and
    reveals nothing -- which is the point for a geometry diagnostic."""
    m = bpy.data.materials.new("CLAY")
    m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.55, 0.55, 0.57, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.45
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = 0.0
    if culling:
        assert add_shader_culling(m), "culling network not attached"
    for o in objs:
        o.data.materials.clear()
        o.data.materials.append(m)


def keep_shading(culling):
    if not culling:
        return
    n = 0
    for m in bpy.data.materials:
        if m.use_nodes and add_shader_culling(m):
            n += 1
    assert n, "culling requested but attached to no material"
    print(f"DIAG_CULL: shader culling attached to {n} materials")


def face_orientation(objs):
    """Blender's face-orientation overlay is viewport-only, so build the
    equivalent in Cycles: BLUE where the geometric normal faces the camera,
    RED where it faces away. This is the render that makes an inverted normal
    visible without hiding the geometry, which culling would."""
    m = bpy.data.materials.new("FACEORI")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    mix = nt.nodes.new("ShaderNodeMixRGB")
    em = nt.nodes.new("ShaderNodeEmission")
    mix.inputs["Color1"].default_value = (0.05, 0.25, 1.0, 1)   # front: blue
    mix.inputs["Color2"].default_value = (1.0, 0.08, 0.05, 1)   # back:  red
    nt.links.new(geo.outputs["Backfacing"], mix.inputs["Fac"])
    nt.links.new(mix.outputs["Color"], em.inputs["Color"])
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    m.use_backface_culling = False
    for o in objs:
        o.data.materials.clear()
        o.data.materials.append(m)


def matid(objs):
    """Flat emission, one hue per material name — deterministic, so the same
    component keeps its colour between before and after sheets."""
    import hashlib
    cache = {}
    for o in objs:
        names = [s.material.name if s.material else "NONE"
                 for s in o.material_slots] or ["NONE"]
        newmats = []
        for n in names:
            if n not in cache:
                h = int(hashlib.md5(n.encode()).hexdigest()[:6], 16)
                col = ((h >> 16 & 255) / 255, (h >> 8 & 255) / 255,
                       (h & 255) / 255, 1.0)
                m = bpy.data.materials.new("ID_" + n)
                m.use_nodes = True
                nt = m.node_tree
                nt.nodes.clear()
                em = nt.nodes.new("ShaderNodeEmission")
                ou = nt.nodes.new("ShaderNodeOutputMaterial")
                em.inputs["Color"].default_value = col
                nt.links.new(em.outputs["Emission"], ou.inputs["Surface"])
                m.use_backface_culling = False
                cache[n] = m
            newmats.append(cache[n])
        o.data.materials.clear()
        for m in newmats:
            o.data.materials.append(m)


def lights():
    for name, loc, energy in (("key", (4.0, -5.0, 4.5), 900.0),
                              ("fill", (-4.5, -3.5, 2.5), 420.0),
                              ("rim", (-3.0, 5.0, 3.5), 520.0),
                              ("top", (0.0, 0.0, 6.0), 380.0)):
        d = bpy.data.lights.new(name, "AREA")
        d.energy = energy
        d.size = 4.0
        o = bpy.data.objects.new(name, d)
        o.location = loc
        o.rotation_mode = "QUATERNION"
        v = np.array(loc, dtype=float)
        o.rotation_quaternion = _look_quat(-v / np.linalg.norm(v))
        bpy.context.collection.objects.link(o)


def _look_quat(fwd):
    from mathutils import Vector
    return Vector(fwd).to_track_quat("-Z", "Y")


def ortho_cam(centre, radius, az_deg, el_deg, name="cam"):
    """Orthographic camera on a sphere around `centre`. AZ/EL in degrees;
    az 0 = +X (nose end for a length-on-X car), az 90 = +Y."""
    cd = bpy.data.cameras.new(name)
    cd.type = "ORTHO"
    cd.ortho_scale = radius * 2.0
    cam = bpy.data.objects.new(name, cd)
    bpy.context.collection.objects.link(cam)
    a, e = math.radians(az_deg), math.radians(el_deg)
    d = np.array([math.cos(e) * math.cos(a),
                  math.cos(e) * math.sin(a),
                  math.sin(e)])
    cam.location = tuple(np.array(centre) + d * max(radius * 4.0, 8.0))
    cam.rotation_mode = "QUATERNION"
    cam.rotation_quaternion = _look_quat(-d)
    bpy.context.scene.camera = cam
    return cam


def render_to(path):
    bpy.context.scene.render.filepath = path
    bpy.context.scene.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)


def measure(path):
    """Numeric exposure verification. A render this project trusts must state
    its clipped fraction; a tyre once clipped to pure white and set a verdict."""
    img = bpy.data.images.load(path)
    px = np.array(img.pixels[:], dtype=np.float32).reshape(-1, 4)
    rgb = px[:, :3]
    lum = rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    bpy.data.images.remove(img)
    return {
        "mean_srgb": round(float(lum.mean()) * 255, 2),
        "clipped_white_frac": round(float((lum >= 0.999).mean()), 5),
        "clipped_black_frac": round(float((lum <= 0.001).mean()), 5),
        "nonbg_frac": round(float((np.abs(lum - 0.22) > 0.02).mean()), 5),
    }


def main():
    a = argv()
    src, outdir = a[0], a[1]
    preset = opt(a, "--preset", "full")
    only = opt(a, "--only", "")
    res = opt(a, "--res", 1400, int)
    samples = opt(a, "--samples", 40, int)
    shading = opt(a, "--shading", "clay")
    views = opt(a, "--views", "")
    os.makedirs(outdir, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=src)
    allobs = [o for o in bpy.data.objects if o.type == "MESH"]

    # full-car frame FIRST, so an isolated preset keeps the car's own framing
    # and a before/after pair is comparable. Locking the frame across a pair is
    # a rule this project learned by producing an uncomparable one.
    pts = []
    for o in allobs:
        n = len(o.data.vertices)
        co = np.empty(n * 3, dtype=np.float64)
        o.data.vertices.foreach_get("co", co)
        co = co.reshape(n, 3)
        m = np.array(o.matrix_world)
        pts.append(co @ m[:3, :3].T + m[:3, 3])
    P = np.vstack(pts)
    car_c = (P.min(0) + P.max(0)) / 2
    car_r = float(np.linalg.norm(P.max(0) - P.min(0))) / 2

    pref = PRESETS.get(preset, [""])
    if only:
        want = set(only.split(","))
        keep = [o for o in allobs if o.name in want]
    else:
        keep = [o for o in allobs
                if any(o.name.startswith(p) for p in pref)] or allobs
    for o in allobs:
        if o not in keep:
            bpy.data.objects.remove(o, do_unlink=True)
    objs = [o for o in bpy.data.objects if o.type == "MESH"]
    if not objs:
        raise SystemExit(f"preset {preset!r} selected nothing")

    # subject frame
    pts = []
    for o in objs:
        n = len(o.data.vertices)
        co = np.empty(n * 3, dtype=np.float64)
        o.data.vertices.foreach_get("co", co)
        co = co.reshape(n, 3)
        m = np.array(o.matrix_world)
        pts.append(co @ m[:3, :3].T + m[:3, 3])
    Q = np.vstack(pts)
    c = (Q.min(0) + Q.max(0)) / 2
    r = float(np.linalg.norm(Q.max(0) - Q.min(0))) / 2 * 1.12

    setup_engine(samples, res)
    bg = world_grey(0.22)
    lights()

    VIEWS = {
        "side_L": (90, 0), "side_R": (270, 0),
        "front": (0, 0), "rear": (180, 0),
        "f34_R": (35, 12), "f34_L": (325, 12),
        "r34_R": (145, 12), "r34_L": (215, 12),
        "top": (0, 89),
    }
    if views:
        VIEWS = {k: VIEWS[k] for k in views.split(",") if k in VIEWS}

    report = {"source": src, "preset": preset, "shading": shading,
              "objects": sorted(o.name for o in objs),
              "world_bg": bg, "res": res, "samples": samples,
              "subject_centre": [round(float(v), 5) for v in c],
              "subject_radius": round(r, 5),
              "car_centre": [round(float(v), 5) for v in car_c],
              "car_radius": round(car_r, 5),
              "frames": {}}

    modes = [("cullOFF", False), ("cullON", True)]
    for mname, cull in modes:
        if shading == "clay":
            clay(objs, cull)
        elif shading == "faceori":
            face_orientation(objs)
        elif shading == "matid":
            matid(objs)
        else:
            keep_shading(cull)
        if shading in ("faceori", "matid") and mname == "cullON":
            continue     # those two are culling-independent by construction
        for vname, (az, el) in VIEWS.items():
            ortho_cam(c, r, az, el)
            fp = os.path.join(outdir, f"{preset}_{shading}_{mname}_{vname}.png")
            render_to(fp)
            report["frames"][os.path.basename(fp)] = measure(fp)
            print("FRAME", os.path.basename(fp), report["frames"][os.path.basename(fp)])

    with open(os.path.join(outdir, f"REPORT_{preset}_{shading}.json"), "w") as fh:
        json.dump(report, fh, indent=1)
    print("DIAG_RENDER_DONE", preset, shading, len(report["frames"]), "frames")


if __name__ == "__main__":
    main()
