#!/usr/bin/env python3
"""crease_locate.py — are the reconstruction's deep creases the INPUT's creases,
or new noise that happens to score the same?

THE RIVAL THEORY THIS EXISTS TO TEST, written before running it. crease2 says
the recon retains 99.4% of the input's >=60 degree crease LENGTH. Two very
different worlds produce that number:

  (A) the representation genuinely preserved the shut lines, grille slats and
      lamp recesses — the creases are in the SAME PLACES; or
  (B) the representation eroded the real features AND added surface noise, and
      the two happen to cancel in a length total. CLAUDE.md's standing warning
      is exactly this: "the metric counts sharp geometry, not GOOD geometry",
      and it has already burned this project once (crease 43 -> 132 on a mesh
      that was a melted blob).

A length total cannot separate them. LOCATION can. So: sample points along every
deep-crease edge of both meshes and ask, for each recon crease point, how far it
is from the nearest INPUT crease point (and vice versa). Under (A) the two sets
lie on top of each other. Under (B) the recon's crease points scatter over
panels where the input has no crease at all.

Both meshes are normalised the same way (centre, max extent 1) so distances are
comparable and are reported as a percentage of the bounding-box diagonal.

MEASURED RESULT, 2026-08-21, Kia Sportage NQ5 through TripoSF/SparseFlex 1024^3
(the sharpest car in the catalogue, handed to a reconstruction VAE):

    deep-crease EDGE COUNT   input 35,180  ->  recon 210,572   (6.0x MORE)
    deep-crease TOTAL LENGTH input 136.8   ->  recon 136.0     (the SAME)
    recon crease -> nearest INPUT crease: 10.1% of length within 0.2% of diag,
        42.9% within 0.5%, 78.4% within 1.0%; median offset 0.568% of diag
    input crease -> nearest RECON crease: 31.3% / 66.3% / 87.1%; median 0.367%

Six times the edges carrying the same total length means each is a sixth as
long: the recon's deep creases are SHORT SCATTERED FRAGMENTS, not feature lines,
and the median one sits about 3 cm from the nearest real crease on a car whose
shut lines are 2-4 mm wide. crease2 reported "99.4% retention at 60 degrees" for
that mesh. It is a coincidence of totals — eroded features plus added noise —
and theory (B) is what actually happened. THE PRODUCTION RENDER AGREED: broken
dashed shut lines, badge gone, window surrounds torn.

So: NEVER report crease retention as feature preservation without this check.

Usage: crease_locate.py input.obj recon.glb [deg] [max_points]
"""
import sys

import numpy as np
import trimesh
from scipy.spatial import cKDTree


def crease_points(path, deg, cap):
    sc = trimesh.load(path, process=False, force="scene")
    gs = [g for g in sc.geometry.values()
          if hasattr(g, "faces") and len(g.faces)]
    m = trimesh.util.concatenate(gs) if len(gs) > 1 else gs[0]
    m = m.copy()
    m.apply_translation(-m.bounding_box.centroid)
    m.apply_scale(1.0 / max(m.bounding_box.extents))
    ang = np.degrees(np.abs(m.face_adjacency_angles))
    keep = (ang >= deg) & (ang <= 179.0)
    e = m.vertices[m.face_adjacency_edges[keep]]
    L = np.linalg.norm(e[:, 0] - e[:, 1], axis=1)
    mids = 0.5 * (e[:, 0] + e[:, 1])
    diag = float(np.linalg.norm(m.bounding_box.extents))
    if len(mids) > cap:                      # length-weighted, so long real
        p = L / L.sum()                      # creases are not out-voted by
        idx = np.random.default_rng(0).choice(  # a swarm of tiny noise edges
            len(mids), size=cap, replace=False, p=p)
        mids, L = mids[idx], L[idx]
    return mids, L, diag, int(keep.sum()), float(
        np.linalg.norm((m.vertices[m.face_adjacency_edges[keep]][:, 0] -
                        m.vertices[m.face_adjacency_edges[keep]][:, 1]),
                       axis=1).sum())


def main(a, b, deg=60.0, cap=200000):
    pa, la, diag, na, tota = crease_points(a, deg, cap)
    pb, lb, _, nb, totb = crease_points(b, deg, cap)
    print(f"deep-crease edges (>= {deg:g} deg):  input {na:,}  recon {nb:,}")
    print(f"total deep-crease length / diag:    input {tota/diag:.1f}  "
          f"recon {totb/diag:.1f}")
    ta, tb = cKDTree(pa), cKDTree(pb)
    d_b2a, _ = ta.query(pb)          # recon crease -> nearest input crease
    d_a2b, _ = tb.query(pa)          # input crease -> nearest recon crease
    for tag, d, w in (("recon crease -> nearest INPUT crease", d_b2a, lb),
                      ("input crease -> nearest RECON crease", d_a2b, la)):
        r = d / diag * 100.0
        # length-weighted, because what matters is how much CREASE LENGTH is
        # explained, not how many edges.
        wsum = w.sum()
        print(f"  {tag}:")
        for t in (0.2, 0.5, 1.0, 2.0):
            print(f"      within {t:>4.1f}% of diag: "
                  f"{100.0*w[r <= t].sum()/wsum:5.1f}% of length")
        print(f"      median {np.median(r):.3f}%  p90 {np.percentile(r,90):.3f}%")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2],
         float(sys.argv[3]) if len(sys.argv) > 3 else 60.0,
         int(sys.argv[4]) if len(sys.argv) > 4 else 200000)
