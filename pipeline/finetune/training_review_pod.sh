#!/bin/bash
# training_review_pod.sh — put EYES on the Stage C training set.
#
# Why: the four-way isolation run (2026-07-26) proved the tuned 512 stage adds
# a ridge along the roofline and softens the front end, while the tuned 1024
# stage is clean. The 512 stage learns whole-car silhouette, so the suspicion
# is that the training shapes themselves carry roof aerials, light bars and
# scan spikes, and the model learned them as car anatomy.
#
# I first tried to measure this geometrically. The detector flagged known-good
# cars and could not reliably find the up-axis, so it was scrapped — a
# heuristic nobody trusts is worse than no number at all. This does what the
# project standard says to do instead: render contact sheets and look.
#
# No rendering cost: Stage A already produced 16 conditioning views per shape
# in renders_cond/. This just tiles them.
ROOT=/workspace/alamcars
LOCAL=/root/review
mkdir -p "$LOCAL/sheets"
( cd "$LOCAL" && python3 -m http.server 8000 >/dev/null 2>&1 & )
exec > >(tee -a "$LOCAL/stage_b.log") 2>&1
status(){ printf '{"step":"%s","at":"%s"}\n' "$1" "$(date -u +%FT%TZ)" > "$LOCAL/status.json"; echo "===== $1 ====="; }

status boot
[ -f /etc/rp_environment ] && source /etc/rp_environment
export SB_KEY
[ -n "$SB_KEY" ] && echo "SB key: present" || echo "SB key: MISSING — sheets will not upload"
pip install -q pillow pandas || true

status inspect-renders
python3 - <<'PY'
import glob, os
d = sorted(glob.glob("/workspace/alamcars/renders_cond/*"))
print(f"renders_cond entries: {len(d)}")
for p in d[:3]:
    fs = sorted(glob.glob(p + "/*"))
    print(f"  {os.path.basename(p)}: {len(fs)} files -> {[os.path.basename(f) for f in fs[:6]]}")
PY

status build-sheets
python3 - <<'PY'
import glob, json, os
from PIL import Image, ImageDraw

SRC = sorted(glob.glob("/workspace/alamcars/renders_cond/*"))
SRC = [p for p in SRC if os.path.isdir(p)]
print(f"{len(SRC)} shapes with conditioning renders", flush=True)

TILE, COLS, ROWS = 256, 6, 5
PER = COLS * ROWS
CAP = 16

def pick(d):
    """one consistent near-side view per shape: conditioning views orbit the
    object, so a middle index lands broadside where a roof mast is obvious"""
    fs = sorted(glob.glob(d + "/*.png")) or sorted(glob.glob(d + "/*.jpg"))
    if not fs:
        return None
    return fs[len(fs) // 4]

index, n = [], 0
sheet = page = None
for i, d in enumerate(SRC):
    f = pick(d)
    if not f:
        continue
    if n % PER == 0:
        if sheet:
            sheet.save(f"/root/review/sheets/train_{page:02d}.jpg", quality=88)
        page = n // PER + 1
        sheet = Image.new("RGB", (TILE * COLS, (TILE + CAP) * ROWS), (16, 16, 18))
    dr = ImageDraw.Draw(sheet)
    slot = n % PER
    x, y = (slot % COLS) * TILE, (slot // COLS) * (TILE + CAP)
    try:
        im = Image.open(f).convert("RGB").resize((TILE, TILE))
        sheet.paste(im, (x, y))
    except Exception as e:
        dr.text((x + 6, y + 6), "unreadable", fill=(255, 90, 90))
    tag = os.path.basename(d)[:10]
    dr.text((x + 4, y + TILE + 2), f"#{n+1} {tag}", fill=(230, 230, 120))
    index.append({"n": n + 1, "sheet": page, "sha": os.path.basename(d)})
    n += 1
if sheet:
    sheet.save(f"/root/review/sheets/train_{page:02d}.jpg", quality=88)
json.dump(index, open("/root/review/sheets/INDEX.json", "w"))
print(f"built {page} sheets covering {n} shapes", flush=True)
PY

status upload
if [ -n "$SB_KEY" ]; then
  for f in "$LOCAL"/sheets/*; do
    n=$(basename "$f")
    curl -s -X POST "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/car-meshes/audit/train/$n" \
      -H "apikey: $SB_KEY" -H "Authorization: Bearer $SB_KEY" -H "x-upsert: true" \
      --data-binary @"$f" -o /dev/null -w "$n: %{http_code}\n"
  done
fi

status DONE
ls -la "$LOCAL/sheets" | tail -25
sleep infinity
