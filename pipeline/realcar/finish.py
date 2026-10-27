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
     "cabin_pack": "cabin_pack.glb",                          # optional: fitted when the
                                                              # model's cabin is empty
     "credit": "2023 Volkswagen Polo GTI by … (CC BY 4.0)",   # optional, -> asset.copyright
     "paint": [20, 20, 22],                                   # optional, sRGB 0-255
     "keep_native_engine": false,                             # optional: keep a model's own bay
     "electric": false,                                       # optional: an electric car, no engine pack
     "manual": ["bonnet", "door_fl"],                         # optional: parts set by hand in the
                                                              # Studio (edits.py): taken as they are
     "hinges": {"bonnet": {"edge": "front", "deg": 50},       # optional: hinge edge and angle,
                "door_rl": {"slide": true}}}                  # or a side door that slides back
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
import copy
import io
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
from gltf import GLTF, row_ids  # noqa: E402

HINGED = {"door_fl": -65, "door_fr": 65, "door_rl": -65, "door_rr": 65, "bonnet": -55, "tailgate": 75,
          "door_bl": 95, "door_br": 95}                 # a van's barn doors, hinged at the back's outer edges
BARN = ("door_bl", "door_br")

# Where the engine pack sits in the Golf master's frame (measured from
# tmpl/master_golf.glb): front and rear axle z, ground y, tyre outer x.
PACK_FRAME = {"front_axle_z": 1.316, "rear_axle_z": -1.315, "ground_y": -0.013, "track_half": 0.875, "body_half": 0.894, "bonnet_half": 0.794,
              "exhaust_front_z": 0.802, "exhaust_tail_z": -2.081}
PACK_REAR = {"bay:susp_rear", "bay:fuel_tank"}
PACK_EXHAUST = {"bay:exhaust_rear"}
EXHAUST_INSIDE = 0.30      # m: where the pack's exhaust ends, inside the car's rearmost point


def hinge_line(part, plo, phi, edge=None, deg=None):
    """Pivot, axis and opening angle for a hinged part, from its box (the
    Studio draws the same line). Doors: front edge (or rear, a rear-hinged
    door); bonnet: rear edge (or front); tailgate: top edge (or bottom: a
    drop-down tail; left / right: side-hinged)."""
    deg = abs(float(deg)) if deg else abs(HINGED[part])
    if part in BARN:
        left = part == "door_bl"
        x = float(phi[0] - 0.02 if left else plo[0] + 0.02)
        return [x, float((plo[1] + phi[1]) / 2), float(plo[2] + 0.02)], [0, 1, 0], -deg if left else deg
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
    vid = row_ids(np.round(T.reshape(-1, 3) / weld).astype(np.int64)).reshape(-1, 3)
    nt = len(T)
    rows = np.repeat(np.arange(nt), 3)
    cols = vid.ravel() + nt
    n = nt + int(vid.max()) + 1
    A = coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(n, n))
    _, lab = connected_components(A, directed=False)
    return lab[:nt], vid


def surface_points(T, step=0.008, with_index=False):
    """Vertices plus points spread over each triangle about `step` apart, so a
    nearest-point query measures distance to the surface, not to corners.
    With with_index, also the triangle each point lies on."""
    a, _ = tri_area_normal(T)
    pts = [T.reshape(-1, 3)]
    idx = [np.repeat(np.arange(len(T)), 3)]
    k = np.clip(np.ceil(np.sqrt(a) / step), 1, 40).astype(int)
    for n in np.unique(k):
        if n < 2:
            continue
        on = np.where(k == n)[0]
        sel = T[on]
        u, v = np.meshgrid(np.arange(n + 1), np.arange(n + 1))
        keep = (u + v) <= n
        u, v = u[keep] / n, v[keep] / n
        w = 1 - u - v
        P = (sel[:, None, 0] * w[None, :, None] + sel[:, None, 1] * u[None, :, None] + sel[:, None, 2] * v[None, :, None])
        pts.append(P.reshape(-1, 3))
        idx.append(np.repeat(on, len(u)))
    if with_index:
        return np.vstack(pts), np.concatenate(idx)
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


def _alpha_soft(g, mat):
    """The share of a material's base-colour texture that is neither clear nor
    solid (alpha 0.1-0.9): 1.0 is see-through all over, near 0 a cut-out
    pattern. None when there is no texture with alpha to read."""
    t = mat.get("pbrMetallicRoughness", {}).get("baseColorTexture")
    if not t:
        return None
    try:
        tex = g.j["textures"][t["index"]]
        src = tex.get("source", next((e.get("source") for e in (tex.get("extensions") or {}).values()
                                      if isinstance(e, dict) and "source" in e), None))
        img = g.j["images"][src]
        bv = g.j["bufferViews"][img["bufferView"]]
        data = g.bin[bv.get("byteOffset", 0): bv.get("byteOffset", 0) + bv["byteLength"]]
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        if im.mode not in ("RGBA", "LA", "PA") and "transparency" not in im.info:
            return None
        im.thumbnail((256, 256))
        a = np.asarray(im.convert("RGBA"))[:, :, 3].astype(np.float32) / 255
        return float(np.mean((a >= 0.1) & (a <= 0.9)))
    except Exception:
        return None


def lamp_lens(mat):
    """A lamp's lens: by its name (lamp, light, lens, red, amber ...; never a
    brake disc's), or, as many models name nothing, by its colour: red or
    amber (the 1998 Micra's tail lamps are "Material.005", a see-through red)."""
    name = mat.get("name", "")
    if re.search(r"disc|disk|caliper|rotor|pad", name, re.I):
        return False
    if re.search(r"lamp|light|lens|reflector|indicator|signal|red|amber|orange", name, re.I):
        return True
    r, g, b = mat.get("pbrMetallicRoughness", {}).get("baseColorFactor", [1, 1, 1, 1])[:3]
    return r >= 0.25 and b < 0.4 * r and g < 0.65 * r


def tail_lamps_inside(T, tmat, nrm, lamps, zback, ylo, yhi):
    """The inner edge (|x|) of the tail lamps on a car's back: lens triangles
    facing back within 25 cm of the rearmost point, between ylo and yhi,
    off the middle (not a plate lamp or a high brake light). None if none."""
    c = T.mean(1)
    lt = np.isin(tmat, lamps) & (c[:, 2] < zback + 0.25) & (nrm[:, 2] < -0.5) & (c[:, 1] > ylo) & (c[:, 1] < yhi) \
        & (np.abs(c[:, 0]) > 0.25)
    if not lt.any() or tri_area_normal(T[lt])[0].sum() <= 0.003:
        return None
    return float(np.percentile(np.abs(T[lt].reshape(-1, 3)[:, 0]), 2))


def bumper_top(T, keep, x_lo, x_hi, ytop, ylow, zmax, below=0.10, painted=None):
    """Going down a car's back from ytop, off its middle (|x| in x_lo..x_hi),
    the bumper's top, at least `below` under ytop: the first place the back
    either steps back 2 cm or more in 1 cm and 4 cm or more in 3 cm, beyond
    the lean of the surface higher up (a sloping tailgate, a rounded lip),
    and stays back (a lamp's lip comes forward again; a number plate's recess
    steps back less); or, with `painted` (the triangles in the body colour),
    turns from paint to something else for the next 15 cm (a black bumper
    nearly flush with the doors, the Master's; a number plate or a trim strip
    is not that tall). The rearmost surface in 1 cm steps, from points spread
    over the triangles `keep` (their corners alone leave steps empty or deep
    inside), the rearmost within 1 cm. None if not found."""
    c = T.mean(1)
    sel = keep & (np.abs(c[:, 0]) > x_lo - 0.05) & (np.abs(c[:, 0]) < x_hi + 0.05) & (c[:, 2] < zmax) \
        & (c[:, 1] < ytop + 0.05) & (c[:, 1] > ylow - 0.05)
    if not sel.any():
        return None
    on = np.where(sel)[0]
    P, ti = surface_points(T[on], 0.01, with_index=True)
    pa = painted[on][ti] if painted is not None else np.zeros(len(P), bool)
    m = (np.abs(P[:, 0]) > x_lo) & (np.abs(P[:, 0]) < x_hi) & (P[:, 2] < zmax)
    P, pa = P[m], pa[m]
    yb = np.arange(ytop, ylow, -0.01)
    hb = np.floor((ytop - P[:, 1]) / 0.01).astype(np.int64)
    ok = (hb >= 0) & (hb < len(yb))
    P, pa, hb = P[ok], pa[ok], hb[ok]
    zb = np.full(len(yb), np.inf)
    np.minimum.at(zb, hb, P[:, 2])
    fb = np.zeros(len(yb), bool)                 # the rearmost point of each step painted
    o = np.lexsort((P[:, 2], hb))
    first = np.r_[True, hb[o][1:] != hb[o][:-1]]
    fb[hb[o][first]] = pa[o][first]
    # a 1 cm gap between panels: the rearmost within 1 cm
    zs = np.stack([zb, np.r_[zb[1:], np.inf], np.r_[np.inf, zb[:-1]]])
    fs = np.stack([fb, np.r_[fb[1:], False], np.r_[False, fb[:-1]]])
    j = zs.argmin(0)
    zb, fb = zs[j, np.arange(len(yb))], fs[j, np.arange(len(yb))]
    for k in range(max(int(round(below / 0.01)) + 1, 11), len(yb) - 10):
        z0 = zb[k - 1]
        if not (np.isfinite(z0) and np.isfinite(zb[k - 11]) and np.isfinite(zb[k - 6])):
            continue
        lean = max((zb[k - 11] - zb[k - 6]) / 5, 0.0)    # metres further back per step, higher up
        if zb[k] < z0 - lean - 0.02 and zb[k + 2] < z0 - 3 * lean - 0.04 \
                and np.median(zb[k:k + 10]) <= zb[k] + 0.01:
            return float(yb[k - 1]) - 0.01
        if painted is not None and fb[k - 3:k].all() and k + 15 <= len(yb) \
                and np.isfinite(zb[k:k + 15]).all() and (~fb[k:k + 15]).mean() >= 0.9:
            return float(yb[k - 1]) - 0.01
    return None


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


def _texture_slots(d):
    """Every texture binding in a material, as (holder, key) pairs."""
    for k, v in list(d.items()):
        if isinstance(v, dict):
            if k.endswith("Texture") and "index" in v:
                yield d, k
            else:
                yield from _texture_slots(v)


def drop_unreachable_maps(g):
    """A primitive with no texture coordinates for a map its material binds
    (the engine pack's gearbox case wears a roughness map on pieces with
    none: glTF validator, an error, once the file is re-written) gets a copy
    of the material without those maps; the material stays as it is for the
    pieces that have them. Returns how many primitives were given a copy."""
    mats = g.j.get("materials", [])
    made, fixed = {}, 0
    for mesh in g.j.get("meshes", []):
        for p in mesh["primitives"]:
            mi = p.get("material")
            if mi is None:
                continue
            missing = []
            for holder, key in _texture_slots(mats[mi]):
                if f"TEXCOORD_{holder[key].get('texCoord', 0)}" not in p["attributes"]:
                    missing.append(key)
            if not missing:
                continue
            k = (mi, tuple(sorted(missing)))
            if k not in made:
                m2 = copy.deepcopy(mats[mi])
                for holder, key in list(_texture_slots(m2)):
                    if key in missing:
                        holder.pop(key)
                m2["name"] = (m2.get("name") or "material") + " (no maps)"
                mats.append(m2)
                made[k] = len(mats) - 1
            p["material"] = made[k]
            fixed += 1
    return fixed


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


def cabin_count(recs, ground, wheel_top, zf, zr):
    """Triangles of the body (not the doors) in the cabin's middle: inboard,
    between the axles, from a little over the wheel centres to well over
    them. A modelled cabin has thousands; a shell with nothing in it (the
    sourced 1998 Micra) a few dozen."""
    body = [r for r in recs if not r["rig"].startswith(("door_", "wheel_"))]
    T = np.vstack([r["P"][r["I"]] for r in body])
    c = T.mean(1)
    half = float(np.abs(T[:, :, 0]).max())
    D, wb = wheel_top - ground, zf - zr
    wy = (ground + wheel_top) / 2
    box = ((np.abs(c[:, 0]) < .6 * half) & (c[:, 2] < zf - .1 * wb) & (c[:, 2] > zr + .1 * wb)
           & (c[:, 1] > wy + .15 * D) & (c[:, 1] < wy + 1.1 * D))
    return int(box.sum())


def fit_cabin(g, recs, path, to_out, s, ground, zf, zr):
    """Bring the cabin pack in (cabin_pack.py): scaled to this car's
    wheelbase, width and roof, then moved back, down or made lower (at most
    20 cm, 4 cm, 12%) until it stays inside the car: under the roof and the
    windscreen, over the floor, nothing outside the body's plan. Returns
    the pack's root node and the log."""
    from cabin_pack import dense_points, roof_of
    pack = GLTF(path)
    info = (pack.j.get("asset", {}).get("extras") or {}).get("cabin_pack") or {}
    near = [r for r in recs if not r["rig"].startswith("wheel_")]
    T = np.vstack([to_out(r["P"][r["I"]].reshape(-1, 3)).reshape(-1, 3, 3) for r in near])
    S = dense_points(T, 0.015)
    zf_o, zr_o = (zf - zr) * s / 2, -(zf - zr) * s / 2
    half_r = (S[:, 0].max() - S[:, 0].min()) / 2
    roof_r = roof_of(S, zf_o, zr_o)
    sx, sy, sz = half_r / info["half_width"], roof_r / info["roof_y"], (zf - zr) * s / info["wheelbase"]
    # the pack's points, and this car's surfaces in 3 cm cells across x and z
    PW, _ = pack.world_matrices()
    pts = []
    for i, nd in enumerate(pack.j["nodes"]):
        if "mesh" in nd:
            for pr in pack.j["meshes"][nd["mesh"]]["primitives"]:
                Pp = pack.accessor(pr["attributes"]["POSITION"])
                pts.append(Pp @ PW[i][:3, :3].T + PW[i][:3, 3])
    Q0 = np.vstack(pts)
    Q0 = Q0[:: max(1, len(Q0) // 20000)] * np.array([sx, sy, sz])
    z_lo, z_hi = Q0[:, 2].min() - .3, Q0[:, 2].max() + .1
    S = S[(S[:, 2] > z_lo) & (S[:, 2] < z_hi)]
    key = lambda P: np.floor(P[:, [0, 2]] / 0.03).astype(np.int64) @ np.array([100000, 1])  # noqa: E731
    uk, inv = np.unique(key(S), return_inverse=True)
    top = np.full(len(uk), -np.inf)
    bot = np.full(len(uk), np.inf)
    np.maximum.at(top, inv, S[:, 1])
    np.minimum.at(bot, inv, S[:, 1])

    def outside(Q):
        k = key(Q)
        ix = np.clip(np.searchsorted(uk, k), 0, len(uk) - 1)
        hit = uk[ix] == k
        return float(np.mean(~hit | (Q[:, 1] > top[ix] - 0.02) | (Q[:, 1] < bot[ix] + 0.01)))
    best = None
    for shrink in (1.0, .97, .94, .91, .88):
        for dy in (0.0, -.02, -.04, .02):
            for dz in np.arange(0, -.205, -.01):
                Q = Q0 * np.array([1, shrink, 1]) + np.array([0, dy, dz])
                out = outside(Q)
                cost = (out > 0.002, out if out > 0.002 else 0, -dz / .2 + (1 - shrink) / .12 * 1.5 + abs(dy) / .04)
                if best is None or cost < best[0]:
                    best = (cost, shrink, dy, float(dz), out)
    _, shrink, dy, dz, out = best
    M = np.eye(4)
    M[:3, :3] = np.diag([sx, sy * shrink, sz])
    M[:3, 3] = [0.0, dy, dz]
    roots = g.append(pack)
    root = roots[0]
    g.j["nodes"][root]["matrix"] = [float(v) for v in M.T.ravel()]
    cr = info.get("credit") or {}
    return root, {"from": cr.get("title"), "author": cr.get("author"), "licence": cr.get("licence"), "url": cr.get("url"),
                  "scale": [round(sx, 3), round(sy * shrink, 3), round(sz, 3)], "back_m": round(-dz, 3),
                  "down_m": round(-dy, 3), "outside": round(out, 4)}


def wheel_outliers(recs, log):
    """Pieces the rig gave a wheel that lie wholly outside it: past its
    tyre's sides by more than 3 cm, or past its tread by more than 5%. The
    2017 Golf's model has a small black, plastic and chrome piece floating by
    each wheel (out beside the front tyres, down to the ground; behind the
    rears): left in, they set the ground 10 cm under the tyres and the wheels'
    cylinders too big. The tyre's radius is the wheel's piece of the largest
    diameter; its width, all its pieces on that axle. A small piece (under a
    tenth of the wheel's area) is dropped; a larger one goes back to the body."""
    groups = {}
    for r in recs:
        if r["rig"].startswith("wheel_") and len(r["I"]):
            groups.setdefault(r["rig"], []).append(r)
    dropped, to_body = {}, {}
    for k, rs in groups.items():
        boxes = [(r["P"][np.unique(r["I"])].min(0), r["P"][np.unique(r["I"])].max(0)) for r in rs]
        dia = [max(hi[1] - lo[1], hi[2] - lo[2]) for lo, hi in boxes]
        lo_t, hi_t = boxes[int(np.argmax(dia))]
        c, R = (lo_t + hi_t) / 2, max(dia) / 2
        # its width: every piece on the same axle (tyre, rim, disc, hub; a
        # tyre modelled as two sidewalls and a tread, the M5's), centred
        # within a tenth of the radius
        on_axle = [b for b in boxes if np.hypot((b[0][1] + b[1][1]) / 2 - c[1], (b[0][2] + b[1][2]) / 2 - c[2]) < 0.1 * R]
        lo_t = np.min([b[0] for b in on_axle], 0)
        hi_t = np.max([b[1] for b in on_axle], 0)
        areas = [float(tri_area_normal(r["P"][r["I"]])[0].sum()) for r in rs]
        for r, a in zip(rs, areas):
            V = r["P"][np.unique(r["I"])]
            out = (V[:, 0] < lo_t[0] - 0.03) | (V[:, 0] > hi_t[0] + 0.03) \
                | (np.hypot(V[:, 1] - c[1], V[:, 2] - c[2]) > 1.05 * R)
            if not out.all():
                continue
            if a < 0.1 * sum(areas):
                dropped[k] = dropped.get(k, 0) + len(r["I"])
                r["I"] = r["I"][:0]
            else:
                to_body[k] = to_body.get(k, 0) + len(r["I"])
                r["rig"] = "body"
    if dropped:
        log["wheel_outliers_dropped"] = dropped
    if to_body:
        log["wheel_outliers_to_body"] = to_body
    recs[:] = [r for r in recs if len(r["I"])]


def wheel_strays(recs, mats, log):
    """A wheel's pieces the rigger left in the body: the body's triangles in
    that wheel's own cylinder (round its axle, within its width) go to the
    wheel. Its tyre, when the model filed it under the body (the 2023 Clio:
    the wheel group is the rim, the tyre a ring of the paint material round
    it, painted blue with the car), is found as a full ring just outside the
    rim (23 of 24 sectors round filled, band after band) and turns rubber. The
    wheels then explode whole, stand on their tyres, and a new wheel design
    replaces the tyre too. Returns the moved triangles per wheel."""
    wheels = {}
    for r in recs:
        if r["rig"].startswith("wheel_"):
            wheels.setdefault(r["rig"], []).append(r["P"][np.unique(r["I"])])
    body = [r for r in recs if r["rig"] == "body" and len(r["I"])]
    if len(wheels) != 4 or not body:
        return {}
    C = [r["P"][r["I"]] for r in body]
    rubber = None
    moved = {}
    for k, vs in sorted(wheels.items()):
        V = np.vstack(vs)
        lo, hi = V.min(0), V.max(0)
        c = (lo + hi) / 2
        R0 = max(hi[1] - lo[1], hi[2] - lo[2]) / 2
        slab = max((hi[0] - lo[0]) / 2 * 1.1, 0.3 * R0)
        if R0 <= 0:
            continue
        # the ring outside the rim: how full each radius band is, round the axle
        pts = np.vstack([np.vstack([T.reshape(-1, 3), T.mean(1)]) for T in C])
        pts = pts[np.abs(pts[:, 0] - c[0]) < slab]
        rho = np.hypot(pts[:, 1] - c[1], pts[:, 2] - c[2])
        ang = ((np.arctan2(pts[:, 1] - c[1], pts[:, 2] - c[2]) + np.pi) / (2 * np.pi) * 24).astype(int) % 24
        Rt, step = R0, 0.04 * R0
        for b in range(18):
            r_lo, r_hi = R0 * 0.98 + b * step, R0 * 0.98 + (b + 1) * step
            band = (rho >= r_lo) & (rho < r_hi)
            if len(np.unique(ang[band])) < 23:          # all the way round: an arch liner stops at the sill
                break
            Rt = r_hi
        n_tyre = 0
        lim = Rt * 1.02 if Rt > R0 * 1.02 else R0 * 0.98
        for r, T in zip(body, C):
            tc = T.mean(1)
            rr = np.hypot(tc[:, 1] - c[1], tc[:, 2] - c[2])
            # every corner inside the wheel: its width and its radius
            rv = np.hypot(T[:, :, 1] - c[1], T[:, :, 2] - c[2])
            take = (np.abs(T[:, :, 0] - c[0]) < slab).all(1) & (rv <= lim).all(1)
            if not take.any():
                continue
            name = mats[r["mat"]].get("name", "") if r["mat"] is not None else ""
            ring = take & (rr > R0 * 0.98) if Rt > R0 * 1.02 and "paint" in name.lower() else np.zeros(len(take), bool)
            if ring.any():
                if rubber is None:
                    mats.append({"name": "SB_tyre_rubber", "pbrMetallicRoughness": {
                        "baseColorFactor": [0.03, 0.03, 0.032, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.9}})
                    rubber = len(mats) - 1
                recs.append(dict(r, I=r["I"][ring], rig=k, mat=rubber))
                n_tyre += int(ring.sum())
            rest = take & ~ring
            if rest.any():
                recs.append(dict(r, I=r["I"][rest], rig=k))
            r["I"] = r["I"][~take]
            moved[k] = moved.get(k, 0) + int(take.sum())
        if Rt > R0 * 1.02:
            log.setdefault("wheel_tyres_from_body", {})[k] = {"rim_d_m": round(2 * R0, 3), "tyre_d_m": round(2 * Rt, 3),
                                                              "rubber_triangles": n_tyre}
        C = [r["P"][r["I"]] for r in body]
    recs[:] = [r for r in recs if len(r["I"])]
    if moved:
        log["wheel_strays"] = moved
    return moved


def close_cracks(recs, paint_ids, log, tol=0.05, gap=0.004, small=0.02, turn=60):
    """A model whose painted panels do not meet (the 2022 Caddy: torn edges
    along the bonnet, the A-pillars and the roof rails, the dark cabin showing
    through in shards): each open edge's corners go onto the nearest open edge
    of another panel within 5 cm that faces the same way (within 60 degrees:
    a bonnet's edge rolls over onto the wing). Panels of one part
    are closed up; a door or a lid and the body keep a clean 4 mm shut line,
    each side moving half way. Pieces under 0.02 m2 (a handle's cover, a
    badge's surround) stay as they are. For a model listed as torn only: on a
    sound one this would close every shut line."""
    segs, verts = [], []
    pid = 0
    for ri, r in enumerate(recs):
        if r["mat"] not in paint_ids or not len(r["I"]):
            continue
        T = r["P"][r["I"]]
        lab, vid = islands(T, weld=1e-4)
        a, nrm = tri_area_normal(T)
        parts = np.unique(r["tri_part"], return_inverse=True)[1]
        key = lab * (parts.max() + 1) + parts          # a piece: one island, one part
        _, piece = np.unique(key, return_inverse=True)
        area = np.bincount(piece, weights=a)
        nv = int(vid.max()) + 1
        vn = np.zeros((nv, 3))
        np.add.at(vn, vid.ravel(), np.repeat(nrm * a[:, None], 3, axis=0))
        vn /= np.maximum(np.linalg.norm(vn, axis=1), 1e-12)[:, None]
        pos = np.zeros((nv, 3))
        pos[vid.ravel()] = T.reshape(-1, 3)
        orig = np.zeros(nv, int)                     # one of the rec's own vertices at each welded one
        orig[vid.ravel()] = r["I"].ravel()
        E = np.c_[vid[:, [0, 1]], vid[:, [1, 2]], vid[:, [2, 0]]].reshape(-1, 2)
        ep = np.repeat(piece, 3)
        Es = np.sort(E, axis=1)
        k = (Es[:, 0].astype(np.int64) * nv + Es[:, 1]) * (piece.max() + 1) + ep
        _, first, cnt = np.unique(k, return_index=True, return_counts=True)
        open_ = first[cnt == 1]                      # an edge one face of its piece uses
        if not len(open_):
            pid += piece.max() + 1
            continue
        big = area[ep[open_]] >= small
        e, epc = E[open_][big], ep[open_][big]
        prt = np.zeros(piece.max() + 1, object)
        prt[piece] = r["tri_part"]
        for (i, j), q in zip(e, epc):
            segs.append((pos[i], pos[j], vn[i] + vn[j], pid + q, prt[q]))
        bv = np.unique(e)
        vp = np.zeros(nv, int)
        vp[e[:, 0]] = epc
        vp[e[:, 1]] = epc
        verts.append((ri, bv, pos[bv], vn[bv], pid + vp[bv], prt[vp[bv]], vid, r["I"]))
        pid += piece.max() + 1
    if not segs:
        return 0
    A = np.array([x[0] for x in segs])
    B = np.array([x[1] for x in segs])
    SN = np.array([x[2] for x in segs])
    SN /= np.maximum(np.linalg.norm(SN, axis=1), 1e-12)[:, None]
    SP = np.array([x[3] for x in segs])
    SR = np.array([x[4] for x in segs], object)
    tree = cKDTree((A + B) / 2)
    reach = tol + np.linalg.norm(B - A, axis=1).max() / 2
    cos = np.cos(np.radians(turn))
    moved, closed, lines = 0, 0, 0
    for ri, bv, P, N, pids, prts, vid, I in verts:
        r = recs[ri]
        newpos = {}
        for i, cs in enumerate(tree.query_ball_point(P, reach)):
            cs = np.array([c for c in cs if SP[c] != pids[i]], int)
            if not len(cs):
                continue
            a, ab = A[cs], B[cs] - A[cs]
            t = np.clip(((P[i] - a) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-18), 0, 1)
            q = a + t[:, None] * ab
            d = np.linalg.norm(q - P[i], axis=1)
            ok = (d <= tol) & ((SN[cs] * N[i]).sum(1) > cos)
            if not ok.any():
                continue
            j = int(np.argmin(np.where(ok, d, np.inf)))
            if SR[cs[j]] == prts[i]:
                if d[j] > 1e-4:
                    newpos[bv[i]] = q[j]
                    closed += 1
            elif d[j] > 2 * gap:
                newpos[bv[i]] = P[i] + (q[j] - P[i]) * (0.5 - gap / 2 / d[j])
                lines += 1
        if newpos:
            r["P"] = r["P"].copy()
            w = vid.ravel()
            hit = np.isin(w, list(newpos))
            for k in np.flatnonzero(hit):
                r["P"][I.ravel()[k]] = newpos[w[k]]
            moved += len(newpos)
    if moved:
        log["cracks_closed"] = {"corners_moved": moved, "closed": closed, "to_shut_line": lines}
    return moved


def right_hand_drive(g, recs, mats, log, ground, xc):
    """A left-hand-drive model made right-hand drive (a UK car): the cabin
    mirrored across the car's centre plane, its steering wheel carried across
    whole (not mirrored, so its badge and buttons read the right way round).

    The cabin: every island (welded triangles) of the rig's cabin part or the
    body that lies wholly inside the cabin: within the door lines, under the
    roof, behind the dash (the front of the cabin part). The outer shell,
    doors, wheels and the engine bay stay. The driver's side is the one with
    the dense pieces of a steering wheel and its column in the metre behind
    the dash at hand height; a model already right-hand drive, or one whose
    wheel is not found, is left as it is (the log says which)."""
    cand = [(k, r) for k, r in enumerate(recs) if "tri_part" in r]
    rows = [(k, np.nonzero(np.isin(r["tri_part"], ("cabin", "body")))[0]) for k, r in cand]
    rows = [(k, ix) for k, ix in rows if len(ix)]
    if not rows:
        log["right_hand_drive"] = {"done": False, "why": "no cabin"}
        return
    T = np.vstack([recs[k]["P"][recs[k]["I"][ix]] for k, ix in rows])
    own = np.concatenate([np.full(len(ix), k) for k, ix in rows])
    row = np.concatenate([ix for _, ix in rows])
    cab = np.concatenate([np.full(len(ix), recs[k]["rig"] == "cabin") for k, ix in rows])   # the rigger's cabin (the finisher files it as body)
    if not cab.any():
        log["right_hand_drive"] = {"done": False, "why": "the rig found no cabin"}
        return
    lab, _ = islands(T)
    nl = lab.max() + 1
    flat, lab3 = T.reshape(-1, 3), np.repeat(lab, 3)
    lo, hi = np.full((nl, 3), np.inf), np.full((nl, 3), -np.inf)
    for a in range(3):
        np.minimum.at(lo[:, a], lab3, flat[:, a])
        np.maximum.at(hi[:, a], lab3, flat[:, a])
    body_half = float(np.abs(T[:, :, 0] - xc).max())
    roof = float(T[:, :, 1].max())
    # the front of the cabin part (its bulkhead: the pedals hang just behind
    # it, the 2025 M5's 25 cm forward of most of the dash)
    z_dash = float(np.percentile(T[cab][:, :, 2], 99.9))
    z_back = float(T[cab][:, :, 2].min())
    inside = ((np.maximum(np.abs(lo[:, 0] - xc), np.abs(hi[:, 0] - xc)) < body_half - 0.10)
              & (lo[:, 1] > ground + 0.10) & (hi[:, 1] < roof - 0.03)
              & (hi[:, 2] < z_dash + 0.05) & (lo[:, 2] > z_back - 0.05))
    # the driver's side: the steering wheel and its column, at hand height in the metre behind the dash
    c = (lo + hi) / 2
    xd = 0.37 * body_half / 0.99
    win = inside & (c[:, 1] > ground + 0.60) & (c[:, 1] < ground + 1.05) & (c[:, 2] > z_dash - 1.0)
    ntri = np.bincount(lab, minlength=nl)
    side_n = {sd: int(ntri[win & (np.abs(c[:, 0] - xc - sd * xd) < 0.18)].sum()) for sd in (1, -1)}
    drv = 1 if side_n[1] > side_n[-1] else -1
    if side_n[drv] < 500 or side_n[drv] < 2 * side_n[-drv]:
        log["right_hand_drive"] = {"done": False, "why": "the steering wheel's side is not clear", "triangles": side_n}
        return
    if drv == -1:
        log["right_hand_drive"] = {"done": False, "why": "the model is right-hand drive already"}
        return
    # the wheel: rim-sized pieces on the driver's side (one dimension 20-45 cm,
    # another under 20); its centre, then every piece within 24 cm of it moves whole
    s3 = hi - lo
    rim = win & (np.abs(c[:, 0] - xc - xd) < 0.18) & (s3.max(1) > 0.2) & (s3.max(1) < 0.45) & (s3.min(1) < 0.2)
    if not rim.any():
        log["right_hand_drive"] = {"done": False, "why": "no steering wheel rim found"}
        return
    wc = (c[rim] * ntri[rim, None]).sum(0) / ntri[rim].sum()
    # across, the middle of the rim's own span: the wheel is symmetric about it, so
    # the pieces carried across line up with those mirrored (the column under it)
    wc[0] = (lo[rim, 0].min() + hi[rim, 0].max()) / 2
    wheel = inside & (np.linalg.norm(np.maximum(np.abs(lo - wc), np.abs(hi - wc)), axis=1) < 0.24)
    move = inside & ~wheel
    dx = 2 * (wc[0] - xc)

    def own_verts(r, rows):
        # a vertex the triangles `rows` share with others of the record (a door
        # card cut from the same mesh, a piece outside the cabin): `rows` get
        # their own copy, so a moved triangle never drags a staying one with it
        other = np.ones(len(r["I"]), bool)
        other[rows] = False
        shared = np.intersect1d(np.unique(r["I"][rows]), np.unique(r["I"][other]))
        if not len(shared):
            return
        attr = r.get("attr") or {an: g.accessor(ai) for an, ai in r["prim"]["attributes"].items()
                                  if not an.startswith(("JOINTS", "WEIGHTS"))}
        nv = len(r["P"])
        r["P"] = np.vstack([r["P"], r["P"][shared]])
        r["attr"] = {an: np.vstack([A, A[shared]]) for an, A in attr.items()}
        remap = np.arange(nv + len(shared))
        remap[shared] = nv + np.arange(len(shared))
        I = r["I"].copy()
        I[rows] = remap[I[rows]]
        r["I"] = I
    n_m = n_w = 0
    for k in np.unique(own):
        r = recs[k]
        sel = own == k
        tm, tw = row[sel & move[lab]], row[sel & wheel[lab]]
        if len(tm):
            own_verts(r, tm)
            v = np.unique(r["I"][tm])
            r["P"] = r["P"].copy()
            r["P"][v, 0] = 2 * xc - r["P"][v, 0]
            mv = np.zeros(len(r["P"]), bool)
            mv[v] = True
            r["mirror_v"] = mv                               # normals and tangents turn with it (the rebuild)
            r["I"] = r["I"].copy()
            r["I"][tm] = r["I"][tm][:, [0, 2, 1]]          # a mirror turns a triangle over: wound back
            n_m += len(tm)
        if len(tw):
            own_verts(r, tw)
            v = np.unique(r["I"][tw])
            r["P"] = r["P"].copy()
            r["P"][v, 0] -= dx
            n_w += len(tw)
    log["right_hand_drive"] = {"done": True, "from": "left-hand drive", "cabin_triangles_mirrored": n_m,
                               "wheel_triangles_moved": n_w, "wheel_centre": [round(float(x), 3) for x in wc],
                               "wheel_moved_m": round(float(dx), 3)}


LAMPISH = re.compile(r"lamp|light|lens|indicat|reflect|brake|calip|badge|logo|emblem|^detail-|engine|bay|interior|seat|"
                     r"dash|leather|fabric|carpet|stitch|plate|licen|tail|rear.?l|marker|signal", re.I)


def _lin_to_lab(c):
    """CIE Lab of a glTF colour factor (linear RGB, D65)."""
    r, g_, b = (float(x) for x in c[:3])
    X = (0.4124 * r + 0.3576 * g_ + 0.1805 * b) / 0.95047
    Y = 0.2126 * r + 0.7152 * g_ + 0.0722 * b
    Z = (0.0193 * r + 0.1192 * g_ + 0.9505 * b) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116  # noqa: E731
    return 116 * f(Y) - 16, 500 * (f(X) - f(Y)), 200 * (f(Y) - f(Z))


# a material the model names as its paint ("carpaint", "Paint1", German "Lack"),
# never "black" (the "lack" in it painted black trim the body colour on 32 cars)
PAINT_NAME = re.compile(r"paint|(?<!b)lack", re.I)
PAINT_OR_BODY = re.compile(r"paint|(?<!b)lack|body", re.I)
WHEELISH = re.compile(r"wheel|\brims?\b|tyre|tire|hub ?cap", re.I)        # a wheel's material, by name
TRIMMISH = re.compile(r"chrome|rim\b|wheel|tyre|tire|glass|mirror|metal|steel|alu|grill|trim|plast|rubber|black|carbon|"
                      r"interior|dash|seat|floor|under|chassis|engine|exhaust|brake|calip|light|lamp|lens|logo|badge|plate", re.I)


def same_paint(mats, paint, glass, area=None):
    """Materials of the paint's own colour under other names: solid, not a
    lamp, badge or engine-bay part, the same clear hue. A white or silver
    paint's colour is many a trim's too: for one, only a material of its very
    tone, named as no trim, covering a panel's area (the Captur's front,
    "door_lf_ok.3", left silver on a blue car)."""
    pbr = mats[paint].get("pbrMetallicRoughness") or {}
    if "baseColorTexture" in pbr:
        return set()
    L0, a0, b0 = _lin_to_lab(pbr.get("baseColorFactor") or [1, 1, 1])
    C0 = math.hypot(a0, b0)
    h0 = math.degrees(math.atan2(b0, a0))
    out = set()
    for i, m in enumerate(mats):
        p = m.get("pbrMetallicRoughness") or {}
        if i == paint or i in glass or m.get("alphaMode") == "BLEND" or "baseColorTexture" in p or LAMPISH.search(m.get("name", "")):
            continue
        L, a, b = _lin_to_lab(p.get("baseColorFactor") or [1, 1, 1])
        C, h = math.hypot(a, b), math.degrees(math.atan2(b, a))
        if C0 >= 20:
            # (never a wheel's or an inside's, whatever its colour: the 2022
            # Swift's "WHEEL_BLACK_MAT" is its paint's red, and was painted on
            # eight cars made from it)
            if C > 0.6 * C0 and abs((h - h0 + 180) % 360 - 180) < 15 and abs(L - L0) < 25 \
                    and not WHEELISH.search(m.get("name", "")) and not INSIDE.search(m.get("name", "")):
                out.add(i)
        elif L0 > 55 and C < 6 and abs(L - L0) < 6 and not TRIMMISH.search(m.get("name", "")) \
                and area is not None and area.get(i, 0) >= 0.15:
            out.add(i)
    return out


def wheels_in_paint(mats, paint, glass):
    """A wheel's material coloured in the model's own paint (the 2022 Swift's
    "WHEEL_BLACK_MAT" is its paint's red): shown red on a white car made
    from it. Named for a wheel, untextured, the paint's clear hue."""
    pbr = mats[paint].get("pbrMetallicRoughness") or {}
    if "baseColorTexture" in pbr:
        return set()
    L0, a0, b0 = _lin_to_lab(pbr.get("baseColorFactor") or [1, 1, 1])
    C0, h0 = math.hypot(a0, b0), math.degrees(math.atan2(b0, a0))
    if C0 < 20:
        return set()
    out = set()
    for i, m in enumerate(mats):
        p = m.get("pbrMetallicRoughness") or {}
        if i == paint or i in glass or "baseColorTexture" in p or not WHEELISH.search(m.get("name", "")):
            continue
        L, a, b = _lin_to_lab(p.get("baseColorFactor") or [1, 1, 1])
        C, h = math.hypot(a, b), math.degrees(math.atan2(b, a))
        if C > 0.6 * C0 and abs((h - h0 + 180) % 360 - 180) < 15 and abs(L - L0) < 25:
            out.add(i)
    return out


def _paint_one(pm, spec, j):
    """The colour asked for (sRGB 0-255) on one paint material."""
    pbr = pm.setdefault("pbrMetallicRoughness", {})
    pbr.pop("baseColorTexture", None)
    lin = [float(c / 255 / 12.92 if c / 255 <= 0.04045 else ((c / 255 + 0.055) / 1.055) ** 2.4) for c in spec["paint"][:3]]
    pbr["baseColorFactor"] = lin + [1.0]
    # the finish follows the colour, not the model's paint: white on the 2001
    # Yaris's metallic silver (metallic 0.8) read as silver. A silver
    # (colourless and light) is lightly metallic: at 0.6 it showed mid grey
    # in the studio (the build review's commonest colour fault); a mid grey
    # is solid, metal darkened it to gunmetal
    r_, g_, b_ = spec["paint"][:3]
    light, chroma = (max(r_, g_, b_) + min(r_, g_, b_)) / 2, max(r_, g_, b_) - min(r_, g_, b_)
    metallic = spec.get("paint_metallic", 0.25 if chroma < 20 and 150 < light < 215 else 0.0)
    pbr["metallicFactor"] = float(metallic)
    pbr["roughnessFactor"] = 0.3 if metallic else 0.35
    pbr.pop("metallicRoughnessTexture", None)
    sp = (pm.get("extensions") or {}).get("KHR_materials_specular")
    if sp:                                      # a specular map painted for the old colour
        sp.pop("specularTexture", None)
        sp.pop("specularColorTexture", None)
    # a car's paint is lacquered: a clear coat over the colour gives the sharp
    # reflections a photo of the car shows
    pm.setdefault("extensions", {})["KHR_materials_clearcoat"] = {"clearcoatFactor": 1.0, "clearcoatRoughnessFactor": 0.04}
    if "KHR_materials_clearcoat" not in j.setdefault("extensionsUsed", []):
        j["extensionsUsed"].append("KHR_materials_clearcoat")


# a roof's glass or opening by its name: it stays dark when the roof is painted
ROOF_GLASS = re.compile(r"glass|vitre|window|sunroof|moonroof|pano|screen", re.I)


def _edge_pairs(T, weld):
    """Triangles of T sharing an edge, as index arrays (a, b), both ways."""
    _, vid = islands(T, weld)
    e = np.sort(np.stack([vid[:, [0, 1]], vid[:, [1, 2]], vid[:, [2, 0]]], 1), axis=2).reshape(-1, 2)
    key = e[:, 0] * (int(vid.max()) + 1) + e[:, 1]
    o = np.argsort(key, kind="stable")
    k, t = key[o], np.repeat(np.arange(len(T)), 3)[o]
    same = k[1:] == k[:-1]
    a, b = t[:-1][same], t[1:][same]
    return np.concatenate([a, b]), np.concatenate([b, a])


def roof_in_paint(g, mats, paint, painted, glass, waist=0.78, band=0.06, up=0.5, share=0.05, crumb=0.005, colour=None):
    """A roof in another colour than the body, left from a stand-in's donor
    (the bZ4X's and the 2008's black roofs on the white Fiat 600, Lexus RZ and
    Omoda 9 made from them, in the build review): the roof takes the paint.
    The roof is the up-facing skin over WAIST of the car's height, in pieces
    that reach over the glasshouse, whole: a roof sloping to the tail is
    painted to its end (the top tenth only left most of the Captur's black),
    and one modelled in strips is painted strip by strip (the RAV4's, each
    under 5% of the car). A glass roof lying flat on top (the 207's) is a
    roof too; a windscreen never. It is done when it comes to SHARE of the
    car's footprint or more; crumbs (under CRUMB: an aerial's) keep theirs,
    as do lamps, the cabin and a mesh used twice.
    With COLOUR (sRGB), a roof of that colour on the body's paint (the
    Captur's and the Mini's white roofs): the paint's own top too, in a
    material of its own made from the paint's."""
    j = g.j
    W, _ = g.world_matrices()
    uses = {}
    for n in j["nodes"]:
        if "mesh" in n:
            uses[n["mesh"]] = uses.get(n["mesh"], 0) + 1
    wheel_y, body_v, body_t, cand, glass_v = [], [], [], [], []
    for ni, n in enumerate(j["nodes"]):
        if "mesh" not in n:
            continue
        is_wheel = bool(re.match(r"(?:SB_)?wheel", n.get("name") or ""))
        for p in j["meshes"][n["mesh"]]["primitives"]:
            if p.get("mode", 4) != 4 or "indices" not in p:
                continue
            P = g.accessor(p["attributes"]["POSITION"]) @ W[ni][:3, :3].T + W[ni][:3, 3]
            if is_wheel:
                wheel_y.append(float(P[:, 1].min()))
                continue
            I = g.accessor(p["indices"]).ravel().astype(np.int64)
            I = I[:len(I) // 3 * 3].reshape(-1, 3)
            body_v.append(P)
            if p.get("material") in glass or (p.get("material") is not None
                                              and mats[p["material"]].get("alphaMode") == "BLEND"):
                glass_v.append(P[I])
            a_, _ = tri_area_normal(P[I])
            body_t.append((P[I][:, :, 1].mean(1), a_))
            m = p.get("material")
            if m is None or (colour is None and (m == paint or m in painted)) or uses[n["mesh"]] > 1 or p.get("targets"):
                continue
            name = mats[m].get("name", "")
            is_glass = m in glass or mats[m].get("alphaMode") == "BLEND" or bool(ROOF_GLASS.search(name))
            if (LAMPISH.search(name) or INSIDE.search(name)) and not is_glass:
                continue
            cand.append((p, P, I, is_glass))
    if not cand or not wheel_y or not body_v:
        return None
    V = np.vstack(body_v)
    # the top by the skin's area, not its corners: an aerial's thousand
    # corners stood over the Captur's roof, and no roof reached that top
    ty = np.concatenate([t for t, _ in body_t])
    ta = np.concatenate([a for _, a in body_t])
    o = np.argsort(ty)
    cum = np.cumsum(ta[o])
    ground = min(wheel_y)
    top = float(ty[o][min(np.searchsorted(cum, 0.998 * cum[-1]), len(o) - 1)]) if cum[-1] > 0 else float(V[:, 1].max())
    x0, x1 = np.percentile(V[:, 0], [0.5, 99.5])
    z0, z1 = np.percentile(V[:, 2], [0.5, 99.5])
    foot = float((x1 - x0) * (z1 - z0))
    h = top - ground
    from scipy.spatial import cKDTree
    G = [P[I] for p, P, I, is_glass in cand if is_glass] + glass_v
    G = np.vstack(G) if G else np.zeros((0, 3, 3))
    glass_pts = cKDTree(surface_points(G, 0.01 * h)) if len(G) else None
    picks, Ts = [], []
    for p, P, I, is_glass in cand:
        T = P[I]
        _, nrm = tri_area_normal(T)
        cy = T.mean(1)[:, 1]
        if is_glass:
            # a glass roof: a pane lying flat on top, the whole pane; a
            # windscreen's top strip curves flat into the roof too, and was
            # painted (the Fiat 600's, the Captur's: a patch of body colour
            # round the mirror's mount, in round 2), but most of it is raked
            a_, _ = tri_area_normal(T)
            gl, _ = islands(T, weld=1e-3 * max(top - ground, 1e-6) / 1.5)
            flat_a = np.bincount(gl, weights=a_ * (nrm[:, 1] > 0.92))
            all_a = np.maximum(np.bincount(gl, weights=a_), 1e-12)
            gy = np.bincount(gl, weights=a_ * cy) / all_a
            pane = (flat_a / all_a >= 0.7) & (gy > top - band * (top - ground))
            sel = np.where(pane[gl])[0]
        else:
            sel = np.where((nrm[:, 1] > up) & (cy > ground + waist * h))[0]
        if len(sel) and not is_glass and glass_pts is not None:
            # never what lies on the glass: a windscreen's dotted black band,
            # the mirror's housing, the trims along the windows (painted, they
            # were patches of body colour on the windscreen and the A-pillars
            # of 18 builds, in round 3); a roof's own sides stay as they are.
            # The glass by its surface, not its corners: the Fiat 600's
            # windscreen is two triangles, its band far from their corners
            near = np.isfinite(glass_pts.query(T[sel].mean(1), distance_upper_bound=0.02 * h)[0])
            if near.any():
                # but one near glass among painted ones, two of its edges on
                # them, is the roof's own edge over a windscreen running on
                # under it (the RAV4's): left, its edge was a saw's teeth
                a_, b_ = _edge_pairs(T[sel], 1e-3 * h / 1.5)
                near &= np.bincount(a_, weights=~near[b_], minlength=len(sel)) < 2
                sel = sel[~near]
        if len(sel):
            picks.append((p, I, sel))
            Ts.append(T[sel])
    if not Ts:
        return None
    T = np.vstack(Ts)
    area, _ = tri_area_normal(T)
    # the pieces, each of one material: a trim touching the roof's edge is
    # not the roof
    tm = np.concatenate([np.full(len(sel), p.get("material")) for p, _, sel in picks])
    lab = np.zeros(len(T), np.int64)
    nxt = 0
    for m_ in np.unique(tm):
        w_ = np.where(tm == m_)[0]
        l_, _ = islands(T[w_], weld=1e-3 * max(h, 1e-6) / 1.5)
        lab[w_] = l_ + nxt
        nxt += int(l_.max()) + 1
    hi = np.full(lab.max() + 1, -np.inf)
    np.maximum.at(hi, lab, T[:, :, 1].max(1))
    # pieces over the glasshouse (their top over 82% of the height: a roof's
    # rear section stepping down to the tail counts, which 88% left in the
    # donor's colour on the Kona, the Compass, the bZ4X) that cross the middle
    # of the car, no crumbs: roof rails and window trims run along its sides
    # (the RAV4's, its BlackChrome and WindowsTrims), a roof across
    xc, xw = (x0 + x1) / 2, x1 - x0
    lo_x = np.full(lab.max() + 1, np.inf)
    hi_x = np.full(lab.max() + 1, -np.inf)
    np.minimum.at(lo_x, lab, T[:, :, 0].min(1))
    np.maximum.at(hi_x, lab, T[:, :, 0].max(1))
    mid = (lo_x < xc - 0.1 * xw) & (hi_x > xc + 0.1 * xw)
    keep_isl = (np.bincount(lab, weights=area) >= crumb * foot) & (hi >= ground + 0.82 * h) & mid
    keep = keep_isl[lab]
    mid_t = keep & (T[:, :, 0].min(1) < xc + 0.1 * xw) & (T[:, :, 0].max(1) > xc - 0.1 * xw)
    if mid_t.any():
        # nothing ahead of the roof's own front edge at the middle: the
        # A-pillars, the donor's roof running down beside the windscreen from
        # its corners (a wedge of the Fiat 600's was left in body colour)
        keep &= T.mean(1)[:, 2] <= T[mid_t][:, :, 2].max() + 0.005 * h
    if area[keep].sum() < share * foot:
        return None
    to = paint
    if colour is not None:
        import copy
        rm = copy.deepcopy(mats[paint])
        rm["name"] = (rm.get("name") or "paint") + "_roof"
        _paint_one(rm, {"paint": list(colour)}, j)
        mats.append(rm)
        to = len(mats) - 1
    out, at, names = 0, 0, set()
    for p, I, sel in picks:
        k = keep[at:at + len(sel)]
        at += len(sel)
        mine = sel[k]
        if not len(mine):
            continue
        names.add(mats[p["material"]].get("name"))
        rest = np.setdiff1d(np.arange(len(I)), mine)
        q = {kk: v for kk, v in p.items() if kk not in ("indices", "material")}
        q["indices"] = g.add_accessor(I[mine].ravel().astype(np.uint32), ctype=5125, atype="SCALAR", target=34963)
        q["material"] = to
        if len(rest):
            p["indices"] = g.add_accessor(I[rest].ravel().astype(np.uint32), ctype=5125, atype="SCALAR", target=34963)
            for mesh in j["meshes"]:
                if any(x is p for x in mesh["primitives"]):
                    mesh["primitives"].append(q)
                    break
        else:
            p.clear()
            p.update(q)
        out += len(mine)
    return {"triangles": int(out), "share_of_footprint": round(float(area[keep].sum()) / foot, 3),
            "materials": sorted(n for n in names if n), **({"colour": list(colour)} if colour is not None else {})}


def _corner_attrs(g, attrs, S):
    """The other vertex attributes (UVs, colours, tangents) of the triangles S
    (k, 3), one value a corner, for a primitive remade on corners of its own."""
    out = {}
    for an, ai in attrs.items():
        if an in ("POSITION", "NORMAL") or an.startswith(("JOINTS", "WEIGHTS")):
            continue
        A = g.accessor(ai)
        A = A.reshape(len(A), -1)
        out[an] = g.add_accessor(A[S].reshape(-1, A.shape[1]).astype(np.float32), target=34962)
    return out


def mend_normals(g, mat_ids, cos_max=0.26):
    """A model's shading broken on its paint: triangles whose corners' normals
    point 75 degrees or more off their own face (the Sprinter's rear quarter,
    lit as grey triangles on every van made from it, in the build review) are
    put on corners of their own, flat, by their face."""
    j, n_tri = g.j, 0
    for mesh in j["meshes"]:
        new = []
        for p in mesh["primitives"]:
            at = p.get("attributes") or {}
            if p.get("mode", 4) != 4 or "indices" not in p or p.get("material") not in mat_ids or "NORMAL" not in at \
                    or p.get("targets"):
                continue
            P = g.accessor(at["POSITION"]).astype(np.float64)
            N = g.accessor(at["NORMAL"]).astype(np.float64)
            I = g.accessor(p["indices"]).ravel().astype(np.int64)
            I = I[:len(I) // 3 * 3].reshape(-1, 3)
            area, fn = tri_area_normal(P[I])
            nv = N[I] / np.maximum(np.linalg.norm(N[I], axis=2, keepdims=True), 1e-12)
            bad = (np.einsum("kcj,kj->kc", nv, fn) < cos_max).any(1) & (area > 1e-7)
            if not bad.any() or bad.all():
                continue                         # all of it: the model's way, not a fault in places
            S = I[bad]
            p["indices"] = g.add_accessor(I[~bad].ravel().astype(np.uint32), ctype=5125, atype="SCALAR", target=34963)
            q = {k: v for k, v in p.items() if k not in ("indices", "attributes")}
            q["attributes"] = {"POSITION": g.add_accessor(P[S].reshape(-1, 3).astype(np.float32), minmax=True, target=34962),
                               "NORMAL": g.add_accessor(np.repeat(fn[bad], 3, axis=0).astype(np.float32), target=34962)}
            q["attributes"].update(_corner_attrs(g, at, S))
            q["indices"] = g.add_accessor(np.arange(S.size, dtype=np.uint32), ctype=5125, atype="SCALAR", target=34963)
            new.append(q)
            n_tri += int(bad.sum())
        mesh["primitives"].extend(new)
    return n_tri


# a material of the car's inside, by its name: "Interior", "internal", "Carro_Interno", a seat's (not
# "carpaint.198": the "int." in it is the paint's)
INSIDE = re.compile(r"(?:^|[^a-z])int(?:erior|ernal|erno)?(?![a-z])|interior|internal|interno|seat|leather|"
                    r"fabric|carpet|cloth", re.I)


def panel_sides(g, glass, paint):
    """A panel van's sides behind the cab are steel: its model's side glass
    there (a windowed minibus's, the Sprinter file's) takes the body's paint.
    Behind the front doors' rear edge, facing sideways; the windscreen, the
    cab's own windows and the back doors' glass stay."""
    j = g.j
    W, _ = g.world_matrices()
    rear_edges = []
    for ni, n in enumerate(j["nodes"]):
        # by now a door's piece is its own node under its hinge ("door_fl")
        if "mesh" in n and re.match(r"(?:SB_)?door_f[lr](?:__\d+)?$", n.get("name") or ""):
            for p in j["meshes"][n["mesh"]]["primitives"]:
                P = g.accessor(p["attributes"]["POSITION"])
                rear_edges.append(float((P @ W[ni][:3, :3].T + W[ni][:3, 3])[:, 2].min()))
    if not rear_edges:
        return {"skipped": "no front doors found"}
    zb = min(rear_edges) - 0.02
    cx = float(np.mean([W[ni][0, 3] for ni, n in enumerate(j["nodes"]) if re.match(r"(?:SB_)?door_f[lr](?:__\d+)?$", n.get("name") or "")]))
    n_tri, meshes = 0, set()
    mats = j["materials"]

    def seal(i):
        # a window's rubber: dark, untextured or named so
        m = mats[i] if i is not None and i < len(mats) else {}
        pbr = m.get("pbrMetallicRoughness") or {}
        c = (pbr.get("baseColorFactor") or [1, 1, 1])[:3]
        return bool(re.search(r"rubber|seal|gasket|window.?(?:frame|trim)|black", m.get("name", ""), re.I)) \
            or ("baseColorTexture" not in pbr and max(c) < 0.06)
    panes = []                                  # the blanked glass's centres: its seals lie round them
    for stage in ("glass", "seals"):
        if stage == "seals":
            if not panes:
                break
            from scipy.spatial import cKDTree
            near = cKDTree(np.vstack(panes))
        n_tri, meshes = _panel_stage(g, j, W, glass, paint, zb, cx, stage, seal, panes,
                                     near if stage == "seals" else None, n_tri, meshes)
    return {"behind_z": round(zb, 3), "triangles": n_tri, "meshes": sorted(meshes)[:12]}


def _panel_stage(g, j, W, glass, paint, zb, cx, stage, seal, panes, near, n_tri, meshes):
    for ni, n in enumerate(j["nodes"]):
        if "mesh" not in n:
            continue
        mesh, M = j["meshes"][n["mesh"]], W[ni]
        new = []
        for p in mesh["primitives"]:
            if p.get("mode", 4) != 4 or "indices" not in p or p.get("targets"):
                continue
            if (stage == "glass") != (p.get("material") in glass) or (stage == "seals" and not seal(p.get("material"))):
                continue
            P = g.accessor(p["attributes"]["POSITION"]) @ M[:3, :3].T + M[:3, 3]
            I = g.accessor(p["indices"]).ravel().astype(np.int64)
            I = I[:len(I) // 3 * 3].reshape(-1, 3)
            T = P[I]
            _, nrm = tri_area_normal(T)
            sel = (np.abs(nrm[:, 0]) > 0.5) & (T.mean(1)[:, 2] < zb)
            if stage == "seals" and sel.any():
                d, _ = near.query(T.mean(1)[sel], distance_upper_bound=0.06)
                sel[np.where(sel)[0][~np.isfinite(d)]] = False
            if not sel.any():
                continue
            if stage == "glass":
                panes.append(T.mean(1)[sel])
            # the paint is one-sided: each panel turned to face out (a pane
            # modelled facing in would show the cabin through it), on corners
            # of its own whose normals face out too: turned on the glass's
            # shared corners, a pane lit from inside came out grey triangles
            # among white ones (the Sprinter's, in the build review)
            S = I[sel].copy()
            inward = np.sign(nrm[sel, 0]) != np.sign(T[sel].mean(1)[:, 0] - cx)
            S[inward] = S[inward][:, ::-1]
            if not sel.all():
                p["indices"] = g.add_accessor(I[~sel].ravel().astype(np.uint32), ctype=5125, atype="SCALAR", target=34963)
            # the pane's own smooth normals, each turned out where it faced in
            # (a flat one a triangle each showed the studio's reflection in patches)
            out_side = np.sign(T[sel].mean(1)[:, 0] - cx)[:, None]
            if "NORMAL" in p["attributes"]:
                N = g.accessor(p["attributes"]["NORMAL"])[S].astype(np.float64)          # (k, 3, 3), the node's frame
                facing = np.sign((N @ np.linalg.pinv(M[:3, :3]))[..., 0]) * out_side     # a normal goes by the inverse
                N *= np.where(facing < 0, -1.0, 1.0)[..., None]
            else:
                f_ = nrm[sel] * np.where(inward, -1.0, 1.0)[:, None] @ M[:3, :3]     # a normal goes by the transpose
                N = np.repeat(f_[:, None, :], 3, axis=1)
            N = N.reshape(-1, 3)
            N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
            P0 = g.accessor(p["attributes"]["POSITION"])
            q = {k: v for k, v in p.items() if k not in ("indices", "material", "attributes")}
            q["attributes"] = {"POSITION": g.add_accessor(P0[S].reshape(-1, 3).astype(np.float32), minmax=True, target=34962),
                               "NORMAL": g.add_accessor(N.astype(np.float32), target=34962)}
            q["attributes"].update(_corner_attrs(g, p["attributes"], S))
            q["indices"] = g.add_accessor(np.arange(S.size, dtype=np.uint32), ctype=5125, atype="SCALAR", target=34963)
            q["material"] = paint
            if sel.all():
                p.clear()
                p.update(q)
            else:
                new.append(q)
            n_tri += int(sel.sum())
            meshes.add(mesh.get("name") or n.get("name") or str(ni))
        mesh["primitives"].extend(new)
    return n_tri, meshes


def finish(src, spec, out, base_dir="."):
    log = {"src": os.path.basename(src)}
    # parts a person set by hand in the Studio stand as they are: no search,
    # no cut, no trims added
    manual = set(spec.get("manual") or [])
    if manual:
        log["manual"] = sorted(manual)
    # a rear-engined car (the 911): the engine under the rear lid, which is
    # the engine lid behind a fixed rear window; the front lid opens on the
    # luggage space
    rear_engine = spec.get("layout") == "rear"
    if rear_engine:
        log["layout"] = "rear engine"
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


    # a wheel modelled inside out (the 2017 Golf's front left, seen from its
    # side) shows its inner faces: drawn from both sides, it is solid
    for r in recs:
        if r["rig"].startswith("wheel_") and r["mat"] is not None:
            mats[r["mat"]]["doubleSided"] = True

    # ── frame: wheels give the axles, the ground and the track ──
    if not any(p.startswith("wheel_") for p in manual):
        wheel_outliers(recs, log)
    wc = {}
    for r in recs:
        if r["rig"].startswith("wheel_"):
            wc.setdefault(r["rig"], []).append(r["P"][np.unique(r["I"])])
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
    # a wheel's pieces left in the body go to the wheel (its tyre turns
    # rubber), after the car is measured: its frame and sizes stay as they were
    if not any(p.startswith("wheel_") for p in manual):
        wheel_strays(recs, mats, log)
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
        w_ = np.array([0.5 if INSIDE.search(m.get("name", "")) else 1.0 for m in mats] + [1.0])
        np.add.at(door_area, ms[sk], a_[sk] * w_[ms[sk]])
    paint = int(door_area.argmax())
    # a door card or sill moulding of colourless near-black plastic lying ON
    # the door skin (the 1998 Micra's `Material.003`, no thickness between
    # them) outweighs the paint: the rig's own pick from the doors' outer
    # faces (renamed `…_paint`) wins when it has 40% of that area
    def dark_plastic(m):
        pbr = m.get("pbrMetallicRoughness") or {}
        c = (pbr.get("baseColorFactor") or [1, 1, 1])[:3]
        return "baseColorTexture" not in pbr and max(c) < 0.05 and max(c) - min(c) < 0.01
    if paint < nm and dark_plastic(mats[paint]) and "paint" not in mats[paint].get("name", "").lower():
        alt = [i for i in range(nm) if "paint" in mats[i].get("name", "").lower() and not dark_plastic(mats[i])
               and door_area[i] >= 0.4 * door_area[paint]]
        if alt:
            log["paint_over_plastic"] = mats[paint].get("name")
            paint = max(alt, key=lambda i: door_area[i])
    # a material the model names as its paint, nearly as much of the side as
    # one it does not (the 2017 Countryman's "varnish_paint" over a "panel"
    # under it): the named one is the paint seen
    if paint < nm and not PAINT_OR_BODY.search(mats[paint].get("name", "")):
        named = [i for i in range(nm) if PAINT_NAME.search(mats[i].get("name", ""))
                 and not mats[i].get("name", "").startswith("detail-") and door_area[i] >= 0.6 * door_area[paint]]
        if named:
            log["paint_by_name_over"] = mats[paint].get("name")
            paint = max(named, key=lambda i: door_area[i])
    # an inside's material (the Levante's textured "internal", the Courier's
    # "Interior") showing through a thin door skin is never the paint when a
    # paint-named one has a real share of the side (the build review: five
    # cars kept their model's colour, the photo's painted on their insides)
    if paint < nm and INSIDE.search(mats[paint].get("name", "")):
        named = [i for i in range(nm) if PAINT_OR_BODY.search(mats[i].get("name", ""))
                 and not INSIDE.search(mats[i].get("name", "")) and door_area[i] >= 0.25 * door_area[paint]]
        if named:
            log["paint_over_inside"] = mats[paint].get("name")
            paint = max(named, key=lambda i: door_area[i])
    log["paint"] = mats[paint].get("name")
    log["paint_side_m2"] = {mats[i].get("name") if i < nm else "-": round(float(door_area[i]), 3)
                            for i in np.argsort(-door_area)[:3] if door_area[i] > 0}
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
    # Tinted windows: a blended, colourless material too dark or too opaque
    # for clear glass (the 1998 Micra's grey at 0.79), any name, with over a
    # square metre above the waist, all round the car (front and back of the
    # cabin, both sides): no lamp or trim covers that
    for i, m in enumerate(mats):
        if i in glass or m.get("alphaMode") != "BLEND":
            continue
        c = m.get("pbrMetallicRoughness", {}).get("baseColorFactor", [1, 1, 1, 1])
        if not (c[3] < 0.9 and max(c[:3]) - min(c[:3]) < 0.08):
            continue
        Tu = [t[t.mean(1)[:, 1] > waist] for t in (tris(r) for r in recs if r["mat"] == i)]
        Tu = np.vstack(Tu) if Tu else np.zeros((0, 3, 3))
        if not len(Tu) or float(tri_area_normal(Tu)[0].sum()) < 1.0:
            continue
        cu = Tu.mean(1)
        if (cu[:, 0] > 0.3).any() and (cu[:, 0] < -0.3).any() and (cu[:, 2] > zr + 0.3 * (zf - zr)).any() \
                and (cu[:, 2] < zr + 0.2 * (zf - zr)).any():
            glass.add(i)
            log.setdefault("glass_tinted", []).append(m.get("name"))

    label = np.array(["body"] * nl, dtype=object)
    glass_m2 = mat_area[:, sorted(glass)].sum(1) if glass else np.zeros(nl)

    # bonnet: the largest flat paint island over the front of the car
    cand = [i for i in range(nl) if dom[i] == paint and cz[i] > zf - 0.35 and up[i] > 0.5 and hi[i, 1] > wheel_top]
    if "bonnet" in manual:
        cand = []
        log["bonnet"] = {"from": "the Studio"}
    bonnet = clip = None
    # the model's own bonnet first: the piece the rig machine took by its
    # name. The wings and front panel welded into one larger piece (the 2026
    # G-Class's) are not it, though bigger
    rig_b = np.concatenate([np.full(len(r["I"]), r["rig"] == "panel_bonnet") for r in body])
    own_b = np.bincount(lab, weights=area * rig_b, minlength=nl) / np.maximum(isl_area, 1e-12)
    named_b = [i for i in cand if own_b[i] > 0.5 and isl_area[i] > 0.5]
    if named_b:
        cand = named_b
        log["bonnet_named"] = True
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
    # the model's own tailgate, rear window and all (the rig machine took it
    # by its name), stands: the box below would take the lamps beside it (the
    # G-Class's sit on the body, its door swings between them)
    rig_tg0 = np.concatenate([np.full(len(r["I"]), r["rig"] == "tailgate") for r in body])
    named_tg = area[grear].sum() > 0.15 and area[grear & rig_tg0].sum() > 0.5 * area[grear].sum()
    if named_tg:
        log["tailgate_named"] = True
    # A panel van has no rear window to start from (the NV200's back is all
    # steel): the opening is then the van's painted back. Sides: inside the
    # tail lamps in the rear pillars; top: just under the roof's edge; bottom:
    # going down the back off-centre (the number plate's recess is not a
    # step), the first step back of 2 cm or more, which is the bumper's top.
    # The back leans forward as it rises (17 cm on the NV200), so it is taken
    # by its facing, not by its depth. The barn-door split further on halves
    # it. A van with rear glass, or a back its model names, is found as before.
    van_back = None
    if area[grear].sum() <= 0.15 and spec.get("body_family") == "van" and "tailgate" not in manual and not named_tg \
            and (tmat == paint).any():
        zmin_v = float(T[tmat == paint].reshape(-1, 3)[:, 2].min())
        back_paint_v = (tmat == paint) & (tri_c[:, 2] < min(zr, zmin_v + 0.35)) & (nrm[:, 2] < -0.6) \
            & (tri_c[:, 1] > ground + 0.9 * (wheel_top - ground))
        if area[back_paint_v].sum() > 0.6:
            Pb_v = T[back_paint_v].reshape(-1, 3)
            xh_v = float(np.percentile(np.abs(Pb_v[:, 0]), 98)) - 0.10
            ytop_v = float(np.percentile(Pb_v[:, 1], 99)) - 0.04
            # the tail lamps in the rear pillars, under the roof
            li_v = tail_lamps_inside(T, tmat, nrm, [i for i in range(nm) if i not in paint_ids and lamp_lens(mats[i])],
                                     zmin_v, ground + 0.9 * (wheel_top - ground), ytop_v - 0.15)
            if li_v is not None:
                xh_v = min(xh_v, li_v - 0.02)
            # the bumper's top, as for a welded tailgate below, everything but
            # glass; at least 40 cm under the roof's edge
            keep_v = ~np.isin(tmat, list(glass))
            ybot_v = bumper_top(T, keep_v, 0.25, max(0.45, 0.6 * xh_v), ytop_v, ground + 0.3 * (wheel_top - ground),
                                zmin_v + 0.35, below=0.40, painted=np.isin(tmat, list(paint_ids)))
            # the back's front edge: the most forward of its rearmost surface
            # (in 1 cm steps) along the top 40 cm
            Pt_v = T[keep_v].reshape(-1, 3)
            Pt_v = Pt_v[(np.abs(Pt_v[:, 0]) > 0.25) & (np.abs(Pt_v[:, 0]) < max(0.45, 0.6 * xh_v))
                        & (Pt_v[:, 1] <= ytop_v) & (Pt_v[:, 1] > ytop_v - 0.41) & (Pt_v[:, 2] < zmin_v + 0.35)]
            if len(Pt_v):
                rb_v = np.full(41, np.inf)
                np.minimum.at(rb_v, np.floor((ytop_v - Pt_v[:, 1]) / 0.01).astype(np.int64), Pt_v[:, 2])
                rb_v = rb_v[np.isfinite(rb_v)]
            if xh_v > 0.3 and ybot_v is not None and ytop_v - ybot_v > 0.6 and len(Pt_v):
                van_back = {"x_half": xh_v, "top_y": ytop_v, "bottom_y": ybot_v, "z_front": float(rb_v.max()) + 0.05,
                            "m2": float(area[back_paint_v].sum())}
                log["van_back"] = {k: round(v, 3) for k, v in van_back.items()}
    if (area[grear].sum() > 0.15 or van_back) and "tailgate" not in manual and not named_tg:
        if van_back:
            rw_m2 = van_back["m2"]
            xb, zfront, ybot = van_back["x_half"], van_back["z_front"], van_back["bottom_y"]
        else:
            Rv = T[grear].reshape(-1, 3)
            rw_lo, rw_hi, rw_cz, rw_m2 = Rv.min(0), Rv.max(0), float(tri_c[grear, 2].mean()), float(area[grear].sum())
            xb = max(abs(rw_lo[0]), abs(rw_hi[0])) + 0.08
            zfront = rw_hi[2] + 0.10
            under = [i for i in range(nl) if dom[i] == paint and abs(hi[i, 1] - rw_lo[1]) < 0.04
                     and cz[i] < rw_cz and max(abs(lo[i, 0]), abs(hi[i, 0])) < xb and isl_area[i] > 0.1]
            ybot = (min(lo[i, 1] for i in under) if under else rw_lo[1] - 0.35) - 0.01
        if rear_engine:
            # the engine lid: from the rear window's lower edge back, above the
            # rear lamps (the 992's light bar stays on the body), the window
            # fixed. The lamps: the backward-facing lamp triangles behind the
            # rear axle, under the window; their main band (most lamp area:
            # the light bar, not the third brake light in the wing) and its top
            zfront = rw_lo[2] + 0.01
            lamp_m = [i for i in range(nm) if re.search(r"lamp|light|lens|reflector|indicator|signal|brake|stop",
                                                         mats[i].get("name", ""), re.I)]
            lt = np.isin(tmat, lamp_m) & (tri_c[:, 2] < zr) & (tri_c[:, 1] < rw_lo[1]) & (nrm[:, 2] < -0.5)
            ybot = rw_lo[1] - 0.25
            if area[lt].sum() > 0.005:
                ly, la = tri_c[lt, 1], area[lt]
                o = np.argsort(ly)
                main = float(ly[o][np.searchsorted(np.cumsum(la[o]), la.sum() / 2)])
                band = np.abs(T[lt].reshape(-1, 3)[:, 1] - main) < 0.08
                ybot = float(np.percentile(T[lt].reshape(-1, 3)[band, 1], 98))
            ybot += 0.01
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
        if van_back:                           # the high brake light on the roof stays
            inside &= hi[:, 1] <= van_back["top_y"] + 0.02
        tg = inside & (near_share > 0.5)
        # the window pane can be modelled twice (outer and inner face): both go
        if not rear_engine:
            tg |= inside & np.isin(dom, list(glass))
        tg &= label == "body"
        if rear_engine:
            tg &= ~np.isin(dom, list(glass))
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
            # the panel's full thickness: paint and the liner behind it, within
            # 8 cm of the rearmost surface, in 3 cm cells. The surface from
            # points spread over the rear half's triangles: a big triangle's
            # corners alone leave cells where a trim inside the boot (the
            # 1998 Micra's) looks like the skin
            ts = np.where(~np.isin(tmat, list(glass)))[0]
            cen = T[ts].mean(1)
            back_ts = ts[cen[:, 2] < zr]
            skin_pts = surface_points(T[back_ts], 0.02) if len(back_ts) else T[ts].reshape(-1, 3)
            on_skin = skin(cen, skin_pts, (0, 1), -1, 0.08)
            if rear_engine:                    # an engine lid lies flat: its top skin too
                on_skin |= skin(cen, T[ts].reshape(-1, 3), (0, 2), 1, 0.07)
            ytopc, xt_low, ywin = np.inf, None, None
            if van_back:                       # the van's back, as found above
                xt, ycut, ztop, ytopc = van_back["x_half"], van_back["bottom_y"], van_back["z_front"], van_back["top_y"]
            else:
                xt = max(abs(rw_lo[0]), abs(rw_hi[0])) + 0.02
                # under the window, inside the tail lamps when they sit in the
                # body's corners and reach just inside the window's width (the
                # Micra's): they stay on the body
                li = tail_lamps_inside(T, tmat, nrm, [i for i in range(nm) if i not in paint_ids and lamp_lens(mats[i])],
                                       float(T[np.isin(tmat, list(paint_ids))].reshape(-1, 3)[:, 2].min()),
                                       ground + 0.5 * (wheel_top - ground), rw_lo[1])
                # (lamps far inside the window's width are on the lid, or a
                # light bar across it: the Focus's, the Roma's)
                if li is not None and 0.85 * xt <= li - 0.02 < xt and not rear_engine:
                    xt_low, ywin = li - 0.02, rw_lo[1]
                    log["tailgate"]["inside_lamps_x"] = round(xt_low, 3)
                # A boot lid (a saloon's, a coupe's: a deck of 35 cm or more
                # from the rear window to the tail) ends at its own lip: the
                # first step back in the paint down the middle. A tailgate
                # runs down to the bumper (bumper_top).
                # (the window's lower edge by area: a lamp's clear lens behind it
                # is small, the 128i coupe's)
                gy, ga = tri_c[grear, 1], area[grear]
                o_ = np.argsort(gy)
                y5 = float(gy[o_][np.searchsorted(np.cumsum(ga[o_]), 0.05 * ga.sum())])
                low = grear & (np.abs(tri_c[:, 1] - y5) < 0.03)
                deck = float(np.percentile(tri_c[low, 2], 5) - T[np.isin(tmat, list(paint_ids))].reshape(-1, 3)[:, 2].min())
                log["tailgate"]["deck_m"] = round(deck, 3)
                ycut = None
                if deck >= 0.35:
                    sp = T[np.isin(tmat, list(paint_ids))].reshape(-1, 3)
                    mid = sp[np.abs(sp[:, 0]) < 0.15]
                    yb = np.arange(rw_lo[1], 0.6 * wheel_top, -0.01)
                    zb = np.array([mid[(mid[:, 1] <= y) & (mid[:, 1] > y - 0.01), 2].min()
                                   if ((mid[:, 1] <= y) & (mid[:, 1] > y - 0.01)).any() else np.nan for y in yb])
                    for k in range(11, len(yb)):
                        if np.isfinite(zb[k]) and np.isfinite(zb[k - 1]) and zb[k] < zb[k - 1] - 0.02:
                            ycut = float(yb[k - 1])
                            break
                else:
                    ycut = bumper_top(T, ~np.isin(tmat, list(glass)), 0.2, max(0.4, 0.6 * xt), rw_lo[1], 0.3 * wheel_top,
                                      rw_hi[2] + 0.30, painted=np.isin(tmat, list(paint_ids)))
                if ycut is None:
                    ycut = rw_lo[1] - 0.35
                ztop = rw_hi[2] + 0.02
            if rear_engine:                    # the engine lid's box, as above
                ycut, ztop = ybot, zfront

            xw = xt if xt_low is None else xt_low

            def tfield(P, xt=xt, xw=xw, ywin=ywin, ycut=ycut, ztop=ztop, ytopc=ytopc):
                xs = np.abs(P[:, 0]) - (xt if ywin is None else np.where(P[:, 1] >= ywin, xt, xw))
                return np.maximum.reduce([xs, ycut - P[:, 1], P[:, 2] - ztop, P[:, 1] - ytopc])
            if not rear_engine:
                # a floor meeting the back at the sill (a van's load floor) is
                # not the panel: near the bottom edge, what faces up or down
                # goes with it only within 3 cm of the skin (its own edges)
                on_skin &= (np.abs(nrm[ts, 1]) < 0.7) | (cen[:, 1] > ycut + 0.15) \
                    | skin(cen, skin_pts, (0, 1), -1, 0.03)
            cuts.append(("tailgate", ts[on_skin], tfield))
            log["tailgate"]["cut"] = {"from": "the body shell's rear skin", "x_half": round(float(xt), 3),
                                      "bottom_y": round(ycut, 3)}
            # the pieces on the cut panel go with it (the 1998 Micra's
            # number plate and badge, under the window's box above)
            if not rear_engine and ycut < ybot:
                # (lying on it: a boot-floor trim reaching into the car is not)
                more = (np.abs(lo[:, 0]) <= xw) & (np.abs(hi[:, 0]) <= xw) & (lo[:, 1] >= ycut - 0.01) \
                    & (hi[:, 1] <= ytopc + 0.02) & (hi[:, 2] <= ztop) & (hi[:, 2] - lo[:, 2] < 0.10) \
                    & (near_share > 0.5) & (label == "body") & ~np.isin(dom, list(paint_ids))
                label[more] = "tailgate"
                if more.any():
                    log["tailgate"]["cut"]["pieces_on_it"] = int(more.sum())

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
    # (a rear-engined car's bay is under its engine lid, the "tailgate": the
    # same, front and back swapped - 12 cm clear of the lid's rear edge, where
    # the lamps are)
    lid_part = "tailgate" if rear_engine else "bonnet"
    bt = [r["P"][r["I"][r["tri_part"] == lid_part]] for r in recs if (r["tri_part"] == lid_part).any()]
    cleared = 0.0
    if bt and spec.get("engine_pack") and not spec.get("keep_native_engine") and not spec.get("electric"):
        B = np.vstack(bt).reshape(-1, 3)
        wd = wheel_top - ground
        z0, z1, ytop = B[:, 2].min() + 0.05, B[:, 2].max() - 0.12, B[:, 1].min()
        if rear_engine:
            z0, z1 = B[:, 2].min() + 0.12, B[:, 2].max() - 0.02
        # big sheets reach to the lid's edge at the lamps' end
        zb0, zb1 = (z0 - 0.12, z1) if rear_engine else (z0, z1 + 0.12)
        # the bonnet's underside, cell by cell (cells as big as its triangles,
        # at least 3 cm): everything below it is
        # bay, up to just under the panel - a fake engine (the Fiesta's is a
        # photo on a sheet 15 cm under the bonnet) sits above the lowest
        # point of the bonnet's front lip
        bcell = float(np.clip(2 * np.sqrt(np.median(tri_area_normal(np.vstack(bt))[0])), 0.03, 0.12))
        # a rear-engined car: the cabin's back, as the open lid shows it (the
        # 992's seat backs are a zigzag of carpet and leather), goes where it
        # reaches behind the lid's front edge; a panel closes the bay there
        zfe_s = float(B[:, 2].max())
        xfe_s = float(np.percentile(np.abs(B[B[:, 2] > zfe_s - 0.05, 0]), 98))
        trim_rx = re.compile(r"(^|[_\W])int($|[_\W\d])|interior|rug|carpet|leather|seat|fabric|alcantara|upholst", re.I)
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
            under_bonnet = (c[:, 1] > ground + 0.35 * wd) & (c[:, 1] < lid) & (c[:, 2] > min(z0, zb0))
            # small detail: the middle of the bay only (headlamp insides and
            # the grille stay); big flat sheets (a tub, a photo of an engine:
            # the Fiesta's are 30 cm triangles) out to the inner wings and up
            # to the bonnet's front, except what faces forward (the grille)
            # or is named as a lamp, chrome or badge
            lampish = bool(re.search(r"light|lamp|lens|luz|chrome|cromo|grill|badge|logo|emblem",
                                     mats[r["mat"]].get("name", "") if r["mat"] is not None else "", re.I))
            inb = under_bonnet & (
                ((np.abs(c[:, 0]) < 0.45 * track_half) & (c[:, 2] > z0) & (c[:, 2] < z1)) |
                (big & (np.abs(c[:, 0]) < 0.75 * track_half) & (c[:, 2] > zb0) & (c[:, 2] < zb1)
                 & (np.abs(nr_[:, 2]) < 0.7) & (not lampish)))
            # the model's own engine, by its material's name (the 2001 Yaris's
            # VITZ_ENGINE covers stood over the generic engine): all of it
            # under the bonnet's top and inside its footprint goes
            enginish = bool(re.search(r"engine|motor|engbay|intake|radiator|battery|bay\b",
                                      mats[r["mat"]].get("name", "") if r["mat"] is not None else "", re.I))
            if enginish:
                inb |= (c[:, 1] > ground + 0.2 * wd) & (c[:, 1] < btop.max()) & (np.abs(c[:, 0]) < track_half) \
                    & (c[:, 2] > z0 - 0.1) & (c[:, 2] < B[:, 2].max())
            if rear_engine and r["mat"] not in paint_ids and not lampish:
                # under an engine lid all but the body's paint and the lamps
                # goes, up to the lid's top, in the lid's box (its vertex grid
                # has holes under its big triangles): the 992's grille has deep
                # fins the lid's cut leaves standing in the bay
                inb |= (np.abs(c[:, 0]) < xfe_s) & (c[:, 1] > ground + 0.35 * wd) & (c[:, 1] < B[:, 1].max() - 0.02) \
                    & (c[:, 2] > z0) & (c[:, 2] < zfe_s - 0.005)
            if rear_engine and trim_rx.search(mats[r["mat"]].get("name", "") if r["mat"] is not None else ""):
                inb |= (np.abs(nr_[:, 2]) > 0.3) & (np.abs(c[:, 0]) < xfe_s) & (c[:, 1] > ground + 0.35 * wd) \
                    & (c[:, 1] < B[:, 1].max()) & (c[:, 2] > zfe_s - 0.25) & (c[:, 2] < zfe_s + 0.08) \
                    & (Tr[:, :, 2].min(1) < zfe_s - 0.015)
            if inb.any():
                cleared += float(tri_area_normal(Tr[inb])[0].sum())
                r["tri_part"][body_t[inb]] = "drop"
        log["bay_cleared_m2"] = round(cleared, 3)
    elif spec.get("keep_native_engine") or spec.get("electric"):
        # an electric car has no engine, radiator, fuel tank or exhaust to
        # fit: its own front end (a front boot, often) stays as modelled
        spec = dict(spec, engine_pack=None)
        log["engine_pack"] = {"skipped": "electric" if spec.get("electric") else "keep_native_engine"}
    if spec.get("electric"):
        log["powertrain"] = "electric"

    # ── output frame: centred on the wheelbase, scaled to the published one ──
    def to_out(P):
        Q = (P - np.array([0.0, ground, zmid])) * s
        return Q

    # a VAN's back is two barn doors, not a lid (the Master, the Transit): the
    # tailgate found or cut here splits down its middle, each half hinged at
    # its outer edge. A tailgate the model names stands as it is.
    if spec.get("body_family") == "van" and "tailgate" not in manual and not log.get("tailgate_named"):
        xs = [r["P"][r["I"][r["tri_part"] == "tailgate"]].reshape(-1, 3)[:, 0] for r in recs
              if (r["tri_part"] == "tailgate").any()]
        if xs:
            xa = np.concatenate(xs)
            xm = (xa.min() + xa.max()) / 2
            lamp_rx = re.compile(r"lamp|light|lens|(red|orange|amber)_?glass|reflector|indicator|signal|brake|stop", re.I)
            for r in recs:
                on = r["tri_part"] == "tailgate"
                if on.any():
                    # a van's tail lamps sit in its rear pillars, beside the doors
                    if r["rig"] == "lamps_rear" or (r["mat"] is not None
                                                    and lamp_rx.search(mats[r["mat"]].get("name", ""))):
                        r["tri_part"] = np.where(on, "body", r["tri_part"])
                        continue
                    cx_ = r["P"][r["I"]].mean(1)[:, 0]
                    r["tri_part"] = np.where(on, np.where(cx_ > xm, "door_bl", "door_br"), r["tri_part"])
            log["barn_doors"] = {"split_x": round(float(xm), 3), "why": "a van: the back opens as two doors"}

    # a sliding door is its painted skin and what lies on it: a strip the
    # model runs on past it (the ID Buzz's waist moulding, back to the tail
    # lamps) stays on the body, or it would slide out behind the van
    for d in ("door_rl", "door_rr"):
        if not ((spec.get("hinges") or {}).get(d) or {}).get("slide"):
            continue
        sk = [r["P"][r["I"][r["tri_part"] == d]].reshape(-1, 3)[:, 2] for r in recs
              if r["mat"] in paint_ids and (r["tri_part"] == d).any()]
        if not sk:
            continue
        z0, z1 = np.percentile(np.concatenate(sk), [1, 99])
        n = 0
        for r in recs:
            on = r["tri_part"] == d
            if on.any():
                cz = r["P"][r["I"]].mean(1)[:, 2]
                past = on & ((cz < z0 - 0.05) | (cz > z1 + 0.05))
                if past.any():
                    r["tri_part"] = np.where(past, "body", r["tri_part"])
                    n += int(past.sum())
        if n:
            log.setdefault("sliding_door_trimmed", {})[d] = n

    # a side door stays on its own side of the car: a piece of it reaching
    # across the centreline is the body's (the ID Buzz's right front door
    # took a black strip as wide as the cabin, and swung it out over the roof)
    xs_ = np.concatenate([r["P"][np.unique(r["I"]), 0] for r in recs if len(r["I"])])
    cx_, half_ = (xs_.min() + xs_.max()) / 2, (xs_.max() - xs_.min()) / 2
    for d in ("door_fl", "door_fr", "door_rl", "door_rr"):
        sg = 1.0 if d.endswith("l") else -1.0
        moved = []
        for r in recs:
            idx = np.flatnonzero(r["tri_part"] == d)
            if not len(idx):
                continue
            lab, _ = islands(r["P"][r["I"][idx]])
            across = [idx[lab == k] for k in np.unique(lab)
                      if (sg * (r["P"][r["I"][idx[lab == k]]][..., 0] - cx_)).min() < -0.2 * half_]
            if across:
                tp = r["tri_part"].copy()
                for sel in across:
                    tp[sel] = "body"
                    V = r["P"][r["I"][sel]].reshape(-1, 3)
                    moved.append({"triangles": len(sel), "mat": mats[r["mat"]].get("name") if r["mat"] is not None else None,
                                  "lo": [round(float(v), 2) for v in V.min(0)], "hi": [round(float(v), 2) for v in V.max(0)]})
                r["tri_part"] = tp
        if moved:
            log.setdefault("door_strays_across", {})[d] = moved

    # ── a model listed as torn: its painted panels closed up (close_cracks) ──
    if spec.get("close_cracks"):
        close_cracks(recs, paint_ids, log)

    # ── right-hand drive asked for (a UK car) from a left-hand-drive model ──
    if spec.get("drive") == "right":
        xc = float(np.mean([r["P"][np.unique(r["I"]), 0].mean() for r in recs if r["rig"].startswith("wheel_")]))
        right_hand_drive(g, recs, mats, log, ground, xc)     # xc: the car's centre plane, between its wheels

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
                if an in ("NORMAL", "TANGENT") and "mirror_v" in r:
                    mv = r["mirror_v"][uniq]          # mirrored across the car (right_hand_drive): x turns, and the tangent's hand
                    A[mv, 0] *= -1
                    if an == "TANGENT":
                        A[mv, 3] *= -1
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
            if h.get("slide") and pname in ("door_rl", "door_rr"):
                # a van's sliding side door: out from the body 7 cm, then
                # back along it by most of its own length (0.82 of it, as the
                # rig machine judges a slider); its node moves, it does not turn
                # (never past the tail: its rear edge stops 15 cm short of it)
                lo_d, hi_d = V.min(0), V.max(0)
                side = 1.0 if (lo_d[0] + hi_d[0]) / 2 > 0 else -1.0
                tail = min(float(g.accessor(pr["attributes"]["POSITION"])[:, 2].min()) for pr in by_part.get("body", []))
                back = min(0.82 * float(hi_d[2] - lo_d[2]), max(float(lo_d[2]) - tail - 0.15, 0.0))
                move = {"out": round(0.07 * side, 3), "back": round(-back, 3)}
                extras = {"slide": move}
                log.setdefault("sliding", {})[pname] = move
            else:
                extras = {"axis": axis, "open_deg": deg}
            nodes.append({"name": pname + "_hinge", "translation": piv, "children": [hv + 1], "extras": extras})
            nodes.append({"name": pname, "translation": [-c for c in piv], "mesh": mi})
            nodes[0]["children"].append(hv)
            pivots[pname] = (hv, axis, deg) if "axis" in extras else (hv, ("slide", piv, extras["slide"]), None)
        else:
            nodes.append({"name": pname, "mesh": mi})
            nodes[0]["children"].append(len(nodes) - 1)
    j["meshes"] = meshes
    j["nodes"] = nodes
    log["parts"] = {rename.get(k, k): int(sum(j["accessors"][pr["indices"]]["count"] // 3 for pr in v))
                    for k, v in by_part.items()}
    log["opens"] = sorted(pivots)
    barn = any(b in pivots for b in BARN)
    log["missing"] = sorted(set(HINGED) - set(pivots) - set(BARN) - ({"tailgate"} if barn else set()))

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
            # a rear-engined car's pack is turned round (180 degrees about the
            # vertical): the bay, engine and gearbox on the rear axle, the
            # engine behind it; the tank and the other axle's gear in front
            A = np.array([-sx, sy, -sl] if rear_engine else [sx, sy, sl])
            return mat4(A, np.array([0.0, 0.0, z_to]) - A * np.array([0.0, F["ground_y"], z_from]))
        front = anchored(F["front_axle_z"], zr_o if rear_engine else zf_o)
        rear = anchored(F["rear_axle_z"], zf_o if rear_engine else zr_o)
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
        # a 911's radiators are in its nose: the pack's, at the back of a
        # turned-round bay, stay out (and the engine goes further back)
        no_room = set()          # pack parts that still break through after the moves: left out
        no_room_cm = {}
        left_out = lambda nm: nm in no_room or (rear_engine and nm.startswith("bay:radiator"))  # noqa: E731
        pts, by_top = [], {}
        for i, nd in enumerate(pack.j["nodes"]):
            if "mesh" in nd and i not in stray and top_of(i) not in PACK_REAR | PACK_EXHAUST and not left_out(top_of(i)):
                for pr in pack.j["meshes"][nd["mesh"]]["primitives"]:
                    Pp = pack.accessor(pr["attributes"]["POSITION"])
                    pts.append(Pp[:: max(1, len(Pp) // 400)] @ PW[i][:3, :3].T + PW[i][:3, 3])
                    by_top.setdefault(top_of(i), []).append(pts[-1])
        Mf = np.array(front).reshape(4, 4).T
        Q = np.vstack(pts) @ Mf[:3, :3].T + Mf[:3, 3]
        bon = [to_out(r["P"][r["I"][r["tri_part"] == lid_part]].reshape(-1, 3)) for r in recs if (r["tri_part"] == lid_part).any()]
        skin_pts = np.vstack([to_out(r["P"][r["I"][r["tri_part"] == "body"]].reshape(-1, 3))
                              for r in recs if not r["rig"].startswith(("wheel_", "door_")) and (r["tri_part"] == "body").any()])
        back = 0.0
        lid_out = np.vstack(bon) if bon else None
        if rear_engine and bon:
            # the engine under the middle of the engine lid (the pack's block
            # sits ahead of its axle; a 911's flat six behind it), and nothing
            # up through the fixed rear window over it
            blk = [i for i, nd in enumerate(pack.j["nodes"]) if "mesh" in nd and nd.get("name") in ("bay:blk", "bay:head")]
            ez = np.mean([(pack.accessor(pr["attributes"]["POSITION"]) @ PW[i][:3, :3].T + PW[i][:3, 3])[:, 2].mean()
                          for i in blk for pr in pack.j["meshes"][pack.j["nodes"][i]["mesh"]]["primitives"]]) \
                if blk else F["front_axle_z"] + 0.24
            ez_out = Mf[2, 2] * ez + Mf[2, 3]
            back = float(np.clip(np.vstack(bon)[:, 2].mean() - ez_out, -0.6, 0.0))
            Q[:, 2] += back
            Mf[2, 3] += back
            bon = bon + [to_out(r["P"][r["I"]].reshape(-1, 3)) for r in recs if r["mat"] in glass]

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
        qn = Q[Q[:, 1] > 0.35 * wd * s]
        if rear_engine:
            # the tail only: body behind the rear axle; the bay comes forward
            # out of it (z mirrored, so the same check looks backwards)
            tail = skin_pts[skin_pts[:, 2] < zr_o] * np.array([1.0, 1.0, -1.0])
            dz = -min(0.12 - back, overshoot(qn * np.array([1.0, 1.0, -1.0]), tail, (0, 1), 2, np.maximum, 0.04)) \
                if len(qn) and len(tail) else 0.0
        else:
            # the nose only: body ahead of the front axle, bay points from the
            # bumper's lower edge up (the arms and subframe sit under the floor)
            nose = skin_pts[skin_pts[:, 2] > zf_o]
            dz = min(0.12, overshoot(qn, nose, (0, 1), 2, np.maximum, 0.04)) if len(qn) and len(nose) else 0.0
        Mf[1, 3] -= dy
        Mf[2, 3] -= dz
        # Lowering and moving back stop at 15 and 12 cm. In a short nose (the
        # Focus RS's) the cooling pack still came out through the bumper, a
        # black box in front of the grille: a part still out through the lid's
        # or the nose's outer skin by more than a centimetre (where it shows,
        # not where it merely touches the inside) is left out, as a 911's
        # radiators are, and the log names it

        def beyond(P, ref, axes, ax, cell=0.05, reach=2):
            """How far points P stand out past the outer envelope of ref along
            axis ax: ref's furthest point in each 5 cm cell, widened to the
            furthest within 25 cm, so a grille or intake opening is not taken
            for the outside of the car. Only points with ref around them count."""
            a0, a1 = axes
            lo0, lo1 = ref[:, a0].min(), ref[:, a1].min()
            i0 = np.floor((ref[:, a0] - lo0) / cell).astype(int)
            i1 = np.floor((ref[:, a1] - lo1) / cell).astype(int)
            grid = np.full((i0.max() + 1, i1.max() + 1), -np.inf)
            np.maximum.at(grid, (i0, i1), ref[:, ax])
            env = grid.copy()
            for d0 in range(-reach, reach + 1):
                for d1 in range(-reach, reach + 1):
                    sh = np.full_like(grid, -np.inf)
                    s0 = slice(max(0, d0), grid.shape[0] + min(0, d0)); t0 = slice(max(0, -d0), grid.shape[0] + min(0, -d0))
                    s1 = slice(max(0, d1), grid.shape[1] + min(0, d1)); t1 = slice(max(0, -d1), grid.shape[1] + min(0, -d1))
                    sh[t0, t1] = grid[s0, s1]
                    env = np.maximum(env, sh)
            q0 = np.floor((P[:, a0] - lo0) / cell).astype(int)
            q1 = np.floor((P[:, a1] - lo1) / cell).astype(int)
            ok = (q0 >= 0) & (q0 < grid.shape[0]) & (q1 >= 0) & (q1 < grid.shape[1])
            if not ok.any():
                return 0.0
            lim = env[q0[ok], q1[ok]]
            fin = np.isfinite(lim)
            return float(max(0.0, (P[ok][fin, ax] - lim[fin]).max())) if fin.any() else 0.0

        for nm, ps in by_top.items():
            Pn = np.vstack(ps) @ Mf[:3, :3].T + Mf[:3, 3]
            # past the lid's outer skin (its top in each cell), not merely its underside
            through = beyond(Pn, np.vstack(bon), (0, 2), 1) if bon else 0.0
            t_lid = through
            # every height: the envelope test ignores what has no body round it
            # (the arms under the floor), and a tray out under the bumper shows
            up = Pn
            if len(up):
                if rear_engine:
                    tail = skin_pts[skin_pts[:, 2] < zr_o] * np.array([1.0, 1.0, -1.0])
                    if len(tail):
                        through = max(through, beyond(up * np.array([1.0, 1.0, -1.0]), tail, (0, 1), 2))
                else:
                    # the nose's front face is the body and the lid together:
                    # where the bonnet alone covers the front, it is the skin
                    face = np.vstack([skin_pts] + ([np.vstack(bon)] if bon else []))
                    face = face[face[:, 2] > zf_o]
                    if len(face):
                        through = max(through, beyond(up, face, (0, 1), 2))
            if through > 0.01:
                no_room.add(nm)
                no_room_cm[nm] = [round(t_lid * 100, 1), round(through * 100, 1)]
        front = [float(v) for v in Mf.T.ravel()]
        # exhaust: from where the front pipe hands over to 30 cm inside the tail:
        # under the floor, seen from below, never a second tailpipe beside the
        # model's own (the 2025 M5's four dark tips had a silver fifth)
        tail_o = (float(min(lo[:, 2])) - zmid) * s
        z1 = sl * (F["exhaust_front_z"] - F["front_axle_z"]) + zf_o
        if rear_engine:                      # the pipe hands over ahead of the engine, turned round
            z1 = float(Mf[2, 2] * F["exhaust_front_z"] + Mf[2, 3])
        z2 = tail_o + EXHAUST_INSIDE
        az = (z1 - z2) / (F["exhaust_front_z"] - F["exhaust_tail_z"])
        A = np.array([sx, sy, az])
        exhaust = mat4(A, np.array([0.0, -sy * F["ground_y"], z1 - az * F["exhaust_front_z"]]))
        wrap = {"engine_bay": front, "rear_running_gear": rear, "exhaust": exhaust}
        if rear_engine:
            # the nose is the luggage space: the pack's tank and other axle stay
            # out (the model's own floor and liner stand under the front lid)
            del wrap["rear_running_gear"]
        widx = {}
        for k, M in wrap.items():
            widx[k] = len(j["nodes"])
            j["nodes"].append({"name": k, "matrix": M, "children": []})
            nodes[0]["children"].append(widx[k])
        for r0 in proots:
            for c in j["nodes"][r0].get("children", [r0]):
                nmx = j["nodes"][c].get("name", "")
                k = "exhaust" if nmx in PACK_EXHAUST else "rear_running_gear" if nmx in PACK_REAR else "engine_bay"
                if k in widx and not left_out(nmx):
                    j["nodes"][widx[k]]["children"].append(c)
            j["nodes"][r0].pop("children", None)     # a node has one parent
        if rear_engine and lid_out is not None:
            # the bay's front wall: a model is seldom finished behind its rear
            # seats (the 992's seat backs are a zigzag of carpet and leather,
            # seen from the bay), so the bay is closed at the lid's front edge
            # with a dark panel from the bay's floor up to just under the lid
            # (its top follows the lid's edge across the car); the engine runs
            # on under the parcel shelf behind it, as a 911's does
            zfe = float(lid_out[:, 2].max())
            band = lid_out[lid_out[:, 2] > zfe - 0.05]
            xh = float(np.percentile(np.abs(band[:, 0]), 98)) - 0.01
            y_lo = 0.35 * wd * s
            cols = np.linspace(-xh, xh, 17)
            tops = []
            for x in cols:
                near = band[np.abs(band[:, 0] - x) < xh / 16 + 0.02]
                tops.append(float(near[:, 1].max()) - 0.015 if len(near) else np.nan)
            tops = np.array(tops)
            if np.isfinite(tops).sum() > 4 and xh > 0.2:
                ok = np.isfinite(tops)
                tops = np.interp(cols, cols[ok], tops[ok])
                zw = zfe - 0.015
                V = np.array([[x, y, zw] for x, t in zip(cols, tops) for y in (y_lo, t)], np.float32)
                n = len(cols)
                quads = [(2 * k, 2 * k + 2, 2 * k + 3, 2 * k + 1) for k in range(n - 1)]
                fwd = [i for a, b, c, d in quads for i in (a, b, c, a, c, d)]           # facing the nose
                Ix = np.array(fwd + [i + 2 * n for a, b, c, d in quads for i in (a, c, b, a, d, c)], np.uint32)
                Vp = np.vstack([V, V])
                Nn = np.array([[0, 0, 1]] * (2 * n) + [[0, 0, -1]] * (2 * n), np.float32)
                j["materials"].append({"name": "bay_front_wall", "pbrMetallicRoughness": {
                    "baseColorFactor": [0.025, 0.025, 0.028, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.85}})
                j["meshes"].append({"name": "bay_front_wall", "primitives": [{
                    "attributes": {"POSITION": g.add_accessor(Vp, minmax=True, target=34962),
                                   "NORMAL": g.add_accessor(Nn, target=34962)},
                    "indices": g.add_accessor(Ix, ctype=5125, atype="SCALAR", target=34963),
                    "material": len(j["materials"]) - 1}]})
                j["nodes"].append({"name": "bay_front_wall", "mesh": len(j["meshes"]) - 1})
                nodes[0]["children"].append(len(j["nodes"]) - 1)
                log["bay_front_wall"] = {"z": round(zw, 3), "y": [round(y_lo, 3), round(float(tops.min()), 3),
                                                                  round(float(tops.max()), 3)], "x_half": round(xh, 3)}
        log["engine_pack"] = {"file": os.path.basename(spec["engine_pack"]), "scale": [round(sx, 4), round(sy, 4), round(sl, 4)],
                              "lowered_m": round(dy, 3), "moved_back_m": round(dz - back, 3),
                              "width_ratios": [round(x, 3) for x in ratios],
                              "exhaust_stretch": round(az / sl, 4), "strays_dropped": len(stray),
                              **({"left_out_no_room": sorted(no_room), "no_room_cm": no_room_cm} if no_room else {})}

    # ── cabin: a model with nothing inside gets the cabin pack (the 1998
    # Micra: a shell), fitted between its axles; the pack's maker is credited
    if spec.get("cabin_pack") and spec.get("body_family") != "van" and "cabin" not in manual:
        n_cab = cabin_count(recs, ground, wheel_top, zf, zr)
        if n_cab < 300:
            root, log["cabin_pack"] = fit_cabin(g, recs, spec["cabin_pack"], to_out, s, ground, zf, zr)
            log["cabin_pack"]["cabin_triangles_before"] = n_cab
            nodes[0]["children"].append(root)
            c = log["cabin_pack"]
            spec = dict(spec, credit=(spec.get("credit") or "") + f" Cabin fitted from '{c['from']}'"
                        + (f" by {c['author']}" if c.get("author") else "") + f", {c['licence']}"
                        + (f", {c['url']}" if c.get("url") else "") + ".")

    j["scenes"] = [{"name": spec.get("name") or "car", "nodes": [0]}]
    j["scene"] = 0

    # ── paint: a colour asked for (sRGB 0-255) replaces the model's own ──
    if spec.get("paint"):
        # every piece of the paint, not only the one material found: a model
        # splits its paint over materials of one name (the Astra's two
        # "carpaint", the Octavia's two "body_paint"), or names its bonnet and
        # roof's paint otherwise in the same colour (the Octavia's red
        # "material"); left alone, they kept the model's colour beside the new one
        mat_m2 = {}
        for r in recs:
            if r["mat"] is not None and not r["rig"].startswith("wheel_"):
                mat_m2[r["mat"]] = mat_m2.get(r["mat"], 0) + float(tri_area_normal(tris(r))[0].sum()) * s * s
        # and a second material the model names as paint with a real share of
        # the side (the Jazz's "Paint1" beside its "Main_Color_paint")
        named = {i for i in range(min(len(mats), len(door_area))) if i != paint and re.search(r"paint", mats[i].get("name", ""), re.I)
                 and not mats[i].get("name", "").startswith("detail-") and door_area[i] >= 0.3 * door_area[paint]}
        # and one named for the paint itself with a letter or number after it,
        # of real panels (the Ghost's "rrghost_paint_b", its two-tone's
        # bonnet, which stayed black on the white i7 made from it)
        stem = mats[paint].get("name", "")
        named |= {i for i in range(len(mats)) if i != paint and len(stem) >= 4 and i not in glass
                  and re.fullmatch(re.escape(stem) + r"[ _.\-]?[a-z0-9]{1,3}", mats[i].get("name", ""), re.I)
                  and not INSIDE.search(mats[i].get("name", "")) and mat_m2.get(i, 0) >= 0.5}

        # and a two-tone's other paint, named as paint, over the waist where the
        # side's skin is not counted: as much as 40% of the paint's own area
        # (the ID Buzz's white "Carpaint_Simple_Ruby" upper half, kept on a red
        # Tourneo): the photo's car is one colour
        # (never a trim, a lamp or a colourless near-black plastic: the review
        # of this rule found "black" painted the body colour on 32 cars)
        named |= {i for i in range(len(mats)) if i != paint and i not in glass
                  and PAINT_NAME.search(mats[i].get("name", ""))
                  and not mats[i].get("name", "").startswith("detail-") and not INSIDE.search(mats[i].get("name", ""))
                  and not TRIMMISH.search(mats[i].get("name", "")) and not LAMPISH.search(mats[i].get("name", ""))
                  and not dark_plastic(mats[i]) and mat_m2.get(i, 0) >= 0.4 * mat_m2.get(paint, 1e9)}
        coats = sorted(set(paint_ids) | same_paint(mats, paint, glass, mat_m2) | named)
        # a wheel's material in the model's own paint colour: a wheel's dark grey
        wip = wheels_in_paint(mats, paint, glass)
        for i in wip:
            (mats[i].setdefault("pbrMetallicRoughness", {})).update(
                {"baseColorFactor": [0.03, 0.03, 0.03, 1.0], "metallicFactor": 0.3, "roughnessFactor": 0.55})
        if wip:
            log["wheels_in_paint"] = [mats[i].get("name") for i in sorted(wip)]
        for i in coats:
            _paint_one(mats[i], spec, j)
        # a material the model also uses for body panels (batch.PAINT_ALSO):
        # those panels take the paint, its own parts (the wheels) keep it
        also = set(spec.get("paint_also") or [])
        if also:
            moved = 0
            for n in j["nodes"]:
                if "mesh" not in n or re.match(r"(?:SB_)?wheel", n.get("name") or ""):
                    continue
                for p in j["meshes"][n["mesh"]]["primitives"]:
                    if p.get("material") is not None and mats[p["material"]].get("name") in also:
                        p["material"] = paint
                        moved += 1
            log["paint_also"] = {"materials": sorted(also), "pieces": moved}
        pm = mats[paint]
        metallic = pm["pbrMetallicRoughness"]["metallicFactor"]
        log["paint_set"] = {"material": pm.get("name"), "srgb": list(spec["paint"][:3]), "metallic": float(metallic),
                            "clearcoat": True, "materials": [mats[i].get("name") for i in coats]}

    # ── a roof in the body's colour: a stand-in's donor's black roof (batch.py
    # asks it of every stand-in, unless the request asks for a contrasting roof)
    if spec.get("roof") == "body" or isinstance(spec.get("roof"), (list, tuple)):
        rp = roof_in_paint(g, mats, paint, set(coats) if spec.get("paint") else paint_ids, glass,
                           colour=spec["roof"] if isinstance(spec["roof"], (list, tuple)) else None)
        if rp:
            log["roof_in_paint"] = rp
    # ── a panel van asked: no windows behind the cab ──
    if spec.get("panel_van"):
        log["panel_van"] = panel_sides(g, glass, paint)
    # ── the paint's shading where the model broke it ──
    log["normals_mended"] = mend_normals(g, set(coats) | {paint} if spec.get("paint") else paint_ids)

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

    # ── blended, yet solid: a cut-out instead ──
    # A material at full alpha marked BLEND (the 2025 M5's cabin, its
    # steering wheel with it) blends with whatever is behind: the dash screen
    # showed through the wheel's rim. When its texture's alpha is mostly on
    # or off (a cut-out pattern: perforation, stitching, a grille's holes),
    # MASK draws it solid with its holes. One soft all over is see-through
    # by design (the 2001 Yaris's gauge cover) and stays; so do glass, lamp
    # lenses and anything named as a shadow or decal.
    masked = []
    for i, m in enumerate(mats):
        if m.get("alphaMode") != "BLEND" or i in glass or is_clear_glass(m):
            continue
        c = m.get("pbrMetallicRoughness", {}).get("baseColorFactor", [1, 1, 1, 1])
        if c[3] < 0.99 or re.search(r"glass|window|windscreen|lamp|light|lens|refl|indic|shadow|decal|\bao\b|dirt|grime"
                                    r"|smoke|^detail-", m.get("name", ""), re.I):
            continue
        soft = _alpha_soft(g, m)
        if soft is not None and soft >= 0.5:
            continue
        m["alphaMode"], m["alphaCutoff"] = "MASK", 0.1     # low: a soft edge stays, as blended it showed
        masked.append(m.get("name"))
    if masked:
        log["blend_to_mask"] = masked

    # ── animation clips ──
    # a hinged part turns its hinge node; a sliding door moves its node out
    # from the body over the first fifth, then back along it
    tin = g.add_accessor(np.array([0.0, 1.0]), minmax=True)
    tin3 = None
    clips = {}
    for part, (hv, axis, deg) in pivots.items():
        if axis[0] == "slide":
            _, piv, mv = axis
            tin3 = tin3 if tin3 is not None else g.add_accessor(np.array([0.0, 0.2, 1.0]), minmax=True)
            p0 = np.array(piv, dtype=float)
            q = g.add_accessor(np.array([p0, p0 + [mv["out"], 0, -0.02], p0 + [mv["out"], 0, mv["back"]]]))
            ch = (hv, q, tin3, "translation")
        else:
            ch = (hv, g.add_accessor(np.array([[0, 0, 0, 1], quat(axis, deg)])), tin, "rotation")
        clips.setdefault(part + "_open", []).append(ch)
        if part.startswith("door") and part not in BARN:
            clips.setdefault("doors_open", []).append(ch)
        clips.setdefault("all_open", []).append(ch)
    j["animations"] = [{"name": nm_, "samplers": [{"input": t_, "output": q, "interpolation": "LINEAR"} for _, q, t_, _ in ch],
                        "channels": [{"sampler": i, "target": {"node": pv, "path": path}}
                                     for i, (pv, _, _, path) in enumerate(ch)]}
                       for nm_, ch in clips.items()]
    if spec.get("credit"):
        j.setdefault("asset", {})["copyright"] = spec["credit"]
    j.setdefault("asset", {}).setdefault("extras", {})["realcar_finish"] = log
    log["maps_without_uv"] = drop_unreachable_maps(g)
    log["tangents"] = ensure_tangents(g)
    log["bytes"] = g.save(out)
    return log


if __name__ == "__main__":
    src, spec_p, out = sys.argv[1:4]
    spec = json.load(open(spec_p))
    d = os.path.dirname(os.path.abspath(spec_p))
    for k in ("engine_pack", "cabin_pack"):
        if spec.get(k) and not os.path.isabs(spec[k]):
            spec[k] = os.path.join(d, spec[k])
    print(json.dumps(finish(src, spec, out, d), indent=1, default=float))
