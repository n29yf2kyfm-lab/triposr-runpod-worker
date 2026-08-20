#!/usr/bin/env python3
"""wheel_evidence.py — GATE 6 evidence renderer: the pictures a human judges.

`wheel_metrology.py` measures and `wheel_ground_op.py` repairs; neither draws
anything. This module draws, and it draws ONLY what the measurement already
says, so a reader can check the numbers against the pixels rather than taking
either on trust.

WHY THE VIEWS ARE ORTHOGRAPHIC
------------------------------
Every criterion in Gate 6 is a distance or an angle in the car's own frame:
track, hub symmetry, sidewall-versus-fender, tyre bottom against the ground.
A perspective camera makes the near wheel bigger than the far one, so a
symmetric car photographs asymmetric and an asymmetric one can photograph
square. An orthographic camera is the only one whose picture can be measured.
The front and rear views sit at HUB HEIGHT for the same reason: from above or
below the hub line the far tyre's sidewall is foreshortened against the near
one's and the fender relationship cannot be read at all.

WHY THE OVERLAY IS COMPUTED, NOT DRAWN BY HAND
----------------------------------------------
Blender renders the car and the ground grid as GEOMETRY (so occlusion is
real: a tyre that sinks below the grid is drawn in front of it, a floating
one is not). The annotations — hub crosses, centreline, axle lines, track and
clearance callouts — are drawn afterwards in image space through the exact
orthographic projection of the camera that took the frame, which the render
step writes out alongside the PNG.

That projection is VERIFIED IN EVERY FRAME rather than assumed. The render
step places a small marker sphere at each measured hub; the annotate step
projects the same hub through its own maths and draws a cross. If the cross
does not sit on the sphere, the mapping is wrong and the picture says so.
This project has twice burned renders on an unverified axis convention
(CLAUDE.md, "the render rig's azimuth convention"), so the convention here is
derived from the measurement's own axis indices and then checked on screen.

    glTF (x, y, z) -> Blender (x, -z, y)      [CLAUDE.md, seg_project.py]

EXPOSURE
--------
Standard view transform, never AgX: a clipped tyre once produced a false
defect verdict for this project (the white-tyre episode). The world is a flat
0.22 grey, which must land near sRGB 130 in the background of every frame;
`annotate` measures it and prints the number, so an exposure fault cannot be
silent. Denoising is off — this Blender has no OIDN and asking for it raises
AFTER "Blender quit" prints, which has left stale frames behind before.

Run (three modes, one file):
    blender -b --python wheel_evidence.py -- render CAR.GLB METRO.JSON OUTDIR
    python3 wheel_evidence.py annotate OUTDIR METRO.JSON
    python3 wheel_evidence.py wheels-glb CAR.GLB METRO.JSON WHEELS.GLB
"""

from __future__ import annotations

import json
import math
import os
import sys

# --------------------------------------------------------------------------
# view table: name, kind, azimuth handling. `kind` decides how the camera is
# placed from the measured frame, not from any fixed azimuth convention.
VIEWS = (
    ("front_hub", "end_near_nose"),
    ("rear_hub", "end_near_tail"),
    ("side_L", "side_plus"),
    ("side_R", "side_minus"),
    ("top", "top"),
    ("hero34", "three_quarter"),
)

GRID_STEP = 0.25          # m, ground grid pitch
GRID_HALF = 3.2           # m, grid half-extent
LINE_W = 0.004            # m, grid line width


# ============================================================ RENDER (Blender)
def render(car, metro, outd):
    import bpy
    import mathutils
    import numpy as np

    m = json.load(open(metro))
    li = m["axes"]["length"]; ti = m["axes"]["lateral"]; ui = m["axes"]["up"]
    nose = m["frame"]["nose"] or 1
    res = int(os.environ.get("EV_RES", "1400"))
    samples = int(os.environ.get("EV_SAMPLES", "24"))
    os.makedirs(outd, exist_ok=True)

    def to_bl(p):
        """glTF/world point (as the metrology sees it) -> Blender coords."""
        return mathutils.Vector((p[0], -p[2], p[1]))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=car)
    sc = bpy.context.scene

    # ---- clay override. The gate is about GEOMETRY; a baked texture or a
    # forced-transmission glass hides exactly the things being judged.
    clay = bpy.data.materials.new("clay")
    clay.use_nodes = True
    bsdf = clay.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.42, 0.43, 0.45, 1)
    bsdf.inputs["Roughness"].default_value = 0.55
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = 0.0
    car_objs = [o for o in sc.objects if o.type == "MESH"]
    for o in car_objs:
        o.data.materials.clear()
        o.data.materials.append(clay)

    # ---- ground grid, as geometry so occlusion is honest
    def strip(p0, p1, w, name, colour):
        """A flat quad on the ground plane, from p0 to p1, width w."""
        d = mathutils.Vector((p1[0] - p0[0], p1[1] - p0[1], 0))
        if d.length < 1e-9:
            return
        n = mathutils.Vector((-d.y, d.x, 0)).normalized() * (w / 2)
        vs = [(p0[0] + n.x, p0[1] + n.y, 0), (p1[0] + n.x, p1[1] + n.y, 0),
              (p1[0] - n.x, p1[1] - n.y, 0), (p0[0] - n.x, p0[1] - n.y, 0)]
        me = bpy.data.meshes.new(name)
        me.from_pydata(vs, [], [(0, 1, 2, 3)])
        ob = bpy.data.objects.new(name, me)
        mat = bpy.data.materials.new(name + "_m")
        mat.use_nodes = True
        e = mat.node_tree.nodes.new("ShaderNodeEmission")
        e.inputs[0].default_value = colour
        e.inputs[1].default_value = 1.0
        out = mat.node_tree.nodes["Material Output"]
        mat.node_tree.links.new(e.outputs[0], out.inputs[0])
        me.materials.append(mat)
        sc.collection.objects.link(ob)
        return ob

    g = int(GRID_HALF / GRID_STEP)
    for i in range(-g, g + 1):
        v = i * GRID_STEP
        c = (0.10, 0.10, 0.11, 1) if i else (0.85, 0.15, 0.15, 1)
        strip((-GRID_HALF, v), (GRID_HALF, v), LINE_W, f"gx{i}", c)
        strip((v, -GRID_HALF), (v, GRID_HALF), LINE_W, f"gy{i}", c)

    # ---- hub markers + axle rods, straight from the measurement
    for r in m["wheels"]:
        c = to_bl(r["centre"])
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.018, location=c)
        s = bpy.context.object
        s.name = "hub_" + r["corner"]
        mat = bpy.data.materials.new("hubm_" + r["corner"])
        mat.use_nodes = True
        e = mat.node_tree.nodes.new("ShaderNodeEmission")
        e.inputs[0].default_value = (0.05, 0.9, 1.0, 1)
        mat.node_tree.links.new(
            e.outputs[0], mat.node_tree.nodes["Material Output"].inputs[0])
        s.data.materials.append(mat)
        # axle rod along the FITTED axis of revolution, 0.5 m outboard
        a = to_bl(r["axis"]).normalized()
        bpy.ops.mesh.primitive_cylinder_add(radius=0.006, depth=0.5,
                                            location=c + a * 0.25)
        rod = bpy.context.object
        rod.rotation_mode = "QUATERNION"
        rod.rotation_quaternion = a.to_track_quat("Z", "Y")
        rod.data.materials.append(mat)

    # ---- lights and film
    key = bpy.data.objects.new("key", bpy.data.lights.new("key", "SUN"))
    key.data.energy = 3.0
    sc.collection.objects.link(key)
    key.rotation_euler = (math.radians(52), 0, math.radians(35))
    fill = bpy.data.objects.new("fill", bpy.data.lights.new("fill", "SUN"))
    fill.data.energy = 1.6
    sc.collection.objects.link(fill)
    fill.rotation_euler = (math.radians(60), 0, math.radians(215))
    sc.world = bpy.data.worlds.new("w")
    sc.world.use_nodes = True
    sc.world.node_tree.nodes["Background"].inputs[0].default_value = \
        (0.22, 0.22, 0.22, 1)
    sc.render.engine = "CYCLES"
    sc.cycles.samples = samples
    sc.cycles.use_denoising = False
    sc.view_layers[0].cycles.use_denoising = False
    sc.view_settings.view_transform = "Standard"       # never AgX
    sc.render.film_transparent = False
    sc.render.image_settings.file_format = "PNG"
    sc.render.resolution_x = res
    sc.render.resolution_y = res

    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    cam.data.type = "ORTHO"
    sc.collection.objects.link(cam)
    sc.camera = cam

    V = np.vstack([np.array([v.co for v in o.data.vertices]) @
                   np.array(o.matrix_world.to_3x3()).T +
                   np.array(o.matrix_world.translation) for o in car_objs])
    lo, hi = V.min(0), V.max(0)
    ctr = (lo + hi) / 2
    hub_h = float(sum(r["hub_up"] for r in m["wheels"]) / len(m["wheels"]))
    nose_x = min(r["hub_length"] for r in m["wheels"]) if nose < 0 else \
        max(r["hub_length"] for r in m["wheels"])
    D = 8.0

    maps = {}
    for name, kind in VIEWS:
        if kind == "end_near_nose":
            loc = mathutils.Vector((ctr[0] + nose * D, 0, hub_h))
            tgt = mathutils.Vector((ctr[0], 0, hub_h)); S = 2.30
        elif kind == "end_near_tail":
            loc = mathutils.Vector((ctr[0] - nose * D, 0, hub_h))
            tgt = mathutils.Vector((ctr[0], 0, hub_h)); S = 2.30
        elif kind == "side_plus":                 # glTF +lateral flank
            loc = mathutils.Vector((ctr[0], -D, hub_h))
            tgt = mathutils.Vector((ctr[0], 0, hub_h)); S = 4.80
        elif kind == "side_minus":
            loc = mathutils.Vector((ctr[0], D, hub_h))
            tgt = mathutils.Vector((ctr[0], 0, hub_h)); S = 4.80
        elif kind == "top":
            loc = mathutils.Vector((ctr[0], 0, D))
            tgt = mathutils.Vector((ctr[0], 0, 0)); S = 4.80
        else:
            loc = mathutils.Vector((ctr[0] + nose * D * 0.75, -D * 0.55,
                                    hub_h + 1.2))
            tgt = mathutils.Vector((ctr[0], 0, hub_h)); S = 5.00
        cam.location = loc
        d = (tgt - loc).normalized()
        up = "Y" if kind != "top" else "Y"
        cam.rotation_euler = d.to_track_quat("-Z", up).to_euler()
        cam.data.ortho_scale = S
        sc.render.filepath = os.path.join(outd, name + ".png")
        bpy.ops.render.render(write_still=True)
        R = cam.matrix_world.to_3x3()
        maps[name] = dict(
            loc=[loc.x, loc.y, loc.z], S=S, res=res,
            R=[[R[i][j] for j in range(3)] for i in range(3)],
            kind=kind)
    with open(os.path.join(outd, "views.json"), "w") as f:
        json.dump(dict(views=maps, axes=m["axes"], nose=nose,
                       note="Blender coords; glTF (x,y,z) -> (x,-z,y)"), f,
                  indent=1)
    print("WHEEL_EVIDENCE_RENDER_DONE")


# ============================================================ ANNOTATE (CPython)
def _proj(mp, P):
    """World (Blender) point -> (px, py) through an orthographic camera."""
    import numpy as np
    R = np.array(mp["R"]); loc = np.array(mp["loc"]); S = mp["S"]; N = mp["res"]
    v = R.T @ (np.asarray(P, float) - loc)      # camera space, looks down -Z
    return ((v[0] / S + 0.5) * N, (0.5 - v[1] / S) * N)


def annotate(outd, metro):
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    m = json.load(open(metro))
    vj = json.load(open(os.path.join(outd, "views.json")))
    ti = m["axes"]["lateral"]; ui = m["axes"]["up"]; li = m["axes"]["length"]
    rows = {r["corner"]: r for r in m["wheels"]}

    def bl(p):
        return [p[0], -p[2], p[1]]

    try:
        F = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 19)
        FB = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 23)
    except Exception:
        F = FB = ImageFont.load_default()

    exposure = {}
    for name, mp in vj["views"].items():
        p = os.path.join(outd, name + ".png")
        if not os.path.exists(p):
            continue
        im = Image.open(p).convert("RGB")
        d = ImageDraw.Draw(im)
        N = im.size[0]
        a = np.asarray(im)
        exposure[name] = float(np.median(a[4:40, 4:40]))

        def X(P):
            return _proj(mp, bl(P))

        def line(P0, P1, col, w=2):
            d.line([X(P0), X(P1)], fill=col, width=w)

        def cross(P, col, r=13, w=3):
            x, y = X(P)
            d.line([(x - r, y), (x + r, y)], fill=col, width=w)
            d.line([(x, y - r), (x, y + r)], fill=col, width=w)

        # --- ground plane line (y = 0 in car coords) and vehicle centreline
        big = 4.0
        if mp["kind"] in ("end_near_nose", "end_near_tail"):
            P = lambda lat, up: [0, up, lat]                       # noqa: E731
            line(P(-big, 0), P(big, 0), (255, 90, 90), 2)          # ground
            line(P(0, -0.2), P(0, 2.0), (255, 210, 60), 2)         # centreline
        elif mp["kind"] in ("side_plus", "side_minus"):
            P = lambda ln, up: [ln, up, 0]                          # noqa: E731
            line(P(-big, 0), P(big, 0), (255, 90, 90), 2)
        elif mp["kind"] == "top":
            P = lambda ln, lat: [ln, 0, lat]                        # noqa: E731
            line(P(-big, 0), P(big, 0), (255, 210, 60), 2)          # centreline
            for axle, pre in (("F", "F"), ("R", "R")):
                pair = [r for c, r in rows.items() if c.startswith(pre)]
                if len(pair) == 2:
                    line([pair[0]["hub_length"], 0, pair[0]["hub_lat"]],
                         [pair[1]["hub_length"], 0, pair[1]["hub_lat"]],
                         (60, 220, 255), 2)

        # --- hub crosses. These ALSO verify the projection: each cross must
        # land on the cyan marker sphere the render put at the same hub.
        for c, r in rows.items():
            cen = list(r["centre"])
            if mp["kind"] in ("end_near_nose", "end_near_tail"):
                cen[li] = 0.0            # ortho: length does not move the pixel
            elif mp["kind"] in ("side_plus", "side_minus"):
                # Both wheels of an axle project to the same pixel in a side
                # view. Label only the flank being looked at, or the two
                # labels overprint and neither is readable.
                if r["side"] != ("+" if mp["kind"] == "side_plus" else "-"):
                    continue
                cen[ti] = 0.0
            elif mp["kind"] == "top":
                cen[ui] = 0.0
            cross(cen, (255, 255, 255))
            x, y = X(cen)
            # In an END view both wheels of a flank project to the same pixel,
            # so the labels must be split by axle or they overprint.
            dy = -30 if c.startswith("F") else 12
            d.text((x + 16, y + dy), c, font=FB, fill=(255, 255, 255))

        # --- per-view measured callouts
        txt = [name]
        if mp["kind"] in ("end_near_nose", "end_near_tail"):
            pre = "F" if (mp["kind"] == "end_near_nose") == (vj["nose"] < 0) \
                else "R"
            pre = "F" if mp["kind"] == "end_near_nose" else "R"
            ax = m.get("axles", {}).get(pre, {})
            txt.append(f"axle {pre}: track {ax.get('track_m', float('nan')):.4f} m")
            txt.append(f"hub lateral asym {1000*ax.get('hub_lat_asym_m', 0):.1f} mm"
                       f"   vertical asym {1000*ax.get('hub_up_asym_m', 0):.1f} mm")
            for c in sorted(rows):
                if not c.startswith(pre):
                    continue
                r = rows[c]
                fv = r.get("sidewall_vs_fender_m")
                txt.append(
                    f"{c}: R {r['radius_m']:.4f}  W {r['width_m']:.4f}  "
                    f"bottom {1000*r['bottom_m']:+.1f} mm  "
                    f"camber {r['camber_deg']:+.3f}d  "
                    f"sidewall-fender {1000*fv:+.1f} mm"
                    if fv is not None and np.isfinite(fv) else
                    f"{c}: R {r['radius_m']:.4f}  W {r['width_m']:.4f}  "
                    f"bottom {1000*r['bottom_m']:+.1f} mm")
                # sidewall and fender verticals
                if fv is not None and np.isfinite(fv):
                    s = 1 if r["hub_lat"] > 0 else -1
                    for val, col in ((r["outer_sidewall_lat"], (80, 255, 140)),
                                     (r["fender_lip_lat"], (255, 140, 60))):
                        line([0, r["hub_up"] - 0.30, s * val],
                             [0, r["hub_up"] + 0.42, s * val], col, 2)
        elif mp["kind"] in ("side_plus", "side_minus"):
            txt.append(f"wheelbase {m.get('wheelbase_m', float('nan')):.4f} m")
            side = "+" if mp["kind"] == "side_plus" else "-"
            for c, r in sorted(rows.items()):
                if r["side"] != side:
                    continue
                txt.append(f"{c}: R {r['radius_m']:.4f}  bottom "
                           f"{1000*r['bottom_m']:+.1f} mm  toe {r['toe_deg']:+.3f}d")
                # radius circle
                cen = [r["hub_length"], r["hub_up"], 0]
                pts = [X([cen[0] + r["radius_m"] * math.cos(t), cen[1] +
                          r["radius_m"] * math.sin(t), 0])
                       for t in np.linspace(0, 2 * math.pi, 97)]
                d.line(pts, fill=(60, 220, 255), width=2)
        elif mp["kind"] == "top":
            for pre in ("F", "R"):
                ax = m.get("axles", {}).get(pre, {})
                if ax:
                    txt.append(f"axle {pre}: track {ax['track_m']:.4f} m  "
                               f"long asym {1000*ax['hub_long_asym_m']:.1f} mm  "
                               f"total toe {ax['total_toe_deg']:+.3f} deg")

        pad = 10
        h = 8 + 26 * len(txt)
        d.rectangle([pad, pad, pad + 760, pad + h], fill=(12, 12, 14))
        for i, t in enumerate(txt):
            d.text((pad + 10, pad + 6 + 26 * i), t,
                   font=(FB if i == 0 else F), fill=(240, 240, 240))
        d.text((pad + 10, N - 34),
               "white cross = projected hub (must sit on the cyan sphere) | "
               "red = ground y=0 | yellow = centreline | grid 0.25 m",
               font=F, fill=(200, 200, 200))
        im.save(os.path.join(outd, name + "_ann.png"))

    print(json.dumps(dict(exposure_median_sRGB=exposure), indent=1))
    bad = {k: v for k, v in exposure.items() if not (110 <= v <= 150)}
    print("EXPOSURE OUT OF BAND:" if bad else "exposure OK (0.22 world -> "
          "sRGB ~130 in every frame)", bad if bad else "")


# ========================================================= WHEELS-ONLY (CPython)
def wheels_glb(car, metro, out):
    """Export ONLY the geometry the metrology's cylinders own, as one GLB.

    Uses `wheel_ground_op.isolate`, i.e. the SAME containment test the repair
    operator uses to decide what it may move — so this render is a picture of
    exactly what was (or would be) transformed, not a lookalike.
    """
    import numpy as np
    import trimesh
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import wheel_ground_op as OP

    m = json.load(open(metro))
    sc = trimesh.load(car, force="scene")
    meshes = {}
    for node in sc.graph.nodes_geometry:
        T, gname = sc.graph[node]
        g = sc.geometry[gname]
        V = np.asarray(g.vertices, float)
        if not np.allclose(T, np.eye(4)):
            V = V @ np.asarray(T)[:3, :3].T + np.asarray(T)[:3, 3]
        meshes[node] = (V, np.asarray(g.faces))
    cfg = dict(OP.DEFAULTS)
    out_sc = trimesh.Scene()
    tally = {}
    for r in m["wheels"]:
        w = dict(centre=r["centre"], axis=r["axis"], radius_m=r["radius_m"],
                 width_m=r["width_m"])
        picked, _ = OP.isolate(meshes, w, cfg)
        n = 0
        for name, keep in picked.items():
            V, F = meshes[name]
            sub = trimesh.Trimesh(vertices=V, faces=F[keep], process=True)
            out_sc.add_geometry(sub, node_name=f"{r['corner']}__{name}")
            n += int(keep.sum())
        tally[r["corner"]] = n
    out_sc.export(out)
    print(json.dumps(dict(output=out, faces_per_corner=tally), indent=1))


# ------------------------------------------------------------------------ CLI
def main():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = argv[1:]
    mode = argv[0]
    if mode == "render":
        render(argv[1], argv[2], argv[3])
    elif mode == "annotate":
        annotate(argv[1], argv[2])
    elif mode == "wheels-glb":
        wheels_glb(argv[1], argv[2], argv[3])
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
