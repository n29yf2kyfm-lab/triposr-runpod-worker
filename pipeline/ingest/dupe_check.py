#!/usr/bin/env python3
"""Duplicate detection over the FINAL Nissan pass list.

A looser face-only check produced false pairs (a Navara and a GT-R 57 faces
apart), so a pair is flagged ONLY when:
  (a) normalised title token overlap >= 0.75 (ignoring "nissan") AND face
      counts within 1%, or
  (b) face counts within 50 AND title token overlap >= 0.4.
Round-number decimation clusters (within 250 of a 100k multiple) are excluded
from rule (b): four Toyota Hiaces all landed within 252 faces of 1,000,000 and
were four different vans.
The lower face count is dropped; the more detailed mesh is kept.
"""
import json, re, itertools

V = "/home/user/triposr-runpod-worker/pipeline/ingest/nissan_audit_verdicts.json"
M = "/tmp/nissan/manifest.filtered.json"
OUT = "/home/user/triposr-runpod-worker/pipeline/ingest/NISSAN_DUPES.json"

STOP = {"nissan", "the", "a", "of", "and", "com", "www", "3d", "model", "free"}


def toks(s):
    s = re.sub(r"[^0-9a-z]+", " ", s.lower())
    return {t for t in s.split() if t and t not in STOP}


def overlap(a, b):
    A, B = toks(a), toks(b)
    if not A or not B:
        return 0.0
    return len(A & B) / min(len(A), len(B))


def shared(a, b):
    return len(toks(a) & toks(b))


def roundish(f):
    m = round(f / 100000) * 100000
    return m > 0 and abs(f - m) <= 250


PRIOR_DROPS = {r["drop_uid"] for r in json.load(open(OUT))}
rows = {r["uid"]: r for r in json.load(open(M))}
passes = [x for x in json.load(open(V)) if x["verdict"] == "pass"]
for p in passes:
    p["faces"] = rows.get(p["uid"], {}).get("faces", 0)
passes = [p for p in passes if p["faces"]]
print(f"{len(passes)} passes with a face count")

pairs = []
for a, b in itertools.combinations(sorted(passes, key=lambda x: -x["faces"]), 2):
    fa, fb = a["faces"], b["faces"]
    d = abs(fa - fb)
    ov = overlap(a["name"], b["name"])
    pct = d / max(fa, fb)
    ruleA = ov >= 0.75 and pct <= 0.01
    # Rule B on a single shared token is worthless: "Nissan Skyline Wagon" and
    # "1999 Skyline GT-R V-Spec II (R34)" land 13 faces apart and share only
    # "skyline" -> overlap 0.50, a wagon paired with a coupe. Demand >= 2.
    ruleB = (d <= 50 and ov >= 0.4 and shared(a["name"], b["name"]) >= 2
             and not (roundish(fa) and roundish(fb)))
    if ruleA or ruleB:
        keep, drop = (a, b) if fa >= fb else (b, a)
        # Respect a drop side already recorded by an earlier pass over this
        # marque rather than churning a decision the owner may have acted on.
        if keep["uid"] in PRIOR_DROPS and drop["uid"] not in PRIOR_DROPS:
            keep, drop = drop, keep
        pairs.append((keep, drop, ov, d, pct, "A" if ruleA else "B"))

# a uid already marked for dropping must not also be a keeper
dropped = set()
out = []
for keep, drop, ov, d, pct, rule in sorted(pairs, key=lambda t: -t[0]["faces"]):
    if drop["uid"] in dropped:
        continue
    dropped.add(drop["uid"])
    out.append({
        "drop_uid": drop["uid"],
        "name": drop["name"],
        "faces": drop["faces"],
        "keep_uid": keep["uid"],
        "keep_name": keep["name"],
        "keep_faces": keep["faces"],
        "reason": (f"duplicate mesh (rule {rule}): title token overlap "
                   f"{ov:.2f} ignoring 'nissan', face counts {drop['faces']:,} "
                   f"vs {keep['faces']:,} ({d:,} apart, {pct*100:.2f}%); "
                   f"keeping the higher face count"),
    })
out.sort(key=lambda r: r["drop_uid"])
json.dump(out, open(OUT, "w"), indent=1, ensure_ascii=False)
print(f"{len(out)} duplicate drops -> {OUT}")
for r in out:
    print(" ", r["name"], r["faces"], "<-drop | keep->", r["keep_name"], r["keep_faces"])
