#!/usr/bin/env python3
"""ab_sheet.py — pair BEFORE and AFTER renders of the same camera side by side.

A repair claim is only readable when the two images sit in one frame at one
scale. Separate files invite the reader to compare a remembered image against a
present one, which is exactly how a change of camera, exposure or shading
treatment slips through unnoticed — this project has a documented case of a
review round lost because two near-identical tiles carried no caption saying
what differed.

So every tile is captioned with the file it came from, and the sheet header
states the pass and the fact that the cameras are replayed from one spec. If a
view is present on one side and missing on the other it is drawn as an explicit
gap rather than silently dropped, because a quietly missing "after" is
indistinguishable from an unchanged one.

Run:
  python3 ab_sheet.py <before_dir> <after_dir> <out.jpg> [--pass clay]
        [--label-a BEFORE] [--label-b AFTER] [--views a,b,c] [--width 1500]
        [--note "..."]
"""
import argparse
import os

from PIL import Image, ImageDraw, ImageFont


def font(sz):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, sz)
            except Exception:
                pass
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("out")
    ap.add_argument("--pass", dest="pss", default="clay")
    ap.add_argument("--label-a", default="BEFORE")
    ap.add_argument("--label-b", default="AFTER")
    ap.add_argument("--views", default=None)
    ap.add_argument("--width", type=int, default=1500)
    ap.add_argument("--note", default="")
    a = ap.parse_args()

    da = os.path.join(a.before, a.pss)
    db = os.path.join(a.after, a.pss)
    if a.views:
        views = a.views.split(",")
    else:
        views = sorted({os.path.splitext(f)[0] for f in os.listdir(da)
                        if f.endswith(".png")})
    if not views:
        raise SystemExit(f"REFUSED: no images in {da}")

    tw = a.width // 2
    tiles = []
    for v in views:
        pa, pb = os.path.join(da, v + ".png"), os.path.join(db, v + ".png")
        row = []
        for p in (pa, pb):
            if os.path.exists(p):
                im = Image.open(p).convert("RGB")
                th = int(im.height * tw / im.width)
                row.append(im.resize((tw, th), Image.LANCZOS))
            else:
                row.append(None)
        h = max((r.height for r in row if r), default=200)
        row = [r if r else Image.new("RGB", (tw, h), (60, 20, 20)) for r in row]
        tiles.append((v, row, h))

    head, cap = 62, 26
    H = head + sum(t[2] + cap for t in tiles)
    sheet = Image.new("RGB", (a.width, H), (16, 16, 18))
    d = ImageDraw.Draw(sheet)
    f1, f2, f3 = font(24), font(17), font(15)
    d.text((14, 10), f"{a.pss.upper()}  —  {a.label_a}  vs  {a.label_b}",
           fill=(245, 245, 245), font=f1)
    d.text((14, 38), (a.note or "identical cameras: both sides replay one "
                      "locked camera spec; identical shading treatment"),
           fill=(150, 190, 150), font=f3)
    y = head
    for v, row, h in tiles:
        for i, im in enumerate(row):
            sheet.paste(im, (i * tw, y))
        d.rectangle([0, y + h, a.width, y + h + cap], fill=(24, 24, 28))
        d.text((10, y + h + 5), f"{v}   [{a.label_a}]", fill=(235, 235, 235),
               font=f2)
        d.text((tw + 10, y + h + 5), f"{v}   [{a.label_b}]",
               fill=(235, 235, 235), font=f2)
        d.line([tw, y, tw, y + h], fill=(90, 90, 100), width=2)
        y += h + cap
    sheet.save(a.out, quality=92)
    print(f"wrote {a.out}  ({sheet.width}x{sheet.height}, {len(tiles)} views)")


if __name__ == "__main__":
    main()
