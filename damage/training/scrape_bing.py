"""Bing image-search source for the car-damage corpus — and a hard warning.

WRITTEN, MEASURED, AND FOUND NOT CURRENTLY USABLE. Keep the code; do not trust
the results without running --selftest first. What follows is what the
measurement actually showed, so the next person does not repeat it.

WHAT WORKS
  The transport works. GET https://www.bing.com/images/search?q=... with a
  desktop browser User-Agent returns HTTP 200 from this container, with genuine
  Bing response headers (X-EventID, MUID cookie), and image metadata is
  extractable from the `m="{...}"` attribute on each `a.iusc` result tile.
  Roughly 20-60 distinct image URLs come back per query.

WHAT DOES NOT WORK — THE PART THAT MATTERS
  The URLs are not answers to the query. Measured 2026-08-13 over the ten
  damage-class queries: 303 distinct image URLs, of which ONE (0.3%) had a
  title or source page mentioning anything related to its query.

    "car door dent"      -> Darryl Starbird Rod & Custom show-car photos
    "car rust corrosion" -> byte-identical result set to "car door dent"
    "car paint chip"     -> byte-identical result set to both of the above
    "cracked windscreen" -> an Indonesian song-lyrics blog
    "bumper scuff"       -> "White Pattern Backgrounds" wallpaper
    "hail damage car"    -> hairstyle sites

  The <title> of the page echoes the query back ("car door dent - Search
  Images"), which is what makes this failure so easy to miss: every cheap
  smoke test passes. The response looks like a SERP, parses like a SERP, and
  yields a plausible count of image URLs. Only reading the per-result titles
  shows the grid is decoy or stale content. This is bot mitigation against a
  datacenter IP, not a parsing bug — three distinct queries returning the same
  35 URLs in the same order cannot be a real ranking.

  Sending a fuller browser header set and warming cookies on the homepage first
  made it worse, not better (zero parsable results).

  So `count_of_urls_extracted` IS NOT A MEASURE OF SUCCESS for this source. The
  original assessment of "works, 32 URLs for one query" was a false positive
  produced by exactly that metric. `_relevance` below exists to make the real
  failure visible, and --selftest asserts on it.

DOWNLOAD + FILTER EVIDENCE
  40 of these images were downloaded and run through clean_dataset.classify():
  27 (67.5%) passed — 12 annotation_suspect, 1 burned_in_annotation, and 3
  fetch failures were the rejects. That 67.5% "survival rate" is meaningless
  and actively misleading: the survivors were mirror-polished restored show
  cars and abstract white wallpaper. The contamination filter screens for
  burned-in boxes, stock watermarks and dead pixels. IT DOES NOT SCREEN FOR
  RELEVANCE, and it never claimed to. Nothing downstream will catch an
  undamaged car filed under "car door dent"; it will just teach the model that
  a flawless Ford Fairlane is a dent.

OTHER ENGINES (measured same day)
  DuckDuckGo  i.js still HTTP 403. The vqd token is obtainable from the HTML,
              the JSON endpoint rejects the call. Unchanged, not transient.
  Google      No public API. SERP scraping breaks their terms and blocks
              datacenter IPs. Not attempted. See scrape_images.py's note.

EVEN IF IT WORKED: CLASSIFIER ONLY
  Search results carry no bounding boxes and no licence metadata. The detector
  pipeline refuses unboxed images on purpose — an unannotated photo of a dented
  door teaches the detector that visible damage is background. So this source
  can only ever feed an image CLASSIFIER, where the query string is the class
  label, and only then if the returned images actually match the query. The
  licence is recorded as "unverified" and never guessed; scrape_images.py's
  licence gate will reject every one of these unless --allow-any-licence is
  passed, which is the correct default.

    python scrape_bing.py --selftest
    python scrape_bing.py --query "car door dent" --limit 20
"""
import argparse
import html
import json
import re
import sys
import time
import urllib.parse

# A research User-Agent gets a different (worse) response here than a browser
# one, so this source cannot share scrape_images.UA.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# Each result tile is <a class="iusc" ... m="{...json...}">. Match the attribute
# by its content rather than by its position after class="iusc": the attribute
# ORDER changed between two responses during measurement, and an order-dependent
# pattern silently returned zero results rather than failing.
_TILE = re.compile(r'm="(\{[^"]*?murl[^"]*?\})"')

# Deliberately NOT the murl&quot; regex. That one truncates any URL containing
# an ampersand at the first &, and gives no access to the title, which is the
# only field that reveals the decoy problem.

_STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "with", "and", "car",
         "auto", "vehicle", "close", "up", "photo", "image"}


def _session():
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9"})
    return s


def _parse_tiles(text):
    """Every result tile on a Bing image SERP, as dicts."""
    out = []
    for m in _TILE.finditer(text):
        try:
            d = json.loads(html.unescape(m.group(1)))
        except Exception:
            continue          # one malformed tile must not kill the page
        if d.get("murl"):
            out.append(d)
    return out


def _relevance(query, tiles):
    """Fraction of tiles whose own title/page mentions a query word, 0-1.

    The single most important number this module produces. Bing will happily
    return a full grid of unrelated images under a page titled with your query;
    result COUNT cannot distinguish that from a real answer, and this can.
    Uses each result's own title and source URL — Bing's text, not ours.
    """
    words = [w for w in re.findall(r"[a-z]{4,}", query.lower())
             if w not in _STOP]
    if not words or not tiles:
        return 0.0
    hits = 0
    for t in tiles:
        hay = ((t.get("t") or "") + " " + (t.get("purl") or "")).lower()
        # prefix match so "scratch" catches "scratches", "corros" -> "corrosion"
        if any(w[:6] in hay for w in words):
            hits += 1
    return hits / len(tiles)


def search_bing(sess, query, limit=35, min_relevance=0.0, verbose=True):
    """(tiles, relevance) for one query, paginated as far as Bing allows.

    Pagination note: Bing accepts &first=N but MEASURED AS INERT here — first=36
    returned the identical 35 URLs as first=1, so the practical ceiling is one
    page, ~35 URLs per query. The loop stops as soon as a page adds nothing new
    rather than assuming a page size.
    """
    tiles, seen = [], set()
    for first in range(1, max(limit, 1) + 70, 35):
        url = ("https://www.bing.com/images/search?q="
               + urllib.parse.quote(query)
               + f"&first={first}&count=35&form=HDRSC2")
        try:
            r = sess.get(url, timeout=25)
        except Exception as e:
            if verbose:
                print(f"    [bing] {type(e).__name__} on {query!r}",
                      file=sys.stderr)
            break
        if r.status_code != 200:
            if verbose:
                print(f"    [bing http {r.status_code}] {query!r}",
                      file=sys.stderr)
            break
        new = [t for t in _parse_tiles(r.text) if t["murl"] not in seen]
        for t in new:
            seen.add(t["murl"])
        if not new:
            break                     # ceiling reached; asking again just loops
        tiles.extend(new)
        if len(tiles) >= limit:
            break
        time.sleep(2.0)               # be polite

    rel = _relevance(query, tiles)
    if verbose and tiles and rel < 0.15:
        print(f"    [bing] WARNING {query!r}: {len(tiles)} URLs but only "
              f"{rel:.0%} mention the query — results look like decoy content, "
              f"NOT an answer. Do not ingest.", file=sys.stderr)
    if rel < min_relevance:
        return [], rel
    return tiles[:limit], rel


def source_bing(sess, query, limit, min_relevance=0.15):
    """Bing image search, shaped like scrape_images.py's source_* generators.

    Yields the same keys as source_wikimedia / source_openverse so it can be
    dropped into that pipeline. Licence is ALWAYS "unverified" — Bing exposes
    no licence metadata, and inventing a tag here is the exact mistake that
    contaminated the Roboflow corpus.

    min_relevance defaults to 0.15 and yields NOTHING below it. A source that
    is confidently returning wallpaper for "bumper scuff" should produce an
    empty stream, not 35 quietly-wrong training images.
    """
    tiles, rel = search_bing(sess, query, limit, min_relevance=min_relevance)
    for t in tiles:
        yield {
            "image_url": t.get("murl"),
            "page_url": t.get("purl") or "",
            "licence": "unverified",      # never guessed. see module docstring
            "licence_url": "",
            "author": "",
            "title": t.get("t") or "",
            "width": t.get("mw"), "height": t.get("mh"),
        }


DAMAGE_QUERIES = [
    "light faint car scratch", "deep scratch to primer car", "car door dent",
    "bumper scuff", "cracked windscreen", "broken headlight car",
    "car rust corrosion", "hail damage car", "car paint chip",
    "panel gap misalignment car",
]


def selftest(sess):
    """Is Bing answering the query, or serving decoys? Exit 1 if decoys.

    Also checks whether different queries return the SAME results, which is the
    cleanest possible proof that ranking is not happening.
    """
    heads, rels = {}, {}
    for q in DAMAGE_QUERIES[:5]:
        tiles, rel = search_bing(sess, q, 35, verbose=False)
        rels[q] = rel
        heads[q] = tuple(t["murl"] for t in tiles[:5])
        print(f"  {q:32s} urls={len(tiles):3d}  relevance={rel:.0%}")
        time.sleep(2)
    dupes = [(a, b) for i, a in enumerate(heads) for b in list(heads)[i + 1:]
             if heads[a] and heads[a] == heads[b]]
    for a, b in dupes:
        print(f"  IDENTICAL RESULTS: {a!r} == {b!r}")
    mean = sum(rels.values()) / len(rels) if rels else 0.0
    print(f"\n  mean relevance {mean:.0%}")
    if mean < 0.15 or dupes:
        print("  VERDICT: Bing is NOT answering these queries. Do not ingest.")
        return 1
    print("  VERDICT: results look query-relevant. Still classifier-only "
          "(no boxes, no licence).")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--query")
    ap.add_argument("--limit", type=int, default=20)
    # Must match source_bing's own default. An argparse default of 0.0 here
    # silently disabled the guard for every CLI user while the library default
    # looked safe — the CLI is the way this gets run, so it must not be the
    # lenient path. Pass --min-relevance 0 explicitly to inspect raw results.
    ap.add_argument("--min-relevance", type=float, default=0.15,
                    help="drop the whole query below this relevance "
                         "(default 0.15; pass 0 to dump everything for "
                         "inspection)")
    ap.add_argument("--selftest", action="store_true",
                    help="check whether Bing is answering queries at all")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    sess = _session()
    if args.selftest:
        sys.exit(selftest(sess))
    if not args.query:
        ap.error("--query is required (or use --selftest)")

    items = list(source_bing(sess, args.query, args.limit,
                             min_relevance=args.min_relevance))
    if args.json:
        print(json.dumps(items, indent=1))
    else:
        for it in items:
            print(f"[{it['licence']}] {it['title'][:58]:58s} {it['image_url']}")
    print(f"\n{len(items)} results for {args.query!r}", file=sys.stderr)


if __name__ == "__main__":
    main()
