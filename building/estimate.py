"""From a measured bill to a priced estimate — with the rates visible.

WHAT WAS MISSING. quantities.py measures the job properly and stops.
takeoff.py prices roof mode only. So the platform could tell a builder
he needed 9,657 bricks and not what the job costs, which is half a tool.

THE HONEST PROBLEM WITH PRICING. There is no free, authoritative, current
UK rate database. SPON's and BCIS are licensed products; merchant trade
prices are account-specific and confidential; and a scraped shelf price
is retail list, which is not what anyone in the trade pays (prices.py
says all of this at length and is right).

So this module does NOT pretend to know your rates. It ships an
INDICATIVE rate card with a stated basis and date, marks every line with
where its rate came from, and is built to be overridden — by your own
rate card, or by prices.py observations from your real invoices. The
estimate says, on its face, how much of itself is indicative.

AND IT GIVES A RANGE. A concept-stage estimate from a massing model is
not a price; presenting one number to the penny is the lie that gets
builders into trouble. This follows normal estimating practice: the
class of estimate determines the spread, and the spread is printed.
"""
from __future__ import annotations

import datetime as _dt
import math

# --------------------------------------------------------------- basis
RATE_CARD_DATE = "2026-01"
RATE_BASIS = (
    "Indicative UK rates for small domestic works, gathered as a starting "
    "point and NOT a published price book. Replace them with your own "
    "rates, or let the estimate read your invoices through prices.py, "
    "before quoting a customer."
)

# Estimate classes and their honest spread. An estimate built from a
# massing model with no room layout cannot be better than order-of-
# magnitude, and saying so is the difference between an estimate and a
# guess with a decimal point.
CLASSES = {
    "order_of_magnitude": (-0.30, 0.50,
                           "massing only — no room layout, no survey"),
    "concept": (-0.20, 0.30, "measured geometry, standard specification"),
    "detailed": (-0.10, 0.15, "measured geometry with confirmed rates"),
    "tender": (-0.05, 0.05, "priced against real quotations"),
}

# Regional variation is real and large. These are INDICATIVE relative
# factors, not the licensed BCIS location factors; BCIS publishes the
# authoritative series and a business quoting real work should buy it
# and substitute the current number here.
REGIONS = {
    "london": (1.12, "Greater London"),
    "south_east": (1.05, "South East"),
    "east": (1.00, "East of England"),
    "south_west": (0.98, "South West"),
    "west_midlands": (0.96, "West Midlands"),
    "east_midlands": (0.95, "East Midlands"),
    "north_west": (0.95, "North West"),
    "yorkshire": (0.94, "Yorkshire and the Humber"),
    "wales": (0.94, "Wales"),
    "north_east": (0.93, "North East"),
    "scotland": (0.97, "Scotland"),
    "northern_ireland": (0.82, "Northern Ireland"),
}
DEFAULT_REGION = "west_midlands"

# VAT on building work is not one number, and getting it wrong is a
# 20% error on the whole job. HMRC Notice 708 is the operative document;
# these are the common cases with the note that qualification is a
# question for the customer's accountant, not for software.
VAT_RATES = {
    "standard": (0.20, "Standard-rated: most alterations, extensions and "
                       "repairs to an existing dwelling."),
    "reduced": (0.05, "Reduced-rated: a dwelling empty for 2+ years, or a "
                      "conversion that changes the number of dwellings. "
                      "Conditions apply — see HMRC Notice 708."),
    "zero": (0.00, "Zero-rated: a genuinely NEW dwelling, or work for a "
                   "disabled person's needs. Not an extension."),
    "none": (0.00, "Not VAT registered / customer supplies materials."),
}

# --------------------------------------------------- labour constants
# Hours of trade time per unit of finished work. These are ordinary
# planning norms for small works — the kind of figure a builder carries
# in his head — and like every rate here they are meant to be replaced
# with what your gang actually achieves.
LABOUR = {
    # key: (trade, hours per unit, unit)
    "Facing bricks":               ("bricklayer", 0.0140, "no"),
    "100mm blocks (inner leaf)":   ("bricklayer", 0.0450, "no"),
    "100mm blocks (party wall, both leaves)":
                                   ("bricklayer", 0.0450, "no"),
    "Mortar":                      ("labourer", 1.2000, "m3"),
    "Cavity wall ties":            ("bricklayer", 0.0030, "no"),
    "DPC 100mm roll":              ("bricklayer", 0.0600, "m"),
    "Lintels":                     ("bricklayer", 0.7500, "no"),
    "Roof covering (concrete interlocking)":
                                   ("roofer", 0.0180, "no"),
    "Treated battens 25x50":       ("roofer", 0.0150, "m"),
    "Breather membrane":           ("roofer", 0.0400, "m2"),
    "Ridge tiles":                 ("roofer", 0.1800, "no"),
    "Monopitch top edge (ridge OR flashing)":
                                   ("roofer", 0.3500, "m"),
    "Gutter + fittings":           ("roofer", 0.2200, "m"),
    "Dry verge / barge":           ("roofer", 0.2000, "m"),
    "Plasterboard 12.5mm sheets":  ("plasterer", 0.3500, "no"),
    "Skim plaster":                ("plasterer", 0.1600, "m2"),
    "Emulsion":                    ("decorator", 0.1200, "L"),
    "Floor screed/deck":           ("labourer", 0.2500, "m2"),
    "Skirting":                    ("carpenter", 0.1200, "m"),
    "Internal door sets 762mm":    ("carpenter", 1.6000, "no"),
    "Radiators (as heat design)":  ("plumber", 2.5000, "no"),
    "Soil stack + fittings":       ("plumber", 4.0000, "no"),
    # substructure
    "Excavate foundation trench":  ("groundworker", 1.8000, "m3"),
    "Cart away spoil":             ("groundworker", 0.3500, "m3"),
    "Foundation concrete C20":     ("groundworker", 1.1000, "m3"),
    "Hardcore sub-base":           ("groundworker", 1.4000, "m3"),
    "Sand blinding":               ("groundworker", 1.2000, "m3"),
    "DPM 1200g":                   ("labourer", 0.0700, "m2"),
    "Floor insulation PIR 100mm":  ("labourer", 0.1200, "m2"),
    "Ground slab concrete C25":    ("groundworker", 1.6000, "m3"),
    "A252 mesh":                   ("labourer", 0.0800, "m2"),
    # structural timber
    "Rafters 47x150 C24":          ("carpenter", 0.1100, "m"),
    "Ridge board and purlins 47x200": ("carpenter", 0.1600, "m"),
    "Wall plate 100x50 treated":   ("carpenter", 0.1000, "m"),
    "Floor joists 47x220 C24":     ("carpenter", 0.1300, "m"),
    "Steel beam over opening (ALLOWANCE)": ("bricklayer", 14.0000, "no"),
    "Restraint straps and joist hangers": ("carpenter", 0.1800, "no"),
    # openings
    "Windows, PVCu double glazed": ("carpenter", 1.1000, "m2"),
    "External door sets":          ("carpenter", 3.2000, "no"),
    "Cavity closers":              ("bricklayer", 0.1200, "m"),
    "Window boards":               ("carpenter", 0.2000, "m"),
    # insulation
    "Cavity insulation 100mm":     ("bricklayer", 0.0600, "m2"),
    "Loft insulation 300mm":       ("labourer", 0.1000, "m2"),
    # fit out
    "Consumer unit and circuits":  ("electrician", 9.0000, "no"),
    "Twin sockets":                ("electrician", 0.7000, "no"),
    "Light fittings and switches": ("electrician", 0.8000, "no"),
    "Smoke and heat alarms":       ("electrician", 1.2000, "no"),
    "Boiler and controls (ALLOWANCE)": ("plumber", 14.0000, "no"),
    "Bathroom suite":              ("plumber", 16.0000, "no"),
    "Kitchen units and worktop (ALLOWANCE)": ("carpenter", 26.0000, "no"),
    # external works
    "Drain run to existing manhole": ("groundworker", 0.9000, "m"),
    "Inspection chamber":          ("groundworker", 5.0000, "no"),
    "Make good paving and ground": ("groundworker", 0.3500, "m2"),
}
# Pipe and cable runs are priced per metre by their own trade.
LABOUR_PATTERNS = (
    ("copper", ("plumber", 0.2200, "m")),
    ("PVCu", ("plumber", 0.1800, "m")),
    ("drainage", ("groundworker", 0.2500, "m")),
    ("T&E", ("electrician", 0.1600, "m")),
)

# Gang rates, £ per hour, all-in (wages, NI, holiday, small tools).
TRADE_RATES = {
    "bricklayer": 32.0, "labourer": 22.0, "roofer": 30.0,
    "plasterer": 30.0, "carpenter": 32.0, "decorator": 26.0,
    "plumber": 38.0, "electrician": 40.0, "groundworker": 26.0,
}

# Material rates, £ per unit of the bill's own unit.
MATERIAL_RATES = {
    "Facing bricks": 0.72, "100mm blocks (inner leaf)": 2.10,
    "100mm blocks (party wall, both leaves)": 2.10,
    "Mortar": 165.0, "Cement 25kg bags": 6.20, "Building sand": 52.0,
    "Cavity wall ties": 0.28, "DPC 100mm roll": 1.30, "Lintels": 68.0,
    "Roof covering (concrete interlocking)": 1.05,
    "Roof covering (natural slate)": 2.60,
    "Treated battens 25x50": 0.95, "Breather membrane": 1.40,
    "Ridge tiles": 7.50,
    "Monopitch top edge (ridge OR flashing)": 26.0,
    "Gutter + fittings": 14.0, "Dry verge / barge": 12.5,
    "Plasterboard 12.5mm sheets": 11.50, "Skim plaster": 3.10,
    "Emulsion": 4.80, "Floor screed/deck": 22.0, "Skirting": 4.60,
    "Internal door sets 762mm": 96.0,
    "Radiators (as heat design)": 140.0, "Soil stack + fittings": 130.0,
    # substructure
    "Excavate foundation trench": 0.0, "Cart away spoil": 22.0,
    "Foundation concrete C20": 135.0, "Hardcore sub-base": 38.0,
    "Sand blinding": 42.0, "DPM 1200g": 1.60,
    "Floor insulation PIR 100mm": 21.0, "Ground slab concrete C25": 145.0,
    "A252 mesh": 6.40,
    # structural timber
    "Rafters 47x150 C24": 4.60, "Ridge board and purlins 47x200": 7.80,
    "Wall plate 100x50 treated": 3.10, "Floor joists 47x220 C24": 7.20,
    "Steel beam over opening (ALLOWANCE)": 620.0,
    "Restraint straps and joist hangers": 4.20,
    # openings — the units, which are the big money in a domestic job
    "Windows, PVCu double glazed": 340.0, "External door sets": 780.0,
    "Cavity closers": 4.20, "Window boards": 8.50,
    # insulation
    "Cavity insulation 100mm": 13.5, "Loft insulation 300mm": 9.80,
    # fit out
    "Consumer unit and circuits": 320.0, "Twin sockets": 9.50,
    "Light fittings and switches": 34.0, "Smoke and heat alarms": 48.0,
    "Boiler and controls (ALLOWANCE)": 1650.0,
    "Bathroom suite": 1400.0,
    "Kitchen units and worktop (ALLOWANCE)": 6500.0,
    # external works
    "Drain run to existing manhole": 34.0, "Inspection chamber": 210.0,
    "Make good paving and ground": 28.0,
}
MATERIAL_PATTERNS = (
    ("15mm copper", 6.20), ("22mm copper", 9.40),
    ("110mm", 12.50), ("40mm", 3.60), ("32mm", 3.20),
    ("1.5mm2 T&E", 1.30), ("2.5mm2 T&E", 1.85), ("6mm2 T&E", 4.30),
)

# Everything that is not a material or a trade hour, as a percentage of
# the measured work. Preliminaries on a domestic extension are mostly
# scaffold, skip hire, welfare and plant.
PRELIMS_PCT = 0.12
OVERHEAD_PROFIT_PCT = 0.18
CONTINGENCY_PCT = 0.08

# Professional fees, as a fraction of construction cost. Building control
# and planning are real fixed-ish fees; design and structural scale.
FEES = {
    "design": (0.055, "Architect / designer, concept to building regs "
                      "drawings"),
    "structural": (0.020, "Structural engineer: beams over openings, "
                          "foundations"),
    "building_control": (0.014, "Local authority or approved inspector"),
    "planning": (0.008, "Planning application, where one is needed"),
}


# ------------------------------------------------------- coverage
# THE MOST DANGEROUS THING THIS MODULE COULD DO is price an incomplete
# bill and present the answer as "the cost". quantities.py measures
# masonry, roof covering, finishes and service runs — real work, but
# roughly a third of a domestic job. It measures no foundations, no roof
# timbers, no windows, no insulation and no fit-out, and an estimate
# that omits those in silence is not an underestimate, it is a trap.
#
# So the estimate declares its own coverage: which standard packages the
# bill contains, which are absent, and what that means for the headline.
PACKAGES = {
    "substructure": (
        ["excavation", "foundation", "footing", "dpm", "oversite",
         "slab", "hardcore"],
        "Excavation, concrete foundations, DPM, floor slab and insulation"),
    "superstructure_masonry": (
        ["brick", "block", "mortar", "cement", "sand", "tie", "dpc",
         "lintel"],
        "External and internal walls above dpc"),
    "structural_timber": (
        ["rafter", "truss", "joist", "wall plate", "purlin", "beam",
         "steel"],
        "Roof structure, floor joists, and any beam over an opening"),
    "roof_covering": (
        ["roof covering", "batten", "membrane", "ridge", "verge",
         "gutter", "flashing", "top edge"],
        "Tiles or slates, battens, membrane and rainwater goods"),
    "external_openings": (
        ["window unit", "external door", "bifold", "patio door",
         "rooflight"],
        "Windows and external doors as UNITS — not the lintels over them"),
    "insulation": (
        ["insulation", "cavity fill", "pir", "mineral wool"],
        "Cavity, floor and roof insulation to Part L"),
    "internal_finishes": (
        ["plasterboard", "skim", "emulsion", "screed", "skirting",
         "internal door", "floor finish"],
        "Boarding, plaster, decoration, floors and internal doors"),
    "services_first_fix": (
        ["copper", "t&e", "pvcu", "drainage", "cable", "pipe"],
        "Pipework and cable runs"),
    "services_fit_out": (
        ["boiler", "consumer unit", "socket", "switch", "light fitting",
         "sanitaryware", "kitchen", "radiator"],
        "Boiler, consumer unit, accessories, sanitaryware and kitchen"),
    "external_works": (
        ["drain run", "manhole", "soakaway", "paving", "path",
         "make good"],
        "Drainage connections, paving and making good outside"),
}

# What a real small domestic job costs, all in, per m2 of new floor area.
# Wide on purpose: specification and access move it more than region
# does. Used ONLY as a sanity band — if an estimate lands far below it,
# that is a signal the bill is incomplete, and the estimate says so.
TYPICAL_GROSS_PER_M2 = (1800.0, 3200.0)


def coverage(bill):
    """Which standard packages this bill actually contains."""
    items = [L["item"].lower()
             for lines in (bill.get("groups") or {}).values()
             for L in lines or [] if float(L.get("quantity") or 0) > 0]
    present, absent = [], []
    for key, (keys, desc) in PACKAGES.items():
        hit = any(any(k in it for k in keys) for it in items)
        (present if hit else absent).append(
            {"package": key, "description": desc})
    return {"present": present, "absent": absent,
            "priced_packages": len(present),
            "total_packages": len(PACKAGES),
            "complete": not absent}


class RateCard:
    """Rates, and where each of them came from.

    Every rate carries a source: `card` for the shipped indicative
    figures, `user` for anything you have set, `invoice` where it came
    from prices.py observations of what you actually paid. The estimate
    reports the mix, so "how much of this is guessed" is answerable.
    """

    def __init__(self, materials=None, trades=None, labour=None,
                 region=DEFAULT_REGION, prelims_pct=PRELIMS_PCT,
                 ohp_pct=OVERHEAD_PROFIT_PCT,
                 contingency_pct=CONTINGENCY_PCT, date=RATE_CARD_DATE):
        self.materials = dict(MATERIAL_RATES)
        self.trades = dict(TRADE_RATES)
        self.labour = dict(LABOUR)
        self._source = {k: "card" for k in self.materials}
        if materials:
            self.materials.update(materials)
            self._source.update({k: "user" for k in materials})
        if trades:
            self.trades.update(trades)
        if labour:
            self.labour.update(labour)
        if region not in REGIONS:
            raise ValueError(
                f"unknown region {region!r}; known: {', '.join(sorted(REGIONS))}")
        self.region = region
        self.prelims_pct = float(prelims_pct)
        self.ohp_pct = float(ohp_pct)
        self.contingency_pct = float(contingency_pct)
        self.date = date

    @property
    def region_factor(self):
        return REGIONS[self.region][0]

    def material_rate(self, item):
        if item in self.materials:
            return self.materials[item], self._source.get(item, "card")
        for pat, rate in MATERIAL_PATTERNS:
            if pat in item:
                return rate, "card"
        return None, None

    def labour_for(self, item):
        if item in self.labour:
            return self.labour[item]
        for pat, spec in LABOUR_PATTERNS:
            if pat in item:
                return spec
        return None

    def from_observations(self, observations, tier="standard", today=None):
        """Replace card rates with what YOUR invoices say, via prices.py.

        This is the path that makes the estimate genuinely yours: a rate
        derived from your own delivery notes beats any published figure,
        and prices.py already weights invoice over quote over published.
        """
        try:
            import prices
        except ImportError:
            return 0
        replaced = 0
        by_product = {}
        for o in observations or []:
            by_product.setdefault(getattr(o, "product", None), []).append(o)
        for product, obs in by_product.items():
            if not product:
                continue
            try:
                est = prices.estimate(obs, product, tier, today=today)
            except Exception:
                continue
            unit = est.get("unit_price") if isinstance(est, dict) else None
            if unit is None:
                continue
            for item in self.materials:
                if product.replace("_", " ").lower() in item.lower():
                    self.materials[item] = float(unit)
                    self._source[item] = est.get("source", "invoice")
                    replaced += 1
        return replaced

    def as_dict(self):
        return {"region": self.region, "region_factor": self.region_factor,
                "region_name": REGIONS[self.region][1],
                "date": self.date, "basis": RATE_BASIS,
                "prelims_pct": self.prelims_pct, "ohp_pct": self.ohp_pct,
                "contingency_pct": self.contingency_pct,
                "materials": self.materials, "trades": self.trades,
                "sources": self._source}


def _money(x):
    return round(float(x), 2)


def price_bill(bill, card=None, *, estimate_class="concept",
               vat="standard", fees=True, today=None):
    """Price a quantities.bill() into a builder's estimate.

    Returns materials, labour, preliminaries, overhead and profit,
    contingency, professional fees, VAT and a range — with every line
    saying which rate it used and where that rate came from, and with
    UNPRICED items listed rather than silently dropped.
    """
    card = card or RateCard()
    if estimate_class not in CLASSES:
        raise ValueError(f"estimate_class must be one of {sorted(CLASSES)}")
    if vat not in VAT_RATES:
        raise ValueError(f"vat must be one of {sorted(VAT_RATES)}")
    rf = card.region_factor

    mat_lines, lab_lines, unpriced = [], [], []
    hours_by_trade = {}

    for trade_group, lines in (bill.get("groups") or {}).items():
        for L in lines or []:
            qty = float(L.get("quantity") or 0.0)
            if qty <= 0:
                continue
            item, unit = L["item"], L.get("unit", "")

            rate, src = card.material_rate(item)
            if rate is None:
                unpriced.append({"item": item, "quantity": qty, "unit": unit,
                                 "why": "no material rate on the card"})
            else:
                cost = qty * rate * rf
                mat_lines.append({
                    "trade": trade_group, "item": item, "quantity": qty,
                    "unit": unit, "rate": _money(rate), "rate_source": src,
                    "cost": _money(cost)})

            spec = card.labour_for(item)
            if spec:
                trade, hrs_per, _u = spec
                hours = qty * hrs_per
                hours_by_trade[trade] = hours_by_trade.get(trade, 0.0) + hours

    for trade, hours in sorted(hours_by_trade.items()):
        rate = card.trades.get(trade, 30.0)
        lab_lines.append({
            "trade": trade, "hours": round(hours, 1),
            "rate_per_hour": _money(rate * rf),
            "cost": _money(hours * rate * rf)})

    materials = sum(l["cost"] for l in mat_lines)
    labour = sum(l["cost"] for l in lab_lines)
    measured = materials + labour
    prelims = measured * card.prelims_pct
    subtotal = measured + prelims
    ohp = subtotal * card.ohp_pct
    construction = subtotal + ohp
    contingency = construction * card.contingency_pct
    build_total = construction + contingency

    fee_lines = []
    if fees:
        for key, (pct, note) in FEES.items():
            fee_lines.append({"item": key.replace("_", " ").title(),
                              "pct": pct, "cost": _money(construction * pct),
                              "note": note})
    fees_total = sum(f["cost"] for f in fee_lines)

    net = build_total + fees_total
    vat_rate, vat_note = VAT_RATES[vat]
    vat_amount = net * vat_rate
    gross = net + vat_amount

    cov = coverage(bill)
    lo, hi = CLASSES[estimate_class][0], CLASSES[estimate_class][1]
    # An incomplete bill widens the range upward: what is missing can
    # only add cost, never remove it.
    if cov["absent"]:
        hi = max(hi, 0.30 + 0.22 * len(cov["absent"]))
    card_rates = sum(1 for l in mat_lines if l["rate_source"] == "card")
    own_rates = len(mat_lines) - card_rates

    return {
        "available": True,
        "currency": "GBP",
        "estimate_class": estimate_class,
        "estimate_class_note": CLASSES[estimate_class][2],
        "region": card.region, "region_name": REGIONS[card.region][1],
        "region_factor": rf,
        "rate_card_date": card.date,
        "materials": {"lines": mat_lines, "total": _money(materials)},
        "labour": {"lines": lab_lines, "total": _money(labour),
                   "hours": round(sum(l["hours"] for l in lab_lines), 1)},
        "preliminaries": {"pct": card.prelims_pct, "total": _money(prelims),
                          "note": "scaffold, skip, welfare, plant, "
                                  "site supervision"},
        "overhead_profit": {"pct": card.ohp_pct, "total": _money(ohp)},
        "contingency": {"pct": card.contingency_pct,
                        "total": _money(contingency),
                        "note": "for what a massing model cannot see: "
                                "ground conditions, existing structure, "
                                "drainage diversions"},
        "professional_fees": {"lines": fee_lines, "total": _money(fees_total)},
        "totals": {
            "measured_works": _money(measured),
            "construction": _money(construction),
            "build_total": _money(build_total),
            "net": _money(net),
            "vat_rate": vat_rate, "vat": _money(vat_amount),
            "gross": _money(gross),
            "range_low": _money(gross * (1 + lo)),
            "range_high": _money(gross * (1 + hi)),
        },
        "vat_basis": vat_note,
        "unpriced": unpriced,
        "coverage": cov,
        "rate_provenance": {
            "from_card_indicative": card_rates,
            "from_your_own_rates": own_rates,
            "basis": RATE_BASIS,
            "confidence": ("low — every rate is an indicative default"
                           if own_rates == 0 else
                           f"{own_rates} of {len(mat_lines)} material rates "
                           f"are yours; the rest are indicative"),
        },
        "status": "PARTIAL" if cov["absent"] else "FULL",
        "excludes": [a["description"] for a in cov["absent"]],
        "disclaimer": (
            f"ESTIMATE, not a quotation. Class: {estimate_class} "
            f"({CLASSES[estimate_class][2]}). The realistic range is "
            f"£{_money(gross * (1 + lo)):,.0f} to "
            f"£{_money(gross * (1 + hi)):,.0f}. Rates are indicative "
            f"unless you have replaced them. VAT treatment is the "
            f"customer's to confirm — see HMRC Notice 708."
            + ("" if cov["complete"] else
               f" THIS IS A PARTIAL PRICE: it covers "
               f"{cov['priced_packages']} of {cov['total_packages']} work "
               f"packages and EXCLUDES "
               + ", ".join(a["package"].replace("_", " ")
                           for a in cov["absent"]) + ".")
        ),
    }


def calibrate(bill, gia_m2, *, known_cost=None, known_per_m2=None,
              card=None, vat="standard", estimate_class="concept",
              include_vat=True):
    """Scale the rate card so it reproduces a job YOU actually did.

    THE FEATURE THAT MAKES THIS MODULE HONEST AND USEFUL AT ONCE. The
    shipped rates are indicative and land low — measured at about
    £960/m2 against the £1,800-£3,200/m2 that small domestic work really
    costs, which is exactly what the sanity band is for. Rather than
    quietly inflating the defaults until the number looks plausible —
    which would be inventing data to hide inventing data — this takes
    ONE real job off you: what it cost, and how many square metres it
    was. The factor that reconciles the two is applied to the card, and
    from then on the estimate is calibrated to your business rather than
    to a guess.

    Returns (calibrated_card, report). A factor far from 1 is not an
    error; it is the size of the gap between generic rates and yours,
    and it is reported rather than swallowed.
    """
    card = card or RateCard()
    if gia_m2 <= 0:
        raise ValueError("calibration needs the floor area of this job")
    # A builder carries £/m2 in his head far more often than a total, so
    # take either. Whichever arrives becomes the same target.
    if known_per_m2 is not None:
        known_cost = float(known_per_m2) * gia_m2
    if not known_cost or known_cost <= 0:
        raise ValueError(
            "give either known_cost (what this job would cost you) or "
            "known_per_m2 (your usual rate for work like this)")
    base = price_bill(bill, card, estimate_class=estimate_class, vat=vat)
    modelled = (base["totals"]["gross"] if include_vat
                else base["totals"]["net"])
    if modelled <= 0:
        raise ValueError("the card produced no cost to calibrate against")
    # Only the direct rates are scaled: prelims, overhead and contingency
    # are percentages and already ride on top of them.
    factor = known_cost / modelled
    if not 0.2 <= factor <= 6.0:
        raise ValueError(
            f"calibration factor {factor:.2f} is implausible — check the "
            f"cost and area you gave (a £{known_cost:,.0f} job over "
            f"{gia_m2:g} m2 is £{known_cost / gia_m2:,.0f}/m2)")
    out = RateCard(region=card.region, prelims_pct=card.prelims_pct,
                   ohp_pct=card.ohp_pct,
                   contingency_pct=card.contingency_pct,
                   date=card.date)
    out.materials = {k: round(v * factor, 4) for k, v in card.materials.items()}
    out.trades = {k: round(v * factor, 2) for k, v in card.trades.items()}
    out._source = {k: "calibrated" for k in out.materials}
    report = {
        "factor": round(factor, 3),
        "reference_cost": _money(known_cost),
        "reference_gia_m2": gia_m2,
        "reference_per_m2": _money(known_cost / gia_m2),
        "card_produced_per_m2": _money(modelled / gia_m2),
        "note": (
            f"The shipped rates produced £{modelled / gia_m2:,.0f}/m2 for "
            f"this job; your real figure is £{known_cost / gia_m2:,.0f}/m2, "
            f"so every rate is multiplied by {factor:.2f}. Give it a second "
            f"and third job and the spread between the factors tells you "
            f"how consistent your pricing is."),
    }
    return out, report


def per_m2(priced, gia_m2):
    """£/m2, the number a builder compares jobs on — and the sanity check.

    A domestic job that prices out well under what domestic jobs cost is
    not a bargain, it is an incomplete bill. Saying that here, next to
    the number, is the whole point: the £/m2 figure is the fastest way
    for anyone who builds for a living to spot it.
    """
    if not gia_m2:
        return None
    gross = priced["totals"]["gross"] / gia_m2
    lo, hi = TYPICAL_GROSS_PER_M2
    if gross < lo:
        verdict = (f"FAR BELOW the £{lo:,.0f}-£{hi:,.0f}/m2 that small "
                   f"domestic work actually costs. Expected, because this "
                   f"bill excludes "
                   + ", ".join(a["package"].replace("_", " ")
                               for a in priced["coverage"]["absent"])
                   + ". Do not quote from it."
                   ) if priced["coverage"]["absent"] else (
                   f"below the usual £{lo:,.0f}-£{hi:,.0f}/m2 band — check "
                   f"the rates and the specification before relying on it")
    elif gross > hi:
        verdict = (f"above the usual £{lo:,.0f}-£{hi:,.0f}/m2 band — check "
                   f"for double-counting or an unusually high specification")
    else:
        verdict = f"inside the usual £{lo:,.0f}-£{hi:,.0f}/m2 band"
    if (gross < lo and not priced["coverage"]["absent"]
            and priced["rate_provenance"]["from_your_own_rates"] == 0):
        verdict += (". The bill is complete, so this is the SHIPPED RATES "
                    "being low rather than work being missing — calibrate "
                    "the card against one job you have really done "
                    "(estimate.calibrate) and it will price like your "
                    "business instead of like a default")
    return {
        "build_per_m2": _money(priced["totals"]["build_total"] / gia_m2),
        "gross_per_m2": _money(gross),
        "typical_band": list(TYPICAL_GROSS_PER_M2),
        "verdict": verdict,
        "note": "Compare against your own recent jobs — this is the "
                "fastest sanity check on any estimate.",
    }
