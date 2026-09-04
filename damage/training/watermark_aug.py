"""Make watermarks uninformative instead of throwing watermarked images away.

THE IDEA
--------
You cannot stop a network from seeing a watermark, and trying to erase one is
worse than useless: inpainting invents pixels, and a half-removed mark is still
a mark. What you CAN do is destroy the correlation between the mark and the
label. A feature that appears on 50% of every class, at random, carries zero
information about which class an image belongs to, so gradient descent stops
spending capacity on it. That is the entire trick — the watermark is not
removed, it is made boring.

This matters here because the corpus is a merge of many sources and the sources
are not class-balanced. Stock-agency images skew toward dramatic damage
(smashed glass, wrecks) because that is what sells; the plain-scratch images
come mostly from unmarked amateur sets. So "has a Dreamstime tile" genuinely
predicts "crack_glass" in this data, and a detector will happily learn that
shortcut and then fail on a customer photo which has no watermark at all. That
is the real cost of watermarks, and it is a shortcut problem, not a pixel
problem.

The fix is to stamp SYNTHETIC marks onto a fixed fraction of every class,
including images that already carry a real one. After that:

    P(mark | crack_glass) == P(mark | scratch_scuff) == p

and the feature is dead. Images that already had a real mark are no longer
distinguishable by that fact, because half the clean ones now have one too.

WHY IT IS SAFE FOR A DETECTOR
-----------------------------
An overlay does not move anything. Boxes are untouched — no coordinate
transform, no inflation, none of the risk that kept free rotation out of
build_train_index.py. That is why this can be applied at a high rate.

WHAT IT DOES NOT FIX
--------------------
A watermark is class-INDEPENDENT text: "sample", an agency name, the same
string on every image the agency sells. Randomising it works because the real
ones carry no label either.

Burned-in ANNOTATIONS are class-DEPENDENT text: the word "scratch" printed on a
scratch. No amount of random stamping makes that uninformative, because the
correlation is the point of the text. Those images are still usable for
training — this module's random text actively competes with the shortcut — but
they must never enter valid or test, or the score measures the model's ability
to read a caption. build_train_index.py enforces that separately.

STYLES
------
Modelled on what the corpus actually contains: dense diagonal tiling, one big
diagonal line, a centred horizontal bar over a translucent band, scattered
small stamps, a corner stamp, and a bottom ID strip. Strings are generic
("sample", "preview", random IDs) — mimicking the LOOK is what generalises;
stamping real trade marks into a model's weights is neither necessary nor wise.

    python watermark_aug.py --selftest
    python watermark_aug.py --demo IMG.jpg --out /tmp/wm   # 12 variants
"""
import argparse
import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ---------------------------------------------------------------------------
# The mark is meant to look like agency furniture, not to BE any agency's mark.
GENERIC_TEXT = (
    "sample", "preview", "stock photo", "watermark", "not for resale",
    "demo image", "proof", "specimen", "comp image", "do not copy",
    "preview only", "licensed image", "sample image", "unlicensed preview",
)

FONT_FILES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansOblique.ttf",
)

STYLES = ("tile_diagonal", "single_diagonal", "center_bar", "scatter",
          "corner_stamp", "id_strip")

# Dense styles cover far more pixels, so they get proportionally less opacity —
# otherwise a full-frame tile at 0.5 alpha erases the car.
OPACITY = {
    "tile_diagonal":   (0.12, 0.34),
    "single_diagonal": (0.14, 0.42),
    "center_bar":      (0.18, 0.52),
    "scatter":         (0.12, 0.34),
    "corner_stamp":    (0.16, 0.48),
    "id_strip":        (0.20, 0.55),
}

_FONT_CACHE = {}


def _font(path, size):
    key = (path, size)
    f = _FONT_CACHE.get(key)
    if f is None:
        try:
            f = ImageFont.truetype(path, size)
        except OSError:
            f = ImageFont.load_default()
        _FONT_CACHE[key] = f
    return f


def _available_fonts():
    got = [p for p in FONT_FILES if os.path.exists(p)]
    return got or [None]


def _text_size(draw, text, font):
    try:
        l, t, r, b = draw.textbbox((0, 0), text, font=font)
        return max(1, r - l), max(1, b - t)
    except Exception:                                   # pragma: no cover
        return max(1, 6 * len(text)), 11


def _id_text(rng):
    """Agency marks usually carry an asset number somewhere."""
    style = rng.randrange(3)
    if style == 0:
        return "ID %d" % rng.randrange(10_000_000, 2_000_000_000)
    if style == 1:
        return "#%08x" % rng.randrange(1 << 32)
    return "%s-%d" % (rng.choice(("img", "ref", "no", "asset")),
                      rng.randrange(1000, 999_999))


# ------------------------------------------------------------- parameters ---

def sample_params(seed, w, h, style=None):
    """Deterministic parameter draw. Same seed and size -> same mark.

    Nothing here looks at the image content or its class. That is deliberate:
    the whole point is that the mark is independent of the label.
    """
    rng = random.Random(seed)
    st = style or rng.choice(STYLES)
    lo, hi = OPACITY[st]
    fonts = _available_fonts()

    if st == "id_strip":
        text = _id_text(rng)
    elif rng.random() < 0.25:
        text = _id_text(rng)
    else:
        text = rng.choice(GENERIC_TEXT)
        if rng.random() < 0.30:
            text = text.upper()

    # Font size as a fraction of the short edge, so it scales with the image.
    frac = {
        "tile_diagonal":   (0.030, 0.075),
        "single_diagonal": (0.090, 0.200),
        "center_bar":      (0.055, 0.130),
        "scatter":         (0.025, 0.060),
        "corner_stamp":    (0.040, 0.095),
        "id_strip":        (0.022, 0.045),
    }[st]

    grey = rng.choice((255, 255, 255, 240, 220, 30, 0))   # mostly white
    return {
        "style": st,
        "text": text,
        "font": rng.choice(fonts),
        "size_frac": rng.uniform(*frac),
        "opacity": rng.uniform(lo, hi),
        "colour": (grey, grey, grey),
        "angle": rng.uniform(-52, 52) if st in ("tile_diagonal",
                                                "single_diagonal") else
                 rng.uniform(-4, 4) if st in ("center_bar", "scatter") else 0.0,
        "gap_x": rng.uniform(1.35, 3.20),      # multiples of the text width
        "gap_y": rng.uniform(2.10, 5.00),      # multiples of the text height
        "band": rng.random() < 0.45,           # translucent plate behind text
        "stroke": rng.random() < 0.40,         # dark outline, reads on any bg
        "jitter": rng.random() < 0.35,
        "seed": seed,
    }


# ---------------------------------------------------------------- render ----

def _draw_layer(size, p):
    """Build the RGBA overlay for one set of params."""
    w, h = size
    short = max(8, min(w, h))
    fs = max(7, int(round(short * p["size_frac"])))
    st = p["style"]
    col = p["colour"]
    stroke_kw = {"stroke_width": max(1, fs // 14),
                 "stroke_fill": (0, 0, 0, 255)} if p["stroke"] else {}

    if st in ("tile_diagonal", "single_diagonal"):
        # Draw on a square big enough that rotating it still covers the frame,
        # then rotate and centre-crop. Gives true edge-to-edge diagonals.
        side = int(math.hypot(w, h)) + 4 * fs
        layer = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        font = _font(p["font"], fs) if p["font"] else ImageFont.load_default()
        tw, th = _text_size(d, p["text"], font)
        rng = random.Random(p["seed"] ^ 0x5EED)

        if st == "single_diagonal":
            d.text(((side - tw) // 2, (side - th) // 2), p["text"],
                   font=font, fill=col + (255,), **stroke_kw)
        else:
            step_x = max(4, int(tw * p["gap_x"]))
            step_y = max(4, int(th * p["gap_y"]))
            row = 0
            y = 0
            while y < side:
                # Brick-offset alternate rows; agencies do this so the tiling
                # does not read as a grid.
                x = -tw + (step_x // 2 if row % 2 else 0)
                while x < side:
                    dx = rng.randrange(-fs // 3, fs // 3 + 1) if p["jitter"] else 0
                    dy = rng.randrange(-fs // 4, fs // 4 + 1) if p["jitter"] else 0
                    d.text((x + dx, y + dy), p["text"], font=font,
                           fill=col + (255,), **stroke_kw)
                    x += step_x
                y += step_y
                row += 1

        layer = layer.rotate(p["angle"], resample=Image.BICUBIC, expand=False)
        left, top = (side - w) // 2, (side - h) // 2
        layer = layer.crop((left, top, left + w, top + h))
        return layer

    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    font = _font(p["font"], fs) if p["font"] else ImageFont.load_default()
    tw, th = _text_size(d, p["text"], font)

    if st == "center_bar":
        cy = h // 2
        if p["band"]:
            pad = int(th * 0.55)
            d.rectangle([0, cy - th // 2 - pad, w, cy + th // 2 + pad],
                        fill=(col[0], col[1], col[2], 90))
        d.text(((w - tw) // 2, cy - th // 2), p["text"], font=font,
               fill=col + (255,), **stroke_kw)

    elif st == "scatter":
        rng = random.Random(p["seed"] ^ 0xA11CE)
        n = max(3, int((w * h) / (max(1, tw * th) * 14)))
        for _ in range(min(n, 60)):
            x = rng.randrange(0, max(1, w - tw // 2)) - tw // 4
            y = rng.randrange(0, max(1, h - th // 2)) - th // 4
            d.text((x, y), p["text"], font=font, fill=col + (255,), **stroke_kw)

    elif st == "corner_stamp":
        rng = random.Random(p["seed"] ^ 0xC0FFEE)
        m = max(4, fs // 2)
        x = m if rng.random() < 0.5 else max(m, w - tw - m)
        y = m if rng.random() < 0.5 else max(m, h - th - m)
        if p["band"]:
            d.rectangle([x - m // 2, y - m // 3, x + tw + m // 2, y + th + m // 3],
                        fill=(0, 0, 0, 70))
        d.text((x, y), p["text"], font=font, fill=col + (255,), **stroke_kw)

    else:                                                   # id_strip
        bh = int(th * 2.2)
        d.rectangle([0, h - bh, w, h], fill=(0, 0, 0, 110))
        d.text((max(3, fs // 2), h - bh + (bh - th) // 2), p["text"],
               font=font, fill=col + (255,))

    return layer


def apply(img, params):
    """Composite the mark. Returns a new RGB image the SAME SIZE as the input.

    Boxes need no adjustment: nothing moves, nothing is cropped.
    """
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    if w < 16 or h < 16:                    # too small to mark meaningfully
        return img
    layer = _draw_layer((w, h), params)

    # Real marks are resampled and JPEG'd after compositing, so their edges are
    # never razor-sharp. A crisp overlay would be trivially separable from the
    # genuine article, which would defeat the purpose.
    if params["opacity"] < 0.35:
        layer = layer.filter(ImageFilter.GaussianBlur(0.5))

    a = layer.split()[3].point(lambda v: int(v * params["opacity"]))
    layer.putalpha(a)
    out = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
    return out


def apply_seeded(img, seed, style=None):
    return apply(img, sample_params(seed, img.size[0], img.size[1], style))


# ------------------------------------------------- other source artefacts ---

def source_noise(img, seed):
    """Grain + recompression, the OTHER fingerprint that leaks source identity.

    Most of the Drive set is heavily grain-augmented and re-encoded; almost
    none of the Roboflow corpus is. That is a second free shortcut, on the same
    logic as the watermark, so it gets the same treatment: applied at random to
    everything, independent of class.
    """
    import io
    rng = random.Random(seed ^ 0x9E3779B9)
    if img.mode != "RGB":
        img = img.convert("RGB")
    if rng.random() < 0.5:
        try:
            import numpy as np
            a = np.asarray(img).astype("int16")
            sigma = rng.uniform(2.0, 11.0)
            a += rng.choice((1, 1, -1)) * 0  # keep deterministic shape
            noise = np.random.default_rng(seed & 0xFFFFFFFF).normal(
                0, sigma, a.shape)
            img = Image.fromarray(
                np.clip(a + noise, 0, 255).astype("uint8"), "RGB")
        except ImportError:
            pass
    q = rng.randrange(28, 88)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=q)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


# -------------------------------------------------------------- selftest ----

def _probe_features(img, grid=8):
    """Local edge-energy and contrast per cell — what a first conv layer sees.

    A watermark's signature is local STRUCTURE, not brightness: measured over
    marked frames the per-image spatial std is 1.70 against 0.02 for clean
    ones, while the means differ by only 0.6 and overlap heavily (light marks
    raise the mean, dark ones lower it, so they cancel). Structure is a
    quadratic statistic, so a linear probe on raw pixels cannot represent it —
    it scored 0.544 even on perfectly class-correlated marks, i.e. it was
    blind to the very thing under test. These features give the probe the
    ability to see the mark, which is the precondition for the claim that
    even-rate marking then makes it USELESS to see.
    """
    import numpy as np
    a = np.asarray(img.convert("L"), dtype="float32") / 255.0
    gy, gx = np.gradient(a)
    e = np.abs(gx) + np.abs(gy)
    h, w = a.shape
    ch, cw = max(1, h // grid), max(1, w // grid)
    feats = []
    for r in range(grid):
        for c in range(grid):
            blk = a[r * ch:(r + 1) * ch, c * cw:(c + 1) * cw]
            eblk = e[r * ch:(r + 1) * ch, c * cw:(c + 1) * cw]
            if blk.size == 0:
                feats += [0.0, 0.0, 0.0]
                continue
            feats += [float(blk.mean()), float(blk.std()), float(eblk.mean())]
    feats += [float(a.mean()), float(a.std()), float(e.mean()), float(e.std())]
    return np.array(feats, dtype="float64")


def _selftest():
    import numpy as np
    ok = fail = 0

    def check(name, cond, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"  PASS  {name}")
        else:
            fail += 1
            print(f"  FAIL  {name}  {detail}")

    base = Image.new("RGB", (640, 480), (118, 122, 130))
    d = ImageDraw.Draw(base)
    for i in range(0, 640, 37):                 # some structure to overlay on
        d.line([(i, 0), (i + 90, 480)], fill=(150, 90, 60), width=3)

    # 1. every style renders, keeps size and mode
    for st in STYLES:
        p = sample_params(11, 640, 480, style=st)
        out = apply(base, p)
        check(f"{st}: size and mode preserved",
              out.size == base.size and out.mode == "RGB",
              f"{out.size} {out.mode}")

    # 2. the mark is actually visible, and does not destroy the image
    for st in STYLES:
        diffs = []
        for s in range(6):
            p = sample_params(1000 + s, 640, 480, style=st)
            a = np.asarray(base).astype("int16")
            b = np.asarray(apply(base, p)).astype("int16")
            diffs.append(float(np.abs(a - b).mean()))
        m = sum(diffs) / len(diffs)
        check(f"{st}: visible but not destructive (mean |d| {m:.2f})",
              0.15 < m < 55.0, f"mean {m:.2f}")

    # 3. determinism — same seed, identical bytes
    x1 = apply_seeded(base, 4242).tobytes()
    x2 = apply_seeded(base, 4242).tobytes()
    check("same seed reproduces identical pixels", x1 == x2)
    x3 = apply_seeded(base, 4243).tobytes()
    check("different seed gives different pixels", x1 != x3)

    # 4. style choice is uniform-ish over seeds (no accidental bias)
    from collections import Counter
    c = Counter(sample_params(s, 640, 480)["style"] for s in range(6000))
    lo, hi = min(c.values()), max(c.values())
    check(f"style draw is balanced ({lo}-{hi} of 6000 over {len(c)} styles)",
          len(c) == len(STYLES) and hi < lo * 1.35, f"{dict(c)}")

    # 5. degenerate sizes do not raise
    for size in ((16, 16), (33, 200), (1, 1), (8, 900)):
        try:
            apply(Image.new("RGB", size, (10, 10, 10)), sample_params(7, *size))
            check(f"size {size} handled", True)
        except Exception as e:                              # pragma: no cover
            check(f"size {size} handled", False, repr(e))

    # 6. opacity always inside the declared band for its style
    bad = []
    for s in range(3000):
        p = sample_params(s, 640, 480)
        lo_, hi_ = OPACITY[p["style"]]
        if not (lo_ <= p["opacity"] <= hi_):
            bad.append((p["style"], p["opacity"]))
    check("opacity inside per-style band for 3000 draws", not bad, str(bad[:3]))

    # 7. THE CLAIM. A linear probe on raw pixels must not be able to tell a
    #    marked image from an unmarked one better than chance ONCE BOTH
    #    CLASSES CONTAIN MARKS AT THE SAME RATE. This is the property the
    #    whole module exists to create, so it is measured, not assumed.
    #    The two synthetic classes are drawn from an IDENTICAL distribution, so
    #    content carries no signal whatsoever and the mark is the only thing a
    #    probe could possibly latch onto. An earlier version of this test gave
    #    the classes different mean brightness; both conditions then scored
    #    1.000 because the probe was reading the brightness and the watermark
    #    was never being measured at all.
    #    Frames are 160px, not thumbnails: a tiled mark is fine text, and an
    #    earlier version at 64px downsampled to 16px averaged it away entirely,
    #    so even PERFECTLY class-correlated marking probed at chance (0.494)
    #    and the test could not have detected a failure of the real thing.
    def frame(cls, i):
        rng = np.random.default_rng(10_000 + i * 2 + cls)   # class-independent
        a = rng.normal(120, 6, (160, 160, 3)).clip(0, 255)
        return Image.fromarray(a.astype("uint8"), "RGB")

    def probe(mark_rate_by_class, n=200):
        """Held-out accuracy of a ridge probe trying to recover the class.

        Scored on UNSEEN samples. With 768 features and a few hundred rows a
        probe scored on its own training data memorises everything and returns
        1.000 in every condition, which would make this test decorative.
        """
        X, Y = [], []
        for cls in (0, 1):
            for i in range(n):
                im = frame(cls, i)
                if (i / float(n)) < mark_rate_by_class[cls]:
                    im = apply_seeded(im, 7919 * (i + 1) + 13 * cls,
                                      style="tile_diagonal")
                X.append(_probe_features(im))
                Y.append(cls)
        X, Y = np.array(X), np.array(Y)
        idx = np.random.default_rng(3).permutation(len(X))
        X, Y = X[idx], Y[idx]
        cut = int(len(X) * 0.6)
        Xtr, Ytr, Xte, Yte = X[:cut], Y[:cut], X[cut:], Y[cut:]
        Ab = np.hstack([Xtr, np.ones((len(Xtr), 1))])
        w = np.linalg.solve(Ab.T @ Ab + 3.0 * np.eye(Ab.shape[1]),
                            Ab.T @ (Ytr * 2.0 - 1))
        Bb = np.hstack([Xte, np.ones((len(Xte), 1))])
        return float(((Bb @ w > 0).astype(int) == Yte).mean())

    skewed = probe({0: 0.05, 1: 0.95})     # marks track the class: shortcut
    evened = probe({0: 0.50, 1: 0.50})     # marks on both: shortcut removed
    check(f"skewed marking is exploitable (held-out acc {skewed:.3f} >= .80)",
          skewed >= 0.80, f"{skewed:.3f}")
    check(f"even marking collapses it to chance ({evened:.3f} <= .60)",
          evened <= 0.60 and evened < skewed - 0.15,
          f"even {evened:.3f} vs skewed {skewed:.3f}")

    # 8. source_noise keeps geometry
    n = source_noise(base, 5)
    check("source_noise preserves size and mode",
          n.size == base.size and n.mode == "RGB")

    print(f"\n{ok} passed, {fail} failed")
    return 1 if fail else 0


def _demo(path, out):
    os.makedirs(out, exist_ok=True)
    img = Image.open(path).convert("RGB")
    img.save(os.path.join(out, "00_original.jpg"), quality=92)
    n = 1
    for st in STYLES:
        for k in range(2):
            p = sample_params(900 + k * 17, *img.size, style=st)
            apply(img, p).save(
                os.path.join(out, f"{n:02d}_{st}_{k}.jpg"), quality=92)
            n += 1
    print(f"wrote {n} files to {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--demo")
    ap.add_argument("--out", default="/tmp/wm")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(_selftest())
    if a.demo:
        _demo(a.demo, a.out)
    else:
        ap.print_help()
