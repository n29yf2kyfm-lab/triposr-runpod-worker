"""Bake the 8-colour DVLA palette for the single-colour cars whose body-paint
material has been proven by the coverage probe, upload, render-audit, stamp,
then gate + serve both public catalogue paths.

Resprays at the glTF JSON level (respray.py) rather than through Blender, so the
geometry — including the GB plates already baked into these files — is copied
through byte-for-byte and the material names matched are the real glTF ones.

Cars whose 8-colour set fails the render audit are demoted to single-neutral AND
their base GLB is resprayed to the palette's natural grey, so a car that cannot
offer colours still reads as a deliberate neutral rather than whatever colour its
source happened to ship.
"""
import concurrent.futures as cf
import json, os, re, subprocess, sys, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import respray

S = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = f"{S}/single19"
REPO = "/home/user/triposr-runpod-worker"
CAT = f"{REPO}/platform/catalogue/catalogue.v2.json"
SB = re.search(r'SBKEY\s*=\s*"([^"]+)"', open(f"{S}/golf_publish.py").read()).group(1)
BASE = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
W = f"{D}/vwork"
os.makedirs(W, exist_ok=True)

PAL = {"grey": "6f7276", "silver": "b6b9be", "black": "1b1d20", "white": "e4e6e8",
       "blue": "1f4fb0", "red": "b11e1e", "green": "1f6b3a", "yellow": "d9b310"}
NEUTRAL = "6f7276"

APPROVED = [a.strip() for a in open(f"{D}/PROVEN.txt")] if os.path.exists(f"{D}/PROVEN.txt") else []
APPROVED = [a for a in APPROVED if a and not a.startswith("#")]
picks = json.load(open(f"{D}/PICKS.json"))

def free_gb():
    st = os.statvfs("/")
    return st.f_bavail * st.f_frsize / 1e9

def up(path, blob):
    for a in range(4):
        rq = urllib.request.Request(f"{BASE}/{path}", data=blob, method="POST")
        for h, v in (("apikey", SB), ("Authorization", "Bearer " + SB),
                     ("Content-Type", "model/gltf-binary"), ("x-upsert", "true")):
            rq.add_header(h, v)
        try:
            urllib.request.urlopen(rq, timeout=600).read(); return
        except Exception:
            if a == 3:
                raise
            time.sleep(20)

def fetch(url):
    for a in range(4):
        try:
            return urllib.request.urlopen(url, timeout=600).read()
        except Exception:
            if a == 3:
                raise
            time.sleep(20)

cat = {e["assetId"]: e for e in json.load(open(CAT))}
baked = []
for i, aid in enumerate(APPROVED):
    e = cat.get(aid)
    if not e:
        print(f"[{i+1}] {aid}: not in catalogue, skip", flush=True); continue
    try:
        if free_gb() < 1.0:
            print("DISK GUARD: <1GB free, aborting resumably", flush=True); sys.exit(6)
        src = f"{D}/work/{aid}.glb"
        if not os.path.exists(src):
            open(src, "wb").write(fetch(e["desktopGlbUrl"]))
        cv = {}
        for col, hexv in PAL.items():
            out = f"{W}/{aid}__{col}.glb"
            respray.respray(src, out, picks[aid], hexv)
            sz = os.path.getsize(out)
            if sz > 48_000_000:
                print(f"[{i+1}] {aid}: {col} {sz/1e6:.1f}MB over the 48MB cap", flush=True)
                raise RuntimeError("too big")
            dest = f"car-meshes/finished/{e['make']}/{aid}__{col}.glb"
            up(dest, open(out, "rb").read())
            cv[col] = f"{BASE}/public/{dest}"
            os.remove(out)
        cat2 = json.load(open(CAT))
        for x in cat2:
            if x["assetId"] == aid:
                x["colourVariants"] = cv
                x["paintMaterialNames"] = picks[aid]
                x.pop("recolourAudit", None)
                break
        json.dump(cat2, open(CAT, "w"), indent=1, ensure_ascii=False)
        baked.append(aid)
        print(f"[{i+1}/{len(APPROVED)}] baked 8 colours {aid} (disk {free_gb():.1f}G)", flush=True)
    except Exception as ex:
        print(f"[{i+1}] {aid}: ITEM FAIL {type(ex).__name__} {str(ex)[:120]}", flush=True)

print(f"BAKED {len(baked)}", flush=True)

def audit(aid):
    r = subprocess.run(["python3", f"{REPO}/pipeline/qc/recolour_audit.py", aid],
                       capture_output=True, text=True, timeout=1800)
    line = [l for l in (r.stdout or "").splitlines() if l.startswith("RECOLOUR_AUDIT")]
    return aid, (line[-1] if line else f"RECOLOUR_AUDIT {aid} ERR {(r.stderr or '')[-120:]}")

results = {}
with cf.ThreadPoolExecutor(max_workers=2) as ex:
    for aid, line in ex.map(audit, baked):
        results[aid] = line
        print(line, flush=True)

good = [a for a, l in results.items() if " PASS " in l]
bad = [a for a in baked if a not in good]
for aid in good:
    subprocess.run(["python3", f"{REPO}/pipeline/qc/recolour_audit.py", aid, "--stamp"],
                   capture_output=True, text=True, timeout=1800)
    print(f"stamped {aid}", flush=True)

# demote failures to single-neutral, and make that neutral an honest grey
for aid in bad:
    e = cat[aid]
    try:
        out = f"{W}/{aid}__neutral.glb"
        respray.respray(f"{D}/work/{aid}.glb", out, picks[aid], NEUTRAL)
        path = e["desktopGlbUrl"].split("/object/public/", 1)[1]
        up(path, open(out, "rb").read())
        size = os.path.getsize(out)
        os.remove(out)
        note = "grey"
    except Exception as exx:
        size = None; note = f"left as-is ({type(exx).__name__})"
    cat2 = json.load(open(CAT))
    for x in cat2:
        if x["assetId"] == aid:
            x.pop("colourVariants", None)
            x.pop("recolourAudit", None)
            if size:
                x["fileSizeBytes"] = size
            break
    json.dump(cat2, open(CAT, "w"), indent=1, ensure_ascii=False)
    print(f"demoted {aid} -> single-neutral {note}", flush=True)

print(f"VARIANTS19_DONE pass={len(good)} fail={len(bad)}", flush=True)
