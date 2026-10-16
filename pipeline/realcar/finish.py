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
    return lab[:nt]


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
    body = [r for r in recs if r["rig"] in ("body", "panel_bonnet", "tailgate")]
    T = np.vstack([tris(r) for r in body])
    owner = np.concatenate([np.full(len(r["I"]), k) for k, r in enumerate(body)])
    tmat = np.concatenate([np.full(len(r["I"]), -1 if r["mat"] is None else r["mat"]) for r in body])
    lab = islands(T)
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

    # door trims: window frames, belt mouldings and mirrors modelled as their
    # own small pieces are left on the body by the rig's door cut and float in
    # the air when the door opens. A piece inside a door's box, above the
    # wheels, that touches the door (within 1 cm of its surface) goes with it;
    # a seat or a brake inside the same box does not touch it.
    doors = {}
    for r in recs:
        if r["rig"].startswith("door_"):
            doors.setdefault(r["rig"], []).append(tris(r))
    trims = {}
    if doors:
        trees = {}
        for d, ts in doors.items():
            Td = np.vstack(ts)
            trees[d] = (cKDTree(surface_points(Td)), Td.reshape(-1, 3).min(0) - 0.015, Td.reshape(-1, 3).max(0) + 0.015)
        cand = [i for i in range(nl) if label[i] == "body" and lo[i, 1] > 0.9 * wheel_top and isl_area[i] < 0.2]
        verts_of = {}
        order = np.argsort(lab3, kind="stable")
        bounds = np.searchsorted(lab3[order], np.arange(nl + 1))
        for i in cand:
            best = None
            for d, (tree, dlo, dhi) in trees.items():
                if (lo[i] >= dlo).all() and (hi[i] <= dhi).all():
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
        if r["rig"] == "panel_bonnet":
            tp = np.where(tp == "body", "bonnet" if bonnet is None else "body", tp)
        r["tri_part"] = tp
        off += n
    for r in recs:
        if "tri_part" not in r:
            r["tri_part"] = np.full(len(r["I"]), r["rig"], dtype=object)

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
                A = g.accessor(ai)[uniq]
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
