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


def vw_from_slug(n):
    """A part link's last slug token, back to the real VW number. The link
    DROPS LEADING ZEROS: 04E 103 623 S is linked as `4e103623s`. A VW number
    is a 3-character prefix, 6 digits and a 0-3 letter suffix, so a 2-character
    prefix gets its zero back. Standard hardware (N + 8 digits) is left alone."""
    n = n.upper()
    if re.fullmatch(r'N\d{8}', n):
        return n
    m = re.fullmatch(r'([0-9A-Z]{1,3}?)(\d{6})([A-Z]{0,3})', n)
    if m and len(m.group(1)) < 3:
        return m.group(1).rjust(3, '0') + m.group(2) + m.group(3)
    return n


def vw_display(n):
    """5q0698151m -> 5Q0 698 151 M (VW/Audi/SEAT/Skoda 3-3-3-suffix)."""
    n = n.upper().replace('-', '').replace(' ', '')
    m = re.fullmatch(r'(N)(\d{3})(\d{3})(\d{2})', n)   # standard hardware first: N 106 483 01
    if m:
        return ' '.join(m.groups())
    m = re.fullmatch(r'(N)(\d{3})(\d{3})(\d)', n)      # older hardware: N 019 530 7
    if m:
        return ' '.join(m.groups())
    m = re.fullmatch(r'(D)(\d{3})(\d{3})([A-Z]\d)', n)   # chemicals: D 176 501 A1
    if m:
        return ' '.join(m.groups())
    # 3-3-3, letter suffix, then any colour/trim code: 5Q0 615 425 C QB7
    m = re.fullmatch(r'([0-9A-Z]{3})([0-9]{3})([0-9]{3})([A-Z]{0,3}?)([A-Z0-9]{3})?', n)
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
    for line in re.split(r'\n(?=\[\d+\]\(|- \[)', md):
        c = re.match(r'\[(\d+)\]\([^)]*#part_row_\d+_(\d+)_\d+\)', line)
        if c:
            callout = int(c.group(1))
            continue
        # price is absent on parts the dealer marks "(Unavailable)" — still real numbers
        p = re.match(r'- \[(?:\$([\d,.]+)\\\\?\s*\n)?(.*?)\]\((https://[^)\s]+/oem-parts/[^)\s]+)\)', line, re.S)
        if not p:
            continue
        price, body, url = p.groups()
        lines = [x.strip().rstrip('\\').strip() for x in body.split('\n')]
        lines = [x for x in lines if x]
        name = lines[0] if lines else ''
        rest = lines[2:] if len(lines) > 1 and lines[1].lower() in ('volkswagen', 'audi', 'genuine') else lines[1:]
        fits = next((x[5:].strip() for x in rest if x.startswith('Fits ')), '')
        notes = ' '.join(x for x in rest if not x.startswith('Fits '))
        oem = vw_from_slug(url.rstrip('/').rsplit('-', 1)[-1])
        out['parts'].append({'oem': oem, 'oem_display': vw_display(oem), 'oem_from': 'link (zero-restored)',
                             'name': name, 'callout': callout, 'diagram': shown,
                             'price_usd': float(price.replace(',', '')) if price else None,
                             'unavailable': '(Unavailable)' in body,
                             'notes': notes, 'fits': fits, 'url': url})
    # a page uses one layout or the other; run both and merge by part link,
    # keeping the TABLE row where both saw a part (its number is printed)
    table = parse_table(md)
    seen = {p['url'] for p in table}
    out['parts'] = table + [p for p in out['parts'] if p['url'] not in seen]
    return out


def parse_table(md):
    """The TABLE layout (front suspension, mounts…): each part is an image link
    titled "<name> - Part No 04E-103-623-S", a bold name, MSRP and price, and
    the number again as link text. Here the number is PRINTED, so it is taken
    as printed, leading zero and all."""
    parts, diagram = [], None
    blocks = re.split(r'\n(?=\[!\[[^\]]*\]\([^)]*\)\]\(https://[^ )]+/oem-parts/)', md)
    for i, b in enumerate(blocks):
        heads = re.findall(r'^Diagram (\d+): ', blocks[i - 1] if i else '', re.M)
        if heads:
            diagram = int(heads[-1])
        m = re.match(r'\[!\[[^\]]*\]\([^)]*\)\]\((https://[^ )]+/oem-parts/[^ )]+) "(.*?) - Part No ([0-9A-Z-]+)"\)', b)
        if not m:
            continue
        url, label, pno = m.groups()
        prev = (blocks[i - 1] if i else '').strip().splitlines()
        callout = int(prev[-1]) if prev and prev[-1].strip().isdigit() else None
        nm = re.search(r'\*\*\[([^\]]+)\]', b)
        prices = [float(x.replace(',', '')) for x in re.findall(r'\$([\d,]+\.\d\d)', b)]
        tail = b.split('**Volkswagen**', 1)[-1].split('-+', 1)[0]
        lines = [x.strip() for x in tail.strip().splitlines() if x.strip()]
        oem = pno.replace('-', '')
        parts.append({'oem': oem, 'oem_display': vw_display(oem), 'oem_from': 'printed',
                      'name': nm.group(1) if nm else label, 'label': lines[0] if lines else label,
                      'callout': callout, 'diagram': diagram,
                      'price_usd': prices[-1] if prices else None, 'msrp_usd': prices[0] if len(prices) > 1 else None,
                      'notes': ' '.join(lines[1:]), 'fits': '', 'url': url})
    return parts


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
