#!/usr/bin/env python3
"""evidence.py — the eight-view sheet, so the owner can look at the car.

Every delivered artefact self-describes ON THE IMAGE (CLAUDE.md, the council
audit): the version, what changed, and any expected-odd feature.  The "duplicate"
bisect tiles cost a review round for want of one caption line.

Eight views at one locked camera set, plus a matched BEFORE/AFTER strip against
the base at three of them — because a single after-shot cannot show whether
anything improved, and the brief's whole question is whether one car now carries
six gates' worth of repair.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glbmeas                                                   # noqa: E402
import render as R                                               # noqa: E402

# az 270 = FRONT, az 090 = REAR on this car (nose at -X), confirmed by render.
VIEWS = [(270, 6, "front"), (305, 12, "front34_R"), (215, 12, "front34_L"),
         (0, 6, "side_L"), (180, 6, "side_R"), (125, 12, "rear34_R"),
         (90, 6, "rear"), (270, 62, "roof")]
PAIR = [(305, 12, "front34_R"), (90, 6, "rear"), (0, 6, "side_L")]


def _label(im, text, sub=""):
    from PIL import ImageDraw
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, im.width, 30], fill=(16, 16, 18))
    d.text((8, 8), text, fill=(255, 255, 255))
    if sub:
        d.text((im.width - 8 - 6 * len(sub), 8), sub, fill=(190, 190, 200))
    return im


def sheet(tiles, out, cols, tile_w=780, title=None):
    from PIL import Image
    ims = []
    for path, cap, sub in tiles:
        im = Image.open(path).convert("RGB")
        h = int(im.height * tile_w / im.width)
        im = im.resize((tile_w, h), Image.LANCZOS)
        ims.append(_label(im, cap, sub))
    rows = (len(ims) + cols - 1) // cols
    W, H = tile_w * cols, ims[0].height * rows
    top = 44 if title else 0
    sh = Image.new("RGB", (W, H + top), (28, 28, 32))
    if title:
        from PIL import ImageDraw
        ImageDraw.Draw(sh).text((12, 15), title, fill=(255, 255, 255))
    for i, im in enumerate(ims):
        sh.paste(im, ((i % cols) * tile_w, top + (i // cols) * im.height))
    sh.save(out, quality=92)
    return out


def run(ctx, inp):
    w = ctx.sw("sheet")
    m = glbmeas.measure(inp)
    base = ctx.p("in", "car_rebound.glb")
    bm = glbmeas.measure(base)

    # ONE camera set, framed on the BASE, so the before/after pair is matched.
    cam = R.camera_for(bm, dist_mul=1.45)
    cam["shots"] = R.shots(VIEWS)
    a, _ = R.render(inp, w, "shaded", "A", cam, res=1200, samples=48)
    tiles = [(p, f"{s['tag']}  az{int(s['az']):03d}", "") for p, s in zip(a, cam["shots"])]
    ver = (f"GOLF_ALL_GATES.glb  sha {m['sha256'][:12]}...  "
           f"{m['nodes']} nodes  {m['faces']:,} faces  {m['bytes']:,} B")
    sub = ("six gates merged: glass / front v7 / rear v2 / cabin / skin / pose  |  "
           "az270=FRONT az090=REAR  |  paint shown as authored")
    s8 = sheet(tiles, ctx.p("ev", "GOLF_ALL_GATES_8VIEW.jpg"), 4,
               title=f"{ver}\n{sub}")

    campair = R.camera_for(bm, dist_mul=1.45)
    campair["shots"] = R.shots(PAIR)
    b, _ = R.render(base, w, "shaded", "B", campair, res=1200, samples=48)
    a2 = [p for p in a if any(p.endswith(f"A_{t}.png") for _, _, t in PAIR)]
    a2 = sorted(a2, key=lambda p: [t for _, _, t in PAIR].index(
        os.path.basename(p)[2:-4]))
    pair_tiles = []
    for (bp, ap, (_, _, t)) in zip(b, a2, PAIR):
        pair_tiles.append((bp, f"BEFORE  car_rebound.glb  {t}", "base"))
        pair_tiles.append((ap, f"AFTER   all six gates     {t}", "merged"))
    sp = sheet(pair_tiles, ctx.p("ev", "GOLF_BEFORE_AFTER.jpg"), 2,
               title="BEFORE = the Gate 7+8 base every gate measured against; "
                     "AFTER = one car carrying all six gates. Same camera, same rig.")

    # a clay pass: surface truth with no colour to hide behind (brief rule 1)
    camc = R.camera_for(bm, dist_mul=1.45)
    camc["shots"] = R.shots([(305, 12, "front34_R"), (125, 12, "rear34_R")])
    c, _ = R.render(inp, w, "clay", "C", camc, res=1200, samples=48)
    sheet([(c[0], "CLAY  front 3/4  (no paint, no colour to hide behind)", ""),
           (c[1], "CLAY  rear 3/4", "")],
          ctx.p("ev", "GOLF_CLAY.jpg"), 2)
    json.dump({"sheet": s8, "pair": sp, "views": VIEWS},
              open(ctx.p("ev", "sheet.json"), "w"), indent=1)
    return s8
