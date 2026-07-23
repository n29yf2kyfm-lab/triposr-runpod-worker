#!/usr/bin/env python3
"""meshy_api.py — Meshy AI image->3D API client.

Same offline gap-filler contract as the TRELLIS / Rodin / Hunyuan workers:
image in -> GLB out -> the caller runs the QC + catalogue gates. NEVER on the
customer request path; AI reconstruction is a last-resort gap-filler only.

API (Meshy OpenAPI v1, verified 2026-07-23):
  POST https://api.meshy.ai/openapi/v1/image-to-3d
       {image_url, enable_pbr, should_remesh, should_texture, target_polycount}
       -> {result: <task_id>}
  GET  https://api.meshy.ai/openapi/v1/image-to-3d/<task_id>
       -> {status: PENDING|IN_PROGRESS|SUCCEEDED|FAILED, progress,
           model_urls: {glb, fbx, obj, usdz}, texture_urls}
Auth: Authorization: Bearer $MESHY_API_KEY

image_url may be a public URL or a data: URI (a local file is inlined as one).

Usage:
  export MESHY_API_KEY=...
  python3 pipeline/generators/meshy_api.py --image refs/car.jpg --out car.glb
  python3 pipeline/generators/meshy_api.py --image-url https://... --out car.glb
  python3 pipeline/generators/meshy_api.py --selftest        # auth check only
"""
import argparse, base64, json, mimetypes, os, sys, time, urllib.request

HOST = "https://api.meshy.ai/openapi/v1"


def _key():
    k = os.environ.get("MESHY_API_KEY")
    if not k:
        print("set MESHY_API_KEY", file=sys.stderr)
        sys.exit(1)
    return k


def _req(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    rq = urllib.request.Request(f"{HOST}{path}", data=data, method=method,
        headers={"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"})
    with urllib.request.urlopen(rq, timeout=120) as r:
        return json.loads(r.read())


def _data_uri(path):
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(open(path, "rb").read()).decode()


def submit(image_url, pbr=True, remesh=True, texture=True, polycount=None):
    body = {"image_url": image_url, "enable_pbr": pbr,
            "should_remesh": remesh, "should_texture": texture}
    if polycount:
        body["target_polycount"] = polycount
    return _req("POST", "/image-to-3d", body)["result"]


def poll(task_id, timeout=1200, interval=10):
    """Block until the task settles; returns the final task dict."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        d = _req("GET", f"/image-to-3d/{task_id}")
        st = d.get("status")
        print(f"  meshy {task_id[:8]} {st} {d.get('progress')}%", file=sys.stderr)
        if st in ("SUCCEEDED", "FAILED", "CANCELED", "EXPIRED"):
            return d
        time.sleep(interval)
    return {"status": "TIMEOUT"}


def download_glb(task, out):
    url = (task.get("model_urls") or {}).get("glb")
    if not url:
        raise RuntimeError(f"no glb in task: {json.dumps(task)[:200]}")
    urllib.request.urlretrieve(url, out)
    return out


def generate(image_url, out, **opts):
    tid = submit(image_url, **opts)
    task = poll(tid)
    if task.get("status") != "SUCCEEDED":
        raise RuntimeError(f"meshy task {tid} -> {task.get('status')}: {json.dumps(task)[:200]}")
    return download_glb(task, out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", help="local image file (inlined as data URI)")
    ap.add_argument("--image-url", help="public image URL")
    ap.add_argument("--out", default="meshy.glb")
    ap.add_argument("--polycount", type=int, default=None)
    ap.add_argument("--no-pbr", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        # cheapest authenticated call: list image-to-3d tasks
        d = _req("GET", "/image-to-3d?page_size=1")
        print("MESHY_AUTH_OK", "tasks_visible" if isinstance(d, list) else type(d).__name__)
        return
    img = a.image_url or (_data_uri(a.image) if a.image else None)
    if not img:
        print("need --image or --image-url", file=sys.stderr); sys.exit(1)
    path = generate(img, a.out, pbr=not a.no_pbr, polycount=a.polycount)
    print("MESHY_GLB", path, os.path.getsize(path), "bytes")


if __name__ == "__main__":
    main()
