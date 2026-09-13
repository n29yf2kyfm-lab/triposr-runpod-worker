"""Photoreal rendering of the MEASURED geometry, locally, in Blender.

WHY THIS IS A DIFFERENT CLAIM FROM providers/visual.py. The impression
path sends a picture of the model to an image model and asks it not to
move anything; it can, so fidelity.py checks and refuses. This path
never leaves the model at all. Blender is handed the same rectangles,
eaves and ridge the floor plan and the schedules are drawn from, and
Cycles photographs them. The geometry cannot drift because nothing
regenerates it — fidelity is 1.0 by construction, and there is nothing
to check.

So the honest caption changes, and that is the point:

    impression:  "ARTIST'S IMPRESSION — generated, not a photograph."
    this:        "MEASURED GEOMETRY — materials and openings indicative."

Walls, heights, roof pitch and ridge are survey-derived. Brick colour,
tile colour, glass and grass are assigned, and openings are drawn only
when the model actually has them. Nothing here invents a volume.

It needs Blender >= 4.2 on PATH and no network, no API key and no
account. A render is a subprocess, not a request, so it cannot be rate
limited, deprecated, or switched off by somebody else's billing.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile

BLENDER = os.environ.get("BLENDER_BIN", "blender")
MIN_VERSION = (4, 2)

CAPTION = ("MEASURED GEOMETRY — materials and openings are indicative. "
           "Walls, heights and roof pitch are survey-derived.")


class NotAvailable(RuntimeError):
    """Raised with a reason a person can act on."""


def usable() -> tuple:
    """(ok, reason). Checked before the UI offers the button."""
    exe = shutil.which(BLENDER)
    if not exe:
        return (False, f"Blender is not on PATH (looked for {BLENDER!r}). "
                       f"It is a free download from blender.org; this "
                       f"renderer needs {MIN_VERSION[0]}.{MIN_VERSION[1]} "
                       f"or newer and nothing else — no key, no account.")
    try:
        out = subprocess.run([exe, "--version"], capture_output=True,
                             text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError) as e:
        return (False, f"Blender would not start: {e}")
    ver = _parse_version(out)
    if ver is None:
        return (False, f"could not read a version out of {out.strip()[:60]!r}")
    if ver < MIN_VERSION:
        return (False, f"Blender {ver[0]}.{ver[1]} is too old; this needs "
                       f"{MIN_VERSION[0]}.{MIN_VERSION[1]} or newer")
    return (True, "")


def _parse_version(text: str):
    for token in (text or "").split():
        bits = token.split(".")
        if len(bits) >= 2 and bits[0].isdigit() and bits[1].isdigit():
            return (int(bits[0]), int(bits[1]))
    return None


# ------------------------------------------------------- geometry

def solid_mesh(solid: dict) -> dict:
    """Walls and roof for one block, as verts and faces in metres.

    THE SAME MATHS AS THE WEBGL VIEWER. render3d.js builds this from the
    identical fields, so the Blender render and the on-screen model are
    the same building rather than two readings of one spec. Plan (x, y)
    maps to Blender (x, y) with z up; the viewer's y-up is its own
    convention, not the model's.
    """
    ring = list(solid["ring"])
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring = ring[:-1]
    base = float(solid.get("base_m", 0.0))
    eaves = float(solid.get("eaves_m", 3.0))
    roof = solid.get("roof") or {}
    kind = roof.get("kind") or "flat"
    pitch = float(roof.get("pitch_deg") or 0.0)

    verts, faces = [], []

    def V(x, y, z):
        verts.append((float(x), float(y), float(z)))
        return len(verts) - 1

    # walls
    low = [V(x, y, base) for x, y in ring]
    high = [V(x, y, eaves) for x, y in ring]
    n = len(ring)
    for i in range(n):
        j = (i + 1) % n
        faces.append(("wall", [low[i], low[j], high[j], high[i]]))

    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)

    if kind == "flat" or not pitch:
        faces.append(("roof", [V(x0, y0, eaves), V(x1, y0, eaves),
                               V(x1, y1, eaves), V(x0, y1, eaves)]))
        return {"verts": verts, "faces": faces, "top": eaves}

    along_x = (roof.get("ridge_along") or "y") == "x"
    span = (y1 - y0) if along_x else (x1 - x0)
    t = math.tan(math.radians(pitch))

    if kind == "monopitch":
        top = eaves + span * t
        high_side = roof.get("high_side") == "max"
        if along_x:
            ry, ly = (y1, y0) if high_side else (y0, y1)
            faces.append(("roof", [V(x0, ly, eaves), V(x1, ly, eaves),
                                   V(x1, ry, top), V(x0, ry, top)]))
            faces.append(("wall", [V(x0, ly, eaves), V(x0, ry, top),
                                   V(x0, ry, eaves)]))
            faces.append(("wall", [V(x1, ly, eaves), V(x1, ry, eaves),
                                   V(x1, ry, top)]))
        else:
            rx, lx = (x1, x0) if high_side else (x0, x1)
            faces.append(("roof", [V(lx, y0, eaves), V(lx, y1, eaves),
                                   V(rx, y1, top), V(rx, y0, top)]))
            faces.append(("wall", [V(lx, y0, eaves), V(rx, y0, top),
                                   V(rx, y0, eaves)]))
            faces.append(("wall", [V(lx, y1, eaves), V(rx, y1, eaves),
                                   V(rx, y1, top)]))
        return {"verts": verts, "faces": faces, "top": top}

    # gabled / hipped
    top = eaves + (span / 2.0) * t
    if along_x:
        my = (y0 + y1) / 2.0
        rx0, rx1 = ((x0 + (y1 - y0) / 2.0, x1 - (y1 - y0) / 2.0)
                    if kind == "hipped" else (x0, x1))
        faces.append(("roof", [V(x0, y0, eaves), V(x1, y0, eaves),
                               V(rx1, my, top), V(rx0, my, top)]))
        faces.append(("roof", [V(x1, y1, eaves), V(x0, y1, eaves),
                               V(rx0, my, top), V(rx1, my, top)]))
        faces.append(("wall", [V(x0, y1, eaves), V(x0, y0, eaves),
                               V(rx0, my, top)]))
        faces.append(("wall", [V(x1, y0, eaves), V(x1, y1, eaves),
                               V(rx1, my, top)]))
    else:
        mx = (x0 + x1) / 2.0
        ry0, ry1 = ((y0 + (x1 - x0) / 2.0, y1 - (x1 - x0) / 2.0)
                    if kind == "hipped" else (y0, y1))
        faces.append(("roof", [V(x0, y0, eaves), V(x0, y1, eaves),
                               V(mx, ry1, top), V(mx, ry0, top)]))
        faces.append(("roof", [V(x1, y1, eaves), V(x1, y0, eaves),
                               V(mx, ry0, top), V(mx, ry1, top)]))
        faces.append(("wall", [V(x0, y0, eaves), V(x1, y0, eaves),
                               V(mx, ry0, top)]))
        faces.append(("wall", [V(x1, y1, eaves), V(x0, y1, eaves),
                               V(mx, ry1, top)]))
    return {"verts": verts, "faces": faces, "top": top}


def scene(massing: dict) -> dict:
    """The whole model, plus the bounds a camera can be framed from."""
    blocks = [solid_mesh(s) for s in (massing.get("solids") or [])]
    if not blocks:
        raise NotAvailable("there is no geometry to render")
    xs = [v[0] for b in blocks for v in b["verts"]]
    ys = [v[1] for b in blocks for v in b["verts"]]
    top = max(b["top"] for b in blocks)
    return {"blocks": blocks,
            "bounds": [min(xs), min(ys), max(xs), max(ys)],
            "top": top}


def sun_vector(lat_deg: float, lon_deg: float, when) -> dict:
    """Where the sun actually is, by NOAA's low-precision algorithm.

    The SAME algorithm as the viewer's setSun, so a shadow in the render
    falls where the shadow on screen falls. Good to about a degree,
    which is far inside what a massing study can justify.
    """
    rad = math.pi / 180.0
    start = when.replace(month=1, day=1, hour=0, minute=0, second=0,
                         microsecond=0)
    day = (when - start).total_seconds() / 86400.0 + 1.0
    g = (357.529 + 0.98560028 * day) * rad
    q = (280.459 + 0.98564736 * day) * rad
    L = q + (1.915 * math.sin(g) + 0.020 * math.sin(2 * g)) * rad
    e = (23.439 - 0.00000036 * day) * rad
    dec = math.asin(math.sin(e) * math.sin(L))
    hours = when.hour + when.minute / 60.0
    ha = ((hours - 12.0) * 15.0 + lon_deg) * rad
    la = lat_deg * rad
    alt = math.asin(math.sin(la) * math.sin(dec) +
                    math.cos(la) * math.cos(dec) * math.cos(ha))
    az = math.atan2(-math.sin(ha),
                    math.tan(dec) * math.cos(la) - math.sin(la) * math.cos(ha))
    return {"altitude_deg": alt / rad,
            "azimuth_deg": (az / rad + 360.0) % 360.0,
            "above_horizon": alt > 0}


# --------------------------------------------------------- render

_SCRIPT = r'''
import bpy, json, math, sys, os

spec = json.load(open(os.environ["TWIN_SPEC"]))
S = spec["scene"]

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = "CYCLES"
sc.cycles.samples = spec["samples"]
sc.cycles.use_denoising = True
try:
    sc.cycles.device = "CPU"
except Exception:
    pass
sc.render.resolution_x = spec["width"]
sc.render.resolution_y = spec["height"]
sc.render.film_transparent = False
sc.render.image_settings.file_format = "PNG"
sc.render.filepath = spec["out"]


def mat(name, rgba, rough=0.85, metallic=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = rgba
    b.inputs["Roughness"].default_value = rough
    if "Metallic" in b.inputs:
        b.inputs["Metallic"].default_value = metallic
    return m


MATS = {
    "wall": mat("Brick", (0.42, 0.19, 0.13, 1.0), 0.92),
    "roof": mat("Tile",  (0.26, 0.24, 0.23, 1.0), 0.88),
    "ground": mat("Grass", (0.16, 0.28, 0.09, 1.0), 0.95),
}

for i, blk in enumerate(S["blocks"]):
    me = bpy.data.meshes.new(f"block{i}")
    verts = [tuple(v) for v in blk["verts"]]
    slots, polys = [], []
    for kind, idx in blk["faces"]:
        polys.append(tuple(idx))
        slots.append(kind)
    me.from_pydata(verts, [], polys)
    me.update()
    ob = bpy.data.objects.new(f"block{i}", me)
    sc.collection.objects.link(ob)
    order = ["wall", "roof"]
    for k in order:
        ob.data.materials.append(MATS[k])
    for p, kind in zip(me.polygons, slots):
        p.material_index = order.index(kind)
    me.shade_flat() if hasattr(me, "shade_flat") else None

# ground plane, big enough that its edge is never in shot
x0, y0, x1, y1 = S["bounds"]
cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
bpy.ops.mesh.primitive_plane_add(size=400.0, location=(cx, cy, 0.0))
bpy.context.object.data.materials.append(MATS["ground"])

# sun where the sun actually is
sun_data = bpy.data.lights.new("Sun", type="SUN")
sun_data.energy = spec["sun_energy"]
sun_data.angle = math.radians(2.0)
sun = bpy.data.objects.new("Sun", sun_data)
sc.collection.objects.link(sun)
alt = math.radians(max(spec["sun_alt"], 3.0))
az = math.radians(spec["sun_az"])
sun.rotation_euler = (math.radians(90.0) - alt, 0.0, -az)

# overcast sky so north faces are not black
w = bpy.data.worlds.new("W")
w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.55, 0.6, 0.68, 1)
w.node_tree.nodes["Background"].inputs[1].default_value = spec["sky"]
sc.world = w

# camera on the same orbit convention as the on-screen viewer
cam_data = bpy.data.cameras.new("Cam")
cam_data.lens = spec["lens_mm"]
cam = bpy.data.objects.new("Cam", cam_data)
sc.collection.objects.link(cam)
sc.camera = cam
yaw, pitch, dist = spec["yaw"], spec["pitch"], spec["dist"]
tz = S["top"] * 0.45
cam.location = (cx + math.sin(yaw) * math.cos(pitch) * dist,
                cy - math.cos(yaw) * math.cos(pitch) * dist,
                tz + math.sin(pitch) * dist)
tgt = bpy.data.objects.new("Target", None)
tgt.location = (cx, cy, tz)
sc.collection.objects.link(tgt)
c = cam.constraints.new(type="TRACK_TO")
c.target = tgt
c.track_axis = "TRACK_NEGATIVE_Z"
c.up_axis = "UP_Y"

bpy.ops.render.render(write_still=True)
print("TWIN_RENDER_OK", spec["out"])
'''


def render(massing: dict, *, out_path: str, width=1280, height=1024,
           samples=96, yaw=0.7, pitch=0.55, dist=None, lens_mm=38.0,
           sun_alt=52.0, sun_az=180.0, sky=1.2, sun_energy=3.2,
           timeout_s=900) -> dict:
    """Render the measured massing with Cycles. Returns a report."""
    ok, why = usable()
    if not ok:
        raise NotAvailable(why)
    sc = scene(massing)
    x0, y0, x1, y1 = sc["bounds"]
    extent = max(x1 - x0, y1 - y0, 6.0)
    spec = {
        "scene": sc, "out": out_path, "width": width, "height": height,
        "samples": samples, "yaw": yaw, "pitch": pitch,
        "dist": dist if dist else extent * 2.1, "lens_mm": lens_mm,
        "sun_alt": sun_alt, "sun_az": sun_az, "sky": sky,
        "sun_energy": sun_energy,
    }
    with tempfile.TemporaryDirectory() as tmp:
        spec_path = os.path.join(tmp, "spec.json")
        script_path = os.path.join(tmp, "build.py")
        with open(spec_path, "w") as fh:
            json.dump(spec, fh)
        with open(script_path, "w") as fh:
            fh.write(_SCRIPT)
        env = dict(os.environ, TWIN_SPEC=spec_path)
        try:
            proc = subprocess.run(
                [shutil.which(BLENDER), "--background", "--factory-startup",
                 "--python", script_path],
                capture_output=True, text=True, timeout=timeout_s, env=env)
        except subprocess.TimeoutExpired:
            raise NotAvailable(f"Blender did not finish within {timeout_s}s")
    if "TWIN_RENDER_OK" not in (proc.stdout or ""):
        tail = ((proc.stderr or "") + (proc.stdout or ""))[-400:]
        raise NotAvailable(f"Blender failed to render: {tail}")
    if not os.path.exists(out_path):
        raise NotAvailable("Blender reported success but wrote no file")
    return {
        "path": out_path,
        "engine": "cycles",
        "samples": samples,
        "blocks": len(sc["blocks"]),
        "classification": "derived",
        "caption": CAPTION,
        # NOT a fidelity score. There is nothing to score: the renderer
        # was handed the measured geometry and photographed it.
        "geometry": "measured — rendered directly, not regenerated",
    }
