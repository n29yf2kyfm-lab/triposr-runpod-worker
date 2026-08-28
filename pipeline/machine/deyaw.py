#!/usr/bin/env python3
"""deyaw.py — align a car to its own MIRROR PLANE of symmetry.

WHAT IT FIXES, and how it was found. On the Tripo v3.1 Golf a whole session's
headline finding was "the generated body is left-right SKEWED — 194mm (24.6%)
at the rear axle, 114mm at the front, and the sign FLIPS between them, so it
is twisted and no downstream stage can repair it." That was WRONG, and a
council audit killed it with one measurement:

    mirror residual at canon's own z=0 plane :  66.9 mm = 1.57% of length
    mirror residual at the OPTIMAL plane     :   9.8 mm = 0.23% of length
    optimal plane: z0 +0.0240 m, tilt_y +4.11 deg

0.23% is the same band as the Hunyuan output this project already measured as
SYMMETRIC (0.16% mean, 0.28% p95). The car was never twisted. It is YAWED ~4
degrees in the canonical frame, and slicing a yawed car with axis-aligned
slabs manufactures exactly the observed signature: one side wider at the tail,
the other wider at the nose, with a sign flip in the middle. Two independent
methods agreed — PCA long axis -3.80 deg, and axle lateral midpoints of
OPPOSITE sign (-48mm front, +95mm rear).

WHY IT MATTERS MORE THAN IT LOOKS. Every symmetric operation downstream is
placed about z=0: wheel centres, arch liners, lamp kits, plate plinths, the
interior kit. Under a 4 degree yaw those all land skewed relative to the body,
which is why premium's symmetrically-placed arch liners protruded on a
DIAGONAL pair (FR +130.7mm, RL +219.5mm) while the other two sat flush. The
observable was blamed on the generator; the cause was our own pose.

METHOD. Fit the plane (offset + two tilts) that minimises the nearest-
neighbour distance between the mesh and its own reflection, then rotate that
plane onto z=0. This is a whole-body fit with no zones, no percentiles and no
hand-picked bands — the very things that made the original skew claim
unfalsifiable.

SAFETY. Written as a root-node transform with the BIN chunk VERBATIM (the
pose_fix / clay_rebuild pattern), so it cannot damage geometry, UVs or
normals. The rotation is a proper rotation (determinant +1, never a mirror),
so winding and normals stay valid. It REFUSES when the fit does not improve
matters or when the correction exceeds a sane cap, because a large "fix" here
would mean the fit found something other than the car's symmetry plane.

Run:
  python3 deyaw.py <in.glb> <out.glb> [--max-deg 12] [--min-gain 1.25] [--report x.json]
"""
import argparse
import json
import os
import struct

import numpy as np
import trimesh
from scipy.optimize import minimize
from scipy.spatial import cKDTree

REF_N = 250_000
SMP_N = 25_000


def read_glb(path):
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:4] != b"glTF":
        raise SystemExit(f"REFUSED: {path} is not a binary glTF")
    n = struct.unpack("<I", data[12:16])[0]
    return json.loads(data[20:20 + n]), data[20 + n:]


def write_glb(path, j, rest):
    js = json.dumps(j, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    with open(path, "wb") as fh:
        fh.write(b"glTF" + struct.pack("<II", 2, 12 + 8 + len(js) + len(rest)))
        fh.write(struct.pack("<I", len(js)) + b"JSON" + js)
        fh.write(rest)


def world_vertices(path):
    sc = trimesh.load(path, force="scene")
    out = []
    for node in sc.graph.nodes_geometry:
        T, gname = sc.graph[node]
        out.append(trimesh.transform_points(sc.geometry[gname].vertices, T))
    return np.vstack(out)


def plane_normal(ax, ay):
    n = np.array([np.sin(ay), np.sin(ax), 1.0])
    return n / np.linalg.norm(n)


def fit_plane(V, seed=0):
    rng = np.random.default_rng(seed)
    ref = V[rng.choice(len(V), min(REF_N, len(V)), replace=False)]
    smp = V[rng.choice(len(V), min(SMP_N, len(V)), replace=False)]
    tree = cKDTree(ref)

    def resid(p):
        z0, ax, ay = p
        n = plane_normal(ax, ay)
        d = (smp - np.array([0.0, 0.0, z0])) @ n
        return float(tree.query(smp - 2.0 * d[:, None] * n[None, :], k=1)[0].mean())

    before = resid([0.0, 0.0, 0.0])
    r = minimize(resid, [0.0, 0.0, 0.0], method="Nelder-Mead",
                 options={"xatol": 1e-4, "fatol": 1e-6, "maxiter": 200})
    return before, float(r.fun), r.x


def rotation_to_z(n):
    """Proper rotation taking unit vector n onto +Z. Determinant +1 by
    construction (Rodrigues), so winding and normals stay valid — never a
    mirror, which would invert them."""
    z = np.array([0.0, 0.0, 1.0])
    v = np.cross(n, z)
    s, c = np.linalg.norm(v), float(np.dot(n, z))
    if s < 1e-12:
        return np.eye(3) if c > 0 else np.diag([1.0, -1.0, -1.0])
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + K + K @ K * ((1 - c) / (s ** 2))


def mat_to_quat(R):
    t = np.trace(R)
    if t > 0:
        s = np.sqrt(t + 1.0) * 2
        w, x, y, z = 0.25 * s, (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        w, x, y, z = (R[2, 1] - R[1, 2]) / s, 0.25 * s, (R[0, 1] + R[1, 0]) / s, (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        w, x, y, z = (R[0, 2] - R[2, 0]) / s, (R[0, 1] + R[1, 0]) / s, 0.25 * s, (R[1, 2] + R[2, 1]) / s
    else:
        s = np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
        w, x, y, z = (R[1, 0] - R[0, 1]) / s, (R[0, 2] + R[2, 0]) / s, (R[1, 2] + R[2, 1]) / s, 0.25 * s
    q = np.array([x, y, z, w])
    return q / np.linalg.norm(q)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--max-deg", type=float, default=12.0,
                    help="refuse a correction larger than this (a big one means "
                         "the fit did not find the car's symmetry plane)")
    ap.add_argument("--min-gain", type=float, default=1.25,
                    help="refuse unless residual improves by at least this factor")
    ap.add_argument("--report", default=None)
    a = ap.parse_args()

    V = world_vertices(a.inp)
    L = float(V[:, 0].max() - V[:, 0].min())
    before, after, p = fit_plane(V)
    z0, ax, ay = p
    n = plane_normal(ax, ay)
    deg = float(np.degrees(np.arccos(min(1.0, abs(float(np.dot(n, [0, 0, 1])))))))
    gain = before / max(after, 1e-9)

    print(f"mirror residual before : {before*1000:7.2f} mm = {before/L*100:.3f}% of length")
    print(f"mirror residual after  : {after*1000:7.2f} mm = {after/L*100:.3f}% of length")
    print(f"correction             : {deg:.2f} deg, lateral offset {z0*1000:+.1f} mm  "
          f"(gain x{gain:.2f})")

    rep = {"input": a.inp, "length_m": L,
           "residual_before_mm": before * 1000, "residual_after_mm": after * 1000,
           "residual_before_pct": before / L * 100, "residual_after_pct": after / L * 100,
           "correction_deg": deg, "offset_mm": z0 * 1000, "gain": gain}

    if deg > a.max_deg:
        raise SystemExit(f"REFUSED: correction {deg:.2f} deg exceeds --max-deg "
                         f"{a.max_deg}; the fit likely locked onto something "
                         f"other than the car's symmetry plane")
    if gain < a.min_gain:
        raise SystemExit(f"REFUSED: residual improved only x{gain:.2f} "
                         f"(< --min-gain {a.min_gain}); the car is already "
                         f"aligned and rewriting it would be a no-op dressed "
                         f"up as a fix")

    R = rotation_to_z(n)
    assert np.linalg.det(R) > 0, "rotation must be proper (det +1), never a mirror"
    q = mat_to_quat(R)
    # translate the plane onto z=0 first, then rotate: p' = R (p - z0*n)
    t = -R @ (z0 * n)

    j, rest = read_glb(a.inp)
    scene = j.get("scenes", [{}])[j.get("scene", 0)]
    roots = list(scene.get("nodes", []))
    j.setdefault("nodes", []).append({
        "name": "deyaw", "children": roots,
        "rotation": [float(v) for v in q],
        "translation": [float(v) for v in t]})
    scene["nodes"] = [len(j["nodes"]) - 1]
    write_glb(a.out, j, rest)

    # VERIFY on the written file, not on the intention
    V2 = world_vertices(a.out)
    b2, a2, _ = fit_plane(V2, seed=1)
    print(f"verified on output     : residual at z=0 is now {b2*1000:.2f} mm "
          f"({b2/L*100:.3f}% of length)")
    rep["verified_residual_mm"] = b2 * 1000
    if b2 > before:
        raise SystemExit("REFUSED: output is LESS symmetric than the input — "
                         "the transform was applied wrongly")
    if a.report:
        json.dump(rep, open(a.report, "w"), indent=1)
    print(f"wrote {a.out} ({os.path.getsize(a.out)} bytes; BIN verbatim, "
          f"root-node transform only)")


if __name__ == "__main__":
    main()
