# Training the damage detector

Produces the ONNX model that `DAMAGE_BACKEND=detector` runs on CPU
(`../detect.py`). Training needs a rented GPU **once**; inference afterwards is
free, CPU-only, and ~0.1–0.4 s/image against 5–20 s for any hosted VLM.

Nothing in here ships in the worker image — the `Dockerfile` copies named
modules, not this directory.

## Why a licence section comes first

The convenient pre-trained car-damage models are unusable in a commercial
product, which is why this repo trains its own:

- **Ultralytics YOLOv8/v11 weights are AGPL-3.0.** Serving one over a network —
  exactly what this worker does — triggers copyleft on the whole application
  unless a commercial licence is bought.
- **CarDD**, which nearly every strong HuggingFace car-damage model is fine-tuned
  on, is **non-commercial research only**, and does not own the underlying
  Flickr/Shutterstock image copyrights.

So: an **Apache-2.0 architecture** (RF-DETR, RT-DETR, D-FINE) on **permissively
licensed data**. Then the weights are genuinely ours.

## Data

Surveyed Aug 2026: **311** unique car-damage projects on Roboflow Universe,
**395,517** images total; the top 25 projects sum to roughly 200k.

The primary set, and the one `prepare_data.py` is verified against:

| Source | Licence | Images | Classes |
|---|---|---|---|
| `ai-model-vapko/vehicle-damage-detection-9tpqp` v2 | **CC BY 4.0** | 7,889 (13,436 aug.) | Scratch, Dent, Crack, Rust_Corrision, Paint Damage, Flat Tire, Lamp Broken |
| `curacel-ai/car-damage-detection-5ioys` v1 | **Public Domain** | 6,839 | panel-specific damage (`front-bumper-dent`, `bonnet-dent`, …) |

CC BY 4.0 permits commercial use **with attribution** — keep the credit line in
the app/docs. The Public Domain set carries no obligation, and its
panel-specific classes are the route to resolving *which panel* a finding sits
on. Its long tail is unusable (`doorouter-scratch` has 4 examples,
`doorouter-paint-trace` has 0), so `MIN_BOXES` drops anything too sparse to
learn: a class that fires at random is worse than one that never fires, because
a confident-looking wrong finding reaches an invoice.

HuggingFace was searched too. Its best detection-grade set
(`yusufnull/car-parts-and-damage-dataset`, MIT, 814 damage images) is ~10×
smaller, and the other seven hits are the same dataset re-uploaded. Note that HF
licence tags are **self-declared by the uploader** — verify provenance before
relying on one commercially.

## Prepare

```bash
python prepare_data.py --src /path/to/roboflow-coco-export --out ./prepared
```

Remaps source class names onto `taxonomy.DAMAGE_TYPES` so the trained model
emits taxonomy ids natively — no translation layer at inference, and no class
able to silently fail to map on a customer's scan. Unmapped names are reported
loudly rather than dropped.

Verified on the primary set: **11,094 train / 1,184 valid / 1,158 test images,
20,762 boxes, 0 unmapped, 0 degenerate**, remapped onto seven classes —
`crack 4531 · dent 5804 · scratch 5629 · rust 3424 · paint_chip 794 ·
tire_damage 470 · lamp_damage 110`.

### The label contract

`prepare_data.py` writes `labels.txt`, and **`DAMAGE_DETECTOR_LABELS` must be set
to that exact string.** Real classes start at id **1**; id 0 is a reserved
placeholder in the Roboflow/RF-DETR COCO convention. Reindexing from 0 trains a
model whose every prediction is off by one class — dents reported as cracks —
while loss curves and mAP look perfectly healthy, because the labels stay
self-consistent during training and are only wrong against the taxonomy. The
placeholder is carried into `labels.txt` so the index → name lookup at inference
lines up with what was trained.

## What accuracy to expect

**mAP of 99% is not achievable, by anyone.** State of the art on COCO is ~60
mAP; RF-DETR made news in 2025 for being the first real-time model past 60.
Published car-damage models land around mAP50 0.70–0.85 on the easy classes,
and much lower on cracks.

The reason is structural, not a matter of more data: mAP requires the predicted
box to overlap ground truth at IoU thresholds up to 0.95, and damage has no
crisp boundary — two expert appraisers draw different boxes around the same
dent. **A model cannot score higher than the annotators agree with each other.**

Target these instead, because they are what the product actually rides on:

| Metric | Realistic | Why |
|---|---|---|
| **Recall on structural damage** | **95–99%** | Never miss a shattered windshield — the failure that matters |
| "Is this car damaged at all?" | 95%+ | Triage |
| mAP50, main classes | 0.80–0.88 | Box quality |
| mAP50-95 | 0.45–0.60 | The honest number |

This product does not fail because a dent box is 8 px off. It fails if it
**misses** severe damage or **invents** damage that is not there. So tune for
recall on the dangerous classes, keep confidence calibrated, and escalate
low-confidence scans to `DAMAGE_BACKEND=anthropic` — the seam is already there.

## Scaling the data

More images help only after the label vocabularies are reconciled. Merging
projects that disagree — one calls a region `Car-Damage`, another
`dent`+`scratch` — teaches the model that identical pixels are different
classes and makes it worse. Extend `CLASS_MAP`, and dedupe by image hash:
re-uploads of the same dataset are common (one HuggingFace set appeared 8
times).
