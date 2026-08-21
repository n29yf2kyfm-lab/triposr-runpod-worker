#!/usr/bin/env python3
"""inventory.py — node/material/geometry inventory of a GLB, read from the FILE.

Reads the glTF JSON directly (never a library's reinterpretation) for node
names, material bindings and accessor presence, then trimesh for geometry.
"""
import json, struct, sys
import numpy as np, trimesh

GLB = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else None

with open(GLB, "rb") as f:
    magic, ver, total = struct.unpack("<III", f.read(12))
    js = None
    while f.tell() < total:
        ln, ty = struct.unpack("<II", f.read(8))
        d = f.read(ln)
        if ty == 0x4E4F534A: js = json.loads(d.decode("utf-8")); break
        f.seek(ln - len(d), 1)
G = js
rep = {"file": GLB, "meshes": len(G.get("meshes", [])), "materials": [m.get("name") for m in G.get("materials", [])]}

prims = []
for mi, m in enumerate(G.get("meshes", [])):
    for pi, p in enumerate(m.get("primitives", [])):
        at = p.get("attributes", {})
        prims.append({"mesh": m.get("name"), "mi": mi, "pi": pi,
                      "material": G["materials"][p["material"]].get("name") if "material" in p else None,
                      "NORMAL": "NORMAL" in at, "TEXCOORD_0": "TEXCOORD_0" in at,
                      "nverts": G["accessors"][at["POSITION"]]["count"],
                      "nfaces": G["accessors"][p["indices"]]["count"] // 3 if "indices" in p else None})
rep["primitives"] = prims
rep["normals_present"] = sum(1 for p in prims if p["NORMAL"])
rep["normals_total"] = len(prims)

sc = trimesh.load(GLB, force="scene", process=False)
geo = {}
for name, g in sc.geometry.items():
    v = g.vertices
    geo[name] = {"nv": int(len(v)), "nf": int(len(g.faces)),
                 "bbox_min": [round(float(x), 4) for x in v.min(0)],
                 "bbox_max": [round(float(x), 4) for x in v.max(0)],
                 "area": round(float(g.area), 5),
                 "watertight": bool(g.is_watertight)}
rep["geometry"] = geo
allv = np.vstack([g.vertices for g in sc.geometry.values()])
rep["scene_bbox"] = {"min": [round(float(x), 4) for x in allv.min(0)],
                     "max": [round(float(x), 4) for x in allv.max(0)],
                     "L_x": round(float(allv[:,0].max()-allv[:,0].min()), 4),
                     "H_y": round(float(allv[:,1].max()-allv[:,1].min()), 4),
                     "W_z": round(float(allv[:,2].max()-allv[:,2].min()), 4)}
rep["total_faces"] = int(sum(len(g.faces) for g in sc.geometry.values()))
print(json.dumps({k: rep[k] for k in ("file","meshes","materials","normals_present","normals_total","scene_bbox","total_faces")}, indent=1))
print("\nname                      nv       nf     area   wt  material")
mat_by_mesh = {}
for p in prims: mat_by_mesh.setdefault(p["mesh"], set()).add(p["material"])
for n, d in sorted(geo.items(), key=lambda kv: -kv[1]["nf"]):
    print(f"{n:26s} {d['nv']:8d} {d['nf']:8d} {d['area']:8.4f} {str(d['watertight'])[0]}  {sorted(mat_by_mesh.get(n,{'?'}))}")
if OUT: json.dump(rep, open(OUT, "w"), indent=1)
