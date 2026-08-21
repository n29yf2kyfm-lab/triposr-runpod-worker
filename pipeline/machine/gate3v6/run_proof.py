"""GATE 3 v6 — proof-package orchestrator (CPU side).

    python3 run_proof.py <target.glb> <TAG> <outroot> [--baseline <v0.glb> --baseline-tag V0]

Emits the render jobs, runs Blender once per job, and composes:
  * the 15-item proof package (each >= 2048 px)
  * the canonical 8-view sheet (per-tile fit, 75-85% occupancy) and a
    constant-scale companion sheet
Every camera parameter, exposure number and measured occupancy is written to
PROOF_INDEX.md and index.json - nothing in either is asserted, all of it is read
back off the rendered frames.
"""
import argparse, json, math, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import plan as planner                                            # noqa: E402
import compose as C                                               # noqa: E402

BLENDER = "/usr/bin/blender"
# G3V6_RES_SCALE / G3V6_SAMP_SCALE let the whole package be dry-run at a
# fraction of the cost before the expensive pass. A dry run at 0.15/0.1 proves
# every view spec actually renders what it claims in about two minutes.
_RS = float(os.environ.get("G3V6_RES_SCALE", "1"))
_SS = float(os.environ.get("G3V6_SAMP_SCALE", "1"))
_r = lambda wh: [max(64, int(round(wh[0] * _RS / 2) * 2)),
                 max(64, int(round(wh[1] * _RS / 2) * 2))]
_s = lambda n: max(1, int(round(n * _SS)))
RES_MAIN = _r([2560, 2048])
RES_WIRE = _r([3072, 2458])
RES_TILE = _r([1600, 1280])
SAMPLES_LIT = _s(48)
SAMPLES_CLAY = _s(48)
SAMPLES_FLAT = 1
SAMPLES_ZEBRA = _s(96)


def sh(cmd, log_path):
    with open(log_path, "w") as lf:
        p = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT)
    return p.returncode


def run_blender(job, jobpath, marker, log_path):
    """Runs one render job. GREPS FOR OUR OWN DONE MARKER, never for Blender's
    exit - this container has no OpenImageDenoiser and a failed render dies
    AFTER 'Blender quit' prints, silently leaving stale frames."""
    if os.path.exists(marker):
        os.remove(marker)
    with open(jobpath, "w") as f:
        json.dump(job, f, indent=1)
    t = time.time()
    rc = sh([BLENDER, "-b", "--python", os.path.join(HERE, "render_job.py"),
             "--", jobpath], log_path)
    ok = os.path.exists(marker)
    print("  blender rc=%d  marker=%s  %.0fs" % (rc, "YES" if ok else "MISSING",
                                                 time.time() - t))
    if not ok:
        with open(log_path) as f:
            tail = f.read()[-4000:]
        raise RuntimeError("render job %s produced NO DONE MARKER.\n%s"
                           % (os.path.basename(jobpath), tail))
    return True


# --------------------------------------------------------------- view specs

SHEET_ORDER = [
    ("s_front",      270, "FRONT"),
    ("s_frontleft",  315, "FRONT-LEFT 3/4"),
    ("s_left",         0, "LEFT"),
    ("s_rearleft",    45, "REAR-LEFT 3/4"),
    ("s_rear",        90, "REAR"),
    ("s_rearright",  135, "REAR-RIGHT 3/4"),
    ("s_right",      180, "RIGHT"),
    ("s_frontright", 225, "FRONT-RIGHT 3/4"),
]
SHEET_ELEV = 10.0


def sheet_views(ly, occ=0.80, ortho_scale=None, suffix=""):
    out = []
    for vid, az, _lab in SHEET_ORDER:
        v = {"id": vid + suffix, "az": az, "elev": SHEET_ELEV, "pass": "matte",
             "cam": "ortho", "res": RES_TILE, "samples": SAMPLES_LIT,
             "target_y_gltf": ly, "ground": True, "ground_grey": 0.45,
             "world_grey": 0.22, "probe_px": 448}
        if ortho_scale is None:
            v["occ"] = occ
        else:
            v["ortho_scale"] = ortho_scale
            v["shift"] = [0.0, 0.0]
        out.append(v)
    return out


def proof_views(ly, groups, boxes_lo, boxes_hi, lamp_centre):
    """The 15-item proof package. Items 1,4,5,6,7,8,10 deliberately SHARE one
    canonical front camera so the passes are matched frame-for-frame."""
    front = dict(az=270, elev=0.0, cam="ortho", target_y_gltf=ly, occ=0.80,
                 no_shift_x=True, res=RES_MAIN)
    frontkit = sorted(groups["frontkit"])
    lamps = sorted(groups["lamps"])
    V = []

    # 1 straight ORTHOGRAPHIC front at headlamp height, neutral matte
    V.append(dict(id="p01_ortho_front_lamp_height", pass_="matte",
                  samples=SAMPLES_LIT, ground=False, **front))
    # 2/3 front three-quarters (az 305 / 215 per the verified mapping)
    V.append(dict(id="p02_front_left_34", az=305, elev=6.0, cam="ortho",
                  target_y_gltf=ly, occ=0.80, res=RES_MAIN, pass_="matte",
                  samples=SAMPLES_LIT, ground=True, ground_grey=0.45))
    V.append(dict(id="p03_front_right_34", az=215, elev=6.0, cam="ortho",
                  target_y_gltf=ly, occ=0.80, res=RES_MAIN, pass_="matte",
                  samples=SAMPLES_LIT, ground=True, ground_grey=0.45))
    # 4 neutral clay front
    V.append(dict(id="p04_clay_front", pass_="clay", samples=SAMPLES_CLAY,
                  ground=False, **front))
    # 5 wireframe front (higher res: sub-pixel wires on a dense mesh, WITH AA -
    # a 1 px wire without anti-aliasing reads as noise, not as topology)
    w = dict(front); w["res"] = RES_WIRE
    V.append(dict(id="p05_wireframe_front", pass_="wire", wire_px=0.75,
                  samples=_s(24), filter_size=1.3, adaptive=True,
                  ground=False, **w))
    # 6 normal diagnostic
    V.append(dict(id="p06_normals_front", pass_="normals", samples=SAMPLES_FLAT,
                  ground=False, **front))
    # 7 zebra / reflection lines
    # auto_exposure STAYS ON here. It was disabled at first on the theory that
    # pulling the bright bands down would flatten the contrast the pass exists to
    # show - that was wrong: exposure is a linear scale, so it moves both bands
    # together and the stripe CONTRAST RATIO is unchanged. Measured: with it off
    # the bands clipped 6.02% of car pixels, which hides surface inside the blown
    # bands, and the owner's spec forbids exactly that.
    V.append(dict(id="p07_zebra_front", pass_="zebra", samples=SAMPLES_ZEBRA,
                  ground=False, n_stripes=26, **front))
    # 8 material-ID front (flat emission, AA off, 1 sample)
    V.append(dict(id="p08_matid_front", pass_="matid", samples=SAMPLES_FLAT,
                  ground=False, **front))
    # 9 reference overlay - perspective matched to the reference photo EXIF
    #   (Canon EOS 200D, APS-C sensor 22.3 mm, 50 mm)
    V.append(dict(id="p09_ref_match_34", az=305, elev=5.0, cam="persp",
                  lens=50.0, target_y_gltf=ly * 0.92, res=RES_MAIN,
                  pass_="matte", samples=SAMPLES_LIT, ground=True,
                  ground_grey=0.30, radius_mult=2.2))
    # 10 symmetry overlay source = the canonical front (no_shift_x already set)
    #    (composed in post from p01; no extra render)
    # 11 front assembly exploded — the body shell stays as CONTEXT, the bulk
    #    inner/glass/wheel shells are hidden so every front component reads.
    bulk = sorted(set(groups["interior"]) | set(groups["glass"]) | set(groups["wheels"]))
    # az 330 (nearly side-on), body shell HIDDEN, 0.30 m per layer: at az 305
    # with the shell present the layers overlapped and half the components were
    # occluded by the nose, which defeats the whole point of the view.
    V.append(dict(id="p11_front_exploded", az=330, elev=14.0, cam="ortho",
                  occ=0.92, res=RES_MAIN, pass_="explode_id",
                  samples=SAMPLES_FLAT, ground=False,
                  hide=sorted(set(bulk) | set(groups["base"])),
                  fit_objects=frontkit, aim="fit",
                  explode=dict(axis_blender=[-1, 0, 0], spacing=0.30,
                               ranks=planner.explode_ranks(BOXES, frontkit))))
    # 12 headlamp exploded — components only, no shell, so nothing can hide a
    #    part that is not actually there
    # ONLY the lamp nodes. Hiding just the shell was not enough - the intact
    # grille and bumper still buried one side's lamp parts.
    V.append(dict(id="p12_headlamp_exploded", az=330, elev=12.0, cam="ortho",
                  occ=0.86, res=RES_MAIN,
                  pass_="explode_id", samples=SAMPLES_FLAT, ground=False,
                  only=lamps, fit_objects=lamps, aim="fit",
                  explode=dict(axis_blender=[-1, 0, 0], spacing=0.34,
                               ranks=planner.explode_ranks(BOXES, lamps))))
    # 13 old-geometry-removed: same front camera, new components HIDDEN
    V.append(dict(id="p13_kit_hidden_front", pass_="matte", samples=SAMPLES_LIT,
                  ground=False, hide=frontkit, **front))
    V.append(dict(id="p13_kit_hidden_34", az=305, elev=6.0, cam="ortho",
                  target_y_gltf=ly, occ=0.80, res=RES_MAIN, pass_="matte",
                  samples=SAMPLES_LIT, ground=True, hide=frontkit))
    # 14 intersection clearance - two near-plane SECTION cuts zoomed on ONE
    #    headlamp cluster. Zoomed on purpose: a whole-nose section averages the
    #    gaps away and cannot show whether a lens intersects its housing.
    #    The big inner shell is hidden so the lens/housing/body relationship
    #    reads; matID colours + a scale bar make the gaps measurable.
    # One cluster only, and drop anything that straddles the centreline (a
    # legacy whole-width lamp material would stretch the fit off the cluster).
    _side = planner.headlamp_sets(BOXES, lamps)[0] or lamps
    lamp_L = sorted(n for n in _side
                    if not (BOXES[n]["lo"][2] < 0.0 < BOXES[n]["hi"][2])) or lamps
    hide_sec = sorted(set(groups["interior"]) | set(groups["wheels"]))
    V.append(dict(id="p14_section_plan", az=270, elev=90.0, cam="ortho",
                  res=RES_MAIN, pass_="matid", samples=SAMPLES_FLAT,
                  ground=False, occ=0.74, hide=hide_sec,
                  fit_objects=lamp_L, aim="fit",
                  target_y_gltf=lamp_centre[1],
                  section_point_gltf=[lamp_centre[0], lamp_centre[1], lamp_centre[2]]))
    V.append(dict(id="p14_section_transverse", az=0, elev=0.0, cam="ortho",
                  res=RES_MAIN, pass_="matid", samples=SAMPLES_FLAT,
                  ground=False, occ=0.74, hide=hide_sec,
                  fit_objects=lamp_L, aim="fit",
                  section_point_gltf=[lamp_centre[0], lamp_centre[1],
                                      abs(lamp_centre[2])]))
    # 15 before/after uses p01 + p02 matched against the baseline render
    out = []
    for v in V:
        v["pass"] = v.pop("pass_")
        out.append(v)
    return out


BOXES = None


def main():
    global BOXES
    ap = argparse.ArgumentParser()
    ap.add_argument("glb")
    ap.add_argument("tag")
    ap.add_argument("outroot")
    ap.add_argument("--baseline")
    ap.add_argument("--baseline-tag", default="V0")
    ap.add_argument("--ref-dir")
    ap.add_argument("--only", default="all",
                    choices=["all", "sheet", "proof", "baseline", "compose"])
    a = ap.parse_args()

    # PER-TAG png directory. Two runs (V5 source, V6 rebuild) use the same view
    # ids, so a shared directory would silently overwrite the first run's frames
    # while its metadata still pointed at them - the stale-frame class this
    # project has already been burned by.
    png = os.path.join(a.outroot, "png", a.tag)
    sheets = os.path.join(a.outroot, "sheets")
    logs = os.path.join(a.outroot, "logs")
    for d in (png, sheets, logs):
        os.makedirs(d, exist_ok=True)

    BOXES = planner.node_boxes(a.glb)
    groups, geo = planner.classify(BOXES)
    import numpy as np
    lo = np.min([b["lo"] for b in BOXES.values()], axis=0)
    hi = np.max([b["hi"] for b in BOXES.values()], axis=0)
    lamps = sorted(groups["lamps"]) or sorted(groups["frontkit"])[:1]
    ly = float(np.mean([BOXES[n]["c"][1] for n in lamps])) if lamps \
        else float(lo[1] + 0.55 * (hi[1] - lo[1]))
    lc = np.mean([BOXES[n]["c"] for n in lamps], axis=0)
    lc = [float(lc[0]), float(ly), float(max(abs(BOXES[n]["c"][2]) for n in lamps))]
    print("tag=%s  ext=%s  headlamp_y=%.4f  lamp_centre=%s  nodes=%d"
          % (a.tag, np.round(hi - lo, 4), ly, [round(x, 3) for x in lc], len(BOXES)))
    print("  groups:", {k: len(v) for k, v in groups.items()})

    state = {"tag": a.tag, "glb": a.glb, "ext_gltf": (hi - lo).tolist(),
             "headlamp_height_gltf_y": ly, "groups": groups,
             "n_nodes": len(BOXES)}

    # ---------------- job A: canonical 8-view sheet (per-tile fit) ---------
    if a.only in ("all", "sheet"):
        # The sheet aims at the car's MID-HEIGHT (identical for all eight tiles);
        # only proof item 1 is pinned to headlamp height, per the spec.
        mid_y = float((lo[1] + hi[1]) / 2.0)
        state["sheet_target_y_gltf"] = mid_y
        jobA = {"glb": a.glb, "outdir": png, "name": "%s_sheet" % a.tag,
                "done_marker": os.path.join(png, "_DONE_%s_sheet" % a.tag),
                "views": sheet_views(mid_y)}
        print("[A] 8-view sheet, per-tile fit ...")
        run_blender(jobA, os.path.join(a.outroot, "job_%s_sheet.json" % a.tag),
                    jobA["done_marker"], os.path.join(logs, "%s_sheet.log" % a.tag))
        # constant-scale companion: reuse the widest tile's ortho scale
        m = json.load(open(os.path.join(png, "_meta_%s_sheet.json" % a.tag)))
        S = max(v["ortho_scale"] for v in m["views"].values())
        jobA2 = {"glb": a.glb, "outdir": png, "name": "%s_sheetC" % a.tag,
                 "done_marker": os.path.join(png, "_DONE_%s_sheetC" % a.tag),
                 "views": sheet_views(mid_y, ortho_scale=S, suffix="_c")}
        print("[A2] 8-view sheet, CONSTANT scale S=%.4f ..." % S)
        run_blender(jobA2, os.path.join(a.outroot, "job_%s_sheetC.json" % a.tag),
                    jobA2["done_marker"], os.path.join(logs, "%s_sheetC.log" % a.tag))
        state["const_ortho_scale"] = S

    # ---------------- job B: 15-item proof package ------------------------
    if a.only in ("all", "proof"):
        jobB = {"glb": a.glb, "outdir": png, "name": "%s_proof" % a.tag,
                "done_marker": os.path.join(png, "_DONE_%s_proof" % a.tag),
                "views": proof_views(ly, groups, lo, hi, lc)}
        print("[B] 15-item proof package ...")
        run_blender(jobB, os.path.join(a.outroot, "job_%s_proof.json" % a.tag),
                    jobB["done_marker"], os.path.join(logs, "%s_proof.log" % a.tag))

    # ---------------- job C: matched baseline renders ---------------------
    if a.baseline and a.only in ("all", "baseline"):
        mb = json.load(open(os.path.join(png, "_meta_%s_proof.json" % a.tag)))
        vs = []
        for vid in ("p01_ortho_front_lamp_height", "p02_front_left_34",
                    "p04_clay_front", "p08_matid_front"):
            src = mb["views"][vid]
            vs.append({"id": vid.replace("p0", "b0") + "_" + a.baseline_tag,
                       "az": src["az"], "elev": src["elev"], "cam": "ortho",
                       "pass": src["pass"], "res": src["res"],
                       "samples": SAMPLES_LIT if src["pass"] != "matid" else SAMPLES_FLAT,
                       "target_y_gltf": src["target_y_gltf"],
                       "ortho_scale": src["ortho_scale"], "shift": src["shift"],
                       "ground": vid == "p02_front_left_34", "ground_grey": 0.45})
        jobC = {"glb": a.baseline, "outdir": png, "name": "%s_base" % a.baseline_tag,
                "done_marker": os.path.join(png, "_DONE_%s_base" % a.baseline_tag),
                "views": vs}
        print("[C] matched baseline renders (%s) ..." % a.baseline_tag)
        run_blender(jobC, os.path.join(a.outroot, "job_%s_base.json" % a.baseline_tag),
                    jobC["done_marker"], os.path.join(logs, "%s_base.log" % a.baseline_tag))

    with open(os.path.join(a.outroot, "state_%s.json" % a.tag), "w") as f:
        json.dump(state, f, indent=1)
    print("RENDERS COMPLETE for", a.tag)


if __name__ == "__main__":
    main()
