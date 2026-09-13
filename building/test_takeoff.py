"""Tests for Price Mode.

A wrong quote loses the user money on their own job, so these lean on the
same principle as the scale tests: refuse and flag rather than guess.

Run: python building/test_takeoff.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import takeoff as T  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(
        name if cond else f"{name}{' — ' + detail if detail else ''}")


# The real measured roof from B36 8AR.
Q = {
    "plan_area_m2": 121.09, "sloped_area_m2": 138.82, "slope_uplift_pct": 13.5,
    "predominant_pitch_deg": 32, "ridge_m": 7.39, "hip_m": 0.0,
    "valley_m": 0.0, "eaves_m": 45.09,
    "materials": {"covering": "concrete_interlocking", "covering_units": 1512,
                  "battens_m": 503.3, "membrane_m2": 158.0, "ridge_units": 28,
                  "guttering_m": 45.1, "waste_factor": 1.1},
}


# ---- 1. rate card ---------------------------------------------------------
card = T.RateCard()
check("1a defaults load", card.material("battens_m")[0] > 0)
check("1b defaults are marked as defaults", card.is_default("battens_m"))

own = T.RateCard(materials={"battens_m": 1.10}, version="mine-v1")
check("1c own rate overrides the default",
      own.material("battens_m")[0] == 1.10)
check("1d own rate is not marked default", not own.is_default("battens_m"))
check("1e untouched rates stay default", own.is_default("membrane_m2"))
check("1f version recorded", own.version == "mine-v1")
# A bare number must inherit the unit and description it replaces.
check("1g bare number keeps its unit", own.material("battens_m")[1] == "m")

rich = T.RateCard(materials={"battens_m": {"rate": 0.9, "unit": "m",
                                           "description": "my batten"}})
check("1h dict form accepted", rich.material("battens_m")[2] == "my batten")
tup = T.RateCard(labour={"roofer": (300.0, "day", "my roofer")})
check("1i tuple form accepted", tup.labour_rate("roofer")[0] == 300.0)

for bad in ({"materials": {"x": "free"}},):
    try:
        T.RateCard(**bad)
        check("1j unreadable rate refused", False)
    except T.QuoteError:
        check("1j unreadable rate refused", True)

try:
    card.material("unobtainium")
    check("1k unknown material refused", False)
except T.QuoteError as e:
    check("1k unknown material refused", "unobtainium" in str(e))
    check("1l refusal lists what is known", "battens_m" in str(e))


# ---- 2. pricing derives from SLOPED area, never plan ----------------------
# The distinction the roof module exists to make, carried through so the
# quote cannot quietly revert to footprint and under-order.
lines = T.price_roof(Q, card)
check("2a lines produced", len(lines) >= 5, str(len(lines)))
check("2b every line is traceable",
      all(l.source for l in lines))
check("2c quantities cite sloped area",
      any("sloped" in l.source for l in lines),
      str([l.source for l in lines]))

no_sloped = dict(Q); no_sloped.pop("sloped_area_m2")
try:
    T.price_roof(no_sloped, card)
    check("2d missing sloped area refused", False)
except T.QuoteError as e:
    check("2d missing sloped area refused", "sloped_area_m2" in str(e))
    check("2e refusal explains the risk", "under-order" in str(e), str(e))

# Zero-length elements must not appear as £0 lines.
check("2f zero valley produces no line",
      not any(l.key == "valley_m" for l in lines))

slate = T.price_roof(Q, card, covering="natural_slate")
check("2g covering can be overridden",
      any(l.key == "natural_slate" for l in slate))


# ---- 3. labour ------------------------------------------------------------
lab = T.labour_for_roof(Q, card, gang=2)
check("3a labour lines produced", len(lab) == 2, str(len(lab)))
check("3b days derive from area and output",
      "138.82 m2" in lab[0].source, lab[0].source)
solo = T.labour_for_roof(Q, card, gang=1)
check("3c a gang of one has no mate line", len(solo) == 1)
check("3d a bigger gang takes fewer days",
      T.labour_for_roof(Q, card, gang=4)[0].quantity < solo[0].quantity)
check("3e no area means no labour", T.labour_for_roof({}, card) == [])


# ---- 4. totals ------------------------------------------------------------
q = T.build_quote(Q, card)
t = q["totals"]
check("4a materials total is the sum of its lines",
      abs(t["materials"] - sum(l["total"] for l in q["materials"])) < 0.02)
check("4b net is materials plus labour",
      abs(t["net"] - (t["materials"] + t["labour"])) < 0.02)
check("4c prelims applied to net",
      abs(t["prelims"] - t["net"] * 0.08) < 0.02)
check("4d margin applied after prelims",
      abs(t["margin"] - (t["net"] + t["prelims"]) * 0.18) < 0.02)
check("4e subtotal composes correctly",
      abs(t["subtotal"] - (t["net"] + t["prelims"] + t["margin"])) < 0.02)
check("4f VAT on the subtotal", abs(t["vat"] - t["subtotal"] * 0.20) < 0.02)
check("4g total is subtotal plus VAT",
      abs(t["total"] - (t["subtotal"] + t["vat"])) < 0.02)
check("4h a real roof prices to a plausible figure",
      3000 < t["total"] < 25000, str(t["total"]))


# ---- 5. UK VAT is not flat ------------------------------------------------
# Getting this wrong is expensive in both directions, so the basis is chosen
# per quote — it depends on the WORK, not the trade.
std = T.build_quote(Q, card, vat="standard")["totals"]
red = T.build_quote(Q, card, vat="reduced")["totals"]
zero = T.build_quote(Q, card, vat="zero")["totals"]
check("5a standard is 20%", std["vat_pct"] == 20.0)
check("5b reduced is 5%", red["vat_pct"] == 5.0)
check("5c zero rating charges nothing", zero["vat"] == 0.0)
check("5d zero-rated total equals subtotal",
      zero["total"] == zero["subtotal"])
check("5e reduced beats standard", red["total"] < std["total"])
check("5f standard rate prompts a check",
      any("5%" in w or "zero" in w for w in
          T.build_quote(Q, card, vat="standard")["warnings"]))

try:
    T.build_quote(Q, card, vat="made_up")
    check("5g unknown VAT basis refused", False)
except T.QuoteError as e:
    check("5g unknown VAT basis refused", "standard" in str(e))


# ---- 6. CIS is withheld from labour only ----------------------------------
# A common and costly slip: deducting it from the whole invoice rather than
# the labour element.
cis = T.build_quote(Q, card, cis="registered")
check("6a CIS reported", cis["cis"] is not None)
check("6b CIS is 20% of labour, not of the total",
      abs(cis["cis"]["deduction_from_labour"]
          - cis["totals"]["labour"] * 0.20) < 0.02,
      str(cis["cis"]))
check("6c CIS says it excludes materials",
      "never materials" in cis["cis"]["note"])
check("6d unregistered is 30%",
      T.build_quote(Q, card, cis="unregistered")["cis"]["rate_pct"] == 30.0)
check("6e no CIS by default", T.build_quote(Q, card)["cis"] is None)
# CIS changes what the subcontractor RECEIVES, not what the job COSTS.
check("6f CIS does not alter the job total",
      cis["totals"]["total"] == std["total"])

try:
    T.build_quote(Q, card, cis="nonsense")
    check("6g unknown CIS status refused", False)
except T.QuoteError:
    check("6g unknown CIS status refused", True)


# ---- 7. default rates must be flagged loudly ------------------------------
# Sending a customer a quote priced on someone else's guessed rates is the
# most likely way this tool loses a user money.
q = T.build_quote(Q, card)
check("7a default rates warned about",
      any("default rates" in w for w in q["warnings"]), str(q["warnings"]))
check("7b warning names the lines",
      any("battens_m" in w for w in q["warnings"]))
check("7c warning says to fix it before sending",
      any("before sending" in w for w in q["warnings"]))

full = T.RateCard(
    materials={k: v[0] for k, v in T.DEFAULT_MATERIAL_RATES.items()},
    labour={k: v[0] for k, v in T.DEFAULT_LABOUR_RATES.items()},
    version="mine")
check("7d a fully custom card raises no default warning",
      not any("default rates" in w
              for w in T.build_quote(Q, full)["warnings"]))


# ---- 8. guards ------------------------------------------------------------
for pct in (-0.1, 1.0, 1.5):
    try:
        T.build_quote(Q, card, margin_pct=pct)
        check(f"8a margin {pct} refused", False)
    except T.QuoteError:
        check(f"8a margin {pct} refused", True)
try:
    T.build_quote(Q, card, prelims_pct=-0.5)
    check("8b negative prelims refused", False)
except T.QuoteError:
    check("8b negative prelims refused", True)

check("8c rate card version carried onto the quote",
      T.build_quote(Q, own)["rate_card_version"] == "mine-v1")
check("8d currency stated", q["currency"] == "GBP")

# Every line must be auditable back to the geometry.
for line in q["materials"] + q["labour"]:
    check(f"8e {line['key']} cites its source", bool(line["measured_from"]))


# ==========================================================================
# ---- the rate is rounded for DISPLAY, not before multiplying -------------
# Materials priced per metre or per square metre routinely land on fractions
# of a penny, and rounding the rate first looks tidy and is wrong at
# quantity: 500m at a true £0.855 billed £425.00 instead of £427.50.
_line = T.Line("x", "Membrane", 500.0, "m", 0.855, "rate_card")
check("R1 the line total uses the full-precision rate",
      _line.total == 427.50, str(_line.total))
check("R2 while the rate still displays in pence", _line.rate == 0.85)
check("R3 and rounding first would have been wrong",
      round(500.0 * round(0.855, 2), 2) == 425.00)


print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
