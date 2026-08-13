#!/usr/bin/env python3
"""source_probe.py — glTF material verdicts for candidates BEFORE any render.

Council order 2026-08-13, after the owner said Keep on a clay shell: every
known detector must run before a sheet reaches the owner's eyes. This is the
missing pre-render stage. It reads only the glTF JSON chunk (a ranged read —
no mesh bytes), so it costs nothing next to a GPU render and can run on a
whole sweep.

Verdicts, each grounded in a measured defect class:

  flat_shell   All untextured materials share ONE baseColorFactor. This is
               Sketchfab's converter flattening a non-glTF upload (proven
               2026-08-13 on fresh candidates: Juke 2023 all-0.588 across 20
               materials, Astra 2022 all-0.800 across 45 — flat in their
               GLTF archive as well as the GLB, so no other format recovers
               it). The material NAMES survive, which is why a rich table is
               not evidence of a good car, and why the wave header's
               cov/mats numbers are blind to it (the Juke read
               'mats=1 cov=0.121 recolourable'). Owner scrapped 64 live cars
               for this class. HARD SKIP.

  atlas_scan   <=2 materials with >=1 texture image: a photogrammetry scan
               or game-rip with everything baked into one atlas. No respray
               possible, glazing baked opaque (Ford Puma 2025, Fiesta 2018).
               HARD SKIP for the premium bar.

  ok           None of the above fired. NOT a quality pass — geometry,
               wheels, pose and glazing still need their own gates. This
               probe only kills the two classes that keep reaching sheets.

A row that cannot be probed scores "unknown", never a skip — an unreadable
candidate must reach the eye rather than die silently (same rule as
tyre_probe: a failed read must not manufacture a verdict).

Usage:
  source_probe.py --manifest m.json [--out annotated.json] [--drop]
      rows need "uid" (Sketchfab download API is used) or a direct "url"
  source_probe.py --url https://.../file.glb        # one-off check
"""
import argparse
import io
import json
import os
import struct
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

API = "https://api.sketchfab.com/v3"
# JSON chunk cap: the biggest catalogue glTF JSON seen is ~3MB; 8MB covers it.
CAP = 8_000_000


def _read(url, n):
    rq = urllib.request.Request(url, headers={"Range": f"bytes=0-{n-1}",
                                              "User-Agent": "Mozilla/5.0"})
    try:
        return urllib.request.urlopen(rq, timeout=300).read(n)
    except urllib.error.HTTPError as e:
        if e.code == 416:
            return urllib.request.urlopen(url, timeout=300).read(n)
        raise


def gltf_json(url):
    head = _read(url, 20)
    if head[:4] != b"glTF":
        raise ValueError("not a GLB")
    ln = struct.unpack("<I", head[12:16])[0]
    if ln > CAP:
        raise ValueError(f"JSON chunk {ln/1e6:.0f}MB over cap")
    blob = _read(url, 20 + ln)
    return json.loads(blob[20:20 + ln])


def verdict(g):
    mats = g.get("materials", [])
    n_img = len(g.get("images", []))
    untex = [m for m in mats
             if "baseColorTexture" not in m.get("pbrMetallicRoughness", {})]
    vals = {tuple(round(x, 4) for x in
                  m.get("pbrMetallicRoughness", {}).get("baseColorFactor",
                                                        [1, 1, 1, 1])[:3])
            for m in untex}
    out = {"n_materials": len(mats), "n_textures": n_img,
           "n_untextured": len(untex), "distinct_colours": len(vals)}
    if len(untex) >= 3 and len(vals) == 1:
        out["verdict"] = "flat_shell"
        out["flat_value"] = list(vals)[0]
    elif len(mats) <= 2 and n_img >= 1:
        out["verdict"] = "atlas_scan"
    else:
        out["verdict"] = "ok"
    return out


def dl_url(uid, tok):
    rq = urllib.request.Request(f"{API}/models/{uid}/download",
                                headers={"Authorization": f"Token {tok}",
                                         "User-Agent": "Mozilla/5.0"})
    d = json.load(urllib.request.urlopen(rq, timeout=120))
    return (d.get("glb") or {}).get("url")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest")
    ap.add_argument("--url", help="probe one GLB URL and exit")
    ap.add_argument("--out", help="write annotated manifest here")
    ap.add_argument("--drop", action="store_true",
                    help="drop flat_shell/atlas_scan rows from --out")
    a = ap.parse_args()

    if a.url:
        print(json.dumps(verdict(gltf_json(a.url)), indent=1))
        return

    toks = [t.strip() for t in
            os.environ.get("SKETCHFAB_TOKENS", "").split(",") if t.strip()]
    rows = json.load(open(a.manifest))
    kept, counts = [], {}
    for i, r in enumerate(rows, 1):
        try:
            url = r.get("url") or dl_url(r["uid"], toks[(i - 1) % len(toks)])
            v = verdict(gltf_json(url))
        except Exception as e:
            v = {"verdict": "unknown", "error": f"{type(e).__name__}: {e}"[:120]}
        r["probe"] = v
        counts[v["verdict"]] = counts.get(v["verdict"], 0) + 1
        print(f"[{i}/{len(rows)}] {v['verdict']:10s} "
              f"{r.get('name', r.get('uid', ''))[:52]}", flush=True)
        if not (a.drop and v["verdict"] in ("flat_shell", "atlas_scan")):
            kept.append(r)
    print("SUMMARY:", counts, flush=True)
    if a.out:
        json.dump(kept, open(a.out, "w"), indent=1)
        print(f"wrote {a.out} ({len(kept)} rows"
              f"{', flagged rows dropped' if a.drop else ''})")


if __name__ == "__main__":
    main()
