#!/usr/bin/env python3
"""Ingest dealer PART pages (/oem-parts/...) fetched as raw HTML by Firecrawl.

    python3 platform/catalogue/oem/ingest_products.py TOOL_RESULTS_DIR [--keep]

A part page's schema.org Product block lists every VW the part fits, across
all models, years, trims and engines. That is one page per part instead of
hundreds of category pages per car. For each saved Firecrawl result whose
rawHtml is a part page, this writes products/<OEM>.json with: name, other
names, position, fitment notes, superseded numbers, category, diagram images
and callout, and the fitment list. Prices are NOT kept (owner's call,
2026-10-06). The raw result file (~500 KB) is deleted afterwards unless
--keep, so the disk does not fill.
"""
import glob, html, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'products')


def out_dir(url):
    """VW parts go to products/; every other Group brand's dealer site
    (audi., porsche., ... .oempartsonline.com) to sources/<brand>/products/.
    Routed by the URL's own host, so a file can never land under the wrong brand."""
    m = re.match(r'https?://([a-z0-9]+)\.oempartsonline\.com/', url)
    brand = m.group(1) if m else 'vw'
    d = OUT if brand == 'vw' else os.path.join(HERE, 'sources', brand, 'products')
    os.makedirs(d, exist_ok=True)
    return d


def parse(raw, url):
    prod = None
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', raw, re.S):
        try:
            d = json.loads(m.group(1))
        except ValueError:
            continue
        for o in d if isinstance(d, list) else [d]:
            if isinstance(o, dict) and o.get('@type') == 'Product':
                prod = o
    if not prod:
        return None
    props = {}
    for p in prod.get('additionalProperty') or []:
        props.setdefault(p.get('name'), p.get('value'))
    cat = prod.get('category') or ''
    segs = [s.strip() for s in cat.split('>')]
    master = next((i for i, s in enumerate(segs) if s.startswith('master_')), None)
    category = ' > '.join(segs[master + 1:]) if master is not None else ''
    fits = []
    for v in prod.get('isAccessoryOrSparePartFor') or []:
        fits.append([int(v.get('vehicleModelDate') or 0), v.get('model') or '',
                     v.get('vehicleConfiguration') or '', v.get('vehicleEngine') or ''])
    fits.sort(key=lambda f: (f[1], f[0], f[2], f[3]))
    imgs = [i.get('url') for i in prod.get('image') or [] if isinstance(i, dict) and 'illustrations' in (i.get('url') or '')]
    ref = re.search(r'reference #(\w+) in illustration', raw)
    sup = props.get('Superseded MPNs') or ''
    return {
        # from the URL: the schema.org mpn drops leading zeros (000071597d -> 71597d)
        'oem': url.rstrip('/').rsplit('-', 1)[1].upper(),
        'number': prod.get('productID') or '',
        'name': html.unescape(prod.get('name') or ''),
        'other_names': props.get('Other Names') or '',
        'position': props.get('Positions') or '',
        'fitment_notes': props.get('Fitment Notes') or '',
        'superseded': [s.strip().upper() for s in sup.split(',') if s.strip()],
        'category': category,
        'diagrams': imgs[:6],
        'callout': ref.group(1) if ref else None,
        'fits': fits,
        'url': url,
    }


def main():
    src = sys.argv[1]
    keep = '--keep' in sys.argv
    os.makedirs(OUT, exist_ok=True)
    n = bad = gone = 0
    for f in sorted(glob.glob(os.path.join(src, '*.txt')) + glob.glob(os.path.join(src, '*.json'))):
        try:
            d = json.load(open(f))
        except (ValueError, UnicodeDecodeError, OSError):   # OSError: another ingest took it first
            continue
        if not isinstance(d, dict) or 'rawHtml' not in d:
            continue
        meta = d.get('metadata') or {}
        url = meta.get('sourceURL') or ''
        if '/oem-parts/' not in url:
            continue
        if '/oem-parts/' not in (meta.get('url') or url):
            # the dealer redirects a part it no longer carries to the model list
            oem = url.rsplit('-', 1)[1].upper()
            json.dump({'oem': oem, 'gone': True, 'url': url}, open(os.path.join(out_dir(url), oem + '.json'), 'w'))
            gone += 1
            if not keep and os.path.exists(f):
                os.remove(f)
            continue
        p = parse(d['rawHtml'], url)
        if not p or not p['oem']:
            bad += 1
            print(f'PRODUCT unparsed {url}', flush=True)
            continue
        json.dump(p, open(os.path.join(out_dir(url), p['oem'] + '.json'), 'w'), separators=(',', ':'))
        n += 1
        if not keep and os.path.exists(f):
            os.remove(f)
    print(f'PRODUCTS +{n} ingested, {gone} no longer listed, {bad} unparsed; {len(os.listdir(OUT))} VW on disk', flush=True)


if __name__ == '__main__':
    main()
