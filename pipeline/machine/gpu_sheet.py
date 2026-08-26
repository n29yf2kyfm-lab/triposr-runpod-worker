#!/usr/bin/env python3
"""gpu_sheet.py — a captioned 4-view OPTIX studio sheet for any GLB URL.

WHY THIS IS A COMMITTED TOOL AND NOT A SCRATCH SCRIPT. It has now been written
three times: once for the Yaris slice, once for the TRELLIS van, and once here.
Each of the first two lived only in /tmp and a container rollback took it, so
the next comparison started by rebuilding the renderer instead of looking at
cars. Origin survives rollbacks; /tmp does not (CLAUDE.md, standing order).

WHAT IT RENDERS, and why it is the PRODUCTION rig rather than a local Blender.
Frames come from the render serverless endpoint (OPTIX). That matters for a
material verdict: the worker FORCES transmission=1.0 onto any material whose
name matches its glass regex, so a local render of our authored BLEND glass and
the production render of the same file are different pictures, and only the
production one shows what a customer's poster would. CLAUDE.md records this
costing a wrong "clean rear" verdict twice in one session.

THE CAPTION IS NOT DECORATION. The council audit of 2026-08-16 cost a review
round to an uncaptioned pair of tiles nobody could tell apart, and the naming
trap of 2026-08-20 cost an hour to a mesh whose FILE NAME said Golf and whose
badge said Toyota. Every tile therefore carries its azimuth, and the sheet
carries the label, the source URL and the render date, burned into the image
where they cannot drift away from it.

AZIMUTH CONVENTION (burned renders discovering it twice — CLAUDE.md):
for a glTF Y-up car with its length on X, az 0/180 are the SIDE views, az
90/270 are END-ON, and 35/125/215/305 are the four three-quarters. A car
authored length-on-Z shows different views at the same az, so match tiles
against a control rather than against this note.

Run:
  python3 gpu_sheet.py --glb <public-glb-url> --label "Pixal van v1" \\
      --out /tmp/VAN_SHEET.png [--az 35,125,215,305] [--samples 110]
"""
import argparse
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

EP = os.environ.get("RENDER_ENDPOINT", "ng8oiz4p2l0xa0")
DEFAULT_AZ = [35, 125, 215, 305]


def load_env(path="/root/.alam3d_env"):
    """Load credentials HERE rather than trusting the caller to source them.

    A relaunch that forgot to source the env file once died one line in and the
    failure was indistinguishable from a healthy start (CLAUDE.md).
    """
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


def render(glb_url, az, elev, samples, w, h, rp, timeout=1500):
    """One frame from the OPTIX worker. Returns PNG bytes."""
    body = {"input": {"glb_url": glb_url, "recolour": "off", "studio": True,
                      "az": az, "elev": elev, "samples": samples,
                      "width": w, "height": h}}
    jid = None
    last = ""
    for _ in range(10):
        try:
            rq = urllib.request.Request(
                f"https://api.runpod.ai/v2/{EP}/run",
                data=json.dumps(body).encode(),
                headers={"Authorization": "Bearer " + rp,
                         "Content-Type": "application/json"})
            jid = json.load(urllib.request.urlopen(rq, timeout=90))["id"]
            break
        except urllib.error.HTTPError as e:
            # 409 while the endpoint settles after a recycle is NOT a failure —
            # it is the documented first-submit behaviour. Back off and retry.
            last = f"HTTP {e.code}"
            time.sleep(15)
        except Exception as e:                      # noqa: BLE001
            last = f"{type(e).__name__}"
            time.sleep(15)
    if not jid:
        raise RuntimeError(f"submit failed ({last})")

    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            d = json.load(urllib.request.urlopen(urllib.request.Request(
                f"https://api.runpod.ai/v2/{EP}/status/{jid}",
                headers={"Authorization": "Bearer " + rp}), timeout=60))
        except Exception:                           # noqa: BLE001
            time.sleep(6)
            continue
        st = d.get("status")
        if st == "COMPLETED":
            png = (d.get("output") or {}).get("png_b64")
            if not png:
                raise RuntimeError("COMPLETED but no png_b64 in output")
            return base64.b64decode(png)
        if st in ("FAILED", "CANCELLED"):
            raise RuntimeError(str(d.get("error"))[:140])
        time.sleep(6)
    raise TimeoutError(f"az{az} still running after {timeout}s")


def _font(size):
    from PIL import ImageFont
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:                       # noqa: BLE001
                pass
    return ImageFont.load_default()


def build_sheet(frames, label, src, out):
    """2x2 tiles, each captioned with its azimuth; header names the asset."""
    from PIL import Image, ImageDraw
    tiles = [Image.open(io.BytesIO(b)).convert("RGB") for _, b in frames]
    tw, th = tiles[0].size
    cap, head = 34, 76
    sheet = Image.new("RGB", (tw * 2, head + (th + cap) * 2), (18, 18, 20))
    d = ImageDraw.Draw(sheet)
    d.text((16, 12), label, font=_font(30), fill=(255, 255, 255))
    d.text((16, 48), f"{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}  "
                     f"OPTIX studio  |  {src[-92:]}",
           font=_font(17), fill=(150, 150, 158))
    for i, ((az, _), t) in enumerate(zip(frames, tiles)):
        x, y = (i % 2) * tw, head + (i // 2) * (th + cap)
        sheet.paste(t, (x, y))
        d.text((x + 12, y + th + 7), f"az {az}", font=_font(22),
               fill=(235, 235, 240))
    sheet.save(out)
    return sheet.size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glb", required=True, help="PUBLIC glb url")
    ap.add_argument("--label", required=True, help="burned into the sheet")
    ap.add_argument("--out", required=True)
    ap.add_argument("--az", default=",".join(map(str, DEFAULT_AZ)))
    ap.add_argument("--elev", type=float, default=0.13)
    ap.add_argument("--samples", type=int, default=110)
    ap.add_argument("--width", type=int, default=1200)
    ap.add_argument("--height", type=int, default=800)
    ap.add_argument("--parallel", type=int, default=4)
    a = ap.parse_args()

    load_env()
    rp = os.environ.get("RUNPOD_API_KEY") or sys.exit("FATAL: RUNPOD_API_KEY not set")
    azs = [int(x) for x in a.az.split(",") if x.strip()]

    # cache-bust: the worker must never serve a stale copy of a re-uploaded GLB
    url = a.glb + ("&" if "?" in a.glb else "?") + f"cb={int(time.time())}"

    def one(az):
        t0 = time.time()
        png = render(url, az, a.elev, a.samples, a.width, a.height, rp)
        print(f"  az {az:>3}  ok  {time.time()-t0:5.1f}s  {len(png)//1024} KB",
              flush=True)
        return az, png

    print(f"rendering {len(azs)} views on {EP} (OPTIX): {azs}", flush=True)
    with ThreadPoolExecutor(max_workers=a.parallel) as ex:
        frames = sorted(ex.map(one, azs), key=lambda f: azs.index(f[0]))

    size = build_sheet(frames, a.label, a.glb, a.out)
    print(f"wrote {a.out}  {size[0]}x{size[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
