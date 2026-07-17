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
    def load_lora_weights(self, path):
        captured["lora_loaded"] = path
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
check("T2I got scaffolded prompt", "a toy car" in captured.get("t2i_prompt", "") and "one single vehicle" in captured.get("t2i_prompt", ""))
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

# ---- Test 6: structured vehicle spec -> engineered prompt ----
print("Test 6: vehicle spec")
r = H.handler({"id": "t6", "input": {"vehicle": {
    "year": 2019, "make": "Toyota", "model": "Corolla", "trim": "SE",
    "color": "silver", "body_style": "sedan"}}})
check("success", r.get("status") == "success", json.dumps(r)[:300])
p = captured.get("t2i_prompt", "")
check("identity front-loaded", "2019 Toyota Corolla SE" in p)
check("colour + body style in prompt", "silver paint" in p and "sedan" in p)
check("default view applied", "three-quarter front view" in p)
check("prompt_used echoed", "2019 Toyota Corolla SE" in r.get("prompt_used", ""))

# ---- Test 7: LoRA hook loads when T2I_LORA is set ----
print("Test 7: T2I_LORA hook")
H.T2I_LORA = "/runpod-volume/loras/cars-v1"; H._t2i_pipeline = None
r = H.handler({"id": "t7", "input": {"prompt": "a truck"}})
check("lora loaded from configured path", captured.get("lora_loaded") == "/runpod-volume/loras/cars-v1")

# ---- Test 8: input validation + clamping ----
print("Test 8: knob validation and clamping")
r = H.handler({"id": "t8a", "input": {"prompt": "a mug", "texture_size": "huge"}})
check("bad numeric type -> clear error, no traceback", "Invalid numeric input" in r.get("error", "") and "traceback" not in r)
r = H.handler({"id": "t8b", "input": {"prompt": "a mug", "texture_size": 999999, "decimation_target": 1}})
check("oversize texture clamped to 4096", captured["to_glb"]["texture_size"] == 4096)
check("tiny decimation clamped to 20k", captured["to_glb"]["decimation_target"] == 20_000)

# ---- Test 9: delivery — Supabase upload + size-gated inline base64 ----
print("Test 9: delivery (upload + size gate)")
H.SUPABASE_URL = "https://x.supabase.co"; H.SUPABASE_KEY = "k"; H.SUPABASE_BUCKET = "car-meshes"
fake_up = types.SimpleNamespace(status_code=200, text="")
with mock.patch.object(H.requests, "post", return_value=fake_up) as up:
    r = H.handler({"id": "t9", "input": {"prompt": "a chair"}})
check("glb_url returned", r.get("glb_url") == "https://x.supabase.co/storage/v1/object/public/car-meshes/trellis2/t9.glb")
check("upload hit bucket path", any("car-meshes/trellis2/t9.glb" in c.args[0] for c in up.call_args_list))
check("small glb still inlined", "glb_b64" in r and r.get("glb_size_bytes", 0) <= H.MAX_INLINE_BYTES)
H.MAX_INLINE_BYTES = 4  # force the file over the cap
with mock.patch.object(H.requests, "post", return_value=fake_up):
    r = H.handler({"id": "t9b", "input": {"prompt": "a chair"}})
check("oversized glb NOT inlined (url only)", "glb_b64" not in r and r.get("glb_url"))

# ---- Test 10: glass finalizer on real mini-GLBs ----
print("Test 10: glass finalizer")
import struct
def make_glb(path, alpha_value, frac=1.0):
    img = Image.new("RGBA", (8, 8), (30, 30, 30, 255))
    if alpha_value < 255:
        # paint a localized "window" patch covering ~frac of the texture
        n = max(1, int(64 * frac))
        px = img.load()
        for i in range(n):
            px[i % 8, i // 8] = (30, 30, 30, alpha_value)
    ibuf = io.BytesIO(); img.save(ibuf, "PNG"); png = ibuf.getvalue()
    png += b"\x00" * ((4 - len(png) % 4) % 4)
    j = {"asset": {"version": "2.0"},
         "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}],
         "textures": [{"source": 0}],
         "images": [{"bufferView": 0, "mimeType": "image/png"}],
         "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(png)}],
         "buffers": [{"byteLength": len(png)}]}
    nj = json.dumps(j, separators=(",", ":")).encode()
    nj += b" " * ((4 - len(nj) % 4) % 4)
    out = (b"glTF" + struct.pack("<II", 2, 12 + 8 + len(nj) + 8 + len(png))
           + struct.pack("<I", len(nj)) + b"JSON" + nj
           + struct.pack("<I", len(png)) + b"BIN\x00" + png)
    open(path, "wb").write(out)

def read_alpha_mode(path):
    d = open(path, "rb").read()
    ln = struct.unpack("<I", d[12:16])[0]
    return json.loads(d[20:20+ln])["materials"][0].get("alphaMode", "OPAQUE")

glb_t = f"{H.OUTPUT_DIR}/glass_translucent.glb"; make_glb(glb_t, 80, frac=0.14)
glb_o = f"{H.OUTPUT_DIR}/glass_opaque.glb"; make_glb(glb_o, 255)
check("translucent texture -> BLEND", H.finalize_glass(glb_t) is True and read_alpha_mode(glb_t) == "BLEND")
check("opaque texture -> untouched", H.finalize_glass(glb_o) is False and read_alpha_mode(glb_o) == "OPAQUE")
check("garbage file tolerated", H.finalize_glass(__file__) is False)
os.environ["GLB_ALPHA_MODE"] = "opaque"
make_glb(glb_t, 80, frac=0.14)
check("GLB_ALPHA_MODE=opaque disables", H.finalize_glass(glb_t) is False)
del os.environ["GLB_ALPHA_MODE"]

# ---- Test 11: lightning auto-tune ----
print("Test 11: Lightning model auto-tune")
H.T2I_MODEL = "SG161222/RealVisXL_V4.0_Lightning"; H._t2i_pipeline = None
r = H.handler({"id": "t11", "input": {"prompt": "a van"}})
check("lightning steps=6/guidance=1.5", captured["t2i_steps"] == 6 and captured["t2i_guidance"] == 1.5)

# ---- Test 12: return_image flag + image persistence ----
print("Test 12: return_image flag + image_url")
H.SUPABASE_URL = "https://x.supabase.co"; H.SUPABASE_KEY = "k"; H.SUPABASE_BUCKET = "car-meshes"
fake_up = types.SimpleNamespace(status_code=200, text="")
with mock.patch.object(H.requests, "post", return_value=fake_up):
    r = H.handler({"id": "t12", "input": {"prompt": "a bike", "return_image": False}})
check("inline image suppressed", "generated_image_b64" not in r)
check("image_url still returned", r.get("image_url", "").endswith("trellis2/t12.png"))
check("image persisted to disk", os.path.exists(f"{H.OUTPUT_DIR}/t12.png"))
with mock.patch.object(H.requests, "post", return_value=fake_up):
    r = H.handler({"id": "t12b", "input": {"prompt": "a bike"}})
check("inline image on by default", "generated_image_b64" in r)

# ---- Test 13: glass gate upper bound ----
print("Test 13: glass ceiling (body-wide translucency stays opaque)")
glb_w = f"{H.OUTPUT_DIR}/glass_wide.glb"; make_glb(glb_w, 100)  # 100% translucent
check("body-wide translucency -> stays OPAQUE", H.finalize_glass(glb_w) is False and read_alpha_mode(glb_w) == "OPAQUE")

# ---- Test 14: OEM paint stage ----
print("Test 14: OEM paint (texture-space recolour)")
try:
    import numpy  # oem_paint needs real numpy
    from oem_paint import apply_oem_paint
    glb_p = f"{H.OUTPUT_DIR}/paint.glb"
    img = Image.new("RGBA", (16, 16), (30, 80, 40, 255))  # green "paint"
    ibuf = io.BytesIO(); img.save(ibuf, "PNG"); png = ibuf.getvalue()
    png += b"\x00" * ((4 - len(png) % 4) % 4)
    import struct as _st
    jj = {"asset": {"version": "2.0"},
          "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}],
          "textures": [{"source": 0}],
          "images": [{"bufferView": 0, "mimeType": "image/png"}],
          "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(png)}],
          "buffers": [{"byteLength": len(png)}]}
    nj = json.dumps(jj, separators=(",", ":")).encode(); nj += b" " * ((4 - len(nj) % 4) % 4)
    open(glb_p, "wb").write(b"glTF" + _st.pack("<II", 2, 12+8+len(nj)+8+len(png))
        + _st.pack("<I", len(nj)) + b"JSON" + nj + _st.pack("<I", len(png)) + b"BIN\x00" + png)
    rep = apply_oem_paint(glb_p, {"hex": "#8E1B21", "finish": "solid"})
    check("paint applied with coverage", bool(rep and rep.get("applied") and rep["coverage"] > 0.5))
    d = open(glb_p, "rb").read()
    ln = _st.unpack("<I", d[12:16])[0]; jx = json.loads(d[20:20+ln])
    rest = d[20+ln:]; bl = _st.unpack("<I", rest[0:4])[0]; bd = rest[8:8+bl]
    bv = jx["bufferViews"][jx["images"][0]["bufferView"]]
    im2 = Image.open(io.BytesIO(bd[bv.get("byteOffset",0):bv.get("byteOffset",0)+bv["byteLength"]])).convert("RGB")
    r_, g_, b_ = im2.getpixel((8, 8))
    check("texture recoloured toward target red", r_ > g_ and r_ > b_)
    check("named paint resolves", apply_oem_paint(glb_p, {"name": "Nardo Grey"}) is not None)
    check("unknown spec skipped", apply_oem_paint(glb_p, {"name": "not-a-paint"}) is None)
except ImportError:
    print("  SKIP (numpy unavailable in this env)")

# ---- Test 15: wheel swap ----
print("Test 15: wheel swap (detection + parametric overlay)")
try:
    import numpy as np  # wheel_swap needs real numpy
    from wheel_swap import apply_wheel_swap, detect_wheels, _read_glb, _positions

    def make_car_glb(path, wheel_r=0.075, rot_deg=25):
        """Point-cloud car: box body + 4 wheel disks, rotated about Y."""
        rs = np.random.RandomState(42)
        pts = [np.stack([rs.uniform(-0.45, 0.45, 4000),
                         rs.uniform(2 * wheel_r + 0.01, 0.34, 4000),
                         rs.uniform(-0.17, 0.17, 4000)], 1)]
        for wx in (-0.27, 0.27):
            for wz in (-0.18, 0.18):
                th = rs.uniform(0, 2 * np.pi, 900)
                rr = wheel_r * np.sqrt(rs.uniform(0, 1, 900))
                pts.append(np.stack([wx + rr * np.cos(th),
                                     wheel_r + rr * np.sin(th),
                                     wz + rs.uniform(-0.03, 0.03, 900)], 1))
        V = np.concatenate(pts).astype(np.float32)
        a = np.deg2rad(rot_deg)
        R = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0],
                      [-np.sin(a), 0, np.cos(a)]], np.float32)
        V = V @ R.T
        F = np.arange((len(V) // 3) * 3, dtype=np.uint32)
        pos, idx = V.tobytes(), F.tobytes()
        bb = bytearray(pos + idx)
        while len(bb) % 4:
            bb.append(0)
        import struct as _st
        jj = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": len(bb)}],
              "bufferViews": [
                  {"buffer": 0, "byteOffset": 0, "byteLength": len(pos)},
                  {"buffer": 0, "byteOffset": len(pos), "byteLength": len(idx)}],
              "accessors": [
                  {"bufferView": 0, "componentType": 5126, "count": len(V),
                   "type": "VEC3", "min": V.min(0).tolist(), "max": V.max(0).tolist()},
                  {"bufferView": 1, "componentType": 5125, "count": len(F),
                   "type": "SCALAR"}],
              "materials": [{"pbrMetallicRoughness": {}}],
              "meshes": [{"primitives": [{"attributes": {"POSITION": 0},
                                          "indices": 1, "material": 0}]}],
              "nodes": [{"mesh": 0}], "scenes": [{"nodes": [0]}], "scene": 0}
        nj = json.dumps(jj, separators=(",", ":")).encode()
        nj += b" " * ((4 - len(nj) % 4) % 4)
        open(path, "wb").write(
            b"glTF" + _st.pack("<II", 2, 12 + 8 + len(nj) + 8 + len(bb))
            + _st.pack("<I", len(nj)) + b"JSON" + nj
            + _st.pack("<I", len(bb)) + b"BIN\x00" + bytes(bb))

    glb_c = f"{H.OUTPUT_DIR}/wheels.glb"
    make_car_glb(glb_c)
    jj0, _, bb0 = _read_glb(glb_c)
    det = detect_wheels(_positions(jj0, bb0))
    check("4 wheels detected on rotated car", det is not None and len(det["centers"]) == 4)
    check("wheelbase plausible", det is not None and 0.45 < det["wheelbase"] < 0.65)
    check("radius plausible", det is not None and 0.04 < det["radius"] < 0.11)
    rep = apply_wheel_swap(glb_c, {"style": "audi"})
    check("swap applied", bool(rep and rep.get("applied")))
    jj1, _, bb1 = _read_glb(glb_c)
    wn = [n for n in jj1["nodes"] if n.get("name") == "oem_wheel_node"]
    check("4 wheel nodes appended", len(wn) == 4)
    check("wheel materials appended", len(jj1["materials"]) == 4)
    ok = all(bv.get("byteOffset", 0) + bv["byteLength"] <= len(bb1)
             for bv in jj1["bufferViews"]) and jj1["buffers"][0]["byteLength"] == len(bb1)
    check("binary chunk consistent", ok)
    check("original mesh untouched", jj1["meshes"][0] == jj0["meshes"][0])
    # negative control: a shapeless blob must be refused (GLB untouched)
    blob = rs_v = np.random.RandomState(7).uniform(-0.4, 0.4, (3000, 3)).astype(np.float32)
    check("no false positive on blob", detect_wheels(blob) is None)
except ImportError:
    print("  SKIP (numpy unavailable in this env)")

# ---- Test 16: panel-detail normal map ----
print("Test 16: panel detail (shut-line normal map)")
try:
    import numpy as np
    from normal_detail import apply_panel_detail
    import struct as _st

    def make_tex_glb(path, img):
        ibuf = io.BytesIO(); img.save(ibuf, "PNG"); png = ibuf.getvalue()
        png += b"\x00" * ((4 - len(png) % 4) % 4)
        jj = {"asset": {"version": "2.0"},
              "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}],
              "textures": [{"source": 0}],
              "images": [{"bufferView": 0, "mimeType": "image/png"}],
              "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(png)}],
              "buffers": [{"byteLength": len(png)}]}
        nj = json.dumps(jj, separators=(",", ":")).encode()
        nj += b" " * ((4 - len(nj) % 4) % 4)
        open(path, "wb").write(
            b"glTF" + _st.pack("<II", 2, 12 + 8 + len(nj) + 8 + len(png))
            + _st.pack("<I", len(nj)) + b"JSON" + nj
            + _st.pack("<I", len(png)) + b"BIN\x00" + png)

    glb_n = f"{H.OUTPUT_DIR}/detail.glb"
    body = Image.new("RGBA", (64, 64), (120, 140, 160, 255))
    for x in range(64):  # two dark shut lines
        body.putpixel((x, 20), (20, 22, 25, 255))
        body.putpixel((x, 40), (20, 22, 25, 255))
    make_tex_glb(glb_n, body)
    rep = apply_panel_detail(glb_n, {"strength": 1.5})
    check("detail applied on lined texture", bool(rep and rep.get("applied")))
    d = open(glb_n, "rb").read()
    ln_ = _st.unpack("<I", d[12:16])[0]; jx = json.loads(d[20:20 + ln_])
    check("normalTexture attached", "normalTexture" in jx["materials"][0])
    check("normal image appended", any(i.get("name") == "panel_normal" for i in jx["images"]))
    check("second run refuses to stack", apply_panel_detail(glb_n, True) is None)
    glb_f = f"{H.OUTPUT_DIR}/detail_flat.glb"
    make_tex_glb(glb_f, Image.new("RGBA", (64, 64), (120, 140, 160, 255)))
    check("flat texture skipped", apply_panel_detail(glb_f, True) is None)
except ImportError:
    print("  SKIP (numpy unavailable in this env)")

# ---- Test 17: polish (normal/position smoothing + texture sharpen) ----
print("Test 17: polish (surface + texture)")
try:
    import numpy as np
    from polish import apply_polish
    import struct as _st

    def make_mesh_tex_glb(path):
        """Wavy plane with texture — vertices carry deliberate ripple."""
        n = 24
        gx, gz = np.meshgrid(np.linspace(0, 1, n), np.linspace(0, 1, n))
        ripple = 0.01 * np.sin(gx * 40) * np.sin(gz * 40)
        V = np.stack([gx, ripple, gz], -1).reshape(-1, 3).astype(np.float32)
        N = np.tile(np.array([0, 1, 0], np.float32), (len(V), 1))
        idx = []
        for r in range(n - 1):
            for c in range(n - 1):
                a = r * n + c
                idx += [[a, a + 1, a + n], [a + 1, a + n + 1, a + n]]
        F = np.array(idx, np.uint32)
        img = Image.new("RGBA", (32, 32), (100, 120, 140, 255))
        for x in range(32):
            img.putpixel((x, 16), (20, 22, 25, 255))
        ib = io.BytesIO(); img.save(ib, "PNG"); png = ib.getvalue()
        parts, views, accs, off = [], [], [], 0
        for blob in (V.tobytes(), N.tobytes(), F.tobytes(), png):
            blob += b"\x00" * ((4 - len(blob) % 4) % 4)
            parts.append(blob)
            views.append({"buffer": 0, "byteOffset": off, "byteLength": len(blob)})
            off += len(blob)
        bb = b"".join(parts)
        jj = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": len(bb)}],
              "bufferViews": views,
              "accessors": [
                  {"bufferView": 0, "componentType": 5126, "count": len(V),
                   "type": "VEC3", "min": V.min(0).tolist(), "max": V.max(0).tolist()},
                  {"bufferView": 1, "componentType": 5126, "count": len(N), "type": "VEC3"},
                  {"bufferView": 2, "componentType": 5125, "count": int(F.size), "type": "SCALAR"}],
              "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}],
              "textures": [{"source": 0}],
              "images": [{"bufferView": 3, "mimeType": "image/png"}],
              "meshes": [{"primitives": [{
                  "attributes": {"POSITION": 0, "NORMAL": 1},
                  "indices": 2, "material": 0}]}],
              "nodes": [{"mesh": 0}], "scenes": [{"nodes": [0]}], "scene": 0}
        nj = json.dumps(jj, separators=(",", ":")).encode()
        nj += b" " * ((4 - len(nj) % 4) % 4)
        open(path, "wb").write(
            b"glTF" + _st.pack("<II", 2, 12 + 8 + len(nj) + 8 + len(bb))
            + _st.pack("<I", len(nj)) + b"JSON" + nj
            + _st.pack("<I", len(bb)) + b"BIN\x00" + bb)
        return V

    glb_s = f"{H.OUTPUT_DIR}/polish.glb"
    V0 = make_mesh_tex_glb(glb_s)
    rep = apply_polish(glb_s, True)
    check("polish applied", bool(rep and rep.get("applied")))
    from wheel_swap import _read_glb as _rg
    jx, _, bx = _rg(glb_s)
    accp = jx["accessors"][0]
    bvp = jx["bufferViews"][accp["bufferView"]]
    V1 = np.frombuffer(bytes(bx[bvp["byteOffset"]:bvp["byteOffset"] + len(V0) * 12]),
                       dtype=np.float32).reshape(-1, 3)
    check("ripple reduced", float(np.abs(V1[:, 1]).mean()) < float(np.abs(V0[:, 1]).mean()))
    check("texture re-encoded", jx["images"][0]["bufferView"] != 3)
    check("polish opt-out shape", apply_polish(glb_s, {"smooth_iters": 0, "flatten_iters": 0}) is not None)

    # 17b regression: dark SATURATED paint (navy blue) must NOT get glossed
    # -- live bug: a phytonic-blue X5's body panels were glossed body-wide,
    # rendering as a fireflies/"snow" artifact over the paint. Only dark AND
    # desaturated (true black plastic) should gain gloss.
    def make_gloss_glb(path):
        # realistic proportions: most of the atlas is body paint, trim is a
        # small strip -- a 50/50 split tripped the (correct) area ceiling
        # that caps gloss from ever covering a large contiguous region.
        w, h = 50, 20
        img = Image.new("RGBA", (w, h), (18, 22, 60, 255))  # navy paint (dark, saturated)
        for x in range(w - 4, w):   # 8% strip: black plastic trim (dark, grey)
            for y in range(h):
                img.putpixel((x, y), (20, 20, 20, 255))
        mr = Image.new("RGB", (w, h), (0, 200, 0))  # roughness=200 (matte)
        ib = io.BytesIO(); img.save(ib, "PNG"); png = ib.getvalue()
        mb = io.BytesIO(); mr.save(mb, "PNG"); mrpng = mb.getvalue()
        parts, views, off = [], [], 0
        for blob in (png, mrpng):
            blob = blob + b"\x00" * ((4 - len(blob) % 4) % 4)
            parts.append(blob)
            views.append({"buffer": 0, "byteOffset": off, "byteLength": len(blob)})
            off += len(blob)
        bb = b"".join(parts)
        jj = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": len(bb)}],
              "bufferViews": views,
              "materials": [{"pbrMetallicRoughness": {
                  "baseColorTexture": {"index": 0},
                  "metallicRoughnessTexture": {"index": 1}}}],
              "textures": [{"source": 0}, {"source": 1}],
              "images": [{"bufferView": 0, "mimeType": "image/png"},
                        {"bufferView": 1, "mimeType": "image/png"}]}
        nj = json.dumps(jj, separators=(",", ":")).encode()
        nj += b" " * ((4 - len(nj) % 4) % 4)
        open(path, "wb").write(
            b"glTF" + _st.pack("<II", 2, 12 + 8 + len(nj) + 8 + len(bb))
            + _st.pack("<I", len(nj)) + b"JSON" + nj
            + _st.pack("<I", len(bb)) + b"BIN\x00" + bb)

    glb_g = f"{H.OUTPUT_DIR}/gloss_paint.glb"
    make_gloss_glb(glb_g)
    apply_polish(glb_g, {"smooth_iters": 0, "flatten_iters": 0})
    jg, _, bg = _rg(glb_g)
    mr_i = jg["materials"][0]["pbrMetallicRoughness"]["metallicRoughnessTexture"]["index"]
    mr_img_i = jg["textures"][mr_i]["source"]
    mbv = jg["bufferViews"][jg["images"][mr_img_i]["bufferView"]]
    mrim = Image.open(io.BytesIO(bytes(bg[mbv.get("byteOffset", 0):
                                          mbv.get("byteOffset", 0) + mbv["byteLength"]])))
    mrarr = np.asarray(mrim)
    paint_rough = mrarr[10, 5, 1]     # navy-paint region
    plastic_rough = mrarr[10, 48, 1]  # black-plastic trim strip
    check("dark saturated paint NOT glossed", int(paint_rough) >= 150,
          f"roughness={paint_rough}")
    check("dark desaturated plastic IS glossed", int(plastic_rough) < 150,
          f"roughness={plastic_rough}")
except ImportError:
    print("  SKIP (numpy unavailable in this env)")

# ---- Test 18: vehicle resolver / reference cache ----
print("Test 18: vehicle reference cache")
check("slug canonical", H.vehicle_slug(
    {"make": "BMW", "model": "X5 M Sport", "year": 2020}) == "bmw-x5-m-sport-2020")
check("slug empty spec", H.vehicle_slug({}) is None)
_refpng = io.BytesIO(); Image.new("RGB", (8, 8), (10, 10, 10)).save(_refpng, "PNG")
fake_hit = mock.Mock(status_code=200, content=_refpng.getvalue())
fake_miss = mock.Mock(status_code=404, content=b"")
veh = {"vehicle": {"make": "BMW", "model": "X5", "year": 2020}}
with mock.patch.object(H.requests, "get", return_value=fake_hit), \
     mock.patch.object(H.requests, "post", return_value=fake_up):
    r = H.handler({"id": "t18a", "input": dict(veh)})
check("cache hit -> reference mode", r.get("mode") == "reference")
check("hit returns reference url",
      (r.get("reference_url") or "").endswith("references/bmw-x5-2020.png"))
with mock.patch.object(H.requests, "get", return_value=fake_miss), \
     mock.patch.object(H.requests, "post", return_value=fake_up):
    r2 = H.handler({"id": "t18b", "input": dict(veh)})
check("cache miss -> text mode + stored",
      r2.get("mode") == "text"
      and (r2.get("reference_url") or "").endswith("references/bmw-x5-2020.png"))
with mock.patch.object(H.requests, "get", return_value=fake_hit), \
     mock.patch.object(H.requests, "post", return_value=fake_up):
    r3 = H.handler({"id": "t18c", "input": {**veh, "reference": "off"}})
check("reference off -> no cache use",
      r3.get("mode") == "text" and r3.get("reference_url") is None)

# ---- Test 19: review-fix regressions ----
print("Test 19: adversarial-review fixes")
# 19a: Dockerfile must COPY every local module handler imports at top level
_here = os.path.dirname(os.path.abspath(__file__))
_dockerfile = open(os.path.join(_here, "Dockerfile")).read()
_local_mods = []
for line in open(os.path.join(_here, "handler.py")):
    m = line.strip()
    if m.startswith("from ") and " import " in m:
        mod = m.split()[1].split(".")[0]
        if os.path.exists(os.path.join(_here, mod + ".py")):
            _local_mods.append(mod)
missing = [m for m in set(_local_mods) if (m + ".py") not in _dockerfile]
check("Dockerfile copies all handler imports", not missing,
      f"missing: {missing}")

try:
    import numpy as np
    from wheel_swap import _read_glb as _rg19, _write_glb as _wg19, compact_glb

    # 19b: glass ceiling actively forces OPAQUE on an exporter-set BLEND
    glb_c19 = f"{H.OUTPUT_DIR}/ceiling_blend.glb"
    make_glb(glb_c19, 100)  # 100% translucent = bad segmentation
    j19, t19, b19 = _rg19(glb_c19)
    j19["materials"][0]["alphaMode"] = "BLEND"
    _wg19(glb_c19, j19, t19, b19)
    r19 = H.finalize_glass(glb_c19)
    check("ceiling forces OPAQUE over exporter BLEND",
          r19 is False and read_alpha_mode(glb_c19) == "OPAQUE")

    # 19c: compaction drops orphaned bufferViews and keeps the file valid
    glb_o19 = f"{H.OUTPUT_DIR}/orphan.glb"
    make_glb(glb_o19, 255)
    j19, t19, b19 = _rg19(glb_o19)
    b19 = bytearray(b19)
    blob = b"\x00" * 5000
    start = len(b19); b19.extend(blob)
    j19["bufferViews"].append({"buffer": 0, "byteOffset": start,
                               "byteLength": len(blob)})
    # repoint the image to the new view -> its old view becomes an orphan...
    old_bv = j19["images"][0]["bufferView"]
    px = b19[j19["bufferViews"][old_bv].get("byteOffset", 0):
             j19["bufferViews"][old_bv].get("byteOffset", 0)
             + j19["bufferViews"][old_bv]["byteLength"]]
    b19[start:start + len(px)] = px  # keep it a decodable image
    j19["bufferViews"][-1]["byteLength"] = len(px)
    j19["images"][0]["bufferView"] = len(j19["bufferViews"]) - 1
    _wg19(glb_o19, j19, t19, b19)
    size_before = os.path.getsize(glb_o19)
    saved = compact_glb(glb_o19)
    check("compaction saves bytes", bool(saved) and saved > 0
          and os.path.getsize(glb_o19) < size_before)
    j19b, _, b19b = _rg19(glb_o19)
    ok19 = all(bv.get("byteOffset", 0) + bv["byteLength"] <= len(b19b)
               for bv in j19b["bufferViews"])
    check("compacted GLB structurally valid", ok19)
    check("compaction idempotent", compact_glb(glb_o19) == 0)
except ImportError:
    print("  SKIP numpy-dependent 19b-c")

# 19d: colour is part of the reference slug
check("slug includes colour", H.vehicle_slug(
    {"make": "VW", "model": "Golf", "year": 2021, "color": "Dolphin Blue"})
    == "vw-golf-2021-dolphin-blue")
# 19e: non-dict vehicle is a clean error, not a crash
r19e = H.handler({"id": "t19e", "input": {"vehicle": "2020 BMW X5"}})
check("string vehicle -> clean error", "error" in r19e)
# 19f: t2i_guidance clamped
r19f = H.handler({"id": "t19f", "input": {"prompt": "a car",
                                          "t2i_guidance": 1e9}})
check("huge guidance clamped (no crash)", r19f.get("status") == "success"
      or "error" not in r19f)

# ---- Test 20: FULL five-stage chain on one realistic GLB ----
# The reviewer's top coverage gap: every handler test no-ops the stages on a
# fake binary, so ordering/interaction bugs were invisible. This fixture has
# real geometry (car point cloud + normals + indices) AND a real RGBA
# texture (translucent glass band + dark shut lines), so every stage fires.
print("Test 20: full stage chain integration")
try:
    import numpy as np
    import struct as _st
    from wheel_swap import (_read_glb as _rg20, apply_wheel_swap as _ws20,
                            compact_glb as _cg20, _positions as _pos20)
    from polish import apply_polish as _pol20
    from normal_detail import apply_panel_detail as _pd20

    def make_full_car_glb(path, wheel_r=0.075):
        rs = np.random.RandomState(7)
        pts = [np.stack([rs.uniform(-0.45, 0.45, 6000),
                         rs.uniform(2 * wheel_r + 0.01, 0.34, 6000),
                         rs.uniform(-0.17, 0.17, 6000)], 1)]
        for wx in (-0.27, 0.27):
            for wz in (-0.18, 0.18):
                th = rs.uniform(0, 2 * np.pi, 900)
                rr = wheel_r * np.sqrt(rs.uniform(0, 1, 900))
                pts.append(np.stack([wx + rr * np.cos(th),
                                     wheel_r + rr * np.sin(th),
                                     wz + rs.uniform(-0.03, 0.03, 900)], 1))
        V = np.concatenate(pts).astype(np.float32)
        N = np.tile(np.array([0, 1, 0], np.float32), (len(V), 1))
        F = np.arange((len(V) // 3) * 3, dtype=np.uint32)
        tex = Image.new("RGBA", (64, 64), (40, 80, 160, 255))
        for x in range(64):
            tex.putpixel((x, 20), (15, 16, 18, 255))   # shut line
        for x in range(20, 40):                         # glass band ~5%
            for y in range(4):
                tex.putpixel((x, 50 + y), (30, 40, 45, 120))
        ib = io.BytesIO(); tex.save(ib, "PNG"); png = ib.getvalue()
        parts, views, off = [], [], 0
        for blob in (V.tobytes(), N.tobytes(), F.tobytes(), png):
            blob += b"\x00" * ((4 - len(blob) % 4) % 4)
            parts.append(blob)
            views.append({"buffer": 0, "byteOffset": off, "byteLength": len(blob)})
            off += len(blob)
        bb = b"".join(parts)
        jj = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": len(bb)}],
              "bufferViews": views,
              "accessors": [
                  {"bufferView": 0, "componentType": 5126, "count": len(V),
                   "type": "VEC3", "min": V.min(0).tolist(), "max": V.max(0).tolist()},
                  {"bufferView": 1, "componentType": 5126, "count": len(N), "type": "VEC3"},
                  {"bufferView": 2, "componentType": 5125, "count": int(F.size), "type": "SCALAR"}],
              "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}],
              "textures": [{"source": 0}],
              "images": [{"bufferView": 3, "mimeType": "image/png"}],
              "meshes": [{"primitives": [{
                  "attributes": {"POSITION": 0, "NORMAL": 1},
                  "indices": 2, "material": 0}]}],
              "nodes": [{"mesh": 0}], "scenes": [{"nodes": [0]}], "scene": 0}
        nj = json.dumps(jj, separators=(",", ":")).encode()
        nj += b" " * ((4 - len(nj) % 4) % 4)
        open(path, "wb").write(
            b"glTF" + _st.pack("<II", 2, 12 + 8 + len(nj) + 8 + len(bb))
            + _st.pack("<I", len(nj)) + b"JSON" + nj
            + _st.pack("<I", len(bb)) + b"BIN\x00" + bb)

    glb_f = f"{H.OUTPUT_DIR}/fullchain.glb"
    make_full_car_glb(glb_f)
    g_ok = H.finalize_glass(glb_f)
    p_ok = _pol20(glb_f, True)
    d_ok = _pd20(glb_f, True)
    w_ok = _ws20(glb_f, {"style": "audi"})
    c_saved = _cg20(glb_f)
    check("chain: glass fired", g_ok is True)
    check("chain: polish fired", bool(p_ok and p_ok.get("applied")))
    check("chain: panel detail fired", bool(d_ok and d_ok.get("applied")))
    check("chain: wheels fired", bool(w_ok and w_ok.get("applied")))
    check("chain: compaction ran", c_saved is not None and c_saved >= 0)
    jf, _, bf = _rg20(glb_f)
    ok_f = (all(bv.get("byteOffset", 0) + bv["byteLength"] <= len(bf)
                for bv in jf["bufferViews"])
            and jf["buffers"][0]["byteLength"] == len(bf))
    check("chain: final GLB structurally valid", ok_f)
    check("chain: material is BLEND with normal map",
          jf["materials"][0].get("alphaMode") == "BLEND"
          and "normalTexture" in jf["materials"][0])
    check("chain: positions still parseable", len(_pos20(jf, bf)) > 6000)
except ImportError:
    print("  SKIP (numpy unavailable in this env)")

print()
print("RESULT:", f"{len(fails)} failures" if fails else "ALL TESTS PASSED")
sys.exit(1 if fails else 0)
