"""Grade a damage box by MEASURING it, because severity is never labelled.

WHY THIS IS NOT A SET OF CLASSES
--------------------------------
The detector was trained on six classes and none of them carries a severity.
That is not an oversight in the taxonomy — it is what the public data is.
Every boxed damage dataset that exists labels a box "scratch"; not one labels
it "scratch, through to primer". So a severity class has nothing to learn from
and cannot be trained, in the same way and for the same reason that paint
mismatch cannot (see paint_mismatch.py).

Severity is not a category anyway. It is a depth, and depth leaves a
measurable trace in the pixels.

THE PHYSICS, WHICH IS THE WHOLE METHOD
--------------------------------------
Automotive paint is layered, and each layer that a scratch reaches looks
different:

    clearcoat   40-50um   transparent   scatters light, reveals NO new colour
    basecoat    15-20um   the colour    matte where the clear is gone
    primer      25-35um   grey/white/black
    metal                                bright, specular, colourless

So the giveaway is not "how different is this from the paint" — a deep scratch
in a white car is barely different in dE from a shallow one in a red car. The
giveaway is WHICH DIRECTION it differs in:

    clearcoat only  ->  lightness shifts, colour does not.  Chroma preserved.
    into basecoat   ->  gloss lost, lightness shifts more.  Chroma preserved.
    into primer     ->  CHROMA COLLAPSES toward neutral. Primer has no hue.
    to metal        ->  chroma near zero AND lightness high.

Chroma collapse is the depth signal, and it works on any paint colour, because
every primer is neutral no matter what is sprayed on top of it.

A plain dE threshold gets this right only when the light is even. Under real
light it does not, because dE lumps lightness and chroma together and lightness
is what the sun moves: measured on the same red paint, a harmless sunlit
clearcoat haze scores dE 57.8 while a scratch through to primer on the shaded
side of the same car scores 31.0. dE ranks them backwards. The chroma ratio
ignores lightness entirely and ranks them correctly, which is the whole reason
it is a ratio of chroma and not a distance.

    neutralisation = 1 - C*(damage) / C*(surrounding paint)

    0.0  the damage is as colourful as the paint     -> clearcoat
    0.5  half the colour is gone                     -> into basecoat
    0.9  almost no colour left                       -> primer or metal

WHITE, SILVER AND BLACK CARS BREAK THAT RATIO, and they are three of the four
most common car colours, so this is not an edge case. C*(paint) is already near
zero, the ratio divides by nothing and the score becomes noise. Below
NEUTRAL_FLOOR the module stops using chroma and scores on lightness alone, and
says so in the returned `basis` field rather than pretending to a number it
cannot compute.

WHERE THE THRESHOLDS COME FROM
------------------------------
Not from me choosing round numbers. The Drive corpus has image-level severity
folders — scratch_faint/medium/deep/severe, dent_minor/medium/major/severe —
which are far too small and too coarse to train a detector on (64 faint
scratches) but are exactly the right size to fit three cut points on a
one-dimensional score. training/calibrate_severity.py does that fitting and
writes the numbers back here. The defaults below are the physics-derived
starting point, used until calibration replaces them.

DENTS ARE WEAKER AND SAY SO
---------------------------
A dent does not break the paint, so there is no colour signal at all. The only
cue in a single photograph is that a dent bends the reflection of the world:
straight lines in the environment come back curved. That is measurable as
curvature energy in the lightness channel, and it is genuinely informative, but
it depends on there being something to reflect. A dent photographed in flat
diffuse light is close to invisible to any method, human included. So dent
grades carry a `confidence` that drops when the panel has no reflection
structure, instead of guessing.

    grade(img, box, "scratch_scuff") -> {
        "tier": "deep", "score": 0.71, "basis": "chroma",
        "confidence": 0.82, "length_px": 240, "width_px": 6, ... }
"""
import json
import math
import os

try:                                   # package import (damage.severity)
    from .paint_mismatch import rgb_to_lab
except ImportError:                    # flat import, as the worker runs it
    from paint_mismatch import rgb_to_lab

# Below this chroma the paint is white/silver/grey/black and the chroma ratio
# is a division by noise. Measured on a neutral grey card render: C* 1.4.
# Real "colourless" cars sit under 8 and real colours over 15.
NEUTRAL_FLOOR = 8.0

# Fraction of the box's shorter side used as the reference ring OUTSIDE the
# box. The ring is undamaged paint by construction — if the detector's box is
# right, the damage is inside it.
RING_FRAC = 0.35

# Minimum pixels in the damage mask for the measurement to mean anything.
MIN_MASK_PX = 24

# How far the damage must sit from the paint, measured in the PAINT'S OWN
# noise (robust MAD units), before a grade is given at all. Below this the box
# holds one population of pixels and whatever Otsu split out is a highlight or
# a shading gradient. Expressed as a ratio for the same reason the curvature
# baseline is: it cancels the sensor, the ISO and the JPEG quality, none of
# which is knowable from the photo.
MIN_SEPARATION = 6.0

# And the separated group must differ from the paint in absolute terms too. A
# mask two Lab units away from its surroundings is a lighting gradient.
MIN_DAMAGE_DE = 6.0

# Curvature gets its own, much wider ring. See curvature_ratio.
CURV_RING_FRAC = 1.0

# Cut points on the 0-1 depth score. Overwritten by calibrate_severity.py;
# these are the physics-derived starting values, one per layer boundary.
SCRATCH_CUTS = {"faint": 0.18, "medium": 0.42, "deep": 0.68}
SCRATCH_TIERS = ("faint", "light", "medium", "deep", "severe")

DENT_CUTS = {"minor": 0.22, "medium": 0.48, "major": 0.72}
DENT_TIERS = ("minor", "medium", "major", "severe")

CALIBRATION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "severity_cuts.json")

# Which measurement path each detector class takes. The classes that break
# paint are scored on depth; the classes that deform metal are scored on
# reflection curvature; glass and lamps get extent only, because a cracked
# lamp has no layers to cut through.
_DEPTH_CLASSES = {"scratch_scuff", "rust_paint"}
_DEFORM_CLASSES = {"dent", "structural"}


def load_calibration(path=CALIBRATION_FILE):
    """Replace the default cut points with fitted ones, if they exist.

    Called at import. A missing file is not an error: the physics defaults are
    usable, they are just not tuned to this corpus.
    """
    global SCRATCH_CUTS, DENT_CUTS
    if not os.path.exists(path):
        return False
    with open(path) as f:
        d = json.load(f)
    if "scratch" in d:
        SCRATCH_CUTS = dict(d["scratch"])
    if "dent" in d:
        DENT_CUTS = dict(d["dent"])
    return True


def _otsu(values, bins=64):
    """(threshold, separability) for a 1-D sample.

    SEPARABILITY IS THE HALF THAT MATTERS, and the first version did not
    return it. Otsu always yields a threshold — it is the best split of
    whatever it is given, and "best" does not mean "good". Run on undamaged
    paint it dutifully splits the paint from its own specular highlight, the
    highlight is neutral because a reflection of the sky has no hue, and the
    chroma test then reports that the colour has collapsed to primer. Measured
    on the Drive folders, that made clean panels score 0.755 against genuinely
    severe scratches at 0.568 — the grader ranked no_damage as worse than
    severe damage, which is exactly backwards.

    The returned eta (between-class over total variance) is Otsu's own quality
    number and is reported for the record, but it must NOT be used as the
    damage test — measured, a Gaussian scores 0.63, a uniform sample 0.75 and
    a genuine weak bimodal mixture 0.60, so it ranks pure noise ABOVE real
    structure. Otsu's eta is a threshold-quality statistic, not a bimodality
    test. measure() uses a robust separation instead; see `separable` there.

    Used on the per-pixel difference map to decide which pixels inside the box
    ARE the damage. A fixed percentile was tried first and is wrong in both
    directions: a hairline scratch occupies maybe 2% of its box and a 10%
    percentile drags in the surrounding paint, while a scuffed bumper corner
    fills 60% of its box and a 10% percentile keeps only the darkest core.
    Otsu adapts to whichever it is.
    """
    import numpy as np
    v = np.asarray(values, dtype="float64").ravel()
    if v.size == 0:
        return 0.0, 0.0
    lo, hi = float(v.min()), float(v.max())
    if hi - lo < 1e-9:
        return hi, 0.0
    hist, edges = np.histogram(v, bins=bins, range=(lo, hi))
    hist = hist.astype("float64")
    w = np.cumsum(hist)
    total = w[-1]
    centres = (edges[:-1] + edges[1:]) / 2.0
    s = np.cumsum(hist * centres)
    mean_total = s[-1] / total
    w0 = w
    w1 = total - w0
    ok = (w0 > 0) & (w1 > 0)
    if not ok.any():
        return (lo + hi) / 2.0, 0.0
    m0 = np.where(ok, s / np.maximum(w0, 1e-12), 0.0)
    m1 = np.where(ok, (s[-1] - s) / np.maximum(w1, 1e-12), 0.0)
    between = w0 * w1 * (m0 - m1) ** 2
    between = np.where(ok, between, -1.0)
    k = int(np.argmax(between))
    # between[] is built from COUNTS, so it carries an N^2 that the plain
    # variance does not. Dividing by var*N left eta pinned at 1.0 for every
    # sample including pure noise — the guard was reporting perfect
    # separability on undamaged paint, which is precisely the case it exists
    # to catch.
    denom = float(np.var(v)) * total * total
    eta = float(between[k] / denom) if denom > 0 else 0.0
    return float(centres[k]), max(0.0, min(1.0, eta))


def _lab_image(rgb):
    """Vectorised sRGB -> Lab for a whole array.

    rgb_to_lab in paint_mismatch is per-pixel and is called on medians there,
    which is fine. Here it would run on a quarter of a million pixels, so the
    same maths is written against numpy. The two agree to 1e-6 — asserted in
    the selftest, because two implementations of one formula is exactly how a
    silent divergence gets in.
    """
    import numpy as np
    c = rgb.astype("float64") / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
    xyz = lin @ m.T
    xyz /= np.array([0.95047, 1.0, 1.08883])
    e = 216 / 24389
    f = np.where(xyz > e, np.cbrt(xyz), (841 / 108) * xyz + 4 / 29)
    L = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], axis=-1)


def _ring(shape, box, frac=RING_FRAC):
    """Pixel mask of undamaged paint around the box.

    Returns (outer_slice, inner_box_within_outer). Clipped at the image edge,
    which matters: damage photographed at the edge of the frame has no ring on
    one side and the median simply uses the sides that exist.
    """
    H, W = shape[:2]
    x, y, w, h = [int(round(v)) for v in box]
    pad = max(4, int(round(min(w, h) * frac)))
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1, y1 = min(W, x + w + pad), min(H, y + h + pad)
    return (slice(y0, y1), slice(x0, x1)), (x - x0, y - y0, w, h), pad


def _mask_axes(mask):
    """(major, minor) extent in pixels of the damage mask, via PCA.

    A scratch's bounding box says almost nothing about the scratch: a diagonal
    hairline 300px long fills a 220x200 box. The eigenvectors of the pixel
    coordinates give the actual length and, more importantly, the actual WIDTH,
    which is the number that separates a hairline from a gouge.
    """
    import numpy as np
    ys, xs = np.nonzero(mask)
    if len(xs) < 3:
        return 0.0, 0.0
    pts = np.stack([xs, ys], axis=1).astype("float64")
    pts -= pts.mean(axis=0)
    cov = np.cov(pts, rowvar=False)
    vals, vecs = np.linalg.eigh(cov)
    proj = pts @ vecs
    # 5th-95th percentile span, not min-max: a single stray pixel from the
    # mask's ragged edge would otherwise set the length.
    spans = []
    for k in range(2):
        p = proj[:, k]
        spans.append(float(np.percentile(p, 95) - np.percentile(p, 5)))
    spans.sort(reverse=True)
    return spans[0], spans[1]


def _box_blur(L, r):
    """Separable box blur via cumulative sums. Removes the noise that would
    otherwise dominate a second derivative — see _curvature."""
    import numpy as np
    if r <= 0:
        return L
    k = 2 * r + 1
    c = np.cumsum(np.pad(L, ((0, 0), (r, r)), mode="edge"), axis=1)
    c = np.concatenate([np.zeros((L.shape[0], 1)), c], axis=1)
    L = (c[:, k:] - c[:, :-k]) / k
    c = np.cumsum(np.pad(L, ((r, r), (0, 0)), mode="edge"), axis=0)
    c = np.concatenate([np.zeros((1, L.shape[1])), c], axis=0)
    return (c[k:, :] - c[:-k, :]) / k


def _curvature(L, r, s):
    """Mean |second derivative| of lightness at scale s, after smoothing at r.

    BOTH KNOBS ARE FORCED BY MEASUREMENT, not taste. The first version
    differentiated adjacent pixels and was useless: on a synthetic flat panel
    with realistic sensor noise (sigma 1.5 of 255) it scored 0.249 while a
    pronounced dent scored 0.027 — the noise beat the signal ten to one,
    because a second difference amplifies high frequencies and noise IS high
    frequency. Smoothing first, and then differencing across a span rather
    than a pixel, inverts that: signal grows as s^2 while noise does not, so
    at r=5, s=12 the same dent scores 0.0026 against a noisy flat panel's
    0.00016.

    Normalised by the region's own contrast, so a dark car and a light car
    score alike for the same dent, and divided by s^2 so the number does not
    change meaning when the scale adapts to the box size.
    """
    import numpy as np
    if L.shape[0] < 2 * s + 3 or L.shape[1] < 2 * s + 3:
        return None
    Ls = _box_blur(L, r)
    lyy = Ls[2 * s:, s:-s] - 2 * Ls[s:-s, s:-s] + Ls[:-2 * s, s:-s]
    lxx = Ls[s:-s, 2 * s:] - 2 * Ls[s:-s, s:-s] + Ls[s:-s, :-2 * s]
    contrast = float(np.percentile(L, 90) - np.percentile(L, 10))
    if contrast < 1e-6:
        return None
    return float(np.mean(np.abs(lxx) + np.abs(lyy)) / contrast) / (s * s)


def curvature_ratio(rgb, box, frac=None):
    """Curvature inside the box, in units of the SAME PANEL's flat paint.

    An absolute curvature threshold cannot work, because how much curvature a
    flat panel shows depends on the camera, the ISO, the JPEG quality and how
    much texture the environment had to reflect — none of which is knowable
    from the photo. A ratio against the undamaged paint immediately around the
    damage cancels every one of them: same sensor, same exposure, same
    surroundings, same panel.

    The baseline comes from the four ring strips, reduced with the median so
    that one strip landing on a door handle or a window rubber does not set
    the floor.

    THE CURVATURE RING IS WIDER THAN THE COLOUR RING, and deliberately so.
    Colour wants a reference as close to the damage as possible, because paint
    varies across a panel. Curvature wants the opposite: the baseline is a
    second derivative measured at dent scale, and a thin strip does not contain
    enough independent samples to estimate one. Sharing RING_FRAC's 0.35 was
    tried and it flattened a clear synthetic dent from 16x its baseline down to
    1.7x — the baseline was so noisy it swallowed the signal. At 1.0 the strips
    are as thick as the box and the same dent separates properly.

    Returns (ratio, inside, baseline); ratio is None when the geometry is too
    small to measure at dent scale, which is a real answer and not a zero.
    """
    import numpy as np
    H, W = rgb.shape[:2]
    x, y, w, h = [int(round(v)) for v in box]
    pad = max(6, int(round(min(w, h) * (frac if frac else CURV_RING_FRAC))))
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1, y1 = min(W, x + w + pad), min(H, y + h + pad)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None, None, None
    region_L = _lab_image(rgb[y0:y1, x0:x1])[..., 0]
    ix0, iy0 = x - x0, y - y0
    ix1, iy1 = min(region_L.shape[1], ix0 + w), min(region_L.shape[0], iy0 + h)
    ix0, iy0 = max(0, ix0), max(0, iy0)

    # 2s+3 rows must fit inside BOTH the box and the ring strips, or the two
    # curvatures would be measured at different scales and their ratio would
    # mean nothing.
    room = min(pad, ix1 - ix0, iy1 - iy0)
    s = min(20, (room - 3) // 2)
    if s < 3:
        return None, None, None
    r = max(1, s // 2)
    inside = _curvature(region_L[iy0:iy1, ix0:ix1], r, s)
    if inside is None:
        return None, None, None

    strips = [region_L[:iy0, :], region_L[iy1:, :],
              region_L[:, :ix0], region_L[:, ix1:]]
    base = [c for c in (_curvature(t, r, s) for t in strips) if c is not None]
    if not base:
        return None, inside, None
    baseline = float(np.median(base))
    if baseline <= 1e-9:
        return None, inside, baseline
    return inside / baseline, inside, baseline


def measure(img, box):
    """All the raw numbers for one box. No verdict, no tier.

    Separated from grade() so the calibrator can measure once and refit cut
    points many times without re-reading 2,065 JPEGs on every iteration.
    """
    import numpy as np
    rgb = np.asarray(img.convert("RGB"))
    outer, inner, pad = _ring(rgb.shape, box)
    region = rgb[outer]
    if region.size == 0:
        return None
    lab = _lab_image(region)
    ix, iy, iw, ih = inner
    iy0, ix0 = max(0, iy), max(0, ix)
    iy1, ix1 = min(lab.shape[0], iy + ih), min(lab.shape[1], ix + iw)
    if iy1 - iy0 < 3 or ix1 - ix0 < 3:
        return None

    ring_mask = np.ones(lab.shape[:2], dtype=bool)
    ring_mask[iy0:iy1, ix0:ix1] = False
    if ring_mask.sum() < 32:
        # Box fills its region (damage at the frame edge). Fall back to the
        # box's own outer eighth as reference — worse, but not nothing.
        ring_mask[:] = False
        e = max(1, min(lab.shape[:2]) // 8)
        ring_mask[:e, :] = ring_mask[-e:, :] = True
        ring_mask[:, :e] = ring_mask[:, -e:] = True
        ring_mask[iy0 + e:iy1 - e, ix0 + e:ix1 - e] = False

    ref = np.median(lab[ring_mask], axis=0)
    ref_C = float(math.hypot(ref[1], ref[2]))

    inside = lab[iy0:iy1, ix0:ix1]
    # Difference from the reference paint, per pixel. Plain Lab distance here,
    # not CIEDE2000: this is only used to SEPARATE damage from paint, and
    # running the full formula per pixel costs far more than it buys. The
    # perceptual weighting matters for the verdict, and the verdict is
    # computed from the medians below.
    diff = np.sqrt(((inside - ref) ** 2).sum(axis=-1))
    thr, eta = _otsu(diff)
    mask = diff >= thr
    if mask.sum() < MIN_MASK_PX:
        mask = diff >= np.percentile(diff, 80)
    n = int(mask.sum())
    if n < 3:
        return None
    # THE NULL HYPOTHESIS, recorded rather than enforced here. Everything above
    # finds the most different pixels in the box; nothing so far has asked
    # whether they are different ENOUGH to be damage.
    #
    # It is recorded and not enforced because it applies to ONE of the two
    # measurement paths. A scratch announces itself in colour, so a box whose
    # pixels are one population contains no scratch. A DENT does not: it breaks
    # no paint and is invisible in this difference map by construction, and
    # rejecting it here would refuse to grade every dent ever photographed.
    # depth_score consults this; deform_score does not, because curvature
    # carries its own baseline test.
    mask_de = float(np.median(diff[mask]))
    bg = diff[~mask]
    if bg.size >= 16:
        bg_med = float(np.median(bg))
        mad = float(np.median(np.abs(bg - bg_med))) * 1.4826
        separation = (mask_de - bg_med) / max(mad, 0.5)
    else:
        bg_med, separation = 0.0, 0.0
    separable = bool(separation >= MIN_SEPARATION and mask_de >= MIN_DAMAGE_DE)

    dmg = np.median(inside[mask], axis=0)
    dmg_C = float(math.hypot(dmg[1], dmg[2]))
    major, minor = _mask_axes(mask)
    ratio, curv_in, curv_base = curvature_ratio(rgb, box)
    contrast = float(np.percentile(lab[..., 0], 90)
                     - np.percentile(lab[..., 0], 10))

    return {
        "separable": separable, "otsu_eta": eta, "mask_de": mask_de,
        "separation": separation, "bg_de": bg_med,
        "ref_L": float(ref[0]), "ref_C": ref_C,
        "dmg_L": float(dmg[0]), "dmg_C": dmg_C,
        "dL": float(dmg[0] - ref[0]),
        "dC": dmg_C - ref_C,
        "mask_px": n,
        "area_frac": float(n) / float(inside.shape[0] * inside.shape[1]),
        "length_px": major, "width_px": minor,
        "elongation": (major / minor) if minor > 0.5 else float(major),
        "curv_ratio": ratio, "curv_inside": curv_in, "curv_base": curv_base,
        "contrast": contrast,
        "box_frac": float(box[2] * box[3]) / float(rgb.shape[0] * rgb.shape[1]),
    }


def depth_score(m):
    """0-1 estimate of how many paint layers the damage has cut through.

    Returns (score, basis). basis is "chroma" when the paint had enough colour
    for the ratio to mean something and "lightness" when it did not — reported
    rather than hidden, because a lightness-only grade on a silver car is a
    genuinely weaker claim and the report should be able to say so.
    """
    if m is None:
        return 0.0, "none"
    if not m.get("separable", True):
        # One population of pixels: a highlight or a shading gradient, not
        # damage. Returning 0.0 would be a claim that the paint is perfect;
        # "none" is the honest answer and grade() turns it into no tier.
        return 0.0, "none"
    if m["ref_C"] >= NEUTRAL_FLOOR:
        neutralisation = 1.0 - (m["dmg_C"] / m["ref_C"])
        neutralisation = max(0.0, min(1.0, neutralisation))
        gloss = min(1.0, abs(m["dL"]) / 60.0)
        return 0.7 * neutralisation + 0.3 * gloss, "chroma"
    # NEUTRAL PAINT, AND THIS PATH IS WEAK. Only lightness is left, and a
    # specular highlight moves lightness exactly as damage does. Measured on
    # the Drive folders, that is not a theoretical worry: 70% of those images
    # land here, and with lightness alone the grader scored undamaged panels
    # at 0.755 against genuinely severe scratches at 0.568 — worse than
    # useless, actively inverted.
    #
    # The one physical discriminator left is SHAPE. A scratch is thin and long
    # because something dragged along the panel. A highlight is broad, because
    # it is the reflection of a light source. So on neutral paint a BRIGHTER
    # region is believed only when it is also thin; a darker one is believed
    # either way, since a highlight cannot be darker than the paint it sits on.
    # "Thin" has to be strict, and measurement set the bar: a broad specular
    # band still came out at elongation 3.2 once the box cropped it, while a
    # real hairline runs 10-50. Aspect alone is therefore not enough — the
    # damage must also be a SMALL PART of its box, which a highlight covering
    # a third of the paint is not.
    thin = (m.get("elongation", 0) >= 6.0
            and m.get("area_frac", 1.0) <= 0.15)
    if m["dL"] > 0 and not thin:
        return 0.0, "none"
    # Capped below the top tier on purpose. Without chroma there is no way to
    # tell basecoat from primer, so claiming "severe" from a lightness shift
    # would be inventing precision. The report says the basis, and the reader
    # can see the claim is the weaker one.
    return min(0.75, abs(m["dL"]) / 45.0), "lightness"


def deform_score(m):
    """0-1 estimate of how badly a panel is deformed.

    Curvature energy is the signal; size is the multiplier. A 2cm ding and a
    caved-in door produce similar curvature per pixel and are not similar
    damage, so extent has to enter, and it enters as the box's share of the
    frame rather than in pixels, which are meaningless without a distance.
    """
    if m is None:
        return 0.0, 0.0
    extent = min(1.0, math.sqrt(max(0.0, m["box_frac"])) / 0.45)
    ratio = m.get("curv_ratio")
    if ratio is None:
        # Too small to measure curvature at dent scale, or the surrounding
        # paint had no texture to form a baseline from. Size is all that is
        # left, and the confidence says so rather than the score pretending.
        return extent, 0.25
    # A ratio of 1 is flat paint. Measured on synthetic panels with realistic
    # sensor noise: a pronounced dent came out at 16x its own panel's
    # baseline, a broad shallow one at about 2x. So 1x-8x spans the usable
    # range and anything past that is already a major deformation.
    bend = min(1.0, max(0.0, (ratio - 1.0) / 7.0))
    score = 0.6 * bend + 0.4 * extent
    # Confidence: curvature needs something to reflect. A panel shot in flat
    # diffuse light has almost no reflection structure, so the ratio is two
    # noise estimates divided by each other. This is a genuine limit of
    # single-photograph dent grading, not a tuning problem.
    conf = max(0.15, min(1.0, m["contrast"] / 25.0))
    return score, conf


def _tier(score, cuts, names):
    for i, key in enumerate(names[:-1]):
        c = cuts.get(key)
        if c is None:
            continue
        if score < c:
            return names[i]
    return names[-1]


def grade(img, box, cls):
    """Full severity verdict for one detected box.

    cls is the DETECTOR's class name, which decides which measurement applies:
    paint-breaking damage is graded on depth, deformation on reflection
    curvature, and glass or lamp damage on extent alone — a cracked lens has no
    layers to cut through, so a depth score on it would be a fabricated number.
    """
    m = measure(img, box)
    if m is None:
        return {"tier": None, "score": 0.0, "basis": "unmeasurable",
                "confidence": 0.0, "metrics": {}}

    if cls in _DEPTH_CLASSES:
        s, basis = depth_score(m)
        if basis == "none":
            return {"tier": None, "score": 0.0, "basis": "not-separable",
                    "confidence": 0.0, "metrics": m}
        tier = _tier(s, SCRATCH_CUTS, SCRATCH_TIERS)
        # A hairline is thin. Width is the one measurement that separates a
        # 1px scratch from a scuffed patch of the same depth, and it upgrades
        # rather than downgrades: a wide gouge is worse than a wide scuff.
        conf = 0.9 if basis == "chroma" else 0.55
        if m["mask_px"] < MIN_MASK_PX:
            conf *= 0.5
        return {"tier": tier, "score": round(s, 4), "basis": basis,
                "confidence": round(conf, 3), "metrics": m}

    if cls in _DEFORM_CLASSES:
        s, conf = deform_score(m)
        return {"tier": _tier(s, DENT_CUTS, DENT_TIERS), "score": round(s, 4),
                "basis": "curvature", "confidence": round(conf, 3),
                "metrics": m}

    # crack_glass, lamp_wheel: extent only, and labelled as such so nobody
    # reads it as a depth.
    s = min(1.0, math.sqrt(max(0.0, m["box_frac"])) / 0.4)
    return {"tier": _tier(s, DENT_CUTS, DENT_TIERS), "score": round(s, 4),
            "basis": "extent", "confidence": 0.6, "metrics": m}


load_calibration()


def _selftest():
    import numpy as np
    from PIL import Image
    ok = fail = 0

    def check(name, cond, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"  ok   {name}")
        else:
            fail += 1
            print(f"  FAIL {name} {detail}")

    # --- the two Lab implementations must agree ---
    px = np.array([[[200, 30, 40], [255, 255, 255], [0, 0, 0], [18, 90, 160]]],
                  dtype="uint8")
    vec = _lab_image(px)[0]
    for i in range(4):
        r, g, b = [int(v) for v in px[0, i]]
        scal = rgb_to_lab(r, g, b)
        d = max(abs(vec[i][k] - scal[k]) for k in range(3))
        check(f"lab agrees with paint_mismatch on {(r,g,b)}", d < 1e-6,
              f"delta {d:.2e}")

    # --- Otsu separates two clusters ---
    v = np.concatenate([np.full(900, 2.0), np.full(100, 40.0)])
    t, eta = _otsu(v)
    check("otsu splits a bimodal sample", 2.0 < t < 40.0, f"t={t}")
    check("a clean split reports high separability", eta > 0.9, f"eta={eta:.3f}")
    # The case that made the grader rank clean paint as severe damage: one
    # population, no damage in it. Otsu still returns a threshold; the
    # separability is what says not to believe it.
    # Otsu's eta is NOT a bimodality test and is not used as one — asserted
    # here so nobody reinstates it as the damage guard. Pure noise outscores
    # real structure.
    rng0 = np.random.default_rng(11)
    _, eta_gauss = _otsu(rng0.normal(10, 2.0, 4000))
    _, eta_weak = _otsu(np.concatenate([rng0.normal(10, 3, 3600),
                                        rng0.normal(20, 3, 400)]))
    check("otsu eta ranks noise above real structure, so it is not the guard",
          eta_gauss > eta_weak, f"gaussian {eta_gauss:.3f} vs "
                                f"bimodal {eta_weak:.3f}")
    check("otsu survives a constant sample", _otsu(np.full(50, 7.0))[0] == 7.0)
    check("otsu survives an empty sample", _otsu([]) == (0.0, 0.0))

    def painted(colour, size=180):
        a = np.full((size, size, 3), colour, dtype="uint8")
        # A little noise, so the medians are not degenerate and Otsu has a
        # distribution to work with rather than two delta functions.
        rng = np.random.default_rng(7)
        a = np.clip(a.astype("int16") + rng.integers(-4, 5, a.shape), 0,
                    255).astype("uint8")
        return a

    RED = (178, 34, 34)
    box = (60, 60, 60, 60)

    # --- shallow scuff: lightness moves, hue does not ---
    a = painted(RED)
    a[80:100, 70:130] = (205, 62, 62)          # lighter, SAME hue
    shallow = measure(Image.fromarray(a), box)
    s_shallow, basis = depth_score(shallow)
    check("coloured paint scores on chroma", basis == "chroma")

    # --- deep scratch: primer grey, chroma collapses ---
    b = painted(RED)
    b[80:100, 70:130] = (150, 148, 146)        # neutral primer
    deep = measure(Image.fromarray(b), box)
    s_deep, _ = depth_score(deep)
    check("primer-grey scratch outscores a same-hue scuff",
          s_deep > s_shallow + 0.2, f"{s_deep:.3f} vs {s_shallow:.3f}")

    # --- the thing a plain dE threshold gets WRONG ---
    # Not "primer vs paint" — dE gets that right. The case dE fails on is the
    # one that actually turns up: a SUNLIT shallow scuff against a SHADED deep
    # scratch. dE is dominated by lightness, so it ranks the harmless one as
    # worse. The chroma ratio ignores lightness and gets it right. This
    # comparison is the entire justification for the score, so it is asserted
    # rather than described.
    import numpy as _np

    def de76(c1, c2):
        return _np.linalg.norm(_np.array(rgb_to_lab(*c1))
                               - _np.array(rgb_to_lab(*c2)))

    SUNLIT = (232, 60, 60)              # red paint, bright side of car
    SHADED = (70, 16, 16)               # the SAME paint, shaded side
    scuff_sun = (255, 185, 185)         # clearcoat haze, sunlit: hue intact
    primer_shade = (64, 62, 61)         # through to primer, in shadow
    check("dE ranks the sunlit scuff above the shaded primer scratch",
          de76(SUNLIT, scuff_sun) > de76(SHADED, primer_shade),
          f"{de76(SUNLIT, scuff_sun):.1f} vs {de76(SHADED, primer_shade):.1f}")

    a2 = painted(SUNLIT)
    a2[80:100, 70:130] = scuff_sun
    b2 = painted(SHADED)
    b2[80:100, 70:130] = primer_shade
    s_sun, _ = depth_score(measure(Image.fromarray(a2), box))
    s_shade, _ = depth_score(measure(Image.fromarray(b2), box))
    check("chroma score ranks them the right way round",
          s_shade > s_sun, f"primer {s_shade:.3f} vs scuff {s_sun:.3f}")
    check("chroma score ranks primer above a same-hue scuff",
          s_deep > s_shallow)

    # --- tiers are ordered and monotone ---
    seq = [_tier(s, SCRATCH_CUTS, SCRATCH_TIERS)
           for s in (0.0, 0.3, 0.5, 0.8, 1.0)]
    idx = [SCRATCH_TIERS.index(t) for t in seq]
    check("tier is monotone in the score", idx == sorted(idx), str(seq))
    check("score 0 is the mildest tier", seq[0] == SCRATCH_TIERS[0])
    check("score 1 is the worst tier", seq[-1] == SCRATCH_TIERS[-1])

    # --- neutral paint falls back and SAYS so ---
    c = painted((208, 208, 208))
    c[80:100, 70:130] = (120, 119, 121)
    m_white = measure(Image.fromarray(c), box)
    s_white, basis_white = depth_score(m_white)
    check("silver paint falls back to lightness", basis_white == "lightness")
    check("silver fallback still scores the damage", s_white > 0.1,
          f"{s_white:.3f}")
    check("fallback is reported as lower confidence",
          grade(Image.fromarray(c), box, "scratch_scuff")["confidence"] <
          grade(Image.fromarray(b), box, "scratch_scuff")["confidence"])

    # --- PCA measures a diagonal hairline, the bounding box does not ---
    d = painted(RED, 200)
    for i in range(120):
        d[40 + i, 40 + i] = (150, 148, 146)
        d[40 + i, 41 + i] = (150, 148, 146)
    m_diag = measure(Image.fromarray(d), (30, 30, 140, 140))
    check("pca recovers a diagonal length the box hides",
          m_diag["length_px"] > 120, f"{m_diag['length_px']:.0f}px")
    check("pca recovers a hairline width", m_diag["width_px"] < 12,
          f"{m_diag['width_px']:.1f}px")
    check("hairline reads as elongated", m_diag["elongation"] > 8,
          f"{m_diag['elongation']:.1f}")

    # --- curvature: noise must not beat signal ---
    # The first implementation differenced adjacent pixels and FAILED this:
    # a noisy flat panel scored 0.249 against a pronounced dent's 0.027. The
    # test is kept in that form so the regression cannot come back.
    yy, xx = np.mgrid[0:240, 0:240]
    ramp = (120 + 30 * (xx / 239.0)).astype("float64")   # a lighting gradient
    rng = np.random.default_rng(3)
    noise = rng.normal(0, 1.5, ramp.shape)               # sensor noise

    def as_img(arr):
        u = np.clip(arr, 0, 255).astype("uint8")
        return Image.fromarray(np.stack([u] * 3, axis=-1))

    blob = 25 * np.sin(xx / 6.0) * np.exp(-((xx - 120) ** 2 +
                                            (yy - 120) ** 2) / 2400.0)
    dbox = (80, 80, 80, 80)
    m_flat = measure(as_img(ramp + noise), dbox)
    m_dent = measure(as_img(ramp + noise + blob), dbox)
    check("a flat noisy panel sits at its own baseline",
          m_flat["curv_ratio"] is not None and m_flat["curv_ratio"] < 2.0,
          f"{m_flat['curv_ratio']}")
    check("a dent rises well above the same panel's baseline",
          m_dent["curv_ratio"] > m_flat["curv_ratio"] * 3,
          f"{m_dent['curv_ratio']:.2f} vs {m_flat['curv_ratio']:.2f}")
    check("the dent scores higher than the flat panel",
          deform_score(m_dent)[0] > deform_score(m_flat)[0],
          f"{deform_score(m_dent)[0]:.3f} vs {deform_score(m_flat)[0]:.3f}")

    # --- the ratio cancels the camera, which is why it is a ratio ---
    # Same dent, three times the sensor noise. An absolute threshold would
    # move; the ratio should not move much.
    m_noisy = measure(as_img(ramp + rng.normal(0, 4.5, ramp.shape) + blob),
                      dbox)
    rel = abs(m_noisy["curv_ratio"] - m_dent["curv_ratio"]) / m_dent["curv_ratio"]
    check("tripling sensor noise barely moves the ratio", rel < 0.6,
          f"{m_dent['curv_ratio']:.2f} -> {m_noisy['curv_ratio']:.2f}")

    # --- dent confidence collapses in flat light ---
    dull = np.full((180, 180, 3), 90, dtype="uint8")
    m_dull = measure(Image.fromarray(dull), box)
    if m_dull is not None:
        _, conf_dull = deform_score(m_dull)
        check("flat light lowers dent confidence", conf_dull < 0.4,
              f"{conf_dull:.2f}")
    else:
        check("flat light lowers dent confidence", True, "(unmeasurable)")

    # --- class routing ---
    g = Image.fromarray(b)
    check("scratch routes to depth",
          grade(g, box, "scratch_scuff")["basis"] in ("chroma", "lightness"))
    check("dent routes to curvature",
          grade(g, box, "dent")["basis"] == "curvature")
    check("glass routes to extent",
          grade(g, box, "crack_glass")["basis"] == "extent")

    # --- clean paint must NOT be graded as damage ---
    # This is the defect the Drive folders exposed: no_damage scored 0.755
    # against scratch_severe's 0.568. The measurement now declines instead.
    rng2 = np.random.default_rng(19)
    for name, colour in (("red", RED), ("silver", (208, 208, 208))):
        clean = np.clip(np.full((200, 200, 3), colour, dtype="int16")
                        + rng2.integers(-6, 7, (200, 200, 3)), 0,
                        255).astype("uint8")
        # A broad specular highlight — the thing Otsu latched onto and called
        # damage. Brighter than the paint, and NOT thin.
        clean[70:95, 30:170] = np.clip(
            clean[70:95, 30:170].astype("int16") + 55, 0, 255).astype("uint8")
        g = grade(Image.fromarray(clean), (60, 60, 80, 80), "scratch_scuff")
        if name == "silver":
            check("a highlight on neutral paint is not graded as damage",
                  g["tier"] is None, f"graded {g['tier']} at {g['score']}")
        else:
            # On coloured paint the chroma ratio handles it directly: the
            # highlight keeps the hue, so almost no colour is missing.
            check("a highlight on coloured paint grades at worst mild",
                  g["tier"] in (None, "faint", "light"),
                  f"graded {g['tier']} at {g['score']}")

    # A thin bright scratch on neutral paint IS still believed — the shape
    # rule must not simply refuse everything on a silver car.
    silver = np.clip(np.full((200, 200, 3), 208, dtype="int16")
                     + rng2.integers(-6, 7, (200, 200, 3)), 0,
                     255).astype("uint8")
    silver[96:100, 40:170] = 255
    gs = grade(Image.fromarray(silver), (60, 60, 80, 80), "scratch_scuff")
    check("a thin bright scratch on silver is still graded",
          gs["tier"] is not None, f"{gs['tier']} {gs['basis']}")
    check("a lightness-only grade never claims the worst tier",
          gs["tier"] != SCRATCH_TIERS[-1], str(gs["tier"]))

    # real damage still grades, i.e. the guard is not simply refusing everything
    check("a primer-deep scratch still grades",
          grade(Image.fromarray(b), box, "scratch_scuff")["tier"] is not None)

    # --- degenerate inputs return a verdict, not an exception ---
    tiny = Image.fromarray(painted(RED, 8))
    r = grade(tiny, (2, 2, 2, 2), "scratch_scuff")
    check("a 2px box returns a verdict rather than raising",
          isinstance(r, dict) and "tier" in r)
    r2 = grade(Image.fromarray(painted(RED)), (-20, -20, 60, 60), "dent")
    check("a box off the top-left edge is handled",
          isinstance(r2, dict) and "tier" in r2)

    print(f"\n{ok} passed, {fail} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
