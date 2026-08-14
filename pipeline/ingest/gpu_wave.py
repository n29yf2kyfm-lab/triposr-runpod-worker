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
import argparse, base64, datetime, io, itertools, json, os, struct, sys, time
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
# Sketchfab download throttling. RATE_RETRIES attempts after the first failure,
# waiting RATE_BACKOFF * 2**n seconds (60/120/240 = ~7 min of patience) before a
# row is written off as RATE-DROP.
RATE_RETRIES = int(os.environ.get("WAVE_RATE_RETRIES", "3"))
RATE_BACKOFF = int(os.environ.get("WAVE_RATE_BACKOFF", "60"))
# Consecutive rows lost to throttling before the wave aborts (resumable).
RATE_ABORT = int(os.environ.get("WAVE_RATE_ABORT", "5"))
# Token-pool size, set in main(). Attempts below this only ROTATE (no sleep):
# with per-account throttling, a fresh token succeeds immediately.
NTOK = 1


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


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geom_audit import geom_signals, verdict as geom_verdict   # noqa: E402


def render_view(glb_url, az, colour, samples, w, h, audit=False):
    """Submit one view and wait. Returns (png_bytes, recolour_dict, audit_dict).

    `audit` asks the handler for its pose block (glass_zf/glass_af). It is set on
    ONE view per car, not all four: the handler runs an extra geometry pass for it,
    and the pose of a car does not change with camera azimuth.
    """
    body = {"input": {"glb_url": glb_url, "colour": colour, "studio": True,
                      "az": az, "elev": 0.18, "samples": samples,
                      "resx": w, "resy": h, "audit": bool(audit)}}
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
            return base64.b64decode(o["png_b64"]), o.get("recolour"), o.get("audit")
        if st in ("FAILED", "CANCELLED"):
            raise RuntimeError(str(d.get("error"))[:120])
        time.sleep(4)
    raise TimeoutError("render timed out")


HARD_REJECTS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "HARD_REJECTS.json")


def load_hard_rejects():
    """uids that can NEVER succeed: over MAX_OBJ, or no GLB format offered.

    Without this the wave re-downloads them on every rerun and throws them away
    -- 30 rows on the live Nissan/Fiat/Citroen waves, 48-94MB each. Sketchfab
    download quota is the scarce resource (it is what stalled the waves), so
    spending it re-proving a known-permanent failure is the worst possible use
    of it. Distinct from REJECTS.json, which is the OWNER'S review ledger.
    Fails open: an unreadable cache just means nothing is skipped."""
    try:
        return {r["uid"]: r for r in json.load(open(HARD_REJECTS))}
    except Exception:
        return {}


def add_hard_reject(uid, name, reason):
    """Append-only. Re-read before write so concurrent waves don't clobber."""
    try:
        cur = load_hard_rejects()
        if uid in cur:
            return
        cur[uid] = {"uid": uid, "name": (name or "")[:80], "reason": reason,
                    "at": datetime.date.today().isoformat()}
        tmp = HARD_REJECTS + ".tmp"
        json.dump(sorted(cur.values(), key=lambda r: r["uid"]),
                  open(tmp, "w"), indent=1, ensure_ascii=False)
        os.replace(tmp, HARD_REJECTS)
    except Exception as e:
        log(f"hard-reject cache write failed ({type(e).__name__}) -- continuing")


def fetch_glb(uid, staged, tok):
    """Bucket first, Sketchfab second. Returns the GLB bytes, or None when the
    uid is already staged in the bucket (nothing to download or upload).
    (Used to also return a URL; it was never read, and the bucket-hit branch's
    version contained a literal unexpanded "{stage}" placeholder, so any future
    caller trusting it would have fetched a 404. Removed.)"""
    if f"{uid}.glb" in staged:
        return None
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
    return blob


def pose_repair(uid, blob, stage, workdir):
    """Try to stand a pose-rejected car back on its wheels; None = not fixable.

    Wraps pipeline/ingest/pose_fix.py: TYRE-evidence only (no --allow-proxy —
    a wave must never roll a car on a proxy signal), verifies the WRITTEN file,
    and re-stages it over the original so every later stage sees the fixed car.
    Fails closed: any exception returns None and the normal reject stands.
    """
    try:
        from pose_fix import plan, apply_rotation, score
        os.makedirs(workdir, exist_ok=True)
        src = os.path.join(workdir, f"{uid}.fix_in.glb")
        dst = os.path.join(workdir, f"{uid}.fix_out.glb")
        if blob is not None:
            open(src, "wb").write(blob)
        else:
            return None
        rows_, best, named = plan(src, allow_proxy=False)
        if best is None or best[0] == "identity" or not named:
            return None
        apply_rotation(src, dst, best[1])
        ver, _, _ = plan(dst, allow_proxy=False)
        vm = ver[0][2]                      # identity row of the OUTPUT
        if score(vm, False) is None:
            return None                     # written file is not upright
        data = open(dst, "rb").read()
        sb_put(f"{BUCKET}/{stage}/{uid}.glb", data, "model/gltf-binary")
        return f"{best[0]} tyre_y={vm['tyre_y']}"
    except Exception:
        return None
    finally:
        for f in (locals().get("src"), locals().get("dst")):
            try:
                if f: os.remove(f)
            except OSError:
                pass


def pose_gate(uid, blob, glb_url, workdir):
    """LOCAL pose gate, run BEFORE any GPU render is submitted.

    Computes geom_audit's signals from the GLB itself (trimesh, world-space
    verts), so it cannot be contaminated by the render worker's studio floor --
    the flaw that made the handler-side audit unusable (a 1977 Accord reported
    h_over_l=0.101 against a true 0.317, floor is 2.5x the car).

    Validated 2026-08-09 against staged ground truth: rejects the wheels-up
    J100 (tob=1.47) and the on-side ML W163 (h/l=0.05); passes the GR86, a
    saloon and a Hilux pickup (low-top warn only). KNOWN LIMIT: it reads the
    SOURCE mesh, so it cannot catch render-side inversion -- the upside-down
    Camry XV30 sheet came from a geometrically upright GLB (h/l=0.305,
    tob=0.775): the worker flipped it at render time, consistent with the ~8%
    inversion rate measured on the Honda wave. That is a separate worker bug,
    still open. Fails open: any error returns ok so the wave never dies here.
    """
    path = os.path.join(workdir, f"{uid}.pose.glb")
    try:
        os.makedirs(workdir, exist_ok=True)
        if blob is not None:
            open(path, "wb").write(blob)
        else:
            rq = urllib.request.urlopen(glb_url, timeout=600)
            with open(path, "wb") as f:
                while True:
                    c = rq.read(1 << 20)
                    if not c:
                        break
                    f.write(c)
        g = geom_signals(path)
        return geom_verdict(g, None, None)
    except Exception as e:
        return "ok", [f"pose-gate-skipped:{type(e).__name__}"]
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


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
    global NTOK
    _toks = [t for t in os.environ.get("SKETCHFAB_TOKENS", "").split(",") if t.strip()]
    NTOK = max(1, len(_toks))
    tok = itertools.cycle(_toks)
    hard = load_hard_rejects()
    log(f"manifest {len(rows)} | already sheeted "
        f"{len([r for r in rows if r['uid']+'.jpg' in done])} | "
        f"hard-rejected {len([r for r in rows if r['uid'] in hard])}")

    built = 0
    rate_streak = 0            # consecutive RATE-DROPs -> circuit breaker
    for i, p in enumerate(rows, 1):
        uid = p["uid"]
        if f"{uid}.jpg" in done:
            continue
        if uid in hard:
            continue        # known-permanent: never spend download quota again
        # -- Phase 1: Sketchfab download. Throttling (429/403), network drops
        # and truncated bodies are all TRANSIENT here and retried with backoff
        # -- the old code dropped the car (429: after one blind 90s sleep;
        # network errors and truncation: instantly), which is how three
        # concurrent waves sharing the token pool ate their manifests producing
        # nothing. Retry-After is honoured when Sketchfab sends it (same
        # pattern as pipeline/geometry/fetch_dims.py). "no glb format offered"
        # and "too big" are PERMANENT: they spend no retry budget.
        # next(tok) inside fetch_glb rotates the token on every attempt.
        blob = None            # stays None on a bucket hit -- nothing to upload
        fetched = False
        for attempt in range(RATE_RETRIES + 1):
            try:
                blob = fetch_glb(uid, staged, tok)
                fetched = True
                rate_streak = 0
                break
            except urllib.error.HTTPError as e:
                if e.code in (429, 403) and attempt < RATE_RETRIES:
                    ra = int((e.headers.get("Retry-After", 0) if e.headers else 0) or 0)
                    # Each attempt rotates to the NEXT token, so while untried
                    # tokens remain the fix is rotation, not waiting -- sleeping
                    # here just burns wall-clock on an account that may be fine.
                    # Only back off once a full cycle has been tried and every
                    # account is genuinely throttled. (Retry-After still wins.)
                    if attempt + 1 < NTOK and not ra:
                        continue
                    wait = max(RATE_BACKOFF * (2 ** max(0, attempt - NTOK + 1)), ra)
                    log(f"[{i}/{len(rows)}] http-{e.code} all {NTOK} tokens throttled, "
                        f"retry {attempt+1}/{RATE_RETRIES} in {wait}s  {p['name'][:30]}")
                    time.sleep(wait)
                    continue
                # RATE-DROP is deliberately distinct from other failures so a
                # wave's lost-to-throttling count is greppable afterwards.
                # (RATE-DROP-403 vs -429 stays distinguishable in the log: a
                # sustained 403 wall is revoked tokens or a non-downloadable
                # model, not congestion.)
                tag = "RATE-DROP" if e.code in (429, 403) else "http"
                log(f"[{i}/{len(rows)}] {tag}-{e.code} giving up  {p['name'][:40]}")
                if tag == "RATE-DROP":
                    rate_streak += 1
                break
            except OSError as e:
                # URLError / socket timeout / connection reset mid-blob: the
                # same silent-drop class the 429 fix was for. Short retry.
                if attempt < RATE_RETRIES:
                    log(f"[{i}/{len(rows)}] net {type(e).__name__} retry "
                        f"{attempt+1}/{RATE_RETRIES}  {p['name'][:36]}")
                    time.sleep(10)
                    continue
                log(f"[{i}/{len(rows)}] NET-DROP {type(e).__name__}: {str(e)[:50]}")
                break
            except RuntimeError as e:
                if "truncated" in str(e) and attempt < RATE_RETRIES:
                    log(f"[{i}/{len(rows)}] truncated glb, refetch "
                        f"{attempt+1}/{RATE_RETRIES}  {p['name'][:36]}")
                    time.sleep(10)
                    continue
                msg = str(e)
                # "too big" and "no glb format offered" can never change on a
                # rerun -- cache them so the download is never repeated.
                if "too big" in msg or "no glb format" in msg:
                    add_hard_reject(uid, p.get("name"), msg[:60])
                    hard[uid] = True
                    log(f"[{i}/{len(rows)}] HARD-REJECT {msg[:50]}  {p['name'][:34]}")
                else:
                    log(f"[{i}/{len(rows)}] fetch {msg[:60]}")
                break
            except Exception as e:
                log(f"[{i}/{len(rows)}] fetch {type(e).__name__}: {str(e)[:60]}")
                break
        if not fetched:
            # Circuit breaker: when EVERY row is rate-dropping the token pool
            # is saturated and per-row patience just burns hours producing
            # nothing (~7 min sleep/row). The wave is resumable by design
            # (done/staged are re-checked against the bucket), so abort and
            # let a later rerun pick these rows up.
            if rate_streak >= RATE_ABORT:
                log(f"CIRCUIT-BREAK {rate_streak} consecutive RATE-DROPs -- "
                    f"token pool saturated; aborting resumable wave at row {i}")
                break
            continue

        # -- Phase 2: stage to Supabase. A failure here is NOT Sketchfab
        # throttling: the blob is already in memory, so retry the upload alone
        # -- never re-download (that burns the rate-limited quota) and never
        # label it RATE-DROP (that corrupts the throttling stats).
        try:
            if blob is not None:
                for up in range(2):
                    try:
                        sb_put(f"{BUCKET}/{a.stage}/{uid}.glb", blob, "model/gltf-binary")
                        break
                    except Exception:
                        if up == 1:
                            raise
                        time.sleep(10)
                log(f"[{i}/{len(rows)}] staged {len(blob)/1e6:.1f}MB  {p['name'][:44]}")
        except Exception as e:
            log(f"[{i}/{len(rows)}] SB-DROP upload {type(e).__name__}: {str(e)[:50]}")
            continue
        glb_url = f"{SB}/storage/v1/object/public/{BUCKET}/{a.stage}/{uid}.glb"

        # LOCAL pose gate: reject mis-oriented source meshes BEFORE spending
        # four GPU renders on them. See pose_gate docstring for what it can
        # and cannot catch.
        pose, preasons = pose_gate(uid, blob, glb_url, a.work)
        if pose == "reject":
            # AUTO-REPAIR (2026-08-14): a wrong pose is a rigid transform, not
            # a bad mesh — every car this gate caught used to be scrapped, and
            # the Tucson proved several are good cars stored 180 degrees over.
            # pose_fix decides on TYRE-height evidence and REFUSES when it
            # cannot stand the car on its wheels, so a genuine wreck still
            # falls through to the reject below. On success the FIXED file
            # replaces the staged one and the wave carries on.
            fixed = pose_repair(uid, blob, a.stage, a.work)
            if fixed:
                log(f"[{i}/{len(rows)}] POSE-FIXED {fixed}  {p['name'][:40]}")
            else:
                log(f"[{i}/{len(rows)}] POSE-REJECT {','.join(preasons)[:70]}  {p['name'][:40]}")
                del blob
                continue
        del blob

        try:
            with ThreadPoolExecutor(max_workers=a.parallel) as ex:
                futs = {lab: ex.submit(render_view, glb_url, az, a.colour,
                                       a.samples, 1000, 562, False)
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

        # Pose verdict (pose, preasons) came from the LOCAL pre-render gate
        # above. The handler-side audit that briefly stood here never ran (no
        # "geom" key in its payload) and its signals are contaminated by the
        # studio floor; the render-side inversion bug it also cannot see is
        # tracked separately. audit=True is no longer requested from the worker.

        # C-gate: body-paint coverage, TWO-SIDED. Both tails are unsafe to recolour.
        #
        # LOW (<0.12): measured across the Mercedes clean set 2026-08-08 -- every car
        # under ~0.10 rendered its OWN colour under a forced one, because the classifier
        # had matched trim or a badge rather than body paint. The boundary is a gradient,
        # not a cliff, hence the 0.12 cutoff rather than 0.10.
        #
        # HIGH (>0.90): one material covering the WHOLE model -- glass, tyres and trim
        # as well as the body. It recolours "successfully" by every metric and repaints
        # the entire car, glass included. This is not hypothetical: toyota-auris-v1 was
        # RETIRED for it on 2026-07-21 ("covers body+glass+trim, recolour would overspill
        # onto glass"), and four Peugeots in the current wave sit at cov=1.000.
        #
        # Both WARN and never reject: recolour_audit --stamp stays the only proof.
        low_cov = 0.0 < cov < 0.12 or cov > 0.90
        flags = ""
        if pose == "reject": flags += "  |  POSE REJECT: " + ",".join(preasons)[:60]
        elif preasons:       flags += "  |  pose: " + ",".join(preasons)[:50]
        if low_cov:
            flags += ("  |  FULL COVERAGE, respray would repaint glass too" if cov > 0.90
                      else "  |  LOW COVERAGE, respray may not take")
        hdr = ("%s  |  %s f  |  body mats=%d cov=%.3f  |  %s%s%s" % (
                   p["name"][:52], f"{p.get('faces',0):,}", nm, cov,
                   "recolourable" if adv else "MATERIAL SPLIT SUSPECT",
                   ("  |  TAGGED '%s'" % cw) if cw else "", flags),
               (255, 120, 120) if pose == "reject"
               else (150, 255, 170) if (adv and not low_cov) else (255, 170, 170))
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
        log(f"[{i}/{len(rows)}] SHEET mats={nm} cov={cov:.3f} "
            f"{'POSE-REJECT' if pose == 'reject' else 'OK' if adv else 'split'}"
            f"{(' FULLCOV' if cov > 0.90 else ' LOWCOV') if low_cov else ''}  {p['name'][:40]}")
    log("GPU_WAVE_DONE", built, "new sheets")


if __name__ == "__main__":
    main()
