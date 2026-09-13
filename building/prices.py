"""Material prices — three quality tiers, multiple sources, weekly refresh.

WHY THIS DOES NOT SCRAPE MERCHANT WEBSITES, stated once so the design makes
sense. Every major UK merchant prohibits it in their terms; UK law also
grants a sui generis DATABASE RIGHT over a compiled catalogue, so lifting
one wholesale infringes even where an individual price is just a fact. For
a product intended to be sold, that is a live liability rather than a
theoretical one.

It is also the WRONG DATA. A scraped shelf price is retail list. Trade
pricing is account-specific and confidential, routinely 15-40% below it,
and every builder's number differs. Scraping would produce a large, illegal
dataset of prices nobody in the trade actually pays.

What beats it, in order of how much a price should be trusted:

  INVOICE   what this user actually paid, from their own delivery notes.
            Legally theirs, specific to their account, and it compounds —
            nobody can buy a corpus of real paid prices.
  QUOTE     a merchant's response to an RFQ for this basket.
  PUBLISHED affiliate and partner product feeds, which merchants license
            deliberately for exactly this use.
  INDEX     DBT Construction Material Price Indices — free, official,
            monthly, with commodity series going back decades. Not a price,
            but the best available answer to "which way is this moving".

The index is also what makes forecasting possible at all. A scrape gives a
snapshot of today; the index gives thirty years of movement to project from.
"""
import math
from datetime import date, timedelta

# --- quality tiers ---------------------------------------------------------
ECONOMY = "economy"
STANDARD = "standard"
PREMIUM = "premium"
TIERS = (ECONOMY, STANDARD, PREMIUM)

TIER_LABELS = {
    ECONOMY: "Budget — meets spec, shortest life, trade-off on finish",
    STANDARD: "Standard — what most jobs are built with",
    PREMIUM: "Premium — longest life or best finish, specify deliberately",
}

# --- source trust ----------------------------------------------------------
INVOICE = "invoice"
QUOTE = "quote"
PUBLISHED = "published"
INDEX = "index"

# Higher wins when sources disagree. A price the user actually paid beats a
# published list price every time, because the list price is not what they
# would be charged.
SOURCE_TRUST = {INVOICE: 100, QUOTE: 70, PUBLISHED: 40, INDEX: 10}

# A price loses relevance with age. Materials moved violently through the
# 2021-23 period, so a six-month-old invoice is history, not a quote.
HALF_LIFE_DAYS = 120
STALE_DAYS = 365

# How far a price may be dated into the future before it stops being clock
# drift and starts being bad data. Timezones alone account for a day.
CLOCK_SKEW_DAYS = 2

REFRESH_INTERVAL_DAYS = 7

# --- the catalogue ---------------------------------------------------------
# Real UK tiering: the same job element built three ways. Tier is about
# specification, not just price — a builder choosing "economy" is accepting
# a shorter life or a plainer finish, and should be told which.
CATALOGUE = {
    "roof_covering": {
        "unit": "each",
        # covers_per_m2 is what makes the three tiers comparable at all.
        # They are different tile types laying 10.5, 60 and 20 to the
        # square metre (docs/ESTIMATING_RATES.md gauges), so a per-tile
        # price comparison inverts reality: a plain tile at £0.55 looks
        # cheaper than an interlocking one at £1.20, but a square metre
        # of plain tile costs nearly three times as much.
        ECONOMY:  {"spec": "Concrete interlocking tile", "life_years": 40,
                   "covers_per_m2": 10.5},
        STANDARD: {"spec": "Concrete plain tile", "life_years": 60,
                   "covers_per_m2": 60.0},
        PREMIUM:  {"spec": "Natural slate", "life_years": 100,
                   "covers_per_m2": 20.0},
        "index_series": "roofing_tiles_slate",
    },
    "battens": {
        "unit": "m",
        ECONOMY:  {"spec": "Untreated batten — NOT graded for roofing"},
        STANDARD: {"spec": "BS 5534 graded treated batten"},
        PREMIUM:  {"spec": "BS 5534 graded, factory-marked"},
        "index_series": "sawn_timber",
        # Untreated batten is a false economy and a genuine failure mode.
        "economy_warning":
            "Ungraded batten does not meet BS 5534 and is a common cause of "
            "premature roof failure. The saving is a few pounds a roof.",
    },
    "membrane": {
        "unit": "m2",
        ECONOMY:  {"spec": "Basic bitumen felt"},
        STANDARD: {"spec": "Breathable membrane"},
        PREMIUM:  {"spec": "High-performance air-open breather"},
        "index_series": "other_materials",
    },
    "plasterboard": {
        "unit": "m2",
        ECONOMY:  {"spec": "9.5mm standard board"},
        STANDARD: {"spec": "12.5mm standard board"},
        PREMIUM:  {"spec": "12.5mm moisture or fire board"},
        "index_series": "plaster_plasterboard",
    },
    "insulation": {
        "unit": "m2",
        ECONOMY:  {"spec": "Mineral wool quilt"},
        STANDARD: {"spec": "PIR rigid board"},
        PREMIUM:  {"spec": "Phenolic board — thinnest for the U-value"},
        "index_series": "insulating_materials",
    },
    "structural_timber": {
        "unit": "m",
        ECONOMY:  {"spec": "C16 softwood"},
        STANDARD: {"spec": "C24 softwood"},
        PREMIUM:  {"spec": "Engineered joist"},
        "index_series": "sawn_timber",
    },
    "bricks": {
        "unit": "each",
        ECONOMY:  {"spec": "Common brick"},
        STANDARD: {"spec": "Facing brick"},
        PREMIUM:  {"spec": "Handmade or reclaimed facing"},
        "index_series": "bricks_blocks",
    },
    "guttering": {
        "unit": "m",
        ECONOMY:  {"spec": "Half-round uPVC"},
        STANDARD: {"spec": "Deepflow uPVC"},
        PREMIUM:  {"spec": "Cast aluminium"},
        "index_series": "other_materials",
    },
}

# What a unit of each product could plausibly cost, ex-VAT, in the
# catalogue's own unit. NOT an estimate — the estimate comes from
# observations. This is an order-of-magnitude sanity band, and it exists
# because of a real import.
#
# The government's own DBT building-materials tables were fed through the
# importer as a price list. They are an INDEX (2015 = 100), not pounds, and
# 29 of 30 lines were correctly refused as unmatched — but "Precast
# concrete: blocks, bricks, tiles and flagstones" matched `bricks` and its
# index value of 173.1 was filed as £173.10 PER BRICK, with no note at all.
# A facing brick is well under a pound. Nothing in the module could catch a
# 200x error, because nothing in the module knew what a brick costs.
#
# Bands are deliberately wide — wider than any real price spread — because
# the job is to catch a unit mix-up, an index mistaken for money, or pence
# read as pounds, not to second-guess a merchant.
PLAUSIBLE_PRICE = {
    "roof_covering":     (0.15, 12.00),    # per tile: concrete to handmade clay
    "battens":           (0.20, 5.00),     # per m
    "membrane":          (0.30, 12.00),    # per m2
    "plasterboard":      (1.00, 25.00),    # per m2
    "insulation":        (1.00, 60.00),    # per m2: mineral wool to PIR
    "structural_timber": (0.80, 40.00),    # per m: batten to glulam
    "bricks":            (0.15, 8.00),     # each: common to handmade
    "guttering":         (1.50, 60.00),    # per m: uPVC to cast iron
}


def plausible_price(product, price):
    """Whether a unit price could be real for this product. None if unknown."""
    band = PLAUSIBLE_PRICE.get(product)
    if band is None or price is None:
        return None
    return band[0] <= price <= band[1]


# DBT Construction Material Price Indices, published monthly on the first
# Wednesday, free and official, with commodity series running back decades.
# The series names below map our catalogue onto theirs.
INDEX_SOURCE = {
    "publisher": "Department for Business and Trade",
    "series": "Construction Material Price Indices (CMPI)",
    "cadence": "monthly, first Wednesday",
    "licence": "Open Government Licence",
    "url": "https://www.gov.uk/government/collections/"
           "building-materials-and-components-monthly-statistics",
}


class PriceError(ValueError):
    """Raised when a price cannot be established honestly."""


class Observation:
    """One sighting of a price, with where it came from."""

    def __init__(self, product, tier, price, source, observed_on,
                 merchant=None, region=None, unit=None, quantity=None):
        if product not in CATALOGUE:
            raise PriceError(
                f"unknown product {product!r}; known: "
                f"{', '.join(sorted(CATALOGUE))}")
        if tier not in TIERS:
            raise PriceError(f"tier must be one of {', '.join(TIERS)}")
        if source not in SOURCE_TRUST:
            raise PriceError(
                f"unknown source {source!r}; known: "
                f"{', '.join(sorted(SOURCE_TRUST))}")
        if price is None or price <= 0:
            raise PriceError(f"{product}/{tier}: price must be positive")

        self.product = product
        self.tier = tier
        self.price = float(price)
        self.source = source
        self.observed_on = observed_on
        self.merchant = merchant
        self.region = region
        self.unit = unit or CATALOGUE[product]["unit"]
        self.quantity = quantity

    def age_days(self, today=None):
        return ((today or date.today()) - self.observed_on).days

    def weight(self, today=None):
        """Trust, decayed by age.

        Materials moved violently through 2021-23, so a six-month-old
        invoice is history rather than a quote. Weight halves every
        HALF_LIFE_DAYS and reaches zero once stale.
        """
        age = self.age_days(today)
        # A price dated slightly in the future is a clock, not a claim about
        # the future. The worker, the caller and the merchant's export can sit
        # in different timezones and drift apart, and treating a day of skew
        # as "weight zero" silently voided every line of a price list
        # imported minutes earlier — surfacing as "no usable price" gaps
        # rather than as an error anyone could act on.
        if -CLOCK_SKEW_DAYS <= age < 0:
            age = 0
        if age < 0 or age > STALE_DAYS:
            return 0.0
        return SOURCE_TRUST[self.source] * (0.5 ** (age / HALF_LIFE_DAYS))

    def as_dict(self):
        return {"product": self.product, "tier": self.tier,
                "price": round(self.price, 2), "unit": self.unit,
                "source": self.source, "merchant": self.merchant,
                "region": self.region,
                "observed_on": self.observed_on.isoformat()}


def _weighted_median(pairs):
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    if total <= 0:
        return None
    half, run = total / 2.0, 0.0
    for value, weight in pairs:
        run += weight
        if run >= half:
            return value
    return pairs[-1][0]


def estimate(observations, product, tier, today=None):
    """Best current price for one product at one tier.

    Uses a weighted median rather than a mean so one mistyped invoice or one
    outlier quote cannot drag the figure — the same reasoning as the scale
    module, and for the same reason: a wrong number here propagates silently
    into every quote.
    """
    today = today or date.today()
    relevant = [o for o in observations
                if o.product == product and o.tier == tier
                and o.weight(today) > 0]
    if not relevant:
        # Distinguish "nothing was ever supplied" from "everything supplied
        # was discarded", because they call for opposite actions and both
        # otherwise arrive as the same shrug.
        matching = [o for o in observations
                    if o.product == product and o.tier == tier]
        stale = [o for o in matching if o.age_days(today) > STALE_DAYS]
        future = [o for o in matching if o.age_days(today) < 0]
        if future:
            why = (f"{len(future)} price(s) are dated in the future by more "
                   f"than {CLOCK_SKEW_DAYS} days, so they were ignored. "
                   f"Check the clock on whatever produced them.")
        elif stale:
            why = (f"{len(stale)} price(s) exist but are all over "
                   f"{STALE_DAYS} days old. Materials moved too far for "
                   f"those to be quotable — re-import a current list.")
        else:
            why = ("Add an invoice, request a quote, or fall back to your "
                   "rate card.")
        return {
            "product": product, "tier": tier, "price": None,
            "confidence": "none",
            "observations_discarded": len(matching),
            "message": f"No usable price for {product} at {tier} tier. {why}",
        }

    pairs = [(o.price, o.weight(today)) for o in relevant]
    price = _weighted_median(pairs)
    prices = [p for p, _ in pairs]
    spread = (max(prices) - min(prices)) / price if price else 0.0

    best = max(relevant, key=lambda o: o.weight(today))
    own = [o for o in relevant if o.source == INVOICE]

    return {
        "product": product,
        "tier": tier,
        "spec": CATALOGUE[product][tier]["spec"],
        "unit": CATALOGUE[product]["unit"],
        "price": round(price, 2),
        "observations": len(relevant),
        "your_invoices": len(own),
        "best_source": best.source,
        "newest_days": min(o.age_days(today) for o in relevant),
        "spread_pct": round(spread * 100, 1),
        "confidence": _confidence(relevant, spread, today),
        "warning": CATALOGUE[product].get("economy_warning")
                   if tier == ECONOMY else None,
    }


def _confidence(relevant, spread, today):
    """How much the estimate can be relied on: source, freshness AND spread.

    Every tier tests the spread. The "good" tier used not to, so a price set
    whose members disagreed by 20,000x — £1, £5 and £1,000 for the same
    product — came back labelled "good" purely because one of them was an
    invoice from last month. Freshness says nothing about whether the
    observations describe the same thing, and disagreement that wide almost
    always means a mis-filed line rather than a real market.
    """
    own = [o for o in relevant if o.source == INVOICE]
    freshest = min(o.age_days(today) for o in relevant)
    if own and freshest <= 60 and spread <= 0.15:
        return "high"
    if ((own or any(o.source == QUOTE for o in relevant))
            and freshest <= 120 and spread <= 0.60):
        return "good"
    if freshest <= 240 and spread <= 1.50:
        return "fair"
    return "low"


def compare_tiers(observations, product, today=None):
    """All three tiers side by side — the choice a builder actually makes."""
    if product not in CATALOGUE:
        raise PriceError(f"unknown product {product!r}")
    out = {"product": product, "unit": CATALOGUE[product]["unit"], "tiers": {}}
    for tier in TIERS:
        e = estimate(observations, product, tier, today)
        e["label"] = TIER_LABELS[tier]
        life = CATALOGUE[product][tier].get("life_years")
        if life:
            e["life_years"] = life
        out["tiers"][tier] = e

    priced = {t: v["price"] for t, v in out["tiers"].items() if v["price"]}
    if len(priced) >= 2:
        # Tiers of a per-each product are not always the same object. The
        # roof coverings are different tile types laying 10.5, 60 and 20
        # to the square metre, so comparing their per-tile prices showed
        # plain tile as "cheapest" and interlocking at +118% when, per
        # square metre of roof, the truth was the reverse — inverted by up
        # to 6x. Where every priced tier declares its coverage, every
        # comparison figure is computed on the installed square metre.
        cover = {t: CATALOGUE[product][t].get("covers_per_m2")
                 for t in priced}
        per_m2 = all(cover.values())
        basis = ({t: p * cover[t] for t, p in priced.items()} if per_m2
                 else dict(priced))
        if per_m2:
            for tier, cost in basis.items():
                out["tiers"][tier]["price_per_m2"] = round(cost, 2)
            out["comparison_basis"] = (
                "per m2 installed, using each tier's own coverage rate — "
                "the tiers lay different counts to the square metre, so "
                "per-unit prices are not comparable")
        cheapest = min(basis.values())
        for tier, cost in basis.items():
            out["tiers"][tier]["vs_cheapest_pct"] = round(
                (cost / cheapest - 1) * 100, 1)
        # Whole-life comparison, where a life expectancy exists — on the
        # same common basis, so a long life cannot launder a unit mix-up.
        for tier, v in out["tiers"].items():
            if tier in basis and v.get("life_years"):
                v["cost_per_year"] = round(
                    basis[tier] / v["life_years"], 3)
    return out


# ---------------------------------------------------------------------------
# Forecasting from the official index
# ---------------------------------------------------------------------------

def trend(index_points):
    """Fit a simple trend to an index series. Returns %/month and R².

    index_points: [(date, value)]. The DBT series is monthly, so a handful
    of years is plenty to see direction without over-reading noise.
    """
    if not index_points or len(index_points) < 3:
        return None
    base = min(d for d, _ in index_points)
    xs = [(d - base).days / 30.44 for d, _ in index_points]
    ys = [v for _, v in index_points]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx < 1e-12:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    intercept = my - slope * mx

    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    r2 = 1 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0

    return {
        "pct_per_month": round(slope / my * 100, 3) if my else 0.0,
        "pct_per_year": round(slope / my * 1200, 2) if my else 0.0,
        "r_squared": round(r2, 3),
        "months": round(max(xs) - min(xs), 1),
        "latest": ys[-1],
    }


def forecast(current_price, trend_info, months_ahead, today=None):
    """Project a price forward using the index trend.

    Deliberately conservative and explicit about being a projection. An
    index describes a national basket, not this merchant's price to this
    builder, and a poor fit is reported rather than hidden — R² below about
    0.5 means the series is not trending, it is wandering.
    """
    if not trend_info or current_price is None:
        return None
    if months_ahead <= 0:
        raise PriceError("months_ahead must be positive")

    rate = trend_info["pct_per_month"] / 100.0
    projected = current_price * ((1 + rate) ** months_ahead)

    r2 = trend_info["r_squared"]
    reliable = r2 >= 0.5
    # Uncertainty widens with horizon and with a poor fit.
    band = (0.02 + 0.01 * months_ahead) * (1.0 if reliable else 2.5)

    return {
        "current": round(current_price, 2),
        "months_ahead": months_ahead,
        "projected": round(projected, 2),
        "change_pct": round((projected / current_price - 1) * 100, 1),
        "low": round(projected * (1 - band), 2),
        "high": round(projected * (1 + band), 2),
        "trend_pct_per_year": trend_info["pct_per_year"],
        "r_squared": r2,
        "reliable": reliable,
        "basis": INDEX_SOURCE["series"],
        "note": ("Projection from the national index, not a quotation. It "
                 "describes a UK-wide basket rather than your merchant's "
                 "price to your account."
                 if reliable else
                 f"The index is not trending cleanly (R²={r2}), so this "
                 f"projection is weak. Treat the range as indicative only "
                 f"and get a quote for anything that matters."),
    }


# ---------------------------------------------------------------------------
# Refresh scheduling
# ---------------------------------------------------------------------------

def refresh_due(last_refresh, today=None, interval_days=REFRESH_INTERVAL_DAYS):
    """Whether the price set is due its weekly refresh."""
    today = today or date.today()
    if last_refresh is None:
        return {"due": True, "reason": "never refreshed", "days_since": None}
    days = (today - last_refresh).days
    return {
        "due": days >= interval_days,
        "days_since": days,
        "next_due": (last_refresh + timedelta(days=interval_days)).isoformat(),
        "reason": (f"{days} days since last refresh"
                   if days >= interval_days else "up to date"),
    }


def coverage(observations, today=None):
    """What the price set actually covers, and where the gaps are.

    A weekly refresh is only worth running if it is told what is missing,
    and a builder should be able to see which of their prices are their own
    and which are borrowed.
    """
    today = today or date.today()
    live = [o for o in observations if o.weight(today) > 0]
    rows, gaps = {}, []
    for product in CATALOGUE:
        rows[product] = {}
        for tier in TIERS:
            matching = [o for o in live
                        if o.product == product and o.tier == tier]
            own = sum(1 for o in matching if o.source == INVOICE)
            rows[product][tier] = {"observations": len(matching),
                                   "your_invoices": own}
            if not matching:
                gaps.append(f"{product}/{tier}")
    return {
        "products": len(CATALOGUE),
        "slots": len(CATALOGUE) * len(TIERS),
        "covered": len(CATALOGUE) * len(TIERS) - len(gaps),
        "gaps": gaps,
        "own_price_share": round(
            sum(1 for o in live if o.source == INVOICE) / len(live) * 100, 1)
        if live else 0.0,
        "detail": rows,
    }
