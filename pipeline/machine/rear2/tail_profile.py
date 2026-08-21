#!/usr/bin/env python3
"""tail_profile.py — the OUTER tail surface x(y,z), measured per side.

Estimator: OUTER EXTREME with a spike guard, never a percentile.
Gate 4 recorded that a p95 per-cell estimator is pulled short by the melt's
dense INTERIOR points and seated a lens up to 150 mm inside the body. So per
(y,z) cell we take the largest x, then reject it if it is a lone spike --
defined as >12 mm proud of the 2nd..5th largest in the same cell.

It also reports, per cell, how many DISTINCT surface layers exist behind the
outer one within 150 mm: that is the hidden-melt depth profile of the zone I
am about to strip.

Run: python3 tail_profile.py <glb> <out.json>
"""
import json, sys
import numpy as np, trimesh

GLB, OUT = sys.argv[1], sys.argv[2]
sc = trimesh.load(GLB, force="scene", process=False)
G = dict(sc.geometry)
# EXCLUDE the constructed Gate-4 parts: they are additions ON the surface, not
# the surface. Including them would make the profile ride the lens crest.
EXCL = {n for n in G if n.startswith(("Tail_Lens","Tail_Housing","Rear_Plate"))}
pts, own = [], []
names = [n for n in G if n not in EXCL]
for i, n in enumerate(names):
    fc = G[n].triangles_center
    pts.append(fc); own.append(np.full(len(fc), i))
P = np.vstack(pts); O = np.concatenate(own)
XMAX = float(np.vstack([g.vertices for g in G.values()])[:,0].max())

DY = DZ = 0.020
YLO, YHI = 0.10, 1.10
ZLO, ZHI = -0.95, 0.95
ny = int(round((YHI-YLO)/DY)); nz = int(round((ZHI-ZLO)/DZ))
prof = np.full((ny, nz), np.nan)
layers = np.zeros((ny, nz), int)
spikes = 0
iy = ((P[:,1]-YLO)/DY).astype(int); iz = ((P[:,2]-ZLO)/DZ).astype(int)
ok = (iy>=0)&(iy<ny)&(iz>=0)&(iz<nz)&(P[:,0] > 0.9)
iy, iz, Px, Po = iy[ok], iz[ok], P[ok,0], O[ok]
order = np.lexsort((-Px, iz, iy))
iy, iz, Px = iy[order], iz[order], Px[order]
key = iy*nz+iz
bnd = np.flatnonzero(np.r_[True, key[1:]!=key[:-1]])
for s, e in zip(bnd, np.r_[bnd[1:], len(key)]):
    xs = Px[s:e]
    if len(xs) == 0: continue
    x0 = xs[0]
    if len(xs) >= 5 and (x0 - xs[1:5].max()) > 0.012:
        spikes += 1
        x0 = xs[1]                    # lone spike rejected
    prof[iy[s], iz[s]] = x0
    layers[iy[s], iz[s]] = int((xs > x0 - 0.150).sum())
ys = YLO + (np.arange(ny)+0.5)*DY
zs = ZLO + (np.arange(nz)+0.5)*DZ

rep = {"XMAX": XMAX, "cells": int(np.isfinite(prof).sum()), "spikes_rejected": spikes,
       "ys": [round(float(v),4) for v in ys], "zs": [round(float(v),4) for v in zs],
       "prof": [[None if not np.isfinite(v) else round(float(v),4) for v in row] for row in prof],
       "layers": layers.tolist()}

# left/right correspondence at matched |z|
print(f"{'y':>6s} | {'zmax(+z)':>9s} {'zmin(-z)':>9s} {'shear':>7s} | "
      f"{'x@z=+0.30':>9s} {'x@z=-0.30':>9s} {'dx':>7s} | layers(mean)")
for j, y in enumerate(ys):
    row = prof[j]
    fin = np.isfinite(row)
    if fin.sum() < 4: continue
    zp = zs[fin & (zs > 0)]; zm = zs[fin & (zs < 0)]
    if len(zp) == 0 or len(zm) == 0: continue
    zmax, zmin = zp.max(), zm.min()
    def at(zt):
        k = int(np.argmin(np.abs(zs - zt)))
        for d in range(0, 6):
            for kk in (k-d, k+d):
                if 0 <= kk < nz and np.isfinite(row[kk]): return row[kk]
        return np.nan
    print(f"{y:6.3f} | {zmax:9.3f} {zmin:9.3f} {abs(zmin)-zmax:7.3f} | "
          f"{at(0.30):9.3f} {at(-0.30):9.3f} {at(0.30)-at(-0.30):7.3f} | {layers[j][fin].mean():.2f}")
json.dump(rep, open(OUT,"w"))
print("\nspikes rejected:", spikes, " cells:", int(np.isfinite(prof).sum()))
