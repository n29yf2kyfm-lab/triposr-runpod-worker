"""Tests for the Google Solar cross-check.

Every one of these runs against `fixtures_solar_pub.json` — a REAL
buildingInsights response for a real UK pub conversion,
HIGH quality imagery dated 2023-05-03. Not a hand-written mock. The two bugs
this file exists to pin down were both invisible to a mock, because a mock
gets written with the same wrong idea of the payload that the parser had.

WHAT WENT WRONG, LIVE:

  1. `predominant_pitch_deg` took the single LARGEST roof plane. On a simple
     roof that is the roof. On a real pub roof — twelve planes, the biggest being
     18% of the area at 57.8 degrees, which is a dormer cheek or a gable —
     it reported 57.8 for a roof the height model puts at 33.8.

  2. `building_area_m2` read `buildingStats.areaMeters2`, which is the roof
     SURFACE, and compare() then divided it by cos(pitch) to imply a roof
     area — applying the slope twice.

Together they turned a 278 m2 roof into 578 m2. Ordering tiles off that is
not a rounding error, it is twice the roof.

Network-free: the fixture is on disk.

Run: python building/test_solar.py
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import solar as S  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(
        name if cond else f"{name}{' — ' + detail if detail else ''}")


PUB = json.load(open(os.path.join(HERE, "fixtures_solar_pub.json")))
R = S.parse_segments(PUB)


# ---- 1. the fixture is what we think it is --------------------------------

check("1a the fixture is HIGH quality", R["quality"] == "HIGH")
check("1b dated", R["imagery_date"] == "2023-05-03", str(R["imagery_date"]))
check("1c twelve roof planes", R["segments"] == 12, str(R["segments"]))
check("1d every plane has a pitch and an area",
      all(p["pitch_deg"] is not None and p["sloped_area_m2"] > 0
          for p in R["planes"]))


# ---- 2. footprint vs surface ----------------------------------------------
# Solar reports both and they differ by the pitch. Reading one as the other
# is the whole bug.

check("2a footprint comes from groundAreaMeters2",
      R["footprint_m2"] == 224.49, str(R["footprint_m2"]))
check("2b the roof SURFACE is a separate, larger figure",
      R["building_area_m2"] == 308.01 > R["footprint_m2"],
      f"{R['building_area_m2']} vs {R['footprint_m2']}")
check("2c and the measured roof area is reported as measured",
      R["whole_roof_area_m2"] == 277.81, str(R["whole_roof_area_m2"]))
check("2d a surface is never smaller than its own footprint",
      R["whole_roof_area_m2"] > R["roof_ground_area_m2"])

# THE COS PROJECTION, VALIDATED AGAINST SOLAR'S OWN ARITHMETIC. Summing each
# segment's area times cos(its pitch) must reproduce the ground area Solar
# publishes independently. It does, exactly — which is the only proof
# available that this module reads pitch and area the right way round.
check("2e summing area*cos(pitch) reproduces Solar's own ground area exactly",
      abs(R["plan_area_m2"] - R["roof_ground_area_m2"]) < 0.01,
      f"{R['plan_area_m2']} vs {R['roof_ground_area_m2']}")

# The same check the other way: had the module divided instead of multiplied,
# it would land here and nowhere near the truth.
wrong = sum(p["sloped_area_m2"] / math.cos(math.radians(p["pitch_deg"]))
            for p in R["planes"])
check("2f dividing instead of multiplying would be visibly wrong",
      abs(wrong - R["roof_ground_area_m2"]) > 100,
      f"{wrong:.1f} vs {R['roof_ground_area_m2']}")


# ---- 3. pitch is area-weighted, not the biggest plane ----------------------

biggest = max(R["planes"], key=lambda p: p["sloped_area_m2"])
check("3a the biggest single plane is a steep outlier",
      biggest["pitch_deg"] > 55, str(biggest["pitch_deg"]))
check("3b and it is a minority of the roof",
      biggest["sloped_area_m2"] / R["sloped_area_m2"] < 0.25,
      f"{biggest['sloped_area_m2'] / R['sloped_area_m2'] * 100:.0f}%")
check("3c so the reported pitch is NOT the biggest plane's",
      R["predominant_pitch_deg"] != biggest["pitch_deg"],
      f"both {R['predominant_pitch_deg']}")

# The independent check: gradients taken straight off the Solar DSM for this
# building give a median of 33.8 degrees. The reported pitch has to land near
# that, not near the 57.8 the old code produced.
DSM_MEDIAN = 33.8
check("3d the reported pitch matches the height model within a degree",
      abs(R["predominant_pitch_deg"] - DSM_MEDIAN) <= 1.0,
      f"{R['predominant_pitch_deg']} vs DSM {DSM_MEDIAN}")
check("3e the old behaviour would have been over 20 degrees out",
      abs(biggest["pitch_deg"] - DSM_MEDIAN) > 20)
check("3f the area-weighted mean is also reported, and sits above the median "
      "because the outliers are the steep ones",
      R["mean_pitch_deg"] > R["predominant_pitch_deg"],
      f"mean {R['mean_pitch_deg']} median {R['predominant_pitch_deg']}")


# ---- 4. a complex roof says it is complex ----------------------------------

check("4a the pitch spread is reported", R["pitch_spread_deg"] > 30,
      str(R["pitch_spread_deg"]))
check("4b and the roof is flagged complex", R["complex"] is True)

simple = {
    "imageryQuality": "HIGH", "imageryDate": {"year": 2024, "month": 1, "day": 1},
    "solarPotential": {
        "buildingStats": {"areaMeters2": 122.0, "groundAreaMeters2": 100.0},
        "wholeRoofStats": {"areaMeters2": 122.0, "groundAreaMeters2": 100.0},
        "roofSegmentStats": [
            {"pitchDegrees": 35.0, "azimuthDegrees": 90.0,
             "stats": {"areaMeters2": 61.0}},
            {"pitchDegrees": 35.0, "azimuthDegrees": 270.0,
             "stats": {"areaMeters2": 61.0}},
        ]}}
Q = S.parse_segments(simple)
check("4c a plain duopitch is not flagged complex", Q["complex"] is False)
check("4d and its pitch is simply the pitch", Q["predominant_pitch_deg"] == 35.0)
check("4e with zero spread", Q["pitch_spread_deg"] == 0.0)


# ---- 5. compare() ----------------------------------------------------------

MINE = {"predominant_pitch_deg": 34.0, "plan_area_m2": 229.9,
        "sloped_area_m2": 303.48}
C = S.compare(MINE, R)

check("5a pitch is compared against the weighted figure",
      abs(C["pitch_deg"]["delta"]) < 1.0, str(C["pitch_deg"]))
check("5b plan area is compared against the FOOTPRINT, not the surface",
      C["plan_area_m2"]["solar"] == R["footprint_m2"],
      str(C["plan_area_m2"]))
check("5c sloped area uses Solar's MEASURED WHOLE roof, not one derived "
      "from a pitch and not the segmented subset",
      C["sloped_area_m2"]["solar_measured"] == 308.01,
      str(C["sloped_area_m2"]))
check("5c-2 the segmented subset is reported alongside, and is smaller",
      C["sloped_area_m2"]["solar_segmented"] == 277.81
      < C["sloped_area_m2"]["solar_measured"])
# The model was built from figured dimensions off a drawing and has never
# seen this imagery. Landing within 2% of an independent aerial measurement
# is the only end-to-end check Model Mode's roof has ever had.
check("5c-3 the modelled roof lands within 2% of the measured one",
      abs(C["sloped_area_m2"]["delta_pct"]) < 2.0,
      str(C["sloped_area_m2"]["delta_pct"]))
check("5d and says so in the basis",
      "measured" in C["sloped_area_m2"]["basis"])
check("5e the complexity warning reaches the notes",
      any("not one roof at one angle" in n for n in C["notes"]), str(C["notes"]))
check("5f a 0.2 degree pitch agreement raises no alarm",
      not any("disagree by" in n and "degrees" in n for n in C["notes"]),
      str(C["notes"]))

# THE REGRESSION THAT MATTERS. Reproduce exactly what the old code did and
# assert the new answer is nowhere near it.
old_pitch, old_area = 57.8, 308.01
old_implied = old_area / math.cos(math.radians(old_pitch))
check("5g the old pair would have implied a roof twice the real one",
      old_implied > 2 * R["whole_roof_area_m2"],
      f"{old_implied:.0f} vs {R['whole_roof_area_m2']}")
check("5h and the new comparison is nowhere near that",
      abs(C["sloped_area_m2"]["delta_pct"]) < 10.0,
      str(C["sloped_area_m2"]["delta_pct"]))

far = S.compare({"predominant_pitch_deg": 20.0, "plan_area_m2": 229.9,
                 "sloped_area_m2": 560.0}, R)
check("5i a real pitch disagreement IS flagged",
      any("Pitch sources disagree" in n for n in far["notes"]), str(far["notes"]))
check("5j and a real area disagreement too",
      any("Sloped area sources disagree" in n for n in far["notes"]))


# ---- 6. failing safely -----------------------------------------------------
# Solar is an enhancement. A missing key, a metered-out account or a location
# outside coverage must never take down a job the free LIDAR path could have
# finished on its own.

check("6a no payload parses to None", S.parse_segments(None) is None)
check("6b an empty payload parses to None", S.parse_segments({}) is None)
check("6c a payload with no segments parses to None",
      S.parse_segments({"solarPotential": {"roofSegmentStats": []}}) is None)
check("6d compare with no solar result returns None",
      S.compare(MINE, None) is None)
check("6e a segment missing its pitch is skipped, not guessed",
      S.parse_segments({"solarPotential": {"roofSegmentStats": [
          {"azimuthDegrees": 90.0, "stats": {"areaMeters2": 10.0}}]}}) is None)

flat_only = S.parse_segments({"solarPotential": {"roofSegmentStats": [
    {"pitchDegrees": 1.0, "azimuthDegrees": 0.0,
     "stats": {"areaMeters2": 200.0}}]}})
check("6f a genuinely flat roof reports no pitch rather than a fake one",
      flat_only["predominant_pitch_deg"] is None
      and flat_only["planes"][0]["flat"] is True)
check("6g and compare copes with that",
      S.compare(MINE, flat_only) is not None)

# A DEGENERATE SEGMENT MUST NOT TAKE THE JOB DOWN. Weighting the pitch by
# area divides by the total, so a response whose only pitched plane has zero
# area was a ZeroDivisionError on the whole roof job — for a plane that
# contributes nothing either way.
zero = S.parse_segments({"solarPotential": {"roofSegmentStats": [
    {"pitchDegrees": 40.0, "azimuthDegrees": 0.0,
     "stats": {"areaMeters2": 0.0}}]}})
check("6f-2 a zero-area segment does not crash the parse", zero is not None)
check("6f-3 and reports no pitch rather than a fabricated one",
      zero["predominant_pitch_deg"] is None
      and zero["mean_pitch_deg"] is None)
mixed = S.parse_segments({"solarPotential": {"roofSegmentStats": [
    {"pitchDegrees": 40.0, "azimuthDegrees": 0.0,
     "stats": {"areaMeters2": 0.0}},
    {"pitchDegrees": 30.0, "azimuthDegrees": 180.0,
     "stats": {"areaMeters2": 50.0}}]}})
check("6f-4 a zero-area segment alongside a real one is simply ignored",
      mixed["predominant_pitch_deg"] == 30.0,
      str(mixed["predominant_pitch_deg"]))
check("6f-5 and compare copes",
      S.compare(MINE, zero) is not None)

# A PARTIAL imageryDate MUST NOT TAKE THE JOB DOWN. {"year": 2023} with
# month/day absent (or null) used to hit f"{None:02d}" and raise TypeError
# out of parse_segments — which roof.run calls after the free LIDAR path
# has already produced quantities. A partial date is no date.
_seg = [{"pitchDegrees": 35.0, "azimuthDegrees": 90.0,
         "stats": {"areaMeters2": 61.0}}]
_yr_only = S.parse_segments({"imageryDate": {"year": 2023},
                             "solarPotential": {"roofSegmentStats": _seg}})
check("6f-6 a year-only imageryDate parses without raising",
      _yr_only is not None)
check("6f-7 and reports no date rather than a fabricated one",
      _yr_only["imagery_date"] is None, str(_yr_only["imagery_date"]))
_null_day = S.parse_segments({"imageryDate": {"year": 2023, "month": 7,
                                              "day": None},
                              "solarPotential":
                              {"roofSegmentStats": _seg}})
check("6f-8 a null day likewise",
      _null_day["imagery_date"] is None, str(_null_day["imagery_date"]))
# The complete date still formats — hand-checked against the section 4
# fixture: {"year": 2024, "month": 1, "day": 1} -> "2024-01-01".
check("6f-9 a complete date still formats zero-padded",
      Q["imagery_date"] == "2024-01-01", str(Q["imagery_date"]))

check("6h the key is read from the environment, never hard-coded",
      "AIza" not in open(os.path.join(HERE, "solar.py")).read())
check("6i and the module names the env var it wants",
      "GOOGLE_SOLAR_API_KEY" in open(os.path.join(HERE, "solar.py")).read())

_saved = os.environ.pop("GOOGLE_SOLAR_API_KEY", None)
try:
    check("6j with no key configured, available() is False", not S.available())
    check("6k and fetching returns None without a request",
          S.fetch_building_insights(52.5, -1.9) is None)
finally:
    if _saved is not None:
        os.environ["GOOGLE_SOLAR_API_KEY"] = _saved

check("6l solar mode does not touch the vehicle worker",
      "trellis" not in open(os.path.join(HERE, "solar.py")).read().lower())


# ==========================================================================
print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
