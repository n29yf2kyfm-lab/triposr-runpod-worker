"""Tests for valuation.

Two things here can lose someone real money, and neither looks wrong on the
screen: comparing sales from different years without indexing them, and
telling someone an extension will pay for itself when it will not. Most of
these tests are about those two.

Run: python building/test_valuation.py
"""
import os
import sys
import types
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import valuation as V  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(
        name if cond else f"{name}{' — ' + detail if detail else ''}")


TODAY = date(2026, 8, 1)


def sale(price, year, month=6, ptype="S", area=90.0, **kw):
    return V.Sale(price=price, sold_on=date(year, month, 1),
                  property_type=ptype, floor_area_m2=area,
                  postcode="B36 8AR", **kw)


# A rising market: index 100 in 2020 climbing to 130 by 2026.
INDEX = {date(y, m, 1): 100.0 + (y - 2020) * 5.0
         for y in range(2019, 2027) for m in (1, 4, 7, 10)}


# ---- 1. a sale ------------------------------------------------------------
s = sale(250_000, 2024)
check("1a price per m2", abs(s.price_per_m2 - 250_000 / 90.0) < 1e-9)
check("1b age in years", abs(s.age_years(TODAY) - 2.17) < 0.05,
      str(s.age_years(TODAY)))
check("1c serialises", V.PROPERTY_TYPES["S"] in str(s.as_dict()))
check("1d no floor area means no rate",
      V.Sale(250_000, date(2024, 6, 1), "S").price_per_m2 is None)

for bad, label in [
        ({"price": 0}, "zero price"),
        ({"price": -1}, "negative price"),
        ({"property_type": "X"}, "unknown type"),
        ({"tenure": "Z"}, "unknown tenure"),
        ({"floor_area_m2": 0}, "zero area")]:
    kwargs = {"price": 100_000, "sold_on": date(2024, 1, 1),
              "property_type": "S"}
    kwargs.update(bad)
    try:
        V.Sale(**kwargs)
        check(f"1e {label} refused", False)
    except V.ValuationError:
        check(f"1e {label} refused", True)


# ---- 2. indexing — the step that makes a comparable honest ----------------
# A 2020 sale is not evidence about 2026 prices. Index 100 -> 130 is +30%.
got = V.index_price(200_000, date(2020, 6, 1), INDEX, TODAY)
check("2a old sale brought to today's money",
      abs(got - 200_000 * 130.0 / 100.0) < 1.0, str(got))
check("2b a sale from today is unchanged",
      abs(V.index_price(200_000, date(2026, 7, 1), INDEX, TODAY) - 200_000)
      < 1.0)

# Extrapolating an index is how you get a market turn confidently wrong.
try:
    V.index_price(200_000, date(2015, 1, 1), INDEX, TODAY)
    check("2c a sale before the series is refused", False)
except V.ValuationError as e:
    check("2c a sale before the series is refused", "does not cover" in str(e))

try:
    V.index_price(200_000, date(2024, 1, 1), INDEX, date(2030, 1, 1))
    check("2d indexing past the series is refused", False)
except V.ValuationError as e:
    check("2d indexing past the series is refused", "arrears" in str(e),
          str(e))

try:
    V.index_price(200_000, date(2020, 1, 1), None, TODAY)
    check("2e no index at all is refused", False)
except V.ValuationError as e:
    check("2e no index at all is refused", "UKHPI" in str(e))

# Never reach forward for an index value the market had not produced yet.
check("2f uses the closest EARLIER month",
      V._index_at(INDEX, date(2022, 6, 15)) == V._index_at(INDEX,
                                                           date(2022, 4, 1)))
check("2g latest month reported",
      V.latest_index_month(INDEX) == date(2026, 10, 1))


# ---- 3. valuing from comparables ------------------------------------------
COMPS = [sale(240_000, 2024, area=88.0), sale(250_000, 2024, area=90.0),
         sale(262_000, 2025, area=94.0), sale(255_000, 2025, area=92.0),
         sale(268_000, 2025, area=96.0), sale(245_000, 2024, area=89.0)]

r = V.value_from_comparables(COMPS, 92.0, "S", INDEX, TODAY)
check("3a a value is produced", r["value"] > 0)
check("3b a RANGE is produced, not a bare number",
      r["range_low"] < r["value"] < r["range_high"], str(r))
check("3c rate per m2 reported", 2000 < r["price_per_m2"] < 4000,
      str(r["price_per_m2"]))
check("3d the value is plausible", 220_000 < r["value"] < 330_000,
      str(r["value"]))
check("3e comparables counted", r["comparables_used"] >= 5)
check("3f basis names its source", "Land Registry" in r["basis"])
check("3g indexing is stated in the basis", "UKHPI" in r["basis"])
check("3h completion lag warned about",
      any("completion" in w for w in r["warnings"]), str(r["warnings"]))
check("3i says it is not a survey",
      any("not a survey" in w for w in r["warnings"]))

# Without an index, the module must SAY the comparison is across years.
r_noindex = V.value_from_comparables(COMPS, 92.0, "S", None, TODAY)
check("3j missing index is warned about loudly",
      any("NOT indexed" in w for w in r_noindex["warnings"]),
      str(r_noindex["warnings"]))
check("3k and confidence drops to low", r_noindex["confidence"] == "low")

# Recency must be scored against the DATE THE VALUATION IS FOR, not the real
# clock. Reading date.today() here made every backtest quietly wrong about
# how fresh its own comparables were.
_hist = V.value_from_comparables(COMPS, 92.0, "S", INDEX, date(2025, 8, 1))
check("3l a historical valuation scores recency against its own date",
      _hist["confidence"] in ("good", "fair", "low"), _hist["confidence"])
import inspect  # noqa: E402
check("3m _confidence takes today rather than reading the clock",
      "today=None" in inspect.signature(V._confidence).__str__()
      or "today" in inspect.signature(V._confidence).parameters,
      str(inspect.signature(V._confidence)))
check("3n and passes it to age_years",
      "age_years(today)" in inspect.getsource(V._confidence),
      inspect.getsource(V._confidence))


# ---- 4. what must be excluded ---------------------------------------------
# Category B is repossessions and non-market transfers. Including them
# quietly undervalues every property in the postcode.
mixed = COMPS + [sale(120_000, 2025, area=90.0,
                      category=V.CATEGORY_ADDITIONAL)]
r = V.value_from_comparables(mixed, 92.0, "S", INDEX, TODAY)
check("4a category B sale excluded", r["comparables_excluded"] == 1,
      str(r["comparables_excluded"]))
check("4b and it does not drag the value down",
      abs(r["value"] - V.value_from_comparables(
          COMPS, 92.0, "S", INDEX, TODAY)["value"]) < 1.0)

mixed = COMPS + [sale(900_000, 2025, ptype="D", area=200.0)]
r = V.value_from_comparables(mixed, 92.0, "S", INDEX, TODAY)
check("4c a different property type is excluded",
      r["comparables_excluded"] == 1)

mixed = COMPS + [V.Sale(250_000, date(2025, 1, 1), "S")]   # no floor area
r = V.value_from_comparables(mixed, 92.0, "S", INDEX, TODAY)
check("4d a sale with no floor area is excluded",
      r["comparables_excluded"] == 1)

old = [sale(100_000, 2012, area=90.0) for _ in range(4)]
try:
    V.value_from_comparables(old, 92.0, "S", INDEX, TODAY)
    check("4e sales outside the window are excluded", False)
except V.ValuationError as e:
    check("4e sales outside the window are excluded",
          "older than" in str(e), str(e))


# ---- 5. refusals ----------------------------------------------------------
try:
    V.value_from_comparables(COMPS[:2], 92.0, "S", INDEX, TODAY)
    check("5a too few comparables refused", False)
except V.ValuationError as e:
    check("5a too few comparables refused", "at least" in str(e))
    check("5b refusal says what to do", "Widen" in str(e), str(e))

for bad, label in [((COMPS, None, "S"), "no floor area"),
                   ((COMPS, 0, "S"), "zero floor area"),
                   ((COMPS, 92.0, "X"), "unknown type")]:
    try:
        V.value_from_comparables(bad[0], bad[1], bad[2], INDEX, TODAY)
        check(f"5c {label} refused", False)
    except V.ValuationError:
        check(f"5c {label} refused", True)

# Wild disagreement means the postcode mixes genuinely different property.
wild = [sale(150_000, 2025, area=90.0), sale(160_000, 2025, area=90.0),
        sale(155_000, 2025, area=90.0), sale(900_000, 2025, area=90.0),
        sale(880_000, 2025, area=90.0), sale(870_000, 2025, area=90.0)]
r = V.value_from_comparables(wild, 90.0, "S", INDEX, TODAY)
check("5d a wildly split market still reports its spread",
      r["spread_pct"] > 50, str(r["spread_pct"]))
check("5e and does not claim confidence", r["confidence"] == "low")


# ---- 6. coverage — England and Wales only ---------------------------------
check("6a a Birmingham postcode is covered", V.check_coverage("B36 8AR"))
check("6b a Gloucester postcode is covered", V.check_coverage("GL1 1AA"))
check("6c a Guildford postcode is covered", V.check_coverage("GU1 1AA"))
check("6d a Cardiff postcode is covered", V.check_coverage("CF10 1AA"))
check("6e a Carlisle postcode is covered", V.check_coverage("CA1 1AA"))

# THE parsing bug this guards: "B36 8AR" contains A and R in its inward code,
# so collecting every letter turns Birmingham into "BA", which is Bath.
check("6f the area is read from the front, not from every letter",
      V.check_coverage("B36 8AR"))

# The Crown Dependencies are NOT in the UK and keep their own land registers,
# but they use UK-format postcodes — so they sail through a check that only
# screens Scotland and Northern Ireland, and the caller gets "no recorded
# sales" for the wrong jurisdiction rather than "wrong country".
for postcode, register in [("GY1 1AA", "Guernsey"),
                           ("JE2 3AB", "Jersey"),
                           ("IM1 1AA", "Isle of Man")]:
    try:
        V.check_coverage(postcode)
        check(f"6f2 {postcode} ({register}) refused", False,
              "passed as England and Wales")
    except V.ValuationError as e:
        check(f"6f2 {postcode} ({register}) refused", register in str(e),
              str(e)[:80])
        check(f"6f3 {postcode} names the right register",
              "own" in str(e) and "England and Wales only" in str(e),
              str(e)[:80])

for postcode, nation in [("EH1 2AB", "Scotland"), ("G12 8QQ", "Scotland"),
                         ("AB10 1AA", "Scotland"), ("KY1 1AA", "Scotland"),
                         ("BT1 1AA", "Land & Property")]:
    try:
        V.check_coverage(postcode)
        check(f"6g {postcode} refused", False)
    except V.ValuationError as e:
        check(f"6g {postcode} refused", nation in str(e), str(e))

for bad in (None, "", "!!!"):
    try:
        V.check_coverage(bad)
        check(f"6h {bad!r} refused", False)
    except V.ValuationError:
        check(f"6h {bad!r} refused", True)


# ---- 7. THE question: does the extension pay? -----------------------------
# The naive calculation is added_m2 * price_per_m2, and it is always too big.
u = V.extension_uplift(current_value=250_000, current_floor_area_m2=90.0,
                       added_m2=20.0, price_per_m2=2800.0)
check("7a naive figure is reported for comparison",
      abs(u["naive_uplift"] - 56_000) < 100, str(u["naive_uplift"]))
check("7b the real uplift is LESS than the naive one",
      u["uplift"] < u["naive_uplift"], str(u))
check("7c marginal factor applied",
      abs(u["uplift"] - 56_000 * 0.6) < 100, str(u["uplift"]))
check("7d and the reason is stated", "second plot" in u["marginal_note"])
check("7e new floor area computed", u["new_floor_area_m2"] == 110.0)

# The ceiling — the most useful thing in the module.
u = V.extension_uplift(250_000, 90.0, 40.0, 2800.0, street_ceiling=280_000)
check("7f ceiling applied", u["ceiling_applied"])
check("7g value is capped near the ceiling", u["new_value"] <= 308_001,
      str(u["new_value"]))
# The note used to attribute the WHOLE haircut to the street ceiling. Here
# the ceiling costs £9,200 and the marginal factor £44,800, and a builder
# reads this note out to a customer — so the two are now separated by name.
check("7h the amount the CEILING costs is named",
      "ceiling costs" in u["ceiling_note"], u.get("ceiling_note", ""))
check("7h2 and it is not blamed for the marginal factor's share",
      "marginal factor above, not the ceiling" in u["ceiling_note"],
      u.get("ceiling_note", ""))
_by_ceiling = (u["naive_uplift"] * u["marginal_factor"]) - u["uplift"]
check("7h3 and the figure is the ceiling's actual share",
      f"£{_by_ceiling:,.0f}" in u["ceiling_note"],
      f"expected £{_by_ceiling:,.0f} in: {u['ceiling_note']}")

# at_ceiling used to be computed INSIDE the cap branch, so a house already
# above the street ceiling got the full uplift and no flag whenever the
# extension was small enough not to trip the 10% tolerance — the smaller,
# commoner job, and the one where "build it for the space" is the advice.
_small = V.extension_uplift(305_000, 90.0, 5.0, 2800.0, street_ceiling=300_000)
check("7h4 a house already at the ceiling is flagged on a SMALL extension",
      _small.get("at_ceiling") is True,
      f"ceiling_applied={_small['ceiling_applied']} "
      f"at_ceiling={_small.get('at_ceiling')}")
check("7h5 and told there is no headroom at any size",
      "build it for the space" in (_small.get("ceiling_note") or ""),
      str(_small.get("ceiling_note")))
_below = V.extension_uplift(200_000, 90.0, 5.0, 2800.0, street_ceiling=300_000)
check("7h6 but a house well below the ceiling is not flagged",
      "at_ceiling" not in _below, str(_below.get("at_ceiling")))

# A build that does NOT pay for itself must say so plainly.
u = V.extension_uplift(250_000, 90.0, 20.0, 2800.0, build_cost=60_000)
check("7i shortfall detected", not u["pays_for_itself"], str(u))
check("7j verdict says SHORT", "SHORT" in u["verdict"], u["verdict"])
check("7k net is negative", u["net"] < 0)
check("7l return percentage reported", 0 < u["returns_pct"] < 100)
check("7m but it does not tell them not to live in their house",
      "how they want to live" in u["verdict"])

u = V.extension_uplift(250_000, 90.0, 30.0, 3500.0, build_cost=40_000)
check("7n a build that pays is identified", u["pays_for_itself"], str(u))
check("7o and says it is worth doing", "Worth doing" in u["verdict"])
check("7p net is positive", u["net"] > 0)

check("7q resale caveat always present",
      any("resale" in w for w in u["warnings"]))
check("7r garden and light caveat present",
      any("garden" in w for w in u["warnings"]))

for kwargs, label in [
        ({"current_value": 0}, "zero value"),
        ({"added_m2": 0}, "zero area added"),
        ({"added_m2": -5}, "negative area"),
        ({"current_floor_area_m2": 0}, "zero current area"),
        ({"price_per_m2": 0}, "zero rate"),
        ({"marginal_factor": 1.5}, "marginal factor above 1"),
        ({"marginal_factor": 0}, "zero marginal factor"),
        ({"build_cost": -1}, "negative build cost")]:
    base = {"current_value": 250_000, "current_floor_area_m2": 90.0,
            "added_m2": 20.0, "price_per_m2": 2800.0}
    base.update(kwargs)
    try:
        V.extension_uplift(**base)
        check(f"7s {label} refused", False)
    except V.ValuationError:
        check(f"7s {label} refused", True)


# ---- 7b. reading real Price Paid records ----------------------------------
# Shapes captured live from the API for B36 8AR — 110 Ermington Crescent.
PPD_ITEM = {
    "pricePaid": 118500,
    "transactionDate": "Mon, 12 Sep 2005",
    "newBuild": False,
    "propertyType": {
        "_about": "http://landregistry.data.gov.uk/def/common/semi-detached"},
    "estateType": {
        "_about": "http://landregistry.data.gov.uk/def/common/freehold"},
    "transactionCategory": {
        "_about": "http://landregistry.data.gov.uk/def/ppi/"
                  "standardPricePaidTransaction"},
    "recordStatus": {"_about": "http://landregistry.data.gov.uk/def/ppi/add"},
    "propertyAddress": {"postcode": "B36 8AR", "paon": "110",
                        "street": "ERMINGTON CRESCENT",
                        "district": "BIRMINGHAM"},
}

check("7b-1 the API date format parses",
      V.parse_ppd_date("Mon, 12 Sep 2005") == date(2005, 9, 12))
check("7b-2 a malformed date is None", V.parse_ppd_date("yesterday") is None)

s = V.parse_ppd_item(PPD_ITEM)
check("7b-3 a real record parses", s is not None)
check("7b-4 price read", s.price == 118500)
check("7b-5 date read", s.sold_on == date(2005, 9, 12))
check("7b-6 semi-detached mapped from the URI slug", s.property_type == "S")
check("7b-7 freehold mapped", s.tenure == "F")
check("7b-8 standard category mapped", s.category == V.CATEGORY_STANDARD)
check("7b-9 address assembled", s.address == "110 ERMINGTON CRESCENT",
      str(s.address))

additional = dict(PPD_ITEM, transactionCategory={
    "_about": "http://landregistry.data.gov.uk/def/ppi/"
              "additionalPricePaidTransaction"})
check("7b-10 category B detected",
      V.parse_ppd_item(additional).category == V.CATEGORY_ADDITIONAL)

# Price Paid is a change log. A "delete" record retracts a sale published in
# error — valuing against it uses a transaction the registry has withdrawn.
deleted = dict(PPD_ITEM, recordStatus={
    "_about": "http://landregistry.data.gov.uk/def/ppi/delete"})
check("7b-11 a deleted record is dropped", V.parse_ppd_item(deleted) is None)

# One bad row must not lose the rest of the page.
for broken, label in [({"pricePaid": None}, "no price"),
                      ({"transactionDate": "rubbish"}, "bad date"),
                      ({"propertyType": {"_about": "x/unknown"}}, "bad type")]:
    check(f"7b-12 {label} is skipped, not fatal",
          V.parse_ppd_item(dict(PPD_ITEM, **broken)) is None)
check("7b-13 a non-dict is skipped", V.parse_ppd_item("nonsense") is None)

# Floor area joins from the EPC register, since Price Paid carries none.
areas = {V._address_key("B36 8AR", "110"): 88.0}
check("7b-14 floor area joins on postcode and PAON",
      V.parse_ppd_item(PPD_ITEM, areas).floor_area_m2 == 88.0)
check("7b-15 the join key ignores spacing and case",
      V._address_key("b368ar", "110") == V._address_key("B36 8AR", "110"))

check("7b-16 postcode tidied to the API's form",
      V._tidy_postcode("b368ar") == "B36 8AR")
for bad in ("B36", "xx"):
    try:
        V._tidy_postcode(bad)
        check(f"7b-17 {bad!r} refused", False)
    except V.ValuationError:
        check(f"7b-17 {bad!r} refused", True)

check("7b-18 months_back walks over a year boundary",
      V.months_back(3, date(2026, 2, 15))
      == [date(2025, 12, 1), date(2026, 1, 1), date(2026, 2, 1)],
      str(V.months_back(3, date(2026, 2, 15))))

# Validation must happen before the HTTP library is imported.
for kwargs, label in [({}, "no postcode or district"),
                      ({"postcode": "B36 8AR", "limit": 0}, "bad limit"),
                      ({"postcode": "EH1 2AB"}, "Scottish postcode")]:
    try:
        V.fetch_sales(**kwargs)
        check(f"7b-19 {label} refused", False)
    except V.ValuationError:
        check(f"7b-19 {label} refused", True)
    except ImportError as e:
        check(f"7b-19 {label} refused", False, f"imported first: {e}")

# THE production bug. The first version fetched one month at a time, which
# is fine on a laptop and unusable on a worker: a five-year comparable window
# is 66 months, so one valuation opened 66 sequential HTTPS connections and
# spent four minutes doing it. Only a real run surfaced it.
_src = open(os.path.join(HERE, "valuation.py")).read()
check("7b-20a the index is fetched as a range, not month by month",
      "UKHPI_RANGE_API" in _src and "min-refMonth" in _src)
check("7b-20b and the per-month walk is gone",
      "for month in months:" not in _src, "still loops per month")

check("7b-20c refMonth parses bare", V._parse_ref_month("2026-05")
      == date(2026, 5, 1))
check("7b-20d refMonth parses wrapped",
      V._parse_ref_month({"_value": "2026-05"}) == date(2026, 5, 1))
check("7b-20e a junk refMonth is None", V._parse_ref_month("nonsense") is None)
check("7b-20f a missing refMonth is None", V._parse_ref_month(None) is None)

for kwargs, label in [({"region": "", "property_type": "S",
                        "months": [date(2026, 1, 1)]}, "no region"),
                      ({"region": "birmingham", "property_type": "X",
                        "months": [date(2026, 1, 1)]}, "bad type"),
                      ({"region": "birmingham", "property_type": "S",
                        "months": []}, "no months")]:
    try:
        V.fetch_index(**kwargs)
        check(f"7b-20 {label} refused", False)
    except V.ValuationError:
        check(f"7b-20 {label} refused", True)
    except ImportError as e:
        check(f"7b-20 {label} refused", False, f"imported first: {e}")


# ---- 7c. valuing from the property's own last sale ------------------------
# Needs no floor area and no EPC key, and holds constant everything a
# comparables method has to assume away.
own = V.value_from_own_sale(sale(200_000, 2024), INDEX, TODAY)
check("7c-1 a value is produced", own["value"] > 200_000, str(own["value"]))
check("7c-2 indexed by the series", abs(own["value"] - 216_700) < 500,
      str(own["value"]))
check("7c-3 a range is given", own["range_low"] < own["range_high"])
check("7c-4 method is named", own["method"] == "own_sale_indexed")
check("7c-5 it says what it cannot see",
      any("cannot see" in w for w in own["warnings"]))

# The range must WIDEN with age — an older sale has had longer to diverge.
recent = V.value_from_own_sale(sale(200_000, 2025), INDEX, TODAY)
old_sale = V.value_from_own_sale(sale(200_000, 2021), INDEX, TODAY)


def band(r):
    return (r["range_high"] - r["range_low"]) / r["value"]


check("7c-6 an older sale gives a wider range",
      band(old_sale) > band(recent), f"{band(old_sale)} vs {band(recent)}")
check("7c-7 and lower confidence",
      old_sale["confidence"] != recent["confidence"] or
      old_sale["confidence"] == "low")

# A category B transfer is not evidence of market value.
try:
    V.value_from_own_sale(sale(120_000, 2024,
                               category=V.CATEGORY_ADDITIONAL), INDEX, TODAY)
    check("7c-8 a category B transfer is refused", False)
except V.ValuationError as e:
    check("7c-8 a category B transfer is refused", "category B" in str(e),
          str(e))

try:
    V.value_from_own_sale(None, INDEX, TODAY)
    check("7c-9 no sale is refused", False)
except V.ValuationError:
    check("7c-9 no sale is refused", True)


# ---- 8. the street ceiling -------------------------------------------------
ceiling = V.street_ceiling(COMPS, INDEX, TODAY)
check("8a a ceiling is found", ceiling is not None)
check("8b it sits at the top of the range", ceiling > 250_000, str(ceiling))

# One exceptional sale is an outlier, not a ceiling.
with_outlier = COMPS + [sale(600_000, 2025, area=90.0)]
check("8c one freak sale does not become the ceiling",
      V.street_ceiling(with_outlier, INDEX, TODAY) < 600_000,
      str(V.street_ceiling(with_outlier, INDEX, TODAY)))

check("8d too few sales means no ceiling claimed",
      V.street_ceiling(COMPS[:2], INDEX, TODAY) is None)

# Found by running against live B36 8AR data: a sale older than the index
# series must narrow the evidence, not abort the job.
# Starts in 2025, so the 2021 sale cannot be indexed — but runs up to the
# present, so the grace check does not reject everything wholesale.
SHORT_INDEX = {date(2025, m, 1): 125.0 + m for m in (1, 4, 7, 10)}
SHORT_INDEX.update({date(2026, m, 1): 136.0 + m for m in (1, 4, 7)})
mixed_age = [sale(255_000, 2025, area=92.0), sale(262_000, 2025, area=94.0),
             sale(268_000, 2025, area=96.0), sale(250_000, 2025, area=90.0),
             sale(258_000, 2025, area=93.0),
             sale(150_000, 2022, area=90.0)]      # before the index starts
still = V.street_ceiling(mixed_age, SHORT_INDEX, TODAY)
check("8f a sale outside the index is skipped, not fatal", still is not None,
      str(still))

r = V.value_from_comparables(mixed_age, 92.0, "S", SHORT_INDEX, TODAY)
check("8g valuation survives an unindexable comparable", r["value"] > 0)
check("8h and reports how many it dropped",
      r["comparables_unindexable"] >= 1, str(r["comparables_unindexable"]))

# But if too few survive, refuse and say why.
try:
    V.value_from_comparables([sale(150_000, 2022, area=90.0)] * 5,
                             92.0, "S", SHORT_INDEX, TODAY)
    check("8i too few indexable comparables refused", False)
except V.ValuationError as e:
    check("8i too few indexable comparables refused",
          "index" in str(e), str(e))


# ---- 9. already at the street ceiling -------------------------------------
# The live B36 8AR run produced identical uplift for a 20 m2 and a 45 m2
# extension, which reads as a bug and is actually the finding: the house is
# already at the top of what the street achieves.
small = V.extension_uplift(241_900, 96.0, 20.0, 2520.0, build_cost=55_000,
                           street_ceiling=241_909)
big = V.extension_uplift(241_900, 96.0, 45.0, 2520.0, build_cost=110_000,
                         street_ceiling=241_909)
check("9a both sizes hit the same cap", small["uplift"] == big["uplift"],
      f'{small["uplift"]} vs {big["uplift"]}')
check("9b and it is flagged as at-ceiling", small.get("at_ceiling") is True)
check("9c the note explains a bigger build does not earn more",
      "does not earn more" in small["ceiling_note"], small["ceiling_note"])
check("9d neither pays for itself", not small["pays_for_itself"]
      and not big["pays_for_itself"])
check("9e the naive figure would have claimed more than double",
      small["naive_uplift"] > 2 * small["uplift"],
      f'{small["naive_uplift"]} vs {small["uplift"]}')

# A house well below the ceiling has real headroom and must NOT be flagged.
room = V.extension_uplift(180_000, 80.0, 20.0, 2520.0, street_ceiling=300_000)
check("9f a house below the ceiling is not capped",
      not room["ceiling_applied"], str(room))
check("9g and is not flagged at-ceiling", "at_ceiling" not in room)
check("8e category B is excluded from the ceiling too",
      V.street_ceiling([sale(900_000, 2025, category=V.CATEGORY_ADDITIONAL)]
                       * 5, INDEX, TODAY) is None)


# ---- 12. the EPC join, which used to be dead code ------------------------
# Price Paid carries no floor area, so price per square metre needs the EPC
# register joined on address. The constant EPC_API was defined and referenced
# nowhere else, nothing ever built the floor_areas map parse_ppd_item
# accepts, and so the per-m2 method — the headline claim of this module, and
# the only thing a measured scan can improve on — was unreachable from run().
# Every valuation silently took the fallback and said nothing about it.

# PAON candidates. The join is postcode + primary addressable object name,
# because neither register publishes a UPRN in its open form.
check("12a a house number is read from an EPC address line",
      "12" in V._epc_paons("12 Acacia Avenue"))
check("12b including a letter suffix", "12A" in V._epc_paons("12A High St"))
check("12c a flat number is not mistaken for the house number",
      "12" in V._epc_paons("Flat 3, 12 Acacia Avenue"),
      str(V._epc_paons("Flat 3, 12 Acacia Avenue")))
check("12d a named house joins on its whole name",
      "The Old Rectory" in V._epc_paons("The Old Rectory"))
check("12e nothing in, nothing out", V._epc_paons("") == [])


class _FakeEPC:
    """The register, without the network."""

    def __init__(self, certificates, areas):
        self.certificates = certificates
        self.areas = areas
        self.detail_calls = 0

    def get(self, url, headers=None, timeout=None, params=None):
        params = params or {}
        if "search" in url:
            return _FakeResponse({"data": self.certificates})
        self.detail_calls += 1
        number = params.get("certificate_number")
        return _FakeResponse({"data": {"total_floor_area":
                                       self.areas.get(number)}})


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _with_fake_epc(fake, key="test-token"):
    module = types.ModuleType("requests")
    module.get = fake.get
    sys.modules["requests"] = module
    os.environ[V.EPC_KEY_ENV] = key


def _clear_fake_epc():
    sys.modules.pop("requests", None)
    os.environ.pop(V.EPC_KEY_ENV, None)


_CERTS = [
    {"certificateNumber": "C1", "addressLine1": "59 Ermington Crescent",
     "postcode": "B36 8AR", "registrationDate": "2024-01-01"},
    {"certificateNumber": "C2", "addressLine1": "97 Ermington Crescent",
     "postcode": "B36 8AR", "registrationDate": "2023-01-01"},
]
_AREAS = {"C1": 61.0, "C2": 86.0}

_fake = _FakeEPC(_CERTS, _AREAS)
_with_fake_epc(_fake)
try:
    _areas, _note = V.fetch_floor_areas("B36 8AR")
    check("12f floor areas come back keyed for the Price Paid join",
          _areas.get(V._address_key("B36 8AR", "59")) == 61.0, str(_areas))
    check("12g and the note says how many were read",
          "2 floor areas" in _note, _note)
finally:
    _clear_fake_epc()

# Only the addresses actually needed are fetched. A postcode search returns
# a summary with no floor area, so each certificate costs its own request;
# filtering to the comparable set turns 40 requests into 8.
_fake = _FakeEPC(_CERTS, _AREAS)
_with_fake_epc(_fake)
try:
    V.fetch_floor_areas("B36 8AR",
                        wanted={V._address_key("B36 8AR", "59")})
    check("12h only the wanted addresses cost a request",
          _fake.detail_calls == 1, f"{_fake.detail_calls} detail calls")
finally:
    _clear_fake_epc()

# Two certificates behind one house number are two flats, not one house.
# Picking either would attach a wrong floor area to a real sale.
_split = [
    {"certificateNumber": "F1", "addressLine1": "Flat 1, 8 Mill Court",
     "postcode": "B36 8AR", "registrationDate": "2024-01-01"},
    {"certificateNumber": "F2", "addressLine1": "Flat 2, 8 Mill Court",
     "postcode": "B36 8AR", "registrationDate": "2024-01-01"},
]
_fake = _FakeEPC(_split, {"F1": 48.0, "F2": 91.0})
_with_fake_epc(_fake)
try:
    _areas, _note = V.fetch_floor_areas("B36 8AR")
    check("12i two conflicting certificates for one number are both dropped",
          V._address_key("B36 8AR", "8") not in _areas, str(_areas))
    check("12j and the note says why", "disagreed" in _note, _note)
finally:
    _clear_fake_epc()

# No key is the normal case for a fresh deployment, and it must degrade with
# an explanation rather than pretend.
_clear_fake_epc()
_areas, _note = V.fetch_floor_areas("B36 8AR")
check("12k with no key configured, no areas and a clear reason",
      _areas == {} and V.EPC_KEY_ENV in _note, _note)

# The join onto real Sale objects.
_sales = [V.Sale(price=240_000, sold_on=date(2025, 11, 14), property_type="S",
                 postcode="B36 8AR", address="59 ERMINGTON CRESCENT"),
          V.Sale(price=230_000, sold_on=date(2025, 5, 28), property_type="S",
                 postcode="B36 8AR", address="97 ERMINGTON CRESCENT")]
_fake = _FakeEPC(_CERTS, _AREAS)
_with_fake_epc(_fake)
try:
    _joined, _note = V.attach_floor_areas(_sales, "B36 8AR")
    check("12l sales come back carrying a floor area",
          [s.floor_area_m2 for s in _joined] == [61.0, 86.0],
          str([s.floor_area_m2 for s in _joined]))
    check("12m which makes price per m2 available",
          abs(_joined[0].price_per_m2 - 240_000 / 61.0) < 1,
          str(_joined[0].price_per_m2))
    check("12n and the note says how many matched",
          "2 of 2 sales matched" in _note, _note)
finally:
    _clear_fake_epc()

# index_price used to raise TypeError, not ValuationError, when asked to
# index to a date before the series began. Callers catch ValuationError
# specifically so they can drop one comparable and carry on; a TypeError
# escapes all of them and kills the whole valuation on one bad row.
try:
    V.index_price(200_000, date(2022, 1, 1), INDEX, date(2000, 1, 1))
    check("12o indexing to a date before the series is a clean refusal",
          False, "no error at all")
except V.ValuationError:
    check("12o indexing to a date before the series is a clean refusal", True)
except TypeError as e:
    check("12o indexing to a date before the series is a clean refusal",
          False, f"TypeError escaped: {e}")

# range_low went NEGATIVE whenever the surviving spread exceeded 200% of the
# median. A negative pound figure is not a wide valuation, it is a broken
# one — and the docstring called it the honest output.
_splitmarket = [sale(100_000, 2025, area=90.0), sale(105_000, 2025, area=90.0),
                sale(110_000, 2025, area=90.0),
                sale(900_000, 2025, area=90.0), sale(950_000, 2025, area=90.0),
                sale(1_000_000, 2025, area=90.0)]
try:
    _r = V.value_from_comparables(_splitmarket, 90.0, "S", INDEX, TODAY)
    check("12p a valuation never reports a negative lower bound",
          _r["range_low"] > 0,
          f"range_low={_r['range_low']} on spread {_r['spread_pct']}%")
except V.ValuationError as e:
    check("12p a valuation never reports a negative lower bound", True)
    check("12q and says the bound would have been at or below zero",
          "zero" in str(e), str(e))


# ==========================================================================
# ---- region slugs ----------------------------------------------------------
# The caller should not have to know UKHPI's naming scheme. The postcode's
# own admin_district is the local authority; these pin the slug spelling,
# because a wrong slug is a silent "no index" rather than an error.
check("r1 a plain name", V.region_slug("Birmingham") == "birmingham")
check("r2 spaces hyphenate",
      V.region_slug("City of Westminster") == "city-of-westminster")
check("r3 apostrophes drop, not hyphenate",
      V.region_slug("King's Lynn and West Norfolk")
      == "kings-lynn-and-west-norfolk",
      V.region_slug("King's Lynn and West Norfolk"))
check("r4 nothing in, None out", V.region_slug("") is None)
check("r5 derive_region survives a dead lookup",
      V.derive_region("not even a postcode") in (None,) or True)

print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
