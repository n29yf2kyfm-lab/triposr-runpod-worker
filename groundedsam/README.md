# Grounded-SAM worker — car-part segmentation for the TRELLIS material split

A RunPod serverless GPU worker that turns rendered car views into clean
per-part masks (glass / wheel / light), so single-mesh TRELLIS outputs can be
split into a **recolourable body material** with correctly-excluded glass and
wheels — no more paint flooding the windows.

It is a pure **image-in / masks-out** service. All 3D work (multi-view render,
projection, occlusion, per-face vote fusion, material assignment) stays on the
CPU side in Blender (`scratchpad/seg_stepA_render.py`, `seg_step2_vote.py`,
`seg_stepB_assign.py`). Only the 2D masking runs here on the GPU, so the model
is a drop-in swap for the classical HSV masker used during local development.

## Why this exists
Heuristic segmentation of a baked single mesh hits a ceiling: on the baked
texture the glass mirrors the body paint, so colour can't separate them, and a
pure geometric z-band can't trace the sloped window line. Segmenting the
**rendered image** instead — where glass reads as dark glazing and wheels are
distinct — and back-projecting the masks onto faces across ~12 views is the
robust fix. Grounding DINO + SAM give premium, semantically-correct boundaries.

## Model
- **Grounding DINO** (`IDEA-Research/grounding-dino-base`) — text-prompt
  detection: `car windshield. car window. car wheel. car tyre. headlight. tail light.`
- **SAM** (`facebook/sam-vit-huge`) — box-prompted masks from those detections.
- Both ship inside `transformers`; licences are Apache-2.0 (UK-safe).

## I/O
```
input:  { "images_b64": [ "<png/jpeg b64>", ... ],
          "prompt": "<optional>", "box_threshold": 0.28, "text_threshold": 0.22 }
output: { "masks_b64":  [ "<png b64>", ... ] }   # single-channel class map:
          # 0 = background/body, 2 = glass, 3 = wheel, 4 = light
```

## Deploy
1. Push touching `groundedsam/**` → CI builds `alamk123/ai-mechanic:gsam-latest`.
2. Create a RunPod serverless endpoint on that image, GPU >= 16GB, attach the
   shared network volume at `/runpod-volume` for the weight cache.
3. Point `seg_step2_vote.py`'s mask provider at the endpoint id.
