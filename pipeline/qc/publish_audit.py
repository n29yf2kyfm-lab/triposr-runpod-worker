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
    "skoda#37": "slammed to the floor with the wheels tucked into the arches",
    "skoda#38": "same slammed mesh as #37",
}

# Live entry this car would compete with: same make + model + overlapping years
# + same body style is a straight collision in the resolver.
COLLIDES = {
    "skoda#17": "skoda-karoq-2020-v1 (Karoq, 2020, suv)",
    "skoda#43": "skoda-karoq-2020-v1 (Karoq, 2020, suv)",
    "skoda#25": "skoda-enyaq-v1 (Enyaq, 2021-2026, suv)",
    "skoda#37": "skoda-kamiq-v1 (2019-2026) and skoda-kamiq-2020-w12-v1",
    "skoda#38": "skoda-kamiq-v1 (2019-2026) and skoda-kamiq-2020-w12-v1",
    "skoda#34": "skoda-kodiaq-2022-v1 and skoda-kodiaq-2020-w12-v1",
    "skoda#26": "skoda-kamiq-v1 (2019-2026, suv)",
    "skoda#27": "skoda-kamiq-v1 (2019-2026, suv)",
    "seat#12":  "seat-ateca-2020-v1 (Ateca, 2020, suv)",
    "seat#15":  "seat-ibiza-mk2-v1 (Ibiza, 1993-2002, hatchback)",
    "kia#20":   "kia-sportage-2023-v1 (Sportage, 2023-2026, suv)",
    "kia#21":   "kia-sportage-2023-v1 (Sportage, 2023-2026, suv)",
    "kia#26":   "kia-sportage-2023-v1 (Sportage, 2023-2026, suv)",
    "kia#7":    "kia-sportage-2012-v1 (2016-2026) and kia-sportage-2011-w6-v1",
    "kia#16":   "kia-rio-v1 (Rio, 2021-2026, hatchback)",
    "kia#15":   "kia-rio-v1 (Rio, 2021-2026, hatchback)",
    "kia#3":    "kia-stonic-v1 (Stonic, 2017-2026, suv)",
    "kia#23":   "kia-stonic-v1 (Stonic, 2017-2026, suv)",
    "kia#6":    "kia-stinger-v1 (Stinger, 2017-2023, saloon)",
    "kia#19":   "kia-sorento-v1 (Sorento, 2020-2026, suv)",
    "kia#29":   "kia-carnival-2022-w6-v1 (Carnival, 2022)",
    "kia#49":   "kia-soul-2020-v1 (Soul, 2020, suv) — different generation, check the year range",
    "skoda#13": "the other B8 Superbs in this same wave (#3, #15)",
    "skoda#3":  "the other B8 Superbs in this same wave (#13, #15)",
    "mini#3":   "mini#9, the other 1960s classic Mini in this wave",
    "mini#9":   "mini#3, the other 1960s classic Mini in this wave",
}


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


def audit(keeps):
    """Each car gets a verdict and the reasons behind it."""
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
        if t in COLLIDES:
            flags.append(("collides", COLLIDES[t]))
            if verdict == "SHIP": verdict = "REVIEW"
        state, why = recolour(k)
        if state != "ok":
            flags.append(("recolour " + state, why))
            if verdict == "SHIP": verdict = "REVIEW"
        out[t] = {"verdict": verdict, "flags": flags, **k}
    return out


def main():
    keeps = load()
    res = audit(keeps)
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
