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
    """One dict a vehicle: key, kind, photo, build picture and every answer the run has on them. The kind is what
    the photo shows (kind_by_eye.json: a panel van the target list registers as a car is a van here);
    registered_kind is the list's. A build of the other kind than its photo (the same file) is not a kind example."""
    rows, _ = paths.rows()
    targets = paths.load(paths.f("targets.json"), [])
    eye = paths.load(os.path.join(HERE, "kind_by_eye.json"), {})
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
        it = {"key": k, "kind": eye.get("kind", {}).get(k, cls), "registered_kind": cls, "photo": p,
              "make": t.get("make"), "model": t.get("model"), "colour": colour.get(k), "side": side.get(k),
              "build_other_kind": k in eye.get("build_is_other_kind", {})}
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


# photos from outside the run, by a coarse colour (Wikimedia Commons' categories, extra/harvest.py): the run's
# families each may be. The fine family is the model's own best guess within the group (train.py)
GROUPS = {
    "Red": ["red", "dark-red"], "White": ["white", "pearl-white"], "Blue": ["blue", "dark-blue", "light-blue", "grey-blue"],
    "Black": ["black"], "Silver": ["silver"], "Gray": ["grey", "dark-grey"], "Grey": ["grey", "dark-grey"],
    "Green": ["green", "dark-green", "light-green", "grey-green", "sage", "olive"], "Yellow": ["yellow"],
    "Orange": ["orange", "copper"], "Beige": ["beige", "champagne", "taupe"], "Brown": ["brown", "bronze", "taupe"],
    "Purple": ["purple", "lilac"], "Gold": ["gold", "champagne"], "Pink": ["lilac"],
}


def extra_items(folders, min_side=200):
    """Photos from outside the run (FOLDERS, comma-separated, each with files.jsonl, img/, qa.json: see extra/), as items with a
    kind, a coarse colour group and its FAMILIES (None when the picture's paint belies its colour word), a licence
    and an author; no build, side or fine colour.
    Only pictures qa.py kept (an exterior view of one vehicle). Each picture's licence and author are in
    attrib.json once attrib.py has fetched them (Commons hosts free content only; "pending" until then)."""
    import json
    if "," in folders:
        return [it for f in folders.split(",") if f for it in extra_items(f, min_side)]
    folder = folders
    qa = paths.load(os.path.join(folder, "qa.json"), {})
    attrib = paths.load(os.path.join(folder, "attrib.json"), {})
    out = []
    with open(os.path.join(folder, "files.jsonl")) as fh:
        for line in fh:
            r = json.loads(line)
            p = os.path.join(folder, "img", f"{r['id']}.jpg")
            q = qa.get(str(r["id"]))
            if not os.path.exists(p) or not q or not q.get("keep") or r["colour"] not in GROUPS:
                continue
            if (r.get("w") or 0) < min_side or (r.get("h") or 0) < min_side:
                continue
            a = attrib.get(r["id"]) or {}
            # a colour word its picture does not bear out (qa.py's paint check) is not a colour example
            paint_ok = q.get("paint_ok", True)
            out.append({"key": f"extra-{r['id']}", "kind": r["kind"], "photo": p, "group": r["colour"] if paint_ok else None,
                        "families": GROUPS[r["colour"]] if paint_ok else None,
                        "licence": a.get("licence") or r.get("licence") or "pending",
                        "author": a.get("author") or r.get("author"), "page": r.get("page"), "title": r["title"],
                        "source": os.path.basename(os.path.normpath(folder)), "extra": True})
    return out


def fold(key, n=5):
    """The key's own fold, 0 to N-1, from its name only."""
    return int(hashlib.sha1(key.encode()).hexdigest()[:8], 16) % n


SAME_PHOTO_BITS = 10        # photos this near (of 256 bits, vision.dhash) are one photo saved twice


def folds(its, n=5, looks=None):
    """Each vehicle's fold. Vehicles that share a picture (the same file, or photos LOOKS, key -> dhash, finds
    within SAME_PHOTO_BITS: one photo resized) are one group and share a fold: no picture is answered by
    heads trained on it (88 pictures are shared, by twins and a van's car version). A group's fold is its
    first key's, so a vehicle keeps its fold unless one sharing its picture comes."""
    parent = {it["key"]: it["key"] for it in its}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    first = {}
    for it in its:
        for s in ("photo", "build"):
            if it.get(s):
                h = paths.sha(it[s])
                if h in first:
                    parent[find(it["key"])] = find(first[h])
                first.setdefault(h, it["key"])
    if looks:
        ks = sorted(k for k in looks if k in parent)
        bits = np.unpackbits(np.array([list(bytes.fromhex(looks[k])) for k in ks], np.uint8), axis=1).astype(np.float32)
        # the bits that differ between every two: a@(1-b) + (1-a)@b
        near = bits @ (1 - bits).T + (1 - bits) @ bits.T <= SAME_PHOTO_BITS
        for i, j in zip(*np.nonzero(np.triu(near, 1))):
            parent[find(ks[i])] = find(ks[j])
    groups = {}
    for it in sorted(its, key=lambda x: x["key"]):
        groups.setdefault(find(it["key"]), it["key"])
    return {it["key"]: fold(groups[find(it["key"])], n) for it in its}
