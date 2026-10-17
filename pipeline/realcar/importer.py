#!/usr/bin/env python3
"""importer.py — a model bought or made outside, turned into the plain GLB
the machine builds from.

    python3 pipeline/realcar/importer.py CAR.obj|CAR.gltf|CAR.glb OUT.glb

GLB passes through. glTF (with its .bin and textures beside it) is packed
into one GLB by the node tools (decode.mjs). OBJ (with its .mtl and
textures) is read here:

  * every `o` / `g` name becomes its own node, and every material its own
    primitive: the rigger finds doors, wheels and glass by those names, so
    a shop model's 'Door_FL' or 'Wheel_RR' still counts;
  * polygons are split into triangles, negative indices allowed;
  * the .mtl's colour (Kd), transparency (d / Tr), shininess (Ns, as
    roughness) and colour map (map_Kd, and map_d for cut-outs) become glTF
    materials; textures are packed into the file (TGA and BMP as PNG);
  * a group without normals gets smooth ones.

Units and axes are left as they are: the rigger finds the wheels, the up
axis and the scale itself.
"""
import io
import json
import math
import os
import struct
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


# ── a minimal GLB writer ────────────────────────────────────────────────────
class GLB:
    def __init__(self):
        self.bin = bytearray()
        self.j = {"asset": {"version": "2.0", "generator": "ExpertCarCheck GLB machine importer"},
                  "buffers": [{}], "bufferViews": [], "accessors": [], "meshes": [], "nodes": [],
                  "materials": [], "textures": [], "images": [], "samplers": [{"wrapS": 10497, "wrapT": 10497}],
                  "scenes": [{"nodes": []}], "scene": 0}

    def view(self, data, target=None):
        while len(self.bin) % 4:
            self.bin.append(0)
        v = {"buffer": 0, "byteOffset": len(self.bin), "byteLength": len(data)}
        if target:
            v["target"] = target
        self.bin += data
        self.j["bufferViews"].append(v)
        return len(self.j["bufferViews"]) - 1

    def accessor(self, arr, ctype, atype, target=None, minmax=False):
        arr = np.ascontiguousarray(arr)
        a = {"bufferView": self.view(arr.tobytes(), target), "componentType": ctype,
             "count": int(arr.shape[0]), "type": atype}
        if minmax:
            a["min"], a["max"] = [float(x) for x in arr.min(0)], [float(x) for x in arr.max(0)]
        self.j["accessors"].append(a)
        return len(self.j["accessors"]) - 1

    def image(self, data, mime):
        self.j["images"].append({"bufferView": self.view(data), "mimeType": mime})
        self.j["textures"].append({"source": len(self.j["images"]) - 1, "sampler": 0})
        return len(self.j["textures"]) - 1

    def save(self, path):
        for k in ("textures", "images", "materials"):
            if not self.j[k]:
                del self.j[k]
        if "textures" not in self.j:
            self.j.pop("samplers", None)
        self.j["buffers"][0]["byteLength"] = len(self.bin)
        js = json.dumps(self.j, separators=(",", ":")).encode()
        js += b" " * (-len(js) % 4)
        bn = bytes(self.bin) + b"\0" * (-len(self.bin) % 4)
        with open(path, "wb") as f:
            f.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bn)))
            f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
            f.write(struct.pack("<II", len(bn), 0x004E4942) + bn)


# ── OBJ ─────────────────────────────────────────────────────────────────────
def _find(folder, name):
    """A texture the .mtl names, also when its path is from another machine
    or its case differs (C:\\Users\\...\\Body.PNG next to the .obj as body.png)."""
    name = name.replace("\\", "/")
    for p in (os.path.join(folder, name), os.path.join(folder, os.path.basename(name))):
        if os.path.exists(p):
            return p
    want = os.path.basename(name).lower()
    for root, _, files in os.walk(folder):
        for f in files:
            if f.lower() == want:
                return os.path.join(root, f)
    return None


def read_mtl(path):
    mats, cur = {}, None
    folder = os.path.dirname(path)
    for line in open(path, errors="replace"):
        t = line.strip().split()
        if not t or t[0].startswith("#"):
            continue
        k = t[0].lower()
        if k == "newmtl":
            cur = mats.setdefault(" ".join(t[1:]), {})
        elif cur is None:
            continue
        elif k in ("kd", "ke") and len(t) >= 4:
            cur[k] = [float(x) for x in t[1:4]]
        elif k == "d":
            cur["d"] = float(t[-1])
        elif k == "tr":
            cur["d"] = 1 - float(t[-1])
        elif k == "ns":
            cur["ns"] = float(t[1])
        elif k == "pm":
            cur["pm"] = float(t[1])
        elif k in ("map_kd", "map_d", "map_bump", "bump", "norm"):
            f = _find(folder, t[-1])
            if f:
                cur[k] = f
    return mats


def _png_or_jpg(path):
    ext = os.path.splitext(path)[1].lower()
    data = open(path, "rb").read()
    if ext in (".png",):
        return data, "image/png"
    if ext in (".jpg", ".jpeg"):
        return data, "image/jpeg"
    from PIL import Image                    # TGA, BMP, TIFF ... as PNG
    out = io.BytesIO()
    Image.open(path).save(out, "PNG")
    return out.getvalue(), "image/png"


def obj_to_glb(src, dst):
    V, VT, VN = [], [], []
    groups, order = {}, []
    name, mat, mtllibs = "model", None, []
    for line in open(src, errors="replace"):
        t = line.split()
        if not t:
            continue
        k = t[0]
        if k == "v":
            V.append([float(x) for x in t[1:4]])
        elif k == "vt":
            VT.append([float(t[1]), float(t[2]) if len(t) > 2 else 0.0])
        elif k == "vn":
            VN.append([float(x) for x in t[1:4]])
        elif k == "f":
            c = []
            for w in t[1:]:
                p = w.split("/")
                vi = int(p[0])
                ti = int(p[1]) if len(p) > 1 and p[1] else 0
                ni = int(p[2]) if len(p) > 2 and p[2] else 0
                c.append((vi - 1 if vi > 0 else len(V) + vi,
                          (ti - 1 if ti > 0 else len(VT) + ti) if ti else -1,
                          (ni - 1 if ni > 0 else len(VN) + ni) if ni else -1))
            key = (name, mat)
            if key not in groups:
                groups[key] = []
                order.append(key)
            g = groups[key]
            for i in range(1, len(c) - 1):
                g += (c[0], c[i], c[i + 1])
        elif k in ("o", "g") and len(t) > 1:
            name = " ".join(t[1:])
        elif k == "usemtl":
            mat = " ".join(t[1:]) if len(t) > 1 else None
        elif k == "mtllib":
            mtllibs.append(" ".join(t[1:]))
    if not groups:
        raise ValueError("no faces in the OBJ")
    folder = os.path.dirname(os.path.abspath(src))
    mtl = {}
    for m in mtllibs:
        p = _find(folder, m)
        if p:
            mtl.update(read_mtl(p))
    nv, nvt, nvn = len(V), len(VT), len(VN)
    V, VT, VN = np.array(V, np.float64), np.array(VT or [[0, 0]], np.float64), np.array(VN or [[0, 0, 1]], np.float64)
    for key in order:
        c = np.array(groups[key], np.int64)
        bad = (c[:, 0] < 0) | (c[:, 0] >= nv)
        if bad.any():
            raise ValueError(f"'{key[0]}' uses vertex {int(c[bad][0, 0]) + 1}, the file has {nv}: "
                             "export the OBJ again")
        # a texture or normal index past the end (a careless exporter): that
        # group goes without, rather than the whole file failing
        c[(c[:, 1] >= nvt) | (c[:, 1] < -1), 1] = -1
        c[(c[:, 2] >= nvn) | (c[:, 2] < -1), 2] = -1
        groups[key] = c

    out = GLB()
    mat_index, tex_cache = {}, {}

    def texture(path):
        if path not in tex_cache:
            tex_cache[path] = out.image(*_png_or_jpg(path))
        return tex_cache[path]

    def material(m):
        if m not in mat_index:
            d = mtl.get(m, {})
            kd = d.get("kd", [0.8, 0.8, 0.8])
            alpha = d.get("d", 1.0)
            pbr = {"baseColorFactor": [float(x) for x in kd] + [float(alpha)],
                   "metallicFactor": float(d.get("pm", 0.0)),
                   "roughnessFactor": float(min(1.0, max(0.05, math.sqrt(2.0 / (d.get("ns", 30.0) + 2.0)))))}
            g = {"name": m or "default", "pbrMetallicRoughness": pbr, "doubleSided": True}
            if d.get("map_kd"):
                pbr["baseColorTexture"] = {"index": texture(d["map_kd"])}
                pbr["baseColorFactor"] = [1.0, 1.0, 1.0, float(alpha)]
            if alpha < 0.999:
                g["alphaMode"] = "BLEND"
            elif d.get("map_d"):
                g["alphaMode"] = "MASK"
            if d.get("norm"):
                g["normalTexture"] = {"index": texture(d["norm"])}
            if d.get("ke") and max(d["ke"]) > 0:
                g["emissiveFactor"] = [float(min(1.0, x)) for x in d["ke"]]
            out.j["materials"].append(g)
            mat_index[m] = len(out.j["materials"]) - 1
        return mat_index[m]

    by_name = {}
    for key in order:
        corners = groups[key]                                      # (n, 3): v, vt, vn
        uniq, inv = np.unique(corners, axis=0, return_inverse=True)
        inv = inv.ravel()
        P = V[uniq[:, 0]]
        prim = {"attributes": {"POSITION": out.accessor(P.astype(np.float32), 5126, "VEC3", 34962, True)},
                "indices": out.accessor(inv.astype(np.uint32), 5125, "SCALAR", 34963), "mode": 4,
                "material": material(key[1])}
        if (uniq[:, 1] >= 0).all() and len(VT):
            uv = VT[uniq[:, 1]].copy()
            uv[:, 1] = 1.0 - uv[:, 1]                                  # OBJ v runs up, glTF's down
            prim["attributes"]["TEXCOORD_0"] = out.accessor(uv.astype(np.float32), 5126, "VEC2", 34962)
        if (uniq[:, 2] >= 0).all():
            N = VN[uniq[:, 2]]
        else:                                                          # smooth normals by position
            T = inv.reshape(-1, 3)
            fn = np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]])
            pk, pinv = np.unique(np.round(P, 6), axis=0, return_inverse=True)
            acc = np.zeros((len(pk), 3))
            for k in range(3):
                np.add.at(acc, pinv.ravel()[T[:, k]], fn)
            N = acc[pinv.ravel()]
        N = N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
        prim["attributes"]["NORMAL"] = out.accessor(N.astype(np.float32), 5126, "VEC3", 34962)
        by_name.setdefault(key[0], []).append(prim)
    for nm, prims in by_name.items():
        out.j["meshes"].append({"name": nm, "primitives": prims})
        out.j["nodes"].append({"name": nm, "mesh": len(out.j["meshes"]) - 1})
        out.j["scenes"][0]["nodes"].append(len(out.j["nodes"]) - 1)
    out.save(dst)
    return {"nodes": len(by_name), "materials": len(mat_index), "textures": len(tex_cache),
            "triangles": int(sum(len(groups[k]) for k in order) // 3)}


def to_glb(src, dst, tools=HERE):
    ext = os.path.splitext(src)[1].lower()
    if ext == ".obj":
        return obj_to_glb(src, dst)
    if ext in (".glb", ".gltf"):
        subprocess.run(["node", os.path.join(tools, "decode.mjs"), os.path.abspath(src), os.path.abspath(dst)],
                       check=True, capture_output=True)
        return {"packed": ext}
    raise ValueError(f"{ext or 'this'} files are not read: export the model as GLB, glTF or OBJ (most shops offer one)")


if __name__ == "__main__":
    print(json.dumps(to_glb(sys.argv[1], sys.argv[2])))
