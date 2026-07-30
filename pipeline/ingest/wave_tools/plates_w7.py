"""Wave-7 GB plate bake: for each published w7 entry, bake UK front/rear
plates (blank character area, accuracy rule) into the base GLB and all colour
variants via pipeline/blender/plates_generic.py. Same URLs are overwritten, so
variantsHash and the render-verified recolour stamps remain valid. Updates
contentHash/fileSizeBytes/platesBaked per entry, then gate + serve.
"""
import hashlib, json, os, re, shutil, struct, subprocess, sys, time, urllib.request

S = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "/home/user/triposr-runpod-worker"
CAT = f"{REPO}/platform/catalogue/catalogue.v2.json"
SB = re.search(r'SBKEY\s*=\s*"([^"]+)"', open(f"{S}/golf_publish.py").read()).group(1)
BASE = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
W = f"{S}/qc_wave7/pwork"
TEX = f"{W}/tex"
os.makedirs(TEX, exist_ok=True)
subprocess.run([sys.executable, f"{REPO}/pipeline/blender/make_plate_textures.py", TEX],
               check=True, capture_output=True)

def free_gb():
    st = os.statvfs("/")
    return st.f_bavail * st.f_frsize / 1e9

def glb_ok(p):
    b = open(p, "rb").read(12)
    return len(b) == 12 and b[:4] == b"glTF" and struct.unpack("<I", b[8:12])[0] == os.path.getsize(p)

def up(path, blob, ctype="model/gltf-binary"):
    for attempt in range(3):
        rq = urllib.request.Request(f"{BASE}/{path}", data=blob, method="POST")
        for h, v in (("apikey", SB), ("Authorization", "Bearer " + SB),
                     ("Content-Type", ctype), ("x-upsert", "true")):
            rq.add_header(h, v)
        try:
            urllib.request.urlopen(rq, timeout=300).read()
            return
        except Exception:
            if attempt == 2:
                raise
            time.sleep(20)

def fetch(url):
    for attempt in range(3):
        try:
            return urllib.request.urlopen(url, timeout=300).read()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(20)

def plate_one(url):
    """Download url, bake plates, re-upload to the SAME path. Returns
    (sha256, size) of the uploaded plated file."""
    name = hashlib.sha1(url.encode()).hexdigest()[:12]
    raw = f"{W}/{name}.glb"
    dec = f"{W}/{name}_dec.glb"
    out = f"{W}/{name}_pl.glb"
    open(raw, "wb").write(fetch(url))
    if not glb_ok(raw):
        raise RuntimeError("bad source glb")
    subprocess.run(["npx", "--yes", "@gltf-transform/cli@4", "copy", raw, dec],
                   capture_output=True, timeout=600)
    if not os.path.exists(dec):
        shutil.copy(raw, dec)
    norm = f"{W}/{name}_norm.glb"
    rn = subprocess.run(["blender", "-b", "--factory-startup", "-noaudio", "--python",
                         f"{S}/qc_wave7/pwork/normalize_upright.py", "--", dec, norm],
                        capture_output=True, timeout=900)
    if b"NORMALIZE_OK" not in rn.stdout or not os.path.exists(norm):
        raise RuntimeError(f"normalize failed: {rn.stdout[-120:]}")
    r = subprocess.run(["blender", "-b", "--factory-startup", "-noaudio", "--python",
                        f"{REPO}/pipeline/blender/plates_generic.py", "--", norm, out, TEX],
                       capture_output=True, timeout=900)
    os.remove(norm)
    if not os.path.exists(out) or not glb_ok(out):
        raise RuntimeError(f"plate bake failed: {r.stdout[-150:]}")
    sm = out + ".dr.glb"
    subprocess.run(["npx", "--yes", "@gltf-transform/cli@4", "draco", out, sm],
                   capture_output=True, timeout=600)
    if os.path.exists(sm) and 0 < os.path.getsize(sm) <= 48_000_000 and glb_ok(sm):
        os.replace(sm, out)
    else:
        raise RuntimeError("plated glb too big or draco failed")
    blob = open(out, "rb").read()
    path = url.split("/object/public/", 1)[1]
    up(path, blob)
    for p in (raw, dec, out):
        if os.path.exists(p):
            os.remove(p)
    return hashlib.sha256(blob).hexdigest(), len(blob)

cat = json.load(open(CAT))
targets = [e for e in cat
           if e.get("pipelineVersion", "").startswith("publish-batch-w7")
           and e.get("publicationStatus") == "approved"
           and not e.get("platesBaked")]
print(f"plate targets: {len(targets)}", flush=True)

done = 0
for i, e in enumerate(targets):
    aid = e["assetId"]
    try:
        if free_gb() < 1.0:
            print("DISK GUARD: <1GB free, aborting resumably", flush=True)
            sys.exit(6)
        sha, size = plate_one(e["desktopGlbUrl"])
        for col, curl in (e.get("colourVariants") or {}).items():
            plate_one(curl)
        cat2 = json.load(open(CAT))
        for x in cat2:
            if x["assetId"] == aid:
                x["platesBaked"] = True
                x["contentHash"] = sha
                x["fileSizeBytes"] = size
                x["mobileFileSizeBytes"] = size
                x["notes"].append("w7 plates: GB front/rear baked into base + all colour "
                                  "variants (blank character area per accuracy rule)")
                break
        json.dump(cat2, open(CAT, "w"), indent=1, ensure_ascii=False)
        done += 1
        nv = len(e.get("colourVariants") or {})
        print(f"[{i+1}/{len(targets)}] plated {aid} (base + {nv} variants, "
              f"disk {free_gb():.1f}G)", flush=True)
    except Exception as ex:
        print(f"[{i+1}] {aid}: ITEM FAIL {type(ex).__name__} {str(ex)[:120]}", flush=True)

g = subprocess.run([sys.executable, f"{REPO}/pipeline/qc/gate_catalogue.py"],
                   capture_output=True, text=True)
print(g.stdout.strip()[-300:], flush=True)
if g.returncode != 0:
    sys.exit("GATE FAIL — catalogue NOT served")
data = open(CAT, "rb").read()
for path in ("car-renders/resolver/catalogue.v2.json", "car-renders/catalogue.v2.json"):
    up(path, data, "application/json")
print(f"PLATES_W7_DONE plated={done} of {len(targets)} served both paths", flush=True)
