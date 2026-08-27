#!/usr/bin/env python3
"""seg_masks.py — text-prompted 2D segmentation of seg_views renders.

GroundingDINO-tiny proposes boxes for each class prompt; SAM (vit-base)
refines every box to a pixel mask; per-class masks are OR-combined and saved
as <view>_<class>.png (0/255). CPU-friendly: one SAM forward per view with
all boxes batched.

Run: python3 seg_masks.py <views_dir>
"""
import os, re, sys, json
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
# Thresholds are env-tunable: on a DARK car DINO under-fires on near-black
# windows at 0.25 (RF67 Golf 2026-08-27: glass labels came back 0.51% of area,
# 13 sliver components — the dark-car failure this file already documents for
# PAINT_REJECT). The lamp_boost pattern applies: re-detect lower, let the
# downstream zone priors and stencils police the extra boxes.
BOX_THR = float(os.environ.get("SEG_BOX_THR", "0.25"))
TEXT_THR = float(os.environ.get("SEG_TEXT_THR", "0.22"))

# --- PAINT REJECTION for the glass class (added 2026-08-26, van generality) ---
#
# WHY. On a Ford Transit Custom PANEL van, GroundingDINO's "car window" box
# covers the ENTIRE solid cargo flank — verified by overlaying the saved mask on
# the beauty render, not inferred. The box passes the 0.35-of-car-area filter
# because that band really is under a third of the car on screen, and SAM then
# happily segments a flat painted panel as a window. Downstream this glazed the
# cargo box: 23.6% of the finished van's glazing area sat in its rear third
# while the raw texture there is solid white paint. glass_probe, the area band
# gate and glass_topo all PASSED that van (see glass_where.py).
#
# THE DISCRIMINATOR, measured across all 10 van views: a real window in a
# photo-derived texture is DARK (interior behind it), painted metal is not.
#   9 of 10 views: 79-96% of the "glass" mask sat at >=0.85x the body's own
#                  median luminance  -> paint
#   view_04:       0.7%, glass median 57.8 against body 124.9 -> real glazing
# It is measured against the CAR'S OWN PAINT, not an absolute threshold, so it
# does not assume a light car.
#
# IT IS DELIBERATELY BIASED TOWARDS UNDER-STRIPPING. The two failure directions
# are not symmetric: leaving a cargo panel glazed makes a panel van look like a
# Tourneo, but stripping a real window makes the glazing OPAQUE, which is the
# owner's hard scrap (ruling 2026-08-11). So PAINT_FRAC is conservative, and on
# a dark car — where glass and paint are both dark and the test cannot separate
# them — it FAILS OPEN and changes nothing.
PAINT_FRAC = float(os.environ.get("SEG_PAINT_FRAC", "0.85"))
# Below this body luminance there is no contrast headroom to judge with.
PAINT_MIN_BODY_LUM = float(os.environ.get("SEG_PAINT_MIN_BODY", "60"))
# DEFAULT OFF, ON PURPOSE — the diagnosis is solid and the CALIBRATION is not.
# The only car this could be calibrated against today is the TRELLIS.2 van, and
# that van's glazing is genuinely SHREDDED: its windscreen component measures
# median luminance 196.8 against a body median of 179.0, i.e. brighter than the
# paint. Any threshold fitted here drops a real windscreen, which is the
# owner's hard scrap (opaque glazing, 2026-08-11) — the failure direction this
# rule is explicitly supposed to avoid. And the Yaris views that would serve as
# the must-NOT-strip control were lost to a container rollback.
#
# "A threshold with no positive control behind it is a guess" (CLAUDE.md).
# TO TURN IT ON, first settle both directions on a car with intact glazing:
#   1. must strip:     a panel van's cargo flank
#   2. must NOT strip: that same van's cabin windows AND windscreen
#   3. must NOT strip: a hatchback's full glazing (regenerate the Yaris views)
#   4. must fail open: a dark car, where paint and glass are both dark
# Then set SEG_PAINT_REJECT=1 and record which car calibrated it.
PAINT_REJECT = os.environ.get("SEG_PAINT_REJECT", "0") == "1"


def _lum(rgb):
    return rgb @ np.array([0.2126, 0.7152, 0.0722])


def reject_paint(mask, img_rgb, oncar):
    """Drop glass pixels as bright as the car's own paint. Returns (mask, note).

    The body reference deliberately does NOT subtract the wheel and lamp masks.
    CLASSES is iterated glass-first, so those files do not exist yet on a fresh
    run but DO exist from the previous run on a re-run — the reference would
    then differ between the two, which is exactly the kind of silent
    run-to-run inconsistency this repo has been burned by. Wheels and lamps are
    a few percent of on-car area and dark, so including them only pulls the
    median DOWN, i.e. strictly toward keeping more glass. Measured both ways on
    all 10 van views: the bright-share verdict is unchanged.
    """
    if not PAINT_REJECT or not mask.any():
        return mask, "skipped"
    lum = _lum(np.asarray(img_rgb).astype(float))
    body = oncar & ~mask
    if body.sum() < 500:
        return mask, "no body reference"
    bmed = float(np.median(lum[body]))
    if bmed < PAINT_MIN_BODY_LUM:
        # dark car: glazing and paint are both dark, the test cannot separate
        # them, and guessing here would risk an opaque-glazing scrap.
        return mask, f"fail-open (body lum {bmed:.0f} < {PAINT_MIN_BODY_LUM})"
    keep = mask & (lum < PAINT_FRAC * bmed)
    dropped = int(mask.sum() - keep.sum())
    return keep, (f"body lum {bmed:.0f}, dropped {dropped} of {int(mask.sum())} "
                  f"px ({100*dropped/max(1,mask.sum()):.0f}%) as paint")

dp = AutoProcessor.from_pretrained("IDEA-Research/grounding-dino-tiny")
dm = AutoModelForZeroShotObjectDetection.from_pretrained("IDEA-Research/grounding-dino-tiny").eval()
sp = SamProcessor.from_pretrained("facebook/sam-vit-base")
sm = SamModel.from_pretrained("facebook/sam-vit-base").eval()

report = {}
for fn in sorted(os.listdir(VIEWS)):
    # STRICT view filename match. This stage writes its own outputs
    # (view_NN_glass.png etc.) into the same directory, so the loose
    # startswith/endswith filter made a RE-RUN consume its previous outputs
    # as views and die on KeyError('view_00_glass') (2026-08-27).
    if not re.fullmatch(r"view_\d+\.png", fn):
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
        if cls == "glass":
            mask, note = reject_paint(mask, img, oncar)
            print(f"    glass paint-reject: {note}", flush=True)
        Image.fromarray((mask * 255).astype(np.uint8)).save(
            os.path.join(VIEWS, fn.replace(".png", f"_{cls}.png")))
        view_stats[cls] = {"boxes": len(boxes), "px": int(mask.sum())}
    report[fn] = view_stats
    print(fn, view_stats, flush=True)
json.dump(report, open(os.path.join(VIEWS, "seg_report.json"), "w"), indent=1)
print("SEG_MASKS_DONE")
