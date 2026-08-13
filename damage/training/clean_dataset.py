"""Strip contaminated images out of a merged car-damage dataset.

Auditing the merged set found three problems that a licence tag and a class
histogram both miss, because they live in the pixels rather than the metadata:

  1. BURNED-IN ANNOTATIONS (~16% of a 400-image sample). Someone exported a
     dataset with the boxes already drawn on — a salmon rectangle plus text like
     "minor-scratch 0.82" rendered into the JPEG. This is label leakage of the
     worst kind: the answer is visible in the input, so a detector is rewarded
     for finding a drawn rectangle rather than a scratch, and because the leak
     is in the validation split too, the metric confirms its own mistake. One
     such "scratch" image turned out to be a photograph of a person's legs.

  2. STOCK-AGENCY WATERMARKS. Shutterstock, Alamy and Dreamstime marks appear in
     random samples. This is a LICENSING problem, not a quality one: whoever
     uploaded the set to Roboflow tagged it CC-BY-4.0 or Public Domain, but an
     uploader's tag cannot override the photographer's copyright. It is the same
     trap as CarDD ("does not own the underlying image copyrights") wearing a
     friendlier label.

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

    python clean_dataset.py --data merged --out merged_clean [--report-only]
"""
import argparse
import json
import os
import shutil

# Annotation-overlay colour. The exported boxes and their label text are drawn
# in a narrow salmon/red band; requiring red to lead both other channels by a
# wide margin keeps ordinary red paintwork, tail lights and brake calipers out
# of the net (they are darker and far less channel-separated).
# Longest straight run, on a 160px thumbnail. Measured separation is wide:
# leaked images score 26-48, clean ones (including a rusted wreck) 2-12.
OVERLAY_MIN_RUN = 14
LAPLACIAN_DEAD = 12.0         # below this, the image carries no usable edges


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
    import numpy as np
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


def watermark_score(arr):
    """Text-like structure in the bottom band, where stock marks sit.

    Deliberately a shape test rather than OCR: agencies differ in wording but
    all park a light-on-dark or dark-on-light strip along the bottom edge. It
    is a flag for review, not a verdict — hence reported separately.
    """
    import numpy as np
    band = arr[int(arr.shape[0] * 0.86):, :, :].mean(axis=2)
    if band.size == 0:
        return 0.0
    # Text produces many sharp horizontal transitions against a flat backdrop.
    edges = np.abs(np.diff(band, axis=1))
    return float((edges > 40).mean())


def sharpness(arr):
    """Laplacian variance — a blur/destruction proxy."""
    import numpy as np
    g = arr.mean(axis=2)
    lap = (-4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1]
           + g[1:-1, :-2] + g[1:-1, 2:])
    return float(lap.var())


def classify(path, wm_threshold=0.30):
    """(verdict, metrics) for one image. verdict is None when the image is fine."""
    try:
        arr = _thumb(path)
    except Exception as e:
        return "unreadable", {"error": f"{type(e).__name__}"}
    ov = overlay_score(arr)
    wm = watermark_score(arr)
    sh = sharpness(arr)
    metrics = {"overlay_run": ov, "watermark": round(wm, 3), "sharpness": round(sh, 1)}
    # Order matters: label leakage is the disqualifying one, so it is checked
    # first and reported even when the image is also blurry or watermarked.
    if ov >= OVERLAY_MIN_RUN:
        return "burned_in_annotation", metrics
    if wm >= wm_threshold:
        return "watermark_suspect", metrics
    if sh < LAPLACIAN_DEAD:
        return "destroyed", metrics
    return None, metrics


def clean_split(src_dir, dst_dir, split, report_only, wm_threshold):
    ann = os.path.join(src_dir, split, "_annotations.coco.json")
    if not os.path.exists(ann):
        return None
    d = json.load(open(ann))
    by_img = {}
    for a in d.get("annotations", []):
        by_img.setdefault(a["image_id"], []).append(a)

    counts = {"kept": 0, "burned_in_annotation": 0, "watermark_suspect": 0,
              "destroyed": 0, "unreadable": 0}
    keep_images, keep_anns, examples = [], [], {}
    for im in d.get("images", []):
        p = os.path.join(src_dir, split, im["file_name"])
        if not os.path.exists(p):
            counts["unreadable"] += 1
            continue
        verdict, metrics = classify(p, wm_threshold)
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

    total = sum(counts.values())
    print(f"\n  {split}: {total} images")
    for k in ("kept", "burned_in_annotation", "watermark_suspect", "destroyed",
              "unreadable"):
        if counts[k]:
            print(f"    {k:24s} {counts[k]:7d}  ({counts[k]/max(1,total)*100:5.1f}%)")
    for verdict, rows in examples.items():
        fn, m = rows[0]
        print(f"    e.g. {verdict}: {fn[:46]} {m}")
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="merged dataset root")
    ap.add_argument("--out", default="merged_clean")
    ap.add_argument("--splits", default="train,valid,test")
    ap.add_argument("--report-only", action="store_true",
                    help="measure and print, write nothing")
    ap.add_argument("--watermark-threshold", type=float, default=0.30)
    args = ap.parse_args()

    totals = {}
    for split in args.splits.split(","):
        c = clean_split(args.data, args.out, split, args.report_only,
                        args.watermark_threshold)
        if c:
            for k, v in c.items():
                totals[k] = totals.get(k, 0) + v

    grand = sum(totals.values())
    print(f"\n{'='*58}\nTOTAL {grand} images")
    for k, v in sorted(totals.items(), key=lambda kv: -kv[1]):
        print(f"  {k:24s} {v:7d}  ({v/max(1,grand)*100:5.1f}%)")
    dropped = grand - totals.get("kept", 0)
    print(f"\n  dropped {dropped} ({dropped/max(1,grand)*100:.1f}%), "
          f"kept {totals.get('kept',0)}")
    if args.report_only:
        print("  (report only — nothing written)")


if __name__ == "__main__":
    main()
