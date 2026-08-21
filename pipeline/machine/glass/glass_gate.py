#!/usr/bin/env python3
"""glass_gate.py — the acceptance suite for the GLAZING gate, run BEFORE and AFTER.

Everything here is a PAIRED measurement: the same probe on the input and the output, so
a number is only ever reported as a change, never as an absolute that nothing calibrates.

  G1 glass_probe verdict + certainty + flat_shell + alpha_shell   (must not regress)
  G2 SPILL: glazing area on roof / cant rail / below the beltline / over the pillars
  G3 APERTURE GLAZING: of the surface that IS the windscreen (body-or-glass faces lying
     on the fitted screen quadric inside the measured cowl->header, above-beltline box),
     what fraction carries the glazing material?  This is the number the label render
     shows by eye; the aperture definition is fixed from the INPUT and reused for the
     OUTPUT so the denominator cannot move under the answer.
  G4 HOLES: 15 directions (az 0/+-22/+-40 x el 0/+-18).  For each ray that hits the car,
     record whether it hits at all.  A repair that opened a hole shows as rays that hit
     before and miss after.  Also reports first-hit BACK-FACING fraction per node, which
     is the defect a doubleSided:false client renders as a hole and which Cycles cannot
     see.
  G5 NORMALS: every primitive carries NORMAL; count non-unit vectors.
  G6 TYRES: the tyre material's baseColorFactor (CLAUDE.md: a glTF tyre probe cannot
     clear a car of the per-corner render artefact -- this ONLY rules out the
     paint-over-rubber and flat-shell mechanisms, and it says so).

Run: glass_gate.py before.glb after.glb --json gate.json
"""
import argparse
import json
import os
import struct
import sys

import numpy as np
import trimesh

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "ingest"))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from glass_forensics import world_mesh                                    # noqa: E402

GLASSY_MAT = "glass"


def gltf_json(path):
    b = open(path, "rb").read()
    jlen = struct.unpack("<I", b[12:16])[0]
    return json.loads(b[20:20 + jlen].decode("utf-8")), b


def probe_file(path):
    import glass_probe as G
    return G.probe(None, url="file://" + os.path.abspath(path))


def glass_faces(sc):
    """Faces whose MATERIAL is the glazing material -- not faces whose NODE is named
    Glass_*.  A node name is a label; the material is what the renderer and the probe
    actually use."""
    out = {}
    for name in sc.graph.nodes_geometry:
        m = world_mesh(sc, name)
        mat = getattr(m.visual, "material", None)
        nm = getattr(mat, "name", "") or ""
        out[name] = (m, nm == GLASSY_MAT)
    return out


def cat(sc):
    V, F, gmask, node, off = [], [], [], [], 0
    for name in sc.graph.nodes_geometry:
        m = world_mesh(sc, name)
        mat = getattr(m.visual, "material", None)
        isg = (getattr(mat, "name", "") or "") == GLASSY_MAT
        V.append(m.vertices); F.append(m.faces + off)
        gmask.append(np.full(len(m.faces), isg))
        node += [name] * len(m.faces)
        off += len(m.vertices)
    V = np.vstack(V); F = np.vstack(F)
    big = trimesh.Trimesh(vertices=V, faces=F, process=False, validate=False)
    return big, np.concatenate(gmask), np.array(node, dtype=object)


def ray_grid(mesh, n_az=5, n_el=3, res=260):
    b = mesh.bounds; ctr = b.mean(0); rad = float(np.linalg.norm(b[1] - b[0]))
    dirs = []
    for az in (0, 22, -22, 40, -40):
        for el in (0, 18, -18):
            a, e = np.radians(az), np.radians(el)
            dirs.append((np.cos(e) * np.cos(a), np.sin(e), np.cos(e) * np.sin(a)))
    try:
        from trimesh.ray import ray_pyembree
        inter = ray_pyembree.RayMeshIntersector(mesh)
    except Exception:
        inter = trimesh.ray.ray_triangle.RayMeshIntersector(mesh)
    hits, org_all, dir_all = [], [], []
    for d in dirs:
        d = np.array(d, float); d /= np.linalg.norm(d)
        up = np.array([0, 1, 0.0]) if abs(d[1]) < 0.9 else np.array([1, 0, 0.0])
        e1 = np.cross(d, up); e1 /= np.linalg.norm(e1)
        e2 = np.cross(d, e1)
        g = np.linspace(-0.55 * rad, 0.55 * rad, res)
        gu, gv = np.meshgrid(g, g)
        org = ctr + np.outer(gu.ravel(), e1) + np.outer(gv.ravel(), e2) - d * rad
        org_all.append(org); dir_all.append(np.tile(d, (len(org), 1)))
    org = np.vstack(org_all); dd = np.vstack(dir_all)
    idx_tri, idx_ray = inter.intersects_id(org, dd, multiple_hits=False, return_locations=False)[:2] \
        if False else (None, None)
    loc, ray_i, tri = inter.intersects_location(org, dd, multiple_hits=True)
    t = ((loc - org[ray_i]) * dd[ray_i]).sum(1)
    order = np.lexsort((t, ray_i))
    ray_i, tri = ray_i[order], tri[order]
    _, u = np.unique(ray_i, return_index=True)
    hitmask = np.zeros(len(org), dtype=bool)
    hitmask[ray_i[u]] = True
    first = np.full(len(org), -1, dtype=np.int64)
    first[ray_i[u]] = tri[u]
    backface = np.zeros(len(org), dtype=bool)
    fn = mesh.face_normals[first[hitmask]]
    backface[hitmask] = (fn * dd[hitmask]).sum(1) > 0
    return hitmask, first, backface, len(org)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("before"); ap.add_argument("after")
    ap.add_argument("--json"); ap.add_argument("--res", type=int, default=240)
    a = ap.parse_args()
    R = {"before": a.before, "after": a.after}

    # ---- G1 -----------------------------------------------------------------
    R["G1_glass_probe"] = {}
    for k, p in (("before", a.before), ("after", a.after)):
        r = probe_file(p)
        R["G1_glass_probe"][k] = {kk: r.get(kk) for kk in
                                  ("verdict", "certainty", "flat_shell", "alpha_shell")}
    print("G1 glass_probe:", json.dumps(R["G1_glass_probe"]))

    scB = trimesh.load(a.before, force="scene", process=False)
    scA = trimesh.load(a.after, force="scene", process=False)
    bigB, gB, ndB = cat(scB)
    bigA, gA, ndA = cat(scA)
    CB, CA = bigB.triangles_center, bigA.triangles_center
    aB, aA = bigB.area_faces, bigA.area_faces
    nB, nA = bigB.face_normals, bigA.face_normals
    nuB = nB * np.where(nB[:, 1] < 0, -1.0, 1.0)[:, None]
    nuA = nA * np.where(nA[:, 1] < 0, -1.0, 1.0)[:, None]

    # ---- G2 spill (same rules and constants both sides) ----------------------
    BELT, HEADER, CPIL, APIL = 0.995, -0.34, 0.86, -0.62
    R["G2_spill"] = {}
    for k, (C, ar, nu, g) in (("before", (CB, aB, nuB, gB)), ("after", (CA, aA, nuA, gA))):
        mid = (C[:, 0] > HEADER) & (C[:, 0] < CPIL + 0.28)
        roof = g & mid & (np.abs(nu[:, 1]) > 0.72)
        below = g & (C[:, 1] < BELT)
        cpil = g & (C[:, 0] > CPIL) & (C[:, 0] < CPIL + 0.14) & (np.abs(C[:, 2]) > 0.40)
        front = g & (C[:, 0] < APIL)
        R["G2_spill"][k] = {
            "glazing_area": round(float(ar[g].sum()), 5),
            "roof_cantrail_area": round(float(ar[roof].sum()), 5),
            "below_beltline_area": round(float(ar[below].sum()), 5),
            "over_cpillar_area": round(float(ar[cpil].sum()), 5),
            "fwd_of_apillar_area": round(float(ar[front].sum()), 5),
        }
    print("G2 spill:", json.dumps(R["G2_spill"], indent=1))

    # ---- G3 aperture glazing share ------------------------------------------
    # the aperture surface is fixed from the BEFORE file and reused unchanged
    from glass_repair import fit_quadric, quadric_dist
    core = (CB[:, 0] > -1.16) & (CB[:, 0] < HEADER) & (CB[:, 1] > BELT) & \
        (np.abs(CB[:, 2]) < 0.33) & ~gB
    d0 = np.array([-0.55, 0.835, 0.0]); d0 /= np.linalg.norm(d0)
    core &= np.abs(nuB @ d0) > 0.90
    c0, R0, k0 = fit_quadric(CB[core])
    for _ in range(3):
        dd, _, _ = quadric_dist(CB[core], c0, R0, k0)
        core2 = core.copy(); core2[core] = np.abs(dd) < max(0.012, 2.5 * np.std(dd))
        c0, R0, k0 = fit_quadric(CB[core2]); core = core2
    nsurf = R0[2]
    R["G3_aperture"] = {}
    for k, (C, ar, nu, g) in (("before", (CB, aB, nuB, gB)), ("after", (CA, aA, nuA, gA))):
        dsurf = np.abs(quadric_dist(C, c0, R0, k0)[0])
        ap_m = (C[:, 0] > -1.16 - 0.12) & (C[:, 0] < HEADER + 0.05) & (C[:, 1] > BELT) & \
               (dsurf < 0.09) & (np.abs(nu @ nsurf) > 0.70)
        tot = float(ar[ap_m].sum()); gl = float(ar[ap_m & g].sum())
        R["G3_aperture"][k] = {"aperture_area": round(tot, 5), "glazed_area": round(gl, 5),
                               "glazed_frac": round(gl / tot, 4) if tot else None}
    print("G3 windscreen aperture glazed fraction:", json.dumps(R["G3_aperture"]))

    # ---- G4 holes + backface -------------------------------------------------
    R["G4_holes"] = {}
    hB, fB, bfB, nrB = ray_grid(bigB, res=a.res)
    hA, fA, bfA, nrA = ray_grid(bigA, res=a.res)
    assert nrB == nrA, "ray grids differ"
    lost = int((hB & ~hA).sum()); gained = int((~hB & hA).sum())
    R["G4_holes"] = {"rays": int(nrB), "hits_before": int(hB.sum()), "hits_after": int(hA.sum()),
                     "rays_lost": lost, "rays_gained": gained,
                     "lost_frac_of_hits": round(lost / max(1, int(hB.sum())), 6)}
    for k, (h, f, bf, nd) in (("before", (hB, fB, bfB, ndB)), ("after", (hA, fA, bfA, ndA))):
        per = {}
        for nm in sorted(set(nd)):
            if not str(nm).startswith("Glass"):
                continue
            m = h & np.isin(f, np.where(nd == nm)[0])
            if m.sum():
                per[str(nm)] = {"first_hits": int(m.sum()),
                                "backface_frac": round(float(bf[m].mean()), 4)}
        R["G4_holes"][k + "_glass_firsthit"] = per
    print("G4 holes:", json.dumps({k: v for k, v in R["G4_holes"].items()
                                   if not k.endswith("_glass_firsthit")}))
    print("   glazing first-hit backface fraction before:",
          json.dumps(R["G4_holes"]["before_glass_firsthit"]))
    print("   glazing first-hit backface fraction after :",
          json.dumps(R["G4_holes"]["after_glass_firsthit"]))

    # ---- G5 normals ----------------------------------------------------------
    R["G5_normals"] = {}
    for k, p in (("before", a.before), ("after", a.after)):
        g, b = gltf_json(p)
        off = 20 + struct.unpack("<I", b[12:16])[0]
        blen = struct.unpack("<I", b[off:off + 4])[0]
        binc = b[off + 8:off + 8 + blen]
        prims = miss = nonunit = 0
        for nd in g.get("nodes", []):
            if "mesh" not in nd:
                continue
            for pr in g["meshes"][nd["mesh"]]["primitives"]:
                prims += 1
                ai = pr["attributes"].get("NORMAL")
                if ai is None:
                    miss += 1; continue
                A = g["accessors"][ai]; BV = g["bufferViews"][A["bufferView"]]
                o = BV.get("byteOffset", 0) + A.get("byteOffset", 0)
                arr = np.frombuffer(binc, dtype=np.float32, count=A["count"] * 3,
                                    offset=o).reshape(-1, 3)
                L = np.linalg.norm(arr, axis=1)
                nonunit += int((np.abs(L - 1) > 1e-3).sum())
        R["G5_normals"][k] = {"primitives": prims, "missing_NORMAL": miss,
                              "non_unit_vectors": nonunit,
                              "extensionsUsed": g.get("extensionsUsed")}
    print("G5 normals:", json.dumps(R["G5_normals"]))

    # ---- G6 tyres ------------------------------------------------------------
    R["G6_tyres"] = {}
    for k, p in (("before", a.before), ("after", a.after)):
        g, _ = gltf_json(p)
        for m in g.get("materials", []):
            if (m.get("name") or "").lower().startswith("tyre") or \
               (m.get("name") or "").lower().startswith("tire"):
                R["G6_tyres"][k] = {"name": m["name"],
                                    "baseColorFactor": m.get("pbrMetallicRoughness", {}).get("baseColorFactor"),
                                    "textured": bool(m.get("pbrMetallicRoughness", {}).get("baseColorTexture"))}
    R["G6_tyres"]["note"] = ("baseColorFactor only. CLAUDE.md: a glTF tyre probe scored "
                             "0/8 recall against render ground truth -- a dark reading "
                             "rules out paint-over-rubber and flat-shell, and does NOT "
                             "clear the car of the per-corner render artefact.")
    print("G6 tyres:", json.dumps(R["G6_tyres"]))

    if a.json:
        json.dump(R, open(a.json, "w"), indent=1)
        print("wrote", a.json)


if __name__ == "__main__":
    main()
