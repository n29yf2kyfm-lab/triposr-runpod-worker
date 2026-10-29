"""vision.py: the image encoder the trained heads sit on.

CLIP's image half (ViT-B/32, OpenAI's weights, as exported to ONNX for
transformers.js), run with onnxruntime: no PyTorch at use time. A picture is
padded to a square (a car photo is wide; CLIP's own centre crop cuts off its
nose or tail, which is what tells its side) and turned into 512 numbers, of
unit length. The heads (heads.py) read those numbers.

The encoder is fetched once into $VEHICLE_AI_HOME (default ~/.cache/vehicle-ai)
and checked against its published SHA-256 before it is used; a copy found
later (there, or beside this file in a bundle) must be the same size.
"""
import hashlib
import os
import urllib.request

import numpy as np
from PIL import Image, ImageOps

# name: (Hugging Face repo, pinned revision, file, SHA-256, size in bytes)
ENCODERS = {
    "clip-b32": ("Xenova/clip-vit-base-patch32", "d15189d7028b43f1d3e65039190477f6af591c2a", "onnx/vision_model.onnx",
                 "fd6e1402a588279d1723c7534d4bcba5bc0b14b47dfab0e46f8c47b8270d7d40", 351685709),
    # the same, its weights in 8 bits (90 MB): the phone page's (web/), with heads trained on it (web/heads.json)
    "clip-b32-int8": ("Xenova/clip-vit-base-patch32", "d15189d7028b43f1d3e65039190477f6af591c2a",
                      "onnx/vision_model_quantized.onnx",
                      "583fd1110a514667812fee7d684952aaf82a99b959760c8d7dca7e0ab9839299", 89117001),
    # CLIP ViT-L/14 (1.2 GB, 768 numbers a picture): far better at whether a build is the photo's vehicle
    "clip-l14": ("Xenova/clip-vit-large-patch14", "c307790166907339eed5a9a53a249af534102536", "onnx/vision_model.onnx",
                 "ff49f8aa57c7abfd26e382eb083e4dbf988505223a9bd3767dbfd4e729206709", 1216438437),
    "clip-l14-int8": ("Xenova/clip-vit-large-patch14", "c307790166907339eed5a9a53a249af534102536",
                      "onnx/vision_model_int8.onnx",
                      "d6eac98fc74a89ef2e50ba635c6b4c7f005dd324dcc6aeb6be89872f58d7b3fd", 306348752),
    # DINOv2 (Meta's, self-supervised; 350 MB, 1536 numbers: its class token and its patches' mean): reads
    # which way a vehicle points without a miss
    "dinov2-base": ("Xenova/dinov2-base", "d623d125a29e343851bcedff293fdc8b6bda292b", "onnx/model.onnx",
                    "de9c675d214f0171285f90f1d1d7716bce1c5e280e93826d071d57f7b9314d98", 346555570),
    "dinov2-base-int8": ("Xenova/dinov2-base", "d623d125a29e343851bcedff293fdc8b6bda292b", "onnx/model_quantized.onnx",
                         "1a1210212e3d8c2924d2ad985e46207bb407ac9a9763a240cacdeb94cd0bbf9c", 90974542),
    "dinov2-base-q4": ("Xenova/dinov2-base", "d623d125a29e343851bcedff293fdc8b6bda292b", "onnx/model_q4f16.onnx",
                       "86d3711c68b1937d666ce6af8336c2296a54a783617070a5cb33458e33eb17f4", 49539422),
    # SigLIP (Google's, base, patch 16; 370 MB, 768 numbers: its pooled output): the best of these at a vehicle's
    # kind and colour, and at whether a build is the photo's vehicle; poor at which way it points
    "siglip-b16": ("Xenova/siglip-base-patch16-224", "4649052661e53c7000355844105f8a1792088239", "onnx/vision_model.onnx",
                   "f89d41bac7f4d4b87e010a467d93f98689d708916ed22f5a07f96fdfa26f475f", 371819850),
    "siglip-b16-q4": ("Xenova/siglip-base-patch16-224", "4649052661e53c7000355844105f8a1792088239",
                      "onnx/vision_model_q4f16.onnx",
                      "c9eb383bddf748212d240d90ca765415137d7994c60dd8be97bdb3adad30c682", 54625339),
}
DEFAULT_ENCODERS = ["siglip-b16", "dinov2-base"]
SIZE = 224
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], np.float32)
# DINOv2 was trained on pictures normalised ImageNet's way, SigLIP on ones scaled to -1..1; the square is
# still padded with CLIP's mean colour for all of them
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], np.float32)
HALF = np.array([0.5, 0.5, 0.5], np.float32)
MIN_SIDE = 64          # a picture smaller than this on its short side is not read: there is no vehicle to see


class Unreadable(ValueError):
    """A file that is not a picture the model can read: missing, broken, empty, too small."""


def home():
    return os.environ.get("VEHICLE_AI_HOME") or os.path.join(os.path.expanduser("~"), ".cache", "vehicle-ai")


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(name="clip-b32"):
    """The encoder's file: beside this file (a bundle), else in $VEHICLE_AI_HOME, else downloaded there once."""
    repo, rev, path, want, size = ENCODERS[name]
    for have in (os.path.join(os.path.dirname(os.path.abspath(__file__)), name + ".onnx"),
                 os.path.join(home(), name + ".onnx")):
        if os.path.exists(have):
            if os.path.getsize(have) != size:
                raise SystemExit(f"vehicle-ai: {have} is not the encoder the heads were trained on "
                                 f"({os.path.getsize(have)} bytes, not {size}): remove it and run again")
            return have
    out = os.path.join(home(), name + ".onnx")
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
    """A picture as RGB, its camera rotation applied. A cut-out (a build's studio picture, its background
    see-through) is cropped to the vehicle and put on white, so a full picture and a small copy read alike."""
    try:
        im = ImageOps.exif_transpose(Image.open(path))
        im.load()
    except (OSError, ValueError, Image.DecompressionBombError) as e:   # missing, empty, not a picture, cut short
        raise Unreadable(f"{path}: not a picture it can read ({e})") from None
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        box = Image.fromarray((np.asarray(im)[..., 3] > 8).astype(np.uint8) * 255).getbbox()
        if box:
            m = round(0.04 * max(box[2] - box[0], box[3] - box[1]))
            im = im.crop((max(0, box[0] - m), max(0, box[1] - m), min(im.width, box[2] + m), min(im.height, box[3] + m)))
        im = Image.alpha_composite(Image.new("RGBA", im.size, (255, 255, 255, 255)), im)
    if min(im.size) < MIN_SIDE:
        raise Unreadable(f"{path}: {im.width}x{im.height} is too small to read (under {MIN_SIDE} px a side)")
    return im.convert("RGB")


def dhash(im):
    """A picture's fingerprint by its looks (256 bits, as 64 hex digits): the same photo resized or saved
    again is a few bits from it, another photo is a hundred or so (difference hash, 17x16 grey)."""
    a = np.asarray(im.convert("L").resize((17, 16), Image.BILINEAR), np.int16)
    return np.packbits((a[:, 1:] > a[:, :-1]).ravel()).tobytes().hex()


def dhash_bits(a, b):
    """How many of the 256 bits two dhashes differ in."""
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def prep(im, mean=MEAN, std=STD):
    """The whole picture on a square of CLIP's mean colour (zero once normalised CLIP's way), 224 a side."""
    s = SIZE / max(im.size)
    w, h = max(1, round(im.width * s)), max(1, round(im.height * s))
    im = im.resize((w, h), Image.BICUBIC)
    sq = Image.new("RGB", (SIZE, SIZE), tuple(int(round(m * 255)) for m in MEAN))
    sq.paste(im, ((SIZE - w) // 2, (SIZE - h) // 2))
    a = (np.asarray(sq, np.float32) / 255.0 - mean) / std
    return a.transpose(2, 0, 1)


class Encoder:
    """One image encoder (ONNX), told apart by the file's own outputs: CLIP's (image_embeds), SigLIP's
    (pooler_output) or DINOv2's (last_hidden_state alone: the class token and the patches' mean, side by side)."""

    def __init__(self, path=None, threads=None):
        import onnxruntime as ort
        so = ort.SessionOptions()
        if threads:
            so.intra_op_num_threads = threads
        self.path = path or fetch()
        self.sess = ort.InferenceSession(self.path, so, providers=["CPUExecutionProvider"])
        outs = {o.name: o for o in self.sess.get_outputs()}
        self.kind = "siglip" if "pooler_output" in outs else "dino" if "last_hidden_state" in outs else "clip"
        self.out = outs[{"siglip": "pooler_output", "dino": "last_hidden_state"}.get(self.kind, "image_embeds")]
        self.dino = self.kind == "dino"
        self.mean, self.std = {"dino": (IMAGENET_MEAN, IMAGENET_STD), "siglip": (HALF, HALF)}.get(self.kind, (MEAN, STD))
        self.width = int(self.out.shape[-1]) * (2 if self.dino else 1)      # numbers a picture: 512, 768 or 1536

    def embed(self, images, flip=False, batch=16):
        """Unit-length embeddings of PIL images (mirrored first if FLIP), one row each."""
        out = []
        for i in range(0, len(images), batch):
            ims = images[i:i + batch]
            if flip:
                ims = [im.transpose(Image.FLIP_LEFT_RIGHT) for im in ims]
            x = np.stack([prep(im, self.mean, self.std) for im in ims]).astype(np.float32)
            y = self.sess.run([self.out.name], {"pixel_values": x})[0]
            out.append(np.concatenate([y[:, 0], y[:, 1:].mean(1)], 1) if self.dino else y)
        e = np.concatenate(out) if out else np.zeros((0, self.width), np.float32)
        return e / np.linalg.norm(e, axis=1, keepdims=True).clip(1e-8)


class Encoders:
    """Several encoders read as one: their embeddings side by side (each of unit length)."""

    def __init__(self, paths=None, threads=None):
        paths = paths or [fetch(n) for n in DEFAULT_ENCODERS]
        self.parts = [Encoder(p, threads) for p in paths]
        self.path = ",".join(e.path for e in self.parts)
        self.width = sum(e.width for e in self.parts)

    def embed(self, images, flip=False, batch=16):
        return np.hstack([e.embed(images, flip, batch) for e in self.parts])


def encoders(spec=None):
    """The encoders SPEC names: paths or ENCODERS names, comma-separated (default DEFAULT_ENCODERS)."""
    names = [x for x in (spec or "").split(",") if x] or list(DEFAULT_ENCODERS)
    return Encoders([fetch(n) if n in ENCODERS else n for n in names])
