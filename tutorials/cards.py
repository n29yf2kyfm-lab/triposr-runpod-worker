"""PIL-rendered graphics: title/disclaimer/outro cards and lower-third step
overlays. Deterministic and free — this is the 'tutorial' visual layer that
costs 0p, versus paying a diffusion model to (badly) render text."""
import os

from PIL import Image, ImageDraw, ImageFont

BG = (16, 18, 22)
ACCENT = (0, 168, 255)
TEXT = (240, 242, 245)
DIM = (170, 176, 184)

FONT_PATHS = [
    os.environ.get("CARD_FONT", ""),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _font(size):
    for path in FONT_PATHS:
        if path and os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _wrap(draw, text, font, max_width):
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def title_card(path, size, title, subtitle=""):
    img = Image.new("RGB", size, BG)
    d = ImageDraw.Draw(img)
    w, h = size
    font = _font(max(28, w // 18))
    lines = _wrap(d, title, font, int(w * 0.84))
    line_h = int(font.size * 1.3)
    y = h // 2 - (len(lines) * line_h) // 2 - (line_h if subtitle else 0)
    d.rectangle([(w * 0.08, y - line_h * 0.8), (w * 0.08 + w * 0.1, y - line_h * 0.8 + 8)],
                fill=ACCENT)
    for line in lines:
        d.text((w * 0.08, y), line, font=font, fill=TEXT)
        y += line_h
    if subtitle:
        sub_font = _font(max(16, w // 40))
        for line in _wrap(d, subtitle, sub_font, int(w * 0.84)):
            d.text((w * 0.08, y), line, font=sub_font, fill=DIM)
            y += int(sub_font.size * 1.35)
    img.save(path)
    return path


def text_card(path, size, heading, lines, small=False):
    img = Image.new("RGB", size, BG)
    d = ImageDraw.Draw(img)
    w, h = size
    head_font = _font(max(22, w // 26))
    body_font = _font(max(16, w // (44 if small else 34)))
    y = int(h * 0.16)
    d.text((w * 0.08, y), heading, font=head_font, fill=ACCENT)
    y += int(head_font.size * 1.8)
    for item in lines:
        for line in _wrap(d, f"•  {item}", body_font, int(w * 0.84)):
            d.text((w * 0.08, y), line, font=body_font, fill=TEXT)
            y += int(body_font.size * 1.45)
        y += int(body_font.size * 0.3)
    img.save(path)
    return path


def lower_third(path, size, step_number, step_title):
    """Transparent PNG overlaid on b-roll: step number + title on a dark
    band along the bottom."""
    w, h = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    band_h = int(h * 0.14)
    band_top = h - int(h * 0.06) - band_h
    d.rectangle([(0, band_top), (w, band_top + band_h)], fill=(10, 12, 15, 200))
    d.rectangle([(0, band_top), (int(w * 0.012), band_top + band_h)], fill=ACCENT + (255,))
    font = _font(max(18, w // 34))
    num_font = _font(max(22, w // 26))
    pad = int(w * 0.035)
    d.text((pad, band_top + band_h // 2 - num_font.size // 2),
           f"{step_number:02d}", font=num_font, fill=ACCENT + (255,))
    d.text((pad + int(num_font.size * 2.2), band_top + band_h // 2 - font.size // 2),
           step_title, font=font, fill=TEXT + (255,))
    img.save(path)
    return path
