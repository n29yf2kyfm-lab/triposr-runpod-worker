"""
holes.py -- "no new holes introduced by the merge", 15 directions, before vs after.

Definition, chosen so the test CAN fail:
  A ray that hit ANY surface in the BEFORE file and hits NOTHING in the AFTER file
  is a LOST SURFACE -> a new hole in the silhouette.
  A ray whose first-hit depth moves further away by more than `thresh` is a
  RECEDED FIRST SURFACE -> the outer skin has gone even though something behind it
  still stops the ray. This second class is the one `intersects_any` can never see,
  because the cabin sits behind every panel and always answers "yes".

Both classes are reported. Reporting only the first would make the test
empty-by-construction on a car with an interior -- the exact failure mode recorded
for the arch-intersection gate that had never fired.
"""
import numpy as np
import raycast as RC

# az 0/+-22/+-40 x el 0/+-18, per the brief
AZ = [0, 22, -22, 40, -40]
EL = [0, 18, -18]


def directions():
    out = []
    for az in AZ:
        for el in EL:
            a, e = np.radians(az), np.radians(el)
            # camera looks at the car; ray direction points INTO the car
            d = np.array([-np.cos(e) * np.cos(a), -np.sin(e), -np.cos(e) * np.sin(a)])
            out.append((az, el, d / np.linalg.norm(d)))
    return out


def _bundle(centre, radius, d, n):
    a = np.array([0.0, 1.0, 0.0])
    u = np.cross(d, a)
    if np.linalg.norm(u) < 1e-6:
        u = np.cross(d, np.array([1.0, 0, 0]))
    u /= np.linalg.norm(u)
    v = np.cross(d, u)
    O, _ = RC.grid_origins(centre, u, v, radius, radius, n, n, d, back=2 * radius + 1.0)
    return O


def hole_test(gA, gB, n=40, thresh_m=0.05, ncell=192):
    """gA = before, gB = after."""
    VA, FA, oA, nmA = RC.gather(gA)
    VB, FB, oB, nmB = RC.gather(gB)
    allV = np.vstack([VA[np.unique(FA)], VB[np.unique(FB)]])
    centre = (allV.min(0) + allV.max(0)) / 2
    radius = float(np.linalg.norm(allV.max(0) - allV.min(0)) / 2) * 0.62
    rows = []
    tot = dict(rays=0, lost=0, gained=0, receded=0, advanced=0)
    for az, el, d in directions():
        O = _bundle(centre, radius, d, n)
        bA = RC.Binned(VA, FA, oA, d, ncell=ncell)
        bB = RC.Binned(VB, FB, oB, d, ncell=ncell)
        hA, hB = bA.hits(O), bB.hits(O)
        tA = np.array([h[0][0] if len(h[0]) else np.inf for h in hA])
        tB = np.array([h[0][0] if len(h[0]) else np.inf for h in hB])
        hitA, hitB = np.isfinite(tA), np.isfinite(tB)
        lost = int((hitA & ~hitB).sum())
        gained = int((~hitA & hitB).sum())
        both = hitA & hitB
        receded = int((both & (tB - tA > thresh_m)).sum())
        advanced = int((both & (tA - tB > thresh_m)).sum())
        rows.append(dict(az=az, el=el, rays=int(len(O)), hitA=int(hitA.sum()),
                         hitB=int(hitB.sum()), lost=lost, gained=gained,
                         receded=receded, advanced=advanced))
        tot['rays'] += len(O); tot['lost'] += lost; tot['gained'] += gained
        tot['receded'] += receded; tot['advanced'] += advanced
    return dict(per_direction=rows, total=tot, thresh_m=thresh_m,
                grid=f'{n}x{n}', directions=len(rows))
