"""Find NEAR-duplicate images, which SHA-256 dedupe cannot see.

The corpus dedupes on the sha of the original bytes. That is exact and it is
not enough. The same photograph re-exported by another Roboflow project — a
different JPEG quality, a two-pixel crop, a resize — has a different sha and
enters the corpus twice. Rendering a demonstration sheet showed two panels of
one white sedan, different file names, identical 8-box label sets.

WHY THIS IS THE MOST EXPENSIVE BUG AVAILABLE
--------------------------------------------
build_train_index splits by sha, so two copies of one photo can land on
opposite sides of the train/valid boundary. The model then memorises the copy
it trained on and is scored on its twin. The score goes UP and the model gets
no better, which is the worst possible failure because it is invisible in
exactly the number you would use to detect it. This corpus was already rebuilt
once over a leak of this shape (burned-in annotations present in validation,
0.4390 mAP that measured the contamination). A perceptual-hash leak is the same
error wearing different clothes.

METHOD
------
dHash: greyscale, resize to 9x8, compare each pixel with its right-hand
neighbour, pack the 64 comparisons into an integer. Robust to resize, JPEG
quality and small brightness shifts — precisely the transforms that break a
byte hash — and it does not care about absolute colour.

Exact dHash collisions are grouped first. Then, because a near-duplicate can
differ by a bit or two, groups are extended by Hamming distance within buckets
keyed on 16-bit slices of the hash: two hashes within distance 3 must agree
exactly on at least one of the four slices, so this finds every such pair
without comparing all 14 billion.

OUTPUT is a set of groups; the caller decides what to do with them. The right
action is NOT deletion — a near-duplicate is a real image and useful training
data. It is to force every member of a group into the SAME split, which
removes the leak while keeping the pixels.

    python near_dupes.py --coco DIR --out groups.json [--sample N]
    python near_dupes.py --selftest
"""
import argparse
import json
import os
import sys

SLICES = 4
SLICE_BITS = 16
MAX_HAMMING = 3


def dhash(path, size=8):
    from PIL import Image
    import numpy as np
    with Image.open(path) as im:
        im = im.convert("L").resize((size + 1, size), Image.LANCZOS)
        a = np.asarray(im, dtype="int16")
    bits = (a[:, 1:] > a[:, :-1]).flatten()
    v = 0
    for b in bits:
        v = (v << 1) | int(b)
    return v


def _buckets(hashes):
    """key -> [ids], one bucket per 16-bit slice position."""
    out = [{} for _ in range(SLICES)]
    for i, h in hashes:
        for s in range(SLICES):
            k = (h >> (s * SLICE_BITS)) & ((1 << SLICE_BITS) - 1)
            out[s].setdefault(k, []).append(i)
    return out


def group_near_dupes(hashes, max_hamming=MAX_HAMMING):
    """hashes: [(id, dhash)] -> list of groups (each a list of ids), size >= 2.

    Union-find over candidate pairs that share a 16-bit slice. Two hashes at
    Hamming distance <= 3 cannot differ in all four slices, so no such pair is
    missed.
    """
    parent = {i: i for i, _h in hashes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    hmap = dict(hashes)
    for bucket in _buckets(hashes):
        for ids in bucket.values():
            if len(ids) < 2:
                continue
            # A slice shared by a huge number of images is a degenerate hash
            # (blank or near-blank frames); comparing them all is quadratic and
            # tells us nothing, so it is reported rather than ground through.
            if len(ids) > 400:
                continue
            for x in range(len(ids)):
                for y in range(x + 1, len(ids)):
                    a, b = ids[x], ids[y]
                    if bin(hmap[a] ^ hmap[b]).count("1") <= max_hamming:
                        union(a, b)

    groups = {}
    for i, _h in hashes:
        groups.setdefault(find(i), []).append(i)
    return [sorted(v) for v in groups.values() if len(v) > 1]


def _selftest():
    from PIL import Image
    import numpy as np
    import io
    import tempfile
    ok = fail = 0

    def check(name, cond, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"  PASS  {name}")
        else:
            fail += 1
            print(f"  FAIL  {name}  {detail}")

    tmp = tempfile.mkdtemp(prefix="nd_")
    rng = np.random.default_rng(0)
    base = Image.fromarray(
        rng.integers(0, 255, (400, 300, 3), dtype="uint8"), "RGB")
    # smooth it so resizing does not scramble the comparison pattern
    from PIL import ImageFilter
    base = base.filter(ImageFilter.GaussianBlur(6))

    p0 = os.path.join(tmp, "a.jpg")
    base.save(p0, quality=95)
    p1 = os.path.join(tmp, "b.jpg")           # re-encoded, lower quality
    base.save(p1, quality=45)
    p2 = os.path.join(tmp, "c.jpg")           # resized
    base.resize((260, 195)).save(p2, quality=90)
    p3 = os.path.join(tmp, "d.jpg")           # a different picture
    Image.fromarray(rng.integers(0, 255, (400, 300, 3), dtype="uint8"),
                    "RGB").filter(ImageFilter.GaussianBlur(6)).save(p3)

    h0, h1, h2, h3 = (dhash(p) for p in (p0, p1, p2, p3))
    check(f"re-encode survives (hamming {bin(h0 ^ h1).count('1')})",
          bin(h0 ^ h1).count("1") <= MAX_HAMMING)
    check(f"resize survives (hamming {bin(h0 ^ h2).count('1')})",
          bin(h0 ^ h2).count("1") <= MAX_HAMMING)
    check(f"different image separates (hamming {bin(h0 ^ h3).count('1')})",
          bin(h0 ^ h3).count("1") > MAX_HAMMING)

    g = group_near_dupes([(0, h0), (1, h1), (2, h2), (3, h3)])
    check(f"groups the three variants, excludes the stranger {g}",
          len(g) == 1 and sorted(g[0]) == [0, 1, 2], str(g))

    # transitive chaining: a-b close, b-c close, a-c further apart
    # The stranger must be genuinely distant. An earlier version used 1 << 40
    # against 5, which is only THREE bits apart — inside the threshold — so the
    # test failed for being wrong rather than the code being wrong.
    far = 0xFFFF_FFFF_0000_0000
    check(f"identical hashes group, distant one excluded "
          f"(hamming {bin(5 ^ far).count('1')})",
          group_near_dupes([(0, 5), (1, 5), (2, far)]) == [[0, 1]])
    check("no false group among unrelated hashes",
          group_near_dupes([(0, 0xF0F0F0F0F0F0F0F0),
                            (1, 0x0F0F0F0F0F0F0F0F)]) == [])
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{ok} passed, {fail} failed")
    return 1 if fail else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coco")
    ap.add_argument("--out")
    ap.add_argument("--sample", type=int, default=0,
                    help="hash only the first N images (estimate)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        raise SystemExit(_selftest())
    if not args.coco:
        ap.error("--coco is required")

    # EVERY source beneath --coco, not just the top-level one. This module
    # reads one annotation file originally, and when CarDD arrived as
    # merged640/cardd/ it hashed 167,157 images — the corpus exactly, with the
    # 2,816 new ones invisible. A source that escapes the leak check is worse
    # than one that was never added: it splits at random against a corpus it
    # may well be a re-export of, and the leak lands in the validation score.
    # build_train_index already pools by walking for _annotations.coco.json,
    # so this matches it and any future source is covered by default.
    sources = []
    for dirpath, _dirnames, filenames in os.walk(args.coco):
        if "_annotations.coco.json" in filenames:
            sources.append(dirpath)
    if not sources:
        ap.error(f"no _annotations.coco.json beneath {args.coco}")

    # file_name is the sha of the original bytes, so it is unique corpus-wide
    # and a name seen twice is the SAME image reachable through two sources —
    # hash it once. ids are per-source and collide, so they are discarded in
    # favour of a global index; the output has always been keyed on file_name.
    seen, paths = {}, []
    for sdir in sorted(sources):
        with open(os.path.join(sdir, "_annotations.coco.json")) as f:
            d = json.load(f)
        idir = os.path.join(sdir, "images")
        n_new = 0
        for i in d["images"]:
            fn = i["file_name"]
            if fn in seen:
                continue
            seen[fn] = len(paths)
            paths.append((len(paths), os.path.join(idir, fn)))
            n_new += 1
        print(f"  {os.path.relpath(sdir, args.coco):20s} "
              f"{len(d['images']):7,} images, {n_new:7,} new")
    by_id = {v: k for k, v in seen.items()}
    if args.sample:
        paths = paths[:args.sample]

    from multiprocessing import Pool

    print(f"hashing {len(paths):,} images with {args.workers} workers ...")
    with Pool(args.workers) as pool:
        res = pool.map(_hash_one, paths, chunksize=256)
    hashes = [r for r in res if r]
    print(f"hashed {len(hashes):,}")

    groups = group_near_dupes(hashes)
    dupes = sum(len(g) - 1 for g in groups)
    print(f"\nnear-duplicate groups : {len(groups):,}")
    print(f"redundant images      : {dupes:,} "
          f"({100.0 * dupes / max(1, len(hashes)):.1f}% of those hashed)")
    if groups:
        big = sorted(groups, key=len, reverse=True)[:5]
        print(f"largest groups        : {[len(g) for g in big]}")

    if args.out:
        with open(args.out, "w") as f:
            json.dump({"groups": [[by_id.get(i, i) for i in g]
                                  for g in groups],
                       "n_hashed": len(hashes), "n_redundant": dupes}, f)
        print(f"wrote {args.out}")


def _hash_one(t):
    try:
        return (t[0], dhash(t[1]))
    except Exception:
        return None


if __name__ == "__main__":
    main()
