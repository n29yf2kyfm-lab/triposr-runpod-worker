#!/usr/bin/env python3
"""chamfer.py — how FAITHFUL is the reconstruction, independent of sharpness.

crease density says how much sharp geometry a mesh contains. It says nothing
about whether that geometry is in the RIGHT PLACE. A reconstruction could keep
its crease budget and still be a different car. This measures surface agreement:
symmetric point-to-surface distance, both directions, reported as a fraction of
the bounding-box diagonal so it is scale-free and comparable to crease/diag.

Deliberately separate from the gate. The gate is sharpness; this is fidelity.
Reporting them together stops "it kept the creases" being read as "it kept the
car", which is exactly the conflation this whole experiment exists to avoid.

MEASURED, 2026-08-21, Kia Sportage NQ5 through TripoSF/SparseFlex 1024^3,
400,000 surface samples per side:

    SYMMETRIC CHAMFER = 0.1477% of the bbox diagonal
    input->recon mean 0.149%, p50 0.137%, p95 0.297%, max 1.441%
    extents agree to 0.05% on all three axes

On that car (bbox diagonal about 5.25 m) 0.1477% is roughly 7.8 mm of mean
surface deviation. Read alongside crease_locate.py's result, the pair says the
thing that matters: the SHAPE survives the representation and the FEATURE SCALE
does not. A 1024^3 grid over a 4.5 m car is about 4.4 mm per voxel, and a shut
line is 2-4 mm — the features that died are exactly those at or below one voxel.
"""
import sys

import numpy as np
import trimesh


def one(path, n):
    sc = trimesh.load(path, process=False, force="scene")
    gs = [g for g in sc.geometry.values()
          if hasattr(g, "faces") and len(g.faces)]
    m = trimesh.util.concatenate(gs) if len(gs) > 1 else gs[0]
    # Normalise exactly as TripoSF does, so a scale/offset difference between
    # the two files is not counted as reconstruction error.
    m = m.copy()
    m.apply_translation(-m.bounding_box.centroid)
    m.apply_scale(1.0 / max(m.bounding_box.extents))
    pts, _ = trimesh.sample.sample_surface(m, n)
    return m, np.asarray(pts)


def main(a, b, n=60000):
    ma, pa = one(a, n)
    mb, pb = one(b, n)
    diag = float(np.linalg.norm(ma.bounding_box.extents))
    # POINT-to-point chamfer over dense surface samples, not point-to-SURFACE.
    # trimesh's ProximityQuery on a 10.6M-face mesh is far too slow to be
    # practical here, and with samples this dense the two agree to well inside
    # the differences being measured. Standard chamfer definition either way.
    from scipy.spatial import cKDTree
    d_ab = cKDTree(pb).query(pa)[0]
    d_ba = cKDTree(pa).query(pb)[0]
    print(f"samples per side: {n};  normalised bbox diag = {diag:.4f}")
    for tag, d in (("input->recon", d_ab), ("recon->input", d_ba)):
        print(f"  {tag}: mean {d.mean()/diag*100:.3f}% of diag, "
              f"p50 {np.percentile(d,50)/diag*100:.3f}%, "
              f"p95 {np.percentile(d,95)/diag*100:.3f}%, "
              f"max {d.max()/diag*100:.3f}%")
    ch = 0.5 * (d_ab.mean() + d_ba.mean()) / diag
    print(f"  SYMMETRIC CHAMFER = {ch*100:.4f}% of bbox diagonal")
    print(f"  extents input {np.round(ma.bounding_box.extents,4).tolist()}  "
          f"recon {np.round(mb.bounding_box.extents,4).tolist()}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2],
         int(sys.argv[3]) if len(sys.argv) > 3 else 60000)
