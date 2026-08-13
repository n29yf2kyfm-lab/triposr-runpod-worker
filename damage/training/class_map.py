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
        "drive": ["alloy_scratch", "alloy_scuff"],
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
        "drive": ["alloy_corrosion", "paint_bad_repair", "paint_fade"],
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
