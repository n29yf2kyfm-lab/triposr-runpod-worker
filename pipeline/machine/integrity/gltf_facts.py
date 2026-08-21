#!/usr/bin/env python3
"""gltf_facts.py — read the glTF JSON + index accessors of a GLB, no Blender.

Answers two Stage-0 open findings from the FILE side, so that the Blender-side
numbers have something independent to be compared against:

  * the file's per-primitive triangle count, and how many of those triangles are
    DEGENERATE by index (two or three indices equal).  A degenerate-by-index
    triangle is dropped by Blender's importer, so this is the first candidate
    mechanism for the 888,807 -> 887,879 delta.
  * every node's local transform, its accumulated world transform, the world
    bbox of the primitives it draws, and therefore which NODE holds the lowest
    world Y (glTF is Y-up; Blender's importer maps it to Z).

Deliberately does NOT use trimesh: trimesh drops KHR material extensions on any
round-trip and recomputes normals, and this stage must report what the FILE
says, not what a library reconstructs.
"""
import json
import struct
import sys

COMP = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2),
        5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4,
         "MAT2": 4, "MAT3": 9, "MAT4": 16}


def load_glb(path):
    with open(path, "rb") as fh:
        magic, ver, _ = struct.unpack("<III", fh.read(12))
        assert magic == 0x46546C67, "not a GLB"
        js = bin_ = None
        while True:
            hdr = fh.read(8)
            if len(hdr) < 8:
                break
            ln, ty = struct.unpack("<II", hdr)
            data = fh.read(ln)
            if ty == 0x4E4F534A:
                js = json.loads(data)
            elif ty == 0x004E4942:
                bin_ = data
    return js, bin_


def read_accessor(g, bin_, idx):
    a = g["accessors"][idx]
    fmt, sz = COMP[a["componentType"]]
    n = NCOMP[a["type"]]
    count = a["count"]
    if "bufferView" not in a:
        return [tuple([0] * n)] * count
    bv = g["bufferViews"][a["bufferView"]]
    base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = bv.get("byteStride") or sz * n
    out = []
    for i in range(count):
        off = base + i * stride
        out.append(struct.unpack_from("<" + fmt * n, bin_, off))
    return out


def mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)]
            for i in range(4)]


def trs_to_mat(node):
    if "matrix" in node:
        m = node["matrix"]  # column-major
        return [[m[0], m[4], m[8], m[12]],
                [m[1], m[5], m[9], m[13]],
                [m[2], m[6], m[10], m[14]],
                [m[3], m[7], m[11], m[15]]]
    t = node.get("translation", [0, 0, 0])
    r = node.get("rotation", [0, 0, 0, 1])
    s = node.get("scale", [1, 1, 1])
    x, y, z, w = r
    rm = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
          [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
          [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    out = [[rm[i][j] * s[j] for j in range(3)] + [t[i]] for i in range(3)]
    out.append([0, 0, 0, 1])
    return out


def det3(m):
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


def xf(m, p):
    return tuple(m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2] + m[i][3]
                 for i in range(3))


def main(path, outpath):
    g, bin_ = load_glb(path)
    nodes = g["nodes"]
    parent = {}
    for i, n in enumerate(nodes):
        for c in n.get("children", []):
            parent[c] = i

    world = {}

    def wmat(i):
        if i in world:
            return world[i]
        m = trs_to_mat(nodes[i])
        if i in parent:
            m = mat_mul(wmat(parent[i]), m)
        world[i] = m
        return m

    mats = g.get("materials", [])
    prim_rows = []
    tri_file = 0
    tri_nondegen = 0
    dup_total = 0
    degen_by_prim = {}
    dup_by_prim = {}
    dup_by_mesh = {}

    for mi, mesh in enumerate(g["meshes"]):
        for pi, p in enumerate(mesh["primitives"]):
            mode = p.get("mode", 4)
            pos = g["accessors"][p["attributes"]["POSITION"]]
            if "indices" in p:
                idx = [v[0] for v in read_accessor(g, bin_, p["indices"])]
                ntri = len(idx) // 3
                dg = 0
                # DUPLICATE VERTEX-TRIPLE = a second face on a triple that
                # already carries one. BMesh refuses to create it, so Blender's
                # importer silently DROPS it and the count can never be seen
                # from the imported scene -- it has to be measured HERE.
                # These ship to the viewer and z-fight; the Khronos validator
                # does not flag them (it flagged 1 of the 928 on this car).
                seen = set()
                dup = 0
                for t in range(ntri):
                    a, b, c = idx[3 * t], idx[3 * t + 1], idx[3 * t + 2]
                    if a == b or b == c or a == c:
                        dg += 1
                        continue
                    k = tuple(sorted((a, b, c)))
                    if k in seen:
                        dup += 1
                    else:
                        seen.add(k)
                tri = ntri
            else:
                tri = pos["count"] // 3
                dg = 0
                dup = 0
            tri_file += tri
            tri_nondegen += tri - dg
            dup_total += dup
            if dg:
                degen_by_prim[f"meshes/{mi}/primitives/{pi}"] = dg
            if dup:
                dup_by_prim[f"meshes/{mi}/primitives/{pi}"] = dup
            dup_by_mesh[mesh.get("name")] = dup_by_mesh.get(mesh.get("name"), 0) + dup
            prim_rows.append({
                "mesh": mi, "mesh_name": mesh.get("name"), "prim": pi,
                "mode": mode, "material": p.get("material"),
                "material_name": (mats[p["material"]].get("name")
                                  if p.get("material") is not None
                                  and p["material"] < len(mats) else None),
                "triangles": tri, "degenerate_by_index": dg,
                "duplicate_vertex_triples": dup,
                "vertices": pos["count"],
                "has_NORMAL": "NORMAL" in p["attributes"],
                "has_TEXCOORD_0": "TEXCOORD_0" in p["attributes"],
                "pos_min": pos.get("min"), "pos_max": pos.get("max"),
            })

    node_rows = []
    for i, n in enumerate(nodes):
        m = wmat(i)
        row = {"node": i, "name": n.get("name"), "mesh": n.get("mesh"),
               "parent": parent.get(i), "det3": round(det3(m), 9),
               "local_is_identity": ("matrix" not in n
                                     and "translation" not in n
                                     and "rotation" not in n
                                     and "scale" not in n),
               "world_matrix": [[round(v, 9) for v in r] for r in m]}
        if n.get("mesh") is not None:
            lo = [1e30] * 3
            hi = [-1e30] * 3
            for p in g["meshes"][n["mesh"]]["primitives"]:
                a = g["accessors"][p["attributes"]["POSITION"]]
                if "min" not in a:
                    continue
                for cx in (a["min"][0], a["max"][0]):
                    for cy in (a["min"][1], a["max"][1]):
                        for cz in (a["min"][2], a["max"][2]):
                            w = xf(m, (cx, cy, cz))
                            for k in range(3):
                                lo[k] = min(lo[k], w[k])
                                hi[k] = max(hi[k], w[k])
            row["world_bbox_min"] = [round(v, 6) for v in lo]
            row["world_bbox_max"] = [round(v, 6) for v in hi]
        node_rows.append(row)

    out = {
        "file": path,
        "triangles_declared_total": tri_file,
        "triangles_nondegenerate_by_index": tri_nondegen,
        "degenerate_by_index_total": tri_file - tri_nondegen,
        "degenerate_by_primitive": degen_by_prim,
        "duplicate_vertex_triples_total": dup_total,
        "duplicate_vertex_triples_by_primitive": dup_by_prim,
        "duplicate_vertex_triples_by_mesh": {k: v for k, v in sorted(
            dup_by_mesh.items(), key=lambda kv: -kv[1]) if v},
        "importable_triangles": tri_nondegen - dup_total,
        "primitive_modes": sorted({r["mode"] for r in prim_rows}),
        "primitives": prim_rows,
        "nodes": node_rows,
    }
    json.dump(out, open(outpath, "w"), indent=1)
    print("triangles declared      :", tri_file)
    print("degenerate BY INDEX     :", tri_file - tri_nondegen)
    print("non-degenerate          :", tri_nondegen)
    print("duplicate vertex-triples:", dup_total)
    print("importable (file - degen - dup):", tri_nondegen - dup_total)
    print("primitive modes present :", out["primitive_modes"])
    print("degenerate per primitive:", degen_by_prim)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
