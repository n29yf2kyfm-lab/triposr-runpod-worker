"""Repair cost estimation — a defensible RANGE, never a false-precision number.

FairMoto shows "Repair: 700-1700 USD". Car Damage Scanner tailors estimates
to a chosen region's "local market prices". AutoScan prints a single "$300"
per issue. A range is the honest form: a dent's cost genuinely depends on
whether paintless dent repair works or the panel needs replacing, and no photo
resolves that. So every estimate here is (low, high) with the assumption
stated, and the app shows the band, not a point.

HOW THE NUMBER IS BUILT (transparent on purpose — a repair total a user can't
decompose is a repair total they can't trust):

    parts        from a panel base cost, scaled by severity
    paint/labour body labour hours x a regional labour rate, + materials
    total range  low = best-case method (PDR, refinish), high = replace

Regional multipliers scale a US-baseline set of rates. They are ORDER-OF-
MAGNITUDE market factors, not a live price feed — labelled as such in the
output so nobody mistakes them for a quote. The real per-market rate card is
the kind of thing that becomes a paid data asset later (the same play the
building product makes with its invoice-OCR price index); the structure here
is ready for that card to drop in.
"""
from taxonomy import clamp_severity, canonical_panel, PANELS

# Currency + labour rate ($/hour body-shop equivalent) + a parts/materials
# scalar, per region. US is the baseline (1.0). These are broad market
# factors; see module docstring.
REGIONS = {
    "us":     {"currency": "USD", "symbol": "$",  "labour_per_hour": 60,  "parts_factor": 1.00},
    "uk":     {"currency": "GBP", "symbol": "£",  "labour_per_hour": 55,  "parts_factor": 1.05},
    "eu":     {"currency": "EUR", "symbol": "€",  "labour_per_hour": 65,  "parts_factor": 1.05},
    "asia":   {"currency": "USD", "symbol": "$",  "labour_per_hour": 30,  "parts_factor": 0.85},
    "mena":   {"currency": "USD", "symbol": "$",  "labour_per_hour": 35,  "parts_factor": 0.95},
    "au":     {"currency": "AUD", "symbol": "A$", "labour_per_hour": 75,  "parts_factor": 1.10},
}
DEFAULT_REGION = "us"

# Per-panel replacement/parts baseline in USD, and the paint/refinish labour
# hours a full panel refinish takes. Panels not listed fall back to a body-
# panel default. Glass and lamps are parts-dominated; bumpers are labour-light
# but part-heavy; structural rails are the expensive tail.
PANEL_COST = {
    #                       parts_usd  refinish_hours
    "front_bumper":         (450,      2.5),
    "rear_bumper":          (480,      2.5),
    "hood":                 (600,      3.0),
    "tailgate":             (650,      3.0),
    "grille":               (220,      0.5),
    "front_left_fender":    (350,      2.5),
    "front_right_fender":   (350,      2.5),
    "front_left_door":      (700,      3.0),
    "front_right_door":     (700,      3.0),
    "rear_left_door":       (700,      3.0),
    "rear_right_door":      (700,      3.0),
    "left_quarter_panel":   (900,      4.0),   # welded, not bolt-on -> dearer
    "right_quarter_panel":  (900,      4.0),
    "left_rocker":          (800,      3.5),
    "right_rocker":         (800,      3.5),
    "roof":                 (1200,     5.0),
    "windshield":           (350,      1.5),
    "rear_windshield":      (300,      1.5),
    "left_front_glass":     (250,      1.0),
    "right_front_glass":    (250,      1.0),
    "front_left_headlight": (400,      0.8),
    "front_right_headlight":(400,      0.8),
    "rear_left_light":      (250,      0.8),
    "rear_right_light":     (250,      0.8),
    "left_mirror":          (280,      0.7),
    "right_mirror":         (280,      0.7),
    "front_left_wheel":     (300,      1.0),
    "front_right_wheel":    (300,      1.0),
    "rear_left_wheel":      (300,      1.0),
    "rear_right_wheel":     (300,      1.0),
}
DEFAULT_PANEL_COST = (500, 2.5)

# How each damage type is repaired, as (low_method, high_method) fractions of
# the panel replacement cost + labour, plus paint materials. Low is the
# optimistic method (paintless dent repair, resin fill, refinish only); high is
# replacement. Severity slides the estimate between and past these.
#   (parts_frac_low, parts_frac_high, labour_frac_low, labour_frac_high)
DAMAGE_METHOD = {
    "scratch":        (0.00, 0.05, 0.30, 1.00),   # buff -> full refinish
    "scuff":          (0.00, 0.02, 0.15, 0.70),
    "paint_chip":     (0.00, 0.05, 0.10, 0.90),
    "paint_fade":     (0.00, 0.00, 0.60, 1.20),   # refinish-only, can be whole panel
    "paint_mismatch": (0.00, 0.05, 0.50, 1.20),
    "dent":           (0.00, 1.00, 0.40, 1.00),   # PDR -> replace
    "deformation":    (0.10, 1.00, 0.70, 1.30),
    "crack":          (0.20, 1.00, 0.40, 1.10),
    "shattered_glass":(0.90, 1.10, 0.90, 1.10),   # replace, little variance
    "chip_glass":     (0.00, 0.30, 0.20, 1.00),   # resin -> replace
    "rust":           (0.05, 1.00, 0.60, 1.50),   # treat -> cut & weld
    "misalignment":   (0.00, 0.40, 0.50, 1.20),   # refit -> parts + structural
    "missing_part":   (0.90, 1.10, 0.30, 0.70),
    "lamp_damage":    (0.90, 1.05, 0.80, 1.10),
    "tire_damage":    (0.40, 1.20, 0.30, 0.80),
    "hail":           (0.00, 0.30, 0.80, 2.00),   # many dents -> panel(s)
    # Filler under the paint: best case the repair is sound and costs nothing
    # to leave alone; worst case the panel has to be stripped and redone.
    "body_filler":    (0.00, 1.00, 0.00, 1.20),
    "other":          (0.00, 0.50, 0.30, 1.00),
}

# Types that cost NOTHING to repair because nothing is broken. A measured
# prior respray is the case that forced this set to exist: it is a HISTORY and
# VALUE finding, and folding a notional "refinish it again" cost into the
# repair total would invent a bill the owner does not have. It still scores
# against the car in severity.py, and it still appears in the report — it just
# does not pretend to be a quote.
#
# NOTE ON DIMINISHED VALUE: no defensible published percentage was found for
# what a documented respray takes off a car's market value, and it varies with
# marque, age, panel and market. So this module states the finding and
# declines to put a number on the value impact rather than inventing one.
ZERO_REPAIR_TYPES = {"prior_refinish"}

# Paint materials cost per refinish hour (USD, US baseline).
PAINT_MATERIALS_PER_HOUR = 25


def normalize_region(region):
    if not region:
        return DEFAULT_REGION
    r = str(region).strip().lower()
    aliases = {
        "usa": "us", "united states": "us", "america": "us", "us": "us",
        "uk": "uk", "gb": "uk", "united kingdom": "uk", "britain": "uk",
        "europe": "eu", "eu": "eu", "de": "eu", "fr": "eu",
        "asia": "asia", "in": "asia", "india": "asia",
        "middle east": "mena", "mena": "mena", "gulf": "mena", "uae": "mena",
        "australia": "au", "au": "au", "nz": "au",
    }
    return aliases.get(r, r if r in REGIONS else DEFAULT_REGION)


def _severity_scale(sev):
    """Severity slides the estimate. sev 1 -> ~0.3 of the method span, sev 10
    -> ~1.15 (past nominal, because the worst cases exceed the tidy method)."""
    sev = clamp_severity(sev)
    return 0.25 + (sev / 10.0) * 0.9


def estimate_one(finding, region=DEFAULT_REGION):
    """Estimate (low, high) repair cost for one finding, in the region's
    currency. Returns a dict with the band and the assumptions behind it."""
    region = normalize_region(region)
    rc = REGIONS[region]
    panel = canonical_panel(finding.get("panel")) or finding.get("panel") \
        or "body_other"
    parts_base, refinish_hours = PANEL_COST.get(panel, DEFAULT_PANEL_COST)
    dtype = finding.get("damage_type", "other")
    sev = clamp_severity(finding.get("severity", 5))
    if dtype in ZERO_REPAIR_TYPES:
        return {
            "panel": panel, "damage_type": dtype, "severity": sev,
            "currency": rc["currency"], "symbol": rc["symbol"],
            "low": 0, "high": 0,
            "assumption_low": "no repair required — nothing is broken",
            "assumption_high": ("no repair required; this affects the "
                                "vehicle's history and value, not its "
                                "condition"),
        }
    pfl, pfh, lfl, lfh = DAMAGE_METHOD.get(dtype, DAMAGE_METHOD["other"])
    scale = _severity_scale(sev)

    def side(parts_frac, labour_frac):
        parts = parts_base * parts_frac * rc["parts_factor"]
        hours = refinish_hours * labour_frac
        labour = hours * rc["labour_per_hour"]
        materials = hours * PAINT_MATERIALS_PER_HOUR * rc["parts_factor"]
        return parts + labour + materials

    # low = optimistic method, lightly severity-scaled; high = worse method,
    # scaled up with severity (a severe dent is more likely to need the panel).
    low = side(pfl, lfl) * (0.6 + 0.4 * scale)
    high = side(pfh, lfh) * (0.7 + 0.6 * scale)
    if high < low:
        low, high = high, low
    # round to a currency-sensible step
    low = _round_cost(low)
    high = _round_cost(max(high, low + 25))
    return {
        "panel": panel,
        "damage_type": dtype,
        "severity": sev,
        "currency": rc["currency"],
        "symbol": rc["symbol"],
        "low": low,
        "high": high,
        "assumption_low": _method_label(dtype, "low"),
        "assumption_high": _method_label(dtype, "high"),
    }


def _round_cost(x):
    x = max(0, x)
    if x < 100:
        return int(round(x / 5.0) * 5)
    if x < 1000:
        return int(round(x / 25.0) * 25)
    return int(round(x / 50.0) * 50)


_METHOD_LABELS = {
    "dent": ("paintless dent repair", "panel replacement"),
    "scratch": ("machine polish", "full panel refinish"),
    "rust": ("treat and seal", "cut out and weld new metal"),
    "crack": ("repair", "replace"),
    "shattered_glass": ("glass replacement", "glass replacement"),
    "chip_glass": ("resin repair", "glass replacement"),
    "misalignment": ("refit / adjust", "parts + structural check"),
    "hail": ("PDR across dents", "affected panel replacement"),
    "body_filler": ("leave as is if the repair is sound",
                    "strip filler, repair the metal, refinish"),
}


def _method_label(dtype, which):
    pair = _METHOD_LABELS.get(dtype)
    if pair:
        return pair[0 if which == "low" else 1]
    return "best-case repair" if which == "low" else "replacement"


def estimate_all(findings, region=DEFAULT_REGION):
    """Estimate every finding and total the range.

    Hidden-damage contingencies are surfaced SEPARATELY (see
    `hidden_contingency`) rather than folded into the visible total, because
    they are probabilistic — presenting a p=25% airbag cost as part of the
    firm estimate would overstate it. The app shows "known repairs: X-Y, plus
    possible hidden: up to Z".
    """
    region = normalize_region(region)
    rc = REGIONS[region]
    lines = [estimate_one(f, region) for f in findings]
    total_low = sum(l["low"] for l in lines)
    total_high = sum(l["high"] for l in lines)
    hidden = hidden_contingency(findings, region)
    return {
        "region": region,
        "currency": rc["currency"],
        "symbol": rc["symbol"],
        "lines": lines,
        "total_low": _round_cost(total_low),
        "total_high": _round_cost(total_high),
        "hidden_contingency_high": hidden,
        "grand_total_high": _round_cost(total_high + hidden),
        "disclaimer": (
            "Estimate range from image analysis only, using regional market "
            "factors — not a workshop quote. Actual cost depends on parts "
            "availability, sub-surface damage found on strip-down, and your "
            "chosen shop."),
    }


def hidden_contingency(findings, region=DEFAULT_REGION):
    """Expected-value cost of the hidden-damage risks the analysis flagged.

    Each finding may carry hidden_damage[{probability, est_cost_high}]. We sum
    probability x est_cost_high — the risk-weighted amount to set aside, not a
    charge. If the analysis gave no cost, a panel-based default stands in.
    """
    region = normalize_region(region)
    rc = REGIONS[region]
    total = 0.0
    for f in findings:
        for hd in f.get("hidden_damage", []) or []:
            p = hd.get("probability")
            try:
                p = float(p)
                if p > 1:      # given as a percentage
                    p /= 100.0
            except (TypeError, ValueError):
                p = 0.3
            p = max(0.0, min(1.0, p))
            cost = hd.get("est_cost_high")
            if cost is None:
                cost = 800 * rc["parts_factor"]   # generic sub-surface default
            try:
                cost = float(cost)
            except (TypeError, ValueError):
                cost = 800 * rc["parts_factor"]
            total += p * cost
    return _round_cost(total)
