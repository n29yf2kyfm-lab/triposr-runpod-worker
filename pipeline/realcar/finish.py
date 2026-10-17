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
     "credit": "2023 Volkswagen Polo GTI by … (CC BY 4.0)",   # optional, -> asset.copyright
     "paint": [20, 20, 22],                                   # optional, sRGB 0-255
     "keep_native_engine": false,                             # optional: keep a model's own bay
     "manual": ["bonnet", "door_fl"],                         # optional: parts set by hand in the
                                                              # Studio (edits.py): taken as they are
     "hinges": {"bonnet": {"edge": "front", "deg": 50}}}      # optional: hinge edge and angle
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
4. Engine: one generic engine in every car. The middle of the model's own
   bay is cleared (a tub, flat sheets or a rough engine), then the pack (the
   workshop's petrol bay, exported in the Golf master's frame) goes in: the bay, engine, gearbox and front suspension
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
from scipy.ndimage import binary_closing, gaussian_filter1d, median_filter
from scipy.ndimage import label as ndi_label
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "template"))
from gltf import GLTF  # noqa: E402

HINGED = {"door_fl": -65, "door_fr": 65, "door_rl": -65, "door_rr": 65, "bonnet": -55, "tailgate": 75}

# Where the engine pack sits in the Golf master's frame (measured from
# tmpl/master_golf.glb): front and rear axle z, ground y, tyre outer x.
PACK_FRAME = {"front_axle_z": 1.316, "rear_axle_z": -1.315, "ground_y": -0.013, "track_half": 0.875, "body_half": 0.894, "bonnet_half": 0.794,
              "exhaust_front_z": 0.802, "exhaust_tail_z": -2.081}
PACK_REAR = {"bay:susp_rear", "bay:fuel_tank"}
PACK_EXHAUST = {"bay:exhaust_rear"}


def hinge_line(part, plo, phi, edge=None, deg=None):
    """Pivot, axis and opening angle for a hinged part, from its box (the
    Studio draws the same line). Doors: front edge (or rear, a rear-hinged
    door); bonnet: rear edge (or front); tailgate: top edge (or bottom: a
    drop-down tail; left / right: side-hinged)."""
    deg = abs(float(deg)) if deg else abs(HINGED[part])
    if part.startswith("door"):
        left = (plo[0] + phi[0]) / 2 > 0
        x = float(phi[0] - 0.03 if left else plo[0] + 0.03)
        if edge == "rear":
            return [x, float((plo[1] + phi[1]) / 2), float(plo[2] + 0.03)], [0, 1, 0], deg if left else -deg
        return [x, float((plo[1] + phi[1]) / 2), float(phi[2] - 0.03)], [0, 1, 0], -deg if left else deg
    if part == "tailgate":
        if edge == "bottom":
            return [0.0, float(plo[1] + 0.01), float(plo[2] + 0.01)], [1, 0, 0], -deg
        if edge in ("left", "right"):
            x = float(phi[0] - 0.02 if edge == "left" else plo[0] + 0.02)
            return [x, float((plo[1] + phi[1]) / 2), float(plo[2] + 0.02)], [0, 1, 0], -deg if edge == "left" else deg
        return [0.0, float(phi[1] - 0.01), float(phi[2] - 0.01)], [1, 0, 0], deg
    if edge == "front":
        return [0.0, float(phi[1] - 0.01), float(phi[2] - 0.02)], [1, 0, 0], deg
    return [0.0, float(phi[1] - 0.01), float(plo[2] + 0.02)], [1, 0, 0], -deg


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
    kept = np.setdiff1d(np.arange(len(I)), mixed)
    keepI, keepT = [I[kept]], [tp[kept]]
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
    for k, fl in r.get("flags", {}).items():     # other cuts' marks follow their triangles
        r["flags"][k] = np.concatenate([fl[kept], np.repeat(fl[mixed], 3)])
    return len(mixed)


def skin(cen, pts, axes, sign, depth, cell=0.03):
    """Which triangles (centroids `cen`) lie within `depth` of the outermost
    surface of `pts`, looking along the axis not in `axes`: sign +1 the
    highest (a bonnet's top), -1 the lowest (a tailgate's rear, nose +z)."""
    ax = 3 - sum(axes)
    pts = np.vstack([pts, cen])                 # a cell can hold a triangle's centre and none of its corners
    k = lambda P: np.floor(P[:, list(axes)] / cell).astype(np.int64) @ np.array([100000, 1])  # noqa: E731
    kp = k(pts)
    uk, inv = np.unique(kp, return_inverse=True)
    ext = np.full(len(uk), -np.inf)
    np.maximum.at(ext, inv, sign * pts[:, ax])
    kc = k(cen)
    ix = np.clip(np.searchsorted(uk, kc), 0, len(uk) - 1)
    return (uk[ix] == kc) & (sign * cen[:, ax] > ext[ix] - depth)


def is_clear_glass(mat):
    if mat.get("alphaMode") != "BLEND":
        return False
    c = mat.get("pbrMetallicRoughness", {}).get("baseColorFactor", [1, 1, 1, 1])
    # see-through (alpha well under 1) and colourless: windows, headlamp
    # lenses; not a blended decal or stitching texture at full alpha
    return c[3] < 0.7 and max(c[:3]) - min(c[:3]) < 0.08


def _normal_maps(m):
    """The texture slots of a material that need a tangent space."""
    out = []
    if "normalTexture" in m:
        out.append((m, "normalTexture"))
    cc = m.get("extensions", {}).get("KHR_materials_clearcoat") or {}
    if "clearcoatNormalTexture" in cc:
        out.append((cc, "clearcoatNormalTexture"))
    return out


def ensure_tangents(g):
    """Every primitive whose material needs a tangent space (a normal map, a
    clear coat's normal map) gets tangents of its own, from its texture
    coordinates: the source models seldom carry them, and a viewer left to
    make its own may differ from another (glTF validator, a warning; an
    error where the only normal map is the clear coat's). With no texture
    coordinates the map cannot apply, and is dropped. Returns counts."""
    mats = g.j.get("materials", [])
    made = dropped = 0
    for mesh in g.j.get("meshes", []):
        for p in mesh["primitives"]:
            if p.get("material") is None or "TANGENT" in p["attributes"]:
                continue
            slots = _normal_maps(mats[p["material"]])
            if not slots:
                continue
            a = p["attributes"]
            uv = f"TEXCOORD_{slots[0][0][slots[0][1]].get('texCoord', 0)}"
            if not all(k in a for k in ("POSITION", "NORMAL", uv)):
                for holder, key in slots:
                    holder.pop(key, None)
                dropped += 1
                continue
            P, N, UV = g.accessor(a["POSITION"]), g.accessor(a["NORMAL"]), g.accessor(a[uv])
            I = g.accessor(p["indices"]).reshape(-1, 3).astype(np.int64) if "indices" in p \
                else np.arange(len(P)).reshape(-1, 3)
            e1, e2 = P[I[:, 1]] - P[I[:, 0]], P[I[:, 2]] - P[I[:, 0]]
            d1, d2 = UV[I[:, 1]] - UV[I[:, 0]], UV[I[:, 2]] - UV[I[:, 0]]
            r = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
            r = np.where(np.abs(r) < 1e-12, 1e-12, r)
            t = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) / r[:, None]
            bt = (e2 * d1[:, 0:1] - e1 * d2[:, 0:1]) / r[:, None]
            T, B = np.zeros_like(P), np.zeros_like(P)
            for k in range(3):
                np.add.at(T, I[:, k], t)
                np.add.at(B, I[:, k], bt)
            n = N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
            T = T - n * (T * n).sum(1, keepdims=True)                 # Gram-Schmidt against the normal
            bad = np.linalg.norm(T, axis=1) < 1e-9                       # no texture gradient: any tangent
            T[bad] = np.cross(n, np.where(np.abs(n[:, :1]) < 0.9, [[1.0, 0, 0]], [[0, 1.0, 0]]))[bad]
            T = T / np.maximum(np.linalg.norm(T, axis=1, keepdims=True), 1e-12)
            w = np.where((np.cross(n, T) * B).sum(1) < 0, -1.0, 1.0)
            a["TANGENT"] = g.add_accessor(np.c_[T, w].astype(np.float32), atype="VEC4")
            made += 1
    return {"made": made, "maps_dropped": dropped}


def finish(src, spec, out, base_dir="."):
    log = {"src": os.path.basename(src)}
    # parts a person set by hand in the Studio stand as they are: no search,
    # no cut, no trims added
    manual = set(spec.get("manual") or [])
    if manual:
        log["manual"] = sorted(manual)
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
    wb_mm = spec.get("wheelbase")
    if callable(wb_mm):
        # looked up on demand: the model's own wheelbase-to-length proportion
        # tells two generations on sale the same year apart
        body_z = [r["P"][:, 2] for r in recs if not r["rig"].startswith("wheel_")]
        length = float(max(z.max() for z in body_z) - min(z.min() for z in body_z))
        wb_mm, log["wheelbase_lookup"] = wb_mm(base / length if length else None, base)
    s = (wb_mm / 1000.0) / base if wb_mm else 1.0
    zmid = (zf + zr) / 2
    log["measured"] = {"wheelbase_m": round(base, 3), "front_axle_z": round(zf, 3), "rear_axle_z": round(zr, 3),
                       "wheel_d_m": round(wheel_top - ground, 3), "track_half_m": round(track_half, 3)}
    log["rescale"] = round(s, 4)

    # ── body islands ──
    # everything but the doors and wheels: the rig machine may file the body
    # shell under "cabin" or "lamps_rear", and its tailgate may be the boot floor
    body = [r for r in recs if not r["rig"].startswith(("door_", "wheel_"))]
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

    # paint: the opaque material covering most of the car's outer side skin
    # between the axles, from the wheel tops to the waist (doors and body
    # alike, so a rig that found one door still gets it right). Counting
    # whole doors picked their insides: the Mini's "DoorPanels", the Jazz's
    # "dash paint", the 500e's "Interior_paint".
    door_area = np.zeros(nm + 1)
    side = [r for r in recs if not r["rig"].startswith("wheel_") and r["mat"] is not None
            and mats[r["mat"]].get("alphaMode") != "BLEND" and not mats[r["mat"]].get("name", "").startswith("SB_")]
    if side:
        Ts = np.vstack([tris(r) for r in side])
        ms = np.concatenate([np.full(len(r["I"]), r["mat"]) for r in side])
        a_, n_ = tri_area_normal(Ts)
        c_ = Ts.mean(1)
        cab = np.c_[np.abs(c_[:, 0]), c_[:, 1:]]
        pab = Ts.reshape(-1, 3).copy()
        pab[:, 0] = np.abs(pab[:, 0])             # both sides as one
        waist_ = ground + 1.35 * (wheel_top - ground)
        sk = skin(cab, pab, (1, 2), 1, 0.03) & (n_[:, 0] * np.sign(c_[:, 0]) > 0.3) \
            & (c_[:, 1] > ground + 0.9 * (wheel_top - ground)) & (c_[:, 1] < waist_ + 0.1) \
            & (c_[:, 2] > zr) & (c_[:, 2] < zf)
        w_ = np.array([0.5 if re.search(r"int(erior)?\b|int\.|seat|leather|fabric|carpet|cloth", m.get("name", ""), re.I)
                       else 1.0 for m in mats] + [1.0])
        np.add.at(door_area, ms[sk], a_[sk] * w_[ms[sk]])
    paint = int(door_area.argmax())
    log["paint"] = mats[paint].get("name")
    paint_ids = {i for i, m in enumerate(mats) if m.get("name") == mats[paint].get("name")}
    glass = {i for i, m in enumerate(mats) if is_clear_glass(m)}
    # Windows modelled as opaque black (a dark paint with a glass name, the
    # A45's "glass2") hide the cabin. A colourless material named as glass,
    # not a lamp's, with over half a square metre above the waist: a window.
    waist = ground + 1.35 * (wheel_top - ground)
    for i, m in enumerate(mats):
        if i in glass or not re.search(r"glass|window|windscreen|vidr|vidro|scheibe|glas\b", m.get("name", ""), re.I) \
                or re.search(r"light|lamp|head|tail|back|indic|refl|mirror|lens", m.get("name", ""), re.I):
            continue
        c = m.get("pbrMetallicRoughness", {}).get("baseColorFactor", [1, 1, 1, 1])
        if max(c[:3]) - min(c[:3]) > 0.08:
            continue
        up_area = sum(float(tri_area_normal(tris(r)[tris(r).mean(1)[:, 1] > waist])[0].sum())
                      for r in recs if r["mat"] == i)
        if up_area > 0.5:
            glass.add(i)
            m["alphaMode"] = "BLEND"

    label = np.array(["body"] * nl, dtype=object)
    glass_m2 = mat_area[:, sorted(glass)].sum(1) if glass else np.zeros(nl)

    # bonnet: the largest flat paint island over the front of the car
    cand = [i for i in range(nl) if dom[i] == paint and cz[i] > zf - 0.35 and up[i] > 0.5 and hi[i, 1] > wheel_top]
    if "bonnet" in manual:
        cand = []
        log["bonnet"] = {"from": "the Studio"}
    bonnet = clip = None
    if cand:
        b = max(cand, key=lambda i: isl_area[i])
        # a front clip, not a bonnet: the piece runs down the car's sides past
        # the tops of the wheels behind the front axle (the wings welded to
        # it, the Kamiq). Then it is cut along its shoulders like a welded
        # shell, below. A bonnet's front corners may dip over the lamps (the
        # Superb's); its sides behind the axle never come down that far.
        tb = T[lab == b].reshape(-1, 3)
        xc, xw = (lo[b, 0] + hi[b, 0]) / 2, hi[b, 0] - lo[b, 0]
        flank = tb[(np.abs(tb[:, 0] - xc) > 0.4 * xw) & (tb[:, 2] < zf - 0.1)]
        if len(flank) and float(flank[:, 1].min()) < wheel_top - 0.05 and xw > 1.2 * track_half:
            log["bonnet_island_is_front_clip"] = {"area_m2": round(float(isl_area[b]), 3),
                                                  "flank_low_y": round(float(flank[:, 1].min()), 3),
                                                  "wheel_top": round(float(wheel_top), 3)}
            clip, cand = b, []
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
    cuts = []                                  # (part, triangle indices, field)
    if bonnet is None and "bonnet" not in manual:
        # a welded piece can mix materials (the shell with its trims), so the
        # shell is the piece with the most paint, and only its paint is cut
        shells = [i for i in range(nl) if mat_area[i, paint] > 0.5 and lo[i, 2] < zf < hi[i, 2] and hi[i, 1] > wheel_top]
        # a window is the piece with the most glass, not only one that is
        # mostly glass: the A3's windscreen is welded to its black frame
        tri_c = T.mean(1)
        waist_ = ground + 1.35 * (wheel_top - ground)
        # a tinted windscreen is not cleared, but it is still the windscreen (the Kamiq's)
        # (and a lamp's glass is never the windscreen, though it is cleared too)
        named_glass = {i for i in glass | {i for i, m in enumerate(mats)
                                           if re.search(r"glass|window|windscreen|windshield|vidr|vidro|scheibe|glas\b",
                                                        m.get("name", ""), re.I)}
                       if not re.search(r"light|lamp|head|tail|indic|refl|mirror|lens|trim|frame|seal|rubber",
                                        mats[i].get("name", ""), re.I)}
        gfront = np.isin(tmat, list(named_glass)) & (tri_c[:, 2] > (zf + zr) / 2) & (tri_c[:, 1] > waist_) \
            & (np.abs(nrm[:, 2]) > 0.2)               # facing forward: the windscreen, not side glass
        ws = [0] if area[gfront].sum() > 0.3 else []
        Wv = T[gfront].reshape(-1, 3) if ws else None
        big = int(np.argmax(isl_area))
        log["bonnet_search"] = {"shells": len(shells), "windscreens": len(ws),
                                "largest_piece": {"m2": round(float(isl_area[big]), 2), "material": (mats[dom[big]].get("name") if dom[big] < nm else None),
                                                  "z": [round(float(lo[big, 2]), 2), round(float(hi[big, 2]), 2)], "top_y": round(float(hi[big, 1]), 2)}}
        if shells and ws:
            sh = max(shells, key=lambda i: mat_area[i, paint])
            # the windscreen's own triangles, wherever the model put them
            # (the A3's and 500e's sit inside one piece with the whole shell)
            z_rear = float(Wv[Wv[:, 1] < Wv[:, 1].min() + 0.03, 2].max()) + 0.06
            # All the paint, not one piece's: a model's paint can come in many
            # pieces (the Golf R's bonnet is spread over several), and a cut
            # of one leaves the rest of the panel shut.
            ts = np.where(tmat == paint)[0]
            cen = T[ts].mean(1)
            ok = (cen[:, 2] > z_rear) & (np.abs(nrm[ts, 1]) > 0.5) & (cen[:, 1] > wheel_top + 0.1)
            sub = ts[ok]
            if len(sub):
                # connected on a top-down grid, so pieces that touch without
                # sharing vertices still count as one surface; the grid is as
                # coarse as the model's triangles (the A3's are 5 cm across,
                # and on a 2 cm grid its bonnet fell apart into strips)
                c2 = cen[ok]
                gcell = float(np.clip(1.2 * np.sqrt(np.median(area[sub])), 0.02, 0.08))
                gx = np.floor(c2[:, 0] / gcell).astype(int)
                gz = np.floor(c2[:, 2] / gcell).astype(int)
                grid = np.zeros((gx.max() - gx.min() + 3, gz.max() - gz.min() + 3), bool)
                grid[gx - gx.min() + 1, gz - gz.min() + 1] = True
                gl_, _ = ndi_label(binary_closing(grid, np.ones((3, 3))))
                # the seed: on the centre line, half way from the windscreen to
                # the front of the paint that faces up (the shell's own front
                # when the bonnet is a piece of its own, the Kamiq's clip)
                seed = np.argmin(np.abs(c2[:, 0]) + np.abs(c2[:, 2] - (z_rear + min(hi[sh, 2], c2[:, 2].max())) / 2)
                                 if hi[sh, 2] > z_rear + 0.2 else
                                 np.abs(c2[:, 0]) + np.abs(c2[:, 2] - (z_rear + c2[:, 2].max()) / 2))
                cl = gl_[gx - gx.min() + 1, gz - gz.min() + 1]
                region = sub[cl == cl[seed]]
                if clip is not None:                   # the clip's own top, its wings left on the body
                    own = sub[lab[sub] == clip]
                    if area[own].sum() > area[region].sum():
                        region = own
                log["bonnet_search"].update({"facing_up": int(len(sub)), "region": int(len(region)),
                                             "region_m2": round(float(area[region].sum()), 3), "z_rear": round(z_rear, 3)})
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
                    # The panel's full thickness: the paint and, in the same
                    # welded piece, the inner liner under it (any material but
                    # glass) within 7 cm of the top surface, in 3 cm cells.
                    # Leaving the liner shuts the bay with a black lid.
                    tall = np.where(~np.isin(tmat, list(glass)))[0]
                    call = T[tall].mean(1)
                    on_top = skin(call, T[tall].reshape(-1, 3), (0, 2), 1, 0.07)
                    ts, cen = tall, call
                    ymin = wheel_top + 0.05

                    def field(P, z_rear=z_rear, half=half, nb=nb, ymin=ymin):
                        k = np.clip(np.floor((P[:, 2] - z_rear) / 0.01).astype(int), 0, nb - 1)
                        return np.maximum.reduce([np.abs(P[:, 0]) - half[k], z_rear - P[:, 2], ymin - P[:, 1]])
                    cuts.append(("bonnet", ts[on_top], field))
                    log["bonnet_search"].update({"eligible": int(on_top.sum()), "eligible_inside": int((field(cen[on_top]) < 0).sum()), "of": int(len(ts))})
                    bonnet = -1
                    log["bonnet"] = {"from": "cut from the body shell along a smoothed shut line",
                                     "rear_edge_z": round(z_rear, 3),
                                     "half_width_m": [round(float(half.min()), 3), round(float(half.max()), 3)]}

    # tailgate: the rear window, the panel under it, and what sits on that skin
    # the rear window from its glass triangles, facing back, above the waist
    tri_c = T.mean(1)
    waist_ = ground + 1.35 * (wheel_top - ground)
    grear = np.isin(tmat, list(glass)) & (tri_c[:, 2] < zr) & (tri_c[:, 1] > waist_) & (np.abs(nrm[:, 2]) > 0.2)
    if area[grear].sum() > 0.15 and "tailgate" not in manual:
        Rv = T[grear].reshape(-1, 3)
        rw_lo, rw_hi, rw_cz, rw_m2 = Rv.min(0), Rv.max(0), float(tri_c[grear, 2].mean()), float(area[grear].sum())
        xb = max(abs(rw_lo[0]), abs(rw_hi[0])) + 0.08
        zfront = rw_hi[2] + 0.10
        under = [i for i in range(nl) if dom[i] == paint and abs(hi[i, 1] - rw_lo[1]) < 0.04
                 and cz[i] < rw_cz and max(abs(lo[i, 0]), abs(hi[i, 0])) < xb and isl_area[i] > 0.1]
        ybot = (min(lo[i, 1] for i in under) if under else rw_lo[1] - 0.35) - 0.01
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
        log["tailgate"] = {"from": "islands", "rear_window_m2": round(rw_m2, 3),
                           "box": {"x_half": round(float(xb), 3), "y_bottom": round(float(ybot), 3),
                                   "z_front": round(float(zfront), 3)},
                           "pieces": int(tg.sum())}
        # A tailgate welded into the body shell has no paint piece of its own:
        # cut it from the shell's rear skin like a welded bonnet. Sides: the
        # rear window's width; top: the window's top edge; bottom: going down
        # the middle of the shell's rear skin, the first step back of 2 cm or
        # more at least 10 cm under the window, which is the bumper's top
        # (else 35 cm under the window).
        tg_paint = float(sum(isl_area[i] for i in np.where(tg)[0] if dom[i] == paint))
        shells_r = [i for i in range(nl) if mat_area[i, paint] > 0.5 and lo[i, 2] < zr and label[i] == "body"]
        # the rig machine's own tailgate cut beats ours: a rear-skin cut on a
        # welded shell comes away ragged (Fiesta, Golf R, A3), the rig's
        # panel cut follows the model's own edges
        # (when it is a panel: at least 0.3 m2 of it paint - the Golf R's
        # "tailgate" from the rig is the boot floor carpet)
        rig_tg_m2 = float(sum(tri_area_normal(tris(r))[0].sum() for r in body
                              if r["rig"] == "tailgate" and r["mat"] in paint_ids))
        if rig_tg_m2 > 0.3 and tg_paint < 0.3:
            label[tg] = "body"
            del log["tailgate"]
        elif tg_paint < 0.3 and shells_r:
            sh = max(shells_r, key=lambda i: mat_area[i, paint])
            tp_ = np.where(tmat == paint)[0]
            # the panel's full thickness: paint and the liner behind it, within
            # 8 cm of the rearmost surface, in 3 cm cells
            ts = np.where(~np.isin(tmat, list(glass)))[0]
            cen = T[ts].mean(1)
            on_skin = skin(cen, T[ts].reshape(-1, 3), (0, 1), -1, 0.08)
            sp = T[tp_].reshape(-1, 3)
            mid = sp[np.abs(sp[:, 0]) < 0.15]
            ytop_b = rw_lo[1]
            yb = np.arange(ytop_b, 0.6 * wheel_top, -0.01)
            zb = np.array([mid[(mid[:, 1] <= y) & (mid[:, 1] > y - 0.01), 2].min()
                           if ((mid[:, 1] <= y) & (mid[:, 1] > y - 0.01)).any() else np.nan for y in yb])
            ycut = rw_lo[1] - 0.35
            for k in range(11, len(yb)):
                if np.isfinite(zb[k]) and np.isfinite(zb[k - 1]) and zb[k] < zb[k - 1] - 0.02:
                    ycut = float(yb[k - 1])
                    break
            xt = max(abs(rw_lo[0]), abs(rw_hi[0])) + 0.02
            ztop = rw_hi[2] + 0.02

            def tfield(P, xt=xt, ycut=ycut, ztop=ztop):
                return np.maximum.reduce([np.abs(P[:, 0]) - xt, ycut - P[:, 1], P[:, 2] - ztop])
            cuts.append(("tailgate", ts[on_skin], tfield))
            log["tailgate"]["cut"] = {"from": "the body shell's rear skin", "x_half": round(float(xt), 3),
                                      "bottom_y": round(ycut, 3)}

    # no tailgate found here: the rig machine's tailgate stands, as the islands
    # mostly made of its triangles
    rig_tg_direct = None
    if "tailgate" in manual:
        rig_tg = np.concatenate([np.full(len(r["I"]), r["rig"] == "tailgate") for r in body])
        rig_tg_direct = rig_tg & (label[lab] == "body")
        log["tailgate"] = {"from": "the Studio", "triangles": int(rig_tg_direct.sum())}
    elif "tailgate" not in log:
        rig_tg = np.concatenate([np.full(len(r["I"]), r["rig"] == "tailgate") for r in body])
        if rig_tg.any():
            share = np.bincount(lab, weights=rig_tg.astype(float), minlength=nl) / np.maximum(
                np.bincount(lab, minlength=nl), 1)
            label[(share > 0.5) & (label == "body")] = "tailgate"
            log["tailgate"] = {"from": "rig", "pieces": int((label == "tailgate").sum())}
            if not log["tailgate"]["pieces"]:
                # welded here into a larger piece of the shell (the 2004
                # Micra's lid shares its edge vertices with the body): the
                # rig's own triangles are the lid
                rig_tg_direct = rig_tg & (label[lab] == "body")
                log["tailgate"]["triangles"] = int(rig_tg_direct.sum())

    # door trims: window frames, belt mouldings and mirrors modelled as their
    # own small pieces are left on the body by the rig's door cut and float in
    # the air when the door opens. A piece inside a door's box, above the
    # wheels, that touches the door (within 1 cm of its surface) goes with it;
    # a seat or a brake inside the same box does not touch it.
    # The tailgate takes what touches it the same way (a rear window modelled
    # in a dark plastic rather than glass, the inner lamps).
    doors = {}
    for r in recs:
        if r["rig"].startswith("door_") and r["rig"] not in manual:
            doors.setdefault(r["rig"], []).append(tris(r))
    if "tailgate" in manual:
        pass
    elif (label == "tailgate").any():
        doors["tailgate"] = [T[label[lab] == "tailgate"]]
    elif rig_tg_direct is not None and rig_tg_direct.any():
        doors["tailgate"] = [T[rig_tg_direct]]
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
        if r["rig"] == "tailgate" and rig_tg_direct is not None:
            tp = np.where(tp == "body", "tailgate", tp)
        r["tri_part"] = tp
        off += n
    for r in recs:
        if "tri_part" not in r:
            r["tri_part"] = np.full(len(r["I"]), r["rig"], dtype=object)

    # the cuts: shell triangles inside a shut line go to that part, and those
    # crossing it are split along it
    if cuts:
        off = 0
        for r in body:
            n = len(r["I"])
            r["flags"] = {}
            for part, tri_ids, _ in cuts:
                el = np.zeros(len(T), bool)
                el[tri_ids] = True
                r["flags"][part] = el[off:off + n]
            off += n
        for part, _, field in cuts:
            nsplit = 0
            for r in body:
                if r["flags"][part].any():
                    nsplit += split_along(g, r, r["flags"][part], field, part)
            pa = sum(tri_area_normal(r["P"][r["I"][r["tri_part"] == part]])[0].sum() for r in body)
            entry = log[part] if part == "bonnet" else log[part]["cut"]
            entry.update({"area_m2": round(float(pa), 3), "triangles_split": nsplit})

    # a bonnet is a skin: what is not paint stays on it only where it lies
    # just under the painted panel (its liner, hinges, washer jets), and the
    # parts the rigger called lamps never ride on it. A model
    # that joins its headlamps or grille to the bonnet panel (the Superb's)
    # would otherwise lift them with it. A bonnet set in the Studio is taken
    # as given.
    if "bonnet" not in manual:
        panel = [r["P"][r["I"][r["tri_part"] == "bonnet"]].reshape(-1, 3)
                 for r in recs if r["mat"] in paint_ids and (r["tri_part"] == "bonnet").any()]
        if panel:
            from scipy.ndimage import minimum_filter
            S, cell = np.vstack(panel), 0.04
            x0, z0 = S[:, 0].min() - cell, S[:, 2].min() - cell
            gx = np.floor((S[:, 0] - x0) / cell).astype(int)
            gz = np.floor((S[:, 2] - z0) / cell).astype(int)
            under = np.full((gx.max() + 3, gz.max() + 3), np.inf)
            np.minimum.at(under, (gx, gz), S[:, 1])          # the panel's underside, cell by cell
            under = minimum_filter(under, size=3)              # and its neighbours: no gaps at the seams
            moved = 0
            for r in recs:
                on = r["tri_part"] == "bonnet"
                if r["mat"] in paint_ids or not on.any():
                    continue
                if str(r.get("rig") or "").startswith("lamps"):     # the rigger's own lamps: never the bonnet's
                    r["tri_part"] = np.where(on, "body", r["tri_part"])
                    moved += int(on.sum())
                    continue
                c = r["P"][r["I"][on]].mean(1)
                cx = np.floor((c[:, 0] - x0) / cell).astype(int)
                cz_ = np.floor((c[:, 2] - z0) / cell).astype(int)
                inside = (cx >= 0) & (cz_ >= 0) & (cx < under.shape[0]) & (cz_ < under.shape[1])
                ref = np.full(len(c), np.inf)
                ref[inside] = under[cx[inside], cz_[inside]]
                off_skin = ~np.isfinite(ref) | (c[:, 1] < ref - 0.06)
                if off_skin.any():
                    idx = np.where(on)[0][off_skin]
                    r["tri_part"] = r["tri_part"].copy()
                    r["tri_part"][idx] = "body"
                    moved += int(off_skin.sum())
            if moved and isinstance(log.get("bonnet"), dict):
                log["bonnet"]["left_on_the_body"] = {"triangles": moved, "why": "not paint and not under the panel"}

    # ── the engine bay: one generic engine in every car ──
    # The owner's rule: every car gets the same generic petrol bay. What a
    # model has under its bonnet (nothing, a tub of flat sheets, or a rough
    # engine of its own) is cleared from the middle of the bay so the pack is
    # seen: |x| under 45% of the track (the headlamps and wings stay), above
    # the bottom third of the wheels (the floor stays), under the bonnet,
    # and 12 cm clear of the bonnet's front edge (the grille stays).
    # spec "keep_native_engine": true keeps a model's own instead.
    bt = [r["P"][r["I"][r["tri_part"] == "bonnet"]] for r in recs if (r["tri_part"] == "bonnet").any()]
    cleared = 0.0
    if bt and spec.get("engine_pack") and not spec.get("keep_native_engine"):
        B = np.vstack(bt).reshape(-1, 3)
        wd = wheel_top - ground
        z0, z1, ytop = B[:, 2].min() + 0.05, B[:, 2].max() - 0.12, B[:, 1].min()
        # the bonnet's underside, cell by cell (cells as big as its triangles,
        # at least 3 cm): everything below it is
        # bay, up to just under the panel - a fake engine (the Fiesta's is a
        # photo on a sheet 15 cm under the bonnet) sits above the lowest
        # point of the bonnet's front lip
        bcell = float(np.clip(2 * np.sqrt(np.median(tri_area_normal(np.vstack(bt))[0])), 0.03, 0.12))
        bk = np.floor(B[:, [0, 2]] / bcell).astype(np.int64) @ np.array([100000, 1])
        buk, binv = np.unique(bk, return_inverse=True)
        bunder = np.full(len(buk), np.inf)
        np.minimum.at(bunder, binv, B[:, 1])
        btop = np.full(len(buk), -np.inf)
        np.maximum.at(btop, binv, B[:, 1])
        for r in recs:
            if r["rig"].startswith(("wheel_", "door_")) or r["mat"] in glass:
                continue
            body_t = np.where(r["tri_part"] == "body")[0]
            if not len(body_t):
                continue
            Tr = r["P"][r["I"][body_t]]
            c = Tr.mean(1)
            ck = np.floor(c[:, [0, 2]] / bcell).astype(np.int64) @ np.array([100000, 1])
            ix = np.clip(np.searchsorted(buk, ck), 0, len(buk) - 1)
            hit = buk[ix] == ck
            lid = np.where(hit, bunder[ix] - 0.01, ytop)
            ar_, nr_ = tri_area_normal(Tr)
            big = ar_ > 0.005 * (wd / 0.66) ** 2
            # a big sheet can lie a centimetre under the bonnet's liner (the
            # Fiesta's photo engine): for those, anything under the bonnet's
            # top skin is bay (the bonnet itself is its own part by now)
            lid = np.where(big & hit, btop[ix] - 0.02, lid)
            under_bonnet = (c[:, 1] > ground + 0.35 * wd) & (c[:, 1] < lid) & (c[:, 2] > z0)
            # small detail: the middle of the bay only (headlamp insides and
            # the grille stay); big flat sheets (a tub, a photo of an engine:
            # the Fiesta's are 30 cm triangles) out to the inner wings and up
            # to the bonnet's front, except what faces forward (the grille)
            # or is named as a lamp, chrome or badge
            lampish = bool(re.search(r"light|lamp|lens|luz|chrome|cromo|grill|badge|logo|emblem",
                                     mats[r["mat"]].get("name", "") if r["mat"] is not None else "", re.I))
            inb = under_bonnet & (
                ((np.abs(c[:, 0]) < 0.45 * track_half) & (c[:, 2] < z1)) |
                (big & (np.abs(c[:, 0]) < 0.75 * track_half) & (c[:, 2] < z1 + 0.12) & (np.abs(nr_[:, 2]) < 0.7)
                 & (not lampish)))
            # the model's own engine, by its material's name (the 2001 Yaris's
            # VITZ_ENGINE covers stood over the generic engine): all of it
            # under the bonnet's top and inside its footprint goes
            enginish = bool(re.search(r"engine|motor|engbay|intake|radiator|battery|bay\b",
                                      mats[r["mat"]].get("name", "") if r["mat"] is not None else "", re.I))
            if enginish:
                inb |= (c[:, 1] > ground + 0.2 * wd) & (c[:, 1] < btop.max()) & (np.abs(c[:, 0]) < track_half) \
                    & (c[:, 2] > z0 - 0.1) & (c[:, 2] < B[:, 2].max())
            if inb.any():
                cleared += float(tri_area_normal(Tr[inb])[0].sum())
                r["tri_part"][body_t[inb]] = "drop"
        log["bay_cleared_m2"] = round(cleared, 3)
    elif spec.get("keep_native_engine"):
        spec = dict(spec, engine_pack=None)
        log["engine_pack"] = {"skipped": "keep_native_engine"}

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
            if part == "drop":
                continue
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
            h = (spec.get("hinges") or {}).get(part) or (spec.get("hinges") or {}).get(pname) or {}
            piv, axis, deg = hinge_line(pname, V.min(0), V.max(0), h.get("edge"), h.get("deg"))
            hv = len(nodes)
            nodes.append({"name": pname + "_hinge", "translation": piv, "children": [hv + 1],
                          "extras": {"axis": axis, "open_deg": deg}})
            nodes.append({"name": pname, "translation": [-c for c in piv], "mesh": mi})
            nodes[0]["children"].append(hv)
            pivots[pname] = (hv, axis, deg)
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
        # Scale: the body's half-width at the front axle, between the
        # wheels' mid-height and the waist, against the Golf master's 0.894 m.
        # (A wheel group can carry more than the wheel: the A45's is 38 cm
        # wide, and a track from it made the engine 17% too big.)
        wd = wheel_top - ground
        cz_ = T.mean(1)
        selw = (np.abs(cz_[:, 2] - zf) < 0.35) & (cz_[:, 1] > ground + 0.5 * wd) & (cz_[:, 1] < ground + 1.2 * wd)
        body_half = float(np.percentile(np.abs(cz_[selw, 0]), 98)) if selw.sum() > 50 else track_half
        # three measures of the front end's width against the Golf master's;
        # the middle one sets the scale (any one can be thrown by a model's
        # wheel group, arch flares or a narrow bonnet)
        bon_r = [r["P"][r["I"][r["tri_part"] == "bonnet"]].reshape(-1, 3) for r in recs if (r["tri_part"] == "bonnet").any()]
        bonnet_half = float(np.percentile(np.abs(np.vstack(bon_r)[:, 0]), 99)) if bon_r else body_half
        ratios = [track_half / F["track_half"], body_half / F["body_half"], bonnet_half / F["bonnet_half"]]
        # across the car by width; along and up the car by the wheelbase
        # against the master's 2.631 m (a model can be stretched sideways:
        # the A45's is 14% too wide), never taller than it is wide
        sx = float(np.median(ratios)) * s
        sl = (zf - zr) * s / 2.631
        sy = min(sx, sl)
        se = sx
        zf_o, zr_o = (zf - zmid) * s, (zr - zmid) * s

        def mat4(A, t):
            M = np.eye(4)
            M[:3, :3] = np.diag(A)
            M[:3, 3] = t
            return [float(v) for v in M.T.ravel()]

        def anchored(z_from, z_to):
            A = np.array([sx, sy, sl])
            return mat4(A, np.array([0.0, 0.0, z_to]) - A * np.array([0.0, F["ground_y"], z_from]))
        front = anchored(F["front_axle_z"], zf_o)
        rear = anchored(F["rear_axle_z"], zr_o)
        # Fit: nothing of the bay may show through the shut bonnet or the
        # nose. The bay's points are checked against the bonnet's underside
        # (3 cm cells, 3 cm clear) and then the front skin (4 cm clear); the
        # bay goes down, then back, as far as needed (at most 15 / 20 cm).
        _, ppar = pack.world_matrices()
        root = pack.j["scenes"][pack.j.get("scene", 0)]["nodes"][0]

        def top_of(i):
            while ppar.get(i, root) != root:
                i = ppar[i]
            return pack.j["nodes"][i].get("name", "")
        pts = []
        for i, nd in enumerate(pack.j["nodes"]):
            if "mesh" in nd and i not in stray and top_of(i) not in PACK_REAR | PACK_EXHAUST:
                for pr in pack.j["meshes"][nd["mesh"]]["primitives"]:
                    Pp = pack.accessor(pr["attributes"]["POSITION"])
                    pts.append(Pp[:: max(1, len(Pp) // 400)] @ PW[i][:3, :3].T + PW[i][:3, 3])
        Mf = np.array(front).reshape(4, 4).T
        Q = np.vstack(pts) @ Mf[:3, :3].T + Mf[:3, 3]
        bon = [to_out(r["P"][r["I"][r["tri_part"] == "bonnet"]].reshape(-1, 3)) for r in recs if (r["tri_part"] == "bonnet").any()]
        skin_pts = np.vstack([to_out(r["P"][r["I"][r["tri_part"] == "body"]].reshape(-1, 3))
                              for r in recs if not r["rig"].startswith(("wheel_", "door_")) and (r["tri_part"] == "body").any()])

        def overshoot(Q, ref, axes, ax, reduce, clear):
            """How far points Q reach past `lim - clear` along axis ax, where
            lim is the ref surface's min or max (reduce) in each 3 cm cell."""
            kk = lambda P: np.floor(P[:, list(axes)] / 0.03).astype(np.int64) @ np.array([100000, 1])  # noqa: E731
            kr = kk(ref)
            uk, inv = np.unique(kr, return_inverse=True)
            lim = np.full(len(uk), np.inf if reduce is np.minimum else -np.inf)
            reduce.at(lim, inv, ref[:, ax])
            kq = kk(Q)
            ix = np.clip(np.searchsorted(uk, kq), 0, len(uk) - 1)
            hit = uk[ix] == kq
            return float(max(0.0, (Q[hit, ax] - (lim[ix[hit]] - clear)).max())) if hit.any() else 0.0
        dy = min(0.15, overshoot(Q, np.vstack(bon), (0, 2), 1, np.minimum, 0.03)) if bon else 0.0
        Q[:, 1] -= dy
        # the nose only: body ahead of the front axle, bay points from the
        # bumper's lower edge up (the arms and subframe sit under the floor)
        nose = skin_pts[skin_pts[:, 2] > zf_o]
        qn = Q[Q[:, 1] > 0.35 * wd * s]
        dz = min(0.12, overshoot(qn, nose, (0, 1), 2, np.maximum, 0.04)) if len(qn) and len(nose) else 0.0
        Mf[1, 3] -= dy
        Mf[2, 3] -= dz
        front = [float(v) for v in Mf.T.ravel()]
        # exhaust: from where the front pipe hands over to 10 cm inside the tail
        tail_o = (float(min(lo[:, 2])) - zmid) * s
        z1 = sl * (F["exhaust_front_z"] - F["front_axle_z"]) + zf_o
        z2 = tail_o + 0.10
        az = (z1 - z2) / (F["exhaust_front_z"] - F["exhaust_tail_z"])
        A = np.array([sx, sy, az])
        exhaust = mat4(A, np.array([0.0, -sy * F["ground_y"], z1 - az * F["exhaust_front_z"]]))
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
        log["engine_pack"] = {"file": os.path.basename(spec["engine_pack"]), "scale": [round(sx, 4), round(sy, 4), round(sl, 4)],
                              "lowered_m": round(dy, 3), "moved_back_m": round(dz, 3),
                              "width_ratios": [round(x, 3) for x in ratios],
                              "exhaust_stretch": round(az / sl, 4), "strays_dropped": len(stray)}

    j["scenes"] = [{"name": spec.get("name") or "car", "nodes": [0]}]
    j["scene"] = 0

    # ── paint: a colour asked for (sRGB 0-255) replaces the model's own ──
    if spec.get("paint"):
        pm = mats[paint]
        pbr = pm.setdefault("pbrMetallicRoughness", {})
        pbr.pop("baseColorTexture", None)
        lin = [float(c / 255 / 12.92 if c / 255 <= 0.04045 else ((c / 255 + 0.055) / 1.055) ** 2.4)
               for c in spec["paint"][:3]]
        pbr["baseColorFactor"] = lin + [1.0]
        # the finish follows the colour, not the model's paint: white on the
        # 2001 Yaris's metallic silver (metallic 0.8) read as silver. Silver
        # and grey (colourless, mid-light) stay metallic; the rest are solid.
        r_, g_, b_ = spec["paint"][:3]
        light, chroma = (max(r_, g_, b_) + min(r_, g_, b_)) / 2, max(r_, g_, b_) - min(r_, g_, b_)
        metallic = spec.get("paint_metallic", 0.6 if chroma < 20 and 90 < light < 215 else 0.0)
        pbr["metallicFactor"] = float(metallic)
        pbr["roughnessFactor"] = 0.3 if metallic else 0.35
        pbr.pop("metallicRoughnessTexture", None)
        sp = (pm.get("extensions") or {}).get("KHR_materials_specular")
        if sp:                                      # a specular map painted for the old colour
            sp.pop("specularTexture", None)
            sp.pop("specularColorTexture", None)
        log["paint_set"] = {"material": pm.get("name"), "srgb": list(spec["paint"][:3]), "metallic": float(metallic)}

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
        # transmission and clearcoat on a window render as smoked glass in
        # most viewers; plain alpha blend reads as clear everywhere
        for ext in ("KHR_materials_transmission", "KHR_materials_clearcoat", "KHR_materials_volume"):
            (m.get("extensions") or {}).pop(ext, None)
        if m.get("extensions") == {}:
            m.pop("extensions")
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
    log["tangents"] = ensure_tangents(g)
    log["bytes"] = g.save(out)
    return log


if __name__ == "__main__":
    src, spec_p, out = sys.argv[1:4]
    spec = json.load(open(spec_p))
    d = os.path.dirname(os.path.abspath(spec_p))
    if spec.get("engine_pack") and not os.path.isabs(spec["engine_pack"]):
        spec["engine_pack"] = os.path.join(d, spec["engine_pack"])
    print(json.dumps(finish(src, spec, out, d), indent=1, default=float))
