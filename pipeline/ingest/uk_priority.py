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
    # added 2026-08-11 — a coverage check of 97 high-volume UK nameplates found
    # 41 fell through to T4, i.e. the prioritiser could not see the bulk of the
    # actual UK fleet. These are the superminis among them.
    "c3", "ignis", "spark", "i10", "kalos", "getz", "matiz",
]
T2 = [  # mainstream family hatch / saloon / compact SUV
    "golf", "focus", "astra", "civic", "corolla", "auris", "megane", "308", "3008",
    "leon", "octavia", "a3", "1 series", "a-class", "c-class", "3 series", "passat",
    "mondeo", "insignia", "qashqai", "kuga", "tucson", "sportage", "kadjar", "yeti",
    "karoq", "kodiaq", "ateca", "tiguan", "q3", "x1", "gla", "cla", "cx-5", "cx-3", "rav4",
    "cr-v", "crv", "hr-v", "hrv", "c-hr", "chr", "captiva", "nissan x-trail", "x-trail",
    "3008", "5008", "arkana", "puma", "t-roc", "t-cross", "kona", "bayon", "duster",
    # added 2026-08-11 with the T1 batch above — mainstream family cars and
    # compact SUVs the tier lists simply did not know about.
    # "scala" is deliberately NOT here — it is marque-qualified in _OVERRIDE,
    # because "La Scala opera house" is a real Sketchfab title.
    "c4", "cactus", "mokka", "crossland", "grandland", "i30",
    "ioniq", "ceed", "niro", "stonic", "venga", "prius", "ecosport",
    "arona", "q2", "cx-30", "cx30", "vitara", "xc40", "v40", "model 3",
    "model y", "yaris cross", "corolla cross",
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
    # added 2026-08-11 with the T1/T2 batches above.
    "c5", "i40", "i800", "b-max", "bmax", "x3", "x5", "q5", "xc60", "xc90",
    "model s", "model x", "mokka x", "grand c-max", "grand scenic",
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
    # "Mercedes CL 500" scored T1 off Fiat's "500" — the same collision the
    # Lexus LC 500 rules above exist for. "cl" is two characters, so _tok_hit
    # only ever matches it as a whole token: "class" and "clio" are safe.
    ("mercedes", "cl",  5), ("mercedes", "clk", 5),
    # German uploads are titled by TRIM CODE far more often than by class
    # ("Mercedes-Benz C180 W202", not "C-Class"), and the tier lists only knew
    # the class names. Tightening _tok_hit stopped those codes being matched by
    # accident -- "c1" was matching "c180", "a4" was matching "a45" -- which was
    # right, but left 15 real C/A/E-Class cars at T4. These name them properly.
    # AMG halo codes are listed FIRST so "C43 AMG" cannot claim the C-Class tier.
    ("mercedes", "c63", 5), ("mercedes", "c43", 5), ("mercedes", "e63", 5),
    ("mercedes", "a45", 5), ("mercedes", "a35", 5), ("mercedes", "e43", 5),
    ("mercedes", "c180", 2), ("mercedes", "c200", 2), ("mercedes", "c220", 2),
    ("mercedes", "c230", 2), ("mercedes", "c250", 2), ("mercedes", "c300", 2),
    ("mercedes", "c320", 2), ("mercedes", "c350", 2),
    ("mercedes", "a160", 2), ("mercedes", "a180", 2), ("mercedes", "a200", 2),
    ("mercedes", "a220", 2), ("mercedes", "a250", 2),
    ("mercedes", "e200", 3), ("mercedes", "e220", 3), ("mercedes", "e250", 3),
    ("mercedes", "e320", 3), ("mercedes", "e350", 3), ("mercedes", "e400", 3),
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
    # Jeep, added 2026-08-11 after the Jeep wave ran with no Jeep knowledge at
    # all. Renegade and Compass are the two a UK reg actually decodes to in
    # volume; Cherokee and Grand Cherokee are present but thinner; Wrangler is a
    # lifestyle buy, not fleet; and the SRT/Trackhawk/392 V8s, the Gladiator,
    # the Wagoneer and the Commander were never UK-market at all, so a reg can
    # never decode to one. Halo/never-sold rows are listed FIRST so a
    # "Grand Cherokee Trackhawk" cannot claim the Grand Cherokee tier.
    ("jeep", "trackhawk", 5), ("jeep", "srt8", 5), ("jeep", "srt 8", 5),
    ("jeep", "392", 5), ("jeep", "gladiator", 5), ("jeep", "wagoneer", 5),
    ("jeep", "commander", 5), ("jeep", "willys", 5), ("jeep", "cj", 5),
    ("jeep", "renegade", 2), ("jeep", "compass", 2),
    ("jeep", "cherokee", 3), ("jeep", "wrangler", 4),
    # Chrysler, added 2026-08-11 for the Chrysler wave. Without these EVERY
    # Chrysler lands T4 (measured: 38 of the 40 swept rows), so a 1957 New
    # Yorker renders ahead of the 300C and Voyager fleet cars on sweep order
    # alone -- the same failure the Jaguar block above exists for. The other two
    # rows scored WORSE than T4: "CHRYSLER C300 IMPROVED" (a 1955 C-300 letter
    # car) came out T1 because _tok_hit lets Citroen's "c3" swallow "c300", and
    # "Day 308: Vintage Chrysler car" came out T2 off Peugeot's 308.
    #
    # UK relevance is the ONLY axis. A UK reg realistically decodes to a 300C,
    # Voyager/Grand Voyager, PT Cruiser, Ypsilon, Delta, Neon, Sebring or
    # Crossfire. It can NEVER decode to a Pacifica, Aspen, Town & Country,
    # Concorde, LHS, Cirrus, Imperial, New Yorker, Newport, Saratoga, Airflow,
    # Prowler, LeBaron, 200, Turbine or a 300 letter car -- none were UK-market,
    # so those are T5 however good the mesh is. The Ypsilon and Delta are
    # rebadged Lancias sold here 2011-2015 and are genuine UK Chryslers.
    #
    # ORDER MATTERS, first hit wins:
    #  - "300c" is listed BEFORE the letter cars and before bare "300", and the
    #    letter cars before bare "300", because _tok_hit lets a numeric
    #    nameplate take ONE trailing letter: a bare "300" rule would otherwise
    #    claim "Chrysler 300F" for the UK saloon tier. "300c" cannot capture
    #    "300f"/"c300" in return, so putting it first is safe.
    #  - "grand voyager" before "voyager", "town and country" before "country",
    #    "grand caravan" before "caravan".
    #  - "c 300"/"c300" are the 1955 letter car, NOT the 300C.
    ("chrysler", "300c", 3), ("chrysler", "300 c", 3),
    ("chrysler", "c 300", 5), ("chrysler", "c300", 5),
    ("chrysler", "300 letter", 5),
    ("chrysler", "300b", 5), ("chrysler", "300 b", 5),
    ("chrysler", "300d", 5), ("chrysler", "300 d", 5),
    ("chrysler", "300e", 5), ("chrysler", "300 e", 5),
    ("chrysler", "300f", 5), ("chrysler", "300 f", 5),
    ("chrysler", "300g", 5), ("chrysler", "300 g", 5),
    ("chrysler", "300h", 5), ("chrysler", "300 h", 5),
    ("chrysler", "300j", 5), ("chrysler", "300 j", 5),
    ("chrysler", "300k", 5), ("chrysler", "300 k", 5),
    ("chrysler", "300l", 5), ("chrysler", "300 l", 5),
    ("chrysler", "300m", 4),
    # US-market-only nameplates: a UK registration can never decode to one.
    ("chrysler", "pacifica", 5), ("chrysler", "aspen", 5),
    ("chrysler", "town and country", 5), ("chrysler", "town country", 5),
    ("chrysler", "concorde", 5), ("chrysler", "lhs", 5),
    ("chrysler", "cirrus", 5), ("chrysler", "imperial", 5),
    ("chrysler", "new yorker", 5), ("chrysler", "newport", 5),
    ("chrysler", "saratoga", 5), ("chrysler", "airflow", 5),
    ("chrysler", "prowler", 5), ("chrysler", "lebaron", 5),
    ("chrysler", "le baron", 5), ("chrysler", "turbine", 5),
    ("chrysler", "200", 5), ("chrysler", "windsor", 5),
    ("chrysler", "royal", 5), ("chrysler", "valiant", 5),
    ("chrysler", "me four twelve", 5), ("chrysler", "me 412", 5),
    # "me412" is glued in two of the three real uploads, and _tok_hit cannot
    # bridge a space in the RULE into a glued TITLE (CLAUDE.md's separator rule:
    # only the title side is forgiving). Both spellings are listed.
    ("chrysler", "me412", 5), ("chrysler", "me4 12", 5),
    ("chrysler", "firepower", 5),
    ("chrysler", "crossfire", 5),   # UK-sold, but a two-seat halo coupe
    ("chrysler", "viper", 5),       # a Dodge; frequently mislabelled Chrysler
    ("chrysler", "grand caravan", 5), ("chrysler", "caravan", 5),
    # The cars a UK reg actually decodes to.
    ("chrysler", "ypsilon", 1),
    ("chrysler", "delta", 2), ("chrysler", "neon", 2),
    ("chrysler", "pt cruiser", 2), ("chrysler", "ptcruiser", 2),
    ("chrysler", "sebring", 3), ("chrysler", "stratus", 3),
    ("chrysler", "grand voyager", 3), ("chrysler", "voyager", 3),
    ("chrysler", "300", 3),
    # Volvo, added 2026-08-11 for the Volvo wave. Measured before the change:
    # 55 of the 70 filtered rows landed T4, including EVERY S60, V60, V70, S80,
    # S90, V90, S40 and V50 -- so a Wrecked V40 and three C30s rendered ahead of
    # the entire Volvo saloon and estate range on sweep order alone.
    #
    # Two rows scored WORSE than T4, both off the SAME digit-suffix bug the
    # Chrysler block above documents for "C300": "Volvo C30" came out T1 because
    # Citroen's "c3" swallows "c30", and "Volvo C40 Recharge" came out T2 off
    # Citroen's "c4". Those tiers were roughly right by luck, not by rule, and a
    # rule that fires for the wrong marque cannot be relied on.
    #
    # ORDER MATTERS, first hit wins:
    #  - the race cars (BTCC/WTCC) come FIRST so a "Volvo 850 BTCC" cannot claim
    #    the 850 tier; they are competition cars, not fleet.
    #  - "xc70" before "v70", because "Volvo V70 XC" and "Volvo XC70" are the
    #    same estate and both must land in the same place.
    #  - EVERY rule is listed in BOTH the glued and separated spelling. _tok_hit
    #    cannot bridge a space in the RULE into a glued TITLE -- only the title
    #    side is forgiving -- and the real uploads are overwhelmingly glued
    #    ("Volvo XC60", "volvo v70"), while a few are separated ("Volvo S-40").
    ("volvo", "btcc", 5), ("volvo", "wtcc", 5),
    # Halo, competition and classic. Genuinely well-modelled and genuinely loved,
    # but a UK registration in 2026 almost never decodes to one, which is the
    # only axis this file ranks on.
    ("volvo", "p1800", 5), ("volvo", "p 1800", 5), ("volvo", "1800", 5),
    ("volvo", "amazon", 5), ("volvo", "duett", 5),
    ("volvo", "pv444", 5), ("volvo", "pv 444", 5),
    ("volvo", "pv544", 5), ("volvo", "pv 544", 5),
    ("volvo", "pv36", 5), ("volvo", "pv 36", 5),
    ("volvo", "pv4", 5), ("volvo", "pv 4", 5),
    ("volvo", "polestar", 5),
    ("volvo", "240", 5), ("volvo", "242", 5), ("volvo", "244", 5),
    ("volvo", "245", 5), ("volvo", "264", 5),
    ("volvo", "740", 5), ("volvo", "745", 5), ("volvo", "760", 5),
    ("volvo", "850", 5), ("volvo", "940", 5), ("volvo", "960", 5),
    ("volvo", "142", 5), ("volvo", "144", 5), ("volvo", "145", 5),
    ("volvo", "164", 5), ("volvo", "66", 5), ("volvo", "480", 5),
    # The cars a UK registration actually decodes to, in UK parc order. The XC40
    # and XC60 are Volvo UK's volume sellers; the V40 and S60/V60 are the fleet
    # saloons and estates behind them. XC90 is a large seven-seat SUV and V70 the
    # older estate -- common on UK roads, but an order of magnitude behind.
    ("volvo", "xc40", 2), ("volvo", "xc 40", 2),
    ("volvo", "xc60", 2), ("volvo", "xc 60", 2),
    ("volvo", "v40", 2), ("volvo", "v 40", 2),
    ("volvo", "s60", 2), ("volvo", "s 60", 2),
    ("volvo", "v60", 2), ("volvo", "v 60", 2),
    ("volvo", "c30", 2), ("volvo", "c 30", 2),
    ("volvo", "c40", 2), ("volvo", "c 40", 2),
    ("volvo", "ex30", 2), ("volvo", "ex 30", 2),
    ("volvo", "xc70", 3), ("volvo", "xc 70", 3),
    ("volvo", "xc90", 3), ("volvo", "xc 90", 3),
    ("volvo", "v70", 3), ("volvo", "v 70", 3),
    ("volvo", "v50", 3), ("volvo", "v 50", 3),
    ("volvo", "s40", 3), ("volvo", "s 40", 3),
    ("volvo", "s80", 3), ("volvo", "s 80", 3),
    ("volvo", "v90", 3), ("volvo", "v 90", 3),
    ("volvo", "s90", 3), ("volvo", "s 90", 3),
    ("volvo", "ex90", 3), ("volvo", "ex 90", 3),
    # Still road cars, but low UK volume: the C70 is a two-door coupe/convertible
    # and the S70 a short-lived saloon.
    ("volvo", "c70", 4), ("volvo", "c 70", 4),
    ("volvo", "s70", 4), ("volvo", "s 70", 4),
    # Nameplates that are ordinary English/Italian words or bare digits, so they
    # can only be trusted alongside their marque. "Adam", "Viva", "Soul",
    # "Scala" and "Tipo" all occur in unrelated Sketchfab titles, and a bare "2"
    # or "3" would match almost anything.
    # A longer nameplate that CONTAINS a shorter one has to be resolved here:
    # the tier lists are scanned T1 before T2, so a bare "c3" would claim a
    # C3 Aircross for the supermini tier before T2 ever sees it.
    ("citroen", "c3 aircross", 2), ("citroen", "c4 cactus", 2),
    ("citroen", "c5 aircross", 2), ("citroen", "grand c4", 3),
    ("vauxhall", "adam", 1), ("opel", "adam", 1),
    ("vauxhall", "viva", 1), ("opel", "viva", 1),
    ("vauxhall", "agila", 1), ("opel", "agila", 1),
    ("kia", "soul", 2), ("skoda", "scala", 2), ("fiat", "tipo", 2),
    ("audi", "a1", 1), ("audi", "a2", 1),
    # Mazda's bare digits are handled by _PHRASE below, NOT here. The three
    # entries that used to sit at this spot -- ("mazda","6",3), ("mazda","3",2),
    # ("mazda","2",1) -- were measured wrong on the real 2026-08-11 sweep and
    # are removed; see the _PHRASE docstring for what they did.
]

# Bare-digit nameplates, matched ONLY where they are ADJACENT to their marque.
#
# _OVERRIDE tests marque and nameplate independently, which is not good enough
# for a marque whose whole range is single digits. Measured against the real
# Mazda sweep, 2026-08-11:
#   "Mazda 2 1.3"        -> normalises to "mazda 2 1 3"; the bare "3" rule fires
#                           on the ENGINE SIZE, so a Mazda 2 is tiered T2 as a
#                           Mazda 3. Ordering 6/3/2 does not help: the collision
#                           is with the displacement, not between the digits.
#   "Mazda 3 1.6"        -> same, tiered T3 as a Mazda 6.
#   "Mazda6 Wagon 2018"  -> T4. _tok_hit("mazda6", "6") is false (no token
#                           starts with "6"), so every GLUED spelling -- and
#                           Mazda's own badging is glued -- fell straight
#                           through to the "everything else" tier, behind the
#                           MX-5s this file exists to hold back.
#   "Mazda Xedos 6"      -> T3 as a Mazda 6. Different car.
# Requiring adjacency fixes all four at once and needs no ordering trick:
# "mazda\s*6" cannot reach the 6 in "1.6", and \s* spans the glued spelling
# exactly as nameplate_filter's does. It also cannot reach 626/323: the
# trailing \b fails between "6" and "2".
#
# Checked BEFORE _OVERRIDE and before the tier lists. Each entry is
# (marque-token, plate-regex against the normalised title, tier); the marque
# must still be present, so these rules can never fire on another make.
_PHRASE = [
    # Halo first -- an MX-5 or RX-7 must not claim a fleet tier off a stray digit.
    ("mazda", r"\bmx\s*5\b", 5), ("mazda", r"\bmiata\b", 5),
    ("mazda", r"\beunos\b", 5),
    ("mazda", r"\brx\s*7\b", 5), ("mazda", r"\brx\s*8\b", 5),
    ("mazda", r"\brx\s*3\b", 5), ("mazda", r"\brx\s*500\b", 5),
    ("mazda", r"\brx\s*vision\b", 5), ("mazda", r"\brx\s*9\b", 5),
    ("mazda", r"\bcosmo\b", 5), ("mazda", r"\bfurai\b", 5),
    ("mazda", r"\b787\s*b?\b", 5), ("mazda", r"\bsavanna\b", 5),
    ("mazda", r"\bluce\b", 5), ("mazda", r"\blantis\b", 5),
    # OEM performance variants of fleet cars are ROAD cars a reg decodes to, so
    # they keep their family's tier rather than being swept into T5 with the
    # halo cars (CLAUDE.md: "an AMG GT Black Series IS a road car").
    ("mazda", r"\bmazda\s*speed\s*3\b", 2), ("mazda", r"\bmazdaspeed\s*3\b", 2),
    ("mazda", r"\bmazda\s*speed\s*6\b", 3), ("mazda", r"\bmazdaspeed\s*6\b", 3),
    # Longer nameplates that CONTAIN a shorter one, before the short ones.
    ("mazda", r"\bcx\s*30\b", 2), ("mazda", r"\bcx\s*3\b", 2),
    ("mazda", r"\bcx\s*5\b", 2), ("mazda", r"\bcx\s*50\b", 4),
    ("mazda", r"\bcx\s*60\b", 3), ("mazda", r"\bcx\s*7\b", 3),
    ("mazda", r"\bcx\s*8\b", 4), ("mazda", r"\bcx\s*9\b", 4),
    ("mazda", r"\bmx\s*30\b", 3), ("mazda", r"\bmx\s*3\b", 4),
    ("mazda", r"\bmx\s*6\b", 4),
    ("mazda", r"\bxedos\b", 4), ("mazda", r"\bbt\s*50\b", 4),
    ("mazda", r"\bb\s*2\d00\b", 4), ("mazda", r"\bbounty\b", 4),
    ("mazda", r"\btribute\b", 4), ("mazda", r"\bpremacy\b", 3),
    ("mazda", r"\bbongo\b", 3), ("mazda", r"\bmpv\b", 3),
    ("mazda", r"\b323\b", 4), ("mazda", r"\b626\b", 4),
    ("mazda", r"\b121\b", 4), ("mazda", r"\b929\b", 4),
    ("mazda", r"\bfamilia\b", 4), ("mazda", r"\bprotege\b", 4),
    # The fleet. Adjacent to the marque, so an engine size cannot fire them.
    ("mazda", r"\bmazda\s*2\b", 1), ("mazda", r"\bdemio\b", 1),
    ("mazda", r"\bmazda\s*3\b", 2), ("mazda", r"\baxela\b", 2),
    ("mazda", r"\bmazda\s*6\b", 3), ("mazda", r"\batenza\b", 3),
    ("mazda", r"\bmazda\s*5\b", 3),
]
_PHRASE = [(m, re.compile(p), t) for m, p, t in _PHRASE]

# Nameplates that are ALSO plausible model years. "2008" is a Peugeot supermini
# SUV and it is also the year a third of Sketchfab's uploads were built in, so a
# bare token test promoted every car titled "… 2008" into the supermini tier.
# Measured: "2008 Ford Focus" scored T1 — the YEAR outranked the car's own
# nameplate, which is T2 — and the Jeep wave mis-tiered a Grand Cherokee SRT8 to
# T1 the same way. This is not Jeep-specific; it hit every marque swept.
# A yearlike nameplate only counts when the marque that owns it is in the title.
_YEAR_OWNER = {"2008": "peugeot"}

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
        # The digit-suffix expansion is for ALPHABETIC nameplates that carry a
        # numeric variant ("rx" -> "rx450h", "xj" -> "xj220", "cj" -> "cj5").
        # For an all-numeric nameplate, appending digits makes a DIFFERENT car:
        # "500" matched "5008", so every Peugeot 5008 was tiered as a Fiat 500
        # supermini. Numeric nameplates match exactly or with a letter suffix.
        # ...and only when the nameplate does not ALREADY end in a digit.
        # Appending digits to a digit-ending nameplate makes a different car:
        # "c3" matched "c300", so "Mercedes C300 AMG Line" scored T1 as a
        # Citroen C3, and "m3" matched "m340i", scoring an ordinary 3-series as
        # an M3. "rx"/"xj"/"cj" end in letters and are unaffected.
        if not w[-1].isdigit() and re.fullmatch(r"\d[0-9a-z]*", rest):
            return True
        # ONE trailing letter only. Two allowed "cla" to match "class", so a
        # Mercedes C-Class scored as a CLA -- the exact substring bug this
        # function was written to kill, just one size up. Nothing in the tier
        # lists needs a two-letter suffix; "500l" needs one.
        if len(w) >= 3 and re.fullmatch(r"[a-z]", rest):        # 500 -> 500l
            return True
    return False

def tier(name: str) -> int:
    n = _norm(name)
    for marque, rx, t in _PHRASE:
        if _tok_hit(n, marque) and rx.search(n):
            return t
    for marque, plate, t in _OVERRIDE:
        if _tok_hit(n, marque) and _tok_hit(n, plate):
            return t
    def hit(words, allow_yearlike):
        # Token-aware match (see _tok_hit). A bare substring test put "Renault
        # Kangoo" in T1 because the supermini list contains "ka" -- the same
        # bug class as "cla" matching inside "class" -- while a strict
        # whole-token test missed "rx450h" and "500l".
        for w in words:
            if w in _YEAR_OWNER:
                if not allow_yearlike or not _tok_hit(n, _YEAR_OWNER[w]):
                    continue      # "2008" here is a model year, not a Peugeot
            if _tok_hit(n, w):
                return True
        return False

    # Two passes. A yearlike nameplate is a LAST RESORT: "Peugeot 308 2008" is a
    # 308 that happens to be a 2008 model, so the 308 must win even though both
    # tokens are present and both are Peugeot nameplates. Only a title with no
    # other nameplate at all gets to be a Peugeot 2008.
    # T5 is first within each pass: a "Civic Type R" is a Civic, but it is a
    # halo car, not fleet.
    for allow_yearlike in (False, True):
        for tiers, t in ((T5, 5), (T1, 1), (T2, 2), (T3, 3)):
            if hit(tiers, allow_yearlike):
                return t
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
