#!/usr/bin/env python3
"""Side-by-side zoom crops with a same-scale control in the SAME image.

CLAUDE.md, repeatedly: a 1x thumbnail read was wrong three times in one wave;
"a same-batch known-good control in the same image is worth more than any
brightness argument".  This tool therefore always emits pairs, never singles.

Usage: python3 zoom.py out.jpg "label|img.png|cx,cy,w,h" ["label2|..."] ...
       cx,cy,w,h are FRACTIONS of the source image.
"""
import sys
from PIL import Image, ImageDraw, ImageFont

OUT = sys.argv[1]
specs = sys.argv[2:]
try:
    F = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 20)
except Exception:
    F = ImageFont.load_default()

TW = 560
tiles = []
for s in specs:
    lab, path, box = s.split('|')
    cx, cy, w, h = (float(v) for v in box.split(','))
    im = Image.open(path).convert('RGB')
    W, H = im.size
    x0, y0 = int((cx - w / 2) * W), int((cy - h / 2) * H)
    x1, y1 = int((cx + w / 2) * W), int((cy + h / 2) * H)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(W, x1), min(H, y1)
    c = im.crop((x0, y0, x1, y1))
    th = int(TW * c.size[1] / c.size[0])
    tiles.append((lab, c.resize((TW, th), Image.LANCZOS)))

CAP = 30
mh = max(t[1].size[1] for t in tiles)
sheet = Image.new('RGB', (TW * len(tiles), mh + CAP), (18, 18, 20))
dr = ImageDraw.Draw(sheet)
for i, (lab, t) in enumerate(tiles):
    sheet.paste(t, (i * TW, 0))
    dr.rectangle([i * TW, 0, (i + 1) * TW - 1, mh + CAP - 1], outline=(80, 80, 90))
    dr.text((i * TW + 8, mh + 5), lab, font=F, fill=(255, 235, 160))
sheet.save(OUT, quality=94)
print('wrote', OUT, sheet.size)
