#!/usr/bin/env python3
"""qc_evidence.py — the QA evidence pack: eight matched cameras and every
render pass needed to PROVE or REJECT a claim about a finished car.

This is the independent verifier's toolkit. It repairs nothing and it decides
nothing; it produces the images and the numbers a human uses to decide, plus a
manifest saying exactly how each image was made so a later run can be compared
against it.

WHY IT EXISTS. `eyeball_views.py` renders SEVEN views from bbox-derived
cameras and the owner called that insufficient by name: there is no strict
RIGHT-side view (0/45/90/135/180/225/315 — 270 is missing), so a defect living
on one flank could only ever be seen obliquely. It also has one pass. Class-A
review needs the surface passes (clay, zebra), the structure passes (wire,
normals, material IDs) and the isolation passes (glass, interior, body-hidden),
and every one of them has to be shot from the SAME cameras or a before/after
comparison proves nothing.

WHAT IT PRODUCES
  ring        eight matched cameras — front, front-left 3/4, left, rear-left
              3/4, rear, rear-right 3/4, right, front-right 3/4. Identical
              lens, distance, height, target, lighting, ground and resolution;
              the ONLY difference is azimuth, and the manifest proves it by
              recording each camera's world matrix and asserting the invariant.
  ortho       orthographic front / rear / left / right / top.
  passes      beauty, clay, wire, normals, matid (+legend), zebra,
              glass_only, interior_only, body_hidden, backlight.
  exploded    one wheel assembly separated along its axle, and the lamps
              separated from the body.
  turntable   an image sequence, plus an mp4 IF ffmpeg exists.
  sheets      contact sheets with every tile LABELLED with its camera name and
              measured fill fraction.
  manifest    qc_manifest.json — every file, every camera parameter, every
              measured number.

NOSE DIRECTION IS DETECTED, NOT ASSUMED. canon.py deliberately does not
resolve which end is the front ("it does not affect materials or gates"), so
"front" is NOT a fixed azimuth — it differs per mesh. This project has shipped
upside-down and side-on sheets twice by assuming a convention. See
`resolve_axes` and `detect_nose` for the signals, their measured scores and
what defeats them. When the evidence is weak the views are labelled
NEUTRALLY (`a000`, `a045`, …) and the manifest says `nose.confident = false`:
a confidently wrong "front" is worse than an honest "undetermined".

FOUR TRAPS THIS FILE PAYS FOR, ALL MEASURED HERE, NOT INHERITED
  1. CLIP PLANES. Blender's default camera clip_end is 1000 and a catalogue car
     is modelled in CENTIMETRES (a 2009 Avensis is 480 units long), so a
     matched ring at 2.3x the diagonal sits at ~1150 units — past the far
     plane. The render comes back EMPTY, with no error and rc=0. Measured:
     the front/rear views of that car rendered (nearest surface 913 < 1000)
     and both flank views came back alpha=0.0000, which reads as "the car is
     missing". Clip planes are now derived from the model scale.
  2. THE AXIS MAP HAS A SIGN. glTF (x,y,z) -> Blender (x,-z,y): the LENGTH
     axis flips too, not just the up axis. Getting this wrong cost the first
     ground-truth read of this tool — four cars whose length is on glTF Z had
     their "front" and "rear" tiles swapped, which made three good nose
     signals look like they were wrong on every fastback. Verified by slab
     fingerprint, not by memory: glTF z-max slab (n=838, x_ptp 162.97) is
     Blender y-MIN slab (n=870, x_ptp 163.99).
  3. AgX. Blender 4 defaults to the AgX view transform, which once clipped a
     tyre to pure white here and manufactured a defect that took four control
     renders to disprove. Every run therefore begins with a CALIBRATION
     render — a flat 0.22 world — and asserts it lands at sRGB ~130 with 0%
     clipped before any evidence frame is trusted. The result is in the
     manifest as `calibration`.
  4. ONE-SIDED KEY LIGHT. The production rig's key is one-sided, which makes a
     MAJORITY of cars read as a 2-vs-2 brightness split by side; that has been
     misdiagnosed as a per-side wheel defect more than once. This rig's lights
     are MIRROR-SYMMETRIC about the car's length-vertical plane, and the
     manifest records `lighting_symmetry` — the measured brightness difference
     between each left/right camera pair. A symmetric car must come back near
     zero, and if it does not, the rig is at fault and not the car.

EEVEE cannot initialise in this container (EGL is absent), so CYCLES with
use_denoising=False is the only combination that renders; this build has no
OIDN either.

Run:
  python3 qc_evidence.py <car.glb> <outdir> [--passes beauty,clay,...]
                         [--res 1000] [--samples 24] [--turntable 36]
                         [--nose auto|+|-] [--fit ring|per-view] [--no-sheets]

The same file is re-entered under Blender by the driver
(`blender -b --python qc_evidence.py -- --worker plan.json`); bpy and trimesh
are imported on opposite sides of that fence and never together.
"""
import argparse
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile

# --------------------------------------------------------------------------
# The two halves of this file never share an interpreter: the driver runs under
# system python3 (trimesh + PIL, no bpy) and the worker runs under Blender
# (bpy + numpy, no trimesh and NO PIL — checked: Blender 4.0.2 here has numpy
# 2.5.1 and no PIL). Every pixel measurement is therefore done driver-side on
# the saved PNG, which also removes Blender's colour-management from the
# answer entirely — see the AgX trap above.
# --------------------------------------------------------------------------
IN_BLENDER = "--worker" in sys.argv

VIEW_NAMES = ["front", "front_left", "left", "rear_left",
              "rear", "rear_right", "right", "front_right"]
VIEW_AZ = [0, 45, 90, 135, 180, 225, 270, 315]
NEUTRAL_NAMES = ["a%03d" % a for a in VIEW_AZ]
ORTHO = ["ortho_front", "ortho_rear", "ortho_left", "ortho_right", "ortho_top"]
ALL_PASSES = ["beauty", "clay", "wire", "normals", "matid", "zebra",
              "glass_only", "interior_only", "body_hidden", "backlight"]
# Passes that MOVE geometry. They run last and are never restored, so a
# destructive crop cannot contaminate an analysis pass rendered after it.
EXPLODE_PASSES = ["exploded_wheel", "exploded_lamps"]

GLASS_TOK = ("glass", "window", "windscreen", "windshield", "screen", "glazing",
             "glas", "scheibe", "vidro", "fenster")
# A material called "mirror" is a mirror FINISH (chrome), not the door mirror —
# measured on catalogue cars, where it decorates trim all over the car. It must
# never be read as a position cue. Same for the interior rear-view mirror,
# which contains "rear" and sits at the FRONT of the cabin.
GLASS_NOT = ("mirror", "rearview", "rear_view", "icon", "button", "instrument",
             "dash", "aircondition")
BODY_TOK = ("carpaint", "paint", "body", "shell", "lack")
INTERIOR_TOK = ("interior", "cabin", "seat", "dash", "trim", "cockpit")
LAMP_TOK = ("lamp", "headlight", "headlamp", "taillight", "taillamp",
            "tail_light", "head_light", "lens", "light")
WHEEL_TOK = ("tyre", "tire", "rubber", "rim", "alloy", "wheel", "hub",
             "brake", "disc", "disk", "caliper", "spoke")

# Deterministic ID palette: sorted material name -> colour, so two runs of the
# matid pass on the same car produce the SAME colours and are comparable.
ID_PALETTE = [(0.90, 0.16, 0.16), (0.16, 0.48, 0.92), (0.18, 0.80, 0.32),
              (0.98, 0.76, 0.10), (0.80, 0.20, 0.86), (0.10, 0.84, 0.86),
              (0.98, 0.48, 0.10), (0.60, 0.60, 0.62), (0.42, 0.16, 0.72),
              (0.55, 0.80, 0.15), (0.95, 0.55, 0.65), (0.30, 0.30, 0.55)]


# ==========================================================================
#  DRIVER SIDE — geometry analysis, camera solve, sheets, manifest
# ==========================================================================
if not IN_BLENDER:
    import numpy as np


def _load_scene(path):
    """trimesh scene with node transforms BAKED IN.

    `geometry.values()` alone drops node transforms, so a bbox measured from
    them is in a different frame from the vertices — the instance-collapse
    class of bug canon.py already records.
    """
    import trimesh
    sc = trimesh.load(path, force="scene")
    for node in sc.graph.nodes_geometry:
        T, gname = sc.graph[node]
        if T is not None and not np.allclose(T, np.eye(4)):
            sc.geometry[gname].apply_transform(T)
            sc.graph.update(frame_to=node, matrix=np.eye(4), geometry=gname)
    return sc


def is_draco(path):
    """True if the glTF declares Draco. trimesh here CANNOT decode it and
    returns placeholder ZEROS with only a warning — a car whose extents come
    back [0,0,0] has not failed, it has silently lied."""
    with open(path, "rb") as fh:
        head = fh.read(4)
        if head != b"glTF":
            return False
        fh.seek(12)
        jlen = struct.unpack("<I", fh.read(4))[0]
        fh.seek(20)
        try:
            j = json.loads(fh.read(jlen))
        except Exception:                                       # noqa: BLE001
            return False
    return "KHR_draco_mesh_compression" in (j.get("extensionsUsed") or [])


def decode_draco(path, workdir):
    """`gltf-transform copy` decodes Draco. Without it trimesh reads zeros."""
    out = os.path.join(workdir, "decoded.glb")
    r = subprocess.run(["gltf-transform", "copy", path, out],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        raise SystemExit("REFUSED: Draco input and gltf-transform failed: "
                         + (r.stderr or "")[-400:])
    return out


def _spread_profile(V, axis, nbins=20):
    """Per-slab cross-section SIZE along `axis`, as a fraction of the whole.

    This is the up-axis test. A car's roof slab spans ~40% of the length while
    its underbody slab spans ~95%; across the WIDTH axis both flanks span the
    full length, so that profile is symmetric.

    It replaced a footprint/occupancy measure that was MEASURED to fail: on a
    catalogue car carrying a full interior the occupancy asymmetry was 0.003
    against a runner-up of 0.0026 — a coin flip — and it put the 2009 Avensis
    on its side. A bounding-box footprint failed differently and worse: on
    golf_final.glb a single stray low vertex dragged the minimum below the
    tyres, so the bottom 8% slab held 1,693 stray verts with a 0.61 bbox area
    against the roof's 2.45, and the car rendered UPSIDE DOWN. Percentile
    clipping plus a spread (not a count, not a bbox) fixes both.

    Measured on 8 cars (2 machine-pipeline, 6 catalogue, 4 marques): asymmetry
    0.34-0.57 against a runner-up axis of 0.002-0.038. 8/8, never close.
    """
    other = [i for i in range(3) if i != axis]
    lo, hi = np.percentile(V[:, axis], [1, 99])
    if hi <= lo:
        return None
    P = V[(V[:, axis] >= lo) & (V[:, axis] <= hi)]
    if len(P) < 200:
        return None
    b = np.clip(((P[:, axis] - lo) / (hi - lo) * nbins).astype(int), 0, nbins - 1)
    total = [float(np.ptp(np.percentile(V[:, other[i]], [1, 99]))) for i in (0, 1)]
    prof = np.zeros(nbins)
    for k in range(nbins):
        q = P[b == k]
        if len(q) < 20:
            continue
        s = 1.0
        for i in (0, 1):
            p2, p98 = np.percentile(q[:, other[i]], [2, 98])
            s *= max(p98 - p2, 0.0) / max(total[i], 1e-9)
        prof[k] = s
    return prof


def resolve_axes(V):
    """(length, up, width) axis indices plus the up SIGN, in the file's frame.

    Length is the largest extent — safe for a car. Up is decided by
    `_spread_profile`, never by extent order alone: extent order says nothing
    about the SIGN, and on a van width and height are close enough that the
    order itself is unsafe.
    """
    ext = V.max(0) - V.min(0)
    L = int(np.argmax(ext))
    cands = []
    for a in range(3):
        if a == L:
            continue
        p = _spread_profile(V, a)
        if p is None:
            continue
        k = max(1, len(p) // 3)
        lom, him = float(p[:k].mean()), float(p[-k:].mean())
        asym = abs(lom - him) / max(lom, him, 1e-9)
        cands.append((asym, a, lom, him))
    if not cands:
        raise SystemExit("REFUSED: cannot resolve the up axis — the mesh has "
                         "no usable cross-section profile")
    cands.sort(reverse=True)
    asym, U, lom, him = cands[0]
    runner = cands[1][0] if len(cands) > 1 else 0.0
    W = [i for i in range(3) if i not in (L, U)][0]
    return {"length_axis": L, "up_axis": U, "width_axis": W,
            "up_sign": 1 if lom >= him else -1,
            "up_asymmetry": round(asym, 4),
            "runner_up_asymmetry": round(runner, 4),
            "margin": round(asym - runner, 4),
            # A small margin means the two candidate axes look alike, i.e. the
            # car is as tall as it is wide. Report it; do not hide it.
            "confident": bool(asym > 0.15 and asym - runner > 0.10),
            "extents": [round(float(e), 4) for e in ext]}


def detect_nose(scene, V, ax):
    """Which end of the length axis is the FRONT. Returns votes + a verdict.

    Every signal here was scored against ground truth read BY EYE from
    rendered front/rear pairs of six cars (VW Golf Mk8 machine build, Toyota
    Yaris machine build, Toyota Avensis T27, Mercedes CLS, Nissan Leaf,
    Porsche Panamera — two body-on-frame conventions, four marques, hatchback
    / liftback / fastback / saloon):

        cabin_centroid    6/6      the cabin sits BEHIND the length centre
        deck_length       6/6      the bonnet deck is longer than the boot deck
        end_bluntness     6/6      the tail cross-section is blunter than the nose
        glass_area        4/6      windscreen bigger than the rear screen
        windscreen_rake   4/6      the front screen rakes nearer 30 deg
        flat_band_run     0/6      DROPPED

    `flat_band_run` scored a perfect ZERO — it is real signal with the sign
    reasoned backwards. It is not included: a metric whose direction I cannot
    derive is a metric I do not understand, and flipping it to make the score
    read 6/6 would be fitting the answer to the test set.

    WHAT DEFEATS THIS, stated plainly because the sample is only six cars and
    every one of them is a conventional front-engine layout:
      * mid- and rear-engined cars (911, Boxster) invert cabin_centroid and
        deck_length together, and they are the two heaviest geometric votes.
      * cab-forward vans and MPVs have almost no bonnet, so deck_length
        collapses toward zero rather than inverting.
      * a pickup inverts end_bluntness — the bed is open and the cab is not.
    In all three the votes disagree, the score falls under threshold, and the
    caller gets `confident: false` and neutral azimuth labels. That is the
    designed outcome, not a failure.

    The NAME vote outranks all of them when it fires, because it is evidence
    from the file rather than an inference about car shape.
    """
    L, U, W, S = ax["length_axis"], ax["up_axis"], ax["width_axis"], ax["up_sign"]
    x = V[:, L].astype(float)
    z = V[:, U].astype(float) * S
    cx = float(x.min() + x.max()) / 2.0
    Lx = float(x.max() - x.min())
    zlo, zhi = np.percentile(z, [1, 99])
    H = float(zhi - zlo)
    votes = []

    # ---- vote: NAMES -----------------------------------------------------
    # Node names first, material names second. A material name is a weaker
    # cue: "mirror" is a chrome FINISH used all over a catalogue car, and
    # reading it as a door mirror mis-signed the nose on the first attempt.
    front_tok = ("headlight", "headlamp", "head_lamp", "bonnet", "hood",
                 "grille", "grill", "windscreen", "windshield", "fog",
                 "radiator", "splitter", "front", "plate_front", "bumper_f")
    rear_tok = ("taillight", "taillamp", "tail_lamp", "rearlight", "boot",
                "trunk", "tailgate", "exhaust", "muffler", "diffuser",
                "spoiler", "backlight", "rear", "plate_rear", "bumper_r")
    fx, rx = [], []
    for name, g in scene.geometry.items():
        try:
            mat = (g.visual.material.name or "")
        except Exception:                                       # noqa: BLE001
            mat = ""
        label = (str(name) + " " + str(mat)).lower()
        if any(t in label for t in ("rearview", "rear_view", "rear view")):
            continue
        c = float(g.vertices[:, L].mean()) - cx
        if any(t in label for t in front_tok):
            fx.append(c)
        elif any(t in label for t in rear_tok):
            rx.append(c)
    if fx and rx:
        d = float(np.mean(fx) - np.mean(rx))
        votes.append(("names_front_vs_rear", 4.0, float(np.sign(d)), abs(d) / Lx))
    elif fx:
        votes.append(("names_front_only", 2.5, float(np.sign(np.mean(fx))),
                      abs(float(np.mean(fx))) / Lx))
    elif rx:
        votes.append(("names_rear_only", 2.5, -float(np.sign(np.mean(rx))),
                      abs(float(np.mean(rx))) / Lx))

    # ---- vote: CABIN CENTROID (6/6) -------------------------------------
    cab = x[z > zlo + 0.62 * H]
    if len(cab) > 50:
        d = float(np.mean(cab)) - cx
        votes.append(("cabin_centroid", 2.0, -float(np.sign(d)), abs(d) / Lx))

    # ---- vote: DECK LENGTH (6/6) ----------------------------------------
    nb = 60
    edges = np.linspace(x.min(), x.max(), nb + 1)
    idx = np.clip(np.digitize(x, edges) - 1, 0, nb - 1)
    prof = np.full(nb, -1e9)
    np.maximum.at(prof, idx, z)
    ok = prof > -1e8
    gh = np.where(ok & (prof > zlo + 0.80 * H))[0]
    if len(gh) > 2:
        lo_run = gh[0] / nb                       # low deck at the -x end
        hi_run = (nb - 1 - gh[-1]) / nb           # low deck at the +x end
        d = lo_run - hi_run
        votes.append(("deck_length", 2.0, -float(np.sign(d)), abs(d)))

    # ---- vote: END BLUNTNESS (6/6) --------------------------------------
    def end_area(sign):
        q = V[x > x.max() - 0.06 * Lx] if sign > 0 else V[x < x.min() + 0.06 * Lx]
        if len(q) < 20:
            return 0.0
        return float(np.ptp(np.percentile(q[:, W], [2, 98]))
                     * np.ptp(np.percentile(q[:, U], [2, 98])))
    a_lo, a_hi = end_area(-1), end_area(+1)
    if max(a_lo, a_hi) > 0:
        d = (a_hi - a_lo) / max(a_hi, a_lo)
        votes.append(("end_bluntness", 1.5, -float(np.sign(d)), abs(d)))

    # A vote whose magnitude is inside the noise floor carries no sign. 1.5%
    # of the car's length is ~6 cm on a Golf; that is not a bonnet.
    live = [v for v in votes if v[2] != 0 and v[3] >= 0.015]
    score = sum(w * s for _, w, s, _ in live)
    total = sum(w for _, w, s, _ in live)
    dissent = max([w for _, w, s, _ in live
                   if np.sign(s) != np.sign(score)] or [0.0])
    confident = bool(total >= 3.5 and abs(score) >= 3.0 and dissent < 2.0)
    return {"votes": [{"signal": n, "weight": w, "sign": int(s),
                       "magnitude": round(float(m), 4),
                       "counted": bool(s != 0 and m >= 0.015)}
                      for n, w, s, m in votes],
            "score": round(float(score), 3),
            "weight_counted": round(float(total), 3),
            "dissent_weight": round(float(dissent), 3),
            "agreement": round(abs(score) / total, 3) if total else 0.0,
            "nose_sign": int(np.sign(score)) if score else 0,
            "confident": confident}


# --- glTF -> Blender frame -------------------------------------------------
# VERIFIED by slab fingerprint on a real car, not from memory (see trap 2):
# glTF (x, y, z) -> Blender (x, -z, y). The SIGN on axis 2 is the part that
# gets forgotten, and forgetting it silently swaps "front" for "rear" on every
# car whose length runs along glTF Z — which is most catalogue cars.
G2B_AXIS = {0: 0, 1: 2, 2: 1}
G2B_SIGN = {0: 1.0, 1: 1.0, 2: -1.0}


def gltf_axis_to_blender(axis, sign=1):
    return G2B_AXIS[axis], G2B_SIGN[axis] * sign


def basis_in_blender(ax, nose_sign):
    """Unit ex (nose), ey (car's LEFT), ez (up) as Blender-frame vectors.

    ey = ez x ex, so with ex forward and ez up, +ey is the car's own left —
    which is the viewer's right when standing in front of the car. The eight
    view names depend on this and nothing else.
    """
    ex = np.zeros(3)
    a, s = gltf_axis_to_blender(ax["length_axis"], nose_sign or 1)
    ex[a] = s
    ez = np.zeros(3)
    a, s = gltf_axis_to_blender(ax["up_axis"], ax["up_sign"])
    ez[a] = s
    ey = np.cross(ez, ex)
    return ex, ey / (np.linalg.norm(ey) + 1e-12), ez


def _cam_basis(cam_loc, target, world_up):
    f = np.asarray(target, float) - np.asarray(cam_loc, float)
    f /= np.linalg.norm(f) + 1e-12                   # camera looks along -Z
    r = np.cross(f, world_up)
    n = np.linalg.norm(r)
    if n < 1e-6:                                     # looking straight down
        r = np.cross(f, np.array([1.0, 0.0, 0.0]))
        n = np.linalg.norm(r)
    r /= n + 1e-12
    u = np.cross(r, f)
    return r, u, f


def _project_fill_dir(P, cam_loc, target, world_up, lens, sensor, res_x, res_y):
    """Fraction of the frame the car's silhouette spans, computed ANALYTICALLY
    from vertices rather than from pixels.

    The pixel measurement is the honest cross-check but it cannot be the
    primary one: the beauty pass carries a shadow-catching ground plane whose
    shadow lands in the alpha channel, so an alpha measurement of THAT pass
    measures the shadow as well as the car. Both numbers go in the manifest,
    and the alpha figure is taken from a pass with no ground plane.
    """
    r, u, f = _cam_basis(cam_loc, target, world_up)
    rel = P - np.asarray(cam_loc, float)
    zc = rel @ f
    keep = zc > 1e-6
    if not keep.any():
        return 0.0, 0.0
    rel, zc = rel[keep], zc[keep]
    xc, yc = rel @ r, rel @ u
    # Blender sensor_fit AUTO: sensor_width applies to the LARGER image side.
    if res_x >= res_y:
        half_x = sensor / 2.0
        half_y = half_x * res_y / res_x
    else:
        half_y = sensor / 2.0
        half_x = half_y * res_x / res_y
    ndc_x = (xc / zc) * (lens / half_x)
    ndc_y = (yc / zc) * (lens / half_y)
    return (float(np.ptp(ndc_x) / 2.0), float(np.ptp(ndc_y) / 2.0))


def solve_ring(P, centre, target, ex, ey, ez, lens, sensor, res_x, res_y,
               cam_height, want=0.80, per_view=False):
    """Distance for the camera ring.

    THE HONEST LIMITATION, stated because the spec asks for both and they
    cannot both hold: eight cameras at an IDENTICAL distance cannot each fill
    75-85% of the frame. A car is ~2.4x longer than it is wide, so at whatever
    distance frames the side view at 80% the front view frames at ~35%. The
    ring is solved so the WIDEST view lands on `want`, every view's fill is
    measured and reported, and `--fit per-view` is offered for the case where
    equal framing matters more than matched cameras. The default is matched
    cameras, because that is what makes two passes comparable.
    """
    def fills(dist):
        out = []
        for az in VIEW_AZ:
            a = math.radians(az)
            loc = centre + dist * (math.cos(a) * ex + math.sin(a) * ey) \
                + cam_height * ez
            fx, fy = _project_fill_dir(P, loc, target, ez, lens, sensor,
                                       res_x, res_y)
            out.append(max(fx, fy))
        return out

    span = float(np.ptp(P, axis=0).max())
    lo, hi = span * 0.25, span * 20.0
    for _ in range(48):                              # bisection on max fill
        mid = (lo + hi) / 2.0
        if max(fills(mid)) > want:
            lo = mid
        else:
            hi = mid
    dist = (lo + hi) / 2.0
    if not per_view:
        return [dist] * 8, fills(dist)
    # per-view: solve each azimuth separately. Cameras are then NOT matched,
    # which the manifest records so nobody compares two of them by mistake.
    dists, got = [], []
    for az in VIEW_AZ:
        a = math.radians(az)
        lo, hi = span * 0.25, span * 20.0
        for _ in range(40):
            mid = (lo + hi) / 2.0
            loc = centre + mid * (math.cos(a) * ex + math.sin(a) * ey) \
                + cam_height * ez
            fx, fy = _project_fill_dir(P, loc, target, ez, lens, sensor,
                                       res_x, res_y)
            if max(fx, fy) > want:
                lo = mid
            else:
                hi = mid
        d = (lo + hi) / 2.0
        loc = centre + d * (math.cos(a) * ex + math.sin(a) * ey) + cam_height * ez
        fx, fy = _project_fill_dir(P, loc, target, ez, lens, sensor, res_x, res_y)
        dists.append(d)
        got.append(max(fx, fy))
    return dists, got


# ---------------------------------------------------------------------------
#  Pixel measurement (driver side, PIL)
# ---------------------------------------------------------------------------
def measure_png(path):
    """Alpha-derived fill plus the clipping numbers.

    `clipped_frac` exists because of the AgX tyre: a blown highlight and a
    white tyre look identical to the eye and different in the histogram. It is
    measured on the SAVED file, so it is the number a reviewer can reproduce
    with any image tool.
    """
    from PIL import Image
    im = Image.open(path).convert("RGBA")
    a = np.asarray(im, dtype=np.uint8)
    alpha = a[:, :, 3]
    rgb = a[:, :, :3].astype(np.float32)
    h, w = alpha.shape
    m = alpha > 128
    out = {"w": w, "h": h, "alpha_area_frac": round(float(m.mean()), 5)}
    if m.any():
        ys, xs = np.nonzero(m)
        bw = (xs.max() - xs.min() + 1) / w
        bh = (ys.max() - ys.min() + 1) / h
        out["fill_bbox_w"] = round(float(bw), 4)
        out["fill_bbox_h"] = round(float(bh), 4)
        out["fill_max_dim"] = round(float(max(bw, bh)), 4)
        sel = rgb[m]
        out["mean_srgb"] = round(float(sel.mean()), 2)
        out["clipped_frac"] = round(float((sel >= 254.5).mean()), 5)
    else:
        out.update({"fill_bbox_w": 0.0, "fill_bbox_h": 0.0, "fill_max_dim": 0.0,
                    "mean_srgb": 0.0, "clipped_frac": 0.0,
                    # An empty frame is the clip-plane failure mode (trap 1).
                    # Say so rather than reporting a serene zero.
                    "EMPTY_FRAME": True})
    return out


def check_calibration(path):
    """A flat 0.22 linear world must land at sRGB ~130 with nothing clipped.

    sRGB(0.22) = 1.055*0.22^(1/2.4) - 0.055 = 0.5065 -> 129.2/255. If this
    comes back near 90 the view transform is AgX and every downstream
    brightness judgement in the pack is void.
    """
    from PIL import Image
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    mean = float(a.mean())
    clip = float((a >= 254.5).mean())
    ok = abs(mean - 129.2) <= 3.0 and clip == 0.0
    return {"expected_srgb": 129.2, "measured_srgb": round(mean, 2),
            "clipped_frac": round(clip, 6), "view_transform": "Standard",
            "pass": bool(ok),
            "note": ("Standard confirmed" if ok else
                     "FAILED — view transform is not Standard, or exposure is "
                     "not 0. Every brightness verdict in this pack is void "
                     "until this passes.")}


# ---------------------------------------------------------------------------
#  Contact sheets
# ---------------------------------------------------------------------------
def contact_sheet(tiles, out_path, title, cols=4, tile_w=520, sub=None):
    """Grid sheet, every tile LABELLED. An unlabelled tile is how a rear got
    reported as a front; the label is the point of the sheet, not decoration.
    """
    from PIL import Image, ImageDraw, ImageFont
    def font(sz):
        try:
            return ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", sz)
        except Exception:                                       # noqa: BLE001
            return ImageFont.load_default()
    if not tiles:
        return None
    probe = Image.open(tiles[0][1])
    tile_h = int(tile_w * probe.height / probe.width)
    lab_h, head_h, pad = 26, 62, 6
    rows = (len(tiles) + cols - 1) // cols
    W = cols * (tile_w + pad) + pad
    H = head_h + rows * (tile_h + lab_h + pad) + pad
    sheet = Image.new("RGB", (W, H), (26, 26, 28))
    d = ImageDraw.Draw(sheet)
    d.text((pad + 4, 10), title, font=font(24), fill=(255, 255, 255))
    if sub:
        d.text((pad + 4, 40), sub, font=font(14), fill=(168, 168, 176))
    f = font(15)
    for i, (label, path) in enumerate(tiles):
        r, c = divmod(i, cols)
        x = pad + c * (tile_w + pad)
        y = head_h + r * (tile_h + lab_h + pad)
        im = Image.open(path).convert("RGBA").resize((tile_w, tile_h),
                                                     Image.LANCZOS)
        bg = Image.new("RGBA", im.size, (243, 243, 245, 255))
        bg.alpha_composite(im)
        sheet.paste(bg.convert("RGB"), (x, y + lab_h))
        d.rectangle([x, y, x + tile_w, y + lab_h - 2], fill=(44, 44, 50))
        d.text((x + 6, y + 5), label, font=f, fill=(240, 240, 245))
    sheet.save(out_path)
    return out_path


# ==========================================================================
#  WORKER SIDE — everything that needs bpy
# ==========================================================================
def run_worker(plan_path):
    import bpy
    import bmesh
    import mathutils
    import numpy as _np

    plan = json.load(open(plan_path))
    outd = plan["outdir"]
    os.makedirs(outd, exist_ok=True)
    sc = bpy.context.scene

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=plan["glb"])
    sc = bpy.context.scene
    meshes = [o for o in sc.objects if o.type == "MESH"]
    if not meshes:
        raise SystemExit("REFUSED: no mesh geometry")

    # ---- render settings ------------------------------------------------
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = plan["samples"]
    sc.cycles.use_denoising = False                  # no OIDN in this build
    sc.view_layers[0].cycles.use_denoising = False
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    sc.render.film_transparent = True
    sc.render.resolution_x = plan["res_x"]
    sc.render.resolution_y = plan["res_y"]
    sc.render.resolution_percentage = 100
    # STANDARD, never AgX — see trap 3. The calibration frame below proves it
    # rather than asserting it.
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.view_settings.exposure = 0.0
    sc.view_settings.gamma = 1.0

    span = plan["span"]
    ex = mathutils.Vector(plan["ex"])
    ey = mathutils.Vector(plan["ey"])
    ez = mathutils.Vector(plan["ez"])

    cam = bpy.data.objects.new("qc_cam", bpy.data.cameras.new("qc_cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.lens = plan["lens"]
    cam.data.sensor_width = plan["sensor"]
    cam.data.sensor_fit = "AUTO"
    # CLIP PLANES FROM THE MODEL SCALE — trap 1. A catalogue car in
    # centimetres puts the ring past Blender's default far plane of 1000 and
    # the frame comes back empty with rc=0.
    far = max(plan["ring_dist"]) if isinstance(plan["ring_dist"], list) \
        else plan["ring_dist"]
    cam.data.clip_start = max(span * 1e-4, 1e-5)
    cam.data.clip_end = float(far) * 12.0 + span * 12.0

    # ---- world ----------------------------------------------------------
    world = bpy.data.worlds.new("qc_world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.06, 0.06, 0.065, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 1.0
    sc.world = world

    def sun(name, az_deg, el_deg, energy):
        """A sun aimed at the car from (azimuth, elevation) in the CAR frame."""
        a, e = math.radians(az_deg), math.radians(el_deg)
        d = -(math.cos(e) * math.cos(a) * ex + math.cos(e) * math.sin(a) * ey
              + math.sin(e) * ez)
        lt = bpy.data.objects.new(name, bpy.data.lights.new(name, "SUN"))
        lt.data.energy = energy
        lt.data.angle = math.radians(9)
        sc.collection.objects.link(lt)
        lt.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        return lt

    # MIRROR-SYMMETRIC KEYS — trap 4. Equal energy at +az and -az about the
    # car's length-vertical plane, so a symmetric car CANNOT produce the 2-vs-2
    # brightness split that has twice been misread as a per-side wheel defect.
    # `lighting_symmetry` in the manifest is the measurement that proves it.
    sun("key_left", +52, 44, 2.6)
    sun("key_right", -52, 44, 2.6)
    sun("rim_rear", 180, 68, 1.1)                    # in-plane: symmetric alone

    # ---- ground ---------------------------------------------------------
    ground_z = plan["ground_point"]
    bpy.ops.mesh.primitive_plane_add(size=span * 12.0)
    ground = bpy.context.object
    ground.name = "qc_ground"
    ground.location = mathutils.Vector(ground_z)
    # Align the plane to the car's up axis (catalogue cars are not Z-up).
    ground.rotation_euler = ez.to_track_quat("Z", "Y").to_euler()
    ground.is_shadow_catcher = True                  # contact shadow, clean alpha
    ground.hide_render = True                        # enabled per pass

    carparts = [o for o in meshes]
    orig_slots = [[s.material for s in o.material_slots] for o in carparts]
    orig_hide = [o.hide_render for o in carparts]

    def labels(o):
        out = [o.name.lower()]
        for s in o.material_slots:
            if s.material:
                out.append(s.material.name.lower())
        return out

    def hit(o, toks, block=()):
        ls = labels(o)
        if any(any(b in l for b in block) for l in ls):
            return False
        return any(any(t in l for t in toks) for l in ls)

    def restore():
        for o, sl, hd in zip(carparts, orig_slots, orig_hide):
            o.data.materials.clear()
            for m in sl:
                o.data.materials.append(m)
            o.hide_render = hd
        sc.view_layers[0].material_override = None
        sc.world = world
        ground.hide_render = True

    # ---- shaders --------------------------------------------------------
    def clay_mat():
        m = bpy.data.materials.new("qc_clay")
        m.use_nodes = True
        b = m.node_tree.nodes["Principled BSDF"]
        b.inputs["Base Color"].default_value = (0.58, 0.58, 0.60, 1)
        b.inputs["Roughness"].default_value = 0.42
        b.inputs["Metallic"].default_value = 0.0
        # A LITTLE specular, not none. A perfectly Lambertian clay hides
        # surface waves as effectively as gloss does: the broad specular lobe
        # is what turns a curvature ripple into a visible highlight bend, and
        # that is the entire reason the clay pass exists.
        if "Specular IOR Level" in b.inputs:
            b.inputs["Specular IOR Level"].default_value = 0.5
        elif "Specular" in b.inputs:
            b.inputs["Specular"].default_value = 0.5
        return m

    def wire_mat():
        """Wireframe over clay via the WIREFRAME SHADER NODE, not the modifier.

        The modifier rebuilds geometry: on a 985k-face car it would produce
        millions of extra faces and blow the 15 GB this container has. The
        shader node costs nothing, and `use_pixel_size` keeps the line the same
        weight whether the car is modelled in metres or in centimetres — which
        matters here, because catalogue cars are in centimetres and a
        world-space thickness would render either invisible or solid black.
        """
        m = bpy.data.materials.new("qc_wire")
        m.use_nodes = True
        nt = m.node_tree
        nt.nodes.clear()
        wf = nt.nodes.new("ShaderNodeWireframe")
        wf.use_pixel_size = True
        wf.inputs[0].default_value = 1.1
        base = nt.nodes.new("ShaderNodeBsdfDiffuse")
        base.inputs["Color"].default_value = (0.72, 0.72, 0.74, 1)
        line = nt.nodes.new("ShaderNodeEmission")
        line.inputs["Color"].default_value = (0.02, 0.02, 0.03, 1)
        mix = nt.nodes.new("ShaderNodeMixShader")
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(wf.outputs[0], mix.inputs[0])
        nt.links.new(base.outputs[0], mix.inputs[1])
        nt.links.new(line.outputs[0], mix.inputs[2])
        nt.links.new(mix.outputs[0], out.inputs["Surface"])
        return m

    def normals_mat():
        """World-space normal as colour, with BACKFACES tinted magenta.

        Two signals in one pass. The hue shows the normal direction, so a
        flipped patch lands on the opposite hue; but Cycles flips the shading
        normal to face the viewer, which can hide exactly the case you are
        hunting. The Backfacing output is not fooled by that, so a face whose
        winding is reversed reads magenta whatever its shading normal does.
        """
        m = bpy.data.materials.new("qc_normals")
        m.use_nodes = True
        nt = m.node_tree
        nt.nodes.clear()
        geo = nt.nodes.new("ShaderNodeNewGeometry")
        mad = nt.nodes.new("ShaderNodeVectorMath")
        mad.operation = "MULTIPLY_ADD"
        mad.inputs[1].default_value = (0.5, 0.5, 0.5)
        mad.inputs[2].default_value = (0.5, 0.5, 0.5)
        mixc = nt.nodes.new("ShaderNodeMixRGB")
        mixc.blend_type = "MIX"
        mixc.inputs[2].default_value = (1.0, 0.0, 0.85, 1)
        em = nt.nodes.new("ShaderNodeEmission")
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(geo.outputs["Normal"], mad.inputs[0])
        nt.links.new(mad.outputs[0], mixc.inputs[1])
        nt.links.new(geo.outputs["Backfacing"], mixc.inputs[0])
        nt.links.new(mixc.outputs[0], em.inputs["Color"])
        nt.links.new(em.outputs[0], out.inputs["Surface"])
        return m

    def flat_emissive(name, rgb):
        """Unlit flat colour — the only honest material-ID pass.

        A LIT ID pass shades the ID colour by geometry, so two different
        materials can land on the same tone and the legend stops meaning
        anything. Emission takes lighting out of the answer.
        """
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        nt = m.node_tree
        nt.nodes.clear()
        e = nt.nodes.new("ShaderNodeEmission")
        e.inputs["Color"].default_value = (rgb[0], rgb[1], rgb[2], 1)
        e.inputs["Strength"].default_value = 1.0
        o = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(e.outputs[0], o.inputs["Surface"])
        return m

    def zebra_world():
        """Long horizontal strip lights — the Class-A surface-continuity check.

        Hard-edged emissive bands in ELEVATION reflect off a mirror body as
        continuous lines. A G1 break kinks a line, a G2 break puts a visible
        corner in it, and a panel wave makes it wobble. This is the check that
        catches what a beauty render's soft studio lighting smooths away.
        """
        w = bpy.data.worlds.new("qc_zebra")
        w.use_nodes = True
        nt = w.node_tree
        nt.nodes.clear()
        tc = nt.nodes.new("ShaderNodeTexCoord")
        wave = nt.nodes.new("ShaderNodeTexWave")
        wave.wave_type = "BANDS"
        wave.bands_direction = "Z"
        wave.wave_profile = "SAW"
        wave.inputs["Scale"].default_value = 5.0
        wave.inputs["Distortion"].default_value = 0.0
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.interpolation = "CONSTANT"   # hard stripe edges
        ramp.color_ramp.elements[0].position = 0.0
        ramp.color_ramp.elements[0].color = (0.015, 0.015, 0.02, 1)
        ramp.color_ramp.elements[1].position = 0.5
        ramp.color_ramp.elements[1].color = (1, 1, 1, 1)
        bg = nt.nodes.new("ShaderNodeBackground")
        bg.inputs["Strength"].default_value = 3.0
        out = nt.nodes.new("ShaderNodeOutputWorld")
        nt.links.new(tc.outputs["Generated"], wave.inputs["Vector"])
        nt.links.new(wave.outputs["Fac"], ramp.inputs["Fac"])
        nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
        nt.links.new(bg.outputs[0], out.inputs["Surface"])
        return w

    def chrome_mat():
        m = bpy.data.materials.new("qc_chrome")
        m.use_nodes = True
        b = m.node_tree.nodes["Principled BSDF"]
        b.inputs["Base Color"].default_value = (0.86, 0.87, 0.90, 1)
        b.inputs["Metallic"].default_value = 1.0
        b.inputs["Roughness"].default_value = 0.045
        return m

    # ---- cameras --------------------------------------------------------
    target = mathutils.Vector(plan["target"])
    centre = mathutils.Vector(plan["centre"])

    def aim(loc):
        cam.location = loc
        f = (target - loc).normalized()
        r = f.cross(ez)
        if r.length < 1e-6:
            r = f.cross(mathutils.Vector((1, 0, 0)))
        r.normalize()
        u = r.cross(f)
        # Explicit basis, never to_track_quat alone: track-quat picks its own
        # roll from world Z, and a catalogue car whose up axis is NOT world Z
        # then comes out rolled. Two sheets in this project's history were
        # side-on for exactly this reason.
        cam.rotation_euler = mathutils.Matrix(
            ((r.x, u.x, -f.x), (r.y, u.y, -f.y), (r.z, u.z, -f.z))).to_euler()

    def ring_loc(i):
        a = math.radians(VIEW_AZ[i])
        d = plan["ring_dist"][i] if isinstance(plan["ring_dist"], list) \
            else plan["ring_dist"]
        return centre + d * (math.cos(a) * ex + math.sin(a) * ey) \
            + plan["cam_height"] * ez

    log = {"frames": {}, "cameras": {}, "legend": {}, "notes": []}

    def shoot(path):
        sc.render.filepath = path
        bpy.ops.render.render(write_still=True)

    def record_cam(key):
        m = cam.matrix_world
        log["cameras"][key] = {
            "location": [round(v, 6) for v in cam.location],
            "rotation_euler": [round(v, 6) for v in cam.rotation_euler],
            "matrix_world": [[round(m[r][c], 6) for c in range(4)]
                             for r in range(4)],
            "lens_mm": cam.data.lens, "sensor_mm": cam.data.sensor_width,
            "type": cam.data.type,
            "ortho_scale": (cam.data.ortho_scale
                            if cam.data.type == "ORTHO" else None),
            "clip": [cam.data.clip_start, cam.data.clip_end]}

    # ---- calibration ----------------------------------------------------
    # Rendered FIRST and unconditionally. If the view transform is not
    # Standard, everything after it is void, and it is cheaper to learn that
    # in one 96 px frame than after a whole pack.
    cw = bpy.data.worlds.new("qc_calib")
    cw.use_nodes = True
    cw.node_tree.nodes["Background"].inputs[0].default_value = (0.22, 0.22, 0.22, 1)
    prev_world, prev_ft = sc.world, sc.render.film_transparent
    prev_rx, prev_ry, prev_s = sc.render.resolution_x, sc.render.resolution_y, \
        sc.cycles.samples
    sc.world = cw
    sc.render.film_transparent = False
    sc.render.resolution_x = sc.render.resolution_y = 96
    sc.cycles.samples = 4
    for o in carparts:
        o.hide_render = True
    shoot(os.path.join(outd, "_calibration.png"))
    for o, hd in zip(carparts, orig_hide):
        o.hide_render = hd
    sc.world, sc.render.film_transparent = prev_world, prev_ft
    sc.render.resolution_x, sc.render.resolution_y = prev_rx, prev_ry
    sc.cycles.samples = prev_s

    # ---- pass setup -----------------------------------------------------
    def setup(pname):
        """Configure the scene for one pass. Returns a dict of pass metadata."""
        restore()
        meta = {"ground": False}
        vl = sc.view_layers[0]
        if pname == "beauty":
            ground.hide_render = False
            meta["ground"] = True
        elif pname == "clay":
            vl.material_override = clay_mat()
        elif pname == "wire":
            vl.material_override = wire_mat()
        elif pname == "normals":
            vl.material_override = normals_mat()
        elif pname == "zebra":
            sc.world = zebra_world()
            vl.material_override = chrome_mat()
        elif pname == "matid":
            names = set()
            for o in carparts:
                for s in o.material_slots:
                    names.add(s.material.name if s.material else "<none:%s>" % o.name)
                if not o.material_slots:
                    names.add("<none:%s>" % o.name)
            table = {n: ID_PALETTE[i % len(ID_PALETTE)]
                     for i, n in enumerate(sorted(names))}
            for o in carparts:
                if not o.material_slots:
                    o.data.materials.append(
                        flat_emissive("id_none_" + o.name,
                                      table["<none:%s>" % o.name]))
                    continue
                for i, s in enumerate(o.material_slots):
                    n = s.material.name if s.material else "<none:%s>" % o.name
                    o.material_slots[i].material = flat_emissive(
                        "id_%s_%d" % (o.name, i), table[n])
            log["legend"] = {n: [round(c, 3) for c in col]
                             for n, col in table.items()}
        elif pname == "glass_only":
            for o in carparts:
                o.hide_render = not hit(o, GLASS_TOK, GLASS_NOT)
        elif pname == "interior_only":
            # Body AND glass hidden. Hiding only the body would leave tinted
            # glazing in front of the cabin and make an absent interior read as
            # merely dark — which is a false pass, not a conservative one.
            for o in carparts:
                o.hide_render = hit(o, BODY_TOK) or hit(o, GLASS_TOK, GLASS_NOT)
        elif pname == "body_hidden":
            for o in carparts:
                o.hide_render = hit(o, BODY_TOK)
        elif pname == "backlight":
            bpy.ops.mesh.primitive_plane_add(size=span * 3.0)
            pl = bpy.context.object
            pl.name = "qc_backlight"
            pl.location = centre - ex * (span * 1.4)
            pl.rotation_euler = ex.to_track_quat("Z", "Y").to_euler()
            pl.data.materials.append(flat_emissive("qc_bl", (1.0, 0.0, 0.85)))
            meta["backlight_plane"] = True
        return meta

    def visible_count(pname):
        return sum(1 for o in carparts if not o.hide_render)

    # ---- the passes -----------------------------------------------------
    view_names = plan["view_names"]
    for pname in plan["passes"]:
        meta = setup(pname)
        if pname in ("glass_only", "interior_only", "body_hidden"):
            n = visible_count(pname)
            meta["objects_visible"] = n
            if n == 0:
                # An isolation pass with nothing in it is EVIDENCE (there is no
                # glass / no interior), not an error — but it must be labelled,
                # because an empty frame is also what a broken camera produces.
                log["notes"].append(
                    "%s: no object matched — the frame is empty BY SELECTION, "
                    "not by a camera fault" % pname)
        pdir = os.path.join(outd, pname)
        os.makedirs(pdir, exist_ok=True)
        for i, vn in enumerate(view_names):
            cam.data.type = "PERSP"
            aim(ring_loc(i))
            if pname == plan["passes"][0]:
                record_cam(vn)
            fp = os.path.join(pdir, "%02d_%s.png" % (i + 1, vn))
            shoot(fp)
            log["frames"].setdefault(pname, {})[vn] = fp
        log.setdefault("pass_meta", {})[pname] = meta
        # Orthographic set, only where it earns its cost: beauty (proportion
        # and stance) and clay (surface, with no perspective foreshortening to
        # argue about).
        if pname in ("beauty", "clay"):
            for oname, vec, up in (
                    ("ortho_front", ex, ez), ("ortho_rear", -ex, ez),
                    ("ortho_left", ey, ez), ("ortho_right", -ey, ez),
                    ("ortho_top", ez, ex)):
                cam.data.type = "ORTHO"
                cam.data.ortho_scale = plan["ortho_scale"]
                loc = centre + vec * (span * 3.0)
                cam.location = loc
                f = (centre - loc).normalized()
                r = f.cross(up)
                if r.length < 1e-6:
                    r = f.cross(ex if abs(f.dot(ex)) < 0.9 else ey)
                r.normalize()
                u = r.cross(f)
                cam.rotation_euler = mathutils.Matrix(
                    ((r.x, u.x, -f.x), (r.y, u.y, -f.y),
                     (r.z, u.z, -f.z))).to_euler()
                fp = os.path.join(pdir, "%s.png" % oname)
                shoot(fp)
                log["frames"].setdefault(pname + "_ortho", {})[oname] = fp
                if pname == "beauty":
                    record_cam(oname)
            cam.data.type = "PERSP"

    # ---- turntable ------------------------------------------------------
    if plan["turntable"]:
        restore()
        ground.hide_render = False
        tdir = os.path.join(outd, "turntable")
        os.makedirs(tdir, exist_ok=True)
        sc.render.resolution_x = plan["tt_res_x"]
        sc.render.resolution_y = plan["tt_res_y"]
        sc.cycles.samples = plan["tt_samples"]
        n = plan["turntable"]
        d = plan["ring_dist"][0] if isinstance(plan["ring_dist"], list) \
            else plan["ring_dist"]
        for k in range(n):
            a = math.radians(360.0 * k / n)
            aim(centre + d * (math.cos(a) * ex + math.sin(a) * ey)
                + plan["cam_height"] * ez)
            shoot(os.path.join(tdir, "tt_%04d.png" % k))
        sc.render.resolution_x, sc.render.resolution_y = plan["res_x"], plan["res_y"]
        sc.cycles.samples = plan["samples"]
        log["turntable_dir"] = tdir

    # ---- exploded views (LAST — these MOVE and DELETE geometry) ---------
    def bbox_of(objs):
        lo = [1e30] * 3
        hi = [-1e30] * 3
        for o in objs:
            for c in o.bound_box:
                w = o.matrix_world @ mathutils.Vector(c)
                for i in range(3):
                    lo[i] = min(lo[i], w[i])
                    hi[i] = max(hi[i], w[i])
        return mathutils.Vector(lo), mathutils.Vector(hi)

    def face_centroids(o):
        M = o.matrix_world
        return [(p.index, M @ p.center) for p in o.data.polygons]

    def crop_copy(o, keep_fn, name):
        """Duplicate `o` keeping only faces whose world centroid passes."""
        dup = o.copy()
        dup.data = o.data.copy()
        dup.name = name
        sc.collection.objects.link(dup)
        bm = bmesh.new()
        bm.from_mesh(dup.data)
        bm.faces.ensure_lookup_table()
        M = dup.matrix_world
        kill = [f for f in bm.faces if not keep_fn(M @ f.calc_center_median())]
        bmesh.ops.delete(bm, geom=kill, context="FACES")
        bm.to_mesh(dup.data)
        bm.free()
        if len(dup.data.polygons) == 0:
            bpy.data.objects.remove(dup, do_unlink=True)
            return None
        return dup

    def delete_faces(o, kill_fn):
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bm.faces.ensure_lookup_table()
        M = o.matrix_world
        kill = [f for f in bm.faces if kill_fn(M @ f.calc_center_median())]
        bmesh.ops.delete(bm, geom=kill, context="FACES")
        bm.to_mesh(o.data)
        bm.free()

    def explode_wheel():
        restore()
        ground.hide_render = False
        info = {}
        lo, hi = bbox_of(carparts)
        wheel_objs = [o for o in carparts if hit(o, WHEEL_TOK)]
        info["selector"] = "names" if wheel_objs else "geometric_fallback"
        if not wheel_objs:
            # DOCUMENTED FALLBACK. With no wheel-ish name anywhere, the wheels
            # are found by position instead: geometry in the lower band and
            # outboard of the centreline. It is weaker than a name — an outer
            # sill or a side skirt can fall inside it — so the manifest says
            # which selector ran, and a reviewer can discount the view.
            wheel_objs = list(carparts)
        cen = (lo + hi) / 2.0
        H = abs((hi - lo).dot(ez))
        halfw = abs((hi - lo).dot(ey)) / 2.0
        base = lo.dot(ez) if ez.dot(hi - lo) > 0 else hi.dot(ez)

        def in_wheel_band(p):
            rel = p - cen
            return (abs(rel.dot(ez)) < 0.5 * H * 0.72
                    and abs(rel.dot(ey)) > 0.42 * halfw
                    and (p.dot(ez) - base) < 0.52 * H)

        cands = []
        for o in wheel_objs:
            for _i, c in face_centroids(o):
                if in_wheel_band(c):
                    cands.append((o, c))
        if len(cands) < 50:
            info["result"] = "SKIPPED — no wheel region found"
            log["notes"].append("exploded_wheel: no wheel region found; "
                                "no view produced (a guessed wheel is worse "
                                "than an absent one)")
            return info, []
        # Target the NOSE-side, car's-LEFT wheel, so the label is meaningful.
        sel = [(o, c) for o, c in cands
               if (c - cen).dot(ex) > 0 and (c - cen).dot(ey) > 0]
        if len(sel) < 30:
            sel = cands
        pts = [c for _o, c in sel]
        wc = sum(pts, mathutils.Vector((0, 0, 0))) / len(pts)
        # Radius from tyre-zone faces only. The wheel LABEL bbox includes arch
        # spill, which mis-centred and oversized the box by 40% the first time
        # this was attempted in wheel_swap.py — same trap, same fix.
        rad = max((p - wc).length for p in pts) * 0.62
        info["wheel_centre"] = [round(v, 5) for v in wc]
        info["wheel_radius"] = round(rad, 5)

        def inside(p):
            return (p - wc).length < rad * 1.35

        made = []
        for o in list(carparts):
            has = any(inside(c) for _i, c in face_centroids(o))
            if not has:
                continue
            nslots = max(1, len(o.material_slots))
            for si in range(nslots):
                mname = (o.material_slots[si].material.name
                         if si < len(o.material_slots) and o.material_slots[si].material
                         else o.name)
                def keep(p, o=o, si=si):
                    return inside(p)
                dup = crop_copy(o, keep, "qc_wheelpart_%s_%d" % (o.name, si))
                if dup is None:
                    continue
                # Keep only this material's faces on the duplicate.
                if len(dup.material_slots) > 1:
                    bm = bmesh.new()
                    bm.from_mesh(dup.data)
                    bm.faces.ensure_lookup_table()
                    kill = [f for f in bm.faces if f.material_index != si]
                    bmesh.ops.delete(bm, geom=kill, context="FACES")
                    bm.to_mesh(dup.data)
                    bm.free()
                    if len(dup.data.polygons) == 0:
                        bpy.data.objects.remove(dup, do_unlink=True)
                        continue
                made.append((mname, dup))
            delete_faces(o, inside)                  # remove the original wheel
        if not made:
            info["result"] = "SKIPPED — wheel region isolated no parts"
            return info, []
        # Order outermost-first by mean radius so the tyre travels furthest and
        # the stack reads like an exploded diagram rather than a pile.
        def meanrad(ob):
            M = ob.matrix_world
            ps = [M @ v.co for v in ob.data.vertices]
            return sum((p - wc).length for p in ps) / max(1, len(ps))
        made.sort(key=lambda t: -meanrad(t[1]))
        step = rad * 1.15
        for k, (mname, ob) in enumerate(made):
            ob.location = ob.location + ey * (step * (k + 1))
        info["parts"] = [m for m, _ in made]
        info["result"] = "ok"
        if len(made) == 1:
            # The Supra trap: a donor wheel can ship as ONE material, so a
            # material split yields a single piece. Say so instead of
            # presenting a one-part "explode" as a component proof.
            log["notes"].append(
                "exploded_wheel: the wheel carries ONE material, so the "
                "material split produced a single part — this view proves "
                "separation of the wheel from the car, NOT of tyre from rim")
        return info, made

    def explode_lamps():
        restore()
        ground.hide_render = False
        # `backlight` means the REAR WINDSCREEN as often as it means a tail
        # lamp, and `light` matches it — CLAUDE.md records that trap costing a
        # good car a glazing verdict. Blocked here, along with the named
        # windscreen glasses, so the explode never drags a window off the car.
        # `orangeglass` / `redglass` are deliberately still allowed: on a
        # catalogue car those ARE the lamp lenses.
        lamps = [o for o in carparts
                 if hit(o, LAMP_TOK, ("plate", "backlight", "window",
                                      "windscreen", "windshield",
                                      "clearglass", "greenglass"))]
        info = {"selector": "names", "count": len(lamps)}
        if not lamps:
            # DOCUMENTED FALLBACK — deliberately absent. There is no honest
            # geometric lamp detector: a lamp is not geometrically distinct
            # from the panel around it, and a guessed one would separate the
            # wrong faces and read as a confident component proof. CLAUDE.md's
            # standing rule is that a metric which confidently says "all clear"
            # is worse than no metric; the same holds for a view.
            info["result"] = ("SKIPPED — no lamp-named material or node. There "
                              "is no honest geometric lamp detector; a guessed "
                              "one would produce a confidently wrong view")
            log["notes"].append("exploded_lamps: " + info["result"])
            return info, []
        moved = []
        for o in lamps:
            M = o.matrix_world
            c = sum((M @ mathutils.Vector(b) for b in o.bound_box),
                    mathutils.Vector((0, 0, 0))) / 8.0
            s = 1.0 if (c - centre).dot(ex) >= 0 else -1.0
            o.location = o.location + ex * (s * span * 0.30) + ez * (span * 0.04)
            moved.append(o.name)
        info["moved"] = moved
        info["result"] = "ok"
        return info, moved

    for ename, fn in (("exploded_wheel", explode_wheel),
                      ("exploded_lamps", explode_lamps)):
        if ename not in plan["explode"]:
            continue
        info, _ = fn()
        log.setdefault("explode", {})[ename] = info
        if str(info.get("result", "")).startswith("SKIPPED"):
            continue
        pdir = os.path.join(outd, ename)
        os.makedirs(pdir, exist_ok=True)
        for i, vn in enumerate(view_names):
            cam.data.type = "PERSP"
            aim(ring_loc(i))
            fp = os.path.join(pdir, "%02d_%s.png" % (i + 1, vn))
            shoot(fp)
            log["frames"].setdefault(ename, {})[vn] = fp

    with open(os.path.join(outd, "_render_log.json"), "w") as fh:
        json.dump(log, fh, indent=1)
    print("QC_WORKER_DONE")


# ==========================================================================
#  DRIVER
# ==========================================================================
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("glb")
    ap.add_argument("outdir")
    ap.add_argument("--passes", default=",".join(ALL_PASSES))
    ap.add_argument("--explode", default=",".join(EXPLODE_PASSES))
    ap.add_argument("--res", type=int, default=1000)
    ap.add_argument("--aspect", default="4:3")
    ap.add_argument("--samples", type=int, default=24)
    ap.add_argument("--lens", type=float, default=85.0)
    ap.add_argument("--fill", type=float, default=0.80,
                    help="target frame fill for the WIDEST of the eight views")
    ap.add_argument("--fit", choices=["ring", "per-view"], default="ring")
    ap.add_argument("--turntable", type=int, default=36)
    ap.add_argument("--tt-res", type=int, default=640)
    ap.add_argument("--nose", choices=["auto", "+", "-"], default="auto")
    ap.add_argument("--no-sheets", action="store_true")
    ap.add_argument("--blender", default="blender")
    a = ap.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    work = tempfile.mkdtemp(prefix="qcev_")
    glb = os.path.abspath(a.glb)
    prep = {"draco": False}
    if is_draco(glb):
        # trimesh here cannot decode Draco and returns placeholder ZEROS with
        # only a warning, so every measurement downstream would be silently
        # meaningless. Decode first.
        prep["draco"] = True
        glb = decode_draco(glb, work)

    sc = _load_scene(glb)
    import trimesh
    m = trimesh.util.concatenate([g.copy() for g in sc.geometry.values()])
    V = np.asarray(m.vertices, dtype=float)
    if len(V) < 100 or float(np.ptp(V, axis=0).max()) <= 0:
        raise SystemExit("REFUSED: degenerate or empty geometry in " + a.glb)

    ax = resolve_axes(V)
    nose = detect_nose(sc, V, ax)
    if a.nose != "auto":
        nose["nose_sign"] = 1 if a.nose == "+" else -1
        nose["confident"] = True
        nose["override"] = "supplied by --nose"
    labelled = bool(nose["confident"] and nose["nose_sign"] != 0)
    view_names = VIEW_NAMES if labelled else NEUTRAL_NAMES

    # ---- camera geometry, all in the BLENDER frame ----------------------
    ex, ey, ez = basis_in_blender(ax, nose["nose_sign"] or 1)
    # trimesh vertices are glTF-space; move the sample cloud into Blender space
    # using the VERIFIED map so the analytic solve matches what Blender renders.
    P = np.stack([V[:, 0], -V[:, 2], V[:, 1]], axis=1)
    if len(P) > 120000:                              # solve cost, not accuracy
        P = P[np.random.default_rng(0).choice(len(P), 120000, replace=False)]
    lo, hi = P.min(0), P.max(0)
    bcentre = (lo + hi) / 2.0
    span = float((hi - lo).max())
    height = float(abs(np.dot(hi - lo, ez)))
    ground_pt = bcentre - ez * (np.dot(bcentre - lo, ez))
    # A fixed aim point and a fixed camera height, shared by all eight views:
    # this is what "matched" means, and the manifest asserts it afterwards.
    target = ground_pt + ez * (0.42 * height)
    # Offset from the bbox centre, because the ring is built from that centre.
    # Camera eye line lands at 0.58 x car height above the ground for all eight.
    cam_h_off = float(0.58 * height - np.dot(bcentre - ground_pt, ez))

    ar_w, ar_h = (int(x) for x in a.aspect.split(":"))
    res_x = a.res
    res_y = int(round(a.res * ar_h / ar_w))
    sensor = 36.0

    centre_for_ring = bcentre
    dists, fills = solve_ring(P, centre_for_ring, target, ex, ey, ez, a.lens,
                              sensor, res_x, res_y, cam_h_off, a.fill,
                              per_view=(a.fit == "per-view"))
    ortho_scale = float(max(np.ptp(P @ ex), np.ptp(P @ ey),
                            np.ptp(P @ ez))) / max(a.fill, 0.1)

    plan = {
        "glb": glb, "outdir": os.path.abspath(a.outdir),
        "passes": [p for p in a.passes.split(",") if p],
        "explode": [p for p in a.explode.split(",") if p],
        "res_x": res_x, "res_y": res_y, "samples": a.samples,
        "lens": a.lens, "sensor": sensor,
        "ring_dist": [float(d) for d in dists] if a.fit == "per-view"
        else float(dists[0]),
        "cam_height": float(cam_h_off),
        "centre": [float(v) for v in centre_for_ring],
        "target": [float(v) for v in target],
        "ground_point": [float(v) for v in ground_pt],
        "ex": [float(v) for v in ex], "ey": [float(v) for v in ey],
        "ez": [float(v) for v in ez],
        "span": span, "ortho_scale": ortho_scale,
        "view_names": view_names,
        "turntable": a.turntable,
        "tt_res_x": a.tt_res, "tt_res_y": int(round(a.tt_res * ar_h / ar_w)),
        "tt_samples": max(8, a.samples // 2)}
    plan_path = os.path.join(a.outdir, "_plan.json")
    with open(plan_path, "w") as fh:
        json.dump(plan, fh, indent=1)

    r = subprocess.run([a.blender, "-b", "--python", os.path.abspath(__file__),
                        "--", "--worker", plan_path],
                       capture_output=True, text=True)
    if "QC_WORKER_DONE" not in r.stdout:
        raise SystemExit("REFUSED: the Blender worker did not finish.\n"
                         + r.stdout[-3000:] + "\n" + r.stderr[-2000:])
    log = json.load(open(os.path.join(a.outdir, "_render_log.json")))

    # ---- measure every frame -------------------------------------------
    calib = check_calibration(os.path.join(a.outdir, "_calibration.png"))
    measured = {}
    for pname, frames in log["frames"].items():
        measured[pname] = {vn: measure_png(p) for vn, p in frames.items()}

    # THE MATCHED-CAMERA ASSERTION. Claiming eight identical cameras is not
    # evidence; measuring them is. Distance to target, camera height along the
    # up axis and the lens must be constant across the ring.
    cams = log["cameras"]
    ring = [cams[v] for v in view_names if v in cams]
    inv = {}
    if len(ring) == 8:
        tg = np.asarray(plan["target"])
        d = [float(np.linalg.norm(np.asarray(c["location"]) - tg)) for c in ring]
        hgt = [float(np.dot(np.asarray(c["location"]), ez)) for c in ring]
        lens = [c["lens_mm"] for c in ring]
        inv = {"distance_to_target": [round(x, 5) for x in d],
               "distance_spread": round(max(d) - min(d), 8),
               "height_along_up": [round(x, 5) for x in hgt],
               "height_spread": round(max(hgt) - min(hgt), 8),
               "lens_spread": round(max(lens) - min(lens), 8),
               "matched": bool(a.fit == "ring"
                               and max(d) - min(d) < span * 1e-6
                               and max(hgt) - min(hgt) < span * 1e-6
                               and max(lens) - min(lens) == 0)}

    # LIGHTING SYMMETRY — the proof for trap 4. Mirror pairs about the car's
    # length-vertical plane must render at the same brightness on a symmetric
    # car. A large number here indicts the RIG, not the car.
    sym = {}
    base_pass = "clay" if "clay" in measured else (
        "beauty" if "beauty" in measured else None)
    if base_pass and labelled:
        for lft, rgt in (("left", "right"), ("front_left", "front_right"),
                         ("rear_left", "rear_right")):
            if lft in measured[base_pass] and rgt in measured[base_pass]:
                ml = measured[base_pass][lft]["mean_srgb"]
                mr = measured[base_pass][rgt]["mean_srgb"]
                sym["%s_vs_%s" % (lft, rgt)] = {
                    "mean_srgb": [ml, mr],
                    "abs_diff": round(abs(ml - mr), 3),
                    "rel_diff": round(abs(ml - mr) / max(ml, mr, 1e-6), 5)}
        sym["measured_on"] = base_pass
        sym["interpretation"] = (
            "rel_diff is the LEFT/RIGHT brightness split this rig can produce "
            "on its own. The production rig's one-sided key drives this to a "
            "visible 2-vs-2 split that has been misread as a per-side wheel "
            "defect; anything under ~0.02 here means a side-to-side difference "
            "in the image is a property of the CAR.")

    # ---- turntable ------------------------------------------------------
    tt = {"frames": 0, "mp4": None}
    tdir = log.get("turntable_dir")
    if tdir and os.path.isdir(tdir):
        fr = sorted(f for f in os.listdir(tdir) if f.endswith(".png"))
        tt["frames"] = len(fr)
        tt["dir"] = tdir
        ff = shutil.which("ffmpeg")
        if ff:
            mp4 = os.path.join(a.outdir, "turntable.mp4")
            rr = subprocess.run(
                [ff, "-y", "-framerate", "24", "-i",
                 os.path.join(tdir, "tt_%04d.png"), "-c:v", "libx264",
                 "-pix_fmt", "yuv420p", "-crf", "18", mp4],
                capture_output=True, text=True)
            tt["mp4"] = mp4 if rr.returncode == 0 else None
            tt["ffmpeg"] = "ok" if rr.returncode == 0 else rr.stderr[-400:]
        else:
            # SAID, not silently skipped. A missing video that nobody mentions
            # reads as a video nobody made on purpose.
            tt["ffmpeg"] = ("NOT PRESENT in this container — the %d turntable "
                            "frames are written to %s and no mp4 was made. "
                            "Encode with: ffmpeg -framerate 24 -i "
                            "'%s/tt_%%04d.png' -c:v libx264 -pix_fmt yuv420p "
                            "turntable.mp4" % (tt["frames"], tdir, tdir))
            with open(os.path.join(a.outdir, "make_turntable_mp4.sh"), "w") as fh:
                fh.write("#!/bin/sh\n# ffmpeg was absent when this pack was "
                         "built; run this once it is installed.\n"
                         "ffmpeg -y -framerate 24 -i '%s/tt_%%04d.png' "
                         "-c:v libx264 -pix_fmt yuv420p '%s/turntable.mp4'\n"
                         % (tdir, os.path.abspath(a.outdir)))

    # ---- sheets ---------------------------------------------------------
    sheets = {}
    if not a.no_sheets:
        sdir = os.path.join(a.outdir, "sheets")
        os.makedirs(sdir, exist_ok=True)
        stamp = ("%dx%d  %d spp  CYCLES/Standard  lens %.0fmm  fit=%s"
                 % (res_x, res_y, a.samples, a.lens, a.fit))
        for pname, frames in log["frames"].items():
            tiles = []
            for vn in (view_names if not pname.endswith("_ortho") else ORTHO):
                if vn not in frames:
                    continue
                mm = measured[pname][vn]
                tiles.append(("%s   fill %.0f%%" % (vn, 100 * mm["fill_max_dim"]),
                              frames[vn]))
            if not tiles:
                continue
            out = os.path.join(sdir, "sheet_%s.png" % pname)
            contact_sheet(tiles, out,
                          "%s — %s" % (os.path.basename(a.glb), pname),
                          cols=4 if len(tiles) > 3 else len(tiles), sub=stamp)
            sheets[pname] = out

    manifest = {
        "tool": "pipeline/machine/qc_evidence.py",
        "source_glb": os.path.abspath(a.glb),
        "rendered_glb": glb,
        "input_prep": prep,
        "engine": {"renderer": "CYCLES", "device": "CPU",
                   "denoise": False,
                   "denoise_note": "EEVEE cannot initialise here (no EGL) and "
                                   "this build has no OIDN",
                   "view_transform": "Standard", "samples": a.samples,
                   "resolution": [res_x, res_y]},
        "calibration": calib,
        "axes": ax,
        "nose": nose,
        "view_labelling": {
            "names": view_names,
            "azimuths_deg": VIEW_AZ,
            "labelled": labelled,
            "note": ("views are labelled by DETECTED nose direction"
                     if labelled else
                     "NOSE UNDETERMINED — views are labelled by azimuth only. "
                     "Do not read 'a000' as the front; read the sheet.")},
        "camera": {
            "lens_mm": a.lens, "sensor_mm": sensor, "fit": a.fit,
            "ring_distance": plan["ring_dist"],
            "target": plan["target"], "up": plan["ez"],
            "nose_vector": plan["ex"], "left_vector": plan["ey"],
            "ortho_scale": ortho_scale,
            "matched_camera_check": inv,
            "per_view": {vn: cams.get(vn) for vn in view_names}},
        "fill_fraction": {
            "target": a.fill,
            "analytic": {vn: round(float(f), 4)
                         for vn, f in zip(view_names, fills)},
            "measured_from_alpha": {
                vn: measured.get(base_pass, {}).get(vn, {}).get("fill_max_dim")
                for vn in view_names} if base_pass else {},
            "measured_on_pass": base_pass,
            "note": ("Eight cameras at an IDENTICAL distance CANNOT each fill "
                     "75-85%: a car is ~2.4x longer than it is wide, so the "
                     "distance that frames the side view at 80% frames the "
                     "front at ~35%. The ring is solved so the WIDEST view "
                     "lands on the target; --fit per-view equalises the fill "
                     "instead and gives up matched cameras. Analytic values "
                     "come from the vertices; the alpha values are the "
                     "cross-check and are measured on a pass with NO ground "
                     "plane, because a shadow lands in the alpha channel.")},
        "lighting": {
            "rig": "two SUN keys at +-52 deg azimuth / 44 deg elevation, equal "
                   "energy, mirror-symmetric about the car's length-vertical "
                   "plane; one in-plane rear rim at 68 deg; world 0.06",
            "symmetry_check": sym},
        "passes": {p: {"frames": len(log["frames"].get(p, {})),
                       "meta": log.get("pass_meta", {}).get(p, {})}
                   for p in plan["passes"]},
        "material_id_legend": log.get("legend", {}),
        "explode": log.get("explode", {}),
        "turntable": tt,
        "sheets": sheets,
        "frames": log["frames"],
        "measurements": measured,
        "notes": log.get("notes", [])}

    empty = [(p, v) for p, d in measured.items() for v, mm in d.items()
             if mm.get("EMPTY_FRAME")]
    if empty:
        manifest["notes"].append(
            "EMPTY FRAMES: %s. An empty frame is either an isolation pass with "
            "no matching object (evidence) or the clip-plane failure "
            "(a bug). Check `passes.*.meta.objects_visible` before reading it "
            "as evidence." % ", ".join("%s/%s" % e for e in empty))
    if not calib["pass"]:
        manifest["notes"].append(
            "CALIBRATION FAILED — do not trust any brightness or clipping "
            "judgement from this pack.")

    mpath = os.path.join(a.outdir, "qc_manifest.json")
    with open(mpath, "w") as fh:
        json.dump(manifest, fh, indent=1)
    shutil.rmtree(work, ignore_errors=True)
    print("QC_EVIDENCE_DONE " + json.dumps({
        "manifest": mpath, "sheets": len(sheets),
        "frames": sum(len(v) for v in log["frames"].values()),
        "nose": nose["nose_sign"], "nose_confident": nose["confident"],
        "calibration_pass": calib["pass"],
        "matched": inv.get("matched")}))


if __name__ == "__main__":
    if IN_BLENDER:
        argv = sys.argv[sys.argv.index("--") + 1:]
        run_worker(argv[argv.index("--worker") + 1])
    else:
        main()
