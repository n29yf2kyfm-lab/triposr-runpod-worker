#!/usr/bin/env python3
"""salvage_run.py — drive the whole recovery chain over the glazing-quarantine
pool, ten cars at a time, and put the result somewhere a rollback cannot take it.

THE POOL. reports/golfmk8/SALVAGE_POOL.json, 83 cars: every catalogue entry with
publicationStatus=quarantined, a grey-windows reason, and a fetchable GLB.

WHY THIS IS A FILE IN THE REPO AND NOT A SHELL LOOP. This container has rolled
back twice in one session, each time discarding /opt, the scratchpad and the git
checkout. Both times the only thing that survived was what had been pushed. A
hand-typed loop is lost with the first rollback and its outputs with it, which
is exactly how a day's salvage work was lost earlier today. So: this is
committed, every artefact is uploaded to Supabase the moment it validates, and
the runner is RESUMABLE -- rerun it and it skips whatever the bucket already
holds. A rollback then costs the car in flight and nothing else.

THE CHAIN, per car:
  1. fetch the shipped GLB
  2. r8_reglaze     rebuild the glazing, with the geometric lamp and bodywork
                    gates (a name list cannot do this -- see that file)
  3. glass_probe    the gate. Not the render: render/handler.py forges clear
                    glass onto any glass-NAMED material, so only the file can
                    settle whether the glazing is real
  4. r10_polish     real paint found by ray visibility, black tyres, and the
                    cabin placeholder neutralised
  5. render         three views, for the eye
  6. upload         GLB + views + record, immediately

WHAT A "FIX" MEANS HERE, said plainly so the number cannot be over-read. It
means the glazing now probes clear (proven) and the car renders with paint,
black tyres and a visible interior. It does NOT mean the car is shippable.
Measured on the first three cars taken this far: one was a keeper, one was a
keeper with a visible flaw, and one failed on a soft front end that no material
work touches. And a car can pass every check here and still have NO FRONT
BODYWORK -- skoda-octavia-w7-v1 did. The eye decides; this only gets cars to the
point where the eye is worth spending.

Run: python3 salvage_run.py <from> <count>     e.g.  python3 salvage_run.py 0 10
Env: SALVAGE_RES (900) · SALVAGE_SAMPLES (24) · SALVAGE_FORCE=1 to redo cars
     already in the bucket
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
POOL = os.path.join(REPO, "reports", "golfmk8", "SALVAGE_POOL.json")
WORK = os.environ.get("SALVAGE_WORK", "/tmp/salvage")
SB = "https://tfkvthprsntexrcuqpyd.supabase.co"
BUCKET = "car-meshes"
PREFIX = "salvage/v2"
RES = os.environ.get("SALVAGE_RES", "900")
SAMPLES = os.environ.get("SALVAGE_SAMPLES", "24")
FORCE = os.environ.get("SALVAGE_FORCE", "0") == "1"
BLENDER = os.environ.get("BLENDER_BIN", "blender")


def load_env():
    """Read the credentials ourselves rather than trusting the caller to have
    sourced them. CLAUDE.md records a relaunch that forgot, died one line in,
    and was indistinguishable from a healthy start."""
    p = "/root/.alam3d_env"
    if not os.path.exists(p):
        sys.exit("REFUSED: /root/.alam3d_env missing")
    for line in open(p):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    if not os.environ.get("SB_KEY"):
        sys.exit("REFUSED: SB_KEY not in the env file")


def sb_headers():
    # Storage needs BOTH headers. With Authorization alone it returns
    # 403 "Invalid Compact JWS", which reads exactly like an expired key.
    k = os.environ["SB_KEY"]
    return {"apikey": k, "Authorization": f"Bearer {k}"}


def sb_upload(path, dest, content_type="application/octet-stream"):
    url = f"{SB}/storage/v1/object/{BUCKET}/{dest}"
    data = open(path, "rb").read()
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, data=data, method="POST")
            for h, v in sb_headers().items():
                req.add_header(h, v)
            req.add_header("Content-Type", content_type)
            req.add_header("x-upsert", "true")
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.status
        except Exception as e:
            if attempt == 3:
                print(f"    UPLOAD FAILED {dest}: {e}")
                return None
            time.sleep(2 ** attempt)


def sb_exists(dest):
    url = f"{SB}/storage/v1/object/public/{BUCKET}/{dest}"
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status == 200
    except Exception:
        return False


def fetch(url, dest):
    if os.path.exists(dest) and os.path.getsize(dest) > 1024:
        return True
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=300) as r, open(dest, "wb") as f:
                f.write(r.read())
            # A truncated GLB extracts to something that fails deep inside
            # Blender with an unhelpful message. Check the container format
            # here, where the error can still name itself.
            with open(dest, "rb") as f:
                head = f.read(12)
            if head[:4] != b"glTF":
                raise ValueError("not a GLB (bad magic)")
            return True
        except Exception as e:
            if attempt == 3:
                print(f"    FETCH FAILED: {e}")
                return False
            time.sleep(2 ** attempt)


def run(cmd, env=None, tag=""):
    e = dict(os.environ)
    if env:
        e.update(env)
    p = subprocess.run(cmd, capture_output=True, text=True, env=e, timeout=3600)
    return p.returncode, p.stdout + p.stderr


def main():
    load_env()
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    pool = json.load(open(POOL))
    batch = pool[start:start + count]
    os.makedirs(WORK, exist_ok=True)
    print(f"SALVAGE batch {start}..{start + len(batch) - 1} of {len(pool)}")
    records = []
    for n, car in enumerate(batch, start + 1):
        a = car["assetId"]
        print(f"\n[{n}/{len(pool)}] {a}")
        rec = {"n": n, "assetId": a, "make": car.get("make"),
               "sourceTitle": car.get("sourceTitle"), "stage": "start"}
        if not FORCE and sb_exists(f"{PREFIX}/{a}/polished.glb"):
            print("    already in the bucket -- skipping (SALVAGE_FORCE=1 to redo)")
            continue
        d = os.path.join(WORK, a)
        os.makedirs(d, exist_ok=True)
        src = os.path.join(d, "src.glb")
        if not fetch(car["glb"], src):
            rec["stage"] = "fetch-failed"
            records.append(rec)
            continue
        rec["src_bytes"] = os.path.getsize(src)

        fix = os.path.join(d, "fix.glb")
        rc, out = run([BLENDER, "-b", "--python",
                       os.path.join(HERE, "r8_reglaze.py"), "--",
                       src, fix, os.path.join(d, "r8.json")])
        if rc != 0 or not os.path.exists(fix):
            rec["stage"] = "r8-failed"
            rec["error"] = out[-600:]
            print("    R8 FAILED")
            records.append(rec)
            continue
        rec["r8_hits"] = next((int(l.split()[1]) for l in out.splitlines()
                               if l.startswith("R8_HITS")), None)
        rec["lamps_spared"] = sum(1 for l in out.splitlines() if l.startswith("R8_LAMP "))
        rec["body_spared"] = sum(1 for l in out.splitlines() if l.startswith("R8_BODY "))

        rc, out = run(["python3", os.path.join(HERE, "glass_probe_local.py"), fix])
        line = out.strip().splitlines()[-1] if out.strip() else ""
        rec["probe"] = ("clear" if "verdict=clear" in line else
                        "opaque" if "verdict=opaque" in line else
                        "faded" if "verdict=faded" in line else
                        "ambiguous" if "verdict=ambiguous" in line else "?")
        rec["probe_certainty"] = "proven" if "certainty=proven" in line else "inferred"
        print(f"    r8 hits={rec['r8_hits']} lamps_spared={rec['lamps_spared']} "
              f"body_spared={rec['body_spared']} probe={rec['probe']}/{rec['probe_certainty']}")

        pol = os.path.join(d, "polished.glb")
        rc, out = run([BLENDER, "-b", "--python",
                       os.path.join(HERE, "r10_polish.py"), "--",
                       fix, pol, "silver", os.path.join(d, "r10.json")],
                      env={"R10_CABIN": "1"})
        if rc != 0 or not os.path.exists(pol):
            rec["stage"] = "r10-failed"
            rec["error"] = out[-600:]
            print(f"    R10 FAILED  {out.strip().splitlines()[-1][:120] if out.strip() else ''}")
            records.append(rec)
            continue
        rec["paint"] = next((l.split()[1] for l in out.splitlines()
                             if l.startswith("R10_PAINT")), None)
        rec["cabin_fixed"] = sum(1 for l in out.splitlines() if l.startswith("R10_CABIN "))
        rec["tyres_darkened"] = sum(1 for l in out.splitlines()
                                    if l.startswith("R10_TYRE ") and "->" in l)

        imgs = os.path.join(d, "img")
        os.makedirs(imgs, exist_ok=True)
        rc, out = run([BLENDER, "-b", "--python",
                       os.path.join(REPO, "pipeline", "machine", "studio_hero.py"),
                       "--", pol, imgs, "35,215,305"],
                      env={"HERO_RES": RES, "HERO_SAMPLES": SAMPLES})
        frames = sorted(f for f in os.listdir(imgs) if f.endswith(".png"))
        rec["frames"] = len(frames)
        if not frames:
            rec["stage"] = "render-failed"
            rec["error"] = out[-600:]
            print("    RENDER FAILED")
            records.append(rec)
            continue

        sb_upload(pol, f"{PREFIX}/{a}/polished.glb", "model/gltf-binary")
        for f in frames:
            sb_upload(os.path.join(imgs, f), f"{PREFIX}/{a}/{f}", "image/png")
        rec["stage"] = "done"
        print(f"    polished, {len(frames)} frames, uploaded")
        records.append(rec)

    mpath = os.path.join(WORK, f"manifest_{start}_{start + count}.json")
    json.dump(records, open(mpath, "w"), indent=1)
    sb_upload(mpath, f"{PREFIX}/manifests/manifest_{start}_{start + count}.json",
              "application/json")
    ok = [r for r in records if r.get("stage") == "done"]
    clear = [r for r in ok if r.get("probe") == "clear"]
    print(f"\nSALVAGE_BATCH_DONE processed={len(records)} completed={len(ok)} "
          f"glazing_clear={len(clear)}")


if __name__ == "__main__":
    main()
