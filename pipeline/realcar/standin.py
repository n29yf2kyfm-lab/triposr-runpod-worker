#!/usr/bin/env python3
"""standin.py — a car the catalogue does not have, made from one it does.

    python3 pipeline/realcar/standin.py DONOR_RIG.glb TARGET.json OUT.glb

The donor is the rigger's own output (rig/src.glb: SB_ parts, metres, y up,
nose +z, the car's left +x, ground at 0), so it already has separate doors,
bonnet and tailgate, glass and a cabin. TARGET holds the real car's
published figures in mm: {"length", "wheelbase", "width", "height"} (and a
"name"). The donor is reshaped to them one axis at a time, so the warp's
Jacobian is diagonal and normals and tangents stay exact:

  along (z)  a smooth monotone map through the tail, both axles and the
             nose: the target's wheelbase between the axles, its overhangs in
             the donor's proportion, each arch (axle +/- 1.15 wheel radius)
             at the wheel's own scale so it stays round about the new wheel;
  up (y)     below the arch tops the wheel's scale; above, stretched so the
             roof meets the target's height;
  across (x) the body to the target's width.

Wheels (SB_wheel_*) move whole to the new axles and track and grow or shrink
evenly with the new wheel size, never squashed. The finisher (finish.py)
then hangs the doors on their new hinge lines, fits the engine bay and
exhaust, clears the glass and paints the car, as for any other car.

It must not claim to be its donor either: debadge() makes the number plates
plain and paints the donor's badges and lettering over in the body colour,
pressed flat onto their panels.

What it is not: the target's own face. Lamps and grille keep the donor's
shape; the report and the file's credit call the car a stand-in.
"""
import json
import os
import re
import sys

import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.ndimage import median_filter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "template"))
from gltf import GLTF  # noqa: E402

VERSION = "1.9"                     # a change here reshapes stand-ins built before
WHEEL = re.compile(r"^SB_wheel_(fl|fr|rl|rr)")


def _parts(g):
    """(node index, name, world matrix) for every mesh node, each with a mesh
    of its own: a mesh two nodes share is copied, since each is warped where
    it stands."""
    W, _ = g.world_matrices()
    used, out = set(), []
    for i, n in enumerate(g.j["nodes"]):
        if "mesh" not in n:
            continue
        if n["mesh"] in used:
            g.j["meshes"].append(json.loads(json.dumps(g.j["meshes"][n["mesh"]])))
            n["mesh"] = len(g.j["meshes"]) - 1
        used.add(n["mesh"])
        out.append((i, n.get("name") or "", W[i]))
    return out


def _world(g, mesh, M):
    return [(g.accessor(p["attributes"]["POSITION"]) @ M[:3, :3].T + M[:3, 3]) for p in mesh["primitives"]]


def measure(g, parts):
    """The donor's wheel centres, wheel radius, wheelbase, track, overall
    length, body width (below the mirrors) and height."""
    wheels, body, every = {}, [], []
    for i, name, M in parts:
        vs = _world(g, g.j["meshes"][g.j["nodes"][i]["mesh"]], M)
        v = np.vstack(vs) if vs else np.zeros((0, 3))
        if not len(v):
            continue
        every.append(v)
        m = WHEEL.match(name)
        if m:
            wheels.setdefault(m.group(1), []).append(v)
        elif name.startswith(("SB_body", "SB_door", "SB_panel", "SB_tailgate")):
            body.append(v)
    if set(wheels) != {"fl", "fr", "rl", "rr"}:
        raise ValueError(f"the donor needs four wheels; it has {sorted(wheels)}")
    allv, body = np.vstack(every), np.vstack(body)
    c = {}
    for k, vs in wheels.items():
        v = np.vstack(vs)
        lo, hi = v.min(0), v.max(0)
        c[k] = {"centre": (lo + hi) / 2, "R": (hi[1] - lo[1]) / 2}
    R = float(np.mean([w["R"] for w in c.values()]))
    zf = float((c["fl"]["centre"][2] + c["fr"]["centre"][2]) / 2)
    zr = float((c["rl"]["centre"][2] + c["rr"]["centre"][2]) / 2)
    # the roof: along the car, the top of the body near the centre line, with
    # a spike a few bins long (an aerial, a fin) smoothed away
    zc = body[:, 2]
    mid = body[np.abs(body[:, 0]) < 0.3 * (body[:, 0].max() - body[:, 0].min())]
    bins = np.arange(zc.min(), zc.max() + 0.05, 0.05)
    idx = np.clip(np.digitize(mid[:, 2], bins) - 1, 0, len(bins) - 1)
    top = np.full(len(bins), np.nan)
    for k in np.unique(idx):
        top[k] = np.percentile(mid[idx == k, 1], 98)
    top = top[np.isfinite(top)]
    H = float(np.max(median_filter(top, size=9))) if len(top) >= 9 else float(np.percentile(body[:, 1], 99.5))
    low = body[body[:, 1] < 0.55 * H]                       # below the mirrors
    W = float(2 * np.percentile(np.abs(low[:, 0]), 99.7))
    return {"wheels": c, "R": R, "zf": zf, "zr": zr, "wheelbase": zf - zr,
            "zmin": float(allv[:, 2].min()), "zmax": float(allv[:, 2].max()),
            "length": float(allv[:, 2].max() - allv[:, 2].min()), "width": W, "height": H,
            "track": float(np.mean([abs(c["fl"]["centre"][0] - c["fr"]["centre"][0]),
                                    abs(c["rl"]["centre"][0] - c["rr"]["centre"][0])]))}


def plan(d, t):
    """The three axis maps from the donor's measures D to the target T (mm)."""
    L, WB, Wd, H = (t[k] / 1000.0 for k in ("length", "wheelbase", "width", "height"))
    # the new wheel: the donor's, in proportion to the target's size (the
    # donor's own scale may be a guess, so only ratios are used), kept to a
    # road car's 0.55-0.82 m
    d_wheel = 2 * d["R"]
    k_size = ((WB / d["wheelbase"]) * (H / d["height"])) ** 0.5
    w_new = float(np.clip(d_wheel * k_size, 0.55, 0.82))
    s = w_new / d_wheel
    # along: overhangs in the donor's proportion
    of, orr = d["zmax"] - d["zf"], d["zr"] - d["zmin"]
    O = max(L - WB, 0.2)
    of_t, or_t = O * of / (of + orr), O * orr / (of + orr)
    mid = (d["zf"] + d["zr"]) / 2
    zf_t, zr_t = mid + WB / 2, mid - WB / 2
    a, a_t = 1.15 * d["R"], 1.15 * d["R"] * s
    a = min(a, 0.45 * min(of, orr, d["wheelbase"] / 2))
    a_t = min(a_t, 0.45 * min(of_t, or_t, WB / 2))
    zs = [d["zmin"], d["zr"] - a, d["zr"] + a, d["zf"] - a, d["zf"] + a, d["zmax"]]
    zt = [zr_t - or_t, zr_t - a_t, zr_t + a_t, zf_t - a_t, zf_t + a_t, zf_t + of_t]
    # up: the wheel's scale to the arch tops, then the roof to the height
    ya = 2.1 * d["R"]
    ys, yt = [0.0, ya, d["height"]], [0.0, ya * s, H]
    if yt[2] <= yt[1] + 0.2:                                  # a car lower than its arches cannot be
        yt[2] = yt[1] + 0.2
    sx = Wd / d["width"]
    return {"z": PchipInterpolator(zs, zt, extrapolate=True), "y": PchipInterpolator(ys, yt, extrapolate=True),
            "sx": sx, "s": s, "zf_t": zf_t, "zr_t": zr_t, "track_t": d["track"] * sx,
            "log": {"wheel_d_m": [round(d_wheel, 3), round(w_new, 3)], "s_wheel": round(s, 4), "sx": round(sx, 4),
                    "along": [round(zt[-1] - zt[0], 3), round(d["length"], 3)],
                    "wheelbase_m": [round(d["wheelbase"], 3), round(WB, 3)],
                    "overhangs_m": {"front": [round(of, 3), round(of_t, 3)], "rear": [round(orr, 3), round(or_t, 3)]},
                    "height_m": [round(d["height"], 3), round(H, 3)], "width_m": [round(d["width"], 3), round(Wd, 3)]}}


def _top(v, half_width, z0, z1, step=0.05):
    """The top of the car along z (bins of STEP), near the centre line, a
    spike a few bins long (an aerial) smoothed away: (z centres, heights)."""
    mid = v[np.abs(v[:, 0]) < half_width]
    bins = np.arange(z0, z1 + step, step)
    idx = np.clip(np.digitize(mid[:, 2], bins) - 1, 0, len(bins) - 1)
    top = np.full(len(bins), np.nan)
    for k in np.unique(idx):
        top[k] = np.percentile(mid[idx == k, 1], 98)
    ok = np.isfinite(top)
    top = np.interp(np.arange(len(bins)), np.where(ok)[0], top[ok])
    return bins + step / 2, median_filter(top, size=5)


def roof_stage(roof, p, d, body_v2):
    """The photo's roofline as a height factor along the car: (k(z), dk/dz,
    ya, log), or None. The photo's wheel centres are put on the new axles;
    its heights are scaled so its top is the published height (the figure
    gives the size, the photograph the shape)."""
    from scipy.ndimage import gaussian_filter1d
    u, r = np.asarray(roof["u"], float), np.asarray(roof["roof"], float)
    uf, ur = roof["u_front"], roof["u_rear"]
    L, WB = p["log"]["along"][0], p["log"]["wheelbase_m"][1]
    z0 = p["zr_t"] - p["log"]["overhangs_m"]["rear"][1]
    if 0.5 < uf < 0.95 and 0.05 < ur < 0.5 and abs((uf - ur) * L / WB - 1) < 0.08:
        zt = p["zr_t"] + (u - ur) / (uf - ur) * (p["zf_t"] - p["zr_t"])     # its wheels on the new axles
        align = "wheels"
    else:                                                  # wheels not found in the photo: its two ends
        zt = z0 + u * L
        align = "ends"
    H = p["log"]["height_m"][1]
    r = r * H / max(r.max(), 1e-6)
    ya = 2.1 * d["R"] * p["s"]
    zc, top = _top(body_v2, 0.3 * p["log"]["width_m"][1], body_v2[:, 2].min(), body_v2[:, 2].max())
    rt = np.interp(zc, zt, r, left=np.nan, right=np.nan)
    ok = np.isfinite(rt) & (top > ya + 0.12) & (rt > ya + 0.12)
    if ok.sum() < 20:
        return None
    k = np.ones_like(zc)
    k[ok] = np.clip((rt[ok] - ya) / (top[ok] - ya), 0.8, 1.2)
    k = gaussian_filter1d(k, 2.4)                         # about 0.12 m
    ramp = np.clip(np.minimum(zc - zc[0], zc[-1] - zc) / 0.15, 0, 1)
    k = 1 + (k - 1) * ramp                                 # nothing moves at the bumpers' ends
    before = float(np.nanmean(np.abs(top[ok] - rt[ok])))
    fk = PchipInterpolator(zc, k, extrapolate=True)
    return fk, fk.derivative(), ya, {"stations": int(ok.sum()), "aligned_by": align, "k_range": [round(float(k.min()), 3), round(float(k.max()), 3)],
                                     "roofline_off_cm_before": round(100 * before, 1),
                                     "_check": (zc, rt, ok)}


def warp(src, target, dst):
    g = GLTF(src)
    parts = _parts(g)
    d = measure(g, parts)
    p = plan(d, target)
    fz, fy, sx = p["z"], p["y"], p["sx"]
    dfz, dfy = fz.derivative(), fy.derivative()
    new_c = {}
    for k, w in d["wheels"].items():
        c = w["centre"]
        new_c[k] = np.array([np.sign(c[0]) * p["track_t"] / 2, d["R"] * p["s"],
                             p["zf_t"] if k[0] == "f" else p["zr_t"]])
    # pass 1: the size, one axis at a time (Jacobian diagonal)
    work = []
    for i, name, M in parts:
        mesh = g.j["meshes"][g.j["nodes"][i]["mesh"]]
        m = WHEEL.match(name)
        for prim in mesh["primitives"]:
            v = g.accessor(prim["attributes"]["POSITION"]) @ M[:3, :3].T + M[:3, 3]
            if m:                                             # whole: moved and evenly scaled
                c0 = d["wheels"][m.group(1)]["centre"]
                v2 = new_c[m.group(1)] + p["s"] * (v - c0)
                J = np.full((len(v), 3), p["s"])
            else:
                v2 = np.c_[v[:, 0] * sx, fy(v[:, 1]), fz(v[:, 2])]
                J = np.c_[np.full(len(v), sx), np.maximum(dfy(v[:, 1]), 1e-3), np.maximum(dfz(v[:, 2]), 1e-3)]
            work.append((prim, M, bool(m), name, v2, J))
    # pass 2: the photograph's roofline, when the agent found one
    rs = None
    if target.get("roof"):
        body = np.vstack([w[4] for w in work if not w[2] and w[3].startswith(("SB_body", "SB_door", "SB_panel", "SB_tailgate"))])
        rs = roof_stage(target["roof"], p, d, body)
    for prim, M, is_wheel, name, v2, J in work:
        at = prim["attributes"]
        A = M[:3, :3]
        Ai = np.linalg.inv(A)
        a = b = None
        if rs and not is_wheel:
            fk, dfk, ya, _ = rs
            h = v2[:, 1] - ya
            t = np.clip(h / 0.12, 0, 1)
            w = t * t * (3 - 2 * t)                           # smoothstep from the arch tops up
            dw = np.where((h > 0) & (h < 0.12), 6 * t * (1 - t) / 0.12, 0.0)
            kz, dkz = fk(v2[:, 2]), dfk(v2[:, 2])
            v2 = v2.copy()
            v2[:, 1] = v2[:, 1] + w * np.maximum(h, 0) * (kz - 1)
            a = 1 + (kz - 1) * (w + dw * np.maximum(h, 0))    # dy'/dy
            b = w * np.maximum(h, 0) * dkz                    # dy'/dz
            a = np.maximum(a, 1e-3)
        local = (v2 - M[:3, 3]) @ Ai.T
        at["POSITION"] = g.add_accessor(local, minmax=True, target=34962)
        if "NORMAL" in at:                                   # through the inverse transpose of the Jacobian
            n = g.accessor(at["NORMAL"]) @ Ai                 # local -> world: A^-T n, as rows: n @ A^-1
            n = n / J
            if a is not None:                                 # the roof stage: [[1,0,0],[0,a,b],[0,0,1]]^-T
                n = np.c_[n[:, 0], n[:, 1] / a, n[:, 2] - (b / a) * n[:, 1]]
            n = n @ A                                         # world -> local: A^T n
            n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
            at["NORMAL"] = g.add_accessor(n, target=34962)
        if "TANGENT" in at:
            t4 = g.accessor(at["TANGENT"])
            t = (t4[:, :3] @ A.T) * J
            if a is not None:
                t = np.c_[t[:, 0], a * t[:, 1] + b * t[:, 2], t[:, 2]]
            t = t @ Ai.T
            t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-12)
            at["TANGENT"] = g.add_accessor(np.c_[t, t4[:, 3:4]], target=34962)
        prim["_v_world"] = v2
    log = dict(p["log"], target=target.get("name"), donor_measured={k: round(v, 3) for k, v in d.items()
                                                                     if isinstance(v, float)})
    if rs:
        info = dict(rs[3])
        zc, rt, ok = info.pop("_check")
        body = np.vstack([w[0]["_v_world"] for w in work if not w[2] and w[3].startswith(("SB_body", "SB_door", "SB_panel", "SB_tailgate"))])
        zc2, top2 = _top(body, 0.3 * p["log"]["width_m"][1], zc[0] - 0.025, zc[-1] - 0.025)
        n = min(len(top2), len(rt))
        okn = ok[:n]
        info["roofline_off_cm_after"] = round(100 * float(np.nanmean(np.abs(top2[:n][okn] - rt[:n][okn]))), 1)
        log["roofline"] = dict(info, photo=target["roof"].get("file"))
    for w in work:
        w[0].pop("_v_world", None)
    g.save(dst)
    if target.get("debadge", True):
        log["debadged"] = debadge(dst)
    big = {k: v for k, v in (("along", log["along"][0] / log["along"][1]), ("height", p["log"]["height_m"][1] / p["log"]["height_m"][0]),
                              ("width", sx)) if abs(v - 1) > 0.18}
    if big:
        log["large_change"] = {k: round(v, 3) for k, v in big.items()}
    return log


PLATE = {"front": [0.92, 0.92, 0.90, 1.0], "rear": [0.96, 0.78, 0.08, 1.0]}     # plain UK plates
NOT_BADGE = re.compile(r"glass|window|lamp|light|lens|signal|indic|refl|chmsl|tail|head|mirror", re.I)
BADGE = re.compile(r"badge|logo|emblem|letter", re.I)          # the modeller said so
PLATE_MAT = re.compile(r"plate|licen[cs]e|number", re.I)


def _closed(m):
    """A lamp's cells with the gaps between its vertices closed, no wider."""
    from scipy.ndimage import binary_closing
    return binary_closing(m, structure=np.ones((3, 3), bool)) | m


def _cover(T, x0, y0, cell, shape, depth=None):
    """The grid cells (x, y) under the triangles T (n, 3, 3), seen end on;
    with DEPTH ("front" or "rear") the outermost z in each cell instead
    (-inf / +inf where there is none)."""
    m = np.zeros(shape, bool) if depth is None else np.full(shape, -np.inf if depth == "front" else np.inf)
    if not len(T):
        return m
    edge = np.max([np.linalg.norm((T[:, a] - T[:, b])[:, :2], axis=1) for a, b in ((0, 1), (1, 2), (2, 0))], axis=0)
    k = np.clip(np.ceil(edge / (0.5 * cell)).astype(int), 1, 120)
    for kk in np.unique(k):
        i, j = np.mgrid[0:kk + 1, 0:kk + 1]
        a, b = i[i + j <= kk] / kk, j[i + j <= kk] / kk
        P = np.einsum("mk,nkd->nmd", np.stack([1 - a - b, a, b], 1), T[k == kk]).reshape(-1, 3)
        ij = (np.clip(((P[:, 0] - x0) / cell).astype(int), 0, shape[0] - 1),
              np.clip(((P[:, 1] - y0) / cell).astype(int), 0, shape[1] - 1))
        if depth is None:
            m[ij] = True
        else:
            (np.maximum if depth == "front" else np.minimum).at(m, ij, P[:, 2])
    return m


def _flat(g, prim, I, lab, side, M, panel=None):
    """Painted-over badge pieces pressed flat against what they stand on, a
    millimetre behind their own backs, so not even the brand's shape is
    left in relief. Each piece flattens along its own outward face (a badge
    on a sloping boot lid stays on the lid), and takes the panel's own
    normal where there is paint around it (panel(point) gives it), so the
    glossy paint shades the same across it. Its walls go (pressed flat they
    are slivers) and every face left is turned to look out: the paint is
    double-sided, and a badge's back pressed onto its front would show dark.
    The pieces get vertices of their own; the rest of the part keeps the
    originals. Returns the new primitive's attributes and indices (None if
    nothing is left)."""
    used, J = np.unique(I, return_inverse=True)
    J = J.reshape(-1, 3)
    w = g.accessor(prim["attributes"]["POSITION"])[used] @ M[:3, :3].T + M[:3, 3]
    nrm = np.zeros_like(w)
    keep, flip = np.zeros(len(J), bool), np.zeros(len(J), bool)
    for L in np.unique(lab):
        t = lab == L
        vi = np.unique(J[t])
        cr = np.cross(w[J[t, 1]] - w[J[t, 0]], w[J[t, 2]] - w[J[t, 0]])
        out = np.array([0.0, 0.0, side[t][0]])
        along = cr @ out
        face = np.abs(along) > 0.8 * np.linalg.norm(cr, axis=1)          # the faces looking out, either winding
        n = (cr[face] * np.sign(along[face])[:, None]).sum(0) if face.any() else out
        n = n / max(np.linalg.norm(n), 1e-12)
        pn = panel(w[vi].mean(0), out) if panel else None
        if pn is not None:
            n = pn
        a_n = cr @ n
        keep[t] = np.abs(a_n) > 0.2 * np.linalg.norm(cr, axis=1)
        flip[t] = a_n < 0
        dd = (w[vi] - w[vi].mean(0)) @ n
        w[vi] -= (dd - dd.min() + 0.001)[:, None] * n
        nrm[vi] = n
    J = np.where(flip[:, None], J[:, [0, 2, 1]], J)[keep]
    if not len(J):
        return None, None
    Mi = np.linalg.inv(M)
    att = {}
    for key, acc in prim["attributes"].items():
        if key == "POSITION":
            att[key] = g.add_accessor(w @ Mi[:3, :3].T + Mi[:3, 3], minmax=True)
        elif key == "NORMAL":
            nl = nrm @ M[:3, :3]
            att[key] = g.add_accessor(nl / np.maximum(np.linalg.norm(nl, axis=1, keepdims=True), 1e-12))
        elif key.startswith("JOINTS"):
            att[key] = g.add_accessor(g.accessor(acc)[used], ctype=g.j["accessors"][acc]["componentType"])
        else:
            att[key] = g.add_accessor(g.accessor(acc)[used])
    return att, g.add_accessor(J.ravel().astype(np.uint32), ctype=5125, atype="SCALAR", target=34963)


def debadge(path):
    """A stand-in must not claim to be its donor. Found by shape, on the
    car's front and rear faces only:
      plates    flat rectangles of a plate's size, centred (measured in the
                plate's own plane, so a tilted one counts): plain, white at
                the front, yellow at the back, their text gone;
      logo      front and back, small pieces on the face within 13 cm of
                the centre line, and everything within their outline (the
                backing, the inlay, a lit logo): painted over in the body
                colour and pressed flat, so not even the shape is left;
      lettering at the back, small pieces standing on the face above the
                bumper (a glyph can be dozens of fragments): the same.
    Painting over rather than cutting out leaves no holes, and a fragment
    missed shows as a faint relief, not a broken word. Glass, lamps, paint
    and whatever is seen through the glass are never touched. Returns
    counts for the report."""
    from scipy.ndimage import maximum_filter, minimum_filter
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    g = GLTF(path)
    parts = _parts(g)
    d = measure(g, parts)
    mats = g.j.setdefault("materials", [])
    every = np.vstack([v for i, name, M in parts if not WHEEL.match(name)
                       for v in _world(g, g.j["meshes"][g.j["nodes"][i]["mesh"]], M)])
    cell = 0.04
    x0, y0 = every[:, 0].min() - cell, every[:, 1].min() - cell
    gx = np.clip(((every[:, 0] - x0) / cell).astype(int), 0, None)
    gy = np.clip(((every[:, 1] - y0) / cell).astype(int), 0, None)
    shape = (gx.max() + 3, gy.max() + 3)
    front, rear = np.full(shape, -np.inf), np.full(shape, np.inf)
    np.maximum.at(front, (gx, gy), every[:, 2])
    np.minimum.at(rear, (gx, gy), every[:, 2])
    # each cell's own face; an empty cell takes its neighbours' (a sloping
    # boot lid must not borrow the spoiler's lip 12 cm further back)
    front = np.where(np.isfinite(front), front, maximum_filter(front, size=3))
    rear = np.where(np.isfinite(rear), rear, minimum_filter(rear, size=3))
    zf_zone = d["zf"] + 0.5 * (d["zmax"] - d["zf"])
    zr_zone = d["zr"] - 0.5 * (d["zr"] - d["zmin"])
    # where the lamps are, seen from each end: nothing there is painted over
    lamp = {"front": np.zeros(shape, bool), "rear": np.zeros(shape, bool)}
    for i, name, M in parts:
        if name.startswith("SB_lamps"):
            mesh = g.j["meshes"][g.j["nodes"][i]["mesh"]]
            for prim, v in zip(mesh["primitives"], _world(g, mesh, M)):
                mi = prim.get("material")
                mname = (mats[mi].get("name") or "") if mi is not None and mi < len(mats) else ""
                if BADGE.search(mname) or PLATE_MAT.search(mname):   # a lit badge or plate the rigger put with the lamps
                    continue
                for end, sel in (("front", v[:, 2] > zf_zone), ("rear", v[:, 2] < zr_zone)):
                    if sel.any():
                        lamp[end][np.clip(((v[sel, 0] - x0) / cell).astype(int), 0, shape[0] - 1),
                                  np.clip(((v[sel, 1] - y0) / cell).astype(int), 0, shape[1] - 1)] = True
    lamp = {k: _closed(m) for k, m in lamp.items()}
    # where the glass is, and the lamps' lenses, seen from each end: the cabin
    # behind a window and a lamp's insides are not a badge
    pane = {"front": [], "rear": []}
    for i, name, M in parts:
        mesh = g.j["meshes"][g.j["nodes"][i]["mesh"]]
        for prim, v in zip(mesh["primitives"], _world(g, mesh, M)):
            mi = prim.get("material")
            mat = g.j["materials"][mi] if mi is not None and mi < len(g.j.get("materials", [])) else {}
            lens = name.startswith("SB_lamps") and not BADGE.search(mat.get("name") or "") \
                and not PLATE_MAT.search(mat.get("name") or "") \
                and (mat.get("alphaMode") == "BLEND" or NOT_BADGE.search(mat.get("name") or ""))
            if not (name.startswith("SB_glazing") or "KHR_materials_transmission" in mat.get("extensions", {})
                    or re.search(r"glass|window", mat.get("name", ""), re.I) or lens):
                continue
            I = g.accessor(prim["indices"]).reshape(-1, 3).astype(np.int64) if "indices" in prim \
                else np.arange(len(v)).reshape(-1, 3)
            T = v[I]
            pane["front"].append(T[(T[:, :, 2] > zf_zone).any(1)])
            pane["rear"].append(T[(T[:, :, 2] < zr_zone).any(1)])
    glass = {k: _cover(np.concatenate(T) if T else np.zeros((0, 3, 3)), x0, y0, cell, shape, depth=k)
             for k, T in pane.items()}

    def behind_glass(end, kx, ky, lo, hi):
        """Inside the car behind a window, seen from this end (not merely near one)."""
        gz = glass[end][kx, ky]
        return bool(np.isfinite(gz)) and (hi[2] < gz - 0.005 if end == "front" else lo[2] > gz + 0.005)
    paint = None
    for panel_part in ("SB_door", "SB_panel_bonnet", "SB_tailgate", "SB_body"):   # the paint: most of the doors
        area_by_mat = {}                                        # (as finish.py), else of the bonnet, ...
        for i, name, M in parts:
            if name.startswith(panel_part):
                mesh = g.j["meshes"][g.j["nodes"][i]["mesh"]]
                for prim, v in zip(mesh["primitives"], _world(g, mesh, M)):
                    mi = prim.get("material")
                    mat = mats[mi] if mi is not None and mi < len(mats) else {}
                    if "KHR_materials_transmission" in mat.get("extensions", {}) or mat.get("alphaMode") == "BLEND":
                        continue
                    I = g.accessor(prim["indices"]).reshape(-1, 3) if "indices" in prim else np.arange(len(v)).reshape(-1, 3)
                    a = 0.5 * np.linalg.norm(np.cross(v[I[:, 1]] - v[I[:, 0]], v[I[:, 2]] - v[I[:, 0]]), axis=1).sum()
                    area_by_mat[mi] = area_by_mat.get(mi, 0) + a
        if area_by_mat:
            paint = max(area_by_mat, key=area_by_mat.get)
            break
    # the paint's own surface at each end, for the normal a flattened badge takes
    from scipy.spatial import cKDTree
    pc, pnrm = [], []
    for i, name, M in parts:
        if WHEEL.match(name):
            continue
        mesh = g.j["meshes"][g.j["nodes"][i]["mesh"]]
        for prim, v in zip(mesh["primitives"], _world(g, mesh, M)):
            if prim.get("material") != paint:
                continue
            I = g.accessor(prim["indices"]).reshape(-1, 3).astype(np.int64) if "indices" in prim \
                else np.arange(len(v)).reshape(-1, 3)
            c = v[I].mean(1)
            k = (c[:, 2] > zf_zone) | (c[:, 2] < zr_zone)
            cr = np.cross(v[I[k, 1]] - v[I[k, 0]], v[I[k, 2]] - v[I[k, 0]])
            pc.append(c[k])
            pnrm.append(cr / np.maximum(np.linalg.norm(cr, axis=1, keepdims=True), 1e-12))
    tree = cKDTree(np.vstack(pc)) if pc and sum(map(len, pc)) else None
    pnrm = np.vstack(pnrm) if tree is not None else None

    def panel(at, out):
        """The paint's outward normal within 8 cm of AT, or None (a badge in a grille)."""
        if tree is None:
            return None
        k = tree.query_ball_point(at, 0.08)
        if len(k) < 3:
            return None
        n = pnrm[k]
        n = n * np.sign(n @ out + 1e-9)[:, None]                 # either winding, facing out of this end
        n = n[n @ out > 0.2].sum(0) if (n @ out > 0.2).any() else None
        return None if n is None else n / max(np.linalg.norm(n), 1e-12)
    plate_mat = {}

    def plate_material(end):
        if end not in plate_mat:
            mats.append({"name": f"plate_{end}_plain", "pbrMetallicRoughness": {
                "baseColorFactor": PLATE[end], "metallicFactor": 0.0, "roughnessFactor": 0.45}})
            plate_mat[end] = len(mats) - 1
        return plate_mat[end]
    out = {"plates": 0, "front_badge_pieces": 0, "rear_badge_pieces": 0}
    # first look: every small piece on the two faces, judged on its own
    work = []
    for i, name, M in parts:
        if WHEEL.match(name) or name.startswith("SB_glazing"):
            continue
        mesh = g.j["meshes"][g.j["nodes"][i]["mesh"]]
        for prim, v in zip(list(mesh["primitives"]), _world(g, mesh, M)):
            mi = prim.get("material")
            mat = mats[mi] if mi is not None and mi < len(mats) else {}
            if mi == paint or "KHR_materials_transmission" in mat.get("extensions", {}) \
                    or re.search(r"glass|window", mat.get("name", ""), re.I):
                continue
            # a lamp, a lit or see-through part is never painted over; a plate in it still turns plain
            plates_only = bool(NOT_BADGE.search(mat.get("name", ""))) or mat.get("alphaMode") == "BLEND" \
                or any(mat.get("emissiveFactor") or [0]) or name.startswith("SB_lamps")
            I = g.accessor(prim["indices"]).reshape(-1, 3).astype(np.int64) if "indices" in prim \
                else np.arange(len(v)).reshape(-1, 3)
            if not len(I):
                continue
            c = v[I].mean(1)
            near = (c[:, 2] > zf_zone) | (c[:, 2] < zr_zone)
            if not near.any():
                continue
            # pieces by shared corners, welded by position first: some models
            # are a "triangle soup", every triangle with corners of its own
            _, weld = np.unique(np.round(v / 1e-5).astype(np.int64), axis=0, return_inverse=True)
            W_ = weld.ravel()[I]
            e = np.r_[W_[:, 0], W_[:, 1], W_[:, 2]], np.r_[W_[:, 1], W_[:, 2], W_[:, 0]]
            nw = int(W_.max()) + 1
            _, lab = connected_components(coo_matrix((np.ones(len(e[0])), e), shape=(nw, nw)), directed=False)
            tlab = lab[W_[:, 0]]
            cr = np.cross(v[I[:, 1]] - v[I[:, 0]], v[I[:, 2]] - v[I[:, 0]])
            pieces = []
            for L in np.unique(tlab[near]):
                t = tlab == L
                if t.sum() > 4000:                               # a whole bumper, not a badge
                    continue
                pv = v[np.unique(I[t])]
                lo, hi = pv.min(0), pv.max(0)
                w, h, dz = hi - lo
                cx, cy, cz = c[t].mean(0)
                end = "front" if cz > zf_zone else "rear" if cz < zr_zone else None
                if end is None:
                    continue
                kx = int(np.clip((cx - x0) / cell, 0, shape[0] - 1))
                ky = int(np.clip((cy - y0) / cell, 0, shape[1] - 1))
                face = front[kx, ky] if end == "front" else rear[kx, ky]
                if not np.isfinite(face):
                    continue
                proud = (face - hi[2]) if end == "front" else (lo[2] - face)     # how far behind the face
                piece = {"t": t, "end": end, "xy": pv[:, :2], "is": None, "z": (lo[2], hi[2]), "cx": cx,
                         "sig": (int(t.sum()), round(w / 0.005), round(h / 0.005)), "named": False,
                         "layer": max(w, h) <= 0.56 and not lamp[end][kx, ky] and not behind_glass(end, kx, ky, lo, hi)}
                pieces.append(piece)
                # a plate: upright and plate-sized, or tilted and plate-sized in its own plane
                if len(pv) >= 4 and abs(cx) < 0.15 and w >= 0.3 and proud < 0.15:
                    nz = cr[t, 2].sum() / max(np.linalg.norm(cr[t].sum(0)), 1e-12)
                    upright = 0.36 <= w <= 0.56 and 0.08 <= h <= 0.17 and dz < 0.05 and abs(nz) > 0.7
                    q = pv - pv.mean(0)
                    _, _, vt = np.linalg.svd(q, full_matrices=False)
                    ext = np.ptp(q @ vt.T, axis=0)
                    tilted = 0.36 <= ext[0] <= 0.56 and 0.08 <= ext[1] <= 0.17 and ext[2] < 0.03 and abs(vt[2, 2]) > 0.6
                    if upright or tilted:
                        piece["is"] = "plate"
                        out["plates"] += 1
                        continue
                if behind_glass(end, kx, ky, lo, hi) or t.sum() < 2:
                    continue
                if BADGE.search(mat.get("name") or "") and max(w, h) < 0.3 and proud < 0.05:
                    piece["is"], piece["named"] = "badge", True
                    continue
                if lamp[end][kx, ky]:
                    continue
                if plates_only:                              # a lit logo: only as part of a badge
                    piece["is"] = "maybe" if max(w, h) < 0.16 and proud < 0.1 else None
                    continue
                compact = max(w, h) < 0.03 or max(w, h) / max(min(w, h), 1e-6) < 2.6   # a badge, not a grille bar
                if abs(cx) + w / 2 < 0.13 and max(w, h) < 0.25 and compact and proud < (0.025 if end == "front" else 0.02):
                    piece["is"] = "badge"                    # the brand's badge, front or back
                elif end == "rear" and max(w, h) < 0.15 and h < 0.08 and proud < 0.02 and cy > 0.45 * d["height"] \
                        and abs(cx) < 0.75 * d["width"] / 2:
                    piece["is"], piece["named"] = "badge", True   # the model's name and engine (glyphs repeat)
                elif max(w, h) < 0.16 and proud < 0.1:
                    piece["is"] = "maybe"                    # only if it lies within a badge
            # a piece repeated across the face (a honeycomb grille's cells, a
            # vent's slats) is a pattern, not a badge
            kin = {}
            for p_ in pieces:
                kin.setdefault(p_["sig"], []).append(p_)
            for same in kin.values():
                if len(same) >= 8 and np.ptp([p_["cx"] for p_ in same]) > 0.3:
                    for p_ in same:
                        if p_["is"] in ("badge", "maybe") and not p_["named"]:
                            p_["is"] = None
            work.append((mesh, prim, M, v, I, tlab, pieces))
    # second look: whatever lies within a badge's outline (its backing, its
    # inlay, the light behind it) goes with it, holes and all filled in
    from scipy.ndimage import binary_fill_holes
    fine = 0.01
    fshape = (int(shape[0] * cell / fine) + 2, int(shape[1] * cell / fine) + 2)

    def at(xy):
        return (np.clip(((xy[:, 0] - x0) / fine).astype(int), 0, fshape[0] - 1),
                np.clip(((xy[:, 1] - y0) / fine).astype(int), 0, fshape[1] - 1))
    outline = {"front": np.zeros(fshape, bool), "rear": np.zeros(fshape, bool)}
    for _, _, _, v_, I_, _, ps in work:
        for p_ in ps:
            if p_["is"] != "badge":
                continue
            T = v_[I_[p_["t"]]]                                  # drawn where it is, no wider
            i0, j0 = [max(int(np.floor((T[:, :, k].min() - o) / fine)) - 1, 0) for k, o in ((0, x0), (1, y0))]
            sub = _cover(T, x0 + i0 * fine, y0 + j0 * fine, fine,
                         (int(np.ptp(T[:, :, 0]) / fine) + 4, int(np.ptp(T[:, :, 1]) / fine) + 4))
            win = outline[p_["end"]][i0:i0 + sub.shape[0], j0:j0 + sub.shape[1]]
            win |= sub[:win.shape[0], :win.shape[1]]
    outline = {k: binary_fill_holes(m) for k, m in outline.items()}   # a ring of fragments holds its middle
    # a plate is often built in layers (its white, its letters, the EU band):
    # whatever lies on a plate's outline, within 3 cm of it, is the plate too
    plate = {"front": np.zeros(fshape, bool), "rear": np.zeros(fshape, bool)}
    plate_z = {"front": [], "rear": []}
    for _, _, _, v_, I_, _, ps in work:
        for p_ in ps:
            if p_["is"] == "plate":
                plate[p_["end"]] |= _cover(v_[I_[p_["t"]]], x0, y0, fine, fshape)
                plate_z[p_["end"]].append(p_["z"])
    plate = {k: binary_fill_holes(m) for k, m in plate.items()}
    for mesh, prim, M, v, I, tlab, pieces in work:
        for p_ in pieces:
            e = p_["end"]
            if p_["is"] != "plate" and p_["layer"] and plate_z[e] and plate[e][at(p_["xy"])].mean() >= 0.97 \
                    and any(z0 - 0.03 <= p_["z"][0] and p_["z"][1] <= z1 + 0.03 for z0, z1 in plate_z[e]):
                p_["is"] = "plate"
                out["plate_layers"] = out.get("plate_layers", 0) + 1
            elif p_["is"] == "maybe" and outline[e][at(p_["xy"])].mean() >= 0.97:
                p_["is"] = "badge"
            if p_["is"] == "badge":
                out[e + "_badge_pieces"] += 1
    # and the change: plates plain, badges painted over and pressed flat
    new_prims = {}
    for mesh, prim, M, v, I, tlab, pieces in work:
        to = {"plate_front": np.zeros(len(I), bool), "plate_rear": np.zeros(len(I), bool),
              "paint": np.zeros(len(I), bool)}
        side = np.zeros(len(I))
        for p_ in pieces:
            if p_["is"] == "plate":
                to["plate_" + p_["end"]] |= p_["t"]
            elif p_["is"] == "badge" and paint is not None:
                to["paint"] |= p_["t"]
                side[p_["t"]] = 1.0 if p_["end"] == "front" else -1.0
        moved = to["plate_front"] | to["plate_rear"] | to["paint"]
        if not moved.any():
            continue
        for k, tm in to.items():
            if not tm.any():
                continue
            np_ = {kk: vv for kk, vv in prim.items() if kk not in ("indices", "material", "extensions")}
            if k == "paint":                                     # pressed flat, on vertices of its own
                np_.pop("targets", None)
                np_["attributes"], np_["indices"] = _flat(g, prim, I[tm], tlab[tm], side[tm], M, panel)
                if np_["indices"] is None:
                    continue
            else:
                np_["attributes"] = dict(prim["attributes"])
                np_["indices"] = g.add_accessor(I[tm].ravel().astype(np.uint32), ctype=5125, atype="SCALAR",
                                                target=34963)
            np_["material"] = paint if k == "paint" else plate_material(k[6:])
            new_prims.setdefault(id(mesh), (mesh, []))[1].append(np_)
        prim["indices"] = g.add_accessor(I[~moved].ravel().astype(np.uint32), ctype=5125, atype="SCALAR", target=34963)
    for mesh, extra in new_prims.values():
        mesh["primitives"].extend(extra)
    g.save(path)
    return out


if __name__ == "__main__":
    print(json.dumps(warp(sys.argv[1], json.load(open(sys.argv[2])), sys.argv[3]), indent=1))
