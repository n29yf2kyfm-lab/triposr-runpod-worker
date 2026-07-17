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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from trellis2.pipelines import Trellis2ImageTo3DPipeline
import o_voxel
from oem_paint import apply_oem_paint
from wheel_swap import apply_wheel_swap
from normal_detail import apply_panel_detail
from polish import apply_polish

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
    ", exactly one single vehicle, one single view, whole subject centered "
    "and fully in frame, photorealistic dslr photograph, natural daylight, "
    "eye-level view, high detail"
)
# "multiple views/three-view/blueprint" guards added after a live run where
# SDXL drew a 3-view spec-sheet collage and the 3D stage faithfully built
# all three overlapping cars.
T2I_NEGATIVE_PROMPT = (
    "multiple views, three-view, blueprint, spec sheet, collage, grid, "
    "multiple objects, cropped, out of frame, text, watermark, toy, "
    "miniature, render, cartoon, people"
)

# GLB baking defaults — mirror upstream example.py. Both are per-request
# overridable: `decimation_target` = trim (target face count after remesh),
# `texture_size` = colour (baked PBR texture resolution).
DEFAULT_DECIMATION_TARGET = 1_000_000
DEFAULT_TEXTURE_SIZE = 4096
REMESH = True

OUTPUT_DIR = "/runpod-volume/outputs"

# Delivery: RunPod drops job outputs that exceed its response-size cap
# (live-confirmed: attempt 8 COMPLETED with a multi-MB GLB and the platform
# returned output=None). So the primary delivery is an upload to Supabase
# storage (same pattern/bucket as the production worker); inline base64 is
# included only when the file is small enough to survive the cap.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "")
MAX_INLINE_BYTES = 4_000_000  # raw bytes; ~5.3MB as base64, safely under the cap


def upload_to_supabase(path, object_name, content_type):
    """Upload a file to Supabase storage; returns its public URL or None."""
    if not (SUPABASE_URL and SUPABASE_KEY and SUPABASE_BUCKET):
        return None
    try:
        with open(path, "rb") as f:
            data = f.read()
        r = requests.post(
            f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{object_name}",
            data=data,
            headers={
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "apikey": SUPABASE_KEY,
                "Content-Type": content_type,
                "x-upsert": "true",
            },
            timeout=180,
        )
        if r.status_code in (200, 201):
            return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{object_name}"
        print(f"supabase upload failed: {r.status_code} {r.text[:200]}", file=sys.stderr)
    except Exception as e:
        print(f"supabase upload error: {e}", file=sys.stderr)
    return None

_pipeline = None
_t2i_pipeline = None


def finalize_glass(glb_path):
    """Post-export glass enable: if the baked baseColor texture carries real
    translucency (TRELLIS.2 generates window-glass alpha), flip the GLB's
    materials to alphaMode=BLEND — and BOOST the glass so the modeled
    interior (dashboard, seats, wheel) is actually visible: the baked alpha
    sits around 60-80% opaque, which renders as near-black windows
    (user-confirmed on the Golf), so the translucent band is remapped to
    ~60-85% transparent and its tint lifted. Upstream o-voxel hardcodes
    OPAQUE; an in-pipeline gate missed on its first live run, so this
    operates on the FINAL file. Disable with GLB_ALPHA_MODE=opaque.
    Returns True if transparency was enabled."""
    if os.environ.get("GLB_ALPHA_MODE", "auto").lower() == "opaque":
        return False
    try:
        from wheel_swap import _read_glb, _write_glb
        from oem_paint import _tex_source
        j, jtype, bin_data = _read_glb(glb_path)
        mats = j.get("materials") or []
        if not mats:
            return False
        tex_ref = (mats[0].get("pbrMetallicRoughness", {})
                   .get("baseColorTexture") or {}).get("index")
        if tex_ref is None:
            return False
        img_idx = _tex_source(j["textures"][tex_ref])
        bv = j["bufferViews"][j["images"][img_idx]["bufferView"]]
        off = bv.get("byteOffset", 0)
        im = Image.open(BytesIO(bytes(bin_data[off:off + bv["byteLength"]])))
        if im.mode != "RGBA":
            print("glass check: texture has no alpha channel", file=sys.stderr)
            return False
        hist = im.getchannel("A").histogram()
        frac = sum(hist[:250]) / float(im.size[0] * im.size[1])
        print(f"glass check: translucent fraction={frac:.4f}", file=sys.stderr)
        if frac < 0.002:
            return False
        if frac > 0.25:
            # windows are a small share of a car's surface; body-wide
            # translucency means bad segmentation, not glass — forcing BLEND
            # would ghost the whole model (live-confirmed failure mode)
            print("glass check: translucency too widespread, keeping OPAQUE",
                  file=sys.stderr)
            return False
        # interior-reveal boost on the translucent band only
        import numpy as _np
        arr = _np.asarray(im).astype(_np.float64)
        a = arr[..., 3]
        band = (a >= 30) & (a < 210)
        if band.any():
            arr[..., 3] = _np.where(
                band, _np.clip(30 + (a - 30) * 0.32, 30, 88), a)
            arr[..., :3] = _np.where(
                band[..., None], _np.clip(arr[..., :3] * 1.9 + 26, 0, 255),
                arr[..., :3])
            buf = BytesIO()
            mime = j["images"][img_idx].get("mimeType", "image/webp")
            Image.fromarray(arr.astype(_np.uint8)).save(
                buf, "WEBP" if "webp" in mime else "PNG", quality=95)
            blob = buf.getvalue()
            while len(bin_data) % 4:
                bin_data.append(0)
            start = len(bin_data)
            bin_data.extend(blob)
            j["bufferViews"].append({"buffer": 0, "byteOffset": start,
                                     "byteLength": len(blob)})
            j["images"][img_idx]["bufferView"] = len(j["bufferViews"]) - 1
        for m in mats:
            m["alphaMode"] = "BLEND"
            m["doubleSided"] = True
        _write_glb(glb_path, j, jtype, bin_data)
        return True
    except Exception as e:
        print(f"glass check skipped: {e}", file=sys.stderr)
        return False


# Background removal checkpoint override — handled inside our vendored
# pipeline (trellis2_image_to_3d.py reads REMBG_MODEL). pipeline.json pins the
# license-gated briaai/RMBG-2.0 (verified 403 in live deploy); setting
# REMBG_MODEL=ZhengPeng7/BiRefNet uses the public equivalent, no rebuild.


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
        # fp16 variant first (smaller download), fall back for checkpoints
        # that only publish full-precision weights (many finetunes do).
        try:
            _t2i_pipeline = AutoPipelineForText2Image.from_pretrained(
                T2I_MODEL, torch_dtype=torch.float16,
                variant="fp16", use_safetensors=True,
            )
        except Exception:
            _t2i_pipeline = AutoPipelineForText2Image.from_pretrained(
                T2I_MODEL, torch_dtype=torch.float16, use_safetensors=True,
            )
        if T2I_LORA:
            _t2i_pipeline.load_lora_weights(T2I_LORA)
        if os.environ.get("T2I_OFFLOAD") == "1":
            # big models (FLUX) can't stay resident next to TRELLIS.2 on a
            # 48GB card — stream weights from CPU per generation instead.
            _t2i_pipeline.enable_model_cpu_offload()
        else:
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
    name = T2I_MODEL.lower()
    is_lightning = "lightning" in name
    is_turbo = "turbo" in name or "schnell" in name
    if steps is None:
        steps = 6 if is_lightning else (4 if is_turbo else 30)
    if guidance is None:
        # lightning keeps guidance >1 so the negative prompt (anti-collage
        # guards) stays active; turbo/schnell are trained for cfg=0
        guidance = 1.5 if is_lightning else (0.0 if is_turbo else 7.0)
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


def run_pipeline(pipeline, img, seed, pipeline_type=None):
    """Run generation. Signature verified against the vendored pipeline:
    run(image, num_samples=1, seed=42, ..., pipeline_type=None) ->
    List[MeshWithVoxel]. pipeline_type: '512' | '1024' | '1024_cascade' |
    '1536_cascade' (default from the model's pipeline.json)."""
    if pipeline_type:
        return pipeline.run(img, seed=seed, pipeline_type=pipeline_type)[0]
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
    # A structured vehicle spec takes precedence over a free-text prompt.
    if vehicle:
        prompt = build_vehicle_prompt(vehicle)

    # Validate + clamp numeric knobs: a bad type returns a clear error instead
    # of a traceback, and extreme values can't OOM the worker (texture baking
    # at absurd resolutions / decimation targets was flagged in review).
    try:
        seed = int(job_input.get("seed", 1))
        decimation_target = int(job_input.get("decimation_target", DEFAULT_DECIMATION_TARGET))
        texture_size = int(job_input.get("texture_size", DEFAULT_TEXTURE_SIZE))
        t2i_steps = job_input.get("t2i_steps")
        t2i_steps = None if t2i_steps is None else int(t2i_steps)
        t2i_guidance = job_input.get("t2i_guidance")
        t2i_guidance = None if t2i_guidance is None else float(t2i_guidance)
    except (TypeError, ValueError) as e:
        return {"error": f"Invalid numeric input: {e}. seed/decimation_target/"
                         f"texture_size/t2i_steps must be integers, t2i_guidance a number."}
    decimation_target = max(20_000, min(decimation_target, 2_000_000))
    texture_size = max(512, min(texture_size, 4096))
    if t2i_steps is not None:
        t2i_steps = max(1, min(t2i_steps, 100))
    # geometry detail tier — TRELLIS.2's pipeline_type ('1536_cascade' is the
    # premium setting: highest-res geometry, slower, more VRAM)
    pipeline_type = job_input.get("pipeline_type")
    if pipeline_type not in (None, "512", "1024", "1024_cascade", "1536_cascade"):
        return {"error": "pipeline_type must be one of 512, 1024, 1024_cascade, 1536_cascade"}

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
            # publish the image immediately via job progress — the app can
            # display it while the 3D stage is still generating
            try:
                runpod.serverless.progress_update(
                    job, {"stage": "image_ready",
                          "generated_image_b64": generated_image_b64})
            except Exception:
                pass

        # --- Stage 2: make model ---
        pipeline = get_pipeline()
        with torch.no_grad():
            mesh = run_pipeline(pipeline, img, seed, pipeline_type)

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
        # smaller PBR maps, as in upstream example.py. If the PIL/WebP
        # toolchain is broken, fall back to a plain export rather than losing
        # a finished model to a codec problem (live-hit on attempt 7).
        try:
            glb.export(persisted_path, extension_webp=True)
        except Exception:
            glb.export(persisted_path)

        glass_enabled = finalize_glass(persisted_path)
        # OEM paint stage: repaint the body to a factory colour (texture-space,
        # shading-preserving) — beats baked-in ambient every time
        paint_report = None
        if job_input.get("oem_paint"):
            paint_report = apply_oem_paint(persisted_path, job_input["oem_paint"])
        # Polish: crease-preserving normal smoothing (flattens wavy voxel
        # panels) + texture edge sharpening/paint de-blotch. Runs before
        # panel detail so the line extraction sees the crisper texture.
        polish_report = None
        pol = job_input.get("polish")
        if pol is None:
            pol = (mode == "text")
        if pol:
            polish_report = apply_polish(persisted_path, pol)
        # Panel detail: normal map derived from shut-line features in the
        # baked texture so gaps read as grooves. Same default policy as wheels.
        detail_report = None
        pd = job_input.get("panel_detail")
        if pd is None:
            pd = (mode == "text")
        if pd:
            detail_report = apply_panel_detail(persisted_path, pd)
        # Wheel swap: overlay clean parametric OEM-style wheels (voxel-baked
        # rims are the worst-scoring feature). Default ON for generated cars,
        # opt-in for photo mode, opt-out with wheel_swap: false.
        wheel_report = None
        ws = job_input.get("wheel_swap")
        if ws is None:
            ws = (mode == "text")
        if ws:
            if not isinstance(ws, dict):
                make = (vehicle or {}).get("make", "") if isinstance(vehicle, dict) else ""
                ws = {"style": make.lower() or prompt.lower()[:60]}
            wheel_report = apply_wheel_swap(persisted_path, ws)
        glb_size = os.path.getsize(persisted_path)
        glb_url = upload_to_supabase(
            persisted_path, f"trellis2/{job_id}.glb", "model/gltf-binary")

        result = {
            "status": "success",
            "glb_url": glb_url,
            "glb_path": persisted_path,
            "glb_size_bytes": glb_size,
            "glass": glass_enabled,
            "oem_paint": paint_report,
            "wheels": wheel_report,
            "panel_detail": detail_report,
            "polish": polish_report,
            "mode": mode,
            "message": "GLB generated successfully",
        }
        # Inline base64 only when it fits under RunPod's output cap —
        # otherwise the platform silently drops the ENTIRE output.
        if glb_size <= MAX_INLINE_BYTES:
            with open(persisted_path, "rb") as f:
                result["glb_b64"] = base64.b64encode(f.read()).decode("utf-8")

        if generated_image_b64:
            # persist the intermediate image next to the GLB — RunPod job
            # outputs expire in ~30 min; the bucket copy is permanent
            img_path = os.path.join(OUTPUT_DIR, f"{job_id}.png")
            with open(img_path, "wb") as f:
                f.write(base64.b64decode(generated_image_b64))
            result["image_url"] = upload_to_supabase(
                img_path, f"trellis2/{job_id}.png", "image/png")
            # echo the engineered prompt so callers can see/tune what the
            # vehicle spec expanded to
            result["prompt_used"] = prompt
            # return_image=false -> clean text->3D response (no inline image
            # payload); image_url is always included
            if job_input.get("return_image", True):
                result["generated_image_b64"] = generated_image_b64
        return result

    except Exception as e:
        # Tracebacks are debug output: they leak file paths and internals to
        # whoever calls the endpoint. Ship them only when DEBUG=1 is set on
        # the endpoint (as during bring-up); production gets the message and
        # the full trace goes to worker logs instead.
        import traceback
        result = {"error": str(e)}
        if os.environ.get("DEBUG") == "1":
            result["traceback"] = traceback.format_exc()
        else:
            print(traceback.format_exc(), file=sys.stderr)
        return result


runpod.serverless.start({"handler": handler})
