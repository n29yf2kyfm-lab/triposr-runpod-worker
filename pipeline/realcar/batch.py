#!/usr/bin/env python3
"""batch.py — finish the UK's best-selling cars from the approved catalogue,
in sales order, unattended and resumable.

    BLENDER_BIN=... python3 pipeline/realcar/batch.py OUT_DIR --top 20 \
        --engine-pack engine_pack.glb --tools TOOLS_DIR [--class car]

For each target in platform/catalogue/uk_targets/targets.csv (ranked by
licensed vehicles), the best approved catalogue model is chosen (quality
newest generation, a quality grade counting as four years), and then:

  download -> rig machine (doors, wheels, frame) -> finish.py (bonnet,
  tailgate, trims, glass, engine, clips) -> glTF validator -> meshopt web
  copy -> four-view check sheet

One line per car goes to OUT_DIR/state.jsonl. A re-run skips cars already
there; remove a car's line to redo it (its rigged copy is kept, so that only
re-finishes). The rigged copy, web copy, sheet and log stay on disk. Nothing is
published: a person looks at each sheet first.

TOOLS_DIR is a folder with node_modules for @gltf-transform, meshoptimizer,
gltf-validator and puppeteer-core, plus validate.mjs, encode.mjs and view.mjs
(see pipeline/template/tools). The check sheet is rendered by a three.js page
(VIEW_DIR) served on localhost.
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import finish  # noqa: E402

GRADE = {"A": 0, "B": 1, "C": 2}

# Wheelbases (mm) checked by hand for the catalogue models at the top of the
# list. A model at true scale needs none. One the rig machine had to rescale
# from an assumed wheel height is set to this figure, and is flagged
# "scale unverified" if it has none.
WHEELBASE = {
    "volkswagen-polo-2023-v1": 2564,
    "nissan-qashqai-2018-v1": 2646,
    "ford-fiesta-2009-w12-v1": 2489,          # Fiesta Mk6 (2008-2017), en.wikipedia infobox
    "volkswagen-golf-2025-w12-v1": 2636,      # Golf Mk8 / 8.5, en.wikipedia infobox
    "mercedes-benz-a-class-2018-w12-v1": 2699,  # A45 AMG W176 (2012-2018), en.wikipedia infobox
}


# Catalogue years corrected by looking at the model against the generation's
# published production dates (the catalogue keeps the source's title year).
GENERATION_FIX = {
    "mercedes-benz-a-class-2018-w12-v1": {"yearStart": 2012, "yearEnd": 2018, "generation": "W176"},
}


def catalogue():
    d = json.load(open(os.path.join(REPO, "platform/catalogue/catalogue.v2.json")))
    items = d if isinstance(d, list) else d.get("models") or d.get("items") or list(d.values())[0]
    cat = {i["assetId"]: i for i in items}
    for aid, fix in GENERATION_FIX.items():
        if aid in cat:
            cat[aid] = {**cat[aid], **fix}
    return cat


def pick(target, cat):
    ids = [a for a in (target["assetIds"] or "").split("|") if a in cat]
    ok = [cat[a] for a in ids if cat[a].get("publicationStatus") == "approved" and cat[a].get("desktopGlbUrl")]
    if not ok:
        return None
    # the generation on the road now matters most; a grade is worth 4 years
    ok.sort(key=lambda i: -((i.get("yearStart") or 1990) - 4 * GRADE.get(i.get("qualityGrade"), 3)))
    return ok[0]


def credit_of(item):
    ref = item.get("sourceReferenceId")
    title, who, lic = item.get("sourceTitle"), item.get("sourceCreator"), item.get("licence")
    if ref:
        try:
            with urllib.request.urlopen(f"https://api.sketchfab.com/v3/models/{ref}", timeout=20) as r:
                m = json.load(r)
            title, who = m.get("name") or title, m["user"]["displayName"]
            lic = {"by": "CC BY 4.0", "by-sa": "CC BY-SA 4.0", "by-nc": "CC BY-NC 4.0",
                   "by-nc-sa": "CC BY-NC-SA 4.0", "cc0": "CC0"}.get(m["license"]["slug"], m["license"]["label"])
        except Exception:
            pass
    return {"title": title, "author": who, "licence": lic, "url": item.get("sourceUrl"),
            "commercial": bool(lic) and "NC" not in lic.upper().replace("NON-COMMERCIAL", "NC")}


def run(cmd, timeout, log=None, **kw):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
    if log is not None:
        log.write(" ".join(cmd) + "\n" + p.stdout[-4000:] + p.stderr[-4000:] + "\n")
    return p


def one(target, item, args, out):
    aid = item["assetId"]
    d = os.path.join(out, aid)
    os.makedirs(d, exist_ok=True)
    lg = open(os.path.join(d, "batch.log"), "w")
    rec = {"rank": int(target["rank"]), "target": target["genModel"], "asset": aid,
           "grade": item.get("qualityGrade"), "years": [item.get("yearStart"), item.get("yearEnd")]}
    src, rig = os.path.join(d, "src.glb"), os.path.join(d, "rig")
    rigged = os.path.join(rig, "src.glb")
    rr_path = os.path.join(rig, "result.json")
    tm = {}
    t0 = time.time()
    if os.path.exists(rigged) and os.path.exists(rr_path):
        rr = json.load(open(rr_path))           # rigged before: finish again only
        tm["rig"] = 0.0
    else:
        urllib.request.urlretrieve(item["desktopGlbUrl"], src)
        tm["download"] = round(time.time() - t0, 1)
        t0 = time.time()
        # rig only: the finisher draws its own sheet, so no Blender stills
        p = run([sys.executable, os.path.join(REPO, "platform/rigmachine/run.py"), src, rig, "--no-stills"], 2400, lg)
        tm["rig"] = round(time.time() - t0, 1)
        try:
            rr = json.loads(p.stdout.strip().splitlines()[-1])
        except Exception:
            rr = {"status": "error", "error": (p.stderr or p.stdout)[-300:]}
    rec["rig"] = {k: rr.get(k) for k in ("status", "opens", "missing", "refused", "error")}
    if not os.path.exists(rigged):
        rec["status"] = "rig failed"
        return rec
    rep = json.load(open(os.path.join(rig, "src.report.json")))
    cr = credit_of(item)
    rec["credit"] = cr
    spec = {"name": f"{item['make'].title()} {item.get('modelFamily') or item['model']}",
            "engine_pack": args.engine_pack,
            "credit": f"Body, cabin and wheels: '{cr['title']}' by {cr['author']}, {cr['licence']}, {cr['url']}. "
                      "Rigged, glass cleared and engine bay fitted by the ExpertCarCheck GLB machine."}
    if getattr(args, "paint", None):
        spec["paint"] = list(args.paint)
    if aid in WHEELBASE:
        spec["wheelbase"] = WHEELBASE[aid]
    elif rep.get("rescaled"):
        rec["scale_unverified"] = rep["rescaled"].get("why")
    fin = os.path.join(d, "finished.glb")
    t0 = time.time()
    try:
        flog = finish.finish(rigged, spec, fin)
    except BaseException as e:            # SystemExit from a bad frame too
        rec["status"] = f"finish failed: {e}"
        return rec
    tm["finish"] = round(time.time() - t0, 1)
    rec["finish"] = {k: flog.get(k) for k in ("opens", "missing", "bonnet", "tailgate", "door_trims", "rescale",
                                              "glass_cleared", "measured", "bay_cleared_m2", "engine_pack", "paint_set")}
    # validator, web copy and check sheet at the same time: the sheet is drawn
    # from the finished file, so it need not wait for the compression
    web = os.path.join(d, "web.glb")
    rel = os.path.relpath(fin, args.view_dir)
    shots = [("hero", "az=38&el=14&d=6.6&ty=0.6"), ("all", "az=40&el=22&d=6.9&open=all_open"),
             ("rear", "az=215&el=18&d=6.9&open=all_open"), ("bay", "az=8&el=48&d=3.4&tz=1.25&ty=0.6&open=bonnet_open")]
    t0 = time.time()
    procs = {
        "validate": subprocess.Popen(["node", os.path.join(args.tools, "validate.mjs"), fin],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True),
        "encode": subprocess.Popen(["node", os.path.join(args.tools, "encode.mjs"), fin, web],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True),
        "render": subprocess.Popen(["node", os.path.join(args.tools, "view.mjs"), "1000", "640"] +
                                   [f"{os.path.join(d, n)}.png:f={rel}&{q}" for n, q in shots],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   env={**os.environ, "VIEW_PORT": str(args.port)}),
    }
    outs = {}
    for k, pr in procs.items():
        try:
            o, e = pr.communicate(timeout=900)
        except subprocess.TimeoutExpired:
            pr.kill()
            o, e = pr.communicate()
        outs[k] = o
        lg.write(f"{k}\n{o[-4000:]}{e[-4000:]}\n")
        tm[k] = round(time.time() - t0, 1)
    try:
        rec["validator"] = json.loads(outs["validate"])
    except Exception:
        rec["validator"] = {"errors": -1}
    rec["web_bytes"] = os.path.getsize(web) if os.path.exists(web) else None
    try:
        from PIL import Image
        ims = [Image.open(os.path.join(d, n + ".png")).convert("RGB") for n, _ in shots]
        W, H = ims[0].size
        S = Image.new("RGB", (W * 2, H * 2))
        for i, im in enumerate(ims):
            S.paste(im, ((i % 2) * W, (i // 2) * H))
        S.save(os.path.join(d, "sheet.jpg"), quality=86)
        for n, _ in shots:
            os.remove(os.path.join(d, n + ".png"))
    except Exception as e:
        rec["sheet_error"] = str(e)
    rec["timings_s"] = tm
    for f in (src, fin):                         # the rigged copy stays, so a fix re-finishes in seconds
        if os.path.exists(f):
            os.remove(f)
    for f in os.listdir(rig):
        if f.endswith(".png"):
            os.remove(os.path.join(rig, f))
    # what this car should open: what the rig machine found plus what it looked
    # for and missed (a three-door car has no rear doors to miss)
    want = set(rr.get("opens") or []) | set(rr.get("missing") or []) | {"bonnet", "tailgate"}
    want = {"bonnet" if w == "panel_bonnet" else w for w in want}
    rec["missing"] = sorted(want - set(flog.get("opens") or []))
    ok = not rec["missing"] and rec["validator"].get("errors") == 0 and rec["web_bytes"] \
        and not rec.get("scale_unverified")
    rec["status"] = "done" if ok else "check"
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--class", dest="cls", default="car")
    ap.add_argument("--engine-pack", required=True)
    ap.add_argument("--tools", required=True)
    ap.add_argument("--view-dir", required=True)
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--skip", default="", help="comma-separated targets already finished, e.g. 'NISSAN QASHQAI'")
    args = ap.parse_args()
    args.engine_pack = os.path.abspath(args.engine_pack)
    os.makedirs(args.out, exist_ok=True)
    state = os.path.join(args.out, "state.jsonl")
    done = set()
    if os.path.exists(state):
        done = {json.loads(line)["asset"] for line in open(state) if line.strip()}
    cat = catalogue()
    rows = [r for r in csv.DictReader(open(os.path.join(REPO, "platform/catalogue/uk_targets/targets.csv")))
            if r["class"] == args.cls]
    rows.sort(key=lambda r: int(r["rank"]))
    server = subprocess.Popen([sys.executable, "-m", "http.server", str(args.port)], cwd=args.view_dir,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    n = 0
    try:
        for t in rows:
            if n >= args.top:
                break
            item = pick(t, cat)
            if item is None:
                continue
            n += 1
            if item["assetId"] in done or t["genModel"] in {x.strip() for x in args.skip.split(",")}:
                continue
            t0 = time.time()
            try:
                rec = one(t, item, args, args.out)
            except Exception as e:
                rec = {"rank": int(t["rank"]), "target": t["genModel"], "asset": item["assetId"],
                       "status": f"error: {e}"}
            rec["seconds"] = round(time.time() - t0)
            with open(state, "a") as f:
                f.write(json.dumps(rec, default=str) + "\n")
            print(rec["rank"], rec["asset"], rec["status"], rec["seconds"], "s", flush=True)
    finally:
        server.terminate()


if __name__ == "__main__":
    main()
