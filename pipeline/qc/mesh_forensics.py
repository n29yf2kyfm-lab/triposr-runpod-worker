#!/usr/bin/env python3
"""mesh_forensics.py — tell a GENERATED mesh from an AUTHORED one, and say why.

Written 2026-08-14 while studying why every generator this project has tested
produces "melt": soft panels, no shut lines, blobby lamp recesses. The research
says the cause is the REPRESENTATION, not the model size — Hunyuan/TRELLIS
predict an occupancy or SDF field and extract the surface with Marching Cubes,
whose vertices are constrained to lie ON GRID EDGES. A vertex that must live on
a grid edge cannot sit on a crease, so a sharp feature is averaged away and the
surface staircases instead. Dual Contouring / FlexiCubes exist precisely because
of this (they place one free vertex INSIDE each cell).

That is a claim about our own files, so this measures it instead of quoting it.

MEASUREMENTS
  grid_score   fraction of vertices with >=2 coordinates landing within eps of a
               common lattice, maximised over plausible grid resolutions. This is
               the Marching-Cubes fingerprint: MC puts every vertex on a cell
               EDGE, so two of its three coordinates are exact lattice values and
               only the third is interpolated. An authored mesh has no such
               lattice and scores near the random baseline.
  grid_res     the resolution that best explains the vertices (should match the
               generator's octree_resolution when the fingerprint is real).
  dihedral     histogram of face-pair angles. An authored car is BIMODAL: large
               flat regions (near 0 deg) plus deliberate creases (shut lines,
               swage lines) above ~25 deg. MC output is unimodal — everything is
               slightly bent and nothing is truly sharp.
  crease_dens  edge length at dihedral 25-150 deg over bbox diagonal, the metric
               already used by curate_trainset.py. Kept here so one run reports
               both the CAUSE (grid) and the SYMPTOM (creases).
  tri_quality  aspect-ratio distribution. MC emits many slivers; artist meshes
               triangulated from quads are well-conditioned.
  regularity   share of vertices with valence 4 (a quad-grid signature) and 6
               (a uniform triangulation signature).

Usage:
    python3 pipeline/qc/mesh_forensics.py a.glb b.glb ...
Draco files must be decompressed first (`gltf-transform copy in.glb out.glb`);
this refuses placeholder-zero geometry loudly rather than scoring noise.
"""
import sys

import numpy as np
import trimesh


def grid_fingerprint(V, resolutions=range(64, 641, 16), eps_frac=0.02):
    """Fraction of vertices lying on a lattice, maximised over resolutions.

    KNOWN LIMITATION (council audit 2026-08-14): the lattice is anchored to the
    MESH's own min/max, but a generator's marching grid spans the generation
    BOUNDS (e.g. +-1.01), which the mesh never reaches — so scale and offset
    are both wrong and a real lattice can score at baseline. The sweep also
    steps by 16, so odd resolutions (380) are missed. A baseline score
    therefore means "no lattice DETECTED", never "no lattice exists". Verified
    the hard way: Hunyuan 2.1's default extractor IS classic marching cubes
    (surface_extractors.py, skimage measure.marching_cubes), yet our meshes
    score baseline here. Use sharp_share and the dihedral histogram as the
    load-bearing metrics; they measure the surface, not the extraction grid.
    """
    lo = V.min(0)
    span = (V.max(0) - lo).max()
    if span <= 0:
        return 0.0, 0
    best, best_n = 0.0, 0
    for n in resolutions:
        cell = span / n
        # distance of each coordinate to its nearest lattice line, in cells
        d = np.abs(((V - lo) / cell + 0.5) % 1.0 - 0.5)
        on = (d < eps_frac).sum(axis=1)          # coords sitting on a line
        score = float((on >= 2).mean())          # MC: >=2 of 3 are exact
        if score > best:
            best, best_n = score, n
    return best, best_n


def random_baseline(V, n, eps_frac=0.02):
    """What grid_fingerprint scores on the SAME point count, shuffled.

    Without this the absolute number means nothing: a dense mesh hits some
    lattice lines by chance. Any real fingerprint must beat this by a wide
    margin.
    """
    rng = np.random.default_rng(0)
    R = rng.random(V.shape) * (V.max(0) - V.min(0)) + V.min(0)
    cell = (V.max(0) - V.min(0)).max() / n
    d = np.abs(((R - R.min(0)) / cell + 0.5) % 1.0 - 0.5)
    return float(((d < eps_frac).sum(axis=1) >= 2).mean())


def dihedral_stats(m):
    ang = np.degrees(np.abs(m.face_adjacency_angles))
    edges = m.vertices[m.face_adjacency_edges]
    length = np.linalg.norm(edges[:, 0] - edges[:, 1], axis=1)
    diag = float(np.linalg.norm(m.bounds[1] - m.bounds[0]))
    sharp = (ang >= 25) & (ang <= 150)
    bins = [0, 5, 15, 25, 45, 90, 180]
    hist = [float(((ang >= bins[i]) & (ang < bins[i + 1])).mean()) for i in range(len(bins) - 1)]
    return {
        # sharp_share is the cleanest single discriminator found 2026-08-14:
        # the share of face pairs folded past 45 deg, i.e. edges that are a
        # DELIBERATE feature rather than surface curvature. Measured on real
        # files: authored catalogue car 18.5%, hand-authored reference 6.5%,
        # Hunyuan-generated car 0.9%, raw pre-decimation generated 0.3%. Unlike
        # crease_density it does not reward mesh density, so a coarse authored
        # car still beats a dense generated one.
        "sharp_share": float((ang >= 45).mean()),
        "crease_density": float(length[sharp].sum() / diag) if diag else 0.0,
        "median_dihedral": float(np.median(ang)),
        "p95_dihedral": float(np.percentile(ang, 95)),
        "hist_0_5_15_25_45_90_180": [round(h, 3) for h in hist],
    }


def tri_quality(m):
    """Aspect ratio = longest edge / (2 * inradius). 1.0 is equilateral."""
    tri = m.vertices[m.faces]
    a = np.linalg.norm(tri[:, 1] - tri[:, 0], axis=1)
    b = np.linalg.norm(tri[:, 2] - tri[:, 1], axis=1)
    c = np.linalg.norm(tri[:, 0] - tri[:, 2], axis=1)
    s = (a + b + c) / 2
    area = np.sqrt(np.maximum(s * (s - a) * (s - b) * (s - c), 1e-24))
    inr = area / np.maximum(s, 1e-12)
    ar = np.maximum.reduce([a, b, c]) / np.maximum(2 * inr, 1e-12)
    return {
        "aspect_median": float(np.median(ar)),
        "aspect_p95": float(np.percentile(ar, 95)),
        "slivers_gt10": float((ar > 10).mean()),
    }


def valence(m):
    counts = np.bincount(m.faces.reshape(-1), minlength=len(m.vertices))
    return {
        "valence6_share": float((counts == 6).mean()),
        "valence4_share": float((counts == 4).mean()),
        "valence_median": float(np.median(counts)),
    }


def analyse(path):
    m = trimesh.load(path, force="mesh")
    V = np.asarray(m.vertices, dtype=np.float64)
    if len(V) == 0 or not np.any(V):
        raise ValueError(f"{path}: all-zero vertices — Draco placeholder. "
                         "Decompress first: gltf-transform copy in.glb out.glb")
    score, n = grid_fingerprint(V)
    out = {
        "file": path.split("/")[-1],
        "verts": int(len(V)),
        "faces": int(len(m.faces)),
        "grid_score": round(score, 3),
        "grid_res": n,
        "grid_baseline": round(random_baseline(V, n), 3) if n else 0.0,
    }
    out.update({k: (round(v, 4) if isinstance(v, float) else v)
                for k, v in dihedral_stats(m).items()})
    out.update({k: round(v, 3) for k, v in tri_quality(m).items()})
    out.update({k: round(v, 3) for k, v in valence(m).items()})
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    rows = []
    for p in sys.argv[1:]:
        try:
            rows.append(analyse(p))
        except Exception as e:                                   # noqa: BLE001
            print(f"{p}: FAILED {e}")
    hdr = ["file", "verts", "faces", "sharp_share", "grid_score", "grid_baseline",
           "crease_density", "median_dihedral", "aspect_median", "valence6_share"]
    print(" | ".join(f"{h:>14s}" for h in hdr))
    for r in rows:
        print(" | ".join(f"{str(r.get(h, '')):>14s}" for h in hdr))
    print()
    for r in rows:
        print(f"{r['file']}: dihedral histogram [0-5,5-15,15-25,25-45,45-90,90-180] "
              f"= {r['hist_0_5_15_25_45_90_180']}")
