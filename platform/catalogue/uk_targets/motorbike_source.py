"""Anonymous Sketchfab candidate search for the UK motorbike targets in targets.csv
(Harley-Davidson first, then road order). Commercial-OK licences only (CC BY, BY-SA,
CC0), with source.py's search and matching; nothing is downloaded (that needs
SKETCHFAB_TOKENS). Writes motorbike_candidates.jsonl here, resumable; the shortlist
in motorbike_candidates.csv is made from it (scans, toys and models under 20,000
faces left out, at most three per bike).

    python3 motorbike_source.py
"""
import csv, json, os, re, time

HERE = os.path.dirname(os.path.abspath(__file__))
ns = {}
exec(open(os.path.join(HERE, "source.py")).read().split("rows=list(csv.DictReader")[0], ns)   # get, q, cand
q, cand = ns["q"], ns["cand"]
rows = [r for r in csv.DictReader(open(os.path.join(HERE, "targets.csv"))) if r["class"] == "motorbike"]
rows.sort(key=lambda r: ("HARLEY" not in r["make"].upper(), int(r["rank"])))
out_p = os.path.join(HERE, "motorbike_candidates.jsonl")
done = {json.loads(l)["key"] for l in open(out_p)} if os.path.exists(out_p) else set()
with open(out_p, "a") as out:
    for i, r in enumerate(rows):
        key = f"{r['make']}|{r['genModel']}"
        if key in done:
            continue
        make, model = r["make"].title(), r["genModel"].replace(r["make"], "", 1).strip().title()
        words = [w.lower() for w in re.split(r"[\s-]+", model) if len(w) > 1] or [model.lower()]
        seen = {}
        for text in (f"{make} {model} motorcycle", f"{make} {model}"):
            for x in q(text):
                c = cand(x, words)
                if c and c["uid"] not in seen:
                    nm = (x.get("name") or "").lower()
                    c["make_named"] = any(w in nm for w in make.lower().replace("-", " ").split())
                    seen[c["uid"]] = c
            time.sleep(0.7)
        cs = sorted(seen.values(), key=lambda c: (-c["make_named"], -c["name_hits"], -(c["likes"] or 0)))[:8]
        out.write(json.dumps({"key": key, "rank": int(r["rank"]), "make": r["make"], "genModel": r["genModel"],
                              "licensed": int(r["licensed"]), "n": len(cs), "candidates": cs}) + "\n")
        out.flush()
        if i % 20 == 0:
            print(f"{i}/{len(rows)} {key} -> {len(cs)}", flush=True)
print("DONE", flush=True)
