#!/usr/bin/env python3
"""surface_metric.py — a CALIBRATED Class-A surface-quality metric.

WHY NOT crease_density. `shut_lines.py` took crease density from 35.9 to 126.7
by engraving texture NOISE all over a door and it read as a triumph. Crease
density counts SHARP geometry, not GOOD geometry, and it moves the same
direction for a shut line and for a scan artefact. It cannot be the verdict on
a surface-repair gate, so this file exists.

WHAT THE OWNER ACTUALLY COMPLAINED ABOUT is a zebra render whose reflection
lines SHATTER instead of running continuously. That is not a statement about
positions; it is a statement about the NORMAL FIELD. A mirror reflection is
r = 2(n.v)n - v, so for a fixed viewer the zebra band pattern is literally an
iso-contour set of a smooth function of n. Bands stay continuous exactly when n
varies smoothly over the panel, and they shatter exactly when it does not.
So the metric measures the normal field, at a stated spatial scale.

THE METRIC — sigma_theta(R), "slope error", in DEGREES.
For every panel face f with centroid c and unit normal n:
  1. collect neighbouring face centroids within radius R (plus a normal-
     agreement filter, so the far flank of a thin panel cannot join the fit),
  2. build a local frame whose +Z is n, and least-squares fit the quadric
        h(x, y) = a x^2 + b xy + c y^2 + d x + e y + g
     to the neighbours, area-weighted with a smooth radial kernel,
  3. the fitted surface's slope at the origin is (d, e); the face's OWN normal
     is (0, 0, 1) in this frame BY CONSTRUCTION, so the angle between the face
     and the smooth surface its neighbourhood defines is exactly
        theta = atan(sqrt(d^2 + e^2)).
sigma_theta(R) is the area-weighted RMS of theta over panel faces.

The quadric matters. A fit to a PLANE would charge a car for being curved: a
roof of radius 2 m read at R = 25 mm scores ~0.36 deg of honest crown. The
quadric absorbs constant curvature, so what is left is the deviation from
"manufactured curvature" — which is the owner's phrase for the thing being
measured.

TWO SCALES, because the owner named two different defects.
  R = 25 mm  ROUGHNESS band — triangle chatter, scan grain, faceting. This is
             the band that shatters a zebra line.
  R = 80 mm  WAVINESS band — broad dents, bonnet undulation, panel swelling.
             A dent shallow enough to hide from the 25 mm fit still tilts the
             80 mm one.
(An ISO-4287 form/waviness/roughness split, in the only band-limited form
available on an irregular triangle mesh.)

PANEL RESTRICTION, and why it cannot be gamed. Shut lines, aperture edges and
the swage crease are SUPPOSED to be sharp: including them would make a car with
crisp panel gaps score worse than one with none, i.e. exactly backwards. So
faces within RING rings of an edge whose dihedral exceeds CREASE_DEG are
excluded and the excluded fraction is REPORTED. Deleting the creases to improve
the score is therefore visible in `panel_frac`, and destroying them is visible
in `crease_len_m`, which is printed beside the metric for that reason.

CALIBRATION. A metric that has never met a real car is a vibe with a decimal
point. `--calibrate` runs the same measurement over reference cars from this
catalogue and prints their distribution, so a generated car's number can be
read as "inside the real-car band" or "outside it" rather than as a bare float.
Cars are normalised to a common length first (default 4.3 m) because R is a
PHYSICAL radius and the catalogue is modelled in metres, centimetres and
millimetres indiscriminately.

Run:
  python3 surface_metric.py <car.glb> [--region all|roof|flank|bonnet|upper]
                            [--radii 0.025,0.080] [--json out.json]
                            [--geom carpaint] [--max-faces 250000]
  python3 surface_metric.py --calibrate a.glb b.glb ... [--json cal.json]
"""
import argparse
import json
import math
import os
import sys

import numpy as np
import trimesh
from scipy.spatial import cKDTree

# Material-name tokens that mark geometry as painted BODY panel. Everything
# else (glass, rubber, interior, chrome trim) is excluded from a body reading:
# a tyre's tread is legitimately rough and would swamp the panels.
BODY_TOK = ("carpaint", "paint", "body", "karosserie", "coloured", "car_paint")
NOTBODY_TOK = ("glass", "window", "windscreen", "windshield", "screen", "glas",
               "tyre", "tire", "rubber", "interior", "seat", "dash", "engine",
               "lamp", "light", "lens", "rim", "wheel", "grille", "carbon",
               "plate", "mirror", "caliper", "brake", "badge", "logo",
               "leather", "fabric", "cloth", "wiper", "exhaust", "radiator")

CREASE_DEG = 25.0        # above this an edge is a FEATURE, not noise
RING = 2                 # how many face rings around a feature to exclude
NORMAL_AGREE = 0.50      # cos limit: neighbours must face broadly the same way
MIN_NBRS = 8             # below this a fit is not determined; face is skipped
MAX_NBRS = 220           # kdtree k cap (radius mask applied after)


# ---------------------------------------------------------------- loading
def load_body(path, geom=None, target_len=None, verbose=True):
    """-> (trimesh.Trimesh welded body, info dict).

    Node transforms are APPLIED. Half this catalogue keeps its scale in the
    node matrix (a Panamera whose geometry extents read 0.022) and a physical
    radius measured against unscaled vertices is meaningless.
    """
    sc = trimesh.load(path, force="scene")
    picked, skipped = [], []
    for name, g in sc.geometry.items():
        if not isinstance(g, trimesh.Trimesh) or len(g.faces) == 0:
            continue
        mat = getattr(getattr(g, "visual", None), "material", None)
        mname = (getattr(mat, "name", None) or name or "").lower()
        if geom:
            take = geom.lower() in (name or "").lower() or geom.lower() in mname
        else:
            take = (any(t in mname for t in BODY_TOK)
                    and not any(t in mname for t in NOTBODY_TOK))
        (picked if take else skipped).append(name)

    if not picked:
        # No paint-named geometry (common on older sourced cars whose meshes
        # are called Object_17). Fall back to "everything that is not obviously
        # not-body" and SAY SO — the panel restriction still carries the load.
        for name, g in sc.geometry.items():
            if not isinstance(g, trimesh.Trimesh) or len(g.faces) == 0:
                continue
            mat = getattr(getattr(g, "visual", None), "material", None)
            mname = (getattr(mat, "name", None) or name or "").lower()
            if not any(t in mname for t in NOTBODY_TOK):
                picked.append(name)
        fallback = True
    else:
        fallback = False

    parts = []
    for node in sc.graph.nodes_geometry:
        T, gn = sc.graph[node]
        if gn not in picked:
            continue
        g = sc.geometry[gn].copy()
        g.apply_transform(T)
        parts.append(g)
    if not parts:
        raise SystemExit(f"no body geometry in {path}")
    m = trimesh.util.concatenate(parts)

    scale_applied = 1.0
    if target_len:
        L = float(np.ptp(m.vertices, axis=0).max())
        if L <= 0:
            raise SystemExit(f"degenerate bbox in {path}")
        scale_applied = target_len / L
        m.apply_scale(scale_applied)

    # weld: duplicated border verts would otherwise split the face adjacency
    # graph and hide every crease that runs along a shell seam.
    V = np.asarray(m.vertices, dtype=np.float64)
    F = np.asarray(m.faces)
    sc_ = float(np.ptp(V, axis=0).max())
    key = np.round(V / (1e-6 * sc_)).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    Vw, Fw = V[first], inv[F]
    Fw = Fw[(Fw[:, 0] != Fw[:, 1]) & (Fw[:, 1] != Fw[:, 2]) & (Fw[:, 0] != Fw[:, 2])]
    w = trimesh.Trimesh(vertices=Vw, faces=Fw, process=False)
    info = dict(path=os.path.basename(path), geoms_used=len(picked),
                fallback_selection=fallback, faces=int(len(Fw)),
                verts=int(len(Vw)), welded_away=int(len(V) - len(Vw)),
                scale_applied=round(scale_applied, 6),
                extents=[round(float(x), 4) for x in w.extents])
    if verbose:
        print(f"  {info['path']}: {len(picked)} geoms -> {len(Fw)} faces, "
              f"extents {np.round(w.extents, 3)}"
              + ("  [FALLBACK selection]" if fallback else ""))
    return w, info


def car_axes(m):
    """-> (i_len, i_width, i_up). Cars are longer than wide, and wider than
    tall (Golf Mk8: 4284 x 1789 x 1456). Sorting the extents is therefore a
    sound axis map for a saloon/hatch and it is PRINTED so a tall van that
    breaks it is caught by eye rather than silently mismeasured."""
    e = np.asarray(m.extents, dtype=float)
    order = np.argsort(-e)
    return int(order[0]), int(order[1]), int(order[2])


# ---------------------------------------------------------------- regions
def region_mask(m, region):
    """Face mask for a named panel region, in normalised bbox coordinates."""
    F = m.faces
    C = m.vertices[F].mean(axis=1)
    N = m.face_normals
    il, iw, iu = car_axes(m)
    lo, hi = m.bounds
    span = np.where((hi - lo) > 1e-9, hi - lo, 1.0)
    u = (C - lo) / span                                   # 0..1 per axis
    up = np.zeros(3); up[iu] = 1.0
    wd = np.zeros(3); wd[iw] = 1.0
    ndu = N @ up
    ndw = N @ wd
    if region == "all":
        return np.ones(len(F), dtype=bool)
    if region == "roof":
        return (u[:, iu] > 0.78) & (ndu > 0.70)
    if region == "upper":                                  # roof + bonnet + boot
        return (u[:, iu] > 0.45) & (ndu > 0.70)
    if region == "bonnet":
        return (u[:, iu] > 0.45) & (u[:, iu] < 0.80) & (ndu > 0.70) & \
               ((u[:, il] < 0.30) | (u[:, il] > 0.70))
    if region == "flank":
        return (np.abs(ndw) > 0.72) & (u[:, iu] > 0.22) & (u[:, iu] < 0.72)
    raise SystemExit(f"unknown region {region!r}")


# ---------------------------------------------------------------- the metric
def feature_mask(m, crease_deg=CREASE_DEG, ring=RING):
    """True for faces that are ON or NEAR a genuine sharp feature."""
    adj = m.face_adjacency
    ang = m.face_adjacency_angles
    sharp = ang > math.radians(crease_deg)
    hot = np.zeros(len(m.faces), dtype=bool)
    hot[adj[sharp][:, 0]] = True
    hot[adj[sharp][:, 1]] = True
    for _ in range(ring):
        grow = hot.copy()
        grow[adj[hot[adj[:, 0]]][:, 1]] = True
        grow[adj[hot[adj[:, 1]]][:, 0]] = True
        hot = grow
    return hot


def crease_length(m, crease_deg=CREASE_DEG):
    """Total length of feature edges, metres. Printed BESIDE the metric so a
    'repair' that flattened the shut lines away cannot hide behind a better
    sigma_theta — that trade is this gate's obvious failure mode."""
    ang = m.face_adjacency_angles
    e = m.face_adjacency_edges[ang > math.radians(crease_deg)]
    if len(e) == 0:
        return 0.0
    return float(np.linalg.norm(m.vertices[e[:, 0]] - m.vertices[e[:, 1]],
                                axis=1).sum())


def slope_error(m, radius, mask=None, max_faces=250000, seed=0):
    """sigma_theta(radius) over the masked faces. Returns a dict of stats."""
    C = m.vertices[m.faces].mean(axis=1)
    N = m.face_normals
    A = m.area_faces
    idx = np.where(mask)[0] if mask is not None else np.arange(len(C))
    if len(idx) == 0:
        return dict(n=0)
    if len(idx) > max_faces:                     # deterministic subsample
        rng = np.random.default_rng(seed)
        idx = np.sort(rng.choice(idx, max_faces, replace=False))

    tree = cKDTree(C)
    k = min(MAX_NBRS, len(C))
    theta = np.full(len(idx), np.nan)

    # CHUNKED. The batched (M,k,6) design matrix is 2.5 GB at M=243k, k=220 and
    # the first run of this file was OOM-KILLED with rc=0 and no traceback —
    # it printed the load line, printed nothing else, and looked like a pass.
    # Chunking is not an optimisation here, it is the difference between a
    # measurement and a silent lie.
    CH = max(1, int(4e7 / (k * 8 * 12)))
    for s in range(0, len(idx), CH):
        sl = slice(s, min(s + CH, len(idx)))
        ii = idx[sl]
        d, nb = tree.query(C[ii], k=k, workers=-1)
        ok = (d <= radius) & (nb < len(C))
        ok[:, 0] = True                          # itself always counts

        P = C[nb] - C[ii][:, None, :]            # (m,k,3) offsets
        n0 = N[ii]
        # neighbours whose normal disagrees are a different surface (the far
        # side of a thin panel, or across a shut line) — keep them out of the fit.
        ok &= np.einsum("mkj,mj->mk", N[nb], n0) > NORMAL_AGREE

        # local frame: +Z = face normal, X/Y arbitrary but orthonormal
        tmp = np.tile(np.array([1.0, 0.0, 0.0]), (len(ii), 1))
        tmp[np.abs(n0[:, 0]) > 0.9] = np.array([0.0, 1.0, 0.0])
        ex = np.cross(n0, tmp)
        ex /= np.linalg.norm(ex, axis=1, keepdims=True).clip(1e-12)
        ey = np.cross(n0, ex)

        x = np.einsum("mkj,mj->mk", P, ex)
        y = np.einsum("mkj,mj->mk", P, ey)
        z = np.einsum("mkj,mj->mk", P, n0)

        # weights: face area x smooth radial kernel (zero at r = radius)
        r = np.sqrt(x * x + y * y).clip(0, radius)
        w = A[nb] * (1.0 - r / radius) ** 2 * ok
        cnt = ok.sum(1)

        B = np.stack([x * x, x * y, y * y, x, y, np.ones_like(x)], axis=-1)
        Bw = B * w[..., None]
        AtA = np.einsum("mki,mkj->mij", Bw, B)
        Atb = np.einsum("mki,mk->mi", Bw, z)
        tr = np.trace(AtA, axis1=1, axis2=2)
        AtA[:, np.arange(6), np.arange(6)] += (1e-9 * tr + 1e-30)[:, None]
        good = cnt >= MIN_NBRS
        if good.any():
            # b as (n,6,1), NOT (n,6): NumPy 2 dropped the old "b is a stack of
            # vectors" rule for solve and reads a 2-D b as a single matrix.
            coef = np.linalg.solve(AtA[good], Atb[good][..., None])[..., 0]
            th = np.degrees(np.arctan(np.hypot(coef[:, 3], coef[:, 4])))
            out = np.full(len(ii), np.nan)
            out[good] = th
            theta[sl] = out

    v = theta[np.isfinite(theta)]
    aw = A[idx][np.isfinite(theta)]
    if len(v) == 0:
        return dict(n=0)
    rms = float(np.sqrt((aw * v * v).sum() / aw.sum()))
    return dict(n=int(len(v)),
                rms=round(rms, 4),
                median=round(float(np.median(v)), 4),
                p90=round(float(np.percentile(v, 90)), 4),
                p99=round(float(np.percentile(v, 99)), 4),
                frac_over_1deg=round(float((v > 1.0).mean()), 4),
                frac_over_3deg=round(float((v > 3.0).mean()), 4),
                undetermined=int(np.isnan(theta).sum()),
                radius_mm=round(radius * 1000, 1))


def measure(path, region="all", radii=(0.025, 0.080), geom=None,
            target_len=4.30, max_faces=250000, verbose=True):
    m, info = load_body(path, geom=geom, target_len=target_len, verbose=verbose)
    il, iw, iu = car_axes(m)
    feat = feature_mask(m)
    reg = region_mask(m, region)
    panel = reg & ~feat
    el = m.edges_unique_length
    out = dict(info=info, region=region, axes=dict(length=il, width=iw, up=iu),
               region_faces=int(reg.sum()), panel_faces=int(panel.sum()),
               panel_frac=round(float(panel.sum() / max(reg.sum(), 1)), 4),
               feature_frac=round(float(feat.mean()), 4),
               crease_len_m=round(crease_length(m), 3),
               edge_mm=dict(median=round(float(np.median(el)) * 1000, 2),
                            p05=round(float(np.percentile(el, 5)) * 1000, 2),
                            p95=round(float(np.percentile(el, 95)) * 1000, 2)),
               sigma=dict())
    for R in radii:
        out["sigma"][f"{int(R*1000)}mm"] = slope_error(
            m, R, mask=panel, max_faces=max_faces)
    if verbose:
        s = "  ".join(f"s{k}={v.get('rms', float('nan')):.3f}deg"
                      for k, v in out["sigma"].items())
        print(f"    region={region} panel={out['panel_faces']} "
              f"({out['panel_frac']*100:.0f}% of region)  {s}  "
              f"crease={out['crease_len_m']:.2f}m  "
              f"edge~{out['edge_mm']['median']:.1f}mm")
    return out


# ---------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("glb", nargs="*")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--region", default="all")
    ap.add_argument("--regions", default=None,
                    help="comma list; measures each (implies a summary table)")
    ap.add_argument("--radii", default="0.025,0.080")
    ap.add_argument("--geom", default=None)
    ap.add_argument("--target-len", type=float, default=4.30)
    ap.add_argument("--max-faces", type=int, default=250000)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    if not a.glb:
        ap.error("give at least one glb")
    radii = tuple(float(x) for x in a.radii.split(","))
    regions = a.regions.split(",") if a.regions else [a.region]

    results = []
    for p in a.glb:
        print(p)
        try:
            for reg in regions:
                results.append(measure(p, region=reg, radii=radii, geom=a.geom,
                                       target_len=a.target_len,
                                       max_faces=a.max_faces))
        except Exception as exc:                       # a bad car must not stop a sweep
            print(f"  FAILED: {type(exc).__name__}: {exc}")
            results.append(dict(info=dict(path=os.path.basename(p)),
                                error=f"{type(exc).__name__}: {exc}"))

    if a.calibrate:
        print("\n=== CALIBRATION BAND ===")
        for reg in regions:
            for R in radii:
                key = f"{int(R*1000)}mm"
                vals = [r["sigma"][key]["rms"] for r in results
                        if "sigma" in r and r.get("region") == reg
                        and r["sigma"][key].get("n")]
                if not vals:
                    continue
                v = np.array(vals)
                print(f"  {reg:7s} sigma({key}): n={len(v)} "
                      f"min={v.min():.3f} p25={np.percentile(v,25):.3f} "
                      f"median={np.median(v):.3f} p75={np.percentile(v,75):.3f} "
                      f"max={v.max():.3f}  deg")
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(results, fh, indent=1)
        print("wrote", a.json)


if __name__ == "__main__":
    main()
