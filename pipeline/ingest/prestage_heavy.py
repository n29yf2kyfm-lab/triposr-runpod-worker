#!/usr/bin/env python3
"""prestage_heavy.py — download, decimate if needed, stage. Run BEFORE gpu_wave.

Why this exists (measured 2026-08-13, Ford wave): gpu_wave refuses any source
over MAX_OBJ (48MB, the Supabase per-object ceiling) and writes it to
HARD_REJECTS.json, whose contract is "uids that can NEVER succeed". That is
wrong for a big-but-good model: the size is a TRANSPORT limit, not a property
of the car, and decimate_heavy.py already reduces geometry safely (small parts
protected, hard ratio floor). The Ford Puma 2025 — the UK's best selling car,
of which the catalogue holds none — was auto-blacklisted that way at 66MB, and
came back to 18.5MB with its material table intact.

This stages the decimated file under the wave's prefix. gpu_wave skips any uid
already staged, so a wave run afterwards renders these without re-downloading
and without ever seeing the oversized original.

Verified on the Puma and the 2018 Fiesta: 66MB -> 18.5MB, materials unchanged.
Decimation does NOT invent the flat-shell defect — both of those cars were
single-material photogrammetry scans BEFORE decimation, checked against the
raw download.

Usage:
  SB_KEY=... SKETCHFAB_TOKENS=... python3 pipeline/ingest/prestage_heavy.py \
      --manifest gap6.json --stage staging/gap6 [--budget 450000] [--work DIR]
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from gpu_wave import MAX_OBJ, load_env, valid_glb        # noqa: E402

SB_BASE = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
API = "https://api.sketchfab.com/v3"
DECIMATE = os.path.join(REPO, "pipeline", "optimisation", "decimate_heavy.py")


def sb_put(path, blob, key):
    rq = urllib.request.Request(f"{SB_BASE}/{path}", data=blob, method="POST")
    # apikey AND Authorization — Bearer alone returns "403 Invalid Compact JWS"
    for h, v in (("apikey", key), ("Authorization", "Bearer " + key),
                 ("Content-Type", "model/gltf-binary"), ("x-upsert", "true")):
        rq.add_header(h, v)
    return urllib.request.urlopen(rq, timeout=600).status


def fetch(uid, token):
    rq = urllib.request.Request(f"{API}/models/{uid}/download",
                                headers={"Authorization": f"Token {token}",
                                         "User-Agent": "Mozilla/5.0"})
    url = (json.load(urllib.request.urlopen(rq, timeout=120)).get("glb") or {}).get("url")
    if not url:
        raise RuntimeError("no glb format offered")
    return urllib.request.urlopen(url, timeout=1800).read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--stage", required=True, help="e.g. staging/gap6")
    ap.add_argument("--budget", type=int, default=450_000)
    ap.add_argument("--work", default="/tmp/prestage")
    a = ap.parse_args()

    load_env()
    key = os.environ.get("SB_KEY") or sys.exit("FATAL: SB_KEY required")
    toks = [t.strip() for t in os.environ.get("SKETCHFAB_TOKENS", "").split(",") if t.strip()]
    if not toks:
        sys.exit("FATAL: SKETCHFAB_TOKENS required")
    os.makedirs(a.work, exist_ok=True)

    rows = json.load(open(a.manifest))
    for i, r in enumerate(rows, 1):
        uid, name = r["uid"], r.get("name", "")
        raw = os.path.join(a.work, f"{uid}.raw.glb")
        dec = os.path.join(a.work, f"{uid}.dec.glb")
        try:
            blob = fetch(uid, toks[(i - 1) % len(toks)])
        except Exception as e:
            print(f"[{i}/{len(rows)}] FETCH FAIL {uid[:8]} {type(e).__name__}: {e}", flush=True)
            continue
        if not valid_glb(blob):
            print(f"[{i}/{len(rows)}] BAD GLB {uid[:8]}", flush=True)
            continue
        if len(blob) <= MAX_OBJ:
            print(f"[{i}/{len(rows)}] {len(blob)/1e6:5.1f}MB fits — leaving to gpu_wave  {name[:38]}",
                  flush=True)
            continue
        open(raw, "wb").write(blob)
        p = subprocess.run(["xvfb-run", "-a", "blender", "-b", "--factory-startup",
                            "-noaudio", "--python", DECIMATE, "--",
                            "--in", raw, "--out", dec, "--budget", str(a.budget)],
                           capture_output=True, text=True)
        if p.returncode != 0 or not os.path.exists(dec):
            print(f"[{i}/{len(rows)}] DECIMATE FAIL {uid[:8]}: {p.stderr.strip()[-200:]}", flush=True)
            os.remove(raw)
            continue
        out = open(dec, "rb").read()
        if len(out) > MAX_OBJ:
            print(f"[{i}/{len(rows)}] STILL TOO BIG {len(out)/1e6:.1f}MB {uid[:8]} — "
                  "lower --budget", flush=True)
        else:
            sb_put(f"car-meshes/{a.stage}/{uid}.glb", out, key)
            print(f"[{i}/{len(rows)}] {len(blob)/1e6:5.1f}MB -> {len(out)/1e6:5.1f}MB staged  "
                  f"sha={hashlib.sha256(out).hexdigest()[:12]}  {name[:34]}", flush=True)
        for f in (raw, dec):
            if os.path.exists(f):
                os.remove(f)          # container disk fills fast; keep nothing
    print("PRESTAGE_DONE", flush=True)


if __name__ == "__main__":
    main()
