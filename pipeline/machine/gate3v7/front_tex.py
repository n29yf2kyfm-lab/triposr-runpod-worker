#!/usr/bin/env python3
"""front_tex.py -- GATE 3 v7: orthographic depth map of the front face.

Produces the (y,z) -> depth-behind-the-nose-plane field the planner and the
builder both work in, plus the node that OWNS each frontmost cell.  Depth D is
measured BACKWARD from the nose plane, so "proud" means a SMALLER D -- the same
convention gate3/front_build.py used, kept deliberately so its numbers remain
comparable.

There is no Embree in this container (`embreex` and `pyembree` both absent), so
this is a vectorised software rasteriser rather than a ray cast: every triangle
is expanded over the grid cells its (y,z) bbox covers, tested barycentrically,
and reduced with a scatter-min on x.  It is exact for the frontmost surface,
which is all the planner needs.

NORMALS ARE NEVER CONSULTED.  46% of the body faces in the lamp band carry
inverted normals on this family of meshes, so a front-facing test would drop
half the fascia.  Frontmost-x is orientation-blind by construction.

Run: python3 front_tex.py <car.glb> <survey.json> <out.npz> [--res 0.002]
"""
import json
import sys

import numpy as np
import trimesh

CAR, SURVEY, OUT = sys.argv[1:4]
RES = 0.002
if "--res" in sys.argv:
    RES = float(sys.argv[sys.argv.index("--res") + 1])

sv = json.load(open(SURVEY))
if sv["nose_at"] != "XMIN":
    raise SystemExit("front_tex: this tool assumes nose at XMIN; survey says "
                     + sv["nose_at"])
XMIN = float(sv["nose_plane"]["x_bbox"])
DEPTH = 0.75                     # how far back from the nose we care about
Y0, Y1 = 0.15, 1.15
Z0, Z1 = -0.95, 0.95

ny = int(round((Y1 - Y0) / RES)) + 1
nz = int(round((Z1 - Z0) / RES)) + 1
ys = Y0 + np.arange(ny) * RES
zs = Z0 + np.arange(nz) * RES
print(f"grid {ny} x {nz} @ {RES*1000:.1f}mm   XMIN {XMIN:+.5f}  depth window {DEPTH}")

sc = trimesh.load(CAR, force="scene", process=False)
nodes = sorted(sc.graph.nodes_geometry)
nidx = {n: i for i, n in enumerate(nodes)}

TRI, OWN = [], []
for node in nodes:
    T, gname = sc.graph[node]
    g = sc.geometry[gname]
    v = trimesh.transform_points(np.asarray(g.vertices, float), T)
    tri = v[np.asarray(g.faces)]
    keep = (tri[:, :, 0].min(1) < XMIN + DEPTH)
    if not keep.any():
        continue
    TRI.append(tri[keep])
    OWN.append(np.full(int(keep.sum()), nidx[node], np.int32))
    print(f"  {node:22s} {int(keep.sum()):7d} / {len(tri):7d} tris in window")
TRI = np.concatenate(TRI)
OWN = np.concatenate(OWN)
print(f"rasterising {len(TRI)} triangles")

# ------------------------------------------------------------ to grid space
gy = (TRI[:, :, 1] - Y0) / RES
gz = (TRI[:, :, 2] - Z0) / RES
j0 = np.clip(np.floor(gy.min(1)).astype(np.int64), 0, ny - 1)
j1 = np.clip(np.ceil(gy.max(1)).astype(np.int64), 0, ny - 1)
i0 = np.clip(np.floor(gz.min(1)).astype(np.int64), 0, nz - 1)
i1 = np.clip(np.ceil(gz.max(1)).astype(np.int64), 0, nz - 1)
hh = (j1 - j0 + 1)
ww = (i1 - i0 + 1)
# a triangle whose (y,z) bbox is empty in the window contributes nothing
live = ((gy.max(1) >= 0) & (gy.min(1) <= ny - 1) &
        (gz.max(1) >= 0) & (gz.min(1) <= nz - 1))
TRI, OWN, j0, i0, hh, ww = TRI[live], OWN[live], j0[live], i0[live], hh[live], ww[live]
cnt = hh * ww
print(f"  {len(TRI)} live, {cnt.sum()} candidate cells "
      f"(max bbox {hh.max()}x{ww.max()})")

DM = np.full((ny, nz), np.inf)
OWNMAP = np.full((ny, nz), -1, np.int32)

CH = 4_000_000                   # candidate-cell budget per chunk
order = np.argsort(-cnt)         # big triangles first so chunks stay bounded
start = 0
csum = np.cumsum(cnt[order])
chunks = []
lo = 0
while lo < len(order):
    hi = int(np.searchsorted(csum, csum[lo - 1] if lo else 0) )
    hi = int(np.searchsorted(csum, (csum[lo - 1] if lo else 0) + CH, "right"))
    hi = max(hi, lo + 1)
    chunks.append(order[lo:hi])
    lo = hi

for ci, sel in enumerate(chunks):
    t = TRI[sel]
    o = OWN[sel]
    h, w = hh[sel], ww[sel]
    n = h * w
    tid = np.repeat(np.arange(len(sel)), n)
    off = np.concatenate([[0], np.cumsum(n)[:-1]])
    k = np.arange(n.sum()) - np.repeat(off, n)
    wr = np.repeat(w, n)
    jj = np.repeat(j0[sel], n) + k // wr
    ii = np.repeat(i0[sel], n) + k % wr
    ok = (jj >= 0) & (jj < ny) & (ii >= 0) & (ii < nz)
    tid, jj, ii = tid[ok], jj[ok], ii[ok]

    Py = ys[jj]
    Pz = zs[ii]
    a, b, c = t[tid, 0], t[tid, 1], t[tid, 2]
    # barycentric in the (y,z) plane
    v0y, v0z = b[:, 1] - a[:, 1], b[:, 2] - a[:, 2]
    v1y, v1z = c[:, 1] - a[:, 1], c[:, 2] - a[:, 2]
    v2y, v2z = Py - a[:, 1], Pz - a[:, 2]
    den = v0y * v1z - v1y * v0z
    good = np.abs(den) > 1e-14
    u = np.where(good, (v2y * v1z - v1y * v2z) / np.where(good, den, 1), -1)
    v = np.where(good, (v0y * v2z - v2y * v0z) / np.where(good, den, 1), -1)
    tol = 1e-9
    inside = good & (u >= -tol) & (v >= -tol) & (u + v <= 1 + tol)
    if not inside.any():
        continue
    tid, jj, ii, u, v = tid[inside], jj[inside], ii[inside], u[inside], v[inside]
    a, b, c = t[tid, 0], t[tid, 1], t[tid, 2]
    X = a[:, 0] + u * (b[:, 0] - a[:, 0]) + v * (c[:, 0] - a[:, 0])
    flat = jj.astype(np.int64) * nz + ii
    # scatter-min with owner: sort by (cell, x) and take the first of each cell
    srt = np.lexsort((X, flat))
    flat, X, tid = flat[srt], X[srt], tid[srt]
    first = np.concatenate([[True], flat[1:] != flat[:-1]])
    fc, fx, ft = flat[first], X[first], tid[first]
    cj, cinz = fc // nz, fc % nz
    better = fx < DM[cj, cinz]
    DM[cj[better], cinz[better]] = fx[better]
    OWNMAP[cj[better], cinz[better]] = o[ft[better]]
    print(f"  chunk {ci+1}/{len(chunks)}: {len(sel)} tris -> {int(better.sum())} cells improved")

SIL = np.isfinite(DM)
D = np.where(SIL, DM - XMIN, np.nan)
print(f"covered cells {SIL.sum()} / {ny*nz} ({SIL.mean()*100:.1f}%)")
np.savez_compressed(OUT, D=D, ys=ys, zs=zs, OWN=OWNMAP, nodes=np.array(nodes),
                    XMIN=XMIN, RES=RES, Y0=Y0, Z0=Z0)
print("FRONT_TEX_DONE", OUT)
