#!/usr/bin/env python3
"""wheel_rebuild.py — STAGE 2 repair: ONE approved wheel assembly, instanced
four times on measured axles, by ROTATION ONLY.

Run: blender -b --python wheel_rebuild.py -- IN.glb OUT.glb REPORT.json
                                             [--donor FR] [--dry]

WHAT THIS FIXES. The four corners of the source are four DIFFERENT meshes of
two different qualities: the right pair (FR, RR) are clean 10-spoke alloys, the
left pair (FL, RL) are torn melt with no spokes and large ragged holes. This was
established from isolated clay renders, not inferred, and the alternatives were
ruled out individually (0 negative scales, 0 mirrored determinants, 0 inverted
components on the rims, culling changes nothing, all four rims carry Rim_Alloy).

HOW IT FIXES IT. The donor corner's tyre/rim/disc mesh DATA is shared by four
node instances, so identical radius and width hold BY CONSTRUCTION rather than
by measurement afterwards. The left pair is placed with a 180 deg rotation about
the vertical axis -- determinant +1, winding and normals preserved. NEGATIVE
SCALING IS NEVER USED: a mirror flips winding, which is the documented cause of
this project's per-side wheel-void defect, and the brief forbids it outright.

WHAT IT DOES NOT DO, STATED PLAINLY. The source contains NO hub and NO caliper
node -- the assembly is tyre + rim + brake disc only. Those two components are
reported ABSENT and are NOT fabricated. Inventing them would be component
construction, not integrity repair, and this gate's rules forbid creating a node
so that an inventory reads full.
"""
import json
import math
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PARTS = ("Tyre", "Rim", "Disc")
CORNERS = ("FL", "FR", "RL", "RR")


def argv():
    a = sys.argv
    return a[a.index("--") + 1:] if "--" in a else []


def opt(a, f, d=None):
    return a[a.index(f) + 1] if f in a else d


def wverts(ob):
    n = len(ob.data.vertices)
    co = np.empty(n * 3, dtype=np.float64)
    ob.data.vertices.foreach_get("co", co)
    co = co.reshape(n, 3)
    m = np.array(ob.matrix_world, dtype=np.float64)
    return co @ m[:3, :3].T + m[:3, 3]


def basis(a):
    t = np.array([1.0, 0.0, 0.0])
    if abs(a @ t) > 0.9:
        t = np.array([0.0, 0.0, 1.0])
    e1 = np.cross(a, t)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(a, e1)
    return e1, e2 / np.linalg.norm(e2)


def circle_fit(u, v):
    A = np.column_stack([u, v, np.ones_like(u)])
    b = u ** 2 + v ** 2
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    u0, v0 = sol[0] / 2.0, sol[1] / 2.0
    return u0, v0, math.sqrt(max(0.0, sol[2] + u0 ** 2 + v0 ** 2))


def fit_axis(P, band=(0.97, 1.03), iters=18):
    """Same direct cylinder fit as wheel_metrology (validated against six
    synthetic controls incl. torn 120 deg arcs, where an SVD of the band gives
    an 88 deg axis error)."""
    a = np.array([0.0, 1.0, 0.0])
    c = P.mean(axis=0)

    def resid(ax, pts):
        e1, e2 = basis(ax)
        d = pts - pts.mean(axis=0)
        u, v = d @ e1, d @ e2
        u0, v0, R = circle_fit(u, v)
        return float(np.sqrt(((np.hypot(u - u0, v - v0) - R) ** 2).mean())), \
            (u0, v0, R, e1, e2)

    for _ in range(iters):
        e1, e2 = basis(a)
        d = P - c
        u, v = d @ e1, d @ e2
        r = np.hypot(u, v)
        R = np.percentile(r, 95)
        m = (r >= band[0] * R) & (r <= band[1] * R)
        if m.sum() < 50:
            break
        B = P[m]
        best, span, st = a, 6.0, 1.0
        for _lv in range(5):
            bb, br = None, None
            for d1 in np.arange(-span, span + 1e-9, st):
                for d2 in np.arange(-span, span + 1e-9, st):
                    ax = best + math.radians(d1) * e1 + math.radians(d2) * e2
                    ax /= np.linalg.norm(ax)
                    rr, _ = resid(ax, B)
                    if br is None or rr < br:
                        br, bb = rr, ax
            best, span, st = bb, st, st / 5.0
        an = best if best @ a >= 0 else -best
        _, (u0, v0, Rc, e1b, e2b) = resid(an, B)
        Bm = B.mean(axis=0)
        cn = Bm + u0 * e1b + v0 * e2b
        step = math.degrees(math.acos(max(-1, min(1, abs(float(an @ a))))))
        a, c = an, cn
        if step < 1e-4:
            break
    e1, e2 = basis(a)
    d = P - c
    r = np.hypot(d @ e1, d @ e2)
    Rs = float(np.percentile(r, 95))
    m = (r >= band[0] * Rs) & (r <= band[1] * Rs)
    u0, v0, Rf = circle_fit((d @ e1)[m], (d @ e2)[m])
    return a, c, float(Rf)


def rot_between(u, v):
    """Minimal rotation taking unit u to unit v. Determinant +1 always."""
    u = u / np.linalg.norm(u)
    v = v / np.linalg.norm(v)
    c = float(u @ v)
    if c > 1 - 1e-12:
        return np.eye(3)
    if c < -1 + 1e-12:
        t = np.array([1.0, 0, 0])
        if abs(u @ t) > 0.9:
            t = np.array([0, 0, 1.0])
        k = np.cross(u, t)
        k /= np.linalg.norm(k)
        K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
        return np.eye(3) + 2 * (K @ K)
    k = np.cross(u, v)
    s = np.linalg.norm(k)
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + K + (K @ K) * ((1 - c) / (s ** 2))


RZ180 = np.array([[-1.0, 0, 0], [0, -1.0, 0], [0, 0, 1.0]])


def set_world(ob, M4, tol=1e-9):
    """Assign a 4x4 world matrix and PROVE the readback matches.

    MEASURED IN THIS CONTAINER, Blender 4.5.12: `ob.matrix_world = M.tolist()`
    stores the TRANSPOSE. Assigning a 30 deg rotation about Z read back as -30
    deg, and a vertex at (1,0,0) landed at (0.866, -0.5, 0) instead of
    (0.866, +0.5, 0). In the first run of this repair that silently DOUBLED the
    donor's -3.43 deg camber to -6.98 deg instead of cancelling it to zero, and
    the wheels came out 42 mm through the floor. Nothing raised.

    So the matrix is transposed on the way in and the result is ASSERTED on the
    way out. An unverified matrix assignment is exactly the class of silent
    error this gate exists to catch.
    """
    ob.matrix_world = M4.T.tolist()
    bpy.context.view_layer.update()
    back = np.array(ob.matrix_world, dtype=np.float64)
    if not np.allclose(back, M4, atol=1e-6):
        raise RuntimeError(
            f"matrix_world readback mismatch on {ob.name}:\n"
            f"wanted\n{np.round(M4, 6)}\ngot\n{np.round(back, 6)}")
    return back


def main():
    a = argv()
    src, dst, rep = a[0], a[1], a[2]
    donor = opt(a, "--donor", "FR")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=src)
    obs = {o.name: o for o in bpy.data.objects if o.type == "MESH"}

    # ---- measure every corner from TRANSFORMED vertices
    meas = {}
    for c in CORNERS:
        t = obs.get(f"Wheel_{c}_Tyre")
        if t is None:
            continue
        ax, ct, R = fit_axis(wverts(t))
        meas[c] = {"axis": ax, "centre": ct, "radius": R,
                   "tyre_min_z": float(wverts(t)[:, 2].min())}

    # ---- symmetric target axles: L/R mirrored about y=0, front and rear
    # tracks kept separate (a real Golf's are 1549/1520 mm, not equal).
    tgt = {}
    for pair, (l, r) in (("F", ("FL", "FR")), ("R", ("RL", "RR"))):
        xs = np.mean([meas[l]["centre"][0], meas[r]["centre"][0]])
        yy = np.mean([abs(meas[l]["centre"][1]), abs(meas[r]["centre"][1])])
        zs = np.mean([meas[l]["centre"][2], meas[r]["centre"][2]])
        tgt[l] = np.array([xs, +yy, zs])
        tgt[r] = np.array([xs, -yy, zs])

    # ---- donor frame: axis exactly outboard -Y, ZERO toe and ZERO camber.
    dax, dctr, dR = meas[donor]["axis"], meas[donor]["centre"], meas[donor]["radius"]
    dax_out = dax if dax[1] < 0 else -dax           # donor is a RIGHT corner
    Ralign = rot_between(dax_out, np.array([0.0, -1.0, 0.0]))

    # ---- ground the assembly: after alignment, put the tyre's lowest point at
    # z = 0 exactly. Measured on the ROTATED donor, not assumed from radius --
    # a tyre 4.5 mm out of round does not touch at exactly -R.
    dt = wverts(obs[f"Wheel_{donor}_Tyre"])
    dt_al = (dt - dctr) @ Ralign.T
    drop = float(dt_al[:, 2].min())                 # negative

    report = {"stage": "2 repair — one assembly, four instances",
              "donor_corner": donor,
              "donor_axis_measured": [round(float(v), 6) for v in dax_out],
              "donor_radius_m": round(dR, 6),
              "donor_tyre_low_after_align_m": round(drop, 6),
              "hub_absent": True, "caliper_absent": True,
              "hub_caliper_note": ("source contains no hub and no caliper node; "
                                   "NOT fabricated — that is component "
                                   "construction, not integrity repair"),
              "measured_before": {c: {
                  "centre": [round(float(v), 6) for v in meas[c]["centre"]],
                  "radius_m": round(meas[c]["radius"], 6)} for c in meas},
              "target_axles": {c: [round(float(v), 6) for v in tgt[c]]
                               for c in tgt},
              "instances": {}}

    if "--dry" in a:
        json.dump(report, open(rep, "w"), indent=1)
        print("DRY_RUN_DONE")
        return

    # ---- build the four instances from the DONOR MESH DATA (true sharing)
    donor_data = {p: obs[f"Wheel_{donor}_{p}"].data for p in PARTS}
    donor_mw = {p: np.array(obs[f"Wheel_{donor}_{p}"].matrix_world)
                for p in PARTS}

    for c in CORNERS:
        left = c[1] == "L"
        M = (RZ180 @ Ralign) if left else Ralign
        centre = tgt[c].copy()
        centre[2] = -drop        # tyre bottom lands exactly on z = 0
        report["instances"][c] = {
            "side": "L" if left else "R",
            "rotation_det": round(float(np.linalg.det(M)), 9),
            "uses_negative_scale": False,
            "centre": [round(float(v), 6) for v in centre],
            "shares_mesh_with_donor": True,
        }
        for p in PARTS:
            old = obs.get(f"Wheel_{c}_{p}")
            if old is not None:
                bpy.data.objects.remove(old, do_unlink=True)
            ob = bpy.data.objects.new(f"Wheel_{c}_{p}", donor_data[p])
            bpy.context.collection.objects.link(ob)
            # world = translate(centre) . M . translate(-dctr) . donor_world
            T = np.eye(4)
            T[:3, :3] = M
            T[:3, 3] = centre - M @ dctr
            set_world(ob, T @ donor_mw[p])

    bpy.context.view_layer.update()

    # ---- VERIFY on the rebuilt scene, before export
    ver = {}
    for c in CORNERS:
        t = bpy.data.objects[f"Wheel_{c}_Tyre"]
        V = wverts(t)
        ax, ct, R = fit_axis(V)
        out = ax if ((c[1] == "L" and ax[1] > 0) or
                     (c[1] == "R" and ax[1] < 0)) else -ax
        toe = math.degrees(math.atan2(out[0], abs(out[1])))
        if c[1] == "R":
            toe = -toe
        cam = math.degrees(math.asin(max(-1, min(1, out[2]))))
        det = float(np.linalg.det(np.array(t.matrix_world)[:3, :3]))
        ver[c] = {"radius_m": round(R, 6),
                  "centre": [round(float(v), 6) for v in ct],
                  "toe_deg": round(toe, 4), "camber_deg": round(cam, 4),
                  "tyre_bottom_mm": round(float(V[:, 2].min()) * 1000, 4),
                  "world_det": round(det, 9),
                  "negative_scale": bool(det < 0)}
    report["verify_in_scene"] = ver
    report["hub_symmetry_mm"] = {
        "front": round(abs(abs(ver["FL"]["centre"][1])
                           - abs(ver["FR"]["centre"][1])) * 1000, 4),
        "rear": round(abs(abs(ver["RL"]["centre"][1])
                          - abs(ver["RR"]["centre"][1])) * 1000, 4)}
    report["radius_spread_mm"] = round(
        (max(v["radius_m"] for v in ver.values())
         - min(v["radius_m"] for v in ver.values())) * 1000, 4)

    bpy.ops.export_scene.gltf(
        filepath=dst, export_format="GLB", use_selection=False,
        export_apply=False, export_yup=True, export_normals=True,
        export_materials="EXPORT", export_cameras=False, export_lights=False)
    report["exported"] = dst
    json.dump(report, open(rep, "w"), indent=1)
    print("WHEEL_REBUILD_DONE", dst)
    print(json.dumps({k: report[k] for k in
                      ("hub_symmetry_mm", "radius_spread_mm")}, indent=1))
    for c in CORNERS:
        v = ver[c]
        print(f"  {c} R={v['radius_m']:.5f} toe={v['toe_deg']:+.4f} "
              f"cam={v['camber_deg']:+.4f} bottom={v['tyre_bottom_mm']:+.3f}mm "
              f"det={v['world_det']:+.4f}")


if __name__ == "__main__":
    main()
