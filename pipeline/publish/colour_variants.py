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
import argparse, csv, json, os, re, shutil, struct, sys, tempfile, time, urllib.request

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


def _mk(s):
    """Manufacturer key: case, spaces, hyphens and underscores all equivalent.

    The catalogue slugs makes ("land-rover", "alfa-romeo") while the paint
    database spells them out ("Land Rover", "Alfa Romeo"). A plain lowercase
    comparison misses those, silently: the entry publishes with an empty paint
    list and nothing complains. Measured on the live catalogue, that was 27
    approved cars -- 19 Land Rover, 8 Alfa Romeo -- getting no OEM candidates
    for no reason other than a hyphen.
    """
    return re.sub(r"[\s_-]+", " ", (s or "").strip().lower())


def oem_paints(make):
    """{DVLA_COLOUR: [{name, family, finish}]} for one manufacturer.

    An unknown make yields {} -- never another marque's paints, which is the
    failure the customization.colourOptions rule exists to prevent.
    """
    out = {}
    want = _mk(make)
    with open(PAINT_DB, newline="") as fh:
        for row in csv.DictReader(fh):
            if _mk(row["MANUFACTURER"]) != want:
                continue
            out.setdefault((row["DVLA_COLOUR"] or "").strip().upper(), []).append(
                {"oemPaintName": (row["OEM_PAINT_NAME"] or "").strip(),
                 "colourFamily": (row["COLOUR_FAMILY"] or "").strip(),
                 "finish": (row["FINISH"] or "").strip()})
    return out


def variant_path(asset_id, make, colour):
    """Storage path for one colour, keyed on assetId.

    It must be assetId, never make+model. A make+model key collides the moment
    two entries share a nameplate, and the library is full of those: four
    Mercedes E-Class entries, four Skoda Octavias, three Honda Civics, eleven
    Volkswagen Golfs. On a collision the second bake overwrites the first's
    eight GLBs and both entries' colourVariants then point at the same files,
    so two different cars serve one model -- and nothing catches it, because
    gate_catalogue only checks that variantsHash matches and recolourAudit
    passed, and both still hold when the shared file recolours correctly.

    This is also the convention the library already uses: every wave-tagged
    entry is `<assetId>__<colour>.glb`. Only the oldest `-v1` entries still
    carry the superseded `<model>_uc__<colour>.glb` form.
    """
    return f"car-meshes/library/{make}/{asset_id}__{colour}.glb"


def claimed_paths(entries):
    """{storage path: assetId} for every variant already referenced anywhere.

    Belt and braces behind the assetId key: even if a future edit reintroduces
    an ambiguous path scheme, a bake that would land on another entry's file
    refuses instead of silently overwriting it.
    """
    out = {}
    for e in entries:
        for url in (e.get("colourVariants") or {}).values():
            out[url.split("/object/public/", 1)[-1]] = e.get("assetId")
    return out


def bake(entry, work, dry=False, taken=None):
    taken = taken or {}
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
        p = variant_path(entry["assetId"], entry["make"], colour)
        if p in taken and taken[p] != entry["assetId"]:
            return None, f"path {p} already claimed by {taken[p]} — refusing to overwrite"
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
    ap.add_argument("--rebake", action="store_true",
                    help="also re-bake entries that already carry colourVariants "
                         "(re-baking changes variantsHash, so recolour_audit --stamp "
                         "must run again before the gate will serve them)")
    a = ap.parse_args()

    cat = json.load(open(CAT))
    entries = cat if isinstance(cat, list) else cat.get("entries", cat)
    want = {s for s in a.assets.split(",") if s}
    todo = [e for e in entries
            if e.get("publicationStatus") == "approved"
            and (a.rebake or not (e.get("colourVariants") or {}))
            and (e.get("assetId") in want if want else
                 (a.wave and (e.get("assetId") or "").endswith(f"-{a.wave}-v1")))]
    if not todo:
        sys.exit("nothing to do — no matching approved entry lacks colourVariants")
    log(f"{len(todo)} entrie(s) to bake" + ("  [DRY RUN]" if a.dry_run else ""))

    rebaking = {e.get("assetId") for e in todo}
    taken = {p: aid for p, aid in claimed_paths(entries).items() if aid not in rebaking}

    work = tempfile.mkdtemp(prefix="cvar-")
    ok = fail = 0
    try:
        for e in todo:
            got, err = bake(e, work, a.dry_run, taken)
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
