#!/usr/bin/env python3
"""Porsche vehicles.json from the dealer's year and model pages.

    python3 vehicle_pages.py next            # print next year/model page to fetch
    python3 vehicle_pages.py ingest FILE...  # parse saved Firecrawl rawHtml results

Year page  /v-<year>-porsche          -> links to model pages /v-<year>-porsche-<model>
Model page /v-<year>-porsche-<model>  -> one link per trim+engine, anchor text e.g.
           "Carrera 4S 3.0L H6 - Gas", href /v-2020-porsche-911--carrera-4s--3-0l-h6-gas
The trim/engine split of the anchor text is decided by the href slug (the
shortest word prefix whose slug equals the trim slug). The model display name is
the model page's <h1>. State (pages fetched/queued) is kept in
../vehicle_pages_state.json. Raw result files are deleted after parsing.
"""
import html, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'vehicles.json')
STATE = os.path.join(HERE, '..', 'vehicle_pages_state.json')
BASE = 'https://porsche.oempartsonline.com/'

def slugify(s):
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')

def load(p, default):
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return default

def state():
    s = load(STATE, None)
    if s is None:
        s = {'todo': [BASE + f'v-{y}-porsche' for y in range(1995, 2027)], 'done': {}}
    return s

def save(s, veh):
    json.dump(s, open(STATE, 'w'), indent=0)
    out = sorted(veh.values(), key=lambda v: (v['year'], v['model'], v['trim'], v['engine']))
    json.dump(out, open(OUT, 'w'), indent=0, separators=(',', ':'))

def text(h):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', h))).strip()

def ingest(files):
    s = state()
    veh = {v['slug']: v for v in load(OUT, [])}
    for f in files:
        d = json.load(open(f))
        url = (d['metadata'].get('sourceURL') or '').rstrip('/')
        final = (d['metadata'].get('url') or url).rstrip('/')
        raw = d['rawHtml']
        path = url[len(BASE):]
        m_year = re.fullmatch(r'v-(\d{4})-porsche', path)
        m_model = re.fullmatch(r'v-(\d{4})-porsche-([a-z0-9-]+)', path)
        note = ''
        if final != url:
            note = f'redirected to {final}'
        elif m_year:
            links = sorted(set(re.findall(r'href="(' + re.escape(BASE + path) + r'-[a-z0-9-]+)"', raw)))
            links = [l for l in links if '--' not in l[len(BASE):]]
            for l in links:
                if l not in s['done'] and l not in s['todo']:
                    s['todo'].append(l)
            note = f'{len(links)} model pages'
        elif m_model:
            year = int(m_model.group(1))
            h1 = re.search(r'page_heading">(.*?)</h1>', raw, re.S)
            title = text(h1.group(1)) if h1 else ''
            mm = re.fullmatch(rf'{year} Porsche (.+?) Trims & Engines', title)
            model = mm.group(1) if mm else m_model.group(2).replace('-', ' ')
            n = 0
            for a in re.finditer(r'<a href="(' + re.escape(BASE + path) + r'--[^"]+)">(.*?)</a>', raw, re.S):
                href, label = a.group(1), text(a.group(2))
                slug = href[len(BASE):]
                parts = slug[len(path) + 2:].split('--')
                tslug = parts[0]
                words = label.split(' ')
                trim, engine = None, label
                for i in range(1, len(words)):
                    if slugify(' '.join(words[:i])) == tslug:
                        trim, engine = ' '.join(words[:i]), ' '.join(words[i:])
                        break
                v = veh.get(slug) or {}
                v.update({'year': year, 'make': 'Porsche', 'model': model,
                          'trim': trim if trim is not None else tslug.replace('-', ' '),
                          'engine': engine if trim is not None else '--'.join(parts[1:]).replace('-', ' '),
                          'label': label, 'slug': slug, 'url': href, 'source': BASE + path})
                v.setdefault('categories', [])
                if trim is None:
                    v['split_unverified'] = True
                veh[slug] = v
                n += 1
            note = f'{n} trims ({model})'
        else:
            note = 'not a year/model page'
        s['done'][url] = note
        if url in s['todo']:
            s['todo'].remove(url)
        print(url, '->', note)
        os.remove(f)
    save(s, veh)
    print(len(s['done']), 'pages done,', len(s['todo']), 'queued,', len(veh), 'vehicles')

if __name__ == '__main__':
    if sys.argv[1] == 'next':
        s = state()
        print(s['todo'][0] if s['todo'] else 'DONE')
    else:
        ingest(sys.argv[2:])
