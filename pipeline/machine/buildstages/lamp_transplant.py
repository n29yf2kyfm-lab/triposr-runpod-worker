#!/usr/bin/env python3
"""lamp_transplant.py — bring Gate 4's four tail-lamp units onto this lineage.

WHY THIS IS A TRANSPLANT WHEN THE PANELS WERE A REPLAY, and the distinction is
the whole argument:

  * the rear PANELS are FITTED to the car's own measured skin.  Fitting is a
    function of the lineage, so a panel fitted to Gate 4's file is not the panel
    this car needs, and they were re-derived (see rear_replay.py).
  * the LAMP UNITS are CONSTRUCTED SOLIDS.  They are rigid parts that sit ON the
    skin at measured landmarks, they carry identity node transforms, and the two
    files are the same car in the same world frame to under 2 mm at every height
    (proven in rear_replay.py's docstring).  There is nothing to re-derive: the
    part is the part.

WHAT IS NOT CARRIED ACROSS.  Gate 4's MATERIAL TABLE.  That file has
`extensionsUsed` absent entirely -- no transmission, no IOR, no clearcoat -- and
importing it would put a second, weaker table into a car whose glazing
certification depends on the first.  Two materials are AUTHORED here instead,
with Gate 4's measured values: a dark red lens (baseColor 0.361/0.016/0.024,
roughness 0.10, metallic 0) and a near-black housing (0.031/0.031/0.035,
roughness 0.85, metallic 0).  Nothing else about the target's table is touched.

THE MELT LAMPS ARE DELETED IN THE SAME OPERATION.  `TailLamp_L/R` on this
lineage are the original melt under clean semantic names -- exactly the "a node
whose NAME is right and whose GEOMETRY is melt" trap Gate 3 v7 documents.
Keeping both would leave the constructed units stacked on the melt they replace,
which is the parts-over-melt failure, and would leave the melt shells
interpenetrating the rebuilt tailgate by up to 17.7 mm (measured before this
step).  Deleting a whole node moves no vertex, so it cannot open a crack.

Everything is done at the glTF level: accessors, bufferViews and mesh entries
are APPENDED and the BIN chunk is extended, so no existing byte is rewritten and
no trimesh round-trip can drop an extension.

Run: lamp_transplant.py <target.glb> <donor.glb> <out.glb> <report.json>
"""
from __future__ import annotations

import json
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glbmeas                                                   # noqa: E402

UNITS = ["Tail_Lens_LO", "Tail_Lens_LH", "Tail_Lens_RO", "Tail_Lens_RH",
         "Tail_Housing_LO", "Tail_Housing_LH", "Tail_Housing_RO",
         "Tail_Housing_RH"]
DROP = ["TailLamp_L", "TailLamp_R"]

MATS = {
    "Tail_Lens_Red": {"name": "Tail_Lens_Red", "doubleSided": False,
                      "pbrMetallicRoughness": {
                          "baseColorFactor": [0.3607843137254902,
                                              0.01568627450980392,
                                              0.023529411764705882, 1.0],
                          "metallicFactor": 0.0, "roughnessFactor": 0.10}},
    "Tail_Housing": {"name": "Tail_Housing", "doubleSided": False,
                     "pbrMetallicRoughness": {
                         "baseColorFactor": [0.03137254901960784,
                                             0.03137254901960784,
                                             0.03529411764705882, 1.0],
                         "metallicFactor": 0.0, "roughnessFactor": 0.85}},
}


def _write(path, js, binbuf):
    j = json.dumps(js, separators=(",", ":")).encode("utf-8")
    j += b" " * ((4 - len(j) % 4) % 4)
    b = bytes(binbuf)
    b += b"\0" * ((4 - len(b) % 4) % 4)
    with open(path, "wb") as f:
        f.write(b"glTF" + struct.pack("<II", 2, 12 + 8 + len(j) + 8 + len(b)))
        f.write(struct.pack("<II", len(j), 0x4E4F534A) + j)
        f.write(struct.pack("<II", len(b), 0x004E4942) + b)


def run(target, donor, out, report=None):
    T = glbmeas.GLB(target)
    D = glbmeas.GLB(donor)
    tj = T.g
    binbuf = bytearray(T.bin)
    rep = {"target": os.path.basename(target), "donor": os.path.basename(donor),
           "target_sha256_in": glbmeas.sha256(target),
           "added": {}, "dropped": {}, "materials_added": []}

    # ---- the donor units, in WORLD space (their nodes are identity; asserted)
    dgeo = {}
    for ni, name, W, mi in D.graph():
        if name not in UNITS:
            continue
        if float(np.abs(W - np.eye(4)).max()) > 1e-9:
            raise SystemExit(f"REFUSED: donor node {name} is not identity; the "
                             f"transplant assumes local == world on that file")
        prims = D.g["meshes"][mi]["primitives"]
        if len(prims) != 1:
            raise SystemExit(f"REFUSED: donor {name} has {len(prims)} primitives")
        p = prims[0]
        if "NORMAL" not in p["attributes"]:
            raise SystemExit(f"REFUSED: donor {name} has no NORMAL accessor")
        V = D.accessor(p["attributes"]["POSITION"]).astype(np.float32)
        N = D.accessor(p["attributes"]["NORMAL"]).astype(np.float32)
        F = D.accessor(p["indices"]).astype(np.uint32).reshape(-1, 3)
        mn = D.g["materials"][p["material"]].get("name")
        dgeo[name] = (V, N, F, mn)
    missing = [u for u in UNITS if u not in dgeo]
    if missing:
        raise SystemExit(f"REFUSED: donor is missing {missing}")

    # ---- materials: APPEND ours, never import the donor's table
    midx = {m.get("name"): i for i, m in enumerate(tj["materials"])}
    for k, v in MATS.items():
        if k in midx:
            continue
        tj["materials"].append(json.loads(json.dumps(v)))
        midx[k] = len(tj["materials"]) - 1
        rep["materials_added"].append(k)

    def put(arr, comp, typ, minmax=False):
        while len(binbuf) % 4:
            binbuf.append(0)
        off = len(binbuf)
        b = arr.tobytes()
        binbuf.extend(b)
        tj["bufferViews"].append({"buffer": 0, "byteOffset": off,
                                  "byteLength": len(b)})
        a = {"bufferView": len(tj["bufferViews"]) - 1, "componentType": comp,
             "count": int(arr.shape[0]), "type": typ}
        if minmax:
            a["min"] = [float(x) for x in arr.min(0)]
            a["max"] = [float(x) for x in arr.max(0)]
        tj["accessors"].append(a)
        return len(tj["accessors"]) - 1

    scene = tj["scenes"][tj.get("scene", 0)]
    for name in UNITS:
        V, N, F, mn = dgeo[name]
        ip = put(np.ascontiguousarray(V, "<f4"), 5126, "VEC3", True)
        inn = put(np.ascontiguousarray(N, "<f4"), 5126, "VEC3")
        ii = put(np.ascontiguousarray(F.ravel(), "<u4"), 5125, "SCALAR")
        tj["meshes"].append({"name": name, "primitives": [{
            "attributes": {"POSITION": ip, "NORMAL": inn},
            "indices": ii, "material": midx[mn], "mode": 4}]})
        tj["nodes"].append({"name": name, "mesh": len(tj["meshes"]) - 1})
        scene["nodes"].append(len(tj["nodes"]) - 1)
        rep["added"][name] = {"faces": int(len(F)), "verts": int(len(V)),
                              "material": mn}

    # ---- drop the melt lamps.  Node removal only; no index is rewritten, so a
    # dangling mesh/accessor is simply unreferenced (the validator reports
    # UNUSED_OBJECT as a HINT, and the mobile export drops them).
    keep_nodes = []
    for i in scene["nodes"]:
        nm = tj["nodes"][i].get("name")
        if nm in DROP:
            mi = tj["nodes"][i].get("mesh")
            nf = sum(tj["accessors"][p["indices"]]["count"] // 3
                     for p in tj["meshes"][mi]["primitives"]) if mi is not None else 0
            rep["dropped"][nm] = {"faces": int(nf)}
        else:
            keep_nodes.append(i)
    scene["nodes"] = keep_nodes
    still = [n for n in DROP if n not in rep["dropped"]]
    if still:
        raise SystemExit(f"REFUSED: expected to drop {DROP}, could not find {still}")

    tj["buffers"][0]["byteLength"] = len(binbuf)
    _write(out, tj, binbuf)

    # ---- assert on the WRITTEN file, never on the structure in memory
    m = glbmeas.measure(out)
    got = set(m["per_node"])
    absent = [u for u in UNITS if u not in got]
    lingering = [d for d in DROP if d in got]
    rep["written"] = {
        "sha256": m["sha256"], "bytes": m["bytes"], "nodes": m["nodes"],
        "faces": m["faces"], "primitives_missing_NORMAL":
            m["primitives_missing_NORMAL"], "zero_normals": m["zero_normals"],
        "units_absent": absent, "melt_lamps_still_present": lingering,
        "glass_projected_m2": m["glass_projected_m2"]["max"]}
    if absent or lingering or m["primitives_missing_NORMAL"] or m["zero_normals"]:
        raise SystemExit(f"REFUSED on the written file: {rep['written']}")
    if report:
        json.dump(rep, open(report, "w"), indent=1)
    return rep


if __name__ == "__main__":
    r = run(*sys.argv[1:5])
    print(json.dumps(r, indent=1))
