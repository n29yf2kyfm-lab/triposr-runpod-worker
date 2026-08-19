"""Tests for metric scale — the safety-critical number.

A wrong scale multiplies through every dimension, every quantity and every
price in the product, and it looks entirely plausible while doing it. These
tests are mostly about REFUSING rather than computing.

Run: python building/test_scale.py
"""
import os
import sys
import math

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import scale as S  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(
        name if cond else f"{name}{' — ' + detail if detail else ''}")


def obs(kind, units, repeats=1):
    return S.Observation(kind, units, repeats)


# A model whose units happen to be centimetres: true scale 0.01 m/unit.
TRUE = 0.01
BRICK20 = obs("brick_course", 0.075 * 20 / TRUE, 20)   # 20 courses
SOCKET = obs("socket_height", 0.450 / TRUE)
DOOR_W = obs("door_internal_w", 0.762 / TRUE)


# ---- 1. basic estimation --------------------------------------------------
r = S.estimate_scale([BRICK20, SOCKET])
check("1a recovers the true scale", abs(r["scale_m_per_unit"] - TRUE) < 1e-9,
      str(r["scale_m_per_unit"]))
check("1b reports source", r["source"] == "anchors")
check("1c names its references",
      set(r["references"]) == {"brick_course", "socket_height"})
check("1d counts repeats", r["total_repeats"] == 21)
check("1e gives a confidence word",
      r["confidence"] in ("high", "good", "fair", "low"), r["confidence"])

r3 = S.estimate_scale([BRICK20, SOCKET, DOOR_W])
check("1f three agreeing references still recover it",
      abs(r3["scale_m_per_unit"] - TRUE) < 1e-9)


# ---- 2. robustness: one bad detection must not win ------------------------
# THE bug this module was written around. Weight rises as stated tolerance
# falls, and a door leaf is specified more tightly than a brick joint — so
# weighting the OUTLIER-DETECTION median let one misidentified door outvote
# twenty courses of brickwork that agreed with each other, and the "robust"
# median landed on the single wrong reading. Detection is now unweighted.
BAD_DOOR = obs("door_internal_h", 1.981 / 0.0066)   # implies 0.0066 m/unit
r = S.estimate_scale([BRICK20, SOCKET, BAD_DOOR])
check("2a outlier rejected", "door_internal_h" in r["rejected"],
      str(r["rejected"]))
check("2b true scale survives the outlier",
      abs(r["scale_m_per_unit"] - TRUE) < 1e-6,
      str(r["scale_m_per_unit"]))
check("2c rejection is counted", r["observations_rejected"] == 1)

# A tight-tolerance reference must not dominate simply by being tight.
r = S.estimate_scale([BRICK20, SOCKET, DOOR_W,
                      obs("plasterboard_h", 2.400 / 0.0090)])
check("2d a single tight outlier cannot drag the answer",
      abs(r["scale_m_per_unit"] - TRUE) < 1e-6, str(r["scale_m_per_unit"]))

# The weight cap must hold against a tight reference that disagrees WITHIN
# its outlier allowance. The old cap — half the raw total — shrank the
# total as it clipped, so a door reading 1% high (doors are specified to
# 0.5%, so 1% survives the 2x allowance) still held two thirds of the
# final weight and the median sat exactly on the door, against a socket
# and a ceiling that agreed. Hand-worked: door weight ~198 clips to
# socket+ceiling = 18 + 4 = 22 of a 44 total; the cumulative weight
# reaches half inside the agreeing pair, so the answer is 0.0100.
HIGH_DOOR = obs("door_internal_h", 1.981 / 0.0101)     # reads 1% high
r = S.estimate_scale([HIGH_DOOR, SOCKET, obs("ceiling_height", 2.400 / TRUE)])
check("2e a within-allowance disagreement is kept, not rejected",
      r["observations_rejected"] == 0, str(r["rejected"]))
check("2f but a single tight reference cannot dictate the median",
      abs(r["scale_m_per_unit"] - TRUE) < 1e-9, str(r["scale_m_per_unit"]))


# ---- 3. refusals ----------------------------------------------------------
# Each of these MUST raise. A silently-wrong scale is the worst failure the
# product can have, because everything downstream looks confident.
try:
    S.estimate_scale([BRICK20])
    check("3a single reference refused", False)
except S.ScaleError as e:
    check("3a single reference refused", "at least 2" in str(e))
    check("3b refusal says how to fix it", "brickwork" in str(e), str(e))

try:
    S.estimate_scale([])
    check("3c empty refused", False)
except S.ScaleError:
    check("3c empty refused", True)

try:
    # 0.45/0.20 = 0.0225 vs 0.01 — a 125% disagreement.
    S.estimate_scale([BRICK20, obs("socket_height", 20.0)])
    check("3d wild disagreement refused", False)
except S.ScaleError as e:
    check("3d wild disagreement refused", "span" in str(e))
    check("3e refusal says re-capture", "Re-capture" in str(e), str(e))

# Three consistent misdetections outvote the two true references. The
# module cannot know which cluster is real — a majority of agreeing
# observations IS the evidence — so the majority wins. What it must not do
# is shrug: the answer must sit wholly on the winning cluster (an average
# across both clusters here would be ~0.016, a number NO reference
# supports), and the outvoted references must be visibly counted as
# rejected. This check used to pass True unconditionally on the success
# branch, so a silent blend would have sailed through.
try:
    r = S.estimate_scale([BRICK20, SOCKET,
                          obs("door_internal_h", 1.981 / 0.02),
                          obs("plasterboard_h", 2.400 / 0.02),
                          obs("switch_height", 1.200 / 0.02)])
    check("3f the majority cluster wins whole, never a blend",
          abs(r["scale_m_per_unit"] - 0.02) < 1e-9,
          str(r["scale_m_per_unit"]))
    check("3f2 the outvoted references are reported rejected",
          r["observations_rejected"] == 2
          and set(r["rejected"]) == {"brick_course", "socket_height"},
          str(r["rejected"]))
except S.ScaleError as e:
    check("3f majority-outlier refusal names the disagreement",
          "disagree" in str(e) or "span" in str(e), str(e))

try:
    S.Observation("banana", 1.0)
    check("3g unknown reference refused", False)
except S.ScaleError as e:
    check("3g unknown reference refused", "banana" in str(e))
    check("3h lists known references", "brick_course" in str(e))

for bad, label in [((0,), "zero"), ((-5,), "negative")]:
    try:
        S.Observation("brick_course", bad[0])
        check(f"3i {label} measurement refused", False)
    except S.ScaleError:
        check(f"3i {label} measurement refused", True)

try:
    S.Observation("brick_course", 10.0, repeats=0)
    check("3j zero repeats refused", False)
except S.ScaleError:
    check("3j zero repeats refused", True)


# ---- 4. brick coursing is the strong reference ----------------------------
# Four courses are exactly 300mm by national standard, and the run REPEATS —
# so error averages down instead of resting on one object.
one = obs("brick_course", 7.5)
twenty = obs("brick_course", 150.0, 20)
check("4a repeats reduce uncertainty",
      twenty.relative_tolerance < one.relative_tolerance)
check("4b reduction follows sqrt(n)",
      abs(twenty.relative_tolerance
          - one.relative_tolerance / math.sqrt(20)) < 1e-9)
check("4c 4 courses = 300mm exactly",
      abs(obs("brick_course", 1, 4).real_metres - 0.300) < 1e-12,
      str(obs("brick_course", 1, 4).real_metres))
check("4d 20 courses beats a single door on tolerance",
      twenty.relative_tolerance < obs("door_internal_w", 76.2).relative_tolerance)


# ---- 5. weak references cannot carry a scale alone ------------------------
weak = S.estimate_scale([obs("ceiling_height", 240.0),
                         obs("stair_rise", 20.0)])
check("5a weak-only estimate is low confidence",
      weak["confidence"] == "low", weak["confidence"])
strong = S.estimate_scale([BRICK20, SOCKET, DOOR_W])
check("5b strong references rate better than weak",
      strong["confidence"] != "low", strong["confidence"])
check("5c weak references carry less weight",
      obs("ceiling_height", 240.0).effective_weight
      < obs("door_internal_w", 76.2).effective_weight)


# ---- 6. uncertainty is never flattered ------------------------------------
# Reported uncertainty must not be tighter than the observations' own
# disagreement — otherwise a quote inherits false precision.
spread_obs = [obs("brick_course", 150.0, 20),
              obs("brick_course", 153.0, 20)]   # ~2% apart
r = S.estimate_scale(spread_obs)
check("6a uncertainty reflects real disagreement",
      r["uncertainty_pct"] >= r["spread_pct"] / 2 - 1e-9,
      f'unc {r["uncertainty_pct"]} vs spread {r["spread_pct"]}')
check("6b spread is reported", r["spread_pct"] > 0)


# ---- 7. LiDAR and manual paths -------------------------------------------
l = S.from_lidar()
check("7a lidar is unit scale", l["scale_m_per_unit"] == 1.0)
check("7b lidar is high confidence", l["confidence"] == "high")
check("7c lidar states its own error", l["uncertainty_pct"] == 1.0)
try:
    S.from_lidar(depth_available=False)
    check("7d missing depth refused", False)
except S.ScaleError:
    check("7d missing depth refused", True)

m = S.from_manual(3.6, 360.0)
check("7e manual scale computed", abs(m["scale_m_per_unit"] - 0.01) < 1e-12)
# Single-point: trusted, but it has no cross-check and must say so.
check("7f manual warns it is unchecked", "no independent check" in m["note"])
for bad in [(0, 10), (10, 0), (-1, 10)]:
    try:
        S.from_manual(*bad)
        check(f"7g manual rejects {bad}", False)
    except S.ScaleError:
        check(f"7g manual rejects {bad}", True)


# ---- 8. applying the scale ------------------------------------------------
pts = S.apply([(1, 2, 3), (10, 0, -5)], 0.01)
check("8a points scaled", pts[0] == (0.01, 0.02, 0.03), str(pts[0]))
check("8b negatives preserved", pts[1] == (0.10, 0.0, -0.05), str(pts[1]))
check("8c empty set is fine", S.apply([], 0.5) == [])


# ---- 9. descriptions are human --------------------------------------------
check("9a lidar description", "LiDAR" in S.describe(S.from_lidar()))
check("9b manual description mentions no cross-check",
      "no cross-check" in S.describe(S.from_manual(3.6, 360.0)))
d = S.describe(S.estimate_scale([BRICK20, SOCKET]))
check("9c anchor description names references", "brick_course" in d, d)
check("9d anchor description carries uncertainty", "±" in d, d)


# ==========================================================================
print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
