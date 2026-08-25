#!/usr/bin/env python3
"""fit_spec.py — scale an ALREADY-canonical car onto its published dimensions.

WHY THIS EXISTS AND canon.py --spec DOES NOT COVER IT. canon.py does two
things in one pass: it finds the canonical POSE (oriented bounding box, axis
assignment, up-sign) and then optionally scales onto `--spec`. That is right
for a raw generator output. It is WRONG to re-run on a mesh that is already
canonical, and the failure is quiet:

  * the OBB has a SIGN AMBIGUITY. Re-running canon.py on its own output for
    the fresh Pixal Golf returned a mesh whose X and Z were both NEGATED --
    a 180-degree rotation about Y, i.e. the car turned to face the other way.
    Measured: max|B - A*s| came back [4.284, 0.005, 1.789], full-range on X
    and Z and essentially zero on Y. Harmless on its own (canon.py says
    outright that nose direction is not resolved), but it silently
    invalidates any per-face labels, priors or camera calibration that were
    computed in the first frame.
  * it also printed "up-sign: FLIPPED" on a mesh that was already the right
    way up. The flip about X and the OBB's own sign choice cancelled, so the
    result was correct and the log line was not. A log line that says the
    opposite of what happened is worse than no log line.

So: pose is decided ONCE, by canon.py, before the seg stack runs. Scale is a
separate, later, purely diagonal operation, and this file is it. No OBB, no
rotation, no re-centring beyond putting the wheels back on the ground.

WHAT IT CORRECTS, measured on the fresh Pixal3D Golf (2026-08-25, 998,730
faces, --resolution 1536):

    canonical  L=1.005  H=0.370  W=0.559     H/L 0.368   W/L 0.556
    Golf Mk8   L=4.284  H=1.456  W=1.789     H/L 0.340   W/L 0.418

    residual after the uniform length fit:   H x0.924    W x0.750

The height bias is the one canon.py already documents (+8% here, +12% and
+8% on two earlier cars). The WIDTH bias is 33% and was not previously
recorded, so state plainly what it is not: it is NOT wing mirrors. Width was
measured band by band up the car and the mirror level is no wider than the
door level (0.5564 vs 0.5535 of length, a 0.5% difference), so the published
excl.-mirrors figure is the right thing to fit to. The mesh is simply fat.

A CAVEAT THAT WILL BITE A DIFFERENT CAR. Because this fits the mesh's full
Z extent to an excl.-mirrors published width, a car whose mirrors DO stand
proud will be over-narrowed by roughly the mirror overhang. Check the
band profile before trusting the result on a new mesh; --max-mirror-frac
refuses when the widest band sits above the door line by more than the
given fraction.

WHAT IT DOES NOT FIX. Scaling is diagonal, so it cannot restore TUMBLEHOME.
The same band profile shows this Golf's width essentially constant from the
floor to 80% of its height (0.529 -> 0.556) when a real car's greenhouse is
markedly narrower than its door line. That is a shape defect in the
generator and no amount of scaling touches it.

Run: python3 fit_spec.py <canon.glb> <out.glb> --spec specs/car.json
     [--max-mirror-frac 0.02]
"""
import argparse
import os
import sys

import numpy as np
import trimesh

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from carspec import CarSpec

ap = argparse.ArgumentParser()
ap.add_argument("inp")
ap.add_argument("out")
ap.add_argument("--spec", required=True)
ap.add_argument("--max-mirror-frac", type=float, default=0.02,
                help="refuse if the widest height band stands more than this "
                     "fraction wider than the door line -- the mesh has "
                     "protruding mirrors and the excl.-mirrors published "
                     "width is then the wrong thing to fit the Z extent to")
a = ap.parse_args()

spec = CarSpec.load(a.spec)
tgt = {k: spec.dim(k)[0] for k in ("length_m", "height_m", "width_m")}
if not all(tgt.values()):
    raise SystemExit(f"REFUSED: spec must give length_m, height_m AND "
                     f"width_m; got {tgt}")

sc = trimesh.load(a.inp, force="scene")
# Bake node transforms before measuring, for the same reason canon.py does:
# geometry.values() alone drops them and the measurement would be taken in a
# different frame from the one the scale is applied in.
for _node in sc.graph.nodes_geometry:
    _T, _gn = sc.graph[_node]
    if _T is not None and not np.allclose(_T, np.eye(4)):
        sc.geometry[_gn].apply_transform(_T)
        sc.graph.update(frame_to=_node, matrix=np.eye(4), geometry=_gn)
m = trimesh.util.concatenate([g for g in sc.geometry.values()])
V = m.vertices
lo, hi = V.min(0), V.max(0)
e = hi - lo
if not (e[0] > e[2] > e[1]):
    raise SystemExit(f"REFUSED: extents {np.round(e,4)} are not L>W>H on "
                     "X,Z,Y -- this file is not canonical, run canon.py first")
print(f"canonical extents L={e[0]:.3f} H={e[1]:.3f} W={e[2]:.3f} "
      f"(H/L={e[1]/e[0]:.3f} W/L={e[2]/e[0]:.3f})")

# --- mirror guard: width band by band up the car --------------------------
zc = (lo[2] + hi[2]) / 2
aw = np.abs(V[:, 2] - zc)
hf = (V[:, 1] - lo[1]) / max(e[1], 1e-9)
bands = []
for i in range(10):
    k = (hf >= i / 10) & (hf < (i + 1) / 10)
    bands.append(2 * aw[k].max() / e[0] if k.sum() >= 50 else None)
door = max([b for b in bands[2:6] if b], default=None)   # 20-60% of height
above = max([b for b in bands[6:9] if b], default=None)  # 60-90%: mirror band
print("width by height band (frac of length): "
      + " ".join("-" if b is None else f"{b:.3f}" for b in bands))
if door and above and above > door * (1 + a.max_mirror_frac):
    raise SystemExit(
        f"REFUSED: widest band above the door line is {above:.4f} vs door "
        f"{door:.4f} (+{100*(above/door-1):.1f}%) -- the mirrors stand proud, "
        f"so fitting the full Z extent to an excl.-mirrors published width "
        f"would over-narrow the body. Raise --max-mirror-frac only if you "
        f"have checked the published figure INCLUDES mirrors.")

uniform = tgt["length_m"] / e[0]
resid = np.array([1.0,
                  tgt["height_m"] / (e[1] * uniform),
                  tgt["width_m"] / (e[2] * uniform)])
# Same bound canon.py uses, and for the same reason: the uniform factor is a
# unit conversion and may be any magnitude, but the residual is the
# generator's SHAPE bias and a large one means a units or axis mix-up rather
# than a bias worth correcting.
if not np.all((resid > 0.65) & (resid < 1.35)):
    raise SystemExit(f"REFUSED: residual proportion correction "
                     f"{np.round(resid,3)} outside +-35% after the uniform "
                     f"fit (x{uniform:.3f}) -- check the spec units and axes")
s = uniform * resid
print(f"uniform fit x{uniform:.3f}; residual H x{resid[1]:.3f} "
      f"W x{resid[2]:.3f}")

for gm in sc.geometry.values():
    gm.vertices = gm.vertices * s

m2 = trimesh.util.concatenate([g for g in sc.geometry.values()])
lo2 = m2.vertices.min(0)
if abs(lo2[1]) > 1e-6:                      # keep the wheels on the ground
    for gm in sc.geometry.values():
        gm.vertices[:, 1] -= lo2[1]
    m2 = trimesh.util.concatenate([g for g in sc.geometry.values()])
e2 = m2.extents
print(f"scaled x{s[0]:.3f} y{s[1]:.3f} z{s[2]:.3f} -> L={e2[0]:.3f} "
      f"H={e2[1]:.3f} W={e2[2]:.3f} (H/L={e2[1]/e2[0]:.3f})")
for k, got, want in (("length", e2[0], tgt["length_m"]),
                     ("height", e2[1], tgt["height_m"]),
                     ("width",  e2[2], tgt["width_m"])):
    if abs(got / want - 1) > 0.01:
        raise SystemExit(f"REFUSED: post-scale {k} {got:.4f} vs spec {want}")
# The whole point of this file over a canon.py re-run: FACE ORDER and vertex
# order are untouched, so per-face labels from the seg stack stay valid.
if len(m2.faces) != len(m.faces):
    raise SystemExit("REFUSED: face count changed -- labels would be invalid")
print(f"verified: all three dimensions within 1%; {len(m2.faces)} faces, "
      "order preserved (labels stay valid)")
sc.export(a.out, include_normals=True)
print("wrote", a.out)
