#!/usr/bin/env python3
"""carparts_split.py — rebuild Carparts-Seg with an HONEST split, by source photo.

MEASURED PROBLEM (2026-08-20). The shipped dataset is 3,833 images but only ~600
distinct photographs: filenames are Roboflow's `<stem>_jpg.rf.<hash>.jpg` and
each source photo ships ~5.5 baked-in augmentations (rotations, flips, blur).
Grouping by stem:

    train 579 stems / val 295 / test 229
    train n val  = 290 stems  -> 98.3% of val is an augmented copy of a train photo
    train n test = 223 stems  -> 97.4% of test likewise

So the shipped val/test splits measure MEMORISATION of the same photographs, and
any mAP quoted against them — including the docs page's — is inflated by an
unknown amount. This script pools all three splits, groups by stem, and assigns
each STEM wholly to train or val, so no photograph appears on both sides.

It also caps variants per stem. Our target domain (seg_views renders) is always
upright and always the same ten calibrated angles, so the baked rotation
augmentations buy us nothing and cost 5.5x the CPU per epoch.

Run: python3 carparts_split.py <src_root> <dst_root> [train_frac] [n_train_var]
"""
import os
import random
import re
import sys
from collections import defaultdict

from carparts_remap import MAP, OURS, SRC_NAMES, YAML

STEM = re.compile(r"_jpg\.rf\.[0-9a-f]+\..*$")


def build(src, dst, frac=0.8, nvar=3, seed=0):
    groups = defaultdict(list)
    for split in ("train", "val", "test"):
        for fn in os.listdir(os.path.join(src, "images", split)):
            groups[STEM.sub("", fn)].append((split, fn))
    stems = sorted(groups)
    random.Random(seed).shuffle(stems)
    cut = int(len(stems) * frac)
    assign = {s: ("train" if i < cut else "val") for i, s in enumerate(stems)}
    print(f"{sum(len(v) for v in groups.values())} images -> {len(stems)} distinct "
          f"photos; train {cut} photos / val {len(stems)-cut} photos")

    counts = {"train": 0, "val": 0}
    inst = {"train": defaultdict(int), "val": defaultdict(int)}
    for s in stems:
        tgt = assign[s]
        keep = sorted(groups[s])[: (nvar if tgt == "train" else 1)]
        for split, fn in keep:
            stem = os.path.splitext(fn)[0]
            di = os.path.join(dst, "images", tgt)
            dl = os.path.join(dst, "labels", tgt)
            os.makedirs(di, exist_ok=True)
            os.makedirs(dl, exist_ok=True)
            out = []
            for ln in open(os.path.join(src, "labels", split, stem + ".txt")):
                p = ln.split()
                if not p:
                    continue
                t = MAP[SRC_NAMES[int(p[0])]]
                if t is None:
                    continue
                inst[tgt][t] += 1
                out.append(" ".join([str(OURS[t])] + p[1:]))
            open(os.path.join(dl, stem + ".txt"), "w").write(
                "\n".join(out) + ("\n" if out else ""))
            d = os.path.join(di, fn)
            if not os.path.exists(d):
                os.symlink(os.path.abspath(os.path.join(src, "images", split, fn)), d)
            counts[tgt] += 1
    y = YAML.format(root=os.path.abspath(dst)).replace("test: images/test\n", "")
    open(os.path.join(dst, "carparts4.yaml"), "w").write(y)
    print("images:", counts)
    print("train instances:", dict(inst["train"]))
    print("val   instances:", dict(inst["val"]))


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2],
          float(sys.argv[3]) if len(sys.argv) > 3 else 0.8,
          int(sys.argv[4]) if len(sys.argv) > 4 else 3)
    print("SPLIT_DONE")
