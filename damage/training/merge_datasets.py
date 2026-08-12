"""Download many Roboflow projects, remap them onto one taxonomy, and merge.

Scaling data only helps if the labels agree. Merging projects that disagree —
one calls a region `Car-Damage`, another `dent` plus `scratch` — teaches the
model that identical pixels are different classes, and the result is worse than
training on the smaller consistent set. So every source passes through
prepare_data.CLASS_MAP, and a project whose classes mostly do not map is
skipped rather than half-imported.

Two filters that exist because raw image count is the wrong target:

  * DOMAIN. "crack detection" and "corrosion detection" projects are often
    concrete, road surface, pipework or shipping containers. Those images are
    real and well labelled and would actively damage a CAR damage model, so
    off-domain sources are excluded by default.
  * DUPLICATES. The same dataset is re-uploaded constantly (one set appeared
    eight times on HuggingFace). Images are hashed by content, so a re-upload
    contributes nothing instead of silently reweighting the training set toward
    whatever happens to be duplicated most.

Usage:
    python merge_datasets.py --manifest manifest.json --out merged --api-key KEY
"""
import argparse
import collections
import hashlib
import json
import os
import shutil
import subprocess
import zipfile

from prepare_data import CLASS_MAP, IGNORE, MIN_BOXES, PLACEHOLDER

# Substrings that mark a project as another domain wearing car-damage words.
OFF_DOMAIN = ("container", "concrete", "road", "pavement", "pipe", "weld",
              "bridge", "pisa", "robotics", "building", "wall", "asphalt")


def is_off_domain(path):
    return any(k in path.lower() for k in OFF_DOMAIN)


def fetch(path, version, api_key, dest):
    """Download one Roboflow COCO export and unzip it."""
    url = (f"https://api.roboflow.com/{path}/{version}/coco?api_key={api_key}")
    meta = json.loads(subprocess.run(["curl", "-s", url],
                                     capture_output=True, text=True).stdout)
    link = (meta.get("export") or {}).get("link")
    if not link:
        raise RuntimeError(f"no export link for {path}/{version}: "
                           f"{str(meta)[:160]}")
    zp = dest + ".zip"
    subprocess.run(["curl", "-sL", link, "-o", zp], check=True)
    with zipfile.ZipFile(zp) as z:
        z.extractall(dest)
    os.remove(zp)
    return dest


def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def merge(sources, out_dir, splits=("train", "valid", "test")):
    """Merge many COCO roots into one, remapping classes and deduping images."""
    os.makedirs(out_dir, exist_ok=True)
    counts = collections.Counter()
    seen_hashes = set()
    dupes = 0
    unmapped = collections.Counter()

    # One pass to learn which taxonomy classes clear MIN_BOXES across ALL
    # sources — a class that is rare in one project may be common overall.
    for root in sources:
        for split in splits:
            p = os.path.join(root, split, "_annotations.coco.json")
            if not os.path.exists(p):
                continue
            d = json.load(open(p))
            cats = {c["id"]: c["name"] for c in d.get("categories", [])}
            for a in d.get("annotations", []):
                name = cats.get(a["category_id"], "").strip().lower()
                if name in IGNORE:
                    continue
                t = CLASS_MAP.get(name)
                if t:
                    counts[t] += 1
                else:
                    unmapped[name] += 1

    keep = sorted(t for t, n in counts.items() if n >= MIN_BOXES)
    index = {t: i + 1 for i, t in enumerate(keep)}
    print(f"\nclasses kept ({len(keep)}): "
          + ", ".join(f"{t}={counts[t]}" for t in keep))
    dropped = {t: n for t, n in counts.items() if t not in keep}
    if dropped:
        print(f"dropped (<{MIN_BOXES}): {dropped}")
    if unmapped:
        top = dict(unmapped.most_common(12))
        print(f"unmapped source classes (not imported): {top}")

    for split in splits:
        img_dir = os.path.join(out_dir, split)
        os.makedirs(img_dir, exist_ok=True)
        images, annotations = [], []
        next_img, next_ann = 1, 1
        for root in sources:
            p = os.path.join(root, split, "_annotations.coco.json")
            if not os.path.exists(p):
                continue
            d = json.load(open(p))
            cats = {c["id"]: c["name"] for c in d.get("categories", [])}
            by_img = collections.defaultdict(list)
            for a in d.get("annotations", []):
                by_img[a["image_id"]].append(a)
            for im in d.get("images", []):
                src = os.path.join(root, split, im["file_name"])
                if not os.path.exists(src):
                    continue
                anns = by_img.get(im["id"], [])
                mapped = [a for a in anns
                          if CLASS_MAP.get(cats.get(a["category_id"], "")
                                           .strip().lower()) in index]
                if not mapped:
                    continue          # an image with no usable label is noise
                h = file_hash(src)
                if h in seen_hashes:
                    dupes += 1
                    continue
                seen_hashes.add(h)
                fn = f"{h[:16]}{os.path.splitext(im['file_name'])[1] or '.jpg'}"
                shutil.copyfile(src, os.path.join(img_dir, fn))
                images.append({**im, "id": next_img, "file_name": fn})
                for a in mapped:
                    x, y, w, hh = a["bbox"]
                    if w <= 0 or hh <= 0:
                        continue
                    t = CLASS_MAP[cats[a["category_id"]].strip().lower()]
                    annotations.append({**a, "id": next_ann,
                                        "image_id": next_img,
                                        "category_id": index[t]})
                    next_ann += 1
                next_img += 1
        cat_rows = [{"id": 0, "name": PLACEHOLDER, "supercategory": "none"}]
        cat_rows += [{"id": i, "name": t, "supercategory": "damage"}
                     for t, i in sorted(index.items(), key=lambda kv: kv[1])]
        with open(os.path.join(img_dir, "_annotations.coco.json"), "w") as f:
            json.dump({"images": images, "annotations": annotations,
                       "categories": cat_rows}, f)
        print(f"  {split:6s} images={len(images):7d} boxes={len(annotations):7d}")

    with open(os.path.join(out_dir, "labels.txt"), "w") as f:
        f.write(",".join([PLACEHOLDER] + keep))
    print(f"\nduplicate images skipped: {dupes}")
    print(f"labels.txt -> {','.join([PLACEHOLDER] + keep)}")
    return keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", default="merged")
    ap.add_argument("--api-key", default=os.environ.get("ROBOFLOW_API_KEY"))
    ap.add_argument("--work", default="_sources")
    ap.add_argument("--allow-off-domain", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    entries = json.load(open(args.manifest))
    os.makedirs(args.work, exist_ok=True)
    roots = []
    for i, e in enumerate(entries):
        if args.limit and len(roots) >= args.limit:
            break
        if not args.allow_off_domain and is_off_domain(e["path"]):
            print(f"  skip (off-domain): {e['path']}")
            continue
        dest = os.path.join(args.work, e["path"].replace("/", "__"))
        if os.path.isdir(dest):
            roots.append(dest)
            continue
        try:
            print(f"  fetching {e['path']}/{e['version']} "
                  f"({e.get('images')} images) ...")
            roots.append(fetch(e["path"], e["version"], args.api_key, dest))
        except Exception as ex:
            print(f"  ! failed {e['path']}: {type(ex).__name__}: {ex}")
    print(f"\nmerging {len(roots)} sources ...")
    merge(roots, args.out)


if __name__ == "__main__":
    main()
