"""Colour-coded damage visualisation — boxes, heat map, and light map.

This is the surface the customer actually looks at. The report already argues
the case in numbers; this makes the same case in one glance, and it must agree
with the numbers exactly — a box drawn amber next to a finding scored "severe"
destroys trust faster than a missing feature.

So every colour here comes from taxonomy.SEVERITY_BANDS, the same table that
colours the report gauge and drives the grade. There is no second palette to
drift out of sync: green (cosmetic) -> lime (minor) -> amber (moderate) ->
orange (major) -> red (severe) is already a heat ramp, so the heat map is not a
new visual language, it is the existing one applied continuously.

Three modes, because they answer different questions:

    box    where exactly is it, and what is each one?   (precise, per-finding)
    heat   where is this car hurt, overall?             (severity density)
    light  which areas are clean?                       (inverse: dims damage-
                                                         free regions so the
                                                         eye lands on trouble)

Findings without a `bbox` cannot be drawn — a VLM backend often returns none.
That is reported honestly in the result rather than silently producing an empty
overlay that reads as "no damage found".
"""
import io
import base64

from taxonomy import SEVERITY_BANDS, clamp_severity, severity_band, PANELS
from taxonomy import DAMAGE_TYPES

# Heat ramp stops, taken straight from the severity bands so the overlay and
# the score can never disagree. (position 0..1, #rrggbb)
RAMP = [(i / (len(SEVERITY_BANDS) - 1.0), c)
        for i, (_lo, _hi, _name, c) in enumerate(SEVERITY_BANDS)]

HEAT_ALPHA = 0.55       # peak opacity of the heat wash
LIGHT_DIM = 0.45        # how far clean areas are dimmed in light mode
BOX_WIDTH = 4


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def ramp_colour(t):
    """Colour at position t (0..1) along the severity heat ramp.

    Linear interpolation between band colours: a severity-6 finding shades
    toward the severity-7 colour rather than snapping, so a heat map reads as a
    gradient while a discrete box still snaps to its band colour.
    """
    t = max(0.0, min(1.0, float(t)))
    for i in range(len(RAMP) - 1):
        t0, c0 = RAMP[i]
        t1, c1 = RAMP[i + 1]
        if t0 <= t <= t1:
            f = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
            a, b = hex_to_rgb(c0), hex_to_rgb(c1)
            return tuple(int(round(a[j] + (b[j] - a[j]) * f)) for j in range(3))
    return hex_to_rgb(RAMP[-1][1])


def severity_colour(sev):
    """Discrete band colour for a finding — identical to the report's chip."""
    return hex_to_rgb(severity_band(clamp_severity(sev))[1])


def finding_label(f):
    """Short human label for a box: panel, damage, severity."""
    panel = PANELS.get(f.get("panel"), (f.get("panel") or "Body",))[0]
    dmg = DAMAGE_TYPES.get(f.get("damage_type"), ("Damage",))[0]
    return f"{panel} · {dmg} · {clamp_severity(f.get('severity', 5))}"


def drawable(findings, image_size, image_index=0):
    """Findings for one image that carry a usable box, in PIXEL corners.

    `bbox` on a finding is NORMALISED [x, y, w, h] in the unit square — the
    single convention this product uses (analyze._bbox_or_none enforces it, and
    detect.py converts to it at the detector boundary). It is stored normalised
    so a finding survives the report being rendered at any resolution; drawing
    is the point where it becomes pixels, using this image's real size.

    The skipped count is returned rather than swallowed so callers can say so:
    an overlay with nothing drawn must never be able to read as "clean car".
    """
    W, H = float(image_size[0]), float(image_size[1])
    out, skipped = [], 0
    for f in findings or []:
        idx = f.get("image_index")
        if idx is not None and idx != image_index:
            continue
        box = f.get("bbox")
        if not box or len(box) != 4:
            skipped += 1
            continue
        try:
            x, y, bw, bh = [float(v) for v in box]
        except (TypeError, ValueError):
            skipped += 1
            continue
        if bw <= 0 or bh <= 0:
            skipped += 1
            continue
        out.append((f, (x * W, y * H, (x + bw) * W, (y + bh) * H)))
    return out, skipped


def render(image_path, findings, mode="both", image_index=0, legend=True):
    """Render an annotated image. Returns (PIL.Image, meta dict).

    mode: "box" | "heat" | "light" | "both" (heat + box)
    """
    from PIL import Image
    base = Image.open(image_path).convert("RGB")
    items, skipped = drawable(findings, base.size, image_index)
    meta = {"drawn": len(items), "skipped_no_bbox": skipped, "mode": mode}

    img = base
    if mode in ("heat", "both"):
        img = _apply_heat(img, items)
    if mode == "light":
        img = _apply_light(img, items)
    if mode in ("box", "both"):
        img = _draw_boxes(img, items)
    if legend and items:
        img = _draw_legend(img)
    return img, meta


def _heat_mask(size, items):
    """Greyscale severity-density mask: brighter where damage is worse.

    Each finding contributes an ellipse whose brightness scales with severity
    and whose size follows its box, then the whole thing is blurred. Overlapping
    damage accumulates, which is the point — three findings on one door should
    read hotter than one.
    """
    from PIL import Image, ImageDraw, ImageFilter
    w, h = size
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    for f, (x1, y1, x2, y2) in items:
        sev = clamp_severity(f.get("severity", 5))
        v = int(round(40 + 215 * (sev / 10.0)))
        draw.ellipse([x1, y1, x2, y2], fill=v)
    radius = max(8, int(min(w, h) * 0.035))
    return mask.filter(ImageFilter.GaussianBlur(radius))


def _apply_heat(img, items):
    """Wash the image with the severity ramp where damage is dense."""
    from PIL import Image
    if not items:
        return img
    mask = _heat_mask(img.size, items)
    # Colourise the mask through the ramp, then composite by its own intensity.
    lut_r, lut_g, lut_b = [], [], []
    for i in range(256):
        r, g, b = ramp_colour(i / 255.0)
        lut_r.append(r)
        lut_g.append(g)
        lut_b.append(b)
    heat = Image.merge("RGB", (mask.point(lut_r), mask.point(lut_g),
                               mask.point(lut_b)))
    # Alpha follows the mask, so the wash fades out with the damage density
    # instead of ending at a hard edge.
    alpha = mask.point(lambda v: int(v * HEAT_ALPHA))
    return Image.composite(heat, img, alpha)


def _apply_light(img, items):
    """Light map: keep damaged areas lit, dim everything else.

    The inverse question from heat — "what is actually clean?" — which is what a
    buyer or a returning renter wants to confirm.
    """
    from PIL import Image, ImageEnhance
    if not items:
        return img
    mask = _heat_mask(img.size, items)
    dim = ImageEnhance.Brightness(img).enhance(LIGHT_DIM)
    dim = ImageEnhance.Color(dim).enhance(0.35)
    return Image.composite(img, dim, mask)


def _draw_boxes(img, items):
    from PIL import ImageDraw
    if not items:
        return img
    img = img.copy()
    draw = ImageDraw.Draw(img, "RGBA")
    font = _font(max(13, int(min(img.size) * 0.028)))
    for f, (x1, y1, x2, y2) in items:
        col = severity_colour(f.get("severity", 5))
        draw.rectangle([x1, y1, x2, y2], outline=col + (255,), width=BOX_WIDTH)
        label = finding_label(f)
        tw, th = _text_size(draw, label, font)
        pad = 4
        # Keep the caption on-canvas when the box hugs the top edge.
        ly = y1 - th - pad * 2
        if ly < 0:
            ly = min(y2 + 2, img.size[1] - th - pad * 2)
        draw.rectangle([x1, ly, x1 + tw + pad * 2, ly + th + pad * 2],
                       fill=col + (230,))
        draw.text((x1 + pad, ly + pad), label, fill=(0, 0, 0, 255), font=font)
    return img


def _draw_legend(img):
    """A severity scale strip, so the colours are self-explanatory."""
    from PIL import ImageDraw
    img = img.copy()
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    bw, bh = int(w * 0.26), max(10, int(h * 0.016))
    x0, y0 = int(w * 0.03), h - bh - int(h * 0.045)
    # Dark backing: the strip sits on unknown photo content, and a legend that
    # is only legible over dark paintwork is not a legend.
    pad = max(8, int(min(w, h) * 0.012))
    draw.rectangle([x0 - pad, y0 - bh - pad * 2 - 6,
                    x0 + bw + pad, y0 + bh + pad], fill=(0, 0, 0, 140))
    for i in range(bw):
        draw.line([(x0 + i, y0), (x0 + i, y0 + bh)],
                  fill=ramp_colour(i / max(1.0, bw - 1.0)) + (255,))
    draw.rectangle([x0, y0, x0 + bw, y0 + bh], outline=(255, 255, 255, 180))
    font = _font(max(11, int(min(w, h) * 0.022)))
    draw.text((x0, y0 - bh - 6), "cosmetic", fill=(255, 255, 255, 230), font=font)
    tw, _ = _text_size(draw, "severe", font)
    draw.text((x0 + bw - tw, y0 - bh - 6), "severe",
              fill=(255, 255, 255, 230), font=font)
    return img


def _font(size):
    from PIL import ImageFont
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _text_size(draw, text, font):
    try:
        l, t, r, b = draw.textbbox((0, 0), text, font=font)
        return r - l, b - t
    except Exception:
        return len(text) * 7, 12


def render_data_uri(image_path, findings, mode="both", image_index=0,
                    max_width=1280, quality=82):
    """Annotated image as a data: URI, for inlining in the HTML report.

    Downscaled first: reports are emailed and printed, and a full-resolution
    phone capture inflates the HTML by megabytes for no visible gain.
    """
    img, meta = render(image_path, findings, mode, image_index)
    if img.width > max_width:
        h = int(img.height * (max_width / float(img.width)))
        from PIL import Image
        img = img.resize((max_width, h), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    meta["bytes"] = buf.tell()
    return f"data:image/jpeg;base64,{b64}", meta
