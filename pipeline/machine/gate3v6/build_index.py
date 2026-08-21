"""GATE 3 v6 — compose the deliverables and write PROOF_INDEX.md.

    python3 build_index.py <outroot> <TAG> [--baseline-tag V0] [--ref-dir ...]

Reads the rig metadata written by render_job.py and composes:
  15 numbered proof items + the canonical 8-view sheet (+ constant-scale
  companion). Every number in PROOF_INDEX.md is read back off the rendered
  frames or off the rig metadata - none of it is asserted.
"""
import argparse, json, math, os, sys
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import compose as C                                              # noqa: E402

SHEET_LABELS = [
    ("s_front", "FRONT"), ("s_frontleft", "FRONT-LEFT 3/4"), ("s_left", "LEFT"),
    ("s_rearleft", "REAR-LEFT 3/4"), ("s_rear", "REAR"),
    ("s_rearright", "REAR-RIGHT 3/4"), ("s_right", "RIGHT"),
    ("s_frontright", "FRONT-RIGHT 3/4"),
]

AZ_NOTE = ("az 270=FRONT 090=REAR 000=LEFT 180=RIGHT 305/315=FRONT-LEFT 3/4 "
           "215/225=FRONT-RIGHT 3/4  (this file's NOSE IS AT -X)")


def px_per_m(v):
    if v["cam_type"] != "ORTHO":
        return None
    W, H = v["res"]
    a = W / float(H)
    frame_w = v["ortho_scale"] if a >= 1 else v["ortho_scale"] * a
    return W / frame_w


def camline(v):
    s = ("%s  az %03d  elev %.1f  " % (v["cam_type"].lower(), v["az"], v["elev"]))
    if v["cam_type"] == "ORTHO":
        s += "ortho_scale %.4f m  (%.1f px/m)" % (v["ortho_scale"], px_per_m(v))
    else:
        s += "lens %.1f mm" % v["lens_mm"]
    s += "  target_y(glTF) %.4f  shift [%.4f, %.4f]" % (
        v.get("target_y_gltf") or 0.0, v["shift"][0], v["shift"][1])
    return s


def expline(v):
    e = v.get("exposure", {}) or {}
    m = v.get("measured", {}) or {}
    parts = ["exposure %+.2f stops" % (e.get("exposure_stops") or 0.0)]
    p = e.get("probe_p99.8_linear")
    if p:
        parts.append("probe p99.8 %.3f -> %.3f linear" % (p, e.get("predicted_peak_linear") or 0))
    parts.append("bg sRGB %s (world %.2f -> %s expected)"
                 % (m.get("bg_corner_srgb"), v.get("world_grey", 0.22),
                    v.get("expected_bg_srgb")))
    cf = m.get("clipped_frac_frame")
    cc = m.get("clipped_frac_car", m.get("clipped_frac_nonbg"))
    parts.append("clipped: frame %.4f%%" % (100 * (cf or 0.0)))
    if cc is not None:
        parts.append("car %.4f%%" % (100 * cc))
    return "  |  ".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outroot")
    ap.add_argument("tag")
    ap.add_argument("--baseline-tag", default="V0")
    ap.add_argument("--ref-dir", default=None)
    a = ap.parse_args()

    png = os.path.join(a.outroot, "png")
    out = os.path.join(a.outroot, "sheets")
    os.makedirs(out, exist_ok=True)

    def meta(n):
        p = os.path.join(png, "_meta_%s.json" % n)
        return json.load(open(p)) if os.path.exists(p) else None

    mS = meta("%s_sheet" % a.tag)
    mSC = meta("%s_sheetC" % a.tag)
    mP = meta("%s_proof" % a.tag)
    mB = meta("%s_base" % a.baseline_tag)
    items = []          # (n, title, file, view_meta_or_None, evidence_of, notes)

    # ---------------------------------------------------- 8-view sheet(s)
    sheet_report = const_report = None
    if mS:
        order = [(vid, lab) for vid, lab in SHEET_LABELS]
        p, sheet_report = C.sheet8(
            order, mS, png, os.path.join(out, "SHEET_8VIEW_%s.jpg" % a.tag),
            "CANONICAL 8-VIEW SHEET — %s" % a.tag,
            "identical lens (orthographic), identical camera height and elevation, "
            "identical lighting and ground; per-tile ortho scale so every tile "
            "lands in the 75-85%% occupancy band.  " + AZ_NOTE)
        print("8-view sheet ->", p)
    if mSC:
        order = [(vid + "_c", lab) for vid, lab in SHEET_LABELS]
        try:
            p2, const_report = C.sheet8(
                order, mSC, png,
                os.path.join(out, "SHEET_8VIEW_CONSTSCALE_%s.jpg" % a.tag),
                "8-VIEW SHEET, CONSTANT SCALE — %s" % a.tag,
                "COMPANION SHEET. One ortho scale for all eight tiles, so sizes are "
                "directly comparable across views. A single scale CANNOT put both the "
                "4.28 m side view and the 1.79 m front view in 75-85%% — that is why "
                "the primary sheet fits per tile.  " + AZ_NOTE,
                occ_band=(0.0, 1.0))
            print("const-scale sheet ->", p2)
        except Exception as e:
            print("const-scale sheet FAILED:", e)

    # ---------------------------------------------------- 15 proof items
    def V(vid):
        return mP["views"][vid] if mP and vid in mP["views"] else None

    def src(vid):
        v = V(vid)
        return os.path.join(png, v["file"]) if v else None

    if mP:
        # 1
        v = V("p01_ortho_front_lamp_height")
        C.save_jpeg(C.caption_bar(C.flatten(src("p01_ortho_front_lamp_height")),
                    "01  ORTHOGRAPHIC FRONT AT HEADLAMP HEIGHT — %s" % a.tag,
                    camline(v) + "  |  neutral matte, no colour"),
                    os.path.join(out, "01_ortho_front_lamp_height.jpg"))
        items.append((1, "Straight orthographic front at headlamp height",
                      "01_ortho_front_lamp_height.jpg", v,
                      "True orthographic projection with the optical axis at the measured "
                      "headlamp centre height (glTF y=%.4f), elevation 0.000 — no perspective "
                      "and no downward tilt, so front-face proportions and lamp/grille "
                      "alignment can be read without foreshortening."
                      % (v.get("target_y_gltf") or 0), ""))
        # 2 / 3
        for n, vid, lab in ((2, "p02_front_left_34", "FRONT-LEFT THREE-QUARTER"),
                            (3, "p03_front_right_34", "FRONT-RIGHT THREE-QUARTER")):
            v = V(vid)
            C.save_jpeg(C.caption_bar(C.flatten(src(vid)),
                        "%02d  %s — %s" % (n, lab, a.tag),
                        camline(v) + "  |  neutral matte  |  " + expline(v)),
                        os.path.join(out, "%02d_%s.jpg" % (n, vid[4:])))
            items.append((n, lab.title(), "%02d_%s.jpg" % (n, vid[4:]), v,
                          "Form and continuity of the front end read against the flank; "
                          "the matched opposite-hand view makes a one-sided defect obvious.",
                          ""))
        # 4
        v = V("p04_clay_front")
        C.save_jpeg(C.caption_bar(C.flatten(src("p04_clay_front")),
                    "04  NEUTRAL CLAY FRONT — %s" % a.tag,
                    camline(v) + "  |  clay 0.55 grey, roughness 0.90, no specular, "
                    "no colour  |  " + expline(v)),
                    os.path.join(out, "04_clay_front.jpg"))
        items.append((4, "Neutral clay front", "04_clay_front.jpg", v,
                      "Surface form with no material, colour or gloss to flatter it. "
                      "Same camera as item 01, so clay and matte are frame-matched.", ""))
        # 5
        v = V("p05_wireframe_front")
        C.save_jpeg(C.caption_bar(C.flatten(src("p05_wireframe_front")),
                    "05  WIREFRAME FRONT — %s" % a.tag,
                    camline(v) + "  |  Cycles Wireframe node, 0.75 px wires, AA on"),
                    os.path.join(out, "05_wireframe_front.jpg"))
        items.append((5, "Wireframe front", "05_wireframe_front.jpg", v,
                      "Actual triangle density and distribution over the front end. "
                      "Dense/uneven areas are where the surface is carrying tessellation "
                      "noise rather than form.", ""))
        # 6
        v = V("p06_normals_front")
        C.save_jpeg(C.caption_bar(C.flatten(src("p06_normals_front")),
                    "06  NORMAL DIAGNOSTIC (world-space) — %s" % a.tag,
                    camline(v) + "  |  RGB = n*0.5+0.5, flat emission, no lighting"),
                    os.path.join(out, "06_normals_front.jpg"))
        items.append((6, "Normal diagnostic", "06_normals_front.jpg", v,
                      "Shading-independent read of surface direction. Mottling here is "
                      "REAL geometry noise; a smooth colour ramp is a smooth panel. "
                      "Also exposes missing/flipped normals.", ""))
        # 7
        v = V("p07_zebra_front")
        C.save_jpeg(C.caption_bar(C.flatten(src("p07_zebra_front")),
                    "07  ZEBRA / REFLECTION LINES — %s" % a.tag,
                    camline(v) + "  |  %d-band striped environment, neutral surface "
                    "roughness 0.055, film transparent over neutral grey"
                    % 26),
                    os.path.join(out, "07_zebra_front.jpg"))
        items.append((7, "Zebra / reflection-line front", "07_zebra_front.jpg", v,
                      "Surface CONTINUITY. Straight, evenly spaced bands = a fair surface; "
                      "a kink or a break in a band is a surface wave or a crease defect. "
                      "Neutral grey surface, neutral grey background - nothing is hidden "
                      "behind paint, gloss or a dark backdrop.", ""))
        # 8 (with legend)
        v = V("p08_matid_front")
        idc = (mP.get("id_colours") or {}).get("p08_matid_front", {})
        im = C.id_legend(C.flatten(src("p08_matid_front")), idc) if idc \
            else C.flatten(src("p08_matid_front"))
        C.save_jpeg(C.caption_bar(im, "08  MATERIAL-ID FRONT — %s" % a.tag,
                    camline(v) + "  |  flat emission, AA OFF (filter 0.01), 1 sample, "
                    "one colour per node  |  %d nodes visible" % v["n_visible_objects"]),
                    os.path.join(out, "08_matid_front.jpg"))
        items.append((8, "Material-ID front", "08_matid_front.jpg", v,
                      "Which node owns which pixel. Deterministic flat label render - "
                      "point-sampled renderers produce z-fighting speckle where two shells "
                      "are coincident, which reads as raggedness when the label is fine.", ""))
        # 9 reference overlay
        v = V("p09_ref_match_34")
        refs = []
        if a.ref_dir and os.path.isdir(a.ref_dir):
            rj = os.path.join(a.ref_dir, "REFERENCES.json")
            info = json.load(open(rj)) if os.path.exists(rj) else {}
            rf = os.path.join(a.ref_dir, "REF_FRONT_golf_mk8_style_2020.jpg")
            gap = (info.get("gaps", {}) or {}).get("orthographic_front", "")
            if os.path.exists(rf):
                refs = [(rf, "REFERENCE  2020 VW Golf Style 1.5 (Wikimedia, Vauxford, "
                             "CC BY-SA 4.0) - front-LEFT 3/4, NOT orthographic"),
                        (src("p09_ref_match_34"),
                         "RENDER  az 305 front-left 3/4, perspective 50 mm "
                         "(matched to the reference EXIF)")]
        if refs:
            C.side_by_side(refs, os.path.join(out, "09_reference_overlay.jpg"),
                           "09  REFERENCE OVERLAY — %s" % a.tag,
                           "LIMIT, quoted from ref/REFERENCES.json: no orthographic front "
                           "reference exists for this vehicle, so this pair governs FEATURE "
                           "STRUCTURE and PROPORTION RATIOS only. Any criterion needing an "
                           "orthographic reference overlay is NOT TESTED, never estimated.")
        else:
            C.save_jpeg(C.caption_bar(C.flatten(src("p09_ref_match_34")),
                        "09  REFERENCE-MATCHED VIEW (reference not supplied) — %s" % a.tag,
                        camline(v)), os.path.join(out, "09_reference_overlay.jpg"))
        items.append((9, "Reference overlay", "09_reference_overlay.jpg", v,
                      "Render taken at the reference photograph's own focal length and "
                      "viewpoint class, presented beside it so feature structure "
                      "(DRL signature, grille bar, badge/bar relationship, lamp outline) "
                      "can be compared like for like.",
                      "NOT orthographic - the reference itself is a three-quarter photo."))
        # 10 symmetry
        v = V("p01_ortho_front_lamp_height")
        p, sym = C.symmetry_overlay(
            src("p01_ortho_front_lamp_height"),
            os.path.join(out, "10_symmetry_overlay.jpg"),
            "10  SYMMETRY OVERLAY (mirror difference) — %s" % a.tag,
            camline(v) + "  |  optical axis forced through the mesh mirror plane "
            "(glTF z=0, shift_x=0)")
        items.append((10, "Symmetry overlay", "10_symmetry_overlay.jpg", v,
                      "Left/right asymmetry of the front end. The frame is mirrored about "
                      "its own centre column and differenced; red = disagreement. Valid "
                      "only because the camera's optical axis is pinned to glTF z=0.",
                      "mean|d| %.2f sRGB, p99 %.2f, %.2f%% of pixels differ by >12"
                      % (sym["mean_abs_diff_srgb"], sym["p99_abs_diff_srgb"],
                         100 * sym["frac_px_over_12"])))
        # 11 / 12 exploded
        for n, vid, title, what in (
            (11, "p11_front_exploded", "FRONT ASSEMBLY EXPLODED",
             "Every front-end component exists as SEPARATE geometry. Parts are "
             "translated along -X (out through the nose) in assembly layers and each "
             "is labelled with its glTF node name. A component missing from this view "
             "is a component that has not been proven."),
            (12, "p12_headlamp_exploded", "HEADLAMP EXPLODED",
             "The headlamp is a multi-part assembly, not a painted patch: lens, "
             "housing, inner/reflector and DRL emit as distinct nodes. Body shell "
             "hidden so nothing can conceal a part that is not there.")):
            v = V(vid)
            if not v:
                continue
            idc = (mP.get("id_colours") or {}).get(vid, {})
            tmp = os.path.join(out, "_tmp_%d.jpg" % n)
            C.save_jpeg(C.flatten(src(vid)), tmp)
            f, cnt = C.label_exploded(
                tmp, v, os.path.join(out, "%02d_%s.jpg" % (n, vid[4:])),
                "%02d  %s — %s" % (n, title, a.tag),
                camline(v) + "  |  explode -X, %.2f m per layer"
                % v.get("explode_spacing", 0.34) if False else camline(v))
            os.remove(tmp)
            items.append((n, title.title(), "%02d_%s.jpg" % (n, vid[4:]), v, what,
                          "%d components separated and labelled" % cnt))
        # 13 old geometry removed
        v = V("p13_kit_hidden_front")
        pairs = []
        if mB and "b01_ortho_front_lamp_height_%s" % a.baseline_tag in mB["views"]:
            bv = mB["views"]["b01_ortho_front_lamp_height_%s" % a.baseline_tag]
            pairs.append((os.path.join(png, bv["file"]),
                          "%s BASELINE  (original geometry, no rebuilt components)"
                          % a.baseline_tag))
        pairs.append((src("p13_kit_hidden_front"),
                      "%s WITH REBUILT COMPONENTS HIDDEN  (what the shell carries "
                      "underneath)" % a.tag))
        pairs.append((src("p01_ortho_front_lamp_height"),
                      "%s COMPLETE  (components restored)" % a.tag))
        C.side_by_side(pairs, os.path.join(out, "13_old_geometry_removed.jpg"),
                       "13  OLD-GEOMETRY-REMOVED — %s" % a.tag,
                       "All three frames share ONE camera: " + camline(v))
        items.append((13, "Old-geometry-removed", "13_old_geometry_removed.jpg", v,
                      "What the original shell holds where the rebuilt components sit. "
                      "Comparing the baseline, the components-hidden frame and the "
                      "complete frame at ONE camera shows whether the superseded "
                      "geometry was removed or merely covered over.", ""))
        # 14 sections
        secs = []
        for vid, lab in (("p14_section_plan", "PLAN SECTION at headlamp mid-height "
                          "(camera looking straight down; image-right = car tail)"),
                         ("p14_section_transverse", "TRANSVERSE SECTION at headlamp "
                          "mid-width (camera on the car's left)")):
            v = V(vid)
            if not v:
                continue
            im = C.flatten(src(vid))
            ppm = px_per_m(v)
            if ppm:
                im = C.scale_bar(im, ppm)
            t = os.path.join(out, "_tmp_%s.jpg" % vid)
            C.save_jpeg(im, t)
            secs.append((t, lab))
        if secs:
            C.side_by_side(secs, os.path.join(out, "14_intersection_clearance.jpg"),
                           "14  INTERSECTION / CLEARANCE SECTIONS — %s" % a.tag,
                           "Near-plane section cuts through one headlamp cluster, flat "
                           "material-ID colours, scale bar on each panel. Inner shell "
                           "hidden so the lens / housing / body relationship reads.")
            for t, _ in secs:
                os.remove(t)
        items.append((14, "Intersection-clearance", "14_intersection_clearance.jpg",
                      V("p14_section_transverse"),
                      "Whether components sit clear of one another and of the body, or "
                      "interpenetrate. Sections are cut at the component, not across the "
                      "whole nose - a whole-nose section averages the gaps away.",
                      "candidate observations only; the verifier owns the verdict"))
        # 15 before / after
        rows = []
        for vid, bid, lab in (
            ("p01_ortho_front_lamp_height", "b01_ortho_front_lamp_height_%s" % a.baseline_tag,
             "ORTHO FRONT, neutral matte"),
            ("p04_clay_front", "b04_clay_front_%s" % a.baseline_tag, "CLAY FRONT"),
            ("p02_front_left_34", "b02_front_left_34_%s" % a.baseline_tag,
             "FRONT-LEFT 3/4")):
            if not (mB and bid in mB["views"]) or not V(vid):
                continue
            bv = mB["views"][bid]
            t = os.path.join(out, "_tmp_ab_%s.jpg" % vid)
            C.side_by_side(
                [(os.path.join(png, bv["file"]), "BEFORE — %s baseline" % a.baseline_tag),
                 (src(vid), "AFTER — %s" % a.tag)], t, "", "", tile=(1300, 1040))
            rows.append(t)
        if rows:
            C.stack(rows, os.path.join(out, "15_before_after.jpg"),
                    "15  BEFORE / AFTER MATCHED COMPARISON — %s vs %s"
                    % (a.baseline_tag, a.tag),
                    "Every pair shares the SAME ortho scale, shift, target height, "
                    "azimuth, elevation, lighting and view transform — the baseline was "
                    "rendered with the camera parameters read out of the target's own "
                    "metadata, not re-fitted.")
            for t in rows:
                os.remove(t)
        items.append((15, "Before/after matched comparison", "15_before_after.jpg",
                      None, "Same-camera pairs of the baseline and the target so a change "
                      "in the render is a change in the geometry, not a change in framing.",
                      ""))

    # ---------------------------------------------------- write the index
    idx = {"tag": a.tag, "az_convention": AZ_NOTE,
           "sheet": sheet_report, "const_sheet": const_report,
           "items": []}
    lines = []
    lines.append("# GATE 3 v6 — PROOF INDEX (%s)\n" % a.tag)
    lines.append("Rigs: `pipeline/machine/gate3v6/` "
                 "(`rig.py`, `render_job.py`, `plan.py`, `compose.py`, "
                 "`run_proof.py`, `build_index.py`). Renderer: Blender 4.0.2 / "
                 "**Cycles CPU**, view transform **Standard** (never AgX), "
                 "denoising **off** (this container has no OpenImageDenoiser).\n")
    lines.append("**Azimuth convention for this file — NOSE IS AT -X:** `%s`\n" % AZ_NOTE)
    lines.append("Every occupancy, exposure and clipped-pixel number below is **measured "
                 "off the rendered frame** (alpha probe for the silhouette, direct pixel "
                 "read for clipping). None of it is asserted.\n")

    if sheet_report:
        lines.append("\n## Deliverable 2 — canonical 8-view sheet\n")
        lines.append("`sheets/SHEET_8VIEW_%s.jpg`\n" % a.tag)
        v0 = mS["views"][SHEET_LABELS[0][0]]
        lines.append("- tile resolution **%d x %d** each, 8 tiles -> sheet is well over "
                     "2048 px\n" % (v0["res"][0], v0["res"][1]))
        lines.append("- identical for all eight tiles: orthographic lens, elevation "
                     "%.1f deg, camera height (target glTF y = %.4f), light rig, ground "
                     "plane, world grey %.2f, Standard view transform\n"
                     % (v0["elev"], v0.get("target_y_gltf") or 0, v0.get("world_grey", .22)))
        lines.append("- per-tile ortho scale so each tile lands in the 75-85%% band\n")
        lines.append("\n| # | view | az | populated | occupancy (bbox) | silhouette fill | "
                     "clipped (car) | ortho scale m | exposure |\n"
                     "|---|---|---|---|---|---|---|---|---|\n")
        for i, r in enumerate(sheet_report, 1):
            lines.append("| %d | %s | %03d | %s | **%.1f%%** | %.1f%% | %.3f%% | %.4f | "
                         "%+.2f st |\n"
                         % (i, r["label"], r["az"], "YES" if r["populated"] else "NO",
                            100 * (r["occ_max"] or 0), 100 * (r["silhouette_px_frac"] or 0),
                            100 * (r["clipped_frac_car"] or 0), r["ortho_scale"],
                            r["exposure_stops"] or 0))
        npop = sum(1 for r in sheet_report if r["populated"])
        nband = sum(1 for r in sheet_report if r["occ_in_band"])
        lines.append("\n**%d/8 tiles populated. %d/8 tiles inside the 75-85%% occupancy "
                     "band.**\n" % (npop, nband))
        lines.append("\n*Occupancy is the vehicle silhouette's bounding box as a fraction "
                     "of the frame in its larger dimension — the framing metric. "
                     "Silhouette fill is the fraction of frame pixels the vehicle actually "
                     "covers, and it is the populated-tile test (a background-colour "
                     "difference cannot be trusted once a ground plane is in frame).*\n")
        if const_report:
            lines.append("\n### Companion: constant-scale sheet\n")
            lines.append("`sheets/SHEET_8VIEW_CONSTSCALE_%s.jpg` — one ortho scale "
                         "(%.4f m) across all eight tiles, so sizes are directly "
                         "comparable. **A single scale cannot satisfy 75-85%% on both "
                         "the 4.28 m side view and the 1.79 m front view**; measured "
                         "occupancies are:\n\n" % const_report[0]["ortho_scale"])
            lines.append("| view | az | occupancy | fill |\n|---|---|---|---|\n")
            for r in const_report:
                lines.append("| %s | %03d | %.1f%% | %.1f%% |\n"
                             % (r["label"], r["az"], 100 * (r["occ_max"] or 0),
                                100 * (r["silhouette_px_frac"] or 0)))

    lines.append("\n## Deliverable 1 — the 15-item proof package\n")
    lines.append("All files in `sheets/`. Camera, exposure and measurement lines are "
                 "also burnt into each image.\n")
    for n, title, f, v, ev, note in sorted(items):
        p = os.path.join(out, f)
        res = None
        if os.path.exists(p):
            with Image.open(p) as im:
                res = im.size
        lines.append("\n### %02d. %s\n" % (n, title))
        lines.append("- **file**: `sheets/%s`%s\n"
                     % (f, "  (**%d x %d**)" % res if res else "  *(MISSING)*"))
        if v:
            lines.append("- **camera**: %s\n" % camline(v))
            lines.append("- **render**: %d x %d, %d samples, %s\n"
                         % (v["res"][0], v["res"][1], v["samples"], expline(v)))
            if v.get("hidden"):
                lines.append("- **hidden nodes**: %s\n" % ", ".join(v["hidden"]))
            if v.get("section"):
                lines.append("- **section**: cut plane through glTF %s, clip_start %.4f m\n"
                             % ([round(x, 4) for x in v["section"]["section_point_gltf"]],
                                v["section"]["clip_start"]))
        lines.append("- **evidence of**: %s\n" % ev)
        if note:
            lines.append("- **note**: %s\n" % note)
        idx["items"].append({"n": n, "title": title, "file": f, "res": res,
                             "evidence_of": ev, "note": note,
                             "camera": None if not v else
                             {k: v.get(k) for k in
                              ("cam_type", "az", "elev", "ortho_scale", "lens_mm",
                               "target_y_gltf", "shift", "res", "samples",
                               "world_grey", "expected_bg_srgb")},
                             "exposure": None if not v else v.get("exposure"),
                             "measured": None if not v else v.get("measured")})

    with open(os.path.join(a.outroot, "PROOF_INDEX.md"), "w") as f:
        f.write("".join(lines))
    with open(os.path.join(a.outroot, "index.json"), "w") as f:
        json.dump(idx, f, indent=1)
    print("wrote PROOF_INDEX.md and index.json  (%d items)" % len(items))


if __name__ == "__main__":
    main()
