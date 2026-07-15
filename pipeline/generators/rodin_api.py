#!/usr/bin/env python3
"""rodin_api.py — Hyper3D Rodin (Deemos) image->3D API client.

Same offline gap-filler contract as the TRELLIS/Hunyuan workers: image(s) in
-> GLB out -> caller runs QC + catalogue gates. Never on the customer path.

API (verified against developer.hyper3d.ai, 2026-07-15):
  POST https://api.hyper3d.com/api/v2/rodin     multipart generation submit
       -> {uuid, jobs: {uuids, subscription_key}}
  POST https://api.hyper3d.com/api/v2/status    {subscription_key}
       -> {jobs: [{uuid, status: Waiting|Generating|Done|Failed}]}
  POST https://api.hyper3d.com/api/v2/download  {task_uuid}
       -> {list: [{url, name}]}
Auth: Authorization: Bearer $RODIN_API_KEY

Usage:
  export RODIN_API_KEY=...
  python3 pipeline/generators/rodin_api.py --image refs/car1.jpg \
      [--image refs/car2.jpg ... up to 5] [--tier Gen-2.5-Medium] \
      [--seed 3] [--out car.glb]
  python3 pipeline/generators/rodin_api.py --selftest
"""
import argparse, json, mimetypes, os, sys, time, urllib.request, uuid as _uuid

HOST = "https://api.hyper3d.com"


def _key():
    k = os.environ.get("RODIN_API_KEY")
    if not k:
        print("set RODIN_API_KEY", file=sys.stderr)
        sys.exit(1)
    return k


def _post_json(path, payload):
    rq = urllib.request.Request(f"{HOST}{path}", data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"})
    with urllib.request.urlopen(rq, timeout=120) as r:
        return json.loads(r.read())


def _multipart(fields, files):
    b = f"----rodin{_uuid.uuid4().hex}"
    out = bytearray()
    for k, v in fields.items():
        if v is None:
            continue
        out += (f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
    for k, path in files:
        ct = mimetypes.guess_type(path)[0] or "application/octet-stream"
        out += (f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"; "
                f"filename=\"{os.path.basename(path)}\"\r\nContent-Type: {ct}\r\n\r\n").encode()
        out += open(path, "rb").read()
        out += b"\r\n"
    out += f"--{b}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={b}"


def submit(images, tier="Gen-2.5-Medium", seed=None, mesh_mode="Quad",
           material="PBR", hd_texture=False):
    fields = {"tier": tier, "geometry_file_format": "glb", "mesh_mode": mesh_mode,
              "material": material, "seed": seed,
              "hd_texture": "true" if hd_texture else None}
    body, ctype = _multipart(fields, [("images", p) for p in images])
    rq = urllib.request.Request(f"{HOST}/api/v2/rodin", data=body,
        headers={"Authorization": f"Bearer {_key()}", "Content-Type": ctype})
    with urllib.request.urlopen(rq, timeout=300) as r:
        out = json.loads(r.read())
    if out.get("error"):
        raise RuntimeError(f"submit: {out['error']}")
    return out["uuid"], out["jobs"]["subscription_key"]


def wait(subscription_key, timeout_s=1800):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        r = _post_json("/api/v2/status", {"subscription_key": subscription_key})
        stats = [j.get("status") for j in r.get("jobs", [])]
        print(f"  {int(time.time()-t0)}s: {stats}", flush=True)
        if stats and all(s == "Done" for s in stats):
            return
        if any(s == "Failed" for s in stats):
            raise RuntimeError(f"job failed: {r}")
        time.sleep(15)
    raise TimeoutError(subscription_key)


def download(task_uuid, out_glb):
    r = _post_json("/api/v2/download", {"task_uuid": task_uuid})
    if r.get("error"):
        raise RuntimeError(f"download: {r['error']}")
    saved = []
    for f in r.get("list", []):
        name, url = f.get("name", ""), f.get("url")
        if not url:
            continue
        if name.endswith(".glb"):
            dest = out_glb
        elif name.endswith(".webp"):
            dest = out_glb.rsplit(".", 1)[0] + "_preview.webp"
        else:
            continue
        data = urllib.request.urlopen(url, timeout=600).read()
        open(dest, "wb").write(data)
        saved.append((dest, len(data) // 1024))
        print(f"saved {dest} ({len(data)//1024} KB)")
    if not any(d.endswith(".glb") for d, _ in saved):
        raise RuntimeError(f"no glb in result list: {[f.get('name') for f in r.get('list', [])]}")
    return saved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", action="append", default=[],
                    help="reference image; repeat up to 5 (first drives the material)")
    ap.add_argument("--tier", default="Gen-2.5-Medium")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--mesh_mode", default="Quad", choices=["Quad", "Raw"])
    ap.add_argument("--hd_texture", action="store_true")
    ap.add_argument("--out", default="rodin.glb")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        try:
            r = _post_json("/api/v2/status", {"subscription_key": "selftest-nonexistent"})
            print("SELFTEST OK — API reachable, response:", json.dumps(r)[:200])
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:200]
            if e.code in (400, 401, 403, 404, 422):
                print(f"SELFTEST {'OK — auth accepted, structured error' if e.code in (400,404,422) else 'FAILED — check RODIN_API_KEY'}: {e.code} {body}")
                sys.exit(0 if e.code in (400, 404, 422) else 1)
            raise
        return

    if not a.image:
        ap.error("need at least one --image (or --selftest)")
    task_uuid, sub = submit(a.image, tier=a.tier, seed=a.seed,
                            mesh_mode=a.mesh_mode, hd_texture=a.hd_texture)
    print("task:", task_uuid)
    wait(sub)
    download(task_uuid, a.out)


if __name__ == "__main__":
    main()
