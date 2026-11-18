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

IT IS COMPLETELY OFFLINE. No key, no account, no network: the render is
a subprocess, not a request. Every material is PROCEDURAL — Blender's
own brick, noise and wave textures evaluated on the user's machine —
because a texture library would mean a download, a licence and a thing
to go missing. `offline_render()` asserts it, and a test pins it.

WHAT MAKES IT THIS HOUSE AND NOT A HOUSE. Four things, in descending
order of how much they are worth:

  1. The footprint, heights and roof pitch, which are survey-derived.
  2. The openings, when the model has them — the renderer draws the
     windows that were recorded, where they were recorded, matching the
     elevation sheets exactly.
  3. The materials, when OpenStreetMap recorded what the walls and roof
     are made of. Rare on British housing, but free and real when there.
  4. Failing 3, an assumption, which `palette()` labels as assumed so
     the caption can say so rather than implying a survey.

The honest ceiling without a photograph is "a house of exactly these
dimensions, in plausible materials". To go past that you need a picture
of the actual building, which is what building/facade.py rectifies onto
a measured wall — the true one-of-one clone, and the next step up.
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
CAPTION_TAGGED = ("MEASURED GEOMETRY — materials as recorded for this "
                  "building. Walls, heights and roof pitch are "
                  "survey-derived.")


class NotAvailable(RuntimeError):
    """Raised with a reason a person can act on."""


def usable() -> tuple:
    """(ok, reason). Checked before the UI offers the button."""
    exe = shutil.which(BLENDER)
    if not exe:
        return (False, f"Blender is not on PATH (looked for {BLENDER!r}). "
                       f"It is a free download from blender.org; this "
                       f"renderer needs {MIN_VERSION[0]}.{MIN_VERSION[1]} "
                       f"or newer and nothing else — no key, no account, "
                       f"no network.")
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


# ------------------------------------------------------- materials

# Real British domestic colours, as linear RGB. Named so the report can
# say which was used and whether it was recorded or assumed.
_WALL = {
    "brick": (0.185, 0.062, 0.042),
    "red_brick": (0.195, 0.058, 0.038),
    "yellow_brick": (0.30, 0.23, 0.12),
    "london_stock": (0.26, 0.20, 0.12),
    "sandstone": (0.33, 0.26, 0.17),
    "stone": (0.28, 0.26, 0.23),
    "limestone": (0.40, 0.37, 0.31),
    "render": (0.52, 0.50, 0.46),
    "plaster": (0.52, 0.50, 0.46),
    "concrete": (0.44, 0.44, 0.42),
    "wood": (0.25, 0.15, 0.08),
    "timber": (0.25, 0.15, 0.08),
}
_ROOF = {
    "tile": (0.048, 0.042, 0.038),
    "tiles": (0.048, 0.042, 0.038),
    "roof_tiles": (0.048, 0.042, 0.038),
    "clay": (0.145, 0.055, 0.032),
    "slate": (0.026, 0.028, 0.032),
    "concrete": (0.14, 0.14, 0.14),
    "metal": (0.18, 0.19, 0.20),
    "thatch": (0.34, 0.26, 0.13),
}
# Colour words OSM uses, where no material was given.
_NAMED = {
    "red": (0.33, 0.07, 0.05), "brown": (0.22, 0.13, 0.07),
    "white": (0.80, 0.79, 0.76), "cream": (0.73, 0.69, 0.57),
    "grey": (0.33, 0.33, 0.33), "gray": (0.33, 0.33, 0.33),
    "black": (0.035, 0.035, 0.035), "yellow": (0.52, 0.42, 0.18),
    "buff": (0.47, 0.40, 0.26), "green": (0.14, 0.22, 0.12),
    "blue": (0.12, 0.16, 0.30),
}


def _hex_rgb(text):
    t = (text or "").strip().lstrip("#")
    if len(t) == 6:
        try:
            srgb = [int(t[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
        except ValueError:
            return None
        # sRGB -> linear, because Blender's Base Color is linear and a
        # hex pasted straight in comes out washed out.
        return tuple(c / 12.92 if c <= 0.04045
                     else ((c + 0.055) / 1.055) ** 2.4 for c in srgb)
    return None


def palette(bld) -> dict:
    """Colours for this building, and whether they were recorded.

    `assumed` lists what nobody told us, so the caller can caption the
    picture honestly instead of implying the brick was surveyed.
    """
    m = (getattr(bld, "materials", None) or {})
    assumed, used = [], {}

    def pick(table, mat_key, col_key, default, what):
        mat = (m.get(mat_key) or "").strip().lower().replace(" ", "_")
        col = m.get(col_key)
        rgb = _hex_rgb(col) or _NAMED.get((col or "").strip().lower())
        if mat in table:
            used[what] = mat
            # A recorded colour refines a recorded material.
            return rgb or table[mat]
        if rgb is not None:
            used[what] = f"colour {col}"
            return rgb
        assumed.append(what)
        return default

    wall = pick(_WALL, "wall_material", "wall_colour",
                _WALL["red_brick"], "walls")
    roof = pick(_ROOF, "roof_material", "roof_colour",
                _ROOF["tile"], "roof")
    wall_mat = (m.get("wall_material") or "").strip().lower()
    return {
        "wall_rgb": list(wall),
        "roof_rgb": list(roof),
        # Render and stone are smooth; brick gets a bond pattern.
        "wall_is_masonry": wall_mat not in ("render", "plaster", "concrete"),
        "recorded": used,
        "assumed": assumed,
    }


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
    # THE OVERHANG IS WHY A REAL ROOF READS AS A ROOF. A roof plane that
    # stops dead on the wall face is the single clearest tell of an
    # untextured CAD massing: real eaves project, throw a shadow line
    # along the top of the wall, and carry the verge past the gable.
    # from_footprint already records 0.3 m; this draws it. The wall
    # geometry is untouched — the measured envelope does not move,
    # only the roof that sits on it.
    oh = float(roof.get("overhang") or 0.0)
    drop = oh * t
    if kind == "hipped":
        oh = 0.0                  # a hip would need every edge mitred
        drop = 0.0
    if along_x:
        my = (y0 + y1) / 2.0
        ex0, ex1 = x0 - oh, x1 + oh
        ey0, ey1 = y0 - oh, y1 + oh
        ez = eaves - drop
        rx0, rx1 = ((x0 + (y1 - y0) / 2.0, x1 - (y1 - y0) / 2.0)
                    if kind == "hipped" else (ex0, ex1))
        faces.append(("roof", [V(ex0, ey0, ez), V(ex1, ey0, ez),
                               V(rx1, my, top), V(rx0, my, top)]))
        faces.append(("roof", [V(ex1, ey1, ez), V(ex0, ey1, ez),
                               V(rx0, my, top), V(rx1, my, top)]))
        faces.append(("wall", [V(x0, y1, eaves), V(x0, y0, eaves),
                               V(x0, my, eaves + (span / 2.0) * t)]))
        faces.append(("wall", [V(x1, y0, eaves), V(x1, y1, eaves),
                               V(x1, my, eaves + (span / 2.0) * t)]))
    else:
        mx = (x0 + x1) / 2.0
        ex0, ex1 = x0 - oh, x1 + oh
        ey0, ey1 = y0 - oh, y1 + oh
        ez = eaves - drop
        ry0, ry1 = ((y0 + (x1 - x0) / 2.0, y1 - (x1 - x0) / 2.0)
                    if kind == "hipped" else (ey0, ey1))
        faces.append(("roof", [V(ex0, ey0, ez), V(ex0, ey1, ez),
                               V(mx, ry1, top), V(mx, ry0, top)]))
        faces.append(("roof", [V(ex1, ey1, ez), V(ex1, ey0, ez),
                               V(mx, ry0, top), V(mx, ry1, top)]))
        faces.append(("wall", [V(x0, y0, eaves), V(x1, y0, eaves),
                               V(mx, y0, eaves + (span / 2.0) * t)]))
        faces.append(("wall", [V(x1, y1, eaves), V(x0, y1, eaves),
                               V(mx, y1, eaves + (span / 2.0) * t)]))
    return {"verts": verts, "faces": faces, "top": top}


# ------------------------------------------------------- openings

# front: (x0,y0)->(x1,y0); rear: (x1,y1)->(x0,y1);
# left: (x0,y1)->(x0,y0); right: (x1,y0)->(x1,y1).
# EXACTLY sheets._edge_points, so a window in the render is the window
# on the elevation. Two conventions would put them in different places
# and only one drawing would be wrong.
def edge_points(b, edge):
    x0, y0 = b["x"], b["y"]
    x1, y1 = x0 + b["width"], y0 + b["depth"]
    return {"front": ((x0, y0), (x1, y0)),
            "rear": ((x1, y1), (x0, y1)),
            "left": ((x0, y1), (x0, y0)),
            "right": ((x1, y0), (x1, y1))}.get(edge)


def opening_quads(blocks, openings, inset=0.09):
    """Each opening as a flat quad on its wall, set back in the reveal.

    A quad rather than a hole cut with a boolean: a boolean through a
    wall that a roof plane also meets is the kind of operation that
    fails silently and leaves a hole in the render. A recessed pane with
    a frame reads correctly and cannot corrupt the mesh.
    """
    by_id = {b["id"]: b for b in blocks}
    out = []
    for o in openings:
        b = by_id.get(o.get("block_id"))
        if b is None:
            continue
        seg = edge_points(b, o.get("edge"))
        if seg is None:
            continue
        (ax, ay), (bx, by) = seg
        L = math.hypot(bx - ax, by - ay) or 1.0
        ux, uy = (bx - ax) / L, (by - ay) / L
        # inward normal: the wall runs along u, the inside is to its left
        nx, ny = uy, -ux
        a0 = float(o.get("along_m", 0.0))
        w = float(o.get("width", 1.2))
        h = float(o.get("height", 1.2))
        if a0 < -1e-6 or a0 + w > L + 1e-6 or w <= 0 or h <= 0:
            continue                       # not on this wall; skip it
        sh = float(b.get("storey_height", 2.65))
        z0 = int(o.get("level", 0)) * sh + float(o.get("sill", 0.9))
        p0 = (ax + ux * a0 + nx * inset, ay + uy * a0 + ny * inset)
        p1 = (p0[0] + ux * w, p0[1] + uy * w)
        out.append({
            "kind": o.get("kind", "window"),
            "quad": [[p0[0], p0[1], z0], [p1[0], p1[1], z0],
                     [p1[0], p1[1], z0 + h], [p0[0], p0[1], z0 + h]],
            # the frame sits just proud of the pane, on the wall face
            "frame": [[p0[0] - nx * inset, p0[1] - ny * inset, z0],
                      [p1[0] - nx * inset, p1[1] - ny * inset, z0],
                      [p1[0] - nx * inset, p1[1] - ny * inset, z0 + h],
                      [p0[0] - nx * inset, p0[1] - ny * inset, z0 + h]],
        })
    return out


def derived_openings(blocks, storeys_by_block):
    """A plausible domestic rhythm, when the model records none.

    INDICATIVE AND LABELLED AS SUCH. A blank brick box is not what the
    house looks like either, so the choice is between two kinds of
    wrong; this one is wrong in the way the caption already declares.
    Anything the model DOES record is used instead of this.
    """
    out = []
    for b in blocks:
        n = max(1, int(storeys_by_block.get(b["id"], 2)))
        sh = float(b.get("storey_height", 2.65))
        for edge in ("front", "rear", "left", "right"):
            seg = edge_points(b, edge)
            (ax, ay), (bx, by) = seg
            L = math.hypot(bx - ax, by - ay)
            if L < 2.2:
                continue
            # A HOUSE, NOT A BLOCK OF FLATS. One opening per ~4.2 m of
            # wall, and at most two on a wall: the first pass put 24
            # windows on a three-bed semi, which is an institutional
            # rhythm and reads instantly as generated.
            bays = max(1, min(2, int(L // 4.2)))
            for lvl in range(n):
                for i in range(bays):
                    centre = L * (i + 0.5) / bays
                    w = min(1.35, L / bays * 0.45)
                    door = (edge == "front" and lvl == 0 and i == bays // 2)
                    h = 2.0 if door else 1.25
                    sill = 0.0 if door else 0.95
                    if door:
                        w = min(0.95, w)
                    out.append({"block_id": b["id"], "edge": edge,
                                "kind": "door" if door else "window",
                                "along_m": centre - w / 2.0, "width": w,
                                "height": h, "sill": sill, "level": lvl})
    return out


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


def scene(massing: dict, bld=None) -> dict:
    """The whole model, plus what a camera needs to frame it."""
    solids = massing.get("solids") or []
    blocks = [solid_mesh(s) for s in solids]
    if not blocks:
        raise NotAvailable("there is no geometry to render")
    plan = []
    storeys = {}
    for s in solids:
        ring = [p for p in s["ring"]]
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        bid = s.get("id") or f"b{len(plan)}"
        plan.append({"id": bid, "x": min(xs), "y": min(ys),
                     "width": max(xs) - min(xs), "depth": max(ys) - min(ys),
                     "storey_height": float(s.get("storey_height", 2.65))})
        eaves = float(s.get("eaves_m", 5.3))
        storeys[bid] = max(1, round(eaves / float(s.get("storey_height", 2.65))))

    recorded = [o.as_dict() if hasattr(o, "as_dict") else dict(o)
                for o in (getattr(bld, "openings", None) or [])]
    if recorded:
        quads, opening_source = opening_quads(plan, recorded), "model"
    else:
        quads = opening_quads(plan, derived_openings(plan, storeys))
        opening_source = "derived"

    xs = [v[0] for b in blocks for v in b["verts"]]
    ys = [v[1] for b in blocks for v in b["verts"]]
    top = max(b["top"] for b in blocks)
    return {"blocks": blocks, "openings": quads,
            "opening_source": opening_source,
            "bounds": [min(xs), min(ys), max(xs), max(ys)], "top": top}


# --------------------------------------------------------- render
#
# Every texture below is PROCEDURAL — Blender's own Brick, Noise and
# Wave nodes. No image files, so no download, no licence and nothing to
# go missing: the render works on a machine that has never been online.

_SCRIPT = r'''
import bpy, json, math, os

spec = json.load(open(os.environ["TWIN_SPEC"]))
S = spec["scene"]
P = spec["palette"]

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
# Blender 4.2 defaults to AgX, which is built for film latitude and
# renders a brick wall as grey suede. Standard with the exposure
# actually controlled is what an architectural visualisation wants.
try:
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.view_settings.exposure = spec["exposure"]
except Exception:
    pass


def face_uvs(me):
    """Metre-scale UVs from the geometry itself.

    WITHOUT THIS THE BRICK IS STRIPES. Blender's Brick texture reads
    vector.x and vector.y and ignores z, so on a wall standing in the
    x-z plane every course collapses into a vertical smear. Generated
    coordinates cannot fix that; the wall needs its own 2D frame.

    So each face gets one: u runs ALONG the face, v runs UP it, both in
    metres. A course is then 75 mm up the wall whichever way the wall
    faces, and the roof battens run across the slope rather than across
    the world.
    """
    uv = me.uv_layers.new(name="UVMap")
    for poly in me.polygons:
        n = poly.normal
        if abs(n.z) < 0.85:
            # a wall: along the wall, and straight up
            t1 = (-n.y, n.x, 0.0)
            L = math.hypot(t1[0], t1[1]) or 1.0
            t1 = (t1[0] / L, t1[1] / L, 0.0)
            t2 = (0.0, 0.0, 1.0)
        else:
            # flat roof or floor: world x and y are as good as any
            t1, t2 = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)
        if 0.05 < abs(n.z) < 0.999:
            # a PITCHED roof: run v up the slope, so the courses lie
            # across the fall the way tiles actually do
            t1 = (-n.y, n.x, 0.0)
            L = math.hypot(t1[0], t1[1]) or 1.0
            t1 = (t1[0] / L, t1[1] / L, 0.0)
            t2 = (n.y * t1[2] - n.z * t1[1],
                  n.z * t1[0] - n.x * t1[2],
                  n.x * t1[1] - n.y * t1[0])
            L2 = math.sqrt(sum(c * c for c in t2)) or 1.0
            t2 = tuple(c / L2 for c in t2)
        for li in poly.loop_indices:
            p = me.vertices[me.loops[li].vertex_index].co
            uv.data[li].uv = (p.x * t1[0] + p.y * t1[1] + p.z * t1[2],
                              p.x * t2[0] + p.y * t2[1] + p.z * t2[2])


def new_mat(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    return m, nt, nt.nodes["Principled BSDF"]


def set_in(bsdf, key, value):
    if key in bsdf.inputs:
        bsdf.inputs[key].default_value = value


def masonry(name, rgb, mortar, brick_w, brick_h, bias, rough):
    """Brick/stone: bond pattern into colour, and into bump so the
    joints actually catch the light rather than being printed on."""
    m, nt, b = new_mat(name)
    tex = nt.nodes.new("ShaderNodeTexBrick")
    tex.offset = 0.5
    tex.offset_frequency = 2
    tex.squash = 1.0
    tex.inputs["Color1"].default_value = (*rgb, 1)
    tex.inputs["Color2"].default_value = (*[c * bias for c in rgb], 1)
    tex.inputs["Mortar"].default_value = (*mortar, 1)
    tex.inputs["Scale"].default_value = 1.0
    tex.inputs["Mortar Size"].default_value = 0.006
    tex.inputs["Mortar Smooth"].default_value = 0.1
    tex.inputs["Bias"].default_value = 0.0
    tex.inputs["Brick Width"].default_value = brick_w
    tex.inputs["Row Height"].default_value = brick_h
    coord = nt.nodes.new("ShaderNodeUVMap")
    coord.uv_map = "UVMap"
    nt.links.new(tex.inputs["Vector"], coord.outputs["UV"])
    nt.links.new(b.inputs["Base Color"], tex.outputs["Color"])
    # grime/variation so large walls are not one flat tone
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 1.6
    noise.inputs["Detail"].default_value = 6.0
    nt.links.new(noise.inputs["Vector"], coord.outputs["UV"])
    mixn = nt.nodes.new("ShaderNodeMix")
    mixn.data_type = "RGBA"
    mixn.blend_type = "MULTIPLY"
    mixn.inputs["Factor"].default_value = 0.22
    nt.links.new(mixn.inputs[6], tex.outputs["Color"])
    nt.links.new(mixn.inputs[7], noise.outputs["Color"])
    nt.links.new(b.inputs["Base Color"], mixn.outputs[2])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.45
    bump.inputs["Distance"].default_value = 0.015
    nt.links.new(bump.inputs["Height"], tex.outputs["Fac"])
    nt.links.new(b.inputs["Normal"], bump.outputs["Normal"])
    set_in(b, "Roughness", rough)
    set_in(b, "Specular IOR Level", 0.2)
    return m


def flat(name, rgb, rough=0.9, noise_scale=None):
    m, nt, b = new_mat(name)
    set_in(b, "Base Color", (*rgb, 1))
    set_in(b, "Roughness", rough)
    if noise_scale:
        coord = nt.nodes.new("ShaderNodeTexCoord")
        noise = nt.nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = noise_scale
        noise.inputs["Detail"].default_value = 8.0
        nt.links.new(noise.inputs["Vector"], coord.outputs["Object"])
        bump = nt.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.18
        nt.links.new(bump.inputs["Height"], noise.outputs["Fac"])
        nt.links.new(b.inputs["Normal"], bump.outputs["Normal"])
    return m


def glass(name):
    """Dark, glossy, slightly reflective. Not transmissive: a real
    window at daylight reads as a dark mirror of the sky, and actual
    transmission would show an empty interior that is not modelled."""
    m, nt, b = new_mat(name)
    set_in(b, "Base Color", (0.035, 0.045, 0.055, 1))
    set_in(b, "Roughness", 0.07)
    set_in(b, "Metallic", 0.55)
    set_in(b, "Specular IOR Level", 0.9)
    return m


WALL = masonry("Wall", tuple(P["wall_rgb"]), (0.40, 0.385, 0.355),
               0.215, 0.075, 0.82, 0.88) if P["wall_is_masonry"] else \
       flat("Render", tuple(P["wall_rgb"]), 0.92, 9.0)
# Roof: same node, tuned to a tile course — 265 mm gauge, 165 mm wide.
ROOF = masonry("Roof", tuple(P["roof_rgb"]), (0.040, 0.038, 0.035),
               0.165, 0.265, 0.86, 0.72)
GLASS = glass("Glass")
FRAME = flat("Frame", (0.62, 0.62, 0.60), 0.35)
DOOR = flat("Door", (0.06, 0.09, 0.07), 0.3)
GRASS = flat("Grass", (0.055, 0.105, 0.030), 0.95, 60.0)
DRIVE = flat("Drive", (0.10, 0.092, 0.085), 0.8, 30.0)

for i, blk in enumerate(S["blocks"]):
    me = bpy.data.meshes.new(f"block{i}")
    verts = [tuple(v) for v in blk["verts"]]
    polys, slots = [], []
    for kind, idx in blk["faces"]:
        polys.append(tuple(idx))
        slots.append(kind)
    me.from_pydata(verts, [], polys)
    me.update()
    face_uvs(me)
    ob = bpy.data.objects.new(f"block{i}", me)
    sc.collection.objects.link(ob)
    order = ["wall", "roof"]
    ob.data.materials.append(WALL)
    ob.data.materials.append(ROOF)
    for p, kind in zip(me.polygons, slots):
        p.material_index = order.index(kind)

# openings: a recessed pane plus a frame plate on the wall face
for j, op in enumerate(S["openings"]):
    for part, mat, name in (("quad", GLASS if op["kind"] != "door" else DOOR,
                             "pane"),
                            ("frame", FRAME, "frame")):
        quad = op[part]
        me = bpy.data.meshes.new(f"{name}{j}")
        me.from_pydata([tuple(v) for v in quad], [], [(0, 1, 2, 3)])
        me.update()
        ob = bpy.data.objects.new(f"{name}{j}", me)
        if part == "frame":
            # shrink the frame plate so it reads as a surround
            ob.scale = (1.0, 1.0, 1.0)
        ob.data.materials.append(mat)
        sc.collection.objects.link(ob)
    # solid reveal behind the pane so it does not float
    pass

x0, y0, x1, y1 = S["bounds"]
cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
bpy.ops.mesh.primitive_plane_add(size=600.0, location=(cx, cy, 0.0))
bpy.context.object.data.materials.append(GRASS)

# a drive, offscreen-safe: a flat slab in front of the building
bpy.ops.mesh.primitive_plane_add(size=1.0, location=(cx, y0 - 5.0, 0.01))
drv = bpy.context.object
drv.scale = ((x1 - x0) * 0.55, 5.0, 1.0)
drv.data.materials.append(DRIVE)

sun_data = bpy.data.lights.new("Sun", type="SUN")
sun_data.energy = spec["sun_energy"]
sun_data.angle = math.radians(1.5)
sun = bpy.data.objects.new("Sun", sun_data)
sc.collection.objects.link(sun)
alt = math.radians(max(spec["sun_alt"], 4.0))
az = math.radians(spec["sun_az"])
# SUN AZIMUTH IS WHERE THE SUN IS, NOT WHERE THE LIGHT GOES.
# With euler (90-alt, 0, -az) the light TRAVELS toward az, which puts
# the sun diametrically opposite where it belongs: every facade that
# should have been sunlit came back in shadow, and the shadow fell on
# the wrong side of the house. Work the vector through -
#   d = Rz(rz) Rx(rx) (0,0,-1) = (-cos a sin rz, cos a cos rz, -sin a)
# - and rz = pi - az gives d = (-cos a sin az, -cos a cos az, -sin a),
# i.e. light arriving FROM az. That now matches render3d.js setSun,
# whose uSun points at the sun from the surface.
sun.rotation_euler = (math.radians(90.0) - alt, 0.0, math.pi - az)

# THE SKY HAS TWO JOBS AND THEY NEED DIFFERENT BRIGHTNESSES. As a
# LIGHT it must stay dim: Nishita returns physical radiance, and at the
# strength that looks right in shot it washes every surface out — red
# brick came back salmon and the grass came back radioactive. As a
# BACKDROP it must be bright, or the house stands against a dark band
# that reads as night. A Light Path node separates them: camera rays
# see the bright sky, everything else sees a fraction of it.
w = bpy.data.worlds.new("W")
w.use_nodes = True
wnt = w.node_tree
bg = wnt.nodes["Background"]
sky = wnt.nodes.new("ShaderNodeTexSky")
try:
    sky.sky_type = "NISHITA"
    sky.sun_elevation = alt
    sky.sun_rotation = -az
    sky.altitude = 120.0
    sky.air_density = 1.6
    sky.dust_density = 2.4
    sky.sun_disc = False          # the sun lamp is the sun
    wnt.links.new(bg.inputs["Color"], sky.outputs["Color"])
except Exception:
    bg.inputs["Color"].default_value = (0.52, 0.58, 0.68, 1)

lp = wnt.nodes.new("ShaderNodeLightPath")
mixs = wnt.nodes.new("ShaderNodeMixShader")
camera_bg = wnt.nodes.new("ShaderNodeBackground")
camera_bg.inputs["Strength"].default_value = spec["sky_visible"]
try:
    wnt.links.new(camera_bg.inputs["Color"], sky.outputs["Color"])
except Exception:
    camera_bg.inputs["Color"].default_value = (0.52, 0.58, 0.68, 1)
bg.inputs["Strength"].default_value = spec["sky"]
out = wnt.nodes["World Output"]
wnt.links.new(mixs.inputs[0], lp.outputs["Is Camera Ray"])
wnt.links.new(mixs.inputs[1], bg.outputs["Background"])
wnt.links.new(mixs.inputs[2], camera_bg.outputs["Background"])
wnt.links.new(out.inputs["Surface"], mixs.outputs["Shader"])
sc.world = w

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


def render(massing: dict, *, out_path: str, bld=None, width=1280, height=1024,
           samples=128, yaw=0.7, pitch=0.5, dist=None, lens_mm=40.0,
           sun_alt=52.0, sun_az=180.0, sky=0.030, sky_visible=0.85,
           sun_energy=2.6, exposure=0.0, timeout_s=1800) -> dict:
    """Render the measured massing with Cycles. Returns a report.

    Offline by construction: Blender is launched with --factory-startup
    and --offline-mode, every texture is procedural, and nothing in the
    spec is a URL.
    """
    ok, why = usable()
    if not ok:
        raise NotAvailable(why)
    sc = scene(massing, bld)
    pal = palette(bld) if bld is not None else palette(_NoMaterials())
    x0, y0, x1, y1 = sc["bounds"]
    extent = max(x1 - x0, y1 - y0, 6.0)
    spec = {
        "scene": sc, "palette": pal, "out": out_path,
        "width": width, "height": height, "samples": samples,
        "yaw": yaw, "pitch": pitch,
        "dist": dist if dist else extent * 2.0, "lens_mm": lens_mm,
        # THE SUN ARRIVES AS A COMPASS BEARING, THE SCENE IS NOT NORTH-UP.
        # Blender is handed the BUILDING frame, whose +y points along
        # the building's depth axis at bearing_deg. Feeding a compass
        # azimuth straight in rotated every shadow by that bearing — up
        # to 180 degrees wrong — so the render disagreed with the
        # viewer's own shadow study about which side of the house the
        # sun was on. Convert once, here.
        "sun_alt": sun_alt,
        "sun_az": (sun_az - float(getattr(bld, "bearing_deg", 0.0) or 0.0)) % 360.0,
        "sun_az_compass": sun_az, "sky": sky,
        "sky_visible": sky_visible,
        "sun_energy": sun_energy, "exposure": exposure,
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
                blender_argv(script_path),
                capture_output=True, text=True, timeout=timeout_s, env=env)
        except subprocess.TimeoutExpired:
            raise NotAvailable(f"Blender did not finish within {timeout_s}s")
    if "TWIN_RENDER_OK" not in (proc.stdout or ""):
        tail = ((proc.stderr or "") + (proc.stdout or ""))[-400:]
        raise NotAvailable(f"Blender failed to render: {tail}")
    if not os.path.exists(out_path):
        raise NotAvailable("Blender reported success but wrote no file")
    tagged = bool(pal["recorded"])
    return {
        "path": out_path,
        "engine": "cycles",
        "samples": samples,
        "blocks": len(sc["blocks"]),
        "openings": len(sc["openings"]),
        "openings_from": sc["opening_source"],
        "materials_recorded": pal["recorded"],
        "materials_assumed": pal["assumed"],
        "classification": "derived",
        "caption": CAPTION_TAGGED if tagged else CAPTION,
        "offline": True,
        "sun_azimuth_compass": sun_az,
        "sun_azimuth_scene": (sun_az - float(getattr(bld, "bearing_deg", 0.0)
                                             or 0.0)) % 360.0,
        "sun_altitude": sun_alt,
        # NOT a fidelity score. There is nothing to score: the renderer
        # was handed the measured geometry and photographed it.
        "geometry": "measured — rendered directly, not regenerated",
    }


def blender_argv(script_path):
    """The exact command line. Separated so a test can assert it.

    --offline-mode stops Blender contacting anything (extensions, update
    checks); --factory-startup ignores whatever add-ons the machine has,
    so the render is the same on every machine and cannot be changed by
    something installed locally.
    """
    return [shutil.which(BLENDER), "--background", "--factory-startup",
            "--offline-mode", "--python", script_path]


class _NoMaterials:
    materials = {}
    openings = []
