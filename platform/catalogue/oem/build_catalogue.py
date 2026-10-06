#!/usr/bin/env python3
"""Build the OEM parts catalogue from parsed dealer pages.

    python3 platform/catalogue/oem/build_catalogue.py

Reads pages/<vehicle-slug>/<category>.json (written by parse_revolution.py)
and writes, next to this file:

  vehicles.json  one entry per vehicle: year, make, model, trim, engine, slug
  parts.json     one entry per OEM number: name, part type, system, price,
                 every vehicle/category/drawing/callout it appears on, notes,
                 source links, and its illustration (if generated)
  parts.csv      the same, flattened, one row per OEM number

OEM numbers are copied from the dealer page, never generated. Prices are US
dealer prices on the day crawled. Illustrations are AI-made, one per PART
TYPE, and are labelled as illustrations wherever shown.
"""
import csv, glob, json, os, re

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
                'price_usd': p.get('price_usd'), 'unavailable': p.get('unavailable', False),
                'appears_on': [], 'notes': set(), 'source': p['url'], 'illustration': None})
            d = dia.get(p.get('diagram')) or {}
            e['appears_on'].append({'vehicle': slug, 'category': cat, 'diagram': p.get('diagram'),
                                    'diagram_name': d.get('name'), 'diagram_image': d.get('image'),
                                    'callout': p.get('callout')})
            if p.get('notes'):
                e['notes'].add(p['notes'])
            if e['price_usd'] is None and p.get('price_usd') is not None:
                e['price_usd'] = p['price_usd']
    img_dir = os.path.join(HERE, 'illustrations')
    for e in parts.values():
        e['notes'] = sorted(e['notes'])
        key = illustration_key(e['part_type'])
        if os.path.exists(os.path.join(img_dir, key + '.webp')):
            e['illustration'] = f'illustrations/{key}.webp'
    out = sorted(parts.values(), key=lambda e: (e['system'], e['part_type'], e['oem']))
    json.dump(sorted(vehicles.values(), key=lambda v: v['slug']), open(os.path.join(HERE, 'vehicles.json'), 'w'), indent=1)
    json.dump(out, open(os.path.join(HERE, 'parts.json'), 'w'), indent=1)
    with open(os.path.join(HERE, 'parts.csv'), 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['oem', 'oem_display', 'name', 'part_type', 'system', 'price_usd', 'unavailable',
                    'vehicles', 'drawing_callouts', 'notes', 'illustration', 'source'])
        for e in out:
            w.writerow([e['oem'], e['oem_display'], e['name'], e['part_type'], e['system'], e['price_usd'],
                        e['unavailable'], ' | '.join(sorted({a['vehicle'] for a in e['appears_on']})),
                        ' | '.join(f"{a['diagram_name'] or a['category']} #{a['callout']}" for a in e['appears_on']),
                        ' / '.join(e['notes'])[:500], e['illustration'] or '', e['source']])
    types = sorted({e['part_type'] for e in out})
    print(f'CATALOGUE {len(vehicles)} vehicles, {len(out)} OEM numbers, {len(types)} part types, '
          f'{sum(1 for e in out if e["illustration"])} illustrated')
    return 0


if __name__ == '__main__':
    sys.exit(main())
