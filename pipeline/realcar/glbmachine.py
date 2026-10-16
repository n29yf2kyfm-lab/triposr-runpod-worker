#!/usr/bin/env python3
"""glbmachine — ExpertCarCheck's GLB machine as one program.

Ask for a car in plain words; get back an interactive GLB: doors, bonnet and
tailgate that open (named clips), clear glass, the model's cabin, a generic
engine bay and exhaust, painted the colour asked for. No Blender.

    glbmachine setup                          # once: node tools + work folder
    glbmachine make "Nissan Micra 2004 red"   # one car -> web.glb (+ sheet.jpg)
    glbmachine make "VW Polo 2019" --no-sheet # the car only, in seconds
    glbmachine batch --top 20 --workers 3     # the UK best sellers
    glbmachine rig CAR.glb OUT_DIR            # the rig step alone
    glbmachine serve --port 8080              # the web API (below)
    glbmachine version

WORK FOLDER: $GLBMACHINE_HOME (default ~/.glbmachine) holds view/ (the check
sheet page, served to a headless browser) and view/cars/ (every car built).

WEB API (`serve`):
    POST /v1/cars            {"request": "Ford Fiesta 2015 blue", "sheet": false,
                              "nearest": false}  -> 202 {"id", "status"}
    GET  /v1/cars/ID         -> {"id", "status": queued|building|done|failed, "report", "files"}
    GET  /v1/cars/ID/car.glb    the finished car (meshopt-compressed)
    GET  /v1/cars/ID/sheet.jpg  the four-view check sheet, when asked for
    GET  /health
If $GLBMACHINE_KEYS is set (comma-separated), every /v1 call needs one of
them as `Authorization: Bearer KEY` or `X-API-Key: KEY` — the hook for
licence keys. $GLBMACHINE_WORKERS cars are built side by side (default 2).

NEEDS: Python 3.10+ with numpy, scipy and Pillow; Node 18+ (decode, validate,
web copy); Chromium only for check sheets ($CHROME_PATH).
"""
import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
VERSION = "1.0.0"
HOME = os.path.abspath(os.path.expanduser(os.environ.get("GLBMACHINE_HOME", "~/.glbmachine")))
VIEW = os.path.join(HOME, "view")
CARS = os.path.join(VIEW, "cars")
ENGINE_PACK = os.path.join(HERE, "assets", "engine_pack.glb")
TOOLS = os.environ.get("GLBMACHINE_TOOLS", HERE)      # holds node_modules and the .mjs tools


def setup(quiet=False):
    """Node tools installed and the work folder laid out. Safe to run again."""
    if not os.path.isdir(os.path.join(TOOLS, "node_modules", "@gltf-transform")):
        subprocess.run(["npm", "install", "--no-audit", "--no-fund"], cwd=TOOLS, check=True,
                       stdout=subprocess.DEVNULL if quiet else None)
    os.makedirs(CARS, exist_ok=True)
    shutil.copyfile(os.path.join(HERE, "view.html"), os.path.join(VIEW, "index.html"))
    lib = os.path.join(VIEW, "lib")
    os.makedirs(lib, exist_ok=True)
    three = os.path.join(TOOLS, "node_modules", "three")
    for name, target in (("three.module.js", os.path.join(three, "build", "three.module.js")),
                         ("addons", os.path.join(three, "examples", "jsm"))):
        link = os.path.join(lib, name)
        if not os.path.lexists(link):
            os.symlink(target, link)
    return {"home": HOME, "tools": TOOLS, "engine_pack": ENGINE_PACK}


def make(request, sheet=True, nearest=False, no_source=False, out=None, port=8791):
    import make as mk
    setup(quiet=True)
    return mk.build(request, ENGINE_PACK, TOOLS, VIEW, out or CARS, port, nearest, no_source, not sheet)


def rig(src, out):
    """Decode (Draco / meshopt / quantized -> plain) then rig."""
    os.makedirs(out, exist_ok=True)
    plain = os.path.join(out, "plain.glb")
    subprocess.run(["node", os.path.join(TOOLS, "decode.mjs"), src, plain], check=True, stdout=subprocess.DEVNULL)
    p = subprocess.run([sys.executable, os.path.join(HERE, "rig.py"), plain, out], capture_output=True, text=True)
    os.remove(plain)
    sys.stderr.write(p.stderr)
    return json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else {"status": "error"}


# ── web API ─────────────────────────────────────────────────────────────────
class Jobs:
    """Cars asked for over the API: a queue, a few builders, and one JSON file
    per job so results outlive a restart."""

    def __init__(self, workers):
        self.dir = os.path.join(HOME, "jobs")
        os.makedirs(self.dir, exist_ok=True)
        self.q = queue.Queue()
        self.lock = threading.Lock()
        for k in range(workers):
            threading.Thread(target=self.worker, args=(8800 + k,), daemon=True).start()

    def path(self, jid):
        return os.path.join(self.dir, jid + ".json")

    def get(self, jid):
        if not re.fullmatch(r"[0-9a-f]{12}", jid or "") or not os.path.exists(self.path(jid)):
            return None
        with self.lock:
            return json.load(open(self.path(jid)))

    def put(self, job):
        with self.lock:
            json.dump(job, open(self.path(job["id"]) + ".tmp", "w"), default=str)
            os.replace(self.path(job["id"]) + ".tmp", self.path(job["id"]))

    def add(self, body):
        job = {"id": uuid.uuid4().hex[:12], "status": "queued", "asked_at": time.time(),
               "request": str(body["request"])[:200], "sheet": bool(body.get("sheet")),
               "nearest": bool(body.get("nearest"))}
        self.put(job)
        self.q.put(job["id"])
        return job

    def worker(self, port):
        while True:
            jid = self.q.get()
            job = self.get(jid)
            job["status"] = "building"
            self.put(job)
            try:
                rep = make(job["request"], sheet=job["sheet"], nearest=job["nearest"],
                           out=os.path.join(CARS, jid), port=port)
                job["report"] = rep
                res = rep.get("result") or {}
                job["status"] = "failed" if "error" in rep or not os.path.exists(rep.get("files", {}).get("glb", "")) \
                    else "done"
                job["quality"] = res.get("status")          # done | check (a part missing, see report)
            except Exception as e:
                job["status"], job["error"] = "failed", str(e)[-500:]
            job["finished_at"] = time.time()
            self.put(job)


def serve(port, workers):
    setup(quiet=True)
    keys = {k.strip() for k in os.environ.get("GLBMACHINE_KEYS", "").split(",") if k.strip()}
    jobs = Jobs(workers)

    class H(BaseHTTPRequestHandler):
        server_version = f"glbmachine/{VERSION}"

        def log_message(self, fmt, *a):
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % a))

        def send(self, code, obj=None, path=None, ctype="application/json"):
            data = open(path, "rb").read() if path else json.dumps(obj, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def allowed(self):
            if not keys:
                return True
            auth = self.headers.get("Authorization", "")
            key = auth[7:] if auth.startswith("Bearer ") else self.headers.get("X-API-Key", "")
            if key in keys:
                return True
            self.send(401, {"error": "a valid API key is needed (Authorization: Bearer KEY)"})
            return False

        def do_GET(self):
            parts = [p for p in self.path.split("?")[0].split("/") if p]
            if parts == ["health"]:
                return self.send(200, {"ok": True, "version": VERSION})
            if parts[:2] != ["v1", "cars"] or len(parts) < 3:
                return self.send(404, {"error": "not found"})
            if not self.allowed():
                return
            job = jobs.get(parts[2])
            if not job:
                return self.send(404, {"error": "no such car"})
            files = (job.get("report") or {}).get("files", {})
            if len(parts) == 3:
                job = dict(job, files={k: f"/v1/cars/{job['id']}/" + ("car.glb" if k == "glb" else "sheet.jpg")
                                       for k in files})
                return self.send(200, job)
            want = {"car.glb": ("glb", "model/gltf-binary"), "sheet.jpg": ("sheet", "image/jpeg")}.get(parts[3])
            if not want or want[0] not in files:
                return self.send(404, {"error": "not built"})
            return self.send(200, path=files[want[0]], ctype=want[1])

        def do_POST(self):
            if [p for p in self.path.split("?")[0].split("/") if p] != ["v1", "cars"]:
                return self.send(404, {"error": "not found"})
            if not self.allowed():
                return
            try:
                n = min(int(self.headers.get("Content-Length", 0)), 10000)
                body = json.loads(self.rfile.read(n) or b"{}")
                assert isinstance(body.get("request"), str) and body["request"].strip()
            except Exception:
                return self.send(400, {"error": 'send JSON like {"request": "Ford Fiesta 2015 blue"}'})
            job = jobs.add(body)
            self.send(202, {"id": job["id"], "status": job["status"], "poll": f"/v1/cars/{job['id']}"})

    print(json.dumps({"serving": port, "workers": workers, "keys_required": bool(keys), "home": HOME}), flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()


def main():
    ap = argparse.ArgumentParser(prog="glbmachine", description="ExpertCarCheck GLB machine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    sub.add_parser("version")
    m = sub.add_parser("make")
    m.add_argument("request")
    m.add_argument("--no-sheet", action="store_true", help="the car only, no four-view check sheet")
    m.add_argument("--nearest", action="store_true", help="build the nearest catalogue generation if none is sourced")
    m.add_argument("--no-source", action="store_true", help="catalogue only, no Sketchfab search")
    m.add_argument("--out", default=None)
    b = sub.add_parser("batch")
    b.add_argument("--top", type=int, default=20)
    b.add_argument("--list", default="targets", choices=("targets", "top2000"))
    b.add_argument("--workers", type=int, default=1)
    b.add_argument("--out", default=os.path.join(CARS, "batch"))
    r = sub.add_parser("rig")
    r.add_argument("src")
    r.add_argument("out")
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8080)))
    s.add_argument("--workers", type=int, default=int(os.environ.get("GLBMACHINE_WORKERS", 2)))
    a = ap.parse_args()
    if a.cmd == "version":
        import rig as rg
        print(json.dumps({"glbmachine": VERSION, "rigger": rg.VERSION}))
    elif a.cmd == "setup":
        print(json.dumps(setup()))
    elif a.cmd == "make":
        rep = make(a.request, sheet=not a.no_sheet, nearest=a.nearest, no_source=a.no_source, out=a.out)
        print(json.dumps(rep, indent=1, default=str))
        sys.exit(2 if "error" in rep else 0)
    elif a.cmd == "batch":
        setup(quiet=True)
        import batch
        sys.argv = ["batch.py", a.out, "--top", str(a.top), "--list", a.list, "--workers", str(a.workers),
                    "--engine-pack", ENGINE_PACK, "--tools", TOOLS, "--view-dir", VIEW]
        batch.main()
    elif a.cmd == "rig":
        print(json.dumps(rig(a.src, a.out)))
    elif a.cmd == "serve":
        serve(a.port, a.workers)


if __name__ == "__main__":
    main()
