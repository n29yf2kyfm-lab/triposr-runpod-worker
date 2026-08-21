#!/usr/bin/env python3
"""
fidelity.py -- did the reduction change what the customer SEES, and did it
quietly delete a component?

    python3 pipeline/machine/mobile/fidelity.py master.glb candidate.glb \\
            --out-dir /tmp/fid --json fid.json

TWO INDEPENDENT CHECKS, BECAUSE EITHER ONE ALONE HAS BEEN PROVEN INSUFFICIENT
----------------------------------------------------------------------------

(1) APPEARANCE -- PSNR at matched cameras, PRIMARY.

    Silhouette IoU is NOT a fidelity metric and must never be used as one.
    Measured on this programme: a negative control that deleted 96% of all
    triangles still scored min IoU 0.991. A car's outline is smooth and
    low-frequency, so alpha coverage barely moves while the surface is
    destroyed. PSNR caught that same case at 26.93 dB against a healthy
    37.81 dB.

    IoU is still computed and reported -- it is the right detector for GROSS
    failures (wrong scale, missing part, failed decode) and it caught three
    probe bugs at 0.07-0.16 in mobile_export.py's history. It is reported as a
    SANITY channel and it does not decide the verdict.

    PER-ZONE, NEVER WHOLE-CAR-ONLY. CLAUDE.md 2026-08-16, on why five machine
    passes were accepted by one eye and rejected by another: "full-car beauty
    sheets average away component failures". A whole-car PSNR does exactly that
    arithmetically. So close-ups are rendered on the components most likely to
    be destroyed by decimation and most likely to be owner-visible defects --
    wheel, glazing, lamp -- and the verdict takes the MINIMUM over all zones.

(2) GEOMETRY RETENTION -- per material, triangles AND SURFACE AREA.

    This is the check for the specific way a decimator can pass everything else
    and still ship a scrap. Under the owner's confirmed 2026-08-11 ruling,
    opaque glazing is a hard scrap; 119 live cars (10.3% of the catalogue) were
    culled on it alone. `glass_probe` is the gate for that -- and `glass_probe`
    READS THE MATERIAL TABLE. A decimator that collapses a window pane to
    nothing leaves the `glass` material sitting in the table with its
    transmission factor untouched, so glass_probe still returns clear/proven on
    a car with no glass in it. Verified in this gate's negative control NC2.

    Area, not face count, is the physical quantity: CLAUDE.md 2026-08-19
    measured glass faces 1.58x smaller than body faces, so a face-count share
    mis-states a share of the car. Both are reported; the gate is on area.

WORLD SPACE, END TO END
-----------------------
Cameras are derived from the MASTER's WORLD bounds (node transforms applied) and
the identical camera strings are then used for the candidate. Deriving cameras
from each file's own bounds moves the camera with the mesh and makes the
comparison meaningless -- and a stage that alters a NODE TRANSFORM while leaving
local vertices intact is invisible to any local-space check.

RENDERER CAVEAT
---------------
Chromium + SwiftShader, software, desktop. Deterministic and identical on both
sides, so the DELTA is sound. It is not a device result.
"""

import argparse
import json
import os
import shutil
import socketserver
import subprocess
import sys
import threading

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # pipeline/machine
sys.path.insert(0, HERE)
import viewer_check as VC                          # noqa: E402
from mobile_metrics import glb_read, measure, node_world_translations  # noqa: E402

GLTF_TRANSFORM = shutil.which("gltf-transform") or "/opt/node22/bin/gltf-transform"

ORBIT_AZ = [0, 45, 90, 135, 180, 215, 270, 315]
ORBIT_EL_DEG = 78.0        # model-viewer phi: 90deg = horizon, smaller = above

# Close-up zones. Each entry: (label, node-name regex, radius as a multiple of
# THAT ONE NODE's bbox diagonal). Chosen for what decimation destroys first and
# what the owner rulings are about -- rubber, glazing, lamp lenses.
#
# ONE NODE, NOT THE UNION. The first draft matched `wheel_f[lr]_(rim|tyre)` and
# unioned both front wheels, so the "close-up" bbox spanned the full track and
# the camera framed the whole car -- caught by LOOKING at the render, which is
# the only thing that would have caught it. `lamp_[lr]` was worse: it matched
# head AND tail lamps, spanning the car's whole length, and framed the car at
# 11 m. Each zone now uses the FIRST matching node only.
CLOSEUPS = [
    ("cu_wheel", r"^wheel_fl_(rim|tyre)$", 2.5),
    ("cu_glazing", r"^glass_side_l$", 2.2),
    ("cu_lamp", r"^taillamp_l$|^tail_lamp_l$|^headlamp_l$", 2.8),
]

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<link rel="icon" href="data:,">
<style>html,body{margin:0;background:#202024}
model-viewer{width:768px;height:576px;background:#202024}</style></head><body>
<model-viewer id="mv" disable-pan disable-zoom interaction-prompt="none"
  shadow-intensity="0" exposure="1" environment-image="neutral"
  min-camera-orbit="auto auto 0m" max-camera-orbit="auto auto 1000m"
  min-field-of-view="1deg" max-field-of-view="120deg"></model-viewer>
<script>window.__loaded=false;window.__failed=null;
const mv=document.getElementById('mv');
mv.addEventListener('load',()=>{window.__loaded=true;});
mv.addEventListener('error',e=>{window.__failed=JSON.stringify(e.detail||'error');});</script>
<script type="module">
import '/model-viewer.min.js';
await customElements.whenDefined('model-viewer');
const MV=customElements.get('model-viewer');
MV.meshoptDecoderLocation='/meshopt_decoder.js'; MV.dracoDecoderLocation='/draco/';
window.__setSrc=(s)=>{window.__loaded=false;window.__failed=null;
  document.getElementById('mv').src=s;};
window.__cam=(orbit,target,fov)=>{const mv=document.getElementById('mv');
  mv.cameraOrbit=orbit; mv.cameraTarget=target; mv.fieldOfView=fov;
  mv.jumpCameraToGoal();};
window.__ready=true;
</script></body></html>"""


def _serve(directory):
    handler = lambda *a, **k: VC.Quiet(*a, directory=directory, **k)
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def decode(path, workdir):
    """Return a path whose accessors are readable, decompressing if needed.

    trimesh AND this module's own accessor reader are both blind to
    KHR_draco_mesh_compression / EXT_meshopt_compression -- CLAUDE.md records
    that trimesh returns an all-zero vertex array for Draco and prints a
    'placeholder zeros' line to stderr that is easy to miss. `copy` decodes it;
    `dequantize` is additionally required after meshopt, which leaves
    KHR_mesh_quantization behind and makes int16s read as metres.
    """
    js, _ = glb_read(path)
    ext = js.get("extensionsUsed", [])
    cur = path
    os.makedirs(workdir, exist_ok=True)
    if any(e in ext for e in ("KHR_draco_mesh_compression", "EXT_meshopt_compression")):
        nxt = os.path.join(workdir, os.path.basename(path) + ".dec.glb")
        subprocess.run([GLTF_TRANSFORM, "copy", cur, nxt], check=True,
                       capture_output=True, text=True)
        cur = nxt
    js2, _ = glb_read(cur)
    if "KHR_mesh_quantization" in js2.get("extensionsUsed", []):
        nxt = os.path.join(workdir, os.path.basename(path) + ".deq.glb")
        subprocess.run([GLTF_TRANSFORM, "dequantize", cur, nxt], check=True,
                       capture_output=True, text=True)
        cur = nxt
    return cur


# --------------------------------------------------------------------------
# (2) geometry retention
# --------------------------------------------------------------------------

def geometry_retention(master, candidate, workdir="/tmp/fid_geom",
                       min_area_ratio=0.85, critical=("glass", "Tyre_Rubber",
                                                      "Lamp_Lens", "Lamp_Lens_Rear",
                                                      "Rim_Alloy")):
    """Per-material triangle and AREA retention, master -> candidate.

    `critical` names the materials whose disappearance is an owner-level scrap
    rather than a cosmetic loss. They are gated; everything else is reported.
    """
    a = measure(decode(master, workdir))
    b = measure(decode(candidate, workdir))
    if not (a.get("geometryDecoded") and b.get("geometryDecoded")):
        return {"status": "NOT_TESTED",
                "reason": "geometry census unavailable: %s / %s"
                          % (a.get("geometryError"), b.get("geometryError"))}
    rows, fails = [], []
    for name, da in sorted(a["perMaterial"].items(), key=lambda kv: -kv[1]["area"]):
        db = b["perMaterial"].get(name)
        if db is None:
            rows.append({"material": name, "areaRatio": 0.0, "triRatio": 0.0,
                         "critical": name in critical, "gone": True})
            fails.append("%s: material GONE from candidate" % name)
            continue
        ar = db["area"] / da["area"] if da["area"] else 1.0
        tr = db["triangles"] / da["triangles"] if da["triangles"] else 1.0
        row = {"material": name, "critical": name in critical,
               "areaMaster": round(da["area"], 5), "areaCandidate": round(db["area"], 5),
               "areaRatio": round(ar, 4),
               "trianglesMaster": da["triangles"], "trianglesCandidate": db["triangles"],
               "triRatio": round(tr, 4), "gone": False}
        rows.append(row)
        if name in critical and ar < min_area_ratio:
            fails.append("%s: surface area retained only %.1f%% (need >= %.0f%%)"
                         % (name, 100 * ar, 100 * min_area_ratio))
    crit = [r for r in rows if r["critical"]]
    return {"status": "PASS" if not fails else "FAIL",
            "minAreaRatioThreshold": min_area_ratio,
            "criticalMaterials": list(critical),
            "worstCriticalAreaRatio": min([r["areaRatio"] for r in crit], default=None),
            "rows": rows, "failures": fails,
            "nodesMaster": a["nodes"], "nodesCandidate": b["nodes"],
            "nodeNamesLost": [n for n in a["nodeNames"] if n not in set(b["nodeNames"])],
            "materialNamesLost": [n for n in a["materialNames"]
                                  if n not in set(b["materialNames"])]}


# --------------------------------------------------------------------------
# (1) appearance
# --------------------------------------------------------------------------

def build_cameras(master_metrics, orbit_az=None, closeups=True):
    """Camera strings derived ONCE from the master's WORLD bounds."""
    import re
    lo, hi = [np.array(v, dtype=float) for v in master_metrics["boundsWorld"]]
    c = (lo + hi) / 2.0
    diag = float(np.linalg.norm(hi - lo))
    r = diag * 1.05
    cams = []
    tgt = "%.4fm %.4fm %.4fm" % (c[0], c[1], c[2])
    for az in (orbit_az or ORBIT_AZ):
        cams.append({"view": "az%03d" % az, "zone": "full",
                     "orbit": "%ddeg %.1fdeg %.4fm" % (az, ORBIT_EL_DEG, r),
                     "target": tgt, "fov": "30deg"})
    if not closeups:
        return cams
    # close-up targets from the master's own node geometry, so this generalises
    js, bin_ = glb_read(master_metrics["_decodedPath"])
    xf = node_world_translations(js)
    from mobile_metrics import read_accessor
    for label, pat, mult in CLOSEUPS:
        rx = re.compile(pat, re.I)
        lo2 = np.array([np.inf] * 3); hi2 = np.array([-np.inf] * 3)
        for ni, n in enumerate(js.get("nodes", [])):
            if "mesh" not in n or not rx.search(n.get("name") or ""):
                continue
            M = xf.get(ni, np.eye(4))
            for p in js["meshes"][n["mesh"]]["primitives"]:
                pos = read_accessor(js, bin_, p["attributes"]["POSITION"]).astype(float)
                w = pos @ M[:3, :3].T + M[:3, 3]
                lo2 = np.minimum(lo2, w.min(axis=0)); hi2 = np.maximum(hi2, w.max(axis=0))
            break                       # FIRST match only -- see CLOSEUPS above
        if not np.isfinite(lo2).all():
            continue
        cc = (lo2 + hi2) / 2.0
        # A close-up must actually BE closer. Some components are single meshes
        # spanning most of the car (Glass_Side_L is both side windows as one
        # mesh, diag 2.5 m), so an unclamped node-diagonal radius reproduces the
        # full-car view under a close-up label -- which is worse than no close-up
        # because it looks like coverage. Cap at 55% of the car's own diagonal.
        # ...and it must not be so close that the camera sits INSIDE the body.
        # The lamp zone at an unclamped 1.07 m put the camera inside the nose and
        # rendered the cabin floor -- again, caught only by looking. Band the
        # radius to 35-55% of the car's diagonal: always outside, always about
        # twice as close as the full-car view.
        rr = float(np.clip(float(np.linalg.norm(hi2 - lo2)) * mult,
                           0.35 * diag, 0.55 * diag))
        # aim from the side the component faces (sign of its own z offset)
        az = 250 if cc[2] < 0 else 290
        cams.append({"view": label, "zone": "closeup",
                     "orbit": "%ddeg 85deg %.4fm" % (az, rr),
                     "target": "%.4fm %.4fm %.4fm" % (cc[0], cc[1], cc[2]),
                     "fov": "30deg"})
    return cams


def appearance(master, candidate, out_dir, cams=None, min_psnr=35.0,
               keep_pngs=True, verbose=True, master_cache=None):
    """master_cache: a directory to hold the MASTER's renders across calls.

    The master here is an uncompressed 28.7 MB GLB and takes ~2 minutes to load
    under SwiftShader; re-rendering it once per ladder rung is the dominant cost
    of a whole gate run and produces byte-identical PNGs every time. Cached by
    (master sha-less mtime+size, camera signature) so a changed master or a
    changed camera set can never silently reuse stale reference frames.
    """
    from PIL import Image
    from playwright.sync_api import sync_playwright

    mv = VC.find_model_viewer(); exe = VC.find_chromium()
    if not mv or not exe:
        return {"status": "NOT_TESTED",
                "reason": "model-viewer bundle or Chromium unavailable"}
    os.makedirs(out_dir, exist_ok=True)
    if cams is None:
        wk = os.path.join(out_dir, "_dec")
        mm = measure(decode(master, wk))
        mm["_decodedPath"] = decode(master, wk)
        cams = build_cameras(mm)

    cache_dir = None
    if master_cache:
        st = os.stat(master)
        sig = "%s_%d_%d_%s" % (os.path.basename(master), st.st_size, int(st.st_mtime),
                               abs(hash(json.dumps(cams, sort_keys=True))) % (10 ** 8))
        cache_dir = os.path.join(master_cache, sig)
        os.makedirs(cache_dir, exist_ok=True)
    have_master = bool(cache_dir) and all(
        os.path.exists(os.path.join(cache_dir, "master_%s.png" % c["view"])) for c in cams)

    web = os.path.join(out_dir, "web"); os.makedirs(web, exist_ok=True)
    if not have_master:
        shutil.copy(master, os.path.join(web, "a.glb"))
    shutil.copy(candidate, os.path.join(web, "b.glb"))
    shutil.copy(mv, os.path.join(web, "model-viewer.min.js"))
    VC.vendor_decoders(web)
    with open(os.path.join(web, "index.html"), "w") as fh:
        fh.write(PAGE)

    httpd, port = _serve(web)
    shots = {}
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True, executable_path=exe, args=[
                "--use-gl=angle", "--use-angle=swiftshader",
                "--enable-unsafe-swiftshader", "--no-sandbox", "--disable-dev-shm-usage"])
            p = b.new_page(viewport={"width": 820, "height": 620})
            p.goto("http://127.0.0.1:%d/index.html" % port)
            p.wait_for_function("()=>window.__ready===true", timeout=60000)
            todo = [("cand", "/b.glb")] if have_master else \
                   [("master", "/a.glb"), ("cand", "/b.glb")]
            for tag, src in todo:
                p.evaluate("s=>window.__setSrc(s)", src)
                p.wait_for_function("()=>window.__loaded===true||window.__failed!==null",
                                    timeout=600000)
                if p.evaluate("window.__failed"):
                    raise RuntimeError("%s failed to load: %s"
                                       % (tag, p.evaluate("window.__failed")))
                p.wait_for_timeout(1200)
                for cam in cams:
                    p.evaluate("a=>window.__cam(a[0],a[1],a[2])",
                               [cam["orbit"], cam["target"], cam["fov"]])
                    p.wait_for_timeout(600)
                    fp = os.path.join(out_dir, "%s_%s.png" % (tag, cam["view"]))
                    p.locator("#mv").screenshot(path=fp)
                    if tag == "master" and cache_dir:
                        shutil.copy(fp, os.path.join(cache_dir, "master_%s.png" % cam["view"]))
                    shots[(tag, cam["view"])] = fp
            b.close()
    finally:
        httpd.shutdown()
    if have_master:
        for cam in cams:
            shots[("master", cam["view"])] = os.path.join(
                cache_dir, "master_%s.png" % cam["view"])

    bg = np.array([0x20, 0x20, 0x24])
    rows = []
    for cam in cams:
        A = np.asarray(Image.open(shots[("master", cam["view"])]).convert("RGB")).astype(np.float64)
        B = np.asarray(Image.open(shots[("cand", cam["view"])]).convert("RGB")).astype(np.float64)
        d = np.abs(A - B)
        mse = float((d ** 2).mean())
        psnr = 10 * np.log10(255.0 ** 2 / mse) if mse > 0 else 99.0
        ma = np.abs(A - bg).sum(axis=2) > 24
        mb = np.abs(B - bg).sum(axis=2) > 24
        union = np.logical_or(ma, mb).sum()
        iou = float(np.logical_and(ma, mb).sum()) / float(union) if union else 1.0
        rows.append({"view": cam["view"], "zone": cam["zone"],
                     "psnrDb": round(psnr, 2), "iou": round(iou, 5),
                     "meanAbs": round(float(d.mean()), 3),
                     "p99Abs": round(float(np.percentile(d, 99)), 1),
                     "coverageMaster": int(ma.sum()), "coverageCand": int(mb.sum())})
    if not keep_pngs:
        for k, f in shots.items():
            if cache_dir and k[0] == "master":
                continue            # never delete the shared master cache
            if os.path.exists(f):
                os.remove(f)
    ps = [r["psnrDb"] for r in rows]
    io = [r["iou"] for r in rows]
    full = [r for r in rows if r["zone"] == "full"]
    cu = [r for r in rows if r["zone"] == "closeup"]
    res = {"status": "PASS" if min(ps) >= min_psnr else "FAIL",
           "minPsnrThreshold": min_psnr,
           "psnrMin": min(ps), "psnrMean": round(float(np.mean(ps)), 2),
           "psnrMinFullCar": min([r["psnrDb"] for r in full], default=None),
           "psnrMinCloseup": min([r["psnrDb"] for r in cu], default=None),
           "iouMin": min(io), "iouMean": round(float(np.mean(io)), 5),
           "views": rows, "cameras": cams, "outDir": os.path.abspath(out_dir),
           "renderer": "chromium headless + SwiftShader (SOFTWARE, desktop) -- "
                       "identical engine and cameras both sides; NOT a device result"}
    if verbose:
        print(fmt_appearance(res))
    return res


def fmt_appearance(r):
    if r.get("status") == "NOT_TESTED":
        return "APPEARANCE: NOT_TESTED -- %s" % r.get("reason")
    L = ["APPEARANCE DELTA  master vs candidate, identical engine + cameras",
         "  %-12s %-8s %9s %9s %9s %9s" % ("view", "zone", "PSNR dB", "IoU",
                                           "meanAbs", "p99Abs")]
    for v in r["views"]:
        L.append("  %-12s %-8s %9.2f %9.5f %9.3f %9.1f"
                 % (v["view"], v["zone"], v["psnrDb"], v["iou"],
                    v["meanAbs"], v["p99Abs"]))
    L.append("  PSNR  min %.2f dB (full-car %.2f, close-up %.2f)  mean %.2f dB   "
             "threshold %.1f -> %s"
             % (r["psnrMin"], r["psnrMinFullCar"] or -1, r["psnrMinCloseup"] or -1,
                r["psnrMean"], r["minPsnrThreshold"], r["status"]))
    L.append("  IoU   min %.5f mean %.5f   <- SANITY CHANNEL ONLY. 96%%-decimation "
             "scored 0.991; IoU never decides." % (r["iouMin"], r["iouMean"]))
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("master"); ap.add_argument("candidate")
    ap.add_argument("--out-dir", default="/tmp/fidelity")
    ap.add_argument("--min-psnr", type=float, default=35.0)
    ap.add_argument("--min-area-ratio", type=float, default=0.85)
    ap.add_argument("--no-closeups", action="store_true")
    ap.add_argument("--json")
    a = ap.parse_args()
    geo = geometry_retention(a.master, a.candidate,
                             workdir=os.path.join(a.out_dir, "_geom"),
                             min_area_ratio=a.min_area_ratio)
    print("GEOMETRY RETENTION  %s" % geo["status"])
    for r in geo.get("rows", []):
        print("  %-20s %-9s area %6.1f%%  tris %6.1f%%"
              % (r["material"], "CRITICAL" if r["critical"] else "",
                 100 * r["areaRatio"], 100 * r["triRatio"]))
    for f in geo.get("failures", []):
        print("  FAIL: %s" % f)
    print()
    wk = os.path.join(a.out_dir, "_dec")
    mm = measure(decode(a.master, wk)); mm["_decodedPath"] = decode(a.master, wk)
    cams = build_cameras(mm, closeups=not a.no_closeups)
    app = appearance(a.master, a.candidate, a.out_dir, cams=cams, min_psnr=a.min_psnr)
    out = {"geometryRetention": geo, "appearance": app}
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(out, fh, indent=2)
    return 0 if (geo["status"] in ("PASS", "NOT_TESTED")
                 and app.get("status") == "PASS") else 1


if __name__ == "__main__":
    sys.exit(main())
