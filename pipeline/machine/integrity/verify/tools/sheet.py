#!/usr/bin/env python3
"""Contact sheet with a caption strip per tile.  Captions carry the MEASURED
numbers (fill, silhouette fraction, clipped fraction) so the sheet cannot be
read without them -- CLAUDE.md records a sheet that shipped with a blank tile
and a stated occupancy range nobody had measured.

Usage: python3 sheet.py <dir> <out.jpg> <title> [cols] [tilewidth]
"""
import sys, os, json
from PIL import Image, ImageDraw, ImageFont

D, OUT, TITLE = sys.argv[1], sys.argv[2], sys.argv[3]
COLS = int(sys.argv[4]) if len(sys.argv) > 4 else 4
TW = int(sys.argv[5]) if len(sys.argv) > 5 else 640

ORDER = ['CAM_FRONT', 'CAM_FRONT_LEFT_34', 'CAM_LEFT', 'CAM_REAR_LEFT_34',
         'CAM_REAR', 'CAM_REAR_RIGHT_34', 'CAM_RIGHT', 'CAM_FRONT_RIGHT_34',
         'ORTHO_FRONT', 'ORTHO_REAR', 'ORTHO_LEFT', 'ORTHO_RIGHT', 'ORTHO_TOP']
rep = {}
rp = os.path.join(D, 'rig_report.json')
if os.path.exists(rp):
    rep = json.load(open(rp)).get('tiles', {})

names = [n for n in ORDER if os.path.exists(os.path.join(D, n + '.png'))]
names += sorted(f[:-4] for f in os.listdir(D)
                if f.endswith('.png') and not f.endswith('_mask.png')
                and f[:-4] not in names)
if not names:
    raise SystemExit('no tiles in ' + D)

try:
    F = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 17)
    Fs = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 14)
    Ft = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 26)
except Exception:
    F = Fs = Ft = ImageFont.load_default()

im0 = Image.open(os.path.join(D, names[0] + '.png'))
TH = int(TW * im0.size[1] / im0.size[0])
CAP = 46
rows = (len(names) + COLS - 1) // COLS
HDR = 48
W = COLS * TW
H = HDR + rows * (TH + CAP)
sheet = Image.new('RGB', (W, H), (22, 22, 24))
dr = ImageDraw.Draw(sheet)
dr.text((14, 12), TITLE, font=Ft, fill=(240, 240, 245))

for i, n in enumerate(names):
    r, c = divmod(i, COLS)
    x, y = c * TW, HDR + r * (TH + CAP)
    t = Image.open(os.path.join(D, n + '.png')).convert('RGB').resize((TW, TH),
                                                                     Image.LANCZOS)
    sheet.paste(t, (x, y))
    dr.rectangle([x, y + TH, x + TW - 1, y + TH + CAP - 1], fill=(30, 30, 34))
    dr.rectangle([x, y, x + TW - 1, y + TH + CAP - 1], outline=(70, 70, 78))
    dr.text((x + 8, y + TH + 4), n, font=F, fill=(255, 235, 160))
    m = rep.get(n, {})
    if m:
        # Only print the mask-derived numbers when a mask was actually rendered.
        # The first version printed "fill 0.000  silh 0.0000" on every tile of a
        # --nomask sheet, i.e. a caption stating the tile was empty underneath a
        # tile that plainly was not. A wrong number on an evidence sheet is worse
        # than no number.
        if 'silhouette_pixel_fraction' in m:
            s = ('fill %.3f   silh %.4f   clip %.6f   bg %.1f'
                 % (m.get('frame_fill_max_dim', 0), m['silhouette_pixel_fraction'],
                    m.get('clipped_fraction_ge_254', 0),
                    m.get('background_srgb8_top_band', 0)))
            col = (150, 230, 150) if m.get('POPULATED') else (255, 90, 90)
        else:
            s = ('mask not rendered   clip %.6f   bg %.1f'
                 % (m.get('clipped_fraction_ge_254', 0),
                    m.get('background_srgb8_top_band', 0)))
            col = (185, 185, 195)
        dr.text((x + 8, y + TH + 25), s, font=Fs, fill=col)
sheet.save(OUT, quality=92)
print('wrote %s  %dx%d  %d tiles' % (OUT, W, H, len(names)))
