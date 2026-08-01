"""Sourcing wave: fetch, de-rig, render and contact-sheet a set of target cars.

Lives in the REPO, not the scratchpad. The first version of this was a scratchpad
script and a container rollback destroyed it mid-run at 02:00 while the owner was
asleep; the manifest and seven finished sheets survived only because they had
already been pushed to Supabase. Anything that must outlive a rollback belongs in
git or in the bucket.

Reads a manifest of candidates (see harvest_targets in this file, or an existing
manifest recovered from the bucket) and for each one:

  1. downloads the GLB, checking magic bytes AND the header's own length field
  2. strips baked-in environment geometry (see strip_env.py)
  3. renders the four rubric views through the REAL render worker
  4. builds a contact sheet carrying the worker's own material verdict
  5. uploads GLB and sheet to Supabase the moment each validates

Every stage is resumable against the bucket, so a rollback costs only the car in
flight. Usage:

    vw_wave.py --manifest path.json [--limit N]
    vw_wave.py --harvest "Volkswagen Polo:2002,2006,2010" ... --manifest out.json
"""
import argparse, json, os, re, struct, sys, time, types, urllib.error, urllib.parse, urllib.request

ENV_FILE = "/root/.alam3d_env"


def load_env(path=ENV_FILE):
    """Populate missing credentials from the out-of-repo env file.

    A relaunch that forgets to source this file used to die one line in, and the
    failure looked exactly like a healthy start: the process logged the manifest
    count, then exited. Reading the file here means the tool cannot be launched
    without its credentials. Values already in the environment always win.
    """
    try:
        with open(path) as fh:
            body = fh.read()
    except OSError:
        return
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line[7:].lstrip() if line.startswith("export ") else line
        name, sep, value = line.partition("=")
        if sep and not os.environ.get(name.strip()):
            os.environ[name.strip()] = value.strip().strip("'\"")


load_env()

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
R = os.path.join(REPO, "render")
os.environ.setdefault("HDRI_PATH", os.path.join(R, "assets", "hdri.hdr"))
sys.modules.setdefault("runpod", types.ModuleType("runpod"))
sys.modules["runpod"].serverless = types.SimpleNamespace(start=lambda *a, **k: None)
sys.path.insert(0, R)
sys.path.insert(0, os.path.join(REPO, "pipeline", "ingest"))

SB = "https://tfkvthprsntexrcuqpyd.supabase.co"
BUCKET = "car-meshes"
VIEWS = [("front34", 35), ("front34_L", 325), ("side", 90), ("rear34", 215)]
W, HG, SAMPLES = 1024, 576, 96
MAX_OBJ = 48_000_000


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def key():
    k = os.environ.get("SB_KEY")
    if not k:
        sys.exit("FATAL: SB_KEY not set")
    return k


def sb_put(path, blob, ctype):
    rq = urllib.request.Request(f"{SB}/storage/v1/object/{path}", data=blob, method="POST",
        headers={"Authorization": f"Bearer {key()}", "apikey": key(),
                 "Content-Type": ctype, "x-upsert": "true"})
    return urllib.request.urlopen(rq, timeout=900).status


def sb_list(prefix):
    body = json.dumps({"prefix": prefix, "limit": 1000}).encode()
    rq = urllib.request.Request(f"{SB}/storage/v1/object/list/{BUCKET}", data=body,
        headers={"Authorization": f"Bearer {key()}", "apikey": key(),
                 "Content-Type": "application/json"})
    try:
        return {o["name"].split("/")[-1]
                for o in json.load(urllib.request.urlopen(rq, timeout=180))}
    except Exception as e:
        log("warn: bucket list failed", str(e)[:70])
        return set()


def valid_glb(b):
    """Magic bytes AND the header's own total-length field. Either alone lets a
    truncated download through looking like a valid file."""
    return len(b) > 20 and b[:4] == b"glTF" and struct.unpack("<I", b[8:12])[0] == len(b)


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower())


def class_gates():
    """The hardened title gates from the Objaverse curator, or None.

    `BAD` rejects toy/game/stylised assets, `WRONG_CLASS` rejects the wrong
    vehicle class (train, boat, bus, tractor, fire truck…). Both were repaired
    and regression-tested on 2026-07-27 — see the comments around their
    definitions, and do not "tidy" their terminators.

    This wave's own "every target word must be in the title" rule is already
    stricter than these for the common case: nothing that matches both
    "volkswagen" and "polo" is a helicopter. These add the case that rule
    cannot see — a correctly-named listing that is a toy, a game asset or a
    Polo-badged van. Verified against the 29 VW titles staged on 2026-08-01:
    0 flagged, so this narrows nothing that was already passing.

    Imported lazily and defensively: the curator lives under pipeline/finetune
    and is not a dependency of sourcing. If it cannot be loaded the wave still
    runs, and says so, rather than silently dropping a gate.
    """
    import importlib.util
    p = os.path.join(REPO, "pipeline", "finetune", "objaverse_wave4.py")
    try:
        spec = importlib.util.spec_from_file_location("_ow4", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.BAD, mod.WRONG_CLASS
    except Exception as e:
        log(f"warn: hardened title gates unavailable ({type(e).__name__}) - "
            f"harvest runs WITHOUT them")
        return None


def harvest(specs, cat_path):
    """specs: ["Make Model:yr,yr,yr", ...] -> candidate list.

    Searched once PER GENERATION YEAR on purpose. A single query per nameplate
    ranks newest-first and returns four copies of the current car, which is not
    what "Polo from 2000 to 2026" means.
    """
    from gap_search import API, face_score, toks
    known = set()
    try:
        known = {e["sourceReferenceId"] for e in json.load(open(cat_path))
                 if e.get("sourceReferenceId")}
    except Exception as e:
        log("warn: catalogue unreadable", e)
    tok = toks()
    gates = class_gates()
    picks, seen, rejects = [], set(), []
    for spec in specs:
        plate, _, ys = spec.partition(":")
        years = [int(y) for y in ys.split(",") if y.strip()]
        want = norm(plate).split()
        for yr in years:
            best = None
            for q in (f"{plate} {yr}", f"{plate} {yr} model"):
                p = {"type": "models", "q": q, "downloadable": "true",
                     "sort_by": "-likeCount", "count": 24}
                try:
                    rq = urllib.request.Request(f"{API}/search?" + urllib.parse.urlencode(p),
                        headers={"Authorization": f"Token {next(tok)}",
                                 "User-Agent": "Mozilla/5.0"})
                    res = json.load(urllib.request.urlopen(rq, timeout=60)).get("results", [])
                except Exception as e:
                    log(f"  query fail [{q}] {type(e).__name__}"); time.sleep(8); continue
                for r in res:
                    nm = norm(r.get("name"))
                    if not all(w in nm for w in want):
                        continue
                    if r["uid"] in known or r["uid"] in seen:
                        continue
                    warn = None
                    if gates:
                        # Title is a hard reject; description and tags only warn.
                        #
                        # Measured 2026-08-01 against the 29 staged VW titles:
                        # the title test flagged 0, and extending it to
                        # description+tags flagged 8 -- every one of them for a
                        # sim-mod tag (gta, assetto, forza, beamng) or for
                        # "freedownload", not for being the wrong vehicle. BAD
                        # was written to curate a TRAINING pool, where an
                        # Assetto Corsa conversion is noise; for the serving
                        # catalogue those are often the most accurate car
                        # geometry on the site. Rejecting on them would have
                        # dropped 8 of 29, including the only Sharan that exists
                        # in the band.
                        #
                        # So the owner's eye stays the gate (2026-07-23
                        # standard: an automated pass is not a quality verdict),
                        # and the warning rides along to the contact sheet.
                        nmh = gates[0].search(nm) or gates[1].search(nm)
                        if nmh:
                            rejects.append((r.get("name", "")[:44], nmh.group(0)))
                            log(f"  reject [{nmh.group(0)}] {r.get('name','')[:44]}")
                            seen.add(r["uid"])
                            continue
                        tags = " ".join(t.get("name", "") for t in (r.get("tags") or []))
                        body = norm(f"{r.get('description','')} {tags}")
                        bh = gates[0].search(body) or gates[1].search(body)
                        warn = bh.group(0) if bh else None
                    fc = r.get("faceCount") or 0
                    if not face_score(fc):
                        continue
                    yrs = [int(y) for y in re.findall(r"\b((?:19|20)\d{2})\b", r.get("name") or "")]
                    dist = min((abs(y - yr) for y in yrs), default=99)
                    sc = face_score(fc) * 2 + min(r.get("likeCount", 0), 200) / 200.0 - dist * 0.15
                    if best is None or sc > best["score"]:
                        best = {"uid": r["uid"], "name": r.get("name", ""), "faces": fc,
                                "likes": r.get("likeCount", 0), "plate": plate,
                                "anchor": yr, "score": sc,
                                "licence": (r.get("license") or {}).get("label", "?"),
                                "author": (r.get("user") or {}).get("displayName", ""),
                                "class_warn": warn}
                time.sleep(1.2)
            if best:
                seen.add(best["uid"]); picks.append(best)
                w = f"  WARN[{best['class_warn']}]" if best.get("class_warn") else ""
                log(f"  {plate} {yr} -> {best['name'][:44]} ({best['faces']:,}f){w}")
            else:
                log(f"  {plate} {yr} -> nothing in-band")
    if gates:
        log(f"hardened title gates rejected {len(rejects)} listing(s)")
        for nm, why in rejects:
            log(f"    [{why}] {nm}")
    return picks


def run(picks, work, stage, sheets, limit=None):
    import handler as H
    import bpy
    from strip_env import strip
    from PIL import Image, ImageDraw, ImageFont
    try:
        FT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 19)
        FS = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 15)
    except Exception:
        FT = FS = ImageFont.load_default()
    from gap_search import API, toks
    tok = toks()

    staged = sb_list(stage + "/")
    done = sb_list(sheets + "/")
    os.makedirs(work, exist_ok=True)
    built = 0
    for i, p in enumerate(picks, 1):
        if limit and built >= limit:
            break
        uid = p["uid"]
        if f"{uid}.jpg" in done:
            continue
        raw, clean = f"{work}/{uid}.glb", f"{work}/{uid}_c.glb"
        try:
            if not os.path.exists(raw) and not os.path.exists(clean):
                if f"{uid}_clean.glb" in staged:
                    urllib.request.urlretrieve(
                        f"{SB}/storage/v1/object/public/{BUCKET}/{stage}/{uid}_clean.glb", clean)
                elif f"{uid}.glb" in staged:
                    urllib.request.urlretrieve(
                        f"{SB}/storage/v1/object/public/{BUCKET}/{stage}/{uid}.glb", raw)
                else:
                    rq = urllib.request.Request(f"{API}/models/{uid}/download",
                        headers={"Authorization": f"Token {next(tok)}",
                                 "User-Agent": "Mozilla/5.0"})
                    url = (json.load(urllib.request.urlopen(rq, timeout=90)).get("glb") or {}).get("url")
                    if not url:
                        log(f"[{i}] {p['plate']} {p['anchor']} no-glb-format"); continue
                    blob = urllib.request.urlopen(url, timeout=900).read()
                    if not valid_glb(blob):
                        log(f"[{i}] {p['plate']} {p['anchor']} bad/truncated"); continue
                    if len(blob) > MAX_OBJ:
                        log(f"[{i}] {p['plate']} {p['anchor']} too big {len(blob)/1e6:.0f}MB"); continue
                    sb_put(f"{BUCKET}/{stage}/{uid}.glb", blob, "model/gltf-binary")
                    open(raw, "wb").write(blob)
                    log(f"[{i}/{len(picks)}] staged {p['plate']} {p['anchor']} {len(blob)/1e6:.1f}MB")
        except urllib.error.HTTPError as e:
            log(f"[{i}] {p['plate']} {p['anchor']} http-{e.code}")
            if e.code in (429, 403):
                time.sleep(120)
            continue
        except Exception as e:
            log(f"[{i}] {p['plate']} {p['anchor']} {type(e).__name__}: {str(e)[:70]}"); continue

        if not os.path.exists(clean) and os.path.exists(raw):
            try:
                rep = strip(bpy, raw, clean)
                if rep.get("stripped") and rep.get("ok"):
                    log(f"       de-rigged {[s['name'] for s in rep['stripped']]}")
                    sb_put(f"{BUCKET}/{stage}/{uid}_clean.glb",
                           open(clean, "rb").read(), "model/gltf-binary")
            except Exception as e:
                log(f"       strip failed {type(e).__name__}: {str(e)[:60]}")
        glb = clean if os.path.exists(clean) else raw
        if not os.path.exists(glb):
            continue

        mats = None
        for name, az in VIEWS:
            out = f"{work}/{uid}_{name}.png"
            if os.path.exists(out):
                continue
            try:
                _, rc, _, _ = H._render(bpy, glb, out, colour=None, plate_reg=None,
                    az_deg=az, elev=0.15, zfrac=0.32, samples=SAMPLES,
                    resx=W, resy=HG, studio=True)
                mats = mats or rc
            except Exception as e:
                log(f"       render {name} FAILED {type(e).__name__}: {str(e)[:60]}")
        p["recolour"] = mats

        have = [(f"{work}/{uid}_{n}.png", l) for n, l in
                [("front34", "front 3/4"), ("front34_L", "front 3/4 left"),
                 ("side", "side"), ("rear34", "rear 3/4")]]
        have = [(q, l) for q, l in have if os.path.exists(q)]
        if not have:
            log(f"       no views rendered"); continue
        ims = [(Image.open(q).convert("RGB"), l) for q, l in have]
        w, h = ims[0][0].size
        TW = 860; TH = int(h * TW / w); PAD = 28
        sheet = Image.new("RGB", (TW * 2, (TH + PAD) * 2 + PAD), (14, 14, 16))
        d = ImageDraw.Draw(sheet)
        nm = len((mats or {}).get("materials") or [])
        cov = (mats or {}).get("coverage") or 0.0
        adv = 1 <= nm <= 2 and 0.05 <= cov <= 0.45
        cw = p.get("class_warn")
        d.text((10, 5), f"{p['plate']}  gen~{p['anchor']}  |  {p['name'][:44]}  |  "
                        f"{p['faces']:,}f  |  body mats={nm} cov={cov:.3f}  |  "
                        f"{'recolourable' if adv else 'MATERIAL SPLIT SUSPECT'}"
                        + (f"  |  TAGGED '{cw}'" if cw else ""),
               fill=(150, 255, 170) if adv else (255, 170, 170), font=FT)
        for j, (im, lab) in enumerate(ims):
            x = (j % 2) * TW; y = PAD + (j // 2) * (TH + PAD)
            sheet.paste(im.resize((TW, TH), Image.LANCZOS), (x, y))
            d.text((x + 8, y + TH + 4), lab, fill=(155, 155, 163), font=FS)
        sp = f"{work}/SHEET_{p['plate'].split()[-1]}_{p['anchor']}_{uid[:6]}.jpg"
        sheet.save(sp, quality=91)
        try:
            sb_put(f"{BUCKET}/{sheets}/{uid}.jpg", open(sp, "rb").read(), "image/jpeg")
        except Exception as e:
            log("       sheet upload failed", str(e)[:60])
        built += 1
        log(f"[{i}/{len(picks)}] SHEET {p['plate']} {p['anchor']}  mats={nm} cov={cov:.3f}")

        # keep only the de-rigged copy; local disk hit 100% twice in one session
        for f in (raw,) + tuple(q for q, _ in have):
            if os.path.exists(clean) and os.path.exists(f) and f != clean:
                try:
                    os.remove(f)
                except OSError:
                    pass
    return built


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--harvest", nargs="*", default=[])
    ap.add_argument("--work", default="/tmp/wave_work")
    ap.add_argument("--stage", default="staging/vw2026")
    ap.add_argument("--sheets", default="audit/vw2026")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    cat = os.path.join(REPO, "platform", "catalogue", "catalogue.v2.json")

    if os.path.exists(a.manifest):
        picks = json.load(open(a.manifest))
        log(f"manifest: {len(picks)} candidates")
    elif a.harvest:
        picks = harvest(a.harvest, cat)
        json.dump(picks, open(a.manifest, "w"), indent=1)
        sb_put(f"{BUCKET}/{a.sheets}/_manifest.json",
               json.dumps(picks, indent=1).encode(), "application/json")
        log(f"harvested {len(picks)} candidates")
    else:
        sys.exit("no manifest and no --harvest specs")

    n = run(picks, a.work, a.stage, a.sheets, a.limit or None)
    json.dump(picks, open(a.manifest, "w"), indent=1)
    try:
        sb_put(f"{BUCKET}/{a.sheets}/_manifest.json",
               json.dumps(picks, indent=1).encode(), "application/json")
    except Exception:
        pass
    log(f"WAVE_DONE  {n} new sheets this run")


if __name__ == "__main__":
    main()
