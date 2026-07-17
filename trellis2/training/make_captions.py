"""Generate training captions from a vehicles CSV export.

CSV columns (from the app's vehicles/car_listings tables):
  image_file, year, make, model, trim, colour, body_style, view(optional)

Usage: python make_captions.py listings.csv data/img/
Writes <basename>.txt beside each image, in the worker's vehicle-prompt
vocabulary so training matches inference.
"""
import csv, os, sys

src, out = sys.argv[1], sys.argv[2]
n = 0
for row in csv.DictReader(open(src)):
    img = row["image_file"]
    base = os.path.splitext(os.path.basename(img))[0]
    identity = " ".join(str(row[k]) for k in ("year", "make", "model", "trim") if row.get(k))
    bits = [f"a {identity}"]
    if row.get("colour"):
        bits.append(f"{row['colour'].lower()} paint")
    if row.get("body_style"):
        bits.append(row["body_style"].lower())
    bits.append(row.get("view") or "three-quarter front view")
    open(os.path.join(out, base + ".txt"), "w").write(", ".join(bits) + "\n")
    n += 1
print(f"wrote {n} captions to {out}")
