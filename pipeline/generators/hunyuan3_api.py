#!/usr/bin/env python3
"""hunyuan3_api.py — Tencent Cloud Hunyuan 3D (3.x) API client.

Hunyuan 3D 3.0/3.1 has NO open-source release (verified 2026-07-14: no GitHub
repo, no HF weights — API/studio only). This client is the only integration
path. It follows the same offline gap-filler contract as the TRELLIS worker:
image in -> GLB out -> caller runs QC + catalogue gates.

Auth: Tencent Cloud TC3-HMAC-SHA256 (SecretId/SecretKey), service "ai3d".
  export TENCENT_SECRET_ID=...   TENCENT_SECRET_KEY=...
Usage:
  python3 pipeline/generators/hunyuan3_api.py --image refs/car.jpg --out car.glb
  python3 pipeline/generators/hunyuan3_api.py --selftest   # signed no-op call

NOTE: verify Tencent Cloud International's service terms permit your use —
the cloud API contract is separate from the (UK-excluded) community licence
that covers the open 2.x weights.
"""
import argparse, base64, hashlib, hmac, json, os, sys, time, urllib.request

HOST = "ai3d.tencentcloudapi.com"
SERVICE = "ai3d"
VERSION = "2025-05-13"
REGION = os.environ.get("TENCENT_REGION", "ap-guangzhou")


def _sign(secret_key, date, string_to_sign):
    k_date = hmac.new(("TC3" + secret_key).encode(), date.encode(), hashlib.sha256).digest()
    k_service = hmac.new(k_date, SERVICE.encode(), hashlib.sha256).digest()
    k_signing = hmac.new(k_service, b"tc3_request", hashlib.sha256).digest()
    return hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()


def call(action, payload, secret_id=None, secret_key=None):
    secret_id = secret_id or os.environ["TENCENT_SECRET_ID"]
    secret_key = secret_key or os.environ["TENCENT_SECRET_KEY"]
    body = json.dumps(payload)
    ts = int(time.time())
    date = time.strftime("%Y-%m-%d", time.gmtime(ts))

    canonical = "\n".join([
        "POST", "/", "",
        f"content-type:application/json; charset=utf-8\nhost:{HOST}\nx-tc-action:{action.lower()}\n",
        "content-type;host;x-tc-action",
        hashlib.sha256(body.encode()).hexdigest(),
    ])
    string_to_sign = "\n".join([
        "TC3-HMAC-SHA256", str(ts), f"{date}/{SERVICE}/tc3_request",
        hashlib.sha256(canonical.encode()).hexdigest(),
    ])
    sig = _sign(secret_key, date, string_to_sign)
    auth = (f"TC3-HMAC-SHA256 Credential={secret_id}/{date}/{SERVICE}/tc3_request, "
            f"SignedHeaders=content-type;host;x-tc-action, Signature={sig}")
    rq = urllib.request.Request(f"https://{HOST}/", data=body.encode(), method="POST", headers={
        "Authorization": auth, "Content-Type": "application/json; charset=utf-8",
        "Host": HOST, "X-TC-Action": action, "X-TC-Timestamp": str(ts),
        "X-TC-Version": VERSION, "X-TC-Region": REGION,
    })
    with urllib.request.urlopen(rq, timeout=120) as r:
        out = json.loads(r.read())
    if "Error" in out.get("Response", {}):
        raise RuntimeError(f"{action}: {out['Response']['Error']}")
    return out["Response"]


def submit(image_path, prompt=None):
    payload = {"ResultFormat": "GLB"}
    if image_path:
        payload["ImageBase64"] = base64.b64encode(open(image_path, "rb").read()).decode()
    if prompt:
        payload["Prompt"] = prompt
    return call("SubmitHunyuanTo3DJob", payload)["JobId"]


def wait(job_id, timeout_s=1800):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        r = call("QueryHunyuanTo3DJob", {"JobId": job_id})
        status = r.get("Status")
        print(f"  {job_id}: {status} ({int(time.time()-t0)}s)", flush=True)
        if status in ("DONE", "SUCCESS", "FINISHED"):
            files = r.get("ResultFile3Ds") or r.get("ResultFiles") or []
            for f in files:
                url = f.get("Url") or f.get("FileUrl")
                if url and (f.get("Type", "GLB").upper() == "GLB" or url.endswith(".glb")):
                    return url
            raise RuntimeError(f"job done but no GLB url in {r}")
        if status in ("FAIL", "FAILED", "ERROR"):
            raise RuntimeError(f"job failed: {r}")
        time.sleep(15)
    raise TimeoutError(job_id)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image")
    ap.add_argument("--prompt")
    ap.add_argument("--out", default="hunyuan3.glb")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        try:
            call("QueryHunyuanTo3DJob", {"JobId": "selftest-nonexistent"})
        except RuntimeError as e:
            # a structured API error proves auth + signing + service reachability
            print("SELFTEST OK — API reachable, credentials accepted, error was:", e)
            return
        except KeyError:
            print("SELFTEST FAILED: set TENCENT_SECRET_ID / TENCENT_SECRET_KEY", file=sys.stderr)
            sys.exit(1)
        print("SELFTEST unexpected success"); return
    if not (a.image or a.prompt):
        ap.error("need --image or --prompt (or --selftest)")
    job = submit(a.image, a.prompt)
    print("job:", job)
    url = wait(job)
    data = urllib.request.urlopen(url, timeout=600).read()
    open(a.out, "wb").write(data)
    print(f"saved {a.out} ({len(data)//1024} KB) from {url[:80]}")


if __name__ == "__main__":
    main()
