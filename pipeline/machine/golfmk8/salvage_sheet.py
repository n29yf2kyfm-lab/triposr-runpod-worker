#!/usr/bin/env python3
"""salvage_sheet.py — one numbered contact sheet per batch, for the eye.

The project standard is that automated gates are candidate finders and the
verdict is a human looking at a render. This lays a batch out so that is cheap
to do: one row per car, three studio views, and a header carrying the numbers
that decide whether the render is even ADMISSIBLE as evidence.

WHAT THE HEADER SAYS AND WHY EACH FIELD IS THERE:
  probe        glass_probe on the SHIPPED file. The render cannot witness this
               -- render/handler.py forces transmission onto any glass-NAMED
               material, so a poster shows perfect glazing on an opaque car.
  lamps        lens materials left alone. A non-zero count means this car
               carried lamp lenses named like windows, which the old name-only
               list would have turned to clear glass.
  body         body panels left alone. Non-zero means a panel was named
               `ext_glass`-something and would have become a hole in the car.
  cabin        placeholder interior colours neutralised (green seats and so on).
  paint        the material found by ray visibility and painted.

READ THE RENDER FOR WHAT THE NUMBERS CANNOT SEE: missing bodywork (a car with
no front end passes every check above), soft or melted surfacing, wrong vehicle,
and shut lines. Those are the things that actually decide whether a car ships.

Run: python3 salvage_sheet.py <manifest.json> <outdir> <out.png>
"""
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

MAN, WORK, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
TW = int(os.environ.get("SHEET_TILE", "640"))


def font(sz, bold=True):
    for p in (("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
               else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            pass
    return ImageFont.load_default()


F1, F2 = font(27), font(19, False)
recs = [r for r in json.load(open(MAN)) if r.get("stage") == "done"]
if not recs:
    sys.exit("no completed cars in this manifest")

rows = []
for r in recs:
    a = r["assetId"]
    d = os.path.join(WORK, a, "img")
    fs = sorted(f for f in os.listdir(d) if f.endswith(".png")) if os.path.isdir(d) else []
    if not fs:
        continue
    ims = [Image.open(os.path.join(d, f)).convert("RGB") for f in fs]
    w, h = ims[0].size
    th = int(TW * h / w)
    strip = Image.new("RGB", (TW * len(ims), th + 60), (250, 250, 250))
    for i, im in enumerate(ims):
        strip.paste(im.resize((TW, th)), (TW * i, 60))
    dr = ImageDraw.Draw(strip)
    dr.rectangle([0, 0, strip.size[0], 59], fill=(24, 24, 26))
    title = f"#{r['n']}  {(r.get('sourceTitle') or a)[:58]}"
    dr.text((14, 8), title, font=F1, fill=(255, 255, 255))
    sub = (f"{a}   ·   probe {r.get('probe')}/{r.get('probe_certainty')}"
           f"   ·   lamps spared {r.get('lamps_spared', 0)}"
           f"   ·   body spared {r.get('body_spared', 0)}"
           f"   ·   cabin {r.get('cabin_fixed', 0)}"
           f"   ·   paint {(r.get('paint') or '?')[:26]}")
    ok = r.get("probe") == "clear" and r.get("probe_certainty") == "proven"
    dr.text((16, 36), sub, font=F2, fill=(150, 220, 160) if ok else (240, 190, 120))
    rows.append(strip)

W = max(r.size[0] for r in rows)
H = sum(r.size[1] for r in rows) + 3 * len(rows)
sheet = Image.new("RGB", (W, H), (250, 250, 250))
y = 0
for r in rows:
    sheet.paste(r, (0, y))
    y += r.size[1] + 3
sheet = sheet.resize((W // 2, H // 2))
sheet.save(OUT)
print(f"SHEET {OUT} {sheet.size} rows={len(rows)}")
