"""vision.py: the image encoder the trained heads sit on.

CLIP's image half (ViT-B/32, OpenAI's weights, as exported to ONNX for
transformers.js), run with onnxruntime: no PyTorch at use time. A picture is
padded to a square (a car photo is wide; CLIP's own centre crop cuts off its
nose or tail, which is what tells its side) and turned into 512 numbers, of
unit length. The heads (heads.py) read those numbers.

The encoder is fetched once into $VEHICLE_AI_HOME (default ~/.cache/vehicle-ai)
and checked against its published SHA-256 before it is used.
"""
import hashlib
import os
import urllib.request

import numpy as np
from PIL import Image, ImageOps

ENCODERS = {
    # name: (Hugging Face repo, pinned revision, file, SHA-256 of the file)
    "clip-b32": ("Xenova/clip-vit-base-patch32", "d15189d7028b43f1d3e65039190477f6af591c2a",
                 "onnx/vision_model.onnx", "fd6e1402a588279d1723c7534d4bcba5bc0b14b47dfab0e46f8c47b8270d7d40"),
    "clip-b32-int8": ("Xenova/clip-vit-base-patch32", "d15189d7028b43f1d3e65039190477f6af591c2a",
                      "onnx/vision_model_quantized.onnx", "583fd1110a514667812fee7d684952aaf82a99b959760c8d7dca7e0ab9839299"),
}
SIZE = 224
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], np.float32)


def home():
    return os.environ.get("VEHICLE_AI_HOME") or os.path.join(os.path.expanduser("~"), ".cache", "vehicle-ai")


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(name="clip-b32"):
    """The encoder's file: from $VEHICLE_AI_HOME, else downloaded there (once) and checked."""
    repo, rev, path, want = ENCODERS[name]
    beside = os.path.join(os.path.dirname(os.path.abspath(__file__)), name + ".onnx")
    if os.path.exists(beside):          # a bundle (bundle.py) carries its encoder with it
        return beside
    out = os.path.join(home(), name + ".onnx")
    if os.path.exists(out):
        return out
    os.makedirs(home(), exist_ok=True)
    part = out + ".part"
    url = f"https://huggingface.co/{repo}/resolve/{rev}/{path}"
    print(f"vehicle-ai: fetching the image encoder ({name}) from {url}", flush=True)
    urllib.request.urlretrieve(url, part)
    got = file_sha256(part)
    if got != want:
        os.remove(part)
        raise SystemExit(f"vehicle-ai: {url} is not the file the heads were trained on (sha256 {got})")
    os.replace(part, out)
    return out


def load(path):
    """A picture as RGB, its camera rotation applied; a cut-out's see-through background made white."""
    im = ImageOps.exif_transpose(Image.open(path))
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)
    return im.convert("RGB")


def prep(im):
    """The whole picture on a square of CLIP's mean colour (zero once normalised), 224 a side."""
    s = SIZE / max(im.size)
    w, h = max(1, round(im.width * s)), max(1, round(im.height * s))
    im = im.resize((w, h), Image.BICUBIC)
    sq = Image.new("RGB", (SIZE, SIZE), tuple(int(round(m * 255)) for m in MEAN))
    sq.paste(im, ((SIZE - w) // 2, (SIZE - h) // 2))
    a = (np.asarray(sq, np.float32) / 255.0 - MEAN) / STD
    return a.transpose(2, 0, 1)


class Encoder:
    def __init__(self, path=None, threads=None):
        import onnxruntime as ort
        so = ort.SessionOptions()
        if threads:
            so.intra_op_num_threads = threads
        self.path = path or fetch()
        self.sess = ort.InferenceSession(self.path, so, providers=["CPUExecutionProvider"])

    def embed(self, images, flip=False, batch=16):
        """Unit-length embeddings of PIL images (mirrored first if FLIP), one row each."""
        out = []
        for i in range(0, len(images), batch):
            ims = images[i:i + batch]
            if flip:
                ims = [im.transpose(Image.FLIP_LEFT_RIGHT) for im in ims]
            x = np.stack([prep(im) for im in ims]).astype(np.float32)
            out.append(self.sess.run(None, {"pixel_values": x})[0])
        e = np.concatenate(out) if out else np.zeros((0, 512), np.float32)
        return e / np.linalg.norm(e, axis=1, keepdims=True).clip(1e-8)
