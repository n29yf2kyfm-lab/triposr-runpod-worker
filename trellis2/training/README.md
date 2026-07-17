# Car LoRA training — make the T2I stage factory-accurate

The text stage's remaining weakness is *year/generation accuracy* (live
examples: "2025 Defender" drew the classic shape; "2024 Q7" drew the Mk1).
A LoRA fine-tuned on real, captioned car photos fixes this class of error.
The worker already has the hook: set `T2I_LORA` on the endpoint template —
no code change, no rebuild.

## Dataset spec (what to collect)

- **Images**: real photos, one vehicle per frame, ≥1024px on the long edge,
  eye-level or three-quarter views preferred. 30–80 images per model
  generation you care about; 1,000–5,000 total is a strong v1.
- **Sources you already own**: `car_listings` photos in the app's storage,
  dealer/turntable shots (like the MC18 OZL set). For gaps, openly-licensed
  photos (Wikimedia) — keep the licence column.
- **Captions**: one `.txt` per image, same basename. Format mirrors the
  worker's vehicle-prompt builder so training and inference vocabulary match:

      a 2024 Audi Q7 S line, district green metallic paint, SUV,
      three-quarter front view

  `make_captions.py` generates these from a CSV export of the `vehicles` /
  `car_listings` tables (reg → DVLA/DVSA spec → caption).

## Layout

    training/data/
      img/0001.jpg  0001.txt
      img/0002.jpg  0002.txt ...

## Run (RunPod pod, A40 48GB, ~2-4h, ~$2-4)

    bash train_lora_sdxl.sh /workspace/data  # produces cars-v1.safetensors

Upload the output to the network volume (`/runpod-volume/loras/cars-v1`) or
an HF repo, then set on the endpoint template:

    T2I_LORA=/runpod-volume/loras/cars-v1

## Base model note
Train against the SAME base the endpoint runs (`T2I_MODEL`, currently
RealVisXL Lightning). If you switch bases later, retrain or re-test — LoRAs
are base-specific in quality.
