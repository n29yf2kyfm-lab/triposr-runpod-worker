"""webp.py: studio pictures from hero.mjs (hero_png/) cropped to the vehicle
and saved small, as hero/<key>.webp for the report and the review sheets.

    python3 webp.py            # make the small pictures; the full ones are kept
    python3 webp.py --prune    # and then remove the full ones (only once every review of them is done)

The full pictures are kept by default: removing them while review agents
were still opening them sent the agents to the small copies mid-run.
"""
import os
import sys

from PIL import Image

import paths


def main():
    prune = "--prune" in sys.argv[1:]
    src, dst = paths.f("hero_png"), paths.f("hero")
    os.makedirs(dst, exist_ok=True)
    n = 0
    for f in sorted(os.listdir(src)) if os.path.isdir(src) else []:
        if not f.endswith(".png"):
            continue
        out = os.path.join(dst, f[:-4] + ".webp")
        if not os.path.exists(out) or os.path.getmtime(out) < os.path.getmtime(os.path.join(src, f)):
            im = Image.open(os.path.join(src, f)).convert("RGBA")
            bb = im.getbbox()
            if bb:
                pad = 30
                im = im.crop((max(0, bb[0] - pad), max(0, bb[1] - pad), min(im.width, bb[2] + pad), min(im.height, bb[3] + pad)))
            im.thumbnail((560, 400))
            im.save(out + ".part", "WEBP", quality=82, method=4)
            os.replace(out + ".part", out)
            n += 1
        if prune:
            os.remove(os.path.join(src, f))
    print(n, "pictures made" + (", full pictures removed" if prune else ""))


if __name__ == "__main__":
    main()
