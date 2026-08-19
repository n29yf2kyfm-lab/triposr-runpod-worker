#!/usr/bin/env python3
"""delight.py — remove BAKED LIGHTING from a generated car's base-colour texture.

    python3 delight.py <in.glb> <out.glb> [--dry-run] [--force] [options]

WHY
---
A single-image generator (Pixal3D, Hunyuan3D, TRELLIS) bakes the photograph
into the base-colour map, so the sky gradient, the sun side and the shaded side
are painted into what should be pure albedo. The production brief forbids that
("no baked lighting" in base colour): a car with light baked in cannot relight
when the customer spins it.

WHAT IT DOES
------------
Estimates the incident-lighting field in THREE-DIMENSIONAL space (never in UV
space) and divides it out of every texel.

Why 3D and not UV: this atlas has 17,187 separate charts at 2048 (35,840 at
4096). A "heavily blurred luminance" computed in UV space blurs across chart
gutters and across unrelated islands, so the estimated field is meaningless at
every chart edge — which, with charts this small, is most of the texture. The
field is therefore built from texels binned by their position ON THE CAR, which
is chart-agnostic by construction.

Method:
  1. texel -> 3D position + coverage mask, by scatter-sampling every triangle
  2. exteriority per texel, by ray-marching a voxel occupancy grid (the inside
     of a fused shell must never vote on the lighting)
  3. the PAINT class = the exterior colour cluster with the widest spatial
     coverage over the car. Body paint is the only material that is one colour
     over the whole body; tyres, glass and lamps cluster in a few places. This
     is why the class finder scores COVERAGE, not count — it works on a black
     car, where paint is not the brightest cluster.
  4. shading field S(x) = smoothed median paint luminance per 3D cell,
     normalised to its own median, clamped, and faded to 1.0 where no paint
     supports it
  5. every texel: linear_rgb /= S. S varies only over >= ~4 cm, so panel gaps,
     badges, grille slats and lamp internals pass through untouched (measured:
     high-frequency residual preserved to 4 decimal places).

It REFUSES (exit 2, writes nothing) rather than degrading silently when:
  * there is no base-colour texture, or it cannot be decoded
  * no paint class can be identified (too small, or too localised)
  * the measured baked lighting is below --min-spread — nothing to fix, so the
    texture is left alone rather than re-encoded for nothing (--force overrides)

MEASURED ON THE PIXAL YARIS (car-meshes/pixal_test/pixal_golf.glb, 2026-08-19)
-----------------------------------------------------------------------------
Baked lighting in that texture is REAL BUT MILD, and the honest numbers are:
  * paint low-frequency field (median per 3.5 cm cell), p5 -> p95: 2.21x linear
    (sRGB 0.61 -> 0.87); interquartile only 1.33x
  * top-of-body vs bottom-of-body: 1.14x   left flank vs right flank: 1.09x
  * up-facing vs down-facing paint: 1.06x  -- almost no directional signature
  * correlation with geometric ambient occlusion: r = -0.19, i.e. the WRONG
    sign. There is NO baked cast shadow under the arches in this texture.
  * nothing is clipped (max sRGB 0.867), so no highlight is unrecoverable
So most of the low-frequency variation is local mottle (kerb/ground reflection
on the lower doors, a soft wash on the bonnet), not a sun/sky gradient. Expect
a modest improvement, and do not oversell it: this pass flattens the paint, it
does not rescue a badly lit capture. Glazing is a separate problem it CANNOT
fix — sky and interior are painted into the glass as high-frequency content,
and only a real glass material replaces that.
"""
import argparse
import io
import json
import struct
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

# ---------------------------------------------------------------- glTF I/O ---
_CT = {5120: "i1", 5121: "u1", 5122: "i2", 5123: "u2", 5125: "u4", 5126: "f4"}
_NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def load_glb(path):
    with open(path, "rb") as f:
        magic, ver, total = struct.unpack("<III", f.read(12))
        if magic != 0x46546C67:
            raise ValueError("not a GLB")
        js = bn = None
        while f.tell() < total:
            clen, ctype = struct.unpack("<II", f.read(8))
            data = f.read(clen)
            if ctype == 0x4E4F534A:
                js = json.loads(data)
            elif ctype == 0x004E4942:
                bn = data
    if js is None:
        raise ValueError("no JSON chunk")
    return js, (bn or b"")


def write_glb(path, gltf, bin_bytes):
    j = json.dumps(gltf, separators=(",", ":")).encode()
    j += b" " * ((4 - len(j) % 4) % 4)
    b = bin_bytes + b"\0" * ((4 - len(bin_bytes) % 4) % 4)
    total = 12 + 8 + len(j) + 8 + len(b)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, total))
        f.write(struct.pack("<II", len(j), 0x4E4F534A))
        f.write(j)
        f.write(struct.pack("<II", len(b), 0x004E4942))
        f.write(b)


def accessor(g, bn, i):
    a = g["accessors"][i]
    bv = g["bufferViews"][a["bufferView"]]
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    n = _NC[a["type"]]
    dt = np.dtype(_CT[a["componentType"]])
    stride = bv.get("byteStride") or n * dt.itemsize
    cnt = a["count"]
    raw = np.frombuffer(bn, dtype=np.uint8, count=stride * cnt, offset=off)
    return raw.reshape(cnt, stride)[:, : n * dt.itemsize].copy().view(dt).reshape(cnt, n)


def image_of_texture(g, ti):
    """Image index for a texture, honouring the compressed-texture extensions
    (EXT_texture_webp / KHR_texture_basisu keep `source` inside the extension
    and may omit the plain one -- the recorded KeyError trap)."""
    t = g["textures"][ti]
    for ext in ("EXT_texture_webp", "KHR_texture_basisu", "EXT_texture_avif"):
        e = t.get("extensions", {}).get(ext)
        if e and "source" in e:
            return e["source"]
    return t.get("source")


def node_world_transforms(g):
    """node index -> 4x4 world matrix (scene graph walk)."""
    out = {}

    def mat(n):
        if "matrix" in n:
            return np.array(n["matrix"], dtype=float).reshape(4, 4).T
        M = np.eye(4)
        if "scale" in n:
            M[:3, :3] = np.diag(n["scale"])
        if "rotation" in n:
            x, y, z, w = n["rotation"]
            R = np.array([
                [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
            ])
            M[:3, :3] = R @ M[:3, :3]
        if "translation" in n:
            M[:3, 3] = n["translation"]
        return M

    def walk(i, parent):
        n = g["nodes"][i]
        M = parent @ mat(n)
        out[i] = M
        for c in n.get("children", []):
            walk(c, M)

    roots = g["scenes"][g.get("scene", 0)]["nodes"] if g.get("scenes") else range(len(g.get("nodes", [])))
    for r in roots:
        walk(r, np.eye(4))
    return out


# --------------------------------------------------------------- colour ------
def srgb_to_linear(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c):
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


LUMW = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


# ------------------------------------------------------- texel <-> geometry ---
def barycentric_grid(k):
    return np.array([(i / k, j / k, 1 - i / k - j / k)
                     for i in range(k + 1) for j in range(k + 1 - i)], dtype=np.float32)


def build_texel_maps(prims, res, geo_res):
    """Scatter-sample every triangle into UV space.

    Returns coverage mask at `res` (full texture resolution, for the eroded
    interior) and a position map at `geo_res`."""
    mask = np.zeros(res * res, dtype=bool)
    cnt = np.zeros(geo_res * geo_res, dtype=np.float32)
    pos = np.zeros((geo_res * geo_res, 3), dtype=np.float32)
    bs = barycentric_grid(6)
    for P, UV, idx in prims:
        uv0, uv1, uv2 = UV[idx[:, 0]], UV[idx[:, 1]], UV[idx[:, 2]]
        p0, p1, p2 = P[idx[:, 0]], P[idx[:, 1]], P[idx[:, 2]]
        for s in bs:
            u = s[0] * uv0 + s[1] * uv1 + s[2] * uv2
            uu = np.mod(u[:, 0], 1.0)
            vv = np.mod(u[:, 1], 1.0)
            mask[(np.clip(((1 - vv) * res).astype(np.int32), 0, res - 1) * res
                  + np.clip((uu * res).astype(np.int32), 0, res - 1))] = True
            k = (np.clip(((1 - vv) * geo_res).astype(np.int32), 0, geo_res - 1) * geo_res
                 + np.clip((uu * geo_res).astype(np.int32), 0, geo_res - 1))
            np.add.at(cnt, k, 1.0)
            np.add.at(pos, k, s[0] * p0 + s[1] * p1 + s[2] * p2)
    m = cnt > 0
    pos[m] /= cnt[m, None]
    return mask.reshape(res, res), m.reshape(geo_res, geo_res), pos.reshape(geo_res, geo_res, 3)


def exteriority(pos, gmask, all_pts, grid=160, dirs=16, steps=20, seed=0):
    """Fraction of a uniform hemisphere-ish bundle of rays that escapes the
    occupancy grid. The inside face of a fused shell scores ~0 and is thereby
    kept out of the lighting estimate."""
    lo = all_pts.min(0)
    span = float((all_pts.max(0) - lo).max())
    occ = np.zeros((grid, grid, grid), dtype=bool)
    gi = np.clip(((all_pts - lo) / span * (grid - 1)).astype(np.int32), 0, grid - 1)
    occ[gi[:, 0], gi[:, 1], gi[:, 2]] = True
    P = pos[gmask]
    rng = np.random.default_rng(seed)
    D = rng.normal(size=(dirs, 3))
    D /= np.linalg.norm(D, axis=1, keepdims=True)
    step = span / grid * 1.6
    vis = np.zeros(len(P), dtype=np.float32)
    for d in D:
        cur = P + d * (span / grid * 1.5)
        alive = np.ones(len(P), dtype=bool)
        for _ in range(steps):
            cur = cur + d * step
            g = (cur - lo) / span * (grid - 1)
            oob = (g < 0).any(1) | (g > grid - 1).any(1)
            ij = np.clip(g.astype(np.int32), 0, grid - 1)
            alive &= ~(occ[ij[:, 0], ij[:, 1], ij[:, 2]] & ~oob)
        vis += alive
    out = np.zeros(gmask.shape, dtype=np.float32)
    out[gmask] = vis / dirs
    return out


# ------------------------------------------------------------- paint class ---
def find_paint(lin, lum, pos, sel, cell):
    """The exterior colour cluster with the widest spatial coverage.

    Scored on COVERAGE (how much of the car it is spread over), not on count:
    body paint is the only material that is one colour over the whole body,
    whatever colour that is. Returns (mask, info)."""
    L = np.maximum(lum[sel], 1e-4)
    rgb = lin[sel]
    s = np.maximum(rgb.sum(1), 1e-5)
    cr, cg = rgb[:, 0] / s, rgb[:, 1] / s
    ll = np.log(L)
    NB, NL = 48, 22
    br = np.clip((cr * NB).astype(int), 0, NB - 1)
    bg = np.clip((cg * NB).astype(int), 0, NB - 1)
    bl = np.clip(((ll + 8) / 8 * NL).astype(int), 0, NL - 1)
    H = np.zeros((NB, NB, NL), dtype=np.float32)
    np.add.at(H, (br, bg, bl), 1.0)
    Hs = ndimage.gaussian_filter(H, 1.0)
    P = pos[sel]
    org = P.min(0)
    coarse = np.clip(((P - org) / max(cell * 4, 1e-6)).astype(int), 0, 63)
    ckey = (coarse[:, 0] * 64 + coarse[:, 1]) * 64 + coarse[:, 2]
    best = None
    Hw = Hs.copy()
    for _ in range(8):
        pk = np.unravel_index(np.argmax(Hw), Hw.shape)
        if Hw[pk] <= 0:
            break
        near = (np.abs(br - pk[0]) <= 1) & (np.abs(bg - pk[1]) <= 1) & (np.abs(bl - pk[2]) <= 1)
        Hw[max(0, pk[0] - 1):pk[0] + 2, max(0, pk[1] - 1):pk[1] + 2, max(0, pk[2] - 1):pk[2] + 2] = 0
        if near.sum() < 200:
            continue
        cells = np.unique(ckey[near])
        cov = len(cells)
        if best is None or cov > best[0]:
            best = (cov, near, pk)
    if best is None:
        return None, {}
    cov, near, pk = best
    # widen the winning cluster: same chromaticity, luminance within a factor
    med_l = float(np.median(L[near]))
    cr0, cg0 = float(np.median(cr[near])), float(np.median(cg[near]))
    wide = ((np.abs(cr - cr0) < 0.035) & (np.abs(cg - cg0) < 0.035)
            & (L > med_l / 4.0) & (L < med_l * 4.0))
    m = np.zeros(sel.shape, dtype=bool)
    m[sel] = wide
    info = dict(chroma=(cr0, cg0), median_lum=med_l,
                frac_of_exterior=float(wide.sum() / max(sel.sum(), 1)),
                coverage_cells=int(len(np.unique(ckey[wide]))),
                total_cells=int(len(np.unique(ckey))))
    return m, info


# ---------------------------------------------------------- shading field ----
def shading_field(pos, paint, lum, cell, sigma_cells, clamp, min_cell):
    """Median paint luminance per 3D cell -> smoothed -> normalised = S(x)."""
    P = pos[paint]
    V = lum[paint]
    org = P.min(0) - cell
    dims = np.ceil((P.max(0) + cell - org) / cell).astype(int) + 1
    g = np.clip(((P - org) / cell).astype(int), 0, dims - 1)
    key = (g[:, 0] * dims[1] + g[:, 1]) * dims[2] + g[:, 2]
    uk, inv = np.unique(key, return_inverse=True)
    cnt = np.bincount(inv)
    order = np.argsort(inv, kind="stable")
    bnd = np.searchsorted(inv[order], np.arange(len(uk) + 1))
    vs = V[order]
    med = np.array([np.median(vs[bnd[i]:bnd[i + 1]]) for i in range(len(uk))])
    ok = cnt >= min_cell
    vol = np.zeros(dims, dtype=np.float32)
    wgt = np.zeros(dims, dtype=np.float32)
    gk = np.array(np.unravel_index(uk, tuple(dims))).T[ok]
    vol[gk[:, 0], gk[:, 1], gk[:, 2]] = med[ok]
    wgt[gk[:, 0], gk[:, 1], gk[:, 2]] = 1.0
    vs_ = ndimage.gaussian_filter(vol * wgt, sigma_cells)
    ws_ = ndimage.gaussian_filter(wgt, sigma_cells)
    field = np.where(ws_ > 1e-4, vs_ / np.maximum(ws_, 1e-6), np.nan)
    ref = float(np.median(med[ok]))
    S = field / ref
    conf = np.clip(ws_ / (0.25 * float(np.median(ws_[ws_ > 0])) + 1e-9), 0, 1)
    S = np.where(np.isfinite(S), S, 1.0)
    S = 1.0 + (np.clip(S, 1.0 / clamp, clamp) - 1.0) * conf
    return S.astype(np.float32), org, cell, ref, float(cnt[ok].sum()), int(ok.sum())


def sample_field(S, org, cell, pts):
    c = ((pts - org) / cell).T
    return ndimage.map_coordinates(S, c, order=1, mode="nearest")


# ------------------------------------------------------------- reporting -----
def spread_report(pos, paint, lum, cell, min_cell=25):
    """Low-frequency spread of the paint: percentiles of the per-cell median."""
    P = pos[paint]
    V = lum[paint]
    org = P.min(0)
    g = np.clip(((P - org) / cell).astype(int), 0, 999)
    key = (g[:, 0] * 1000 + g[:, 1]) * 1000 + g[:, 2]
    uk, inv = np.unique(key, return_inverse=True)
    cnt = np.bincount(inv)
    order = np.argsort(inv, kind="stable")
    bnd = np.searchsorted(inv[order], np.arange(len(uk) + 1))
    vs = V[order]
    med = np.array([np.median(vs[bnd[i]:bnd[i + 1]]) for i in range(len(uk))])
    ok = cnt >= min_cell
    m, w = med[ok], cnt[ok].astype(float)
    o = np.argsort(m)
    cw = np.cumsum(w[o]) / w.sum()
    q = lambda t: float(m[o][np.searchsorted(cw, t)])
    resid = np.log(np.maximum(V, 1e-4)) - np.log(np.maximum(med[inv], 1e-4))
    return dict(p5=q(0.05), p25=q(0.25), p50=q(0.5), p75=q(0.75), p95=q(0.95),
                spread=q(0.95) / max(q(0.05), 1e-6), iqr=q(0.75) / max(q(0.25), 1e-6),
                cells=int(ok.sum()), detail_std=float(resid.std()))


def axis_trends(pos, paint, lum):
    """Trend of paint luminance along each principal axis of the body (pose
    agnostic: the shortest principal axis of a car is its height)."""
    P = pos[paint]
    V = lum[paint]
    C = P - P.mean(0)
    _, _, Vt = np.linalg.svd(C[:: max(1, len(C) // 40000)], full_matrices=False)
    out = []
    for k, name in enumerate(("longest", "middle", "shortest")):
        t = C @ Vt[k]
        lo, hi = np.percentile(t, [10, 90])
        a = np.median(V[t < lo])
        b = np.median(V[t > hi])
        out.append((name, float(b / max(a, 1e-6))))
    return out


# ------------------------------------------------------------------ main -----
def main():
    ap = argparse.ArgumentParser(description="remove baked lighting from a GLB base-colour texture")
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--dry-run", action="store_true", help="measure only, write nothing")
    ap.add_argument("--force", action="store_true", help="write even if the baked lighting is below --min-spread")
    ap.add_argument("--min-spread", type=float, default=1.15, help="refuse below this p95/p5 of the paint field")
    ap.add_argument("--cell-frac", type=float, default=0.030, help="cell size as a fraction of the body diagonal")
    ap.add_argument("--sigma-cells", type=float, default=1.5, help="smoothing of the lighting field, in cells")
    ap.add_argument("--clamp", type=float, default=1.6, help="max correction factor either way")
    ap.add_argument("--geo-res", type=int, default=1024, help="resolution of the texel->geometry maps")
    ap.add_argument("--ext-ao", type=float, default=0.35, help="exteriority cut (fraction of escaping rays)")
    ap.add_argument("--min-paint-frac", type=float, default=0.10, help="refuse if the paint class is smaller than this share of the exterior")
    ap.add_argument("--lossy", type=int, default=0, help="re-encode WebP at this quality instead of lossless")
    ap.add_argument("--report", help="write the measurements to this JSON file")
    args = ap.parse_args()

    def refuse(msg):
        print("REFUSED: " + msg)
        sys.exit(2)

    g, bn = load_glb(args.inp)
    if not g.get("meshes"):
        refuse("no meshes in %s" % args.inp)

    # --- which base-colour images are actually painted onto geometry ---------
    xf = node_world_transforms(g)
    mesh_nodes = {}
    for ni, n in enumerate(g.get("nodes", [])):
        if "mesh" in n:
            mesh_nodes.setdefault(n["mesh"], []).append(xf.get(ni, np.eye(4)))
    by_img = {}
    for mi, mesh in enumerate(g["meshes"]):
        for prim in mesh["primitives"]:
            mat = g.get("materials", [{}])[prim["material"]] if "material" in prim else {}
            bct = mat.get("pbrMetallicRoughness", {}).get("baseColorTexture")
            if bct is None or "TEXCOORD_0" not in prim.get("attributes", {}):
                continue
            img = image_of_texture(g, bct["index"])
            if img is None:
                continue
            P = accessor(g, bn, prim["attributes"]["POSITION"]).astype(np.float32)
            UV = accessor(g, bn, prim["attributes"]["TEXCOORD_0"]).astype(np.float32)
            idx = (accessor(g, bn, prim["indices"]).reshape(-1, 3) if "indices" in prim
                   else np.arange(len(P), dtype=np.int32).reshape(-1, 3))
            for M in mesh_nodes.get(mi, [np.eye(4)]):
                Pw = (M[:3, :3] @ P.T).T + M[:3, 3]
                by_img.setdefault(img, []).append((Pw.astype(np.float32), UV, idx))
    if not by_img:
        refuse("no primitive carries a base-colour texture")

    all_pts = np.concatenate([p for prims in by_img.values() for p, _, _ in prims])
    diag = float(np.linalg.norm(all_pts.max(0) - all_pts.min(0)))
    cell = args.cell_frac * diag
    print("mesh: %d primitives, %d base-colour image(s), body diagonal %.3f -> cell %.1f mm-equivalent"
          % (sum(len(v) for v in by_img.values()), len(by_img), diag, cell / diag * 4000))

    # --- decode textures and build texel maps -------------------------------
    layers = []
    for img_i, prims in by_img.items():
        im = g["images"][img_i]
        if "bufferView" not in im:
            refuse("image %d is a URI, not embedded -- unsupported" % img_i)
        bv = g["bufferViews"][im["bufferView"]]
        off = bv.get("byteOffset", 0)
        raw = bn[off:off + bv["byteLength"]]
        try:
            pil = Image.open(io.BytesIO(raw))
            pil.load()
        except Exception as e:                                    # noqa: BLE001
            refuse("cannot decode base-colour image %d (%s): %s" % (img_i, im.get("mimeType"), e))
        res = pil.size[0]
        if pil.size[0] != pil.size[1]:
            refuse("non-square texture %s -- unsupported" % (pil.size,))
        geo_res = min(args.geo_res, res)
        cov, gmask, pos = build_texel_maps(prims, res, geo_res)
        layers.append(dict(img=img_i, pil=pil, res=res, geo=geo_res, cov=cov,
                           gmask=gmask, pos=pos, fmt=pil.format, mime=im.get("mimeType")))
        print("  image %d: %dx%d %s, %.1f%% of texels carry geometry"
              % (img_i, res, res, pil.format, 100 * cov.mean()))

    # --- per-texel colour on the eroded interior of every chart --------------
    for L in layers:
        res, geo = L["res"], L["geo"]
        closed = ndimage.binary_closing(L["cov"], np.ones((3, 3)))
        inner = ndimage.binary_erosion(closed, np.ones((3, 3)), iterations=2)
        arr = np.asarray(L["pil"].convert("RGB")).astype(np.float32) / 255.0
        L["srgb_full"] = arr
        b = res // geo
        if b > 1:
            w = inner.reshape(geo, b, geo, b).astype(np.float32)
            c = (arr.reshape(geo, b, geo, b, 3) * w[..., None]).sum(axis=(1, 3))
            nn = w.sum(axis=(1, 3))
            col = np.where(nn[..., None] > 0, c / np.maximum(nn, 1)[..., None], 0)
            L["valid"] = (nn > 0) & L["gmask"]
        else:
            col = arr
            L["valid"] = inner & L["gmask"]
        L["lin"] = srgb_to_linear(col).astype(np.float32)
        L["lum"] = (L["lin"] @ LUMW).astype(np.float32)

    # --- exteriority --------------------------------------------------------
    sub = all_pts[:: max(1, len(all_pts) // 400000)]
    for L in layers:
        L["ao"] = exteriority(L["pos"], L["valid"], sub)

    ext = np.concatenate([L["ao"][L["valid"]] > args.ext_ao for L in layers])
    pos_all = np.concatenate([L["pos"][L["valid"]] for L in layers])
    lin_all = np.concatenate([L["lin"][L["valid"]] for L in layers])
    lum_all = np.concatenate([L["lum"][L["valid"]] for L in layers])
    if ext.sum() < 5000:
        refuse("only %d exterior texels -- the mesh is not a closed body or the atlas is tiny" % ext.sum())
    print("texels: %d covered, %d exterior (%.0f%%)" % (len(ext), ext.sum(), 100 * ext.mean()))

    # --- paint class --------------------------------------------------------
    paint, info = find_paint(lin_all, lum_all, pos_all, ext, cell)
    if paint is None:
        refuse("no colour cluster found on the exterior")
    print("paint class: %d texels = %.0f%% of the exterior, chromaticity (%.3f, %.3f), median luminance %.3f"
          % (paint.sum(), 100 * info["frac_of_exterior"], info["chroma"][0], info["chroma"][1], info["median_lum"]))
    print("             spread over %d of %d body cells (%.0f%%)"
          % (info["coverage_cells"], info["total_cells"], 100 * info["coverage_cells"] / max(info["total_cells"], 1)))
    if info["frac_of_exterior"] < args.min_paint_frac:
        refuse("paint class is only %.0f%% of the exterior (need %.0f%%) -- cannot tell paint from trim"
               % (100 * info["frac_of_exterior"], 100 * args.min_paint_frac))
    if info["coverage_cells"] < 0.25 * info["total_cells"]:
        refuse("the dominant colour cluster covers only %.0f%% of the body -- it is a part, not the paint"
               % (100 * info["coverage_cells"] / max(info["total_cells"], 1)))

    # --- measure BEFORE -----------------------------------------------------
    before = spread_report(pos_all, paint, lum_all, cell)
    trends = axis_trends(pos_all, paint, lum_all)
    print("\nBAKED LIGHTING MEASURED (paint, median per %.0f mm-equivalent cell, %d cells):"
          % (cell / diag * 4000, before["cells"]))
    print("  linear luminance  p5 %.3f  p25 %.3f  med %.3f  p75 %.3f  p95 %.3f"
          % (before["p5"], before["p25"], before["p50"], before["p75"], before["p95"]))
    print("  low-frequency spread p95/p5 = %.2fx   interquartile = %.2fx" % (before["spread"], before["iqr"]))
    for name, r in trends:
        print("  trend along the %-8s body axis: %.2fx end to end" % (name, r))
    print("  high-frequency detail (residual log-luminance std): %.4f" % before["detail_std"])
    if before["spread"] < args.min_spread and not args.force:
        refuse("low-frequency spread %.2fx is below --min-spread %.2fx: there is no baked lighting worth "
               "removing, and re-encoding the texture would only cost quality. Use --force to override."
               % (before["spread"], args.min_spread))

    # --- fit and apply ------------------------------------------------------
    S, org, cellsz, ref, nsup, ncell = shading_field(
        pos_all, paint, lum_all, cell, args.sigma_cells, args.clamp, min_cell=25)
    fs = sample_field(S, org, cellsz, pos_all[paint])
    print("\nlighting field: %d cells from %d paint texels, correction %.3f..%.3f (median %.3f); "
          "%.0f%% of paint area moves by more than 10%%"
          % (ncell, nsup, fs.min(), fs.max(), np.median(fs), 100 * np.mean(np.abs(fs - 1) > 0.10)))

    lum_new = lum_all / np.maximum(sample_field(S, org, cellsz, pos_all), 1e-3)
    after = spread_report(pos_all, paint, lum_new, cell)
    print("AFTER: spread p95/p5 = %.2fx (was %.2fx), interquartile = %.2fx (was %.2fx), "
          "detail std %.4f (was %.4f)"
          % (after["spread"], before["spread"], after["iqr"], before["iqr"],
             after["detail_std"], before["detail_std"]))
    for (name, r0), (_, r1) in zip(trends, axis_trends(pos_all, paint, lum_new)):
        print("  trend along the %-8s axis: %.2fx -> %.2fx" % (name, r0, r1))

    rep = dict(input=args.inp, output=args.out, diagonal=diag, cell=cell,
               paint=info, before=before, after=after,
               trends_before=dict(trends), trends_after=dict(axis_trends(pos_all, paint, lum_new)),
               field_min=float(fs.min()), field_max=float(fs.max()))
    if args.report:
        with open(args.report, "w") as f:
            json.dump(rep, f, indent=1)
    if args.dry_run:
        print("\n--dry-run: nothing written")
        return

    # --- rewrite the textures ----------------------------------------------
    new_images = {}
    for L in layers:
        res, geo = L["res"], L["geo"]
        # S is smooth by construction, so evaluating it on the geometry grid and
        # upsampling is exact enough and avoids a full-res position map.
        pts = L["pos"].reshape(-1, 3)
        f = sample_field(S, org, cellsz, pts).reshape(geo, geo).astype(np.float32)
        # carry the correction into the gutter so chart edges stay continuous
        bad = ~L["valid"]
        if bad.any():
            _, ind = ndimage.distance_transform_edt(bad, return_indices=True)
            f = f[tuple(ind)]
        if res != geo:
            f = ndimage.zoom(f, res / geo, order=1)
            if f.shape[0] != res:
                f = np.resize(f, (res, res))
        lin = srgb_to_linear(L["srgb_full"])
        out = linear_to_srgb(lin / np.maximum(f, 1e-3)[..., None])
        rgb = np.clip(out * 255.0 + 0.5, 0, 255).astype(np.uint8)
        im = Image.fromarray(rgb, "RGB")
        buf = io.BytesIO()
        fmt = (L["fmt"] or "PNG").upper()
        if fmt == "WEBP":
            im.save(buf, "WEBP", lossless=(args.lossy == 0), quality=(args.lossy or 80), method=4)
        elif fmt in ("JPEG", "JPG"):
            im.save(buf, "JPEG", quality=(args.lossy or 95), subsampling=0)
        else:
            im.save(buf, "PNG", compress_level=6)
        new_images[L["img"]] = buf.getvalue()
        print("  image %d re-encoded as %s: %.2f MB -> %.2f MB"
              % (L["img"], fmt, len(bn[g["bufferViews"][g["images"][L["img"]]["bufferView"]]["byteOffset"]
                                        if "byteOffset" in g["bufferViews"][g["images"][L["img"]]["bufferView"]] else 0:][
                                    :g["bufferViews"][g["images"][L["img"]]["bufferView"]]["byteLength"]]) / 1e6,
                 len(buf.getvalue()) / 1e6))

    # rebuild the BIN chunk with the replaced image bufferViews
    views = []
    for i, bv in enumerate(g["bufferViews"]):
        off = bv.get("byteOffset", 0)
        views.append((i, off, bv["byteLength"]))
    repl = {}
    for img_i, data in new_images.items():
        repl[g["images"][img_i]["bufferView"]] = data
    out = bytearray()
    for i, off, ln in sorted(views, key=lambda t: t[1]):
        data = repl.get(i, bn[off:off + ln])
        pad = (4 - len(out) % 4) % 4
        out += b"\0" * pad
        g["bufferViews"][i]["byteOffset"] = len(out)
        g["bufferViews"][i]["byteLength"] = len(data)
        out += data
    g["buffers"][0]["byteLength"] = len(out)
    g["buffers"][0].pop("uri", None)
    write_glb(args.out, g, bytes(out))
    print("\nwrote %s (%.1f MB)" % (args.out, len(out) / 1e6))


if __name__ == "__main__":
    main()
