#!/usr/bin/env python3
"""Build sources/audi/vehicles.json from audi.oempartsonline.com model pages.

    python3 vehicles.py ingest DIR   # parse saved Firecrawl rawHtml results of
                                     # /v-audi-<model> and /v-YYYY-audi-<model>
                                     # pages found in DIR, then delete them
    python3 vehicles.py next         # print the next page to fetch
    python3 vehicles.py build        # write vehicles.json + per-year counts

Model slugs come from sitemaps/models_sitemap.xml (models.txt). A model page
lists its years; a year-model page lists every trim + engine as links
/v-YYYY-audi-<model>--<trim>--<engine>. Only years 1995-2026 are followed.
Everything is read from the fetched pages; nothing is inferred.
"""
import glob, html, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BRAND = os.path.dirname(HERE)
STATE = os.path.join(HERE, 'vehicle_pages.json')
HOST = 'https://audi.oempartsonline.com/'
Y0, Y1 = 1995, 2026


def load():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {'models': {}, 'years': {}}   # models[slug] = [years] ; years[yslug] = [[text,url],...]


def save(s):
    json.dump(s, open(STATE, 'w'), indent=0, sort_keys=True)


def model_slugs():
    ms = [l.strip() for l in open(os.path.join(HERE, 'models.txt')) if l.strip() and not l.startswith('#')]
    return ms + [m for m in load().get('brand_models', []) if m not in ms]


def anchors(raw):
    for m in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', raw, re.S):
        href = html.unescape(m.group(1)).strip()
        if href.startswith('/'):
            href = HOST + href[1:]
        text = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', m.group(2)))).strip()
        yield href.split('?')[0].split('#')[0].rstrip('/'), text


def ingest(d):
    s = load()
    n = 0
    for f in glob.glob(os.path.join(d, '*.txt')) + glob.glob(os.path.join(d, '*.json')):
        try:
            j = json.load(open(f))
        except (ValueError, UnicodeDecodeError, OSError):
            continue
        if not isinstance(j, dict) or 'rawHtml' not in j:
            continue
        meta = j.get('metadata') or {}
        url = (meta.get('sourceURL') or '').rstrip('/')
        if url == HOST + 'v-audi':          # brand page: every model it links
            s['brand_models'] = sorted({a[len(HOST) + 7:] for a, _ in anchors(j['rawHtml'])
                                        if re.fullmatch(re.escape(HOST) + r'v-audi-[a-z0-9-]+', a)})
            n += 1; os.remove(f); continue
        m1 = re.fullmatch(re.escape(HOST) + r'v-audi-([a-z0-9-]+)', url)
        m2 = re.fullmatch(re.escape(HOST) + r'v-(\d{4})-audi-([a-z0-9-]+)', url)
        if not (m1 or m2) or '--' in url:
            continue
        raw = j['rawHtml']
        if m1:
            slug = m1.group(1)
            ys = sorted({int(a.rsplit('/', 1)[1][2:6]) for a, _ in anchors(raw)
                         if re.fullmatch(re.escape(HOST) + r'v-\d{4}-audi-' + re.escape(slug), a)})
            s['models'][slug] = ys
        else:
            yslug = url[len(HOST):]
            rows = {}
            for a, t in anchors(raw):
                if re.fullmatch(re.escape(HOST) + re.escape(yslug) + r'--[a-z0-9-]+--[a-z0-9-]+', a) and t:
                    rows[a] = t
            s['years'][yslug] = sorted([t, a] for a, t in rows.items())
        n += 1
        os.remove(f)
    save(s)
    print(f'VEHICLES ingested {n} pages; models {len(s["models"])}/{len(model_slugs())}, '
          f'year pages {len(s["years"])}/{len(queue_years(s))}')


def queue_years(s):
    q = []
    for slug, ys in s['models'].items():
        q += [f'v-{y}-audi-{slug}' for y in ys if Y0 <= y <= Y1]
    return q


def nxt():
    s = load()
    if 'brand_models' not in s:
        print(HOST + 'v-audi'); return
    for slug in model_slugs():
        if slug not in s['models']:
            print(HOST + 'v-audi-' + slug); return
    for y in sorted(queue_years(s)):
        if y not in s['years']:
            print(HOST + y); return
    print('DONE')


def split(text, url):
    # link text is "<Trim> <Engine> - <Fuel>", e.g. "Premium Plus 2.0L L4 - Gas"
    m = re.fullmatch(r'(.*?)\s*(\d+(?:\.\d+)?L\b.*?)\s*-\s*(\S.*)', text)
    if m:
        return m.group(1).strip(), f'{m.group(2).strip()} {m.group(3).strip()}'
    m = re.fullmatch(r'(.*?)\s*-\s*(\S.*)', text)          # no displacement (electric)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return text, ''


def build():
    s = load()
    out = []
    for yslug, rows in s['years'].items():
        y = int(yslug[2:6])
        model_slug = yslug[len('v-0000-audi-'):]
        for text, url in rows:
            trim, engine = split(text, url)
            out.append({'year': y, 'make': 'Audi', 'model': model_slug, 'trim': trim,
                        'engine': engine, 'link_text': text, 'url': url})
    out.sort(key=lambda v: (v['year'], v['model'], v['trim'], v['engine']))
    json.dump(out, open(os.path.join(BRAND, 'vehicles.json'), 'w'), indent=1)
    per = {}
    for v in out:
        per.setdefault(v['year'], set()).add(v['model'])
    empty = [k for k, r in s['years'].items() if not r]
    print(f'{len(out)} vehicles; year pages with no trim links: {len(empty)} {empty[:10]}')
    for y in sorted(per):
        print(y, len(per[y]), 'models', sum(1 for v in out if v['year'] == y), 'trims')


if __name__ == '__main__':
    {'ingest': lambda: ingest(sys.argv[2]), 'next': nxt, 'build': build}[sys.argv[1]]()
