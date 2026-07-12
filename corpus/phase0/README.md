# Phase 0 — real SAM 3D Body inference on RunPod

Goal: does a real 3D avatar of a person actually look like them?
Gate: silhouette IoU ≥ 0.85 vs the source photo (eyeball it for the first pass).

Uses the official `facebookresearch/sam-3d-body` repo and the gated
`facebook/sam-3d-body-dinov3` checkpoint. Nothing here is mocked — but it needs
a GPU, a container registry, and your own RunPod + Hugging Face accounts, which
is why it can't run in the free local loop.

## Files

| File | Purpose |
|---|---|
| `Dockerfile` | Builds the inference container (headless OSMesa OpenGL so pyrender doesn't crash). |
| `requirements.txt` | Deps from the repo's INSTALL.md. |
| `handler.py` | RunPod serverless handler — real inference, returns 3D vertices/keypoints. |
| `test_endpoint.py` | Calls your deployed endpoint with a real photo. |

## Steps

**1. Build and push the image**
```bash
docker build -t <dockerhub-user>/sam3d-body:phase0 .
docker push <dockerhub-user>/sam3d-body:phase0
```

**2. Create the RunPod serverless endpoint**
- Serverless → New Endpoint → container image `<dockerhub-user>/sam3d-body:phase0`
- GPU: RTX A5000 (24 GB) is enough
- Env var: add `HF_TOKEN` as a **secret** (your approved HF token) — never bake it into the image
- Attach a Network Volume mounted at `/runpod-volume` so the checkpoint persists across cold starts
- Deploy; note the Endpoint ID and a RunPod API key

**3. Run a real test**
```bash
export RUNPOD_API_KEY="…"
export RUNPOD_ENDPOINT_ID="…"
python test_endpoint.py path/to/photo.jpg
```

## Next: vertices → measurements

The mesh output (`pred_vertices`, SMPL-family topology) feeds the regressor's
inputs (waist/hip/arm circumference, leg length) via fixed landmark ring indices.
That bridge is sketched in `../CORPUS_REVIEW.md §2` — the ring indices there are
placeholders and must be filled from the actual template topology before use.
