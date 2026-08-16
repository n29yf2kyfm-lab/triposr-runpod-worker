#!/usr/bin/env python3
"""surface_clean.py — edge-preserving surface denoise for generated car meshes.

The foil shimmer on Pixal panels is high-frequency NORMAL noise. Global
positional smoothing (Taubin) was measured to destroy creases with the noise
(145->36 crease density in 8 iters) — so this is NOT that. It is bilateral
NORMAL filtering (Zheng/Sun class): each face normal is replaced by a
weighted average of its neighbours where the weight decays with normal
DIFFERENCE, so neighbours across a crease contribute ~nothing and the crease
survives while in-panel noise averages out. Vertices are then updated to
match the filtered normals (small, bounded moves).

Fragment-soup safety: Pixal meshes are hundreds of shells whose border
vertices are DUPLICATED. Filtering per-shell would move each copy
differently and crack every seam. So faces are re-indexed onto WELDED
vertex ids first (positions rounded), the filter runs on the welded
topology, and each welded vertex's displacement is written back to all of
its duplicates — seams stay sealed by construction.

Texture safety: vertices move, UVs and topology do not. The scene is
exported with its original per-geometry materials untouched, so the baked
texture survives.

Prints crease density (dihedral>30deg edge length / bbox diag) before and
after — but the RENDER is the arbiter, per the standing rule.

Run: python3 surface_clean.py <in.glb> <out.glb> [iters_n] [iters_v] [sigma]
"""
import sys
import numpy as np
import trimesh

INP, OUT = sys.argv[1], sys.argv[2]
IT_N = int(sys.argv[3]) if len(sys.argv) > 3 else 8      # normal-filter iters
IT_V = int(sys.argv[4]) if len(sys.argv) > 4 else 12     # vertex-update iters
SIGMA = float(sys.argv[5]) if len(sys.argv) > 5 else 0.35  # normal-diff sigma

sc = trimesh.load(INP, force="scene")
geoms = list(sc.geometry.items())
verts_l, faces_l, off = [], [], 0
spans = []
for name, gm in geoms:
    verts_l.append(gm.vertices.copy())
    faces_l.append(gm.faces + off)
    spans.append((off, off + len(gm.vertices)))
    off += len(gm.vertices)
V = np.vstack(verts_l)
Fc = np.vstack(faces_l)
print(f"{len(geoms)} geometries, {len(V)} verts, {len(Fc)} faces")

# ---- weld map: duplicated border verts share one welded id
scale = float(np.ptp(V, axis=0).max())
key = np.round(V / (1e-6 * scale)).astype(np.int64)
_, weld, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
Vw = V[weld]
Fw = inv[Fc]
Fw = Fw[(Fw[:, 0] != Fw[:, 1]) & (Fw[:, 1] != Fw[:, 2]) & (Fw[:, 0] != Fw[:, 2])]
mw = trimesh.Trimesh(vertices=Vw, faces=Fw, process=False)
print(f"welded: {len(Vw)} verts ({len(V) - len(Vw)} duplicates sealed)")


def crease_density(mesh):
    ang = mesh.face_adjacency_angles
    sharp = ang > np.radians(30)
    e = mesh.face_adjacency_edges[sharp]
    ln = np.linalg.norm(mesh.vertices[e[:, 0]] - mesh.vertices[e[:, 1]], axis=1)
    return float(ln.sum() / np.linalg.norm(mesh.extents))


print(f"crease density BEFORE: {crease_density(mw):.1f}")

adj = mw.face_adjacency                      # (E,2) face pairs
n = mw.face_normals.copy()
area = mw.area_faces.copy()
for it in range(IT_N):
    acc = n * area[:, None]                  # self term, area-weighted
    wsum = area.copy()
    dot = np.einsum("ij,ij->i", n[adj[:, 0]], n[adj[:, 1]]).clip(-1, 1)
    w = np.exp(-(1 - dot) ** 2 / (2 * SIGMA ** 2))
    wa = w * area[adj[:, 1]]
    wb = w * area[adj[:, 0]]
    np.add.at(acc, adj[:, 0], n[adj[:, 1]] * wa[:, None])
    np.add.at(acc, adj[:, 1], n[adj[:, 0]] * wb[:, None])
    np.add.at(wsum, adj[:, 0], wa)
    np.add.at(wsum, adj[:, 1], wb)
    n = acc / wsum[:, None]
    n /= np.linalg.norm(n, axis=1, keepdims=True).clip(1e-12)

# ---- vertex update to match filtered normals (Sun et al. iteration)
Vc = Vw.copy()
deg = np.zeros(len(Vc))
np.add.at(deg, Fw.ravel(), 1)
deg = deg.clip(1)
for it in range(IT_V):
    fc = Vc[Fw].mean(1)                      # face centroids
    disp = np.zeros_like(Vc)
    for k in range(3):
        vidx = Fw[:, k]
        d = np.einsum("ij,ij->i", n, fc - Vc[vidx])
        np.add.at(disp, vidx, n * d[:, None])
    Vc += disp / (3 * deg[:, None])

moved = np.linalg.norm(Vc - Vw, axis=1)
print(f"vertex moves: mean {moved.mean()*1000:.2f} p99 "
      f"{np.percentile(moved, 99)*1000:.2f} max {moved.max()*1000:.2f} "
      f"(per-mille of unit; diag {np.linalg.norm(mw.extents):.2f})")
m2 = trimesh.Trimesh(vertices=Vc, faces=Fw, process=False)
print(f"crease density AFTER:  {crease_density(m2):.1f}")

# ---- write displacements back through the weld map, per geometry
Vnew = Vc[inv]
for (name, gm), (a, b) in zip(geoms, spans):
    gm.vertices = Vnew[a:b]
sc.export(OUT)
import os
print("wrote", OUT, os.path.getsize(OUT), "bytes")
