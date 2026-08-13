"""Sweep every downloadable model for a marque, not the single best per query.

`wave_render.harvest` is deliberately narrow: it asks for one nameplate-year at
a time and keeps the top-scoring result, which is the right tool for filling a
known gap. Asked to sweep a whole marque it returns one car per query -- Audi
came back with 33 candidates that way, against the 347 the Volkswagen sweep
produced -- because 566 in-band models were never considered, only outranked.

This walks the search API by cursor across a generic marque query plus one
query per nameplate, keeps EVERY result inside the serving face band, dedupes
by uid, and drops anything already in the catalogue or refused by the hardened
title gates. Breadth is the point; ranking happens later, by eye, off the
rendered sheets.

The face band is the same one the serving pipeline uses (gap_search:
FACE_LO/FACE_HI). Below it a model is a low-poly proxy; above it the browser
decodes millions of triangles however well the file compresses.

Usage:
    marque_sweep.py --marque Audi --out /tmp/audi/manifest.json
                    [--nameplates "A1,A3,A4,..."] [--max-pages 60]
"""
import argparse, json, os, sys, time, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from gap_search import API, FACE_LO, FACE_HI, toks          # noqa: E402
from wave_render import class_gates, norm                    # noqa: E402

CAT = os.path.join(REPO, "platform", "catalogue", "catalogue.v2.json")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def walk(tok, q, max_pages):
    """Every downloadable result for one query, following the cursor."""
    out, cursor, pages = {}, None, 0
    while pages < max_pages:
        p = {"type": "models", "q": q, "downloadable": "true",
             "count": 24, "archives_flavours": "false"}
        if cursor:
            p["cursor"] = cursor
        rq = urllib.request.Request(f"{API}/search?" + urllib.parse.urlencode(p),
            headers={"Authorization": f"Token {next(tok)}",
                     "User-Agent": "Mozilla/5.0"})
        try:
            d = json.load(urllib.request.urlopen(rq, timeout=60))
        except urllib.error.HTTPError as e:
            if e.code in (429, 403):
                time.sleep(3)
                continue
            break
        except Exception:
            break
        res = d.get("results") or []
        for r in res:
            out[r["uid"]] = r
        pages += 1
        nxt = (d.get("cursors") or {}).get("next")
        if not res or not nxt or nxt == cursor:
            break
        cursor = nxt
        time.sleep(0.15)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--marque", required=True)
    ap.add_argument("--nameplates", default="",
                    help="comma-separated; each becomes '<marque> <nameplate>'")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-pages", type=int, default=60)
    # CLAUDE.md 2026-08-09: "COST TO EARLIER WAVES IS UNMEASURED, NOT ZERO ...
    # those files are POST-filter, so any car the bug dropped was never written
    # to them. The loss is invisible there by construction ... worth doing: no
    # wave currently retains it." These two dumps make it measurable. Both are
    # opt-in so a concurrent wave's invocation is unchanged.
    ap.add_argument("--raw-out", default="",
                    help="dump EVERY in-band result before the on-marque and "
                         "title-gate cuts, so downstream filter losses can be "
                         "measured rather than guessed")
    ap.add_argument("--rejects-out", default="",
                    help="dump every title-gate rejection with the token that "
                         "fired it (the log only prints the first 10)")
    ap.add_argument("--face-hi", type=int, default=FACE_HI,
                    help="upper face cap for this sweep (default %(default)s). "
                         "RAISE IT to reach modern volume cars: the standard "
                         "1.2M cap is a BROWSER DELIVERY budget, not a quality "
                         "judgement, and pipeline/optimisation/decimate_heavy.py "
                         "already reduces an over-budget model safely. Measured "
                         "2026-08-13: the cap alone was hiding 'Ford Puma 2025' "
                         "(1,498,818 faces) — the UK's best selling car, of "
                         "which the catalogue holds NONE — plus Ford Fiesta 2018 "
                         "(1.5M), Fiesta MK6 (1.76M) and Qashqai 2010 (1.39M). "
                         "Picks above the standard cap are flagged heavy=true.")
    ap.add_argument("--face-lo", type=int, default=FACE_LO,
                    help="lower face floor for this sweep (default %(default)s)")
    a = ap.parse_args()

    tok = toks()
    gates = class_gates()
    try:
        known = {e["sourceReferenceId"] for e in json.load(open(CAT))
                 if e.get("sourceReferenceId")}
    except Exception:
        known = set()
    log(f"catalogue already holds {len(known)} sourced uids")

    queries = [a.marque] + [f"{a.marque} {n.strip()}"
                            for n in a.nameplates.split(",") if n.strip()]
    pool = {}
    for q in queries:
        got = walk(tok, q, a.max_pages)
        fresh = len(set(got) - set(pool))
        pool.update(got)
        log(f"  {q:28s} {len(got):4d} results, {fresh:4d} new  (pool {len(pool)})")

    band, thin, heavy = [], 0, 0
    for r in pool.values():
        fc = r.get("faceCount") or 0
        if fc < a.face_lo:
            thin += 1
        elif fc > a.face_hi:
            heavy += 1
        else:
            band.append(r)

    picks, dupes, rejects, offmarque = [], 0, [], 0
    raw = []
    want = norm(a.marque)
    for r in sorted(band, key=lambda x: -(x.get("faceCount") or 0)):
        if a.raw_out:
            raw.append({"uid": r["uid"], "name": r.get("name", ""),
                        "faces": r.get("faceCount") or 0,
                        "likes": r.get("likeCount") or 0,
                        "licence": ((r.get("license") or {}).get("label") or ""),
                        "author": ((r.get("user") or {}).get("displayName")
                                   or (r.get("user") or {}).get("username") or ""),
                        "catalogued": r["uid"] in known})
        if r["uid"] in known:
            dupes += 1
            continue
        nm = norm(r.get("name", ""))
        if want not in nm:                       # keep the sweep on-marque
            offmarque += 1
            continue
        if gates:
            hit = gates[0].search(nm) or gates[1].search(nm)
            if hit:
                rejects.append({"uid": r["uid"], "name": r.get("name", ""),
                                "faces": r.get("faceCount") or 0,
                                "gate_token": hit.group(0)})
                continue
        picks.append({"uid": r["uid"], "name": r.get("name", ""),
                      "faces": r.get("faceCount") or 0,
                      # over the STANDARD delivery cap -> must go through
                      # decimate_heavy before publish, not a quality flag
                      "heavy": (r.get("faceCount") or 0) > FACE_HI,
                      "likes": r.get("likeCount") or 0,
                      "licence": ((r.get("license") or {}).get("label") or ""),
                      "author": ((r.get("user") or {}).get("displayName")
                                 or (r.get("user") or {}).get("username") or ""),
                      "plate": a.marque, "anchor": 0})

    log(f"\nunique downloadable : {len(pool)}")
    log(f"  below {a.face_lo:,} faces : {thin}")
    log(f"  above {a.face_hi:,} faces : {heavy}")
    log(f"  inside the band     : {len(band)}")
    log(f"  already catalogued  : {dupes}")
    log(f"  off-marque title    : {offmarque}")
    log(f"  title gates rejected: {len(rejects)}")
    for r in rejects[:10]:
        log(f"      [{r['gate_token']}] {r['name'][:46]}")
    log(f"CANDIDATES          : {len(picks)}")
    json.dump(picks, open(a.out, "w"), indent=1)
    log(f"wrote {a.out}")
    if a.raw_out:
        json.dump(raw, open(a.raw_out, "w"), indent=1)
        log(f"wrote {a.raw_out}  ({len(raw)} in-band rows, pre-filter)")
    if a.rejects_out:
        json.dump(rejects, open(a.rejects_out, "w"), indent=1)
        log(f"wrote {a.rejects_out}  ({len(rejects)} title-gate rejections)")


if __name__ == "__main__":
    main()
