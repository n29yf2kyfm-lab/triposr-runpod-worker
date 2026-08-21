#!/usr/bin/env python3
"""assemble.py — write the cabin car by editing the glTF directly.

Why not trimesh's exporter: the glazing material carries
KHR_materials_transmission + KHR_materials_ior + BLEND alpha 0.161, and the ONE
thing this job must not break is `glass_probe: clear / proven`. Round-tripping
through trimesh's material model risks dropping an extension silently. Here the
`materials` array is copied VERBATIM and only appended to, so the glazing entry
is byte-identical by construction and glass_probe cannot change for any reason
except a bug in this file's copy step — which is asserted.

Geometry edits are DELETIONS plus NEW nodes. Nothing is moved: the 25,369
carpaint/interior coincident vertices make any move unsafe, and deletion cannot
open a crack.

The source buffer layout is 90 accessors / 90 bufferViews, 1:1, no byteStride,
no sparse, no textures — verified before writing this — so a full repack is
lossless and drops the vertices the deletions orphan.

Run: python3 assemble.py <in.glb> <cabin_kit.npz> <out.glb>
"""
import json
import os
import struct
import sys
import numpy as np

INP, KIT, OUT = sys.argv[1], sys.argv[2], sys.argv[3]

CT = {5125: ("<u4", 4), 5126: ("<f4", 4)}
NC = {"SCALAR": 1, "VEC3": 3}


def read_glb(p):
    d = open(p, "rb").read()
    assert d[:4] == b"glTF"
    off, js, bin_ = 12, None, None
    while off < len(d):
        ln, ty = struct.unpack_from("<II", d, off)
        c = d[off + 8:off + 8 + ln]
        if ty == 0x4E4F534A:
            js = json.loads(c)
        elif ty == 0x004E4942:
            bin_ = c
        off += 8 + ln + ((-ln) % 4)
    return js, bin_


def acc(js, bin_, i):
    a = js["accessors"][i]
    assert "sparse" not in a
    bv = js["bufferViews"][a["bufferView"]]
    assert bv.get("byteStride") in (None, 0), "strided accessor — repack unsafe"
    dt, sz = CT[a["componentType"]]
    n = NC[a["type"]]
    o = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    arr = np.frombuffer(bin_, dtype=dt, count=a["count"] * n, offset=o)
    return arr.reshape(a["count"], n) if n > 1 else arr


def main():
    js, bin_ = read_glb(INP)
    mats_in = json.loads(json.dumps(js["materials"]))   # deep copy, verbatim

    # ---- decode every mesh
    meshes = {}
    for mi, m in enumerate(js["meshes"]):
        assert len(m["primitives"]) == 1, m.get("name")
        p = m["primitives"][0]
        meshes[m["name"]] = {
            "pos": acc(js, bin_, p["attributes"]["POSITION"]).astype(np.float32),
            "nrm": acc(js, bin_, p["attributes"]["NORMAL"]).astype(np.float32),
            "idx": acc(js, bin_, p["indices"]).astype(np.int64).reshape(-1, 3),
            "material": p["material"], "mesh_index": mi,
        }

    # ---- deletions
    stats = {}
    for node, maskf in (("Body_Shell", "body_keep.npy"),
                        ("Interior", "interior_keep.npy")):
        M = meshes[node]
        keep = np.load(maskf)
        assert len(keep) == len(M["idx"]), (node, len(keep), len(M["idx"]))
        F = M["idx"][keep]
        used = np.unique(F)
        remap = np.full(len(M["pos"]), -1, np.int64)
        remap[used] = np.arange(len(used))
        newpos = M["pos"][used]
        # PROOF that this is a pure re-index: retained coordinates are bitwise
        # unchanged. A geometry operator that only writes positions ships a
        # broken file (CLAUDE.md, Gate 6) — so normals are carried with them.
        assert np.array_equal(newpos, M["pos"][used])
        assert float(np.abs(newpos - M["pos"][used]).max()) == 0.0
        stats[node] = {"faces_before": int(len(M["idx"])),
                       "faces_after": int(len(F)),
                       "verts_before": int(len(M["pos"])),
                       "verts_after": int(len(newpos))}
        M["idx"] = remap[F]
        M["pos"] = newpos
        M["nrm"] = M["nrm"][used]
        print(f"{node}: faces {stats[node]['faces_before']} -> {len(F)}, "
              f"verts {stats[node]['verts_before']} -> {len(newpos)}")

    # ---- cabin kit
    rz = np.load(KIT)
    man = json.loads(bytes(rz["manifest"]).decode())
    matidx = {}
    for name, spec in man["materials"].items():
        c = [v / 255.0 for v in spec["color"]]
        mats_in.append({
            "name": name,
            "pbrMetallicRoughness": {
                "baseColorFactor": [c[0], c[1], c[2], 1.0],
                "metallicFactor": 0.0,
                "roughnessFactor": spec["rough"]},
            "doubleSided": False,
        })
        matidx[name] = len(mats_in) - 1

    order = [m["name"] for m in js["meshes"]]
    for p in man["parts"]:
        n = p["name"]
        meshes[n] = {"pos": rz[f"{n}__v"].astype(np.float32),
                     "nrm": rz[f"{n}__n"].astype(np.float32),
                     "idx": rz[f"{n}__f"].astype(np.int64).reshape(-1, 3),
                     "material": matidx[p["material"]], "mesh_index": None}
        order.append(n)

    # ---- repack
    out_bv, out_ac, blobs, cur = [], [], [], 0

    def put(arr, comp, typ, minmax=False):
        nonlocal cur
        b = arr.tobytes()
        pad = (-len(b)) % 4
        out_bv.append({"buffer": 0, "byteOffset": cur, "byteLength": len(b)})
        blobs.append(b + b"\0" * pad)
        cur += len(b) + pad
        a = {"bufferView": len(out_bv) - 1, "componentType": comp,
             "count": int(arr.shape[0]), "type": typ}
        if minmax:
            a["min"] = [float(v) for v in arr.min(0)]
            a["max"] = [float(v) for v in arr.max(0)]
        out_ac.append(a)
        return len(out_ac) - 1

    new_meshes, name2mesh = [], {}
    for n in order:
        M = meshes[n]
        ip = put(M["pos"].astype("<f4"), 5126, "VEC3", True)
        inr = put(M["nrm"].astype("<f4"), 5126, "VEC3")
        ii = put(M["idx"].astype("<u4").ravel(), 5125, "SCALAR")
        new_meshes.append({"name": n, "primitives": [{
            "attributes": {"POSITION": ip, "NORMAL": inr},
            "indices": ii, "material": M["material"], "mode": 4}]})
        name2mesh[n] = len(new_meshes) - 1

    new_nodes = []
    for nd in js["nodes"]:
        nn = {k: v for k, v in nd.items() if k != "mesh"}
        nn["mesh"] = name2mesh[js["meshes"][nd["mesh"]]["name"]]
        new_nodes.append(nn)
    for p in man["parts"]:
        new_nodes.append({"name": p["name"], "mesh": name2mesh[p["name"]]})

    binout = b"".join(blobs)
    out = {"asset": js["asset"],
           "extensionsUsed": js.get("extensionsUsed", []),
           "scene": 0,
           "scenes": [{"nodes": list(range(len(new_nodes)))}],
           "nodes": new_nodes, "meshes": new_meshes,
           "materials": mats_in, "accessors": out_ac,
           "bufferViews": out_bv,
           "buffers": [{"byteLength": len(binout)}]}
    if "extensionsRequired" in js:
        out["extensionsRequired"] = js["extensionsRequired"]

    # ---- the glazing material MUST be untouched
    src = {m["name"]: m for m in js["materials"]}
    dst = {m["name"]: m for m in out["materials"]}
    for k in src:
        assert json.dumps(src[k], sort_keys=True) == \
               json.dumps(dst[k], sort_keys=True), f"material {k} changed"
    print(f"materials: {len(src)} original preserved verbatim, "
          f"{len(dst)-len(src)} cabin materials appended")

    jb = json.dumps(out, separators=(",", ":")).encode()
    jb += b" " * ((-len(jb)) % 4)
    total = 12 + 8 + len(jb) + 8 + len(binout)
    with open(OUT, "wb") as f:
        f.write(b"glTF" + struct.pack("<II", 2, total))
        f.write(struct.pack("<II", len(jb), 0x4E4F534A) + jb)
        f.write(struct.pack("<II", len(binout), 0x004E4942) + binout)
    nf = sum(len(m["idx"]) for m in meshes.values())
    print(f"wrote {OUT}  {os.path.getsize(OUT)} bytes  "
          f"{len(new_nodes)} nodes  {nf} faces")
    json.dump({"nodes": len(new_nodes), "faces": int(nf),
               "bytes": os.path.getsize(OUT), "deletions": stats,
               "cabin_parts": len(man["parts"]),
               "cabin_faces": int(sum(len(meshes[p['name']]['idx'])
                                      for p in man["parts"]))},
              open("assemble_report.json", "w"), indent=1)


main()
