"""dataset.py: the run's own answers, as training examples.

Everything is read from the review's data folder ($F1K_HOME, see
../review/README.md):

- colour: each car and van photo's paint family, named by the colour agents
  (paint_label.json); and each build's picture, in the colour it was built in
  (results.jsonl), so the colour model also reads builds
- side: the way each photo's car points (view_label.json), and every photo
  mirrored with the other side
- kind: car, van or motorbike, from the target list, for every photo
- match: each build beside its own photo; whether the build is of the photo's
  own model or a stand-in (another model's body reshaped to its size: the
  machine's own record, results.jsonl); the build reviews whose verdict is on
  that build and that photo (a verdict on a build since rebuilt is not used);
  and builds beside other vehicles' photos as the clear mismatches

An answer is only as good as the agents' and the hand checks behind it: the
labels are the run's, checked by gold items, not certain.
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "review"))

import paths  # noqa: E402
from paint_label import FAMILY  # noqa: E402

KINDS = ["car", "van", "motorbike"]
SIDES = ["left", "right"]
# a fault that says the build is not the photo's vehicle (its shape)
SHAPE_FAULTS = {"body", "kind", "generation", "proportions"}


def _lab(hexes):
    rgb = np.array([[int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)] for h in hexes])
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    xyz = lin @ np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]]).T
    xyz /= np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], 1)


FAMILIES = list(FAMILY)
_FAM_LAB = _lab([FAMILY[k] for k in FAMILIES])


def nearest_family(hex_):
    d = np.linalg.norm(_FAM_LAB - _lab([hex_])[0], axis=1)
    return FAMILIES[int(d.argmin())]


def bike_photo(rank):
    p = paths.f("bike_photos", f"{rank}.jpg")
    return p if os.path.exists(p) else None


def items():
    """One dict a vehicle: key, kind, photo, build picture and every answer the run has on them."""
    rows, _ = paths.rows()
    targets = paths.load(paths.f("targets.json"), [])
    colour = paths.load(paths.f("paint_label.json"), {})
    side = paths.load(paths.f("view_label.json"), {})
    review = paths.load(paths.f("build_review.json"), {})
    paint = paths.load(paths.f("photo_paint.json"), {})
    out = []
    for t in targets:
        k, cls = t["key"], t["class"]
        if cls == "motorbike":
            p = bike_photo(t["rank"])
            if p:
                out.append({"key": k, "kind": cls, "photo": p})
            continue
        p = paths.photo(k)
        if not p:
            continue
        it = {"key": k, "kind": cls, "photo": p, "make": t.get("make"), "model": t.get("model"),
              "colour": colour.get(k), "side": side.get(k)}
        r = rows.get(k) or {}
        if r.get("status") in ("built", "standin"):
            pic = paths.picture(k)
            if pic and pic.endswith(".png"):
                it["build"] = pic
                # built from another model's body, reshaped to this one's size (the catalogue has none of its own)
                it["standin"] = r["status"] == "standin"
                if r.get("paint"):
                    # built in the paint read for the photo's named colour: that colour;
                    # else the family nearest the paint it wears
                    same = (paint.get(k) or {}).get("hex") == r["paint"] and it["colour"]
                    it["build_colour"] = it["colour"] if same else nearest_family(r["paint"])
                v = review.get(k) or {}
                if v.get("built_at") == r.get("built_at") and v.get("photo_sha") == paths.sha(p):
                    it["verdict"] = v["verdict"]
                    it["faults"] = v.get("faults") or []
                # a shape fault on an earlier build of it too: most rebuilds since changed its
                # paint, roof or glass, not its body, so it is not taken as a match
                it["shape_fault_ever"] = bool(set(v.get("faults") or []) & SHAPE_FAULTS)
        out.append(it)
    return out


def split(keys, test_share=0.2, seed=0):
    """Held-out keys, by a fixed draw: the same vehicles are held out on every run."""
    rng = np.random.default_rng(seed)
    keys = sorted(keys)
    pick = rng.permutation(len(keys))[:int(round(len(keys) * test_share))]
    return {keys[i] for i in pick}
