#!/usr/bin/env python3
"""recess_glass.py — find GLAZING on a Hi3DGen mesh by detecting RECESSES.

Why this exists (measured, 2026-08-15): Hi3DGen models glazing as recessed
panels — watertight, no material, but geometrically INSET from the surrounding
sheetmetal. PartCrafter could not be relied on to hand us a greenhouse part
(the Golf run emitted five overlapping mega-parts), so glass must be read off
the shape itself. A recess is exactly the thing a local-background comparison
finds: rasterise the flank into a width-map, estimate the local skin level
with a coarse maximum filter, and mark faces that sit measurably INSIDE it.

Bands and thresholds are fractions of the car's own bbox, so the detector is
scale-free. Verdicts are printed per region; the output is a FACE MASK (npy)
plus an optional preview GLB with the mask painted as a dark material so the
result can be LOOKED at before anything downstream trusts it.

Usage:
    python3 pipeline/carglb/recess_glass.py shape.glb mask.npy [preview.glb]
"""
import sys

import numpy as np
import trimesh


def axes_of(V):
    ext = V.max(0) - V.min(0)
    L = int(np.argmax(ext))
    rest = [i for i in range(3) if i != L]
    H = rest[int(np.argmin(ext[rest]))]
    W = [i for i in rest if i != H][0]
    return L, H, W


def sliding_row_max(img, win):
    """Per ROW, the maximum over a sliding window of +-win columns.

    v1 used a coarse CELL max and marked 21.7% of the car glass — over a cell
    (~4% of length) ordinary body curvature exceeds any recess depth, so
    everything scored "inset". The correct skin reference is the PILLAR level:
    the widest surface at the SAME HEIGHT, nearby in length. A sliding
    row-max is exactly that, and it never compares across heights, so
    tumblehome (the body legitimately narrowing with height) cannot trigger.
    """
    out = img.copy()
    for shift in range(1, win + 1):
        out[:, shift:] = np.maximum(out[:, shift:], img[:, :-shift])
        out[:, :-shift] = np.maximum(out[:, :-shift], img[:, shift:])
    return out


def detect(src, mask_out=None, preview=None, depth_frac=0.008, win_frac=0.10):
    m = trimesh.load(src, force="mesh")
    V = np.asarray(m.vertices)
    F = np.asarray(m.faces)
    N = m.face_normals
    C = V[F].mean(axis=1)
    lo, hi = V.min(0), V.max(0)
    ext = hi - lo
    L, H, W = axes_of(V)
    depth = depth_frac * ext[L]          # how far inside the skin = glass
    win = max(2, int(0.5 * win_frac * 512))   # sliding half-window in pixels
    glass = np.zeros(len(F), dtype=bool)

    def norm(a, axis):
        return (a - lo[axis]) / ext[axis]

    res = 512
    # ---- side windows: one width-map per side ------------------------------
    for sign in (+1, -1):
        side = (N[:, W] * sign > 0.55)
        band = (norm(C[:, H], H) > 0.42) & (norm(C[:, H], H) < 0.95) \
            & (norm(C[:, L], L) > 0.08) & (norm(C[:, L], L) < 0.92)
        sel = side & band
        if not sel.any():
            continue
        u = (norm(C[sel, L], L) * (res - 1)).astype(int)
        v = (norm(C[sel, H], H) * (res - 1)).astype(int)
        w = C[sel, W] * sign             # outward offset, larger = skin
        img = np.full((res, res), -np.inf)
        np.maximum.at(img, (v, u), w)
        bg = sliding_row_max(img, win)    # pillar level at this height, nearby
        pix_bg = bg[v, u]
        face_inset = pix_bg - w
        glass_sel = face_inset > depth
        idx = np.where(sel)[0][glass_sel]
        glass[idx] = True
        print(f"side {'+' if sign>0 else '-'}: band faces {sel.sum():6d} "
              f"-> glass {glass_sel.sum():6d}")

    # ---- windscreen + backlight: height-map from above ---------------------
    up = N[:, H] > 0.30
    band = (norm(C[:, H], H) > 0.55) & (norm(C[:, L], L) > 0.05) \
        & (norm(C[:, L], L) < 0.95)
    sel = up & band
    if sel.any():
        u = (norm(C[sel, L], L) * (res - 1)).astype(int)
        v = (norm(C[sel, W], W) * (res - 1)).astype(int)
        h = C[sel, H]
        img = np.full((res, res), -np.inf)
        np.maximum.at(img, (v, u), h)
        # for the raked screens the window slides along LENGTH per width-row:
        # the reference is the bonnet/roof level fore-aft of the screen
        bg = sliding_row_max(img, win)
        pix_bg = bg[v, u]
        face_inset = pix_bg - h
        glass_sel = face_inset > depth
        idx = np.where(sel)[0][glass_sel]
        glass[idx] = True
        print(f"top-rake  : band faces {sel.sum():6d} -> glass {glass_sel.sum():6d}")

    share = glass.mean() * 100
    print(f"TOTAL glass: {glass.sum()} faces = {share:.2f}% "
          f"(gate band 2.5-9.5%)")
    if mask_out:
        np.save(mask_out, glass)
    if preview:
        # paint the mask dark so a human can LOOK before anything trusts it
        col = np.full((len(F), 4), [200, 202, 205, 255], dtype=np.uint8)
        col[glass] = [20, 30, 40, 255]
        pm = trimesh.Trimesh(vertices=V, faces=F, process=False)
        pm.visual.face_colors = col
        pm.export(preview)
        print(f"preview -> {preview}")
    return glass, share


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    detect(sys.argv[1], sys.argv[2],
           sys.argv[3] if len(sys.argv) > 3 else None)
