"""Tests for the UK Building Regulations engine.

The behaviour that matters most is the BORDERLINE verdict. A rules engine
run against drawings never faces measurement error; run against a scan it
always does, and calling a borderline case a breach could send someone
ripping out a compliant staircase.

Run: python building/test_regs.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import regs as G  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(
        name if cond else f"{name}{' — ' + detail if detail else ''}")


# ---- 1. clear pass and clear fail -----------------------------------------
f = G.check("stair_rise", 0.190, 0.002)
check("1a comfortable rise passes", f.verdict == G.PASS, f.message)
check("1b a passing item has no severity", f.severity is None)

f = G.check("stair_rise", 0.260, 0.002)
check("1c a rise well over the limit fails", f.verdict == G.FAIL, f.message)
check("1d stairs are life safety", f.severity == G.CRITICAL)
check("1e the message quotes the measurement", "0.260m" in f.message, f.message)
check("1f the message quotes the limit", "0.220m" in f.message, f.message)

f = G.check("stair_headroom", 1.700, 0.010)
check("1g headroom below minimum fails", f.verdict == G.FAIL, f.message)


# ---- 2. BORDERLINE — the point of the module ------------------------------
# 221mm against a 220mm limit, measured to ±5mm, has NOT been shown to
# breach anything. Reporting it as a failure is irresponsible.
f = G.check("stair_rise", 0.221, 0.005)
check("2a a rise within error of the limit is borderline",
      f.verdict == G.BORDERLINE, f.message)
check("2b borderline says to check on site", "tape on site" in f.message)
check("2c borderline is not reported at critical severity",
      f.severity == G.MAJOR, str(f.severity))

# The same measurement, known precisely, IS a breach.
f = G.check("stair_rise", 0.221, 0.0001)
check("2d the same value measured precisely fails",
      f.verdict == G.FAIL, f.message)

# Minimums straddle the same way.
f = G.check("guarding_balcony", 1.095, 0.010)
check("2e guarding just under the minimum is borderline",
      f.verdict == G.BORDERLINE, f.message)
f = G.check("guarding_balcony", 1.095, 0.001)
check("2f measured precisely it fails", f.verdict == G.FAIL)
f = G.check("guarding_balcony", 1.150, 0.010)
check("2g comfortably over passes", f.verdict == G.PASS)

# Zero uncertainty must behave exactly like the classical check.
check("2h zero uncertainty gives a clean pass",
      G.check("stair_rise", 0.200, 0).verdict == G.PASS)
check("2i zero uncertainty gives a clean fail",
      G.check("stair_rise", 0.230, 0).verdict == G.FAIL)


# ---- 3. missing data is not a pass ----------------------------------------
f = G.check("stair_rise", None)
check("3a unmeasured is insufficient_data", f.verdict == G.UNKNOWN)
check("3b it says it was not measured", "not measured" in f.message)
check("3c it still cites the rule", "Approved Document K" in f.message)

try:
    G.check("nonexistent_rule", 1.0)
    check("3d unknown rule refused", False)
except KeyError as e:
    check("3d unknown rule refused", "nonexistent_rule" in str(e))
    check("3e it lists known rules", "stair_rise" in str(e))


# ---- 4. every rule cites a document and clause ----------------------------
for code, rule in G.RULES.items():
    check(f"4 {code} cites a document",
          rule.part and rule.clause and rule.title,
          f"{rule.part} {rule.clause}")
check("4z citation reads properly",
      G.RULES["stair_rise"].cite() == "Approved Document K, 1.2",
      G.RULES["stair_rise"].cite())


# ---- 5. stairs are judged as a whole --------------------------------------
# A flight can satisfy every individual limit and still be wrong to climb.
good = G.check_stair(0.190, 0.250, 0.003)
check("5a a sound stair passes throughout",
      all(f.verdict == G.PASS for f in good),
      str([(f.rule.code, f.verdict) for f in good]))
check("5b pitch is derived, not asked for",
      any(f.rule.code == "stair_pitch" for f in good))

steep = G.check_stair(0.230, 0.200, 0.003)
check("5c a steep stair fails on more than one count",
      sum(1 for f in steep if f.verdict == G.FAIL) >= 2,
      str([(f.rule.code, f.verdict) for f in steep]))

# 2R+G: rise 150 going 220 gives 520mm — under the 550 minimum, even though
# each dimension passes on its own.
formula = G.check_stair(0.150, 0.220, 0.002)
check("5d the 2R+G relationship is checked",
      any("2x rise + going" in f.message for f in formula),
      str([f.message[:50] for f in formula]))
check("5e it explains why that matters",
      any("feel wrong to climb" in f.message for f in formula))


# ---- 6. escape windows need all three, not any one ------------------------
# A wide, shallow window can have ample area and still be impossible to
# climb through — the combination is what gets missed.
ok = G.check_escape_window(0.700, 0.700, 0.900, 0.02)
check("6a a sound escape window passes throughout",
      all(f.verdict == G.PASS for f in ok),
      str([(f.rule.code, f.verdict) for f in ok]))

shallow = G.check_escape_window(1.500, 0.300, 0.900, 0.02)
area = [f for f in shallow if f.rule.code == "escape_window_area"][0]
least = [f for f in shallow if f.rule.code == "escape_window_dim"][0]
check("6b ample area can still pass", area.verdict == G.PASS,
      area.message)
check("6c but the least dimension fails", least.verdict == G.FAIL,
      least.message)
check("6d escape is life safety", least.severity == G.CRITICAL)

high = G.check_escape_window(0.700, 0.700, 1.400, 0.02)
cill = [f for f in high if f.rule.code == "escape_window_cill"][0]
check("6e an unreachable cill fails", cill.verdict == G.FAIL, cill.message)


# ---- 7. ventilation is a ratio, not an area -------------------------------
v = G.check_purge_ventilation(1.2, 20.0)
check("7a 1/20 of floor area passes", v[0].verdict == G.PASS, v[0].message)
v = G.check_purge_ventilation(0.5, 20.0)
check("7b too little openable area fails", v[0].verdict == G.FAIL)
v = G.check_purge_ventilation(1.0, 20.0, uncertainty_ratio=0.005)
check("7c exactly on the limit is borderline", v[0].verdict == G.BORDERLINE,
      v[0].message)
v = G.check_purge_ventilation(1.0, None)
check("7d no floor area means it cannot be checked",
      v[0].verdict == G.UNKNOWN)


# ---- 8. triage ------------------------------------------------------------
findings = [
    G.check("stair_rise", 0.260, 0.002),        # critical fail
    G.check("socket_height", 0.300, 0.010),     # major fail
    G.check("ceiling_height", 2.250, 0.010),    # advisory
    G.check("guarding_floor", 1.150, 0.010),    # pass
    G.check("stair_going", None),               # unknown
]
s = G.summarise(findings)
check("8a counts are tallied",
      s["counts"]["fail"] == 3 and s["counts"]["pass"] == 1,
      str(s["counts"]))
check("8b life-safety items are separated", len(s["critical"]) == 1)
check("8c major items are separated", len(s["major"]) == 1)
check("8d advisory items are separated", len(s["advisory"]) == 1)
check("8e unknowns are excluded from the checked count", s["checked"] == 4)
# An unmeasured rule is a gap in the survey, not a finding against the
# building — filing it under life-safety failures would bury real breaches.
check("8e-2 unknowns carry no severity",
      G.check("stair_rise", None).severity is None)
check("8e-3 unknowns are reported as survey gaps",
      len(s["not_checked"]) == 1 and
      s["not_checked"][0]["code"] == "stair_going",
      str(s["not_checked"]))
check("8f headline reports the failures", "3 item(s)" in s["headline"],
      s["headline"])

clean = G.summarise([G.check("guarding_floor", 1.150, 0.010)])
check("8g a clean run says so", "within the guidance" in clean["headline"],
      clean["headline"])

edge = G.summarise([G.check("stair_rise", 0.221, 0.005)])
check("8h a borderline-only run does not claim failure",
      "within measurement error" in edge["headline"], edge["headline"])


# ---- 9. the disclaimer is not optional ------------------------------------
# Approved Documents are guidance; building control decides. Saying so is
# what keeps this a competent first pass rather than a determination.
d = G.summarise([])["disclaimer"]
check("9a states it is guidance", "guidance, not the regulation" in d)
check("9b covers existing work", "when it was built" in d)
check("9c covers listed buildings", "historic or listed" in d)
check("9d defers to building control", "Building control decides" in d)


# ---- 10. limits that come from the document, not from habit ----------------
# Each of these was once a stricter figure than the Approved Document asks
# for, and a limit the document does not contain fails compliant work as a
# definite breach — the ripping-out-a-compliant-staircase outcome, only
# self-inflicted.

# AD K Diagram 3.1: 900mm inside a single dwelling, 1100mm only once you
# step outside onto a balcony. A 950mm internal landing guarding complies.
f = G.check("guarding_floor", 0.950, 0.010)
check("10a a 950mm internal landing guarding passes", f.verdict == G.PASS,
      f.message)
f = G.check("guarding_floor", 0.850, 0.010)
check("10b but 850mm is below even the internal minimum",
      f.verdict == G.FAIL)
check("10c and it is life safety", f.severity == G.CRITICAL)
f = G.check("guarding_balcony", 0.950, 0.010)
check("10d the same 950mm on an external balcony fails",
      f.verdict == G.FAIL, f.message)
check("10e both guarding rules cite Diagram 3.1",
      G.RULES["guarding_floor"].clause == "Diagram 3.1"
      and G.RULES["guarding_balcony"].clause == "Diagram 3.1")

# AD B puts NO minimum on an escape cill — only the 1100mm maximum above
# which the window cannot be climbed out of. A 600mm cill complies.
check("10f the cill rule carries no invented minimum",
      G.RULES["escape_window_cill"].minimum is None,
      str(G.RULES["escape_window_cill"].minimum))
low = G.check_escape_window(0.900, 0.900, 0.600, 0.02)
check("10g a compliant window with a 600mm cill passes throughout",
      all(f.verdict == G.PASS for f in low),
      str([(f.rule.code, f.verdict) for f in low]))
check("10h escape windows cite para 2.10, where the doc puts them",
      G.RULES["escape_window_cill"].cite() == "Approved Document B1, 2.10",
      G.RULES["escape_window_cill"].cite())

# AD M: switches, sockets and controls share ONE 450-1200mm band.
f = G.check("switch_height", 0.600, 0.010)
check("10i a switch at 600mm is inside the Part M band",
      f.verdict == G.PASS, f.message)
f = G.check("switch_height", 0.400, 0.005)
check("10j and 400mm is below it", f.verdict == G.FAIL, f.message)


# ==========================================================================
print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
