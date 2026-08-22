"""Score the shipped ONNX against an INDEPENDENT, externally-labelled test set.

WHY THIS IS THE ONLY HONEST NUMBER SO FAR
-----------------------------------------
Every figure this project has reported came from its own corpus and its own
labels — labels that, on inspection, included boxes drawn on burned-in caption
text. A model measured on the labels it trained against is graded by its own
teacher. The ECC set is different: different photographers, different
annotators, a taxonomy chosen without reference to ours, and no overlap with
anything used for training.

TWO LEVELS, BECAUSE THE TAXONOMIES DO NOT MATCH
-----------------------------------------------
ECC has eight classes and this detector has six, and the mapping is genuinely
lossy in places. Reporting only a mapped per-class score would blame the model
for a disagreement about vocabulary; reporting only class-agnostic would hide
real confusion. So both are printed:

  CLASS-AGNOSTIC   Is there damage here, roughly in the right place? This is
                   the question a customer actually asks, and it is invariant
                   to how the two label sets carve up the space.

  MAPPED CLASSES   Only for the pairs that map cleanly, plus a confusion table
                   so the disagreements are visible rather than averaged away.

THE MAPPING, AND WHERE IT IS UNFAIR TO THE MODEL
------------------------------------------------
    scratch_scuff      -> scratch_scuff     exact
    dent               -> dent              exact
    cracked_component  -> crack_glass       close
    corrosion          -> rust_paint        close
    paint_flaking      -> rust_paint        close
    paint_chip         -> rust_paint        close-ish: our rust_paint is
                                            corrosion + paint failure, and
                                            ECC splits chip from flaking
    missing_part       -> structural        loose
    broken_part        -> AMBIGUOUS. In ECC this covers broken lamps, broken
                        glass and broken bumpers, which we split across
                        crack_glass, lamp_wheel and structural. Any single
                        choice is wrong for two thirds of it, so it is scored
                        as a match against ANY of the three rather than
                        silently assigned to one.

IoU 0.5 only. This detector's per-class AP is depressed at the strict end by
box SHAPE (see audit_labels), which is a property of thin damage rather than of
the model, and stacking that on top of a taxonomy mismatch would measure
neither thing clearly.

    python eval_external.py --root /home/user/ecc/ECC_..._part_1_of_3
"""
import argparse
import collections
import json
import os
import sys

IOU_MATCH = 0.5

# ECC class -> the set of our classes that legitimately satisfy it.
ECC_TO_OURS = {
    "scratch_scuff": {"scratch_scuff"},
    "dent": {"dent"},
    "cracked_component": {"crack_glass"},
    "corrosion": {"rust_paint"},
    "paint_flaking": {"rust_paint"},
    "paint_chip": {"rust_paint"},
    "missing_part": {"structural"},
    # see the docstring: one ECC label spanning three of ours
    "broken_part": {"crack_glass", "lamp_wheel", "structural"},
}


def iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    return inter / (aw * ah + bw * bh - inter)


def match(preds, gts, class_aware):
    """Greedy by score. Returns (tp, fp, fn, pairs) for one image."""
    used = [False] * len(gts)
    tp, pairs = 0, []
    for p in sorted(preds, key=lambda x: -x["score"]):
        best, bi = 0.0, -1
        for i, g in enumerate(gts):
            if used[i]:
                continue
            if class_aware and p["cls"] not in ECC_TO_OURS.get(g["cls"], set()):
                continue
            v = iou(p["box"], g["box"])
            if v > best:
                best, bi = v, i
        if bi >= 0 and best >= IOU_MATCH:
            used[bi] = True
            tp += 1
            pairs.append((gts[bi]["cls"], p["cls"]))
        else:
            pairs.append((None, p["cls"]))
    return tp, len(preds) - tp, len(gts) - tp, pairs


def run(root, model, limit, thresholds, tiled=False):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    os.environ["DAMAGE_DETECTOR_MODEL"] = model
    os.environ.pop("DAMAGE_DETECTOR_LABELS", None)
    os.environ["DAMAGE_GRADE"] = "0"
    os.environ["DAMAGE_TILED"] = "1" if tiled else "0"
    import numpy as np
    import onnxruntime
    from PIL import Image
    import detect as DET

    ann = os.path.join(root, "annotations", "coco_instances_hitl.json")
    with open(ann) as f:
        doc = json.load(f)
    cats = {c["id"]: c["name"] for c in doc["categories"]}
    imgs = {i["id"]: i for i in doc["images"]}
    gt = collections.defaultdict(list)
    for a in doc["annotations"]:
        gt[a["image_id"]].append({"cls": cats[a["category_id"]],
                                  "box": list(a["bbox"])})

    labels = DET._labels_beside_model(model)
    size = None
    sess = onnxruntime.InferenceSession(model,
                                        providers=["CPUExecutionProvider"])
    shp = sess.get_inputs()[0].shape
    size = shp[2] if isinstance(shp[2], int) else 560
    inp = sess.get_inputs()[0].name
    print(f"model {os.path.basename(model)}  input {size}  classes {labels}")

    ids = sorted(gt)[:limit] if limit else sorted(gt)
    print(f"evaluating {len(ids)} annotated images "
          f"({sum(len(gt[i]) for i in ids):,} ground-truth boxes)\n")

    cache = {}
    for n, iid in enumerate(ids):
        path = os.path.join(root, imgs[iid]["file_name"])
        if not os.path.exists(path):
            continue
        with Image.open(path) as im:
            im2 = im.convert("RGB")
            im = im2
            W, H = im.size
            arr = np.asarray(im.resize((size, size)),
                             dtype=np.float32) / 255.0
        arr = np.transpose(arr, (2, 0, 1))[None, ...]
        outs = sess.run(None, {inp: arr})
        if tiled:
            from tiled_detect import tiled_detect as _t
            def _run(crop, _l=labels, _s=size):
                return DET.onnx_detect_image(crop, session=sess, labels=_l,
                                             input_size=_s)
            dets = _t(im2, _run, model_size=size)
        else:
            dets = DET.parse_detections(outs, (W, H), (size, size), labels, 0.0)
        cache[iid] = [{"cls": d["label"], "score": d["score"],
                       "box": [d["box"][0], d["box"][1],
                               d["box"][2] - d["box"][0],
                               d["box"][3] - d["box"][1]]} for d in dets]
        if (n + 1) % 50 == 0:
            print(f"  {n+1}/{len(ids)}", flush=True)

    for aware in (False, True):
        title = ("MAPPED CLASSES — the class must agree too"
                 if aware else
                 "CLASS-AGNOSTIC — is there damage, roughly there?")
        print(f"\n{'='*66}\n{title}\n{'='*66}")
        print(f"{'thresh':>7} {'precision':>10} {'recall':>8} {'F1':>7} "
              f"{'TP':>6} {'FP':>6} {'FN':>6}")
        best = None
        for t in thresholds:
            TP = FP = FN = 0
            for iid in cache:
                preds = [p for p in cache[iid] if p["score"] >= t]
                a, b, c, _ = match(preds, gt[iid], aware)
                TP += a
                FP += b
                FN += c
            p = TP / (TP + FP) if TP + FP else 0.0
            r = TP / (TP + FN) if TP + FN else 0.0
            f1 = 2 * p * r / (p + r) if p + r else 0.0
            print(f"{t:>7.2f} {p:>10.4f} {r:>8.4f} {f1:>7.4f} "
                  f"{TP:>6,} {FP:>6,} {FN:>6,}")
            if best is None or f1 > best[0]:
                best = (f1, t, p, r)
        print(f"  best F1 {best[0]:.4f} at threshold {best[1]:.2f} "
              f"(P {best[2]:.3f} / R {best[3]:.3f})")

    # confusion at a mid threshold, so disagreements are visible
    conf = collections.Counter()
    for iid in cache:
        preds = [p for p in cache[iid] if p["score"] >= 0.30]
        _a, _b, _c, pairs = match(preds, gt[iid], False)
        for g, p in pairs:
            conf[(g or "(nothing there)", p)] += 1
    print(f"\n{'='*66}\nWHAT IT CALLED THINGS (threshold 0.30, "
          f"class-agnostic matching)\n{'='*66}")
    print(f"{'ECC ground truth':22s} {'our prediction':16s} {'n':>6}")
    for (g, p), n in conf.most_common(18):
        ok = "" if g == "(nothing there)" else (
            "  ok" if p in ECC_TO_OURS.get(g, set()) else "  <- mismatch")
        print(f"{g:22s} {p:16s} {n:6,}{ok}")
    return 0


def _selftest():
    ok = fail = 0

    def check(n, c, d=""):
        nonlocal ok, fail
        if c:
            ok += 1
            print(f"  ok   {n}")
        else:
            fail += 1
            print(f"  FAIL {n} {d}")

    check("identical boxes have IoU 1",
          abs(iou([0, 0, 10, 10], [0, 0, 10, 10]) - 1) < 1e-9)
    check("disjoint boxes have IoU 0", iou([0, 0, 1, 1], [9, 9, 1, 1]) == 0.0)

    gts = [{"cls": "dent", "box": [0, 0, 10, 10]}]
    good = [{"cls": "dent", "score": 0.9, "box": [0, 0, 10, 10]}]
    check("an exact match counts", match(good, gts, True)[:3] == (1, 0, 0))
    wrong = [{"cls": "scratch_scuff", "score": 0.9, "box": [0, 0, 10, 10]}]
    check("a wrong class fails class-aware matching",
          match(wrong, gts, True)[:3] == (0, 1, 1))
    check("...but passes class-agnostic matching",
          match(wrong, gts, False)[:3] == (1, 0, 0))

    # broken_part accepts any of three, which is the point of the set-valued map
    bp = [{"cls": "broken_part", "box": [0, 0, 10, 10]}]
    for ours in ("crack_glass", "lamp_wheel", "structural"):
        pred = [{"cls": ours, "score": 0.9, "box": [0, 0, 10, 10]}]
        check(f"broken_part is satisfied by {ours}",
              match(pred, bp, True)[:3] == (1, 0, 0))
    pred = [{"cls": "dent", "score": 0.9, "box": [0, 0, 10, 10]}]
    check("broken_part is NOT satisfied by dent",
          match(pred, bp, True)[:3] == (0, 1, 1))

    check("every ECC class has a mapping", len(ECC_TO_OURS) == 8)
    check("the three paint-ish ECC classes all map to rust_paint",
          ECC_TO_OURS["corrosion"] == ECC_TO_OURS["paint_flaking"]
          == ECC_TO_OURS["paint_chip"] == {"rust_paint"})
    print(f"\n{ok} passed, {fail} failed")
    return 1 if fail else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=False,
                    default="/home/user/ecc/"
                            "ECC_Car_Damage_Test_Set_1000_compact_part_1_of_3")
    ap.add_argument("--model", default="/home/user/rfdetr-base.onnx")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--tiled", action="store_true",
                    help="run the tiled inference path, which exists for "
                         "exactly this case (fine damage in a large photo) "
                         "and had never been measured against real labels")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    return run(a.root, a.model, a.limit,
               (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.60),
               tiled=a.tiled)


if __name__ == "__main__":
    sys.exit(main())
