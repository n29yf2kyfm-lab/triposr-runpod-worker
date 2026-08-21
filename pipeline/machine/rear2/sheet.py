#!/usr/bin/env python3
"""sheet.py — captioned evidence sheet.

Every delivered artefact self-describes on the image: version, what each tile
is, the azimuth convention for THIS file, and any expected-odd feature. The
"duplicate bisect tiles" review round in CLAUDE.md was lost for want of one
caption line.
"""
import sys
from PIL import Image, ImageDraw, ImageFont
TILES = [
    ("evidence/BASE_shaded35_az035.png",   "BEFORE  rear_v3 (Gate 4 out)  az035  melt hatch+bumper"),
    ("evidence/V4_shaded_az035.png", "AFTER  rear2_v4  az035  rebuilt hatch + bumper"),
    ("evidence/base_shaded_az090.png","BEFORE  az090 STRAIGHT REAR  ragged screen, wavy panels"),
    ("evidence/V4_shaded_az090.png", "AFTER  az090  clean panels, constructed screen aperture"),
    ("evidence/V4_CAVITY_az090.png", "CUT PROOF  components hidden: the melt skins are GONE"),
    ("evidence/V4_matid_az090.png",  "matID  hatch CYAN  bumper YELLOW  L lamp MAGENTA  R ORANGE"),
    ("evidence/V4_clay_az090.png",   "CLAY (surface truth, no colour hiding)"),
    ("evidence/V4_blue_az090.png",   "RESPRAY CONTROL  carpaint->blue: lamps hold red"),
]
W, H = 700, 450
cols, rows = 2, 4
sheet = Image.new("RGB", (W * cols, (H + 26) * rows + 44), (24, 24, 26))
d = ImageDraw.Draw(sheet)
try: f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 15)
except Exception: f = ImageFont.load_default()
try: fh = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
except Exception: fh = f
d.text((12, 12), "REAR GATE v2 — rear2_v4.glb — hatch + rear bumper SURFACES rebuilt.  "
                 "THIS FILE: tail at +X, so az090 = STRAIGHT REAR, az035/125 = rear 3/4s.",
       (250, 250, 250), font=fh)
for i, (p, cap) in enumerate(TILES):
    r, c = divmod(i, cols)
    x, y = c * W, 44 + r * (H + 26)
    try:
        im = Image.open(p).convert("RGB").resize((W, H), Image.LANCZOS)
    except Exception:
        im = Image.new("RGB", (W, H), (60, 30, 30))
        ImageDraw.Draw(im).text((20, 20), "MISSING " + p, (255, 180, 180), font=f)
    sheet.paste(im, (x, y))
    d.rectangle([x, y + H, x + W, y + H + 26], fill=(40, 40, 46))
    d.text((x + 8, y + H + 5), cap, (235, 235, 240), font=f)
sheet.save(sys.argv[1], quality=88)
print("wrote", sys.argv[1], sheet.size)
