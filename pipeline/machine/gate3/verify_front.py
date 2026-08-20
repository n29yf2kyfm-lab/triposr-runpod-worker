#!/usr/bin/env python3
"""verify_front.py -- Gate 3 acceptance measurements on a built car.

Measures, rather than asserts, the seven Gate 3 criteria that can be measured
from the file.  Criterion 6 (respray) needs a render and is done separately.

The coverage test is the important one: for every aperture footprint it fires
a dense (y,z) ray grid straight at the nose and records WHICH geometry the ray
hits first.  It answers three questions at once --
  * is the aperture actually filled by the constructed component (or does the
    melt still show through)?
  * is anything left OPEN (a ray that hits nothing, or hits something more than
    0.9 m back = seeing into the car through a hole)?
  * does the melt poke IN FRONT of a component anywhere?

Run: python3 verify_front.py <car.glb> <out.json>
"""
import json
import struct
import sys
import numpy as np
import trimesh

CAR, OUT = sys.argv[1], sys.argv[2]
R = {}

sc = trimesh.load(CAR, force="scene")
names = [n for n in sc.geometry.keys()]
meshes = [sc.geometry[n] for n in names]
gof = np.concatenate([[0], np.cumsum([len(m.faces) for m in meshes])])
occ = trimesh.util.concatenate(meshes)
inter = trimesh.ray.ray_pyembree.RayMeshIntersector(occ)
XMIN = float(occ.vertices[:, 0].min())

SHELL = {"carpaint", "interior", "glass", "Tyre_Rubber", "Rim_Alloy", "Lamp_Lens"}
BUILT = [n for n in names if n not in SHELL]
R["nodes"] = sorted(names)
R["built_parts"] = sorted(BUILT)
R["n_built"] = len(BUILT)

# ---- 1. per-part solidity / size -----------------------------------------
R["parts"] = {}
for n in BUILT:
    m = sc.geometry[n]
    e = m.vertices.max(0) - m.vertices.min(0)
    R["parts"][n] = {"faces": int(len(m.faces)), "watertight": bool(m.is_watertight),
                     "volume_cm3": round(float(abs(m.volume)) * 1e6, 1),
                     "extent_mm": [round(float(v) * 1000, 1) for v in e]}
R["all_watertight"] = all(v["watertight"] for v in R["parts"].values())

# ---- 2. aperture coverage -------------------------------------------------
APERTURES = {
    "headlamp_R": dict(y=(0.735, 0.855), z=(0.255, 0.700)),
    "headlamp_L": dict(y=(0.735, 0.855), z=(-0.700, -0.255)),
    "grille":     dict(y=(0.752, 0.838), z=(-0.250, 0.250)),
    "plate":      dict(y=(0.583, 0.697), z=(-0.262, 0.262)),
    "intake":     dict(y=(0.458, 0.556), z=(-0.460, 0.460)),
}
R["coverage"] = {}
for lab, a in APERTURES.items():
    ys = np.arange(a["y"][0] + 0.004, a["y"][1] - 0.004, 0.002)
    zs = np.arange(a["z"][0] + 0.004, a["z"][1] - 0.004, 0.002)
    ZZ, YY = np.meshgrid(zs, ys)
    N = ZZ.size
    org = np.stack([np.full(N, XMIN - 0.6), YY.ravel(), ZZ.ravel()], 1)
    dr = np.tile([1.0, 0.0, 0.0], (N, 1))
    loc, iray, itri = inter.intersects_location(org, dr, multiple_hits=False)
    first = np.full(N, -1, np.int64)
    dep = np.full(N, np.nan)
    first[iray] = itri
    dep[iray] = loc[:, 0] - XMIN
    gid = np.searchsorted(gof, first, side="right") - 1
    gid[first < 0] = -1
    tally = {}
    for g in np.unique(gid):
        tally[("MISS" if g < 0 else names[g])] = int((gid == g).sum())
    built_hit = sum(v for k, v in tally.items() if k in BUILT)
    open_thru = int(np.isnan(dep).sum() + np.nansum(dep > 0.9))
    R["coverage"][lab] = {
        "cells": int(N),
        "built_pct": round(100 * built_hit / N, 1),
        "see_through_pct": round(100 * open_thru / N, 2),
        "first_hit": dict(sorted(tally.items(), key=lambda kv: -kv[1])[:6]),
        "depth_mm": [round(float(np.nanmin(dep)) * 1000, 1),
                     round(float(np.nanmax(dep[dep < 0.9])) * 1000, 1)],
    }

# ---- 3. component depth (does the recess have real depth?) ----------------
for lab in ("grille", "plate", "intake"):
    a = APERTURES[lab]
    ys = np.linspace(a["y"][0] + 0.006, a["y"][1] - 0.006, 40)
    zs = np.linspace(a["z"][0] + 0.006, a["z"][1] - 0.006, 90)
    ZZ, YY = np.meshgrid(zs, ys)
    N = ZZ.size
    org = np.stack([np.full(N, XMIN - 0.6), YY.ravel(), ZZ.ravel()], 1)
    loc, iray, _ = inter.intersects_location(org, np.tile([1.0, 0, 0], (N, 1)),
                                             multiple_hits=False)
    dep = np.full(N, np.nan)
    dep[iray] = loc[:, 0] - XMIN
    d = dep[np.isfinite(dep) & (dep < 0.9)]
    R["coverage"][lab]["relief_p5_p95_mm"] = [round(float(np.percentile(d, 5)) * 1000, 1),
                                              round(float(np.percentile(d, 95)) * 1000, 1)]
    R["coverage"][lab]["relief_mm"] = round(float(np.percentile(d, 95) -
                                                  np.percentile(d, 5)) * 1000, 1)

# ---- 4. glTF structure ----------------------------------------------------
b = open(CAR, "rb").read()
jl = struct.unpack("<I", b[12:16])[0]
g = json.loads(b[20:20 + jl])
R["gltf"] = {
    "meshes": len(g["meshes"]),
    "materials": [m["name"] for m in g["materials"]],
    "nodes": [n.get("name") for n in g["nodes"]],
    "primitives_without_NORMAL": [m["name"] for m in g["meshes"]
                                  for p in m["primitives"]
                                  if "NORMAL" not in p["attributes"]],
}
R["gltf"]["normals_ok"] = not R["gltf"]["primitives_without_NORMAL"]

json.dump(R, open(OUT, "w"), indent=1)
print(json.dumps({k: R[k] for k in ("n_built", "all_watertight")}, indent=1))
for lab, c in R["coverage"].items():
    print(f"{lab:11s} built {c['built_pct']:5.1f}%  see-through {c['see_through_pct']:5.2f}%  "
          f"relief {c.get('relief_mm','-')}mm  top hits "
          f"{list(c['first_hit'].items())[:3]}")
print("normals ok:", R["gltf"]["normals_ok"], "| materials:", len(R["gltf"]["materials"]))
print("VERIFY_DONE")
