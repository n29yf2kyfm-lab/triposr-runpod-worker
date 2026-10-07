#!/usr/bin/env python3
"""The Cars view's data: brand -> model -> generations, with trims and pictures.

    python3 platform/catalogue/oem/build_cars.py

Reads sources/models/models.json (every generation, from Wikipedia
infoboxes), cars/index.json (which AI picture exists and how it was made) and
group_vehicles.json (the dealer catalogues' own year/model/trim/engine rows),
and writes cars.json:

  [{brand, model, gens: [{name, code, years, body, pic, method, source,
                          trims: [[year, trim, engine], ...]}]}]

A generation's trims are the dealer rows for the same make whose model name
starts the generation's model name and whose year falls in its production
span. Nothing is invented: a generation with no dealer rows has no trims.
"""
import json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
sys_path = __import__('sys').path
sys_path.insert(0, HERE)
from car_images import slug   # noqa: E402

MAKE = {'Volkswagen Commercial Vehicles': 'Volkswagen'}
# a generation article's title minus its generation marker gives the model
GEN = re.compile(r'\s+(?:Mk\s?\d+|\([^)]*\)|[IVX]+|[A-Z]{1,2}\d{1,2}|\d(?:st|nd|rd|th) generation|Typ \w+)$', re.I)


def model_of(row):
    t = row['wikipedia_title']
    for _ in range(3):
        t = GEN.sub('', t)
    brand = MAKE.get(row['brand'], row['brand'])
    for prefix in (brand + ' ', 'Volkswagen ', 'Škoda ', 'Skoda ', 'SEAT ', 'Cupra '):
        if t.startswith(prefix):
            return t[len(prefix):].strip() or t
    return t


def norm(s):
    return re.sub(r'[^a-z0-9]+', ' ', (s or '').lower()).strip()


def main():
    rows = json.load(open(os.path.join(HERE, 'sources', 'models', 'models.json')))
    ip = os.path.join(HERE, 'cars', 'index.json')
    pics = json.load(open(ip)) if os.path.exists(ip) else {}
    vp = os.path.join(HERE, 'group_vehicles.json')
    dealer = json.load(open(vp)) if os.path.exists(vp) else []
    models = {}
    for r in rows:
        brand = MAKE.get(r['brand'], r['brand'])
        m = model_of(r)
        s = slug(r)
        trims = sorted({(v['year'], v.get('trim') or '', v.get('engine') or '') for v in dealer
                        if norm(v.get('make')) == norm(brand) and norm(v.get('model')).startswith(norm(m))
                        and r['years'][0] <= (v['year'] or 0) <= r['years'][1]})
        models.setdefault((brand, m), []).append({
            'name': r['generation'], 'code': r.get('code') or '', 'years': r['years'],
            'body': (r.get('body_styles') or [''])[0], 'pic': f'cars/{s}.webp' if s in pics else None,
            'method': pics.get(s, {}).get('method'), 'source': r['wikipedia_title'],
            'trims': [list(t) for t in trims]})
    out = []
    for (brand, m), gens in sorted(models.items()):
        gens.sort(key=lambda g: (-g['years'][0], g['name']))
        out.append({'brand': brand, 'model': m, 'gens': gens})
    json.dump(out, open(os.path.join(HERE, 'cars.json'), 'w'), separators=(',', ':'), ensure_ascii=False)
    nb = {}
    for c in out:
        nb.setdefault(c['brand'], [0, 0])
        nb[c['brand']][0] += 1; nb[c['brand']][1] += len(c['gens'])
    print('CARS', ', '.join(f'{b} {m} models / {g} generations' for b, (m, g) in nb.items()),
          f'| pictures {sum(1 for c in out for g in c["gens"] if g["pic"])}')


if __name__ == '__main__':
    main()
