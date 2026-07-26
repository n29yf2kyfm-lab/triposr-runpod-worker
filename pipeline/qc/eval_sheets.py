#!/usr/bin/env python3
"""eval_sheets.py — render base-vs-Alam-3D comparison sheets for the fine-tune
eval, per the visual-review standard (the owner judges renders, not metrics).

Reads the eval GLBs from car-meshes/eval/<RUN_ID>/, renders 4 studio angles of
each through the render endpoint, and composes one sheet per case:
top row = stock TRELLIS.2, bottom row = Alam-3D.

  python3 pipeline/qc/eval_sheets.py <RUN_ID> [--cases gti] [--label "ckpt 4000"]

Env: RUNPOD_API_KEY (render endpoint). No secrets in this file.
"""
import argparse, base64, io, json, os, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageDraw

EP = os.environ.get("RENDER_ENDPOINT", "ng8oiz4p2l0xa0")
PUB = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/public/car-meshes/eval"
AZS = [35, 125, 215, 305]
OUTDIR = os.environ.get("SHEET_OUT", "/tmp")
# row label per GLB tag; --tags picks which rows a sheet gets
ROW_LABELS = {
    "base":   "STOCK TRELLIS.2  (stock 512 + stock 1024)",
    "alam3d": "ALAM-3D          (tuned 512 + tuned 1024)",
    "conly":  "STAGE C ONLY     (tuned 512 + stock 1024)",
    "donly":  "STAGE D ONLY     (stock 512 + tuned 1024)",
    "cd":     "STAGE C + D      (tuned 512 + tuned 1024)",
}


def rp(url, key, body=None):
    rq = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                method="POST" if body else "GET",
                                headers={"Authorization": "Bearer " + key,
                                         "Content-Type": "application/json"})
    for a in range(6):
        try:
            return json.loads(urllib.request.urlopen(rq, timeout=150).read())
        except Exception:
            time.sleep(3 * (a + 1))
    return {}


def render(key, glb_url, az):
    j = rp(f"https://api.runpod.ai/v2/{EP}/run", key,
           {"input": {"glb_url": glb_url + f"?cb={int(time.time())}", "recolour": "off",
                      "studio": True, "az": az, "elev": 0.06, "samples": 110,
                      "width": 640, "height": 420}})
    jid = j.get("id")
    if not jid:
        return None
    for _ in range(120):
        st = rp(f"https://api.runpod.ai/v2/{EP}/status/{jid}", key)
        if st.get("status") == "COMPLETED":
            b = (st.get("output") or {}).get("png_b64")
            return Image.open(io.BytesIO(base64.b64decode(b))) if b else None
        if st.get("status") in ("FAILED", "CANCELLED"):
            return None
        time.sleep(5)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("--cases", default="golf,model3,escape")
    ap.add_argument("--label", default="ALAM-3D v0")
    ap.add_argument("--tags", default="base,alam3d",
                    help="GLB variants to stack as rows, e.g. base,conly,donly,cd")
    a = ap.parse_args()
    key = os.environ.get("RUNPOD_API_KEY")
    if not key:
        sys.exit("RUNPOD_API_KEY missing from env")
    cases = [c for c in a.cases.split(",") if c]
    tags = [t for t in a.tags.split(",") if t]

    jobs = [(c, t, az) for c in cases for t in tags for az in AZS]
    results = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(render, key, f"{PUB}/{a.run_id}/{c}_{t}.glb", az): (c, t, az)
                for c, t, az in jobs}
        for f in futs:
            c, t, az = futs[f]
            results[(c, t, az)] = f.result()
            print(f"{c}/{t}/az{az}: {'ok' if results[(c, t, az)] else 'FAIL'}", flush=True)

    W, H, BAND = 640, 420, 26
    for c in cases:
        sheet = Image.new("RGB", (W * 4, (H + BAND) * len(tags)), (12, 12, 14))
        d = ImageDraw.Draw(sheet)
        for row, t in enumerate(tags):
            y = row * (H + BAND)
            # paste FIRST, label after: drawing the text first put it under the
            # images, which is why earlier sheets came out with no row captions
            for col, az in enumerate(AZS):
                im = results.get((c, t, az))
                if im:
                    sheet.paste(im.convert("RGB").resize((W, H)), (col * W, y + BAND))
            label = ROW_LABELS.get(t, t.upper())
            if t not in ("base",) and a.label != "ALAM-3D v0":
                label = f"{label}   [{a.label}]"
            d.text((10, y + 7), f"{c.upper()}  —  {label}", fill=(255, 220, 60))
        out = os.path.join(OUTDIR, f"eval_{c}_sheet.jpg")
        sheet.save(out, quality=86)
        print("sheet:", out)


if __name__ == "__main__":
    main()
