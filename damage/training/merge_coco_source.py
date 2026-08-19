"""Fold a COCO directory that already speaks the final taxonomy into the corpus.

ingest_roboflow_zips.py handles Roboflow exports, whose class names are foreign
("Rust_Corrision", "Flat Tire") and need mapping. This handles the other case:
a set already labelled in class_map.FINAL_CLASSES — cardata_damage, converted
from Supervisely — which needs no mapping but does need everything else the
corpus guarantees.

It follows ingest_roboflow_zips' four ordered steps exactly, because a merged
image that skipped one of them is a silent defect:

  1. HASH THE ORIGINAL BYTES, BEFORE ANY RESIZE. The corpus dedupes on the
     sha of the source file, so the same photo exported at two sizes still
     collides. Hashing the resized copy would defeat that on the first merge.
  2. CARRY THE CLASS NAME. Every box in the corpus has `cls`; the category id
     alone is meaningless across sources that numbered their categories
     differently.
  3. SCALE BOXES WITH THE IMAGE. A resize that forgets the annotations puts
     every box in the wrong place while the file still loads fine.
  4. DROP DEGENERATE BOXES. A zero-width box after scaling is not a label.

Images already present by sha are skipped whole — including their boxes. Two
copies of one photograph carrying two independent sets of annotations would
split the same pixels across train and valid, which is the leak this corpus was
rebuilt to remove.

    python merge_coco_source.py --src DIR --merged DIR [--dry-run]
    python merge_coco_source.py --selftest
"""
import argparse
import hashlib
import json
import os
import shutil
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import class_map as CM

# 640 IS A CEILING ON WHAT THE DETECTOR CAN EVER LEARN ABOUT SCRATCHES, and it
# is worth stating plainly here because the consequence shows up far away.
#
# A real hairline scratch is a millimetre or two on a car. In a 640px picture
# of a whole panel that is one or two pixels; in a picture of a whole car it is
# less than one. So the corpus does not contain sharp scratches at all, and no
# amount of training can recover what was never captured.
#
# Measured consequence: scratch_scuff went 0.186 -> 0.192 -> 0.205 over three
# epochs while every other class gained two to five times as much. That is not
# an under-trained class, it is a class whose evidence was thrown away before
# training started.
#
# It also explains why training at 728 was pointless — 728 is LARGER than the
# source images, so that run upscaled 640px pictures and asked the network to
# find detail upscaling cannot create — and why tiling cannot be measured on
# this corpus: a whole 640px image is a single tile, while a 4032px phone photo
# is twenty.
#
# Raising this number does nothing on its own. The sources are already ~640;
# fixing it needs higher-resolution captures, which is a data problem, not a
# training one.
MAX_SIDE = 640


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def find_coco(src):
    out = []
    for root, _d, files in os.walk(src):
        if "_annotations.coco.json" in files:
            out.append(root)
    return sorted(out)


def merge(src, merged, dry_run=False, max_side=MAX_SIDE, verbose=True):
    mp = os.path.join(merged, "_annotations.coco.json")
    with open(mp) as f:
        dst = json.load(f)
    img_dir = os.path.join(merged, "images")
    seen = {i["sha"] for i in dst["images"] if i.get("sha")}
    name_to_cid = {c["name"]: c["id"] for c in dst.get("categories", [])}
    next_img = max((i["id"] for i in dst["images"]), default=0) + 1
    next_ann = max((a["id"] for a in dst["annotations"]), default=0) + 1

    added = dup = skipped = bad_cls = degenerate = 0
    new_imgs, new_anns = [], []

    for root in find_coco(src):
        with open(os.path.join(root, "_annotations.coco.json")) as f:
            d = json.load(f)
        cats = {c["id"]: c.get("name", "") for c in d.get("categories", [])}
        by_img = {}
        for a in d.get("annotations", []):
            by_img.setdefault(a["image_id"], []).append(a)

        for im in d.get("images", []):
            p = os.path.join(root, im["file_name"])
            if not os.path.exists(p):
                skipped += 1
                continue
            sha = sha256_file(p)                       # (1) original bytes
            if sha in seen:
                dup += 1
                continue

            boxes = []
            for a in by_img.get(im["id"], []):
                cls = cats.get(a["category_id"], "")   # (2) carry the name
                if cls not in CM.FINAL_CLASSES:
                    bad_cls += 1
                    continue
                boxes.append((cls, a["bbox"]))
            if not boxes:
                skipped += 1
                continue

            try:
                with Image.open(p) as pim:
                    pim = pim.convert("RGB")
                    W, H = pim.size
                    scale = min(1.0, max_side / float(max(W, H)))
                    if scale < 1.0:
                        pim = pim.resize((max(1, int(W * scale)),
                                          max(1, int(H * scale))),
                                         Image.LANCZOS)
                    nw, nh = pim.size
                    if not dry_run:
                        pim.save(os.path.join(img_dir, sha[:20] + ".jpg"),
                                 "JPEG", quality=90)
            except Exception:
                skipped += 1
                continue

            kept = []
            for cls, bbox in boxes:
                x, y, w, h = (float(v) * scale for v in bbox)   # (3) scale
                x, y = max(0.0, x), max(0.0, y)
                w, h = min(w, nw - x), min(h, nh - y)
                if w <= 1 or h <= 1:                            # (4) degenerate
                    degenerate += 1
                    continue
                kept.append((cls, [x, y, w, h]))
            if not kept:
                skipped += 1
                if not dry_run:
                    try:
                        os.remove(os.path.join(img_dir, sha[:20] + ".jpg"))
                    except OSError:
                        pass
                continue

            seen.add(sha)
            new_imgs.append({"id": next_img, "file_name": sha[:20] + ".jpg",
                             "width": nw, "height": nh, "sha": sha,
                             "src": os.path.basename(os.path.abspath(src))})
            for cls, bb in kept:
                new_anns.append({"id": next_ann, "image_id": next_img,
                                 "category_id": name_to_cid.get(cls, 0),
                                 "cls": cls, "bbox": bb,
                                 "area": bb[2] * bb[3], "iscrowd": 0})
                next_ann += 1
            next_img += 1
            added += 1

    if verbose:
        print(f"added      {added:,} images, {len(new_anns):,} boxes")
        print(f"duplicate  {dup:,} (already in corpus by sha)")
        print(f"skipped    {skipped:,} (unreadable / no usable boxes)")
        print(f"off-taxon  {bad_cls:,} boxes with a class not in FINAL_CLASSES")
        print(f"degenerate {degenerate:,} boxes dropped after scaling")

    if dry_run:
        if verbose:
            print("\n(dry run — nothing written)")
        return added, len(new_anns)

    dst["images"].extend(new_imgs)
    dst["annotations"].extend(new_anns)
    tmp = mp + ".tmp"
    with open(tmp, "w") as f:
        json.dump(dst, f)
    os.replace(tmp, mp)
    if verbose:
        print(f"\ncorpus now {len(dst['images']):,} images, "
              f"{len(dst['annotations']):,} boxes")
    return added, len(new_anns)


# -------------------------------------------------------------- selftest ----

def _selftest():
    import tempfile
    ok = fail = 0

    def check(name, cond, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"  PASS  {name}")
        else:
            fail += 1
            print(f"  FAIL  {name}  {detail}")

    tmp = tempfile.mkdtemp(prefix="mcs_")
    merged = os.path.join(tmp, "merged")
    os.makedirs(os.path.join(merged, "images"))
    cats = [{"id": 0, "name": "_placeholder_"}]
    cats += [{"id": i + 1, "name": n}
             for i, n in enumerate(sorted(CM.FINAL_CLASSES))]
    with open(os.path.join(merged, "_annotations.coco.json"), "w") as f:
        json.dump({"images": [], "annotations": [], "categories": cats}, f)

    src = os.path.join(tmp, "src")
    os.makedirs(src)
    # 1200px so the resize path is exercised; a known box at a known place
    Image.new("RGB", (1200, 800), (90, 20, 20)).save(
        os.path.join(src, "a.jpg"), quality=95)
    Image.new("RGB", (300, 200), (20, 90, 20)).save(
        os.path.join(src, "b.jpg"), quality=95)
    with open(os.path.join(src, "_annotations.coco.json"), "w") as f:
        json.dump({
            "images": [{"id": 1, "file_name": "a.jpg", "width": 1200,
                        "height": 800},
                       {"id": 2, "file_name": "b.jpg", "width": 300,
                        "height": 200}],
            "annotations": [
                {"id": 1, "image_id": 1, "category_id": 1,
                 "bbox": [600.0, 400.0, 300.0, 200.0], "area": 60000,
                 "iscrowd": 0},
                {"id": 2, "image_id": 1, "category_id": 99,      # unknown cls
                 "bbox": [0.0, 0.0, 10.0, 10.0], "area": 100, "iscrowd": 0},
                {"id": 3, "image_id": 2, "category_id": 2,
                 "bbox": [10.0, 10.0, 50.0, 40.0], "area": 2000, "iscrowd": 0}],
            "categories": [{"id": 1, "name": sorted(CM.FINAL_CLASSES)[0]},
                           {"id": 2, "name": sorted(CM.FINAL_CLASSES)[1]},
                           {"id": 99, "name": "not_a_real_class"}]}, f)

    n_img, n_box = merge(src, merged, verbose=False)
    check(f"merged both images ({n_img})", n_img == 2, str(n_img))
    check(f"dropped the off-taxonomy box ({n_box} kept)", n_box == 2, str(n_box))

    with open(os.path.join(merged, "_annotations.coco.json")) as f:
        m = json.load(f)
    big = [i for i in m["images"] if i["width"] > 400][0]
    check(f"resized to max side {MAX_SIDE} ({big['width']}x{big['height']})",
          max(big["width"], big["height"]) == MAX_SIDE)

    # the box must scale with the image: 600/1200 of the way across, still
    ann = [a for a in m["annotations"] if a["image_id"] == big["id"]][0]
    fx = ann["bbox"][0] / big["width"]
    check(f"box scaled with the image (x at {fx:.3f} of width, want 0.500)",
          abs(fx - 0.5) < 0.01, f"{ann['bbox']}")
    check("area recomputed after scaling",
          abs(ann["area"] - ann["bbox"][2] * ann["bbox"][3]) < 1e-6)

    check("every merged box carries a cls name",
          all(a.get("cls") in CM.FINAL_CLASSES for a in m["annotations"]))
    check("every merged image carries a sha",
          all(len(i.get("sha", "")) == 64 for i in m["images"]))
    check("file names follow sha[:20].jpg",
          all(i["file_name"] == i["sha"][:20] + ".jpg" for i in m["images"]))
    check("image files exist on disk",
          all(os.path.exists(os.path.join(merged, "images", i["file_name"]))
              for i in m["images"]))
    check("ids are unique",
          len({i["id"] for i in m["images"]}) == len(m["images"])
          and len({a["id"] for a in m["annotations"]}) == len(m["annotations"]))

    # re-running must add nothing: hash dedupe, including the boxes
    n2, b2 = merge(src, merged, verbose=False)
    check(f"re-merge is a no-op ({n2} images, {b2} boxes)",
          n2 == 0 and b2 == 0)
    with open(os.path.join(merged, "_annotations.coco.json")) as f:
        m2 = json.load(f)
    check("corpus unchanged after re-merge",
          len(m2["images"]) == len(m["images"])
          and len(m2["annotations"]) == len(m["annotations"]))

    # dry run writes nothing
    before = json.dumps(m2, sort_keys=True)
    os.remove(os.path.join(src, "a.jpg"))
    Image.new("RGB", (500, 500), (7, 7, 7)).save(os.path.join(src, "a.jpg"))
    merge(src, merged, dry_run=True, verbose=False)
    with open(os.path.join(merged, "_annotations.coco.json")) as f:
        check("--dry-run writes nothing",
              json.dumps(json.load(f), sort_keys=True) == before)

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{ok} passed, {fail} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src")
    ap.add_argument("--merged")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(_selftest())
    if not a.src or not a.merged:
        ap.error("--src and --merged are required")
    merge(a.src, a.merged, a.dry_run)
