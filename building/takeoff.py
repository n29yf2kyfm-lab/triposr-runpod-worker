"""Price Mode — measured quantities into a priced quote.

    quantities x rate card + waste + labour + prelims + margin + VAT = quote

THE RATE CARD IS THE USER'S OWN. A builder knows their prices better than
any published book, and their merchant discount is theirs alone. The
defaults here exist so a first quote is not a blank form; they are a
starting point to overwrite, not an authority, and every line says which it
came from.

EVERY LINE IS TRACEABLE. Each priced item records the measured quantity it
came from and how that quantity was derived, so a builder queried on a
number can follow it back to the geometry rather than defending a black box.
That is also what makes a bad quote diagnosable instead of merely wrong.
"""
import math

# --- VAT ------------------------------------------------------------------
# UK construction VAT is not flat, and getting it wrong is expensive in both
# directions. These are the headline cases; the rate is chosen per quote
# because it depends on the WORK, not the trade.
VAT_RATES = {
    "standard": 0.20,   # most repair, maintenance and improvement work
    "reduced": 0.05,    # e.g. a home empty 2+ years, some energy-saving work
    "zero": 0.00,       # e.g. qualifying new-build dwellings
}

# Construction Industry Scheme deduction, withheld from a subcontractor's
# LABOUR only — never from materials. Included because a builder quoting
# subcontract work needs the net figure, and it is a common costly slip.
CIS_RATES = {"none": 0.0, "registered": 0.20, "unregistered": 0.30}

# --- default rates --------------------------------------------------------
# Placeholders in GBP, deliberately conservative and clearly marked. They
# make a first quote possible; they are not a price book.
DEFAULT_MATERIAL_RATES = {
    "concrete_interlocking": (1.20, "each", "concrete interlocking tile"),
    "plain_tile":            (0.55, "each", "clay plain tile"),
    "natural_slate":         (2.40, "each", "natural slate"),
    "battens_m":             (0.85, "m", "treated roofing batten"),
    "membrane_m2":           (1.60, "m2", "breather membrane"),
    "ridge_units":           (6.50, "each", "ridge tile, bedded"),
    "guttering_m":           (12.00, "m", "gutter, brackets and fittings"),
    "valley_m":              (28.00, "m", "valley trough"),
    "plasterboard_m2":       (4.20, "m2", "12.5mm board"),
    "plaster_m2":            (3.10, "m2", "skim finish materials"),
    "paint_m2":              (2.40, "m2", "trade emulsion, two coats"),
    "floor_tile_m2":         (24.00, "m2", "floor tile"),
    "screed_m2":             (14.00, "m2", "levelling screed"),
    "insulation_m2":         (9.50, "m2", "loft or wall insulation"),
    "skirting_m":            (7.50, "m", "MDF skirting"),
    "pipe_m":                (4.20, "m", "15mm copper, fittings"),
    "cable_m":               (1.90, "m", "twin and earth"),
    "socket_each":           (18.00, "each", "socket, back box, accessories"),
}

DEFAULT_LABOUR_RATES = {
    "roofer":       (280.00, "day", "roofer, day rate"),
    "roofer_mate":  (160.00, "day", "labourer, day rate"),
    "plasterer":    (250.00, "day", "plasterer, day rate"),
    "painter":      (200.00, "day", "decorator, day rate"),
    "tiler":        (260.00, "day", "tiler, day rate"),
    "electrician":  (320.00, "day", "electrician, day rate"),
    "plumber":      (320.00, "day", "plumber, day rate"),
    "labourer":     (150.00, "day", "general labourer, day rate"),
}

# Output per worker-day. Rough, and the first thing an experienced builder
# should replace with their own gang's real rate.
DEFAULT_OUTPUTS = {
    "roof_tiling_m2_per_day": 22.0,
    "plastering_m2_per_day": 45.0,
    "painting_m2_per_day": 60.0,
    "floor_tiling_m2_per_day": 12.0,
}

DEFAULT_PRELIMS_PCT = 0.08   # scaffold, skip, welfare, plant, access
DEFAULT_MARGIN_PCT = 0.18    # overhead and profit


class QuoteError(ValueError):
    """Raised when a quote cannot be produced honestly."""


class RateCard:
    """A builder's own prices. Versioned, because a quote must be
    reproducible: re-opening last month's job should re-price at last
    month's rates, not today's."""

    def __init__(self, materials=None, labour=None, outputs=None,
                 version=None, currency="GBP"):
        self.materials = dict(DEFAULT_MATERIAL_RATES)
        self.labour = dict(DEFAULT_LABOUR_RATES)
        self.outputs = dict(DEFAULT_OUTPUTS)
        self.custom = set()

        for src, dest in ((materials or {}, self.materials),
                          (labour or {}, self.labour)):
            for key, value in src.items():
                rate, unit, desc = _coerce_rate(key, value, dest)
                dest[key] = (rate, unit, desc)
                self.custom.add(key)

        self.outputs.update(outputs or {})
        self.version = version or "defaults"
        self.currency = currency

    def material(self, key):
        if key not in self.materials:
            raise QuoteError(
                f"no material rate for {key!r}. Add it to the rate card, or "
                f"use one of: {', '.join(sorted(self.materials))}")
        return self.materials[key]

    def labour_rate(self, key):
        if key not in self.labour:
            raise QuoteError(
                f"no labour rate for {key!r}. Add it to the rate card, or "
                f"use one of: {', '.join(sorted(self.labour))}")
        return self.labour[key]

    def is_default(self, key):
        return key not in self.custom


def _coerce_rate(key, value, existing):
    """Accept a bare number or a (rate, unit, description) triple."""
    if isinstance(value, (int, float)):
        prior = existing.get(key)
        return (float(value),
                prior[1] if prior else "each",
                prior[2] if prior else key)
    if isinstance(value, dict):
        return (float(value["rate"]), value.get("unit", "each"),
                value.get("description", key))
    if isinstance(value, (list, tuple)) and len(value) >= 1:
        return (float(value[0]),
                value[1] if len(value) > 1 else "each",
                value[2] if len(value) > 2 else key)
    raise QuoteError(f"cannot read a rate for {key!r} from {value!r}")


class Line:
    """One priced item, carrying where its quantity came from."""

    def __init__(self, key, description, quantity, unit, rate, source,
                 is_default_rate=False, note=None):
        self.key = key
        self.description = description
        self.quantity = round(float(quantity), 2)
        self.unit = unit
        # The rate is kept at FULL precision and rounded only for display.
        # Rounding it to pence before multiplying looks tidy and is wrong at
        # quantity: 500m of a material costing a true £0.855 billed £430.00
        # against £427.50, and materials priced per metre or per square metre
        # routinely land on fractions of a penny.
        self.rate_exact = float(rate)
        self.rate = round(self.rate_exact, 2)
        self.source = source
        self.is_default_rate = is_default_rate
        self.note = note

    @property
    def total(self):
        return round(self.quantity * self.rate_exact, 2)

    def as_dict(self):
        d = {"key": self.key, "description": self.description,
             "quantity": self.quantity, "unit": self.unit,
             "rate": self.rate, "total": self.total,
             "measured_from": self.source}
        if self.is_default_rate:
            d["rate_is_default"] = True
        if self.note:
            d["note"] = self.note
        return d


def price_roof(quantities, rate_card, covering=None):
    """Turn a roof takeoff into priced material lines.

    Every quantity here derives from TRUE SLOPED area, never the footprint —
    the distinction the roof module exists to make, carried through so the
    quote inherits it rather than quietly reverting to plan area.
    """
    materials = quantities.get("materials") or {}
    covering = covering or materials.get("covering") or "concrete_interlocking"
    sloped = quantities.get("sloped_area_m2")
    if not sloped:
        raise QuoteError(
            "roof pricing needs sloped_area_m2. Pricing from plan area "
            "under-orders by 10-25% and is the error this refuses to make.")

    src = f"{sloped} m2 true sloped area"
    lines = []

    def add(key, qty, source, note=None):
        if not qty:
            return
        rate, unit, desc = rate_card.material(key)
        lines.append(Line(key, desc, qty, unit, rate, source,
                          rate_card.is_default(key), note))

    add(covering, materials.get("covering_units"), src,
        "includes waste allowance")
    add("battens_m", materials.get("battens_m"), src)
    add("membrane_m2", materials.get("membrane_m2"), src)
    add("ridge_units", materials.get("ridge_units"),
        f"{quantities.get('ridge_m', 0)}m ridge + {quantities.get('hip_m', 0)}m hip")
    add("valley_m", materials.get("valley_m"),
        f"{quantities.get('valley_m', 0)}m valley")
    add("guttering_m", materials.get("guttering_m"),
        f"{quantities.get('eaves_m', 0)}m eaves")
    return lines


def labour_for_roof(quantities, rate_card, gang=2):
    """Estimate roofing labour from measured area and the card's outputs."""
    sloped = quantities.get("sloped_area_m2") or 0
    if not sloped:
        return []
    per_day = rate_card.outputs.get("roof_tiling_m2_per_day", 22.0)
    days = math.ceil(sloped / max(per_day, 1e-6) / max(gang, 1) * 10) / 10

    lines = []
    rate, unit, desc = rate_card.labour_rate("roofer")
    lines.append(Line("roofer", desc, days, unit, rate,
                      f"{sloped} m2 at {per_day} m2/day, gang of {gang}",
                      rate_card.is_default("roofer")))
    if gang > 1:
        rate, unit, desc = rate_card.labour_rate("roofer_mate")
        lines.append(Line("roofer_mate", desc, days * (gang - 1), unit, rate,
                          f"gang of {gang}", rate_card.is_default("roofer_mate")))
    return lines


def build_quote(quantities, rate_card=None, labour_lines=None,
                extra_lines=None, covering=None, gang=2,
                prelims_pct=DEFAULT_PRELIMS_PCT,
                margin_pct=DEFAULT_MARGIN_PCT,
                vat="standard", cis="none", notes=None):
    """Assemble a full quote. Returns a dict ready to render or store."""
    rate_card = rate_card or RateCard()

    if vat not in VAT_RATES:
        raise QuoteError(
            f"unknown VAT basis {vat!r}; use one of: {', '.join(VAT_RATES)}")
    if cis not in CIS_RATES:
        raise QuoteError(
            f"unknown CIS status {cis!r}; use one of: {', '.join(CIS_RATES)}")
    for name, pct in (("prelims_pct", prelims_pct), ("margin_pct", margin_pct)):
        if not 0 <= pct < 1:
            raise QuoteError(f"{name} must be between 0 and 1, got {pct}")

    material_lines = price_roof(quantities, rate_card, covering)
    material_lines.extend(extra_lines or [])
    labour = (labour_lines if labour_lines is not None
              else labour_for_roof(quantities, rate_card, gang))

    materials_total = round(sum(l.total for l in material_lines), 2)
    labour_total = round(sum(l.total for l in labour), 2)
    net = round(materials_total + labour_total, 2)

    prelims = round(net * prelims_pct, 2)
    margin = round((net + prelims) * margin_pct, 2)
    subtotal = round(net + prelims + margin, 2)

    vat_rate = VAT_RATES[vat]
    vat_amount = round(subtotal * vat_rate, 2)
    total = round(subtotal + vat_amount, 2)

    # CIS is withheld from LABOUR only, never materials. Reported alongside
    # the total rather than deducted from it, because it changes what the
    # subcontractor RECEIVES, not what the job COSTS.
    cis_rate = CIS_RATES[cis]
    cis_deduction = round(labour_total * cis_rate, 2) if cis_rate else 0.0

    warnings = list(notes or [])
    defaults_used = sorted({l.key for l in material_lines + labour
                            if l.is_default_rate})
    if defaults_used:
        warnings.append(
            f"{len(defaults_used)} line(s) priced at built-in default rates, "
            f"not your own: {', '.join(defaults_used)}. Set your rate card "
            f"before sending this to a customer.")
    if vat == "standard":
        warnings.append(
            "VAT at 20% (standard). Some work qualifies for 5% or zero rating "
            "— a long-empty dwelling or a qualifying new build — so check "
            "before issuing.")

    return {
        "currency": rate_card.currency,
        "rate_card_version": rate_card.version,
        "materials": [l.as_dict() for l in material_lines],
        "labour": [l.as_dict() for l in labour],
        "totals": {
            "materials": materials_total,
            "labour": labour_total,
            "net": net,
            "prelims": prelims,
            "prelims_pct": round(prelims_pct * 100, 1),
            "margin": margin,
            "margin_pct": round(margin_pct * 100, 1),
            "subtotal": subtotal,
            "vat_basis": vat,
            "vat_pct": round(vat_rate * 100, 1),
            "vat": vat_amount,
            "total": total,
        },
        "cis": {"status": cis, "rate_pct": round(cis_rate * 100, 1),
                "deduction_from_labour": cis_deduction,
                "note": "CIS is withheld from labour only, never materials."}
        if cis_rate else None,
        "warnings": warnings,
    }


def run(spec, prog, output_dir):
    """Price mode entry point for the handler."""
    import os
    import json

    prog.stage("fetching")
    quantities = spec.get("quantities")
    if not quantities and spec.get("roof"):
        quantities = spec["roof"].get("quantities")
    if not quantities:
        raise QuoteError(
            "price mode needs measured quantities. Run roof mode first and "
            "pass its quantities, or supply them directly.")

    prog.stage("quantities")
    card_spec = spec.get("rate_card") or {}
    rate_card = RateCard(materials=card_spec.get("materials"),
                         labour=card_spec.get("labour"),
                         outputs=card_spec.get("outputs"),
                         version=card_spec.get("version"))

    prog.stage("pricing")
    quote = build_quote(
        quantities, rate_card,
        covering=card_spec.get("covering"),
        gang=card_spec.get("gang", 2),
        prelims_pct=card_spec.get("prelims_pct", DEFAULT_PRELIMS_PCT),
        margin_pct=card_spec.get("margin_pct", DEFAULT_MARGIN_PCT),
        vat=card_spec.get("vat", "standard"),
        cis=card_spec.get("cis", "none"),
        notes=spec.get("notes"))

    prog.stage("exporting")
    os.makedirs(output_dir, exist_ok=True)
    scan = spec.get("scan_id") or "quote"
    path = os.path.join(output_dir, f"quote_{scan}.json")
    with open(path, "w") as f:
        json.dump(quote, f, indent=2)

    return ([(path, f"quotes/{scan}.json", None)],
            {"quote": quote, "warnings": quote["warnings"]})
