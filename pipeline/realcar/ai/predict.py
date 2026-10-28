"""predict.py: the trained vehicle model, for the tool and for anyone's own code.

    python3 pipeline/realcar/ai/predict.py photo PHOTO [PHOTO ...]   # kind, side, colour of each
    python3 pipeline/realcar/ai/predict.py check PHOTO BUILD         # a build's picture against its photo
    python3 pipeline/realcar/ai/predict.py key KEY [KEY ...]         # the run's own photo and build ($F1K_HOME)
    python3 pipeline/realcar/ai/predict.py run [--out FILE]          # every build of the run: ai_review.json

Each prints JSON. From Python:

    from predict import VehicleAI
    ai = VehicleAI()
    ai.photo("car.jpg")             # {"kind": {...}, "side": {...}, "colour": {...}}
    ai.check("car.jpg", "build.png")

A check is a second opinion, not a verdict: it lists what looks wrong
("flags") and says "look" when there is any, "ok" when there is none. How far
each answer can be trusted is in heads.json's card (scores on vehicles the
model was not trained on) and in README.md.

Needs numpy, pillow and onnxruntime; the image encoder is fetched once
(about 350 MB, see vision.py).
"""
import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import heads as H  # noqa: E402
import vision  # noqa: E402

def _lab100(hex_):
    return H.lab([[int(hex_[i:i + 2], 16) for i in (1, 3, 5)]])[0] * np.array([100 / 255, 1, 1])


def next_shade(paint, a, b, limit=25.0):
    """Two families close enough to be one paint in another light (grey and dark grey, white and pearl)."""
    return a == b or float(np.linalg.norm(_lab100(paint[a]) - _lab100(paint[b]))) < limit


class VehicleAI:
    def __init__(self, heads=None, encoder=None):
        self.heads, self.card = H.load_heads(heads or os.path.join(HERE, "heads.json"))
        self.enc = vision.Encoder(encoder)
        self.th = self.card.get("thresholds", {})
        self.paint = self.card["paint"]           # each family's paint, as the review builds it

    def _read(self, path):
        im = vision.load(path)
        e, ef = self.enc.embed([im]), self.enc.embed([im], flip=True)
        return e[0], ef[0], H.colour_hist(im)

    def _answers(self, e, ef, h):
        def top(head, p, n=1):
            o = np.argsort(-p)[:n]
            return [[head.classes[i], round(float(p[i]), 3)] for i in o]
        kh, sh, ch = self.heads["kind"], self.heads["side"], self.heads["colour"]
        pk = kh.proba(e)[0]
        ps = H.side_proba(sh, e[None], ef[None])[0]
        pc = ch.proba(np.concatenate([e, h]))[0]
        (k, kp), (s, sp), (c, cp) = top(kh, pk)[0], top(sh, ps)[0], top(ch, pc)[0]
        return {"kind": {"answer": k, "p": kp}, "side": {"answer": s, "p": sp},
                "colour": {"answer": c, "p": cp, "paint": self.paint.get(c), "top3": top(ch, pc, 3)}}

    def photo(self, path):
        return {"file": path, **self._answers(*self._read(path))}

    def check(self, photo, build):
        P, B = self._read(photo), self._read(build)
        a, b = self._answers(*P), self._answers(*B)
        pm = float(self.heads["match"].proba(H.pair(P[0], B[0]))[0, 1])
        flags = []
        sure = self.th.get("sure", 0.6)
        if a["kind"]["answer"] != b["kind"]["answer"] and min(a["kind"]["p"], b["kind"]["p"]) >= sure:
            flags.append(f"kind: the photo shows a {a['kind']['answer']}, the build a {b['kind']['answer']}")
        if a["side"]["answer"] != b["side"]["answer"] and min(a["side"]["p"], b["side"]["p"]) >= 0.8:
            flags.append(f"side: the photo's vehicle points {a['side']['answer']}, the build {b['side']['answer']}")
        ca, cb = a["colour"]["answer"], b["colour"]["answer"]
        if not next_shade(self.paint, ca, cb) and min(a["colour"]["p"], b["colour"]["p"]) >= sure:
            flags.append(f"colour: the photo's paint reads {ca}, the build's {cb}")
        if pm < self.th.get("match", 0.5):
            flags.append(f"shape: the build may not be the photo's vehicle (match {pm:.2f})")
        return {"photo": a, "build": b, "match": round(pm, 3), "flags": flags, "answer": "look" if flags else "ok"}


def _run_paths(key):
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "review"))
    import paths
    return paths, paths.photo(key), paths.picture(key)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("what", choices=["photo", "check", "key", "run"])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--heads", default=None)
    ap.add_argument("--encoder", default=None, help="the encoder's .onnx (default: fetched once, see vision.py)")
    ap.add_argument("--out", default=None, help="run: where to write (default $F1K_HOME/ai_review.json)")
    a = ap.parse_args()
    ai = VehicleAI(a.heads, a.encoder)
    if a.what == "photo":
        out = [ai.photo(f) for f in a.files]
    elif a.what == "check":
        if len(a.files) != 2:
            raise SystemExit("check takes a photo and a build's picture")
        out = ai.check(*a.files)
    elif a.what == "key":
        out = {}
        for k in a.files:
            _, ph, pic = _run_paths(k)
            out[k] = ai.check(ph, pic) if ph and pic else {"error": "no photo or no build picture for " + k}
    else:
        paths, _, _ = _run_paths("")
        rows, _ = paths.rows()
        review = paths.load(paths.f("build_review.json"), {})
        out = {}
        for k, r in sorted(rows.items()):
            ph, pic = paths.photo(k), paths.picture(k)
            if r.get("status") in ("built", "standin") and ph and pic:
                out[k] = ai.check(ph, pic)
                out[k]["reviewers"] = (review.get(k) or {}).get("verdict")
        path = a.out or paths.f("ai_review.json")
        paths.save(path, out)
        look = sorted(k for k, v in out.items() if v["answer"] == "look")
        unsaid = [k for k in look if out[k]["reviewers"] == "ok"]
        print(json.dumps({"checked": len(out), "look": len(look), "look_where_reviewers_said_ok": unsaid,
                          "written": path}, indent=1))
        return
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
