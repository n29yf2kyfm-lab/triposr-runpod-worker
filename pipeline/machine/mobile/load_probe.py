#!/usr/bin/env python3
"""
load_probe.py -- MEASURE how long a GLB takes to become a picture, in a real
browser, over an emulated mobile link. Nothing here is estimated.

    python3 pipeline/machine/mobile/load_probe.py mobile.glb --json load.json

WHY THIS EXISTS
---------------
`viewer_check.py` proves an asset LOADS. Its own docstring is explicit that it
"says NOTHING about device frame rate or load time". `mobile_export.py` gates on
bytes and silhouette. Nothing in the repo measured TIME, so every load-time
claim on this programme so far has been arithmetic on a file size. Arithmetic
misses the half that decimation and codec choice actually move: PARSE and
DECODE. A 3.65 MB Draco file is 7.9x smaller than its 28.70 MB source and is NOT
7.9x faster to first frame, because the Draco decode is CPU work that the
uncompressed file does not do at all. That trade is the whole point of the
measurement.

WHAT IS MEASURED (three separable numbers, deliberately)
--------------------------------------------------------
  transferMs   time to pull the bytes, from the browser's own Resource Timing
               entry for the .glb request. Under emulation this is the link.
  decodeMs     load-event time minus transfer time: parse + decompress + build
               BufferGeometry + upload. This is the CPU term.
  totalMs      src assignment -> model-viewer 'load' event. What a user waits.

Each is measured `--repeats` times and reported as median plus full spread,
because a single timing on a shared container is not a measurement.

NETWORK EMULATION
-----------------
Chrome DevTools Protocol `Network.emulateNetworkConditions`, driven through
Playwright's CDP session. Tiers are named and their parameters are stated in the
output -- they are a CHOSEN SCENARIO, not a claim about any real network:

    wifi        50 Mbit/s   20 ms RTT   (near-best case, upper bound only)
    good4G       12 Mbit/s   60 ms RTT
    typical4G     8 Mbit/s  100 ms RTT   <- the tier the budget is set on
    busy4G        3 Mbit/s  200 ms RTT
    slow3G      0.4 Mbit/s  400 ms RTT   (Chrome's own Slow 3G numbers)

HONEST LIMITS -- read before quoting any number from this file
---------------------------------------------------------------
  * The CPU is this container's DESKTOP x86 core, not a phone SoC. A mid-range
    ARM phone is slower at the decode term. So `decodeMs` here is a LOWER BOUND
    on a device and must never be presented as a device figure.
  * Rendering is SwiftShader (software). GPU upload cost and frame rate are NOT
    measured and are reported as NOT TESTED. There is no phone attached to this
    container and no honest way to synthesise one.
  * `Network.emulateNetworkConditions` shapes throughput and latency. It does
    not model packet loss, radio wake-up, TLS handshakes to a real CDN, or
    HTTP/2 multiplexing against other page assets.
  * jsHeapDeltaBytes is `performance.memory` around the load. It captures the
    typed arrays three.js retains, which for a TEXTURE-FREE car is the bulk of
    client memory -- but it is NOT VRAM and it is NOT process RSS. Read it
    alongside `gpuBufferBytes` from mobile_metrics, which is exact.

So this module answers "does the DOWNLOAD-plus-DECODE budget hold" with
measurements, and refuses to answer "does it hold 30 fps on a phone" at all.
"""

import argparse
import http.server
import json
import os
import shutil
import socketserver
import statistics
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # pipeline/machine
import viewer_check as VC                          # noqa: E402  (decoder vendoring, chromium)

TIERS = {
    #  name      down Mbit/s  up Mbit/s  RTT ms
    "wifi":      (50.0, 20.0, 20),
    "good4G":    (12.0, 6.0, 60),
    "typical4G": (8.0, 3.0, 100),
    "busy4G":    (3.0, 1.0, 200),
    "slow3G":    (0.4, 0.4, 400),
}
DEFAULT_TIERS = ["wifi", "typical4G", "busy4G"]

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<link rel="icon" href="data:,">
<style>html,body{margin:0;background:#202024}
model-viewer{width:900px;height:600px;background:#202024}</style></head><body>
<model-viewer id="mv" camera-controls disable-pan interaction-prompt="none"
  shadow-intensity="0" exposure="1" environment-image="neutral"></model-viewer>
<script>
window.__err=[]; window.__console=[];
window.addEventListener('error',e=>window.__err.push(String(e.message)));
window.addEventListener('unhandledrejection',e=>window.__err.push('unhandledrejection: '+e.reason));
const mv=document.getElementById('mv');
window.__t0=null; window.__tload=null; window.__failed=null;
mv.addEventListener('load',()=>{window.__tload=performance.now();});
mv.addEventListener('error',e=>{window.__failed=JSON.stringify(e.detail||'error');});
</script>
<script type="module">
import '/model-viewer.min.js';
await customElements.whenDefined('model-viewer');
const MV=customElements.get('model-viewer');
MV.meshoptDecoderLocation='/meshopt_decoder.js';
MV.dracoDecoderLocation='/draco/';
window.__load=(src)=>{
  const mv=document.getElementById('mv');
  window.__tload=null; window.__failed=null;
  performance.clearResourceTimings();
  window.__t0=performance.now();
  mv.src=src;
};
window.__timing=(needle)=>{
  const e=performance.getEntriesByType('resource').filter(r=>r.name.indexOf(needle)>=0);
  if(!e.length) return null;
  const r=e[e.length-1];
  return {startMs:r.startTime, endMs:r.responseEnd, durMs:r.duration,
          transferSize:r.transferSize, encodedBodySize:r.encodedBodySize,
          decodedBodySize:r.decodedBodySize};
};
window.__ready=true;
</script></body></html>"""


def _serve(directory):
    handler = lambda *a, **k: VC.Quiet(*a, directory=directory, **k)
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, httpd.server_address[1]


def probe(glb, out_dir="/tmp/load_probe", tiers=None, repeats=3,
          timeout_ms=300000, verbose=True):
    from playwright.sync_api import sync_playwright

    tiers = tiers or DEFAULT_TIERS
    for t in tiers:
        if t not in TIERS:
            raise KeyError("unknown tier %r; have %s" % (t, sorted(TIERS)))

    mv = VC.find_model_viewer()
    exe = VC.find_chromium()
    if not mv:
        return {"status": "NOT_TESTED", "reason": "model-viewer bundle unavailable"}
    if not exe:
        return {"status": "NOT_TESTED", "reason": "no Chromium under PLAYWRIGHT_BROWSERS_PATH"}

    os.makedirs(out_dir, exist_ok=True)
    web = os.path.join(out_dir, "web")
    os.makedirs(web, exist_ok=True)
    name = os.path.basename(glb)
    shutil.copy(glb, os.path.join(web, name))
    shutil.copy(mv, os.path.join(web, "model-viewer.min.js"))
    decoders = VC.vendor_decoders(web)
    with open(os.path.join(web, "index.html"), "w") as fh:
        fh.write(PAGE)

    httpd, port = _serve(web)
    res = {
        "file": os.path.abspath(glb), "sizeBytes": os.path.getsize(glb),
        "chromium": exe, "decoders": decoders, "repeats": repeats,
        "renderer": "chromium headless + SwiftShader (SOFTWARE) on this container's "
                    "DESKTOP x86 CPU -- decode times are a LOWER BOUND for a phone; "
                    "frame rate and VRAM are NOT TESTED",
        "tiers": {},
    }
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True, executable_path=exe, args=[
                "--use-gl=angle", "--use-angle=swiftshader",
                "--enable-unsafe-swiftshader", "--no-sandbox",
                "--disable-dev-shm-usage", "--enable-precise-memory-info"])
            page = b.new_page(viewport={"width": 960, "height": 640})
            console = []
            page.on("console", lambda m: console.append({"type": m.type, "text": m.text}))
            page.on("pageerror", lambda e: console.append({"type": "pageerror", "text": str(e)}))
            cdp = page.context.new_cdp_session(page)
            cdp.send("Network.enable")
            # A warm HTTP cache would measure nothing on repeat 2 and 3.
            cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})

            page.goto("http://127.0.0.1:%d/index.html" % port)
            page.wait_for_function("()=>window.__ready===true", timeout=60000)

            for tier in tiers:
                down, up, rtt = TIERS[tier]
                cdp.send("Network.emulateNetworkConditions", {
                    "offline": False, "latency": rtt,
                    "downloadThroughput": down * 1e6 / 8.0,
                    "uploadThroughput": up * 1e6 / 8.0})
                runs = []
                for k in range(repeats):
                    # unique query defeats every layer of caching, belt and braces
                    src = "/%s?t=%s_%d" % (name, tier, k)
                    heap0 = page.evaluate(
                        "()=>performance.memory?performance.memory.usedJSHeapSize:null")
                    page.evaluate("s=>window.__load(s)", src)
                    page.wait_for_function(
                        "()=>window.__tload!==null||window.__failed!==null",
                        timeout=timeout_ms)
                    r = page.evaluate("""()=>({t0:window.__t0,tload:window.__tload,
                        failed:window.__failed,
                        heap:performance.memory?performance.memory.usedJSHeapSize:null})""")
                    if r["failed"]:
                        raise RuntimeError("model-viewer load failed: %s" % r["failed"])
                    tm = page.evaluate("n=>window.__timing(n)", name)
                    total = r["tload"] - r["t0"]
                    transfer = (tm["endMs"] - tm["startMs"]) if tm else None
                    runs.append({
                        "totalMs": round(total, 1),
                        "transferMs": round(transfer, 1) if transfer is not None else None,
                        "decodeMs": round(total - transfer, 1) if transfer is not None else None,
                        "encodedBodySize": tm.get("encodedBodySize") if tm else None,
                        "jsHeapDeltaBytes": (r["heap"] - heap0)
                        if (r["heap"] is not None and heap0 is not None) else None,
                    })
                    # drop the model so the next repeat is a cold build
                    page.evaluate("()=>{document.getElementById('mv').src='';}")
                    page.wait_for_timeout(250)

                def med(k):
                    vals = [x[k] for x in runs if x[k] is not None]
                    return round(statistics.median(vals), 1) if vals else None

                res["tiers"][tier] = {
                    "downMbit": down, "upMbit": up, "rttMs": rtt,
                    "runs": runs,
                    "totalMsMedian": med("totalMs"),
                    "transferMsMedian": med("transferMs"),
                    "decodeMsMedian": med("decodeMs"),
                    "totalMsMin": min(x["totalMs"] for x in runs),
                    "totalMsMax": max(x["totalMs"] for x in runs),
                    "jsHeapDeltaBytesMedian": med("jsHeapDeltaBytes"),
                }
            # restore an unthrottled link before the screenshot
            cdp.send("Network.emulateNetworkConditions", {
                "offline": False, "latency": 0,
                "downloadThroughput": -1, "uploadThroughput": -1})
            res["console"] = console
            b.close()
    finally:
        httpd.shutdown()

    bad = [c for c in res.get("console", [])
           if c["type"] in ("error", "warning", "pageerror")
           and not any(p in c["text"] for p in VC.BENIGN_CONSOLE)]
    res["consoleBad"] = bad
    res["status"] = "MEASURED"
    if verbose:
        print(fmt(res))
    return res


def fmt(res):
    if res.get("status") != "MEASURED":
        return "LOAD PROBE: %s -- %s" % (res.get("status"), res.get("reason"))
    L = ["=" * 78,
         "LOAD PROBE  %s  (%.3f MB, median of %d cold loads)"
         % (os.path.basename(res["file"]), res["sizeBytes"] / 1e6, res["repeats"]),
         "=" * 78,
         res["renderer"],
         "",
         "  %-11s %7s %6s  %9s %9s %9s   %11s"
         % ("tier", "Mbit/s", "RTT", "transfer", "decode", "TOTAL", "spread")]
    for t, d in res["tiers"].items():
        L.append("  %-11s %7.1f %5dms  %8.0fms %8.0fms %8.0fms   %5.0f-%.0fms"
                 % (t, d["downMbit"], d["rttMs"], d["transferMsMedian"] or -1,
                    d["decodeMsMedian"] or -1, d["totalMsMedian"],
                    d["totalMsMin"], d["totalMsMax"]))
    hp = [d["jsHeapDeltaBytesMedian"] for d in res["tiers"].values()
          if d["jsHeapDeltaBytesMedian"]]
    if hp:
        L.append("")
        L.append("  JS heap delta on load: %.2f MB (median) -- CPU-side typed arrays, "
                 "NOT VRAM" % (statistics.median(hp) / 1e6))
    L.append("")
    L.append("  NOT TESTED: on-device frame rate, GPU upload cost, VRAM, real-network "
             "loss/handshake")
    if res.get("consoleBad"):
        L.append("  CONSOLE ERRORS: %d" % len(res["consoleBad"]))
        for c in res["consoleBad"][:5]:
            L.append("    [%s] %s" % (c["type"], c["text"][:120]))
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("glb", nargs="+")
    ap.add_argument("--tiers", default=",".join(DEFAULT_TIERS),
                    help="comma list from %s" % ",".join(TIERS))
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--out-dir", default="/tmp/load_probe")
    ap.add_argument("--json")
    a = ap.parse_args()
    out = []
    for i, g in enumerate(a.glb):
        out.append(probe(g, out_dir=os.path.join(a.out_dir, "p%d" % i),
                         tiers=a.tiers.split(","), repeats=a.repeats))
        print()
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(out if len(out) > 1 else out[0], fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
