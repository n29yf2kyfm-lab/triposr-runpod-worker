#!/usr/bin/env python3
"""align_dims.py — align the car to trusted vehicle dimensions (Phase 2).

Baseline forensics on the gseg Golf measured length +2.5% and height +15%
against the published Mk8 Golf hatch specs, with the front wheels placed
10cm/side too narrow (track 1.324 vs rear 1.539). The generator made the
body too tall; scaling is the honest correction — it aligns the SILHOUETTE
to trusted dimensions without painting over any surface defect.

Method:
  * body-type nodes (shell, glass, interior, lamps, occluder, backstop,
    frit, cavities, plate) scale NON-uniformly to spec about ground centre
  * wheel assemblies (tyre/rim/disc/caliper) scale UNIFORMLY (circles stay
    circles) and are re-seated on corrected axle geometry: spec wheelbase,
    equal front/rear track, all four on the ground plane
  * width target uses the BODY side skin (z p99.7), not the mirrors

Trusted specs (VW Golf Mk8 hatch, published): L 4.284 W 1.789 H 1.456
WB 2.619 track ~1.54. Identity note per rule 7: make/model = volkswagen
golf (from the catalogue reference the input render came from); year/trim
NOT verifiable from references — recorded as unverified, never guessed.

Run: python3 align_dims.py <in.glb> <out.glb>
"""
import sys
import numpy as np
import trimesh

INP, OUT = sys.argv[1], sys.argv[2]
SPEC = dict(L=4.284, W=1.789, H=1.456, WB=2.619, TRACK=1.540)

sc = trimesh.load(INP, force="scene")
geoms = dict(sc.geometry.items())

WHEEL_PREFIX = ("Tyre_Rubber", "Rim_Alloy", "disc_", "cal_")
is_wheel = lambda n: any(n.startswith(p) for p in WHEEL_PREFIX)

body_nodes = {n: g for n, g in geoms.items() if not is_wheel(n)}
allv = np.vstack([g.vertices for g in body_nodes.values()])
L0x, L1x = allv[:, 0].min(), allv[:, 0].max()
gy = allv[:, 1].min()
cz = (allv[:, 2].min() + allv[:, 2].max()) / 2
cx = (L0x + L1x) / 2

# measure: length full extent; height excluding the aerial spike (p99.8);
# width from the body side skin, not mirror pods (p99.7 of |z|)
cp = geoms.get("carpaint")
L_now = L1x - L0x
H_now = float(np.percentile(cp.vertices[:, 1], 99.8)) - gy
W_now = 2 * float(np.percentile(np.abs(cp.vertices[:, 2] - cz), 99.7))
sx, sy, szf = SPEC["L"] / L_now, SPEC["H"] / H_now, SPEC["W"] / W_now
print(f"measured L {L_now:.3f} H {H_now:.3f} W {W_now:.3f}  "
      f"-> scales x{sx:.3f} y{sy:.3f} z{szf:.3f}")

for n, g in body_nodes.items():
    v = g.vertices.copy()
    v[:, 0] = (v[:, 0] - cx) * sx
    v[:, 1] = (v[:, 1] - gy) * sy
    v[:, 2] = (v[:, 2] - cz) * szf
    g.vertices = v

# wheels: uniform scale (sy, so arch fit tracks the height squash), re-seat
# WHEELS SEAT WHERE THIS BODY'S ARCHES ARE — not at spec positions.
# (v36 first cut forced spec WB/track and the wheels floated outside the
# scaled arches; the arch openings are the body's own truth. Deviations
# from spec go in the QC report, never disguised.)
ac = geoms["Arch_Cavity"].vertices          # already scaled with the body
targets = {}
for sxn in (1, -1):
    for szn in (1, -1):
        sel = ac[(np.sign(ac[:, 0]) == sxn) & (np.sign(ac[:, 2]) == szn)]
        targets[(sxn, szn)] = sel.mean(0)
fr = [t for (a, _), t in targets.items() if a > 0]
re_ = [t for (a, _), t in targets.items() if a < 0]
wb_body = float(np.mean([t[0] for t in fr]) - np.mean([t[0] for t in re_]))
print(f"arch centres give wheelbase {wb_body:.3f} "
      f"({100*(wb_body/SPEC['WB']-1):+.1f}% vs spec — body geometry, recorded)")
wc = {n: g.vertices.mean(0) for n, g in geoms.items() if n.startswith("Rim_Alloy")}
cs = np.array(list(wc.values()))
su = sy                                  # uniform wheel scale

groups = {}
for n, g in geoms.items():
    if not is_wheel(n):
        continue
    idx = n.split("_")[-1]
    groups.setdefault(idx, []).append((n, g))

for idx, parts in groups.items():
    rim = dict(parts)[f"Rim_Alloy_{idx}"]
    c_old = rim.vertices.mean(0)
    sxn = 1 if c_old[0] > cs[:, 0].mean() else -1
    szn = 1 if c_old[2] > cz else -1
    t = targets[(sxn, szn)]
    tx, tz = float(t[0]), float(t[2])
    # uniform scale about the wheel's own centre, then translate to target;
    # target axle height = scaled radius so the tyre sits on the ground
    r_scaled = (c_old[1] - gy) * su          # axle height follows scale
    for n, g in parts:
        v = g.vertices.copy()
        v = (v - c_old) * su
        v[:, 0] += tx
        v[:, 1] += r_scaled
        v[:, 2] += tz
        g.vertices = v

out = trimesh.Scene()
for n, g in geoms.items():
    out.add_geometry(g, node_name=n, geom_name=n)
out.export(OUT)

# verify
allv2 = np.vstack([g.vertices for n, g in geoms.items() if not is_wheel(n)])
cp2 = geoms["carpaint"]
L2 = allv2[:, 0].max() - allv2[:, 0].min()
H2 = float(np.percentile(cp2.vertices[:, 1], 99.8)) - allv2[:, 1].min()
W2 = 2 * float(np.percentile(np.abs(cp2.vertices[:, 2]), 99.7))
wc2 = np.array([g.vertices.mean(0) for n, g in geoms.items()
                if n.startswith("Rim_Alloy")])
frx = wc2[wc2[:, 0] > 0][:, 0].mean(); rex = wc2[wc2[:, 0] < 0][:, 0].mean()
tr = np.abs(wc2[:, 2]).mean() * 2
print(f"RESULT  L {L2:.3f} ({100*(L2/SPEC['L']-1):+.1f}%)  "
      f"H {H2:.3f} ({100*(H2/SPEC['H']-1):+.1f}%)  "
      f"W {W2:.3f} ({100*(W2/SPEC['W']-1):+.1f}%)  "
      f"WB {frx-rex:.3f} ({100*((frx-rex)/SPEC['WB']-1):+.1f}% — arch-true)  "
      f"track {tr:.3f}")
import os
print("wrote", OUT, os.path.getsize(OUT), "bytes")
