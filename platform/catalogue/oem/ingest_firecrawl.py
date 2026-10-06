#!/usr/bin/env python3
"""Turn saved Firecrawl results (JSON with `markdown` and `metadata.sourceURL`)
into parsed catalogue pages: pages/<vehicle-slug>/<category>.json.

    python3 platform/catalogue/oem/ingest_firecrawl.py FILE_OR_DIR [...]

Checks every page as it goes: every /oem-parts/ link under the page heading
must come out as a part row. A page that loses any is reported, not hidden.
Then run build_catalogue.py.
"""
import glob, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from parse_revolution import parse   # noqa: E402


def main():
    files = []
    for a in sys.argv[1:]:
        files += sorted(glob.glob(os.path.join(a, '*'))) if os.path.isdir(a) else [a]
    done = lost = 0
    for f in files:
        try:
            d = json.load(open(f))
        except Exception:
            continue
        url = (d.get('metadata') or {}).get('sourceURL', '')
        m = re.search(r'oempartsonline\.com/(v-[^/]+)/([^/?]+)', url)
        if not m or 'markdown' not in d:
            continue
        md = d['markdown']
        pg = parse(md, url)
        links = set(re.findall(r'/oem-parts/([a-z0-9-]+)', md[max(0, md.find('\n# ')):]))
        got = {p['url'].rsplit('/oem-parts/', 1)[-1] for p in pg['parts']}
        if links - got:
            lost += len(links - got)
            print(f'INGEST {m.group(1)}/{m.group(2)}: {len(links - got)} part link(s) not parsed', flush=True)
        os.makedirs(os.path.join(HERE, 'pages', m.group(1)), exist_ok=True)
        json.dump(pg, open(os.path.join(HERE, 'pages', m.group(1), m.group(2) + '.json'), 'w'), indent=1)
        done += 1
    print(f'INGEST {done} pages, {lost} part links lost')
    return 1 if lost else 0


if __name__ == '__main__':
    sys.exit(main())
