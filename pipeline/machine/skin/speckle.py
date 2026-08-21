#!/usr/bin/env python3
"""speckle.py -- count dark specks on the paint, in a fixed region, from a
locked-camera render.  A pixel is a SPECK when it is much darker than the
median of its 9x9 neighbourhood AND the neighbourhood is paint-bright.  The
region is a rectangle in image space, identical for every render because the
camera spec is replayed, so before/after counts are comparable.
"""
import sys
import numpy as np
from PIL import Image
from scipy.ndimage import median_filter

REGIONS = {                       # y0,y1,x0,x1 in the 1300x936 full34 frame
    "bonnet":  (430, 540, 250, 620),
    "roof":    (235, 300, 560, 950),
    "flank":   (470, 660, 700, 960),
    "cowl":    (300, 430, 400, 700),
    "carbody": (200, 760, 130, 1060),
}
out = {}
for path in sys.argv[1:]:
    a = np.asarray(Image.open(path).convert("RGB")).astype(np.float32)
    lum = a @ np.array([0.2126, 0.7152, 0.0722])
    med = median_filter(lum, size=9)
    row = {}
    for k, (y0, y1, x0, x1) in REGIONS.items():
        L = lum[y0:y1, x0:x1]; M = med[y0:y1, x0:x1]
        paint = M > 45                       # exclude background/glass/tyre
        spec = paint & (L < M - 28)
        row[k] = (int(spec.sum()), int(paint.sum()),
                  100.0 * spec.sum() / max(paint.sum(), 1))
    out[path] = row
names = list(REGIONS)
print(f"{'render':28s} " + " ".join(f"{n:>16s}" for n in names))
for p, r in out.items():
    print(f"{p:28s} " + " ".join(f"{r[n][0]:7d} {r[n][2]:6.2f}%" for n in names))
