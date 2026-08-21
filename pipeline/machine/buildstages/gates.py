#!/usr/bin/env python3
"""gates.py — the MUST-NOT-BREAK panel, re-run after every stage of the merge.

The four properties the merged car has to keep, and the reason each check is
shaped the way it is:

G1  GLAZING clear/proven  **PAIRED WITH A GLASS-AREA FIGURE.**
    `glass_probe` reads the material TABLE and cannot see which faces carry
    which material.  Two agents proved that independently on 2026-08-21: the
    glass gate found it passing a car whose windscreen aperture was `carpaint`,
    and the mobile gate cut the glazing GEOMETRY to 2.5% of its area, left the
    table untouched, and still got clear/proven.  So the verdict alone is not
    evidence that a car HAS glazing.  This gate refuses the pair separately:
    the verdict must be clear/proven AND the world-space glazing area must be
    retained against the stage's own reference.

G2  TYRES BLACK.  `Tyre_Rubber` baseColorFactor near 0.027, and the material
    must still be BOUND to the tyre nodes (a rebind to `carpaint` leaves the
    table untouched — that is the mobile gate's NC3).

G3  RESPRAY CONTROL, red -> blue at a locked camera.  carpaint must move;
    tyres, glazing, rims and lamps must not.  This is the arbiter CLAUDE.md
    names: gates + eye + texture all agreed and all three were wrong on the
    Pixal Golf; only the respray was right.  Masks come from a MATERIAL-keyed
    matID render at the same camera, so a "region" is the material's own
    pixels rather than a hand-drawn box.

G4  VALIDATOR 0 errors AND NORMAL on every primitive, 0 zero-length,
    0 non-unit.  A geometry operator that only writes positions ships a broken
    file that renders fine (Gate 6 went 30 -> 1,980 errors invisibly).

EVERY ONE OF THESE CAN FAIL, and `selftest()` proves it by injecting the
negative control that each is meant to catch.  CLAUDE.md records three separate
checks found in one day that could never fire; a gate nobody has seen fail is a
gate that does not exist.
"""
from __future__ import annotations

import importlib.util
import json
import os
import struct
import subprocess
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_MACHINE = os.path.dirname(_HERE)
_REPO = os.path.dirname(os.path.dirname(_MACHINE))
sys.path.insert(0, _HERE)

import glbmeas                                                   # noqa: E402
import render as R                                               # noqa: E402

TYRE_BLACK_MAX = 0.06        # baseColorFactor ceiling for "reads as rubber"
GLASS_RETAIN_MIN = 0.90      # of the base's PROJECTED glazing opening
GLASS_REGION_MIN = 0.45      # of the base's area in ANY one region (calibrated below)
FROZEN_MATS = ("Tyre_Rubber", "glass", "Rim_Alloy", "Brake_Disc",
               "Lamp_Lens", "Lamp_Lens_Rear")


# --------------------------------------------------------------------- probe
def glass_probe(path):
    """pipeline/ingest/glass_probe.py VERBATIM, byte-source swapped to local.

    Same trick as rear2/glass_local.py: only `head()` is replaced, so every
    rule in `probe()` is the shipped wave rule and this cannot drift from it.
    """
    spec = importlib.util.spec_from_file_location(
        "glass_probe", os.path.join(_REPO, "pipeline", "ingest", "glass_probe.py"))
    gp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gp)
    gp.head = lambda p, n: open(p, "rb").read(n)
    return gp.probe("local", url=path)


def validate(path, out_json=None):
    r = subprocess.run([sys.executable, os.path.join(_MACHINE, "gltf_validate.py"),
                        path] + (["--json", out_json] if out_json else []),
                       capture_output=True, text=True)
    d = {}
    if out_json and os.path.exists(out_json):
        d = json.load(open(out_json))
    txt = r.stdout + r.stderr
    c = (d.get("counts") or {}) if isinstance(d, dict) else {}
    errs, warns = c.get("errors"), c.get("warnings")
    infos, hints = c.get("infos"), c.get("hints")
    if errs is None:
        # the validator could not run at all -> that is a FAIL, never an
        # "unknown" that a caller might read as clean.
        errs = -1
    return {"errors": errs, "warnings": warns, "infos": infos, "hints": hints,
            "exit": r.returncode,
            "verdict": "PASS" if (errs == 0 and "VERDICT: PASS" in txt) else "FAIL",
            "raw_tail": txt[-600:]}


# ------------------------------------------------------------------- respray
def _respray(inp, out, rgb):
    subprocess.run([sys.executable, os.path.join(_MACHINE, "rear2", "respray.py"),
                    inp, out, str(rgb[0]), str(rgb[1]), str(rgb[2])],
                   check=True, capture_output=True, text=True)


def respray_control(path, workdir, cam, res=700, samples=24, tag="rc"):
    """Red -> blue at a locked camera; per-material masks from a matID pass.

    Returns {material: mean |delta sRGB| over its own pixels, and the pixel
    count}, plus the verdict.  A material that is not visible at this camera
    reports n=0 and is EXCLUDED from the verdict rather than counted as a pass —
    an empty region reporting "no movement" is the empty-by-construction gate
    class CLAUDE.md warns about.
    """
    from PIL import Image
    os.makedirs(workdir, exist_ok=True)
    red = os.path.join(workdir, f"{tag}_red.glb")
    blue = os.path.join(workdir, f"{tag}_blue.glb")
    _respray(path, red, (0.62, 0.06, 0.06))
    _respray(path, blue, (0.06, 0.15, 0.62))
    pr, _ = R.render(red, workdir, "shaded", f"{tag}R", cam, res=res, samples=samples)
    pb, _ = R.render(blue, workdir, "shaded", f"{tag}B", cam, res=res, samples=samples)
    pm, pal = R.render(path, workdir, "matid", f"{tag}M", cam, res=res, samples=1)
    os.remove(red)
    os.remove(blue)

    names = sorted(pal)
    P = np.array([pal[n] for n in names])                       # linear emission
    out = {"per_shot": {}, "materials": {}}
    for i, s in enumerate(cam["shots"]):
        A = np.asarray(Image.open(pr[i]).convert("RGB"), np.float64)
        B = np.asarray(Image.open(pb[i]).convert("RGB"), np.float64)
        M = np.asarray(Image.open(pm[i]).convert("RGB"), np.float64) / 255.0
        # matID is an emission pass under Standard view transform, so the
        # written sRGB is the linear colour gamma-encoded; invert it before
        # matching against the linear palette.
        Ml = np.where(M <= 0.04045, M / 12.92, ((M + 0.055) / 1.055) ** 2.4)
        d = np.linalg.norm(Ml[:, :, None, :] - P[None, None, :, :], axis=3)
        lab = d.argmin(2)
        best = d.min(2)
        on = best < 0.10                        # background / AA edges excluded
        delta = np.linalg.norm(A - B, axis=2)
        shot = {}
        for k, n in enumerate(names):
            m = on & (lab == k)
            shot[n] = {"n": int(m.sum()),
                       "mean_delta_srgb": round(float(delta[m].mean()), 3) if m.sum() else None}
        out["per_shot"][s["tag"]] = shot
    for n in names:
        vals = [(out["per_shot"][s["tag"]][n]["n"],
                 out["per_shot"][s["tag"]][n]["mean_delta_srgb"])
                for s in cam["shots"]]
        tot = sum(v[0] for v in vals)
        wm = (sum(v[0] * v[1] for v in vals if v[1] is not None) / tot) if tot else None
        out["materials"][n] = {"n": tot,
                               "mean_delta_srgb": round(wm, 3) if wm is not None else None}
    cp = out["materials"].get("carpaint", {})
    out["carpaint_delta"] = cp.get("mean_delta_srgb")
    out["carpaint_px"] = cp.get("n", 0)
    frozen = {n: out["materials"][n] for n in FROZEN_MATS if n in out["materials"]}
    out["frozen"] = frozen
    seen = {n: v for n, v in frozen.items() if v["n"] >= 200}
    out["frozen_seen"] = sorted(seen)
    out["frozen_max_delta"] = (round(max(v["mean_delta_srgb"] for v in seen.values()), 3)
                               if seen else None)
    out["frozen_worst"] = (max(seen, key=lambda n: seen[n]["mean_delta_srgb"])
                           if seen else None)
    # A frozen material that has VANISHED from the render reports n=0 and would
    # otherwise be silently excluded — which is how a rebind of the tyre
    # primitives to `carpaint` slipped past this gate in the first selftest run
    # (measured: it was caught by the binding check instead).  Requiring the two
    # materials the owner rulings are about to be PRESENT makes this gate an
    # independent catch for that defect rather than a vacuous pass.
    must_see = ("Tyre_Rubber", "glass")
    out["frozen_missing"] = [n for n in must_see if n not in seen]
    ok = (out["carpaint_px"] >= 2000 and out["carpaint_delta"] is not None
          and out["carpaint_delta"] >= 40.0
          and not out["frozen_missing"]
          and len(seen) >= 3
          and out["frozen_max_delta"] is not None
          and out["frozen_max_delta"] <= 25.0
          and out["carpaint_delta"] >= 3.0 * out["frozen_max_delta"])
    out["pass"] = bool(ok)
    return out


# ---------------------------------------------------------------------- gate
def panel(path, workdir, ref=None, cam=None, do_respray=True, res=700, samples=24,
          tag="g", ref_prev=None):
    """Run every gate on `path`.

    TWO references, deliberately, because they answer different questions:
      `ref`      the BASE measurement -> "does the car still have its glazing at
                 all?"  Held across the whole pipeline.
      `ref_prev` the PREVIOUS STAGE's measurement -> "did THIS stage break a
                 pane?"  A per-node figure held against the base would fire on
                 a gate's own intended work: the glass gate deliberately evicts
                 0.294 m2 of roof/cant-rail/C-pillar spill and carves
                 Glass_Quarter_L out of Glass_Side_L, which takes that node
                 1.2728 -> 0.7903 m2.  That is the gate doing its job, and it
                 must not read as a regression three stages later.
    """
    if ref_prev is None:
        ref_prev = ref
    os.makedirs(workdir, exist_ok=True)
    # SELF-NORMALISED regions, deliberately.  Binning against the BASE's world
    # box was wrong the moment the pose stage rotated the car 4.7301 deg and
    # dropped it 101.6 mm: the bins stopped lining up with the car's own bands
    # and the check fired on a measurement-frame artefact rather than on a
    # defect.  Normalising each file to ITS OWN bounding box makes the figure
    # shape-relative and therefore invariant to a rigid pose -- measured, the
    # glazing TOTAL is bit-identical across the pose stage (3.7833 m2 both
    # sides) and the per-region ratios sit at 0.833-1.258, the residual being
    # faces crossing a bin boundary under the rotation.
    m = glbmeas.measure(path)
    gp = glass_probe(path)
    val = validate(path, os.path.join(workdir, f"{tag}_validate.json"))

    res_d = {"measure": m, "glass_probe": gp, "validator": val, "checks": {}}
    C = res_d["checks"]

    # ---- G1 glazing verdict AND area retention (the pair, never one alone)
    verdict_ok = (gp.get("verdict") == "clear" and gp.get("certainty") == "proven"
                  and not gp.get("flat_shell") and not gp.get("alpha_shell"))
    # GATE ON THE PROJECTED OPENING, not on surface area.  See glbmeas: the
    # melt rear screen has 2.73x more surface than the opening it fills, so a
    # surface-area floor reads a crumple being REPLACED by a clean pane as
    # losing half the rear window.  Surface area is still reported, and its
    # ratio to the projection ("crumple ratio") is a useful number in itself.
    area = m["glass_projected_m2"]["max"]
    ref_area = ref["glass_projected_m2"]["max"] if ref else None
    retain = (area / ref_area) if ref_area else None
    C["glazing_verdict"] = {"pass": bool(verdict_ok),
                            "verdict": gp.get("verdict"),
                            "certainty": gp.get("certainty"),
                            "flat_shell": gp.get("flat_shell"),
                            "alpha_shell": gp.get("alpha_shell")}
    C["glass_area"] = {"pass": bool(retain is None or retain >= GLASS_RETAIN_MIN),
                       "basis": "projected opening (max of 3 axis projections)",
                       "projected_m2": round(area, 6),
                       "ref_projected_m2": round(ref_area, 6) if ref_area else None,
                       "retained": round(retain, 5) if retain else None,
                       "surface_area_m2": round(m["glass_area_m2"], 6),
                       "crumple_ratio": m["glass_crumple_ratio"],
                       "projections": m["glass_projected_m2"],
                       "by_node": m["glass_area_by_node"]}

    # ---- G1b GLAZING RETENTION BY SPATIAL REGION.
    # The material TOTAL and the per-REGION figures catch different defects: a
    # windscreen rebound to `carpaint` moves 0.16 m2 of 3.17 and barely dents
    # the total, but empties its own region.  A region is used rather than a
    # NODE because a node figure cannot tell a deliberate re-partition from a
    # loss -- the glass gate legitimately takes `Glass_Side_L` 1.2728 -> 0.7903
    # by carving `Glass_Quarter_L` out of it, and the per-node rule fired on
    # exactly that and was wrong.
    #
    # THE FLOOR IS MEASURED, NOT CHOSEN.  Run end to end on this car the
    # tightest LEGITIMATE region ratio against the base is 0.632 -- the C-pillar
    # band, which takes the glass gate's cant-rail and over-pillar spill
    # eviction (0.761) and then the pose stage's bin-boundary shift (0.833).
    # The injected defects sit at 0.00 (windscreen rebound to `carpaint`, the
    # region empties) and ~0.03 (glazing geometry cut to a fortieth).  0.45 sits
    # 29% below the tightest legitimate value and 15x above the loudest defect.
    refr = (ref or {}).get("glass_projected_by_region") or {}
    gotr = m.get("glass_projected_by_region") or {}
    emptied, shrunk = [], {}
    for k, v in refr.items():
        if v < 0.005:
            continue                       # a 50 cm2 projected sliver is not a region
        got = gotr.get(k, 0.0)
        if got < GLASS_REGION_MIN * v:
            if got < 0.05 * v:
                emptied.append(k)          # the region is gone, not merely thinner
            else:
                shrunk[k] = [round(v, 5), round(got, 5), round(got / v, 4)]
    C["glass_regions"] = {"pass": bool(not emptied and not shrunk),
                          "floor": GLASS_REGION_MIN,
                          "emptied": emptied, "shrunk_below_floor": shrunk,
                          "ref": {k: round(v, 5) for k, v in refr.items()},
                          "got": {k: round(v, 5) for k, v in gotr.items()}}

    # ---- G1c THE WRITTEN MATERIAL TABLE, read directly.
    # `trimesh` drops every KHR material extension on any round-trip while
    # `alphaMode` survives, so glass_probe still returns clear/proven on glazing
    # that has stopped refracting entirely.  Neither the verdict nor any area
    # figure can see that.  Confirmed a third time by the independent verifier:
    # the probe passed a file with all extensions stripped.
    gm = m["material_table"].get("glass") or {}
    rgm = ((ref_prev or ref or {}).get("material_table") or {}).get("glass") or {}
    need_ext = ["KHR_materials_ior", "KHR_materials_transmission"]
    have = gm.get("extensions") or []
    missing_ext = [e for e in need_ext if e not in have]
    alpha = (gm.get("baseColorFactor") or [None] * 4)[3]
    ralpha = (rgm.get("baseColorFactor") or [None] * 4)[3]
    C["glass_material_written"] = {
        "pass": bool(not missing_ext and gm.get("alphaMode") == "BLEND"
                     and (ralpha is None or (alpha is not None
                                             and abs(alpha - ralpha) < 1e-6))),
        "extensions": have, "missing": missing_ext,
        "alphaMode": gm.get("alphaMode"), "alpha": alpha, "ref_alpha": ralpha,
        "baseColorFactor": gm.get("baseColorFactor")}

    # ---- G2 tyres black AND still bound to the tyre nodes
    bc = m["tyre_baseColor"]
    tyre_nodes = sorted(m["per_material"].get("Tyre_Rubber", {}).get("nodes", []))
    bound_ok = len([n for n in tyre_nodes if n.lower().endswith("tyre")]) == 4
    C["tyres_black"] = {
        "pass": bool(bc is not None and max(bc) <= TYRE_BLACK_MAX and bound_ok),
        "baseColor": [round(x, 5) for x in bc] if bc else None,
        "bound_nodes": tyre_nodes, "four_tyre_nodes": bool(bound_ok),
        "area_m2": m["tyre_area_m2"]}

    # ---- G4 validator + normals
    C["validator"] = {"pass": bool(val["verdict"] == "PASS" and val["errors"] == 0),
                      "errors": val["errors"], "warnings": val["warnings"],
                      "infos": val.get("infos"), "hints": val.get("hints"),
                      "verdict": val["verdict"]}
    C["normals"] = {"pass": bool(m["primitives_missing_NORMAL"] == 0
                                 and m["zero_normals"] == 0
                                 and m["non_unit_normals"] == 0),
                    "primitives": m["primitives"],
                    "missing_NORMAL": m["primitives_missing_NORMAL"],
                    "zero": m["zero_normals"], "non_unit": m["non_unit_normals"]}

    # ---- G3 respray
    if do_respray:
        if cam is None:
            cam = R.camera_for(m)
            cam["shots"] = R.shots([(305, 12, "f34"), (125, 12, "r34")])
        rc = respray_control(path, os.path.join(workdir, f"{tag}_rc"), cam,
                             res=res, samples=samples, tag=tag)
        res_d["respray"] = rc
        C["respray"] = {"pass": rc["pass"], "carpaint_delta": rc["carpaint_delta"],
                        "carpaint_px": rc["carpaint_px"],
                        "frozen_max_delta": rc["frozen_max_delta"],
                        "frozen_worst": rc["frozen_worst"],
                        "frozen_seen": rc["frozen_seen"],
                        "frozen_missing": rc["frozen_missing"]}

    res_d["all_pass"] = all(v["pass"] for v in C.values())
    res_d["failed"] = sorted(k for k, v in C.items() if not v["pass"])
    return res_d


def summary_line(p):
    C = p["checks"]
    bits = [f"glaz={C['glazing_verdict']['verdict']}/{C['glazing_verdict']['certainty']}",
            f"glassproj={C['glass_area']['projected_m2']:.4f}m2"
            + (f" ({100*C['glass_area']['retained']:.1f}%)"
               if C['glass_area']['retained'] else "")
            + f" crumple={C['glass_area']['crumple_ratio']}",
            "ext=" + ("+".join(e.replace("KHR_materials_", "")
                               for e in C['glass_material_written']['extensions'])
                      or "NONE"),
            f"tyre={C['tyres_black']['baseColor'][0] if C['tyres_black']['baseColor'] else '?'}",
            f"val={C['validator']['errors']}err",
            f"N={C['normals']['primitives']-C['normals']['missing_NORMAL']}"
            f"/{C['normals']['primitives']} z{C['normals']['zero']} u{C['normals']['non_unit']}"]
    if "respray" in C:
        bits.append(f"respray cp={C['respray']['carpaint_delta']} "
                    f"frozen<={C['respray']['frozen_max_delta']}")
    return ("PASS  " if p["all_pass"] else "FAIL  ") + " | ".join(bits) \
        + ("" if p["all_pass"] else f"   FAILED: {p['failed']}")


# ------------------------------------------------------------------ controls
def _rw(path, out, fn):
    js, bin_ = glbmeas.read_glb(path)
    fn(js, bin_)
    j = json.dumps(js, separators=(",", ":")).encode()
    j += b" " * ((4 - len(j) % 4) % 4)
    b = bin_ + b"\0" * ((4 - len(bin_) % 4) % 4)
    with open(out, "wb") as f:
        f.write(b"glTF" + struct.pack("<II", 2, 12 + 8 + len(j) + 8 + len(b)))
        f.write(struct.pack("<II", len(j), 0x4E4F534A) + j)
        f.write(struct.pack("<II", len(b), 0x004E4942) + b)


def make_control(path, out, kind):
    """Inject a defect each gate is supposed to catch.  Used by selftest()."""
    if kind == "glass_cut":
        # the mobile gate's NC2: cut the glazing GEOMETRY, leave the TABLE alone.
        # glass_probe must still say clear/proven; the area gate must catch it.
        def fn(js, bin_):
            gl = [i for i, m in enumerate(js["materials"]) if m.get("name") == "glass"]
            for me in js["meshes"]:
                for p in me["primitives"]:
                    if p.get("material") in gl:
                        a = js["accessors"][p["indices"]]
                        a["count"] = max(3, (a["count"] // 3) // 40 * 3)
        _rw(path, out, fn)
    elif kind == "tyre_pale":
        def fn(js, bin_):
            for m in js["materials"]:
                if m.get("name") == "Tyre_Rubber":
                    m.setdefault("pbrMetallicRoughness", {})["baseColorFactor"] = \
                        [0.82, 0.82, 0.83, 1.0]
        _rw(path, out, fn)
    elif kind == "tyre_bound_to_paint":
        # the mobile gate's NC3: rebind the tyre PRIMITIVES to carpaint. The
        # tyre material's own numbers are untouched, so only a BINDING-aware or
        # render-based check can see it.
        def fn(js, bin_):
            cp = [i for i, m in enumerate(js["materials"]) if m.get("name") == "carpaint"][0]
            tn = {n["mesh"] for n in js["nodes"]
                  if n.get("name", "").lower().endswith("tyre") and "mesh" in n}
            for mi in tn:
                for p in js["meshes"][mi]["primitives"]:
                    p["material"] = cp
        _rw(path, out, fn)
    elif kind == "drop_normals":
        def fn(js, bin_):
            for me in js["meshes"][:1]:
                for p in me["primitives"]:
                    p["attributes"].pop("NORMAL", None)
        _rw(path, out, fn)
    elif kind == "strip_extensions":
        # the verifier's NC5: remove every KHR material extension.  glass_probe
        # returns clear/proven regardless — only a direct read of the written
        # table sees it.  This is what a trimesh round-trip does by itself.
        def fn(js, bin_):
            for m in js["materials"]:
                m.pop("extensions", None)
            js.pop("extensionsUsed", None)
        _rw(path, out, fn)
    elif kind == "windscreen_to_paint":
        # rebind the WINDSCREEN pane to `carpaint`.  The glazing-material TOTAL
        # barely notices (the windscreen is 0.16 m2 of 3.17 on the base); the
        # PER-NODE figure empties.
        def fn(js, bin_):
            cp = [i for i, m in enumerate(js["materials"])
                  if m.get("name") == "carpaint"][0]
            for n in js["nodes"]:
                if n.get("name") == "Glass_Windscreen" and "mesh" in n:
                    for p in js["meshes"][n["mesh"]]["primitives"]:
                        p["material"] = cp
        _rw(path, out, fn)
    elif kind == "break_validator":
        # ACCESSOR_MIN_MISMATCH / ACCESSOR_MAX_MISMATCH are spec ERRORS and are
        # completely invisible in a render.  Chosen over inflating an index
        # accessor's count, which breaks the MEASURING tool before the
        # validator gate is ever reached — a control has to exercise the gate
        # it targets, not the instrument in front of it.
        def fn(js, bin_):
            for a in js["accessors"]:
                if a.get("type") == "VEC3" and "min" in a:
                    a["min"] = [float(x) - 7.0 for x in a["min"]]
                    return
        _rw(path, out, fn)
    else:
        raise ValueError(kind)
    return out


def selftest(path, workdir, cam=None, res=560, samples=16):
    """Prove every gate FIRES.  Each control must fail the gate it targets."""
    os.makedirs(workdir, exist_ok=True)
    ref = glbmeas.measure(path)
    base = panel(path, os.path.join(workdir, "base"), ref=ref, cam=cam,
                 do_respray=True, res=res, samples=samples, tag="nc_base")
    out = {"base": {"all_pass": base["all_pass"], "failed": base["failed"],
                    "summary": summary_line(base)}, "controls": {}}
    want = {
        "glass_cut": ("glass_area", True),
        "tyre_pale": ("tyres_black", False),
        # CORRECTED after the first selftest run: I predicted this would be
        # caught by the respray gate and it was NOT — it was caught by the
        # BINDING half of `tyres_black`, because a material bound to nothing
        # owns no pixels for a respray to move.  The respray gate now also
        # requires Tyre_Rubber and glass to be PRESENT in the render, so both
        # gates catch it; the expectation recorded here is the one that was
        # measured, and both are asserted.
        "tyre_bound_to_paint": (("tyres_black", "respray"), True),
        "drop_normals": ("normals", False),
        "break_validator": ("validator", False),
        "strip_extensions": ("glass_material_written", False),
        "windscreen_to_paint": ("glass_regions", False),
    }
    for kind, (gate, needs_render) in want.items():
        cp = os.path.join(workdir, f"NC_{kind}.glb")
        make_control(path, cp, kind)
        try:
            p = panel(cp, os.path.join(workdir, kind), ref=ref, cam=cam,
                      do_respray=needs_render, res=res, samples=samples, tag=kind)
            want_g = gate if isinstance(gate, tuple) else (gate,)
            fired = all(x in p["failed"] for x in want_g)
            row = {"gate": list(want_g), "fired": bool(fired), "failed": p["failed"],
                   "summary": summary_line(p)}
            if kind in ("glass_cut", "strip_extensions", "windscreen_to_paint"):
                # the whole point: the probe must STILL pass while the paired
                # figure fails.  Three separate defects, one blind probe.
                row["probe_still_clear"] = bool(
                    p["checks"]["glazing_verdict"]["pass"])
        except SystemExit as e:
            fired = True
            row = {"gate": gate if isinstance(gate, str) else list(gate),
                   "fired": True, "refused_with": str(e)[:300]}
        out["controls"][kind] = row
        os.remove(cp)
    out["all_fired"] = all(v["fired"] for v in out["controls"].values())
    out["base_clean"] = bool(base["all_pass"])
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("glb")
    ap.add_argument("--work", default="gatework")
    ap.add_argument("--ref")
    ap.add_argument("--json")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--no-respray", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        r = selftest(a.glb, a.work)
        print(json.dumps(r, indent=1))
    else:
        ref = json.load(open(a.ref)) if a.ref else None
        r = panel(a.glb, a.work, ref=ref, do_respray=not a.no_respray)
        print(summary_line(r))
    if a.json:
        json.dump(r, open(a.json, "w"), indent=1, default=str)
