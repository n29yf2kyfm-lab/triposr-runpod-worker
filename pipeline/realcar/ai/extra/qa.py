"""qa.py: which extra photos to train on: an exterior view of one vehicle, whose paint bears its colour word out.

    python3 pipeline/realcar/ai/extra/qa.py FOLDER       -> FOLDER/qa.json

For each picture in FOLDER (flickr.py's files.jsonl and img/): {"keep": an exterior view of a whole car,
van or motorbike (CLIP B/32, zero-shot against the prompts below: not an interior, an engine, a wheel, a
badge, a toy, a drawing, a crowd...), "paint_ok": its middle's dominant hue agrees with its colour word
(a colour's hue among its chromatic pixels; a neutral's few chromatic pixels), "view", "p", "chromatic",
"hue"}. dataset.extra_items reads it: a picture not kept is left out, one kept whose paint is doubtful
teaches kind only. CLIP's text model (64 MB) is fetched once, pinned, like the encoders.
"""
import json
import os
import sys
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import heads as H  # noqa: E402
import vision  # noqa: E402

TEXT = {"clip-b32-text.onnx": ("https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/d15189d7028b43f1d3e65039190477f6af591c2a/"
                               "onnx/text_model_quantized.onnx", "73baab855d406190da9faa498cfedf65f15cf309f4cc7385b7b032e6d08e5c3a"),
        "clip-b32-tokenizer.json": ("https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/d15189d7028b43f1d3e65039190477f6af591c2a/"
                                    "tokenizer.json", "f7f3b7af117d467b58374797691a6438d3e6b9e9cef800dfd5dced7f697a90cd")}
# a whole vehicle, outside, from any angle (the extras teach kind and colour, not which way it points)
GOOD = ["a photo of a car from the side", "a photo of a car from the front, at an angle", "a photo of a van from the side",
        "a photo of a van from the front, at an angle", "a photo of a motorcycle from the side", "a photo of a pickup truck",
        "a car seen from directly behind", "a car seen from directly ahead", "a racing car on a track"]
BAD = ["the interior of a car", "a car engine bay", "a close-up of a car wheel", "a car badge or logo", "a toy model car",
       "a drawing or illustration of a car", "a group of people", "many cars in a car park", "a car crash", "a text document",
       "a building"]
# where each colour word's paint sits in Lab: hue in degrees (red about 40, orange 60, yellow 95, green 140, blue 270,
# purple 310); white, black, silver and grey are the neutrals (few chromatic pixels)
HUES = {"Red": (345, 52), "Orange": (35, 82), "Yellow": (70, 112), "Gold": (60, 105), "Beige": (50, 110), "Brown": (20, 85),
        "Green": (85, 195), "Blue": (215, 300), "Purple": (285, 345), "Pink": (315, 25)}
NEUTRAL = {"White", "Black", "Silver", "Gray", "Grey"}


def fetch_text():
    out = []
    for name, (url, want) in TEXT.items():
        p = os.path.join(vision.home(), name)
        if not os.path.exists(p) or vision.file_sha256(p) != want:
            os.makedirs(vision.home(), exist_ok=True)
            urllib.request.urlretrieve(url, p + ".part")
            if vision.file_sha256(p + ".part") != want:
                os.remove(p + ".part")
                raise SystemExit(f"qa: {url} is not the file pinned here")
            os.replace(p + ".part", p)
        out.append(p)
    return out


def text_embeds(prompts):
    import onnxruntime as ort
    from tokenizers import Tokenizer
    model, tokenizer = fetch_text()
    tok = Tokenizer.from_file(tokenizer)
    s = ort.InferenceSession(model, providers=["CPUExecutionProvider"])
    ins = {i.name for i in s.get_inputs()}
    es = []
    for p in prompts:
        ids = np.array([tok.encode(p).ids], np.int64)
        feed = {"input_ids": ids, **({"attention_mask": np.ones_like(ids)} if "attention_mask" in ins else {})}
        v = s.run(["text_embeds"], feed)[0][0]
        es.append(v / np.linalg.norm(v))
    return np.stack(es)


def paint_check(im, colour):
    """Whether the picture's middle agrees with the colour word: a colour's hue among its chromatic pixels (at
    least a tenth of them), a neutral's chromatic pixels under half (a white car under a blue sky is a third).
    Returns (ok, chromatic share, hue)."""
    im = im.convert("RGB")
    im.thumbnail((160, 160))
    w, h = im.size
    a = np.asarray(im, np.float64)[int(h * 0.2):int(h * 0.8), int(w * 0.2):int(w * 0.8)].reshape(-1, 3)
    lab = H.lab(a)
    A, B = lab[:, 1] - 128, lab[:, 2] - 128
    chromatic = np.hypot(A, B) > 14
    share = float(chromatic.mean())
    hue = float(np.degrees(np.arctan2(B[chromatic].mean(), A[chromatic].mean())) % 360) if chromatic.any() else None
    if colour in NEUTRAL:
        return share < 0.5, share, hue
    lo, hi = HUES.get(colour, (0, 360))
    inside = hue is not None and ((lo <= hue <= hi) if lo <= hi else (hue >= lo or hue <= hi))
    return share >= 0.1 and inside, share, hue


def main():
    folder = sys.argv[1]
    rows = [json.loads(l) for l in open(os.path.join(folder, "files.jsonl"))]
    colour_of = {r["id"]: r["colour"] for r in rows}
    qa_path = os.path.join(folder, "qa.json")
    done = json.load(open(qa_path)) if os.path.exists(qa_path) else {}
    todo = [r["id"] for r in rows if os.path.exists(os.path.join(folder, "img", f"{r['id']}.jpg")) and str(r["id"]) not in done]
    print(len(rows), "pictures,", len(todo), "to judge", flush=True)
    T = text_embeds(GOOD + BAD)
    enc = vision.Encoder(vision.fetch("clip-b32"))
    for n in range(0, len(todo), 32):
        batch = todo[n:n + 32]
        ims = {}
        for i in batch:
            try:
                ims[i] = vision.load(os.path.join(folder, "img", f"{i}.jpg"))
            except vision.Unreadable:
                done[str(i)] = {"keep": False, "view": "unreadable", "p": 0}
        if ims:
            E = enc.embed(list(ims.values()))
            sims = E @ T.T * 100
            p = np.exp(sims - sims.max(1, keepdims=True))
            p /= p.sum(1, keepdims=True)
            for (i, im), row in zip(ims.items(), p):
                best = int(row.argmax())
                ok, share, hue = paint_check(im, colour_of.get(i, ""))
                done[str(i)] = {"keep": best < len(GOOD) and float(row[:len(GOOD)].sum()) > 0.6, "view": (GOOD + BAD)[best],
                                "p": round(float(row[:len(GOOD)].sum()), 3), "paint_ok": bool(ok),
                                "chromatic": round(share, 3), "hue": hue and round(hue)}
        if n % 320 == 0:
            json.dump(done, open(qa_path, "w"))
            print(n + len(batch), flush=True)
    json.dump(done, open(qa_path, "w"))
    kept = [v for v in done.values() if v["keep"]]
    print(f"kept {len(kept)} of {len(done)}; paint word agreed on {sum(1 for v in kept if v.get('paint_ok'))}")


if __name__ == "__main__":
    main()
