#!/usr/bin/env python3
"""review_sheets.py — visual quality gate for the shipped catalogue.

The recolour audit only proves a colour-swap works; it is NOT a model-quality
gate. Before any batch ships (or on demand), render the library's existing
posters into numbered contact sheets so a human can eyeball fidelity —
proportions, sharpness, wrong/duplicate vehicles — and call out numbers to cull.

Usage:
  python3 pipeline/qc/review_sheets.py [--status approved] [--per 30]
                                       [--out /tmp/review] [--catalogue PATH]
Outputs sheet_NN.jpg (6x5 grid, each tile numbered #N + assetId) and INDEX.txt
mapping #N -> assetId. Uses posterUrl already in the catalogue (no re-render).
"""
import json, os, argparse, urllib.request, concurrent.futures as cf
from PIL import Image, ImageDraw
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ap_ = argparse.ArgumentParser()
ap_.add_argument("--catalogue", default=os.path.join(REPO, "platform", "catalogue", "catalogue.v2.json"))
ap_.add_argument("--status", default="approved")
ap_.add_argument("--per", type=int, default=30)
ap_.add_argument("--out", default="/tmp/review")
A = ap_.parse_args()
os.makedirs(A.out, exist_ok=True)
cat = json.load(open(A.catalogue))
rows = [e for e in cat if e.get("publicationStatus") == A.status and e.get("posterUrl")]
rows.sort(key=lambda e: (e.get("make", "").lower(), e.get("model", "").lower(), e["assetId"]))

def fetch(i_e):
    i, e = i_e; p = f"{A.out}/p{i:03d}.png"
    try: urllib.request.urlretrieve(e["posterUrl"], p); return i, p
    except Exception: return i, None
imgs = {}
with cf.ThreadPoolExecutor(max_workers=8) as ex:
    for i, p in ex.map(fetch, enumerate(rows)): imgs[i] = p

COLS, ROWS = 6, 5; PER = A.per; TW, TH = 300, 225; lbl = 28; pad = 6; hdr = 34
def load(p):
    if not p or not os.path.exists(p): return Image.new("RGB", (TW, TH), (70, 70, 70))
    im = Image.open(p).convert("RGBA"); bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    bg.alpha_composite(im); return bg.convert("RGB").resize((TW, TH))
index = []; nsheets = (len(rows) + PER - 1) // PER
for s in range(nsheets):
    W = COLS * TW + pad * (COLS + 1); H = hdr + ROWS * (TH + lbl) + pad
    sheet = Image.new("RGB", (W, H), (235, 236, 238)); d = ImageDraw.Draw(sheet)
    d.text((pad, 8), f"REVIEW SHEET {s+1}/{nsheets}   ({s*PER+1}-{min((s+1)*PER, len(rows))})   call out numbers to scrap", fill=(15, 15, 15))
    for k in range(PER):
        gi = s * PER + k
        if gi >= len(rows): break
        e = rows[gi]; col = k % COLS; row = k // COLS
        x = pad + col * (TW + pad); y = hdr + row * (TH + lbl)
        sheet.paste(load(imgs.get(gi)), (x, y))
        d.text((x + 2, y + TH + 2), f"#{gi+1}", fill=(150, 20, 20))
        d.text((x + 40, y + TH + 2), e["assetId"][:34], fill=(20, 20, 20))
        index.append(f"#{gi+1}\t{e['assetId']}")
    sheet.save(f"{A.out}/sheet_{s+1:02d}.jpg", quality=86)
    print("SAVED", f"{A.out}/sheet_{s+1:02d}.jpg")
open(f"{A.out}/INDEX.txt", "w").write("\n".join(index))
print(f"TOTAL {len(rows)} cars, {nsheets} sheets -> {A.out}")
