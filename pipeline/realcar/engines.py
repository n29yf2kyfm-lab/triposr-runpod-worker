"""engines.py: each car's own engine, read from a parts catalogue: its layout and its real parts.

    python3 pipeline/realcar/engines.py build CATALOGUE [CATALOGUE ...]   # -> $GLBMACHINE_HOME/engines.json
    python3 pipeline/realcar/engines.py look MAKE MODEL [YEAR]            # what a car's engine is, and its parts

CATALOGUE is an OEM parts catalogue as CSV (or a zip of CSVs): one row a part fitted to a vehicle, with its
make, model, year and engine. Two layouts are read: the master file's (Brand, Model, Trim / Body, Engine,
Year, Category, Part Name, OEM Number, Description, ...) and the per-brand files' (Make, Model, Body & Trim,
Engine & Transmission, Year, Category, Part Name, OEM Number, ...). Pictures are not read or fetched.

The index (engines.json, in the machine's home, not in git: the catalogue is the owner's) keeps:
- vehicles: make -> model -> year -> its engines, commonest first, and how many parts each was named on
- engines: "make|engine" -> spec (litres, layout, cylinders, fuel, read from the engine's text; see spec())
- parts: "make|model|engine" -> that model's parts for that engine, by system (Timing, Valvetrain, Cylinder
  head, Block and crank, Lubrication, Cooling, Ignition, Fuel, Air and intake, Exhaust, Sensors and control,
  Belts and accessories, Mounts): each part's name, OEM number, on how many of the model's years it was named,
  and its first and last year. Kept by model, not by engine: "3.0L L6 - Gas" is the same words on an M3 and
  an X5, not the same parts

look() finds a car's engine for the car machine: its spec builds the page's running engine to the car's own
layout (an inline-4, a V8, a flat-6, an electric motor), its parts list the Engine tab's real parts.
"""
import collections
import csv
import io
import json
import os
import re
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.environ.get("GLBMACHINE_HOME") or os.path.join(os.path.expanduser("~"), ".glbmachine")
INDEX = os.path.join(HOME, "engines.json")
PARTS_A_SYSTEM = 40                 # parts given per system, the most often fitted first
KEPT_A_SYSTEM = 400                 # parts kept in the index per system per model's engine

# the two layouts' column names, as one
COLS = {"make": ("Brand", "Make"), "model": ("Model",), "year": ("Year",), "engine": ("Engine", "Engine & Transmission"),
        "trim": ("Trim / Body", "Body & Trim"),
        "category": ("Category",), "name": ("Part Name",), "oem": ("OEM Number",)}

# a part's system, by words in its name: the first that matches (checked in this order)
NOT_ENGINE = re.compile(r"\b(tire|tpms|brake|wiper|door|seat|window|hood|headl|lamp|light|bumper|mirror|evaporator|"
                        r"condenser|blower|cabin|transmission|transaxle|axle|wheel|shock|strut|control arm|steering|"
                        r"a/c|ac compressor|expansion valve|refrigerant|clutch|differential|drive shaft|cv |trim|"
                        r"emblem|badge|grille|fender|weatherstrip|glass|horn|radio|speaker|airbag|logo|valve stem caps?\b|tire valve)", re.I)
SYSTEMS = [
    ("Timing", r"timing|sprocket|chain guide|chain tensioner|variable valve|vvt|camshaft adjuster|cam phaser|phaser"),
    ("Sensors and control", r"sensor|solenoid|\becm\b|\bpcm\b|control module|control unit|wiring harness|knock|"
                            r"switch|actuator|relay"),
    ("Valvetrain", r"camshaft|rocker|lifter|follower|tappet|valve spring|valve stem|intake valve|exhaust valve|"
                   r"valve guide|valve seat|valve keeper|valve retainer|spring retainer|^valve$|^valve lifters?$"),
    ("Cylinder head", r"cylinder head|head gasket|valve cover|cam cover|head bolt|rocker cover"),
    ("Block and crank", r"piston|connecting rod|rod bearing|crankshaft|main bearing|thrust washer|engine block|"
                        r"cylinder block|core plug|crankcase|cylinder liner|flywheel|flexplate|flex plate|"
                        r"harmonic balancer|vibration damper|balance shaft|short block|long block"),
    ("Lubrication", r"oil pump|oil pan|oil filter|oil cooler|dipstick|oil drain|oil separator|\bpcv\b|oil seal|"
                    r"oil pressure|oil level|oil filler|oil cap|engine oil"),
    ("Cooling", r"water pump|thermostat|coolant|radiator|cooling fan|fan clutch|expansion tank|heater hose|"
                r"engine fan"),
    ("Ignition", r"spark plug|ignition coil|coil pack|glow plug|distributor|ignition wire|spark plug wire"),
    ("Fuel", r"fuel injector|injector|fuel pump|fuel rail|fuel filter|fuel pressure|fuel line|high pressure pump|"
             r"injection pump|fuel hose|fuel tank"),
    ("Air and intake", r"intake manifold|air filter|air intake|throttle body|intake hose|air box|air cleaner|"
                       r"turbo|intercooler|supercharger|charge air|boost|resonator|air duct|intake"),
    ("Exhaust", r"exhaust manifold|catalytic|\begr\b|downpipe|exhaust pipe|muffler|exhaust"),
    ("Belts and accessories", r"serpentine|drive belt|accessory belt|v-belt|ribbed belt|belt tensioner|idler|"
                              r"tensioner pulley|alternator|starter|power steering pump|\bbelt\b"),
    ("Mounts", r"engine mount|motor mount|mount bracket|engine support|torque strut"),
]
SYSTEMS = [(s, re.compile(p, re.I)) for s, p in SYSTEMS]


def system_of(name):
    """The engine system a part's NAME belongs to, or None (not an engine part)."""
    if not name or NOT_ENGINE.search(name):
        return None
    for s, pat in SYSTEMS:
        if pat.search(name):
            return s
    return None


LAYOUT = {"L": "inline", "I": "inline", "V": "v", "H": "flat", "B": "flat", "W": "w", "R": "rotary"}


def spec(text):
    """An engine's text as {litres, layout, cylinders, fuel, electric, guessed}: "2.0L L4 - Gas", "3.0L V6 -
    Electric/Gas", "LY2 4.8L Petrol 8-cyl", "GAS, 6 CYL, 4.3L, MFI, V6, 90 DEG", "1368 PT (1.4)",
    "BATTERY EV (EV/BEV)". A cylinder count the text does not give is guessed from the litres (guessed: True)."""
    t = (text or "").strip()
    u = t.upper()
    out = {"text": t, "litres": None, "layout": None, "cylinders": None, "fuel": "petrol", "electric": False, "guessed": False}
    if not t or u in ("ALL ENGINES", "ENGINE"):
        return None
    if re.fullmatch(r"ELECTRIC|.*\bBEV\b.*|.*BATTERY EV.*|.*FUEL CELL.*", u) and "GAS" not in u:
        out.update(fuel="electric", electric=True, layout="electric", cylinders=0)
        return out
    m = re.search(r"(\d+(?:\.\d+)?)\s*L\b", u) or re.search(r"\((\d\.\d)\b", u)
    if m:
        out["litres"] = float(m.group(1))
    else:
        cc = re.search(r"\b(\d{3,4})\b", u)
        if cc and 500 <= int(cc.group(1)) <= 8500:
            out["litres"] = round(int(cc.group(1)) / 1000, 1)
    # the first layout word that is one ("L84 5.3L Petrol V8": L84 is GM's engine code, V8 the layout)
    m = next((m for m in re.finditer(r"\b([LVHWRIB])(\d{1,2})\b", u) if 1 <= int(m.group(2)) <= 16), None)
    if m:
        out["layout"], out["cylinders"] = LAYOUT[m.group(1)], int(m.group(2))
    else:
        m = re.search(r"\b(\d{1,2})\s*-?\s*CYL", u)
        if m:
            out["cylinders"] = int(m.group(1))
        m = re.search(r"\b(\d{1,2})\s*-\s*(?:ELECTRIC|GAS|DIESEL)", u)
        if m and not out["cylinders"]:
            out["cylinders"] = int(m.group(1))
    if out["cylinders"] and not out["layout"]:
        out["layout"] = "inline" if out["cylinders"] <= 6 and "V6" not in u else "v"
    if not out["cylinders"] and out["litres"]:
        L = out["litres"]
        out["cylinders"], out["layout"] = (3, "inline") if L < 1.15 else (4, "inline") if L < 2.6 else \
            (6, "v") if L < 3.9 else (8, "v")
        out["guessed"] = True
    if not out["cylinders"]:
        return None
    if re.search(r"DIESEL|\bJTD|\bTDI|\bCDI|\bHDI|\bDCI|\bCRDI", u):
        out["fuel"] = "diesel"
    if re.search(r"PLUG-IN|\bPHEV|\(PH", u):
        out["fuel"] = "plug-in hybrid"
    elif re.search(r"ELECTRIC/|HYBRID|\bMHEV|\bFHEV", u):
        out["fuel"] = "hybrid"
    elif "FLEX" in u:
        out["fuel"] = "flex"
    elif "CNG" in u or "BI-FUEL" in u:
        out["fuel"] = "gas (CNG)"
    return out


def describe(sp):
    """A spec in words: "2.0-litre inline-4 petrol", "4.4-litre V8 petrol hybrid", "electric"."""
    if not sp:
        return None
    if sp["electric"]:
        return "electric"
    shape = {"inline": f"inline-{sp['cylinders']}", "v": f"V{sp['cylinders']}", "flat": f"flat-{sp['cylinders']}",
             "w": f"W{sp['cylinders']}", "rotary": f"{sp['cylinders']}-rotor rotary"}.get(sp["layout"], f"{sp['cylinders']}-cylinder")
    fuel = {"petrol": "petrol", "diesel": "diesel", "hybrid": "petrol hybrid", "plug-in hybrid": "petrol plug-in hybrid",
            "flex": "flex-fuel", "gas (CNG)": "gas (CNG)"}.get(sp["fuel"], sp["fuel"])
    return (f"{sp['litres']:.1f}-litre " if sp.get("litres") else "") + f"{shape} {fuel}"


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def rows(path):
    """Every row of a catalogue file (CSV, or the CSVs in a zip), its columns named as COLS's keys."""
    def read(fh):
        r = csv.DictReader(fh)
        names = {k: next((c for c in (r.fieldnames or []) if c.lstrip("﻿") in v), None) for k, v in COLS.items()}
        if not names["make"] or not names["engine"]:
            return
        for row in r:
            yield {k: (row.get(c) or "").strip() if c else "" for k, c in names.items()}
    csv.field_size_limit(10 ** 8)
    if path.endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if n.lower().endswith(".csv"):
                    yield from read(io.TextIOWrapper(z.open(n), encoding="utf-8-sig", errors="replace"))
    else:
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            yield from read(fh)


def build(sources, out=INDEX):
    """The index from the catalogue files SOURCES, written to OUT."""
    t0 = time.time()
    veh = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(collections.Counter)))
    parts = collections.defaultdict(lambda: collections.defaultdict(dict))   # make|model|engine -> system -> (name, oem) -> [years named, first, last]
    fits = collections.defaultdict(set)              # engine -> its (model, year)s
    trims = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))   # make|model|year -> engine -> trims
    rows_of = collections.Counter()                  # (make|model|year, engine) -> rows
    seen = set()
    n = 0
    for src in sources:
        for r in rows(src):
            n += 1
            make = norm(r["make"])
            if not make:
                continue
            for e in r["engine"].split(";"):
                e = e.strip()
                if not e or spec(e) is None:
                    continue
                key = f"{make}|{e}"
                veh[make][norm(r["model"])][r["year"]][e] += 1
                fits[key].add((norm(r["model"]), r["year"]))
                mm = f"{make}|{norm(r['model'])}|{r['year']}"
                rows_of[(mm, e)] += 1
                # a part named on a trim or two says which engine those trims have; one fitting every trim of the
                # model says nothing: each row's trims count 1/(how many it names)
                ts = [norm(t) for t in r["trim"].split(";") if norm(t)]
                for t in ts:
                    trims[mm][e][t] += 1 / len(ts)
                s = system_of(r["name"])
                if s:
                    k = (key, r["oem"] or r["name"], r["model"], r["year"])
                    if k not in seen:                 # a part named on one vehicle-year counts once there
                        seen.add(k)
                        y = int(r["year"]) if r["year"].isdigit() else None
                        p = parts[f"{make}|{norm(r['model'])}|{e}"][s].setdefault((r["name"], r["oem"]), [0, y, y])
                        p[0] += 1
                        if y:
                            p[1], p[2] = min(p[1] or y, y), max(p[2] or y, y)
            if n % 200000 == 0:
                print(f"  {n} rows ({time.time() - t0:.0f} s)", flush=True)
    engines = {}
    for key, f in fits.items():
        sp = spec(key.split("|", 1)[1])
        engines[key] = {"spec": sp, "words": describe(sp), "vehicle_years": len(f)}
    kept = {k: {s: [[nm, oem, *c] for (nm, oem), c in sorted(ps[s].items(), key=lambda x: -x[1][0])[:KEPT_A_SYSTEM]]
                for s, _ in SYSTEMS if ps.get(s)} for k, ps in parts.items()}
    vehicles = {mk: {md: {y: [e for e, _ in c.most_common()] for y, c in ys.items()} for md, ys in mds.items()}
                for mk, mds in veh.items()}
    # each engine's trims, with on how many of its rows each is named: a trim of its own is on nearly all
    # of them, one of the model's every engine only on the parts they share
    trim_of = {mm: {e: {"n": rows_of[(mm, e)], "t": {t: round(v, 1) for t, v in c.most_common(20) if v >= 0.5}}
                    for e, c in es.items()} for mm, es in trims.items()}
    idx = {"built": time.strftime("%Y-%m-%d %H:%M"), "sources": [os.path.basename(s) for s in sources], "rows": n,
           "vehicles": vehicles, "engines": engines, "trims": trim_of, "parts": kept}
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out + ".part", "w") as fh:
        json.dump(idx, fh, separators=(",", ":"))
    os.replace(out + ".part", out)
    return {"rows": n, "makes": len(vehicles), "models": sum(len(v) for v in vehicles.values()), "engines": len(engines),
            "written": out, "seconds": round(time.time() - t0)}


_IDX = None


def index(path=INDEX):
    global _IDX
    if _IDX is None:
        _IDX = json.load(open(path)) if os.path.exists(path) else {"vehicles": {}, "engines": {}}
    return _IDX


MAKE_ALIAS = {"vw": "volkswagen", "merc": "mercedes benz", "mercedes": "mercedes benz", "chevy": "chevrolet",
              "range rover": "land rover", "landrover": "land rover"}


def find_model(models, model):
    """The catalogue's models for MODEL: the same words; for a BMW-style "3 Series" its numbered models (328i,
    330e ..., not the M cars unless asked); else one holding all its words (A4 -> A4 Quattro); else one whose
    first word is its first word (at least three letters)."""
    q = norm(model)
    if not q:
        return []
    if q in models:
        return [q]
    s = re.fullmatch(r"(\d) series( m)?", q)
    if s:
        if s.group(2):
            return sorted(m for m in models if re.fullmatch(rf"(m{s.group(1)}|{s.group(1)} series m)( .*)?", m))
        return sorted(m for m in models if re.fullmatch(rf"{s.group(1)}\d\d[a-z]*( [a-z]+)*", m))
    words = set(q.split())
    hold = sorted((m for m in models if words <= set(m.split())), key=len)
    if hold:
        return hold[:1]
    # a model all of whose words were asked ("golf gti" -> gti, "range rover sport svr" -> range rover sport):
    # the one of most words, then the one named latest (a trim comes after its model)
    qs = q.split()
    inside = [m for m in models if set(m.split()) <= words]
    if inside:
        return [max(inside, key=lambda m: (len(m.split()), max(qs.index(w) for w in m.split())))]
    first = qs[0]
    if len(first) >= 3:
        return sorted((m for m in models if m.split() and m.split()[0] == first), key=len)[:1]
    return []


RECENT_YEARS = 8                    # with no year asked, the engine of the model's latest years
# an electric car's list has no use for these: rows of them on one are the catalogue's slips
NOT_ELECTRIC = {"Timing", "Valvetrain", "Cylinder head", "Block and crank", "Ignition", "Fuel", "Exhaust"}


def own_parts(idx, mk, ms, e, years, electric=False):
    """The parts the catalogue names for engine E in models MS (of make MK) in YEARS (first, last): by system,
    [name, OEM numbers, years named], one row a name (its OEM numbers, the most used first: a switch in 14
    paints is one switch), the most named first. With the part count, how many rows were left out, and every
    part name kept (construction() reads the engine's build from them)."""
    rows = collections.defaultdict(dict)
    for m in ms:
        for s, ps in ((idx.get("parts") or {}).get(f"{mk}|{m}|{e}") or {}).items():
            for nm, oem, n, y0, y1 in ps:
                if years and y0 and (y1 < years[0] or y0 > years[1]):
                    continue
                r = rows[s].setdefault((nm, oem), [0])
                r[0] += n
    left_out = sum(len(v) for s, v in rows.items() if electric and s in NOT_ELECTRIC)
    out = {}
    for s, _ in SYSTEMS:
        if s not in rows or (electric and s in NOT_ELECTRIC):
            continue
        by_name = collections.defaultdict(list)
        for (nm, oem), (n,) in sorted(rows[s].items(), key=lambda x: -x[1][0]):
            by_name[nm].append((oem, n))
        named = sorted(by_name.items(), key=lambda x: -max(n for _, n in x[1]))[:PARTS_A_SYSTEM]
        out[s] = [[nm, ", ".join(o for o, _ in v[:2] if o) + (f" +{len(v) - 2} more" if len(v) > 2 else ""),
                   max(n for _, n in v)] for nm, v in named]
    names = collections.Counter(nm for s, v in rows.items() if not (electric and s in NOT_ELECTRIC) for nm, _ in v)
    return out, sum(len(v) for s, v in rows.items() if not (electric and s in NOT_ELECTRIC)), left_out, names


# makes whose V8s (and GM's 4.3 V6) carry one camshaft in the block, pushing the valves through pushrods and
# rockers: the catalogue does not name the pushrods (GM's lists "Engine Camshaft" and "Valve Rocker Arm Cover"),
# so it is read from what the engine is. Their overhead-cam V8s are the exceptions (litres): Cadillac's
# Northstar and Blackwing, the Corvette Z06's flat-plane 5.5, Chrysler's 4.7
PUSHROD = {"chevrolet": "gm", "gmc": "gm", "cadillac": "gm", "buick": "gm", "pontiac": "gm", "hummer": "gm",
           "dodge": "chrysler", "ram": "chrysler", "chrysler": "chrysler", "jeep": "chrysler"}
OHC_V8 = {"gm": {4.2, 4.4, 4.6, 5.5}, "chrysler": {4.7}}
TURBO = re.compile(r"\bturbo(?:charger)?\b|wastegate", re.I)
SUPER = re.compile(r"supercharg", re.I)


def construction(names, sp, make):
    """How the engine is built, from its part NAMES (own_parts') and its spec: valvetrain (pushrod or overhead
    cam), timing (belt or chain), induction (turbo or supercharged, and turbos: how many; None when the catalogue
    lists neither, which is not the same as none: it lists no turbo part for some turbo engines), balance shafts
    and hybrid (a motor in the driveline). Each with the parts that say so (evidence), or the rule (PUSHROD)."""
    if not sp or sp.get("electric"):
        return None
    has = lambda rx: sorted(n for n in names if rx.search(n))  # noqa: E731
    out, ev = {}, {}
    fam = PUSHROD.get(make)
    L = round(sp.get("litres") or 0, 1)
    pushrod = bool(fam) and ((sp["layout"] == "v" and sp["cylinders"] == 8 and L not in OHC_V8[fam] and
                              (fam == "gm" or L >= 5.2)) or
                             (fam == "gm" and sp["layout"] == "v" and sp["cylinders"] == 6 and L == 4.3))
    out["valvetrain"] = "pushrod" if pushrod else "overhead cam"
    if pushrod:
        ev["valvetrain"] = [f"{make.title()}'s {L}-litre V{sp['cylinders']}: a pushrod engine"]
    belt, chain = has(re.compile(r"timing belt", re.I)), has(re.compile(r"timing chain", re.I))
    out["timing"] = "belt" if belt and not chain else "chain" if chain or pushrod else None
    ev["timing"] = (belt if out["timing"] == "belt" else chain)[:3]
    t, sc = has(TURBO), has(SUPER)
    out["induction"] = "turbo" if t else "supercharged" if sc else None
    if t:                 # a V or flat six and up: a turbo a bank
        out["turbos"] = 2 if sp["layout"] in ("v", "flat") and sp["cylinders"] >= 6 else 1
    ev["induction"] = (t or sc)[:3]
    bs = has(re.compile(r"balance shaft", re.I))
    out["balance_shafts"] = bool(bs)
    if bs:
        ev["balance_shafts"] = bs[:2]
    out["hybrid"] = sp.get("fuel") in ("hybrid", "plug-in hybrid")
    out["evidence"] = {k: v for k, v in ev.items() if v}
    return out


def built_words(c):
    """construction()'s answer in words: "twin-turbo, overhead camshafts, timing chain" (a hybrid's is in its
    engine's words already: describe's "petrol hybrid")."""
    if not c:
        return ""
    w = [{"turbo": "twin-turbo" if c.get("turbos") == 2 else "turbo", "supercharged": "supercharged"}.get(c["induction"]),
         "pushrod valves (one camshaft in the block)" if c["valvetrain"] == "pushrod" else "overhead camshafts",
         f"timing {c['timing']}" if c["timing"] else None, "balance shafts" if c["balance_shafts"] else None]
    return ", ".join(x for x in w if x)


def look(make, model, year=None, idx=None, trim=None):
    """MAKE MODEL YEAR's engine from the index: {"engine", "spec", "words", "others", "parts", "matched"}, or None.
    TRIM ("Turbo S", "GTI") picks, of the year's engines, the one the catalogue names on that trim."""
    idx = idx or index()
    mk = MAKE_ALIAS.get(norm(make), norm(make))
    models = idx["vehicles"].get(mk) or {}
    ms = find_model(models, model)
    if not ms:
        return None
    years = collections.defaultdict(collections.Counter)
    for m in ms:
        for y, es in models[m].items():
            for i, e in enumerate(es):
                years[y][e] += len(es) - i
    if not years:
        return None
    ys = sorted((y for y in years if y.isdigit()), key=int)
    want = str(year) if year and str(year) in years else None
    if not want and year and ys:
        want = min(ys, key=lambda y: abs(int(y) - int(year)))
    recent = ys[-RECENT_YEARS:] or list(years)
    pool = years[want] if want else sum((years[y] for y in recent), collections.Counter())
    ranked = [e for e, _ in pool.most_common()]
    by_trim = None
    tw = set(norm(trim).split()) if trim else set()
    if tw:
        tri = idx.get("trims") or {}
        score, loose = collections.Counter(), collections.Counter()
        for m in ms:
            for y in ([want] if want else recent):
                for e2, ts in (tri.get(f"{mk}|{m}|{y}") or {}).items():
                    if e2 in pool and isinstance(ts, dict) and ts.get("n"):
                        # the share of the engine's rows that year naming the trim (its words exactly: "turbo s",
                        # not "turbo"), each row weighed by how few trims it names (build())
                        named = sum(c for t, c in ts["t"].items() if set(t.split()) == tw)
                        if named >= 3:
                            score[e2] = max(score[e2], named / ts["n"])
                        # else the trims holding its words ("p400" in "p400 se"), a little behind
                        within = sum(c for t, c in ts["t"].items() if tw < set(t.split()))
                        if within >= 3:
                            loose[e2] = max(loose[e2], within / ts["n"])
        score = score or loose
        if score and score.most_common(1)[0][1] > 0:
            by_trim = score.most_common(1)[0][0]
            ranked = [by_trim] + [x for x in ranked if x != by_trim]
    e = ranked[0]
    info = idx["engines"].get(f"{mk}|{e}") or {}
    sp = info.get("spec") or spec(e)
    span = (int(want), int(want)) if want and want.isdigit() else (int(recent[0]), int(recent[-1])) \
        if recent and recent[0].isdigit() else None
    parts, count, left_out, names = own_parts(idx, mk, ms, e, span, bool(sp and sp.get("electric")))
    built = construction(names, sp, mk)
    return {"engine": e, "spec": sp, "words": info.get("words") or describe(sp), "construction": built,
            "built_words": built_words(built),
            "others": [{"engine": o, "words": describe(spec(o))} for o in ranked[1:6]],
            "parts": parts, "part_count": count, "left_out": left_out,
            "matched": {"make": mk, "models": ms[:4], "models_n": len(ms), "year": want, "asked_year": year,
                        "trim": trim if by_trim else None,
                        "years": None if want else f"{recent[0]}-{recent[-1]}" if recent and recent[0].isdigit() else None}}


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "build":
        print(json.dumps(build(sys.argv[2:]), indent=1))
    elif len(sys.argv) >= 4 and sys.argv[1] == "look":
        r = look(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)
        if r:
            r = {**r, "parts": {s: v[:5] for s, v in r["parts"].items()}}
        print(json.dumps(r, indent=1))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
