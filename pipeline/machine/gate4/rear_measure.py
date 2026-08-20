#!/usr/bin/env python3
"""rear_measure.py — measure the REAR zone with the orientation VERIFIED by render.

Established by render (base_shaded_az270 = FRONT, base_shaded_az090 = REAR):
this file has its NOSE at -X and its TAIL at +X. That is the OPPOSITE of the
machine's documented canon frame, which rear_lamps4.py/rear_kit.py assume when
they build at XMIN. Recorded, not assumed.

Also runs canon_dims' own nose rule on this car to see what it would decide.

Run: python3 rear_measure.py <glb>
"""
import json
import sys
import numpy as np
import trimesh

GLB = sys.argv[1] if len(sys.argv) > 1 else "car.glb"
sc = trimesh.load(GLB, force="scene")
G = dict(sc.geometry)
rep = {"orientation_evidence": "render az270=FRONT, az090=REAR -> tail at +X"}

allv = np.vstack([g.vertices for g in G.values()])
XMIN, XMAX = float(allv[:, 0].min()), float(allv[:, 0].max())
GY = float(allv[:, 1].min()); YMAX = float(allv[:, 1].max())
H = YMAX - GY; L = XMAX - XMIN
HW = float(np.percentile(np.abs(allv[:, 2]), 99.7))
rep["frame"] = dict(L=L, H=H, halfW=HW, xmin=XMIN, xmax=XMAX, tail_x=XMAX)
print(f"FRAME L={L:.4f} H={H:.4f} halfW={HW:.4f}; TAIL at x={XMAX:.3f}")

# ---- canon_dims' own nose rule, run verbatim on this car ----
gg = G["glass"]; fn = gg.face_normals; fa = gg.area_faces; fc = gg.triangles_center
endish = np.abs(fn[:, 0]) >= 0.30
xmid = (XMAX + XMIN) / 2
score = {}
for tag, m in (("high", endish & (fc[:, 0] > xmid)), ("low", endish & (fc[:, 0] <= xmid))):
    if m.sum() < 50:
        score[tag] = 0.0; continue
    score[tag] = float(fa[m].sum()) * (0.5 + float(np.average(np.abs(fn[m, 1]), weights=fa[m])))
print(f"canon_dims nose rule: score_high_x={score['high']:.4f} score_low_x={score['low']:.4f} "
      f"-> ratio low/high = {score['low']/max(score['high'],1e-9):.3f} "
      f"({'would FLIP (nose is at -X)' if score['low'] > 1.3*score['high'] else 'NOT confident -> leaves frame alone'})")
rep["canon_nose_rule"] = dict(high=score["high"], low=score["low"],
                              ratio_low_over_high=score["low"] / max(score["high"], 1e-9))

# ---- glass clusters: find the REAR SCREEN ----
xf = (fc[:, 0] - XMIN) / L
rear_glass = xf > 0.72
print(f"\nGLASS: total {gg.area:.4f} m2 in {len(gg.faces)} faces")
print(f"  rear-third (xf>0.72): {fa[rear_glass].sum():.4f} m2, {int(rear_glass.sum())} faces, "
      f"x[{fc[rear_glass,0].min():.3f},{fc[rear_glass,0].max():.3f}] "
      f"y[{fc[rear_glass,1].min():.3f},{fc[rear_glass,1].max():.3f}] "
      f"z[{fc[rear_glass,2].min():.3f},{fc[rear_glass,2].max():.3f}]")
rep["rear_glass"] = dict(area=float(fa[rear_glass].sum()), faces=int(rear_glass.sum()),
                         x=[float(fc[rear_glass, 0].min()), float(fc[rear_glass, 0].max())],
                         y=[float(fc[rear_glass, 1].min()), float(fc[rear_glass, 1].max())],
                         z=[float(fc[rear_glass, 2].min()), float(fc[rear_glass, 2].max())])

# ---- REAR-FACING skin: z-buffer from +X (what the tail view actually sees) ----
# immune to material names and to face normals (the two things Gate 5 forbade)
CELL = 0.006
pts, src, area = [], [], []
for n, g in G.items():
    c = g.triangles_center
    m = c[:, 0] > XMAX - 0.35 * L
    pts.append(c[m]); src += [n] * int(m.sum()); area.append(g.area_faces[m])
P = np.vstack(pts); src = np.array(src); AR = np.concatenate(area)
iy = np.floor((P[:, 1] - GY) / CELL).astype(int)
iz = np.floor((P[:, 2] + HW + 0.1) / CELL).astype(int)
key = iy.astype(np.int64) * 100000 + iz
order = np.lexsort((-P[:, 0], key))       # within each cell, largest x first
ks = key[order]
first = np.ones(len(ks), bool); first[1:] = ks[1:] != ks[:-1]
vis = order[first]                        # nearest-to-camera face per cell
print(f"\nREAR-VISIBLE SKIN ({CELL*1000:.0f}mm cells, camera at +X): {len(vis)} cells")
for n in G:
    s = src[vis] == n
    print(f"  {n}: {int(s.sum())} cells ({100*s.mean():.1f}%)")
    rep.setdefault("rear_visible_by_material", {})[n] = int(s.sum())

# ---- rear-face WIDTH profile by height (for the lamp-band width criterion) --
tailx = P[:, 0] > XMAX - 0.10 * L
print(f"\nREAR-FACE WIDTH PROFILE (faces within 10% of length of the tail, {int(tailx.sum())} faces):")
prof = {}
for f0, f1 in [(.20, .30), (.30, .40), (.40, .50), (.50, .60), (.60, .70), (.70, .80)]:
    s = tailx & (P[:, 1] > GY + f0 * H) & (P[:, 1] < GY + f1 * H)
    if s.sum() < 50:
        continue
    w = float(np.percentile(P[s, 2], 99.0) - np.percentile(P[s, 2], 1.0))
    prof[f"{f0:.2f}-{f1:.2f}"] = w
    print(f"  y {f0:.2f}-{f1:.2f}H: width {w:.4f} m ({int(s.sum())} faces)")
rep["rear_face_width_profile"] = prof

json.dump(rep, open("rear_measure.json", "w"), indent=1)
print("\nwrote rear_measure.json")
