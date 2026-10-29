"""features.py: every training picture read by the phone page itself, for the page's heads.

    F1K_HOME=/path/to/f1k python3 pipeline/realcar/ai/web/features.py SITE_DIR OUT.npz [--pages 3]
    F1K_HOME=/path/to/f1k python3 pipeline/realcar/ai/ai/train.py --encoder INT8.onnx --features OUT.npz \\
        --out pipeline/realcar/ai/web/heads.json --review /tmp/phone_review.json

The page's engine (onnxruntime-web, WebAssembly) does the int8 encoder's
arithmetic a little otherwise than onnxruntime here (cosine 0.99 between the
two): heads trained on this machine's numbers moved the page's match by up to
0.3. Trained on the page's own numbers, they answer as they learned.
WebAssembly gives the same numbers on every device, so these are a phone's.

SITE_DIR is build.py's folder; the run's pictures are linked into it while
the browser reads them (features.cjs), then unlinked.
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
AI = os.path.dirname(HERE)
sys.path.insert(0, AI)
sys.path.insert(0, HERE)

import build  # noqa: E402
import check  # noqa: E402
import dataset  # noqa: E402
import vision  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("site")
    ap.add_argument("out")
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--extra", default=None, help="folders of photos from outside the run (train.py --extra)")
    a = ap.parse_args()
    its = dataset.items()
    files = sorted({it[s] for it in its for s in ("photo", "build") if it.get(s)})
    extras = sorted(it["photo"] for it in dataset.extra_items(a.extra)) if a.extra else []
    home = os.path.realpath(dataset.paths.home())
    link = os.path.join(a.site, "_train")
    if os.path.lexists(link):
        os.remove(link)
    os.symlink(home, link)
    links = [link]
    try:
        served = {f: "_train/" + os.path.relpath(os.path.realpath(f), home) for f in files}
        for i, folder in enumerate(sorted({os.path.dirname(f) for f in extras})):
            ln = os.path.join(a.site, f"_extra{i}")
            if os.path.lexists(ln):
                os.remove(ln)
            os.symlink(os.path.realpath(folder), ln)
            links.append(ln)
            served.update({f: f"_extra{i}/" + os.path.basename(f) for f in extras if os.path.dirname(f) == folder})
        for f in ("example-photo.jpg", "example-build.png"):     # the page's example, worked out from these
            if os.path.exists(os.path.join(a.site, f)):
                served[os.path.join(a.site, f)] = f
        cdn = os.path.join(vision.home(), "ortweb")
        os.makedirs(cdn, exist_ok=True)
        for f, sha in check.CDN.items():
            build.fetch_pinned(build.ORT + f, os.path.join(cdn, f), sha)
        lst, lines = a.out + ".list.json", a.out + ".jsonl"
        json.dump(sorted(served.values()), open(lst, "w"))
        srv = check.serve(a.site)
        env = {**os.environ, "NODE_PATH": subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()}
        subprocess.run(["node", os.path.join(HERE, "features.cjs"), f"http://127.0.0.1:{srv.server_address[1]}/index.html",
                        lst, lines, cdn, str(a.pages)], check=True, env=env)
        srv.shutdown()
    finally:
        for ln in links:
            os.remove(ln)
    got = {}
    for line in open(lines):
        r = json.loads(line)
        got[r["path"]] = r
    out, errors = {}, []
    for f, p in served.items():
        r = got.get(p)
        if not r or "error" in r:
            errors.append((p, r and r.get("error")))
            continue
        i = dataset.paths.sha(f)
        out[i + ":e"], out[i + ":f"], out[i + ":h"] = (np.asarray(r[k], np.float32) for k in ("e", "ef", "h"))
    np.savez(a.out, **out)
    print(json.dumps({"pictures": len(served), "read": len(out) // 3, "errors": errors[:10], "written": a.out}))


if __name__ == "__main__":
    main()
