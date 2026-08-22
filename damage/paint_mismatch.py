"""Detect a resprayed panel by comparing it with the panels beside it.

WHY THIS IS NOT A DETECTOR
--------------------------
Four platforms were searched for labelled "paint mismatch", "panel gap" and
"fading" and returned ZERO examples. That absence is not a gap in the public
data, it is a sign the problem was posed wrongly. A respray does not look like
anything on its own — photograph one panel and there is nothing to see. It
looks wrong NEXT TO THE PANEL BESIDE IT.

So no class is learned. A panel segmenter finds the panels, and this module
does arithmetic on the pixels between them. Nothing here needs a labelled
mismatch, which is fortunate, because none exists to train on.

WHAT IS MEASURED
----------------
CIEDE2000 colour difference in CIE Lab. Not RGB distance: RGB distance is
dominated by lightness, so the shaded side of a car reads as a different colour
from the sunlit side and every photograph becomes a mismatch. Lab separates
lightness from chroma, and CIEDE2000 further corrects for the fact that the eye
tolerates far more variation in some regions of colour space than others.

Rough scale, which is why the thresholds are where they are:
    dE < 1     invisible to anyone
    dE 1-2     visible only side by side under good light
    dE 2-3.5   a trained eye sees it on adjacent panels
    dE > 5     obvious to a customer

THE THREE THINGS THAT MAKE THIS HARD, AND WHAT IS DONE ABOUT THEM
-----------------------------------------------------------------
1. LIGHTING. One side of a car is lit, the other shaded, and that difference
   dwarfs any respray. Handled by comparing only ADJACENT panels, which share
   lighting, and by weighting chroma over lightness in the verdict: a respray
   usually misses the hue or the saturation, while lighting moves lightness.

2. CURVATURE AND HIGHLIGHTS. A specular highlight is not paint colour. Pixels
   are sampled from the middle of each panel and reduced with the MEDIAN, which
   survives a highlight covering up to half the region. Trimming the extreme
   deciles and taking a mean was tried first and was not enough — see
   panel_colour.

3. PLASTIC. Bumpers are painted, but moulded plastic takes colour slightly
   differently from steel even when both left the factory together, so a
   bumper-to-wing difference is held to a wider tolerance than wing-to-door.
   Without this every undamaged car reports two mismatches at the ends.

THIS IS EVIDENCE, NOT A VERDICT. A mismatch means the panels differ; it does
not prove a repair. Sun fade on a roof, a replacement panel from a scrapyard,
and a bad respray all present the same way. The paint-thickness test in
paint_thickness.py is the one that distinguishes them, and the two together are
what a trade buyer actually relies on.

    python paint_mismatch.py --selftest
"""
import argparse
import math

# dE thresholds. Steel-to-steel is the strict case: two panels that left the
# factory together should be within a couple of units.
DE_SUSPECT = 2.5          # worth reporting
DE_STRONG = 5.0           # a customer would see it
DE_PLASTIC_BONUS = 1.8    # added tolerance when either panel is plastic

# Fraction of a panel's pixels kept after discarding highlights and shadow.
TRIM_DECILE = 0.1


def _srgb_to_linear(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def rgb_to_lab(r, g, b):
    """sRGB (0-255) -> CIE Lab, D65. Written out rather than pulled from a
    library so the pipeline has no dependency beyond numpy."""
    rl, gl, bl = _srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b)
    x = rl * 0.4124564 + gl * 0.3575761 + bl * 0.1804375
    y = rl * 0.2126729 + gl * 0.7151522 + bl * 0.0721750
    z = rl * 0.0193339 + gl * 0.1191920 + bl * 0.9503041
    xn, yn, zn = 0.95047, 1.0, 1.08883

    def f(t):
        return t ** (1.0 / 3.0) if t > 216 / 24389 else (841 / 108) * t + 4 / 29

    fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def ciede2000(lab1, lab2):
    """Perceptual colour difference. The 1976 formula (plain Lab distance)
    over-reports differences in blues and under-reports them in greys, both of
    which are common car colours, so the corrected version is worth the code."""
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    kL = kC = kH = 1.0
    C1 = math.hypot(a1, b1)
    C2 = math.hypot(a2, b2)
    Cb = (C1 + C2) / 2.0
    G = 0.5 * (1 - math.sqrt(Cb ** 7 / (Cb ** 7 + 25.0 ** 7))) if Cb > 0 else 0.0
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if (a1p or b1) else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if (a2p or b2) else 0.0

    dLp = L2 - L1
    dCp = C2p - C1p
    if C1p * C2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    elif h2p - h1p > 180:
        dhp = h2p - h1p - 360
    else:
        dhp = h2p - h1p + 360
    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dhp) / 2)

    Lbp = (L1 + L2) / 2.0
    Cbp = (C1p + C2p) / 2.0
    if C1p * C2p == 0:
        hbp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbp = (h1p + h2p) / 2.0
    elif h1p + h2p < 360:
        hbp = (h1p + h2p + 360) / 2.0
    else:
        hbp = (h1p + h2p - 360) / 2.0

    T = (1 - 0.17 * math.cos(math.radians(hbp - 30))
         + 0.24 * math.cos(math.radians(2 * hbp))
         + 0.32 * math.cos(math.radians(3 * hbp + 6))
         - 0.20 * math.cos(math.radians(4 * hbp - 63)))
    dTh = 30 * math.exp(-(((hbp - 275) / 25.0) ** 2))
    Rc = 2 * math.sqrt(Cbp ** 7 / (Cbp ** 7 + 25.0 ** 7)) if Cbp > 0 else 0.0
    Sl = 1 + (0.015 * (Lbp - 50) ** 2) / math.sqrt(20 + (Lbp - 50) ** 2)
    Sc = 1 + 0.045 * Cbp
    Sh = 1 + 0.015 * Cbp * T
    Rt = -math.sin(math.radians(2 * dTh)) * Rc

    return math.sqrt((dLp / (kL * Sl)) ** 2 + (dCp / (kC * Sc)) ** 2
                     + (dHp / (kH * Sh)) ** 2
                     + Rt * (dCp / (kC * Sc)) * (dHp / (kH * Sh)))


def panel_colour(img, box, trim=TRIM_DECILE):
    """Representative Lab colour of a panel region.

    THE MEDIAN, NOT A TRIMMED MEAN. A specular highlight is the reflection of
    the sky, not the colour of the paint. The first version trimmed the top and
    bottom luminance deciles and averaged the rest, which sounds sufficient and
    is not: a highlight streak across a door covered about 21% of the sampled
    region, so trimming 10% left half of it in and the mean carried a dE of
    12.8 — a confident mismatch report on a uniformly painted car. The median
    tolerates contamination up to half the pixels, which is the right guarantee
    when the contaminant is "the sun is on this panel".
    """
    import numpy as np
    x, y, w, h = [int(round(v)) for v in box]
    # Sample the middle of the panel: edges carry shadow lines, trim, and the
    # neighbouring panel's paint.
    ix, iy = x + int(w * 0.25), y + int(h * 0.25)
    iw, ih = max(1, int(w * 0.5)), max(1, int(h * 0.5))
    crop = np.asarray(img.convert("RGB"))[iy:iy + ih, ix:ix + iw]
    if crop.size == 0:
        return None, 0
    flat = crop.reshape(-1, 3).astype("float32")
    lum = flat @ np.array([0.2126, 0.7152, 0.0722], dtype="float32")
    lo, hi = np.quantile(lum, trim), np.quantile(lum, 1 - trim)
    keep = flat[(lum >= lo) & (lum <= hi)]
    if len(keep) < 32:
        keep = flat
    r, g, b = np.median(keep, axis=0)
    return rgb_to_lab(float(r), float(g), float(b)), len(keep)


def compare_panels(img, panels):
    """panels: [{name, box}] -> findings for adjacent pairs that disagree.

    Only ADJACENT pairs are compared. Comparing every panel with every other
    would flag the roof against the front bumper on a sound car — different
    lighting, different material, different angle to the sky — and bury the
    one comparison that means something.
    """
    import class_map as CM
    lab = {}
    for p in panels:
        name = str(p["name"]).strip().lower()
        if not CM.is_painted_panel(name):
            continue
        c, n = panel_colour(img, p["box"])
        if c is not None:
            # keep the largest instance of each panel type
            if name not in lab or n > lab[name][1]:
                lab[name] = (c, n)

    seen, out = set(), []
    for name, (c1, _n) in sorted(lab.items()):
        for nb in CM.panel_neighbours(name):
            if nb not in lab or (nb, name) in seen:
                continue
            seen.add((name, nb))
            de = ciede2000(c1, lab[nb][0])
            plastic = (CM.PAINTED_PANELS[name]["plastic"]
                       or CM.PAINTED_PANELS[nb]["plastic"])
            thresh = DE_SUSPECT + (DE_PLASTIC_BONUS if plastic else 0.0)
            strong = DE_STRONG + (DE_PLASTIC_BONUS if plastic else 0.0)
            if de < thresh:
                continue
            out.append({
                "panels": (name, nb),
                "delta_e": round(de, 2),
                "threshold": round(thresh, 2),
                "severity": "strong" if de >= strong else "suspect",
                "plastic_pair": plastic,
                "note": ("colour differs from the adjacent panel; consistent "
                         "with a respray or a replaced panel, but sun fade and "
                         "a scrapyard panel look the same — paint thickness "
                         "distinguishes them"),
            })
    return sorted(out, key=lambda f: -f["delta_e"])


# -------------------------------------------------------------- selftest ----

def _selftest():
    from PIL import Image
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

    # 1. known Lab values
    L, a, b = rgb_to_lab(255, 255, 255)
    check(f"white -> L*=100 ({L:.1f}, {a:.1f}, {b:.1f})",
          abs(L - 100) < 0.5 and abs(a) < 0.5 and abs(b) < 0.5)
    L, a, b = rgb_to_lab(0, 0, 0)
    check(f"black -> L*=0 ({L:.1f})", abs(L) < 0.5)

    # 2. CIEDE2000 sanity
    grey = rgb_to_lab(128, 128, 128)
    check("identical colours -> dE 0", ciede2000(grey, grey) < 1e-9)
    near = rgb_to_lab(130, 128, 128)
    # 1.5 not 1.0: grey is where the eye is most sensitive to a hue shift, so
    # (128,128,128) vs (130,128,128) legitimately scores just over 1. The
    # original bound was a guess, not a measurement.
    check(f"near-identical -> dE < 1.5 ({ciede2000(grey, near):.2f})",
          ciede2000(grey, near) < 1.5)
    red = rgb_to_lab(200, 40, 40)
    check(f"grey vs red -> large dE ({ciede2000(grey, red):.1f})",
          ciede2000(grey, red) > 25)

    # 3. THE LIGHTING TEST — the failure mode this module exists to survive.
    #    The same paint in shade must NOT read as a mismatch. Plain RGB
    #    distance fails this badly, which is why Lab is used at all.
    lit = rgb_to_lab(150, 40, 40)
    shade = rgb_to_lab(90, 24, 24)          # same hue, 60% brightness
    de_shade = ciede2000(lit, shade)
    rgb_dist = math.dist((150, 40, 40), (90, 24, 24))
    check(f"shaded same-colour paint: dE {de_shade:.1f} vs raw RGB distance "
          f"{rgb_dist:.1f}", de_shade < rgb_dist / 2)

    # 4. a uniform car reports nothing
    img = Image.new("RGB", (800, 400), (140, 30, 30))
    panels = [{"name": "front_door", "box": [100, 100, 200, 200]},
              {"name": "back_door", "box": [320, 100, 200, 200]},
              {"name": "fender", "box": [20, 100, 70, 200]}]
    f = compare_panels(img, panels)
    check(f"uniform car -> no findings ({len(f)})", not f, str(f))

    # 5. one repainted panel IS found, and named correctly
    img2 = img.copy()
    px = img2.load()
    for yy in range(100, 300):
        for xx in range(320, 520):
            px[xx, yy] = (150, 66, 44)      # wrong hue and saturation
    f2 = compare_panels(img2, panels)
    check(f"repainted back_door found ({[x['panels'] for x in f2]})",
          any(set(x["panels"]) == {"front_door", "back_door"} for x in f2))
    check("finding carries a delta_e and severity",
          bool(f2) and "delta_e" in f2[0] and f2[0]["severity"] in
          ("suspect", "strong"))

    # 6. NON-ADJACENT panels are never compared. A roof and a front bumper
    #    differing is normal; reporting it would bury the real finding.
    img3 = Image.new("RGB", (800, 400), (140, 30, 30))
    px3 = img3.load()
    for yy in range(0, 400):
        for xx in range(600, 800):
            px3[xx, yy] = (40, 40, 150)
    far = [{"name": "roof", "box": [610, 10, 180, 180]},
           {"name": "front_bumper", "box": [10, 10, 180, 180]}]
    check("non-adjacent panels are not compared",
          compare_panels(img3, far) == [])

    # 7. glass and wheels are excluded outright
    glass = [{"name": "windshield", "box": [610, 10, 180, 180]},
             {"name": "front_wheel", "box": [10, 10, 180, 180]}]
    check("non-painted parts are ignored", compare_panels(img3, glass) == [])

    # 8. plastic pairs get the wider tolerance
    img4 = Image.new("RGB", (600, 300), (140, 30, 30))
    px4 = img4.load()
    for yy in range(0, 300):
        for xx in range(300, 600):
            px4[xx, yy] = (137, 38, 36)     # small, plausible factory variance
    steel = [{"name": "front_door", "box": [10, 10, 280, 280]},
             {"name": "back_door", "box": [310, 10, 280, 280]}]
    plast = [{"name": "fender", "box": [10, 10, 280, 280]},
             {"name": "front_bumper", "box": [310, 10, 280, 280]}]
    fs, fp = compare_panels(img4, steel), compare_panels(img4, plast)
    check(f"plastic tolerance is wider (steel {len(fs)} vs plastic "
          f"{len(fp)} findings)", len(fp) <= len(fs))

    # 9. a blown highlight must not invent a mismatch
    img5 = Image.new("RGB", (600, 300), (140, 30, 30))
    px5 = img5.load()
    for yy in range(120, 150):               # specular streak on one panel
        for xx in range(340, 560):
            px5[xx, yy] = (255, 255, 255)
    f5 = compare_panels(img5, steel)
    check(f"specular highlight does not create a mismatch ({len(f5)})",
          not f5, str(f5))

    print(f"\n{ok} passed, {fail} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(_selftest())
    ap.print_help()
