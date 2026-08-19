#!/usr/bin/env python3
"""canon_dims.py — Stage 0: canonical frame, canonical names, spec dims.

Forensic findings this stage exists to fix (Yaris premium run, 2026-08-19):

  * TRACK GATES FAILED HONESTLY because the generated body is narrower
    than the real car: the width budget was consumed by mirror tips, so
    the FLANK sat at 1.55m against a real 1.695m body and the flank guard
    had to tuck the wheels 150mm/side inside spec. The correction belongs
    UPSTREAM of the wheel stage: scale the body so its FLANK (p99.7 of
    |z|, measured below 0.75H so mirror pods are excluded) matches the
    spec body width. Same argument for height (p99.8, aerial-immune) and
    length. This is align_dims.py's method made car-agnostic: that script
    carries the Golf's spec and the V41 node names as literals and is
    kept as history.
  * HALF THE STAGE FAMILY assumes the body node is literally named
    "carpaint" (rear_lamps4, rear_separate, front_kit, interior_kit
    pre-hardening). A labelled hybrid car names it "body". Renaming ONCE
    here — geometry and node — makes the whole family compatible instead
    of patching lookups file by file.
  * wheel_stage grew its own length-on-Z rotation and z-centring guards;
    doing frame canon here as well makes every stage's input canonical
    (length on X, Y up, z straddling 0, ground at y=0) so no stage needs
    to trust another's guard.

Everything measured/derived lands in <out>_canon_qc.json with provenance.
Scales are corrections toward PUBLISHED dims and are recorded per axis;
a scale beyond +-20% is refused as a likely axis mix-up, not applied.

Run: python3 canon_dims.py <in.glb> <out.glb> [--spec specs/car.json]
"""
import json
import os
import sys
import numpy as np
import trimesh

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from carspec import CarSpec

INP, OUT = sys.argv[1], sys.argv[2]
SPEC = None
for i, a in enumerate(sys.argv):
    if a == "--spec":
        SPEC = sys.argv[i + 1]
spec = CarSpec.empty() if SPEC is None else CarSpec.load(SPEC)
QC = {"stage": "canon_dims", "input": INP, "spec": spec.path, "derived": {}}

sc = trimesh.load(INP, force="scene")

# ---- canonical names: body node -> 'carpaint' ---------------------------
# labels.input_body names the body node AS DELIVERED by the label source;
# after this stage the canonical name is always 'carpaint', so downstream
# stages use their defaults and the spec never has to describe both worlds.
body_label = spec.label("input_body", spec.label("body", "carpaint"))
renamed = False
if body_label != "carpaint" and body_label in sc.geometry:
    if "carpaint" in sc.geometry:
        raise SystemExit("REFUSED: both a 'carpaint' node and a spec body "
                         f"node {body_label!r} exist — ambiguous")
    g = sc.geometry.pop(body_label)
    sc.geometry["carpaint"] = g
    # rebuild the graph edge under the new name
    T, _ = sc.graph[body_label]
    sc.graph.transforms.remove_node(body_label)
    sc.graph.update(frame_to="carpaint", matrix=(np.eye(4) if T is None else T),
                    geometry="carpaint")
    renamed = True
QC["derived"]["body_renamed"] = f"{body_label} -> carpaint" if renamed \
    else "already canonical"
if "carpaint" not in sc.geometry:
    raise SystemExit(f"REFUSED: no body node ({body_label!r} or 'carpaint') "
                     f"in scene: {sorted(sc.geometry)[:20]}")

# ---- bake node transforms so vertex edits are world-true ----------------
for node in list(sc.graph.nodes_geometry):
    T, gn = sc.graph[node]
    if T is not None and not np.allclose(T, np.eye(4)):
        sc.geometry[gn].apply_transform(T)
        sc.graph.update(frame_to=node, matrix=np.eye(4), geometry=gn)

geoms = dict(sc.geometry.items())
allv = np.vstack([g.vertices for g in geoms.values()])

# ---- canonical frame ----------------------------------------------------
ops = []
ex = allv[:, 0].max() - allv[:, 0].min()
ez = allv[:, 2].max() - allv[:, 2].min()
if ez > ex * 1.15:
    R = trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0])
    for g in geoms.values():
        g.apply_transform(R)
    allv = np.vstack([g.vertices for g in geoms.values()])
    ops.append("rotated 90deg about Y (length was on Z)")
zmid = float((allv[:, 2].max() + allv[:, 2].min()) / 2)
zw = float(allv[:, 2].max() - allv[:, 2].min())
if abs(zmid) > 0.02 * zw:
    for g in geoms.values():
        g.apply_translation([0.0, 0.0, -zmid])
    allv = np.vstack([g.vertices for g in geoms.values()])
    ops.append(f"z recentred by {-zmid:+.3f}")
gy = float(allv[:, 1].min())
if abs(gy) > 1e-4:
    for g in geoms.values():
        g.apply_translation([0.0, -gy, 0.0])
    allv = np.vstack([g.vertices for g in geoms.values()])
    ops.append(f"grounded (y shifted {-gy:+.3f})")

# ---- NOSE at +X, enforced -----------------------------------------------
# Every downstream stage assumes it (glass_stage names screens by xfrac,
# front_kit builds at XMAX, rear_lamps4 at XMIN, detect_fused calls the
# higher-x axle "front") and nothing verified it — a nose-at--X car would
# get its headlamps on the tailgate with no refusal. When a glass label
# exists, resolve it: of the two end-facing glazing clusters, the
# WINDSCREEN has the larger area and the more raked (up-tilted) normals —
# true across hatch/saloon/SUV. Flip 180deg about Y only on a confident
# ratio; otherwise record the ambiguity and leave the frame alone.
glass_label = spec.label("glass", "glass")
if glass_label in geoms:
    gg = geoms[glass_label]
    fn = gg.face_normals
    fa = gg.area_faces
    fc = gg.triangles_center
    endish = np.abs(fn[:, 0]) >= 0.30
    xmid = float((allv[:, 0].max() + allv[:, 0].min()) / 2)
    score = {}
    for tag, m in (("high", endish & (fc[:, 0] > xmid)),
                   ("low", endish & (fc[:, 0] <= xmid))):
        if m.sum() < 50:
            score[tag] = 0.0
            continue
        area = float(fa[m].sum())
        rake = float(np.average(np.abs(fn[m, 1]), weights=fa[m]))
        score[tag] = area * (0.5 + rake)
    QC["derived"]["nose_check"] = {
        "score_high_x": round(score.get("high", 0.0), 4),
        "score_low_x": round(score.get("low", 0.0), 4),
        "rule": "windscreen = larger area x more raked end cluster"}
    hi, lo = score.get("high", 0.0), score.get("low", 0.0)
    if lo > 1.3 * hi and lo > 0:
        R180 = trimesh.transformations.rotation_matrix(np.pi, [0, 1, 0])
        for g in geoms.values():
            g.apply_transform(R180)
        allv = np.vstack([g.vertices for g in geoms.values()])
        ops.append("flipped 180deg about Y (windscreen was at low x)")
        QC["derived"]["nose_check"]["action"] = "flipped"
    elif hi >= lo:
        QC["derived"]["nose_check"]["action"] = "nose already at +X"
    else:
        QC["derived"]["nose_check"]["action"] = (
            "AMBIGUOUS (ratio under 1.3) — frame left alone, check the render")
QC["derived"]["frame_ops"] = ops or ["already canonical"]

# ---- dims to spec -------------------------------------------------------
cp = geoms["carpaint"].vertices
H_now = float(np.percentile(cp[:, 1], 99.8))
L_now = float(allv[:, 0].max() - allv[:, 0].min())
flank = cp[cp[:, 1] < 0.75 * H_now]            # mirrors sit high: excluded
W_now = 2 * float(np.percentile(np.abs(flank[:, 2]), 99.7))
tgt = {}
for key, now in (("length_m", L_now), ("height_m", H_now), ("width_m", W_now)):
    val, src = spec.dim(key)
    tgt[key] = {"measured": round(now, 4), "spec": val, "source": src,
                "scale": round(val / now, 4) if val else 1.0}
sx = tgt["length_m"]["scale"]
sy = tgt["height_m"]["scale"]
sz = tgt["width_m"]["scale"]
for name, s in (("x", sx), ("y", sy), ("z", sz)):
    if not (0.8 <= s <= 1.2):
        raise SystemExit(f"REFUSED: {name} scale {s} outside +-20% — "
                         "likely an axis mix-up, inspect the input")
cx = float((allv[:, 0].max() + allv[:, 0].min()) / 2)
for g in geoms.values():
    v = g.vertices.copy()
    v[:, 0] = (v[:, 0] - cx) * sx + cx
    v[:, 1] = v[:, 1] * sy
    v[:, 2] = v[:, 2] * sz
    g.vertices = v
QC["derived"]["dims"] = tgt
print(f"dims: L {L_now:.3f}->x{sx}  H {H_now:.3f}->x{sy}  "
      f"W(flank) {W_now:.3f}->x{sz}")

# ---- DETAPER: per-slice width correction of the perspective bake --------
# Single-image generators bake camera perspective into the mesh: the far
# end comes out narrower (measured on this Yaris: rear half-width 25%
# under the front, axle zones 0.72 vs mid-flank 0.85 after global scale).
# A real hatchback's sides are near-parallel — width at both axles is
# within a few percent of max width — so the profile correction target is
# CONSTANT spec width over the wheelbase span, blending to the measured
# shape only in the bumper zones. Per-slice z scale, capped and smoothed;
# everything measured is recorded. This corrects a documented distortion
# toward published dims; it does not invent styling.
cp = geoms["carpaint"].vertices
H2m = float(np.percentile(cp[:, 1], 99.8))
x0, x1 = float(cp[:, 0].min()), float(cp[:, 0].max())
Lc = x1 - x0
nb = 48
edges = np.linspace(x0, x1, nb + 1)
mids = (edges[:-1] + edges[1:]) / 2
flank_pts = cp[cp[:, 1] < 0.75 * H2m]
prof = np.full(nb, np.nan)
bi = np.clip(np.searchsorted(edges, flank_pts[:, 0]) - 1, 0, nb - 1)
for b in range(nb):
    sel = bi == b
    if sel.sum() >= 40:
        prof[b] = float(np.percentile(np.abs(flank_pts[sel, 2]), 99))
spec_half = (spec.dim("width_m")[0] or (2 * np.nanmax(prof))) / 2
# parallel-side span: exclude the bumper blends (nose 8%, tail 12% —
# the tail carries the hatch tumblehome)
core = (mids > x0 + 0.12 * Lc) & (mids < x1 - 0.08 * Lc) & ~np.isnan(prof)
s_bin = np.ones(nb)
s_bin[core] = np.clip(spec_half / prof[core], 0.97, 1.30)
# ends: hold the last core correction so the bumper keeps its plan taper
idx_core = np.where(core)[0]
if len(idx_core):
    s_bin[:idx_core[0]] = s_bin[idx_core[0]]
    s_bin[idx_core[-1] + 1:] = s_bin[idx_core[-1]]
from scipy.ndimage import gaussian_filter1d
s_bin = gaussian_filter1d(s_bin, 1.5, mode="nearest")
corr = {"max_scale": round(float(s_bin.max()), 4),
        "min_scale": round(float(s_bin.min()), 4),
        "profile_before": [round(float(p), 4) if not np.isnan(p) else None
                           for p in prof]}
if s_bin.max() > 1.005:
    for g in geoms.values():
        v = g.vertices.copy()
        sv = np.interp(v[:, 0], mids, s_bin)
        v[:, 2] = v[:, 2] * sv
        g.vertices = v
    print(f"detaper: per-slice z x[{corr['min_scale']}..{corr['max_scale']}] "
          f"over {int(core.sum())} core bins")
else:
    print("detaper: profile already parallel — no correction")
QC["derived"]["detaper"] = corr

# renormalise overall width after the detaper: the per-bin p99 targets do
# not equal the global p99.7 the dims verify measures (run3 measured the
# mismatch at +2.6% and the verify correctly refused). One uniform z
# scale restores the global statistic while keeping the parallel profile.
cp = geoms["carpaint"].vertices
H3 = float(np.percentile(cp[:, 1], 99.8))
fl3 = cp[cp[:, 1] < 0.75 * H3]
W3 = 2 * float(np.percentile(np.abs(fl3[:, 2]), 99.7))
specW = spec.dim("width_m")[0]
if specW and abs(W3 / specW - 1) > 0.002:
    sz3 = specW / W3
    for g in geoms.values():
        v = g.vertices.copy()
        v[:, 2] *= sz3
        g.vertices = v
    QC["derived"]["detaper"]["width_renorm"] = round(sz3, 4)
    print(f"detaper width renorm: x{sz3:.4f}")

out = trimesh.Scene()
for n, g in geoms.items():
    out.add_geometry(g, geom_name=n, node_name=n)
out.export(OUT, include_normals=True)

# verify from the exported file
sc2 = trimesh.load(OUT, force="scene")
cp2 = sc2.geometry["carpaint"].vertices
H2 = float(np.percentile(cp2[:, 1], 99.8))
fl2 = cp2[cp2[:, 1] < 0.75 * H2]
W2 = 2 * float(np.percentile(np.abs(fl2[:, 2]), 99.7))
av2 = np.vstack([g.vertices for g in sc2.geometry.values()])
L2 = float(av2[:, 0].max() - av2[:, 0].min())
QC["verified"] = {"L": round(L2, 4), "H": round(H2, 4), "W_flank": round(W2, 4)}
for key, got in (("length_m", L2), ("height_m", H2), ("width_m", W2)):
    val, _ = spec.dim(key)
    if val and abs(got / val - 1) > 0.01:
        raise SystemExit(f"REFUSED: post-scale {key} {got:.4f} vs spec {val} "
                         "outside 1% — verify failed")
print(f"verified: L {L2:.3f} H {H2:.3f} W(flank) {W2:.3f} — all within 1% of spec")
json.dump(QC, open(OUT.replace(".glb", "_canon_qc.json"), "w"), indent=1)
print(f"wrote {OUT}")
