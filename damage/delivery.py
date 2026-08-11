"""Artifact delivery for the damage worker.

Copied in pattern from the vehicle/building workers (not imported — PLAN.md
§2.3 isolation). Same hard lesson: RunPod silently drops job outputs over its
response-size cap, so the primary channel is an upload to object storage and
inline base64 is a fallback only when the artifact is small enough to survive.

This worker's artifacts are small — a JSON report and an HTML page, kilobytes
each — so most jobs inline fine. The upload path still matters for the HTML
report a caller wants a durable URL for, and for staying identical to the
other workers so the pattern is one thing to reason about, not three.
"""
import os
import sys
import base64
import mimetypes

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
# Own bucket, separate from the vehicle and building workers.
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "damage-scans")

MAX_INLINE_BYTES = 4_000_000
UPLOAD_TIMEOUT = 120

_CONTENT_TYPES = {
    ".json": "application/json",
    ".html": "text/html; charset=utf-8",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".glb": "model/gltf-binary",
}


def _requests():
    """Lazy import — the test runner is a bare Python by design."""
    import requests
    return requests


def content_type_for(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in _CONTENT_TYPES:
        return _CONTENT_TYPES[ext]
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def storage_configured():
    return bool(SUPABASE_URL and SUPABASE_KEY and SUPABASE_BUCKET)


def upload(path, object_name, content_type=None):
    """Upload a file to object storage; return its public URL, or None.
    Never raises — a delivery failure is reported through the return value."""
    if not storage_configured():
        return None
    if not os.path.exists(path):
        print(f"delivery: {path} does not exist", file=sys.stderr)
        return None
    content_type = content_type or content_type_for(path)
    try:
        with open(path, "rb") as f:
            data = f.read()
        r = _requests().post(
            f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{object_name}",
            data=data,
            headers={
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "apikey": SUPABASE_KEY,
                "Content-Type": content_type,
                "x-upsert": "true",
            },
            timeout=UPLOAD_TIMEOUT,
        )
        if r.status_code in (200, 201):
            return (f"{SUPABASE_URL}/storage/v1/object/public/"
                    f"{SUPABASE_BUCKET}/{object_name}")
        print(f"delivery: upload failed {r.status_code} {r.text[:200]}",
              file=sys.stderr)
    except Exception as e:
        print(f"delivery: upload error {type(e).__name__}: {e}",
              file=sys.stderr)
    return None


def deliver(path, object_name, inline_key=None, allow_inline=True):
    """Deliver one artifact. Returns {url, size_bytes, path, [inline_key],
    [warning]}."""
    size = os.path.getsize(path) if os.path.exists(path) else 0
    url = upload(path, object_name)
    out = {"url": url, "size_bytes": size, "path": path}
    if allow_inline and inline_key and size and size <= MAX_INLINE_BYTES:
        with open(path, "rb") as f:
            out[inline_key] = base64.b64encode(f.read()).decode("utf-8")
    if not url and size > MAX_INLINE_BYTES:
        out["warning"] = (
            f"{os.path.basename(path)} is {size / 1e6:.1f}MB — too large to "
            f"inline and object storage is not configured. The file exists "
            f"only on the worker volume at {path} and will be lost when the "
            f"worker recycles.")
    return out


def deliver_many(artifacts):
    """Deliver several artifacts: list of (path, object_name, inline_key?)."""
    out = {}
    for item in artifacts:
        path, object_name = item[0], item[1]
        inline_key = item[2] if len(item) > 2 else None
        out[os.path.basename(path)] = deliver(path, object_name, inline_key)
    return out
