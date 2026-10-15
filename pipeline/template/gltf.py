#!/usr/bin/env python3
"""gltf.py — read and write a plain (uncompressed) GLB with numpy.

Just enough of glTF 2.0 for the template machine: accessors in and out,
world matrices, and a writer that appends new buffer data while keeping
every material, texture, image and extension of the source untouched.
Masters are decoded once (tools/decode.mjs) so this never meets meshopt or
quantization.
"""
import json
import struct

import numpy as np

CTYPE = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


class GLTF:
    def __init__(self, path):
        b = open(path, "rb").read()
        magic, ver, total = struct.unpack("<III", b[:12])
        assert magic == 0x46546C67, "not a GLB"
        off = 12
        self.json, self.bin = None, b""
        while off < total:
            ln, typ = struct.unpack("<II", b[off:off + 8])
            chunk = b[off + 8:off + 8 + ln]
            if typ == 0x4E4F534A:
                self.json = json.loads(chunk)
            elif typ == 0x004E4942:
                self.bin = bytes(chunk)
            off += 8 + ln
        self.j = self.json
        self.extra = bytearray()          # appended after the original BIN

    # ── reading ──────────────────────────────────────────────────────────
    def accessor(self, i):
        a = self.j["accessors"][i]
        n, comp = a["count"], NCOMP[a["type"]]
        dt = np.dtype(CTYPE[a["componentType"]])
        if "bufferView" not in a:
            return np.zeros((n, comp), dt)
        bv = self.j["bufferViews"][a["bufferView"]]
        start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        stride = bv.get("byteStride", 0) or comp * dt.itemsize
        arr = np.ndarray((n, comp), dtype=dt, buffer=self.bin, offset=start, strides=(stride, dt.itemsize))
        out = arr.astype(np.float64) if dt == np.float32 else arr.copy()
        if a.get("normalized"):
            out = out.astype(np.float64) / np.iinfo(dt).max
        return out

    def local_matrix(self, n):
        if "matrix" in n:
            return np.array(n["matrix"], dtype=np.float64).reshape(4, 4).T
        T = np.eye(4)
        T[:3, 3] = n.get("translation", [0, 0, 0])
        x, y, z, w = n.get("rotation", [0, 0, 0, 1])
        R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                      [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                      [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        S = np.diag(list(n.get("scale", [1, 1, 1])) + [1])
        M = np.eye(4)
        M[:3, :3] = R
        return T @ M @ S

    def world_matrices(self):
        W = {}
        parent = {}
        for i, n in enumerate(self.j["nodes"]):
            for c in n.get("children", []):
                parent[c] = i

        def get(i):
            if i in W:
                return W[i]
            M = self.local_matrix(self.j["nodes"][i])
            if i in parent:
                M = get(parent[i]) @ M
            W[i] = M
            return M
        for i in range(len(self.j["nodes"])):
            get(i)
        return W, parent

    # ── writing ──────────────────────────────────────────────────────────
    def add_accessor(self, arr, ctype=5126, atype=None, target=None, minmax=False):
        arr = np.ascontiguousarray(arr)
        if arr.ndim == 1:
            arr = arr[:, None]
        comp = arr.shape[1]
        atype = atype or {1: "SCALAR", 2: "VEC2", 3: "VEC3", 4: "VEC4"}[comp]
        data = arr.astype(CTYPE[ctype]).tobytes()
        while (len(self.bin) + len(self.extra)) % 4:
            self.extra += b"\0"
        bv = {"buffer": 0, "byteOffset": len(self.bin) + len(self.extra), "byteLength": len(data)}
        if target:
            bv["target"] = target
        self.extra += data
        self.j["bufferViews"].append(bv)
        acc = {"bufferView": len(self.j["bufferViews"]) - 1, "componentType": ctype, "count": int(arr.shape[0]),
               "type": atype}
        if minmax:
            acc["min"] = [float(v) for v in arr.min(0)]
            acc["max"] = [float(v) for v in arr.max(0)]
        self.j["accessors"].append(acc)
        return len(self.j["accessors"]) - 1

    def save(self, path, compact=True):
        """Write the GLB. With `compact`, buffer views no accessor or image
        uses any more are dropped, so a morph does not ship the master's
        original positions alongside its own."""
        if compact:
            self._compact()
        binary = self.bin + bytes(self.extra)
        while len(binary) % 4:
            binary += b"\0"
        self.j["buffers"] = [{"byteLength": len(binary)}]
        js = json.dumps(self.j, separators=(",", ":")).encode()
        while len(js) % 4:
            js += b" "
        out = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(binary))
        out += struct.pack("<II", len(js), 0x4E4F534A) + js
        out += struct.pack("<II", len(binary), 0x004E4942) + binary
        open(path, "wb").write(out)
        return len(out)

    def _compact(self):
        j = self.j
        # accessors still referenced by a mesh, an animation or a skin
        live = set()
        for m in j.get("meshes", []):
            for p in m["primitives"]:
                live.update(p["attributes"].values())
                if "indices" in p:
                    live.add(p["indices"])
                for t in p.get("targets", []):
                    live.update(t.values())
        for an in j.get("animations", []):
            for s in an["samplers"]:
                live.update((s["input"], s["output"]))
        for sk in j.get("skins", []):
            if "inverseBindMatrices" in sk:
                live.add(sk["inverseBindMatrices"])
        amap = {}
        accs = []
        for i, a in enumerate(j["accessors"]):
            if i in live:
                amap[i] = len(accs)
                accs.append(a)
        j["accessors"] = accs
        for m in j.get("meshes", []):
            for p in m["primitives"]:
                p["attributes"] = {k: amap[v] for k, v in p["attributes"].items()}
                if "indices" in p:
                    p["indices"] = amap[p["indices"]]
                p["targets"] = [{k: amap[v] for k, v in t.items()} for t in p.get("targets", [])] or None
                if p["targets"] is None:
                    del p["targets"]
        for an in j.get("animations", []):
            for s in an["samplers"]:
                s["input"], s["output"] = amap[s["input"]], amap[s["output"]]
        for sk in j.get("skins", []):
            if "inverseBindMatrices" in sk:
                sk["inverseBindMatrices"] = amap[sk["inverseBindMatrices"]]
        # Rebuild the binary ACCESSOR by accessor: a writer such as
        # glTF-Transform packs many accessors into one buffer view, so keeping
        # whole views would carry the master's replaced positions along as
        # dead bytes (12 MB on the Golf).
        whole = self.bin + bytes(self.extra)
        new_bin = bytearray()
        views = []

        def put(chunk, target=None):
            while len(new_bin) % 4:
                new_bin.extend(b"\0")
            v = {"buffer": 0, "byteOffset": len(new_bin), "byteLength": len(chunk)}
            if target:
                v["target"] = target
            new_bin.extend(chunk)
            views.append(v)
            return len(views) - 1

        old_views = j["bufferViews"]
        for a in j["accessors"]:
            if "bufferView" not in a:
                continue
            bv = old_views[a["bufferView"]]
            comp = NCOMP[a["type"]]
            dt = np.dtype(CTYPE[a["componentType"]])
            esize = comp * dt.itemsize
            start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
            stride = bv.get("byteStride", 0) or esize
            arr = np.ndarray((a["count"], comp), dtype=dt, buffer=whole, offset=start, strides=(stride, dt.itemsize))
            a["bufferView"] = put(np.ascontiguousarray(arr).tobytes(), bv.get("target"))
            a.pop("byteOffset", None)
        for im in j.get("images", []):
            if "bufferView" in im:
                bv = old_views[im["bufferView"]]
                s = bv.get("byteOffset", 0)
                im["bufferView"] = put(whole[s:s + bv["byteLength"]])
        j["bufferViews"] = views
        self.bin, self.extra = bytes(new_bin), bytearray()
