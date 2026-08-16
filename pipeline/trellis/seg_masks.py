#!/usr/bin/env python3
"""seg_masks.py — text-prompted 2D segmentation of seg_views renders.

GroundingDINO-tiny proposes boxes for each class prompt; SAM (vit-base)
refines every box to a pixel mask; per-class masks are OR-combined and saved
as <view>_<class>.png (0/255). CPU-friendly: one SAM forward per view with
all boxes batched.

Run: python3 seg_masks.py <views_dir>
"""
import os, sys, json
import numpy as np
import torch
import OpenEXR, Imath
from PIL import Image
from transformers import (AutoProcessor, AutoModelForZeroShotObjectDetection,
                          SamModel, SamProcessor)

VIEWS = sys.argv[1]

def car_mask(vname):
    """On-car pixel mask from the Blender depth pass — the exact car
    silhouette, free. Boxes and masks are filtered against IT, not the image:
    a whole-car box is only ~18%% of the frame and sails through an
    image-relative filter (measured: every class mask became the car)."""
    cams = json.load(open(os.path.join(VIEWS, "cameras.json")))
    fp = os.path.join(VIEWS, cams[vname]["depth_exr"])
    ex = OpenEXR.InputFile(fp); hdr = ex.header(); dw = hdr["dataWindow"]
    W = dw.max.x - dw.min.x + 1; H = dw.max.y - dw.min.y + 1
    ch = "R" if "R" in hdr["channels"] else list(hdr["channels"])[0]
    d = np.frombuffer(ex.channel(ch, Imath.PixelType(Imath.PixelType.FLOAT)),
                      dtype=np.float32).reshape(H, W)
    return d < 1e9
CLASSES = {
    "glass": ["car window", "windshield"],
    "wheel": ["wheel", "tire"],
    "lamp":  ["headlight", "tail light"],
}
BOX_THR, TEXT_THR = 0.25, 0.22

dp = AutoProcessor.from_pretrained("IDEA-Research/grounding-dino-tiny")
dm = AutoModelForZeroShotObjectDetection.from_pretrained("IDEA-Research/grounding-dino-tiny").eval()
sp = SamProcessor.from_pretrained("facebook/sam-vit-base")
sm = SamModel.from_pretrained("facebook/sam-vit-base").eval()

report = {}
for fn in sorted(os.listdir(VIEWS)):
    if not (fn.startswith("view_") and fn.endswith(".png")):
        continue
    img = Image.open(os.path.join(VIEWS, fn)).convert("RGB")
    W, H = img.size
    oncar = car_mask(fn[:-4])
    car_area = int(oncar.sum())
    view_stats = {}
    for cls, prompts in CLASSES.items():
        boxes = []
        for prompt in prompts:
            inp = dp(images=img, text=f"{prompt}.", return_tensors="pt")
            with torch.no_grad():
                out = dm(**inp)
            res = dp.post_process_grounded_object_detection(
                out, inp.input_ids, threshold=BOX_THR, text_threshold=TEXT_THR,
                target_sizes=[(H, W)])[0]
            for b, s in zip(res["boxes"], res["scores"]):
                b = b.tolist()
                # discard boxes that cover a large share of the CAR itself
                if (b[2]-b[0]) * (b[3]-b[1]) > 0.35 * car_area:
                    continue
                boxes.append(b)
        mask = np.zeros((H, W), bool)
        if boxes:
            sinp = sp(img, input_boxes=[boxes], return_tensors="pt")
            with torch.no_grad():
                sout = sm(**sinp)
            masks = sp.image_processor.post_process_masks(
                sout.pred_masks.cpu(), sinp["original_sizes"].cpu(),
                sinp["reshaped_input_sizes"].cpu())[0]     # [N,3,H,W]
            scores = sout.iou_scores.cpu()[0]              # [N,3]
            for i in range(masks.shape[0]):
                x0, y0, x1, y1 = [int(v) for v in boxes[i]]
                box_area = max(1, (x1 - x0) * (y1 - y0))
                cand = sorted(range(masks.shape[1]),
                              key=lambda k: -float(scores[i][k]))
                pick = None
                for k in cand:      # best score whose area plausibly fits the box
                    mk = masks[i, k].numpy().astype(bool)
                    if mk.sum() <= 1.5 * box_area:
                        pick = mk; break
                if pick is None:    # all leaked -> smallest
                    pick = masks[i, int(np.argmin([masks[i, k].sum() for k in range(masks.shape[1])]))].numpy().astype(bool)
                clip = np.zeros_like(pick); clip[y0:y1, x0:x1] = True
                mask |= pick & clip
        mask &= oncar
        Image.fromarray((mask * 255).astype(np.uint8)).save(
            os.path.join(VIEWS, fn.replace(".png", f"_{cls}.png")))
        view_stats[cls] = {"boxes": len(boxes), "px": int(mask.sum())}
    report[fn] = view_stats
    print(fn, view_stats, flush=True)
json.dump(report, open(os.path.join(VIEWS, "seg_report.json"), "w"), indent=1)
print("SEG_MASKS_DONE")
