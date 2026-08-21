#!/usr/bin/env python3
"""glbmeas.py — measure a GLB straight out of its own bytes.

NO TRIMESH.  Every other reader in this repo goes through `trimesh.load`, and
CLAUDE.md records twice over that a trimesh round-trip silently drops every KHR
material extension and can zero normals.  A MEASURING instrument must not be
able to change what it measures, and it must not inherit a reader's opinions, so
this one parses the glTF JSON and the BIN chunk directly.

WHAT IT MEASURES, and why each number is here rather than a neighbouring one:

  * `glass_area_m2` — the WORLD-SPACE surface area of every triangle whose
    primitive is bound to a glazing-named material.  This is the figure that
    CLAUDE.md 2026-08-21 says must ALWAYS be paired with a `glass_probe`
    verdict: two agents independently proved the probe passes a car whose
    windscreen aperture is `carpaint` (glass gate) and a car whose glazing
    geometry has been cut to 2.5% of its area (mobile gate).  The probe reads
    the material TABLE; this reads the SURFACE.  Neither is sufficient alone.

  * area is computed from TRANSFORMED vertices.  CLAUDE.md's standing rule, and
    the reason the merge gate had to correct the brief: node-local minima said
    the tyres were 307 mm underground when they were 183 mm in the air.

  * `zero_normals` / `non_unit_normals` — ACCESSOR_VECTOR3_NON_UNIT is a
    validator ERROR and it is invisible in a render (the crumpled-foil class).

  * per-node and per-material areas, so a regression can be LOCATED rather than
    merely detected.

Sparse accessors and byteStride are handled; a Draco-compressed primitive is
refused rather than silently measured as empty (trimesh in this container has no
Draco handler and returns all-zero vertices — CLAUDE.md 2026-08-14).
"""
from __future__ import annotations

import hashlib
import json
import struct

import numpy as np

_CT = {5120: ("<i1", 1), 5121: ("<u1", 1), 5122: ("<i2", 2),
       5123: ("<u2", 2), 5125: ("<u4", 4), 5126: ("<f4", 4)}
_NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

GLAZING_MATS = ("glass",)          # this car's glazing material name


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def read_glb(path):
    raw = open(path, "rb").read()
    if raw[:4] != b"glTF":
        raise ValueError(f"{path}: not a GLB")
    off, js, bin_ = 12, None, b""
    while off < len(raw):
        ln, ty = struct.unpack_from("<II", raw, off)
        off += 8
        chunk = raw[off:off + ln]
        if ty == 0x4E4F534A:
            js = json.loads(chunk.decode("utf-8"))
        elif ty == 0x004E4942:
            bin_ = chunk
        off += ln
    return js, bin_


class GLB:
    def __init__(self, path):
        self.path = path
        self.g, self.bin = read_glb(path)

    # ------------------------------------------------------------- accessors
    def accessor(self, idx):
        a = self.g["accessors"][idx]
        n, nc = a["count"], _NC[a["type"]]
        dt, isz = _CT[a["componentType"]]
        if "bufferView" not in a:
            out = np.zeros((n, nc), dtype=np.dtype(dt))
        else:
            bv = self.g["bufferViews"][a["bufferView"]]
            base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
            stride = bv.get("byteStride") or isz * nc
            if stride == isz * nc:
                out = np.frombuffer(self.bin, dtype=np.dtype(dt),
                                    count=n * nc, offset=base).reshape(n, nc)
            else:
                out = np.empty((n, nc), dtype=np.dtype(dt))
                for i in range(n):
                    out[i] = np.frombuffer(self.bin, dtype=np.dtype(dt),
                                           count=nc, offset=base + i * stride)
        if "sparse" in a:                      # rare, but silently wrong if skipped
            out = np.array(out)
            sp = a["sparse"]
            ib = self.g["bufferViews"][sp["indices"]["bufferView"]]
            idt, iis = _CT[sp["indices"]["componentType"]]
            ii = np.frombuffer(self.bin, dtype=np.dtype(idt), count=sp["count"],
                               offset=ib.get("byteOffset", 0)
                               + sp["indices"].get("byteOffset", 0))
            vb = self.g["bufferViews"][sp["values"]["bufferView"]]
            vv = np.frombuffer(self.bin, dtype=np.dtype(dt), count=sp["count"] * nc,
                               offset=vb.get("byteOffset", 0)
                               + sp["values"].get("byteOffset", 0)).reshape(-1, nc)
            out[ii] = vv
        return out

    def node_matrix(self, nd):
        if "matrix" in nd:
            return np.array(nd["matrix"], float).reshape(4, 4).T
        M = np.eye(4)
        if "rotation" in nd:
            x, y, z, w = nd["rotation"]
            M[:3, :3] = np.array([
                [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        if "scale" in nd:
            M[:3, :3] = M[:3, :3] @ np.diag(nd["scale"])
        if "translation" in nd:
            M[:3, 3] = nd["translation"]
        return M

    def graph(self):
        """[(node_index, name, world_matrix, mesh_index)] for every mesh node."""
        out, seen = [], set()
        scenes = self.g.get("scenes") or [{}]
        scene = scenes[self.g.get("scene", 0)]
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

    def material_name(self, prim):
        if "material" not in prim:
            return None
        return self.g["materials"][prim["material"]].get(
            "name", f"mat{prim['material']}")


def measure(path, glazing=GLAZING_MATS, ref_box=None):
    """The full measurement panel for one GLB.  Pure read, no writes.

    `ref_box` = (min, max) of the REFERENCE car, so `glass_area_by_region` is
    binned in the same physical boxes at every stage and the numbers compare.
    """
    g = GLB(path)
    j = g.g
    mats = [m.get("name", f"mat{i}") for i, m in enumerate(j.get("materials", []))]
    rep = {
        "path": path, "sha256": sha256(path),
        "bytes": len(open(path, "rb").read()),
        "nodes": len(j.get("nodes", [])), "meshes": len(j.get("meshes", [])),
        "materials": mats,
        "extensionsUsed": sorted(j.get("extensionsUsed") or []),
        "images": len(j.get("images", [])),
    }
    if any("KHR_draco_mesh_compression" in (p.get("extensions") or {})
           for m in j.get("meshes", []) for p in m.get("primitives", [])):
        raise SystemExit(f"REFUSED: {path} is Draco-compressed; this container "
                         f"has no Draco decoder and would measure zeros")

    per_node, per_mat = {}, {}
    tot_area = 0.0
    faces = 0
    prims = 0
    prims_with_normal = 0
    zero_n = 0
    nonunit_n = 0
    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)
    node_bbox = {}
    for ni, name, W, mi in g.graph():
        for pi, p in enumerate(j["meshes"][mi].get("primitives", [])):
            prims += 1
            V = g.accessor(p["attributes"]["POSITION"]).astype(np.float64)
            V = V @ W[:3, :3].T + W[:3, 3]
            if "indices" in p:
                F = g.accessor(p["indices"]).astype(np.int64).reshape(-1, 3)
            else:
                F = np.arange(len(V), dtype=np.int64).reshape(-1, 3)
            tri = V[F]
            a = 0.5 * np.linalg.norm(
                np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
            ar = float(a.sum())
            mn = g.material_name(p) or "<none>"
            faces += len(F)
            tot_area += ar
            e = per_node.setdefault(name, {"faces": 0, "area": 0.0, "materials": []})
            e["faces"] += len(F)
            e["area"] += ar
            if mn not in e["materials"]:
                e["materials"].append(mn)
            m2 = per_mat.setdefault(mn, {"faces": 0, "area": 0.0, "nodes": []})
            m2["faces"] += len(F)
            m2["area"] += ar
            if name not in m2["nodes"]:
                m2["nodes"].append(name)
            used = V[np.unique(F)] if len(F) else V
            if len(used):
                lo = np.minimum(lo, used.min(0))
                hi = np.maximum(hi, used.max(0))
                bb = node_bbox.setdefault(name, [used.min(0).copy(), used.max(0).copy()])
                bb[0] = np.minimum(bb[0], used.min(0))
                bb[1] = np.maximum(bb[1], used.max(0))
            if "NORMAL" in p["attributes"]:
                prims_with_normal += 1
                N = g.accessor(p["attributes"]["NORMAL"]).astype(np.float64)
                ln = np.linalg.norm(N, axis=1)
                zero_n += int((ln < 1e-8).sum())
                nonunit_n += int(((ln > 1e-8) & (np.abs(ln - 1.0) > 1e-3)).sum())

    rep["faces"] = faces
    rep["primitives"] = prims
    rep["primitives_with_NORMAL"] = prims_with_normal
    rep["primitives_missing_NORMAL"] = prims - prims_with_normal
    rep["zero_normals"] = zero_n
    rep["non_unit_normals"] = nonunit_n
    rep["total_area_m2"] = round(tot_area, 9)
    rep["bbox_min"] = [round(float(x), 6) for x in lo]
    rep["bbox_max"] = [round(float(x), 6) for x in hi]
    rep["per_material"] = {k: {"faces": v["faces"], "area": round(v["area"], 9),
                               "nodes": sorted(v["nodes"])}
                           for k, v in sorted(per_mat.items())}
    rep["per_node"] = {k: {"faces": v["faces"], "area": round(v["area"], 9),
                           "materials": v["materials"]}
                       for k, v in sorted(per_node.items())}
    rep["node_bbox"] = {k: {"min": [round(float(x), 6) for x in v[0]],
                            "max": [round(float(x), 6) for x in v[1]]}
                        for k, v in sorted(node_bbox.items())}

    gl = [m for m in per_mat if m.lower() in [x.lower() for x in glazing]]
    rep["glass_materials"] = sorted(gl)
    rep["glass_area_m2"] = round(sum(per_mat[m]["area"] for m in gl), 9)
    rep["glass_faces"] = int(sum(per_mat[m]["faces"] for m in gl))
    rep["glass_area_by_node"] = {}
    for ni, name, W, mi in g.graph():
        for p in j["meshes"][mi].get("primitives", []):
            if (g.material_name(p) or "") in gl:
                V = g.accessor(p["attributes"]["POSITION"]).astype(np.float64)
                V = V @ W[:3, :3].T + W[:3, 3]
                F = g.accessor(p["indices"]).astype(np.int64).reshape(-1, 3)
                tri = V[F]
                a = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0],
                                                  tri[:, 2] - tri[:, 0]), axis=1)
                rep["glass_area_by_node"][name] = round(
                    rep["glass_area_by_node"].get(name, 0.0) + float(a.sum()), 9)

    # ---- glazing area by SPATIAL REGION.
    # The per-NODE figure cannot tell a deliberate re-partition from a loss: the
    # glass gate carves `Glass_Quarter_L` out of `Glass_Side_L` and takes that
    # node 1.2728 -> 0.7903 m2 while removing nothing from the car.  A region is
    # invariant to renaming — glazing that is merely re-labelled stays in the
    # same box; glazing that is rebound to `carpaint` or cut away leaves it.
    # Five bands along the car's length x two sides, binned against the
    # REFERENCE car's bounding box so the boxes are physically the same at every
    # stage.
    rb = ref_box or (lo, hi)
    rlo, rhi = np.asarray(rb[0], float), np.asarray(rb[1], float)
    reg = {}
    for ni, name, W, mi in g.graph():
        for p in j["meshes"][mi].get("primitives", []):
            if (g.material_name(p) or "") not in gl:
                continue
            V = g.accessor(p["attributes"]["POSITION"]).astype(np.float64)
            V = V @ W[:3, :3].T + W[:3, 3]
            F = g.accessor(p["indices"]).astype(np.int64).reshape(-1, 3)
            tri = V[F]
            c = tri.mean(1)
            a = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0],
                                              tri[:, 2] - tri[:, 0]), axis=1)
            xf = (c[:, 0] - rlo[0]) / max(rhi[0] - rlo[0], 1e-9)
            xb = np.clip((xf * 5).astype(int), 0, 4)
            sd = (c[:, 2] > 0).astype(int)
            for b in range(5):
                for k in (0, 1):
                    m2 = (xb == b) & (sd == k)
                    if m2.any():
                        key = f"x{b}{'P' if k else 'M'}"
                        reg[key] = reg.get(key, 0.0) + float(a[m2].sum())
    rep["glass_area_by_region"] = {k: round(v, 9) for k, v in sorted(reg.items())}
    rep["region_ref_box"] = [[round(float(x), 6) for x in rlo],
                             [round(float(x), 6) for x in rhi]]

    # material factual table — what a respray and the glazing ruling can see
    tbl = {}
    for m in j.get("materials", []):
        pbr = m.get("pbrMetallicRoughness", {}) or {}
        tbl[m.get("name")] = {
            "baseColorFactor": pbr.get("baseColorFactor"),
            "metallicFactor": pbr.get("metallicFactor"),
            "roughnessFactor": pbr.get("roughnessFactor"),
            "alphaMode": m.get("alphaMode"),
            "extensions": sorted((m.get("extensions") or {}).keys()),
            "hasBaseColorTexture": "baseColorTexture" in pbr,
        }
    rep["material_table"] = tbl

    t = tbl.get("Tyre_Rubber", {})
    bcf = t.get("baseColorFactor")
    rep["tyre_baseColor"] = bcf[:3] if bcf else None
    rep["tyre_area_m2"] = round(per_mat.get("Tyre_Rubber", {}).get("area", 0.0), 9)

    # tyre-node world minima — viewer_check's on_ground reads the whole-model
    # bbox and passes a car with its front tyres 183 mm in the air (CLAUDE.md).
    rep["tyre_node_min_y"] = {k: round(float(v["min"][1]), 9)
                              for k, v in rep["node_bbox"].items()
                              if k.lower().endswith("tyre")}
    return rep


if __name__ == "__main__":
    import sys
    r = measure(sys.argv[1])
    if len(sys.argv) > 2:
        json.dump(r, open(sys.argv[2], "w"), indent=1)
    print(json.dumps({k: v for k, v in r.items()
                      if k not in ("per_node", "node_bbox", "per_material",
                                   "material_table")}, indent=1))
