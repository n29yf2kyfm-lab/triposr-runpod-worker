"""Delete only the labels that were LOOKED AT and confirmed wrong.

WHAT THIS DELETES, AND WHY ONLY THIS
------------------------------------
The label audit flagged four kinds of suspect annotation. Rendering samples of
each turned two of the four into keeps, so this removes two and leaves two
alone. The rendering mattered more than the counting:

  DELETE  sub-pixel boxes (under MICRO of frame). Measured at 2-7px square on
          a 640px image and roughly SQUARE rather than elongated, which is not
          the shape of a scratch. Zooming eight of them showed three-pixel
          marks on plain paint, marks on sensor noise, and -- twice out of
          eight -- a box drawn on the burned-in caption text "minor". They are
          annotations of nothing, and at 560 model input a 2px box is below
          what the network can represent even when something is there.

  DELETE  duplicate boxes of the SAME class overlapping above DUP_IOU. One
          damage annotated twice teaches nothing extra and double-counts the
          class. The larger box is kept, since the smaller is usually a
          partial re-draw.

  KEEP    whole-frame boxes. This was going to be the headline deletion --
          1,460 crack_glass boxes covering over 80% of frame, "somebody boxed
          the whole car". Rendering them showed the opposite: they are
          close-up photographs of a shattered windscreen, a broken tail light,
          a flat tyre, a crushed wing, where the damage genuinely does fill
          the frame. They are among the most informative images in the corpus
          and deleting them would have been pure destruction.

  KEEP    cross-class overlaps. 397 dent/scratch_scuff pairs label the same
          pixels twice, which looked like contradiction. A dented panel is
          very often also scratched, so both labels are true at once. Deleting
          either would teach the model that damage does not co-occur, which is
          false about real cars.

The corpus annotation files are rewritten in place, with the original kept
alongside as `_annotations.coco.json.orig` on first run so this is reversible.

    python clean_labels.py --corpus /home/user/rf/merged640 --dry-run
    python clean_labels.py --corpus /home/user/rf/merged640
"""
import argparse
import collections
import json
import os
import shutil
import sys

# Below this share of frame a box is 2-7px on a 640px image. See the docstring
# for what those actually contain.
MICRO = 5e-5

# Same-class overlap above this is one damage drawn twice.
DUP_IOU = 0.70


def iou_xywh(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    return inter / (aw * ah + bw * bh - inter)


def clean_image_detailed(anns, W, H):
    """(kept, micro_removed, dup_removed) with the removals themselves.

    The caller needs to know WHICH class each removal came from, and the
    earlier version reconstructed that by slicing `removed[:m]` / `removed[m:]`
    on the assumption that micro removals precede duplicate ones in annotation
    order. They interleave, so the per-class report attributed removals to the
    wrong classes. Returning the two lists is both simpler and correct.
    """
    frame = float(W * H) or 1.0
    survivors, micro = [], []
    for a in anns:
        x, y, w, h = a["bbox"]
        if w <= 0 or h <= 0 or (w * h) / frame < MICRO:
            micro.append(a)
            continue
        survivors.append(a)

    # Largest first, so the box that survives a duplicate pair is the larger.
    survivors.sort(key=lambda a: -(a["bbox"][2] * a["bbox"][3]))
    kept, dup = [], []
    for a in survivors:
        clash = False
        for b in kept:
            if a["category_id"] != b["category_id"]:
                continue          # cross-class overlap is legitimate — see docstring
            if iou_xywh(a["bbox"], b["bbox"]) > DUP_IOU:
                clash = True
                break
        (dup if clash else kept).append(a)
    return kept, micro, dup


def clean_image(anns, W, H):
    """(kept, n_micro, n_dup) — counts only. See clean_image_detailed."""
    kept, micro, dup = clean_image_detailed(anns, W, H)
    return kept, len(micro), len(dup)


def clean_source(path, dry_run):
    with open(path) as f:
        doc = json.load(f)
    cats = {c["id"]: c["name"] for c in doc["categories"]}
    size = {im["id"]: (im.get("width", 640), im.get("height", 640))
            for im in doc["images"]}

    by_img = collections.defaultdict(list)
    for a in doc["annotations"]:
        by_img[a["image_id"]].append(a)

    out, micro, dup = [], collections.Counter(), collections.Counter()
    for iid, anns in by_img.items():
        W, H = size.get(iid, (640, 640))
        kept, m_rm, d_rm = clean_image_detailed(anns, W, H)
        out.extend(kept)
        for a in m_rm:
            micro[cats.get(a["category_id"], "?")] += 1
        for a in d_rm:
            dup[cats.get(a["category_id"], "?")] += 1

    before, after = len(doc["annotations"]), len(out)
    rel = os.path.basename(os.path.dirname(path)) or "."
    print(f"\n{rel}: {before:,} boxes -> {after:,}  "
          f"(-{before - after:,})")
    for name, c in (("sub-pixel", micro), ("duplicate", dup)):
        if c:
            print(f"  {name:10s} " + ", ".join(
                f"{k} {v:,}" for k, v in sorted(c.items())))

    if not dry_run:
        orig = path + ".orig"
        if not os.path.exists(orig):
            shutil.copy2(path, orig)      # reversible, once
        doc["annotations"] = out
        with open(path, "w") as f:
            json.dump(doc, f)
    return before, after


def run(corpus, dry_run):
    sources = []
    for dirpath, _dn, filenames in os.walk(corpus):
        if "_annotations.coco.json" in filenames:
            sources.append(os.path.join(dirpath, "_annotations.coco.json"))
    if not sources:
        print(f"no annotation files beneath {corpus}")
        return 1
    print(f"cleaning {len(sources)} source(s) under {corpus}")
    tb = ta = 0
    for p in sorted(sources):
        b, a = clean_source(p, dry_run)
        tb += b
        ta += a
    print(f"\nTOTAL {tb:,} -> {ta:,} boxes  (-{tb - ta:,}, "
          f"{100.0 * (tb - ta) / max(1, tb):.2f}%)")
    print("\nKEPT deliberately: whole-frame boxes (verified close-ups of real "
          "damage) and cross-class overlaps (a dent really is often scratched)")
    if dry_run:
        print("--dry-run: nothing written")
    else:
        print("originals saved alongside as _annotations.coco.json.orig")
        print("rebuild the index next: build_train_index.py --coco "
              f"{corpus} ...")
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

    def ann(i, cid, box):
        return {"id": i, "image_id": 1, "category_id": cid, "bbox": list(box)}

    W = H = 640
    frame = W * H

    # a 3x3px box on a 640 frame is 2.2e-5 of frame -- under MICRO
    tiny = ann(1, 5, [100, 100, 3, 3])
    big = ann(2, 5, [10, 10, 200, 200])
    kept, m, d = clean_image([tiny, big], W, H)
    check("a 3x3px box is removed", m == 1 and kept == [big], str(kept))
    check("a normal box survives", big in kept)

    # exact duplicates of the same class collapse to one
    a1 = ann(1, 5, [50, 50, 100, 100])
    a2 = ann(2, 5, [52, 52, 100, 100])
    kept, m, d = clean_image([a1, a2], W, H)
    check("a same-class near-duplicate is collapsed",
          len(kept) == 1 and d == 1, str(kept))

    # ...and the LARGER survives. 90x90 inside 100x100 is IoU 0.81, a real
    # duplicate. (80x80 inside 100x100 is only 0.64 and is correctly KEPT as
    # two distinct boxes -- an earlier version of this test asserted otherwise
    # and was wrong about its own threshold.)
    small = ann(1, 5, [50, 50, 90, 90])
    large = ann(2, 5, [50, 50, 100, 100])
    kept, _m, d = clean_image([small, large], W, H)
    check("the larger of a duplicate pair is the one kept",
          kept == [large] and d == 1, str(kept))
    loose_s = ann(1, 5, [50, 50, 80, 80])
    loose_l = ann(2, 5, [50, 50, 100, 100])
    kept, _m, d = clean_image([loose_s, loose_l], W, H)
    check("boxes overlapping below the threshold are both kept",
          len(kept) == 2 and d == 0, str(kept))

    # cross-class overlap is KEPT — a scratched dent is two true labels
    dent = ann(1, 2, [50, 50, 100, 100])
    scr = ann(2, 5, [52, 52, 100, 100])
    kept, _m, d = clean_image([dent, scr], W, H)
    check("a dent and a scratch on the same pixels are both kept",
          len(kept) == 2 and d == 0, str(kept))

    # whole-frame boxes are KEPT — verified to be genuine close-ups
    whole = ann(1, 1, [0, 0, 640, 640])
    kept, _m, _d = clean_image([whole], W, H)
    check("a whole-frame box is kept", kept == [whole])

    # degenerate geometry goes
    zero = ann(1, 5, [10, 10, 0, 50])
    kept, m, _d = clean_image([zero], W, H)
    check("a zero-width box is removed", kept == [] and m == 1)

    check("the micro threshold is under one part in ten thousand",
          MICRO < 1e-4)
    check("a 3x3 box really is below the threshold",
          (3 * 3) / frame < MICRO, str((3 * 3) / frame))
    check("an 8x8 box is NOT below the threshold",
          (8 * 8) / frame > MICRO, str((8 * 8) / frame))
    check("duplicate detection needs substantial overlap", DUP_IOU >= 0.7)

    print(f"\n{ok} passed, {fail} failed")
    return 1 if fail else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="/home/user/rf/merged640")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    return run(a.corpus, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
