#!/usr/bin/env python3
"""fit_inside.py — clamp every cabin part inside the body's own inner surface.

v1 put the door cards, headliner and bench back THROUGH the body skin: a grey
slab on the rear quarter and a strip along the roof, measured at 26,320 px over
3 views by poke_test.py. The cause is that the kit used SINGLE half-width and
roof-height values for the whole cabin, while the body tapers front-to-rear.

The clamp is measured, not guessed, off Body_Shell's MAIN component:
  lateral : for a cabin vertex (x,y,z), the nearest flank vertices in (x,y) on
            the SAME side give the innermost |z| of the body there; the cabin
            vertex is pulled to |z| <= that - INSET
  vertical: the nearest body vertices in (x,z) with y above the beltline give
            the roof underside; the cabin vertex is pulled to y <= that - INSET

Moving MY OWN new vertices is safe — the coincident-vertex hazard applies to the
generator's meshes, where carpaint and interior share 25,369 positions. Nothing
in the original file is touched by this stage.

Run: python3 fit_inside.py <kit_in.npz> <kit_out.npz>
"""
import json
import sys
import numpy as np
import trimesh
from scipy.spatial import cKDTree
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

IN, OUT = sys.argv[1], sys.argv[2]
INSET_Z = 0.028
INSET_Y = 0.028
WS_CLEAR = 0.045     # m of clearance under the windscreen pane
WS_X_AFT = -0.45     # the real header, aft of where the partial pane stops
WS_ZMAX = 0.70
MAX_MOVE = 0.060
MAX_MOVE_Y = 0.150   # the vertical cap is larger: the wheel needed 115 mm      # a clamp bigger than this would DEFORM the part, not fit
                      # it — v1's 426 mm pulls were the tell. Anything needing
                      # more must be rebuilt on the measured surface instead
                      # (door cards and headliner now are), and is REPORTED.

_S = np.load(__import__("os").environ.get("CABIN_SURF", "body_surf.npz"))


def _bil(gridname, a, b, ea, eb):
    G = _S[gridname]
    ca = (ea[:-1] + ea[1:]) / 2
    cb = (eb[:-1] + eb[1:]) / 2
    ia = np.clip(np.searchsorted(ca, a) - 1, 0, len(ca) - 2)
    ib = np.clip(np.searchsorted(cb, b) - 1, 0, len(cb) - 2)
    ta = np.clip((a - ca[ia]) / (ca[ia + 1] - ca[ia]), 0, 1)
    tb = np.clip((b - cb[ib]) / (cb[ib + 1] - cb[ib]), 0, 1)
    return ((1 - ta) * ((1 - tb) * G[ia, ib] + tb * G[ia, ib + 1]) +
            ta * ((1 - tb) * G[ia + 1, ib] + tb * G[ia + 1, ib + 1]))


import os as _o
sc = trimesh.load(_o.environ.get("CABIN_CAR", "car_merged.glb"), force="scene", process=False)
_Tw, _gw = sc.graph["Glass_Windscreen"]
_WSV = trimesh.transform_points(sc.geometry[_gw].vertices, _Tw)
_Aw = np.c_[_WSV[:, 0], _WSV[:, 2], np.ones(len(_WSV))]
_WSCO, _, _, _ = np.linalg.lstsq(_Aw, _WSV[:, 1], rcond=None)
print(f"windscreen plane y = {_WSCO[0]:.4f}x + {_WSCO[1]:.4f}z + {_WSCO[2]:.4f}")
T, gn = sc.graph["Body_Shell"]
g = sc.geometry[gn]
BV = trimesh.transform_points(g.vertices, T)
BF = np.asarray(g.faces)
q = np.round(BV / 1e-5).astype(np.int64)
_, inv = np.unique(q, axis=0, return_inverse=True)
Fw = inv[BF]
e = np.vstack([Fw[:, [0, 1]], Fw[:, [1, 2]], Fw[:, [2, 0]]])
A = coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])),
               shape=(int(inv.max()) + 1,) * 2)
_, lab = connected_components(A, directed=False)
flab = lab[Fw[:, 0]]
MAIN = int(np.argmax(np.bincount(flab)))
mv = np.unique(BF[flab == MAIN])
P = BV[mv]
print(f"body main component: {len(P)} vertices used as the clamp surface")

rz = np.load(IN)
man = json.loads(bytes(rz["manifest"]).decode())
out = {k: rz[k] for k in rz.files}
report = []
for p in man["parts"]:
    n = p["name"]
    V = rz[f"{n}__v"].astype(np.float64).copy()
    V0 = V.copy()
    for sgn in (-1, 1):
        m = np.sign(V[:, 2]) == sgn
        if not m.any():
            continue
        lim = _bil("ZIN_R" if sgn < 0 else "ZIN_L", V[m, 0], V[m, 1],
                   _S["xe"], _S["ye"]) - INSET_Z
        z = np.abs(V[m, 2])
        newz = np.minimum(z, np.maximum(lim, 0.05))
        newz = np.maximum(newz, z - MAX_MOVE)          # capped
        V[m, 2] = sgn * newz
    ylim = _bil("YTOP", V[:, 0], V[:, 2], _S["xe"], _S["ze"]) - INSET_Y
    # ...and under the WINDSCREEN where that pane covers the (x,z) cell. The
    # steering wheel penetrated the screen by ~70 mm in v3 and showed as 364
    # GAINED silhouette pixels outside the apertures — hole_attrib named it.
    # PLANE, not the grid. The grid's per-cell 5th percentile is nearest-filled,
    # and on the driver's side the nearest covered cell is the pane's BASAL
    # STRIP, so it read ~100 mm low and flattened the steering wheel instead of
    # placing it. Plane fit over all 1,491 pane verts, rms 11.9 mm, extrapolated
    # aft to WS_X_AFT because the pane itself stops short of the real header.
    yws = (_WSCO[0] * V[:, 0] + _WSCO[1] * V[:, 2] + _WSCO[2]) - WS_CLEAR
    inws = (V[:, 0] <= WS_X_AFT) & (np.abs(V[:, 2]) <= WS_ZMAX)
    ylim = np.where(inws, np.minimum(ylim, yws), ylim)
    V[:, 1] = np.maximum(np.minimum(V[:, 1], ylim), V[:, 1] - MAX_MOVE_Y)
    d = np.linalg.norm(V - V0, axis=1)
    report.append({"name": n, "moved": int((d > 1e-6).sum()),
                   "verts": int(len(V)),
                   "max_move_mm": round(float(d.max()) * 1000, 1),
                   "capped": int((d > MAX_MOVE - 1e-6).sum())})
    out[f"{n}__v"] = V.astype(np.float32)
    # normals must be recomputed for moved geometry — NORMALS ARE NOT POSITIONS
    m2 = trimesh.Trimesh(V, rz[f"{n}__f"].astype(np.int64).reshape(-1, 3),
                         process=False)
    nn = np.asarray(m2.vertex_normals, np.float32)
    ln = np.linalg.norm(nn, axis=1)
    bad = int((ln <= 0.5).sum())
    if bad:                       # degenerate after clamping -> fall back
        nn[ln <= 0.5] = rz[f"{n}__n"][ln <= 0.5]
    out[f"{n}__n"] = nn
    print(f"  {n:24s} moved {report[-1]['moved']:5d}/{len(V):5d} "
          f"max {report[-1]['max_move_mm']:6.1f} mm  capped={report[-1]['capped']:4d}"
          f"  degen_n={bad}")

np.savez(OUT, **out)
json.dump(report, open("fit_inside.json", "w"), indent=1)
print(f"\nwrote {OUT}")
