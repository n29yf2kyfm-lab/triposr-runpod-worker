#!/usr/bin/env python3
"""photos.py — the agent's reference photograph of a car the catalogue lacks.

    python3 pipeline/realcar/photos.py "Ford" "Puma" 2019 OUT_DIR LENGTH WHEELBASE HEIGHT   # mm

side_photo() searches Openverse (api.openverse.org: openly licensed images,
mostly Wikimedia Commons and Flickr, each with its licence and author), the
local index of open Flickr photos when it has been built (openphotos.py:
YFCC100M, from Hugging Face), and Wikimedia Commons itself when Openverse
does not answer. It keeps only
licences that allow commercial use: CC BY, CC BY-SA, CC0, public domain.
Side and profile views come first, then the model and its first year. It
downloads them in that order, takes the background off (rembg, U2-Net on the
CPU) and stops at the first true side elevation of a plain-painted car. A
deadline keeps it inside the machine's minute; a search still running when
the build is done goes on, and its photo is used the next time.

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
    if (~a.any(0)[np.where(a.any(0))[0].min():np.where(a.any(0))[0].max() + 1]).any():
        return "the outline has a gap in it"
    try:
        r = roofline(cutout, dims["length"])
    except Exception:
        return "the outline could not be traced"
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
        except Exception as e:
            if getattr(e, "code", None) == 429:
                THROTTLED["openverse"] += 1
            continue
        for h in d.get("results", []):
            lic = OV_LICENCE.get(h.get("license"))
            if not lic or h.get("id") in seen or not h.get("url"):
                continue
            seen.add(h["id"])
            u = h["url"]
            m = re.match(r"(https://upload\.wikimedia\.org/wikipedia/commons)/([0-9a-f])/([0-9a-f]{2})/(.+)$", u)
            if m and (h.get("width") or 0) > 1280:     # Wikimedia serves standard thumbnail widths only
                u = f"{m.group(1)}/thumb/{m.group(2)}/{m.group(3)}/{m.group(4)}/1280px-{m.group(4)}"
            out.append({"title": h.get("title") or h["id"], "url": u, "w": h.get("width") or 0, "h": h.get("height") or 1,
                        "source": h.get("source"), "thumb": h.get("thumbnail"),
                        "tags": " ".join(str(t.get("name") or "") for t in h.get("tags") or [])[:400],
                        "licence": f"{lic} {h.get('license_version') or ''}".strip(), "author": (h.get("creator") or "")[:120],
                        "page": h.get("foreign_landing_url") or h.get("url")})
    return out


def _fetch(url, path, wait_s=0.0):
    """Download URL to PATH. A server that says "too many requests" is asked
    once more after the pause it names, if that fits in WAIT_S."""
    import urllib.request
    for attempt in (0, 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                open(path, "wb").write(r.read())
            return True
        except Exception as e:
            if getattr(e, "code", None) != 429:
                return False
            THROTTLED["files"] += 1
            try:
                pause = float(e.headers.get("Retry-After") or 2)
            except (TypeError, ValueError, AttributeError):
                pause = 2.0
            if attempt or pause > wait_s:
                return False
            time.sleep(pause)
    return False


def _via_openverse(c, path):
    """The same photo from Openverse's own copy (its image proxy), for a host
    that will not serve this machine; Flickr's come through, Wikimedia's
    mostly not (the proxy answers 424 when it cannot fetch them either)."""
    return bool(c.get("thumb")) and _fetch(c["thumb"] + "?full_size=true", path)


THROTTLED = {"openverse": 0, "files": 0}           # refusals for too many requests, for photolib's pacing

# the shipped roofline library (photolib.py): measured outlines, credits, no photos
LIBRARY = os.path.join(HERE, "roofline_table.json")
_LIB = {}
MAKE_KEY = {"mercedes": "mercedesbenz", "merc": "mercedesbenz", "vw": "volkswagen", "opel": "vauxhall",
            "rangerover": "landrover", "alfa": "alfaromeo"}


def libkey(make, model, year0):
    """'mercedes-benz|a-class|2012' and 'Mercedes|A Class|2012' are one key;
    an Opel and its Vauxhall twin share an outline."""
    n = lambda x: re.sub(r"[^a-z0-9]", "", str(x or "").lower())  # noqa: E731
    mk = MAKE_KEY.get(n(make), n(make))
    md = n(model)
    if md.startswith(mk):
        md = md[len(mk):]
    return f"{mk}|{md}|{year0 or ''}"


def library():
    if not _LIB and os.path.exists(LIBRARY):
        _LIB.update(json.load(open(LIBRARY)))
    return _LIB


def from_library(make, model, year0):
    """A generation's measured outline and its photo's credit, if the library has it."""
    return library().get(libkey(make, model, year0))


def side_photo(make, model, years, out_dir, dims, deadline_s=45, max_dl=24, dated_only=False, accept=None):
    """The first licensed, plain-painted side view of the car (passing
    check()), as {"cutout", "photo", "file", "author", "licence", "page",
    "dated", "seconds", "rejected"}; {"none": True, ...} if none in time.
    A true side elevation is tried first; a nearly side-on photo (the car a
    little turned) counts when check() finds the car's own wheel spacing and
    proportions in it, which a real three-quarter view never has. "dated"
    says whether the file's name or tags gave the right years (an undated
    photo of a model's other generation with the same proportions can pass
    check()); DATED_ONLY keeps only those. ACCEPT(candidate, cutout), if
    given, has the last word: a reason to pass a photo over, or None (the
    library's, which can date a photo by when it was taken)."""
    import finder
    t0 = time.time()
    os.makedirs(out_dir, exist_ok=True)
    Make = make.replace("-", " ").title()
    y0 = (years or [None])[0]
    lo, hi = (y0 or 1900) - 1, ((years or [None, None])[1] or time.localtime().tm_year) + 1

    def era(c):
        """2 the right years named, 1 none named, 0 other years."""
        ys = [int(y) for y in re.findall(r"\b(19[5-9]\d|20[0-4]\d)\b", c["title"])]
        if not ys:                                  # the photographer's tags, when the name has no year
            ys = [int(y) for y in re.findall(r"\b(19[5-9]\d|20[0-4]\d)\b", c.get("tags") or "")]
        return 1 if not ys else (2 if any(lo <= y <= hi for y in ys) else 0)
    hits = _openverse([f"{Make} {model} side", f"{Make} {model} profile", f"{Make} {model} {y0 or ''}".strip(),
                       f"{Make} {model}"], t0 + deadline_s * 0.4)
    try:                                           # the local index of open Flickr photos (openphotos.py), if built
        import openphotos
        hits += openphotos.candidates(make, model, years)
    except Exception:
        pass
    if not hits and deadline_s >= 90:              # Openverse down: Commons itself, polite and slow (agent runs only)
        titles = finder.search([f"{Make} {model} side"], limit=30)
        hits = finder.info(titles) if titles and time.time() - t0 < deadline_s * 0.5 else []
    want_words = [w.lower() for w in model.split()]
    cands = [c for c in hits if (finder.OK_LICENCE.match(c["licence"] or "") or c["licence"].startswith(("CC0", "Public")))
             and (c["w"] is None or (c["w"] >= 1000 and 1.3 <= c["w"] / c["h"] <= 3.8))   # None: not known until fetched
             and not finder.bad_name(c["title"], make, model)
             and era(c) >= (2 if dated_only and not (accept and c.get("taken")) else 1)
             and all(w in c["title"].lower() for w in want_words)]
    # a file named "side" or "profile" first (most photos are three-quarter
    # views); then Flickr's (Wikimedia's file server throttles busy
    # addresses, HTTP 429); then the right years, the biggest
    cands.sort(key=lambda c: (1 if finder.SIDE_HINT.search(c["title"] + " " + (c.get("tags") or "")) else 0,
                              c.get("source") in ("flickr", "flickr-yfcc"), era(c), c["w"] or 0), reverse=True)
    from rembg import new_session, remove
    sess, rejected = None, []
    got, refused = 0, {}
    for c in cands:
        if time.time() - t0 > deadline_s or got >= max_dl:
            break
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", c["title"].replace("File:", ""))[:100] + "_" + str(abs(hash(c["url"])) % 10**6)
        raw = os.path.join(out_dir, name + ".jpg")
        host = (re.match(r"https?://([^/]+)", c["url"]) or [None, ""])[1]
        if not os.path.exists(raw):
            # a host that has refused twice in this search is not asked again
            # (it is busy or blocking this address); Openverse's copy is tried
            ok = c.get("source") == "flickr-yfcc" and _fetch(re.sub(r"\.jpg$", "_b.jpg", c["url"]), raw)   # 1024 px
            ok = ok or (refused.get(host, 0) < 2 and _fetch(c["url"], raw, wait_s=5 if deadline_s >= 60 else 0))
            if not ok:
                refused[host] = refused.get(host, 0) + 1
                ok = _via_openverse(c, raw)
            if not ok:
                rejected.append({"file": c["title"], "why": "could not be downloaded"})
                continue
        got += 1
        try:
            im = Image.open(raw).convert("RGB")
            if im.width < 450 or not 1.3 <= im.width / im.height <= 3.8:
                rejected.append({"file": c["title"], "why": f"{im.width}x{im.height}: too small or not a car's shape"})
                continue
            im.thumbnail((1600, 1600))
            sess = sess or new_session("u2net")
            cut = remove(im, session=sess)
            a = np.asarray(cut)[:, :, 3] > 128
            rows, cols = np.where(a.any(1))[0], np.where(a.any(0))[0]
            if not len(rows):
                continue
            if a[:, :2].sum() > 0.05 * a.shape[0] or a[:, -2:].sum() > 0.05 * a.shape[0]:
                rejected.append({"file": c["title"], "why": "the car runs off the edge of the photo"})
                continue
            cut = cut.crop((cols.min(), rows.min(), cols.max() + 1, rows.max() + 1))
            cp = os.path.join(out_dir, "side.cut.png")
            cut.save(cp)
        except Exception:
            continue
        view, asp = finder.classify(cp)
        near_side = view == "34" and 2.0 <= asp < 2.5          # a little turned: check() decides
        why = "not a side view" if view != "side" and not near_side \
            else "liveried or two-tone" if not finder.plain_paint(cp) else check(cp, dims)
        if not why and accept:
            why = accept(dict(c, dated=era(c) == 2), cp)
        if why:
            rejected.append({"file": c["title"], "why": why})
            continue
        photo = os.path.join(out_dir, "photo.jpg")
        im.save(photo, quality=85)
        return {"cutout": cp, "photo": photo, "file": c["title"], "author": c["author"], "licence": c["licence"],
                "page": c["page"], "view": "side" if view == "side" else "nearly side-on", "dated": era(c) == 2, "taken": c.get("taken"),
                "seconds": round(time.time() - t0, 1), "rejected": rejected}
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
