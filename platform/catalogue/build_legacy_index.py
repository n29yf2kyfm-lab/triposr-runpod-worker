#!/usr/bin/env python3
"""build_legacy_index.py — regenerate the LEGACY serving index
(car-renders/catalogue.json, old flat schema) from the curated
catalogue.v2.json so both Supabase serving paths point at the same
approved, visually-audited assets.

Why this exists (found 2026-07-24): the live legacy index still pointed all
173 rows at pre-curation GLBs (`*_uc.glb`, raw TRELLIS dumps, and at least
one wrong vehicle — kia sportage serving a hyundai tucson mesh), while the
finished library sat unused in car-meshes/finished/. Any app path reading
the legacy index rendered junk.

Behaviour:
  * one row per (make, modelFamily), picking the best approved asset
    (qualityGrade, then newest yearStart);
  * glb_url -> the finished desktopGlbUrl; frame_count 0 / no manifest_url
    (no turntable frames exist for the curated library yet — the app's GLB
    viewer path takes over; re-add manifests as curated turntables land);
  * colour label from the asset's render colour, hex from the render palette;
  * backs up the live index to car-renders/backups/ before overwriting;
  * HEAD-checks every glb_url and refuses to publish on any failure.

Env: SB_KEY (Supabase service-role key). Never hardcoded.
"""
import datetime, json, os, sys, urllib.request

REF = os.environ.get("SUPABASE_REF", "tfkvthprsntexrcuqpyd")
SBKEY = os.environ.get("SB_KEY")
BASE = f"https://{REF}.supabase.co/storage/v1/object"
PUB = f"{BASE}/public/car-renders"

# colour family -> display hex (linear-ish palette from render/handler.py _RGB)
HEX = {"grey": "#6e7176", "gray": "#6e7176", "silver": "#c0c2c7", "black": "#0d0d0f",
       "white": "#e6e8ea", "blue": "#1a3d8f", "navy": "#12234d", "red": "#8f1d1d",
       "green": "#1d5c34", "orange": "#c2591a", "yellow": "#d4a90e", "bronze": "#6b4a1f",
       "gold": "#a67c1c", "beige": "#b0a184", "purple": "#4d1a70", "maroon": "#5c1a20",
       "pink": "#c25580", "turquoise": "#1a8f8f", "gunmetal": "#3d4449", "brown": "#5c4033"}


def fetch_v2():
    url = f"{PUB}/catalogue.v2.json?cb={int(datetime.datetime.now().timestamp())}"
    return json.loads(urllib.request.urlopen(url, timeout=60).read())


def head_ok(url):
    try:
        rq = urllib.request.Request(url, method="HEAD")
        return urllib.request.urlopen(rq, timeout=30).status == 200
    except Exception:
        return False


def upload(path, data, ctype="application/json"):
    rq = urllib.request.Request(f"{BASE}/car-renders/{path}", data=data, method="POST")
    for h, v in (("apikey", SBKEY), ("Authorization", "Bearer " + SBKEY),
                 ("Content-Type", ctype), ("x-upsert", "true")):
        rq.add_header(h, v)
    urllib.request.urlopen(rq, timeout=120).read()


def build(v2):
    grade = {"A": 0, "B": 1, "C": 2}
    best = {}
    for e in v2:
        if e.get("publicationStatus") != "approved" or not e.get("desktopGlbUrl"):
            continue
        key = ((e.get("make") or "").strip().lower(),
               (e.get("modelFamily") or e.get("model") or "").strip().lower())
        if not all(key):
            continue
        rank = (grade.get(e.get("qualityGrade"), 3), -(e.get("yearStart") or 0))
        if key not in best or rank < best[key][0]:
            best[key] = (rank, e)

    rows = []
    for (make, model), (_, e) in sorted(best.items()):
        fam = (e.get("defaultColourFamily") or "").lower()
        rows.append({
            "make": make, "model": model,
            "source_title": e.get("sourceTitle"),
            "colour_rendered": e.get("renderColourLabel") or e.get("oemPaintName") or "Native",
            "colour_hex": HEX.get(fam, "#8a8f98"),
            "licence": e.get("licence"),
            "tier": "B",
            "frame_count": 0,
            "glb_url": e.get("desktopGlbUrl"),
            "poster_url": e.get("posterUrl"),
            "undercarriage": True,
        })
    return rows


def main():
    if not SBKEY:
        sys.exit("set SB_KEY env var (Supabase service role key)")
    v2 = fetch_v2()
    rows = build(v2)
    print(f"v2 approved -> {len(rows)} legacy rows")

    bad = [r["glb_url"] for r in rows if not head_ok(r["glb_url"])]
    if bad:
        print("REFUSING to publish; unreachable glb_url(s):")
        for u in bad:
            print("  ", u)
        sys.exit(1)

    # reversible: snapshot the live index before overwriting it
    live = urllib.request.urlopen(f"{PUB}/catalogue.json", timeout=60).read()
    stamp = datetime.date.today().isoformat()
    upload(f"backups/catalogue.legacy-{stamp}.json", live)
    print(f"backed up live index -> backups/catalogue.legacy-{stamp}.json")

    body = json.dumps(rows, indent=1).encode()
    upload("catalogue.json", body)
    print(f"PUBLISHED {PUB}/catalogue.json ({len(rows)} rows, {len(body)//1024}KB)")


if __name__ == "__main__":
    main()
