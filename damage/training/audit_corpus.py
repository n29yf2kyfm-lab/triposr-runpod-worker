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
DEDUP_RADIUS = 8      # Hamming, on the 63-bit phash; see the dedup block for why 8

# Whole-project drops. A council review re-examined all five original entries:
#   container-damage  -- 25/25 random frames are shipping containers. Certain.
#   yjf3z             -- kept, but for the decisive reason the first pass
#                        missed: 77% of it is black-letterboxed, which zeroes
#                        edge_bar's text term, so per-image filtering is
#                        structurally blind to this project (99% would pass).
#   curacel           -- 70% any-flag rate, median grain 4.5. Corroborated.
#   datasetyolo       -- REMOVED from this list. Its measured flag rate is
#                        4.0%, cleaner than four kept projects, and the 20-image
#                        sheet (5 bad) has P=0.95 of looking that bad from a
#                        60%-good project. Dropping it cost 38% of lamp_wheel.
#   rfvnx             -- REMOVED. 8/20 bad is the same reading four kept
#                        projects got. 79% passes the per-image filters.
#   drive             -- ADDED. 5,553 rows, median grain 4.71, uniformly noise
#                        augmented with stock marks; it was never given a
#                        verdict in the first pass and grain merely skimmed it.
DROP_PROJECTS = {
    "container-damage-ke5bc/dent-detection-4qxiu":            "shipping containers, not cars",
    "vehicle-detection-yjf3z/car-dent-scratch-detection":     "77% letterboxed: edge_bar is blind to it; flips, HDR, watermarks",
    "curacel-ai/car-damage-detection-5ioys":                  "stock scrape with noise aug: 70% flag rate",
    "drive":                                                  "noise-augmented stock scrape: median grain 4.71",
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


def _white_one(job):
    key, path = job
    try:
        return key, round(F.whiteness(F.load(path)), 4)
    except Exception:
        return key, None


def whiteness_pass(a):
    """Add a 'white' score to every grain-flagged row that lacks one, and
    rewrite scores.jsonl atomically. Only grain-flagged rows need it: the gate
    can only rescue an image that grain would otherwise drop."""
    rows = {r["image"]: r for r in rows_with_project()}
    recs = [json.loads(l) for l in open(SCORES)]
    todo = [(d["key"], rows[d["key"]]["path"]) for d in recs
            if d.get("white") is None and not d["err"] and d["grain"] >= F.FLAGS["grain"] and d["key"] in rows]
    print(f"{len(recs):,} scored rows, {len(todo):,} grain-flagged rows need a whiteness score", flush=True)
    white = {}
    if todo:
        with Pool(a.workers) as pool:
            for key, w in pool.imap_unordered(_white_one, todo, chunksize=32):
                white[key] = w
    for d in recs:
        if d["key"] in white:
            d["white"] = white[d["key"]]
    with open(SCORES + ".tmp", "w") as fh:
        for d in recs: fh.write(json.dumps(d) + "\n")
    os.replace(SCORES + ".tmp", SCORES)
    have = sum(1 for d in recs if d.get("white") is not None)
    print(f"wrote {SCORES}: {have:,} rows carry a whiteness score")


def rows_with_project():
    """reingest.jsonl has 101,365 rows for 85,717 images: 6,760 images were
    exported by more than one Roboflow project. An earlier version kept one
    source per image -- whichever line came LAST -- which made 2,276 drop
    decisions depend on file order and hid three projects (~20,000 rows)
    from the audit entirely. Now every source is kept: an image is dropped if
    ANY of its sources is a drop project, and "project" (for reporting and
    for which duplicate survives) is its best-ranked source."""
    src = {}
    for line in open(REINGEST):
        d = json.loads(line); src.setdefault(d["sha"][:16], set()).add(d["source"])
    rank = {p: i for i, p in enumerate(CLEAN_FIRST)}
    rows = [r for r in csv.DictReader(open(MASTER)) if r["verdict"] == "keep"]
    for r in rows:
        ps = src.get(r["sha"][:16], {"UNSOURCED"}) if r["dataset"] == "roboflow" else {r["dataset"]}
        r["projects"] = sorted(ps)
        r["project"] = min(ps, key=lambda p: (rank.get(p, len(rank)), p))
        r["path"] = os.path.join(ROOT[r["dataset"]], r["image"])
    return rows


def score(a):
    rows = rows_with_project()
    done = set()
    if os.path.exists(SCORES):
        # Repair, do not merely skip, a torn line from a hard kill: skipped, it
        # stays in the file, the redo is appended onto the fragment, the merged
        # line never parses, and that image is "unscored" on every later run
        # and silently dropped from the corpus. Rewrite via a temp file so a
        # reclaim mid-repair cannot destroy the partial either.
        good, torn = [], 0
        for line in open(SCORES):
            try: done.add(json.loads(line)["key"]); good.append(line.rstrip("\n") + "\n")
            except Exception: torn += 1
        # A kill that lands after the closing brace but before the newline
        # leaves a COMPLETE last line with no terminator: torn == 0, and the
        # next append glues a new row onto it, costing two images. Rewriting
        # from `good` (every line re-terminated) covers that case too.
        with open(SCORES, "rb") as fh:
            fh.seek(0, 2); unterminated = fh.tell() > 0 and (fh.seek(-1, 2) or fh.read(1) != b"\n")
        if torn or unterminated:
            with open(SCORES + ".tmp", "w") as fh: fh.writelines(good)
            os.replace(SCORES + ".tmp", SCORES)
            print(f"repaired {SCORES}: dropped {torn} torn row(s), re-terminated last line")
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
            # deadline every 25, not every 500: at 6-15/s a 500 cadence
            # overshoots by up to 80 s and never fires on a short tail.
            if n % 25 == 0 and time.time() > deadline:
                out.flush()
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
        # REFUSE. An earlier version warned and then wrote clean_verdicts.csv
        # anyway -- all 85,623 rows, every column filled, internally
        # consistent -- and a truncated score file produced a 15,768-image
        # corpus that nothing downstream could tell from the real one.
        print(f"REFUSING to finalise: {len(missing):,} rows unscored. Run without --finalise first.")
        return

    for r in rows:
        s = sc.get(r["image"])
        bad = [p for p in r["projects"] if p in DROP_PROJECTS]
        if bad:
            r["clean_verdict"], r["clean_reason"] = "drop_project", DROP_PROJECTS[bad[0]]
        elif s is None:
            r["clean_verdict"], r["clean_reason"] = "unscored", ""
        elif s["err"]:
            r["clean_verdict"], r["clean_reason"] = "drop_unreadable", s["err"]
        else:
            fl = F.flags(s, r["class"])
            r["clean_verdict"] = "drop_" + fl[0] if fl else "keep"
            r["clean_reason"] = ",".join(fl)
        for k in ("grain", "edge_bar", "seam", "phash"):
            r[k] = s[k] if s else ""
        r["white"] = "" if not s or s.get("white") is None else s["white"]

    # Perceptual duplicates among what is still kept, clean projects surviving.
    #
    # EXACT for Hamming <= 8, by pigeonhole: the hash is 63 bits (8x8 DCT
    # minus the DC term), split into 9 bands of 7 bits; 8 differing bits can
    # touch at most 8 bands, so any pair within 8 agrees exactly on at least
    # one band and is compared. Radius 8, not 6: a second council review ran
    # the exhaustive all-pairs check on idx19 and found the split straddle
    # rate at Hamming 8 sitting at pure chance (34.9%), with 777 held-out
    # images having a train neighbour there -- and by eye about two thirds of
    # those pairs are the same photograph. Deduping at 6 and then verifying
    # at 6 was circular. (At 10 only ~20% are twins; that shell is handled by
    # split grouping, not deletion -- see make_dupe_groups.py.) An earlier version bucketed on the top 16
    # bits only, with a comment claiming close pairs "almost always share the
    # leading bits". They do not: P(top 16 agree | Hamming 6) = C(47,6)/C(63,6)
    # = 0.16, so it missed 84% of what it existed to find -- 1,952 images, 700
    # of them a held-out image with a twin in train. Three reviewers found it
    # independently. Note also that the median split leaves every hash with
    # exactly 31 set bits, so distances are always EVEN: <= 6 means {0,2,4,6}.
    rank = {p: i for i, p in enumerate(CLEAN_FIRST)}
    kept = sorted((r for r in rows if r["clean_verdict"] == "keep"),
                  key=lambda r: rank.get(r["project"], len(rank)))
    bands = [{} for _ in range(9)]
    for r in kept:
        h = int(r["phash"], 16)
        keys = [(h >> (7 * i)) & 0x7F for i in range(9)]
        seen = set(); hit = None
        for i, k in enumerate(keys):
            for c in bands[i].get(k, ()):
                if id(c) in seen: continue
                seen.add(id(c))
                if bin(h ^ int(c["phash"], 16)).count("1") <= DEDUP_RADIUS:
                    hit = c; break
            if hit: break
        if hit is None:
            for i, k in enumerate(keys):
                bands[i].setdefault(k, []).append(r)
        else:
            r["clean_verdict"] = "drop_near_duplicate"
            r["clean_reason"] = f"of {hit['image']} ({hit['project']})"

    for r in rows: r["projects"] = "|".join(r["projects"])
    cols = ["image", "sha", "dataset", "project", "projects", "class", "split",
            "grain", "white", "edge_bar", "seam", "phash", "clean_verdict", "clean_reason"]
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
    ap.add_argument("--whiteness", action="store_true", help="score whiteness for grain-flagged rows")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(SCORES), exist_ok=True)
    if a.whiteness: whiteness_pass(a)
    elif a.finalise: finalise()
    else: score(a)
