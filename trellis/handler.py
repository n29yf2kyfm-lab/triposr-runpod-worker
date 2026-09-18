"""TRELLIS v1 worker: validated requests and safe pipeline caching."""
from __future__ import annotations
import base64, gc, logging, os, sys, threading
from pathlib import Path
sys.path.insert(0, "/app/TRELLIS")
os.environ.setdefault("SPCONV_ALGO", "native")
os.environ.setdefault("ATTN_BACKEND", "xformers")
from input_safety import InputError, decode_base64, fetch_image, validate_job
from output_safety import persist_glb

TEXT_MODEL = "microsoft/TRELLIS-text-xlarge"
IMAGE_MODEL = "microsoft/TRELLIS-image-large"
SPARSE_STRUCTURE_SAMPLER_PARAMS = {"steps": 25, "cfg_strength": 7.5}
SLAT_SAMPLER_PARAMS = {"steps": 25, "cfg_strength": 3.5}
OUTPUT_DIR = os.getenv("TRELLIS_OUTPUT_DIR", "/runpod-volume/outputs/trellis-v1")
LOGGER = logging.getLogger("trellis_worker")
_LOCK = threading.RLock()
_pipeline = None
_pipeline_mode = None

def _backend():
    import torch
    from trellis.pipelines import TrellisImageTo3DPipeline, TrellisTextTo3DPipeline
    from trellis.utils import postprocessing_utils
    return torch, {"text": TrellisTextTo3DPipeline, "image": TrellisImageTo3DPipeline}, postprocessing_utils

def _clear_pipeline(torch):
    global _pipeline, _pipeline_mode
    _pipeline = None
    _pipeline_mode = None
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

def _get_pipeline(mode, torch, classes):
    global _pipeline, _pipeline_mode
    if _pipeline is not None and _pipeline_mode == mode:
        return _pipeline
    _clear_pipeline(torch)
    candidate = None
    try:
        candidate = classes[mode].from_pretrained(TEXT_MODEL if mode == "text" else IMAGE_MODEL)
        candidate.cuda()
    except Exception:
        candidate = None
        _clear_pipeline(torch)
        raise
    _pipeline, _pipeline_mode = candidate, mode
    return candidate

def _generate(data, mode):
    torch, classes, postprocess = _backend()
    argument = data["prompt"].strip() if mode == "text" else (
        decode_base64(data["image_b64"]) if data.get("image_b64", "").strip() else fetch_image(data["image_url"])
    )
    try:
        with _LOCK:
            try:
                pipeline = _get_pipeline(mode, torch, classes)
                outputs = pipeline.run(argument, seed=data.get("seed", 1),
                    sparse_structure_sampler_params=dict(SPARSE_STRUCTURE_SAMPLER_PARAMS),
                    slat_sampler_params=dict(SLAT_SAMPLER_PARAMS))
                glb = postprocess.to_glb(outputs["gaussian"][0], outputs["mesh"][0],
                    simplify=0.9, texture_size=2048)
                return bytes(glb.export(file_type="glb"))
            except Exception:
                _clear_pipeline(torch)
                raise
    finally:
        if mode == "image":
            argument.close()

def handler(job):
    try:
        data, mode = validate_job(job)
        blob = _generate(data, mode)
        path = persist_glb(blob, Path(OUTPUT_DIR))
        return {"status":"success","glb_b64":base64.b64encode(blob).decode("ascii"),
                "glb_path":str(path),"mode":mode,"message":"GLB generated successfully"}
    except InputError as exc:
        return {"error":str(exc),"error_code":"INVALID_INPUT"}
    except Exception:
        LOGGER.exception("TRELLIS generation failed")
        return {"error":"3D generation failed. Check worker logs for this job.","error_code":"GENERATION_FAILED"}

if __name__ == "__main__":
    from verify_runtime import verify
    verify()
    import runpod
    runpod.serverless.start({"handler": handler})
