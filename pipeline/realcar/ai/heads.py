"""heads.py: the trained part: small models on the encoder's numbers, and the rules that read them.

- colour: the paint family of a photo or a build (the review's families),
  from the embedding and a colour histogram of the picture's middle
- side: the way the vehicle points (left, right), from the embedding, read on
  the picture and on its mirror image (so a mirrored picture always reads the
  other way)
- kind: car, van or motorbike
- vehicle: whether there is a vehicle in the picture at all (taught on photos
  of landscapes, animals, food, rooms, people and drawn noise: extra/none.py),
  so a picture of none is not read as a car
- match: whether a build is the photo's vehicle (its shape, not its paint),
  from the two embeddings; a stand-in (another model's body reshaped to the
  photo's car) is held to the stand-ins' own threshold, as it is never quite
  its photo

Each head is a logistic regression (sklearn to train; numpy to run). Its
weights are kept in heads.json, which any language can read: a score is
x @ W.T + b, then a softmax (or, for one row, a sigmoid).
"""
import colorsys
import json

import numpy as np
from PIL import Image

from vision import load

# what a picture's features are made of: the encoder's reading of vision.prep's square (a cut-out
# cropped to its vehicle, vision.load) and colour_hist below. Changed, the training cache is read anew.
FEATURES_VERSION = 3
# a and b in an odd number of bins: a neutral (white, grey, black: a = b = 128) falls in the middle of
# one, not on the edge between two, where the last digit of the arithmetic picked the bin (6 bins did:
# a white car's and a studio background's whites split between two bins by rounding, machine by machine)
HIST_BINS = (8, 7, 7)
HIST_RANGE = ((0, 256), (64, 192), (64, 192))


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


def lab100(hex_):
    """A paint '#rrggbb' as CIE Lab in its own units (L 0-100)."""
    v = lab([[int(hex_[i:i + 2], 16) for i in (1, 3, 5)]])[0]
    return np.array([v[0] * 100 / 255, v[1] - 128, v[2] - 128])


# the paints from white to black: one another's next shade, never a colour's
NEUTRAL = ("white", "pearl-white", "silver", "grey", "dark-grey", "black")


def shade_group(paint, a):
    """A family's group: the neutrals as one, the rest by their paint's hue (reds and yellows, greens, blues)."""
    if a in NEUTRAL:
        return "neutral"
    h = colorsys.rgb_to_hls(*(int(paint[a][i:i + 2], 16) / 255 for i in (1, 3, 5)))[0]
    return "reds" if h < 0.19 or h > 0.92 else "greens" if h < 0.47 else "blues"


# a paint darker than this (Lab L) is a dark one: black, dark blue and dark green are one another's next
# shade in a photo (looked at, the run's "mistakes" between them are mostly a toss-up)
DARK_L = 32.0


def next_shade(paint, a, b, limit=25.0):
    """Two families close enough to be one paint in another light (grey and dark grey, white and pearl,
    black and dark blue): their paints (PAINT, family -> '#rrggbb') within LIMIT of each other (CIE76),
    and in one group (shade_group: a pale aqua is near white, but a colour) or both dark (DARK_L)."""
    if a == b:
        return True
    la, lb = lab100(paint[a]), lab100(paint[b])
    alike = shade_group(paint, a) == shade_group(paint, b) or (la[0] < DARK_L and lb[0] < DARK_L)
    return alike and float(np.linalg.norm(la - lb)) < limit


def colour_hist(im, mid=0.6):
    """The middle of the picture (where the vehicle is), as a Lab histogram, square-rooted. Colours past
    the outer bins (a strong yellow, red or blue) are counted in the outer bins, not left out."""
    a = np.asarray(im.resize((160, 100), Image.BILINEAR))
    h, w = a.shape[:2]
    y0, x0 = int(h * (1 - mid) / 2), int(w * (1 - mid) / 2)
    px = lab(a[y0:h - y0, x0:w - x0].reshape(-1, 3))
    for i, (lo, hi) in enumerate(HIST_RANGE):
        px[:, i] = np.clip(px[:, i], lo, hi - 1e-6)
    H, _ = np.histogramdd(px, bins=HIST_BINS, range=HIST_RANGE)
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


def fold_words(head, T, weight):
    """HEAD, fitted on [embedding, histogram, words.likeness(embedding, T, WEIGHT)], as a head on [embedding,
    histogram] that answers the same: the likeness is the embedding's first numbers times WEIGHT * T, so its
    weights fold into theirs."""
    n, width = T.shape
    W = head.W[:, :-n].astype(np.float64)
    W[:, :width] += weight * head.W[:, -n:].astype(np.float64) @ T
    return Head(head.classes, W, head.b)


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


def read(hs, paint, f):
    """The answers on one picture's features F = (embedding, mirrored embedding, histogram): whether there is a
    vehicle in it ("yes", "no"), and its kind, side and colour (read whatever the first says: with no vehicle in
    the picture they are guesses)."""
    e, ef, h = f

    def top(head, p, n):
        return [[head.classes[i], round(float(p[i]), 3)] for i in np.argsort(-p)[:n]]
    kh, sh, ch = hs["kind"], hs["side"], hs["colour"]
    (k, kp), = top(kh, kh.proba(e)[0], 1)
    (s, sp), = top(sh, side_proba(sh, e[None], ef[None])[0], 1)
    c3 = top(ch, ch.proba(np.concatenate([e, h]))[0], 3)
    out = {}
    if "vehicle" in hs:                       # heads trained before it have no vehicle head
        (v, vp), = top(hs["vehicle"], hs["vehicle"].proba(e)[0], 1)
        out["vehicle"] = {"answer": "yes" if v == "vehicle" else "no", "p": vp}
    return {**out, "kind": {"answer": k, "p": kp}, "side": {"answer": s, "p": sp},
            "colour": {"answer": c3[0][0], "p": c3[0][1], "paint": paint.get(c3[0][0]), "top3": c3}}


def no_vehicle(r, th):
    """A reading (read's) that there is no vehicle in the picture, at least as sure as TH's vehicle threshold."""
    v = r.get("vehicle")
    return bool(v) and v["answer"] == "no" and v["p"] >= th.get("vehicle", 0.5)


def judge(hs, th, paint, P, B, standin=False):
    """A build's picture against its photo's, from their features: both pictures' answers, the match,
    and what looks wrong. An answer only counts against the build when both readings are at least as
    sure as TH says (each head's threshold: photos read that surely were right 99 times in 100, held out).
    STANDIN: the build is another model's body reshaped to the photo's car (the machine knows which builds
    are): its match is held to the stand-ins' threshold, the score below which one good stand-in in ten falls,
    where a build of the photo's own model is held to its own (one in ten of those)."""
    a, b = read(hs, paint, P), read(hs, paint, B)
    pm = float(hs["match"].proba(pair(P[0], B[0]))[0, 1])
    sure = lambda what: min(a[what]["p"], b[what]["p"]) >= th[what]  # noqa: E731
    flags = [f"{w}: no vehicle in the {w}'s picture" for w, r in (("photo", a), ("build", b)) if no_vehicle(r, th)]
    if flags:                                  # nothing else to compare
        return {"photo": a, "build": b, "match": round(pm, 3), "flags": flags, "answer": "look"}
    if a["kind"]["answer"] != b["kind"]["answer"] and sure("kind"):
        flags.append(f"kind: the photo shows a {a['kind']['answer']}, the build a {b['kind']['answer']}")
    if a["side"]["answer"] != b["side"]["answer"] and sure("side"):
        flags.append(f"side: the photo's vehicle points {a['side']['answer']}, the build {b['side']['answer']}")
    if not next_shade(paint, a["colour"]["answer"], b["colour"]["answer"]) and sure("colour"):
        flags.append(f"colour: the photo's paint reads {a['colour']['answer']}, the build's {b['colour']['answer']}")
    if standin and pm < th.get("match_standin", th["match"]):
        flags.append(f"shape: a poorer stand-in than nine in ten good ones (match {pm:.2f})")
    elif not standin and pm < th["match"]:
        flags.append(f"shape: the build may not be the photo's vehicle (match {pm:.2f})")
    return {"photo": a, "build": b, "match": round(pm, 3), "flags": flags, "answer": "look" if flags else "ok"}
