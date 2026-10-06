#!/usr/bin/env python3
"""Parse a RevolutionParts dealer catalogue page (e.g. vw.oempartsonline.com)
into OEM parts. Input is the page as MARKDOWN (what Firecrawl returns).

    python3 parse_revolution.py PAGE.json|PAGE.md [...]   -> JSON on stdout

A category page shows a strip of DIAGRAMS (assemblies) and the parts of ONE
of them — the first, or the one named by ?assembly=N. Each part row gives
its callout number on that drawing, price, name, notes, "Fits ..." line and
a link whose LAST slug token is the OEM number (…/volkswagen-brake-hose-
5qm611701c -> 5QM 611 701 C). The OEM number is read from the link, never
from model text, so it is copied exactly.

Recorded per part: oem, oem_display, name, callout, diagram, price_usd,
notes, fits, url, source page. US-market catalogue: say so wherever shown.
"""
import json, re, sys


def vw_display(n):
    """5q0698151m -> 5Q0 698 151 M (VW/Audi/SEAT/Skoda 3-3-3-suffix)."""
    n = n.upper()
    m = re.fullmatch(r'(N)(\d{3})(\d{3})(\d{2})', n)   # standard hardware first: N 106 483 01
    if m:
        return ' '.join(m.groups())
    m = re.fullmatch(r'([0-9A-Z]{3})([0-9]{3})([0-9]{3})([A-Z]{0,3})', n)
    if m:
        return ' '.join(x for x in m.groups() if x)
    return n


def parse(md, page_url=''):
    out = {'page': page_url, 'title': '', 'diagrams': [], 'parts': []}
    t = re.search(r'^# (.+)$', md, re.M)
    out['title'] = t.group(1).strip() if t else ''
    for n, img, name, url in re.findall(
            r'\[!\[Diagram (\d+)\]\((https://cdn-illustrations[^)]+)\)\d+\\?\.\s*([^\]]+?)\]\((https://[^ )]+)', md):
        out['diagrams'].append({'n': int(n), 'name': name.strip(), 'image': img, 'url': url})
    cur = re.search(r'^Diagram (\d+): (.+?)\d*$', md, re.M)
    shown = int(cur.group(1)) if cur else None
    # a callout marker "[7](…#part_row_0_7_0)" applies to the part rows after it
    callout = None
    for line in re.split(r'\n(?=\[\d+\]\(|- \[\$)', md):
        c = re.match(r'\[(\d+)\]\([^)]*#part_row_\d+_(\d+)_\d+\)', line)
        if c:
            callout = int(c.group(1))
            continue
        p = re.match(r'- \[\$([\d,.]+)\\\\?\s*\n(.*?)\]\((https://[^)\s]+/oem-parts/[^)\s]+)\)', line, re.S)
        if not p:
            continue
        price, body, url = p.groups()
        lines = [x.strip().rstrip('\\').strip() for x in body.split('\n')]
        lines = [x for x in lines if x]
        name = lines[0] if lines else ''
        rest = lines[2:] if len(lines) > 1 and lines[1].lower() in ('volkswagen', 'audi', 'genuine') else lines[1:]
        fits = next((x[5:].strip() for x in rest if x.startswith('Fits ')), '')
        notes = ' '.join(x for x in rest if not x.startswith('Fits '))
        oem = url.rstrip('/').rsplit('-', 1)[-1]
        out['parts'].append({'oem': oem.upper(), 'oem_display': vw_display(oem), 'name': name,
                             'callout': callout, 'diagram': shown, 'price_usd': float(price.replace(',', '')),
                             'notes': notes, 'fits': fits, 'url': url})
    return out


def main():
    res = []
    for f in sys.argv[1:]:
        raw = open(f).read()
        try:
            d = json.loads(raw)
            md, url = d.get('markdown', ''), (d.get('metadata') or {}).get('sourceURL', '')
        except json.JSONDecodeError:
            md, url = raw, ''
        res.append(parse(md, url))
    json.dump(res, sys.stdout, indent=1)


if __name__ == '__main__':
    main()
