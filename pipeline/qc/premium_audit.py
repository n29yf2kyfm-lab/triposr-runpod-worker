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


def judge(r):
    """-> (gate, verdict, reason). verdict in PASS | SALVAGE | SCRAP | UNKNOWN."""
    text = " ".join(str(r.get(k) or "") for k in ("name", "class_warn"))
    cov = r.get("coverage")
    mats = r.get("bodyMaterials")
    faces = r.get("faces") or 0

    hit = JUNK.search(text)
    if hit:
        return "G3", "SCRAP", f"source describes a defect: '{hit.group(0)}'"

    if cov is None or mats is None:
        return "G0", "UNKNOWN", "no material verdict captured"
    if mats == 0:
        return "G2", "SCRAP", "no body material - DVLA colour can never be applied"
    if cov >= SHELL_COV:
        return "G1", "SCRAP", (f"coverage {cov:.3f} - one material spans the car; no separate "
                               f"glass or lamp lenses; tint recolour proven to flood them")
    if mats <= 2 and CLEAN_LO <= cov <= CLEAN_HI:
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

    tally, examples = {}, {}
    for r in rows:
        if r.get("publicationStatus") == "quarantined" and r.get("quarantineReason"):
            tally["already-scrapped"] = tally.get("already-scrapped", 0) + 1
            continue
        gate, verdict, reason = judge(r)
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
