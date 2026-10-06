#!/usr/bin/env python3
"""Crawl the Golf workshop manual's ASSEMBLY OVERVIEWS on vwgolf.org into one
structured file: every exploded drawing, its numbered parts, and each part's
notes and tightening torques.

    python3 platform/trainer/data/crawl_vwgolf.py OUT.json [--limit=N]

Source: https://www.vwgolf.org (the Golf Mk7-era service manual, book 512).
Its robots.txt allows crawling. Polite: one request a second, a browser
User-Agent, resumable (pages already in OUT.json are skipped). Drawings are
recorded by URL, not downloaded — nothing large stays on this box.

These are references for BUILDING parts, not geometry: a drawing gives a
part's name, its place in the assembly, the fitting order and the torque;
the 3D part is still constructed by hand from it. The trainer's car is a
Mk8 GTI; many systems carry over from the Mk7 and some do not.
"""
import html, json, os, re, sys, time, urllib.request

BASE = 'https://www.vwgolf.org/'
UA = {'User-Agent': 'Mozilla/5.0 (training-manual research; polite crawler)'}


def get(url):
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return r.read().decode('utf-8', 'ignore')
        except Exception as ex:                     # network blips: back off and retry
            if attempt == 3:
                raise
            time.sleep(2 ** (attempt + 1))


def text(s):
    s = re.sub(r'<[^>]+>', ' ', s)
    return re.sub(r'\s+', ' ', html.unescape(s)).strip()


def parse(url, h):
    title = text(re.search(r'<h1[^>]*>(.*?)</h1>', h, re.S).group(1)) if '<h1' in h else ''
    title = re.sub(r'^Volkswagen Golf Service & Repair Manual:\s*', '', title)
    crumbs = [text(c) for c in re.findall(r'<a[^>]+href="[^"]+-\d+\.html"[^>]*>(.*?)</a>',
                                           h.split('<h1', 1)[-1].split('</div>', 1)[0])]
    images = [BASE + s for s in re.findall(r'<img[^>]+class="explo-bild[^"]*"[^>]+src="([^"]+)"', h)]
    # each numbered row is a table whose first cell is "N - "; the rows after
    # it, until the next number, are that part's notes
    parts, cur = [], None
    body = h.split('images/previous.png', 1)[0]        # the prev/next footer starts here
    for tbl in re.findall(r'<table class="cc[^"]*"[^>]*>(.*?)</table>', body, re.S):
        num = re.search(r'class="einzug-nummer">\s*(\d+)\s*(?:&nbsp;|\s)*-', tbl)
        cells = [text(c) for c in re.findall(r'<td[^>]*>(.*?)</td>', tbl, re.S)]
        cells = [c for c in cells if c]
        if num:
            cur = {'n': int(num.group(1)), 'name': cells[-1] if cells else '', 'notes': []}
            parts.append(cur)
        elif cur and cells:
            cur['notes'].extend(cells)
    for p in parts:
        notes = ' '.join(p['notes'])
        p['torque_nm'] = [float(x) for x in re.findall(r'(\d+(?:\.\d+)?)\s*Nm', notes)]
        p['angle_deg'] = [int(x) for x in re.findall(r'(\d+)\s*°', notes)]
        p['renew'] = bool(re.search(r'always renew|renew after removing', notes, re.I))
    return {'url': url, 'title': title, 'path': crumbs, 'images': images, 'parts': parts}


def main():
    pos = [a for a in sys.argv[1:] if not a.startswith('--')]
    opt = dict(a[2:].split('=', 1) for a in sys.argv[1:] if a.startswith('--') and '=' in a)
    if len(pos) != 1:
        print(__doc__)
        return 1
    out = pos[0]
    data = json.load(open(out)) if os.path.exists(out) else []
    done = {d['url'] for d in data}
    urls = re.findall(r'<loc>([^<]*assembly_overview[^<]*)</loc>', get(BASE + 'sitemap.xml'))
    todo = [u for u in urls if u not in done][:int(opt.get('limit', 10 ** 6))]
    print(f'VWGOLF {len(urls)} assembly overviews, {len(done)} already done, {len(todo)} to go', flush=True)
    for i, u in enumerate(todo, 1):
        try:
            data.append(parse(u, get(u)))
        except Exception as ex:
            data.append({'url': u, 'error': f'{type(ex).__name__}: {ex}'[:200]})
        if i % 20 == 0 or i == len(todo):
            json.dump(data, open(out, 'w'), indent=1, ensure_ascii=False)
            print(f'VWGOLF [{i}/{len(todo)}] {data[-1].get("title", "")[:60]}', flush=True)
        time.sleep(1)
    json.dump(data, open(out, 'w'), indent=1, ensure_ascii=False)
    print('VWGOLF_DONE', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
