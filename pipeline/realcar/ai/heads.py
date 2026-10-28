"""heads.py: the trained part: small models on the encoder's numbers.

- colour: the paint family of a photo or a build (29 families), from the
  embedding and a colour histogram of the picture's middle
- side: the way the vehicle points (left, right), from the embedding, read on
  the picture and on its mirror image (so a mirrored picture always reads the
  other way)
- kind: car, van or motorbike
- match: whether a build is the photo's vehicle (its shape, not its paint),
  from the two embeddings

Each head is a logistic regression (sklearn to train; numpy to run). Its
weights are kept in heads.json, which any language can read: a score is
x @ W.T + b, then a softmax (or, for one row, a sigmoid).
"""
import json

import numpy as np
from PIL import Image

from vision import load

HIST_BINS = (8, 6, 6)


def lab(rgb):
    """sRGB 0-255 (n, 3) to CIE Lab (D65), as OpenCV's 8-bit Lab: L 0-255, a and b offset by 128."""
    c = np.asarray(rgb, np.float64) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    xyz = lin @ np.array([[0.412453, 0.357580, 0.180423], [0.212671, 0.715160, 0.072169],
                          [0.019334, 0.119193, 0.950227]]).T
    xyz /= np.array([0.950456, 1.0, 1.088754])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    L = np.where(xyz[:, 1] > 0.008856, 116 * f[:, 1] - 16, 903.3 * xyz[:, 1])
    return np.stack([L * 255 / 100, 500 * (f[:, 0] - f[:, 1]) + 128, 200 * (f[:, 1] - f[:, 2]) + 128], 1)


def colour_hist(im, mid=0.6):
    """The middle of the picture (where the vehicle is), as a Lab histogram, square-rooted."""
    a = np.asarray(im.resize((160, 100), Image.BILINEAR))
    h, w = a.shape[:2]
    y0, x0 = int(h * (1 - mid) / 2), int(w * (1 - mid) / 2)
    px = lab(a[y0:h - y0, x0:w - x0].reshape(-1, 3))
    H, _ = np.histogramdd(px, bins=HIST_BINS, range=((0, 256), (64, 192), (64, 192)))
    return np.sqrt(H.ravel() / max(H.sum(), 1)).astype(np.float32)


def pair(p, b):
    """A photo's embedding and a build's, as one row for the match head."""
    return np.concatenate([p * b, np.abs(p - b)], axis=-1)


def _softmax(z):
    z = z - z.max(axis=-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)


class Head:
    def __init__(self, classes, W, b):
        self.classes = list(classes)
        self.W = np.asarray(W, np.float32)
        self.b = np.asarray(b, np.float32)

    @classmethod
    def fit(cls, X, y, C=100.0, sample_weight=None, **kw):
        from sklearn.linear_model import LogisticRegression
        m = LogisticRegression(C=C, max_iter=20000, **kw).fit(X, y, sample_weight=sample_weight)
        return cls(m.classes_.tolist(), m.coef_, m.intercept_)

    def proba(self, X):
        z = np.atleast_2d(X) @ self.W.T + self.b
        if len(self.classes) == 2 and self.W.shape[0] == 1:
            p1 = 1 / (1 + np.exp(-z[:, 0]))
            return np.stack([1 - p1, p1], 1)
        return _softmax(z)

    def to_json(self):
        return {"classes": self.classes, "W": np.round(self.W, 6).tolist(), "b": np.round(self.b, 6).tolist()}

    @classmethod
    def from_json(cls, d):
        return cls(d["classes"], d["W"], d["b"])


def side_proba(head, e, ef):
    """Left/right from a picture's embedding and its mirror's: the two readings averaged, the mirror's swapped."""
    p, pf = head.proba(e), head.proba(ef)
    return (p + pf[:, ::-1]) / 2


def save(path, heads, card):
    with open(path, "w") as fh:
        json.dump({"card": card, "heads": {k: h.to_json() for k, h in heads.items()}}, fh, separators=(",", ":"))


def load_heads(path):
    d = json.load(open(path))
    return {k: Head.from_json(v) for k, v in d["heads"].items()}, d["card"]


def features(enc, paths_):
    """Embedding, mirrored embedding and colour histogram of each picture file."""
    ims = [load(p) for p in paths_]
    return enc.embed(ims), enc.embed(ims, flip=True), np.stack([colour_hist(im) for im in ims])
