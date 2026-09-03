"""
Leak audit for a training index. Writes <idx>/leak_verified.json.

idx18 shipped with no such artifact, and a council review found 700 held-out
images with a near-twin in train (6.4%) -- the split "by photograph, not by
file" claim had no evidence behind it and was false. This is the evidence:

  sha        no image sha in more than one split
  aug        no row with a recipe or rep>0 outside train
  phash      no held-out image within Hamming <= RADIUS of any train image,
             found with a 9-band x 7-bit index that is EXACT for radius 8 on
             this 63-bit hash (8 differing bits cannot touch all 9 bands)

Phashes come from audit/scores.jsonl (keyed by relative image path), so the
check is independent of whatever the index builder believed about groups.

    python3 verify_index.py --idx /home/user/rf/idx19
"""
import argparse, json, os, collections

RADIUS = 8   # audit_corpus dedups at 8; checking at the dedup radius is circular,
             # but the exhaustive check that found the leak was AT 8, so 8 is the
             # floor. 9 bands x 7 bits is exact for radius 8 by pigeonhole.


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--idx", required=True)
    ap.add_argument("--scores", default="/home/user/rf/audit/scores.jsonl")
    a = ap.parse_args()

    ph = {}
    for line in open(a.scores):
        d = json.loads(line); ph[d["key"]] = int(d["phash"], 16)

    split, file_of = {}, {}
    for line in open(os.path.join(a.idx, "images.jsonl")):
        d = json.loads(line)
        split.setdefault(d["sha"], set()).add(d["split"]); file_of[d["sha"]] = d["file"]
    sha_multi = [s for s, v in split.items() if len(v) > 1]

    aug_outside = collections.Counter()
    for line in open(os.path.join(a.idx, "index.jsonl")):
        d = json.loads(line)
        if d["split"] != "train" and (d.get("recipe") or d.get("rep", 0) > 0):
            aug_outside[d["split"]] += 1

    # Negatives are index rows too: a crop from a held-out image would be a
    # leak, and a crop with a recipe outside train is augmentation outside train.
    neg_path = os.path.join(a.idx, "negatives.jsonl")
    neg_outside = 0
    if os.path.exists(neg_path):
        for line in open(neg_path):
            d = json.loads(line)
            if "train" not in split.get(d["sha"], {"train"}) or d.get("split") != "train":
                neg_outside += 1

    # 7x9 LSH over train; probe every held-out image. An image with no phash
    # cannot be checked, so it is COUNTED and fails the audit rather than
    # silently passing as leak-free.
    bands = [collections.defaultdict(list) for _ in range(9)]
    train, held, unhashed = [], [], []
    for s, v in split.items():
        f = file_of[s]
        if f not in ph:
            unhashed.append(f); continue
        (train if "train" in v else held).append((s, f, ph[f]))
    for s, f, h in train:
        for i in range(9):
            bands[i][(h >> (7 * i)) & 0x7F].append((s, f, h))
    leaks = []
    for s, f, h in held:
        seen = set(); best = None
        for i in range(9):
            for ts, tf, th in bands[i].get((h >> (7 * i)) & 0x7F, ()):
                if ts in seen: continue
                seen.add(ts)
                d = bin(h ^ th).count("1")
                if d <= RADIUS and (best is None or d < best[0]): best = (d, tf)
        if best: leaks.append({"held_out": f, "split": sorted(split[s])[0], "train_twin": best[1], "hamming": best[0]})

    by_d = collections.Counter(l["hamming"] for l in leaks)
    report = {"index": a.idx, "radius": RADIUS, "method": "9-band x 7-bit LSH, exact for radius <= 8",
              "n_train": len(train), "n_held_out": len(held), "sha_in_multiple_splits": len(sha_multi),
              "images_without_phash": len(unhashed), "negatives_outside_train": neg_outside,
              "augmented_rows_outside_train": dict(aug_outside),
              "held_out_with_train_twin": len(leaks), "by_hamming": {str(k): v for k, v in sorted(by_d.items())},
              "examples": leaks[:20]}
    with open(os.path.join(a.idx, "leak_verified.json"), "w") as f:
        json.dump(report, f, indent=1)
    ok = not sha_multi and not aug_outside and not leaks and not unhashed and not neg_outside
    print(json.dumps({k: v for k, v in report.items() if k != "examples"}, indent=1))
    print("LEAK-FREE" if ok else f"LEAKS: {len(leaks):,} held-out images have a train twin within Hamming {RADIUS}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
