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
    m = re.match(r"\s*#REDIRECT\s*\[\[([^\]|#]+)", t, re.I)
    if m and (_seen or 0) < 2:
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
    if m:
        nums = [float(x.replace(",", "")) for x in re.findall(r"[\d,]+(?:\.\d+)?", m.group(1))]
    else:
        m = re.search(r"([\d,]{4,6})\s*(?:[-–]\s*([\d,]{4,6})\s*)?mm", v)
        nums = [float(x.replace(",", "")) for x in m.groups() if x] if m else []
    nums = [n for n in nums if lo <= n <= hi]
    return int(round((nums[0] + nums[-1]) / 2)) if nums else None


def _text(v):
    """An infobox value as plain words, its first line or list item only
    ('{{ubl|5-door [[hatchback]]|...}}' -> '5-door hatchback')."""
    v = re.sub(r"<br\s*/?>|\s/\s|;", "\n", _clean(v), flags=re.I)
    v = re.sub(r"\{\{\s*(?:ubl|unbulleted list|plainlist|flatlist|hlist)\s*\|?", "", v, flags=re.I)
    v = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", v)
    v = re.sub(r"\{\{[^{}]*\}\}|<[^>]+>|'{2,3}", " ", v)
    first = next((x for x in re.split(r"\n|\*|\|", v) if x.strip(" }{")), "")
    return " ".join(first.strip(" }{").split())


def body_family(body, cls="", name=""):
    """hatch, saloon, estate, suv, mpv, coupe, convertible, pickup or van,
    from a generation's body style, else its class, else its name."""
    for text in (body, cls, name):
        t = (text or "").lower()
        for fam, rx in (("convertible", r"convertible|cabrio|roadster|spider|spyder|targa"),
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


def infoboxes(text, title):
    out = []
    for m in re.finditer(r"\{\{\s*Infobox automobile", text, re.I):
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
            continue
        yr = _years(fields.get("production", "")) or _years(fields.get("model_years", ""))
        out.append({"page": title, "name": re.sub(r"\[\[|\]\]|'''|''", "", fields.get("name", "")).strip()[:80],
                    "years": yr, "wheelbase": wb, "length": _mm(fields.get("length", "")),
                    "width": _mm(fields.get("width", ""), 1300, 2700), "height": _mm(fields.get("height", ""), 1000, 2600),
                    "body": _text(fields.get("body_style", ""))[:80], "class": _text(fields.get("class", ""))[:80]})
    return out


# a make's other name, for when its own page has no generations
SISTER = {"vauxhall": "Opel", "opel": "Vauxhall", "mini": "Mini", "dacia": "Renault", "seat": "SEAT"}
# a model's other page name
ALIAS = {("mini", "cooper"): "Mini Hatch", ("mini", "hatch"): "Mini Hatch", ("honda", "jazz"): "Honda Fit"}
# more pages that hold a model's generations: the first three Yaris
# generations are filed under the Japanese name
EXTRA = {("toyota", "yaris"): ["Toyota Vitz"]}


def _generation_link(link, stem):
    """A generation's own page, not a spin-off: 'Nissan Micra (K12)', 'Ford
    Fiesta (sixth generation)', 'Volkswagen Golf Mk8', 'Opel Astra K' - but
    not 'Fiat 500L' or 'Volkswagen Polo GTI'."""
    rest = link[len(stem):]
    return bool(re.fullmatch(r"\s*\([^)]*\)|\s+Mk\s?\d+[^ ]*(\s*\([^)]*\))?|\s+[A-Z]{1,2}\d{0,3}|\s+\w+ generation", rest))


def _boxes_for(base):
    """(boxes, generation pages, title, pages that could not be reached)."""
    text, title = raw(base)
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
    return boxes, pages, title, unreached


_LOCK = threading.Lock()                       # batch.py builds cars side by side
TABLE = os.path.join(HERE, "wheelbase_table.json")
_TABLE = {}


def local_table_path():
    """Cars looked up while the machine runs (a model the catalogue does not
    have, for a stand-in): kept in the work folder, beside the shipped table."""
    home = os.path.expanduser(os.environ.get("GLBMACHINE_HOME", "~/.glbmachine"))
    return os.path.join(home, "wheelbase_local.json")


def table():
    if not _TABLE and os.path.exists(TABLE):
        _TABLE.update(json.load(open(TABLE)))
        try:
            _TABLE.update({k: v for k, v in json.load(open(local_table_path())).items() if k not in _TABLE})
        except (OSError, ValueError):
            pass
    return _TABLE


def wiki_title(model):
    """A model name as Wikipedia titles it: Micra, E-Class, CR-V, GT-R, CX-5."""
    def word(w):
        if re.fullmatch(r"[ie]\d+", w):           # i10, i30: Hyundai keeps the small i
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
    out = {"boxes": uniq, "tried": tried}
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


def choose(boxes, year, ratio=None):
    """The generation on sale in YEAR; of two, the proportion nearer RATIO;
    else the newest."""
    # race and rally cars (Fiesta R5, Polo R WRC) are not the road car's generation
    road = [b for b in boxes if not RACE.search(b.get("name") or "")]
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
    return dict(on[0], source=f"en.wikipedia: {on[0]['page']}", candidates=len(boxes))


def lookup(make, model, year, ratio=None, online=None):
    key = f"{make}|{model}".lower()
    ent = table().get(key)
    if ent is None:
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
    return choose(ent["boxes"], year, ratio)


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
