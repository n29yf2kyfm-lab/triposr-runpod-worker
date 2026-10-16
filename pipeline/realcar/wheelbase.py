#!/usr/bin/env python3
"""wheelbase.py — a model's published wheelbase, found without a person.

    python3 pipeline/realcar/wheelbase.py nissan micra 2004 [--ratio 0.62]

A catalogue model that is not at metre scale has to be scaled to the real
car, and the wheelbase is the figure that fixes the scale best (it is not
changed by bumpers or spoilers). This reads English Wikipedia's page text
(index.php?action=raw: the search API is often rate-limited on shared
addresses, the page text is not):

  1. the model's page ("Nissan Micra"), following a redirect;
  2. every generation page it links to ("Nissan Micra (K12)", "Ford Fiesta
     (sixth generation)", "Volkswagen Golf Mk8"), up to 12;
  3. every {{Infobox automobile}} on them: production years, wheelbase and
     length (the first figure given, which is the main body style's).

The infobox on sale in the given year wins. When two are (a generation
change that year: the A-Class W176 ended and the W177 began in 2018), the
one whose wheelbase-to-length proportion is closest to the 3D model's
(`ratio`) wins. Every answer, and every miss, is cached in
wheelbase_cache.json so a car is looked up once.
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
CACHE = os.path.join(HERE, "wheelbase_cache.json")
UA = "ExpertCarCheck-GLB/1.0 (car model sizing; https://github.com/n29yf2kyfm-lab/triposr-runpod-worker)"
MAKE_TITLE = {"mercedes-benz": "Mercedes-Benz", "volkswagen": "Volkswagen", "bmw": "BMW", "mg": "MG", "byd": "BYD",
              "land-rover": "Land Rover", "alfa-romeo": "Alfa Romeo", "aston-martin": "Aston Martin",
              "rolls-royce": "Rolls-Royce", "mini": "Mini", "ds": "DS", "seat": "SEAT", "kia": "Kia"}


def raw(title, _seen=None):
    """Page wikitext, redirects followed (twice at most)."""
    url = "https://en.wikipedia.org/w/index.php?" + urllib.parse.urlencode({"title": title, "action": "raw"})
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                t = r.read().decode("utf-8", "replace")
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
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


def _mm(v):
    """The first length in mm in an infobox value: {{convert|2430|mm|..}},
    {{convert|2548-2564|mm|..}} or {{convert|4292|-|4367|mm|..}} (a range:
    its middle), '2,430 mm'."""
    v = _clean(v)
    m = re.search(r"\{\{\s*(?:convert|cvt)\s*\|([^{}]*?)\|\s*mm\b", v, re.I)
    if m:
        nums = [float(x.replace(",", "")) for x in re.findall(r"[\d,]+(?:\.\d+)?", m.group(1))]
    else:
        m = re.search(r"([\d,]{4,6})\s*(?:[-–]\s*([\d,]{4,6})\s*)?mm", v)
        nums = [float(x.replace(",", "")) for x in m.groups() if x] if m else []
    nums = [n for n in nums if 1500 <= n <= 7000]
    return int(round((nums[0] + nums[-1]) / 2)) if nums else None


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
        for f in re.finditer(r"\|\s*([a-z_ ]+?)\s*=\s*(.*?)(?=\n\s*\|\s*[a-z_ ]+?\s*=|\}\}\s*$)", box, re.S | re.I):
            fields[f.group(1).strip().lower()] = f.group(2)
        wb = _mm(fields.get("wheelbase", ""))
        if not wb:
            continue
        yr = _years(fields.get("production", "")) or _years(fields.get("model_years", ""))
        out.append({"page": title, "name": re.sub(r"\[\[|\]\]|'''|''", "", fields.get("name", "")).strip()[:80],
                    "years": yr, "wheelbase": wb, "length": _mm(fields.get("length", ""))})
    return out


# a make's other name, for when its own page has no generations
SISTER = {"vauxhall": "Opel", "opel": "Vauxhall", "mini": "Mini", "dacia": "Renault", "seat": "SEAT"}
# a model's other page name
ALIAS = {("mini", "cooper"): "Mini Hatch", ("mini", "hatch"): "Mini Hatch", ("honda", "jazz"): "Honda Fit"}


def _generation_link(link, stem):
    """A generation's own page, not a spin-off: 'Nissan Micra (K12)', 'Ford
    Fiesta (sixth generation)', 'Volkswagen Golf Mk8', 'Opel Astra K' - but
    not 'Fiat 500L' or 'Volkswagen Polo GTI'."""
    rest = link[len(stem):]
    return bool(re.fullmatch(r"\s*\([^)]*\)|\s+Mk\s?\d+[^ ]*(\s*\([^)]*\))?|\s+[A-Z]{1,2}\d{0,3}|\s+\w+ generation", rest))


def _boxes_for(base):
    text, title = raw(base)
    boxes, pages = [], []
    if not text:
        return boxes, pages, title
    if len(text) < 6000:                       # a pointer page: follow its first car link
        m = re.search(r"\[\[(" + re.escape(base.split()[0]) + r" [^\]|#]+)", text)
        if m and m.group(1).strip() != base:
            text, title = raw(m.group(1).strip())
            if not text:
                return boxes, pages, title
    boxes += infoboxes(text, title)
    stem = title.split(" (")[0]
    for link in re.findall(r"(?:\[\[|\{\{\s*(?:main|see also|further)\s*\|)\s*(" + re.escape(stem) + r"[^\]|}#]*)", text, re.I):
        link = link.strip()
        if link != title and link not in pages and _generation_link(link, stem):
            pages.append(link)
    for p in pages[:12]:
        t, tt = raw(p)
        if t:
            boxes += infoboxes(t, tt)
    return boxes, pages, title


_LOCK = threading.Lock()                       # batch.py builds cars side by side


def lookup(make, model, year, ratio=None, key=None, use_cache=True):
    key = key or f"{make}|{model}|{year}".lower()
    with _LOCK:
        cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    if use_cache and key in cache:
        return cache[key]
    mt = MAKE_TITLE.get(make.lower(), make.title())
    mdl = model if re.search(r"[A-Z]", model) else model.title()
    bases = [ALIAS.get((make.lower(), model.lower()), f"{mt} {mdl}")]
    if make.lower() in SISTER:
        bases.append(f"{SISTER[make.lower()]} {mdl}")
    tried, uniq = [], []
    for base in bases:
        boxes, pages, title = _boxes_for(base)
        tried += [title] + pages[:12]
        seen = {(b["years"], b["wheelbase"]) for b in uniq}
        uniq += [b for b in boxes if (b["years"], b["wheelbase"]) not in seen]
        if any(b["years"] and year and b["years"][0] - 1 <= year <= b["years"][1] for b in uniq):
            break
    on = [b for b in uniq if b["years"] and b["years"][0] - 1 <= year <= b["years"][1]] if year else uniq
    if len(on) > 1 and ratio:
        on.sort(key=lambda b: abs(b["wheelbase"] / b["length"] - ratio) if b.get("length") else 1)
    elif len(on) > 1:                          # the newest generation on sale that year
        on.sort(key=lambda b: -(b["years"] or (0, 0))[0])
    ans = dict(on[0], source=f"en.wikipedia: {on[0]['page']}", candidates=len(uniq)) if on else \
        {"wheelbase": None, "why": f"no infobox on sale in {year} among {len(uniq)} on {len(tried)} pages",
         "tried": tried}
    with _LOCK:
        cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
        cache[key] = ans
        json.dump(cache, open(CACHE + ".tmp", "w"), indent=1, sort_keys=True)
        os.replace(CACHE + ".tmp", CACHE)
    return ans


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    ratio = next((float(x.split("=")[1]) for x in sys.argv if x.startswith("--ratio=")), None)
    print(json.dumps(lookup(a[0], " ".join(a[1:-1]), int(a[-1]), ratio, use_cache=False), indent=1))
