#!/usr/bin/env python3
"""glbmachine — ExpertCarCheck's GLB machine as one program.

Ask for a car in plain words; it is found in your catalogue and you get back
your own interactive GLB: doors, bonnet and tailgate that open (named
clips), clear glass, the model's cabin, a generic engine bay and exhaust,
painted the colour asked for. No Blender, no Sketchfab, no outside service:
the only network use is fetching the model from the catalogue's storage.

    glbmachine setup                          # once: node tools + work folder
    glbmachine make "Nissan Micra 2004 red" -o micra.glb        # + a check sheet
    glbmachine make "VW Polo 2019" --no-sheet -o polo.glb       # the car only, in seconds
    glbmachine make "Ford Fiesta 2012" --full -o fiesta.glb     # uncompressed: any 3D program
    glbmachine batch --top 20 --workers 3     # the UK best sellers
    glbmachine rig CAR.glb OUT_DIR            # the rig step alone
    glbmachine serve --port 8080              # the web API (below) and GLB Studio at /studio/
    glbmachine version

WORK FOLDER: $GLBMACHINE_HOME (default ~/.glbmachine) holds view/ (the check
sheet page, served to a headless browser) and view/cars/ (every car built).

WEB API (`serve`):
    POST /v1/cars            {"request": "Ford Fiesta 2015 blue", "sheet": false,
                              "exact": false}  -> 202 {"id", "status"}
    GET  /v1/cars/ID         -> {"id", "status": queued|building|done|failed, "report", "files"}
    GET  /v1/cars/ID/car.glb    the finished car (meshopt-compressed)
    GET  /v1/cars/ID/sheet.jpg  the four-view check sheet, when asked for
    GET  /health
GLB STUDIO (`serve`, /studio/): open a built car, select a wrong part, say
what it is, build again. Its calls: GET /v1/library, GET /v1/library/KEY/
rig.glb | edits | record | car.glb, POST /v1/library/KEY/edits (apply and
rebuild), POST /v1/library/KEY/reset.
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
import urllib.parse
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


def make(request, sheet=True, exact=False, out=None, port=8791, out_file=None, full=False):
    import make as mk
    setup(quiet=True)
    return mk.build(request, ENGINE_PACK, TOOLS, VIEW, out or CARS, port, exact, not sheet, out_file, full)


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
               "exact": bool(body.get("exact"))}
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
                rep = make(job["request"], sheet=job["sheet"], exact=job.get("exact", False),
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


# ── the Studio's library: every car built here that kept its rig ────────────
_CATALOGUE = {}


def _catalogue_item(asset):
    if not _CATALOGUE:
        import batch
        _CATALOGUE.update(batch.catalogue())
    return _CATALOGUE.get(asset) or {}


def _car_name(item):
    """'Nissan Micra (2004)' from a catalogue record ('nissan', 'nissan micra')."""
    make = str(item.get("make") or "")
    model = str(item.get("modelFamily") or item.get("model") or "")
    if model.lower().startswith(make.lower() + " "):
        model = model[len(make) + 1:]
    import wheelbase

    def nice(w):
        if any(c.isupper() for c in w):
            return w
        # letters beside a digit or hyphen are a code (CR-V, CX-5, XC90, X5), bar i10 / e-208
        return re.sub(r"[a-z]+", lambda m: m.group(0) if m.group(0) in ("i", "e") and m.start() == 0 and len(w) > 1
                      else (m.group(0).upper() if len(m.group(0)) <= 2 and re.search(r"[\d-]", w) else m.group(0).title()), w)
    make = wheelbase.MAKE_TITLE.get(make.lower(), nice(make))
    years = "-".join(str(y) for y in (item.get("yearStart"), item.get("yearEnd")) if y)
    return " ".join(x for x in (make, " ".join(nice(w) for w in model.split()), f"({years})" if years else "") if x)


def library():
    out = []
    for root, dirs, files in os.walk(CARS):
        depth = os.path.relpath(root, CARS).count(os.sep)
        if os.path.exists(os.path.join(root, "rig", "src.glb")):
            key = os.path.relpath(root, CARS).replace(os.sep, "/")
            rec = _json(os.path.join(root, "record.json")) or {}
            b = _json(os.path.join(root, "build.json")) or {}
            item = b.get("item") or _catalogue_item(os.path.basename(root))
            ed = _json(os.path.join(root, "rig", "edits.json"))
            name = (b.get("target") or {}).get("genModel") or _car_name(item) or os.path.basename(root)
            out.append({"key": key, "name": name, "asset": os.path.basename(root), "status": rec.get("status"),
                        "missing": rec.get("missing"), "opens": (rec.get("finish") or {}).get("opens"),
                        "edited": bool(ed), "has_car": os.path.exists(os.path.join(root, "web.glb")),
                        "updated": os.path.getmtime(os.path.join(root, "rig", "src.glb"))})
            dirs[:] = []
        elif depth >= 2:
            dirs[:] = []
    return sorted(out, key=lambda c: -c["updated"])


def _json(p):
    try:
        return json.load(open(p))
    except Exception:
        return None


def car_dir(key):
    """A library key -> its folder, only if it is a car under CARS."""
    d = os.path.realpath(os.path.join(CARS, key))
    if not d.startswith(os.path.realpath(CARS) + os.sep) or not os.path.exists(os.path.join(d, "rig", "src.glb")):
        return None
    return d


def rebuild(d, port=8799):
    """Finish a car again from its rig (and the person's edits, if any): the
    same path as make, without the download, the rig or the check sheet."""
    import argparse
    import batch
    b = _json(os.path.join(d, "build.json"))
    if b:
        target, item, paint, body = b["target"], b["item"], b.get("paint"), b.get("body_style")
    else:
        item = batch.catalogue().get(os.path.basename(d))
        if item is None:
            raise ValueError("no record of how this car was built")
        target, paint, body = {"rank": 0, "genModel": f"{item['make']} {item.get('modelFamily') or item['model']}"}, None, None
    args = argparse.Namespace(engine_pack=ENGINE_PACK, tools=TOOLS, view_dir=VIEW, port=port, no_sheet=True,
                              paint=paint, body_style=body)
    if os.path.exists(os.path.join(d, "sheet.jpg")):
        os.remove(os.path.join(d, "sheet.jpg"))     # it no longer shows this car
    return batch.one(target, item, args, os.path.dirname(d))


STATIC = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css",
          ".svg": "image/svg+xml", ".json": "application/json", ".wasm": "application/wasm"}


def serve(port, workers):
    import edits as ed_mod
    setup(quiet=True)
    keys = {k.strip() for k in os.environ.get("GLBMACHINE_KEYS", "").split(",") if k.strip()}
    jobs = Jobs(workers)
    locks, locks_lock = {}, threading.Lock()
    studio_dir, lib_dir = os.path.join(HERE, "studio"), os.path.join(VIEW, "lib")

    class H(BaseHTTPRequestHandler):
        server_version = f"glbmachine/{VERSION}"

        def log_message(self, fmt, *a):
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % a))

        def send(self, code, obj=None, path=None, ctype="application/json", cache=False):
            data = open(path, "rb").read() if path else json.dumps(obj, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
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

        def static(self, base, rel, cache):
            """A file under BASE (symlinks followed only into the node tools)."""
            p = os.path.realpath(os.path.join(base, rel))
            roots = [os.path.realpath(base), os.path.realpath(os.path.join(TOOLS, "node_modules"))]
            if ".." in rel.split("/") or not any(p.startswith(r + os.sep) for r in roots) or not os.path.isfile(p):
                return self.send(404, {"error": "not found"})
            return self.send(200, path=p, ctype=STATIC.get(os.path.splitext(p)[1], "application/octet-stream"),
                             cache=cache)

        def body(self, limit):
            n = int(self.headers.get("Content-Length", 0))
            if n > limit:
                raise ValueError("too large")
            return json.loads(self.rfile.read(n) or b"{}")

        def do_GET(self):
            path = self.path.split("?")[0]
            parts = [urllib.parse.unquote(p) for p in path.split("/") if p]
            if not parts:
                self.send_response(302)
                self.send_header("Location", "/studio/")
                self.end_headers()
                return
            if parts == ["health"]:
                return self.send(200, {"ok": True, "version": VERSION})
            if parts[0] == "studio":
                return self.static(studio_dir, "/".join(parts[1:]) or "index.html", cache=False)
            if parts[0] == "lib":
                return self.static(lib_dir, "/".join(parts[1:]), cache=True)
            if parts[:2] == ["v1", "library"]:
                if not self.allowed():
                    return
                if len(parts) == 2:
                    return self.send(200, library())
                d = car_dir(parts[2]) if len(parts) == 4 else None
                if not d:
                    return self.send(404, {"error": "no such car"})
                rig = os.path.join(d, "rig")
                if parts[3] == "rig.glb":         # always the rigger's own parts: edits are re-applied to them
                    orig = os.path.join(rig, "src.orig.glb")
                    return self.send(200, path=orig if os.path.exists(orig) else os.path.join(rig, "src.glb"),
                                     ctype="model/gltf-binary")
                if parts[3] == "edits":
                    return self.send(200, _json(os.path.join(rig, "edits.json")) or {})
                if parts[3] == "record":
                    return self.send(200, _json(os.path.join(d, "record.json")) or {})
                if parts[3] == "car.glb" and os.path.exists(os.path.join(d, "web.glb")):
                    return self.send(200, path=os.path.join(d, "web.glb"), ctype="model/gltf-binary")
                if parts[3] == "sheet.jpg" and os.path.exists(os.path.join(d, "sheet.jpg")):
                    return self.send(200, path=os.path.join(d, "sheet.jpg"), ctype="image/jpeg")
                return self.send(404, {"error": "not found"})
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
            parts = [urllib.parse.unquote(p) for p in self.path.split("?")[0].split("/") if p]
            if parts[:2] == ["v1", "library"] and len(parts) == 4 and parts[3] in ("edits", "reset"):
                if not self.allowed():
                    return
                d = car_dir(parts[2])
                if not d:
                    return self.send(404, {"error": "no such car"})
                try:
                    body = self.body(64 << 20) if parts[3] == "edits" else {}
                except Exception:
                    return self.send(400, {"error": "send the edits as JSON"})
                with locks_lock:
                    lock = locks.setdefault(d, threading.Lock())
                with lock:
                    t0 = time.time()
                    try:
                        if parts[3] == "edits":
                            saved = ed_mod.apply(os.path.join(d, "rig"), body)
                        else:
                            ed_mod.reset(os.path.join(d, "rig"))
                            saved = {}
                        rec = rebuild(d)
                    except Exception as e:
                        return self.send(500, {"error": str(e)[-400:]})
                    return self.send(200, {"edits": saved, "record": rec, "seconds": round(time.time() - t0, 1)})
            if parts != ["v1", "cars"]:
                return self.send(404, {"error": "not found"})
            if not self.allowed():
                return
            try:
                body = self.body(10000)
                assert isinstance(body.get("request"), str) and body["request"].strip()
            except Exception:
                return self.send(400, {"error": 'send JSON like {"request": "Ford Fiesta 2015 blue"}'})
            job = jobs.add(body)
            self.send(202, {"id": job["id"], "status": job["status"], "poll": f"/v1/cars/{job['id']}"})

    print(json.dumps({"serving": port, "studio": f"http://localhost:{port}/studio/", "workers": workers,
                      "keys_required": bool(keys), "home": HOME}), flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()


def main():
    ap = argparse.ArgumentParser(prog="glbmachine", description="ExpertCarCheck GLB machine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    sub.add_parser("version")
    m = sub.add_parser("make")
    m.add_argument("request")
    m.add_argument("--no-sheet", action="store_true", help="the car only, no four-view check sheet")
    m.add_argument("-o", "--output", default=None, help="write the finished GLB here")
    m.add_argument("--full", action="store_true", help="the uncompressed GLB (opens in any 3D program)")
    m.add_argument("--exact", action="store_true", help="only that year's generation, never the nearest")
    m.add_argument("--out", default=None, help="work folder for the build (default: the car library)")
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
        rep = make(a.request, sheet=not a.no_sheet, exact=a.exact, out=a.out, out_file=a.output, full=a.full)
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
