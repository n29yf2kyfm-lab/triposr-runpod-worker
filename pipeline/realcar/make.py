#!/usr/bin/env python3
"""make.py — ask for a car in plain words, get back your own GLB file. Your
catalogue only: no Sketchfab, no outside service.

    python3 pipeline/realcar/glbmachine.py make "Mercedes A-Class 2012 black 5-door" -o a-class.glb
    python3 pipeline/realcar/make.py "..." --engine-pack E --tools T --view-dir V   # the same, all paths given

The request is read for a make and model, a year, a colour (DVLA colour
names), and a door count or body style. The approved catalogue is searched
for that model in a generation on sale in that year; if the catalogue has
the model but not that generation, the nearest generation it has is built
and the report says so (--exact refuses instead). Then the same steps as
batch.py run:

    download from the catalogue -> decode -> rig.py -> finish.py -> validator
    -> web copy (-> check sheet)

The finish uses the generic petrol engine bay and paints the car in the
colour asked for. The only network use is fetching the model file from the
catalogue's own storage; wheelbases come from the table that ships with the
machine (wheelbase.py) and credits from the catalogue record. A car is built
in 5-15 s; its four-view check sheet takes 25-50 s more (--no-sheet skips
it). The catalogue does not record door counts, so a door count is only
reported back, never used to choose.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import batch  # noqa: E402
import wheelbase  # noqa: E402

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


def edits(a, b):
    """Levenshtein distance, small strings."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def parse(text):
    t = text.lower()
    want = {"text": text}
    m = re.search(r"\b(19[5-9]\d|20[0-3]\d)\b", t)
    if m:
        want["year"] = int(m.group(1))
        t = t.replace(m.group(1), " ")
    else:
        # a UK registration plate: "12 Yaris", "62-plate Corsa": 02-29 is that
        # March's year, 51-79 that September's (fifty on)
        yy = time.localtime().tm_year % 100
        m = re.search(r"(?<![\w.])(\d\d)(?:[\s-]*(?:plate|reg))?(?![\w.])", t)
        if m and (2 <= int(m.group(1)) <= yy or 51 <= int(m.group(1)) <= yy + 50):
            n = int(m.group(1))
            want["year"] = 2000 + (n if n < 50 else n - 50)
            want["plate"] = m.group(1)
            t = t[:m.start()] + " " + t[m.end():]
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
    if not make:
        # a model named without its make ("12 Yaris"): the make whose
        # catalogue model names appear in the request, if only one does
        by_model = {}
        for i in cat.values():
            for n in {norm(x) for x in [i.get("model"), i.get("modelFamily")] if x}:
                n2 = n.replace(norm(i["make"]), "")
                if len(n2) >= 3 and n2 in q:
                    by_model.setdefault(i["make"].lower(), set()).add(n2)
        for uk, other in (("vauxhall", "opel"),):          # the UK badge of the same car
            if uk in by_model and other in by_model:
                del by_model[other]
        if len(by_model) == 1:
            make = next(iter(by_model))
            rest = q
            want["make_from_model"] = True
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
        # a one-letter slip ("micro" for Micra): the nearest name within one
        # edit of a word in the request, if there is exactly one such name
        words = [norm(x) for x in want["words"].replace("-", " ").split()]
        near = {}
        for i in pool:
            for n in names(i):
                n2 = n.replace(norm(make), "")
                if len(n2) >= 4 and any(edits(n2, w) == 1 for w in words):
                    near.setdefault(n2, []).append(i)
        if len(near) == 1:
            (n2, hits), = near.items()
            want["spelling"] = f"read as {n2}"
    if not hits:
        return None, [], "not in the catalogue"
    if want.get("body"):
        hb = [i for i in hits if (i.get("bodyStyle") or want["body"]) == want["body"]]
        hits = hb or hits
    yr = want.get("year")

    def years(i):
        # the generation's own production years from the wheelbase table (the
        # catalogue often records one model year: its 2011 Corsa is the
        # 2006-2014 Corsa D), else the record's, else seven years from its start
        y0 = i.get("yearStart") or 0
        if y0 and (i.get("yearEnd") or y0) == y0:     # only a record that gives one year is widened
            g = wheelbase.lookup(*batch.model_of(i), y0).get("years")
            if g and g[0] - 1 <= y0 <= g[1]:
                return min(g[0], y0), max(min(g[1], time.localtime().tm_year), i.get("yearEnd") or y0)
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


def build(request, engine_pack, tools, view_dir, out=None, port=8791, exact=False, no_sheet=False,
          out_file=None, full=False):
    """One request, start to finish, from the catalogue. Returns the report
    (with "result" and "files" when a car was built, "error" when the
    catalogue has no such model)."""
    args = argparse.Namespace(engine_pack=os.path.abspath(engine_pack), tools=tools, view_dir=view_dir,
                              port=port, no_sheet=no_sheet, keep_full=full)
    want = parse(request)
    cat = batch.catalogue()
    item, others, why = find(want, cat)
    report = {"asked": want, "match": why,
              "nearest": [f"{i['assetId']} ({i.get('yearStart')}-{i.get('yearEnd') or ''})" for i in others[:4]]}
    if item is None and others and not exact:
        item, report["match"] = others[0], f"{why}; built the nearest generation in the catalogue"
    if item is None:
        report["error"] = "not in the catalogue" if not others else "that generation is not in the catalogue"
        if want.get("make"):           # what the catalogue does have for that make
            report["catalogue_has"] = sorted({batch.model_of(i)[1].title() for i in cat.values()
                                              if i["make"].lower() == want["make"]
                                              and i.get("publicationStatus") == "approved"})[:40]
        return report
    report["asset"] = item["assetId"]
    report["source"] = item.get("sourceTitle")
    args.paint = COLOURS.get(want.get("colour"))
    # the doors asked for decide the body the rigger cuts: "2 door" / "3 door"
    # is a three-door hatch or a coupe (one door each side), "4/5 door" not
    if want.get("doors"):
        args.body_style = "3-door" if want["doors"] <= 3 else f"{want['doors']}-door"
    elif want.get("body"):
        args.body_style = want["body"]
    out = out or os.path.join(view_dir, "make")
    os.makedirs(out, exist_ok=True)
    server = None
    if not no_sheet:                      # the check sheet is drawn by a browser from this folder
        server = subprocess.Popen([sys.executable, "-m", "http.server", str(port)], cwd=view_dir,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
    try:
        t0 = time.time()
        rec = batch.one({"rank": 0, "genModel": request}, item, args, out)
        rec["seconds"] = round(time.time() - t0)
    finally:
        if server:
            server.terminate()
    report["result"] = rec
    side = [p for p in ((rec.get("finish") or {}).get("opens") or []) if p.startswith("door_") and p[5] in "fr"]
    report["side_doors_built"] = len(side)
    if want.get("doors"):
        # "2 door" / "3 door" in UK speech is a 3-door hatch: 2 side doors
        asked = 2 if want["doors"] <= 3 else 4
        report["doors_note"] = (f"asked for {want['doors']}-door: this model has {len(side)} side doors"
                                + ("" if len(side) == asked else " (the catalogue has no other body of this model)"))
    d = os.path.join(out, item["assetId"])
    report["files"] = {k: os.path.join(d, f) for k, f in
                       (("glb", "web.glb"), ("glb_full", "car_full.glb"), ("sheet", "sheet.jpg"))
                       if os.path.exists(os.path.join(d, f))}
    if out_file and report["files"].get("glb_full" if full else "glb"):
        os.makedirs(os.path.dirname(os.path.abspath(out_file)), exist_ok=True)
        shutil.copyfile(report["files"]["glb_full" if full else "glb"], out_file)
        report["files"]["yours"] = os.path.abspath(out_file)
    return report

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("request")
    ap.add_argument("--engine-pack", required=True)
    ap.add_argument("--tools", required=True)
    ap.add_argument("--view-dir", required=True)
    ap.add_argument("--out", default=None, help="work folder (default: VIEW_DIR/make)")
    ap.add_argument("-o", "--output", default=None, help="write the finished GLB here")
    ap.add_argument("--full", action="store_true", help="the uncompressed GLB (opens in any 3D program)")
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--exact", action="store_true", help="only that year's generation, never the nearest")
    ap.add_argument("--no-sheet", action="store_true", help="the car only, no four-view check sheet")
    a = ap.parse_args()
    report = build(a.request, a.engine_pack, a.tools, a.view_dir, a.out, a.port, a.exact, a.no_sheet, a.output, a.full)
    print(json.dumps(report, indent=1, default=str))
    if "error" in report:
        sys.exit(2)

if __name__ == "__main__":
    main()
