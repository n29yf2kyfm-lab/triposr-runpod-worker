"""Undo the copper-corrosion contamination in the merged corpus.

rust-detection-38s6e is a 10k corrosion set that mixes automotive rust with
copper patina, pipework and other industrial substrates. It was ingested BEFORE
OFF_MATERIAL existed, so "copper corrosion" boxes went in labelled rust_paint —
straight into the thinnest real class, which is exactly where a wrong example
does the most harm. Worse, it predates the `src` field, so those images are
anonymous in the corpus and cannot simply be selected and dropped.

The only way back is to re-fetch that one export and match on the hash. Every
merged image carries the SHA-256 of its ORIGINAL bytes, computed before any
downscale, so the export's files identify their copies exactly.

Three outcomes per matched image, and the middle one is the reason this is not
just a delete:

  ALL boxes now unmapped   -> remove the image and its boxes entirely.
  SOME boxes now unmapped  -> keep the image, drop only the offending boxes.
                              A photo of a rusty car door beside a corroded
                              pipe is still a rusty car door.
  NO boxes affected        -> leave alone.

    python fix_rust_contamination.py --merged DIR --api-key KEY [--dry-run]
"""
import argparse
import hashlib
import json
import os
import shutil
import tempfile
import zipfile

from ingest_roboflow_zips import class_for

PROJECT = "rust-detection/rust-detection-38s6e"


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def scan_export(zpath):
    """{sha: (n_total_boxes, n_still_valid)} for every image in the export."""
    out = {}
    tmp = tempfile.mkdtemp(prefix="rustfix_")
    try:
        with zipfile.ZipFile(zpath) as z:
            z.extractall(tmp)
        for root, _d, files in os.walk(tmp):
            if "_annotations.coco.json" not in files:
                continue
            with open(os.path.join(root, "_annotations.coco.json")) as f:
                d = json.load(f)
            cats = {c["id"]: c.get("name", "") for c in d.get("categories", [])}
            by_img = {}
            for a in d.get("annotations", []):
                by_img.setdefault(a["image_id"], []).append(a)
            for im in d.get("images", []):
                p = os.path.join(root, im["file_name"])
                if not os.path.exists(p):
                    continue
                anns = by_img.get(im["id"], [])
                total = len(anns)
                valid = sum(1 for a in anns
                            if class_for(cats.get(a["category_id"], "")))
                out[sha256(p)] = (total, valid)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merged", required=True)
    ap.add_argument("--api-key", required=True)
    ap.add_argument("--zip", default="/home/user/rf/_rustfix.zip")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.zip):
        import requests
        from fetch_roboflow_bulk import download_project, resolve_version
        s = requests.Session()
        s.headers.update({"User-Agent": "triposr-damage-dataset/1.0"})
        ver = resolve_version(s, PROJECT, args.api_key, 1)
        print(f"fetching {PROJECT} v{ver} ...")
        got, err = download_project(s, PROJECT, ver, args.api_key, args.zip)
        if not got:
            raise SystemExit(f"fetch failed: {err}")
    print(f"export: {os.path.getsize(args.zip)/1e6:.0f} MB")

    export = scan_export(args.zip)
    all_bad = {h for h, (t, v) in export.items() if v == 0}
    part_bad = {h for h, (t, v) in export.items() if 0 < v < t}
    print(f"export images: {len(export):,}")
    print(f"  now fully unmapped (copper/pipe/etc): {len(all_bad):,}")
    print(f"  partially affected                  : {len(part_bad):,}")

    p = os.path.join(args.merged, "_annotations.coco.json")
    with open(p) as f:
        d = json.load(f)
    imgs, anns = d["images"], d["annotations"]
    by_sha = {i.get("sha"): i for i in imgs if i.get("sha")}

    drop_ids = {by_sha[h]["id"] for h in all_bad if h in by_sha}
    matched = sum(1 for h in export if h in by_sha)
    print(f"\nmatched in corpus: {matched:,} of {len(export):,} export images")
    print(f"images to remove : {len(drop_ids):,}")

    keep_imgs = [i for i in imgs if i["id"] not in drop_ids]
    keep_anns = [a for a in anns if a["image_id"] not in drop_ids]
    removed_boxes = len(anns) - len(keep_anns)
    print(f"boxes to remove  : {removed_boxes:,}")
    print(f"\nbefore: {len(imgs):,} images, {len(anns):,} boxes")
    print(f"after : {len(keep_imgs):,} images, {len(keep_anns):,} boxes")

    if args.dry_run:
        print("\n(dry run — nothing written)")
        return

    idir = os.path.join(args.merged, "images")
    gone = 0
    for i in imgs:
        if i["id"] in drop_ids:
            try:
                os.remove(os.path.join(idir, i["file_name"]))
                gone += 1
            except OSError:
                pass
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"images": keep_imgs, "annotations": keep_anns,
                   "categories": d.get("categories", [])}, f)
    os.replace(tmp, p)
    print(f"\ndeleted {gone:,} image files; corpus rewritten")
    from collections import Counter
    for c, n in Counter(a.get("cls") for a in keep_anns).most_common():
        print(f"    {str(c):16s} {n:>9,}")


if __name__ == "__main__":
    main()
