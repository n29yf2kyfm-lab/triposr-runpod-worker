"""photo_paint.py: each car and van photo's paint colour, for the build to wear.

The car is cut from its background (OpenCV GrabCut, started from the middle
of the frame, where the photos put the car); its body is the mask less the
bottom fifth (tyres, shadow) and the top fifth (roof line, glass); the paint
is the largest of four colour clusters there, read in Lab so a dark car's
glass and a light car's sky are told from its paint by more than brightness,
and read at its lit tone (a white car's shaded side is not grey paint).

    python3 pipeline/realcar/review/photo_paint.py [key ...]      # f1k/photo_paint.json
    python3 pipeline/realcar/review/photo_paint.py --sheet KEYS   # dbg/paint_sheet.jpg: photo, mask, swatch
    python3 pipeline/realcar/review/photo_paint.py --view [key ...]   # f1k/photo_view.json: the side the photo's car points to
"""
import json
import os
import sys

import cv2
import numpy as np

import paths


def PH():
    return paths.f("car_photos")


def OUT():
    return paths.f("photo_paint.json")


def VIEW():
    return paths.f("photo_view.json")


def MASKS():
    return paths.f("photo_mask")          # each photo's cut-out, kept: GrabCut is the slow part


def photo_and_mask(key):
    """The photo (at most 480 px) and its car's cut-out, the cut-out from
    MASKS when it was made before."""
    img = cv2.imread(f"{PH()}/{key}.jpg")
    if img is None:
        return None, None
    s = 480 / max(img.shape[:2])
    img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else img
    f = f"{MASKS()}/{key}.png"
    m = cv2.imread(f, cv2.IMREAD_GRAYSCALE) if os.path.exists(f) and os.path.getmtime(f) >= os.path.getmtime(f"{PH()}/{key}.jpg") else None
    if m is None or m.shape != img.shape[:2]:
        m = car_mask(img)
        os.makedirs(MASKS(), exist_ok=True)
        cv2.imwrite(f, m * 255)
    return img, (m > 0).astype(np.uint8)


def car_mask(img):
    h, w = img.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    rect = (int(w * 0.04), int(h * 0.08), int(w * 0.92), int(h * 0.86))
    bg, fg = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(img, mask, rect, bg, fg, 4, cv2.GC_INIT_WITH_RECT)
    m = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 1, 0).astype(np.uint8)
    # the largest piece only: a car beside it, a kerb, a sign are not this car
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    if n > 1:
        big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        m = (lab == big).astype(np.uint8)
    return m


def paint_of(key):
    img, m = photo_and_mask(key)
    return None if img is None else paint_from(img, m)


def _shape(m):
    ys, xs = np.nonzero(m)
    c = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.uint8)
    return cv2.resize(c, (160, 80), interpolation=cv2.INTER_AREA) > 0


def nose_side(key):
    """The side of the frame the photo's car points to, "left" or "right":
    the studio picture of its build (f1k/hero, taken nose-left) laid on the
    photo's outline as it is and mirrored, the closer fit the side. Then the
    next studio picture is taken from the photo's side (f1k_hero.mjs). None
    when there is no picture yet, or the two fit alike (a side-on photo)."""
    img, m = photo_and_mask(key)
    hero = paths.picture(key)
    if img is None or not hero:
        return None
    h = cv2.imread(hero, cv2.IMREAD_UNCHANGED)
    if m.sum() < 0.05 * m.size or h is None or h.shape[2] < 4:
        return None
    p, r = _shape(m), _shape(h[:, :, 3] > 128)
    fit = lambda a, b: (a & b).sum() / max(1, (a | b).sum())  # noqa: E731
    # the picture's own side as it was taken: a mirrored one (an earlier
    # "right") is mirrored back before the fit
    was = paths.load(VIEW()).get(key)
    if was == "right":
        r = r[:, ::-1]
    same, mirrored = fit(p, r), fit(p, r[:, ::-1])
    if abs(same - mirrored) < 0.03:
        return None
    return "left" if same > mirrored else "right"


def paint_from(img, m):
    """The paint of a car in IMG (BGR) whose pixels MASK marks: a photo's
    GrabCut mask, or a studio picture's alpha (paint_check.py)."""
    ys, xs = np.nonzero(m)
    if len(ys) < 0.05 * m.size:
        return {"rgb": None, "why": "the car could not be cut from its background"}
    y0, y1 = ys.min(), ys.max()
    band = m.copy()
    band[: y0 + int((y1 - y0) * 0.22)] = 0         # roof line and glass
    band[y1 - int((y1 - y0) * 0.3):] = 0           # wheels, tyres and shadow
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    px = lab[band == 1].reshape(-1, 3).astype(np.float32)
    if len(px) < 200:
        return {"rgb": None, "why": "too little of the body in view"}
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
    cv2.setRNGSeed(1)                                # the same photo reads the same each time
    _, labels, centres = cv2.kmeans(px, 4, None, crit, 3, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.ravel(), minlength=4)
    chroma = lambda v: float(np.hypot(v[1] - 128, v[2] - 128))  # noqa: E731
    yy = np.nonzero(band)[0]
    ry = (yy - yy.min()) / max(1, yy.max() - yy.min())       # 0 at the band's top, 1 at its foot
    # a coloured car: the most of its body in one clear colour (a red car's
    # paint, not its black bumpers and grey reflections). All of the body in
    # that hue, its lit and its shaded side; its tone read a little above the
    # middle (the highlights would wash it out, the shade darken it), its hue
    # and strength from its most saturated third (where the paint shows as
    # itself, not greyed by the sky in it)
    coloured = [k for k in range(4) if chroma(centres[k]) > 18 and counts[k] >= 0.2 * counts.sum()]
    if coloured:
        best = max(coloured, key=lambda k: counts[k])
        hue = lambda a, b: np.degrees(np.arctan2(b - 128, a - 128))  # noqa: E731
        C = np.hypot(px[:, 1] - 128, px[:, 2] - 128)
        dh = np.abs((hue(px[:, 1], px[:, 2]) - hue(*centres[best][1:]) + 180) % 360 - 180)
        sel = px[(dh < 25) & (C > 12)]
        Cs = np.hypot(sel[:, 1] - 128, sel[:, 2] - 128)
        vivid = sel[Cs >= np.percentile(Cs, 70)]
        # its middle tone: above it a vivid paint read pale (an orange Micra as
        # salmon, a red Niro as pink: the build review's finding)
        c = np.array([np.percentile(sel[:, 0], 50), np.median(vivid[:, 1]), np.median(vivid[:, 2])], np.float32)
        kind, share = "colour", float(len(sel) / len(px))
    else:
        # black, grey, silver or white: the body as a whole. Dark low on it
        # is trim (cladding, sills, arches), not paint; a car whose middle tone
        # is dark is a dark paint under the sky's reflections (read low), one
        # whose middle tone is light a light paint in and out of shade (read high)
        L = px[:, 0]
        # measured on labelled photos: every dark grey or black car's middle
        # tone was 128 or under (on 0-255), every silver or white car's 132 or over
        dark_car = float(np.median(L)) < 130
        keep = np.ones(len(px), bool)
        dark = L < 70
        if not dark_car and dark.mean() > 0.12 and ry[dark].mean() > ry.mean() + 0.06:
            keep &= ~(dark & (ry > 0.45))       # a light car's black trim, low on it
        Lk = L[keep]
        # a dark paint read a little above its shade (the studio darkens it
        # again), a light one near its lit tone (a white car's shaded side
        # read grey)
        Lp = float(np.percentile(Lk, 40 if dark_car else 85))
        near = keep & (np.abs(L - Lp) < 20)
        # colourless: the sky's blue in a silver or white car is not its paint
        # (they read powder blue), so most of the tint is taken out
        c = np.array([Lp, 128 + 0.3 * (np.median(px[near, 1]) - 128), 128 + 0.3 * (np.median(px[near, 2]) - 128)], np.float32)
        kind, share = "dark" if dark_car else "light", float(keep.mean())
    rgb = cv2.cvtColor(np.uint8([[np.clip(c, 0, 255)]]), cv2.COLOR_LAB2RGB)[0, 0].tolist()
    return {"rgb": rgb, "hex": "#%02x%02x%02x" % tuple(rgb), "kind": kind, "share": round(share, 2)}


def _lab(rgb):
    v = cv2.cvtColor(np.uint8([[rgb]]), cv2.COLOR_RGB2LAB)[0, 0].astype(float)
    return np.array([v[0] * 100 / 255, v[1] - 128, v[2] - 128])


def resolve(reading, family):
    """The paint to build: the reading when it is of the colour the photo was
    labelled by eye (f1k/paint_label.json), else that family's paint. White
    and black are taken as the family's (a shaded white read grey); a silver
    or a colour keeps its reading when close to its family."""
    import paint_label as pl
    ref = pl.FAMILY.get(family)
    if not ref:
        return reading
    rr = [int(ref[i:i + 2], 16) for i in (1, 3, 5)]
    out = {"rgb": rr, "hex": ref, "kind": reading.get("kind"), "family": family, "measured": reading.get("hex"), "from": "family"}
    if not reading.get("rgb") or family in ("white", "pearl-white", "black"):
        return out
    a, b = _lab(reading["rgb"]), _lab(rr)
    ca, cb = np.hypot(*a[1:]), np.hypot(*b[1:])
    dh = abs((np.degrees(np.arctan2(a[2], a[1])) - np.degrees(np.arctan2(b[2], b[1])) + 180) % 360 - 180)
    neutral = family in ("silver", "grey", "dark-grey")
    if neutral:
        # silver, grey, dark grey: a colourless reading near the family's tone
        # (not a sage's or a taupe's, faint as their colour is: a grey reading
        # of the EX40's Sage Green was kept and built a plain grey)
        keep = ca < 12 and abs(a[0] - b[0]) < 12
    else:
        # a colour: the family's hue, near its tone, and nearly as strong (a
        # vivid blue read pale lavender, a red read pink, are not kept)
        keep = dh < 18 and abs(a[0] - b[0]) < 18 and ca >= 0.7 * cb
    if neutral and keep and family == "silver" and a[0] > b[0] + 3:
        # a silver read in bright light (the 3 Series' at #d7dde2): built so,
        # too light for a silver's metal, it showed white in the studio (40 of
        # 140 silvers). Its tone is the family's, a little lighter; its tint kept
        m = np.array([b[0] + 3, a[1], a[2]])
        lab8 = np.array([m[0] * 255 / 100, m[1] + 128, m[2] + 128])
        rgb = cv2.cvtColor(np.uint8([[np.clip(lab8, 0, 255)]]), cv2.COLOR_LAB2RGB)[0, 0].tolist()
        return dict(reading, rgb=rgb, hex="#%02x%02x%02x" % tuple(rgb), family=family, measured=reading.get("hex"),
                    **{"from": "photo, a silver's tone"})
    if neutral:
        return dict(reading, family=family, measured=reading.get("hex"), **{"from": "photo"}) if keep else out
    # a colour: the reading drawn toward its family's paint, a quarter of the
    # way when it is of the family, half when only its hue is (a vivid paint
    # read pastel: the review's salmon orange, pink red, pale mint for sage)
    w = 0.25 if keep else 0.5 if (dh < 40 and ca > 8) else 1.0
    if w == 1.0:
        return out
    m = (1 - w) * a + w * b
    lab8 = np.array([m[0] * 255 / 100, m[1] + 128, m[2] + 128])
    rgb = cv2.cvtColor(np.uint8([[np.clip(lab8, 0, 255)]]), cv2.COLOR_LAB2RGB)[0, 0].tolist()
    return dict(reading, rgb=rgb, hex="#%02x%02x%02x" % tuple(rgb), family=family, measured=reading.get("hex"),
                **{"from": "photo, toward its family" if keep else "photo and family"})
    return out


def sheet(keys, out=None):
    out = out or paths.f("sheets", "paint_sheet.jpg")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    d = paths.load(OUT())
    W, H, rows = 300, 200, []
    for k in keys:
        p = f"{PH()}/{k}.jpg"
        if not os.path.exists(p):
            continue
        img = cv2.imread(p)
        s = W / img.shape[1]
        img = cv2.resize(img, (W, min(H, int(img.shape[0] * s))))
        row = np.full((H + 20, W + 120, 3), 255, np.uint8)
        row[20:20 + img.shape[0], :W] = img
        rgb = (d.get(k) or {}).get("rgb")
        if rgb:
            row[30:H, W + 10:W + 110] = rgb[::-1]
        cv2.putText(row, k[:40], (2, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 1)
        rows.append(row)
    cols = 3
    while len(rows) % cols:
        rows.append(np.full_like(rows[0], 255))
    grid = np.vstack([np.hstack(rows[i:i + cols]) for i in range(0, len(rows), cols)])
    cv2.imwrite(out, grid, [cv2.IMWRITE_JPEG_QUALITY, 80])
    print("wrote", out)


def main():
    a = sys.argv[1:]
    if a and a[0] == "--sheet":
        return sheet(a[1:])
    if a and a[0] == "--view":
        v = paths.load(VIEW())
        keys = a[1:] or sorted(f[:-4] for f in os.listdir(PH()) if f.endswith(".jpg"))
        # a side named by eye (view_label.py) is kept: the outline fit reads a front
        # three-quarter photo the wrong way round about one time in ten
        named = paths.load(paths.f("view_label.json"))
        for k in keys:
            if k in named:
                v[k] = named[k]
                continue
            try:
                v[k] = nose_side(k)
            except Exception:
                v[k] = None
        paths.save(VIEW(), v, indent=0)
        print(len(keys), "photos:", sum(1 for k in keys if v.get(k) == "left"), "nose left,",
              sum(1 for k in keys if v.get(k) == "right"), "right, the rest side-on")
        return
    keys = a or sorted(f[:-4] for f in os.listdir(PH()) if f.endswith(".jpg"))
    d = read(keys, verbose=True)
    print(len(keys), "photos read;", sum(1 for k in keys if (d.get(k) or {}).get("rgb")), "with a paint colour")


def read(keys, verbose=False):
    """Each key's paint read again from its photo now (and its colour label),
    with the photo's fingerprint, so a later change of photo is seen as a
    stale paint (check.py). Returns the whole paint file."""
    import paint_label as pl
    with paths.lock("photo_paint"):
        d = paths.load(OUT())
        labels = paths.load(pl.OUT())
        for n, k in enumerate(keys):
            try:
                d[k] = paint_of(k) or {"rgb": None, "why": "unreadable"}
                if labels.get(k):
                    d[k] = resolve(d[k], labels[k])
            except Exception as e:
                d[k] = {"rgb": None, "why": f"{type(e).__name__}: {e}"[:100]}
            d[k]["photo_sha"] = paths.sha(paths.photo(k))
            d[k]["label"] = labels.get(k)
            if verbose and n % 50 == 0:
                print(n, k, d[k].get("hex") or d[k].get("why"), flush=True)
        paths.save(OUT(), d, indent=0)
    return d


if __name__ == "__main__":
    main()
