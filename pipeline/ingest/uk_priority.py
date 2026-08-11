#!/usr/bin/env python3
"""Reorder a wave manifest so the cars a UK registration is most likely to
decode to render FIRST.

Why this exists: Sketchfab download quota, not GPU or money, is what caps a
night's output. A manifest left in sweep order spends that quota on whatever
the search API happened to return first -- on the Ford wave that was 102
Mustangs ahead of 9 Fiestas. The product goal is reg -> premium 3D car, so a
Fiesta is worth an order of magnitude more than a GT40 and must not queue
behind it.

Tiers are by UK parc / registration volume, not by how interesting the car is:
  T1 supermini + small hatch      - the bulk of the UK fleet
  T2 mainstream family + compact SUV
  T3 common estates, MPVs, vans, larger saloons
  T4 everything else that is still a road car
  T5 halo/sports/classic - real cars, but a reg rarely decodes to one

Within a tier, rows keep their sweep order. Nothing is dropped -- this only
changes what renders first, so an interrupted wave stops having spent its
budget on the right cars.

Usage: uk_priority.py <manifest.json> [--write]
"""
import json, re, sys

T1 = [  # superminis / small hatches — highest UK volume
    "fiesta", "corsa", "polo", "clio", "yaris", "jazz", "fabia", "ibiza", "micra",
    "aygo", "c1", "107", "108", "up", "i10", "i20", "picanto", "rio", "swift",
    "mii", "citigo", "ka", "twingo", "500", "panda", "punto", "sandero", "note",
    "zoe", "leaf", "e-208", "208", "2008", "captur", "juke", "mini",
]
T2 = [  # mainstream family hatch / saloon / compact SUV
    "golf", "focus", "astra", "civic", "corolla", "auris", "megane", "308", "3008",
    "leon", "octavia", "a3", "1 series", "a-class", "c-class", "3 series", "passat",
    "mondeo", "insignia", "qashqai", "kuga", "tucson", "sportage", "kadjar", "yeti",
    "karoq", "kodiaq", "ateca", "tiguan", "q3", "x1", "gla", "cx-5", "cx-3", "rav4",
    "cr-v", "crv", "hr-v", "hrv", "c-hr", "chr", "captiva", "nissan x-trail", "x-trail",
    "3008", "5008", "arkana", "puma", "t-roc", "t-cross", "kona", "bayon", "duster",
]
T3 = [  # estates, MPVs, vans, larger saloons — common but lower volume
    "transit", "tourneo", "turneo", "kangoo", "berlingo", "partner", "caddy", "combo",
    "trafic", "vivaro", "dispatch", "expert", "scudo", "doblo", "connect", "relay",
    "boxer", "ducato", "master", "movano", "sprinter", "vito", "crafter", "talento",
    "scenic", "touran", "zafira", "s-max", "smax", "c-max", "cmax", "galaxy", "sharan",
    "alhambra", "espace", "picasso", "verso", "avensis", "laguna", "vectra", "superb",
    "a4", "a6", "5 series", "e-class", "mondeo estate", "octavia estate", "outlander",
    "discovery sport", "evoque", "range rover", "defender", "discovery", "santa fe",
    "sorento", "shogun", "hilux", "ranger", "navara", "l200", "amarok",
]
T5 = [  # halo / sports / classic — a reg almost never decodes to one
    "gt40", "mustang", "nsx", "s2000", "type r", "rs200", "gt-r", "gtr", "skyline",
    "supra", "silvia", "s15", "s14", "s13", "180sx", "350z", "370z", "z4", "m3", "m5",
    "amg gt", "sl ", "sls", "slr", "gullwing", "300 sl", "pagoda", "testarossa",
    "f40", "f50", "enzo", "diablo", "countach", "aventador", "huracan", "gallardo",
    "carrera", "911", "boxster", "cayman", "elise", "exige", "esprit", "dbs", "db9",
    "vantage", "vanquish", "continental gt", "chiron", "veyron", "senna", "p1",
    "lafferrari", "laferrari", "stratos", "delta integrale", "quattro", "escort rs",
    "cosworth", "integrale", "abarth", "gordini", "williams", "clio v6", "220",
    "alpine", "a110", "dino", "topolino", "2cv", "beetle", "camper", "gt86", "brz",
    "mx-5", "miata", "celica", "mr2", "prelude", "integra", "civic type r", "elan",
]

def _norm(s: str) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", s.lower()).strip() + " "

# Marque-qualified overrides, applied BEFORE the tier lists.
#
# The tier lists match on nameplate alone, which breaks when one marque's
# supermine nameplate is another marque's engine size or halo suffix. Measured
# failures this caused:
#   "2017 Lexus LC 500"  -> T1, because "500" is in the Fiat supermini list, so
#                           every halo LC 500 rendered AHEAD of the IS/RX fleet
#                           cars on the Lexus wave -- exactly backwards.
#   "Mercedes SL 500", "BMW 530", "Audi S5" hit the same class of collision.
# A marque-qualified rule is checked first and wins outright.
_OVERRIDE = [
    # (marque, nameplate-token, tier)
    ("lexus",   "lc",   5), ("lexus", "lfa", 5), ("lexus", "rc", 5),
    ("lexus",   "is",   2), ("lexus", "nx",  2), ("lexus", "ux", 2),
    ("lexus",   "ct",   1), ("lexus", "rx",  3), ("lexus", "es", 3),
    ("mercedes", "sl",  5), ("mercedes", "slk", 5), ("mercedes", "amg gt", 5),
    ("porsche", "911",  5), ("porsche", "718", 5), ("porsche", "cayman", 5),
    ("porsche", "boxster", 5), ("porsche", "macan", 3), ("porsche", "cayenne", 3),
    ("porsche", "panamera", 3), ("porsche", "taycan", 3),
    ("subaru",  "brz",  5), ("subaru", "svx", 5), ("subaru", "impreza", 2),
    ("subaru",  "forester", 2), ("subaru", "outback", 3), ("subaru", "xv", 2),
    ("abarth",  "500",  5),
    # Jaguar, added 2026-08-11 for the Jaguar wave. Without these EVERY Jaguar
    # lands T4 (no nameplate is in T1/T2/T3/T5), so an E-Type or D-Type renders
    # ahead of the XE/XF/F-Pace fleet cars purely on sweep order -- the exact
    # failure this file exists to stop. Order matters: the first hit wins, so
    # the halo suffixes are listed BEFORE the families they glue onto
    # (_tok_hit lets "xj" match "xj220" and "xk" match "xk120").
    ("jaguar", "xj220", 5), ("jaguar", "xjr", 5), ("jaguar", "xjs", 5),
    ("jaguar", "xkr", 5), ("jaguar", "xk8", 5), ("jaguar", "xk 8", 5),
    ("jaguar", "e type", 5), ("jaguar", "etype", 5),
    ("jaguar", "d type", 5), ("jaguar", "dtype", 5),
    ("jaguar", "c type", 5), ("jaguar", "ctype", 5),
    ("jaguar", "f type", 5), ("jaguar", "ftype", 5),
    ("jaguar", "mark 2", 5), ("jaguar", "mk2", 5), ("jaguar", "mk 2", 5),
    ("jaguar", "mark vii", 5), ("jaguar", "240", 5), ("jaguar", "420", 5),
    ("jaguar", "xk", 5),
    ("jaguar", "f pace", 2), ("jaguar", "fpace", 2),
    ("jaguar", "e pace", 2), ("jaguar", "epace", 2),
    ("jaguar", "i pace", 2), ("jaguar", "ipace", 2),
    ("jaguar", "xe", 2), ("jaguar", "xf", 2),
    ("jaguar", "x type", 2), ("jaguar", "xtype", 2),
    ("jaguar", "s type", 3), ("jaguar", "stype", 3),
    ("jaguar", "xj", 3), ("jaguar", "sovereign", 3), ("jaguar", "daimler", 3),
]

def _tok_hit(n: str, word: str) -> bool:
    """Does normalised title `n` contain nameplate `word` as a real token?

    Whole-token match, PLUS the two glued forms that a bare token test misses:
      "rx"  must match "rx450h"  (nameplate + digit-led suffix)
      "500" must match "500l"    (nameplate + short letter suffix)
    but "ka" must NOT match "kangoo" -- the substring bug that put a Renault
    Kangoo in the supermini tier. So a letter suffix is only allowed when the
    nameplate is >=3 characters, and is capped at 2 trailing letters.
    """
    w = _norm(word).strip()
    if not w:
        return False
    if f" {w} " in n:
        return True
    for tok in n.split():
        if not tok.startswith(w) or tok == w:
            continue
        rest = tok[len(w):]
        if re.fullmatch(r"\d[0-9a-z]*", rest):        # rx -> rx450h
            return True
        if len(w) >= 3 and re.fullmatch(r"[a-z]{1,2}", rest):   # 500 -> 500l
            return True
    return False

def tier(name: str) -> int:
    n = _norm(name)
    for marque, plate, t in _OVERRIDE:
        if _tok_hit(n, marque) and _tok_hit(n, plate):
            return t
    def hit(words):
        # Token-aware match (see _tok_hit). A bare substring test put "Renault
        # Kangoo" in T1 because the supermini list contains "ka" -- the same
        # bug class as "cla" matching inside "class" -- while a strict
        # whole-token test missed "rx450h" and "500l".
        return any(_tok_hit(n, w) for w in words)
    # T5 first: a "Civic Type R" is a Civic, but it is a halo car, not fleet.
    if hit(T5):
        return 5
    if hit(T1):
        return 1
    if hit(T2):
        return 2
    if hit(T3):
        return 3
    return 4

def reorder(rows):
    return sorted(enumerate(rows), key=lambda t: (tier(t[1].get("name", "")), t[0]))

def main():
    path = sys.argv[1]
    write = "--write" in sys.argv
    rows = json.load(open(path))
    ordered = [r for _, r in reorder(rows)]
    counts = {}
    for r in ordered:
        counts[tier(r.get("name", ""))] = counts.get(tier(r.get("name", "")), 0) + 1
    print(f"{path}: {len(rows)} rows -> tiers " +
          " ".join(f"T{k}={counts.get(k,0)}" for k in (1, 2, 3, 4, 5)))
    print("  first 8 after reorder:")
    for r in ordered[:8]:
        print(f"    T{tier(r.get('name',''))}  {r.get('name','')[:52]}")
    if write:
        json.dump(ordered, open(path, "w"))
        print("  written")

if __name__ == "__main__":
    main()
