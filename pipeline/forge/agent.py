#!/usr/bin/env python3
"""agent.py — run Forge over the UK target list with nobody watching.

    python3 pipeline/forge/agent.py [--class car] [--top 50] [--only "ford fiesta"]
                                    [--out forge_out] [--redo]

For every target, in parc order:
  1. the generation and years from the UK index;
  2. dimensions (dims.py: repo tables, then Wikipedia's infobox);
  3. licensed photographs (finder.py: Wikimedia Commons, backgrounds removed);
  4. forge.py --skin: the GLB, with its self-check;
  5. the open/shut render sheet, when BLENDER_BIN points at a Blender (the
     Strip Bay rigger does the opening); skipped otherwise;
  6. upload to the bucket when SB_KEY is set; otherwise the files stay in
     OUT/<id>/ for the owner to collect.

One line per target goes to OUT/state.jsonl: done, or why not (no dims, no
side photo, build failed). A failure never stops the run, and a re-run skips
every target already in the state file unless --redo.
"""
import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
from dims import get_dims, norm       # noqa: E402
from finder import find_photos        # noqa: E402

STYLE = {"hatchback": "hatch", "saloon": "saloon", "estate": "estate", "suv": "suv", "coupe": "coupe",
         "convertible": "coupe", "mpv": "suv", "pickup": "suv", "van": "estate"}


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def uk_index():
    p = os.path.join(REPO, "platform", "catalogue", "vehicle_index.json")
    return json.load(open(p))["vehicles"] if os.path.exists(p) else []


def generation_for(make, model, index):
    """The latest generation the UK index knows for this nameplate."""
    hits = [v for v in index if norm(v["make"]) == norm(make) and norm(v["model"]) == norm(model)]
    if not hits:
        return None

    def gen_no(v):                      # Mk8 -> 8, 8V -> 8, AW -> 0: the tie-break when years match
        m = re.search(r"\d+", str(v.get("generation") or ""))
        return int(m.group(0)) if m else 0
    return max(hits, key=lambda v: (v.get("year_to") or 0, v.get("year_from") or 0, gen_no(v)))


def render_sheet(glb, out_dir):
    blender = os.environ.get("BLENDER_BIN")
    if not blender or not os.path.exists(blender):
        return None
    run = os.path.join(REPO, "platform", "rigmachine", "run.py")
    rig_dir = os.path.join(out_dir, "rig")
    shutil.rmtree(rig_dir, ignore_errors=True)
    try:
        subprocess.run([sys.executable, run, glb, rig_dir, "--size=720x450", "--samples=6"],
                       capture_output=True, timeout=900)
    except subprocess.TimeoutExpired:
        return None
    sheet = os.path.join(rig_dir, "sheet.jpg")
    res = os.path.join(rig_dir, "result.json")
    if os.path.exists(sheet):
        shutil.copy(sheet, os.path.join(out_dir, "sheet.jpg"))
    r = json.load(open(res)) if os.path.exists(res) else {}
    for f in os.listdir(rig_dir):            # no GLB copies left behind
        if f.endswith(".glb"):
            os.remove(os.path.join(rig_dir, f))
    return {"opens": r.get("opens"), "status": r.get("status"), "sheet": os.path.exists(sheet)}


def upload(out_dir, car_id):
    key = os.environ.get("SB_KEY")
    if not key:
        return None
    base = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/car-meshes/forge/" + car_id
    done = []
    for f in os.listdir(out_dir):
        p = os.path.join(out_dir, f)
        if not os.path.isfile(p) or f.endswith(".bak"):
            continue
        ct = "model/gltf-binary" if f.endswith(".glb") else "image/jpeg" if f.endswith(".jpg") else \
             "image/png" if f.endswith(".png") else "application/json"
        r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-X", "POST", f"{base}/{f}",
                            "-H", f"apikey: {key}", "-H", f"Authorization: Bearer {key}", "-H", f"Content-Type: {ct}",
                            "-H", "x-upsert: true", "--data-binary", f"@{p}"], capture_output=True, text=True)
        done.append((f, r.stdout.strip()))
    return done


def one(t, index, out_root, session, redo=False):
    make, model = t["make"].title(), t["genModel"].replace(t["make"], "", 1).strip().title()
    car_id = re.sub(r"[^a-z0-9]+", "-", f"{make} {model}".lower()).strip("-")
    out_dir = os.path.join(out_root, car_id)
    os.makedirs(out_dir, exist_ok=True)
    row = {"id": car_id, "class": t["class"], "rank": int(t["rank"]), "make": make, "model": model,
           "licensed": int(t["licensed"]), "at": time.strftime("%Y-%m-%d %H:%M")}
    gen = generation_for(make, model, index)
    hints = []
    if gen:
        row["generation"] = gen.get("generation")
        row["years"] = [gen.get("year_from"), gen.get("year_to")]
        hints = [h for h in (gen.get("generation"), str(gen.get("year_from") or "")) if h]
    dims = get_dims(make, model, gen.get("generation") if gen else None)
    if not dims:
        row.update(status="no dims", reason="no published dimensions found (repo tables, Wikipedia)")
        return row
    style = STYLE.get((gen or {}).get("body_style") or "", "hatch")
    d = {"name": car_id, "style": style, "length": dims["length"], "width": dims["width"], "height": dims["height"],
         "wheelbase": dims["wheelbase"], "track": dims.get("track", round(dims["width"] * 0.86)),
         "wheel_d": dims.get("wheel_d", 650), "tyre_w": dims.get("tyre_w", 205)}
    json.dump(d, open(os.path.join(out_dir, "dims.json"), "w"), indent=1)
    row["dims_source"] = dims.get("source")
    if redo or not os.path.exists(os.path.join(out_dir, "side.png")):
        found = find_photos(make, model, hints, out_dir, session=session)
        row["photos"] = found
    if not os.path.exists(os.path.join(out_dir, "side.png")):
        row.update(status="no side photo", reason="no licensed true side view on Commons")
        return row
    from forge import run as forge_run
    glb = os.path.join(out_dir, car_id + ".glb")
    try:
        _, rep = forge_run(out_dir, glb, skin=True)
    except Exception as e:
        row.update(status="build failed", reason=f"{type(e).__name__}: {e}"[:160])
        return row
    row["overlap"] = rep.get("overlap")
    row["used"] = rep.get("used")
    row["glb_kb"] = rep.get("glb", {}).get("kb")
    row["sheet"] = render_sheet(glb, out_dir)
    up = upload(out_dir, car_id)
    if up:
        row["uploaded"] = up
        if all(code in ("200", "201") for _, code in up):
            os.remove(glb)                    # the bucket has it; the box does not keep GLBs
    row["status"] = "done"
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--targets", default=os.path.join(REPO, "platform", "catalogue", "uk_targets", "targets.csv"))
    ap.add_argument("--class", dest="cls", default="car")
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--only", help='"make model" to run one target')
    ap.add_argument("--out", default="forge_out")
    ap.add_argument("--redo", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    state_p = os.path.join(a.out, "state.jsonl")
    done = {}
    if os.path.exists(state_p):
        for l in open(state_p):
            r = json.loads(l)
            done[r["id"]] = r
    targets = [t for t in csv.DictReader(open(a.targets)) if t["class"] == a.cls]
    if a.only:
        targets = [t for t in targets if norm(a.only) == norm(t["genModel"]) or norm(a.only) == norm(t["make"] + t["genModel"])]
    targets = targets[:a.top]
    index = uk_index()
    from rembg import new_session
    session = new_session("u2net")
    log(f"FORGE AGENT {len(targets)} targets, {len(done)} already in state")
    for t in targets:
        car_id = re.sub(r"[^a-z0-9]+", "-", f"{t['make']} {t['genModel'].replace(t['make'], '', 1)}".lower()).strip("-")
        if car_id in done and done[car_id].get("status") == "done" and not a.redo:
            continue
        try:
            row = one(t, index, a.out, session, redo=a.redo)
        except Exception:
            row = {"id": car_id, "status": "error", "reason": traceback.format_exc()[-300:]}
        with open(state_p, "a") as f:
            f.write(json.dumps(row, default=str) + "\n")
        log(f"{row['status']:14s} {car_id}  {row.get('reason') or row.get('overlap') or ''}")
    rows = [json.loads(l) for l in open(state_p)]
    from collections import Counter
    log("SUMMARY " + json.dumps(Counter(r["status"] for r in rows)))


if __name__ == "__main__":
    main()
