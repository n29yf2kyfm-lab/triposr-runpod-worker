#!/usr/bin/env python3
"""carparts_train.py — CPU FEASIBILITY PROBE, not a production model.

Fine-tunes the smallest YOLO-seg checkpoint (yolo11n-seg, COCO-pretrained) on
the remapped 4-label Carparts-Seg set. This exists to answer ONE question:
does a detector trained on road-scene photographs fire at all on our clean
studio renders of an untextured generated mesh?

It is deliberately NOT a production training run. Read the numbers as
"does this transfer at all", never as "this is the accuracy achievable".
The dataset's own val split cannot be used to claim accuracy either — 290 of
its 295 source photos also appear in train (see CARPARTS_SEG.md), so val mAP
measures memorisation of the same 579 photographs.

Run: python3 carparts_train.py <data.yaml> <run_dir> [epochs] [imgsz]
"""
import os
import sys

os.environ.setdefault("OMP_NUM_THREADS", "4")

from ultralytics import YOLO  # noqa: E402

DATA = sys.argv[1]
RUN = sys.argv[2]
EPOCHS = int(sys.argv[3]) if len(sys.argv) > 3 else 12
IMGSZ = int(sys.argv[4]) if len(sys.argv) > 4 else 416

m = YOLO("yolo11n-seg.pt")
m.train(
    data=DATA, epochs=EPOCHS, imgsz=IMGSZ, batch=16, device="cpu",
    workers=2, project=RUN, name="probe", exist_ok=True,
    # the source images are ALREADY augmented (each of 579 photos ships ~5.5
    # baked rotations/flips/blurs), so piling more geometric augmentation on
    # top mostly wastes CPU. Keep flips, drop the heavy stuff.
    mosaic=0.0, mixup=0.0, copy_paste=0.0, degrees=0.0, scale=0.3,
    plots=False, val=True, patience=100, seed=0,
)
print("TRAIN_DONE")
