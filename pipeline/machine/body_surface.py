#!/usr/bin/env python3
"""body_surface.py — find the car's EXTERIOR BODY SURFACE by geometry, and weld
the whole car into one continuous surface so a repair cannot crack a seam.

TWO MEASURED FACTS ABOUT THIS CAR DRIVE THE WHOLE DESIGN, both established
before any repair was attempted and neither of them true of a normal catalogue
car.

FACT 1 — THE MATERIAL NAMES DO NOT DELIMIT THE BODY. On the Golf Mk8 master the
`interior` material is bound to the front bumper and the sills, and `interior`
is 660,134 faces spanning the FULL car bbox (4.276 x 1.447 x 1.778) — 67% of
the car. Two of the panels the surface gate names, "rocker/sill deformation"
and "rear bumper swelling", therefore live in a mesh called `interior`.
Selecting the body by material name repairs the wrong faces and misses the
named defects. So the body is selected by GEOMETRY: the exterior visible shell.

FACT 2 — THE SIX MESHES ARE ONE SURFACE, SPLIT BY LABEL. Measured coincident
vertices between geometries, at 1e-6 of car length:

        interior/carpaint 25,369    interior/glass 7,030    interior/rim 5,869
        interior/tyre      4,290    carpaint/glass 4,676    carpaint/tyre 1,072

Every mesh shares vertices with `interior`. These are not separate shells that
happen to touch; they are one continuous surface cut into six label submeshes,
with the border vertices DUPLICATED into each side. The consequence is hard:
moving `carpaint`'s copy of a shared vertex and not `interior`'s copy OPENS A
CRACK at 25,369 places. A per-geometry repair is therefore not merely
incomplete, it is destructive — which is why this module welds GLOBALLY, across
all six meshes at once, and scatters the result back to every duplicate.

HOW EXTERIOR IS DECIDED — OPENNESS, NOT NORMALS. Each face is asked how much of
the sphere it can see: rays are fired from its centroid in DIRS uniform
directions and the fraction that escape the car is its openness. A face on the
outer shell sees roughly a hemisphere; a face buried in the cabin sees almost
nothing.

The obvious cheaper test — cast one ray along the face normal and see if it
escapes — is WRONG on this car and would have been believed. Generated meshes
carry large patches of inverted normals (CLAUDE.md records 46% of body faces in
this Golf's lamp band facing inward, 28% strongly), so a normal-direction test
reports outer-shell faces as buried, and it does so in patches rather than at
random, which reads as a plausible region rather than as noise. Openness does
not consult the normal at all and is immune to that.

Run:
  python3 body_surface.py <car.glb> [--npz out.npz] [--dirs 32]
        [--open-thresh 0.10] [--debug-glb dbg.glb]
"""
import argparse
import json
import os
import time

import numpy as np
import trimesh

# Materials that are never a painted body panel, however they are positioned.
# This is used only to SUBTRACT from an already geometric selection, never to
# define it — see FACT 1.
NONPANEL_TOK = ("glass", "window", "windscreen", "screen", "tyre", "tire",
                "rubber", "lamp", "lens", "rim", "wheel", "brake", "caliper",
                "plate", "mirror_glass")


class Car:
    """The whole car, welded across meshes, with the map back to every
    geometry's own vertex array."""

    def __init__(self, path, tol_rel=1e-6):
        sc = trimesh.load(path, force="scene")
        self.scene = sc
        self.names, Vs, Fs, gid = [], [], [], []
        off = 0
        self.slices = {}
        # SORTED BY GEOMETRY NAME, never in scene-graph traversal order. A GLB
        # exported by trimesh comes back with its nodes in a different order
        # than it went in, so a traversal-ordered concatenation makes the
        # "same" car two different vertex arrays before and after a repair and
        # every index-wise comparison between them is then meaningless.
        order = []
        seen = set()
        for node in sc.graph.nodes_geometry:
            T, gn = sc.graph[node]
            if gn not in seen:
                seen.add(gn)
                order.append((gn, T))
        for gn, T in sorted(order, key=lambda kv: kv[0]):
            g = sc.geometry[gn]
            if not isinstance(g, trimesh.Trimesh) or len(g.faces) == 0:
                continue
            V = trimesh.transform_points(
                np.asarray(g.vertices, dtype=np.float64), T)
            F = np.asarray(g.faces, dtype=np.int64)
            self.slices[gn] = (off, off + len(V), len(self.names), T)
            self.names.append(gn)
            Vs.append(V)
            Fs.append(F + off)
            gid.append(np.full(len(F), len(self.names) - 1, dtype=np.int32))
            off += len(V)
        if not Vs:
            raise SystemExit(f"REFUSED: no geometry in {path}")
        self.V_all = np.concatenate(Vs)          # per-geometry vertex arrays,
        self.F_all = np.concatenate(Fs)          # concatenated, NOT welded
        self.face_geom = np.concatenate(gid)

        s = float(np.ptp(self.V_all, axis=0).max())
        key = np.round(self.V_all / (tol_rel * s)).astype(np.int64)
        _, first, inv = np.unique(key, axis=0, return_index=True,
                                  return_inverse=True)
        self.inv = inv                            # all-vertex -> welded id
        self.first = first                        # welded id -> a representative
        self.Vw = self.V_all[first]
        Fw = inv[self.F_all]
        keep = ((Fw[:, 0] != Fw[:, 1]) & (Fw[:, 1] != Fw[:, 2]) &
                (Fw[:, 0] != Fw[:, 2]))
        self.degenerate = int((~keep).sum())
        self.Fw = Fw[keep]
        self.keep = keep
        self.face_geom_w = self.face_geom[keep]
        self.mesh = trimesh.Trimesh(vertices=self.Vw, faces=self.Fw,
                                    process=False)
        self.scale = s

    @property
    def fingerprint(self):
        """Identifies the WELD, not the file. A face mask saved against one
        weld is meaningless against another, and the two are the same LENGTH,
        so a length check does not catch a stale mask — it would repair
        arbitrary faces and report a plausible number. Any saved mask carries
        this and is refused if it does not match."""
        import hashlib
        h = hashlib.sha256()
        h.update(np.ascontiguousarray(self.Fw, dtype=np.int64).tobytes())
        h.update(",".join(self.names).encode())
        return h.hexdigest()[:16]

    def rewelded_like(self, other):
        """This car's vertices, re-expressed in ANOTHER car's welded ordering.

        NEVER compare two independently welded cars index by index. The weld is
        `np.unique` over a QUANTISED COORDINATE KEY, so its output order is
        lexicographic in position — move a vertex and it takes a different slot
        in the welded array. Comparing base.Vw to variant.Vw elementwise
        therefore silently pairs unrelated vertices, and it does not look like
        an error: it looks like a 1.85 m displacement and a crease length of
        715,908 m, which reads as a catastrophic repair rather than as a
        catastrophic measurement. It cost one wrong verdict here on 2026-08-20.

        A repair that only MOVES vertices leaves every per-geometry vertex
        array the same length and in the same order, so the concatenated
        V_all arrays correspond 1:1 and the other car's `first` index is the
        correct re-weld.
        """
        if len(self.V_all) != len(other.V_all):
            raise ValueError(
                f"vertex counts differ ({len(self.V_all)} vs "
                f"{len(other.V_all)}): these are not the same topology")
        if self.names != other.names:
            raise ValueError(f"geometry order differs: {self.names} vs "
                             f"{other.names}")
        return self.V_all[other.first]

    def scatter(self, Vw_new):
        """Welded positions -> the full concatenated per-geometry array. Every
        duplicate of a welded vertex receives the SAME position, which is what
        keeps the six label submeshes sealed to each other."""
        return Vw_new[self.inv]

    def write(self, Vw_new, out_path, normals=None):
        V_all = self.scatter(Vw_new)
        sc = self.scene
        for gn, (a, b, gi, T) in self.slices.items():
            g = sc.geometry[gn]
            Ti = np.linalg.inv(T)
            g.vertices = trimesh.transform_points(V_all[a:b], Ti)
            if normals is not None:
                R = Ti[:3, :3]
                n = normals[a:b] @ R.T
                n /= np.linalg.norm(n, axis=1, keepdims=True).clip(1e-12)
                g.vertex_normals = n
        sc.export(out_path, include_normals=True)
        return out_path


def openness(mesh, dirs=32, eps_frac=2e-4, seed=0, verbose=True):
    """Fraction of DIRS uniform directions from which each face escapes.

    Fibonacci sphere directions rather than random: a random set clumps, and a
    clump biases every face in the same way, which is indistinguishable from a
    real result.
    """
    t0 = time.time()
    i = np.arange(dirs) + 0.5
    phi = np.arccos(1 - 2 * i / dirs)
    gold = np.pi * (1 + 5 ** 0.5)
    theta = gold * i
    D = np.stack([np.cos(theta) * np.sin(phi),
                  np.sin(theta) * np.sin(phi),
                  np.cos(phi)], axis=1)
    C = mesh.vertices[mesh.faces].mean(axis=1)
    eps = eps_frac * float(np.ptp(mesh.vertices, axis=0).max())
    try:
        from trimesh.ray.ray_pyembree import RayMeshIntersector
        rmi = RayMeshIntersector(mesh)
        backend = "embree"
    except Exception:
        rmi = mesh.ray
        backend = "trimesh(slow)"
    esc = np.zeros(len(C), dtype=np.int32)
    for k, d in enumerate(D):
        o = C + d * eps
        hit = rmi.intersects_any(o, np.tile(d, (len(C), 1)))
        esc += ~hit
        if verbose and (k + 1) % 8 == 0:
            print(f"    openness {k+1}/{dirs} dirs ({time.time()-t0:.0f}s)")
    op = esc / float(dirs)
    if verbose:
        print(f"  openness via {backend}: {dirs} dirs, {len(C)} faces, "
              f"{time.time()-t0:.0f}s;  median={np.median(op):.3f} "
              f"frac>0.10={np.mean(op>0.10):.3f} frac>0.25={np.mean(op>0.25):.3f}")
    return op


def nonpanel_face_mask(car):
    """Faces whose SOURCE material is structurally not a paint panel."""
    bad = np.zeros(len(car.names), dtype=bool)
    for i, n in enumerate(car.names):
        g = car.scene.geometry[n]
        mat = getattr(getattr(g, "visual", None), "material", None)
        mn = (getattr(mat, "name", None) or n or "").lower()
        bad[i] = any(t in mn for t in NONPANEL_TOK)
    return bad[car.face_geom_w], [car.names[i] for i in range(len(car.names))
                                  if bad[i]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("glb")
    ap.add_argument("--npz", default=None)
    ap.add_argument("--dirs", type=int, default=32)
    ap.add_argument("--open-thresh", type=float, default=0.10)
    ap.add_argument("--debug-glb", default=None)
    a = ap.parse_args()

    t0 = time.time()
    car = Car(a.glb)
    print(f"{a.glb}")
    print(f"  {len(car.names)} geometries {car.names}")
    print(f"  {len(car.V_all)} vertices -> {len(car.Vw)} welded "
          f"({len(car.V_all)-len(car.Vw)} duplicates removed), "
          f"{len(car.Fw)} faces, {car.degenerate} degenerate dropped")
    for gn, (s, e, gi, T) in car.slices.items():
        share = np.unique(car.inv[s:e])
        print(f"    {gn:12s} {e-s:7d} verts -> {len(share):7d} welded ids")

    op = openness(car.mesh, dirs=a.dirs)
    ext = op > a.open_thresh
    npm, npnames = nonpanel_face_mask(car)
    panel = ext & ~npm
    A = car.mesh.area_faces
    print(f"  exterior faces (openness>{a.open_thresh}): {ext.sum()} "
          f"({ext.mean()*100:.1f}%), area {A[ext].sum():.2f} m2")
    print(f"  non-panel materials {npnames}: {npm.sum()} faces")
    print(f"  EXTERIOR BODY PANEL: {panel.sum()} faces "
          f"({panel.mean()*100:.1f}%), area {A[panel].sum():.2f} m2")
    # how the panel set is distributed over the SOURCE meshes -- this is the
    # number that proves the name-based selection was wrong
    print("  panel faces by source mesh:")
    for i, n in enumerate(car.names):
        sel = panel & (car.face_geom_w == i)
        if sel.sum():
            print(f"    {n:12s} {sel.sum():7d} faces  "
                  f"{A[sel].sum():6.2f} m2  "
                  f"({sel.sum()/max((car.face_geom_w==i).sum(),1)*100:4.1f}% "
                  f"of that mesh)")

    if a.npz:
        np.savez_compressed(a.npz, openness=op, exterior=ext, panel=panel,
                            face_geom=car.face_geom_w,
                            fingerprint=np.array(car.fingerprint),
                            names=np.array(car.names, dtype=object))
        print(f"  wrote {a.npz}")
    if a.debug_glb:
        m = car.mesh.copy()
        col = np.zeros((len(m.faces), 4), dtype=np.uint8)
        col[:] = (40, 40, 46, 255)                 # hidden
        col[ext] = (150, 150, 155, 255)            # exterior, non-panel
        col[panel] = (225, 120, 40, 255)           # exterior body panel
        m.visual.face_colors = col
        m.export(a.debug_glb)
        print(f"  wrote {a.debug_glb}")
    print(f"  total {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
