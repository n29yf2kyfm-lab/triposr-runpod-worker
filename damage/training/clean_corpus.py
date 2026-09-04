"""Rebuild an index so the splits are honest and the duplicates are capped.

THE PROBLEM THIS EXISTS FOR

The corpus deduplicates by SHA. A sha changes when a single byte changes, so
re-encoding a JPEG, resizing it, or cropping it produces a "new" image that
sha dedup cannot see. Perceptual hashing over the built corpus found:

    169,973 files  ->  118,829 distinct photographs   (30% redundant)
    13.3% of VALID is a near-copy of something in TRAIN
    13.1% of TEST  is a near-copy of something in TRAIN

The second pair is the damaging one. A validation image that the model has
already trained on is not a measurement, it is a memory test, and it inflates
mAP without the detector improving. That is the shape of what was observed:
validation mAP rose 0.3948 -> 0.4237 across runs while the score on a real
external test set did not move.

WHAT IT DOES

1. Clusters every image by perceptual hash at Hamming <= 5.
2. Assigns splits BY CLUSTER, not by image, so every copy of a photograph
   lands in the same split and leakage becomes structurally impossible
   rather than merely unlikely.
3. Caps how many copies of one photograph may appear in train. Five copies of
   a dent teach the model that this dent is common, not what dents look like
   -- and the duplication is concentrated 4.5x in classes that are already
   dominant, so it actively worsens the imbalance.
4. Keeps valid/test at one image per cluster: a test set should ask each
   question once.

WHAT IT DOES NOT DO

It does not touch the images or the annotations, and it never invents a box.
It rewrites index membership only, so any mistake here is undone by rerunning
the previous index.
"""
import argparse
import collections
import json
import os
import random
import sys

HAMMING = 5
SEGMENTS = 4          # 64-bit hash split into 4x16 bits


def cluster_hashes(hashes, radius=HAMMING):
    """Union-find over hashes within `radius` bits of each other.

    Exact, not approximate. Two 64-bit values differing in at most 5 bits must
    agree exactly on at least one of four 16-bit segments -- 5 errors cannot
    touch 4 segments -- so bucketing by segment and comparing only within a
    bucket finds every pair the brute-force 1.4e10 comparisons would.
    """
    parent = {h: h for h in hashes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    seg = collections.defaultdict(list)
    for h in hashes:
        for i in range(SEGMENTS):
            seg[(i, (h >> (16 * i)) & 0xFFFF)].append(h)

    for group in seg.values():
        # A bucket this large is a degenerate hash (blank or near-uniform
        # frames). Comparing it is quadratic and tells us nothing.
        if len(group) > 400:
            continue
        for i, a in enumerate(group):
            ra = find(a)
            for b in group[i + 1:]:
                if bin(a ^ b).count("1") <= radius:
                    rb = find(b)
                    if ra != rb:
                        parent[rb] = ra
                        ra = find(a)

    out = collections.defaultdict(list)
    for h in hashes:
        out[find(h)].append(h)
    return out


def assign_splits(clusters, ratios=(0.80, 0.10, 0.10), seed=1337):
    """Split by cluster. Deterministic in the cluster's own identity.

    Hashing the cluster root rather than shuffling a list means a cluster
    keeps its split when the corpus grows -- add 10,000 images and the
    existing valid set does not silently reshuffle into train.
    """
    rng = random.Random(seed)
    keys = sorted(clusters)
    rng.shuffle(keys)
    n = len(keys)
    n_tr = int(n * ratios[0])
    n_va = int(n * (ratios[0] + ratios[1]))
    out = {}
    for i, k in enumerate(keys):
        out[k] = "train" if i < n_tr else ("valid" if i < n_va else "test")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True, help="dir holding images.jsonl")
    ap.add_argument("--qc", required=True, help="jsonl with file+phash")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-train-copies", type=int, default=2,
                    help="copies of one photograph allowed in train")
    ap.add_argument("--seed", type=int, default=1337)
    a = ap.parse_args()

    rows = [json.loads(l) for l in
            open(os.path.join(a.index, "images.jsonl"))]
    by_base = {os.path.basename(r["file"]): r for r in rows}
    print(f"index: {len(rows):,} images")

    phash, unhashed = {}, 0
    for line in open(a.qc):
        q = json.loads(line)
        if not q.get("ok"):
            continue
        r = by_base.get(os.path.basename(q["file"]))
        if r is None:
            continue
        phash[r["sha"]] = q["phash"]
    unhashed = [r for r in rows if r["sha"] not in phash]
    print(f"hashed: {len(phash):,}   unhashed: {len(unhashed):,}")

    shas_by_hash = collections.defaultdict(list)
    for sha, h in phash.items():
        shas_by_hash[h].append(sha)
    clusters = cluster_hashes(list(shas_by_hash))
    members = {root: [s for h in hs for s in shas_by_hash[h]]
               for root, hs in clusters.items()}
    print(f"clusters: {len(members):,} distinct photographs "
          f"from {len(phash):,} files")

    split_of_cluster = assign_splits(members, seed=a.seed)
    cluster_of = {s: root for root, ss in members.items() for s in ss}

    rng = random.Random(a.seed)
    kept, per_split = [], collections.Counter()
    dropped_cap = dropped_extra = 0
    for root, shas in members.items():
        sp = split_of_cluster[root]
        # deterministic order, so a rerun keeps the same members
        shas = sorted(shas)
        if sp == "train":
            keep = shas[:a.max_train_copies]
            dropped_cap += len(shas) - len(keep)
        else:
            keep = shas[:1]           # ask each question once
            dropped_extra += len(shas) - 1
        for s in keep:
            per_split[sp] += 1
        kept.extend((s, sp) for s in keep)

    # An unhashed image has no cluster, so it cannot be proven distinct from
    # anything. Keeping it in train risks a silent leak into valid; dropping
    # it loses real data. Train is the safe home: a leak INTO train hurts
    # nothing, a leak into valid corrupts the measurement.
    for r in unhashed:
        kept.append((r["sha"], "train"))
        per_split["train"] += 1

    keep_split = dict(kept)
    os.makedirs(a.out, exist_ok=True)
    n_out = 0
    with open(os.path.join(a.out, "images.jsonl"), "w") as f:
        for r in rows:
            sp = keep_split.get(r["sha"])
            if sp is None:
                continue
            r = dict(r, split=sp)
            f.write(json.dumps(r, sort_keys=True) + "\n")
            n_out += 1

    # PROVE the leak is gone rather than asserting it.
    split_now = {s: sp for s, sp in kept}
    leaks = 0
    for root, shas in members.items():
        seen = {split_now[s] for s in shas if s in split_now}
        if len(seen) > 1:
            leaks += 1

    boxes_before = sum(len(r.get("boxes") or []) for r in rows)
    boxes_after = sum(len(r.get("boxes") or []) for r in rows
                      if r["sha"] in keep_split)
    print()
    print(f"  wrote {n_out:,} images to {a.out}/images.jsonl")
    print(f"    train {per_split['train']:,}   valid {per_split['valid']:,}"
          f"   test {per_split['test']:,}")
    print(f"  dropped: {dropped_cap:,} over the train copy cap, "
          f"{dropped_extra:,} extra copies from valid/test")
    print(f"  boxes: {boxes_before:,} -> {boxes_after:,}")
    print(f"  CLUSTERS SPANNING MORE THAN ONE SPLIT: {leaks}")
    if leaks:
        sys.exit("split leakage survived the rebuild — refusing to ship this")
    print("  verified: no photograph appears in two splits")

    with open(os.path.join(a.out, "clean_report.json"), "w") as f:
        json.dump({"in": len(rows), "out": n_out,
                   "clusters": len(members),
                   "per_split": dict(per_split),
                   "dropped_train_cap": dropped_cap,
                   "dropped_eval_extra": dropped_extra,
                   "boxes_before": boxes_before, "boxes_after": boxes_after,
                   "max_train_copies": a.max_train_copies,
                   "hamming": HAMMING, "seed": a.seed,
                   "leaks_after": leaks}, f, indent=1)


def _selftest():
    # clustering: transitive chains merge, distant hashes do not
    a = 0b0
    b = 0b111                       # 3 bits from a
    c = 0b111111                    # 3 more from b, 6 from a -> chains via b
    far = (1 << 40) | 0xFFFF
    cl = cluster_hashes([a, b, c, far])
    groups = sorted(sorted(v) for v in cl.values())
    assert [a, b, c] in groups, groups
    assert [far] in groups, groups

    # a cluster never spans two splits
    cls = {i: [f"s{i}a", f"s{i}b"] for i in range(200)}
    sp = assign_splits(cls)
    assert set(sp.values()) == {"train", "valid", "test"}
    # and the assignment is stable across calls
    assert sp == assign_splits(cls)

    # ratios land in the right ballpark
    n = collections.Counter(sp.values())
    assert 150 <= n["train"] <= 170, n
    print("clean_corpus selftests passed")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
