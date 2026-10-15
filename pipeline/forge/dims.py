#!/usr/bin/env python3
"""dims.py — a car's published dimensions, from the repo first, Wikipedia second.

Forge scales a car from its manufacturer's figures and never from pixels
(the accuracy rule in CLAUDE.md), so the agent needs length, width, height
and wheelbase for every target. Three sources, in order:

  1. platform/geometry/vehicle_dims.csv (366 rows, 168 complete), by
     make/model/generation;
  2. pipeline/authoring/parametric_car.SPECS;
  3. the English Wikipedia infobox of the model's generation page, read
     through the public API and parsed from the wikitext ({{convert|4284|mm..}}
     or "4,284 mm"). Values outside a car's physical range are rejected.

Every answer, and every failure, is cached in dims_cache.json next to this
file so a re-run never asks twice. Wikimedia rate-limits shared addresses:
calls back off for up to two minutes before giving up on a title.
"""
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
CACHE = os.path.join(HERE, "dims_cache.json")
UA = {"User-Agent": "ecc-forge/0.1 (https://github.com/n29yf2kyfm-lab/triposr-runpod-worker; dims fetcher)"}
RANGE = {"length": (2400, 7500), "width": (1350, 2400), "height": (1100, 2900), "wheelbase": (1700, 4300)}
ORD = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth", 7: "seventh", 8: "eighth",
       9: "ninth", 10: "tenth", 11: "eleventh", 12: "twelfth"}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _cache():
    try:
        return json.load(open(CACHE))
    except Exception:
        return {}


def _save(c):
    json.dump(c, open(CACHE, "w"), indent=1, sort_keys=True)


def api(params, tries=5):
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(dict(params, format="json", formatversion=2))
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(25 * (i + 1))
                continue
            return None
        except Exception:
            time.sleep(5)
    return None


def _mm(value):
    """First plausible millimetre figure in an infobox value."""
    if not value:
        return None
    v = value.replace(",", "")
    m = re.search(r"\{\{\s*(?:cvt|convert)\s*\|\s*(\d{3,5})(?:\s*[-–]\s*\d{3,5})?\s*\|\s*mm", v, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d{4})\s*(?:mm|millimet)", v, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"(?<!\d)(\d{4})(?!\d)", v)
    return int(m.group(1)) if m else None


def parse_infobox(wikitext):
    out = {}
    for k in ("length", "width", "height", "wheelbase"):
        for m in re.finditer(r"^\|\s*" + k + r"\s*=\s*(.*)$", wikitext, re.M):
            n = _mm(m.group(1))
            if n and RANGE[k][0] <= n <= RANGE[k][1]:
                out[k] = n
                break
    return out


def from_wikipedia(make, model, generation=None):
    """Try generation-specific titles first, then the model page."""
    Make, Model = make.replace("-", " ").title().replace("Bmw", "BMW").replace("Mg", "MG"), model
    titles = []
    if generation:
        g = str(generation)
        titles.append(f"{Make} {Model} {g}")
        m = re.match(r"(?:mk|mark)\s*(\d+)", g, re.I)
        if m and int(m.group(1)) in ORD:
            titles.append(f"{Make} {Model} ({ORD[int(m.group(1))]} generation)")
        titles.append(f"{Make} {Model} ({g})")
    titles.append(f"{Make} {Model}")
    for t in titles:
        d = api({"action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main",
                 "titles": t, "redirects": 1})
        if not d:
            continue
        pages = d.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing"):
            continue
        text = pages[0].get("revisions", [{}])[0].get("slots", {}).get("main", {}).get("content", "")
        got = parse_infobox(text)
        if all(k in got for k in ("length", "width", "height", "wheelbase")):
            got["source"] = f"en.wikipedia: {pages[0]['title']}"
            return got
        time.sleep(2)
    return None


def from_csv(make, model, generation=None):
    p = os.path.join(REPO, "platform", "geometry", "vehicle_dims.csv")
    if not os.path.exists(p):
        return None
    rows = [r for r in csv.DictReader(open(p)) if norm(r["make"]) == norm(make) and norm(r["model"]) == norm(model)
            and all(r[k] for k in ("length_mm", "width_mm", "height_mm", "wheelbase_mm"))]
    if generation:
        g = [r for r in rows if norm(r["generation"]) == norm(generation)]
        rows = g or rows
    if not rows:
        return None
    r = rows[0]
    return {"length": int(r["length_mm"]), "width": int(r["width_mm"]), "height": int(r["height_mm"]),
            "wheelbase": int(r["wheelbase_mm"]), "source": f"vehicle_dims.csv: {r['source_page']}"}


def from_specs(make, model):
    sys.path.insert(0, os.path.join(HERE, "..", "authoring"))
    from parametric_car import SPECS
    for (mk, md), s in SPECS.items():
        if norm(mk) == norm(make) and norm(md) == norm(model):
            return dict(length=s["length"], width=s["width"], height=s["height"], wheelbase=s["wheelbase"],
                        track=s["track"], wheel_d=s["wheel_d"], tyre_w=s["tyre_w"], source="parametric_car.SPECS")
    return None


def get_dims(make, model, generation=None):
    key = f"{norm(make)}|{norm(model)}|{norm(generation)}"
    c = _cache()
    if key in c:
        return c[key]
    got = from_csv(make, model, generation) or from_specs(make, model) or from_wikipedia(make, model, generation)
    c[key] = got
    _save(c)
    return got


if __name__ == "__main__":
    a = sys.argv[1:]
    print(json.dumps(get_dims(a[0], a[1], a[2] if len(a) > 2 else None), indent=1))
