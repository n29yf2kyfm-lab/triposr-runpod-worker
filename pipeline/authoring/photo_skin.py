#!/usr/bin/env python3
"""photo_skin.py — bake a real car PHOTO onto the authored body's texture.

The technique is the one every architectural visualiser uses to turn a photo of
a building into a convincing 3D building in about a minute: keep the geometry
simple, and let the PHOTOGRAPH carry the detail as texture. STUDY_3D.md already
measured why that is the right call for us — at the viewer's 5mm/pixel a shut
line is 0.6 of a pixel, so panel detail is a SHADING phenomenon — and this is
the same argument applied to the thing that actually makes a car recognisable:
its graphics. A generic hatchback with a Yaris photo baked on reads as a Yaris;
the geometry alone never will.

This is a BAKE, not a render-time projection. For every texel we already know
the 3D point (the loft grid IS the texture parametrisation), so we project that
point into the photograph, sample it, and write it into the same texture space
skin.py paints the seams and AO into. One texture, one material, no extra UV
set, and resprays still work because the paint colour stays in
baseColorFactor... except where the photo overrides it, which is the honest
trade named below.

INPUT REQUIREMENT, and it is a hard one: a TRUE SIDE view, background removed.
A three-quarter photo carries perspective, so the far end of the car is smaller
in frame than the near end and the bake stretches it — visible as a smeared
nose or tail. There is no clever fix; the technique needs an orthographic-ish
side elevation, which is exactly why the demo README's capture contract asks
for one. The `--view` argument records which view was supplied so the caller
cannot silently bake a 3/4 shot and wonder why the doors slide.

TRADE, stated plainly: baking a photo means the body no longer respray-safe in
the region the photo covers — the photo's own colour is burned in. For a
catalogue that ships eight colours per car, use this for a photographic HERO
variant and keep the flat-paint build for the colour swatches.
"""
import io

import numpy as np
from PIL import Image, ImageFilter


def _alpha_bbox(im):
    """Tight bounding box of the car in a background-removed photo."""
    a = np.asarray(im.convert("RGBA"))[:, :, 3]
    ys, xs = np.where(a > 24)
    if len(xs) == 0:
        raise ValueError("photo has no opaque pixels — is the background removed?")
    return xs.min(), ys.min(), xs.max(), ys.max()


def bake(car, P, us, photo_path, tex_w=2048, tex_h=512, view="side",
         base_rgb=(184, 186, 190), flank_power=2.0):
    """Project `photo_path` onto the loft grid and return (png_bytes, stats).

    P   : (stations, nv, 3) loft grid — the same one the mesh is built from
    us  : (stations,) station parameters, 0 tail -> 1 nose
    view: 'side' (correct), or '3q'/'front'/'rear' (recorded, expect stretch)
    """
    photo = Image.open(photo_path).convert("RGBA")
    px0, py0, px1, py1 = _alpha_bbox(photo)
    ph = np.asarray(photo).astype(np.float64)
    H_img, W_img = ph.shape[:2]

    nstat, nv = P.shape[0], P.shape[1]
    # model bounds used for the mapping: length on X, height on Y
    Xmin, Xmax = P[:, :, 0].min(), P[:, :, 0].max()
    Ymin, Ymax = P[:, :, 1].min(), P[:, :, 1].max()

    # --- per-texel 3D point, by bilinear lookup into the loft grid
    tx = np.linspace(0, 1, tex_w)
    ty = np.linspace(0, 1, tex_h)
    # texture v runs 1 - j/(nv-1) (see emit_grid), so invert it here
    jj = (1.0 - ty) * (nv - 1)
    ii = np.interp(tx, us, np.arange(nstat))       # station index per texel column
    i0 = np.clip(ii.astype(int), 0, nstat - 2)
    fi = (ii - i0)[None, :, None]
    j0 = np.clip(jj.astype(int), 0, nv - 2)
    fj = (jj - j0)[:, None, None]

    A = P[i0][:, :, :]                              # (tex_w, nv, 3) -> reorder below
    A = np.transpose(P[i0], (0, 1, 2))              # (tex_w, nv, 3)
    B = P[i0 + 1]
    S = A * (1 - fi.transpose(1, 0, 2)) + B * fi.transpose(1, 0, 2)   # (tex_w, nv, 3)
    S = np.transpose(S, (1, 0, 2))                  # (nv, tex_w, 3)
    lower = S[j0]                                   # (tex_h, tex_w, 3)
    upper = S[np.clip(j0 + 1, 0, nv - 1)]
    Pt = lower * (1 - fj) + upper * fj              # (tex_h, tex_w, 3)

    # --- project into the photograph: X -> image x, Y -> image y (flipped)
    fx = (Pt[:, :, 0] - Xmin) / max(Xmax - Xmin, 1e-9)
    fy = (Pt[:, :, 1] - Ymin) / max(Ymax - Ymin, 1e-9)
    sx = np.clip(px0 + fx * (px1 - px0), 0, W_img - 1).astype(int)
    sy = np.clip(py1 - fy * (py1 - py0), 0, H_img - 1).astype(int)
    samp = ph[sy, sx]                               # (tex_h, tex_w, 4)
    rgb = samp[:, :, :3]
    hit = samp[:, :, 3] > 24                        # sampled a real car pixel

    # --- how sideways-facing is this texel? Only the flank can legitimately
    # take a side photo; the roof and bonnet face up and would smear, so they
    # fall back to flat paint. Surface normal is approximated from the section
    # tangent (the loft's own geometry), no extra data needed.
    dj = np.gradient(Pt, axis=0)                    # along the section
    di = np.gradient(Pt, axis=1)                    # along the car
    n = np.cross(di, dj)
    ln = np.linalg.norm(n, axis=2, keepdims=True)
    n = n / np.maximum(ln, 1e-9)
    w = np.abs(n[:, :, 2]) ** flank_power           # |nz| = sideways
    w = np.where(hit, w, 0.0)
    w = np.asarray(Image.fromarray((w * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(3.0)), dtype=np.float64) / 255.0

    base = np.array(base_rgb, dtype=np.float64)[None, None, :]
    out = rgb * w[:, :, None] + base * (1 - w[:, :, None])
    img = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")

    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    stats = {"view": view, "photo": photo_path.split("/")[-1],
             "photo_bbox": [int(px0), int(py0), int(px1), int(py1)],
             "coverage": round(float(w.mean()), 3),
             "warning": None if view == "side" else
             f"view='{view}' is not a side elevation — expect stretch at the ends"}
    return buf.getvalue(), stats


def composite_ao(photo_png, ao_png):
    """Multiply the baked photo by skin.py's AO/seam map.

    Keeps the engraved shut lines and sill shadow reading on top of the
    photograph instead of the photo washing them out.
    """
    a = Image.open(io.BytesIO(photo_png)).convert("RGB")
    b = Image.open(io.BytesIO(ao_png)).convert("RGB").resize(a.size, Image.LANCZOS)
    out = np.asarray(a, np.float64) * (np.asarray(b, np.float64) / 255.0)
    buf = io.BytesIO()
    Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB").save(
        buf, "PNG", optimize=True)
    return buf.getvalue()
