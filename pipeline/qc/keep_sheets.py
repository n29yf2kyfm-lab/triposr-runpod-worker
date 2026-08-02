"""Contact sheets for the cars that survived a per-car audit.

The owner reviews a wave by eye, in numbered grids, and calls out the numbers to
cull -- so the deliverable at the end of an audit is not a JSON file, it is a
sheet you can look at. This builds that: a 4-across grid of the keepers, each
tile labelled `#N  <name>`, plus an INDEX.txt mapping every number back to its
uid so a call of "scrap 7 and 12" is unambiguous.

Tiles are cropped from the front-three-quarter panel of each car's existing
four-view sheet rather than re-rendered. That view is the one the rubric leads
on ("front three-quarter view is strong"), and reusing the frame that was
actually audited means the grid cannot disagree with the verdict it summarises.

Usage:
    keep_sheets.py --verdicts verdicts.json --sheets /tmp/batch --out /tmp/batch
                   [--cols 4] [--rows 3] [--upload audit/vwfull/keep]
"""
import argparse, json, os, sys, time, urllib.request

SB = "https://tfkvthprsntexrcuqpyd.supabase.co"
BUCKET = "car-meshes"


def load_env(path="/root/.alam3d_env"):
    try:
        body = open(path).read()
    except OSError:
        return
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line[7:].lstrip() if line.startswith("export ") else line
        n, sep, v = line.partition("=")
        if sep and not os.environ.get(n.strip()):
            os.environ[n.strip()] = v.strip().strip("'\"")


load_env()


def sb_put(path, blob, ctype):
    k = os.environ["SB_KEY"]
    rq = urllib.request.Request(f"{SB}/storage/v1/object/{path}", data=blob,
        method="POST", headers={"apikey": k, "Authorization": "Bearer " + k,
                                "Content-Type": ctype, "x-upsert": "true"})
    return urllib.request.urlopen(rq, timeout=600).status


def tile(path, pad=27):
    """Top-left panel of a view sheet.

    Two sheet layouts are in play and they are not interchangeable: the wave
    sheets carry four views in two rows, the re-render sheets carry five in
    three. Assuming two rows for both squashes a three-row sheet's tile into a
    band of two half-panels, which is what it did before this took the row
    count into account. Rows are read from the geometry: each row is one panel
    plus its caption strip, so H = rows*(TH+pad) + pad with TH fixed by the
    panel's own aspect, and only the true row count satisfies it.
    """
    from PIL import Image
    im = Image.open(path).convert("RGB")
    w, h = im.size
    pw = w // 2
    for rows in (2, 3, 4):
        th = (h - pad * (rows + 1)) / rows
        if th <= 0:
            continue
        # a rendered panel is 1000x562; accept anything close to that aspect
        if 1.55 <= pw / th <= 1.95:
            return im.crop((0, pad, pw, pad + int(th)))
    head = int(h * 0.026)                      # fall back to the old estimate
    return im.crop((0, head, pw, head + (h - head) // 2 - int(h * 0.024)))


def build(entries, out_dir, cols, rows, prefix):
    from PIL import Image, ImageDraw, ImageFont
    try:
        FN = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
        FT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
    except Exception:
        FN = FT = ImageFont.load_default()
    TW, TH, CAP, PAD = 640, 360, 34, 12
    per = cols * rows
    made = []
    for page in range((len(entries) + per - 1) // per):
        chunk = entries[page * per:(page + 1) * per]
        gw = cols * (TW + PAD) + PAD
        gh = rows * (TH + CAP + PAD) + PAD + 34
        s = Image.new("RGB", (gw, gh), (13, 13, 15))
        d = ImageDraw.Draw(s)
        d.text((PAD, 8), f"{prefix}  —  sheet {page + 1} of "
                         f"{(len(entries) + per - 1) // per}  ({len(entries)} cars kept)",
               fill=(150, 255, 170), font=FN)
        for i, e in enumerate(chunk):
            x = PAD + (i % cols) * (TW + PAD)
            y = 34 + PAD + (i // cols) * (TH + CAP + PAD)
            try:
                t = tile(e["sheet"]).resize((TW, TH), Image.LANCZOS)
                s.paste(t, (x, y))
            except Exception:
                d.rectangle([x, y, x + TW, y + TH], fill=(30, 30, 34))
                d.text((x + 12, y + TH // 2), "sheet unavailable",
                       fill=(200, 120, 120), font=FT)
            d.text((x + 4, y + TH + 6), f"#{e['n']}  {e['name'][:52]}",
                   fill=(232, 232, 238), font=FT)
        p = os.path.join(out_dir, f"KEEP_sheet{page + 1}.jpg")
        s.save(p, quality=92)
        made.append(p)
    return made


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdicts", required=True)
    ap.add_argument("--rows-json", default="/tmp/batch/pass98.json")
    ap.add_argument("--sheets", default="/tmp/batch")
    ap.add_argument("--out", default="/tmp/batch")
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--rows", type=int, default=3)
    ap.add_argument("--prefix", default="VW wave — audited keepers")
    ap.add_argument("--upload", default="")
    a = ap.parse_args()

    verdicts = json.load(open(a.verdicts))
    src = json.load(open(a.rows_json))
    keep = sorted(int(k[1:]) for k, v in verdicts.items() if v[0] == "KEEP")
    if not keep:
        sys.exit("no KEEP verdicts")

    entries, index = [], []
    for i, n in enumerate(keep, 1):
        r = src[n - 1]
        rc = os.path.join(a.sheets, f"RC{n:03d}.jpg")
        orig = [f for f in os.listdir(a.sheets) if f.startswith(f"P{n:03d}_")]
        sheet_path = rc if os.path.exists(rc) else \
            (os.path.join(a.sheets, orig[0]) if orig else "")
        entries.append({"n": i, "name": r["name"], "sheet": sheet_path})
        index.append(f"#{i:2d}  {r['name'][:56]:58s} uid={r['uid']}  "
                     f"faces={r.get('faces', 0):,}  (was P{n:03d})")

    made = build(entries, a.out, a.cols, a.rows, a.prefix)
    idx = os.path.join(a.out, "KEEP_INDEX.txt")
    with open(idx, "w") as fh:
        fh.write(f"{a.prefix}\n{len(keep)} cars kept   "
                 f"{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}\n\n")
        fh.write("\n".join(index) + "\n")
    print(f"{len(made)} sheet(s) + index for {len(keep)} keepers")
    for p in made + [idx]:
        print("  ", p)

    if a.upload:
        for p in made + [idx]:
            ct = "text/plain" if p.endswith(".txt") else "image/jpeg"
            sb_put(f"{BUCKET}/{a.upload}/{os.path.basename(p)}", open(p, "rb").read(), ct)
        print("uploaded to", f"{BUCKET}/{a.upload}/")


if __name__ == "__main__":
    main()
