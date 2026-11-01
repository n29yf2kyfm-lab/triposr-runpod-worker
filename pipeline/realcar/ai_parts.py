#!/usr/bin/env python3
"""ai_parts.py: a car an image-to-3D generator made as one fused shell (Tripo, Hunyuan3D, Meshy: the windows
painted on, nothing separate) cut into the parts the machine rigs: four wheels, the doors, bonnet and tailgate,
and the glass as its own see-through material, so the doors open, the windows are clear and the cabin shows.

    node pipeline/realcar/slim.mjs RAW.glb IN.glb 0.15                  # first: a million vertices down to a phone's
    python3 pipeline/realcar/ai_parts.py IN.glb OUTLINES.json OUT.glb [TEXTURE_PX]
    python3 pipeline/realcar/glbmachine.py add OUT.glb --make ... --model ... --years ... --doors 5 --licence ...

OUTLINES (ai_parts/<car>.json) holds the car's panel and window outlines in metres, traced from the shut lines
and seals the generator printed into its texture (see the Golf Mk4's). The parts are named the way the rigger
reads them: door_front_left ..., bonnet, tailgate, wheel_*, window_* and windscreen (glazing: clear, and a door's
window travels with its door), tailgate_rear_window (the rear glass, on the tailgate)."""
import io
import json
import struct
import sys

import numpy as np
import trimesh

GLASS = {"name": "window_glass", "baseColorFactor": [0.30, 0.42, 0.38, 0.45], "alphaMode": "BLEND",
         "metallicFactor": 0.0, "roughnessFactor": 0.05, "doubleSided": True}


def inside(poly, a, b):
    """Which points (a, b) lie inside POLY [[a, b], ...] (even-odd rule)."""
    P = np.asarray(poly, float)
    hit = np.zeros(len(a), bool)
    for (a0, b0), (a1, b1) in zip(P, np.roll(P, -1, 0)):
        crosses = (b0 > b) != (b1 > b)
        at = a0 + (b - b0) * (a1 - a0) / ((b1 - b0) if b1 != b0 else 1e-12)
        hit ^= crosses & (a < at)
    return hit


# each outline: the plane it is drawn in (two of X, Y, Z in the car's metres) and the axis a face must look
# along to be cut by it (a face seen edge-on in that plane is not cut: its pieces could not be placed)
SPLIT = {"window_front": ("ZY", 0), "window_rear": ("ZY", 0), "window_rear_quarter": ("ZY", 0),
         "door_front": ("ZY", 0), "door_rear": ("ZY", 0), "rear_window": ("XY", 2), "tailgate": ("XY", 2),
         "bonnet": ("ZX", 1), "bonnet_front": ("XY", 2, lambda Q: Q[:, 2] > 1.6)}


# the panels a mechanic unbolts (lamps, grille, bumpers, front wings): outline, plane, axis, which faces, and
# whether the outline is one side's ([|X|, Y]) and stands for both
PANEL_SPLIT = {"lamp_front": ("XY", 2, lambda Q: Q[:, 2] > 1.7, True),
               "lamp_rear": ("XY", 2, lambda Q: Q[:, 2] < -1.7, True),
               "grille": ("XY", 2, lambda Q: Q[:, 2] > 1.75, False),
               "bumper_front": ("ZY", 0, lambda Q: Q[:, 2] > 1.5, False),
               "bumper_front_face": ("XY", 2, lambda Q: Q[:, 2] > 1.6, False),
               "bumper_rear": ("ZY", 0, lambda Q: Q[:, 2] < -1.5, False),
               "bumper_rear_face": ("XY", 2, lambda Q: Q[:, 2] < -1.6, False),
               "wing": ("ZY", 0, lambda Q: (np.abs(Q[:, 0]) > 0.5) & (Q[:, 2] > 0.6), False)}
PANELS = ("lamp_front_left", "lamp_front_right", "lamp_rear_left", "lamp_rear_right", "grille", "bumper_front",
          "bumper_rear", "wing_front_left", "wing_front_right")


def _split_jobs(o):
    for key, (plane, along, *where) in SPLIT.items():
        if key in o:
            yield o[key], plane, along, (where[0] if where else None)
    for key, (plane, along, where, both) in PANEL_SPLIT.items():
        if key in o:
            yield o[key], plane, along, where
            if both:
                yield [[-p[0], p[1]] for p in o[key]], plane, along, where


def _car_frame(P, s, f, lo):
    return np.column_stack([f * P[:, 0] / s, (P[:, 1] - lo[1]) / s, f * P[:, 2] / s])


def split_on_outlines(m, o, s, f, lo):
    """The faces an outline crosses, cut along it: each such triangle becomes the pieces inside and outside
    the outline (with their texture places and normals), so a door, the bonnet or a window comes away on its
    shut line instead of along the triangles' saw-teeth. Returns a new mesh and how many faces were cut."""
    import shapely
    from shapely.geometry import Polygon
    V = np.array(m.vertices, np.float64)
    F = np.array(m.faces)                       # a copy: the cut faces are struck out of it, not out of M
    UV = np.array(m.visual.uv, np.float64)
    VN = np.asarray(m.vertex_normals, np.float64)
    ncut = 0
    for pts, plane, along, where in _split_jobs(o):
        poly = Polygon(pts)
        if not poly.is_valid:
            poly = poly.buffer(0)
        a, b = "XYZ".index(plane[0]), "XYZ".index(plane[1])
        Q = _car_frame(V, s, f, lo)
        ins = inside(pts, Q[:, a], Q[:, b])
        k = ins[F].sum(1)
        T = Q[F]
        n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        # and the faces an outline's corner pokes into with all three of their own corners outside it
        t2all = T[:, :, [a, b]]
        e0, e1 = t2all[:, 1] - t2all[:, 0], t2all[:, 2] - t2all[:, 0]
        det = e0[:, 0] * e1[:, 1] - e0[:, 1] * e1[:, 0]
        corner = np.zeros(len(F), bool)
        for pc in np.asarray(pts, float):
            d = pc - t2all[:, 0]
            with np.errstate(divide="ignore", invalid="ignore"):
                u = (d[:, 0] * e1[:, 1] - d[:, 1] * e1[:, 0]) / det
                w = (e0[:, 0] * d[:, 1] - e0[:, 1] * d[:, 0]) / det
            corner |= (u > 0) & (w > 0) & (u + w < 1)
        ok = (((k > 0) & (k < 3)) | corner) & (np.abs(n[:, along]) > 0.3)
        if where is not None:
            ok &= where(T.mean(1))
        todo = np.where(ok)[0]
        if not len(todo):
            continue
        newV, newUV, newN, newF = [V], [UV], [VN], []
        nv = len(V)
        for fi in todo:
            t2 = T[fi][:, [a, b]]
            A = np.array([[t2[0, 0] - t2[2, 0], t2[1, 0] - t2[2, 0]], [t2[0, 1] - t2[2, 1], t2[1, 1] - t2[2, 1]]])
            if abs(np.linalg.det(A)) < 1e-14:
                continue
            Ai = np.linalg.inv(A)
            tri = Polygon(t2)
            sign = np.sign(np.linalg.det(A))
            vid = F[fi]
            pieces = []
            for g in (tri.intersection(poly), tri.difference(poly)):
                if g.is_empty:
                    continue
                for t in shapely.get_parts(shapely.constrained_delaunay_triangles(g)):
                    c = np.asarray(t.exterior.coords)[:3]
                    if abs(Polygon(c).area) < 1e-12:
                        continue
                    pieces.append(c)
            if len(pieces) < 2:
                continue
            for c in pieces:
                l01 = (c - t2[2]) @ Ai.T                            # barycentric weights of the piece's corners
                w = np.column_stack([l01, 1 - l01.sum(1)])
                P3, U3, N3 = w @ V[vid], w @ UV[vid], w @ VN[vid]
                d = (c[1, 0] - c[0, 0]) * (c[2, 1] - c[0, 1]) - (c[1, 1] - c[0, 1]) * (c[2, 0] - c[0, 0])
                order = [0, 1, 2] if np.sign(d) == sign else [0, 2, 1]
                newV.append(P3[order]), newUV.append(U3[order]), newN.append(N3[order])
                newF.append([nv, nv + 1, nv + 2])
                nv += 3
            F[fi] = -1
            ncut += 1
        V = np.vstack(newV)
        UV = np.vstack(newUV)
        VN = np.vstack(newN)
        F = np.vstack([F[F[:, 0] >= 0]] + ([np.array(newF)] if newF else []))
    out = trimesh.Trimesh(vertices=V, faces=F, vertex_normals=VN, process=False,
                          visual=trimesh.visual.TextureVisuals(uv=UV, material=m.visual.material))
    return out, ncut


# glTF colours are linear: anthracite trim plastic (sRGB ~ 46,47,51), mid-grey cloth (~ 78,79,84), satin chrome
CARD = {"plastic": ([0.027, 0.028, 0.032, 1.0], 0.0, 0.6), "fabric": ([0.075, 0.078, 0.087, 1.0], 0.0, 0.95),
        "handle": ([0.55, 0.56, 0.57, 1.0], 0.9, 0.28)}


def _box(c, half):
    """A box's twelve triangles round centre C with half-sizes HALF (car frame)."""
    b = trimesh.creation.box(extents=2 * np.asarray(half, float))
    return b.vertices + c, b.faces


def door_cards(Q, Nq, labels, o, step=0.04):
    """A trim card on the inside of each door (the generator moulds only the outer skin, so an open door was a
    hollow shell): the door's outline less its window, held a door's depth in from the skin it follows, a
    fabric insert, an armrest with a pull cup, the release handle and a speaker grille, and a strip round the
    card's edge back to the skin. Car frame (metres, X left +, Y up, Z nose +). Returns {door: {material:
    (vertices, faces)}}."""
    import shapely
    from scipy.spatial import cKDTree
    from shapely.geometry import Polygon, box
    out = {}
    for door in sorted({str(x) for x in labels if str(x).startswith("door_")}):
        _, end, side = door.split("_")
        sg = 1.0 if side == "left" else -1.0
        ix = np.where((labels == door) & (np.abs(Nq[:, 0]) > 0.4) & (np.sign(Nq[:, 0]) == sg))[0]
        if len(ix) < 50:
            continue
        skin = cKDTree(Q[ix][:, [2, 1]])
        sx = np.abs(Q[ix, 0])

        def skin_x(zy):
            d, k = skin.query(zy, k=8)
            w = 1 / np.maximum(d, 1e-3)
            return (sx[k] * w).sum(1) / w.sum(1)
        outline = Polygon(o[f"door_{end}"])
        wins = [Polygon(o[k]) for k in (("window_front",) if end == "front" else ("window_rear", "window_rear_quarter")) if k in o]
        belt = min(np.asarray(w.exterior.coords)[:, 1].min() for w in wins) if wins else 0.95
        card = outline.buffer(-0.015)
        for w in wins:
            card = card.difference(w.buffer(0.012))
        z0, y0, z1, y1 = card.bounds

        def depth(zy):                                  # deep below the window line, a slim frame round the glass
            t = np.clip((zy[:, 1] - (belt - 0.03)) / 0.05, 0, 1)
            return 0.085 * (1 - t) + 0.035 * t

        def place(zy, extra=0.0):
            x = skin_x(zy) - depth(zy) - extra
            return np.column_stack([sg * x, zy[:, 1], zy[:, 0]])

        def sheet(poly, extra=0.0):
            V, F = [], []
            gz = np.arange(z0, z1 + step, step)
            gy = np.arange(y0, y1 + step, step)
            for za in gz:
                for ya in gy:
                    piece = poly.intersection(box(za, ya, za + step, ya + step))
                    if piece.is_empty or piece.area < 1e-7:
                        continue
                    for t in shapely.get_parts(shapely.constrained_delaunay_triangles(piece)):
                        c = np.asarray(t.exterior.coords)[:3]
                        V.append(place(c, extra))
                        F.append(np.arange(3) + 3 * (len(F)))
            if not V:
                return np.zeros((0, 3)), np.zeros((0, 3), int)
            return np.vstack(V), np.vstack(F)

        parts = {"plastic": [], "fabric": [], "handle": []}
        parts["plastic"].append(sheet(card))
        # the edge: a strip from the skin to the card all the way round, and round the window opening
        polys = [g for g in shapely.get_parts(card) if g.geom_type == "Polygon" and g.area > 1e-4]
        for ring in [r for g in polys for r in [g.exterior, *g.interiors]]:
            ring = ring.segmentize(0.03)
            zy = np.asarray(ring.coords)
            xs, xc = skin_x(zy), skin_x(zy) - depth(zy)
            a = np.column_stack([sg * xs, zy[:, 1], zy[:, 0]])
            b = np.column_stack([sg * xc, zy[:, 1], zy[:, 0]])
            n = len(zy) - 1
            V = np.vstack([a, b])
            F = np.vstack([[i, i + 1, n + 1 + i] for i in range(n)] + [[i + 1, n + 2 + i, n + 1 + i] for i in range(n)])
            parts["plastic"].append((V, F))
        # the fabric insert: a band across the card's middle, 6 mm proud of it
        band = card.intersection(box(z0 + 0.07, 0.56, z1 - 0.07, min(0.84, belt - 0.1)))
        if not band.is_empty:
            parts["fabric"].append(sheet(band, 0.006))
        # armrest along the door at elbow height, with the pull cup; the release handle up at the front;
        # a speaker grille low at the front
        zf_, zr_ = (z1 - 0.12, z0 + 0.10) if end == "front" else (z1 - 0.08, z0 + 0.32)
        zf_, zr_ = (zf_, max(zr_, zf_ - 0.55))
        zm = (zf_ + zr_) / 2
        x_at = lambda z, y: skin_x(np.array([[z, y]]))[0] - depth(np.array([[z, y]]))[0]   # noqa: E731
        xa = x_at(zm, 0.72)
        parts["plastic"].append(_box(np.array([sg * (xa - 0.045), 0.72, zm]), [0.045, 0.028, (zf_ - zr_) / 2]))
        parts["plastic"].append(_box(np.array([sg * (xa - 0.05), 0.79, zm + 0.05]), [0.03, 0.04, 0.07]))
        zh = z1 - 0.10
        xh = x_at(zh, min(0.88, belt - 0.07))
        parts["handle"].append(_box(np.array([sg * (xh - 0.012), min(0.88, belt - 0.07), zh]), [0.012, 0.016, 0.06]))
        zs = z1 - 0.16 if end == "front" else z1 - 0.14
        if card.contains(shapely.Point(zs, 0.42)):
            xs_ = x_at(zs, 0.42)
            cyl = trimesh.creation.cylinder(radius=0.075, height=0.012, sections=28)
            cyl.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
            parts["plastic"].append((cyl.vertices + [sg * (xs_ - 0.008), 0.42, zs], cyl.faces))
        res = {}
        for mat, lst in parts.items():
            lst = [t for t in lst if len(t[1])]
            if not lst:
                continue
            V, F, off = [], [], 0
            for v_, f_ in lst:
                V.append(v_), F.append(np.asarray(f_) + off)
                off += len(v_)
            res[mat] = (np.vstack(V), np.vstack(F))
        out[door] = res
    return out


def cut(src, outlines, dst):
    o = json.load(open(outlines))
    m = trimesh.load(src, force="mesh", process=False)
    V, F = np.asarray(m.vertices), np.asarray(m.faces)
    lo, hi = V.min(0), V.max(0)
    ax = int(np.argmax(hi - lo))
    if ax != 2:
        raise SystemExit("the car's length must lie along the file's Z (turn it first)")
    s = (hi[2] - lo[2]) / o["length"]
    # the rear: where the red of the tail lights is (texture at each face's centre)
    tex = np.asarray(m.visual.material.baseColorTexture.convert("RGB"), np.float32) / 255
    H, W = tex.shape[:2]

    def colours(F, uvs):
        uv = uvs[F].mean(1)
        return tex[np.clip(((1 - uv[:, 1] % 1) * (H - 1)).astype(int), 0, H - 1), np.clip((uv[:, 0] % 1 * (W - 1)).astype(int), 0, W - 1)]
    col = colours(F, np.asarray(m.visual.uv))
    C = V[F].mean(1)
    red = (col[:, 0] > 0.45) & (col[:, 1] < 0.25) & (col[:, 2] < 0.25)
    f = -1.0 if C[red, 2].mean() > (lo[2] + hi[2]) / 2 else 1.0        # nose to +Z (a half turn keeps it right-handed)
    m, n_split = split_on_outlines(m, o, s, f, lo)
    V, F = np.asarray(m.vertices), np.asarray(m.faces)
    col = colours(F, np.asarray(m.visual.uv))
    v = col.max(1)
    C = V[F].mean(1)
    X, Y, Z = f * C[:, 0] / s, (C[:, 1] - lo[1]) / s, f * C[:, 2] / s
    N = np.asarray(m.face_normals) * [f, 1, f]
    label = np.array(["body"] * len(F), dtype=object)
    free = lambda: label == "body"                                      # noqa: E731

    # wheels: a tyre-sized cylinder round each axle, outboard of the track's inner face
    r = o["tyre_radius"]
    low = Y < 0.12 * r
    axles = [Z[low & (Z > 0)].mean(), Z[low & (Z < 0)].mean()]
    tri = V[F]
    for zc, end in zip(axles, ("front", "rear")):
        for sgn, side in ((1, "left"), (-1, "right")):
            d = np.hypot((tri[:, :, 1] - lo[1]) / s - r, f * tri[:, :, 2] / s - zc)
            sel = (d < r * 1.04).all(1) & ((f * tri[:, :, 0] / s * sgn) > o["track"] / 2 - o["tyre_width"] / 2 - 0.035).all(1)
            label[sel & free()] = f"wheel_{end}_{side}"
    side_of = np.where(X > 0, "left", "right")
    outward = np.sign(N[:, 0]) == np.sign(X)
    # glass first, so it is taken out of the panels round it
    for key, nm in (("window_front", "window_front"), ("window_rear", "window_rear"), ("window_rear_quarter", "window_quarter")):
        sel = free() & (np.abs(X) > 0.45) & (np.abs(N[:, 0]) > 0.35) & outward & inside(o[key], Z, Y)
        label[sel] = [f"{nm}_{sd}" for sd in side_of[sel]]
    ws = o["windscreen"]
    sel = free() & (N[:, 2] > 0.25) & (N[:, 1] > 0.2) & (np.abs(X) < ws["half_width"]) & (Y > ws["y"][0]) & (Y < ws["y"][1]) \
        & (Z > ws["z"][0]) & (Z < ws["z"][1]) & (v > 0.14)
    label[sel] = "windscreen"
    sel = free() & (N[:, 2] < -0.3) & (Z < -1.4) & inside(o["rear_window"], X, Y) & ~((v < 0.15) & (Y < 1.12))
    label[sel] = "tailgate_rear_window"
    # glass the outlines just missed (the windscreen's edges where it wraps into the A-pillars, a window's
    # corners): the glass-coloured faces next to it, by the tint the generator painted its glass
    tint = (col[:, 1] > col[:, 0] + 0.03) & (col[:, 1] >= col[:, 2]) & (v < 0.6)
    sel = free() & tint & (N[:, 2] > 0.05) & (np.abs(X) < ws["half_width"] + 0.1) & (Y > ws["y"][0]) & (Y < ws["y"][1]) \
        & (Z > ws["z"][0]) & (Z < ws["z"][1] + 0.05)
    label[sel] = "windscreen"
    for key, nm in (("door_front", "window_front"), ("door_rear", "window_rear")):
        sel = free() & tint & (np.abs(X) > 0.45) & (Y > 0.95) & inside(o[key], Z, Y)
        names = np.where((nm == "window_rear") & (Z[sel] < -0.998), "window_quarter", nm)
        label[sel] = [f"{n}_{sd}" for n, sd in zip(names, side_of[sel])]
    sel = free() & tint & (Z < -1.4) & (Y > 1.0) & inside(o["tailgate"], X, Y)
    label[sel] = "tailgate_rear_window"
    # the panels
    for key, nm in (("door_front", "door_front"), ("door_rear", "door_rear")):
        sel = free() & (np.abs(X) > 0.5) & inside(o[key], Z, Y)
        label[sel] = [f"{nm}_{sd}" for sd in side_of[sel]]
    # the bonnet: its top (facing up), and at the nose its lip curling down to the grille and the headlights,
    # down to the line where the silver meets their black (bonnet_front, seen from the front)
    lip = (Z > 1.7) & (N[:, 1] > -0.1) & inside(o["bonnet_front"], X, Y) if "bonnet_front" in o else np.zeros(len(Z), bool)
    sel = free() & ((N[:, 1] > 0.25) | lip) & (Y > o["bonnet_low"]) & inside(o["bonnet"], Z, X)
    label[sel] = "bonnet"
    sel = free() & (N[:, 2] < -0.15) & (Z < -1.5) & inside(o["tailgate"], X, Y)
    label[sel] = "tailgate"

    # the cabin the generator moulded from what the photo showed through the glass (lumps for seats) is left
    # out, so the machine fits its own cabin pack (it fits one only into an empty shell)
    # the panels a mechanic unbolts: the lamps and the grille first, then the bumpers, then the front wings
    ax_ = np.abs(X)
    if "lamp_front" in o:
        sel = free() & (Z > 1.7) & (N[:, 2] > -0.2) & inside(o["lamp_front"], ax_, Y)
        label[sel] = [f"lamp_front_{sd}" for sd in side_of[sel]]
    if "lamp_rear" in o:
        sel = free() & (Z < -1.7) & (N[:, 2] < 0.2) & inside(o["lamp_rear"], ax_, Y)
        label[sel] = [f"lamp_rear_{sd}" for sd in side_of[sel]]
    if "grille" in o:
        sel = free() & (Z > 1.75) & (N[:, 2] > -0.2) & inside(o["grille"], X, Y)
        label[sel] = "grille"
    for key in ("bumper_front", "bumper_rear"):
        if key in o:
            label[free() & inside(o[key], Z, Y)] = key
    if "wing" in o:
        sel = free() & (ax_ > 0.5) & inside(o["wing"], Z, Y)
        label[sel] = [f"wing_front_{sd}" for sd in side_of[sel]]

    cab = o.get("cabin")
    if cab:
        sel = free() & (np.abs(X) < cab["half_width"]) & (Z > cab["z"][0]) & (Z < cab["z"][1]) & (Y > cab["y"][0]) & (Y < cab["y"][1])
        label[sel] = "_drop"
    label_kept = label != "_drop"
    dropped = int((~label_kept).sum())
    scene = trimesh.Scene()
    counts = {}
    glass = None
    for nm in sorted(set(label) - {"_drop"}):
        ix = np.where(label == nm)[0]
        counts[nm] = int(len(ix))
        sub = m.submesh([ix], append=True, repair=False)
        if nm.startswith("window") or nm in ("windscreen", "tailgate_rear_window"):
            if glass is None:
                glass = trimesh.visual.material.PBRMaterial(**GLASS)
            sub.visual = trimesh.visual.TextureVisuals(uv=sub.visual.uv, material=glass)
        elif nm in PANELS:
            # its own material (the same texture): the rigger and the finisher keep a material whatever part it
            # is filed under, so the page finds the panel by it and takes it off on its own
            pm = sub.visual.material.copy()
            pm.name = "panel_" + nm
            sub.visual = trimesh.visual.TextureVisuals(uv=sub.visual.uv, material=pm)
        scene.add_geometry(sub, node_name=nm, geom_name=nm)
    # a trim card inside each door, as a child of the door's node: the rigger reads the door's name up the chain,
    # so the card opens with its door (the names say nothing a rule would read as a wheel, lamp or cabin)
    Qv = np.column_stack([X, Y, Z])
    cards = door_cards(Qv, N, label, o) if o.get("door_cards", True) else {}
    ab = {"front_left": "fl", "front_right": "fr", "rear_left": "rl", "rear_right": "rr"}
    mats = {}
    for door, res in cards.items():
        k = ab[door[5:]]
        for mat, (Vc, Fc) in res.items():
            if mat not in mats:
                c, met, rough = CARD[mat]
                mats[mat] = trimesh.visual.material.PBRMaterial(name=f"door_card_{mat}", baseColorFactor=c, metallicFactor=met,
                                                                roughnessFactor=rough, doubleSided=True)
            P = np.column_stack([f * Vc[:, 0] * s, Vc[:, 1] * s + lo[1], f * Vc[:, 2] * s])   # back to the file's frame
            g = trimesh.Trimesh(vertices=P, faces=Fc, process=False,
                                visual=trimesh.visual.TextureVisuals(uv=np.zeros((len(P), 2)), material=mats[mat]))
            nm = {"plastic": "card", "fabric": "cardcloth", "handle": "cardpull"}[mat] + "_" + k
            scene.add_geometry(g, node_name=nm, geom_name=nm, parent_node_name=door)
            counts[nm] = int(len(Fc))
    scene.export(dst, include_normals=True)              # the file's own normals: without them the paint renders as streaky chrome
    return {"scale_per_m": round(float(s), 4), "nose": "+Z" if f > 0 else "-Z (turned)", "faces_cut_on_outlines": n_split,
            "wheelbase_m": round(float(axles[0] - axles[1]), 3), "parts": counts, "cabin_left_out": dropped, "wrote": dst}


def shrink_images(path, px=2048, quality=88):
    """Every texture in the GLB at PATH down to PX on its longest side and stored as JPEG (a generator's three
    4K maps are most of the file); the GLB is written back in place."""
    from PIL import Image
    b = open(path, "rb").read()
    jl = struct.unpack("<I", b[12:16])[0]
    j = json.loads(b[20:20 + jl])
    bin0 = 20 + jl + 8
    blob = b[bin0:bin0 + struct.unpack("<I", b[20 + jl:24 + jl])[0]]
    views = j["bufferViews"]
    # only a colour map may go to JPEG: its colour-subsampling would smear a metal/roughness map's separate
    # channels (the paint turned to chrome) and a normal map's directions; those stay PNG, only smaller
    colour = {j["textures"][m["pbrMetallicRoughness"]["baseColorTexture"]["index"]].get("source")
              for m in j.get("materials", []) if "baseColorTexture" in m.get("pbrMetallicRoughness", {})}
    # a generator's metal/roughness map reads its car as polished metal (roughness 0.25, metal 0.5): the
    # silver came out chrome. Paint is rougher and less metallic: G (roughness) raised, B (metal) lowered
    shine = {j["textures"][m["pbrMetallicRoughness"]["metallicRoughnessTexture"]["index"]].get("source")
             for m in j.get("materials", []) if "metallicRoughnessTexture" in m.get("pbrMetallicRoughness", {})}
    repl = {}
    for ii, im in enumerate(j.get("images", [])):
        if "bufferView" not in im:
            continue
        bv = views[im["bufferView"]]
        raw = blob[bv.get("byteOffset", 0):bv.get("byteOffset", 0) + bv["byteLength"]]
        img = Image.open(io.BytesIO(raw))
        img.load()
        img.thumbnail((px, px), Image.LANCZOS)
        if ii in shine:
            import numpy as np_
            a_ = np_.asarray(img.convert("RGB"), np_.float32) / 255
            a_[..., 1] = np_.clip(a_[..., 1] * 0.8 + 0.25, 0, 1)
            a_[..., 2] = a_[..., 2] * 0.65
            img = Image.fromarray((a_ * 255 + 0.5).astype("uint8"))
        out = io.BytesIO()
        if ii in colour:
            img.convert("RGB").save(out, "JPEG", quality=quality)
            im["mimeType"] = "image/jpeg"
        else:
            img.save(out, "PNG", optimize=True)
            im["mimeType"] = "image/png"
        repl[im["bufferView"]] = out.getvalue()
    # one copy of each picture: a panel's material copies the body's, and the exporter wrote the same maps once
    # per material (thirty images for three)
    first, img_map = {}, {}
    for ii, im in enumerate(j.get("images", [])):
        if "bufferView" not in im:
            continue
        data = repl.get(im["bufferView"])
        if data is None:
            bv = views[im["bufferView"]]
            data = blob[bv.get("byteOffset", 0):bv.get("byteOffset", 0) + bv["byteLength"]]
        img_map[ii] = first.setdefault(hash(data), ii)
    keep_img = sorted(set(img_map.values()) | {ii for ii, im in enumerate(j.get("images", [])) if "bufferView" not in im})
    new_img = {ii: k for k, ii in enumerate(keep_img)}
    for t in j.get("textures", []):
        if "source" in t:
            t["source"] = new_img[img_map.get(t["source"], t["source"])]
    dropped_views = {j["images"][ii]["bufferView"] for ii in img_map if ii not in new_img} \
        - {j["images"][ii]["bufferView"] for ii in keep_img if "bufferView" in j["images"][ii]}
    j["images"] = [j["images"][ii] for ii in keep_img]
    keep_view = [i for i in range(len(views)) if i not in dropped_views]
    new_view = {i: k for k, i in enumerate(keep_view)}
    for acc in j.get("accessors", []):
        if "bufferView" in acc:
            acc["bufferView"] = new_view[acc["bufferView"]]
    for im in j["images"]:
        if "bufferView" in im:
            im["bufferView"] = new_view[im["bufferView"]]
    repl = {new_view[i]: d for i, d in repl.items() if i in new_view}
    old_views = views
    views = j["bufferViews"] = [old_views[i] for i in keep_view]
    old_off = {k: (old_views[i].get("byteOffset", 0), old_views[i]["byteLength"]) for k, i in enumerate(keep_view)}
    new = bytearray()
    for i, bv in enumerate(views):
        o0, n0 = old_off[i]
        data = repl.get(i) or blob[o0:o0 + n0]
        while len(new) % 4:
            new += b"\0"
        bv["byteOffset"], bv["byteLength"] = len(new), len(data)
        new += data
    while len(new) % 4:
        new += b"\0"
    j["buffers"][0]["byteLength"] = len(new)
    js = json.dumps(j, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(new)
    with open(path, "wb") as fh:
        fh.write(struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<I", len(js)) + b"JSON" + js
                 + struct.pack("<I", len(new)) + b"BIN\0" + new)


if __name__ == "__main__":
    if len(sys.argv) not in (4, 5):
        raise SystemExit(__doc__)
    rep = cut(*sys.argv[1:4])
    if len(sys.argv) == 5:
        shrink_images(sys.argv[3], int(sys.argv[4]))
        rep["textures_px"] = int(sys.argv[4])
    print(json.dumps(rep, indent=1))
