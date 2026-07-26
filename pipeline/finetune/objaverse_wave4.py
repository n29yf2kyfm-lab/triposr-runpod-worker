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
                 r"stylised|anime|chibi|cute|voxel|blocky|fantasy|sci-?fi|scifi|futuristic|alien|"
                 r"cyberpunk|apocalypse|zombie|mad ?max|steampunk|hover|flying ?car|toy|miniature|"
                 r"papercraft|origami|clay|sculpt(ing)? ?practice|study|exercise|tutorial|"
                 r"my ?first|beginner|practice|wip|placeholder|dummy|free ?(download|asset|model)|"
                 r"rigged ?for|scan|photogrammetry|lidar|wreck|destroyed|damaged|burnt|rusty|"
                 r"abandoned|sticker|logo|badge|diorama|scene|pack|bundle|collection)")


def norm(s):
    return unicodedata.normalize("NFKD", (s or "").lower()).encode("ascii", "ignore").decode()


def gz(u, timeout=300):
    rq = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
    return json.loads(gzip.decompress(urllib.request.urlopen(rq, timeout=timeout).read()))


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
            hit = BAD.search(txt)
            verdict[u] = f"game/stylised: {hit.group(0)}" if hit else "OK"
        if (i + 1) % 30 == 0:
            ok = sum(1 for v in verdict.values() if v == "OK")
            print(f"  {i+1}/{len(shards)} shards, {ok} passing", flush=True)

    approved = [c for c in pool if verdict.get(c["uid"]) == "OK"]
    culled = len(pool) - len(approved)
    print(f"\nHARD AUDIT: {len(approved)} pass, {culled} rejected before download", flush=True)

    rows, thumbs, got = [], [], 0
    for c in approved:
        if got >= a.target:
            break
        try:
            data = urllib.request.urlopen(urllib.request.Request(
                f"{HF}/{c['glb_path']}", headers={"User-Agent": "Mozilla/5.0"}), timeout=600).read()
        except Exception as e:
            print(f"  dl fail {c['uid'][:8]}: {str(e)[:40]}", flush=True)
            continue
        if not (200 * 1024 <= len(data) <= 48 * 1024 * 1024):
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
                     "status": "approved-shape [hard audit pre-download]"})
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
