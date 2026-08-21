#!/usr/bin/env python3
"""clipping.py — report the clipped fraction of every render.

Gate 4's first production tiles clipped 42.58% of car pixels (70.5% of the
body's red channel) and the AgX/white-tyre lesson says a clipped render is not
evidence. So every image this gate presents carries its own number.

"Car pixels" = anything that is not the flat studio backdrop.
"""
import sys, glob
import numpy as np
from PIL import Image
print(f"{'image':38s} {'carpx%':>7s} {'clip%ofcar':>11s} {'meanLum':>8s} {'p99Lum':>7s}")
for f in sorted(sum([glob.glob(a) for a in sys.argv[1:]], [])):
    a = np.asarray(Image.open(f).convert("RGB")).astype(np.float32)
    lum = a @ np.array([0.2126, 0.7152, 0.0722])
    bg = np.median(a.reshape(-1, 3), 0)
    car = np.linalg.norm(a - bg, axis=2) > 12
    if car.sum() == 0: car = np.ones(lum.shape, bool)
    clip = (a >= 254.5).any(2) & car
    print(f"{f.split('/')[-1]:38s} {100*car.mean():7.2f} {100*clip.sum()/car.sum():11.3f} "
          f"{lum[car].mean():8.2f} {np.percentile(lum[car],99):7.1f}")
