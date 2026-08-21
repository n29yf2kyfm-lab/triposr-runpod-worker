#!/usr/bin/env python3
"""Backfacing-pixel fraction per canonical view, from a faceorient render dir.

A face-orientation render localises inverted / see-through-to-the-inside
geometry that no count-based check can find (control C4 proves the counts are
blind to a winding reversal: 888,807 triangles before and after).  This turns
the sheet into a number so the same measurement can be repeated on the repaired
export and compared.

Usage: python3 faceorient_metric.py <dir> <out.json>
"""
import sys, os, json
import numpy as np
from PIL import Image
D, OUT = sys.argv[1], sys.argv[2]
rows = {}
tr = tb = 0
for f in sorted(os.listdir(D)):
    if not f.endswith('.png') or f.endswith('_mask.png'):
        continue
    im = np.asarray(Image.open(os.path.join(D, f)).convert('RGB')).astype(int)
    back = (im[:, :, 0] > 140) & (im[:, :, 2] < 110)
    front = (im[:, :, 2] > 140) & (im[:, :, 0] < 110)
    rows[f[:-4]] = {'backfacing_px': int(back.sum()), 'frontfacing_px': int(front.sum()),
                    'back_over_front': round(float(back.sum() / max(front.sum(), 1)), 5)}
    tr += int(back.sum()); tb += int(front.sum())
L = [v['back_over_front'] for k, v in rows.items() if 'LEFT' in k or k.endswith('_LEFT')]
R = [v['back_over_front'] for k, v in rows.items() if 'RIGHT' in k]
out = {'dir': D, 'views': rows,
       'total_back_over_front': round(tb and tr / tb or 0, 5),
       'mean_left_side_views': round(sum(L) / len(L), 5) if L else None,
       'mean_right_side_views': round(sum(R) / len(R), 5) if R else None,
       'left_right_asymmetry_ratio': (round((sum(R) / len(R)) / (sum(L) / len(L)), 4)
                                      if L and R and sum(L) else None),
       'NOTE': 'backfacing pixels mean the camera is seeing the reverse of a '
               'surface: either inverted winding, or the inside of the part '
               'through a gap.  Which of the two it is needs the cull-ON sheet.'}
json.dump(out, open(OUT, 'w'), indent=1)
print('total back/front=%s  left=%s  right=%s  R/L asymmetry=%s'
      % (out['total_back_over_front'], out['mean_left_side_views'],
         out['mean_right_side_views'], out['left_right_asymmetry_ratio']))
