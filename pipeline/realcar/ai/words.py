"""words.py: what each paint family is called, as SigLIP reads the words: a direction in its pictures' own space.

SigLIP was trained on pictures with their captions, and has no projection between the two: its pooled
reading of a picture and of a caption are compared directly. So "a photo of a silver car" is a direction
that points where silver cars' pictures do, learnt from far more pictures than the run has. train.py gives
the colour head each picture's likeness to every family's words beside its embedding and histogram, then
folds those weights back into the embedding's (the likeness is the embedding times a fixed matrix): the
head written takes the same numbers it always did, and nothing reads text when it runs. Only training
needs the text tower (110 MB, fetched once, pinned, like the encoders).
"""
import os
import urllib.request

import numpy as np

import vision

REV = "https://huggingface.co/Xenova/siglip-base-patch16-224/resolve/4649052661e53c7000355844105f8a1792088239/"
TEXT = {"siglip-b16-text.onnx": (REV + "onnx/text_model_quantized.onnx",
                                 "ad0329b1f35acc66d8953ff2559ce358da8eb0a7011794cf951523d63a4dbce2"),
        "siglip-b16-tokenizer.json": (REV + "tokenizer.json",
                                      "4a17c975210be5ab4c36b47d8dae4eefb866dbfb1e676e394aad85dc30a3ae08")}
# the encoders whose first numbers are SigLIP's pooled reading (vision.ENCODERS): the words' space
SPACE = ("siglip-b16", "siglip-b16-q4")
WIDTH = 768
# each family as people say it: its words in each template, averaged
WORDS = {"white": ["white"], "pearl-white": ["pearl white", "off-white"], "silver": ["silver"], "grey": ["grey", "gray"],
         "dark-grey": ["dark grey", "charcoal grey"], "black": ["black"], "dark-blue": ["dark blue", "navy blue"],
         "blue": ["blue"], "light-blue": ["light blue", "sky blue"], "turquoise": ["turquoise", "teal"], "red": ["red"],
         "dark-red": ["dark red", "maroon"], "orange": ["orange"], "yellow": ["yellow"], "gold": ["gold"],
         "green": ["green"], "dark-green": ["dark green", "british racing green"], "light-green": ["light green", "lime green"],
         "brown": ["brown"], "bronze": ["bronze"], "beige": ["beige"], "champagne": ["champagne", "pale gold"],
         "purple": ["purple"], "lilac": ["lilac", "lavender"], "grey-blue": ["slate blue", "steel blue"],
         "grey-green": ["grey-green", "slate green"], "taupe": ["taupe"], "sage": ["sage green", "pale sage"],
         "olive": ["olive green", "khaki"], "copper": ["copper", "terracotta"], "aqua": ["aqua", "pale aqua"]}
TEMPLATES = ["a photo of a {} car.", "a {} car.", "a {} vehicle parked outside."]
MAX_TOKENS = 64             # SigLIP's captions: padded to 64 with its end token, read at the last


def fetch():
    out = []
    for name, (url, want) in TEXT.items():
        p = os.path.join(vision.home(), name)
        if not os.path.exists(p) or vision.file_sha256(p) != want:
            os.makedirs(vision.home(), exist_ok=True)
            urllib.request.urlretrieve(url, p + ".part")
            if vision.file_sha256(p + ".part") != want:
                os.remove(p + ".part")
                raise SystemExit(f"words: {url} is not the file pinned here")
            os.replace(p + ".part", p)
        out.append(p)
    return out


def embed(texts):
    """SigLIP's unit-length reading of each caption."""
    import onnxruntime as ort
    from tokenizers import Tokenizer
    model, tokenizer = fetch()
    tok = Tokenizer.from_file(tokenizer)
    s = ort.InferenceSession(model, providers=["CPUExecutionProvider"])
    out = []
    for t in texts:
        ids = tok.encode(t.lower()).ids[:MAX_TOKENS]
        ids = ids + [1] * (MAX_TOKENS - len(ids))
        v = s.run(["pooler_output"], {"input_ids": np.array([ids], np.int64)})[0][0]
        out.append(v / np.linalg.norm(v))
    return np.stack(out)


def directions(families):
    """(len(FAMILIES), WIDTH): each family's words, unit length, in SigLIP's space."""
    out = []
    for f in families:
        v = embed([t.format(w) for w in WORDS[f] for t in TEMPLATES]).mean(0)
        out.append(v / np.linalg.norm(v))
    return np.stack(out).astype(np.float32)


def likeness(E, T, weight):
    """The words' block of the colour head's input: each picture's SigLIP reading (E's first WIDTH numbers)
    against each family's words, WEIGHT times over."""
    return weight * (np.atleast_2d(E)[:, :WIDTH] @ T.T)
