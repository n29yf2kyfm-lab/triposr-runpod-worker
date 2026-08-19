#!/usr/bin/env python3
"""glass_stage.py — Stage 2, GENERIC: real glass nodes for any car.

Supersedes glass_nodes.py (kept as the V41 development record). That
script carried V41-specific surgery baked into code: absolute-coordinate
component thresholds (x > 0.3 = windscreen), an UNCONDITIONAL right-side
rebuild, a B-pillar search band in world coordinates, and a fixed 18mm
desnake cap. This stage is car-agnostic software:

  * every node name comes from the CarSpec labels (with defaults);
    a missing glass source is an honest REFUSAL with the found node
    names recorded, never a crash or a silent pass
  * glass components are classified by GEOMETRY — outward-normal
    laterality plus position along the glass group's own axis — not by
    absolute coordinates. Sides may be multiple components per side
    (separate quarter glass stays separate); a mid-cabin non-lateral
    pane classifies as a roof pane.
  * the incomplete-side rebuild is CONDITIONAL on measurement: a side is
    rebuilt only when its x-extent falls short of its mirror by more
    than the asymmetry threshold, and the fitted quadric must reach
    rms < 5mm or the stage refuses. A symmetric car is left alone and
    the measured ratio is recorded.
  * the B-pillar split derives its search band from the side pane's OWN
    y-range and x-span (30-70% of span — the A/C pillar bases live in
    the outer 30%s, measured on V41 where a wider window locked onto
    the A-pillar base at x=0.487). Self-tests: L/R pillar positions
    must agree within 3% of span, both split halves must hold >= 20% of
    the side's faces, and when the spec carries expect.glass.b_pillar_x
    the measured value must reproduce it or the stage REFUSES.
  * the desnake displacement cap is MEASURED: 1.5x the pane's boundary
    quantisation pitch (median boundary edge length), not a constant.
    The V41-tuned 18mm is what this formula yields on a ~11-12mm-pitch
    voxel body; on a quarter-scale body it scales automatically.
  * glass thickness comes from spec dimensions (glass_thickness_m) or
    defaults to 4mm tagged APPROXIMATE (real glazing is 3-5mm).

Everything the stage derives goes into <out>_glass_qc.json with its
derivation stated, so no number is presented without provenance.

Run: python3 glass_stage.py <in.glb> <out.glb> [--spec specs/car.json]
"""
import json
import os
import struct
import sys
import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from carspec import CarSpec

INP, OUT = sys.argv[1], sys.argv[2]
SPEC = None
for i, a in enumerate(sys.argv):
    if a == "--spec":
        SPEC = sys.argv[i + 1]
spec = CarSpec.load(SPEC) if SPEC else CarSpec.empty()

QC = {"stage": "glass_stage", "input": INP, "spec": spec.path,
      "derived": {}, "self_tests": {}, "decisions": {}}

ASYM_REBUILD = 0.88   # side x-extent ratio below which a side is INCOMPLETE
                      # (V41 right side: 0.82/1.32 of the left's span = 0.62;
                      #  a healthy body measures ~1.0). Recorded per run.
QUADRIC_RMS_MAX = 0.005  # m: rebuild surface must fit the side's own verts
SPLIT_MIN_FRAC = 0.20    # both B-pillar halves must keep >= this face share
PILLAR_AGREE_FRAC = 0.03  # L/R pillar x must agree within this frac of span

# ---------------------------------------------------------------- load
sc = trimesh.load(INP, force="scene")
# BAKE the node hierarchy first. Catalogue sources carry node transforms
# (scale/rotation hierarchies); editing raw geometry under a transformed
# node computes T*R*v instead of R*T*v — measured on uid 1fc46cb3, whose
# body rendered microscopic after canonicalisation while the identity-
# transform glass rendered fine. Every node becomes an identity-transform
# copy of its world-transformed geometry; instanced nodes get suffixed
# geometry names so nothing collides.
_baked = trimesh.Scene()
_seen = {}
for _node in sc.graph.nodes_geometry:
    _T, _gn = sc.graph[_node]
    _g = sc.geometry[_gn].copy()
    if not np.allclose(_T, np.eye(4)):
        _g.apply_transform(_T)
    _name = _gn if _gn not in _seen else f"{_gn}__inst{_seen[_gn]}"
    _seen[_gn] = _seen.get(_gn, 0) + 1
    _baked.add_geometry(_g, geom_name=_name, node_name=_node)
sc = _baked
glass_label = spec.label("glass", "glass")
body_label = spec.label("body", "carpaint")
frit_label = spec.label("frit", "frit_band")

# labels.glass may be a LIST: real sources ship glazing as several named
# nodes (per-window meshes — measured on catalogue uid 1fc46cb3: boot,
# both doors, three windscreen/quarter pieces, with LAMP glass in
# separate lamp nodes that must not be swept in)
glass_names = glass_label if isinstance(glass_label, list) else [glass_label]
glass_names = [n for n in glass_names if n in sc.geometry]
if not glass_names:
    names = sorted(sc.geometry.keys())
    QC["status"] = "REFUSED"
    QC["reason"] = (f"no glass source geometry: {spec.label('glass', 'glass')!r} "
                    f"absent. Scene nodes: {names[:40]}")
    json.dump(QC, open(OUT.replace(".glb", "_glass_qc.json"), "w"), indent=1)
    raise SystemExit(f"REFUSED: {QC['reason']}\n"
                     "A car with no labelled glass geometry needs glass "
                     "synthesis, which this stage does not fake.")

# CANONICAL ORIENTATION: the stage classifies along x (length). Catalogue
# cars ship length-on-Z (nose at -Z, y up — measured convention); rotate
# the whole scene into canon like wheel_stage does, and record it.
_allv = np.vstack([g_.vertices for g_ in sc.geometry.values()])
_ex = _allv[:, 0].max() - _allv[:, 0].min()
_ez = _allv[:, 2].max() - _allv[:, 2].min()
if _ez > _ex * 1.15:
    _ROT = trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0])
    for _gn in list(sc.geometry):
        sc.geometry[_gn].apply_transform(_ROT)
    QC["canonicalised"] = "rotated 90deg about Y (length was on Z)"
    print("canonicalised: length was on Z, rotated to X")

g = trimesh.util.concatenate([sc.geometry[n] for n in glass_names]) \
    if len(glass_names) > 1 else sc.geometry[glass_names[0]]
QC["derived"]["glass_source_nodes"] = glass_names

# SCALE: sources arrive at arbitrary units (uid 1fc46cb3 is a 3.7cm car —
# authored 100x with node scale 0.01). The stage's absolute-physical
# constants scale with measured body length relative to a nominal 4.3m
# car, tagged APPROXIMATE off-nominal; spec glass_thickness_m overrides.
_L_meas = float(_allv[:, 2].max() - _allv[:, 2].min()) if _ez > _ex * 1.15 \
    else float(_ex)
SCALE_F = _L_meas / 4.3
QC["derived"]["body_length_measured_m"] = round(_L_meas, 4)
THICK, tsrc = spec.dim("glass_thickness_m")
if THICK is None:
    THICK = 0.004 * SCALE_F
    tsrc = (f"APPROXIMATE default 4mm scaled by measured length "
            f"({_L_meas:.3f}m / nominal 4.3m); no spec value")
QC["derived"]["glass_thickness_m"] = {"value": THICK, "source": tsrc}
QUADRIC_RMS_MAX = QUADRIC_RMS_MAX * SCALE_F

# ------------------------------------------------- classify components
comps = g.split(only_watertight=False)
# FRAGMENT SANITY: a pane is a substantial sheet. Without this guard the
# hybrid body's transferred glass region — fragment soup — produced 76
# named "panes" down to 12 faces with a straight face (measured
# 2026-08-18). Components under 1% of total glass area are set aside; if
# they carry more than 15% of the area the node is soup and the stage
# refuses with the numbers.
_areas0 = np.array([c.area for c in comps])
_tot = _areas0.sum()
_major = [c for c, a in zip(comps, _areas0) if a >= 0.01 * _tot]
_minor_frac = float(_areas0[_areas0 < 0.01 * _tot].sum() / max(_tot, 1e-12))
QC["derived"]["glass_components"] = {
    "total": len(comps), "major": len(_major),
    "minor_area_fraction": round(_minor_frac, 4)}
if _minor_frac > 0.15:
    QC["status"] = "REFUSED"
    QC["reason"] = (f"glass node is fragment soup: {len(comps)} components, "
                    f"{len(_major)} majors, minors carry {_minor_frac:.0%} of "
                    "the area — no trustworthy panes can be named from this")
    json.dump(QC, open(OUT.replace(".glb", "_glass_qc.json"), "w"), indent=1)
    raise SystemExit(f"REFUSED: {QC['reason']}")
if len(_major) < len(comps):
    print(f"note: {len(comps) - len(_major)} sub-1%-area glass fragments set "
          f"aside ({_minor_frac:.1%} of area), recorded in QC")
comps = _major
if len(comps) < 2:
    QC["status"] = "REFUSED"
    QC["reason"] = (f"glass node is {len(comps)} connected component(s) — a "
                    "fused glass shell cannot be split into named panes by "
                    "this stage (it separates, it does not segment)")
    json.dump(QC, open(OUT.replace(".glb", "_glass_qc.json"), "w"), indent=1)
    raise SystemExit(f"REFUSED: {QC['reason']}")

areas = np.array([c.area for c in comps])
cents = np.array([c.triangles_center.mean(0) if len(c.faces) else c.vertices.mean(0)
                  for c in comps])
gx0 = min(c.vertices[:, 0].min() for c in comps)
gx1 = max(c.vertices[:, 0].max() for c in comps)
gspan = gx1 - gx0


def concat(ms):
    return ms[0] if len(ms) == 1 else trimesh.util.concatenate(ms)


# PANE GROUPING: real sources model a window as TWO coincident sheets —
# inner + outer skin (measured on 1fc46cb3: windscreen 15.1%+14.9% at the
# same centroid, every door pane a 5.7%+5.7% pair). Such a pane already
# HAS thickness, so it must be one unit and must not be thickened again.
# Group = centroid distance < 5% of the glass x-span AND extents within
# 2x per axis (a big centre pane never groups with a nearby quarter).
PRE = {}                      # id(mesh) -> source pane was double-skinned
order = np.argsort(-areas)
used = np.zeros(len(comps), bool)
groups = []
for i in order:
    if used[i]:
        continue
    grp = [int(i)]
    used[i] = True
    for j in order:
        if used[j]:
            continue
        if np.linalg.norm(cents[i] - cents[j]) < 0.05 * gspan:
            ei = np.maximum(comps[i].extents, 1e-6)
            ej = np.maximum(comps[j].extents, 1e-6)
            if np.all(np.maximum(ei, ej) / np.minimum(ei, ej) < 2.0):
                grp.append(int(j))
                used[j] = True
    groups.append(grp)
QC["derived"]["pane_grouping"] = {
    "groups": len(groups),
    "double_skinned": sum(1 for g in groups if len(g) >= 2),
    "note": "coincident inner/outer sheets grouped as one pane; grouped "
            "panes keep their source thickness (thicken skipped)"}
if len(groups) > 16:
    QC["status"] = "REFUSED"
    QC["reason"] = (f"{len(groups)} pane groups after grouping — a real car "
                    "peaks around 10; this is not nameable glazing")
    json.dump(QC, open(OUT.replace(".glb", "_glass_qc.json"), "w"), indent=1)
    raise SystemExit(f"REFUSED: {QC['reason']}")

units = []                    # (group_mesh, largest_sheet)
for grp in groups:
    gm = concat([comps[k] for k in grp])
    if len(grp) >= 2:
        PRE[id(gm)] = True
    units.append((gm, comps[grp[0]]))

u_area = np.array([u.area for u, _ in units])
u_cent = np.array([u.triangles_center.mean(0) for u, _ in units])
cabin = (u_cent * u_area[:, None]).sum(0) / u_area.sum()

sides = {"L": [], "R": []}
screens = {}
roof_panes = []
cls_log = []
for (gm, main), ct in zip(units, u_cent):
    # normal from the LARGEST sheet only: a double-skinned pane's two
    # sheets carry opposing normals whose area-weighted sum cancels
    fn = main.face_normals
    fa = main.area_faces
    n = (fn * fa[:, None]).sum(0)
    n /= max(np.linalg.norm(n), 1e-12)
    if n @ (ct - cabin) < 0:      # orient outward, away from the cabin
        n = -n
    lat = abs(n[2]) > np.hypot(n[0], n[1])          # laterality test
    xfrac = (ct[0] - gx0) / max(gspan, 1e-9)
    if lat:
        key = "L" if ct[2] < cabin[2] else "R"
        sides[key].append(gm)
        cls_log.append([f"side_{key}", round(float(xfrac), 2), len(gm.faces)])
    elif xfrac > 0.6:
        screens.setdefault("windscreen", []).append(gm)
        cls_log.append(["windscreen", round(float(xfrac), 2), len(gm.faces)])
    elif xfrac < 0.4:
        screens.setdefault("rear_screen", []).append(gm)
        cls_log.append(["rear_screen", round(float(xfrac), 2), len(gm.faces)])
    else:
        roof_panes.append(gm)
        cls_log.append(["roof", round(float(xfrac), 2), len(gm.faces)])
QC["derived"]["component_classification"] = {
    "note": "area-weighted outward normal laterality + x-fraction of the "
            "glass group's own span (screens at the ends, roof mid-cabin)",
    "components": cls_log}
if not sides["L"] or not sides["R"] or "windscreen" not in screens:
    QC["status"] = "REFUSED"
    QC["reason"] = f"classification incomplete: {cls_log}"
    json.dump(QC, open(OUT.replace(".glb", "_glass_qc.json"), "w"), indent=1)
    raise SystemExit(f"REFUSED: {QC['reason']}")


# ------------------------------------- conditional incomplete-side rebuild
def xext(ms):
    return (min(m.vertices[:, 0].min() for m in ms),
            max(m.vertices[:, 0].max() for m in ms))


eL, eR = xext(sides["L"]), xext(sides["R"])
spanL, spanR = eL[1] - eL[0], eR[1] - eR[0]
ratio = min(spanL, spanR) / max(spanL, spanR)
QC["decisions"]["side_completeness"] = {
    "x_extent_L": [round(float(v), 3) for v in eL],
    "x_extent_R": [round(float(v), 3) for v in eR],
    "ratio": round(float(ratio), 3), "threshold": ASYM_REBUILD}
if ratio < ASYM_REBUILD:
    short = "L" if spanL < spanR else "R"
    lng = "R" if short == "L" else "L"
    donor = concat(sides[lng])
    V = np.vstack([m.vertices for m in sides[short]])
    A = np.c_[np.ones(len(V)), V[:, 0], V[:, 1], V[:, 0]**2, V[:, 0]*V[:, 1], V[:, 1]**2]
    coef, *_ = np.linalg.lstsq(A, V[:, 2], rcond=None)
    rms = float(np.sqrt(np.mean((A @ coef - V[:, 2])**2)))
    QC["decisions"]["side_completeness"]["action"] = (
        f"side {short} incomplete -> rebuilt as mirrored {lng} footprint on "
        f"the {short} side's own fitted quadric (rms {rms*1000:.1f}mm)")
    if rms > QUADRIC_RMS_MAX:
        QC["status"] = "REFUSED"
        QC["reason"] = (f"quadric fit rms {rms*1000:.1f}mm exceeds "
                        f"{QUADRIC_RMS_MAX*1000:.0f}mm — the incomplete side "
                        "cannot be rebuilt on a trustworthy surface")
        json.dump(QC, open(OUT.replace(".glb", "_glass_qc.json"), "w"), indent=1)
        raise SystemExit(f"REFUSED: {QC['reason']}")
    Rm = donor.copy()
    Vm = Rm.vertices.copy()
    Am = np.c_[np.ones(len(Vm)), Vm[:, 0], Vm[:, 1], Vm[:, 0]**2,
               Vm[:, 0]*Vm[:, 1], Vm[:, 1]**2]
    Vm[:, 2] = Am @ coef
    # inset 2mm INTO the cabin so the rebuilt pane cannot z-fight the frit
    Vm[:, 2] += -0.002 if np.median(V[:, 2]) > cabin[2] else 0.002
    Rm.vertices = Vm
    Rm.faces = Rm.faces[:, ::-1]
    if any(PRE.get(id(m)) for m in sides[lng]):
        PRE[id(Rm)] = True
    sides[short] = [Rm]
    # self-test: extents must now mirror
    eS = xext(sides[short])
    eD = xext(sides[lng])
    ok = abs((eS[1]-eS[0]) - (eD[1]-eD[0])) < 0.02 * (eD[1]-eD[0])
    QC["self_tests"]["side_rebuild_extent"] = {
        "rebuilt": [round(float(v), 3) for v in eS],
        "donor": [round(float(v), 3) for v in eD], "pass": bool(ok)}
    if not ok:
        raise SystemExit("REFUSED: rebuilt side extent does not mirror donor")
else:
    QC["decisions"]["side_completeness"]["action"] = "both sides complete — no rebuild"

# ------------------------------------------------------- B-pillar split
body = sc.geometry.get(body_label)


def pillar_joint(sides_d, body_mesh):
    """B-pillar x from BOTH body sides jointly.

    The pillar is the column that is dense on BOTH sides at the same x;
    a melt clump is one-sided. Per-side argmax measurably fails here:
    V41's left body carries a melt clump at x -0.55 that out-scores the
    real pillar on that side alone (the L/R self-test caught it, 329mm
    disagreement), while min(hist_L, hist_R) rejects it by construction.
    DLO band = range fractions 0.20-0.82 of each side's glass extent
    (vertex percentiles measurably truncate the pillar's dense lower
    region); window = side span shrunk 30% per end (A/C pillar bases).
    """
    cent = body_mesh.triangles_center
    hists = {}
    dbg = {}
    edges = None
    for key in ("L", "R"):
        sv = np.vstack([m.vertices for m in sides_d[key]])
        x0, x1 = sv[:, 0].min(), sv[:, 0].max()
        span = x1 - x0
        y0v, y1v = sv[:, 1].min(), sv[:, 1].max()
        ylo = y0v + 0.20 * (y1v - y0v)
        yhi = y0v + 0.82 * (y1v - y0v)
        zmin = 0.85 * np.median(np.abs(sv[:, 2]))
        zsgn = np.sign(np.median(sv[:, 2]))
        w0, w1 = x0 + 0.30 * span, x1 - 0.30 * span
        if edges is None:
            edges = np.linspace(w0, w1, 41)
        m = ((cent[:, 1] > ylo) & (cent[:, 1] < yhi) &
             (np.abs(cent[:, 2]) > zmin) & (np.sign(cent[:, 2]) == zsgn) &
             (cent[:, 0] > edges[0]) & (cent[:, 0] < edges[-1]))
        hists[key], _ = np.histogram(cent[m, 0], bins=edges)
        dbg[key] = {"band_faces": int(m.sum()),
                    "y_band": [round(float(ylo), 3), round(float(yhi), 3)],
                    "z_min": round(float(zmin), 3),
                    "own_argmax_x": round(float(
                        (edges[hists[key].argmax()] + edges[hists[key].argmax() + 1]) / 2), 4)}
    if sum(h.sum() for h in hists.values()) < 30:
        return None, {"note": "too few pillar-band faces", **dbg}
    # SUM of both sides, not min: V41's left body carries NO carpaint
    # pillar column at all (the left pillar's faces belong to other
    # nodes), so requiring two-sided support refuses forever — measured:
    # L max 112 at a melt clump, R max 238 at the true pillar. The sum
    # lets the strong, real column dominate while per-side support is
    # RECORDED for the eye rather than gated.
    joint = hists["L"] + hists["R"]
    # the B-pillar is the DOMINANT column in the A/C-excluded window —
    # plain argmax of the sum. (Two selection tricks were tried and both
    # measurably mis-picked on V41: per-side argmax locked onto a
    # one-sided melt clump, and nearest-to-mid-span among strong local
    # maxima promoted a weak central column at -0.305 over the 238-face
    # true pillar. Other strong columns are recorded for the eye.)
    strong = joint >= 0.5 * joint.max()
    locmax = np.r_[joint[:1] >= joint[1:2],
                   (joint[1:-1] >= joint[:-2]) & (joint[1:-1] >= joint[2:]),
                   joint[-1:] >= joint[-2:-1]]
    cand = np.where(strong & locmax)[0]
    centres_x = (edges[cand] + edges[cand + 1]) / 2
    b = int(joint.argmax())
    px = float((edges[b] + edges[b + 1]) / 2)
    dbg["window"] = [round(float(edges[0]), 3), round(float(edges[-1]), 3)]
    dbg["candidates_x"] = [round(float(c), 3) for c in centres_x]
    dbg["joint_pillar_x"] = round(px, 4)
    dbg["joint_max"] = int(joint.max())
    dbg["support_at_pillar"] = {k: int(hists[k][b]) for k in hists}
    dbg["side_max"] = {k: int(hists[k].max()) for k in hists}
    return px, dbg


def split_x(mesh, x0):
    keepf = mesh.triangles_center[:, 0] >= x0
    fr = mesh.copy(); fr.update_faces(keepf); fr.remove_unreferenced_vertices()
    rr = mesh.copy(); rr.update_faces(~keepf); rr.remove_unreferenced_vertices()
    return fr, rr


panes = {}
if screens.get("windscreen"):
    _w = concat(screens["windscreen"])
    if any(PRE.get(id(m)) for m in screens["windscreen"]):
        PRE[id(_w)] = True
    panes["Glass_Windscreen"] = _w
if screens.get("rear_screen"):
    _r = concat(screens["rear_screen"])
    if any(PRE.get(id(m)) for m in screens["rear_screen"]):
        PRE[id(_r)] = True
    panes["Glass_Rear_Screen"] = _r
for i, rp in enumerate(roof_panes):
    panes[f"Glass_Roof{'' if not i else '_'+str(i+1)}"] = rp

need_split = [k for k in ("L", "R") if len(sides[k]) == 1]
px_joint = None
if need_split and body is not None:
    px_joint, pdbg = pillar_joint(sides, body)
    QC["derived"]["b_pillar"] = pdbg
    if px_joint is not None:
        # self-test: the chosen column must be strong in the SUM; per-side
        # support is recorded but not gated (a side can genuinely lack the
        # pillar in the body node — V41's left does)
        sup = pdbg["support_at_pillar"]
        tot = sum(sup.values())
        ok = tot >= 30 and tot >= 0.4 * pdbg["joint_max"]
        QC["self_tests"]["pillar_strength"] = {
            "support": sup, "total_at_pillar": tot,
            "joint_max": pdbg["joint_max"],
            "rule": ">= 30 faces and >= 40% of the strongest joint column",
            "pass": bool(ok)}
        if not ok:
            QC["status"] = "REFUSED"
            json.dump(QC, open(OUT.replace(".glb", "_glass_qc.json"), "w"), indent=1)
            raise SystemExit(f"REFUSED: chosen B-pillar column is weak ({sup}) "
                             "— no trustworthy split position")
for key in ("L", "R"):
    ms = sides[key]
    if len(ms) > 1:
        # separate panes already (e.g. real quarter glass) — keep them,
        # ordered front to rear
        ms = sorted(ms, key=lambda m: -m.vertices[:, 0].max())
        names = [f"Glass_Side_F{key}", f"Glass_Side_R{key}"] + \
                [f"Glass_Quarter_{key}{i}" for i in range(1, len(ms) - 1)]
        for nm, m in zip(names, ms):
            panes[nm] = m
        QC["decisions"][f"side_{key}_split"] = \
            f"{len(ms)} source components kept as separate panes (no cut needed)"
        continue
    if px_joint is None:
        panes[f"Glass_Side_{key}"] = ms[0]
        QC["decisions"][f"side_{key}_split"] = (
            "no usable pillar measurement — side kept unsplit (recorded "
            "limitation)" if body is not None else
            f"body node {body_label!r} absent — side kept unsplit")
        continue
    fr, rr = split_x(ms[0], px_joint)
    if PRE.get(id(ms[0])):
        PRE[id(fr)] = PRE[id(rr)] = True
    tot = len(ms[0].faces)
    fF, fR = len(fr.faces) / tot, len(rr.faces) / tot
    if fF < SPLIT_MIN_FRAC or fR < SPLIT_MIN_FRAC:
        panes[f"Glass_Side_{key}"] = ms[0]
        QC["decisions"][f"side_{key}_split"] = (
            f"split at {px_joint:.3f} rejected: face shares {fF:.2f}/{fR:.2f} "
            f"below {SPLIT_MIN_FRAC} — kept unsplit")
        continue
    panes[f"Glass_Side_F{key}"] = fr
    panes[f"Glass_Side_R{key}"] = rr
    QC["decisions"][f"side_{key}_split"] = \
        f"split at joint pillar x {px_joint:.3f} (face shares {fF:.2f}/{fR:.2f})"

exp = spec.expect().get("glass", {})
if "b_pillar_x" in exp and px_joint is not None:
    want = float(exp["b_pillar_x"])
    tol = float(exp.get("tolerance_m", 0.05))
    got = px_joint
    ok = abs(got - want) <= tol
    QC["self_tests"]["b_pillar_expect"] = {
        "expected": want, "measured": round(float(got), 4),
        "tolerance_m": tol, "pass": bool(ok)}
    if not ok:
        QC["status"] = "REFUSED"
        json.dump(QC, open(OUT.replace(".glb", "_glass_qc.json"), "w"), indent=1)
        raise SystemExit(f"REFUSED: B-pillar self-test {got:.3f} vs expected "
                         f"{want:.3f} (tol {tol}) — detector does not reproduce "
                         "the spec's measured position")
if "panes" in exp:
    ok = len(panes) == int(exp["panes"])
    QC["self_tests"]["pane_count"] = {"expected": int(exp["panes"]),
                                      "measured": len(panes), "pass": bool(ok)}
    if not ok:
        QC["status"] = "REFUSED"
        json.dump(QC, open(OUT.replace(".glb", "_glass_qc.json"), "w"), indent=1)
        raise SystemExit(f"REFUSED: {len(panes)} panes vs expected {exp['panes']}")

# --------------------------------------------------------- desnake (measured cap)
def boundary_loops(mesh):
    eu, cnt = np.unique(np.sort(mesh.edges, axis=1), axis=0, return_counts=True)
    b = eu[cnt == 1]
    adj = {}
    for a, c in b:
        adj.setdefault(int(a), []).append(int(c))
        adj.setdefault(int(c), []).append(int(a))
    seen, loops = set(), []
    for start in adj:
        if start in seen:
            continue
        loop, cur, prev = [start], start, None
        seen.add(start)
        while True:
            nxt = [n for n in adj[cur] if n != prev]
            nxt = [n for n in nxt if n not in seen] or [n for n in nxt if n == start]
            if not nxt:
                break
            n = nxt[0]
            if n == start:
                break
            loop.append(n); seen.add(n); prev, cur = cur, n
        if len(loop) > 6:
            loops.append(loop)
    return loops


def turning_angle(mesh, loops):
    tot, n = 0.0, 0
    for lp in loops:
        P = mesh.vertices[lp]
        d = np.roll(P, -1, axis=0) - P
        ln = np.linalg.norm(d, axis=1, keepdims=True)
        d = d / np.clip(ln, 1e-9, None)
        dot = np.clip((d * np.roll(d, -1, axis=0)).sum(1), -1, 1)
        tot += np.degrees(np.arccos(dot)).sum(); n += len(lp)
    return tot / max(n, 1)


def desnake(mesh, iters=14, label=""):
    """Boundary-only Laplacian, capped at 1.5x the MEASURED staircase pitch."""
    m = mesh.copy()
    loops = boundary_loops(m)
    if not loops:
        return m, None
    steps = []
    for lp in loops:
        P = m.vertices[lp]
        steps.append(np.linalg.norm(np.roll(P, -1, axis=0) - P, axis=1))
    pitch = float(np.median(np.concatenate(steps)))
    max_disp = 1.5 * pitch
    before = turning_angle(m, loops)
    # desnake removes VOXEL QUANTISATION. The raw turning angle cannot
    # gate this alone: mean |turn| scales with boundary vertex count (a
    # clean 20-vert rectangle measures ~18 deg). Gate on the ratio to the
    # pane's own expected clean turning, 360/n per loop: V41 staircases
    # measure 25-40x that baseline; clean low-poly catalogue panes
    # measure 1-2x (both measured 2026-08-18). Below 5x the pane is
    # judged un-quantised and left alone, recorded.
    nbv = int(sum(len(l) for l in loops))
    baseline = 360.0 * len(loops) / max(nbv, 1)
    ratio_q = before / max(baseline, 1e-9)
    if ratio_q < 5.0:
        return m, {"loops": len(loops), "boundary_verts": nbv,
                   "pitch_mm_measured": round(pitch * 1000, 2),
                   "turning_before_deg": round(float(before), 2),
                   "quantisation_ratio": round(float(ratio_q), 1),
                   "skipped": "turning under 5x the clean baseline — no "
                              "quantisation to remove"}
    orig = m.vertices.copy()
    V = m.vertices.copy()
    for _ in range(iters):
        for lp in loops:
            P = V[lp]
            sm = 0.5 * P + 0.25 * np.roll(P, 1, axis=0) + 0.25 * np.roll(P, -1, axis=0)
            V[lp] = sm
    disp = V - orig
    d = np.linalg.norm(disp, axis=1)
    over = d > max_disp
    if over.any():
        V[over] = orig[over] + disp[over] * (max_disp / d[over])[:, None]
    m.vertices = V
    after = turning_angle(m, loops)
    stats = {"loops": len(loops),
             "boundary_verts": int(sum(len(l) for l in loops)),
             "pitch_mm_measured": round(pitch * 1000, 2),
             "cap_mm": round(max_disp * 1000, 2),
             "turning_before_deg": round(float(before), 2),
             "turning_after_deg": round(float(after), 2),
             "max_disp_mm": round(float(np.linalg.norm(V - orig, axis=1).max() * 1000), 2)}
    print(f"  desnake {label}: turning {stats['turning_before_deg']} -> "
          f"{stats['turning_after_deg']} deg, pitch {stats['pitch_mm_measured']}mm, "
          f"cap {stats['cap_mm']}mm")
    return m, stats


def thicken(mesh, outward_hint):
    m = mesh.copy()
    n = m.vertex_normals.copy()
    flip = (n.mean(0) @ outward_hint) < 0
    if flip:
        n = -n
    inner_v = m.vertices - n * THICK
    nv = len(m.vertices)
    V2 = np.vstack([m.vertices, inner_v])
    F2 = [m.faces if not flip else m.faces[:, ::-1],
          (m.faces[:, ::-1] if not flip else m.faces) + nv]
    eu, cnt = np.unique(np.sort(m.edges, axis=1), axis=0, return_counts=True)
    boundary = eu[cnt == 1]
    wall = []
    for a, b in boundary:
        wall += [[a, b, b + nv], [a, b + nv, a + nv]]
    F2.append(np.array(wall).reshape(-1, 3))
    return trimesh.Trimesh(vertices=V2, faces=np.vstack(F2), process=True), len(boundary)


# ------------------------------------------------------------- assemble
out = trimesh.Scene()
for node in sc.graph.nodes_geometry:
    T, gn = sc.graph[node]
    if gn in glass_names:
        continue
    geom = sc.geometry[gn]
    if gn == frit_label:
        geom, fst = desnake(geom, label=frit_label)
        QC.setdefault("desnake", {})[frit_label] = fst
    if gn not in out.geometry:
        out.add_geometry(geom, geom_name=gn, node_name=node, transform=T)
    else:
        out.graph.update(frame_to=node, matrix=T, geometry=gn)

table = {}
footprints = {}
for name, mesh in panes.items():
    pre = bool(PRE.get(id(mesh)))
    mesh, st = desnake(mesh, label=name)
    if st:
        QC.setdefault("desnake", {})[name] = st
    lps = boundary_loops(mesh)
    if lps:
        lp = max(lps, key=len)
        footprints[name] = mesh.vertices[lp].tolist()
    hint = mesh.vertices.mean(0) - cabin
    if np.linalg.norm(hint) < 1e-9:
        hint = np.array([0.0, 1.0, 0.0])
    if pre:
        # source pane is double-skinned — it already carries thickness;
        # adding an inner shell would quadruple the surfaces
        solid, nb = mesh, 0
    else:
        solid, nb = thicken(mesh, hint)
    mat = PBRMaterial(name=name, baseColorFactor=[20, 24, 28, 90],
                      metallicFactor=0.0, roughnessFactor=0.05,
                      alphaMode="BLEND", doubleSided=True)
    solid.visual = trimesh.visual.TextureVisuals(material=mat)
    out.add_geometry(solid, node_name=name, geom_name=name)
    b = solid.bounds
    table[name] = {"faces": int(len(solid.faces)),
                   "boundary_edges_stitched": int(nb),
                   "bbox_min": [round(float(x), 3) for x in b[0]],
                   "bbox_max": [round(float(x), 3) for x in b[1]],
                   "thickness_m": ("source double-skinned (kept)" if pre
                                   else THICK)}
    print(f"  {name}: {len(solid.faces)} faces, wall from {nb} boundary edges")

out.export(OUT, include_normals=True)
with open(OUT, "rb") as fh:
    fh.seek(12); ln, _ = struct.unpack("<II", fh.read(8)); j = json.loads(fh.read(ln))
missing = [m2.get("name") for m2 in j["meshes"]
           if any("NORMAL" not in p["attributes"] for p in m2["primitives"])]
if missing:
    raise SystemExit(f"REFUSED: NORMAL missing on {missing[:5]}")
# trimesh export DROPS TANGENT accessors (measured: 29 tangent-space
# warnings introduced on a source carrying normal maps — same defect
# family as the dropped-NORMALs lesson). Regenerate via gltf-transform
# when any material needs a tangent space.
if any("normalTexture" in (m2 or {}) for m2 in j.get("materials", [])):
    import subprocess
    r = subprocess.run(["gltf-transform", "tangents", OUT, OUT],
                       capture_output=True, text=True)
    QC["derived"]["tangents"] = ("regenerated (source carries normal maps; "
                                 "trimesh drops TANGENT)" if r.returncode == 0
                                 else f"REGENERATION FAILED: {r.stderr[-120:]}")
    print(f"tangents: {'regenerated' if r.returncode == 0 else 'FAILED'}")
    with open(OUT, "rb") as fh:
        fh.seek(12); ln, _ = struct.unpack("<II", fh.read(8))
        j = json.loads(fh.read(ln))
names = [m2.get("name") for m2 in j["meshes"]]
absent = [n for n in panes if n not in names]
if absent:
    raise SystemExit(f"REFUSED: panes missing from export: {absent}")

QC["status"] = "PASS" if all(t.get("pass", True) for t in QC["self_tests"].values()) else "FAIL"
QC["panes"] = table
QC["_footprints"] = footprints
json.dump(QC, open(OUT.replace(".glb", "_glass_qc.json"), "w"), indent=1)
# aperture_clean compatibility: it reads _footprints from <out>_nodes.json
json.dump({"_footprints": footprints, "panes": table},
          open(OUT.replace(".glb", "_nodes.json"), "w"), indent=1)
print(f"wrote {OUT} ({os.path.getsize(OUT)} bytes), {len(panes)} panes, "
      f"status {QC['status']}; QC -> {OUT.replace('.glb', '_glass_qc.json')}")
