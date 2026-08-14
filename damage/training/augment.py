"""Apply one index row to one image. The half of build_train_index.py that
actually touches pixels.

build_train_index.py emits recipes as NAMES — ["hflip", "crop"] — and says the
training loader owns the implementation. Nothing implemented it, so the index
was a plan no one carried out: `wm` was a field in a file that no code read,
and no watermark would have reached the network. This is that loader.

CONTRACT
--------
    img_out, boxes_out = apply_row(img, boxes, row)

`boxes` are normalised [x, y, w, h] in [0, 1], as written by images.jsonl.
Boxes come back normalised against the NEW image, so a caller never has to know
which ops moved anything.

Order matters and is fixed:

    geometry (hflip, crop)  ->  photometric  ->  blur/sharpen  ->  wm  ->  sn

Geometry first because only geometry moves boxes, and doing it first means the
box arithmetic is over before any appearance op runs. The watermark goes on
near the end because that is where a real one goes — an agency stamps the
finished frame — and stamping before a crop would let the crop slice the mark
into a fragment no real image would ever contain. `sn` (grain and JPEG) comes
last for the same reason: it is what the file suffers on its way out.

BOX SAFETY
----------
Every op either has an exact box transform or provably has none:

    hflip        x -> 1 - x - w                        exact
    crop         translate + rescale, then clip        exact
    photometric  no geometric change                   none needed
    blur         no geometric change                   none needed
    sharpen      no geometric change                   none needed
    wm           overlay only, nothing moves           none needed
    sn           overlay only, nothing moves           none needed

Rotation is absent, deliberately — see the note in build_train_index.py.

A crop can push a box mostly out of frame. A box surviving with a sliver of its
original area is a lie: the label says "dent" while the pixels show a corner of
one. Anything retaining less than MIN_BOX_KEEP of its area is dropped, and if a
crop would empty an image of boxes the crop is abandoned and the original
returned. A training image with no boxes teaches a detector that a damaged car
is undamaged.

    python augment.py --selftest
"""
import argparse
import random

from PIL import Image, ImageEnhance, ImageFilter

import watermark_aug as WA

# Below this share of its pre-crop area, a clipped box is no longer the thing
# it is labelled as.
MIN_BOX_KEEP = 0.35

CROP_SCALE = (0.62, 0.95)      # side length as a fraction of the original


def _clip01(v):
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def hflip(img, boxes):
    out = img.transpose(Image.FLIP_LEFT_RIGHT)
    return out, [[1.0 - x - w, y, w, h] for (x, y, w, h) in boxes]


def _keep_all(boxes):
    return list(range(len(boxes)))


def crop(img, boxes, rng):
    """Random window, resized back to the original size.

    Returns the input untouched if the window would destroy every box.
    """
    W, H = img.size
    for _ in range(8):                      # a few tries before giving up
        s = rng.uniform(*CROP_SCALE)
        cw, ch = max(8, int(W * s)), max(8, int(H * s))
        if cw >= W and ch >= H:
            continue
        x0 = rng.randint(0, max(0, W - cw))
        y0 = rng.randint(0, max(0, H - ch))
        fx0, fy0 = x0 / W, y0 / H
        fw, fh = cw / W, ch / H

        kept, kept_idx = [], []
        for bi, (x, y, w, h) in enumerate(boxes):
            nx0 = _clip01((x - fx0) / fw)
            ny0 = _clip01((y - fy0) / fh)
            nx1 = _clip01((x + w - fx0) / fw)
            ny1 = _clip01((y + h - fy0) / fh)
            nw, nh = nx1 - nx0, ny1 - ny0
            if nw <= 0 or nh <= 0:
                continue
            # area is compared in the ORIGINAL frame's units, so the resize
            # back to (W, H) cannot flatter the survival ratio
            before = w * h
            after = (nw * fw) * (nh * fh)
            if before > 0 and after / before < MIN_BOX_KEEP:
                continue
            kept.append([nx0, ny0, nw, nh])
            kept_idx.append(bi)

        if boxes and not kept:
            continue
        out = img.crop((x0, y0, x0 + cw, y0 + ch)).resize((W, H),
                                                          Image.BILINEAR)
        return out, kept, kept_idx
    return img, boxes, _keep_all(boxes)


def photometric(img, rng):
    for cls, lo, hi in ((ImageEnhance.Brightness, 0.72, 1.32),
                        (ImageEnhance.Contrast, 0.72, 1.35),
                        (ImageEnhance.Color, 0.60, 1.40)):
        img = cls(img).enhance(rng.uniform(lo, hi))
    return img


def blur(img, rng):
    return img.filter(ImageFilter.GaussianBlur(rng.uniform(0.4, 1.6)))


def sharpen(img, rng):
    return img.filter(ImageFilter.UnsharpMask(
        radius=rng.uniform(1.0, 2.5), percent=int(rng.uniform(60, 190)),
        threshold=3))


def apply_row(img, boxes, row, with_indices=False):
    """Apply one index.jsonl row. Pure function of (img, boxes, row).

    With with_indices=True returns (img, boxes, keep) where `keep` gives, for
    each surviving box, its position in the INPUT list. A caller carrying class
    ids alongside the boxes needs that: a crop can drop a box from the middle,
    and matching survivors back by position then shifts every id after it, so
    the classes silently rotate. Re-rendering box-by-box to find out is not an
    alternative — crop() retries when a window would lose a box, which advances
    the RNG by a different amount per box and hands each one a DIFFERENT crop
    window from the image they are all stored against.
    """
    rng = random.Random(row.get("seed", 0))
    recipe = row.get("recipe") or []
    if img.mode != "RGB":
        img = img.convert("RGB")
    boxes = [list(b) for b in boxes]

    if "hflip" in recipe:
        img, boxes = hflip(img, boxes)
    keep = _keep_all(boxes)
    if "crop" in recipe:
        img, boxes, kidx = crop(img, boxes, rng)
        keep = [keep[i] for i in kidx]
    if "photometric" in recipe:
        img = photometric(img, rng)
    if "blur" in recipe:
        img = blur(img, rng)
    if "sharpen" in recipe:
        img = sharpen(img, rng)

    # Independent of class and of recipe — see build_train_index.mark_flags.
    if row.get("wm"):
        img = WA.apply_seeded(img, (row.get("seed", 0) ^ 0x5713A9) & 0xFFFFFFFF)
    if row.get("sn"):
        img = WA.source_noise(img, (row.get("seed", 0) ^ 0x2C91B) & 0xFFFFFFFF)

    boxes = [[_clip01(x), _clip01(y), _clip01(w), _clip01(h)]
             for (x, y, w, h) in boxes]
    final, fkeep = [], []
    for b, k in zip(boxes, keep):
        if b[2] > 0 and b[3] > 0:
            final.append(b)
            fkeep.append(k)
    if with_indices:
        return img, final, fkeep
    return img, final


# -------------------------------------------------------------- selftest ----

def _selftest():
    ok = fail = 0

    def check(name, cond, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"  PASS  {name}")
        else:
            fail += 1
            print(f"  FAIL  {name}  {detail}")

    # A synthetic frame with a bright square whose position is known exactly,
    # so a box transform can be verified against the PIXELS rather than against
    # the arithmetic that produced it.
    def marked(w=400, h=300, bx=0.60, by=0.20, bw=0.15, bh=0.20):
        im = Image.new("RGB", (w, h), (30, 30, 30))
        px = im.load()
        for yy in range(int(by * h), int((by + bh) * h)):
            for xx in range(int(bx * w), int((bx + bw) * w)):
                px[xx, yy] = (255, 0, 0)
        return im, [[bx, by, bw, bh]]

    def found(im):
        """Normalised bbox of the red patch, measured from the image."""
        import numpy as np
        a = np.asarray(im)
        m = (a[:, :, 0] > 150) & (a[:, :, 1] < 110) & (a[:, :, 2] < 110)
        if not m.any():
            return None
        ys, xs = m.nonzero()
        H, W = m.shape
        return [xs.min() / W, ys.min() / H,
                (xs.max() - xs.min() + 1) / W, (ys.max() - ys.min() + 1) / H]

    def close(a, b, tol=0.035):
        return a and b and all(abs(u - v) <= tol for u, v in zip(a, b))

    # 1. hflip: the claimed box must land on the actual red patch
    im, bx = marked()
    o, nb = apply_row(im, bx, {"recipe": ["hflip"], "seed": 1})
    check(f"hflip box tracks the pixels  claim={[round(v,3) for v in nb[0]]} "
          f"actual={[round(v,3) for v in found(o)]}",
          close(nb[0], found(o)))

    # 2. hflip twice is the identity
    o2, nb2 = apply_row(o, nb, {"recipe": ["hflip"], "seed": 2})
    check("hflip is its own inverse", close(nb2[0], bx[0], 0.01),
          f"{nb2[0]} vs {bx[0]}")

    # 3. crop: box must still track the pixels, over many seeds
    bad = []
    for s in range(60):
        im, bx = marked()
        o, nb = apply_row(im, bx, {"recipe": ["crop"], "seed": s})
        if not nb:
            bad.append((s, "no boxes"))
            continue
        f = found(o)
        if not close(nb[0], f, 0.05):
            bad.append((s, [round(v, 3) for v in nb[0]],
                        [round(v, 3) for v in f]))
    check(f"crop box tracks the pixels over 60 seeds ({60-len(bad)}/60)",
          not bad, str(bad[:3]))

    # 4. a crop never empties an image of boxes
    empties = 0
    for s in range(300):
        im, bx = marked(bx=0.02, by=0.02, bw=0.08, bh=0.08)   # awkward corner
        _o, nb = apply_row(im, bx, {"recipe": ["crop"], "seed": s})
        empties += (len(nb) == 0)
    check("crop never returns an image with zero boxes", empties == 0,
          f"{empties} empty of 300")

    # 5. appearance-only ops leave boxes exactly alone
    for op in ("photometric", "blur", "sharpen"):
        im, bx = marked()
        _o, nb = apply_row(im, bx, {"recipe": [op], "seed": 5})
        check(f"{op} leaves boxes untouched", nb == bx, f"{nb} vs {bx}")

    # 6. wm and sn move nothing
    im, bx = marked()
    o, nb = apply_row(im, bx, {"recipe": [], "wm": True, "sn": True, "seed": 9})
    check("wm+sn leave boxes untouched", nb == bx, f"{nb} vs {bx}")
    check("wm+sn preserve image size", o.size == im.size)

    # 7. wm actually changed the pixels (a no-op would be a silent failure —
    #    the index would say `wm` and nothing would be stamped)
    import numpy as np
    a = np.asarray(apply_row(im, bx, {"recipe": [], "seed": 9})[0]).astype(int)
    b = np.asarray(o).astype(int)
    check(f"wm+sn actually alter pixels (mean |d| {np.abs(a-b).mean():.2f})",
          np.abs(a - b).mean() > 0.5)

    # 8. determinism
    p = {"recipe": ["hflip", "crop", "photometric"], "wm": True, "sn": True,
         "seed": 777}
    r1 = apply_row(*marked(), p)
    r2 = apply_row(*marked(), p)
    check("same row reproduces identical pixels and boxes",
          r1[0].tobytes() == r2[0].tobytes() and r1[1] == r2[1])

    # 9. every recipe in the index's cycle runs, keeps size, keeps boxes valid
    import build_train_index as B
    for rec in B.RECIPES:
        im, bx = marked()
        o, nb = apply_row(im, bx, {"recipe": list(rec), "wm": True, "seed": 3})
        good = (o.size == im.size and nb
                and all(0 <= v <= 1 for v in nb[0])
                and nb[0][2] > 0 and nb[0][3] > 0)
        check(f"recipe {rec} produces a valid sample", good, f"{nb}")

    # 10. multi-box: a box that leaves the frame is dropped, one that stays is
    #     kept — not silently clipped to a sliver
    im = Image.new("RGB", (400, 300), (30, 30, 30))
    boxes = [[0.45, 0.45, 0.10, 0.10], [0.00, 0.00, 0.04, 0.04]]
    slivers = 0
    for s in range(120):
        _o, nb = apply_row(im, boxes, {"recipe": ["crop"], "seed": s})
        for bb in nb:
            if bb[2] < 1e-3 or bb[3] < 1e-3:
                slivers += 1
    check("no degenerate sliver boxes survive a crop", slivers == 0,
          f"{slivers} slivers")

    print(f"\n{ok} passed, {fail} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(_selftest())
    ap.print_help()
