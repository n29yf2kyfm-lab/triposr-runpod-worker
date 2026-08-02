"""Bake the 8-colour DVLA palette for catalogue entries that ship single-neutral.

Every approved car in the library carries exactly eight colour variants --
grey, silver, black, white, blue, red, green, yellow -- each a separate GLB at
`car-meshes/library/<make>/<model>__<colour>.glb`, with `colourVariants`
mapping colour to public URL. publish_batch deliberately ships single-neutral
and leaves this step separate, and gate_catalogue enforces that ordering.

This replaces wave_tools/variants_w7.py, which cannot run: it regex-scrapes its
Supabase key out of `wave_tools/golf_publish.py`, a scratch file that was never
tracked and no longer exists. Credentials come from the environment here, like
every other tool in the pipeline.

The respray is a glTF-JSON edit, not a Blender bake -- Blender matches on ITS
material names, which can differ from the glTF ones, and silently exports the
file unchanged when nothing matches. That is how two "different" colours once
shipped rendering identically. Editing the JSON matches the real names and
raises KeyError instead, so a car that cannot be resprayed fails loudly and is
left single-neutral rather than shipping eight identical files.

`colourVariantPaints` records the OEM paint names that are plausible for each
colour, resolved through platform/paint/oem_paint_db.csv filtered to the
entry's MANUFACTURER and then to the DVLA broad colour -- ranked candidates,
never a claim. Rule 7 of the resolution workflow: an exact OEM paint is never
asserted without VIN, paint label, or manufacturer record, so these are carried
as possibilities for the app to display as "Possible OEM colour".

Verification is not optional and is not done here: run
`pipeline/qc/recolour_audit.py --stamp` afterwards. It renders each variant and
proves the body colour actually moved; gate_catalogue refuses to serve a
colour-swap entry that is not stamped.

Usage:
    colour_variants.py --assets volkswagen-fox-2004-vw1-v1,... [--dry-run]
    colour_variants.py --wave vw1
"""
import argparse, csv, json, os, shutil, struct, sys, tempfile, time, urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "pipeline", "publish"))
from respray_gltf import respray                                   # noqa: E402

CAT = os.path.join(REPO, "platform", "catalogue", "catalogue.v2.json")
PAINT_DB = os.path.join(REPO, "platform", "paint", "oem_paint_db.csv")
SB = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"

# The palette every shipped car uses. Hexes match the existing 562 entries.
PALETTE = {"grey": "6f7276", "silver": "b6b9be", "black": "1b1d20", "white": "e4e6e8",
           "blue": "1f4fb0", "red": "b11e1e", "green": "1f6b3a", "yellow": "d9b310"}
# palette colour -> the DVLA broad colour the paint DB indexes on
DVLA = {"grey": "GREY", "silver": "SILVER", "black": "BLACK", "white": "WHITE",
        "blue": "BLUE", "red": "RED", "green": "GREEN", "yellow": "YELLOW"}


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
KEY = os.environ.get("SB_KEY") or sys.exit("FATAL: SB_KEY not set")
HDR = {"apikey": KEY, "Authorization": "Bearer " + KEY}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def sb_get(path):
    return urllib.request.urlopen(
        urllib.request.Request(f"{SB}/{path}", headers=HDR), timeout=900).read()


def sb_put(path, blob, ctype="model/gltf-binary"):
    last = None
    for _ in range(3):
        try:
            rq = urllib.request.Request(f"{SB}/{path}", data=blob, method="POST",
                headers={**HDR, "Content-Type": ctype, "x-upsert": "true"})
            return urllib.request.urlopen(rq, timeout=900).status
        except Exception as e:
            last = e
            time.sleep(5)
    raise last


def glb_ok(path):
    """Magic AND the header's own length -- either alone passes a truncated file."""
    with open(path, "rb") as f:
        head = f.read(12)
    return len(head) == 12 and head[:4] == b"glTF" and \
        struct.unpack("<I", head[8:12])[0] == os.path.getsize(path)


def oem_paints(make):
    """{DVLA_COLOUR: [{name, family, finish}]} for one manufacturer.

    An unknown make yields {} -- never another marque's paints, which is the
    failure the customization.colourOptions rule exists to prevent.
    """
    out = {}
    want = (make or "").strip().lower()
    with open(PAINT_DB, newline="") as fh:
        for row in csv.DictReader(fh):
            if (row["MANUFACTURER"] or "").strip().lower() != want:
                continue
            out.setdefault((row["DVLA_COLOUR"] or "").strip().upper(), []).append(
                {"oemPaintName": (row["OEM_PAINT_NAME"] or "").strip(),
                 "colourFamily": (row["COLOUR_FAMILY"] or "").strip(),
                 "finish": (row["FINISH"] or "").strip()})
    return out


def variant_path(make, model, colour):
    slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in (model or "").lower())
    return f"car-meshes/library/{make}/{slug}__{colour}.glb"


def bake(entry, work, dry=False):
    aid = entry["assetId"]
    body = entry.get("paintMaterialNames") or []
    if not body:
        return None, "no paintMaterialNames — nothing to respray"

    src_url = entry.get("desktopGlbUrl") or entry.get("fallbackGlbUrl")
    if not src_url:
        return None, "no source GLB url"
    rel = src_url.split("/object/public/", 1)[-1]
    src = os.path.join(work, f"{aid}.glb")
    with open(src, "wb") as fh:
        fh.write(sb_get(rel))
    if not glb_ok(src):
        return None, "source GLB truncated"

    made = {}
    for colour, hexcol in PALETTE.items():
        dst = os.path.join(work, f"{aid}__{colour}.glb")
        try:
            respray(src, dst, body, hexcol)
        except KeyError as e:
            return None, f"respray failed: {str(e)[:90]}"
        if not glb_ok(dst):
            return None, f"{colour}: wrote a bad GLB"
        p = variant_path(entry["make"], entry["model"], colour)
        if not dry:
            sb_put(p, open(dst, "rb").read())
        made[colour] = f"{SB}/public/{p}"
        os.remove(dst)
    os.remove(src)

    db = oem_paints(entry.get("make"))
    paints = {c: db.get(DVLA[c], []) for c in PALETTE}
    return (made, paints), None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", default="", help="comma-separated assetIds")
    ap.add_argument("--wave", default="", help="all approved entries whose assetId ends -<wave>-v1")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    cat = json.load(open(CAT))
    entries = cat if isinstance(cat, list) else cat.get("entries", cat)
    want = {s for s in a.assets.split(",") if s}
    todo = [e for e in entries
            if e.get("publicationStatus") == "approved"
            and not (e.get("colourVariants") or {})
            and (e.get("assetId") in want if want else
                 (a.wave and (e.get("assetId") or "").endswith(f"-{a.wave}-v1")))]
    if not todo:
        sys.exit("nothing to do — no matching approved entry lacks colourVariants")
    log(f"{len(todo)} entrie(s) to bake" + ("  [DRY RUN]" if a.dry_run else ""))

    work = tempfile.mkdtemp(prefix="cvar-")
    ok = fail = 0
    try:
        for e in todo:
            got, err = bake(e, work, a.dry_run)
            if err:
                log(f"  SKIP {e['assetId']}: {err}")
                fail += 1
                continue
            variants, paints = got
            if not a.dry_run:
                e["colourVariants"] = variants
                e["colourVariantPaints"] = paints
            ok += 1
            n = sum(len(v) for v in paints.values())
            log(f"  OK   {e['assetId']}  8 variants, {n} candidate OEM paints")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    if not a.dry_run and ok:
        json.dump(cat, open(CAT, "w"), indent=1, ensure_ascii=False)
        log(f"catalogue.v2.json updated locally — {ok} baked, {fail} skipped")
        log("NEXT: pipeline/qc/recolour_audit.py --stamp, then serve. "
            "gate_catalogue refuses an unstamped colour-swap entry.")
    else:
        log(f"{ok} would bake, {fail} would skip")


if __name__ == "__main__":
    main()
