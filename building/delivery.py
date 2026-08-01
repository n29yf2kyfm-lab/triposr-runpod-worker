"""Artifact delivery for the building worker.

Copied in pattern from trellis2/handler.py (not imported — see PLAN.md §2.3).

THE LESSON THIS ENCODES, learned live on the vehicle worker: RunPod silently
drops job outputs that exceed its response-size cap. A job returned
COMPLETED with output=None and a multi-MB GLB simply vanished.

That matters far more here. A GLB is single-digit MB; a point cloud, an IFC
model or a Gaussian splat is tens to hundreds of MB. Every artifact this
worker produces would trip that cap. So:

  primary   -> upload to object storage, return a URL
  secondary -> inline base64 ONLY when small enough to survive the cap
  neither   -> say so loudly instead of reporting "success"
"""
import os
import sys
import base64
import mimetypes

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
# Own bucket, separate from the vehicle worker's (PLAN.md §2.3 isolation).
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "building-scans")

# Raw bytes. Base64 inflates by ~4/3, so this lands around 5.3MB encoded —
# safely under the platform cap with headroom for the rest of the payload.
MAX_INLINE_BYTES = 4_000_000

# Upload timeout. Point clouds are large and merchant-grade broadband on a
# building site is optimistic; 10 minutes is not excessive here.
UPLOAD_TIMEOUT = 600

_CONTENT_TYPES = {
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".ifc": "application/x-step",
    ".ply": "application/octet-stream",
    ".laz": "application/octet-stream",
    ".las": "application/octet-stream",
    ".e57": "application/octet-stream",
    ".xyz": "text/plain",
    ".dxf": "image/vnd.dxf",
    ".usdz": "model/vnd.usdz+zip",
    ".json": "application/json",
    ".pdf": "application/pdf",
}


def _requests():
    """Imported lazily, as in every other module here.

    A module-level `import requests` broke CI: the test runner is a bare
    Python with no packages, by design — the whole point of these tests is
    that they need no GPU, no network and no dependencies. Delivery is only
    ever exercised in its unconfigured form there, so the import must not
    happen until an upload is actually attempted.
    """
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

    Never raises — a delivery failure is reported through the return value so
    a finished multi-minute reconstruction is not lost to a transient network
    error. The caller decides how loud to be about it.
    """
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
    """Deliver one artifact. Returns a dict describing how it went.

    Keys: url, size_bytes, path, and optionally <inline_key> (base64) and
    'warning' when the artifact cannot be retrieved by the caller at all.
    """
    size = os.path.getsize(path) if os.path.exists(path) else 0
    url = upload(path, object_name)

    out = {"url": url, "size_bytes": size, "path": path}

    if allow_inline and inline_key and size and size <= MAX_INLINE_BYTES:
        with open(path, "rb") as f:
            out[inline_key] = base64.b64encode(f.read()).decode("utf-8")

    if not url and size > MAX_INLINE_BYTES:
        # No upload channel and too large to inline: the caller cannot get
        # this file. Reporting "success" here would be a lie — the artifact
        # dies with the worker.
        out["warning"] = (
            f"{os.path.basename(path)} is {size / 1e6:.1f}MB — too large to "
            f"inline, and object storage is not configured "
            f"(SUPABASE_URL/KEY/BUCKET). The file exists only on the worker "
            f"volume at {path} and will be lost when the worker recycles.")
    return out


def deliver_many(artifacts):
    """Deliver several artifacts. `artifacts` is a list of
    (local_path, object_name, inline_key_or_None).

    Returns {basename: delivery_dict}. Collects warnings rather than
    failing — a partial delivery still beats losing everything.
    """
    out = {}
    for item in artifacts:
        path, object_name = item[0], item[1]
        inline_key = item[2] if len(item) > 2 else None
        out[os.path.basename(path)] = deliver(path, object_name, inline_key)
    return out
