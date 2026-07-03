import runpod
import torch
import requests
import base64
import os
import tempfile
from PIL import Image
import sys

# Add TripoSR to path
sys.path.insert(0, '/app/TripoSR')

def load_model():
    from tsr.system import TSR
    model = TSR.from_pretrained(
        "stabilityai/TripoSR",
        config_name="config.yaml",
        weight_name="model.ckpt",
    )
    model.renderer.set_chunk_size(8192)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    return model, device

MODEL = None
DEVICE = None

def get_model():
    global MODEL, DEVICE
    if MODEL is None:
        MODEL, DEVICE = load_model()
    return MODEL, DEVICE

def process_image(image_input):
    """Load image from URL or base64"""
    if image_input.startswith('http'):
        response = requests.get(image_input, timeout=30)
        img = Image.open(BytesIO(response.content)).convert("RGBA")
    else:
        img_data = base64.b64decode(image_input)
        img = Image.open(BytesIO(img_data)).convert("RGBA")
    return img

def handler(job):
    job_input = job.get("input", {})
    
    image_url = job_input.get("image_url", "")
    image_b64 = job_input.get("image_b64", "")
    
    if not image_url and not image_b64:
        return {"error": "Provide image_url or image_b64"}
    
    try:
        from io import BytesIO
        import trimesh
        
        model, device = get_model()
        
        # Load image
        if image_url:
            response = requests.get(image_url, timeout=30)
            img = Image.open(BytesIO(response.content)).convert("RGBA")
        else:
            img_data = base64.b64decode(image_b64)
            img = Image.open(BytesIO(img_data)).convert("RGBA")
        
        # Resize — FIX: cast to int to avoid PIL float error
        img = img.resize((512, 512), Image.Resampling.LANCZOS)
        
        # Run TripoSR
        with torch.no_grad():
            scene_codes = model([img], device=device)
        
        # Export GLB
        with tempfile.TemporaryDirectory() as tmpdir:
            glb_path = os.path.join(tmpdir, "output.glb")
            
            exporter_output = model.render(
                scene_codes,
                n_views=1,
                return_type="pil"
            )
            
            meshes = model.extract_mesh(
                scene_codes,
                has_vertex_color=True,
                resolution=256,
            )
            
            # FIX: ensure int dimensions
            mesh = meshes[0]
            mesh.export(glb_path)
            
            with open(glb_path, "rb") as f:
                glb_b64 = base64.b64encode(f.read()).decode("utf-8")
        
        return {
            "status": "success",
            "glb_b64": glb_b64,
            "message": "GLB generated successfully"
        }
        
    except Exception as e:
        import traceback
        return {
            "error": str(e),
            "traceback": traceback.format_exc()
        }

runpod.serverless.start({"handler": handler})
