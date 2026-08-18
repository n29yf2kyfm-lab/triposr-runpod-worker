#!/usr/bin/env python3
"""surface_stage.py — Stage 6: panel-surface RECONSTRUCTION (not smoothing).

What is already measured and settled about this body class (2026-08-18):
capped Laplacian relaxation cannot reach the melt (bonnet p95 sits 69.9mm
from ANY smooth design surface); a single global quadric under-fits; and
"more smoothing" is concealment, which the brief forbids. The brief's own
remedy applies instead: "if a neural section cannot be repaired
economically, REPLACE it with clean reconstructed geometry."

This stage rebuilds a SEPARATED PANEL (stage-5 contract: Bonnet,
Front_Wing_L/R, Rear_Hatch, ... are named nodes) on its own fitted
design surface:

  1. PCA frame per panel — offsets measured along the panel's dominant
     normal axis, so bonnets (y-up) and wings (z-out) use the same code
  2. robust IRLS bicubic spline fit (Tukey weights, 4 rounds): the fit
     follows the panel's dominant smooth surface and treats melt lumps
     as OUTLIERS instead of averaging them in. Knot spacing ~1/8 of the
     panel span = design-curvature scale, bridging 50-150mm melt.
  3. symmetric fold: a panel that straddles the centreline is fitted on
     its own samples PLUS their z-mirror — the design is symmetric, the
     melt is not, so folding doubles evidence against it (decided per
     panel by measurement: fold kept only if it does not worsen the
     inlier fit)
  4. rebuild: vertices move to the fitted surface, feathered to ZERO at
     the panel boundary so edges stay glued to the neighbouring shell

--measure fits and REPORTS ONLY (diagnostic-first; nothing written).
Every displacement is recorded; the panel's bbox must not drift.

Run: python3 surface_stage.py <in.glb> <out.glb> --panels Bonnet[,..]
         [--spec spec.json] [--measure]
"""
import json
import os
import struct
import sys
import numpy as np
import trimesh
from scipy.interpolate import LSQBivariateSpline

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from carspec import CarSpec

INP, OUT = sys.argv[1], sys.argv[2]
MEASURE = "--measure" in sys.argv
PANELS = ["Bonnet"]
SPEC = None
for i, a in enumerate(sys.argv):
    if a == "--panels":
        PANELS = sys.argv[i + 1].split(",")
    if a == "--spec":
        SPEC = sys.argv[i + 1]
spec = CarSpec.load(SPEC) if SPEC else CarSpec.empty()

QC = {"stage": "surface_stage", "input": INP, "spec": spec.path,
      "mode": "measure" if MEASURE else "apply", "panels": {}}

KNOT_FRAC = 1 / 8      # knot spacing as fraction of panel span (design scale)
FEATHER_FRAC = 0.05    # boundary feather as fraction of panel diagonal
TUKEY_C = 4.685        # standard Tukey constant (x MAD)
IRLS_ROUNDS = 4

sc = trimesh.load(INP, force="scene")


def tukey_w(r, scale):
    t = np.abs(r) / max(scale, 1e-9)
    w = (1 - (t / TUKEY_C) ** 2) ** 2
    w[t > TUKEY_C] = 0.0
    return w


def fit_panel(P, fold_b=None):
    """IRLS spline fit of offsets h over plane coords (a,b).

    Returns (spline, inlier_rms, report). fold_b: if set, samples are
    augmented with (a, fold_b(b), h) mirrors before fitting.
    """
    a, b, h = P[:, 0], P[:, 1], P[:, 2]
    if fold_b is not None:
        a = np.r_[a, a]
        b = np.r_[b, fold_b(P[:, 1])]
        h = np.r_[h, h]
    na = max(4, int((a.max() - a.min()) / max((a.max() - a.min()) * KNOT_FRAC, 1e-9)))
    ka = np.linspace(a.min(), a.max(), na + 1)[1:-1]
    nb = max(4, int(1 / KNOT_FRAC))
    kb = np.linspace(b.min(), b.max(), nb + 1)[1:-1]
    w = np.ones(len(a))
    sp = None
    for _ in range(IRLS_ROUNDS):
        sp = LSQBivariateSpline(a, b, h, ka, kb, w=np.maximum(w, 1e-4))
        r = h - sp.ev(a, b)
        mad = np.median(np.abs(r - np.median(r))) * 1.4826
        w = tukey_w(r, mad)
    r = h - sp.ev(a, b)
    inl = w > 0.1
    rms = float(np.sqrt(np.mean(r[inl] ** 2))) if inl.any() else float("inf")
    rep = {"samples": int(len(a)), "inliers": int(inl.sum()),
           "outlier_frac": round(1 - inl.mean(), 3),
           "inlier_rms_mm": round(rms * 1000, 2),
           "resid_p95_mm": round(float(np.percentile(np.abs(r), 95)) * 1000, 2)}
    return sp, rms, rep


out = trimesh.Scene()
node_T = {}
for node in sc.graph.nodes_geometry:
    T, gn = sc.graph[node]
    node_T[gn] = (node, T)

for pname in PANELS:
    if pname not in sc.geometry:
        QC["panels"][pname] = {"status": "ABSENT",
                               "note": f"node not in scene: {sorted(sc.geometry)[:12]}"}
        print(f"{pname}: ABSENT — skipped")
        continue
    m = sc.geometry[pname]
    V = m.vertices.copy()
    ctr = V.mean(0)
    _, S, Vt = np.linalg.svd(V - ctr, full_matrices=False)
    u_ax, v_ax, n_ax = Vt[0], Vt[1], Vt[2]
    A = (V - ctr) @ u_ax
    B = (V - ctr) @ v_ax
    Hh = (V - ctr) @ n_ax
    P = np.c_[A, B, Hh]

    # symmetric fold candidate: does the panel straddle the centreline,
    # and does one plane axis carry world z (so a mirror is expressible)?
    straddle = (V[:, 2].min() < -0.02) and (V[:, 2].max() > 0.02)
    zdot_u, zdot_v = abs(u_ax[2]), abs(v_ax[2])
    fold = None
    fold_note = "not straddling centreline — no fold"
    if straddle and max(zdot_u, zdot_v) > 0.9:
        # mirror in the plane axis that carries z; valid because the axis
        # is (near-)parallel to world z, so b -> -b + const mirrors z
        if zdot_v > zdot_u:
            zc = -((ctr @ np.array([0, 0, 1.0])) / max(v_ax[2], 1e-9))
            fold = lambda b: 2 * zc - b
        else:
            fold = None    # u carrying z would swap the long axis; skip
            fold_note = "long axis carries z — fold skipped"
    sp0, rms0, rep0 = fit_panel(P)
    chosen, rep_f = sp0, None
    if fold is not None:
        spf, rmsf, rep_f = fit_panel(P, fold_b=fold)
        if rmsf <= rms0 * 1.1:      # fold kept unless it worsens the fit
            chosen = spf
            fold_note = (f"folded across centreline (inlier rms "
                         f"{rmsf*1000:.1f}mm vs {rms0*1000:.1f}mm unfolded)")
        else:
            fold_note = (f"fold REJECTED by measurement (rms {rmsf*1000:.1f}"
                         f"mm vs {rms0*1000:.1f}mm)")
    prep = {"pca_normal_axis": [round(float(x), 3) for x in n_ax],
            "fit_unfolded": rep0, "fit_folded": rep_f,
            "fold": fold_note}

    d = chosen.ev(A, B) - Hh          # move-to-surface displacement
    # boundary feather: ONLY the OUTER perimeter stays glued to the shell.
    # This body class is fragment soup (217k boundary edges) — feathering
    # on ALL boundary edges anchored every internal melt crack and froze
    # the panel (measured: mean disp 0.54mm against a 28mm p95 defect).
    # Internal crack edges must move WITH the surface — that is what
    # heals the crack steps. Outer perimeter = longest boundary loop.
    eu, cnt = np.unique(np.sort(m.edges, axis=1), axis=0, return_counts=True)
    be = eu[cnt == 1]
    adj = {}
    for a2, c2 in be:
        adj.setdefault(int(a2), []).append(int(c2))
        adj.setdefault(int(c2), []).append(int(a2))
    seen, loops = set(), []
    for start in adj:
        if start in seen:
            continue
        loop, cur, prev = [start], start, None
        seen.add(start)
        while True:
            nxt = [n2 for n2 in adj[cur] if n2 != prev and n2 not in seen]
            if not nxt:
                break
            n2 = nxt[0]
            loop.append(n2)
            seen.add(n2)
            prev, cur = cur, n2
        loops.append(loop)
    bidx = np.array(max(loops, key=len)) if loops else np.array([], int)
    diag = float(np.linalg.norm(V.max(0) - V.min(0)))
    feather = FEATHER_FRAC * diag
    if len(bidx):
        from scipy.spatial import cKDTree
        t = cKDTree(V[bidx])
        dist, _ = t.query(V, k=1)
        wgt = np.clip(dist / feather, 0, 1)
    else:
        wgt = np.ones(len(V))
    # trust gate: where the spline demands more than 2x the measured
    # defect amplitude it is EXTRAPOLATING outside its data support
    # (measured: 682mm at a corner cell) — those vertices stay put and
    # are counted, they are not "corrected" by a wrong amount
    trust_cap = 2.0 * np.percentile(np.abs(Hh - chosen.ev(A, B)), 95)
    wild = np.abs(d) > trust_cap
    d = d.copy()
    d[wild] = 0.0
    disp = d * wgt
    prep["displacement"] = {
        "trust_cap_mm": round(float(trust_cap) * 1000, 1),
        "verts_outside_trust": int(wild.sum()),
        "mean_mm": round(float(np.abs(disp).mean()) * 1000, 2),
        "p95_mm": round(float(np.percentile(np.abs(disp), 95)) * 1000, 2),
        "max_mm": round(float(np.abs(disp).max()) * 1000, 2),
        "feather_mm": round(feather * 1000, 1)}
    print(f"{pname}: inlier rms {rep0['inlier_rms_mm']}mm, resid p95 "
          f"{rep0['resid_p95_mm']}mm, {fold_note.split('(')[0].strip()}, "
          f"disp p95 {prep['displacement']['p95_mm']}mm "
          f"max {prep['displacement']['max_mm']}mm")

    if not MEASURE:
        V2 = V + n_ax[None, :] * disp[:, None]
        bb0 = V.max(0) - V.min(0)
        m2 = m.copy()
        m2.vertices = V2
        bb1 = V2.max(0) - V2.min(0)
        drift = float(np.abs(bb1 - bb0).max())
        ok_drift = drift < 0.01 * diag
        # residual AFTER: the rebuilt interior must sit on the fit
        core = (wgt > 0.99) & ~wild
        r_after = (chosen.ev(A[core], B[core])
                   - ((V2[core] - ctr) @ n_ax)) if core.any() else np.array([0.0])
        p95_after = float(np.percentile(np.abs(r_after), 95)) * 1000
        prep["self_tests"] = {
            "bbox_drift_mm": {"value": round(drift * 1000, 2),
                              "limit_mm": round(10 * diag, 2),
                              "pass": bool(ok_drift)},
            "core_on_surface_p95_mm": {"value": round(p95_after, 3),
                                       "limit": 1.0,
                                       "pass": bool(p95_after < 1.0)}}
        if not all(t["pass"] for t in prep["self_tests"].values()):
            prep["status"] = "REFUSED"
            QC["panels"][pname] = prep
            json.dump(QC, open(OUT.replace(".glb", "_surface_qc.json"), "w"), indent=1)
            raise SystemExit(f"REFUSED: {pname} self-tests failed: "
                             f"{prep['self_tests']}")
        sc.geometry[pname].vertices = V2
        vn = np.array(sc.geometry[pname].vertex_normals)
        bad = np.linalg.norm(vn, axis=1) < 1e-6
        if bad.any():
            vn[bad] = [0.0, 1.0, 0.0]
            sc.geometry[pname].vertex_normals = vn
        prep["status"] = "REBUILT"
    else:
        prep["status"] = "MEASURED"
    QC["panels"][pname] = prep

if not MEASURE:
    for node in sc.graph.nodes_geometry:
        T, gn = sc.graph[node]
        if gn not in out.geometry:
            out.add_geometry(sc.geometry[gn], geom_name=gn, node_name=node,
                             transform=T)
        else:
            out.graph.update(frame_to=node, matrix=T, geometry=gn)
    out.export(OUT, include_normals=True)
    with open(OUT, "rb") as fh:
        fh.seek(12); ln, _ = struct.unpack("<II", fh.read(8))
        j = json.loads(fh.read(ln))
    missing = [m2.get("name") for m2 in j["meshes"]
               if any("NORMAL" not in p["attributes"] for p in m2["primitives"])]
    if missing:
        raise SystemExit(f"REFUSED: NORMAL missing on {missing[:4]}")
    print(f"wrote {OUT} ({os.path.getsize(OUT)} bytes)")
json.dump(QC, open(OUT.replace(".glb", "_surface_qc.json"), "w"), indent=1)
print(f"QC -> {OUT.replace('.glb', '_surface_qc.json')}")
