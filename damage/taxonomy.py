"""The shared vocabulary of a vehicle damage inspection — pure stdlib.

Every other module in this worker keys off these three tables: the panels a
car is divided into, the kinds of damage a panel can have, and the 1-10
severity scale. Keeping them in one place is what lets the VLM output, the
severity score, the repair estimate, the capture-completeness check and the
3D fusion all speak the same language instead of drifting apart.

WHY A CANONICAL PANEL LIST AT ALL. The eight competitor apps each invent
their own labels ("Pass - Front", "front left fender", "Driver - Front").
The moment two parts of a pipeline disagree on what a panel is called, the
repair table can't price it, the completeness check can't tell what's missing,
and the 3D layer can't place a pin. So the VLM is forced to map every finding
onto ONE of these ids (analyze.py normalises synonyms), and everything
downstream trusts the id.

THE 3D ANCHOR is the capability none of the competitors have. Each panel
carries a canonical anchor point in a normalised car frame — the coordinate
where a pin for "dent on the front-left fender" should sit on the
reconstructed model that trellis2/ produces. Frame convention, right-handed:

    +x = driver's RIGHT   (passenger side is +x on a LHD car; see note)
    +y = UP
    +z = FORWARD (towards the front bumper)
    origin at the vehicle centre, extents normalised to [-0.5, +0.5]

We label sides as LEFT / RIGHT of the vehicle (facing forward), never
"driver/passenger" — which side the driver sits on depends on the market, and
a US Prime van and a UK Transit would otherwise pin the same dent on opposite
sides. The app maps left/right to driver/passenger for display using the
vehicle's market.
"""

# --- panels ---------------------------------------------------------------
# id -> (human label, region, (x, y, z) anchor in the normalised car frame)
# region groups panels for roll-up scoring and for the capture grid.
PANELS = {
    # front
    "front_bumper":        ("Front bumper",          "front",  (0.0,  -0.15,  0.50)),
    "hood":                ("Hood / bonnet",         "front",  (0.0,   0.20,  0.30)),
    "grille":              ("Grille",                "front",  (0.0,  -0.02,  0.49)),
    "windshield":          ("Windshield",            "glass",  (0.0,   0.30,  0.18)),
    "front_left_headlight":("Front left headlight",  "front",  (-0.42,-0.02,  0.47)),
    "front_right_headlight":("Front right headlight","front",  (0.42, -0.02,  0.47)),
    # left side
    "front_left_fender":   ("Front left fender",     "left",   (-0.48, 0.02,  0.28)),
    "front_left_door":     ("Front left door",       "left",   (-0.50, 0.00,  0.05)),
    "rear_left_door":      ("Rear left door",        "left",   (-0.50, 0.00, -0.15)),
    "left_quarter_panel":  ("Left rear quarter",     "left",   (-0.48, 0.02, -0.35)),
    "left_mirror":         ("Left wing mirror",      "left",   (-0.52, 0.12,  0.12)),
    "front_left_wheel":    ("Front left wheel",      "wheels", (-0.46,-0.30,  0.30)),
    "rear_left_wheel":     ("Rear left wheel",       "wheels", (-0.46,-0.30, -0.30)),
    "left_rocker":         ("Left sill / rocker",    "left",   (-0.50,-0.22, -0.05)),
    # right side
    "front_right_fender":  ("Front right fender",    "right",  (0.48,  0.02,  0.28)),
    "front_right_door":    ("Front right door",      "right",  (0.50,  0.00,  0.05)),
    "rear_right_door":     ("Rear right door",       "right",  (0.50,  0.00, -0.15)),
    "right_quarter_panel": ("Right rear quarter",    "right",  (0.48,  0.02, -0.35)),
    "right_mirror":        ("Right wing mirror",     "right",  (0.52,  0.12,  0.12)),
    "front_right_wheel":   ("Front right wheel",     "wheels", (0.46, -0.30,  0.30)),
    "rear_right_wheel":    ("Rear right wheel",      "wheels", (0.46, -0.30, -0.30)),
    "right_rocker":        ("Right sill / rocker",   "right",  (0.50, -0.22, -0.05)),
    # roof / glass
    "roof":                ("Roof",                  "roof",   (0.0,   0.42,  0.0)),
    "left_front_glass":    ("Left front window",     "glass",  (-0.47, 0.22,  0.08)),
    "right_front_glass":   ("Right front window",    "glass",  (0.47,  0.22,  0.08)),
    # rear
    "rear_bumper":         ("Rear bumper",           "rear",   (0.0,  -0.15, -0.50)),
    "tailgate":            ("Tailgate / boot",       "rear",   (0.0,   0.10, -0.48)),
    "rear_windshield":     ("Rear windshield",       "glass",  (0.0,   0.28, -0.40)),
    "rear_left_light":     ("Rear left light",       "rear",   (-0.40,-0.02, -0.49)),
    "rear_right_light":    ("Rear right light",      "rear",   (0.40, -0.02, -0.49)),
    # catch-all so a finding is never dropped for lack of a precise panel
    "body_other":          ("Body (unspecified)",    "other",  (0.0,   0.0,   0.0)),
}

REGIONS = ("front", "left", "right", "rear", "roof", "glass", "wheels", "other")

# Structural weight: how much a panel matters to the vehicle's integrity and
# value. Drives both the condition score and the repair cost — a dent in a
# structural rail is not a dent in a bumper cover. 1.0 = cosmetic skin,
# higher = safety / structure / expensive glass.
PANEL_WEIGHT = {
    "windshield": 1.6, "rear_windshield": 1.3,
    "roof": 1.4, "left_rocker": 1.5, "right_rocker": 1.5,
    "front_left_wheel": 1.3, "front_right_wheel": 1.3,
    "rear_left_wheel": 1.3, "rear_right_wheel": 1.3,
    "front_left_headlight": 1.2, "front_right_headlight": 1.2,
}
DEFAULT_PANEL_WEIGHT = 1.0

# The capture grid: the panels a complete walk-around should include, grouped
# the way DAMAGE iD's guided-capture screen groups them. quality.py compares
# what was actually seen against this to tell the user what's still missing.
CAPTURE_GRID = {
    "front":  ["front_bumper", "hood", "grille", "windshield"],
    "left":   ["front_left_fender", "front_left_door", "rear_left_door",
               "left_quarter_panel"],
    "right":  ["front_right_fender", "front_right_door", "rear_right_door",
               "right_quarter_panel"],
    "rear":   ["rear_bumper", "tailgate", "rear_windshield"],
    "wheels": ["front_left_wheel", "front_right_wheel",
               "rear_left_wheel", "rear_right_wheel"],
    "roof":   ["roof"],
}

# --- damage types ---------------------------------------------------------
# id -> (label, is_structural_candidate, typical repair action)
# is_structural_candidate flags damage that can hide sub-surface / safety
# consequences — the trigger for the hidden-damage reasoning in analyze.py.
DAMAGE_TYPES = {
    "scratch":        ("Scratch",            False, "refinish"),
    "scuff":          ("Scuff",              False, "polish_or_refinish"),
    "paint_chip":     ("Paint chip",         False, "touch_up_or_refinish"),
    "paint_fade":     ("Paint fade / oxidation", False, "refinish"),
    "paint_mismatch": ("Paint mismatch",     False, "investigate_prior_repair"),
    "dent":           ("Dent",               True,  "pdr_or_panel"),
    "deformation":    ("Panel deformation",  True,  "panel_repair_or_replace"),
    "crack":          ("Crack",              True,  "replace_or_repair"),
    "shattered_glass":("Shattered glass",    True,  "replace_glass"),
    "chip_glass":     ("Glass chip",         False, "resin_repair"),
    "rust":           ("Rust / corrosion",   True,  "treat_or_replace"),
    "misalignment":   ("Panel gap / misalignment", True, "refit_or_investigate"),
    "missing_part":   ("Missing part",       True,  "replace"),
    "lamp_damage":    ("Lamp damage",        True,  "replace_lamp"),
    "tire_damage":    ("Tyre / wheel damage", True, "inspect_replace"),
    "hail":           ("Hail damage",        False, "pdr"),
    "other":          ("Other",              False, "assess"),
}

# --- severity -------------------------------------------------------------
# A single 1-10 scale, matching FairMoto's "sev N" so a number means the same
# thing everywhere. Bands give the human label and the traffic-light colour
# the report and the app both use.
SEVERITY_BANDS = [
    (1, 2,  "cosmetic",    "#3fb950"),  # barely visible, defer
    (3, 4,  "minor",       "#9ece6a"),
    (5, 6,  "moderate",    "#e3b341"),
    (7, 8,  "major",       "#f0883e"),
    (9, 10, "severe",      "#f85149"),  # structural / safety / write-off risk
]


def clamp_severity(value, default=5):
    """Coerce anything the model emits into an integer 1-10."""
    try:
        v = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return max(1, min(10, v))


def severity_band(sev):
    """(label, colour) for a 1-10 severity."""
    sev = clamp_severity(sev)
    for lo, hi, label, colour in SEVERITY_BANDS:
        if lo <= sev <= hi:
            return label, colour
    return "moderate", "#e3b341"


def canonical_panel(name):
    """Map a free-form panel string onto a taxonomy id, or None.

    The VLM is told to use our ids, but real models paraphrase ("left front
    door", "driver door", "n/s front door"). This absorbs the common cases so
    a finding is placed rather than dropped. Unmapped returns None and the
    caller falls back to 'body_other' — a finding is never lost.
    """
    if not name:
        return None
    s = str(name).strip().lower().replace("-", " ").replace("_", " ")
    s = " ".join(s.split())
    if not s:
        return None
    # direct id match (with underscores restored)
    direct = s.replace(" ", "_")
    if direct in PANELS:
        return direct
    # UK n/s (nearside = left) and o/s (offside = right) shorthand
    s = s.replace("nearside", "left").replace("offside", "right")
    s = s.replace("n/s", "left").replace("o/s", "right")
    # driver/passenger -> left/right is market-dependent; analyze.py resolves
    # it with the market before calling here. Bare "driver"/"passenger" left
    # unresolved fall through to side-agnostic matching below.
    side = "left" if "left" in s else ("right" if "right" in s else None)
    front = "front" in s or "bonnet" in s
    rear = "rear" in s or "back" in s or "boot" in s or "tailgate" in s

    def has(*words):
        return any(w in s for w in words)

    if has("windshield", "windscreen") and rear:
        return "rear_windshield"
    if has("windshield", "windscreen"):
        return "windshield"
    if has("bonnet", "hood"):
        return "hood"
    if has("grille"):
        return "grille"
    if has("roof"):
        return "roof"
    if has("mirror"):
        return f"{side}_mirror" if side else "left_mirror"
    if has("headlight", "headlamp"):
        return f"front_{side}_headlight" if side else "front_left_headlight"
    if has("tail light", "taillight", "tail lamp", "rear light", "rear lamp"):
        return f"rear_{side}_light" if side else "rear_left_light"
    if has("wheel", "rim", "tyre", "tire", "alloy"):
        pos = "rear" if rear else "front"
        return f"{pos}_{side}_wheel" if side else "front_left_wheel"
    if has("rocker", "sill"):
        return f"{side}_rocker" if side else "left_rocker"
    if has("quarter"):
        return f"{side}_quarter_panel" if side else "left_quarter_panel"
    if has("fender", "wing"):
        return f"front_{side}_fender" if side else "front_left_fender"
    if has("door"):
        pos = "rear" if rear else "front"
        return f"{pos}_{side}_door" if side else "front_left_door"
    if has("bumper") and rear:
        return "rear_bumper"
    if has("bumper"):
        return "front_bumper"
    if has("tailgate", "boot", "trunk", "liftgate"):
        return "tailgate"
    return None


def canonical_damage(name):
    """Map a free-form damage string onto a DAMAGE_TYPES id."""
    if not name:
        return "other"
    s = str(name).strip().lower()
    if s in DAMAGE_TYPES:
        return s
    table = [
        (("shatter", "smash", "broken glass", "spiderweb", "cracked windshield"),
         "shattered_glass"),
        (("glass chip", "stone chip glass", "rock chip"), "chip_glass"),
        (("dent", "ding"), "dent"),
        (("deform", "crease", "buckle", "bent panel"), "deformation"),
        (("scratch", "scrape", "keyed"), "scratch"),
        (("scuff", "rub"), "scuff"),
        (("chip",), "paint_chip"),
        (("fade", "oxidation", "clear coat", "clearcoat", "sun"), "paint_fade"),
        (("mismatch", "overspray", "respray", "colour", "color diff"),
         "paint_mismatch"),
        (("rust", "corros", "oxidis"), "rust"),
        (("gap", "misalign", "panel fit", "uneven"), "misalignment"),
        (("missing", "absent"), "missing_part"),
        (("hail",), "hail"),
        (("crack",), "crack"),
        (("lamp", "light", "headlight", "taillight"), "lamp_damage"),
        (("tyre", "tire", "wheel", "rim", "alloy"), "tire_damage"),
    ]
    for needles, out in table:
        if any(n in s for n in needles):
            return out
    return "other"
