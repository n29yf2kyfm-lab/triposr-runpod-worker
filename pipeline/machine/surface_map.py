#!/usr/bin/env python3
"""surface_map.py — paint sigma_theta onto the car, so the number has a place.

WHY. The lam sweep on the Golf Mk8 showed the fairing removing WAVINESS
(sigma at 80 mm: flank -31%, bonnet -27%) while barely touching ROUGHNESS
(sigma at 25 mm: -2% overall, and the roof did not move at all). A summary
number cannot say whether that residual roughness is:

  H1  genuine per-vertex chatter spread evenly over the panels,
  H2  an artefact of the METRIC — a 25 mm neighbourhood spanning two of the
      parallel shells this generated body is built from, so the quadric is
      fitted through two surfaces at once and the error is booked against the
      visible one,
  H3  concentrated in a few zones (fascia melt, arch lips, mirror) while the
      large panels are actually acceptable.

Each hypothesis makes a DIFFERENT PICTURE, which is what makes this a probe and
not a confirmation: H1 paints the panels evenly warm, H2 paints thin lines
along shell borders, H3 paints isolated blobs on an otherwise cool car. A probe
that could only show one of them would prove nothing — this project has already
paid for a ray probe that confirmed its author's own hypothesis while the
render falsified it.

The map is exported as face colours on a GLB and rendered through the SAME
locked cameras as the clay and zebra passes, so the hot regions can be laid
directly beside the shattered reflections they are supposed to explain.

Colour scale is stated on every run and is linear from 0 to --hot degrees:
  deep blue 0 .. cyan .. green .. yellow .. red >= hot.
Faces outside the measured set are painted dark grey, so "not measured" can
never be misread as "measured and good".

Run:
  python3 surface_map.py <car.glb> --select sel.npz [--radius 0.025]
        [--hot 6.0] [--out map.glb] [--npy theta.npy] [--layer-report]
"""
import argparse
import json
import os
import sys

import numpy as np
import trimesh

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import body_surface as bs             # noqa: E402
import surface_metric as sm           # noqa: E402


def theta_per_face(mesh, radius, mask, max_faces=10 ** 9):
    """Per-face slope error in degrees, NaN where undetermined.

    surface_metric.slope_error returns aggregate statistics; here the per-face
    values are needed, so the fit is re-run with the array kept. Same maths,
    same constants — imported rather than reimplemented so the map and the
    number can never drift apart.
    """
    C = mesh.vertices[mesh.faces].mean(axis=1)
    N = mesh.face_normals
    A = mesh.area_faces
    from scipy.spatial import cKDTree
    idx = np.where(mask)[0]
    tree = cKDTree(C)
    k = min(sm.MAX_NBRS, len(C))
    theta = np.full(len(C), np.nan)
    CH = max(1, int(4e7 / (k * 8 * 12)))
    for s in range(0, len(idx), CH):
        ii = idx[s:min(s + CH, len(idx))]
        d, nb = tree.query(C[ii], k=k, workers=-1)
        ok = (d <= radius) & (nb < len(C))
        ok[:, 0] = True
        P = C[nb] - C[ii][:, None, :]
        n0 = N[ii]
        ok &= np.einsum("mkj,mj->mk", N[nb], n0) > sm.NORMAL_AGREE
        tmp = np.tile(np.array([1.0, 0.0, 0.0]), (len(ii), 1))
        tmp[np.abs(n0[:, 0]) > 0.9] = np.array([0.0, 1.0, 0.0])
        ex = np.cross(n0, tmp)
        ex /= np.linalg.norm(ex, axis=1, keepdims=True).clip(1e-12)
        ey = np.cross(n0, ex)
        x = np.einsum("mkj,mj->mk", P, ex)
        y = np.einsum("mkj,mj->mk", P, ey)
        z = np.einsum("mkj,mj->mk", P, n0)
        r = np.sqrt(x * x + y * y).clip(0, radius)
        w = A[nb] * (1.0 - r / radius) ** 2 * ok
        cnt = ok.sum(1)
        B = np.stack([x * x, x * y, y * y, x, y, np.ones_like(x)], axis=-1)
        Bw = B * w[..., None]
        AtA = np.einsum("mki,mkj->mij", Bw, B)
        Atb = np.einsum("mki,mk->mi", Bw, z)
        tr = np.trace(AtA, axis1=1, axis2=2)
        AtA[:, np.arange(6), np.arange(6)] += (1e-9 * tr + 1e-30)[:, None]
        good = cnt >= sm.MIN_NBRS
        if good.any():
            coef = np.linalg.solve(AtA[good], Atb[good][..., None])[..., 0]
            out = np.full(len(ii), np.nan)
            out[good] = np.degrees(np.arctan(np.hypot(coef[:, 3], coef[:, 4])))
            theta[ii] = out
    return theta


def layer_report(mesh, radius, mask, theta):
    """Test H2 directly: is a hot face one whose neighbourhood spans TWO
    surfaces? For each measured face, measure the spread of neighbour offsets
    ALONG its own normal. On a single sheet that spread is a fraction of a
    millimetre; where a second shell sits a few millimetres behind, it jumps.
    """
    from scipy.spatial import cKDTree
    C = mesh.vertices[mesh.faces].mean(axis=1)
    N = mesh.face_normals
    idx = np.where(mask & np.isfinite(theta))[0]
    tree = cKDTree(C)
    k = min(sm.MAX_NBRS, len(C))
    spread = np.full(len(C), np.nan)
    CH = max(1, int(4e7 / (k * 8 * 12)))
    for s in range(0, len(idx), CH):
        ii = idx[s:min(s + CH, len(idx))]
        d, nb = tree.query(C[ii], k=k, workers=-1)
        ok = (d <= radius) & (nb < len(C))
        ok[:, 0] = True
        n0 = N[ii]
        ok &= np.einsum("mkj,mj->mk", N[nb], n0) > sm.NORMAL_AGREE
        z = np.einsum("mkj,mj->mk", C[nb] - C[ii][:, None, :], n0)
        zz = np.where(ok, z, np.nan)
        spread[ii] = np.nanmax(zz, axis=1) - np.nanmin(zz, axis=1)
    v = spread[idx]
    t = theta[idx]
    print("\n=== H2 TEST: does the metric's neighbourhood span two shells? ===")
    print(f"  normal-direction spread of the fitted neighbourhood, mm:")
    for p in (50, 75, 90, 99):
        print(f"    p{p:<3d} {np.nanpercentile(v,p)*1000:8.2f} mm")
    lo = v < np.nanpercentile(v, 50)
    hi = v > np.nanpercentile(v, 90)
    print(f"  sigma on faces with a THIN neighbourhood (<p50 spread): "
          f"{np.sqrt(np.nanmean(t[lo]**2)):.3f} deg  (n={lo.sum()})")
    print(f"  sigma on faces with a THICK neighbourhood (>p90 spread): "
          f"{np.sqrt(np.nanmean(t[hi]**2)):.3f} deg  (n={hi.sum()})")
    print("  If the thin-neighbourhood figure is already high, the roughness is"
          "\n  REAL surface chatter (H1/H3) and not a layering artefact (H2).")
    return spread


def zone_report(mesh, mask, theta, feat):
    """Split the panel into FIELD and APERTURE-TRANSITION, and score each.

    The heat map on the Golf Mk8 master showed the error is not spread over the
    panels: the hottest 5% of faces carry 70% of the squared-slope energy, and
    they lie in bands along shut lines, window surrounds, arch lips and bumper
    edges, while the door skin, bonnet centre and roof centre are cool. Two of
    the gate's acceptance criteria map onto exactly that split —

        "no broad dents or scan noise"                 -> the FIELD
        "clean edge flow around apertures and gaps"    -> the TRANSITION

    — so reporting one blended number for the body hides which of the two is
    failing, and would let a real improvement in one be cancelled by the other.

    Distance is measured in FACE RINGS from the nearest feature edge rather than
    in millimetres, because what matters is how many rows of triangles the
    transition occupies: on a real car a shut line is crisp within a ring or
    two, and on this one it ramps over many.
    """
    import scipy.sparse as sp
    from scipy.sparse.csgraph import dijkstra
    adj = mesh.face_adjacency
    n = len(mesh.faces)
    g = sp.coo_matrix((np.ones(len(adj)), (adj[:, 0], adj[:, 1])), shape=(n, n))
    g = (g + g.T).tocsr()
    seeds = np.where(feat)[0]
    if len(seeds) == 0:
        print("  no feature faces; zone split not meaningful")
        return None
    # multi-source BFS via dijkstra on the unit-weight face graph, from a
    # subsample of seeds (the full set is every feature face and the distance
    # to the nearest is unchanged by thinning a dense band)
    rng = np.random.default_rng(0)
    ss = seeds if len(seeds) < 4000 else rng.choice(seeds, 4000, replace=False)
    d = dijkstra(g, directed=False, indices=ss, unweighted=True, min_only=True)
    A = mesh.area_faces
    fin = mask & np.isfinite(theta)
    print("\n=== ZONE SPLIT: field vs aperture transition ===")
    print(f"  {'rings from a feature':<24s} {'faces':>8s} {'area m2':>9s} "
          f"{'sigma':>8s} {'share of energy':>16s}")
    tot_e = (A[fin] * theta[fin] ** 2).sum()
    bands = [(0, 2), (3, 5), (6, 10), (11, 10 ** 6)]
    out = {}
    for lo, hi in bands:
        sel = fin & (d >= lo) & (d <= hi)
        if sel.sum() == 0:
            continue
        s = float(np.sqrt((A[sel] * theta[sel] ** 2).sum() / A[sel].sum()))
        e = float((A[sel] * theta[sel] ** 2).sum() / max(tot_e, 1e-30))
        lbl = f"{lo}-{hi}" if hi < 10 ** 5 else f"{lo}+"
        print(f"  {lbl:<24s} {int(sel.sum()):8d} {A[sel].sum():9.2f} "
              f"{s:8.3f} {e*100:15.1f}%")
        out[lbl] = dict(faces=int(sel.sum()), area_m2=round(A[sel].sum(), 3),
                        sigma=round(s, 4), energy_share=round(e, 4))
    return out


def ramp(t, hot):
    """blue -> cyan -> green -> yellow -> red, linear in 0..hot."""
    x = np.clip(np.nan_to_num(t, nan=0.0) / max(hot, 1e-9), 0, 1)
    stops = np.array([[0.05, 0.10, 0.55], [0.05, 0.75, 0.85],
                      [0.15, 0.80, 0.20], [0.98, 0.90, 0.10],
                      [0.90, 0.10, 0.05]])
    pos = x * (len(stops) - 1)
    i = np.clip(pos.astype(int), 0, len(stops) - 2)
    f = (pos - i)[:, None]
    return stops[i] * (1 - f) + stops[i + 1] * f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("glb")
    ap.add_argument("--select", required=True)
    ap.add_argument("--radius", type=float, default=0.025)
    ap.add_argument("--hot", type=float, default=6.0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--npy", default=None)
    ap.add_argument("--layer-report", action="store_true")
    ap.add_argument("--zones", action="store_true")
    ap.add_argument("--baseline", default=None,
                    help="master glb; score this variant in ITS weld frame")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    car = bs.Car(a.glb)
    sel = np.load(a.select, allow_pickle=True)
    panel = sel["panel"]
    if a.baseline:
        # A REPAIRED file welds in a DIFFERENT ORDER from its own baseline --
        # the weld is np.unique over a quantised coordinate key, so moving a
        # vertex moves its slot -- and its fingerprint therefore never matches
        # the selection built on the master. That is the fingerprint guard
        # doing its job, not a false alarm: the mask really is invalid against
        # this file's own weld. The fix is to score the variant IN THE
        # BASELINE'S FRAME, exactly as surface_score.py does, so the mask, the
        # face indices and the map all refer to the same faces on both sides.
        base = bs.Car(a.baseline)
        if str(sel.get("fingerprint")) != base.fingerprint:
            raise SystemExit(f"REFUSED: selection fingerprint "
                             f"{sel.get('fingerprint')} != baseline "
                             f"{base.fingerprint}")
        V = car.rewelded_like(base)
        mesh = trimesh.Trimesh(vertices=V, faces=base.Fw, process=False)
        # THE FEATURE MASK COMES FROM THE BASELINE TOO, not from this file.
        # A repair changes dihedral angles, so a variant that recomputes its own
        # feature mask CHANGES ITS OWN SCOREBOARD: softening an edge below the
        # 25 deg threshold promotes it from "excluded feature" to "scored
        # panel". Measured on this Golf, that alone moved the scored set from
        # 142,371 to 152,784 faces -- 10,413 newly included faces, every one of
        # them a former feature and therefore among the worst on the car -- and
        # made a real improvement read as no change at all. Same trap as
        # surface_score.py exists to avoid.
        feat_src = base.mesh
        print(f"  scored in the frame of {os.path.basename(a.baseline)} "
              f"(faces AND feature mask both from the baseline)")
    else:
        if str(sel.get("fingerprint")) != car.fingerprint:
            raise SystemExit(f"REFUSED: selection fingerprint "
                             f"{sel.get('fingerprint')} != {car.fingerprint}. "
                             f"If this is a REPAIRED file, pass --baseline "
                             f"<master.glb> so it is scored on the master's "
                             f"faces.")
        mesh = car.mesh
        feat_src = mesh
    feat = sm.feature_mask(feat_src)
    mask = panel & ~feat
    print(f"{a.glb}: mapping sigma_theta at {a.radius*1000:.0f}mm over "
          f"{int(mask.sum())} faces")
    th = theta_per_face(mesh, a.radius, mask)
    fin = np.isfinite(th) & mask
    A = mesh.area_faces
    print(f"  measured {int(fin.sum())} faces; area-weighted rms "
          f"{np.sqrt((A[fin]*th[fin]**2).sum()/A[fin].sum()):.3f} deg")
    for p in (50, 75, 90, 95, 99):
        print(f"    p{p:<3d} {np.nanpercentile(th[fin],p):7.3f} deg")
    # how concentrated is the error? H1 predicts the top decile carries ~ its
    # share of the energy; H3 predicts it carries most of it.
    e = A[fin] * th[fin] ** 2
    order = np.argsort(-th[fin])
    cum = np.cumsum(e[order]) / e.sum()
    for frac in (0.05, 0.10, 0.25, 0.50):
        n = int(frac * len(order))
        print(f"    hottest {frac*100:4.0f}% of faces carry "
              f"{cum[max(n-1,0)]*100:5.1f}% of the squared-slope energy")

    zones = None
    if a.zones:
        zones = zone_report(mesh, mask, th, feat)
    if a.layer_report:
        layer_report(mesh, a.radius, mask, th)
    if a.json:
        import json as _j
        with open(a.json, "w") as fh:
            _j.dump(dict(file=os.path.basename(a.glb), radius=a.radius,
                         rms=float(np.sqrt((A[fin]*th[fin]**2).sum()/A[fin].sum())),
                         n=int(fin.sum()), zones=zones), fh, indent=1)
        print("  wrote", a.json)

    if a.npy:
        np.save(a.npy, th)
        print("  wrote", a.npy)
    if a.out:
        col = np.zeros((len(mesh.faces), 4), dtype=np.uint8)
        col[:] = (55, 55, 60, 255)
        c = ramp(th[fin], a.hot)
        col[fin, :3] = (np.clip(c, 0, 1) * 255).astype(np.uint8)
        m = mesh.copy()
        m.visual.face_colors = col
        m.export(a.out)
        print(f"  wrote {a.out}  (scale: blue 0 deg -> red {a.hot} deg, "
              f"dark grey = not measured)")


if __name__ == "__main__":
    main()
