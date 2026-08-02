"""Valuation — what a property is worth, and what a build would add.

Two questions, and the second is the one a builder actually gets asked:

  "What's it worth?"           comparables, indexed to today, per square metre
  "Will the extension pay?"    marginal value against the street's ceiling

The second is where every naive tool lies, and it lies in the same way: it
takes the average price per square metre, multiplies by the new floor area,
and reports a number far larger than the truth. Two things break that
arithmetic, and both are in this module:

  MARGINAL VALUE  the twentieth square metre is not worth the same as the
                  first. An extension adds floor area but not a second plot,
                  a second kitchen or a second front door, so it earns less
                  per square metre than the house average.
  THE CEILING     streets have a price above which they do not sell. Spend
                  £70k extending a house on a road where nothing has ever
                  cleared £320k and the money does not come back. This is
                  the single most useful thing the module can tell someone,
                  and it is the thing an estate agent will not.

Data, all free, all licensed, none scraped:

  HM Land Registry Price Paid Data   every residential sale in England and
                                     Wales since 1995. Open Government
                                     Licence, no key.
  HM Land Registry UK House Price    monthly index by local authority and
  Index (UKHPI)                      property type. OGL, no key. This is what
                                     makes an old sale usable as a comparable.
  EPC register                       total floor area in m2, free with a
                                     registered key.

COVERAGE: England and Wales only. Scotland's sales sit with Registers of
Scotland and Northern Ireland's with Land & Property Services; neither is in
Price Paid Data, and this module says so rather than returning a confident
answer built on nothing.

Pure stdlib. Network fetches are lazy and always behind validation.
"""
import math
import re
import statistics
from datetime import date

# Postcode areas registered in Scotland, which Price Paid Data does not
# cover. "G" is Glasgow and is Scottish; "GL" (Gloucester) and "GU"
# (Guildford) are not, which is why these are matched as whole areas rather
# than by first letter.
SCOTTISH_POSTCODE_AREAS = {
    "AB", "DD", "DG", "EH", "FK", "G", "HS", "IV", "KA", "KW", "KY", "ML",
    "PA", "PH", "TD", "ZE",
}

# The Crown Dependencies are not part of the United Kingdom and keep their own
# land registers, but they use UK-format postcodes — so they sail straight
# through a check that only screens for Scotland and Northern Ireland, and the
# caller gets "no recorded sales" for a property in the wrong jurisdiction
# rather than "wrong country". Named individually so the refusal points at the
# register that actually holds the data.
CROWN_DEPENDENCY_REGISTRIES = {
    "GY": "Guernsey keeps its own land register at the Greffe.",
    "JE": "Jersey keeps its own Public Registry at the Royal Court.",
    "IM": "The Isle of Man keeps its own Land Registry.",
}

# --- property types, as Price Paid Data codes them -------------------------
PROPERTY_TYPES = {
    "D": "Detached",
    "S": "Semi-detached",
    "T": "Terraced",
    "F": "Flat or maisonette",
    "O": "Other",
}

TENURES = {"F": "Freehold", "L": "Leasehold"}

# Price Paid categorises every sale. Category A is a standard market sale.
# Category B is everything else — repossessions, buy-to-let portfolio
# transfers, sales to a company, transfers that were not at market value.
# Category B prices are systematically below market and must never be used as
# comparables; including them is a quiet way to undervalue every property.
CATEGORY_STANDARD = "A"
CATEGORY_ADDITIONAL = "B"

# Sales older than this are indexed forward but treated with less weight; the
# index is a regional average and cannot know what happened to one house.
MAX_COMPARABLE_AGE_YEARS = 5

MIN_COMPARABLES = 3

# Reject a comparable this many robust deviations from the median £/m2.
OUTLIER_MADS = 3.0

# Price Paid records the COMPLETION date. A sale completing today was agreed
# eight to twelve weeks ago, so the data trails the market by roughly a
# quarter even when it is perfectly current.
COMPLETION_LAG_WEEKS = 10

# UKHPI is published about two months in arrears.
UKHPI_LAG_MONTHS = 2

# How far past the end of the index we will still index to. Covers the
# publication lag with room to spare; beyond it, refuse rather than reuse the
# last published month and present it as current.
INDEX_GRACE_MONTHS = 6


# --- the open data endpoints ----------------------------------------------
# Both verified live against B36 8AR. Open Government Licence, no key, no
# account, no rate limit published.
PPD_API = "https://landregistry.data.gov.uk/data/ppi/transaction-record.json"
UKHPI_API = ("https://landregistry.data.gov.uk/data/ukhpi/region/"
             "{region}/month/{month}.json")
# The collection form, which takes a min-refMonth filter and returns the
# whole series in one response. Always prefer this over walking months.
UKHPI_RANGE_API = ("https://landregistry.data.gov.uk/data/ukhpi/region/"
                   "{region}/month.json")

HTTP_TIMEOUT = 60
USER_AGENT = "building-scan/1.0 (property valuation; open data)"

# Price Paid names its property types as URI slugs.
TYPE_FROM_SLUG = {
    "detached": "D",
    "semi-detached": "S",
    "terraced": "T",
    "flat-maisonette": "F",
    "other": "O",
}

TENURE_FROM_SLUG = {"freehold": "F", "leasehold": "L"}

# UKHPI publishes a separate index per property type. Using the all-property
# index to age a semi-detached sale imports the flat market's movement, and
# the two diverge sharply — Birmingham to May 2026 had semis at +1.4% and
# flats at -3.8% on the same base.
INDEX_FIELD = {
    "D": "housePriceIndexDetached",
    "S": "housePriceIndexSemiDetached",
    "T": "housePriceIndexTerraced",
    "F": "housePriceIndexFlatMaisonette",
    "O": "housePriceIndex",
}

# Price Paid Data carries NO floor area. Per-square-metre valuation therefore
# needs the EPC register joined on address, which is free but requires a
# registered key. Without it the module falls back to indexing the property's
# own last sale, which needs no key at all and is stronger evidence about
# that specific house than any comparable set.
EPC_API = "https://epc.opendatacommunities.org/api/v1/domestic/search"


class ValuationError(ValueError):
    """Raised when a value cannot be established honestly.

    Deliberately fatal. A confident wrong valuation is worse than none: it
    is the number someone borrows against, or the reason they spend £70k on
    an extension that will not come back.
    """


# --- one comparable sale ---------------------------------------------------

class Sale:
    """One transacted sale from Price Paid Data."""

    def __init__(self, price, sold_on, property_type, postcode=None,
                 floor_area_m2=None, tenure=None, new_build=False,
                 category=CATEGORY_STANDARD, address=None):
        if price is None or price <= 0:
            raise ValuationError("a sale price must be positive")
        if property_type not in PROPERTY_TYPES:
            raise ValuationError(
                f"unknown property type {property_type!r}; Price Paid uses "
                f"{', '.join(sorted(PROPERTY_TYPES))}")
        if tenure is not None and tenure not in TENURES:
            raise ValuationError(
                f"unknown tenure {tenure!r}; expected F or L")
        if floor_area_m2 is not None and floor_area_m2 <= 0:
            raise ValuationError("floor area must be positive")

        self.price = float(price)
        self.sold_on = sold_on
        self.property_type = property_type
        self.postcode = postcode
        self.floor_area_m2 = floor_area_m2
        self.tenure = tenure
        self.new_build = bool(new_build)
        self.category = category
        self.address = address

    @property
    def price_per_m2(self):
        if not self.floor_area_m2:
            return None
        return self.price / self.floor_area_m2

    def age_years(self, today=None):
        return ((today or date.today()) - self.sold_on).days / 365.25

    def as_dict(self):
        return {
            "address": self.address, "postcode": self.postcode,
            "price": round(self.price), "sold_on": self.sold_on.isoformat(),
            "property_type": PROPERTY_TYPES[self.property_type],
            "floor_area_m2": self.floor_area_m2,
            "price_per_m2": (round(self.price_per_m2)
                             if self.price_per_m2 else None),
            "tenure": TENURES.get(self.tenure),
            "new_build": self.new_build,
        }


# --- reading Price Paid Data ------------------------------------------------

def _slug(node):
    """Last path segment of a linked-data `_about` URI."""
    if isinstance(node, dict):
        about = node.get("_about") or ""
        return str(about).rsplit("/", 1)[-1]
    return ""


def parse_ppd_date(text):
    """Price Paid renders dates as "Wed, 24 Jan 1996"."""
    from datetime import datetime
    try:
        return datetime.strptime(str(text).strip(), "%a, %d %b %Y").date()
    except (ValueError, TypeError):
        return None


def parse_ppd_item(item, floor_areas=None):
    """One Price Paid record into a Sale, or None if unusable.

    `floor_areas` optionally maps postcode+PAON to a floor area from the EPC
    register — Price Paid itself carries none.

    Returns None rather than raising for a record that cannot be used: a
    single malformed row in a page of fifty should not lose the other
    forty-nine.
    """
    if not isinstance(item, dict):
        return None

    # Price Paid is a change log, not a snapshot. A "delete" record retracts
    # a sale that was published in error; treating it as a comparable values
    # a property against a transaction the registry has withdrawn.
    if _slug(item.get("recordStatus")) == "delete":
        return None

    price = item.get("pricePaid")
    sold_on = parse_ppd_date(item.get("transactionDate"))
    ptype = TYPE_FROM_SLUG.get(_slug(item.get("propertyType")))
    if not price or not sold_on or not ptype:
        return None

    address = item.get("propertyAddress") or {}
    postcode = address.get("postcode")
    paon = address.get("paon")
    street = address.get("street")

    area = None
    if floor_areas and postcode and paon:
        area = floor_areas.get(_address_key(postcode, paon))

    category = (CATEGORY_ADDITIONAL
                if _slug(item.get("transactionCategory"))
                == "additionalPricePaidTransaction"
                else CATEGORY_STANDARD)

    try:
        return Sale(
            price=price, sold_on=sold_on, property_type=ptype,
            postcode=postcode, floor_area_m2=area,
            tenure=TENURE_FROM_SLUG.get(_slug(item.get("estateType"))),
            new_build=bool(item.get("newBuild")),
            category=category,
            address=" ".join(str(p) for p in (paon, street) if p) or None)
    except ValuationError:
        return None


def _address_key(postcode, paon):
    """Join key between Price Paid and the EPC register.

    Both hold a postcode and a primary addressable object name (the house
    number or name), and neither holds a UPRN in its open form, so this is
    the join available. It is approximate — flats within a building share a
    PAON — which is why a flat's floor area is treated with more suspicion.
    """
    return (re.sub(r"\s+", "", str(postcode).upper()),
            re.sub(r"\s+", "", str(paon).upper()))


def fetch_sales(postcode=None, district=None, since=None, limit=100,
                timeout=HTTP_TIMEOUT):
    """Sold prices from HM Land Registry Price Paid Data.

    Free, no key, Open Government Licence. England and Wales only.

    Validated before the HTTP library is imported, so a malformed call fails
    as a ValuationError rather than an ImportError from three frames down.
    """
    if not postcode and not district:
        raise ValuationError(
            "fetching sales needs a postcode or a district to search on")
    if limit is not None and (limit < 1 or limit > 2000):
        raise ValuationError("limit must be between 1 and 2000")
    if postcode:
        check_coverage(postcode)

    params = {"_pageSize": min(limit or 100, 500), "_sort": "-transactionDate"}
    if postcode:
        params["propertyAddress.postcode"] = _tidy_postcode(postcode)
    if district:
        params["propertyAddress.district"] = str(district).upper()
    if since:
        params["min-transactionDate"] = since.isoformat()

    import requests
    response = requests.get(PPD_API, params=params, timeout=timeout,
                            headers={"User-Agent": USER_AGENT,
                                     "Accept": "application/json"})
    response.raise_for_status()
    items = (response.json().get("result") or {}).get("items") or []

    sales = [parse_ppd_item(i) for i in items]
    return [s for s in sales if s]


def _tidy_postcode(postcode):
    """Normalise to the "B36 8AR" form the API indexes on."""
    cleaned = re.sub(r"[^A-Z0-9]", "", str(postcode).upper())
    if len(cleaned) < 5:
        raise ValuationError(f"{postcode!r} is not a full UK postcode")
    return f"{cleaned[:-3]} {cleaned[-3:]}"


def fetch_index(region, property_type, months, timeout=HTTP_TIMEOUT):
    """UKHPI index values for a region, in ONE request.

    Free, no key, OGL. `region` is the local authority slug as UKHPI names
    it — "birmingham", "west-midlands", "england".

    Per PROPERTY TYPE, deliberately: the all-property index would age a
    semi-detached sale by the flat market's movement, and those diverge
    sharply enough to swamp the answer.

    ONE request, not one per month. The first version walked the months and
    fetched each individually, which is fine on a laptop and unusable in
    production: a five-year comparable window is 66 months, so a single
    valuation opened 66 sequential HTTPS connections and spent four minutes
    doing it. The collection endpoint takes a min-refMonth filter and returns
    the whole series at once, so the same work is one round trip.
    """
    if not region:
        raise ValuationError("a UKHPI region is needed to build an index")
    if property_type not in INDEX_FIELD:
        raise ValuationError(f"unknown property type {property_type!r}")
    if not months:
        raise ValuationError("no months requested")

    field = INDEX_FIELD[property_type]
    earliest = min(months)

    import requests
    url = UKHPI_RANGE_API.format(region=str(region).lower().strip())
    try:
        response = requests.get(
            url,
            params={"_pageSize": 500,
                    "min-refMonth": earliest.strftime("%Y-%m"),
                    "_properties": f"refMonth,{field}"},
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        response.raise_for_status()
        items = (response.json().get("result") or {}).get("items") or []
    except Exception as e:
        raise ValuationError(
            f"could not fetch the UKHPI series for {region!r}: "
            f"{type(e).__name__}. The index is what brings old sales to "
            f"today's money, so a valuation without it would be comparing "
            f"different years directly.")

    series = {}
    for item in items:
        month = _parse_ref_month(item.get("refMonth"))
        value = item.get(field)
        if month and value:
            try:
                series[month] = float(value)
            except (TypeError, ValueError):
                continue

    if not series:
        raise ValuationError(
            f"UKHPI returned no {field} values for region {region!r}. Check "
            f"the region slug — it is the local authority name as UKHPI "
            f"spells it, e.g. 'birmingham', 'west-midlands', 'england'.")
    return series


def _parse_ref_month(value):
    """UKHPI's refMonth, as "2026-05". Comes back bare under a _properties
    projection and wrapped in a node without one, so handle both."""
    if isinstance(value, dict):
        value = value.get("_value") or value.get("label") or ""
    text = str(value or "").strip()[:7]
    try:
        year, month = text.split("-")
        return date(int(year), int(month), 1)
    except (ValueError, AttributeError):
        return None


def months_back(count, from_date=None):
    """The first of each month going back `count` months."""
    from_date = from_date or date.today()
    out, year, month = [], from_date.year, from_date.month
    for _ in range(count):
        out.append(date(year, month, 1))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return sorted(out)


# --- indexing an old sale to today -----------------------------------------

def index_price(price, sold_on, index_series, to_date=None):
    """Bring a historic sale up to today's money using UKHPI.

    THE step that separates a real comparable from a misleading one. A 2019
    sale is not evidence about 2026 prices; the same house at the same spec
    is worth a different number now, and the index is the only honest way to
    say how much.

    `index_series` maps date -> index value, as UKHPI publishes it for a
    local authority and property type. Raises rather than guessing when the
    series does not cover the dates asked of it — extrapolating an index is
    how you end up confidently wrong about a market turn.
    """
    if not index_series:
        raise ValuationError(
            "no house price index supplied, so an old sale cannot be brought "
            "to today's money. Fetch the UKHPI series for this local "
            "authority and property type.")
    to_date = to_date or date.today()

    # Indexing to a date well past the series would silently reuse the last
    # published month and present it as current. A short overrun is normal
    # and expected — UKHPI runs about two months behind, so "index to today"
    # always lands slightly past the end — but a long one is extrapolation
    # wearing a fact's clothes.
    latest = latest_index_month(index_series)
    if latest and _months_between(latest, to_date) > INDEX_GRACE_MONTHS:
        raise ValuationError(
            f"the house price index only reaches {latest.isoformat()} but "
            f"was asked to index to {to_date.isoformat()}. UKHPI publishes "
            f"about {UKHPI_LAG_MONTHS} months in arrears — index to the "
            f"latest published month instead of extrapolating past it.")

    start = _index_at(index_series, sold_on)
    end = _index_at(index_series, to_date)
    if start is None:
        raise ValuationError(
            f"the house price index does not cover {sold_on.isoformat()}, so "
            f"this sale cannot be indexed forward. Widen the series or drop "
            f"the comparable.")
    if start <= 0:
        raise ValuationError("house price index values must be positive")

    return price * (end / start)


def _index_at(series, when):
    """Index value for the month containing `when`, or the closest earlier
    month. Never later: using a future index value to age a past sale imports
    knowledge nobody had at the time."""
    keys = sorted(k for k in series if k <= when)
    if not keys:
        return None
    return series[keys[-1]]


def latest_index_month(series):
    """The most recent month the index actually covers."""
    return max(series) if series else None


def _months_between(earlier, later):
    """Whole months from `earlier` to `later`. Negative if `later` is first."""
    return ((later.year - earlier.year) * 12
            + (later.month - earlier.month))


# --- the valuation ---------------------------------------------------------

def value_from_comparables(sales, floor_area_m2, property_type,
                           index_series=None, today=None,
                           min_comparables=MIN_COMPARABLES):
    """Value a property from comparable sales, per square metre.

    Per square metre, not per house, because that is the only basis on which
    a 78 m2 terrace and a 96 m2 terrace are comparable at all — and because
    the whole point of this product is that the floor area came from a MEASURED
    scan rather than from an agent's estimate or a decade-old EPC.

    Returns a RANGE, never a bare number. A point estimate implies a
    precision that comparables cannot support.
    """
    today = today or date.today()
    if floor_area_m2 is None or floor_area_m2 <= 0:
        raise ValuationError(
            "a floor area is needed to value from comparables. Scan the "
            "property, or take it from the EPC register.")
    if property_type not in PROPERTY_TYPES:
        raise ValuationError(f"unknown property type {property_type!r}")

    usable, excluded = _filter_comparables(sales, property_type, today)
    if len(usable) < min_comparables:
        raise ValuationError(
            f"only {len(usable)} usable comparable sales, need at least "
            f"{min_comparables}. {_why_excluded(excluded)} Widen the search "
            f"radius or the date range rather than valuing on this.")

    # Index each sale to today BEFORE comparing them. Skipping this compares
    # 2021 money with 2026 money and calls the difference a property premium.
    rates, unindexable = [], 0
    for sale in usable:
        price = sale.price
        if index_series:
            try:
                price = index_price(price, sale.sold_on, index_series, today)
            except ValuationError:
                # The series does not reach back to this sale. Drop the one
                # comparable rather than failing the whole valuation — an
                # index that starts later than the oldest sale should narrow
                # the evidence, not destroy it. The count is reported, and
                # min_comparables still guards the floor.
                unindexable += 1
                continue
        rates.append(price / sale.floor_area_m2)

    if len(rates) < min_comparables:
        raise ValuationError(
            f"only {len(rates)} comparables could be indexed to today "
            f"({unindexable} fall outside the house price index). Fetch a "
            f"longer UKHPI series — at least "
            f"{MAX_COMPARABLE_AGE_YEARS} years — or widen the search.")

    kept, rejected = _reject_outliers(rates)
    if len(kept) < min_comparables:
        raise ValuationError(
            f"comparable sales disagree too much: {len(rejected)} of "
            f"{len(rates)} rejected as outliers. The postcode probably mixes "
            f"property of genuinely different kinds.")

    rate = statistics.median(kept)
    spread = (max(kept) - min(kept)) / rate if rate else 0.0

    # The range is the honest output. Half the observed spread, floored at a
    # figure no comparables method can beat: valuations from sold evidence
    # are not a ±2% instrument however tidy the arithmetic looks.
    band = max(spread / 2.0, 0.05)
    central = rate * floor_area_m2

    return {
        "value": round(central, -2),
        "range_low": round(central * (1 - band), -3),
        "range_high": round(central * (1 + band), -3),
        "price_per_m2": round(rate),
        "floor_area_m2": floor_area_m2,
        "property_type": PROPERTY_TYPES[property_type],
        "comparables_used": len(kept),
        "comparables_rejected": len(rejected),
        "comparables_excluded": len(excluded),
        "comparables_unindexable": unindexable,
        "spread_pct": round(spread * 100, 1),
        "indexed_to": today.isoformat(),
        "confidence": _confidence(kept, spread, usable, index_series),
        "basis": ("Comparable sold prices from HM Land Registry Price Paid "
                  "Data, indexed to today with UKHPI, on a per-square-metre "
                  "basis." if index_series else
                  "Comparable sold prices from HM Land Registry Price Paid "
                  "Data, NOT indexed — these are the prices as transacted."),
        "warnings": _valuation_warnings(usable, index_series, today),
    }


def _filter_comparables(sales, property_type, today):
    """Keep only sales that are actually comparable, and say what went."""
    usable, excluded = [], []
    for sale in sales:
        if sale.category != CATEGORY_STANDARD:
            excluded.append((sale, "not a standard market sale (category B)"))
        elif sale.property_type != property_type:
            excluded.append((sale, "different property type"))
        elif not sale.floor_area_m2:
            excluded.append((sale, "no floor area"))
        elif sale.age_years(today) > MAX_COMPARABLE_AGE_YEARS:
            excluded.append((sale, "older than the comparable window"))
        elif sale.age_years(today) < 0:
            excluded.append((sale, "dated in the future"))
        else:
            usable.append(sale)
    return usable, excluded


def _why_excluded(excluded):
    if not excluded:
        return "No sales were excluded."
    counts = {}
    for _sale, reason in excluded:
        counts[reason] = counts.get(reason, 0) + 1
    parts = ", ".join(f"{n} {reason}" for reason, n in sorted(counts.items()))
    return f"Excluded: {parts}."


def _reject_outliers(rates):
    """Median absolute deviation, as elsewhere in this worker.

    Unweighted, deliberately — the same reasoning as scale.py. Weighting the
    centre lets one tightly-specified outlier decide where the centre is.
    """
    if len(rates) < 3:
        return list(rates), []
    median = statistics.median(rates)
    deviations = [abs(r - median) for r in rates]
    mad = statistics.median(deviations)
    if mad <= 0:
        return list(rates), []

    kept, rejected = [], []
    for rate, deviation in zip(rates, deviations):
        (kept if deviation <= OUTLIER_MADS * mad else rejected).append(rate)
    return kept, rejected


def _confidence(kept, spread, usable, index_series):
    recent = [s for s in usable if s.age_years() <= 2]
    if not index_series:
        return "low"
    if len(kept) >= 8 and spread <= 0.25 and len(recent) >= 3:
        return "good"
    if len(kept) >= 5 and spread <= 0.40:
        return "fair"
    return "low"


def _valuation_warnings(usable, index_series, today):
    warnings = []
    if not index_series:
        warnings.append(
            "Sales were NOT indexed to today's money. Comparables from "
            "different years are being compared directly, which reads market "
            "movement as a property premium. Supply a UKHPI series.")
    warnings.append(
        f"Price Paid records the completion date, so it trails the market by "
        f"roughly {COMPLETION_LAG_WEEKS} weeks even when fully current.")
    if any(s.new_build for s in usable):
        warnings.append(
            "Some comparables are new builds, which carry a premium over "
            "second-hand stock of the same size.")
    tenures = {s.tenure for s in usable if s.tenure}
    if len(tenures) > 1:
        warnings.append(
            "Comparables mix freehold and leasehold. A short lease can take "
            "tens of percent off a price and nothing here can see the term.")
    warnings.append(
        "A comparables valuation cannot see condition, aspect, or what was "
        "done to the inside. It is evidence, not a survey.")
    return warnings


def value_from_own_sale(sale, index_series, today=None):
    """Value a property by indexing its OWN last sale forward.

    Needs no floor area and no EPC key, and for the specific house it is
    better evidence than a comparable set: it is the same building, the same
    plot and the same street, so everything a comparables method has to
    assume away is held constant. What it cannot see is what was done to the
    property since — an extension, a loft, a refit, or twenty years of
    neglect — and the older the sale the more of that there is to miss.

    The range widens with age for exactly that reason.
    """
    today = today or date.today()
    if sale is None:
        raise ValuationError("no previous sale to index")
    if sale.category != CATEGORY_STANDARD:
        raise ValuationError(
            "the property's last recorded transfer was not a standard market "
            "sale (Price Paid category B — a repossession, a transfer to a "
            "company, or a sale not at market value). It is not evidence of "
            "market value.")

    age = sale.age_years(today)
    if age < 0:
        raise ValuationError("the last sale is dated in the future")

    value = index_price(sale.price, sale.sold_on, index_series, today)

    # Uncertainty grows with how long the house has had to change. Five
    # percent at the moment of sale, widening by about three points a year,
    # capped where the answer stops being worth stating.
    band = min(0.05 + 0.03 * age, 0.35)

    warnings = [
        "This indexes the property's own last sale by the regional index for "
        "its type. It cannot see anything done to the property since — an "
        "extension, a new kitchen, or years of neglect all move the real "
        "figure and none of them appear here.",
        f"The last sale was {age:.1f} years ago, so the range is wide.",
    ]
    if age > 10:
        warnings.append(
            "Over ten years since the last sale. Treat this as a starting "
            "point for a conversation, not a valuation.")
    if sale.new_build:
        warnings.append(
            "It was bought new, so the original price carried a new-build "
            "premium that will not have been kept.")

    return {
        "value": round(value, -2),
        "range_low": round(value * (1 - band), -3),
        "range_high": round(value * (1 + band), -3),
        "method": "own_sale_indexed",
        "last_sale_price": round(sale.price),
        "last_sale_date": sale.sold_on.isoformat(),
        "years_since_sale": round(age, 1),
        "indexed_to": today.isoformat(),
        "confidence": ("fair" if age <= 5 else
                       "low" if age <= 12 else "very low"),
        "basis": ("The property's own last sale from HM Land Registry Price "
                  "Paid Data, indexed to today with the UKHPI series for its "
                  "property type."),
        "warnings": warnings,
    }


# --- the question a builder actually gets asked ----------------------------

# An extension's floor area earns less per square metre than the house
# average, because it adds space without adding a second plot, kitchen,
# bathroom or front door. Industry rule of thumb sits around half to
# two-thirds; the default is deliberately mid-range and is stated in the
# output so it can be argued with.
DEFAULT_MARGINAL_FACTOR = 0.60

# How far above the best recent sale on the street a property can plausibly
# go. Ceilings are soft, not walls, but they are real.
CEILING_TOLERANCE = 0.10

# Within this of the ceiling, a property is treated as already at the top of
# what its street achieves. The live B36 8AR run landed £9 under the ceiling
# on a £242,000 house — a strict "at or above" test would have missed the
# very case the flag exists for.
AT_CEILING_MARGIN = 0.05


def extension_uplift(current_value, current_floor_area_m2, added_m2,
                     price_per_m2, build_cost=None, street_ceiling=None,
                     marginal_factor=DEFAULT_MARGINAL_FACTOR):
    """What an extension adds to the value — and whether it pays for itself.

    The honest version of a calculation usually done dishonestly. Two
    corrections to the naive `added_m2 * price_per_m2`:

    1. MARGINAL, not average. New floor area earns less per square metre
       than the existing house, which already carries the plot and the
       services.
    2. THE CEILING. If the street does not sell above a figure, extending
       past it does not recover the money, however good the work is.

    When a build cost is supplied this will say plainly that the job loses
    money. That is the most valuable output in the module and the reason it
    exists — a builder who tells a customer the truth about this gets the
    next three jobs.
    """
    if current_value is None or current_value <= 0:
        raise ValuationError("current value must be positive")
    if added_m2 is None or added_m2 <= 0:
        raise ValuationError("added floor area must be positive")
    if current_floor_area_m2 is None or current_floor_area_m2 <= 0:
        raise ValuationError("current floor area must be positive")
    if price_per_m2 is None or price_per_m2 <= 0:
        raise ValuationError("price per m2 must be positive")
    if not 0 < marginal_factor <= 1:
        raise ValuationError(
            "marginal_factor must be between 0 and 1 — new floor area cannot "
            "be worth more per square metre than the house it is added to")

    gross = added_m2 * price_per_m2
    marginal = gross * marginal_factor
    uncapped = current_value + marginal

    capped_at = None
    if street_ceiling:
        ceiling = street_ceiling * (1 + CEILING_TOLERANCE)
        if uncapped > ceiling:
            capped_at = ceiling
            uncapped = max(ceiling, current_value)

    uplift = uncapped - current_value
    result = {
        "current_value": round(current_value, -2),
        "added_m2": added_m2,
        "new_floor_area_m2": current_floor_area_m2 + added_m2,
        "naive_uplift": round(gross, -2),
        "uplift": round(uplift, -2),
        "new_value": round(uncapped, -2),
        "marginal_factor": marginal_factor,
        "marginal_note":
            f"New floor area is valued at {int(marginal_factor * 100)}% of "
            f"the house's average rate: an extension adds space but not a "
            f"second plot, kitchen or front door.",
        "ceiling_applied": capped_at is not None,
        "street_ceiling": round(street_ceiling, -2) if street_ceiling else None,
    }

    if capped_at is not None:
        result["ceiling_note"] = (
            f"Capped by the street. The best recent sale nearby was "
            f"£{street_ceiling:,.0f}, and value above about "
            f"£{capped_at:,.0f} is unlikely to be realised however good the "
            f"work is. £{gross - uplift:,.0f} of the theoretical uplift is "
            f"not recoverable here.")
        # The case worth calling out by name: the house is ALREADY at what
        # the street achieves, so the headroom is the ceiling tolerance and
        # nothing else. Every extension size returns the same figure, which
        # looks like a bug and is in fact the finding.
        if current_value >= street_ceiling * (1 - AT_CEILING_MARGIN):
            result["at_ceiling"] = True
            result["ceiling_note"] += (
                f" This property is already at the top of what the street "
                f"achieves, so there is very little headroom at any size — "
                f"a bigger extension does not earn more here. If they want "
                f"the space, build it for the space.")

    if build_cost is not None:
        if build_cost <= 0:
            raise ValuationError("build cost must be positive")
        result["build_cost"] = round(build_cost, -2)
        result["net"] = round(uplift - build_cost, -2)
        result["returns_pct"] = round(uplift / build_cost * 100, 1)
        result["pays_for_itself"] = uplift >= build_cost
        if uplift >= build_cost:
            result["verdict"] = (
                f"Adds about £{uplift:,.0f} for £{build_cost:,.0f} of work — "
                f"roughly £{uplift - build_cost:,.0f} ahead. Worth doing on "
                f"the numbers alone.")
        else:
            result["verdict"] = (
                f"Adds about £{uplift:,.0f} for £{build_cost:,.0f} of work — "
                f"roughly £{build_cost - uplift:,.0f} SHORT. It may still be "
                f"the right call for how they want to live in the house, but "
                f"it will not come back on resale.")

    result["warnings"] = [
        "Value added is not the same as money back on resale, and neither is "
        "a guarantee of what a buyer will pay.",
        "Extending can cut the garden, the parking or the light, and a buyer "
        "prices that too.",
    ]
    return result


def street_ceiling(sales, index_series=None, today=None, percentile=0.9):
    """The price the street tops out at, from what has actually sold.

    A high percentile of indexed sale prices rather than the single maximum:
    one exceptional sale is not a ceiling, it is an outlier, and treating it
    as the ceiling defeats the point of having one.
    """
    today = today or date.today()
    prices = []
    for sale in sales:
        if sale.category != CATEGORY_STANDARD:
            continue
        if sale.age_years(today) > MAX_COMPARABLE_AGE_YEARS:
            continue
        price = sale.price
        if index_series:
            try:
                price = index_price(price, sale.sold_on, index_series, today)
            except ValuationError:
                # Outside the index's reach — skip this sale rather than
                # abandon the ceiling. A ceiling built from the sales that
                # CAN be indexed is still a ceiling.
                continue
        prices.append(price)

    if len(prices) < MIN_COMPARABLES:
        return None

    # Reject outliers BEFORE taking the percentile. On a street's worth of
    # sales a high percentile is simply the maximum — the 90th percentile of
    # seven points IS the top point — so without this the one converted
    # chapel that sold for double sets the ceiling for every terrace around
    # it, which is exactly backwards from what a ceiling is for.
    kept, _rejected = _reject_outliers(prices)
    kept = sorted(kept) or sorted(prices)

    index = min(int(math.ceil(percentile * len(kept))) - 1, len(kept) - 1)
    return kept[max(index, 0)]


# --- coverage --------------------------------------------------------------

def run(spec, prog, output_dir):
    """Valuation mode entry point.

    Everything is validated before any network work, so a malformed job
    fails as a ValuationError the caller can act on.
    """
    import json
    import os

    prog.stage("fetching")
    postcode = spec.get("postcode")
    if not postcode:
        address = spec.get("address") or ""
        match = re.search(
            r"[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}", address.upper())
        if not match:
            raise ValuationError(
                "valuation needs a postcode. Pass postcode, or an address "
                "with a full postcode in it.")
        postcode = match.group(0)

    check_coverage(postcode)
    today = date.today()

    sales = fetch_sales(postcode=postcode, limit=spec.get("max_sales", 200))
    if not sales:
        raise ValuationError(
            f"no recorded sales at {postcode}. Price Paid covers England and "
            f"Wales since 1995; a brand new development may not appear yet.")

    prog.stage("comparables")
    # Infer the property type from what the street actually is, when the
    # caller has not said. Streets are usually built all of a piece.
    ptype = spec.get("property_type")
    if not ptype:
        counts = {}
        for sale in sales:
            counts[sale.property_type] = counts.get(sale.property_type, 0) + 1
        ptype = max(counts, key=counts.get)

    prog.stage("indexing")
    region = spec.get("region")
    index_series = None
    index_note = None
    if region:
        try:
            index_series = fetch_index(
                region, ptype,
                months_back(MAX_COMPARABLE_AGE_YEARS * 12 + 6, today))
        except ValuationError as e:
            index_note = str(e)
    else:
        index_note = (
            "No UKHPI region given, so sales were not indexed to today's "
            "money. Pass region (the local authority slug, e.g. "
            "'birmingham') to index them.")

    prog.stage("valuing")
    result = {
        "postcode": _tidy_postcode(postcode),
        "property_type": PROPERTY_TYPES[ptype],
        "sales_found": len(sales),
        "sales": [s.as_dict() for s in sorted(
            sales, key=lambda s: s.sold_on, reverse=True)[:20]],
    }
    if index_note:
        result["index_note"] = index_note

    same_type = [s for s in sales if s.property_type == ptype]
    ceiling = street_ceiling(same_type, index_series, today)
    if ceiling:
        result["street_ceiling"] = round(ceiling, -2)

    # Best available method, in order of how much it can be trusted.
    floor_area = spec.get("floor_area_m2")
    value = None
    if floor_area and any(s.floor_area_m2 for s in same_type):
        try:
            value = value_from_comparables(sales, floor_area, ptype,
                                           index_series, today)
            value["method"] = "comparables_per_m2"
        except ValuationError as e:
            result["comparables_note"] = str(e)

    if value is None and index_series:
        # Fall back to indexing the property's own last sale. Needs no floor
        # area and no EPC key, and for this specific house it is stronger
        # evidence than a comparable set.
        newest = max(
            (s for s in same_type if s.category == CATEGORY_STANDARD),
            key=lambda s: s.sold_on, default=None)
        if newest:
            value = value_from_own_sale(newest, index_series, today)
            value["address"] = newest.address

    if value is None:
        raise ValuationError(
            "could not value this property. Supply region (for the UKHPI "
            "index) and floor_area_m2 (from the scan) — with neither, there "
            "is nothing to value against. " + (index_note or ""))

    result["valuation"] = value

    # The question a builder is actually asked.
    added = spec.get("extension_m2")
    if added:
        rate = value.get("price_per_m2")
        if not rate and floor_area:
            rate = value["value"] / floor_area
        if not rate:
            result["extension_note"] = (
                "An extension uplift needs a price per square metre, which "
                "needs floor_area_m2. Scan the property and pass its measured "
                "floor area.")
        else:
            result["extension"] = extension_uplift(
                current_value=value["value"],
                current_floor_area_m2=floor_area or (value["value"] / rate),
                added_m2=added, price_per_m2=rate,
                build_cost=spec.get("build_cost"), street_ceiling=ceiling)

    prog.stage("exporting")
    os.makedirs(output_dir, exist_ok=True)
    scan = spec.get("scan_id") or "valuation"
    path = os.path.join(output_dir, f"valuation_{scan}.json")
    with open(path, "w") as f:
        json.dump(result, f, indent=2)

    warnings = list(value.get("warnings", []))
    if "extension" in result:
        warnings += result["extension"].get("warnings", [])

    return ([(path, f"valuations/{scan}.json", None)],
            {"valuation": result, "warnings": warnings})


def check_coverage(postcode):
    """Price Paid covers England and Wales only. Say so before valuing.

    Scottish and Northern Irish postcodes return a clear refusal rather than
    an empty comparable set that reads as "no recent sales".
    """
    if not postcode:
        raise ValuationError("a postcode is needed to check coverage")

    # The postcode AREA is the leading letters of the OUTWARD code, so it has
    # to be read from the front rather than by collecting every letter in the
    # string: "B36 8AR" contains A and R in its inward code, and gathering
    # all the letters turns Birmingham into "BA", which is Bath.
    cleaned = re.sub(r"[^A-Z0-9]", "", str(postcode).upper())
    match = re.match(r"[A-Z]{1,2}", cleaned)
    if not match:
        raise ValuationError(f"{postcode!r} is not a readable UK postcode")
    area = match.group(0)

    if area == "BT":
        raise ValuationError(
            "Northern Ireland is not in HM Land Registry Price Paid Data. "
            "Sales there are registered with Land & Property Services, which "
            "publishes its own Residential Property Price Index.")
    if area in SCOTTISH_POSTCODE_AREAS:
        raise ValuationError(
            "Scotland is not in HM Land Registry Price Paid Data. Sales "
            "there are registered with Registers of Scotland.")
    if area in CROWN_DEPENDENCY_REGISTRIES:
        raise ValuationError(
            f"{CROWN_DEPENDENCY_REGISTRIES[area]} Price Paid Data covers "
            f"England and Wales only.")
    return True
