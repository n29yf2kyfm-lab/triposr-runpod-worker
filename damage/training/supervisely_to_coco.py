"""Convert Supervisely polygon annotations into COCO boxes.

Found by accident, and worth recording why it was missed. This corpus was
audited earlier and written off as "images with segmentation masks" — the audit
walked masks_human/ and masks_machine/, counted the renderings as contaminated
images, and never opened ann/. In fact ann/ holds 998 + 814 Supervisely JSON
files with real polygon geometry and image dimensions, which convert to
bounding boxes exactly. Nothing needed downloading; it was already on disk.

The two folders are ALSO named backwards, which is why a glance at the names
did not help:

    "Car damages dataset/"  -> 998 images, 21 CAR PART classes (15,767 polys)
    "Car parts dataset/"    ->  814 images, 8 DAMAGE classes  ( 9,084 polys)

Both are useful, for different jobs:

  DAMAGE (--kind damage) maps onto the detector taxonomy in class_map.py:
    Scratch->scratch_scuff  Dent->dent  Cracked->crack_glass
    Paint chip/Flaking/Corrosion->rust_paint  Broken part/Missing part->structural

  PARTS (--kind parts) does not train the damage detector at all. It answers
  "WHICH PANEL is this damage on?" — the `panel` field every finding carries,
  and the anchor the 3D pin needs. A damage box plus a part box that overlaps it
  gives panel attribution without asking a VLM to guess.

A polygon's bounding box is its coordinate extremes. That is exact, not an
approximation: the tight axis-aligned box around a polygon IS the box a
detector should predict. (Contrast rotating a box, which inflates it — see the
augmentation note in balance_classes.py.)

    python supervisely_to_coco.py --root "/home/user/cardata" --kind damage \
        --out /home/user/cardata_coco
"""
import argparse
import json
import os
import shutil

# Damage classTitles -> our final detector classes (class_map.FINAL_CLASSES).
DAMAGE_MAP = {
    "scratch": "scratch_scuff",
    "dent": "dent",
    "cracked": "crack_glass",
    "crack": "crack_glass",
    "paint chip": "rust_paint",
    "flaking": "rust_paint",
    "corrosion": "rust_paint",
    "broken part": "structural",
    "missing part": "structural",
}


def polygon_bbox(points):
    """Exact axis-aligned box [x, y, w, h] around an exterior ring."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    return [float(x0), float(y0), float(x1 - x0), float(y1 - y0)]


def convert(root, kind, out_dir, min_side=4):
    """Walk <root>/*/File1/{ann,img} and emit one COCO split."""
    import glob
    ann_files = []
    for base in sorted(glob.glob(os.path.join(root, "*", "File1"))):
        ann_files += sorted(glob.glob(os.path.join(base, "ann", "*.json")))
    if not ann_files:
        raise SystemExit(f"no ann/*.json under {root}")

    images, annotations, cats = [], [], {}
    img_id = ann_id = 1
    skipped_class, degenerate, missing_img = 0, 0, 0
    os.makedirs(os.path.join(out_dir, "train"), exist_ok=True)

    for ap in ann_files:
        try:
            d = json.load(open(ap))
        except Exception:
            continue
        stem = os.path.basename(ap)[:-5]            # strip ".json" -> "X.png"
        img_path = os.path.join(os.path.dirname(os.path.dirname(ap)), "img", stem)
        if not os.path.exists(img_path):
            missing_img += 1
            continue
        size = d.get("size") or {}
        W, H = size.get("width"), size.get("height")
        rows = []
        for o in d.get("objects", []):
            if o.get("geometryType") != "polygon":
                continue
            title = str(o.get("classTitle", "")).strip()
            if kind == "damage":
                final = DAMAGE_MAP.get(title.lower())
                if not final:
                    skipped_class += 1
                    continue
            else:
                # Parts keep their own label, normalised to the panel-ish ids
                # the app already uses elsewhere (lowercase, underscores).
                final = title.lower().replace(" ", "_").replace("-", "_")
            pts = (o.get("points") or {}).get("exterior") or []
            if len(pts) < 3:
                continue
            x, y, w, h = polygon_bbox(pts)
            if w < min_side or h < min_side:
                degenerate += 1
                continue
            cats.setdefault(final, len(cats) + 1)
            rows.append((final, [round(v, 2) for v in (x, y, w, h)]))
        if not rows:
            continue
        dst = os.path.join(out_dir, "train", stem)
        shutil.copyfile(img_path, dst)
        images.append({"id": img_id, "file_name": stem, "width": W, "height": H})
        for final, bbox in rows:
            annotations.append({"id": ann_id, "image_id": img_id,
                                "category_id": cats[final], "bbox": bbox,
                                "area": round(bbox[2] * bbox[3], 2), "iscrowd": 0})
            ann_id += 1
        img_id += 1

    categories = [{"id": 0, "name": "_placeholder_", "supercategory": "none"}]
    categories += [{"id": i, "name": n, "supercategory": kind}
                   for n, i in sorted(cats.items(), key=lambda kv: kv[1])]
    with open(os.path.join(out_dir, "train", "_annotations.coco.json"), "w") as f:
        json.dump({"images": images, "annotations": annotations,
                   "categories": categories}, f)

    print(f"  kind={kind}")
    print(f"  images written   : {len(images)}")
    print(f"  boxes written    : {len(annotations)}")
    print(f"  categories       : {len(cats)}")
    for n, i in sorted(cats.items(), key=lambda kv: kv[1]):
        c = sum(1 for a in annotations if a["category_id"] == i)
        print(f"      {n:22s} {c}")
    if skipped_class:
        print(f"  skipped (unmapped class): {skipped_class}")
    if degenerate:
        print(f"  skipped (box < {min_side}px): {degenerate}")
    if missing_img:
        print(f"  skipped (image missing) : {missing_img}")
    print(f"  -> {out_dir}/train")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--kind", choices=["damage", "parts"], default="damage")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    convert(args.root, args.kind, args.out)


if __name__ == "__main__":
    main()
