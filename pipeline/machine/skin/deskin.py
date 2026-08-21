#!/usr/bin/env python3
"""deskin.py -- WITHDRAWN.  The deletion route, built, run, and MEASURED WORSE.

KEEP THIS FILE, DO NOT RUN IT.  It implements exactly what the brief asked for --
ray order to decide which sheet of a pair is the intruder, a visibility-derived
outward field to decide which side a face is on, deletion only where another
surface is within --dnear so no hole can open.  It works as specified.  It is
still the wrong operation on this car, because there is no double skin here:

    v1 (outward field built from ALL faces, including the 543,164 that are never
        visible and therefore have a ZERO outward vector -> side read 0.0)
        condemned 17.3% of the car.  That was a bug, fixed.
    v3 (signed distance to the closest point on the VISIBLE winner surface)
        deleted 74,722 faces / 3.71 m2 and the matched render got WORSE:
        bonnet dark specks 5.34% -> 6.41%, roof 5.55% -> 6.28%.

The reason is in skin/README.md: `Body_Shell` and `Interior` are ONE triangulated
surface split by label (exactly 1 duplicate triangle between them; 23,232 shared-
vertex faces of which 92.4% sit on a Body_Shell BOUNDARY edge).  Deleting the
"intruder" removes real skin.  `relabel.py` is the repair.

--- original docstring follows ---

deskin.py -- remove the intruding sheet of a double skin.

THE DEFECT, as measured on car_rebound.glb (not as assumed):
  the visible speckle is NOT the near-coincident anti-parallel set.  A magenta
  diagnostic of that set (diag05.glb) put nothing on the bonnet or the roof,
  where the speckle is worst.  What the deterministic mesh-ID pass shows is a
  SECOND SHELL -- Interior / Arch_Liner -- lying a few mm inside Body_Shell and
  Bumper_*_Paint, whose surface noise CROSSES the outer skin.  Every crossing
  shows a dark triangle on red paint.  Interior wins 10.1% of roof pixels and
  9.0% of bonnet pixels while winning 0.07% of the flank, which is the profile
  of noise crossing a surface, not of a panel.

THE DECISION, and why it is not made on names or normals:
  * WHICH SHEET IS THE INTRUDER is decided by RAY ORDER, over 48 directions:
    Body_Shell is in front of Interior over 3.397 m2 and behind it over
    0.089 m2 -- 38:1.  A thin solid seen from both sides scores ~1:1 and is
    refused.  Only pairs above --ratio are acted on.
  * WHICH SIDE a given face is on is decided by an OUTWARD FIELD built from
    visibility: a face's outward direction is the average of the directions
    from which it is the first thing hit.  No face normal is read (46% of
    faces in the lamp band are flipped) and no material name decides anything.
  * A face is deleted only when the winning surface is within --dnear of it,
    so the geometry it exposes is always the winner's own surface a few mm
    behind.  That is what makes the operation hole-free by construction; the
    multi-angle ray test then proves it rather than assuming it.

Deletion is at FACE level; vertices are left alone.  Nothing is moved: the
recorded failure "vertex-pull DENTS panels" is not available to this tool.

Run: deskin.py <car.glb> <out.glb> [--ratio 8] [--minarea 0.002]
                [--dnear 0.008] [--safe 0.001] [--dirs 96]
"""
import json
import sys

import numpy as np
import trimesh
from scipy.spatial import cKDTree
from trimesh.ray import ray_pyembree

CAR = sys.argv[1]
OUT = sys.argv[2]


def opt(f, d, c=float):
    return c(sys.argv[sys.argv.index(f) + 1]) if f in sys.argv else d


RATIO = opt("--ratio", 8.0)
MINAREA = opt("--minarea", 0.002)
DNEAR = opt("--dnear", 0.008)
SAFE = opt("--safe", 0.001)
NDIR = opt("--dirs", 96, int)
BIG = 6.0
EPS = 2e-5
REPORT = sys.argv[sys.argv.index("--report") + 1] if "--report" in sys.argv else "deskin_report.json"

# ------------------------------------------------------------------ load
sc = trimesh.load(CAR, process=False, force="scene")
names = list(sc.geometry.keys())
Vl, Fl, Gl = [], [], []
off = 0
counts = []
for gi, n in enumerate(names):
    m = sc.geometry[n]
    T, _ = sc.graph.get(n)
    v = trimesh.transformations.transform_points(np.asarray(m.vertices, np.float64), T)
    f = np.asarray(m.faces, np.int64)
    Vl.append(v); Fl.append(f + off); Gl.append(np.full(len(f), gi, np.int32))
    off += len(v); counts.append(len(f))
V = np.vstack(Vl); F = np.vstack(Fl); G = np.concatenate(Gl)
occ = trimesh.Trimesh(vertices=V, faces=F, process=False)
tri = V[F]
C = tri.mean(1)
A = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
NF = len(F); NG = len(names)
print(f"[deskin] {NF} faces / {NG} meshes / {A.sum():.4f} m2")

# ------------------------------------------------- pass 1: order + outward
inter = ray_pyembree.RayMeshIntersector(occ)
i = np.arange(NDIR) + 0.5
phi = np.arccos(1 - 2 * i / NDIR)
th = np.pi * (1 + 5 ** 0.5) * i
DIRS = np.stack([np.cos(th) * np.sin(phi), np.sin(th) * np.sin(phi), np.cos(phi)], 1)
idx = np.arange(NF)
outw = np.zeros((NF, 3))
vis = np.zeros(NF, np.int32)
pair = np.zeros((NG, NG))
for k, dv in enumerate(DIRS):
    t1 = inter.intersects_first(C - dv * BIG, np.tile(dv, (NF, 1)))
    seen = t1 == idx
    vis += seen
    outw[seen] -= dv                      # viewer sits on the -dir side
    s = np.nonzero(seen)[0]
    if not len(s):
        continue
    o2 = C[s] + dv * EPS
    loc, ir, it = inter.intersects_location(o2, np.tile(dv, (len(s), 1)), multiple_hits=False)
    if len(ir):
        g = np.linalg.norm(loc - o2[ir], axis=1) + EPS
        ok = (it != s[ir]) & (g < 0.006)
        np.add.at(pair, (G[s[ir[ok]]], G[it[ok]]), A[s[ir[ok]]])
    if k % 24 == 0:
        print(f"   dir {k}/{NDIR}", flush=True)
nrm = np.linalg.norm(outw, axis=1)
print(f"[deskin] visible faces {int((vis>0).sum())} ({100*(vis>0).mean():.2f}%)")

# ------------------------------------------------- decide loser/winner pairs
pairs = []
for a in range(NG):
    for b in range(NG):
        if a == b or pair[a, b] <= 0:
            continue
        fwd, rev = pair[a, b], pair[b, a]
        if fwd >= MINAREA and (rev <= 0 or fwd / rev >= RATIO):
            pairs.append((b, a, fwd, rev, fwd / rev if rev > 0 else float("inf")))
pairs.sort(key=lambda r: -r[2])
print("\n[deskin] LOSER -> WINNER pairs accepted (ratio >= "
      f"{RATIO}, winner-front area >= {MINAREA} m2):")
for l, w, fwd, rev, r in pairs:
    print(f"   loser {names[l]:20s} under winner {names[w]:20s}  "
          f"front {fwd:7.4f} rev {rev:7.4f} ratio {r:8.1f}")
refused = [(names[a], names[b], round(pair[a, b], 5), round(pair[b, a], 5))
           for a in range(NG) for b in range(NG)
           if a != b and pair[a, b] >= MINAREA and pair[b, a] > 0
           and pair[a, b] / pair[b, a] < RATIO]
print(f"[deskin] refused (too symmetric to call): {len(refused)}")
for r in refused[:10]:
    print("   ", r)

# ------------------------------------------------- point-triangle distance
def pt_tri(p, a, b, c):
    """squared distance from points p to triangles (a,b,c), vectorised."""
    ab = b - a; ac = c - a; ap = p - a
    d1 = (ab * ap).sum(-1); d2 = (ac * ap).sum(-1)
    bp = p - b; d3 = (ab * bp).sum(-1); d4 = (ac * bp).sum(-1)
    cp = p - c; d5 = (ab * cp).sum(-1); d6 = (ac * cp).sum(-1)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    den = va + vb + vc
    with np.errstate(divide="ignore", invalid="ignore"):
        v = np.where(den != 0, vb / den, 0.0)
        w = np.where(den != 0, vc / den, 0.0)
    q = a + v[..., None] * ab + w[..., None] * ac
    # region checks -> clamp to edges / vertices
    m1 = (d1 <= 0) & (d2 <= 0); q = np.where(m1[..., None], a, q)
    m2 = (d3 >= 0) & (d4 <= d3); q = np.where(m2[..., None], b, q)
    m3 = (d6 >= 0) & (d5 <= d6); q = np.where(m3[..., None], c, q)
    m4 = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    t = np.where(d1 - d3 != 0, d1 / np.where(d1 - d3 != 0, d1 - d3, 1), 0)
    q = np.where(m4[..., None], a + np.clip(t, 0, 1)[..., None] * ab, q)
    m5 = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
    t = np.where(d2 - d6 != 0, d2 / np.where(d2 - d6 != 0, d2 - d6, 1), 0)
    q = np.where(m5[..., None], a + np.clip(t, 0, 1)[..., None] * ac, q)
    m6 = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
    dd = (d4 - d3) - (d5 - d6)
    t = np.where(dd != 0, (d4 - d3) / np.where(dd != 0, dd, 1), 0)
    q = np.where(m6[..., None], b + np.clip(t, 0, 1)[..., None] * (c - b), q)
    return ((p - q) ** 2).sum(-1), q


kill = np.zeros(NF, bool)
detail = {}
VIS = vis > 0
print(f"[deskin] outward field built from {int(VIS.sum())} visible faces; "
      f"{int((~VIS).sum())} faces have NO visibility and are never used as a "
      f"side reference (v1 of this file used them, their outward vector is the "
      f"zero vector, side read 0.0 and 17.3% of the car was condemned).")
OWN = outw / np.maximum(np.linalg.norm(outw, axis=1, keepdims=True), 1e-12)

for l, w, fwd, rev, r in pairs:
    lf = np.nonzero(G == l)[0]
    wf = np.nonzero((G == w) & VIS)[0]          # VISIBLE winner surface only
    if len(lf) == 0 or len(wf) < 32:
        continue
    twd = cKDTree(C[wf])
    pre = twd.query_ball_point(C[lf], r=DNEAR + 0.03, return_length=True) > 0
    lf = lf[pre]
    if not len(lf):
        continue
    # ONE smoothed outward per WINNER face, averaged over its own mesh's 12
    # nearest visible faces.  Smoothing across the query point's neighbourhood
    # instead (v2) mixes outwards from opposite sides of a fold.
    _, nn = twd.query(C[wf], k=12, workers=-1)
    owf = OWN[wf][nn].sum(1)
    owf /= np.maximum(np.linalg.norm(owf, axis=1, keepdims=True), 1e-12)

    K = 12
    P = V[F[lf]]
    rr = np.arange(len(lf))
    best_d2 = np.full((len(lf), 3), np.inf)
    best_side = np.full((len(lf), 3), -1e9)
    for corner in range(3):
        pts = P[:, corner, :]
        dd, jj = twd.query(pts, k=K, workers=-1)
        tw = V[F[wf[jj]]]
        d2, q = pt_tri(pts[:, None, :], tw[..., 0, :], tw[..., 1, :], tw[..., 2, :])
        k0 = d2.argmin(1)
        best_d2[:, corner] = d2[rr, k0]
        # TRUE signed distance: from the closest point ON the winner surface to
        # the query point, projected on that winner face's outward.
        best_side[:, corner] = ((pts - q[rr, k0]) * owf[jj[rr, k0]]).sum(1)
    dmin = np.sqrt(best_d2.min(1))
    m = (dmin < DNEAR) & (best_side.max(1) > -SAFE)
    kill[lf[m]] = True
    detail[f"{names[l]}<{names[w]}"] = {
        "loser_faces": int((G == l).sum()), "near_winner": int(len(lf)),
        "killed": int(m.sum()), "killed_area": round(float(A[lf[m]].sum()), 6),
        "ratio": None if not np.isfinite(r) else round(float(r), 2)}
    print(f"   {names[l]:20s} under {names[w]:20s}: near {len(lf):6d}  kill "
          f"{int(m.sum()):6d} faces / {A[lf[m]].sum():.4f} m2  "
          f"(side p50 {np.median(best_side.max(1))*1000:+.2f}mm)")

print(f"\n[deskin] TOTAL delete {int(kill.sum())} faces ({100*kill.mean():.3f}%), "
      f"area {A[kill].sum():.4f} m2 of {A.sum():.4f}")

# ------------------------------------------------- write
out = trimesh.Scene()
off = 0
kept_meta = {}
for gi, n in enumerate(names):
    m = sc.geometry[n]
    T, _ = sc.graph.get(n)
    nf = counts[gi]
    k = kill[off:off + nf]
    off += nf
    keep = ~k
    if not keep.any():
        print(f"   WARNING mesh {n} fully deleted -- refusing"); keep[:] = True
    g = trimesh.Trimesh(vertices=m.vertices.copy(), faces=m.faces[keep], process=False)
    if hasattr(m.visual, "material"):
        g.visual = trimesh.visual.TextureVisuals(material=m.visual.material)
    out.add_geometry(g, node_name=n, geom_name=n, transform=T)
    kept_meta[n] = {"before": int(nf), "after": int(keep.sum())}
assert off == NF
out.export(OUT)
np.save(OUT + ".kill.npy", kill)
json.dump({"input": CAR, "output": OUT,
           "params": {"ratio": RATIO, "minarea": MINAREA, "dnear": DNEAR,
                      "safe": SAFE, "dirs": NDIR},
           "pairs": detail, "refused": refused, "meshes": kept_meta,
           "faces_before": int(NF), "faces_after": int((~kill).sum()),
           "area_before": round(float(A.sum()), 6),
           "area_after": round(float(A[~kill].sum()), 6)},
          open(REPORT, "w"), indent=1)
print(f"[deskin] wrote {OUT} and {REPORT}")
