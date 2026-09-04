"""Re-attach dropped annotations to images the corpus already holds.

THE SITUATION

Two audits found the same shape of loss twice. 24 class strings across the 41
manifest projects, then 78 across 13 projects that manifest.json never
recorded, mapped to nothing and were deleted at merge -- while the images
themselves stayed, because each happened to carry one box that did map. The
corpus therefore contains roughly 170,000 photographs carrying a fraction of
the labels that were downloaded with them.

Re-running the whole merge would mean re-downloading ~195,000 images into
about 700 MB of free disk. It is also unnecessary: the pixels are already
here. What is missing is the mapping from image to box, and that lives in each
project's _annotations.coco.json, a file measured in megabytes.

SO THIS DOWNLOADS EACH PROJECT, KEEPS ONLY THE ANNOTATIONS, AND DELETES THE
IMAGES IMMEDIATELY -- after hashing them, because the hash is the join. A
Roboflow export renames every file, so the only stable identity between the
export and the corpus is the content sha256, which is exactly what the corpus
is keyed on.

Peak disk is one project's zip plus its extraction, and the guard checks free
space between the two rather than only before, which is how an earlier attempt
ran the volume to zero mid-unzip.

OUTPUT is a jsonl of {sha, boxes, source} that build_train_index can merge.
Nothing is overwritten: an image that gains boxes keeps the ones it had.
"""
import argparse
import collections
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import prepare_data as PD                      # noqa: E402

# Extraction needs room for the zip AND the tree it unpacks to, on the same
# filesystem. 1.6x the zip plus a floor, checked BETWEEN download and unzip.
DISK_FLOOR_MB = 200


def sha_of(path, buf=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(buf)
            if not b:
                return h.hexdigest()
            h.update(b)


def free_mb():
    return shutil.disk_usage("/").free / 1e6


def export_link(path, version, api_key, tries=6, wait=20):
    """Roboflow generates exports lazily; a missing link is retried, an
    explicit error is not."""
    import time
    url = f"https://api.roboflow.com/{path}/{version}/coco?api_key={api_key}"
    for attempt in range(tries):
        meta = json.loads(subprocess.run(["curl", "-s", url],
                                         capture_output=True, text=True).stdout)
        if meta.get("error"):
            raise RuntimeError(str(meta["error"])[:120])
        link = (meta.get("export") or {}).get("link")
        if link:
            return link
        if attempt < tries - 1:
            time.sleep(wait)
    raise RuntimeError("no export link")


def harvest(path, version, api_key, corpus_shas, workdir):
    """-> (rows, stats). Downloads, hashes, maps, then deletes the pixels."""
    dest = os.path.join(workdir, path.replace("/", "__"))
    zp = dest + ".zip"
    link = export_link(path, version, api_key)

    # SIZE THE DOWNLOAD BEFORE STARTING IT.
    #
    # Checking free space after curl returns is too late: the download itself
    # is what fills the volume. A first run took the disk to zero on its very
    # first project, a 10,931-image export, and every project after it failed
    # with the same error for the same reason. Ask for Content-Length first
    # and refuse the whole job if the zip plus its extraction will not fit.
    head = subprocess.run(["curl", "-sIL", link], capture_output=True,
                          text=True, timeout=120).stdout
    zmb = 0.0
    for ln in head.splitlines():
        if ln.lower().startswith("content-length:"):
            zmb = max(zmb, int(ln.split(":", 1)[1].strip()) / 1e6)
    need = zmb * 2.6 + DISK_FLOOR_MB          # zip + extracted tree + slack
    if zmb and free_mb() < need:
        raise RuntimeError(f"zip {zmb:.0f}MB needs ~{need:.0f}MB, "
                           f"have {free_mb():.0f}MB")
    try:
        subprocess.run(["curl", "-sL", link, "-o", zp], check=True, timeout=1800)
    except Exception:
        if os.path.exists(zp):
            os.remove(zp)                     # never leave a partial zip behind
        raise
    zmb = os.path.getsize(zp) / 1e6
    if free_mb() < zmb * 1.6 + DISK_FLOOR_MB:
        os.remove(zp)
        raise RuntimeError(f"extract needs ~{zmb*1.6+DISK_FLOOR_MB:.0f}MB, "
                           f"have {free_mb():.0f}MB")
    try:
        with zipfile.ZipFile(zp) as z:
            z.extractall(dest)
    finally:
        os.remove(zp)

    rows = []
    st = collections.Counter()
    try:
        for ann in glob.glob(os.path.join(dest, "*", "_annotations.coco.json")):
            split_dir = os.path.dirname(ann)
            doc = json.load(open(ann))
            cats = {c["id"]: c["name"] for c in doc.get("categories", [])}
            by_img = collections.defaultdict(list)
            for a in doc.get("annotations", []):
                name = cats.get(a["category_id"], "")
                low = name.strip().lower()
                if low in PD.IGNORE:
                    st["ignored"] += 1
                    continue
                t = PD.CLASS_MAP.get(low)
                if not t:
                    st["unmapped"] += 1
                    continue
                by_img[a["image_id"]].append((t, list(a["bbox"])))
            for im in doc.get("images", []):
                st["images_seen"] += 1
                boxes = by_img.get(im["id"])
                if not boxes:
                    continue
                fp = os.path.join(split_dir, im["file_name"])
                if not os.path.exists(fp):
                    st["file_missing"] += 1
                    continue
                sha = sha_of(fp)
                if sha not in corpus_shas:
                    st["not_in_corpus"] += 1
                    continue
                st["matched"] += 1
                st["boxes"] += len(boxes)
                rows.append({"sha": sha, "source": path,
                             "width": im.get("width"), "height": im.get("height"),
                             "boxes": [{"cls": t, "bbox": b} for t, b in boxes]})
    finally:
        shutil.rmtree(dest, ignore_errors=True)
    return rows, st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", required=True)
    ap.add_argument("--index", default="/home/user/rf/idx16")
    ap.add_argument("--out", required=True)
    ap.add_argument("--workdir", default="/home/user/rf/_reingest")
    ap.add_argument("--only", help="comma-separated project paths")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()

    corpus = {json.loads(l)["sha"]
              for l in open(os.path.join(a.index, "images.jsonl"))}
    print(f"corpus: {len(corpus):,} shas")

    jobs = []
    for e in json.load(open(os.path.join(HERE, "manifest.json"))):
        jobs.append((e["path"], str(e.get("version", 1))))
    pj = "/home/user/rf/bulk/provenance.jsonl"
    if os.path.exists(pj):
        seen = {p for p, _ in jobs}
        for line in open(pj):
            r = json.loads(line)
            if r["path"] not in seen:
                jobs.append((r["path"], str(r.get("version", 1))))
    if a.only:
        want = set(a.only.split(","))
        jobs = [j for j in jobs if j[0] in want]
    if a.limit:
        jobs = jobs[:a.limit]
    print(f"{len(jobs)} projects to harvest\n")

    os.makedirs(a.workdir, exist_ok=True)
    done = set()
    if os.path.exists(a.out):
        for line in open(a.out):
            done.add(json.loads(line)["source"])
        print(f"resuming: {len(done)} projects already harvested")

    total = collections.Counter()
    with open(a.out, "a") as f:
        for i, (path, ver) in enumerate(jobs, 1):
            if path in done:
                continue
            print(f"[{i}/{len(jobs)}] {path}  (free {free_mb():.0f}MB)",
                  flush=True)
            try:
                rows, st = harvest(path, ver, a.api_key, corpus, a.workdir)
            except Exception as e:
                print(f"    SKIP {type(e).__name__}: {str(e)[:90]}", flush=True)
                continue
            for r in rows:
                f.write(json.dumps(r) + "\n")
            f.flush()
            total.update(st)
            print(f"    matched {st['matched']:,} imgs, {st['boxes']:,} boxes; "
                  f"unmapped {st['unmapped']:,}, "
                  f"not in corpus {st['not_in_corpus']:,}", flush=True)

    print(f"\nTOTAL matched {total['matched']:,} images, "
          f"{total['boxes']:,} boxes")
    print(f"      unmapped {total['unmapped']:,}, "
          f"not in corpus {total['not_in_corpus']:,}")


if __name__ == "__main__":
    main()
