#!/bin/bash
# stage_c_subset_audit.sh — measure the pool Stage C ACTUALLY trained on.
#
# The 33 legacy contact sheets cover all 964 ingested shapes, but Stage C
# trained on 365 of them. I said the 365 were "probably worse than average
# because they are the earliest, least-filtered intake" — that was inference,
# not measurement, and the retrain decision hangs on it.
#
# How the subset is identified, from evidence rather than assumption: Stage C
# started at the mtime of /workspace/alam3d_stage_c (Jul 25 00:40) and can only
# have trained on latents that existed by then. Everything encoded later came
# in with the wave-3 ingest on Jul 26. So the split is the latent file mtime
# against the Stage C directory mtime — no guessing which wave a sha came from.
ROOT=/workspace/alamcars
LOCAL=/root/subset
mkdir -p "$LOCAL/sheets"
( cd "$LOCAL" && python3 -m http.server 8000 >/dev/null 2>&1 & )
exec > >(tee -a "$LOCAL/stage_b.log") 2>&1
status(){ printf '{"step":"%s","at":"%s"}\n' "$1" "$(date -u +%FT%TZ)" > "$LOCAL/status.json"; echo "===== $1 ====="; }

status boot
[ -f /etc/rp_environment ] && source /etc/rp_environment
export SB_KEY
# say it out loud: run 1 uploaded nothing and the silent guard below gave no
# clue why. The sheets are served from this pod over :8000 regardless, so the
# upload is a convenience, not the delivery mechanism.
[ -n "$SB_KEY" ] && echo "SB key: present (${#SB_KEY} chars)" || echo "SB key: MISSING — sheets stay on the pod only"
pip install -q pillow pandas || true

status split
python3 - <<'PY'
import glob, json, os, time
import datetime as dt

anchor = os.path.getmtime("/workspace/alam3d_stage_c")
print("Stage C run directory created:", dt.datetime.utcfromtimestamp(anchor).isoformat(), "UTC")

lat = {}
for d in sorted(glob.glob("/workspace/alamcars/shape_latents/*/")):
    for f in glob.glob(d + "*.npz") + glob.glob(d + "*.pt"):
        sha = os.path.splitext(os.path.basename(f))[0]
        m = os.path.getmtime(f)
        # keep the EARLIEST encode time per sha across resolutions
        if sha not in lat or m < lat[sha]:
            lat[sha] = m

pre  = sorted(s for s, m in lat.items() if m <= anchor)
post = sorted(s for s, m in lat.items() if m > anchor)
print(f"latents encoded BEFORE Stage C started : {len(pre)}   <- Stage C's training pool")
print(f"latents encoded AFTER  Stage C started : {len(post)}  <- wave-3 ingest, Stage D only")
json.dump({"pre": pre, "post": post}, open("/root/subset/split.json", "w"))
PY

status build-sheets
python3 - <<'PY'
import glob, json, os
from PIL import Image, ImageDraw

split = json.load(open("/root/subset/split.json"))
pre = set(split["pre"])
dirs = [d for d in sorted(glob.glob("/workspace/alamcars/renders_cond/*"))
        if os.path.isdir(d) and os.path.basename(d) in pre]
print(f"{len(dirs)} of Stage C's shapes have conditioning renders", flush=True)

TILE, COLS, ROWS, CAP = 256, 6, 5, 16
PER = COLS * ROWS
index, n, sheet, page = [], 0, None, 0
for d in dirs:
    fs = sorted(glob.glob(d + "/*.png")) or sorted(glob.glob(d + "/*.jpg"))
    if not fs:
        continue
    if n % PER == 0:
        if sheet:
            sheet.save(f"/root/subset/sheets/stagec_{page:02d}.jpg", quality=88)
        page = n // PER + 1
        sheet = Image.new("RGB", (TILE * COLS, (TILE + CAP) * ROWS), (16, 16, 18))
    dr = ImageDraw.Draw(sheet)
    slot = n % PER
    x, y = (slot % COLS) * TILE, (slot // COLS) * (TILE + CAP)
    try:
        sheet.paste(Image.open(fs[len(fs) // 4]).convert("RGB").resize((TILE, TILE)), (x, y))
    except Exception:
        dr.text((x + 6, y + 6), "unreadable", fill=(255, 90, 90))
    dr.text((x + 4, y + TILE + 2), f"#{n+1} {os.path.basename(d)[:10]}", fill=(230, 230, 120))
    index.append({"n": n + 1, "sheet": page, "sha": os.path.basename(d)})
    n += 1
if sheet:
    sheet.save(f"/root/subset/sheets/stagec_{page:02d}.jpg", quality=88)
json.dump(index, open("/root/subset/sheets/INDEX.json", "w"))
print(f"built {page} sheets covering {n} of Stage C's training shapes", flush=True)
PY

status upload
if [ -n "$SB_KEY" ]; then
  for f in "$LOCAL"/sheets/*; do
    n=$(basename "$f")
    curl -s -X POST "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/car-meshes/audit/stagec/$n" \
      -H "apikey: $SB_KEY" -H "Authorization: Bearer $SB_KEY" -H "x-upsert: true" \
      --data-binary @"$f" -o /dev/null -w "$n: %{http_code}\n"
  done
else
  echo "SKIPPED — no SB_KEY in pod env; fetch the sheets from this pod's :8000/sheets/ instead"
fi
# the sheet names, so they can be pulled off :8000 without guessing
echo "SHEETS: $(ls "$LOCAL/sheets" | tr '\n' ' ')"

status DONE
ls "$LOCAL/sheets" | wc -l
sleep infinity
