#!/usr/bin/env python3
"""Audit prep for the Hyundai wave.

Two products, deliberately separate, because one image cannot carry both:

  sheets/<uid>.jpg   the full 1720x1050 contact sheet (pass 1 -- proportions,
                     glazing, pose, grille/headlight sharpness, scan mush)
  wheels/w<NN>.jpg   a WHEEL-ZOOM strip, one band per car per side, upscaled
                     ~2.2x (pass 2 -- tyre colour and rim-face presence)

Why the zoom is a separate image: the reader downscales anything wider than
~1568px, so a composite carrying both the whole sheet and a genuine 2x wheel
crop ends up delivering neither. The tyre-colour defect in CLAUDE.md was missed
precisely because it was judged at thumbnail scale.

Crop calibrated by eye against a real 860x483 tile (nissan GT-R side view):
body sits y~110-360, wheels y~230-360, x~130-730. The band below covers both
wheels with margin.

NOTE: no pixel-darkness probe anywhere here. That was tried on a previous
marque and DISCARDED as invalid -- the wheel crop contains the black backdrop
and the floor reflection, so a "darkest pixel" test returns zero suspects for
every car. This tool only ever produces something for a human eye to read.
"""
import io, json, os, sys, urllib.request, concurrent.futures as cf
from PIL import Image, ImageDraw, ImageFont

M = "hyundai"
SB = "https://tfkvthprsntexrcuqpyd.supabase.co"
K = os.environ["SB_KEY"]
BASE = f"/tmp/{M}"
SHEETS, WHEELS = f"{BASE}/sheets", f"{BASE}/wheels"
PAD, TW = 28, 860

# tile index -> (label, is_side_A).  front34+side show one side of the car;
# front34_L+rear34 show the other (CLAUDE.md, per-side wheel voids).
TILES = [("front34", 0, 0, "A"), ("front34_L", 1, 0, "B"),
         ("side", 0, 1, "A"), ("rear34", 1, 1, "B")]

# wheel band inside a tile, as fractions of tile w/h
BX0, BX1, BY0, BY1 = 0.09, 0.93, 0.43, 0.80


def font(sz):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            pass
    return ImageFont.load_default()


def sb_list(prefix):
    out, off = [], 0
    while True:
        rq = urllib.request.Request(
            f"{SB}/storage/v1/object/list/car-meshes",
            data=json.dumps({"prefix": prefix, "limit": 1000, "offset": off}).encode(),
            headers={"apikey": K, "Authorization": f"Bearer {K}",
                     "Content-Type": "application/json"})
        b = json.load(urllib.request.urlopen(rq, timeout=120))
        out += [o["name"] for o in b]
        if len(b) < 1000:
            return out
        off += len(b)


def fetch(uid):
    dst = f"{SHEETS}/{uid}.jpg"
    if os.path.exists(dst) and os.path.getsize(dst) > 10000:
        return uid
    rq = urllib.request.Request(f"{SB}/storage/v1/object/car-meshes/audit/{M}/{uid}.jpg",
                                headers={"apikey": K, "Authorization": f"Bearer {K}"})
    try:
        open(dst, "wb").write(urllib.request.urlopen(rq, timeout=180).read())
        return uid
    except Exception as e:
        print("  fetch fail", uid[:8], type(e).__name__)
        return None


def tiles_of(uid):
    im = Image.open(f"{SHEETS}/{uid}.jpg").convert("RGB")
    th = (im.size[1] - 3 * PAD) // 2
    out = {}
    for lab, cx, cy, side in TILES:
        x, y = cx * TW, PAD + cy * (th + PAD)
        out[lab] = (im.crop((x, y, x + TW, y + th)), side)
    return out


def band(tile, width=1540):
    w, h = tile.size
    c = tile.crop((int(w * BX0), int(h * BY0), int(w * BX1), int(h * BY1)))
    return c.resize((width, int(c.size[1] * width / c.size[0])), Image.LANCZOS)


def wheel_strip(group, idx):
    """One image = 2 cars x 2 sides, each band upscaled ~2.2x."""
    rows, F = [], font(26)
    for n, uid, name in group:
        t = tiles_of(uid)
        for lab in ("side", "rear34"):
            rows.append((band(t[lab][0]), f"#{n}  {name[:52]}   [{lab}]"))
    W = rows[0][0].size[0]
    H = sum(r[0].size[1] + 34 for r in rows)
    out = Image.new("RGB", (W, H), (10, 10, 12))
    d = ImageDraw.Draw(out)
    y = 0
    for im, lab in rows:
        d.text((8, y + 6), lab, fill=(240, 210, 90), font=F)
        out.paste(im, (0, y + 34))
        y += im.size[1] + 34
    p = f"{WHEELS}/w{idx:02d}.jpg"
    out.save(p, quality=93)
    return p


if __name__ == "__main__":
    os.makedirs(SHEETS, exist_ok=True)
    os.makedirs(WHEELS, exist_ok=True)
    rows = {r["uid"]: r for r in json.load(open(f"{BASE}/manifest.filtered.json"))}
    have = {n.split("/")[-1].replace(".jpg", "") for n in sb_list(f"audit/{M}/")}
    have &= set(rows)
    print(f"{len(have)} sheets in bucket of {len(rows)} manifest rows")

    if sys.argv[1:] and sys.argv[1] == "wheels":
        order = json.load(open(f"{BASE}/order.json"))
        want = [(n, u, rows[u]["name"]) for n, u in order
                if u in json.load(open(f"{BASE}/pass1_survivors.json"))]
        for i in range(0, len(want), 2):
            print(wheel_strip(want[i:i + 2], i // 2))
        sys.exit()

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        got = [g for g in ex.map(fetch, sorted(have)) if g]
    got.sort(key=lambda u: rows[u]["name"].lower())
    json.dump([[i, u] for i, u in enumerate(got, 1)], open(f"{BASE}/order.json", "w"))
    print(f"downloaded {len(got)} sheets -> {SHEETS}")
    for i, u in enumerate(got, 1):
        print(f"  #{i:02d} {u} {rows[u]['faces']:>9,} {rows[u]['name'][:56]}")
