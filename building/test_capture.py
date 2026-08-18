"""Tests for the capture plan — the shot list a homeowner actually follows.

The point of this module is that the plan is computed from the building
rather than recited, so the tests are about it CHANGING with the building:
a tight alley must produce a closer, denser, tiered walk, and a party wall
must produce a refusal with a reason rather than an instruction nobody can
carry out.

Run: python building/test_capture.py
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import capture as C  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("ok   " if cond else "FAIL ") + name
          + (f"  [{detail}]" if detail and not cond else ""))


def model(width=13.167, depth=9.908, ridge=8.03, clear=None):
    return {
        "roof": {"ridge_z_m": ridge},
        "eaves_z_m": 5.5,
        "site": {
            "address": "test",
            "plan_m": {"width": width, "depth": depth},
            "clearances_m": clear if clear is not None else {
                "south": 12.0, "north": 12.0, "east": 2.75, "west": 0.0},
            "frame": {"angle_rad": 0.0, "origin_en": [413200.0, 289290.0],
                      "anchor_en": [413218.44, 289299.6]},
        },
    }


# --- 1. standing far enough back --------------------------------------------
# An 8.03m ridge with the phone at 1.5m leaves 6.53m to cover above it, and a
# 69.4 degree vertical field of view covers that at 6.53/tan(34.7) = 9.4m,
# plus the 1.18 margin.
d = C.standoff(8.03)
check("1a full-height standoff for an 8m ridge", abs(d - 11.1) < 0.2, str(d))
check("1b a taller house needs more room", C.standoff(11.0) > d)
check("1c a bungalow is floored at the minimum",
      C.standoff(3.0) == C.MIN_STANDOFF_M, str(C.standoff(3.0)))
try:
    C.standoff(8.0, fov_deg=0.0)
    check("1d a camera with no field of view is refused", False)
except ValueError:
    check("1d a camera with no field of view is refused", True)

# Frame spacing must fall as you get closer, or a tight alley is undersampled.
check("1e closer means smaller steps", C.frame_step(2.45) < C.frame_step(11.1))
step = C.frame_step(11.1)
across = 2 * 11.1 * math.tan(math.radians(C.FOV_WIDE_DEG) / 2)
check("1f step leaves the required overlap",
      abs(step - across * (1 - C.OVERLAP)) < 0.01, str(step))


# --- 2. bearings and positions ----------------------------------------------
check("2a north is 000", abs(C.bearing_to((0, 0), (0, 5))) < 1e-6)
check("2b east is 090", abs(C.bearing_to((0, 0), (5, 0)) - 90) < 1e-6)
check("2c south is 180", abs(C.bearing_to((0, 0), (0, -5)) - 180) < 1e-6)

# A point 10m north of the anchor must come back ~10m north in latitude.
lat, lon = 52.50144, -1.806705
anchor = [413218.44, 289299.6]
got = C.to_latlon((0.0, 0.0), 0.0, [anchor[0], anchor[1] + 10.0],
                  lat, lon, anchor)
# Tolerance is 2e-7 degrees, not something tighter: to_latlon rounds to 7
# decimal places, which is about a centimetre, and a centimetre is already
# far finer than a person standing where a plan tells them to.
check("2d ten metres north moves latitude by 10/111320",
      abs((got[0] - lat) - 10.0 / C.M_PER_DEG_LAT) < 2e-7, str(got))
same = C.to_latlon((0.0, 0.0), 0.0, anchor, lat, lon, anchor)
check("2e the anchor maps to itself",
      abs(same[0] - lat) < 1e-7 and abs(same[1] - lon) < 1e-7, str(same))


# --- 3. each elevation gets its own standoff --------------------------------
p = C.plan(model(), lat, lon)
check("3a the open sides use the full-height standoff",
      abs(p["standoff_m"]["front"] - 11.1) < 0.2, str(p["standoff_m"]))
check("3b the 2.75m alley is walked from inside it",
      p["standoff_m"]["east"] <= 2.75 - 0.3 + 1e-9,
      str(p["standoff_m"].get("east")))
check("3c and never closer than the clearance allows",
      p["standoff_m"]["east"] > 0)
check("3d a tight side is shot in tiers", p["tiers"]["east"] > 1,
      str(p["tiers"]))
check("3e an open side needs only one", p["tiers"]["front"] == 1,
      str(p["tiers"]))
check("3f tiers are capped", max(p["tiers"].values()) <= C.MAX_TIERS)
check("3g the tight side is named", "east" in p["tight_sides"],
      str(p["tight_sides"]))
check("3h a tight side is sampled more finely",
      p["frame_step_m"]["east"] < p["frame_step_m"]["front"])


# --- 4. a party wall is refused, with a reason ------------------------------
west = [b for b in p["blocked"] if b["side"] == "west"]
check("4a the attached side is blocked", len(west) == 1, str(p["blocked"]))
if west:
    check("4b and it says why", "party wall" in west[0]["why"].lower(),
          west[0]["why"][:60])
check("4c no shots are planned on a wall nobody can reach",
      all(s["side"] != "west" for s in p["shots"]))
check("4d the reachable sides are all planned",
      {s["side"] for s in p["shots"]} == {"front", "east", "rear"},
      str({s["side"] for s in p["shots"]}))

# A detached house on an open plot blocks nothing.
opn = C.plan(model(clear={"south": 12.0, "north": 12.0,
                          "east": 9.0, "west": 9.0}), lat, lon)
check("4e an open plot blocks nothing", opn["blocked"] == [], str(opn["blocked"]))
check("4f and walks all four elevations",
      {s["side"] for s in opn["shots"]} == {"front", "east", "rear", "west"})

# A house wedged on every side has no capture to plan, and says so.
try:
    C.plan(model(clear={"south": 0.0, "north": 0.0, "east": 0.0,
                        "west": 0.0}), lat, lon)
    check("4g a fully enclosed building is refused", False)
except ValueError as e:
    check("4g a fully enclosed building is refused", "nowhere" in str(e).lower(),
          str(e))

try:
    C.plan({"site": {"plan_m": {}}}, lat, lon)
    check("4h no measured plan is refused", False)
except ValueError:
    check("4h no measured plan is refused", True)


# --- 5. the shot list is usable ---------------------------------------------
check("5a shots are numbered from one without gaps",
      [s["no"] for s in p["shots"]] == list(range(1, len(p["shots"]) + 1)))
check("5b every shot carries real coordinates",
      all(52.4 < s["gps"]["lat"] < 52.6 and -1.9 < s["gps"]["lon"] < -1.7
          for s in p["shots"]))
check("5c every shot has a heading", all(0 <= s["heading_deg"] <= 360
                                         for s in p["shots"]))
check("5d tiers are labelled with a tilt",
      {s["tilt"] for s in p["shots"] if s["side"] == "east"} != {"level"})
check("5e the plan is a real session, not a token one",
      40 < len(p["shots"]) < 400, str(len(p["shots"])))
check("5f three passes, including LiDAR", len(p["passes"]) == 3
      and any("LiDAR" in r["name"] for r in p["passes"]))
# The first version of this check ended in `or True` — a tautology that
# passed whatever the pass said. capture.py carries the range only in the
# pass's note text, so the note is what can be pinned: every LiDAR pass
# must state the walking distance, and the constant it states must be
# Apple LiDAR's confident ~5m — at 50m the depth sensor is extrapolating
# and the scale anchor the pass exists for is noise.
check("5g the close pass states the 5m LiDAR range in its instruction",
      C.LIDAR_RANGE_M == 5.0
      and all("LiDAR" not in r["name"]
              or f"within {C.LIDAR_RANGE_M:.0f}m" in r["note"]
              for r in p["passes"]),
      str([r["note"] for r in p["passes"] if "LiDAR" in r["name"]]))
check("5h it warns about what it cannot see",
      "fences" in p["warning"] and "parked cars" in p["warning"])
check("5i and about walking rather than turning",
      any("WALK" in r["note"] for r in p["passes"]))

# The standoff shrinking must actually shrink the walking ring, or the shots
# are computed at one distance and described at another.
runs = dict((r[0], r) for r in C.side_runs(13.167, 9.908,
                                           {"front": 11.1, "east": 2.45,
                                            "rear": 11.1, "west": 2.45}))
check("5j the east run sits at the east standoff",
      abs(runs["east"][1][0] - (13.167 + 2.45)) < 1e-9, str(runs["east"]))
check("5k the front run sits at the front standoff",
      abs(runs["front"][1][1] + 11.1) < 1e-9, str(runs["front"]))


print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
