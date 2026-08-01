"""Tests for access, scaffolding and health & safety.

The two behaviours that matter most are the ones site conversation gets
wrong: that there is no two-metre exemption in British law, and that a
scaffold outside the TG20 envelope needs a design rather than just erecting.

Run: python building/test_safety.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import safety as S  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(
        name if cond else f"{name}{' — ' + detail if detail else ''}")


def find(findings, code):
    return next((f for f in findings if f.code == code), None)


# ---- 1. scaffold sizing from measured geometry ----------------------------
est = S.scaffold_estimate(eaves_height_m=5.4, perimeter_m=45.1)
check("1a estimate produced", est is not None)
check("1b platform sits below the eaves",
      est["platform_height_m"] < 5.4, str(est["platform_height_m"]))
check("1c guardrails stand above the platform",
      est["scaffold_height_m"] > est["platform_height_m"])
check("1d lifts derived from height", est["lifts"] == 3, str(est["lifts"]))
check("1e bays derived from run", est["bays"] == 19, str(est["bays"]))
check("1f deck area calculated", est["deck_area_m2"] > 0)
check("1g inspection interval carried", est["inspection_interval_days"] == 7)
check("1h missing dimensions give nothing",
      S.scaffold_estimate(None, 45.1) is None)

taller = S.scaffold_estimate(8.0, 45.1)
check("1i a taller building needs more lifts",
      taller["lifts"] > est["lifts"])
longer = S.scaffold_estimate(5.4, 90.0)
check("1j a longer run needs more bays", longer["bays"] > est["bays"])


# ---- 2. TG20 envelope — a design, or not ----------------------------------
# "Compliant" is a configuration, not a vibe. Outside the eGuide's envelope
# a scaffold needs a bespoke design from a temporary works engineer.
domestic = S.check_scaffold(S.scaffold_estimate(5.4, 45.1))
tg = find(domestic, "tg20_scope")
check("2a a domestic scaffold sits inside TG20", tg.verdict == S.PASS,
      tg.message)
check("2b it says a compliance sheet should be obtainable",
      "compliance sheet" in tg.message)

tall = S.check_scaffold(S.scaffold_estimate(30.0, 60.0))
tg = find(tall, "tg20_scope")
check("2c a tall scaffold falls outside TG20", tg.verdict == S.REQUIRED,
      tg.message)
check("2d it is flagged critical", tg.severity == S.CRITICAL)
check("2e it names who designs it", "temporary works engineer" in tg.message)
check("2f it says to price the design in", "Price the design in" in tg.message)

# Sheeting is the quiet one — it can double wind load on a scaffold that
# was adequate bare, and it lowers the TG20 height limit.
bare = S.scaffold_estimate(20.0, 40.0, sheeted=False)
sheet = S.scaffold_estimate(20.0, 40.0, sheeted=True)
check("2g sheeting lowers the TG20 height limit",
      sheet["tg20_height_limit_m"] < bare["tg20_height_limit_m"])
check("2h the same scaffold sheeted leaves the envelope",
      bare["within_tg20"] and not sheet["within_tg20"],
      f"bare={bare['within_tg20']} sheeted={sheet['within_tg20']}")
w = find(S.check_scaffold(sheet), "sheeting_wind_load")
check("2i sheeting raises a wind-load finding", w is not None)
check("2j it warns against sheeting an existing scaffold",
      "never sheet an existing scaffold" in w.message.lower(), w.message)
check("2k a bare scaffold raises no sheeting finding",
      find(S.check_scaffold(bare), "sheeting_wind_load") is None)


# ---- 3. guardrails and toe boards, with uncertainty ------------------------
f = find(S.check_scaffold(est, guardrail_height_m=1.000), "guardrail_height")
check("3a a compliant guardrail passes", f.verdict == S.PASS, f.message)
f = find(S.check_scaffold(est, guardrail_height_m=0.800), "guardrail_height")
check("3b a low guardrail fails", f.verdict == S.FAIL, f.message)
check("3c a failed guardrail is critical", f.severity == S.CRITICAL)
# 945mm against a 950mm requirement, measured to ±20mm, has not been shown
# to breach anything.
f = find(S.check_scaffold(est, guardrail_height_m=0.945), "guardrail_height")
check("3d a borderline guardrail is borderline", f.verdict == S.BORDERLINE,
      f.message)
check("3e borderline says to check with a tape", "tape" in f.message)

f = find(S.check_scaffold(est, toeboard_height_m=0.100), "toeboard_height")
check("3f a short toe board fails", f.verdict == S.FAIL, f.message)
f = find(S.check_scaffold(est), "guardrail_height")
check("3g unmeasured is not a pass", f.verdict == S.UNKNOWN, f.message)
check("3h it still says to verify on site", "verify" in f.message.lower())
# An unbuilt scaffold's guardrail is obviously unmeasured. Reporting that as
# CRITICAL put "not measured" alongside a genuine steep-roof hazard at the
# top of every assessment, which teaches a builder to skim the critical list.
check("3h-2 unmeasured carries no severity", f.severity is None,
      str(f.severity))

f = find(S.check_scaffold(est), "inspection")
check("3i inspection regime is stated", f.verdict == S.REQUIRED)
check("3j it covers alteration and weather",
      "alteration" in f.message and "weather" in f.message)

f = find(S.check_scaffold(None), "scaffold_unknown")
check("3k unmeasured building cannot be sized", f.verdict == S.UNKNOWN)


# ---- 4. THE two-metre myth ------------------------------------------------
# There is no 2m exemption in British law. Anything implying one would be
# worse than useless — people die falling from under two metres.
low = S.check_work_at_height(1.5)
f = find(low, "wah_threshold")
check("4a duties apply below two metres", f.verdict == S.REQUIRED, f.message)
check("4b it is flagged critical", f.severity == S.CRITICAL)
check("4c it names the myth", "two metre rule" in f.message.lower(),
      f.message)
check("4d it states the real test",
      "ANY height" in f.message, f.message)
check("4e it gives the hierarchy",
      "Avoid working at height" in f.message and "prevent falls" in f.message)
check("4f the duty is height-independent",
      find(S.check_work_at_height(12.0), "wah_threshold").verdict == S.REQUIRED)


# ---- 5. roof access scales with pitch --------------------------------------
steep = find(S.check_work_at_height(5.4, 35.0), "roof_access")
check("5a a steep roof needs a roof ladder",
      "ladder" in steep.message or "crawling" in steep.message, steep.message)
check("5b steep roof access is critical", steep.severity == S.CRITICAL)

sloping = find(S.check_work_at_height(5.4, 20.0), "roof_access")
check("5c a sloping roof needs crawling boards",
      "Crawling boards" in sloping.message, sloping.message)
check("5d it is major rather than critical", sloping.severity == S.MAJOR)

flat = find(S.check_work_at_height(5.4, 2.0), "roof_access")
check("5e a flat roof needs edge protection",
      "Edge protection" in flat.message, flat.message)
check("5f rooflights are called out as fragile",
      "fragile" in flat.message, flat.message)

frag = find(S.check_work_at_height(5.4, 30.0, fragile_surfaces=True),
            "fragile_surface")
check("5g fragile surfaces raise a finding", frag is not None)
check("5h it is critical", frag.severity == S.CRITICAL)
check("5i it says assume fragile until proven otherwise",
      "until proven otherwise" in frag.message)
check("5j no fragile flag, no finding",
      find(S.check_work_at_height(5.4, 30.0), "fragile_surface") is None)


# ---- 6. CDM 2015 -----------------------------------------------------------
big = find(S.check_cdm(duration_days=60, max_workers=25), "cdm_notify")
check("6a a large project is notifiable", big.verdict == S.REQUIRED,
      big.message)
check("6b it names the form", "F10" in big.message)

# Long but small is NOT notifiable — BOTH limbs must be exceeded.
long_small = find(S.check_cdm(duration_days=60, max_workers=4), "cdm_notify")
check("6c long but small is not notifiable", long_small.verdict == S.PASS,
      long_small.message)
check("6d it says other duties still apply",
      "not what triggers them" in long_small.message)

# The person-days limb stands alone.
pd = find(S.check_cdm(person_days=600), "cdm_notify")
check("6e person-days alone can trigger it", pd.verdict == S.REQUIRED)

unknown = find(S.check_cdm(), "cdm_notify")
check("6f no programme means it cannot be assessed",
      unknown.verdict == S.UNKNOWN)
check("6g it states the thresholds anyway",
      "30" in unknown.message and "500" in unknown.message)

multi = find(S.check_cdm(contractor_count=3), "cdm_roles")
check("6h more than one contractor needs PD and PC",
      multi.verdict == S.REQUIRED and "Principal Designer" in multi.message)
single = find(S.check_cdm(contractor_count=1), "cdm_roles")
check("6i a plan is required on every project",
      "however small" in single.message, single.message)

dom = find(S.check_cdm(domestic_client=True), "cdm_domestic")
check("6j domestic client duties transfer", dom is not None)
check("6k it says who carries them", "you do" in dom.message.lower())
check("6l no finding for a commercial client",
      find(S.check_cdm(domestic_client=False), "cdm_domestic") is None)


# ---- 7. full assessment from a measured roof ------------------------------
roof = {"quantities": {"predominant_pitch_deg": 32, "eaves_m": 45.09,
                       "sloped_area_m2": 138.82}}
a = S.assess(roof=roof, eaves_height_m=5.4, domestic_client=True)
check("7a scaffold sized from the roof", a["scaffold"]["bays"] > 0)
check("7b perimeter taken from the eaves run",
      abs(a["scaffold"]["run_m"] - 45.09) < 0.2, str(a["scaffold"]["run_m"]))
check("7c pitch drives roof access",
      any(f["code"] == "roof_access" for f in a["findings"]))
check("7d findings are triaged by severity",
      len(a["critical"]) >= 1 and len(a["major"]) >= 1)
check("7e every finding cites a source",
      all(f["citation"] for f in a["findings"]))
check("7f the disclaimer names what it cannot see",
      "overhead lines" in a["disclaimer"] and "asbestos" in a["disclaimer"])
check("7g it defers to a competent person",
      "competent person" in a["disclaimer"])
check("7h unmeasured items are a site to-do, not failures",
      any(f["code"] == "guardrail_height" for f in a["to_verify_on_site"]),
      str([f["code"] for f in a["to_verify_on_site"]]))
check("7i they are kept out of the critical list",
      not any(f["code"] == "guardrail_height" for f in a["critical"]),
      str([f["code"] for f in a["critical"]]))
check("7j the critical list holds only real hazards",
      all(f["verdict"] != S.UNKNOWN for f in a["critical"]))


# ==========================================================================
print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
