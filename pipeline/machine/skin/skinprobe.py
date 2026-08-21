#!/usr/bin/env python3
"""skinprobe.py -- who is in FRONT of whom, decided by rays only.

For D directions spread over the whole sphere:
  pass 1  origin = centroid - 4 m * dir, shoot along dir.  Face f is VISIBLE
          along dir iff it is the FIRST triangle hit.  (openness.py v1 shot
          rays OUTWARD from the face and self-hit every time, reading 0.000 for
          its own exterior control -- inverted rays cannot self-hit.)
  pass 2  from the hit point, step eps along the same dir and shoot again.
          That is the surface immediately BEHIND f from this viewpoint, and the
          along-ray distance to it is the GAP.

Nothing here reads a face normal (46% are flipped in the lamp band) or a
material name (`interior` is documented to hold exterior panels on this family).
The only inputs are ray order and geometry.

Outputs per face: vis (how many directions see it), and for the direction with
the SMALLEST backing gap, the backing face and that gap.  Plus the ordered
mesh-pair area table, which is what decides which sheet of a doubled pair is
the true outer skin: a real doubling is ASYMMETRIC (one sheet is in front
almost everywhere), a thin solid seen from both sides is not.

Run: skinprobe.py <car.glb> <out.npz> [--dirs 48] [--gmax 0.006]
"""
import sys
import numpy as np
import trimesh
from trimesh.ray import ray_pyembree

CAR = sys.argv[1]
OUT = sys.argv[2]


def opt(f, d, c=float):
    return c(sys.argv[sys.argv.index(f) + 1]) if f in sys.argv else d


NDIR = opt("--dirs", 48, int)
GMAX = opt("--gmax", 0.006)
BIG = 6.0
EPS = 2e-5

sc = trimesh.load(CAR, process=False, force="scene")
names = list(sc.geometry.keys())
Vl, Fl, Gl = [], [], []
off = 0
for gi, n in enumerate(names):
    m = sc.geometry[n]
    T, _ = sc.graph.get(n)
    v = trimesh.transformations.transform_points(np.asarray(m.vertices, np.float64), T)
    f = np.asarray(m.faces, np.int64)
    Vl.append(v); Fl.append(f + off); Gl.append(np.full(len(f), gi, np.int32)); off += len(v)
V = np.vstack(Vl); F = np.vstack(Fl); G = np.concatenate(Gl)
occ = trimesh.Trimesh(vertices=V, faces=F, process=False)
tri = V[F]
C = tri.mean(1)
A = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
NF = len(F)
print(f"[skinprobe] {NF} faces, {len(names)} meshes, area {A.sum():.4f} m2, dirs {NDIR}")

inter = ray_pyembree.RayMeshIntersector(occ)
i = np.arange(NDIR) + 0.5
phi = np.arccos(1 - 2 * i / NDIR)
th = np.pi * (1 + 5 ** 0.5) * i
DIRS = np.stack([np.cos(th) * np.sin(phi), np.sin(th) * np.sin(phi), np.cos(phi)], 1)

idx = np.arange(NF)
vis = np.zeros(NF, np.int16)
best_gap = np.full(NF, np.inf)
best_back = np.full(NF, -1, np.int64)
best_dir = np.full(NF, -1, np.int16)
# ordered mesh-pair area: pair_area[a,b] = visible area of mesh a with mesh b
# immediately behind it within GMAX, summed over directions (area-weighted)
NG = len(names)
pair_area = np.zeros((NG, NG))

for k, dv in enumerate(DIRS):
    o = C - dv * BIG
    dd = np.tile(dv, (NF, 1))
    t1 = inter.intersects_first(o, dd)
    seen = (t1 == idx)
    vis += seen
    s = np.nonzero(seen)[0]
    if not len(s):
        continue
    o2 = C[s] + dv * EPS
    d2 = np.tile(dv, (len(s), 1))
    loc, ir, it = inter.intersects_location(o2, d2, multiple_hits=False)
    if len(ir):
        g = np.linalg.norm(loc - o2[ir], axis=1) + EPS
        # a re-hit of the face itself is a precision artefact, not a backing
        good = it != s[ir]
        ir, it, g = ir[good], it[good], g[good]
        near = g < GMAX
        fs = s[ir[near]]
        bs = it[near]
        np.add.at(pair_area, (G[fs], G[bs]), A[fs])
        upd = g[near] < best_gap[fs]
        best_gap[fs[upd]] = g[near][upd]
        best_back[fs[upd]] = bs[upd]
        best_dir[fs[upd]] = k
    if k % 12 == 0:
        print(f"   dir {k}/{NDIR} vis_so_far {int((vis>0).sum())}", flush=True)

print(f"\n[skinprobe] visible faces: {(vis>0).sum()} ({100*(vis>0).mean():.2f}%), "
      f"visible area {A[vis>0].sum():.4f} m2")
backed = np.isfinite(best_gap)
print(f"[skinprobe] visible AND backed within {GMAX*1000:.1f} mm: {backed.sum()} "
      f"({100*backed.mean():.2f}%), area {A[backed].sum():.4f} m2")

print("\n=== ordered mesh pairs: visible area of FRONT with BACK within gmax ===")
print("   (A>B means A was in front of B; asymmetry is the doubling signature)")
tot = pair_area.sum()
order = np.dstack(np.unravel_index(np.argsort(-pair_area, axis=None), pair_area.shape))[0]
shown = 0
for a, b in order:
    if pair_area[a, b] <= 0 or shown >= 22:
        break
    rev = pair_area[b, a]
    r = pair_area[a, b] / rev if rev > 0 else np.inf
    print(f"   {names[a]:20s} > {names[b]:20s} {pair_area[a,b]:8.4f}  rev {rev:8.4f}  ratio {r:7.2f}")
    shown += 1

np.savez_compressed(OUT, vis=vis, best_gap=best_gap, best_back=best_back,
                    best_dir=best_dir, pair_area=pair_area, A=A, G=G, C=C,
                    names=np.array(names), dirs=DIRS)
print("\nwrote", OUT)
