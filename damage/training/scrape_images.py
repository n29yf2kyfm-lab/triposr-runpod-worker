"""Collect car-damage training images from licence-clean sources, with provenance.

This exists because of a specific, expensive mistake. The merged Roboflow corpus
was tagged CC-BY-4.0 and Public Domain by its uploaders, and 26.6% of it turned
out to carry burned-in annotation boxes while ~114 files were iStock, Getty,
Shutterstock and AdobeStock previews. An uploader's licence tag cannot override
a photographer's copyright, and by the time the images are in a folder the
question "where did this come from?" is unanswerable from the pixels — two
separate pixel-based watermark detectors were built and both measurably failed
(see clean_dataset.py). So the rule here is:

    PROVENANCE IS RECORDED AT DOWNLOAD TIME OR THE IMAGE IS NOT KEPT.

Every accepted image gets a line in provenance.jsonl carrying its source, page
URL, licence, licence URL, author and the query that found it. That file is the
dataset's licence audit, and it is written as the image lands rather than
reconstructed later.

SOURCES
  wikimedia  MediaWiki API over Wikimedia Commons. Returns real licence
             metadata (LicenseShortName, Artist, UsageTerms) per file. Verified
             reachable from this container; needs a descriptive User-Agent or
             it 429s.
  openverse  api.openverse.org — aggregates Flickr, Wikimedia, museums and
             others behind one licence-filtered search. No key needed.
  urls       A plain text file of image URLs, one per line, optionally
             "<url><TAB><licence>". For images you have sourced yourself and
             whose rights you know.

ON GOOGLE IMAGES: not wired in, deliberately. There is no image API to call;
Google Images results are scraped SERP HTML, which breaks their terms, blocks
datacenter IPs, and — the part that actually matters here — returns arbitrary
copyrighted images with no licence metadata whatsoever. That is precisely the
hole the corpus already fell into. If you find images on Google that you want,
put their URLs in a file and use `--source urls`: the pipeline will still fetch,
filter, dedupe and record them, and the licence field will honestly say
"unverified" rather than inventing a tag.

FILTERING. Every candidate must survive, in order: a resolution floor, a
sharpness floor (the "crisp" requirement), the clean_dataset verdicts
(burned-in annotation / stock filename / destroyed), and a SHA-256 dedupe
against everything already in the output directory.

FAINT DAMAGE. `--pack faint` targets the subtle end — hairline scratches, light
scuffs, swirl marks — because that is where a detector trained on wrecked-car
photos fails hardest, and it is the case worth optimising for. `--min-faint`
additionally screens for images whose damage signal is genuinely low-contrast,
so a "faint scratch" query that returns a smashed bumper gets dropped.

    python scrape_images.py --source wikimedia --pack faint --out scraped --limit 300
    python scrape_images.py --source openverse --pack general --out scraped --limit 500
    python scrape_images.py --source urls --urls my_links.txt --out scraped
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from clean_dataset import classify, sharpness, _thumb  # noqa: E402

UA = ("triposr-damage-dataset/1.0 (research; contact via repository) "
      "python-requests")

# Licence gate. Two vocabularies have to be understood at once: Wikimedia
# spells them out ("CC BY-SA 4.0", "Public domain"), Openverse uses bare short
# codes ("by", "by-sa", "cc0", "pdm"). A regex written for one silently rejects
# every result from the other — which is exactly what happened on the first
# live run, where all 85 Openverse candidates were thrown away as
# "licence_not_allowed" because "by-sa" does not start with "cc".
_LICENCE_OK = re.compile(
    r"^(cc0|pdm|public\s*domain(\s*mark)?|no\s*restrictions|"
    r"(cc[\s-]*)?by([\s-]*sa)?)"
    r"([\s-]*\d(\.\d)?)?\s*$", re.I)          # optional trailing version
# NonCommercial and NoDerivatives cannot be used to train a model that ships in
# a commercial product. Checked separately and first, because "CC BY-NC-SA 4.0"
# would otherwise partially match the permissive pattern above.
_LICENCE_BLOCKED = re.compile(r"(^|[\s-])(nc|nd)([\s-]|$)", re.I)


def licence_ok(licence):
    """True when this licence permits commercial reuse of the image.

    Unknown or empty licences are NOT permitted: the whole point of this module
    is that an absent licence is a red flag, not a default-allow.
    """
    s = (licence or "").strip()
    if not s:
        return False
    if _LICENCE_BLOCKED.search(s):
        return False
    return bool(_LICENCE_OK.match(s))

QUERY_PACKS = {
    # The subtle end. This is the pack that matters: a detector trained only on
    # dramatic collision photos will not see a hairline scratch on a grey door.
    "faint": [
        "car paint scratch close up", "light scratch car door",
        "hairline scratch car paint", "car clear coat scratch",
        "swirl marks car paint", "car paint scuff mark",
        "minor scratch car bumper", "car door ding", "light scuff car bumper",
        "car paint chip close up", "shopping trolley scratch car",
        "key scratch car paint", "car paint imperfection close up",
    ],
    "general": [
        "car accident damage", "damaged car bumper", "dented car door",
        "car collision damage", "broken car headlight", "cracked windshield",
        "car rust damage", "hail damage car", "car fender bender",
        "crashed car front", "car rear end collision", "scratched car panel",
    ],
    "severe": [
        "car wreck", "totaled car", "car crash damage severe",
        "car front end collision damage", "rolled over car",
    ],
}


def _session():
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s


def _get(sess, url, tries=3, timeout=20, **kw):
    """GET with bounded backoff.

    Bounded on purpose. An earlier version retried 5 times with unbounded
    exponential backoff and a 45s timeout, so a single dead image URL could
    burn ~250s and one bad query could stall the whole run past any sensible
    limit. Broken image links are common and individually worthless — give up
    quickly and move to the next candidate. Wikimedia's 429s are handled by the
    descriptive User-Agent, not by waiting longer.
    """
    delay = 2
    for attempt in range(tries):
        try:
            r = sess.get(url, timeout=timeout, **kw)
        except Exception:
            if attempt == tries - 1:
                return None
            time.sleep(delay); delay = min(delay * 2, 8)
            continue
        if r.status_code == 200:
            return r
        if r.status_code in (429, 503) and attempt < tries - 1:
            time.sleep(delay); delay = min(delay * 2, 8)
            continue
        # Say so. A silently-swallowed 4xx on a SEARCH call ends the generator
        # with no candidates and no rejections, which reads as "the source had
        # nothing" rather than "the request was wrong" — a 401 from a too-large
        # page_size once cost a whole run that looked merely empty.
        if r.status_code != 404:
            body = (r.text or "")[:160].replace("\n", " ")
            print(f"    [http {r.status_code}] {url.split('?')[0][:70]} {body}",
                  file=sys.stderr)
        return None
    return None


# --- sources ---------------------------------------------------------------
# Each yields dicts: image_url, page_url, licence, licence_url, author, title.

def source_wikimedia(sess, query, limit):
    """Wikimedia Commons file search with licence metadata."""
    api = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}", "gsrnamespace": "6",
        "gsrlimit": str(min(limit, 50)), "prop": "imageinfo",
        "iiprop": "url|extmetadata|size",
        "iiurlwidth": "1600",
    }
    r = _get(sess, api, params=params)
    if not r:
        return
    pages = (r.json().get("query") or {}).get("pages") or {}
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        def m(k):
            v = (meta.get(k) or {}).get("value", "")
            return re.sub(r"<[^>]+>", "", str(v)).strip()
        yield {
            "image_url": info.get("thumburl") or info.get("url"),
            "page_url": info.get("descriptionurl") or "",
            "licence": m("LicenseShortName") or m("License"),
            "licence_url": m("LicenseUrl"),
            "author": m("Artist"),
            "title": page.get("title", ""),
            "width": info.get("width"), "height": info.get("height"),
        }


def source_openverse(sess, query, limit):
    """Openverse — CC-licensed image aggregator, mostly Flickr for this domain.

    Paginated: Openverse returns at most 50 per page and caps a query at a few
    hundred results total, so the per-query ceiling is a property of the source
    rather than something a bigger --per-query can lift. Stops on the first
    empty or failed page.
    """
    api = "https://api.openverse.org/v1/images/"
    # 20 is the hard ceiling for unauthenticated requests — asking for more
    # returns 401, not a truncated page. Register a free Openverse key and set
    # OPENVERSE_TOKEN to raise it.
    page_size = 20
    token = os.environ.get("OPENVERSE_TOKEN")
    if token:
        sess.headers["Authorization"] = f"Bearer {token}"
        page_size = 50
    page, got = 1, 0
    while got < limit and page <= 40:
        r = _get(sess, api, params={
            "q": query, "page_size": str(page_size), "page": str(page),
            "license_type": "all-cc,commercial", "mature": "false"})
        if not r:
            return
        try:
            results = r.json().get("results", [])
        except Exception:
            return
        if not results:
            return
        for it in results:
            yield {
                "image_url": it.get("url"),
                "page_url": it.get("foreign_landing_url") or it.get("url", ""),
                "licence": it.get("license", ""),
                "licence_url": it.get("license_url", ""),
                "author": it.get("creator", ""),
                "title": it.get("title", ""),
                "width": it.get("width"), "height": it.get("height"),
            }
            got += 1
            if got >= limit:
                return
        page += 1


def source_urls(sess, url_file, limit):
    """A file of URLs you supply. Licence is whatever you declare, or
    'unverified' — never guessed."""
    with open(url_file) as f:
        for i, line in enumerate(f):
            if i >= limit:
                return
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            yield {
                "image_url": parts[0],
                "page_url": parts[0],
                "licence": parts[1].strip() if len(parts) > 1 else "unverified",
                "licence_url": "", "author": "", "title": "",
                "width": None, "height": None,
            }


# --- quality gates ---------------------------------------------------------

def faintness(path):
    """How subtle the strongest local feature is, 0-1 (higher = fainter).

    A smashed bumper has huge dark/bright discontinuities; a hairline scratch is
    a thin low-amplitude ridge. This measures the 99.5th-percentile gradient
    magnitude and inverts it, so 'faint scratch' queries that return wrecks can
    be screened out of a faint-damage pack.
    """
    import numpy as np
    arr = _thumb(path, size=256)
    g = arr.mean(axis=2)
    gx = np.abs(np.diff(g, axis=1))[:-1, :]
    gy = np.abs(np.diff(g, axis=0))[:, :-1]
    mag = np.hypot(gx, gy)
    peak = float(np.percentile(mag, 99.5))
    return max(0.0, min(1.0, 1.0 - peak / 160.0))


def accept(path, min_side, min_sharp, min_faint):
    """(ok, reason, metrics) for a freshly downloaded file."""
    from PIL import Image
    try:
        with Image.open(path) as im:
            w, h = im.size
            im.verify()
    except Exception as e:
        return False, "unreadable", {"error": type(e).__name__}
    if min(w, h) < min_side:
        return False, "too_small", {"size": [w, h]}
    verdict, metrics = classify(path)
    if verdict:
        return False, verdict, metrics
    sh = sharpness(_thumb(path))
    if sh < min_sharp:
        return False, "not_crisp", {"sharpness": round(sh, 1)}
    metrics = {"size": [w, h], "sharpness": round(sh, 1)}
    if min_faint > 0:
        fa = faintness(path)
        metrics["faintness"] = round(fa, 3)
        if fa < min_faint:
            return False, "damage_too_obvious", metrics
    return True, None, metrics


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_seen(out_dir):
    """Hashes already present, so re-runs extend the corpus instead of
    duplicating it."""
    seen = set()
    prov = os.path.join(out_dir, "provenance.jsonl")
    if os.path.exists(prov):
        with open(prov) as f:
            for line in f:
                try:
                    seen.add(json.loads(line)["sha256"])
                except Exception:
                    pass
    return seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True,
                    choices=["wikimedia", "openverse", "urls"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--pack", default="faint", choices=sorted(QUERY_PACKS))
    ap.add_argument("--queries", default=None,
                    help="comma-separated queries, overrides --pack")
    ap.add_argument("--urls", default=None, help="url list for --source urls")
    ap.add_argument("--limit", type=int, default=200, help="max images kept")
    ap.add_argument("--per-query", type=int, default=50)
    ap.add_argument("--min-side", type=int, default=512)
    ap.add_argument("--min-sharp", type=float, default=60.0,
                    help="Laplacian variance floor — the 'crisp' gate")
    ap.add_argument("--min-faint", type=float, default=0.0,
                    help="0 disables; ~0.45 keeps only subtle damage")
    ap.add_argument("--allow-any-licence", action="store_true",
                    help="keep images whose licence is not on the reuse "
                         "allowlist (still recorded verbatim)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    sess = _session()
    seen = load_seen(args.out)
    prov_path = os.path.join(args.out, "provenance.jsonl")
    kept = 0
    rejected = {}

    queries = ([q.strip() for q in args.queries.split(",")] if args.queries
               else QUERY_PACKS[args.pack])
    if args.source == "urls":
        if not args.urls:
            ap.error("--source urls requires --urls FILE")
        candidates = source_urls(sess, args.urls, args.limit * 4)
        queries = ["(url list)"]
        streams = [(queries[0], candidates)]
    else:
        fn = {"wikimedia": source_wikimedia, "openverse": source_openverse}[args.source]
        streams = [(q, fn(sess, q, args.per_query)) for q in queries]

    print(f"source={args.source} pack={args.pack} queries={len(queries)} "
          f"target={args.limit}")
    with open(prov_path, "a") as prov:
        for query, stream in streams:
            if kept >= args.limit:
                break
            for item in stream:
                if kept >= args.limit:
                    break
                url = item.get("image_url")
                if not url:
                    continue
                lic = (item.get("licence") or "").strip()
                if not args.allow_any_licence and args.source != "urls":
                    if not licence_ok(lic):
                        key = f"licence_not_allowed[{lic or 'none'}]"
                        rejected[key] = rejected.get(key, 0) + 1
                        continue
                if args.dry_run:
                    print(f"  would fetch [{lic}] {url[:90]}")
                    kept += 1
                    continue
                r = _get(sess, url)
                if not r or not r.content:
                    rejected["fetch_failed"] = rejected.get("fetch_failed", 0) + 1
                    continue
                ext = os.path.splitext(url.split("?")[0])[1].lower()
                if ext not in (".jpg", ".jpeg", ".png", ".webp"):
                    ext = ".jpg"
                tmp = os.path.join(args.out, f".tmp{ext}")
                with open(tmp, "wb") as f:
                    f.write(r.content)

                ok, reason, metrics = accept(tmp, args.min_side,
                                             args.min_sharp, args.min_faint)
                if not ok:
                    rejected[reason] = rejected.get(reason, 0) + 1
                    os.remove(tmp)
                    continue
                digest = sha256(tmp)
                if digest in seen:
                    rejected["duplicate"] = rejected.get("duplicate", 0) + 1
                    os.remove(tmp)
                    continue
                seen.add(digest)
                name = f"{args.source}_{digest[:16]}{ext}"
                os.rename(tmp, os.path.join(args.out, name))
                prov.write(json.dumps({
                    "file": name, "sha256": digest, "source": args.source,
                    "query": query, "image_url": url,
                    "page_url": item.get("page_url", ""),
                    "licence": lic or "unverified",
                    "licence_url": item.get("licence_url", ""),
                    "author": item.get("author", ""),
                    "title": item.get("title", ""),
                    **metrics,
                }) + "\n")
                prov.flush()
                kept += 1
                if kept % 10 == 0:
                    print(f"  kept {kept}/{args.limit}")

    print(f"\nkept {kept} -> {args.out}")
    if rejected:
        print("rejected:")
        for k, v in sorted(rejected.items(), key=lambda kv: -kv[1]):
            print(f"  {k:24s} {v}")
    print(f"provenance -> {prov_path}")


if __name__ == "__main__":
    main()
