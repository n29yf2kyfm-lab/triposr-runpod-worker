#!/usr/bin/env python3
"""holes_map.py — WHERE are the receded rays? A seam is a line; a hole is a blob.

A rebuilt panel with REAL shut lines must produce some receded rays: a gap is a
gap, and a ray through it legitimately reaches whatever is behind. So the count
alone cannot separate "this panel has seams" from "this panel has a hole". The
map can, and connected-component sizes make it quantitative.
"""
import sys
import numpy as np, trimesh
from scipy import ndimage
TOL = 0.060
DIRS = [(0, 0), (40, 0), (-40, 0)]


def scene_tris(path):
    sc = trimesh.load(path, force="scene", process=False)
    T = []
    for n in sc.graph.nodes_geometry:
        M, g = sc.graph[n]
        T.append(trimesh.transform_points(sc.geometry[g].vertices, M)[sc.geometry[g].faces])
    T = np.vstack(T)
    return trimesh.Trimesh(vertices=T.reshape(-1, 3),
                           faces=np.arange(len(T) * 3).reshape(-1, 3), process=False)


def depth(mesh, az, el, n=44):
    ys = np.linspace(0.16, 1.36, n); zs = np.linspace(-0.86, 0.80, n)
    Y, Z = np.meshgrid(ys, zs, indexing="ij")
    a, e = np.radians(az), np.radians(el)
    d = np.array([-np.cos(e) * np.cos(a), -np.sin(e), -np.cos(e) * np.sin(a)])
    tgt = np.stack([np.full(Y.size, 2.05), Y.ravel(), Z.ravel()], 1)
    o = tgt - 3.0 * d
    loc, ir, _ = mesh.ray.intersects_location(o, np.tile(d, (len(o), 1)), multiple_hits=False)
    dep = np.full(len(o), np.inf)
    if len(ir):
        np.minimum.at(dep, ir, np.linalg.norm(loc - o[ir], axis=1))
    return dep.reshape(n, n), ys, zs


mb, ma = scene_tris(sys.argv[1]), scene_tris(sys.argv[2])
for az, el in DIRS:
    b, ys, zs = depth(mb, az, el)
    a, _, _ = depth(ma, az, el)
    hb = np.isfinite(b)
    rec = hb & (~np.isfinite(a) | ((a - b) > TOL))
    lab, n = ndimage.label(rec)
    sizes = sorted(ndimage.sum(rec, lab, range(1, n + 1)).astype(int), reverse=True)
    print(f"--- az{az:+d} el{el:+d}: receded {int(rec.sum())} of {int(hb.sum())} hit-before, "
          f"{n} components, largest {sizes[:6]}")
    for i in range(rec.shape[0] - 1, -1, -2):
        row = "".join("#" if rec[i, j] else ("." if hb[i, j] else " ") for j in range(rec.shape[1]))
        print(f"  y={ys[i]:.2f} |{row}|")
