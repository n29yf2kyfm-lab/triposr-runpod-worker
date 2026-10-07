#!/usr/bin/env python3
"""Merge every brand worker's vehicle list into one Group index.

    python3 platform/catalogue/oem/build_vehicles.py

Reads sources/<brand>/vehicles.json (each row {year, make, model, trim,
engine, url}, gathered from that brand's source, never typed in) and writes
group_vehicles.json, de-duplicated on (year, make, model, trim, engine) and
sorted, plus a coverage line per year: how many makes, models and trims the
sources list. Model years outside 1995-2026 are dropped. Images from
sources/images/images.json are attached per make + model where the image
worker found a free-licensed one.
"""
import glob, json, os, re
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))


def key(s):
    return re.sub(r'[^a-z0-9]+', ' ', (s or '').lower()).strip()


def main():
    rows = {}
    # trims.json (trim_pages.py: dealer year pages, display-cased names) is read first so its
    # spelling wins over slug-derived rows describing the same car.
    for f in (sorted(glob.glob(os.path.join(HERE, 'sources', '*', 'trims.json'))) +
              sorted(glob.glob(os.path.join(HERE, 'sources', '*', 'vehicles.json')))):
        try:
            data = json.load(open(f))
        except ValueError:
            print('VEHICLES unreadable (worker still writing?)', f)
            continue
        for v in data:
            y = int(v.get('year') or 0)
            if y and not 1995 <= y <= 2026:
                continue
            k = (y, key(v.get('make')), key(v.get('model')), key(v.get('trim')), key(v.get('engine')))
            rows.setdefault(k, {x: v.get(x) for x in ('year', 'make', 'model', 'trim', 'engine', 'url')})
    imgs = {}
    ip = os.path.join(HERE, 'sources', 'images', 'images.json')
    if os.path.exists(ip):
        try:
            for i in json.load(open(ip)):
                if i.get('thumb_800_url'):
                    imgs.setdefault((key(i.get('brand')), key(i.get('model'))), []).append(
                        {k: i.get(k) for k in ('generation', 'years', 'trim', 'thumb_800_url', 'file_page', 'licence', 'artist')})
        except ValueError:
            pass
    out = sorted(rows.values(), key=lambda v: (v['year'] or 0, v['make'] or '', v['model'] or '', v['trim'] or ''))
    json.dump(out, open(os.path.join(HERE, 'group_vehicles.json'), 'w'), separators=(',', ':'))
    json.dump({f'{b}|{m}': v for (b, m), v in imgs.items()}, open(os.path.join(HERE, 'group_images.json'), 'w'),
              separators=(',', ':'))
    per = defaultdict(lambda: [set(), set(), 0])
    for v in out:
        p = per[v['year']]
        p[0].add(v['make']); p[1].add((v['make'], v['model'])); p[2] += 1
    for y in sorted(per):
        m, mo, n = per[y]
        print(f'{y or "generation only"}: {len(m)} makes, {len(mo)} models, {n} trims')
    print(f'VEHICLES {len(out)} rows, images for {len(imgs)} make+model pairs')


if __name__ == '__main__':
    main()
