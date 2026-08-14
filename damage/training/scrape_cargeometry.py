"""Harvest vehicle body-geometry records from cargeometry.org, with provenance.

WHY THIS EXISTS
The damage pipeline can only turn a scratch measured in PIXELS into one measured
in MILLIMETRES if it knows the true size of the panel it is looking at. It can
only call a panel "misaligned" if it knows what the factory shut-line should be.
And damage/fusion.py can only pin a finding onto a 3D model if the model is
anchored to real dimensions. cargeometry.org is a catalogue of factory body-
geometry documentation (chassis datums, upper-body and underbody datasheets,
diagonal measurements) covering ~3.4k vehicles, which is the densest index of
that material on the open web.

WHAT IS ACTUALLY THERE — READ THIS BEFORE EXPECTING NUMBERS
The dimension pages carry NO measurement tables in HTML. Every page is a product
listing: an identity (make / model / chassis code / year range), a prose
description of which datasheets the archive contains, a price in USD, and 15-35
low-resolution JPEG "data sample" pages from the archive. The millimetre values
live inside the paid download only. So this scraper deliberately harvests the
CATALOGUE LAYER — identity, coverage flags, price, sample-image URLs — and is
honest about it. It does not attempt to defeat the paywall, and it does not OCR
the sample images: they are the vendor's product shown as a preview, they are
watermarked, and at ~450 px wide the digits in their tables are not legibly
recoverable anyway. Whether to buy archives and parse them is the owner's call;
this tool tells him exactly what he would be buying, per vehicle.

    measurement_source == "paid_download"   on every row. Nothing is inferred.

JOINING. Rows are shaped to join `cargeometry_catalog_full` on
(make, model, chassis_code, year_start, year_end), with `url` carried on every
row as the tiebreaker and audit trail. Year fields are ints; chassis_code is the
parenthesised or bare type designation from the title, uppercased, or "".

UNITS. Every numeric field names its unit (length_mm, price_usd). A field whose
unit cannot be established is not emitted. Where a page ever does carry an HTML
table, parse_measurement_tables() records each cell with the unit it was labelled
with and NEVER converts silently.

POLITENESS. robots.txt permits these pages (only /engine/go.php and
/engine/download.php are disallowed for *, and this tool touches neither; GPTBot,
SemrushBot and AhrefsBot are blocked outright and this is none of them). One
request every --delay seconds, default 3.0, a descriptive User-Agent, and a HARD
STOP on any 403 or 429 — a small site gets the benefit of the doubt.

RESUMABILITY. Sessions here get reclaimed mid-run, so an interrupted job must
never restart from zero. Every completed page is appended to rows.jsonl as it
lands and its URL recorded in the done-set read back at startup; raw HTML is
cached under cache/ so a re-parse costs no requests at all (--reparse).

    python scrape_cargeometry.py --sitemap-only --out cg
    python scrape_cargeometry.py --out cg --limit 20 --dry-run
    python scrape_cargeometry.py --out cg --limit 20 --kind body-dimensions
    python scrape_cargeometry.py --out cg --reparse          # no network
"""
import argparse
import hashlib
import html as html_mod
import json
import os
import re
import sys
import time

BASE = "https://cargeometry.org"
SITEMAP = f"{BASE}/sitemap.xml"

UA = ("triposr-damage-research/1.0 (vehicle body-geometry reference for a "
      "damage-measurement tool; contact via repository) python-requests")

# robots.txt Disallow for User-agent: * — never request these, and assert it in
# code rather than trusting the caller to remember.
FORBIDDEN = ("/engine/go.php", "/engine/download.php")


class Stop(Exception):
    """Raised on 403/429 — the site has asked us to stop, so we stop."""


# --- page kinds -------------------------------------------------------------
# The catalogue mixes three document types under one sitemap. They are not
# interchangeable: a body-dimensions page is the datum/measurement archive, a
# collision or body-repair-manual page is the procedural manual (sectioning
# points, panel replacement) which is what `collision_url` in the existing
# catalogue points at. Both matter, for different reasons, so both are kept and
# labelled instead of one being filtered away.
KINDS = {
    "body-dimensions": "body_dimensions",
    "collision-repair-manual": "collision_repair_manual",
    "collision-shop-manual": "collision_repair_manual",
    "body-repair-manual": "body_repair_manual",
    "body-shop-manual": "body_repair_manual",
    "bodyshop-manual": "body_repair_manual",
    "repair-manual": "repair_manual",
}


def classify_url(url):
    slug = url.rsplit("/", 1)[-1]
    # Longest token first, so "collision-repair-manual" is not shadowed by the
    # substring "repair-manual".
    for token in sorted(KINDS, key=len, reverse=True):
        if token in slug:
            return KINDS[token]
    return "other"


def _session():
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "text/html,application/xml"})
    return s


def _get(sess, url, tries=3, timeout=25):
    """GET with bounded backoff, and an unconditional stop on 403/429.

    Bounded like scrape_images._get: a page that will not load is worth a few
    seconds, not minutes. The difference here is 403/429 — on an image CDN those
    are noise, on a small independent site they are the operator telling us to
    go away, so they raise Stop and end the run rather than being retried.
    """
    if any(f in url for f in FORBIDDEN):
        raise Stop(f"refusing robots.txt-disallowed path: {url}")
    delay = 3
    for attempt in range(tries):
        try:
            r = sess.get(url, timeout=timeout)
        except Exception:
            if attempt == tries - 1:
                return None
            time.sleep(delay); delay = min(delay * 2, 12)
            continue
        if r.status_code in (403, 429):
            raise Stop(f"HTTP {r.status_code} on {url} — stopping immediately")
        if r.status_code == 200:
            return r
        if r.status_code in (500, 502, 503, 504) and attempt < tries - 1:
            time.sleep(delay); delay = min(delay * 2, 12)
            continue
        if r.status_code != 404:
            print(f"    [http {r.status_code}] {url[:80]}", file=sys.stderr)
        return None
    return None


# --- sitemap ----------------------------------------------------------------

def fetch_sitemap(sess, cache_path=None):
    """(url, lastmod) for every article, from the published sitemap.

    Using the sitemap rather than crawling category pages is both the polite
    option and the correct one: it is one request for the whole index, it is
    what the operator published for this purpose, and it removes any need to
    guess URL patterns (the make segment is NOT uniform — 'audi-dimension' and
    'bentley-dimension' sit next to bare 'bmw' and 'toyota').
    """
    xml = None
    if cache_path and os.path.exists(cache_path):
        xml = open(cache_path, encoding="utf-8").read()
    else:
        r = _get(sess, SITEMAP)
        if not r:
            return []
        xml = r.text
        if cache_path:
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(xml)
    out = []
    for m in re.finditer(r"<url>\s*<loc>([^<]+)</loc>(?:\s*<lastmod>"
                         r"([^<]*)</lastmod>)?", xml):
        loc, lastmod = m.group(1).strip(), (m.group(2) or "").strip()
        if loc.endswith(".html"):
            out.append((loc, lastmod))
    return out


# --- identity parsing -------------------------------------------------------

MAKE_FIX = {
    "alfa-romeo": "Alfa Romeo", "land-rover": "Land Rover",
    "great-wall": "Great Wall", "rolls-royce": "Rolls Royce",
    "li-xiang": "Li Xiang", "bmw": "BMW", "gmc": "GMC", "byd": "BYD",
    "mg": "MG", "jac": "JAC", "vinfast": "VinFast", "ssangyong": "SsangYong",
    "saic": "Saic", "aito": "Aito",
}

# Title shape: "<Make> <Model> (<Chassis>) <y1>-<y2> <Document type>"
# The chassis code is often but not always parenthesised, the dash is sometimes
# an en-dash, the year range is sometimes glued together ("19972002"), and an
# open-ended range reads "from 2022" — hence the optional filler between the
# chassis parenthesis and the first year, without which "Daihatsu Atrai & Hijet
# Cargo (S700 S710) from 2022" loses its chassis code and keeps "from" in the
# model.
_TITLE_RE = re.compile(
    r"^(?P<head>.*?)\s*"
    r"(?:\((?P<paren>[^)]*)\)\s*)?"
    r"(?P<filler>(?:from|since|starting)\s+)?"
    r"(?P<y1>(?:19|20)\d{2})\s*(?:[-–—]\s*)?(?P<y2>(?:19|20)\d{2})?\s*"
    r"(?P<doc>.*)$")


def parse_identity(title, url):
    """(make, model, chassis_code, year_start, year_end) — the join key.

    Deliberately conservative: an unparseable chassis code becomes "" rather
    than a guess, because a wrong chassis code joins two different cars together
    and that is worse than a missing one.
    """
    make_slug = url.split("/")[3] if url.count("/") > 3 else ""
    make_slug = re.sub(r"-dimension$", "", make_slug)
    make = MAKE_FIX.get(make_slug,
                        " ".join(w.capitalize() for w in make_slug.split("-")))

    m = _TITLE_RE.match(title.strip())
    if not m:
        return make, title.strip(), "", None, None
    head = m.group("head").strip(" -–—")
    chassis = (m.group("paren") or "").strip()
    y1 = int(m.group("y1"))
    y2 = int(m.group("y2")) if m.group("y2") else None

    # Strip the make off the front of the head to leave the model.
    model = head
    if make and head.lower().startswith(make.lower()):
        model = head[len(make):].strip()
    # Some titles carry the chassis code bare: "Alfa Romeo 156 932A 1997-2002".
    if not chassis:
        mm = re.search(r"\s([A-Z0-9]{2,}(?:[- ][A-Z0-9]{2,})*)$", model)
        if mm and any(c.isdigit() for c in mm.group(1)):
            chassis, model = mm.group(1), model[:mm.start()].strip()
    chassis = re.sub(r"^(?:Type|Chassis|Code)\s+", "", chassis, flags=re.I)
    return make, model.strip(), chassis.strip().upper(), y1, y2


# --- page parsing -----------------------------------------------------------

_TAG = re.compile(r"(?s)<[^>]+>")


def _text(fragment):
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", fragment)
    s = re.sub(r"(?is)<br\s*/?>|</(p|div|li|tr|h\d)>", "\n", s)
    s = html_mod.unescape(_TAG.sub(" ", s))
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


# Coverage flags. The description prose is the only free statement of WHAT the
# paid archive contains, and the distinctions in it are exactly the ones the
# damage pipeline cares about — so they are lifted into booleans rather than
# left as text a downstream query would have to grep.
COVERAGE = {
    "has_upperbody_datasheet": r"upper\s*body",
    "has_underbody_datasheet": r"under\s*body",
    "has_chassis_diagrams": r"chassis diagram",
    "has_pillar_widths": r"pillar width",
    "has_door_dimensions": r"\bdoor\b",
    "has_windshield_dimensions": r"windshield|windscreen",
    "has_rear_window_dimensions": r"rear window",
    "has_diagonal_measurements": r"diagonal",
    "has_decklid_measurements": r"deck\s*lid",
    "has_centerline_widths": r"centerline|centre\s*line",
    "has_edge_of_hole_option": r"edge-?of-?hole",
    "has_center_of_hole_option": r"cent(?:er|re)-?of-?hole",
    "has_measurement_points": r"measurement point|reference point|datum",
    "has_body_repair_procedures": r"repair manual|sectioning|panel replacement",
}

_UNIT_RE = re.compile(r"\b(mm|millimet|inch|in\.|\bcm\b)", re.I)


def parse_measurement_tables(body_html):
    """Any real HTML <table> on the page, cell by cell, with its stated unit.

    As of this writing no dimension page carries one — the numbers are inside
    the paid archive — so this normally returns []. It is here because the
    existing catalogue has a `tables_found` column implying some page somewhere
    does, and because if the site ever publishes tables this must capture them
    WITH units rather than as bare floats. Unit is taken only from a header or
    the cell itself; an unlabelled number is recorded with unit None and is
    never assumed to be millimetres.
    """
    tables = []
    for tm in re.finditer(r"(?is)<table[^>]*>(.*?)</table>", body_html):
        raw = tm.group(1)
        rows = []
        for rm in re.finditer(r"(?is)<tr[^>]*>(.*?)</tr>", raw):
            cells = [_text(c) for c in
                     re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", rm.group(1))]
            if any(cells):
                rows.append(cells)
        if not rows:
            continue
        blob = " ".join(" ".join(r) for r in rows)
        um = _UNIT_RE.search(blob)
        unit = None
        if um:
            u = um.group(1).lower()
            unit = {"millimet": "mm", "inch": "in", "in.": "in"}.get(u, u)
        tables.append({"header": rows[0], "rows": rows[1:],
                       "unit_declared": unit, "n_rows": len(rows) - 1})
    return tables


def parse_page(url, html, lastmod=""):
    """One normalised record from one page's raw HTML."""
    title = ""
    tm = re.search(r'<meta property="og:title" content="([^"]*)"', html)
    if tm:
        title = html_mod.unescape(tm.group(1)).strip()
    if not title:
        tm = re.search(r"(?is)<title>(.*?)</title>", html)
        title = html_mod.unescape(tm.group(1)).split("»")[0].strip() if tm else ""

    desc = ""
    dm = re.search(r'<meta name="description" content="([^"]*)"', html)
    if dm:
        desc = html_mod.unescape(dm.group(1)).strip()

    # The article body, from the start of the post to the story_tools div that
    # closes it. Two openers are tried: DLE's classic .full-text, and the
    # <article class="... fullstory"> this site actually serves. The second was
    # added after the first silently stopped matching: the fall-back to the
    # whole document is NOT harmless, because the page's "Related News" block
    # lists OTHER vehicles' "... Body repair manual" titles, and those set
    # has_body_repair_procedures on 91% of rows that should not have it. So the
    # fall-back now also trims everything from the related-posts footer on,
    # keeping a future template change noisy-but-scoped rather than wrong.
    bm = (re.search(r'(?is)<div class="full-text[^"]*"[^>]*>(.*?)'
                    r'<div class="story_tools', html)
          or re.search(r'(?is)<article[^>]*class="[^"]*fullstory[^"]*"[^>]*>'
                       r'(.*?)<div class="story_tools', html))
    if bm:
        body_html = bm.group(1)
    else:
        body_html = re.split(r'(?is)<div class="fullstory_foot|Related News',
                             html)[0]
    body_text = _text(body_html)

    price = None
    pm = re.search(r"Price:\s*\$\s*([\d,]+(?:\.\d+)?)", body_text)
    if pm:
        price = float(pm.group(1).replace(",", ""))

    # Sample images: the free preview pages of the paid archive. Recorded as
    # URLs and counted, NOT downloaded — they are the vendor's product, they are
    # watermarked, and at ~450 px their tables are not legibly recoverable.
    imgs = []
    # DLE marks each inserted image as <!--dle_image_begin:<url>|...-->. The
    # terminator is the pipe, NOT the first hyphen — an early version stopped at
    # the hyphen in the "/2024-06/" date folder and produced 42 truncated,
    # duplicated URLs for a page with 30 images.
    for m in re.finditer(r"<!--dle_image_begin:([^|>]+)\|", body_html):
        u = m.group(1).strip()
        if u not in imgs:
            imgs.append(u)
    for m in re.finditer(r'<img[^>]+src="(/uploads/posts/[^"]+)"', body_html):
        u = BASE + m.group(1)
        u = u.replace("/medium/", "/")
        if u not in imgs:
            imgs.append(u)
    imgs = [i for i in imgs if "buyitem" not in i]

    og_img = ""
    om = re.search(r'<meta property="og:image" content="([^"]*)"', html)
    if om:
        og_img = om.group(1)

    views = None
    vm = re.search(r'title="Views:\s*(\d+)"', html)
    if vm:
        views = int(vm.group(1))

    post_id = None
    im = re.search(r"/(\d+)-", url.rsplit("/", 1)[-1])
    if im:
        post_id = int(im.group(1))
    else:
        im = re.match(r"^(\d+)-", url.rsplit("/", 1)[-1])
        post_id = int(im.group(1)) if im else None

    make, model, chassis, y1, y2 = parse_identity(title, url)
    tables = parse_measurement_tables(body_html)
    hay = f"{title} {desc} {body_text}".lower()

    rec = {
        # --- join key -----------------------------------------------------
        "make": make, "model": model, "chassis_code": chassis,
        "year_start": y1, "year_end": y2,
        "url": url,
        # --- identity -----------------------------------------------------
        "post_id": post_id, "title": title, "page_kind": classify_url(url),
        "description": desc,
        # --- commercial ---------------------------------------------------
        "price_usd": price,
        "paywalled": price is not None,
        "measurement_source": "paid_download" if price is not None else "none",
        # --- what the archive contains (from the free description) ---------
        **{k: bool(re.search(p, hay)) for k, p in COVERAGE.items()},
        # --- free preview material ----------------------------------------
        "sample_image_count": len(imgs),
        "sample_image_urls": imgs,
        "preview_image_url": og_img,
        # --- numeric dimensions: absent from HTML, kept explicit -----------
        "length_mm": None, "width_mm": None, "height_mm": None,
        "wheelbase_mm": None, "track_front_mm": None, "track_rear_mm": None,
        "tables_found": len(tables),
        "measurement_tables": tables,
        # --- provenance ----------------------------------------------------
        "views": views,
        "sitemap_lastmod": lastmod,
        "source": "cargeometry.org",
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "html_sha256": hashlib.sha256(html.encode("utf-8",
                                                  "replace")).hexdigest(),
        "licence": "unverified — site states 'Copyright (c) 2010-2026 "
                   "Cargeometry All Rights Reserved'; see Terms of use",
    }
    return rec


# --- resumable state --------------------------------------------------------

def cache_name(url):
    return hashlib.sha256(url.encode()).hexdigest()[:24] + ".html"


def load_done(rows_path):
    """URLs already written. Read back at startup so an interrupted run — the
    normal case in this environment — resumes instead of refetching."""
    done = set()
    if os.path.exists(rows_path):
        with open(rows_path, encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line)["url"])
                except Exception:
                    pass
    return done


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--limit", type=int, default=20,
                    help="max pages to fetch this run")
    ap.add_argument("--kind", default="body-dimensions",
                    help="URL token filter, or 'all'")
    ap.add_argument("--make", default=None, help="restrict to one make slug")
    ap.add_argument("--delay", type=float, default=3.0,
                    help="seconds between requests (floor 2.0)")
    ap.add_argument("--spread", action="store_true",
                    help="sample evenly across the whole catalogue instead of "
                         "taking the first N (better structural coverage)")
    ap.add_argument("--sitemap-only", action="store_true")
    ap.add_argument("--reparse", action="store_true",
                    help="re-parse cached HTML, no network at all")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    delay = max(2.0, args.delay)
    os.makedirs(args.out, exist_ok=True)
    cache_dir = os.path.join(args.out, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    rows_path = os.path.join(args.out, "rows.jsonl")
    sm_cache = os.path.join(args.out, "sitemap.xml")

    sess = _session()
    try:
        entries = fetch_sitemap(sess, sm_cache)
    except Stop as e:
        print(f"STOP: {e}", file=sys.stderr)
        return 2
    if not entries:
        print("sitemap empty or unreachable", file=sys.stderr)
        return 1

    by_kind = {}
    for u, _ in entries:
        k = classify_url(u)
        by_kind[k] = by_kind.get(k, 0) + 1
    makes = sorted({u.split("/")[3] for u, _ in entries})
    print(f"sitemap: {len(entries)} article pages, {len(makes)} makes")
    for k, v in sorted(by_kind.items(), key=lambda kv: -kv[1]):
        print(f"  {v:5d}  {k}")
    if args.sitemap_only:
        with open(os.path.join(args.out, "sitemap_index.json"), "w") as f:
            json.dump({"total": len(entries), "by_kind": by_kind,
                       "makes": makes,
                       "urls": [{"url": u, "lastmod": lm, "kind": classify_url(u)}
                                for u, lm in entries]}, f, indent=1)
        return 0

    todo = entries
    if args.kind != "all":
        todo = [(u, lm) for u, lm in todo if args.kind in u]
    if args.make:
        todo = [(u, lm) for u, lm in todo if f"/{args.make}/" in u]

    if args.reparse:
        done, targets = set(), todo
    else:
        done = load_done(rows_path)
        targets = [(u, lm) for u, lm in todo if u not in done]
        print(f"{len(done)} already done, {len(targets)} remaining "
              f"(kind={args.kind})")
        if args.spread and len(targets) > args.limit:
            step = len(targets) / float(args.limit)
            targets = [targets[int(i * step)] for i in range(args.limit)]

    fetched = written = 0
    stopped = None
    with open(rows_path, "a", encoding="utf-8") as out:
        for url, lastmod in targets:
            if written >= args.limit:
                break
            cpath = os.path.join(cache_dir, cache_name(url))
            html = None
            if os.path.exists(cpath):
                html = open(cpath, encoding="utf-8", errors="replace").read()
            elif args.reparse:
                continue
            elif args.dry_run:
                print(f"  would fetch {url}")
                written += 1
                continue
            else:
                try:
                    r = _get(sess, url)
                except Stop as e:
                    stopped = str(e)
                    break
                time.sleep(delay)
                if not r:
                    continue
                html = r.text
                with open(cpath, "w", encoding="utf-8") as cf:
                    cf.write(html)
                fetched += 1
            if url in done:
                continue
            try:
                rec = parse_page(url, html, lastmod)
            except Exception as e:
                print(f"  parse failed {url}: {type(e).__name__}: {e}",
                      file=sys.stderr)
                continue
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()          # flush per row: the container can vanish
            os.fsync(out.fileno())
            done.add(url)
            written += 1
            if written % 5 == 0:
                print(f"  {written} rows  (fetched {fetched})")

    print(f"\nwrote {written} rows ({fetched} network fetches) -> {rows_path}")
    if stopped:
        print(f"STOPPED EARLY: {stopped}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
