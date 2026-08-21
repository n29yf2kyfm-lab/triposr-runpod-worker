#!/usr/bin/env python3
"""glb_assert.py — re-read a WRITTEN glb and assert it is clean.

Reads the file back from disk, never the scene in memory: on this programme
the EXPORT is the step that has silently dropped NORMAL accessors and left
orphan vertices. Prints GLB_ASSERT_OK only when every primitive has NORMAL,
every normal is unit length, no vertex is unreferenced and no face is
zero-area.
"""
import json, struct, sys
import numpy as np
P = sys.argv[1]
f = open(P, "rb"); struct.unpack("<III", f.read(12))
ln, ty = struct.unpack("<II", f.read(8)); G = json.loads(f.read(ln).decode())
bl, bt = struct.unpack("<II", f.read(8)); BIN = f.read(bl)


def acc(i):
    a = G["accessors"][i]; bv = G["bufferViews"][a["bufferView"]]
    n = {5126: 'f4', 5123: 'u2', 5125: 'u4', 5121: 'u1'}[a["componentType"]]
    k = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}[a["type"]]
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    return np.frombuffer(BIN, dtype=n, count=a["count"] * k, offset=off).reshape(a["count"], k)


tz = tn = tl = td = 0; nomap = []
for m in G["meshes"]:
    for p in m["primitives"]:
        at = p["attributes"]
        if "NORMAL" not in at: nomap.append(m["name"]); continue
        V = acc(at["POSITION"]); N = acc(at["NORMAL"]); F = acc(p["indices"]).reshape(-1, 3)
        L = np.linalg.norm(N, axis=1)
        tz += int((L < 1e-6).sum()); tn += int((np.abs(L - 1) > 1e-3).sum())
        tl += int(len(V) - len(np.unique(F)))
        tri = V[F]
        ar = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
        td += int((ar < 1e-12).sum())
print(f"primitives={sum(len(m['primitives']) for m in G['meshes'])} "
      f"missing_NORMAL={nomap or 'none'} zero_normals={tz} non_unit={tn} "
      f"loose_verts={tl} zero_area_faces={td}")
if not nomap and tz == 0 and tn == 0 and tl == 0 and td == 0:
    print("GLB_ASSERT_OK")
else:
    sys.exit(1)
