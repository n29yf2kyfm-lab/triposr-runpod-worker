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

What it is not: the target's own face. Lamps, grille and badges stay the
donor's; the report and the file's credit call the car a stand-in.
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

VERSION = "1.1"                     # a change here reshapes stand-ins built before
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
    for i, name, M in parts:
        mesh = g.j["meshes"][g.j["nodes"][i]["mesh"]]
        A = M[:3, :3]
        Ai = np.linalg.inv(A)
        m = WHEEL.match(name)
        for prim in mesh["primitives"]:
            at = prim["attributes"]
            v = g.accessor(at["POSITION"]) @ A.T + M[:3, 3]
            if m:                                             # whole: moved and evenly scaled
                c0 = d["wheels"][m.group(1)]["centre"]
                v2 = new_c[m.group(1)] + p["s"] * (v - c0)
                J = np.full((len(v), 3), p["s"])
            else:
                v2 = np.c_[v[:, 0] * sx, fy(v[:, 1]), fz(v[:, 2])]
                J = np.c_[np.full(len(v), sx), np.maximum(dfy(v[:, 1]), 1e-3), np.maximum(dfz(v[:, 2]), 1e-3)]
            local = (v2 - M[:3, 3]) @ Ai.T
            at["POSITION"] = g.add_accessor(local, minmax=True, target=34962)
            if "NORMAL" in at:                               # world normal / J (the inverse transpose of a diagonal)
                n = g.accessor(at["NORMAL"]) @ Ai             # local -> world: A^-T n, as rows: n @ A^-1
                n = n / J
                n = n @ A                                     # world -> local: A^T n
                n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
                at["NORMAL"] = g.add_accessor(n, target=34962)
            if "TANGENT" in at:
                t4 = g.accessor(at["TANGENT"])
                t = (t4[:, :3] @ A.T) * J
                t = t @ Ai.T
                t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-12)
                at["TANGENT"] = g.add_accessor(np.c_[t, t4[:, 3:4]], target=34962)
    g.save(dst)
    log = dict(p["log"], target=target.get("name"), donor_measured={k: round(v, 3) for k, v in d.items()
                                                                     if isinstance(v, float)})
    big = {k: v for k, v in (("along", log["along"][0] / log["along"][1]), ("height", p["log"]["height_m"][1] / p["log"]["height_m"][0]),
                              ("width", sx)) if abs(v - 1) > 0.18}
    if big:
        log["large_change"] = {k: round(v, 3) for k, v in big.items()}
    return log


if __name__ == "__main__":
    print(json.dumps(warp(sys.argv[1], json.load(open(sys.argv[2])), sys.argv[3]), indent=1))
