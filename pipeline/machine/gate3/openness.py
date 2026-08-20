#!/usr/bin/env python3
"""openness.py -- geometric EXTERIOR selection for the front fascia.

WHY NOT MATERIAL NAMES: on this car the material named `interior` holds
223,595 of the 267,108 nose-zone faces (12.15 of 16.7 m2) and includes the
bumper and valance.  Gate 5 measured the same thing globally (45% of
exterior panel area is labelled `interior`).  Selecting the fascia by name
is therefore wrong in both directions.

WHY NOT FACE NORMALS: the shell carries inverted-normal patches -- 46% of
body faces in the lamp band point the wrong way.  Any normal-sign test
inherits that.

The test that survives both: cast 32 rays from each face centroid over the
whole sphere and count how many ESCAPE the car.  A face on the outside of
the bumper sees open sky over roughly a hemisphere; a face inside the
engine bay or behind the shell sees almost none.  No names, no normals.

FALSIFICATION, written before the probe was built: if openness cannot
separate exterior from enclosed geometry, the escape-fraction histogram
will be unimodal, and hand-picked control faces (outer bonnet crown =
exterior; a face inside the engine bay = enclosed) will land at the same
value.  Both are checked and printed below.

v1 OF THIS PROBE FAILED THAT TEST AND IS WITHDRAWN.  Shooting rays OUTWARD
from the face centroid self-intersects the originating triangle: offsetting
the origin along the ray only clears the triangle plane by eps*cos(theta),
so every grazing ray hits t~0.  Result: 228,989 of 319,301 faces scored
exactly 0.000, INCLUDING the exterior bonnet control.  A probe whose
control and its opposite read the same number measures nothing.

v2, used here, INVERTS the rays: for each of 32 directions, start 4 m
OUTSIDE the car and shoot inward at the face centroid.  The face is
"visible from that direction" iff it is the FIRST thing the inbound ray
hits.  No self-hit is possible, and this is the property actually wanted:
a fascia surface a camera can see.

Run: python3 openness.py <car.glb> <out.npz>
"""
import sys
import numpy as np
import trimesh

CAR = sys.argv[1]
OUT = sys.argv[2]
NRAY = 32
ZONE = float(sys.argv[3]) if len(sys.argv) > 3 else 1.10   # metres back from nose

sc = trimesh.load(CAR, force="scene")
names = list(sc.geometry.keys())
meshes = [sc.geometry[n] for n in names]

# one concatenated occluder = the whole car (rays must be blocked by ALL of it)
occ = trimesh.util.concatenate(meshes)
print(f"occluder: {len(occ.faces)} faces")
inter = trimesh.ray.ray_pyembree.RayMeshIntersector(occ)

XMIN = float(occ.vertices[:, 0].min())
XMAX = float(occ.vertices[:, 0].max())
GY = float(occ.vertices[:, 1].min())
H = float(np.percentile(occ.vertices[:, 1], 99.8)) - GY
print(f"XMIN {XMIN:.4f} XMAX {XMAX:.4f} ground {GY:.4f} H {H:.4f}  NOSE AT -X")

# fibonacci sphere directions
i = np.arange(NRAY) + 0.5
phi = np.arccos(1 - 2 * i / NRAY)
th = np.pi * (1 + 5 ** 0.5) * i
DIRS = np.stack([np.cos(th) * np.sin(phi), np.sin(th) * np.sin(phi), np.cos(phi)], 1)

# gather nose-zone faces, tagged with their source geometry
recs = []
for gi, (n, m) in enumerate(zip(names, meshes)):
    c = m.triangles_center
    sel = np.nonzero(c[:, 0] < XMIN + ZONE)[0]
    if len(sel):
        recs.append((gi, n, sel, c[sel], m.area_faces[sel]))
        print(f"  {n:12s} {len(sel):7d} nose-zone faces")

C = np.vstack([r[3] for r in recs])
A = np.concatenate([r[4] for r in recs])
GID = np.concatenate([np.full(len(r[2]), r[0]) for r in recs])
FID = np.concatenate([r[2] for r in recs])
print(f"candidates: {len(C)}")

# control faces, chosen BEFORE the histogram is seen
crown = np.argmin(np.abs(C[:, 2]) + np.abs(C[:, 0] - (XMIN + 0.85)) +
                  np.abs(C[:, 1] - (GY + 0.62 * H)))          # bonnet crown-ish
deep = np.argmin(np.abs(C[:, 2]) + np.abs(C[:, 0] - (XMIN + 1.05)) +
                 np.abs(C[:, 1] - (GY + 0.30 * H)))           # inside engine bay

esc = np.zeros(len(C), dtype=np.float32)
R = 4.0
TOL = 0.004          # 4 mm: the inbound ray must land ON this face
CH = 6000
for s0 in range(0, len(C), CH):
    e = min(s0 + CH, len(C))
    n = e - s0
    tgt = np.repeat(C[s0:e], NRAY, axis=0)
    dirs = np.tile(DIRS, (n, 1))
    org = tgt + dirs * R
    loc, iray, _ = inter.intersects_location(org, -dirs, multiple_hits=False)
    vis = np.zeros(n * NRAY, dtype=bool)
    if len(iray):
        d = np.linalg.norm(loc - tgt[iray], axis=1)
        vis[iray[d < TOL]] = True
    esc[s0:e] = vis.reshape(n, NRAY).mean(1)
    if (s0 // CH) % 10 == 0:
        print(f"  {e}/{len(C)}", flush=True)

h, edges = np.histogram(esc, bins=20, range=(0, 1))
print("escape-fraction histogram (20 bins 0..1):")
print("  counts:", h.tolist())
print("  area-weighted:", np.round(
    [A[(esc >= edges[k]) & (esc < edges[k + 1] + (1e-9 if k == 19 else 0))].sum()
     for k in range(20)], 3).tolist())
print(f"CONTROL bonnet-crown face esc={esc[crown]:.3f} at {np.round(C[crown],3)}")
print(f"CONTROL engine-bay  face esc={esc[deep]:.3f} at {np.round(C[deep],3)}")

np.savez_compressed(OUT, esc=esc, C=C, A=A, GID=GID, FID=FID,
                    names=np.array(names), XMIN=XMIN, XMAX=XMAX, GY=GY, H=H)
print("wrote", OUT)
