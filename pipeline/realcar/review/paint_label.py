"""paint_label.py: each photo's paint named by eye (the colour agents), so the
measured colour (photo_paint.py) is kept only when it is that colour: a white
car read as grey from its shade, a silver one read as charcoal, a navy one read
as black are given their family's paint instead.

    python3 paint_label.py sheet OUT.jpg KEY ... [--batch NAME] [--gold N]   # photos, 12 a sheet
    python3 paint_label.py label "KEY=family KEY=family ..."
    python3 paint_label.py families

A label is read into the photo's paint at once (photo_paint.py), and a key
whose paint changes goes to the rebuild queue: a new colour is never left
waiting on someone remembering it. A sheet's labels are refused together when
one of them is wrong on a photo checked by hand, with the reason.
"""
import os
import sys

import cv2
import numpy as np

import gold
import paths

# each family's paint as a maker sells it (sRGB): what the build wears when the
# measured colour is not of the family the photo shows
FAMILY = {
    "white": "#eeefed", "pearl-white": "#e9e6dd", "silver": "#c4c7ca", "grey": "#80858a", "dark-grey": "#46494e",
    "black": "#141518", "dark-blue": "#1d2a4a", "blue": "#2a5aa6", "light-blue": "#79a6d2", "turquoise": "#1d8a8c",
    "red": "#b3131c", "dark-red": "#6b1421", "orange": "#e2601d", "yellow": "#efc21a", "gold": "#b9973e",
    "green": "#2d7a34", "dark-green": "#1e3a2a", "light-green": "#a3b884", "brown": "#5b3e2b", "bronze": "#8b6b49",
    "beige": "#cbbb9b", "champagne": "#c2b190", "purple": "#5a2a6c", "lilac": "#a89bb9",
    # the muted ones: a steel or slate blue, a sage or grey-green, a taupe
    # (the build review's: each was painted its family's vivid colour)
    "grey-blue": "#566c86", "grey-green": "#617863", "taupe": "#7d6a5b",
}


def OUT():
    return paths.f("paint_label.json")


def sheet(out, keys, batch=None, n_gold=0, kind="paint", ask="name the colour of each"):
    """Photos 12 a sheet, each under its key, with N_GOLD checked photos of KIND among them."""
    keys = gold.mix(keys, kind, n_gold, out, batch) if n_gold else list(keys)
    if not n_gold:
        gold.note_sheet(out, batch, keys, [])
    W, H, cells = 400, 250, []
    for k in keys:
        c = np.full((H + 26, W, 3), 255, np.uint8)
        p = paths.photo(k)
        im = cv2.imread(p) if p else None
        if im is not None:
            s = min(W / im.shape[1], H / im.shape[0])
            im = cv2.resize(im, (int(im.shape[1] * s), int(im.shape[0] * s)))
            c[26:26 + im.shape[0], :im.shape[1]] = im
        cv2.putText(c, k, (3, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 170), 2)
        cells.append(c)
    while len(cells) % 3:
        cells.append(np.full_like(cells[0], 255))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    cv2.imwrite(out, np.vstack([np.hstack(cells[i:i + 3]) for i in range(0, len(cells), 3)]), [cv2.IMWRITE_JPEG_QUALITY, 82])
    print("wrote", out, f"({len(keys)} photos: {ask})")


def parse(pairs, allowed):
    got, bad = {}, []
    for p in pairs.split():
        k, _, v = p.partition("=")
        (got.__setitem__(k, v) if k and v in allowed else bad.append(p))
    return got, bad


def gold_misses(kind, got):
    """The labels in GOT that are wrong on a checked photo, as messages; every
    answer on a checked photo is logged."""
    out = []
    for k, v in got.items():
        g = gold.judge(kind, k, v)
        if g is None:
            continue
        gold.log(kind, k, v, g["right"])
        if not g["right"]:
            out.append(f"{k}: you said {v}, but it was checked by hand as {g['expected']} ({g['why']})")
    return out


def label(pairs, read_paint=True):
    got, bad = parse(pairs, FAMILY)
    if bad:
        raise SystemExit(f"not recorded: {bad} are not KEY=family with a family from: {' '.join(FAMILY)}")
    rows = paths.rows()[0]
    unknown = [k for k in got if k not in rows]
    if unknown:
        raise SystemExit(f"not recorded: {unknown} are no keys of this run (copy them exactly from the sheet)")
    miss = gold_misses("paint", got)
    if miss:
        print("REFUSED (none of these labels recorded):\n  " + "\n  ".join(miss) +
              "\nLook again at every photo on this sheet: name the body's paint in daylight, not its shade, its "
              "reflections or its black trim. Then record the sheet's labels again.")
        raise SystemExit(2)
    with paths.lock("paint_label"):
        d = paths.load(OUT())
        d.update(got)
        paths.save(OUT(), d, indent=0)
    paths.labelled("colour", list(got))
    if read_paint:
        import photo_paint
        pp = photo_paint.read(list(got))
        for k in got:
            if rows[k].get("paint") and (pp.get(k) or {}).get("hex") and pp[k]["hex"] != rows[k]["paint"]:
                paths.queue_rebuild(k, f"paint now {pp[k]['hex']} (built {rows[k]['paint']})")
    print(f"{len(got)} labelled")


def main():
    a = sys.argv[1:]
    if a and a[0] == "sheet":
        batch = a[a.index("--batch") + 1] if "--batch" in a else None
        n = int(a[a.index("--gold") + 1]) if "--gold" in a else 0
        keys = [x for i, x in enumerate(a[2:], 2) if not x.startswith("--") and a[i - 1] not in ("--batch", "--gold")]
        return sheet(a[1], keys, batch, n)
    if a and a[0] == "label":
        return label(" ".join(a[1:]))
    if a and a[0] == "families":
        return print(" ".join(FAMILY))
    raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
