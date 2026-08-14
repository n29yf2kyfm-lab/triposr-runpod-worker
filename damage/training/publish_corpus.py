"""Upload the cleaned corpus and its index to a Hugging Face dataset repo.

The pod fetches from here instead of rebuilding. That is the whole point of
train.sh's changed data step: rebuilding on the pod threw away every correction
made to this data — the off-domain removal, the class grouping, the
near-duplicate split, the taxonomy agreement between labels.txt and the
weights — and spent the first hour of a paid GPU doing it.

WHAT GOES UP
    merged640/_annotations.coco.json   167,157 images / 375,291 boxes
    merged640/images/*.jpg             ~14GB
    idx/{index,images}.jsonl           the split-and-balance plan
    idx/{classes,plan}.json            the class vocabulary and the report

IMAGES GO UP AS TARBALLS, NOT AS 167,157 FILES.
The per-file upload stalled dead at 9,999 images with HTTP 429 on every
request: a repo with that many small objects is the wrong shape for the Hub,
which says so itself ("Consider reorganising into sub-folders"). Sharding into
~500MB tars turns 167k requests into about thirty, which no rate limiter
objects to, and moves far more bytes per second besides.

Shards are built ONE AT A TIME and deleted after upload, because there is under
4GB free here and the corpus is 14GB. Building them all first would fill the
disk before the first byte was sent.

    python publish_corpus.py --repo user/damage-corpus --token hf_xxx
    python publish_corpus.py --repo ... --token ... --dry-run
"""
import argparse
import json
import os
import sys


def preflight(corpus, index):
    """Refuse to upload a corpus whose index does not match it.

    A pod that downloads 14GB and then finds half its index pointing at absent
    files has burned the download and the GPU time before failing. Checked here,
    where it costs seconds.
    """
    problems = []
    coco = os.path.join(corpus, "_annotations.coco.json")
    if not os.path.exists(coco):
        return [f"missing {coco}"]
    with open(coco) as f:
        d = json.load(f)
    n_img, n_ann = len(d["images"]), len(d["annotations"])

    shas = set()
    for ln in open(os.path.join(index, "images.jsonl")):
        shas.add(json.loads(ln)["sha"])

    idir = os.path.join(corpus, "images")
    on_disk = set(os.listdir(idir)) if os.path.isdir(idir) else set()
    missing = sum(1 for s in shas if s[:20] + ".jpg" not in on_disk)
    if missing:
        problems.append(f"{missing:,} indexed images are not on disk")

    with open(os.path.join(index, "classes.json")) as f:
        classes = json.load(f)
    names = [r["name"] for r in classes["classes"]]
    if not names:
        problems.append("classes.json lists no classes")

    splits = {}
    for ln in open(os.path.join(index, "index.jsonl")):
        splits[json.loads(ln)["split"]] = splits.get(
            json.loads(ln)["split"], 0) + 1
    for need in ("train", "valid", "test"):
        if not splits.get(need):
            problems.append(f"index has no {need} samples")

    print(f"corpus   {n_img:,} images, {n_ann:,} boxes, {len(on_disk):,} files")
    print(f"index    {len(shas):,} originals, classes {names}")
    print(f"samples  " + ", ".join(f"{k} {v:,}" for k, v in
                                   sorted(splits.items())))
    return problems


def retry_call(fn, what, attempts=8):
    """Run fn(), waiting out the Hub's stated rate-limit window on failure.

    Applies to EVERY upload, not just the shard loop. The first sharded run
    died with the 429 traceback escaping straight out of upload_folder,
    because only the shard uploads were wrapped and the index upload — which
    runs first — was not. A retry that covers most of the calls covers none of
    the run.
    """
    import re
    import time
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as e:
            msg = str(e)
            m = re.search(r"retry this action in (\d+) minute", msg)
            m2 = re.search(r"Retry after (\d+) second", msg)
            if m:
                wait = int(m.group(1)) * 60 + 30
            elif m2:
                wait = int(m2.group(1)) + 15
            else:
                wait = min(600, 2 ** attempt * 15)
            print(f"      {what}: retry {attempt+1}/{attempts} in {wait}s "
                  f"({type(e).__name__} {msg[:90]})", flush=True)
            time.sleep(wait)
    raise SystemExit(f"gave up on {what}")


def upload_shards(api, repo, img_dir, shard_mb, scratch):
    """Tar the images into ~shard_mb pieces, uploading and deleting each.

    Resumable: shards already present in the repo are skipped, so an
    interrupted run continues rather than restarting. Names are deterministic
    (images_0000.tar) and membership follows sorted filename order, so shard N
    holds the same images on every run and "already uploaded" is meaningful.
    """
    import tarfile
    os.makedirs(scratch, exist_ok=True)
    existing = {f for f in api.list_repo_files(repo, repo_type="dataset")
                if f.startswith("shards/")}
    names = sorted(os.listdir(img_dir))
    budget = shard_mb * 1024 * 1024

    shards, cur, cur_bytes = [], [], 0
    for n in names:
        sz = os.path.getsize(os.path.join(img_dir, n))
        if cur and cur_bytes + sz > budget:
            shards.append(cur)
            cur, cur_bytes = [], 0
        cur.append(n)
        cur_bytes += sz
    if cur:
        shards.append(cur)

    print(f"\n{len(names):,} images -> {len(shards)} shards of ~{shard_mb}MB")
    for i, members in enumerate(shards):
        remote = f"shards/images_{i:04d}.tar"
        if remote in existing:
            print(f"  [{i+1}/{len(shards)}] {remote} already uploaded")
            continue
        local = os.path.join(scratch, os.path.basename(remote))
        with tarfile.open(local, "w") as tf:
            for m in members:
                tf.add(os.path.join(img_dir, m), arcname=m)
        mb = os.path.getsize(local) / 1e6
        print(f"  [{i+1}/{len(shards)}] {remote}  {len(members):,} images  "
              f"{mb:.0f}MB", flush=True)
        retry_call(lambda: api.upload_file(
            path_or_fileobj=local, path_in_repo=remote,
            repo_id=repo, repo_type="dataset"), remote)
        os.remove(local)          # under 4GB free: never hold two shards
    print(f"\nall {len(shards)} shards uploaded")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="/home/user/rf/merged640")
    ap.add_argument("--index", default="/home/user/rf/idx")
    ap.add_argument("--repo", required=True, help="e.g. user/damage-corpus")
    ap.add_argument("--token", default=os.environ.get("HF_TOKEN"))
    ap.add_argument("--private", action="store_true", default=True)
    ap.add_argument("--shard-mb", type=int, default=500,
                    help="approximate size of each tar shard")
    ap.add_argument("--scratch", default="/home/user/rf/_shards")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    problems = preflight(a.corpus, a.index)
    if problems:
        print("\nPREFLIGHT FAILED:")
        for p in problems:
            print("  ! " + p)
        raise SystemExit(2)
    print("\npreflight OK")

    if a.dry_run:
        print("(dry run — nothing uploaded)")
        return
    if not a.token:
        raise SystemExit("no token: pass --token or set HF_TOKEN")

    from huggingface_hub import HfApi
    api = HfApi(token=a.token)
    api.create_repo(a.repo, repo_type="dataset", private=a.private,
                    exist_ok=True)

    # Staged separately so the small, frequently-rebuilt index can be
    # refreshed without re-sending 14GB of pixels.
    print(f"\nuploading index -> {a.repo}:idx/")
    retry_call(lambda: api.upload_folder(
        folder_path=a.index, path_in_repo="idx",
        repo_id=a.repo, repo_type="dataset"), "idx/")
    retry_call(lambda: api.upload_file(
        path_or_fileobj=os.path.join(a.corpus, "_annotations.coco.json"),
        path_in_repo="merged640/_annotations.coco.json",
        repo_id=a.repo, repo_type="dataset"), "_annotations.coco.json")

    upload_shards(api, a.repo, os.path.join(a.corpus, "images"),
                  a.shard_mb, a.scratch)
    print(f"\ndone: https://huggingface.co/datasets/{a.repo}")
    print(f"set CORPUS_REPO={a.repo} for train.sh")


if __name__ == "__main__":
    sys.exit(main())
