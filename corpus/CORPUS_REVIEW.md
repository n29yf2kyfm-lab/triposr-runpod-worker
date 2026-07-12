# Corpus — engineering audit & action plan

Technical review of the structural risks in the Corpus pipeline, with the fixes.

## 1. Architectural blind spots

### A. Headless GPU OpenGL crash (Phase 0)
`pyrender` (a `sam-3d-body` dependency) wants an active OpenGL context. In a
headless RunPod serverless container it crashes on import/mesh init with an
`OpenGL.error.NullFunctionError`. **Fix:** run pyrender headlessly via OSMesa/EGL
and set the platform env var — applied in `phase0/Dockerfile`
(`PYRENDER_PLATFORM=osmesa` + the OSMesa apt packages).

### B. The WebGPU ViT-H memory wall (Phase 2)
The zero-cost plan relies on on-device WebGPU inference of SAM 3D Body ViT-H
(637M params). In FP16 that's ~1.27 GB just to load and 3–4 GB peak during
self-attention. iOS Safari caps per-tab GPU allocations (~1 GB standard, ~2 GB
Pro), so most mobile devices will silently OOM. **Fix:** switch the on-device
encoder to a quantized **MobileSAM / SAM-tiny** in a 4-bit ONNX runtime (model
footprint <40 MB) with minor silhouette-quality loss.

### C. The missing vertex → measurement bridge
There's a gap between the mesh (`pred_vertices`) and the regressor's inputs
(waist/hip/arm circumference, leg length). A raw mesh can't be "guessed" into
measurements. **Fix:** landmark-indexing — SAM 3D Body outputs vertices on a
standard template (SMPL family), so fixed vertex-ring indices map to physical
landmarks (narrowest waist, widest hip). Extract circumferences as closed-loop
polygon perimeters.

## 2. Patches

### Patch 1 — headless pyrender (Dockerfile)
Applied in `phase0/Dockerfile`: install `libosmesa6-dev libgl1-mesa-glx xvfb`,
set `ENV PYRENDER_PLATFORM=osmesa`.

### Patch 2 — vertices → measurements
```python
import numpy as np

def circumference(vertices, ring_indices):
    """Perimeter of a closed 3D loop defined by an ordered index ring."""
    pts = vertices[ring_indices]
    d = np.linalg.norm(pts - np.roll(pts, -1, axis=0), axis=1)
    return float(np.sum(d))

def extract_nhanes_inputs(pred_vertices, height_cm):
    # scale camera-space mesh to metric using known height
    mesh_h = pred_vertices[:, 1].max() - pred_vertices[:, 1].min()
    scale = (height_cm / 100.0) / mesh_h
    v = pred_vertices * scale

    # NOTE: these ring/joint indices are PLACEHOLDERS — fill from the actual
    # template topology before trusting the output.
    WAIST = [2529, 2530, 2531, 2532]
    HIP   = [3120, 3121, 3122, 3123]
    ARM   = [1280, 1281, 1282, 1283]
    HIP_J, ANKLE_J = [120, 121], [340, 341]

    leg = np.linalg.norm(v[HIP_J].mean(0) - v[ANKLE_J].mean(0))
    return {
        "waist_cm": round(circumference(v, WAIST) * 100, 1),
        "hip_cm":   round(circumference(v, HIP)   * 100, 1),
        "arm_circ_cm": round(circumference(v, ARM) * 100, 1),
        "leg_length_cm": round(leg * 100, 1),
    }
```

## 3. Physical consistency note on NHANES features

NHANES has no thigh circumference — the regressor uses `BMXLEG` (upper-leg
*length*, inguinal fold → mid-patella), a skeletal length, not a muscle/fat
indicator. Two people with the same leg length but very different quad
development get the same feature value. **v1.1 upgrade:** once a client-side mesh
exists, compute a thigh-segment volume proxy (`volume / length²`) to capture
muscular mass changes the NHANES features can't.
