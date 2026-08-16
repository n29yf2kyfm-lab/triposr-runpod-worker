#!/usr/bin/env python3
"""lamp_boost.py — second-chance headlamp detection on the nose views.

Measured on the gseg Golf: DINO's "headlight" prompt at the default 0.25
threshold found ZERO boxes in both head-on nose views (the tail views got
13k px), so the headlamps labeled ~586 faces and rendered body-colour —
the exact "painted-over lights" defect the owner rejects. Generated cars
have soft lamp geometry, so the detector needs more prompts and a lower
bar. Extra detections elsewhere are safe: seg_project's lamp zone prior
(nose/tail only) and seg_boundary's centre-band eviction cull strays.

ORs the new masks into the existing <view>_lamp.png files, then the label
chain is re-run from seg_project.

Run: python3 lamp_boost.py <views_dir> <view_name> [<view_name> ...]
"""
import os
import sys
import numpy as np
import torch
import OpenEXR
import Imath
import json
from PIL import Image
from transformers import (AutoProcessor, AutoModelForZeroShotObjectDetection,
                          SamModel, SamProcessor)

VIEWS = sys.argv[1]
NAMES = sys.argv[2:]
PROMPTS = ["headlight", "head lamp", "front light of a car", "fog light"]
BOX_THR, TEXT_THR = 0.16, 0.14

def car_mask(vname):
    cams = json.load(open(os.path.join(VIEWS, "cameras.json")))
    fp = os.path.join(VIEWS, cams[vname]["depth_exr"])
    ex = OpenEXR.InputFile(fp); hdr = ex.header(); dw = hdr["dataWindow"]
    W = dw.max.x - dw.min.x + 1; H = dw.max.y - dw.min.y + 1
    ch = "R" if "R" in hdr["channels"] else list(hdr["channels"])[0]
    d = np.frombuffer(ex.channel(ch, Imath.PixelType(Imath.PixelType.FLOAT)),
                      dtype=np.float32).reshape(H, W)
    return d < 1e9

dp = AutoProcessor.from_pretrained("IDEA-Research/grounding-dino-tiny")
dm = AutoModelForZeroShotObjectDetection.from_pretrained(
    "IDEA-Research/grounding-dino-tiny").eval()
sp = SamProcessor.from_pretrained("facebook/sam-vit-base")
sm = SamModel.from_pretrained("facebook/sam-vit-base").eval()

for vname in NAMES:
    img = Image.open(os.path.join(VIEWS, f"{vname}.png")).convert("RGB")
    W, H = img.size
    oncar = car_mask(vname)
    car_area = int(oncar.sum())
    boxes = []
    for prompt in PROMPTS:
        inp = dp(images=img, text=f"{prompt}.", return_tensors="pt")
        with torch.no_grad():
            out = dm(**inp)
        res = dp.post_process_grounded_object_detection(
            out, inp.input_ids, threshold=BOX_THR, text_threshold=TEXT_THR,
            target_sizes=[(H, W)])[0]
        for b, s in zip(res["boxes"], res["scores"]):
            b = b.tolist()
            if (b[2]-b[0]) * (b[3]-b[1]) > 0.20 * car_area:   # a lamp is small
                continue
            boxes.append(b)
    mask = np.zeros((H, W), bool)
    if boxes:
        sinp = sp(img, input_boxes=[boxes], return_tensors="pt")
        with torch.no_grad():
            sout = sm(**sinp)
        masks = sp.image_processor.post_process_masks(
            sout.pred_masks.cpu(), sinp["original_sizes"].cpu(),
            sinp["reshaped_input_sizes"].cpu())[0]
        scores = sout.iou_scores.cpu()[0]
        for i in range(masks.shape[0]):
            x0, y0, x1, y1 = [int(v) for v in boxes[i]]
            box_area = max(1, (x1 - x0) * (y1 - y0))
            cand = sorted(range(masks.shape[1]), key=lambda k: -float(scores[i][k]))
            pick = None
            for k in cand:
                mk = masks[i, k].numpy().astype(bool)
                if mk.sum() <= 1.5 * box_area:
                    pick = mk; break
            if pick is None:
                pick = masks[i, int(np.argmin(
                    [masks[i, k].sum() for k in range(masks.shape[1])]))].numpy().astype(bool)
            clip = np.zeros_like(pick); clip[y0:y1, x0:x1] = True
            mask |= pick & clip
    mask &= oncar
    fp = os.path.join(VIEWS, f"{vname}_lamp.png")
    old = np.array(Image.open(fp)) > 127
    merged = old | mask
    Image.fromarray((merged * 255).astype(np.uint8)).save(fp)
    print(f"{vname}: boxes={len(boxes)} new_px={int(mask.sum())} "
          f"total_px={int(merged.sum())}")
print("LAMP_BOOST_DONE")
