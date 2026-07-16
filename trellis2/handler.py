import runpod
import torch
import requests
import base64
import os
from io import BytesIO
from PIL import Image
import sys

# Match the environment example.py sets before importing cv2/torch.
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("ATTN_BACKEND", "flash-attn")

# OFFLINE=1 forbids ALL model downloads at request time — every weight must
# already be in HF_HOME (see preload_models.py). Any cache miss then fails
# fast with a clear "offline mode" error instead of hanging on a download.
if os.environ.get("OFFLINE") == "1":
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

sys.path.insert(0, "/app/TRELLIS.2")

from trellis2.pipelines import Trellis2ImageTo3DPipeline
import o_voxel

# TRELLIS.2 itself is image-to-3D only, so text-to-3D is a two-stage pipeline
# owned by this worker:
#   text --(diffusion T2I)--> image --(TRELLIS.2)--> model --> trim --> colour
# The T2I stage renders the prompt as a single centered object on a plain
# background (TRELLIS.2's own preprocessing then segments it), and the 3D stage
# makes the mesh, trims it (remesh + decimation) and colours it (baked PBR
# textures: basecolor/roughness/metallic/opacity).
IMAGE_MODEL = "microsoft/TRELLIS.2-4B"

# SDXL base by default: permissive OpenRAIL++ license, solid single-object
# renders. Swap via env without a rebuild, e.g.:
#   T2I_MODEL=stabilityai/sdxl-turbo        (much faster, research license)
#   T2I_MODEL=black-forest-labs/FLUX.1-schnell (Apache-2.0, needs more VRAM)
T2I_MODEL = os.environ.get("T2I_MODEL", "stabilityai/stable-diffusion-xl-base-1.0")

# Optional LoRA adapter for the T2I stage. This is the drop-in point for the
# planned car-specific fine-tune: once a LoRA is trained on real vehicle photos
# (so specs like "2019 Toyota Corolla SE" render factory-accurate), point this
# at its HF repo or a local/volume path — no code change, no rebuild.
T2I_LORA = os.environ.get("T2I_LORA", "")

# Prompt scaffolding that biases the T2I stage toward images TRELLIS.2 handles
# best: one full object, centered, no crop, uncluttered background.
T2I_PROMPT_SUFFIX = (
    ", single object, centered, full object in view, 3d asset style, "
    "plain studio background, soft even lighting, high detail"
)
T2I_NEGATIVE_PROMPT = (
    "cropped, out of frame, multiple objects, collage, text, watermark, "
    "busy background, scenery, people"
)

# GLB baking defaults — mirror upstream example.py. Both are per-request
# overridable: `decimation_target` = trim (target face count after remesh),
# `texture_size` = colour (baked PBR texture resolution).
DEFAULT_DECIMATION_TARGET = 1_000_000
DEFAULT_TEXTURE_SIZE = 4096
REMESH = True

OUTPUT_DIR = "/runpod-volume/outputs"

_pipeline = None
_t2i_pipeline = None


def get_pipeline():
    global _pipeline
    if _pipeline is None:
        _pipeline = Trellis2ImageTo3DPipeline.from_pretrained(IMAGE_MODEL)
        _pipeline.cuda()
    return _pipeline


def get_t2i_pipeline():
    global _t2i_pipeline
    if _t2i_pipeline is None:
        from diffusers import AutoPipelineForText2Image
        _t2i_pipeline = AutoPipelineForText2Image.from_pretrained(
            T2I_MODEL,
            torch_dtype=torch.float16,
            variant="fp16",
            use_safetensors=True,
        )
        if T2I_LORA:
            _t2i_pipeline.load_lora_weights(T2I_LORA)
        _t2i_pipeline.to("cuda")
    return _t2i_pipeline


def build_vehicle_prompt(vehicle):
    """Turn a structured vehicle spec into an engineered T2I prompt.

    This is the current answer to 'make the model know what the car looks
    like from a spec': a deterministic template that front-loads the exact
    identity (year make model trim) — which base SDXL renders reasonably for
    common vehicles — plus controlled view/condition details. Accuracy on
    rare trims is what the future car LoRA (T2I_LORA) will fix; the input
    contract here stays the same when it lands.
    """
    identity = " ".join(
        str(vehicle[k]) for k in ("year", "make", "model", "trim") if vehicle.get(k)
    )
    details = []
    if vehicle.get("color"):
        details.append(f"{vehicle['color']} paint")
    if vehicle.get("body_style"):
        details.append(vehicle["body_style"])
    details.append(vehicle.get("view", "three-quarter front view"))
    if vehicle.get("condition"):
        details.append(vehicle["condition"])
    if vehicle.get("extras"):
        details.append(str(vehicle["extras"]))
    return f"a {identity}, " + ", ".join(details) + ", factory-accurate proportions and design"


def text_to_image(prompt, seed, steps=None, guidance=None):
    """Stage 1 of text-to-3D: render the prompt to a single-object image."""
    pipe = get_t2i_pipeline()
    is_turbo = "turbo" in T2I_MODEL.lower() or "schnell" in T2I_MODEL.lower()
    if steps is None:
        steps = 4 if is_turbo else 30
    if guidance is None:
        guidance = 0.0 if is_turbo else 7.0
    generator = torch.Generator("cuda").manual_seed(seed)
    result = pipe(
        prompt=prompt + T2I_PROMPT_SUFFIX,
        negative_prompt=T2I_NEGATIVE_PROMPT if guidance > 1.0 else None,
        num_inference_steps=steps,
        guidance_scale=guidance,
        width=1024,
        height=1024,
        generator=generator,
    )
    return result.images[0]


def fetch_image(image_url):
    """Fetch an image from a URL with browser-like headers."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TRELLIS2-Worker/1.0)",
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
    }
    response = requests.get(image_url, headers=headers, timeout=30)
    response.raise_for_status()
    return Image.open(BytesIO(response.content)).convert("RGB")


def run_pipeline(pipeline, img, seed):
    """Run generation. Signature verified against the vendored pipeline:
    run(image, num_samples=1, seed=42, ...) -> List[MeshWithVoxel]."""
    return pipeline.run(img, seed=seed)[0]


def image_to_b64(img):
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def handler(job):
    job_input = job.get("input", {})
    job_id = job.get("id", "unknown")

    prompt = job_input.get("prompt", "")
    vehicle = job_input.get("vehicle")
    image_url = job_input.get("image_url", "")
    image_b64 = job_input.get("image_b64", "")
    seed = int(job_input.get("seed", 1))
    # A structured vehicle spec takes precedence over a free-text prompt.
    if vehicle:
        prompt = build_vehicle_prompt(vehicle)
    # trim + colour knobs
    decimation_target = int(job_input.get("decimation_target", DEFAULT_DECIMATION_TARGET))
    texture_size = int(job_input.get("texture_size", DEFAULT_TEXTURE_SIZE))
    # optional T2I knobs
    t2i_steps = job_input.get("t2i_steps")
    t2i_guidance = job_input.get("t2i_guidance")

    if not prompt and not image_url and not image_b64:
        return {
            "error": "Provide prompt or vehicle spec (text-to-3D via built-in "
                     "text-to-image), or image_url / image_b64 (image-to-3D)."
        }

    try:
        generated_image_b64 = None

        # --- Stage 1: get the input image (supplied, or generated from text) ---
        if image_b64:
            img_data = base64.b64decode(image_b64)
            img = Image.open(BytesIO(img_data)).convert("RGB")
            mode = "image"
        elif image_url:
            img = fetch_image(image_url)
            mode = "image"
        else:
            with torch.no_grad():
                img = text_to_image(prompt, seed, t2i_steps, t2i_guidance)
            # return the intermediate image so callers can see/reuse it
            generated_image_b64 = image_to_b64(img)
            mode = "text"

        # --- Stage 2: make model ---
        pipeline = get_pipeline()
        with torch.no_grad():
            mesh = run_pipeline(pipeline, img, seed)

        # --- Stage 3: trim (remesh + decimate) and colour (bake PBR) -> GLB ---
        # Signature verified against vendored o_voxel/postprocess.py and
        # example.py — aabb is REQUIRED (no default); values match upstream.
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
            remesh=REMESH,
            remesh_band=1,
            remesh_project=0,
        )

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        persisted_path = os.path.join(OUTPUT_DIR, f"{job_id}.glb")
        # extension_webp=True stores textures as WebP inside the GLB — much
        # smaller PBR maps, as in upstream example.py.
        glb.export(persisted_path, extension_webp=True)

        with open(persisted_path, "rb") as f:
            glb_b64 = base64.b64encode(f.read()).decode("utf-8")

        result = {
            "status": "success",
            "glb_b64": glb_b64,
            "glb_path": persisted_path,
            "mode": mode,
            "message": "GLB generated successfully",
        }
        if generated_image_b64:
            result["generated_image_b64"] = generated_image_b64
            # echo the engineered prompt so callers can see/tune what the
            # vehicle spec expanded to
            result["prompt_used"] = prompt
        return result

    except Exception as e:
        import traceback
        return {
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


runpod.serverless.start({"handler": handler})
