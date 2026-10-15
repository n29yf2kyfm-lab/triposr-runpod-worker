#!/usr/bin/env python3
"""trace.py — read a car's shape out of its photographs.

Forge's first stage. Three background-removed photographs (true side, front,
rear) become the curves the loft needs: the roofline and sill along the car,
the wheel centres, the beltline and where the side glass actually is, the door
shut lines, and the cross-section shape seen from each end. Everything is
MEASURED from the cut-out; the manufacturer's dimensions pin the scale (a
photograph cannot give absolute size) and act as hard limits.

Pixels are converted to metres with the car's published length (side view)
and width (front/rear view). Image y grows downward; the ground is the lowest
row of the cut-out, so a height is (ground_row - row) / pixels_per_metre.

Nothing here needs more than numpy and Pillow.
"""
import numpy as np
from PIL import Image, ImageFilter


def load_cutout(path):
    """RGBA cut-out -> (rgb float HxWx3 in 0..1, mask bool HxW)."""
    im = Image.open(path)
    if im.mode != "RGBA":
        raise ValueError(f"{path}: need an RGBA cut-out (background removed)")
    a = np.asarray(im)
    mask = a[:, :, 3] > 128
    rgb = a[:, :, :3].astype(np.float64) / 255.0
    return rgb, mask


def _runs(b):
    """Start/end index pairs of True runs in a 1-D bool array."""
    b = np.r_[False, b, False]
    d = np.diff(b.astype(int))
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0] - 1))


def _smooth(y, k):
    if k <= 1:
        return y
    ker = np.ones(k) / k
    pad = np.pad(y, (k // 2, k - 1 - k // 2), mode="edge")
    return np.convolve(pad, ker, mode="valid")


# ───────────────────────────────────────────────────────────── side view
def trace_side(rgb, mask, dims):
    """Side profile in metres, nose at u = 1.

    Returns a dict:
      u          (n,) stations tail->nose
      roof       (n,) top of the body at u, metres above ground
      sill       (n,) underside of the body at u (wheels excluded)
      belt       (n,) bottom of the side glass at u, or NaN where none seen
      u_front, u_rear   wheel centres as u
      glass      HxW bool in IMAGE space (dark glass inside the cut-out)
      frame      (x0, x1, ground_row, px_per_m, facing) to map (u, z) back
      shut_u     list of u where a vertical shut line was seen
      height_photo  the cut-out's height in metres, for the report
    """
    H, W = mask.shape
    cols = np.where(mask.any(axis=0))[0]
    x0, x1 = int(cols.min()), int(cols.max())
    n = x1 - x0 + 1
    top = np.empty(n)
    bot = np.empty(n)
    for k, x in enumerate(range(x0, x1 + 1)):
        ys = np.where(mask[:, x])[0]
        top[k], bot[k] = ys.min(), ys.max()
    ground = float(np.percentile(bot, 97))         # tyre contact, not a shadow spike
    L = dims["length"] / 1000.0
    pxm = n / L

    height = (ground - top) / pxm                  # metres, per column
    # which way does the car face: the roof run sits rear of centre
    roof_h = np.percentile(height, 92)
    roof_cols = np.where(height >= 0.985 * roof_h)[0]
    facing = "right" if roof_cols.mean() / n < 0.5 else "left"

    def to_u(k):                                   # column index -> u (nose = 1)
        return (n - 1 - k) / (n - 1) if facing == "left" else k / (n - 1)

    u = np.array([to_u(k) for k in range(n)])
    order = np.argsort(u)
    u, height, top_o, bot_o = u[order], height[order], top[order], bot[order]
    cols_o = np.arange(n)[order]

    # the dims say how tall the car is; the photo says the shape. Rescale the
    # profile so its roof equals the published height (a few percent of
    # perspective at most; anything more is reported).
    Hd = dims["height"] / 1000.0
    zscale = Hd / max(height.max(), 1e-6)
    # A cut-out edge is jagged at the pixel level (aerial, mirror, matting
    # noise), and every jag becomes a ripple across the whole loft, so the
    # profile is smoothed over a real distance: 6 cm for the roof, which keeps
    # the screen base and the roof's ends as the soft corners they are.
    roof = _smooth(height * zscale, max(3, int(0.06 * pxm)))

    # wheel centres: the two runs where the cut-out reaches the ground
    RW = dims.get("wheel_d", 640) / 2000.0
    ground_cols = (ground - bot_o) / pxm < 0.03
    runs = [r for r in _runs(ground_cols) if (r[1] - r[0]) / pxm > 0.12]
    if len(runs) >= 2:
        runs = sorted(runs, key=lambda r: -(r[1] - r[0]))[:2]
        centres = sorted(((r[0] + r[1]) / 2 / (n - 1)) for r in runs)
        u_rear, u_front = centres[0], centres[1]
    else:                                          # fall back to the dims
        ov = (L - dims["wheelbase"] / 1000.0) / 2
        u_rear, u_front = ov / L, (ov + dims["wheelbase"] / 1000.0) / L
    wb_photo = (u_front - u_rear) * L

    # sill: the body's underside away from the wheels. Inside an arch the
    # bottom of the cut-out is the tyre, so those columns are bridged.
    under = (ground - bot_o) / pxm * zscale
    arch_half = RW * 1.25 / L
    in_arch = (np.abs(u - u_front) < arch_half) | (np.abs(u - u_rear) < arch_half)
    sill = under.copy()
    sill[in_arch] = np.nan
    ok = ~np.isnan(sill)
    sill = np.interp(u, u[ok], sill[ok]) if ok.sum() > 10 else np.full(n, RW * 1.02)
    sill = _smooth(sill, max(3, int(0.15 * pxm)))      # a rocker is straight; 15 cm
    # A cut-out usually keeps the car's own ground shadow, which reads as a
    # skirt reaching the road. A photograph cannot tell shadow from sill, so
    # when the measured underside sits below 0.75 of a wheel radius the rocker
    # is taken at the typical height instead, and the report says so.
    sill_from_photo = bool(np.median(sill[(u > u_rear + arch_half) & (u < u_front - arch_half)]) >= RW * 0.75)
    if not sill_from_photo:
        sill = np.full(n, RW * 1.02)
        sill[u < 0.08] *= 0.88 + 0.12 * u[u < 0.08] / 0.08
        sill[u > 0.92] *= 0.88 + 0.12 * (1 - u[u > 0.92]) / 0.08
    sill = np.clip(sill, RW * 0.6, roof - 0.3)

    # side glass: dark, low-saturation pixels in the upper half of the body.
    lum = rgb @ np.array([0.299, 0.587, 0.114])
    sat = rgb.max(axis=2) - rgb.min(axis=2)
    body_lum = np.median(lum[mask])
    glass = np.zeros_like(mask)
    belt = np.full(n, np.nan)
    rail = np.full(n, np.nan)
    windows = []
    if body_lum > 0.42:                            # only separable on a light car
        dark = mask & (lum < 0.33) & (sat < 0.25)
        # the glasshouse sits above 55% of the car's height; lower than that
        # the dark patches are wheel-arch shadow and lamp lenses
        rows = np.arange(H)[:, None]
        zrow = (ground - rows) / pxm * zscale
        dark &= zrow > 0.55 * Hd
        dark_im = Image.fromarray(dark.astype(np.uint8) * 255).filter(ImageFilter.MedianFilter(9))
        darkm = np.asarray(dark_im) > 128
        lo_raw = np.full(n, np.nan)
        hi_raw = np.full(n, np.nan)
        count = np.zeros(n)
        for k, c in enumerate(cols_o):
            ys = np.where(darkm[:, x0 + c])[0]
            if len(ys) >= 6:
                lo_raw[k] = (ground - ys.max()) / pxm * zscale
                hi_raw[k] = (ground - ys.min()) / pxm * zscale
                count[k] = len(ys) / pxm * zscale          # metres of glass in the column
        # The beltline of a car is one smooth, nearly straight line. A
        # quadratic through the columns that show glass ignores reflections
        # and the gaps at the pillars.
        has = ~np.isnan(lo_raw) & (count > 0.10)
        if has.sum() > 0.15 * n:
            cb = np.polyfit(u[has], lo_raw[has], 2)
            ch = np.polyfit(u[has], hi_raw[has], 2)
            belt_fit = np.polyval(cb, u)
            rail_fit = np.polyval(ch, u)
            # windows are runs of columns with glass most of the way from the
            # belt to the rail; the gaps between them are the pillars
            frac = np.where(rail_fit - belt_fit > 0.05, count / np.maximum(rail_fit - belt_fit, 0.05), 0)
            isg = _smooth(frac.astype(float), max(3, int(0.03 * pxm))) > 0.45
            windows = [(float(u[a]), float(u[b])) for a, b in _runs(isg) if (b - a) / pxm > 0.18]
            span = (u >= min(w[0] for w in windows) - 0.02) & (u <= max(w[1] for w in windows) + 0.02) if windows else has
            belt = np.where(span, belt_fit, np.nan)
            rail = np.where(span, np.minimum(rail_fit, roof - 0.02), np.nan)
            # the glass mask the loft samples: inside a window, between belt and rail
            for k, c in enumerate(cols_o):
                if not any(a <= u[k] <= b for a, b in windows):
                    continue
                y_top = int(round(ground - rail[k] / zscale * pxm))
                y_bot = int(round(ground - belt[k] / zscale * pxm))
                glass[max(0, y_top):max(0, y_bot) + 1, x0 + c] = True
            glass &= mask

    # shut lines: vertical dark edges in the band between sill and belt,
    # between the arches. A door edge is a thin, tall, dark line.
    # A door edge runs the whole height of the band; a handle, a badge or a
    # swage end is short. So the score is the FRACTION of band rows with a
    # strong vertical edge in the column (or its neighbours), not the mean
    # edge strength, which a chrome handle wins.
    gx = np.abs(np.diff(lum, axis=1, prepend=lum[:, :1]))
    gx = np.maximum.reduce([np.roll(gx, s, axis=1) for s in (-1, 0, 1)])
    band_lo, band_hi = 0.22 * Hd, 0.52 * Hd
    resp = np.zeros(n)
    for k, c in enumerate(cols_o):
        x = x0 + c
        ys = np.where(mask[:, x])[0]
        if not len(ys):
            continue
        z = (ground - ys) / pxm * zscale
        sel = ys[(z > band_lo) & (z < band_hi)]
        if len(sel) > 10:
            resp[k] = (gx[sel, x] > 0.06).mean()
    resp = _smooth(resp, 3)
    lo_u, hi_u = u_rear + arch_half * 0.9, u_front - arch_half * 0.9
    shut_u = []
    cand = [(resp[k], u[k]) for k in range(2, n - 2)
            if lo_u < u[k] < hi_u and resp[k] >= resp[k - 2:k + 3].max()]
    for r, uu in sorted(cand, reverse=True):
        if r < np.percentile(resp[(u > lo_u) & (u < hi_u)], 85):
            break
        if all(abs(uu - s) > 0.09 for s in shut_u):
            shut_u.append(float(uu))
        if len(shut_u) == 3:
            break
    shut_u.sort()

    return dict(u=u, roof=roof, sill=sill, belt=belt, rail=rail, windows=windows,
                u_front=float(u_front), u_rear=float(u_rear),
                glass=glass, frame=(x0, x1, ground, pxm, facing, zscale), shut_u=shut_u,
                height_photo=float(height.max()), wheelbase_photo=float(wb_photo),
                zscale=float(zscale), body_lum=float(body_lum), sill_from_photo=sill_from_photo)


# ───────────────────────────────────────────────────────── front / rear
def trace_end(mask, dims, which="front"):
    """Half-width of the body as a function of height, metres, from a front
    or rear view. Mirrors are clipped (nothing above the beltline may be wider
    than the beltline); the tyres set the width at the bottom, which the
    section builder ignores below the sill.

    Returns dict: z (m, ascending), hw (m), z_shoulder (widest), height_photo.
    """
    H, W = mask.shape
    rows = np.where(mask.any(axis=1))[0]
    y0, y1 = int(rows.min()), int(rows.max())
    ground = float(y1)
    width_px = np.zeros(y1 - y0 + 1)
    for k, y in enumerate(range(y0, y1 + 1)):
        xs = np.where(mask[y])[0]
        width_px[k] = xs.max() - xs.min() + 1
    width_px = _smooth(width_px, 5)
    hpx = y1 - y0 + 1
    # body width = the widest row below 60% of the height (mirrors sit higher)
    zfrac = (ground - np.arange(y0, y1 + 1)) / hpx
    body_rows = zfrac < 0.60
    wmax = width_px[body_rows].max()
    pxm = wmax / (dims["width"] / 1000.0)
    Hd = dims["height"] / 1000.0
    z = (ground - np.arange(y0, y1 + 1)) / pxm
    zs = Hd / max(z.max(), 1e-6)
    z = z * zs
    hw = width_px / pxm / 2
    order = np.argsort(z)
    z, hw = z[order], hw[order]
    # clip mirrors: above 55% of height nothing is wider than the width there
    k55 = int(np.searchsorted(z, 0.55 * Hd))
    if 0 < k55 < len(hw):
        cap = hw[max(0, k55 - 3):k55 + 1].min()
        hw[k55:] = np.minimum(hw[k55:], cap)
    hw = _smooth(hw, 7)
    i_sh = int(np.argmax(hw[(z > 0.25 * Hd) & (z < 0.6 * Hd)])) + int(np.searchsorted(z, 0.25 * Hd))
    i_sh = min(i_sh, len(z) - 1)
    # Section RATIOS, which survive a camera held above eye level (every
    # phone photo of a car's nose is): widths are read across rows, and the
    # elevation only moves rows up and down. The belt is where the body stops
    # being full width above the shoulder; tumblehome is the glass width at
    # mid-glass; roof_w the width just under the roof — all relative to the
    # widest point, as parametric_car's landmarks are.
    hmax = hw[i_sh]
    above = np.where((z > z[i_sh]) & (hw < 0.955 * hmax))[0]
    i_belt = int(above[0]) if len(above) else min(i_sh + 1, len(z) - 1)
    ztop = z.max()
    zb = z[i_belt]
    tumble = float(np.interp(zb + 0.55 * (ztop - zb), z, hw) / hmax)
    roof_w = float(np.interp(ztop - 0.10 * (ztop - zb), z, hw) / hmax)
    return dict(z=z, hw=hw, z_shoulder=float(z[i_sh]), z_belt=float(zb), height_photo=float(z.max() / zs),
                tumble=float(np.clip(tumble, 0.6, 0.95)), roof_w=float(np.clip(roof_w, 0.3, 0.75)),
                elevated=bool(abs(z.max() / zs - Hd) > 0.08 * Hd), which=which)
