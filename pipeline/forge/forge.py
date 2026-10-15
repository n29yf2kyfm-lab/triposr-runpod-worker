#!/usr/bin/env python3
"""forge.py — photographs in, an interactive car GLB out. No Blender.

    python3 pipeline/forge/forge.py JOB_DIR [--out car.glb]

JOB_DIR holds dims.json (the manufacturer's figures in mm — see
authoring/photos_to_glb.py for the contract) and background-removed RGBA
cut-outs named side*.png, front*.png, rear*.png. The side view is what makes
the shape; the end views make the cross-section; anything missing falls back
to the body-style default and the report says so.

The build checks itself: the finished loft is projected back onto each
photograph and the overlap (intersection over union) is reported per view.
A side overlap under 0.90 means the photo and the model disagree — look
before shipping.
"""
import argparse
import glob
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "authoring"))
from trace import load_cutout, trace_side, trace_end          # noqa: E402
from shape import PhotoCar                                     # noqa: E402
from structured_car import build_structured, loft              # noqa: E402


def first(folder, key):
    hits = sorted(glob.glob(os.path.join(folder, f"{key}*.png")))
    return hits[0] if hits else None


def silhouette_side(car, P, mask, frame):
    """Rasterise the loft (both sides) and the wheels into the side photo's
    frame; return IoU with the cut-out mask."""
    x0, x1, ground, pxm, facing, zscale = frame
    n = x1 - x0 + 1
    im = Image.new("1", mask.shape[::-1], 0)
    d = ImageDraw.Draw(im)

    def px(x, y):                                  # car x (m, nose +) and height -> image
        u = x / car.L + 0.5
        k = (1 - u) * (n - 1) if facing == "left" else u * (n - 1)
        return (x0 + k, ground - y / zscale * pxm)
    NUu, nv = P.shape[0], P.shape[1]
    for i in range(NUu - 1):
        for j in range(nv - 1):
            q = [px(P[a, b, 0], P[a, b, 1]) for a, b in ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))]
            d.polygon(q, fill=1)
    for ax in (car.L * (car.u_front - 0.5), car.L * (car.u_rear - 0.5)):
        cx, cy = px(ax, car.RW)
        r = car.RW / zscale * pxm
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=1)
    m = np.asarray(im).astype(bool)
    inter, union = (m & mask).sum(), (m | mask).sum()
    return float(inter / max(union, 1)), m


def silhouette_end(car, P, mask, dims, which):
    """Same for a front/rear view: project (width, height)."""
    H, W = mask.shape
    rows = np.where(mask.any(axis=1))[0]
    ground = rows.max()
    cols = np.where(mask.any(axis=0))[0]
    cx = (cols.min() + cols.max()) / 2
    hpx = rows.max() - rows.min() + 1
    pxm = hpx / car.H
    im = Image.new("1", (W, H), 0)
    d = ImageDraw.Draw(im)

    def px(z, y):
        return (cx + z * pxm, ground - y * pxm)
    NUu, nv = P.shape[0], P.shape[1]
    for i in range(NUu - 1):
        for j in range(nv - 1):
            for s in (1, -1):
                q = [px(s * P[a, b, 2], P[a, b, 1]) for a, b in ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))]
                d.polygon(q, fill=1)
    for s in (1, -1):
        z = s * car.TR / 2
        a, b = px(z - car.TW / 2, 0), px(z + car.TW / 2, 2 * car.RW)
        d.rectangle([min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])], fill=1)
    m = np.asarray(im).astype(bool)
    return float((m & mask).sum() / max((m | mask).sum(), 1)), m


def run(folder, out=None, skin=False):
    dims = json.load(open(os.path.join(folder, "dims.json")))
    report = {"dims": dims, "photos": {}, "used": {}, "overlap": {}}
    side = front = rear = None
    masks = {}
    p = first(folder, "side")
    if p:
        rgb, mask = load_cutout(p)
        side = trace_side(rgb, mask, dims)
        masks["side"] = (mask, side["frame"])
        report["photos"]["side"] = os.path.basename(p)
        report["side"] = {k: side[k] for k in ("u_front", "u_rear", "height_photo", "wheelbase_photo",
                                                "zscale", "shut_u", "body_lum")}
        report["side"]["belt_seen_fraction"] = float(np.isfinite(side["belt"]).mean())
    for key in ("front", "rear"):
        p = first(folder, key)
        if p:
            rgb, mask = load_cutout(p)
            # a true end view of a car is about as wide as it is tall
            # (W/H 1.1-1.45 with mirrors); a three-quarter view is far wider and
            # would be read as a car twice its real width
            rows = np.where(mask.any(axis=1))[0]
            cols = np.where(mask.any(axis=0))[0]
            aspect = (cols.max() - cols.min() + 1) / max(rows.max() - rows.min() + 1, 1)
            if not 0.95 <= aspect <= 1.55:
                report["photos"][key] = f"{os.path.basename(p)}: not a true {key} view (aspect {aspect:.2f}), ignored"
                continue
            t = trace_end(mask, dims, key)
            masks[key] = (mask, None)
            report["photos"][key] = os.path.basename(p)
            report[key] = {"z_shoulder": t["z_shoulder"], "height_photo": t["height_photo"]}
            if key == "front":
                front = t
            else:
                rear = t
    car = PhotoCar(dims, side=side, front=front, rear=rear, name=dims["name"])
    report["used"] = car.used
    report["style_landmarks"] = {k: round(float(v), 3) for k, v in car.s.items()}

    out = out or os.path.join(folder, f"{dims['name']}.glb")
    # the side photograph is baked onto the body as its skin when asked: the
    # loft now follows the photo's own profile, so the projection lines up
    skin_photo = first(folder, "side") if skin else None
    size, g = build_structured(car, out, root_name=dims["name"], photo=skin_photo, photo_view="side")
    report["skin"] = os.path.basename(skin_photo) if skin_photo else None
    report["glb"] = {"path": out, "kb": round(size / 1024), "meshes": len(g.g["meshes"])}
    if hasattr(car, "door_seams"):
        report["door_seams"] = {k: round(float(v), 3) for k, v in car.door_seams.items()}

    # self-check: project the built body back onto the photographs
    P, REG, us, arch, axles, arch_r, CREASE = loft(car)
    if "side" in masks:
        iou, _ = silhouette_side(car, P, masks["side"][0], masks["side"][1])
        report["overlap"]["side"] = round(iou, 3)
    for key in ("front", "rear"):
        if key in masks:
            iou, _ = silhouette_end(car, P, masks[key][0], dims, key)
            report["overlap"][key] = round(iou, 3)
    rp = os.path.join(folder, "forge_report.json")
    json.dump(report, open(rp, "w"), indent=1, default=float)
    print(json.dumps({k: report[k] for k in ("used", "overlap", "side", "door_seams") if k in report},
                     indent=1, default=float))
    print(f"wrote {out} ({size/1024:.0f} KB) and {rp}")
    return out, report


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--out")
    ap.add_argument("--skin", action="store_true", help="bake the side photo onto the body")
    a = ap.parse_args()
    run(a.folder, a.out, skin=a.skin)
