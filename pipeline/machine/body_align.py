#!/usr/bin/env python3
"""body_align.py — proportion alignment, car-agnostic (owner critique 2026-08-18).

The owner read the V51 side view as "long nose, high tail" and the
measurement agreed: front overhang +7.3%, rear overhang +13.8%, wheelbase
-5.5% — the generator put the arches too close together while overall
length is right, so both ends are stretched.

Fix: a MONOTONE PIECEWISE warp of x through four anchors —
(tail, rear axle, front axle, nose) mapped to the spec's proportions
(wheelbase + overhang split). Axle positions come from the same
label-free arch detector the wheel stage uses; targets come from the
CarSpec. Everything body-attached is warped (glass, lamps, interior);
nodes matching the wheel-strip prefixes are left alone because the wheel
stage strips and rebuilds them next. PCHIP keeps the map C1 so no crease
appears at the axle planes; local scale stays within a few percent.

Emits a DERIVED spec (expect.axle_x = the warp's target axle positions,
tight tolerance) so the downstream wheel stage self-tests against what
this stage just constructed.

Run: python3 body_align.py <in.glb> <spec.json> <out.glb> <derived_spec.json> <qc.json>
"""
import json
import os
import struct
import sys
import numpy as np
import trimesh
from scipy.interpolate import PchipInterpolator

from carspec import CarSpec
from wheel_stage import detect_arches

inp, spec_path, out_path, dspec_path, qc_path = sys.argv[1:6]
spec = CarSpec.load(spec_path)
report = {"stage": "body_align", "input": inp, "spec": spec.path}

sc = trimesh.load(inp, force="scene")
strip = tuple(spec.label("wheel_strip_prefixes", []))
skin_names = [n for n in spec.label("body_skin_nodes",
              [spec.label("body", "carpaint")]) if n in sc.geometry]
skin_pts = np.vstack([sc.geometry[n].vertices for n in skin_names])
det = detect_arches(skin_pts, report)

L, Lsrc = spec.dim("length_m")
WB, WBsrc = spec.dim("wheelbase_m")
FO, FOsrc = spec.dim("front_overhang_m")
RO, ROsrc = spec.dim("rear_overhang_m")
if not all(v is not None for v in (L, WB, FO, RO)):
    raise SystemExit("body_align needs length_m, wheelbase_m and both "
                     "overhangs in the spec — refusing to guess proportions")

nose = float(np.percentile(skin_pts[:, 0], 99.9))
tail = float(np.percentile(skin_pts[:, 0], 0.1))
fx, rx = det["front_x"], det["rear_x"]
# keep the car's centre where it is; lay out spec proportions around it
c_now = (nose + tail) / 2
tail_t = c_now - (RO + WB + FO) / 2
rx_t = tail_t + RO
fx_t = rx_t + WB
nose_t = fx_t + FO
src_anchor = np.array([tail, rx, fx, nose])
dst_anchor = np.array([tail_t, rx_t, fx_t, nose_t])
warp = PchipInterpolator(src_anchor, dst_anchor, extrapolate=False)
slope_lo = (dst_anchor[1] - dst_anchor[0]) / (src_anchor[1] - src_anchor[0])
slope_hi = (dst_anchor[3] - dst_anchor[2]) / (src_anchor[3] - src_anchor[2])


def fmap(x):
    y = np.empty_like(x)
    inside = (x >= src_anchor[0]) & (x <= src_anchor[-1])
    y[inside] = warp(x[inside])
    lo = x < src_anchor[0]
    hi = x > src_anchor[-1]
    y[lo] = dst_anchor[0] + (x[lo] - src_anchor[0]) * slope_lo
    y[hi] = dst_anchor[-1] + (x[hi] - src_anchor[-1]) * slope_hi
    return y


report["warp"] = {
    "anchors_src": [round(float(v), 4) for v in src_anchor],
    "anchors_dst": [round(float(v), 4) for v in dst_anchor],
    "segment_scale": {
        "rear_overhang": round(float((dst_anchor[1]-dst_anchor[0]) /
                                     (src_anchor[1]-src_anchor[0])), 4),
        "wheelbase": round(float((dst_anchor[2]-dst_anchor[1]) /
                                 (src_anchor[2]-src_anchor[1])), 4),
        "front_overhang": round(float((dst_anchor[3]-dst_anchor[2]) /
                                      (src_anchor[3]-src_anchor[2])), 4)},
    "targets_source": {"L": Lsrc, "WB": WBsrc, "FO": FOsrc, "RO": ROsrc}}
print("warp segment scales:", report["warp"]["segment_scale"])

out = trimesh.Scene()
warped = 0
for node in sc.graph.nodes_geometry:
    T, gn = sc.graph[node]
    g = sc.geometry[gn]
    if not any(node.startswith(p) or gn.startswith(p) for p in strip):
        if gn not in out.geometry:
            g = g.copy()
            v = g.vertices.copy()
            v[:, 0] = fmap(v[:, 0])
            g.vertices = v
            warped += 1
            out.add_geometry(g, geom_name=gn, node_name=node, transform=T)
        else:
            out.graph.update(frame_to=node, matrix=T, geometry=gn)
    else:
        if gn not in out.geometry:
            out.add_geometry(g, geom_name=gn, node_name=node, transform=T)
        else:
            out.graph.update(frame_to=node, matrix=T, geometry=gn)
print(f"warped {warped} geometries (wheel-system nodes passed through)")
out.export(out_path, include_normals=True)

with open(out_path, "rb") as fh:
    fh.seek(12); ln, _ = struct.unpack("<II", fh.read(8)); j = json.loads(fh.read(ln))
missing = [m.get("name") for m in j["meshes"]
           if any("NORMAL" not in p["attributes"] for p in m["primitives"])]
if missing:
    raise SystemExit(f"REFUSED: NORMAL missing on {missing[:4]}")

d = dict(spec.data)
d.setdefault("expect", {})
d["expect"]["axle_x"] = {"front": round(float(fx_t), 4),
                         "rear": round(float(rx_t), 4)}
d["expect"]["tolerance_m"] = 0.05
d["expect"]["note"] = ("DERIVED by body_align: the warp maps the detected "
                       "axles to these spec-proportioned positions by "
                       "construction; the wheel stage must find them there.")
json.dump(d, open(dspec_path, "w"), indent=2)
json.dump(report, open(qc_path, "w"), indent=1)
print(f"wrote {out_path} ({os.path.getsize(out_path)} bytes), derived spec, qc")
