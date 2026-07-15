import runpod
import torch
import requests
import base64
import os
import numpy as np
from io import BytesIO
from PIL import Image
import sys

# TRELLIS.2 repo is cloned to /app/TRELLIS.2 in the Dockerfile; its `trellis2`
# package is imported from there. The CUDA extension `o_voxel` is pip-installed.
sys.path.insert(0, "/app/TRELLIS.2")
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("SPCONV_ALGO", "native")
# TRELLIS.2 uses flash-attn by default; xformers is the fallback for GPUs
# without flash-attention support.
os.environ.setdefault("ATTN_BACKEND", "flash-attn")

import o_voxel
from trellis2.pipelines import Trellis2ImageTo3DPipeline

IMAGE_MODEL = "microsoft/TRELLIS.2-4B"

OUTPUT_DIR = "/runpod-volume/outputs"

# Optional Supabase Storage upload. When SUPABASE_URL + SUPABASE_KEY are set,
# the generated GLB is uploaded and a public URL is returned, so large meshes
# never hit RunPod's inline output-size cap (which silently drops the payload).
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "car-meshes")
# Only inline the base64 GLB when it is comfortably under RunPod's response cap.
INLINE_B64_MAX_BYTES = int(os.environ.get("INLINE_B64_MAX_BYTES", 1_300_000))


def upload_to_supabase(local_path, object_path):
    """Upload a file to Supabase Storage; return the public URL (or None)."""
    if not (SUPABASE_URL and SUPABASE_KEY):
        return None
    with open(local_path, "rb") as f:
        data = f.read()
    url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{object_path}"
    resp = requests.post(
        url,
        data=data,
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "model/gltf-binary",
            "x-upsert": "true",
        },
        timeout=120,
    )
    resp.raise_for_status()
    return (f"{SUPABASE_URL}/storage/v1/object/public/"
            f"{SUPABASE_BUCKET}/{object_path}")

_image_pipeline = None


def _patch_rembg_to_free_model():
    """Force the background-removal model to the ungated, MIT-licensed original.

    TRELLIS.2-4B's pipeline config builds its background-removal model EAGERLY in
    from_pretrained() (not lazily in preprocess_image), pinned to the gated,
    NON-COMMERCIAL briaai/RMBG-2.0. That 403s without a BRIA licence, and even
    with one its licence forbids a paid app. The BiRefNet wrapper's own default is
    ZhengPeng7/BiRefNet — the ungated, MIT-licensed model RMBG-2.0 is fine-tuned
    from, and TRELLIS.2's upstream-tested default. We repin __init__ to it so the
    pipeline builds with no gated download and on-worker preprocessing stays
    commercially usable for plain-RGB inputs.
    """
    try:
        import trellis2.pipelines.rembg as rembg_pkg
    except Exception:
        return
    cls = getattr(rembg_pkg, "BiRefNet", None)
    if cls is None or getattr(cls, "_free_patched", False):
        return
    _orig_init = cls.__init__

    def _init(self, *args, **kwargs):  # ignore the config's gated model_name
        _orig_init(self, "ZhengPeng7/BiRefNet")
        # ZhengPeng7/BiRefNet loads in half precision, but preprocess_image feeds
        # it a float32 image tensor -> "Input type (float) and bias type
        # (c10::Half) should be the same". Force the seg model to float32 so the
        # dtypes match (24GB has ample headroom for an fp32 BiRefNet).
        try:
            if getattr(self, "model", None) is not None:
                self.model = self.model.float()
        except Exception:
            pass

    cls.__init__ = _init
    cls._free_patched = True


def _patch_dinov3_extract_features():
    """Make the DINOv3 image encoder robust to the installed transformers version.

    TRELLIS.2 hand-walks the encoder: it reads self.model.embeddings /
    .rope_embeddings / .layer and runs each block manually. Current transformers
    kept embeddings/rope_embeddings on DINOv3ViTModel but moved the transformer
    blocks into an inner encoder, so self.model.layer no longer exists and the run
    dies with "'DINOv3ViTModel' object has no attribute 'layer'".

    Replace extract_features with the model's canonical forward
    (output_hidden_states=True). The last hidden state is the pre-final-norm
    output — exactly what TRELLIS's manual loop produced — so the weightless
    layer_norm they apply on top is unchanged. Version-proof, same maths.
    """
    try:
        import torch.nn.functional as F
        from trellis2.modules import image_feature_extractor as ife
    except Exception:
        return

    def extract_features(self, image):
        image = image.to(next(self.model.parameters()).dtype)
        outputs = self.model(pixel_values=image, output_hidden_states=True)
        hidden_states = outputs.hidden_states[-1]
        return F.layer_norm(hidden_states, hidden_states.shape[-1:])

    for name in dir(ife):
        cls = getattr(ife, name)
        if (isinstance(cls, type) and "dino" in name.lower()
                and hasattr(cls, "extract_features")
                and not getattr(cls, "_fwd_patched", False)):
            cls.extract_features = extract_features
            cls._fwd_patched = True


def get_image_pipeline():
    global _image_pipeline
    if _image_pipeline is None:
        _patch_rembg_to_free_model()
        _patch_dinov3_extract_features()
        _image_pipeline = Trellis2ImageTo3DPipeline.from_pretrained(IMAGE_MODEL)
        _image_pipeline.cuda()
    return _image_pipeline


def _load_image(data_or_bytes):
    """Load an image PRESERVING its alpha channel.

    The background-removal model is repinned to the free, MIT-licensed
    ZhengPeng7/BiRefNet (see _patch_rembg_to_free_model), so preprocessing works
    for plain RGB inputs too. On top of that, when the caller already sends a
    background-removed cutout (RGBA with a real alpha mask) we keep the alpha and
    signal "skip preprocessing", avoiding a redundant second segmentation pass.
    """
    img = Image.open(BytesIO(data_or_bytes))
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
    else:
        img = img.convert("RGB")
    return img


def _has_cutout_alpha(img):
    """True if the image carries a usable transparency mask (a real cutout)."""
    if img.mode != "RGBA":
        return False
    alpha = np.asarray(img)[:, :, 3]
    return bool(alpha.min() < 250)  # some pixels transparent -> it's a cutout


def fetch_image(image_url):
    """Fetch image from URL with browser-like headers, keeping any alpha."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TRELLIS-Worker/1.0)",
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
    }
    response = requests.get(image_url, headers=headers, timeout=30)
    response.raise_for_status()
    return _load_image(response.content)


def handler(job):
    job_input = job.get("input", {})
    job_id = job.get("id", "unknown")

    prompt = job_input.get("prompt", "")
    image_url = job_input.get("image_url", "")
    image_b64 = job_input.get("image_b64", "")
    images_b64 = job_input.get("images_b64") or []   # multi-view (Alam 3D)
    seed = job_input.get("seed", 1)
    # Mesh knobs (safe defaults tuned for car assets served to a web viewer).
    decimation_target = int(job_input.get("decimation_target", 500000))
    texture_size = int(job_input.get("texture_size", 2048))
    # Quality knobs surfaced from Trellis2ImageTo3DPipeline.run() (Alam 3D
    # upgrade): 1536 cascade auto-degrades resolution under VRAM pressure via
    # max_num_tokens, so it is safe to request on 24GB workers.
    pipeline_type = job_input.get("pipeline_type", "1536_cascade")
    num_samples = int(job_input.get("num_samples", 1))

    if not image_url and not image_b64 and not images_b64:
        # TRELLIS.2-4B is image-to-3D. A prompt with no image is a client error.
        return {
            "error": "TRELLIS.2 is image-to-3D: provide image_url or image_b64"
                     + (" (prompt received but not supported here)" if prompt else "")
        }

    try:
        if images_b64:
            imgs = [_load_image(base64.b64decode(b)) for b in images_b64]
            img = imgs[0]
        elif image_b64:
            imgs = None
            img = _load_image(base64.b64decode(image_b64))
        else:
            imgs = None
            img = fetch_image(image_url)

        # A real cutout (RGBA with transparency) skips the on-worker background
        # removal; plain RGB is background-removed by the free BiRefNet.
        skip_preprocess = _has_cutout_alpha(img)

        pipeline = get_image_pipeline()
        if imgs and len(imgs) > 1:
            from alam3d_multiview import run_multi_image
            meshes = run_multi_image(
                pipeline, imgs, seed=seed,
                preprocess_image=not all(_has_cutout_alpha(i) for i in imgs),
                pipeline_type=pipeline_type, num_samples=num_samples)
            mesh = max(meshes, key=lambda m: len(m.faces)) if len(meshes) > 1 else meshes[0]
        else:
            try:
                meshes = pipeline.run(
                    img, seed=seed, preprocess_image=not skip_preprocess,
                    pipeline_type=pipeline_type, num_samples=num_samples,
                )
                # best-of-N: keep the sample with the most faces (densest recon)
                mesh = max(meshes, key=lambda m: len(m.faces)) if len(meshes) > 1 else meshes[0]
            except TypeError:
                torch.manual_seed(seed)
                mesh = pipeline.run(img)[0]

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        persisted_path = os.path.join(OUTPUT_DIR, f"{job_id}.glb")

        # O-Voxel -> GLB with PBR (Base Color / Roughness / Metallic / Opacity).
        # remesh=True closes surface holes (the black-gap artifacts of v1) and
        # produces watertight-ish topology; PNG textures (extension_webp=False)
        # keep the GLB compatible with every downstream loader (Blender, web).
        glb = o_voxel.postprocess.to_glb(
            vertices=mesh.vertices,
            faces=mesh.faces,
            attr_volume=mesh.attrs,
            coords=mesh.coords,
            attr_layout=mesh.layout,
            voxel_size=mesh.voxel_size,
            aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
            decimation_target=decimation_target,
            texture_size=texture_size,
            remesh=True,
            remesh_band=1,
            remesh_project=0,
            verbose=True,
        )
        glb.export(persisted_path, extension_webp=False)

        glb_bytes = os.path.getsize(persisted_path)

        # Prefer a Supabase URL (no size cap); fall back to inline base64 only
        # when the GLB is small enough to survive RunPod's response-size limit.
        glb_url = None
        upload_error = None
        try:
            glb_url = upload_to_supabase(persisted_path, f"trellis/{job_id}.glb")
        except Exception as up_err:
            upload_error = str(up_err)

        glb_b64 = None
        if glb_url is None and glb_bytes <= INLINE_B64_MAX_BYTES:
            with open(persisted_path, "rb") as f:
                glb_b64 = base64.b64encode(f.read()).decode("utf-8")

        result = {
            "status": "success",
            "glb_url": glb_url,
            "glb_b64": glb_b64,
            "glb_path": persisted_path,
            "glb_bytes": glb_bytes,
            "mode": "image",
            "model": IMAGE_MODEL,
            "message": "GLB generated successfully",
        }
        if upload_error:
            result["upload_error"] = upload_error
        if glb_url is None and glb_b64 is None:
            result["warning"] = (
                f"GLB is {glb_bytes} bytes: too large to inline and no Supabase "
                "upload configured. Set SUPABASE_URL/SUPABASE_KEY or lower "
                "texture_size/decimation_target."
            )
        return result

    except Exception as e:
        import traceback
        return {
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


runpod.serverless.start({"handler": handler})
