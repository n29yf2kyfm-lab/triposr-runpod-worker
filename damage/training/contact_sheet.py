"""Render a labelled contact sheet of sampled images, so a human (or a model
with eyes) can check that the folder name matches what is actually in the photo.

Every real defect in this project's data was found by looking at the pictures.
The structural checks — counts, hashes, split ratios — passed on corpora that
turned out to be renderings, watermarked stock, or annotation overlays. So this
is not a nicety: it is the only check with a hit rate.

Two sampling modes:
  --mode broad  one image from each of N randomly chosen classes, weighted by
                class size, i.e. what the training distribution actually looks
                like.
  --mode thin   only the small, high-value classes (scratch_faint,
                paint_bad_repair, panel_gap, interior_*, paint_depth_*), which
                have no public equivalent anywhere and therefore decide whether
                this corpus is worth anything beyond dents.
"""

import argparse
import json
import os
import random

from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
THIN = ["scratch_faint", "scratch_severe", "paint_bad_repair", "paint_chip",
        "paint_fade", "panel_gap", "interior_damage", "interior_wear",
        "alloy_scuff", "alloy_corrosion", "paint_depth_thin",
        "paint_depth_normal", "paint_depth_thick", "crack_windscreen",
        "no_damage", "structural_bumper"]


def load_index(path):
    by_folder = {}
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            by_folder.setdefault(r["folder"], []).append(r["path"])
    return by_folder


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--index", default=os.path.join(
        here, "drive_classifier_split.jsonl"))
    ap.add_argument("--out", default=os.path.join(here, "contact_sheet.png"))
    ap.add_argument("--mode", choices=["broad", "thin", "folders"],
                    default="broad")
    ap.add_argument("--folders", default=None,
                    help="folders mode: comma-separated folder names, sampled "
                         "equally and shown in the order given — for checking "
                         "whether an ORDINAL axis (dent_minor..dent_severe) is "
                         "visually coherent, which one random tile per class "
                         "cannot show")
    ap.add_argument("--n", type=int, default=16)
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--tile", type=int, default=300)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    by_folder = load_index(args.index)
    rng = random.Random(args.seed)

    picks = []
    if args.mode == "folders":
        names = [c.strip() for c in (args.folders or "").split(",") if c.strip()]
        per = max(1, args.n // max(1, len(names)))
        for c in names:
            ps = by_folder.get(c, [])
            for p in rng.sample(ps, min(per, len(ps))):
                picks.append((c, p))
    elif args.mode == "thin":
        folders = [c for c in THIN if by_folder.get(c)]
        rng.shuffle(folders)
        for c in folders[:args.n]:
            picks.append((c, rng.choice(by_folder[c])))
    else:
        # Weighted by class size: a sheet that shows one image per class makes a
        # 30-class corpus look balanced when 68% of it is dents. Sampling the
        # real distribution keeps the check honest about what the model will see.
        pool = [(c, p) for c, ps in by_folder.items() for p in ps]
        picks = rng.sample(pool, min(args.n, len(pool)))

    cols = args.cols
    rows = (len(picks) + cols - 1) // cols
    t, bar = args.tile, 30
    sheet = Image.new("RGB", (cols * t, rows * (t + bar)), (18, 18, 20))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype(FONT, 17)
    except OSError:
        font = ImageFont.load_default()

    for i, (cls, path) in enumerate(picks):
        x, y = (i % cols) * t, (i // cols) * (t + bar)
        try:
            im = Image.open(path).convert("RGB")
            w, h = im.size
            s = t / min(w, h)
            im = im.resize((max(1, int(w * s)), max(1, int(h * s))),
                           Image.LANCZOS)
            im = im.crop(((im.width - t) // 2, (im.height - t) // 2,
                          (im.width - t) // 2 + t, (im.height - t) // 2 + t))
            sheet.paste(im, (x, y))
            label = f"{cls}  [{w}x{h}]"
        except Exception as e:
            draw.rectangle([x, y, x + t, y + t], fill=(60, 20, 20))
            label = f"{cls}  UNREADABLE {e}"
        draw.rectangle([x, y + t, x + t, y + t + bar], fill=(30, 30, 34))
        draw.text((x + 5, y + t + 6), label[:40], font=font,
                  fill=(235, 235, 240))
        print(f"{i:>2} {cls:<20} {os.path.basename(path)}")

    sheet.save(args.out, quality=88)
    print(f"\n{args.mode} sheet -> {args.out}  {sheet.size}")


if __name__ == "__main__":
    main()
