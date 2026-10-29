"""predict.py: the trained vehicle model, for the tool and for anyone's own code.

    python3 pipeline/realcar/ai/predict.py photo PHOTO [PHOTO ...]   # kind, side, colour of each
    python3 pipeline/realcar/ai/predict.py check PHOTO BUILD         # a build's picture against its photo
    python3 pipeline/realcar/ai/predict.py key KEY [KEY ...]         # the run's own photo and build ($F1K_HOME)
    python3 pipeline/realcar/ai/predict.py run [--out FILE]          # every build of the run: ai_review.json

Each prints JSON; a file it cannot read gets {"error": ...} and the rest go
on. From Python:

    from predict import VehicleAI
    ai = VehicleAI()
    ai.photo("car.jpg")             # {"kind": {...}, "side": {...}, "colour": {...}}
    ai.check("car.jpg", "build.png")

A check is a second opinion, not a verdict: it lists what looks wrong
("flags") and says "look" when there is any, "ok" when there is none. How far
each answer can be trusted is in heads.json's card (scores on vehicles the
model was not trained on) and in README.md.

`run` keeps the answers train.py left in ai_review.json, made by heads that
had not seen the vehicle, for every build and photo still the same; a build
or photo new since is checked by the heads in heads.json, which have not seen
it either. Each entry says which ("by").

Needs numpy, pillow and onnxruntime; the image encoder is fetched once
(about 350 MB, see vision.py).
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import heads as H  # noqa: E402
import vision  # noqa: E402


class VehicleAI:
    def __init__(self, heads=None, encoder=None):
        self.heads, self.card = H.load_heads(heads or os.path.join(HERE, "heads.json"))
        # the encoders the heads were trained on (the card's), unless told which files to use
        self.enc = vision.encoders(encoder or ",".join(e["name"] for e in self.card.get("encoders", [])))
        self.th = self.card["thresholds"]
        self.paint = self.card["paint"]           # each family's paint, as the review builds it

    def features(self, path):
        im = vision.load(path)
        return self.enc.embed([im])[0], self.enc.embed([im], flip=True)[0], H.colour_hist(im)

    def photo(self, path):
        return {"file": path, **H.read(self.heads, self.paint, self.features(path))}

    def check(self, photo, build):
        return H.judge(self.heads, self.th, self.paint, self.features(photo), self.features(build))


def safe(fn, *files):
    """FN's answer on FILES, or what stopped it: one bad file is reported, not a stop to the rest."""
    try:
        return fn(*files)
    except vision.Unreadable as e:
        return {"file": files[0] if len(files) == 1 else list(files), "error": str(e)}


def _review_paths():
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "review"))
        import dataset
        return dataset
    except ImportError as e:
        raise SystemExit(f"key and run read the run's data folder ($F1K_HOME) with the repository's "
                         f"pipeline/realcar/review and its packages ({e}); photo and check need neither") from None


def run(ai, out_path=None):
    """Every build of the run against its photo: held-out answers kept, the rest checked; written to OUT_PATH."""
    dataset = _review_paths()
    paths = dataset.paths
    rows, _ = paths.rows()
    review = paths.load(paths.f("build_review.json"), {})
    path = out_path or paths.f("ai_review.json")
    old = paths.load(path, {})
    out = {}
    for k, r in sorted(rows.items()):
        ph, pic = paths.photo(k), paths.picture(k)
        if r.get("status") not in ("built", "standin") or not ph or not pic:
            continue
        sha_p, sha_b = paths.sha(ph), paths.sha(pic)
        v = old.get(k) or {}
        if v.get("heads") == ai.card["trained"] and v.get("photo_sha") == sha_p and v.get("build_sha") == sha_b:
            out[k] = v
        else:
            out[k] = {**safe(ai.check, ph, pic), "photo_sha": sha_p, "build_sha": sha_b, "heads": ai.card["trained"],
                      "by": "heads in heads.json (this build or photo is newer than their training)"}
        fresh = dataset.fresh(review.get(k), r, ph)
        out[k]["reviewers"] = fresh["verdict"] if fresh else None
    paths.save(path, out)
    look = sorted(k for k, v in out.items() if v.get("answer") == "look")
    return {"checked": len(out), "look": len(look), "unreadable": sorted(k for k, v in out.items() if "error" in v),
            "look_where_reviewers_passed_this_build": [k for k in look if out[k]["reviewers"] == "ok"],
            "written": path}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("what", choices=["photo", "check", "key", "run"])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--heads", default=None)
    ap.add_argument("--encoder", default=None, help="the encoders' .onnx files or names, comma-separated (default: "
                    "the card's, fetched once; see vision.py)")
    ap.add_argument("--out", default=None, help="run: where to write (default $F1K_HOME/ai_review.json)")
    a = ap.parse_args()
    if a.what == "check" and len(a.files) != 2:
        raise SystemExit("check takes a photo and a build's picture")
    ai = VehicleAI(a.heads, a.encoder)
    if a.what == "photo":
        out = [safe(ai.photo, f) for f in a.files]
    elif a.what == "check":
        out = safe(ai.check, *a.files)
    elif a.what == "key":
        paths = _review_paths().paths
        out = {}
        for k in a.files:
            ph, pic = paths.photo(k), paths.picture(k)
            out[k] = safe(ai.check, ph, pic) if ph and pic else {"error": "no photo or no build picture for " + k}
    else:
        out = run(ai, a.out)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
