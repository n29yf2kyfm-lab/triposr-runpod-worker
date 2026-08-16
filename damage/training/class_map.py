"""The training taxonomy: how two very different corpora become five classes.

Two sources have to agree on a label set before anything can be balanced:

  * The merged Roboflow corpus — 7 classes, ~20,700 BOXED annotations. This is
    the only source with bounding boxes, so it is the only thing a detector can
    train on directly.
  * The Drive corpus — 18,863 images labelled only by the folder they sit in
    (dent_major/, crack_hairline/, ...). No boxes at all.

They are complementary rather than redundant, which is the reason for merging
them at all: Roboflow carries 5,629 scratch annotations and the Drive set has
literally zero, while the Drive set carries 2,279 lamp images against
Roboflow's 110. Neither alone covers the field.

WHY FIVE CLASSES AND NOT SEVENTEEN. The fine-grained folder names are real
distinctions but the data behind them is not: paint_bad_repair has 17 images
and alloy_scuff has 27. Balancing to a 40k-per-class target from 17 originals
means ~2,350 copies of each, which teaches a model to memorise seventeen
photographs rather than to recognise bad paintwork. Merging up to the level the
data can actually support puts every class within ~13x augmentation of its
target:

    dent           20,803 real ->  1.9x     scratch_scuff   5,656 real ->  7.1x
    crack_glass     5,816 real ->  6.9x     rust_paint      4,283 real ->  9.3x
    lamp_wheel      2,944 real -> 13.6x

The fine label is NOT discarded — it is preserved per image as `subclass`, so a
finer head can be trained later if the thin classes ever fill up, and so the
report can still say "alloy scuff" when it knows.

COLOURS are inherited from the app's existing per-damage-type palette in
overlay.py rather than invented here, so a box drawn during training review and
a box drawn in a customer report are the same colour for the same damage.
"""

# Final class -> everything that feeds it.
#   roboflow: category names as they appear in _annotations.coco.json
#   drive:    folder names under drive_images/
#   canonical:the app taxonomy id (damage/taxonomy.py DAMAGE_TYPES)
#   colour:   hex, matching damage/overlay.py CLASS_COLOURS
FINAL_CLASSES = {
    "dent": {
        "roboflow": ["Dent"],
        "drive": ["dent_major", "dent_medium", "dent_minor", "dent_severe"],
        "canonical": "dent",
        "colour": "#f0883e",
        "structural": True,
    },
    "scratch_scuff": {
        "roboflow": ["Scratch"],
        # scratch_faint / scratch_light are the whole reason this project
        # exists — a detector trained only on dramatic damage cannot see a
        # hairline on a grey door — so they belong in the trained set even
        # though they are the smallest folders in the corpus.
        "drive": ["alloy_scratch", "alloy_scuff", "scratch_faint",
                  "scratch_light", "scratch_medium", "scratch_deep",
                  "scratch_severe"],
        "canonical": "scratch",
        "colour": "#58a6ff",
        "structural": False,
    },
    "crack_glass": {
        "roboflow": ["Crack"],
        "drive": ["crack_glass", "crack_windscreen", "crack_hairline",
                  "crack_structural"],
        "canonical": "crack",
        "colour": "#f85149",
        "structural": True,
    },
    "rust_paint": {
        "roboflow": ["Rust_Corrision", "Paint Damage"],
        # paint_depth_* record how far through the paint stack the damage goes
        # (thin / normal / thick / primer). That is a DEPTH axis rather than a
        # damage type, and it is preserved in `subclass`: it is exactly the
        # signal a severity head would need later, and exactly the wrong thing
        # to split a five-class detector on.
        "drive": ["alloy_corrosion", "paint_bad_repair", "paint_fade",
                  "paint_chip", "paint_rust", "paint_depth_thin",
                  "paint_depth_normal", "paint_depth_thick",
                  "paint_depth_primer"],
        "canonical": "rust",
        "colour": "#bb8009",
        "structural": True,
    },
    "lamp_wheel": {
        "roboflow": ["Lamp Broken", "Flat Tire"],
        "drive": ["light_broken", "light_crack", "light_fade", "light_frosted",
                  "light_water", "alloy_buckle"],
        "canonical": "lamp_damage",
        "colour": "#e3b341",
        "structural": True,
    },
    "structural": {
        # Deliberately its own class rather than folded into dent. A shoved
        # bumper, a broken structural member and a panel gap are the findings
        # that decide whether a car is safe to drive, and severity.py already
        # gates its "get this inspected" banner on exactly this distinction.
        # Merging them into dent would erase the one call the report cannot
        # afford to get wrong.
        "roboflow": [],
        "drive": ["structural_broken", "structural_bumper", "panel_gap",
                  "panel_mismatch"],
        "canonical": "deformation",
        "colour": "#db6d28",
        "structural": True,
    },
}

# Deliberately not a training class. `no_damage` is kept aside as a NEGATIVE
# set — images of undamaged panels are the cheapest defence against a detector
# that finds a scratch on every clean door, and they must never be balanced up
# into a positive class. `interior_*` is parked: 74 images cannot support a
# class, and interior trim damage is a different problem from body damage.
NEGATIVE_CLASSES = ["no_damage"]
PARKED_CLASSES = ["interior_damage", "interior_wear"]

# Reverse lookups, built once.
_FROM_ROBOFLOW = {n: c for c, d in FINAL_CLASSES.items() for n in d["roboflow"]}
_FROM_DRIVE = {n: c for c, d in FINAL_CLASSES.items() for n in d["drive"]}


def from_roboflow(category_name):
    """Final class for a Roboflow category name, or None if it is not trained."""
    return _FROM_ROBOFLOW.get(str(category_name).strip())


def from_drive(folder_name):
    """Final class for a Drive folder name, or None (negatives and parked
    classes both return None and are handled explicitly by the caller)."""
    return _FROM_DRIVE.get(str(folder_name).strip().lower())


def resolve(name):
    """Final class for a label from either corpus. Roboflow names are checked
    first because they are capitalised and cannot collide with folder names."""
    return from_roboflow(name) or from_drive(name)


def colour(final_class):
    return FINAL_CLASSES.get(final_class, {}).get("colour", "#8b949e")


def canonical(final_class):
    """The app-taxonomy damage id, so a trained class maps straight onto the
    existing severity, pricing and 3D-pin logic without a translation layer."""
    return FINAL_CLASSES.get(final_class, {}).get("canonical", "other")


def class_index():
    """{final_class: contiguous id}. Index 0 is reserved as the COCO
    placeholder, matching prepare_data.py, so real classes start at 1."""
    return {c: i for i, c in enumerate(sorted(FINAL_CLASSES), start=1)}


def summary():
    """One line per class — used by the balancer's report header."""
    idx = class_index()
    out = []
    for c in sorted(FINAL_CLASSES):
        d = FINAL_CLASSES[c]
        out.append(f"{idx[c]:>2}  {c:<14} {d['colour']}  "
                   f"canonical={d['canonical']:<12} "
                   f"sources={len(d['roboflow'])}rf+{len(d['drive'])}drive")
    return "\n".join(out)


if __name__ == "__main__":
    print(summary())
    print(f"\nnegatives (never balanced up): {NEGATIVE_CLASSES}")
    print(f"parked (too few to train):     {PARKED_CLASSES}")


# --------------------------------------------------------- training groups ---
# Merging classes so that BALANCE COMES FROM GROUPING, NOT FROM CLONING.
#
# The six-class split cannot be balanced honestly. Real train boxes run from
# scratch_scuff at 169,844 down to rust_paint at 5,884 — a 29x spread — so
# levelling up the thin end needs multipliers of 17.8x and 28.9x, both past the
# 15x ceiling that separates balancing from cloning. Fifteen near-identical
# copies of one photograph do not carry fifteen photographs' worth of signal;
# they teach the detector that particular car.
#
# Grouping fixes the ratio at the source. Required multipliers drop to:
#
#     surface      175,728   1.00x
#     dent          81,798   2.15x
#     structural    21,173   8.30x
#     broken_part   21,420   8.21x
#
# all comfortably inside the ceiling, with no class relying on heavy repetition.
#
# The groups are chosen by what the damage IS, not by what balances neatly:
#
#   surface      The paint and finish layer, whatever disturbed it — scratches,
#                scuffs, chips, fade, corrosion, bad respray work. Folding rust
#                in here also matches the actual inspection domain: modern cars
#                rarely rust, and when the paint layer is wrong it is far more
#                often a mismatch or a poor repair than corrosion.
#   dent         Metal deformed, panel intact.
#   structural   Deformation severe enough to be a structural question rather
#                than a cosmetic one. Kept apart from `dent` deliberately: the
#                two price differently and one of them gates a safety warning,
#                so merging them to save 8x of repetition would be trading the
#                product's most consequential distinction for arithmetic.
#   broken_part  A component is broken rather than marked — glass cracked, lamp
#                or wheel damaged. Distinct from `surface` because it is a part
#                to replace, not a finish to correct.
#
# Every member of a group still resolves through FINAL_CLASSES first, so source
# names map exactly as before; this only decides what the model is asked to
# separate.
TRAIN_GROUPS = {
    "surface":     {"members": ("scratch_scuff", "rust_paint"),
                    "colour": "#58a6ff", "canonical": "scratch",
                    "structural": False},
    "dent":        {"members": ("dent",),
                    "colour": "#f0883e", "canonical": "dent",
                    "structural": True},
    "structural":  {"members": ("structural",),
                    "colour": "#db6d28", "canonical": "deformation",
                    "structural": True},
    "broken_part": {"members": ("crack_glass", "lamp_wheel"),
                    "colour": "#f85149", "canonical": "crack",
                    "structural": True},
}

_GROUP_OF = {m: g for g, spec in TRAIN_GROUPS.items()
             for m in spec["members"]}


def group_for(final_class):
    """FINAL_CLASSES name -> training group name. Identity if ungrouped."""
    return _GROUP_OF.get(final_class, final_class)


def _check_groups():
    missing = sorted(set(FINAL_CLASSES) - set(_GROUP_OF))
    extra = sorted(set(_GROUP_OF) - set(FINAL_CLASSES))
    return missing, extra


# ------------------------------------------------- v2: merge the weak class ---
# Measured after one epoch on the four-group split:
#
#     broken_part  AP 0.4281   21,370 boxes
#     dent         AP 0.3115   81,707
#     surface      AP 0.1725  174,875
#     structural   AP 0.1610   21,199
#
# The two weak classes are weak for OPPOSITE reasons, and only one of them is
# fixable by merging.
#
# `structural` is SCARCE: 21,199 real boxes needing 8.9x repetition to reach
# target, so the model sees a few thousand distinct examples many times over.
# Folding it into `dent` gives one deformation class with 102,906 real boxes
# and a 2.1x multiplier — the merge does what merges are good for.
#
# `surface` is ABUNDANT: 174,875 boxes, the largest class, needing no
# repetition at all. Its 0.17 is not a data-quantity problem, it is the label
# ambiguity that was flagged before any of this trained — where a scratch ends
# is genuinely unclear, and forty-one source projects each drew that line
# differently. No regrouping fixes that; only relabelling would.
#
# WHAT MERGING COSTS. The four-group split deliberately kept `structural`
# apart from `dent` because they price differently and one gates a safety
# warning. That distinction now has to be recovered at inference from box area
# and severity instead of from the class head — a worse place for it, but a
# 0.16 AP class is not carrying that distinction reliably either.
TRAIN_GROUPS_V2 = {
    "surface":     {"members": ("scratch_scuff", "rust_paint"),
                    "colour": "#58a6ff", "canonical": "scratch",
                    "structural": False},
    "deformation": {"members": ("dent", "structural"),
                    "colour": "#f0883e", "canonical": "dent",
                    "structural": True},
    "broken_part": {"members": ("crack_glass", "lamp_wheel"),
                    "colour": "#f85149", "canonical": "crack",
                    "structural": True},
}

_GROUP_OF_V2 = {m: g for g, spec in TRAIN_GROUPS_V2.items()
                for m in spec["members"]}


def group_for_v2(final_class):
    return _GROUP_OF_V2.get(final_class, final_class)


def _check_groups_v2():
    return (sorted(set(FINAL_CLASSES) - set(_GROUP_OF_V2)),
            sorted(set(_GROUP_OF_V2) - set(FINAL_CLASSES)))


# ----------------------------------------------- painted body panels (v3) ---
# PAINT MISMATCH IS A MEASUREMENT BETWEEN PANELS, NOT A CLASS TO DETECT.
#
# Searching four platforms for labelled "paint mismatch", "panel gap" and
# "fading" returned zero examples, and that absence is not an oversight in the
# public data — it is the wrong shape for the problem. A respray does not look
# like anything on its own; it looks WRONG NEXT TO THE PANEL BESIDE IT. So the
# detector's job is to find the panels, and the comparison does the rest:
# segment adjacent panels, measure their colour and gloss, and flag the pair
# that disagrees. No labelled mismatch is required, which is fortunate, since
# none exists.
#
# Only PAINTED BODY panels are listed. Glass, wheels, lights, grille, mirrors
# and plates are excluded: comparing the colour of a windscreen against a wing
# says nothing about paintwork, and including them would generate false
# mismatches on every car. Bumpers are kept but flagged `plastic` — they are
# painted and worth comparing, but moulded plastic takes colour slightly
# differently from steel even from the factory, so a bumper-to-wing difference
# needs a wider tolerance than wing-to-door.
PAINTED_PANELS = {
    "hood":          {"plastic": False, "adjacent": ("fender", "windshield")},
    "roof":          {"plastic": False, "adjacent": ("quarter_panel",)},
    "trunk":         {"plastic": False, "adjacent": ("quarter_panel",
                                                     "back_bumper")},
    "fender":        {"plastic": False, "adjacent": ("hood", "front_door",
                                                     "front_bumper")},
    "front_door":    {"plastic": False, "adjacent": ("fender", "back_door",
                                                     "rocker_panel")},
    "back_door":     {"plastic": False, "adjacent": ("front_door",
                                                     "quarter_panel",
                                                     "rocker_panel")},
    "quarter_panel": {"plastic": False, "adjacent": ("back_door", "roof",
                                                     "trunk", "back_bumper")},
    "rocker_panel":  {"plastic": False, "adjacent": ("front_door",
                                                     "back_door")},
    "front_bumper":  {"plastic": True,  "adjacent": ("fender",)},
    "back_bumper":   {"plastic": True,  "adjacent": ("quarter_panel",
                                                     "trunk")},
}

# Present in cardata_parts but deliberately NOT compared for paint.
NON_PAINTED = ("windshield", "back_windshield", "front_window", "back_window",
               "front_wheel", "back_wheel", "headlight", "tail_light",
               "mirror", "grille", "license_plate")


def is_painted_panel(name):
    return str(name).strip().lower() in PAINTED_PANELS


def panel_neighbours(name):
    """Panels whose paint SHOULD match this one on an unrepaired car."""
    spec = PAINTED_PANELS.get(str(name).strip().lower())
    return tuple(spec["adjacent"]) if spec else ()


def _check_panels():
    # Adjacency MUST be symmetric. Three pairs were one-directional on the
    # first draft — rocker/back_door, front_bumper/fender, back_bumper/quarter
    # — which would have reported a mismatch from one side of the pair and not
    # the other, depending only on which panel the loop reached first. A
    # finding that appears or vanishes with iteration order is worse than no
    # finding at all, so this is checked rather than assumed.
    bad = [p for spec in PAINTED_PANELS.values() for p in spec["adjacent"]
           if p not in PAINTED_PANELS and p not in NON_PAINTED]
    # adjacency must be symmetric among painted panels, or a mismatch would be
    # reported from one side only depending on iteration order
    asym = []
    for a, spec in PAINTED_PANELS.items():
        for b in spec["adjacent"]:
            if b in PAINTED_PANELS and a not in PAINTED_PANELS[b]["adjacent"]:
                asym.append((a, b))
    return bad, asym
