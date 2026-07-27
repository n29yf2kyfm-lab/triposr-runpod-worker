#!/usr/bin/env python3
"""objaverse_wave4.py — scale the training set past 2000 shapes.

Wave 3 proved the pipeline; wave 4 applies its lessons up front instead of
retro-fitting them:
  * hard audit BEFORE download — tags/description/face-count are checked from
    Objaverse metadata, so game-engine, cartoon, stylised, fantasy and
    amateur assets never touch the bucket;
  * >= 40k faces (below that a "car" is a hollow shell with detail painted on,
    which teaches the model to make blobs);
  * CC-BY / CC0 only, provenance recorded per asset;
  * van / 4x4 / pickup bias retained — the body styles the set still lacks.

Usage:
  python3 pipeline/finetune/objaverse_wave4.py --target 1600
Env: SB_KEY. No secrets in this file.
"""
import argparse, collections, gzip, io, json, os, re, sys, time, unicodedata, urllib.request

HF = "https://huggingface.co/datasets/allenai/objaverse/resolve/main"
SUPA = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
OUT = os.environ.get("HARVEST_OUT", "/tmp")
MIN_FACES = 40_000

BAD = re.compile(r"(?i)\b(low ?poly|lowpoly|low-poly|game ?ready|gameready|game ?asset|for ?games|"
                 r"unity|unreal|ue4|ue5|roblox|minecraft|fortnite|gta|forza|nfs|need ?for ?speed|"
                 r"rocket ?league|beamng|assetto|simulator|mobile ?game|cartoon|toon|stylized|"
                 r"stylised|anime|chibi|cute|voxel|blocky|fantasy|sci ?fi|scifi|futuristic|alien|"
                 r"cyberpunk|apocalypse|zombie|mad ?max|steampunk|hover|flying ?car|toy|miniature|"
                 r"papercraft|origami|clay|sculpt(ing)? ?practice|study|exercise|tutorial|"
                 r"my ?first|beginner|practice|wip|placeholder|dummy|free ?(download|asset|model)|"
                 r"rigged ?for|scan|photogrammetry|lidar|wreck|destroyed|damaged|burnt|rusty|"
                 r"abandoned|sticker|logo|badge|diorama|scene|pack|bundle|collection)\b")
# NB the trailing \b is load-bearing. Without it this pattern matched PREFIXES:
# "toy" inside "Toyota", "scan" inside "scanner", "pack" inside "Packard".
# Measured 2026-07-27: 15 Toyotas in the training set were flagged as toys.


BRANDS = (r"bmw|audi|mercedes|benz|volkswagen|vw|ford|toyota|honda|nissan|mazda|kia|"
          r"hyundai|peugeot|renault|citroen|skoda|seat|volvo|fiat|opel|vauxhall|subaru|"
          r"mitsubishi|suzuki|dacia|tesla|porsche|jaguar|lexus|mini|dodge|chevrolet|chevy|"
          r"gmc|cadillac|chrysler|jeep|land ?rover|range ?rover|defender|lotus|bentley|"
          r"rolls ?royce|aston ?martin|maserati|alfa|lancia|infiniti|acura|genesis|"
          r"isuzu|daihatsu|ssangyong|cupra|smart|saab|"
          # marques whose absence made VEHICLE_NAME reject real cars: measured
          # 2026-07-27, 31 genuine cars in the training set failed the name test
          r"ferrari|lamborghini|mclaren|lincoln|polestar|byd|alpina|pontiac|"
          r"bugatti|koenigsegg|pagani|rivian|polaris|abarth|ds ?automobiles|"
          r"wuling|chery|great ?wall|haval|ora|nio|xpeng|lynk|geely|"
          r"mg\b")
BODY = (r"sedan|saloon|hatchback|hatch ?back|coupe|convertible|cabriolet|cabrio|roadster|"
        r"suv|crossover|4x4|estate car|station ?wagon|pickup ?truck|pick ?up|"
        r"panel ?van|cargo ?van|minivan|mpv|people ?carrier|transit|sprinter|transporter")
VEHICLE_NAME = re.compile(r"(?i)\b(" + BRANDS + r"|" + BODY + r")\b")

# Non-car vehicles that would teach the wrong prior.
#
# THIS PATTERN WAS DEAD FOR ITS ENTIRE LIFE. It used to end `)\\b` inside an
# r-string, i.e. a literal backslash followed by 'b', which no title contains —
# so it matched NOTHING and every bus, tractor and fire truck walked straight
# through the "hard audit". Verified 2026-07-27 against the exact titles it was
# claimed to catch: 0/8 hits. Do not "tidy" the terminator.
#
# Several terms are deliberately narrowed because the bare word appears in
# legitimate car metadata (measured against 2,155 real titles):
#   jet    -> "Jet Black" is a paint name
#   tank   -> "fuel tank" appears in descriptions
#   sonic  -> the Chevrolet Sonic is a real car
#   monster-> only "monster truck", not the drinks sponsor
WRONG_CLASS = re.compile(
    r"(?i)\b("
    r"train|locomotive|tram|railcar|railway|railroad|rail ?car|freight|"
    r"boat|ship|yacht|plane|aircraft|airplane|helicopter|drone|"
    r"(fighter|jumbo) ?jet|jet ?(fighter|plane|liner)|"
    r"bike|bicycle|motorbike|motorcycle|scooter|moped|quad|atv|"
    r"forklift|excavator|bulldozer|digger|crane|tractor|combine|harvester|"
    r"golf ?cart|go.?kart|trailer|caravan|motorhome|"
    r"bus|coach|minibus|panzer|battle ?tank|"
    r"skateboard|skate|longboard|carriage|wagon ?model|passenger ?wagon|"
    r"horse|cart|chariot|trolley|wheelbarrow|rickshaw|tuk.?tuk|"
    r"dump ?truck|tipper|mixer|tanker|vacuum|sweeper|refuse|garbage|"
    r"fire ?truck|fire ?engine|ambulance|police ?car|semi ?truck|"
    r"articulated|hgv|lorry|18.?wheeler|monster ?truck|6 ?x ?6|8 ?x ?8|"
    r"overwatch|zelda|romani|halo|fallout|apex|valorant|csgo|warcraft|"
    r"pubg|starcraft|mario"
    r")\b")


def norm(s):
    """Lowercase ASCII, with separators flattened to spaces.

    The separator step matters: \\b does not fire between an underscore and a
    letter, and a hyphen splits a two-word marque. Without this,
    "Rolls-Royce Ghost", "Renault_Kadjar_2018" and "Cupra_Terramar" all failed
    the VEHICLE_NAME test and were rejected as "not a car".
    """
    s = unicodedata.normalize("NFKD", (s or "").lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[_\-/|.,()\[\]]+", " ", s)


def gz(u, timeout=300):
    rq = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
    return json.loads(gzip.decompress(urllib.request.urlopen(rq, timeout=timeout).read()))


def geometry_ok(data):
    """Validate the actual mesh: metadata can lie, geometry cannot.

    Rejects anything whose bounding box is not car/van shaped, and anything
    that is really a scene (many scattered parts) rather than one vehicle.
    """
    try:
        import trimesh
        scene = trimesh.load(io.BytesIO(data), file_type="glb")
    except Exception as e:
        return False, f"unloadable ({str(e)[:24]})"
    try:
        geoms = list(scene.geometry.values()) if hasattr(scene, "geometry") else [scene]
        if not geoms:
            return False, "no geometry"
        ext = sorted(scene.bounding_box.extents, reverse=True)
        if ext[2] <= 0:
            return False, "flat/degenerate"
        L, W, Hh = ext          # longest, middle, shortest
        if not (1.6 <= L / W <= 3.6):
            return False, f"aspect L/W={L/W:.1f}"
        if not (1.5 <= L / Hh <= 4.5):
            return False, f"aspect L/H={L/Hh:.1f}"
        faces = sum(len(g.faces) for g in geoms if hasattr(g, "faces"))
        if faces < 40_000:
            return False, "faces<40k after load"
        if len(geoms) > 400:
            return False, f"scene-like ({len(geoms)} parts)"
        return True, "ok"
    except Exception as e:
        return False, f"check failed ({str(e)[:24]})"


def upload(key, bucket, path, data, ctype):
    rq = urllib.request.Request(f"{SUPA}/{bucket}/{path}", data=data, method="POST")
    for h, v in (("apikey", key), ("Authorization", "Bearer " + key),
                 ("Content-Type", ctype), ("x-upsert", "true")):
        rq.add_header(h, v)
    urllib.request.urlopen(rq, timeout=300).read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=1600, help="approved shapes to stage")
    a = ap.parse_args()
    key = os.environ.get("SB_KEY")
    if not key:
        sys.exit("SB_KEY missing from env")

    cands = json.load(open(f"{OUT}/objaverse_candidates.json"))
    prev = json.loads(urllib.request.urlopen(
        f"{SUPA}/public/car-renders/finetune/training_candidates.json?cb=1", timeout=120).read())
    seen = {c.get("uid") for c in prev}
    pool = [c for c in cands if c["uid"] not in seen and c["faces"] >= MIN_FACES]
    pool.sort(key=lambda c: -c["score"])
    print(f"pool: {len(pool)} unhandled premium-tier candidates", flush=True)

    # hard audit BEFORE download: pull each candidate's tags/description
    paths = gz(f"{HF}/object-paths.json.gz")
    shards = collections.defaultdict(list)
    for c in pool:
        p = paths.get(c["uid"])
        if p:
            shards[p.split("/")[1]].append(c["uid"])
    print(f"auditing across {len(shards)} shards", flush=True)
    verdict = {}
    for i, (sh, uids) in enumerate(sorted(shards.items())):
        try:
            m = gz(f"{HF}/metadata/{sh}.json.gz")
        except Exception as e:
            print(f"  shard {sh}: {str(e)[:50]}", flush=True)
            continue
        for u in uids:
            r = m.get(u)
            if not r:
                verdict[u] = "no metadata"
                continue
            tags = " ".join(t.get("name", "") for t in (r.get("tags") or []))
            txt = norm(f"{r.get('name','')} {r.get('description','')} {tags}")
            name = norm(r.get("name", ""))
            hit = BAD.search(txt)
            wrong = WRONG_CLASS.search(txt)
            if hit:
                verdict[u] = f"game/stylised: {hit.group(0)}"
            elif wrong:
                verdict[u] = f"wrong vehicle class: {wrong.group(0)}"
            elif not VEHICLE_NAME.search(name):
                # tags lie (wave 1 pulled an aircraft carrier tagged 'car');
                # the NAME must independently identify a road vehicle
                verdict[u] = "name does not identify a car/van"
            elif (r.get("animationCount") or 0) > 0:
                verdict[u] = "animated (rigged game asset)"
            elif r.get("isAgeRestricted"):
                verdict[u] = "age-restricted"
            else:
                verdict[u] = "OK"
        if (i + 1) % 30 == 0:
            ok = sum(1 for v in verdict.values() if v == "OK")
            print(f"  {i+1}/{len(shards)} shards, {ok} passing", flush=True)

    approved = [c for c in pool if verdict.get(c["uid"]) == "OK"]
    culled = len(pool) - len(approved)
    print(f"\nHARD AUDIT: {len(approved)} pass, {culled} rejected before download", flush=True)

    rows, thumbs, got = [], [], 0
    geom_rejects = {}
    for c in approved:
        if got >= a.target:
            break
        try:
            data = urllib.request.urlopen(urllib.request.Request(
                f"{HF}/{c['glb_path']}", headers={"User-Agent": "Mozilla/5.0"}), timeout=600).read()
        except Exception as e:
            print(f"  dl fail {c['uid'][:8]}: {str(e)[:40]}", flush=True)
            continue
        if not (1024 * 1024 <= len(data) <= 48 * 1024 * 1024):
            continue                       # a premium car GLB is never under 1MB
        ok, why = geometry_ok(data)
        if not ok:
            geom_rejects[why] = geom_rejects.get(why, 0) + 1
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", norm(c["name"] or "vehicle"))[:40].strip("-")
        path = f"training/w4-{slug}--{c['uid'][:8]}.glb"
        try:
            upload(key, "car-meshes", path, data, "model/gltf-binary")
        except Exception as e:
            print(f"  upload fail {slug}: {str(e)[:40]}", flush=True)
            continue
        rows.append({"make": "", "model": "", "source_title": c["name"], "uid": c["uid"],
                     "licence": c["licence"], "creator": c["creator"],
                     "source_url": c["source_url"], "glb_path": path, "bytes": len(data),
                     "faces": c["faces"], "wave": 4, "dataset": "objaverse",
                     "status": "approved-shape [hard audit + geometry gate]"})
        if c.get("thumb"):
            thumbs.append((slug, c["thumb"]))
        got += 1
        if got % 25 == 0:
            print(f"[{got}/{a.target}] staged; latest: {c['name'][:40]}", flush=True)
            merged = prev + rows          # checkpoint the manifest as we go
            upload(key, "car-renders", "finetune/training_candidates.json",
                   json.dumps(merged, indent=1).encode(), "application/json")
        time.sleep(0.3)

    merged = prev + rows
    upload(key, "car-renders", "finetune/training_candidates.json",
           json.dumps(merged, indent=1).encode(), "application/json")
    json.dump(merged, open(f"{OUT}/training_candidates.json", "w"), indent=1)
    print("geometry rejects:", geom_rejects)
    appr = sum(1 for r in merged if str(r.get("status", "")).startswith("approved"))
    print(f"\nWAVE4 STAGED {len(rows)} | manifest total {len(merged)} ({appr} approved)")

    from PIL import Image, ImageDraw
    W, H, COLS, ROWS = 300, 200, 6, 5
    for s0 in range(0, len(thumbs), COLS * ROWS):
        batch = thumbs[s0:s0 + COLS * ROWS]
        sheet = Image.new("RGB", (W * COLS, H * ROWS), (15, 15, 18))
        d = ImageDraw.Draw(sheet)
        for i, (slug, url) in enumerate(batch):
            try:
                im = Image.open(io.BytesIO(urllib.request.urlopen(url, timeout=40).read()))
                sheet.paste(im.convert("RGB").resize((W, H - 18)), ((i % COLS) * W, (i // COLS) * H))
            except Exception:
                pass
            d.text(((i % COLS) * W + 4, (i // COLS) * H + H - 16),
                   f"W4#{s0 + i + 1} {slug[:34]}", fill=(255, 220, 60))
        sheet.save(f"{OUT}/training_wave4_sheet{s0 // (COLS * ROWS) + 1}.jpg", quality=84)
    print(f"review sheets: {len(thumbs)} thumbnails")


if __name__ == "__main__":
    main()
