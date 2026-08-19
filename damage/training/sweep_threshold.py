"""Measure what recall actually costs in precision, on the real test split.

WHY THIS IS NOT "TUNING THE THRESHOLD TO FIX RECALL"
----------------------------------------------------
RF-DETR's validation table already reports its F1 SWEEP — the F1, precision and
recall it printed are taken at the threshold that MAXIMISES F1, not at some
arbitrary default. So the run's Recall 0.5208 / Precision 0.6722 is already the
best-balanced point on the curve, and "tune the threshold" cannot conjure
recall out of it. Moving the threshold trades one for the other along a curve
that is already fixed by the weights.

What it can do — and what this measures — is let the product choose a point
that is not the F1 optimum, because F1 is the wrong objective here. F1 treats
a missed scratch and a false scratch as equally bad. For an insurance scan they
are not remotely equal: a missed scratch is a claim that gets disputed later,
a false one is thirty seconds of an assessor's time. The right operating point
is deliberately recall-heavy, and the only question is the exchange rate.

This prints that exchange rate, measured, so the choice is made from numbers
rather than from a preference.

WHAT IS COMPARED
----------------
Predictions come from the exported ONNX — the artefact that actually ships, not
the checkpoint — over the held-out TEST split, which no training or model
selection has touched. Matching is greedy by score at IoU 0.5, one prediction
per ground-truth box, which is the standard COCO convention for a single IoU.

    python sweep_threshold.py --model rfdetr-base.onnx --limit 800
"""
import argparse
import collections
import json
import os
import sys

THRESHOLDS = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40,
              0.50, 0.60, 0.70)
IOU_MATCH = 0.5


def iou(a, b):
    ax1, ay1, aw, ah = a
    bx1, by1, bw, bh = b
    ax2, ay2, bx2, by2 = ax1 + aw, ay1 + ah, bx1 + bw, by1 + bh
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    return inter / (aw * ah + bw * bh - inter)


def match(preds, gts, thr, iou_thr=IOU_MATCH):
    """(tp, fp, fn) for one image at one score threshold.

    Greedy by descending score, each ground-truth box claimable once. Class
    must agree: a dent found where a scratch is is not a hit, and counting it
    as one would flatter every number here.
    """
    kept = sorted([p for p in preds if p["score"] >= thr],
                  key=lambda p: -p["score"])
    used = [False] * len(gts)
    tp = 0
    for p in kept:
        best, bi = 0.0, -1
        for i, g in enumerate(gts):
            if used[i] or g["cls"] != p["cls"]:
                continue
            v = iou(p["box"], g["box"])
            if v > best:
                best, bi = v, i
        if bi >= 0 and best >= iou_thr:
            used[bi] = True
            tp += 1
    return tp, len(kept) - tp, len(gts) - tp


def run(index_dir, corpus, model, size, limit, split, out_json):
    import numpy as np
    import onnxruntime
    from PIL import Image
    sys.path.insert(0, os.path.join(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    from detect import parse_detections

    with open(os.path.join(index_dir, "classes.json")) as f:
        classes = json.load(f)
    idx_to_name = {int(k): v for k, v in classes["index_to_name"].items()}

    want = set()
    for ln in open(os.path.join(index_dir, "index.jsonl")):
        r = json.loads(ln)
        if r["split"] == split:
            want.add(r["sha"])
    gt = {}
    for ln in open(os.path.join(index_dir, "images.jsonl")):
        rec = json.loads(ln)
        if rec["sha"] in want:
            gt[rec["sha"]] = rec
    shas = sorted(gt)[:limit] if limit else sorted(gt)
    print(f"{split} split: {len(want):,} originals, evaluating {len(shas):,}")

    sess = onnxruntime.InferenceSession(
        model, providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0].name

    agg = {t: [0, 0, 0] for t in THRESHOLDS}
    per_class = {t: collections.defaultdict(lambda: [0, 0, 0])
                 for t in THRESHOLDS}
    done = 0
    for sha in shas:
        rec = gt[sha]
        path = os.path.join(corpus, rec["file"])
        if not os.path.exists(path):
            continue
        try:
            with Image.open(path) as im:
                im = im.convert("RGB")
                W, H = im.size
                arr = np.asarray(im.resize((size, size)),
                                 dtype=np.float32) / 255.0
            arr = np.transpose(arr, (2, 0, 1))[None, ...]
            outs = sess.run(None, {inp: arr})
        except Exception:
            continue
        # min_confidence 0 so every threshold is applied HERE, from one
        # inference pass, rather than re-running the model per threshold.
        dets = parse_detections(outs, (W, H), (size, size), None, 0.0)
        preds = []
        for d in dets:
            x1, y1, x2, y2 = d["box"]
            preds.append({"cls": int(float(d["label"])) if str(
                d["label"]).isdigit() else d["label"],
                "score": d["score"], "box": [x1, y1, x2 - x1, y2 - y1]})
        gts = [{"cls": b[0], "box": [b[1] * W, b[2] * H, b[3] * W, b[4] * H]}
               for b in rec["boxes"]]
        for t in THRESHOLDS:
            tp, fp, fn = match(preds, gts, t)
            agg[t][0] += tp
            agg[t][1] += fp
            agg[t][2] += fn
        done += 1
        if done % 100 == 0:
            print(f"  {done}/{len(shas)}", flush=True)

    print(f"\nevaluated {done:,} images at IoU {IOU_MATCH}\n")
    print(f"{'thresh':>7} {'precision':>10} {'recall':>8} {'F1':>7} "
          f"{'TP':>7} {'FP':>7} {'FN':>7}")
    rows = []
    for t in THRESHOLDS:
        tp, fp, fn = agg[t]
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        rows.append({"threshold": t, "precision": round(p, 4),
                     "recall": round(r, 4), "f1": round(f1, 4),
                     "tp": tp, "fp": fp, "fn": fn})
        print(f"{t:>7.2f} {p:>10.4f} {r:>8.4f} {f1:>7.4f} "
              f"{tp:>7,} {fp:>7,} {fn:>7,}")
    best = max(rows, key=lambda x: x["f1"])
    print(f"\nF1-optimal threshold: {best['threshold']:.2f} "
          f"(P {best['precision']:.3f} / R {best['recall']:.3f})")
    print("For an insurance scan the right point is BELOW this: a missed "
          "scratch is a disputed claim, a false one is thirty seconds of "
          "review.")
    if out_json:
        with open(out_json, "w") as f:
            json.dump({"iou": IOU_MATCH, "images": done,
                       "classes": idx_to_name, "rows": rows}, f, indent=1)
        print(f"wrote {out_json}")
    return 0


def _selftest():
    ok = fail = 0

    def check(name, cond, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"  ok   {name}")
        else:
            fail += 1
            print(f"  FAIL {name} {detail}")

    check("identical boxes have IoU 1", abs(iou([0, 0, 10, 10],
                                                [0, 0, 10, 10]) - 1) < 1e-9)
    check("disjoint boxes have IoU 0", iou([0, 0, 10, 10],
                                           [50, 50, 10, 10]) == 0.0)
    check("half-overlap is a third",
          abs(iou([0, 0, 10, 10], [5, 0, 10, 10]) - 1 / 3) < 1e-9)

    gts = [{"cls": 1, "box": [0, 0, 10, 10]}, {"cls": 2, "box": [50, 50, 10, 10]}]
    perfect = [{"cls": 1, "score": 0.9, "box": [0, 0, 10, 10]},
               {"cls": 2, "score": 0.8, "box": [50, 50, 10, 10]}]
    check("perfect predictions are all true positives",
          match(perfect, gts, 0.1) == (2, 0, 0))
    check("raising the threshold above every score yields all misses",
          match(perfect, gts, 0.95) == (0, 0, 2))

    # The class must agree — a dent on a scratch is not a hit.
    wrongcls = [{"cls": 2, "score": 0.9, "box": [0, 0, 10, 10]}]
    check("a right box with the wrong class is not a hit",
          match(wrongcls, [gts[0]], 0.1) == (0, 1, 1))

    # One ground truth cannot be claimed twice.
    dup = [{"cls": 1, "score": 0.9, "box": [0, 0, 10, 10]},
           {"cls": 1, "score": 0.8, "box": [0, 0, 10, 10]}]
    check("a duplicate prediction becomes a false positive",
          match(dup, [gts[0]], 0.1) == (1, 1, 0))

    # The higher-scoring prediction claims the box.
    two = [{"cls": 1, "score": 0.4, "box": [0, 0, 10, 10]},
           {"cls": 1, "score": 0.9, "box": [1, 1, 10, 10]}]
    tp, fp, fn = match(two, [gts[0]], 0.1)
    check("matching is greedy by score", (tp, fp, fn) == (1, 1, 0))

    # A loose box below the IoU floor misses.
    loose = [{"cls": 1, "score": 0.9, "box": [7, 7, 10, 10]}]
    check("a box below the IoU floor is a miss",
          match(loose, [gts[0]], 0.1) == (0, 1, 1))

    # Recall must be monotone non-increasing in the threshold.
    preds = [{"cls": 1, "score": s / 10, "box": [0, 0, 10, 10]}
             for s in range(1, 10)]
    rec = [match(preds, [gts[0]], t)[0] for t in (0.05, 0.3, 0.6, 0.95)]
    check("true positives never rise with the threshold",
          rec == sorted(rec, reverse=True), str(rec))

    print(f"\n{ok} passed, {fail} failed")
    return 1 if fail else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="/home/user/rf/idx6")
    ap.add_argument("--corpus", default="/home/user/rf/merged640")
    ap.add_argument("--model", default="/home/user/rfdetr-base.onnx")
    ap.add_argument("--size", type=int, default=560)
    ap.add_argument("--split", default="test")
    ap.add_argument("--limit", type=int, default=800)
    ap.add_argument("--out", default="/home/user/rf/threshold_sweep.json")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    return run(a.index, a.corpus, a.model, a.size, a.limit, a.split, a.out)


if __name__ == "__main__":
    sys.exit(main())
