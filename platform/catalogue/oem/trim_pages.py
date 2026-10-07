#!/usr/bin/env python3
"""Every trim and engine, 1995-2026, from the US dealer sites' vehicle pages.

    python3 trim_pages.py next BRAND [N]   # print the next N pages to fetch (rawHtml)
    python3 trim_pages.py ingest           # parse every saved Firecrawl result for any brand
    python3 trim_pages.py build            # write sources/<brand>/trims.json and print coverage

BRAND is vw, audi or porsche (all RevolutionParts sites with the same layout):
  /v-<make>                    brand page   -> one link per model   /v-<make>-<model>
  /v-<make>-<model>            model page   -> one link per year    /v-<year>-<make>-<model>
  /v-<year>-<make>-<model>     year page    -> one link per trim    /v-<year>-<make>-<model>--<trim>--<engine>
The trim link text is "<Trim> <Engine> - <Fuel>". Everything comes from fetched
pages; nothing is inferred. State is sources/<brand>/trim_pages.json. Raw
Firecrawl results are deleted once parsed. US-market data only.
"""
import glob, html, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
TR = '/root/.claude/projects/-home-user-triposr-runpod-worker/34795087-6986-5aae-b59f-cce8aae2f506/tool-results'
BRANDS = {'vw': ('https://vw.oempartsonline.com/', 'volkswagen', 'Volkswagen'),
          'audi': ('https://audi.oempartsonline.com/', 'audi', 'Audi'),
          'porsche': ('https://porsche.oempartsonline.com/', 'porsche', 'Porsche')}
Y0, Y1 = 1995, 2026
# US model lines that ended before 1995: their model pages are not fetched (it saves
# calls only; nothing is recorded for them, so no data is assumed).
SKIP = {'vw': {'quantum', 'vanagon', 'scirocco', 'corrado'},
        'audi': {'4000-quattro', '5000', '5000-quattro', 'quattro'},
        'porsche': {'924', '944'}}


def spath(b):
    return os.path.join(HERE, 'sources', b, 'trim_pages.json')


def load(b):
    try:
        return json.load(open(spath(b)))
    except (OSError, ValueError):
        return {'models': None, 'years': {}, 'model_years': {}, 'names': {}}


def save(b, s):
    os.makedirs(os.path.dirname(spath(b)), exist_ok=True)
    json.dump(s, open(spath(b), 'w'), indent=0, sort_keys=True)


def anchors(host, raw):
    for m in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', raw, re.S):
        href = html.unescape(m.group(1)).strip()
        if href.startswith('/'):
            href = host + href[1:]
        text = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', m.group(2)))).strip()
        yield href.split('?')[0].split('#')[0].rstrip('/'), text


def ingest():
    n = 0
    for f in glob.glob(os.path.join(TR, 'mcp-Firecrawl-firecrawl_scrape-*.txt')):
        try:
            j = json.load(open(f))
        except (ValueError, UnicodeDecodeError, OSError):
            continue
        if not isinstance(j, dict) or 'rawHtml' not in j:
            continue
        url = ((j.get('metadata') or {}).get('sourceURL') or '').rstrip('/')
        for b, (host, mk, _) in BRANDS.items():
            if not url.startswith(host):
                continue
            path = url[len(host):]
            brand_page = path == f'v-{mk}'
            m1 = re.fullmatch(rf'v-{mk}-([a-z0-9-]+)', path)
            m2 = re.fullmatch(rf'v-(\d{{4}})-{mk}-([a-z0-9-]+)', path)
            if not (brand_page or m1 or m2) or '--' in path:
                break
            s, raw = load(b), j['rawHtml']
            links = list(anchors(host, raw))
            if brand_page:
                s['models'] = sorted({a[len(host) + len(mk) + 3:] for a, t in links
                                      if re.fullmatch(re.escape(host) + rf'v-{mk}-[a-z0-9-]+', a)})
                for a, t in links:
                    if re.fullmatch(re.escape(host) + rf'v-{mk}-[a-z0-9-]+', a) and t:
                        s['names'][a[len(host) + len(mk) + 3:]] = t
            elif m1:
                slug = m1.group(1)
                s['model_years'][slug] = sorted({int(a[len(host) + 2:len(host) + 6]) for a, _ in links
                                                 if re.fullmatch(re.escape(host) + rf'v-\d{{4}}-{mk}-' + re.escape(slug), a)})
            else:
                rows = {a: t for a, t in links if t and re.fullmatch(
                    re.escape(host) + re.escape(path) + r'--[a-z0-9-]+--[a-z0-9-]+', a)}
                final = ((j.get('metadata') or {}).get('url') or '').rstrip('/')
                m3 = re.fullmatch(re.escape(host) + re.escape(path) + r'--([a-z0-9-]+)--([a-z0-9-]+)', final)
                if m3:
                    # a year with one trim redirects straight to that trim's page; the label
                    # is rebuilt from the URL slug (e.g. base / 2-5l-l5-gas -> "Base 2.5L L5 - Gas")
                    eng = re.sub(r'(\d)-(\d)l', r'\1.\2l', m3.group(2)).split('-')
                    fuel = eng.pop() if eng else ''
                    label = (' '.join(w.capitalize() for w in m3.group(1).split('-')) + ' ' +
                             ' '.join(w.upper() for w in eng) + ' - ' + fuel.capitalize())
                    rows = {final: label}
                s['years'][path] = sorted([t, a] for a, t in rows.items())
            save(b, s)
            os.remove(f)
            n += 1
            break
    print(f'TRIMS ingested {n} pages')


def queue(b):
    host, mk, _ = BRANDS[b]
    s = load(b)
    if s['models'] is None:
        return [host + f'v-{mk}']
    q = [host + f'v-{mk}-{m}' for m in s['models'] if m not in s['model_years'] and m not in SKIP[b]]
    for m, ys in sorted(s['model_years'].items()):
        q += [host + f'v-{y}-{mk}-{m}' for y in ys if Y0 <= y <= Y1 and f'v-{y}-{mk}-{m}' not in s['years']]
    return q


def split(text):
    m = re.fullmatch(r'(.*?)\s*(\d+(?:\.\d+)?L\b.*?)\s*-\s*(\S.*)', text)
    if m:
        return m.group(1).strip(), f'{m.group(2).strip()} {m.group(3).strip()}'
    m = re.fullmatch(r'(.*?)\s*-\s*(\S.*)', text)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return text, ''


def build():
    for b, (host, mk, make) in BRANDS.items():
        s = load(b)
        out = []
        for path, rows in s['years'].items():
            y = int(path[2:6])
            slug = path[len(f'v-0000-{mk}-'):]
            name = s['names'].get(slug, slug.replace('-', ' ').title())
            if name.lower().startswith(make.lower() + ' '):
                name = name[len(make) + 1:]
            for text, url in rows:
                trim, engine = split(text)
                out.append({'year': y, 'make': make, 'model': name, 'trim': trim or 'Base',
                            'engine': engine, 'market': 'US', 'url': url})
        out.sort(key=lambda v: (v['year'], v['model'], v['trim'], v['engine']))
        if out or os.path.exists(spath(b)):
            json.dump(out, open(os.path.join(HERE, 'sources', b, 'trims.json'), 'w'), indent=0)
        print(f'{b}: {len(out)} trims, {len({(v["year"], v["model"]) for v in out})} year-models, '
              f'queue {len(queue(b))}')


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'next':
        for u in queue(sys.argv[2])[:int(sys.argv[3]) if len(sys.argv) > 3 else 1]:
            print(u)
    else:
        {'ingest': ingest, 'build': build}[cmd]()
