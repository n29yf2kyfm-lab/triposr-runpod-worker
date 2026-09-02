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

RUNS IN BOUNDED CHUNKS. This session's container is reclaimed after a period
of inactivity, which killed the first attempt at 22,000 of 85,623 images and
lost every one of them, because that version only wrote its output at the end.
So scoring now appends to scores.jsonl as it goes and --resume skips what is
already there; --minutes stops cleanly inside a tool timeout. Nothing is ever
lost to a reclaimed container again -- at worst the images in flight.

    python3 audit_corpus.py --minutes 9        # score a chunk, resumable
    python3 audit_corpus.py --finalise         # verdicts + dedup -> csv
"""
import argparse, csv, json, os, sys, time
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import image_filters as F  # noqa: E402

MASTER = "/home/user/rf/master.csv"
REINGEST = "/home/user/rf/reingest.jsonl"
SCORES = "/home/user/rf/audit/scores.jsonl"
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
    from PIL import Image
    g = np.asarray(im.convert("L").resize((32, 32), Image.LANCZOS), dtype=np.float64)
    N = 32
    k = np.arange(N)[:, None]; n = np.arange(N)[None, :]
    D = np.cos(np.pi * (2 * n + 1) * k / (2 * N))
    d = D @ g @ D.T
    low = d[:8, :8].flatten()[1:]           # drop the DC term
    return int("".join("1" if b else "0" for b in low > np.median(low)), 2)


def one(job):
    """Keyed on the image path, NOT the sha. All 5,553 drive rows carry an
    empty sha in the master chart, so a sha-keyed result dict collapsed them
    onto one entry and handed every drive image the same scores -- which
    dropped the whole set on a grain reading that belonged to one file."""
    key, path = job
    try:
        im = F.load(path)
        return {"key": key, "grain": round(F.grain(im), 4), "edge_bar": round(F.edge_bar(im), 4),
                "seam": round(F.seam(im), 4), "phash": f"{phash(im):016x}", "err": ""}
    except Exception as e:
        return {"key": key, "grain": -1, "edge_bar": -1, "seam": -1, "phash": "0", "err": type(e).__name__}


def rows_with_project():
    src = {}
    for line in open(REINGEST):
        d = json.loads(line); src[d["sha"][:16]] = d["source"]
    rows = [r for r in csv.DictReader(open(MASTER)) if r["verdict"] == "keep"]
    for r in rows:
        r["project"] = r["dataset"] if r["dataset"] != "roboflow" else src.get(r["sha"][:16], "UNSOURCED")
        r["path"] = os.path.join(ROOT[r["dataset"]], r["image"])
    return rows


def score(a):
    rows = rows_with_project()
    done = set()
    if os.path.exists(SCORES):
        for line in open(SCORES):
            try: done.add(json.loads(line)["key"])
            except Exception: pass          # a torn last line from a hard kill
    todo = [(r["image"], r["path"]) for r in rows if r["image"] not in done]
    print(f"{len(rows):,} keep rows, {len(done):,} already scored, {len(todo):,} to go", flush=True)
    if not todo:
        print("scoring complete -- run with --finalise"); return

    deadline = time.time() + a.minutes * 60
    t0 = time.time(); n = 0
    with open(SCORES, "a") as out, Pool(a.workers) as pool:
        for s in pool.imap_unordered(one, todo, chunksize=16):
            out.write(json.dumps(s) + "\n"); n += 1
            if n % 500 == 0:
                out.flush()
                rate = n / (time.time() - t0)
                left = (len(todo) - n) / rate / 60
                print(f"  {n:,}/{len(todo):,}  {rate:.0f}/s  {left:.0f} min of scoring left", flush=True)
                if time.time() > deadline:
                    print(f"time budget reached, {len(done)+n:,} of {len(rows):,} scored; re-run to continue", flush=True)
                    pool.terminate(); break
    print(f"wrote {SCORES}")


def finalise():
    rows = rows_with_project()
    sc = {}
    for line in open(SCORES):
        try: d = json.loads(line); sc[d["key"]] = d
        except Exception: pass
    missing = [r for r in rows if r["image"] not in sc]
    if missing:
        print(f"WARNING: {len(missing):,} rows unscored; run without --finalise first")

    for r in rows:
        s = sc.get(r["image"])
        if r["project"] in DROP_PROJECTS:
            r["clean_verdict"], r["clean_reason"] = "drop_project", DROP_PROJECTS[r["project"]]
        elif s is None:
            r["clean_verdict"], r["clean_reason"] = "unscored", ""
        elif s["err"]:
            r["clean_verdict"], r["clean_reason"] = "drop_unreadable", s["err"]
        else:
            fl = F.flags(s)
            r["clean_verdict"] = "drop_" + fl[0] if fl else "keep"
            r["clean_reason"] = ",".join(fl)
        for k in ("grain", "edge_bar", "seam", "phash"):
            r[k] = s[k] if s else ""

    # perceptual duplicates among what is still kept. Bucket by the top 16
    # bits then compare within buckets -- Hamming <= 6 on 64 bits almost
    # always shares the leading bits, and it keeps this O(n) in practice.
    rank = {p: i for i, p in enumerate(CLEAN_FIRST)}
    kept = sorted((r for r in rows if r["clean_verdict"] == "keep"),
                  key=lambda r: rank.get(r["project"], len(rank)))
    buckets = {}
    for r in kept:
        h = int(r["phash"], 16); key = h >> 48
        hit = next((c for c in buckets.get(key, ()) if bin(h ^ int(c["phash"], 16)).count("1") <= 6), None)
        if hit is None:
            buckets.setdefault(key, []).append(r)
        else:
            r["clean_verdict"] = "drop_near_duplicate"
            r["clean_reason"] = f"of {hit['image']} ({hit['project']})"

    cols = ["image", "sha", "dataset", "project", "class", "split",
            "grain", "edge_bar", "seam", "phash", "clean_verdict", "clean_reason"]
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)

    from collections import Counter
    v = Counter(r["clean_verdict"] for r in rows)
    print("\nverdicts:")
    for k, n in v.most_common(): print(f"  {n:7,}  {k}")
    print("\nkept by class:")
    for k, n in Counter(r["class"] for r in rows if r["clean_verdict"] == "keep").most_common():
        print(f"  {n:7,}  {k}")
    print("\nkept / total by project:")
    tot = Counter(r["project"] for r in rows)
    kp = Counter(r["project"] for r in rows if r["clean_verdict"] == "keep")
    for p, n in tot.most_common():
        print(f"  {kp[p]:7,} / {n:7,}  {100*kp[p]/n:5.1f}%  {p}")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--minutes", type=float, default=9.0, help="stop scoring cleanly after this long")
    ap.add_argument("--finalise", action="store_true")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(SCORES), exist_ok=True)
    finalise() if a.finalise else score(a)
