#!/usr/bin/env python3
"""morph.py — reshape a master car into another car of the same body style.

    python3 pipeline/template/morph.py MASTER.glb SPEC.json OUT.glb

A master is a properly built car: separate doors, bonnet and tailgate, clear
glass, a full interior. Every car made from it inherits all of that, so the
output always opens and always has a cabin behind clear glass — by
construction, not by repair.

SPEC.json (published figures, mm):
    {"name": "Ford Fiesta Mk7", "length": 4040, "width": 1735, "height": 1476,
     "wheelbase": 2493, "track": 1493, "wheel_d": 619,
     "paint": [0.05, 0.18, 0.55],
     "side_profile": "path/to/side_cutout.png"}       # optional
track, wheel_d, paint and side_profile are optional.

THE WARP (master frame: y up, nose +z, the car's left +x)
  along the car   a smooth monotone map through the tail, both wheel arches
                  and the nose: the overhangs and wheelbase become the
                  target's, and each arch keeps the wheel's own scale so it
                  stays round around the new wheel;
  up the car      below the arch tops everything scales with the wheel; above,
                  each station is stretched so the roofline meets the
                  target's — from its side photograph when there is one, else
                  its published height;
  across the car  the published width.
  Wheels, tyres, discs and calipers are moved rigidly to the new axles and
  track and scaled to the new wheel size: a wheel is never squashed.
Normals and tangents are carried through the warp's own Jacobian, so the
paint keeps its reflections where the panel kept its shape.

THE RIG. Doors, bonnet and tailgate each hang from a pivot node placed on the
warped part's own hinge edge, and the file carries glTF animation clips
(door_FL_open … tailgate_open, doors_open, all_open) so any viewer can open
them with no code of its own.
"""
import json
import math
import os
import re
import sys

import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.ndimage import gaussian_filter1d

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gltf import GLTF  # noqa: E402

GROUPS = [  # first match wins, on the node name
    ("wheel_FL", r"(Tire|Rim)_FL|Brake_FL"),
    ("wheel_FR", r"(Tire|Rim)_FR|Brake_FR"),
    ("wheel_RL", r"(Tire|Rim)_RL"),
    ("wheel_RR", r"(Tire|Rim)_RR"),
    ("wheel_rear", r"Brake_Rear"),                 # one mesh for both rear corners
    ("door_FL", r"Door_FL|Mirror_FL"),
    ("door_FR", r"Door_FR"),
    ("door_RL", r"Door_RL"),
    ("door_RR", r"Door_RR"),
    ("tailgate", r"Trunk_Lid(?!_Hyd)"),
    ("bonnet", r"Panel_Bonnet"),
]
HINGED = {"door_FL": -65, "door_FR": 65, "door_RL": -65, "door_RR": 65, "bonnet": -55, "tailgate": 75}


def group_of(name):
    for g, rx in GROUPS:
        if re.search(rx, name):
            return g
    return "body"


def collect(g):
    """Every mesh node with its world matrix, group and world-space vertices."""
    W, parent = g.world_matrices()
    out = []
    for i, n in enumerate(g.j["nodes"]):
        if "mesh" not in n:
            continue
        name = n.get("name") or ""
        if i in parent and g.j["nodes"][parent[i]].get("name", "").startswith("G:"):
            name = g.j["nodes"][parent[i]]["name"]
        name = re.sub(r"^G:", "", name)
        name = re.sub(r"_DefaultOBJ.*$", "", name)
        M = W[i]
        prims = []
        for p in g.j["meshes"][n["mesh"]]["primitives"]:
            v = g.accessor(p["attributes"]["POSITION"])
            prims.append((p, (np.c_[v, np.ones(len(v))] @ M.T)[:, :3]))
        out.append({"node": i, "mesh": n["mesh"], "name": name, "group": group_of(name), "M": M, "prims": prims})
    return out


def measure(parts):
    def verts(pred):
        vs = [v for pt in parts if pred(pt) for _, v in pt["prims"]]
        return np.vstack(vs) if vs else np.zeros((0, 3))
    allv = verts(lambda pt: True)
    tyres = {c: verts(lambda pt, c=c: pt["group"] == "wheel_" + c and "Tire" in pt["name"]) for c in ("FL", "FR", "RL", "RR")}
    gy = min(t[:, 1].min() for t in tyres.values())
    R = np.mean([(t[:, 1].max() - t[:, 1].min()) / 2 for t in tyres.values()])
    centre = {c: np.array([(t[:, 0].min() + t[:, 0].max()) / 2, gy + R, (t[:, 2].min() + t[:, 2].max()) / 2])
              for c, t in tyres.items()}
    body = verts(lambda pt: pt["group"] == "body" and "Car_Paint" in pt["name"])
    zf = (centre["FL"][2] + centre["FR"][2]) / 2
    zr = (centre["RL"][2] + centre["RR"][2]) / 2
    # the master's own top line: highest point per 1 cm station over the outside of the car
    ext = verts(lambda pt: pt["name"].startswith("Ext") or pt["group"] in ("bonnet", "tailgate"))
    z0, z1 = allv[:, 2].min(), allv[:, 2].max()
    bins = np.arange(z0, z1 + 0.01, 0.01)
    idx = np.clip(((ext[:, 2] - z0) / 0.01).astype(int), 0, len(bins) - 1)
    top = np.full(len(bins), -np.inf)
    np.maximum.at(top, idx, ext[:, 1] - gy)
    ok = np.isfinite(top)
    top = np.interp(bins, bins[ok], top[ok])
    top = gaussian_filter1d(top, 2)
    return {"ground": float(gy), "R": float(R), "zf": float(zf), "zr": float(zr), "zmin": float(z0), "zmax": float(z1),
            "W": float(body[:, 0].max() - body[:, 0].min()), "H": float(allv[:, 1].max() - gy),
            "track": float(abs(centre["FL"][0] - centre["FR"][0])), "centre": centre,
            "roof_z": bins, "roof": top}


def side_profile(path, spec):
    """Target top line (metres above ground) against u (0 tail, 1 nose), and
    the axle positions, from a background-removed side photograph."""
    sys.path.insert(0, os.path.join(HERE, "..", "forge"))
    from trace import load_cutout, trace_side
    rgb, mask = load_cutout(path)
    s = trace_side(rgb, mask, {k: spec[k] for k in ("length", "width", "height", "wheelbase")} | {"wheel_d": spec.get("wheel_d", 620)})
    return s["u"], s["roof"], s["u_front"], s["u_rear"]


def build_warp(m, spec, log):
    L_t, W_t, H_t, WB_t = (spec[k] / 1000.0 for k in ("length", "width", "height", "wheelbase"))
    R_t = spec.get("wheel_d", m["R"] * 2000 * (L_t / (m["zmax"] - m["zmin"]))) / 2000.0
    s_r = R_t / m["R"]
    track_t = spec.get("track", m["track"] * 1000 * W_t / m["W"]) / 1000.0
    sx = W_t / m["W"]
    OF_m, OR_m = m["zmax"] - m["zf"], m["zr"] - m["zmin"]
    prof = None
    if spec.get("side_profile") and os.path.exists(spec["side_profile"]):
        u, roof, uf, ur = side_profile(spec["side_profile"], spec)
        mid = (uf + ur) / 2
        OF_t = (1 - (mid + WB_t / L_t / 2)) * L_t
        OR_t = L_t - WB_t - OF_t
        if not (0.4 * (L_t - WB_t) / 2 < OF_t < 1.6 * (L_t - WB_t) / 2):
            log["overhangs"] = "photo split implausible; master ratio used"
            prof = None
            OF_t = (L_t - WB_t) * OF_m / (OF_m + OR_m)
            OR_t = L_t - WB_t - OF_t
        else:
            prof = (u, roof)
            log["overhangs"] = "side photo"
    else:
        OF_t = (L_t - WB_t) * OF_m / (OF_m + OR_m)
        OR_t = L_t - WB_t - OF_t
        log["overhangs"] = "master ratio (no side photo)"
    zmid = (m["zf"] + m["zr"]) / 2
    zf_t, zr_t = zmid + WB_t / 2, zmid - WB_t / 2
    a = 1.25 * m["R"]
    src = [m["zmin"], m["zr"] - a, m["zr"] + a, m["zf"] - a, m["zf"] + a, m["zmax"]]
    dst = [zr_t - OR_t, zr_t - a * s_r, zr_t + a * s_r, zf_t - a * s_r, zf_t + a * s_r, zf_t + OF_t]
    Z = PchipInterpolator(src, dst, extrapolate=True)

    # vertical: below the arch tops scale with the wheel, above fit the roof
    hb, bw = 2.2 * m["R"], 0.06
    a_, c_ = hb - bw, hb + bw
    H_m = m["H"]
    k_glob = s_r + (H_t - s_r * H_m) / (bw + H_m - c_)
    zs = m["roof_z"]
    roof_m = m["roof"]
    if prof is not None:
        u, roof = prof
        zt = Z(zs)
        ut = (zt - (zr_t - OR_t)) / L_t
        R_tgt = np.interp(ut, u, roof)
        k = s_r + (R_tgt - s_r * roof_m) / np.maximum(bw + roof_m - c_, 1e-6)
        w = np.clip((roof_m - c_ - 0.08) / 0.12, 0, 1)          # trust the profile only above the bonnet line
        k = w * k + (1 - w) * k_glob
        k = gaussian_filter1d(np.clip(k, 0.6, 1.5), 6)
    else:
        k = np.full(len(zs), k_glob)
    gy = m["ground"]

    def I(u_):
        return u_ ** 3 - u_ ** 4 / 2

    def f(P):
        x, y, z = P[:, 0], P[:, 1], P[:, 2]
        h = y - gy
        kz = np.interp(z, zs, k)
        t = np.clip((h - a_) / (2 * bw), 0, 1)
        extra = np.where(h <= a_, 0.0, np.where(h < c_, 2 * bw * I(t), bw + (h - c_)))
        hn = s_r * h + (kz - s_r) * extra
        return np.c_[x * sx, gy + hn, Z(z)]

    wheels = {}
    for c, cm in m["centre"].items():
        sign = 1 if cm[0] > 0 else -1
        zt = zf_t if c[0] == "F" else zr_t
        wheels[c] = (cm, np.array([sign * track_t / 2, gy + R_t, zt]))
    log.update({"s_wheel": round(s_r, 4), "sx": round(sx, 4), "k_roof_global": round(float(k_glob), 4),
                "overhang_front_m": round(OF_t, 3), "overhang_rear_m": round(OR_t, 3),
                "track_m": round(track_t, 3), "wheel_d_m": round(2 * R_t, 3)})
    return f, wheels, s_r


def jac_normals(f, P, N, T=None, h=1e-3):
    """Push normals (and tangents) through the warp's Jacobian."""
    J = np.empty((len(P), 3, 3))
    for i in range(3):
        d = np.zeros(3)
        d[i] = h
        J[:, :, i] = (f(P + d) - f(P - d)) / (2 * h)
    out_n = None
    if N is not None:
        Jit = np.linalg.inv(J).transpose(0, 2, 1)
        n = np.einsum("nij,nj->ni", Jit, N)
        out_n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    out_t = None
    if T is not None:
        t = np.einsum("nij,nj->ni", J, T[:, :3])
        t = t / np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-12)
        out_t = np.c_[t, T[:, 3:4]]
    return out_n, out_t


def quat(axis, deg):
    a = np.array(axis, float)
    a /= np.linalg.norm(a)
    s = math.sin(math.radians(deg) / 2)
    return [float(a[0] * s), float(a[1] * s), float(a[2] * s), float(math.cos(math.radians(deg) / 2))]


def morph(master, spec, out):
    g = GLTF(master)
    parts = collect(g)
    m = measure(parts)
    log = {"master": os.path.basename(master), "target": spec.get("name"),
           "master_measured": {"length_m": round(m["zmax"] - m["zmin"], 3), "width_m": round(m["W"], 3),
                               "height_m": round(m["H"], 3), "wheelbase_m": round(m["zf"] - m["zr"], 3),
                               "track_m": round(m["track"], 3), "wheel_d_m": round(2 * m["R"], 3)}}
    f, wheels, s_r = build_warp(m, spec, log)

    group_verts = {}
    for pt in parts:
        Mn = np.linalg.inv(pt["M"][:3, :3]).T
        for p, Pw in pt["prims"]:
            at = p["attributes"]
            N = g.accessor(at["NORMAL"]) @ Mn.T if "NORMAL" in at else None
            if N is not None:
                N = N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
            T = g.accessor(at["TANGENT"]) if "TANGENT" in at else None
            if T is not None:
                T = np.c_[T[:, :3] @ pt["M"][:3, :3].T, T[:, 3:4]]
            if pt["group"].startswith("wheel"):
                # rigid: each vertex follows its nearest master wheel
                cs = list(wheels.items())
                d = np.stack([np.linalg.norm(Pw[:, [0, 2]] - cm[[0, 2]], axis=1) for _, (cm, ct) in cs], 1)
                near = d.argmin(1)
                newP = np.empty_like(Pw)
                for wi, (_, (cm, ct)) in enumerate(cs):
                    sel = near == wi
                    newP[sel] = ct + s_r * (Pw[sel] - cm)
                newN, newT = N, T
            else:
                newP = f(Pw)
                newN, newT = jac_normals(f, Pw, N, T)
            at["POSITION"] = g.add_accessor(newP, minmax=True, target=34962)
            if newN is not None:
                at["NORMAL"] = g.add_accessor(newN, target=34962)
            if newT is not None:
                at["TANGENT"] = g.add_accessor(newT, target=34962)
            group_verts.setdefault(pt["group"], []).append(newP)

    # ── new node tree: everything in world space, hinged parts on pivots ──
    j = g.j
    nodes = [{"name": spec.get("name") or "car", "children": []}]
    groups = {}
    for gname in sorted({pt["group"] for pt in parts}):
        if gname in HINGED:
            V = np.vstack(group_verts[gname])
            lo, hi = V.min(0), V.max(0)
            if gname.startswith("door"):
                left = (lo[0] + hi[0]) / 2 > 0
                piv = [float(hi[0] - 0.02 if left else lo[0] + 0.02), float((lo[1] + hi[1]) / 2), float(hi[2] - 0.03)]
                axis = [0, 1, 0]
            elif gname == "tailgate":
                piv, axis = [0.0, float(hi[1] - 0.01), float(hi[2] - 0.01)], [1, 0, 0]
            else:                                   # bonnet: hinge at its rear edge, under the screen
                piv, axis = [0.0, float(hi[1] - 0.01), float(lo[2] + 0.02)], [1, 0, 0]
            pivot = len(nodes)
            nodes.append({"name": gname + "_hinge", "translation": piv, "children": [pivot + 1],
                          "extras": {"axis": axis, "open_deg": HINGED[gname]}})
            nodes.append({"name": gname, "translation": [-c for c in piv], "children": []})
            nodes[0]["children"].append(pivot)
            groups[gname] = pivot + 1
            groups[gname + "_pivot"] = (pivot, axis, HINGED[gname])
        else:
            gi = len(nodes)
            nodes.append({"name": gname, "children": []})
            nodes[0]["children"].append(gi)
            groups[gname] = gi
    for pt in parts:
        ni = len(nodes)
        nodes.append({"name": pt["name"], "mesh": pt["mesh"]})
        nodes[groups[pt["group"]]]["children"].append(ni)
    j["nodes"] = nodes
    j["scenes"] = [{"name": spec.get("name") or "car", "nodes": [0]}]
    j["scene"] = 0

    # ── animation clips ──
    tin = g.add_accessor(np.array([0.0, 1.0]), minmax=True)
    clips = {}
    for gname, val in groups.items():
        if not gname.endswith("_pivot"):
            continue
        pivot, axis, deg = val
        part = gname[:-6]
        out_q = g.add_accessor(np.array([[0, 0, 0, 1], quat(axis, deg)]))
        clips.setdefault(part + "_open", []).append((pivot, out_q))
        if part.startswith("door"):
            clips.setdefault("doors_open", []).append((pivot, out_q))
        clips.setdefault("all_open", []).append((pivot, out_q))
    anims = []
    for name, chans in clips.items():
        samplers, channels = [], []
        for pivot, out_q in chans:
            samplers.append({"input": tin, "output": out_q, "interpolation": "LINEAR"})
            channels.append({"sampler": len(samplers) - 1, "target": {"node": pivot, "path": "rotation"}})
        anims.append({"name": name, "samplers": samplers, "channels": channels})
    j["animations"] = anims

    # ── paint ──
    if spec.get("paint"):
        for mat in j["materials"]:
            if mat.get("name") == "CarPaint":
                mat.setdefault("pbrMetallicRoughness", {})["baseColorFactor"] = list(spec["paint"]) + [1.0]
    j.setdefault("asset", {}).setdefault("extras", {})["template_morph"] = log
    size = g.save(out)
    log["bytes"] = size
    return log


if __name__ == "__main__":
    master, spec_p, out = sys.argv[1:4]
    print(json.dumps(morph(master, json.load(open(spec_p)), out), indent=1, default=float))
