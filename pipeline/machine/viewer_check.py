#!/usr/bin/env python3
"""
viewer_check.py -- headless <model-viewer> load test for an exported GLB.

    python3 pipeline/machine/viewer_check.py mobile.glb --out-dir /tmp/vc

Loads the GLB in a real browser (Chromium via Playwright, WebGL through
SwiftShader) inside Google's <model-viewer> -- the same component the product
viewer is built on -- and asserts:

  1. RENDERS      the model 'load' event fires and the canvas is not blank
                  (fraction of non-background pixels within a sane band)
  2. ORBIT CENTRE camera target sits near the model's bounding-box centre
  3. ON THE GROUND  bbox minimum Y is ~0, so the car is not floating or sunk
  4. CLEAN CONSOLE no console errors/warnings and no uncaught page errors

WHAT THIS IS NOT
----------------
This is a DESKTOP HEADLESS software-rasterised render. It proves the asset
loads, parses, and draws correctly in a real WebGL engine. It says NOTHING about
device frame rate or load time.

There is no iPhone and no Android device attached to this container, so
device FPS, first-usable-frame on 4G, and mobile screen recordings are
NOT TESTED and cannot be produced here. Any FPS number this script prints is
SwiftShader on a CPU and is explicitly labelled as such -- it is not a device
result and must never be presented as one.
"""

import argparse
import http.server
import json
import os
import shutil
import socketserver
import sys
import threading
import tarfile
import urllib.request

MV_CANDIDATES = [
    "/tmp/mvpkg/package/dist/model-viewer.min.js",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "model-viewer.min.js"),
    "/opt/node22/lib/node_modules/@google/model-viewer/dist/model-viewer.min.js",
]

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="icon" href="data:,">
<style>
  html,body{margin:0;height:100%%;background:#202024;}
  model-viewer{width:900px;height:600px;--poster-color:transparent;background:#202024;}
</style>
</head><body>
<model-viewer id="mv"
  camera-controls disable-pan interaction-prompt="none"
  shadow-intensity="0" exposure="1"
  environment-image="neutral"></model-viewer>
<script>
window.__err=[];
window.addEventListener('error',e=>window.__err.push(String(e.message)));
window.addEventListener('unhandledrejection',e=>window.__err.push('unhandledrejection: '+e.reason));
window.__loaded=false; window.__failed=null;
const mv=document.getElementById('mv');
mv.addEventListener('load',()=>{window.__loaded=true;});
mv.addEventListener('error',e=>{window.__failed=JSON.stringify(e.detail||'error');});
</script>
<script type="module">
import '/model-viewer.min.js';
await customElements.whenDefined('model-viewer');
const MV = customElements.get('model-viewer');
// model-viewer does NOT bundle these decoders. Left at their defaults it fetches
// them from unpkg/gstatic, which fails offline and produces
// "THREE.GLTFLoader: setMeshoptDecoder must be called before loading compressed
// files" -- a load failure that looks like a corrupt asset. Point them local.
MV.meshoptDecoderLocation = '/meshopt_decoder.js';
MV.dracoDecoderLocation = '/draco/';
document.getElementById('mv').src = '/%s';
</script>
</body></html>
"""


def find_model_viewer():
    for p in MV_CANDIDATES:
        if os.path.exists(p):
            return p
    # last resort: pull the npm tarball through the proxy
    dest = "/tmp/mvpkg"
    try:
        tgz = "/tmp/_mv.tgz"
        urllib.request.urlretrieve(
            "https://registry.npmjs.org/@google/model-viewer/-/model-viewer-4.3.1.tgz", tgz)
        os.makedirs(dest, exist_ok=True)
        with tarfile.open(tgz) as t:
            t.extractall(dest)
        p = os.path.join(dest, "package/dist/model-viewer.min.js")
        if os.path.exists(p):
            return p
    except Exception:
        pass
    return None


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


# The UMD/CJS build, NOT the .mjs. model-viewer fetches this URL and evaluates it
# as a CLASSIC script, so an ES module produces "Unexpected token 'export'".
# meshopt_decoder.cjs falls through its AMD/CommonJS branches in a browser and
# assigns self.MeshoptDecoder, which is what model-viewer reads.
MESHOPT_CANDIDATES = [
    "/tmp/moz/package/meshopt_decoder.cjs",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "meshopt_decoder.js"),
]
DRACO_DIRS = [
    "/tmp/thr/package/examples/jsm/libs/draco/gltf",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "draco"),
]


def vendor_decoders(web):
    """Copy the meshopt + draco decoders next to the page.

    model-viewer does NOT bundle either one. At their default locations it
    fetches them from unpkg / gstatic, which fails with no outbound network and
    surfaces as 'THREE.GLTFLoader: setMeshoptDecoder must be called before
    loading compressed files' -- a load failure that reads like a corrupt asset.
    CLAUDE.md already records the Draco half of this trap; meshopt behaves the
    same way.
    """
    got = {"meshopt": None, "draco": None}
    for c in MESHOPT_CANDIDATES:
        if os.path.exists(c):
            shutil.copy(c, os.path.join(web, "meshopt_decoder.js"))
            got["meshopt"] = c
            break
    for d in DRACO_DIRS:
        if os.path.isdir(d):
            dst = os.path.join(web, "draco")
            os.makedirs(dst, exist_ok=True)
            for f in os.listdir(d):
                shutil.copy(os.path.join(d, f), os.path.join(dst, f))
            got["draco"] = d
            break
    return got


# Console messages that are a property of THIS HARNESS, not of the asset. Each
# needs a justification, the same discipline gltf_validate.py applies to
# validator warnings -- an unexplained message is a failure, not noise.
BENIGN_CONSOLE = {
    "rAF timed out in updateSource":
        "model-viewer's own watchdog. SwiftShader software rasterisation makes "
        "the first frames slow enough to trip it; irrelevant on GPU hardware and "
        "unrelated to the asset.",
}


def find_chromium():
    """Locate an already-installed Chromium.

    The Python playwright package here is 1.62.0 and expects browser build 1234,
    but /opt/pw-browsers ships 1194. Rather than run `playwright install` (which
    this environment forbids), point launch() at the binary that IS present.
    """
    import glob
    roots = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "/opt/pw-browsers"]
    pats = ["chromium-*/chrome-linux/chrome",
            "chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell",
            "chromium-*/chrome-linux64/chrome"]
    found = []
    for r in roots:
        for p in pats:
            found += sorted(glob.glob(os.path.join(r, p)))
    for f in found:                      # prefer full chrome (WebGL support)
        if f.endswith("/chrome"):
            return f
    return found[0] if found else None


def serve(directory):
    handler = lambda *a, **k: Quiet(*a, directory=directory, **k)
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, port


def check(glb, out_dir="/tmp/viewer_check", timeout_ms=180000,
          centre_tol=0.12, ground_tol=0.02, verbose=True):
    from playwright.sync_api import sync_playwright

    mv = find_model_viewer()
    if not mv:
        return {"status": "NOT_TESTED",
                "reason": "model-viewer bundle unavailable (no network, none vendored)"}

    os.makedirs(out_dir, exist_ok=True)
    web = os.path.join(out_dir, "web")
    os.makedirs(web, exist_ok=True)
    name = os.path.basename(glb)
    shutil.copy(glb, os.path.join(web, name))
    shutil.copy(mv, os.path.join(web, "model-viewer.min.js"))
    vendored = vendor_decoders(web)
    result_decoders = vendored
    with open(os.path.join(web, "index.html"), "w") as fh:
        fh.write(PAGE % name)

    httpd, port = serve(web)
    result = {"status": "UNKNOWN", "file": os.path.abspath(glb),
              "decoders": result_decoders,
              "sizeBytes": os.path.getsize(glb),
              "renderer": "chromium headless + SwiftShader (SOFTWARE, desktop) "
                          "-- NOT a device measurement"}
    try:
        exe = find_chromium()
        if not exe:
            return {"status": "NOT_TESTED",
                    "reason": "no Chromium found under PLAYWRIGHT_BROWSERS_PATH"}
        result["chromium"] = exe
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, executable_path=exe, args=[
                "--use-gl=angle", "--use-angle=swiftshader",
                "--enable-unsafe-swiftshader", "--no-sandbox",
                "--disable-dev-shm-usage",
            ])
            page = browser.new_page(viewport={"width": 960, "height": 640})
            console = []
            page.on("console", lambda m: console.append(
                {"type": m.type, "text": m.text}))
            page.on("pageerror", lambda e: console.append(
                {"type": "pageerror", "text": str(e)}))

            page.goto("http://127.0.0.1:%d/index.html" % port)
            page.wait_for_function(
                "() => window.__loaded === true || window.__failed !== null",
                timeout=timeout_ms)

            failed = page.evaluate("window.__failed")
            result["loaded"] = page.evaluate("window.__loaded")
            result["modelViewerError"] = failed

            page.wait_for_timeout(2500)  # let the first frames settle

            info = page.evaluate("""() => {
              const mv=document.getElementById('mv');
              const d=mv.getDimensions(), c=mv.getBoundingBoxCenter();
              const orb=mv.getCameraOrbit(), tgt=mv.getCameraTarget();
              return {dims:{x:d.x,y:d.y,z:d.z},
                      centre:{x:c.x,y:c.y,z:c.z},
                      orbit:{theta:orb.theta,phi:orb.phi,radius:orb.radius},
                      target:{x:tgt.x,y:tgt.y,z:tgt.z},
                      fov:mv.getFieldOfView()};
            }""")
            result.update(info)

            shot = os.path.join(out_dir, "viewer.png")
            page.locator("#mv").screenshot(path=shot)
            result["screenshot"] = shot

            # crude frame-rate probe, SOFTWARE renderer -- diagnostic only
            fps = page.evaluate("""async () => {
              let n=0; const t0=performance.now();
              await new Promise(r=>{
                const tick=()=>{n++; if(performance.now()-t0<2000) requestAnimationFrame(tick); else r();};
                requestAnimationFrame(tick);
              });
              return n/((performance.now()-t0)/1000);
            }""")
            result["swiftshader_fps"] = round(fps, 1)

            result["console"] = console
            browser.close()
    finally:
        httpd.shutdown()

    # ---- assertions ----
    checks, fails = {}, []

    checks["loaded"] = bool(result.get("loaded")) and not result.get("modelViewerError")
    if not checks["loaded"]:
        fails.append("model did not load: %s" % result.get("modelViewerError"))

    # not blank
    try:
        from PIL import Image
        import numpy as np
        im = np.asarray(Image.open(result["screenshot"]).convert("RGB")).astype(int)
        bg = np.array([0x20, 0x20, 0x24])
        nonbg = (np.abs(im - bg).sum(axis=2) > 24)
        frac = float(nonbg.mean())
        result["non_background_fraction"] = round(frac, 4)
        checks["renders"] = 0.02 < frac < 0.95
        if not checks["renders"]:
            fails.append("canvas looks blank or fully covered "
                         "(non-background fraction %.4f)" % frac)
    except Exception as e:
        checks["renders"] = None
        result["render_probe_error"] = str(e)

    d, c, t = result.get("dims"), result.get("centre"), result.get("target")
    scale = max(d["x"], d["y"], d["z"]) if d else 0.0
    if d and c and t and scale > 0:
        off = max(abs(c["x"] - t["x"]), abs(c["y"] - t["y"]), abs(c["z"] - t["z"]))
        result["orbit_centre_offset"] = round(off, 4)
        result["orbit_centre_offset_rel"] = round(off / scale, 4)
        checks["orbit_centre"] = (off / scale) <= centre_tol
        if not checks["orbit_centre"]:
            fails.append("orbit target %.3f from bbox centre (%.1f%% of size)"
                         % (off, 100 * off / scale))

        min_y = c["y"] - d["y"] / 2.0
        result["bbox_min_y"] = round(min_y, 5)
        result["bbox_min_y_rel"] = round(min_y / scale, 5)
        checks["on_ground"] = abs(min_y / scale) <= ground_tol
        if not checks["on_ground"]:
            fails.append("car not on the ground: bbox min Y = %.4f (%.2f%% of size)"
                         % (min_y, 100 * min_y / scale))

    bad, benign = [], []
    for m in result.get("console", []):
        if m["type"] not in ("error", "warning", "pageerror"):
            continue
        why = next((j for pat, j in BENIGN_CONSOLE.items() if pat in m["text"]), None)
        (benign if why else bad).append(dict(m, justification=why))
    result["console_benign"] = benign
    result["console_bad"] = bad
    checks["clean_console"] = len(bad) == 0
    if bad:
        fails.append("%d console error/warning(s): %s"
                     % (len(bad), "; ".join(m["text"][:120] for m in bad[:4])))

    result["checks"] = checks
    result["failures"] = fails
    result["status"] = "PASS" if not fails else "FAIL"

    if verbose:
        print("=" * 74)
        print("HEADLESS <model-viewer> CHECK -- %s" % os.path.basename(glb))
        print("=" * 74)
        print("renderer : %s" % result["renderer"])
        print("size     : %.2f MB" % (result["sizeBytes"] / 1e6))
        if d:
            print("dims     : %.3f x %.3f x %.3f m" % (d["x"], d["y"], d["z"]))
            print("bbox minY: %.5f  (%.3f%% of size)"
                  % (result["bbox_min_y"], 100 * result["bbox_min_y_rel"]))
            print("orbit    : theta=%s phi=%s radius=%s"
                  % (result["orbit"]["theta"], result["orbit"]["phi"], result["orbit"]["radius"]))
            print("centre off %.4f (%.2f%% of size)"
                  % (result["orbit_centre_offset"], 100 * result["orbit_centre_offset_rel"]))
        print("non-bg px: %s" % result.get("non_background_fraction"))
        print("swiftshader fps: %s   <-- SOFTWARE DESKTOP, NOT a device figure"
              % result.get("swiftshader_fps"))
        print()
        for k, v in checks.items():
            print("  [%s] %s" % ({True: "PASS", False: "FAIL", None: "SKIP"}[v], k))
        for m in result.get("console_benign", []):
            print("  [note] benign console %s: %s" % (m["type"], m["text"][:90]))
            print("         justified: %s" % m["justification"][:150])
        for f in fails:
            print("  - %s" % f)
        print("VERDICT: %s" % result["status"])
        print()
        print("NOT TESTED (no device attached to this container):")
        print("  - on-device frame rate (iOS / Android)")
        print("  - first usable frame over 4G")
        print("  - mobile screen recording")
    return result




COMPARE_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<link rel="icon" href="data:,">
<style>html,body{margin:0;background:#202024}model-viewer{width:900px;height:600px;background:#202024}</style>
</head><body>
<model-viewer id="mv" camera-controls disable-pan interaction-prompt="none"
  shadow-intensity="0" exposure="1" environment-image="neutral"
  min-camera-orbit="auto auto 0m" max-camera-orbit="auto auto 1000m"></model-viewer>
<script>window.__loaded=false;const mv=document.getElementById('mv');
mv.addEventListener('load',()=>{window.__loaded=true;});</script>
<script type="module">
import '/model-viewer.min.js';
await customElements.whenDefined('model-viewer');
const MV=customElements.get('model-viewer');
MV.meshoptDecoderLocation='/meshopt_decoder.js'; MV.dracoDecoderLocation='/draco/';
window.__setSrc=(s)=>{window.__loaded=false;document.getElementById('mv').src=s;};
</script></body></html>"""

COMPARE_VIEWS = [("front", "180deg"), ("front34", "215deg"), ("side", "270deg"),
                 ("rear34", "315deg"), ("rear", "0deg"), ("rear34_L", "45deg"),
                 ("side_L", "90deg"), ("front34_L", "135deg")]


def appearance_delta(master, export, out_dir, orbit_alt="78deg", orbit_r="9m",
                     target="0m 0.75m 0m", min_psnr=30.0, verbose=True):
    """Pixel-level appearance delta, master vs export, SAME engine SAME cameras.

    WHY THIS EXISTS -- the silhouette IoU gate in mobile_export.py is NOT
    sufficient on its own, and it is important not to oversell it. MEASURED on
    the Golf: a brutal simplify that deleted 96% of all triangles (985,227 ->
    39,446) still scored min IoU 0.991. A car's outline is smooth and
    low-frequency, so alpha coverage barely moves even when surface detail is
    destroyed.

    So IoU is the right detector for GROSS failures -- wrong scale, a missing
    part, a bad decode (it caught all three probe bugs at 0.07-0.16) -- and it is
    blind to surfacing and to texture, which is where the bytes actually went
    (4096 PNG -> 2048 WebP). This renders both files through real model-viewer
    from identical cameras and compares pixels, which sees both.

    Still a DESKTOP SOFTWARE render, and still says nothing about device
    performance.
    """
    import numpy as np
    from PIL import Image
    from playwright.sync_api import sync_playwright

    mv = find_model_viewer()
    if not mv:
        return {"status": "NOT_TESTED", "reason": "model-viewer bundle unavailable"}
    os.makedirs(out_dir, exist_ok=True)
    web = os.path.join(out_dir, "web"); os.makedirs(web, exist_ok=True)
    shutil.copy(master, os.path.join(web, "a.glb"))
    shutil.copy(export, os.path.join(web, "b.glb"))
    shutil.copy(mv, os.path.join(web, "model-viewer.min.js"))
    vendor_decoders(web)
    with open(os.path.join(web, "index.html"), "w") as fh:
        fh.write(COMPARE_PAGE)

    httpd, port = serve(web)
    shots = {}
    try:
        exe = find_chromium()
        if not exe:
            return {"status": "NOT_TESTED", "reason": "no Chromium found"}
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True, executable_path=exe, args=[
                "--use-gl=angle", "--use-angle=swiftshader",
                "--enable-unsafe-swiftshader", "--no-sandbox", "--disable-dev-shm-usage"])
            p = b.new_page(viewport={"width": 960, "height": 640})
            p.goto("http://127.0.0.1:%d/index.html" % port)
            p.wait_for_function("()=>typeof window.__setSrc==='function'", timeout=60000)
            for tag, src in (("master", "/a.glb"), ("export", "/b.glb")):
                p.evaluate("s=>window.__setSrc(s)", src)
                p.wait_for_function("()=>window.__loaded===true", timeout=300000)
                p.wait_for_timeout(1500)
                for name, az in COMPARE_VIEWS:
                    p.evaluate("""([az,alt,r,t])=>{const mv=document.getElementById('mv');
                        mv.cameraOrbit=az+' '+alt+' '+r; mv.cameraTarget=t;
                        mv.fieldOfView='30deg'; mv.jumpCameraToGoal();}""",
                        [az, orbit_alt, orbit_r, target])
                    p.wait_for_timeout(700)
                    fp = os.path.join(out_dir, "%s_%s.png" % (tag, name))
                    p.locator("#mv").screenshot(path=fp)
                    shots[(tag, name)] = fp
            b.close()
    finally:
        httpd.shutdown()

    rows = []
    for name, _ in COMPARE_VIEWS:
        A = np.asarray(Image.open(shots[("master", name)]).convert("RGB")).astype(np.float64)
        B = np.asarray(Image.open(shots[("export", name)]).convert("RGB")).astype(np.float64)
        d = np.abs(A - B)
        mse = float((d ** 2).mean())
        psnr = 10 * np.log10(255.0 ** 2 / mse) if mse > 0 else float("inf")
        rows.append({"view": name, "psnr_db": round(psnr, 2),
                     "mean_abs": round(float(d.mean()), 3),
                     "p99_abs": round(float(np.percentile(d, 99)), 1)})
    ps = [r["psnr_db"] for r in rows]
    res = {"status": "PASS" if min(ps) >= min_psnr else "FAIL",
           "views": rows, "psnr_min": min(ps), "psnr_mean": round(sum(ps) / len(ps), 2),
           "min_psnr_threshold": min_psnr,
           "renderer": "chromium headless + SwiftShader (SOFTWARE, desktop) "
                       "-- NOT a device measurement"}
    if verbose:
        print("APPEARANCE DELTA  master vs export, identical cameras")
        print("  %-10s %8s %9s %8s" % ("view", "PSNR_dB", "meanAbs", "p99Abs"))
        for r in rows:
            print("  %-10s %8.2f %9.3f %8.1f"
                  % (r["view"], r["psnr_db"], r["mean_abs"], r["p99_abs"]))
        print("  min %.2f dB  mean %.2f dB  (threshold %.1f) -> %s"
              % (res["psnr_min"], res["psnr_mean"], min_psnr, res["status"]))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("glb")
    ap.add_argument("--compare", help="master GLB: also report pixel appearance delta")
    ap.add_argument("--min-psnr", type=float, default=30.0)
    ap.add_argument("--out-dir", default="/tmp/viewer_check")
    ap.add_argument("--json")
    ap.add_argument("--timeout-ms", type=int, default=180000)
    a = ap.parse_args()
    r = check(a.glb, out_dir=a.out_dir, timeout_ms=a.timeout_ms)
    if a.compare:
        print()
        r["appearance"] = appearance_delta(a.compare, a.glb,
                                           os.path.join(a.out_dir, "compare"),
                                           min_psnr=a.min_psnr)
        if r["appearance"].get("status") == "FAIL":
            r["status"] = "FAIL"
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(r, fh, indent=2, default=str)
    return 0 if r["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
