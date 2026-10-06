#!/usr/bin/env python3
"""Pack the part illustrations into a few bundles for the Parts Desk artifact.

    python3 platform/catalogue/oem/pack_pictures.py OUT_DIR

An artifact version holds at most 511 files, and the catalogue has more
part-type pictures than that. This writes OUT_DIR/pics/bNN.json — 32 bundles,
each mapping an illustration key to a 384 px WebP data URI. catalogue.html
picks a bundle with the same hash (picBucket) and loads it only when a card
from that bundle scrolls into view. The bundles are derived files: rebuild them
before each publish, never edit them.
"""
import base64, glob, io, json, os, sys, zlib

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
BUCKETS = 32
SIZE = 384


def bucket(key):
    # must match picBucket() in catalogue.html: crc32 of the key, mod BUCKETS
    return zlib.crc32(key.encode()) % BUCKETS


def main():
    out = os.path.join(sys.argv[1], 'pics')
    os.makedirs(out, exist_ok=True)
    packs = [dict() for _ in range(BUCKETS)]
    for f in sorted(glob.glob(os.path.join(HERE, 'illustrations', '*.webp'))):
        key = os.path.basename(f)[:-5]
        im = Image.open(f).convert('RGB').resize((SIZE, SIZE), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, 'WEBP', quality=78, method=6)
        packs[bucket(key)][key] = 'data:image/webp;base64,' + base64.b64encode(buf.getvalue()).decode()
    total = 0
    for i, p in enumerate(packs):
        path = os.path.join(out, f'b{i:02d}.json')
        json.dump(p, open(path, 'w'), separators=(',', ':'))
        total += os.path.getsize(path)
    print(f'PACK {sum(map(len, packs))} pictures into {BUCKETS} bundles, {total // 1024} KB')


if __name__ == '__main__':
    main()
