#!/usr/bin/env python3
"""hole_test.py -- prove no new holes, two independent ways.

(1) EXACT: the triangle multiset.  Positions and normals are copied byte for
    byte and only the index arrays are rewritten, so the set of triangles the
    two files draw must be IDENTICAL.  This is compared as a sorted multiset of
    world-space vertex triples, which is stronger than any ray test: a ray test
    samples, this does not.

(2) RAY: 15 directions (az 0/+-22/+-40 x el 0/+-18), a dense parallel grid per
    direction, hit/miss recorded per ray.  A NEW HOLE is a ray that hit the car
    before and misses it after.  Also reports the silhouette pixel count per
    direction, which is the silhouette-change number.

Run: hole_test.py <before.glb> <after.glb> [--res 1400]
"""
import sys

import numpy as np
import trimesh
from trimesh.ray import ray_pyembree

BEFORE, AFTER = sys.argv[1], sys.argv[2]
RES = int(sys.argv[sys.argv.index("--res") + 1]) if "--res" in sys.argv else 1400


def world(path):
    sc = trimesh.load(path, process=False, force="scene")
    Vl, Fl = [], []
    off = 0
    for n in sc.graph.nodes_geometry:
        T, gname = sc.graph[n]
        m = sc.geometry[gname]
        v = trimesh.transformations.transform_points(np.asarray(m.vertices, np.float64), T)
        Vl.append(v); Fl.append(np.asarray(m.faces, np.int64) + off); off += len(v)
    V = np.vstack(Vl); F = np.vstack(Fl)
    return trimesh.Trimesh(vertices=V, faces=F, process=False)


A = world(BEFORE)
B = world(AFTER)
print(f"before {len(A.faces)} faces / after {len(B.faces)} faces")
print(f"before area {A.area:.6f} m2 / after area {B.area:.6f} m2  "
      f"(delta {B.area-A.area:+.9f})")
lo_a, hi_a = A.bounds; lo_b, hi_b = B.bounds
print(f"before extents {np.round(hi_a-lo_a,6)}")
print(f"after  extents {np.round(hi_b-lo_b,6)}")

# ---------------------------------------------------------------- (1) exact
def tset(m):
    t = np.round(m.vertices[m.faces] / 1e-9).astype(np.int64)
    t = np.sort(t.reshape(len(t), 3, 3).view([('', np.int64)] * 3).reshape(len(t), 3),
                axis=1) if False else t
    k = t.reshape(len(t), 9)
    k = np.array(sorted(map(tuple, np.sort(k.reshape(-1, 3, 3), axis=1).reshape(-1, 9))))
    return k


ka, kb = tset(A), tset(B)
identical = ka.shape == kb.shape and np.array_equal(ka, kb)
print(f"\n(1) EXACT triangle multiset identical: {identical}   "
      f"({len(ka)} vs {len(kb)} triangles)")

# ---------------------------------------------------------------- (2) rays
inter_a = ray_pyembree.RayMeshIntersector(A)
inter_b = ray_pyembree.RayMeshIntersector(B)
ctr = (lo_a + hi_a) / 2.0
rad = float(np.linalg.norm(hi_a - lo_a))
tot_new = 0
print("\n(2) RAY test, 15 directions, "
      f"{RES}x{RES} parallel rays each ({RES*RES*15/1e6:.1f}M rays)")
print(f"{'az':>5s} {'el':>5s} {'hit_before':>11s} {'hit_after':>10s} "
      f"{'new_holes':>10s} {'sil_delta':>10s}")
for az in (-40, -22, 0, 22, 40):
    for el in (-18, 0, 18):
        a = np.radians(az); e = np.radians(el)
        d = np.array([np.cos(e) * np.cos(a), np.sin(e), np.cos(e) * np.sin(a)])
        d /= np.linalg.norm(d)
        up = np.array([0.0, 1.0, 0.0])
        rgt = np.cross(d, up); rgt /= np.linalg.norm(rgt)
        up2 = np.cross(rgt, d)
        s = np.linspace(-rad * 0.55, rad * 0.55, RES)
        gx, gy = np.meshgrid(s, s, indexing="ij")
        o = (ctr - d * rad * 1.5
             + gx.ravel()[:, None] * rgt + gy.ravel()[:, None] * up2)
        dd = np.tile(d, (len(o), 1))
        ha = inter_a.intersects_first(o, dd) >= 0
        hb = inter_b.intersects_first(o, dd) >= 0
        new = int((ha & ~hb).sum())
        tot_new += new
        print(f"{az:5d} {el:5d} {int(ha.sum()):11d} {int(hb.sum()):10d} "
              f"{new:10d} {int(hb.sum())-int(ha.sum()):+10d}")
print(f"\nTOTAL NEW HOLES across all 15 directions: {tot_new}")
