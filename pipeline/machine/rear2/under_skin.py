#!/usr/bin/env python3
"""under_skin.py — criterion 2, asked directly: what is UNDER the new skin?

"No hidden melt underneath" is not a count of surfaces -- a real pressing has
two (its own outer and inner skin), so a bare crossing count cannot answer it.
The question is WHOSE surfaces they are. This fires the same radial rays as
layer_probe and names the owner of every crossing within 100 mm behind the
first, then reports the share that belong to a MELT component.

Gate 3 v6 reported this class of number as 1.34% against its predecessor's
24.33%.

Run: python3 under_skin.py <glb> <out.json>
"""
import json, sys
from collections import Counter
import numpy as np, trimesh
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from rear_zone import load_points, section_centre, Y_BUMPER_BOT, Y_BUMPER_TOP, Y_HATCH_TOP

GLB, OUT = sys.argv[1], sys.argv[2]
REBUILT = {"Hatch", "Hatch_Inner", "Bumper_Rear", "Bumper_Rear_Inner",
           "Plate_Rear", "Glass_Backlight"}
sc = trimesh.load(GLB, force="scene", process=False)
G = dict(sc.geometry)
P, O, names = load_points(sc)
tris = np.vstack([G[n].triangles for n in names])
owner = np.concatenate([np.full(len(G[n].faces), i) for i, n in enumerate(names)])
big = trimesh.Trimesh(vertices=tris.reshape(-1, 3),
                      faces=np.arange(len(tris) * 3).reshape(-1, 3), process=False)
inter = trimesh.ray.ray_triangle.RayMeshIntersector(big)
rep = {}
for panel, ylo, yhi, thmax in (("bumper", Y_BUMPER_BOT, Y_BUMPER_TOP, 68.0),
                               ("hatch", Y_BUMPER_TOP, Y_HATCH_TOP, 34.0)):
    ys = np.arange(ylo + 0.010, yhi, 0.020)
    C = section_centre(P, ys)
    ths = np.linspace(-thmax, thmax, 49)
    O_, D_, meta = [], [], []
    for j, y in enumerate(ys):
        xc, zc = C[j]
        if not np.isfinite(xc): continue
        for t in ths:
            a = np.radians(t); out = np.array([np.cos(a), 0.0, np.sin(a)])
            O_.append(np.array([xc, y, zc]) + 1.4 * out); D_.append(-out)
            meta.append((y, xc, zc))
    O_, D_ = np.array(O_), np.array(D_)
    loc, ir, it = inter.intersects_location(O_, D_, multiple_hits=True)
    per = {}
    for r, t, p in zip(ir, it, loc):
        y, xc, zc = meta[int(r)]
        s = float(np.dot(p - np.array([xc, y, zc]), -D_[int(r)]))
        if s <= 0: continue
        per.setdefault(int(r), []).append((s, names[owner[t]]))
    first, under, melt_rays, tot = Counter(), Counter(), 0, 0
    for r, h in per.items():
        h.sort(key=lambda q: -q[0])
        keep = [h[0]]
        for i in range(1, len(h)):
            if keep[-1][0] - h[i][0] > 0.002: keep.append(h[i])
        first[keep[0][1]] += 1
        tot += 1
        got = False
        for s, nm in keep[1:]:
            if keep[0][0] - s > 0.100: break
            under[nm] += 1
            if nm not in REBUILT: got = True
        if got: melt_rays += 1
    rep[panel] = {"rays": tot,
                  "first_surface": dict(first.most_common()),
                  "surfaces_within_100mm_behind": dict(under.most_common()),
                  "rays_with_NON_REBUILT_surface_within_100mm": melt_rays,
                  "pct_rays_with_melt_under_skin": round(100.0 * melt_rays / max(tot, 1), 2)}
    print(panel, json.dumps(rep[panel], indent=1))
json.dump(rep, open(OUT, "w"), indent=1)
