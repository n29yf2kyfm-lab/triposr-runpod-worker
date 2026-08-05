"""Premium gate for a sourcing wave: pass, salvage, or scrap -- with the reason.

The owner's bar, in his words: proportions read as the right car instantly, a
strong front three-quarter, roof/pillars/wheelbase consistent across all four
views, clean reflections, premium paint. Fails on soft grille edges, headlights
without sharp internal LED elements, wheel spokes inconsistent between views, a
soft rear bumper, and undefined shut lines.

Most of that only a human eye settles, and this tool does not pretend otherwise.
What it does is remove the cars that CANNOT clear the bar, so attention is spent
on the ones that might. Each gate below is something measured, not guessed, and
every threshold traces to a car the owner personally called.

  G1 SHELL          coverage >= 0.89
                    One material spans the whole car: windows are solid body
                    colour, there are no lamp lenses, the grille is flat. Such a
                    model fails "headlights lacking sharp internal LED elements"
                    and "shut lines not defined" by construction. Validated 12/12
                    against the owner's own calls -- Crafter 1.000, Tiguan
                    Allspace 1.000, Passat B8 Variant 0.940, ID.7 0.898 and Golf
                    VIII 0.894 were all called half-baked; Golf GTI 2014 at 0.095
                    and Golf R Variant at 0.171 were kept. Nothing in that sample
                    lands between 0.20 and 0.89.
                    NOT SALVAGEABLE: a tint-mode recolour was tried on the Tiguan
                    Allspace and turned the glass, wheels and trim red too.

  G2 NO BODY        bodyMaterials == 0
                    The worker found nothing it could paint, so DVLA colour can
                    never be applied. NOT SALVAGEABLE.

  G3 JUNK TAG       source metadata says scan / lidar / photogrammetry / wreck /
                    rusty / damaged / destroyed / burnt / abandoned / toy /
                    lowpoly / cartoon / stylised.
                    These describe the asset itself, not its provenance, and each
                    one names a defect the rubric rejects. NOT SALVAGEABLE.
                    Sim-mod provenance (gta, forza, assetto, beamng, freedownload)
                    is deliberately NOT in this list -- the owner ruled those are
                    warnings, not culls, because a sim conversion is often the
                    most accurate geometry on the site.

  G4 THIN           faces < 100,000
                    The harvest band opens at 60,000, which is fine for a shape
                    but thin for four views at 1000px where grille honeycomb and
                    shut lines are judged. This is an EYE judgement, not a proof,
                    so it only flags -- it never scrapps. The 100k line is a rule
                    of thumb, and the owner kept a 98,695-face Golf GTI Mk7 that
                    an earlier draft of this gate would have binned on a 1.3%
                    margin. Aesthetic thresholds do not get to overrule a person.

  G5 SPLIT SUSPECT  0.45 < coverage < 0.89, or bodyMaterials > 2
                    Body paint bleeds into trim or glass. The car may be
                    excellent otherwise. SALVAGEABLE -- a material split or a
                    tint recolour can rescue it -- so this is flagged, never
                    auto-scrapped.

  G6 PASS           1 <= bodyMaterials <= 2 and 0.05 <= coverage <= 0.45
                    Real separation: paint lands on the body alone. Goes to the
                    owner for the eye test, which remains the only thing that
                    decides premium.

The gates below were added after the Audi wave. G1-G6 measure whether a car CAN
be painted; they say nothing about whether it is the right car, and 9 of the
first 11 Audi candidates cleared G6 and were still scrapped by eye. Each gate
here is traceable to specific cars in that set and is tested in
`tests/test_premium_audit.py` against the ones it must catch AND the ones it
must not touch.

  G7 NOT ROAD LEGAL motorsport vocabulary in the title: dtm, gt3/gt4/gte, lms,
                    lmp, wrc, rally, race/racing, drift, formula, nascar, plus
                    liveried service vehicles (police, taxi, ambulance).
                    A silhouette racer is not the car a UK registration decodes
                    to, however good the mesh is. Catches the A4 DTM R14, RS5
                    DTM, TT-R DTM, R8 LMS GT4, Quattro Rally, LMS Evo II GT3 --
                    7 of 129 in the Audi wave. NOT SALVAGEABLE.

  G8 WRONG MARKET   `A3 L`, `A4 L40 tfsi` and the like -- China-market
                    long-wheelbase saloons. Visibly longer than the UK car, so a
                    UK lookup would return the wrong shape. Catches exactly the
                    two the owner's rubric rejected by eye (U005, U010). NOT
                    SALVAGEABLE.

  G9 NEAR DUPLICATE same author, same nameplate, face counts within 2%.
                    One uploader put the same current A3 8Y on the site five
                    times; four cleared every material gate and three were
                    scrapped by hand as copies of the first. The largest member
                    survives and the rest are scrapped naming it.
                    LIMIT, stated plainly: "largest wins" is a heuristic, not a
                    quality judgement. It happened to pick right here (the 539k
                    A3 was the keeper, and the 536k copy had a torn shut line),
                    but a bigger mesh is not automatically a better car. The
                    survivor still faces the eye.

  G10 THIN PAINT    coverage < 0.10. FLAG ONLY -- never scraps.
                    The A4 B6 at 0.081 turned out to be a patchwork of
                    mismatched baked textures that no respray could reach. This
                    is ONE observation, which is not enough to cull on, so it
                    only asks for a closer look. 5 of 129 in the Audi wave.

  G11 RE-UPLOAD     same nameplate, faces within 1.5%, AND coverage equal to
                    three decimals -- regardless of author.
                    G9 keys on author deliberately, so it is blind to the same
                    file posted by two different people, which turns out to be
                    common: the 2021 RS5 Sportback appears at 523,832 and
                    517,930 faces under two names whose four renders are
                    pixel-for-pixel identical. Coverage is a measured property
                    of the mesh; two independent models matching to 3dp AND
                    sitting within 1.5% on face count is not chance. Found 5
                    pairs in the Audi wave, picked the larger every time, and
                    touched none of the 16 cars kept by eye.

  G12 TUNER         aftermarket conversions: LB Works, Liberty Walk, ABT,
                    Mansory, Brabus, Rocket Bunny, widebody, body kit, Prior
                    Design, Hamann, stance, slammed, bagged.
                    The owner already quarantined audi-rs6-v3 for being an ABT
                    RS6-R; this wave then offered the SAME car again, plus an
                    LB Works RS5 and a Liberty Walk RS5. "low"/"lowered" are
                    deliberately NOT in the list -- too easy to hit an innocent
                    title. 4 of 129. NOT SALVAGEABLE.

NOT COVERED, and worth stating so nobody reads a PASS as more than it is:
  - an asset that renders upside down (the A4 Avant ships rolled 180 degrees)
  - a body built from mismatched baked textures, or two-tone with the second
    tone outside the paint material, which survives every colour
  - missing, detached or exploded geometry -- four cars in this wave had no
    wheels, floating wheels, or every panel separated in space
  - a body that renders as a featureless black silhouette
All are geometry or material-value defects invisible in the metadata this tool
reads, and every one was caught only by looking at the render.

Nothing here is deleted. Everything is marked, with its gate and reason, and the
GLB and sheet stay in the bucket.

Usage:
    premium_audit.py [--sheets audit/vwfull] [--apply]
"""
import argparse, json, os, re, sys, time, urllib.request

ENV_FILE = "/root/.alam3d_env"


def load_env(path=ENV_FILE):
    try:
        body = open(path).read()
    except OSError:
        return
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line[7:].lstrip() if line.startswith("export ") else line
        n, sep, v = line.partition("=")
        if sep and not os.environ.get(n.strip()):
            os.environ[n.strip()] = v.strip().strip("'\"")


load_env()

SB = "https://tfkvthprsntexrcuqpyd.supabase.co"
BUCKET = "car-meshes"

SHELL_COV = 0.89
MIN_FACES = 100_000
CLEAN_LO, CLEAN_HI = 0.05, 0.45

JUNK = re.compile(r"(?i)\b(scan|photogrammetry|lidar|wreck|wrecked|crash|crashed|"
                  r"destroyed|damaged|burnt|burned|rusty|rusted|abandoned|derelict|"
                  r"junk|toy|lowpoly|low.?poly|cartoon|stylized|stylised|voxel|"
                  r"papercraft|dealership|showroom|vertriebstelle|vetriebstelle)\b")

# G7: not the car a UK registration decodes to. "lms"/"lmp"/"gte" are whole
# words only -- "lms" must not fire inside a longer token.
RACE = re.compile(r"(?i)\b(dtm|gt3|gt4|gte|lms|lmp\d?|wrc|rally|rallye|race|racecar|"
                  r"racing|drift|formula|nascar|safety.?car|police|polizei|taxi|"
                  r"ambulance)\b")

# G8: China-market long-wheelbase. Two shapes seen in the wild -- "a3 L 35 tfsi"
# (L as its own word) and "a4 L40 tfsi" (L glued to the power figure). Anchored
# on a model code so a stray "L" elsewhere in a title cannot trigger it.
LWB = re.compile(r"(?i)\b[aq]\d\s*l\b|\b[aq]\d\s*l\d{2}\b|\bl\d{2}\s*tfsi\b")

DUP_FACE_TOL = 0.02      # G9: same author, face counts within 2% of the largest
XDUP_FACE_TOL = 0.015    # G11: any author -- tighter, and coverage must match too
THIN_PAINT = 0.10        # G10 flag only

# G12: aftermarket conversions. The body is not the car a UK registration
# decodes to, and the owner already quarantined audi-rs6-v3 on exactly this.
# "low"/"lowered" are deliberately absent -- too easy to hit an innocent title.
TUNER = re.compile(r"(?i)\b(lb.?works|liberty.?walk|abt|mansory|brabus|rocket.?bunny|"
                   r"widebody|wide.?body|body.?kit|bodykit|prior.?design|hamann|"
                   r"stance|slammed|bagged)\b")


def nameplate(name):
    """The model token a duplicate cluster is keyed on: a3, q7, r8, 3series, x5.

    Without this, two different cars by one prolific author (an A3 and a Q5 that
    happen to land within 2% on face count) would cluster as duplicates of each
    other and one would be scrapped for no reason.

    The pattern was Audi-only when it was written, which made G9 and G11 silently
    blind to every other marque: on 902 BMW candidates it matched nothing and
    found zero duplicates, not because there were none but because "3 Series"
    and "X5" are not Audi model codes. Patterns are ordered longest-first so
    "3 series" wins over the bare "s3"-shaped fallback, and each marque's
    additions are listed separately so the next wave can extend it without
    disturbing the ones already validated.
    """
    n = re.sub(r"[_.]+", " ", (name or "").lower())
    for pat in (
        # BMW -- series numbers, X/Z/i ranges, M cars
        r"\b(\d)\s*series\b", r"\b([xz]\d)\b", r"\b(i[x3-8])\b", r"\b(m\d)\b",
        r"\b(xm)\b",
        # Audi
        r"\b(rs\s?\d|sq\d|s\d|[aq]\d|r8|tt|e.?tron)\b",
        # BMW engine codes (520i, 116d, 740Li) -- LAST on purpose. It is the
        # loosest pattern here and would otherwise eat a trailing power figure
        # in another marque's title ("Audi A6 3.0 TDI 245" -> "2series"), so
        # every named model code gets to match before it does. The optional
        # leading m catches M340i/M550i, whose digits carry no word boundary.
        r"\bm?([1-8])\d{2}[a-z]{0,2}\b",
    ):
        m = re.search(pat, n)
        if m:
            g = m.group(1)
            return (g + "series") if "series" in pat or pat.endswith(r"[a-z]{0,2}\b") \
                else re.sub(r"[\s-]", "", g)
    return ""


def duplicate_clusters(rows):
    """-> {uid: (survivor_uid, survivor_faces)} for every row that is a copy.

    Same author + same nameplate + face count within DUP_FACE_TOL of the
    largest in the group. The largest survives; see the G9 limit in the module
    docstring -- this is a heuristic, not a verdict on which car is better.
    """
    groups = {}
    for r in rows:
        key = ((r.get("author") or "").strip().lower(), nameplate(r.get("name")))
        if key[0] and key[1]:
            groups.setdefault(key, []).append(r)
    out = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        members = sorted(members, key=lambda r: -(r.get("faces") or 0))
        top = members[0]
        tf = top.get("faces") or 0
        for r in members[1:]:
            f = r.get("faces") or 0
            if tf and abs(tf - f) / tf <= DUP_FACE_TOL:
                out[r["uid"]] = (top["uid"], tf)
    return out


def cross_author_clusters(rows):
    """G11: the same file re-uploaded by a DIFFERENT person.

    G9 keys on author on purpose -- two people modelling the same car
    independently is normal and both deserve a look. But two people posting the
    same file is not modelling, and it happens constantly: this wave has the
    RS5 Sportback at 523,832 and 517,930 faces under different names whose four
    renders are pixel-for-pixel identical, plus the same story for a Q3
    Sportback, an R8 and an A3.

    The signature is deliberately tighter than G9's: same nameplate, face
    counts within 1.5%, AND coverage equal to three decimals. Coverage is a
    measured property of the mesh, so two genuinely independent models of the
    same car landing on the same value to 3dp while also sitting within 1.5% on
    face count is not something that happens by chance. Measured on the Audi
    wave it found 5 pairs, picked the larger member every time, and touched
    none of the 16 cars kept by eye.
    """
    groups = {}
    for r in rows:
        cov = r.get("coverage")
        np_ = nameplate(r.get("name"))
        if np_ and cov is not None:
            groups.setdefault((np_, round(cov, 3)), []).append(r)
    out = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        members = sorted(members, key=lambda r: -(r.get("faces") or 0))
        top = members[0]
        tf = top.get("faces") or 0
        for r in members[1:]:
            f = r.get("faces") or 0
            if tf and abs(tf - f) / tf <= XDUP_FACE_TOL:
                out[r["uid"]] = (top["uid"], tf)
    return out


def sbk():
    k = os.environ.get("SB_KEY")
    if not k:
        sys.exit("FATAL: SB_KEY not set")
    return k


def sb_get(p):
    return urllib.request.urlopen(urllib.request.Request(
        f"{SB}/storage/v1/object/{p}",
        headers={"apikey": sbk(), "Authorization": f"Bearer {sbk()}"}), timeout=300).read()


def sb_put(p, blob, ctype="application/json"):
    return urllib.request.urlopen(urllib.request.Request(
        f"{SB}/storage/v1/object/{p}", data=blob, method="POST",
        headers={"apikey": sbk(), "Authorization": f"Bearer {sbk()}",
                 "Content-Type": ctype, "x-upsert": "true"}), timeout=600).status


def searchable(*vals):
    """Title text with separators normalised to spaces before any \\b match.

    Underscores are word characters, so `\\bABT\\b` does NOT match inside
    "2020_ABT_ Sportline_ Audi_RS6-R" -- and that is a real title from the Audi
    wave, an ABT conversion the tuner gate walked straight past. Sketchfab
    titles arrive with underscores, dots and stars scattered through them
    ("LB*WORKS", "audi_a4_avant_2013_fbx"), so every gate matches against this
    rather than the raw string.
    """
    return re.sub(r"[_.*+/|\\-]+", " ", " ".join(str(v or "") for v in vals))


def judge(r, dups=None, xdups=None):
    """-> (gate, verdict, reason). verdict in PASS | SALVAGE | SCRAP | UNKNOWN.

    `dups`/`xdups` are duplicate_clusters(rows)/cross_author_clusters(rows) when
    judging a whole wave; omitted when judging one row, in which case G9 and G11
    simply cannot fire.
    """
    text = searchable(r.get("name"), r.get("class_warn"))
    cov = r.get("coverage")
    mats = r.get("bodyMaterials")
    faces = r.get("faces") or 0

    hit = JUNK.search(text)
    if hit:
        return "G3", "SCRAP", f"source describes a defect: '{hit.group(0)}'"

    # wrong car entirely -- checked before any material gate, because a material
    # split says nothing about whether this is the vehicle a UK reg decodes to
    hit = RACE.search(text)
    if hit:
        return "G7", "SCRAP", (f"'{hit.group(0)}' - motorsport or service vehicle, "
                               f"not the road car a UK registration decodes to")
    hit = LWB.search(text)
    if hit:
        return "G8", "SCRAP", (f"'{hit.group(0).strip()}' - China-market long-wheelbase, "
                               f"visibly longer than the UK car of the same name")
    hit = TUNER.search(text)
    if hit:
        return "G12", "SCRAP", (f"'{hit.group(0)}' - aftermarket conversion, not the "
                                f"factory car a UK registration decodes to")
    if dups and r.get("uid") in dups:
        keep, kf = dups[r["uid"]]
        return "G9", "SCRAP", (f"near-duplicate of {keep} ({kf:,} f) by the same author "
                               f"at {faces:,} f - within {DUP_FACE_TOL:.0%}")
    if xdups and r.get("uid") in xdups:
        keep, kf = xdups[r["uid"]]
        return "G11", "SCRAP", (f"same file as {keep} ({kf:,} f) re-uploaded by a different "
                                f"author at {faces:,} f - identical coverage {cov}")

    if cov is None or mats is None:
        return "G0", "UNKNOWN", "no material verdict captured"
    if mats == 0:
        return "G2", "SCRAP", "no body material - DVLA colour can never be applied"
    if cov >= SHELL_COV:
        return "G1", "SCRAP", (f"coverage {cov:.3f} - one material spans the car; no separate "
                               f"glass or lamp lenses; tint recolour proven to flood them")
    if mats <= 2 and CLEAN_LO <= cov <= CLEAN_HI:
        if cov < THIN_PAINT:
            return "G10", "SALVAGE", (f"clean split but coverage only {cov:.3f} - the one car "
                                      f"seen this thin was a patchwork of baked textures; look closer")
        return "G6", "PASS", f"clean split - {mats} body material(s), coverage {cov:.3f}"
    if faces and faces < MIN_FACES:
        return "G4", "SALVAGE", f"only {faces:,} faces - thin for four-view scrutiny, needs an eye"
    return "G5", "SALVAGE", (f"{mats} body material(s), coverage {cov:.3f} - paint would bleed "
                             f"into trim/glass; fixable by a material split")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheets", default="audit/vwfull")
    ap.add_argument("--apply", action="store_true",
                    help="write SCRAP verdicts back as quarantined (reversible)")
    a = ap.parse_args()

    mpath = f"{BUCKET}/{a.sheets}/_manifest.json"
    rows = json.loads(sb_get(mpath))
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    dups = duplicate_clusters(rows)
    xdups = cross_author_clusters(rows)
    tally, examples = {}, {}
    for r in rows:
        if r.get("publicationStatus") == "quarantined" and r.get("quarantineReason"):
            tally["already-scrapped"] = tally.get("already-scrapped", 0) + 1
            continue
        gate, verdict, reason = judge(r, dups, xdups)
        r["auditGate"] = gate
        r["auditVerdict"] = verdict
        r["auditReason"] = reason
        r["auditedAt"] = now
        key = f"{gate} {verdict}"
        tally[key] = tally.get(key, 0) + 1
        examples.setdefault(key, []).append(r.get("name", "")[:46])
        if a.apply and verdict == "SCRAP":
            r["publicationStatus"] = "quarantined"
            r["quarantineReason"] = f"premium audit {gate}: {reason}"
            r["quarantinedAt"] = now

    print("PREMIUM AUDIT — %s\n%s" % (a.sheets, "=" * 66))
    for k in sorted(tally, key=lambda x: -tally[x]):
        print("  %-18s %4d" % (k, tally[k]))
        for e in examples.get(k, [])[:3]:
            print("        e.g. %s" % e)
    if a.apply:
        sb_put(mpath, json.dumps(rows, indent=1).encode())
        for name, sel in (("_scrapped", "quarantined"),):
            sb_put(f"{BUCKET}/{a.sheets}/{name}.json",
                   json.dumps([x for x in rows if x.get("publicationStatus") == sel],
                              indent=1).encode())
        for name, v in (("_pass", "PASS"), ("_salvage", "SALVAGE")):
            sb_put(f"{BUCKET}/{a.sheets}/{name}.json",
                   json.dumps([x for x in rows if x.get("auditVerdict") == v
                               and x.get("publicationStatus") != "quarantined"],
                              indent=1).encode())
        print("\napplied and uploaded")
    else:
        print("\nDRY RUN — pass --apply to write it back")


if __name__ == "__main__":
    main()
