"""check.py: the phone page reads and answers as the Python model does.

    F1K_HOME=/path/to/f1k python3 pipeline/realcar/ai/web/check.py SITE_DIR [--n 24] [PICTURE ...]

Serves SITE_DIR (made by build.py) on this machine, opens it in Chromium
(check_page.cjs, with Playwright), has it read N of the run's photos and builds
(and any PICTURE given) and check each build against its photo, and checks:

- the picture the page hands the encoder is Python's (vision.load, vision.prep):
  the same size, and every 97th value the same to the last bit of rounding
- its colour histogram is Python's (heads.colour_hist), but for a pixel or two on
  a bin's edge
- its engine's numbers are the int8 encoder's here, but for its arithmetic
  (cosine; the heads are trained on the page's own numbers, web/features.py)
- on the page's own numbers, Python's heads give the page's every answer
  (heads.read, heads.judge): the page's head arithmetic is the Python one's
- the page's example is what the page answers on its example pictures

Exits 1 on any difference.
"""
import argparse
import functools
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
AI = os.path.dirname(HERE)
sys.path.insert(0, AI)
sys.path.insert(0, HERE)

import build  # noqa: E402
import heads as H  # noqa: E402
import vision  # noqa: E402

CDN = {"ort.wasm.min.js": "e66568724f8848e57cc2a56e4bea3a5b86ce3ff81b2da11eac8ed7ab02b27bd4",
       "ort-wasm-simd-threaded.mjs": "745eb7c0ce6f18a6aa521971b2877babc7ffb27eecb58ab3bc6e5ef4692672e8"}
SAMPLE = list(range(0, 2 * 3 * 224 * 224, 97))         # the values of the page's encoder input compared one by one


def serve(root):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=root)
    handler.extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                              ".wasm": "application/wasm", ".txt": "text/plain"}
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def node_env():
    return {**os.environ, "NODE_PATH": subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()}


def pictures(n):
    """N of the run's built vehicles, spread over the list: their photo and their build's picture."""
    sys.path.insert(0, os.path.join(os.path.dirname(AI), "review"))
    import paths
    rows, _ = paths.rows()
    keys = sorted(k for k, r in rows.items() if r.get("status") in ("built", "standin") and paths.photo(k) and paths.picture(k))
    step = max(1, len(keys) // n)
    return [(paths.photo(k), paths.picture(k), rows[k]["status"] == "standin") for k in keys[::step][:n]]


def cos(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


def same_answers(a, b):
    """Two answers alike: the same labels, and p within rounding."""
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(same_answers(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(same_answers(x, y) for x, y in zip(a, b))
    if a is None or b is None:                     # one side with no answer where the other has one
        return a is b
    if isinstance(a, float) or isinstance(b, float):
        return abs(float(a) - float(b)) <= 0.0015
    return a == b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("site")
    ap.add_argument("pictures", nargs="*")
    ap.add_argument("--n", type=int, default=24)
    a = ap.parse_intermixed_args()
    hs, card = H.load_heads(os.path.join(a.site, "heads.json"))
    enc = vision.Encoders([vision.fetch(n) for n in build.encoder_names(card)])
    first = enc.parts[0]
    cdn = os.path.join(vision.home(), "ortweb")
    os.makedirs(cdn, exist_ok=True)
    for f, sha in CDN.items():
        build.fetch_pinned(build.ORT + f, os.path.join(cdn, f), sha)
    work = os.path.join(a.site, "_check")
    os.makedirs(work, exist_ok=True)
    try:
        pairs, reads = [], []
        for i, (ph, bu, st) in enumerate(pictures(a.n)):
            p, b = f"_check/{i}-photo{os.path.splitext(ph)[1]}", f"_check/{i}-build{os.path.splitext(bu)[1]}"
            shutil.copy2(ph, os.path.join(a.site, p))
            shutil.copy2(bu, os.path.join(a.site, b))
            pairs.append([p, b, st])
            reads += [p, b]
        for i, f in enumerate(a.pictures):
            p = f"_check/extra-{i}{os.path.splitext(f)[1]}"
            shutil.copy2(f, os.path.join(a.site, p))
            reads.append(p)
        page = open(os.path.join(a.site, "index.html")).read()
        ex = json.loads(page.split("/*EXAMPLE*/", 1)[1].split("/*END*/", 1)[0])
        if ex:
            pairs.append([ex["photo"], ex["build"], bool(ex.get("standin"))])
        srv = serve(a.site)
        with tempfile.TemporaryDirectory() as tmp:
            lst, out = os.path.join(tmp, "pics.json"), os.path.join(tmp, "out.json")
            json.dump({"read": reads, "check": pairs, "sample": SAMPLE}, open(lst, "w"))
            subprocess.run(["node", os.path.join(HERE, "check_page.cjs"), f"http://127.0.0.1:{srv.server_address[1]}/index.html",
                            lst, out, cdn], check=True, env=node_env(), timeout=1800)
            js = json.load(open(out))
        srv.shutdown()
        bad, cs, hs_diff = [], [], []
        feats = {}
        for p in reads:
            im = vision.load(os.path.join(a.site, p))
            x = np.stack([vision.prep(im, first.mean, first.std),
                          vision.prep(im.transpose(Image.FLIP_LEFT_RIGHT), first.mean, first.std)]).ravel()
            f = js["features"][p]
            q = f["prep"]
            off = abs(q["sum"] - float(x.astype(np.float64).sum()))
            if (q["w"], q["h"]) != im.size or float(np.abs(np.asarray(q["sample"]) - x[SAMPLE]).max()) > 1e-5 or off > 0.05:
                bad.append(f"{p}: the encoder's input is not Python's ({q['w']}x{q['h']}, sum {q['sum']:.3f} against {x.sum():.3f})")
            # (the page normalises each value in one step, Python in three float32 steps: the last bit of
            # rounding differs, a few thousandths over the 301,056 values; one pixel level is 0.015 alone)
            e, ef = enc.embed([im]), enc.embed([im.transpose(Image.FLIP_LEFT_RIGHT)])
            at = 0
            for part in enc.parts:          # each encoder's numbers against this machine's, one by one
                cs += [cos(f["e"][at:at + part.width], e[0][at:at + part.width]),
                       cos(f["ef"][at:at + part.width], ef[0][at:at + part.width])]
                at += part.width
            d = float(np.abs(np.asarray(f["h"]) - H.colour_hist(im)).max())
            hs_diff.append(d)
            if d > 0.02:                       # a pixel moved is 0.013 (60x96 of them)
                bad.append(f"{p}: colour histogram off by {d:.3f}")
            feats[p] = tuple(np.asarray(f[k], np.float32) for k in ("e", "ef", "h"))
            py = H.read(hs, card["paint"], feats[p])
            if not same_answers(js["read"][p], py):
                bad.append(f"{p}: the page's heads answer {js['read'][p]}, Python's on its numbers {py}")
        for c in js["check"]:
            P = feats.get(c["photo"]) or tuple(np.asarray(c["photo_features"][k], np.float32) for k in ("e", "ef", "h"))
            B = feats.get(c["build"]) or tuple(np.asarray(c["build_features"][k], np.float32) for k in ("e", "ef", "h"))
            py = H.judge(hs, card["thresholds"], card["paint"], P, B, standin=c.get("standin", False))
            if not same_answers(c["result"], py):
                bad.append(f"{c['photo']}: the page's check {c['result']['answer']} {c['result']['match']}, Python's {py['answer']} {py['match']}")
            # the example's answer was Python's on this machine's numbers, the page's on the browser's: the same
            # answer, its match within the two engines' difference (the heads are held to Python's just above)
            if ex and c["photo"] == ex["photo"] and (c["result"]["answer"] != ex["check"]["answer"]
                                                     or c["result"]["match"] is None
                                                     or abs(c["result"]["match"] - ex["check"]["match"]) > 0.01):
                bad.append(f"the example says {ex['check']['answer']} {ex['check']['match']}, the page {c['result']['answer']} {c['result']['match']}")
        res = {"pictures": len(reads), "checks": len(js["check"]),
               "engine_cosine_min": round(min(cs), 4), "engine_cosine_mean": round(float(np.mean(cs)), 4),
               "histogram_max_diff": round(max(hs_diff), 4), "different": bad,
               "page_errors": js["errors"], "load_ms": round(js["load_ms"]),
               "ms_a_picture": round(float(np.mean([f["ms"] for f in js["features"].values()])))}
        print(json.dumps(res, indent=1))
        sys.exit(1 if bad or js["errors"] or min(cs) < 0.97 else 0)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
