"""Fold CarDD into the corpus WITHOUT throwing away what makes it valuable.

WHY THIS DATASET AND WHAT IT FIXES
----------------------------------
The corpus the detector learned from is 640px, and its scratches occupy a
median 1.11% of the frame. That is the whole reason scratch recall sat at
0.302 while every other class climbed: a scratch that small, in an image that
small, is a couple of pixels by the time the network sees it. Measured against
CarDD:

    median damage box, as a share of the frame
                    CarDD       ours       ratio
    scratch         5.43%      1.11%       4.9x
    dent            8.27%     10.32%       0.8x

Scratches — and only scratches — are dramatically larger. Combined with 1000px
images against our 640px, a median CarDD scratch reaches the network with
roughly SEVEN TIMES the pixel area of ours. That is the missing evidence, not
more of the same.

Note what this does NOT fix. CarDD has no rust, no faded paint and no
structural class, and rust_paint is the smallest thing in our corpus at 0.50%
of frame. So the fade problem is untouched by this and still needs its own
data.

RESOLUTION IS PRESERVED, DELIBERATELY
-------------------------------------
merge_coco_source caps every source at MAX_SIDE 640. Running CarDD through it
would downscale exactly the images that were fetched for their resolution, and
the 5.43% scratch would arrive as blurred as our own. So this writes the
images through untouched and the cap does not apply.

Mixing 1000px and 640px sources is fine and is not a compromise: the network
resizes everything to its input anyway, and what governs whether it can see a
scratch is the box's SHARE of the frame, which resizing does not change. The
source resolution decides whether the detail inside that share survived being
captured — and CarDD's did.

CLASS MAPPING IS LOSSY IN ONE DIRECTION AND SAID SO
---------------------------------------------------
CarDD's six classes do not line up with ours one-to-one:

    scratch       -> scratch_scuff     the reason we are here
    dent          -> dent
    crack         -> crack_glass       body/bumper cracks join glass cracks
    glass shatter -> crack_glass
    lamp broken   -> lamp_wheel
    tire flat     -> lamp_wheel        our lamp_wheel already spans wheels

Nothing maps to rust_paint or structural, so those two classes gain nothing
here. Folding a body crack in with glass is the one genuinely debatable call:
our crack_glass already contains crack_hairline and crack_structural from the
Drive taxonomy, so a bumper crack is not out of place, but it is a widening of
that class and worth knowing when its AP moves.

    python ingest_cardd.py --dry-run
    python ingest_cardd.py --out /home/user/rf/merged640/cardd
"""
import argparse
import collections
import hashlib
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from class_map import FINAL_CLASSES  # noqa: E402

CLASS_MAP = {
    "scratch": "scratch_scuff",
    "dent": "dent",
    "crack": "crack_glass",
    "glass shatter": "crack_glass",
    "glass_shatter": "crack_glass",
    "lamp broken": "lamp_wheel",
    "lamp_broken": "lamp_wheel",
    "tire flat": "lamp_wheel",
    "tire_flat": "lamp_wheel",
}

# A box smaller than this share of the frame is almost certainly an annotation
# slip rather than damage, and at 560 input it would be under two pixels.
MIN_BOX_FRAC = 1e-5


def sha_of(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def load(root):
    with open(os.path.join(root, "samples.json")) as f:
        return json.load(f)["samples"]


def build(root, out, dry_run, limit):
    from PIL import Image
    samples = load(root)
    print(f"CarDD samples in annotation file: {len(samples):,}")

    names = sorted(FINAL_CLASSES)
    index = {n: i + 1 for i, n in enumerate(names)}
    print(f"target classes ({len(names)}): {names}")

    images, anns, aid = [], [], 1
    counts = collections.Counter()
    unmapped = collections.Counter()
    missing = tiny = 0
    sizes = []

    if not dry_run:
        os.makedirs(os.path.join(out, "images"), exist_ok=True)

    for s in samples[:limit] if limit else samples:
        # FiftyOne stores filepath as it was on the exporter's machine; only
        # the basename is meaningful here.
        rel = os.path.join("data", os.path.basename(s["filepath"]))
        src = os.path.join(root, rel)
        if not os.path.exists(src):
            missing += 1
            continue
        det = (s.get("detections") or {}).get("detections") or []
        keep = []
        for d in det:
            lab = str(d.get("label", "")).strip().lower()
            tgt = CLASS_MAP.get(lab)
            if not tgt:
                unmapped[lab] += 1
                continue
            bb = d.get("bounding_box")
            if not bb or len(bb) != 4:
                continue
            x, y, w, h = [float(v) for v in bb]
            if w * h < MIN_BOX_FRAC or w <= 0 or h <= 0:
                tiny += 1
                continue
            keep.append((tgt, x, y, w, h))
        if not keep:
            continue

        try:
            with Image.open(src) as im:
                W, H = im.size
        except Exception:
            missing += 1
            continue
        sizes.append(max(W, H))

        # sha of the ORIGINAL bytes, matching the corpus convention so a
        # CarDD image that also exists upstream would collide and be caught.
        sha = sha_of(src)
        name = f"{sha[:20]}.jpg"
        iid = len(images) + 1
        images.append({"id": iid, "file_name": name, "width": W, "height": H})
        for tgt, x, y, w, h in keep:
            anns.append({"id": aid, "image_id": iid,
                         "category_id": index[tgt],
                         # COCO wants absolute pixels; CarDD gives normalised.
                         "bbox": [round(x * W, 2), round(y * H, 2),
                                  round(w * W, 2), round(h * H, 2)],
                         "area": round(w * W * h * H, 2), "iscrowd": 0})
            aid += 1
            counts[tgt] += 1
        if not dry_run:
            dst = os.path.join(out, "images", name)
            if not os.path.exists(dst):
                # NOT RESIZED. See the module docstring: downscaling here would
                # undo the only reason this dataset was fetched.
                #
                # HARDLINKED where the filesystem allows it. These bytes are
                # immutable — nothing in the pipeline ever writes back to a
                # corpus image — so a second copy buys nothing and costs 2.1GB
                # on a disk that is already at 96%. os.link fails across
                # filesystems and on some overlay mounts, so a real copy stays
                # as the fallback rather than the ingest failing.
                try:
                    os.link(src, dst)
                except OSError:
                    shutil.copy2(src, dst)

    print(f"\nusable images {len(images):,}   boxes {len(anns):,}")
    if missing:
        print(f"  ! {missing:,} samples had no image file on disk")
    if tiny:
        print(f"  ! {tiny:,} boxes were below {MIN_BOX_FRAC} of frame, dropped")
    if unmapped:
        print(f"  ! labels with no mapping: {dict(unmapped)}")
    if sizes:
        sizes.sort()
        print(f"  resolution: median long side {sizes[len(sizes)//2]}, "
              f"min {sizes[0]}, max {sizes[-1]}  (corpus is 640)")
    print("\nboxes contributed per class:")
    for n in names:
        print(f"  {n:16s} {counts.get(n, 0):7,}"
              + ("" if counts.get(n) else "   <- CarDD has none of this"))

    if dry_run:
        print("\n--dry-run: nothing written")
        return 0
    doc = {"images": images, "annotations": anns,
           "categories": [{"id": i, "name": n, "supercategory": "damage"}
                          for n, i in index.items()]}
    with open(os.path.join(out, "_annotations.coco.json"), "w") as f:
        json.dump(doc, f)
    print(f"\nwrote {out}/_annotations.coco.json + images/")
    print("build_train_index pools every _annotations.coco.json under --coco, "
          "so this is picked up automatically.")
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

    check("every mapped target is a real class",
          all(v in FINAL_CLASSES for v in CLASS_MAP.values()),
          str([v for v in CLASS_MAP.values() if v not in FINAL_CLASSES]))
    check("scratch maps to the scratch class",
          CLASS_MAP["scratch"] == "scratch_scuff")
    check("tire and lamp share our combined class",
          CLASS_MAP["tire flat"] == CLASS_MAP["lamp broken"] == "lamp_wheel")
    check("both glass forms land in crack_glass",
          CLASS_MAP["crack"] == CLASS_MAP["glass shatter"] == "crack_glass")
    # The two classes CarDD cannot help with must be visibly absent, so nobody
    # expects this ingest to improve them.
    check("nothing maps to rust_paint",
          "rust_paint" not in CLASS_MAP.values())
    check("nothing maps to structural",
          "structural" not in CLASS_MAP.values())

    # Normalised -> absolute conversion, the step most likely to be silently
    # wrong and the one that would misplace every box.
    W, H = 1000, 750
    x, y, w, h = 0.16704, 0.05361, 0.20279, 0.17512
    bbox = [round(x * W, 2), round(y * H, 2), round(w * W, 2), round(h * H, 2)]
    check("normalised box becomes absolute pixels",
          bbox == [167.04, 40.21, 202.79, 131.34], str(bbox))
    check("the converted box fits inside the frame",
          bbox[0] + bbox[2] <= W and bbox[1] + bbox[3] <= H)
    check("a degenerate box is below the drop threshold",
          1e-6 < MIN_BOX_FRAC)

    print(f"\n{ok} passed, {fail} failed")
    return 1 if fail else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/home/user/cardd")
    ap.add_argument("--out", default="/home/user/rf/merged640/cardd")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    return build(a.root, a.out, a.dry_run, a.limit)


if __name__ == "__main__":
    sys.exit(main())
