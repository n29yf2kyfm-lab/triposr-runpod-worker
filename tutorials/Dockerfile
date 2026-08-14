# Tutorial assembler — CPU-ONLY worker. No CUDA base image, no diffusion:
# the request path is TTS + PIL + ffmpeg, so this runs on RunPod CPU
# serverless or any small VPS. Keeping GPUs out of this image is the
# economic guardrail (see README.md).

FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# libass in the ffmpeg build is required for the subtitles filter.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg fonts-dejavu-core wget \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    runpod requests Pillow pyyaml numpy kokoro-onnx onnxruntime

WORKDIR /app

# Kokoro weights (~330MB) are small enough to bake in — no volume needed.
RUN mkdir -p /app/models && \
    wget -q -O /app/models/kokoro-v1.0.onnx \
      https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx && \
    wget -q -O /app/models/voices-v1.0.bin \
      https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin

COPY procedures /app/procedures
COPY script_gen.py tts.py cards.py assemble.py cache.py publish.py handler.py /app/

CMD ["python", "-u", "/app/handler.py"]
