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

# bpy 4.5.11 == Blender 4.5 LTS (Principled v2 Coat inputs + AgX view
# transform, which the render pipeline relies on). 4.5 is the FIRST LTS whose
# wheel bundles libextern_draco.so (draco starts at 4.4.0) — the serving
# catalogue is draco-compressed, so this is a hard requirement.
# runpod = serverless SDK.
RUN pip install --no-cache-dir \
        bpy==4.5.11 \
        runpod requests pillow numpy

# build-time verification (institutional rule: builds must import-check what
# they claim to ship): bpy imports headless AND the draco decoder is bundled.
RUN python - <<'PYCHECK'
import glob, os
import bpy
scripts = bpy.utils.system_resource("SCRIPTS")
hits = glob.glob(os.path.join(scripts, "**", "libextern_draco*.so"),
                 recursive=True)
assert hits, "bpy wheel has NO libextern_draco — draco catalogue would fail"
print("bpy", bpy.app.version_string, "draco lib:", hits[0])
PYCHECK

WORKDIR /app
COPY assets/hdri.hdr /app/assets/hdri.hdr
COPY handler.py /app/handler.py

ENV HDRI_PATH=/app/assets/hdri.hdr
ENV PLATE_FONT=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf

CMD ["python", "-u", "/app/handler.py"]
