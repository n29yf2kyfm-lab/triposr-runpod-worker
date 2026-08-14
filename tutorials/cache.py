"""Content-addressed caching + Supabase storage for the assembler.

The cache key covers everything that changes the rendered video: the
procedure template bytes (edits invalidate automatically), the vehicle
string, voice, format, and the pipeline version stamp. Same request twice ->
same key -> the stored MP4 is served with zero compute. This is what makes
"200k videos on demand" cost pennies: unique work happens once per distinct
video, not once per request.
"""
import hashlib
import os
from pathlib import Path

import requests

# Bump when assembly output changes materially (layouts, encoder, timing) so
# stale renders regenerate lazily.
PIPELINE_VERSION = "1"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "car-videos")

BROLL_CACHE_DIR = Path(os.environ.get("BROLL_CACHE_DIR", "/tmp/broll_cache"))


def video_key(procedure_path, vehicle, voice, fmt, extra=""):
    h = hashlib.sha256()
    with open(procedure_path, "rb") as f:
        h.update(f.read())
    for part in (PIPELINE_VERSION, vehicle or "", voice or "", fmt, extra):
        h.update(b"\x00" + str(part).encode())
    return h.hexdigest()[:24]


def public_url(object_name):
    if not (SUPABASE_URL and SUPABASE_BUCKET):
        return None
    return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{object_name}"


def exists(object_name):
    url = public_url(object_name)
    if not url:
        return False
    try:
        return requests.head(url, timeout=10).status_code == 200
    except Exception:
        return False


def upload(path, object_name, content_type="video/mp4"):
    if not (SUPABASE_URL and SUPABASE_KEY and SUPABASE_BUCKET):
        return None
    with open(path, "rb") as f:
        data = f.read()
    r = requests.post(
        f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{object_name}",
        data=data,
        headers={
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "apikey": SUPABASE_KEY,
            "Content-Type": content_type,
            "x-upsert": "true",
        },
        timeout=300,
    )
    if r.status_code in (200, 201):
        return public_url(object_name)
    print(f"supabase upload failed: {r.status_code} {r.text[:200]}")
    return None


def fetch_broll(library_key):
    """Download a library clip (uploaded by wan/ as broll/<key>.mp4) into the
    local disk cache; returns the path, or None when the clip doesn't exist
    yet (the assembler then falls back to a card segment)."""
    safe = library_key.replace("/", "__")
    local = BROLL_CACHE_DIR / f"{safe}.mp4"
    if local.exists() and local.stat().st_size > 0:
        return str(local)
    url = public_url(f"broll/{library_key}.mp4")
    if not url:
        return None
    try:
        r = requests.get(url, timeout=60)
        if r.status_code != 200:
            return None
        BROLL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = local.with_suffix(".part")
        with open(tmp, "wb") as f:
            f.write(r.content)
        os.replace(tmp, local)
        return str(local)
    except Exception as e:
        print(f"broll fetch failed for {library_key}: {e}")
        return None
