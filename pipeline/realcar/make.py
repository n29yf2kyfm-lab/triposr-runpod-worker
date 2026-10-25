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
COLOURS = {                       # longer names first: "dark grey" before "grey"
    "dark grey": (64, 66, 70), "dark gray": (64, 66, 70), "graphite": (64, 66, 70), "gunmetal": (64, 66, 70),
    "anthracite": (56, 58, 62),
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
# makers' own names for a body; an "Active Tourer" or "Gran Tourer" is not an
# estate (its body is left to the table: no body is asked), nor a 911 GT3
# Touring or a Grand Touring
ESTATE_WORDS = (r"(?<!gt3\s)(?<!grand\s)\btouring\b|\bsports?\s?tourer\b|\bavant\b|\bvariant\b|\bsports?\s?wagon\b"
                r"|\bwagon\b(?![\s-]?r\b)|\bshooting\s+brake\b|\bk?combi\b|\bsw\b")      # a Wagon R is a hatch
BODY_WORDS = [
    (re.compile(r"\b(?:active|gran)\s+tourer\b"), None),
    (re.compile(ESTATE_WORDS), "estate"),
]
BIKE = re.compile(r"\b(?:harley|motorbike|motorcycle|bike)\b")


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


# what people call a car, as its make and model; the trim it names is kept
# as the spec ("G63" is an AMG G-Class)
NICKNAMES = [
    (re.compile(r"\b(?:mercedes[- ]?(?:benz)?\s+|merc\s+|amg\s+)?(?:g[- ]?wag(?:on|en)|gelaende?wagen|geländewagen)\b"),
     "mercedes-benz g-class", None),
    (re.compile(r"\b(?:mercedes[- ]?(?:benz)?\s+|merc\s+)?(?:mercedes-amg\s+|amg\s+)?(g\s?(?:63|65|55|500|550|400\s?d|450\s?d|350\s?d|580))\b"),
     "mercedes-benz g-class", 1),
]


def parse(text):
    t = text.lower()
    want = {"text": text}
    placed = False                       # "G Wagon G63": the model once, the G63 as its trim
    for rx, canon, trim in NICKNAMES:
        m = rx.search(t)
        if m:
            if trim:
                want["nickname_trim"] = m.group(trim).upper().replace(" ", "")
            t = t[:m.start()] + " " + ("" if placed else canon) + " " + t[m.end():]
            placed = True
    # a model named like a year is the model: the Peugeot 2008 (and e-2008)
    m = next((m for m in re.finditer(r"\b(19[5-9]\d|20[0-3]\d)\b(?:[\s-]*(?:plate|reg)\b)?", t)
              if not re.search(r"(?:peugeot\s+(?:e-?)?|\be-)$", t[:m.start()])), None)
    if m:
        want["year"] = int(m.group(1))         # "2024 plate": the year, the word "plate" with it
        t = t[:m.start()] + " " + t[m.end():]
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
    # the steering wheel's side: "RHD", "right hand drive" (a UK car from a
    # left-hand-drive model: finish.right_hand_drive)
    m = re.search(r"\b(?:rhd|right[\s-]?hand[\s-]?drive)\b", t)
    if m:
        want["drive"] = "right"
        t = t[:m.start()] + " " + t[m.end():]
    # the wheels' colour ("black wheels", "gloss black alloys"): read first,
    # so its colour is not taken for the paint; the page starts the rims in it
    names = "|".join(re.escape(c) for c in COLOURS)
    m = re.search(rf"\b(?:(matte?|gloss|satin)\s+)?({names})\s+(?:wheels?|alloys?|rims?)\b", t)
    if m:
        want["wheels"] = {"colour": m.group(2), "srgb": list(COLOURS[m.group(2)]),
                          "finish": "matt" if (m.group(1) or "").startswith("matt") else m.group(1) or "gloss"}
        t = t[:m.start()] + " " + t[m.end():]
    # a paint finish ("matt grey", BMW's "Frozen"): the page starts the body
    # in it (the Finish Lab's), the colour as asked
    m = re.search(r"\b(matte?|frozen|satin)\b", t)
    if m:
        want["finish"] = "satin" if m.group(1) == "satin" else "matt"
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
    # what makers call their estates ("M5 Touring", "RS6 Avant", "308 SW") and
    # MPVs ("Active Tourer"): the body, but the word stays in the request, as
    # a model's name can carry it ("3 Series Touring", "Octavia Combi")
    if "body" not in want and not BIKE.search(t):
        for rx, b in BODY_WORDS:
            m = rx.search(t)
            if m:
                if b:
                    want["body"], want["body_word"] = b, m.group(0)
                break
    want["words"] = t.strip()
    return want


def in_words(name, text):
    """NAME (normalised) is the request's words, whole: one word or several
    side by side ("g class", "gclass"), or a word with digits after it
    ("golf7"); never letters inside a word: "cla" is not in "G-Class". A
    short name with digits after it is another model, not a generation:
    "iX4" is not the iX, "X5" not an X."""
    w = [norm(x) for x in re.split(r"[\s\-_/.,]+", text or "") if norm(x)]
    joins = {"".join(w[a:b]) for a in range(len(w)) for b in range(a + 1, len(w) + 1)}
    return name in joins or (len(name) >= 3 and any(j.startswith(name) and j[len(name):].isdigit() for j in joins))


def find(want, cat, skip=()):
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
    # the model words as typed, for a search outside the catalogue; a hyphen
    # in the model's name stays ("C-HR", "T-Roc": the sizes are filed so)
    toks = [t for t in want["words"].split() if norm(t)]          # a lone "-" ("Fiesta - red") is no word
    for k in range(len(toks), 0, -1):           # the longest: "mercedes benz", not "mercedes"
        if norm(" ".join(toks[:k])) in (norm(make), *[a for a, b in MAKES.items() if b == make]):
            want["model_words"] = " ".join(toks[k:])
            break
    if want["model_words"] is None:
        want["model_words"] = " ".join(toks[1:])
    # a file that is another car (batch.WRONG_CAR) is never built as the car it is filed under
    pool = [i for i in cat.values() if norm(i["make"]) == norm(make) and i.get("publicationStatus") == "approved"
            and i.get("desktopGlbUrl") and i["assetId"] not in skip and i["assetId"] not in batch.WRONG_CAR
            and not batch.is_game(i)]

    def names(i):
        return {norm(n) for n in [i.get("model"), i.get("modelFamily"), *(i.get("modelAliases") or [])] if n}
    best, hits = 0, []
    for i in pool:
        for n in names(i):
            n2 = n.replace(norm(make), "")
            if n2 and n2 in rest and in_words(n2, want["words"]) and len(n2) >= best:
                if len(n2) > best:
                    best, hits = len(n2), []
                hits.append(i)
                break
    if not hits:
        # a one-letter slip ("micro" for Micra): the nearest name within one
        # edit of a word in the request, if there is exactly one such name.
        # A word that is itself a model name of this make (a 208 whose only
        # files are refused or held back) is no slip, and nor is a model
        # number: 208 and 2008 are two cars
        words = [norm(x) for x in want["words"].replace("-", " ").split()]
        known = {n.replace(norm(make), "") for i in cat.values() if norm(i["make"]) == norm(make) for n in names(i)}
        words = [w for w in words if w not in known and not any(c.isdigit() for c in w)]
        near = {}
        for i in pool:
            for n in names(i):
                n2 = n.replace(norm(make), "")
                if len(n2) >= 4 and not any(c.isdigit() for c in n2) and any(edits(n2, w) == 1 for w in words):
                    near.setdefault(n2, []).append(i)
        if len(near) == 1:
            (n2, hits), = near.items()
            want["spelling"] = f"read as {n2}"
    if not hits:
        return None, [], "not in the catalogue"
    if want.get("body"):
        # the body asked: a record of that body first; one that says nothing of
        # its body may be it. A model the catalogue has only in another body
        # (an "M5 Touring" where it has the saloon alone) is marked, so a
        # stand-in of the body asked is made from another car, or the note
        # says the other body was built; never the other body unsaid
        fam = RECORD_BODY.get(want["body"], want["body"])
        bodies = {i["assetId"]: record_body(i) for i in hits}
        exact = [i for i in hits if bodies[i["assetId"]] == fam]
        unknown = [i for i in hits if bodies[i["assetId"]] is None]
        if exact or unknown:
            hits = exact or unknown
        else:
            want["body_missing"] = {"asked": fam, "has": sorted({bodies[i["assetId"]] for i in hits})}

    def doors_rank(i):
        # a record that gives its doors (an added model: `glbmachine add
        # --doors 3`) and agrees with the request wins; one that disagrees
        # comes last ("2 door" / "3 door" is one side door, "4/5 door" two)
        if not want.get("doors") or not i.get("doors"):
            return 1
        side = lambda n: 2 if n <= 3 else 4  # noqa: E731
        return 0 if side(int(i["doors"])) == side(want["doors"]) else 2
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
    asked = {n.replace(norm(make), "") for i in hits for n in names(i)}
    asked = {b for b in asked if b and b in rest and in_words(b, want["words"])}
    model_rx = "|".join(re.escape(w) for w in sorted({x for i in hits for x in [str(i.get("model") or "")] if x}, key=len,
                                                       reverse=True)) or "$^"

    def is_variant(i):
        # a long or special body the request did not name: an alias that is the
        # asked model plus words ("Tiguan Allspace"), or a title that says so
        # ("Tiguan L 430 PHEV"); the plain car comes first
        if any(n.replace(norm(make), "") != b and n.replace(norm(make), "").startswith(b) for n in names(i) for b in asked):
            return 1
        return 1 if re.search(rf"\b(?:{model_rx})\s+(?:l|lwb|long|allspace|xl|grand|max|limited)\b",
                              str(i.get("sourceTitle") or ""), re.I) else 0

    def generation(i):
        # when the record's generation started (the wheelbase table's), so two
        # records of one generation are told from a newer generation's
        y0 = i.get("yearStart") or 0
        g = wheelbase.lookup(*batch.model_of(i), y0).get("years") if y0 else None
        return g[0] if g and g[0] <= y0 + 1 else y0

    # of the records that fit as well: the doors asked for, the plain body, the
    # newer generation; within one generation, one ExpertCarCheck may use
    # commercially, then the newest and best graded
    rank = lambda i: (doors_rank(i), is_variant(i), -generation(i), not batch.credit_of(i)["commercial"],  # noqa: E731
                      -((i.get("yearStart") or 1990) - 4 * batch.GRADE.get(i.get("qualityGrade"), 3)))
    order = lambda L: sorted(L, key=rank)  # noqa: E731

    def pick(hits, first=lambda i: ()):
        if yr:
            on_sale = [i for i in hits if years(i)[0] - 1 <= yr <= years(i)[1]]
            others = sorted(hits, key=lambda i: (min(abs(yr - years(i)[0]), abs(yr - years(i)[1])), first(i), rank(i)))
        else:
            on_sale, others = hits, sorted(hits, key=lambda i: (first(i), rank(i)))
        return (min(on_sale, key=lambda i: (first(i), rank(i))) if on_sale else None), others

    variant, badge = spec_variants(want.get("spec"), hits, pool, names, norm(make), rest)
    if variant:
        item, others = pick(variant)
        if item:
            want["spec_used"] = f"{badge} is its own model in the catalogue: built that one"
            return item, others, "exact generation"
        want["spec_used"] = "none: the catalogue has that variant only from other years, so the standard car is built"
    fit, asked_trim = trim_fit(want, hits, names, norm(make))
    if fit:
        # of the records of the trim asked, the one on sale that year; the
        # whole trim named beats part of it, a record of one trim a list
        item, others = pick([i for i in hits if i["assetId"] in fit], lambda i: fit[i["assetId"]][:3])
        if item:
            want["trim_used"] = {"asked": asked_trim, "built": fit[item["assetId"]][3],
                                 "words_not_matched": fit[item["assetId"]][4]}
            return item, others, "exact generation"
        want["trim_used"] = {"asked": asked_trim, "built": None,
                             "why": "the catalogue has that trim only from other years: the standard car is built"}
    item, others = pick(hits)
    if item:
        return item, others, "exact generation"
    return None, others, "model found, not that year's generation"


# a trim, not a different car: "ST-Line" is a Fiesta with ST-look bumpers,
# "GT Line", "R-Line", "S line", "AMG Line" the same; read as one word so
# the badge before it (ST, GT, R, S) does not pick the sports model
_TRIM_WORD = re.compile(r"\b([a-z0-9]+)[\s-]+(line|look|design|style|pack|edition|plus)\b")


def spec_variants(spec, hits, pool, names, make_n, rest):
    """The catalogue records of the variant a spec names: "GTI" with a Golf
    asked for gives the Golf GTI records, "Type R" the Civic Type R. Only a
    name that is the asked model plus words of the spec counts. Empty if the
    spec names no variant the catalogue has. Also the badge as written
    for the report ("GTI", "Type R")."""
    if not spec or not hits:
        return [], None
    tok = [t for t in re.split(r"[^a-z0-9]+", _TRIM_WORD.sub(r"\1\2", spec.lower())) if t]
    grams = {"".join(tok[a:b]): " ".join(t.upper() if len(t) <= 3 else t.capitalize() for t in tok[a:b])
             for a in range(len(tok)) for b in range(a + 1, min(len(tok), a + 3) + 1)}
    base = {n.replace(make_n, "") for i in hits for n in names(i)}
    base = {b for b in base if b and b in rest}
    out, badge = [], None
    for i in pool:
        for n in names(i):
            n2 = n.replace(make_n, "")
            b = next((b for b in base if n2.startswith(b) and n2[len(b):] in grams), None)
            if b:
                out.append(i)
                badge = badge or grams[n2[len(b):]]
                break
    return out, badge


def _words(s):
    return [norm(x) for x in re.split(r"[\s\-_/.,]+", s or "") if norm(x)]


def trim_fit(want, hits, names, make_n):
    """The records whose trim the request names: the words after the model
    ("911 turbo s": Turbo S), and the spec. Only a record made as one or two
    trims counts (a 911 Turbo, a Civic Type R); a record listing the trims
    its body fits (SE, Sport, ST-Line ...) is the standard car. Returns
    {assetId: (part of the trim only, -words matched, trims listed, trim,
    request words not in it)} and the trim words asked."""
    toks = _words(want.get("model_words"))
    for n2 in sorted({n.replace(make_n, "") for i in hits for n in names(i)} - {""}, key=len, reverse=True):
        run = next(((a, b) for a in range(len(toks)) for b in range(a + 1, len(toks) + 1)
                    if "".join(toks[a:b]) == n2), None)
        if run:                                          # the model's own words are not its trim
            toks = toks[:run[0]] + toks[run[1]:]
            break
    toks += [t for t in _words(want.get("spec")) if t not in toks]
    if not toks:
        return {}, None
    fit = {}
    for i in hits:
        trims = [t for t in (i.get("compatibleTrimFamilies") or []) if _words(t)]
        if not 1 <= len(trims) <= 2:
            continue
        for tf in trims:
            T = _words(tf)
            k = max(next((n for n in range(len(T), 0, -1) if toks[a:a + n] == T[:n]), 0) for a in range(len(toks)))
            # the whole trim, or a word of it long enough to mean it ("turbo", not "s")
            if k == len(T) or (k and any(len(t) >= 3 for t in T[:k])):
                key = (k < len(T), -k, len(trims), tf, [t for t in toks if t not in T[:k]])
                if i["assetId"] not in fit or key[:3] < fit[i["assetId"]][:3]:
                    fit[i["assetId"]] = key
    return fit, " ".join(toks)


def _choose(want, cat, exact, skip):
    """The report so far and the catalogue record to build (None, with the
    report's "error", when there is none)."""
    want = {k: v for k, v in want.items() if k not in ("spec_used", "trim_used")}
    item, others, why = find(want, cat, skip)
    report = {"asked": want, "match": why,
              "nearest": [f"{i['assetId']} ({i.get('yearStart')}-{i.get('yearEnd') or ''})" for i in others[:4]]}
    bm = want.get("body_missing")
    if bm and item is not None:
        # the model, but not in the body asked: not an exact match, so a
        # stand-in of that body is tried (_standin); if none can be made, the
        # note says which body was built
        has = " or ".join(BODY_NAME.get(b, b or "body not recorded") for b in bm["has"])
        asked = BODY_NAME.get(bm["asked"], bm["asked"])
        report["match"] = f"the catalogue has this model only as a {has}, not as the {asked} asked for"
        report["body_note"] = f"The catalogue has this model only as a {has}, so the {has} is built, not the {asked} asked for"
    if item is None and others and not exact:
        item, report["match"] = others[0], f"{why}; built the nearest generation in the catalogue"
    if item is None:
        report["error"] = "not in the catalogue" if not others else "that generation is not in the catalogue"
        if want.get("make"):           # what the catalogue does have for that make
            report["catalogue_has"] = sorted({batch.model_of(i)[1].title() for i in cat.values()
                                              if i["make"].lower() == want["make"]
                                              and i.get("publicationStatus") == "approved"
                                              and i["assetId"] not in batch.WRONG_CAR})[:40]
        return report, None
    if want.get("trim_used"):
        report["trim"] = want.pop("trim_used")
    if want.get("spec"):
        report["spec_note"] = want.pop("spec_used", None) or (
            f"the {report['trim']['built']} body in the catalogue is built" if (report.get("trim") or {}).get("built")
            else "the spec names no separate model in the catalogue (a trim or engine): the standard body is built")
    report["asset"] = item["assetId"]
    report["source"] = item.get("sourceTitle")
    return report, item


RECORD_BODY = {"hatchback": "hatch", "hatch": "hatch", "saloon": "saloon", "sedan": "saloon", "estate": "estate",
               "wagon": "estate", "suv": "suv", "crossover": "suv", "mpv": "mpv", "coupe": "coupe",
               "convertible": "convertible", "cabriolet": "convertible", "roadster": "convertible",
               "pickup": "pickup", "van": "van"}
BODY_NAME = {"hatch": "hatchback", "suv": "SUV", "mpv": "MPV"}     # a body family in words; the rest as they are


VARIANT = re.compile(r"\b(?:GTI|GTD|GTE|GTS|R32|RS ?\d?|ST|AMG|Type R|GR|Nismo|JCW|Cupra|vRS|SVR|Allspace|LWB|"
                     r"Cabrio(?:let)?|Convertible|Coup[eé]|Works|Trophy|Rally|WRC)\b|\bgolf-r\b|\bgolf r\b|\b(?:tiguan|range rover|a6|a8|5 series) l\b",
                     re.I)


def _refused_path():
    return os.path.join(os.path.expanduser(os.environ.get("GLBMACHINE_HOME", "~/.glbmachine")), "rig_refused.json")


def refused():
    """Catalogue models this rigger version could not use (fused shells): not
    tried again, so a request does not wait on a known failure."""
    import rig
    try:
        return {a for a, v in json.load(open(_refused_path())).items()
                if v.get("rigger") == rig.VERSION and not v.get("missing")}
    except (OSError, ValueError):
        return set()


def incomplete():
    """Catalogue models that came out with parts missing (doors on one side,
    no tailgate): {asset: [parts]}, whichever rigger version made them (a new
    one seldom completes them, and a stand-in that waits on one is late).
    Still usable, but a stand-in tries the complete ones first. An entry goes
    when that model next comes out complete."""
    try:
        return {a: v["missing"] for a, v in json.load(open(_refused_path())).items() if v.get("missing")}
    except (OSError, ValueError):
        return {}


def _forget(asset):
    p = _refused_path()
    try:
        d = json.load(open(p))
    except (OSError, ValueError):
        return
    if d.pop(asset, None) is not None:
        json.dump(d, open(p + ".tmp", "w"), indent=1)
        os.replace(p + ".tmp", p)


def _remember_refused(asset, why, missing=None):
    import rig
    p = _refused_path()
    try:
        d = json.load(open(p))
    except (OSError, ValueError):
        d = {}
    d[asset] = {"why": why, "rigger": rig.VERSION, "at": time.strftime("%Y-%m-%d")}
    if missing:
        d[asset]["missing"] = sorted(missing)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(d, open(p + ".tmp", "w"), indent=1)
    os.replace(p + ".tmp", p)


def _generation(make, model, year, online=False):
    """The wheelbase table's generation of MAKE MODEL built in YEAR (the newest
    with no year), with its size and body family; None without a full size.
    With no year, a model no longer made (the Fiesta, to 2023) or whose new
    generation's size is not published yet (the 2023 Transit Custom) is its
    newest generation the table has a full size for."""
    try:
        b = wheelbase.lookup(make, model, year or 2100, online=online)
        size = ("wheelbase", "length", "width", "height")
        if not year and not all(b.get(k) for k in size):
            full = [x for x in (wheelbase.table().get(f"{make}|{model}".lower()) or {}).get("boxes", [])
                    if x.get("years") and all(x.get(k) for k in size)]
            if full:
                b = wheelbase.choose(full, None)
    except Exception:
        return None
    if not b.get("wheelbase"):
        return None
    fam = wheelbase.body_family(b.get("body"), b.get("class"), b.get("name"))
    if not fam:
        # the model's other generations' body (the Kuga's first two are SUVs),
        # else its proportions: tall for its length is an SUV
        ent = wheelbase.table().get(f"{make}|{model}".lower()) or {}
        y0 = (b.get("years") or [year or 2015])[0]
        near = sorted(((abs((x.get("years") or [9999])[0] - y0), wheelbase.body_family(x.get("body"), x.get("class"),
                                                                                       x.get("name")))
                       for x in ent.get("boxes", []) if x is not b), key=lambda t: t[0])
        fam = next((f for _, f in near if f), None)          # the nearest generation in time
        if not fam and b.get("height") and b.get("length"):
            fam = "suv" if b["height"] >= 1560 and b["height"] / b["length"] >= 0.355 else None
    return dict(b, family=fam)


# makers that share platforms and a family look: a stand-in from the same
# group looks more like the car than one from another group
GROUP = {m: g for g, ms in {
    "vw": ("volkswagen", "skoda", "seat", "cupra", "audi", "porsche", "bentley", "lamborghini"),
    "stellantis": ("peugeot", "citroen", "ds", "vauxhall", "opel", "fiat", "alfa-romeo", "jeep", "abarth", "lancia",
                   "chrysler", "dodge", "maserati"),
    "renault": ("renault", "dacia", "nissan", "infiniti", "mitsubishi"),
    "hyundai": ("hyundai", "kia", "genesis"),
    "bmw": ("bmw", "mini", "rolls-royce"),
    "toyota": ("toyota", "lexus", "suzuki"),
    "mercedes": ("mercedes-benz", "smart"),
    "jlr": ("jaguar", "land-rover"),
    "geely": ("volvo", "polestar", "lotus"),
    "ford": ("ford",), "honda": ("honda",), "mazda": ("mazda",), "subaru": ("subaru",), "tesla": ("tesla",),
    "mg": ("mg",), "byd": ("byd",)}.items() for m in ms}


TITLE_ESTATE = re.compile(r"\bestate\b|" + ESTATE_WORDS, re.I)     # a record's title: the request's estate words, and "Estate" itself


def record_body(i, gen=None):
    """A catalogue record's body family (hatch, saloon, estate, suv, ...): its
    own bodyStyle, else the wheelbase table's for its generation; a title
    that names another body wins over both (the model's other body, not the
    one its page leads with: "BMW 3 Series touring (E46)"). None when nothing
    says."""
    if gen is None:
        gen = _generation(*batch.model_of(i), i.get("yearStart")) or {}
    f = RECORD_BODY.get(str(i.get("bodyStyle") or "").lower()) or gen.get("family")
    title, md = str(i.get("sourceTitle") or ""), batch.model_of(i)[1]
    if re.search(r"\b(?:active|gran) tourer\b", title, re.I):
        f = "mpv"
    elif TITLE_ESTATE.search(title):
        f = "estate"
    elif re.search(r"cabrio|convertible|roadster|spider|spyder", title, re.I):
        f = "convertible"
    elif re.search(r"pick[- ]?up|double cab|crew cab|single cab|\bute\b", title, re.I) or \
            re.fullmatch(r"ranger|hilux|navara|l200|amarok|d-?max|tacoma|tundra|f-?150|f-?250|silverado|"
                         r"sierra|ram|gladiator|x-class|frontier|colorado|musso|bt-50|triton", md.lower()):
        f = "pickup"                             # an open load bed: not an SUV's shape (the Defender 130 pickup)
    return f


REACH = 0.35      # a donor's size term (length + 1.5 height + width off) the reshape still carries well: about 10% each


def donors(target, fam, cat, make, model_key, want, skip=()):
    """Catalogue cars to make a stand-in from, best first: the same body,
    then the nearest in size; the asked model's other generation first, the
    same make next, then the same maker group (its family face, often its
    platform); one that came out short of parts before goes later; the
    doors asked for, a model ExpertCarCheck may use commercially and the
    better grade breaking ties."""
    out, short = [], incomplete()
    for i in cat.values():
        if i.get("publicationStatus") != "approved" or not i.get("desktopGlbUrl") or i["assetId"] in skip \
                or i["assetId"] in batch.WRONG_CAR or batch.is_game(i):
            continue
        mk, md = batch.model_of(i)
        b = _generation(mk, md, i.get("yearStart")) or {}
        f = record_body(i, b)
        if fam and f != fam:
            continue
        def off(k, w):
            return abs(b[k] / target[k] - 1) * w if b.get(k) else 0.12 * w
        size = off("length", 1.0) + off("height", 1.5) + off("width", 1.0)
        three = bool(re.search(r"\b[23][- ]?(?:door|dr)\b|coup[eé]", str(i.get("sourceTitle") or ""), re.I)) \
            or (i.get("doors") and int(i["doors"]) <= 3)
        doors_off = 0.0
        if want.get("doors"):
            doors_off = 0.0 if three == (want["doors"] <= 3) else 0.4
        elif three:
            doors_off = 0.1                      # most cars on the road have rear doors
        # a sporting or special version ("Golf GTI" for a Golf) after the plain
        # car, unless the request or spec names it
        badge = VARIANT.search(" ".join(str(i.get(k) or "") for k in ("model", "modelFamily", "sourceTitle", "assetId")))
        variant = 0.15 if badge and badge.group(0).lower() not in (str(want.get("words") or "") + " "
                                                                     + str(want.get("spec") or "")).lower() else 0.0
        age = min(abs((i.get("yearStart") or target["years"][0] or 2015) - (target["years"][0] or 2015)) * 0.01, 0.15)
        a_, b_ = (x.lower().replace(" ", "-") for x in (mk, make))
        kin = 0 if a_ == b_ else 0.08 if GROUP.get(a_, a_) == GROUP.get(b_, b_) else 0.15
        tier = 0 if kin < 0.15 else 1                 # the make or its group (a Picanto for an i10), or another maker
        score = (size + age + variant + (0 if (mk.lower(), md.lower()) == model_key else 0.3) + kin
                 + doors_off + (0 if batch.credit_of(i)["commercial"] else 0.12)
                 + 0.25 * len(short.get(i["assetId"], ()))          # it came out short of these parts before
                 + 0.03 * batch.GRADE.get(i.get("qualityGrade"), 3))
        out.append((round(score, 4), i["assetId"], i, tier, size <= REACH and not short.get(i["assetId"])))
    # the reshape makes any donor the car's size, so its face counts most: when
    # the body is known (every donor has it), the make or its group first if
    # one is within reach of the size (a BMW estate stretched 10% reads as a
    # BMW, a Ford of the right size as a Ford); otherwise the nearest in
    # size, as scored
    best = min((r[3] for r in out if r[4]), default=1) if fam else 1
    return [r[2] for r in sorted(out, key=lambda r: (r[3] > best, r[0], r[1]))]


def _standin(want, report, item, cat, skip):
    """For a car the catalogue does not have (or not in the year asked), a
    stand-in: the nearest catalogue car of the same body, reshaped to the
    real car's size (standin.py). (report, item) for it, or None to build as
    before (no size known for the car)."""
    if item is not None and report["match"].startswith("exact generation"):
        return None
    if item is not None:
        make, model = (x.lower() for x in batch.model_of(item))
        gen = _generation(make, model, want.get("year"))
    elif want.get("make") and want.get("model_words"):
        make, model = want["make"], want["model_words"]
        gen = _generation(make, model, want.get("year"), online=True)     # the agent's one outside call
    else:
        return None
    if not gen or not all(gen.get(k) for k in ("length", "width", "height")):
        return None
    y = gen.get("years") or [None, None]
    if want.get("year") and y[0] and not (y[0] - 1 <= want["year"] <= y[1]):
        return None                              # the table has no generation for that year either
    title = wheelbase.MAKE_TITLE.get(make, make.title())
    name = re.sub(r"<[^>]+>|\s+", " ", str(gen.get("name") or "")).strip()
    name = name if name.lower().startswith(title.lower()) else f"{title} {wheelbase.wiki_title(model)} ({name})"
    # the body the stand-in must have: the one asked for, else the
    # generation's (an M5 Touring is made from an estate, not from the M5
    # saloon the catalogue has); its size is the generation's published one
    bm = want.get("body_missing")
    if not gen.get("family"):
        # a page that names no body (the C-HR's): the body the catalogue's own
        # files of the model give, held back or refused ones too, if they agree
        own = {RECORD_BODY.get(str(i.get("bodyStyle") or "").lower()) for i in cat.values()
               if [x.lower() for x in batch.model_of(i)] == [make.lower(), model.lower()]} - {None}
        if len(own) == 1:
            gen = dict(gen, family=own.pop(), family_from="the catalogue's files of the model")
    fam = RECORD_BODY.get(want.get("body") or "", None) or gen.get("family")
    other = bool(gen.get("family") and fam != gen["family"])         # not the body the table's size is for
    if other:
        name = f"{name} {str(want.get('body_word') or BODY_NAME.get(fam, fam)).title()}"
    # the side doors it must open: the request's, else the most its body has ("3/5-door hatchback": 4)
    nd = [int(x) for x in re.findall(r"([2-5])(?=[-/ ]?(?:\d-?)?door)", str(gen.get("body") or ""))]
    nd = want.get("doors") or (max(nd) if nd else None)
    target = {"name": name, "length": gen["length"], "wheelbase": gen["wheelbase"], "width": gen["width"],
              "height": gen["height"], "years": [y[0], None if (y[1] or 0) >= 2100 else y[1]],
              "body": fam, "source": gen.get("source"),
              "side_doors": (2 if nd <= 3 else 4) if nd else None}
    if other:
        target["no_photo"] = True     # the model's photos would be of its other body: the donor's own roof stays
    ranked = donors(target, fam, cat, make, (make, model), want, skip)
    if not ranked:
        return None
    d = ranked[0]
    dg = _generation(*batch.model_of(d), d.get("yearStart")) or {}
    if other and gen["family"] == "hatch" and fam in ("estate", "saloon") and dg.get("length") and dg.get("wheelbase"):
        # a hatch's estate or saloon is longer behind (a Golf estate is 30 cm
        # on the hatch): the donor's own overhangs on the car's wheelbase,
        # never shorter than the hatch
        target["length"] = max(target["length"], round(dg["length"] * target["wheelbase"] / dg["wheelbase"]))
        target["length_from"] = "the donor's proportions on the car's wheelbase"
    if (dg.get("name"), dg.get("page")) == (gen.get("name"), gen.get("page")):
        # the donor is that very generation (its record gave other years): no
        # stand-in, the car itself
        report = dict(report, match="exact generation (the wheelbase table's years for it)", asset=d["assetId"],
                      source=d.get("sourceTitle"))
        report.pop("error", None)
        report.pop("catalogue_has", None)
        report.pop("body_note", None)                # the body asked for, found under the table's years: no note
        return report, d
    sid = re.sub(r"[^a-z0-9]+", "-", f"{make} {model} {y[0] or ''} {fam if other else ''}".lower()).strip("-")
    it = dict(d, assetId=f"{d['assetId']}--as-{sid}", standin=target, standin_donor=d["assetId"],
              standin_of={"make": make, "model": model})          # the car asked for: its layout (batch.layout_of)
    report = dict(report)
    report.pop("error", None)
    report.pop("catalogue_has", None)
    report.pop("body_note", None)                # the body asked is built: no note that it is not
    yrs = f"{y[0]}-" + ("" if target["years"][1] is None else str(target["years"][1]))
    report["match"] = (f"stand-in: the catalogue has no {name} ({yrs}); "
                       f"'{d.get('sourceTitle') or d['assetId']}' reshaped to its size")
    report["standin"] = {"car": name, "make": title, "model": wheelbase.wiki_title(model), "years": target["years"], "size_mm": {k: target[k] for k in
                         ("length", "wheelbase", "width", "height")}, "body": target["body"],
                         "size_from": target["source"], "donor": d["assetId"], "donor_source": d.get("sourceTitle"),
                         "others": [x["assetId"] for x in ranked[1:4]]}
    report["asset"] = it["assetId"]
    report["source"] = d.get("sourceTitle")
    return report, it


class PhotoSearch:
    """The agent's search for a licensed true side photo of a stand-in's real
    car (photos.py), run beside the build. Each car's answer is kept in
    $GLBMACHINE_HOME/photos/<car>/found.json, so it is looked for once."""

    def __init__(self, make, model, target, deadline_s=45):
        import threading
        home = os.path.expanduser(os.environ.get("GLBMACHINE_HOME", "~/.glbmachine"))
        slug = re.sub(r"[^a-z0-9]+", "-", f"{make} {model} {target['years'][0] or ''}".lower()).strip("-")
        self.dir = os.path.join(home, "photos", slug)
        self.found_p = os.path.join(self.dir, "found.json")
        self.result, self.thread = None, None
        import photos
        lib = photos.from_library(make, model, target["years"][0])
        if lib:                                   # the standby library (photolib.py): no search at all
            self.result = {"file": lib["photo"]["file"], "author": lib["photo"].get("author"),
                           "licence": lib["photo"].get("licence"), "page": lib["photo"].get("page"), "seconds": 0,
                           "from_library": True,
                           "roofline": {k: lib[k] for k in ("u", "roof", "u_front", "u_rear", "height_photo")}}
            local = os.path.join(self.dir, "photo.jpg")
            if os.path.exists(local):
                self.result["photo"] = local
            return
        if os.path.exists(self.found_p):
            self.result = json.load(open(self.found_p))
            return

        def run():
            import photos
            try:
                r = photos.side_photo(make, wheelbase.wiki_title(model), target["years"], self.dir,
                                      {k: target[k] for k in ("length", "wheelbase", "height")}, deadline_s)
            except Exception as e:
                r = {"none": True, "error": str(e)[:200]}
            if r and r.get("cutout"):
                r["roofline"] = photos.roofline(r["cutout"], target["length"])
            self.result = r
            if r and (r.get("cutout") or not r.get("error")):
                os.makedirs(self.dir, exist_ok=True)
                json.dump(r, open(self.found_p, "w"), indent=1)
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def get(self, wait_s):
        if self.thread is not None:
            self.thread.join(max(0.0, wait_s))
        return self.result


def _licence_note(report, commercial_only, nc_best):
    """What the build may be used for, in its report: commercial only, and the
    non-commercial model left out for it, if one fitted better."""
    report["licence_mode"] = "commercial only" if commercial_only else "any licence (demo)"
    if nc_best:
        report["noncommercial_left_out"] = dict(nc_best, why="CC BY-NC: not for anything sold; "
                                                "build with commercial_only off for a demo")
    res = report.get("result") or {}
    if res.get("credit"):
        report["commercial_use"] = bool(res["credit"].get("commercial"))
    return report


def deadline_s():
    """The time a request has, from asking to its file: $GLBMACHINE_DEADLINE_S,
    50 s by default (the promise is under a minute; the check sheet, when
    asked for, comes after the file)."""
    try:
        return float(os.environ.get("GLBMACHINE_DEADLINE_S", 50))
    except ValueError:
        return 50.0


def commercial_only_default():
    """Builds use only models ExpertCarCheck may use commercially unless
    $GLBMACHINE_COMMERCIAL_ONLY is 0: a car that is sold must not be made
    from a non-commercial (CC BY-NC) model."""
    return os.environ.get("GLBMACHINE_COMMERCIAL_ONLY", "1").strip().lower() not in ("0", "false", "no", "off")


def build(request, engine_pack, tools, view_dir, out=None, port=8791, exact=False, no_sheet=False,
          out_file=None, full=False, spec=None, standin=True, photos=True, commercial_only=None, sheet_after=False):
    """One request, start to finish, from the catalogue. Returns the report
    (with "result" and "files" when a car was built, "error" when the
    catalogue has no such model). SPEC is the car's spec as a check gives it
    ("GTI", "ST-Line 1.0 EcoBoost 5dr hatchback"): a badge the catalogue has
    as its own model picks it, its doors and body count when the request
    gives none, and the rest (engine, fuel, trim) leaves the body as it is.
    SHEET_AFTER: no sheet now, but the finished file is kept for draw_sheet,
    which the caller runs once it has handed the file over (the server)."""
    t_start = time.time()                                # the request's clock: to its file, under the deadline
    # each try is built without its sheet and keeps its finished file; the
    # sheet is drawn once, for the car kept
    args = argparse.Namespace(engine_pack=os.path.abspath(engine_pack), tools=tools, view_dir=view_dir,
                              port=port, no_sheet=True, keep_finished=True, keep_full=full)
    want = parse(request)
    args.year = want.get("year")                         # the year asked: the generation's size when the model has none
    if not (spec and spec.strip()) and want.get("nickname_trim"):
        spec = want["nickname_trim"]                     # "G63": the AMG, as the spec
    if spec and spec.strip():
        want["spec"] = spec.strip()[:120]
        sp = parse(want["spec"])
        for k in ("doors", "body", "body_word", "colour"):
            if sp.get(k) and not want.get(k):
                want[k] = sp[k]
    cat = batch.catalogue()
    # COMMERCIAL ONLY (the default): the non-commercial models are left out,
    # so a car the catalogue has only under CC BY-NC is made as a stand-in
    # from a model that may be sold. The report names the model left out: a
    # demo may build it with commercial_only=False.
    if commercial_only is None:
        commercial_only = commercial_only_default()
    nc_best = None
    if commercial_only:
        whole = cat
        cat = {k: i for k, i in cat.items() if batch.credit_of(i)["commercial"]}
        try:
            r0, i0 = _choose(want, whole, exact, refused())
            if i0 is not None and not batch.credit_of(i0)["commercial"]:
                nc_best = {"asset": i0["assetId"], "source": i0.get("sourceTitle"), "match": r0.get("match"),
                           "licence": batch.credit_of(i0)["licence"]}
        except Exception:
            nc_best = None
    args.paint = COLOURS.get(want.get("colour"))
    args.drive = want.get("drive")                       # "right": a left-hand-drive model's cabin turned round
    # the doors asked for decide the body the rigger cuts: "2 door" / "3 door"
    # is a three-door hatch or a coupe (one door each side), "4/5 door" not
    if want.get("doors"):
        args.body_style = "3-door" if want["doors"] <= 3 else f"{want['doors']}-door"
    elif want.get("body"):
        args.body_style = want["body"]
    out = out or os.path.join(view_dir, "make")
    os.makedirs(out, exist_ok=True)
    # a model the rigger cannot use (its wheels and doors fused into a few
    # shells) is passed over for the next best, up to three, and the report
    # says why
    passed, known, best, tried, search = [], refused(), None, [], None
    deadline, last_s = deadline_s(), 0.0
    for attempt in range(3):
        if attempt and time.time() - t_start + last_s > deadline:
            # another try would not finish in time (it takes about as long as
            # the last): keep the best so far
            report["time_limit"] = f"stopped trying other models at {time.time() - t_start:.0f} s"
            break
        skip = {p["asset"] for p in passed} | known
        report, item = _choose(want, cat, exact, skip)
        if standin and not exact:
            st = _standin(report["asked"], report, item, cat, skip)
            if st:
                report, item = st
                if photos and item.get("standin") and not item["standin"].get("no_photo") and search is None:
                    s_ = report["standin"]
                    search = PhotoSearch(s_["make"], s_["model"], item["standin"])
        if item is None:
            break
        photo = search.result if search is not None and (search.thread is None or not search.thread.is_alive()) else None
        if item.get("standin") and (photo or {}).get("roofline"):
            # the photo is known already (the standby library, or a search for
            # this car before): its roofline goes into this build, not into a
            # second build after it that the time may not allow
            item = dict(item, standin=dict(item["standin"], roof=dict(photo["roofline"], file=photo["file"])))
        t0 = time.time()
        rec = batch.one({"rank": 0, "genModel": request}, item, args, out)
        last_s = time.time() - t0
        rec["seconds"] = round(last_s)
        tried.append(item["assetId"])
        report["result"] = rec
        built = os.path.exists(os.path.join(out, item["assetId"], "web.glb")) and rec.get("status") in ("done", "check")
        if built and item.get("standin"):
            # the real car's doors: a 5-door stand-in with front doors only is short of two
            side = [p for p in ((rec.get("finish") or {}).get("opens") or []) if re.fullmatch(r"door_[fr][lr]", p)]
            need = item["standin"].get("side_doors")
            if need and len(side) < need:
                rec["missing"] = sorted(set(rec.get("missing") or []) | ({"door_rl", "door_rr"} - set(side)))
        if built and item.get("standin") and rec.get("missing"):
            # a stand-in's donor is a choice: one that comes out with parts
            # missing (doors on one side only) gives way to the next, and the
            # most complete of the tries is kept
            if best is None or len(rec["missing"]) < len(best[2]["missing"]):
                best = (report, item, rec)
            passed.append({"asset": item["standin_donor"], "source": item.get("sourceTitle"),
                           "why": "missing " + ", ".join(rec["missing"])})
            _remember_refused(item["standin_donor"], passed[-1]["why"], rec["missing"])   # next time, later in line
            continue
        if built:
            if item.get("standin"):
                _forget(item["standin_donor"])     # complete now: no longer short of parts
            break
        rig = rec.get("rig") or {}
        passed.append({"asset": item.get("standin_donor") or item["assetId"], "source": item.get("sourceTitle"),
                       "why": rig.get("refused") or rig.get("error") or rec.get("status")})
        if rig.get("status") == "refused":
            _remember_refused(passed[-1]["asset"], passed[-1]["why"])
    if best is not None and (item is None or "error" in report or not report.get("result")
                             or len((report["result"].get("missing") or [])) > len(best[2]["missing"])
                             or not os.path.exists(os.path.join(out, item["assetId"], "web.glb"))):
        report, item, rec = best
        passed = [p for p in passed if p["asset"] != item.get("standin_donor")]
    for a in set(tried) - {item and item["assetId"]}:     # finished files kept for a sheet only
        f = os.path.join(out, a, "finished.glb")
        if os.path.exists(f):
            os.remove(f)
    if passed:
        report["passed_over"] = passed
    if item is None or "error" in report:
        if passed:
            report["error"] = "no model of this car in the catalogue could be rigged"
        return _licence_note(report, commercial_only, nc_best)
    if not os.path.exists(os.path.join(out, item["assetId"], "web.glb")):
        report["error"] = "no model of this car in the catalogue could be rigged"
        return _licence_note(report, commercial_only, nc_best)
    if passed:
        report["match"] += f"; {len(passed)} other model(s) tried first and passed over (see passed_over)"
    if item.get("standin") and search is not None:
        def photo_used(ph, rec):
            rl = (rec.get("standin") or {}).get("roofline") or {}
            report["standin"]["photo"] = {"file": ph["file"], "author": ph.get("author"), "licence": ph.get("licence"),
                                          "page": ph.get("page"), "dated": ph.get("dated", True),
                                          "view": ph.get("view") or "side",
                                          "roofline_off_cm": [rl.get("roofline_off_cm_before"),
                                                              rl.get("roofline_off_cm_after")],
                                          "used_for": "the roofline only: nothing of the photo is in the car",
                                          "from_library": bool(ph.get("from_library"))}
            if ph.get("photo") and os.path.exists(ph["photo"]):
                shutil.copyfile(ph["photo"], os.path.join(out, item["assetId"], "photo.jpg"))
        # a photo known before the build went into it; else it is waited for
        # only while a rebuild with it still fits in the time, and a search
        # still running goes on and is kept for next time
        ph = search.result if item["standin"].get("roof") else \
            search.get(deadline - (time.time() - t_start) - last_s)
        report["standin"]["photo_search"] = ({"found": ph.get("file"), "seconds": ph.get("seconds"),
                                             "rejected": len(ph.get("rejected") or [])} if ph else
                                            {"found": None, "why": "still searching at the time limit: "
                                                                   "a photo found later is used next time"})
        if item["standin"].get("roof"):
            photo_used(ph, rec)
        elif ph and ph.get("roofline") and time.time() - t_start + last_s > deadline:
            report["standin"]["photo_search"]["why"] = "found too late to rebuild in time: used next time"
        elif ph and ph.get("roofline"):
            st2 = dict(item["standin"], roof=dict(ph["roofline"], file=ph["file"]))
            item2 = dict(item, standin=st2)
            rec2 = batch.one({"rank": 0, "genModel": request}, item2, args, out)
            if os.path.exists(os.path.join(out, item["assetId"], "web.glb")) and rec2.get("status") in ("done", "check") \
                    and len(rec2.get("missing") or []) <= len(rec.get("missing") or []):
                item, rec = item2, rec2
                report["result"] = rec
                photo_used(ph, rec)
    side = [p for p in ((rec.get("finish") or {}).get("opens") or []) if p.startswith("door_") and p[5] in "fr"]
    report["side_doors_built"] = len(side)
    if want.get("doors"):
        # "2 door" / "3 door" in UK speech is a 3-door hatch: 2 side doors
        asked = 2 if want["doors"] <= 3 else 4
        report["doors_note"] = f"asked for {want['doors']}-door: {len(side)} side doors open" + (
            "" if len(side) == asked else
            " (only the front doors: the model's rear doors are not separate parts, or it is a 3-door; "
            "mark them in Studio)" if len(side) < asked else
            " (the catalogue's model of this car is a 5-door)")
    d = os.path.join(out, item["assetId"])
    # the file first: the time a request is promised is to its file; the
    # check sheet, when asked for, comes after it
    report["files"] = _files(d)
    if out_file and report["files"].get("glb_full" if full else "glb"):
        os.makedirs(os.path.dirname(os.path.abspath(out_file)), exist_ok=True)
        shutil.copyfile(report["files"]["glb_full" if full else "glb"], out_file)
        report["files"]["yours"] = os.path.abspath(out_file)
    report["seconds_to_file"] = round(time.time() - t_start, 1)
    if sheet_after:
        report["sheet_from"] = d
    elif not no_sheet:
        draw_sheet(d, args, rec)
        report["files"].update(_files(d))
    elif os.path.exists(os.path.join(d, "finished.glb")):
        os.remove(os.path.join(d, "finished.glb"))
    return _licence_note(report, commercial_only, nc_best)


def _files(d):
    return {k: os.path.join(d, f) for k, f in
            (("glb", "web.glb"), ("glb_full", "car_full.glb"), ("sheet", "sheet.jpg"), ("photo", "photo.jpg"))
            if os.path.exists(os.path.join(d, f))}


def draw_sheet(d, args, rec):
    """The four-view check sheet of the car built in D (from its kept
    finished.glb, which goes afterwards), drawn by a browser from the view
    folder. Its time goes in REC's timings, or its error."""
    if os.path.exists(os.path.join(d, "finished.glb")):
        server = subprocess.Popen([sys.executable, "-m", "http.server", str(args.port)], cwd=args.view_dir,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.6)
        try:
            sh = batch.render_sheet(d, args)
        except Exception as e:                # the browser timed out: the finished file still goes
            sh = {"error": str(e)[-300:]}
        finally:
            server.terminate()
            os.remove(os.path.join(d, "finished.glb"))
    else:
        sh = {"error": "no finished car to draw"}
    if "seconds" in sh:
        rec.setdefault("timings_s", {})["render"] = sh["seconds"]
        rec.pop("sheet_error", None)
    else:
        rec["sheet_error"] = sh["error"]

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
    ap.add_argument("--spec", default=None, help='the spec, e.g. "GTI" or "ST-Line 1.0 5dr"')
    ap.add_argument("--no-standin", action="store_true", help="never reshape another car: the nearest as it is")
    ap.add_argument("--allow-noncommercial", action="store_true",
                    help="a demo: non-commercial (CC BY-NC) models may be used; never for anything sold")
    a = ap.parse_args()
    report = build(a.request, a.engine_pack, a.tools, a.view_dir, a.out, a.port, a.exact, a.no_sheet, a.output, a.full,
                   a.spec, not a.no_standin, commercial_only=False if a.allow_noncommercial else None)
    print(json.dumps(report, indent=1, default=str))
    if "error" in report:
        sys.exit(2)
    if not report.get("files", {}).get("glb"):
        sys.exit(3)

if __name__ == "__main__":
    main()
