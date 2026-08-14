#!/usr/bin/env python3
"""test_hy21_render.py — edge-case suite for the Hunyuan training renderer.

Runs `hy21_render.py` over deliberately awkward REAL catalogue cars and asserts
the invariants the trainer depends on. Written before the 200-car sweep, because
a format fault here is invisible: training would simply learn from bad images
and the only symptom, weeks and hundreds of pounds later, would be a bad model.

INVARIANTS CHECKED
  I1 24 files 000..023.png exist, 512x512, RGBA (the dataloader ASSERTS 4 chans)
  I2 alpha coverage in a sane band per view — an empty frame scores ~0 and the
     first version of this renderer produced exactly that on every view
  I3 alpha is effectively BINARY. This is the car-specific risk: our glazing is
     alphaMode BLEND at ~0.72 and Hunyuan renders with the object's REAL
     materials (their `override_material()` is commented out in main()). If
     glass renders semi-transparent, the alpha channel — which the loader uses
     as the object MASK — gets holes exactly where the windows are, and the
     model trains on cars with see-through cabins.
  I4 mesh.ply centred with longest axis 1.0 (their mini_trainset convention)
  I5 no NaN/Inf in the exported ply
  I6 Draco input is REFUSED loudly rather than silently rendering nothing

EDGE CASES, chosen from measured extremes of the real catalogue:
  tiny-scale source, huge-scale source, very high face count, very low face
  count, and a car with heavy transparent glazing.

Usage:
  python3 pipeline/trellis/test_hy21_render.py [--keep]
"""
import argparse
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
RENDER = os.path.join(HERE, "hy21_render.py")
CAT = os.path.join(REPO, "platform", "catalogue", "catalogue.v2.json")

ALPHA_MIN, ALPHA_MAX = 0.02, 0.75      # per-view coverage sanity band
PARTIAL_MAX = 0.06                     # share of pixels allowed strictly between


def log(*a):
    print(*a, flush=True)


def is_draco(path):
    raw = open(path, "rb").read(1 << 21)
    if raw[:4] != b"glTF":
        return False
    ln = struct.unpack("<I", raw[12:16])[0]
    try:
        g = json.loads(raw[20:20 + min(ln, len(raw) - 20)])
    except Exception:
        return False
    ext = set(g.get("extensionsUsed", [])) | set(g.get("extensionsRequired", []))
    return "KHR_draco_mesh_compression" in ext


def fetch(url, dst):
    with urllib.request.urlopen(url, timeout=900) as r, open(dst, "wb") as f:
        while True:
            c = r.read(1 << 20)
            if not c:
                break
            f.write(c)


def undraco(src, dst):
    p = subprocess.run(["gltf-transform", "copy", src, dst],
                       capture_output=True, text=True, timeout=600)
    return p.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 10000


def render(glb, outdir, views=24, res=512, samples=16, timeout=2400):
    os.makedirs(outdir, exist_ok=True)
    cmd = ["xvfb-run", "-a", "blender", "-b", "--factory-startup", "-noaudio",
           "-P", RENDER, "--", "--object", glb, "--output_folder", outdir,
           "--views", str(views), "--resolution", str(res), "--samples", str(samples)]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return p, time.time() - t0


def check(outdir, views=24, res=512):
    """Returns (ok, failures[], stats{})."""
    from PIL import Image
    import trimesh
    fails = []

    # I1
    missing = [i for i in range(views)
               if not os.path.exists(os.path.join(outdir, f"{i:03d}.png"))]
    if missing:
        return False, [f"I1 missing {len(missing)} renders"], {}

    covs, partials = [], []
    for i in range(views):
        a = np.asarray(Image.open(os.path.join(outdir, f"{i:03d}.png")))
        if a.shape != (res, res, 4):
            fails.append(f"I1 view {i}: shape {a.shape} != ({res},{res},4)")
            break
        al = a[..., 3].astype(np.float32) / 255.0
        covs.append(float((al > 0.5).mean()))
        # I3: pixels neither clearly background nor clearly object
        partials.append(float(((al > 0.08) & (al < 0.92)).mean()))

    if covs:
        if min(covs) < ALPHA_MIN:
            fails.append(f"I2 empty-ish view: min coverage {min(covs):.3f} < {ALPHA_MIN}")
        if max(covs) > ALPHA_MAX:
            fails.append(f"I2 overfull view: max coverage {max(covs):.3f} > {ALPHA_MAX}")
        if max(partials) > PARTIAL_MAX:
            fails.append(f"I3 alpha NOT binary: {max(partials):.3f} of pixels "
                         f"partially transparent (>{PARTIAL_MAX}) — glazing holes?")

    # I4 / I5
    ply = os.path.join(outdir, "mesh.ply")
    stats = {}
    if not os.path.exists(ply):
        fails.append("I4 mesh.ply missing")
    else:
        m = trimesh.load(ply, process=False)
        v = np.asarray(m.vertices)
        if not np.isfinite(v).all():
            fails.append("I5 ply contains NaN/Inf")
        mn, mx = v.min(0), v.max(0)
        longest = float((mx - mn).max())
        centre = float(np.abs((mn + mx) / 2).max())
        stats.update(longest=round(longest, 4), centre_off=round(centre, 4),
                     verts=len(v))
        if not (0.99 <= longest <= 1.01):
            fails.append(f"I4 longest axis {longest:.4f} != 1.0")
        if centre > 0.01:
            fails.append(f"I4 not centred, max centre offset {centre:.4f}")

    stats.update(cov_min=round(min(covs), 3) if covs else None,
                 cov_mean=round(float(np.mean(covs)), 3) if covs else None,
                 partial_max=round(max(partials), 3) if partials else None)
    return (not fails), fails, stats


def pick_cases():
    """Edge cases drawn from measured extremes of the real catalogue."""
    cat = json.load(open(CAT))
    ap = [e for e in cat if e.get("publicationStatus") == "approved"
          and e.get("desktopGlbUrl")]
    scores = {}
    sp = os.path.join(HERE, "TRAINSET_SCORES.jsonl")
    if os.path.exists(sp):
        for line in open(sp):
            try:
                r = json.loads(line)
                if "crease" in r:
                    scores[r["assetId"]] = r
            except Exception:
                pass
    by = {e["assetId"]: e for e in ap}
    rows = [scores[a] for a in scores if a in by]
    rows.sort(key=lambda r: r.get("faces", 0))
    cases = []
    if rows:
        cases.append(("lowest-face", rows[0]["assetId"]))
        cases.append(("highest-face", rows[-1]["assetId"]))
        rows.sort(key=lambda r: r.get("diag", 0))
        cases.append(("smallest-scale", rows[0]["assetId"]))
        cases.append(("largest-scale", rows[-1]["assetId"]))
    # a car with heavy transparent glazing — published, glass proven clear
    for cand in ("kia-picanto-2024-m1-v1", "skoda-octavia-2025-m1-v1"):
        if cand in by:
            cases.append(("transparent-glazing", cand))
            break
    seen, out = set(), []
    for tag, aid in cases:
        if aid in seen:
            continue
        seen.add(aid)
        out.append((tag, aid, by[aid]["desktopGlbUrl"]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()

    cases = pick_cases()
    log(f"{len(cases)} edge cases\n")
    tmp = tempfile.mkdtemp(prefix="hy21test_")
    npass = nfail = 0
    draco_tested = False

    for tag, aid, url in cases:
        log(f"--- {tag}: {aid}")
        src = os.path.join(tmp, f"{aid}.glb")
        try:
            fetch(url, src)
        except Exception as e:
            log(f"    SKIP download {type(e).__name__}"); continue

        if is_draco(src):
            # I6: the guard must REFUSE, not silently render nothing
            p, _ = render(src, os.path.join(tmp, aid, "draco_probe"), views=2)
            refused = "Draco-compressed" in (p.stdout + p.stderr)
            log(f"    I6 draco guard: {'REFUSED (correct)' if refused else 'DID NOT REFUSE'}")
            if not refused:
                nfail += 1; log("    FAIL I6"); continue
            draco_tested = True
            dec = os.path.join(tmp, f"{aid}_dec.glb")
            if not undraco(src, dec):
                log("    SKIP: draco decode failed"); continue
            src = dec

        outdir = os.path.join(tmp, aid, "render_cond")
        p, secs = render(src, outdir)
        if p.returncode != 0:
            tail = (p.stdout + p.stderr).strip().splitlines()[-3:]
            log(f"    FAIL render rc={p.returncode} {secs:.0f}s :: {' | '.join(tail)}")
            nfail += 1; continue
        ok, fails, stats = check(outdir)
        log(f"    {secs:5.1f}s  {stats}")
        if ok:
            npass += 1; log("    PASS")
        else:
            nfail += 1
            for f in fails:
                log(f"    FAIL {f}")

    log(f"\n{npass} passed, {nfail} failed"
        + ("" if draco_tested else "  (no Draco case encountered — I6 untested)"))
    if not a.keep:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
