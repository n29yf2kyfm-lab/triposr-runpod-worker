#!/usr/bin/env python3
"""wave_agent.py — one command runs a sourcing wave to the owner's-eyes stage.

Orchestrates the PROVEN tools in order, adds the one stage that was always
manual: a per-sheet AI eye audit at full resolution, using the rubric distilled
from every failure this project has paid for (EYE_RUBRIC.md).

  sweep  -> pipeline/ingest/marque_sweep.py, one run per badge
  merge  -> dedupe by uid + REJECTS.json + quarantined-source cross-ref
  render -> pipeline/ingest/gpu_wave.py   (downloads, pose gate, sheets)
  probe  -> pipeline/ingest/glass_probe.py + flat/alpha-shell gates
  scrub  -> dupe rules (title overlap + faces) + class scrub (military/racing)
  eye    -> AI vision audit of EVERY surviving sheet, one by one
  report -> numbered clean-sheet grids + CLEAN_DATA.csv + AUDIT.json to bucket

HARD RULES, enforced by construction, not by prompt:
  * This tool NEVER publishes. There is no code path to publish_batch,
    colour_variants or the catalogue. Its terminal output is a candidate
    review sheet + AUDIT.json for the owner's cull call.
  * An AI SCRAP is advisory: it removes a car from the CLEAN sheet but the car
    stays in AUDIT.json with its reasons, and the ALL sheet shows everything.
  * UNSURE is never a scrap. It lands on the clean sheet flagged for the eye.
  * The render stage refuses to start if the RunPod balance is under
    --min-balance (default $3) unless --yes-spend is passed.

Eye backends (--eye):
  claude-cli  (default) headless `claude -p` on the operator's subscription.
              No API key needed. The CLI reads the sheet image itself.
  anthropic   Anthropic SDK, model claude-opus-5, base64 vision blocks.
              Needs ANTHROPIC_API_KEY (or an `ant auth login` profile).
  mock        no AI: every sheet -> UNSURE. For pipeline tests.

Usage:
  wave_agent.py --tag kia1 --marque Kia --nameplates "Ceed,Sportage,..." --stage all
  wave_agent.py --tag vx1 --stage eye --sheets-dir /path/to/jpgs   # re-run one stage
Every stage is resumable: artefacts land in <workdir>/<tag>/ and in the bucket
under audit/<tag>/, and a finished artefact is never recomputed.
"""
import argparse, base64, csv, itertools, json, os, re, shutil, subprocess, sys, time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SB = "https://tfkvthprsntexrcuqpyd.supabase.co"
BUCKET = "car-meshes"
RUBRIC = open(os.path.join(HERE, "EYE_RUBRIC.md")).read()

# same class scrub that caught the Blitz trucks and the DTM racer on vx1
MILRACE = re.compile(r"flak|field kitchen|ww2|military|army|wehrmacht|dtm|btcc|"
                     r"rally ?car|race ?car|\bblitz\b", re.I)


def load_env():
    try:
        for line in open("/root/.alam3d_env"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                n, _, v = line.partition("=")
                os.environ.setdefault(n.strip(), v.strip().strip("'\""))
    except OSError:
        pass


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def run(cmd, **kw):
    log("$", " ".join(cmd[:6]), "..." if len(cmd) > 6 else "")
    return subprocess.run(cmd, **kw)


def sb_get(path, out=None):
    url = f"{SB}/storage/v1/object/public/{BUCKET}/{path}"
    if out:
        urllib.request.urlretrieve(url, out)
        return out
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def sb_put(path, data, ctype):
    rq = urllib.request.Request(
        f"{SB}/storage/v1/object/{BUCKET}/{path}", data=data, method="POST",
        headers={"Authorization": f"Bearer {os.environ['SB_KEY']}",
                 "apikey": os.environ["SB_KEY"], "Content-Type": ctype,
                 "x-upsert": "true"})
    urllib.request.urlopen(rq, timeout=120)


# ---------------------------------------------------------------- stages
def stage_sweep(a, W):
    for badge in a.badges:
        out = f"{W}/{badge.lower()}_manifest.json"
        if os.path.exists(out):
            log(f"sweep {badge}: already done"); continue
        cmd = [sys.executable, f"{REPO}/pipeline/ingest/marque_sweep.py",
               "--marque", badge, "--out", out,
               "--raw-out", f"{W}/{badge.lower()}_raw.json",
               "--rejects-out", f"{W}/{badge.lower()}_rejects.json"]
        if a.nameplates:
            cmd += ["--nameplates", a.nameplates]
        r = run(cmd)
        if r.returncode != 0:
            sys.exit(f"sweep {badge} failed rc={r.returncode}")


def stage_merge(a, W):
    out = f"{W}/wave_manifest.json"
    if os.path.exists(out):
        log("merge: already done"); return
    merged = {}
    for badge in a.badges:
        for row in json.load(open(f"{W}/{badge.lower()}_manifest.json")):
            merged[row["uid"]] = row
    rej = set(json.load(open(f"{REPO}/pipeline/ingest/REJECTS.json")))
    dropped = [u for u in merged if u in rej]
    for u in dropped:
        del merged[u]
    cat = json.load(open(f"{REPO}/platform/catalogue/catalogue.v2.json"))
    entries = cat if isinstance(cat, list) else cat.get("entries", [])
    qids = {e.get("sourceReferenceId") for e in entries
            if e.get("publicationStatus") == "quarantined"}
    holds = [u for u in merged if u in qids]
    for u in holds:
        del merged[u]
    json.dump(list(merged.values()), open(out, "w"), indent=1)
    log(f"merge: {len(merged)} candidates "
        f"(rejects ledger -{len(dropped)}, quarantined-source -{len(holds)})")


def stage_render(a, W):
    # money gate: billing exhaustion looks exactly like capacity starvation
    q = json.dumps({"query": "query { myself { clientBalance } }"}).encode()
    rq = urllib.request.Request("https://api.runpod.io/graphql", data=q,
        headers={"Authorization": f"Bearer {os.environ['RUNPOD_API_KEY']}",
                 "Content-Type": "application/json"})
    bal = json.load(urllib.request.urlopen(rq, timeout=60))["data"]["myself"]["clientBalance"]
    log(f"RunPod balance: ${bal:.2f}")
    if bal < a.min_balance and not a.yes_spend:
        sys.exit(f"REFUSING TO RENDER: balance ${bal:.2f} < ${a.min_balance:.2f} "
                 "floor. Top up or pass --yes-spend.")
    r = run([sys.executable, "-u", f"{REPO}/pipeline/ingest/gpu_wave.py",
             "--manifest", f"{W}/wave_manifest.json",
             "--stage", f"staging/{a.tag}", "--sheets", f"audit/{a.tag}",
             "--parallel", str(a.parallel), "--work", f"{W}/work"])
    if r.returncode != 0:
        sys.exit(f"render failed rc={r.returncode}")


def stage_probe(a, W):
    out = f"{W}/GLASS.json"
    if not os.path.exists(out):
        r = run([sys.executable, f"{REPO}/pipeline/ingest/glass_probe.py",
                 f"{W}/wave_manifest.json", out, f"staging/{a.tag}"])
        if r.returncode != 0:
            sys.exit(f"glass probe failed rc={r.returncode}")
    probe = json.load(open(out))
    keep, fails = [], []
    for p in probe:
        # alpha_shell: body/tyre transparent (the gate the 2026-08-16 audit
        # nearly missed) -- flat_shell: one flat colour everywhere
        body_trans = [m for m in (p.get("body_transparent") or [])
                      if not re.search(r"plate|licence|license", m.get("name", ""), re.I)]
        if p.get("flat_shell") or body_trans:
            p["fail"] = "flat/alpha shell"; fails.append(p)
        elif p.get("verdict") == "opaque":
            p["fail"] = f"glazing opaque ({p.get('certainty')})"; fails.append(p)
        elif p.get("verdict") == "unknown":
            p["fail"] = "never staged"; fails.append(p)
        else:
            keep.append(p)          # clear, faded and ambiguous continue;
    json.dump({"keep": keep, "fails": fails}, open(f"{W}/PROBE_VERDICTS.json", "w"), indent=1)
    log(f"probe: {len(keep)} keep, {len(fails)} material fails")


def stage_scrub(a, W):
    pv = json.load(open(f"{W}/PROBE_VERDICTS.json"))
    man = {r["uid"]: r for r in json.load(open(f"{W}/wave_manifest.json"))}
    keep, scrapped = [], []
    for p in pv["keep"]:
        name = p.get("name", "")
        if MILRACE.search(name):
            p["fail"] = "class: military/racing/pre-war"; scrapped.append(p)
        else:
            p["faces"] = man.get(p["uid"], {}).get("faces")
            keep.append(p)

    def toks(t):
        t = re.sub(r"[^a-z0-9 ]", " ", t.lower())
        stop = {w.lower() for w in a.badges} | {"the", "a"}
        return {w for w in t.split() if w not in stop}

    def roundcluster(f):
        return f and any(abs(f - k * 100000) <= 250 for k in range(1, 13))

    for x, y in itertools.combinations(list(keep), 2):
        if x not in keep or y not in keep:
            continue
        fx, fy = x.get("faces"), y.get("faces")
        if not fx or not fy:
            continue
        tx, ty = toks(x["name"]), toks(y["name"])
        ov = len(tx & ty) / max(1, min(len(tx), len(ty)))
        close1 = abs(fx - fy) <= 0.01 * max(fx, fy)
        close2 = abs(fx - fy) <= 50 and not (roundcluster(fx) or roundcluster(fy))
        if (ov >= 0.75 and close1) or (ov >= 0.4 and close2):
            drop = x if fx < fy else y
            drop["fail"] = f"duplicate ({fx} vs {fy} faces)"
            scrapped.append(drop); keep.remove(drop)
    json.dump({"keep": keep, "scrapped": scrapped},
              open(f"{W}/SCRUB_VERDICTS.json", "w"), indent=1)
    log(f"scrub: {len(keep)} keep, {len(scrapped)} scrapped")


# ---------------------------------------------------------------- eye
def eye_claude_cli(sheet_path, model=None):
    prompt = (f"{RUBRIC}\n\nThe sheet image is at: {sheet_path}\n"
              "Read that image file, audit it against the rubric above, and "
              "reply with ONLY the JSON object.")
    # headless mode denies tools by default; the audit needs exactly one —
    # Read, scoped to the sheets directory. Without these two flags the CLI
    # politely answers "I don't have permission to read that file" (measured).
    cmd = ["claude", "-p", prompt, "--output-format", "json",
           "--allowedTools", "Read", "--add-dir", os.path.dirname(sheet_path)]
    if model:
        cmd += ["--model", model]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        return {"verdict": "UNSURE", "reasons": [f"cli rc={r.returncode}"], "flags": []}
    try:
        result = json.loads(r.stdout).get("result", "")
        m = re.search(r"\{.*\}", result, re.S)
        return json.loads(m.group(0))
    except Exception as e:
        return {"verdict": "UNSURE", "reasons": [f"unparseable: {e}"], "flags": []}


def eye_anthropic(sheet_path, model="claude-opus-5"):
    import anthropic                       # pip install anthropic
    client = anthropic.Anthropic()
    data = base64.standard_b64encode(open(sheet_path, "rb").read()).decode()
    resp = client.messages.create(
        model=model, max_tokens=1024,
        messages=[{"role": "user", "content": [
            {"type": "image",
             "source": {"type": "base64", "media_type": "image/jpeg", "data": data}},
            {"type": "text", "text": RUBRIC + "\nAudit this sheet. JSON only."},
        ]}])
    if resp.stop_reason == "refusal":
        return {"verdict": "UNSURE", "reasons": ["model refusal"], "flags": []}
    text = "".join(b.text for b in resp.content if b.type == "text")
    try:
        return json.loads(re.search(r"\{.*\}", text, re.S).group(0))
    except Exception as e:
        return {"verdict": "UNSURE", "reasons": [f"unparseable: {e}"], "flags": []}


def stage_eye(a, W):
    sv = json.load(open(f"{W}/SCRUB_VERDICTS.json"))
    sheets_dir = a.sheets_dir or f"{W}/sheets"
    os.makedirs(sheets_dir, exist_ok=True)
    out_path = f"{W}/EYE.json"
    done = {}
    if os.path.exists(out_path):
        done = {e["uid"]: e for e in json.load(open(out_path))}
    results = []
    for i, p in enumerate(sv["keep"], 1):
        uid = p["uid"]
        if uid in done:
            results.append(done[uid]); continue
        sheet = os.path.join(sheets_dir, f"{uid}.jpg")
        if not os.path.exists(sheet):
            try:
                sb_get(f"audit/{a.tag}/{uid}.jpg", sheet)
            except Exception as e:
                results.append({"uid": uid, "name": p.get("name"),
                                "verdict": "UNSURE",
                                "reasons": [f"sheet missing: {e}"], "flags": []})
                continue
        if a.eye == "mock":
            v = {"verdict": "UNSURE", "reasons": ["mock backend"], "flags": []}
        elif a.eye == "anthropic":
            v = eye_anthropic(sheet, a.model or "claude-opus-5")
        else:
            v = eye_claude_cli(sheet, a.model)
        v.update(uid=uid, name=p.get("name"))
        results.append(v)
        log(f"eye [{i}/{len(sv['keep'])}] {v['verdict']:6s} "
            f"{(p.get('name') or '')[:44]} {'; '.join(v.get('reasons', [])[:1])}")
        json.dump(results, open(out_path, "w"), indent=1)   # save-as-you-go
    json.dump(results, open(out_path, "w"), indent=1)
    from collections import Counter
    log("eye verdicts:", dict(Counter(r["verdict"] for r in results)))


def stage_report(a, W):
    from PIL import Image, ImageDraw, ImageFont
    sv = json.load(open(f"{W}/SCRUB_VERDICTS.json"))
    eye = {e["uid"]: e for e in json.load(open(f"{W}/EYE.json"))}
    pvf = json.load(open(f"{W}/PROBE_VERDICTS.json"))["fails"]
    sheets_dir = a.sheets_dir or f"{W}/sheets"
    clean = [p for p in sv["keep"]
             if eye.get(p["uid"], {}).get("verdict") != "SCRAP"]
    ai_scraps = [p for p in sv["keep"]
                 if eye.get(p["uid"], {}).get("verdict") == "SCRAP"]

    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
    except OSError:
        font = ImageFont.load_default()
    COLS, TW, PER = 4, 640, 24
    tiles, rows = [], []
    for n, p in enumerate(clean, 1):
        fp = os.path.join(sheets_dir, f"{p['uid']}.jpg")
        if not os.path.exists(fp):
            continue
        im = Image.open(fp)
        im = im.resize((TW, int(im.height * TW / im.width)))
        d = ImageDraw.Draw(im)
        e = eye.get(p["uid"], {})
        lab = f"#{n}" + (" ?" if e.get("verdict") == "UNSURE" else "")
        d.rectangle([0, 0, 170, 30], fill=(0, 0, 0))
        d.text((6, 4), lab, fill=(80, 220, 120), font=font)
        tiles.append(im)
        rows.append([n, p.get("name"), p["uid"], e.get("verdict"),
                     ";".join(e.get("flags", [])), p.get("faces")])
    pages = []
    if tiles:
        TH = max(t.height for t in tiles)
        for pg in range((len(tiles) + PER - 1) // PER):
            chunk = tiles[pg * PER:(pg + 1) * PER]
            prows = (len(chunk) + COLS - 1) // COLS
            page = Image.new("RGB", (COLS * TW, prows * TH), (18, 18, 20))
            for j, t in enumerate(chunk):
                page.paste(t, ((j % COLS) * TW, (j // COLS) * TH))
            fp = f"{W}/CLEAN_p{pg + 1}.jpg"
            page.save(fp, quality=84); pages.append(fp)

    with open(f"{W}/CLEAN_DATA.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["n", "name", "uid", "eye_verdict", "flags", "faces"])
        w.writerows(rows)
    audit = {"tag": a.tag, "clean": [p["uid"] for p in clean],
             "ai_scraps": [{"uid": p["uid"], "name": p.get("name"),
                            "reasons": eye[p["uid"]].get("reasons")} for p in ai_scraps],
             "scrub_scraps": sv["scrapped"], "probe_fails": pvf}
    json.dump(audit, open(f"{W}/AUDIT.json", "w"), indent=1)
    for fp in pages + [f"{W}/CLEAN_DATA.csv", f"{W}/AUDIT.json", f"{W}/EYE.json"]:
        ct = ("image/jpeg" if fp.endswith(".jpg") else
              "text/csv" if fp.endswith(".csv") else "application/json")
        sb_put(f"audit/{a.tag}/{os.path.basename(fp)}", open(fp, "rb").read(), ct)
    log(f"report: {len(clean)} on the clean sheet, {len(ai_scraps)} AI scraps "
        f"(recorded, reviewable), {len(sv['scrapped'])} scrub scraps, "
        f"{len(pvf)} probe fails")
    log(f"uploaded to {BUCKET}/audit/{a.tag}/ — owner cull call is next. "
        "THIS TOOL DOES NOT PUBLISH.")


STAGES = ["sweep", "merge", "render", "probe", "scrub", "eye", "report"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True, help="wave tag, e.g. kia1")
    ap.add_argument("--marque", default="", help="primary badge name")
    ap.add_argument("--badges", default="", help="comma list; default = marque")
    ap.add_argument("--nameplates", default="")
    ap.add_argument("--stage", default="all", help="all or one of " + ",".join(STAGES))
    ap.add_argument("--eye", default="claude-cli",
                    choices=("claude-cli", "anthropic", "mock"))
    ap.add_argument("--model", default="", help="override eye model")
    ap.add_argument("--sheets-dir", default="", help="local sheet jpgs (skip download)")
    ap.add_argument("--workdir", default="/tmp/wave_agent")
    ap.add_argument("--parallel", type=int, default=6)
    ap.add_argument("--min-balance", type=float, default=3.0)
    ap.add_argument("--yes-spend", action="store_true")
    a = ap.parse_args()
    a.badges = [b for b in (a.badges or a.marque).split(",") if b]
    load_env()
    W = os.path.join(a.workdir, a.tag)
    os.makedirs(W, exist_ok=True)
    todo = STAGES if a.stage == "all" else [a.stage]
    for s in todo:
        log(f"=== stage {s} ===")
        globals()[f"stage_{s}"](a, W)


if __name__ == "__main__":
    main()
