#!/usr/bin/env python3
"""make.py — ask for a car in plain words, get it back finished.

    BLENDER_BIN=... python3 pipeline/realcar/make.py "Mercedes A-Class 2012 black 5-door" \
        --engine-pack engine_pack.glb --tools TOOLS_DIR --view-dir VIEW_DIR [--nearest]

The request is read for a make and model, a year, a colour (DVLA colour
names), and a door count or body style. The approved catalogue is searched
for that model in a generation on sale in that year. Then the same steps as
batch.py run:

    rig machine -> finish.py -> validator -> web copy -> check sheet

The finish uses the generic petrol engine bay (or the model's own, if it has
one) and paints the car in the colour asked for.

If the catalogue has no such car, or not in that year's generation, it is
sourced: Sketchfab is searched (source.py: a CC licence, the model in the
title, no toy or game cars, the nearest year) and the best hit downloaded
with SKETCHFAB_TOKEN. Failing that, --nearest builds the catalogue's
nearest generation. Every step is timed; a catalogue car takes about 35 s. The catalogue does not record door counts, so a door count
is only reported back, never used to choose.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import batch  # noqa: E402
import source  # noqa: E402

# DVLA colour names, as a typical paint of that name (sRGB)
COLOURS = {
    "black": (16, 16, 18), "white": (236, 236, 233), "silver": (186, 189, 192), "grey": (108, 111, 115),
    "gray": (108, 111, 115), "blue": (24, 52, 118), "red": (152, 16, 22), "green": (28, 78, 44),
    "yellow": (232, 190, 28), "orange": (222, 98, 20), "brown": (84, 54, 34), "beige": (201, 186, 150),
    "gold": (182, 150, 80), "bronze": (140, 100, 60), "purple": (78, 30, 92), "maroon": (88, 14, 24),
    "turquoise": (28, 140, 140), "pink": (220, 120, 160), "cream": (236, 226, 196),
}
MAKES = {"mercedes": "mercedes-benz", "merc": "mercedes-benz", "benz": "mercedes-benz", "vw": "volkswagen",
         "landrover": "land-rover", "rangerover": "land-rover", "alfa": "alfa-romeo", "astonmartin": "aston-martin",
         "rollsroyce": "rolls-royce", "opel": "vauxhall"}
BODIES = ("hatchback", "saloon", "sedan", "estate", "coupe", "convertible", "suv", "mpv", "van", "pickup", "roadster")


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def parse(text):
    t = text.lower()
    want = {"text": text}
    m = re.search(r"\b(19[5-9]\d|20[0-3]\d)\b", t)
    if m:
        want["year"] = int(m.group(1))
        t = t.replace(m.group(1), " ")
    m = re.search(r"\b([2-5])[\s-]*(?:door|dr)s?\b", t)
    if m:
        want["doors"] = int(m.group(1))
        t = t[:m.start()] + " " + t[m.end():]
    for c in COLOURS:
        if re.search(rf"\b{c}\b", t):
            want["colour"] = c
            t = re.sub(rf"\b{c}\b", " ", t)
            break
    for b in BODIES:
        if re.search(rf"\b{b}\b", t):
            want["body"] = "saloon" if b == "sedan" else b
            t = re.sub(rf"\b{b}\b", " ", t)
    want["words"] = t.strip()
    return want


def find(want, cat):
    q = norm(want["words"])
    makes = {norm(i["make"]): i["make"].lower() for i in cat.values()}
    make, rest = None, q
    for k in sorted(set(makes) | set(MAKES), key=len, reverse=True):
        if q.startswith(k) or k in q:
            make = MAKES.get(k, makes.get(k))
            rest = q.replace(k, "", 1)
            break
    want["make"], want["model_words"] = make, None
    if not make:
        return None, [], "no make recognised"
    # the model words as typed, for a search outside the catalogue
    toks = want["words"].replace("-", " ").split()
    for k in range(1, len(toks) + 1):
        if norm(" ".join(toks[:k])) in (norm(make), *[a for a, b in MAKES.items() if b == make]):
            want["model_words"] = " ".join(toks[k:])
            break
    if want["model_words"] is None:
        want["model_words"] = " ".join(toks[1:])
    pool = [i for i in cat.values() if norm(i["make"]) == norm(make) and i.get("publicationStatus") == "approved"
            and i.get("desktopGlbUrl")]

    def names(i):
        return {norm(n) for n in [i.get("model"), i.get("modelFamily"), *(i.get("modelAliases") or [])] if n}
    best, hits = 0, []
    for i in pool:
        for n in names(i):
            n2 = n.replace(norm(make), "")
            if n2 and n2 in rest and len(n2) >= best:
                if len(n2) > best:
                    best, hits = len(n2), []
                hits.append(i)
                break
    if not hits:
        return None, [], "not in the catalogue"
    if want.get("body"):
        hb = [i for i in hits if (i.get("bodyStyle") or want["body"]) == want["body"]]
        hits = hb or hits
    yr = want.get("year")

    def years(i):
        y0 = i.get("yearStart") or 0
        return y0, i.get("yearEnd") or y0 + 7
    if yr:
        on_sale = [i for i in hits if years(i)[0] - 1 <= yr <= years(i)[1]]
        others = sorted(hits, key=lambda i: min(abs(yr - years(i)[0]), abs(yr - years(i)[1])))
    else:
        on_sale, others = hits, hits
    order = lambda L: sorted(L, key=lambda i: -((i.get("yearStart") or 1990) - 4 * batch.GRADE.get(i.get("qualityGrade"), 3)))  # noqa: E731
    if on_sale:
        return order(on_sale)[0], others, "exact generation"
    return None, others, "model found, not that year's generation"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("request")
    ap.add_argument("--engine-pack", required=True)
    ap.add_argument("--tools", required=True)
    ap.add_argument("--view-dir", required=True)
    ap.add_argument("--out", default=None, help="default: VIEW_DIR/make")
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--nearest", action="store_true", help="build the nearest catalogue generation if none is sourced")
    ap.add_argument("--no-source", action="store_true", help="catalogue only, no Sketchfab search")
    args = ap.parse_args()
    args.engine_pack = os.path.abspath(args.engine_pack)
    want = parse(args.request)
    cat = batch.catalogue()
    item, others, why = find(want, cat)
    report = {"asked": want, "match": why,
              "nearest": [f"{i['assetId']} ({i.get('yearStart')}-{i.get('yearEnd') or ''})" for i in others[:4]]}
    # not in the catalogue, or not that year's generation: source it
    if item is None and want.get("make") and not args.no_source:
        try:
            ok, refused = source.search(want["make"], want["model_words"], want.get("year"))
            report["sourcing"] = {"candidates": [f"{o['name']} by {o['author']} ({o['licence']}, {o['faces']} faces)"
                                                 for o in ok[:4]], "refused": len(refused)}
            if ok:
                item = source.as_item(ok[0], want["make"], want["model_words"], want.get("year"))
                report["match"] = f"{why}; sourced from Sketchfab"
        except Exception as e:
            report["sourcing_error"] = str(e)
    if item is None and args.nearest and others:
        item, report["match"] = others[0], f"{why}; building the nearest catalogue generation"
    if item is None:
        print(json.dumps(report, indent=1))
        sys.exit(2)
    report["asset"] = item["assetId"]
    report["source"] = item.get("sourceTitle")
    if want.get("doors"):
        report["doors_note"] = "door count reported back only: the catalogue does not record it"
    args.paint = COLOURS.get(want.get("colour"))
    out = args.out or os.path.join(args.view_dir, "make")
    os.makedirs(out, exist_ok=True)
    server = subprocess.Popen([sys.executable, "-m", "http.server", str(args.port)], cwd=args.view_dir,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    try:
        t0 = time.time()
        rec = batch.one({"rank": 0, "genModel": args.request}, item, args, out)
        rec["seconds"] = round(time.time() - t0)
    finally:
        server.terminate()
    report["result"] = rec
    report["files"] = {k: os.path.join(out, item["assetId"], f) for k, f in
                       (("glb", "web.glb"), ("sheet", "sheet.jpg"))}
    print(json.dumps(report, indent=1, default=str))


if __name__ == "__main__":
    main()
