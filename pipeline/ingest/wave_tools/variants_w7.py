"""Wave-7 colour variants: for every published w7 entry with a real body-paint
material, bake the 8-colour DVLA palette (flat respray via bake_colour.py),
upload, write colourVariants, run the render recolour audit (parallel,
stampless), stamp sequentially, demote failures to single-neutral, then
gate_catalogue + serve BOTH paths. Mirrors the wave-6 variants flow.
"""
import concurrent.futures as cf
import json, os, re, shutil, struct, subprocess, sys, time, urllib.request

S = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "/home/user/triposr-runpod-worker"
CAT = f"{REPO}/platform/catalogue/catalogue.v2.json"
SB = re.search(r'SBKEY\s*=\s*"([^"]+)"', open(f"{S}/golf_publish.py").read()).group(1)
BASE = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
W = f"{S}/qc_wave7/vwork"
os.makedirs(W, exist_ok=True)

def hexlin(h):
    def c(x):
        x = int(x, 16) / 255
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
    return f"{c(h[0:2]):.6f},{c(h[2:4]):.6f},{c(h[4:6]):.6f}"

PAL = {"grey": "6f7276", "silver": "b6b9be", "black": "1b1d20", "white": "e4e6e8",
       "blue": "1f4fb0", "red": "b11e1e", "green": "1f6b3a", "yellow": "d9b310"}

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

cat = json.load(open(CAT))
targets = [e for e in cat
           if e.get("pipelineVersion", "").startswith("publish-batch-w7")
           and e.get("publicationStatus") == "approved"
           and not e.get("colourVariants")
           and e.get("paintMaterialNames")]
print(f"variants targets: {len(targets)}", flush=True)

done_bake = []
for i, e in enumerate(targets):
    aid = e["assetId"]
    try:
        if free_gb() < 1.0:
            print("DISK GUARD: <1GB free, aborting resumably", flush=True)
            sys.exit(6)
        src = f"{W}/{aid}.glb"
        if not os.path.exists(src):
            blob = fetch(e["desktopGlbUrl"])
            open(src, "wb").write(blob)
        if not glb_ok(src):
            print(f"[{i+1}] {aid}: source glb bad, skip", flush=True)
            continue
        # local Blender 4.0.2 lacks the Draco import decoder; decompress first
        dec = f"{W}/{aid}_dec.glb"
        if not os.path.exists(dec):
            subprocess.run(["npx", "--yes", "@gltf-transform/cli@4", "copy", src, dec],
                           capture_output=True, timeout=600)
            if not os.path.exists(dec):
                shutil.copy(src, dec)
        src = dec
        mats = ",".join(e["paintMaterialNames"])
        cv = {}
        ok = True
        for col, hexv in PAL.items():
            out = f"{W}/{aid}__{col}.glb"
            if not os.path.exists(out):
                r = subprocess.run(["blender", "-b", "--factory-startup", "-noaudio",
                                    "--python", f"{S}/bake_colour.py", "--",
                                    src, out, hexlin(hexv), mats],
                                   capture_output=True, timeout=900)
            if not os.path.exists(out) or not glb_ok(out):
                print(f"[{i+1}] {aid}: bake {col} FAILED", flush=True)
                ok = False
                break
            if os.path.getsize(out) > 48_000_000:
                sm = out + ".dr.glb"
                subprocess.run(["npx", "--yes", "@gltf-transform/cli@4", "draco", out, sm],
                               capture_output=True, timeout=600)
                if os.path.exists(sm) and 0 < os.path.getsize(sm) <= 48_000_000 and glb_ok(sm):
                    os.replace(sm, out)
                else:
                    print(f"[{i+1}] {aid}: {col} still too big after draco", flush=True)
                    ok = False
                    break
            dest = f"car-meshes/finished/{e['make']}/{aid}__{col}.glb"
            up(dest, open(out, "rb").read())
            cv[col] = f"{BASE}/public/{dest}"
            os.remove(out)
        os.remove(src)
        orig = f"{W}/{aid}.glb"
        if os.path.exists(orig):
            os.remove(orig)
        if not ok:
            continue
        # write variants into the catalogue (fresh read-modify-write)
        cat2 = json.load(open(CAT))
        for x in cat2:
            if x["assetId"] == aid:
                x["colourVariants"] = cv
                break
        json.dump(cat2, open(CAT, "w"), indent=1, ensure_ascii=False)
        done_bake.append(aid)
        print(f"[{i+1}/{len(targets)}] baked+uploaded 8 colours {aid} "
              f"(disk {free_gb():.1f}G)", flush=True)
    except Exception as ex:
        print(f"[{i+1}] {aid}: ITEM FAIL {type(ex).__name__} {str(ex)[:100]}", flush=True)

cat_now = json.load(open(CAT))
missing = [e for e in cat_now
           if e.get("pipelineVersion", "").startswith("publish-batch-w7")
           and e.get("publicationStatus") == "approved"
           and not e.get("colourVariants") and e.get("paintMaterialNames")
           and e["assetId"] not in done_bake]
print(f"retry pass: {len(missing)} items", flush=True)
for i, e in enumerate(missing):
    aid = e["assetId"]
    try:
        src = f"{W}/{aid}.glb"
        if not os.path.exists(src):
            open(src, "wb").write(fetch(e["desktopGlbUrl"]))
        dec = f"{W}/{aid}_dec.glb"
        if not os.path.exists(dec):
            subprocess.run(["npx", "--yes", "@gltf-transform/cli@4", "copy", src, dec],
                           capture_output=True, timeout=600)
            if not os.path.exists(dec):
                shutil.copy(src, dec)
        mats = ",".join(e["paintMaterialNames"])
        cv = {}
        ok = True
        for col, hexv in PAL.items():
            out = f"{W}/{aid}__{col}.glb"
            if not os.path.exists(out):
                subprocess.run(["blender", "-b", "--factory-startup", "-noaudio",
                                "--python", f"{S}/bake_colour.py", "--",
                                dec, out, hexlin(hexv), mats],
                               capture_output=True, timeout=900)
            if not os.path.exists(out) or not glb_ok(out):
                print(f"retry [{i+1}] {aid}: bake {col} FAILED", flush=True)
                ok = False
                break
            if os.path.getsize(out) > 48_000_000:
                sm = out + ".dr.glb"
                subprocess.run(["npx", "--yes", "@gltf-transform/cli@4", "draco", out, sm],
                               capture_output=True, timeout=600)
                if os.path.exists(sm) and 0 < os.path.getsize(sm) <= 48_000_000 and glb_ok(sm):
                    os.replace(sm, out)
                else:
                    print(f"retry [{i+1}] {aid}: {col} still too big after draco", flush=True)
                    ok = False
                    break
            dest = f"car-meshes/finished/{e['make']}/{aid}__{col}.glb"
            up(dest, open(out, "rb").read())
            cv[col] = f"{BASE}/public/{dest}"
            os.remove(out)
        for p2 in (src, dec):
            if os.path.exists(p2):
                os.remove(p2)
        if not ok:
            continue
        cat2 = json.load(open(CAT))
        for x in cat2:
            if x["assetId"] == aid:
                x["colourVariants"] = cv
                break
        json.dump(cat2, open(CAT, "w"), indent=1, ensure_ascii=False)
        done_bake.append(aid)
        print(f"retry [{i+1}/{len(missing)}] baked+uploaded {aid}", flush=True)
    except Exception as ex:
        print(f"retry [{i+1}] {aid}: ITEM FAIL {type(ex).__name__} {str(ex)[:100]}", flush=True)

print(f"baked: {len(done_bake)} — starting recolour audits", flush=True)

def audit_one(aid):
    r = subprocess.run([sys.executable, f"{REPO}/pipeline/qc/recolour_audit.py", aid],
                       capture_output=True, text=True, timeout=1800)
    m = re.search(r"RECOLOUR_AUDIT \S+ (PASS|FAIL|SKIP) dist=([0-9.]+)", r.stdout or "")
    return aid, (m.group(1) if m else "ERR"), (float(m.group(2)) if m else -1)

results = {}
with cf.ThreadPoolExecutor(max_workers=2) as ex:
    for aid, verdict, dist in ex.map(audit_one, done_bake):
        results[aid] = (verdict, dist)
        print(f"audit {aid}: {verdict} dist={dist}", flush=True)

# sequential stamping / demotion
for aid, (verdict, dist) in results.items():
    if verdict == "PASS":
        subprocess.run([sys.executable, f"{REPO}/pipeline/qc/recolour_audit.py", aid, "--stamp"],
                       capture_output=True, timeout=1800)
    else:
        cat2 = json.load(open(CAT))
        for x in cat2:
            if x["assetId"] == aid:
                x["colourVariants"] = None
                x["notes"].append(f"w7 variants demoted single-neutral: recolour audit {verdict} dist={dist}")
                break
        json.dump(cat2, open(CAT, "w"), indent=1, ensure_ascii=False)
        print(f"DEMOTED {aid} ({verdict} dist={dist})", flush=True)

g = subprocess.run([sys.executable, f"{REPO}/pipeline/qc/gate_catalogue.py"],
                   capture_output=True, text=True)
print(g.stdout.strip()[-400:], flush=True)
if g.returncode != 0:
    sys.exit("GATE FAIL — catalogue NOT served")
data = open(CAT, "rb").read()
for path in ("car-renders/resolver/catalogue.v2.json", "car-renders/catalogue.v2.json"):
    up(path, data, "application/json")
npass = sum(1 for v, _ in results.values() if v == "PASS")
print(f"VARIANTS_W7_DONE pass={npass} demoted={len(results)-npass} served both paths", flush=True)
