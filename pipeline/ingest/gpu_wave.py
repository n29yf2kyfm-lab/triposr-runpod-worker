"""Render a whole sourcing wave through the GPU endpoint instead of local CPU.

`wave_render.py` calls the render worker in-process, which is right for a
handful of cars and hopeless for hundreds: local Cycles runs on 4 CPU cores at
roughly 60-100s per view, so 347 cars x 4 views is about 31 hours. The same
frames on the serverless A-series endpoint take ~6s each and six workers run in
parallel, which brings the same job under two hours.

Per car: fetch the GLB (from the bucket if already staged, else Sketchfab),
verify it, stage it to Supabase so the endpoint can reach it by public URL,
submit the four rubric views, composite the contact sheet locally, upload the
sheet, then delete the local GLB. Every step is resumable against the bucket --
a finished sheet is never re-rendered -- and the local copy is dropped
immediately because this container has reverted ~8 times in a day and disk is
the first thing to fill.

The endpoint must be running an image that contains the ground-height fix
(bounding boxes, not raw mesh vertices) or every car renders floating.

Usage:
    gpu_wave.py --manifest m.json [--stage staging/vwfull] [--sheets audit/vwfull]
                [--limit N] [--parallel 6]
"""
import argparse, base64, io, itertools, json, os, struct, sys, time
import urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

ENV_FILE = "/root/.alam3d_env"


def load_env(path=ENV_FILE):
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


load_env()

SB = "https://tfkvthprsntexrcuqpyd.supabase.co"
BUCKET = "car-meshes"
API = "https://api.sketchfab.com/v3"
EP = os.environ.get("RENDER_ENDPOINT", "ng8oiz4p2l0xa0")
VIEWS = [("front34", 215), ("front34_L", 145), ("side", 270), ("rear34", 35)]
MAX_OBJ = 48_000_000


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def sbk():
    k = os.environ.get("SB_KEY")
    if not k:
        sys.exit("FATAL: SB_KEY not set")
    return k


def rpk():
    k = os.environ.get("RUNPOD_API_KEY")
    if not k:
        sys.exit("FATAL: RUNPOD_API_KEY not set")
    return k


def sb_put(path, blob, ctype):
    rq = urllib.request.Request(f"{SB}/storage/v1/object/{path}", data=blob, method="POST",
        headers={"apikey": sbk(), "Authorization": f"Bearer {sbk()}",
                 "Content-Type": ctype, "x-upsert": "true"})
    return urllib.request.urlopen(rq, timeout=900).status


def sb_list(prefix):
    body = json.dumps({"prefix": prefix, "limit": 2000}).encode()
    rq = urllib.request.Request(f"{SB}/storage/v1/object/list/{BUCKET}", data=body,
        headers={"apikey": sbk(), "Authorization": f"Bearer {sbk()}",
                 "Content-Type": "application/json"})
    try:
        return {o["name"] for o in json.load(urllib.request.urlopen(rq, timeout=180))}
    except Exception:
        return set()


def valid_glb(b):
    """Magic AND the header's own length. Either alone lets a truncated
    download look like a valid file."""
    return len(b) > 20 and b[:4] == b"glTF" and struct.unpack("<I", b[8:12])[0] == len(b)


def render_view(glb_url, az, colour, samples, w, h):
    """Submit one view and wait. Returns (png_bytes, recolour_dict)."""
    body = {"input": {"glb_url": glb_url, "colour": colour, "studio": True,
                      "az": az, "elev": 0.18, "samples": samples,
                      "resx": w, "resy": h}}
    rq = urllib.request.Request(f"https://api.runpod.ai/v2/{EP}/run",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {rpk()}", "Content-Type": "application/json"})
    jid = json.load(urllib.request.urlopen(rq, timeout=90))["id"]
    t0 = time.time()
    while time.time() - t0 < 900:
        srq = urllib.request.Request(f"https://api.runpod.ai/v2/{EP}/status/{jid}",
            headers={"Authorization": f"Bearer {rpk()}"})
        try:
            d = json.load(urllib.request.urlopen(srq, timeout=60))
        except Exception:
            time.sleep(5); continue
        st = d.get("status")
        if st == "COMPLETED":
            o = d.get("output") or {}
            return base64.b64decode(o["png_b64"]), o.get("recolour")
        if st in ("FAILED", "CANCELLED"):
            raise RuntimeError(str(d.get("error"))[:120])
        time.sleep(4)
    raise TimeoutError("render timed out")


def fetch_glb(uid, staged, tok):
    """Bucket first, Sketchfab second. Returns the public URL the endpoint uses."""
    if f"{uid}.glb" in staged:
        return f"{SB}/storage/v1/object/public/{BUCKET}/{{stage}}/{uid}.glb", None
    rq = urllib.request.Request(f"{API}/models/{uid}/download",
        headers={"Authorization": f"Token {next(tok)}", "User-Agent": "Mozilla/5.0"})
    url = (json.load(urllib.request.urlopen(rq, timeout=120)).get("glb") or {}).get("url")
    if not url:
        raise RuntimeError("no glb format offered")
    blob = urllib.request.urlopen(url, timeout=1200).read()
    if not valid_glb(blob):
        raise RuntimeError("bad or truncated glb")
    if len(blob) > MAX_OBJ:
        raise RuntimeError("too big %.0fMB" % (len(blob) / 1e6))
    return None, blob


def sheet(pngs, header, out_path):
    from PIL import Image, ImageDraw, ImageFont
    try:
        FT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 15)
        FS = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
    except Exception:
        FT = FS = ImageFont.load_default()
    ims = [(Image.open(io.BytesIO(b)).convert("RGB"), lab) for b, lab in pngs]
    w, h = ims[0][0].size
    TW = 860; TH = int(h * TW / w); PAD = 28
    s = Image.new("RGB", (TW * 2, (TH + PAD) * 2 + PAD), (14, 14, 16))
    d = ImageDraw.Draw(s)
    d.text((10, 5), header[0], fill=header[1], font=FT)
    for j, (im, lab) in enumerate(ims):
        x = (j % 2) * TW; y = PAD + (j // 2) * (TH + PAD)
        s.paste(im.resize((TW, TH), Image.LANCZOS), (x, y))
        d.text((x + 8, y + TH + 4), lab, fill=(155, 155, 163), font=FS)
    s.save(out_path, quality=90)
    return open(out_path, "rb").read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--stage", default="staging/vwfull")
    ap.add_argument("--sheets", default="audit/vwfull")
    ap.add_argument("--work", default="/tmp/gpuwave")
    ap.add_argument("--colour", default="silver")
    ap.add_argument("--samples", type=int, default=72)
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    os.makedirs(a.work, exist_ok=True)
    rows = json.load(open(a.manifest))
    rows = rows if isinstance(rows, list) else rows.get("candidates", rows)
    if a.limit:
        rows = rows[:a.limit]
    done = {n.split("/")[-1] for n in sb_list(a.sheets + "/")}
    staged = {n.split("/")[-1] for n in sb_list(a.stage + "/")}
    tok = itertools.cycle(os.environ.get("SKETCHFAB_TOKENS", "").split(","))
    log(f"manifest {len(rows)} | already sheeted {len([r for r in rows if r['uid']+'.jpg' in done])}")

    built = 0
    for i, p in enumerate(rows, 1):
        uid = p["uid"]
        if f"{uid}.jpg" in done:
            continue
        try:
            url, blob = fetch_glb(uid, staged, tok)
            if blob is not None:
                sb_put(f"{BUCKET}/{a.stage}/{uid}.glb", blob, "model/gltf-binary")
                log(f"[{i}/{len(rows)}] staged {len(blob)/1e6:.1f}MB  {p['name'][:44]}")
                del blob
            glb_url = f"{SB}/storage/v1/object/public/{BUCKET}/{a.stage}/{uid}.glb"
        except urllib.error.HTTPError as e:
            log(f"[{i}] http-{e.code} {p['name'][:40]}")
            if e.code in (429, 403):
                time.sleep(90)
            continue
        except Exception as e:
            log(f"[{i}] fetch {type(e).__name__}: {str(e)[:60]}")
            continue

        try:
            with ThreadPoolExecutor(max_workers=a.parallel) as ex:
                futs = {lab: ex.submit(render_view, glb_url, az, a.colour,
                                       a.samples, 1000, 562)
                        for lab, az in VIEWS}
                got = {lab: f.result() for lab, f in futs.items()}
        except Exception as e:
            log(f"[{i}] render {type(e).__name__}: {str(e)[:70]}")
            continue

        rc = next((v[1] for v in got.values() if v[1]), None) or {}
        nm = len(rc.get("materials") or [])
        cov = rc.get("coverage") or 0.0
        adv = 1 <= nm <= 2 and 0.05 <= cov <= 0.45
        cw = p.get("class_warn")
        hdr = ("%s  |  %s f  |  body mats=%d cov=%.3f  |  %s%s" % (
                   p["name"][:52], f"{p.get('faces',0):,}", nm, cov,
                   "recolourable" if adv else "MATERIAL SPLIT SUSPECT",
                   ("  |  TAGGED '%s'" % cw) if cw else ""),
               (150, 255, 170) if adv else (255, 170, 170))
        pngs = [(got[lab][0], lab) for lab, _ in VIEWS]
        sp = f"{a.work}/{uid}.jpg"
        try:
            sb_put(f"{BUCKET}/{a.sheets}/{uid}.jpg", sheet(pngs, hdr, sp), "image/jpeg")
        except Exception as e:
            log(f"[{i}] sheet upload {type(e).__name__}"); continue
        for f in (sp,):
            try: os.remove(f)
            except OSError: pass
        built += 1
        log(f"[{i}/{len(rows)}] SHEET mats={nm} cov={cov:.3f} {'OK' if adv else 'split'}"
            f"  {p['name'][:40]}")
    log("GPU_WAVE_DONE", built, "new sheets")


if __name__ == "__main__":
    main()
