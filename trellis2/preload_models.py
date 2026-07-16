"""Preload every model the worker needs, so it can run with ZERO network access.

The worker hits the network for five things at request time if caches are cold
(inventory taken from microsoft/TRELLIS.2-4B's pipeline.json + our handler):

  1. microsoft/TRELLIS.2-4B                       - 8 checkpoints + pipeline.json
  2. microsoft/TRELLIS-image-large                - 1 reused v1 checkpoint
                                                    (ss_dec_conv3d_16l8_fp16)
  3. facebook/dinov3-vitl16-pretrain-lvd1689m     - image conditioner  [GATED]
  4. briaai/RMBG-2.0                              - background removal [GATED]
  5. T2I_MODEL (default SDXL base 1.0)            - text-to-image stage

Run this ONCE with network access, pointing HF_HOME at the cache location the
worker will read (the RunPod network volume, or a directory baked into the
image), and the worker never needs the internet again:

  # onto the network volume (from any pod that has it mounted):
  HF_HOME=/runpod-volume/hf_cache HF_TOKEN=hf_... python preload_models.py

  # baked into the Docker image: see PRELOAD_MODELS build arg in the Dockerfile.

GATED repos (3) and (4) require visiting the model page on huggingface.co,
accepting the license, and passing a token via HF_TOKEN. The script tells you
exactly which ones are missing access rather than failing cryptically.

After preloading, set HF_HUB_OFFLINE=1 (or OFFLINE=1 for the handler) on the
endpoint to guarantee no network calls sneak through.
"""
import os
import sys

from huggingface_hub import snapshot_download
from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError

T2I_MODEL = os.environ.get("T2I_MODEL", "stabilityai/stable-diffusion-xl-base-1.0")
TOKEN = os.environ.get("HF_TOKEN") or None

# (repo_id, allow_patterns, ignore_patterns, gated)
MODELS = [
    ("microsoft/TRELLIS.2-4B", None, None, False),
    # Only the one checkpoint TRELLIS.2's pipeline.json borrows from v1 —
    # not the entire v1 model repo.
    ("microsoft/TRELLIS-image-large",
     ["ckpts/ss_dec_conv3d_16l8_fp16*", "pipeline.json"], None, False),
    ("facebook/dinov3-vitl16-pretrain-lvd1689m", None, None, True),
    ("briaai/RMBG-2.0", None, ["*.onnx*"], True),
    # fp16-friendly subset; skip the giant fp32 .bin duplicates.
    (T2I_MODEL, None, ["*.bin", "*.onnx*", "*.ckpt"], False),
]


def main():
    print(f"Preloading into HF_HOME={os.environ.get('HF_HOME', '~/.cache/huggingface')}")
    failures = []
    for repo_id, allow, ignore, gated in MODELS:
        print(f"\n=== {repo_id} ===")
        # Local-first: a complete cache hit is success with no network and no
        # token — this is what lets a pod/worker reuse gated models already on
        # the shared volume without re-authenticating.
        try:
            path = snapshot_download(
                repo_id, allow_patterns=allow, ignore_patterns=ignore,
                local_files_only=True,
            )
            print(f"    cached -> {path}")
            continue
        except Exception:
            pass
        try:
            path = snapshot_download(
                repo_id,
                allow_patterns=allow,
                ignore_patterns=ignore,
                token=TOKEN,
            )
            print(f"    ok -> {path}")
        except GatedRepoError:
            failures.append(repo_id)
            print(f"    GATED: visit https://huggingface.co/{repo_id}, accept the "
                  f"license, and re-run with HF_TOKEN set to a token of that account.")
        except RepositoryNotFoundError:
            failures.append(repo_id)
            print(f"    NOT FOUND (private or renamed?). If gated+private, HF_TOKEN "
                  f"with granted access is required even to see it.")
        except Exception as e:  # keep going; report at the end
            failures.append(repo_id)
            print(f"    FAILED: {type(e).__name__}: {e}")

    print()
    if failures:
        print(f"INCOMPLETE — {len(failures)} model(s) missing: {failures}")
        print("The worker is NOT fully offline-capable until these are cached.")
        sys.exit(1)
    print("All models cached. The worker can now run with HF_HUB_OFFLINE=1.")


if __name__ == "__main__":
    main()
