#!/usr/bin/env python3
"""photos_to_glb.py — drop a folder of photos + dims.json, get a structured GLB.

The owner's target workflow (2026-08-14, verbatim intent): "you drop, say,
eight photos into a folder and it outputs" a proper car GLB with the named part
tree. Quality ladder: one photo -> AI guesses the unseen side; multiple photos
-> multi-view; multi-view + KNOWN DIMENSIONS + automated cleanup -> the level
this pipeline targets.

FOLDER CONTRACT
    dims.json     REQUIRED. The manufacturer's published figures, in mm:
                      {"name": "2012_Toyota_Yaris", "style": "hatch",
                       "length": 3885, "width": 1695, "height": 1510,
                       "wheelbase": 2510, "track": 1470,
                       "wheel_d": 608, "tyre_w": 175}
                  Dimensions are never estimated from pixels — the accuracy
                  rule in CLAUDE.md forbids invented specs, and pixels cannot
                  give absolute scale anyway. Photos refine SHAPE; dims pin
                  SIZE.
    side*.png     strongly recommended: a true side profile, background
                  removed (RGBA) or near-white. Drives the roofline fit.
    front*.png / rear*.png / *34*.png   currently recorded for the report and
                  reserved for the section-shape fit (next stage).

WHAT THE SIDE VIEW FITS — measured landmarks, not a freeform copy:
    * bonnet height  (top profile at the front-axle x, as a fraction of H)
    * cowl position  (where the top profile pulls away from the bonnet line)
    * front/rear roof extents (where the profile reaches ~97% of max height)
    * beltline       (not yet — needs window detection; belt stays styled)
The fitted values override the style defaults in STYLES; everything else
(sections, seams, parts, materials) comes from structured_car. If no side view
is present the style defaults are used and the report says so.

Usage:
    python3 pipeline/authoring/photos_to_glb.py <folder> [--out car.glb]
Outputs into the folder: <name>.glb, fit_report.json.
"""
import argparse
import glob
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parametric_car import Car, STYLES                        # noqa: E402
from structured_car import build_structured                   # noqa: E402


def load_mask(path):
    """Silhouette mask from an RGBA cutout, or near-white-background photo."""
    im = Image.open(path)
    if im.mode == "RGBA":
        a = np.asarray(im)[:, :, 3]
        return a > 128
    g = np.asarray(im.convert("L"))
    # near-white background: the car is whatever is NOT white. Refuse if the
    # frame edge is not actually white — that means a busy background, and a
    # bad mask would silently corrupt the fit.
    edge = np.concatenate([g[0], g[-1], g[:, 0], g[:, -1]])
    if edge.mean() < 200:
        raise ValueError(f"{os.path.basename(path)}: background is not "
                         "white/removed — supply an RGBA cutout")
    return g < 235


def side_profile(mask):
    """Top/bottom y per x column, trimmed to the car's x extent."""
    cols = mask.any(axis=0)
    xs = np.where(cols)[0]
    x0, x1 = xs.min(), xs.max()
    top, bot = [], []
    H = mask.shape[0]
    for x in range(x0, x1 + 1):
        ys = np.where(mask[:, x])[0]
        top.append(ys.min())
        bot.append(ys.max())
    top = np.array(top, dtype=float)
    bot = np.array(bot, dtype=float)
    return x0, x1, top, bot, H


def fit_side(mask, facing="auto"):
    """Landmark fit. Returns dict of overrides for STYLES, all in [0,1] u/frac.

    Facing: the fit needs to know which image side is the NOSE. 'auto' decides
    by where the profile's tallest run (the roof) sits — the roof of every car
    is rear-of-centre, so the nose is on the side farther from the roof run.
    """
    x0, x1, top, bot, imgH = side_profile(mask)
    n = len(top)
    ymin = top.min()                      # roof (image y grows downward)
    ymax = bot.max()                      # ground contact
    H = ymax - ymin
    height = ymax - top                   # car height profile per column

    # ROBUST roof height: the 92nd percentile of the profile, not the absolute
    # maximum. Measured failure on a real SUV mesh: roof RAILS raised max() by a
    # few percent, the ">=97% of max" band collapsed to the rail span, and
    # roof_f slid 0.13 rearward — the built car grew a windscreen half the
    # bonnet long. Rails, aerials and mirrors are thin protrusions; a
    # percentile ignores them, the true roof is a wide flat run.
    roof_h = np.percentile(height, 92)
    hi = height >= 0.985 * roof_h
    roof_cols = np.where(hi)[0]
    roof_mid = roof_cols.mean() / n
    if facing == "auto":
        facing = "right" if roof_mid < 0.5 else "left"
    # normalise so u runs tail->nose = 0->1 like the builder
    prof = height / H
    if facing == "left":
        prof = prof[::-1]
        roof_cols = n - 1 - roof_cols[::-1]

    u = np.arange(n) / (n - 1)
    roof_f_u = roof_cols.max() / (n - 1)
    roof_r_u = roof_cols.min() / (n - 1)

    # bonnet height: median profile over the front 12-25% (clear of bumper wrap)
    zone = (u > 0.75) & (u < 0.88)
    bonnet_h = float(np.median(prof[zone]))
    # cowl: walking back from the nose, the first station where the profile
    # exceeds the bonnet line by 6% of H is the base of the screen
    cowl_u = None
    for i in range(n - 1, -1, -1):
        if u[i] < roof_f_u:
            break
        if prof[i] > bonnet_h + 0.06:
            cowl_u = u[i]
    fit = {"bonnet_h": round(bonnet_h, 3),
           "roof_f": round(float(roof_f_u), 3),
           "roof_r": round(float(roof_r_u), 3),
           "facing": facing}
    if cowl_u:
        fit["cowl"] = round(float(cowl_u), 3)
    return fit


def run(folder, out=None):
    dims_path = os.path.join(folder, "dims.json")
    if not os.path.exists(dims_path):
        raise SystemExit(f"{folder}/dims.json is required — put the "
                         "manufacturer's published dimensions there (mm). "
                         "This pipeline never estimates size from pixels.")
    dims = json.load(open(dims_path))
    for k in ("name", "length", "width", "height", "wheelbase"):
        if k not in dims:
            raise SystemExit(f"dims.json missing '{k}'")
    style = dims.get("style", "hatch")
    if style not in STYLES:
        raise SystemExit(f"style '{style}' unknown; one of {sorted(STYLES)}")

    report = {"dims": dims, "photos": {}, "fit": None, "fit_source": None}
    photos = sorted(glob.glob(os.path.join(folder, "*.png")) +
                    glob.glob(os.path.join(folder, "*.jpg")))
    side = [p for p in photos if "side" in os.path.basename(p).lower()]
    for p in photos:
        report["photos"][os.path.basename(p)] = "side-fit" if p in side else "recorded"

    overrides = {}
    if side:
        try:
            mask = load_mask(side[0])
            fit = fit_side(mask)
            report["fit"] = fit
            report["fit_source"] = os.path.basename(side[0])
            # sanity clamps: a fit outside physical range means a bad mask, and
            # the style default is better than a corrupt landmark
            if 0.45 <= fit["bonnet_h"] <= 0.75:
                overrides["bonnet_h"] = fit["bonnet_h"]
            if 0.55 <= fit.get("cowl", 0) <= 0.88:
                overrides["cowl"] = fit["cowl"]
            # clamp roof_f against the cowl ACTUALLY IN USE — override if one
            # was fitted, otherwise the style default. Clamping against a
            # non-existent fitted cowl let roof_f 0.526 through against a
            # style cowl of 0.770 and built a windscreen half the bonnet long.
            cowl_used = overrides.get("cowl", STYLES[style]["cowl"])
            if 0.50 <= fit["roof_f"] <= 0.75:
                overrides["roof_f"] = min(fit["roof_f"], cowl_used - 0.06)
            if 0.10 <= fit["roof_r"] <= 0.45:
                overrides["roof_r"] = fit["roof_r"]
        except ValueError as e:
            report["fit"] = f"REFUSED: {e}"
    report["overrides_applied"] = overrides

    spec = dict(length=dims["length"], width=dims["width"], height=dims["height"],
                wheelbase=dims["wheelbase"],
                track=dims.get("track", dims["width"] * 0.86),
                wheel_d=dims.get("wheel_d", 640), tyre_w=dims.get("tyre_w", 205),
                style=style)
    car = Car(name=dims["name"], **spec)
    if overrides:
        car.s = dict(car.s)
        car.s.update(overrides)

    out = out or os.path.join(folder, f"{dims['name']}.glb")
    size, g = build_structured(car, out, root_name=dims["name"])
    report["glb"] = {"path": out, "kb": round(size / 1024),
                     "meshes": len(g.g["meshes"]),
                     "materials": [m["name"] for m in g.g["materials"]]}
    rp = os.path.join(folder, "fit_report.json")
    json.dump(report, open(rp, "w"), indent=1)
    print(json.dumps(report["fit"], indent=1) if report["fit"] else "no side view — style defaults")
    print(f"overrides applied: {overrides}")
    print(f"wrote {out} ({size/1024:.0f} KB) and {rp}")
    return out, report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--out")
    a = ap.parse_args()
    run(a.folder, a.out)
