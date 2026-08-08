#!/usr/bin/env python3
"""publish_audit.py — the gate between an eye-reviewed wave and publish_batch.

An eye review answers one question: is this a good model of a car? It does not
answer whether the SET is publishable, and four separate reviews cannot see each
other at all. This checks the things that only show up when the keeps are looked
at together, and against what is already live:

  * **Duplicate meshes.** The same GLB gets uploaded by several people. Two
    identical entries score identically in the resolver and one wins arbitrarily.
    Face count alone is not enough to detect this -- a Kia Rio and a Kia K8 came
    within 1% of each other -- so pairs are confirmed on the rendered sheets and
    recorded here explicitly.
  * **Not a car.** A wave keeps whatever survived triage. A 1960s LIAZ tipper
    lorry and a works rally car both reached the Skoda keep list.
  * **Photogrammetry scans.** Ground baked into the mesh, lighting baked into the
    texture, body share 1.000. They pass "is it the right car" and fail the bar.
  * **Not UK-market.** A car never sold here cannot be reached by a DVLA decode,
    so it is dead weight in a registration-lookup library however good it is.
  * **Collision with a live entry.** Same make, same model, overlapping years and
    the same body style means the new car competes with one already serving.

Nothing here is destructive: it prints a recommendation per car. The owner's
verdicts are untouched.
"""
import json, os, sys, urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAT = ("https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/public/"
       "car-renders/catalogue.v2.json")

# Same car, two uploads. Every pair confirmed on the four-view sheets.
DUPLICATE = [
    (["skoda#4", "skoda#5"],   "Octavia Combi 2009 — renders pixel-identical"),
    (["skoda#7", "skoda#8"],   "Octavia RS 2014 — pixel-identical, 12 faces apart"),
    (["skoda#11", "skoda#12"], "Octavia 2005 — pixel-identical"),
    (["skoda#37", "skoda#38"], "Kamiq — identical 364,722 f, only base colour differs"),
    (["skoda#26", "skoda#27"], "Kamiq GT — #27 is #26 decimated to half the faces"),
    (["skoda#21", "skoda#32"], "Rapid Spaceback 2020 — same SAIC car, two uploaders"),
    (["seat#7", "seat#8"],     "Leon 5F five-door — same mesh, same uploader"),
    (["kia#20", "kia#21"],     "Sportage NQ5 — identical 374,469 f, only base colour differs"),
]

NOT_A_CAR = {
    "skoda#30": "LIAZ 706 MTS — a 1960s Czech tipper lorry",
    "skoda#44": "Fabia RS WRC — works rally car in full sponsor livery, not a road Fabia",
}

SCAN = {
    "skoda#54": "photogrammetry scan of an Octavia Sedan — the Wagon capture at #53 was scrapped",
    "seat#39":  "photogrammetry scan of an Ateca — the Arona scan at #29 was scrapped",
    "mini#48":  "photogrammetry scan — tarmac baked into the mesh, glass missing entirely",
}

NOT_UK = {
    "kia#36":   "K8 — sold in Korea and the US, never here",
    "kia#64":   "K5 2025 — replaced the Optima outside Europe, never sold here",
    "skoda#26": "Kamiq GT — SAIC China only",
    "skoda#27": "Kamiq GT — SAIC China only",
    "skoda#21": "Rapid Spaceback 2020 — SAIC China; the UK car ended in 2019 on the older face",
    "skoda#32": "Rapid Spaceback 2020 — SAIC China",
    "skoda#29": "Rapid saloon 2020 — SAIC China",
    "skoda#34": "Kodiaq 2020 — carries the SAIC China dealer decal",
}

DEFECT = {
    "kia#18":   "no wheels at all — every arch is an empty void in all four views",
    "kia#14":   "grey untextured patches across front wing, rear quarter and sills in every view",
    "mini#24":  "wheel arch extensions render as a mottled grey camouflage patch",
    "seat#4":   "modified — aftermarket orange wheels a recolour cannot touch; headlights have no internals",
    "kia#6":    "wheels are near-featureless discs with no spoke definition",
    "kia#7":    "wheels are flat black discs with no spoke definition; 82k faces",
    "skoda#18": "headlights are blank pale voids, rear cluster is a flat magenta blob",
    "skoda#19": "headlights and tail lights featureless, no shut lines, 93k faces",
    "skoda#25": "headlight and tail-light units are blank body panels; faceted surfacing",
    # Mis-keyed as skoda#22 in the first run of this audit, which is a scrapped
    # Octavia scene. The finding is the SEAT Alhambra 7M and it reached the clean
    # list because of it. Keys here are marque-scoped for exactly this reason.
    "seat#22":  "tail clusters are flat red rectangles with no internal structure; "
                "rear plate recess is a bare grey slab",
    "skoda#37": "slammed to the floor with the wheels tucked into the arches",
    "skoda#38": "same slammed mesh as #37",
}

# Collisions are COMPUTED against the live catalogue, not listed by hand. The
# hand-written table this replaced was built marque by marque from the live
# listing and silently omitted MINI entirely, so seven MINI keeps reached the
# clean list while the library already served a Clubman, two Countrymen, a
# Convertible, a Cooper S Convertible and a Hatch covering the same years. A
# table you maintain by eye is a table that goes stale the moment a wave lands.
def collisions(plan, live):
    """Live entries the planned entry would compete with.

    Competing means: same make, a shared model token, overlapping year ranges,
    and a body style that either matches or is blank on one side. A blank counts
    because the resolver only hard-rejects on a body-style *conflict* — blank
    versus set is not a conflict, so both entries stay in the running and score
    against each other.

    Open-ended ranges are treated as open. Most live entries carry a yearStart
    and no yearEnd, so they extend to the present and overlap almost anything
    later; that is real, not an artefact.
    """
    out = []
    for x in live:
        if x.get("make") != plan["make"]:
            continue
        if not (_toks(x.get("model")) & _toks(plan["model"])):
            continue
        if not _overlap(plan.get("year_start"), plan.get("year_end"),
                        x.get("yearStart"), x.get("yearEnd")):
            continue
        xb = (x.get("bodyStyle") or "").lower()
        pb = (plan.get("body_style") or "").lower()
        if xb and pb and xb != pb:
            continue                      # genuine conflict: resolver rejects, no contest
        out.append((x["assetId"], x.get("model"), x.get("yearStart"),
                    x.get("yearEnd"), xb or "-"))
    return out


def _toks(s):
    import re as _re
    return set(_re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).split())


def _overlap(a1, a2, b1, b2):
    """True when two year ranges genuinely compete.

    A single shared year is NOT a collision. Consecutive generations meet at the
    changeover year by definition -- a Toledo 1999-2004 and a Toledo 2004-2009
    touch at 2004 and are still two different cars -- and counting that as a
    clash flagged almost every legitimate pair in the batch. Two or more shared
    years means they really are covering the same period.
    """
    a1, a2 = a1 or 1900, a2 or 2100
    b1, b2 = b1 or 1900, b2 or 2100
    return min(a2, b2) - max(a1, b1) >= 1




PLAN_FILE = os.path.join(REPO, "pipeline", "publish", "WAVE_PLAN.json")

# Nameplates per marque, longest first so "leon st" beats "leon". Used only to
# read a model out of the SOURCE TITLE -- never to assert anything the title does
# not say (accuracy rule).
NAMEPLATES = {
 "skoda": ["octavia", "superb", "fabia", "kamiq", "karoq", "kodiaq", "enyaq",
           "scala", "rapid", "roomster", "citigo", "yeti", "felicia", "favorit"],
 "seat":  ["alhambra", "formentor", "tarraco", "toledo", "cordoba", "marbella",
           "arona", "ateca", "ibiza", "altea", "exeo", "leon", "arosa", "inca",
           "mii", "cupra"],
 "mini":  ["countryman", "clubman", "paceman", "aceman", "cooper", "moke", "mini"],
 "kia":   ["sportage", "sorento", "picanto", "carnival", "stinger", "stonic",
           "venga", "carens", "optima", "cee d", "ceed", "niro", "soul", "rio",
           "k5", "k8", "ev6", "ev9", "ev3"],
}
BODY = [("combi", "estate"), ("wagon", "estate"), (" sw", "estate"),
        ("estate", "estate"), (" st ", "estate"), ("cabrio", "convertible"),
        ("convertible", "convertible"), ("roadster", "convertible"),
        ("coupe", "coupe"), ("sedan", "saloon"), ("saloon", "saloon"),
        ("hatchback", "hatchback"), ("spaceback", "hatchback")]


def plan_from_title(k):
    """Model, years and body read off the source title and nothing else."""
    import re as _re
    t = " " + (k["name"] or "").lower() + " "
    model = next((n for n in NAMEPLATES.get(k["marque"], [])
                  if _re.search(r"\b" + _re.escape(n) + r"\b", t)), "")
    yrs = [int(y) for y in _re.findall(r"\b(19[5-9]\d|20[0-4]\d)\b", t)]
    ys = min(yrs) if yrs else None
    ye = max(yrs) if len(yrs) > 1 else None
    body = next((b for kw, b in BODY if kw in t), "")
    return {"make": k["marque"], "model": model, "year_start": ys,
            "year_end": ye, "body_style": body, "trim": ""}


def recolour(k):
    c, m = k["cov"], k["mats"]
    if m == 0 or c == 0:  return "none",  "no material classed as body"
    if c >= 0.95:         return "none",  f"body share {c:.0%} — whole mesh is one material"
    if c > 0.45:          return "spill", f"body share {c:.0%}, above the 45% ceiling"
    if c < 0.05:          return "none",  f"body share {c:.0%}, below the 5% floor"
    return "ok", ""


def load():
    keeps = {}
    for m in ("skoda", "seat", "mini", "kia"):
        tri = json.load(open(f"{REPO}/pipeline/ingest/{m}_triage.json"))
        ver = json.load(open(f"{REPO}/pipeline/qc/{m}_percar_verdicts.json"))
        for i, r in enumerate(tri, 1):
            v = ver.get(r["uid"])
            if v and v[0] == "KEEP":
                keeps[f"{m}#{i}"] = {**r, "marque": m, "n": i}
    return keeps


def audit(keeps, coll=None):
    """Each car gets a verdict and the reasons behind it."""
    coll = coll or {}
    dup_drop = {}
    for grp, why in DUPLICATE:
        present = [t for t in grp if t in keeps]
        if len(present) < 2:
            continue
        best = max(present, key=lambda t: keeps[t]["faces"])
        for t in present:
            if t != best:
                dup_drop[t] = f"duplicate of {best} — {why}"

    out = {}
    for t, k in keeps.items():
        flags, verdict = [], "SHIP"
        if t in NOT_A_CAR:
            flags.append(("not a car", NOT_A_CAR[t])); verdict = "DROP"
        if t in SCAN:
            flags.append(("scan", SCAN[t])); verdict = "DROP"
        if t in dup_drop:
            flags.append(("duplicate", dup_drop[t])); verdict = "DROP"
        if t in NOT_UK:
            flags.append(("not UK-market", NOT_UK[t])); verdict = "DROP"
        if t in DEFECT:
            flags.append(("defect", DEFECT[t]))
            verdict = "DROP" if verdict == "SHIP" else verdict
        for a, mdl, ys, ye, bs in coll.get(t, []):
            flags.append(("collides", f"{a} ({mdl} {ys or '?'}-{ye or ''} [{bs}])"))
            if verdict == "SHIP": verdict = "REVIEW"
        state, why = recolour(k)
        if state != "ok":
            flags.append(("recolour " + state, why))
            if verdict == "SHIP": verdict = "REVIEW"
        out[t] = {"verdict": verdict, "flags": flags, **k}
    return out


def main():
    keeps = load()
    # Derived for every keep, then overridden by the hand-curated plan where one
    # exists -- so a car nobody has planned yet is still collision-checked.
    plan = {t: plan_from_title(k) for t, k in keeps.items()}
    if os.path.exists(PLAN_FILE):
        plan.update(json.load(open(PLAN_FILE)))
    live = [x for x in json.loads(urllib.request.urlopen(CAT, timeout=60).read())
            if x.get("publicationStatus") != "quarantined"]
    coll = {t: collisions(p, live) for t, p in plan.items()
            if t in keeps and p.get("model")}

    # Entries in this batch also compete with EACH OTHER. Checking only against
    # the live catalogue misses that: two B8 Superbs and two 5F Leons were both
    # about to ship as "clean" while colliding head-on with their own batch mate.
    for t, p in plan.items():
        if t not in keeps or not p.get("model"):
            continue
        for u, q in plan.items():
            if u <= t or u not in keeps or not q.get("model"):
                continue
            if p["make"] != q["make"] or not (_toks(p["model"]) & _toks(q["model"])):
                continue
            if not _overlap(p.get("year_start"), p.get("year_end"),
                            q.get("year_start"), q.get("year_end")):
                continue
            pb, qb = (p.get("body_style") or "").lower(), (q.get("body_style") or "").lower()
            if pb and qb and pb != qb:
                continue
            coll.setdefault(t, []).append((u, "same batch", q.get("year_start"),
                                           q.get("year_end"), qb or "-"))
            coll.setdefault(u, []).append((t, "same batch", p.get("year_start"),
                                           p.get("year_end"), pb or "-"))
    res = audit(keeps, coll)
    order = {"DROP": 0, "REVIEW": 1, "SHIP": 2}
    tally = {}
    for t, r in sorted(res.items(), key=lambda kv: (order[kv[1]["verdict"]], kv[0])):
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1
    print(f"{len(keeps)} keeps audited — "
          + ", ".join(f"{v} {k}" for k, v in sorted(tally.items(), key=lambda kv: order[kv[0]])))
    for want in ("DROP", "REVIEW", "SHIP"):
        rows = [(t, r) for t, r in res.items() if r["verdict"] == want]
        print(f"\n{'='*74}\n{want} — {len(rows)}\n{'='*74}")
        for t, r in sorted(rows):
            print(f"  {t:<10} {r['name'][:48]}")
            for kind, why in r["flags"]:
                print(f"      [{kind}] {why}")
    json.dump(res, open("/tmp/publish_audit.json", "w"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
