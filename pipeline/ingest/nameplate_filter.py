#!/usr/bin/env python3
"""nameplate_filter.py — keep only the rows of a marque sweep that are actually
cars of that marque.

Why this exists
---------------
`marque_sweep.py` fires one generic query for the marque name plus one query per
nameplate, then filters by face count and the `wave_render.class_gates` title
gates. That works for a marque whose name is not an ordinary English word. It
fails badly for one that is.

Measured on the SEAT sweep, 2026-08-08: the bare query `SEAT` returned **1,425**
results against 22 for `SEAT Ibiza`. 707 landed inside the face band, the title
gates rejected **20**, and 415 reached the manifest — of which only **43**
carried any SEAT nameplate. The other 372 were three-seat airline rows, ejection
seats, sofas, a seated Bodhisattva, and car-interior seats from other marques.
Rendering that manifest would have been ~1,660 GPU views for a yield near 35.

The class gates cannot catch this on their own: they reject a title by what it
looks like (`scan`, `train`, `bus`), and "Leather Car Seat" looks like nothing
in particular. The reliable signal is the opposite one — a real SEAT Leon says
"Leon" somewhere in its title. So require a nameplate, rather than trying to
enumerate every wrong thing.

This is not SEAT-specific. Any marque whose name collides with a common word
needs it (SEAT, Born, Smart, Lotus, Jaguar in a wildlife sense). Run it on any
sweep where the bare-marque query returns wildly more than the nameplate
queries — that ratio is the tell.

Two rules learned on the MINI sweep, 2026-08-08
-----------------------------------------------
**Pass only marque-SPECIFIC nameplates.** MINI's own range includes One, Coupé,
Convertible, Roadster, Hatch and Traveller — words so generic that feeding them
in as nameplates would admit any other marque's convertible. The MINI sweep did
pull in cross-marque rows ("Dodge Mini Ram Van 1984", "Geely Mini Panda",
"Wuling Hongguang Mini EV"), so this is not hypothetical. Pass Cooper, Clubman,
Countryman, Paceman, JCW, Moke and the like; leave the generic ones out and
accept losing a bare-titled car rather than admitting hundreds of wrong ones.

**Some marques cannot be recovered by nameplate alone.** A classic Mini is often
titled just "Mini", and 383 of the 432 MINI candidates matched `\\bmini\\b` while
being mini skirts, mini golf, DJI Mavic Minis and Poppy Playtime characters. A
handful of genuine ambiguous titles ("Classic Red Mini", "Mini Coupe") are worth
rendering anyway — rendering one sheet is seconds of GPU and the eye settles it
instantly, where a title guess cannot. That is what `--allow-uid` is for: force
specific rows through so the reviewer decides, instead of the filter deciding.

Usage:
    nameplate_filter.py --in m.json --out m.filtered.json \
        --nameplates "Ibiza,Leon,Arona,..." [--allow-uid a,b,c] [--report]
"""
import argparse, json, re, sys, unicodedata

# Titles that carry a nameplate but are a part, a prop or an unusable scale
# model rather than a whole car. Each of these was present in the SEAT sweep.
PART_WORDS = [
    "headlight", "taillight", "tail light", "rear light", "enginebay",
    "engine bay", "engine", "interior", "dashboard", "dash ", "steering",
    "wheel only", "rim", "alloy", "seat cover", "badge", "logo", "emblem",
    "bumper", "spoiler", "grill", "grille", "mirror", "door panel", "exhaust",
    "brake", "caliper", "gearknob", "gear knob", "key ", "keyfob",
    # Wheel, in the languages uploaders actually use. "Roda Peugeot 208 ACTIVE"
    # is an alloy wheel and would otherwise have been rendered as a car.
    "roda", "rueda", "jante", "felge", "cerchio", "llanta",
    # Bare component words that reached render on the Honda wave 2026-08-09:
    # a "Civic Wheel" terrain scan, a "Pilot Upper Airbox", a "CRV Waterpump".
    "wheel", "airbox", "pump", "waterpump", "manifold", "radiator",
    # Land Rover sweep 2026-08-09: "Range Rover Velar Tyre" (367,725 faces) and
    # "Land Rover Series 3 Wiper Cover" (952,096) both carried a valid nameplate
    # and would have been downloaded and rendered as cars. \b anchoring means
    # "tire" does NOT match inside "entire".
    "tyre", "tire", "wiper",
    # Mazda sweep 2026-08-11. Four component models carried a valid nameplate,
    # sat inside the face band, and would have been downloaded and rendered as
    # cars: "1994 Mazda Rx7 Front Passenger Suspension" (859,129 faces),
    # "1999 Mazda Miata Drivetrain 1.8L" (313,003), "Rotor motor Wankel 13B
    # Mazda RX8" (139,318) and "Mazda-RX-7- Widebody (body only)" (96,682).
    # "engine" was already listed but catches none of them -- a rotary is a
    # "motor"/"wankel"/"rotor", never an "engine", in the titles uploaders use.
    # \b anchoring keeps these narrow: "motor" does NOT match inside
    # "Versus Motorsport", which is a whole car in this same sweep.
    "suspension", "drivetrain", "gearbox", "chassis", "subframe", "axle",
    "differential", "motor", "wankel", "rotor", "body only", "hubcap",
]
# Commercial vehicles and construction plant — a whole VEHICLE, correctly named,
# correctly on-marque, that no car registration can ever decode to.
#
# Added 2026-08-11 for the Volvo wave. Volvo Trucks, Volvo Buses and Volvo
# Construction Equipment are separate businesses with a large Sketchfab
# presence, and the 110-row Volvo sweep contained 23 of them (21%) -- FH16 and
# FM tractor units, B9TL/B10M/B5TL double-deckers, a Marcopolo coach, an EC480
# excavator, an L220H wheel loader, an A40G articulated hauler.
#
# The existing gates do NOT catch these. `wave_render.class_gates` (WRONG_CLASS)
# has bus/coach/minibus/lorry/hgv/excavator/tractor, but NOT a bare "truck" --
# only "dump truck", "fire truck", "semi truck", "monster truck" -- so "Volvo
# Truck", "volvo vnl 2025" and "Volvo FH 460" all walked through it. Verified,
# not assumed: those three titles are in the post-gate manifest.
#
# Only unambiguous CLASS words go here, in the languages uploaders write in.
# Manufacturer model codes are marque-specific and must NOT be hardcoded --
# "FL" and "FE" are Volvo truck families but two-letter noise anywhere else --
# so they are passed per-wave via --drop-tokens instead.
COMMERCIAL_WORDS = [
    "truck", "trucks", "lorry", "lorries", "hgv", "tractor unit", "prime mover",
    "cabover", "sleeper cab", "semi trailer", "semitrailer", "artic",
    "bus", "buses", "autobus", "omnibus", "minibus", "coach", "double decker",
    "doubledecker", "decker",
    "excavator", "backhoe", "bulldozer", "dozer", "grader", "wheel loader",
    "loader", "hauler", "dumper", "compactor", "telehandler", "skid steer",
    "forklift", "crawler", "digger", "paver",
    # Uploaders title these in their own language far more often than cars:
    # "2009 Volvo FM Hormigonera" (Spanish, concrete mixer) is in this sweep.
    "camion", "camiao", "caminhao", "lastwagen", "lkw", "onibus", "autocar",
    "hormigonera", "betoniera", "gruszka", "gravsko",
    "concrete mixer", "cement mixer", "refuse", "garbage", "street sweeper",
]
# ARCHITECTURE. A marque whose name is also a famous BUILDING.
#
# Added 2026-08-11 for the Chrysler wave. The Chrysler Building is one of the
# most-modelled structures on Sketchfab and the bare-marque query is dominated
# by it: of the 166 unique downloadable results the Chrysler sweep returned,
# 13 (7.8%) were Art Deco architecture — ten Chrysler Buildings plus the
# MetLife Building and two 40 Wall Street towers that the search engine served
# alongside them.
#
# Nothing upstream stops these. `wave_render.class_gates` has no architecture
# term at all (BAD's nearest miss is "diorama|scene"); it rejected exactly 2 of
# the 13, both only because someone had typed "Minecraft" in the title. The
# face band caught 6 more as thin. THREE reached the candidate manifest —
# "Chrysler Building" at 246,187 and 75,149 faces and "Extractor elevator
# Chrysler building" at 198,160 — sitting comfortably inside the serving band
# and looking, to every gate before this one, exactly like a car.
#
# The nameplate requirement below does drop all three today, because no
# building title happens to carry a Chrysler nameplate. That is luck, not a
# gate: "Chrysler Building 300" or "Chrysler Building — Imperial spire detail"
# would walk straight through it. Testing architecture FIRST also makes the
# drop count honest instead of hiding a tenth of the sweep under "no-nameplate".
#
# Deliberately narrow — only words no car title contains. "tower" is safe
# (verified against 3,078 rows of 14 saved marque manifests: 0 hits), but
# "empire", "crown", "royal" and "palace" are all real car nameplates and are
# NOT here.
# "manhattan" and "rooftop" were in the first draft of this list and the
# regression run over those 3,078 rows threw them straight back out: Audi paints
# a car "Manhattan Grey" and a "Ford Bronco Raptor With Rooftop Tent" is a whole
# car. Both are gone. That is the two-directional test doing its job — a gate
# tested only against what it must catch is a gate that eats real cars.
BUILDING_WORDS = [
    "building", "skyscraper", "tower", "spire", "steeple",
    "architecture", "architectural", "facade", "skyline", "cityscape",
    "art deco", "artdeco", "elevator", "lobby", "staircase",
    "new york city", "nyc", "wall street", "downtown",
]
# Scale / print / sprite artefacts — geometry exists but is not a serving asset.
SCALE_WORDS = [
    "for 3d-printing", "for 3d printing", "3d-printing", "3d printing",
    "scale 1-", "scale 1:", "lowpoly sprite", "papercraft", "lego",
]


def norm(s):
    """Lowercase, strip diacritics, reduce punctuation to spaces.

    The diacritic fold is load-bearing, not cosmetic. Without it the Kia sweep's
    "KIA Río 2018 HB" normalised to "kia r o 2018 hb" — the accented i simply
    vanished as a non-[a-z] character — so it failed to match the nameplate "Rio"
    and a real car would have been dropped as junk. Uploaders write Citroën,
    Škoda, Río and Cee'd; a filter that only understands ASCII silently discards
    exactly the rows a native speaker of the marque uploaded."""
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def build(nameplates):
    """Nameplate tokens as whole-word regexes, longest first so 'Leon ST'
    is tried before 'Leon'.

    Build the pattern by escaping each word and joining with \\s+. The obvious
    one-liner — `re.escape(norm(n)).replace(" ", r"\\s+")` — is silently broken:
    `re.escape` turns the space into a backslash-space, so the replace leaves the
    backslash behind and yields `cee\\\\s+d`, a pattern matching a literal
    backslash. Every multi-word nameplate then matches nothing at all. That cost
    a real car here ("Morris Mini" in the MINI sweep) and is the same failure as
    the `\\b`-inside-a-raw-string gate recorded in CLAUDE.md: a filter nobody
    tested against a case it must catch is a filter that does not exist."""
    HYPHEN_NOTE = """
    Hyphenated nameplates match BOTH spellings. norm() reduces punctuation to a
    space, so "CR-V" becomes `cr v` while an uploader who wrote "CRV" becomes
    `crv` -- the two can never match, and the car is silently dropped as
    no-nameplate. Measured on the Honda sweep 2026-08-09: this lost 12 genuine
    cars (6 CR-X, 4 CRV, 2 HRV), one of them a 1,047,310-face 1988 CR-X. It is
    not Honda-specific -- verified the same day that it also breaks Toyota C-HR
    vs CHR and Peugeot e-208 vs e208. So each multi-token nameplate gets an
    OPTIONAL separator between its parts: \s* rather than \s+.
    """
    pats = []
    for n in sorted({n.strip() for n in nameplates if n.strip()},
                    key=len, reverse=True):
        words = norm(n).split()
        if not words:
            continue
        # \s* (not \s+) so "cr v" also matches "crv" -- see HYPHEN_NOTE.
        body = r"\s*".join(re.escape(w) for w in words)
        pats.append((n, re.compile(r"\b" + body + r"\b")))
    return pats


def classify(title, pats, drop_tokens=()):
    t = norm(title)
    # COMMERCIAL FIRST, and deliberately BEFORE the nameplate test, for two
    # reasons. (1) It makes the drop count honest: a truck that carries no car
    # nameplate would otherwise be filed under "no-nameplate", hiding how much
    # of the sweep was commercial. (2) More importantly, truck and bus model
    # designations COLLIDE with Volvo's numeric car nameplates -- a "Volvo VNL
    # 760" tractor unit matches the 760 saloon, and a "Volvo FL 240" matches the
    # 240. Testing commercial first is what stops that pairing from shipping.
    for w in list(COMMERCIAL_WORDS) + list(drop_tokens):
        if re.search(r"\b" + re.escape(norm(w)).replace(r"\ ", r"\s*") + r"\b", t):
            return "commercial-vehicle", None
    # ARCHITECTURE, also before the nameplate test — see BUILDING_WORDS.
    for w in BUILDING_WORDS:
        if re.search(r"\b" + re.escape(norm(w)).replace(r"\ ", r"\s*") + r"\b", t):
            return "architecture", None
    hit = next((n for n, p in pats if p.search(t)), None)
    if not hit:
        return "no-nameplate", None
    for w in SCALE_WORDS:
        if norm(w) in t:
            return "scale-artefact", hit
    for w in PART_WORDS:
        if re.search(r"\b" + re.escape(norm(w)) + r"\b", t):
            return "component", hit
    return "keep", hit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--nameplates", required=True,
                    help="marque-SPECIFIC nameplates only — see the module docstring")
    ap.add_argument("--drop-tokens", default="",
                    help="comma-separated MARQUE-SPECIFIC tokens to drop as "
                         "commercial vehicles, e.g. Volvo's truck/bus/plant model "
                         "families 'FH,FM,FMX,VNL,B9TL,EC480'. Kept out of the "
                         "shared COMMERCIAL_WORDS list on purpose: two-letter "
                         "model codes are meaningful for one marque and noise for "
                         "every other. Matched as whole tokens, before the "
                         "nameplate test, so a 'Volvo VNL 760' cannot claim the "
                         "760 saloon nameplate.")
    ap.add_argument("--allow-uid", default="",
                    help="comma-separated uids to force through regardless of title; "
                         "for ambiguous rows a render settles faster than a guess")
    ap.add_argument("--rejects", default="pipeline/ingest/REJECTS.json",
                    help="ledger of uids the owner already scrapped on review; they are "
                         "dropped silently. A sweep re-run re-finds every rejected car, "
                         "so without this the same junk is re-rendered and re-reviewed "
                         "every wave. Pass an empty string to disable.")
    ap.add_argument("--report", action="store_true",
                    help="print every row and why it was dropped")
    a = ap.parse_args()

    rows = json.load(open(a.src))
    pats = build(a.nameplates.split(","))
    allow = {u.strip() for u in a.allow_uid.split(",") if u.strip()}
    drop_tokens = [t.strip() for t in a.drop_tokens.split(",") if t.strip()]

    rejected = set()
    if a.rejects:
        try:
            rejected = set(json.load(open(a.rejects))["rejects"])
        except FileNotFoundError:
            pass

    kept, dropped, seen, forced = [], {}, set(), 0
    for r in rows:
        if r.get("uid") in rejected:
            dropped.setdefault("already-scrapped", []).append(r.get("name", ""))
            continue
        verdict, plate = classify(r.get("name", ""), pats, drop_tokens)
        if r.get("uid") in allow and verdict != "keep":
            verdict, plate, forced = "keep", "(forced)", forced + 1
        if verdict != "keep":
            dropped.setdefault(verdict, []).append(r.get("name", ""))
            continue
        # The same car is often uploaded twice. uid already deduped upstream.
        #
        # Keyed on title AND face count until 2026-08-08, which missed six pairs
        # in 67 audited Toyotas -- "Toyota GT86 3D Model (Free)" and "Toyota gt86
        # lowprice" are the same 1,152,416-face mesh under two titles, and a
        # re-upload almost always gets retitled. Face count alone is the real
        # identity: an exact match at six or seven digits is the same mesh, not a
        # coincidence. Guarded at 50k so genuinely simple meshes, where collisions
        # are plausible, still fall back to needing the title too.
        f = r.get("faces") or 0
        sig = f if f >= 50_000 else (norm(r.get("name")), f)
        if sig in seen:
            dropped.setdefault("duplicate-mesh", []).append(r.get("name", ""))
            continue
        seen.add(sig)
        r["plate"] = plate
        kept.append(r)

    json.dump(kept, open(a.out, "w"), indent=1)

    print(f"in  {len(rows)}")
    for k in sorted(dropped, key=lambda k: -len(dropped[k])):
        print(f"  dropped {k:<16} {len(dropped[k])}")
        if a.report:
            for n in dropped[k]:
                print(f"      {n[:78]}")
    if forced:
        print(f"  forced through   {forced}  (--allow-uid; rendered for the eye to settle)")
    missing = allow - {r.get("uid") for r in kept}
    if missing:
        print(f"  WARNING: {len(missing)} --allow-uid not present in the input: "
              f"{sorted(missing)[:4]}", file=sys.stderr)
    print(f"out {len(kept)}  -> {a.out}")
    if rows and len(kept) / len(rows) < 0.2:
        print("\nNOTE: under 20% survived. That is the homonym signature -- the bare\n"
              "marque query dominated the sweep. Worth checking the kept list by eye\n"
              "before spending GPU on it.", file=sys.stderr)


if __name__ == "__main__":
    main()
