#!/usr/bin/env python3
"""
STAGE 7 HONESTY TEST: prove the neutral diagnostic material set REVEALS at
least as much as the shipped set, and hides nothing.

The brief's rule is blunt: "never use materials, backface-culling settings or
camera angles to CONCEAL missing geometry".  A diagnostic set that quietly made
glazing opaque, or darkened a void until it read as shadow, would flatter the
model exactly where it is weakest.  So the same eight cameras are rendered twice
-- shipped materials and neutral diagnostics -- and three numbers are compared
per view:

  1. SILHOUETTE IoU.  Materials cannot move geometry, so this must be ~1.000.
     Anything below flags a shader that is dropping surfaces (e.g. a
     transmissive material sampled as fully transparent in the mask pass).
  2. EDGE ENERGY inside the silhouette.  This is the concealment test proper:
     if the neutral set resolves materially FEWER internal edges than the
     shipped set, it is smoothing detail away.  Reported as a ratio.
  3. LOCAL WORST CASE.  A whole-frame mean can hide a locally concealed region,
     so the frame is tiled 16x12 and the worst tile ratio is reported too.

Usage: python3 conceal_diff.py <dirA_neutral> <dirB_original> <out.json>
"""
import sys, os, json
import numpy as np
from PIL import Image
from scipy import ndimage

A, B, OUT = sys.argv[1], sys.argv[2], sys.argv[3]


def load(p):
    return np.asarray(Image.open(p).convert('RGB')).astype(np.float64)


def gray(a):
    return a.mean(axis=2)


def edges(g):
    gy = np.abs(np.diff(g, axis=0))[:, :-1]
    gx = np.abs(np.diff(g, axis=1))[:-1, :]
    return np.sqrt(gx * gx + gy * gy)


def mask(p):
    im = Image.open(p)
    a = np.asarray(im.convert('RGBA')).astype(np.float64)
    return a[:, :, 3] > 128


rows = []
names = sorted(f[:-4] for f in os.listdir(A)
               if f.endswith('.png') and not f.endswith('_mask.png'))
for n in names:
    pa, pb = os.path.join(A, n + '.png'), os.path.join(B, n + '.png')
    if not os.path.exists(pb):
        continue
    ma_p, mb_p = os.path.join(A, n + '_mask.png'), os.path.join(B, n + '_mask.png')
    iou = None
    if os.path.exists(ma_p) and os.path.exists(mb_p):
        ma, mb = mask(ma_p), mask(mb_p)
        inter = np.logical_and(ma, mb).sum()
        uni = np.logical_or(ma, mb).sum()
        iou = float(inter / uni) if uni else None
        sil = ma
    else:
        sil = None
    ga, gb = gray(load(pa)), gray(load(pb))
    ea, eb = edges(ga), edges(gb)
    # ERODE the silhouette before measuring.  The first version measured the
    # whole silhouette including its outline against the background, and on a
    # car whose shipped paint is saturated RED that outline dominates: the
    # neutral grey body against a grey backdrop has almost no boundary contrast,
    # so the metric scored 0.07 and read as concealment when the silhouette IoU
    # was an exact 1.000 and nothing was hidden at all.  Eroding by 6 px removes
    # the body-vs-background edge from both images and leaves only INTERNAL
    # detail, which is what "does the neutral set hide anything" actually asks.
    if sil is not None:
        s = ndimage.binary_erosion(sil, np.ones((13, 13), bool))[:-1, :-1]
    else:
        s = np.ones_like(ea, dtype=bool)
    mean_a = float(ea[s].mean())
    mean_b = float(eb[s].mean())
    # worst local tile
    H, W = ea.shape
    th, tw = H // 12, W // 16
    worst = None
    worst_at = None
    for i in range(12):
        for j in range(16):
            sl = (slice(i * th, (i + 1) * th), slice(j * tw, (j + 1) * tw))
            m = s[sl]
            if m.sum() < 200:
                continue
            va, vb = ea[sl][m].mean(), eb[sl][m].mean()
            if vb < 1.0:
                continue
            r = va / vb
            if worst is None or r < worst:
                worst = float(r)
                worst_at = [i, j]
    rows.append({
        'view': n,
        'silhouette_IoU_neutral_vs_original': (round(iou, 6) if iou is not None else None),
        'edge_energy_neutral': round(mean_a, 4),
        'edge_energy_original': round(mean_b, 4),
        'edge_ratio_neutral_over_original': round(mean_a / mean_b, 4) if mean_b else None,
        'worst_local_tile_ratio': (round(worst, 4) if worst is not None else None),
        'worst_tile_rowcol': worst_at,
        'mean_srgb8_neutral': round(float(ga[:-1, :-1][s].mean()), 2),
        'mean_srgb8_original': round(float(gb[:-1, :-1][s].mean()), 2),
    })

ious = [r['silhouette_IoU_neutral_vs_original'] for r in rows
        if r['silhouette_IoU_neutral_vs_original'] is not None]
ratios = [r['edge_ratio_neutral_over_original'] for r in rows
          if r['edge_ratio_neutral_over_original'] is not None]
worsts = [r['worst_local_tile_ratio'] for r in rows
          if r['worst_local_tile_ratio'] is not None]
out = {
    'A_neutral_dir': A, 'B_original_dir': B, 'views': len(rows),
    'min_silhouette_IoU': (round(min(ious), 6) if ious else None),
    'GEOMETRY_UNCHANGED_BY_MATERIALS': bool(ious and min(ious) > 0.999),
    'min_edge_ratio_whole_frame': (round(min(ratios), 4) if ratios else None),
    'min_worst_local_tile_ratio': (round(min(worsts), 4) if worsts else None),
    'NEUTRAL_SET_CONCEALS_NOTHING': bool(
        ratios and min(ratios) >= 0.80 and worsts and min(worsts) >= 0.50),
    'threshold_note': 'whole-frame edge ratio >= 0.80 and worst local tile >= 0.50. '
                      'A ratio ABOVE 1.0 means the neutral set reveals MORE, '
                      'which is the intended direction.',
    'rows': rows,
}
json.dump(out, open(OUT, 'w'), indent=1)
print('views=%d  minIoU=%s  geometry_unchanged=%s' %
      (len(rows), out['min_silhouette_IoU'], out['GEOMETRY_UNCHANGED_BY_MATERIALS']))
print('min whole-frame edge ratio=%s  min worst-tile ratio=%s  conceals_nothing=%s'
      % (out['min_edge_ratio_whole_frame'], out['min_worst_local_tile_ratio'],
         out['NEUTRAL_SET_CONCEALS_NOTHING']))
for r in rows:
    print('  %-22s IoU=%-9s edges %8.3f / %8.3f = %-7s worst tile %-7s'
          % (r['view'], r['silhouette_IoU_neutral_vs_original'],
             r['edge_energy_neutral'], r['edge_energy_original'],
             r['edge_ratio_neutral_over_original'], r['worst_local_tile_ratio']))
