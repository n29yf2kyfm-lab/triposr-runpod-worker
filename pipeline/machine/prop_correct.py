#!/usr/bin/env python3
"""prop_correct.py — post-placement overhang correction, axle-anchored.

WHY THIS EXISTS (independent verification, 2026-08-18): body_align warps
the body to spec proportions BEFORE the wheel stage, but the wheel stage
then re-detects the arches on the warped body and places wheels at the
DETECTED positions — measured 13.7mm forward of the warp's targets on
V53 (a consistent detector bias; wheelbase preserved exactly). Add the
tail extending ~9mm past body_align's percentile anchor and the shipped
rear overhang measured +2.84% against spec — outside the brief's ±1%
dimensional gate, while my earlier report claimed +1.7%. The overhang a
customer sees is nose/tail relative to the wheels ACTUALLY PLACED, so
the correction must run after placement, anchored on the real axles.

The map: identity everywhere between (and around) the axles — the
wheel/arch relationship is untouched out to 1.35 x tyre R from each
axle — then a smoothstep-ramped local scale over each overhang cap so
the body's true extreme vertex lands exactly at axle +/- spec overhang.
Monotone by construction for corrections under ~30%; asserted anyway.
Wheel-system nodes (WHEEL_/LINER_) pass through unwarped.

Gate: overhangs re-measured FROM THE OUTPUT FILE must sit within +/-1%
of spec or the stage exits FAIL.

Run: python3 prop_correct.py <in.glb> <spec.json> <out.glb> <qc.json>
"""
import json
import os
import struct
import sys
import numpy as np
import trimesh

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from carspec import CarSpec

inp, spec_path, out_path, qc_path = sys.argv[1:5]
spec = CarSpec.load(spec_path)
report = {"stage": "prop_correct", "input": inp, "spec": spec.path}

FO, FOsrc = spec.dim("front_overhang_m")
RO, ROsrc = spec.dim("rear_overhang_m")
if FO is None or RO is None:
    report["status"] = "SKIPPED"
    report["reason"] = "spec carries no overhang dimensions — nothing to correct against"
    json.dump(report, open(qc_path, "w"), indent=1)
    raise SystemExit(f"SKIPPED: {report['reason']}")

sc = trimesh.load(inp, force="scene")
# actual axle positions from the placed wheel nodes — the ground truth
ax = {}
for tag in ("FR", "FL", "RR", "RL"):
    node = f"WHEEL_{tag}__TYRE_MASTER"
    if node not in sc.graph.nodes_geometry:
        raise SystemExit(f"REFUSED: {node} absent — run wheel_stage first")
    T, _ = sc.graph[node]
    ax[tag] = float(T[0, 3])
fx = (ax["FR"] + ax["FL"]) / 2
rx = (ax["RR"] + ax["RL"]) / 2
tyre_pts = trimesh.transform_points(
    sc.geometry["TYRE_MASTER"].vertices, sc.graph["WHEEL_FR__TYRE_MASTER"][0])
R = float(tyre_pts[:, 1].max() - tyre_pts[:, 1].min()) / 2

skin_names = [n for n in spec.label("body_skin_nodes",
              [spec.label("body", "carpaint")]) if n in sc.geometry]
if not skin_names:
    raise SystemExit("REFUSED: no configured body-skin nodes present")
skin = np.vstack([sc.geometry[n].vertices for n in skin_names])
nose, tail = float(skin[:, 0].max()), float(skin[:, 0].min())
fo_now, ro_now = nose - fx, rx - tail
report["measured_before"] = {
    "front_axle_x": round(fx, 4), "rear_axle_x": round(rx, 4),
    "nose_x": round(nose, 4), "tail_x": round(tail, 4),
    "front_overhang": {"value": round(fo_now, 4),
                       "error_pct": round(100 * (fo_now / FO - 1), 2)},
    "rear_overhang": {"value": round(ro_now, 4),
                      "error_pct": round(100 * (ro_now / RO - 1), 2)},
    "definition": f"extreme vertex over skin nodes {skin_names} vs placed axles"}
print(f"before: FO {fo_now:.4f} ({report['measured_before']['front_overhang']['error_pct']:+.2f}%), "
      f"RO {ro_now:.4f} ({report['measured_before']['rear_overhang']['error_pct']:+.2f}%)")

GUARD = 1.35 * R          # identity zone beyond each axle: arch untouched
f0, r0 = fx + GUARD, rx - GUARD
if nose <= f0 or tail >= r0:
    raise SystemExit("REFUSED: overhang shorter than the arch guard zone — "
                     "geometry does not look like a car with these axles")


def cap_map(x0, x1_src, x1_dst, sign):
    """Monotone map on the cap [x0, x1_src] -> [x0, x1_dst].

    Local scale ramps (smoothstep) from 1 at x0 to s_f over the first 30%
    of the cap, then holds; s_f solved in closed form so the extreme lands
    exactly on target. sign = +1 nose cap, -1 tail cap.
    """
    span_s = abs(x1_src - x0)
    span_d = abs(x1_dst - x0)
    B = 0.30 * span_s
    A_w = span_s - B / 2          # integral of the smoothstep weight
    s_f = 1 + (span_d - span_s) / A_w
    assert s_f > 0.5, f"cap scale {s_f:.3f} out of safe range"
    grid = np.linspace(0, span_s, 2048)
    t = np.clip(grid / B, 0, 1)
    w = 3 * t**2 - 2 * t**3
    s = 1 + (s_f - 1) * w
    mapped = np.concatenate([[0], np.cumsum((s[1:] + s[:-1]) / 2 * np.diff(grid))])
    mapped *= span_d / mapped[-1]         # exact endpoint (kills quadrature error)
    assert np.all(np.diff(mapped) > 0), "cap map not monotone"
    return grid, mapped, s_f


gf, mf, sf_f = cap_map(f0, nose, fx + FO, +1)
gr, mr, sf_r = cap_map(r0, tail, rx - RO, -1)
report["warp"] = {
    "identity_zone": [round(r0, 4), round(f0, 4)],
    "arch_guard": "1.35 x tyre R beyond each axle",
    "front_cap_scale_final": round(float(sf_f), 4),
    "rear_cap_scale_final": round(float(sf_r), 4),
    "targets": {"front_overhang": {"value": FO, "source": FOsrc},
                "rear_overhang": {"value": RO, "source": ROsrc}}}
print(f"cap scales: front {sf_f:.4f}, rear {sf_r:.4f} "
      f"(identity zone {r0:.3f}..{f0:.3f})")


def fmap(x):
    y = x.copy()
    hi = x > f0
    y[hi] = f0 + np.interp(x[hi] - f0, gf, mf)
    lo = x < r0
    y[lo] = r0 - np.interp(r0 - x[lo], gr, mr)
    return y


out = trimesh.Scene()
warped = 0
for node in sc.graph.nodes_geometry:
    T, gn = sc.graph[node]
    g = sc.geometry[gn]
    if not (node.startswith("WHEEL_") or node.startswith("LINER_")):
        if gn not in out.geometry:
            g = g.copy()
            v = g.vertices.copy()
            v[:, 0] = fmap(v[:, 0])
            g.vertices = v
            # compression can collapse melt slivers -> zero-area faces ->
            # zero-length normals -> validator ACCESSOR_VECTOR3_NON_UNIT
            # (one carpaint vertex, measured on the first V55 build)
            if len(g.faces):
                tri = g.triangles
                area = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0],
                                               tri[:, 2] - tri[:, 0]), axis=1)
                if (area < 1e-10).any():
                    g.update_faces(area >= 1e-10)
                    g.remove_unreferenced_vertices()
                vn = np.array(g.vertex_normals)
                bad = np.linalg.norm(vn, axis=1) < 1e-6
                if bad.any():
                    vn[bad] = [0.0, 1.0, 0.0]
                    g.vertex_normals = vn
            warped += 1
            out.add_geometry(g, geom_name=gn, node_name=node, transform=T)
        else:
            out.graph.update(frame_to=node, matrix=T, geometry=gn)
    else:
        if gn not in out.geometry:
            out.add_geometry(g, geom_name=gn, node_name=node, transform=T)
        else:
            out.graph.update(frame_to=node, matrix=T, geometry=gn)
print(f"warped {warped} geometries (wheel system untouched)")
out.export(out_path, include_normals=True)

with open(out_path, "rb") as fh:
    fh.seek(12); ln, _ = struct.unpack("<II", fh.read(8)); j = json.loads(fh.read(ln))
missing = [m.get("name") for m in j["meshes"]
           if any("NORMAL" not in p["attributes"] for p in m["primitives"])]
if missing:
    raise SystemExit(f"REFUSED: NORMAL missing on {missing[:4]}")

# ------------------- gate, FROM THE EXPORTED FILE -------------------
sc2 = trimesh.load(out_path, force="scene")
skin2 = np.vstack([sc2.geometry[n].vertices for n in skin_names])
ax2 = {}
for tag in ("FR", "FL", "RR", "RL"):
    T, _ = sc2.graph[f"WHEEL_{tag}__TYRE_MASTER"]
    ax2[tag] = float(T[0, 3])
fx2, rx2 = (ax2["FR"] + ax2["FL"]) / 2, (ax2["RR"] + ax2["RL"]) / 2
fo2 = float(skin2[:, 0].max()) - fx2
ro2 = rx2 - float(skin2[:, 0].min())
ef, er = 100 * (fo2 / FO - 1), 100 * (ro2 / RO - 1)
gate = "PASS" if (abs(ef) <= 1.0 and abs(er) <= 1.0) else "FAIL"
report["measured_after"] = {
    "front_overhang": {"value": round(fo2, 4), "error_pct": round(ef, 2)},
    "rear_overhang": {"value": round(ro2, 4), "error_pct": round(er, 2)},
    "gate_limit_pct": 1.0, "gate": gate}
report["status"] = gate
json.dump(report, open(qc_path, "w"), indent=1)
print(f"after: FO {fo2:.4f} ({ef:+.2f}%), RO {ro2:.4f} ({er:+.2f}%) -> {gate}")
print(f"wrote {out_path} ({os.path.getsize(out_path)} bytes) + {qc_path}")
if gate != "PASS":
    raise SystemExit("overhang gate FAIL")
