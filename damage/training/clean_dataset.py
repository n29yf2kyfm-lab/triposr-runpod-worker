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


# The exporter's label vocabulary. Its overlays read "minor-scratch 0.82",
# "dent 0.41" and similar, so finding one of these words rendered INTO the
# image is direct evidence of a burned-in annotation.
LABEL_WORDS = ("scratch", "minor", "dent", "damage", "crack", "major")


def _edit(a, b):
    """Levenshtein distance. Small strings only; not worth a dependency."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def label_hit(text):
    """Fuzzy-match OCR output against the label vocabulary, or None.

    Exact matching finds nothing: tesseract reads these overlays as 'serotcn',
    'strateh', 'scrotch', 'mine -serdien'. Allowing an edit distance of up to a
    third of the word recovers them, while the noise tokens that clean images
    produce ('zz.', '~~,', 'bY') stay far from any real word — measured at zero
    false positives across 24 clean trials.
    """
    import re
    s = re.sub(r"[^a-z]", " ", (text or "").lower())
    for w in (w for w in s.split() if len(w) >= 4):
        for t in LABEL_WORDS:
            tol = max(1, len(t) // 3)
            for L in (len(t) - 1, len(t), len(t) + 1):
                for i in range(0, max(1, len(w) - L + 1)):
                    sub = w[i:i + L]
                    if len(sub) >= 4 and _edit(sub, t) <= tol:
                        return t
    return None


def ocr_label(path, upscale=4):
    """The damage-word rendered into this image, or None.

    THE KEY STEP IS COLOUR ISOLATION, NOT OCR. Running tesseract on the photo
    returns pure noise, because every image here carries augmentation grain and
    the label text is only ~10px tall. Masking to the overlay hue first turns it
    into clean black-on-white glyphs that tesseract reads, and the augmentation
    noise is discarded because it does not match the hue.

    Two page-segmentation modes are tried: 11 (sparse text) catches most, 6
    (uniform block) catches a few that 11 misses. Measured 4/6 recall at 100%
    precision on a hand-labelled set — deliberately reported rather than
    rounded up, because the residual third is why a separate 'suspect' verdict
    exists instead of a single confident drop.
    """
    import numpy as np
    from PIL import Image
    try:
        import pytesseract
    except ImportError:
        return None
    try:
        with Image.open(path) as im:
            a = np.asarray(im.convert("RGB"), dtype="int16")
    except Exception:
        return None
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    m = (r > 150) & ((r - g) > 30) & ((r - b) > 30)
    if m.sum() < 20:
        return None
    img = Image.fromarray(np.where(m, 0, 255).astype("uint8"), "L")
    w, h = img.size
    img = img.resize((w * upscale, h * upscale), Image.LANCZOS)
    for cfg in ("--psm 11", "--psm 6"):
        try:
            got = label_hit(pytesseract.image_to_string(img, config=cfg))
        except Exception:
            return None
        if got:
            return got
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


def classify(path, use_ocr=True):
    """(verdict, metrics) for one image. verdict is None when the image is fine.

    Verdicts are TIERED by how much the evidence is worth, because the two
    signals here have opposite strengths and collapsing them into one boolean
    is what made the previous version untrustworthy:

      burned_in_annotation  OCR read a damage word rendered into the image.
                            Direct evidence. ~100% precision, ~67% recall.
      annotation_suspect    The overlay colour forms a long straight run but no
                            text was read. HIGH RECALL, POOR PRECISION — roughly
                            half of these are red cars, rust and smashed glass,
                            verified by eye. Kept as its own verdict so it can
                            be quarantined for review instead of deleted, and
                            so the cost of acting on it is always visible in the
                            report rather than hidden inside one total.

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

    # OCR is ~30x more expensive than the pixel stats, so it only runs where
    # there is enough overlay-coloured ink for a label to plausibly exist.
    # The gate is deliberately far below OVERLAY_MIN_RUN: the point is to skip
    # images with no candidate ink at all, not to pre-judge them.
    if use_ocr and ov >= 5:
        word = ocr_label(path)
        if word:
            metrics["label_word"] = word
            return "burned_in_annotation", metrics

    if ov >= OVERLAY_MIN_RUN:
        return "annotation_suspect", metrics
    if sh < LAPLACIAN_DEAD:
        return "destroyed", metrics
    return None, metrics


VERDICTS = ("kept", "burned_in_annotation", "annotation_suspect",
            "stock_licensed", "destroyed", "unreadable")


def _report(counts, examples, label):
    total = sum(counts.values())
    print(f"\n  {label}: {total} images")
    for k in VERDICTS:
        if counts.get(k):
            print(f"    {k:24s} {counts[k]:7d}  ({counts[k]/max(1,total)*100:5.1f}%)")
    for verdict, rows in examples.items():
        fn, m = rows[0]
        print(f"    e.g. {verdict}: {fn[:46]} {m}")


def _classify_one(args):
    """Worker entry point — must be module-level to be picklable."""
    path, use_ocr = args
    return path, classify(path, use_ocr)


def _classify_many(paths, use_ocr, jobs, progress_every=500):
    """{path: (verdict, metrics)}, computed across a process pool.

    OCR costs ~0.36s per image against ~0.01s for the pixel stats, which turns
    a 13k-image pass from a minute into most of an hour on one core. The work is
    embarrassingly parallel and purely CPU-bound, so a pool sized to the cores
    is the whole optimisation.

    USES THE "spawn" START METHOD, NOT THE DEFAULT FORK. pytesseract shells out
    to the tesseract binary through subprocess, and a forked child inherits the
    parent's lock state at the instant of the fork; combining the two deadlocked
    this pass reliably — the parent parked in futex_do_wait, the four workers
    burned one second of CPU each and then slept forever, and 34 minutes later
    the run had produced nothing at all. spawn starts each worker as a clean
    interpreter with no inherited locks, at the cost of re-importing this module
    per worker, which is microseconds against a 0.36s OCR call.

    Progress is printed and FLUSHED as it goes for the same reason: the silent
    version was indistinguishable from the deadlocked one.
    """
    import sys
    items = [(p, use_ocr) for p in paths]
    if jobs <= 1 or len(items) < 32:
        # Progress here too, not only in the pool branch. The first version
        # printed nothing on this path, so a 13k-image single-threaded run —
        # the very fallback chosen BECAUSE the pool deadlocked — produced an
        # empty log for minutes and was indistinguishable from a hang. Silence
        # is the failure mode this whole function is trying to avoid.
        out = {}
        for i, it in enumerate(items, 1):
            path, res = _classify_one(it)
            out[path] = res
            if progress_every and i % progress_every == 0:
                print(f"    ...{i}/{len(items)}", flush=True)
                sys.stdout.flush()
        return out
    import multiprocessing as mp
    ctx = mp.get_context("spawn")
    out = {}
    with ctx.Pool(jobs) as pool:
        for i, (path, res) in enumerate(
                pool.imap_unordered(_classify_one, items, chunksize=8), 1):
            out[path] = res
            if progress_every and i % progress_every == 0:
                print(f"    ...{i}/{len(items)}", flush=True)
                sys.stdout.flush()
    return out


def clean_split(src_dir, dst_dir, split, report_only, use_ocr=True, jobs=1,
                keep_suspect=False, quarantine=None):
    """Filter one COCO split, carrying its annotations across."""
    ann = os.path.join(src_dir, split, "_annotations.coco.json")
    if not os.path.exists(ann):
        return None
    with open(ann) as f:
        d = json.load(f)
    by_img = {}
    for a in d.get("annotations", []):
        by_img.setdefault(a["image_id"], []).append(a)

    images = d.get("images", [])
    paths = [os.path.join(src_dir, split, im["file_name"]) for im in images]
    present = [p for p in paths if os.path.exists(p)]
    verdicts = _classify_many(present, use_ocr, jobs)

    counts = dict.fromkeys(VERDICTS, 0)
    keep_images, keep_anns, examples, quarantined = [], [], {}, []
    for im, p in zip(images, paths):
        if p not in verdicts:
            counts["unreadable"] += 1
            continue
        verdict, metrics = verdicts[p]
        # A suspect is dropped from the training set but, unless the caller
        # opts to keep it, preserved in a quarantine directory rather than
        # deleted — the signal is only about half right and the images it
        # removes are otherwise perfectly good training data.
        if verdict == "annotation_suspect" and keep_suspect:
            verdict = None
        if verdict:
            counts[verdict] += 1
            examples.setdefault(verdict, []).append((im["file_name"], metrics))
            if verdict == "annotation_suspect" and quarantine:
                quarantined.append(im["file_name"])
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
        if quarantine and quarantined:
            qdir = os.path.join(quarantine, split)
            os.makedirs(qdir, exist_ok=True)
            for fn in quarantined:
                shutil.copyfile(os.path.join(src_dir, split, fn),
                                os.path.join(qdir, fn))
    _report(counts, examples, split)
    return counts


def clean_flat(src_dir, dst_dir, report_only, use_ocr=True, jobs=1,
               keep_suspect=False, quarantine=None):
    """Filter a plain directory tree of images (no COCO annotations).

    For corpora that are not COCO — a HuggingFace segmentation set, a class-per-
    folder collection, or a fresh scrape. Mirrors the source tree, so a
    class-named parent directory survives the clean and any sidecar mask
    directory stays aligned by filename.

    SKIPS mask directories. A segmentation dataset ships masks_human/ renderings
    that are annotation overlays BY DESIGN; walking them made an earlier audit
    report 5,436 images at 22% contaminated when the real photo count was 1,811.
    """
    counts = dict.fromkeys(VERDICTS, 0)
    examples = {}
    exts = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
    skip = {"masks_human", "masks_machine", "ann", "masks"}
    paths = []
    for root, dirs, files in os.walk(src_dir):
        dirs[:] = [d for d in dirs if d not in skip]
        for fn in files:
            if fn.lower().endswith(exts):
                paths.append(os.path.join(root, fn))
    verdicts = _classify_many(paths, use_ocr, jobs)

    for p in paths:
        fn = os.path.basename(p)
        verdict, metrics = verdicts.get(p, ("unreadable", {}))
        if verdict == "annotation_suspect" and keep_suspect:
            verdict = None
        if verdict:
            counts[verdict] += 1
            examples.setdefault(verdict, []).append((fn, metrics))
            if verdict == "annotation_suspect" and quarantine and not report_only:
                dst = os.path.join(quarantine, os.path.relpath(p, src_dir))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(p, dst)
            continue
        counts["kept"] += 1
        if not report_only:
            dst = os.path.join(dst_dir, os.path.relpath(p, src_dir))
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
    ap.add_argument("--no-ocr", action="store_true",
                    help="skip OCR confirmation (fast, but then every overlay "
                         "hit is only a suspect)")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2)),
                    help="parallel workers; OCR is CPU-bound")
    ap.add_argument("--keep-suspect", action="store_true",
                    help="keep overlay-suspect images (no OCR-confirmed text). "
                         "About half of them are red cars and rust, so keeping "
                         "them trades some leakage for a lot more data.")
    ap.add_argument("--quarantine", default=None,
                    help="copy suspects here instead of only dropping them")
    args = ap.parse_args()
    out = args.out or (args.data.rstrip("/") + "_clean")
    use_ocr = not args.no_ocr

    totals = {}
    if args.flat:
        c = clean_flat(args.data, out, args.report_only, use_ocr, args.jobs,
                       args.keep_suspect, args.quarantine)
        totals.update(c)
    else:
        for split in args.splits.split(","):
            c = clean_split(args.data, out, split, args.report_only, use_ocr,
                            args.jobs, args.keep_suspect, args.quarantine)
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
