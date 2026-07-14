import runpod
import requests
import base64
import os
import sys
import glob
import shutil
import tempfile
import subprocess
from io import BytesIO
from PIL import Image

PIFUHD_DIR = "/app/pifuhd"
POSE_DIR = "/app/lightweight-human-pose-estimation.pytorch"
PIFUHD_CKPT = "/app/pifuhd/checkpoints/pifuhd.pt"

# 256 matches PIFuHD's demo default (-r 256). 512 is sharper but ~4x slower and
# far more VRAM-hungry. Override with the PIFUHD_RESOLUTION env var if wanted.
RESOLUTION = os.environ.get("PIFUHD_RESOLUTION", "256")

# Persist outputs to the network volume when one is mounted; skip silently if not.
OUTPUT_DIR = "/runpod-volume/outputs"


def fetch_image(image_url):
    """Fetch image from URL with browser-like headers."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; MetaHuman-Worker/1.0)",
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
    }
    response = requests.get(image_url, headers=headers, timeout=30)
    response.raise_for_status()
    return Image.open(BytesIO(response.content)).convert("RGB")


def obj_to_glb_b64(obj_path):
    """Load PIFuHD's OBJ (with per-vertex colors) and return it as GLB base64."""
    import trimesh

    mesh = trimesh.load(obj_path, process=False)
    if isinstance(mesh, trimesh.Scene):
        mesh = mesh.dump(concatenate=True)
    glb_bytes = mesh.export(file_type="glb")
    return base64.b64encode(glb_bytes).decode("utf-8"), mesh


def handler(job):
    job_input = job.get("input", {})
    job_id = job.get("id", "unknown")

    image_url = job_input.get("image_url", "")
    image_b64 = job_input.get("image_b64", "")
    resolution = str(job_input.get("resolution", RESOLUTION))

    if not image_url and not image_b64:
        return {"error": "Provide image_url or image_b64 (a photo of a person)"}

    work_in = tempfile.mkdtemp(prefix="mh_in_")
    work_out = tempfile.mkdtemp(prefix="mh_out_")
    try:
        # Load the input image.
        if image_b64:
            img = Image.open(BytesIO(base64.b64decode(image_b64))).convert("RGB")
        else:
            img = fetch_image(image_url)

        img_path = os.path.join(work_in, "input.png")
        img.save(img_path)

        # Step 1: detect the person and write input_rect.txt next to the image.
        # Run in the pose repo so its `import models/modules/demo` resolve there.
        rect_proc = subprocess.run(
            [sys.executable, "gen_rect.py", img_path],
            cwd=POSE_DIR,
            capture_output=True,
            text=True,
        )
        if rect_proc.returncode != 0:
            return {
                "error": "Pose/rect detection failed",
                "stdout": rect_proc.stdout[-4000:],
                "stderr": rect_proc.stderr[-4000:],
            }

        # Step 2: run PIFuHD reconstruction over the cropped person.
        recon_proc = subprocess.run(
            [
                sys.executable, "-m", "apps.simple_test",
                "-i", work_in,
                "-o", work_out,
                "-r", resolution,
                "-c", PIFUHD_CKPT,
                "--use_rect",
            ],
            cwd=PIFUHD_DIR,
            capture_output=True,
            text=True,
        )

        # PIFuHD writes results/pifuhd_final/recon/result_<name>_<res>.obj
        objs = glob.glob(os.path.join(work_out, "**", "recon", "*.obj"), recursive=True)
        if not objs:
            return {
                "error": "PIFuHD produced no mesh",
                "stdout": recon_proc.stdout[-4000:],
                "stderr": recon_proc.stderr[-4000:],
            }

        obj_path = max(objs, key=os.path.getsize)
        glb_b64, mesh = obj_to_glb_b64(obj_path)

        # Persist a copy to the network volume if one is mounted.
        persisted_path = None
        if os.path.isdir("/runpod-volume"):
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            persisted_path = os.path.join(OUTPUT_DIR, f"{job_id}.glb")
            mesh.export(persisted_path)

        return {
            "status": "success",
            "glb_b64": glb_b64,
            "glb_path": persisted_path,
            "resolution": resolution,
            "message": "GLB generated successfully",
        }

    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}
    finally:
        shutil.rmtree(work_in, ignore_errors=True)
        shutil.rmtree(work_out, ignore_errors=True)


runpod.serverless.start({"handler": handler})
