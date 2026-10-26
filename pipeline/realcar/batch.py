#!/usr/bin/env python3
"""batch.py — finish the UK's best-selling cars from the approved catalogue,
in sales order, unattended and resumable.

    BLENDER_BIN=... python3 pipeline/realcar/batch.py OUT_DIR --top 20 \
        --engine-pack engine_pack.glb --tools TOOLS_DIR [--class car]

For each target in platform/catalogue/uk_targets/targets.csv (ranked by
licensed vehicles), the best approved catalogue model is chosen (quality
newest generation, a quality grade counting as four years), and then:

  download -> decode -> rig.py (doors, wheels, frame) -> finish.py (bonnet,
  tailgate, trims, glass, engine, clips) -> glTF validator -> meshopt web
  copy -> four-view check sheet

One line per car goes to OUT_DIR/state.jsonl. A re-run skips cars already
there; remove a car's line to redo it (its rigged copy is kept, so that only
re-finishes). The rigged copy, web copy, sheet and log stay on disk. Nothing is
published: a person looks at each sheet first.

TOOLS_DIR is a folder with node_modules for @gltf-transform, meshoptimizer,
gltf-validator and puppeteer-core, plus validate.mjs, encode.mjs and view.mjs
(see pipeline/template/tools). The check sheet is rendered by a three.js page
(VIEW_DIR) served on localhost.
"""
import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
CABIN_PACK = os.path.join(HERE, "assets", "cabin_pack.glb")   # cabin_pack.py: fitted when a model has no cabin
sys.path.insert(0, HERE)
import finish  # noqa: E402
from rig import TWO_DOOR  # noqa: E402
import rig as rig_mod  # noqa: E402
import wheelbase  # noqa: E402

GRADE = {"A": 0, "B": 1, "C": 2}

# Wheelbases (mm) checked by hand for the catalogue models at the top of the
# list. A model at true scale needs none. One the rig machine had to rescale
# from an assumed wheel height is set to this figure, and is flagged
# "scale unverified" if it has none.
WHEELBASE = {
    "volkswagen-polo-2023-v1": 2564,
    "nissan-qashqai-2018-v1": 2646,
    "ford-fiesta-2009-w12-v1": 2489,          # Fiesta Mk6 (2008-2017), en.wikipedia infobox
    "volkswagen-golf-2025-w12-v1": 2636,      # Golf Mk8 / 8.5, en.wikipedia infobox
    "mercedes-benz-a-class-2018-w12-v1": 2699,  # A45 AMG W176 (2012-2018), en.wikipedia infobox
    "toyota-yaris-2001-v1": 2370,             # Yaris / Vitz XP10 (1999-2005): its page is titled Vitz
}


# Catalogue bodies corrected by looking at the model: a file whose record
# names no body takes its generation's first ("3/5-door hatchback" for the
# Astra G), which is not always the body modelled
BODY_FIX = {"opel-astra-1998-w7-v1": "saloon"}     # an Astra G saloon, boot and all


# Catalogue models whose own cues put the nose at the wrong end (seen on the
# check sheets: built tail first, its "tailgate" the bonnet): the rigger is
# told the nose is the other end
NOSE_BACK = {"mercedes-benz-gl-class-2012-mw1-v1": "the height over the axles reads it backwards"}


# Catalogue years corrected by looking at the model against the generation's
# published production dates (the catalogue keeps the source's title year).
GENERATION_FIX = {
    "mercedes-benz-a-class-2018-w12-v1": {"yearStart": 2012, "yearEnd": 2018, "generation": "W176"},
    # a first-generation Yaris (XP10: its sheet, and the 2001 in its id),
    # recorded as the 2020 car
    "toyota-yaris-2001-v1": {"yearStart": 1999, "yearEnd": 2005, "generation": "XP10"},
    # recorded with no year: a 992 Turbo (its sheet: full-width rear light
    # bar, flush door handles, 992 bumpers and side intakes)
    "porsche-911-pw2-v7": {"yearStart": 2020, "generation": "992"},
    # an Audi A4 (B5) recorded as from 2015 (its title names the B5)
    "audi-a4-v1": {"yearStart": 1994, "yearEnd": 2001, "generation": "B5"},
    # a W123 E-Class (its grille, bumpers and glasshouse), recorded with no year
    "mercedes-benz-e-class-mw1-v5": {"yearStart": 1976, "yearEnd": 1986, "generation": "W123"},
    # the 1968 Beetle its title names, recorded as the 1997-2019 New Beetle and Beetle
    "volkswagen-beetle-v1": {"yearStart": 1968, "yearEnd": 1968, "generation": "Type 1"},
    # the C8 its title names ("2019 Chevrolet Corvette C8 Stingray"), recorded from 1997
    "chevrolet-corvette-v1": {"yearStart": 2020, "yearEnd": 2026, "generation": "C8"},
    # the 1992 Escort RS Cosworth its title names, recorded as every Escort of 1968-2000
    "ford-escort-v1": {"yearStart": 1992, "yearEnd": 1996, "generation": "Mk5 (RS Cosworth)"},
    # a first-generation Fabia (its grille, lamps and bumpers), recorded with no year
    "skoda-fabia-w7-v1": {"yearStart": 1999, "yearEnd": 2007, "generation": "Mk1 (6Y)"},
}


# Catalogue models of a special version their records do not name (a Focus RS
# filed as a Focus): built as their car, but a stand-in's donor after a plain
# car, as a named badge's is (make.VARIANT), unless the request names it
SPECIAL_VERSION = {"ford-focus-v1": r"\brs\b", "jaguar-xe-v1": r"project ?8|\bsv\b",
                   "jaguar-xe-2018-jgw1-v1": r"project ?8|\bsv\b"}

# Catalogue models whose paint is a livery, not the road car's (an art car's
# print): built in a plain paint of the model when no colour is asked, as the
# car itself and as a stand-in's donor (sRGB)
PLAIN_PAINT = {
    "mercedes-benz-glc-mw1-v2": (172, 175, 178),      # an art-car print; built in a plain silver
    "kia-stinger-v1": (96, 100, 106),                 # a camouflage wrap; built in a plain grey
}


# Engines behind the rear axle under an engine lid (finish.py "layout":
# "rear"): every 911, under whatever name the catalogue gives it. (A Smart's
# or a Twingo's engine is under the boot floor, its tailgate a hatch: not
# these.)
REAR_ENGINE = re.compile(r"^porsche\|(911|930|959|964|993|996|997|991|992)\b")
# and behind the seats (mid-engined): built the same way, the engine under
# the rear lid and luggage under the front one. The Corvette from its 2020
# C8 (every one before it has its engine in front)
MID_ENGINE = re.compile(r"^(?:porsche\|(?:boxster|cayman|718|914|918|carrera gt)|audi\|r8|ferrari\||lamborghini\||mclaren\||"
                        r"lotus\|(?:elise|exige|evora|emira|europa)|alpine\|a110|honda\|nsx|toyota\|mr2|fiat\|x1-?9|ford\|gt\b|"
                        r"bugatti\||pagani\||koenigsegg\|)")


def layout_of(item):
    """'rear' for a rear-engined car, else None. A stand-in takes the layout
    of the car it stands in for, not its donor's: a 911 of a generation the
    catalogue lacks is rear-engined whatever it is reshaped from."""
    if item.get("standin"):
        of = item.get("standin_of") or {}
        make, model = str(of.get("make") or ""), str(of.get("model") or "")
    else:
        make, model = model_of(item)
    key = f"{make.lower()}|{model.lower()}"
    year = (item.get("standin") or {}).get("years", [None])[0] if item.get("standin") else item.get("yearStart")
    c8 = key.startswith("chevrolet|corvette") and (year or 0) >= 2020
    return "rear" if REAR_ENGINE.search(key) or MID_ENGINE.search(key) or c8 else None


# Catalogue models held back (seen on the check sheets): files that are not
# the car their record says, and files too broken to build from. Never
# picked for their car, nor as a stand-in's donor.
WRONG_CAR = {
    "honda-jazz-2018-v1": "is a Toyota RAV4 (badge and 'JPRAV4' plate)",
    "mini-cooper-w7-v1": "is the classic Mini, not the BMW MINI on UK roads",
    "ford-ranger-2023-v1": "is a Suzuki Vitara ('VITARA' on its tailgate), not a Ford Ranger",
    # seen on the 1,000-vehicle check sheets
    "audi-a1-quattro-v1": "is a Citroen C4 saloon (the same pack's file), not an Audi A1",
    "skoda-octavia-estate-v1": "is a Peugeot 307 hatchback (its lion on the grille), not a Skoda Octavia estate",
    "bmw-8-series-v1": "is a BMW X7 (an SUV with the X7's grille), not the 8 Series coupe it is titled",
    "hyundai-i30-2010-v1": "is a Volkswagen Arteon Shooting Brake (VW grille and badge), not a 2010 Hyundai i30",
    "ford-s-max-v1": "is a Ford Fiesta ST hatchback ('FIESTA ST' plate, ST badges), not an S-MAX people carrier",
    "fiat-500-2016-v1": "is an Audi hatchback (Audi grille and rings, 'Audi A6' plate), not a Fiat 500",
    "mercedes-benz-cls-2022-v1": "is a Skoda Octavia vRS estate (Skoda grille and badge), not a CLS 53",
    "mercedes-benz-s-class-v1": "is a first-generation A-Class (W168), not the S65 (W222) it is titled",
    "alfa-romeo-milano-2023-v1": "is a Cupra Formentor (Cupra badge and copper wheels), not an Alfa Romeo Milano/Junior",
    "audi-a8-2008-v1": "is an Audi Q5 Sportback (its grille and roofline), not a 2008 A8; and broken as the next three are",
    # files the catalogue cut down to about 150,000 triangles, their inner
    # panels merged through the paint: the cabin and the bay show through in
    # shards on the bonnet, pillars and roof. Nothing in them to mend
    "citroen-c5-2022-v1": "a broken file: its inner panels show through the paint in shards",
    "lexus-rx-v1": "a broken file: its inner panels show through the paint in shards",
    "honda-zr-v-2023-v1": "a broken file: its inner panels show through the paint in shards",
    "suzuki-swift-2017-v1": "a broken file: its inner panels show through the paint in shards",
    "bmw-320i-2023-v1": "a broken file: its inner panels show through the paint in shards",
    "bmw-ix-v1": "a broken file: its inner panels show through the paint in shards",
    "volkswagen-caddy-2022-v1": "a broken file: its inner panels show through the paint in shards",
    "citroen-c4-2008-v1": "a broken file: its paint is see-through, the inner panels in shards",
    "mazda-3-2020-v1": "a broken file: its inner panels show through the paint in shards",
    "mercedes-benz-gls-2022-v1": "a broken file: its inner panels show through the paint in shards",
    "peugeot-307-2008-v1": "a broken file: its inner panels show through the paint in shards",
}


# Catalogue models whose painted panels do not meet (seen on the check
# sheets): the finisher closes them up (finish.close_cracks). Only these: on
# a sound model the same rule would close every shut line.
TORN = {
    "volkswagen-caddy-2022-v1": "bonnet, A-pillars and roof rails torn: the dark cabin shows through",
}


# a model ripped from a video game, a toy or a low-poly game asset: never built
# (the owner's rule). "Gran Turismo" alone is a real body (BMW, Maserati)
GAME = re.compile(r"gran turismo (?:\d|sport)\b|grand turismo|\bforza\b|\bgta ?[ivx\d]|grand theft|need for speed|"
                  r"\bnfs\b|assetto|project cars|burnout|midnight club|\bgame\b|low[- ]?poly|\btoy\b|lego|hot ?wheels|"
                  r"die-?cast|matchbox|cartoon|chibi|\brc car\b", re.I)


# an electric car has no engine: the engine pack (a petrol four, its radiator,
# gearbox, fuel tank and exhaust) is not fitted (the Tesla had all of them).
# Only models sold as electric only; a plug-in or hybrid keeps its engine, and
# a name used for both (Volvo's "Recharge", BYD's DM models) is left alone
ELECTRIC = re.compile(
    r"\btesla\b|\bmodel [3sxy]\b|\bi[3457]\b|\bix\d?\b|\bid\.?\s?[34567]\b|\bid\.?\s?buzz\b|\be-?golf\b|\be-?up\b|"
    r"\be-?tron\b|\beq[abcesv]\b|\bleaf\b|\bariya\b|\bzoe\b|\be-?tech electric\b|\bev[3569]\b|\be-?niro\b|\bniro ev\b|"
    r"\bioniq ?[56]\b|\bkona electric\b|\be-(?:208|2008|308|3008|5008|rifter|partner|expert|traveller)\b|\bcorsa-?e\b|"
    r"\bmokka-?e\b|\b500e\b|\be500\b|\btaycan\b|\bmg ?4\b|\bzs ev\b|\benyaq\b|\belroq\b|\bborn\b|\bi-?pace\b|"
    r"\bex(?:30|40|90)\b|\bc40\b|\bmach-?e\b|\bhonda e\b|\beletre\b|\bsmart #\d|\beq fortwo\b|\brivian\b|\blucid\b|"
    r"\belectric\b|\b(?:ev|bev)\b", re.I)
BYD_ELECTRIC = {"atto 2", "atto 3", "dolphin", "dolphin mini", "seagull", "seal", "sealion 7", "yuan plus", "m6",
                "yangwang u7", "yangwang u9"}
NOT_ELECTRIC = re.compile(r"hybrid|phev|plug-?in|\bi8\b|\bdm-?i\b|\bdm\b|\ba3\b.*e-?tron|\bt8\b|range extender", re.I)


def is_electric(item, *more):
    """Whether a catalogue record (or a stand-in's target name) is an
    electric-only car."""
    text = " ".join([str(item.get(k) or "") for k in ("make", "model", "modelFamily", "sourceTitle", "assetId")]
                    + [str(m or "") for m in more])
    text = re.sub(r"[-_](?=\w)", " ", text)
    make = str(item.get("make") or "").lower()
    if make == "polestar":
        return True
    if make == "byd":            # BYD sells its names as electric and as DM plug-ins: the electric-only ones by name
        model = re.sub(r"[-_\s]+", " ", str(item.get("model") or "").lower()).strip()
        return model in BYD_ELECTRIC
    return bool(ELECTRIC.search(text)) and not NOT_ELECTRIC.search(text)


def is_game(item):
    return bool(GAME.search(" ".join(str(item.get(k) or "") for k in ("sourceTitle", "model", "assetId", "sourceUrl"))))


def local_catalogue_path():
    """The owner's own models, added with `glbmachine add`."""
    home = os.path.expanduser(os.environ.get("GLBMACHINE_HOME", "~/.glbmachine"))
    return os.path.join(home, "catalogue_local.json")


def catalogue():
    d = json.load(open(os.path.join(REPO, "platform/catalogue/catalogue.v2.json")))
    items = d if isinstance(d, list) else d.get("models") or d.get("items") or list(d.values())[0]
    cat = {i["assetId"]: i for i in items}
    if os.path.exists(local_catalogue_path()):
        cat.update(json.load(open(local_catalogue_path())))
    for aid, fix in GENERATION_FIX.items():
        if aid in cat:
            cat[aid] = {**cat[aid], **fix}
    for aid, body in BODY_FIX.items():
        if aid in cat:
            cat[aid] = {**cat[aid], "bodyStyle": body}
    return cat


def pick(target, cat):
    ids = [a for a in (target["assetIds"] or "").split("|") if a in cat]
    ok = [cat[a] for a in ids if cat[a].get("publicationStatus") == "approved" and cat[a].get("desktopGlbUrl")
          and a not in WRONG_CAR]
    if not ok:
        return None
    # the generation on the road now matters most; a grade is worth 4 years
    ok.sort(key=lambda i: -((i.get("yearStart") or 1990) - 4 * GRADE.get(i.get("qualityGrade"), 3)))
    return ok[0]


# trim words, never part of a hyphenated name (E-Class, GT-R, CR-V keep theirs)
TRIM = re.compile(r"(?<![\w-])(gti|gtd|gte|gt|r|rs\d?|st|amg|s|se|sport|line|hybrid|phev|ev|e|turbo|quattro|xdrive|\d{3}i|a\d\d)(?![\w-])", re.I)


def model_of(item):
    """(make, model) as the wheelbase table knows it: trim words and the make
    taken off ('volkswagen', 'polo' from 'Volkswagen Polo GTI')."""
    model = TRIM.sub(" ", item.get("modelFamily") or item.get("model") or "")
    make_rx = r"[-\s]".join(re.escape(w) for w in re.split(r"[-\s]+", item["make"]))   # land-rover = land rover
    model = re.sub(make_rx + r"\s*", "", model, flags=re.I).strip(" -") or item.get("model")
    return item["make"], " ".join(model.split())


def auto_wheelbase(item, rep, rec, year=None):
    """The wheelbase for a model not on the hand-checked list, looked up
    when the finisher knows the model's proportions (wheelbase.py). A model
    the rig machine had to rescale from a guessed wheel size must get one;
    the answer is used only if it leaves the wheels a real car's size
    (0.50 to 0.85 m), and on a model already at metre scale only if it
    changes the size by under 25%. Otherwise the car is flagged."""
    make, model = model_of(item)
    year = item.get("yearStart") or year or 2015
    rescaled = rep.get("rescaled")
    # rear doors: not the two- or three-door body (the G-Class's 2.40 m SWB)
    doors = 5 if any(k in (rep.get("parts") or {}) for k in ("door_rl", "door_rr")) else None

    def get(ratio, base):
        try:
            ans = wheelbase.lookup(make, model, year, ratio, doors=doors)
        except Exception as e:
            ans = {"wheelbase": None, "why": str(e)}
        wb = ans.get("wheelbase")
        info = {k: ans.get(k) for k in ("wheelbase", "years", "source", "name", "why")}
        if wb and ratio:
            k = wb / 1000.0 / base
            wheel = 0.68 * k if rescaled else None
            # the body's length at that scale against the published length: when
            # they agree (within 8%) the scale is right, whatever the wheels
            # measured (the rig can measure a rim without its tyre, and then
            # blows the whole car up: a 2020 Jazz 7.4 m long)
            fits = bool(ans.get("length")) and abs(base / ratio * k * 1000.0 / ans["length"] - 1) <= 0.08
            if fits and ((rescaled and not 0.50 <= wheel <= 0.85) or (not rescaled and not 0.75 <= k <= 1.33)):
                info["accepted"] = f"scale x{k:.2f}: the body's length then matches the published {ans['length']} mm"
            elif (rescaled and not 0.50 <= wheel <= 0.85) or (not rescaled and not 0.75 <= k <= 1.33):
                info["refused"] = f"would scale x{k:.2f}" + (f", wheels {wheel:.2f} m" if wheel else "")
                wb = None
        if not wb and rescaled:
            rec["scale_unverified"] = info.get("refused") or info.get("why") or rescaled.get("why")
        rec["wheelbase_lookup"] = info
        return wb, info
    return get


LICENCE = [(r"royalty[- ]free", "royalty-free"), (r"own work|owner", "owner-supplied"),
           (r"non-?commercial.*share-?alike|by-nc-sa", "CC BY-NC-SA"), (r"non-?commercial|by-nc", "CC BY-NC"),
           (r"share-?alike|by-sa", "CC BY-SA"), (r"cc0|public domain", "CC0"), (r"attribution|cc-by|cc by", "CC BY")]


COMMERCIAL = ("CC BY", "CC BY-SA", "CC0", "owner-supplied", "royalty-free")


def _licence_name(raw):
    if re.search(r"free standard|\bstandard\b", raw or "", re.I):
        return "royalty-free"                   # Sketchfab's Free Standard: commercial use in a project
    return next((name for rx, name in LICENCE if re.search(rx, raw or "", re.I)), raw or "unknown")


def credit_of(item):
    """Who made the model and under what licence, from the catalogue record
    and the provenance table (authors_table.json, built by authors.py): no
    outside call. Up to three records of the licence: the catalogue's, the
    one in the file as downloaded (its glTF asset.extras) and the model's
    Sketchfab page now. The catalogue's is wrong for some (NonCommercial
    models filed as CC BY) and some authors changed a model's licence after
    it was downloaded: a model is used commercially only when every record
    there is allows it, and the credit says when they differ. A CC BY model
    with neither its author nor its source to credit is not used commercially."""
    # a stand-in is its donor's model: the donor's record, not "<donor>--as-..."
    prov = authors().get(item.get("standin_donor") or item.get("assetId")) or {}
    emb = (prov.get("embedded") or {}).get("license")
    now = prov.get("licence")
    known = [x for x in (now, emb) if x] or [item.get("licence") or ""]
    names = [_licence_name(x) for x in known]
    lic = names[0]
    make, model = model_of(item)
    title = item.get("sourceTitle") or (prov.get("embedded") or {}).get("title") or prov.get("title") or \
        " ".join(w.upper() if len(w) <= 2 else w.capitalize() for w in f"{make} {model}".replace("-", " ").split())   # Toyota GR Yaris
    author = item.get("sourceCreator") or prov.get("author")
    url = item.get("sourceUrl") or prov.get("source")
    commercial = all(n in COMMERCIAL for n in names) and (bool(author or url) or lic in ("CC0", "owner-supplied"))
    out = {"title": title, "author": author or None, "licence": lic, "url": url, "commercial": commercial,
           "author_missing": not author}
    if len(set(names)) > 1:
        out["licence_note"] = (f"the file was downloaded under {_licence_name(emb)}; its Sketchfab page now says "
                               f"{_licence_name(now)}") if emb and now else f"licence records differ: {', '.join(sorted(set(names)))}"
    # the source page's own title, when it is not the catalogue's: the
    # credit then shows both, for a person to check it is the same model
    pt = prov.get("title") or (prov.get("embedded") or {}).get("title")
    norm_t = lambda t: re.sub(r"[^a-z0-9]", "", str(t or "").lower())  # noqa: E731
    if pt and norm_t(pt) != norm_t(title):
        out["page_title"] = pt
    if not commercial and all(n in COMMERCIAL for n in names):
        out["licence_note"] = "neither its author nor its source is recorded, so it cannot be credited as its licence asks"
    return out


_AUTHORS = {}


def authors():
    """The authors the catalogue leaves out, as their Sketchfab pages name
    them (authors_table.json, built by authors.py from Sketchfab's public
    model pages): {assetId: {"author", "username", "title"}}."""
    if not _AUTHORS:
        p = os.path.join(HERE, "authors_table.json")
        try:
            _AUTHORS.update(json.load(open(p)))
        except (OSError, ValueError):
            _AUTHORS["_none"] = {}
    return _AUTHORS


def run(cmd, timeout, log=None, **kw):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
    if log is not None:
        log.write(" ".join(cmd) + "\n" + p.stdout[-4000:] + p.stderr[-4000:] + "\n")
    return p


SHOTS = [("hero", "az=38&el=14&d=6.6&ty=0.6"), ("all", "az=40&el=22&d=6.9&open=all_open"),
         ("rear", "az=215&el=18&d=6.9&open=all_open"), ("bay", "az=8&el=48&d=3.4&tz=1.25&ty=0.6&open=bonnet_open")]


def shots_for(layout):
    """The sheet's views: a rear-engined car's bay is under its engine lid,
    so its bay view looks at the back."""
    if layout == "rear":
        return [(n, "az=172&el=48&d=3.4&tz=-1.35&ty=0.6&open=tailgate_open" if n == "bay" else q) for n, q in SHOTS]
    return SHOTS


def render_sheet(d, args):
    """The four-view check sheet of a car finished with keep_finished
    (D/finished.glb), drawn after the build: a request that tries more than
    one model draws only the one it keeps. Seconds taken, or an error."""
    fin = os.path.join(d, "finished.glb")
    if not os.path.exists(fin):
        return {"error": "no finished car to draw"}
    rel = os.path.relpath(fin, args.view_dir)
    borrowed = None
    if rel.startswith(".."):
        # built outside the folder the sheet page is served from (make --out):
        # the page can only load a car inside it, so a copy goes there a while
        borrowed = os.path.join(args.view_dir, "_sheet", f"{os.getpid()}.{threading.get_ident()}.glb")
        os.makedirs(os.path.dirname(borrowed), exist_ok=True)
        shutil.copyfile(fin, borrowed)
        rel = os.path.relpath(borrowed, args.view_dir)
    t0 = time.time()
    try:
        # the layout the build used (one() keeps it in build.json; an older
        # build.json: the same rule)
        b = json.load(open(os.path.join(d, "build.json")))
        shots = shots_for(b["layout"] if "layout" in b else layout_of(b["item"]))
    except Exception:
        shots = SHOTS
    try:
        p = subprocess.run(["node", os.path.join(args.tools, "view.mjs"), "1000", "640"] +
                           [f"{os.path.join(d, n)}.png:f={rel}&{q}" for n, q in shots],
                           capture_output=True, text=True, timeout=900, env={**os.environ, "VIEW_PORT": str(args.port)})
    finally:
        if borrowed and os.path.exists(borrowed):
            os.remove(borrowed)
    try:
        from PIL import Image
        ims = [Image.open(os.path.join(d, n + ".png")).convert("RGB") for n, _ in shots]
        W, H = ims[0].size
        S = Image.new("RGB", (W * 2, H * 2))
        for i, im in enumerate(ims):
            S.paste(im, ((i % 2) * W, (i // 2) * H))
        S.save(os.path.join(d, "sheet.jpg"), quality=86)
        for n, _ in shots:
            os.remove(os.path.join(d, n + ".png"))
    except Exception as e:
        return {"error": f"{e}: {(p.stderr or '')[-300:]}"}
    return {"seconds": round(time.time() - t0, 1)}


def body_of(item, args):
    """The body the rigger cuts for, so it cuts the right number of doors:
    the request's ("2 door"), else the catalogue's (coupe, convertible...),
    else the source title's ("3dr"); and the door count the wheelbase table
    gave, if it was that (else None)."""
    body = getattr(args, "body_style", None) or (f"{item['doors']}-door" if item.get("doors") else None) \
        or item.get("bodyStyle") or ""
    if not body and re.search(r"\b[2-5][- ]?(?:door|dr)\b|coupe|cabrio|convertible", item.get("sourceTitle") or "", re.I):
        body = re.search(r"\b[2-5][- ]?(?:door|dr)\b|coupe|cabrio|convertible", item["sourceTitle"], re.I).group(0)
    # a model only ever built with two or three doors (the GR Yaris), when
    # neither the request nor the catalogue says: else its one long door is
    # split into two
    if not getattr(args, "body_style", None) and not TWO_DOOR.search(body or "") \
            and not re.search(r"\b[45][- ]?(?:door|dr)\b", body or "", re.I):
        few = wheelbase.few_doors(*model_of(item), item.get("yearStart") or getattr(args, "year", None))
        if few:
            return f"{few} {body}".strip(), few
    return body, None


RIG_FILES = ("src.glb", "src.report.json", "result.json")


def rig_cache(item, body):
    """The shared folder a catalogue model's rig is kept in for every request
    after the first: $GLBMACHINE_HOME/rigs/<model>/<2|4> (the rigger cuts a
    two-door body apart from a four-door one). Each server job builds in a
    fresh folder; without this it downloaded and rigged its model again."""
    home = os.environ.get("GLBMACHINE_HOME")
    if not home:
        return None
    aid = item.get("standin_donor") or item["assetId"]
    return os.path.join(os.path.expanduser(home), "rigs", aid, "2" if TWO_DOOR.search(body or "") else "4")


def cache_ok(cache):
    """A shared rig made by this rigger, with every file of it there."""
    try:
        return json.load(open(os.path.join(cache, "result.json"))).get("rigger") == rig_mod.VERSION \
            and all(os.path.exists(os.path.join(cache, f)) for f in RIG_FILES)
    except (OSError, ValueError):
        return False


def keep_rig(rig, cache):
    """A fresh rig into the shared cache: copied (a stand-in reshapes its
    src.glb in place afterwards), then put in place whole."""
    tmp = f"{cache}.tmp{os.getpid()}.{threading.get_ident()}"
    try:
        os.makedirs(tmp, exist_ok=True)
        for f in RIG_FILES:
            shutil.copyfile(os.path.join(rig, f), os.path.join(tmp, f))
        if os.path.exists(cache):
            shutil.rmtree(cache)
        os.rename(tmp, cache)
    except OSError:
        shutil.rmtree(tmp, ignore_errors=True)     # another build kept it first


def rig_model(item, d, body, tools, lg, tm):
    """Download a catalogue model into D, decode it to plain geometry (Draco,
    meshopt, quantized -> float) and rig it with our own rigger into D/rig:
    no Blender anywhere. Returns the rigger's result."""
    src, rig = os.path.join(d, "src.glb"), os.path.join(d, "rig")
    # an earlier rig's files go first: a rigger that refuses writes no
    # src.glb, and the build then carried on with the old geometry under the
    # new result ("Golf 2017 2 door": refused as a two-door, built from the
    # four-door rig, and cached that way)
    for f in RIG_FILES:
        if os.path.exists(os.path.join(rig, f)):
            os.remove(os.path.join(rig, f))
    t0 = time.time()
    for attempt in range(3):                     # a transfer cut short is tried again (the Discovery:
        try:                                     # "got only 46219264 out of 47396108 bytes")
            urllib.request.urlretrieve(item["desktopGlbUrl"], src)
            break
        except (urllib.error.ContentTooShortError, urllib.error.URLError, OSError):
            if attempt == 2:
                raise
            if lg is not None:                   # the build's log file
                lg.write(f"download cut short, trying again ({attempt + 2}/3)\n")
            time.sleep(2 * (attempt + 1))
    tm["download"] = round(time.time() - t0, 1)
    t0 = time.time()
    plain = os.path.join(d, "plain.glb")
    run(["node", os.path.join(tools, "decode.mjs"), src, plain], 600, lg)
    tm["decode"] = round(time.time() - t0, 1)
    t0 = time.time()
    back = (item.get("standin_donor") or item["assetId"]) in NOSE_BACK
    p = run([sys.executable, os.path.join(HERE, "rig.py"), plain, rig, f"--body={body}", *(["--nose=back"] if back else [])],
            1200, lg)
    tm["rig"] = round(time.time() - t0, 1)
    for f in (src, plain):
        if os.path.exists(f):
            os.remove(f)
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:
        return {"status": "error", "error": (p.stderr or p.stdout)[-300:]}


def warm(items, args, workers=2, log=print):
    """Rig catalogue models ahead of any request, into the shared cache, so a
    request for them is only finished (seconds). Models already in the cache
    for this rigger are left. Returns {assetId: status}."""
    out = {}

    def one_model(item):
        body, _ = body_of(item, args)
        cache = rig_cache(item, body)
        if cache is None:
            return item["assetId"], "failed: no $GLBMACHINE_HOME for the rig cache"
        if cache_ok(cache):
            return item["assetId"], "cached"
        d = f"{cache}.work{os.getpid()}.{threading.get_ident()}"
        os.makedirs(d, exist_ok=True)
        tm = {}
        try:
            with open(os.path.join(d, "warm.log"), "w") as lg:
                rr = rig_model(item, d, body, args.tools, lg, tm)
            if os.path.exists(os.path.join(d, "rig", "src.glb")):
                keep_rig(os.path.join(d, "rig"), cache)
            if rr.get("status") == "refused":
                return item["assetId"], f"refused: {rr.get('refused')}"      # the rigger's own reason
            return item["assetId"], f"{rr.get('status')} in {sum(tm.values()):.0f} s"
        except Exception as e:
            return item["assetId"], f"failed: {e}"[:200]
        finally:
            shutil.rmtree(d, ignore_errors=True)
    with ThreadPoolExecutor(workers) as ex:
        for aid, st in ex.map(one_model, items):
            out[aid] = st
            log(f"{aid}: {st}")
    return out


def one(target, item, args, out):
    aid = item["assetId"]
    d = os.path.join(out, aid)
    os.makedirs(d, exist_ok=True)
    lg = open(os.path.join(d, "batch.log"), "w")
    rec = {"rank": int(target["rank"]), "target": target["genModel"], "asset": aid,
           "grade": item.get("qualityGrade"), "years": [item.get("yearStart"), item.get("yearEnd")]}
    src, rig = os.path.join(d, "src.glb"), os.path.join(d, "rig")
    rigged = os.path.join(rig, "src.glb")
    rr_path = os.path.join(rig, "result.json")
    tm = {}
    t0 = time.time()
    body, few = body_of(item, args)
    if few:
        rec["body_from_table"] = few
    # the model rigged before, for any request (the shared rig cache): its rig
    # is copied in, and nothing is downloaded or rigged
    cache = rig_cache(item, body)
    if cache and not os.path.exists(rigged) and cache_ok(cache):
        try:
            os.makedirs(rig, exist_ok=True)
            for f in RIG_FILES:
                shutil.copyfile(os.path.join(cache, f), os.path.join(rig, f))
            rec["rig_from_cache"] = True
        except OSError:
            # replaced by another build's rig while it was read (keep_rig):
            # nothing half-copied stays, and the model is rigged here
            for f in RIG_FILES:
                if os.path.exists(os.path.join(rig, f)):
                    os.remove(os.path.join(rig, f))
    rr = json.load(open(rr_path)) if os.path.exists(rigged) and os.path.exists(rr_path) else None
    two = lambda b: bool(TWO_DOOR.search(b or ""))  # noqa: E731
    fresh_rig = False
    # rigged before, with as many doors, by this rigger (or corrected by hand
    # in the Studio since, which a new rig would lose): finish again only
    same_rigger = rr is not None and (rr.get("rigger") == rig_mod.VERSION or os.path.exists(os.path.join(rig, "edits.json")))
    if rr is not None and two(rr.get("body_style")) == two(body) and same_rigger:
        tm["rig"] = 0.0
    else:
        fresh_rig = True
        if rr is not None and not same_rigger:
            rec["rerigged"] = {"was_rigger": rr.get("rigger"), "now": rig_mod.VERSION}
        elif rr is not None:                     # another body: the old cut, and edits made on it, no longer apply
            for f in ("src.glb", "src.orig.glb", "edits.json", "result.json", "src.report.json"):
                if os.path.exists(os.path.join(rig, f)):
                    os.remove(os.path.join(rig, f))
            rec["rerigged"] = {"was": rr.get("body_style", ""), "now": body}
        rr = rig_model(item, d, body, args.tools, lg, tm)
        if cache and os.path.exists(rigged):
            keep_rig(rig, cache)
    rec["rig"] = {k: rr.get(k) for k in ("status", "opens", "missing", "refused", "error")}
    if not os.path.exists(rigged):
        rec["status"] = "rig failed"
        return rec
    rep = json.load(open(os.path.join(rig, "src.report.json")))
    # a stand-in (standin.py): the donor's cut, reshaped to the car asked for.
    # The donor's own cut is kept beside it, so a rebuild reshapes it afresh
    st = item.get("standin")
    if st:
        import standin
        donor = os.path.join(rig, "src.donor.glb")
        if fresh_rig or not os.path.exists(donor):
            shutil.copyfile(rigged, donor)
        st_p = os.path.join(rig, "standin.json")
        prev = json.load(open(st_p)) if os.path.exists(st_p) else None
        if fresh_rig or not prev or prev.get("target") != st or prev.get("version") != standin.VERSION:
            t0 = time.time()
            try:
                prev = {"target": st, "version": standin.VERSION, "warp": standin.warp(donor, st, rigged)}
            except Exception as e:
                rec["status"] = f"stand-in failed: {e}"
                return rec
            json.dump(prev, open(st_p, "w"), indent=1)
            tm["reshape"] = round(time.time() - t0, 1)
        rec["standin"] = prev["warp"]
    cr = credit_of(item)
    rec["credit"] = cr
    spec = {"name": f"{item['make'].title()} {item.get('modelFamily') or item['model']}",
            "engine_pack": args.engine_pack,
            "cabin_pack": getattr(args, "cabin_pack", None) or CABIN_PACK,
            "credit": f"Body, cabin and wheels: '{cr['title']}'" + (f" by {cr['author']}" if cr["author"] else "")
                      + f", {cr['licence']}" + (f", {cr['url']}" if cr["url"] else "") + ". "
                      + (f"Reshaped to the size of the {st['name']} (a stand-in: not that car's own model), r" if st else "R")
                      + "igged, glass cleared and engine bay fitted by the ExpertCarCheck GLB machine."}
    if getattr(args, "paint", None):
        spec["paint"] = list(args.paint)
    elif (item.get("standin_donor") or item["assetId"]) in PLAIN_PAINT:
        spec["paint"] = list(PLAIN_PAINT[item.get("standin_donor") or item["assetId"]])
    if getattr(args, "drive", None):
        spec["drive"] = args.drive
    # an electric car: no engine pack (finish.py keeps its own front end)
    if is_electric(item, (st or {}).get("name")):
        spec["electric"] = True
    # a van opens at the back as two barn doors (finish.py)
    if str(item.get("bodyStyle") or "").lower() == "van" or (st or {}).get("body") == "van":
        spec["body_family"] = "van"
    if aid in TORN:
        spec["close_cracks"] = True
    # a 911 (or a mid-engined car): the engine under the rear lid, which lifts
    # 60 degrees from the rear window; luggage under the front lid
    if layout_of(item) == "rear":
        spec["layout"] = "rear"
        spec.setdefault("hinges", {})["tailgate"] = {"deg": 60}
    if st:
        spec["wheelbase"] = st["wheelbase"]      # reshaped to it already: the finisher checks, and moves nothing
    elif aid in WHEELBASE:
        spec["wheelbase"] = WHEELBASE[aid]
    else:
        spec["wheelbase"] = auto_wheelbase(item, rep, rec, getattr(args, "year", None))
    # a person's corrections from the Studio (edits.py): parts set by hand and
    # hinge choices
    rig_res = json.load(open(rr_path)) if os.path.exists(rr_path) else {}
    rig_hinges = rig_res.get("hinges") or {}
    if rig_hinges:                               # the rig's own: a back door carrying the spare swings sideways
        spec["hinges"] = {**spec.get("hinges", {}), **rig_hinges}
    # sliding side doors: the rig's own judgement (a name, the van signature),
    # and every van's, and a tall MPV's (2.6 wheels or more: the ID Buzz, the
    # Multivan; a Touran or a Galaxy is lower and hinged)
    # The van signature is the rig's guess from door heights alone: a car body
    # the catalogue or the wheelbase table knows keeps its rear doors hinged
    # (the 2016 Jazz and the 2023 Clio pass it: tall cabins, and rear doors
    # modelled taller than the front ones). A slider by name still slides.
    try:
        known = wheelbase.lookup(*model_of(item), item.get("yearStart") or getattr(args, "year", None) or 2015)
    except Exception:
        known = {}
    fam = wheelbase.body_family((st or {}).get("body") or item.get("bodyStyle")) \
        or wheelbase.body_family((known or {}).get("body"))
    slide = {p for p, m in (rig_res.get("motion") or {}).items() if (m or {}).get("type") == "slide"
             and (fam in (None, "van", "mpv") or "signature" not in (m.get("why") or ""))}
    rep_p = os.path.join(rig, "src.report.json")
    sig = (json.load(open(rep_p)).get("door_signature") if os.path.exists(rep_p) else None) or {}
    tall = max([v.get("height_in_wheels") or 0 for v in sig.values()] or [0])
    if spec.get("body_family") == "van" or (str(item.get("bodyStyle") or "").lower() == "mpv" and tall >= 2.6):
        slide |= set(sig)
    for p in sorted(slide & {"door_rl", "door_rr"}):
        spec.setdefault("hinges", {})[p] = {**spec.get("hinges", {}).get(p, {}), "slide": True}
    ed_p = os.path.join(rig, "edits.json")
    if os.path.exists(ed_p):
        ed = json.load(open(ed_p))
        spec["manual"], spec["hinges"] = ed.get("manual") or [], {**spec.get("hinges", {}), **(ed.get("hinges") or {})}
        rec["edited"] = {"manual": spec["manual"], "hinges": spec["hinges"]}
    # how this car was built, so the Studio can build it again
    json.dump({"target": target, "item": item, "paint": getattr(args, "paint", None),
               "body_style": getattr(args, "body_style", None),
               "layout": spec.get("layout")},          # the sheet drawn later (render_sheet) looks where this car's bay is
              open(os.path.join(d, "build.json"), "w"), indent=1, default=str)
    fin = os.path.join(d, "finished.glb")
    if os.path.exists(os.path.join(d, "sheet.jpg")):
        os.remove(os.path.join(d, "sheet.jpg"))     # an earlier build's picture: not this car
    t0 = time.time()
    try:
        flog = finish.finish(rigged, spec, fin)
    except BaseException as e:            # SystemExit from a bad frame too
        rec["status"] = f"finish failed: {e}"
        json.dump(rec, open(os.path.join(d, "record.json"), "w"), indent=1, default=str)
        return rec
    tm["finish"] = round(time.time() - t0, 1)
    rec["finish"] = {k: flog.get(k) for k in ("opens", "missing", "layout", "bonnet", "tailgate", "door_trims", "rescale",
                                              "glass_cleared", "measured", "bay_cleared_m2", "engine_pack", "cabin_pack", "paint_set",
                                              "manual", "wheel_strays", "wheel_tyres_from_body", "right_hand_drive",
                                              "powertrain", "sliding", "cracks_closed")}
    # validator, web copy and check sheet at the same time: the sheet is drawn
    # from the finished file, so it need not wait for the compression
    web = os.path.join(d, "web.glb")
    rel = os.path.relpath(fin, args.view_dir)
    shots = shots_for(spec.get("layout"))
    t0 = time.time()
    procs = {
        "validate": subprocess.Popen(["node", os.path.join(args.tools, "validate.mjs"), fin],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True),
        "encode": subprocess.Popen(["node", os.path.join(args.tools, "encode.mjs"), fin, web],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True),
    }
    if not getattr(args, "no_sheet", False):
        procs["render"] = subprocess.Popen(["node", os.path.join(args.tools, "view.mjs"), "1000", "640"] +
                                           [f"{os.path.join(d, n)}.png:f={rel}&{q}" for n, q in shots],
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                           env={**os.environ, "VIEW_PORT": str(args.port)})
    outs, pv = {}, None
    for k, pr in procs.items():
        try:
            o, e = pr.communicate(timeout=900)
        except subprocess.TimeoutExpired:
            pr.kill()
            o, e = pr.communicate()
        outs[k] = o
        lg.write(f"{k}\n{o[-4000:]}{e[-4000:]}\n")
        tm[k] = round(time.time() - t0, 1)
        if k == "encode" and os.path.exists(web):
            # the web copy is the file people get: it is checked too (a
            # re-write can break what the finished file had right), while the
            # sheet is still being drawn
            pv = subprocess.Popen(["node", os.path.join(args.tools, "validate.mjs"), web],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        rec["validator"] = json.loads(outs["validate"])
    except Exception:
        rec["validator"] = {"errors": -1}
    rec["web_bytes"] = os.path.getsize(web) if os.path.exists(web) else None
    if rec["web_bytes"]:
        try:
            rec["validator_web"] = json.loads(pv.communicate(timeout=600)[0])
        except Exception:
            if pv is not None and pv.poll() is None:
                pv.kill()
                pv.communicate()
            rec["validator_web"] = {"errors": -1}
    try:
        if "render" not in procs:
            raise RuntimeError("no sheet asked for")
        from PIL import Image
        ims = [Image.open(os.path.join(d, n + ".png")).convert("RGB") for n, _ in shots]
        W, H = ims[0].size
        S = Image.new("RGB", (W * 2, H * 2))
        for i, im in enumerate(ims):
            S.paste(im, ((i % 2) * W, (i // 2) * H))
        S.save(os.path.join(d, "sheet.jpg"), quality=86)
        for n, _ in shots:
            os.remove(os.path.join(d, n + ".png"))
    except Exception as e:
        rec["sheet_error"] = str(e)
    rec["timings_s"] = tm
    keep_fin = getattr(args, "keep_finished", False)    # a sheet is drawn from it afterwards (render_sheet)
    if getattr(args, "keep_full", False) and os.path.exists(fin):
        (shutil.copyfile if keep_fin else os.replace)(fin, os.path.join(d, "car_full.glb"))   # opens in any 3D program
    for f in (src,) if keep_fin else (src, fin):  # the rigged copy stays, so a fix re-finishes in seconds
        if os.path.exists(f):
            os.remove(f)
    for f in os.listdir(rig):
        if f.endswith(".png"):
            os.remove(os.path.join(rig, f))
    # what this car should open: what the rig machine found plus what it looked
    # for and missed (a three-door car has no rear doors to miss)
    want = set(rr.get("opens") or []) | set(rr.get("missing") or []) | {"bonnet", "tailgate"}
    want = {"bonnet" if w == "panel_bonnet" else w for w in want}
    # doors come in pairs: a right front door means a left front door to open
    want |= {w[:6] + {"l": "r", "r": "l"}[w[6]] for w in want if re.fullmatch(r"door_[fr][lr]", w)}
    if {"door_bl", "door_br"} & set(flog.get("opens") or []):
        want = (want - {"tailgate"}) | {"door_bl", "door_br"}        # a van's back: two barn doors
    rec["missing"] = sorted(want - set(flog.get("opens") or []))
    ok = not rec["missing"] and rec["validator"].get("errors") == 0 and rec["web_bytes"] \
        and (rec.get("validator_web") or {}).get("errors", 0) == 0 \
        and not rec.get("scale_unverified")
    rec["status"] = "done" if ok else "check"
    json.dump(rec, open(os.path.join(d, "record.json"), "w"), indent=1, default=str)
    return rec


def targets(list_name, cls):
    """Sales-ordered targets: the 2,000-car list (top2000_cars.csv) or the
    multi-class one (targets.csv), as rows with rank, genModel, assetIds."""
    base = os.path.join(REPO, "platform/catalogue/uk_targets")
    if list_name == "top2000":
        return [{"rank": r["rank"], "genModel": r["dft_generic_model"], "assetIds": r["catalogue_ids"]}
                for r in csv.DictReader(open(os.path.join(base, "top2000_cars.csv")))]
    rows = [r for r in csv.DictReader(open(os.path.join(base, "targets.csv"))) if r["class"] == cls]
    return sorted(rows, key=lambda r: int(r["rank"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--top", type=int, default=20, help="how many targets that have a catalogue model")
    ap.add_argument("--list", default="targets", choices=("targets", "top2000"))
    ap.add_argument("--class", dest="cls", default="car")
    ap.add_argument("--engine-pack", required=True)
    ap.add_argument("--tools", required=True)
    ap.add_argument("--view-dir", required=True)
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--workers", type=int, default=1, help="cars built side by side (3 suits 4 cores)")
    ap.add_argument("--keep-rig", action="store_true", help="keep each rigged copy (a fix then only re-finishes)")
    ap.add_argument("--skip", default="", help="comma-separated targets already finished, e.g. 'NISSAN QASHQAI'")
    args = ap.parse_args()
    args.engine_pack = os.path.abspath(args.engine_pack)
    os.makedirs(args.out, exist_ok=True)
    state = os.path.join(args.out, "state.jsonl")
    done = set()
    if os.path.exists(state):
        done = {json.loads(line)["asset"] for line in open(state) if line.strip()}
    cat = catalogue()
    skip = {x.strip() for x in args.skip.split(",") if x.strip()}
    jobs, n = [], 0
    for t in targets(args.list, args.cls):
        if n >= args.top:
            break
        item = pick(t, cat)
        if item is None:
            continue
        n += 1
        if item["assetId"] not in done and t["genModel"] not in skip and \
                item["assetId"] not in {j[1]["assetId"] for j in jobs}:
            jobs.append((t, item))
    server = subprocess.Popen([sys.executable, "-m", "http.server", str(args.port)], cwd=args.view_dir,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    lock = threading.Lock()

    def work(job):
        t, item = job
        t0 = time.time()
        try:
            rec = one(t, item, args, args.out)
        except Exception as e:
            rec = {"rank": int(t["rank"]), "target": t["genModel"], "asset": item["assetId"], "status": f"error: {e}"}
        rec["seconds"] = round(time.time() - t0)
        if not args.keep_rig:
            rg = os.path.join(args.out, item["assetId"], "rig", "src.glb")
            if os.path.exists(rg):
                os.remove(rg)
        with lock:
            with open(state, "a") as f:
                f.write(json.dumps(rec, default=str) + "\n")
            print(rec["rank"], rec["asset"], rec["status"], rec.get("missing"), rec["seconds"], "s", flush=True)
    print(f"{len(jobs)} cars to build, {args.workers} at a time", flush=True)
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            list(ex.map(work, jobs))
    finally:
        server.terminate()


if __name__ == "__main__":
    main()
