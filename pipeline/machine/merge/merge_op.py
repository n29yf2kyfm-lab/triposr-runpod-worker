#!/usr/bin/env python3
"""merge_op.py — carry Gate 6's stance corrections onto another gate's car.

THE PROBLEM THIS SOLVES
-----------------------
Six gates each repaired their own zone on their own copy of the car and were
never merged, so no single file has everything. Gate 7+8's `car_rebound.glb`
has the correct material table (glass_probe clear/proven, black tyres, a
respray that holds, zero validator errors) and Gate 6's grounding and wheel
corrections are missing from it. Gate 6's own delivered file has the stance
and not the materials. Gate 3 v7 is rebuilding the front fascia on the SAME
rebound base right now and its output will need this same treatment, so this
is written as a re-runnable OPERATOR, not a one-off edit.

ROUTE CHOSEN: (B) RE-APPLY GATE 6'S OPERATIONS TO THE BASE'S OWN GEOMETRY.
The alternative — (A) transplanting Gate 6's wheel geometry into the base —
was rejected before any code was written, for three reasons:
  1. it moves geometry across a material boundary. Gate 6's wheels carry Gate
     6's material bindings (`Rim_Alloy`, `Tyre_Rubber`, `carpaint`, `interior`
     — its wheels were CUT OUT OF THE FUSED SHELL and are four-material
     mixtures), while the base binds Brake_Disc / Rim_Alloy / Tyre_Rubber to
     three clean per-corner nodes. Rebinding a mixture onto that scheme is
     exactly the "silently opaques the glazing" class of net loss the brief
     forbids, and it would have to be done by hand, per corner, with no check
     that can prove it right.
  2. Gate 6's shippable file is TEXTURE-REDUCED (the 63 MB original 413'd on
     the bucket). Its geometry is bit-identical, but importing from it makes
     the reduced copy load-bearing.
  3. it does not generalise. The v7 front rebuild will hand me a different
     file with the same wheels; route B re-measures and re-applies, route A
     would need a fresh transplant every time.
  WHAT I WOULD HAVE SEEN IF ROUTE B WERE WRONG: the base's wheels would not
  have been separable — a wheel welded into the body shell cannot be scaled
  without cutting faces and duplicating shared vertices (Gate 6's hardest
  step, and where it shipped 1,980 validator errors). Measured before
  committing: the base carries `Wheel_{FL,FR,RL,RR}_{Tyre,Rim,Disc}` as
  twelve separate nodes with no vertex shared with the body, so the cut this
  operator would have needed does not exist. Route B is not merely safer
  here, it is free.

HOW IT PRESERVES THE MATERIAL LAYER: BY CONSTRUCTION, NOT BY CARE
-----------------------------------------------------------------
Nothing here rebuilds a scene. `glb_io` edits the bytes behind the POSITION
and NORMAL accessors and rewrites those accessors' min/max, and touches the
glTF JSON nowhere else except to clear the node transforms it has just baked.
Materials, extensions (KHR_materials_transmission / _ior / _clearcoat — the
three that make this car's glazing read "clear / proven"), mesh names, node
names, primitive->material bindings and the index buffers are never rewritten,
so the material table diffs EMPTY rather than diffing empty by luck. Every
route that goes through a trimesh export or a Blender round-trip has cost this
project a defect (dropped NORMAL accessors, recomputed vertex normals zeroing
571 vertices, renamed materials); this one cannot.

WHAT IT DOES
------------
  pose    ONE rigid transform of every vertex in the scene: p' = M p + t, with
          M orthogonal so it is provably rigid. Squares the car to the axes
          and drops it onto the ground. Gate 6 solved this matrix on the same
          car in the same frame — MEASURED, not assumed: the base's world AABB
          is 4.282490 x 1.455398 x 1.788713 against Gate 6's recorded
          aabb_before of 4.282490 x 1.455398 x 1.788713, and mapping the
          base's four hub fits through Gate 6's matrix lands them within 0.1
          to 4.3 mm of Gate 6's own post-pose measurements on three corners.
          So the recorded matrix is reused (`--pose record`) and the solve is
          re-derived independently only as a cross-check.

  wheels  Per corner: isolate (geometrically, see wheel_probe), fit the
          cylinder, scale radially and axially, rotate the axis square, and
          place the hub. Then drop the corner so its TYRE's lowest vertex sits
          exactly on the contact plane — the same thing Gate 6 did (its op
          records `bottom_m: 0.0` on all four), and the reason its delivered
          tyres land within 0.29 mm while a radius-based placement cannot: a
          tyre 4.5 mm rms out of round does not touch the ground at its fitted
          radius.

TARGETS: WHICH OF GATE 6'S NUMBERS ARE COPIED, AND WHICH ARE RE-DERIVED
----------------------------------------------------------------------
Copying a target COORDINATE is only valid where the two instruments agree
about where the wheel is now. Measured, they do not agree everywhere:

  stable  hub longitudinal, per axle   my post-pose -1.2791/-1.3034 front vs
          Gate 6's -1.27819/-1.30314 : 0.1-0.9 mm apart. Symmetrised the same
          way, and Gate 6's own two passes agree to 0.1 mm.
  stable  radius            Gate 6 pass1 target 0.307168, pass2 0.307204.
  UNSTABLE  hub LATERAL     Gate 6's pass 1 placed its RL hub at z=+0.74109
          and its pass 2 then MEASURED that same wheel at z=+0.697305 — its
          own two passes disagree by 43.8 mm on this one quantity, because
          the lateral hub is the mid-plane of a tread band and the band is
          re-cut every pass. My fit disagrees with Gate 6's by 34 mm on the
          same corner and by <5 mm on the other three.
  UNSTABLE  width           Gate 6 measured 0.2134-0.2670 across four wheels
          of one car (a 53 mm spread on a quantity that is physically the
          same tyre) because its cut sets carried arch and interior spill.
          Mine, on clean per-corner nodes, read 0.2066-0.2249.

So radius, longitudinal symmetry, axis and grounding follow Gate 6 directly;
width and track are re-derived from the geometry being scaled, per Gate 6's
own recorded lesson ("scale in the units you verify in — isolate first,
measure THAT set, scale it, verify it"). `--track-mode gate6` and
`--radius gate6` copy Gate 6's literal numbers instead, and the report always
carries both so the choice is visible rather than silent.

REFUSALS (all of them better than a silent wrong answer)
  * a mesh referenced by more than one node -> refuse (baking would move an
    instance's siblings)
  * fewer than four corners, or a node-name corner label that disagrees with
    the node's own position -> refuse
  * a corner whose tread fit does not cover the circle or whose rms is worse
    than `max_rms` -> refuse
  * a scale factor outside `--max-scale` -> refuse (a runaway axial scale is
    what walked Gate 6's first attempt 14 mm proud of the fenders)
  * any linear map with a non-positive determinant -> refuse (it would invert
    winding and every normal with it)

Run:
    python3 merge_op.py base.glb out.glb --pose-json op_pose.json \\
        --report merge_report.json
    python3 merge_op.py base.glb out.glb --stages pose
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wheel_probe as WP                       # noqa: E402
from glb_io import GLB, binding_table, material_table   # noqa: E402

# Gate 6's delivered wheel targets, in ITS post-pose frame, transcribed from
# car-meshes/staging/gate6/op_wheels.json.  Its L/R labels are the MIRROR of
# Gate 7+8's on the same car, so these are keyed by GEOMETRY (axle, sign of
# the lateral coordinate) and never by letter.
GATE6 = dict(
    radius_m=0.30720408639890573,
    width_m=0.23639467986708396,
    hub_x=dict(F=-1.290573, R=1.189558),
    hub_absz=dict(F=0.676095, R=0.724044),
    hub_y=0.307204,
)

DEFAULTS = dict(max_scale=0.15, ground_pct=0.0, contact_tol_m=0.0005)


# --------------------------------------------------------------------- maths
def rot_between(a, b):
    """Minimal rotation taking unit vector a to unit vector b."""
    a = np.asarray(a, float) / np.linalg.norm(a)
    b = np.asarray(b, float) / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(a @ b)
    if np.linalg.norm(v) < 1e-12:
        if c > 0:
            return np.eye(3)
        tmp = np.array([1.0, 0, 0]) if abs(a[0]) < 0.9 else np.array([0, 1.0, 0])
        ax = np.cross(a, tmp)
        ax /= np.linalg.norm(ax)
        K = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
        return np.eye(3) + 2 * K @ K
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + K + K @ K * (1.0 / (1.0 + c))


def frame_of(axis):
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    tmp = np.array([0.0, 1.0, 0.0]) if abs(a[1]) < 0.9 else np.array([1.0, 0.0, 0.0])
    e1 = np.cross(a, tmp)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(a, e1)
    return np.column_stack([e1, e2, a])


def axisym_linear(axis, s_rad, s_ax, R_target_axis):
    """rotate(axis->target) . scale(s_rad,s_rad,s_ax in the wheel's own frame)"""
    F = frame_of(axis)
    S = F @ np.diag([s_rad, s_rad, s_ax]) @ F.T
    Rot = rot_between(axis, R_target_axis)
    return Rot @ S, Rot @ F @ np.diag([1 / s_rad, 1 / s_rad, 1 / s_ax]) @ F.T


# ----------------------------------------------------------------- the stages
def load_pose(glb, args):
    """(M, t, provenance). Recorded matrix by default; re-derived on request."""
    if args.pose_mode == "record":
        rec = json.load(open(args.pose_json))
        p = rec.get("pose", rec)
        M = np.array(p["matrix"], float)
        t = np.array(p["translation"], float)
        prov = dict(source=os.path.basename(args.pose_json),
                    yaw_deg=p.get("yaw_deg"), pitch_deg=p.get("pitch_deg"),
                    roll_deg=p.get("roll_deg"),
                    contact_residual_rms_m=p.get("contact_residual_rms_m"))
    elif args.pose_mode == "derive":
        sys.path.insert(0, os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        import wheel_metrology as WM
        m = WM.measure(glb.path, nose="auto", canonicalise=False,
                       bootstrap=False)
        p = m["pose"]
        M = np.array(p["matrix"], float)
        t = np.array(p["translation"], float)
        prov = dict(source="re-derived by wheel_metrology.solve_pose",
                    yaw_deg=p["yaw_deg"], pitch_deg=p["pitch_deg"],
                    roll_deg=p["roll_deg"],
                    contact_residual_rms_m=p["contact_residual_rms_m"])
    else:
        return np.eye(3), np.zeros(3), dict(source="identity (pose skipped)")
    orth = float(np.abs(M @ M.T - np.eye(3)).max())
    det = float(np.linalg.det(M))
    if orth > 1e-9 or abs(det - 1.0) > 1e-9:
        raise SystemExit(f"REFUSED: pose matrix is not a rotation "
                         f"(orthogonality error {orth:.3e}, det {det:.9f})")
    prov.update(orthogonality_error=orth, determinant=det)
    return M, t, prov


def plan_wheels(post, cs, nose, args, report):
    """Per-corner affine, measured on the POST-POSE geometry in `post`."""
    meas = {}
    for k in WP.CORNERS:
        if k not in cs:
            raise SystemExit(f"REFUSED: no geometry found for corner {k}")
        P = np.vstack([post[n] for n in cs[k]["nodes"]])
        m = WP.measure_corner(P)
        toe, cam = WP.angles(m["axis"], m["centre"], nose)
        m["toe_deg"], m["camber_deg"] = toe, cam
        if m["coverage"] < WP.DEFAULTS["min_cov"]:
            raise SystemExit(f"REFUSED: corner {k} tread covers only "
                             f"{m['coverage']:.2f} of its circle")
        if m["rms"] > WP.DEFAULTS["max_rms"]:
            raise SystemExit(f"REFUSED: corner {k} cylinder fit rms "
                             f"{m['rms'] * 1000:.1f} mm")
        meas[k] = m

    R_mean = float(np.mean([meas[k]["R"] for k in WP.CORNERS]))
    W_mean = float(np.mean([meas[k]["width"] for k in WP.CORNERS]))
    R_t = GATE6["radius_m"] if args.radius == "gate6" else R_mean
    W_t = GATE6["width_m"] if args.width == "gate6" else W_mean

    # per-axle symmetrisation of the hub, longitudinal and lateral
    axle_of = {"FL": "F", "FR": "F", "RL": "R", "RR": "R"}
    hub_x, hub_absz = {}, {}
    for ax in ("F", "R"):
        ks = [k for k in WP.CORNERS if axle_of[k] == ax]
        hub_x[ax] = float(np.mean([meas[k]["centre"][0] for k in ks]))
        hub_absz[ax] = float(np.mean([abs(meas[k]["centre"][2]) for k in ks]))
    if args.track_mode == "gate6":
        hub_absz = dict(GATE6["hub_absz"])
    if args.hub_x == "gate6":
        hub_x = dict(GATE6["hub_x"])

    plan = {}
    for k in WP.CORNERS:
        m = meas[k]
        ax = axle_of[k]
        side = 1.0 if m["centre"][2] > 0 else -1.0
        a_t = np.array([0.0, 0.0, side])
        s_rad = R_t / m["R"]
        s_ax = W_t / m["width"]
        for nm, s in (("radial", s_rad), ("axial", s_ax)):
            if abs(s - 1.0) > args.max_scale:
                raise SystemExit(
                    f"REFUSED: corner {k} {nm} scale {s:.4f} is outside "
                    f"+-{args.max_scale:.2f}; a runaway scale is what walked "
                    f"Gate 6's first attempt 14 mm proud of the fenders")
        L, NL = axisym_linear(m["axis"], s_rad, s_ax, a_t)
        det = float(np.linalg.det(L))
        if det <= 0:
            raise SystemExit(f"REFUSED: corner {k} linear map has det {det:.4f}")
        c_t = np.array([hub_x[ax], m["centre"][1], side * hub_absz[ax]])
        plan[k] = dict(measured=m, axle=ax, side=side, s_rad=s_rad, s_ax=s_ax,
                       L=L, NL=NL, c_from=m["centre"].copy(), c_to=c_t,
                       a_to=a_t, det=det)
    report["wheel_targets"] = dict(
        radius_m=R_t, radius_source=args.radius, radius_mean_measured=R_mean,
        radius_gate6=GATE6["radius_m"],
        width_m=W_t, width_source=args.width, width_mean_measured=W_mean,
        width_gate6=GATE6["width_m"],
        hub_x=hub_x, hub_absz=hub_absz,
        track_mode=args.track_mode,
        track_measured_m={a: 2 * hub_absz[a] for a in ("F", "R")},
        track_gate6_m={a: 2 * GATE6["hub_absz"][a] for a in ("F", "R")})
    return plan


def ground_wheels(plan, post, cs, args, report):
    """Drop each corner so its TYRE's lowest vertex sits on y = 0."""
    for k, pl in plan.items():
        tyre = [n for n in cs[k]["nodes"] if n.lower().endswith("tyre")]
        if not tyre:
            raise SystemExit(f"REFUSED: corner {k} has no tyre node; grounding "
                             f"on rim or disc geometry would be wrong")
        T = np.vstack([post[n] for n in tyre])
        moved = (T - pl["c_from"]) @ pl["L"].T + pl["c_to"]
        drop = float(moved[:, 1].min()) - args.ground_pct
        pl["c_to"] = pl["c_to"] - np.array([0.0, drop, 0.0])
        pl["ground_drop_m"] = drop
        final = moved - np.array([0.0, drop, 0.0])
        pl["tyre_bottom_m"] = float(final[:, 1].min())
        pl["contact_verts"] = int((final[:, 1] < args.contact_tol_m).sum())
        pl["tyre_nodes"] = tyre
    return plan


# ---------------------------------------------------------------------- main
def run(args):
    glb = GLB(args.glb)
    report = dict(
        tool="pipeline/machine/merge/merge_op.py",
        base=os.path.abspath(args.glb),
        base_sha256=_sha(args.glb),
        out=os.path.abspath(args.out),
        stages=[s for s in args.stages.split(",") if s],
        config=dict(max_scale=args.max_scale, track_mode=args.track_mode,
                    radius=args.radius, width=args.width, hub_x=args.hub_x,
                    pose_mode=args.pose_mode))

    # --- refusal: instancing. Baking a shared mesh moves every instance.
    users = {}
    for ni, name, W, mi in glb.graph():
        users.setdefault(mi, []).append(name)
    shared = {m: n for m, n in users.items() if len(n) > 1}
    if shared:
        raise SystemExit(f"REFUSED: meshes shared by several nodes {shared}; "
                         f"this operator bakes node transforms and would move "
                         f"an instance's siblings with it")

    mats_before = material_table(glb)
    binds_before = binding_table(glb)

    # --- original world vertices / normals, per node, in float64
    orig, norms, prim_of = {}, {}, {}
    for name, W, mi, pi, p in glb.prims():
        prim_of[name] = (mi, pi, p, W)
        orig[name] = glb.world_positions(W, p)
        if "NORMAL" not in p["attributes"]:
            raise SystemExit(f"REFUSED: node {name} has no NORMAL accessor; "
                             f"writing positions without normals ships the "
                             f"crumpled-foil defect")
        N = glb.accessor(p["attributes"]["NORMAL"]).astype(np.float64)
        norms[name] = N @ np.linalg.inv(W[:3, :3]).T   # node-local -> world
    report["zero_normals_before"] = int(sum(
        int((np.linalg.norm(N, axis=1) < 1e-8).sum()) for N in norms.values()))

    # --- stage: pose
    M, t, prov = load_pose(glb, args) if "pose" in report["stages"] else (
        np.eye(3), np.zeros(3), dict(source="skipped"))
    report["pose"] = prov
    post = {n: V @ M.T + t for n, V in orig.items()}
    post_n = {n: N @ M.T for n, N in norms.items()}

    lin = {n: M.copy() for n in orig}
    off = {n: t.copy() for n in orig}

    # --- stage: wheels
    if "wheels" in report["stages"]:
        cs, nose, xmid = WP.corners(glb)
        conf = {k: sorted(cs[k]["claimed"]) for k in sorted(cs)}
        report["corner_confusion"] = conf
        bad = {k: v for k, v in conf.items() if v != [k]}
        if bad:
            raise SystemExit(
                f"REFUSED: node-name corner labels disagree with geometry "
                f"{bad}. Gate 6's own labels are the mirror of Gate 7+8's on "
                f"this car, so this is checked, never assumed")
        if sorted(cs) != list(WP.CORNERS):
            raise SystemExit(f"REFUSED: found corners {sorted(cs)}")
        plan = plan_wheels(post, cs, nose, args, report)
        plan = ground_wheels(plan, post, cs, args, report)
        for k, pl in plan.items():
            for n in cs[k]["nodes"]:
                lin[n] = pl["L"] @ lin[n]
                off[n] = pl["L"] @ (off[n] - pl["c_from"]) + pl["c_to"]
                post[n] = (post[n] - pl["c_from"]) @ pl["L"].T + pl["c_to"]
                post_n[n] = post_n[n] @ pl["NL"].T
        report["wheels"] = {k: _wrep(pl) for k, pl in plan.items()}

    # --- write. positions + normals only; the JSON is otherwise untouched.
    for name, (mi, pi, p, W) in prim_of.items():
        V = orig[name] @ lin[name].T + off[name]
        chk = float(np.abs(V - post[name]).max())
        if chk > 1e-9:
            raise SystemExit(f"REFUSED: composed affine for {name} disagrees "
                             f"with the staged transform by {chk:.3e} m")
        glb.write_accessor(p["attributes"]["POSITION"], V)
        N = post_n[name]
        ln = np.linalg.norm(N, axis=1)
        ok = ln > 1e-8
        N[ok] = N[ok] / ln[ok][:, None]
        glb.write_accessor(p["attributes"]["NORMAL"], N)
        nd = glb.g["nodes"][[i for i, x in enumerate(glb.g["nodes"])
                             if x.get("name") == name][0]]
        for key in ("translation", "rotation", "scale", "matrix"):
            nd.pop(key, None)
    report["zero_normals_after"] = int(sum(
        int((np.linalg.norm(post_n[n], axis=1) < 1e-8).sum()) for n in post_n))
    if report["zero_normals_after"] > report["zero_normals_before"]:
        raise SystemExit("REFUSED: the transform created zero-length normals")

    glb.save(args.out)
    out = GLB(args.out)
    d_mat = _diff(mats_before, material_table(out))
    d_bind = _diff(binds_before, binding_table(out))
    report["material_table_diff"] = d_mat
    report["binding_table_diff"] = d_bind
    if d_mat or d_bind:
        raise SystemExit(f"REFUSED: the write changed the material or binding "
                         f"table: {d_mat} {d_bind}")
    report["out_sha256"] = _sha(args.out)
    report["out_bytes"] = os.path.getsize(args.out)
    if args.report:
        json.dump(report, open(args.report, "w"), indent=1, default=_j)
    print(json.dumps({k: v for k, v in report.items()
                      if k not in ("wheels",)}, indent=1, default=_j))
    for k in sorted(report.get("wheels", {})):
        w = report["wheels"][k]
        print(f"  {k}: bottom {w['tyre_bottom_m'] * 1000:+.4f} mm  "
              f"contact {w['contact_verts']} v  s_rad {w['s_rad']:.5f}  "
              f"s_ax {w['s_ax']:.5f}  d_toe {w['d_toe_deg']:+.3f}  "
              f"d_camber {w['d_camber_deg']:+.3f}")
    return report


def _wrep(pl):
    m = pl["measured"]
    return dict(
        hub_from=[float(x) for x in pl["c_from"]],
        hub_to=[float(x) for x in pl["c_to"]],
        axis_from=[float(x) for x in m["axis"]],
        axis_to=[float(x) for x in pl["a_to"]],
        radius_from=m["R"], width_from=m["width"],
        s_rad=pl["s_rad"], s_ax=pl["s_ax"], det=pl["det"],
        toe_before_deg=m["toe_deg"], camber_before_deg=m["camber_deg"],
        d_toe_deg=-m["toe_deg"], d_camber_deg=-m["camber_deg"],
        coverage=m["coverage"], fit_rms_m=m["rms"],
        ground_drop_m=pl["ground_drop_m"], tyre_bottom_m=pl["tyre_bottom_m"],
        contact_verts=pl["contact_verts"], tyre_nodes=pl["tyre_nodes"],
        n_points=m["n"])


def _diff(a, b):
    out = {}
    for k in set(a) | set(b):
        if a.get(k) != b.get(k):
            out[k] = dict(before=a.get(k), after=b.get(k))
    return out


def _sha(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _j(o):
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    return str(o)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("glb")
    ap.add_argument("out")
    ap.add_argument("--stages", default="pose,wheels")
    ap.add_argument("--pose-mode", default="record", choices=("record", "derive"))
    ap.add_argument("--pose-json", default=None)
    ap.add_argument("--track-mode", default="measured",
                    choices=("measured", "gate6"))
    ap.add_argument("--radius", default="mean", choices=("mean", "gate6"))
    ap.add_argument("--width", default="mean", choices=("mean", "gate6"))
    ap.add_argument("--hub-x", default="measured", choices=("measured", "gate6"))
    ap.add_argument("--max-scale", type=float, default=DEFAULTS["max_scale"])
    ap.add_argument("--ground-pct", type=float, default=DEFAULTS["ground_pct"])
    ap.add_argument("--contact-tol-m", type=float,
                    default=DEFAULTS["contact_tol_m"])
    ap.add_argument("--report", default=None)
    a = ap.parse_args()
    if a.pose_mode == "record" and not a.pose_json:
        ap.error("--pose-mode record needs --pose-json")
    run(a)


if __name__ == "__main__":
    main()
