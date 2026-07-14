FROM runpod/pytorch:2.2.0-py3.10-cuda12.1.1-devel-ubuntu22.04

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# System deps. libgl/libglib/etc. are needed by opencv even in headless mode.
RUN apt-get update && apt-get install -y \
    git wget curl build-essential \
    libgl1-mesa-glx libglib2.0-0 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# PIFuHD: single-image -> high-resolution 3D human mesh (Facebook Research).
# Chosen over ECON/SIFU because its weights download freely with no signup;
# ECON/SIFU require the SMPL-X body model, which is license-gated behind a
# manual registration wall that can't be automated in a Docker build.
RUN git clone https://github.com/facebookresearch/pifuhd.git /app/pifuhd

# The lightweight pose estimator PIFuHD's demo uses to detect the person and
# produce the crop rectangle that the reconstruction is run on.
RUN git clone https://github.com/Daniil-Osokin/lightweight-human-pose-estimation.pytorch.git \
    /app/lightweight-human-pose-estimation.pytorch

# Python deps. PIFuHD and the pose repo predate modern NumPy and still use
# removed aliases (np.int / np.float), so NumPy is pinned to a version that
# still has them. scikit-image/opencv/PyMCubes supply marching cubes + IO.
RUN pip install --no-cache-dir \
    "numpy==1.23.5" scipy "scikit-image==0.21.0" opencv-python-headless \
    pillow tqdm matplotlib PyMCubes trimesh runpod requests

# Model weights baked into the image (same approach as the TripoSR worker), so
# there's no network-volume region-pinning to manage for a first deployment.
#   - pifuhd.pt (~1.5GB): the reconstruction network
#   - checkpoint_iter_370000.pth: the lightweight pose estimator
RUN mkdir -p /app/pifuhd/checkpoints /app/checkpoints && \
    wget -q "https://dl.fbaipublicfiles.com/pifuhd/checkpoints/pifuhd.pt" \
        -O /app/pifuhd/checkpoints/pifuhd.pt && \
    wget -q "https://download.01.org/opencv/openvino_training_extensions/models/human_pose_estimation/checkpoint_iter_370000.pth" \
        -O /app/checkpoints/checkpoint_iter_370000.pth

# gen_rect.py lives inside the pose repo so its `import models/modules/demo`
# resolve against that repo without a namespace clash with PIFuHD.
COPY gen_rect.py /app/lightweight-human-pose-estimation.pytorch/gen_rect.py
COPY handler.py /app/handler.py

CMD ["python3", "-u", "/app/handler.py"]
