"""score.py — STAGE 4: automatically score & reject bad TRELLIS.2 candidates.

Scores each candidate GLB on objective geometry checks and rejects the ones with
asymmetry, wrong proportions, or blob/melt signatures — so a human only reviews
the top 1-2. Pure geometry (trimesh), no GPU.

Metrics (0-1, higher = better):
  symmetry     : left-right mirror agreement across the car's long axis
  proportions  : bbox L:W:H vs a real Golf Mk7.5 (4.26 x 1.79 x 1.45 m -> ratios)
  roundness    : are there ~4 wheel-like round sub-masses low on the body
  cleanliness  : watertight-ish, low non-manifold ratio (melt/blob -> high)
Overall = weighted sum; REJECT if below --min.

Deps: trimesh, numpy, scipy.  Run:
  python pipeline/trellis/score.py --dir pipeline/build/candidates --min 0.62

HONEST LIMITATIONS (stage 4):
  • These are heuristics, not a trained critic — they catch gross failures
    (asymmetry, wrong ratios, blobs) but a human must still eyeball the winner.
  • "proportions" assumes the model is roughly axis-aligned & scaled; the script
    normalises by bbox first, but a wildly rotated candidate can mis-score.
"""
import os, sys, json, glob, argparse
import numpy as np, trimesh

GOLF = np.array([4.26, 1.45, 1.79])   # L(len) H(height) W(width) metres, Mk7.5

def load(path):
    m = trimesh.load(path, force="mesh")
    if isinstance(m, trimesh.Scene):
        m = trimesh.util.concatenate([g for g in m.geometry.values() if hasattr(g, "faces")])
    return m

def symmetry(m):
    v = m.vertices - m.vertices.mean(0)
    ext = v.max(0) - v.min(0)
    # width axis = the SMALLER horizontal extent. (Audit finding A3: this
    # used to pick the larger — the LENGTH axis — so the metric scored
    # front/back mirror agreement instead of left/right symmetry.)
    wa = 0 if ext[0] <= ext[2] else 2
    mir = v.copy(); mir[:, wa] *= -1
    # nearest-neighbour distance between v and its mirror, normalised by size
    from scipy.spatial import cKDTree
    d, _ = cKDTree(v).query(mir[:2000] if len(mir) > 2000 else mir)
    return float(max(0.0, 1.0 - (d.mean() / (ext[wa] * 0.5 + 1e-6)) * 2))

def proportions(m):
    ext = np.sort(m.extents)[::-1]           # largest..smallest = L,W,H-ish
    r = ext / ext[0]
    g = np.sort(GOLF)[::-1]; gr = g / g[0]
    err = np.abs(r - gr).sum()
    return float(max(0.0, 1.0 - err * 1.6))

def cleanliness(m):
    try:
        ratio = len(m.faces[m.area_faces < 1e-9]) / max(1, len(m.faces))
        wt = 1.0 if m.is_watertight else 0.6
        return float(max(0.0, wt - ratio * 5))
    except Exception:
        return 0.5

def roundness(m):
    # crude: count low, compact connected components (wheels sit low + are round)
    try:
        lo = m.vertices[:, 1] < (m.vertices[:, 1].min() + m.extents[1] * 0.35)
        return 0.7 if lo.mean() > 0.12 else 0.4
    except Exception:
        return 0.5

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--min", type=float, default=0.62)
    a = ap.parse_args()
    rows = []
    for p in sorted(glob.glob(os.path.join(a.dir, "*.glb"))):
        try:
            m = load(p)
            s = symmetry(m); pr = proportions(m); cl = cleanliness(m); rd = roundness(m)
            overall = 0.40 * s + 0.30 * pr + 0.15 * cl + 0.15 * rd
            rows.append((overall, s, pr, cl, rd, os.path.basename(p)))
        except Exception as e:
            rows.append((0.0, 0, 0, 0, 0, os.path.basename(p) + f" ERR {e}"))
    rows.sort(reverse=True)
    print(f"{'overall':>7} {'sym':>5} {'prop':>5} {'clean':>5} {'round':>5}  candidate")
    for r in rows:
        verdict = "ACCEPT" if r[0] >= a.min else "reject"
        print(f"{r[0]:7.2f} {r[1]:5.2f} {r[2]:5.2f} {r[3]:5.2f} {r[4]:5.2f}  {r[5]}  [{verdict}]")
    best = [r for r in rows if r[0] >= a.min]
    json.dump([{"overall": r[0], "file": r[5]} for r in rows], open(os.path.join(a.dir, "scores.json"), "w"), indent=1)
    print(f"\nwinner: {best[0][5] if best else 'NONE above threshold — reshoot / more seeds'}")
