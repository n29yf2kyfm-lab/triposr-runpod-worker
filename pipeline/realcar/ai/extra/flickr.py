"""flickr.py: photos from outside the run, from the machine's open Flickr index, with a colour and a kind.

    python3 pipeline/realcar/ai/extra/flickr.py OUT_DIR [--index FILE]

The index ($GLBMACHINE_HOME/open_photos.jsonl, see ../../openphotos.py: YFCC100M, CC-licensed Flickr
photos with their titles, tags, licence and author) has thousands of vehicle photos. A photo is taken
when its title and tags name exactly one colour and one kind of vehicle: OUT_DIR/files.jsonl (one line a
photo: id, title, colour, kind, thumb, page, licence, author, w, h) and OUT_DIR/img/ID.jpg (Flickr's
500 px copy). The words are the photographer's, so a "green car" can be a car on Kew Green: qa.py then
keeps the exterior views of one vehicle whose paint bears the colour word out. train.py --extra OUT_DIR
trains the colour and kind heads on them, at half the weight of the run's own.
"""
import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.request

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(HERE))))

UA = {"User-Agent": "vehicle-ai/2.0 (https://github.com/n29yf2kyfm-lab/triposr-runpod-worker)"}
COL = {"red": "Red", "white": "White", "blue": "Blue", "black": "Black", "silver": "Silver", "grey": "Gray", "gray": "Gray",
       "green": "Green", "yellow": "Yellow", "orange": "Orange", "beige": "Beige", "brown": "Brown", "purple": "Purple",
       "pink": "Pink", "gold": "Gold"}
KIND = {"car": "car", "cars": "car", "hatchback": "car", "sedan": "car", "saloon": "car", "coupe": "car", "suv": "car",
        "estate": "car", "convertible": "car", "van": "van", "vans": "van", "minivan": "van", "pickup": "van",
        "motorcycle": "motorbike", "motorbike": "motorbike", "moto": "motorbike", "scooter": "motorbike", "harley": "motorbike",
        "ducati": "motorbike", "kawasaki": "motorbike", "vespa": "motorbike"}


def default_index():
    from pipeline.realcar import openphotos
    return openphotos.INDEX


def pick(index):
    rows = []
    for line in open(index):
        r = json.loads(line)
        words = set(re.findall(r"[a-z]+", (r.get("title", "") + " " + r.get("tags", "")).lower()))
        cs = {COL[w] for w in words if w in COL}
        ks = {KIND[w] for w in words if w in KIND}
        if len(cs) == 1 and len(ks) == 1 and r.get("licence") and r.get("url"):
            rows.append({"id": "f" + r["id"], "title": r.get("title", ""), "tags": r.get("tags", ""), "colour": cs.pop(),
                         "kind": ks.pop(), "thumb": r["url"].replace("http://", "https://"), "page": r.get("page"),
                         "licence": r["licence"], "author": r.get("author")})
    return rows


def fetch(rows, out, workers=3):
    os.makedirs(os.path.join(out, "img"), exist_ok=True)
    listing = os.path.join(out, "files.jsonl")
    done = {json.loads(l)["id"] for l in open(listing)} if os.path.exists(listing) else set()
    todo = [r for r in rows if r["id"] not in done]
    print(f"{len(rows)} candidates, {len(todo)} to fetch", flush=True)
    lock = threading.Lock()
    fh = open(listing, "a")
    stats = {"ok": 0, "fail": 0, "t": time.time()}

    def worker(part):
        for r in part:
            p = os.path.join(out, "img", r["id"] + ".jpg")
            ok = False
            try:
                data = urllib.request.urlopen(urllib.request.Request(r["thumb"], headers=UA), timeout=40).read()
                open(p + ".part", "wb").write(data)
                with Image.open(p + ".part") as im:
                    r["w"], r["h"] = im.size
                    if im.mode != "RGB":
                        im.convert("RGB").save(p, quality=90)
                        os.remove(p + ".part")
                    else:
                        os.replace(p + ".part", p)
                ok = True
            except Exception:
                if os.path.exists(p + ".part"):
                    os.remove(p + ".part")
            with lock:
                if ok:
                    fh.write(json.dumps(r) + "\n")
                    fh.flush()
                stats["ok" if ok else "fail"] += 1
                n = stats["ok"] + stats["fail"]
                if n % 200 == 0:
                    print(f"{n}/{len(todo)} ok {stats['ok']} failed {stats['fail']} ({(time.time() - stats['t']) / 60:.0f} min)", flush=True)
            time.sleep(0.4)

    ths = [threading.Thread(target=worker, args=(todo[i::workers],)) for i in range(workers)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    print("done", stats, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--index", default=None, help="the photo index (default $GLBMACHINE_HOME/open_photos.jsonl)")
    a = ap.parse_args()
    fetch(pick(a.index or default_index()), a.out)


if __name__ == "__main__":
    main()
