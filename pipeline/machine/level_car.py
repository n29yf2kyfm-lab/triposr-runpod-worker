#!/usr/bin/env python3
"""level_car.py — put all four tyres on the ground. Nothing else ever did.

THE DEFECT. The owner, on a car the whole gate table had just passed: "why
the fucking car up in the air?" Measured on that file:

    whole-model lowest point   y = 0.0047
    front-R tyre contact       y = 0.1548   -> 150.2 mm IN THE AIR
    front-L tyre contact       y = 0.1548   -> 150.2 mm IN THE AIR
    rear-R  tyre contact       y = 0.0053   ->   0.6 mm
    rear-L  tyre contact       y = 0.0067   ->   2.0 mm

    nose-up pitch: 149.6 mm over a 2.583 m wheelbase = 3.31 degrees

The rear sits down and the front hangs. That is in the GEOMETRY, not the
render — it was measured on the file before any camera existed.

WHY NOTHING CAUGHT IT. The chain corrects YAW (deyaw) and resolves the 180
degree nose AMBIGUITY (nose_fix). PITCH is corrected by nothing, and
`grep -icE "ground|pitch|level|contact"` over the whole driver returned 1,
inside a comment. `wheel_ground_op.py` and `wheel_metrology.py` exist in
this repo, were built for exactly this, and the driver never called either.

Every gate in the chain measures MATERIALS or LABELS — glass area share,
paint-on-windows, boundary length, class counts. Not one asks where the car
sits. CLAUDE.md already records the trap in as many words: "do not trust
viewer_check.py's on_ground result — it reads the WHOLE-MODEL bbox min-Y,
so the Golf passes at +0.3 mm while its front tyres are 183-190 mm in the
air. Measure from the TYRE nodes' world-space minima." Same defect, same
car, written down before it happened again.

METHOD. The ground plane of a car is its CONTACT PATCHES, never its lowest
vertex — the lowest vertex is a splitter, an underbody smear, or in this
car the interior shell at y=0.0047. So: cluster the tyre geometry into four
corners by the sign of x and z, take the lowest slice of each, least-
squares a plane through the four contact points, rotate that plane's normal
onto +Y, and drop the car so the lowest patch sits at y=0.

It runs LAST, after every label and kit stage. A rigid transform at the end
cannot invalidate anything upstream — labels, stencil bands and the
interior kit were all computed in the original frame and rotate with the
body — whereas levelling early would move the ground under every stage that
measures against it.

Written as a root-node matrix with the BIN chunk VERBATIM (the pose_fix /
deyaw pattern). Rotation only, determinant +1, so winding and normals stay
valid — never add a mirror to that set.

REFUSES above --max-deg, because a large correction means the pose is wrong
in some way a rotation should not paper over, and verifies on the WRITTEN
file rather than on intent.

Run: python3 level_car.py <in.glb> <out.glb> [--max-deg 8] [--report r.json]
"""
import argparse
import json
import os
import struct

import numpy as np
import trimesh

TYRE = "Tyre_Rubber"
PATCH_PCT = 3.0          # lowest % of each corner's verts = its contact patch


def read_glb(path):
    d = open(path, "rb").read()
    if d[:4] != b"glTF":
        raise SystemExit(f"REFUSED: {path} is not a binary glTF")
    n = struct.unpack("<I", d[12:16])[0]
    return json.loads(d[20:20 + n]), d[20 + n:]


def write_glb(path, j, rest):
    js = json.dumps(j, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    with open(path, "wb") as fh:
        fh.write(b"glTF" + struct.pack("<II", 2, 12 + 8 + len(js) + len(rest)))
        fh.write(struct.pack("<I", len(js)) + b"JSON" + js)
        fh.write(rest)


def contacts(path, tyre=TYRE):
    """World-space contact point of each of the four corners."""
    sc = trimesh.load(path, force="scene")
    pts = []
    for node in sc.graph.nodes_geometry:
        T, g = sc.graph[node]
        if g != tyre:
            continue
        pts.append(trimesh.transform_points(sc.geometry[g].vertices, T))
    if not pts:
        have = sorted(sc.geometry)
        raise SystemExit(f"REFUSED: no {tyre!r} geometry — the contact "
                         f"patches are the only honest ground plane, and the "
                         f"lowest VERTEX is a splitter or an underbody smear. "
                         f"This file has {have}")
    v = np.vstack(pts)
    out = {}
    for nm, kx, kz in (("FR", 1, 1), ("FL", 1, -1), ("RR", -1, 1),
                       ("RL", -1, -1)):
        k = (np.sign(v[:, 0]) == kx) & (np.sign(v[:, 2]) == kz)
        if k.sum() < 20:
            raise SystemExit(f"REFUSED: corner {nm} has {int(k.sum())} tyre "
                             f"vertices — cannot locate its contact patch")
        c = v[k]
        thr = np.percentile(c[:, 1], PATCH_PCT)
        patch = c[c[:, 1] <= thr]
        out[nm] = patch.mean(axis=0)
    return out, sc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--tyre", default=TYRE)
    ap.add_argument("--max-deg", type=float, default=8.0)
    ap.add_argument("--report", default=None)
    a = ap.parse_args()

    cp, _ = contacts(a.inp, a.tyre)
    P = np.array([cp[k] for k in ("FR", "FL", "RR", "RL")])
    lo = P[:, 1].min()
    print("contact patches (world):")
    for k in ("FR", "FL", "RR", "RL"):
        print(f"  {k}: x {cp[k][0]:7.3f}  y {cp[k][1]:7.4f}  z {cp[k][2]:7.3f}"
              f"   {1000*(cp[k][1]-lo):7.1f} mm above the lowest patch")
    wb = abs(0.5 * (cp["FR"][0] + cp["FL"][0]) - 0.5 * (cp["RR"][0] + cp["RL"][0]))
    tr = abs(0.5 * (cp["FR"][2] + cp["RR"][2]) - 0.5 * (cp["FL"][2] + cp["RL"][2]))
    dpitch = 0.5 * (cp["FR"][1] + cp["FL"][1]) - 0.5 * (cp["RR"][1] + cp["RL"][1])
    droll = 0.5 * (cp["FR"][1] + cp["RR"][1]) - 0.5 * (cp["FL"][1] + cp["RL"][1])
    pitch = np.degrees(np.arctan2(dpitch, wb))
    roll = np.degrees(np.arctan2(droll, tr))
    print(f"\nwheelbase {wb:.3f} m, track {tr:.3f} m")
    print(f"BEFORE  pitch {pitch:+.2f} deg ({1000*dpitch:+.1f} mm), "
          f"roll {roll:+.2f} deg ({1000*droll:+.1f} mm), "
          f"spread {1000*(P[:,1].max()-P[:,1].min()):.1f} mm")

    if max(abs(pitch), abs(roll)) > a.max_deg:
        raise SystemExit(f"REFUSED: {max(abs(pitch),abs(roll)):.2f} deg is "
                         f"more than --max-deg {a.max_deg} — a correction "
                         f"that large means the pose is wrong in a way a "
                         f"rotation should not paper over")
    if P[:, 1].max() - P[:, 1].min() < 0.002:
        raise SystemExit("REFUSED: all four patches already within 2 mm — "
                         "writing an unchanged copy would be a no-op dressed "
                         "as a fix")

    # least-squares plane y = ax + bz + c through the four contact points
    A = np.stack([P[:, 0], P[:, 2], np.ones(4)], 1)
    (ca, cb, cc), *_ = np.linalg.lstsq(A, P[:, 1], rcond=None)
    nrm = np.array([-ca, 1.0, -cb])
    nrm /= np.linalg.norm(nrm)
    up = np.array([0.0, 1.0, 0.0])
    axis = np.cross(nrm, up)
    s, c = np.linalg.norm(axis), float(np.dot(nrm, up))
    if s < 1e-9:
        R = np.eye(4)
    else:
        axis = axis / s
        R = trimesh.transformations.rotation_matrix(np.arctan2(s, c), axis)
    assert abs(np.linalg.det(R[:3, :3]) - 1.0) < 1e-6, "not a proper rotation"

    rot = trimesh.transform_points(P, R)
    drop = rot[:, 1].min()
    M = np.eye(4)
    M[1, 3] = -drop
    M = M @ R

    j, rest = read_glb(a.inp)
    scene = j.get("scenes", [{}])[j.get("scene", 0)]
    roots = list(scene.get("nodes", []))
    j.setdefault("nodes", []).append(
        {"name": "level_car", "children": roots,
         "matrix": [float(x) for x in M.T.reshape(-1)]})
    scene["nodes"] = [len(j["nodes"]) - 1]
    write_glb(a.out, j, rest)

    cp2, _ = contacts(a.out, a.tyre)
    P2 = np.array([cp2[k] for k in ("FR", "FL", "RR", "RL")])
    d2p = 0.5 * (cp2["FR"][1] + cp2["FL"][1]) - 0.5 * (cp2["RR"][1] + cp2["RL"][1])
    d2r = 0.5 * (cp2["FR"][1] + cp2["RR"][1]) - 0.5 * (cp2["FL"][1] + cp2["RL"][1])
    spread = 1000 * (P2[:, 1].max() - P2[:, 1].min())
    print(f"AFTER   pitch {np.degrees(np.arctan2(d2p,wb)):+.2f} deg "
          f"({1000*d2p:+.1f} mm), roll {np.degrees(np.arctan2(d2r,tr)):+.2f} deg "
          f"({1000*d2r:+.1f} mm), spread {spread:.1f} mm")
    print(f"        lowest patch now at y {P2[:,1].min():+.5f}")
    if spread > 2.0:
        raise SystemExit(f"REFUSED: patches still {spread:.1f} mm apart after "
                         f"levelling — the fit did not land")
    if abs(P2[:, 1].min()) > 0.002:
        raise SystemExit(f"REFUSED: car sits {1000*P2[:,1].min():+.1f} mm off "
                         f"the floor after levelling")
    print(f"wrote {a.out} ({os.path.getsize(a.out)} bytes; BIN verbatim)")

    if a.report:
        json.dump({"wheelbase_m": float(wb), "track_m": float(tr),
                   "before": {"pitch_deg": float(pitch), "roll_deg": float(roll),
                              "spread_mm": float(1000*(P[:,1].max()-P[:,1].min()))},
                   "after": {"pitch_deg": float(np.degrees(np.arctan2(d2p, wb))),
                             "roll_deg": float(np.degrees(np.arctan2(d2r, tr))),
                             "spread_mm": float(spread),
                             "floor_mm": float(1000*P2[:, 1].min())}},
                  open(a.report, "w"), indent=1)


if __name__ == "__main__":
    main()
