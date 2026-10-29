"""none.py: pictures with no vehicle in them, for the vehicle head (a vehicle in view, or none).

    python3 pipeline/realcar/ai/extra/none.py OUT_DIR       -> OUT_DIR/files.jsonl, img/, qa.json

CC-licensed Flickr photos (the YFCC100M 15M subset on Hugging Face, as ../../openphotos.py streams it: CC BY and
CC BY-SA only) tagged with one of TOPICS and naming no vehicle, PER_TOPIC of each topic, fetched at Flickr's 500 px;
then each held to CLIP B/32 against vehicle prompts (one showing a vehicle after all is left out); and MADE pictures
drawn here (noise, plain colours, gradients, stripes, blotches: what a broken file or a lens cap gives). Each row
has kind "none" and no colour. train.py --extra OUT_DIR trains the vehicle head on them, and the run's own pictures
and the extras are its vehicles.
"""
import csv
import io
import json
import os
import random
import re
import sys
import urllib.parse
import urllib.request

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import flickr  # noqa: E402
import qa  # noqa: E402
import vision  # noqa: E402

SOURCE = "https://huggingface.co/datasets/mehdidc/yfcc15m/resolve/main/yfcc15m.csv"
LICENCE = {"Attribution License": "CC BY 2.0", "Attribution-ShareAlike License": "CC BY-SA 2.0"}
TOPICS = ["landscape", "mountain", "beach", "sea", "forest", "flower", "garden", "tree", "sky", "sunset", "snow",
          "river", "lake", "desert", "field", "dog", "cat", "bird", "horse", "cow", "sheep", "insect", "butterfly",
          "food", "cake", "fruit", "kitchen", "livingroom", "bedroom", "portrait", "people", "family", "wedding",
          "concert", "church", "castle", "museum", "statue", "painting", "books", "macro", "texture", "wall", "sculpture"]
PER_TOPIC = 30
MADE = 240
# a photo whose words name any vehicle, or a place full of them, is not taken
VEHICLE = re.compile(r"\b(?:cars?|auto\w*|truck\w*|lorr\w*|vans?|bus\w*|coach\w*|taxi\w*|cabs?|motor\w*|moto\w*|"
                     r"bike\w*|bicycl\w*|cycl\w*|scooter\w*|trains?|tram\w*|rail\w*|locomotive\w*|plane\w*|aircraft|"
                     r"airport|boat\w*|ship\w*|ferr\w*|yacht\w*|tractor\w*|traffic|roads?|street\w*|highway\w*|"
                     r"parking|garage\w*|rac\w*|rally\w*|jeep\w*|suv|vehicle\w*|wheel\w*|engine\w*|" +
                     "|".join(re.escape(m.replace(" ", "")) for m in
                              ["ford", "bmw", "audi", "toyota", "honda", "volkswagen", "vw", "mercedes", "porsche",
                               "ferrari", "fiat", "nissan", "renault", "peugeot", "citroen", "vauxhall", "opel",
                               "volvo", "mini", "jaguar", "landrover", "harley", "ducati", "vespa", "kia", "hyundai",
                               "mazda", "subaru", "suzuki", "tesla", "lamborghini", "chevrolet", "dodge"]) + r")\b", re.I)
# a vehicle after all: CLIP's prompts, the first VEH of them a vehicle
VEH = ["a photo of a car", "a photo of a van", "a photo of a truck", "a photo of a motorcycle", "a photo of a bus",
       "a photo of a bicycle", "a street with cars parked", "a car park"]
OTHER = ["a photo of a landscape", "a photo of an animal", "a photo of food", "a photo of a building", "a photo of people",
         "a photo of a flower", "a photo of a room", "a photo of the sky", "a painting", "a photo of an object",
         "a close-up of a texture"]
VEHICLE_P = 0.5          # kept when no vehicle prompt is CLIP's best and they hold under this share (8 of 19 prompts:
                         # a flower's photo gives them about 0.1, a crowd's 0.4)


def _text(s):
    return urllib.parse.unquote_plus(s or "")


def pick(src=SOURCE, per_topic=PER_TOPIC):
    """Rows of the set, streamed from the start until every topic has its PER_TOPIC (half as many again, for the
    fetches that fail and the pictures CLIP finds a vehicle in)."""
    want = int(per_topic * 1.5)
    got = {t: [] for t in TOPICS}
    with urllib.request.urlopen(urllib.request.Request(src, headers={"User-Agent": "vehicle-ai/2.0"}), timeout=120) as r:
        for row in csv.DictReader(io.TextIOWrapper(r, encoding="utf-8", errors="replace", newline="")):
            lic = LICENCE.get(row.get("licensename") or "")
            if not lic or not row.get("downloadurl"):
                continue
            title, tags = _text(row.get("title")), _text(row.get("usertags")).replace(",", " ")
            words = set(tags.lower().split())
            topic = next((t for t in TOPICS if t in words and len(got[t]) < want), None)
            if not topic or VEHICLE.search(title + " " + tags + " " + _text(row.get("description"))[:300]):
                continue
            got[topic].append({"id": "n" + row["photoid"], "title": title[:200], "tags": tags[:400], "colour": None,
                               "kind": "none", "topic": topic, "thumb": row["downloadurl"].replace("http://", "https://"),
                               "page": row.get("pageurl"), "licence": lic, "author": _text(row.get("unickname"))[:80]})
            if all(len(v) >= want for v in got.values()):
                break
    return [r for t in TOPICS for r in got[t]]


def made(out, n=MADE, seed=7):
    """N pictures drawn here, no vehicle in any: noise, plain colour, gradients, stripes, blotches, blurred."""
    rng = random.Random(seed)
    nrng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        w, h = rng.choice([(500, 375), (500, 500), (375, 500), (640, 480)])
        kind = ["noise", "plain", "gradient", "stripes", "blotches", "blur"][i % 6]
        if kind == "noise":
            a = nrng.integers(0, 256, (h, w, 3), dtype=np.uint8)
        elif kind == "plain":
            a = np.zeros((h, w, 3), np.uint8) + np.array([rng.randrange(256) for _ in range(3)], np.uint8)
        elif kind == "gradient":
            t = np.linspace(0, 1, w)[None, :, None] if rng.random() < 0.5 else np.linspace(0, 1, h)[:, None, None]
            c0, c1 = nrng.integers(0, 256, 3), nrng.integers(0, 256, 3)
            a = (c0 + (c1 - c0) * t + np.zeros((h, w, 1))).astype(np.uint8)
        elif kind == "stripes":
            p = rng.randrange(6, 60)
            m = ((np.arange(w)[None, :] + (np.arange(h)[:, None] if rng.random() < 0.5 else 0)) // p) % 2
            a = np.where(m[..., None] == 1, nrng.integers(0, 256, 3), nrng.integers(0, 256, 3)).astype(np.uint8)
        else:
            im = Image.new("RGB", (w, h), tuple(rng.randrange(256) for _ in range(3)))
            d = ImageDraw.Draw(im)
            for _ in range(rng.randrange(3, 25)):
                x, y, r = rng.randrange(w), rng.randrange(h), rng.randrange(10, 160)
                d.ellipse((x - r, y - r, x + r, y + r), fill=tuple(rng.randrange(256) for _ in range(3)))
            if kind == "blur":
                im = im.filter(ImageFilter.GaussianBlur(rng.randrange(8, 40)))
            a = np.asarray(im)
        rid = f"made{i:03d}"
        Image.fromarray(a).save(os.path.join(out, "img", rid + ".jpg"), quality=90)
        rows.append({"id": rid, "title": f"{kind} (drawn here)", "tags": "", "colour": None, "kind": "none",
                     "topic": "made", "thumb": None, "page": None, "licence": "made here", "author": None, "w": w, "h": h})
    return rows


def check(out):
    """qa.json: each picture kept unless CLIP sees a vehicle in it (a vehicle prompt its best, or theirs at least
    VEHICLE_P of the share)."""
    rows = [json.loads(l) for l in open(os.path.join(out, "files.jsonl"))]
    T = qa.text_embeds(VEH + OTHER)
    enc = vision.Encoder(vision.fetch("clip-b32"))
    res = {}
    for n in range(0, len(rows), 32):
        batch = rows[n:n + 32]
        ims = []
        for r in batch:
            try:
                ims.append(vision.load(os.path.join(out, "img", r["id"] + ".jpg")))
            except vision.Unreadable:
                ims.append(None)
        ok = [i for i, im in enumerate(ims) if im is not None]
        if ok:
            E = enc.embed([ims[i] for i in ok])
            s = E @ T.T * 100
            p = np.exp(s - s.max(1, keepdims=True))
            p /= p.sum(1, keepdims=True)
            for i, row in zip(ok, p):
                pv = float(row[:len(VEH)].sum())
                res[str(batch[i]["id"])] = {"keep": pv < VEHICLE_P and int(row.argmax()) >= len(VEH), "p_vehicle": round(pv, 3),
                                            "view": (VEH + OTHER)[int(row.argmax())]}
        for i, im in enumerate(ims):
            if im is None:
                res[str(batch[i]["id"])] = {"keep": False, "view": "unreadable"}
    json.dump(res, open(os.path.join(out, "qa.json"), "w"), indent=0)
    kept = sum(v["keep"] for v in res.values())
    print(f"{len(res)} pictures, {kept} kept, {len(res) - kept} with a vehicle in them (or unreadable)", flush=True)


def main():
    out = sys.argv[1]
    os.makedirs(os.path.join(out, "img"), exist_ok=True)
    listing = os.path.join(out, "files.jsonl")
    if not os.path.exists(os.path.join(out, "picked.jsonl")):
        rows = pick()
        with open(os.path.join(out, "picked.jsonl"), "w") as fh:
            fh.writelines(json.dumps(r) + "\n" for r in rows)
        print(f"{len(rows)} photos picked over {len(TOPICS)} topics", flush=True)
    rows = [json.loads(l) for l in open(os.path.join(out, "picked.jsonl"))]
    flickr.fetch(rows, out)
    have = {json.loads(l)["id"] for l in open(listing)}
    if not any(i.startswith("made") for i in have):
        with open(listing, "a") as fh:
            fh.writelines(json.dumps(r) + "\n" for r in made(out))
    check(out)


if __name__ == "__main__":
    main()
