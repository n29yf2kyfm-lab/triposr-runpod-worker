"""Demonstration sheet: the same annotated images in box / heat / light modes.

A training index is a claim about data you cannot see. This renders a handful of
real images from a COCO corpus through the SHIPPING overlay renderer, so the
class palette, the box geometry and the normalised-bbox convention can be
checked with eyes instead of trusted.

NOTHING IS REIMPLEMENTED HERE. All drawing goes through damage/overlay.py:

    overlay.render(path, findings, mode='box'|'heat'|'light'|'both',
                   colour_by='class'|'severity', legend=True)

and the corpus is read through build_train_index.load_originals(), so the boxes
on this sheet are exactly the boxes the index will train on — same dedupe, same
class resolution, same normalisation. If this sheet looks wrong, the index is
wrong. That is the point of drawing it.

TWO HONEST SUBSTITUTIONS, both visible on the sheet rather than hidden:

  panel     A detection corpus has no panel labels, so `panel` is left None and
            overlay's caption falls back to "Body". Guessing "front bumper"
            from a box's position would be inventing evidence.
  severity  Nor does it carry severity. The heat and light maps need an
            intensity, so severity is derived from relative box area — a
            stand-in for demonstration only, never a measurement. It is used
            for nothing but the shape of the wash.

Which is also why the columns do not all use the same palette. Box mode is
coloured BY CLASS, the categorical question this sheet exists to answer. Heat
and light encode intensity, and intensity has no meaning on a categorical
palette, so they carry the severity ramp and the severity legend — matching
overlay's own rule that a picture must never show a class colour under a
severity legend.

    python render_class_maps.py --coco /home/user/cardata_damage \\
        --out /tmp/class_maps.png --n 4
"""
import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_DAMAGE = os.path.dirname(_HERE)
for _p in (_HERE, _DAMAGE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import overlay                                # the shipping renderer
import class_map as CM
import build_train_index as BTI

# Training class -> app taxonomy damage_type, so the sheet uses the same
# palette entry a customer report would use for the same damage. Taken from
# class_map.canonical() rather than restated, so the two cannot drift.
CANONICAL_OVERRIDES = {}


def damage_type(final_class):
    return CANONICAL_OVERRIDES.get(final_class, CM.canonical(final_class))


def demo_severity(w, h):
    """Stand-in severity from relative box area. NOT a measurement.

    Only the heat and light washes consume it. Bigger damage reads hotter,
    which is enough to demonstrate the mode without pretending the corpus
    carries a severity label it does not have.
    """
    area = max(0.0, float(w)) * max(0.0, float(h))
    return max(1, min(10, int(round(1 + 9 * min(1.0, (area / 0.12) ** 0.5)))))


def findings_for(rec):
    """overlay-shaped findings for one indexed image record."""
    out = []
    for cls, x, y, w, h in rec["boxes"]:
        dt = damage_type(cls)
        out.append({
            "panel": None,                     # corpus has no panel labels
            "damage_type": dt,
            "damage_label": cls,
            "severity": demo_severity(w, h),
            "confidence": 1.0,                 # ground truth, not a prediction
            "image_index": 0,
            "bbox": [x, y, w, h],              # normalised 0-1, overlay's rule
        })
    return out


def pick_images(images, n, seed, ideal_boxes=9):
    """Images worth showing: most distinct classes, at a legible box density.

    Two competing wants. A sheet of four scratch-only photographs demonstrates
    nothing about a colour-coded class palette, so class variety ranks first.
    But this corpus annotates some cars forty-seven times over, and forty-seven
    captions on one 520px cell is a grey smear that demonstrates nothing
    either — so among the multi-class images the ones nearest `ideal_boxes` win.
    Ties break on sha, so the choice is reproducible for a given corpus.
    """
    ranked = sorted(images,
                    key=lambda r: (-len(r["counts"]),
                                   abs(len(r["boxes"]) - ideal_boxes),
                                   r["sha"]))
    head = ranked[:max(n * 4, n)]
    import random
    random.Random(seed).shuffle(head)
    return sorted(head[:n],
                  key=lambda r: (-len(r["counts"]), len(r["boxes"]), r["sha"]))


def _fit(img, width):
    from PIL import Image
    if img.width == width:
        return img
    h = max(1, int(round(img.height * (width / float(img.width)))))
    return img.resize((width, h), Image.LANCZOS)


def build_sheet(images, modes, cell_width, title, subtitle):
    """Compose the grid: one row per image, one column per mode."""
    from PIL import Image, ImageDraw

    palette_of = {"box": "class", "both": "class"}
    rendered, metas = [], []
    for rec in images:
        f = findings_for(rec)
        row = []
        for mode in modes:
            img, meta = overlay.render(rec["abspath"], f, mode=mode,
                                       legend=True,
                                       colour_by=palette_of.get(mode,
                                                                "severity"))
            row.append(_fit(img, cell_width))
            metas.append((rec["file"], mode, meta))
        rendered.append(row)

    gap = 14
    pad = 24
    title_font = overlay._font(30)
    head_font = overlay._font(20)
    sub_font = overlay._font(14)
    cap_font = overlay._font(15)

    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    title_h = 44 + 26 if subtitle else 44
    head_h = 46
    cap_h = 26

    row_h = [max(c.height for c in row) for row in rendered]
    W = pad * 2 + len(modes) * cell_width + (len(modes) - 1) * gap
    H = pad + title_h + head_h + sum(h + cap_h + gap for h in row_h) + pad

    bg = (13, 17, 23)                          # the app's dark surface
    sheet = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(sheet)

    draw.text((pad, pad), title, fill=(230, 237, 243), font=title_font)
    if subtitle:
        draw.text((pad, pad + 36), subtitle, fill=(139, 148, 158),
                  font=sub_font)

    y = pad + title_h
    heads = {"box": ("box — colour by CLASS", "one box per annotation"),
             "heat": ("heat — severity density", "wash follows severity ramp"),
             "light": ("light — clean areas dimmed", "inverse of heat"),
             "both": ("both — heat + boxes", "class boxes over severity wash")}
    for j, mode in enumerate(modes):
        x = pad + j * (cell_width + gap)
        h1, h2 = heads.get(mode, (mode, ""))
        draw.text((x, y), h1, fill=(201, 209, 217), font=head_font)
        draw.text((x, y + 24), h2, fill=(110, 118, 129), font=sub_font)
    y += head_h

    for i, row in enumerate(rendered):
        for j, cell in enumerate(row):
            x = pad + j * (cell_width + gap)
            sheet.paste(cell, (x, y))
        rec = images[i]
        counts = ", ".join(f"{c}x{n}" for c, n in sorted(rec["counts"].items()))
        cap = f"{rec['file']}  —  {len(rec['boxes'])} boxes: {counts}"
        draw.text((pad, y + row_h[i] + 5), cap, fill=(139, 148, 158),
                  font=cap_font)
        y += row_h[i] + cap_h + gap

    return sheet, metas


def main():
    ap = argparse.ArgumentParser(
        description="Render a box/heat/light demonstration sheet from a COCO "
                    "damage corpus, colour-coded by class.")
    ap.add_argument("--coco", required=True, help="COCO corpus root")
    ap.add_argument("--out", required=True, help="output image path (.png/.jpg)")
    ap.add_argument("--n", type=int, default=3, help="images on the sheet")
    ap.add_argument("--modes", default="box,heat,light",
                    help="comma-separated overlay modes")
    ap.add_argument("--cell-width", type=int, default=520)
    ap.add_argument("--seed", type=int, default=1337)
    args = ap.parse_args()

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    images, stats = BTI.load_originals(os.path.abspath(args.coco))
    if not images:
        raise SystemExit(f"no usable images under {args.coco}")
    picks = pick_images(images, args.n, args.seed)

    classes_present = sorted({c for r in images for c in r["counts"]})
    subtitle = (f"{len(images)} images / "
                f"{sum(len(r['boxes']) for r in images)} boxes · classes: "
                + ", ".join(f"{c}={CM.canonical(c)} {CM.colour(c)}"
                            for c in classes_present))

    sheet, metas = build_sheet(picks, modes, args.cell_width,
                               f"Damage class maps — {os.path.basename(os.path.abspath(args.coco))}",
                               subtitle)
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    if out.lower().endswith((".jpg", ".jpeg")):
        sheet.save(out, quality=90)
    else:
        sheet.save(out)

    print(f"corpus     {os.path.abspath(args.coco)}  "
          f"({len(images)} images, {stats['boxes_seen']} boxes seen)")
    for rec in picks:
        print(f"  {rec['file']}  {rec['width']}x{rec['height']}  "
              f"{len(rec['boxes'])} boxes  "
              f"{dict(sorted(rec['counts'].items()))}")
    drawn = sum(m[2]["drawn"] for m in metas)
    skipped = sum(m[2]["skipped_no_bbox"] for m in metas)
    print(f"rendered   {len(metas)} panels, {drawn} boxes drawn, "
          f"{skipped} skipped for no bbox")
    print(f"wrote      {out}  ({sheet.width}x{sheet.height}, "
          f"{os.path.getsize(out) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
