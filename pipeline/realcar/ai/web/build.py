"""build.py: the phone page and every file it reads, in one folder to publish or serve.

    F1K_HOME=/path/to/f1k python3 pipeline/realcar/ai/web/build.py OUT_DIR [--example KEY]

The page (index.html) runs the model in the phone's browser: the int8 encoder
(90 MB, vision.ENCODERS["clip-b32-int8"]) with onnxruntime-web, and the heads
trained on that encoder (web/heads.json: train.py --encoder that file --out
web/heads.json). OUT_DIR gets:

- index.html, with the encoder's pieces and the example filled in
- heads.json
- encoder.0.txt ... : the encoder in pieces of 11 MB, as base64 text (a claude.ai artifact serves
  text and media, not raw bytes, and a file of at most 16 MB: 15 MB of text a piece)
- ort-wasm-simd-threaded.wasm: onnxruntime-web's engine (fetched pinned, checked by SHA-256)
- example-photo.jpg, example-build.png and the example's answer, worked out here by the
  Python model on those very files (web/check.py checks the page gives the same)
"""
import argparse
import base64
import glob
import json
import os
import shutil
import sys
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
AI = os.path.dirname(HERE)
sys.path.insert(0, AI)

import vision  # noqa: E402

ORT = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.20.1/dist/"
ORT_WASM = ("ort-wasm-simd-threaded.wasm", "207d02be4591c156b0a98f024f3d58005b5b04c92274d759fb390338c63559ea")
PIECE = 11 * 1000 * 1000


def fetch_pinned(url, out, want):
    if not os.path.exists(out) or vision.file_sha256(out) != want:
        urllib.request.urlretrieve(url, out + ".part")
        if vision.file_sha256(out + ".part") != want:
            os.remove(out + ".part")
            raise SystemExit(f"build: {url} is not the file pinned here")
        os.replace(out + ".part", out)
    return out


def example(out, key, heads, features=None):
    """The example's pictures (the photo at most 1280 px wide) and the model's check of them: on the page's own
    reading of them (FEATURES, from web/features.py) when there is one, as the page itself would answer."""
    sys.path.insert(0, os.path.join(os.path.dirname(AI), "review"))
    import paths
    from PIL import Image
    import predict
    photo, build = paths.photo(key), paths.picture(key)
    if not photo or not build:
        raise SystemExit(f"build: {key} has no photo or no build picture")
    im = Image.open(photo).convert("RGB")
    im.thumbnail((1280, 1280))
    im.save(os.path.join(out, "example-photo.jpg"), quality=88)
    b = vision.load(build)              # cropped to the vehicle, on white: what the model reads
    b.thumbnail((1280, 1280))
    b.save(os.path.join(out, "example-build.png"))
    ai = predict.VehicleAI(heads=heads, encoder=vision.fetch("clip-b32-int8"))
    files = [os.path.join(out, "example-photo.jpg"), os.path.join(out, "example-build.png")]
    got = dict(np.load(features)) if features else {}
    ids = [paths.sha(f) for f in files]
    if all(i + ":e" in got for i in ids):
        P, B = ((got[i + ":e"], got[i + ":f"], got[i + ":h"]) for i in ids)
        check = predict.H.judge(ai.heads, ai.th, ai.paint, P, B)
    else:
        check = ai.check(*files)
    p = (paths.load(paths.f("car_photos.json"), {}).get(key) or {}).get("photo") or {}
    credit = ", ".join(x for x in (p.get("file"), p.get("author") and f"by {p['author']}", p.get("licence")) if x)
    return {"key": key, "photo": "example-photo.jpg", "build": "example-build.png", "check": check,
            "credit": credit, "page": p.get("page")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--heads", default=os.path.join(HERE, "heads.json"))
    ap.add_argument("--example", default="car-kia-rio", help="a key of the run ($F1K_HOME), shown before any picture")
    ap.add_argument("--features", default=None, help="the page's own reading of the pictures (web/features.py)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    card = json.load(open(a.heads))["card"]
    want = vision.ENCODERS["clip-b32-int8"][3]
    if card["encoder_sha256"] != want:
        raise SystemExit(f"build: {a.heads} was not trained on the int8 encoder (train.py --encoder it)")
    shutil.copy2(a.heads, os.path.join(a.out, "heads.json"))
    for old in glob.glob(os.path.join(a.out, "encoder.*")):
        os.remove(old)
    enc = vision.fetch("clip-b32-int8")
    chunks = []
    with open(enc, "rb") as fh:
        for i, part in enumerate(iter(lambda: fh.read(PIECE), b"")):
            name = f"encoder.{i}.txt"
            with open(os.path.join(a.out, name), "wb") as o:
                o.write(base64.b64encode(part))
            chunks.append(name)
    fetch_pinned(ORT + ORT_WASM[0], os.path.join(a.out, ORT_WASM[0]), ORT_WASM[1])
    ex = example(a.out, a.example, a.heads, a.features) if a.example else None
    page = open(os.path.join(HERE, "index.html")).read()
    model = {"chunks": chunks, "size": os.path.getsize(enc), "sha256": want}
    for tag, value in (("MODEL", model), ("EXAMPLE", ex)):
        start, end = f"/*{tag}*/", "/*END*/"
        i = page.index(start)
        j = page.index(end, i)
        page = page[:i + len(start)] + json.dumps(value) + page[j:]
    with open(os.path.join(a.out, "index.html"), "w") as fh:
        fh.write(page)
    print(json.dumps({"out": a.out, "chunks": len(chunks), "example": ex and ex["check"]["answer"]}))


if __name__ == "__main__":
    main()
