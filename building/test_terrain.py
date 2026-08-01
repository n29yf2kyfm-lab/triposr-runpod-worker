"""Tests for site levels, earthworks, drainage and foundations.

Run: python building/test_terrain.py
"""
import os
import sys
import math

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import terrain as T  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(
        name if cond else f"{name}{' — ' + detail if detail else ''}")


def find(findings, code):
    return next((f for f in findings if f.code == code), None)


def terrain(fn, w=20, d=20, e0=0.0, n0=0.0):
    """Terrain grid. e0/n0 shift it to National Grid magnitudes."""
    return [(e0 + x, n0 + y, fn(x, y))
            for x in range(w) for y in range(d)]


LEVEL = terrain(lambda x, y: 50.0)
GENTLE = terrain(lambda x, y: 50.0 + y * 0.02)     # 1:50
GENTLE_SHED = terrain(lambda x, y: 50.0 + y * 0.04)  # 1:25 — sheds water
MODERATE = terrain(lambda x, y: 50.0 + y * 0.07)   # ~1:14
STEEP = terrain(lambda x, y: 50.0 + y * 0.12)      # ~1:8
SEVERE = terrain(lambda x, y: 50.0 + y * 0.30)     # ~1:3


# ---- 1. plane fitting survives National Grid magnitudes -------------------
# Same trap the roof fitter fell into: at E=413000 the normal equations lose
# precision and the fit collapses to horizontal, reporting every sloping
# site as flat.
near = T.fit_ground_plane(GENTLE)
far = T.fit_ground_plane(terrain(lambda x, y: 50.0 + y * 0.02,
                                 e0=413218.0, n0=289299.0))
check("1a fits a plane", near is not None)
check("1b gradient recovered", abs(near[1] - 0.02) < 1e-9, str(near[1]))
check("1c National Grid coordinates give the same gradient",
      abs(far[1] - near[1]) < 1e-9, f"{far[1]} vs {near[1]}")
check("1d too few points gives nothing", T.fit_ground_plane([(0, 0, 0)]) is None)


# ---- 2. levels ------------------------------------------------------------
lv = T.levels(LEVEL)
check("2a a level site reads as level", lv["gradient"] < 1e-6, str(lv))
check("2b level site has no fall direction", lv["fall_bearing_deg"] is None)
check("2c gradient ratio says level", lv["gradient_ratio"] == "level")

lv = T.levels(GENTLE_SHED)
check("2d gradient measured", abs(lv["gradient"] - 0.04) < 1e-6, str(lv))
check("2e expressed as a ratio", lv["gradient_ratio"] == "1:25",
      lv["gradient_ratio"])
check("2f total fall measured", abs(lv["total_fall_m"] - 0.76) < 0.01,
      str(lv["total_fall_m"]))
# Ground rising to the north means water runs SOUTH.
check("2g fall direction points downhill",
      abs(lv["fall_bearing_deg"] - 180.0) < 0.01,
      str(lv["fall_bearing_deg"]))
check("2h no terrain gives nothing", T.levels([]) is None)


# ---- 3. cut and fill ------------------------------------------------------
# Muck away and imported fill cart differently and are priced separately, so
# they must not be netted off — a balanced site still pays for both.
cf = T.cut_and_fill(MODERATE, T.balance_level(MODERATE))
check("3a cut computed", cf["cut_m3"] > 0)
check("3b fill computed", cf["fill_m3"] > 0)
check("3c reported separately, not netted",
      cf["cut_m3"] != cf["net_m3"], str(cf))
check("3d balance level balances", cf["balanced"], str(cf))
# Excavated ground bulks — the grab lorry carts the bulked volume.
check("3e cut is bulked for carting",
      abs(cf["cut_bulked_m3"] - cf["cut_m3"] * 1.25) < 0.2)
check("3f bulked exceeds in-situ", cf["cut_bulked_m3"] > cf["cut_m3"])

low = T.cut_and_fill(MODERATE, 49.0)   # platform below all ground
check("3g a low platform is all cut", low["fill_m3"] == 0 and low["cut_m3"] > 0)
high = T.cut_and_fill(MODERATE, 52.0)  # platform above all ground
check("3h a high platform is all fill", high["cut_m3"] == 0 and high["fill_m3"] > 0)
check("3i not balanced when one-sided", not high["balanced"])
check("3j level site needs no earthworks",
      T.cut_and_fill(LEVEL, 50.0)["cut_m3"] == 0)


# ---- 4. slope findings scale with gradient --------------------------------
# A dead-flat site is the one that causes ponding complaints, so it is
# flagged rather than passed.
f = find(T.check_site(T.levels(LEVEL)), "slope")
check("4a a dead-level site is flagged", f.verdict == T.ATTENTION, f.message)
check("4b it warns falls must be built in",
      "built into paving" in f.message, f.message)
check("4b-2 it names the consequence", "ponding" in f.message)
# But 1:25 DOES shed water — calling that "near level" and telling a builder
# to build in falls they already have is noise that trains them to ignore it.
f = find(T.check_site(T.levels(GENTLE_SHED)), "slope")
check("4b-3 a gentle slope passes", f.verdict == T.PASS, f.message)
check("4b-4 it says water sheds naturally",
      "shed surface water naturally" in f.message, f.message)

f = find(T.check_site(T.levels(MODERATE)), "slope")
check("4c moderate slope is advisory", f.severity == T.ADVISORY, f.message)
check("4d no retaining implied", "no retaining work" in f.message)

f = find(T.check_site(T.levels(STEEP)), "slope")
check("4e steep slope is major", f.severity == T.MAJOR, f.message)
check("4f retaining flagged", "retaining" in f.message)

f = find(T.check_site(T.levels(SEVERE)), "slope")
check("4g severe slope is critical", f.severity == T.CRITICAL, f.message)
check("4h stepped foundations flagged", "stepped foundations" in f.message)
check("4i it warns a flat-site rate will not cover it",
      "flat-site rate" in f.message, f.message)

f = find(T.check_site(T.levels(MODERATE)), "drainage_direction")
check("4j fall direction named in words", "south" in f.message, f.message)
check("4k no terrain cannot be assessed",
      find(T.check_site(None), "levels_unknown").verdict == T.UNKNOWN)


# ---- 5. foul drainage fall ------------------------------------------------
lv = T.levels(MODERATE)
# Connection far below: plenty of fall.
f = find(T.check_site(lv, drainage_target_m=lv["lowest_m"] - 2.0), "foul_fall")
check("5a ample fall passes", f.verdict == T.PASS, f.message)

# Connection barely below: tight but workable.
f = find(T.check_site(lv, drainage_target_m=lv["lowest_m"] - 0.40), "foul_fall")
check("5b tight fall is flagged major", f.severity == T.MAJOR, f.message)
check("5c it cites both 1:80 and 1:40", "1:80" in f.message and "1:40" in f.message)

# Connection level with the site: a pump job.
f = find(T.check_site(lv, drainage_target_m=lv["lowest_m"]), "foul_fall")
check("5d no fall is critical", f.severity == T.CRITICAL, f.message)
check("5e a pumped station is named", "pumped station" in f.message)
check("5f it says price it before the dig", "not after the dig" in f.message)


# ---- 6. foundations near trees --------------------------------------------
# Clay shrinks as roots draw water; the damage shows years later. Depth is
# driven by MATURE height, not the height today — the mistake made when a
# sapling stands beside a new extension.
far_tree = T.foundation_depth(30.0, 20.0, "moderate", clay=True)
check("6a a distant tree gives the clay minimum",
      far_tree["depth_m"] == T.CLAY_MIN_DEPTH_M, str(far_tree))
close = T.foundation_depth(5.0, 20.0, "moderate", clay=True)
check("6b a close tree deepens the foundation",
      close["depth_m"] > far_tree["depth_m"], str(close))
check("6c depth is capped at something buildable", close["depth_m"] <= 3.0)

thirsty = T.foundation_depth(10.0, 20.0, "high", clay=True)
modest = T.foundation_depth(10.0, 20.0, "low", clay=True)
check("6d a high water-demand species needs more depth",
      thirsty["depth_m"] > modest["depth_m"],
      f"{thirsty['depth_m']} vs {modest['depth_m']}")

check("6e no clay means the normal minimum",
      T.foundation_depth(5.0, 20.0, clay=False)["depth_m"]
      == T.MIN_FOUNDATION_DEPTH_M)
check("6f no tree data still applies the clay minimum",
      T.foundation_depth(None, None, clay=True)["depth_m"]
      == T.CLAY_MIN_DEPTH_M)
check("6g it is labelled a planning figure",
      "PLANNING figure" in close["note"])
check("6h trial holes are named as what decides",
      "trial holes" in close["note"])
check("6i heave on removal is flagged",
      "heave" in close["note"].lower(), close["note"])

# Heave is the counter-intuitive one: taking the tree out can be worse.
f = find(T.check_site(T.levels(LEVEL), clay=True), "clay_heave")
check("6j clay heave raised", f is not None)
check("6k it explains removal can be worse",
      "more damaging than" in f.message, f.message)
check("6l no clay, no heave finding",
      find(T.check_site(T.levels(LEVEL), clay=False), "clay_heave") is None)

f = find(T.check_site(T.levels(LEVEL), clay=True, trees=[
    {"species": "Oak", "distance_m": 6.0, "mature_height_m": 20.0,
     "water_demand": "high"}]), "foundation_depth")
check("6m a named tree produces a depth finding", f is not None)
check("6n the species is quoted", "Oak" in f.message, f.message)


# ---- 7. full assessment ---------------------------------------------------
a = T.assess(terrain_points=STEEP, drainage_target_m=48.0, clay=True,
             trees=[{"species": "Willow", "distance_m": 4.0,
                     "mature_height_m": 18.0, "water_demand": "high"}])
check("7a levels reported", a["levels"] is not None)
check("7b earthworks computed", a["earthworks"]["cut_m3"] > 0)
check("7c platform defaults to the balance level",
      a["earthworks"]["balanced"], str(a["earthworks"]))
check("7d findings triaged", len(a["major"]) >= 1)
check("7e every finding cites its basis",
      all(f["citation"] for f in a["findings"]))
check("7f disclaimer names what terrain cannot see",
      all(w in a["disclaimer"] for w in
          ("soil type", "water table", "buried services", "contamination")))
check("7g trial holes named as what decides", "Trial holes" in a["disclaimer"])
check("7h no terrain still returns an assessment",
      T.assess()["levels"] is None)


# ==========================================================================
print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
