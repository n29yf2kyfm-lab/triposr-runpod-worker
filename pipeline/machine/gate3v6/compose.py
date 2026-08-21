"""GATE 3 v6 — CPU-side composition (runs OUTSIDE Blender, uses PIL).

Builds the deliverables from the rig's PNGs + _meta_*.json:
  * label_exploded()  - draws node-name labels with leader lines on an
                        exploded render, using the projections the rig emitted
  * sheet8()          - the canonical 8-view sheet, with a HARD assertion that
                        every tile is populated and the measured occupancy
                        printed on the tile
  * symmetry_overlay()- mirror-difference map of a centred front render
  * ref_overlay()     - render vs photographic reference, side by side + blend
  * ab_compare()      - before/after matched comparison
All deliverables are written as quality-88 JPEG; the source PNGs are the
caller's to delete (disk is tight).
"""
import json, math, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_R = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

INK = (24, 24, 24)
PAPER = (232, 232, 232)
ACCENT = (176, 32, 32)


def font(px, mono=False, bold=True):
    p = MONO if mono else (FONT if bold else FONT_R)
    return ImageFont.truetype(p, px)


def save_jpeg(im, path, q=88):
    if im.mode != "RGB":
        im = im.convert("RGB")
    im.save(path, "JPEG", quality=q, optimize=True, subsampling=1)
    return path


def flatten(src, grey=(129, 129, 129)):
    """RGBA render -> RGB over a NEUTRAL GREY ground.

    The zebra pass renders with film_transparent so the striped sky lights and
    reflects but never becomes the picture's background - the owner's spec
    forbids hiding faults behind a dark background, and a striped backdrop
    reads as one."""
    im = Image.open(src) if isinstance(src, str) else src
    if im.mode != "RGBA":
        return im.convert("RGB")
    bg = Image.new("RGB", im.size, grey)
    bg.paste(im.convert("RGB"), mask=im.split()[3])
    return bg


def scale_bar(im, px_per_m, out=None, target_mm=100, colour=(15, 15, 15)):
    """Draw a physical scale bar. Turns a section render from 'looks like a gap'
    into something the verifier can actually measure."""
    im = im.convert("RGB")
    d = ImageDraw.Draw(im)
    W, H = im.size
    for mm in (target_mm, 50, 20, 200, 500):
        L = px_per_m * mm / 1000.0
        if W * 0.10 <= L <= W * 0.40:
            target_mm = mm
            break
    L = px_per_m * target_mm / 1000.0
    x0, y0 = int(W * 0.045), int(H * 0.945)
    th = max(3, int(H * 0.005))
    d.rectangle([x0 - 8, y0 - int(H * 0.055), x0 + int(L) + 8, y0 + int(H * 0.016)],
                fill=(248, 248, 248))
    n = 4
    for i in range(n):
        d.rectangle([x0 + i * L / n, y0, x0 + (i + 1) * L / n, y0 + th],
                    fill=colour if i % 2 == 0 else (250, 250, 250),
                    outline=colour, width=1)
    f = font(max(13, int(H * 0.022)))
    d.text((x0, y0 - int(H * 0.046)), "%d mm   (%.1f px/mm)"
           % (target_mm, px_per_m / 1000.0), font=f, fill=colour)
    if out:
        return save_jpeg(im, out)
    return im


def id_legend(im, colours, out=None, cols=3):
    """Colour key for a material-ID / exploded render. A matID pass without a
    legend is a pretty picture, not evidence."""
    im = im.convert("RGB")
    W, H = im.size
    names = sorted(colours)
    fs = max(14, int(W * 0.0105))
    rows = int(math.ceil(len(names) / cols))
    padx, pady = int(fs * 0.9), int(fs * 0.55)
    sw = int(fs * 1.25)
    colw = (W - padx * (cols + 1)) // cols
    bh = pady * 2 + rows * int(fs * 1.55)
    strip = Image.new("RGB", (W, bh), (242, 242, 242))
    d = ImageDraw.Draw(strip)
    f = font(fs, mono=True)
    for i, n in enumerate(names):
        c = tuple(int(round(255 * v)) for v in colours[n][:3])
        r, cc = divmod(i, cols)
        x = padx + cc * (colw + padx)
        y = pady + r * int(fs * 1.55)
        d.rectangle([x, y, x + sw, y + fs], fill=c, outline=(30, 30, 30), width=1)
        d.text((x + sw + int(fs * 0.45), y - 1), n, font=f, fill=INK)
    o = Image.new("RGB", (W, H + bh), (242, 242, 242))
    o.paste(im, (0, 0))
    o.paste(strip, (0, H))
    if out:
        return save_jpeg(o, out)
    return o


def stack(paths_or_ims, out, title, sub=""):
    ims = [Image.open(p).convert("RGB") if isinstance(p, str) else p.convert("RGB")
           for p in paths_or_ims]
    W = max(i.width for i in ims)
    ims = [i if i.width == W else i.resize((W, int(i.height * W / i.width)), Image.LANCZOS)
           for i in ims]
    H = sum(i.height for i in ims) + 8 * (len(ims) - 1)
    o = Image.new("RGB", (W, H), (26, 26, 26))
    y = 0
    for i in ims:
        o.paste(i, (0, y))
        y += i.height + 8
    return save_jpeg(caption_bar(o, title, sub, h=max(54, int(W * 0.016))), out)


def caption_bar(im, title, sub="", h=None, bg=(18, 18, 18), fg=(245, 245, 245)):
    """Every delivered artefact self-describes ON THE IMAGE (council rule
    2026-08-16: an uncaptioned tile cost a whole review round)."""
    W = im.width
    h = h or max(46, int(W * 0.030))
    pad = int(h * 0.32)
    lines = []
    if sub:
        # WRAP, never clip: the first V5 sheet lost the tail of its azimuth
        # legend off the right edge of a 6460 px image. A caption that runs off
        # the page is information the reader does not get.
        fs = font(int(h * 0.40), mono=True, bold=False)
        probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
        avail = W - 2 * pad
        cur = ""
        for w in sub.split(" "):
            t = (cur + " " + w).strip()
            if probe.textlength(t, font=fs) <= avail or not cur:
                cur = t
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
    lh = int(h * 0.50)
    strip = Image.new("RGB", (W, h + (int(h * 0.16) + lh * len(lines) if lines else 0)), bg)
    d = ImageDraw.Draw(strip)
    d.text((pad, int(h * 0.22)), title, font=font(int(h * 0.52)), fill=fg)
    for i, ln in enumerate(lines):
        d.text((pad, h + int(h * 0.02) + i * lh), ln,
               font=font(int(h * 0.40), mono=True, bold=False), fill=(186, 186, 186))
    out = Image.new("RGB", (W, im.height + strip.height), bg)
    out.paste(strip, (0, 0))
    out.paste(im.convert("RGB"), (0, strip.height))
    return out


# ------------------------------------------------------------------ labels

def label_exploded(png, meta_view, out, title, sub="", min_px=15):
    """Draw a labelled callout for every component the rig projected.

    THE POINT OF AN EXPLODED VIEW IS TO PROVE THE COMPONENTS EXIST. A part with
    no label has not been proven, so this function refuses to write a sheet
    whose label count does not match the rig's projection count."""
    im = Image.open(png).convert("RGB")
    W, H = im.size
    labels = meta_view.get("labels", [])
    if not labels:
        raise RuntimeError("no label projections in meta for %s" % png)
    d = ImageDraw.Draw(im, "RGBA")
    fs = max(min_px, int(W * 0.0115))
    f = font(fs)
    # order top-to-bottom then left-to-right, and push labels out to the nearer
    # vertical margin so leader lines do not cross the parts
    pts = []
    for L in labels:
        u, v = L["u"], L["v"]
        px, py = u * W, (1.0 - v) * H
        pts.append((L["name"], px, py))
    pts.sort(key=lambda t: t[2])
    left = [p for p in pts if p[1] < W * 0.5]
    right = [p for p in pts if p[1] >= W * 0.5]
    drawn = 0
    for side, group in (("L", left), ("R", right)):
        n = len(group)
        if not n:
            continue
        top, bot = int(H * 0.06), int(H * 0.955)
        step = (bot - top) / max(1, n)
        for i, (name, px, py) in enumerate(group):
            ty = int(top + step * (i + 0.5))
            tx = int(W * 0.012) if side == "L" else int(W * 0.988)
            bb = d.textbbox((0, 0), name, font=f)
            tw, th = bb[2] - bb[0], bb[3] - bb[1]
            bx = tx if side == "L" else tx - tw - int(fs * 0.7)
            pad = int(fs * 0.34)
            d.rounded_rectangle([bx - pad, ty - th // 2 - pad,
                                 bx + tw + pad, ty + th // 2 + pad + int(fs * 0.25)],
                                radius=pad, fill=(255, 255, 255, 232),
                                outline=(20, 20, 20, 255), width=2)
            d.text((bx, ty - th // 2), name, font=f, fill=INK)
            anchor = (bx + tw + pad if side == "L" else bx - pad, ty)
            d.line([anchor, (int(px), int(py))], fill=(200, 24, 24, 235), width=3)
            d.ellipse([px - 6, py - 6, px + 6, py + 6], fill=(200, 24, 24, 255))
            drawn += 1
    if drawn != len(labels):
        raise RuntimeError("labelled %d of %d components" % (drawn, len(labels)))
    im = caption_bar(im, title, sub + ("  |  %d components labelled" % drawn))
    return save_jpeg(im, out), drawn


# ------------------------------------------------------------- 8-view sheet

def sheet8(order, meta, pngdir, out, title, sub="",
           populated_floor=0.010, occ_band=(0.75, 0.85), cols=4):
    """Compose the canonical 8-view sheet.

    ASSERTS every tile is populated - the previous gate sheet shipped SEVEN
    views and a BLANK tile, so this is checked in code and never by eye. The
    authority is the rig's ALPHA PROBE silhouette fraction (a background-colour
    difference cannot be trusted once a ground plane is in frame).
    Returns (path, per-tile report list).
    """
    tiles, report = [], []
    for vid, label in order:
        v = meta["views"][vid]
        p = os.path.join(pngdir, v["file"])
        exp = v.get("exposure", {})
        silpx = exp.get("silhouette_px_frac")
        occx = exp.get("silhouette_occ_x")
        occy = exp.get("silhouette_occ_y")
        occm = exp.get("silhouette_occ_max")
        meas = v.get("measured", {})
        rec = {"view": vid, "label": label, "az": v["az"], "elev": v["elev"],
               "file": v["file"], "res": v["res"],
               "cam_type": v["cam_type"], "ortho_scale": v["ortho_scale"],
               "target_y_gltf": v.get("target_y_gltf"),
               "exposure_stops": exp.get("exposure_stops"),
               "silhouette_px_frac": silpx,
               "occ_x": occx, "occ_y": occy, "occ_max": occm,
               "clipped_frac_frame": meas.get("clipped_frac_frame"),
               # background-difference mask: with a ground plane in frame this
               # covers car AND floor, so it is an UPPER BOUND on car clipping,
               # not a car-only figure. Named so nobody reads it as car-only.
               "clipped_frac_nonbg": meas.get("clipped_frac_nonbg"),
               "populated": (silpx is not None and silpx >= populated_floor),
               "occ_in_band": (occm is not None and occ_band[0] <= occm <= occ_band[1])}
        report.append(rec)
        if not rec["populated"]:
            raise RuntimeError(
                "TILE NOT POPULATED: %s (%s) silhouette_px_frac=%s < %.3f — this is "
                "the exact defect the previous sheet shipped; refusing to write."
                % (vid, label, silpx, populated_floor))
        im = Image.open(p).convert("RGB")
        cap = ("%s   az %03d  elev %02d\nocc %.1f%%  fill %.1f%%  clip(frame) %.3f%%  "
               "%s %.4f  exp %+.2f st"
               % (label, v["az"], v["elev"], 100 * occm, 100 * silpx,
                  100 * (meas.get("clipped_frac_frame") or 0.0),
                  "ortho" if v["cam_type"] == "ORTHO" else "lens",
                  v["ortho_scale"] if v["cam_type"] == "ORTHO" else v["lens_mm"],
                  exp.get("exposure_stops") or 0.0))
        tiles.append((im, cap))

    tw, th = tiles[0][0].size
    for im, _ in tiles:
        if im.size != (tw, th):
            raise RuntimeError("tiles differ in size - identical rig violated")
    capH = int(th * 0.085)
    rows = int(math.ceil(len(tiles) / cols))
    gap = max(6, int(tw * 0.008))
    W = cols * tw + (cols + 1) * gap
    H = rows * (th + capH) + (rows + 1) * gap
    sheet = Image.new("RGB", (W, H), (26, 26, 26))
    d = ImageDraw.Draw(sheet)
    f = font(int(capH * 0.33), mono=True)
    for i, (im, cap) in enumerate(tiles):
        r, c = divmod(i, cols)
        x = gap + c * (tw + gap)
        y = gap + r * (th + capH + gap)
        sheet.paste(im, (x, y))
        d.rectangle([x, y, x + tw - 1, y + th - 1], outline=(90, 90, 90), width=2)
        for j, line in enumerate(cap.split("\n")):
            d.text((x + int(capH * 0.18), y + th + int(capH * 0.10) + j * int(capH * 0.42)),
                   line, font=f, fill=(238, 238, 238))
    sheet = caption_bar(sheet, title, sub, h=max(58, int(W * 0.017)))
    return save_jpeg(sheet, out), report


# ------------------------------------------------------------- overlays

def symmetry_overlay(png, out, title, sub=""):
    """Mirror the centred front render about the image centre column and map the
    absolute difference. Requires the render's optical axis to pass through the
    mesh mirror plane (rig option no_shift_x)."""
    from PIL import ImageFilter
    im = Image.open(png).convert("RGB")
    # A raw per-pixel mirror difference on a Monte-Carlo render measures the
    # SAMPLING NOISE, not the geometry: mirrored noise never matches itself.
    # Blur first (radius ~0.12% of width) so what survives is structural.
    r = max(1.5, im.width * 0.0012)
    sm = np.asarray(im.filter(ImageFilter.GaussianBlur(r))).astype(np.float64)
    a = np.asarray(im).astype(np.float64)
    W = a.shape[1]
    if W % 2:
        a, sm = a[:, :W - 1], sm[:, :W - 1]
    diff = np.abs(sm - sm[:, ::-1]).mean(2)
    base = a.mean(2)
    # keep the render legible underneath, paint the asymmetry in red on top
    rgb = np.dstack([base, base, base]) * 0.55 + 90.0
    NOISE_FLOOR = 6.0            # sRGB levels; below this it is sampling noise
    amp = np.clip((diff - NOISE_FLOOR) / 36.0, 0, 1)
    rgb[..., 0] = rgb[..., 0] * (1 - amp) + 235 * amp
    rgb[..., 1] = rgb[..., 1] * (1 - amp) + 28 * amp
    rgb[..., 2] = rgb[..., 2] * (1 - amp) + 28 * amp
    o = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(o)
    d.line([(o.width // 2, 0), (o.width // 2, o.height)], fill=(40, 190, 250), width=3)
    stats = {"blur_radius_px": round(r, 2), "noise_floor_srgb": NOISE_FLOOR,
             "mean_abs_diff_srgb": float(diff.mean()),
             "p99_abs_diff_srgb": float(np.percentile(diff, 99)),
             "frac_px_over_12": float((diff > 12).mean()),
             "frac_px_over_24": float((diff > 24).mean())}
    sub2 = (sub + "  |  blur %.1f px, noise floor %.0f  |  mean|d|=%.2f  p99|d|=%.2f  "
            "px>12: %.2f%%  px>24: %.2f%%  (cyan = mirror plane, red = asymmetry)"
            % (r, NOISE_FLOOR, stats["mean_abs_diff_srgb"], stats["p99_abs_diff_srgb"],
               100 * stats["frac_px_over_12"], 100 * stats["frac_px_over_24"]))
    return save_jpeg(caption_bar(o, title, sub2), out), stats


def _fit(im, box):
    im = im.convert("RGB")
    s = min(box[0] / im.width, box[1] / im.height)
    im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
    c = Image.new("RGB", box, (26, 26, 26))
    c.paste(im, ((box[0] - im.width) // 2, (box[1] - im.height) // 2))
    return c


def side_by_side(items, out, title, sub="", tile=(1400, 1120)):
    """items = [(path_or_Image, caption), ...] laid out in one row."""
    cells = []
    for src, cap in items:
        im = Image.open(src).convert("RGB") if isinstance(src, str) else src
        c = _fit(im, tile)
        d = ImageDraw.Draw(c)
        f = font(int(tile[1] * 0.030))
        # WRAP the per-panel caption. Unwrapped, item 13's middle panel read
        # "...what the shell carries underneat" - the caption ran off the tile.
        rows, cur = [], ""
        for w in cap.split(" "):
            t = (cur + " " + w).strip()
            if d.textlength(t, font=f) <= tile[0] - 30 or not cur:
                cur = t
            else:
                rows.append(cur)
                cur = w
        if cur:
            rows.append(cur)
        lh = int(tile[1] * 0.036)
        wide = max(d.textlength(r, font=f) for r in rows)
        d.rectangle([0, 0, wide + 22, 12 + lh * len(rows)], fill=(15, 15, 15))
        for i, r in enumerate(rows):
            d.text((11, 6 + i * lh), r, font=f, fill=(245, 245, 245))
        cells.append(c)
    gap = 10
    W = len(cells) * tile[0] + (len(cells) + 1) * gap
    H = tile[1] + 2 * gap
    sheet = Image.new("RGB", (W, H), (26, 26, 26))
    for i, c in enumerate(cells):
        sheet.paste(c, (gap + i * (tile[0] + gap), gap))
    if not (title or sub):
        return save_jpeg(sheet, out)      # inner row of a stacked figure
    return save_jpeg(caption_bar(sheet, title, sub, h=max(54, int(W * 0.016))), out)


def blend_overlay(a_path, b_path, out, title, sub="", alpha=0.5):
    a = Image.open(a_path).convert("RGB")
    b = Image.open(b_path).convert("RGB").resize(a.size, Image.LANCZOS)
    o = Image.blend(a, b, alpha)
    return save_jpeg(caption_bar(o, title, sub), out)
