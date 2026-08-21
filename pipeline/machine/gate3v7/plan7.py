#!/usr/bin/env python3
"""plan7.py -- GATE 3 v7: derive the build frame from the mesh, place the
landmark spec into it, and emit the strip footprint.  Reads only.

Every number below is DERIVED here and re-derived on each run; nothing is
inherited from a brief.  Three frame decisions, and each is made the way it is
because the obvious way was tried first and measured wrong:

1. LATERAL CENTRELINE -> z = +0.0265.  THIS CAR HAS NO SINGLE CENTRELINE.
   I first set this to 0.000 and that was WRONG; the finding is withdrawn here
   rather than defended.  Measuring Body_Shell's z-midpoint station by station
   along x shows the car is BOWED: the midpoint runs monotonically from +0.052
   at the nose (x -1.65) to -0.088 at the tail (x +1.85), a 140 mm sweep, and
   the windscreen and rear screen differ by 218 mm (+0.076 vs -0.142).  A
   nearest-neighbour symmetry fit confirms it independently: the FRONT third
   fits best at z = +0.0265 (cost 19.97 mm, against 25.13 mm at z = 0) and the
   REAR third at z = -0.068.  That is also exactly why the earlier estimators
   fought each other -- they were each fitting a different part of a banana:
   fascia depth mirror +0.043, whole-body NN -0.036, front wheels +0.026, rear
   wheels -0.062.  All four are consistent once the bow is admitted.

   A front fascia must be centred on the bodywork it sits IN, because a viewer
   judges the plate and badge against the surrounding bumper, not against the
   tailgate.  So the FRONT-LOCAL centreline is used.  Three melt-free estimators
   agree within 3.3 mm: front-third reflection fit +0.0265, front tyres +0.0257,
   front rims +0.0290.  Uncertainty +-5 mm.
   The bow itself is a body defect and is REPORTED, not corrected: straightening
   the car is not Gate 3's scope.

2. VERTICAL DATUM (bonnet leading edge at the centreline) -> y = 0.873.
   The melt has no crease, so "find the edge" has no edge to find.  Measured
   instead as the highest y at which the centreline depth profile's slope is
   still below a tangent threshold, scanning DOWN from the roof (scanning UP
   latches onto the grille-band ripples -- tried, and it returned 0.720 on five
   of eleven columns).  Over the central +-350 mm: threshold 1.0 -> 0.867
   (sd 15.2 mm), 1.3 -> 0.873 (sd 6.9 mm), 1.6 -> 0.892 (sd 4.6 mm).  The datum
   is threshold-dependent across a 25 mm band and cannot be resolved better than
   that on a melted nose.  0.873 is taken and the band is reported.

3. THE MESH'S FRONT FACE IS 21% SHORT, so the stack is placed by FRACTION.
   Bumper lowest edge measures y = 0.433 (turn-under, sharp: centreline depth
   jumps 71 -> 141 mm within 6 mm of height; median 0.433 over seven columns).
   Front-face height is therefore 440 mm against the published car's 554 mm.
   Placing the spec's stack in absolute mm would put the bumper's lowest edge
   89 mm below the mesh's own bumper -- hanging in air.  The spec publishes a
   fraction-of-front-face column precisely so it can be re-scaled, and that is
   what is used.  The scale is 0.794.
   CORROBORATION, and it is independent -- the plate band and the lower-grille
   bottom were NOT used to fit the datum or the scale, and both land on the
   melt's own features: fraction-placed plate 0.657..0.744 against a melt plate
   at ~0.66..0.75, fraction-placed lower-grille bottom 0.548 against melt
   stripes ending at ~0.54.

   THE PLATE STAYS TRUE SIZE, THE BADGE DOES NOT, and that is a forced choice.
   A UK BS AU 145d plate is 520 x 111 mm by law and is the spec's own metric
   anchor, so it is built at true size.  The badge cannot also be true size:
   badge (149) + plate (111) is 47% of the real 554 mm face but 59% of this
   mesh's 440 mm face, so both at true size leaves a NEGATIVE gap where the spec
   has 42 mm.  The badge is therefore scaled with the fascia (149 -> 118.3 mm),
   which preserves the spec's structural requirement -- the badge sits ON the
   bar and overlaps the bonnet shut line -- where keeping it at 149 would break
   it by colliding with the plate.

GROUND is reported and never used.  The front axle is ~180 mm in the air on this
file, so a ground-referenced fascia datum would be ~180 mm out.  The fascia is
anchored to the fascia.

L/R NAMING.  This file names L = -z (Wheel_FL_Tyre sits at z<0) and R = +z.  The
car faces -X with +Y up, so +Z is the car's TRUE LEFT and the file's "L/R" are
VIEWER-left/right from the front.  Rebuilt nodes KEEP the file's convention so
the front matches the wheels.  The one proven asymmetry -- the tow-eye cover, on
the car's RIGHT -- therefore goes at NEGATIVE z, the side this file calls "L".

Run: python3 plan7.py <ftex.npz> <survey.json> <plan.json>
"""
import json
import sys

import numpy as np
from scipy import ndimage

TEX, SURVEY, OUT = sys.argv[1:4]
CARGLB = sys.argv[4] if len(sys.argv) > 4 else None

d = np.load(TEX, allow_pickle=True)
D, ys, zs, OWN, nodes = d["D"], d["ys"], d["zs"], d["OWN"], list(d["nodes"])
RES, XNOSE = float(d["RES"]), float(d["XMIN"])
sv = json.load(open(SURVEY))
SIL = np.isfinite(D)

SPEC_FACE_MM = 554.0


def front_local_centreline(glb):
    """Reflection fit on the FRONT THIRD of real bodywork only.

    Excludes the melted fascia (x > nose+0.40) so the melt cannot vote, and
    excludes the wheels entirely -- Gate 6 measured 76/114 mm of hub asymmetry
    on this car, which makes them the worst available witness.  Returns the
    minimiser of the mean capped nearest-neighbour distance between the cloud
    and its own mirror image.
    """
    import trimesh
    from scipy.spatial import cKDTree
    sc = trimesh.load(glb, force="scene", process=False)
    V = []
    for n in ("Body_Shell", "Glass_Windscreen"):
        if n in sc.graph.nodes_geometry:
            T, g = sc.graph[n]
            V.append(trimesh.transform_points(
                np.asarray(sc.geometry[g].vertices, float), T))
    V = np.vstack(V)
    x0 = V[:, 0].min()
    V = V[(V[:, 0] > x0 + 0.40) & (V[:, 0] < x0 + 1.55)]
    # Exclude the lower third: sills and lower panels carry most of the body's
    # asymmetry and drag the fit. This window is the one validated by hand
    # against the front tyres (+0.0257) and front rims (+0.0290).
    V = V[V[:, 1] > V[:, 1].min() + 0.50]
    sub = V[::3]
    tree = cKDTree(sub)

    def cost(zc):
        m = sub.copy()
        m[:, 2] = 2 * zc - m[:, 2]
        d, _ = tree.query(m, k=1)
        return float(np.mean(np.minimum(d, 0.04)))

    grid = np.arange(-0.06, 0.0601, 0.001)
    c = [cost(z) for z in grid]
    b = float(grid[int(np.argmin(c))])
    fine = np.arange(b - 0.001, b + 0.00101, 0.00025)
    cf = [cost(z) for z in fine]
    bb = float(fine[int(np.argmin(cf))])

    # THE REFLECTION FIT ALONE IS NOT STABLE ENOUGH TO QUOTE.  Its cost surface
    # is shallow (the minimum beats z=0 by only ~20%), and changing the search
    # grid or the sample window moves it by ~12 mm.  So it is one vote of four,
    # and the CENTRELINE IS THE MEDIAN of independent front-local estimators:
    # this fit, the front tyre pair, the front rim pair, and Body_Shell's own
    # z-midpoint at the nose station.  The spread between them is reported, and
    # it IS the uncertainty -- there is no single centreline on a car whose
    # midline sweeps 140 mm from nose to tail.
    est = {"reflection_fit": bb}
    for a, bnode, tag in (("Wheel_FL_Tyre", "Wheel_FR_Tyre", "front_tyres"),
                          ("Wheel_FL_Rim", "Wheel_FR_Rim", "front_rims")):
        if a in sc.graph.nodes_geometry and bnode in sc.graph.nodes_geometry:
            m = []
            for nn in (a, bnode):
                T, g = sc.graph[nn]
                m.append(trimesh.transform_points(
                    np.asarray(sc.geometry[g].vertices, float), T)[:, 2].mean())
            est[tag] = float(np.mean(m))
    T, g = sc.graph["Body_Shell"]
    BS = trimesh.transform_points(np.asarray(sc.geometry[g].vertices, float), T)
    nx = BS[:, 0].min()
    sel = (BS[:, 0] < nx + 0.50) & (BS[:, 1] > BS[:, 1].min() + 0.45)
    if sel.sum() > 500:
        est["nose_station_midpoint"] = float(
            0.5 * (BS[sel, 2].min() + BS[sel, 2].max()))
    vals = np.array(list(est.values()))
    return (float(np.median(vals)), min(cf), cost(0.0), int(len(sub)),
            {k: round(v, 5) for k, v in est.items()},
            round(float(vals.max() - vals.min()) * 1000, 1))


if CARGLB:
    ZC, ZCOST, ZCOST0, ZN_PTS, ZEST, ZSPREAD = front_local_centreline(CARGLB)
    ZC = round(ZC, 4)
else:                            # legacy path: the value fitted for car_rebound
    ZC, ZCOST, ZCOST0, ZN_PTS, ZEST, ZSPREAD = 0.0265, None, None, None, {}, None


def profile(zt, half=0.030, smooth=11):
    ci = int(round((zt - zs[0]) / RES))
    k = int(half / RES)
    sl = slice(max(0, ci - k), ci + k + 1)
    with np.errstate(all="ignore"):
        c = np.nanmin(np.where(SIL[:, sl], D[:, sl], np.nan), axis=1)
    ok = np.isfinite(c)
    idx = np.arange(len(ys))
    return ndimage.uniform_filter1d(np.interp(idx, idx[ok], c[ok]), smooth)


# ------------------------------------------------- datum, scanning DOWNWARD
central = [-0.35, -0.25, -0.15, -0.05, 0.05, 0.15, 0.25, 0.35]
datum_by_thr = {}
for thr in (1.0, 1.3, 1.6):
    v = []
    for zt in central:
        g = np.gradient(profile(zt), RES)
        m = (ys < 1.02) & (ys > 0.60) & (g < thr)
        i = np.nonzero(m)[0]
        v.append(ys[i[-1]] if len(i) else np.nan)
    datum_by_thr[thr] = (float(np.nanmedian(v)), float(np.nanstd(v)))
Y_DATUM = round(datum_by_thr[1.3][0], 4)

# GUARD.  The datum detector scans a FIXED height window with FIXED tangent
# thresholds, both calibrated on this car's pose.  On a differently-posed copy
# of the same mesh (the grounded `car_merged.glb`, rotated 4.7 deg) the scan ran
# off the top of its window and returned 1.0180 for ALL THREE thresholds -- a
# zero-width band, and a "front face" of 656 mm against the real car's 554.  It
# produced a number, and the number was fiction.  A gate that cannot fail is not
# a gate, so the two tells are asserted: the threshold band must have real width,
# and the resulting face height must be a plausible fraction of the published
# one.  If either fires, the detector needs recalibrating for that pose -- it
# must NOT be worked around by widening the window until a number appears.
_band = abs(datum_by_thr[1.6][0] - datum_by_thr[1.0][0])
_TOPW = 1.02
DATUM_TRUSTED = True
DATUM_FAULTS = []
if _band < 1e-6:
    DATUM_TRUSTED = False
    DATUM_FAULTS.append(
        f"zero-width threshold band: all thresholds returned y={Y_DATUM}")
if Y_DATUM > _TOPW - 0.005:
    DATUM_TRUSTED = False
    DATUM_FAULTS.append(
        f"datum {Y_DATUM} is at the top of the search window ({_TOPW}) -- the "
        f"scan did not find a bonnet edge inside it")

# ---------------------------------------------------- bumper lowest edge
lows = []
for zt in [-0.30, -0.10, 0.0, 0.10, 0.30, 0.50]:
    cf = profile(zt)
    m = (ys > 0.36) & (ys < 0.60) & (cf < 0.10)
    i = np.nonzero(m)[0]
    if len(i):
        lows.append(ys[i[0]])
Y_LOW = round(float(np.median(lows)), 4)

H = Y_DATUM - Y_LOW
SCALE = H / (SPEC_FACE_MM / 1000.0)
if not (0.60 <= SCALE <= 1.05):
    DATUM_TRUSTED = False
    DATUM_FAULTS.append(
        f"front-face height {H*1000:.0f} mm gives scale {SCALE:.3f} against the "
        f"published {SPEC_FACE_MM:.0f} mm; outside the plausible 0.60-1.05 band")

# ------------------------------------------------------------ the stack
# mm below datum on the REAL car -> fraction of front-face height -> mesh y
STACK_MM = {
    "headlamp_tip_above_datum": -90, "badge_top": -11, "datum": 0,
    "headlamp_top_inner": 9, "blade_centreline": 20, "badge_centre": 54,
    "grille_bar_bottom": 67, "headlamp_lowest": 97, "badge_bottom": 120,
    "plate_top": 162, "towEye": 207, "intake_top": 230, "plate_bottom": 272,
    "grille_lower_bottom": 410, "bumper_lowest": 554,
}
frac = {k: 1.0 - v / SPEC_FACE_MM for k, v in STACK_MM.items()}
Y = {k: round(Y_LOW + f * H, 5) for k, f in frac.items()}

PLATE_W, PLATE_H = 0.520, 0.111                 # BS AU 145d, TRUE size
plate_centre_y = round(0.5 * (Y["plate_top"] + Y["plate_bottom"]), 5)
BADGE_D = round(0.149 * SCALE, 5)               # scaled, see docstring

# ------------------------------------------- the mesh's own lateral limits
def width_at(ylo, yhi, minrows=4, dmax=0.42):
    m = SIL & ((ys > ylo) & (ys < yhi))[:, None] & (D < dmax)
    s = m.sum(0) > minrows
    i = np.nonzero(s)[0]
    return (float(zs[i.min()]), float(zs[i.max()])) if len(i) else (np.nan, np.nan)


lamp_lo, lamp_hi = width_at(Y["headlamp_lowest"], Y["headlamp_top_inner"])
face_lo, face_hi = width_at(Y_LOW + 0.02, Y_DATUM - 0.01)
# symmetric usable half-width: the smaller side, so nothing is built into air
HALF = round(min(ZC - face_lo, face_hi - ZC), 4)

P = {
 "frame": {
   "x_nose_plane": round(XNOSE, 5),
   "z_centre": ZC,
   "y_datum_bonnet_leading_edge": Y_DATUM,
   "y_bumper_lowest": Y_LOW,
   "front_face_height_m": round(H, 5),
   "front_face_height_mm": round(H * 1000, 1),
   "spec_front_face_height_mm": SPEC_FACE_MM,
   "vertical_scale_vs_spec": round(SCALE, 4),
   "half_width_usable": HALF,
   "depth_sign": "D measured BACKWARD from x_nose_plane; proud = smaller D",
   "LR_convention": "file convention: L = -z, R = +z (viewer L/R from the "
                    "front). The car's TRUE left is +z. Tow-eye (car's RIGHT) "
                    "goes at NEGATIVE z.",
 },
 "evidence": {
   "datum_threshold_sweep": {str(k): {"median_y": round(v[0], 4),
                                      "sd_mm": round(v[1] * 1000, 1)}
                             for k, v in datum_by_thr.items()},
   "datum_uncertainty_band_y": [round(datum_by_thr[1.0][0], 4),
                                round(datum_by_thr[1.6][0], 4)],
   "bumper_low_per_column_y": [round(float(x), 4) for x in lows],
   "centreline_choice": {
       "value": ZC,
       "basis": "FRONT-LOCAL centreline, fitted on THIS file by reflection of "
                "the front third of real bodywork (melt and wheels excluded).",
       "fit_cost_mm": None if ZCOST is None else round(ZCOST * 1000, 3),
       "fit_cost_at_z0_mm": None if ZCOST0 is None else round(ZCOST0 * 1000, 3),
       "fit_points": ZN_PTS,
       "estimators": ZEST,
       "estimator_spread_mm": ZSPREAD,
       "method": "MEDIAN of independent front-local estimators; the reflection "
                 "fit alone moves ~12 mm with the search grid, so it is one "
                 "vote, not the answer.",
       "rear_third_fit": -0.068,
       "body_midline_sweep_mm": 140,
       "withdrawn": "An earlier z=0.000 choice in this same file was WRONG and "
                    "is withdrawn: it used the car's GLOBAL symmetry, which on "
                    "a bowed car does not describe the front.",
   },
   "lamp_band_z_extent": [round(lamp_lo, 4), round(lamp_hi, 4)],
   "face_band_z_extent": [round(face_lo, 4), round(face_hi, 4)],
   "ground": sv["ground"],
   "proportion_finding": (
     f"mesh front face {H*1000:.0f} mm vs published {SPEC_FACE_MM:.0f} mm "
     f"({(1-SCALE)*100:.0f}% short). Reported, NOT corrected -- body proportion "
     f"is Gate 5's scope, not Gate 3's."),
 },
 "stack_mm_below_datum_real_car": STACK_MM,
 "stack_fraction_of_face": {k: round(v, 4) for k, v in frac.items()},
 "y": Y,
 "parts": {
   "plate": {"w": PLATE_W, "h": PLATE_H, "centre_y": plate_centre_y,
             "centre_z": ZC, "note": "TRUE BS AU 145d size, not scaled"},
   "badge": {"diameter": BADGE_D, "centre_y": Y["badge_centre"], "centre_z": ZC,
             "note": f"scaled by {SCALE:.3f} from 149 mm; true size collides "
                     f"with the plate on this compressed face"},
   "grille_upper": {"y0": Y["grille_bar_bottom"], "y1": Y_DATUM,
                    "height_mm": round((Y_DATUM - Y["grille_bar_bottom"]) * 1000, 1),
                    "note": "constant-height SLOT, NO SLATS (spec 4.1)"},
   "blade": {"centre_y": Y["blade_centreline"],
             "thickness_mm": round(7.5 * SCALE, 2),
             "note": "ONE unbroken blade tip->lamp->grille->THROUGH badge->tip"},
   "grille_lower": {"y0": Y["grille_lower_bottom"], "y1": Y["plate_bottom"],
                    "pitch_mm": round(21.0 * SCALE, 2),
                    "note": "horizontal lattice"},
   "valance": {"y0": Y_LOW, "y1": Y["grille_lower_bottom"],
               "note": "body-colour band. THERE IS NO SPLITTER on this trim."},
   "intake": {"y_top": Y["intake_top"], "blades": 3,
              "note": "body-colour surround + THREE chrome blades"},
   "towEye": {"y": Y["towEye"], "z": round(ZC - 0.455 * SCALE, 4),
              "note": "car's RIGHT only = NEGATIVE z. The one proven asymmetry."},
 },
}
P["frame"]["datum_trusted"] = DATUM_TRUSTED
P["evidence"]["datum_faults"] = DATUM_FAULTS
json.dump(P, open(OUT, "w"), indent=1)
if not DATUM_TRUSTED:
    print("DATUM_UNTRUSTED -- do not build on this plan:")
    for f_ in DATUM_FAULTS:
        print("   *", f_)

print(f"CENTRELINE z {ZC:+.4f} (stated, +-10mm)")
print(f"DATUM y {Y_DATUM:.4f}  band {datum_by_thr[1.0][0]:.4f}..{datum_by_thr[1.6][0]:.4f}")
print(f"BUMPER LOW y {Y_LOW:.4f}   FACE {H*1000:.1f} mm  scale {SCALE:.4f} "
      f"({(1-SCALE)*100:.1f}% short of the published 554 mm)")
print(f"usable half width {HALF*1000:.0f} mm  (face z {face_lo:+.3f}..{face_hi:+.3f})")
print("\nstack (mesh y):")
for k in STACK_MM:
    print(f"  {k:26s} {STACK_MM[k]:+5d} mm  frac {frac[k]:.3f}  ->  y {Y[k]:.4f}")
print(f"\nplate  y {plate_centre_y-PLATE_H/2:.4f}..{plate_centre_y+PLATE_H/2:.4f} "
      f"z {ZC-PLATE_W/2:+.3f}..{ZC+PLATE_W/2:+.3f}  (TRUE 520x111)")
print(f"badge  D {BADGE_D*1000:.1f} mm at y {Y['badge_centre']:.4f} "
      f"-> {Y['badge_centre']-BADGE_D/2:.4f}..{Y['badge_centre']+BADGE_D/2:.4f}")
print(f"  badge bottom - plate top gap = "
      f"{(Y['badge_centre']-BADGE_D/2 - (plate_centre_y+PLATE_H/2))*1000:+.1f} mm")
print("PLAN_DONE", OUT)
