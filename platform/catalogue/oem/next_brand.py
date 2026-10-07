#!/usr/bin/env python3
"""Print the next N part-page URLs to fetch for one VW Group brand.

    python3 platform/catalogue/oem/next_brand.py BRAND [N]

Reads sources/<brand>/sitemap_parts.txt (one dealer part-page URL per line,
'#' lines are comments) and lists those with no
sources/<brand>/products/<OEM>.json yet, in a fixed hash order so coverage
spreads across every kind of part. The OEM number is the last '-' field of
the URL, upper-cased, exactly as ingest_products.py keys it.
"""
import os, sys, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
brand = sys.argv[1]
src = os.path.join(HERE, 'sources', brand)
pdir = os.path.join(src, 'products')
have = {f[:-5] for f in os.listdir(pdir)} if os.path.isdir(pdir) else set()
urls = {}
for line in open(os.path.join(src, 'sitemap_parts.txt')):
    u = line.strip()
    if u and not u.startswith('#'):
        urls.setdefault(u.rstrip('/').rsplit('-', 1)[1].upper(), u)
todo = sorted((k for k in urls if k not in have), key=lambda k: zlib.crc32(k.encode()))
print(len(todo), 'of', len(urls), brand, 'part pages left')
for k in todo[:int(sys.argv[2]) if len(sys.argv) > 2 else 10]:
    print(urls[k])
