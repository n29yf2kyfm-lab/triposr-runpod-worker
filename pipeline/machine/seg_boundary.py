#!/usr/bin/env python3
"""seg_boundary.py — straighten glass label boundaries with per-region 2D stencils.

The agent eye and the human eye both flagged the same #1 defect on the gseg
Golf: ragged, crinkled glass borders. The cause is that labels are per-FACE
and the Pixal triangulation does not follow the DLO, so the projected-vote
boundary dithers along the window edge. The fix is the pattern that already
beat boundary dither once (the 2026-08-13 glazing-tighten session): a 2D
STENCIL. Per connected glass region:

  1. fit a plane to the region's face centroids (SVD),
  2. rasterise the region into that plane at ~1/220 of its diagonal,
  3. morphological close -> fill holes -> gaussian smooth -> re-threshold,
     giving one clean smooth outline,
  4. re-stamp every candidate face (thin band around the plane, normal
     aligned, inside the expanded 2D bbox) from the raster.

Glass is then EXHAUSTIVE: any glass face outside every stamped region
reverts to body. That single rule also deletes the stray chrome smears
(tailgate band, cowl spill) — they are exactly "glass labels that belong to
no window plane".

Run: python3 seg_boundary.py <canon.glb> <labels.npy> <out_labels.npy>
"""
import sys
import numpy as np
import trimesh
import scipy.sparse as sp
from scipy import ndimage
from collections import Counter

GLB, INP, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
BODY, GLASS, WHEEL, LAMP, UNSEEN = 0, 1, 2, 3, 4

sc = trimesh.load(GLB, force="scene")
m = trimesh.util.concatenate([g for g in sc.geometry.values()])
cent = m.triangles_center
fnorm = m.face_normals
label = np.load(INP).copy()
F = len(label)
adj = m.face_adjacency

MIN_REGION = 800          # faces; smaller glass regions are noise -> body
BAND_FRAC = 0.030         # stencil band half-thickness, fraction of region diag
RASTER = 220              # cells across the region diagonal
GAUSS_SIGMA = 2.2         # cells; the smoothing that straightens the outline

# PLANARITY GUARD, lamp only in practice: a stencil is a PLANE fit, so it is
# only meaningful on a region that is roughly planar. Glass always is. A lamp
# wrapping a corner is not, and forcing a plane through it would let the
# stencil claim body faces on the far side of the wrap. A region above this
# RMS-out-of-plane fraction is left exactly as projected — worse boundary, but
# never a smear onto the wing. Fail open, never fail dirty.
MAX_NONPLANAR = 0.085


def stencil_class(cls, min_region, max_nonplanar=None, gauss=GAUSS_SIGMA,
                  band_frac=BAND_FRAC):
    """Straighten one class's boundary with per-region 2D stencils.

    Generalised from the glass-only version 2026-08-25. The Yaris PRESERVE
    slice shipped a clean glass boundary and a RAGGED LAMP one, because the
    lamp class only ever got the zone-eviction rules below and never this
    treatment — its edge was raw projected-vote dither, which renders as
    jagged dark patches spilling onto the wings and bonnet lip.

    Returns (stamped, stamp_region). Exhaustiveness is the caller's job.
    """
    mask = label == cls
    if not mask.any():
        return np.zeros(F, bool), np.full(F, -1, np.int32)
    same = mask[adj[:, 0]] & mask[adj[:, 1]]
    g = sp.csr_matrix((np.ones(int(same.sum())), (adj[same, 0], adj[same, 1])),
                      shape=(F, F))
    _, comp = sp.csgraph.connected_components(g + g.T, directed=False)
    comp = comp.copy(); comp[~mask] = -1
    sizes = Counter(comp[mask])
    regions = [cid for cid, n in sizes.items() if n >= min_region]
    print(f"{NAMES[cls]} regions >= {min_region} faces: {len(regions)} "
          f"(of {len(sizes)} total, {int(mask.sum())} {NAMES[cls]} faces)")

    stamped = np.zeros(F, bool)
    # which WINDOW stamped each glass face: glass_smooth fits per window, because
    # welded mesh connectivity merges the whole greenhouse into one blob (measured
    # on the gseg Golf: one 51k-face "region" spanning rear screen + both flanks)
    stamp_region = np.full(F, -1, np.int32)
    for ordinal, cid in enumerate(regions):
        ridx = np.where(comp == cid)[0]
        pts = cent[ridx]
        ctr = pts.mean(0)
        _, _, Vt = np.linalg.svd(pts - ctr, full_matrices=False)
        b1, b2, nrm = Vt[0], Vt[1], Vt[2]
        uv_r = (pts - ctr) @ np.stack([b1, b2], 1)
        diag = float(np.hypot(*(uv_r.max(0) - uv_r.min(0))))
        band = band_frac * diag

        if max_nonplanar is not None and diag > 0:
            rms = float(np.sqrt((((pts - ctr) @ nrm) ** 2).mean())) / diag
            if rms > max_nonplanar:
                stamped[ridx] = True      # keep as-is; do NOT revert to body
                stamp_region[ridx] = ordinal
                print(f"  region {cid}: {len(ridx)} faces, non-planar "
                      f"rms/diag {rms:.3f} > {max_nonplanar} — left as projected")
                continue

        d_all = (cent - ctr) @ nrm
        nd_all = np.abs(fnorm @ nrm)
        uv_all = (cent - ctr) @ np.stack([b1, b2], 1)
        lo, hi = uv_r.min(0) - 0.06 * diag, uv_r.max(0) + 0.06 * diag
        cand = ((np.abs(d_all) < band) & (nd_all > 0.5) &
                (uv_all[:, 0] > lo[0]) & (uv_all[:, 0] < hi[0]) &
                (uv_all[:, 1] > lo[1]) & (uv_all[:, 1] < hi[1]) &
                np.isin(label, (BODY, cls)))

        cell = diag / RASTER
        gw = int(np.ceil((hi[0] - lo[0]) / cell)) + 1
        gh = int(np.ceil((hi[1] - lo[1]) / cell)) + 1
        ras = np.zeros((gh, gw), bool)
        iu = ((uv_r[:, 0] - lo[0]) / cell).astype(int).clip(0, gw - 1)
        iv = ((uv_r[:, 1] - lo[1]) / cell).astype(int).clip(0, gh - 1)
        ras[iv, iu] = True
        ras = ndimage.binary_closing(ras, iterations=3)
        ras = ndimage.binary_fill_holes(ras)
        sm = ndimage.gaussian_filter(ras.astype(np.float32), gauss) > 0.5

        ci = np.where(cand)[0]
        cu = ((uv_all[ci, 0] - lo[0]) / cell).astype(int).clip(0, gw - 1)
        cv = ((uv_all[ci, 1] - lo[1]) / cell).astype(int).clip(0, gh - 1)
        inside = sm[cv, cu]
        label[ci[inside]] = cls
        stamped[ci[inside]] = True
        stamp_region[ci[inside]] = ordinal
        out_idx = ci[~inside]           # outside this stencil: revert cls -> body,
        flip = out_idx[(label[out_idx] == cls) & ~stamped[out_idx]]
        label[flip] = BODY              # unless another region already stamped it
        print(f"  region {cid}: {len(ridx)} faces, diag {diag:.3f}, "
              f"stamped {int(inside.sum())} in / {int((~inside).sum())} out")
    return stamped, stamp_region


NAMES = ["body", "glass", "wheel", "lamp", "interior"]
stamped_glass, stamp_region = stencil_class(GLASS, MIN_REGION)

# glass is exhaustive: anything still glass but never stamped is a smear
stray = (label == GLASS) & ~stamped_glass
label[stray] = BODY
print(f"stray glass reverted to body: {int(stray.sum())}")

# lamp hygiene, REAR ONLY: measured on the gseg Golf v2, 13,364 lamp faces
# spanned the tailgate as a full-width band (DINO's "tail light" boxes
# over-shoot) and the dark-gloss lens renders that band as mirror chrome.
# The nose is exempt: modern front ends run DRL bars across the grille and
# the inner halves of the headlamps sit near the centreline — evicting
# there re-creates the body-coloured-headlight defect this stage fights.
z = cent[:, 2]
half_w = max(abs(z.min()), abs(z.max()))
zc = np.abs(z) / half_w
x_ = cent[:, 0]
xf_ = (x_ - x_.min()) / (x_.max() - x_.min())
rear_half = xf_ < 0.5          # rear = low-x end on the canonical Pixal pose
lamp_mid = (label == LAMP) & (zc < 0.45) & rear_half
label[lamp_mid] = BODY
print(f"lamp centre-band (rear) evicted to body: {int(lamp_mid.sum())}")
# and lamps only live at the ends, above the bumper lip: smoothing/absorption
# can walk lamp label onto sills and valances after seg_project's zone prior
# has already run (measured on v9: pink sill patch + lower-lip band)
y_ = cent[:, 1]
yf_ = (y_ - y_.min()) / (y_.max() - y_.min())
lamp_out = (label == LAMP) & ~(((xf_ < 0.20) | (xf_ > 0.80)) & (yf_ > 0.15))
label[lamp_out] = BODY
print(f"lamp outside end-zones/height evicted to body: {int(lamp_out.sum())}")

# LAMP STENCIL — added 2026-08-25 after the Yaris PRESERVE slice.
# The evictions above are ZONE rules: they delete lamp label in the wrong
# PLACE, and do nothing about its SHAPE. The slice shipped a clean stencilled
# glass edge next to a raw projected-vote lamp edge, and at 5x the difference
# is obvious — jagged dark patches spilling onto the wings and the bonnet lip.
# Same treatment, same code, run after the zone rules so a bogus region (the
# tailgate full-width band DINO invents) is gone before any plane is fitted
# to it. Deliberately AFTER, not before: fitting a plane to that band and then
# evicting it would waste the fit and could stamp body faces along the way.
#
# Smaller MIN_REGION than glass: a headlamp is a fraction of a windscreen
# (measured on this car — 5,902 lamp faces across all four lamps, vs 42,811
# glass). Noise below the floor is never stamped and the exhaustiveness rule
# below sweeps it to body, so a low floor costs nothing.
LAMP_MIN_REGION = 250
stamped_lamp, _ = stencil_class(LAMP, LAMP_MIN_REGION,
                                max_nonplanar=MAX_NONPLANAR)
stray_lamp = (label == LAMP) & ~stamped_lamp
label[stray_lamp] = BODY
print(f"stray lamp reverted to body: {int(stray_lamp.sum())}")

# absorb crumbs the restamp left behind (single scan per label)
for target in range(5):
    tm = label == target
    if not tm.any():
        continue
    same = tm[adj[:, 0]] & tm[adj[:, 1]]
    g = sp.csr_matrix((np.ones(int(same.sum())), (adj[same, 0], adj[same, 1])),
                      shape=(F, F))
    _, comp2 = sp.csgraph.connected_components(g + g.T, directed=False)
    comp2 = comp2.copy(); comp2[~tm] = -1
    sizes2 = Counter(comp2[tm])
    small = {cid for cid, n in sizes2.items() if n < 400}
    if not small:
        continue
    bv = {cid: Counter() for cid in small}
    for a, b in adj:
        ca, cb = comp2[a], comp2[b]
        if ca in small and cb != ca:
            bv[ca][label[b]] += 1
        if cb in small and ca != cb:
            bv[cb][label[a]] += 1
    for cid, cnt in bv.items():
        if cnt:
            label[comp2 == cid] = cnt.most_common(1)[0][0]

stamp_region[label != GLASS] = -1
np.save(OUT, label)
np.save(OUT.replace(".npy", "_regions.npy"), stamp_region)
share = {NAMES[i]: round(100 * float((label == i).mean()), 2) for i in range(5)}
print("face share:", share)
