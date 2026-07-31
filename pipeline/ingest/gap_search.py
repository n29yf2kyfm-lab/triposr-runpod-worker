"""Targeted, one-nameplate-at-a-time Sketchfab search.

Replaces the bulk-CSV approach, which had a collapsing hit rate: the last 237-row
sheet was 119 duplicates, and of the 118 new rows 49 were the same five
nameplates repeated (17 Lancer Evos, 12 Imprezas, 6 identical Lexus bodykits).
Sketchfab is dense in JDM performance cars and thin in ordinary UK metal, so
asking for a specific car by name is a far better use of a request than scraping
and hoping.

Ranking is deliberately not by likes alone. A 3M-face model is not a better
catalogue asset than a 300k one — it is a heavier one, and this library's median
is ~195k triangles. Face count is scored as a BAND around what the pipeline
actually serves, with likes as the tiebreak.

Usage: gap_search.py "Volkswagen Tiguan" [--years 2024,2025] [--top 4]
"""
import argparse, json, os, re, sys, urllib.parse, urllib.request
from itertools import cycle

API = "https://api.sketchfab.com/v3"
REPO = "/home/user/triposr-runpod-worker"
CAT = f"{REPO}/platform/catalogue/catalogue.v2.json"
# Serving band. Below this a model is usually a low-poly proxy; above it the
# browser decodes millions of triangles no matter how well the file compresses.
FACE_LO, FACE_IDEAL, FACE_HI = 60_000, 300_000, 1_200_000


def toks():
    v = os.environ.get("SKETCHFAB_TOKENS", "").strip()
    if not v:
        sys.exit("FATAL: SKETCHFAB_TOKENS not set")
    return cycle([t.strip() for t in v.split(",") if t.strip()])


def search(tok, q, count=24):
    p = {"type": "models", "q": q, "downloadable": "true",
         "sort_by": "-likeCount", "count": count}
    rq = urllib.request.Request(f"{API}/search?" + urllib.parse.urlencode(p),
        headers={"Authorization": f"Token {next(tok)}", "User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(rq, timeout=60)).get("results", [])


def face_score(fc):
    """1.0 at the ideal, decaying outward; 0 outside the usable band."""
    if not fc or fc < FACE_LO or fc > FACE_HI:
        return 0.0
    import math
    return 1.0 / (1.0 + abs(math.log10(fc / FACE_IDEAL)) * 2.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("nameplate", help='e.g. "Volkswagen Tiguan"')
    ap.add_argument("--years", default="", help="comma list to bias newest-first, e.g. 2025,2024")
    ap.add_argument("--top", type=int, default=4)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    tok = toks()

    # Every uid this project has ever judged - approved OR quarantined. A
    # quarantined uid means the owner already rejected it; re-offering it wastes
    # a review cycle on a decision that was already made.
    known = set()
    try:
        for e in json.load(open(CAT)):
            s = e.get("sourceReferenceId")
            if s:
                known.add(s)
    except Exception as ex:
        print(f"warn: catalogue unreadable ({ex}); dedup disabled", file=sys.stderr)

    queries = [f"{a.nameplate} {y}" for y in a.years.split(",") if y.strip()]
    queries += [a.nameplate, f"{a.nameplate} R-Line", f"{a.nameplate} facelift"]
    want = re.sub(r"[^a-z0-9]+", " ", a.nameplate.lower()).split()

    found = {}
    for q in queries:
        try:
            for r in search(tok, q):
                found.setdefault(r["uid"], r)
        except Exception as ex:
            print(f"  query failed [{q}]: {type(ex).__name__}", file=sys.stderr)

    rows = []
    for uid, r in found.items():
        nm = r.get("name", "")
        low = re.sub(r"[^a-z0-9]+", " ", nm.lower())
        # every word of the nameplate must appear, or "Tiguan" returns Golfs
        if not all(w in low for w in want):
            continue
        if uid in known:
            continue
        fc = r.get("faceCount") or 0
        yr = max([int(y) for y in re.findall(r"\b(19|20)\d{2}\b", nm)] or [0]) if re.search(r"\b(19|20)\d{2}\b", nm) else 0
        yr = max([int(y) for y in re.findall(r"\b((?:19|20)\d{2})\b", nm)] or [0])
        rows.append({
            "uid": uid, "name": nm, "year": yr, "faces": fc,
            "likes": r.get("likeCount", 0),
            "licence": (r.get("license") or {}).get("label", "?"),
            "author": (r.get("user") or {}).get("displayName", ""),
            # newest generation first, then a sane polycount, then popularity
            "score": (yr / 2030.0) * 3.0 + face_score(fc) * 2.0
                     + min(r.get("likeCount", 0), 200) / 200.0,
        })
    rows.sort(key=lambda x: -x["score"])
    print(f"{a.nameplate}: {len(found)} raw hits -> {len(rows)} new, on-name candidates")
    for r in rows[:a.top]:
        flag = "" if face_score(r["faces"]) else "  <-- outside serving band"
        print(f"  {r['score']:.2f}  {r['year'] or '----'}  {r['name'][:46]:46} "
              f"{r['faces']:>9,}f  ♥{r['likes']:<4} {r['licence'][:24]}{flag}")
    if a.out:
        json.dump(rows[:a.top], open(a.out, "w"), indent=1)
        print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
