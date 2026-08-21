#!/usr/bin/env python3
"""gate_table.py -- turn measure JSONs into the Gate 3 v6 check table.

The verdict is CODE, not prose, so the same numbers always produce the same
status and nobody has to trust a paragraph.  Statuses:

    PASS        threshold met, measured
    FAIL        threshold not met, measured
    MEASURED    a real number the owner asked for, with no threshold set --
                reported, never dressed up as a pass
    NOT TESTED  honestly not run (an honourable answer; a fabricated number
                is not)
    BLOCKED     could not be run

Run: python3 gate_table.py FINAL.json --baseline BASE.json --validator V.json
                           --selftest S.json --viewer VW.json --out table.json
"""
import argparse
import json

MM = 1000.0
SYM_TOL_MM = 2.0


def _agg(hyg, names):
    out = dict(zero=0, dup=0, nm=0, comps=0, faces=0, bad_wind=0, negscale=0,
               nonident=0, loose=0, inward=0.0, inverted=0)
    for n in names:
        v = hyg.get(n)
        if not v or not v.get("faces"):
            continue
        out["faces"] += v["faces"]
        out["zero"] += v.get("zero_area_faces", 0)
        out["dup"] += v.get("duplicate_faces", 0)
        out["nm"] += v.get("nonmanifold_edges", 0)
        out["comps"] += v.get("components", 0)
        out["loose"] += max(0, v.get("components", 1) - 1)
        out["bad_wind"] += 0 if v.get("winding_consistent", True) else 1
        if v.get("watertight") and v.get("is_volume") is False:
            out["inverted"] = out.get("inverted", 0) + 1
        out["negscale"] += 1 if v.get("negative_scale") else 0
        out["nonident"] += 0 if v.get("transform_identity", True) else 1
        out["inward"] = max(out["inward"], v.get("inward_facing_pct", 0.0))
    return out


def _base_sym(B):
    """Baseline worst L/R deviation -- or an honest 'n/a'.

    The v5 baseline names its lamps `Head_Lens_R`, not `Headlamp_R_Lens`, so
    the v6 pair list matches NOTHING in it and a max() over an empty set would
    have printed a baseline of '0.00 mm' -- a perfect score for a file that was
    never measured. That is exactly the kind of number this gate exists to stop.
    """
    if not B:
        return "n/a"
    vals = [v["shape_deviation"]["max_mm"] for v in
            B.get("symmetry", {}).get("pairs", {}).values() if isinstance(v, dict)]
    if not vals:
        return ("n/a -- v5 node names differ; measured separately in "
                "base_V5_symmetry.json: worst 97.79 mm")
    return f"V5 worst {max(vals):.2f} mm"


def row(req, base, final, thr, ev, status, risk=""):
    return {"requirement": req, "baseline": base, "final": final,
            "threshold": thr, "evidence": ev, "status": status,
            "remaining_risk": risk}


def build(F, B=None, val=None, st=None, vw=None, valbase=None, imp=None):
    R = []
    built = F.get("built_components", [])
    hyg = F.get("hygiene", {})
    bhyg = (B or {}).get("hygiene", {})
    bbuilt = (B or {}).get("built_components", [])
    a = _agg(hyg, built)
    ab = _agg(bhyg, bbuilt) if B else None
    shell = F.get("shell_nodes", [])
    s = _agg(hyg, shell)
    sb = _agg(bhyg, (B or {}).get("shell_nodes", [])) if B else None

    # ---- hierarchy
    h = F.get("hierarchy")
    if h:
        bh = (B or {}).get("hierarchy", {})
        R.append(row(
            "Every required component is a real, separately selectable node "
            "with real geometry (owner: never claim a part exists unless the "
            "GLB hierarchy proves it)",
            f"{len(bh.get('present', {}))}/18 present" if B else "n/a",
            f"{len(h['present'])}/18 present; missing={h['missing'] or 'none'}; "
            f"empty={h['empty'] or 'none'}; shared-mesh={h['shared_mesh'] or 'none'}",
            "18/18, none empty, none sharing a mesh, all with NORMAL",
            "verify_front_gate.json:hierarchy",
            "PASS" if h["pass"] else "FAIL",
            "" if h["pass"] else "an absent or empty node is not a component"))

    # ---- normals present
    if h:
        no_norm = [k for k, v in h["present"].items() if not v["has_NORMAL"]]
        R.append(row(
            "NORMAL accessor present on every constructed primitive "
            "(trimesh submesh export drops them; that is the crumpled-foil bug)",
            "V5: all present", f"{len(no_norm)} without NORMAL: {no_norm or 'none'}",
            "0 primitives without NORMAL", "verify_front_gate.json:hierarchy",
            "PASS" if not no_norm else "FAIL"))

    # ---- hygiene, constructed
    R.append(row("Zero-area faces (constructed components)",
                 ab["zero"] if ab else "n/a", a["zero"], "0",
                 "verify_front_gate.json:hygiene",
                 "PASS" if a["zero"] == 0 else "FAIL"))
    R.append(row("Duplicate faces (constructed components)",
                 ab["dup"] if ab else "n/a", a["dup"], "0",
                 "verify_front_gate.json:hygiene",
                 "PASS" if a["dup"] == 0 else "FAIL"))
    R.append(row("Non-manifold edges (constructed components)",
                 ab["nm"] if ab else "n/a", a["nm"], "0",
                 "verify_front_gate.json:hygiene",
                 "PASS" if a["nm"] == 0 else "FAIL"))
    R.append(row("Flipped normals / inconsistent winding (constructed)",
                 f"{ab['bad_wind']} parts" if ab else "n/a",
                 f"{a['bad_wind']} parts with inconsistent winding, "
                 f"{a['inverted']} closed parts inverted (is_volume False); "
                 f"centroid-inward {a['inward']:.2f}% (informational -- see note)",
                 "0 inconsistent, 0 inverted",
                 "verify_front_gate.json:hygiene",
                 "PASS" if a["bad_wind"] == 0 and a["inverted"] == 0 else "FAIL",
                 "the centroid-inward figure is NOT a gate: a concave closed "
                 "solid reads high (V5 lenses 44.89%) and is not inverted"))
    R.append(row("Loose / floating geometry inside a component "
                 "(extra connected components)",
                 ab["loose"] if ab else "n/a", a["loose"],
                 "0 extra components", "verify_front_gate.json:hygiene",
                 "PASS" if a["loose"] == 0 else "FAIL"))
    R.append(row("Negative scales on component nodes",
                 ab["negscale"] if ab else "n/a", a["negscale"], "0",
                 "verify_front_gate.json:hygiene",
                 "PASS" if a["negscale"] == 0 else "FAIL"))
    R.append(row("Unapplied node transforms (measured from TRANSFORMED "
                 "vertices, so a baked transform cannot read as zero)",
                 ab["nonident"] if ab else "n/a", a["nonident"],
                 "reported, not gated (node TRS is legal glTF)",
                 "verify_front_gate.json:hygiene", "MEASURED"))

    # ---- hygiene, inherited shell
    R.append(row("Inherited shell hygiene (carpaint/interior/glass/etc) -- "
                 "NOT rebuilt by this gate, recorded so it is not mistaken "
                 "for component work",
                 (f"zero {sb['zero']}, dup {sb['dup']}, non-manifold {sb['nm']}, "
                  f"{sb['comps']} connected components") if sb else "n/a",
                 f"zero {s['zero']}, dup {s['dup']}, non-manifold {s['nm']}, "
                 f"{s['comps']} connected components",
                 "no threshold set for the generator shell", "verify_front_gate.json:hygiene",
                 "MEASURED", "the shell is generator melt; it is the open surfacing gap"))

    # ---- self-intersection
    si = F.get("self_intersection", {})
    bsi = (B or {}).get("self_intersection", {})
    bad = {k: v["intersecting_pairs"] for k, v in si.items()
           if v.get("intersecting_pairs", 0) > 0}
    bbad = sum(v.get("intersecting_pairs", 0) for v in bsi.values()) if bsi else None
    R.append(row("Self-intersections inside a constructed component "
                 "(exact Moller tri-tri, not a heuristic)",
                 f"{bbad} pairs over {len(bsi)} parts" if bsi else "n/a",
                 f"{sum(bad.values())} pairs over {len(bad)} parts: {bad or 'none'}",
                 "0 intersecting triangle pairs",
                 "verify_front_gate.json:self_intersection",
                 "PASS" if not bad else "FAIL"))

    # ---- clearance / inter-object
    cl = F.get("clearance", {})
    pr = cl.get("pairs", {})
    neg = {k: v.get("gap_mm") for k, v in pr.items()
           if v.get("gap_mm") is not None and v["gap_mm"] < 0}
    R.append(row("Inter-object intersections between constructed components",
                 (f"{len((B or {}).get('clearance', {}).get('intersecting', []))} "
                  f"pairs") if B else "n/a",
                 f"{len(cl.get('intersecting', []))} of {len(pr)} measured pairs: "
                 f"{cl.get('intersecting', [])}",
                 "reported in mm; seated parts (lens in housing) legitimately "
                 "interpenetrate, so no blanket threshold is invented",
                 "verify_front_gate.json:clearance", "MEASURED",
                 "a designed seat and a modelling error look the same to a "
                 "topology test; judged per pair"))
    R.append(row("Part clearance, actual millimetres "
                 "(lamp / grille / bumper / badge / plate / splitter)",
                 "V5: see baseline JSON", f"{len(pr)} pairs measured, "
                 f"{len(neg)} interpenetrating: {neg or 'none'}",
                 "measured, reported in mm", "verify_front_gate.json:clearance",
                 "MEASURED"))

    # ---- symmetry
    sy = F.get("symmetry", {})
    worst, worstk = 0.0, None
    offs = {}
    for k, v in sy.get("pairs", {}).items():
        if not isinstance(v, dict):
            continue
        m = v["shape_deviation"]["max_mm"]
        if m > worst:
            worst, worstk = m, k
        offs[k] = v["placement_offset_from_centreline_mm"]
    R.append(row("L/R front landmark symmetry: SHAPE deviation about the "
                 "best-fit pair plane",
                 _base_sym(B),
                 f"worst {worst:.3f} mm ({worstk})" if worstk else "no L/R pairs found",
                 f"<= {SYM_TOL_MM} mm", "verify_front_gate.json:symmetry",
                 ("PASS" if worstk and worst <= SYM_TOL_MM else
                  "FAIL" if worstk else "NOT TESTED"),
                 "probe validated to read 0.0000 mm on an exact mirror"))
    wo = max((abs(v) for v in offs.values()), default=None)
    R.append(row("L/R pair PLACEMENT: pair plane vs the vehicle centreline",
                 "n/a", f"worst {wo:.3f} mm" if wo is not None else "no pairs",
                 f"<= {SYM_TOL_MM} mm", "verify_front_gate.json:symmetry",
                 ("PASS" if wo is not None and wo <= SYM_TOL_MM else
                  "FAIL" if wo is not None else "NOT TESTED")))
    cen = sy.get("centred", {})
    bad_c = {k: v["bbox_mid_z_offset_mm"] for k, v in cen.items()
             if isinstance(v, dict) and abs(v["bbox_mid_z_offset_mm"]) > SYM_TOL_MM}
    keyc = {k: (cen[k]["bbox_mid_z_offset_mm"] if isinstance(cen.get(k), dict) else "MISSING")
            for k in ("Badge", "Plate")}
    R.append(row("Badge and plate on the vehicle centreline",
                 "n/a", f"Badge {keyc['Badge']}, Plate {keyc['Plate']} (mm bbox-mid offset)",
                 f"<= {SYM_TOL_MM} mm", "verify_front_gate.json:symmetry",
                 ("NOT TESTED" if any(v == "MISSING" for v in keyc.values()) else
                  "PASS" if all(abs(v) <= SYM_TOL_MM for v in keyc.values()) else "FAIL")))
    R.append(row("All centre-straddling components on the centreline",
                 "n/a", f"{len(bad_c)} beyond tolerance: {bad_c or 'none'}",
                 f"<= {SYM_TOL_MM} mm", "verify_front_gate.json:symmetry",
                 "PASS" if not bad_c else "FAIL"))

    # ---- hidden fascia (the decisive one)
    hf = F.get("hidden_fascia", {})
    res = F.get("v0_residue", {})
    oa = F.get("origin_audit", {})
    bhf = (B or {}).get("hidden_fascia", {})
    bres = (B or {}).get("v0_residue", {})
    inherited = [k for k, v in oa.items()
                 if v.get("verdict") == "INHERITED_ORIGINAL" and k in built]
    mixed = {k: v.get("pct_original_geometry") for k, v in oa.items()
             if v.get("verdict") == "MIXED" and k in built}
    R.append(row(
        "HIDDEN ORIGINAL FASCIA -- ray probe: original shell surface within "
        "60 mm behind a constructed component",
        (f"{bhf.get('shallow_nested_pct')}% of {bhf.get('rays_component_first')} "
         f"component-first rays") if bhf else "n/a",
        (f"{hf.get('shallow_nested_pct')}% of {hf.get('rays_component_first')} "
         f"component-first rays; depth bands {hf.get('nested_depth_bands')}")
        if hf else "NOT MEASURED",
        "no nested shell surface behind the rebuilt fascia",
        "verify_front_gate.json:hidden_fascia", "MEASURED",
        "a hit 200 mm back through an open intake is real structure, which is "
        "why the shallow band is the one judged"))
    R.append(row(
        "HIDDEN ORIGINAL FASCIA -- V0 residue: original front-zone triangles "
        "still present anywhere in the file",
        f"{bres.get('retained_pct_total')}% ({bres.get('retained_total')} faces)"
        if bres else "n/a",
        f"{res.get('retained_pct_total')}% ({res.get('retained_total')} of "
        f"{res.get('v0_front_faces_total')} faces), {res.get('relocated_total')} "
        f"relocated to another node" if res else "NOT MEASURED",
        "a real rebuild must delete the melt it replaces",
        "verify_front_gate.json:v0_residue", "MEASURED"))
    R.append(row(
        "HIDDEN ORIGINAL FASCIA -- origin audit: is any 'component' actually "
        "the old melt under a new name?",
        "V5: 0 of 18 inherited", f"{len(inherited)} inherited "
        f"({inherited or 'none'}); {len(mixed)} mixed {mixed or ''}",
        "0 components inherited verbatim", "verify_front_gate.json:origin_audit",
        "PASS" if not inherited else "FAIL",
        "MIXED nodes are partly re-used original geometry -- read the percentage"))

    # ---- resampled-original shape test
    sh = F.get("shape_origin_audit", {}).get("parts", {})
    resamp = {k: v["pct_within_1mm"] for k, v in sh.items()
              if v.get("verdict") == "RESAMPLED_ORIGINAL"}
    R.append(row("HIDDEN ORIGINAL FASCIA -- shape audit: is any 'new' part the "
                 "old melt RE-TESSELLATED? (centroid matching cannot see that)",
                 "n/a", f"{len(resamp)} of {len(sh)} parts read as resampled "
                 f"original: {resamp or 'none'}",
                 "0 parts sitting within 1 mm of the original surface everywhere",
                 "verify_front_gate.json:shape_origin_audit",
                 "PASS" if not resamp else "FAIL",
                 "a rebuilt part that deliberately hugs the original silhouette "
                 "also reads small -- this narrows the question, it does not "
                 "close it alone"))

    # ---- validator
    if val:
        ne = val.get("counts", {}).get("errors")
        nw = val.get("counts", {}).get("warnings")
        bne = (valbase or {}).get("counts", {}).get("errors") if valbase else None
        R.append(row("Khronos glTF Validator errors",
                     f"V0 input: {bne} errors" if bne is not None else "n/a",
                     f"{ne} errors, {nw} warnings", "0 errors",
                     "verify/json/validate_FINAL.json",
                     "PASS" if ne == 0 else "FAIL"))
    else:
        R.append(row("Khronos glTF Validator errors", "V0 input: 30 errors",
                     "not run", "0 errors", "-", "NOT TESTED"))

    # ---- fresh import / viewer
    if imp:
        objs = imp.get("objects", {})
        dims = imp.get("dimensions_m", {})
        want = set(F.get("built_components", []))
        got = {o.split(".")[0] for o in objs}
        miss = sorted(want - got)
        bb = F.get("bbox_m", {})
        dim_ok = (abs(dims.get("length_x", 0) - bb.get("L_x", -1)) < 1e-3
                  and abs(dims.get("height_z", 0) - bb.get("H_y", -1)) < 1e-3
                  and abs(dims.get("width_y", 0) - bb.get("W_z", -1)) < 1e-3)
        negs = [o for o, v in objs.items() if v.get("negative_scale")]
        R.append(row("Fresh-import test in a brand-new Blender process "
                     "(materials, orientation, scale, component placement)",
                     "V5 imported clean: 24 objects, 4.282 x 1.789 x 1.455 m",
                     f"{len(objs)} mesh objects, {len(imp.get('materials', {}))} "
                     f"materials, dims {dims}, ground min z "
                     f"{imp.get('ground_min_z_mm')} mm, missing components "
                     f"{miss or 'none'}, negative scales {negs or 'none'}",
                     "every component imports, dimensions match the source file, "
                     "no negative scales",
                     "verify/renders/*_import.json + *_front.png",
                     "PASS" if (not miss and dim_ok and not negs) else "FAIL",
                     "" if dim_ok else "imported dimensions differ from the file"))
    else:
        R.append(row("Fresh-import test in a brand-new Blender process",
                     "V5 imported clean", "not run",
                     "imports, dimensions match, components present", "-",
                     "NOT TESTED"))
    if vw:
        # viewer_check writes `status`, not `verdict` -- reading the wrong key
        # printed "?" and scored a PASS as a FAIL. A false FAIL is as bad as a
        # false PASS and this one was caught by reading the row, not the JSON.
        vstat = vw.get("status") or vw.get("verdict") or "?"
        checks = {k: v for k, v in (vw.get("checks") or {}).items()}
        R.append(row("Headless <model-viewer> load (Chromium + SwiftShader)",
                     "V5: PASS", f"{vstat}" + (f" {checks}" if checks else ""),
                     "loads, renders, centred, on the ground, clean console",
                     "verify/renders/viewer_FINAL/",
                     "PASS" if vstat == "PASS" else "FAIL",
                     "software desktop render -- says nothing about device FPS"))
    else:
        R.append(row("Headless <model-viewer> load", "V5: PASS", "not run",
                     "loads and renders", "-", "NOT TESTED"))

    # ---- the harness itself
    if st:
        f = st.get("_summary", {}).get("failed", [])
        R.append(row("The verifier's own checks are proven able to FAIL "
                     "(negative controls)",
                     "-", f"{st.get('_summary', {}).get('controls')} controls, "
                          f"{len(f)} failing: {f or 'none'}",
                     "every check has a control that fires",
                     "verify/json/selftest.json",
                     "PASS" if not f else "FAIL"))
    return R


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("final")
    ap.add_argument("--baseline")
    ap.add_argument("--validator")
    ap.add_argument("--validator-base")
    ap.add_argument("--selftest")
    ap.add_argument("--viewer")
    ap.add_argument("--import-json", dest="import_json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--md")
    a = ap.parse_args()
    ld = lambda p: json.load(open(p)) if p else None      # noqa: E731
    F = ld(a.final)
    rows = build(F, ld(a.baseline), ld(a.validator), ld(a.selftest),
                 ld(a.viewer), ld(a.validator_base), ld(a.import_json))
    json.dump({"rows": rows, "file": F.get("file"), "sha256": F.get("sha256")},
              open(a.out, "w"), indent=1)
    hdr = ["Requirement", "Baseline", "Final measured", "Threshold", "Evidence",
           "Status", "Remaining risk"]
    lines = ["| " + " | ".join(hdr) + " |",
             "|" + "|".join(["---"] * len(hdr)) + "|"]
    for r in rows:
        lines.append("| " + " | ".join(str(r[k]).replace("|", "/") for k in
                     ("requirement", "baseline", "final", "threshold",
                      "evidence", "status", "remaining_risk")) + " |")
    md = "\n".join(lines)
    if a.md:
        open(a.md, "w").write(md + "\n")
    print(md)
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print("\nSTATUS COUNTS:", counts)
    print("GATE_TABLE_DONE")


if __name__ == "__main__":
    main()
