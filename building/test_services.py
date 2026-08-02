"""Tests for Services Mode — the X-ray.

A builder may drill on the strength of this output, so the tests that matter
are the ones where it refuses to guess: a diameter between two pipe sizes, a
run it cannot size, a closed scan that cannot contain services at all.

The BS 7671 safe-zone check is the other half. A cable outside a permitted
zone at shallow depth is where somebody puts a shelf bracket through a live
cable, and finding one is worth more than any quantity in this module.

Run: python building/test_services.py
"""
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
WALL = {"plane": (0.0, 1.0, 0.0, 0.0), "width_m": 4.0, "height_m": 2.4}


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

check("3c2 profile from two dimensions — flat",
      V.profile_of(0.0040, 0.0100) == "flat")
check("3c3 profile from two dimensions — round",
      V.profile_of(0.0150, 0.0150) == "round")
check("3c4 an in-between ratio is not guessed",
      V.profile_of(0.010, 0.015) is None)
check("3c5 one dimension is not a profile", V.profile_of(0.010, None) is None)

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
          "width_m": 0.0100, "length_m": 1.5, "axis": "horizontal"}
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
pipe = dict(hazard, thickness_m=0.015, width_m=0.015)
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


# ==========================================================================
print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
