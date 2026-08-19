#!/usr/bin/env python3
"""Source ONE clean, high-resolution photograph per named car, from this container.

Pixal3D is single-image, so every car we want needs one good photo: front
three-quarter if we can get it, >=2000px on the long edge, one car, unobstructed,
not liveried. Background does not matter -- rembg cuts it out.

WHAT WAS ACTUALLY MEASURED FROM THIS CONTAINER (2026-08-19). Read this before
"fixing" the pacing; the numbers are from real requests, not from documentation.

* The 429 wall is REAL but it is NOT what it looked like. Every wikimedia.org
  host shares ONE token bucket keyed on the egress IP -- and this container's
  egress IP (160.79.106.130, which Wikimedia's own error page prints back at
  you) is SHARED with other agent sessions. commons api.php, upload.wikimedia.org,
  api.wikimedia.org, en.wikipedia.org and wikidata.org all 429 together, and all
  recover together. So a 429 here is not "Wikimedia blocked us", it is "the
  bucket is momentarily empty" -- possibly because of somebody else.

* PACING FIXES IT. 12/12 consecutive 1280px thumb downloads succeeded with ZERO
  429s at a 10s interval sustained over 183s. The reported "3 of 5 with 25s
  delays" failure was a BURST problem, not a throughput ceiling.

* THE PENALTY ESCALATES, so never burst to find the edge. A 48-request burst at
  0.5-5s intervals took Retry-After from 37s to **600s**. One careless probe
  costs ten minutes of the whole shared IP's budget. DEFAULT_WM_INTERVAL below is
  deliberately conservative for that reason -- it is a courtesy to the other
  tenants as much as a throughput setting.

* DO NOT USE commons api.php FOR SEARCH. It is the strictest tier and it is the
  one that produced the original blocker. Openverse replaces it completely:
  api.openverse.org indexes 88.7M Wikimedia Commons images, is on a DIFFERENT
  IP budget, and hands back width/height/licence/attribution in the search
  response -- so discovery costs the Wikimedia bucket nothing at all. We only
  spend Wikimedia requests on bytes we have already decided we want.

* Openverse anon limits, read off its own response headers: 20/min burst,
  200/day sustained. Both are plenty when one search serves one car. A free API
  key (POST /v1/auth_tokens/register/) lifts it to 100/min, 10k/day -- it needs
  an email address, so it is the OWNER's to create, not ours to invent.

* size=large is the filter that matters, and category=photograph is a TRAP:
  with source=wikimedia it returns 0 results for every query tried, because
  Commons rows carry no category. size=large alone returns 4297x2639-class
  press-quality car photos. Verified on Toyota Yaris / Ford Focus / VW Golf /
  Nissan Qashqai / Vauxhall Corsa.

* DOWNLOAD THE ORIGINAL, NOT A CONSTRUCTED THUMB. Wikimedia now allowlists
  thumbnail widths and answers 400 "Use thumbnail sizes listed on
  https://w.wiki/GHai" for anything else. Measured on a real file: 1280 and 1920
  are accepted; 800, 1024, 1500, 2000, 2048, 2560 and 3000 all 400. Since we
  filter on Openverse's reported width >= MIN_LONG_EDGE anyway, the original URL
  is both simpler and always big enough. 1920 is kept only as a fallback for
  originals too large to be worth pulling.

* A CONFORMING User-Agent IS MANDATORY, on both hosts. `python-requests/2.31.0`
  gets 403 from Wikimedia's HAProxy before it ever reaches the rate limiter, and
  bare `Python-urllib/3.11` gets 403 from Openverse. That 403 looks exactly like
  a policy block and is not one.

* FLICKR IS NOT AN ALTERNATIVE for this job, measured: Openverse's Flickr rows
  index at 500-1024px, and constructing the larger static-CDN suffixes
  (_h/_k/_3k/_4k) returns 403 or 410 Gone -- the big sizes do not exist. The
  Flickr CDN itself is unthrottled here, it just has nothing large to serve.

LICENCE IS RECORDED, NEVER ENFORCED (owner instruction, CLAUDE.md). Every
candidate carries whatever licence string its source states, verbatim, in a
plain field. Nothing in this file branches on it. Do not add a gate.

Usage:
  photo_source.py "Toyota Yaris XP130" "Ford Focus Mk3" --out /tmp/photos
  photo_source.py --list cars.txt --out /tmp/photos --per 3 --cutout
  photo_source.py --list cars.txt --out /tmp/photos        # re-run: resumes
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = ("ExpertCarCheck-PhotoSourcer/0.1 "
      "(https://github.com/alamk123/expertcarcheck; 3D catalogue ingest) "
      "urllib/3.11")

OPENVERSE = "https://api.openverse.org/v1/images/"

# Openverse anon burst is 20/min -> 3.0s is the floor; 3.5s leaves headroom.
DEFAULT_OV_INTERVAL = 3.5
# 10s was measured clean (12/12, zero 429) over 183s. The bucket is shared with
# other sessions, so this is a floor we ASK for, not one we are entitled to.
DEFAULT_WM_INTERVAL = 10.0

MIN_LONG_EDGE = 2000
# A car shot from 3/4 is landscape. Squares and portraits are badges, interiors,
# engine bays and detail crops far more often than they are usable cars.
MIN_ASPECT, MAX_ASPECT = 1.15, 2.60

# Junk the title can tell us about before we spend a download.
#
# ANCHORING. \b will not do: underscores and digits are everywhere in Commons
# filenames, so \btoy\b does not behave as expected inside "Yaris_toy_01". _L/_R
# treat a letter on either side as "inside a longer word" instead.
#
# BOTH EDGES ARE MANDATORY ON EVERY GROUP. The first draft of this regex applied
# _L only, and "toy" duly matched inside "TOYota" -- which silently rejected
# every Toyota in the test set. This is the same failure class CLAUDE.md records
# for nameplate_filter's bare digits: a short token is only safe when both its
# edges are pinned. If you add an alternative, put it INSIDE an existing
# {_L}(...){_R} group.
#
# TWO TOKENS ARE DELIBERATELY ABSENT, do not "complete" the list by adding them:
#   * "seat"  -- SEAT is a MARQUE (Ibiza, Leon). Interiors are already caught by
#                interior|dashboard|cockpit, so bare "seat" buys nothing and
#                would reject a whole marque.
#   * "cab"   -- "Double Cab" / "Single Cab" are body styles on every pickup in
#                the catalogue. "taxi" catches the thing we actually mean.
# And "racing" carries a negative lookahead because British Racing Green is a
# COLOUR that appears in perfectly good Jaguar and Aston titles.
_L = r"(?<![a-z])"
_R = r"(?![a-z])"
REJECT_TITLE = re.compile(
    # liveried / competition / service vehicles -- the brief excludes these
    rf"{_L}(rally|wrc|racing(?!\s+green)|races?|racecars?|nascar|drift|"
    rf"motorsport|police|polizei|politie|gendarmerie|taxis?|ambulances?|"
    rf"fire.?brigade|feuerwehr|military|army|driving.?school|liveried|livery|"
    rf"decals?|wrapped|adverts?){_R}"
    # not a whole exterior car
    rf"|{_L}(interiors?|dashboards?|cockpits?|engines?|motor.?bay|boot.?lid|"
    rf"gearbox|transmission|badges?|emblems?|logos?|headlamps?|headlights?|"
    rf"taillights?|tail.?lamps?|wheels?|alloys?|hubcaps?|steering|"
    rf"door.?cards?|grilles?){_R}"
    # not a real car
    rf"|{_L}(model.?cars?|diecast|die.?cast|miniature|toys?|scale.?model|lego|"
    rf"replicas?|renderings?|renders?|drawings?|sketch|blueprint|patent|"
    rf"wrecks?|wrecked|crash(ed|es)?|scrap(ped|yard)?|junk|rusty|rusted|"
    rf"abandoned|burnt|burned){_R}"
    rf"|{_L}(assembly.?line|factory|production.?line){_R}"
    rf"|{_L}(cutaways?|chassis|skeleton){_R}",
    re.I)

# View hints in the filename. Commons' prolific car contributors number their
# shots and name the angle; "front" in the title is the cheapest signal we have
# that we are getting a three-quarter rather than a tail-on.
FRONT_HINT = re.compile(r"(?<![a-z])(front|frontal|vorn|avant|delantera)", re.I)
REAR_HINT = re.compile(r"(?<![a-z])(rear|back|heck|arriere|trasera)", re.I)
SIDE_HINT = re.compile(r"(?<![a-z])(side|profile|seite|lateral)", re.I)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# --------------------------------------------------------------------------
# HTTP with per-host pacing that only ever gets MORE polite
# --------------------------------------------------------------------------
class Gate:
    """Per-host minimum interval that ratchets UP on 429 and never fully back.

    The ratchet is the whole point. A gate that relaxes back to its floor after
    one success will re-trip the limiter on the next slow patch, and on this
    shared IP each trip costs everybody -- the measured penalty went 37s -> 600s
    under exactly that pattern.
    """

    def __init__(self, floor):
        self.floor = floor
        self.interval = floor
        self.last = 0.0
        self.n429 = 0

    def wait(self):
        gap = time.time() - self.last
        if gap < self.interval:
            time.sleep(self.interval - gap)
        self.last = time.time()

    def penalise(self):
        self.n429 += 1
        self.interval = min(120.0, max(self.interval * 1.6, self.floor))

    def relax(self):
        # decay towards the floor, but never below it
        self.interval = max(self.floor, self.interval * 0.95)


_GATES = {}


def gate_for(url, wm_interval, ov_interval):
    host = urllib.parse.urlparse(url).netloc
    if host not in _GATES:
        if host.endswith("wikimedia.org") or host.endswith("wikipedia.org"):
            floor = wm_interval
        elif "openverse" in host:
            floor = ov_interval
        else:
            floor = 2.0
        _GATES[host] = Gate(floor)
    return _GATES[host]


def _lower_headers(h):
    """Header names are case-insensitive on the wire but dict() freezes the case.

    Varnish and envoy disagree about "Content-Type" vs "content-type" on the
    very same host depending on which tier answers, and a case-sensitive lookup
    would make every download report "not-an-image" instead of saving the file.
    """
    return {k.lower(): v for k, v in dict(h).items()}


def http_get(url, gate, timeout=180, tries=4, max_sleep=900):
    """GET with Retry-After-honouring backoff. Returns (status, headers, body).

    Headers come back lower-cased. Never raises on an HTTP status -- the caller
    logs the honest code. Only a transport failure after all tries comes back as
    status "EXC".
    """
    last = None
    for attempt in range(1, tries + 1):
        gate.wait()
        rq = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "application/json,image/*;q=0.9,*/*;q=0.5",
        })
        try:
            with urllib.request.urlopen(rq, timeout=timeout) as r:
                gate.relax()
                return r.status, _lower_headers(r.headers), r.read()
        except urllib.error.HTTPError as e:
            body = b""
            try:
                body = e.read()
            except Exception:
                pass
            if e.code == 429:
                gate.penalise()
                ra = e.headers.get("Retry-After")
                try:
                    nap = float(ra)
                except (TypeError, ValueError):
                    nap = gate.interval
                nap = min(max(nap, 1.0), max_sleep)
                log(f"    429 on {urllib.parse.urlparse(url).netloc} "
                    f"retry-after={ra} -> sleeping {nap:.0f}s "
                    f"(attempt {attempt}/{tries}, gate now {gate.interval:.1f}s)")
                if attempt < tries:
                    time.sleep(nap)
                    continue
            return e.code, _lower_headers(e.headers), body
        except Exception as e:                      # transport / TLS / timeout
            last = e
            if attempt < tries:
                time.sleep(min(30.0, 2 ** attempt))
                continue
    return "EXC", {}, str(last).encode()[:300]


# --------------------------------------------------------------------------
# Discovery -- Openverse only. api.php is deliberately not used; see docstring.
# --------------------------------------------------------------------------
def openverse_search(query, page_size, wm_interval, ov_interval, source="wikimedia"):
    """Return (candidates, error_or_None). Licence fields copied verbatim."""
    qs = urllib.parse.urlencode({
        "q": query,
        "page_size": str(page_size),
        "source": source,
        "size": "large",          # NB: do NOT add category=photograph -- 0 results
    })
    url = f"{OPENVERSE}?{qs}"
    st, hdrs, body = http_get(url, gate_for(url, wm_interval, ov_interval), timeout=60)
    if st != 200:
        return [], f"openverse-http-{st}"
    try:
        j = json.loads(body)
    except Exception as e:
        return [], f"openverse-badjson-{type(e).__name__}"
    out = []
    for it in j.get("results") or []:
        out.append({
            "openverse_id": it.get("id"),
            "title": it.get("title") or "",
            "url": it.get("url"),
            "width": it.get("width") or 0,
            "height": it.get("height") or 0,
            "source": it.get("source"),
            "provider": it.get("provider"),
            "creator": it.get("creator"),
            "creator_url": it.get("creator_url"),
            "foreign_landing_url": it.get("foreign_landing_url"),
            # ---- licence: recorded verbatim, never gated on (CLAUDE.md) ----
            "licence": it.get("license"),
            "licence_version": it.get("license_version"),
            "licence_url": it.get("license_url"),
            "attribution": it.get("attribution"),
        })
    return out, None


def score(cand, query):
    """Higher is better. Pure title/geometry heuristics -- no download needed."""
    t = cand["title"] or ""
    u = urllib.parse.unquote(cand["url"] or "")
    hay = f"{t} {u}"
    s = 0.0
    long_edge = max(cand["width"], cand["height"])
    s += min(long_edge, 6000) / 1000.0                  # bigger is better, capped
    if FRONT_HINT.search(hay):
        s += 4.0                                        # front 3/4 is the brief
    if REAR_HINT.search(hay):
        s -= 3.0
    if SIDE_HINT.search(hay):
        s -= 1.0
    # every query token present in the title is a strong relevance signal
    toks = [w for w in re.split(r"\W+", query.lower()) if len(w) > 1]
    hit = sum(1 for w in toks if w in hay.lower())
    s += 2.0 * hit / max(1, len(toks))
    ar = cand["width"] / cand["height"] if cand["height"] else 0
    if 1.35 <= ar <= 1.85:                              # typical clean car framing
        s += 1.5
    return s


def triage(cands, query, min_long_edge):
    """Split into (keep, dropped_with_reason). Reasons are logged honestly."""
    keep, dropped = [], []
    for c in cands:
        hay = f"{c['title']} {urllib.parse.unquote(c['url'] or '')}"
        m = REJECT_TITLE.search(hay)
        if m:
            dropped.append((c, f"title-reject:{m.group(0).lower()}"))
            continue
        le = max(c["width"], c["height"])
        if le < min_long_edge:
            dropped.append((c, f"too-small:{c['width']}x{c['height']}"))
            continue
        ar = c["width"] / c["height"] if c["height"] else 0
        if not (MIN_ASPECT <= ar <= MAX_ASPECT):
            dropped.append((c, f"aspect:{ar:.2f}"))
            continue
        c["score"] = round(score(c, query), 2)
        keep.append(c)
    keep.sort(key=lambda c: -c["score"])
    return keep, dropped


# --------------------------------------------------------------------------
# Download
# --------------------------------------------------------------------------
def fallback_thumb(orig, width=1920):
    """Commons thumb URL at an ALLOWLISTED width (1280/1920 measured OK).

    Only used when the original is too big to be worth pulling. Any other width
    answers 400 -- see the docstring.
    """
    pre, sep, rest = (orig or "").partition("/commons/")
    if not sep:
        return None
    parts = rest.split("/")
    if len(parts) != 3:
        return None
    a, ab, name = parts
    return f"{pre}/commons/thumb/{a}/{ab}/{name}/{width}px-{name}"


def download(cand, outdir, wm_interval, ov_interval, max_bytes):
    url = cand["url"]
    gate = gate_for(url, wm_interval, ov_interval)
    st, hdrs, body = http_get(url, gate)
    if st != 200 or not hdrs.get("content-type", "").startswith("image"):
        if st == 200:
            return None, f"not-an-image:{hdrs.get('content-type')}"
        # one shot at the allowlisted 1920px thumb before giving up
        alt = fallback_thumb(url)
        if alt:
            st2, h2, b2 = http_get(alt, gate)
            if st2 == 200 and h2.get("content-type", "").startswith("image"):
                st, hdrs, body = st2, h2, b2
            else:
                return None, f"http-{st}(thumb-{st2})"
        else:
            return None, f"http-{st}"
    if len(body) > max_bytes:
        return None, f"too-large:{len(body)}"
    ext = ".jpg"
    ct = hdrs.get("content-type", "")
    if "png" in ct:
        ext = ".png"
    elif "webp" in ct:
        ext = ".webp"
    sha = hashlib.sha256(body).hexdigest()
    fn = os.path.join(outdir, f"{cand['slug']}_{sha[:10]}{ext}")
    tmp = fn + ".part"
    with open(tmp, "wb") as f:
        f.write(body)
    os.replace(tmp, fn)
    cand["file"] = fn
    cand["bytes"] = len(body)
    cand["sha256"] = sha
    return fn, None


# --------------------------------------------------------------------------
# Optional quality check: rembg cutout + car pixel fraction
# --------------------------------------------------------------------------
def cutout_fraction(path, outdir):
    """Return (fraction, cutout_path, error). Import is lazy -- rembg is heavy."""
    try:
        from PIL import Image
        from rembg import remove, new_session
    except Exception as e:
        return None, None, f"rembg-import:{type(e).__name__}"
    try:
        global _RSESS
        try:
            _RSESS
        except NameError:
            _RSESS = new_session("birefnet-general")
        im = Image.open(path).convert("RGB")
        # cutting out at full 4000px costs minutes on CPU for no extra signal
        im.thumbnail((1600, 1600))
        cut = remove(im, session=_RSESS)
        alpha = cut.split()[-1]
        px = list(alpha.getdata())
        frac = sum(1 for p in px if p > 128) / float(len(px))
        cp = os.path.join(outdir, os.path.basename(path).rsplit(".", 1)[0] + "_cut.png")
        cut.save(cp)
        return round(frac, 4), cp, None
    except Exception as e:
        return None, None, f"rembg-fail:{type(e).__name__}:{str(e)[:80]}"


# --------------------------------------------------------------------------
# Resumable state
# --------------------------------------------------------------------------
def load_state(p):
    if os.path.exists(p):
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            log(f"  state file {p} unreadable -- starting fresh")
    return {}


def save_state(p, st):
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, indent=1, sort_keys=True)
    os.replace(tmp, p)          # atomic: a rollback mid-write cannot corrupt it


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cars", nargs="*", help='e.g. "Toyota Yaris XP130"')
    ap.add_argument("--list", help="file with one car description per line")
    ap.add_argument("--out", default="photos", help="output directory")
    ap.add_argument("--per", type=int, default=1, help="images to keep per car")
    ap.add_argument("--page-size", type=int, default=20,
                    help="Openverse results to consider per car")
    ap.add_argument("--min-long-edge", type=int, default=MIN_LONG_EDGE)
    ap.add_argument("--max-bytes", type=int, default=40_000_000)
    ap.add_argument("--wm-interval", type=float, default=DEFAULT_WM_INTERVAL,
                    help="min seconds between upload.wikimedia.org requests")
    ap.add_argument("--ov-interval", type=float, default=DEFAULT_OV_INTERVAL,
                    help="min seconds between Openverse requests")
    ap.add_argument("--source", default="wikimedia",
                    help="Openverse source filter (wikimedia|flickr|...)")
    ap.add_argument("--cutout", action="store_true",
                    help="run rembg and record the car pixel fraction")
    ap.add_argument("--state", help="resume file (default <out>/photo_source_state.json)")
    ap.add_argument("--retry-failed", action="store_true",
                    help="re-attempt cars previously recorded as failed")
    a = ap.parse_args()

    cars = list(a.cars)
    if a.list:
        with open(a.list) as f:
            cars += [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    if not cars:
        ap.error("give car descriptions, or --list FILE")

    os.makedirs(a.out, exist_ok=True)
    state_path = a.state or os.path.join(a.out, "photo_source_state.json")
    state = load_state(state_path)

    log(f"{len(cars)} cars -> {a.out}  (state {state_path})")
    log(f"pacing: openverse >={a.ov_interval}s, wikimedia >={a.wm_interval}s")

    t0 = time.time()
    n_ok = n_skip = n_fail = 0
    for i, car in enumerate(cars, 1):
        key = car.strip()
        prev = state.get(key)
        if prev and prev.get("status") == "ok" and len(prev.get("images", [])) >= a.per:
            n_skip += 1
            log(f"[{i}/{len(cars)}] {car}: already done ({len(prev['images'])} img) -- skip")
            continue
        if prev and prev.get("status") == "failed" and not a.retry_failed:
            n_skip += 1
            log(f"[{i}/{len(cars)}] {car}: previously failed ({prev.get('reason')}) "
                f"-- skip (use --retry-failed)")
            continue

        log(f"[{i}/{len(cars)}] {car}")
        rec = {"query": key, "slug": slugify(key), "attempted_at": time.strftime("%FT%TZ"),
               "images": [], "dropped": [], "status": "failed", "reason": None}

        cands, err = openverse_search(key, a.page_size, a.wm_interval,
                                      a.ov_interval, a.source)
        if err:
            rec["reason"] = err
            log(f"    DISCOVERY FAILED: {err}")
            state[key] = rec
            save_state(state_path, state)
            n_fail += 1
            continue
        if not cands:
            rec["reason"] = "no-results"
            log("    no Openverse results")
            state[key] = rec
            save_state(state_path, state)
            n_fail += 1
            continue

        keep, dropped = triage(cands, key, a.min_long_edge)
        rec["dropped"] = [{"title": c["title"][:90], "reason": r} for c, r in dropped]
        log(f"    {len(cands)} candidates -> {len(keep)} pass triage "
            f"({len(dropped)} dropped)")
        if not keep:
            rec["reason"] = "all-candidates-dropped"
            state[key] = rec
            save_state(state_path, state)
            n_fail += 1
            continue

        got = 0
        for c in keep:
            if got >= a.per:
                break
            c["slug"] = rec["slug"]
            fn, derr = download(c, a.out, a.wm_interval, a.ov_interval, a.max_bytes)
            if derr:
                log(f"    download failed ({derr}) -- {c['title'][:60]}")
                rec["dropped"].append({"title": c["title"][:90], "reason": derr})
                continue
            if a.cutout:
                frac, cp, cerr = cutout_fraction(fn, a.out)
                c["cutout_fraction"] = frac
                c["cutout_file"] = cp
                c["cutout_error"] = cerr
                log(f"    OK {os.path.basename(fn)} {c['width']}x{c['height']} "
                    f"score={c['score']} cutout={frac} licence={c['licence']}")
            else:
                log(f"    OK {os.path.basename(fn)} {c['width']}x{c['height']} "
                    f"score={c['score']} licence={c['licence']}")
            rec["images"].append(c)
            got += 1

        if got:
            rec["status"] = "ok"
            n_ok += 1
        else:
            rec["reason"] = "all-downloads-failed"
            n_fail += 1
        state[key] = rec
        save_state(state_path, state)      # after EVERY car: a rollback costs one item

    dur = time.time() - t0
    imgs = sum(len(v.get("images", [])) for v in state.values())
    log(f"DONE ok={n_ok} failed={n_fail} skipped={n_skip} in {dur:.0f}s "
        f"({imgs} images in state)")
    for host, g in _GATES.items():
        log(f"  gate {host}: floor={g.floor}s final={g.interval:.1f}s 429s={g.n429}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
