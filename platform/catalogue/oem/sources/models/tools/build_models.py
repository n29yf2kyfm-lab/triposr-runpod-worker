#!/usr/bin/env python3
"""Every VW Group model and generation, 1995-2026, from Wikidata + Wikipedia.

    python3 platform/catalogue/oem/sources/models/tools/build_models.py

1. Wikidata: every car model item whose brand or maker is a Group brand, with
   its English Wikipedia article.
2. Wikipedia: the wikitext of those articles (50 per request), and every
   {{Infobox automobile}} in them. A model article usually holds one infobox
   per generation; a generation article holds its own.
3. Each infobox becomes a row: brand, model, generation (the infobox name),
   model code, production years, body styles, source article. Rows whose
   production never touches 1995-2026 are dropped.

Nothing is typed in by hand: every row names the article it came from. Polite:
one request at a time, a pause between them, Retry-After honoured on 429.
"""
import json, os, re, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {'User-Agent': 'VWGroupPartsCatalogue/1.0 (research; one request at a time)'}
BRANDS = {'Volkswagen': 'Q246', 'Volkswagen Commercial Vehicles': 'Q699709', 'Audi': 'Q23317',
          'SEAT': 'Q188217', 'Cupra': 'Q8352675', 'Skoda': 'Q29637', 'Porsche': 'Q40993',
          'Bentley': None, 'Lamborghini': None}
LABELS = {'Bentley': 'Bentley Motors Limited', 'Lamborghini': 'Automobili Lamborghini'}


def get(url, tries=8):
    for i in range(tries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90)
            time.sleep(1.5)
            return r.read().decode()
        except urllib.error.HTTPError as e:
            wait = int(e.headers.get('Retry-After') or 0) or 10 * (i + 1)
            print(f'  HTTP {e.code}, waiting {wait}s', flush=True)
            time.sleep(wait + 2)
        except Exception as e:
            print('  retry', type(e).__name__, flush=True)
            time.sleep(10 * (i + 1))
    raise SystemExit('gave up on ' + url[:120])


def sparql(q):
    return json.loads(get('https://query.wikidata.org/sparql?format=json&query=' + urllib.parse.quote(q)))['results']['bindings']


def brand_qid(label):
    r = sparql(f'SELECT ?b WHERE {{ ?b rdfs:label "{label}"@en }} LIMIT 5')
    return r[0]['b']['value'].rsplit('/', 1)[1] if r else None


def articles(qid):
    q = f'''SELECT DISTINCT ?article WHERE {{
      {{ ?item wdt:P1716 wd:{qid} }} UNION {{ ?item wdt:P176 wd:{qid} }}
      ?item wdt:P31/wdt:P279* wd:Q3231690 .
      ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> .
    }}'''
    return sorted({urllib.parse.unquote(r['article']['value'].rsplit('/wiki/', 1)[1]).replace('_', ' ') for r in sparql(q)})


CACHE = os.environ.get('WIKI_CACHE', '/tmp/claude-0/-home-user-triposr-runpod-worker/34795087-6986-5aae-b59f-cce8aae2f506/scratchpad/wikicache.json')


CATS = {'Volkswagen': ['Category:Volkswagen vehicles', 'Category:Volkswagen Commercial Vehicles vehicles'],
        'Volkswagen Commercial Vehicles': [], 'Audi': ['Category:Audi vehicles'], 'SEAT': ['Category:SEAT vehicles'],
        'Cupra': ['Category:Cupra vehicles'], 'Skoda': ['Category:Škoda vehicles'], 'Porsche': ['Category:Porsche vehicles'],
        'Bentley': ['Category:Bentley vehicles', 'Category:Bentley Motors vehicles'], 'Lamborghini': ['Category:Lamborghini vehicles']}
SKIP_CAT = re.compile(r'concept|racing|race car|prototype|engine|motorsport|rally|military|by |people|images', re.I)


def category_articles(cat, depth=3, seen=None):
    """Every article in a brand's Wikipedia category tree (the Wikidata brand
    links miss many models: Tiguan, Touareg, ID.3...)."""
    seen = seen if seen is not None else set()
    if cat in seen or depth < 0:
        return set()
    seen.add(cat)
    out, cont = set(), ''
    while True:
        u = ('https://en.wikipedia.org/w/api.php?action=query&list=categorymembers&cmlimit=500&format=json'
             '&cmtype=page|subcat&cmtitle=' + urllib.parse.quote(cat) + cont)
        d = json.loads(get(u))
        for m in d['query']['categorymembers']:
            if m['ns'] == 0:
                out.add(m['title'])
            elif m['ns'] == 14 and not SKIP_CAT.search(m['title']):
                out |= category_articles(m['title'], depth - 1, seen)
        if 'continue' not in d:
            return out
        cont = '&cmcontinue=' + urllib.parse.quote(d['continue']['cmcontinue'])


MAKES = r'(Volkswagen|VW|Audi|SEAT|Seat|Cupra|CUPRA|Škoda|Skoda|Porsche|Bentley|Lamborghini)\b'
TITLE_BRAND = [(r'^Audi\b', 'Audi'), (r'^(SEAT|Seat)\b', 'SEAT'), (r'^(Cupra|CUPRA)\b', 'Cupra'), (r'^(Škoda|Skoda)\b', 'Skoda'),
               (r'^Porsche\b', 'Porsche'), (r'^Bentley\b', 'Bentley'), (r'^Lamborghini\b', 'Lamborghini'), (r'^(Volkswagen|VW)\b', 'Volkswagen')]


NAVBOX = {'Volkswagen': ['Template:Volkswagen', 'Template:Volkswagen Commercial Vehicles', 'Template:Volkswagen do Brasil'],
          'Audi': ['Template:Audi'], 'SEAT': ['Template:SEAT'], 'Cupra': ['Template:Cupra'], 'Skoda': ['Template:Škoda'],
          'Porsche': ['Template:Porsche'], 'Bentley': ['Template:Bentley'], 'Lamborghini': ['Template:Lamborghini']}


def navbox_articles(tpl):
    """Every article linked from a brand's navigation template."""
    out, cont = set(), ''
    while True:
        u = ('https://en.wikipedia.org/w/api.php?action=query&prop=links&plnamespace=0&pllimit=500&format=json'
             '&titles=' + urllib.parse.quote(tpl) + cont)
        d = json.loads(get(u))
        for p in d['query']['pages'].values():
            out |= {l['title'] for l in p.get('links', [])}
        if 'continue' not in d:
            return out
        cont = '&plcontinue=' + urllib.parse.quote(d['continue']['plcontinue'])


def wikitext(titles):
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    out = {t: cache[t] for t in titles if t in cache}
    titles = [t for t in titles if t not in cache]
    for k in range(0, len(titles), 50):
        u = ('https://en.wikipedia.org/w/api.php?action=query&prop=revisions&rvprop=content&rvslots=main'
             '&format=json&formatversion=2&redirects=1&titles=' + urllib.parse.quote('|'.join(titles[k:k + 50])))
        for p in json.loads(get(u))['query']['pages']:
            if p.get('revisions'):
                out[p['title']] = p['revisions'][0]['slots']['main']['content']
        print(f'  wikitext {min(k + 50, len(titles))}/{len(titles)}', flush=True)
        cache.update(out)
        json.dump(cache, open(CACHE, 'w'))
    return out


def infoboxes(text):
    """Yield the body of each {{Infobox automobile ...}}, brace-balanced."""
    for m in re.finditer(r'\{\{\s*Infobox[ _](?:automobile|electric[ _]vehicle)(?![ _]engine)', text, re.I):
        i, depth = m.start(), 0
        while i < len(text):
            if text.startswith('{{', i):
                depth += 1; i += 2
            elif text.startswith('}}', i):
                depth -= 1; i += 2
                if depth == 0:
                    break
            else:
                i += 1
        yield text[m.end():i - 2]


def params(box):
    """Split an infobox body into {name: value} on TOP-LEVEL pipes only, so a
    value written as {{ubl|2011-2023|...}} over several lines stays whole."""
    out, depth, cur, i = {}, 0, [], 0
    parts = []
    while i < len(box):
        two = box[i:i + 2]
        if two in ('{{', '[['):
            depth += 1; cur.append(two); i += 2; continue
        if two in ('}}', ']]'):
            depth -= 1; cur.append(two); i += 2; continue
        if box[i] == '|' and depth == 0:
            parts.append(''.join(cur)); cur = []; i += 1; continue
        cur.append(box[i]); i += 1
    parts.append(''.join(cur))
    for p in parts:
        k, eq, v = p.partition('=')
        if eq:
            out.setdefault(k.strip().lower().replace(' ', '_'), v.strip())
    return out


def field(box, name):
    return params(box).get(name.lower().replace(' ', '_'), '')


def clean(s):
    s = re.sub(r'<ref[^>]*/>|<ref[^>]*>.*?</ref>', '', s, flags=re.S)
    s = re.sub(r'<!--.*?-->', '', s, flags=re.S)
    s = re.sub(r'\[\[(?:[^|\]]*\|)?([^\]]*)\]\]', r'\1', s)
    s = re.sub(r"'''?|<br\s*/?>|\{\{(?:nowrap|ubl|plainlist|indented plainlist|unbulleted list|flatlist|hlist)\s*\|?", ' ', s, flags=re.I)
    s = re.sub(r'\{\{[^{}]*\}\}', ' ', s)
    s = re.sub(r'[*{}|]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def years(prod):
    ys = [int(y) for y in re.findall(r'\b(19[4-9]\d|20[0-3]\d)\b', prod)]
    if not ys:
        return None
    end = 2026 if re.search(r'present|current', prod, re.I) else max(ys)
    return [min(ys), max(end, max(ys))]


def tidy(rows):
    """Name bare generations after their article ("First generation" ->
    "Volkswagen Touran First generation") and drop a whole-model summary
    infobox when the same article also has per-generation ones inside its span."""
    out = []
    for r in rows:
        if not re.search(r'[A-Z][a-z]+ [A-Z0-9]', r['generation']) or re.match(r'(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth)\b', r['generation'], re.I):
            r['generation'] = f"{r['wikipedia_title']} {r['generation']}" if r['generation'] != r['wikipedia_title'] else r['generation']
        out.append(r)
    keep = []
    for r in out:
        inner = [o for o in out if o is not r and o['wikipedia_title'] == r['wikipedia_title']
                 and r['years'][0] <= o['years'][0] and o['years'][1] <= r['years'][1]]
        if len(inner) >= 1 and r['generation'] in (r['wikipedia_title'], r['model']):
            continue
        keep.append(r)
    return keep


def main():
    rows, seen = [], set()
    for brand, qid in BRANDS.items():
        qid = qid or brand_qid(LABELS[brand])
        titles = set(articles(qid)) if qid else set()
        n = len(titles)
        for c in CATS.get(brand, []):
            titles |= category_articles(c)
        for t in NAVBOX.get(brand, []):
            titles |= {x for x in navbox_articles(t) if re.match(MAKES, x)}
        titles = sorted(t for t in titles if not re.search(r'^List of|concept|prototype|race|rally|\(racing|engine$', t, re.I))
        print(f'{brand} ({qid}): {n} from Wikidata, {len(titles)} with the category tree', flush=True)
        texts = wikitext(titles)
        for title, text in texts.items():
            for box in infoboxes(text):
                prod = clean(field(box, 'production'))
                cls = clean(field(box, 'class'))
                if re.search(r'concept|prototype|one-off|show car|race car|racing', prod + ' ' + cls, re.I):
                    continue
                if not re.match(MAKES, title):
                    continue          # tuners and other makers filed in a brand category (9ff, Meyers Manx, Chrysler)
                yr = years(prod)
                if not yr or yr[1] < 1995 or yr[0] > 2026:
                    continue
                name = clean(field(box, 'name')) or title
                key = (brand, name.lower(), tuple(yr))
                if key in seen:
                    continue
                seen.add(key)
                own = next((b for rx, b in TITLE_BRAND if re.match(rx, title)), brand)
                rows.append({'brand': own, 'model': title, 'generation': name,
                             'code': clean(field(box, 'model_code')) or clean(field(box, 'model code')),
                             'years': yr, 'production': prod[:120],
                             'body_styles': [b for b in re.split(r'\s{2,}|,|;| / ', clean(field(box, 'body_style'))) if b.strip()][:8],
                             # the generation's own photo, from the same infobox (a Commons file name)
                             'image': re.sub(r'^(?:File|Image):', '', clean(field(box, 'image')).split(' px')[0]).strip(),
                             'wikipedia_title': title})
        rows = tidy(rows)
        json.dump(rows, open(os.path.join(HERE, 'models.json'), 'w'), indent=0, ensure_ascii=False)
        print(f'  -> {len(rows)} generations so far', flush=True)
    print('MODELS', len(rows))


if __name__ == '__main__':
    main()
