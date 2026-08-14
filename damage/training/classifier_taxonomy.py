"""Classifier taxonomy for the Drive corpus — type, severity and paint depth.

The Drive folders are the owner's own filing system, and they mix THREE
different axes into one flat list of 30 names:

  1. DAMAGE TYPE      dent / scratch / crack / light / alloy / paint /
                      structural / interior / none
  2. SEVERITY         minor -> medium -> major -> severe   (dents)
                      faint -> medium -> deep -> severe    (scratches)
  3. PAINT DEPTH      thin / normal / thick — these are paint-gauge readings in
                      microns, not something visible in a photograph.

class_map.py already collapses all of this into 6 DETECTOR classes. That is the
right call for a detector, which has to be balanced up to a per-class target and
so cannot afford a class with 11 real images. A CLASSIFIER is a different
problem: it sees whole images with a folder label and no boxes, so the question
is not "what can be balanced" but "what is actually separable in the pixels".

The answer here is TYPE as the trained head and SEVERITY as a SECOND head
trained only on the images that carry a severity word. Reasons, in order of
weight:

  * Severity is not visually independent of type. A "major" dent and a "severe"
    dent differ by a judgement call about repair cost, not by a feature the
    network can isolate; folded into one flat 30-way softmax they compete as if
    they were unrelated categories, and every dent_severe error is scored as
    harshly as calling a dent a windscreen crack. Two heads make the type
    prediction robust and let the severity head be wrong by one notch cheaply.
  * The severity labels are ORDINAL. A flat softmax throws that away. An ordinal
    (or regression) severity head gets "predicted major, was severe" nearly
    right, which is what the inspection report needs.
  * Splitting the axes fixes most of the imbalance for free. Flat, the ratio is
    dent_major 8,979 : paint_fade 11 = 816:1. By type it is dent 15,071 :
    no_damage 49 = 308:1, and dropping the two unusable heads (interior 74,
    no_damage 49 is a negative set, not a class) leaves 15,071 : 160 = 94:1 over
    seven trainable types. On the severity head, restricted to dents, it is
    8,979 : 764 = 12:1, which class-weighting handles without augmentation.
  * PAINT DEPTH IS NOT A VISUAL CLASS. thin/normal/thick are gauge readings. A
    150um and a 400um panel look identical; asking a CNN to separate them
    teaches it to memorise which cars were photographed on which day. They are
    kept as a metadata attribute on the paint type and are NOT a head.
"""

# folder -> (type, severity or None)
#   severity is an ORDINAL 1..4 where the folder states one, else None.
DRIVE_FOLDERS = {
    "dent_minor":          ("dent", 1),
    "dent_medium":         ("dent", 2),
    "dent_major":          ("dent", 3),
    "dent_severe":         ("dent", 4),

    "scratch_faint":       ("scratch", 1),
    "scratch_medium":      ("scratch", 2),
    "scratch_deep":        ("scratch", 3),
    "scratch_severe":      ("scratch", 4),

    "crack_glass":         ("crack_glass", None),
    "crack_windscreen":    ("crack_glass", None),

    "light_broken":        ("light", 4),
    "light_crack":         ("light", 3),
    "light_frosted":       ("light", 2),
    "light_fade":          ("light", 1),

    "alloy_buckle":        ("alloy", 3),
    "alloy_corrosion":     ("alloy", 2),
    "alloy_scuff":         ("alloy", 1),

    "paint_rust":          ("paint", 3),
    "paint_bad_repair":    ("paint", 2),
    "paint_chip":          ("paint", 2),
    "paint_fade":          ("paint", 1),
    "paint_depth_thin":    ("paint", None),
    "paint_depth_normal":  ("paint", None),
    "paint_depth_thick":   ("paint", None),

    "structural_broken":   ("structural", 4),
    "structural_bumper":   ("structural", 3),
    "panel_gap":           ("panel_gap", None),

    "interior_damage":     ("interior", None),
    "interior_wear":       ("interior", None),

    "no_damage":           ("no_damage", None),
}

SEVERITY_NAMES = {1: "minor", 2: "moderate", 3: "major", 4: "severe"}

# Paint-gauge reading, carried as metadata and never trained as a class.
PAINT_DEPTH = {
    "paint_depth_thin":   "thin",
    "paint_depth_normal": "normal",
    "paint_depth_thick":  "thick",
}

# Types that are NOT trained as positives.
#   no_damage  — negative set. Undamaged panels are the cheapest defence
#                against a classifier that finds a dent on every clean door,
#                but they must never be balanced up into a positive class.
#   interior   — 74 images across two folders, and interior trim damage is a
#                different problem from exterior body damage. Held out.
#   panel_gap  — 60 images, and it is a GEOMETRY finding (the gap between two
#                panels) rather than a surface appearance. It is the one class
#                where a whole-image classifier is the wrong tool: the signal is
#                a few pixels of misaligned seam. Held out from the type head,
#                kept indexed so it is not lost.
NEGATIVE_TYPES = ["no_damage"]
HELD_OUT_TYPES = ["interior", "panel_gap"]

TRAINED_TYPES = ["dent", "scratch", "crack_glass", "light", "alloy", "paint",
                 "structural"]


def resolve(folder):
    """(type, severity) for a Drive folder name; (None, None) if unknown."""
    return DRIVE_FOLDERS.get(str(folder).strip().lower(), (None, None))


def type_of(folder):
    return resolve(folder)[0]


def severity_of(folder):
    return resolve(folder)[1]


def paint_depth_of(folder):
    return PAINT_DEPTH.get(str(folder).strip().lower())


def type_index():
    return {t: i for i, t in enumerate(TRAINED_TYPES)}


if __name__ == "__main__":
    import collections
    import os
    root = "/home/user/drive_images"
    by_type = collections.Counter()
    for f, (t, s) in DRIVE_FOLDERS.items():
        d = os.path.join(root, f)
        if os.path.isdir(d):
            by_type[t] += len(os.listdir(d))
    for t, n in by_type.most_common():
        tag = ("negative" if t in NEGATIVE_TYPES else
               "held out" if t in HELD_OUT_TYPES else "trained")
        print(f"{t:<12} {n:>6}  {tag}")
