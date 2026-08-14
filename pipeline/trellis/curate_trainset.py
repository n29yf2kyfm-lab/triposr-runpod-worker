#!/usr/bin/env python3
"""curate_trainset.py — score every approved catalogue car by crease density.

The fine-tune plan's curation step (MACHINE_PLAN.md): three of six sampled
catalogue cars carry LESS sharp geometry than Hunyuan3D-2.1 already generates,
so training on the whole catalogue would partly teach softness. This sweep
scores all approved cars so the pilot trains only on the top slice.

Built for THIS container's realities:
  * streams — download, measure, delete; never holds more than a few GLBs
  * resumable — skips uids already in the results file, and re-pulls partial
    results from Supabase at start (the container rolls back; scratchpad dies)
  * uploads partial results every 25 cars (the same habit that saved wave-10)
  * Draco: published outputs are often Draco-compressed and trimesh returns
    placeholder ZEROS for them, so those are decompressed with gltf-transform
    first; if the CLI is missing the car is recorded draco_unreadable, never
    silently scored from zeros (crease_density refuses those anyway)
  * every measure runs with a hard timeout so one pathological mesh cannot
    hang the sweep

Usage:
  python3 pipeline/trellis/curate_trainset.py [--limit N] [--workers 3]
"""
import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

CAT = os.path.join(REPO, "platform", "catalogue", "catalogue.v2.json")
OUT = os.path.join(HERE, "TRAINSET_SCORES.jsonl")
SB = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
REMOTE = "car-meshes/hy21_train/trainset_scores.jsonl"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def sb_key():
    return os.environ.get("SB_KEY", "")


def upload_partial():
    k = sb_key()
    if not k or not os.path.exists(OUT):
        return
    try:
        body = open(OUT, "rb").read()
        rq = urllib.request.Request(f"{SB}/{REMOTE}", data=body, method="POST",
                                    headers={"apikey": k, "Authorization": "Bearer " + k,
                                             "x-upsert": "true",
                                             "Content-Type": "application/jsonl"})
        urllib.request.urlopen(rq, timeout=120).read()
    except Exception as e:
        log(f"partial upload failed ({type(e).__name__}) — continuing, local file is intact")


def restore_partial():
    """After a rollback the local file is gone but Supabase still has it."""
    if os.path.exists(OUT):
        return
    try:
        rq = urllib.request.Request(
            f"https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/public/{REMOTE}")
        body = urllib.request.urlopen(rq, timeout=60).read()
        if body and b"assetId" in body:
            open(OUT, "wb").write(body)
            log(f"restored {sum(1 for _ in open(OUT))} prior results from Supabase")
    except Exception:
        pass


def is_draco(path):
    raw = open(path, "rb").read(1 << 21)
    if raw[:4] != b"glTF" or len(raw) < 20:
        return False
    ln = struct.unpack("<I", raw[12:16])[0]
    try:
        g = json.loads(raw[20:20 + min(ln, len(raw) - 20)])
    except Exception:
        return False
    ext = set(g.get("extensionsUsed", [])) | set(g.get("extensionsRequired", []))
    return "KHR_draco_mesh_compression" in ext


def gltf_transform():
    for c in ("gltf-transform",):
        p = shutil.which(c)
        if p:
            return [p]
    # npx fallback (slower first call, cached after)
    if shutil.which("npx"):
        return ["npx", "-y", "@gltf-transform/cli"]
    return None


def score_one(entry):
    """Runs in a worker process. Returns a result dict, never raises."""
    from crease_density import measure
    aid = entry["assetId"]
    url = entry["desktopGlbUrl"]
    tmp = tempfile.mkdtemp(prefix="cur_")
    row = {"assetId": aid, "make": entry.get("make"), "model": entry.get("model")}
    try:
        src = os.path.join(tmp, "m.glb")
        with urllib.request.urlopen(url, timeout=600) as r, open(src, "wb") as f:
            while True:
                c = r.read(1 << 20)
                if not c:
                    break
                f.write(c)
        row["bytes"] = os.path.getsize(src)
        path = src
        if is_draco(src):
            row["draco"] = True
            gt = gltf_transform()
            if not gt:
                row["error"] = "draco_unreadable_no_gltf_transform"
                return row
            dec = os.path.join(tmp, "d.glb")
            p = subprocess.run(gt + ["copy", src, dec], capture_output=True,
                               text=True, timeout=300)
            if p.returncode != 0 or not os.path.exists(dec) or os.path.getsize(dec) < 10000:
                row["error"] = "draco_decode_failed"
                return row
            path = dec
        m = measure(path)
        if m is None:
            row["error"] = "unreadable"
            return row
        row.update(crease=round(m["crease_per_diag"], 1), faces=m["faces"],
                   diag=round(m["diag"], 2))
        return row
    except Exception as e:
        row["error"] = f"{type(e).__name__}: {str(e)[:120]}"
        return row
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()

    restore_partial()
    done = set()
    if os.path.exists(OUT):
        for line in open(OUT):
            try:
                done.add(json.loads(line)["assetId"])
            except Exception:
                pass

    cat = json.load(open(CAT))
    todo = [e for e in cat
            if e.get("publicationStatus") == "approved" and e.get("desktopGlbUrl")
            and e["assetId"] not in done]
    if a.limit:
        todo = todo[:a.limit]
    log(f"approved with GLB: pending {len(todo)}  (already scored {len(done)})")

    n_ok = n_err = 0
    with ProcessPoolExecutor(a.workers) as ex, open(OUT, "a") as out:
        futs = {ex.submit(score_one, e): e["assetId"] for e in todo}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                row = f.result(timeout=900)
            except Exception as e:
                row = {"assetId": futs[f], "error": f"worker:{type(e).__name__}"}
            out.write(json.dumps(row) + "\n")
            out.flush()
            if "error" in row:
                n_err += 1
                log(f"[{i}/{len(todo)}] ERR  {row['assetId'][:36]:36s} {row['error'][:50]}")
            else:
                n_ok += 1
                log(f"[{i}/{len(todo)}] {row['crease']:7.1f}  {row['assetId'][:40]}")
            if i % 25 == 0:
                upload_partial()
    upload_partial()

    # summary over EVERYTHING scored (this run + prior)
    rows = [json.loads(l) for l in open(OUT)]
    good = [r for r in rows if "crease" in r]
    log(f"scored {len(good)} ok, {len(rows)-len(good)} errors "
        f"(this run: {n_ok} ok, {n_err} err)")
    for th in (200, 150, 100, 63.3):
        n = sum(1 for r in good if r["crease"] >= th)
        tag = "  <- Hunyuan-2.1 generates at 63.3" if th == 63.3 else ""
        log(f"  crease >= {th:5}: {n:4d} cars{tag}")
    good.sort(key=lambda r: -r["crease"])
    log("top 10: " + ", ".join(f"{r['assetId'][:28]}({r['crease']:.0f})" for r in good[:10]))
    log("SWEEP_DONE")


if __name__ == "__main__":
    main()
