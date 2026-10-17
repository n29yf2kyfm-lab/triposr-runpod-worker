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
# whole words only: "toy" is not to catch every Toyota, nor "race" a Grace;
# a make that is one of these words (SEAT) is taken out of the name first.
# A tuned or widebody car has the wrong outline for the car it is named for.
BAD_NAME = re.compile(r"\b(?:interior|engine|dash(?:board)?|cockpit|seats?|wheels?|details?|badges?|logos?|emblems?|"
                      r"boot|trunk|steering|gauges?|cluster|screen|keys?|brochure|crash(?:ed)?|rac(?:e|es|ing)|"
                      r"rall(?:y|ies)|police|taxis?|toys?|die[ -]?cast|model car|scale model|lego|cutaway|wreck(?:ed)?|"
                      r"wide ?body|body ?kit|tun(?:ed|ing)|modified|stanced?|slammed|drift(?:ing)?|"
                      r"prior[ -]design|liberty walk|rocket bunny|limo(?:usine)?|stretch(?:ed)?|"
                      r"wrc|r[25]|rally[234]|s2000 rally|super 2000|group [abn]|rallycross|touring car|btcc|dtm|gt[34]|"
                      r"le mans|nascar|time attack|hill ?climb|concept|prototype|show ?car|mock-?up)\b", re.I)


def bad_name(title, make="", model=""):
    """Whether a file's name says it is not a photo of the whole real car
    (the make's and model's own words aside: SEAT, a Renault R5)."""
    for w in (str(make or "") + " " + str(model or "")).replace("-", " ").split():
        title = re.sub(r"\b" + re.escape(w) + r"\b", " ", title, flags=re.I)
    return bool(BAD_NAME.search(title))
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


def plain_paint(cutout_path):
    """False for a liveried, wrapped or two-tone car: the body (the band
    between 25% and 55% of the height, where the doors are) must be mostly
    one colour. The Corsa run baked a dealer's blue wrap onto the model."""
    im = np.asarray(Image.open(cutout_path).convert("RGBA")).astype(float)
    a = im[:, :, 3] > 128
    H = a.shape[0]
    band = np.zeros_like(a)
    band[int(H * 0.45):int(H * 0.75)] = True        # image y grows down: 25-55% of height from the ground
    px = im[a & band][:, :3]
    if len(px) < 500:
        return True
    # quantise to 12 levels a channel and ask how much the top colour covers,
    # counting near-grey shades together (silver, white, black all pass)
    q = (px // 22).astype(int)
    sat = px.max(1) - px.min(1)
    q[sat < 40] = -1                                # all greys are one colour
    keys = q[:, 0] * 10000 + q[:, 1] * 100 + q[:, 2]
    keys[sat < 40] = -1
    vals, counts = np.unique(keys, return_counts=True)
    top = counts.max() / len(keys)
    return bool(top >= 0.55)


def classify(cutout_path):
    a = np.asarray(Image.open(cutout_path))[:, :, 3] > 128
    rows, cols = np.where(a.any(1))[0], np.where(a.any(0))[0]
    if not len(rows) or not len(cols):
        return None, 0
    w, h = cols.max() - cols.min() + 1, rows.max() - rows.min() + 1
    asp = w / h
    fill = a.mean()
    # a true side elevation of a car is 2.5-3.6 times wider than tall; a
    # slightly angled one at 2.2 was taken as a side and lofted as a blob
    if 2.5 <= asp <= 3.6:
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
             and 0.9 <= c["w"] / c["h"] <= 3.8 and not bad_name(c["title"], make)]
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
        if view == "side" and not plain_paint(cp):
            summary["unused"].append({"file": name, "why": "liveried or two-tone body"})
            continue
        area = cut.size[0] * cut.size[1]
        # one car, one photographer: an end view by the author of the side
        # view (same car, same day, same colour) beats a bigger one by
        # somebody else
        same = "side" in best and c["author"] and c["author"] == best["side"][2]["author"]
        rank = (1 if same else 0, area)
        if view not in best or rank > best[view][4]:
            best[view] = (cp, area, c, asp, rank)
        time.sleep(1)
    for view, (cp, area, c, asp, rank) in best.items():
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
