#!/usr/bin/env python3
"""harvest_render.py — screen a harvester manifest by RENDERING it.

WHAT IT IS FOR. A harvest manifest is a raw net cast over Objaverse: it is
scored on tags and titles, and neither is reliable. The 38-line manifest this
was written for contains "Boat12", "Spaceship in Warp" and
"purple-guy-animatronic" alongside genuine cars. No amount of metadata reading
sorts that out -- the only thing that says what a mesh IS, is looking at it.

So this does the cheapest honest thing: fetch, render three views, upload,
delete the mesh. It deliberately does NOT reglaze, paint or polish. Those steps
exist to stop a good car failing for a material reason, and they would be a
waste of an hour on a manifest where a third of the entries may be furniture.
Screen first, polish what survives.

THE LOCAL `path` IN A MANIFEST IS NOT OURS. Harvest manifests carry the path on
the machine that built them (/Users/.../harvester/models/...). Only `url` is
fetchable from here, and it is checked against the recorded sha256 -- a
truncated GLB otherwise fails deep inside Blender with a message that names
nothing.

MESHES ARE DELETED AFTER RENDERING. 38 entries is 632 MB and a manifest can be
much larger; this container has hit 100% disk before and that is when the
rollbacks started. Renders are uploaded as they are made, so a rollback costs
the entry in flight and nothing else -- the same rule the salvage runner earned
over four rollbacks in one session.

Run: python3 harvest_render.py <manifest.jsonl> [from] [count]
Env: HARVEST_RES (900) · HARVEST_SAMPLES (24) · HARVEST_KEEP=1 to keep meshes
"""
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
WORK = os.environ.get("HARVEST_WORK", "/tmp/obj")
SB = "https://tfkvthprsntexrcuqpyd.supabase.co"
BUCKET = "car-meshes"
PREFIX = "harvest/v1"
RES = os.environ.get("HARVEST_RES", "900")
SAMPLES = os.environ.get("HARVEST_SAMPLES", "24")
KEEP = os.environ.get("HARVEST_KEEP", "0") == "1"
BLENDER = os.environ.get("BLENDER_BIN", "blender")


def load_env():
    p = "/root/.alam3d_env"
    if not os.path.exists(p):
        sys.exit("REFUSED: /root/.alam3d_env missing")
    for line in open(p):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def sb_upload(path, dest, ct="application/octet-stream"):
    k = os.environ["SB_KEY"]
    url = f"{SB}/storage/v1/object/{BUCKET}/{dest}"
    data = open(path, "rb").read()
    for a in range(4):
        try:
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("apikey", k)
            req.add_header("Authorization", f"Bearer {k}")
            req.add_header("Content-Type", ct)
            req.add_header("x-upsert", "true")
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.status
        except Exception as e:
            if a == 3:
                print(f"    upload failed {dest}: {e}")
                return None
            time.sleep(2 ** a)


def sb_exists(dest):
    try:
        req = urllib.request.Request(
            f"{SB}/storage/v1/object/public/{BUCKET}/{dest}", method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status == 200
    except Exception:
        return False


def fetch(url, dest, sha=None):
    for a in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
            tok = os.environ.get("HF_TOKEN")
            if tok and "huggingface.co" in url:
                req.add_header("Authorization", f"Bearer {tok}")
            with urllib.request.urlopen(req, timeout=600) as r, open(dest, "wb") as f:
                f.write(r.read())
            with open(dest, "rb") as f:
                head = f.read(4)
            if head != b"glTF":
                raise ValueError("not a GLB (bad magic) -- probably an error page")
            if sha:
                h = hashlib.sha256(open(dest, "rb").read()).hexdigest()
                if h != sha:
                    raise ValueError(f"sha256 mismatch (got {h[:12]}, want {sha[:12]})")
            return True
        except Exception as e:
            if a == 3:
                print(f"    FETCH FAILED: {e}")
                return False
            time.sleep(2 ** a)


def main():
    load_env()
    man = sys.argv[1]
    start = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    count = int(sys.argv[3]) if len(sys.argv) > 3 else 10 ** 6
    rows = [json.loads(l) for l in open(man) if l.strip()]
    batch = rows[start:start + count]
    os.makedirs(WORK, exist_ok=True)
    recs = []
    for i, r in enumerate(batch, start + 1):
        uid = r["uid"].split(":")[-1]
        name = (r.get("meta") or {}).get("name") or uid
        print(f"\n[{i}/{len(rows)}] {name}  ({uid[:12]})")
        rec = {"n": i, "uid": uid, "name": name,
               "bytes": r.get("bytes"), "stage": "start",
               "tags": [t.get("name") for t in (r.get("meta") or {}).get("tags", [])][:8]}
        if sb_exists(f"{PREFIX}/{uid}/v000.png"):
            print("    already rendered -- skipping")
            continue
        d = os.path.join(WORK, uid)
        os.makedirs(d, exist_ok=True)
        glb = os.path.join(d, "m.glb")
        if not (os.path.exists(glb) and os.path.getsize(glb) > 1024):
            if not fetch(r["url"], glb, r.get("sha256")):
                rec["stage"] = "fetch-failed"
                recs.append(rec)
                continue
        imgs = os.path.join(d, "img")
        os.makedirs(imgs, exist_ok=True)
        p = subprocess.run(
            [BLENDER, "-b", "--python",
             os.path.join(REPO, "pipeline", "machine", "eyeball_views.py"),
             "--", glb, imgs],
            capture_output=True, text=True, timeout=2400,
            env={**os.environ, "EYEBALL_RES": RES, "EYEBALL_SAMPLES": SAMPLES})
        frames = sorted(f for f in os.listdir(imgs) if f.endswith(".png"))
        # keep three spread-out views rather than all seven: this is a screen,
        # not an audit, and three is enough to say "car / not a car / junk"
        want = [f for f in ("a000.png", "a135.png", "a225.png") if f in frames]
        if not want:
            rec["stage"] = "render-failed"
            rec["error"] = (p.stdout + p.stderr)[-500:]
            print("    RENDER FAILED")
            recs.append(rec)
        else:
            for k, f in enumerate(want):
                sb_upload(os.path.join(imgs, f), f"{PREFIX}/{uid}/v{k:03d}.png", "image/png")
            rec["stage"] = "done"
            rec["frames"] = len(want)
            print(f"    rendered {len(want)} views, uploaded")
            recs.append(rec)
        if not KEEP:
            try:
                os.remove(glb)
            except OSError:
                pass
    mp = os.path.join(WORK, f"harvest_manifest_{start}.json")
    json.dump(recs, open(mp, "w"), indent=1)
    sb_upload(mp, f"{PREFIX}/manifests/harvest_{start}.json", "application/json")
    ok = [r for r in recs if r.get("stage") == "done"]
    print(f"\nHARVEST_DONE processed={len(recs)} rendered={len(ok)}")


if __name__ == "__main__":
    main()
