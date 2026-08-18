#!/usr/bin/env python3
"""wheel_master.py — SUPERSEDED by wheel_stage.py (2026-08-18).

Owner standard: the machine is car-agnostic SOFTWARE. This script carried
the Golf's numbers (axle x, tracks, tyre dims) as source-code literals and
is kept only as history. Car data now lives in specs/*.json (carspec.py)
and the stage logic in wheel_stage.py, which detects arches geometrically
and self-tests against spec.expect before placing anything. Do not extend
this file.
"""

import json
import sys
import numpy as np
import trimesh

OUT = sys.argv[1]

R_TYRE = 0.31715
W_TYRE = 0.225
R_RIM = 0.2159          # 17" bead seat
R_LIP = 0.2225
R_BARREL_IN = 0.186
R_DISC = 0.155
SEG = 96                # radial resolution — no visible polygon silhouette


def ring(profile, seg=SEG):
    """Revolve a CLOSED (r, z) profile loop around +Z -> watertight solid."""
    profile = np.asarray(profile, float)
    np_, = profile.shape[:1],
    npts = len(profile)
    th = np.linspace(0, 2 * np.pi, seg, endpoint=False)
    V = np.empty((seg * npts, 3))
    for i, t in enumerate(th):
        c, s = np.cos(t), np.sin(t)
        V[i * npts:(i + 1) * npts, 0] = profile[:, 0] * c
        V[i * npts:(i + 1) * npts, 1] = profile[:, 0] * s
        V[i * npts:(i + 1) * npts, 2] = profile[:, 1]
    F = []
    for i in range(seg):
        i2 = (i + 1) % seg
        for k in range(npts):
            k2 = (k + 1) % npts
            a, b = i * npts + k, i * npts + k2
            c2, d = i2 * npts + k, i2 * npts + k2
            F += [[a, b, d], [a, d, c2]]
    m = trimesh.Trimesh(vertices=V, faces=F, process=True)
    m.fix_normals()
    assert m.is_watertight, "ring profile must revolve watertight"
    return m


parts = {}

# ---- TYRE: closed cross-section with shoulder rounding ----
w2 = W_TYRE / 2
tyre = ring([
    (0.205, +w2), (0.285, +w2), (0.306, +w2 * 0.93), (R_TYRE, +w2 * 0.66),
    (R_TYRE, -w2 * 0.66), (0.306, -w2 * 0.93), (0.285, -w2), (0.205, -w2),
])
parts["TYRE_MASTER"] = tyre

# ---- RIM: barrel with lips + 10 spokes + outer spoke ring ----
barrel = ring([
    (R_LIP, +0.100), (R_RIM, +0.088), (R_RIM, -0.088), (R_LIP, -0.100),
    (R_LIP, -0.106), (R_BARREL_IN, -0.094), (R_BARREL_IN, +0.094),
    (R_LIP, +0.106),
])
spokes = []
for k in range(10):
    b = trimesh.creation.box(extents=[0.135, 0.034, 0.024])
    b.apply_translation([0.070 + 0.135 / 2, 0, 0.046])
    b.apply_transform(trimesh.transformations.rotation_matrix(
        k * 2 * np.pi / 10, [0, 0, 1]))
    spokes.append(b)
sring = ring([(R_BARREL_IN + 0.002, 0.058), (0.170, 0.040),
              (0.170, 0.028), (R_BARREL_IN + 0.002, 0.040)], seg=SEG)
parts["RIM_MASTER"] = trimesh.util.concatenate([barrel, sring] + spokes)

# ---- HUB: centre cylinder + cap + 5 lug bosses (5x112 PCD) ----
hub = trimesh.creation.cylinder(radius=0.068, height=0.030, sections=48)
hub.apply_translation([0, 0, 0.044])
cap = trimesh.creation.cylinder(radius=0.030, height=0.010, sections=48)
cap.apply_translation([0, 0, 0.062])
lugs = []
for k in range(5):
    lg = trimesh.creation.cylinder(radius=0.009, height=0.014, sections=16)
    a = k * 2 * np.pi / 5
    lg.apply_translation([0.056 * np.cos(a), 0.056 * np.sin(a), 0.058])
    lugs.append(lg)
parts["HUB_MASTER"] = trimesh.util.concatenate([hub, cap] + lugs)

# ---- BRAKE DISC: annular ring inboard of the spoke face ----
parts["BRAKE_DISC_MASTER"] = ring([
    (0.080, -0.008), (R_DISC, -0.008), (R_DISC, -0.030), (0.080, -0.030)],
    seg=SEG)

# ---- BRAKE CALIPER: arc block straddling the disc, top-rear ----
# corner radius must clear the barrel inner surface (0.186): with radial
# outer 0.170 and half-tangent 0.060 the far corner sits at 0.180
cal = trimesh.creation.box(extents=[0.075, 0.120, 0.052])
cal.apply_translation([0.1325, 0, -0.019])
cal.apply_transform(trimesh.transformations.rotation_matrix(
    np.radians(115), [0, 0, 1]))
parts["BRAKE_CALIPER_MASTER"] = cal

out = {}
meta = {"spec": "225/45 R17 (published Mk8 Golf fitment)",
        "R_tyre": R_TYRE, "W_tyre": W_TYRE, "R_rim": R_RIM,
        "provisional": True,
        "note": "neutral production 10-spoke; trim unverified"}
for name, m in parts.items():
    ok_n = np.isfinite(m.vertices).all()
    print(f"  {name}: {len(m.faces)} faces, watertight={m.is_watertight}, "
          f"r_max={np.linalg.norm(m.vertices[:, :2], axis=1).max():.4f}, "
          f"z [{m.vertices[:,2].min():+.3f},{m.vertices[:,2].max():+.3f}]")
    out[f"{name}_v"] = m.vertices
    out[f"{name}_f"] = m.faces
out["meta"] = np.frombuffer(json.dumps(meta).encode(), dtype=np.uint8)
np.savez(OUT, **out)
print("wrote", OUT)
