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
    # POOL EVERY SOURCE, as build_train_index and the shard upload both do.
    # Counting only the top-level file printed a corpus size that excluded the
    # very extra sources the resolve-check below was added for -- the summary
    # line said 167,157 images while the index legitimately held 169,973.
    n_img = n_ann = 0
    for dirpath, _dn, filenames in os.walk(corpus):
        if "_annotations.coco.json" not in filenames:
            continue
        with open(os.path.join(dirpath, "_annotations.coco.json")) as f:
            d = json.load(f)
        n_img += len(d["images"])
        n_ann += len(d["annotations"])

    # CHECK THE PATHS THE INDEX ACTUALLY RECORDS, not a sha against one
    # directory. The corpus stopped being a single images/ folder when CarDD
    # arrived as merged640/cardd/, and the index records its files as
    # "cardd/images/x.jpg". Testing sha-in-listdir("images") declared all 2,816
    # of them missing while the real question -- does rec["file"] resolve? --
    # was never asked. materialise_index joins rec["file"] onto the corpus
    # root, so that join is the thing to verify.
    missing, checked = 0, 0
    for ln in open(os.path.join(index, "images.jsonl")):
        rec = json.loads(ln)
        checked += 1
        if not os.path.exists(os.path.join(corpus, rec["file"])):
            missing += 1
    shas = set()
    for ln in open(os.path.join(index, "images.jsonl")):
        shas.add(json.loads(ln)["sha"])
    if missing:
        problems.append(f"{missing:,} of {checked:,} indexed images do not "
                        f"resolve under {corpus}")

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

    print(f"corpus   {n_img:,} images, {n_ann:,} boxes, "
          f"{checked - missing:,}/{checked:,} index paths resolve")
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

    # THE RESUME CHECK IS BY NAME, SO THE PLAN MUST NOT HAVE MOVED.
    # Membership is decided by packing sorted filenames into shard_mb buckets,
    # so changing shard_mb re-cuts every boundary while the NAMES stay
    # images_0000..N. Skipping "already uploaded" names then skips shards whose
    # contents are no longer what was uploaded, and the union of old-and-new
    # can omit images entirely -- a corpus quietly missing files, discovered on
    # a paid pod. Running this at 400MB against a repo sharded at 500MB
    # produced exactly that: 34 planned, 27 skipped by name, 7 uploaded, and no
    # guarantee the 167,157 images were still covered.
    #
    # A differing count is the visible symptom, so it stops here.
    prior = {f for f in existing if f.startswith("shards/images_")}
    if prior and len(prior) != len(shards):
        raise SystemExit(
            f"refusing to resume: the repo holds {len(prior)} images_*.tar "
            f"shards but this plan plans {len(shards)}. Shard membership is "
            f"decided by --shard-mb, so a different value re-cuts every "
            f"boundary while the names stay the same, and resuming by name "
            f"would skip shards whose contents have changed. Re-run with the "
            f"--shard-mb the repo was built at, or delete shards/images_*.tar "
            f"and re-upload the whole family.")

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


def upload_extra_sources(api, repo, corpus, shard_mb, scratch):
    """Shard every source BENEATH the corpus root that is not top-level images/.

    THE TWO SHARD FAMILIES, AND WHY THERE ARE TWO
    ---------------------------------------------
    The original 27 `images_NNNN.tar` shards hold BARE filenames, and train.sh
    extracts them into merged640/images/. That is 14GB already uploaded and
    re-cutting it to change the arcnames would cost hours of transfer to
    achieve nothing.

    A second source cannot join that family. CarDD lives at merged640/cardd/
    and the index records "cardd/images/x.jpg", so its files have to land at
    that path and a bare arcname cannot express it. So extra sources go up as
    `src_NNNN.tar` whose members are paths RELATIVE TO THE CORPUS ROOT, and
    train.sh extracts that family into merged640/ rather than merged640/images/.

    The rule is one line on each side and it generalises: any future source
    dropped under the corpus root ships correctly with no further changes.
    """
    import tarfile
    os.makedirs(scratch, exist_ok=True)
    existing = {f for f in api.list_repo_files(repo, repo_type="dataset")
                if f.startswith("shards/")}

    # Every image under a source directory other than the top-level images/.
    # Found by walking for annotation files, the same way build_train_index
    # discovers sources, so the two cannot disagree about what a source is.
    files = []
    for dirpath, _dirnames, filenames in os.walk(corpus):
        if "_annotations.coco.json" not in filenames:
            continue
        rel = os.path.relpath(dirpath, corpus)
        if rel == ".":
            continue                      # the images_* family already has it
        idir = os.path.join(dirpath, "images")
        if not os.path.isdir(idir):
            continue
        for fn in sorted(os.listdir(idir)):
            files.append((os.path.join(rel, "images", fn).replace(os.sep, "/"),
                          os.path.join(idir, fn)))
    files.sort()
    if not files:
        print("\nno extra sources beneath the corpus root")
        return

    budget = shard_mb * 1024 * 1024
    shards, cur, cur_bytes = [], [], 0
    for arc, path in files:
        sz = os.path.getsize(path)
        if cur and cur_bytes + sz > budget:
            shards.append(cur)
            cur, cur_bytes = [], 0
        cur.append((arc, path))
        cur_bytes += sz
    if cur:
        shards.append(cur)

    srcs = sorted({a.split("/")[0] for a, _p in files})
    print(f"\nextra sources {srcs}: {len(files):,} images -> "
          f"{len(shards)} shards of ~{shard_mb}MB")

    # THE SAME RESUME GUARD AS THE images_* FAMILY, which this originally
    # lacked. Membership here is decided by packing sorted (source, filename)
    # pairs into shard_mb buckets, so adding a SECOND extra source re-cuts
    # every boundary while the names stay src_0000..N — and resuming by name
    # then skips shards whose contents have changed, publishing a corpus
    # quietly missing images. Guarding one family and not the other was worse
    # than guarding neither, because it looked handled.
    prior = {f for f in existing if f.startswith("shards/src_")}
    if prior and len(prior) != len(shards):
        raise SystemExit(
            f"refusing to resume: the repo holds {len(prior)} src_*.tar "
            f"shards but this plan plans {len(shards)}. The extra-source set "
            f"or --shard-mb has changed, so the names no longer describe the "
            f"same contents. Delete shards/src_*.tar and re-upload the family.")

    for i, members in enumerate(shards):
        remote = f"shards/src_{i:04d}.tar"
        if remote in existing:
            print(f"  [{i+1}/{len(shards)}] {remote} already uploaded")
            continue
        local = os.path.join(scratch, os.path.basename(remote))
        with tarfile.open(local, "w") as tf:
            for arc, path in members:
                tf.add(path, arcname=arc)
        mb = os.path.getsize(local) / 1e6
        print(f"  [{i+1}/{len(shards)}] {remote}  {len(members):,} images  "
              f"{mb:.0f}MB", flush=True)
        retry_call(lambda: api.upload_file(
            path_or_fileobj=local, path_in_repo=remote,
            repo_id=repo, repo_type="dataset"), remote)
        os.remove(local)
    print(f"all {len(shards)} extra-source shards uploaded")


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
    upload_extra_sources(api, a.repo, a.corpus, a.shard_mb, a.scratch)
    print(f"\ndone: https://huggingface.co/datasets/{a.repo}")
    print(f"set CORPUS_REPO={a.repo} for train.sh")


if __name__ == "__main__":
    sys.exit(main())
