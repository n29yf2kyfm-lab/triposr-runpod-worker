"""Tests for material prices, tiers and forecasting.

Run: python building/test_prices.py
"""
import os
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import prices as P  # noqa: E402

PASSED, FAILED = [], []
TODAY = date(2026, 8, 1)


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(
        name if cond else f"{name}{' — ' + detail if detail else ''}")


def obs(product, tier, price, source=P.INVOICE, days_ago=10, **kw):
    return P.Observation(product, tier, price, source,
                         TODAY - timedelta(days=days_ago), **kw)


# ---- 1. observations ------------------------------------------------------
o = obs("roof_covering", P.STANDARD, 1.20)
check("1a unit inherited from the catalogue", o.unit == "each")
check("1b age computed", o.age_days(TODAY) == 10)

for bad, label in [
    (("nonsense", P.STANDARD, 1.0), "unknown product"),
    (("roof_covering", "gold", 1.0), "unknown tier"),
    (("roof_covering", P.STANDARD, 0), "zero price"),
    (("roof_covering", P.STANDARD, -5), "negative price"),
]:
    try:
        P.Observation(*bad, P.INVOICE, TODAY)
        check(f"1c {label} refused", False)
    except P.PriceError:
        check(f"1c {label} refused", True)

try:
    P.Observation("roof_covering", P.STANDARD, 1.0, "hearsay", TODAY)
    check("1d unknown source refused", False)
except P.PriceError as e:
    check("1d unknown source refused", "invoice" in str(e))


# ---- 2. source trust: a paid invoice beats a list price -------------------
# A scraped or published shelf price is retail list. Trade pricing runs
# 15-40% below it and is account-specific, so what the user actually PAID
# must outrank what a website says.
mixed = [obs("plasterboard", P.STANDARD, 4.20, P.PUBLISHED, 5),
         obs("plasterboard", P.STANDARD, 2.90, P.INVOICE, 5)]
e = P.estimate(mixed, "plasterboard", P.STANDARD, TODAY)
check("2a the paid price wins over the published one",
      abs(e["price"] - 2.90) < 0.01, str(e["price"]))
check("2b the winning source is named", e["best_source"] == P.INVOICE)
check("2c own invoices are counted", e["your_invoices"] == 1)

check("2d invoice outranks quote outranks published outranks index",
      P.SOURCE_TRUST[P.INVOICE] > P.SOURCE_TRUST[P.QUOTE]
      > P.SOURCE_TRUST[P.PUBLISHED] > P.SOURCE_TRUST[P.INDEX])


# ---- 3. age decay ---------------------------------------------------------
# Materials moved violently through 2021-23, so an old invoice is history.
fresh = obs("bricks", P.STANDARD, 0.60, P.INVOICE, 5)
old = obs("bricks", P.STANDARD, 0.40, P.INVOICE, 300)
check("3a a fresh price outweighs an old one",
      fresh.weight(TODAY) > old.weight(TODAY))
check("3b weight halves over the half-life",
      abs(obs("bricks", P.STANDARD, 1, P.INVOICE,
              P.HALF_LIFE_DAYS).weight(TODAY)
          - P.SOURCE_TRUST[P.INVOICE] / 2) < 0.5)
check("3c stale prices carry no weight",
      obs("bricks", P.STANDARD, 1, P.INVOICE, 400).weight(TODAY) == 0.0)
e = P.estimate([fresh, old], "bricks", P.STANDARD, TODAY)
check("3d the estimate follows the fresh price",
      abs(e["price"] - 0.60) < 0.01, str(e["price"]))
check("3e freshness is reported", e["newest_days"] == 5)


# ---- 4. robustness --------------------------------------------------------
# One mistyped invoice must not drag the figure — the same reasoning as the
# scale module, because a wrong number here propagates into every quote.
typo = [obs("bricks", P.STANDARD, 0.60, P.INVOICE, 5),
        obs("bricks", P.STANDARD, 0.62, P.INVOICE, 8),
        obs("bricks", P.STANDARD, 60.00, P.INVOICE, 6)]   # decimal slip
e = P.estimate(typo, "bricks", P.STANDARD, TODAY)
check("4a a decimal slip does not win", e["price"] < 1.0, str(e["price"]))
check("4b the spread is reported", e["spread_pct"] > 100, str(e["spread_pct"]))


# ---- 5. no data is not a guess --------------------------------------------
e = P.estimate([], "bricks", P.STANDARD, TODAY)
check("5a no data gives no price", e["price"] is None)
check("5b confidence says none", e["confidence"] == "none")
check("5c it says what to do instead",
      "rate card" in e["message"], e["message"])


# ---- 6. confidence --------------------------------------------------------
own_fresh = [obs("bricks", P.STANDARD, 0.60, P.INVOICE, 5),
             obs("bricks", P.STANDARD, 0.62, P.INVOICE, 10)]
check("6a own fresh prices rate high",
      P.estimate(own_fresh, "bricks", P.STANDARD, TODAY)["confidence"]
      == "high")
check("6b an old published price rates low",
      P.estimate([obs("bricks", P.STANDARD, 0.6, P.PUBLISHED, 300)],
                 "bricks", P.STANDARD, TODAY)["confidence"] == "low")


# ---- 7. three tiers, side by side -----------------------------------------
roof = [obs("roof_covering", P.ECONOMY, 1.20),
        obs("roof_covering", P.STANDARD, 0.55),
        obs("roof_covering", P.PREMIUM, 2.40)]
c = P.compare_tiers(roof, "roof_covering", TODAY)
check("7a all three tiers present", len(c["tiers"]) == 3)
check("7b each tier carries its spec",
      all(c["tiers"][t].get("spec") for t in P.TIERS))
check("7c each tier is labelled for what it means",
      "shortest life" in c["tiers"][P.ECONOMY]["label"])
check("7d compared against the cheapest",
      c["tiers"][P.PREMIUM]["vs_cheapest_pct"] > 0)

# The argument a customer actually responds to: premium slate at twice the
# price and three times the life is CHEAPER per year than concrete.
cpy = {t: c["tiers"][t].get("cost_per_year") for t in P.TIERS}
check("7e whole-life cost computed", all(v for v in cpy.values()), str(cpy))
check("7f premium can win on cost per year",
      cpy[P.PREMIUM] < cpy[P.ECONOMY], str(cpy))

# Tier is about specification, not just price. Some economy choices are a
# false economy and must say so.
w = P.compare_tiers([obs("battens", P.ECONOMY, 0.60)],
                    "battens", TODAY)["tiers"][P.ECONOMY]["warning"]
check("7g a false economy is flagged", w is not None)
check("7h it names the standard", "BS 5534" in w, str(w))
check("7i it explains the failure mode", "premature roof failure" in w)
check("7j no warning on the standard tier",
      P.compare_tiers([obs("battens", P.STANDARD, 0.85)], "battens",
                      TODAY)["tiers"][P.STANDARD]["warning"] is None)

try:
    P.compare_tiers([], "unobtainium")
    check("7k unknown product refused", False)
except P.PriceError:
    check("7k unknown product refused", True)


# ---- 8. index trend -------------------------------------------------------
# Free, official, monthly, decades of history — the only honest basis for
# forecasting, and better than a snapshot of today's shelf price.
rising = [(date(2025, m, 1), 100 + m * 1.0) for m in range(1, 13)]
t = P.trend(rising)
check("8a a rising series is detected", t["pct_per_month"] > 0, str(t))
check("8b a clean trend fits well", t["r_squared"] > 0.99, str(t["r_squared"]))
check("8c annualised", abs(t["pct_per_year"] - t["pct_per_month"] * 12) < 0.1)

noisy = [(date(2025, m, 1), 100 + (7 * m % 13)) for m in range(1, 13)]
check("8d a wandering series fits badly", P.trend(noisy)["r_squared"] < 0.5,
      str(P.trend(noisy)["r_squared"]))
check("8e too few points gives nothing", P.trend([(date(2025, 1, 1), 100)])
      is None)


# ---- 9. forecasting is labelled a projection ------------------------------
f = P.forecast(1.20, t, 6)
check("9a projected forward", f["projected"] > 1.20, str(f))
check("9b a range is given", f["low"] < f["projected"] < f["high"])
check("9c the range widens with horizon",
      (P.forecast(1.20, t, 12)["high"] - P.forecast(1.20, t, 12)["low"])
      > (f["high"] - f["low"]))
check("9d it says it is not a quotation", "not a quotation" in f["note"])
check("9e it says the index is national, not your merchant",
      "UK-wide basket" in f["note"], f["note"])
check("9f the basis is named", "Construction Material Price" in f["basis"])

weak = P.forecast(1.20, P.trend(noisy), 6)
check("9g a weak fit is declared unreliable", not weak["reliable"])
check("9h it says to get a quote", "get a quote" in weak["note"], weak["note"])
check("9i a weak fit widens the range",
      (weak["high"] - weak["low"]) > (f["high"] - f["low"]))

check("9j no trend gives no forecast", P.forecast(1.20, None, 6) is None)
try:
    P.forecast(1.20, t, 0)
    check("9k zero horizon refused", False)
except P.PriceError:
    check("9k zero horizon refused", True)


# ---- 10. weekly refresh and coverage --------------------------------------
check("10a never refreshed is due",
      P.refresh_due(None, TODAY)["due"])
check("10b a week old is due",
      P.refresh_due(TODAY - timedelta(days=7), TODAY)["due"])
check("10c two days old is not",
      not P.refresh_due(TODAY - timedelta(days=2), TODAY)["due"])
check("10d next due date given",
      P.refresh_due(TODAY - timedelta(days=2), TODAY)["next_due"] is not None)

cov = P.coverage(roof + [obs("bricks", P.STANDARD, 0.6, P.PUBLISHED)], TODAY)
check("10e slots counted", cov["slots"] == len(P.CATALOGUE) * 3)
check("10f gaps listed", len(cov["gaps"]) > 0)
check("10g covered counted", cov["covered"] == 4, str(cov["covered"]))
# A builder should see how much of their price set is genuinely theirs.
check("10h own-price share reported",
      abs(cov["own_price_share"] - 75.0) < 0.1, str(cov["own_price_share"]))
check("10i empty set does not divide by zero",
      P.coverage([], TODAY)["own_price_share"] == 0.0)



# ---- clock skew must not void a whole price list -------------------------
# A price dated slightly in the future is a clock, not a claim about the
# future. The worker, the caller and the merchant's export can sit in
# different timezones; treating a day of drift as "weight zero" silently
# voided every line of a list imported minutes earlier, and it surfaced as
# "no usable price" rather than as anything anyone could act on.
_today = date(2026, 8, 1)
_skewed = P.Observation("battens", P.STANDARD, 0.92, P.INVOICE,
                        date(2026, 8, 2))          # one day ahead
check("skew-1 one day of drift still counts",
      _skewed.weight(_today) > 0, str(_skewed.weight(_today)))
check("skew-2 and counts as fresh, not decayed",
      abs(_skewed.weight(_today) - P.SOURCE_TRUST[P.INVOICE]) < 1e-9,
      str(_skewed.weight(_today)))

_far = P.Observation("battens", P.STANDARD, 0.92, P.INVOICE,
                     date(2026, 12, 1))            # four months ahead
check("skew-3 a genuinely future date is still refused",
      _far.weight(_today) == 0.0, str(_far.weight(_today)))

# ...and when everything IS discarded, say which of the two reasons it was.
_r = P.estimate([_far], "battens", P.STANDARD, today=_today)
check("skew-4 a future-dated discard explains itself",
      "future" in _r["message"], _r["message"])
check("skew-5 and counts what it threw away",
      _r.get("observations_discarded") == 1, str(_r.get("observations_discarded")))

_old = P.Observation("battens", P.STANDARD, 0.92, P.INVOICE, date(2024, 1, 1))
_r = P.estimate([_old], "battens", P.STANDARD, today=_today)
check("skew-6 a stale discard explains itself differently",
      "old" in _r["message"], _r["message"])

_r = P.estimate([], "battens", P.STANDARD, today=_today)
check("skew-7 nothing supplied still reads as nothing supplied",
      "rate card" in _r["message"], _r["message"])

# ==========================================================================
print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
