#!/usr/bin/env python3
"""photoproj.py — find where a photograph was taken from, then paint it on.

Most photographs of a car online are three-quarter views, not orthographic
elevations, so a flat projection smears. This fits a pinhole camera to the
photograph instead: the camera's azimuth, elevation, distance, focal length,
roll and image offset are searched until the car model's outline, drawn from
that camera, covers the photograph's cut-out (intersection over union).
With the camera known, every exterior triangle that faces it takes its
colour from the photograph at the point it projects to, and the triangles
on the far side take theirs from the mirror image of the near side.

Frame: the template master's (y up, nose +z, the car's left +x).
Needs numpy, scipy and Pillow only.
"""
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy.optimize import minimize


def look(az, el, D, target):
    ca, sa, ce, se = math.cos(az), math.sin(az), math.cos(el), math.sin(el)
    C = target + D * np.array([ce * sa, se, ce * ca])
    f = target - C
    f /= np.linalg.norm(f)
    r = np.cross(f, [0.0, 1.0, 0.0])
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    return C, r, u, f


def project(P, cam, W, H):
    """World points -> pixel coordinates (x right, y down) and depth."""
    az, el, logD, logF, tx, ty, roll = cam["p"]
    C, r, u, f = look(az, el, math.exp(logD), cam["target"])
    cr, sr = math.cos(roll), math.sin(roll)
    r2, u2 = cr * r + sr * u, -sr * r + cr * u
    d = P - C
    z = d @ f
    F = math.exp(logF) * W
    x = W / 2 + F * (d @ r2) / np.maximum(z, 1e-3) + tx * W
    y = H / 2 - F * (d @ u2) / np.maximum(z, 1e-3) + ty * H
    return np.c_[x, y], z, C


def raster(tris2d, W, H):
    im = Image.new("1", (W, H), 0)
    dr = ImageDraw.Draw(im)
    for t in tris2d:
        dr.polygon([tuple(p) for p in t], fill=1)
    return np.asarray(im, dtype=bool)


STEP = np.array([0.18, 0.07, 0.15, 0.2, 0.05, 0.05, 0.03])   # az, el, logD, logF, tx, ty, roll


def _simplex(p, scale=1.0):
    S = [np.array(p, float)]
    for i in range(len(p)):
        q = np.array(p, float)
        q[i] += STEP[i] * scale
        S.append(q)
    return np.array(S)


def fit_camera(tris, mask, view, log=None):
    """tris: (n,3,3) world triangles of the car's outside (wheels included).
    mask: bool cut-out of the photograph. view: 'front' or 'rear' (which end
    the photograph mainly shows). Returns the camera dict.

    Coarse to fine: many starting cameras scored at 160 px, the best few
    searched with Nelder-Mead (explicit step sizes: the default simplex is
    5% of each value, which for a zero roll or offset is no step at all),
    then the winner refined at 360 px."""
    H0, W0 = mask.shape
    area = np.linalg.norm(np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]), axis=1)
    target = np.array([0.0, 0.6, (tris[:, :, 2].max() + tris[:, :, 2].min()) / 2])
    ext = float(np.ptp(tris[:, :, 2]))

    def make(Wd, ntri):
        W, H = Wd, max(30, int(round(H0 * Wd / W0)))
        m = np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).resize((W, H), Image.BILINEAR)) > 127
        flat = tris[np.argsort(-area)[:ntri]].reshape(-1, 3)
        # A cut-out keeps the car's shadow on the ground, which reads as body
        # under the sills, and the search then tilts the camera down to cover
        # it. Score only the top 70% of the car in the photograph — roofline,
        # glasshouse, bonnet and tail — plus the top contour column by column.
        rows = np.where(m.any(1))[0]
        cut = int(rows.min() + 0.70 * (rows.max() - rows.min()))
        mu = m.copy()
        mu[cut:] = False
        cols = np.where(m.any(0))[0]
        top_p = np.where(m.any(0), m.argmax(0), -1).astype(float)

        def cost(p):
            cam = {"p": p, "target": target}
            # A street photograph of a car is taken from about eye level
            # (0-25 degrees down) and level (roll within 4 degrees). Without
            # these bounds the search tilts and rolls the camera to make a
            # Golf-shaped outline cover a Polo-shaped one, and the paint lands
            # in the wrong place even though the overlap score rises.
            el, roll = math.degrees(p[1]), math.degrees(p[6])
            # Inside those bounds, a soft preference for eye level: the outline
            # alone often cannot tell a 45-degree eye-level shot from a high
            # side-on one (Polo: 0.165 against 0.167), and eye level is where
            # people stand.
            pen = max(0.0, el - 25) * 0.02 + max(0.0, -2 - el) * 0.02 + max(0.0, abs(roll) - 4) * 0.03 \
                + max(0.0, abs(p[4]) - 0.15) + max(0.0, abs(p[5]) - 0.15) \
                + 0.004 * max(0.0, el - 10) + 0.003 * abs(roll)
            xy, z, _ = project(flat, cam, W, H)
            if (z <= 0.3).any() or not (0.25 < math.exp(p[3]) < 4.0):
                return 1.0
            sil = raster(xy.reshape(-1, 3, 2), W, H)
            sil = np.asarray(Image.fromarray(sil.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(3))
                             .filter(ImageFilter.MinFilter(3))) > 127
            su = sil.copy()
            su[cut:] = False
            iou_u = (su & mu).sum() / max((su | mu).sum(), 1)
            top_m = np.where(sil.any(0), sil.argmax(0), -1).astype(float)
            both = (top_p >= 0) & (top_m >= 0)
            one = (top_p >= 0) ^ (top_m >= 0)
            span = max(len(cols), 1)
            dtop = (np.abs(top_p[both] - top_m[both]).sum() / H + 0.25 * one.sum()) / span
            return (1.0 - iou_u) + 2.0 * dtop + pen
        return cost

    coarse = make(160, 4000)
    starts = []
    base = 0.0 if view == "front" else math.pi
    for da in (25, -25, 40, -40, 55, -55, 70, -70):
        for logF in (math.log(0.8), math.log(1.3), math.log(2.0)):
            F = math.exp(logF)
            D = F * ext * 1.05                        # the car's length about fills the frame width
            starts.append([base + math.radians(da), math.radians(8), math.log(max(D, 2.0)), logF, 0.0, 0.03, 0.0])
    scored = sorted(((coarse(np.array(p)), p) for p in starts), key=lambda t: t[0])[:4]
    best = None
    for sc, p in scored:
        r = minimize(coarse, np.array(p), method="Nelder-Mead",
                     options={"maxfev": 500, "xatol": 1e-3, "fatol": 1e-4, "initial_simplex": _simplex(p)})
        if best is None or r.fun < best.fun:
            best = r
    fine = make(360, 12000)
    r = minimize(fine, best.x, method="Nelder-Mead",
                 options={"maxfev": 400, "xatol": 5e-4, "fatol": 5e-5, "initial_simplex": _simplex(best.x, 0.3)})
    best = r if r.fun <= fine(best.x) else best
    # report the plain overlap of the whole outline, for comparison across cars
    Wr, Hr = 360, max(30, int(round(H0 * 360 / W0)))
    mr = np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).resize((Wr, Hr))) > 127
    xy, _, _ = project(tris[np.argsort(-area)[:12000]].reshape(-1, 3), {"p": best.x, "target": target}, Wr, Hr)
    sr = raster(xy.reshape(-1, 3, 2), Wr, Hr)
    cam = {"p": best.x, "target": target, "iou": float((sr & mr).sum() / max((sr | mr).sum(), 1)),
           "cost": float(fine(best.x))}
    # the outline it settled on, for a person to check
    W, H = 480, max(30, int(round(H0 * 480 / W0)))
    xy, _, _ = project(tris[np.argsort(-area)[:20000]].reshape(-1, 3), cam, W, H)
    sil = raster(xy.reshape(-1, 3, 2), W, H)
    mm = np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).resize((W, H))) > 127
    ov = np.zeros((H, W, 3), np.uint8)
    ov[mm] = (90, 90, 90)
    ov[sil] = (220, 60, 60)
    ov[sil & mm] = (70, 170, 80)
    cam["overlay"] = Image.fromarray(ov)
    if log is not None:
        az, el, logD, logF, tx, ty, roll = best.x
        log[view + "_camera"] = {"iou": round(cam["iou"], 3), "azimuth_deg": round(math.degrees(az), 1),
                                 "elevation_deg": round(math.degrees(el), 1), "distance_m": round(math.exp(logD), 2),
                                 "focal_x_width": round(math.exp(logF), 2), "roll_deg": round(math.degrees(roll), 1)}
    return cam


def photo_texture(path, paint_rgb, max_w=1600):
    """The photograph with everything that is not the car replaced by the
    paint colour, as JPEG bytes, plus its size and mask."""
    im = Image.open(path).convert("RGBA")
    if im.size[0] > max_w:
        im = im.resize((max_w, int(im.size[1] * max_w / im.size[0])), Image.LANCZOS)
    a = np.asarray(im)
    mask = a[:, :, 3] > 128
    rgb = a[:, :, :3].astype(np.float64)
    soft = np.asarray(Image.fromarray(a[:, :, 3]).filter(ImageFilter.GaussianBlur(2)), np.float64)[:, :, None] / 255
    out = rgb * soft + np.array(paint_rgb, np.float64)[None, None, :] * (1 - soft)
    import io
    buf = io.BytesIO()
    Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(buf, "JPEG", quality=88)
    return buf.getvalue(), im.size, mask


def body_colour(path):
    """sRGB 0-255 mean of the paint: the door band, glass and shadow left out."""
    a = np.asarray(Image.open(path).convert("RGBA")).astype(np.float64)
    m = a[:, :, 3] > 128
    ys = np.where(m.any(1))[0]
    y0, y1 = ys.min(), ys.max()
    band = np.zeros_like(m)
    band[int(y0 + 0.45 * (y1 - y0)):int(y0 + 0.75 * (y1 - y0))] = True
    px = a[m & band][:, :3]
    lum = px.mean(1)
    keep = (lum > np.percentile(lum, 30)) & (lum < np.percentile(lum, 90))
    return px[keep].mean(0) if keep.sum() > 50 else px.mean(0)


def srgb_to_linear(c):
    c = np.asarray(c, np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
