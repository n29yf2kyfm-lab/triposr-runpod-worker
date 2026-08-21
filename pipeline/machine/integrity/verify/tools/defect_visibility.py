#!/usr/bin/env python3
"""
Direct Stage 7 concealment test: is each DEFECT still visible in the neutral set?

The generic edge-energy ratio in conceal_diff cannot separate "hides a defect"
from "has less colour contrast".  The shipped scheme is saturated RED on a dark
interior; the brief's diagnostic palette is mid-grey on dark-grey, so a lower
edge ratio is guaranteed by the palette the brief itself specifies, and reading
that as concealment would be wrong.

So this measures the defect directly.  The dominant surface defect on this car
is dark PITTING across the panels.  A pit is a small region markedly darker than
its local surroundings, which is palette-independent: count pixels more than
`drop` sRGB8 below their local median, inside the eroded silhouette, and compare
the two material sets.  If the neutral set finds AT LEAST as many, it is not
hiding them.

Usage: python3 defect_visibility.py <neutralDir> <originalDir> <out.json>
"""
import sys, os, json
import numpy as np
from PIL import Image
from scipy import ndimage

A, B, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
DROP = 14.0


def g(p):
    return np.asarray(Image.open(p).convert('RGB')).astype(np.float64).mean(axis=2)


def sil(p):
    return np.asarray(Image.open(p).convert('RGBA'))[:, :, 3] > 128


def pits(im, m):
    med = ndimage.median_filter(im, size=11)
    d = med - im
    return int(((d > DROP) & m).sum())


rows = []
for n in sorted(f[:-4] for f in os.listdir(A)
                if f.endswith('.png') and not f.endswith('_mask.png')):
    pa, pb = os.path.join(A, n + '.png'), os.path.join(B, n + '.png')
    ma = os.path.join(A, n + '_mask.png')
    if not (os.path.exists(pb) and os.path.exists(ma)):
        continue
    m = ndimage.binary_erosion(sil(ma), np.ones((13, 13), bool))
    ia, ib = g(pa), g(pb)
    na, nb = pits(ia, m), pits(ib, m)
    rows.append({'view': n, 'pits_neutral': na, 'pits_original': nb,
                 'ratio_neutral_over_original': round(na / nb, 4) if nb else None,
                 'neutral_shows_at_least_as_many': bool(na >= nb * 0.9)})

ok = all(r['neutral_shows_at_least_as_many'] for r in rows)
rat = [r['ratio_neutral_over_original'] for r in rows if r['ratio_neutral_over_original']]
out = {'neutral_dir': A, 'original_dir': B, 'drop_threshold_srgb8': DROP,
       'views': rows, 'min_ratio': round(min(rat), 4) if rat else None,
       'mean_ratio': round(sum(rat) / len(rat), 4) if rat else None,
       'NEUTRAL_SHOWS_EVERY_DEFECT_REGION': ok,
       'NOTE': 'a ratio at or above 1.0 means the neutral diagnostic set reveals '
               'the pitting at least as strongly as the shipped red set.'}
json.dump(out, open(OUT, 'w'), indent=1)
print('min ratio=%s mean=%s  neutral reveals every defect region=%s'
      % (out['min_ratio'], out['mean_ratio'], ok))
for r in rows:
    print('  %-22s neutral=%-7d original=%-7d ratio=%s'
          % (r['view'], r['pits_neutral'], r['pits_original'],
             r['ratio_neutral_over_original']))
