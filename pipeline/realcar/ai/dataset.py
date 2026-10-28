"""dataset.py: the run's own answers, as training examples.

Everything is read from the review's data folder ($F1K_HOME, see
../review/README.md):

- colour: each car and van photo's paint family, named by the colour agents
  (paint_label.json); and each build's picture, in the colour it was built in
  (results.jsonl), so the colour model also reads builds
- side: the way each photo's car points (view_label.json), and every photo
  mirrored with the other side
- kind: car, van or motorbike, from the target list, for every photo and build
- match: each build beside its own photo; whether the build is of the photo's
  own model or a stand-in (another model's body reshaped to its size: the
  machine's own record, results.jsonl); the build reviews whose verdict is on
  that build and that photo (a verdict on a build since rebuilt is not used);
  and builds beside other vehicles' photos as the clear mismatches

An answer is only as good as the agents' and the hand checks behind it: the
labels are the run's, checked by gold items, not certain.
"""
import hashlib
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "review"))

import paths  # noqa: E402
from heads import lab100  # noqa: E402
from paint_label import FAMILY  # noqa: E402

KINDS = ["car", "van", "motorbike"]
SIDES = ["left", "right"]
# a fault that says the build is not the photo's vehicle (its shape)
SHAPE_FAULTS = {"body", "kind", "generation", "proportions"}


def nearest_family(hex_):
    """The family whose paint is nearest HEX (CIE76)."""
    want = lab100(hex_)
    return min(FAMILY, key=lambda k: float(np.linalg.norm(lab100(FAMILY[k]) - want)))


def fresh(verdict, row, photo):
    """A review's verdict only if it was made on this build (its built_at) and this photo (its fingerprint)."""
    v = verdict or {}
    return v if v.get("built_at") and v.get("built_at") == (row or {}).get("built_at") \
        and v.get("photo_sha") == paths.sha(photo) else None


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
            # the full studio picture, or its small copy once the full ones are pruned (webp.py):
            # both are read cropped to the vehicle (vision.load), so they read alike
            pic = paths.picture(k)
            if pic:
                it["build"] = pic
                # built from another model's body, reshaped to this one's size (the catalogue has none of its own)
                it["standin"] = r["status"] == "standin"
                if r.get("paint"):
                    # built in the paint read for the photo's named colour: that colour;
                    # else the family nearest the paint it wears
                    same = (paint.get(k) or {}).get("hex") == r["paint"] and it["colour"]
                    it["build_colour"] = it["colour"] if same else nearest_family(r["paint"])
                v = review.get(k) or {}
                if fresh(v, r, p):
                    it["verdict"] = v["verdict"]
                    it["faults"] = v.get("faults") or []
                # the last verdict named a shape fault, on this build or an earlier one (build_review.json
                # keeps one verdict a key): most rebuilds since changed its paint, roof or glass, not its
                # body, so it is not taken as a match
                it["shape_fault_last"] = bool(set(v.get("faults") or []) & SHAPE_FAULTS)
        out.append(it)
    return out


def fold(key, n=5):
    """The key's fold, 0 to N-1, from its own name only: a vehicle stays in its fold when others come and go."""
    return int(hashlib.sha1(key.encode()).hexdigest()[:8], 16) % n
