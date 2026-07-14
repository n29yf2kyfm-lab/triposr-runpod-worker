# MetaHuman RunPod Serverless Worker

RunPod serverless worker for **single-photo → 3D human avatar**, built on
[PIFuHD](https://github.com/facebookresearch/pifuhd) (Facebook Research) — a
high-resolution clothed-human 3D reconstruction model.

Send it one photo of a person, get back a textured `.glb` 3D model. Same input/
output contract as the TripoSR and TRELLIS workers, so the app can call it the
same way (via a Supabase edge function).

## Input

URL or base64, same shape as the other workers:

```json
{
  "input": {
    "image_url": "https://example.com/person.jpg"
  }
}
```

```json
{
  "input": {
    "image_b64": "<base64 encoded image>",
    "resolution": "256"
  }
}
```

- `resolution` is optional (default `256`). `512` is sharper but ~4x slower and
  needs much more VRAM.

## Output

```json
{
  "status": "success",
  "glb_b64": "<base64 encoded GLB file>",
  "glb_path": "/runpod-volume/outputs/<job_id>.glb",
  "resolution": "256",
  "message": "GLB generated successfully"
}
```

`glb_path` is `null` when no network volume is mounted (the GLB is still
returned as base64).

## How it works

1. **Person detection** — a lightweight pose estimator finds the person and
   computes the crop rectangle PIFuHD expects (`gen_rect.py`).
2. **Reconstruction** — `apps/simple_test.py` runs PIFuHD over that crop and
   writes an OBJ mesh with per-vertex colors.
3. **Export** — the OBJ is converted to GLB with `trimesh` and returned as
   base64.

## Why PIFuHD (and not ECON / SIFU)

PIFuHD's weights download freely with no signup. The newer, higher-quality
options (ECON, SIFU) depend on the **SMPL-X body model**, which is license-gated
behind a manual registration wall — that can't be automated in a Docker build,
so it would break unattended CI/deploys. PIFuHD has no such wall.

Tradeoff to set expectations: PIFuHD (2020) produces a solid single-mesh 3D
reconstruction of the person. It is **not** Unreal-Engine-MetaHuman-quality
(no separate rig, blendshapes, or hair cards) — it's the open-source analog for
"turn a photo into a 3D human" that will actually build and deploy here.

## Deployment notes

- **Weights are baked into the image** (`pifuhd.pt` ~1.5GB + the pose
  checkpoint), like the TripoSR worker — no network-volume region pinning to
  manage. Outputs are still persisted to `/runpod-volume/outputs/<job_id>.glb`
  when a volume happens to be mounted.
- **GPU:** any RunPod Ampere GPU (e.g. AMPERE_48) is plenty; PIFuHD is far
  lighter than TRELLIS. No custom CUDA extensions are compiled, so the build is
  simpler than the TRELLIS one.
- **CI** (`.github/workflows/metahuman-docker-build.yml`) builds and pushes on
  any push to `metahuman/**` on `main` (plus manual dispatch), tagged
  `alamk123/ai-mechanic:metahuman-v1`, `:metahuman-latest`, and a per-commit
  SHA tag (so RunPod is forced to pull fresh content rather than reuse a cached
  image for a tag name it has already seen).

## Known unknowns

This Dockerfile and handler were written from PIFuHD's documented demo flow but
have **not been GPU-build-tested** in this environment (no GPU in the authoring
sandbox) — same situation as the TRELLIS worker's first cut. Most likely first
failure points, in order:

1. **PIFuHD on modern PyTorch (2.2).** PIFuHD targeted torch 1.x. NumPy is
   pinned to keep `np.int`/`np.float` alive, but a torch-API incompatibility
   could still surface in `apps/simple_test.py`. Fix forward from whatever the
   `stderr` in the job response shows.
2. **Weight download URLs.** The pose checkpoint (`download.01.org`) and
   `dl.fbaipublicfiles.com/pifuhd/checkpoints/pifuhd.pt` must both be reachable
   from the CI runner. If either 404s, host a mirror and update the Dockerfile.
3. **Per-job model reload.** For simplicity this v1 runs reconstruction as a
   subprocess, so each job reloads the ~1.5GB checkpoint (adds cold-ish latency
   per request). If throughput matters, refactor to import PIFuHD's
   `reconWrapper` and keep the net warm in the handler process.

Run a real build via the CI workflow, submit one test job, and fix forward from
the first error surfaced in the response's `stderr`.
