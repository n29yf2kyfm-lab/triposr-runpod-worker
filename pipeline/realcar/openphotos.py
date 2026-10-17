#!/usr/bin/env python3
"""openphotos.py — a local index of openly licensed car photographs, for
photos.py: the Yahoo Flickr Creative Commons set (YFCC100M), in the 15-million
photo subset published on Hugging Face (mehdidc/yfcc15m: each photo's title,
tags, description, date taken, licence and Flickr address; photos taken
2004-2014).

    python3 pipeline/realcar/openphotos.py --build     # once: streams 10 GB (~5 min), keeps the car photos
    python3 pipeline/realcar/openphotos.py --find Ford Focus 2008

Only CC BY and CC BY-SA photos are kept, the licences a business may use;
the non-commercial and no-derivatives ones are left out. A photo is fetched
from Flickr only when a search uses it, and only measured. The index is
built on the machine that runs it ($GLBMACHINE_HOME/open_photos.jsonl) and
is not shipped.

Why: Wikimedia Commons, the other big source of side views, refuses busy
shared addresses, and Hugging Face serves this set from any address.
"""
import csv
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.abspath(os.path.expanduser(os.environ.get("GLBMACHINE_HOME", "~/.glbmachine")))
INDEX = os.path.join(HOME, "open_photos.jsonl")
SOURCE = "https://huggingface.co/datasets/mehdidc/yfcc15m/resolve/main/yfcc15m.csv"
LICENCE = {"Attribution License": "CC BY 2.0", "Attribution-ShareAlike License": "CC BY-SA 2.0"}
MAKES = ["abarth", "alfa romeo", "aston martin", "audi", "bentley", "bmw", "chevrolet", "chrysler", "citroen",
         "citroën", "cupra", "dacia", "daewoo", "daihatsu", "dodge", "ds", "ferrari", "fiat", "ford", "honda",
         "hyundai", "infiniti", "isuzu", "jaguar", "jeep", "kia", "lamborghini", "land rover", "landrover",
         "range rover", "lexus", "lotus", "maserati", "mazda", "mercedes", "mercedes-benz", "mg", "mini",
         "mitsubishi", "nissan", "opel", "peugeot", "porsche", "proton", "renault", "rover", "saab", "seat",
         "skoda", "škoda", "smart", "ssangyong", "subaru", "suzuki", "tesla", "toyota", "vauxhall", "volkswagen",
         "vw", "volvo"]
MAKE_RX = re.compile(r"\b(?:" + "|".join(re.escape(m).replace(r"\ ", r"[\s+_-]?") for m in MAKES) + r")\b", re.I)
ALIAS = {"volkswagen": ["volkswagen", "vw"], "mercedes-benz": ["mercedes", "mercedes-benz", "benz"],
         "land-rover": ["land rover", "landrover"], "skoda": ["skoda", "škoda"], "citroen": ["citroen", "citroën"],
         "vauxhall": ["vauxhall", "opel"], "alfa-romeo": ["alfa romeo", "alfa"]}


def _text(s):
    return urllib.parse.unquote_plus(s or "")


def build(dst=INDEX, src=SOURCE):
    """Stream the set once and keep the commercially licensed photos that
    name a car make in their title or tags."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    t0, n, kept = time.time(), 0, 0
    with urllib.request.urlopen(urllib.request.Request(src, headers={"User-Agent": "ecc-glbmachine/1.0"}),
                                timeout=120) as r, open(dst + ".tmp", "w") as out:
        rd = csv.DictReader(io.TextIOWrapper(r, encoding="utf-8", errors="replace", newline=""))
        for row in rd:
            n += 1
            lic = LICENCE.get(row.get("licensename") or "")
            if not lic:
                continue
            title, tags = _text(row.get("title")), _text(row.get("usertags")).replace(",", " ")
            if not MAKE_RX.search(title + " " + tags):
                continue
            out.write(json.dumps({"id": row.get("photoid"), "title": title[:200], "tags": tags[:400],
                                  "taken": (row.get("datetaken") or "")[:10], "licence": lic,
                                  "author": _text(row.get("unickname"))[:80], "url": row.get("downloadurl"),
                                  "page": row.get("pageurl")}, ensure_ascii=False) + "\n")
            kept += 1
            if n % 1000000 == 0:
                print(f"  {n:,} photos read, {kept:,} kept ({time.time() - t0:.0f} s)", flush=True)
    os.replace(dst + ".tmp", dst)
    print(json.dumps({"read": n, "kept": kept, "seconds": round(time.time() - t0), "index": dst}), flush=True)


_ROWS = []


def rows():
    if not _ROWS and os.path.exists(INDEX):
        _ROWS.extend(json.loads(l) for l in open(INDEX, encoding="utf-8"))
    return _ROWS


def candidates(make, model, years=None):
    """The index's photos naming MAKE and every word of MODEL, as photos.py's
    candidates. A photo taken before the generation was on sale cannot show
    it, and is left out. Width and height are not known until downloaded."""
    names = ALIAS.get(make.lower(), [make.lower().replace("-", " ")])
    mk = re.compile(r"\b(?:" + "|".join(re.escape(x).replace(r"\ ", r"[\s+_-]?") for x in names) + r")\b", re.I)
    words = [re.compile(r"\b" + re.escape(w) + r"\b", re.I) for w in re.split(r"[\s-]+", model.lower()) if w]
    y0 = (years or [None])[0]
    out = []
    for r in rows():
        s = r["title"] + " " + r["tags"]
        if not mk.search(s) or not all(w.search(s) for w in words):
            continue
        taken = int(r["taken"][:4]) if r["taken"][:4].isdigit() else None
        if y0 and taken and taken < y0:
            continue
        out.append({"title": r["title"] or r["id"], "url": r["url"], "w": None, "h": None, "source": "flickr-yfcc",
                    "thumb": None, "tags": r["tags"], "taken": taken,
                    "licence": r["licence"], "author": r["author"], "page": r["page"]})
    return out


if __name__ == "__main__":
    if "--build" in sys.argv:
        build()
    elif "--find" in sys.argv:
        a = sys.argv[sys.argv.index("--find") + 1:]
        for c in candidates(a[0], " ".join(a[1:-1]) if a[-1].isdigit() else " ".join(a[1:]),
                            [int(a[-1])] if a[-1].isdigit() else None)[:30]:
            print(c["taken"], c["licence"], c["title"][:70], "|", c["tags"][:60], c["url"])
    else:
        print(__doc__)
