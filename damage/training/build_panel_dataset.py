"""Build a PANEL DETECTOR dataset from cardata_parts.

IT IS A DETECTOR, NOT A SEGMENTER, AND THE DATA DECIDES THAT
------------------------------------------------------------
This was planned as a "panel segmenter". The source has no masks:

    annotation keys: ['area', 'bbox', 'category_id', 'id', 'image_id',
                      'iscrowd']
    has segmentation: False

Every annotation is a box. A segmenter cannot be trained from boxes, so what
gets built is a detector, and calling it a segmenter would be describing
something that does not exist.

That turns out to be exactly what the consumer wants anyway.
paint_mismatch.compare_panels takes `[{name, box}]` and samples the middle 50%
of each box, precisely so it never needs a mask: the centre of a panel's box is
that panel's paint, and the corners — which are where a box disagrees with a
mask — are discarded before the median is taken. A mask would be a little more
accurate on a sharply angled door. It is not worth a dataset that does not
exist.

THE DUPLICATE RECORDS ARE TWO ANNOTATION PASSES, NOT AUGMENTATION
------------------------------------------------------------------
441 of the 1,371 photographs appear TWICE in the COCO. That looked like the
near-duplicate problem that cost this project a 44%-contaminated corpus, so it
was checked rather than assumed — and it is something else entirely:

    Car damages 101.png  id 2   -> hood, roof, fender, front_door, ... (panels)
    Car damages 101.png  id 999 -> scratch, dent, broken_part, ...    (damage)

Of the first 200 duplicated files, ZERO had matching annotation sets. One pass
labelled the car's parts, a second labelled its damage, and both were merged
into one file with separate image records.

So annotations are POOLED BY FILENAME, not by image id. Taking either record
alone would silently discard half the labels on 441 photographs — and taking
the damage record alone would yield an image with no panels in it at all,
which then trains the model that a car door is background.

WHY THE DAMAGE CLASSES ARE DROPPED
----------------------------------
scratch, dent, broken_part, paint_chip, missing_part, flaking, corrosion and
cracked account for 8,668 of the 24,434 annotations. They are already covered
by the six-class damage detector, which was trained on 375,291 boxes rather
than these few thousand. Keeping them here would spend a 1,371-image budget
re-learning, worse, something already learned — and would put two models in
disagreement about the same photograph.

    python build_panel_dataset.py --src /home/user/cardata_parts/train \
        --out /home/user/panels
"""
import argparse
import collections
import json
import os
import random
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# The 21 classes the mismatch and report code already speaks. Imported rather
# than restated so a rename in class_map cannot silently desynchronise the
# weights from the code that consumes them — the exact failure that produced a
# model whose labels.txt disagreed with its own taxonomy.
from class_map import PAINTED_PANELS, NON_PAINTED  # noqa: E402

PANEL_CLASSES = tuple(PAINTED_PANELS) + tuple(NON_PAINTED)

SPLITS = (("train", 0.80), ("valid", 0.10), ("test", 0.10))


def load(src):
    with open(os.path.join(src, "_annotations.coco.json")) as f:
        return json.load(f)


def pool_by_filename(doc):
    """{file_name: [annotation, ...]} across every image record for that file.

    See the module docstring: one photograph can carry two image ids, one per
    annotation pass, and using either alone loses half its labels.
    """
    id_to_name = {im["id"]: im["file_name"] for im in doc["images"]}
    size = {im["file_name"]: (im.get("width"), im.get("height"))
            for im in doc["images"]}
    pooled = collections.defaultdict(list)
    orphans = 0
    for a in doc["annotations"]:
        name = id_to_name.get(a["image_id"])
        if name is None:
            orphans += 1
            continue
        pooled[name].append(a)
    return pooled, size, orphans


def build(src, out, seed, dry_run):
    doc = load(src)
    cats = {c["id"]: c["name"] for c in doc["categories"]}
    keep_ids = {cid for cid, n in cats.items() if n in PANEL_CLASSES}
    unknown = sorted({n for n in cats.values() if n not in PANEL_CLASSES})

    pooled, size, orphans = pool_by_filename(doc)
    print(f"source        {len(doc['images']):,} image records, "
          f"{len(pooled):,} distinct files, {len(doc['annotations']):,} boxes")
    print(f"dropped types {', '.join(unknown)}")
    if orphans:
        print(f"  ! {orphans} annotations referenced a missing image record")

    # Keep only panels, and only files that still have some.
    per_file = {}
    for name, anns in pooled.items():
        panels = [a for a in anns if a["category_id"] in keep_ids]
        if panels:
            per_file[name] = panels
    n_boxes = sum(len(v) for v in per_file.values())
    print(f"panels kept   {len(per_file):,} files, {n_boxes:,} boxes "
          f"({len(pooled) - len(per_file):,} files had no panel labels)")

    on_disk = set(os.listdir(src))
    missing = [n for n in per_file if n not in on_disk]
    if missing:
        print(f"  ! {len(missing)} files are indexed but not on disk; dropping")
        for n in missing:
            per_file.pop(n)

    # SPLIT BY FILE, and only after pooling. Splitting the raw image records
    # would put a photograph's panel pass in train and its damage pass in
    # valid — the same photo on both sides of the boundary.
    names = sorted(per_file)
    random.Random(seed).shuffle(names)
    n = len(names)
    cuts, start = {}, 0
    for i, (split, frac) in enumerate(SPLITS):
        stop = n if i == len(SPLITS) - 1 else start + int(round(n * frac))
        cuts[split] = names[start:stop]
        start = stop

    # COCO ids are 1-based with 0 reserved, matching the damage detector's
    # convention so both models' labels.txt can be read the same way.
    order = [c for c in PANEL_CLASSES
             if any(cats[a["category_id"]] == c
                    for v in per_file.values() for a in v)]
    index = {name: i + 1 for i, name in enumerate(order)}
    absent = [c for c in PANEL_CLASSES if c not in index]
    if absent:
        print(f"  note: no examples of {', '.join(absent)} — omitted")

    counts = collections.Counter()
    print()
    for split, files in cuts.items():
        imgs, anns, aid = [], [], 1
        for iid, fn in enumerate(sorted(files), start=1):
            w, h = size.get(fn, (None, None))
            imgs.append({"id": iid, "file_name": fn, "width": w, "height": h})
            for a in per_file[fn]:
                cname = cats[a["category_id"]]
                anns.append({"id": aid, "image_id": iid,
                             "category_id": index[cname],
                             "bbox": [float(v) for v in a["bbox"]],
                             "area": float(a.get("area") or
                                           a["bbox"][2] * a["bbox"][3]),
                             "iscrowd": 0})
                aid += 1
                counts[(split, cname)] += 1
        print(f"{split:6s} {len(imgs):5,} images  {len(anns):6,} boxes")
        if dry_run:
            continue
        d = os.path.join(out, split)
        os.makedirs(d, exist_ok=True)
        for fn in files:
            dst = os.path.join(d, fn)
            if not os.path.exists(dst):
                shutil.copy2(os.path.join(src, fn), dst)
        with open(os.path.join(d, "_annotations.coco.json"), "w") as f:
            json.dump({"images": imgs, "annotations": anns,
                       "categories": [{"id": i, "name": nm,
                                       "supercategory": "panel"}
                                      for nm, i in index.items()]}, f)

    print("\nper class (train / valid / test)")
    for c in order:
        tr, va, te = (counts[("train", c)], counts[("valid", c)],
                      counts[("test", c)])
        flag = "  THIN" if tr < 100 else ""
        painted = "painted" if c in PAINTED_PANELS else "-"
        print(f"  {c:18s} {tr:5d} {va:5d} {te:5d}   {painted}{flag}")

    if dry_run:
        print("\n--dry-run: nothing written")
        return 0

    labels = ["_placeholder_"] + order
    with open(os.path.join(out, "labels.txt"), "w") as f:
        f.write(",".join(labels))
    print(f"\nwrote {out}  ({len(labels)} labels incl. placeholder)")
    return 0


def _selftest():
    ok = fail = 0

    def check(name, cond, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"  ok   {name}")
        else:
            fail += 1
            print(f"  FAIL {name} {detail}")

    doc = {
        "images": [{"id": 1, "file_name": "a.png", "width": 10, "height": 10},
                   {"id": 2, "file_name": "a.png", "width": 10, "height": 10},
                   {"id": 3, "file_name": "b.png", "width": 10, "height": 10}],
        "annotations": [
            {"id": 1, "image_id": 1, "category_id": 100, "bbox": [0, 0, 2, 2]},
            {"id": 2, "image_id": 2, "category_id": 200, "bbox": [1, 1, 2, 2]},
            {"id": 3, "image_id": 3, "category_id": 100, "bbox": [2, 2, 2, 2]},
            {"id": 4, "image_id": 99, "category_id": 100, "bbox": [0, 0, 1, 1]},
        ],
        "categories": [{"id": 100, "name": "hood"},
                       {"id": 200, "name": "scratch"}],
    }
    pooled, size, orphans = pool_by_filename(doc)
    check("two image records for one file are pooled",
          len(pooled["a.png"]) == 2, str(pooled["a.png"]))
    check("distinct files stay distinct", len(pooled) == 2)
    check("an annotation with no image record is counted, not crashed on",
          orphans == 1, str(orphans))
    check("sizes are recovered per filename", size["a.png"] == (10, 10))

    check("every painted panel is in the class list",
          all(p in PANEL_CLASSES for p in PAINTED_PANELS))
    check("every non-painted part is in the class list",
          all(p in PANEL_CLASSES for p in NON_PAINTED))
    check("no class appears twice",
          len(PANEL_CLASSES) == len(set(PANEL_CLASSES)))
    check("damage types are NOT panel classes",
          not any(d in PANEL_CLASSES for d in
                  ("scratch", "dent", "broken_part", "paint_chip")))
    # Every adjacency target must itself be a class, or compare_panels would
    # look up a panel the detector can never produce.
    targets = {t for v in PAINTED_PANELS.values() for t in v["adjacent"]}
    missing = sorted(t for t in targets if t not in PANEL_CLASSES)
    check("every adjacency target is a detectable class", not missing,
          str(missing))

    print(f"\n{ok} passed, {fail} failed")
    return 1 if fail else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="/home/user/cardata_parts/train")
    ap.add_argument("--out", default="/home/user/panels")
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    return build(a.src, a.out, a.seed, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
