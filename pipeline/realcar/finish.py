#!/usr/bin/env python3
"""finish.py — take a real catalogue car the rig machine has cut, and finish it
to the owner's standard: every door, the bonnet and the tailgate on hinges
with animation clips, clear glass, the cabin kept, and an engine bay and
exhaust under it. Pure Python (numpy, scipy); no Blender.

    python3 pipeline/realcar/finish.py RIGGED.glb SPEC.json OUT.glb

RIGGED.glb is platform/rigmachine/run.py's output: nodes named
SB_<part>__<n> (body, door_fl … door_rr, panel_bonnet, wheel_fl …) in the
rig frame (y up, nose +z, the car's left +x, ground y = 0).

SPEC.json:
    {"name": "Volkswagen Polo Mk6", "wheelbase": 2564,       # mm, optional
     "engine_pack": "engine_pack.glb",                        # optional
     "credit": "2023 Volkswagen Polo GTI by … (CC BY 4.0)"}   # optional, -> asset.copyright
Relative paths are taken from the spec file's folder.

What it does, in order:
1. Splits the body into islands (welded connected pieces). A modelled car's
   panels are separate pieces, so the bonnet and tailgate are found as
   pieces, not cut: the bonnet is the largest paint island lying flat over
   the front axle; the tailgate is the rear window plus every piece inside
   the box it and the panel under it span that sits on the car's rear skin.
   The rig machine's own bonnet or tailgate are used only if no piece fits.
2. Rescales to the published wheelbase, and centres the car on its
   wheelbase (x = 0 down the middle, ground y = 0).
3. Glass: every blended, colourless material is made clear (light, low
   alpha, glossy), so the cabin shows through. Lamp lenses keep their colour.
4. Engine: the pack (the workshop's petrol bay, exported in the Golf
   master's frame) goes in: the bay, engine, gearbox and front suspension
   scaled to the track about the front axle, the rear suspension and tank
   about the rear axle, and the exhaust stretched from the front pipe back
   to just inside the rear bumper.
5. Rig: each hinged part hangs from a pivot node on its hinge line, and the
   file carries glTF animation clips (door_fl_open … tailgate_open,
   doors_open, all_open).
"""
import json
import math
import os
import re
import sys

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.ndimage import gaussian_filter1d, median_filter
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "template"))
from gltf import GLTF  # noqa: E402

HINGED = {"door_fl": -65, "door_fr": 65, "door_rl": -65, "door_rr": 65, "bonnet": -55, "tailgate": 75}

# Where the engine pack sits in the Golf master's frame (measured from
# tmpl/master_golf.glb): front and rear axle z, ground y, tyre outer x.
PACK_FRAME = {"front_axle_z": 1.316, "rear_axle_z": -1.315, "ground_y": -0.013, "track_half": 0.875,
              "exhaust_front_z": 0.802, "exhaust_tail_z": -2.081}
PACK_REAR = {"bay:susp_rear", "bay:fuel_tank"}
PACK_EXHAUST = {"bay:exhaust_rear"}


def part_of(name):
    m = re.match(r"SB_(.+?)(__\d+)?$", name or "")
    return m.group(1) if m else "body"


def quat(axis, deg):
    a = math.radians(deg) / 2
    ax = np.array(axis, float)
    ax /= np.linalg.norm(ax)
    return [float(v) for v in ax * math.sin(a)] + [math.cos(a)]


def tri_area_normal(T):
    c = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    a = np.linalg.norm(c, axis=1)
    return a / 2, c / np.maximum(a, 1e-12)[:, None]


def islands(T, weld=2e-4):
    V = np.round(T.reshape(-1, 3) / weld).astype(np.int64)
    _, vid = np.unique(V, axis=0, return_inverse=True)
    vid = vid.reshape(-1, 3)
    nt = len(T)
    rows = np.repeat(np.arange(nt), 3)
    cols = vid.ravel() + nt
    n = nt + int(vid.max()) + 1
    A = coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(n, n))
    _, lab = connected_components(A, directed=False)
    return lab[:nt], vid


def surface_points(T, step=0.008):
    """Vertices plus points spread over each triangle about `step` apart, so a
    nearest-point query measures distance to the surface, not to corners."""
    a, _ = tri_area_normal(T)
    pts = [T.reshape(-1, 3)]
    k = np.clip(np.ceil(np.sqrt(a) / step), 1, 40).astype(int)
    for n in np.unique(k):
        if n < 2:
            continue
        sel = T[k == n]
        u, v = np.meshgrid(np.arange(n + 1), np.arange(n + 1))
        keep = (u + v) <= n
        u, v = u[keep] / n, v[keep] / n
        w = 1 - u - v
        P = (sel[:, None, 0] * w[None, :, None] + sel[:, None, 1] * u[None, :, None] + sel[:, None, 2] * v[None, :, None])
        pts.append(P.reshape(-1, 3))
    return np.vstack(pts)


def split_along(g, r, eligible, field, part):
    """Give `part` to the eligible triangles of record r inside field < 0, and
    split those the zero line crosses: new vertices on the crossed edges
    (every attribute interpolated), the lone corner's side one triangle, the
    other side two, winding kept. Returns how many were split."""
    P = r["P"]
    f = field(P)
    I = r["I"]
    neg = f[I] < 0
    cnt = neg.sum(1)
    tp = r["tri_part"].copy()
    tp[eligible & (cnt == 3)] = part
    mixed = np.where(eligible & (cnt > 0) & (cnt < 3))[0]
    if not len(mixed):
        r["tri_part"] = tp
        return 0
    attr = r.get("attr") or {an: g.accessor(ai) for an, ai in r["prim"]["attributes"].items()
                              if not an.startswith(("JOINTS", "WEIGHTS"))}
    newP, newA = [P], {an: [A] for an, A in attr.items()}
    nv = len(P)
    keepI, keepT = [I[np.setdiff1d(np.arange(len(I)), mixed)]], [tp[np.setdiff1d(np.arange(len(I)), mixed)]]
    addI, addT = [], []

    def lerp(a, b):
        nonlocal nv
        t = f[a] / (f[a] - f[b])
        newP.append(P[a] + t * (P[b] - P[a]))
        for an, A in attr.items():
            newA[an].append(A[a] + t * (A[b] - A[a]))
        nv += 1
        return nv - 1
    for ti in mixed:
        v = I[ti]
        sv = neg[ti]
        k = int(np.where(sv == (sv.sum() == 1))[0][0])     # the corner alone on its side
        a, b, c = v[k], v[(k + 1) % 3], v[(k + 2) % 3]
        pab, pac = lerp(a, b), lerp(a, c)
        lone_in = bool(sv[k])
        addI += [[a, pab, pac], [pab, b, c], [pab, c, pac]]
        addT += [part if lone_in else tp[ti], tp[ti] if lone_in else part, tp[ti] if lone_in else part]
    r["P"] = np.vstack([newP[0], np.array(newP[1:])])
    r["attr"] = {an: np.vstack([L[0], np.array(L[1:])]) for an, L in newA.items()}
    r["I"] = np.vstack(keepI + [np.array(addI, dtype=np.int64)])
    r["tri_part"] = np.concatenate(keepT + [np.array(addT, dtype=object)])
    return len(mixed)


def is_clear_glass(mat):
    if mat.get("alphaMode") != "BLEND":
        return False
    c = mat.get("pbrMetallicRoughness", {}).get("baseColorFactor", [1, 1, 1, 1])
    return max(c[:3]) - min(c[:3]) < 0.08          # colourless: windows, headlamp lenses


def finish(src, spec, out, base_dir="."):
    log = {"src": os.path.basename(src)}
    g = GLTF(src)
    j = g.j
    W, _ = g.world_matrices()

    # ── every primitive's triangles in world space, labelled by rig part ──
    recs = []
    for ni, n in enumerate(j["nodes"]):
        if "mesh" not in n:
            continue
        M = W[ni]
        for p in j["meshes"][n["mesh"]]["primitives"]:
            if p.get("mode", 4) != 4:
                continue
            P = g.accessor(p["attributes"]["POSITION"])
            P = P @ M[:3, :3].T + M[:3, 3]
            I = g.accessor(p["indices"]).ravel().astype(np.int64) if "indices" in p else np.arange(len(P))
            I = I[:len(I) // 3 * 3].reshape(-1, 3)
            recs.append({"node": ni, "M": M, "prim": p, "P": P, "I": I, "rig": part_of(n.get("name")),
                         "mat": p.get("material")})
    mats = j["materials"]

    def tris(r):
        return r["P"][r["I"]]

    # ── frame: wheels give the axles, the ground and the track ──
    wc = {}
    for r in recs:
        if r["rig"].startswith("wheel_"):
            wc.setdefault(r["rig"], []).append(r["P"])
    wb = {k: (np.vstack(v).min(0), np.vstack(v).max(0)) for k, v in wc.items()}
    cen = {k: (lo + hi) / 2 for k, (lo, hi) in wb.items()}
    zf = float(np.mean([cen[k][2] for k in cen if k[6] == "f"]))
    zr = float(np.mean([cen[k][2] for k in cen if k[6] == "r"]))
    ground = float(min(lo[1] for lo, _ in wb.values()))
    wheel_top = float(max(hi[1] for _, hi in wb.values()))
    track_half = float(max(max(abs(lo[0]), abs(hi[0])) for lo, hi in wb.values()))
    if zf < zr:
        raise SystemExit("front axle behind rear axle: rig frame not nose +z")
    base = zf - zr
    s = (spec["wheelbase"] / 1000.0) / base if spec.get("wheelbase") else 1.0
    zmid = (zf + zr) / 2
    log["measured"] = {"wheelbase_m": round(base, 3), "front_axle_z": round(zf, 3), "rear_axle_z": round(zr, 3),
                       "wheel_d_m": round(wheel_top - ground, 3), "track_half_m": round(track_half, 3)}
    log["rescale"] = round(s, 4)

    # ── body islands ──
    body = [r for r in recs if r["rig"] in ("body", "panel_bonnet", "tailgate", "glazing")]
    T = np.vstack([tris(r) for r in body])
    owner = np.concatenate([np.full(len(r["I"]), k) for k, r in enumerate(body)])
    tmat = np.concatenate([np.full(len(r["I"]), -1 if r["mat"] is None else r["mat"]) for r in body])
    lab, vid = islands(T)
    area, nrm = tri_area_normal(T)
    nl = lab.max() + 1
    isl_area = np.bincount(lab, weights=area, minlength=nl)
    lo = np.full((nl, 3), np.inf)
    hi = np.full((nl, 3), -np.inf)
    flat = T.reshape(-1, 3)
    lab3 = np.repeat(lab, 3)
    for k in range(3):
        np.minimum.at(lo[:, k], lab3, flat[:, k])
        np.maximum.at(hi[:, k], lab3, flat[:, k])
    cz = np.bincount(lab, weights=area * T[:, :, 2].mean(1), minlength=nl) / np.maximum(isl_area, 1e-12)
    up = np.bincount(lab, weights=area * np.abs(nrm[:, 1]), minlength=nl) / np.maximum(isl_area, 1e-12)
    nm = len(mats)
    mat_area = np.zeros((nl, nm + 1))
    np.add.at(mat_area, (lab, np.where(tmat < 0, nm, tmat)), area)
    dom = mat_area.argmax(1)

    # paint: the opaque material covering most of the doors
    door_area = np.zeros(nm + 1)
    for r in recs:
        if r["rig"].startswith("door_") and r["mat"] is not None:
            m = mats[r["mat"]]
            if m.get("alphaMode") == "BLEND" or m.get("name", "").startswith("SB_"):
                continue
            door_area[r["mat"]] += tri_area_normal(tris(r))[0].sum()
    paint = int(door_area.argmax())
    log["paint"] = mats[paint].get("name")
    glass = {i for i, m in enumerate(mats) if is_clear_glass(m)}

    label = np.array(["body"] * nl, dtype=object)

    # bonnet: the largest flat paint island over the front of the car
    cand = [i for i in range(nl) if dom[i] == paint and cz[i] > zf - 0.35 and up[i] > 0.5 and hi[i, 1] > wheel_top]
    bonnet = None
    if cand:
        b = max(cand, key=lambda i: isl_area[i])
        if isl_area[b] > 0.5:
            bonnet = b
            blo, bhi = lo[b] - 0.01, hi[b] + 0.01
            ymid = lo[b, 1] + 0.5 * (hi[b, 1] - lo[b, 1])
            for i in range(nl):
                if (lo[i] >= blo).all() and (hi[i] <= bhi).all() and lo[i, 1] > ymid:
                    label[i] = "bonnet"
            label[b] = "bonnet"
            log["bonnet"] = {"from": "island", "area_m2": round(float(isl_area[b]), 3),
                             "pieces": int((label == "bonnet").sum())}

    # bonnet cut: some models weld the bonnet into one shell with the wings
    # and have no shut line in the mesh at all. Then the bonnet is the shell's
    # top over the front: ahead of the windscreen's base (plus the cowl),
    # facing up (within ~50 degrees), above the wheels, and connected to the
    # middle of that area; it stops where the nose turns down to the grille
    # and where the wings turn down at the shoulders.
    cut = None
    if bonnet is None:
        shells = [i for i in range(nl) if dom[i] == paint and lo[i, 2] < zf < hi[i, 2] and hi[i, 1] > wheel_top]
        ws = [i for i in range(nl) if dom[i] in glass and cz[i] > (zf + zr) / 2 and lo[i, 1] > wheel_top]
        if shells and ws:
            sh = max(shells, key=lambda i: isl_area[i])
            w = max(ws, key=lambda i: isl_area[i])
            Wv = T[lab == w].reshape(-1, 3)
            z_rear = float(Wv[Wv[:, 1] < Wv[:, 1].min() + 0.03, 2].max()) + 0.06
            ts = np.where(lab == sh)[0]
            cen = T[ts].mean(1)
            ok = (cen[:, 2] > z_rear) & (np.abs(nrm[ts, 1]) > 0.65) & (cen[:, 1] > wheel_top + 0.1)
            sub = ts[ok]
            if len(sub):
                rows = np.repeat(np.arange(len(sub)), 3)
                cols = vid[sub].ravel()
                _, cv = np.unique(cols, return_inverse=True)
                n = len(sub) + cv.max() + 1
                A = coo_matrix((np.ones(len(rows)), (rows, cv + len(sub))), shape=(n, n))
                _, cl = connected_components(A, directed=False)
                cl = cl[:len(sub)]
                c2 = cen[ok]
                seed = np.argmin(np.abs(c2[:, 0]) + np.abs(c2[:, 2] - (z_rear + hi[sh, 2]) / 2))
                region = sub[cl == cl[seed]]
                # Cutting whole triangles leaves a staircase (a model's
                # triangles run long along the car). So the shut line is a
                # smooth curve: the region's half-width at each 1 cm along
                # the car (both sides averaged, median then Gaussian
                # smoothed), and the rear edge straight across at the cowl.
                # Triangles that cross it are split along it further down.
                rc = T[region].mean(1)
                zb = np.floor((rc[:, 2] - z_rear) / 0.01).astype(int)
                nb = int(zb.max()) + 1
                half = np.zeros(nb)
                for k in range(nb):
                    xs = rc[zb == k, 0]
                    if len(xs) > 3:
                        half[k] = (np.percentile(xs, 97) - np.percentile(xs, 3)) / 2
                filled = half > 0
                ra = area[region].sum()
                if filled.sum() > 5 and ra > 0.5:
                    half = np.interp(np.arange(nb), np.where(filled)[0], half[filled])
                    half = gaussian_filter1d(median_filter(half, 9, mode="nearest"), 4, mode="nearest") - 0.01
                    # the top skin only: not the shell's inner faces under it
                    cell = np.floor(cen[:, [0, 2]] / 0.02).astype(np.int64)
                    key = cell[:, 0] * 100000 + cell[:, 1]
                    uk, inv = np.unique(key, return_inverse=True)
                    top = np.full(len(uk), -np.inf)
                    np.maximum.at(top, inv, cen[:, 1])
                    on_top = cen[:, 1] > top[inv] - 0.04
                    ymin = wheel_top + 0.05

                    def field(P, z_rear=z_rear, half=half, nb=nb, ymin=ymin):
                        k = np.clip(np.floor((P[:, 2] - z_rear) / 0.01).astype(int), 0, nb - 1)
                        return np.maximum.reduce([np.abs(P[:, 0]) - half[k], z_rear - P[:, 2], ymin - P[:, 1]])
                    cut = {"tris": ts[on_top], "field": field}
                    bonnet = -1
                    log["bonnet"] = {"from": "cut from the body shell along a smoothed shut line",
                                     "rear_edge_z": round(z_rear, 3),
                                     "half_width_m": [round(float(half.min()), 3), round(float(half.max()), 3)]}

    # tailgate: the rear window, the panel under it, and what sits on that skin
    gl = [i for i in range(nl) if dom[i] in glass and cz[i] < zr and lo[i, 1] > wheel_top]
    if gl:
        rw = max(gl, key=lambda i: isl_area[i])
        xb = max(abs(lo[rw, 0]), abs(hi[rw, 0])) + 0.08
        zfront = hi[rw, 2] + 0.10
        under = [i for i in range(nl) if dom[i] == paint and abs(hi[i, 1] - lo[rw, 1]) < 0.04
                 and cz[i] < cz[rw] and max(abs(lo[i, 0]), abs(hi[i, 0])) < xb and isl_area[i] > 0.1]
        ybot = (min(lo[i, 1] for i in under) if under else lo[rw, 1] - 0.35) - 0.01
        # the car's rear skin: the rearmost surface at each (x, y), 1 cm cells
        pts = flat
        cell = np.floor(pts[:, :2] / 0.01).astype(np.int64)
        key = cell[:, 0] * 100000 + cell[:, 1]
        uk, inv = np.unique(key, return_inverse=True)
        back = np.full(len(uk), np.inf)
        np.minimum.at(back, inv, pts[:, 2])
        near = (pts[:, 2] - back[inv]) < 0.12
        near_share = np.bincount(lab3, weights=near.astype(float), minlength=nl) / np.maximum(
            np.bincount(lab3, minlength=nl), 1)
        inside = (np.abs(lo[:, 0]) <= xb) & (np.abs(hi[:, 0]) <= xb) & (lo[:, 1] >= ybot) & (hi[:, 2] <= zfront)
        tg = inside & (near_share > 0.5)
        # the window pane can be modelled twice (outer and inner face): both go
        tg |= inside & np.isin(dom, list(glass))
        tg &= label == "body"
        label[tg] = "tailgate"
        log["tailgate"] = {"from": "islands", "rear_window_m2": round(float(isl_area[rw]), 3),
                           "box": {"x_half": round(float(xb), 3), "y_bottom": round(float(ybot), 3),
                                   "z_front": round(float(zfront), 3)},
                           "pieces": int(tg.sum())}

    # no tailgate found here: the rig machine's tailgate stands, as the islands
    # mostly made of its triangles
    if "tailgate" not in log:
        rig_tg = np.concatenate([np.full(len(r["I"]), r["rig"] == "tailgate") for r in body])
        if rig_tg.any():
            share = np.bincount(lab, weights=rig_tg.astype(float), minlength=nl) / np.maximum(
                np.bincount(lab, minlength=nl), 1)
            label[(share > 0.5) & (label == "body")] = "tailgate"
            log["tailgate"] = {"from": "rig", "pieces": int((label == "tailgate").sum())}

    # door trims: window frames, belt mouldings and mirrors modelled as their
    # own small pieces are left on the body by the rig's door cut and float in
    # the air when the door opens. A piece inside a door's box, above the
    # wheels, that touches the door (within 1 cm of its surface) goes with it;
    # a seat or a brake inside the same box does not touch it.
    # The tailgate takes what touches it the same way (a rear window modelled
    # in a dark plastic rather than glass, the inner lamps).
    doors = {}
    for r in recs:
        if r["rig"].startswith("door_"):
            doors.setdefault(r["rig"], []).append(tris(r))
    if (label == "tailgate").any():
        doors["tailgate"] = [T[label[lab] == "tailgate"]]
    trims = {}
    if doors:
        trees = {}
        for d, ts in doors.items():
            Td = np.vstack(ts)
            trees[d] = (cKDTree(surface_points(Td)), Td.reshape(-1, 3).min(0) - 0.015, Td.reshape(-1, 3).max(0) + 0.015)
        cand = [i for i in range(nl) if label[i] == "body" and lo[i, 1] > 0.9 * wheel_top and isl_area[i] < 1.5]
        verts_of = {}
        order = np.argsort(lab3, kind="stable")
        bounds = np.searchsorted(lab3[order], np.arange(nl + 1))
        for i in cand:
            best = None
            for d, (tree, dlo, dhi) in trees.items():
                if (lo[i] >= dlo).all() and (hi[i] <= dhi).all() and (d == "tailgate" or isl_area[i] < 0.2):
                    if i not in verts_of:
                        verts_of[i] = flat[order[bounds[i]:bounds[i + 1]]]
                    dist = tree.query(verts_of[i], k=1)[0].min()
                    if dist < 0.01 and (best is None or dist < best[1]):
                        best = (d, dist)
            if best:
                label[i] = "trim:" + best[0]
                trims[best[0]] = trims.get(best[0], 0) + 1
        log["door_trims"] = trims

    # every triangle's final part
    tri_part = label[lab]
    tri_part = np.array([p[5:] if p.startswith("trim:") else p for p in tri_part], dtype=object)
    off = 0
    for r in body:
        n = len(r["I"])
        tp = tri_part[off:off + n]
        # the rig machine's own bonnet or tailgate stand only where no piece
        # was found for that part here
        if r["rig"] == "panel_bonnet":
            tp = np.where(tp == "body", "bonnet" if bonnet is None else "body", tp)
        if r["rig"] == "tailgate":
            pass                                    # handled as islands above
        r["tri_part"] = tp
        off += n
    for r in recs:
        if "tri_part" not in r:
            r["tri_part"] = np.full(len(r["I"]), r["rig"], dtype=object)

    # the bonnet cut: shell triangles inside the shut line go to the bonnet,
    # and those crossing it are split along it
    if cut is not None:
        eligible = np.zeros(len(T), bool)
        eligible[cut["tris"]] = True
        off, nsplit = 0, 0
        for r in body:
            n = len(r["I"])
            el = eligible[off:off + n]
            off += n
            if el.any():
                nsplit += split_along(g, r, el, cut["field"], "bonnet")
        parts_area = sum(tri_area_normal(r["P"][r["I"][r["tri_part"] == "bonnet"]])[0].sum() for r in body)
        log["bonnet"].update({"area_m2": round(float(parts_area), 3), "triangles_split": nsplit})

    # ── output frame: centred on the wheelbase, scaled to the published one ──
    def to_out(P):
        Q = (P - np.array([0.0, ground, zmid])) * s
        return Q

    # ── rebuild meshes, one per part, primitives kept per source material ──
    by_part = {}
    for r in recs:
        p = r["prim"]
        Rm = r["M"][:3, :3]
        Nm = np.linalg.inv(Rm).T
        for part in np.unique(r["tri_part"]):
            sel = r["I"][r["tri_part"] == part]
            uniq, inv = np.unique(sel.ravel(), return_inverse=True)
            attrs = {}
            for an, ai in p["attributes"].items():
                A = (r["attr"][an] if "attr" in r else g.accessor(ai))[uniq]
                if an == "POSITION":
                    A = to_out(r["P"][uniq])
                    attrs[an] = g.add_accessor(A, minmax=True, target=34962)
                    continue
                if an == "NORMAL":
                    A = A @ Nm.T
                    A /= np.maximum(np.linalg.norm(A, axis=1, keepdims=True), 1e-12)
                elif an == "TANGENT":
                    t3 = A[:, :3] @ Rm.T
                    t3 /= np.maximum(np.linalg.norm(t3, axis=1, keepdims=True), 1e-12)
                    A = np.c_[t3, A[:, 3:4] * np.sign(np.linalg.det(Rm))]
                if an.startswith("JOINTS") or an.startswith("WEIGHTS"):
                    continue
                attrs[an] = g.add_accessor(A, target=34962)
            prim = {"attributes": attrs, "mode": 4,
                    "indices": g.add_accessor(inv.astype(np.uint32), ctype=5125, atype="SCALAR", target=34963)}
            if r["mat"] is not None:
                prim["material"] = r["mat"]
            by_part.setdefault(str(part), []).append(prim)

    rename = {"panel_bonnet": "bonnet"}
    meshes, nodes = [], [{"name": spec.get("name") or "car", "children": []}]
    pivots = {}
    for part in sorted(by_part):
        pname = rename.get(part, part)
        meshes.append({"name": pname, "primitives": by_part[part]})
        mi = len(meshes) - 1
        if pname in HINGED:
            V = np.vstack([g.accessor(pr["attributes"]["POSITION"]) for pr in by_part[part]])
            plo, phi = V.min(0), V.max(0)
            if pname.startswith("door"):
                left = (plo[0] + phi[0]) / 2 > 0
                piv = [float(phi[0] - 0.03 if left else plo[0] + 0.03), float((plo[1] + phi[1]) / 2), float(phi[2] - 0.03)]
                axis = [0, 1, 0]
            elif pname == "tailgate":
                piv, axis = [0.0, float(phi[1] - 0.01), float(phi[2] - 0.01)], [1, 0, 0]
            else:
                piv, axis = [0.0, float(phi[1] - 0.01), float(plo[2] + 0.02)], [1, 0, 0]
            hv = len(nodes)
            nodes.append({"name": pname + "_hinge", "translation": piv, "children": [hv + 1],
                          "extras": {"axis": axis, "open_deg": HINGED[pname]}})
            nodes.append({"name": pname, "translation": [-c for c in piv], "mesh": mi})
            nodes[0]["children"].append(hv)
            pivots[pname] = (hv, axis, HINGED[pname])
        else:
            nodes.append({"name": pname, "mesh": mi})
            nodes[0]["children"].append(len(nodes) - 1)
    j["meshes"] = meshes
    j["nodes"] = nodes
    log["parts"] = {rename.get(k, k): int(sum(j["accessors"][pr["indices"]]["count"] // 3 for pr in v))
                    for k, v in by_part.items()}
    log["opens"] = sorted(pivots)
    log["missing"] = sorted(set(HINGED) - set(pivots))

    # ── engine pack ──
    if spec.get("engine_pack"):
        pack = GLTF(spec["engine_pack"])
        F = PACK_FRAME
        # strays: a piece reaching below the ground is a workshop leftover
        # (a 1 cm stick at the workshop origin), not a car part
        PW, _ = pack.world_matrices()
        stray = []
        for i, n in enumerate(pack.j["nodes"]):
            if "mesh" in n:
                ys = [(pack.accessor(p["attributes"]["POSITION"]) @ PW[i][:3, :3].T + PW[i][:3, 3])[:, 1].min()
                      for p in pack.j["meshes"][n["mesh"]]["primitives"]]
                if min(ys) < F["ground_y"] - 0.02:
                    stray.append(i)
        n0 = len(j["nodes"])
        proots = g.append(pack)
        for i in stray:
            j["nodes"][n0 + i].pop("mesh", None)
        se = track_half * s / F["track_half"]
        zf_o, zr_o = (zf - zmid) * s, (zr - zmid) * s

        def mat4(A, t):
            M = np.eye(4)
            M[:3, :3] = np.diag(A)
            M[:3, 3] = t
            return [float(v) for v in M.T.ravel()]

        def anchored(z_from, z_to):
            A = np.array([se, se, se])
            return mat4(A, np.array([0.0, 0.0, z_to]) - A * np.array([0.0, F["ground_y"], z_from]))
        front = anchored(F["front_axle_z"], zf_o)
        rear = anchored(F["rear_axle_z"], zr_o)
        # exhaust: from where the front pipe hands over to 10 cm inside the tail
        tail_o = (float(min(lo[:, 2])) - zmid) * s
        z1 = se * (F["exhaust_front_z"] - F["front_axle_z"]) + zf_o
        z2 = tail_o + 0.10
        az = (z1 - z2) / (F["exhaust_front_z"] - F["exhaust_tail_z"])
        A = np.array([se, se, az])
        exhaust = mat4(A, np.array([0.0, -se * F["ground_y"], z1 - az * F["exhaust_front_z"]]))
        wrap = {"engine_bay": front, "rear_running_gear": rear, "exhaust": exhaust}
        widx = {}
        for k, M in wrap.items():
            widx[k] = len(j["nodes"])
            j["nodes"].append({"name": k, "matrix": M, "children": []})
            nodes[0]["children"].append(widx[k])
        for r0 in proots:
            for c in j["nodes"][r0].get("children", [r0]):
                nmx = j["nodes"][c].get("name", "")
                k = "exhaust" if nmx in PACK_EXHAUST else "rear_running_gear" if nmx in PACK_REAR else "engine_bay"
                j["nodes"][widx[k]]["children"].append(c)
            j["nodes"][r0].pop("children", None)     # a node has one parent
        log["engine_pack"] = {"file": os.path.basename(spec["engine_pack"]), "scale": round(se, 4),
                              "exhaust_stretch": round(az / se, 4), "strays_dropped": len(stray)}

    j["scenes"] = [{"name": spec.get("name") or "car", "nodes": [0]}]
    j["scene"] = 0

    # ── clear glass ──
    cleared = []
    for i in glass:
        m = mats[i]
        pbr = m.setdefault("pbrMetallicRoughness", {})
        pbr.pop("baseColorTexture", None)
        pbr["baseColorFactor"] = [0.86, 0.9, 0.92, 0.14]
        pbr["metallicFactor"] = 0.0
        pbr["roughnessFactor"] = 0.04
        m["doubleSided"] = True
        cleared.append(m.get("name"))
    log["glass_cleared"] = cleared

    # ── animation clips ──
    tin = g.add_accessor(np.array([0.0, 1.0]), minmax=True)
    clips = {}
    for part, (hv, axis, deg) in pivots.items():
        q = g.add_accessor(np.array([[0, 0, 0, 1], quat(axis, deg)]))
        clips.setdefault(part + "_open", []).append((hv, q))
        if part.startswith("door"):
            clips.setdefault("doors_open", []).append((hv, q))
        clips.setdefault("all_open", []).append((hv, q))
    j["animations"] = [{"name": nm_, "samplers": [{"input": tin, "output": q, "interpolation": "LINEAR"} for _, q in ch],
                        "channels": [{"sampler": i, "target": {"node": pv, "path": "rotation"}}
                                     for i, (pv, _) in enumerate(ch)]}
                       for nm_, ch in clips.items()]
    if spec.get("credit"):
        j.setdefault("asset", {})["copyright"] = spec["credit"]
    j.setdefault("asset", {}).setdefault("extras", {})["realcar_finish"] = log
    log["bytes"] = g.save(out)
    return log


if __name__ == "__main__":
    src, spec_p, out = sys.argv[1:4]
    spec = json.load(open(spec_p))
    d = os.path.dirname(os.path.abspath(spec_p))
    if spec.get("engine_pack") and not os.path.isabs(spec["engine_pack"]):
        spec["engine_pack"] = os.path.join(d, spec["engine_pack"])
    print(json.dumps(finish(src, spec, out, d), indent=1, default=float))
