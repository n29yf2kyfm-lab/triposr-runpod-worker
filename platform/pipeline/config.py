"""Central config for the GLB ingest/fix pipeline.

All secrets and machine-specific paths come from environment variables so the
pipeline scripts stay repo-safe (no keys committed) and portable (no hardcoded
scratchpad paths). See README.md for the full variable list.

Required env for the networked scripts (ingest_process_hard, ingest_commit,
live_cand):
  SKETCHFAB_TOKENS         comma-separated Sketchfab API tokens (rotated on 429/403)
  SUPABASE_SERVICE_KEY     service-role key for the serving Supabase project
  RUNPOD_API_KEY           RunPod API key (rpa_...)

Optional env (sensible defaults):
  PIPELINE_WORKDIR         scratch dir for downloads/renders (default: ./ pipeline_work)
  PIPELINE_ASSETS          dir holding plate_front.png / plate_rear.png (default: ./assets)
  RUNPOD_RENDER_ENDPOINT   render endpoint id (default: ng8oiz4p2l0xa0)
  SUPABASE_OBJECT_URL      Supabase storage object base (default: public serving project)

Dev fallback: if a secret env var is missing, we try to read it out of a local
untracked golf_publish.py in PIPELINE_WORKDIR (the historic scratchpad layout),
so an existing scratchpad checkout keeps working without extra setup.
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
WORKDIR = os.environ.get("PIPELINE_WORKDIR", os.path.join(os.getcwd(), "pipeline_work"))
ASSETS = os.environ.get("PIPELINE_ASSETS", os.path.join(HERE, "assets"))
RUNPOD_ENDPOINT = os.environ.get("RUNPOD_RENDER_ENDPOINT", "ng8oiz4p2l0xa0")
SUPABASE_OBJECT_URL = os.environ.get(
    "SUPABASE_OBJECT_URL",
    "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object",
)


def _from_legacy(pattern):
    """Best-effort read of a secret from an untracked golf_publish.py in WORKDIR."""
    p = os.path.join(WORKDIR, "golf_publish.py")
    if not os.path.exists(p):
        return None
    try:
        m = re.search(pattern, open(p).read())
        return m.group(1) if m and m.lastindex else (m.group(0) if m else None)
    except Exception:
        return None


def sketchfab_tokens():
    raw = os.environ.get("SKETCHFAB_TOKENS", "").strip()
    toks = [t.strip() for t in raw.split(",") if t.strip()]
    if not toks:
        legacy = _from_legacy(r'SKETCHFAB[_A-Z]*\s*=\s*"([^"]+)"')
        if legacy:
            toks = [legacy]
    if not toks:
        raise SystemExit("config: set SKETCHFAB_TOKENS (comma-separated) in the environment")
    return toks


def supabase_service_key():
    k = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    if not k:
        k = _from_legacy(r'SBKEY\s*=\s*"([^"]+)"') or ""
    if not k:
        raise SystemExit("config: set SUPABASE_SERVICE_KEY in the environment")
    return k


def runpod_api_key():
    k = os.environ.get("RUNPOD_API_KEY", "").strip()
    if not k:
        k = _from_legacy(r"rpa_[A-Za-z0-9]+") or ""
    if not k:
        raise SystemExit("config: set RUNPOD_API_KEY in the environment")
    return k
