#!/usr/bin/env python3
"""multiskin.py — bake the side, front AND rear photographs onto the loft.

photo_skin.bake projects one side view along the car. A car is recognised
by its face and its tail as much as its flank, so this does the same for
all three views and blends them by where each texel faces: flank texels take
the side photo, nose texels the front photo, tail texels the rear photo.
Up-facing texels (roof, bonnet top) keep the flat paint, as before — no view
sees them without stretch.

Frames (nose +X, up +Y, right-hand side of the car +Z):
    side   image x <- X            image y <- Y
    front  camera at +X looking back: the car's right (+Z) is on the viewer's
           LEFT, so image x <- -Z
    rear   camera at -X: image x <- +Z
The end views are scaled to the BODY's width, measured on the rows below
60% of the height so the mirrors do not shrink the car.
"""
import io

import numpy as np
from PIL import Image, ImageFilter


def _texel_points(P, us, tex_w, tex_h):
    nstat, nv = P.shape[0], P.shape[1]
    tx = np.linspace(0, 1, tex_w)
    ty = np.linspace(0, 1, tex_h)
    jj = (1.0 - ty) * (nv - 1)
    ii = np.interp(tx, us, np.arange(nstat))
    i0 = np.clip(ii.astype(int), 0, nstat - 2)
    fi = (ii - i0)[None, :, None]
    j0 = np.clip(jj.astype(int), 0, nv - 2)
    fj = (jj - j0)[:, None, None]
    S = P[i0] * (1 - fi.transpose(1, 0, 2)) + P[i0 + 1] * fi.transpose(1, 0, 2)
    S = np.transpose(S, (1, 0, 2))
    Pt = S[j0] * (1 - fj) + S[np.clip(j0 + 1, 0, nv - 1)] * fj
    dj = np.gradient(Pt, axis=0)
    di = np.gradient(Pt, axis=1)
    n = np.cross(di, dj)
    n = n / np.maximum(np.linalg.norm(n, axis=2, keepdims=True), 1e-9)
    return Pt, n


def _bbox(alpha, rows=None):
    ys, xs = np.where(alpha > 24)
    if rows is not None:
        keep = (ys >= rows[0]) & (ys <= rows[1])
        xs, ys = xs[keep], ys[keep]
    return xs.min(), ys.min(), xs.max(), ys.max()


def _sample(photo_path, Pt, view):
    ph = np.asarray(Image.open(photo_path).convert("RGBA")).astype(np.float64)
    H, W = ph.shape[:2]
    a = ph[:, :, 3]
    ys, xs = np.where(a > 24)
    py0, py1 = ys.min(), ys.max()
    if view == "side":
        px0, px1 = xs.min(), xs.max()
        Xmin, Xmax = Pt[:, :, 0].min(), Pt[:, :, 0].max()
        fx = (Pt[:, :, 0] - Xmin) / max(Xmax - Xmin, 1e-9)
    else:
        # body width from the rows below 60% of the height: no mirrors
        lo = py1 - 0.60 * (py1 - py0)
        px0, _, px1, _ = _bbox(a, rows=(lo, py1))
        Zmin, Zmax = Pt[:, :, 2].min(), Pt[:, :, 2].max()
        fz = (Pt[:, :, 2] - Zmin) / max(Zmax - Zmin, 1e-9)
        fx = 1.0 - fz if view == "front" else fz
    Ymin, Ymax = Pt[:, :, 1].min(), Pt[:, :, 1].max()
    fy = (Pt[:, :, 1] - Ymin) / max(Ymax - Ymin, 1e-9)
    sx = np.clip(px0 + fx * (px1 - px0), 0, W - 1).astype(int)
    sy = np.clip(py1 - fy * (py1 - py0), 0, H - 1).astype(int)
    samp = ph[sy, sx]
    return samp[:, :, :3], samp[:, :, 3] > 24


def _body_colour(photo_path):
    """Mean colour of the paint band (25-55% of the height), ignoring glass
    and the darkest shadow, so three photos of differently lit or differently
    coloured cars can be brought to one paint colour."""
    ph = np.asarray(Image.open(photo_path).convert("RGBA")).astype(np.float64)
    a = ph[:, :, 3] > 128
    ys = np.where(a.any(1))[0]
    y0, y1 = ys.min(), ys.max()
    band = np.zeros_like(a)
    band[int(y1 - 0.55 * (y1 - y0)):int(y1 - 0.25 * (y1 - y0))] = True
    px = ph[a & band][:, :3]
    lum = px.mean(1)
    keep = (lum > np.percentile(lum, 20)) & (lum < np.percentile(lum, 95))
    return px[keep].mean(0) if keep.sum() > 50 else px.mean(0)


def bake_all(P, us, photos, tex_w=2048, tex_h=512, base_rgb=(184, 186, 190), power=2.0):
    """photos: {'side': path, 'front': path, 'rear': path} (any subset).
    Returns (png_bytes, stats)."""
    Pt, n = _texel_points(P, us, tex_w, tex_h)
    facing = {"side": np.abs(n[:, :, 2]), "front": np.maximum(n[:, :, 0], 0), "rear": np.maximum(-n[:, :, 0], 0)}
    acc = np.zeros(Pt.shape[:2] + (3,))
    wsum = np.zeros(Pt.shape[:2])
    stats = {}
    # the side photo sets the paint; the end photos are matched to it so a
    # black nose does not end up on a silver car
    ref = _body_colour(photos["side"]) if photos.get("side") else None
    for view, path in photos.items():
        if not path or view not in facing:
            continue
        rgb, hit = _sample(path, Pt, view)
        if ref is not None and view != "side":
            gain = np.clip(ref / np.maximum(_body_colour(path), 1.0), 0.4, 2.5)
            rgb = np.clip(rgb * gain[None, None, :], 0, 255)
            stats[view + "_gain"] = [round(float(g), 2) for g in gain]
        w = facing[view] ** power
        w = np.where(hit, w, 0.0)
        w = np.asarray(Image.fromarray((w * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(3.0)),
                       dtype=np.float64) / 255.0
        acc += rgb * w[:, :, None]
        wsum += w
        stats[view] = round(float(w.mean()), 3)
    base = np.array(base_rgb, dtype=np.float64)[None, None, :]
    cover = np.clip(wsum, 0, 1)
    out = np.where(wsum[:, :, None] > 0, acc / np.maximum(wsum, 1e-9)[:, :, None], base)
    out = out * cover[:, :, None] + base * (1 - cover[:, :, None])
    img = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue(), {"views": stats, "coverage": round(float(cover.mean()), 3)}
