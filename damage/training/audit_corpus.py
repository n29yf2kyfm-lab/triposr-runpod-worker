"""
Full-corpus clean pass: one verdict per keep row of the master chart.

Order of decisions, per image:
  1. provenance     the five projects read as junk on their contact sheets
                    (containers, augmented exports, stock scrapes) are dropped
                    outright -- see audit/project_verdicts.md
  2. image filters  grain / edge_bar / seam from image_filters.py, each
                    validated against sheets read by eye
  3. perceptual     8x8 DCT hash; near-duplicates (Hamming <= 6) across the
     duplicates     whole set collapse to one survivor, clean projects first.
                    The sha dedup missed these because noise augmentation
                    changes every pixel and stock scrapes recut the frame.

Writes audit/clean_verdicts.csv with every score so a threshold can be moved
later without recomputing, and prints the tally.

    python3 audit_corpus.py [--workers N] [--limit N]
"""
import argparse, csv, json, os, sys, time
from multiprocessing import Pool

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from image_filters import score_all, flags  # noqa: E402

MASTER = "/home/user/rf/master.csv"
REINGEST = "/home/user/rf/reingest.jsonl"
OUT = "/home/user/rf/audit/clean_verdicts.csv"
ROOT = {"roboflow": "/home/user/rf/merged640", "cardd": "/home/user/rf/merged640", "drive": "/home/user"}

DROP_PROJECTS = {
    "container-damage-ke5bc/dent-detection-4qxiu":            "shipping containers, not cars",
    "vehicle-detection-yjf3z/car-dent-scratch-detection":     "augmented export: flips, HDR, mirrored watermarks",
    "datasetyolo/broken-car-od":                              "augmented export: flips, rotations, stock",
    "curacel-ai/car-damage-detection-5ioys":                  "stock scrape: watermark bars on most frames",
    "rfvnx-dgm7e/car-damage-c1f0i-epb08":                     "stock scrape with noise aug",
}
# survivors of a duplicate group are chosen in this order
CLEAN_FIRST = ["changs-workspace-hnorg/vehicle-damage-gwmh4", "project-joggx/car-damage-assessment-8mb45",
               "damage-detection-d25qu/vehicle-damage-detection-hhxfj", "gp2-hknp7/car-damage-detection-mwbgo",
               "beena-txfr0/car-damage-detection-tuzuq", "uniud-g3oa7/scratch-detection-hnk3o",
               "haedars-workspace/scratch-segmentation-gsw1t", "cardd", "drive"]


def phash(im):
    """Classic 8x8 DCT perceptual hash, 64 bits."""
    g = np.asarray(im.convert("L").resize((32, 32), Image.LANCZOS), dtype=np.float64)
    # 2D DCT-II via the separable matrix form; no scipy dependency here
    N = 32
    k = np.arange(N)[:, None]; n = np.arange(N)[None, :]
    D = np.cos(np.pi * (2 * n + 1) * k / (2 * N))
    d = D @ g @ D.T
    low = d[:8, :8].flatten()[1:]           # drop the DC term
    bits = low > np.median(low)
    return int("".join("1" if b else "0" for b in bits), 2)


def one(job):
    path, = job
    try:
        im = Image.open(path); im.load()
        s = score_all(path)
        s["phash"] = phash(im)
        s["err"] = ""
    except Exception as e:
        s = {"grain": -1, "edge_bar": -1, "seam": -1, "phash": 0, "err": type(e).__name__}
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    src = {}
    for line in open(REINGEST):
        d = json.loads(line); src[d["sha"][:16]] = d["source"]
    rows = [r for r in csv.DictReader(open(MASTER)) if r["verdict"] == "keep"]
    if a.limit: rows = rows[:a.limit]
    for r in rows:
        r["project"] = r["dataset"] if r["dataset"] != "roboflow" else src.get(r["sha"][:16], "UNSOURCED")
        r["path"] = os.path.join(ROOT[r["dataset"]], r["image"])
    print(f"{len(rows):,} keep rows, {a.workers} workers", flush=True)

    t0 = time.time()
    scored = []
    with Pool(a.workers) as pool:
        for i, s in enumerate(pool.imap(one, [(r["path"],) for r in rows], chunksize=32)):
            scored.append(s)
            if (i + 1) % 2000 == 0:
                rate = (i + 1) / (time.time() - t0)
                print(f"  {i+1:,}/{len(rows):,}  {rate:.0f}/s  eta {(len(rows)-i-1)/rate/60:.0f} min", flush=True)

    # verdicts, stage 1 and 2
    for r, s in zip(rows, scored):
        r.update(s)
        if r["project"] in DROP_PROJECTS:
            r["clean_verdict"], r["clean_reason"] = "drop_project", DROP_PROJECTS[r["project"]]
        elif s["err"]:
            r["clean_verdict"], r["clean_reason"] = "drop_unreadable", s["err"]
        else:
            fl = flags(s)
            if fl:
                r["clean_verdict"], r["clean_reason"] = "drop_" + fl[0], ",".join(fl)
            else:
                r["clean_verdict"], r["clean_reason"] = "keep", ""

    # stage 3: perceptual duplicates among what is still kept. Bucket by the
    # top 16 bits then compare within buckets -- Hamming <= 6 on 64 bits
    # almost always shares the leading bits, and it keeps this O(n) in practice.
    rank = {p: i for i, p in enumerate(CLEAN_FIRST)}
    kept = [r for r in rows if r["clean_verdict"] == "keep"]
    kept.sort(key=lambda r: rank.get(r["project"], len(rank)))
    buckets = {}
    dups = 0
    for r in kept:
        h = r["phash"]; key = h >> 48
        hit = None
        for cand in buckets.get(key, ()):
            if bin(h ^ cand["phash"]).count("1") <= 6:
                hit = cand; break
        if hit is None:
            buckets.setdefault(key, []).append(r)
        else:
            r["clean_verdict"], r["clean_reason"] = "drop_near_duplicate", f"of {hit['image']} ({hit['project']})"
            dups += 1

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    cols = ["image", "sha", "dataset", "project", "class", "split", "grain", "edge_bar", "seam",
            "phash", "clean_verdict", "clean_reason"]
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            r["phash"] = f"{r['phash']:016x}"
            for k in ("grain", "edge_bar", "seam"):
                r[k] = f"{r[k]:.4f}"
            w.writerow(r)

    from collections import Counter
    v = Counter(r["clean_verdict"] for r in rows)
    print("\nverdicts:")
    for k, n in v.most_common():
        print(f"  {n:7,}  {k}")
    print(f"\nby class, kept:")
    c = Counter(r["class"] for r in rows if r["clean_verdict"] == "keep")
    for k, n in c.most_common():
        print(f"  {n:7,}  {k}")
    print(f"\nby project, kept / total:")
    tot = Counter(r["project"] for r in rows); kp = Counter(r["project"] for r in rows if r["clean_verdict"] == "keep")
    for p, n in tot.most_common():
        print(f"  {kp[p]:7,} / {n:7,}  {p}")
    print(f"\nwrote {OUT}  ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
