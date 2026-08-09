"""Tests for Services Mode — the X-ray.

A builder may drill on the strength of this output, so the tests that matter
are the ones where it refuses to guess: a diameter between two pipe sizes, a
run it cannot size, a closed scan that cannot contain services at all.

The BS 7671 safe-zone check is the other half. A cable outside a permitted
zone at shallow depth is where somebody puts a shelf bracket through a live
cable, and finding one is worth more than any quantity in this module.

Run: python building/test_services.py
"""
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import services as V  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(
        name if cond else f"{name}{' — ' + detail if detail else ''}")


# A wall in the y=0 plane, normal along +y, 4m wide and 2.4m tall.
# origin is the wall's bottom-left corner in world space. Without it the
# (u, v) coordinates below are raw world projections, not positions on
# this wall — see project_to_plane.
WALL = {"plane": (0.0, 1.0, 0.0, 0.0), "origin": (0.0, 0.0, 0.0),
        "width_m": 4.0, "height_m": 2.4}


# ---- 1. geometry ----------------------------------------------------------
check("1a distance to plane", V.point_to_plane((1, 0.05, 1), WALL["plane"])
      == 0.05)
u, v = V.plane_basis(WALL["plane"])
check("1b basis vectors are unit",
      abs(sum(c * c for c in u) - 1) < 1e-9
      and abs(sum(c * c for c in v) - 1) < 1e-9)
check("1c v points up the wall", abs(v[2]) > 0.9, str(v))

try:
    V.plane_basis((0.0, 0.0, 0.0, 0.0))
    check("1d a degenerate plane is refused", False)
except V.ServicesError:
    check("1d a degenerate plane is refused", True)


# ---- 2. separating the void from the wall ---------------------------------
# The wall surface itself is not a service.
surface = [(x * 0.02, 0.002, 1.0) for x in range(50)]
check("2a points on the surface are not services",
      V.void_points(surface, WALL["plane"]) == [])

# Something 40mm behind it is.
behind = [(x * 0.02, 0.04, 1.0) for x in range(50)]
check("2b points in the void are", len(V.void_points(behind, WALL["plane"])) == 50)

# Something 600mm behind is the next room, not this wall's void.
far = [(x * 0.02, 0.6, 1.0) for x in range(50)]
check("2c points beyond the stud depth are excluded",
      V.void_points(far, WALL["plane"]) == [])


# ---- 3. identifying real UK products --------------------------------------
for size_m, want in [(0.015, "copper_15"), (0.022, "copper_22"),
                     (0.028, "copper_28"), (0.040, "waste_40"),
                     (0.110, "soil_110")]:
    got = V.identify(size_m)
    check(f"3a {size_m * 1000:.0f}mm -> {want}",
          got and got.get("type") == want, str(got))

check("3b copper 15 is not a cable", not V.identify(0.015)["is_cable"])

# THE genuine collision in the table, and it is not a bug: 10mm microbore
# copper and 2.5mm2 twin-and-earth are both nominally 10mm across. No
# measurement of ONE dimension can separate them.
ambiguous = V.identify(0.0100)
check("3b2 10mm alone cannot be resolved", ambiguous["type"] is None,
      str(ambiguous))
check("3b3 and it says how to resolve it",
      "width_m" in ambiguous["note"], ambiguous["note"])

# Copper is round; T&E is flat, about 10mm by 4mm. THAT separates them.
check("3b4 round at 10mm is copper",
      V.identify(0.0100, "round")["type"] == "copper_10")
check("3b5 flat at 10mm is T&E",
      V.identify(0.0100, "flat")["type"] == "twin_earth_2.5")
check("3c and T&E reads as a cable", V.identify(0.0100, "flat")["is_cable"])

# The profile comes from the SHAPE of the cross-section, not from a ratio of
# two extents. The ratio could never have worked: a scanner sees the near
# half of a pipe, so a pipe's measured depth is its RADIUS and its
# width-to-depth ratio is about 2 — identical to a cable's. Both read
# "flat", and 10mm copper was reported as 2.5mm2 twin-and-earth.
check("3c2 a flat face reads flat",
      V.profile_of({"flat_share": 1.0}) == "flat")
check("3c3 a curved cross-section reads round",
      V.profile_of({"flat_share": 0.4}) == "round")
check("3c4 an in-between shape is not guessed",
      V.profile_of({"flat_share": 0.72}) is None)
check("3c5 too narrow to resolve a shape is not a profile",
      V.profile_of({"flat_share": None}) is None)
check("3c6 a run with no profile at all is not a profile",
      V.profile_of({}) is None)

# characteristic_size returns the SILHOUETTE width for both families: a
# pipe's diameter and a cable's width across the flat. Returning the depth
# for round goods asked for a 7.5mm product when looking at 15mm copper.
check("3c7 a pipe is named by the width the scan sees, its diameter",
      V.characteristic_size(
          {"width_m": 0.015, "flat_share": 0.4}) == (0.015, "round"))
check("3c8 and a cable by its width across the flat",
      V.characteristic_size(
          {"width_m": 0.010, "flat_share": 1.0}) == (0.010, "flat"))

# THE refusal. 20mm conduit and 22mm copper overlap within scan tolerance,
# and the difference is a wrong materials list — so a measurement that could
# be either is reported as neither.
between = V.identify(0.0207)
check("3d a diameter between two products is not snapped",
      between["type"] is None, str(between))
check("3e and it names the candidates",
      "candidates" in between and len(between["candidates"]) == 2, str(between))
check("3f and says how to resolve it",
      "measure it" in between["note"] or "width_m" in between["note"],
      between["note"])

odd = V.identify(0.070)
check("3g a non-standard size is refused", odd["type"] is None)
check("3h and says so plainly", "does not match" in odd["note"], odd["note"])
check("3i but still reports what it measured", odd["measured_mm"] == 70.0)

check("3j nothing in, nothing out", V.identify(None) is None)
check("3k zero is not a pipe", V.identify(0) is None)


# ---- 4. BS 7671 safe zones ------------------------------------------------
# Reg 522.6.202/203 — within 150mm of the top, within 150mm of an angle, or
# in line with an accessory.
top = {"u_m": 2.0, "v_m": 2.32, "depth_m": 0.03}
check("4a within 150mm of the top is a zone",
      V.in_safe_zone(top, WALL)["in_zone"])
check("4b and the reason is given",
      "top of the wall" in V.in_safe_zone(top, WALL)["reasons"][0])

corner = {"u_m": 0.08, "v_m": 1.2, "depth_m": 0.03}
check("4c within 150mm of an angle is a zone",
      V.in_safe_zone(corner, WALL)["in_zone"])
far_corner = {"u_m": 3.95, "v_m": 1.2, "depth_m": 0.03}
check("4d the far angle counts too",
      V.in_safe_zone(far_corner, WALL)["in_zone"])

middle = {"u_m": 2.0, "v_m": 1.2, "depth_m": 0.03}
check("4e the middle of a wall is NOT a zone",
      not V.in_safe_zone(middle, WALL)["in_zone"])

# ...unless it lines up with a socket.
socket = [{"u_m": 2.0, "v_m": 0.45, "name": "socket"}]
check("4f in line with an accessory is a zone",
      V.in_safe_zone(middle, WALL, socket)["in_zone"])
check("4g and names it",
      "socket" in V.in_safe_zone(middle, WALL, socket)["reasons"][0])

try:
    V.in_safe_zone(middle, {"plane": WALL["plane"]})
    check("4h zones need the wall's dimensions", False)
except V.ServicesError as e:
    check("4h zones need the wall's dimensions", "width" in str(e))


# ---- 5. the finding that matters ------------------------------------------
# A shallow cable outside every permitted zone. This is the output worth more
# than every quantity in the module.
hazard = {"u_m": 2.0, "v_m": 1.2, "depth_m": 0.02, "thickness_m": 0.0040,
          "width_m": 0.0100, "flat_share": 1.0, "length_m": 1.5, "axis": "horizontal"}
r = V.check_run(hazard, WALL)
check("5a identified as a cable", r["identity"]["is_cable"])
check("5b and it FAILS", r["compliance"]["verdict"] == "FAIL", str(r))
check("5c flagged critical", r["compliance"]["severity"] == "critical")
check("5d citing the regulation", "522.6.202" in r["compliance"]["note"])
check("5e and saying what it means in plain words",
      "shelf bracket" in r["compliance"]["note"])

# Same cable, but deep enough that the regulation does not bite.
deep = dict(hazard, depth_m=0.08)
check("5f a deep cable passes",
      V.check_run(deep, WALL)["compliance"]["verdict"] == "PASS")
check("5g and says why", "50mm" in V.check_run(deep, WALL)["compliance"]["note"])

# Same cable, in a zone.
zoned = dict(hazard, v_m=2.35)
check("5h a cable in a permitted zone passes",
      V.check_run(zoned, WALL)["compliance"]["verdict"] == "PASS")

# A PIPE outside a "safe zone" is not a regulatory problem — it is a pipe.
# Reporting it as one would bury the cable findings that matter.
pipe = dict(hazard, thickness_m=0.015, width_m=0.015, flat_share=0.4)
p = V.check_run(pipe, WALL)
check("5i a pipe gets no compliance verdict", p["compliance"] is None,
      str(p.get("compliance")))


# ---- 6. tracing runs ------------------------------------------------------
def run_points(along, fixed_v, depth, thickness=0.004, n=60):
    """A straight horizontal run in the wall's u direction."""
    pts = []
    for i in range(n):
        u = along + i * 0.02
        for t in range(3):
            pts.append((u, depth + t * thickness / 2, fixed_v))
    return pts


cloud = run_points(0.5, 1.2, 0.03) + run_points(0.5, 2.30, 0.02)
void = V.void_points(cloud, WALL["plane"])
check("6a void points found", len(void) > 100, str(len(void)))

runs = V.trace_runs(void, WALL["plane"])
check("6b runs traced", len(runs) >= 2, str(len(runs)))
check("6c a run is about the right length",
      any(1.0 < r["length_m"] < 1.5 for r in runs),
      str([r["length_m"] for r in runs]))
check("6d short noise is dropped",
      all(r["length_m"] >= V.MIN_RUN_LENGTH_M for r in runs))
check("6e depth recorded", all("depth_m" in r for r in runs))
check("6f nothing in, nothing out", V.trace_runs([], WALL["plane"]) == [])


# ---- 7. end to end --------------------------------------------------------
result = V.extract(cloud, WALL)
check("7a runs reported", result["totals"]["runs"] >= 2, str(result["totals"]))
check("7b basis says it was measured, not inferred",
      "none of it is inferred" in result["basis"])
check("7c the axis-aligned limit is stated",
      any("axis-aligned" in w for w in result["warnings"]))
check("7d and the date limit — this records what was EXPOSED",
      any("installed after" in w for w in result["warnings"]),
      str(result["warnings"]))

# An already-boarded wall has nothing in its void, and saying so is more
# useful than returning an empty list.
empty = V.extract(surface, WALL)
check("7e a boarded wall reports why it is empty",
      empty["totals"]["runs"] == 0
      and any("already boarded" in w for w in empty["warnings"]),
      str(empty["warnings"]))

for bad, phrase in [({"width_m": 4.0}, "wall plane"),
                    ({"plane": (0, 1, 0, 0)}, "width")]:
    try:
        V.extract(cloud, bad)
        check(f"7f refused: {phrase}", False)
    except V.ServicesError as e:
        check(f"7f refused: {phrase}", phrase.split()[0] in str(e), str(e))

try:
    V.extract([], WALL)
    check("7g an empty cloud is refused", False)
except V.ServicesError:
    check("7g an empty cloud is refused", True)


# ---- 8. handler entry -----------------------------------------------------
class _Prog:
    def stage(self, *a, **k):
        pass


import reconstruct as R  # noqa: E402
TMP = tempfile.gettempdir()
OUT = os.path.join(TMP, "services-test")
cloud_path = os.path.join(TMP, "open.ply")
R.write_ply(cloud_path, cloud)

arts, extra = V.run({"point_cloud_path": cloud_path, "wall": WALL,
                     "stage": "open", "scan_id": "x1"}, _Prog(), OUT)
check("8a end to end", extra["services"]["totals"]["runs"] >= 2)
check("8b artifact written", os.path.exists(arts[0][0]))

# THE conceptual guard. Services cannot come from a closed scan — that is the
# entire premise of the product, and accepting one would mean the output was
# inferred while looking measured.
try:
    V.run({"point_cloud_path": cloud_path, "wall": WALL, "stage": "closed"},
          _Prog(), OUT)
    check("8c a closed scan is refused", False)
except V.ServicesError as e:
    check("8c a closed scan is refused", "OPEN scan" in str(e), str(e))
    check("8d and explains the idea", "before boarding" in str(e))

for bad, phrase in [({}, "open-scan"), ({"point_cloud_path": cloud_path},
                                        "wall")]:
    try:
        V.run(bad, _Prog(), OUT)
        check(f"8e refused: {phrase}", False)
    except V.ServicesError as e:
        check(f"8e refused: {phrase}", phrase.split()[0] in str(e), str(e))

try:
    V.run({"point_cloud_url": "file:///etc/passwd", "wall": WALL},
          _Prog(), OUT)
    check("8f a local-file URL is refused", False)
except Exception as e:
    check("8f a local-file URL is refused",
          "http" in str(e).lower() or "scheme" in str(e).lower(), str(e)[:70])


# ---- 9. through the REAL pipeline, not a hand-authored run ---------------
# Every assertion above this point fed check_run() a dict written by hand,
# carrying keys — width_m especially — that no code path in the module ever
# produced. So the tests exercised an identification chain the worker could
# not reach: trace_runs emitted no width_m, profile_of therefore always
# returned None, identify was never confident, is_cable was never set, and
# totals.compliance_failures was structurally always zero. A module whose
# stated purpose is finding a cable before somebody drills into it could not
# report one, and 68 tests passed.
#
# These build point clouds and run them through extract().

def _wall(x0, y0, x1, y1, height=2.4, base_z=0.0):
    length = math.hypot(x1 - x0, y1 - y0)
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    nx, ny = -uy, ux
    return {"plane": (nx, ny, 0.0, -(nx * x0 + ny * y0)),
            "origin": (x0, y0, base_z),
            "width_m": length, "height_m": height}


def _at(wall, u, v, standoff):
    """A point u along the wall, v up it, standoff out from its face.

    THIS HELPER CARRIED THE SAME SIGN ERROR AS plane_basis, so the two
    agreed with each other and both disagreed with the building: for a wall
    traced (0,0)->(4,0) it placed "2m along" at x = -2. Section 9g passed
    throughout while every real run projected through plane_basis came back
    at negative u and in_safe_zone refused it as "outside the wall — no zone
    judgement is possible". A fixture that shares the code's mistake tests
    nothing. u now runs WITH the wall: +u is (b, -a) for a normal (a, b).
    """
    (x0, y0, z0) = wall["origin"]
    a, b, _c, _d = wall["plane"]
    return (x0 + b * u + a * standoff, y0 - a * u + b * standoff, z0 + v)


def _pipe(wall, u0, v0, length, diameter, vertical=False, clear=0.020,
          step=0.003, arc=32):
    """The surface of a cylinder that faces the room: a curved cross-section
    deepest along its crown. A scanner only ever sees this half, which is
    why the measured depth is the RADIUS, not the diameter."""
    pts, r = [], diameter / 2.0
    for i in range(int(length / step) + 1):
        along = i * step
        for k in range(arc + 1):
            angle = -math.pi / 2 + math.pi * k / arc
            across = r * math.sin(angle)
            standoff = clear + r + r * math.cos(angle)
            u, v = ((u0 + across, v0 + along) if vertical
                    else (u0 + along, v0 + across))
            pts.append(_at(wall, u, v, standoff))
    return pts


def _cable(wall, u0, v0, length, width, thickness, vertical=False,
           clear=0.020, step=0.001):
    """A flat cable: a constant-depth face, then two sharp edges."""
    pts = []
    across_steps = max(1, int(width / step))
    depth_steps = max(1, int(thickness / step))
    for i in range(int(length / step) + 1):
        along = i * step
        for j in range(across_steps + 1):
            across = -width / 2 + j * width / across_steps
            u, v = ((u0 + across, v0 + along) if vertical
                    else (u0 + along, v0 + across))
            pts.append(_at(wall, u, v, clear + thickness))
        for j in range(depth_steps + 1):
            for across in (-width / 2, width / 2):
                u, v = ((u0 + across, v0 + along) if vertical
                        else (u0 + along, v0 + across))
                pts.append(_at(wall, u, v, clear + j * thickness / depth_steps))
    return pts


WALL9 = _wall(0.0, 0.0, 4.0, 0.0)

# Every standard round product, identified from its shape and its silhouette.
for _dia, _want in [(0.010, "copper_10"), (0.015, "copper_15"),
                    (0.022, "copper_22"), (0.040, "waste_40"),
                    (0.110, "soil_110")]:
    _r = V.extract(_pipe(WALL9, 1.0, 1.0, 1.0, _dia), WALL9)
    _a = _r["runs"][0]
    check(f"9a {_dia * 1000:.0f}mm pipe identified through the real pipeline",
          _a["identity"] and _a["identity"].get("type") == _want,
          f"{_a['identity']} from width "
          f"{_a['run']['width_m'] * 1000:.1f}mm "
          f"share {_a['run']['flat_share']}")
    check(f"9b {_dia * 1000:.0f}mm pipe is not called a cable",
          not (_a["identity"] or {}).get("is_cable"))

# THE collision, resolved end to end: 10mm copper against 2.5mm2 T&E. Both
# are 10mm across. Only the cross-section shape separates them, and the
# ratio test that used to do it put copper in the cable table.
_copper = V.extract(_pipe(WALL9, 1.0, 1.0, 1.0, 0.010), WALL9)["runs"][0]
_te = V.extract(_cable(WALL9, 1.0, 1.0, 1.0, 0.010, 0.004),
                WALL9)["runs"][0]
check("9c 10mm copper and 2.5mm2 T&E measure the same width",
      abs(_copper["run"]["width_m"] - _te["run"]["width_m"]) < 0.002,
      f"{_copper['run']['width_m']} vs {_te['run']['width_m']}")
check("9d and the shape still separates them",
      _copper["identity"]["type"] == "copper_10"
      and _te["identity"]["type"] == "twin_earth_2.5",
      f"{_copper['identity']['type']} / {_te['identity']['type']}")

# The whole point of the module: a shallow cable outside every zone, found
# from a point cloud.
_hazard = V.extract(_cable(WALL9, 2.0, 1.2, 1.5, 0.010, 0.004, clear=0.021),
                    WALL9)
check("9e a buried cable is reported as a cable",
      _hazard["totals"]["cables"] == 1, str(_hazard["totals"]))
check("9f and it FAILS BS 7671",
      _hazard["totals"]["compliance_failures"] == 1, str(_hazard["totals"]))

# The same cable in the same room, moved. u_m is a position ON THE WALL, so
# it must not change — it used to be a raw world projection, and the same
# cable read u=6.38 on a 4m wall once the room moved, or u=458210 on the OS
# grid, which flipped every safe-zone verdict to PASS.
for _ox, _oy, _label in [(6.0, 0.0, "moved 6m along"),
                         (458210.0, 289400.0, "surveyed on the OS grid"),
                         (0.0, 0.0, "at the origin")]:
    _w = _wall(_ox, _oy, _ox + 4.0, _oy)
    _r = V.extract(_cable(_w, 2.0, 1.2, 1.5, 0.010, 0.004, clear=0.021), _w)
    check(f"9g {_label}: the cable is still 2.0m along the wall",
          abs(_r["runs"][0]["run"]["u_m"] - 2.0) < 0.02,
          str(_r["runs"][0]["run"]["u_m"]))
    check(f"9h {_label}: and still FAILS",
          _r["totals"]["compliance_failures"] == 1, str(_r["totals"]))

# One 110mm soil pipe is one run. It used to fragment into three, totalling
# 6.06m for a 2.00m pipe, two of them bogus "unsized".
_soil = V.extract(_pipe(WALL9, 1.0, 0.3, 2.0, 0.110, vertical=True), WALL9)
check("9i a fat pipe is one run, not three", len(_soil["runs"]) == 1,
      str([r["run"]["length_m"] for r in _soil["runs"]]))
check("9j and its length is its length",
      abs(_soil["runs"][0]["run"]["length_m"] - 2.0) < 0.05,
      str(_soil["runs"][0]["run"]["length_m"]))

# in_safe_zone used to test only a run's START corner. A cable straight
# across the middle of a wall passed because its left end touched a corner,
# while 3.7m of it sat in no zone at all.
_across = {"u_m": 0.0, "v_m": 1.2, "u_end_m": 4.0, "v_end_m": 1.2,
           "length_m": 4.0, "axis": "horizontal", "depth_m": 0.02}
check("9k a cable spanning the whole wall is not 'in the corner zone'",
      not V.in_safe_zone(_across, WALL9)["in_zone"],
      str(V.in_safe_zone(_across, WALL9)))

# Every bound used to be one-sided, so anything outside the wall's range
# satisfied it — and every error pointed at PASS.
_outside = {"u_m": 9.0, "v_m": 1.2, "u_end_m": 9.5, "v_end_m": 1.2,
            "length_m": 0.5, "axis": "horizontal", "depth_m": 0.02}
_verdict = V.in_safe_zone(_outside, WALL9)
check("9l a run off the end of the wall is not silently 'in a zone'",
      not _verdict["in_zone"], str(_verdict))
check("9m and it says the coordinates do not fit the wall",
      "outside the wall" in (_verdict.get("note") or ""), str(_verdict))

_above = {"u_m": 2.0, "v_m": 3.9, "u_end_m": 2.0, "v_end_m": 4.4,
          "length_m": 0.5, "axis": "vertical", "depth_m": 0.02}
check("9n nor is one above the wall's head",
      not V.in_safe_zone(_above, WALL9)["in_zone"],
      str(V.in_safe_zone(_above, WALL9)))


# ==========================================================================
print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
