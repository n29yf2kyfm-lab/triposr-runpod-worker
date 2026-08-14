"""Content hash + perceptual hash for every image, cached to JSONL.

Split integrity in this corpus depends entirely on knowing which images are the
SAME PICTURE. Two separate mechanisms put copies in it:

  * EXACT duplicates. 22,318 files contain only ~13,758 distinct byte streams —
    38% of the corpus is the same file ingested twice under a different batch
    number (dent_major_rb20_..._0293c10a97.jpg and dent_major_rb21_...
    _0293c10a97.jpg are byte-identical). A SHA1 catches these.

  * AUGMENTED duplicates. Most of the corpus came in through a Roboflow export,
    which ships each source photograph several times with noise, brightness and
    flip augmentation already baked in. Those copies have DIFFERENT bytes and
    therefore different SHA1s, so a content hash alone declares them unrelated
    and a random split cheerfully puts variant 1 in train and variant 2 in test.
    A 1,800-image sample had only 1,323 distinct perceptual hashes: a quarter of
    it is augmented restatement of something already there.

So both hashes are computed, and the split groups on the perceptual one.

dHash rather than aHash or pHash: it compares each pixel with its right-hand
neighbour, so it keys on gradient structure and is close to immune to the
brightness/contrast/noise augmentation that is exactly what was applied here,
while staying an 8-byte integer that can be bucketed for near-neighbour search.
"""

import argparse
import hashlib
import json
import os
import sys

from PIL import Image

EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")


def dhash(path, size=8):
    """64-bit gradient hash. Returns int, or None if the file will not decode."""
    with Image.open(path) as im:
        im = im.convert("L").resize((size + 1, size), Image.LANCZOS)
        px = list(im.tobytes())
    bits = 0
    for r in range(size):
        row = r * (size + 1)
        for c in range(size):
            bits = (bits << 1) | (px[row + c] < px[row + c + 1])
    return bits


def sha1_of(path, buf=1 << 20):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--data", default="/home/user/drive_images")
    ap.add_argument("--out", default=os.path.join(here, "drive_hashes.jsonl"))
    args = ap.parse_args()

    done = set()
    if os.path.exists(args.out):
        with open(args.out) as f:
            for line in f:
                try:
                    done.add(json.loads(line)["path"])
                except Exception:
                    continue
    paths = []
    for root, _dirs, files in os.walk(args.data):
        for fn in sorted(files):
            if fn.lower().endswith(EXTS):
                p = os.path.join(root, fn)
                if p not in done:
                    paths.append(p)
    print(f"{len(done)} cached, {len(paths)} to hash", flush=True)

    with open(args.out, "a") as f:
        for i, p in enumerate(sorted(paths), 1):
            try:
                rec = {"path": p, "sha1": sha1_of(p), "dhash": dhash(p)}
            except Exception as e:
                rec = {"path": p, "sha1": None, "dhash": None,
                       "error": type(e).__name__}
            f.write(json.dumps(rec) + "\n")
            if i % 2000 == 0:
                f.flush()
                print(f"  ...{i}/{len(paths)}", flush=True)
    print(f"-> {args.out}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
