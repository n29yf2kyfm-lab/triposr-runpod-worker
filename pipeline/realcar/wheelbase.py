#!/usr/bin/env python3
"""wheelbase.py — a model's published wheelbase, from a table that ships with
the machine: building a car makes no outside call.

    python3 pipeline/realcar/wheelbase.py nissan micra 2004 [--ratio=0.62]
    python3 pipeline/realcar/wheelbase.py --build      # (re)make the table, once

A catalogue model that is not at metre scale has to be scaled to the real
car, and the wheelbase is the figure that fixes the scale best (it is not
changed by bumpers or spoilers).

THE TABLE (wheelbase_table.json) holds, for every make and model in the
catalogue, every generation's production years, wheelbase and length, read
once from English Wikipedia's page text (the model's page, a sister make's,
and every generation page they link to, up to 12) by `--build`. Facts, not
text: only the numbers are kept. A model added to the catalogue later is
added with `--build` again (or GLBMACHINE_ONLINE=1 looks it up on the spot).

CHOOSING, offline: the generation on sale in the model's year wins. When two
are (a generation change that year: the A-Class W176 ended and the W177
began in 2018), the one whose wheelbase-to-length proportion is closest to
the 3D model's (`ratio`) wins.
"""
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
UA = "ExpertCarCheck-GLB/1.0 (car model sizing; https://github.com/n29yf2kyfm-lab/triposr-runpod-worker)"
MAKE_TITLE = {"mercedes-benz": "Mercedes-Benz", "volkswagen": "Volkswagen", "bmw": "BMW", "mg": "MG", "byd": "BYD",
              "land-rover": "Land Rover", "alfa-romeo": "Alfa Romeo", "aston-martin": "Aston Martin",
              "rolls-royce": "Rolls-Royce", "mini": "Mini", "ds": "DS", "seat": "SEAT", "kia": "Kia"}


_LAST = threading.local()                     # why the last page came back empty


class _Pace:
    def __init__(self):
        self.lock, self.next = threading.Lock(), 0.0

    def __enter__(self):
        self.lock.acquire()

    def __exit__(self, *a):
        self.lock.release()


_PACE = _Pace()


def raw(title, _seen=None):
    """Page wikitext, redirects followed (twice at most). None when the page
    does not exist (_LAST.missing) or could not be reached."""
    _LAST.missing = False
    if not _seen:
        _LAST.anchor = ""
    with _PACE:                                # a few requests a second: Wikipedia throttles bursts
        time.sleep(max(0.0, _PACE.next - time.time()))
        _PACE.next = time.time() + 0.35
    url = "https://en.wikipedia.org/w/index.php?" + urllib.parse.urlencode({"title": title, "action": "raw"})
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                t = r.read().decode("utf-8", "replace")
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                _LAST.missing = True
                return None, title
            time.sleep(2 * (attempt + 1))
        except Exception:
            time.sleep(2 * (attempt + 1))
    else:
        return None, title
    m = re.match(r"\s*#REDIRECT\s*\[\[([^\]|#]+)(?:#([^\]|]+))?", t, re.I)
    if m and (_seen or 0) < 2:
        # a redirect to a section ("Hyundai ix35" -> "Hyundai Tucson#LM")
        # names the generation: kept for _boxes_for
        _LAST.anchor = (m.group(2) or "").strip() or getattr(_LAST, "anchor", "")
        return raw(m.group(1).strip(), (_seen or 0) + 1)
    return t, title


def _clean(v):
    """An infobox value without its footnotes (their access dates are years too)."""
    v = re.sub(r"<ref[^>]*/>", "", v)
    v = re.sub(r"<ref[^>]*>.*?</ref>", "", v, flags=re.S)
    return re.sub(r"\{\{\s*cite[^{}]*\}\}", "", v, flags=re.I)


def _mm(v, lo=1500, hi=7000):
    """The first length in mm in an infobox value: {{convert|2430|mm|..}},
    {{convert|2548-2564|mm|..}} or {{convert|4292|-|4367|mm|..}} (a range:
    its middle), '2,430 mm'. Only figures from LO to HI count: a wheelbase or
    a length by default, a width or a height given its own range."""
    v = _clean(v)
    m = re.search(r"\{\{\s*(?:convert|cvt)\s*\|([^{}]*?)\|\s*mm\b", v, re.I)
    # inches, one figure or a range ({{convert|63.4|–|63.8|in|mm|0}}: the ZR-V's height)
    inch = re.search(r"\{\{\s*(?:convert|cvt)\s*\|([\d.,\s\-–|]+?)\|\s*in\b", v, re.I)
    if inch and not (m and m.start() < inch.start()):
        # an American page's inches ({{convert|101.0|in|mm|0}}): to mm
        nums = [float(x.replace(",", "")) * 25.4 for x in re.findall(r"[\d,]+(?:\.\d+)?", inch.group(1))]
    elif m:
        nums = [float(x.replace(",", "")) for x in re.findall(r"[\d,]+(?:\.\d+)?", m.group(1))]
    else:
        m = re.search(r"([\d,]{4,6})\s*(?:[-–]\s*([\d,]{4,6})\s*)?mm", v)
        nums = [float(x.replace(",", "")) for x in m.groups() if x] if m else []
    nums = [n for n in nums if lo <= n <= hi]
    return int(round((nums[0] + nums[-1]) / 2)) if nums else None


def _lines(v):
    """An infobox value as plain words, one per line or list item."""
    v = re.sub(r"<br\s*/?>|\s/\s|;", "\n", _clean(v), flags=re.I)
    v = re.sub(r"\{\{\s*(?:ubl|unbulleted list|plainlist|flatlist|hlist)\s*\|?", "", v, flags=re.I)
    v = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", v)
    v = re.sub(r"\{\{[^{}]*\}\}|<[^>]+>|'{2,3}", " ", v)
    return [" ".join(x.strip(" }{").split()) for x in re.split(r"\n|\*|\|", v) if x.strip(" }{")]


def _text(v):
    """An infobox value as plain words, its first line or list item only
    ('{{ubl|5-door [[hatchback]]|...}}' -> '5-door hatchback')."""
    return (_lines(v) or [""])[0]


def _doors(v):
    """The most doors any of a box's bodies has ('3-door hatchback<br>5-door
    hatchback': 5, the C1's), its body naming only the first; None when none
    says."""
    n = [int(x) for x in re.findall(r"([2-5])(?=[-/ ]?(?:\d-?)?door)", " ".join(_lines(v)))]
    return max(n) if n else None


def body_family(body, cls="", name=""):
    """hatch, saloon, estate, suv, mpv, coupe, convertible, pickup or van,
    from a generation's body style, else its class, else its name."""
    for text in (body, cls, name):
        t = (text or "").lower()
        for fam, rx in (("convertible", r"convertible|cabrio|roadster|spider|spyder|targa|drophead|open two-seater"),
                        ("pickup", r"pick-?up|\bute\b"), ("van", r"panel van|\bvan\b"),
                        ("mpv", r"\bmpv\b|minivan|people carrier|multi-purpose|leisure activity"),
                        ("suv", r"\bsuv\b|crossover|sport utility|off-road|4x4"),
                        ("estate", r"estate|station wagon|\bwagon\b|touring|shooting brake|\bavant\b"),
                        ("coupe", r"coup[eé]"),
                        ("saloon", r"saloon|sedan|notchback|fastback"),
                        ("hatch", r"hatchback|liftback|supermini|city car|small family|hot hatch")):
            if re.search(rx, t):
                return fam
    return None


def _years(v):
    v = _clean(v)
    ys = [int(y) for y in re.findall(r"\b(19[3-9]\d|20[0-4]\d)\b", v)]
    if not ys:
        return None
    present = re.search(r"present|current|–\s*$|-\s*$", re.sub(r"<[^>]+>|\{\{[^}]*\}\}", "", v), re.I)
    return min(ys), (2100 if present and len(ys) == 1 else max(ys))


# a wheelbase's label: its length in words, or the model it is (the Land
# Rover Ninety's "(90)", "(110)")
WB_LABEL = re.compile(r"\((SWB|LWB|XLWB|short wheelbase|long wheelbase|\d{2,3})\)", re.I)


def _items(v):
    """A field's entries as written, templates kept: its <br> lines, or its
    list template's items ("{{ubl|{{convert|92.9|in|mm}} (90)|...}}")."""
    m = re.match(r"\s*\{\{\s*(?:ubl|unbulleted list|plainlist|flatlist)\s*\|", v, re.I)
    if not m:
        return [x for x in re.split(r"<br\s*/?>", v, flags=re.I) if x.strip()]
    out, depth, cur, i = [], 0, "", m.end()
    while i < len(v):
        two = v[i:i + 2]
        if two in ("{{", "[["):
            depth, cur, i = depth + 1, cur + two, i + 2
            continue
        if two in ("}}", "]]"):
            if depth == 0:
                break
            depth, cur, i = depth - 1, cur + two, i + 2
            continue
        if v[i] == "|" and depth == 0:
            out.append(cur)
            cur, i = "", i + 1
            continue
        cur, i = cur + v[i], i + 1
    out.append(cur)
    return [y for x in out for y in re.split(r"<br\s*/?>|\n\s*\*", x, flags=re.I) if y.strip(" *\n")]


def _by_wheelbase(fields):
    """A box's sizes, one set per wheelbase when it gives two, each line
    labelled ("88 in (SWB)<br>109 in (LWB)": the Land Rover series): a size
    takes its label's line (the latest of them), a size given once is shared.
    [(label or None, fields)]."""
    sizes = ("wheelbase", "length", "width", "height")
    lines = {k: _items(fields.get(k, "")) for k in sizes}
    labels = []
    for x in lines["wheelbase"]:
        g = WB_LABEL.search(x)
        if g and g.group(1).upper() not in labels:
            labels.append(g.group(1).upper())
    if len(labels) < 2:
        return [(None, fields)]
    out = []
    for lab in labels:
        f = dict(fields)
        for k in sizes:
            own = [x for x in lines[k] if (g := WB_LABEL.search(x)) and g.group(1).upper() == lab]
            if not own and lab.isdigit():
                # "(2000s 90)", "(110 Hardtop)": the model's number among the label's words
                own = [x for x in lines[k] if re.search(rf"\([^()]*\b{lab}\b[^()]*\)", x)]
            # a width or height given once for all, then by year: the first
            f[k] = own[-1] if own else (lines[k][0] if len(lines[k]) == 1 or (k in ("width", "height") and lines[k]
                                                                          and not WB_LABEL.search(lines[k][0])) else "")
        out.append((lab, f))
    return out


def infoboxes(text, title):
    out, page = [], {}
    for m in re.finditer(r"\{\{\s*Infobox (?:automobile|electric vehicle)", text, re.I):
        depth, i = 0, m.start()
        while i < len(text):
            if text.startswith("{{", i):
                depth += 1
                i += 2
                continue
            if text.startswith("}}", i):
                depth -= 1
                i += 2
                if depth == 0:
                    break
                continue
            i += 1
        box = text[m.start():i]
        fields = {}
        # [ \t]* after '=': an empty field ('| aka =') must not swallow the next line
        for f in re.finditer(r"\|\s*([a-z_ ]+?)\s*=[ \t]*(.*?)(?=\n\s*\|\s*[a-z_ ]+?\s*=|\}\}\s*$)", box, re.S | re.I):
            fields[f.group(1).strip().lower()] = f.group(2)
        wb = _mm(fields.get("wheelbase", ""))
        if not wb:
            # a box with no size (the page's lead box) may still name the
            # model's class and body ("Mini MPV" for the Cube, whose
            # generation boxes name none): kept for boxes that name neither
            for k, f in (("page_body", "body_style"), ("page_class", "class")):
                v = _text(fields.get(f, ""))[:80]
                # a body only when the box names one: the Mazda 3's lists a
                # saloon and a hatchback, and says nothing of a generation's
                if v and (k == "page_class" or len({body_family(x) for x in _lines(fields.get(f, ""))} - {None}) == 1):
                    page.setdefault(k, v)
            continue
        yr = _years(fields.get("production", "")) or _years(fields.get("model_years", ""))
        name = re.sub(r"\[\[|\]\]|'''|''", "", fields.get("name", "")).strip()[:80]
        for label, f in _by_wheelbase(fields):
            out.append({"page": title, "at": m.start(), "name": f"{name} ({label})" if label else name,
                        "years": yr, "wheelbase": _mm(f.get("wheelbase", "")), "length": _mm(f.get("length", "")),
                        "width": _mm(f.get("width", ""), 1300, 2700), "height": _mm(f.get("height", ""), 1000, 2600),
                        "body": _text(fields.get("body_style", ""))[:80], "class": _text(fields.get("class", ""))[:80],
                        "doors": _doors(fields.get("body_style", ""))})
    for b in out:
        if not (b["body"] or b["class"]):
            b.update({k: v for k, v in page.items() if v})
    return out


# a make's other name, for when its own page has no generations
# a make Wikipedia titles with its accent, when the plain name has no page
ACCENT = {"skoda": "Škoda", "citroen": "Citroën"}
SISTER = {"vauxhall": "Opel", "opel": "Vauxhall", "mini": "Mini", "dacia": "Renault", "seat": "SEAT"}
# a model's other page name
ALIAS = {("vauxhall", "zafira"): "Opel Zafira",     # the Vauxhall page puts the Zafira A and B in one box
         ("mini", "cooper"): "Mini Hatch", ("mini", "hatch"): "Mini Hatch", ("honda", "jazz"): "Honda Fit",
         ("hyundai", "ix20"): "Kia Venga",          # the ix20's page is the Venga's: the same car
         # the 2016-2020 SLC is the renamed SLK (R172); "SLC" alone finds the 1971 SLC coupe
         ("mercedes-benz", "slc"): "Mercedes-Benz R172", ("mercedes-benz", "slc class"): "Mercedes-Benz R172",
         # "Aston Martin Vantage" is a list of every Vantage: the 2018 car's own page
         ("aston-martin", "vantage"): "Aston Martin Vantage (2018)",
         ("suzuki", "e vitara"): "Suzuki e Vitara",       # its own electric car, titled with a small e
         ("ford", "fusion"): "Ford Fusion (Europe)",      # the UK's Fusion: the 2002-2012 Fiesta-based car, not the US saloon
         # the 2024 Milano, renamed the Junior before sale ("Milano" alone is the US name of the 1985 Alfa 75)
         ("alfa-romeo", "milano"): "Alfa Romeo Junior", ("alfa-romeo", "junior"): "Alfa Romeo Junior",
         ("nissan", "pixo"): "Suzuki Alto",         # the UK Pixo is the 2009-2013 Alto
         ("mg", "mgf"): "MG F / MG TF", ("mg", "f"): "MG F / MG TF",
         ("geely", "starray"): "Geely Galaxy Starship 7",     # the export name of the Starship 7 EM-i
         ("smart", "city"): "Smart Fortwo", ("smart", "city coupe"): "Smart Fortwo",
         ("ds", "ds3"): "DS 3", ("ds", "ds4"): "DS 4", ("ds", "ds5"): "DS 5", ("ds", "ds7"): "DS 7",
         ("ds", "ds9"): "DS 9",
         ("alfa-romeo", "giulietta"): "Alfa Romeo Giulietta (2010)",   # "Alfa Romeo Giulietta" lists three cars
         ("citroen", "e-c3"): "Citroën C3", ("audi", "sq2"): "Audi Q2", ("bmw", "x3 m"): "BMW X3",   # on their cars' pages
         ("kgm", "musso"): "SsangYong Musso",               # KGM is SsangYong's new name
         ("hyundai", "iload"): "Hyundai Starex",            # the UK iLoad is the Starex (H-1)
         ("ldv", "v80"): "LDV Maxus",                       # the V80 is the LDV Maxus, made on by SAIC
         ("jaecoo", "omoda 5"): "Chery Omoda 5", ("land-rover", "series"): "Land Rover series"}   # the City-Coupé, renamed in 2004
# more pages that hold a model's generations: the first three Yaris
# generations are filed under the Japanese name
EXTRA = {("bmw", "z4"): ["BMW Z4 (E85)", "BMW Z4 (E89)", "BMW Z4 (G29)"],   # "BMW Z4" redirects to the Z family's page
         ("toyota", "yaris"): ["Toyota Vitz"],
         ("daihatsu", "sirion"): ["Daihatsu Boon"],
         ("fiat", "600"): ["Fiat 600 (2023)"],           # the 2023 600's own page; "Fiat 600" is the 1955 car
         ("land-rover", "88"): ["Land Rover series"], ("land-rover", "109"): ["Land Rover series"],
         # generations on pages of their own the model's page does not link as one
         ("fiat", "tipo"): ["Fiat Tipo (2015)"], ("fiat", "bravo"): ["Fiat Bravo (2007)"],
         ("honda", "civic"): ["Honda Civic (eighth generation)", "Honda Civic (ninth generation)",
                              "Honda Civic (tenth generation)", "Honda Civic (eleventh generation)"],
         ("jeep", "cherokee"): ["Jeep Cherokee (KL)"], ("volvo", "v40"): ["Volvo V40 (2012–2019)"],
         ("mercedes-benz", "gl-class"): ["Mercedes-Benz GL-Class (X164)", "Mercedes-Benz GL-Class (X166)"],
         ("vauxhall", "viva"): ["Opel Karl"],              # the 2015-2019 Viva is the Opel Karl
         ("volkswagen", "transporter"): ["Volkswagen Transporter (T4)", "Volkswagen Transporter (T5)",
                                         "Volkswagen Transporter (T6)"]}   # each generation's own page     # the second Sirion (M300, 2004-2010) is filed as the Boon


def _generation_link(link, stem):
    """A generation's own page, not a spin-off: 'Nissan Micra (K12)', 'Ford
    Fiesta (sixth generation)', 'Volkswagen Golf Mk8', 'Opel Astra K' - but
    not 'Fiat 500L' or 'Volkswagen Polo GTI'."""
    rest = link[len(stem):]
    return bool(re.fullmatch(r"\s*\([^)]*\)|\s+Mk\s?\d+[^ ]*(\s*\([^)]*\))?|\s+[A-Z]{1,2}\d{0,3}|\s+\w+ generation", rest))


def _boxes_for(base):
    """(boxes, generation pages, title, pages that could not be reached)."""
    return _anchored(base)


def _anchored(base):
    """_boxes_all's, only the generation a redirect's section names when one
    does: the box of that name, else the first box after that section's
    heading or anchor on the page."""
    boxes, pages, title, unreached = _boxes_all(base)
    anchor, text = getattr(_LAST, "anchor_of_base", ""), getattr(_LAST, "text_of_base", "")
    if anchor:
        # the anchor as a whole word of the box's name ("LM" in "Second
        # generation (LM)", never "ST" inside "first"); (?<!\w) and (?!\w)
        # also hold beside a bracket, where \b does not
        w = r"(?<![\w])" + re.escape(anchor) + r"(?![\w])"
        keep = [b for b in boxes if re.search(w, b.get("name") or "", re.I)]
        if not keep and text:
            m = re.search(r"\{\{\s*anchors?\s*\|[^}]*" + w + r"|^==+.*" + w + r".*==+\s*$", text, re.I | re.M)
            line = text[m.start():text.find("\n", m.start())] if m else ""
            if m and not re.search(r"generation|\(|\bmk\s?\d|\bseries\b", re.sub(r"<[^>]+>", "", line), re.I):
                m = None                          # a section that is no generation ("History"): all of them
            keep = sorted((b for b in boxes if m and b.get("page") == title and b.get("at", -1) >= m.start()),
                          key=lambda b: b["at"])[:1]
            # the section's own page ({{Main|Hyundai Tucson (LM)}} under its heading)
            main = re.search(r"\{\{\s*main\s*\|\s*([^}|]+)", text[m.end():m.end() + 600], re.I) if m and not keep else None
            if main:
                keep = [b for b in boxes if b.get("page", "").lower() == main.group(1).strip().lower()]
        if keep:
            boxes = keep
    return boxes, pages, title, unreached


def _boxes_all(base):
    text, title = raw(base)
    _LAST.anchor_of_base, _LAST.text_of_base = getattr(_LAST, "anchor", ""), text or ""
    boxes, pages = [], []
    if not text:
        return boxes, pages, title, 0 if getattr(_LAST, "missing", False) else 1
    if len(text) < 6000:                       # a pointer page
        own = list(dict.fromkeys(re.findall(r"\[\[(" + re.escape(base) + r" \([^\]|#]+\))", text)))
        if own:                                # "Ford Puma (crossover)", "Ford Puma (sport compact)": each
            for link in own[:6]:
                t, tt = raw(link)
                if t:
                    boxes += infoboxes(t, tt)
            return boxes, own, title, 0
        m = re.search(r"\[\[(" + re.escape(base.split()[0]) + r" [^\]|#]+)", text)
        if m and m.group(1).strip() != base:
            text, title = raw(m.group(1).strip())
            if not text:
                return boxes, pages, title, 0 if getattr(_LAST, "missing", False) else 1
    boxes += infoboxes(text, title)
    stem = title.split(" (")[0]
    for link in re.findall(r"(?:\[\[|\{\{\s*(?:main|see also|further)\s*\|)\s*(" + re.escape(stem) + r"[^\]|}#]*)", text, re.I):
        link = link.strip()
        if link != title and link not in pages and _generation_link(link, stem):
            pages.append(link)
    unreached = 0
    for p in pages[:12]:
        t, tt = raw(p)
        if t is None and not getattr(_LAST, "missing", False):
            unreached += 1
        # a link can redirect to another make's car ("Toyota Yaris R" is the Mazda2)
        if t and tt.split()[0].lower() == stem.split()[0].lower():
            boxes += infoboxes(t, tt)
    if not boxes:
        # neither the page nor its generation pages give a size: its twin's
        boxes += _twin_boxes(text, title)
    return boxes, pages, title, unreached


def _twin_boxes(text, title):
    """A car whose page gives no size (the Peugeot 108: the Aygo and the C1
    built beside it): the size of the car its infobox calls related or
    also known as, of the generation built in the same years, named so."""
    m = re.search(r"\{\{\s*Infobox automobile(.*?)\n\}\}", text or "", re.S | re.I)
    if not m:
        return []
    box = m.group(1)
    yr = _years((re.search(r"\|\s*production\s*=([^\n]*)", box) or [None, ""])[1])
    links = []
    for k in ("related", "aka"):
        f = re.search(r"\|\s*" + k + r"\s*=([^\n]*)", box)
        links += re.findall(r"\[\[([^\]|#]+)", f.group(1)) if f else []
    out = []
    if not yr:
        return out
    for link in list(dict.fromkeys(l.strip() for l in links))[:3]:
        t, tt = raw(link)
        for b in infoboxes(t or "", tt):
            by = b.get("years")
            # each twin generation built in this car's years, for those years
            # only: an S3 made 1999 on is the A3 of each generation after it,
            # never the 1996 A3 for all of them
            if by and b.get("length") and max(by[0], yr[0]) < min(by[1], yr[1]):
                out.append(dict(b, page=title, years=(max(by[0], yr[0]), min(by[1], yr[1])),
                                name=f"{title} (sized as the {tt} {b.get('name') or ''})".strip(), twin_of=tt))
        if out:
            break
    return out


_LOCK = threading.Lock()                       # batch.py builds cars side by side
TABLE = os.path.join(HERE, "wheelbase_table.json")
_TABLE = {}


def local_table_path():
    """Cars looked up while the machine runs (a model the catalogue does not
    have, for a stand-in): kept in the work folder, beside the shipped table."""
    home = os.path.expanduser(os.environ.get("GLBMACHINE_HOME", "~/.glbmachine"))
    return os.path.join(home, "wheelbase_local.json")


# sizes a page gives wrongly, or for the body few of the cars are, set from
# the maker's published figures as listed by CarsGuide, Caroom, Carsales:
# {(page, generation): sizes}
PAGE_FIX = {("Renault Trafic", "Second generation (X83)"): {
    "height": 1959, "fixed": "height 1,959 mm, the low-roof van (CarsGuide, Caroom): the page's 1,380 mm is no van's"},
    ("Suzuki Vitara", "Third generation"): {
    "length": 4470, "wheelbase": 2640,
    "fixed": "the five-door's length and wheelbase, most of them (Carsales): the page gives the three-door's"},
    # a box that names no body, the page's text does
    ("Triumph Stag", "Triumph Stag"): {
    "body": "2-door convertible", "doors": 2,
    "fixed": "body from the page's text: 'All Stags were four-seater convertible coupés'"}}


def _fixed(boxes):
    return [dict(b, **PAGE_FIX[(b.get("page"), b.get("name"))]) if (b.get("page"), b.get("name")) in PAGE_FIX else b
            for b in boxes]


def table():
    if not _TABLE and os.path.exists(TABLE):
        _TABLE.update(json.load(open(TABLE)))
        try:
            # this machine's own lookups: what the shipped table lacks, has
            # found nothing for (a page the reader of its day could not read),
            # or a newer reader read again with more pages (the 2023 Fiat 600's)
            _TABLE.update({k: v for k, v in json.load(open(local_table_path())).items()
                           if k not in _TABLE or (not _TABLE[k].get("boxes") and (v.get("boxes") or
                                                  v.get("fetch_v", 1) > _TABLE[k].get("fetch_v", 1)))
                           or (v.get("boxes") and not v.get("failed")
                               and v.get("fetch_v", 1) > _TABLE[k].get("fetch_v", 1))})
        except (OSError, ValueError):
            pass
        for v in _TABLE.values():
            if v.get("boxes"):
                v["boxes"] = _fixed(v["boxes"])
    return _TABLE


def wiki_title(model):
    """A model name as Wikipedia titles it: Micra, E-Class, CR-V, GT-R, CX-5."""
    def word(w):
        if re.fullmatch(r"i\d+|ix\d+|e\d+", w):  # i10, i30, ix35: Hyundai keeps the small i (not Volvo's EX30)
            return w
        return re.sub(r"[a-z]+", lambda m: m.group(0).upper() if len(m.group(0)) <= 2 and re.search(r"[\d-]", w)
                      else m.group(0).title(), w)
    return " ".join(word(w) for w in model.split())


def fetch(make, model):
    """Every generation's infobox for a make and model (the outside call;
    only `--build` or GLBMACHINE_ONLINE=1 makes it). Boxes from the sister
    make's page carry base 1, so the make's own page wins a tie."""
    mt = MAKE_TITLE.get(make.lower(), make.title())
    mdl = model if re.search(r"[A-Z]", model) else wiki_title(model)
    bases = [ALIAS.get((make.lower(), model.lower()), f"{mt} {mdl}")]
    if "-" in model and not re.search(r"\d", model):           # range-rover-evoque, 3-series, gr-yaris
        spaced = wiki_title(model.replace("-", " "))
        bases.append(f"{mt} {spaced}")
        bases.append(f"{mt} " + " ".join(w.upper() if len(w) <= 2 else w for w in spaced.split()))   # GR Yaris
    m = re.fullmatch(r"([a-z]{1,3})[ -]class", model.lower())
    if m:
        bases.append(f"{mt} {m.group(1).upper()}-Class")        # Mercedes-Benz SLK-Class, A-Class
        bases.append(f"{mt} {m.group(1).upper()}")              # Mercedes-Benz EQA: no "-Class"
    if re.fullmatch(r"e\d+", model.lower()):
        bases.append(f"{mt} E{model[1:]}")                      # Omoda E5: titled with a capital E
    if re.fullmatch(r"ix\d*", model.lower()):
        bases.append(f"{mt} iX{model[2:]}")                     # BMW iX1, iX3
    if len(model) <= 3 and model.isalpha():
        bases.append(f"{mt} {model.upper()}")                   # MG HS, MG ZS: short names in capitals
    if len(make) <= 3 and make.isalpha() and mt != make.upper():
        bases.append(f"{make.upper()} {mdl}")                   # TVR, KGM, LDV: a short make in capitals
    if make.lower() in ACCENT:
        bases.append(f"{ACCENT[make.lower()]} {mdl}")
    bases += EXTRA.get((make.lower(), model.lower()), [])
    if make.lower() in SISTER:
        bases.append(f"{SISTER[make.lower()]} {mdl}")
    tried, uniq, failed = [], [], False
    for k, base in enumerate(bases):
        boxes, pages, title, unreached = _boxes_for(base)
        failed |= unreached > 0                   # unreachable (rate limit), not "no such page"
        tried += [title] + pages[:12]
        seen = {(tuple(b["years"] or ()), b["wheelbase"]) for b in uniq}
        uniq += [dict(b, base=k) for b in boxes if (tuple(b["years"] or ()), b["wheelbase"]) not in seen]
    out = {"boxes": uniq, "tried": tried, "fetch_v": FETCH_V, "asked": bases}
    if failed:
        out["failed"] = True                      # fetched again by the next --build
    return out


RACE = re.compile(r"\b(?:R5|R2|Rally2?|WRC|S1600|S2000|N5|DTM|BTCC|TCR|race|racing|rally|concept|prototype)\b", re.I)


def _succeeded(boxes):
    """Each generation's years as on sale here: one still built somewhere
    after its successor came (the Tiguan Mk2 runs on in China as the
    Tiguan L) ends the year the successor starts. A successor starts three
    or more years later and outlives it: a coupe launched beside the saloon
    (E-Class C207) or a rally car (Fiesta R5) is not one. A one-year overlap
    is left alone: the proportion settles it."""
    out = []
    for b in boxes:
        y = b.get("years")
        if y:
            nxt = [c["years"][0] for c in boxes if c is not b and c.get("years") and c.get("base", 0) == b.get("base", 0)
                   and c["years"][0] >= y[0] + 3 and c["years"][1] > y[1]]
            if nxt and y[1] > min(nxt):
                b = dict(b, years=(y[0], min(nxt)), years_listed=tuple(y))
        out.append(b)
    return out


FEW_DOORS = re.compile(r"\b[23][- ]?door|convertible|cabrio|coupe|coupé|roadster", re.I)


def choose(boxes, year, ratio=None, doors=None):
    """The generation on sale in YEAR; of two, the proportion nearer RATIO;
    else the newest. A car with rear DOORS is not a two- or three-door body
    of the same name."""
    # race and rally cars (Fiesta R5, Polo R WRC) are not the road car's generation
    road = [b for b in boxes if not RACE.search(b.get("name") or "")]
    if doors and doors >= 4:
        road = [b for b in road if not FEW_DOORS.search(b.get("body") or "") or (b.get("doors") or 0) >= 4] or road
    boxes = _succeeded(road or boxes)
    # the generation that was built that year; failing that, one that started
    # the year after (a car registered the year after it was built)
    on = [b for b in boxes if b["years"] and b["years"][0] <= year <= b["years"][1]] if year else list(boxes)
    if year and not on:
        on = [b for b in boxes if b["years"] and b["years"][0] - 1 <= year <= b["years"][1]]
    if on:
        first = min(b.get("base", 0) for b in on)
        on = [b for b in on if b.get("base", 0) == first]
    if len(on) > 1 and ratio:
        on.sort(key=lambda b: abs(b["wheelbase"] / b["length"] - ratio) if b.get("length") else 1)
    elif len(on) > 1:
        on.sort(key=lambda b: -(b["years"] or (0, 0))[0])
    if not on:
        return {"wheelbase": None, "why": f"no generation on sale in {year} among {len(boxes)} in the table"}
    # a size added by hand to the local table names where it came from
    return dict(on[0], source=on[0].get("source") or f"en.wikipedia: {on[0]['page']}", candidates=len(boxes))


def few_doors(make, model, year=None):
    """'3-door' or '2-door' when every generation of the model on sale in YEAR
    (every one, with no year) was built only with that many doors, from the
    table alone: the GR Yaris ('3-door hatchback'). None when any body had
    more, or the model is not in the table."""
    ent = table().get(f"{make}|{model}".lower())
    if not ent:
        return None
    boxes = [b for b in ent.get("boxes", []) if not RACE.search(b.get("name") or "")]
    if year:
        boxes = [b for b in boxes if b.get("years") and b["years"][0] - 1 <= year <= b["years"][1]]
    bodies = [b.get("body") or "" for b in boxes]
    if not bodies or not all(FEW_DOORS.search(x) for x in bodies) or any(re.search(r"[45][- ]?door|/\s*[45]", x) for x in bodies) \
            or any((b.get("doors") or 0) >= 4 for b in boxes):
        return None
    return "2-door" if all(re.search(r"\b2[- ]?door|coupe|coupé|convertible|cabrio|roadster", x, re.I) for x in bodies) \
        else "3-door"


# the page reader's version: an entry an older reader found nothing in is
# read again once (inches, electric cars' infoboxes, a twin's sizes, short
# names in capitals came with 2)
FETCH_V = 8                                      # 3: EX30, iX1, EQA spelt as titled; 4: TVR, KGM in capitals; 5: inch ranges
# 6, 7: the lead box's body (when it names one) for generations that name none; 8: the most doors of its bodies


def lookup(make, model, year, ratio=None, online=None, doors=None):
    key = f"{make}|{model}".lower()
    ent = table().get(key)
    # a page named for the model since it was read (ALIAS, EXTRA): read again, once
    need = [x for x in [ALIAS.get((make.lower(), model.lower())), *EXTRA.get((make.lower(), model.lower()), [])] if x]
    unread = ent is not None and any(x not in (ent.get("asked") or ent.get("tried") or []) for x in need)
    # an entry with no box of full size (a height in an inch range the reader
    # once missed) is read again by a newer reader, as an empty one is
    whole = ent is not None and any(all(b_.get(k) for k in ("length", "width", "height", "wheelbase"))
                                    for b_ in ent.get("boxes") or [])
    # and one whose boxes name no body, by a reader that keeps the lead box's
    bodied = ent is not None and (ent.get("fetch_v", 1) >= 7 or any(
        b_.get("body") or b_.get("class") for b_ in ent.get("boxes") or []))
    if ent is None or ((((not whole or not bodied) and ent.get("fetch_v", 1) < FETCH_V) or unread)
                       and (online if online is not None else os.environ.get("GLBMACHINE_ONLINE") == "1")):
        if not (online if online is not None else os.environ.get("GLBMACHINE_ONLINE") == "1"):
            return {"wheelbase": None, "why": f"{make} {model} is not in the wheelbase table"}
        ent = fetch(make, model)
        with _LOCK:
            _TABLE[key] = ent
            p = local_table_path()
            try:
                loc = json.load(open(p))
            except (OSError, ValueError):
                loc = {}
            loc[key] = ent
            os.makedirs(os.path.dirname(p), exist_ok=True)
            json.dump(loc, open(p + ".tmp", "w"), indent=0, sort_keys=True)
            os.replace(p + ".tmp", p)
    return choose(named_wheelbase(_fixed(ent["boxes"]), model), year, ratio, doors)       # a fresh read's too


def named_wheelbase(boxes, model):
    """For a model named by its wheelbase in inches (the Land Rover 88, 109),
    the boxes of that wheelbase, when the page gives them; else BOXES."""
    if re.fullmatch(r"\d{2,3}", str(model)) and 80 <= int(model) <= 135:
        return [b for b in boxes if str(b.get("name") or "").endswith(f"({model})")] \
            or [b for b in boxes if b.get("wheelbase") and abs(b["wheelbase"] - int(model) * 25.4) <= 20] or boxes
    return boxes


def build(workers=3):
    """The table for every approved catalogue model, fetched once."""
    from concurrent.futures import ThreadPoolExecutor
    sys.path.insert(0, HERE)
    import batch
    want = sorted({batch.model_of(i) for i in batch.catalogue().values()
                   if i.get("publicationStatus") == "approved" and i.get("desktopGlbUrl")})
    todo = [mm for mm in want if f"{mm[0]}|{mm[1]}".lower() not in table()
            or table()[f"{mm[0]}|{mm[1]}".lower()].get("failed")]
    print(f"{len(want)} makes and models, {len(todo)} to fetch", flush=True)

    def one(mm):
        try:
            return mm, fetch(*mm)
        except Exception as e:
            return mm, {"boxes": [], "tried": [], "error": str(e), "failed": True}
    done = 0
    with ThreadPoolExecutor(workers) as ex:
        for (make, model), ent in ex.map(one, todo):
            with _LOCK:
                _TABLE[f"{make}|{model}".lower()] = ent
                done += 1
                if done % 25 == 0 or done == len(todo):
                    json.dump(_TABLE, open(TABLE + ".tmp", "w"), indent=0, sort_keys=True)
                    os.replace(TABLE + ".tmp", TABLE)
                    print(done, "fetched", flush=True)


if __name__ == "__main__":
    if "--build" in sys.argv:
        if "--all" in sys.argv:            # read every page again (after a parser fix)
            for k in table():
                _TABLE[k]["failed"] = True
        build()
        sys.exit()
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    ratio = next((float(x.split("=")[1]) for x in sys.argv if x.startswith("--ratio=")), None)
    print(json.dumps(lookup(a[0], " ".join(a[1:-1]), int(a[-1]), ratio), indent=1))
