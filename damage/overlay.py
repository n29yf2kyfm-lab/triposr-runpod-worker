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

# Per-damage-type colours, for colour_by="class".
#
# Severity and class answer different questions — "how bad is this?" versus
# "what kind is it?" — and one palette cannot carry both. The severity ramp is
# a SEQUENCE (green through red, ordered, comparable); this is a CATEGORICAL
# set where no colour outranks another. Mixing them is what makes a chart lie,
# so they are separate tables and the legend always states which is in use.
#
# Hues are grouped by family, so a reader learns the scheme once: cool blues for
# paint and surface, warm oranges and reds for structure, violets for glass,
# and distinct outliers for the rest.
# THE TWO PALETTES MUST NOT SHARE A COLOUR, and four of these did: crack was
# byte-identical to the severity band "severe", dent to "major", lamp_damage to
# "moderate" and tire_damage to "cosmetic". A reader who has learned "orange
# means major" from the report gauge then reads an orange box on a
# class-coloured overlay as a severity, which is exactly the ambiguity the two
# separate tables exist to prevent. Every colour here now clears every severity
# band by at least 24 dE, and no two class colours are within 20 dE of each
# other; test 22k pins the first of those.
#
# The warm classes are DEEPER than they were, and that is forced rather than
# chosen: the severity ramp runs green -> lime -> amber -> orange -> red and so
# occupies the entire warm arc at L 0.51-0.72. A warm class colour cannot clear
# it by hue, only by sitting below it.
CLASS_COLOURS = {
    # paint / surface — cool blues
    "scratch": "#4fa2ff", "scuff": "#5dace7", "paint_chip": "#a5d6fe",
    "paint_fade": "#0c70ee", "paint_mismatch": "#6e7cdc",
    # structural — warm
    "dent": "#f46203", "deformation": "#ba4500", "crack": "#ae2b2f",
    "misalignment": "#fab577",
    # glass — violet
    "shattered_glass": "#c383fb", "chip_glass": "#d0a6fd",
    # prior repair — deliberately NOT in the blue paint family.
    #
    # These two were missing entirely and fell through to the grey used for
    # "other", so the two findings a buyer most wants to see — this panel has
    # been resprayed, this one is filled — were drawn in the colour that means
    # "unclassified". They are also not damage: they are history, and a reader
    # must not mistake one for the other, so they get a family of their own
    # (teal-greens, distinct from both the cool paint blues and the warm
    # structural hues) rather than a shade of an existing one.
    "prior_refinish": "#2dd4a7", "body_filler": "#109b75",
    # distinct outliers
    "rust": "#a5722f", "missing_part": "#f7727b", "lamp_damage": "#9d9632",
    "tire_damage": "#00cc32", "hail": "#39c5cf", "other": "#8b949e",
}
DEFAULT_CLASS_COLOUR = "#8b949e"


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


def class_colour(damage_type):
    """Categorical colour for a damage type — for colour_by="class"."""
    return hex_to_rgb(CLASS_COLOURS.get(damage_type, DEFAULT_CLASS_COLOUR))


def finding_colour(f, colour_by="severity"):
    """The one place a finding's box colour is decided.

    Routing both modes through a single function is what keeps the overlay
    honest: the box, its caption background and the legend swatch all ask here,
    so a picture can never show a class colour under a severity legend.
    """
    if colour_by == "class":
        return class_colour(f.get("damage_type", "other"))
    return severity_colour(f.get("severity", 5))


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


def render(image_path, findings, mode="both", image_index=0, legend=True,
           colour_by="severity"):
    """Render an annotated image. Returns (PIL.Image, meta dict).

    mode:      "box" | "heat" | "light" | "both" (heat + box)
    colour_by: "severity" (how bad) or "class" (what kind). The heat and light
               maps always follow SEVERITY regardless — they encode intensity,
               and intensity has no meaning on a categorical palette.
    """
    from PIL import Image
    base = Image.open(image_path).convert("RGB")
    items, skipped = drawable(findings, base.size, image_index)
    meta = {"drawn": len(items), "skipped_no_bbox": skipped, "mode": mode,
            "colour_by": colour_by}

    img = base
    if mode in ("heat", "both"):
        img = _apply_heat(img, items)
    if mode == "light":
        img = _apply_light(img, items)
    if mode in ("box", "both"):
        img = _draw_boxes(img, items, colour_by)
    if legend and items:
        img = _draw_legend(img, items, colour_by)
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


def _draw_boxes(img, items, colour_by="severity"):
    from PIL import ImageDraw
    if not items:
        return img
    img = img.copy()
    draw = ImageDraw.Draw(img, "RGBA")
    font = _font(max(13, int(min(img.size) * 0.028)))
    for f, (x1, y1, x2, y2) in items:
        col = finding_colour(f, colour_by)
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


def _draw_legend(img, items=(), colour_by="severity"):
    """The key for whichever palette was actually used.

    A continuous ramp under class colours would be an outright lie, so class
    mode gets swatches instead — and only for the types present in THIS image,
    since a key listing seventeen damage types the photo does not contain is
    noise rather than explanation.
    """
    if colour_by == "class":
        return _draw_class_legend(img, items)
    return _draw_severity_legend(img)


def _draw_class_legend(img, items):
    from PIL import ImageDraw
    present = []
    for f, _box in items:
        t = f.get("damage_type", "other")
        if t not in present:
            present.append(t)
    if not present:
        return img
    img = img.copy()
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    font = _font(max(11, int(min(w, h) * 0.022)))
    sw = max(10, int(h * 0.018))                      # swatch size
    rows = [(t, DAMAGE_TYPES.get(t, ("Other",))[0]) for t in present]
    tw = max(_text_size(draw, lbl, font)[0] for _t, lbl in rows)
    lh = sw + max(4, int(h * 0.008))
    pad = max(8, int(min(w, h) * 0.012))
    x0 = int(w * 0.03)
    y0 = h - int(h * 0.045) - lh * len(rows)
    draw.rectangle([x0 - pad, y0 - pad,
                    x0 + sw + 8 + tw + pad, y0 + lh * len(rows) + pad // 2],
                   fill=(0, 0, 0, 150))
    for i, (t, lbl) in enumerate(rows):
        y = y0 + i * lh
        draw.rectangle([x0, y, x0 + sw, y + sw],
                       fill=class_colour(t) + (255,),
                       outline=(255, 255, 255, 150))
        draw.text((x0 + sw + 8, y - 1), lbl, fill=(255, 255, 255, 235),
                  font=font)
    return img


def _draw_severity_legend(img):
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
                    max_width=1280, quality=82, colour_by="severity"):
    """Annotated image as a data: URI, for inlining in the HTML report.

    Downscaled first: reports are emailed and printed, and a full-resolution
    phone capture inflates the HTML by megabytes for no visible gain.
    """
    img, meta = render(image_path, findings, mode, image_index,
                       colour_by=colour_by)
    if img.width > max_width:
        h = int(img.height * (max_width / float(img.width)))
        from PIL import Image
        img = img.resize((max_width, h), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    meta["bytes"] = buf.tell()
    return f"data:image/jpeg;base64,{b64}", meta
