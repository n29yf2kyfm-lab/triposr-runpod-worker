"""Deterministic 80/10/10 stratified split of the Drive corpus — as an INDEX.

WHY AN INDEX AND NOT COPIED FILES. The corpus is 2.1GB and the box has ~5GB
free. Three copies of it (train/valid/test) do not fit, and a balanced fourth
copy certainly does not. Every consumer of this split therefore reads a JSONL
of absolute paths plus a label, which costs 4MB and can be regenerated in
seconds. Nothing here moves, copies or rewrites an image.

WHY THE SPLIT HAPPENS BEFORE ANY BALANCING. dent_major has 8,979 images and
paint_fade has 11, so something will have to be oversampled or augmented before
training. If that happens FIRST, the same photograph — or a rotated crop of it —
lands in train AND in valid, and the validation number then measures memorisation
rather than generalisation. It is the single easiest way to ship a model that
scores 0.97 offline and is useless in the field. So: split first, on real
distinct images, and let the balancer act only inside the train split. This file
emits no duplicates at all; the `split` field is the contract the balancer must
respect.

DETERMINISM. Files are ordered by the SHA1 OF THEIR CONTENT, not by name and not
by directory order, then shuffled with a seed derived from the class name. Two
consequences worth having:

  * The split is reproducible on any machine and stable when files are renamed
    or the directory listing changes order.
  * Content hashing gives EXACT-DUPLICATE DETECTION for free, and duplicates are
    the other way an image straddles two splits. A photo present twice under
    dent_major would otherwise have a real chance of sitting in train and in
    test at once. Duplicates are dropped here, keeping one representative, and
    counted in the report.

CLEANLINESS. Only images the OCR/overlay filter passed are indexed. The filter's
verdict cache is read directly (it is the authority), so an image that is
burned_in_annotation, annotation_suspect or destroyed never reaches the
classifier. Images with no verdict yet are reported and excluded rather than
silently assumed clean.
"""

import argparse
import collections
import glob
import hashlib
import json
import os
import random

import classifier_taxonomy as tax

DRIVE = "/home/user/drive_images"
CACHE = "/home/user/rf/drive_cache.jsonl"
EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")

# A class needs enough images that a 10% test slice is more than noise. Below
# ~30 images a "test set" is 3 photographs: it cannot distinguish 60% accuracy
# from 90%, so quoting a per-class number for it is dishonest. Those classes are
# still indexed and still flagged, they just get an explicit recommendation.
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


def sha1_of(path, buf=1 << 20):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def split_sizes(n):
    """(train, valid, test) for n images, 80/10/10, never starving the tails.

    round() alone gives valid=test=0 for n<=7, which silently turns a small
    class into a train-only class. Instead every class with at least 3 images
    gets at least one image in valid and one in test — the number is not
    meaningful at that size, but it is honest about the class existing, and the
    report flags it.
    """
    if n <= 2:
        return n, 0, 0
    test = max(1, int(round(n * 0.10)))
    valid = max(1, int(round(n * 0.10)))
    train = n - valid - test
    if train < 1:  # n == 3
        train, valid, test = n - 2, 1, 1
    return train, valid, test


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DRIVE)
    ap.add_argument("--cache", default=CACHE)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(
        os.path.abspath(__file__)), "drive_classifier_split.jsonl"))
    ap.add_argument("--summary", default=None)
    ap.add_argument("--seed", type=int, default=20260814)
    ap.add_argument("--allow-unverdicted", action="store_true",
                    help="index images the cleaner has not reached yet "
                         "(default: exclude and report them)")
    args = ap.parse_args()
    summary_path = args.summary or args.out.replace(".jsonl", "_summary.json")

    verdicts = load_verdicts(args.cache)
    print(f"verdict cache: {len(verdicts)} entries")

    dropped = collections.Counter()
    by_folder = collections.defaultdict(list)
    for folder in sorted(os.listdir(args.data)):
        d = os.path.join(args.data, folder)
        if not os.path.isdir(d):
            continue
        t, sev = tax.resolve(folder)
        if t is None:
            print(f"  WARNING unknown folder, skipped: {folder}")
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.lower().endswith(EXTS):
                continue
            p = os.path.join(d, fn)
            if p not in verdicts:
                dropped["no_verdict_yet"] += 1
                if not args.allow_unverdicted:
                    continue
            else:
                v = verdicts[p]
                if v:
                    dropped[v] += 1
                    continue
            by_folder[folder].append(p)

    # Exact-duplicate removal, ACROSS the whole corpus rather than per folder:
    # the same photograph filed under both dent_major and dent_severe is a
    # label conflict as well as a leak, and keeping one copy of it is strictly
    # better than training on both readings of it.
    seen = {}
    rows = []
    dup_cross_class = 0
    for folder in sorted(by_folder):
        for p in by_folder[folder]:
            try:
                h = sha1_of(p)
            except OSError:
                dropped["unreadable"] += 1
                continue
            if h in seen:
                dropped["exact_duplicate"] += 1
                if seen[h] != folder:
                    dup_cross_class += 1
                continue
            seen[h] = folder
            rows.append((folder, p, h))

    t_of = {}
    for folder, p, h in rows:
        t_of.setdefault(folder, tax.resolve(folder))

    # STRATIFY ON THE FOLDER, not on the coarse type. The folder is the finest
    # label available, so a per-folder split automatically produces a balanced
    # split for the type head and for the severity head at the same time; the
    # reverse is not true — splitting on `dent` alone could put every dent_minor
    # in test by chance.
    per_folder = collections.defaultdict(list)
    for folder, p, h in rows:
        per_folder[folder].append((h, p))

    index, counts = [], collections.defaultdict(collections.Counter)
    for folder in sorted(per_folder):
        items = sorted(per_folder[folder])          # by content hash
        rng = random.Random(f"{args.seed}:{folder}")
        rng.shuffle(items)
        n_tr, n_va, n_te = split_sizes(len(items))
        splits = ["train"] * n_tr + ["valid"] * n_va + ["test"] * n_te
        t, sev = tax.resolve(folder)
        for (h, p), sp in zip(items, splits):
            counts[folder][sp] += 1
            index.append({
                "path": p,
                "folder": folder,
                "type": t,
                "severity": sev,
                "severity_name": tax.SEVERITY_NAMES.get(sev),
                "paint_depth": tax.paint_depth_of(folder),
                "role": ("negative" if t in tax.NEGATIVE_TYPES else
                         "held_out" if t in tax.HELD_OUT_TYPES else "train"),
                "split": sp,
                "sha1": h,
            })

    with open(args.out, "w") as f:
        for r in index:
            f.write(json.dumps(r) + "\n")

    too_small = [c for c in counts if sum(counts[c].values()) < MIN_SPLITTABLE]
    by_type = collections.defaultdict(collections.Counter)
    for r in index:
        by_type[r["type"]][r["split"]] += 1
    by_sev = collections.defaultdict(collections.Counter)
    for r in index:
        if r["severity"] and r["role"] == "train":
            by_sev[f'{r["type"]}/{r["severity_name"]}'][r["split"]] += 1

    summary = {
        "source": args.data,
        "seed": args.seed,
        "total_indexed": len(index),
        "dropped": dict(dropped),
        "duplicates_across_classes": dup_cross_class,
        "per_folder": {c: dict(v) for c, v in sorted(counts.items())},
        "per_type": {c: dict(v) for c, v in sorted(by_type.items())},
        "per_type_severity": {c: dict(v) for c, v in sorted(by_sev.items())},
        "too_small_to_split": sorted(too_small),
        "min_splittable": MIN_SPLITTABLE,
        "negative_types": tax.NEGATIVE_TYPES,
        "held_out_types": tax.HELD_OUT_TYPES,
    }
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nindexed {len(index)} images -> {args.out}")
    print(f"dropped: {dict(dropped)}  (cross-class dups: {dup_cross_class})")
    print(f"\n{'folder':<22}{'train':>7}{'valid':>7}{'test':>7}{'total':>8}")
    for c in sorted(counts, key=lambda c: -sum(counts[c].values())):
        v = counts[c]
        n = sum(v.values())
        flag = "  << too small to split" if n < MIN_SPLITTABLE else ""
        print(f"{c:<22}{v['train']:>7}{v['valid']:>7}{v['test']:>7}{n:>8}{flag}")
    print(f"\n{'type':<22}{'train':>7}{'valid':>7}{'test':>7}{'total':>8}")
    for c in sorted(by_type, key=lambda c: -sum(by_type[c].values())):
        v = by_type[c]
        print(f"{c:<22}{v['train']:>7}{v['valid']:>7}{v['test']:>7}"
              f"{sum(v.values()):>8}")
    print(f"\nsummary -> {summary_path}")


if __name__ == "__main__":
    main()
