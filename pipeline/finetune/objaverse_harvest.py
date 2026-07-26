#!/usr/bin/env python3
"""objaverse_harvest.py — wave 3: harvest permissively-licensed road-vehicle
meshes from Objaverse for the Alam-3D training set, biased to the body styles
the current dataset lacks (vans, 4x4s, pickups, estates).

Why Objaverse: it is the open dataset TRELLIS itself was trained on, every
object carries an explicit licence, and the assets are artist-made (crisp
seams and real lamp geometry — the things a shape model needs to learn).
Deliberately NOT used: outputs of commercial AI-3D services. Training on
another model's generations inherits its defects and would poison the
provenance manifest that a licensing deal depends on.

Two phases:
  --scan            stream the 160 metadata shards, keep licence-clean
                    vehicle candidates -> objaverse_candidates.json
  --fetch N         download the top N, stage to car-meshes/training/,
                    extend finetune/training_candidates.json, build
                    numbered review sheets for the owner's cull pass

Env: SB_KEY (Supabase service key). No secrets in this file.
"""
import argparse, gzip, io, json, os, re, sys, time, unicodedata, urllib.request

HF = "https://huggingface.co/datasets/allenai/objaverse/resolve/main"
SUPA = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
OK_LICENCES = {"by", "cc0"}          # attribution or public domain only
OUT = os.environ.get("HARVEST_OUT", "/tmp")

# body styles the dataset is thin on get a rank bonus
PRIORITY = {"van": 6, "transit": 6, "sprinter": 6, "transporter": 6, "panel van": 7,
            "minivan": 5, "mpv": 5, "camper": 4, "motorhome": 4,
            "pickup": 6, "ute": 5, "truck": 4, "lorry": 4, "flatbed": 3,
            "4x4": 6, "suv": 5, "offroad": 5, "off-road": 5, "jeep": 5,
            "land rover": 6, "defender": 6, "estate": 5, "wagon": 4,
            "hatchback": 2, "sedan": 2, "saloon": 2, "coupe": 1, "car": 1}
VEHICLE = re.compile(r"\b(car|auto(mobile)?|vehicle|van|truck|lorry|pickup|ute|suv|4x4|jeep|"
                     r"sedan|saloon|hatchback|estate|wagon|coupe|minivan|mpv|camper|"
                     r"motorhome|transit|sprinter|transporter|crossover)\b")
# things that teach the wrong shape (mirrors the wave-1/2 audit findings)
BLOCK = re.compile(r"\b(f1|formula|le ?mans|lmp|gt3|gt500|nascar|rally|race|racing|drift|"
                   r"concept|vision|prototype|hypercar|widebody|liberty ?walk|rocket ?bunny|"
                   r"pandem|bodykit|stance|lowrider|monster ?truck|tank|military|armou?red|"
                   r"police|ambulance|fire ?(truck|engine)|garbage|tow ?truck|tractor|trailer|"
                   r"train|railcar|locomotive|boat|ship|plane|aircraft|helicopter|spaceship|"
                   r"sci-?fi|futuristic|cartoon|toy|lego|voxel|low ?poly|lowpoly|stylized|"
                   r"stylised|wreck|destroyed|damaged|burnt|rusty|abandoned|interior only|"
                   r"wheel|rim|tire|tyre|engine|seat|steering|dashboard|part[s]?\b)")


def norm(s):
    return unicodedata.normalize("NFKD", (s or "").lower()).encode("ascii", "ignore").decode()


def gz_json(url, timeout=300):
    rq = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.loads(gzip.decompress(urllib.request.urlopen(rq, timeout=timeout).read()))


def score(text, faces):
    """Rank: body-style need first, then a sane face budget (detail without bloat)."""
    s = sum(w for k, w in PRIORITY.items() if k in text)
    if 30_000 <= (faces or 0) <= 900_000:
        s += 3
    elif (faces or 0) > 3_000_000:
        s -= 4
    return s


def scan():
    paths = gz_json(f"{HF}/object-paths.json.gz")
    shards = sorted({p.split("/")[1] for p in paths.values()})
    print(f"{len(paths)} objects across {len(shards)} shards", flush=True)
    cands = []
    for i, sh in enumerate(shards):
        try:
            meta = gz_json(f"{HF}/metadata/{sh}.json.gz")
        except Exception as e:
            print(f"  shard {sh}: {str(e)[:60]}", flush=True)
            continue
        for uid, m in meta.items():
            if (m.get("license") or "").lower() not in OK_LICENCES:
                continue
            tags = " ".join(t.get("name", "") for t in (m.get("tags") or []))
            cats = " ".join(c.get("name", "") for c in (m.get("categories") or []))
            text = norm(f"{m.get('name','')} {tags} {cats}")
            if not VEHICLE.search(text) or BLOCK.search(text):
                continue
            faces = m.get("faceCount") or 0
            if faces < 5_000:                      # too coarse to teach shape
                continue
            th = (m.get("thumbnails") or {}).get("images") or []
            cands.append({
                "uid": uid, "name": m.get("name"), "licence": m.get("license"),
                "creator": ((m.get("user") or {}).get("username")),
                "faces": faces, "score": score(text, faces),
                "glb_path": paths[uid],
                "thumb": (sorted(th, key=lambda x: -(x.get("width") or 0))[0]["url"] if th else None),
                "source_url": m.get("viewerUrl") or f"https://sketchfab.com/3d-models/{uid}",
            })
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(shards)} shards, {len(cands)} candidates", flush=True)
    cands.sort(key=lambda c: -c["score"])
    json.dump(cands, open(f"{OUT}/objaverse_candidates.json", "w"), indent=1)
    print(f"SCAN DONE: {len(cands)} licence-clean vehicle candidates -> {OUT}/objaverse_candidates.json")


def upload(key, bucket, path, data, ctype):
    rq = urllib.request.Request(f"{SUPA}/{bucket}/{path}", data=data, method="POST")
    for h, v in (("apikey", key), ("Authorization", "Bearer " + key),
                 ("Content-Type", ctype), ("x-upsert", "true")):
        rq.add_header(h, v)
    urllib.request.urlopen(rq, timeout=300).read()


def fetch(n):
    key = os.environ.get("SB_KEY")
    if not key:
        sys.exit("SB_KEY missing from env")
    cands = json.load(open(f"{OUT}/objaverse_candidates.json"))
    prev = json.loads(urllib.request.urlopen(
        f"{SUPA}/public/car-renders/finetune/training_candidates.json?cb=1", timeout=120).read())
    seen = {c.get("uid") for c in prev}

    rows, thumbs, got = [], [], 0
    for c in cands:
        if got >= n:
            break
        if c["uid"] in seen:
            continue
        try:
            data = urllib.request.urlopen(urllib.request.Request(
                f"{HF}/{c['glb_path']}", headers={"User-Agent": "Mozilla/5.0"}), timeout=600).read()
        except Exception as e:
            print(f"  dl fail {c['uid'][:8]}: {str(e)[:50]}", flush=True)
            continue
        if not (200 * 1024 <= len(data) <= 48 * 1024 * 1024):
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", norm(c["name"] or "vehicle"))[:40].strip("-")
        path = f"training/obj-{slug}--{c['uid'][:8]}.glb"
        try:
            upload(key, "car-meshes", path, data, "model/gltf-binary")
        except Exception as e:
            print(f"  upload fail {slug}: {str(e)[:50]}", flush=True)
            continue
        rows.append({"make": "", "model": "", "source_title": c["name"], "uid": c["uid"],
                     "licence": c["licence"], "creator": c["creator"],
                     "source_url": c["source_url"], "glb_path": path,
                     "bytes": len(data), "faces": c["faces"], "wave": 3,
                     "dataset": "objaverse", "status": "candidate-unreviewed"})
        if c["thumb"]:
            thumbs.append((slug, c["thumb"]))
        got += 1
        print(f"[{got}/{n}] {c['name'][:44]} ({c['licence']}, {c['faces']} faces, {len(data)//1024}KB)", flush=True)
        time.sleep(0.5)

    merged = prev + rows
    upload(key, "car-renders", "finetune/training_candidates.json",
           json.dumps(merged, indent=1).encode(), "application/json")
    json.dump(merged, open(f"{OUT}/training_candidates.json", "w"), indent=1)
    print(f"\nWAVE3 STAGED {len(rows)} (manifest total {len(merged)})")

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
                   f"W3#{s0 + i + 1} {slug[:34]}", fill=(255, 220, 60))
        out = f"{OUT}/training_wave3_sheet{s0 // (COLS * ROWS) + 1}.jpg"
        sheet.save(out, quality=84)
        print("sheet:", out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--fetch", type=int, default=0)
    a = ap.parse_args()
    if a.scan:
        scan()
    if a.fetch:
        fetch(a.fetch)
