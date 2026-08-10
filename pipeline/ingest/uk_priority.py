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

def tier(name: str) -> int:
    n = _norm(name)
    def hit(words):
        # Whole-token match ONLY. A bare substring test put "Renault Kangoo"
        # in T1 because the supermini list contains "ka" -- the same class of
        # bug as "cla" matching inside "class". Both sides are normalised so a
        # multi-word entry ("range rover", "e-208") still matches.
        return any(_norm(w) in n for w in words)
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
