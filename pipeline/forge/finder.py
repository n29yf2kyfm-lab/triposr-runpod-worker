#!/usr/bin/env python3
"""finder.py — licensed reference photographs of a car, found on its own.

Searches Wikimedia Commons (the one large photo source whose licences are
machine-readable), keeps only files under CC BY, CC BY-SA, CC0 or public
domain, downloads the likeliest side, front and rear shots, removes their
backgrounds offline (rembg, U²-Net on CPU) and sorts them by what the
cut-out's proportions say the view is:

    side      width/height 2.2 – 3.6
    end view  width/height 0.95 – 1.6   (front or rear: decided by the
                                         file name, else left unlabelled)
    anything else is a three-quarter view, recorded and unused.

Every file used is written to refs.json with its author, licence and page,
because attribution ships with the model. Google Images is not used: those
photographs are copyrighted and would end up baked into the texture.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import numpy as np
from PIL import Image

UA = {"User-Agent": "ecc-forge/0.1 (https://github.com/n29yf2kyfm-lab/triposr-runpod-worker; reference finder)"}
OK_LICENCE = re.compile(r"^(CC BY(-SA)?( \d\.\d)?|CC0|Public domain|CC-BY(-SA)?.*)$", re.I)
BAD_NAME = re.compile(r"interior|engine|dash|cockpit|seat|wheel|detail|badge|logo|emblem|boot|trunk|steering|"
                      r"gauge|cluster|screen|key|brochure|crash|race|rally|police|taxi|toy|model car|lego|cutaway", re.I)
FRONT_HINT = re.compile(r"front|vorne|_v\.|8v\.|face|nose|avant", re.I)
REAR_HINT = re.compile(r"rear|back|hinten|_h\.|8h\.|heck|tail|arri", re.I)
SIDE_HINT = re.compile(r"side|profile|seite|lateral|profil", re.I)


def api(params, tries=4):
    """One Commons API call, polite: a pause before every call and a longer
    one after a 429. Progress goes to stderr so an agent log shows where the
    time went."""
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(dict(params, format="json"))
    time.sleep(3)
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                print(f"  commons {params.get('list') or params.get('prop')}: ok", file=sys.stderr, flush=True)
                return json.load(r)
        except urllib.error.HTTPError as e:
            print(f"  commons {params.get('list') or params.get('prop')}: HTTP {e.code}, try {i + 1}", file=sys.stderr, flush=True)
            if e.code == 429:
                time.sleep(20 * (i + 1))
                continue
            return None
        except Exception as e:
            print(f"  commons: {e}", file=sys.stderr, flush=True)
            time.sleep(5)
    return None


def fetch(url, path, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
                open(path, "wb").write(r.read())
            return True
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(25 * (i + 1))
                continue
            return False
        except Exception:
            time.sleep(5)
    return False


def search(queries, limit=50):
    titles = []
    for q in queries:
        d = api({"action": "query", "list": "search", "srsearch": q, "srnamespace": 6, "srlimit": limit})
        for hit in (d or {}).get("query", {}).get("search", []):
            if hit["title"] not in titles:
                titles.append(hit["title"])
    return titles


def info(titles):
    out = []
    for i in range(0, min(len(titles), 40), 20):
        d = api({"action": "query", "titles": "|".join(titles[i:i + 20]), "prop": "imageinfo",
                 "iiprop": "url|size|extmetadata|mime", "iiurlwidth": 1600})
        for p in (d or {}).get("query", {}).get("pages", {}).values():
            ii = (p.get("imageinfo") or [None])[0]
            if not ii or ii.get("mime") not in ("image/jpeg", "image/png"):
                continue
            em = ii.get("extmetadata", {})
            lic = em.get("LicenseShortName", {}).get("value", "")
            out.append({"title": p["title"], "url": ii.get("thumburl") or ii["url"], "w": ii["width"], "h": ii["height"],
                        "licence": lic, "author": re.sub("<[^>]+>", "", em.get("Artist", {}).get("value", ""))[:120],
                        "page": ii["descriptionurl"]})
    return out


def front_or_rear(cutout_path):
    """Which end is this? Tail lamps are red and sit at the two outer edges
    at lamp height; a nose has none (unless the whole car is red, in which
    case the lamp zone is no redder than the body and the answer is None)."""
    im = np.asarray(Image.open(cutout_path).convert("RGBA")).astype(float)
    a = im[:, :, 3] > 128
    r, g, b = im[:, :, 0], im[:, :, 1], im[:, :, 2]
    red = a & (r > 110) & (r > 1.6 * g) & (r > 1.6 * b)
    H, W = a.shape
    z0, z1 = int(H * 0.35), int(H * 0.75)              # lamp height band (image y grows down)
    lamp = np.zeros_like(a)
    lamp[z0:z1, :int(W * 0.22)] = True
    lamp[z0:z1, int(W * 0.78):] = True
    lamp &= a
    body = a & ~lamp
    f_lamp = red[lamp].mean() if lamp.any() else 0
    f_body = red[body].mean() if body.any() else 0
    if f_lamp >= 0.03 and f_lamp >= 3 * max(f_body, 0.002):
        return "rear"
    if f_lamp < 0.008 and f_body < 0.05:
        return "front"
    return None


def classify(cutout_path):
    a = np.asarray(Image.open(cutout_path))[:, :, 3] > 128
    rows, cols = np.where(a.any(1))[0], np.where(a.any(0))[0]
    if not len(rows) or not len(cols):
        return None, 0
    w, h = cols.max() - cols.min() + 1, rows.max() - rows.min() + 1
    asp = w / h
    fill = a.mean()
    if 2.2 <= asp <= 3.6:
        return "side", asp
    if 0.95 <= asp <= 1.6:
        return "end", asp
    return "34", asp


def find_photos(make, model, hints, out_dir, max_dl=14, session=None):
    """hints: list of extra words (generation, years). Returns a summary dict
    and writes side/front/rear.png + refs.json into out_dir."""
    os.makedirs(out_dir, exist_ok=True)
    Make = make.replace("-", " ").title()
    queries = [f"{Make} {model} {' '.join(hints[:1])}".strip()]
    titles = search(queries, limit=40)
    if len(titles) < 8:
        titles = search([f"{Make} {model}"], limit=40)
    # a true side view is the one photo Forge cannot do without, and Commons
    # file names usually say "side" or "profile" when they have one
    for t in search([f"{Make} {model} side", f"{Make} {model} profile"], limit=20):
        if t not in titles:
            titles.insert(0, t)
    cands = [c for c in info(titles) if OK_LICENCE.match(c["licence"] or "") and c["w"] >= 1000
             and 0.9 <= c["w"] / c["h"] <= 3.8 and not BAD_NAME.search(c["title"])]
    # prefer files whose names say which view they are, then the biggest
    def score(c):
        n = c["title"]
        return (2 if SIDE_HINT.search(n) else 1 if (FRONT_HINT.search(n) or REAR_HINT.search(n)) else 0, c["w"] * c["h"])
    cands.sort(key=score, reverse=True)
    summary = {"searched": len(titles), "licensed": len(cands), "downloaded": 0, "views": {}, "unused": []}
    if not cands:
        return summary
    from rembg import remove, new_session
    sess = session or new_session("u2net")
    best = {}
    refs = []
    raw_dir = os.path.join(out_dir, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    for c in cands[:max_dl]:
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", c["title"].replace("File:", ""))
        raw = os.path.join(raw_dir, name)
        if not os.path.exists(raw) and not fetch(c["url"], raw):
            continue
        summary["downloaded"] += 1
        try:
            im = Image.open(raw).convert("RGB")
            if max(im.size) > 1800:
                im.thumbnail((1800, 1800))
            cut = remove(im, session=sess)
            a = np.asarray(cut)[:, :, 3] > 128
            rows, cols = np.where(a.any(1))[0], np.where(a.any(0))[0]
            cut = cut.crop((cols.min(), rows.min(), cols.max() + 1, rows.max() + 1))
            cp = os.path.join(raw_dir, name + ".cut.png")
            cut.save(cp)
        except Exception as e:
            summary["unused"].append({"file": name, "why": f"cut-out failed: {e}"[:80]})
            continue
        view, asp = classify(cp)
        if view == "end":
            view = "front" if FRONT_HINT.search(name) else "rear" if REAR_HINT.search(name) else front_or_rear(cp)
            if view is None:
                summary["unused"].append({"file": name, "why": f"end view but unknown which (aspect {asp:.2f})"})
                continue
        if view in (None, "34"):
            summary["unused"].append({"file": name, "why": f"three-quarter view (aspect {asp:.2f})"})
            continue
        area = cut.size[0] * cut.size[1]
        if view not in best or area > best[view][1]:
            best[view] = (cp, area, c, asp)
        time.sleep(1)
    for view, (cp, area, c, asp) in best.items():
        dst = os.path.join(out_dir, f"{view}.png")
        Image.open(cp).save(dst)
        refs.append({"view": view, "file": c["title"], "licence": c["licence"], "author": c["author"], "page": c["page"],
                     "aspect": round(asp, 2)})
        summary["views"][view] = c["title"]
    json.dump(refs, open(os.path.join(out_dir, "refs.json"), "w"), indent=1)
    return summary


if __name__ == "__main__":
    import sys
    print(json.dumps(find_photos(sys.argv[1], sys.argv[2], sys.argv[3:-1], sys.argv[-1]), indent=1))
