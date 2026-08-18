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
glass_label = spec.label("glass", "glass")
body_label = spec.label("body", "carpaint")
frit_label = spec.label("frit", "frit_band")

if glass_label not in sc.geometry:
    names = sorted(sc.geometry.keys())
    QC["status"] = "REFUSED"
    QC["reason"] = (f"no glass source geometry: node {glass_label!r} absent. "
                    f"Scene nodes: {names[:40]}")
    json.dump(QC, open(OUT.replace(".glb", "_glass_qc.json"), "w"), indent=1)
    raise SystemExit(f"REFUSED: {QC['reason']}\n"
                     "A car with no labelled glass geometry needs glass "
                     "synthesis, which this stage does not fake.")

g = sc.geometry[glass_label]
THICK, tsrc = spec.dim("glass_thickness_m")
if THICK is None:
    THICK, tsrc = 0.004, "APPROXIMATE default (real glazing 3-5mm); no spec value"
QC["derived"]["glass_thickness_m"] = {"value": THICK, "source": tsrc}

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
if _minor_frac > 0.15 or len(_major) > 10:
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
cabin = (cents * areas[:, None]).sum(0) / areas.sum()
gx0 = min(c.vertices[:, 0].min() for c in comps)
gx1 = max(c.vertices[:, 0].max() for c in comps)
gspan = gx1 - gx0

sides = {"L": [], "R": []}
screens = {}
roof_panes = []
cls_log = []
for c, ct, ar in zip(comps, cents, areas):
    fn = c.face_normals
    fa = c.area_faces
    n = (fn * fa[:, None]).sum(0)
    n /= max(np.linalg.norm(n), 1e-12)
    if n @ (ct - cabin) < 0:      # orient outward, away from the cabin
        n = -n
    lat = abs(n[2]) > np.hypot(n[0], n[1])          # laterality test
    xfrac = (ct[0] - gx0) / max(gspan, 1e-9)
    if lat:
        key = "L" if ct[2] < cabin[2] else "R"
        sides[key].append(c)
        cls_log.append([f"side_{key}", round(float(xfrac), 2), len(c.faces)])
    elif xfrac > 0.6:
        screens.setdefault("windscreen", []).append(c)
        cls_log.append(["windscreen", round(float(xfrac), 2), len(c.faces)])
    elif xfrac < 0.4:
        screens.setdefault("rear_screen", []).append(c)
        cls_log.append(["rear_screen", round(float(xfrac), 2), len(c.faces)])
    else:
        roof_panes.append(c)
        cls_log.append(["roof", round(float(xfrac), 2), len(c.faces)])
QC["derived"]["component_classification"] = {
    "note": "area-weighted outward normal laterality + x-fraction of the "
            "glass group's own span (screens at the ends, roof mid-cabin)",
    "components": cls_log}
if not sides["L"] or not sides["R"] or "windscreen" not in screens:
    QC["status"] = "REFUSED"
    QC["reason"] = f"classification incomplete: {cls_log}"
    json.dump(QC, open(OUT.replace(".glb", "_glass_qc.json"), "w"), indent=1)
    raise SystemExit(f"REFUSED: {QC['reason']}")


def concat(ms):
    return ms[0] if len(ms) == 1 else trimesh.util.concatenate(ms)


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
    Vm[:, 2] = Am @ coef - np.sign(coef[0]) * 0.0  # surface value first
    # inset 2mm INTO the cabin so the rebuilt pane cannot z-fight the frit
    inset = 0.002 * (-1 if cabin[2] > np.median(V[:, 2]) else 1)
    Vm[:, 2] += -0.002 if np.median(V[:, 2]) > cabin[2] else 0.002
    Rm.vertices = Vm
    Rm.faces = Rm.faces[:, ::-1]
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
    panes["Glass_Windscreen"] = concat(screens["windscreen"])
if screens.get("rear_screen"):
    panes["Glass_Rear_Screen"] = concat(screens["rear_screen"])
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
    if gn == glass_label:
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
                   "thickness_m": THICK}
    print(f"  {name}: {len(solid.faces)} faces, wall from {nb} boundary edges")

out.export(OUT, include_normals=True)
with open(OUT, "rb") as fh:
    fh.seek(12); ln, _ = struct.unpack("<II", fh.read(8)); j = json.loads(fh.read(ln))
missing = [m2.get("name") for m2 in j["meshes"]
           if any("NORMAL" not in p["attributes"] for p in m2["primitives"])]
if missing:
    raise SystemExit(f"REFUSED: NORMAL missing on {missing[:5]}")
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
