"""Generate UK number-plate textures: white front / yellow rear, blue GB band.
Character area left blank on purpose — no invented registration is baked into a
shared asset (accuracy rule). 520x111mm plate -> 1040x222px texture."""
from PIL import Image, ImageDraw, ImageFont
import sys

OUT = sys.argv[1] if len(sys.argv) > 1 else "."
W, H = 1040, 222
BAND_W = 120                      # ~60mm GB band
BLUE = (0, 51, 160)               # UK band blue
FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 64)

def plate(bg, path):
    im = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(im)
    # blue GB band, full height, left edge
    d.rounded_rectangle([0, 0, BAND_W, H], radius=14, fill=BLUE)
    d.rectangle([BAND_W // 2, 0, BAND_W, H], fill=BLUE)   # square inner edge
    # "GB" white, centred in band
    tb = d.textbbox((0, 0), "GB", font=FONT)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    d.text(((BAND_W - tw) / 2 - tb[0], (H - th) / 2 - tb[1]), "GB", font=FONT, fill="white")
    # thin black rounded border
    d.rounded_rectangle([1, 1, W - 2, H - 2], radius=14, outline=(20, 20, 20), width=5)
    im.save(path)
    print("wrote", path)

plate((238, 240, 243), f"{OUT}/uk_plate_front.png")   # white
plate((255, 205, 0),  f"{OUT}/uk_plate_rear.png")     # UK yellow
