"""Preload every model the building worker needs, so it can run offline.

Same discipline as the vehicle worker: fetch everything into HF_HOME once,
with network access, then set OFFLINE=1 on the endpoint so a cache miss
fails fast with a clear error instead of hanging on a multi-GB download in
the middle of a customer's scan.

Run once, pointing HF_HOME at wherever the worker will read from:

    HF_HOME=/runpod-volume/building_hf_cache HF_TOKEN=hf_... \
        python preload_models.py

Note this uses a DIFFERENT cache path from the vehicle worker
(/runpod-volume/hf_cache) so the two products never contend.
"""
import os
import sys

from huggingface_hub import snapshot_download
from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError

TOKEN = os.environ.get("HF_TOKEN") or None

# (repo_id, allow_patterns, ignore_patterns, phase, required)
#
# `required` is the honest bit: the worker is useful without the Phase 5
# vision models, so a failure there should not fail the whole preload.
MODELS = [
    # --- Phase 1: reconstruction -------------------------------------
    # MapAnything: Apache 2.0 code, metric by design. Checkpoint licences
    # vary by training data — verify each one separately from the code
    # licence before commercial release.
    ("facebook/map-anything", None, ["*.onnx*"], "1", True),

    # --- Phase 5: condition -------------------------------------------
    # SAM 2 segments what YOLO locates — the two-stage pattern the 2026
    # crack-segmentation literature converged on.
    ("facebook/sam2-hiera-large", None, ["*.onnx*"], "5", False),
    # Qwen-VL writes the survey prose and reads existing drawings. Strong on
    # documents and diagrams, Apache 2.0.
    ("Qwen/Qwen2.5-VL-7B-Instruct", None, ["*.bin", "*.onnx*"], "5", False),
    # Proven in the vehicle worker as the non-gated segmentation option.
    ("ZhengPeng7/BiRefNet", None, ["*.onnx*"], "5", False),
]


def main():
    home = os.environ.get("HF_HOME", "~/.cache/huggingface")
    print(f"Preloading into HF_HOME={home}")
    if "building" not in home:
        print("  NOTE: HF_HOME does not look like the building cache path. "
              "The vehicle worker uses /runpod-volume/hf_cache; this worker "
              "should use /runpod-volume/building_hf_cache to keep them "
              "separate.")

    required_failures, optional_failures = [], []

    for repo_id, allow, ignore, phase, required in MODELS:
        print(f"\n=== {repo_id}  (phase {phase}"
              f"{', required' if required else ', optional'}) ===")
        # Local-first: a complete cache hit is success with no network and no
        # token. This is what lets a worker reuse models already sitting on a
        # shared volume without re-authenticating.
        try:
            path = snapshot_download(repo_id, allow_patterns=allow,
                                     ignore_patterns=ignore,
                                     local_files_only=True)
            print(f"    cached -> {path}")
            continue
        except Exception:
            pass

        try:
            path = snapshot_download(repo_id, allow_patterns=allow,
                                     ignore_patterns=ignore, token=TOKEN)
            print(f"    ok -> {path}")
        except GatedRepoError:
            (required_failures if required else optional_failures).append(repo_id)
            print(f"    GATED: visit https://huggingface.co/{repo_id}, accept "
                  f"the licence, and re-run with HF_TOKEN set to a token of "
                  f"that account.")
        except RepositoryNotFoundError:
            (required_failures if required else optional_failures).append(repo_id)
            print(f"    NOT FOUND (private, renamed, or the id has changed).")
        except Exception as e:
            (required_failures if required else optional_failures).append(repo_id)
            print(f"    FAILED: {type(e).__name__}: {e}")

    print()
    if optional_failures:
        print(f"Optional models missing: {optional_failures}")
        print("Reconstruction still works; Condition Mode will not.")
    if required_failures:
        print(f"INCOMPLETE — required models missing: {required_failures}")
        print("The worker is NOT offline-capable until these are cached.")
        sys.exit(1)
    print("All required models cached. The worker can run with OFFLINE=1.")


if __name__ == "__main__":
    main()
