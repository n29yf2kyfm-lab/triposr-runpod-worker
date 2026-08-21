#!/usr/bin/env python3
"""verify_lr.py — left/right correspondence of the REBUILT panels, honestly.

This car's tail is SHEARED toward -z. Reporting "symmetric" would be a lie and
reporting nothing would hide the one number a reviewer needs. So: per height,
the panel's own lateral reach on each side, and the surface depth at MIRRORED
|z| -- measured on the rebuilt panels and on the source, so the reader can see
whether the rebuild made the asymmetry better, worse, or left it alone.

Run: python3 verify_lr.py <source.glb> <out.glb> <out.json>
"""
import json, sys
import numpy as np, trimesh

SRC, NEW, OUT = sys.argv[1], sys.argv[2], sys.argv[3]


def pan(path, names):
    sc = trimesh.load(path, force="scene", process=False)
    P = []
    for n in names:
        if n in sc.geometry: P.append(sc.geometry[n].triangles_center)
    return np.vstack(P) if P else None


def profile(P, ys, dy=0.015):
    rows = []
    for y in ys:
        m = np.abs(P[:, 1] - y) < dy
        if m.sum() < 20: continue
        z = P[m, 2]; x = P[m, 0]
        zp, zm = np.percentile(z, 99.5), np.percentile(z, 0.5)

        def xat(zt):
            k = np.abs(z - zt) < 0.03
            return float(np.percentile(x[k], 99)) if k.sum() > 3 else np.nan
        rows.append((float(y), float(zp), float(zm), float(abs(zm) - zp),
                     xat(0.30), xat(-0.30), xat(0.45), xat(-0.45)))
    return rows


rep = {}
for tag, path, names in (("source_hatch", SRC, ["Rear_Hatch"]),
                         ("rebuilt_hatch", NEW, ["Hatch"]),
                         ("source_bumper", SRC, ["Rear_Bumper"]),
                         ("rebuilt_bumper", NEW, ["Bumper_Rear"])):
    P = pan(path, names)
    if P is None: continue
    ys = np.arange(0.60, 0.94, 0.04) if "hatch" in tag else np.arange(0.26, 0.55, 0.04)
    rep[tag] = profile(P, ys)
json.dump(rep, open(OUT, "w"), indent=1)
for tag, rows in rep.items():
    print(f"--- {tag} ---")
    print(f"{'y':>6s} {'z+ reach':>9s} {'z- reach':>9s} {'shear':>7s} "
          f"{'x@+.30':>7s} {'x@-.30':>7s} {'dx':>7s} {'x@+.45':>7s} {'x@-.45':>7s} {'dx':>7s}")
    for y, zp, zm, sh, a, b, c, dd in rows:
        print(f"{y:6.3f} {zp:9.3f} {zm:9.3f} {sh:7.3f} {a:7.3f} {b:7.3f} {a-b:7.3f} "
              f"{c:7.3f} {dd:7.3f} {c-dd:7.3f}")
