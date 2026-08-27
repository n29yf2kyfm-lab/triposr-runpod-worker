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
import os
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

# REGION FLOORS SCALE WITH THE MESH. The original constants (800 glass / 250
# lamp) were calibrated on the 918,715-face Pixal Golf; run unscaled against a
# 40,000-face Hunyuan mesh they exceeded every real window (a windscreen there
# is ~300 faces) and seg_boundary silently reverted ALL 1,166 glass faces to
# body — a no-glazing car, an auto-scrap, behind nine green exit codes
# (2026-08-27, RF67 Golf). Same defect class as the recorded absolute-distance
# thresholds that were wrong for a quarter of the catalogue: an absolute face
# count is wrong for any mesh whose face budget differs from the calibration
# car's. The floors are now FRACTIONS of total faces, anchored so the Pixal
# calibration values are reproduced exactly at 918,715 faces.
MIN_REGION = max(30, int(F * 800 / 918715))   # glass; noise -> body
BAND_FRAC = 0.030         # stencil band half-thickness, fraction of region diag
RASTER = 220              # cells across the region diagonal
GAUSS_SIGMA = 2.2         # cells; the smoothing that straightens the outline

# PLANARITY GUARD, lamp only in practice: a stencil is a PLANE fit, so it is
# only meaningful on a region that is roughly planar. Glass always is. A lamp
# wrapping a corner is not, and forcing a plane through it would let the
# stencil claim body faces on the far side of the wrap.
#
# WHAT A GUARD-FAIL FALLS BACK TO — corrected 2026-08-26 after review. The first
# version left a non-planar region EXACTLY AS PROJECTED, and that is the one
# outcome the evidence had already rejected: raw-projected lamp was the WORST of
# the three renders that decided seg_assemble's lamp rule ("ragged dark band
# across the nose"). The guard was quietly reinstating the rejected artefact
# through a back door. It now runs a MAJORITY FILTER over face adjacency
# instead, which removes raggedness with no plane assumption at all — the right
# tool for a multi-plane lamp assembly (lens + housing + bezel), where a single
# global plane fit was never going to be meaningful.
#
# Note this is invisible on the DEFAULT path, because seg_assemble now keeps the
# lamp textured and both sides of a ragged lamp boundary carry the same pixels.
# It matters under LAMP_FLAT=1, where the boundary becomes a material edge.
MAX_NONPLANAR = 0.085
MAJORITY_ROUNDS = 3


def majority_smooth(idx, rounds=MAJORITY_ROUNDS):
    """Plane-free boundary cleanup: each face takes the majority label of its
    edge neighbours. Removes single-face teeth and hairline spurs without
    assuming the region is flat. Operates on the global `label` array."""
    sel = np.zeros(F, bool)
    sel[idx] = True
    for _ in range(rounds):
        a, b = adj[:, 0], adj[:, 1]
        agree = np.zeros(F, np.int32)
        total = np.zeros(F, np.int32)
        same = label[a] == label[b]
        np.add.at(agree, a[same], 1)
        np.add.at(agree, b[same], 1)
        np.add.at(total, a, 1)
        np.add.at(total, b, 1)
        # A face whose neighbours mostly disagree with it is a tooth.
        # total >= 2, not >= 3: a tooth sitting on a mesh boundary or corner has
        # only two edge neighbours and was silently skipped by the stricter gate
        # — 1 of 6 planted teeth survived the synthetic test. The strict
        # majority test (agree*2 < total) still protects a real 2-neighbour
        # face, because it only flips when BOTH neighbours disagree.
        lonely = sel & (total >= 2) & (agree * 2 < total)
        if not lonely.any():
            break
        for f_ in np.where(lonely)[0]:
            nb = np.concatenate([adj[adj[:, 0] == f_][:, 1], adj[adj[:, 1] == f_][:, 0]])
            if len(nb):
                label[f_] = Counter(label[nb]).most_common(1)[0][0]
    return int(sel.sum())


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
                majority_smooth(ridx)     # plane-free cleanup, NOT raw-projected
                print(f"  region {cid}: {len(ridx)} faces, non-planar "
                      f"rms/diag {rms:.3f} > {max_nonplanar} — majority-smoothed")
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
# GLASS_STENCIL=0 SKIPS THE GLASS STENCIL, KEEPING LAMP/WHEEL HYGIENE.
# The stencil exists to straighten a boundary that DITHERS because labels come
# from per-face projected votes. Labels from glass_relabel.py do not have that
# defect — they are a crease-bounded flood fill, so their boundary is already a
# geometric edge. Worse, running it destroys them: seg_boundary recomputes
# components from the LABEL ALONE, so windscreen + both flanks + backlight merge
# into one region (measured on the RF67 Golf: region 91, 1113 faces, diag 3.692m
# — longer than the car is tall), and a single plane fitted through that
# mega-region throws the windscreen out (stamped 5 in / 262 out). That is the
# recorded mega-region failure, and per-window splitting is the standing fix.
if os.environ.get("GLASS_STENCIL", "1") == "0":
    print("glass stencil SKIPPED (GLASS_STENCIL=0): labels assumed crease-bounded")
    stamped_glass = label == GLASS
    stamp_region = np.where(label == GLASS, 0, -1).astype(np.int32)
else:
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
LAMP_MIN_REGION = max(10, int(F * 250 / 918715))   # scaled; see MIN_REGION
stamped_lamp, _ = stencil_class(LAMP, LAMP_MIN_REGION,
                                max_nonplanar=MAX_NONPLANAR)
stray_lamp = (label == LAMP) & ~stamped_lamp
label[stray_lamp] = BODY
print(f"stray lamp reverted to body: {int(stray_lamp.sum())}")

# WHEEL HYGIENE — added 2026-08-25 from the Yaris matID render.
# A dark ragged band sat along the bonnet lip in every front view. The label
# map named the culprit: WHEEL label on the NOSE. seg_assemble splits wheel
# into tyre/rim by radius, so a stray wheel face on the bonnet lip becomes
# Tyre_Rubber and renders as a black smear on white paint. DINO's "wheel"/
# "tire" prompts match the grille's slat pattern and the round badge; nothing
# downstream questioned it, because WHEEL had no zone rule while LAMP did.
#
# Distance-from-hub, not a height cut. A height rule looks tempting (99% of
# real wheel faces sit below yf 0.473) but the honest measurement kills it:
# evicting above yf 0.45 also clips 2.6% off the TOPS OF THE REAL TYRES.
# Locating the four hubs from unambiguous low faces and evicting whatever sits
# far from all of them removes the spill without touching a tyre crown.
# Measured here: 638 of 14,801 wheel faces evicted (4.3%), 625 of them in the
# nose region (xf > 0.9) — i.e. the smear, and almost nothing else.
# REQUIRES ALL FOUR HUBS, and says so when it declines. Review 2026-08-26
# killed the original `>= 2` guard: two hubs on a DIAGONAL (front-left +
# rear-right, which is what a partial seg gives you) put every face at the other
# two corners far from both centres, so the rule would evict two whole wheels to
# body — a mass failure indistinguishable from the nose smear it exists to fix.
# Four is the only count that is safe without pairing logic, and a car this
# stage cannot resolve is better left alone than half-stripped.
#
# KNOWN LIMIT, recorded not fixed: `seed` is drawn from the same label set the
# rule is cleaning, and the false wheel labels it targets (grille slats, badge)
# sit LOW on the nose, so they pass yf < 0.35 and can bias a quadrant median and
# inflate R. R is self-relative, so contamination erodes its own margin rather
# than blowing up — but on a car with heavy nose contamination this rule will
# under-evict. A contamination-free seed needs a wheel prior the seg does not
# currently produce.
#
# Also NOT handled: a tailgate-mounted spare (far from all four hubs -> evicted
# to body paint), an underfloor spare (enters seed, drags a median), and a
# 6-wheeler's middle axle (no centre near it -> evicted). All three are out of
# scope for a passenger-car catalogue and all three would be visible on the
# sheet; none is silent, because the eviction count prints.
widx = np.where(label == WHEEL)[0]
if len(widx) <= 800:
    print(f"wheel hygiene SKIPPED: only {len(widx)} wheel faces (<= 800)")
else:
    yf_all = (cent[:, 1] - cent[:, 1].min()) / np.ptp(cent[:, 1])
    seed = widx[yf_all[widx] < 0.35]          # unambiguously wheel; locates hubs only
    if len(seed) <= 800:
        print(f"wheel hygiene SKIPPED: only {len(seed)} low seed faces (<= 800)")
    else:
        sc_ = cent[seed]
        xm = np.median(sc_[:, 0])
        zm = (sc_[:, 2].min() + sc_[:, 2].max()) / 2
        centres = []
        for fx in (sc_[:, 0] < xm, sc_[:, 0] >= xm):
            for fz in (sc_[:, 2] < zm, sc_[:, 2] >= zm):
                s = sc_[fx & fz]
                if len(s) > 200:
                    centres.append(np.median(s, axis=0))
        if len(centres) != 4:
            print(f"wheel hygiene SKIPPED: found {len(centres)} hubs, need 4 "
                  f"(a diagonal pair would evict two whole wheels)")
        else:
            centres = np.array(centres)
            d_seed = np.linalg.norm(sc_[:, None, :] - centres[None], axis=2).min(1)
            R = 1.25 * float(np.percentile(d_seed, 95))
            d = np.linalg.norm(cent[widx][:, None, :] - centres[None], axis=2).min(1)
            far = widx[d > R]
            # A rule that evicts most of the wheels is broken, not thorough.
            if len(far) > 0.25 * len(widx):
                print(f"wheel hygiene REFUSED: would evict {len(far)} of "
                      f"{len(widx)} ({100*len(far)/len(widx):.0f}%) — hubs look wrong")
            else:
                label[far] = BODY
                print(f"wheel hubs 4, R={R:.3f}; "
                      f"stray wheel evicted to body: {len(far)} "
                      f"({100*len(far)/len(widx):.1f}%)")

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
