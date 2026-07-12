"""
RunPod serverless handler for SAM 3D Body (DINOv3 checkpoint).

Takes a base64 image, runs real inference, returns per-person 3D vertices,
keypoints, and shape params as JSON.
"""

import os
import base64
import tempfile

import cv2
import numpy as np
import runpod
from huggingface_hub import login

HF_TOKEN = os.environ.get("HF_TOKEN")
if HF_TOKEN:
    login(token=HF_TOKEN)
else:
    print("WARNING: HF_TOKEN not set — downloading the gated checkpoint will fail.")

# Imported after login so gated weights resolve.
from notebook.utils import setup_sam_3d_body  # noqa: E402

print("Loading SAM 3D Body ... first cold start can take a few minutes.")
estimator = setup_sam_3d_body(hf_repo_id="facebook/sam-3d-body-dinov3")
print("Model loaded and ready.")


def _to_list(x):
    if hasattr(x, "detach"):
        x = x.detach().cpu().numpy()
    if isinstance(x, np.ndarray):
        return x.tolist()
    return x


def handler(event):
    inp = event.get("input", {})
    img_b64 = inp.get("image_base64")
    if not img_b64:
        return {"error": "Missing 'image_base64' in input."}

    try:
        img_bytes = base64.b64decode(img_b64)
    except Exception as e:
        return {"error": f"Could not decode base64 image: {e}"}

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=True) as f:
        f.write(img_bytes)
        f.flush()
        img_bgr = cv2.imread(f.name)

    if img_bgr is None:
        return {"error": "Could not decode image bytes into a valid image."}

    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    outputs = estimator.process_one_image(img_rgb)

    people = []
    for person in outputs:
        people.append({
            "pred_vertices": _to_list(person.get("pred_vertices")),
            "pred_keypoints_3d": _to_list(person.get("pred_keypoints_3d")),
            "shape_params": _to_list(person.get("shape_params")),
            "pred_cam_t": _to_list(person.get("pred_cam_t")),
        })

    return {"num_people_detected": len(people), "people": people}


runpod.serverless.start({"handler": handler})
