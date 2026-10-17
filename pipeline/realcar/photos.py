#!/usr/bin/env python3
"""photos.py — the agent's reference photograph of a car the catalogue lacks.

    python3 pipeline/realcar/photos.py "Ford" "Puma" 2019 OUT_DIR LENGTH WHEELBASE HEIGHT   # mm

side_photo() searches Openverse (api.openverse.org: openly licensed images,
mostly Wikimedia Commons and Flickr, each with its licence and author), and
Wikimedia Commons itself when Openverse does not answer. It keeps only
licences that allow commercial use: CC BY, CC BY-SA, CC0, public domain.
Side and profile views come first, then the model and its first year. It
downloads them in that order, takes the background off (rembg, U2-Net on the
CPU) and stops at the first true side elevation of a plain-painted car. A
deadline keeps it inside the machine's two minutes.

roofline() reads the top of the car along its length from that cut-out
(pipeline/forge/trace.py), scaled by the published length, with the wheel
centres for lining it up with the model.

The photograph is only measured: nothing of it goes into the car, so the
car's licence is the donor model's alone. The photo's author, licence and
page are kept for showing it beside the car.
"""
import json
import os
import re
import sys
import time

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "forge"))


def check(cutout, dims):
    """Why a cut-out is not a usable side elevation of this car, or None:
    it must be one car (one outline), show both wheels on the ground at the
    car's own spacing (wheelbase over length within 6%), and have its
    height-to-length proportion within 8% (an older generation of the same
    name, such as the 1997 Puma coupe beside the 2019 crossover, does not)."""
    from scipy.ndimage import label
    a = np.asarray(Image.open(cutout))[:, :, 3] > 128
    lab, n = label(a)
    if n > 1 and np.bincount(lab.ravel())[1:].max() < 0.9 * a.sum():
        return "more than one thing in the picture"
    r = roofline(cutout, dims["length"])
    wb = r["u_front"] - r["u_rear"]
    if wb < 0.2:
        return "both wheels not seen on the ground"
    if abs(wb * dims["length"] / dims["wheelbase"] - 1) > 0.06:
        return f"wheel spacing {wb:.3f} of the length, the car's is {dims['wheelbase'] / dims['length']:.3f}"
    hl = r["height_photo"] * 1000 / dims["length"]
    if abs(hl / (dims["height"] / dims["length"]) - 1) > 0.08:
        return f"height {hl:.3f} of the length, the car's is {dims['height'] / dims['length']:.3f}"
    return None


UA = {"User-Agent": "ecc-glbmachine/1.0 (https://github.com/n29yf2kyfm-lab/triposr-runpod-worker; reference photos)"}
OV_LICENCE = {"by": "CC BY", "by-sa": "CC BY-SA", "cc0": "CC0", "pdm": "Public domain"}


def _openverse(queries, deadline):
    """Openverse hits as finder.info() gives them: title, url, w, h, licence,
    author, page. Wikimedia files are fetched as a 1600 px thumbnail."""
    import urllib.parse
    import urllib.request
    out, seen = [], set()
    for q in queries:
        if time.time() > deadline:
            break
        url = "https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(
            {"q": q, "license_type": "commercial", "page_size": 20, "mature": "false"})   # 20: the most without a key
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as r:
                d = json.load(r)
        except Exception:
            continue
        for h in d.get("results", []):
            lic = OV_LICENCE.get(h.get("license"))
            if not lic or h.get("id") in seen or not h.get("url"):
                continue
            seen.add(h["id"])
            u = h["url"]
            m = re.match(r"(https://upload\.wikimedia\.org/wikipedia/commons)/([0-9a-f])/([0-9a-f]{2})/(.+)$", u)
            if m and (h.get("width") or 0) > 1600:
                u = f"{m.group(1)}/thumb/{m.group(2)}/{m.group(3)}/{m.group(4)}/1600px-{m.group(4)}"
            out.append({"title": h.get("title") or h["id"], "url": u, "w": h.get("width") or 0, "h": h.get("height") or 1,
                        "source": h.get("source"),
                        "licence": f"{lic} {h.get('license_version') or ''}".strip(), "author": (h.get("creator") or "")[:120],
                        "page": h.get("foreign_landing_url") or h.get("url")})
    return out


def _fetch(url, path):
    import urllib.request
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            open(path, "wb").write(r.read())
        return True
    except Exception:
        return False


def side_photo(make, model, years, out_dir, dims, deadline_s=45, max_dl=10):
    """The first licensed, plain-painted true side view of the car (passing
    check()), as {"cutout", "photo", "file", "author", "licence", "page",
    "seconds", "rejected"}; None if none in time."""
    import finder
    t0 = time.time()
    os.makedirs(out_dir, exist_ok=True)
    Make = make.replace("-", " ").title()
    y0 = (years or [None])[0]
    lo, hi = (y0 or 1900) - 1, ((years or [None, None])[1] or time.localtime().tm_year) + 1

    def era(title):
        ys = [int(y) for y in re.findall(r"\b(19[5-9]\d|20[0-4]\d)\b", title)]
        return 1 if not ys else (2 if any(lo <= y <= hi for y in ys) else 0)
    hits = _openverse([f"{Make} {model} side", f"{Make} {model} {y0 or ''}".strip(), f"{Make} {model}"],
                      t0 + deadline_s * 0.4)
    if not hits and deadline_s >= 90:              # Openverse down: Commons itself, polite and slow (agent runs only)
        titles = finder.search([f"{Make} {model} side"], limit=30)
        hits = finder.info(titles) if titles and time.time() - t0 < deadline_s * 0.5 else []
    want_words = [w.lower() for w in model.split()]
    cands = [c for c in hits if (finder.OK_LICENCE.match(c["licence"] or "") or c["licence"].startswith(("CC0", "Public")))
             and c["w"] >= 1000
             and 1.3 <= c["w"] / c["h"] <= 3.8 and not finder.BAD_NAME.search(c["title"]) and era(c["title"])
             and all(w in c["title"].lower() for w in want_words)]
    # a file named "side" or "profile" first (most photos are three-quarter
    # views); then Flickr's (Wikimedia's file server throttles busy
    # addresses, HTTP 429); then the right years, the biggest
    cands.sort(key=lambda c: (1 if finder.SIDE_HINT.search(c["title"]) else 0, c.get("source") == "flickr", era(c["title"]),
                              c["w"]), reverse=True)
    from rembg import new_session, remove
    sess, rejected = None, []
    got = 0
    for c in cands:
        if time.time() - t0 > deadline_s or got >= max_dl:
            break
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", c["title"].replace("File:", ""))[:100] + "_" + str(abs(hash(c["url"])) % 10**6)
        raw = os.path.join(out_dir, name + ".jpg")
        if not os.path.exists(raw) and not _fetch(c["url"], raw):
            rejected.append({"file": c["title"], "why": "could not be downloaded"})
            continue
        got += 1
        try:
            im = Image.open(raw).convert("RGB")
            im.thumbnail((1600, 1600))
            sess = sess or new_session("u2net")
            cut = remove(im, session=sess)
            a = np.asarray(cut)[:, :, 3] > 128
            rows, cols = np.where(a.any(1))[0], np.where(a.any(0))[0]
            if not len(rows):
                continue
            cut = cut.crop((cols.min(), rows.min(), cols.max() + 1, rows.max() + 1))
            cp = os.path.join(out_dir, "side.cut.png")
            cut.save(cp)
        except Exception:
            continue
        view, _ = finder.classify(cp)
        why = "not a side view" if view != "side" else "liveried or two-tone" if not finder.plain_paint(cp) \
            else check(cp, dims)
        if why:
            rejected.append({"file": c["title"], "why": why})
            continue
        photo = os.path.join(out_dir, "photo.jpg")
        im.save(photo, quality=85)
        return {"cutout": cp, "photo": photo, "file": c["title"], "author": c["author"], "licence": c["licence"],
                "page": c["page"], "seconds": round(time.time() - t0, 1), "rejected": rejected}
    return {"none": True, "rejected": rejected, "seconds": round(time.time() - t0, 1)}


def roofline(cutout, length_mm, n=81):
    """{"u": stations tail (0) to nose (1), "roof": metres above the ground,
    "u_front", "u_rear": wheel centres} from a side cut-out."""
    import trace as tr
    rgb, mask = tr.load_cutout(cutout)
    # wheelbase 0: when the wheels are not found the tracer's fallback puts
    # both at the middle, which check() sees, instead of the published spacing
    s = tr.trace_side(rgb, mask, {"length": length_mm, "width": 1800, "height": 1500, "wheelbase": 0})
    u = np.linspace(0, 1, n)
    roof = np.interp(u, s["u"], s["roof"])
    return {"u": [round(float(x), 4) for x in u], "roof": [round(float(x), 4) for x in roof],
            "u_front": round(float(s["u_front"]), 4), "u_rear": round(float(s["u_rear"]), 4),
            "height_photo": round(float(s.get("height_photo") or max(roof)), 3)}


if __name__ == "__main__":
    a = sys.argv[1:]
    dims = dict(zip(("length", "wheelbase", "height"), (int(x) for x in a[4:7])))
    got = side_photo(a[0], a[1], [int(a[2]), None], a[3], dims)
    if got and got.get("cutout"):
        got["roofline"] = roofline(got["cutout"], dims["length"])
    print(json.dumps(got, indent=1))
