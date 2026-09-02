"""
Per-image contamination filters for the damage corpus.

Every filter here was written against contact sheets I read by eye, and each
one targets a defect that provenance alone cannot remove because it also
occurs inside otherwise-good projects:

  grain      additive noise augmentation (Roboflow "noise" export)
  edge_bar   stock-site credit bar along any edge (shutterstock, dreamstime,
             gettyimages, alamy). Checked on all four edges because curacel's
             frames are rotated 90 degrees and carry the bar down the side.
  seam       two photos pasted side by side or top and bottom: a hard,
             full-length edge at the centre of the frame
  baked_box  a detector's prediction rectangles rendered into the pixels

None of them uses OCR. OCR was the previous approach and it read 86 of an
estimated 15% of the corpus, because noise augmentation and mirrored text
defeat it. These look at structure instead.

A first draft of these filters also had "tiled" (autocorrelation for the
repeated alamy watermark) and "composite" (correlation of the two halves).
Both failed validation: tiled missed the real alamy tiles and fired on
grilles and tyre treads, composite could not separate a pasted pair of
different crops from a symmetric real scene. The alamy frames all carry the
bottom credit bar, so edge_bar covers them; seam replaces composite.

Each function returns a float score; thresholds live in FLAGS so they can be
tuned from one place and printed next to the score.
"""
import numpy as np
from PIL import Image, ImageFilter

FLAGS = {
    "grain":     3.0,     # curacel 3-7; gravel lots and textured floors reach 2-3
    "edge_bar":  0.50,
    "seam":      0.80,
    # baked_box and label_tag are recorded as scores but do not flag. Neither
    # survived validation: the box lines cannot be told from chrome trim on a
    # red car, and the label tags are ~4 px tall at corpus resolution while
    # their yellow variant matches Indian number plates. The known residual is
    # about a quarter of the changs project (~1,500 images) carrying rendered
    # prediction boxes -- see audit/project_verdicts.md.
}


def _grey(im, size=320):
    return np.asarray(im.convert("L").resize((size, size)), dtype=np.float32)


def grain(im):
    """Mean |x - median3(x)| inside the flattest quarter of 16x16 blocks.
    A clean photo is near zero on flat paint; injected noise survives the
    median and shows up everywhere, including the flat parts."""
    g = im.convert("L").resize((320, 320))
    a = np.asarray(g, dtype=np.float32)
    med = np.asarray(g.filter(ImageFilter.MedianFilter(3)), dtype=np.float32)
    res = np.abs(a - med)
    B = 16; H = W = 320 // B
    blocks = res.reshape(H, B, W, B).mean(axis=(1, 3))
    grad = np.abs(np.gradient(a)[0]).reshape(H, B, W, B).mean(axis=(1, 3))
    return float(blocks[grad <= np.quantile(grad, 0.25)].mean())


def _bar_score(strip, next_row, last_row):
    """One candidate bar. strip: (h, W) grey rows at the edge, last_row the
    strip's inner row, next_row the first row beyond it.
      step     the boundary is a hard step along (nearly) the whole width --
               a horizon or a floor gives a ragged partial step instead
      uniform  the strip is one colour apart from its text
      text     a small share of pixels sit far from the strip's median
    """
    step = float((np.abs(last_row - next_row) > 25).mean())
    bg = np.median(strip)
    dev = np.abs(strip - bg)
    uniform = float((dev < 20).mean())               # share of pixels that ARE the bar colour
    text = float(((dev > 50).mean()))
    text_ok = 1.0 if 0.005 <= text <= 0.30 else 0.0
    return step * min(1.0, uniform / 0.7) * text_ok


def edge_bar(im):
    a = _grey(im, 400)
    H, W = a.shape
    best = 0.0
    for view in (a, a.T):                              # rows, then columns
        n = view.shape[0]
        for h in (int(n * f) for f in (0.035, 0.05, 0.07, 0.09, 0.12)):
            if h < 4: continue
            top = _bar_score(view[:h], view[h + 1], view[h - 1])
            bot = _bar_score(view[-h:], view[-h - 2], view[-h])
            best = max(best, top, bot)
    return float(best)


def seam(im):
    """Fraction of rows with a hard horizontal step at some column inside the
    middle 8% of the frame (and the transpose for a horizontal seam). Two
    photos pasted together meet in a full-length edge; a real scene almost
    never has one exactly through the centre."""
    a = _grey(im, 320)
    best = 0.0
    for view in (a, a.T):
        n = view.shape[1]; c0, c1 = int(n * 0.46), int(n * 0.54)
        d = np.abs(view[:, c0 + 1:c1 + 1] - view[:, c0:c1])       # (rows, cols)
        best = max(best, float((d > 20).mean(axis=0).max()))
    return best


def baked_box(im):
    """Prediction boxes rendered into the pixels. In the changs project they
    are salmon (about 200,125,120), one pixel wide, with a solid label tag;
    in beena they are yellow. Saturation is NOT the signature -- salmon is
    barely saturated -- the signature is a RENDERED colour: perfectly flat
    along a straight run of >= 20 px, different from the photo on both sides
    of the run, and not grey. A red car body is flat but not thin; a panel
    edge is thin but shaded, never flat for 20 px. Score = share of pixels
    on such runs, summed over the two orientations."""
    from scipy.ndimage import maximum_filter1d, minimum_filter1d
    a = np.asarray(im.convert("RGB"), dtype=np.int16)
    mx = a.max(axis=2); mn = a.min(axis=2)
    notgrey = (mx - mn) > 40
    total = 0.0
    for axis in (1, 0):                       # horizontal runs, then vertical
        L = 20
        span = (maximum_filter1d(a, L, axis=axis) - minimum_filter1d(a, L, axis=axis)).max(axis=2)
        flat = span <= 14                     # same colour for L px along the run
        perp = 1 - axis
        up = np.roll(a, 3, axis=perp); dn = np.roll(a, -3, axis=perp)
        diff_up = np.abs(a - up).max(axis=2) > 25
        diff_dn = np.abs(a - dn).max(axis=2) > 25
        thin = diff_up & diff_dn              # photo on BOTH sides of the line
        total += float((flat & thin & notgrey).mean())
    return total


TAG_COLOURS = (
    ((200, 125, 120), 22),    # changs: salmon "minor-scratch 0.43" tags
    ((235, 215, 40), 40),     # beena: yellow tags
)


def label_tag(im):
    """Count of solid label tags: a 6-row x 24-col block of ONE rendered tag
    colour. baked_box (above) scores the thin box lines but cannot be told
    from chrome trim on a red car; the tag block is unmistakable because no
    car panel is a flat rectangle of exactly that colour. Two colours were
    observed in the corpus; add to TAG_COLOURS if another shows up."""
    from scipy.ndimage import minimum_filter, label
    a = np.asarray(im.convert("RGB"), dtype=np.int16)
    n = 0
    for (r, g, b), tol in TAG_COLOURS:
        m = (np.abs(a - np.array([r, g, b])).max(axis=2) <= tol)
        block = minimum_filter(m, size=(6, 24))
        if block.any():
            n += int(label(block)[1])
    return float(n)


def score_all(path):
    """The three flagging filters. baked_box and label_tag are not run here:
    they work on the full 640 px frame and cost more than the other three
    together, for a score that does not flag."""
    im = Image.open(path)
    im.load()
    return {"grain": grain(im), "edge_bar": edge_bar(im), "seam": seam(im)}


def flags(scores):
    return [k for k, t in FLAGS.items() if scores[k] >= t]
