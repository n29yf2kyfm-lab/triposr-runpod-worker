"""Capture each staged model's material verdict into the manifest.

gpu_wave stamps `body mats=N cov=X` onto the contact sheet and then throws the
numbers away. That was a mistake: the verdict is the single best predictor of
whether a sourced GLB is a finished car or an untextured shell, and having it
only as pixels means the wave cannot be sorted, filtered or measured -- the
owner has to eyeball 325 sheets to find the ones that were never candidates.

Measured on seven reviewed cars, the split is clean:

    coverage >= 0.89   one material spans the whole car: windows solid body
                       colour, no lamp lenses, flat grille  -- "half baked"
    coverage <= 0.20   separate glass, lamps and wheel materials -- a real car

Passat B8 Variant 0.940, Crafter 1.000, Golf VIII 0.894 all failed the owner's
rubric on grille depth, headlight internals and shut lines. Golf GTI 2014 at
0.095 and Golf R Variant at 0.171 passed. So this one number pre-sorts the
review queue.

This runs the cheapest possible render (320x180, 8 samples, ~6s) purely to make
the worker classify materials, and writes mats/coverage/paint_named back onto
the manifest row. It renders nothing anyone looks at.

Usage:
    verdict_pass.py [--sheets audit/vwfull] [--stage staging/vwfull]
                    [--parallel 6] [--limit N]
"""
import argparse, json, os, sys, time, urllib.request
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
EP = os.environ.get("RENDER_ENDPOINT", "ng8oiz4p2l0xa0")


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


def sb_get(path):
    rq = urllib.request.Request(f"{SB}/storage/v1/object/{path}",
        headers={"apikey": sbk(), "Authorization": f"Bearer {sbk()}"})
    return urllib.request.urlopen(rq, timeout=300).read()


def sb_put(path, blob, ctype):
    rq = urllib.request.Request(f"{SB}/storage/v1/object/{path}", data=blob, method="POST",
        headers={"apikey": sbk(), "Authorization": f"Bearer {sbk()}",
                 "Content-Type": ctype, "x-upsert": "true"})
    return urllib.request.urlopen(rq, timeout=600).status


def verdict(uid, stage):
    """One throwaway render, just to make the worker classify materials."""
    body = {"input": {
        "glb_url": f"{SB}/storage/v1/object/public/{BUCKET}/{stage}/{uid}.glb",
        "colour": "silver", "studio": True, "az": 215, "elev": 0.18,
        "samples": 8, "resx": 320, "resy": 180}}
    rq = urllib.request.Request(f"https://api.runpod.ai/v2/{EP}/run",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {rpk()}", "Content-Type": "application/json"})
    jid = json.load(urllib.request.urlopen(rq, timeout=90))["id"]
    t0 = time.time()
    while time.time() - t0 < 600:
        try:
            d = json.load(urllib.request.urlopen(urllib.request.Request(
                f"https://api.runpod.ai/v2/{EP}/status/{jid}",
                headers={"Authorization": f"Bearer {rpk()}"}), timeout=60))
        except Exception:
            time.sleep(4); continue
        st = d.get("status")
        if st == "COMPLETED":
            return (d.get("output") or {}).get("recolour") or {}
        if st in ("FAILED", "CANCELLED"):
            raise RuntimeError(str(d.get("error"))[:100])
        time.sleep(3)
    raise TimeoutError


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheets", default="audit/vwfull")
    ap.add_argument("--stage", default="staging/vwfull")
    ap.add_argument("--parallel", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    mpath = f"{BUCKET}/{a.sheets}/_manifest.json"
    rows = json.loads(sb_get(mpath))
    todo = [r for r in rows if r.get("coverage") is None
            and r.get("publicationStatus") != "quarantined"]
    if a.limit:
        todo = todo[:a.limit]
    log(f"manifest {len(rows)} | needing a verdict {len(todo)}")

    done = 0
    lock_every = 25

    def work(r):
        try:
            v = verdict(r["uid"], a.stage)
            r["bodyMaterials"] = len(v.get("materials") or [])
            r["coverage"] = round(float(v.get("coverage") or 0.0), 3)
            r["paintNamed"] = bool(v.get("paint_named"))
            r["shellSuspect"] = r["coverage"] >= 0.89
            return True
        except Exception as e:
            r["verdictError"] = f"{type(e).__name__}"
            return False

    with ThreadPoolExecutor(max_workers=a.parallel) as ex:
        for i, ok in enumerate(ex.map(work, todo), 1):
            done += bool(ok)
            if i % lock_every == 0 or i == len(todo):
                try:
                    sb_put(mpath, json.dumps(rows, indent=1).encode(), "application/json")
                except Exception:
                    pass
                got = [r for r in rows if r.get("coverage") is not None]
                shell = [r for r in rows if r.get("shellSuspect")]
                log(f"[{i}/{len(todo)}] captured={len(got)} shell-suspect={len(shell)}")
    sb_put(mpath, json.dumps(rows, indent=1).encode(), "application/json")
    got = [r for r in rows if r.get("coverage") is not None]
    shell = [r for r in got if r.get("shellSuspect")]
    log("VERDICT_PASS_DONE", f"{len(got)} verdicts, {len(shell)} shell-suspect "
        f"({100*len(shell)/max(1,len(got)):.0f}%)")


if __name__ == "__main__":
    main()
