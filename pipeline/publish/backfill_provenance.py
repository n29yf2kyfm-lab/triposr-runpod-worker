"""Fill in sourceTitle / sourceCreator / sourceUrl from the authoritative source.

publish_batch reads these three fields out of the LICENCES.csv row, not out of
the staged manifest -- `lr.get("title")`, `lr.get("author")`, `lr.get("page")`.
Hand a it a CSV carrying only `uid,licence` and the entry publishes with empty
provenance and nothing complains, which is how the five vw1 cars shipped with
no source title. That breaks the project's own accuracy standard: the catalogue
is supposed to store the exact source title verbatim, and an empty string is
not verbatim.

Rather than retype the titles from a manifest (which is a copy, and copies
drift), this asks Sketchfab for each uid and writes back what the API returns:
`name`, `user.username`, `viewerUrl`, and `license.label`. That is the same
record the asset itself is served from, so it cannot disagree with the source.

The licence is compared, not overwritten. A mismatch between what the catalogue
claims and what the API reports is printed and left alone -- selection is
decided on the render and licence is recorded rather than enforced, but a
disagreement is worth seeing rather than silently papering over.

Nothing else is touched. colourVariants are not read or written, so
variantsHash is unaffected and existing recolour stamps stay valid.

Usage:
    backfill_provenance.py --assets a,b,c   [--dry-run]
    backfill_provenance.py --wave vw1       [--dry-run]
"""
import argparse, json, os, sys, time, urllib.error, urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAT = os.path.join(REPO, "platform", "catalogue", "catalogue.v2.json")
API = "https://api.sketchfab.com/v3/models"


def load_env(path="/root/.alam3d_env"):
    try:
        body = open(path).read()
    except OSError:
        return
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line[7:].lstrip() if line.startswith("export ") else line
        n, sep, v = line.partition("=")
        if sep and not os.environ.get(n.strip()):
            os.environ[n.strip()] = v.strip().strip("'\"")


load_env()
TOKENS = [t for t in (os.environ.get("SKETCHFAB_TOKENS") or "").split(",") if t]
if not TOKENS:
    sys.exit("FATAL: SKETCHFAB_TOKENS not set")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def fetch(uid):
    """Model record from Sketchfab, rotating tokens on rate limit."""
    last = None
    for tok in TOKENS:
        try:
            rq = urllib.request.Request(f"{API}/{uid}", headers={
                "Authorization": f"Token {tok}", "User-Agent": "Mozilla/5.0"})
            return json.load(urllib.request.urlopen(rq, timeout=60))
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 403):
                time.sleep(2)
                continue
            raise
    raise last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", default="")
    ap.add_argument("--wave", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    cat = json.load(open(CAT))
    entries = cat if isinstance(cat, list) else cat.get("entries", cat)
    want = {s for s in a.assets.split(",") if s}
    todo = [e for e in entries
            if e.get("sourceReferenceId")
            and (e.get("assetId") in want if want else
                 (a.wave and (e.get("assetId") or "").endswith(f"-{a.wave}-v1")))]
    if not todo:
        sys.exit("nothing matched")
    log(f"{len(todo)} entrie(s)" + ("  [DRY RUN]" if a.dry_run else ""))

    changed = 0
    for e in todo:
        uid = e["sourceReferenceId"]
        try:
            d = fetch(uid)
        except Exception as ex:
            log(f"  SKIP {e['assetId']}: {type(ex).__name__} {str(ex)[:60]}")
            continue
        title = d.get("name") or ""
        # displayName is the name the creator publishes under and the one an
        # attribution should carry; username is the account handle and they
        # differ often (KOElkast1007 vs koelkastasbers, Merc_TV vs
        # szymonpasterczyk). Prefer the display name, fall back to the handle.
        user = d.get("user") or {}
        creator = user.get("displayName") or user.get("username") or ""
        url = d.get("viewerUrl") or ""
        api_lic = ((d.get("license") or {}).get("label") or "").strip()

        if api_lic and (e.get("licence") or "").strip() != api_lic:
            log(f"  NOTE {e['assetId']}: catalogue licence "
                f"{e.get('licence')!r} != source {api_lic!r} — left as recorded")

        if not a.dry_run:
            e["sourceTitle"] = title
            e["sourceCreator"] = creator
            e["sourceUrl"] = url
            e["sourceRetrievedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        changed += 1
        log(f"  {e['assetId']}")
        log(f"      title   {title}")
        log(f"      creator {creator}")

    if changed and not a.dry_run:
        json.dump(cat, open(CAT, "w"), indent=1, ensure_ascii=False)
        log(f"catalogue.v2.json updated locally — {changed} entrie(s). "
            "Run gate_catalogue then serve.")
    else:
        log(f"{changed} would change")


if __name__ == "__main__":
    main()
