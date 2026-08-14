#!/usr/bin/env python3
"""glb.py — write a glTF 2.0 binary file by hand.

Extracted from the study artefact `pipeline/trellis/author_car.py` so the car
builder and anything else can share one writer. Nothing here is clever; the
value is that it is CORRECT about the three things that silently break GLBs:

  * every bufferView is padded to a 4-byte boundary before it is written, so an
    accessor never starts on a misaligned offset (loads in one viewer, fails in
    another);
  * the JSON chunk pads with SPACES and the BIN chunk with ZEROS, per spec;
  * POSITION accessors carry the mandatory min/max, without which some loaders
    silently cull the mesh.

Materials are written with explicit names because every gate in this repo keys
off them: glass_probe reads alphaMode/alpha by name, respray_gltf rewrites
baseColorFactor by name, and mat_audit records them.
"""
import json
import struct

import numpy as np


def vertex_normals(V, F):
    """Area-weighted smooth normals.

    Area weighting (rather than normalising each face normal first) is what
    keeps a crease crisp: the big flat panel either side of a groove dominates,
    so the groove walls stay visually distinct instead of being smeared by a
    handful of tiny transition faces.
    """
    N = np.zeros(V.shape, dtype=np.float64)
    tri = V[F]
    fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    for k in range(3):
        np.add.at(N, F[:, k], fn)
    ln = np.linalg.norm(N, axis=1, keepdims=True)
    return (N / np.maximum(ln, 1e-12)).astype(np.float32)


class GLB:
    def __init__(self, generator="expertcarcheck-authoring"):
        self.bin = bytearray()
        self.g = {
            "asset": {"version": "2.0", "generator": generator},
            "scene": 0,
            "scenes": [{"nodes": []}],
            "nodes": [],
            "meshes": [],
            "materials": [],
            "accessors": [],
            "bufferViews": [],
            "buffers": [],
        }
        self._mat_index = {}

    # ------------------------------------------------------------- internals
    def _view(self, data, target):
        while len(self.bin) % 4:
            self.bin.append(0)
        off = len(self.bin)
        self.bin += data
        self.g["bufferViews"].append(
            {"buffer": 0, "byteOffset": off, "byteLength": len(data), "target": target})
        return len(self.g["bufferViews"]) - 1

    def _acc(self, view, ctype, count, atype, mn=None, mx=None):
        a = {"bufferView": view, "componentType": ctype, "count": count, "type": atype}
        if mn is not None:
            a["min"], a["max"] = mn, mx
        self.g["accessors"].append(a)
        return len(self.g["accessors"]) - 1

    # ---------------------------------------------------------------- public
    def material(self, name, base, metal=0.0, rough=0.5, blend=False,
                 double_sided=True, emissive=None):
        """Create (or reuse) a named material and return its index."""
        if name in self._mat_index:
            return self._mat_index[name]
        m = {
            "name": name,
            "pbrMetallicRoughness": {
                "baseColorFactor": [float(c) for c in base],
                "metallicFactor": float(metal),
                "roughnessFactor": float(rough),
            },
            "doubleSided": bool(double_sided),
        }
        if blend:
            m["alphaMode"] = "BLEND"
        if emissive:
            m["emissiveFactor"] = [float(c) for c in emissive]
        self.g["materials"].append(m)
        self._mat_index[name] = len(self.g["materials"]) - 1
        return self._mat_index[name]

    def mesh(self, name, V, F, material, normals=None):
        """Add one triangle mesh as its own node.

        Separate nodes, not one merged primitive: part separation is what makes
        the material rulings enforceable (paint can never reach a tyre that is
        its own mesh with its own material).
        """
        V = np.ascontiguousarray(V, dtype=np.float32)
        F = np.ascontiguousarray(F, dtype=np.uint32)
        if len(F) == 0:
            return
        N = vertex_normals(V, F) if normals is None else np.ascontiguousarray(
            normals, dtype=np.float32)
        vp = self._view(V.tobytes(), 34962)
        vn = self._view(N.tobytes(), 34962)
        vi = self._view(F.reshape(-1).tobytes(), 34963)
        ap = self._acc(vp, 5126, len(V), "VEC3", V.min(0).tolist(), V.max(0).tolist())
        an = self._acc(vn, 5126, len(V), "VEC3")
        ai = self._acc(vi, 5125, F.size, "SCALAR")
        self.g["meshes"].append({"name": name, "primitives": [{
            "attributes": {"POSITION": ap, "NORMAL": an},
            "indices": ai, "material": material}]})
        self.g["nodes"].append({"mesh": len(self.g["meshes"]) - 1, "name": name})
        self.g["scenes"][0]["nodes"].append(len(self.g["nodes"]) - 1)

    def save(self, path):
        while len(self.bin) % 4:
            self.bin.append(0)
        self.g["buffers"] = [{"byteLength": len(self.bin)}]
        js = json.dumps(self.g, separators=(",", ":")).encode()
        js += b" " * ((4 - len(js) % 4) % 4)
        total = 12 + 8 + len(js) + 8 + len(self.bin)
        with open(path, "wb") as f:
            f.write(struct.pack("<III", 0x46546C67, 2, total))
            f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
            f.write(struct.pack("<II", len(self.bin), 0x004E4942) + bytes(self.bin))
        return total
