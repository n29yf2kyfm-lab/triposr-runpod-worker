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

VERSION = "1.2"                     # a change here reshapes stand-ins built before
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
    big = {k: v for k, v in (("along", log["along"][0] / log["along"][1]), ("height", p["log"]["height_m"][1] / p["log"]["height_m"][0]),
                              ("width", sx)) if abs(v - 1) > 0.18}
    if big:
        log["large_change"] = {k: round(v, 3) for k, v in big.items()}
    return log


if __name__ == "__main__":
    print(json.dumps(warp(sys.argv[1], json.load(open(sys.argv[2])), sys.argv[3]), indent=1))
