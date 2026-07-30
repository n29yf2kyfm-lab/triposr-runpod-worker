"""Wave-7 downloader (rebuilt after container restart; resumable by design).
Fetches candidates from the committed 686 CSV that are not in the catalogue
and not already staged. 20s pacing, 120s backoff on 429, 30-min cooldown after
3 consecutive 429s. GLBs over 48MB are Draco-compressed. Size-validated.
"""
import csv, json, os, re, struct, subprocess, sys, time, urllib.request, urllib.error

S = os.path.dirname(os.path.abspath(__file__))
REPO = "/home/user/triposr-runpod-worker"
SB = re.search(r'SBKEY\s*=\s*"([^"]+)"', open(f"{S}/golf_publish.py").read()).group(1)
TOK = re.search(r'TOKEN = "([0-9a-f]+)"', open(f"{S}/store_one.py").read()).group(1)
BASE = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
OUT = f"{S}/qc_wave7"
os.makedirs(OUT, exist_ok=True)
JOBLOG = open(f"{OUT}/download_jobs.jsonl", "a")
def jlog(**kw):
    JOBLOG.write(json.dumps({"ts": time.strftime("%H:%M:%S"), **kw}) + "\n"); JOBLOG.flush()

def sb(path, data=None, ctype="application/json"):
    rq = urllib.request.Request(f"{BASE}/{path}", data=data,
                                method="POST" if data else "GET")
    for h, v in (("apikey", SB), ("Authorization", "Bearer " + SB),
                 ("Content-Type", ctype), ("x-upsert", "true")):
        rq.add_header(h, v)
    return urllib.request.urlopen(rq, timeout=300)

def list_prefix(prefix):
    r = sb("list/car-meshes", json.dumps({"prefix": prefix, "limit": 1000}).encode())
    return {o["name"][:-4] for o in json.load(r) if o["name"].endswith(".glb")}

try:
    sb("list/car-meshes", json.dumps({"prefix": "staging/", "limit": 1}).encode())
    rq = urllib.request.Request("https://api.sketchfab.com/v3/me",
        headers={"Authorization": f"Token {TOK}", "User-Agent": "Mozilla/5.0"})
    urllib.request.urlopen(rq, timeout=30).read()
    print("preflight OK", flush=True)
except Exception as e:
    print(f"PREFLIGHT FAILED ({type(e).__name__}) - aborting resumably", flush=True)
    sys.exit(3)

cat = json.load(open(f"{REPO}/platform/catalogue/catalogue.v2.json"))
known = {e["sourceReferenceId"] for e in cat if e.get("sourceReferenceId")}
w6 = list_prefix("staging/qc_wave6/")
w7_done = list_prefix("staging/qc_wave7/")
rows = list(csv.DictReader(open(f"{REPO}/pipeline/ingest/candidates/ECC_REAL_ASSETS_686.csv",
                                encoding="utf-8-sig")))
todo = [r for r in rows
        if r["uid"].strip() not in known and r["uid"].strip() not in w6
        and r["uid"].strip() not in w7_done]
todo.sort(key=lambda r: (r["strict_status"] != "PRIORITY A",))
print(f"wave-7 remaining to download: {len(todo)} (already staged: {len(w7_done)})", flush=True)

consec_429 = consec_net = ok = skip = 0
for i, r in enumerate(todo):
    uid = r["uid"].strip()
    label = f"{r['make']} {r['model_as_supplied']}".strip()
    try:
        rq = urllib.request.Request(f"https://api.sketchfab.com/v3/models/{uid}/download",
            headers={"Authorization": f"Token {TOK}", "User-Agent": "Mozilla/5.0"})
        dl = json.load(urllib.request.urlopen(rq, timeout=60))
        url = (dl.get("glb") or {}).get("url")
        if not url:
            jlog(uid=uid, status="no-glb-format"); skip += 1
            print(f"[{i+1}/{len(todo)}] SKIP no-glb {label}", flush=True)
            consec_429 = consec_net = 0
            time.sleep(20); continue
        blob = urllib.request.urlopen(url, timeout=600).read()
        if blob[:4] != b"glTF" or len(blob) != struct.unpack("<I", blob[8:12])[0]:
            jlog(uid=uid, status="bad-or-truncated", size=len(blob)); skip += 1
            print(f"[{i+1}/{len(todo)}] SKIP bad-glb {label}", flush=True)
            time.sleep(20); continue
        if len(blob) > 48_000_000:
            a, b = f"{OUT}/_big.glb", f"{OUT}/_big_dr.glb"
            open(a, "wb").write(blob)
            subprocess.run(["npx", "--yes", "@gltf-transform/cli@4", "draco", a, b],
                           capture_output=True, timeout=600)
            if os.path.exists(b) and 0 < os.path.getsize(b) <= 48_000_000:
                blob = open(b, "rb").read()
                jlog(uid=uid, status="draco", size=len(blob))
            else:
                jlog(uid=uid, status="too-big", size=len(blob)); skip += 1
                print(f"[{i+1}/{len(todo)}] SKIP too-big {label}", flush=True)
                time.sleep(20); continue
        sb(f"car-meshes/staging/qc_wave7/{uid}.glb", blob, "model/gltf-binary")
        jlog(uid=uid, status="staged", size=len(blob)); ok += 1
        consec_429 = consec_net = 0
        print(f"[{i+1}/{len(todo)}] staged {label} ({len(blob)//1024}KB) [{ok} ok]", flush=True)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            consec_429 += 1
            if consec_429 >= 3:
                print(f"RATE-LIMIT STORM: 3x429, cooling down 30 min [{i+1}/{len(todo)}]", flush=True)
                jlog(uid=uid, status="429-storm-cooldown"); time.sleep(1800); consec_429 = 0
            else:
                print(f"[{i+1}/{len(todo)}] 429 backoff 120s", flush=True); time.sleep(120)
        else:
            jlog(uid=uid, status=f"http-{e.code}"); skip += 1
            print(f"[{i+1}/{len(todo)}] SKIP http-{e.code} {label}", flush=True)
    except Exception as e:
        consec_net += 1
        jlog(uid=uid, status=f"err-{type(e).__name__}")
        print(f"[{i+1}/{len(todo)}] err {type(e).__name__} {label} (consec {consec_net})", flush=True)
        if consec_net >= 8:
            print("NETWORK STORM: 8 consecutive failures - aborting resumably", flush=True)
            sys.exit(4)
        time.sleep(60)
    time.sleep(20)

staged_now = list_prefix("staging/qc_wave7/")
print(f"WAVE7_DOWNLOAD_DONE staged={len(staged_now)} ok={ok} skip={skip}", flush=True)
