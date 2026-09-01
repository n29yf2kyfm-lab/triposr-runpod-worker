"""Score a detector on the corpus's own held-out test split.

WHY THIS EXISTS WHEN eval_external.py ALREADY DOES

eval_external scores against the ECC set: 814 photos, a different annotator,
a different labelling convention. It is the right yardstick for "does this
work on real photos", and its limitation is that it is small and its class
vocabulary only approximately maps onto ours.

This scores against the corpus's OWN test split -- 16,992 images, our own six
classes, no vocabulary mapping -- which makes it the clean measure of "did the
model learn what it was taught". It became meaningful only on 2026-09-01: until
then 13.1% of the test split was near-copies of training images, so this
number would have been partly a memory test. idx16 onward is leak-free
(verified by leak_audit against pHash clusters), and this tool refuses to run
on an index that has no such verification recorded, because a number from a
leaky split is worse than no number.

WHAT IT MEASURES

Class-aware greedy matching at IoU 0.5, highest-score-first, each truth box
consumed once -- identical to eval_external and compare_models, so the two
scores are comparable in kind even though the sets differ. Predictions come
through detect.parse_detections with its SHIPPED defaults: per-class
confidence floors and NMS, so what is scored is what a user of the worker
would actually see.
"""
import argparse
import collections
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import detect as DET                     # noqa: E402


def iou(a, b):
    """IoU of two [x, y, w, h] boxes."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    return inter / (aw * ah + bw * bh - inter)


def match(preds, truths, t_iou=0.5):
    """Greedy highest-score-first. Returns (tp, fp, fn, per_class_counts)."""
    used = set()
    tp = fp = 0
    said = collections.Counter()
    right = collections.Counter()
    found = collections.Counter()
    for p in sorted(preds, key=lambda q: -q["score"]):
        said[p["cls"]] += 1
        best, bi = 0.0, -1
        for i, t in enumerate(truths):
            if i in used or t["cls"] != p["cls"]:
                continue
            v = iou(p["box"], t["box"])
            if v > best:
                best, bi = v, i
        if best >= t_iou:
            used.add(bi)
            tp += 1
            right[p["cls"]] += 1
            found[truths[bi]["cls"]] += 1
        else:
            fp += 1
    fn = len(truths) - len(used)
    return tp, fp, fn, said, right, found


def load_split(index_dir, split):
    rows = []
    with open(os.path.join(index_dir, "images.jsonl")) as f:
        for line in f:
            r = json.loads(line)
            if r["split"] == split:
                rows.append(r)
    return rows


def truths_of(row, names):
    """Index boxes are [cls_id, x, y, w, h] normalised -> pixel xywh."""
    W, H = row["width"], row["height"]
    out = []
    for b in row.get("boxes") or []:
        out.append({"cls": names[int(b[0])],
                    "box": [b[1] * W, b[2] * H, b[3] * W, b[4] * H]})
    return out


def run_model(model_path, rows, corpus, labels, limit=None, log_every=500):
    import onnxruntime
    from PIL import Image
    sess = onnxruntime.InferenceSession(model_path,
                                        providers=["CPUExecutionProvider"])
    shp = sess.get_inputs()[0].shape
    size = shp[2] if isinstance(shp[2], int) else 560
    inp = sess.get_inputs()[0].name
    preds = {}
    t0 = time.time()
    for n, r in enumerate(rows[:limit] if limit else rows):
        path = os.path.join(corpus, r["file"])
        if not os.path.exists(path):
            continue
        with Image.open(path) as im:
            im = im.convert("RGB")
            W, H = im.size
            arr = np.asarray(im.resize((size, size)), dtype=np.float32) / 255.0
        arr = np.transpose(arr, (2, 0, 1))[None, ...]
        outs = sess.run(None, {inp: arr})
        # min_confidence=None -> the SHIPPED per-class floors and NMS apply
        dets = DET.parse_detections(outs, (W, H), (size, size), labels, None)
        preds[r["sha"]] = [{"cls": d["label"], "score": d["score"],
                            "box": [d["box"][0], d["box"][1],
                                    d["box"][2] - d["box"][0],
                                    d["box"][3] - d["box"][1]]}
                           for d in dets]
        if (n + 1) % log_every == 0:
            el = time.time() - t0
            print(f"  {n+1:,}/{len(rows):,}  {el/60:.1f} min  "
                  f"eta {el/(n+1)*(len(rows)-n-1)/60:.0f} min", flush=True)
    return preds


def score(preds, rows, names):
    TP = FP = FN = 0
    said = collections.Counter()
    right = collections.Counter()
    found = collections.Counter()
    truth_n = collections.Counter()
    img_hit = img_n = 0
    for r in rows:
        if r["sha"] not in preds:
            continue
        truths = truths_of(r, names)
        for t in truths:
            truth_n[t["cls"]] += 1
        tp, fp, fn, s, rt, fd = match(preds[r["sha"]], truths)
        TP += tp
        FP += fp
        FN += fn
        said.update(s)
        right.update(rt)
        found.update(fd)
        if truths:
            img_n += 1
            img_hit += tp > 0
    P = TP / max(1, TP + FP)
    R = TP / max(1, TP + FN)
    return {"tp": TP, "fp": FP, "fn": FN, "precision": P, "recall": R,
            "f1": 2 * P * R / max(1e-9, P + R),
            "per_image": img_hit / max(1, img_n), "images": img_n,
            "said": said, "right": right, "found": found, "truth": truth_n}


def report(s, tag):
    print(f"\n{'=' * 66}\n{tag}\n{'=' * 66}")
    print(f"  images {s['images']:,}   truth boxes {sum(s['truth'].values()):,}"
          f"   predictions {s['tp'] + s['fp']:,}")
    print(f"  precision {s['precision']*100:5.1f}%   recall {s['recall']*100:5.1f}%"
          f"   F1 {s['f1']*100:5.1f}%   per-image {s['per_image']*100:5.1f}%")
    print(f"\n  {'class':16}{'truth':>8}{'found':>8}{'recall':>9}"
          f"{'said':>8}{'right':>8}{'prec':>9}")
    for c in sorted(s["truth"], key=lambda k: -s["truth"][k]):
        t, f = s["truth"][c], s["found"][c]
        sd, rt = s["said"][c], s["right"][c]
        print(f"  {c:16}{t:8,}{f:8,}{f/max(1,t)*100:8.1f}%"
              f"{sd:8,}{rt:8,}{rt/max(1,sd)*100:8.1f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--index", required=True)
    ap.add_argument("--corpus", default="/home/user/rf/merged640")
    ap.add_argument("--split", default="test")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--cache", help="write/read predictions here (pkl)")
    ap.add_argument("--allow-unverified", action="store_true",
                    help="score even if no leak verification is recorded")
    a = ap.parse_args()

    # Refuse a leaky split. A number from one is worse than none.
    marker = os.path.join(a.index, "leak_verified.json")
    if not os.path.exists(marker) and not a.allow_unverified:
        sys.exit(f"{a.index} has no leak_verified.json. Run leak_audit on it "
                 f"and record the result, or pass --allow-unverified and "
                 f"treat the number as suspect.")

    names = {int(k): v for k, v in
             json.load(open(os.path.join(a.index, "classes.json")))
             ["index_to_name"].items()}
    rows = load_split(a.index, a.split)
    print(f"{len(rows):,} {a.split} images in {a.index}")

    import pickle
    if a.cache and os.path.exists(a.cache):
        preds = pickle.load(open(a.cache, "rb"))
        print(f"loaded {len(preds):,} cached predictions")
    else:
        labels = DET._labels_beside_model(a.model)
        if not labels:
            sys.exit(f"no classes.json beside {a.model}")
        print(f"model {a.model}\nclasses {labels}")
        preds = run_model(a.model, rows, a.corpus, labels, a.limit)
        if a.cache:
            pickle.dump(preds, open(a.cache, "wb"))
            print(f"cached {len(preds):,} predictions -> {a.cache}")

    s = score(preds, rows, names)
    report(s, f"{os.path.basename(a.model)} on {a.index} {a.split} "
              f"(class-aware, IoU 0.5, shipped floors + NMS)")


def _selftest():
    names = {1: "a", 2: "b"}
    row = {"sha": "x", "width": 100, "height": 100,
           "boxes": [[1, 0.1, 0.1, 0.2, 0.2], [2, 0.6, 0.6, 0.2, 0.2]]}
    T = truths_of(row, names)
    assert T[0]["box"] == [10.0, 10.0, 20.0, 20.0], T[0]
    # exact hit, right class
    tp, fp, fn, *_ = match([{"cls": "a", "score": .9, "box": [10, 10, 20, 20]}], T)
    assert (tp, fp, fn) == (1, 0, 1), (tp, fp, fn)
    # right place, wrong class -> not a hit
    tp, fp, fn, *_ = match([{"cls": "b", "score": .9, "box": [10, 10, 20, 20]}], T)
    assert (tp, fp, fn) == (0, 1, 2), (tp, fp, fn)
    # each truth consumed once: two predictions on one box -> 1 tp 1 fp
    tp, fp, fn, *_ = match([{"cls": "a", "score": .9, "box": [10, 10, 20, 20]},
                            {"cls": "a", "score": .5, "box": [11, 11, 20, 20]}], T)
    assert (tp, fp, fn) == (1, 1, 1), (tp, fp, fn)
    # scoring aggregates and per-image is right
    s = score({"x": [{"cls": "a", "score": .9, "box": [10, 10, 20, 20]}]},
              [row], names)
    assert s["tp"] == 1 and s["per_image"] == 1.0 and s["found"]["a"] == 1
    print("eval_internal_test selftests passed")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
