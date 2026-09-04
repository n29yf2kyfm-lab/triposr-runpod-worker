"""
Near-duplicate GROUPS for build_train_index --dupe-groups, from the phashes in
audit/scores.jsonl, over the images the clean pass kept.

Two radii do two different jobs:
  <= 8   audit_corpus.py DELETES one of the pair (about two thirds are the
         same photograph, by eye, so a deletion is usually right)
  <= 10  this file GROUPS the pair so the splitter keeps both on the same
         side. Only ~20% of pairs at 10 are twins, so deleting there would
         throw away real photographs; grouping costs nothing and still stops
         a twin straddling train and validation.

The old near_dupes_phash.json cannot do this: every one of its 25,030 groups
had collapsed to <= 1 survivor by idx19, so `--dupe-groups` was a no-op and
the split straddle rate at Hamming 8 sat at pure chance (34.9%).

Exact for radius 10 by pigeonhole: 11 bands (8 of 7 bits, 3 of 5 -- wait,
8*6 + 3*5 = 63) -- 10 differing bits can touch at most 10 of 11 bands, so any
pair within 10 agrees on at least one band and is compared.

Output matches the format load_dupe_groups() reads: {"groups": [[<stem>.jpg,
...], ...]}, stems being sha[:20], which is also the file stem on disk.

    python3 make_dupe_groups.py --out /home/user/rf/near_dupes_r10.json
"""
import argparse, csv, json, os, collections

RADIUS = 10
BANDS = [6] * 8 + [5] * 3          # 48 + 15 = 63 bits


def band_keys(h):
    keys, shift = [], 0
    for w in BANDS:
        keys.append((shift, (h >> shift) & ((1 << w) - 1))); shift += w
    return keys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdicts", default="/home/user/rf/audit/clean_verdicts.csv")
    ap.add_argument("--out", default="/home/user/rf/near_dupes_r10.json")
    a = ap.parse_args()

    rows = [r for r in csv.DictReader(open(a.verdicts)) if r["clean_verdict"] == "keep" and r["phash"]]
    stem = {r["image"]: os.path.splitext(os.path.basename(r["image"]))[0] for r in rows}
    h = {r["image"]: int(r["phash"], 16) for r in rows}
    files = list(h)

    parent = {f: f for f in files}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x

    # Bands of 5-6 bits over ~46k images put ~700-1,500 images in EVERY
    # bucket, so a Python double loop with a small bucket cap compares almost
    # nothing (a first version with cap 400 found 71 groups where an exhaustive
    # pass had counted 7,584 pairs). Vectorised: per bucket, an m x m XOR and
    # popcount in numpy; 1,500 x 1,500 is 2.25M entries, trivial.
    import numpy as np
    H = np.array([h[f] for f in files], dtype=np.uint64)
    try:
        popcount = np.bitwise_count                     # numpy >= 2.0
    except AttributeError:
        _t = np.array([bin(i).count("1") for i in range(1 << 16)], dtype=np.uint8)
        def popcount(x):
            x = x.astype(np.uint64)
            return (_t[x & 0xFFFF] + _t[(x >> 16) & 0xFFFF]
                    + _t[(x >> 32) & 0xFFFF] + _t[(x >> 48) & 0xFFFF])
    pairs = 0
    shift = 0
    for w in BANDS:
        keys = (H >> np.uint64(shift)) & np.uint64((1 << w) - 1); shift += w
        order = np.argsort(keys, kind="stable"); ks = keys[order]
        starts = np.flatnonzero(np.r_[True, ks[1:] != ks[:-1]]); ends = np.r_[starts[1:], len(ks)]
        for s, e in zip(starts, ends):
            if e - s < 2 or e - s > 20000:               # 20k: degenerate blank frames only
                continue
            idx = order[s:e]; X = H[idx]
            d = popcount(X[:, None] ^ X[None, :])
            ii, jj = np.nonzero(np.triu(d <= RADIUS, k=1))
            for i, j in zip(ii.tolist(), jj.tolist()):
                x, y = files[idx[i]], files[idx[j]]
                rx, ry = find(x), find(y)
                if rx != ry: parent[ry] = rx; pairs += 1

    groups = collections.defaultdict(list)
    for f in files:
        groups[find(f)].append(stem[f] + ".jpg")
    out = [sorted(g) for g in groups.values() if len(g) > 1]
    out.sort(key=lambda g: (-len(g), g[0]))
    with open(a.out, "w") as fh:
        json.dump({"radius": RADIUS, "bands": BANDS, "groups": out}, fh)
    covered = sum(len(g) for g in out)
    print(f"{len(files):,} kept images -> {len(out):,} groups covering {covered:,} images "
          f"(largest {len(out[0]) if out else 0}); wrote {a.out}")


if __name__ == "__main__":
    main()
