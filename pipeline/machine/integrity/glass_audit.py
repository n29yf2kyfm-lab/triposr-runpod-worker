#!/usr/bin/env python3
"""glass_audit.py — STAGE 4: glazing inventory, AREA, transparency and overlap.

Run: python3 glass_audit.py IN.glb OUT.json

THE RULE THIS FILE EXISTS TO ENFORCE. `glass_probe` reads the material TABLE and
cannot see WHICH FACES carry which material. Two independent agents proved the
same blind spot on the same day: it returned "clear / proven" for a car whose
windscreen aperture was filled with `carpaint`, and for a control whose glazing
GEOMETRY had been cut to 2.5% of its area with the table untouched. It would
ship a car with no glass in it at all.

So EVERY transparency verdict here is paired with a GLASS-AREA figure, per pane
and in total, and the two are reported together or not at all. A dark aperture
is not proof of glass; a transparent material in the table is not proof of
glazing; only area on the right faces is.

Areas are computed from REFERENCED triangles in WORLD space. 68.3% of this
file's declared positions are referenced by no triangle, so any statistic that
includes them is measuring dead payload.
"""
import json
import math
import sys

import numpy as np

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from gltf_facts import load_glb, read_accessor, trs_to_mat, mat_mul  # noqa: E402

# The render worker FORCES transmission=1.0 onto any material whose NAME matches
# this, so for a name-matching material the studio sheet's clear glazing is
# manufactured and worthless as evidence. Recorded per pane below, because it
# decides whether a render is admissible for glazing at all.
WORKER_GLASS_RE = ("glass", "window", "windscreen", "windshield", "screen",
                   "vidro", "glas", "scheibe", "fenster")


def tri_area_world(V, idx, M):
    W = V @ M[:3, :3].T + np.array([M[0][3], M[1][3], M[2][3]])
    t = idx.reshape(-1, 3)
    a, b, c = W[t[:, 0]], W[t[:, 1]], W[t[:, 2]]
    return 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1), W


def material_transparency(m):
    """FACTOR transparency only for the body test; texture alpha is evidence for
    GLAZING but not against it. This file has 0 textures, so factor is all there
    is here."""
    pbr = m.get("pbrMetallicRoughness", {})
    bcf = pbr.get("baseColorFactor", [1, 1, 1, 1])
    ext = m.get("extensions", {})
    tr = ext.get("KHR_materials_transmission", {}).get("transmissionFactor")
    spec_gloss = ext.get("KHR_materials_pbrSpecularGlossiness")
    if spec_gloss and "diffuseFactor" in spec_gloss:
        bcf = spec_gloss["diffuseFactor"]
    return {
        "alphaMode": m.get("alphaMode", "OPAQUE"),
        "baseColorFactor": [round(float(v), 4) for v in bcf],
        "alpha": round(float(bcf[3]) if len(bcf) > 3 else 1.0, 4),
        "transmissionFactor": tr,
        "ior": ext.get("KHR_materials_ior", {}).get("ior"),
        "factor_transparent": bool(
            (len(bcf) > 3 and bcf[3] < 1.0) or (tr is not None and tr > 0)),
    }


def main(src, out):
    g, bin_ = load_glb(src)
    nodes, meshes = g["nodes"], g["meshes"]
    mats = g.get("materials", [])
    parent = {}
    for i, n in enumerate(nodes):
        for c in n.get("children", []):
            parent[c] = i
    cache = {}

    def wmat(i):
        if i in cache:
            return cache[i]
        m = trs_to_mat(nodes[i])
        if i in parent:
            m = mat_mul(wmat(parent[i]), m)
        cache[i] = m
        return m

    mat_info = []
    for mi, m in enumerate(mats):
        t = material_transparency(m)
        nm = (m.get("name") or "").lower()
        t["index"] = mi
        t["name"] = m.get("name")
        t["matches_worker_glass_regex"] = any(k in nm for k in WORKER_GLASS_RE)
        mat_info.append(t)

    per_node = []
    area_by_mat = {}
    total_area = 0.0
    for i, n in enumerate(nodes):
        if n.get("mesh") is None:
            continue
        M = np.array(wmat(i), dtype=np.float64)
        rows = []
        for p in meshes[n["mesh"]]["primitives"]:
            V = np.array(read_accessor(g, bin_, p["attributes"]["POSITION"]),
                         dtype=np.float64)
            idx = np.array([t[0] for t in read_accessor(g, bin_, p["indices"])])
            ar, W = tri_area_world(V, idx, M)
            A = float(ar.sum())
            mi = p.get("material")
            name = mats[mi].get("name") if mi is not None else None
            area_by_mat[name] = area_by_mat.get(name, 0.0) + A
            total_area += A
            Wr = W[np.unique(idx)]
            # glTF Y-up -> Z-up frame used across this gate
            Wz = np.column_stack([Wr[:, 0], -Wr[:, 2], Wr[:, 1]])
            rows.append({"material": name, "material_index": mi,
                         "area_m2": round(A, 6),
                         "triangles": int(len(idx) // 3),
                         "bbox_min": [round(float(v), 5) for v in Wz.min(0)],
                         "bbox_max": [round(float(v), 5) for v in Wz.max(0)]})
        lo = np.min([r["bbox_min"] for r in rows], axis=0)
        hi = np.max([r["bbox_max"] for r in rows], axis=0)
        per_node.append({
            "node": i, "name": n.get("name"),
            "area_m2": round(sum(r["area_m2"] for r in rows), 6),
            "triangles": sum(r["triangles"] for r in rows),
            "materials": sorted({r["material"] for r in rows}),
            "bbox_min": [round(float(v), 5) for v in lo],
            "bbox_max": [round(float(v), 5) for v in hi],
            "size": [round(float(v), 5) for v in (hi - lo)],
            "prims": rows})

    byname = {r["name"]: r for r in per_node}
    glassy = [r for r in per_node
              if any((m or "").lower().find("glass") >= 0 for m in r["materials"])]
    glass_area = sum(r["area_m2"] for r in glassy)

    # ---- REQUIRED PANE INVENTORY. An absent pane is reported ABSENT.
    # NEVER create an empty node so that this table reads full.
    required = ["windscreen", "front_door_L", "front_door_R", "rear_door_L",
                "rear_door_R", "quarter_L", "quarter_R", "rear_screen"]
    present = {r["name"]: r["area_m2"] for r in glassy}

    # ---- side glazing overlap along the car's length (X)
    def span(nm):
        r = byname.get(nm)
        return None if r is None else (r["bbox_min"][0], r["bbox_max"][0])

    overlap = {}
    for a, b in (("Glass_Side_L", "Glass_Quarter_L"),
                 ("Glass_Side_R", "Glass_Quarter_R"),
                 ("Glass_Backlight", "Glass_Rear")):
        sa, sb = span(a), span(b)
        if sa and sb:
            lo, hi = max(sa[0], sb[0]), min(sa[1], sb[1])
            ov = max(0.0, hi - lo)
            shorter = min(sa[1] - sa[0], sb[1] - sb[0])
            overlap[f"{a}|{b}"] = {
                "a_span_x": [round(v, 5) for v in sa],
                "b_span_x": [round(v, 5) for v in sb],
                "overlap_m": round(ov, 5),
                "pct_of_shorter": round(100 * ov / shorter, 2) if shorter else None}
        else:
            overlap[f"{a}|{b}"] = {"status": "ABSENT",
                                   "missing": [n for n, s in ((a, sa), (b, sb))
                                               if s is None]}

    doc = {
        "source": src,
        "total_surface_area_m2": round(total_area, 5),
        "glass_area_m2": round(glass_area, 5),
        "glass_area_pct_of_total": round(100 * glass_area / total_area, 4),
        "glass_band_note": ("catalogue calibration is glass AREA / total AREA "
                            "banded 1.0-13.0% (10 live cars: min 1.12 VW Polo, "
                            "median 5.75, max 12.24 BMW M440i)"),
        "materials": mat_info,
        "area_by_material_m2": {k: round(v, 6) for k, v in
                                sorted(area_by_mat.items(),
                                       key=lambda kv: -kv[1])},
        "glazing_nodes": [{"name": r["name"], "area_m2": r["area_m2"],
                           "triangles": r["triangles"],
                           "materials": r["materials"],
                           "size": r["size"]} for r in
                          sorted(glassy, key=lambda r: -r["area_m2"])],
        "required_pane_inventory": {
            k: ("see glazing_nodes" if k in present else "NOT A NODE NAME — "
                "mapped by hand below") for k in required},
        "side_glazing_overlap": overlap,
        "nodes": per_node,
    }
    json.dump(doc, open(out, "w"), indent=1)
    print(f"total area {total_area:.4f} m2   glass {glass_area:.4f} m2 "
          f"({100*glass_area/total_area:.3f}%)")
    for r in doc["glazing_nodes"]:
        print(f"  {r['name']:22} {r['area_m2']:8.5f} m2  {r['triangles']:7d} tris "
              f"{r['materials']}")
    print("worker-regex-matching materials:",
          [m["name"] for m in mat_info if m["matches_worker_glass_regex"]])
    print("factor-transparent materials  :",
          [m["name"] for m in mat_info if m["factor_transparent"]])
    for k, v in overlap.items():
        print(" overlap", k, v)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
