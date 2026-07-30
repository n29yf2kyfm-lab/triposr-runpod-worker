"""Wave-7 pipeline (rebuilt after container restart): staged GLBs -> posters
-> hardened audit -> licence check -> review sheets. Council gates: preflight
canary, batched prompt collection (RunPod results expire), jobs.jsonl,
consecutive-failure breaker, per-item prints. Metadata joined from the
committed 686-row candidates CSV.
"""
import base64, csv, json, os, re, sys, time, urllib.request, urllib.error
S = os.path.dirname(os.path.abspath(__file__))
REPO = "/home/user/triposr-runpod-worker"
SB = re.search(r'SBKEY\s*=\s*"([^"]+)"', open(f"{S}/golf_publish.py").read()).group(1)
RP = re.search(r"rpa_[A-Za-z0-9]+", open(f"{S}/condfix_env.sh").read()).group(0)
TOK = re.search(r'TOKEN = "([0-9a-f]+)"', open(f"{S}/store_one.py").read()).group(1)
EP = "https://api.runpod.ai/v2/ng8oiz4p2l0xa0"
BASE = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
OUT = f"{S}/qc_wave7"
os.makedirs(OUT, exist_ok=True)
JOBLOG = open(f"{OUT}/jobs.jsonl", "a")
def jlog(**kw):
    JOBLOG.write(json.dumps({"ts": time.strftime("%H:%M:%S"), **kw}) + "\n"); JOBLOG.flush()

def preflight():
    rq = urllib.request.Request(f"{BASE}/list/car-meshes", method="POST",
        data=json.dumps({"prefix": "staging/qc_wave7/", "limit": 1}).encode())
    for h, v in (("apikey", SB), ("Authorization", "Bearer " + SB), ("Content-Type", "application/json")):
        rq.add_header(h, v)
    urllib.request.urlopen(rq, timeout=30).read()
    rq = urllib.request.Request("https://api.sketchfab.com/v3/me",
        headers={"Authorization": f"Token {TOK}", "User-Agent": "Mozilla/5.0"})
    urllib.request.urlopen(rq, timeout=30).read()
    print("preflight OK: supabase + sketchfab reachable", flush=True)
try:
    preflight()
except Exception:
    print("PREFLIGHT FAILED - environment down, aborting resumably", flush=True)
    sys.exit(3)

rq = urllib.request.Request(f"{BASE}/list/car-meshes", method="POST",
    data=json.dumps({"prefix": "staging/qc_wave7/", "limit": 1000}).encode())
for h, v in (("apikey", SB), ("Authorization", "Bearer " + SB), ("Content-Type", "application/json")):
    rq.add_header(h, v)
staged = [o["name"][:-4] for o in json.load(urllib.request.urlopen(rq, timeout=60)) if o["name"].endswith(".glb")]

meta = {}
for r in csv.DictReader(open(f"{REPO}/pipeline/ingest/candidates/ECC_REAL_ASSETS_686.csv",
                             encoding="utf-8-sig")):
    meta[r["uid"].strip()] = {"make": r["make"].strip(),
                              "model_as_supplied": r["model_as_supplied"].strip(),
                              "asset_title": r["asset_title"].strip()}
staged.sort()
order = {u: i + 1 for i, u in enumerate(staged)}
print(f"staged: {len(staged)} (meta rows: {len(meta)})", flush=True)

def batched_jobs(items, make_body, tag, save):
    consec = 0
    done = {}
    B = 30
    for bi in range(0, len(items), B):
        chunk = items[bi:bi + B]
        jobs = {}
        for uid in chunk:
            try:
                q = urllib.request.Request(f"{EP}/run", data=json.dumps(make_body(uid)).encode(),
                    headers={"Authorization": f"Bearer {RP}", "Content-Type": "application/json"})
                jid = json.load(urllib.request.urlopen(q, timeout=60))["id"]
                jobs[uid] = jid; jlog(kind=tag, uid=uid, job=jid)
                consec = 0
            except Exception as e:
                consec += 1
                print(f"{tag} submit fail {uid[:8]}: {type(e).__name__}", flush=True)
                if consec >= 8:
                    print(f"{tag}: 8 consecutive submit failures - NETWORK STORM, aborting", flush=True)
                    sys.exit(4)
        pend = dict(jobs); t0 = time.time()
        while pend and time.time() - t0 < 1500:
            time.sleep(10)
            for uid, jid in list(pend.items()):
                try:
                    st = json.load(urllib.request.urlopen(urllib.request.Request(
                        f"{EP}/status/{jid}", headers={"Authorization": f"Bearer {RP}"}), timeout=60))
                except Exception:
                    continue
                if st.get("status") == "COMPLETED":
                    out = st.get("output", {})
                    done[uid] = out; save(uid, out)
                    jlog(kind=tag, uid=uid, job=jid, status="done", ok=out.get("status") == "success")
                    del pend[uid]
                elif st.get("status") in ("FAILED", "CANCELLED", "TIMED_OUT"):
                    done[uid] = {"error": st.get("status")}
                    jlog(kind=tag, uid=uid, job=jid, status=st.get("status"))
                    del pend[uid]
        for uid in pend:
            jlog(kind=tag, uid=uid, status="ABANDONED")
        print(f"{tag} batch {bi//B+1}/{(len(items)+B-1)//B}: collected {len(done)}", flush=True)
    return done

def render_body(uid):
    return {"input": {"glb_url": f"{BASE}/car-meshes/staging/qc_wave7/{uid}.glb",
                      "glb_auth": f"Bearer {SB}", "az": 35, "elev": 0.15,
                      "samples": 96, "width": 960, "height": 540}}
def save_poster(uid, out):
    if out.get("status") == "success":
        open(f"{OUT}/{uid}.png", "wb").write(base64.b64decode(out["png_b64"]))
todo = [u for u in staged if not os.path.exists(f"{OUT}/{u}.png")]
print(f"phase1 render: {len(todo)} to do", flush=True)
batched_jobs(todo, render_body, "render", save_poster)
have = [u for u in staged if os.path.exists(f"{OUT}/{u}.png")]
print(f"posters: {len(have)}", flush=True)

def audit_body(uid):
    return {"input": {"mat_audit": True, "glb_url": f"{BASE}/car-meshes/staging/qc_wave7/{uid}.glb",
                      "glb_auth": f"Bearer {SB}"}}
audits = batched_jobs(have, audit_body, "audit", lambda u, o: None)
INTERIOR = re.compile(r"interior|seat|dash|cockpit|steering|console|carpet|trim|pedal|belt|wheel_?in", re.I)
passes = []
with open(f"{OUT}/AUDIT_HARDENED.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["n", "uid", "make", "model", "n_materials", "body_pct", "glass_pct",
                "interior_evidence", "paint_ok", "glass_ok", "interior_ok", "VERDICT", "error"])
    for uid in have:
        r = audits.get(uid, {"error": "no-result"})
        mrow = meta.get(uid, {"make": "", "model_as_supplied": "", "asset_title": ""})
        if "error" in r or r.get("status") != "success":
            w.writerow([order[uid], uid, mrow["make"], mrow["model_as_supplied"], "", "", "", "", "", "", "", "ERROR", str(r.get("error"))[:60]])
            continue
        mats = r.get("materials", [])
        nm = r.get("n_materials", 0)
        body = r.get("body_pct", 0) or 0
        glass = [t for t in mats if t.get("glass")]
        gp = sum(t.get("pct", 0) for t in glass)
        inames = [t["name"] for t in mats if INTERIOR.search(t.get("name") or "")]
        pok = bool(r.get("chosen_body")) and body >= 12
        gok = len(glass) >= 1 and 0.3 <= gp <= 30
        iok = bool(inames) or nm >= 8
        v = "PASS" if (pok and gok and iok) else "FAIL"
        if v == "PASS":
            passes.append(uid)
        w.writerow([order[uid], uid, mrow["make"], mrow["model_as_supplied"], nm, body, round(gp, 1),
                    ";".join(inames[:2])[:40], pok, gok, iok, v, ""])
print(f"hardened audit: {len(passes)} PASS of {len(have)}", flush=True)

lic_rows = []
for i, uid in enumerate(passes):
    lab = author = title = page = ""
    for attempt in (1, 2, 3):
        try:
            rq = urllib.request.Request(f"https://api.sketchfab.com/v3/models/{uid}",
                headers={"Authorization": f"Token {TOK}", "User-Agent": "Mozilla/5.0"})
            mj = json.load(urllib.request.urlopen(rq, timeout=60))
            lab = (mj.get("license") or {}).get("label", "")
            author = (mj.get("user") or {}).get("displayName", "")
            title = mj.get("name", "")
            page = mj.get("viewerUrl", "") or f"https://sketchfab.com/3d-models/{uid}"
            break
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"licence 429 backoff [{i+1}]", flush=True); time.sleep(90); continue
            lab = f"ERR:{e.code}"; break
        except Exception as e:
            lab = f"ERR:{type(e).__name__}"; break
    ok = lab == "CC Attribution"
    mrow = meta.get(uid, {"make": "", "model_as_supplied": ""})
    lic_rows.append({"n": order[uid], "uid": uid, "make": mrow["make"], "model": mrow["model_as_supplied"],
                     "title": title, "page": page,
                     "licence": lab, "author": author, "commercial_ok": ok, "err": ""})
    if (i + 1) % 25 == 0:
        print(f"licence: {i+1}/{len(passes)}", flush=True)
    time.sleep(0.8)
with open(f"{OUT}/LICENCES.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["n", "uid", "make", "model", "title", "page",
                                      "licence", "author", "commercial_ok", "err"])
    w.writeheader()
    for r in lic_rows: w.writerow(r)
nok = sum(1 for r in lic_rows if r["commercial_ok"])
print(f"licence: {nok} CC-BY of {len(lic_rows)} passes", flush=True)

from PIL import Image, ImageDraw, ImageFont
try: font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
except Exception: font = ImageFont.load_default()
clean = [r for r in lic_rows if r["commercial_ok"]]
TW, TH, COLS, ROWS = 480, 300, 6, 5
per = COLS * ROWS
for si in range(0, len(clean), per):
    chunk = clean[si:si + per]
    sheet = Image.new("RGB", (TW * COLS, (TH + 30) * ROWS), (12, 12, 14))
    d = ImageDraw.Draw(sheet)
    for j, r in enumerate(chunk):
        x, y = (j % COLS) * TW, (j // COLS) * (TH + 30)
        im = Image.open(f"{OUT}/{r['uid']}.png").convert("RGB"); im.thumbnail((TW, TH))
        sheet.paste(im, (x + (TW - im.width) // 2, y + 30 + (TH - im.height) // 2))
        label = f"{r['make']} {r['model']}".strip() or r["title"]
        d.text((x + 8, y + 4), f"#{r['n']} {label}"[:44], fill=(140, 240, 150), font=font)
    sheet.save(f"{OUT}/W7_PASS_SHEET_{si//per+1:02d}.jpg", quality=85)
    print(f"sheet {si//per+1}", flush=True)
print(f"WAVE7_PIPELINE_DONE clean={len(clean)}", flush=True)
