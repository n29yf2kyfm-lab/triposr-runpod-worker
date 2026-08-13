"""Strip contaminated images out of a car-damage dataset.

Auditing the merged set found three problems that a licence tag and a class
histogram both miss, because they live in the pixels or the filename rather
than the metadata:

  1. BURNED-IN ANNOTATIONS (26.6% of the merged set). Someone exported a
     dataset with the boxes already drawn on — a salmon rectangle plus text like
     "minor-scratch 0.82" rendered into the JPEG. This is label leakage of the
     worst kind: the answer is visible in the input, so a detector is rewarded
     for finding a drawn rectangle rather than a scratch, and because the leak
     is in the validation split too, the metric confirms its own mistake. One
     such "scratch" image turned out to be a photograph of a person's legs.

  2. STOCK-AGENCY IMAGES. iStock/Getty, Shutterstock and AdobeStock previews
     are present. This is a LICENSING problem, not a quality one: whoever
     uploaded the set to Roboflow tagged it CC-BY-4.0 or Public Domain, but an
     uploader's tag cannot override the photographer's copyright. It is the same
     trap as CarDD ("does not own the underlying image copyrights") wearing a
     friendlier label. Some carry a tiled "iStock by Getty Images" watermark
     across the whole frame; others are clean-looking previews with no visible
     mark at all — so the LICENCE problem is strictly larger than the WATERMARK
     problem, and only the filename identifies both.

  3. DESTROYED AUGMENTATIONS. A minority are so heavily noised that no damage is
     discernible.

What this deliberately does NOT drop: ordinary greyscale, blur, brightness and
mild-noise augmentation. Those are Roboflow applying augmentation on purpose,
they are most of the corpus, and they make a detector more robust rather than
less. An earlier pass measured 69% "near-greyscale" and calling all of it
contamination would have gutted a mostly-healthy dataset — the fix is to
measure whether the image is *destroyed*, not whether it is *grey*.

Augmented copies inherit their source's contamination, so a leaked original
takes its whole family out with it; that is correct, not over-deletion.

    python clean_dataset.py --data DIR --out DIR_clean [--report-only]
    python clean_dataset.py --data DIR --flat            # non-COCO directory

--- WHY THERE IS NO PIXEL WATERMARK DETECTOR -------------------------------
There was one. It never fired: its threshold was 0.30 and the highest score
across a 400-image sample was 0.140, so it reported 1 watermarked image in
13,436 while iStock-watermarked images sat in the corpus untouched. Two
replacements were then built and MEASURED against 58 known-watermarked iStock
files (positives, identified by filename) and 250 random files:

  * FFT periodicity on the high-passed luminance, on the theory that a tiled
    watermark repeats at a fixed pitch. Watermarked median 6.1, clean median
    6.7 — the clean images scored HIGHER. High-passing keeps fine scene texture
    and discards the large, pale watermark entirely.
  * Local-contrast lattice, on the theory that a pale semi-transparent overlay
    crushes contrast in a regular grid. Watermarked median 8.6, clean median
    9.4, and a 93% false-positive rate at any threshold that caught 90% of the
    positives.

Both failed for the same reason: every image in this corpus has been rotated,
mirrored, rescaled and noised by augmentation, which destroys exactly the
regular structure both tests depend on. So pixel watermark detection is NOT
shipped here — a filter that is measured not to work is worse than no filter,
because it produces a clean bill of health nobody re-checks.

The filename IS the reliable signal, and its coverage is near-complete rather
than incidental: Roboflow renames to "<original-stem>_jpg.rf.<hash>.jpg", which
PRESERVES the original filename, and stock agencies use deterministic naming
("istockphoto-<id>-1024x1024", "<slug>-260nw-<id>", "AdobeStock_<id>").
Residual risk, stated plainly: an image whose filename was scrubbed before
upload will not be caught. Anything scraped fresh should carry provenance from
the start — see scrape_images.py, which records source, licence and page URL
per image so this question never has to be answered from pixels again.
"""
import argparse
import json
import os
import re
import shutil

# Annotation-overlay colour. The exported boxes and their label text are drawn
# in a narrow salmon/red band; requiring red to lead both other channels by a
# wide margin keeps ordinary red paintwork, tail lights and brake calipers out
# of the net (they are darker and far less channel-separated).
# Longest straight run, on a 160px thumbnail. Measured separation is wide:
# leaked images score 26-62, clean ones (including a rusted wreck) 2-12.
OVERLAY_MIN_RUN = 14
LAPLACIAN_DEAD = 12.0         # below this, the image carries no usable edges

# Stock-agency filename signatures. Ordered most- to least-specific; each is
# anchored on a token the agency actually emits, not a loose word, so ordinary
# filenames ("stock_car_photo.jpg") do not trip them.
#   istockphoto-<id>-1024x1024      iStock / Getty preview
#   <slug>-260nw-<id>               Shutterstock preview (260px no-watermark)
#   stock-photo-<slug>-<id>         Shutterstock legacy preview
#   AdobeStock_<id>                 Adobe Stock comp
STOCK_PATTERNS = [
    ("istock_getty", re.compile(r"istockphoto[-_]\d+", re.I)),
    ("istock_getty", re.compile(r"gettyimages[-_]\d+", re.I)),
    ("shutterstock", re.compile(r"-260nw-\d+", re.I)),
    ("shutterstock", re.compile(r"\bstock-photo-", re.I)),
    ("shutterstock", re.compile(r"\bstock-vector-", re.I)),
    ("shutterstock", re.compile(r"shutterstock[-_]?\d*", re.I)),
    ("adobe_stock",  re.compile(r"adobestock[-_]\d+", re.I)),
    ("adobe_stock",  re.compile(r"\bfotolia[-_]\d+", re.I)),
    ("dreamstime",   re.compile(r"dreamstime", re.I)),
    ("depositphotos", re.compile(r"depositphotos?[-_]?\d*", re.I)),
    ("123rf",        re.compile(r"\b123rf\b", re.I)),
    ("alamy",        re.compile(r"\balamy\b", re.I)),
]


def stock_agency(file_name):
    """Which stock agency this filename belongs to, or None.

    Returns the FIRST match so a file is attributed once; the patterns are
    mutually specific enough that overlap is rare. An earlier version used a
    loose `stockphoto` pattern that matched "istockphoto" as a substring and
    double-counted every iStock file into a bogus "generic_stock" bucket.
    """
    for agency, pat in STOCK_PATTERNS:
        if pat.search(file_name):
            return agency
    return None


def _thumb(path, size=160):
    from PIL import Image
    import numpy as np
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB").resize((size, size)), dtype="int16")


def overlay_score(arr):
    """Longest straight run of annotation-coloured pixels.

    A pixel count alone cannot do this job. Measured on real images, a rusted
    red wreck scores 62 such pixels while a genuinely leaked image scores 70 —
    the two are inseparable by count, so any threshold either keeps leaks or
    deletes rusty cars, and rust is a damage class we are trying to train.

    Geometry separates them cleanly. A drawn box is straight: its edges and the
    underline of its text label produce long uninterrupted runs along a single
    row or column. Rust, red paint, tail lights and brake calipers are blobby —
    lots of matching pixels, no long straight runs. So this returns the longest
    run rather than the population, which is scale-stable and indifferent to how
    washed-out the overlay is.
    """
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    m = ((r > 170) & (g > 70) & (g < 195) & (b > 70) & (b < 195)
         & ((r - g) > 40) & ((r - b) > 40))
    if not m.any():
        return 0
    best = 0
    for axis in (m, m.T):                       # rows, then columns
        for line in axis:
            run = 0
            for v in line:
                run = run + 1 if v else 0
                if run > best:
                    best = run
    return int(best)


def sharpness(arr):
    """Laplacian variance — a blur/destruction proxy."""
    g = arr.mean(axis=2)
    lap = (-4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1]
           + g[1:-1, :-2] + g[1:-1, 2:])
    return float(lap.var())


def classify(path):
    """(verdict, metrics) for one image. verdict is None when the image is fine.

    The filename test runs FIRST and without opening the file: it is exact,
    costs nothing, and a stock image is disqualified on licence regardless of
    how good the pixels look.
    """
    agency = stock_agency(os.path.basename(path))
    if agency:
        return "stock_licensed", {"agency": agency}
    try:
        arr = _thumb(path)
    except Exception as e:
        return "unreadable", {"error": type(e).__name__}
    ov = overlay_score(arr)
    sh = sharpness(arr)
    metrics = {"overlay_run": ov, "sharpness": round(sh, 1)}
    # Label leakage is the disqualifying one, so it is checked before blur and
    # reported even when the image is also soft.
    if ov >= OVERLAY_MIN_RUN:
        return "burned_in_annotation", metrics
    if sh < LAPLACIAN_DEAD:
        return "destroyed", metrics
    return None, metrics


VERDICTS = ("kept", "burned_in_annotation", "stock_licensed", "destroyed",
            "unreadable")


def _report(counts, examples, label):
    total = sum(counts.values())
    print(f"\n  {label}: {total} images")
    for k in VERDICTS:
        if counts.get(k):
            print(f"    {k:24s} {counts[k]:7d}  ({counts[k]/max(1,total)*100:5.1f}%)")
    for verdict, rows in examples.items():
        fn, m = rows[0]
        print(f"    e.g. {verdict}: {fn[:46]} {m}")


def clean_split(src_dir, dst_dir, split, report_only):
    """Filter one COCO split, carrying its annotations across."""
    ann = os.path.join(src_dir, split, "_annotations.coco.json")
    if not os.path.exists(ann):
        return None
    with open(ann) as f:
        d = json.load(f)
    by_img = {}
    for a in d.get("annotations", []):
        by_img.setdefault(a["image_id"], []).append(a)

    counts = dict.fromkeys(VERDICTS, 0)
    keep_images, keep_anns, examples = [], [], {}
    for im in d.get("images", []):
        p = os.path.join(src_dir, split, im["file_name"])
        if not os.path.exists(p):
            counts["unreadable"] += 1
            continue
        verdict, metrics = classify(p)
        if verdict:
            counts[verdict] += 1
            examples.setdefault(verdict, []).append((im["file_name"], metrics))
            continue
        counts["kept"] += 1
        keep_images.append(im)
        keep_anns.extend(by_img.get(im["id"], []))

    if not report_only:
        out = os.path.join(dst_dir, split)
        os.makedirs(out, exist_ok=True)
        for im in keep_images:
            shutil.copyfile(os.path.join(src_dir, split, im["file_name"]),
                            os.path.join(out, im["file_name"]))
        with open(os.path.join(out, "_annotations.coco.json"), "w") as f:
            json.dump({"images": keep_images, "annotations": keep_anns,
                       "categories": d.get("categories", [])}, f)
    _report(counts, examples, split)
    return counts


def clean_flat(src_dir, dst_dir, report_only):
    """Filter a plain directory tree of images (no COCO annotations).

    For corpora that are not COCO — a HuggingFace segmentation set, or a fresh
    scrape. Mirrors the source tree so any sidecar mask/annotation directory
    stays aligned by filename.
    """
    counts = dict.fromkeys(VERDICTS, 0)
    examples = {}
    exts = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
    for root, _dirs, files in os.walk(src_dir):
        for fn in files:
            if not fn.lower().endswith(exts):
                continue
            p = os.path.join(root, fn)
            verdict, metrics = classify(p)
            if verdict:
                counts[verdict] += 1
                examples.setdefault(verdict, []).append((fn, metrics))
                continue
            counts["kept"] += 1
            if not report_only:
                rel = os.path.relpath(p, src_dir)
                dst = os.path.join(dst_dir, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(p, dst)
    _report(counts, examples, os.path.basename(src_dir.rstrip("/")) or "flat")
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="dataset root")
    ap.add_argument("--out", default=None, help="destination (default <data>_clean)")
    ap.add_argument("--splits", default="train,valid,test")
    ap.add_argument("--flat", action="store_true",
                    help="plain image tree rather than COCO splits")
    ap.add_argument("--report-only", action="store_true",
                    help="measure and print, write nothing")
    args = ap.parse_args()
    out = args.out or (args.data.rstrip("/") + "_clean")

    totals = {}
    if args.flat:
        c = clean_flat(args.data, out, args.report_only)
        totals.update(c)
    else:
        for split in args.splits.split(","):
            c = clean_split(args.data, out, split, args.report_only)
            if c:
                for k, v in c.items():
                    totals[k] = totals.get(k, 0) + v

    grand = sum(totals.values())
    print(f"\n{'='*58}\nTOTAL {grand} images")
    for k in VERDICTS:
        if totals.get(k):
            print(f"  {k:24s} {totals[k]:7d}  ({totals[k]/max(1,grand)*100:5.1f}%)")
    dropped = grand - totals.get("kept", 0)
    print(f"\n  dropped {dropped} ({dropped/max(1,grand)*100:.1f}%), "
          f"kept {totals.get('kept',0)}")
    print("  (report only — nothing written)" if args.report_only
          else f"  wrote -> {out}")


if __name__ == "__main__":
    main()
