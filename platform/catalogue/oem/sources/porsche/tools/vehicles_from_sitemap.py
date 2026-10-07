#!/usr/bin/env python3
"""Merge porsche.oempartsonline.com vehicle sitemap(s) into ../vehicles.json.

    python3 vehicles_from_sitemap.py SAVED_FIRECRAWL_RESULT [...]

Each sitemap <loc> is a vehicle category page:
  /v-<year>-porsche-<model>--<trim>--<engine>/<category>
The vehicle is taken from the slug only (lower-case, '-' for spaces and
punctuation), so model/trim/engine are slug text de-hyphenated, not the dealer's
display capitalisation; the slug itself is kept in `slug`. Category slugs are
kept per vehicle as `categories`. The raw result file is deleted after parsing.
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'vehicles.json')
SLUG = re.compile(r'^v-(\d{4})-porsche-(.+)$')

def load():
    try:
        return {v['slug']: v for v in json.load(open(OUT))}
    except (OSError, ValueError):
        return {}

def main():
    veh = load()
    for f in sys.argv[1:]:
        d = json.load(open(f))
        raw = d['rawHtml']
        n = bad = 0
        for u in re.findall(r'<loc>([^<]+)</loc>', raw):
            parts = u.split('/')
            if len(parts) < 4 or not parts[3].startswith('v-'):
                continue
            slug = parts[3]
            cat = parts[4] if len(parts) > 4 else ''
            m = SLUG.match(slug)
            if not m:
                bad += 1
                continue
            year, rest = int(m.group(1)), m.group(2)
            fields = rest.split('--')
            model = fields[0].replace('-', ' ')
            trim = fields[1].replace('-', ' ') if len(fields) > 1 else ''
            engine = fields[2].replace('-', ' ') if len(fields) > 2 else ''
            v = veh.get(slug)
            if not v:
                v = veh[slug] = {'year': year, 'make': 'Porsche', 'model': model, 'trim': trim,
                                 'engine': engine, 'slug': slug,
                                 'url': 'https://porsche.oempartsonline.com/' + slug, 'categories': []}
                if len(fields) > 3:
                    v['slug_extra'] = '--'.join(fields[3:])
            if cat and cat not in v['categories']:
                v['categories'].append(cat)
            n += 1
        print(f'{d["metadata"].get("sourceURL")}: {n} locs, {bad} unparsed')
        os.remove(f)
    out = sorted(veh.values(), key=lambda v: (v['year'], v['model'], v['trim'], v['engine']))
    for v in out:
        v['categories'].sort()
    json.dump(out, open(OUT, 'w'), indent=0, separators=(',', ':'))
    print(len(out), 'vehicles in', OUT)

if __name__ == '__main__':
    main()
