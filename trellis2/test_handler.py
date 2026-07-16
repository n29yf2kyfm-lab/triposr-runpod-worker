"""Unit test for trellis2/handler.py with heavy deps stubbed.

Verifies the handler's actual control flow end-to-end minus the GPU:
routing (prompt vs image_b64 vs image_url vs nothing), the exact kwargs
passed to pipeline.run / to_glb / glb.export, knob overrides, base64
round-trips, and output persistence.
"""
import base64
import io
import json
import sys
import types
import unittest.mock as mock

from PIL import Image

# ---- stub heavy modules before importing the handler ----
captured = {}

# torch stub
torch = types.ModuleType("torch")
torch.no_grad = lambda: mock.MagicMock(__enter__=lambda s: None, __exit__=lambda s, *a: False)
torch.float16 = "float16"
class _Gen:
    def __init__(self, dev): pass
    def manual_seed(self, s):
        captured["t2i_seed"] = s
        return self
torch.Generator = _Gen
sys.modules["torch"] = torch

# runpod stub — capture the handler instead of starting a server
runpod = types.ModuleType("runpod")
runpod.serverless = types.SimpleNamespace(start=lambda cfg: captured.update(started=cfg))
sys.modules["runpod"] = runpod

# trellis2.pipelines stub
class FakeMesh:
    vertices = "V"; faces = "F"; attrs = "A"; coords = "C"
    layout = {"base_color": slice(0, 3)}; voxel_size = 0.001953125

class FakePipeline:
    @classmethod
    def from_pretrained(cls, name):
        captured["i23d_model"] = name
        return cls()
    def cuda(self): return self
    def run(self, img, num_samples=1, seed=42, **kw):
        captured["run_img_size"] = img.size
        captured["run_seed"] = seed
        return [FakeMesh()]

tp = types.ModuleType("trellis2.pipelines")
tp.Trellis2ImageTo3DPipeline = FakePipeline
t2 = types.ModuleType("trellis2"); t2.pipelines = tp
sys.modules["trellis2"] = t2
sys.modules["trellis2.pipelines"] = tp

# o_voxel stub — enforce the REAL to_glb signature (aabb required, no default)
class FakeGLB:
    def export(self, path, extension_webp=False):
        captured["export"] = (path, extension_webp)
        with open(path, "wb") as f:
            f.write(b"glTF-fake-binary")

def to_glb(vertices, faces, attr_volume, coords, attr_layout, aabb,
           voxel_size=None, grid_size=None, decimation_target=1000000,
           texture_size=2048, remesh=False, remesh_band=1, remesh_project=0.9,
           **kw):
    captured["to_glb"] = dict(vertices=vertices, faces=faces, aabb=aabb,
                              decimation_target=decimation_target,
                              texture_size=texture_size, remesh=remesh)
    return FakeGLB()

ov = types.ModuleType("o_voxel")
ov.postprocess = types.SimpleNamespace(to_glb=to_glb)
sys.modules["o_voxel"] = ov

# diffusers stub (text-to-image)
class FakeT2I:
    @classmethod
    def from_pretrained(cls, name, **kw):
        captured["t2i_model"] = name
        return cls()
    def to(self, dev): return self
    def __call__(self, prompt, negative_prompt=None, num_inference_steps=None,
                 guidance_scale=None, width=None, height=None, generator=None):
        captured["t2i_prompt"] = prompt
        captured["t2i_steps"] = num_inference_steps
        captured["t2i_guidance"] = guidance_scale
        img = Image.new("RGB", (width, height), (200, 30, 30))
        return types.SimpleNamespace(images=[img])

diffusers = types.ModuleType("diffusers")
diffusers.AutoPipelineForText2Image = FakeT2I
sys.modules["diffusers"] = diffusers

# ---- import the handler (runpod.serverless.start is stubbed) ----
import os
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import handler as H
H.OUTPUT_DIR = tempfile.mkdtemp(prefix="trellis2-test-outputs-")

fails = []
def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond: fails.append(name)

# ---- Test 1: no input -> error ----
print("Test 1: empty input")
r = H.handler({"id": "t1", "input": {}})
check("returns error", "error" in r)

# ---- Test 2: text-to-3D path ----
print("Test 2: prompt (text -> image -> 3D -> trim -> colour)")
r = H.handler({"id": "t2", "input": {"prompt": "a toy car", "seed": 7}})
check("success", r.get("status") == "success", json.dumps(r)[:300])
check("mode=text", r.get("mode") == "text")
check("T2I got scaffolded prompt", "a toy car" in captured.get("t2i_prompt", "") and "single object" in captured.get("t2i_prompt", ""))
check("SDXL defaults steps=30/guidance=7.0", captured.get("t2i_steps") == 30 and captured.get("t2i_guidance") == 7.0)
check("seed threaded to both stages", captured.get("t2i_seed") == 7 and captured.get("run_seed") == 7)
check("generated image returned", bool(r.get("generated_image_b64")))
img = Image.open(io.BytesIO(base64.b64decode(r["generated_image_b64"])))
check("generated image is 1024x1024 PNG", img.size == (1024, 1024) and img.format == "PNG")
check("to_glb got required aabb", captured["to_glb"]["aabb"] == [[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]])
check("default trim/colour knobs", captured["to_glb"]["decimation_target"] == 1_000_000 and captured["to_glb"]["texture_size"] == 4096)
check("remesh on", captured["to_glb"]["remesh"] is True)
check("webp export + persisted path", captured["export"] == (f"{H.OUTPUT_DIR}/t2.glb", True))
check("glb_b64 round-trips", base64.b64decode(r["glb_b64"]) == b"glTF-fake-binary")

# ---- Test 3: image_b64 path with knob overrides ----
print("Test 3: image_b64 + trim/colour overrides")
buf = io.BytesIO(); Image.new("RGB", (256, 256), (0, 90, 200)).save(buf, "PNG")
r = H.handler({"id": "t3", "input": {
    "image_b64": base64.b64encode(buf.getvalue()).decode(),
    "seed": 3, "decimation_target": 250000, "texture_size": 1024}})
check("success", r.get("status") == "success", json.dumps(r)[:300])
check("mode=image", r.get("mode") == "image")
check("no generated_image_b64 in image mode", "generated_image_b64" not in r)
check("override trim", captured["to_glb"]["decimation_target"] == 250000)
check("override colour", captured["to_glb"]["texture_size"] == 1024)
check("pipeline got decoded 256x256 image", captured["run_img_size"] == (256, 256))

# ---- Test 4: image_url path (requests mocked) ----
print("Test 4: image_url")
buf2 = io.BytesIO(); Image.new("RGB", (128, 128)).save(buf2, "PNG")
fake_resp = types.SimpleNamespace(content=buf2.getvalue(), raise_for_status=lambda: None)
with mock.patch.object(H.requests, "get", return_value=fake_resp) as g:
    r = H.handler({"id": "t4", "input": {"image_url": "https://x.test/i.png"}})
check("success", r.get("status") == "success", json.dumps(r)[:300])
check("fetched with UA headers", g.call_args.kwargs["headers"]["User-Agent"].startswith("Mozilla/5.0"))

# ---- Test 5: turbo model auto-tunes ----
print("Test 5: T2I_MODEL=sdxl-turbo auto steps/guidance")
H.T2I_MODEL = "stabilityai/sdxl-turbo"; H._t2i_pipeline = None
r = H.handler({"id": "t5", "input": {"prompt": "a mug"}})
check("turbo steps=4/guidance=0.0", captured["t2i_steps"] == 4 and captured["t2i_guidance"] == 0.0)

print()
print("RESULT:", f"{len(fails)} failures" if fails else "ALL TESTS PASSED")
sys.exit(1 if fails else 0)
