"""Preload Wan 2.2 weights so the worker can run without request-time downloads.

Same pattern as trellis2/preload_models.py: run once with network access,
HF_HOME pointed at the RunPod network volume (or a dir baked into the image),
then set OFFLINE=1 on the endpoint.

  HF_HOME=/runpod-volume/hf_cache python preload_models.py

Inventory (~60GB in bf16 — use a network volume, do NOT bake into the image):
  1. Wan-AI/Wan2.2-I2V-A14B-Diffusers  - two 14B experts + T5 + VAE
  2. lightx2v/Wan2.2-Distill-Loras     - 4-step distill LoRAs (small)
  3. STYLE_LORA (optional env)         - automotive fine-tune, when trained
"""
import os
import sys

from huggingface_hub import snapshot_download

MODELS = [
    (os.environ.get("WAN_MODEL", "Wan-AI/Wan2.2-I2V-A14B-Diffusers"), None),
    (os.environ.get("DISTILL_LORA_REPO", "lightx2v/Wan2.2-Distill-Loras"), None),
]
if os.environ.get("STYLE_LORA"):
    MODELS.append((os.environ["STYLE_LORA"], None))

TOKEN = os.environ.get("HF_TOKEN") or None


def main():
    print(f"Preloading into HF_HOME={os.environ.get('HF_HOME', '~/.cache/huggingface')}")
    failures = []
    for repo_id, allow in MODELS:
        print(f"\n=== {repo_id} ===")
        try:  # local-first: complete cache hit needs no network
            path = snapshot_download(repo_id, allow_patterns=allow, local_files_only=True)
            print(f"    cached -> {path}")
            continue
        except Exception:
            pass
        try:
            path = snapshot_download(repo_id, allow_patterns=allow, token=TOKEN)
            print(f"    ok -> {path}")
        except Exception as e:
            failures.append(repo_id)
            print(f"    FAILED: {type(e).__name__}: {e}")

    print()
    if failures:
        print(f"INCOMPLETE — missing: {failures}")
        sys.exit(1)
    print("All models cached. The worker can now run with OFFLINE=1.")


if __name__ == "__main__":
    main()
