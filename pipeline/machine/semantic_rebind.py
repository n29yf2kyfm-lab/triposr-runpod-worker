#!/usr/bin/env python3
"""semantic_rebind.py — Gate 7 (semantic hierarchy) + Gate 8 (PBR materials).

ONE OPERATOR, NOT A HAND EDIT. Everything it decides it derives from the
GEOMETRY of the car it is handed, so it can be re-run on a different car and
re-applied after another stage has changed the mesh. It reads the input's
material names only as a WEAK SEED for glazing, and even that seed is
geometrically verified before it is believed.

WHY IT EXISTS — the defect it was built for, measured on the Class-A Golf Mk8
working copy (985,227 faces, 2026-08-20):

  * `interior` was bound to 11.93 m^2 of DIRECTLY VISIBLE EXTERIOR surface —
    more visible area than `carpaint` itself (11.59 m^2). The front bumper,
    both sills, both valances and the rear bumper all rendered as cabin
    plastic. Per-region measurement: below y=0.35 the visible skin was 84-95%
    `interior`; above y=0.6 it was 84-95% `carpaint`. That is a height-banded
    labelling failure, not an interior.
  * `Rim_Alloy` covered most of each wheel and `Tyre_Rubber` was a thin outer
    ring — the inverse of the truth. This is the exact class of defect that
    got live cars QUARANTINED in this catalogue.
  * `carpaint` and `Rim_Alloy` shipped `metallicFactor 1.0 / roughnessFactor
    1.0` (the glTF DEFAULTS, written explicitly), i.e. the flat-shell trap:
    paint renders as rough black metal in any viewer that honours the file.

HOW IT CLASSIFIES — five geometric measurements, no name matching:

  1. FRAME. Length/up/width axes and the ground plane from the bbox; the nose
     from the same signal set qc_evidence.py uses (imported from it when
     available, so the two tools cannot disagree about which end is the front).
  2. WHEELS. A Hough vote in the (x, y, r) space of each side slab, using only
     faces whose normal lies in the length-height plane — i.e. the TYRE TREAD,
     whose normal is radial. Rim/tyre are then split by RADIUS about the fitted
     axle, never by material name. Measured on the Golf: front axle x -1.24 /
     -1.27 (two sides), rear +1.19 / +1.24, and it caught that the FRONT axle
     sits 0.19 m higher than the rear (front wheels float 0.183 m off the
     ground) — a Gate 6 defect this operator reports and does not touch.
  3. VISIBILITY. Ray casts from a customer orbit (azimuth x elevation -8..55
     deg). Three states per face: DIRECT (nothing in front of it), THROUGH
     GLASS (reachable only once glazing is removed from the occluder set) and
     HIDDEN. "Interior is what has no line of sight from outside except
     THROUGH glazing" becomes a measurement instead of an opinion.
  4. CAVITY (local AO). 24 short hemisphere rays per face. Grille slats, lower
     intakes and arch liners are recessed and come back dark; flat panel is
     open. Measured on the Golf nose: the y 0.45-0.60 intake band scores mean
     AO 0.564 against 0.78-0.97 for the panel around it.
  5. COLOUR PRIOR — MEASURED AND THEN REJECTED FOR THE LOWER BODY, recorded so
     nobody rebuilds it. Sampling the baked paint atlas through the nearest
     textured vertex works where the textured mesh is (median donor distance
     16 mm over the whole car) and does NOT work where the defect is: for the
     mis-bound visible `interior` faces the nearest donor is 53 mm away at the
     median and 299 mm at p90, because the textured mesh does not cover the
     lower body at all. It is therefore used ONLY where the donor is within
     --colour-tol (default 20 mm) — which is what makes lamp detection honest,
     since the lamps DO carry close dark texels — and never to decide paint vs
     trim on the sills or bumpers.

WHAT IT WILL NOT DO. There is no grille aperture in this mesh to find: a
150x300 parallel depth probe across the nose shows the lower bumper standing
0.06-0.09 m PROUD of the band above it, with no recessed grille box anywhere.
So the operator separates recessed trim by cavity where cavity exists and says
so in the report where it does not. It never invents a part.

GATE 7 HONESTY. Doors, bonnet and hatch are NOT separate geometry in a
generated shell, and cutting a continuous skin into a "door" yields a
paper-thin panel with no jamb, no inner skin and no seal — it would rotate
into the body and expose the cabin through the hole. This operator therefore
emits three provenance classes and the report states which is which:
    real  — the node is genuinely separate geometry (wheels, glazing panes,
            mirrors, lamps, interior). These get pivots and can animate.
    cut   — a named REGION carved from the shell at a stated, measured
            boundary (bumpers). Useful for damage overlays and material
            zoning. NOT animatable and never given a hinge.
    absent— reported as NOT ACHIEVABLE (doors, bonnet, hatch as opening
            parts). No empty node is ever created to make a checklist pass.

Run:
    python3 semantic_rebind.py --glb in.glb --out out.glb \
        [--spec pipeline/machine/specs/vw_golf_mk8.json] \
        [--report out.json] [--keep-paint-texture] [--no-cut-bumpers]

    python3 semantic_rebind.py --glb in.glb --measure-only --report r.json
"""
import argparse
import json
import math
import os
import struct
import sys
import time

import numpy as np
import trimesh
from scipy.spatial import cKDTree
from trimesh.visual.material import PBRMaterial

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# THE MATERIAL SET (Gate 8). Every entry carries explicit factors: a material
# that omits metallic/roughness inherits the glTF defaults 1.0/1.0, which is
# the flat-shell trap this file exists partly to close. `ext` values are
# written into the glTF JSON afterwards because trimesh cannot emit KHR_*.
# ---------------------------------------------------------------------------
MATERIALS = {
    # exterior painted skin — the ONE physical paint the respray path targets.
    # The name MUST stay "carpaint": colour_variants.py and the render worker
    # both key on it (see CLAUDE.md, materials_pass.py).
    "carpaint": dict(base=None, metallic=0.0, rough=0.24,
                     ext={"KHR_materials_clearcoat": {
                         "clearcoatFactor": 1.0,
                         "clearcoatRoughnessFactor": 0.08}}),
    # recessed exterior black plastic: grille slats, lower intake, vents
    "Trim_Black":    dict(base=[0.021, 0.021, 0.023], metallic=0.0, rough=0.55),
    # inner wheel arch — matte, near-black, reads as shadow
    "Arch_Liner":    dict(base=[0.013, 0.013, 0.014], metallic=0.0, rough=0.95),
    # floorpan / sills' underside / anything the customer orbit cannot see
    "Underbody":     dict(base=[0.010, 0.010, 0.011], metallic=0.0, rough=0.95),
    "Tyre_Rubber":   dict(base=[0.028, 0.028, 0.030], metallic=0.0, rough=0.90),
    "Rim_Alloy":     dict(base=[0.42, 0.43, 0.45],    metallic=0.85, rough=0.35),
    "Brake_Disc":    dict(base=[0.11, 0.11, 0.12],    metallic=0.75, rough=0.55),
    "Lamp_Lens":     dict(base=[0.035, 0.035, 0.040], metallic=0.0, rough=0.06,
                          ext={"KHR_materials_clearcoat": {
                              "clearcoatFactor": 1.0,
                              "clearcoatRoughnessFactor": 0.03}}),
    "Lamp_Lens_Rear": dict(base=[0.155, 0.012, 0.014], metallic=0.0, rough=0.06,
                           ext={"KHR_materials_clearcoat": {
                               "clearcoatFactor": 1.0,
                               "clearcoatRoughnessFactor": 0.03}}),
    "Lamp_Reflector": dict(base=[0.62, 0.62, 0.64],   metallic=0.95, rough=0.12),
    "Chrome_Trim":   dict(base=[0.78, 0.78, 0.80],    metallic=1.0,  rough=0.10),
    "Seal_Rubber":   dict(base=[0.016, 0.016, 0.017], metallic=0.0, rough=0.95),
    "Interior_Plastic": dict(base=[0.030, 0.030, 0.033], metallic=0.0, rough=0.80),
    "Interior_Fabric":  dict(base=[0.048, 0.046, 0.045], metallic=0.0, rough=0.95),
    # mobile-compatible transparent glazing: BLEND + real transmission + IOR.
    # alpha stays well under 1.0 so a factor-only probe reads it as clear, and
    # KHR_materials_transmission carries the physical behaviour for viewers
    # that support it. See CLAUDE.md: alpha 0.986 renders as a solid panel.
    "glass": dict(base=[0.052, 0.058, 0.062], alpha=0.16, metallic=0.0,
                  rough=0.03, alpha_mode="BLEND", double=False,
                  ext={"KHR_materials_transmission": {"transmissionFactor": 0.92},
                       "KHR_materials_ior": {"ior": 1.45}}),
}

# Classification codes. Order matters only for reporting.
CLASSES = ["carpaint", "Trim_Black", "Arch_Liner", "Underbody", "Tyre_Rubber",
           "Rim_Alloy", "Brake_Disc", "Lamp_Lens", "Lamp_Lens_Rear",
           "Interior_Plastic", "glass"]

GLASS_TOK = ("glass", "window", "windscreen", "windshield", "glazing",
             "glas", "scheibe", "vidro", "fenster")
# A lamp lens is not glazing, and neither is a touchscreen. Same exclusion list
# the project's glass probe learned the hard way (CLAUDE.md, Mercedes wave).
GLASS_NOT = ("lamp", "light", "headlight", "taillight", "backlight", "mirror",
             "rearview", "screen_", "touch", "dash", "instrument", "icon",
             "button", "aircondition", "surr", "frit")


# ===========================================================================
# stage 1 — frame
# ===========================================================================
class Frame:
    """The car's canonical frame, MEASURED, expressed as an exact signed axis
    permutation so nothing is approximated by a fitted rotation.

    LOCAL coordinates are (length, up, width) with +X toward the NOSE, +Y up
    and the ground plane at Y=0. All analysis runs in local; the EXPORT keeps
    the caller's original world coordinates untouched, so re-running this
    operator can never drift a car's frame.

    Which axis is UP is decided by MIRROR SYMMETRY, not by extents: a hatch is
    wider than it is tall and an SUV is not, so `height < width` is not a rule.
    A car is mirror-symmetric about its length-up plane and is not symmetric
    about any other, so the width axis is the one whose mirrored point cloud
    lands on itself. Which END of the up axis is the GROUND is decided by slab
    area: the bottom 3% of a car is four contact patches, the top 3% is a roof.
    """

    def __init__(self, ax_len, ax_up, ax_wid, s_len, s_up, s_wid, origin,
                 lo, hi, evidence):
        self.ax_len, self.ax_up, self.ax_wid = ax_len, ax_up, ax_wid
        self.s_len, self.s_up, self.s_wid = s_len, s_up, s_wid
        self.origin = origin                  # world point that maps to local 0
        self.evidence = evidence
        self.length = float(hi[ax_len] - lo[ax_len])
        self.width = float(hi[ax_wid] - lo[ax_wid])
        self.height = float(hi[ax_up] - lo[ax_up])
        M = np.zeros((3, 3))
        M[0, ax_len], M[1, ax_up], M[2, ax_wid] = s_len, s_up, s_wid
        self.M = M                            # local = (world - origin) @ M.T

    def to_local(self, p):
        return (np.asarray(p) - self.origin) @ self.M.T

    def dir_to_local(self, d):
        return np.asarray(d) @ self.M.T

    def to_world(self, p):
        return np.asarray(p) @ self.M + self.origin

    def as_dict(self):
        return dict(ax_len=self.ax_len, ax_up=self.ax_up, ax_wid=self.ax_wid,
                    sign_len=int(self.s_len), sign_up=int(self.s_up),
                    sign_wid=int(self.s_wid),
                    origin=[round(float(v), 5) for v in self.origin],
                    length_m=round(self.length, 4), width_m=round(self.width, 4),
                    height_m=round(self.height, 4), evidence=self.evidence)


def _mirror_residual(V, axis, n=20000, seed=0):
    """Mean nearest-neighbour distance after mirroring the point cloud about
    the median of `axis`, normalised by the car's diagonal. Small = symmetric."""
    rng = np.random.default_rng(seed)
    k = min(n, len(V))
    idx = rng.choice(len(V), k, replace=False)
    P = V[idx]
    mid = float(np.median(V[:, axis]))
    Q = P.copy()
    Q[:, axis] = 2 * mid - Q[:, axis]
    d, _ = cKDTree(P).query(Q, workers=-1)
    diag = float(np.linalg.norm(V.max(0) - V.min(0)))
    return float(d.mean() / diag)


def measure_frame(mesh, forced_nose=None):
    V = np.asarray(mesh.vertices)
    lo, hi = V.min(0), V.max(0)
    ext = hi - lo
    ax_len = int(np.argmax(ext))
    rest = [i for i in range(3) if i != ax_len]
    res = {i: _mirror_residual(V, i) for i in rest}
    ax_wid = min(rest, key=lambda i: res[i])
    ax_up = [i for i in rest if i != ax_wid][0]
    ev = dict(mirror_residual={str(i): round(res[i], 5) for i in rest},
              width_axis_rule="the axis a car is mirror-symmetric about")

    # sign of UP: the extreme 3% slab with the SMALLER surface area is the
    # ground (contact patches), the other is the roof.
    C = mesh.triangles_center
    A = mesh.area_faces
    t = 0.03 * ext[ax_up]
    a_min = float(A[C[:, ax_up] < lo[ax_up] + t].sum())
    a_max = float(A[C[:, ax_up] > hi[ax_up] - t].sum())
    s_up = 1 if a_min < a_max else -1
    ev["slab_area_min_side"] = round(a_min, 4)
    ev["slab_area_max_side"] = round(a_max, 4)
    ground = lo[ax_up] if s_up > 0 else hi[ax_up]

    # provisional right-handed frame with the nose at +X, then vote on it
    s_len = 1
    s_wid = s_len * s_up          # keeps det(M) = +1 so winding is preserved
    origin = np.zeros(3)
    origin[ax_up] = ground
    prov = Frame(ax_len, ax_up, ax_wid, s_len, s_up, s_wid, origin, lo, hi, ev)
    nose, conf, nev = detect_nose(mesh, prov)
    ev["nose"] = nev
    ev["nose_confident"] = bool(conf)
    if forced_nose in ("+", "-"):
        nose = 1 if forced_nose == "+" else -1
        ev["nose_forced"] = forced_nose
        conf = True
    s_len = nose
    s_wid = s_len * s_up
    return Frame(ax_len, ax_up, ax_wid, s_len, s_up, s_wid, origin, lo, hi, ev)


def detect_nose(mesh, prov):
    """Which end is the front, voted from three signals that survive on a
    hatchback. Returns +1 when the nose is at the provisional +X.

    The project has shipped upside-down and side-on sheets by ASSUMING a
    convention (qc_evidence.py records both), so a weak vote is reported as
    weak and the caller can override with --nose."""
    P = prov.to_local(mesh.triangles_center)
    A = mesh.area_faces
    L, U = P[:, 0], P[:, 1]
    lo, hi = float(L.min()), float(L.max())
    span = hi - lo
    H = float(U.max())
    ev, votes = {}, 0.0

    # 1 — BONNET DECK. At 0.45-0.62 of the height a hatch has a long low deck
    # ahead of the screen and an almost vertical tail, so the band's area
    # centroid sits toward the NOSE.
    deck = (U > 0.45 * H) & (U < 0.62 * H)
    if A[deck].sum() > 0:
        m = float((L[deck] * A[deck]).sum() / A[deck].sum())
        ev["deck_mean"] = round((m - (lo + hi) / 2) / span, 4)
        votes += np.sign(ev["deck_mean"]) * min(1.0, abs(ev["deck_mean"]) * 14)

    # 2 — ROOF. The roofline runs much closer to the tail of a hatch than to
    # its nose, so high geometry sits toward the REAR.
    top = U > 0.86 * H
    if A[top].sum() > 0:
        m = float((L[top] * A[top]).sum() / A[top].sum())
        ev["roof_mean"] = round((m - (lo + hi) / 2) / span, 4)
        votes += -np.sign(ev["roof_mean"]) * min(1.0, abs(ev["roof_mean"]) * 14)

    # 3 — LOWEST BODY. A front bumper reaches lower than a rear bumper on
    # nearly every road car (air dam vs departure angle).
    for sgn, key in ((+1, "low_plus"), (-1, "low_minus")):
        band = (L * sgn) > (span / 2 - 0.10 * span)
        ev[key] = round(float(np.percentile(U[band], 1)), 4) if band.sum() > 50 else None
    if ev.get("low_plus") is not None and ev.get("low_minus") is not None:
        d = ev["low_minus"] - ev["low_plus"]
        votes += np.sign(d) * min(1.0, abs(d) / (0.06 * H))

    ev["vote"] = round(float(votes), 3)
    return (1 if votes > 0 else -1), abs(votes) > 0.40, ev


# ===========================================================================
# stage 2 — wheels
# ---------------------------------------------------------------------------
# Everything from here to stage 7 works on the LOCAL mesh: X toward the nose,
# Y up from the ground, Z across. Axis indices are therefore literal 0/1/2 and
# there is no per-car axis bookkeeping left to get wrong.
# ===========================================================================
class Wheel:
    def __init__(self, corner, centre, radius, rim_radius, z_in, z_out, score,
                 tread_faces):
        self.corner = corner            # "FL" / "FR" / "RL" / "RR"
        self.centre = centre            # 3-vector, LOCAL
        self.radius = radius
        self.rim_radius = rim_radius
        self.z_in, self.z_out = z_in, z_out
        self.score = score
        self.tread_faces = tread_faces

    def as_dict(self):
        return dict(corner=self.corner,
                    centre_local=[round(float(v), 4) for v in self.centre],
                    radius_m=round(self.radius, 4),
                    rim_radius_m=round(self.rim_radius, 4),
                    width_m=round(abs(self.z_out - self.z_in), 4),
                    inboard_z=round(self.z_in, 4), outboard_z=round(self.z_out, 4),
                    ground_gap_m=round(float(self.centre[1] - self.radius), 4),
                    hough_score=round(self.score, 5),
                    tread_faces=int(self.tread_faces))


def detect_wheels(lmesh, frame, spec_tyre=None, report=None):
    """Hough vote for each axle, from TREAD faces only.

    A tyre's tread normal is radial; its sidewall normal and a rim spoke's
    normal are axial. Restricting to |n.z| < 0.45 keeps exactly the surface
    whose normal points away from the axle, so every kept face can vote
    centre = p - r*n over an r sweep and the accumulator peak is the axle.

    The wheel LABEL's bbox is deliberately not used anywhere: wheel_swap.py
    records that it includes arch-liner spill and mis-centred / 40%-oversized
    the first attempt that trusted it.
    """
    C, N, A = lmesh.triangles_center, lmesh.face_normals, lmesh.area_faces
    halfw = frame.width / 2
    if spec_tyre:
        r0, r1 = spec_tyre["radius_m"] * 0.75, spec_tyre["radius_m"] * 1.25
        r_src = "spec tyre %s" % spec_tyre["spec"]
    else:
        r0, r1 = 0.18 * frame.height, 0.50 * frame.height
        r_src = "measured sweep 0.18-0.50 x height (APPROXIMATE, no spec)"
    rs = np.arange(r0, r1, 0.01)
    step = 0.01
    wheels, dbg = [], [dict(radius_sweep=r_src)]

    for sgn, side in ((+1, "L"), (-1, "R")):
        m = ((np.sign(C[:, 2]) == sgn) & (np.abs(C[:, 2]) > 0.33 * halfw)
             & (C[:, 1] < 0.60 * frame.height) & (np.abs(N[:, 2]) < 0.45))
        if m.sum() < 500:
            dbg.append(dict(side=side, error="too few tread-normal faces",
                            n=int(m.sum())))
            continue
        p, n, w = C[m][:, :2], N[m][:, :2], A[m]
        n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
        xs = np.arange(-frame.length / 2 - 0.1, frame.length / 2 + 0.1, step)
        ys = np.arange(0.03, 0.60 * frame.height, step)
        acc = np.zeros((len(xs), len(ys)))
        for r in rs:
            c = p - r * n
            ix = ((c[:, 0] - xs[0]) / step).astype(int)
            iy = ((c[:, 1] - ys[0]) / step).astype(int)
            ok = (ix >= 0) & (ix < len(xs)) & (iy >= 0) & (iy < len(ys))
            np.add.at(acc, (ix[ok], iy[ok]), w[ok])
        a = acc.copy()
        peaks = []
        for _ in range(2):
            i, j = np.unravel_index(np.argmax(a), a.shape)
            peaks.append((float(xs[i]), float(ys[j]), float(a[i, j])))
            a[max(0, i - int(0.40 / step)):i + int(0.40 / step), :] = 0
        top = max(pk[2] for pk in peaks)
        for (px, py, sc) in peaks:
            if sc < 0.25 * top:
                dbg.append(dict(side=side, rejected_peak=[round(px, 3), round(py, 3)],
                                score=round(sc, 5),
                                reason="below 25% of this side's peak"))
                continue
            d = np.linalg.norm(C[:, :2] - np.array([px, py]), axis=1)
            near = m & (d < rs[-1] * 1.2)
            hist, edges = np.histogram(d[near], bins=80,
                                       range=(rs[0] * 0.6, rs[-1] * 1.2),
                                       weights=A[near])
            R0 = float(edges[int(np.argmax(hist))] + (edges[1] - edges[0]) / 2)
            # REFINE BELOW THE AXLE. Above the axle the wheel arch sits at
            # very nearly the tyre's own radius, so a full-height radial
            # histogram fits the ARCH: measured here, that put one corner at
            # R 0.391 against a 0.317 spec tyre (+23%) and dragged 1.7 m^2 of
            # bodywork into the wheel. Under the axle there is no arch.
            low = near & (C[:, 1] < py - 0.30 * R0)
            if low.sum() > 200:
                h2, e2 = np.histogram(d[low], bins=80,
                                      range=(rs[0] * 0.6, rs[-1] * 1.2),
                                      weights=A[low])
                R = float(e2[int(np.argmax(h2))] + (e2[1] - e2[0]) / 2)
            else:
                R = R0
            clamped = None
            if spec_tyre and abs(R - spec_tyre["radius_m"]) > 0.25 * spec_tyre["radius_m"]:
                clamped = dict(fitted=round(R, 4), used=round(spec_tyre["radius_m"], 4),
                               reason="fitted radius more than 25% from the spec "
                                      "tyre; the spec value is used and this is "
                                      "flagged, never silently accepted")
                R = spec_tyre["radius_m"]
            # BOTTOM-OF-TYRE Z EXTENT. Only the lowest fifth of the wheel is
            # certainly wheel: the arch, the sill and the underbody all live
            # above it. Measured on this car the band is a flat 0.196-0.211 m
            # plateau on all four corners against a 0.225 m spec tyre, while
            # the same measurement taken over the FULL height came back
            # 0.34-0.44 m — i.e. it had swallowed the arch.
            bot = ((np.sign(C[:, 2]) == sgn) & (np.abs(d - R) < 0.10 * R)
                   & (C[:, 1] < py - 0.80 * R))
            if bot.sum() < 100:
                dbg.append(dict(side=side, rejected_peak=[round(px, 3), round(py, 3)],
                                reason="no bottom-of-tyre band at the fitted radius"))
                continue
            zc = np.abs(C[bot][:, 2])
            z_a, z_b = float(np.percentile(zc, 2.0)), float(np.percentile(zc, 98.0))
            z_lo, z_hi = sgn * z_a, sgn * z_b
            tread = ((np.sign(C[:, 2]) == sgn) & (np.abs(d - R) < 0.07 * R))
            if spec_tyre:
                rim_r = R * (spec_tyre["rim_r_m"] / spec_tyre["radius_m"])
                rim_src = "spec %s -> rim/tyre radius ratio %.3f" % (
                    spec_tyre["spec"], spec_tyre["rim_r_m"] / spec_tyre["radius_m"])
            else:
                rim_r = R * 0.70
                rim_src = "measured fallback 0.70R (APPROXIMATE, no spec)"
            ctr = np.array([px, py, (z_lo + z_hi) / 2])
            end = "F" if px > 0 else "R"
            wheels.append(Wheel(end + side, ctr, R, rim_r, z_lo, z_hi, sc,
                                int(tread.sum())))
            row = dict(side=side, corner=end + side, rim_radius_source=rim_src,
                       radius_first_pass=round(R0, 4), radius_used=round(R, 4),
                       bottom_band_z=[round(z_lo, 4), round(z_hi, 4)],
                       tyre_width_m=round(abs(z_hi - z_lo), 4))
            if clamped:
                row["radius_clamped"] = clamped
            dbg.append(row)
    if report is not None:
        report["wheel_detect_debug"] = dbg
    return wheels


# ===========================================================================
# stage 3 — visibility and cavity
# ===========================================================================
def orbit_dirs(n_az=24, el0=-8, el1=55, n_el=5):
    """Directions a customer can look FROM, in LOCAL coordinates."""
    out = []
    for el in np.linspace(math.radians(el0), math.radians(el1), n_el):
        for a in np.linspace(0, 2 * math.pi, n_az, endpoint=False):
            out.append([math.cos(a) * math.cos(el), math.sin(el),
                        math.sin(a) * math.cos(el)])
    return np.array(out)


def _cast(mesh, dirs, cen, rad, grid):
    seen = np.zeros(len(mesh.faces), bool)
    for d in dirs:
        d = d / np.linalg.norm(d)
        up = np.array([0., 0., 1.]) if abs(d[2]) < 0.9 else np.array([1., 0., 0.])
        ex = np.cross(up, d)
        ex /= np.linalg.norm(ex)
        ey = np.cross(d, ex)
        us = np.linspace(-rad, rad, grid)
        u, v = np.meshgrid(us, us)
        org = cen + (-d) * rad * 1.6 + u.reshape(-1, 1) * ex + v.reshape(-1, 1) * ey
        tri = mesh.ray.intersects_first(org, np.tile(d, (len(org), 1)))
        seen[tri[tri >= 0]] = True
    return seen


def visibility(lmesh, glass_mask, grid=300, n_az=24):
    """DIRECT / THROUGH-GLASS / HIDDEN by first-hit ray casting.

    THROUGH-GLASS is the second cast, at a mesh with the glazing removed: a
    face that only becomes a first hit once the glass is gone is BEHIND GLASS
    by construction. That is the operational form of "interior is what has no
    line of sight from outside except through glazing"."""
    V, F = lmesh.vertices, lmesh.faces
    lo, hi = V.min(0), V.max(0)
    cen = (lo + hi) / 2
    rad = float(np.linalg.norm(hi - lo) / 2)
    dirs = orbit_dirs(n_az=n_az)
    direct = _cast(lmesh, dirs, cen, rad, grid)
    if glass_mask.any():
        keep = np.where(~glass_mask)[0]
        sub = trimesh.Trimesh(vertices=V, faces=F[keep], process=False)
        s2 = _cast(sub, dirs, cen, rad, grid)
        thru = np.zeros(len(F), bool)
        thru[keep[s2]] = True
        thru &= ~direct
    else:
        thru = np.zeros(len(F), bool)
    return direct, thru, len(dirs)


def local_ao(lmesh, idx, reach, n_rays=24, seed=0, chunk=120000):
    """Cavity measure: the fraction of short hemisphere rays that ESCAPE.

    A grille slat, a lower intake or an arch liner occludes its own hemisphere
    at short range; flat panel does not. `reach` is scaled from the car's own
    height by the caller so the measure transfers between cars."""
    C, N = lmesh.triangles_center, lmesh.face_normals
    rng = np.random.default_rng(seed)
    dirs = rng.normal(size=(n_rays, 3))
    dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
    occ = np.zeros(len(idx), np.float32)
    for s in range(0, len(idx), chunk):
        sl = idx[s:s + chunk]
        org = C[sl] + N[sl] * (reach * 0.005)
        for k in range(n_rays):
            d = np.tile(dirs[k], (len(sl), 1))
            flip = (d * N[sl]).sum(1) < 0
            d[flip] *= -1
            hit = lmesh.ray.intersects_first(org, d)
            ok = hit >= 0
            if not ok.any():
                continue
            dist = np.linalg.norm(C[hit[ok]] - org[ok], axis=1)
            near = np.where(ok)[0][dist < reach]
            occ[s + near] += 1
    return 1.0 - occ / n_rays


# ===========================================================================
# stage 4 — colour prior (used narrowly, see module docstring)
# ===========================================================================
def colour_prior(scene, points, k=12):
    """Median sRGB of the k nearest TEXTURED vertices, plus the distance to the
    nearest one. The distance is the honesty check: measured on this Golf the
    donor is 16 mm away at the median over the whole car but 53 mm (p50) and
    299 mm (p90) for exactly the mis-bound faces the rebind has to decide,
    because the textured mesh does not cover the lower body at all. Anything
    past --colour-tol is therefore discarded rather than believed.

    `points` are WORLD coordinates — the donors come from the untouched input
    scene, so no frame conversion is involved."""
    dv, dc = [], []
    for name, g in scene.geometry.items():
        vis = getattr(g, "visual", None)
        uv = getattr(vis, "uv", None)
        mat = getattr(vis, "material", None)
        tex = getattr(mat, "baseColorTexture", None)
        if uv is None or tex is None or len(uv) != len(g.vertices):
            continue
        img = np.asarray(tex.convert("RGB"))
        H, W, _ = img.shape
        px = np.clip((np.asarray(uv)[:, 0] * (W - 1)).astype(int), 0, W - 1)
        py = np.clip(((1 - np.asarray(uv)[:, 1]) * (H - 1)).astype(int), 0, H - 1)
        dv.append(np.asarray(g.vertices))
        dc.append(img[py, px].astype(np.float32))
    if not dv:
        return None, None
    dv, dc = np.vstack(dv), np.vstack(dc)
    d, i = cKDTree(dv).query(points, k=min(k, len(dv)), workers=-1)
    if d.ndim == 1:
        d, i = d[:, None], i[:, None]
    return np.median(dc[i], axis=1), d[:, 0]


def srgb_to_linear(c):
    c = np.asarray(c, float) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


# ===========================================================================
# stage 5 — classification
# ===========================================================================
def classify(lmesh, frame, wheels, glass_mask, direct, thru, ao, col, cold,
             args, report):
    C, N, A = lmesh.triangles_center, lmesh.face_normals, lmesh.area_faces
    up = C[:, 1]
    lab = np.full(len(C), -1, np.int16)
    idx = {c: i for i, c in enumerate(CLASSES)}
    ev = {}

    # ---- 1. wheels: RADIUS about the fitted axle decides, nothing else -----
    wheel_any = np.zeros(len(C), bool)
    per_wheel = {}
    for w in wheels:
        d = np.linalg.norm(C[:, :2] - w.centre[:2], axis=1)
        zlo, zhi = sorted((w.z_in, w.z_out))
        pad = 0.06 * abs(zhi - zlo)
        inzone = (d < w.radius * 1.04) & (C[:, 2] > zlo - pad) & (C[:, 2] < zhi + pad)
        # A face inside the cylinder is ARCH, not wheel, when its normal points
        # back TOWARD the axle and is not axial: the wheel is convex about the
        # axle, the arch is concave around it. Without this the sill and the
        # arch liner fall inside the tyre annulus and get painted as rubber.
        rvec = np.zeros((len(C), 2))
        rvec[:, 0] = C[:, 0] - w.centre[0]
        rvec[:, 1] = C[:, 1] - w.centre[1]
        rn = np.maximum(np.linalg.norm(rvec, axis=1, keepdims=True), 1e-9)
        radial = (N[:, :2] * (rvec / rn)).sum(1)
        convex = (radial > -0.25) | (np.abs(N[:, 2]) > 0.5)
        inzone &= convex
        per_wheel[w.corner] = inzone
        wheel_any |= inzone
        tyre = inzone & (d >= w.rim_radius)
        rim = inzone & (d < w.rim_radius)
        lab[tyre] = idx["Tyre_Rubber"]
        lab[rim] = idx["Rim_Alloy"]
        # a brake disc sits INBOARD of the rim face and well inside its radius;
        # only claimed when real geometry is there, since generated wheels
        # frequently have none.
        inb_z = min(zlo, zhi) + 0.35 * abs(zhi - zlo)
        deep = rim & ((C[:, 2] < inb_z) if w.centre[2] > 0 else
                      (C[:, 2] > max(zlo, zhi) - 0.35 * abs(zhi - zlo)))
        deep &= d < w.rim_radius * 0.85
        if A[deep].sum() > 0.05 * A[rim].sum():
            lab[deep] = idx["Brake_Disc"]
        ev.setdefault("wheels", {})[w.corner] = dict(
            zone_faces=int(inzone.sum()),
            tyre_area=round(float(A[tyre].sum()), 4),
            rim_area=round(float(A[rim].sum()), 4),
            tyre_area_frac=round(float(A[tyre].sum() / max(A[inzone].sum(), 1e-9)), 4),
            visible_tyre_area=round(float(A[tyre & direct].sum()), 4),
            visible_rim_area=round(float(A[rim & direct].sum()), 4))

    # ---- 2. glazing: the seed, geometrically verified ----------------------
    lab[glass_mask] = idx["glass"]

    # ---- 3. arch liner: in the arch, not the wheel, never in direct sight --
    for w in wheels:
        d = np.linalg.norm(C[:, :2] - w.centre[:2], axis=1)
        same = (np.sign(C[:, 2]) == np.sign(w.centre[2]))
        arch = ((d < w.radius * 1.45) & (lab < 0) & (~direct) & same
                & (np.abs(C[:, 2]) > 0.40 * frame.width / 2))
        lab[arch] = idx["Arch_Liner"]

    # ---- 4. underbody: down-facing, never seen from the customer orbit -----
    down = -N[:, 1] > 0.35
    under = (lab < 0) & (~direct) & (~thru) & down & (up < args.sill_frac * frame.height)
    lab[under] = idx["Underbody"]

    # ---- 5. cabin: only reachable THROUGH glazing --------------------------
    lab[(lab < 0) & thru] = idx["Interior_Plastic"]

    # ---- 6. exterior skin in DIRECT sight, split by cavity ----------------
    if ao is not None:
        cav = (lab < 0) & direct & (ao < args.ao_cavity)
        # a cavity high on the body is a shut line or a window surround, not a
        # grille, so trim is only claimed below --trim-max-frac of the height.
        cav &= up < args.trim_max_frac * frame.height
        lab[cav] = idx["Trim_Black"]
    lab[(lab < 0) & direct] = idx["carpaint"]

    # ---- 7. lamps ---------------------------------------------------------
    lamp_report = detect_lamps(lmesh, frame, lab, idx, direct, col, cold, args)

    # ---- 8. anything still unlabelled is HIDDEN interior structure. It
    #         inherits the nearest decided face so a thin shell's back side
    #         can never disagree with its front side.
    todo = np.where(lab < 0)[0]
    if len(todo):
        done = np.where(lab >= 0)[0]
        _, nn = cKDTree(C[done]).query(C[todo], workers=-1)
        lab[todo] = lab[done[nn]]
        ev["hidden_faces_inherited"] = int(len(todo))
        ev["hidden_area_inherited"] = round(float(A[todo].sum()), 4)

    report["classification"] = ev
    report["lamps"] = lamp_report
    return lab, per_wheel, wheel_any


def detect_lamps(lmesh, frame, lab, idx, direct, col, cold, args):
    """Lamps from the ONE piece of colour evidence that survives its own
    honesty check: the baked atlas DOES cover the lamp faces (donor within
    --colour-tol) and paints them dark-neutral while the panel around them is
    chroma-dominant. Restricted to the outer --lamp-end-frac of the length and
    a height band, then required on BOTH sides before it is believed. A
    one-sided lamp is reported, never shipped."""
    if col is None:
        return dict(status="NOT TESTED", reason="no textured donor in the input")
    C, A = lmesh.triangles_center, lmesh.area_faces
    up, lat = C[:, 1], C[:, 0]
    half = frame.length / 2
    lum = col.mean(1)
    chroma = col.max(1) - col.min(1)
    near = cold < args.colour_tol
    dark = near & (lum < args.lamp_lum) & (chroma < args.lamp_chroma)
    band = (up > args.lamp_y0 * frame.height) & (up < args.lamp_y1 * frame.height)
    out = {}
    for end, sgn in (("front", +1), ("rear", -1)):
        endmask = (lat * sgn) > (half - args.lamp_end_frac * frame.length)
        cand = dark & band & endmask & direct & (lab == idx["carpaint"])
        sides = {s: (cand & (np.sign(C[:, 2]) == z))
                 for s, z in (("L", +1), ("R", -1))}
        aL_, aR_ = float(A[sides["L"]].sum()), float(A[sides["R"]].sum())
        sym = min(aL_, aR_) / max(aL_, aR_, 1e-9)
        cls = "Lamp_Lens" if end == "front" else "Lamp_Lens_Rear"
        if min(aL_, aR_) > args.lamp_min_area and sym > 0.25:
            for s in ("L", "R"):
                lab[sides[s]] = idx[cls]
            out[end] = dict(status="PASS", area_L=round(aL_, 4), area_R=round(aR_, 4),
                            symmetry=round(sym, 3), material=cls,
                            evidence="baked-atlas dark-neutral texels with a "
                                     "donor within %.0f mm" % (args.colour_tol * 1000))
        else:
            out[end] = dict(status="NOT SEPARATED", area_L=round(aL_, 4),
                            area_R=round(aR_, 4), symmetry=round(sym, 3),
                            reason="lamp evidence too small or one-sided; left "
                                   "as body paint rather than invent a lamp")
    return out


# ===========================================================================
# stage 6 — glazing seed and panes
# ===========================================================================
def glass_seed(scene, lmesh, offsets, frame, report):
    """Which faces are glazing. Seeded from the input (transparent materials
    first, glazing NAMES second, with the lamp/mirror/touchscreen exclusions
    this project's glass probe paid for) and then VERIFIED against geometry:
    real glazing lives above the belt line. A seed that fails is REFUSED."""
    mask = np.zeros(len(lmesh.faces), bool)
    why = []
    for name, (s, e) in offsets.items():
        g = scene.geometry[name]
        mat = getattr(getattr(g, "visual", None), "material", None)
        bcf = getattr(mat, "baseColorFactor", None)
        amode = getattr(mat, "alphaMode", None)
        transparent = (bcf is not None and len(bcf) > 3 and float(bcf[3]) < 0.98) \
            or (amode in ("BLEND", "MASK"))
        low = name.lower()
        named = any(t in low for t in GLASS_TOK) and not any(t in low for t in GLASS_NOT)
        if transparent or named:
            mask[s:e] = True
            why.append(dict(node=name, transparent=bool(transparent),
                            named=bool(named)))
    if not mask.any():
        report["glass_seed"] = dict(status="NONE", note="no transparent or "
                                    "glazing-named node; glazing left unclaimed")
        return mask
    up = lmesh.triangles_center[:, 1]
    frac_high = float((up[mask] > 0.55 * frame.height).mean())
    ok = frac_high > 0.80
    report["glass_seed"] = dict(status="VERIFIED" if ok else "REFUSED",
                                sources=why, faces=int(mask.sum()),
                                belt_line_m=round(float(np.percentile(up[mask], 2)), 4),
                                frac_above_055H=round(frac_high, 4),
                                rule="glazing must sit above 0.55H for >80% of "
                                     "its faces or the seed is not glazing")
    return mask if ok else np.zeros(len(lmesh.faces), bool)


def name_glass_panes(lmesh, frame, glass_mask, report, min_area):
    """Split the glazing into named panes by CONNECTED COMPONENT and name each
    by where it sits. Fragments under min_area are merged into the nearest
    named pane rather than shipped as debris."""
    idx = np.where(glass_mask)[0]
    if not len(idx):
        return {}
    sub = lmesh.submesh([idx], append=True, repair=False)
    comps = trimesh.graph.connected_components(sub.face_adjacency,
                                               nodes=np.arange(len(sub.faces)))
    A, C = sub.area_faces, sub.triangles_center
    big = [c for c in comps if A[c].sum() >= min_area]
    small = [c for c in comps if A[c].sum() < min_area]
    named, info = {}, []
    for c in big:
        cc, w = C[c], A[c] / A[c].sum()
        mx = float((cc[:, 0] * w).sum())
        mz = float((cc[:, 2] * w).sum())
        zspan = float(cc[:, 2].max() - cc[:, 2].min())
        side = "L" if mz > 0 else "R"
        if zspan > 0.55 * frame.width:
            nm = "Glass_Windscreen" if mx > 0 else "Glass_Rear"
        elif mx > 0.06 * frame.length:
            nm = "Glass_Door_F" + side
        elif mx > -0.22 * frame.length:
            nm = "Glass_Door_R" + side
        else:
            nm = "Glass_Quarter_" + side
        named.setdefault(nm, []).append(c)
        info.append(dict(pane=nm, area=round(float(A[c].sum()), 4),
                         mid_len=round(mx, 4), mid_wid=round(mz, 4),
                         wid_span=round(zspan, 4)))
    if small and named:
        anchors, keys = [], []
        for nm, cs in named.items():
            for c in cs:
                anchors.append(C[c].mean(0))
                keys.append(nm)
        tree = cKDTree(np.array(anchors))
        for c in small:
            _, j = tree.query(C[c].mean(0))
            named[keys[j]].append(c)
    out = {nm: idx[np.concatenate(cs)] for nm, cs in named.items()}
    report["glass_panes"] = dict(components=len(comps), named=len(out),
                                 merged_fragments=len(small), detail=info)
    return out


# ===========================================================================
# stage 7 — build the named hierarchy
# ===========================================================================
def build_scene(lmesh, frame, lab, per_wheel, panes, wheels, args, report):
    """Every node here is either REAL separate geometry or an explicitly
    stated CUT. Nothing empty is ever created."""
    idx = {c: i for i, c in enumerate(CLASSES)}
    C, A = lmesh.triangles_center, lmesh.area_faces
    up, lat = C[:, 1], C[:, 0]
    claimed = np.zeros(len(lab), bool)
    parts = []          # (node, face_idx, material, pivot_local|None, provenance)

    for w in wheels:                                   # real, animatable
        z = per_wheel[w.corner]
        for cls, suffix in (("Tyre_Rubber", "Tyre"), ("Rim_Alloy", "Rim"),
                            ("Brake_Disc", "Disc")):
            m = z & (lab == idx[cls]) & ~claimed
            if not m.any():
                continue
            claimed |= m
            parts.append(("Wheel_%s/%s" % (w.corner, suffix), np.where(m)[0],
                          cls, w.centre, "real"))

    for nm, faces in panes.items():                    # real
        m = np.zeros(len(lab), bool)
        m[faces] = True
        m &= ~claimed
        if not m.any():
            continue
        claimed |= m
        parts.append((nm, np.where(m)[0], "glass", None, "real"))
    rest_glass = (lab == idx["glass"]) & ~claimed
    if rest_glass.any():
        claimed |= rest_glass
        parts.append(("Glass_Other", np.where(rest_glass)[0], "glass", None, "real"))

    for nm, m in detect_mirrors(lmesh, frame, lab, idx, claimed, args, report).items():
        claimed |= m
        parts.append((nm, np.where(m)[0], "carpaint", None, "real"))

    for cls, base in (("Lamp_Lens", "Headlamp"), ("Lamp_Lens_Rear", "TailLamp")):
        m0 = (lab == idx[cls]) & ~claimed
        if not m0.any():
            continue
        for side, sgn in (("L", +1), ("R", -1)):
            m = m0 & (np.sign(C[:, 2]) == sgn)
            if not m.any():
                continue
            claimed |= m
            parts.append(("%s_%s" % (base, side), np.where(m)[0], cls, None, "real"))

    m = (lab == idx["Interior_Plastic"]) & ~claimed
    if m.any():
        claimed |= m
        parts.append(("Interior", np.where(m)[0], "Interior_Plastic", None, "real"))

    for cls, nm in (("Arch_Liner", "Arch_Liner"), ("Underbody", "Underbody")):
        m = (lab == idx[cls]) & ~claimed
        if m.any():
            claimed |= m
            parts.append((nm, np.where(m)[0], cls, None, "real"))

    cuts = {}
    if args.cut_bumpers and wheels:
        fw = [w for w in wheels if w.corner[0] == "F"]
        rw = [w for w in wheels if w.corner[0] == "R"]
        if fw and rw:
            f_edge = min(w.centre[0] + w.radius for w in fw)
            r_edge = max(w.centre[0] - w.radius for w in rw)
            top = args.bumper_top_frac * frame.height
            cuts["Bumper_Front"] = (lat > f_edge) & (up < top)
            cuts["Bumper_Rear"] = (lat < r_edge) & (up < top)
            report["bumper_cut"] = dict(
                front_boundary_x=round(float(f_edge), 4),
                rear_boundary_x=round(float(r_edge), 4),
                top_boundary_y=round(float(top), 4),
                rule="arch leading/trailing edge (axle +/- tyre radius) and "
                     "%.2f x height. This is a named REGION cut from a "
                     "continuous shell — it is NOT an opening part and gets no "
                     "hinge." % args.bumper_top_frac)
    for nm, sel in cuts.items():
        for cls, tag in (("carpaint", "Paint"), ("Trim_Black", "Trim")):
            m = sel & (lab == idx[cls]) & ~claimed
            if not m.any():
                continue
            claimed |= m
            parts.append(("%s/%s" % (nm, tag), np.where(m)[0], cls, None, "cut"))

    for cls, nm in (("carpaint", "Body_Shell"), ("Trim_Black", "Trim_Black")):
        m = (lab == idx[cls]) & ~claimed
        if m.any():
            claimed |= m
            parts.append((nm, np.where(m)[0], cls, None, "real"))

    rest = ~claimed
    if rest.any():
        parts.append(("Body_Unclassified", np.where(rest)[0], "carpaint", None,
                      "real"))
        report["unclassified_faces"] = int(rest.sum())
    return parts


def detect_mirrors(lmesh, frame, lab, idx, claimed, args, report):
    """A door mirror is body geometry standing OUTBOARD of the widest point of
    the door skin, in the belt-to-shoulder band. A mesh with no such lobe gets
    no mirror node."""
    C, A = lmesh.triangles_center, lmesh.area_faces
    up = C[:, 1]
    body = (lab == idx["carpaint"]) & ~claimed
    out, info = {}, []
    for side, sgn in (("L", +1), ("R", -1)):
        same = np.sign(C[:, 2]) == sgn
        band = body & same & (up > 0.60 * frame.height) & (up < 0.90 * frame.height)
        door = body & same & (up > 0.40 * frame.height) & (up < 0.60 * frame.height)
        if band.sum() < 200 or door.sum() < 200:
            info.append(dict(side=side, status="absent",
                             reason="no band/door geometry to compare"))
            continue
        wref = float(np.percentile(np.abs(C[door, 2]), 98))
        cand = band & (np.abs(C[:, 2]) > wref + args.mirror_proud)
        if A[cand].sum() < args.mirror_min_area:
            info.append(dict(side=side, status="absent",
                             area=round(float(A[cand].sum()), 5),
                             door_half_width=round(wref, 4),
                             reason="no lobe standing %.0f mm proud of the door"
                                    % (args.mirror_proud * 1000)))
            continue
        out["Mirror_" + side] = cand
        info.append(dict(side=side, status="found",
                         area=round(float(A[cand].sum()), 4),
                         door_half_width=round(wref, 4)))
    report["mirrors"] = info
    return out


# ===========================================================================
# stage 8 — export
# ===========================================================================
def paint_colour_from_texture(scene):
    """Body colour MEASURED from the input's baked atlas, the way
    paint_lock.py does it: the median of the chroma-dominant texels. This is a
    CALCULATED value and is never presented as an OEM paint code."""
    for name, g in scene.geometry.items():
        mat = getattr(getattr(g, "visual", None), "material", None)
        tex = getattr(mat, "baseColorTexture", None)
        if tex is None:
            continue
        img = np.asarray(tex.convert("RGB")).reshape(-1, 3).astype(float)
        chroma = img.max(1) - img.min(1)
        sel = (chroma > 40) & (img.max(1) > 60)
        if sel.sum() < 1000:
            continue
        med = np.median(img[sel], axis=0)
        return [round(float(v), 5) for v in srgb_to_linear(med)], dict(
            source="median of %d chroma-dominant texels in the %s atlas"
                   % (int(sel.sum()), name),
            srgb=[round(float(v), 1) for v in med])
    return None, dict(source="no textured donor — paint colour left at default")


def export(wmesh, frame, parts, out_path, paint_rgb, report):
    """Write the hierarchy. Geometry goes out in the CALLER'S ORIGINAL WORLD
    FRAME (only pivots are converted back from local), so re-running this
    operator can never rotate or re-ground a car."""
    sc = trimesh.Scene()
    used = {}
    for node, faces, cls, pivot_local, prov in parts:
        sub = wmesh.submesh([faces], append=True, repair=False)
        spec = dict(MATERIALS[cls])
        base = spec["base"] if spec["base"] is not None else (paint_rgb or
                                                              [0.35, 0.02, 0.02])
        pbr = PBRMaterial(name=cls,
                          baseColorFactor=list(base) + [spec.get("alpha", 1.0)],
                          metallicFactor=spec["metallic"],
                          roughnessFactor=spec["rough"])
        if spec.get("alpha_mode"):
            pbr.alphaMode = spec["alpha_mode"]
        sub.visual = trimesh.visual.TextureVisuals(material=pbr)
        T = np.eye(4)
        if pivot_local is not None:
            pw = frame.to_world(np.asarray(pivot_local, float))
            sub.vertices = sub.vertices - pw
            T[:3, 3] = pw
        gname = node.replace("/", "_")
        sc.add_geometry(sub, geom_name=gname, node_name=gname, transform=T)
        used[gname] = dict(material=cls, faces=int(len(faces)),
                           area=round(float(wmesh.area_faces[faces].sum()), 5),
                           provenance=prov,
                           pivot_world=None if pivot_local is None else
                           [round(float(v), 4) for v in
                            frame.to_world(np.asarray(pivot_local, float))],
                           spin_axis_world=None if pivot_local is None else
                           [round(float(v), 4) for v in frame.M[2]])
    sc.export(out_path)
    report["nodes"] = used
    patch_extensions(out_path)
    return out_path


def patch_extensions(path):
    """trimesh cannot write KHR_materials_clearcoat / _transmission / _ior, so
    they go in by editing the JSON chunk — the respray_gltf pattern, geometry
    untouched. alphaMode and doubleSided are re-asserted here too: a BLEND flag
    that does not survive export is a SCRAP under the owner's glazing ruling,
    so it is written where the file, not the exporter, decides."""
    with open(path, "rb") as f:
        magic, ver, total = struct.unpack("<III", f.read(12))
        jlen, jtype = struct.unpack("<II", f.read(8))
        j = json.loads(f.read(jlen))
        rest = f.read()
    used = set(j.get("extensionsUsed", []))
    for m in j.get("materials", []):
        spec = MATERIALS.get(m.get("name"))
        if not spec:
            continue
        if spec.get("alpha_mode"):
            m["alphaMode"] = spec["alpha_mode"]
        m["doubleSided"] = bool(spec.get("double", True))
        for k, v in (spec.get("ext") or {}).items():
            m.setdefault("extensions", {})[k] = dict(v)
            used.add(k)
    if used:
        j["extensionsUsed"] = sorted(used)
    jout = json.dumps(j, separators=(",", ":")).encode()
    jout += b" " * (-len(jout) % 4)
    total = 12 + 8 + len(jout) + len(rest)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", magic, ver, total))
        f.write(struct.pack("<II", len(jout), jtype))
        f.write(jout)
        f.write(rest)


# ===========================================================================
# driver
# ===========================================================================
def concat(scene):
    """One face-indexed soup plus the face range each input node occupies, so
    the BEFORE picture can be reported in the terms the defect was raised in."""
    V, F, off, fstart = [], [], 0, 0
    offsets = {}
    for name, g in scene.geometry.items():
        V.append(np.asarray(g.vertices))
        F.append(np.asarray(g.faces) + off)
        offsets[name] = (fstart, fstart + len(g.faces))
        fstart += len(g.faces)
        off += len(g.vertices)
    return trimesh.Trimesh(vertices=np.vstack(V), faces=np.vstack(F),
                           process=False), offsets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glb", required=True)
    ap.add_argument("--out")
    ap.add_argument("--report")
    ap.add_argument("--spec")
    ap.add_argument("--measure-only", action="store_true")
    ap.add_argument("--nose", choices=["auto", "+", "-"], default="auto")
    ap.add_argument("--grid", type=int, default=300,
                    help="ray grid per direction for the visibility cast")
    ap.add_argument("--azimuths", type=int, default=24)
    ap.add_argument("--ao-rays", type=int, default=24)
    ap.add_argument("--ao-reach", type=float, default=0.028,
                    help="cavity reach as a FRACTION of car height")
    ap.add_argument("--ao-cavity", type=float, default=0.55,
                    help="below this openness a visible exterior face is trim")
    ap.add_argument("--trim-max-frac", type=float, default=0.62,
                    help="a cavity above this fraction of the height is a shut "
                         "line or a window surround, not a grille — left paint")
    ap.add_argument("--sill-frac", type=float, default=0.30)
    ap.add_argument("--bumper-top-frac", type=float, default=0.62)
    ap.add_argument("--colour-tol", type=float, default=0.020,
                    help="max donor distance (m) before the atlas colour is "
                         "discarded as unrelated geometry")
    ap.add_argument("--lamp-lum", type=float, default=95.0)
    ap.add_argument("--lamp-chroma", type=float, default=45.0)
    ap.add_argument("--lamp-y0", type=float, default=0.44)
    ap.add_argument("--lamp-y1", type=float, default=0.78)
    ap.add_argument("--lamp-end-frac", type=float, default=0.16)
    ap.add_argument("--lamp-min-area", type=float, default=0.010)
    ap.add_argument("--mirror-proud", type=float, default=0.030)
    ap.add_argument("--mirror-min-area", type=float, default=0.004)
    ap.add_argument("--pane-min-area", type=float, default=0.020)
    ap.add_argument("--no-cut-bumpers", dest="cut_bumpers", action="store_false")
    args = ap.parse_args()

    t0 = time.time()
    report = dict(tool="semantic_rebind.py", input=os.path.abspath(args.glb),
                  args=dict(vars(args)))
    scene = trimesh.load(args.glb, force="scene", process=False)
    wmesh, offsets = concat(scene)
    report["input_mesh"] = dict(faces=int(len(wmesh.faces)),
                                verts=int(len(wmesh.vertices)),
                                nodes=list(offsets.keys()),
                                area=round(float(wmesh.area), 4))

    frame = measure_frame(wmesh, None if args.nose == "auto" else args.nose)
    report["frame"] = frame.as_dict()
    lmesh = trimesh.Trimesh(vertices=frame.to_local(wmesh.vertices),
                            faces=wmesh.faces, process=False)

    spec_tyre = None
    if args.spec:
        sys.path.insert(0, HERE)
        from carspec import CarSpec
        spec = CarSpec.load(args.spec)
        spec_tyre = spec.tyre()
        report["spec"] = dict(path=args.spec, identity=spec.identity(),
                              tyre=spec_tyre)
    else:
        report["spec"] = dict(path=None,
                              note="no spec — every derived value is MEASURED "
                                   "and is APPROXIMATE")

    wheels = detect_wheels(lmesh, frame, spec_tyre, report)
    report["wheels"] = [w.as_dict() for w in wheels]
    gaps = {w.corner: round(float(w.centre[1] - w.radius), 4) for w in wheels}
    report["wheel_ground_gap_m"] = gaps
    bad = {k: v for k, v in gaps.items() if abs(v) > 0.02}
    if bad:
        report["wheel_ground_gap_warning"] = dict(
            corners=bad,
            note="wheel does not sit on the ground plane. This is a GEOMETRY "
                 "defect: reported, NOT repaired — the wheel gate owns it.")

    gmask = glass_seed(scene, lmesh, offsets, frame, report)
    direct, thru, ndirs = visibility(lmesh, gmask, grid=args.grid,
                                     n_az=args.azimuths)
    A = lmesh.area_faces
    report["visibility"] = dict(
        directions=int(ndirs),
        direct_area=round(float(A[direct].sum()), 4),
        through_glass_area=round(float(A[thru].sum()), 4),
        hidden_area=round(float(A[~(direct | thru)].sum()), 4))
    before = {}
    for name, (s, e) in offsets.items():
        m = np.zeros(len(wmesh.faces), bool)
        m[s:e] = True
        before[name] = dict(area=round(float(A[m].sum()), 4),
                            direct_visible_area=round(float(A[m & direct].sum()), 4),
                            through_glass_area=round(float(A[m & thru].sum()), 4))
    report["input_binding"] = before

    ao = None
    vis_idx = np.where(direct)[0]
    if len(vis_idx):
        ao = np.ones(len(lmesh.faces), np.float32)
        ao[vis_idx] = local_ao(lmesh, vis_idx, args.ao_reach * frame.height,
                               n_rays=args.ao_rays)
        report["cavity"] = dict(
            reach_m=round(args.ao_reach * frame.height, 4), rays=args.ao_rays,
            mean_openness=round(float(ao[vis_idx].mean()), 4),
            below_threshold_area=round(float(A[direct & (ao < args.ao_cavity)].sum()), 4))

    col, cold = colour_prior(scene, wmesh.triangles_center)
    if cold is not None:
        report["colour_prior"] = dict(
            donor_dist_p50=round(float(np.percentile(cold, 50)), 4),
            donor_dist_p90=round(float(np.percentile(cold, 90)), 4),
            trusted_face_frac=round(float((cold < args.colour_tol).mean()), 4),
            note="used ONLY as lamp evidence; measured unusable for the lower "
                 "body — see the module docstring")

    lab, per_wheel, wheel_any = classify(lmesh, frame, wheels, gmask, direct,
                                         thru, ao, col, cold, args, report)
    idx = {c: i for i, c in enumerate(CLASSES)}
    after = {}
    for c in CLASSES:
        m = lab == idx[c]
        if not m.any():
            continue
        after[c] = dict(area=round(float(A[m].sum()), 4),
                        direct_visible_area=round(float(A[m & direct].sum()), 4),
                        faces=int(m.sum()))
    report["output_binding"] = after

    if args.measure_only:
        finish(report, args, t0)
        return report

    panes = name_glass_panes(lmesh, frame, lab == idx["glass"], report,
                             args.pane_min_area)
    parts = build_scene(lmesh, frame, lab, per_wheel, panes, wheels, args, report)
    paint_rgb, paint_ev = paint_colour_from_texture(scene)
    report["paint_colour"] = dict(linear=paint_rgb, **paint_ev)

    out = args.out or (os.path.splitext(args.glb)[0] + "_rebound.glb")
    export(wmesh, frame, parts, out, paint_rgb, report)
    report["output"] = dict(path=os.path.abspath(out),
                            bytes=os.path.getsize(out))
    report["gate7"] = gate7_table(report)
    finish(report, args, t0)
    return report


NODE_SPEC = ["Body_Shell", "Bonnet", "Bumper_Front", "Bumper_Rear",
             "Door_FL", "Door_FR", "Door_RL", "Door_RR", "Hatch",
             "Mirror_L", "Mirror_R", "Headlamp_L", "Headlamp_R",
             "TailLamp_L", "TailLamp_R", "Glass_Windscreen",
             "Glass_Door_FL", "Glass_Door_FR", "Glass_Door_RL",
             "Glass_Door_RR", "Glass_Quarter_L", "Glass_Quarter_R",
             "Glass_Rear", "Interior", "Wheel_FL", "Wheel_FR",
             "Wheel_RL", "Wheel_RR"]

# Nodes that cannot exist in a fused generated shell without RECONSTRUCTION.
# Cutting a continuous skin here produces a paper-thin panel with no jamb and
# no seal, which fails the gate's own "no body intersection / no detached
# seals" test the moment it rotates. Reported, never faked.
NOT_ACHIEVABLE = {
    "Bonnet": "no bonnet shut line in the shell; a cut panel would have no "
              "underside, no hinge structure and would expose the engine bay",
    "Door_FL": "doors are not separate geometry",
    "Door_FR": "doors are not separate geometry",
    "Door_RL": "doors are not separate geometry",
    "Door_RR": "doors are not separate geometry",
    "Hatch": "tailgate is not separate geometry",
}


def gate7_table(report):
    """The owner's node list, answered honestly. Three outcomes only:
    PRESENT (with its provenance and whether it can actually animate),
    NOT ACHIEVABLE (with the reason), or ABSENT (the detector found no
    geometry that met its evidence bar). No row is ever satisfied by an empty
    node — a hierarchy that looks compliant and animates nothing is the worst
    possible outcome of this gate."""
    nodes = report.get("nodes", {})
    rows = {}
    for want in NODE_SPEC:
        if want in NOT_ACHIEVABLE:
            rows[want] = dict(status="NOT ACHIEVABLE", reason=NOT_ACHIEVABLE[want])
            continue
        hit = sorted(n for n in nodes if n == want or n.startswith(want + "_"))
        if hit:
            provs = sorted({nodes[n]["provenance"] for n in hit})
            anim = any(nodes[n].get("pivot_world") for n in hit)
            rows[want] = dict(status="PRESENT", provenance="+".join(provs),
                              nodes=hit, animatable=bool(anim),
                              faces=int(sum(nodes[n]["faces"] for n in hit)),
                              area=round(sum(nodes[n]["area"] for n in hit), 4))
        else:
            rows[want] = dict(status="ABSENT",
                              reason="no geometry met the detector's evidence "
                                     "bar; no empty node was created")
    extra = [n for n in nodes
             if not any(n == w or n.startswith(w + "_") for w in NODE_SPEC)]
    if extra:
        rows["_additional_nodes"] = sorted(extra)
    return rows


def _np(o):
    """numpy scalars are not JSON — and a report that cannot be written is a
    run that cannot be audited, so this never silently drops a value."""
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(repr(o))


def finish(report, args, t0):
    report["seconds"] = round(time.time() - t0, 1)
    txt = json.dumps(report, indent=1, default=_np)
    if args.report:
        with open(args.report, "w") as f:
            f.write(txt)
        print("report ->", args.report)
    print(json.dumps({k: report[k] for k in
                      ("frame", "wheels", "visibility", "output_binding")
                      if k in report}, indent=1, default=_np))
    if "gate7" in report:
        print("\nGATE 7 node table")
        for k, v in report["gate7"].items():
            print("  %-20s %s %s" % (k, v["status"],
                                     v.get("reason", "") or
                                     ("provenance=%s animatable=%s"
                                      % (v.get("provenance"), v.get("animatable")))))
    print("\n%.1fs" % report["seconds"])


if __name__ == "__main__":
    main()
