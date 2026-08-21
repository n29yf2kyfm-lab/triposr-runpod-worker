#!/usr/bin/env python3
"""layer_probe.py — how deep does the melt go under the tailgate and bumper?

The strip depth must come from a measurement, not a guess. Radial rays are
fired INWARD through the exact footprint the strip will use; each ray's
crossings are ordered by SIGNED distance along its own outward direction, and
only crossings in front of the pivot are counted.

BUG FOUND AND FIXED HERE (recorded, not hidden): v1 ordered crossings by the
UNSIGNED radius |p - pivot|, so a hit on the car's NOSE (r = 3.4) sorted ahead
of the tailgate (r = 0.75) and the probe reported `carpaint` -- a mesh whose
faces stop at x = 1.369 -- as the FIRST surface at the tail. Any depth chosen
from that output would have been measured from the wrong end of the car.

RIVAL THEORY, written before running: if the tailgate is a single clean skin
with only the cabin behind it, rays show ONE crossing then a long gap (>150 mm)
to the next. If it is fragment-soup melt, several crossings land within the
first 100 mm. The depth histogram is printed either way.

Run: python3 layer_probe.py <glb> <out.json> [thmax_bumper] [thmax_hatch]
"""
import json, sys
from collections import Counter
import numpy as np, trimesh
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from rear_zone import (load_points, section_centre,
                       Y_BUMPER_BOT, Y_BUMPER_TOP, Y_HATCH_TOP)

GLB, OUT = sys.argv[1], sys.argv[2]
TB = float(sys.argv[3]) if len(sys.argv) > 3 else 68.0
TH = float(sys.argv[4]) if len(sys.argv) > 4 else 34.0
sc = trimesh.load(GLB, force="scene", process=False)
G = dict(sc.geometry)
P, O, names = load_points(sc)
tris = np.vstack([G[n].triangles for n in names])
owner = np.concatenate([np.full(len(G[n].faces), i) for i, n in enumerate(names)])
big = trimesh.Trimesh(vertices=tris.reshape(-1, 3),
                      faces=np.arange(len(tris) * 3).reshape(-1, 3), process=False)
inter = trimesh.ray.ray_triangle.RayMeshIntersector(big)

rep = {}
for panel, ylo, yhi, thmax in (("bumper", Y_BUMPER_BOT, Y_BUMPER_TOP, TB),
                               ("hatch", Y_BUMPER_TOP, Y_HATCH_TOP, TH)):
    ys = np.arange(ylo + 0.015, yhi, 0.030)
    C = section_centre(P, ys)
    ths = np.linspace(-thmax, thmax, 33)
    O_, D_, meta = [], [], []
    for j, y in enumerate(ys):
        xc, zc = C[j]
        if not np.isfinite(xc): continue
        for t in ths:
            a = np.radians(t)
            out = np.array([np.cos(a), 0.0, np.sin(a)])       # OUTWARD radial
            O_.append(np.array([xc, y, zc]) + 1.4 * out)
            D_.append(-out); meta.append((y, t, xc, zc))
    O_ = np.array(O_); D_ = np.array(D_)
    loc, ir, it = inter.intersects_location(O_, D_, multiple_hits=True)
    per = {}
    for r, t, p in zip(ir, it, loc):
        y, th, xc, zc = meta[int(r)]
        s = float(np.dot(p - np.array([xc, y, zc]), -D_[int(r)]))   # SIGNED
        if s <= 0.0:            # behind the pivot -> the far side of the car
            continue
        per.setdefault(int(r), []).append((s, int(owner[t])))
    depths, ncross, first_names, d2 = [], [], [], []
    for r, hits in per.items():
        hits.sort(key=lambda h: -h[0])
        rs = np.array([h[0] for h in hits])
        keep = [0]
        for i in range(1, len(rs)):
            if rs[keep[-1]] - rs[i] > 0.002: keep.append(i)
        rs2 = rs[keep]
        ncross.append(len(rs2)); first_names.append(names[hits[keep[0]][1]])
        dd = (rs2[0] - rs2[1:]) * 1000.0
        depths.extend(dd.tolist())
        d2.append(float(dd[0]) if len(dd) else 1e9)
    depths = np.array(depths); ncross = np.array(ncross); d2 = np.array(d2)
    bins = [0, 20, 40, 60, 80, 100, 150, 200, 300, 1e9]
    hist = {f"{bins[i]}-{bins[i+1]}mm": int(((depths >= bins[i]) & (depths < bins[i+1])).sum())
            for i in range(len(bins) - 1)}
    cum = {f"<{t}mm": round(float((d2 < t).mean() * 100), 2) for t in (20, 40, 60, 80, 100, 150)}
    within100 = [1 + int((((rs2 := np.array(sorted([h[0] for h in v], reverse=True)))[0] - rs2[1:]) * 1000 < 100).sum())
                 for v in per.values()]
    rep[panel] = {"rays": int(len(O_)), "rays_hit": int(len(ncross)),
                  "mean_crossings": round(float(ncross.mean()), 3),
                  "median_crossings": int(np.median(ncross)),
                  "mean_surfaces_within_100mm_of_outer": round(float(np.mean(within100)), 3),
                  "depth_hist_behind_first": hist,
                  "pct_rays_2nd_surface_within": cum,
                  "first_surface_owner": dict(Counter(first_names).most_common(8))}
    print(panel, json.dumps(rep[panel], indent=1))
json.dump(rep, open(OUT, "w"), indent=1)
