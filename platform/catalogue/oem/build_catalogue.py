#!/usr/bin/env python3
"""Build the OEM parts catalogue from parsed dealer pages.

    python3 platform/catalogue/oem/build_catalogue.py

Reads pages/<vehicle-slug>/<category>.json (written by parse_revolution.py)
and writes, next to this file:

  vehicles.json  one entry per vehicle: year, make, model, trim, engine, slug
  parts.json     one entry per OEM number: name, part type, system,
                 every vehicle/category/drawing/callout it appears on, notes,
                 source links, and its illustration (if generated)
  parts.csv      the same, flattened, one row per OEM number

OEM numbers are copied from the dealer page, never generated. Prices are
left out of every output on purpose (owner's call, 2026-10-06); the raw
pages/ keep them only as crawled source data. Illustrations are AI-made, one per PART
TYPE, and are labelled as illustrations wherever shown.
"""
import csv, glob, json, os, re
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.insert(0, HERE)
from parse_revolution import vw_display   # noqa: E402
from illustrate import illustration_key     # noqa: E402

# words that say WHERE a part goes, not WHAT it is — stripped to get its type
WHERE = r'\b(front|rear|left|right|upper|lower|inner|outer|driver|passenger|lh|rh|side|center|centre)\b'


def vehicle(slug):
    """v-2019-volkswagen-golf--s--1-4l-l4-gas -> year, make, model, trim, engine."""
    m = re.match(r'v-(\d{4})-([a-z]+)-(.+?)--(.+?)--(.+)$', slug)
    if not m:
        return {'slug': slug}
    year, make, model, trim, eng = m.groups()
    e = re.match(r'(\d+)-(\d+)l-([a-z]+\d+)-(.+)$', eng)
    engine = f'{e.group(1)}.{e.group(2)}L {e.group(3).upper()} {e.group(4)}' if e else eng
    nice = lambda s: ' '.join(w.upper() if len(w) <= 3 and w not in ('gas',) else w.title() for w in s.split('-'))
    return {'slug': slug, 'year': int(year), 'make': make.title().replace('Volkswagen', 'Volkswagen'),
            'model': nice(model), 'trim': nice(trim), 'engine': engine, 'market': 'US'}


# one dealer catalogue per Group brand; VW keeps its original top-level paths
PREFIX = {'vw': 'volkswagen-', 'audi': 'audi-', 'porsche': 'porsche-', 'bentley': 'bentley-',
          'lamborghini': 'lamborghini-'}
BRAND_NAME = {'vw': 'Volkswagen', 'audi': 'Audi', 'porsche': 'Porsche', 'bentley': 'Bentley',
              'lamborghini': 'Lamborghini', 'seat': 'SEAT', 'skoda': 'Skoda', 'cupra': 'Cupra'}


def brand_sources():
    """(brand, sitemap list, products dir) for VW and every sources/<brand>/."""
    out = [('vw', os.path.join(HERE, 'sitemap_parts.txt'), os.path.join(HERE, 'products'))]
    for d in sorted(glob.glob(os.path.join(HERE, 'sources', '*', ''))):
        b = os.path.basename(d.rstrip('/'))
        out.append((b, os.path.join(d, 'sitemap_parts.txt'), os.path.join(d, 'products')))
    return out


def part_type(name):
    t = re.sub(WHERE, ' ', name.lower())
    t = re.sub(r'\b(assembly|assy|kit|set)\b', ' ', t)
    t = re.sub(r'[^a-z0-9 &]+', ' ', t)
    return re.sub(r'\s+', ' ', t).strip() or name.lower()


def main():
    vehicles, parts = {}, {}
    for f in sorted(glob.glob(os.path.join(HERE, 'pages', '*', '*.json'))):
        slug = os.path.basename(os.path.dirname(f))
        cat = os.path.basename(f)[:-5]
        system, _, sub = cat.partition('--')
        v = vehicles.setdefault(slug, vehicle(slug))
        pg = json.load(open(f))
        dia = {d['n']: d for d in pg.get('diagrams', [])}
        for p in pg['parts']:
            e = parts.setdefault(p['oem'], {
                'oem': p['oem'], 'oem_display': vw_display(p['oem']), 'name': p['name'],
                'part_type': part_type(p['name']), 'system': system.replace('-', ' '),
                'unavailable': p.get('unavailable', False),
                'appears_on': [], 'notes': set(), 'source': p['url'], 'illustration': None, 'brands': {'vw'}})
            d = dia.get(p.get('diagram')) or {}
            e['appears_on'].append({'vehicle': slug, 'category': cat, 'diagram': p.get('diagram'),
                                    'diagram_name': d.get('name'), 'diagram_image': d.get('image'),
                                    'callout': p.get('callout')})
            if p.get('notes') and 'price' not in p['notes'].lower():   # no prices anywhere in the outputs
                e['notes'].add(p['notes'])
    crawled = len(parts)
    # Every VW part the dealer's 2021 sitemap lists (all models). Number and
    # name come straight from the part's URL; which cars it fits is unknown
    # until a category page containing it is crawled, so appears_on stays empty.
    by_type = {}
    for e in parts.values():
        by_type.setdefault(e['part_type'], Counter())[e['system']] += 1
    for brand, sm, pdir in brand_sources():
        if not os.path.exists(sm):
            continue
        for line in open(sm):
            if not line.startswith('http'):
                continue
            url = line.strip()
            slug = url.rsplit('/oem-parts/', 1)[1]
            slug = slug[len(PREFIX[brand]):] if slug.startswith(PREFIX.get(brand, '\0')) else slug.split('-', 1)[1]
            words, num = slug.rsplit('-', 1)
            oem = num.upper()
            if oem in parts:
                parts[oem]['brands'].add(brand)
                continue
            name = re.sub(r'\bA C\b', 'A/C', words.replace('-', ' ').title())
            pt = part_type(name)
            guess = by_type.get(pt)
            parts[oem] = {'oem': oem, 'oem_display': vw_display(oem), 'name': name, 'part_type': pt,
                          'system': guess.most_common(1)[0][0] if guess else 'not yet sorted',
                          'system_guessed': True, 'unavailable': False, 'appears_on': [], 'notes': set(),
                          'source': url, 'illustration': None, 'brands': {brand}}
    # Part pages (ingest_products.py): full fitment and the dealer's details,
    # from every brand's dealer site. One entry per OEM number however many
    # brands list it (VW Group brands share one numbering system): fitment is
    # merged, and models from brands other than VW carry the make ("Audi Q7").
    for brand, sm, pdir in brand_sources():
        for f in glob.glob(os.path.join(pdir, '*.json')):
            d = json.load(open(f))
            e = parts.get(d['oem'])
            if not e:
                continue
            e['brands'].add(brand)
            if d.get('gone'):
                e.setdefault('gone_on', set()).add(brand)
                continue
            rng = {m: (lo, hi) for m, lo, hi in e.get('fits', [])}
            for y, model, cfg, eng in d['fits']:
                if brand != 'vw':
                    model = f'{BRAND_NAME[brand]} {model}'
                lo, hi = rng.get(model, (y, y))
                rng[model] = (min(lo, y), max(hi, y))
            e['fits'] = sorted([m, lo, hi] for m, (lo, hi) in rng.items())
            e['detail'] = True
            for k in ('other_names', 'position', 'fitment_notes'):
                if d.get(k) and not e.get(k):
                    e[k] = d[k]
            if d.get('superseded'):
                e['superseded'] = sorted(set(e.get('superseded', [])) | set(d['superseded']))
            if d.get('category') and not e.get('category'):
                e['category'] = d['category']
                if e.get('system_guessed'):
                    e['system'] = d['category'].split(' > ')[0].lower()
                    e['system_guessed'] = False
    for e in parts.values():
        # gone only when every brand site that has a page for it dropped it
        if e.get('gone_on') and not e.get('detail'):
            e['dealer_gone'] = True
        e.pop('gone_on', None)
        e['brands'] = sorted(e['brands'])
    img_dir = os.path.join(HERE, 'illustrations')
    for e in parts.values():
        e['notes'] = sorted(e['notes'])
        key = illustration_key(e['part_type'])
        if os.path.exists(os.path.join(img_dir, key + '.webp')):
            e['illustration'] = f'illustrations/{key}.webp'
    out = sorted(parts.values(), key=lambda e: (e['system'], e['part_type'], e['oem']))
    json.dump(sorted(vehicles.values(), key=lambda v: v['slug']), open(os.path.join(HERE, 'vehicles.json'), 'w'), indent=1)
    # parts.json: parts with crawled fitment, full records. parts_more.json: the
    # sitemap-only parts as compact rows [oem, display, name, part_type, system,
    # url slug, illustration] so the page stays light enough for a phone.
    compact = lambda e: not e['appears_on'] and not e.get('detail') and not e.get('dealer_gone')
    json.dump([e for e in out if not compact(e)], open(os.path.join(HERE, 'parts.json'), 'w'),
              separators=(',', ':'))
    pre = 'https://vw.oempartsonline.com/oem-parts/volkswagen-'
    json.dump([[e['oem'], e['oem_display'], e['name'], e['part_type'], e['system'],
                e['source'][len(pre):] if e['source'].startswith(pre) else e['source'],
                e['illustration'] or '', ','.join(e['brands'])] for e in out if compact(e)],
              open(os.path.join(HERE, 'parts_more.json'), 'w'), separators=(',', ':'))
    with open(os.path.join(HERE, 'parts.csv'), 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['oem', 'oem_display', 'name', 'part_type', 'system', 'brands', 'unavailable',
                    'vehicles', 'fits_all_group', 'drawing_callouts', 'notes', 'illustration', 'source'])
        for e in out:
            w.writerow([e['oem'], e['oem_display'], e['name'], e['part_type'], e['system'],
                        ' '.join(e['brands']), e['unavailable'], ' | '.join(sorted({a['vehicle'] for a in e['appears_on']})),
                        ' | '.join(f'{m} {lo}-{hi}' if lo != hi else f'{m} {lo}' for m, lo, hi in e.get('fits', [])),
                        ' | '.join(f"{a['diagram_name'] or a['category']} #{a['callout']}" for a in e['appears_on']),
                        ' / '.join(e['notes'])[:500], e['illustration'] or '', e['source']])
    types = sorted({e['part_type'] for e in out})
    nfit = sum(1 for e in out if e['appears_on'] or e.get('detail'))
    bc = Counter(b for e in out for b in e['brands'])
    print(f'CATALOGUE {len(out)} OEM numbers ({", ".join(f"{b} {n}" for b, n in sorted(bc.items()))}), {nfit} with fitment ({sum(1 for e in out if e.get("detail"))} from part pages), '
          f'{len(types)} part types, '
          f'{sum(1 for e in out if e["illustration"])} illustrated')
    return 0


if __name__ == '__main__':
    sys.exit(main())
