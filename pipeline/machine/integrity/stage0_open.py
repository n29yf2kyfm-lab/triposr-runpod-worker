#!/usr/bin/env python3
"""Independent resolution of the two Stage 0 open findings.

Reads the LOCKED source GLB directly (no Blender, no trimesh) and answers:
  1. the 928-triangle delta between the file's declared count and Blender's import
  2. which named object owns the world z-min of -0.004587 m

Both are answered from the binary, so neither depends on an importer that might
itself be the thing dropping the triangles.
"""
import json, struct, sys
import numpy as np

SRC = sys.argv[1]
buf = open(SRC, "rb").read()
assert buf[:4] == b"glTF"
off = 12
js = binc = None
while off < len(buf):
    ln, ty = struct.unpack_from("<II", buf, off)
    ch = buf[off + 8: off + 8 + ln]
    if ty == 0x4E4F534A: js = json.loads(ch)
    elif ty == 0x004E4942: binc = ch
    off += 8 + ln + ((4 - ln % 4) % 4 if ln % 4 else 0)

CT = {5120: "i1", 5121: "u1", 5122: "i2", 5123: "u2", 5125: "u4", 5126: "f4"}
NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def acc(i):
    a = js["accessors"][i]
    bv = js["bufferViews"][a["bufferView"]]
    dt = np.dtype(CT[a["componentType"]]).newbyteorder("<")
    n = NC[a["type"]]
    base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = bv.get("byteStride") or dt.itemsize * n
    if stride == dt.itemsize * n:
        arr = np.frombuffer(binc, dtype=dt, count=a["count"] * n, offset=base)
        return arr.reshape(a["count"], n) if n > 1 else arr
    out = np.empty((a["count"], n), dtype=dt)
    for k in range(a["count"]):
        out[k] = np.frombuffer(binc, dtype=dt, count=n, offset=base + k * stride)
    return out if n > 1 else out.ravel()


# ---------- 1. triangle delta ----------
tot_decl = dup_within = degen = 0
per_mesh = []
for mi, m in enumerate(js["meshes"]):
    md = ddg = 0
    for p in m["primitives"]:
        if p.get("mode", 4) != 4:
            continue
        idx = acc(p["indices"]).astype(np.int64).reshape(-1, 3)
        tot_decl += len(idx)
        bad = (idx[:, 0] == idx[:, 1]) | (idx[:, 1] == idx[:, 2]) | (idx[:, 0] == idx[:, 2])
        ddg += int(bad.sum())
        good = idx[~bad]
        s = np.sort(good, axis=1)
        # a face Blender's BMesh will refuse: same vertex TRIPLE already present
        _, cnt = np.unique(s, axis=0, return_counts=True)
        md += int((cnt - 1).sum())
    dup_within += md
    degen += ddg
    if md or ddg:
        per_mesh.append({"mesh": mi, "name": js["meshes"][mi].get("name"),
                         "duplicate_faces": md, "degenerate_faces": ddg})

# ---------- 2. world z-min owner ----------
def mat_of(node):
    if "matrix" in node:
        return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T
    M = np.eye(4)
    if "scale" in node:
        M = M @ np.diag(list(node["scale"]) + [1.0])
    if "rotation" in node:
        x, y, z, w = node["rotation"]
        R = np.array([
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), 0],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), 0],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), 0],
            [0, 0, 0, 1]], dtype=np.float64)
        M = R @ M
    if "translation" in node:
        T = np.eye(4); T[:3, 3] = node["translation"]
        M = T @ M
    return M

rows = []
def walk(ni, parent):
    n = js["nodes"][ni]
    W = parent @ mat_of(n)
    if "mesh" in n:
        zmin = 1e18; ymin_named = None
        for p in js["meshes"][n["mesh"]]["primitives"]:
            v = acc(p["attributes"]["POSITION"]).astype(np.float64)
            w = v @ W[:3, :3].T + W[:3, 3]
            zmin = min(zmin, float(w[:, 2].min()))
        rows.append((zmin, n.get("name", f"node{ni}"), ni,
                     js["meshes"][n["mesh"]].get("name")))
    for c in n.get("children", []):
        walk(c, W)

for r in js["scenes"][js.get("scene", 0)]["nodes"]:
    walk(r, np.eye(4))
rows.sort()

out = {
    "source": SRC,
    "triangle_delta": {
        "declared_total": tot_decl,
        "index_degenerate": degen,
        "duplicate_vertex_triples": dup_within,
        "predicted_blender_faces": tot_decl - degen - dup_within,
        "blender_reported": 887879,
        "per_mesh": per_mesh,
    },
    "lowest_objects": [{"world_z_min_m": z, "node": nm, "node_index": ni, "mesh": mn}
                       for z, nm, ni, mn in rows[:8]],
}
print(json.dumps(out, indent=2))
