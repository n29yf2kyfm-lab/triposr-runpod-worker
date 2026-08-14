"""Paint film thickness as a repair-detection signal — pure stdlib.

WHY THIS MODULE EXISTS. Every other signal in this worker is a camera reading
a photo. Photos are where the product owner's real taxonomy — paint mismatch,
bad repair work, panel gaps — has essentially no public training data. A paint
depth gauge sidesteps that entirely: it is a NUMBER, taken by a professional
with a $200 instrument, and the physics is not ambiguous. Factory finish sits
in a known band; a resprayed panel carries an extra paint system on top of it;
filler under the paint puts the probe millimetres from the steel. Where vision
has to be trained, a measurement only has to be interpreted.

WHAT THIS MODULE WILL AND WILL NOT SAY. A thickness reading is evidence about
a panel's SURFACE, not a record of a car's HISTORY. "This panel has been
resprayed" is an assertion about the past that a gauge cannot make: paint
protection film adds 150-200 um on its own, a factory anti-stonechip coating
adds 50-60 um to a rocker, and a two-tone roof is a different film build from
the factory. So every output here is phrased as "the measurement is consistent
with X", carries its caveats inline, and never deletes or overrides what the
camera saw. That is the same rule analyze.py holds: a guess is never presented
as an observation.

--------------------------------------------------------------------------
THE NUMBERS, AND WHERE THEY COME FROM
--------------------------------------------------------------------------
Unit note: 1 mil = 25.4 um. Practitioners in the US work in mils, everyone
else in microns; the gauge switches, so this module stores um and converts.

FACTORY TOTAL FILM BUILD (all layers over the substrate: e-coat, primer,
basecoat, clearcoat):

  * "Most factory paint jobs seem to range from 4-7 mils (100-180 microns)."
    -- DeFelsko (coating-thickness instrument maker),
    https://www.defelsko.com/resources/how-to-use-paint-thickness-gauges-for-better-automotive-detailing
  * "since 2016 automotive paint thickness levels of global vehicle
    manufacturers have averaged between 110-125 microns (~4.3-4.9 mils)";
    "average total paint thickness on contemporary OEM (factory) vehicles
    ranges between 95-125 microns (~3.7-4.3 mils)"; "Ford and General Motors
    consistently produce vehicles with OEM (factory) paint systems as low as
    95-105 microns (~3.7-4.15 mils)."
    -- OCD Car Care, PTG user guide,
    https://www.ocdcarcare.com/auto-detailing-articles/automotive-paint-thickness-gauge-ptg-user-guide/
  * Modern cars (post-2007) typically 100-140 um and rarely above 190 um.
    -- New Old Cars, "What a Paint Thickness Gauge REALLY Tells You",
    https://newoldcars.com/what-a-paint-thickness-gauge-really-tells-you/

  Clearcoat alone is ~40% of the system: 38-50 um (~1.5-2.0 mils)
  (OCD Car Care); DeFelsko quotes 35-50 um (1.5-2.0 mils) for clearcoat and
  notes manufacturers permit removing at most 0.3 mils / 8 um in polishing.

REGIONAL / MANUFACTURER SPREAD. Real, but smaller than folklore suggests:

  * German brands ~4.0-5.5 mils (102-140 um); Japanese brands ~3.5-4.5 mils
    (89-114 um). Measured single models: Audi A4L 134.39 um, Mercedes C-Class
    116.58 um, BMW 3 Series 113.58 um, VW Touareg 110.26 um, Lexus ES
    128.98 um, Nissan Sylphy 104.91 um, Honda Fit 93.34 um.
    -- iNEWS measured comparison,
    https://inf.news/en/auto/4e9af07b413030e98133f08d1c57b397.html
  * Per-brand German inspection reference table (this is the same source
    behind the owner's 97-row `oem_paint_thickness_etari`): Audi A5/A6/A7/A8
    ~100; Audi Q3/Q5/Q7 114-147; BMW X1 110; BMW X3/M6/5-series 89-100; BMW
    X5/X6 120-165; Ford Focus 156-160; Mercedes C/E 230-250; VW
    Touareg/Tiguan 70-85. Method note from the same page: "take the measuring
    of the standard painting thickness on the roof, because the roof unlikely
    to be damaged."
    -- ETARI GmbH, https://etari.de/en/standartlackdicke-lackdickentabelle/
  * Ferrari (powder-coat primer) 150-200 um minimum; BMW Dingolfing ~120 um;
    Porsche Leipzig ~130 um; Rolls-Royce 150+ um after wet sanding.
    -- New Old Cars (above).

  NO SOURCED FIGURE WAS FOUND for Korean marques (Hyundai/Kia/Genesis) as a
  group, so this module does NOT assert one — they fall through to the global
  default at reduced confidence. An absent number beats an invented one.

SUBSTRATE AND PANEL EFFECTS — the classic false positives:

  * Plastic bumper covers cannot be read at all by the magnetic (ferrous) or
    eddy-current (non-ferrous) probes that every cheap gauge uses; they need
    an ULTRASONIC gauge. So "no reading" on a bumper means the wrong probe,
    NOT filler.
    -- DeFelsko, https://www.defelsko.com/resources/automotive-paint-inspection-paint-meters
    (steel = magnetic, aluminium = eddy current, plastic/fibreglass =
    ultrasonic); Linshang, https://www.linshangtech.com/tech/tech331.html
  * On ADAS-equipped bumpers GM caps refinish at 13 mils (330 um) so the
    radar still works — i.e. a legitimately painted plastic bumper can sit at
    triple a steel panel's factory figure.
    -- DeFelsko ADAS note,
    https://www.defelsko.com/resources/measuring-paint-thickness-on-automotive-plastic-bumpers-fascias-with-advanced-driver-assistance-systems-adas
  * Rockers/sills carry PVC or urethane anti-stonechip: +50-60 um or more,
    and "some SUVs may have 17 mils (430 microns) on their rocker panels"
    while "some vehicles may only have 3 mils (75 microns) ... on the roof."
    -- New Old Cars; DeFelsko detailing guide.
  * Basecoat film build is colour-dependent: white ~20 um, red/yellow up to
    ~30 um, silver ~10 um. -- New Old Cars.
  * Take readings "approximately one inch from any edge" and near seams; film
    builds thin on a sharp edge and thick on a flat horizontal.
    -- DeFelsko paint-meter guide.

WHAT A HIGH READING MEANS:

  * ">160 to 300 microns suggests that a panel has been repainted"; repainted
    surfaces "often ... 150 to 300 um due to additional layers of primer and
    paint." Readings above 10 mils (254 um) commonly flag repaint or filler.
    -- OCD Car Care; Dr. Beasley's,
    https://www.drbeasleys.com/blog/2025/04/30/how-to-use-a-paint-thickness-gauge
  * The RELATIVE test is the strong one: "a difference of 40+ microns between
    adjacent panels is a red flag, especially on modern cars", while normal
    panel-to-panel manufacturing variation is roughly +/-15 um. And crucially:
    "A repainted panel can read substantially lower than 200 microns" — a
    skim respray over sanded factory paint can land inside the factory band.
    So a factory-range reading is NOT proof of no respray.
    -- New Old Cars.
  * Filler: "Any 'N/A' meter reading, or inability of a meter to take a
    reading is, usually a clear indication of body filler work."
    -- OCD Car Care. The physics behind that: the Elcometer 311, the standard
    professional automotive paint meter, reads 0-500 um / 0-20 mils
    (https://www.elcometer.com/en/elcometer-311-automotive-paint-meter.html),
    whereas 3M permits Bondo body filler up to 1/4 inch — 6350 um, twelve
    times the top of the gauge's range
    (https://www.3m.com/3M/en_US/bondo-us/). Filler therefore does not read
    "high"; it reads NOTHING, or it pins the gauge.

PAINT TYPE. Metallic and pearl systems measure thicker than solids from the
same maker because more coats are applied, and a tri-coat is base + mid +
clear rather than base + clear
(https://help.scratcheshappen.com/help/what-is-a-tri-coat-color). No
published micron delta for "tri-coat vs solid" was found, so this module does
not invent one: it widens the expected UPPER bound by one basecoat's worth of
film — the 15-25 um basecoat figure cited above, rounded to 30 um for
tolerance — and marks the allowance as DERIVED, not measured.

PPF AND COATINGS. Paint protection film is 8-12 mils / 150-200 um in its own
right; a ceramic coating is 1-2 um per layer, 5-15 um total. PPF alone can
therefore push a perfectly original panel past every respray threshold above,
which is why it is a first-class caveat on every elevated reading and why the
caller is asked whether film is present.
-- https://titancoatings.us/paint-protection-film-thickness/ ,
   https://www.chemicalguys.com/blogs/exterior-how-tos/ppf-vs-ceramic-coating

--------------------------------------------------------------------------
HOW IT PLUGS INTO THIS WORKER
--------------------------------------------------------------------------
`readings_to_findings()` emits findings in EXACTLY the shape analyze.py
produces, so severity.py, repair.py, fusion.py and report.py consume them with
no branching. Two new taxonomy ids carry them: `prior_refinish` (cosmetically
nothing is wrong; the car's VALUE is what moved) and `body_filler` (a
structural candidate, because filler is what hides a repaired dent).

`fuse_with_vision()` reconciles the measurement with the camera. Neither side
is allowed to delete the other — thickness that contradicts a visual paint
call lowers its confidence and says so, it does not silence it.
"""
from taxonomy import (PANELS, DAMAGE_TYPES, clamp_severity, canonical_panel)

MIL_UM = 25.4          # 1 mil = 25.4 microns


def um_to_mils(um):
    return round(um / MIL_UM, 2)


def mils_to_um(mils):
    return round(mils * MIL_UM, 1)


# --- the reference table --------------------------------------------------
# SCHEMA — one row per (make, model-ish, era, panel class):
#
#   make          str, lowercased marque                     required
#   model         str or None; None = every model of the make
#   year_start    int or None (inclusive)                    None = any
#   year_end      int or None (inclusive)                    None = any
#   panel_class   one of PANEL_CLASSES; "body" = painted metal skin
#   min_um        int, low end of the factory band
#   max_um        int, high end of the factory band
#   source        str, where the number came from — MANDATORY
#   confidence    float 0-1, how much this row is trusted
#   note          str, conflicts / caveats, may be ""
#
# The owner's MASTER_paint_thickness_unified (1,357 rows: make, model, year,
# min_um, max_um, avg_um, avg_mils, oem_range_mils, source, confidence) maps
# onto this one-to-one — `year` becomes year_start=year_end, oem_range_mils is
# redundant with min/max, avg_um is not needed by the classifier. Load it with
# `load_table(rows)` and pass the result as `table=`; the built-in table below
# is a PLACEHOLDER so the logic is testable today and MUST be replaced.
PANEL_CLASSES = ("body", "roof", "rocker", "plastic_bumper", "not_paintable")

TABLE_IS_PLACEHOLDER = True

REFERENCE_TABLE = [
    # -- ETARI per-model reference (the source behind oem_paint_thickness_etari)
    dict(make="audi", model="a5", year_start=None, year_end=None,
         panel_class="body", min_um=90, max_um=110, confidence=0.6,
         source="ETARI GmbH standard paint thickness table",
         note="published as a single ~100 um figure; +/-10 um applied"),
    dict(make="audi", model="a6", year_start=None, year_end=None,
         panel_class="body", min_um=90, max_um=110, confidence=0.6,
         source="ETARI GmbH standard paint thickness table", note=""),
    dict(make="audi", model="q5", year_start=None, year_end=None,
         panel_class="body", min_um=114, max_um=147, confidence=0.6,
         source="ETARI GmbH standard paint thickness table", note=""),
    dict(make="audi", model="q7", year_start=None, year_end=None,
         panel_class="body", min_um=114, max_um=147, confidence=0.6,
         source="ETARI GmbH standard paint thickness table", note=""),
    dict(make="bmw", model="x1", year_start=None, year_end=None,
         panel_class="body", min_um=100, max_um=120, confidence=0.6,
         source="ETARI GmbH standard paint thickness table",
         note="published as ~110 um; +/-10 um applied"),
    dict(make="bmw", model="x3", year_start=None, year_end=None,
         panel_class="body", min_um=89, max_um=100, confidence=0.6,
         source="ETARI GmbH standard paint thickness table", note=""),
    dict(make="bmw", model="5 series", year_start=None, year_end=None,
         panel_class="body", min_um=89, max_um=100, confidence=0.6,
         source="ETARI GmbH standard paint thickness table", note=""),
    dict(make="bmw", model="x5", year_start=None, year_end=None,
         panel_class="body", min_um=120, max_um=165, confidence=0.6,
         source="ETARI GmbH standard paint thickness table", note=""),
    dict(make="bmw", model="3 series", year_start=None, year_end=None,
         panel_class="body", min_um=104, max_um=124, confidence=0.55,
         source="iNEWS measured comparison (113.58 um mean)",
         note="measured mean, not an OEM spec; +/-10 um applied"),
    dict(make="ford", model="focus", year_start=None, year_end=None,
         panel_class="body", min_um=156, max_um=160, confidence=0.5,
         source="ETARI GmbH standard paint thickness table",
         note="notably above Ford's 95-105 um house average per OCD Car Care"),
    dict(make="volkswagen", model="tiguan", year_start=None, year_end=None,
         panel_class="body", min_um=70, max_um=85, confidence=0.6,
         source="ETARI GmbH standard paint thickness table", note=""),
    dict(make="volkswagen", model="touareg", year_start=None, year_end=None,
         panel_class="body", min_um=70, max_um=85, confidence=0.5,
         source="ETARI GmbH standard paint thickness table",
         note="conflicts with iNEWS measured 110.26 um on the same model"),
    dict(make="mercedes-benz", model="c class", year_start=None, year_end=None,
         panel_class="body", min_um=110, max_um=250, confidence=0.3,
         source="ETARI (230-250 um) vs iNEWS measured (116.58 um)",
         note="SOURCES DISAGREE BY ~2x. Band spans both, confidence dropped "
              "accordingly — this row exists to show the schema handling a "
              "conflict, and is exactly the case the owner's dataset should "
              "settle."),
    dict(make="honda", model="fit", year_start=None, year_end=None,
         panel_class="body", min_um=83, max_um=103, confidence=0.5,
         source="iNEWS measured comparison (93.34 um mean)", note=""),
    dict(make="lexus", model="es", year_start=None, year_end=None,
         panel_class="body", min_um=119, max_um=139, confidence=0.5,
         source="iNEWS measured comparison (128.98 um mean)", note=""),
    dict(make="ferrari", model=None, year_start=None, year_end=None,
         panel_class="body", min_um=150, max_um=200, confidence=0.5,
         source="New Old Cars — powder-coat primer raises the floor", note=""),
    dict(make="porsche", model=None, year_start=None, year_end=None,
         panel_class="body", min_um=115, max_um=145, confidence=0.5,
         source="New Old Cars — Porsche Leipzig ~130 um; +/-15 um applied",
         note=""),
]

# Make-level fallback, used when no model row matches. Keyed by marque.
MAKE_DEFAULTS = {
    # German group: ~4.0-5.5 mils (iNEWS)
    "audi": (102, 140), "bmw": (102, 140), "mercedes-benz": (102, 140),
    "volkswagen": (102, 140), "porsche": (102, 140), "mini": (102, 140),
    # Japanese group: ~3.5-4.5 mils (iNEWS)
    "toyota": (89, 114), "honda": (89, 114), "nissan": (89, 114),
    "mazda": (89, 114), "subaru": (89, 114), "lexus": (89, 114),
    "mitsubishi": (89, 114), "suzuki": (89, 114), "acura": (89, 114),
    "infiniti": (89, 114),
    # US: Ford and GM "as low as 95-105 um" (OCD Car Care); upper bound left
    # at the global contemporary 125 um rather than invented.
    "ford": (95, 125), "chevrolet": (95, 125), "gmc": (95, 125),
    "cadillac": (95, 125), "buick": (95, 125), "lincoln": (95, 125),
    # NO SOURCED KOREAN FIGURE — hyundai/kia/genesis deliberately absent so
    # they fall to the global default with the lower confidence that implies.
}
MAKE_DEFAULT_SOURCE = ("iNEWS measured comparison (German ~4.0-5.5 mils, "
                       "Japanese ~3.5-4.5 mils); OCD Car Care (Ford/GM "
                       "95-105 um)")

# Global default: the union of "most factory paint jobs 100-180 um"
# (DeFelsko) and the 95 um floor Ford/GM reach (OCD Car Care).
GLOBAL_DEFAULT_UM = (95, 180)
GLOBAL_DEFAULT_SOURCE = ("DeFelsko: most factory finishes 4-7 mils "
                         "(100-180 um); OCD Car Care: Ford/GM floor 95 um")

# Confidence attached to WHICH TIER answered the lookup. This is the honesty
# dial: a global default answering for a car we have no data on must not
# produce the same confidence as an exact model row.
TIER_CONFIDENCE = {
    "model_year": 0.90,
    "model": 0.80,
    "make_era": 0.60,
    "make": 0.55,
    "global": 0.35,
}

# --- panel classification -------------------------------------------------
# Which panels are painted metal, which are plastic (unreadable on a standard
# gauge), which carry a factory anti-stonechip coating, and which are not
# painted at all.
# Plastic-skinned panels. Mirror caps and grilles belong here alongside the
# bumper covers: a magnetic or eddy-current probe reads NOTHING on any of
# them, and without this a painted plastic mirror cap would return the
# no-reading that this module treats as the filler signal on metal. The band
# used for the whole class is the bumper's, because bumpers are the plastic
# panel anyone actually measures and the classifier refuses to call a respray
# on plastic regardless.
_PLASTIC_PANELS = {"front_bumper", "rear_bumper", "grille",
                   "left_mirror", "right_mirror"}
_ROCKER_PANELS = {"left_rocker", "right_rocker"}
_NOT_PAINTABLE = {
    "windshield", "rear_windshield", "left_front_glass", "right_front_glass",
    "front_left_headlight", "front_right_headlight",
    "rear_left_light", "rear_right_light",
    "front_left_wheel", "front_right_wheel",
    "rear_left_wheel", "rear_right_wheel",
}

# Rockers/sills: PVC or urethane anti-stonechip adds 50-60 um or more, and
# SUV rockers reach 430 um from the factory (New Old Cars; DeFelsko). The
# allowance is added to the UPPER bound only.
ROCKER_ALLOWANCE_UM = 60

# Plastic bumper covers are a different world: GM caps ADAS bumper refinish at
# 13 mils (330 um), so a factory-plus-legitimate-refinish bumper can sit where
# a steel panel would be screaming filler. This band is deliberately wide and
# the classifier refuses to call a respray on it at all.
PLASTIC_BUMPER_UM = (80, 330)
PLASTIC_BUMPER_SOURCE = ("DeFelsko/GM: ADAS bumper refinish must not exceed "
                         "13 mils (330 um)")

# Tri-coat / pearl allowance. DERIVED, not measured: a tri-coat adds a mid
# coat to base+clear, and published basecoat film build is 15-25 um, rounded
# up to 30 for tolerance. No published tri-coat-vs-solid delta was found.
PAINT_SYSTEM_ALLOWANCE_UM = {
    "solid": 0,
    "metallic": 0,
    "pearl": 30,
    "tri_coat": 30,
    "tricoat": 30,
}

# --- thresholds -----------------------------------------------------------
# ABSOLUTE tests, against the expected factory band.
FACTORY_TOLERANCE_UM = 15      # normal panel-to-panel manufacturing variation
                               # (New Old Cars: "+/-15 um are normal")
REPAINT_DELTA_UM = 50          # "an entire panel reading 2-3 mils higher than
                               # factory panels suggests a full repaint"
                               # (Dr. Beasley's) — 2 mils = 50.8 um
REPAINT_RATIO = 1.5            # ...or half again the factory band's top, for
                               # cars whose factory band is already thin.
FILLER_ABSOLUTE_UM = 500       # the top of the Elcometer 311's range; filler
                               # runs to 6350 um (3M), so anything at or past
                               # the gauge ceiling is filler-shaped, not paint.

# RELATIVE tests, against an undamaged reference panel on the SAME car. This
# is the strong test — it cancels out marque, era, colour and paint system in
# one stroke, which is why practitioners lead with it.
REL_FACTORY_DELTA_UM = 15      # within normal variation
REL_REPAINT_DELTA_UM = 40      # "a difference of 40+ microns between adjacent
                               # panels is a red flag" (New Old Cars)
# There is deliberately NO relative filler threshold. Filler is not a large
# version of paint, it is a different order of magnitude: paint is applied in
# microns and filler in millimetres (3M permits Bondo to 1/4 inch = 6350 um).
# A panel reading 190 um above the roof has one extra PAINT SYSTEM on it —
# that is a respray, and repainted panels are quoted at 150-300 um. Calling
# that filler because the relative gap looked big would convert the commonest
# respray signature into the most serious accusation the report can make. So
# filler is decided ABSOLUTELY, on the gauge topping out, and nothing else.

# Panels preferred as the same-car reference, in order. The roof is the
# industry's first choice ("the probability of an accident on the roof is the
# smallest" — Linshang; ETARI says the same).
REFERENCE_PREFERENCE = ("roof", "tailgate", "hood")

CLASSES = ("factory", "inconclusive", "refinished", "filler_suspect",
           "not_measurable")


# --- normalisation --------------------------------------------------------

def normalize_make(make):
    if not make:
        return None
    s = str(make).strip().lower().replace("_", " ")
    s = " ".join(s.split())
    aliases = {
        "mercedes": "mercedes-benz", "merc": "mercedes-benz",
        "mercedes benz": "mercedes-benz", "benz": "mercedes-benz",
        "vw": "volkswagen", "chevy": "chevrolet", "gm": "chevrolet",
        "landrover": "land rover", "alfa": "alfa romeo",
    }
    return aliases.get(s, s)


def normalize_model(model):
    """'3-Series' / '3 Series' / '3series' -> '3 series'; 'C-Class' -> 'c class'.

    Deliberately light: the owner's 1,357-row table carries the real model
    strings, and an over-clever normaliser that folds 'A6' into 'A6 Allroad'
    would answer the wrong band with high confidence — the one failure mode
    this lookup must not have.
    """
    if not model:
        return None
    s = str(model).strip().lower().replace("-", " ").replace("_", " ")
    s = " ".join(s.split())
    for word in ("series", "class"):
        if s.endswith(word) and not s.endswith(" " + word):
            s = s[:-len(word)].strip() + " " + word
    return s or None


def panel_class(panel):
    """Which measurement world a panel lives in."""
    p = canonical_panel(panel) or panel
    if p in _NOT_PAINTABLE:
        return "not_paintable"
    if p in _PLASTIC_PANELS:
        return "plastic_bumper"
    if p in _ROCKER_PANELS:
        return "rocker"
    if p == "roof":
        return "roof"
    return "body"


def load_table(rows):
    """Adapt the owner's dataset rows onto the schema above.

    Accepts MASTER_paint_thickness_unified / oem_paint_thickness /
    oem_paint_thickness_etari shapes: make, model, year (or year_start/
    year_end), min_um/max_um (or expected_min_um/expected_max_um, or
    oem_range_mils), source, confidence. Rows without a usable band are
    dropped rather than guessed at.
    """
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        lo = _first_num(r, "min_um", "expected_min_um", "min_micron")
        hi = _first_num(r, "max_um", "expected_max_um", "max_micron")
        if lo is None or hi is None:
            avg = _first_num(r, "avg_um", "expected_avg_um")
            if avg is None:
                mils = r.get("oem_range_mils") or r.get("expected_range_mils")
                lo, hi = _parse_mils_range(mils)
                if lo is None:
                    continue
            else:
                lo, hi = avg - 10, avg + 10
        if hi < lo:
            lo, hi = hi, lo
        year = _first_num(r, "year")
        out.append({
            "make": normalize_make(r.get("make")),
            "model": normalize_model(r.get("model")),
            "year_start": _int_or_none(r.get("year_start")) or
                          (int(year) if year else None),
            "year_end": _int_or_none(r.get("year_end")) or
                        (int(year) if year else None),
            "panel_class": r.get("panel_class") or "body",
            "min_um": float(lo),
            "max_um": float(hi),
            "source": str(r.get("source") or "unattributed dataset row"),
            "confidence": _clamp01(r.get("confidence"), 0.6),
            "note": str(r.get("note") or ""),
        })
    return out


def _parse_mils_range(text):
    """'4-6' / '4.0 - 6.5 mils' -> (um, um). Returns (None, None) if unusable."""
    if text is None:
        return (None, None)
    s = str(text).lower().replace("mils", "").replace("mil", "")
    s = s.replace("–", "-").replace("—", "-").strip()
    parts = [p.strip() for p in s.split("-") if p.strip()]
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return (None, None)
    if not nums:
        return (None, None)
    if len(nums) == 1:
        return (mils_to_um(nums[0]) - 10, mils_to_um(nums[0]) + 10)
    return (mils_to_um(min(nums)), mils_to_um(max(nums)))


# --- the lookup -----------------------------------------------------------

def expected_range(make, model=None, year=None, panel=None,
                   paint_system=None, table=None):
    """Expected FACTORY film thickness for (make, model, year, panel).

    Resolution tiers, most specific first — the tier that answered is returned
    alongside a confidence, so a caller can tell "we know this car" from "we
    guessed from a global average":

        model_year  exact make + model, year inside the row's era   0.90
        model       exact make + model, era-agnostic                0.80
        make_era    make row, year outside the modern era window    0.60
        make        make-level regional average                     0.55
        global      the 95-180 um everybody-average                 0.35

    Panel class is applied ON TOP of whichever tier answered: a plastic bumper
    ignores the body band entirely, a rocker gets its anti-stonechip
    allowance, glass/lamps/wheels return not_paintable.

    Returns a dict:
        min_um, max_um        the expected band, panel-adjusted
        tier, confidence      which tier answered and how much to trust it
        source, note          provenance, always populated
        panel_class           body | roof | rocker | plastic_bumper |
                              not_paintable
        adjustments           list of human-readable band adjustments applied
    """
    table = REFERENCE_TABLE if table is None else table
    mk = normalize_make(make)
    md = normalize_model(model)
    yr = _int_or_none(year)
    pcls = panel_class(panel) if panel else "body"

    if pcls == "not_paintable":
        return {
            "min_um": None, "max_um": None, "tier": "not_applicable",
            "confidence": 0.0, "source": "n/a",
            "note": "this panel is not a painted body surface",
            "panel_class": pcls, "adjustments": [],
        }

    if pcls == "plastic_bumper":
        lo, hi = PLASTIC_BUMPER_UM
        return {
            "min_um": float(lo), "max_um": float(hi),
            "tier": "panel_class", "confidence": 0.4,
            "source": PLASTIC_BUMPER_SOURCE,
            "note": ("plastic bumper covers need an ultrasonic gauge; a "
                     "magnetic or eddy-current probe reads nothing here, and "
                     "a legitimately refinished bumper can legally reach "
                     "330 um"),
            "panel_class": pcls, "adjustments": ["plastic bumper band"],
        }

    tier = source = note = None
    lo = hi = None
    base_conf = None

    # tier 1/2 — model rows
    if mk and md:
        for row in table:
            if row.get("make") != mk:
                continue
            if normalize_model(row.get("model")) != md:
                continue
            if row.get("panel_class") not in (None, "body", pcls):
                continue
            ys, ye = row.get("year_start"), row.get("year_end")
            in_era = (yr is not None and ys is not None and ye is not None
                      and ys <= yr <= ye)
            candidate_tier = "model_year" if in_era else "model"
            # a year-scoped row that the year falls outside is not a match
            if ys is not None and ye is not None and yr is not None \
                    and not in_era:
                continue
            if tier is None or candidate_tier == "model_year":
                tier, lo, hi = candidate_tier, row["min_um"], row["max_um"]
                source, note = row.get("source", ""), row.get("note", "")
                base_conf = row.get("confidence")
            if tier == "model_year":
                break

    # tier 2b — make-wide rows in the table (model=None)
    if tier is None and mk:
        for row in table:
            if row.get("make") == mk and row.get("model") in (None, ""):
                tier, lo, hi = "model", row["min_um"], row["max_um"]
                source, note = row.get("source", ""), row.get("note", "")
                base_conf = row.get("confidence")
                break

    # tier 3/4 — make-level regional average
    if tier is None and mk in MAKE_DEFAULTS:
        lo, hi = MAKE_DEFAULTS[mk]
        source, note = MAKE_DEFAULT_SOURCE, ""
        # Pre-2007 cars used thicker e-coats and stone-chip primers (New Old
        # Cars) but no per-year figure is published, so we WIDEN rather than
        # shift, and drop a tier.
        if yr is not None and yr < 2007:
            tier = "make_era"
            hi = hi * 1.4
            note = ("pre-2007: band widened 40% because e-coat and "
                    "stone-chip primers ran thicker; no per-year figure is "
                    "published, so this is a widening, not a measurement")
        else:
            tier = "make"

    # tier 5 — global
    if tier is None:
        lo, hi = GLOBAL_DEFAULT_UM
        tier, source = "global", GLOBAL_DEFAULT_SOURCE
        note = (f"no reference row for {mk or 'this make'}"
                + (f" {md}" if md else "") + " — global average used")
        if yr is not None and yr < 2007:
            hi = hi * 1.4
            note += "; pre-2007 band widened 40%"

    adjustments = []
    if pcls == "rocker":
        hi = hi + ROCKER_ALLOWANCE_UM
        adjustments.append(
            f"+{ROCKER_ALLOWANCE_UM} um rocker anti-stonechip allowance")

    ps = str(paint_system or "").strip().lower().replace("-", "_")
    ps_allow = PAINT_SYSTEM_ALLOWANCE_UM.get(ps, 0)
    if ps_allow:
        hi = hi + ps_allow
        adjustments.append(
            f"+{ps_allow} um {ps} mid-coat allowance (derived from the "
            f"15-25 um published basecoat film build, not a measured "
            f"tri-coat delta)")

    conf = TIER_CONFIDENCE.get(tier, 0.35)
    if base_conf is not None:
        # a row's own confidence caps the tier's — a conflicted row cannot
        # ride an exact-model match to 0.90
        conf = min(conf, float(base_conf) + 0.1)

    return {
        "min_um": round(float(lo), 1),
        "max_um": round(float(hi), 1),
        "tier": tier,
        "confidence": round(_clamp_conf(conf, 0.35), 2),
        "source": source or "",
        "note": note or "",
        "panel_class": pcls,
        "adjustments": adjustments,
    }


# --- a reading ------------------------------------------------------------

def normalize_reading(raw):
    """Coerce one panel's gauge session into a canonical reading.

    Input (what the app sends):
        {"panel": "front_left_door",
         "points_um": [305, 312, 298, 320],      # or "value_um": 312
         "substrate": "steel"|"aluminium"|"plastic"|None,
         "no_reading": False,                     # gauge showed N/A
         "over_range": False,                     # gauge pinned at its max
         "gauge": "fn"|"f"|"n"|"ultrasonic"|None, # probe technology
         "has_film": True|False|None}             # PPF / wrap known present?

    A no-reading or over-range session is kept, not dropped: on steel that IS
    the filler signal, and on plastic it is the wrong-probe signal. Losing it
    would throw away the most diagnostic thing the gauge does.
    """
    if not isinstance(raw, dict):
        raw = {"value_um": raw}
    panel = canonical_panel(raw.get("panel")) or "body_other"
    pts = [p for p in (_num_or_none(x) for x in (raw.get("points_um") or []))
           if p is not None and p >= 0]
    if not pts:
        v = _num_or_none(raw.get("value_um"))
        if v is not None and v >= 0:
            pts = [v]
    value = (sum(pts) / len(pts)) if pts else None
    spread = (max(pts) - min(pts)) if len(pts) > 1 else 0.0
    return {
        "panel": panel,
        "panel_class": panel_class(panel),
        "points_um": [round(p, 1) for p in pts],
        "n_points": len(pts),
        "value_um": round(value, 1) if value is not None else None,
        "spread_um": round(spread, 1),
        "substrate": (str(raw.get("substrate")).lower()
                      if raw.get("substrate") else None),
        "gauge": (str(raw.get("gauge")).lower() if raw.get("gauge") else None),
        # `no_reading` is EXPLICIT ONLY. It used to be set whenever no number
        # arrived, which quietly turned every malformed entry — a typo, a
        # dropped field, a string where a list belonged — into the strongest
        # accusation this module can make, because a no-reading on metal is
        # the filler signal. "The inspector's gauge would not read" and "the
        # payload was broken" must never be the same value.
        "no_reading": bool(raw.get("no_reading")),
        "over_range": bool(raw.get("over_range")),
        "has_film": raw.get("has_film"),
        # usable at all? Either a number arrived, or the caller deliberately
        # reported that the gauge produced nothing.
        "valid": bool(pts) or bool(raw.get("no_reading")) \
                 or bool(raw.get("over_range")),
    }


def pick_reference(readings):
    """Choose the same-car reference reading, roof first.

    Relative comparison beats absolute comparison because it cancels marque,
    era, colour and paint system at once — so getting the reference right is
    the single highest-leverage thing this module does. Preference order is
    the industry's: roof, then tailgate, then hood; failing all three, the
    MEDIAN body reading, because the median of a set of panels is unlikely to
    be the resprayed one.

    Returns (value_um, panel_id, basis) or (None, None, "none").
    """
    usable = [r for r in readings
              if r.get("value_um") is not None
              and not r.get("no_reading") and not r.get("over_range")
              and r.get("panel_class") in ("body", "roof")]
    if not usable:
        return (None, None, "none")
    for pref in REFERENCE_PREFERENCE:
        for r in usable:
            if r["panel"] == pref:
                return (r["value_um"], pref, "preferred_panel")
    vals = sorted(r["value_um"] for r in usable)
    if len(vals) < 3:
        # two panels cannot vote; a median of two is just an average of a
        # possibly-repaired pair, which is worse than no reference at all
        return (None, None, "insufficient")
    mid = vals[len(vals) // 2]
    panel = next(r["panel"] for r in usable if r["value_um"] == mid)
    return (mid, panel, "median_of_panels")


# --- classification -------------------------------------------------------

def classify_reading(reading, expected, reference_um=None,
                     reference_panel=None):
    """Classify one panel's reading as factory / refinished / filler / etc.

    Returns a dict:
        class          one of CLASSES
        confidence     0-1, how much to trust the classification
        basis          "relative" | "absolute" | "unmeasurable"
        ratio          reading / expected max, or None
        delta_expected um above the expected max (negative = inside band)
        delta_reference um above the same-car reference, or None
        caveats        the false positives that could explain this reading
        reasons        the arithmetic, in words, for the report

    THE ORDER OF TESTS IS THE DESIGN.

      1. Unmeasurable cases first, because a "no reading" means opposite
         things on plastic (wrong probe) and steel (filler).
      2. FILLER, absolutely and only absolutely. Filler is millimetres where
         paint is microns, so its signature is the gauge running out of
         range — not a large relative gap, which is what an ordinary respray
         produces.
      3. The RELATIVE test where a same-car reference exists — it is the
         stronger test for refinishing and every source says so, because it
         cancels marque, era, colour and paint system at once.
      4. The ABSOLUTE test against the expected band otherwise.
      5. A reading that clears "factory" is never upgraded past
         "inconclusive" unless it clears BOTH the +50 um and the 1.5x gates,
         so a car with a thin factory band cannot be accused on a 20 um
         excess.
    """
    r = reading
    pcls = r.get("panel_class", "body")
    caveats, reasons = [], []
    conf = float(expected.get("confidence", 0.35))

    # --- 1. unmeasurable -------------------------------------------------
    if not r.get("valid", True):
        return _result("not_measurable", 0.0, "unmeasurable", None, None, None,
                       [], ["no usable reading was supplied for this panel — "
                            "this is a missing measurement, not a finding"])

    if pcls == "not_paintable":
        return _result("not_measurable", 0.0, "unmeasurable", None, None, None,
                       ["this panel is not a painted body surface"],
                       ["no paint film to measure"])

    if r.get("no_reading") and pcls == "plastic_bumper":
        return _result(
            "not_measurable", 0.0, "unmeasurable", None, None, None,
            ["magnetic and eddy-current probes cannot read a plastic bumper "
             "cover at all — an ultrasonic gauge is required"],
            ["no reading on a plastic panel means the wrong probe, not filler"])

    if r.get("no_reading") or r.get("over_range"):
        # On metal, this is the textbook filler signal: the professional
        # meter's range tops out at 500 um while filler runs to 6350 um.
        return _result(
            "filler_suspect", min(0.75, conf + 0.25), "absolute",
            None, None, None,
            ["confirm the gauge was set to the right substrate (steel vs "
             "aluminium) before treating a no-reading as filler",
             "heavy paint protection film can also defeat a reading"],
            ["gauge returned no reading or pinned at its range limit on a "
             "metal panel; body filler is the usual cause"])

    value = r.get("value_um")
    if value is None:
        return _result("not_measurable", 0.0, "unmeasurable", None, None, None,
                       [], ["no numeric reading supplied"])

    lo, hi = expected.get("min_um"), expected.get("max_um")

    # measurement quality: one point is a poke, four points across the panel
    # is a measurement; a wide spread means the panel is not uniform
    n = r.get("n_points", 0)
    if n >= 4:
        conf = min(1.0, conf + 0.10)
        reasons.append(f"{n} points taken across the panel")
    elif n <= 1:
        conf = max(0.0, conf - 0.15)
        caveats.append("only one point was taken on this panel; film build "
                       "varies across a panel and near edges")
    if r.get("spread_um", 0) >= 60:
        caveats.append(
            f"readings varied by {r['spread_um']:.0f} um across the panel — "
            f"a localised repair, or a point taken too near an edge or seam")

    if r.get("has_film"):
        caveats.append("paint protection film is present and adds 150-200 um "
                       "on its own; this reading cannot be interpreted as "
                       "paint alone")
        conf = max(0.0, conf - 0.35)
    elif r.get("has_film") is None:
        caveats.append("it is not recorded whether paint protection film or a "
                       "vinyl wrap is fitted; film adds 150-200 um")

    if pcls == "rocker":
        caveats.append("sills/rockers carry a factory anti-stonechip coating "
                       "worth 50-60 um or more")
    if pcls == "plastic_bumper":
        caveats.append("bumper covers are refinished routinely and legally up "
                       "to 330 um; thickness alone cannot indicate collision "
                       "repair here")

    ratio = (value / hi) if hi else None
    delta_expected = (value - hi) if hi is not None else None

    # --- 2. filler, absolutely and only absolutely -----------------------
    # Decided before the relative test on purpose: filler's signature is the
    # gauge running out of range, not a big gap to the roof. A door reading
    # 190 um above the roof is carrying one extra paint system, which is a
    # respray (repainted panels are quoted at 150-300 um) — routing that to
    # "filler" would turn the commonest finding into the gravest accusation.
    if value >= FILLER_ABSOLUTE_UM and pcls != "plastic_bumper":
        return _result(
            "filler_suspect", min(0.85, conf + 0.15), "absolute",
            ratio, delta_expected, None, caveats,
            reasons + [f"{value:.0f} um is at or beyond {FILLER_ABSOLUTE_UM} "
                       f"um, the top of a professional automotive paint "
                       f"meter's range; paint is applied in microns, filler "
                       f"in millimetres"])

    # --- 3. relative test (the strong one for refinishing) ---------------
    delta_ref = None
    if reference_um is not None and pcls in ("body", "roof"):
        delta_ref = value - reference_um
        ref_name = PANELS.get(reference_panel, (reference_panel or "reference",))[0]
        reasons.append(
            f"{value:.0f} um here against {reference_um:.0f} um on the "
            f"{ref_name} of this same vehicle "
            f"({delta_ref:+.0f} um)")
        if delta_ref >= REL_REPAINT_DELTA_UM:
            return _result("refinished", min(0.9, conf + 0.15), "relative",
                           ratio, delta_expected, delta_ref, caveats, reasons)
        if abs(delta_ref) <= REL_FACTORY_DELTA_UM:
            reasons.append(
                f"within the +/-{REL_FACTORY_DELTA_UM} um variation normal "
                f"between factory panels")
            return _result("factory", min(0.9, conf + 0.10), "relative",
                           ratio, delta_expected, delta_ref, caveats, reasons)
        # between 15 and 40 um: a real difference, not a red flag
        return _result("inconclusive", conf, "relative",
                       ratio, delta_expected, delta_ref, caveats, reasons)

    # --- 4. absolute test -------------------------------------------------
    if hi is None:
        return _result("not_measurable", 0.0, "unmeasurable", None, None, None,
                       caveats, ["no expected range available"])

    reasons.append(f"{value:.0f} um against an expected factory "
                   f"{lo:.0f}-{hi:.0f} um ({expected.get('tier')} match)")

    if value <= hi + FACTORY_TOLERANCE_UM:
        reasons.append(f"inside the expected band once the +/-"
                       f"{FACTORY_TOLERANCE_UM} um normal variation is allowed")
        return _result("factory", conf, "absolute", ratio, delta_expected,
                       None, caveats, reasons)

    # BOTH gates must open. A thin-paint car (VW at 70-85 um) would otherwise
    # be accused of a respray by a 40 um excess that is nothing on a Ferrari.
    over_delta = value >= hi + REPAINT_DELTA_UM
    over_ratio = value >= hi * REPAINT_RATIO
    if over_delta and over_ratio and pcls != "plastic_bumper":
        reasons.append(
            f"{delta_expected:.0f} um above the top of the expected band and "
            f"{ratio:.1f}x it — past both the +{REPAINT_DELTA_UM} um and the "
            f"{REPAINT_RATIO}x thresholds practitioners use")
        return _result("refinished", conf, "absolute", ratio, delta_expected,
                       None, caveats, reasons)

    reasons.append("above the expected band but short of the thresholds that "
                   "would make refinishing the likely explanation")
    return _result("inconclusive", conf, "absolute", ratio, delta_expected,
                   None, caveats, reasons)


def _result(cls, conf, basis, ratio, d_exp, d_ref, caveats, reasons):
    return {
        "class": cls,
        "confidence": round(_clamp_conf(conf, 0.0), 2),
        "basis": basis,
        "ratio": round(ratio, 2) if ratio else None,
        "delta_expected_um": round(d_exp, 1) if d_exp is not None else None,
        "delta_reference_um": round(d_ref, 1) if d_ref is not None else None,
        "caveats": list(caveats),
        "reasons": list(reasons),
    }


# --- wording --------------------------------------------------------------
# Legally sensitive. "This panel has been resprayed" is a claim about a car's
# history that a gauge cannot support. Every sentence below reports the
# MEASUREMENT, states what it is CONSISTENT WITH, and names what else could
# explain it — the same discipline analyze.py applies to hidden damage.

def describe(reading, expected, verdict):
    """The user-facing sentence for one classified reading."""
    panel = PANELS.get(reading["panel"], (reading["panel"],))[0]
    v = reading.get("value_um")
    lo, hi = expected.get("min_um"), expected.get("max_um")
    cls = verdict["class"]

    if cls == "not_measurable":
        if reading.get("panel_class") == "plastic_bumper":
            return (f"No coating-thickness reading could be taken on the "
                    f"{panel}. This panel is plastic, and magnetic or "
                    f"eddy-current gauges cannot read plastic at all — it "
                    f"needs an ultrasonic gauge. A missing reading here does "
                    f"not indicate filler.")
        return (f"No coating-thickness reading is available for the {panel}.")

    if cls == "factory":
        band = f"{lo:.0f}-{hi:.0f} µm" if hi else "the expected range"
        return (f"Coating thickness on the {panel} measured {v:.0f} µm "
                f"({um_to_mils(v)} mils), within the {band} expected for this "
                f"vehicle. Nothing at the points measured suggests "
                f"refinishing. This is not proof the panel is original — a "
                f"skim respray over sanded paint can read inside the factory "
                f"band.")

    if cls == "inconclusive":
        return (f"Coating thickness on the {panel} measured {v:.0f} µm "
                f"({um_to_mils(v)} mils), above the {lo:.0f}-{hi:.0f} µm "
                f"expected for this vehicle but not far enough above it to "
                f"point to refinishing. Worth a second look in person; not "
                f"reported as a finding.")

    if cls == "refinished":
        head = (f"Coating thickness on the {panel} measured {v:.0f} µm "
                f"({um_to_mils(v)} mils)")
        # Name what the reading was actually compared against. Saying "above
        # the surrounding paint" when no same-car reference existed would
        # describe a comparison that was never made.
        if verdict.get("delta_reference_um") is not None:
            head += (f", {verdict['delta_reference_um']:+.0f} µm against an "
                     f"undamaged reference panel on this same vehicle")
            tail = "A reading this far above the surrounding paint"
        else:
            head += (f", against a factory expectation of {lo:.0f}-{hi:.0f} µm")
            tail = "A reading this far above the factory range"
        return (head + ". " + tail + " is "
                "most often caused by the panel carrying an additional coat "
                "of paint — that is, having been refinished at some point. "
                "This is a measurement, not a service record: paint "
                "protection film, a factory two-tone finish or a thick "
                "anti-stonechip coating raise the same number. Treat it as a "
                "question to put to the seller or the vehicle's history, not "
                "as established accident repair.")

    if cls == "filler_suspect":
        if v is None:
            head = (f"The gauge returned no reading, or ran past its range, "
                    f"on the {panel}")
        else:
            head = (f"Coating thickness on the {panel} measured {v:.0f} µm "
                    f"({um_to_mils(v)} mils)")
        return (head + ". That is well beyond any factory paint system and "
                "beyond what a respray alone adds; it is the pattern body "
                "filler under the paint produces, because filler is applied "
                "in millimetres where paint is applied in microns. Filler is "
                "ordinary bodywork rather than damage in itself, but it "
                "normally means the panel was repaired. Have the panel looked "
                "at in person before relying on this.")

    return f"Coating thickness on the {panel}: {v} µm."


# --- finding construction -------------------------------------------------
# Damage-type mapping. `paint_mismatch` is the wrong home for this: a
# resprayed panel can match its neighbours perfectly and still read 300 um,
# and "Paint mismatch" printed against a colour-perfect panel reads as a
# false statement. `other` throws away the pricing and weighting the finding
# needs. So taxonomy.py gains two ids, and this is the module that emits them.
CLASS_TO_DAMAGE = {
    "refinished": "prior_refinish",
    "filler_suspect": "body_filler",
}

# Severity. A respray is a VALUE event, not a condition event — nothing is
# broken, so the number is deliberately low and its job is to move the score a
# little and appear in the report, not to imitate damage. Filler sits at 6
# because that is the threshold severity.is_structural_concern() uses, and a
# panel with filler under it genuinely warrants the "get this inspected in
# person" banner.
SEVERITY_BY_CLASS = {"refinished": 3, "filler_suspect": 6}
# Several refinished panels is a different story from one: one panel is a
# parking scrape, three adjacent panels is a repaired impact.
MULTI_PANEL_SEVERITY = {2: 4, 3: 5}


def finding_from_reading(reading, expected, verdict):
    """Build a canonical finding — the exact shape analyze.py emits.

    Only `refinished` and `filler_suspect` produce findings. `factory`,
    `inconclusive` and `not_measurable` return None and travel as notes: an
    inconclusive measurement is not an observation of anything, and putting
    it in `findings` would let it score the car down.
    """
    cls = verdict["class"]
    dtype = CLASS_TO_DAMAGE.get(cls)
    if not dtype:
        return None
    panel = reading["panel"]
    v = reading.get("value_um")

    evidence = []
    if v is not None:
        evidence.append(
            f"Coating thickness measured {v:.0f} µm ({um_to_mils(v)} mils) "
            f"at {reading['n_points']} point"
            f"{'s' if reading['n_points'] != 1 else ''} on this panel")
    else:
        evidence.append("Gauge returned no reading / ran past its range on "
                        "this panel")
    if verdict.get("delta_reference_um") is not None:
        evidence.append(verdict["reasons"][0])
    if expected.get("max_um") is not None:
        evidence.append(
            f"Expected factory range {expected['min_um']:.0f}-"
            f"{expected['max_um']:.0f} µm "
            f"({expected['tier']} match; source: {expected['source']})")

    hidden = []
    if cls == "filler_suspect":
        hidden.append({
            "system": "panel repair beneath the filler",
            "probability": 0.5,
            "rationale": ("filler is applied over reshaped metal; the quality "
                          "of the metalwork under it cannot be seen from "
                          "outside, and corrosion often starts there"),
            "est_cost_high": None,
        })

    return {
        "panel": panel,
        "region": PANELS.get(panel, (None, "other"))[1],
        "damage_type": dtype,
        "damage_label": DAMAGE_TYPES.get(dtype, ("Other",))[0],
        "severity": clamp_severity(SEVERITY_BY_CLASS.get(cls, 3)),
        "confidence": verdict["confidence"],
        "image_index": None,
        "bbox": None,
        "evidence": evidence,
        "hidden_damage": hidden,
        "model_specific_risks": [],
        "repair_note": ("No repair is implied — this is a history and value "
                        "finding" if cls == "refinished" else
                        "Have the panel probed in person before pricing"),
        # extras the report and the app can key off; ignored by everything
        # that does not know about them
        "source": "paint_thickness",
        "measurement": {
            "value_um": v,
            "value_mils": um_to_mils(v) if v is not None else None,
            "points_um": reading.get("points_um"),
            "expected_min_um": expected.get("min_um"),
            "expected_max_um": expected.get("max_um"),
            "expected_tier": expected.get("tier"),
            "expected_source": expected.get("source"),
            "class": cls,
            "basis": verdict["basis"],
            "ratio": verdict.get("ratio"),
            "delta_reference_um": verdict.get("delta_reference_um"),
            "caveats": verdict["caveats"],
        },
        "statement": describe(reading, expected, verdict),
    }


def readings_to_findings(readings, vehicle=None, table=None,
                         paint_system=None):
    """The whole pipeline for one car's gauge session.

    Returns (findings, notes, context) where `findings` drops straight into
    severity.condition_score / repair.estimate_all / report.assemble, `notes`
    carries the factory / inconclusive / unmeasurable panels so the report can
    say what WAS checked and came back clean, and `context` records the
    reference panel and the lookup tier for the methods section.
    """
    vehicle = vehicle or {}
    norm = [normalize_reading(r) for r in (readings or [])]
    ref_um, ref_panel, ref_basis = pick_reference(norm)

    findings, notes = [], []
    for r in norm:
        exp = expected_range(vehicle.get("make"), vehicle.get("model"),
                             vehicle.get("year"), r["panel"],
                             paint_system=paint_system or
                             vehicle.get("paint_system"),
                             table=table)
        # a panel cannot be its own reference
        this_ref = None if r["panel"] == ref_panel else ref_um
        verdict = classify_reading(r, exp, this_ref, ref_panel)
        f = finding_from_reading(r, exp, verdict)
        if f:
            findings.append(f)
        else:
            notes.append({
                "panel": r["panel"],
                "class": verdict["class"],
                "value_um": r.get("value_um"),
                "confidence": verdict["confidence"],
                "statement": describe(r, exp, verdict),
                "caveats": verdict["caveats"],
            })

    # escalate when several panels read refinished — one panel is a scrape,
    # a run of them is a repaired impact
    resprayed = [f for f in findings if f["damage_type"] == "prior_refinish"]
    bump = MULTI_PANEL_SEVERITY.get(min(len(resprayed), 3))
    if bump:
        for f in resprayed:
            f["severity"] = clamp_severity(max(f["severity"], bump))
            f["evidence"].append(
                f"{len(resprayed)} panels on this vehicle read above the "
                f"expected factory range")

    return findings, notes, {
        "reference_panel": ref_panel,
        "reference_um": ref_um,
        "reference_basis": ref_basis,
        "panels_measured": len(norm),
        "table_is_placeholder": TABLE_IS_PLACEHOLDER if table is None else False,
        "method_note": (
            "Readings are compared first against an undamaged reference panel "
            "on this same vehicle, and only then against a factory reference "
            "table; the same-car comparison cancels out marque, model year, "
            "colour and paint system. Take at least four points per panel and "
            "no closer than about 25 mm (1 inch) to any edge or seam."),
    }


# --- fusion with the vision findings --------------------------------------
# Visual signs that a panel has been worked on. A colour/texture mismatch is
# the direct one; a panel gap on the same panel is the indirect one, because
# a refitted panel rarely lines up as well as the factory managed.
VISION_REPAIR_SIGNS = ("paint_mismatch", "misalignment")

FUSION_BOOST = 0.15
FUSION_PENALTY = 0.15


def fuse_with_vision(vision_findings, thickness_findings):
    """Reconcile what the camera saw with what the gauge measured.

    THE RULE, and why it is this way: neither channel may delete the other.
    A measurement that contradicts a visual call is not proof the camera was
    wrong — a blended repair, a polished panel or a gauge point that simply
    missed the repaired area all produce factory-range readings over real
    bodywork ("a repainted panel can read substantially lower than 200
    microns"). And a clean-looking panel that measures 300 um is not the
    camera's failure either; a good respray is invisible, which is the entire
    reason a gauge is used. So disagreement adjusts CONFIDENCE and is stated
    out loud, never resolved by silently dropping a finding.

    Four cases:

      CONFIRMS   both channels flag the same panel -> keep both, raise both
                 confidences, cross-reference them in evidence.
      MEASURED   thickness only -> keep as-is. This is the feature's whole
                 point: the invisible respray.
      CONTRADICTS  vision flagged paint work, thickness read factory on that
                 panel -> keep the vision finding, LOWER its confidence, and
                 append the measurement as a counter-observation.
      UNSEEN     thickness flagged, vision saw nothing on that panel -> keep,
                 note that no visual defect accompanies it (which is
                 consistent with competent repair work, not with none).

    Returns {"findings": [...], "corroboration": [...]} — findings is the
    merged list to score and price; corroboration is the audit trail.
    """
    # Copy the evidence lists, not just the dicts: a shallow copy would let
    # fusion append cross-references onto the CALLER's finding, so calling
    # this twice (or calling it and then re-scoring the originals) would
    # silently duplicate evidence lines in the report.
    def _copy(f):
        g = dict(f)
        g["evidence"] = list(f.get("evidence") or [])
        return g

    vision = [_copy(f) for f in (vision_findings or [])]
    thick = [_copy(f) for f in (thickness_findings or [])]
    corroboration = []

    by_panel_vision = {}
    for f in vision:
        by_panel_vision.setdefault(f.get("panel"), []).append(f)

    thick_panels = set()
    for t in thick:
        panel = t.get("panel")
        thick_panels.add(panel)
        signs = [f for f in by_panel_vision.get(panel, [])
                 if f.get("damage_type") in VISION_REPAIR_SIGNS]
        if signs:
            t["confidence"] = _clamp_conf(t.get("confidence", 0.5)
                                          + FUSION_BOOST)
            t["evidence"].append(
                "Visual inspection independently flagged "
                + ", ".join(sorted({s.get("damage_label", s.get("damage_type"))
                                    for s in signs}))
                + " on this panel")
            for s in signs:
                s["confidence"] = _clamp_conf(s.get("confidence", 0.7)
                                              + FUSION_BOOST)
                s.setdefault("evidence", []).append(
                    "Coating thickness on this panel also measured above the "
                    "expected factory range")
            corroboration.append({"panel": panel, "state": "confirms",
                                  "detail": "camera and gauge agree"})
        else:
            corroboration.append({
                "panel": panel, "state": "unseen",
                "detail": ("gauge flagged this panel; no visible paint defect "
                           "was found on it — consistent with competent "
                           "refinishing rather than with none")})

    # vision flagged paint work where the gauge read factory
    for f in vision:
        if f.get("damage_type") not in VISION_REPAIR_SIGNS:
            continue
        if f.get("panel") in thick_panels:
            continue
        f["confidence"] = _clamp_conf(f.get("confidence", 0.7)
                                      - FUSION_PENALTY)
        f.setdefault("evidence", []).append(
            "Coating thickness on this panel measured within the expected "
            "factory range, which does not support prior refinishing here — "
            "though a blended or lightly sanded repair can read normal")
        corroboration.append({
            "panel": f.get("panel"), "state": "contradicts",
            "detail": ("camera flagged paint work, gauge read factory; the "
                       "visual finding is kept at reduced confidence")})

    return {"findings": vision + thick, "corroboration": corroboration}


# --- small coercers (same contracts analyze.py uses) ----------------------

def _clamp01(v, default):
    """PARSING clamp — same contract as analyze._clamp01, including its
    'a value above 1 was meant as a percentage' rule. Correct for values
    arriving from outside; WRONG for arithmetic we did ourselves, where
    0.9 + 0.15 must saturate at 1.0 rather than become 0.0105. Use
    _clamp_conf for that."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if x > 1.0:
        x /= 100.0
    return max(0.0, min(1.0, x))


def _clamp_conf(v, default=0.5):
    """ARITHMETIC clamp: saturate into 0-1, no percentage guessing."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, x))


def _num_or_none(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int_or_none(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _first_num(d, *keys):
    for k in keys:
        v = _num_or_none(d.get(k))
        if v is not None:
            return v
    return None
