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
    min_tread_frac=0.95,    # of a wheel's tread band, or the move is refused
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


def isolate_faces(meshes, wheel, cfg):
    """Face masks for one wheel, cut at FACE level instead of component level.

    WHEN COMPONENT OWNERSHIP IS NOT AVAILABLE, AND WHY THAT IS NOT RARE
    -------------------------------------------------------------------
    `isolate` above asks whole connected components to join a wheel, which is
    the safe cut when the wheel IS a component. On a generated car it often
    is not. Measured on the Gate-6 Golf: the rear tyres are welded into one
    423,288-face `interior` shell that also carries the cabin and the
    underbody, so component ownership claims only 3% of the rear-right tread
    band and 57% of the rear-left. Moving that wheel by components moves a
    third of it and leaves the rest standing in the old position — which is
    what the first run of this operator did, and it is worse than not moving
    at all, because the metrology then fits a mixture of the two and reports
    plausible numbers for a broken car.

    A face-level cut takes every face whose CENTROID lies inside the fitted
    cylinder and then SPLITS the vertices that the cut crosses: shared
    vertices are duplicated so the moving faces own their copies outright.
    Nothing stationary is stretched — the alternative, moving a shared
    vertex, is the "vertex-pull DENTS panels" failure this project already
    paid for twice (bridge_gaps, lamp_recess).

    The honest cost, stated rather than discovered later: the cut leaves a
    SEAM where the tyre was welded to the wheel house. That seam is inside
    the arch, and a wheel that moves relative to a body must separate from
    it somewhere. `--cut face` is opt-in for exactly that reason.
    """
    c = np.array(wheel["centre"]); a = np.array(wheel["axis"])
    R, W = wheel["radius_m"], wheel["width_m"]
    picked = {}
    for name, (V, F) in meshes.items():
        cen = V[F].mean(axis=1)
        d = cen - c
        lat = d @ a
        rad = np.linalg.norm(d - np.outer(lat, a), axis=1)
        keep = (rad < cfg["cyl_r"] * R) & (np.abs(lat) < cfg["cyl_w"] * W)
        if keep.any():
            picked[name] = keep
    return picked, []


def split_shared(meshes, picked):
    """Duplicate every vertex a moving face shares with a stationary one.

    Returns the updated meshes and the number of vertices split per mesh. The
    moving faces are re-indexed onto the copies, so afterwards the moving set
    can be transformed with no effect whatsoever on anything staying put.
    """
    counts = {}
    for name, keep in picked.items():
        V, F = meshes[name]
        moving = np.zeros(len(V), bool)
        moving[F[keep].ravel()] = True
        staying = np.zeros(len(V), bool)
        staying[F[~keep].ravel()] = True
        shared = np.where(moving & staying)[0]
        if not len(shared):
            counts[name] = 0
            continue
        remap = np.arange(len(V))
        newV = np.vstack([V, V[shared]])
        remap = np.concatenate([remap, shared])          # copy -> original
        idx = np.full(len(V), -1, np.int64)
        idx[shared] = np.arange(len(V), len(V) + len(shared))
        Fk = F[keep].copy()
        hit = idx[Fk] >= 0
        Fk[hit] = idx[Fk][hit]
        Fnew = F.copy()
        Fnew[keep] = Fk
        newkeep = keep.copy()
        meshes[name] = (newV, Fnew)
        picked[name] = newkeep
        counts[name] = int(len(shared))
    return meshes, counts


def tread_owned_fraction(meshes, picked, wheel, band_rel=0.030, lat_frac=0.55):
    """How much of the TREAD BAND would actually move? The completeness test.

    A wheel is not "isolated" because some faces were found; it is isolated
    when the part the measurement will judge — the tread — moves as one. This
    returns the fraction, and the operator refuses below `min_tread_frac`
    rather than half-moving a wheel.
    """
    c = np.array(wheel["centre"]); a = np.array(wheel["axis"])
    R, W = wheel["radius_m"], wheel["width_m"]
    tot = own = 0
    for name, (V, F) in meshes.items():
        d = V - c
        lat = d @ a
        rad = np.linalg.norm(d - np.outer(lat, a), axis=1)
        band = (np.abs(rad - R) < band_rel * R) & (np.abs(lat) < lat_frac * W)
        if not band.any():
            continue
        tot += int(band.sum())
        keep = picked.get(name)
        if keep is None:
            continue
        moving = np.zeros(len(V), bool)
        moving[F[keep].ravel()] = True
        own += int((band & moving).sum())
    return (own / tot if tot else 0.0), tot


def isolated_metrics(meshes, picked, wheel):
    """Radius, width and sidewall of ONE wheel, from the geometry it owns.

    WHY THE PLAN MUST USE THIS AND NOT THE SCENE-WIDE FIT
    ----------------------------------------------------
    The metrology measures width as a percentile span of the tread band it
    finds in the whole scene, and on a fused car 8-11% of that band is
    wheel-house skin sitting at the tyre's own radius. Scaling a wheel by
    target/contaminated_width and then verifying the result on the moved
    geometry gave four wheels 10 mm apart after they had all been scaled to
    one number — the scale factor and the check were in different units.

    Measuring on the isolated set closes that loop: the same population is
    measured, scaled and verified, so "identical width" becomes a property
    the operator can actually deliver rather than hope for.
    """
    c = np.array(wheel["centre"]); a = np.array(wheel["axis"])
    a = a / np.linalg.norm(a)
    R = wheel["radius_m"]
    Q = []
    for name, keep in picked.items():
        V, F = meshes[name]
        vm = np.zeros(len(V), bool)
        vm[F[keep].ravel()] = True
        Q.append(V[vm])
    if not Q:
        return None
    Q = np.vstack(Q)
    d = Q - c
    lat = d @ a
    rad = np.linalg.norm(d - np.outer(lat, a), axis=1)
    tread = np.abs(rad - R) < 0.03 * R
    if tread.sum() < 50:
        return None
    lo, hi = np.percentile(lat[tread], [1, 99])
    carcass = rad > 0.62 * R
    return dict(radius_m=float(np.percentile(rad[tread], 50)),
                width_m=float(hi - lo),
                mid_offset_m=float((lo + hi) / 2.0),
                sidewall_out_m=float(np.percentile(
                    np.abs(Q[carcass] @ _unit_lateral(a)), 99.0))
                if carcass.sum() > 50 else None,
                tread_vertices=int(tread.sum()), vertices=int(len(Q)))


def _unit_lateral(a):
    """The scene lateral axis nearest to a wheel axis — for sidewall reads."""
    e = np.zeros(3)
    e[int(np.argmax(np.abs(a)))] = 1.0
    return e


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


def plan_targets(m, spec, args, cfg, iso=None):
    """Everything the wheels stage will do, as data, before anything moves."""
    li, ti, ui = m["axes"]["length"], m["axes"]["lateral"], m["axes"]["up"]
    nose = m["frame"]["nose"] or 1
    rows = {r["corner"]: r for r in m["wheels"]}

    iso = iso or {}

    def _R(r):
        return (iso.get(r["corner"], {}) or {}).get("radius_m", r["radius_m"])

    def _W(r):
        return (iso.get(r["corner"], {}) or {}).get("width_m", r["width_m"])

    def _SW(r):
        # DELIBERATELY the scene-wide sidewall, not the isolated one. The
        # fender criterion is GRADED against `outer_sidewall_lat`, so the
        # target has to be expressed in that same measurement or the repair
        # aims at one number and is marked against another: planning off the
        # isolated sidewall (20 mm smaller, because it excludes arch skin the
        # scene-wide read includes) pushed all four tyres 11-26 mm PROUD of
        # the fenders while the plan believed they were 7.5 mm inside.
        # Scaling still uses the isolated WIDTH — that one is scaled and
        # verified on the same population, so it is coherent on its own terms.
        return r["outer_sidewall_lat"]

    spec_R = WM._spec_tyre_radius(spec) if spec else None
    if args.radius == "spec" and spec_R:
        R_t = spec_R
    elif args.radius == "mean" or (args.radius == "spec" and not spec_R):
        R_t = float(np.mean([_R(r) for r in m["wheels"]]))
    else:
        R_t = float(args.radius)
    if args.width == "mean":
        W_t = float(np.mean([_W(r) for r in m["wheels"]]))
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
            want = []
            for r in pair:
                s_a = W_t / _W(r)
                off = (_SW(r) - abs(r["hub_lat"])) * s_a
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
                radius_from=round(_R(r), 6), radius_to=round(R_t, 6),
                width_from=round(_W(r), 6), width_to=round(W_t, 6),
                scale_radial=round(R_t / _R(r), 6),
                scale_axial=round(W_t / _W(r), 6),
                measured_on=("isolated wheel geometry" if r["corner"] in iso
                             else "scene-wide tread band"),
                mid_offset_m=round(float((iso.get(r["corner"], {}) or {})
                                         .get("mid_offset_m", 0.0)), 6),
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
    if getattr(args, "contain", None) is not None:
        cfg["contain_frac"] = float(args.contain)
    for k, an in (("cyl_w", "cyl_w"), ("cyl_r", "cyl_r")):
        if getattr(args, an, None) is not None:
            cfg[k] = float(getattr(args, an))
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
            # ISOLATE FIRST, THEN PLAN. The plan's scale factors have to be
            # expressed in the same measurement the result will be judged by,
            # so each wheel is cut out first and measured on its own geometry
            # (see `isolated_metrics`). Cutting is side-effect free apart from
            # the vertex splits, which only duplicate vertices.
            iso, picks = {}, {}
            for r in mm["wheels"]:
                if args.cut == "face":
                    picked, audit = isolate_faces(meshes, r, cfg)
                    meshes, split = split_shared(meshes, picked)
                    audit = [dict(action="vertices split along the cut",
                                  per_mesh=split)]
                else:
                    picked, audit = isolate(meshes, r, cfg)
                picks[r["corner"]] = (picked, audit)
                mtr = isolated_metrics(meshes, picked, r)
                if mtr:
                    iso[r["corner"]] = mtr
            report["isolated_metrics"] = iso
            plan, tgt = plan_targets(mm, spec, args, cfg, iso=iso)
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
                    picked, audit = picks[r["corner"]]
                    frac, n_band = tread_owned_fraction(meshes, picked, r)
                    if frac < cfg["min_tread_frac"]:
                        report.setdefault("refused", []).append(
                            dict(corner=r["corner"],
                                 tread_owned_fraction=round(frac, 4),
                                 tread_band_vertices=n_band,
                                 reason="only part of this wheel's tread band "
                                        "would move; moving it would split the "
                                        "wheel in two and every angle measured "
                                        "afterwards would be a fit to the "
                                        "mixture. Try --cut face."))
                        continue
                    bad = _vertex_conflict(meshes, picked)
                    if bad:
                        report.setdefault("refused", []).append(
                            dict(corner=r["corner"], shared_vertices=bad,
                                 reason="moving this wheel would tear geometry "
                                        "it shares with something staying put"))
                        continue
                    axis = np.array(r["axis"])
                    axis = axis / np.linalg.norm(axis)
                    hub = np.array(r["centre"])
                    # The axial scale acts about the wheel's OWN mid-plane —
                    # scaling about a plane a few mm off it walks the wheel
                    # sideways — but the PLACEMENT still maps centre -> target,
                    # because the target was derived from the centre. Moving
                    # the pivot and the destination together is what pushed all
                    # four tyres ~14 mm further outboard than the plan said.
                    mid = float(p.get("mid_offset_m", 0.0))
                    hub_t = np.array(p["hub_to"]); axis_t = np.array(p["axis_to"])
                    nfaces = 0
                    for name, keep in picked.items():
                        V, F = meshes[name]
                        vm = np.zeros(len(V), bool)
                        vm[F[keep].ravel()] = True
                        q = V[vm] - hub
                        a = axis
                        ax = q @ a
                        perp = q - np.outer(ax, a)
                        ax = mid + p["scale_axial"] * (ax - mid)
                        q = np.outer(ax, a) + p["scale_radial"] * perp
                        V[vm] = q @ rot_between(a, axis_t).T + hub_t
                        meshes[name] = (V, F)
                        nfaces += int(keep.sum())
                    # SELF-CHECK ON THE GEOMETRY THIS OPERATOR ACTUALLY MOVED.
                    # The scene-wide metrology re-fits from scratch and, on a
                    # fused car, its tread band picks up wheel-house skin
                    # sitting at the tyre's own radius — measured here as
                    # 8-11% of the band. That contaminates the WIDTH and the
                    # hub's lateral position, and it is not evidence about
                    # what the transform did. This is: the moved set's own
                    # span about the target axis, before and after.
                    Q = []
                    for name, keep in picked.items():
                        V, F = meshes[name]
                        vm = np.zeros(len(V), bool)
                        vm[F[keep].ravel()] = True
                        Q.append(V[vm])
                    Q = np.vstack(Q) if Q else np.zeros((0, 3))
                    at = np.array(p["axis_to"]); ht = np.array(p["hub_to"])
                    dq = Q - ht
                    lq = dq @ at
                    rq = np.linalg.norm(dq - np.outer(lq, at), axis=1)
                    tread = np.abs(rq - p["radius_to"]) < 0.03 * p["radius_to"]
                    moved[r["corner"]] = dict(
                        faces=nfaces, meshes=sorted(picked),
                        left_in_place=audit,
                        achieved=dict(
                            moved_vertices=int(len(Q)),
                            tread_vertices=int(tread.sum()),
                            width_m=float(np.percentile(lq[tread], 99) -
                                          np.percentile(lq[tread], 1))
                            if tread.sum() > 50 else None,
                            radius_p50_m=float(np.percentile(rq[tread], 50))
                            if tread.sum() > 50 else None,
                            bottom_m=float(ht[m0["axes"]["up"]] -
                                           p["radius_to"]),
                            target_width_m=p["width_to"],
                            target_radius_m=p["radius_to"]))
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
    ap.add_argument("--contain", type=float, default=DEFAULTS["contain_frac"],
                    help="fraction of a component's faces that must lie inside "
                         "the fitted cylinder before the component moves with "
                         "the wheel. The default 0.95 is deliberately strict, "
                         "but it is not universal: on the Gate-6 Golf a "
                         "genuine 4,714-face rim component scores 0.918 and "
                         "would be LEFT BEHIND while the rest of its wheel "
                         "moved. Lower it only against a measured containment "
                         "histogram — this car's is bimodal with an empty gap "
                         "from 0.15 to 0.90, so 0.85 is safe here and a value "
                         "inside a populated region never is.")
    ap.add_argument("--cyl-w", type=float, default=DEFAULTS["cyl_w"],
                    help="half-width of the isolation cylinder, as a multiple "
                         "of the measured tyre width. 0.80 covers the tyre "
                         "with 60 mm of margin inboard, which on a fused car "
                         "drags wheel-house skin along with the wheel and then "
                         "shows up as an unstable measured WIDTH. Narrow it "
                         "when the width spread gets worse after a repair.")
    ap.add_argument("--cyl-r", type=float, default=DEFAULTS["cyl_r"])
    ap.add_argument("--cut", choices=["component", "face"],
                    default="component",
                    help="how a wheel is separated from the body. 'component' "
                         "moves whole connected components and cannot cut "
                         "anything (safe, but useless on a car whose wheels "
                         "are welded into one shell). 'face' takes every face "
                         "inside the fitted cylinder and splits the shared "
                         "vertices, which separates a fused wheel at the cost "
                         "of a seam inside the arch.")
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
