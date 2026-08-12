# Damage scanner — RunPod serverless worker, NO-GPU API-proxy build.
#
# This is the DEFAULT and recommended deployment. It runs the vision stage as
# DAMAGE_BACKEND=anthropic (a frontier Claude vision model over the Anthropic
# API), so the container needs no GPU, no CUDA, no torch, and no model
# download. Consequences, all of which this repo paid for the hard way:
#
#   * Image is ~150 MB, not 4.7 GB / 10.6 GB. Cold start is seconds, not the
#     41 MINUTES a live GPU cold-start measured here (delayTime=2,474,145 ms
#     vs executionTime=157 ms). On a scale-to-zero endpoint, image size IS
#     cold-start latency — this removes it.
#   * No warm worker, no network volume, no HF weight cache. The endpoint can
#     truly scale to zero and cost nothing idle (which the GPU build could not,
#     because workersStandby defaults to 1 and is not settable via the API).
#   * The only runtime dependency for correctness is the Anthropic API — which
#     is also the accurate path (a local 7B model scored a shattered-windshield
#     car 99/100 in live testing; see analyze.py get_backend()).
#
# Same pattern as the Seedance worker (PR #14): API proxy, slim CPU image,
# cheapest RunPod workers. To run the local Qwen2.5-VL fallback instead, build
# Dockerfile.gpu and set DAMAGE_BACKEND=qwen — that variant needs a GPU.
#
# ISOLATION: own tag (alamk123/damage-scan:*), own CI (damage/** only). Nothing
# here imports from trellis2/ or building/, and neither is edited.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_NO_CACHE_DIR=1

# The whole dependency set: serverless glue + HTTP + the Anthropic client.
# All pure-Python wheels — no compiler, no system packages, no CUDA.
RUN pip install --upgrade pip && \
    pip install runpod requests anthropic

# Default the deployed image to the accurate, no-GPU backend. Override to qwen
# only on the GPU image. ANTHROPIC_API_KEY must be set on the endpoint (never
# baked in); DAMAGE_VLM_MODEL optionally overrides the model (default
# claude-opus-5). Reports are kilobytes and inline in the response, so no
# object storage or network volume is required.
ENV DAMAGE_BACKEND=anthropic
# DAMAGE_OUTPUT_DIR is deliberately NOT set: paths.py resolves a writable
# location at runtime, and this worker needs no persistent volume.

WORKDIR /app

# Source. The vision backends import their heavy deps lazily (torch only inside
# the qwen path, anthropic only inside the anthropic path), so this slim image
# imports and runs cleanly without torch/transformers ever installed.
COPY paths.py delivery.py progress.py validation.py handler.py \
     taxonomy.py severity.py repair.py quality.py analyze.py fusion.py \
     report.py compare.py /app/

CMD ["python", "-u", "/app/handler.py"]
