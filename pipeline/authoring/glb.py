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
    def group(self, name, parent=None):
        """An empty node used purely to give the file a readable part tree.

        The owner's spec (2026-08-14) is a NAMED hierarchy — body/hood,
        wheels/wheel_FL and so on — because a GLB whose outline reads like a
        parts list is inspectable, repairable and re-materialable per panel.
        """
        self.g["nodes"].append({"name": name})
        idx = len(self.g["nodes"]) - 1
        if parent is None:
            self.g["scenes"][0]["nodes"].append(idx)
        else:
            self.g["nodes"][parent].setdefault("children", []).append(idx)
        return idx

    def texture(self, png_bytes):
        """Embed a PNG in the BIN chunk and return a texture index.

        Textures ride the same buffer as the geometry — images carry a
        bufferView + mimeType instead of a URI, which keeps the GLB
        self-contained (and is exactly the layout the ranged-read probes in
        pipeline/ingest already know how to walk).
        """
        view = self._view(png_bytes, None)
        # bufferViews for images must not carry a target
        del self.g["bufferViews"][view]["target"]
        self.g.setdefault("images", []).append(
            {"bufferView": view, "mimeType": "image/png"})
        self.g.setdefault("samplers", [])
        if not self.g["samplers"]:
            self.g["samplers"].append({"magFilter": 9729, "minFilter": 9987,
                                       "wrapS": 10497, "wrapT": 10497})
        self.g.setdefault("textures", []).append(
            {"source": len(self.g["images"]) - 1, "sampler": 0})
        return len(self.g["textures"]) - 1

    def material(self, name, base, metal=0.0, rough=0.5, blend=False,
                 double_sided=True, emissive=None, base_tex=None,
                 normal_tex=None, normal_scale=1.0):
        """Create (or reuse) a named material and return its index.

        base_tex / normal_tex are texture indices from texture(). The
        baseColorFactor stays authoritative for resprays: glTF multiplies
        factor x texture, so respray_gltf's factor rewrite tints the textured
        panels exactly as it tints flat ones.
        """
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
        if base_tex is not None:
            m["pbrMetallicRoughness"]["baseColorTexture"] = {"index": base_tex}
        if normal_tex is not None:
            m["normalTexture"] = {"index": normal_tex,
                                  "scale": float(normal_scale)}
        if blend:
            m["alphaMode"] = "BLEND"
        if emissive:
            m["emissiveFactor"] = [float(c) for c in emissive]
        self.g["materials"].append(m)
        self._mat_index[name] = len(self.g["materials"]) - 1
        return self._mat_index[name]

    def mesh(self, name, V, F, material, normals=None, parent=None, uvs=None):
        """Add one triangle mesh as its own node, optionally under a group.

        Separate nodes, not one merged primitive: part separation is what makes
        the material rulings enforceable (paint can never reach a tyre that is
        its own mesh with its own material). `uvs` is an (n,2) array in [0,1];
        required on any mesh whose material carries a texture.
        """
        V = np.ascontiguousarray(V, dtype=np.float32)
        F = np.ascontiguousarray(F, dtype=np.uint32)
        if len(F) == 0:
            return None
        N = vertex_normals(V, F) if normals is None else np.ascontiguousarray(
            normals, dtype=np.float32)
        vp = self._view(V.tobytes(), 34962)
        vn = self._view(N.tobytes(), 34962)
        vi = self._view(F.reshape(-1).tobytes(), 34963)
        ap = self._acc(vp, 5126, len(V), "VEC3", V.min(0).tolist(), V.max(0).tolist())
        an = self._acc(vn, 5126, len(V), "VEC3")
        ai = self._acc(vi, 5125, F.size, "SCALAR")
        attrs = {"POSITION": ap, "NORMAL": an}
        if uvs is not None:
            U = np.ascontiguousarray(uvs, dtype=np.float32)
            assert len(U) == len(V), f"{name}: {len(U)} uvs for {len(V)} verts"
            vt = self._view(U.tobytes(), 34962)
            attrs["TEXCOORD_0"] = self._acc(vt, 5126, len(U), "VEC2")
        self.g["meshes"].append({"name": name, "primitives": [{
            "attributes": attrs,
            "indices": ai, "material": material}]})
        self.g["nodes"].append({"mesh": len(self.g["meshes"]) - 1, "name": name})
        idx = len(self.g["nodes"]) - 1
        if parent is None:
            self.g["scenes"][0]["nodes"].append(idx)
        else:
            self.g["nodes"][parent].setdefault("children", []).append(idx)
        return idx

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
