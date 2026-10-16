#!/usr/bin/env python3
"""top2000.py — the UK's 2,000 most common cars by make and model, with what
the catalogue has for each.

    python3 platform/catalogue/uk_targets/top2000.py df_VEH0120_UK.csv [N]

Source: DfT VEH0120 (UK), licensed vehicles at the end of the latest quarter
in the file, body type Cars, summed over fuel and detailed model to DfT's
generic model (FORD FIESTA spans every Fiesta). Rows DfT could not give a
model for ("... MODEL MISSING") are left out of the ranking and counted in
the totals. Writes top2000_cars.csv next to this file.
"""
import collections
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
src = sys.argv[1]
N = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
rows = csv.reader(open(src, newline="", encoding="utf-8-sig"))
head = next(rows)
q = head[6]                                    # the latest quarter, e.g. "2026 Q2"
ix = {k: head.index(k) for k in ("BodyType", "Make", "GenModel", "Fuel", "LicenceStatus")}
count, total, missing = collections.Counter(), 0, 0
fuel = collections.defaultdict(collections.Counter)
for r in rows:
    if r[ix["BodyType"]] != "Cars" or r[ix["LicenceStatus"]] != "Licensed":
        continue
    v = r[6].strip()
    k = int(v) if v.isdigit() else 0          # "[c]"/"[x]" cells are suppressed small counts
    total += k
    if "MISSING" in r[ix["GenModel"]].upper():
        missing += k
        continue
    key = (r[ix["Make"]], r[ix["GenModel"]])
    count[key] += k
    fuel[key][r[ix["Fuel"]]] += k

# the catalogue match, as in join.py
exec(compile(open(os.path.join(HERE, "join.py")).read().split("BODY=")[0]
             .replace("R=json.load(open('ranked_by_body.json'))", "")
             .replace("open('../catalogue.v2.json')", f"open({os.path.join(HERE, '../catalogue.v2.json')!r})")
             .replace("open('../../rigmachine/survey/survey.jsonl')",
                      f"open({os.path.join(HERE, '../../rigmachine/survey/survey.jsonl')!r})"), "join", "exec"))
out, cum = [], 0
for rank, ((make, gen), lic) in enumerate(count.most_common(N), 1):
    cum += lic
    assets = find(make, gen)  # noqa: F821  (from join.py)
    model = gen[len(make):].strip() if gen.upper().startswith(make.upper()) else gen
    nice = lambda t: " ".join(w.title() if len(w) > 3 and not re.search(r"\d", w) else w for w in t.split())  # noqa: E731
    out.append({"rank": rank, "make": nice(make), "model": nice(model),
                "dft_generic_model": gen, "licensed": lic, "share_pct": round(lic * 100 / total, 3),
                "cum_pct": round(cum * 100 / total, 2), "main_fuel": fuel[(make, gen)].most_common(1)[0][0],
                "catalogue_models": len(assets), "catalogue_ids": "|".join(a["assetId"] for a in assets[:6])})
dst = os.path.join(HERE, f"top{N}_cars.csv")
w = csv.DictWriter(open(dst, "w", newline=""), fieldnames=list(out[0]))
w.writeheader()
w.writerows(out)
print(json.dumps({"quarter": q, "licensed_cars": total, "model_missing": missing, "generic_models": len(count),
                  "rows": len(out), "cover_pct": out[-1]["cum_pct"],
                  "with_catalogue_model": sum(1 for o in out if o["catalogue_models"]),
                  "licensed_with_model_pct": round(sum(o["licensed"] for o in out if o["catalogue_models"]) * 100 / total, 1),
                  "file": dst}, indent=1))
