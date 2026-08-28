#!/usr/bin/env python3
"""glass_relabel.py — recover glazing labels on a DARK car, where 2D detection
under-fires and the aperture ends up labelled body.

WHY THIS EXISTS. On the RF67 Golf (near-black paint, dark tinted glass) the
DINO/SAM stage found only slivers even re-run at threshold 0.14, seg_boundary's
exhaustiveness rule then reverted the unstamped remainder to body, and the
shipped GLB had **carpaint filling 93.9% of the windscreen aperture** against
5.9% glass. A blue respray control painted the entire windscreen — proving the
recorded glass_probe blind spot from the other side: a transparent material was
BOUND, just not to the windows. Unanimous council FAIL, 2026-08-27.

THE METHOD, and why each half is necessary:

  SEED — hue. A photo-derived glazing texel is tinted (the cabin behind it
  reads green/blue through the tint); paint on this car is neutral. Measured on
  the RF67: greenness = G - (R+B)/2 over the windscreen aperture reads
  p50 = 3.0, p75 = 19.5, while the DOOR SKIN reads p50 = -0.5 flat. At
  threshold 6 that is 44.6% of the aperture and **0.0% of the door skin** —
  excellent precision, poor recall, which is exactly what a seed should be.

  GROW — crease-bounded flood fill. The other ~55% of the aperture is in
  shadow and hue-neutral, so hue alone cannot finish the job. A windscreen is a
  SMOOTH CONTINUOUS surface bounded by creases at the A-pillars and header, so
  the fill walks face adjacency and stops at a dihedral break. That is a
  geometric property of the aperture, not a threshold fitted to this car.

  ZONE — a band prior only, never a detector. Keeps the fill inside the
  greenhouse and off the roof.

FAILS LOUD, NOT OPEN. If a zone yields no seeds the stage says so and leaves
that zone's labels untouched, rather than inventing glazing. A car whose
glazing is genuinely absent must keep failing the area gate — the gate is what
the owner's opaque-glazing scrap ruling is enforced with.

VALIDATE BOTH DIRECTIONS. --selftest asserts the recovered set covers the
windscreen aperture AND excludes the door skin and the roof panel, and prints
both numbers. A one-directional check would happily relabel the whole car.

LAMPS TOO (--lamps). The identical defect was measured on the same car's
headlamps: Lamp_Lens covered 0.76% of area while the headlamp aperture was
96.6% CARPAINT, so a respray painted the headlamps. Same machinery, different
seed cue — a lamp texel is BRIGHT rather than tinted (measured: luminance > 45
covers 6.7% of the headlamp aperture and 0.0% of both bonnet and door skin).
The seed is weaker than the glass hue seed, which is exactly why the crease-
bounded grow is doing the work in both cases.

Run: python3 glass_relabel.py <car.glb> <labels.npy> <out_labels.npy> [--selftest] [--lamps]
"""
import os
import sys

import numpy as np
import trimesh

GLB, INP, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
SELFTEST = "--selftest" in sys.argv
# --strict restores the pre-2026-08-28 behaviour: a failed selftest kills the
# chain instead of writing the better-scoring arm. Off by default because the
# hard stop is what forced the manual bypass and the two divergent code paths.
STRICT = "--strict" in sys.argv
LAMPS = "--lamps" in sys.argv
TRIM_ON = "--trim" in sys.argv
BODY, GLASS, WHEEL, LAMP, UNSEEN = 0, 1, 2, 3, 4
TRIM = 7          # badge / grille bar / chrome — must never take a respray

LUM_SEED = 45.0        # lamp texels are bright; 0.0% FP on bonnet and door
GREEN_SEED = 6.0        # texel tint above neutral; 0.0% false positives measured
DIHEDRAL_STOP = 26.0    # degrees; a pillar/header crease exceeds this
MIN_SEEDS = 12          # below this a zone is noise, not a window
# Seed-floor, chosen by SWEEP rather than by tuning to one number (RF67 Golf):
#   p10/0.04  glass 14.78%  ws_cov 89.5%  door_FP 3.5%  roof_FP 0.0%
#   p20/0.02  glass 13.26%  ws_cov 88.5%  door_FP 0.4%  roof_FP 0.0%
#   p25/0.02  glass 12.88%  ws_cov 88.3%  door_FP 0.0%  roof_FP 0.0%   <- chosen
#   p30/0.02  glass 12.50%  ws_cov 83.4%  door_FP 0.0%  roof_FP 0.0%
# Those are PRE-boundary numbers. Re-measured on the SHIPPED file after the
# full chain — which is the council's own finding applied to this choice — p30
# wins outright: glass area 10.91% (band PASS, vs 13.46% FAIL at p25) for a
# windscreen aperture of 73.5% against 75.5%. Two points of coverage buys 2.5
# points of area back and turns a failing gate into a passing one.
FLOOR_PCT = 30.0
FLOOR_MARGIN = 0.02

sc = trimesh.load(GLB, force="scene")
for _n in sc.graph.nodes_geometry:
    _T, _g = sc.graph[_n]
    if _T is not None and not np.allclose(_T, np.eye(4)):
        sc.geometry[_g].apply_transform(_T)
        sc.graph.update(frame_to=_n, matrix=np.eye(4), geometry=_g)
m = trimesh.util.concatenate([g for g in sc.geometry.values()])

label = np.load(INP).copy()
if len(label) != len(m.faces):
    raise SystemExit(f"REFUSED: labels {len(label)} != faces {len(m.faces)}")

cent = m.triangles_center
fn = m.face_normals
lo, hi = m.bounds
L = hi[0] - lo[0]
Hh = hi[1] - lo[1]
xf = (cent[:, 0] - lo[0]) / L
yf = (cent[:, 1] - lo[1]) / Hh

# ---- texel tint per face -------------------------------------------------
tint = np.full(len(m.faces), -99.0)
try:
    vis = m.visual
    img = vis.material.baseColorTexture
    uv = np.asarray(vis.uv)
    tex = np.asarray(img.convert("RGB")).astype(float)
    TH, TW, _ = tex.shape
    uvc = uv[m.faces].mean(axis=1)
    ux = (uvc[:, 0] * (TW - 1)).astype(int).clip(0, TW - 1)
    uy = (uvc[:, 1] * (TH - 1)).astype(int).clip(0, TH - 1)
    t = tex[uy, ux]
    tint = t[:, 1] - (t[:, 0] + t[:, 2]) / 2
    print(f"texel tint read for {len(tint)} faces "
          f"(p50 {np.median(tint):.1f}, p99 {np.percentile(tint, 99):.1f})")
except Exception as e:
    raise SystemExit(f"REFUSED: cannot read baseColor texture ({type(e).__name__}: {e}) "
                     "— the hue seed is not optional, this stage has no other seed")

# ---- greenhouse zones ----------------------------------------------------
# Band priors only. n_y > 0.88 in the mid-band is the ROOF and is excluded from
# every zone by construction; a raked screen never sits that flat.
roofish = (fn[:, 1] > 0.88) & (xf > 0.30) & (xf < 0.70)
band = (yf > 0.45) & ~roofish
ZONES = {
    "windscreen": band & (xf > 0.48) & (xf < 0.82) & (fn[:, 1] > 0.15) & (fn[:, 0] > 0.10),
    "backlight":  band & (xf > 0.16) & (xf < 0.50) & (fn[:, 1] > 0.10) & (fn[:, 0] < -0.10),
    "side_left":  band & (fn[:, 2] > 0.55),
    "side_right": band & (fn[:, 2] < -0.55),
}

adj = m.face_adjacency
ang = np.degrees(m.face_adjacency_angles)
smooth = ang < DIHEDRAL_STOP
nbr = {}
for (a, b), ok in zip(adj, smooth):
    if not ok:
        continue
    nbr.setdefault(a, []).append(b)
    nbr.setdefault(b, []).append(a)

new = label.copy()
report = {}
for zname, zmask in ZONES.items():
    seeds = np.where(zmask & (tint > GREEN_SEED))[0]
    if len(seeds) < MIN_SEEDS:
        report[zname] = f"NO SEEDS ({len(seeds)}) — zone left untouched"
        continue
    # SEED-DERIVED FLOOR. The side zones are the dangerous ones: upper door skin
    # is vertical and near-coplanar with the side glass, and a soft beltline
    # crease can be under the dihedral stop, so the fill runs down the door
    # (measured: 11.2% of door skin relabelled). The floor is taken from the
    # SEEDS themselves — glazing does not extend below where glazing was seen —
    # rather than from a hand-tuned height, and a small margin allows for the
    # shadowed lower edge of the pane.
    y_floor = np.percentile(yf[seeds], FLOOR_PCT) - FLOOR_MARGIN
    zmask = zmask & (yf >= y_floor)
    seeds = seeds[yf[seeds] >= y_floor]
    if len(seeds) < MIN_SEEDS:
        report[zname] = f"NO SEEDS above floor ({len(seeds)}) — zone left untouched"
        continue
    seen = set(seeds.tolist())
    stack = list(seeds)
    while stack:
        f = stack.pop()
        for g_ in nbr.get(f, ()):
            if g_ in seen or not zmask[g_]:
                continue
            seen.add(g_)
            stack.append(g_)
    idx = np.fromiter(seen, int)
    keep = idx[(new[idx] == BODY) | (new[idx] == GLASS) | (new[idx] == UNSEEN)]
    new[keep] = GLASS
    report[zname] = (f"{len(seeds)} seeds -> {len(idx)} faces "
                     f"({len(keep)} relabelled to glass)")

# ---- lamps: same seed-and-grow, brightness cue ---------------------------
if LAMPS:
    lum_face = np.full(len(m.faces), -1.0)
    try:
        _t = np.asarray(m.visual.material.baseColorTexture.convert("RGB")).astype(float)
        _th, _tw, _ = _t.shape
        _uvc = np.asarray(m.visual.uv)[m.faces].mean(axis=1)
        lum_face = _t[(_uvc[:, 1] * (_th - 1)).astype(int).clip(0, _th - 1),
                      (_uvc[:, 0] * (_tw - 1)).astype(int).clip(0, _tw - 1)].mean(axis=1)
    except Exception as e:
        raise SystemExit(f"REFUSED: --lamps needs the baseColor texture ({e})")
    zc = np.abs(cent[:, 2] - (lo[2] + hi[2]) / 2) / max((hi[2] - lo[2]) / 2, 1e-9)
    LAMP_ZONES = {
        "head": (xf > 0.84) & (yf > 0.28) & (yf < 0.58) & (zc > 0.28) & (fn[:, 0] > 0.20),
        "tail": (xf < 0.16) & (yf > 0.28) & (yf < 0.62) & (zc > 0.22) & (fn[:, 0] < -0.20),
    }
    for zname, zmask in LAMP_ZONES.items():
        seeds = np.where(zmask & (lum_face > LUM_SEED))[0]
        if len(seeds) < MIN_SEEDS:
            print(f"  lamp/{zname:5s} NO SEEDS ({len(seeds)}) — zone left untouched")
            continue
        seen = set(seeds.tolist())
        stack = list(seeds)
        while stack:
            f = stack.pop()
            for g_ in nbr.get(f, ()):
                if g_ in seen or not zmask[g_]:
                    continue
                seen.add(g_)
                stack.append(g_)
        idx = np.fromiter(seen, int)
        keep = idx[(new[idx] == BODY) | (new[idx] == LAMP) | (new[idx] == UNSEEN)]
        new[keep] = LAMP
        print(f"  lamp/{zname:5s} {len(seeds)} seeds -> {len(idx)} faces "
              f"({len(keep)} relabelled to lamp)")

# ---- trim: badge, grille bar, chrome. Same brightness seed as the lamps, but
# the CENTRE band rather than the outboard one — the lamp zones deliberately
# exclude the centreline, which is exactly where the badge and grille bar sit,
# so they were left as carpaint and a respray painted the badge. Bar item 3
# says identity is kept: badges and grille are identity.
if TRIM_ON:
    if "lum_face" not in dir():
        try:
            _t = np.asarray(m.visual.material.baseColorTexture.convert("RGB")).astype(float)
            _th, _tw, _ = _t.shape
            _uvc = np.asarray(m.visual.uv)[m.faces].mean(axis=1)
            lum_face = _t[(_uvc[:, 1] * (_th - 1)).astype(int).clip(0, _th - 1),
                          (_uvc[:, 0] * (_tw - 1)).astype(int).clip(0, _tw - 1)].mean(axis=1)
        except Exception as e:
            raise SystemExit(f"REFUSED: --trim needs the baseColor texture ({e})")
    zc_t = np.abs(cent[:, 2] - (lo[2] + hi[2]) / 2) / max((hi[2] - lo[2]) / 2, 1e-9)
    TRIM_ZONES = {
        "nose_ctr": (xf > 0.86) & (yf > 0.25) & (yf < 0.55) & (zc_t < 0.32) & (fn[:, 0] > 0.25),
        "tail_ctr": (xf < 0.14) & (yf > 0.28) & (yf < 0.62) & (zc_t < 0.32) & (fn[:, 0] < -0.25),
    }
    for zname, zmask in TRIM_ZONES.items():
        seeds = np.where(zmask & (lum_face > LUM_SEED))[0]
        if len(seeds) < MIN_SEEDS:
            print(f"  trim/{zname:8s} NO SEEDS ({len(seeds)}) — zone left untouched")
            continue
        seen = set(seeds.tolist()); stack = list(seeds)
        while stack:
            f = stack.pop()
            for g_ in nbr.get(f, ()):
                if g_ in seen or not zmask[g_]:
                    continue
                seen.add(g_); stack.append(g_)
        idx = np.fromiter(seen, int)
        keep = idx[new[idx] == BODY]          # never steal from glass or lamp
        new[keep] = TRIM
        print(f"  trim/{zname:8s} {len(seeds)} seeds -> {len(idx)} faces "
              f"({len(keep)} relabelled to trim)")

# CLOSE HOLES INSIDE A PANE. The flood fill stops at creases, which is right at
# the pillars and wrong at the header curve and the shadowed upper corners: a
# handful of faces inside the aperture stay body and still take a respray
# (measured on the RF67 — two patches at the top corners of the windscreen).
# A face inside a zone whose neighbours are overwhelmingly glass is a hole in
# the pane, not a piece of bodywork. Bounded by the zone mask, so it can never
# walk out onto the roof or a door.
zone_any = np.zeros(len(new), bool)
for _z in ZONES.values():
    zone_any |= _z
closed = 0
for _ in range(3):
    is_glass = new == GLASS
    a, b = adj[:, 0], adj[:, 1]
    ng = np.zeros(len(new), np.int32)
    nt = np.zeros(len(new), np.int32)
    np.add.at(ng, a, is_glass[b]); np.add.at(ng, b, is_glass[a])
    np.add.at(nt, a, 1); np.add.at(nt, b, 1)
    fill = zone_any & ~is_glass & (new != TRIM) & (nt >= 2) & (ng * 3 >= nt * 2)   # >=2/3 glass
    if not fill.any():
        break
    new[fill] = GLASS
    closed += int(fill.sum())
print(f"  hole-closing  {closed} faces absorbed into panes")

# ---- ROOF EVICTION -------------------------------------------------------
# THE LEAK THIS EXISTS FOR, measured on the Audi A3 (2026-08-28). The finished
# car rendered with a dark band running over the roof and down the rear quarter
# — a panoramic roof the A3 does not have — and glass_where put a number on it:
# 24.6% of the labelled glazing sat in the top 15% of the car's height, 42.9%
# of it facing up. That is also the whole of the band-gate failure: glass area
# read 13.20% against a 13.0 ceiling, and the roof share alone is ~3.3 points.
#
# STAGE ATTRIBUTION, measured rather than assumed (glass area / roof share):
#     seg_project  3.81%  17.9%      seg_refine   3.84%  17.9%
#     glass_relabel 13.23% 24.9%     seg_boundary 13.20% 24.6%
# So the roof label is BORN upstream (~0.7% of car area) and this stage's fill
# then trebles it (~3.3%). Both had to be caught, and only an eviction can:
# every other step here ADDS glass and none of them can remove what arrived
# already wrong. It runs last so nothing downstream re-adds.
#
# THE DISCRIMINATOR IS |n_x|, NOT HEIGHT. Height alone cannot separate a roof
# panel from the top of a windscreen — they meet. But a roof is near-level
# (n_y high, n_x ~0) while glazing is RAKED, and rake is exactly a longitudinal
# normal component: a screen 30 deg off vertical has n_y 0.50 / n_x 0.87, and
# even a extreme 60 deg screen has n_y 0.87 / n_x 0.50. Requiring |n_x| < 0.35
# therefore cannot reach any real screen, at any rake, which is why the
# windscreen-coverage direction of the selftest is unmoved by this pass.
#
# A PANORAMIC ROOF IS EVICTED TOO, deliberately. It is the rarer car and the
# failure directions are not symmetric: a panoramic roof rendered as paint is a
# missing option, while a solid roof rendered as glass is the "prototype in the
# viewer" look the owner scraps cars for. GLASS_ROOF_EVICT=0 turns it off for a
# car that genuinely has one.
ROOF_EVICT = os.environ.get("GLASS_ROOF_EVICT", "1") == "1"
ROOF_NY = float(os.environ.get("GLASS_ROOF_NY", "0.80"))
ROOF_NX = float(os.environ.get("GLASS_ROOF_NX", "0.35"))
ROOF_YF = float(os.environ.get("GLASS_ROOF_YF", "0.78"))
roof_panel = (fn[:, 1] > ROOF_NY) & (np.abs(fn[:, 0]) < ROOF_NX) & (yf > ROOF_YF)
if ROOF_EVICT:
    eyes = roof_panel & (new == GLASS)
    new[eyes] = BODY
    print(f"  roof-eviction {int(eyes.sum())} glass faces on the roof panel "
          f"-> body (n_y>{ROOF_NY}, |n_x|<{ROOF_NX}, yf>{ROOF_YF})")
else:
    print("  roof-eviction DISABLED (GLASS_ROOF_EVICT=0)")

for k, v in report.items():
    print(f"  {k:11s} {v}")

a_before = float(m.area_faces[label == GLASS].sum()) / float(m.area) * 100
a_after = float(m.area_faces[new == GLASS].sum()) / float(m.area) * 100
print(f"glass area: {a_before:.2f}% -> {a_after:.2f}% of total "
      f"(catalogue band 1.0-13.0, median 5.75)")

# ---- KEEP WHICHEVER LABEL SET SCORES BETTER -----------------------------
# WHY THIS EXISTS. This stage recovers glazing when the 2D projection
# under-detects, which is what a COARSE mesh causes. On a dense mesh the
# projection already sees the glass and this stage's crease-bounded fill has
# no crease to stop against, so it walks onto roof and doors and makes the car
# WORSE. Both directions are measured, same day, same chain (2026-08-28):
#
#   Audi A3, 40,000 faces      WITHOUT this stage -> windscreen almost fully
#                              blue under a respray. The stage is REQUIRED.
#   Tripo Golf, 990,650 faces  WITH this stage -> selftest FAILED (windscreen
#                              31.8%, door FP 4.5%), glass 7.63 -> 9.65%.
#                              WITHOUT it -> clean split, respray HOLDS.
#
# The operator's answer on the day was to bypass the stage BY HAND for the
# dense car. That left two divergent code paths with nothing deciding between
# them — the reviewer council's specific objection: "tomorrow's black Tripo
# car ships a painted windscreen with every gate green."
#
# So the stage now decides for itself, by MEASUREMENT rather than by a
# face-count rule: score the INPUT labels and the OUTPUT labels on the same
# selftest metrics and keep the better set. A face-count threshold would be
# the fifth absolute constant in this pipeline to be calibrated on one mesh
# and wrong on the next; scoring both is calibration-free.
#
# It is NOT a silent fallback. The chosen arm, both scores and the reason are
# printed, and --strict restores the old hard SystemExit for a caller that
# would rather stop than degrade.
def _score(lab):
    """(windscreen coverage by AREA, door false-positive %, roof share of
    glass area). Higher coverage is better; lower FP and roof share better."""
    ws_a = (100 * float(m.area_faces[ws_mask & (lab == GLASS)].sum())
            / float(m.area_faces[ws_mask].sum())) if ws_mask.sum() else 0.0
    d_fp = (100 * float(((lab == GLASS) & door_mask).sum())
            / float(door_mask.sum())) if door_mask.sum() else 0.0
    ga = float(m.area_faces[lab == GLASS].sum())
    r_sh = (100 * float(m.area_faces[roof_panel & (lab == GLASS)].sum()) / ga
            if ga > 0 else 0.0)
    return ws_a, d_fp, r_sh


ws_mask = ZONES["windscreen"]
door_mask = (xf > 0.30) & (xf < 0.55) & (yf > 0.25) & (yf < 0.50) & (np.abs(fn[:, 2]) > 0.7)
_in, _out = _score(label), _score(new)
print(f"arm scores (windscreen AREA cov / door FP / roof share of glass):")
print(f"  input  labels (this stage SKIPPED): {_in[0]:5.1f}% / {_in[1]:4.1f}% / {_in[2]:4.1f}%")
print(f"  output labels (this stage APPLIED): {_out[0]:5.1f}% / {_out[1]:4.1f}% / {_out[2]:4.1f}%")
# A set is disqualified if it leaks onto the door skin or the roof; among the
# admissible ones, more windscreen coverage wins. If both leak, the one that
# leaks less onto the door wins — a painted door is visible, a thin windscreen
# is caught by the respray control downstream.
def _admissible(s):
    return s[1] <= 2.0 and s[2] <= 2.0
if _admissible(_out) and (not _admissible(_in) or _out[0] >= _in[0]):
    chosen, why = new, "APPLIED (scores better or input inadmissible)"
elif _admissible(_in):
    chosen, why = label, "SKIPPED (input labels score better — dense mesh, fill not needed)"
else:
    chosen, why = (new, "APPLIED (neither admissible; output leaks less on the door)") \
        if _out[1] <= _in[1] else (label, "SKIPPED (neither admissible; input leaks less on the door)")
if chosen is label:
    new = label.copy()
print(f"CHOSEN ARM: {why}")

if SELFTEST:
    ws = ZONES["windscreen"]
    door = (xf > 0.30) & (xf < 0.55) & (yf > 0.25) & (yf < 0.50) & (np.abs(fn[:, 2]) > 0.7)
    # FALSE POSITIVES ARE MEASURED AS *ADDED*, not absolute. The input labels
    # already carry some stray glass; scoring those against this stage would
    # make it "fix" something it did not break, and would hide its real error.
    added = (new == GLASS) & (label != GLASS)
    cov = 100 * (new[ws] == GLASS).mean() if ws.sum() else 0.0
    # AND THE SAME THING BY AREA. Coverage was count-only, which is the basis
    # the band gate was moved OFF on 2026-08-19 ("it counted FACES ... AREA is
    # the physical quantity", after glass faces measured 1.58x smaller than
    # body faces on a real mesh). A count-based coverage number can therefore
    # flatter glass without anyone being able to see it happening.
    #
    # ON THIS CAR THE TWO AGREE — A3, 2026-08-28: 70.4% by count, 69.2% by
    # area — which is worth stating plainly, because it is evidence that this
    # particular mesh does NOT have the size disparity that motivated the band
    # gate's change. Printing both is what establishes that; assuming either
    # way would not have.
    #
    # (Recorded because it nearly went the other way: an ad-hoc check of the
    # same aperture read 42.8% glass and looked like a serious regression. That
    # mask had omitted the `~roofish` term, so large roof faces were counted as
    # windscreen aperture and diluted it. The zone masks are not interchangeable
    # with hand-rolled ones — measure through ZONES, or reproduce it exactly.)
    #
    # REPORTED, NOT GATED. The 60% threshold was calibrated against count
    # numbers; swapping the basis underneath it would move a gate with no
    # positive control behind it. Set an area threshold only once a known-good
    # car has been measured through this same mask.
    cov_a = (100 * float(m.area_faces[ws & (new == GLASS)].sum())
             / float(m.area_faces[ws].sum())) if ws.sum() else 0.0
    d_fp = 100 * added[door].mean() if door.sum() else 0.0
    print(f"SELFTEST  windscreen-aperture covered {cov:.1f}% by count, "
          f"{cov_a:.1f}% BY AREA (n={int(ws.sum())})")
    print(f"SELFTEST  door-skin FP (added here)   {d_fp:.1f}% (n={int(door.sum())})")
    # ROOF IS SCORED ABSOLUTE, AND AGAINST THE WHOLE ROOF PANEL. Both halves of
    # that sentence are corrections to a test that reported 0.0% on a car whose
    # roof was visibly glazed (A3, 2026-08-28) — the sixth "gate that could not
    # fire" in this repo, and it hid a defect the eye caught immediately:
    #   * it scored only faces THIS STAGE added, so the ~0.7%-of-car roof glass
    #     arriving from seg_project was invisible to it by construction. The
    #     added-only rule is right for the door (this stage's own fill is the
    #     only thing that reaches it) and wrong for the roof, because the roof
    #     is now EVICTED here — a stage that removes upstream error must be
    #     scored on the result, not on its delta.
    #   * `roofish` is n_y>0.88 over xf 0.30-0.70 — a narrow strip of the
    #     flattest mid-roof. The leak lived on the curved header and the rear
    #     quarter, outside it on both counts. Scored against `roof_panel`, the
    #     same mask the eviction uses, so the test and the fix cannot disagree.
    # Reported as a share of GLASS AREA (what glass_where measures and what the
    # band gate is inflated by), not as a share of roof faces.
    _ga = float(m.area_faces[new == GLASS].sum())
    r_fp = (100 * float(m.area_faces[roof_panel & (new == GLASS)].sum()) / _ga
            if _ga > 0 else 0.0)
    print(f"SELFTEST  roof share of glass AREA    {r_fp:.1f}% "
          f"(n={int(roof_panel.sum())} roof faces)")
    bad = []
    if cov < 60:
        bad.append(f"windscreen coverage {cov:.1f}% < 60%")
    if d_fp > 2:
        bad.append(f"door-skin FP {d_fp:.1f}% > 2%")
    if r_fp > 2:
        bad.append(f"roof share of glass area {r_fp:.1f}% > 2%")
    if bad:
        # The arm-picker above has ALREADY chosen the better of the two label
        # sets, so a failure here describes the CAR, not an unmade decision —
        # and killing the chain is what forced the manual bypass that left two
        # divergent code paths. Report loudly, keep going, and let the respray
        # render be the verdict (the standing rule since 2026-08-28: the only
        # glass verdict is a respray render). --strict restores the hard stop
        # for a caller that would rather not ship a degraded car at all.
        msg = "SELFTEST FAILED: " + "; ".join(bad)
        if STRICT:
            raise SystemExit(msg)
        print(msg + "  [--strict not set: writing the chosen arm anyway; "
                    "the respray control decides]")
    if LAMPS:
        zc2 = np.abs(cent[:, 2] - (lo[2] + hi[2]) / 2) / max((hi[2] - lo[2]) / 2, 1e-9)
        head = (xf > 0.86) & (yf > 0.28) & (yf < 0.55) & (zc2 > 0.30) & (fn[:, 0] > 0.25)
        bonnet = (xf > 0.62) & (xf < 0.82) & (yf > 0.45) & (yf < 0.62) & (fn[:, 1] > 0.7)
        lcov = 100 * (new[head] == LAMP).mean() if head.sum() else 0.0
        b_fp = 100 * ((new == LAMP) & (label != LAMP))[bonnet].mean() if bonnet.sum() else 0.0
        d_fp2 = 100 * ((new == LAMP) & (label != LAMP))[door].mean() if door.sum() else 0.0
        print(f"SELFTEST  headlamp-aperture covered  {lcov:.1f}% (n={int(head.sum())})")
        print(f"SELFTEST  bonnet lamp-FP (added)     {b_fp:.1f}% (n={int(bonnet.sum())})")
        print(f"SELFTEST  door   lamp-FP (added)     {d_fp2:.1f}% (n={int(door.sum())})")
        lbad = []
        if lcov < 55:
            lbad.append(f"headlamp coverage {lcov:.1f}% < 55%")
        if b_fp > 3:
            lbad.append(f"bonnet lamp-FP {b_fp:.1f}% > 3%")
        if d_fp2 > 3:
            lbad.append(f"door lamp-FP {d_fp2:.1f}% > 3%")
        if lbad:
            lmsg = "SELFTEST FAILED (lamps): " + "; ".join(lbad)
            if STRICT:
                raise SystemExit(lmsg)
            print(lmsg + "  [--strict not set: continuing]")
    print("SELFTEST PASSED (both directions)")

np.save(OUT, new)
print(f"wrote {OUT}")
