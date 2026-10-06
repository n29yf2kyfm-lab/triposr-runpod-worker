#!/usr/bin/env python3
"""Print the next N part-page URLs still to fetch for full VW fitment.

    python3 platform/catalogue/oem/next_products.py N

Every part in the catalogue (crawled or from the sitemap) has a dealer part
page; this lists those with no products/<OEM>.json yet. Parts with no fitment
at all come first, then the crawled ones (which so far only have Golf-family
fitment). Within each group the order is a fixed hash shuffle, so coverage
spreads across all kinds of part instead of running alphabetically.
"""
import glob, json, os, sys, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
have = {os.path.basename(f)[:-5] for f in glob.glob(os.path.join(HERE, 'products', '*.json'))}
crawled = {p['oem']: p['source'] for p in json.load(open(os.path.join(HERE, 'parts.json')))}
more = {r[0]: 'https://vw.oempartsonline.com/oem-parts/volkswagen-' + r[5]
        for r in json.load(open(os.path.join(HERE, 'parts_more.json')))}
h = lambda k: zlib.crc32(k.encode())
todo = sorted((k for k in more if k not in have), key=h) + sorted((k for k in crawled if k not in have), key=h)
print(len(todo), 'part pages left')
for k in todo[:int(sys.argv[1]) if len(sys.argv) > 1 else 10]:
    print(more.get(k) or crawled[k])
