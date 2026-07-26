#!/bin/bash
# warm_test_pod.sh — a STAY-UP test rig: loads the pipeline and the Alam-3D
# weights once, then serves generation over HTTP so each extra car costs
# ~4 minutes instead of ~25 (no boot, no model reload, no double run).
#
#   GET  /status.json          launcher/poller compatibility + readiness
#   GET  /health               {"ready":true,"weights":"...","jobs":N}
#   POST /gen                  {"name":"gti","images":["url",...],
#                               "tag":"alam3d"|"base","seed":42,
#                               "pipeline_type":"1024_cascade"}
#                              -> {"glb_url": "...supabase.../eval/warm/<name>_<tag>.glb"}
#
# THIS POD DOES NOT SELF-DELETE — it bills until stopped on purpose.
# Launch with --keep; stop with the delete call in the session notes.
# Secrets (HF_TOKEN, SB_KEY) arrive via pod env only.
OUT=/workspace/alam3d_warm
CKPTS=/workspace/alam3d_stage_c/ckpts
mkdir -p "$OUT/logs"
RUN_LOG="warm_$(hostname)_$(date -u +%Y%m%dT%H%M%SZ).log"
ln -sf "$RUN_LOG" "$OUT/logs/stage_b.log"
exec > >(tee -a "$OUT/logs/$RUN_LOG") 2>&1
status(){ printf '{"step":"%s","at":"%s"}\n' "$1" "$(date -u +%FT%TZ)" > "$OUT/logs/status.json"; echo "===== $1 ====="; }

status boot
[ -f /etc/rp_environment ] && source /etc/rp_environment
export HF_TOKEN HUGGING_FACE_HUB_TOKEN SB_KEY
[ -n "$HF_TOKEN" ] && echo "HF token: present (${#HF_TOKEN} chars)" || echo "HF token: MISSING"
nvidia-smi -L || true
cd /app/TRELLIS.2 || { status FATAL-no-trellis2; sleep infinity; }
export PYTHONPATH=/app/TRELLIS.2:/app:$PYTHONPATH
pip install -q "transformers==4.57.6" || true

status warming
python3 - <<'PY'
import glob, io, json, os, sys, threading, time, types, urllib.request
import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import torch
from PIL import Image
sys.path.insert(0, "/app")

OUT = "/workspace/alam3d_warm/logs"
def status(step):
    json.dump({"step": step, "at": time.strftime("%FT%TZ", time.gmtime())},
              open(f"{OUT}/status.json", "w"))

# production handler (free BiRefNet + DINOv3 patches); stub runpod first
_fake = types.ModuleType("runpod")
_fake.serverless = types.SimpleNamespace(start=lambda *a, **k: None)
sys.modules["runpod"] = _fake
spec = importlib.util.spec_from_file_location("handler", "/app/handler.py")
handler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handler)
import o_voxel

pipeline = handler.get_image_pipeline()
MODEL = pipeline.models["shape_slat_flow_model_512"]
BASE_SD = {k: v.detach().clone() for k, v in MODEL.state_dict().items()}   # keep stock weights
ck = sorted(glob.glob("/workspace/alam3d_stage_c/ckpts/denoiser_ema*step*.pt"), reverse=True)
TUNED_SD = torch.load(ck[0], map_location="cpu", weights_only=True) if ck else None
print("warm rig ready; tuned ckpt:", os.path.basename(ck[0]) if ck else "NONE", flush=True)

STATE = {"weights": "base", "jobs": 0}
LOCK = threading.Lock()
SB = os.environ.get("SB_KEY", "")
SUPA = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"


def set_weights(tag):
    if STATE["weights"] == tag:
        return
    sd = TUNED_SD if tag == "alam3d" else BASE_SD
    if sd is None:
        raise RuntimeError("no tuned checkpoint on volume")
    missing, unexpected = MODEL.load_state_dict(sd, strict=False)
    if len(missing) > 20:
        raise RuntimeError(f"weight swap rejected: {len(missing)} missing keys")
    STATE["weights"] = tag


def fetch_image(url):
    rq = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return Image.open(io.BytesIO(urllib.request.urlopen(rq, timeout=60).read()))


def upload(path, data):
    rq = urllib.request.Request(f"{SUPA}/car-meshes/{path}", data=data, method="POST")
    for h, v in (("apikey", SB), ("Authorization", "Bearer " + SB),
                 ("Content-Type", "model/gltf-binary"), ("x-upsert", "true")):
        rq.add_header(h, v)
    urllib.request.urlopen(rq, timeout=300).read()
    return f"{SUPA}/public/car-meshes/{path}"


def generate(name, urls, tag, seed, ptype):
    with LOCK:
        set_weights(tag)
        imgs = [fetch_image(u) for u in urls]
        torch.manual_seed(seed)
        if len(imgs) > 1:
            from alam3d_multiview import run_multi_image
            meshes = run_multi_image(pipeline, imgs, seed=seed, preprocess_image=True,
                                     pipeline_type=ptype, num_samples=1)
        else:
            meshes = pipeline.run(imgs[0], seed=seed, preprocess_image=True,
                                  pipeline_type=ptype, num_samples=1)
        mesh = max(meshes, key=lambda m: len(m.faces)) if len(meshes) > 1 else meshes[0]
        glb = o_voxel.postprocess.to_glb(
            vertices=mesh.vertices, faces=mesh.faces, attr_volume=mesh.attrs,
            coords=mesh.coords, attr_layout=mesh.layout, voxel_size=mesh.voxel_size,
            aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
            decimation_target=120000, texture_size=2048,
            remesh=True, remesh_band=1, remesh_project=0, verbose=False)
        local = f"{OUT}/{name}_{tag}.glb"
        glb.export(local, extension_webp=False)
        STATE["jobs"] += 1
        url = upload(f"eval/warm/{name}_{tag}.glb", open(local, "rb").read()) if SB else None
        print(f"generated {name}/{tag}: {os.path.getsize(local)//1024}KB -> {url}", flush=True)
        return {"glb_url": url, "bytes": os.path.getsize(local), "weights": tag}


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/health"):
            return self._send(200, {"ready": True, **STATE})
        if self.path.startswith("/status.json"):
            return self._send(200, {"step": "READY", "jobs": STATE["jobs"]})
        p = os.path.join(OUT, os.path.basename(self.path))
        if os.path.exists(p):
            d = open(p, "rb").read()
            self.send_response(200); self.send_header("Content-Length", str(len(d)))
            self.end_headers(); self.wfile.write(d); return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self.path.startswith("/gen"):
            return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
            out = generate(req.get("name", "test"), req["images"],
                           req.get("tag", "alam3d"), int(req.get("seed", 42)),
                           req.get("pipeline_type", "1024_cascade"))
            self._send(200, out)
        except Exception as e:
            print("gen error:", repr(e), flush=True)
            self._send(500, {"error": str(e)[:300]})


status("READY")
print("serving on :8000 — POST /gen  (pod stays up until deleted)", flush=True)
ThreadingHTTPServer(("0.0.0.0", 8000), H).serve_forever()
PY
status FATAL-server-exited
sleep infinity
