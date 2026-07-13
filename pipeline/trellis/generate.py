"""generate.py — STAGE 3: generate multiple TRELLIS.2 candidates.

Submits each prepped image at several seeds to the TRELLIS.2-4B RunPod endpoint
and downloads every candidate GLB. More candidates -> better chance one is clean.

Endpoint input (from trellis/handler.py):
  image_b64 | image_url   (RGBA cutout -> on-worker bg-removal skipped)
  seed                    (vary per candidate)
  decimation_target       (face budget; 200k web / 500k default / 800k hi-detail)
  texture_size            (1024 mobile / 2048 default / 4096 hero)

Deps: python3 (stdlib urllib) + the repo's rp.py helper + RUNPOD key.

Run:
  python pipeline/trellis/generate.py --in pipeline/build/prepped \
      --out pipeline/build/candidates --seeds 0,1,2,3 --texture 2048 --decimate 500000

HONEST LIMITATIONS (stage 3):
  • This handler runs SINGLE-IMAGE per call. True multi-view FUSION (feeding all
    angles into one reconstruction) is a TRELLIS.2 multiimage-pipeline upgrade to
    handler.py — not yet wired. Until then we generate per-image candidates and
    pick the best; the back/underside of the car is still hallucinated.
  • Cold start is minutes; A5000-class GPU ~2-6 min/candidate.
  • Higher texture_size/decimation_target = sharper but heavier + slower.
"""
import os, sys, json, time, base64, argparse, subprocess, urllib.request

EP = "nd0fagqlr5z2ur"   # TRELLIS.2-4B
RP = os.path.join(os.path.dirname(__file__), "..", "..", "scratchpad", "rp.py")  # RunPod helper

def submit(img_path, seed, texture, decimate):
    b64 = base64.b64encode(open(img_path, "rb").read()).decode()
    payload = {"input": {"image_b64": b64, "seed": seed,
                         "texture_size": texture, "decimation_target": decimate}}
    tmp = "/tmp/_trellis_in.json"; json.dump(payload, open(tmp, "w"))
    out = subprocess.run(["python3", RP, "run", EP, tmp], capture_output=True, text=True).stdout
    return json.loads(out.split("\n", 1)[1])["id"]

def status(jid):
    out = subprocess.run(["python3", RP, "status", EP, jid], capture_output=True, text=True).stdout
    return json.loads(out.split("\n", 1)[1])

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--texture", type=int, default=2048)
    ap.add_argument("--decimate", type=int, default=500000)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    seeds = [int(s) for s in a.seeds.split(",")]
    imgs = sorted([os.path.join(a.inp, f) for f in os.listdir(a.inp) if f.endswith(".png")])
    print(f"submitting {len(imgs)} images x {len(seeds)} seeds = {len(imgs)*len(seeds)} candidates")
    # ensure workers are up (endpoint scales to zero)
    subprocess.run(["python3", RP, "patch_endpoint", EP, '{"workersMax":2}'], capture_output=True)

    jobs = {}
    for img in imgs:
        for s in seeds:
            jid = submit(img, s, a.texture, a.decimate)
            jobs[jid] = (os.path.splitext(os.path.basename(img))[0], s)
            print("submitted", jid, jobs[jid]); time.sleep(1)

    pending = dict(jobs); t0 = time.time(); manifest = []
    while pending and time.time() - t0 < 3600:
        time.sleep(20)
        for jid, (name, s) in list(pending.items()):
            d = status(jid)
            if d["status"] in ("COMPLETED", "FAILED"):
                del pending[jid]
                url = (d.get("output") or {}).get("glb_url")
                if url:
                    dst = os.path.join(a.out, f"{name}_seed{s}.glb")
                    urllib.request.urlretrieve(url, dst)
                    manifest.append({"file": dst, "image": name, "seed": s, "url": url})
                    print("DONE", os.path.basename(dst))
                else:
                    print("FAIL", name, s, str(d.get("error"))[:80])
    json.dump(manifest, open(os.path.join(a.out, "candidates.json"), "w"), indent=1)
    print(f"\n{len(manifest)} candidates downloaded -> {a.out}")
    subprocess.run(["python3", RP, "patch_endpoint", EP, '{"workersMax":0}'], capture_output=True)  # scale back down
