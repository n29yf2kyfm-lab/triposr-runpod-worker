#!/usr/bin/env python3
"""glb_io.py — read/write a GLB at the glTF level, geometry only.

WHY THIS EXISTS AND NOT trimesh
-------------------------------
The merge operator must carry Gate 6's spatial corrections onto Gate 7+8's
material-rebound car WITHOUT losing a single material property. Every route
that rebuilds a scene (trimesh export, Blender round-trip) re-authors the
material table, the node names and the primitive bindings, and every one of
those has cost this project a defect:

  * trimesh submesh exports DROP the NORMAL accessor (CLAUDE.md v7: the
    "crumpled foil" class, re-paid at least three times).
  * `trimesh.load()` without process=False recomputes vertex normals and
    zeroes every vertex whose incident faces are degenerate (Gate 6: 571).
  * a Blender round-trip renames materials and re-authors extensions
    (KHR_materials_transmission / _ior / _clearcoat are what make this car's
    glass_probe read "clear / proven").

So this module edits ONLY the binary payload behind POSITION and NORMAL
accessors and leaves the entire glTF JSON — materials, extensions, meshes,
nodes, names, indices — byte-identical unless a caller explicitly changes it.
The material table then diffs empty BY CONSTRUCTION rather than by luck.

TRAPS ENCODED HERE
  * A node transform is real data. glTF node TRS composes down the graph and
    the wheel nodes in car_rebound.glb carry real translations, so anything
    that reads raw accessor values is measuring the wheel in ITS OWN local
    frame, not on the car. `world_positions()` composes the graph; nothing
    else in this package reads a POSITION accessor directly.
  * NORMALS ARE NOT POSITIONS. A rigid rotation applies to both; a non-uniform
    scale needs the INVERSE TRANSPOSE and a renormalise. write_positions()
    refuses to write positions without being told what to do with normals.
  * accessor min/max are validated by the Khronos validator: they are rewritten
    from the data on every write, or the output ships errors.
"""
import json
import struct

import numpy as np

_CT = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
_NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


class GLB:
    def __init__(self, path):
        with open(path, "rb") as fh:
            raw = fh.read()
        magic, ver, _ = struct.unpack("<III", raw[:12])
        assert magic == 0x46546C67, "not a GLB"
        assert ver == 2, f"glTF version {ver}"
        off, self.json_chunk, self.bin = 12, None, bytearray()
        while off < len(raw):
            clen, ctype = struct.unpack("<II", raw[off:off + 8])
            body = raw[off + 8: off + 8 + clen]
            if ctype == 0x4E4F534A:
                self.json_chunk = body
            elif ctype == 0x004E4942:
                self.bin = bytearray(body)
            off += 8 + clen + ((4 - clen % 4) % 4 if clen % 4 else 0)
        self.g = json.loads(self.json_chunk.decode("utf-8"))
        self.path = path

    # ---------------------------------------------------------------- read
    def accessor(self, idx):
        """Return an (n, ncomp) float/int array for accessor idx."""
        a = self.g["accessors"][idx]
        n, nc = a["count"], _NC[a["type"]]
        fmt = _CT[a["componentType"]]
        isz = struct.calcsize(fmt)
        bv = self.g["bufferViews"][a["bufferView"]]
        base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        stride = bv.get("byteStride") or isz * nc
        if stride == isz * nc:
            buf = np.frombuffer(self.bin, dtype=np.dtype("<" + fmt),
                                count=n * nc, offset=base)
            return buf.reshape(n, nc)
        out = np.empty((n, nc), dtype=np.dtype("<" + fmt))
        for i in range(n):
            o = base + i * stride
            out[i] = np.frombuffer(self.bin, dtype=np.dtype("<" + fmt),
                                   count=nc, offset=o)
        return out

    def node_matrix(self, node):
        if "matrix" in node:
            return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T
        M = np.eye(4)
        if "rotation" in node:
            x, y, z, w = node["rotation"]
            M[:3, :3] = np.array([
                [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        if "scale" in node:
            M[:3, :3] = M[:3, :3] @ np.diag(node["scale"])
        if "translation" in node:
            M[:3, 3] = node["translation"]
        return M

    def graph(self):
        """[(node_index, name, world_matrix, mesh_index)] for every mesh node."""
        out, seen = [], set()
        scene = self.g.get("scenes", [{}])[self.g.get("scene", 0)]
        stack = [(r, np.eye(4)) for r in scene.get("nodes", [])]
        while stack:
            ni, P = stack.pop()
            if ni in seen:
                continue
            seen.add(ni)
            nd = self.g["nodes"][ni]
            W = P @ self.node_matrix(nd)
            if "mesh" in nd:
                out.append((ni, nd.get("name", f"node{ni}"), W, nd["mesh"]))
            for c in nd.get("children", []):
                stack.append((c, W))
        return out

    def prims(self):
        """[(node_name, world_matrix, mesh_idx, prim_idx, prim_dict)]."""
        out = []
        for ni, name, W, mi in self.graph():
            for pi, p in enumerate(self.g["meshes"][mi].get("primitives", [])):
                out.append((name, W, mi, pi, p))
        return out

    def world_positions(self, W, prim):
        v = self.accessor(prim["attributes"]["POSITION"]).astype(np.float64)
        return v @ W[:3, :3].T + W[:3, 3]

    def faces(self, prim):
        return self.accessor(prim["indices"]).astype(np.int64).reshape(-1, 3)

    # --------------------------------------------------------------- write
    def write_accessor(self, idx, data):
        """Overwrite accessor idx in place; rewrite its min/max. float32 only."""
        a = self.g["accessors"][idx]
        assert a["componentType"] == 5126, "only float accessors are writable"
        n, nc = a["count"], _NC[a["type"]]
        assert data.shape == (n, nc), f"shape {data.shape} != ({n},{nc})"
        bv = self.g["bufferViews"][a["bufferView"]]
        base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        stride = bv.get("byteStride") or 4 * nc
        d = np.ascontiguousarray(data, dtype="<f4")
        if stride == 4 * nc:
            self.bin[base:base + d.nbytes] = d.tobytes()
        else:
            raw = d.tobytes()
            for i in range(n):
                o = base + i * stride
                self.bin[o:o + 4 * nc] = raw[i * 4 * nc:(i + 1) * 4 * nc]
        a["min"] = [float(x) for x in d.min(axis=0)]
        a["max"] = [float(x) for x in d.max(axis=0)]

    def save(self, path):
        js = json.dumps(self.g, separators=(",", ":")).encode("utf-8")
        js += b" " * ((4 - len(js) % 4) % 4)
        bn = bytes(self.bin)
        bn += b"\0" * ((4 - len(bn) % 4) % 4)
        total = 12 + 8 + len(js) + 8 + len(bn)
        with open(path, "wb") as fh:
            fh.write(struct.pack("<III", 0x46546C67, 2, total))
            fh.write(struct.pack("<II", len(js), 0x4E4F534A))
            fh.write(js)
            fh.write(struct.pack("<II", len(bn), 0x004E4942))
            fh.write(bn)
        return path


def material_table(glb):
    """Everything a respray or a gate can see. Used for the before/after diff."""
    t = {}
    for i, m in enumerate(glb.g.get("materials", [])):
        t[m.get("name", f"mat{i}")] = json.dumps(m, sort_keys=True)
    return t


def binding_table(glb):
    """node name -> [(mesh, prim, material name, index count, vertex count)]."""
    mats = [m.get("name", f"mat{i}") for i, m in enumerate(glb.g.get("materials", []))]
    out = {}
    for name, W, mi, pi, p in glb.prims():
        mat = mats[p["material"]] if "material" in p else None
        out.setdefault(name, []).append((
            mi, pi, mat,
            glb.g["accessors"][p["indices"]]["count"],
            glb.g["accessors"][p["attributes"]["POSITION"]]["count"],
            sorted(p["attributes"].keys())))
    return out
