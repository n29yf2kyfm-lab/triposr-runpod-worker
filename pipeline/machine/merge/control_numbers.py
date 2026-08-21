#!/usr/bin/env python3
"""control_numbers.py — the respray control, measured per material.

THE CONTROL IS THE VERDICT, NOT A FORMALITY. CLAUDE.md records a car on which
every automated gate passed — glass_probe clear/proven, flat_shell false,
alpha_shell false, six named materials — and the RED control turned the windows
and the tyres red with the body. "All gates pass" was reported before the
control was run; do not repeat that.

METHOD. Three renders from the SAME camera: the shipped car, the car with only
`carpaint`'s base colour changed, and a flat-emission material-ID pass. The
matID pass supplies the pixel MASKS, so the identical pixels are read in both
beauty frames and no per-frame segmentation can drift between them. Per
material we then report the mean sRGB of its own pixels in each render.

WHAT THE NUMBERS MUST SAY
  carpaint          moves, and moves the whole way to the new hue
  Tyre_Rubber       does not move (owner ruling: tyres read as black rubber)
  glass             does not move
  Rim_Alloy         does not move (rim colour is its own check — a rim that
                    wears the body colour is the 2026-08-14 Clio defect)
  Lamp_Lens_Rear    does not move; it holds its red through a respray, which
                    is component behaviour that label-paint could never do
  Interior_Plastic, Trim_Black, Arch_Liner, Underbody, Brake_Disc: do not move

A material is judged MOVED if the mean sRGB distance between the two renders
exceeds `--thresh` (default 25, comfortably above the render noise floor at
these sample counts and far below a real hue swap, which lands in the 100s).

Run:
    python3 control_numbers.py MATID_DIR SHIPPED_DIR CONTROL_DIR [--out T.txt]
"""
import argparse
import json
import os

import numpy as np
from PIL import Image

STATIC = ("Tyre_Rubber", "glass", "Rim_Alloy", "Lamp_Lens", "Lamp_Lens_Rear",
          "Interior_Plastic", "Trim_Black", "Arch_Liner", "Underbody",
          "Brake_Disc")


def _srgb(x):
    """Blender's Standard view transform IS the sRGB OETF.

    An emission node's LINEAR value is not what lands in the PNG. Comparing the
    label colours as written (0.95 -> 242) matched nothing at all and every
    material silently reported zero pixels — a mask builder that finds nothing
    produces a control that "passes" without measuring anything, which is the
    metric-that-confidently-says-all-clear failure CLAUDE.md warns about. The
    verdict block therefore also refuses an empty measurement.
    """
    return 12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055


def masks(matid_png, colors, tol=6, erode=2):
    """Per-material pixel masks, ERODED before use.

    THE EDGE-BLEED TRAP, measured here rather than argued. The matID pass is
    rendered with anti-aliasing effectively off (filter_size 0.01) so each
    pixel carries exactly one label; the BEAUTY renders are filtered normally,
    so a pixel on the boundary of a thin region is a MIXTURE of that region and
    its neighbour. On this car the three materials that sit as thin strips
    inside large painted areas — Trim_Black (843 px in the side view),
    Arch_Liner, Interior_Plastic — appeared to "take the paint" purely from
    that mixing, while the large regions (Tyre_Rubber 24k px, Rim_Alloy 19k px,
    glass 33k px) did not. Eroding the mask removes the mixed ring and the
    false movement with it. Set erode=0 to see the unfiltered behaviour.
    """
    im = np.asarray(Image.open(matid_png).convert("RGB")).astype(np.int16)
    out = {}
    for name, c in colors.items():
        if name == "ground":
            continue
        t = np.array([round(_srgb(x) * 255) for x in c], dtype=np.int16)
        d = np.abs(im - t).max(axis=2)
        m = d <= tol
        if erode and m.sum():
            from scipy.ndimage import binary_erosion
            m = binary_erosion(m, iterations=erode)
        if m.sum():
            out[name] = m
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("matid")
    ap.add_argument("shipped")
    ap.add_argument("control")
    ap.add_argument("--thresh", type=float, default=25.0)
    ap.add_argument("--min-px", type=int, default=200)
    ap.add_argument("--erode", type=int, default=2)
    ap.add_argument("--out")
    a = ap.parse_args()

    colors = json.load(open(os.path.join(a.matid, "matid_colors.json")))
    views = sorted(f[:-4] for f in os.listdir(a.matid) if f.endswith(".png"))
    lines, verdict = [], {}
    lines.append("RESPRAY CONTROL - mean sRGB of each material's OWN pixels.")
    lines.append("Masks come from the material-ID pass of the SHIPPED file, so")
    lines.append("the identical pixels are read in both beauty renders.")
    lines.append(f"shipped: {a.shipped}\ncontrol: {a.control}")
    lines.append("")
    for v in views:
        mp = os.path.join(a.matid, v + ".png")
        sp = os.path.join(a.shipped, v + ".png")
        cp = os.path.join(a.control, v + ".png")
        if not (os.path.exists(sp) and os.path.exists(cp)):
            continue
        S = np.asarray(Image.open(sp).convert("RGB")).astype(float)
        C = np.asarray(Image.open(cp).convert("RGB")).astype(float)
        lines.append(f"view {v}.png")
        lines.append(f"  {'material':18s} {'shipped':18s} {'control':18s} "
                     f"{'dist':>7s} {'px':>8s}  moved")
        for name, m in sorted(masks(mp, colors, erode=a.erode).items()):
            if m.sum() < a.min_px:
                continue
            s = S[m].mean(axis=0)
            c = C[m].mean(axis=0)
            d = float(np.linalg.norm(s - c))
            moved = d > a.thresh
            verdict.setdefault(name, []).append(moved)
            lines.append(
                f"  {name:18s} [{s[0]:5.0f}{s[1]:5.0f}{s[2]:5.0f}]   "
                f"[{c[0]:5.0f}{c[1]:5.0f}{c[2]:5.0f}]   {d:7.1f} "
                f"{int(m.sum()):8d}  {'YES' if moved else 'no'}")
        lines.append("")
    lines.append("VERDICT")
    ok = bool(verdict)
    if not verdict:
        lines.append("  NO MATERIAL MASK MATCHED ANY PIXELS - the control "
                     "measured nothing and is NOT a pass.")
    for name, rows in sorted(verdict.items()):
        want_move = name == "carpaint"
        got = any(rows)
        good = (got == want_move)
        ok &= good
        lines.append(f"  {name:18s} moved={got!s:5s} expected={want_move!s:5s} "
                     f"{'PASS' if good else 'FAIL'}")
    lines.append("")
    lines.append(f"CONTROL_OK: {ok}")
    txt = "\n".join(lines)
    print(txt)
    if a.out:
        open(a.out, "w").write(txt + "\n")


if __name__ == "__main__":
    main()
