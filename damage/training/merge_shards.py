"""Fold the per-agent shard outputs into one deduped corpus, in place.

Four agents fetched disjoint Roboflow shards into merged_a0..a3, alongside the
merged640 set the original driver built. Those five directories overlap: the
shards were seeded from the same provenance, several projects are forks of one
another, and the same photograph turns up under different project names. So the
naive union is both wrong and too big for the disk it sits on.

MOVES, DOES NOT COPY. Copying would need the combined size free before anything
could be reclaimed, and the volume has ~5GB against ~10GB of sources. Each
image is renamed into the destination and its source directory removed once
absorbed, so free space grows as the merge proceeds rather than collapsing
first. A copy-then-delete design deadlocks on exactly this dataset.

DEDUPES ON THE STORED HASH. Every ingested image already carries the SHA-256 of
its ORIGINAL bytes, computed before any downscale (see ingest_roboflow_zips).
That is what makes cross-shard dedup meaningful: two projects that exported the
same photo at different sizes still agree on the hash, where comparing the
resized files would not.

IDS ARE REASSIGNED. Each source numbered its images from 1, so the five sets
collide completely on image_id. Annotations are rewritten to the new ids as
they are carried across; keeping the originals would silently attach boxes to
the wrong pictures.

    python merge_shards.py --sources DIR [DIR...] --out DIR [--keep-sources]
"""
import argparse
import json
import os
import shutil


def free_gb(p="/"):
    st = os.statvfs(p)
    return st.f_bavail * st.f_frsize / (1 << 30)


def load(src):
    p = os.path.join(src, "_annotations.coco.json")
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def image_dir(src):
    """Sources differ: the ingester writes images/, the converter writes flat."""
    d = os.path.join(src, "images")
    return d if os.path.isdir(d) else src


def merge(sources, out, keep_sources=False):
    os.makedirs(os.path.join(out, "images"), exist_ok=True)
    out_imgs = os.path.join(out, "images")

    images, anns, seen = [], [], set()
    existing = load(out)
    if existing:
        images = existing.get("images", [])
        anns = existing.get("annotations", [])
        seen = {i["sha"] for i in images if i.get("sha")}
        print(f"destination already holds {len(images):,} images")

    stats = []
    for src in sources:
        if os.path.abspath(src) == os.path.abspath(out):
            continue
        d = load(src)
        if not d:
            print(f"  {src}: no annotations, skipped")
            continue
        idir = image_dir(src)
        cats = {c["id"]: c.get("name", "") for c in d.get("categories", [])}
        by_img = {}
        for a in d.get("annotations", []):
            by_img.setdefault(a["image_id"], []).append(a)

        added = dup = missing = 0
        for im in d.get("images", []):
            sha = im.get("sha")
            src_file = os.path.join(idir, im["file_name"])
            if not os.path.exists(src_file):
                missing += 1
                continue
            if sha and sha in seen:
                dup += 1
                os.remove(src_file)          # reclaim immediately
                continue
            if sha:
                seen.add(sha)
            new_id = len(images) + 1
            dst_name = im["file_name"]
            dst = os.path.join(out_imgs, dst_name)
            if os.path.exists(dst):          # name clash, keep both
                dst_name = f"{new_id}_{dst_name}"
                dst = os.path.join(out_imgs, dst_name)
            try:
                os.rename(src_file, dst)     # MOVE — no extra space needed
            except OSError:
                shutil.move(src_file, dst)
            rec = {"id": new_id, "file_name": dst_name,
                   "width": im.get("width"), "height": im.get("height"),
                   "sha": sha, "src": im.get("src") or os.path.basename(src)}
            images.append(rec)
            for a in by_img.get(im["id"], []):
                cls = a.get("cls") or cats.get(a.get("category_id"), "")
                anns.append({"id": len(anns) + 1, "image_id": new_id,
                             "category_id": a["category_id"], "bbox": a["bbox"],
                             "area": a.get("area"), "iscrowd": 0, "cls": cls})
            added += 1
        stats.append((src, added, dup, missing))
        print(f"  {os.path.basename(src):16s} +{added:>7,} new, {dup:>7,} dup, "
              f"{missing:>5} missing  | {free_gb():.1f} GB free", flush=True)
        save(out, images, anns, d.get("categories"))
        if not keep_sources:
            shutil.rmtree(src, ignore_errors=True)

    save(out, images, anns, (existing or {}).get("categories")
         or (d.get("categories") if sources else None))
    return images, anns, stats


def save(out, images, anns, categories):
    tmp = os.path.join(out, "_annotations.coco.json.tmp")
    with open(tmp, "w") as f:
        json.dump({"images": images, "annotations": anns,
                   "categories": categories or []}, f)
    os.replace(tmp, os.path.join(out, "_annotations.coco.json"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep-sources", action="store_true")
    args = ap.parse_args()

    print(f"free before: {free_gb():.1f} GB")
    images, anns, stats = merge(args.sources, args.out, args.keep_sources)
    from collections import Counter
    print(f"\nMERGED {len(images):,} images, {len(anns):,} boxes")
    print("per class:")
    for c, n in Counter(a.get("cls") for a in anns).most_common():
        print(f"    {str(c):16s} {n:>9,}")
    print("per source:")
    for c, n in Counter(i.get("src", "?") for i in images).most_common(12):
        print(f"    {str(c)[:44]:46s} {n:>8,}")
    print(f"free after: {free_gb():.1f} GB")


if __name__ == "__main__":
    main()
