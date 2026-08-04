"""Proof that the premium-audit gates fire on what they must catch and stay off
what they must not.

This file exists because a gate in this repo once shipped with `\\b` inside a
raw string, so it matched a literal backslash-b and had never matched anything,
while 224 shapes were staged behind it. A gate is not a gate until something
runs it against both a positive and a negative case.

Every case below is a real row from the Audi wave with a verdict the owner's
rubric produced by eye, so a regression here means the tool disagrees with a
decision that was actually made, not with a decision someone imagined.

    python3 tests/test_premium_audit.py
"""
import json, os, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "pipeline", "qc"))
from premium_audit import (judge, duplicate_clusters, cross_author_clusters,  # noqa: E402
                           nameplate, RACE, LWB, JUNK, TUNER)

UNIQ = os.path.join(REPO, "pipeline", "qc", "audi_unique129.json")

fails = []


def check(label, got, want):
    if got != want:
        fails.append(f"{label}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if got == want else 'FAIL'} {label}")


def row(**kw):
    base = dict(uid="u", name="", author="", faces=300_000,
                coverage=0.20, bodyMaterials=1)
    base.update(kw)
    return base


print("G7 motorsport / service vehicles must fire")
for name in ("Audi A4 DTM R14 Redbull", "2019 Audi RS5 DTM", "2003 Audi TT-R DTM",
             "audi r8 gt4", "2017 Audi R8 LMS GT4", "Audi Quattro Rally",
             "Audi Lms Evo Ii Gt3", "Audi A6 police car", "Audi e-tron taxi"):
    check(name, judge(row(name=name))[0], "G7")

print("G7 must NOT fire on ordinary road cars (incl. the two keeps)")
for name in ("Audi A3 Progressive Red_ Advanced", "Audi A3 2021 trim",
             "Audi RS4 Avant", "Audi R8 V10 Performance", "Audi S3 Sportback",
             "Audi A4 Allroad", "Audi Q3 Sportback", "audi_a4_avant_2013_fbx"):
    check(name, judge(row(name=name))[0], "G6")

print("G8 China-market long-wheelbase must fire")
for name in ("audi a3 L 35 tfsi", "audi a4 L40 tfsi", "Audi A6 L 45 TFSI",
             "audi q5 L"):
    check(name, judge(row(name=name))[0], "G8")

print("G8 must NOT fire on ordinary titles containing an L")
for name in ("Audi A4 Avant Legend", "Audi RS6 Launch Edition",
             "Audi A3 Sportback S line", "Audi Q7 LED"):
    check(name, judge(row(name=name))[0], "G6")

print("G9 near-duplicates: the four real A3 8Y uploads by one author")
a3 = [row(uid="U001", name="Audi A3 Progressive Red_ Advanced",
          author="ankitcomxrr", faces=539_297),
      row(uid="U002", name="Audi A3 2025 Mythos Black", author="ankitcomxrr", faces=538_105),
      row(uid="U003", name="Audi A3 2025", author="ankitcomxrr", faces=536_613),
      row(uid="U004", name="AUDI A3 2025 V1 (6)", author="ankitcomxrr", faces=535_310)]
d = duplicate_clusters(a3)
check("largest (U001) survives", "U001" in d, False)
for u in ("U002", "U003", "U004"):
    check(f"{u} flagged as duplicate", u in d, True)
check("U002 points at U001", d["U002"][0], "U001")
check("U002 judged G9 SCRAP", judge(a3[1], d)[:2], ("G9", "SCRAP"))

print("G9 must NOT cluster different models by the same prolific author")
mixed = [row(uid="x1", name="Audi A3 Sportback", author="Merc_TV", faces=300_000),
         row(uid="x2", name="Audi Q5 quattro", author="Merc_TV", faces=299_000)]
check("A3 vs Q5 not clustered", duplicate_clusters(mixed), {})

print("G9 must NOT cluster the same model by DIFFERENT authors")
two = [row(uid="y1", name="Audi A3", author="alice", faces=300_000),
       row(uid="y2", name="Audi A3", author="bob", faces=299_500)]
check("different authors not clustered", duplicate_clusters(two), {})

print("G9 must NOT cluster when face counts are far apart")
far = [row(uid="z1", name="Audi A3", author="alice", faces=500_000),
       row(uid="z2", name="Audi A3", author="alice", faces=194_324)]
check("500k vs 194k not clustered", duplicate_clusters(far), {})

print("nameplate extraction")
for name, want in (("Audi A3 2021 trim", "a3"), ("audi q5 L", "q5"),
                   # separators are stripped so "RS 6"/"RS6" and "e-tron"/"etron"
                   # cluster together instead of splitting into two nameplates
                   ("Audi RS 6 Avant", "rs6"), ("Audi e-tron GT", "etron"),
                   ("2003 Audi TT-R DTM", "tt"), ("Audi R8 V10", "r8"),
                   ("Volkswagen Golf", "")):
    check(f"nameplate({name!r})", nameplate(name), want)

print("G10 thin paint flags but never scraps")
g, v, _ = judge(row(name="Audi A4 MK2 (B6) 2000-2006", coverage=0.081))
check("A4 B6 at cov 0.081 -> G10", g, "G10")
check("G10 is SALVAGE, not SCRAP", v, "SALVAGE")
check("cov 0.175 (kept A3) still G6 PASS", judge(row(coverage=0.175))[:2], ("G6", "PASS"))

print("G11 cross-author re-uploads: the real RS5 Sportback pair")
rs5 = [row(uid="U056", name="2021 Audi RS5 Sportback", author="Ddiaz Design",
           faces=523_832, coverage=0.152),
       row(uid="U057", name="2021 Audi RS5 Sportback Car", author="l4096466",
           faces=517_930, coverage=0.152)]
x = cross_author_clusters(rs5)
check("larger (U056) survives", "U056" in x, False)
check("U057 flagged as re-upload", x.get("U057", (None,))[0], "U056")
check("U057 judged G11 SCRAP", judge(rs5[1], None, x)[:2], ("G11", "SCRAP"))
check("G9 alone does NOT catch it", duplicate_clusters(rs5), {})

print("G11 must NOT fire when coverage differs")
diffcov = [row(uid="a", name="Audi A3", author="x", faces=200_000, coverage=0.150),
           row(uid="b", name="Audi A3", author="y", faces=199_000, coverage=0.137)]
check("different coverage not clustered", cross_author_clusters(diffcov), {})

print("G11 must NOT fire when face counts are more than 1.5% apart")
farfaces = [row(uid="a", name="Audi A3", author="x", faces=200_000, coverage=0.150),
            row(uid="b", name="Audi A3", author="y", faces=180_000, coverage=0.150)]
check("10% apart not clustered", cross_author_clusters(farfaces), {})

print("G12 tuner conversions must fire")
for name in ("2014 Audi RS5 Coupe LB WORKS Body Kit", "Audi RS6-R C8 Avant ABT",
             "2020 ABT Sportline Audi RS6-R", "2013 Audi RS 5 Liberty Walk",
             "Audi Q7 Mansory", "Audi A5 widebody", "Audi S3 slammed"):
    check(name, judge(row(name=name))[0], "G12")

print("G12 must NOT fire on factory cars (incl. every kept car's title)")
for name in ("Audi A3 Progressive Red_ Advanced", "Audi A3 2021 trim",
             "Audi A6 C7 Limousine", "Audi A6 C8 Limousine", "AUDI Q3 SPORTBACK",
             "2022 Audi Q5 S-Line", "Audi TT RS II (8J) 2006-2014",
             "Audi TTS Coupe", "Audi A7 Sportback 2017", "Audi Q4 Etron(SUV 45)",
             "Audi S3 Limousine 8V", "2021 Audi S5 Convertible", "audi Rs3 2022",
             "2021 Audi RS5 Sportback", "2020 Audi RS5 Coupe",
             "2021 Audi RS6 Avant C8"):
    check(name, judge(row(name=name))[0] != "G12", True)

print("existing gates still hold")
check("G1 shell", judge(row(coverage=0.94))[:2], ("G1", "SCRAP"))
check("G2 no body material", judge(row(bodyMaterials=0))[:2], ("G2", "SCRAP"))
check("G3 junk tag", judge(row(name="Audi A6 3D scan"))[:2], ("G3", "SCRAP"))
check("G5 split suspect", judge(row(coverage=0.60))[:2], ("G5", "SALVAGE"))

print("regexes are real patterns, not literal backslash-b")
check("RACE matches a bare word", bool(RACE.search("dtm")), True)
check("RACE does not match inside a word", bool(RACE.search("adtmx")), False)
check("LWB does not match a lone L", bool(LWB.search("Audi L")), False)
check("JUNK still matches 'scan'", bool(JUNK.search("a 3d scan of a car")), True)

print("\nthe whole Audi wave re-judged against the 11 hand verdicts")
uniq = json.load(open(UNIQ))
dups = duplicate_clusters(uniq)
xdups = cross_author_clusters(uniq)
idx = {f"U{i + 1:03d}": e for i, e in enumerate(uniq)}
hand = json.load(open(os.path.join(REPO, "pipeline", "qc", "audi_percar_verdicts.json")))
caught = kept = 0
for k, (verdict, _) in sorted(hand.items()):
    g, v, reason = judge(idx[k], dups, xdups)
    if verdict == "SCRAP" and v == "SCRAP":
        caught += 1
    print(f"  {k} eye={verdict:5s} tool={g} {v:7s} {reason[:62]}")
    if verdict == "KEEP":
        kept += 1
        check(f"  {k} was KEPT by eye -- tool must not scrap it", v != "SCRAP", True)
scraps = sum(1 for v, _ in hand.values() if v == "SCRAP")
print(f"\ntool now auto-scraps {caught}/{scraps} of the hand-scrapped cars; "
      f"{kept} keeps survived")

print("\n" + ("FAILED:\n  " + "\n  ".join(fails) if fails else "ALL CHECKS PASSED"))
sys.exit(1 if fails else 0)
