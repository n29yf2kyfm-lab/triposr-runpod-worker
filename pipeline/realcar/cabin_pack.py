#!/usr/bin/env python3
"""cabin_pack.py — a cabin (seats, dashboard, steering wheel, console, the
trim between them) cut from one rigged car, for the models that come
without one: finish.py fits it between the axles of a car whose cabin is
empty (the 1998 Micra sourced for a K11 request: a shell, nothing inside).

    python3 cabin_pack.py RIGGED.glb OUT.glb --title T --author A --licence L --url U

RIGGED.glb is rig.py's output (rig frame: y up, nose +z, left +x, ground
y = 0, metres). The pack keeps the pieces wholly inside the cabin: inboard
of the doors, from just behind the rear axle to just short of the front
one, off the floor pan and below 78% of the roof (the headrests; not the
pillar trims, mirror and visors, which follow this car's own glasshouse).
Doors, wheels, lids, glass, the body paint and long wide shells (the roof
lining, the floor pan) stay out.
OUT.glb is in the pack frame: x across, y up from the ground, z along the
car from the middle of the wheelbase; its extras carry the donor's measures
and its credit, which goes with every car the cabin is fitted to.
"""
import argparse
import json
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

NOT_CABIN = ("SB_door", "SB_wheel", "SB_panel_bonnet", "SB_bonnet", "SB_tailgate")
GLASS = re.compile(r"glass|window|windscreen|screen", re.I)


def dense_points(T, step=0.015):
    """Points over triangles at most `step` apart along their longest edge
    (a low-poly roof is a few large triangles: corners alone leave holes)."""
    e = np.max(np.linalg.norm(T - np.roll(T, 1, axis=1), axis=2), axis=1)
    k = np.clip(np.ceil(e / step), 1, 300).astype(int)
    pts = [T.reshape(-1, 3)]
    for n in np.unique(k[k > 1]):
        sel = T[k == n]
        u, v = np.meshgrid(np.arange(n + 1), np.arange(n + 1))
        keep = (u + v) <= n
        u, v = u[keep] / n, v[keep] / n
        w = 1 - u - v
        pts.append((sel[:, None, 0] * w[None, :, None] + sel[:, None, 1] * u[None, :, None]
                    + sel[:, None, 2] * v[None, :, None]).reshape(-1, 3))
    return np.vstack(pts)


def roof_of(S, zf, zr):
    """The roof's height over the middle of the cabin (the middle third of
    the width, the middle 60% of the wheelbase): the highest surface point
    in each 5 cm cell, 90th percentile, so an aerial does not count (the
    Yaris's made its roof 19 cm too high)."""
    xm, half = (S[:, 0].max() + S[:, 0].min()) / 2, (S[:, 0].max() - S[:, 0].min()) / 2
    wb = zf - zr
    Q = S[(np.abs(S[:, 0] - xm) < half / 3) & (S[:, 2] > zr + .2 * wb) & (S[:, 2] < zf - .2 * wb)]
    uk, inv = np.unique(np.floor(Q[:, [0, 2]] / 0.05).astype(np.int64) @ np.array([100000, 1]), return_inverse=True)
    top = np.full(len(uk), -np.inf)
    np.maximum.at(top, inv, Q[:, 1])
    return float(np.percentile(top, 90))


def measures(car):
    """Axles, ground, half-width and roof of a rigged car (rig frame)."""
    W = {}
    for o in car.objs:
        for k in ("fl", "fr", "rl", "rr"):
            if f"SB_wheel_{k}" in o["chain"] and car.nfaces(o):
                W.setdefault(k, []).append(car.verts(o))
    if len(W) < 4:
        raise SystemExit("not a rigged car: four SB_wheel groups wanted")
    wc = {k: np.vstack(v).mean(0) for k, v in W.items()}
    zf, zr = (wc["fl"][2] + wc["fr"][2]) / 2, (wc["rl"][2] + wc["rr"][2]) / 2
    T = np.vstack([car.tris(o)[0] for o in car.objs if car.nfaces(o) and "SB_wheel" not in o["chain"]])
    lo, hi = T.reshape(-1, 3).min(0), T.reshape(-1, 3).max(0)
    return {"front_axle_z": float(zf), "rear_axle_z": float(zr), "half_width": float((hi[0] - lo[0]) / 2),
            "roof_y": roof_of(dense_points(T, 0.03), zf, zr)}


def pick(car, m):
    """(prim index, triangle indices) of the cabin's pieces."""
    import rig
    zf, zr, half, roof = m["front_axle_z"], m["rear_axle_z"], m["half_width"], m["roof_y"]
    wb = zf - zr
    L = max(float(np.ptp(np.vstack([car.verts(o) for o in car.objs if car.nfaces(o)])[:, 2])), 1e-6)
    take = {}
    for o in car.objs:
        if not car.nfaces(o) or any(s in o["chain"] for s in NOT_CABIN):
            continue
        _, ms, _ = car.tris(o)
        for c in rig.islands(car, o, L):
            b0, b1 = c["lo"], c["hi"]
            if max(abs(b0[0]), abs(b1[0])) > .85 * half:
                continue                            # the doors' line and outward
            if b0[2] < zr - .15 or b1[2] > zf - .08 or b0[1] < .08:
                continue
            if b1[1] > .78 * roof:
                continue                            # follows this car's own glasshouse: the pillar
                                                    # trims, the mirror, the visors, the grab handles
            if b1[2] - b0[2] > .55 * wb and b1[0] - b0[0] > 1.2 * half:
                continue                            # a shell: the roof lining, the floor pan
            mi = int(np.bincount(np.maximum(ms[c["ix"]], 0)).argmax())
            mt = car.mats[mi] if mi < len(car.mats) else {}
            nm = mt.get("name", "")
            if "paint" in nm.lower() or mt.get("alphaMode") == "BLEND" or GLASS.search(nm):
                continue
            for si, t in c["refs"]:
                take.setdefault(o["segs"][si][0], []).append(t)
    return {pi: np.unique(np.array(t)) for pi, t in take.items()}


def extract(src, out, credit):
    import rig                                  # here, not at load: finish.py and rig.py borrow
    car = rig.Car(src)                          # dense_points and roof_of without the rigger
    m = measures(car)
    zmid = (m["front_axle_z"] + m["rear_axle_z"]) / 2
    sel = pick(car, m)
    g, j = car.g, car.g.j
    used = sorted({car.prims[pi]["mat"] for pi in sel if car.prims[pi]["mat"] is not None})
    mmap = {mi: k for k, mi in enumerate(used)}
    meshes, nodes, ntris = [], [], 0
    for pi, t in sorted(sel.items()):
        pr = car.prims[pi]
        p = pr["prim"]
        I = pr["I"][t]
        if pr["flip"]:
            I = I[:, ::-1]
        vids, inv = np.unique(I.ravel(), return_inverse=True)
        P = pr["P"][vids] - np.array([0.0, 0.0, zmid])
        attrs = {"POSITION": g.add_accessor(P.astype(np.float32), minmax=True, target=34962)}
        if "NORMAL" in p["attributes"]:
            N = g.accessor(p["attributes"]["NORMAL"])[vids] @ pr["Nm"].T
            N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
            attrs["NORMAL"] = g.add_accessor(N.astype(np.float32), target=34962)
        for an in sorted(a for a in p["attributes"] if a.startswith("TEXCOORD_")):
            attrs[an] = g.add_accessor(g.accessor(p["attributes"][an])[vids].astype(np.float32), target=34962)
        prim = {"attributes": attrs, "mode": 4, "indices": g.add_accessor(inv.ravel().astype(np.uint32), ctype=5125,
                                                               atype="SCALAR", target=34963)}
        if pr["mat"] is not None:
            prim["material"] = mmap[pr["mat"]]
        meshes.append({"name": f"cabin_{len(meshes)}", "primitives": [prim]})
        nodes.append({"name": f"cabin_{len(nodes)}", "mesh": len(meshes) - 1})
        ntris += len(I)
    # only the materials, textures and images the cabin uses
    mats = [dict(j["materials"][mi]) for mi in used]
    tex_used = sorted({v["index"] for mt in mats for v in _tex_refs(mt)})
    tmap = {ti: k for k, ti in enumerate(tex_used)}
    texs = [json.loads(json.dumps(j["textures"][ti])) for ti in tex_used]
    img_used = sorted({ref["source"] for t in texs for ref in _img_refs(t)})
    imap = {ii: k for k, ii in enumerate(img_used)}
    for t in texs:
        for ref in _img_refs(t):
            ref["source"] = imap[ref["source"]]
    for mt in mats:
        for v in _tex_refs(mt):
            v["index"] = tmap[v["index"]]
        mt["name"] = "cabin_" + mt.get("name", "")
    j["materials"], j["textures"] = mats, texs
    j["images"] = [j["images"][ii] for ii in img_used]
    if not j["textures"]:
        j.pop("textures", None), j.pop("images", None), j.pop("samplers", None)
    j["meshes"] = meshes
    j["nodes"] = nodes + [{"name": "cabin", "children": list(range(len(nodes)))}]
    j["scenes"], j["scene"] = [{"name": "cabin", "nodes": [len(nodes)]}], 0
    for k in ("animations", "skins", "cameras"):
        j.pop(k, None)
    info = dict(m, front_axle_z=m["front_axle_z"] - zmid, rear_axle_z=m["rear_axle_z"] - zmid,
                wheelbase=m["front_axle_z"] - m["rear_axle_z"], triangles=int(ntris), credit=credit)
    j.setdefault("asset", {})["extras"] = {"cabin_pack": info}
    if credit:
        j["asset"]["copyright"] = (f"Cabin: '{credit.get('title')}'" + (f" by {credit['author']}" if credit.get("author") else "")
                                   + f", {credit.get('licence')}" + (f", {credit['url']}" if credit.get("url") else ""))
    info["bytes"] = g.save(out)
    return info


def _img_refs(t):
    """A texture's image references: its own and its extensions' (a WebP or
    KTX2 image sits under EXT_texture_webp / KHR_texture_basisu)."""
    return ([t] if "source" in t else []) + [e for e in (t.get("extensions") or {}).values()
                                              if isinstance(e, dict) and "source" in e]


def _tex_refs(x):
    """Every {"index": …} texture reference inside a material."""
    out = []
    if isinstance(x, dict):
        for k, v in x.items():
            if isinstance(v, dict) and k.endswith("Texture") and "index" in v:
                out.append(v)
            out += _tex_refs(v)
    elif isinstance(x, list):
        for v in x:
            out += _tex_refs(v)
    return out


def info(path):
    """The pack's measures and credit (its extras)."""
    from gltf import GLTF  # noqa: E402
    return (GLTF(path).j.get("asset", {}).get("extras") or {}).get("cabin_pack") or {}


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(HERE, "..", "template"))
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    for k in ("title", "author", "licence", "url"):
        ap.add_argument("--" + k)
    a = ap.parse_args()
    print(json.dumps(extract(a.src, a.out, {k: getattr(a, k) for k in ("title", "author", "licence", "url")}), indent=1))
