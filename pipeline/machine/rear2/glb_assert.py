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
# ADAPTATION 2026-08-21 (six-gate merge): an optional BASELINE file.
#
# Absolute zeros were the right bar for this gate run alone, where the source
# rear_v3.glb measured zeroN=0 nonunit=0 loose=0.  In the merged pipeline the
# input already carries defects THIS STAGE DID NOT CREATE -- the Gate 7+8 base
# ships 4 zero-area faces in Wheel_FR_Disc and 19 in Interior (the validator's
# two ACCESSOR_INDEX_TRIANGLE_DEGENERATE infos), and Gate 3 v7's strip leaves
# 27,028 unreferenced vertices in Bumper_Front_Paint because it deletes faces
# without repacking the vertex array.  Refusing on those is refusing on someone
# else's file.  With a baseline the rule becomes CLAUDE.md's own: run the check
# on the OUTPUT and DIFF IT AGAINST THE INPUT.  Missing NORMAL, zero-length and
# non-unit normals stay ABSOLUTE -- they are validator ERRORS and no baseline
# excuses them.
P = sys.argv[1]
BASE = sys.argv[2] if len(sys.argv) > 2 else None


def scan(path):
    f = open(path, "rb"); struct.unpack("<III", f.read(12))
    ln, ty = struct.unpack("<II", f.read(8)); G = json.loads(f.read(ln).decode())
    bl, bt = struct.unpack("<II", f.read(8)); BIN = f.read(bl)

    def acc(i):
        a = G["accessors"][i]; bv = G["bufferViews"][a["bufferView"]]
        n = {5126: 'f4', 5123: 'u2', 5125: 'u4', 5121: 'u1'}[a["componentType"]]
        k = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}[a["type"]]
        off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        return np.frombuffer(BIN, dtype=n, count=a["count"] * k,
                             offset=off).reshape(a["count"], k)

    tz = tn = tl = td = 0; nomap = []
    for m in G["meshes"]:
        for p in m["primitives"]:
            at = p["attributes"]
            if "NORMAL" not in at: nomap.append(m["name"]); continue
            V = acc(at["POSITION"]); N = acc(at["NORMAL"])
            F = acc(p["indices"]).reshape(-1, 3)
            L = np.linalg.norm(N, axis=1)
            tz += int((L < 1e-6).sum()); tn += int((np.abs(L - 1) > 1e-3).sum())
            tl += int(len(V) - len(np.unique(F)))
            tri = V[F].astype(np.float64)
            ar = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0],
                                               tri[:, 2] - tri[:, 0]), axis=1)
            td += int((ar < 1e-12).sum())
    return dict(prims=sum(len(m["primitives"]) for m in G["meshes"]),
                nomap=nomap, zeroN=tz, nonunit=tn, loose=tl, zeroarea=td)


a = scan(P)
print(f"primitives={a['prims']} missing_NORMAL={a['nomap'] or 'none'} "
      f"zero_normals={a['zeroN']} non_unit={a['nonunit']} "
      f"loose_verts={a['loose']} zero_area_faces={a['zeroarea']}")
hard = bool(a["nomap"]) or a["zeroN"] or a["nonunit"]
if BASE:
    b = scan(BASE)
    print(f"BASELINE {BASE}: loose_verts={b['loose']} zero_area_faces={b['zeroarea']}")
    soft = (a["loose"] > b["loose"]) or (a["zeroarea"] > b["zeroarea"])
    if soft:
        print(f"NEW loose_verts +{a['loose']-b['loose']} "
              f"zero_area +{a['zeroarea']-b['zeroarea']}")
else:
    soft = bool(a["loose"] or a["zeroarea"])
if not hard and not soft:
    print("GLB_ASSERT_OK")
else:
    sys.exit(1)
