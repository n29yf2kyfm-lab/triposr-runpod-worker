#!/usr/bin/env python3
"""speck2.py -- dark specks ON THE PAINT, pose-independent.

The paint mask is derived from the image itself (locally red-dominant and
bright), so it follows the car rather than a fixed rectangle -- the grounded
car sits 185 mm lower at the nose than the ungrounded one and a fixed crop
would silently measure different parts of the body in the two.
A SPECK is a pixel at least DROP sRGB below the median of its 9x9
neighbourhood, inside that mask.  Same rule, same numbers, both images.
"""
import sys
import numpy as np
from PIL import Image
from scipy.ndimage import median_filter
DROP = 28
for p in sys.argv[1:]:
    a = np.asarray(Image.open(p).convert("RGB")).astype(np.float32)
    lum = a @ np.array([0.2126, 0.7152, 0.0722])
    med = median_filter(lum, size=9)
    mr = median_filter(a[..., 0], size=9); mg = median_filter(a[..., 1], size=9)
    paint = (med > 55) & (mr > mg * 1.6)
    spec = paint & (lum < med - DROP)
    print(f"{p:28s} paint px {int(paint.sum()):7d}   specks {int(spec.sum()):7d}   "
          f"{100*spec.sum()/max(paint.sum(),1):6.3f}%")
