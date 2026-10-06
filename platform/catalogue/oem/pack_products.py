#!/usr/bin/env python3
"""Pack products/*.json into 64 bundles for the VW Parts Desk artifact.

    python3 platform/catalogue/oem/pack_products.py OUT_DIR

Writes OUT_DIR/prod/bNN.json, each mapping OEM number -> the part page's
detail (fitment rows with trims and engines, diagrams, callout). The page
fetches one bundle when a part is opened; the bucket is crc32(OEM) % 64, the
same as prodBucket() in catalogue.html. Derived files: rebuild before each
publish, never commit.
"""
import glob, json, os, sys, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
BUCKETS = 64


def main():
    out = os.path.join(sys.argv[1], 'prod')
    os.makedirs(out, exist_ok=True)
    packs = [dict() for _ in range(BUCKETS)]
    for f in glob.glob(os.path.join(HERE, 'products', '*.json')):
        d = json.load(open(f))
        packs[zlib.crc32(d['oem'].encode()) % BUCKETS][d['oem']] = {
            'fits': d['fits'], 'diagrams': d['diagrams'], 'callout': d['callout'], 'url': d['url']}
    total = 0
    for i, p in enumerate(packs):
        path = os.path.join(out, f'b{i:02d}.json')
        json.dump(p, open(path, 'w'), separators=(',', ':'))
        total += os.path.getsize(path)
    print(f'PACK {sum(map(len, packs))} part pages into {BUCKETS} bundles, {total // 1024} KB')


if __name__ == '__main__':
    main()
