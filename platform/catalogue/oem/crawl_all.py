#!/usr/bin/env python3
"""Crawl EVERY parts category for every catalogued Golf-family car.

    python3 platform/catalogue/oem/crawl_all.py [--limit=N] [--only=slug,slug]

Needs FIRECRAWL_API_KEY in the environment (or /root/.alam3d_env). Reads the
category list each car offers from its already-crawled pages (todo.json is
written beside this file), skips categories already in pages/, and fetches the
rest one at a time at 7 pages a minute — under Firecrawl's plan limit and the
site's robots.txt crawl delay. Resumable: stop it any time and run it again.
Every page is checked like ingest_firecrawl.py does; build_catalogue.py runs
every 50 pages so parts.json (one entry per OEM number, never duplicated) stays
current. The key is read, never written anywhere.
"""
import glob, json, os, re, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from parse_revolution import parse   # noqa: E402

SITE = 'https://vw.oempartsonline.com'
SKIP = re.compile(r'^(accessories|vehicles-equipment|oil-fluids-and-chemicals)')   # not car parts
GAP = 60 / 7


def key():
    k = os.environ.get('FIRECRAWL_API_KEY')
    if not k and os.path.exists('/root/.alam3d_env'):
        for line in open('/root/.alam3d_env'):
            if line.startswith('FIRECRAWL_API_KEY='):
                k = line.split('=', 1)[1].strip().strip('"\'')
    return k


def todo():
    """Every category each car's own pages link to, minus what is crawled."""
    have = {}
    for f in glob.glob(os.path.join(HERE, 'pages', '*', '*.json')):
        have.setdefault(os.path.basename(os.path.dirname(f)), set()).add(os.path.basename(f)[:-5])
    cats = json.load(open(os.path.join(HERE, 'categories.json')))
    out = []
    for v, cs in sorted(cats.items()):
        out += [(v, c) for c in sorted(cs) if not SKIP.match(c) and c not in have.get(v, set())]
    return out


def scrape(url, k):
    body = json.dumps({'url': url, 'formats': ['markdown'], 'onlyMainContent': True}).encode()
    rq = urllib.request.Request('https://api.firecrawl.dev/v2/scrape', data=body, method='POST',
                                headers={'Authorization': 'Bearer ' + k, 'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(rq, timeout=120))['data']['markdown']


def main():
    opt = dict(a[2:].split('=', 1) for a in sys.argv[1:] if a.startswith('--') and '=' in a)
    k = key()
    if not k:
        sys.exit('FIRECRAWL_API_KEY is not set (environment or /root/.alam3d_env)')
    jobs = todo()
    if opt.get('only'):
        jobs = [j for j in jobs if j[0] in opt['only'].split(',')]
    jobs = jobs[:int(opt.get('limit', 10 ** 6))]
    print(f'CRAWL {len(jobs)} category pages to fetch', flush=True)
    done = lost = 0
    for i, (v, c) in enumerate(jobs, 1):
        t0 = time.time()
        url = f'{SITE}/{v}/{c}'
        for attempt in range(4):
            try:
                md = scrape(url, k)
                break
            except Exception as ex:
                print(f'CRAWL retry {v}/{c}: {type(ex).__name__} {str(ex)[:100]}', flush=True)
                time.sleep(15 * (attempt + 1))
        else:
            continue
        pg = parse(md, url)
        links = set(re.findall(r'/oem-parts/([a-z0-9-]+)', md[max(0, md.find('\n# ')):]))
        got = {p['url'].rsplit('/oem-parts/', 1)[-1] for p in pg['parts']}
        if links - got:
            lost += len(links - got)
            print(f'CRAWL {v}/{c}: {len(links - got)} part link(s) not parsed', flush=True)
        os.makedirs(os.path.join(HERE, 'pages', v), exist_ok=True)
        json.dump(pg, open(os.path.join(HERE, 'pages', v, c + '.json'), 'w'), indent=1)
        done += 1
        print(f'CRAWL [{i}/{len(jobs)}] {v}/{c}: {len(pg["parts"])} parts', flush=True)
        if done % 50 == 0:
            os.system(f'{sys.executable} {os.path.join(HERE, "build_catalogue.py")}')
        time.sleep(max(0, GAP - (time.time() - t0)))
    os.system(f'{sys.executable} {os.path.join(HERE, "build_catalogue.py")}')
    print(f'CRAWL_DONE {done} pages, {lost} part links lost', flush=True)


if __name__ == '__main__':
    sys.exit(main())
