"""Build a class-balanced training corpus from the merged sources.

Targets a TOTAL image budget spread evenly across the final classes — 200,000
across five classes is 40,000 each — filling each class from its real images
first and making up the rest with augmentation.

THE ORDER OF OPERATIONS IS THE WHOLE POINT: split first, augment second.

Augmenting before splitting is the single easiest way to build a dataset that
reports a wonderful score and has learned nothing. Twelve augmented copies of
one photograph are near-identical; if the split is drawn afterwards, copies of
the same source land in train AND in validation, so the model is validated
against pictures it memorised. That is exactly the failure this corpus already
suffered once — 26.6% of it had annotation boxes burned into the pixels, the
leak was present in the validation split too, and the resulting 0.4390 mAP
confirmed its own contamination. A second, self-inflicted version of the same
mistake is not worth making.

So:
  1. dedupe by SHA-256 across every source
  2. split ORIGINALS per class, 80/10/10
  3. augment ONLY the train split, up to the per-class target
  4. leave valid and test as real images, never augmented, never topped up

Validation and test therefore stay small and honest. An unbalanced validation
set is fine — it measures the world. A balanced, augmented one measures itself.

AUGMENTATIONS ARE BOX-SAFE BY CONSTRUCTION. Horizontal flip, crop-and-resize,
and photometric jitter (brightness, contrast, saturation, mild blur, mild
noise) all have exact box transforms. Free rotation does not: rotating a box
requires re-fitting an axis-aligned rectangle around it, which inflates every
box a little and, applied twelve times to reach a target, teaches the model
that damage regions are systematically larger than they are. It is excluded
deliberately rather than overlooked.

    python balance_classes.py --drive /home/user/drive_images \\
        --coco /home/user/rf/damage_ocr --out /home/user/balanced \\
        --target-total 200000
"""
import argparse
import hashlib
import json
import os
import random
import shutil

import class_map as CM

SPLITS = (("train", 0.80), ("valid", 0.10), ("test", 0.10))
EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def ingest_drive(root):
    """[{path, final, subclass, source, boxes}] from a class-per-folder tree."""
    items, skipped = [], {}
    if not root or not os.path.isdir(root):
        return items, skipped
    for folder in sorted(os.listdir(root)):
        d = os.path.join(root, folder)
        if not os.path.isdir(d):
            continue
        final = CM.from_drive(folder)
        if not final:
            skipped[folder] = len(
                [f for f in os.listdir(d) if f.lower().endswith(EXTS)])
            continue
        for fn in sorted(os.listdir(d)):
            if fn.lower().endswith(EXTS):
                items.append({"path": os.path.join(d, fn), "final": final,
                              "subclass": folder, "source": "drive",
                              "boxes": None})
    return items, skipped


def ingest_coco(root, splits=("train", "valid", "test")):
    """[{...}] from a COCO tree, carrying boxes across.

    Boxes are kept in COCO [x, y, w, h] absolute pixels; the augmenter converts
    as needed. An image contributes once, with every box it owns, and its final
    class is the class of its most common box — a photo is filed under what it
    mostly shows rather than duplicated into several classes, which would put
    the same pixels in more than one balanced bucket.
    """
    items = []
    if not root or not os.path.isdir(root):
        return items
    for split in splits:
        ann = os.path.join(root, split, "_annotations.coco.json")
        if not os.path.exists(ann):
            continue
        with open(ann) as f:
            d = json.load(f)
        cats = {c["id"]: c["name"] for c in d.get("categories", [])}
        by_img = {}
        for a in d.get("annotations", []):
            by_img.setdefault(a["image_id"], []).append(a)
        for im in d.get("images", []):
            anns = by_img.get(im["id"], [])
            finals = [CM.from_roboflow(cats.get(a["category_id"], "")) for a in anns]
            finals = [f for f in finals if f]
            if not finals:
                continue
            # sorted(), not set(): iterating a set of strings follows Python's
            # per-process randomised string hashing, so a tie between two
            # classes resolved as "dent" in one run and "scratch_scuff" in the
            # next. That silently reshuffles which class an image is filed
            # under, and therefore the train/valid/test split, between runs of
            # the same command. Verified by running the same tie six times and
            # getting both answers back.
            dominant = max(sorted(set(finals)), key=finals.count)
            boxes = [{"bbox": a["bbox"],
                      "final": CM.from_roboflow(cats.get(a["category_id"], ""))}
                     for a in anns
                     if CM.from_roboflow(cats.get(a["category_id"], ""))]
            items.append({"path": os.path.join(root, split, im["file_name"]),
                          "final": dominant, "subclass": f"rf_{split}",
                          "source": "roboflow", "boxes": boxes})
    return items


def dedupe(items):
    """Drop exact duplicates across sources. The two corpora overlap in origin
    (both scrape the same public photos), so this is not theoretical."""
    seen, out, dropped = set(), [], 0
    for it in items:
        try:
            h = sha256(it["path"])
        except OSError:
            continue
        if h in seen:
            dropped += 1
            continue
        seen.add(h)
        it["sha"] = h
        out.append(it)
    return out, dropped


def split_items(items, rng):
    """Per-class 80/10/10 on ORIGINALS. Returns {split: [item]}."""
    by_class = {}
    for it in items:
        by_class.setdefault(it["final"], []).append(it)
    out = {s: [] for s, _ in SPLITS}
    for cls, rows in by_class.items():
        rows = sorted(rows, key=lambda r: r["sha"])   # deterministic
        rng.shuffle(rows)
        n = len(rows)
        n_tr = int(n * 0.80)
        n_va = int(n * 0.10)
        out["train"].extend(rows[:n_tr])
        out["valid"].extend(rows[n_tr:n_tr + n_va])
        out["test"].extend(rows[n_tr + n_va:])
    return out


# --- augmentation ---------------------------------------------------------

def _aug_variant(img, boxes, k, rng):
    """Apply variant k. Returns (image, boxes). Every op has an exact box map."""
    from PIL import Image, ImageEnhance, ImageFilter
    W, H = img.size
    b = [dict(x) for x in (boxes or [])]

    if k % 2 == 1:                                     # horizontal flip
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
        for x in b:
            bx = x["bbox"]
            x["bbox"] = [W - bx[0] - bx[2], bx[1], bx[2], bx[3]]

    mode = (k // 2) % 4
    if mode == 1:                                      # crop and resize back
        f = rng.uniform(0.80, 0.95)
        cw, ch = int(W * f), int(H * f)
        x0 = rng.randint(0, W - cw); y0 = rng.randint(0, H - ch)
        img = img.crop((x0, y0, x0 + cw, y0 + ch)).resize((W, H), Image.BILINEAR)
        sx, sy = W / cw, H / ch
        nb = []
        for x in b:
            bx0, by0, bw, bh = x["bbox"]
            nx0 = (bx0 - x0) * sx; ny0 = (by0 - y0) * sy
            nx1 = (bx0 + bw - x0) * sx; ny1 = (by0 + bh - y0) * sy
            nx0, ny0 = max(0, nx0), max(0, ny0)
            nx1, ny1 = min(W, nx1), min(H, ny1)
            if nx1 - nx0 > 4 and ny1 - ny0 > 4:        # survived the crop
                x["bbox"] = [nx0, ny0, nx1 - nx0, ny1 - ny0]
                nb.append(x)
        b = nb
    elif mode == 2:                                    # photometric
        img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.75, 1.30))
        img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.75, 1.30))
        img = ImageEnhance.Color(img).enhance(rng.uniform(0.60, 1.35))
    elif mode == 3:                                    # soften / sharpen
        if rng.random() < 0.5:
            img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.4, 1.2)))
        else:
            img = ImageEnhance.Sharpness(img).enhance(rng.uniform(1.4, 2.2))
    return img, b


def augment_to_target(rows, target, out_dir, rng, quality=88):
    """Write `target` images for one class into out_dir. Returns (real, aug).

    Real images are written first and unmodified. The shortfall is filled by
    cycling variants over the real pool, so every original is used once before
    any is used twice and the copies are spread evenly rather than piling onto
    whichever image happens to sort first.
    """
    from PIL import Image
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for it in rows[:target]:
        dst = os.path.join(out_dir, f"{it['sha'][:16]}{os.path.splitext(it['path'])[1].lower()}")
        try:
            shutil.copyfile(it["path"], dst)
            with Image.open(dst) as im:
                w, h = im.size
        except Exception:
            continue
        written.append({**it, "out": os.path.basename(dst), "aug": 0,
                        "width": w, "height": h})
    real = len(written)
    if real == 0 or real >= target:
        return written, real, 0

    # Sources that cannot be opened are retired permanently. The previous
    # version incremented the variant counter and `continue`d WITHOUT
    # incrementing `made`, so `rows[made % real]` selected the same broken file
    # on every iteration and the loop never terminated — a single corrupt JPEG
    # in a class hung the whole build. Confirmed by feeding it one unreadable
    # file and watching it spin until killed.
    usable = list(rows)
    bad = set()
    made = 0
    k = 1
    guard = 0
    max_guard = target * 4 + 64        # cannot spin longer than the work needed
    while real + made < target and usable and guard < max_guard:
        guard += 1
        src = usable[made % len(usable)]
        try:
            with Image.open(src["path"]) as im:
                im = im.convert("RGB")
                img, boxes = _aug_variant(im, src.get("boxes"), k, rng)
                name = f"{src['sha'][:16]}_a{k:03d}.jpg"
                img.save(os.path.join(out_dir, name), quality=quality)
        except Exception:
            bad.add(src["sha"])
            usable = [r for r in usable if r["sha"] not in bad]
            continue
        # Every variant preserves the frame size (flip, crop-and-resize-back
        # and photometric all end at W x H), so the source dimensions are the
        # output dimensions and the boxes stay in the same coordinate space.
        written.append({**src, "out": name, "aug": k, "boxes": boxes,
                        "width": img.size[0], "height": img.size[1]})
        made += 1
        if usable and made % len(usable) == 0:
            k += 1                                     # next variant sweep
    if bad:
        print(f"      skipped {len(bad)} unreadable source image(s)")
    if real + made < target:
        print(f"      SHORT: wrote {real+made} of {target} "
              f"({'no usable sources' if not usable else 'guard tripped'})")
    return written, real, made


def write_coco(manifest, out_root):
    """Emit _annotations.coco.json per split, next to the images.

    Without this the balancer produced class folders and a manifest and nothing
    a detector could read — the boxes existed only as a JSON field nobody
    consumes. RF-DETR and every COCO loader want this file beside the images.

    Category ids follow class_map.class_index(), which starts real classes at 1
    and reserves 0 as the placeholder, matching prepare_data.py so the two
    pipelines cannot disagree about what category 1 means.

    Images live in <split>/<class>/, so file_name carries that relative path;
    a loader pointed at <split>/ resolves it without flattening the tree.
    """
    idx = CM.class_index()
    for split in ("train", "valid", "test"):
        rows = [m for m in manifest if m.get("split") == split]
        if not rows:
            continue
        images, annotations = [], []
        img_id = ann_id = 1
        for m in rows:
            images.append({"id": img_id,
                           "file_name": f"{m['class']}/{m['out']}",
                           "width": m.get("width"), "height": m.get("height")})
            for b in (m.get("boxes") or []):
                cat = idx.get(b.get("final"))
                if not cat:
                    continue
                x, y, w, h = b["bbox"]
                annotations.append({"id": ann_id, "image_id": img_id,
                                    "category_id": cat,
                                    "bbox": [round(float(v), 2) for v in (x, y, w, h)],
                                    "area": round(float(w) * float(h), 2),
                                    "iscrowd": 0})
                ann_id += 1
            img_id += 1
        cats = [{"id": 0, "name": "_placeholder_", "supercategory": "none"}]
        cats += [{"id": i, "name": c, "supercategory": CM.canonical(c)}
                 for c, i in sorted(idx.items(), key=lambda kv: kv[1])]
        path = os.path.join(out_root, split, "_annotations.coco.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"images": images, "annotations": annotations,
                       "categories": cats}, f)
        print(f"  {split}/_annotations.coco.json: {len(images)} images, "
              f"{len(annotations)} boxes")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drive", default=None, help="class-per-folder tree")
    ap.add_argument("--coco", default=None, help="cleaned COCO tree")
    ap.add_argument("--out", required=True)
    ap.add_argument("--target-total", type=int, default=200000)
    ap.add_argument("--max-aug", type=float, default=0.0,
                    help="cap augmentation multiplier (0 = uncapped)")
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--task", choices=["detect", "classify"], default="detect",
                    help="detect needs boxes on every image; classify does not")
    ap.add_argument("--allow-unboxed", action="store_true",
                    help="for --task detect: keep images that have no boxes. "
                         "Almost never right — see the guard below.")
    args = ap.parse_args()
    rng = random.Random(args.seed)

    print(CM.summary())
    items, skipped = ingest_drive(args.drive)
    items += ingest_coco(args.coco)
    print(f"\ningested {len(items)} labelled images")
    if skipped:
        print("  not trained (negatives / parked):")
        for k, v in sorted(skipped.items(), key=lambda kv: -kv[1]):
            print(f"    {k:22s} {v}")

    # A DETECTOR CANNOT LEARN FROM AN IMAGE WITH NO BOXES — it learns the
    # opposite of what the folder says. An unannotated photo of a dented door
    # is not "a dent example" to a detector, it is a full frame of BACKGROUND,
    # and every pixel of visible damage in it becomes a negative. The Drive
    # corpus is 100% box-less (22,195 of 22,195), so quietly mixing it in would
    # make ~62% of the training set actively teach the model that damage is
    # nothing. It must be pseudo-labelled first; until then this refuses.
    unboxed = [i for i in items if not i.get("boxes")]
    if args.task == "detect" and unboxed and not args.allow_unboxed:
        by_src = {}
        for i in unboxed:
            by_src[i["source"]] = by_src.get(i["source"], 0) + 1
        print(f"\n  REFUSING {len(unboxed)} images with no bounding boxes "
              f"({len(unboxed)/max(1,len(items))*100:.0f}% of the corpus): {by_src}")
        print("  A detector trained on these learns that visible damage is "
              "background.\n  Pseudo-label them first (see --task classify to "
              "build a classifier instead,\n  or --allow-unboxed if you really "
              "mean it).")
        items = [i for i in items if i.get("boxes")]
        print(f"  continuing with {len(items)} boxed images")

    items, dupes = dedupe(items)
    print(f"  deduped: dropped {dupes}, kept {len(items)}")

    parts = split_items(items, rng)
    classes = sorted(CM.FINAL_CLASSES)
    per_class = args.target_total // max(1, len(classes))
    print(f"\ntarget {args.target_total} total / {len(classes)} classes "
          f"= {per_class} per class (train split carries the target; "
          f"valid+test stay real)")

    print(f"\n{'class':<16}{'real tr':>9}{'target':>9}{'aug x':>8}{'valid':>8}{'test':>7}")
    plan = {}
    for c in classes:
        tr = [i for i in parts["train"] if i["final"] == c]
        va = [i for i in parts["valid"] if i["final"] == c]
        te = [i for i in parts["test"] if i["final"] == c]
        mult = per_class / len(tr) if tr else 0
        if args.max_aug and mult > args.max_aug:
            mult = args.max_aug
        goal = int(len(tr) * mult) if tr else 0
        plan[c] = (tr, va, te, goal)
        flag = "  <-- thin" if mult > 15 else ""
        print(f"{c:<16}{len(tr):>9}{goal:>9}{mult:>7.1f}x{len(va):>8}{len(te):>7}{flag}")
    total = sum(p[3] for p in plan.values()) + \
        sum(len(p[1]) + len(p[2]) for p in plan.values())
    print(f"{'TOTAL':<16}{sum(len(p[0]) for p in plan.values()):>9}"
          f"{sum(p[3] for p in plan.values()):>9}")
    print(f"\nprojected dataset: {total} images "
          f"({sum(len(p[0])+len(p[1])+len(p[2]) for p in plan.values())} real, "
          f"{sum(p[3] for p in plan.values())-sum(len(p[0]) for p in plan.values())} augmented)")
    if args.report_only:
        print("\n(report only — nothing written)")
        return

    manifest = []
    for c in classes:
        tr, va, te, goal = plan[c]
        rows, real, made = augment_to_target(
            tr, goal, os.path.join(args.out, "train", c), rng)
        manifest += [{**r, "split": "train", "class": c} for r in rows]
        print(f"  train/{c}: {real} real + {made} augmented")
        for sp, rowset in (("valid", va), ("test", te)):
            d = os.path.join(args.out, sp, c)
            os.makedirs(d, exist_ok=True)
            for it in rowset:
                dst = os.path.join(d, f"{it['sha'][:16]}"
                                      f"{os.path.splitext(it['path'])[1].lower()}")
                try:
                    shutil.copyfile(it["path"], dst)
                    from PIL import Image as _I
                    with _I.open(dst) as im:
                        w, h = im.size
                except Exception:
                    continue
                manifest.append({**it, "out": os.path.basename(dst), "aug": 0,
                                 "split": sp, "class": c,
                                 "width": w, "height": h})
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "manifest.jsonl"), "w") as f:
        for m in manifest:
            f.write(json.dumps({k: v for k, v in m.items() if k != "path"}) + "\n")
    with open(os.path.join(args.out, "classes.json"), "w") as f:
        json.dump({"classes": CM.class_index(),
                   "colours": {c: CM.colour(c) for c in classes},
                   "canonical": {c: CM.canonical(c) for c in classes}}, f, indent=2)
    if args.task == "detect":
        write_coco(manifest, args.out)
    print(f"\nwrote {len(manifest)} images -> {args.out}")


if __name__ == "__main__":
    main()
