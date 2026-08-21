#!/usr/bin/env python3
"""measure_vis.py — VISIBLE-INTERIOR FRACTION, measured from two label passes.

Definition (stated so it can be argued with):
  car pixels   = every pixel that is not background in the ALL pass
  a pixel READS CABIN if
      (a) its ALL-pass label is a cabin-class node (directly visible), or
      (b) its ALL-pass label is a GLAZING node and its hide-glass-pass label
          at the same pixel is a cabin-class node (visible THROUGH glass).
  VIF = |reads cabin| / |car pixels|

Caveat stated up front: hiding the glazing is not identical to the glazing being
transparent. It is a fair proxy here because the glazing measures BLEND alpha
0.161 with KHR_materials_transmission 0.92 — it is genuinely see-through — but
the number is "what the aperture shows", not "what a ray-traced beauty pixel
integrates to".

Run: python3 measure_vis.py <dir> <prefix_all> <prefix_hideglass> <labels.json> [out.json]
"""
import json
import os
import sys
import numpy as np
from PIL import Image

D, TA, TH = sys.argv[1], sys.argv[2], sys.argv[3]   # TA/TH are FILE PREFIXES
LBL = sys.argv[4]
OUT = sys.argv[5] if len(sys.argv) > 5 else None

GLAZE = {"Glass_Rear", "Glass_Windscreen", "Glass_Side_L", "Glass_Side_R"}


def is_cabin(n):
    return n == "Interior" or n.startswith("Cabin_")


def srgb8(lin255):
    c = np.asarray(lin255, dtype=float) / 255.0
    s = np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)
    return np.clip(np.rint(s * 255.0), 0, 255).astype(np.int64)


# The rig paints only six linear levels per channel; Blender's 8-bit write can
# still land +-1 off the arithmetic prediction. Snap each channel to the nearest
# EXPECTED level rather than trusting the arithmetic, and refuse if any car
# pixel had to move more than SNAP_TOL to get there.
LEVELS_LIN = np.array([40 + i * 43 for i in range(6)])
LEVELS_SRGB = srgb8(LEVELS_LIN)
SNAP_TOL = 3


def snap(a):
    d = np.abs(a[..., None] - LEVELS_SRGB[None, None, None, :])
    idx = d.argmin(-1)
    return LEVELS_SRGB[idx], d.min(-1)


labels = json.load(open(LBL))
# expected 8-bit sRGB code per node, packed
code = {}
for n, c in labels.items():
    r, g, b = srgb8(c)
    code[int(r) << 16 | int(g) << 8 | int(b)] = n


def classify(path):
    a = np.asarray(Image.open(path).convert("RGB")).astype(np.int64)
    raw = a[:, :, 0] << 16 | a[:, :, 1] << 8 | a[:, :, 2]
    sn, dev = snap(a)
    packed = sn[:, :, 0] << 16 | sn[:, :, 1] << 8 | sn[:, :, 2]
    # anything that was essentially black stays background, never snapped up
    packed[raw <= 0x030303] = 0
    return packed, dev.max(-1)


views = sorted(f[len(TA):-4] for f in os.listdir(D)
               if f.startswith(TA) and f.endswith(".png"))
report = {"views": {}, "definition": "see docstring"}
tot_car = tot_cab = 0
for v in views:
    pa, deva = classify(os.path.join(D, TA + v + ".png"))
    ph, devh = classify(os.path.join(D, TH + v + ".png"))
    # exact-code coverage check: a pixel that matches no known code is either
    # background (0) or an anti-aliasing straggler. Assert it is negligible.
    known = np.zeros_like(pa, dtype=bool)
    for k in code:
        known |= (pa == k)
    bg = pa == 0
    stray = (~known) & (~bg)
    assert deva[known].max() <= SNAP_TOL, (v, "label snap exceeded tolerance",
                                          int(deva[known].max()))
    car = known
    ncar = int(car.sum())
    reads_cabin = np.zeros_like(car)
    for k, n in code.items():
        if is_cabin(n):
            reads_cabin |= (pa == k)
    glazed = np.zeros_like(car)
    per_pane = {}
    for k, n in code.items():
        if n in GLAZE:
            m = (pa == k)
            glazed |= m
            if m.sum():
                per_pane[n] = m
    # what shows through each pane
    pane_rep = {}
    for n, m in per_pane.items():
        beh = ph[m]
        cnt = {}
        for k2, n2 in code.items():
            c2 = int((beh == k2).sum())
            if c2:
                cnt[n2] = c2
        cnt["<background>"] = int((beh == 0).sum())
        tot = int(m.sum())
        cab = sum(c for nn, c in cnt.items()
                  if nn != "<background>" and is_cabin(nn))
        pane_rep[n] = {"px": tot, "cabin_px": cab,
                       "cabin_frac": round(cab / tot, 4),
                       "top": dict(sorted(cnt.items(), key=lambda x: -x[1])[:5])}
        mm = m.copy()
        for k2, n2 in code.items():
            if is_cabin(n2):
                reads_cabin |= mm & (ph == k2)
    ncab = int(reads_cabin.sum())
    tot_car += ncar
    tot_cab += ncab
    report["views"][v] = {
        "car_px": ncar, "stray_px": int(stray.sum()),
        "glazed_px": int(glazed.sum()),
        "glazed_frac_of_car": round(float(glazed.sum()) / ncar, 4),
        "cabin_px": ncab, "visible_interior_fraction": round(ncab / ncar, 4),
        "panes": pane_rep,
    }
    print(f"{v}: car={ncar} stray={int(stray.sum())} glazed={int(glazed.sum())} "
          f"({100*glazed.sum()/ncar:.2f}%)  VIF={100*ncab/ncar:.2f}%")
    for n, r in sorted(pane_rep.items()):
        print(f"     {n:18s} {r['px']:6d}px  cabin {100*r['cabin_frac']:5.1f}%  "
              f"top={list(r['top'].items())[:3]}")

report["overall"] = {"car_px": tot_car, "cabin_px": tot_cab,
                     "visible_interior_fraction": round(tot_cab / tot_car, 4)}
print(f"\nOVERALL across {len(views)} views: "
      f"VIF = {100*tot_cab/tot_car:.2f}%  ({tot_cab}/{tot_car} px)")
if OUT:
    json.dump(report, open(OUT, "w"), indent=1)
    print("wrote", OUT)
