"""RunPod serverless handler — Hunyuan3D-2.1 image->3D (shape + PBR texture).
Mirrors trellis/handler.py I/O: {image_b64|image_url, seed?, texture?:bool}
-> {glb_url} via Supabase upload (same env vars as the TRELLIS worker).
VRAM: ~10GB shape-only, ~29GB with texture -> run texture=True only on 48GB pool.
"""
import base64, os, sys, time, uuid
from io import BytesIO

import requests, runpod, torch
from PIL import Image

sys.path.insert(0, "/app/Hunyuan3D-2.1/hy3dshape")
sys.path.insert(0, "/app/Hunyuan3D-2.1/hy3dpaint")
os.chdir("/app/Hunyuan3D-2.1")

try:
    from torchvision_fix import apply_fix
    apply_fix()
except Exception as e:
    print("torchvision_fix skipped:", e)

from hy3dshape.rembg import BackgroundRemover
from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline

MODEL = "tencent/Hunyuan3D-2.1"
OUT = "/runpod-volume/outputs"
os.makedirs(OUT, exist_ok=True)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
BUCKET = os.environ.get("SUPABASE_BUCKET", "car-meshes")

print("loading shape pipeline...", flush=True)
shape_pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(MODEL)
rembg = BackgroundRemover()
paint_pipe = None  # lazy — 21GB extra


def get_paint():
    global paint_pipe
    if paint_pipe is None:
        from textureGenPipeline import Hunyuan3DPaintPipeline, Hunyuan3DPaintConfig
        conf = Hunyuan3DPaintConfig(max_num_view=6, resolution=512)
        conf.realesrgan_ckpt_path = "hy3dpaint/ckpt/RealESRGAN_x4plus.pth"
        conf.multiview_cfg_path = "hy3dpaint/cfgs/hunyuan-paint-pbr.yaml"
        conf.custom_pipeline = "hy3dpaint/hunyuanpaintpbr"
        paint_pipe = Hunyuan3DPaintPipeline(conf)
    return paint_pipe


def upload(local, dest):
    if not (SUPABASE_URL and SUPABASE_KEY):
        return None
    with open(local, "rb") as f:
        data = f.read()
    r = requests.post(
        f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{dest}",
        data=data,
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
                 "Content-Type": "model/gltf-binary", "x-upsert": "true"},
        timeout=300)
    if r.status_code in (200, 201):
        return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{dest}"
    print("upload failed", r.status_code, r.text[:150], flush=True)
    return None


def handler(job):
    inp = job.get("input", {}) or {}
    t0 = time.time()
    if inp.get("image_b64"):
        img = Image.open(BytesIO(base64.b64decode(inp["image_b64"])))
    elif inp.get("image_url"):
        img = Image.open(BytesIO(requests.get(inp["image_url"], timeout=120).content))
    else:
        return {"error": "need image_b64 or image_url"}
    # Always re-run background removal on the flattened photo (unless the
    # caller opts out): incoming alpha cannot be trusted — a soft matte leaves
    # a ghost of the scene after the white composite and the model builds it
    # as a billboard wall (measured: 61% of pixels at partial alpha on smoke
    # test 2). Tencent's remover paints the background white (bgcolor
    # 255,255,255,0), which is what the shape pipeline expects.
    if inp.get("remove_bg", True):
        img = rembg(img.convert("RGB"))
    else:
        img = img.convert("RGBA")
    # u2net mattes can leave most of the background at partial alpha; the
    # pipeline's white composite then keeps a scene ghost that the model
    # reconstructs as a billboard wall (observed twice on the Golf photo).
    # Binarise alpha and force white under transparent pixels.
    import numpy as np
    a = np.array(img)
    hard = (a[..., 3] >= 128)
    a[..., 3] = np.where(hard, 255, 0).astype(a.dtype)
    a[~hard, :3] = 255
    img = Image.fromarray(a)

    seed = int(inp.get("seed", 0))
    torch.manual_seed(seed)
    mesh = shape_pipe(image=img)[0]
    uid = str(uuid.uuid4())
    raw = f"{OUT}/{uid}.glb"
    mesh.export(raw)
    out_path = raw
    tex_err = None

    if inp.get("texture", True):
        try:
            src_png = f"{OUT}/{uid}.png"
            img.save(src_png)
            out_path = get_paint()(mesh_path=raw, image_path=src_png,
                                   output_mesh_path=f"{OUT}/{uid}_tex.glb")
        except Exception as e:
            tex_err = f"{type(e).__name__}: {e}"
            print("texture stage failed, returning shape-only:", e, flush=True)
            out_path = raw

    url = upload(out_path, f"hunyuan21/{os.path.basename(out_path)}")
    return {"glb_url": url, "seconds": round(time.time() - t0, 1),
            "textured": out_path != raw, "seed": seed, "texture_error": tex_err}


runpod.serverless.start({"handler": handler})
