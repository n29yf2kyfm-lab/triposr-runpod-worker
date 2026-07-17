"""Surface polish for GENERATED models.

Voxel-derived surfaces read "soft": flat panels carry low-amplitude waviness
(wobbly reflections), and the baked texture has smudged edges and blotchy
paint shading. Neither needs re-generation to fix:

- geometry: recompute vertex normals seam-welded across UV islands, then run
  crease-preserving Laplacian smoothing on them. Flat regions (neighbour
  normals nearly parallel) get fully smoothed -> mirror-flat reflections;
  creases and edges are left alone so the body lines stay sharp.
- texture: unsharp-mask the baseColor (crisps light clusters, grille edges,
  badges) and smooth the chroma channels only (evens out patchy paint tone
  without touching luminance detail). Glass/cutout texels are excluded.

Input (handler): polish: true (default for generated cars) | false
                 or {"sharpen": 0.2-2.0, "smooth_iters": 0-4}
"""
import sys
from io import BytesIO

import numpy as np
from PIL import Image, ImageFilter

from wheel_swap import _read_glb, _write_glb
from oem_paint import _tex_source


def _accessor_f32(j, bin_data, acc_i):
    """Return (array view copy, bufferView offset, stride) for a VEC3 f32."""
    acc = j["accessors"][acc_i]
    bv = j["bufferViews"][acc["bufferView"]]
    off = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    n = acc["count"]
    stride = bv.get("byteStride") or 12
    raw = np.frombuffer(bytes(bin_data[off:off + stride * n]),
                        dtype=np.uint8).reshape(n, stride)
    return raw[:, :12].copy().view(np.float32).reshape(n, 3), off, stride


def _indices(j, bin_data, prim):
    acc = j["accessors"][prim["indices"]]
    bv = j["bufferViews"][acc["bufferView"]]
    off = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    dt = {5121: np.uint8, 5123: np.uint16, 5125: np.uint32}[acc["componentType"]]
    F = np.frombuffer(bytes(bin_data[off:off + acc["count"] * dt().nbytes]),
                      dtype=dt).astype(np.int64)
    return F.reshape(-1, 3)


def smooth_normals(j, bin_data, iters=2, pos_iters=6,
                   cell_frac=0.025, lim_frac=0.006):
    """Crease-preserving surface polish, written back in place: Taubin
    position smoothing constrained to the normal direction (removes the
    voxel waviness that lives in the VERTICES — normal smoothing alone left
    the tailgate lumpy on the live Golf), then normal-field smoothing.
    Returns fraction of vertices smoothed, or None."""
    prim = j["meshes"][0]["primitives"][0]
    attrs = prim.get("attributes", {})
    if "NORMAL" not in attrs or "POSITION" not in attrs or "indices" not in prim:
        return None
    V, _, _ = _accessor_f32(j, bin_data, attrs["POSITION"])
    F = _indices(j, bin_data, prim)

    # weld by position so UV-seam duplicates smooth as one surface point
    key = np.round(V.astype(np.float64) * 1e5).astype(np.int64)
    _, weld, inv = np.unique(key, axis=0, return_index=True,
                             return_inverse=True)
    W = weld.shape[0]
    Fw = inv[F]

    # area-weighted face normals accumulated per welded vertex
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]]).astype(np.float64)
    N = np.zeros((W, 3))
    for k in range(3):
        np.add.at(N, Fw[:, k], fn)
    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)

    deg = np.zeros(W)
    e = np.concatenate([Fw[:, [0, 1]], Fw[:, [1, 2]], Fw[:, [2, 0]]])
    e = np.concatenate([e, e[:, ::-1]])   # symmetric neighbourhood
    np.add.at(deg, e[:, 0], 1.0)

    def nb_mean(A):
        acc = np.zeros((W, A.shape[1]))
        np.add.at(acc, e[:, 0], A[e[:, 1]])
        return acc / np.maximum(deg, 1.0)[:, None]

    # --- position pass: Taubin (shrink-free) along the normal only ---
    Pw = np.zeros((W, 3))
    np.add.at(Pw, inv, V.astype(np.float64))
    cnt = np.zeros(W)
    np.add.at(cnt, inv, 1.0)
    Pw /= cnt[:, None]

    # --- coarse flattening field: voxel waviness spans dozens of edges, far
    # beyond what 1-ring iterations reach (live Golf tailgate stayed lumpy).
    # Cluster the surface into ~2.5%-of-model cells, smooth the cell centers
    # along their normals, and apply the low-frequency correction back. ---
    if pos_iters:
        scale = float(np.linalg.norm(Pw.max(0) - Pw.min(0)))
        cell = float(cell_frac) * max(scale, 1e-9)
        q = np.floor(Pw / cell).astype(np.int64)
        uq, binv = np.unique(q, axis=0, return_inverse=True)
        B = len(uq)
        bc = np.zeros((B, 3)); bn = np.zeros((B, 3)); bcnt = np.zeros(B)
        np.add.at(bc, binv, Pw); np.add.at(bn, binv, N)
        np.add.at(bcnt, binv, 1.0)
        bc /= bcnt[:, None]
        bn /= np.maximum(np.linalg.norm(bn, axis=1, keepdims=True), 1e-12)
        lut = {tuple(r): i for i, r in enumerate(uq)}
        be = []
        for off in ((1, 0, 0), (0, 1, 0), (0, 0, 1),
                    (1, 1, 0), (1, 0, 1), (0, 1, 1)):
            for i, r in enumerate(uq):
                nb_i = lut.get((r[0] + off[0], r[1] + off[1], r[2] + off[2]))
                if nb_i is not None:
                    be.append((i, nb_i))
        if be:
            be = np.array(be, dtype=np.int64)
            be = np.concatenate([be, be[:, ::-1]])
            bdeg = np.zeros(B)
            np.add.at(bdeg, be[:, 0], 1.0)
            bc0 = bc.copy()
            for it in range(8):
                acc = np.zeros((B, 3))
                np.add.at(acc, be[:, 0], bc[be[:, 1]])
                nbm = acc / np.maximum(bdeg, 1.0)[:, None]
                accn = np.zeros((B, 3))
                np.add.at(accn, be[:, 0], bn[be[:, 1]])
                accn /= np.maximum(np.linalg.norm(accn, axis=1, keepdims=True), 1e-12)
                dflat = np.einsum("ij,ij->i", bn, accn)
                bw = np.clip((dflat - 0.87) / (0.97 - 0.87), 0.0, 1.0)
                lam = 0.6 if it % 2 == 0 else -0.63
                along = np.einsum("ij,ij->i", nbm - bc, bn)
                bc += (lam * bw * along)[:, None] * bn
            bdisp = bc - bc0
            vdisp = bdisp[binv]
            for _ in range(3):     # blend cell seams over the fine graph
                acc = np.zeros((W, 3))
                np.add.at(acc, e[:, 0], vdisp[e[:, 1]])
                vdisp = 0.5 * vdisp + 0.5 * acc / np.maximum(deg, 1.0)[:, None]
            mag = np.linalg.norm(vdisp, axis=1, keepdims=True)
            lim = float(lim_frac) * scale
            vdisp *= np.minimum(1.0, lim / np.maximum(mag, 1e-12))
            Pw += vdisp
            fn = np.cross(Pw[Fw[:, 1]] - Pw[Fw[:, 0]],
                          Pw[Fw[:, 2]] - Pw[Fw[:, 0]])
            N = np.zeros((W, 3))
            for k in range(3):
                np.add.at(N, Fw[:, k], fn)
            N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
    for it in range(max(0, pos_iters)):
        nbn = nb_mean(N)
        nbn /= np.maximum(np.linalg.norm(nbn, axis=1, keepdims=True), 1e-12)
        d = np.einsum("ij,ij->i", N, nbn)
        w = np.clip((d - 0.906) / (0.985 - 0.906), 0.0, 1.0)
        lam = 0.55 if it % 2 == 0 else -0.58
        disp = nb_mean(Pw) - Pw
        along = np.einsum("ij,ij->i", disp, N)
        Pw += (lam * w * along)[:, None] * N
        # refresh face/vertex normals from the moved surface
        fn = np.cross(Pw[Fw[:, 1]] - Pw[Fw[:, 0]],
                      Pw[Fw[:, 2]] - Pw[Fw[:, 0]])
        N = np.zeros((W, 3))
        for k in range(3):
            np.add.at(N, Fw[:, k], fn)
        N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
    if pos_iters:
        pos_i = attrs["POSITION"]
        _, poff, pstride = _accessor_f32(j, bin_data, pos_i)
        outp = Pw[inv].astype(np.float32)
        if pstride == 12:
            bin_data[poff:poff + len(outp) * 12] = outp.tobytes()
        else:
            flat = outp.view(np.uint8).reshape(len(outp), 12)
            for i in range(len(outp)):
                s = poff + i * pstride
                bin_data[s:s + 12] = flat[i].tobytes()
        pacc = j["accessors"][pos_i]
        if "min" in pacc:
            pacc["min"] = outp.min(0).tolist()
            pacc["max"] = outp.max(0).tolist()

    smoothed_frac = 0.0
    for _ in range(max(0, iters)):
        acc = np.zeros((W, 3))
        np.add.at(acc, e[:, 0], N[e[:, 1]])
        nb = acc / np.maximum(deg, 1.0)[:, None]
        nb /= np.maximum(np.linalg.norm(nb, axis=1, keepdims=True), 1e-12)
        d = np.einsum("ij,ij->i", N, nb)
        # flat where neighbours agree (d ~ 1); crease where they diverge.
        w = np.clip((d - 0.906) / (0.985 - 0.906), 0.0, 1.0)  # 25deg..10deg
        smoothed_frac = float((w > 0.5).mean())
        N = N * (1 - w[:, None]) + nb * w[:, None]
        N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)

    # write back through the weld map at the accessor's real stride
    acc_i = attrs["NORMAL"]
    _, off, stride = _accessor_f32(j, bin_data, acc_i)
    out = N[inv].astype(np.float32)
    n = out.shape[0]
    if stride == 12:
        bin_data[off:off + n * 12] = out.tobytes()
    else:
        flat = out.view(np.uint8).reshape(n, 12)
        for i in range(n):  # rare interleaved case
            s = off + i * stride
            bin_data[s:s + 12] = flat[i].tobytes()
    return smoothed_frac


def polish_texture(j, bin_data, sharpen=1.0):
    """Unsharp-mask + chroma smoothing on baseColor. Returns new blob's
    (image index, bytes) or None."""
    mat = j["materials"][0]
    pbr = mat.get("pbrMetallicRoughness", {})
    if "baseColorTexture" not in pbr:
        return None
    img_i = _tex_source(j["textures"][pbr["baseColorTexture"]["index"]])
    bv = j["bufferViews"][j["images"][img_i]["bufferView"]]
    off, ln = bv.get("byteOffset", 0), bv["byteLength"]
    im = Image.open(BytesIO(bytes(bin_data[off:off + ln]))).convert("RGBA")
    rgb = im.convert("RGB")
    a = np.asarray(im)[..., 3]

    # paint-tone de-blotch: smooth chroma only, keep luminance detail
    ycc = rgb.convert("YCbCr")
    yy, cb, cr = ycc.split()
    cb = cb.filter(ImageFilter.GaussianBlur(3))
    cr = cr.filter(ImageFilter.GaussianBlur(3))
    rgb = Image.merge("YCbCr", (yy, cb, cr)).convert("RGB")

    # edge crispness: moderate unsharp mask, thresholded against noise
    pct = int(np.clip(120 * sharpen, 20, 300))
    rgb = rgb.filter(ImageFilter.UnsharpMask(radius=2, percent=pct, threshold=3))

    out = np.dstack([np.asarray(rgb), a]).astype(np.uint8)
    # glass texels keep their original colour (sharpening halos on glass
    # edges read as dirt)
    orig = np.asarray(im)
    glass = a < 200
    out[glass] = orig[glass]

    buf = BytesIO()
    mime = j["images"][img_i].get("mimeType", "image/webp")
    Image.fromarray(out).save(buf, "WEBP" if "webp" in mime else "PNG",
                              quality=95)
    return img_i, buf.getvalue()


def apply_polish(glb_path, spec=True):
    """Sharpen + flatten a generated GLB in place. Returns report or None."""
    try:
        sharpen, iters, flatten = 1.0, 2, 6
        cell_frac, lim_frac = 0.025, 0.006
        if isinstance(spec, dict):
            sharpen = float(np.clip(spec.get("sharpen", 1.0), 0.2, 2.0))
            iters = int(np.clip(spec.get("smooth_iters", 2), 0, 4))
            flatten = int(np.clip(spec.get("flatten_iters", 6), 0, 12))
            cell_frac = float(np.clip(spec.get("flatten_cell", 0.025), 0.01, 0.06))
            lim_frac = float(np.clip(spec.get("flatten_limit", 0.006), 0.0, 0.02))

        j, jtype, bin_data = _read_glb(glb_path)
        frac = (smooth_normals(j, bin_data, iters, flatten, cell_frac, lim_frac)
                if (iters or flatten) else None)
        tex = polish_texture(j, bin_data, sharpen)
        if frac is None and tex is None:
            return None
        if tex is not None:
            img_i, blob = tex
            while len(bin_data) % 4:
                bin_data.append(0)
            start = len(bin_data)
            bin_data.extend(blob)
            j["bufferViews"].append({"buffer": 0, "byteOffset": start,
                                     "byteLength": len(blob)})
            j["images"][img_i]["bufferView"] = len(j["bufferViews"]) - 1
        _write_glb(glb_path, j, jtype, bin_data)
        print(f"polish: normals smoothed on {frac:.1%} of surface, "
              f"texture sharpen={sharpen}" if frac is not None else
              f"polish: texture sharpen={sharpen} (no normals)",
              file=sys.stderr)
        return {"applied": True, "smoothed": None if frac is None else round(frac, 4),
                "sharpen": sharpen}
    except Exception as e:
        print(f"polish skipped: {e}", file=sys.stderr)
        return None
