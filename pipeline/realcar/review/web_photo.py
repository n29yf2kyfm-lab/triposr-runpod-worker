"""web_photo.py: the photo review agents' tools. Every car and van's photo is
looked at (a contact sheet), judged, and a poor one (not the car, the wrong
generation, cut off, far away, crowded, a render) replaced by a better one
found by image search (dealer listings, reviews, Flickr): the whole real car
from outside, in daylight, front three-quarter, as a buyer's listing shows it.

    python3 web_photo.py sheet OUT.jpg KEY ...          # photos to judge, 12 a sheet, with what each should be
    python3 web_photo.py info KEY                        # what the car should be; its photo now
    python3 web_photo.py verdict KEY ok|bad "why"        # photo_review.json
    python3 web_photo.py add KEY IMAGE_URL PAGE_URL "title"   # a candidate: downloaded and measured
    python3 web_photo.py choose KEY N --years Y0 Y1 "generation" --colour FAMILY --side left|right
    python3 web_photo.py years KEY Y0 Y1 "generation"    # correct a photo's generation (2100 = still made)

choose takes everything the new photo needs at once (its generation, its
paint, the way it points), so none of it is left for later: the paint is read
from the new photo, the side and colour labels set, and the key put on the
rebuild queue. It refuses a candidate with no whole car in it, and a photo
of another generation than the build it sits beside.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse

import cv2
import numpy as np

import paths
import photo_paint as pp

# not a photo of the car as a buyer sees it: parts shops, renders and press
# wallpapers (often computer-made), toys, games
NOT_HERE = re.compile(r"aliexpress|alibaba|ebayimg.*parts|temu|amazon\.|etsy|netcarshow|wallpaper|render|configurator|"
                      r"diecast|hotwheels|scale-?model|forza|gran-?turismo|concept", re.I)
MIN_FILL = 0.15        # the car's box as a share of the frame: under this it is far off or a detail


def PHOTOS():
    return paths.f("car_photos.json")


def REVIEW():
    return paths.f("photo_review.json")


def CAND(key=None):
    return paths.f("web_cand", key) if key else paths.f("web_cand")


def build_years(key, row=None):
    """[first, last] year of the generation the build stands for (the run's
    row, else the build's own record), last None while still made; None when
    nobody knows."""
    row = row if row is not None else paths.rows()[0].get(key) or {}
    y = row.get("years")
    if not y and row.get("status") == "built" and row.get("asset"):
        y = paths.load(os.path.join(paths.machine_home(), "view", "cars", row["asset"], "record.json")).get("years")
    if not y or not y[0]:
        return None
    return [int(y[0]), int(y[1]) if y[1] else None]


def years_clash(key, y0, y1, row=None):
    """Why photo years Y0-Y1 cannot sit beside KEY's build, or None."""
    b = build_years(key, row)
    if not b:
        return None
    b1 = b[1] or 2100
    if y1 < b[0] or y0 > b1:
        return (f"the build is the {b[0]}-{b[1] or 'on'} generation, and a {y0}-{y1 if y1 < 2100 else 'on'} photo is "
                "another car: find a photo of the build's generation (look at the badge, lamps and grille)")
    return None


def should_be(key):
    t = next((t for t in paths.load(paths.f("targets.json"), []) if t["key"] == key), {})
    r = paths.rows()[0].get(key) or {}
    p = paths.load(PHOTOS()).get(key) or {}
    ph = p.get("photo") or {}
    gen = re.sub(r"<[^>]+>", " ", str(ph.get("generation") or "")).strip()
    yrs, b = ph.get("years"), build_years(key, r)
    return {"request": t.get("request"), "class": t.get("class"), "built_as": r.get("title"),
            "build_is": ("a stand-in for" if r.get("status") == "standin" else "the catalogue's own model of") + f" {r.get('title')}",
            "build_years": f"{b[0]}-{b[1] or 'on'}" if b else None, "photo_generation": gen or None,
            "photo_years": f"{yrs[0]}-{yrs[1]}" if yrs else None, "photo_now": ph.get("file"),
            "photo_from": "image search" if ph.get("web") else "Wikimedia Commons" if ph else None}


def measure(path, key=None):
    """How the photo shows a car: its size in the frame, whether it runs off
    the frame's sides, how wide it is for its height (side and three-quarter
    views are wide, head-on ones narrow), and how well its outline fits the
    build's picture (either side)."""
    img = cv2.imread(path)
    if img is None:
        return {"error": "unreadable"}
    h0, w0 = img.shape[:2]
    s = 480 / max(h0, w0)
    small = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else img
    m = pp.car_mask(small)
    ys, xs = np.nonzero(m)
    if len(ys) < 0.05 * m.size:
        return {"px": [w0, h0], "error": "no car found in it"}
    h, w = m.shape
    # cut off: the car meets a side of the frame along 80% of its height or
    # more (the Insight's, the TGE's). Only touching it was the old test, and
    # a row of parked cars or a kerb behind a whole car touched it (the MG4's,
    # the 206's); at half its height, a dealer's banner or border joined to
    # the outline still did (the 6 Series', the Laguna's)
    bh = ys.max() - ys.min() + 1
    edge = max(int(m[:, :int(0.045 * w) + 1].any(1).sum()), int(m[:, int(0.955 * w):].any(1).sum())) / bh
    out = {"px": [w0, h0], "fill": round((xs.max() - xs.min()) * (ys.max() - ys.min()) / (w * h), 2),
           "wide": round((xs.max() - xs.min()) / max(1, ys.max() - ys.min()), 2),
           "edge": round(edge, 2), "off_frame": bool(edge >= 0.8)}
    hero = key and paths.picture(key)
    if hero:
        a = cv2.imread(hero, cv2.IMREAD_UNCHANGED)
        if a is not None and a.ndim == 3 and a.shape[2] == 4:
            p_, r_ = pp._shape(m), pp._shape(a[:, :, 3] > 128)
            fit = lambda x, y: float((x & y).sum() / max(1, (x | y).sum()))  # noqa: E731
            out["fits_build"] = round(max(fit(p_, r_), fit(p_, r_[:, ::-1])), 2)
    return out


def unfit(m):
    """Why a measured candidate is no photo of a whole car, or None."""
    if m.get("error"):
        return m["error"]
    if m.get("fill", 0) < MIN_FILL:
        return f"the car fills {m['fill']:.0%} of the frame: it is far off, or this is a detail (a wheel, a badge)"
    if m.get("off_frame"):
        return "the car runs off the side of the frame: it is cut off"
    return None


def sheet(out, keys):
    W, H, cells = 400, 250, []
    for k in keys:
        c = np.full((H + 46, W, 3), 255, np.uint8)
        p = paths.photo(k)
        im = cv2.imread(p) if p else None
        if im is not None:
            s = min(W / im.shape[1], H / im.shape[0])
            im = cv2.resize(im, (int(im.shape[1] * s), int(im.shape[0] * s)))
            c[46:46 + im.shape[0], :im.shape[1]] = im
        b = should_be(k)
        cv2.putText(c, k, (3, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 160), 1)
        cv2.putText(c, f"{(b['built_as'] or b['request'] or '')[:44]}", (3, 29), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)
        cv2.putText(c, f"build {b['build_years'] or '?'}  photo {b['photo_years'] or '?'}" + ("  NO PHOTO" if im is None else ""),
                    (3, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)
        cells.append(c)
    while len(cells) % 3:
        cells.append(np.full_like(cells[0], 255))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    cv2.imwrite(out, np.vstack([np.hstack(cells[i:i + 3]) for i in range(0, len(cells), 3)]), [cv2.IMWRITE_JPEG_QUALITY, 82])
    print("wrote", out)


def add(key, url, page, title):
    if NOT_HERE.search(url) or NOT_HERE.search(page or ""):
        return print(json.dumps({"refused": "a parts shop, a render or press wallpaper, a toy or a game: not a photo of the car"}))
    d = CAND(key)
    os.makedirs(d, exist_ok=True)
    with paths.lock("web_photo"):
        cands = paths.load(f"{d}/cands.json", [])
        n = len(cands)
        cands.append({"n": n, "pending": True})
        paths.save(f"{d}/cands.json", cands)
    raw, path = f"{d}/{n}.raw", f"{d}/{n}.jpg"
    # Wikimedia refuses an unnamed browser: its files are fetched as the project's own tools fetch them
    ua = "ExpertCarCheck-GLB/1.0 (car reference photos; https://github.com/n29yf2kyfm-lab/triposr-runpod-worker)" \
        if "wikimedia.org" in url else "Mozilla/5.0"
    r = subprocess.run(["curl", "-sSL", "--max-time", "40", "-A", ua, "-o", raw, url], capture_output=True, text=True)
    if r.returncode or not os.path.exists(raw):
        return print(json.dumps({"error": "could not download: " + (r.stderr or "")[-120:]}))
    try:
        from PIL import Image
        im = Image.open(raw).convert("RGB")
        im.thumbnail((960, 960))
        im.save(path, quality=88)
    except Exception as e:
        return print(json.dumps({"error": f"not an image: {e}"[:120]}))
    finally:
        if os.path.exists(raw):
            os.remove(raw)
    rec = {"n": n, "url": url, "page": page, "title": title, "site": urllib.parse.urlparse(page or url).netloc,
           "path": path, **measure(path, key)}
    rec["unfit"] = unfit(rec)
    with paths.lock("web_photo"):
        cands = paths.load(f"{d}/cands.json", [])
        cands[n] = rec
        paths.save(f"{d}/cands.json", cands)
    print(json.dumps(rec))


class Refused(Exception):
    pass


def choose(key, n, years, generation, colour, side, anyway=None):
    import paint_label
    rows = paths.rows()[0]
    if key not in rows:
        raise Refused(f"{key} is not a key of this run")
    c = next((x for x in paths.load(f"{CAND(key)}/cands.json", []) if x.get("n") == int(n)), None)
    if not c or c.get("pending"):
        raise Refused(f"no downloaded candidate {n} for {key}")
    why = unfit(c)
    if why and not anyway:
        raise Refused(f"candidate {n}: {why}. Choose a photo of the whole car, or add --anyway \"reason\" if you "
                      "looked at it full size and it is right")
    y0, y1 = int(years[0]), int(years[1])
    clash = years_clash(key, y0, y1, rows[key])
    if clash:
        raise Refused(clash)
    if colour not in paint_label.FAMILY:
        raise Refused(f"--colour is one of: {' '.join(paint_label.FAMILY)}")
    if side not in ("left", "right"):
        raise Refused("--side is left (the car's front towards the picture's left edge) or right")
    with paths.lock("web_photo"):
        photos = paths.load(PHOTOS())
        old = photos.get(key) or {}
        keep = paths.f("car_photos_commons")
        os.makedirs(keep, exist_ok=True)
        if paths.photo(key) and not os.path.exists(f"{keep}/{key}.jpg"):
            shutil.copy(paths.photo(key), f"{keep}/{key}.jpg")
            kept = paths.load(f"{keep}/records.json")
            kept[key] = old
            paths.save(f"{keep}/records.json", kept)
        os.makedirs(pp.PH(), exist_ok=True)
        shutil.copy(c["path"], f"{pp.PH()}/{key}.jpg")
        oph = old.get("photo") or {}
        photos[key] = dict(old, photo={
            "file": c["title"], "licence": "not checked (a web image)", "author": c["site"], "url": c["url"], "page": c["page"],
            "taken": None, "ai": False, "web": True, "generation": generation, "years": [y0, y1], "years_from": "photo review",
            "chosen": "image search: a clearer photo than Commons had" + (f" ({anyway})" if anyway else ""), "wiki": oph.get("wiki")})
        paths.save(PHOTOS(), photos)
        mask = f"{pp.MASKS()}/{key}.png"
        if os.path.exists(mask):
            os.remove(mask)
        rv = paths.load(REVIEW())
        rv[key] = dict(rv.get(key) or {}, replaced=c["n"], replaced_at=paths.now())
        paths.save(REVIEW(), rv)
    # the new photo's colour and side, as the agent named them looking at it
    with paths.lock("paint_label"):
        d = paths.load(paint_label.OUT())
        d[key] = colour
        paths.save(paint_label.OUT(), d, indent=0)
    with paths.lock("view_label"):
        lab, view = paths.load(paths.f("view_label.json")), paths.load(paths.f("photo_view.json"))
        lab[key] = view[key] = side
        paths.save(paths.f("view_label.json"), lab, indent=0)
        paths.save(paths.f("photo_view.json"), view, indent=0)
    got = pp.read([key]).get(key) or {}
    paths.queue_rebuild(key, f"new photo ({c['site']}), paint {got.get('hex')}, pointing {side}")
    return {"key": key, "now": c["title"], "site": c["site"], "paint": got.get("hex"), "side": side,
            "years": [y0, y1], "queued": "for a rebuild"}


def set_years(key, y0, y1, generation=None):
    clash = years_clash(key, y0, y1)
    if clash:
        raise Refused(clash + " (or, if the photo is right and the build is another generation, say so in a verdict)")
    with paths.lock("web_photo"):
        photos = paths.load(PHOTOS())
        ph = (photos.get(key) or {}).get("photo")
        if not ph:
            raise Refused(f"no photo for {key}")
        ph["years"] = [y0, y1]
        if generation:
            ph["generation"] = generation
        ph["years_from"] = "photo review"
        paths.save(PHOTOS(), photos)
    return {"key": key, "years": ph["years"], "generation": ph.get("generation")}


def _opt(a, name, n=1):
    if name not in a:
        return None
    i = a.index(name)
    v = a[i + 1:i + 1 + n]
    if len(v) < n:
        raise SystemExit(f"{name} needs {n} value(s)")
    return v if n > 1 else v[0]


def main():
    a = sys.argv[1:]
    if not a:
        raise SystemExit(__doc__)
    try:
        if a[0] == "sheet":
            return sheet(a[1], a[2:])
        if a[0] == "info":
            p = paths.photo(a[1])
            return print(json.dumps(dict(should_be(a[1]), **({"measured": measure(p, a[1])} if p else {})), indent=1))
        if a[0] == "verdict":
            v, why = a[2], a[3] if len(a) > 3 else ""
            if v not in ("ok", "bad"):
                raise Refused("the verdict is ok or bad")
            if v == "bad" and len(why.split()) < 3:
                raise Refused("say why the photo is poor, in a few words")
            with paths.lock("web_photo"):
                rv = paths.load(REVIEW())
                rv[a[1]] = dict(rv.get(a[1]) or {}, verdict=v, why=why, at=paths.now())
                paths.save(REVIEW(), rv)
            return print("recorded", a[1], v)
        if a[0] == "add":
            return add(a[1], a[2], a[3] if len(a) > 3 else "", a[4] if len(a) > 4 else "")
        if a[0] == "choose":
            yrs = _opt(a, "--years", 3)
            if not yrs:
                raise Refused('choose needs --years Y0 Y1 "generation" --colour FAMILY --side left|right')
            out = choose(a[1], a[2], yrs[:2], yrs[2], _opt(a, "--colour"), _opt(a, "--side"), _opt(a, "--anyway"))
            return print(json.dumps(out))
        if a[0] == "years":
            return print(json.dumps(set_years(a[1], int(a[2]), int(a[3]), a[4] if len(a) > 4 else None)))
    except Refused as e:
        print("REFUSED:", e)
        raise SystemExit(2)
    raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
