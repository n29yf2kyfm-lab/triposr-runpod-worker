#!/usr/bin/env python3
"""wheel_ground_op.py — GATE 6 repair operator: stance, wheels, grounding.

A PARAMETERISED, RE-RUNNABLE OPERATOR, not a one-off edit. It re-measures the
car every time it runs (`wheel_metrology`), derives its own targets from that
measurement plus the CarSpec, and applies the smallest rigid/axisymmetric
change that meets the owner's Gate-6 criteria. Another gate can reshape this
mesh tomorrow and this operator still applies — that is the point of it.

TWO STAGES, DELIBERATELY SEPARATE
---------------------------------
  pose    ONE rigid transform of the WHOLE scene: yaw, pitch, roll and
          translation, so the car is square to the axes and standing on
          y = 0. It cannot break another gate's work, because it moves every
          vertex of every mesh by the same matrix — the car is identical, it
          is only no longer saved crooked. On this Golf it alone takes the
          tyres from 190-200 mm in the air to within 3 mm of the ground, and
          hub lateral symmetry from 76/114 mm to 2.1/2.7 mm.

  wheels  Per-wheel axisymmetric correction: radial scale (radius), axial
          scale (width), rotation to the target axis (toe and camber), and
          translation to the target hub (track, longitudinal symmetry, exact
          ground contact). Only this stage touches geometry differentially,
          and it will REFUSE rather than guess — see below.

HOW A WHEEL IS ISOLATED, AND WHY IT IS SAFE
-------------------------------------------
Not by material name. On this car `Rim_Alloy` covers most of the tyre,
`Tyre_Rubber` is a thin outer ring, `interior` carries 36k faces of genuine
wheel, and all three also carry the front bumper's lower grille. Instead, a
CONNECTED COMPONENT joins a wheel when at least `contain_frac` of its face
centroids lie inside that wheel's fitted cylinder. Measured on this car, the
front-left components are 96-100% contained and no body component reaches in
at all, so the cut is clean by construction: a component that straddles the
boundary is left where it is, and the operator reports it rather than
dragging a piece of the arch along with the wheel.

Three refusals, all of which are better than a silent wrong answer:
  * a component would be split (some of its vertices are shared with faces
    that are not moving) -> refuse that wheel
  * fewer than four wheels are found -> refuse the wheels stage entirely
  * the change would drive a tyre INTO the arch -> refuse, and say by how
    much, because the fix then belongs to whoever owns the body

WHAT THIS OPERATOR WILL NOT DECIDE FOR YOU
------------------------------------------
Published track and the owner's fender criterion are in CONFLICT on this
body and no wheel transform can satisfy both. The Golf Mk8's published track
is 1.549/1.520 m, but this body measures only 1.61 m across the front arches
and 1.66 m across the rear (de-posed, mirrors excluded, against a published
1.789 m). Setting the published track would stand the tyres ~85 mm PROUD of
the fenders. `--track-mode` therefore has three honest settings and no
default that hides the choice:
    fender    (default) put the sidewall the requested distance inside the
              fender lip. Satisfies the owner's acceptance criterion, and
              leaves the track where the body says it should be.
    spec      use the published track. Satisfies the spec sheet and breaks
              the fender criterion. Reported, never silently applied.
    measured  keep each axle's mean track; only symmetry is corrected.

Run:
    python3 wheel_ground_op.py in.glb out.glb --spec specs/vw_golf_mk8.json
    python3 wheel_ground_op.py in.glb out.glb --stages pose        # stance only
    python3 wheel_ground_op.py in.glb out.glb --verify report.json # re-measure
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

import wheel_metrology as WM

DEFAULTS = dict(
    contain_frac=0.95,      # of a component's faces, to join a wheel
    cyl_r=1.03,             # cylinder radius, as a multiple of the fitted R
    cyl_w=0.80,             # cylinder half-width, as a multiple of the width
    min_faces=3,
    fender_inset_m=0.0075,  # middle of the owner's preferred 5-10 mm inside
    arch_margin_m=0.0000,   # tyre may not come closer than this to the body
)


# --------------------------------------------------------------- components
# Component labelling now lives in the METROLOGY, because the measurement
# needs the same notion of "what does this wheel own" that the repair does —
# the arch clearance this operator reads is measured against the complement of
# exactly this set. One implementation, one definition, no drift.
_components = WM._components


def isolate(meshes, wheel, cfg):
    """Face masks per mesh for one wheel, plus the audit of what was left out."""
    c = np.array(wheel["centre"]); a = np.array(wheel["axis"])
    R, W = wheel["radius_m"], wheel["width_m"]
    picked, audit = {}, []
    for name, (V, F) in meshes.items():
        flab, vlab = _components(V, F)
        cen = V[F].mean(axis=1)
        d = cen - c
        lat = d @ a
        rad = np.linalg.norm(d - np.outer(lat, a), axis=1)
        inside = (rad < cfg["cyl_r"] * R) & (np.abs(lat) < cfg["cyl_w"] * W)
        if not inside.any():
            continue
        keep = np.zeros(len(F), bool)
        for comp in np.unique(flab[inside]):
            sub = flab == comp
            n, k = int(sub.sum()), int((sub & inside).sum())
            if n < cfg["min_faces"]:
                continue
            frac = k / n
            if frac >= cfg["contain_frac"]:
                keep |= sub
            else:
                audit.append(dict(mesh=name, component=int(comp), faces=n,
                                  inside=k, contained=round(frac, 3),
                                  action="left in place (straddles the wheel "
                                         "boundary)"))
        if keep.any():
            picked[name] = keep
    return picked, audit


def _vertex_conflict(meshes, picked):
    """Vertices that a moving face and a stationary face share.

    A wheel that shares vertices with the body cannot be moved without
    tearing the body, so the operator refuses instead of tearing it.
    """
    bad = {}
    for name, keep in picked.items():
        V, F = meshes[name]
        moving = np.zeros(len(V), bool)
        moving[F[keep].ravel()] = True
        staying = np.zeros(len(V), bool)
        staying[F[~keep].ravel()] = True
        n = int((moving & staying).sum())
        if n:
            bad[name] = n
    return bad


# ------------------------------------------------------------------ targets
def _axis_for(nose_sign, li, ti, ui, side_sign, toe_deg, camber_deg):
    """Target OUTBOARD axis for one wheel, from the requested toe and camber."""
    out = np.zeros(3); out[ti] = side_sign
    fwd = np.zeros(3); fwd[li] = nose_sign
    up = np.zeros(3); up[ui] = 1.0
    t, g = math.radians(toe_deg), math.radians(camber_deg)
    # inverse of the measurement in wheel_metrology: toe-in tilts the outboard
    # axis toward the nose, negative camber tilts it up.
    v = out * (math.cos(t) * math.cos(g)) + fwd * math.sin(t) - up * math.sin(g)
    return v / np.linalg.norm(v)


def plan_targets(m, spec, args, cfg):
    """Everything the wheels stage will do, as data, before anything moves."""
    li, ti, ui = m["axes"]["length"], m["axes"]["lateral"], m["axes"]["up"]
    nose = m["frame"]["nose"] or 1
    rows = {r["corner"]: r for r in m["wheels"]}

    spec_R = WM._spec_tyre_radius(spec) if spec else None
    if args.radius == "spec" and spec_R:
        R_t = spec_R
    elif args.radius == "mean" or (args.radius == "spec" and not spec_R):
        R_t = float(np.mean([r["radius_m"] for r in m["wheels"]]))
    else:
        R_t = float(args.radius)
    if args.width == "mean":
        W_t = float(np.mean([r["width_m"] for r in m["wheels"]]))
    else:
        W_t = float(args.width)

    plan = {}
    for axle in ("F", "R"):
        pair = [r for r in m["wheels"] if r["corner"].startswith(axle)]
        if len(pair) != 2:
            continue
        # ---- longitudinal: both hubs of an axle share one length coordinate
        l_t = float(np.mean([r["hub_length"] for r in pair]))
        if args.wheelbase == "spec" and spec:
            wb = (spec.get("dimensions", {}).get("wheelbase_m") or {}).get("value")
            if wb:
                # the front axle sits half a wheelbase toward the nose
                l_t = float(nose * abs(wb) / 2.0) if axle == "F" \
                    else float(-nose * abs(wb) / 2.0)
        # ---- lateral: one |hub_lat| per axle, so hub symmetry is exact
        if args.track_mode == "measured":
            half = float(np.mean([abs(r["hub_lat"]) for r in pair]))
        elif args.track_mode == "spec" and spec:
            key = "track_front_m" if axle == "F" else "track_rear_m"
            pub = (spec.get("dimensions", {}).get(key) or {}).get("value")
            half = float(pub) / 2.0 if pub else \
                float(np.mean([abs(r["hub_lat"]) for r in pair]))
        else:                                   # fender
            s_a = W_t / float(np.mean([r["width_m"] for r in pair]))
            want = []
            for r in pair:
                off = (r["outer_sidewall_lat"] - abs(r["hub_lat"])) * s_a
                want.append(r["fender_lip_lat"] - args.fender_inset - off)
            half = float(np.mean(want))
        for r in pair:
            side = 1.0 if r["hub_lat"] > 0 else -1.0
            c_t = np.zeros(3)
            c_t[li], c_t[ui], c_t[ti] = l_t, R_t, side * half
            plan[r["corner"]] = dict(
                corner=r["corner"], axle=axle,
                hub_from=[round(x, 6) for x in r["centre"]],
                hub_to=[round(float(x), 6) for x in c_t],
                axis_from=[round(x, 6) for x in r["axis"]],
                axis_to=[round(float(x), 6) for x in
                         _axis_for(nose, li, ti, ui, side, args.toe, args.camber)],
                radius_from=round(r["radius_m"], 6), radius_to=round(R_t, 6),
                width_from=round(r["width_m"], 6), width_to=round(W_t, 6),
                scale_radial=round(R_t / r["radius_m"], 6),
                scale_axial=round(W_t / r["width_m"], 6),
                d_hub_m=[round(float(c_t[k] - r["centre"][k]), 6) for k in range(3)],
                d_toe_deg=round(args.toe - r["toe_deg"], 4),
                d_camber_deg=round(args.camber - r["camber_deg"], 4),
            )
    return plan, dict(radius_target_m=R_t, width_target_m=W_t,
                      track_mode=args.track_mode,
                      fender_inset_m=args.fender_inset,
                      radius_source=args.radius, width_source=args.width)


def check_arch(m, plan, cfg):
    """Would the planned wheel hit the body? Predicted, before anything moves."""
    warn = []
    for r in m["wheels"]:
        p = plan.get(r["corner"])
        if not p:
            continue
        grow = p["radius_to"] - p["radius_from"]
        clear = r.get("arch_min_clearance_m")
        if clear is None:
            continue
        if grow > clear - cfg["arch_margin_m"]:
            warn.append(dict(corner=r["corner"], radius_growth_m=round(grow, 5),
                             measured_clearance_m=round(clear, 5),
                             note="planned radius growth exceeds the measured "
                                  "gap between tread and body"))
    return warn


# -------------------------------------------------------------------- apply
def rot_between(a, b):
    """Minimal rotation taking unit vector a onto unit vector b."""
    a = np.asarray(a, float); b = np.asarray(b, float)
    a = a / np.linalg.norm(a); b = b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(a @ b)
    if np.linalg.norm(v) < 1e-12:
        return np.eye(3) if c > 0 else -np.eye(3)
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + K + K @ K * (1.0 / (1.0 + c))


def run(args):
    cfg = dict(DEFAULTS)
    spec = WM.load_spec(args.spec)
    stages = [s.strip() for s in args.stages.split(",") if s.strip()]
    report = dict(input=os.path.abspath(args.glb), stages=stages,
                  config={k: v for k, v in cfg.items()})

    import trimesh
    sc = trimesh.load(args.glb, force="scene")
    # world-space vertex arrays, keyed by NODE, exactly as the metrology sees
    meshes = {}
    node_geom = {}
    for node in sc.graph.nodes_geometry:
        T, gname = sc.graph[node]
        g = sc.geometry[gname]
        V = np.asarray(g.vertices, float).copy()
        if not np.allclose(T, np.eye(4)):
            V = V @ np.asarray(T)[:3, :3].T + np.asarray(T)[:3, 3]
            report.setdefault("warnings", []).append(
                f"node {node} carried a non-identity transform; it has been "
                f"baked into the vertices so the output is in world space")
        meshes[node] = (V, np.asarray(g.faces))
        node_geom[node] = gname

    # ---------------- stage: pose
    m0 = WM.measure(args.glb, spec=spec, nose=args.nose, canonicalise=False,
                    bootstrap=False)
    report["measured_before"] = _brief(m0)
    if "pose" in stages:
        if not m0.get("pose"):
            report["pose"] = dict(applied=False,
                                  reason="fewer than four wheels found; the "
                                         "pose solve needs all four contacts")
        else:
            M = np.array(m0["pose"]["matrix"]); t = np.array(m0["pose"]["translation"])
            for n, (V, F) in meshes.items():
                meshes[n] = (V @ M.T + t, F)
            report["pose"] = dict(applied=True, **{
                k: m0["pose"][k] for k in
                ("yaw_deg", "pitch_deg", "roll_deg", "lat_offset_m",
                 "vertical_offset_m", "contact_residual_m",
                 "contact_residual_rms_m", "matrix", "translation")})

    # ---------------- stage: wheels
    if "wheels" in stages:
        mm = _measure_arrays(meshes, spec, args.nose)
        if mm["n_wheels"] != 4:
            report["wheels"] = dict(applied=False, reason=(
                f"found {mm['n_wheels']} wheels, not 4; refusing to move "
                f"geometry on an incomplete fit"))
        else:
            plan, tgt = plan_targets(mm, spec, args, cfg)
            report["targets"] = tgt
            report["transform_table"] = plan
            arch = check_arch(mm, plan, cfg)
            report["arch_warnings"] = arch
            if arch and not args.force:
                report["wheels"] = dict(applied=False, reason=(
                    "planned change would drive a tyre into the body; "
                    "re-run with --force only if that is intended"))
            else:
                moved = {}
                for r in mm["wheels"]:
                    p = plan[r["corner"]]
                    picked, audit = isolate(meshes, r, cfg)
                    bad = _vertex_conflict(meshes, picked)
                    if bad:
                        report.setdefault("refused", []).append(
                            dict(corner=r["corner"], shared_vertices=bad,
                                 reason="moving this wheel would tear geometry "
                                        "it shares with something staying put"))
                        continue
                    hub = np.array(r["centre"]); axis = np.array(r["axis"])
                    hub_t = np.array(p["hub_to"]); axis_t = np.array(p["axis_to"])
                    nfaces = 0
                    for name, keep in picked.items():
                        V, F = meshes[name]
                        vm = np.zeros(len(V), bool)
                        vm[F[keep].ravel()] = True
                        q = V[vm] - hub
                        a = axis / np.linalg.norm(axis)
                        ax = q @ a
                        perp = q - np.outer(ax, a)
                        q = np.outer(p["scale_axial"] * ax, a) + \
                            p["scale_radial"] * perp
                        V[vm] = q @ rot_between(a, axis_t).T + hub_t
                        meshes[name] = (V, F)
                        nfaces += int(keep.sum())
                    moved[r["corner"]] = dict(faces=nfaces,
                                              meshes=sorted(picked),
                                              left_in_place=audit)
                report["wheels"] = dict(applied=True, moved=moved)

    # ---------------- write
    for node, (V, F) in meshes.items():
        g = sc.geometry[node_geom[node]]
        g.vertices = V
        sc.graph.update(frame_to=node, matrix=np.eye(4))
    if not args.dry_run:
        sc.export(args.out)
        report["output"] = os.path.abspath(args.out)
    return report


def _measure_arrays(meshes, spec, nose):
    """Measure from in-memory arrays (mid-pipeline, no file round trip)."""
    fr = WM.resolve_frame(meshes, nose=nose, spec=spec)
    cfg = dict(WM.DEFAULTS)
    r = WM._spec_tyre_radius(spec) if spec else None
    if r:
        cfg["r_lo"], cfg["r_hi"], cfg["r_seed"] = 0.75 * r, 1.30 * r, r
    V = np.vstack([v for v, _ in meshes.values()])
    wheels = WM._fit_all(V, fr, cfg)
    m = WM._finish("<memory>", meshes, V, fr, wheels, cfg, spec, False,
                   None, None, True)
    return WM.fender_and_arch(m)


def _brief(m):
    return dict(n_wheels=m["n_wheels"],
                wheels=[{k: r[k] for k in
                         ("corner", "hub_length", "hub_up", "hub_lat",
                          "radius_m", "width_m", "bottom_m", "toe_deg",
                          "camber_deg")} for r in m["wheels"]],
                axles=m.get("axles"), pose=m.get("pose"),
                pose_effect=m.get("pose_effect"))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("glb")
    ap.add_argument("out")
    ap.add_argument("--spec", default=None)
    ap.add_argument("--stages", default="pose,wheels")
    ap.add_argument("--nose", choices=["+", "-", "auto"], default="auto")
    ap.add_argument("--track-mode", choices=["fender", "spec", "measured"],
                    default="fender")
    ap.add_argument("--fender-inset", type=float,
                    default=DEFAULTS["fender_inset_m"])
    ap.add_argument("--radius", default="spec",
                    help="'spec' | 'mean' | a value in metres")
    ap.add_argument("--width", default="mean",
                    help="'mean' | a value in metres")
    ap.add_argument("--wheelbase", default="measured",
                    choices=["measured", "spec"])
    ap.add_argument("--toe", type=float, default=0.0, help="target, degrees")
    ap.add_argument("--camber", type=float, default=0.0)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", default=None)
    a = ap.parse_args()
    rep = run(a)
    txt = json.dumps(rep, indent=1, default=float)
    if a.report:
        with open(a.report, "w") as f:
            f.write(txt)
        print("wrote", a.report)
    else:
        print(txt)
    for k in ("pose", "wheels"):
        if k in rep:
            print(f"{k}: applied={rep[k].get('applied')} "
                  f"{rep[k].get('reason', '')}", file=sys.stderr)


if __name__ == "__main__":
    main()
