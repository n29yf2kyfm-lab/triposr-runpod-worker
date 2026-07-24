#!/usr/bin/env python3
"""fetch_dims.py — build platform/geometry/vehicle_dims.csv: verifiable factory
exterior dimensions (length/width/height/wheelbase, mm) for every approved
catalogue model.

Source: Wikipedia's open API (facts with a citable source page per row) — NOT
scraped from gated commercial databases. Per the accuracy rule, a row is only
written when a plausible mm value was actually parsed; anything unparsed stays
blank for manual curation, and every row records source_page + fetch date.

Consumers (wired separately):
  * pipeline/qc/asset_audit.py    — auto reference L/W for the G1 proportion gate
  * pipeline/blender/normalize_shell.py — true-scale shells to factory length
  * Alam-3D fine-tune eval        — bbox-vs-factory dimensional accuracy metric

Usage:
  python3 pipeline/geometry/fetch_dims.py [--catalogue PATH] [--out PATH]
      [--limit N] [--sleep 0.25]
"""
import argparse, csv, datetime, json, os, re, time, urllib.parse, urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UA = {"User-Agent": "ExpertCarCheck-dims/1.0 (catalogue QC; contact: repo owner)"}

SANE = {"length_mm": (2300, 6800), "width_mm": (1300, 2400),
        "height_mm": (1000, 2300), "wheelbase_mm": (1600, 4300)}
FIELDS = {"length": "length_mm", "width": "width_mm",
          "height": "height_mm", "wheelbase": "wheelbase_mm"}


def api(params):
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)
    for attempt in range(5):
        try:
            return json.loads(urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=40).read())
        except urllib.error.HTTPError as e:
            wait = int(e.headers.get("Retry-After", 0) or 0) or 3 * (attempt + 1)
            time.sleep(wait)          # 429/5xx: honour Retry-After, else backoff
        except Exception:
            time.sleep(3 * (attempt + 1))
    return {}


def search_page(query):
    d = api({"action": "query", "list": "search", "srsearch": query,
             "srlimit": 3, "format": "json"})
    hits = d.get("query", {}).get("search", [])
    return hits[0]["title"] if hits else None


def wikitext(title):
    d = api({"action": "parse", "page": title, "prop": "wikitext",
             "format": "json", "redirects": 1})
    return d.get("parse", {}).get("wikitext", {}).get("*", "")


def parse_mm(fragment):
    """First plausible mm value in an infobox field fragment.
    Handles '4,284 mm', '{{convert|4284|mm|...}}' and '{{cvt|2680|mm}}'."""
    m = re.search(r"\{\{(?:convert|cvt)\|([\d,\.]+)\|mm", fragment, re.I)
    if not m:
        m = re.search(r"([\d,]{4,6})\s*mm", fragment)
    if not m:
        return None
    try:
        return int(float(m.group(1).replace(",", "")))
    except ValueError:
        return None


def extract_dims(text):
    out = {}
    for wiki_key, col in FIELDS.items():
        m = re.search(r"\|\s*" + wiki_key + r"\s*=\s*([^\n]{0,160})", text, re.I)
        if not m:
            continue
        v = parse_mm(m.group(1))
        if v is not None and SANE[col][0] <= v <= SANE[col][1]:
            out[col] = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalogue", default=os.path.join(REPO, "platform", "catalogue", "catalogue.v2.json"))
    ap.add_argument("--out", default=os.path.join(REPO, "platform", "geometry", "vehicle_dims.csv"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=0.8)
    ap.add_argument("--resume", action="store_true", help="keep rows in --out that already have dims; refetch only blanks")
    a = ap.parse_args()

    cat = [e for e in json.load(open(a.catalogue)) if e.get("publicationStatus") == "approved"]
    seen, targets = set(), []
    for e in cat:
        key = ((e.get("make") or "").strip().lower(), (e.get("model") or "").strip().lower())
        if key in seen or not all(key):
            continue
        seen.add(key)
        targets.append({"make": e.get("make"), "model": e.get("model"),
                        "generation": e.get("generation") or "",
                        "yearStart": e.get("yearStart")})
    if a.limit:
        targets = targets[:a.limit]

    done = {}
    if a.resume and os.path.exists(a.out):
        with open(a.out) as f:
            for r in csv.DictReader(f):
                if r.get("length_mm"):
                    done[(r["make"].lower(), r["model"].lower())] = r

    today = datetime.date.today().isoformat()
    cols = ["make", "model", "generation", "length_mm", "width_mm", "height_mm",
            "wheelbase_mm", "source_page", "source", "fetched"]
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    # incremental: rewrite header now, append each row as it lands (a crash
    # loses at most the in-flight model, never the run)
    outf = open(a.out, "w", newline="")
    writer = csv.DictWriter(outf, fieldnames=cols)
    writer.writeheader()
    rows, hit = [], 0
    for i, t in enumerate(targets):
        prev = done.get((t["make"].lower(), t["model"].lower()))
        if prev:
            rows.append(prev); hit += 1
            writer.writerow({k: prev.get(k, "") for k in cols}); outf.flush()
            continue
        # generation-specific page first (e.g. "Volkswagen Golf Mk7"), then base model
        queries = []
        if t["generation"]:
            queries.append(f"{t['make']} {t['model']} {t['generation']}")
        queries.append(f"{t['make']} {t['model']} (car)")
        dims, page = {}, None
        for q in queries:
            title = search_page(q)
            if not title:
                continue
            d = extract_dims(wikitext(title))
            if d:
                dims, page = d, title
                break
            page = page or title
        row = {"make": t["make"], "model": t["model"], "generation": t["generation"],
               "source_page": page or "", "source": "en.wikipedia", "fetched": today}
        row.update({c: dims.get(c, "") for c in SANE})
        rows.append(row)
        writer.writerow({k: row.get(k, "") for k in cols}); outf.flush()
        if dims:
            hit += 1
        print(f"[{i+1}/{len(targets)}] {t['make']} {t['model']}: "
              f"{dims if dims else 'NO DIMS'} ({page})", flush=True)
        time.sleep(a.sleep)

    outf.close()
    full = sum(1 for r in rows if r["length_mm"] and r["width_mm"])
    print(f"\nVEHICLE_DIMS {a.out}: {len(rows)} models, {hit} with any dims, "
          f"{full} with length+width")


if __name__ == "__main__":
    main()
