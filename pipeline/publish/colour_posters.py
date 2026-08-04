"""Render and index one poster per colour variant, so the library has an image
for every colour it offers -- not just for the neutral GLB.

`make_posters.py` shoots the neutral published GLB, which is the right default
for a single hero image but is not what the customer picks from. It can also be
actively misleading: land-rover-range-rover-sport-2018-rr1-v1 ships a body
material at metallic 0.86 / roughness 0.0, so its neutral poster renders as
mirror chrome while all eight of its actual colour variants render as ordinary
paint. Anyone reviewing the library from posters alone would have judged that
car on a finish no customer ever sees.

Writes `colourPosterUrls`: {colour: url}, alongside the existing
`colourVariants` {colour: glb url}. Additive -- nothing reads it yet, and
nothing that exists breaks if it is absent.

Path convention follows the hero poster
(`car-renders/finished/<make>/<assetId>/hero.jpg`), one directory deeper:
`car-renders/finished/<make>/<assetId>/colours/<colour>.jpg`, same framing and
sample count so a colour poster and a hero poster sit together without a
visible break.

`--cache-dir` reuses frames already rendered on local disk (named
`v_<assetId>_<colour>.jpg`) instead of paying for the GPU again. The renders
are the expensive part and this container loses its disk without warning, so
the useful direction is local -> Supabase, once.

Usage:
    colour_posters.py --wave rr1 [--cache-dir DIR] [--parallel 4] [--dry-run]
"""
import argparse, io, json, os, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "pipeline", "publish"))
from make_posters import render, load_env, SB                        # noqa: E402

CAT = os.path.join(REPO, "platform", "catalogue", "catalogue.v2.json")
ORDER = ["white", "silver", "grey", "black", "blue", "red", "green", "yellow"]

load_env()
KEY = os.environ.get("SB_KEY") or sys.exit("FATAL: SB_KEY not set")
HDR = {"apikey": KEY, "Authorization": "Bearer " + KEY}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def sb_put(path, blob):
    last = None
    for _ in range(3):
        try:
            rq = urllib.request.Request(f"{SB}/{path}", data=blob, method="POST",
                headers={**HDR, "Content-Type": "image/jpeg", "x-upsert": "true"})
            return urllib.request.urlopen(rq, timeout=600).status
        except Exception as e:
            last = e
            time.sleep(5)
    raise last


def poster_path(entry, colour):
    return f"car-renders/finished/{entry['make']}/{entry['assetId']}/colours/{colour}.jpg"


def one(job):
    from PIL import Image
    entry, colour, glb_url, cache_dir, dry = job
    aid = entry["assetId"]
    cached = os.path.join(cache_dir, f"v_{aid}_{colour}.jpg") if cache_dir else None
    try:
        if cached and os.path.exists(cached) and os.path.getsize(cached) > 5000:
            blob, src = open(cached, "rb").read(), "cache"
        else:
            png = render(glb_url + f"?cb={int(time.time())}")
            buf = io.BytesIO()
            Image.open(io.BytesIO(png)).convert("RGB").save(buf, "JPEG", quality=88)
            blob, src = buf.getvalue(), "render"
        # never index an image that is not an image -- a truncated cache file
        # would otherwise be uploaded and referenced as if it were fine
        Image.open(io.BytesIO(blob)).verify()
    except Exception as e:
        return aid, colour, None, f"{type(e).__name__}: {str(e)[:70]}"
    p = poster_path(entry, colour)
    if not dry:
        sb_put(p, blob)
    return aid, colour, f"{SB}/public/{p}", None if src == "render" else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wave", default="")
    ap.add_argument("--assets", default="")
    ap.add_argument("--cache-dir", default="")
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--force", action="store_true", help="redo colours already indexed")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    cat = json.load(open(CAT))
    entries = cat if isinstance(cat, list) else cat.get("entries", cat)
    want = {s for s in a.assets.split(",") if s}
    todo = [e for e in entries
            if e.get("publicationStatus") == "approved"
            and (e.get("colourVariants") or {})
            and (e.get("assetId") in want if want else
                 (a.wave and (e.get("assetId") or "").endswith(f"-{a.wave}-v1")))]
    if not todo:
        sys.exit("nothing to do — no approved entry with colourVariants matched")

    jobs = []
    for e in todo:
        have = e.get("colourPosterUrls") or {}
        for c in ORDER:
            url = (e.get("colourVariants") or {}).get(c)
            if url and (a.force or c not in have):
                jobs.append((e, c, url, a.cache_dir, a.dry_run))
    if not jobs:
        sys.exit("nothing to do — every colour is already indexed (use --force)")
    log(f"{len(jobs)} colour poster(s) across {len(todo)} car(s)"
        + ("  [DRY RUN]" if a.dry_run else ""))

    got, fail = {}, 0
    with ThreadPoolExecutor(max_workers=a.parallel) as ex:
        for aid, colour, url, err in ex.map(one, jobs):
            if err:
                log(f"  FAIL {aid} {colour}: {err}")
                fail += 1
                continue
            got.setdefault(aid, {})[colour] = url

    if not a.dry_run:
        for e in todo:
            if got.get(e["assetId"]):
                e["colourPosterUrls"] = {**(e.get("colourPosterUrls") or {}),
                                         **got[e["assetId"]]}
        if got:
            json.dump(cat, open(CAT, "w"), indent=1, ensure_ascii=False)

    for aid, m in sorted(got.items()):
        log(f"  OK   {aid}  {len(m)} colour poster(s)")
    log(f"{sum(len(m) for m in got.values())} indexed, {fail} failed"
        + ("" if a.dry_run else " — catalogue updated locally. Gate, then serve BOTH paths."))
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
