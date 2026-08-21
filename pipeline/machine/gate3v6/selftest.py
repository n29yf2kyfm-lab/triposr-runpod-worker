#!/usr/bin/env python3
"""selftest.py -- NEGATIVE CONTROLS for every check in verify_front_gate.py.

"A checker that has never returned a failure is not a checker."  This project
has a documented arch-intersection test that was empty by construction and had
never once fired, and a wheel test that read back its own boundary value on 8
of 8 wheels.  So each check here is run twice: once on clean geometry, which
must PASS, and once on geometry with a deliberate defect injected, which must
FAIL.  A control is only `control_ok` when BOTH halves behave.

Every injected defect is removed by construction -- the meshes are built in
memory here and nothing is written into the builder's tree.
"""
import os
import tempfile

import numpy as np
import trimesh

import verify_front_gate as V


def _cube(sx=0.1, sy=0.1, sz=0.1, at=(0, 0, 0)):
    m = trimesh.creation.box(extents=(sx, sy, sz))
    m.apply_translation(at)
    return np.asarray(m.vertices, float), np.asarray(m.faces, np.int64)


def _plane(x, y0, y1, z0, z1, n=6):
    """A flat quad grid at constant x, facing -x."""
    ys = np.linspace(y0, y1, n)
    zs = np.linspace(z0, z1, n)
    ZZ, YY = np.meshgrid(zs, ys)
    Vt = np.stack([np.full(ZZ.size, x), YY.ravel(), ZZ.ravel()], 1)
    F = []
    for i in range(n - 1):
        for j in range(n - 1):
            a, b, c, d = i * n + j, i * n + j + 1, (i + 1) * n + j, (i + 1) * n + j + 1
            F += [[a, b, c], [b, d, c]]
    return Vt, np.asarray(F, np.int64)


def run_selftest():
    R = {}

    # ---------------------------------------------------------- 1 zero area
    Vc, Fc = _cube()
    clean = V.hygiene_one(Vc, Fc)
    Vb = np.vstack([Vc, Vc[0:1]])
    Fb = np.vstack([Fc, [[0, 0, len(Vc)]]])          # a genuinely zero-area tri
    bad = V.hygiene_one(Vb, Fb)
    R["zero_area_faces"] = {
        "clean": clean["zero_area_faces"], "injected": bad["zero_area_faces"],
        "injection": "one triangle with two coincident vertices",
        "control_ok": clean["zero_area_faces"] == 0 and bad["zero_area_faces"] >= 1}

    # --------------------------------------------------------- 2 duplicates
    Fd = np.vstack([Fc, Fc[3:4]])
    bad = V.hygiene_one(Vc, Fd)
    R["duplicate_faces"] = {
        "clean": clean["duplicate_faces"], "injected": bad["duplicate_faces"],
        "injection": "face 3 of a cube duplicated",
        "control_ok": clean["duplicate_faces"] == 0 and bad["duplicate_faces"] >= 1}

    # ----------------------------------------------------- 3 flipped normal
    Ff = Fc.copy()
    Ff[5] = Ff[5][::-1]
    bad = V.hygiene_one(Vc, Ff)
    R["flipped_normals"] = {
        "clean_winding_consistent": clean["winding_consistent"],
        "injected_winding_consistent": bad["winding_consistent"],
        "clean_inward_pct": clean.get("inward_facing_pct"),
        "injected_inward_pct": bad.get("inward_facing_pct"),
        "injection": "winding of one cube face reversed",
        "control_ok": bool(clean["winding_consistent"] and not bad["winding_consistent"])}

    # ---- 3b whole-part inversion (winding stays CONSISTENT) --------------
    # Flipping EVERY face of a closed part leaves the winding self-consistent,
    # so the winding test cannot see it. is_volume / volume sign can.
    Fi = Fc[:, ::-1].copy()
    inv = V.hygiene_one(Vc, Fi)
    R["whole_part_inverted"] = {
        "clean_is_volume": clean.get("is_volume"),
        "inverted_is_volume": inv.get("is_volume"),
        "inverted_winding_consistent": inv["winding_consistent"],
        "inverted_volume_sign_negative": inv.get("volume_sign_negative"),
        "injection": "every face of a closed cube reversed",
        "control_ok": bool(clean.get("is_volume") and not inv.get("is_volume")
                           and inv["winding_consistent"])}

    # ------------------------------------------------------- 4 non-manifold
    Vn = np.vstack([Vc, [[0.2, 0.0, 0.0]]])
    Fn = np.vstack([Fc, [[Fc[0][0], Fc[0][1], len(Vc)]]])   # 3rd face on an edge
    bad = V.hygiene_one(Vn, Fn)
    R["nonmanifold_edges"] = {
        "clean": clean["nonmanifold_edges"], "injected": bad["nonmanifold_edges"],
        "injection": "an extra triangle attached to an existing cube edge",
        "control_ok": clean["nonmanifold_edges"] == 0 and bad["nonmanifold_edges"] >= 1}

    # ---------------------------------------------------- 5 loose geometry
    V2, F2 = _cube(0.01, 0.01, 0.01, at=(0.6, 0, 0))
    Vl = np.vstack([Vc, V2])
    Fl = np.vstack([Fc, F2 + len(Vc)])
    bad = V.hygiene_one(Vl, Fl)
    R["loose_components"] = {
        "clean": clean["components"], "injected": bad["components"],
        "injected_largest_pct": bad["largest_component_pct"],
        "injection": "a detached 10 mm cube 600 mm away",
        "control_ok": clean["components"] == 1 and bad["components"] == 2}

    # ---------------------------------------------------- 6 negative scale
    T = np.eye(4)
    ok = V.hygiene_one(Vc, Fc, T)
    T2 = np.eye(4)
    T2[2, 2] = -1.0
    bad = V.hygiene_one(Vc, Fc, T2)
    R["negative_scale"] = {
        "clean": ok["negative_scale"], "injected": bad["negative_scale"],
        "clean_transform_identity": ok["transform_identity"],
        "injected_transform_identity": bad["transform_identity"],
        "injection": "node transform with scale z = -1",
        "control_ok": (not ok["negative_scale"]) and bad["negative_scale"]}

    # ------------------------------------------------ 7 self-intersection
    Vs = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0],          # tri in z=0
                   [.4, .1, -.5], [.4, .1, .5], [.4, .8, 0]], float)
    Fs = np.array([[0, 1, 2], [3, 4, 5]], np.int64)
    hit = V.self_intersections(Vs, Fs)
    Vs2 = Vs.copy()
    Vs2[3:, 0] += 3.0                                        # move it away
    miss = V.self_intersections(Vs2, Fs)
    R["self_intersection"] = {
        "crossing_pair_detected": hit["intersecting_pairs"],
        "separated_pair_detected": miss["intersecting_pairs"],
        "injection": "two triangles that pierce each other, then moved 3 m apart",
        "control_ok": hit["intersecting_pairs"] == 1 and miss["intersecting_pairs"] == 0}

    # -------------------------------------------- 8 inter-object + clearance
    A = _cube(0.1, 0.1, 0.1, at=(0, 0, 0))
    B_over = _cube(0.1, 0.1, 0.1, at=(0.05, 0, 0))           # overlapping
    B_gap = _cube(0.1, 0.1, 0.1, at=(0.105, 0, 0))           # 5.000 mm gap
    over = V.pair_intersection(A[0], A[1], B_over[0], B_over[1])
    apart = V.pair_intersection(A[0], A[1], B_gap[0], B_gap[1])
    gap = V.surface_gap_mm(A[0], A[1], B_gap[0], B_gap[1], n=6000)
    R["inter_object_intersection"] = {
        "overlapping_pairs": over["intersecting_pairs"],
        "separated_pairs": apart["intersecting_pairs"],
        "injection": "two 100 mm cubes overlapped by 50 mm, then set 5 mm apart",
        "control_ok": over["intersecting_pairs"] > 0 and apart["intersecting_pairs"] == 0}
    R["clearance_mm"] = {
        "measured_gap_mm": gap["gap_mm"], "true_gap_mm": 5.0,
        "error_mm": round(abs(gap["gap_mm"] - 5.0), 4),
        "note": "known 5.000 mm gap between two cubes; surface sampling",
        "control_ok": abs(gap["gap_mm"] - 5.0) < 0.30}

    # ---- 8b clearance on NON-AXIS-ALIGNED geometry ----------------------
    # On the real car several measured gaps came out numerically equal to the
    # AABB separation (5.00 mm, 55.00 mm).  That is correct for axis-aligned
    # slats -- and it is also exactly what a checker that secretly reads back
    # its own bounding boxes would print.  This control removes the doubt: two
    # boxes rotated to an arbitrary orientation, face-to-face, with a known
    # 7.300 mm gap that no axis-aligned box test can produce.
    ang = np.array([0.37, -0.62, 0.21])
    Rm = trimesh.transformations.euler_matrix(*ang)[:3, :3]
    bxa = trimesh.creation.box(extents=(0.12, 0.08, 0.06))
    Va = np.asarray(bxa.vertices) @ Rm.T
    d = 0.12 + 0.0073
    Vb = (np.asarray(bxa.vertices) + np.array([d, 0, 0])) @ Rm.T
    Fq = np.asarray(bxa.faces, np.int64)
    rot = V.surface_gap_mm(Va, Fq, Vb, Fq, n=20000)
    rot_aabb = float(np.maximum(Va.min(0) - Vb.max(0), Vb.min(0) - Va.max(0)).max() * 1000)
    R["clearance_mm_rotated"] = {
        "measured_gap_mm": rot["gap_mm"], "true_gap_mm": 7.3,
        "aabb_separation_mm": round(rot_aabb, 3),
        "error_mm": round(abs(rot["gap_mm"] - 7.3), 4),
        "note": ("two boxes rotated by euler(0.37,-0.62,0.21), 7.300 mm apart "
                 "face-to-face; the AABB separation is a DIFFERENT number, so a "
                 "bounding-box read-back cannot produce the right answer"),
        "control_ok": abs(rot["gap_mm"] - 7.3) < 0.35}

    # ------------------------------------------------------- 9 symmetry
    L = _cube(0.2, 0.1, 0.1, at=(0, 0.8, -0.4))
    Rr = (L[0].copy(), L[1].copy())
    Rr[0][:, 2] = -Rr[0][:, 2]                              # exact mirror
    exact = V.mirror_deviation_mm(L[0], L[1], Rr[0], Rr[1], 0.0, n=6000)
    Rs = (Rr[0].copy(), Rr[1].copy())
    Rs[0][:, 2] += 0.005                                    # 5 mm off
    off5 = V.mirror_deviation_mm(L[0], L[1], Rs[0], Rs[1], 0.0, n=6000)
    R["symmetry_probe"] = {
        "exact_mirror_max_mm": exact["max_mm"], "exact_mirror_median_mm": exact["median_mm"],
        "exact_mirror_centroid_delta_mm": exact["centroid_delta_mm"],
        "shifted_5mm_median_mm": off5["median_mm"], "shifted_5mm_max_mm": off5["max_mm"],
        "shifted_5mm_centroid_delta_mm": off5["centroid_delta_mm"],
        "injection": "an exact mirrored copy (must read 0.0000), then displaced 5 mm in z",
        "finding": ("the MEDIAN point-to-surface distance is blind to a rigid slide "
                    "ALONG the surface -- it read 0.0000 on the 5 mm displaced box. "
                    "max_mm and centroid_delta_mm both read 5.0, so those are the "
                    "figures the gate is judged on."),
        "control_ok": (exact["max_mm"] < 0.001
                       and abs(max(abs(v) for v in exact["centroid_delta_mm"])) < 0.001
                       and abs(off5["max_mm"] - 5.0) < 0.30
                       and abs(off5["centroid_delta_mm"][2] - 5.0) < 0.05)}

    # --------------------------------------------------- 10 centre offset
    C = _cube(0.05, 0.05, 0.05, at=(0, 0.8, 0.0))
    on = V.centre_offset_mm(C[0], C[1], 0.0)
    C2 = (C[0].copy(), C[1])
    C2[0][:, 2] += 0.003
    off = V.centre_offset_mm(C2[0], C2[1], 0.0)
    R["centreline_offset"] = {
        "centred_mm": on["bbox_mid_z_offset_mm"], "shifted_mm": off["bbox_mid_z_offset_mm"],
        "injection": "a centred badge displaced 3 mm off the centreline",
        "control_ok": abs(on["bbox_mid_z_offset_mm"]) < 1e-6
                      and abs(off["bbox_mid_z_offset_mm"] - 3.0) < 0.01}

    # ------------------------------------------- 11 hidden fascia detector
    tmp = tempfile.mkdtemp(prefix="g3v6st_")
    res = {}
    for tag, hidden in (("melt_hidden_behind_part", True), ("melt_deleted", False)):
        sc = trimesh.Scene()
        # a constructed component across the front
        pv, pf = _plane(-2.10, 0.60, 0.90, -0.30, 0.30, n=10)
        sc.add_geometry(trimesh.Trimesh(pv, pf, process=False), node_name="Bumper_Front",
                        geom_name="Bumper_Front")
        # the shell: a body surface elsewhere so the file has a shell at all
        bv, bf = _plane(-1.50, 0.60, 0.90, 0.40, 0.80, n=6)
        sc.add_geometry(trimesh.Trimesh(bv, bf, process=False), node_name="carpaint",
                        geom_name="carpaint")
        if hidden:
            # SAME extent as the component: a smaller hidden plane only covers
            # part of the component's ray footprint, and the first run of this
            # control read 80.84% for exactly that reason (0.26*0.56 / 0.30*0.60
            # = 0.809). The probe was right; the control was badly built.
            hv, hf = _plane(-2.08, 0.60, 0.90, -0.30, 0.30, n=10)   # 20 mm behind
            sc.add_geometry(trimesh.Trimesh(hv, hf, process=False), node_name="interior",
                            geom_name="interior")
        p = os.path.join(tmp, f"{tag}.glb")
        sc.export(p)
        car = V.Car(p)
        f = V.check_hidden_fascia(car)
        res[tag] = {"rays_component_first": f["rays_component_first"],
                    "nested_pct": f["nested_pct_of_component_rays"],
                    "nested_depth_mm": f["nested_depth_mm"],
                    "hidden_owners": f.get("hidden_surface_owners")}
        os.remove(p)
    R["hidden_fascia_probe"] = {
        **res,
        "injection": "a shell plane hidden 20 mm behind a constructed part, then removed",
        "control_ok": (res["melt_hidden_behind_part"]["nested_pct"] > 90
                       and res["melt_deleted"]["nested_pct"] == 0)}

    # ---- 11b the RENAMED-MELT attack against the fascia probe -------------
    # The hidden plane is put in a node called Splitter_Front, so a NAME-based
    # rule sees two "constructed components" and reports nothing behind
    # anything. The provenance path, which tags each triangle by whether it
    # exists in V0, must still catch it.
    scA = trimesh.Scene()
    pv2, pf2 = _plane(-2.10, 0.60, 0.90, -0.30, 0.30, n=10)
    mA = trimesh.Trimesh(pv2, pf2, process=False)
    _ = mA.vertex_normals
    scA.add_geometry(mA, node_name="Bumper_Front", geom_name="Bumper_Front")
    hv2, hf2 = _plane(-2.08, 0.60, 0.90, -0.30, 0.30, n=10)
    mH = trimesh.Trimesh(hv2, hf2, process=False)
    _ = mH.vertex_normals
    scA.add_geometry(mH, node_name="Splitter_Front", geom_name="Splitter_Front")
    pA = os.path.join(tmp, "renamed.glb")
    scA.export(pA)
    scV = trimesh.Scene()
    mV = trimesh.Trimesh(hv2, hf2, process=False)
    _ = mV.vertex_normals
    scV.add_geometry(mV, node_name="carpaint", geom_name="carpaint")
    pV = os.path.join(tmp, "renamed_v0.glb")
    scV.export(pV)
    fr = V.check_hidden_fascia(V.Car(pA), v0=V.Car(pV))
    R["fascia_probe_vs_renamed_melt"] = {
        "name_based_nested_pct": fr["nested_pct_of_component_rays"],
        "provenance_based_pct": fr["by_provenance"]["pct"],
        "provenance_shallow_pct": fr["by_provenance"]["shallow_pct"],
        "faces_matching_V0": fr["by_provenance"]["faces_matching_V0"],
        "injection": ("the original surface hidden 20 mm behind a new part AND "
                      "renamed to Splitter_Front, so no name-based rule can see it"),
        "control_ok": bool(fr["nested_pct_of_component_rays"] == 0
                           and fr["by_provenance"]["pct"] > 90)}
    for q in (pA, pV):
        os.remove(q)

    # --------------------------------------------------- 12 v0 residue test
    sc0 = trimesh.Scene()
    fv, ff = _plane(-2.10, 0.60, 0.90, -0.30, 0.30, n=12)
    sc0.add_geometry(trimesh.Trimesh(fv, ff, process=False), node_name="carpaint",
                     geom_name="carpaint")
    p0 = os.path.join(tmp, "v0.glb")
    sc0.export(p0)
    sc1 = trimesh.Scene()
    keep = np.asarray(ff)[fv[np.asarray(ff)].mean(1)[:, 2] > 0.0]     # delete half
    sc1.add_geometry(trimesh.Trimesh(fv, keep, process=False), node_name="carpaint",
                     geom_name="carpaint")
    p1 = os.path.join(tmp, "v1.glb")
    sc1.export(p1)
    same = V.v0_residue(V.Car(p0), V.Car(p0))
    cut = V.v0_residue(V.Car(p1), V.Car(p0))
    R["v0_residue"] = {
        "identical_file_pct": same["retained_pct_total"],
        "half_deleted_pct": cut["retained_pct_total"],
        "injection": "half the original front faces deleted",
        "control_ok": same["retained_pct_total"] > 99.5 and cut["retained_pct_total"] < 60}
    _keep_p0 = p0

    # ------------------------------- 12b relocation + origin audit --------
    # The rename-not-remove attack: the same original faces, moved into a node
    # called Bumper_Front. A per-LABEL residue test would score that as
    # deletion. The global match must still see 100% retained, flag them all as
    # relocated, and the origin audit must call the node INHERITED_ORIGINAL.
    sc4 = trimesh.Scene()
    mv = trimesh.Trimesh(fv, np.asarray(ff), process=False)
    _ = mv.vertex_normals
    sc4.add_geometry(mv, node_name="Bumper_Front", geom_name="Bumper_Front")
    p4 = os.path.join(tmp, "reloc.glb")
    sc4.export(p4)
    v0c = V.Car(p0) if os.path.exists(p0) else None
    sc0b = trimesh.Scene()
    m0b = trimesh.Trimesh(fv, np.asarray(ff), process=False)
    _ = m0b.vertex_normals
    sc0b.add_geometry(m0b, node_name="carpaint", geom_name="carpaint")
    p0b = os.path.join(tmp, "v0b.glb")
    sc0b.export(p0b)
    car_r, car_0 = V.Car(p4), V.Car(p0b)
    rel = V.v0_residue(car_r, car_0)
    oa_inherit = V.origin_audit(car_r, car_0)["Bumper_Front"]
    cb = trimesh.creation.box(extents=(0.05, 0.05, 0.05))
    cb.apply_translation((-2.10, 0.75, 0.0))
    _ = cb.vertex_normals
    sc5 = trimesh.Scene()
    sc5.add_geometry(cb, node_name="Badge", geom_name="Badge")
    p5 = os.path.join(tmp, "new.glb")
    sc5.export(p5)
    oa_new = V.origin_audit(V.Car(p5), car_0)["Badge"]
    R["relocation_and_origin"] = {
        "relocated_retained_pct": rel["retained_pct_total"],
        "relocated_count": rel["relocated_total"],
        "survivors_by_node": rel["survivors_by_holding_node"],
        "inherited_node_verdict": oa_inherit["verdict"],
        "inherited_node_pct_original": oa_inherit["pct_original_geometry"],
        "new_node_verdict": oa_new["verdict"],
        "new_node_pct_original": oa_new["pct_original_geometry"],
        "injection": ("the original faces moved verbatim into a node named "
                      "Bumper_Front, and separately a genuinely new cube"),
        "control_ok": bool(rel["retained_pct_total"] > 99.5
                           and rel["relocated_total"] == rel["retained_total"]
                           and oa_inherit["verdict"] == "INHERITED_ORIGINAL"
                           and oa_new["verdict"] == "CONSTRUCTED")}
    for q in (p4, p5, p0b):
        os.remove(q)

    # ----------------------------------------------------- 13 hierarchy
    sc2 = trimesh.Scene()
    bx = trimesh.creation.box(extents=(0.1, 0.1, 0.1))
    # trimesh's GLB exporter writes NORMAL only when the normals have been
    # realised -- the documented "submesh exports drop NORMAL accessors" trap,
    # which this control reproduced on its own clean case the first time it ran.
    _ = bx.vertex_normals
    sc2.add_geometry(bx, node_name="Badge", geom_name="Badge")
    p2 = os.path.join(tmp, "h.glb")
    sc2.export(p2)
    car2 = V.Car(p2)
    good = V.check_hierarchy(car2, ["Badge"])
    missing = V.check_hierarchy(car2, ["Badge", "Splitter_Front"])
    sc3 = trimesh.Scene()
    bx2 = trimesh.creation.box(extents=(0.1, 0.1, 0.1))
    sc3.add_geometry(bx2, node_name="Badge", geom_name="Badge")   # no NORMAL
    p3 = os.path.join(tmp, "hn.glb")
    sc3.export(p3)
    nonorm = V.check_hierarchy(V.Car(p3), ["Badge"])
    os.remove(p3)
    R["hierarchy_probe"] = {
        "present_when_present": list(good["present"]), "pass_when_present": good["pass"],
        "missing_when_absent": missing["missing"], "pass_when_absent": missing["pass"],
        "normals_present_detected": good["present"]["Badge"]["has_NORMAL"],
        "normals_absent_detected": nonorm["present"]["Badge"]["has_NORMAL"],
        "pass_when_normals_absent": nonorm["pass"],
        "injection": ("ask for a component the file does not contain; and export "
                      "the same component with the NORMAL accessor stripped"),
        "control_ok": bool(good["pass"] and (not missing["pass"])
                           and missing["missing"] == ["Splitter_Front"]
                           and good["present"]["Badge"]["has_NORMAL"]
                           and not nonorm["present"]["Badge"]["has_NORMAL"]
                           and not nonorm["pass"])}
    os.remove(p2)
    for q in (p0, p1):
        if os.path.exists(q):
            os.remove(q)
    try:
        os.rmdir(tmp)
    except OSError:
        pass

    R["_summary"] = {
        "controls": len([k for k in R if not k.startswith("_")]),
        "failed": [k for k, v in R.items()
                   if isinstance(v, dict) and v.get("control_ok") is False]}
    return R


if __name__ == "__main__":
    import json
    import sys
    out = run_selftest()
    print(json.dumps(out, indent=1, default=V.jdefault))
    sys.exit(1 if out["_summary"]["failed"] else 0)
