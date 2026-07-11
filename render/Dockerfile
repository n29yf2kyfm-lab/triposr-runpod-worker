# GPU render worker: Blender (bpy) Cycles on CUDA/OPTIX. Runtime CUDA base is
# enough — bpy ships its own Cycles kernels; we only need the NVIDIA driver
# (provided by RunPod at run time) plus the X/GL shared libs bpy links against.
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# bpy 4.2 wheels are built for CPython 3.11, so we install python3.11 from
# deadsnakes. fonts-dejavu-core provides the plate font; the libX*/libGL/libSM
# packages are bpy's runtime shared-library dependencies (it still links them
# even in background mode).
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common ca-certificates curl wget \
    && add-apt-repository ppa:deadsnakes/ppa -y \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3.11 python3.11-dev python3.11-venv \
        fonts-dejavu-core \
        libgomp1 \
        libx11-6 libxi6 libxxf86vm1 libxfixes3 libxrender1 libxkbcommon0 \
        libxrandr2 libxinerama1 libxcursor1 \
        libgl1 libglu1-mesa libegl1 libsm6 libxext6 libxml2 \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.11 /usr/bin/python && \
    curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11

# bpy 4.2.0 == Blender 4.2 LTS (Principled v2 Coat inputs + AgX view transform,
# which the render pipeline relies on). runpod = serverless SDK.
RUN pip install --no-cache-dir \
        bpy==4.2.0 \
        runpod requests pillow numpy

WORKDIR /app
COPY assets/hdri.hdr /app/assets/hdri.hdr
COPY handler.py /app/handler.py

ENV HDRI_PATH=/app/assets/hdri.hdr
ENV PLATE_FONT=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf

CMD ["python", "-u", "/app/handler.py"]
