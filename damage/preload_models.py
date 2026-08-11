"""Preload the vision model into HF_HOME for offline operation.

Optional, and only run when the image is built with PRELOAD_MODELS=1. Pair with
OFFLINE=1 on the endpoint so a cache miss fails fast with a clear error instead
of hanging on a multi-GB download mid-request. Same pattern as the vehicle and
building workers.

Run standalone to warm a network-volume cache from a pod:
    HF_HOME=/runpod-volume/damage_hf_cache python preload_models.py
"""
import os
import sys


def main():
    model_id = os.environ.get("DAMAGE_VLM_MODEL",
                              "Qwen/Qwen2.5-VL-7B-Instruct")
    print(f"preloading {model_id} into {os.environ.get('HF_HOME', '~/.cache')}",
          file=sys.stderr)
    try:
        from transformers import (AutoProcessor,
                                  Qwen2_5_VLForConditionalGeneration)
        AutoProcessor.from_pretrained(model_id)
        Qwen2_5_VLForConditionalGeneration.from_pretrained(
            model_id, torch_dtype="auto")
        print("preload complete", file=sys.stderr)
    except Exception as e:
        # Never fail the build on a preload hiccup — the worker can still
        # download at first request when OFFLINE is not set.
        print(f"WARN: preload failed ({type(e).__name__}: {e}). The image is "
              f"still usable when OFFLINE is unset.", file=sys.stderr)


if __name__ == "__main__":
    main()
