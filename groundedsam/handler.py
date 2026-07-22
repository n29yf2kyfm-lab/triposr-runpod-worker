"""Grounded-SAM RunPod worker — 2D car-part segmentation for the TRELLIS
material-split pipeline.

Input  (event["input"]):
  images_b64 : list[str]   PNG/JPEG base64 of rendered views of a car
  prompt     : str         optional Grounding DINO text prompt
  box_threshold, text_threshold : float (optional)

Output:
  masks_b64  : list[str]   one PNG per input image, single-channel class map:
                 0 = background/body, 2 = glass, 3 = wheel, 4 = light
               (values match the segmenter's face-label convention so the
                back-projection step can vote them straight onto faces.)

The heavy 3D work (render, project, occlude, vote, assign materials) stays on
the CPU side in Blender; this worker is a pure image-in / masks-out service, so
it is reusable for any multi-view part-segmentation task.
"""
import runpod, torch, base64, io, numpy as np
from PIL import Image
from transformers import (AutoProcessor, AutoModelForZeroShotObjectDetection,
                          SamModel, SamProcessor)

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
GD_ID = "IDEA-Research/grounding-dino-base"
SAM_ID = "facebook/sam-vit-huge"

gd_proc = AutoProcessor.from_pretrained(GD_ID)
gd_model = AutoModelForZeroShotObjectDetection.from_pretrained(GD_ID).to(DEVICE).eval()
sam_proc = SamProcessor.from_pretrained(SAM_ID)
sam_model = SamModel.from_pretrained(SAM_ID).to(DEVICE).eval()

# text phrase -> class id. glass/wheel/light match the segmenter's labels.
CLASS_FOR = [
    ("windshield", 2), ("windscreen", 2), ("window", 2), ("glass", 2),
    ("wheel", 3), ("tyre", 3), ("tire", 3), ("rim", 3),
    ("headlight", 4), ("head light", 4), ("tail light", 4), ("taillight", 4),
]
# wheel (3) must win over glass (2) where they overlap (dark tyre vs dark glass),
# light (4) over body; paint order low->high priority:
PRIORITY = {2: 1, 4: 2, 3: 3}
DEFAULT_PROMPT = ("car windshield. car window. car wheel. car tyre. "
                  "headlight. tail light.")

def class_of(label):
    l = label.lower()
    for k, cid in CLASS_FOR:
        if k in l:
            return cid
    return 0

@torch.no_grad()
def segment(img, prompt, box_thr, text_thr):
    W, H = img.size
    inp = gd_proc(images=img, text=prompt, return_tensors="pt").to(DEVICE)
    out = gd_model(**inp)
    det = gd_proc.post_process_grounded_object_detection(
        out, inp.input_ids, box_threshold=box_thr, text_threshold=text_thr,
        target_sizes=[(H, W)])[0]
    boxes, labels = det["boxes"], det["labels"]
    cm = np.zeros((H, W), np.uint8)
    if len(boxes) == 0:
        return cm
    cids = [class_of(l) for l in labels]
    keep = [i for i, c in enumerate(cids) if c != 0]
    if not keep:
        return cm
    bx = [[boxes[i].tolist() for i in keep]]
    si = sam_proc(img, input_boxes=bx, return_tensors="pt").to(DEVICE)
    so = sam_model(**si)
    masks = sam_proc.image_processor.post_process_masks(
        so.pred_masks.cpu(), si["original_sizes"].cpu(),
        si["reshaped_input_sizes"].cpu())[0]        # [n, k, H, W]
    for j, i in enumerate(keep):
        cid = cids[i]
        m = masks[j]
        m = (m[0] if m.ndim == 3 else m).numpy() > 0.5
        # paint by priority so wheels beat glass on overlap
        cur = cm[m]
        cm[m] = np.where(
            (cur == 0) | (np.vectorize(lambda x: PRIORITY.get(x, 0))(cur) < PRIORITY.get(cid, 0)),
            cid, cur)
    return cm

def handler(event):
    inp = event.get("input", {})
    imgs = inp.get("images_b64", [])
    prompt = inp.get("prompt", DEFAULT_PROMPT)
    box_thr = float(inp.get("box_threshold", 0.28))
    text_thr = float(inp.get("text_threshold", 0.22))
    outs = []
    for b64 in imgs:
        img = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
        cm = segment(img, prompt, box_thr, text_thr)
        buf = io.BytesIO(); Image.fromarray(cm, mode="L").save(buf, "PNG")
        outs.append(base64.b64encode(buf.getvalue()).decode())
    return {"masks_b64": outs, "count": len(outs)}

runpod.serverless.start({"handler": handler})
