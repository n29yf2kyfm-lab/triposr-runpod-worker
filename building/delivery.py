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
from urllib.parse import quote

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

# How long a returned link stays valid. Seven days: long enough for a builder
# to open a quote on Monday that was produced on a Friday, short enough that a
# forwarded link does not stay live for ever.
SIGNED_URL_TTL = int(os.environ.get("SUPABASE_SIGNED_URL_TTL", 7 * 24 * 3600))

# Whether the bucket is public. Defaults to FALSE, and that default is the
# safe one: this bucket holds interior scans of people's homes, their
# addresses and their floor plans, and a public bucket makes every one of
# them readable by anyone who can guess a path.
#
# It has to be configured because the two cases need DIFFERENT URLS, and
# getting it wrong is silent. The public form only resolves on a public
# bucket; against a private one it 404s while the job still reports success
# with a `url` field — a dead link presented as a delivered artifact.
SUPABASE_PUBLIC_BUCKET = (
    os.environ.get("SUPABASE_PUBLIC_BUCKET", "").strip().lower()
    in ("1", "true", "yes"))

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


def _seg(value, keep_slashes=False):
    """Percent-encode one path segment of a storage URL.

    NOTHING HERE WAS ENCODED, and a real bucket found it. A Supabase bucket
    named "building-scans Pro" — a space is legal, and the dashboard offers
    no warning — produced a malformed request URL and the upload simply did
    not happen. Live-confirmed: the raw form returns nothing at all, the
    percent-encoded form returns a Key.

    CORRECTION. This docstring first claimed object names were the bigger
    exposure, "because they are built from project_id and scan_id, which
    people type". That is wrong, and running a real job through the deployed
    worker is what showed it: parse_job restricts both identifiers to
    letters, digits, dot, dash and underscore, so an object name can never
    carry a space in the first place. The job was refused at validation
    before delivery was ever reached.

    So the encoding earns its place for the BUCKET name, which this worker
    does not validate — it arrives from the environment, and Supabase accepts
    a space. The object-name encoding is belt and braces against a future
    caller that builds a key some other way; it is not fixing a live hole.

    Slashes are kept in object names — they are the path separators that
    give the bucket its folder structure — and encoded in bucket names,
    where a slash cannot be part of the name.
    """
    return quote(str(value), safe="/" if keep_slashes else "")


def content_type_for(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in _CONTENT_TYPES:
        return _CONTENT_TYPES[ext]
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def storage_configured():
    return bool(SUPABASE_URL and SUPABASE_KEY and SUPABASE_BUCKET)


def sign(object_name, ttl=None):
    """A time-limited URL for an object in a PRIVATE bucket, or None.

    Supabase serves private objects only against a signed token, so the
    `/object/public/...` form — which is what this module used to return for
    every upload — 404s on a private bucket. The job still reported success
    with a `url` field, so the caller got a dead link presented as a
    delivered artifact, which is the same class of lie as returning
    COMPLETED with no output at all.

    The bucket must stay private. It holds interior scans of people's homes,
    their addresses and their floor plans; a public bucket makes all of it
    readable by anyone who can guess a path, and object names here are
    derived from project and scan ids rather than being unguessable.
    """
    if not storage_configured():
        return None
    try:
        r = _requests().post(
            f"{SUPABASE_URL}/storage/v1/object/sign/"
            f"{_seg(SUPABASE_BUCKET)}/{_seg(object_name, True)}",
            json={"expiresIn": int(ttl or SIGNED_URL_TTL)},
            headers={"Authorization": f"Bearer {SUPABASE_KEY}",
                     "apikey": SUPABASE_KEY,
                     "Content-Type": "application/json"},
            timeout=60,
        )
        if r.status_code == 200:
            # Supabase returns a path like "/object/sign/bucket/name?token=..."
            # relative to /storage/v1, so joining it needs care: the leading
            # slash means urljoin would throw away the /storage/v1 prefix.
            signed = (r.json() or {}).get("signedURL") or ""
            if signed:
                return f"{SUPABASE_URL}/storage/v1{signed}"
        print(f"delivery: signing failed {r.status_code} {r.text[:200]}",
              file=sys.stderr)
    except Exception as e:
        print(f"delivery: signing error {type(e).__name__}: {e}",
              file=sys.stderr)
    return None


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
            f"{SUPABASE_URL}/storage/v1/object/"
            f"{_seg(SUPABASE_BUCKET)}/{_seg(object_name, True)}",
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
            if SUPABASE_PUBLIC_BUCKET:
                return (f"{SUPABASE_URL}/storage/v1/object/public/"
                        f"{_seg(SUPABASE_BUCKET)}/{_seg(object_name, True)}")
            return sign(object_name)
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

    inlined = False
    if allow_inline and inline_key and size and size <= MAX_INLINE_BYTES:
        with open(path, "rb") as f:
            out[inline_key] = base64.b64encode(f.read()).decode("utf-8")
        inlined = True

    if not url and not inlined:
        # No upload channel and no inline copy: the caller cannot get this
        # file by ANY route. Reporting "success" here would be a lie — the
        # artifact dies with the worker.
        #
        # The gate used to be `size > MAX_INLINE_BYTES`, which assumed the
        # only way a file goes undelivered is by being too big. But most
        # artifact tuples — every OBJ/GLB/IFC from model mode, the services
        # JSON — ship with inline_key=None, so a small file on a worker with
        # no storage came back as {url: null} inside a success response with
        # not a word said, exactly the silent loss the module header
        # promises never happens.
        #
        # The two causes need different words. "Not configured" is a
        # deployment step somebody has not done; a configured store that
        # failed is a bucket, a permission or a network problem, and sending
        # someone to re-check environment variables they already set wastes
        # the one message they get.
        if storage_configured():
            cause = ("object storage is configured but the upload or the "
                     "signing step failed — check the worker log, and that "
                     f"the {SUPABASE_BUCKET!r} bucket exists and the key can "
                     f"write to it")
        else:
            cause = ("object storage is not configured "
                     "(SUPABASE_URL/KEY/BUCKET)")
        how = (f"is {size / 1e6:.1f}MB — too large to inline"
               if size > MAX_INLINE_BYTES else "was not delivered inline")
        out["warning"] = (
            f"{os.path.basename(path)} {how}, and {cause}. The file exists "
            f"only on the worker volume at {path} and will be lost when the "
            f"worker recycles.")
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
