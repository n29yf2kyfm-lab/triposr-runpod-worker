#!/usr/bin/env python3
"""feature_size.py — can this mesh REPRESENT the features the bar requires?

THE ANALYTIC KILL TEST. Every argument about generated-car quality in this
project has been conducted with renders, and renders invite opinion. This asks
a question with a number for an answer: a shut line is a ~4-5 mm gap and a
lamp recess is a ~30 mm step, so what is the smallest feature this mesh's
triangulation could carry even in principle?

Nyquist, applied to geometry: a feature needs at least TWO edges across it to
exist as geometry at all, and realistically three to look like anything. So

    representable feature size  ~=  2 x (median edge length)

If that number is larger than a shut line, no downstream stage -- labelling,
smoothing, normal filtering, detail transfer, another seed, a bigger
generation budget -- can produce one. The geometry has nowhere to put it. That
is a property of the mesh, not of anyone's taste, and it is why this runs
BEFORE any more repair work.

WHAT IT DOES NOT PROVE. A coarse mesh can still LOOK detailed if the detail
lives in a normal map or a baked texture, which is exactly how most good
real-time car assets are built. So a fail here is not "this car looks bad", it
is "this car cannot carry that feature AS GEOMETRY". Run it on a known-good
control in the same breath -- if the control is equally coarse, the answer is
that the whole product tier works by texture and the generated car's problem
lies elsewhere. Never read the subject's number without the control's.

Also reports the dihedral-angle spectrum, which turns "the panels look soft"
into a measurement: what FRACTION of the mesh's edge length is sharp, and at
what angles. `crease_density` already counts sharp edges but cannot separate
"sharp because there is a real crease" from "sharp because the surface is
noisy" -- the spectrum can, because noise is broadband and low-angle while a
shut line is a narrow population at high angle.

Run: python3 feature_size.py <a.glb> [<b.glb> ...] [--length-m 4.284]
"""
import argparse
import sys

import numpy as np
import trimesh

ap = argparse.ArgumentParser()
ap.add_argument("glb", nargs="+")
ap.add_argument("--length-m", type=float, default=None,
                help="real length in metres; the mesh is scaled onto it before "
                     "measuring so a normalised mesh and a metre-scale mesh "
                     "are comparable. Default: assume the mesh is already in "
                     "metres if its longest extent is 1.5-7.0, else refuse.")
SHUT_LINE_MM = 4.5      # typical panel gap on a modern hatch
LAMP_RECESS_MM = 30.0   # depth step around a headlamp aperture
a = ap.parse_args()


def measure(path, length_m):
    sc = trimesh.load(path, force="scene", process=False)
    # Bake node transforms: a scene whose parts carry transforms measures its
    # own extents wrong otherwise, and this file's whole output is a scale.
    for nd in sc.graph.nodes_geometry:
        T, gn = sc.graph[nd]
        if T is not None and not np.allclose(T, np.eye(4)):
            sc.geometry[gn].apply_transform(T)
            sc.graph.update(frame_to=nd, matrix=np.eye(4), geometry=gn)
    m = trimesh.util.concatenate([g for g in sc.geometry.values()])
    ext = m.extents
    L = float(ext.max())
    if length_m is None:
        if not (1.5 <= L <= 7.0):
            raise SystemExit(f"REFUSED: {path} longest extent {L:.3f} is not "
                             "plausibly metres -- pass --length-m")
        length_m = L
    s = length_m / L
    V = m.vertices * s

    # WELD FIRST. A GLB stores split vertices at every UV and material seam, so
    # un-welded edge statistics count seam edges of length ~0 and report a
    # median far below the true triangulation. Recorded trap: the same weld is
    # why surface_clean and glass_topo both remove_doubles before counting.
    mw = trimesh.Trimesh(vertices=V, faces=m.faces, process=True,
                         validate=False)
    E = mw.edges_unique
    el = np.linalg.norm(mw.vertices[E[:, 0]] - mw.vertices[E[:, 1]], axis=1)
    el_mm = el * 1000.0
    q = np.percentile(el_mm, [5, 25, 50, 75, 95])

    # Dihedral spectrum, weighted by EDGE LENGTH so a swarm of tiny noisy edges
    # cannot outvote a real crease.
    ang = np.degrees(mw.face_adjacency_angles)
    aedge = mw.vertices[mw.face_adjacency_edges[:, 0]] - \
        mw.vertices[mw.face_adjacency_edges[:, 1]]
    alen = np.linalg.norm(aedge, axis=1)
    tot = float(alen.sum())
    bands = {}
    for lo, hi in ((0, 5), (5, 15), (15, 30), (30, 60), (60, 120), (120, 180)):
        k = (ang >= lo) & (ang < hi)
        bands[f"{lo}-{hi}"] = 100.0 * float(alen[k].sum()) / max(tot, 1e-9)

    return {
        "path": path, "faces": len(mw.faces), "verts": len(mw.vertices),
        "length_m": length_m, "scaled_by": s,
        "edge_mm": q, "mean_mm": float(el_mm.mean()),
        "feature_mm": 2.0 * q[2],
        # THE MEDIAN IS THE WRONG STATISTIC AND THE CONTROL PROVED IT.
        # Measured 2026-08-25: the sourced Golf the owner ACCEPTED has a
        # median edge of 9.7 mm and "cannot represent" a 4.5 mm shut line by
        # the median test -- yet it plainly has shut lines. Its p5 edge is
        # 0.53 mm. A real asset is ADAPTIVELY triangulated: dense where the
        # detail is, coarse across the flat panels (its p95 is 80 mm). So the
        # question is never "how fine is this mesh on average", it is "does
        # this mesh have fine triangulation available ANYWHERE" -- because
        # that is where a shut line would have to live.
        # The generated mesh is marching-cubes UNIFORM: p5 3.18 mm against the
        # control's 0.53 mm, and a p95 of 32 mm against the control's 80 mm.
        # Narrow distribution, no fine tail, nowhere to put a panel gap.
        "local_mm": 2.0 * q[0],
        "adaptivity": float(q[4] / max(q[0], 1e-9)),
        "bands": bands, "extents_m": (ext * s),
    }


rows = [measure(p, a.length_m) for p in a.glb]
w = max(len(r["path"].split("/")[-1]) for r in rows)
print(f"{'mesh':{w}s}  {'faces':>8s}  {'edge mm p5':>10s} {'p25':>6s} "
      f"{'MEDIAN':>7s} {'p75':>6s} {'p95':>6s}  {'min feature':>11s}")
for r in rows:
    q = r["edge_mm"]
    print(f"{r['path'].split('/')[-1]:{w}s}  {r['faces']:8d}  {q[0]:10.2f} "
          f"{q[1]:6.2f} {q[2]:7.2f} {q[3]:6.2f} {q[4]:6.2f}  "
          f"{r['feature_mm']:8.2f} mm")

print(f"\nLOCAL capability -- 2 x p5 edge, i.e. the finest feature this mesh")
print(f"could carry WHERE IT IS DENSEST. This, not the median, is the test:")
print(f"a real asset is adaptive and puts its triangles where the detail is.")
print(f"required: shut line {SHUT_LINE_MM} mm, lamp recess {LAMP_RECESS_MM} mm")
for r in rows:
    n = r["path"].split("/")[-1]
    f = r["local_mm"]
    print(f"  {n:{w}s} finest {f:6.2f} mm  shut line: "
          f"{'CAN' if f <= SHUT_LINE_MM else 'CANNOT'}   lamp recess: "
          f"{'CAN' if f <= LAMP_RECESS_MM else 'CANNOT'}   "
          f"adaptivity p95/p5 = {r['adaptivity']:6.1f}x")
print("  adaptivity is the tell: a uniform marching-cubes mesh sits near 10x,")
print("  a hand-built asset in the hundreds. Low adaptivity means there is no")
print("  fine triangulation anywhere to carry a panel gap, at any median.")

print("\ndihedral spectrum (% of total edge LENGTH in each angle band)")
hdr = list(rows[0]["bands"])
print(f"{'mesh':{w}s}  " + "  ".join(f"{h:>9s}" for h in hdr))
for r in rows:
    print(f"{r['path'].split('/')[-1]:{w}s}  "
          + "  ".join(f"{r['bands'][h]:9.2f}" for h in hdr))
print("\n  noise is BROADBAND and low-angle; a real shut line is a narrow")
print("  high-angle population. A mesh with a fat 5-30 band and a thin 30-60")
print("  band is soft-with-noise, not soft-with-detail.")
