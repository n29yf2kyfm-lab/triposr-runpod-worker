#!/usr/bin/env python3
"""respray_measure.py — does the respray move the PAINT and leave the LAMPS?

The masks come from the matID render, not from my eye: matID is flat emission,
1 sample, AA off, so each component owns an exact colour and the pixel sets are
per-COMPONENT rather than per-region. The same pixels are then sampled in the
body-red and body-blue shaded renders, which share a camera and an exposure.

This is the control label-paint can never pass: if the tail lamps were texels
on the body material they would turn blue with it.

Run: python3 respray_measure.py <matid.png> <red.png> <blue.png> <out.json>
"""
import json, sys
import numpy as np
from PIL import Image
# THE PALETTE IS LINEAR; THE RENDER IS sRGB-ENCODED. The matID pass uses flat
# emission under Blender's Standard view transform, which applies the sRGB EOTF
# on the way out -- so a linear 0.85 lands at 237, not 217. Matching the raw
# linear values found 0 pixels for four of six components, which reads exactly
# like "the component is not in the render" and is nothing of the sort.
def srgb(c):
    return tuple(int(round(255 * (12.92 * v if v <= 0.0031308
                                  else 1.055 * v ** (1 / 2.4) - 0.055))) for v in c)


PAL = {"Tail_Lens_L (magenta)": srgb((1.0, 0.0, 0.85)),
       "Tail_Lens_R (orange)": srgb((1.0, 0.45, 0.0)),
       "Hatch (cyan)": srgb((0.0, 0.85, 1.0)),
       "Bumper_Rear (yellow)": srgb((1.0, 0.92, 0.0)),
       "Glass_Backlight (dk blue)": srgb((0.03, 0.05, 0.45)),
       "Plate_Rear (white)": (255, 255, 255),
       "Rear_Upper_Legacy_Melt": srgb((0.62, 0.36, 0.36))}
mid = np.asarray(Image.open(sys.argv[1]).convert("RGB")).astype(np.int16)
red = np.asarray(Image.open(sys.argv[2]).convert("RGB")).astype(np.float32)
blu = np.asarray(Image.open(sys.argv[3]).convert("RGB")).astype(np.float32)
rep = {}
print(f"{'component':28s} {'px':>7s} {'RED mean RGB':>22s} {'BLUE mean RGB':>22s} {'maxdelta':>9s}")
for name, c in PAL.items():
    m = (np.abs(mid - np.array(c)) <= 10).all(2)
    if m.sum() < 200:
        print(f"{name:28s} {int(m.sum()):7d}  (too few pixels to measure)"); continue
    r, b = red[m].mean(0), blu[m].mean(0)
    d = float(np.abs(r - b).max())
    rep[name] = {"px": int(m.sum()), "red_rgb": [round(float(v), 1) for v in r],
                 "blue_rgb": [round(float(v), 1) for v in b], "max_channel_delta": round(d, 1),
                 "red_minus_blue_R_B": [round(float(r[0] - r[2]), 1), round(float(b[0] - b[2]), 1)]}
    print(f"{name:28s} {int(m.sum()):7d} {str([round(float(v),1) for v in r]):>22s} "
          f"{str([round(float(v),1) for v in b]):>22s} {d:9.1f}")
json.dump(rep, open(sys.argv[4], "w"), indent=1)
