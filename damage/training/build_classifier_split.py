"""Deterministic 80/10/10 stratified split of the Drive corpus — as an INDEX.

WHY AN INDEX AND NOT COPIED FILES. The corpus is 2.1GB and the box has ~5GB
free. Three copies of it (train/valid/test) do not fit, and a balanced fourth
copy certainly does not. Every consumer reads a JSONL of absolute paths plus a
label, which costs a few MB and regenerates in seconds. Nothing here moves,
copies or rewrites an image.

WHY THE SPLIT HAPPENS BEFORE ANY BALANCING. dent_major has 8,979 files and
paint_fade has 11, so something will have to be oversampled or augmented before
training. If that happens FIRST, the same photograph — or a noised copy of it —
lands in train AND in valid, and the validation number then measures memorisation
rather than generalisation. Split first, on real distinct images; let the
balancer act only inside the train split. This file emits no duplicates of its
own, and `split` is the contract the balancer must respect.

WHY THE SPLIT IS ON GROUPS, NOT IMAGES. This is the part that a naive
stratified split gets silently wrong here. The corpus contains the same
photograph many times over, in two different disguises:

    22,318 files  ->  13,758 distinct byte streams  ->  fewer still distinct
                                                        PHOTOGRAPHS

The first collapse is exact re-ingestion (the same file under two batch
numbers). The second is Roboflow augmentation: noised, brightened and flipped
copies that have different bytes, different SHA1s, and are the same picture. A
per-image random split puts variant 1 in train and variant 2 in test, and the
test score then measures nothing at all.

So images are first grouped into GROUPS OF ONE PHOTOGRAPH — connected components
under "perceptual hashes within Hamming distance 5" — and a whole group is
assigned to one split. Groups are the unit that is stratified, counted, and
80/10/10'd. Every row keeps `group` and `group_size`, and one row per group is
marked `representative`, so a consumer can train on all variants but evaluate on
distinct photographs only, which is the only honest way to read the number.

DETERMINISM. Groups are ordered by their smallest member's content hash — not by
filename, not by directory order — then shuffled with a seed derived from the
folder name. Reproducible anywhere, stable under renames.

CLEANLINESS. Only images the OCR/overlay filter passed are indexed; the filter's
verdict cache is the authority. Images with no verdict yet are counted and
excluded rather than silently assumed clean.
"""

import argparse
import collections
import glob
import json
import os
import random

import classifier_taxonomy as tax

DRIVE = "/home/user/drive_images"
CACHE = "/home/user/rf/drive_cache.jsonl"
HASHES = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "drive_hashes.jsonl")
EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")

# Two perceptual hashes this close are the same photograph under augmentation.
# 5 of 64 bits is empirically past the noise/brightness variants and short of
# merging two different dents on the same colour of door.
HAMMING = 5

# A class needs enough DISTINCT PHOTOGRAPHS that a 10% test slice is more than
# noise. Below ~30 the test set is three pictures: it cannot tell 60% accuracy
# from 90%, so quoting a per-class number for it is dishonest. Such classes are
# still indexed, and flagged.
MIN_SPLITTABLE = 30


def load_verdicts(cache_path):
    """{path: verdict} merged across every shard file the cleaner wrote.

    A null verdict means the image passed. Later lines win, so a re-classified
    image supersedes its earlier entry.
    """
    out = {}
    for p in sorted(glob.glob(cache_path + "*")):
        with open(p) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue  # half-written last line after a hard kill
                out[r["path"]] = r.get("verdict")
    return out


def load_hashes(path):
    out = {}
    if not os.path.exists(path):
        return out
    with open(path) as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("sha1"):
                out[r["path"]] = (r["sha1"], r.get("dhash"))
    return out


class Union:
    def __init__(self):
        self.p = {}

    def find(self, a):
        self.p.setdefault(a, a)
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def group_images(rows):
    """[(idx, sha1, dhash)] -> {idx: group_id}.

    Exact SHA1 matches are unioned outright. Perceptual matches are found by
    BANDED LSH: two hashes within Hamming 5 must agree exactly on at least one
    of four 16-bit bands (pigeonhole — 5 differing bits cannot touch all four
    bands), so only same-band pairs are ever compared. That turns an O(n^2)
    comparison over 22k images into a few million integer XORs.
    """
    u = Union()
    by_sha = collections.defaultdict(list)
    bands = [collections.defaultdict(list) for _ in range(4)]
    for i, sha, dh in rows:
        u.find(i)
        by_sha[sha].append(i)
        if dh is None:
            continue
        for b in range(4):
            bands[b][(b, (dh >> (16 * b)) & 0xFFFF)].append((i, dh))
    for ids in by_sha.values():
        for j in ids[1:]:
            u.union(ids[0], j)
    for band in bands:
        for bucket in band.values():
            if len(bucket) > 400:
                # A flat grey band shared by hundreds of images is not evidence
                # of anything; comparing it is quadratic and merges unrelated
                # photos. The other three bands still catch the real pairs.
                continue
            for a in range(len(bucket)):
                ia, ha = bucket[a]
                for b in range(a + 1, len(bucket)):
                    ib, hb = bucket[b]
                    if bin(ha ^ hb).count("1") <= HAMMING:
                        u.union(ia, ib)
    return {i: u.find(i) for i, _s, _d in rows}


def split_sizes(n):
    """(train, valid, test) group counts for n groups, 80/10/10.

    round() alone gives valid=test=0 for n<=7, silently turning a small class
    into a train-only class. Every class with at least 3 groups gets at least
    one group in valid and one in test — not a meaningful number at that size,
    but honest that the class exists, and flagged in the report.
    """
    if n <= 2:
        return n, 0, 0
    test = max(1, int(round(n * 0.10)))
    valid = max(1, int(round(n * 0.10)))
    train = n - valid - test
    if train < 1:
        train, valid, test = n - 2, 1, 1
    return train, valid, test


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--data", default=DRIVE)
    ap.add_argument("--cache", default=CACHE)
    ap.add_argument("--hashes", default=HASHES)
    ap.add_argument("--out", default=os.path.join(
        here, "drive_classifier_split.jsonl"))
    ap.add_argument("--summary", default=None)
    ap.add_argument("--seed", type=int, default=20260814)
    ap.add_argument("--allow-unverdicted", action="store_true",
                    help="index images the cleaner has not reached yet "
                         "(default: exclude and report them)")
    ap.add_argument("--keep-suspect", action="store_true",
                    help="index annotation_suspect images too. The filter's "
                         "overlay heuristic fires hard on RED PAINT and rust — "
                         "a hand-checked sample of the suspect bucket was "
                         "mostly undamaged-looking red cars and genuine damage "
                         "photos with no overlay at all — so this recovers "
                         "roughly a quarter of the corpus at the cost of some "
                         "annotation leakage. OCR-CONFIRMED text "
                         "(burned_in_annotation) is never recovered.")
    args = ap.parse_args()
    summary_path = args.summary or args.out.replace(".jsonl", "_summary.json")

    verdicts = load_verdicts(args.cache)
    hashes = load_hashes(args.hashes)
    print(f"verdicts: {len(verdicts)}   hashes: {len(hashes)}")

    dropped = collections.Counter()
    cand = []  # (folder, path, sha1, dhash)
    for folder in sorted(os.listdir(args.data)):
        d = os.path.join(args.data, folder)
        if not os.path.isdir(d):
            continue
        if tax.type_of(folder) is None:
            print(f"  WARNING unknown folder, skipped: {folder}")
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.lower().endswith(EXTS):
                continue
            p = os.path.join(d, fn)
            v = verdicts.get(p, "__missing__")
            if v == "__missing__":
                dropped["no_verdict_yet"] += 1
                if not args.allow_unverdicted:
                    continue
            elif v == "annotation_suspect" and args.keep_suspect:
                dropped["suspect_kept"] += 1
            elif v:
                dropped[v] += 1
                continue
            if p not in hashes:
                dropped["no_hash"] += 1
                continue
            sha, dh = hashes[p]
            cand.append((folder, p, sha, dh))

    gid = group_images([(i, c[2], c[3]) for i, c in enumerate(cand)])

    # Group -> its folders. A group spanning two folders is a LABEL CONFLICT:
    # the same photograph filed as two different classes. It is resolved by
    # majority (ties by folder name, so it stays deterministic) and counted,
    # because an unresolved one would put contradictory labels in the same
    # split and quietly cap the achievable accuracy.
    members = collections.defaultdict(list)
    for i, (folder, p, sha, dh) in enumerate(cand):
        members[gid[i]].append(i)
    conflicts = 0
    group_folder, group_key = {}, {}
    for g, idxs in members.items():
        fol = collections.Counter(cand[i][0] for i in idxs)
        if len(fol) > 1:
            conflicts += 1
        group_folder[g] = sorted(fol.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        group_key[g] = min(cand[i][2] for i in idxs)

    per_folder = collections.defaultdict(list)
    for g in members:
        per_folder[group_folder[g]].append(g)

    index = []
    counts = collections.defaultdict(collections.Counter)   # images
    gcounts = collections.defaultdict(collections.Counter)  # groups
    for folder in sorted(per_folder):
        groups = sorted(per_folder[folder], key=lambda g: group_key[g])
        rng = random.Random(f"{args.seed}:{folder}")
        rng.shuffle(groups)
        n_tr, n_va, n_te = split_sizes(len(groups))
        splits = ["train"] * n_tr + ["valid"] * n_va + ["test"] * n_te
        t, sev = tax.resolve(folder)
        role = ("negative" if t in tax.NEGATIVE_TYPES else
                "held_out" if t in tax.HELD_OUT_TYPES else "train")
        for g, sp in zip(groups, splits):
            gcounts[folder][sp] += 1
            idxs = sorted(members[g], key=lambda i: cand[i][2])
            for rank, i in enumerate(idxs):
                fol_i, p, sha, dh = cand[i]
                counts[folder][sp] += 1
                index.append({
                    "path": p,
                    "folder": folder,
                    "folder_as_filed": fol_i,
                    "type": t,
                    "severity": sev,
                    "severity_name": tax.SEVERITY_NAMES.get(sev),
                    "paint_depth": tax.paint_depth_of(folder),
                    "role": role,
                    "split": sp,
                    "sha1": sha,
                    "group": group_key[g],
                    "group_size": len(idxs),
                    "representative": rank == 0,
                })

    index.sort(key=lambda r: (r["folder"], r["group"], r["sha1"]))
    with open(args.out, "w") as f:
        for r in index:
            f.write(json.dumps(r) + "\n")

    reps = [r for r in index if r["representative"]]
    by_type = collections.defaultdict(collections.Counter)
    for r in reps:
        by_type[r["type"]][r["split"]] += 1
    by_sev = collections.defaultdict(collections.Counter)
    for r in reps:
        if r["severity"] and r["role"] == "train":
            by_sev[f'{r["type"]}/{r["severity_name"]}'][r["split"]] += 1
    too_small = sorted(c for c in gcounts
                       if sum(gcounts[c].values()) < MIN_SPLITTABLE)

    summary = {
        "source": args.data,
        "seed": args.seed,
        "hamming": HAMMING,
        "files_indexed": len(index),
        "distinct_photographs": len(reps),
        "dropped": dict(dropped),
        "label_conflict_groups": conflicts,
        "per_folder_files": {c: dict(v) for c, v in sorted(counts.items())},
        "per_folder_groups": {c: dict(v) for c, v in sorted(gcounts.items())},
        "per_type_groups": {c: dict(v) for c, v in sorted(by_type.items())},
        "per_type_severity_groups": {c: dict(v) for c, v in sorted(by_sev.items())},
        "too_small_to_split": too_small,
        "min_splittable": MIN_SPLITTABLE,
        "negative_types": tax.NEGATIVE_TYPES,
        "held_out_types": tax.HELD_OUT_TYPES,
    }
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{len(index)} files -> {len(reps)} distinct photographs")
    print(f"dropped: {dict(dropped)}")
    print(f"label-conflict groups (same photo, two folders): {conflicts}")
    print(f"\n{'folder':<22}{'train':>7}{'valid':>7}{'test':>7}"
          f"{'photos':>8}{'files':>8}")
    order = sorted(gcounts, key=lambda c: -sum(gcounts[c].values()))
    for c in order:
        v, n = gcounts[c], sum(gcounts[c].values())
        flag = "  << too small to split" if n < MIN_SPLITTABLE else ""
        print(f"{c:<22}{v['train']:>7}{v['valid']:>7}{v['test']:>7}{n:>8}"
              f"{sum(counts[c].values()):>8}{flag}")
    print(f"\n{'type (photos)':<22}{'train':>7}{'valid':>7}{'test':>7}{'total':>8}")
    for c in sorted(by_type, key=lambda c: -sum(by_type[c].values())):
        v = by_type[c]
        print(f"{c:<22}{v['train']:>7}{v['valid']:>7}{v['test']:>7}"
              f"{sum(v.values()):>8}")
    print(f"\nindex   -> {args.out}\nsummary -> {summary_path}")


if __name__ == "__main__":
    main()
