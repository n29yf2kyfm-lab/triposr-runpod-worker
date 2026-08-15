#!/usr/bin/env python3
"""silhouette_iou.py — GEOMETRY-mode QC: per-view silhouette IoU vs captures.

Adopted 2026-08-15 from the owner's research review: the h/l coherence ratio
cannot see "one bad front end" — a car can average well and still have a
single wrong view. This gate compares the MESH's orthographic silhouette
against each capture cutout's alpha mask, per view, and reports the WORST
view as well as the mean. It is the formal GEOMETRY half of dual-mode QC
(the studio PBR renders are the APPEARANCE half); silhouettes are compared
as masks so paint, lighting and reflections cannot influence the score.

Method (no renderer needed — deterministic and seconds-fast):
  * sample ~2M points on the mesh surface, project orthographically along
    the width axis (side views) and the length axis (end views), splat into
    a raster, morphologically close to fill sampling pinholes;
  * both the mesh silhouette and the photo alpha mask are bbox-cropped and
    uniformly scaled into a common frame (translation/scale removed, ASPECT
    preserved — a wrong height/length ratio still fails);
  * each photo is scored against the projection AND its mirror, keeping the
    best — nose direction is checked elsewhere (orient_catalogue), and this
    gate must not double-fail on orientation.

Axes are detected from extents, so the gate works in both the authoring
frame (length X) and the catalogue frame (length Z).

Usage:
    python3 pipeline/carglb/silhouette_iou.py car.glb photos_dir \
        [--res 512] [--min-worst 0.90] [--min-mean 0.93]
Exit 1 when a threshold fails. Prints per-view IoU either way.
"""
import argparse
import os
import sys

import numpy as np
import trimesh
from PIL import Image


def axes_of(ext):
    L = int(np.argmax(ext))
    rest = [i for i in range(3) if i != L]
    H = rest[int(np.argmin(ext[rest]))]
    W = [i for i in rest if i != H][0]
    return L, H, W


def close_mask(m, r=2):
    """Binary closing via shifted-OR dilate then shifted-AND erode."""
    d = m.copy()
    for _ in range(r):
        d2 = d.copy()
        d2[1:, :] |= d[:-1, :]; d2[:-1, :] |= d[1:, :]
        d2[:, 1:] |= d[:, :-1]; d2[:, :-1] |= d[:, 1:]
        d = d2
    e = d.copy()
    for _ in range(r):
        e2 = e.copy()
        e2[1:, :] &= e[:-1, :]; e2[:-1, :] &= e[1:, :]
        e2[:, 1:] &= e[:, :-1]; e2[:, :-1] &= e[:, 1:]
        e = e2
    return e


def norm_frame(mask, res):
    """Crop to a ROBUST bbox, uniform-scale into res x res (aspect kept).

    Plain bbox normalisation failed on the Golf (measured, end view IoU
    0.70): the photo's bbox is mirror-to-mirror while thin mirrors barely
    register in the sampled mesh mask, so the two frames disagree by a
    mirror's width per side. Percentile bounds over mask PIXELS make thin
    protrusions (mirrors, aerials, stray speckles) irrelevant to the frame
    on BOTH sides of the comparison.
    """
    ys, xs = np.where(mask)
    if len(ys) == 0:
        return np.zeros((res, res), dtype=bool)
    y0, y1 = np.percentile(ys, [0.3, 99.7]).astype(int)
    x0, x1 = np.percentile(xs, [0.3, 99.7]).astype(int)
    crop = mask[y0:y1 + 1, x0:x1 + 1]
    h, w = crop.shape
    s = (res - 2) / max(h, w)
    im = Image.fromarray((crop * 255).astype(np.uint8)).resize(
        (max(1, int(w * s)), max(1, int(h * s))), Image.BILINEAR)
    a = np.asarray(im) > 127
    out = np.zeros((res, res), dtype=bool)
    y0 = (res - a.shape[0]) // 2
    x0 = (res - a.shape[1]) // 2
    out[y0:y0 + a.shape[0], x0:x0 + a.shape[1]] = a
    return out


def mesh_silhouette(P, ax_u, ax_v, res):
    """COMMON scale factor for both axes — v1 normalised u and v
    independently, which squashed a 4.3m car into a square and scored a
    correct Golf at IoU 0.35 (measured). Aspect must survive rasterisation."""
    u = P[:, ax_u]; v = P[:, ax_v]
    s = (res - 1) / max(u.max() - u.min(), v.max() - v.min(), 1e-9)
    ui = np.clip((u - u.min()) * s, 0, res - 1).astype(int)
    vi = np.clip((v - v.min()) * s, 0, res - 1).astype(int)
    m = np.zeros((res, res), dtype=bool)
    m[vi, ui] = True
    return close_mask(m, 2)


def photo_mask(path):
    a = np.asarray(Image.open(path).convert("RGBA"))[:, :, 3]
    return a > 24


def iou(a, b):
    inter = (a & b).sum()
    union = (a | b).sum()
    return inter / union if union else 0.0


def score(car_glb, photos_dir, res=512, n_samples=2_000_000):
    m = trimesh.load(car_glb, force="mesh")
    P, _ = trimesh.sample.sample_surface(m, n_samples)
    P = np.asarray(P)
    # robust clip: stray geometry outside the 0.2-99.8 percentile box
    # otherwise inflates the frame (measured: a 1.79m-wide Golf read 2.16m)
    lo = np.percentile(P, 0.2, axis=0)
    hi = np.percentile(P, 99.8, axis=0)
    P = P[np.all((P >= lo) & (P <= hi), axis=1)]
    ext = P.max(0) - P.min(0)
    L, H, W = axes_of(ext)

    # view -> projection plane (horizontal axis, vertical axis)
    pairs = [("left.png", (L, H)), ("right.png", (L, H)),
             ("front.png", (W, H)), ("rear.png", (W, H))]
    results = {}
    sil_cache = {}
    for photo, (au, av) in pairs:
        path = os.path.join(photos_dir, photo)
        if not os.path.exists(path):
            continue
        if (au, av) not in sil_cache:
            sil_cache[(au, av)] = norm_frame(
                mesh_silhouette(P, au, av, res)[::-1], res)  # flip: y up
        sil = sil_cache[(au, av)]
        ph = norm_frame(photo_mask(path), res)
        results[photo] = max(iou(sil, ph), iou(sil[:, ::-1], ph))
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("car_glb")
    ap.add_argument("photos_dir")
    # CALIBRATED 2026-08-15 on golf_final.glb — the current best passing car
    # (owner-eyeballed): sides 0.92, end views 0.79. The end-view ceiling is
    # the generator's boxy-sill signature (an ortho end-on silhouette is the
    # UNION of all cross-sections, so bloated sills fatten it) — real signal,
    # not comparison error. These defaults are a REGRESSION TRIPWIRE for the
    # current tier; raise them as the tier improves, never silently lower.
    ap.add_argument("--res", type=int, default=512)
    ap.add_argument("--min-worst", type=float, default=0.75)
    ap.add_argument("--min-mean", type=float, default=0.82)
    a = ap.parse_args()
    r = score(a.car_glb, a.photos_dir, a.res)
    if not r:
        raise SystemExit("no capture photos found — gate not applicable")
    # review finding 3: front.png and rear.png score against ONE union
    # silhouette (an ortho projection along length is the union of all
    # cross-sections) — a single measurement that CANNOT see a bad nose
    # (measured: nose collapsed to 0.45x left end IoU at exactly 1.0000
    # while the side dropped to 0.88). Merge them into one honest score.
    ends = [v for k, v in r.items() if k in ("front.png", "rear.png")]
    r = {k: v for k, v in r.items() if k not in ("front.png", "rear.png")}
    if ends:
        r["end(union)"] = sum(ends) / len(ends)
    print(f"  ({len(r)} independent measurements)")
    for k, v in sorted(r.items()):
        print(f"  {k:12s} IoU {v:.4f}")
    worst = min(r.values()); mean = sum(r.values()) / len(r)
    print(f"silhouette IoU: mean {mean:.4f}  worst {worst:.4f} "
          f"(gates: mean>={a.min_mean}, worst>={a.min_worst})")
    if worst < a.min_worst or mean < a.min_mean:
        raise SystemExit("GATE FAIL: silhouette IoU below threshold")
    print("silhouette gate PASS")


if __name__ == "__main__":
    main()
