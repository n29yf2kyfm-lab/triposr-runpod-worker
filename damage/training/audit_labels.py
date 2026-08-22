"""Audit the LABELS, after scale was tested and ruled out.

WHY THIS EXISTS
---------------
scratch_scuff has been the worst class in every run: AP 0.1864 (v8), 0.1847
(v9d), 0.1863 (v10). The standing explanation was SCALE -- a scratch occupies a
median 1.1% of the frame against a dent's 10%, so "the model cannot see it".
Two things were built on that premise: CarDD was folded in for its 5.4% median
scratches, and zoom() was written to magnify a box to 3-12% of frame.

zoom reached 7.5% of training samples and lifted the median scratch from 0.97%
to 1.55% of frame, with the 75th percentile at 7.32%. The result:

    v8 scratch AP  0.1864
    v10 scratch AP 0.1863

Nothing. Not a small gain, not a regression -- the same number. A large,
verified change to the training data moved the metric by 0.0001, which is
strong evidence the premise was wrong.

THE HYPOTHESIS THIS TESTS: IoU IS SCALE-INVARIANT
-------------------------------------------------
IoU compares a predicted box with a true box RELATIVE TO THEIR OWN SIZE. Make
the scratch twice as big and the tolerable localisation error doubles too, so
the ratio -- and therefore the score -- is unchanged. Magnification cannot help
a metric that already normalises out magnification. That alone would explain a
null result this exact.

What DOES change the ratio is SHAPE. For a box shifted by d along an axis of
length L, the intersection is (L-d) of that axis and the union is (L+d), so

    IoU = (L - d) / (L + d)        and       d_max = L * (1 - t) / (1 + t)

The tolerance is proportional to the axis being crossed. A scratch box is thin:
its short axis may be a handful of pixels, so a couple of pixels of error
destroys the match. A dent is compact and forgives tens of pixels. Since
mAP@50:95 averages thresholds from 0.50 to 0.95, and the 0.95 term demands
near-perfect overlap, a thin class is penalised structurally -- by its shape,
not by the model's ability to find it.

This module measures that, per class, on the real corpus, and separately counts
the label pathologies that would depress a class independently of shape.

    python audit_labels.py --index /home/user/rf/idx8
"""
import argparse
import collections
import json
import math
import os
import sys

# A box covering more than this share of the frame is very likely the whole
# vehicle boxed as one damage, not a damage.
WHOLE_FRAME = 0.80

# Below this share, a box is under two pixels at 560 input and cannot be learnt.
MICRO = 5e-5

# Two boxes of the SAME class overlapping by more than this are probably one
# damage annotated twice.
DUP_IOU = 0.70

# Two boxes of DIFFERENT classes overlapping by more than this mean the same
# pixels carry two labels, which teaches the model contradictory targets.
CONFLICT_IOU = 0.60

# IoU thresholds mAP@50:95 averages over.
COCO_THRESHOLDS = [0.50 + 0.05 * i for i in range(10)]


def iou_xywh(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    return inter / (aw * ah + bw * bh - inter)


def shift_tolerance(length, t):
    """Pixels of pure translation along an axis before IoU falls below t.

    From IoU = (L - d) / (L + d), solved for d. Depends ONLY on the axis being
    crossed, which is why a thin box is fragile: its short axis is the one a
    perpendicular error crosses.
    """
    if length <= 0:
        return 0.0
    return length * (1.0 - t) / (1.0 + t)


def mean_tolerance(length):
    """Average tolerance across the ten thresholds mAP@50:95 averages."""
    return sum(shift_tolerance(length, t) for t in COCO_THRESHOLDS) / len(
        COCO_THRESHOLDS)


def run(index_dir, limit):
    with open(os.path.join(index_dir, "classes.json")) as f:
        classes = json.load(f)
    i2n = {int(k): v for k, v in classes["index_to_name"].items()}

    per = collections.defaultdict(lambda: {
        "n": 0, "areas": [], "ar": [], "short_px": [], "long_px": [],
        "whole": 0, "micro": 0, "dup": 0,
    })
    conflicts = collections.Counter()
    boxes_per_image = []
    n_img = 0

    with open(os.path.join(index_dir, "images.jsonl")) as f:
        for ln in f:
            if limit and n_img >= limit:
                break
            rec = json.loads(ln)
            n_img += 1
            W, H = rec["width"], rec["height"]
            bs = rec["boxes"]
            boxes_per_image.append(len(bs))
            resolved = []
            for b in bs:
                name = i2n.get(int(b[0]), str(b[0]))
                x, y, w, h = b[1], b[2], b[3], b[4]
                resolved.append((name, (x, y, w, h)))
                d = per[name]
                d["n"] += 1
                d["areas"].append(w * h)
                wpx, hpx = w * W, h * H
                lo, hi = min(wpx, hpx), max(wpx, hpx)
                d["short_px"].append(lo)
                d["long_px"].append(hi)
                d["ar"].append(hi / lo if lo > 0 else 999.0)
                if w * h > WHOLE_FRAME:
                    d["whole"] += 1
                if w * h < MICRO:
                    d["micro"] += 1
            # pathologies needing pairs
            for i in range(len(resolved)):
                for j in range(i + 1, len(resolved)):
                    (na, ba), (nb, bb) = resolved[i], resolved[j]
                    v = iou_xywh(ba, bb)
                    if na == nb and v > DUP_IOU:
                        per[na]["dup"] += 1
                    elif na != nb and v > CONFLICT_IOU:
                        conflicts[tuple(sorted((na, nb)))] += 1

    def med(v):
        if not v:
            return 0.0
        s = sorted(v)
        return s[len(s) // 2]

    names = sorted(per)
    print(f"audited {n_img:,} images, "
          f"{sum(per[c]['n'] for c in names):,} boxes\n")

    print("SHAPE — the axis an error has to cross")
    print(f"{'class':15s} {'boxes':>9} {'med area':>9} {'aspect':>7} "
          f"{'short px':>9} {'long px':>8}")
    for c in names:
        d = per[c]
        print(f"{c:15s} {d['n']:9,} {med(d['areas'])*100:8.2f}% "
              f"{med(d['ar']):7.2f} {med(d['short_px']):9.1f} "
              f"{med(d['long_px']):8.1f}")

    print("\nIoU FRAGILITY — pixels of localisation error the class tolerates")
    print("  (pure translation across the SHORT axis, the unforgiving one)")
    print(f"{'class':15s} {'@0.50':>8} {'@0.75':>8} {'@0.95':>8} "
          f"{'mean 50:95':>11}   relative to dent")
    base = mean_tolerance(med(per['dent']['short_px'])) if 'dent' in per else 1
    for c in names:
        s = med(per[c]["short_px"])
        mt = mean_tolerance(s)
        rel = mt / base if base else 0
        print(f"{c:15s} {shift_tolerance(s,0.50):8.2f} "
              f"{shift_tolerance(s,0.75):8.2f} {shift_tolerance(s,0.95):8.2f} "
              f"{mt:11.2f}   {rel:5.2f}x")

    print("\nLABEL PATHOLOGIES")
    print(f"{'class':15s} {'whole-frame':>12} {'micro':>8} {'duplicate':>10}")
    for c in names:
        d = per[c]
        n = max(1, d["n"])
        print(f"{c:15s} {d['whole']:7,} {100*d['whole']/n:4.1f}% "
              f"{d['micro']:7,} {d['dup']:10,}")

    if conflicts:
        print("\nCONTRADICTORY LABELS — same pixels, two classes "
              f"(IoU > {CONFLICT_IOU})")
        for (a, b), n in conflicts.most_common(8):
            print(f"  {n:7,}   {a} vs {b}")

    bp = sorted(boxes_per_image)
    print(f"\nBOXES PER IMAGE  median {bp[len(bp)//2]}  "
          f"p90 {bp[int(len(bp)*0.9)]}  max {bp[-1]}")
    print(f"  images with 1 box: "
          f"{100.0*sum(1 for v in bp if v == 1)/len(bp):.1f}%  "
          f"(a single box often means the rest went unlabelled)")
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

    check("identical boxes have IoU 1",
          abs(iou_xywh((0, 0, 10, 10), (0, 0, 10, 10)) - 1) < 1e-9)
    check("disjoint boxes have IoU 0",
          iou_xywh((0, 0, 10, 10), (50, 50, 10, 10)) == 0.0)

    # The formula this whole audit rests on: a shift of d along an axis of
    # length L gives IoU (L-d)/(L+d). Verified against the real computation.
    for L, d in ((100.0, 10.0), (20.0, 3.0), (8.0, 1.0)):
        got = iou_xywh((0, 0, L, 50), (d, 0, L, 50))
        want = (L - d) / (L + d)
        check(f"IoU of a {d}px shift on a {L}px axis is (L-d)/(L+d)",
              abs(got - want) < 1e-9, f"{got} vs {want}")

    # And the inverse: the tolerance formula must reproduce the threshold.
    for L, t in ((100.0, 0.5), (30.0, 0.75), (12.0, 0.9)):
        d = shift_tolerance(L, t)
        got = iou_xywh((0, 0, L, 40), (d, 0, L, 40))
        check(f"tolerance at t={t} on a {L}px axis lands exactly on t",
              abs(got - t) < 1e-9, f"{got}")

    check("a thinner axis tolerates less error",
          shift_tolerance(5, 0.5) < shift_tolerance(50, 0.5))
    check("a stricter threshold tolerates less error",
          shift_tolerance(50, 0.95) < shift_tolerance(50, 0.5))
    # 20x thinner must be 20x less forgiving — the linearity is the point.
    check("tolerance is proportional to the axis length",
          abs(shift_tolerance(100, 0.5) / shift_tolerance(5, 0.5) - 20) < 1e-9)

    # SCALE INVARIANCE — the claim that explains the null result. Doubling
    # both the box and the error leaves IoU untouched.
    a = iou_xywh((0, 0, 10, 40), (2, 0, 10, 40))
    b = iou_xywh((0, 0, 20, 80), (4, 0, 20, 80))
    check("doubling box AND error leaves IoU unchanged (scale invariance)",
          abs(a - b) < 1e-9, f"{a} vs {b}")

    check("mAP50:95 averages ten thresholds", len(COCO_THRESHOLDS) == 10
          and abs(COCO_THRESHOLDS[0] - 0.5) < 1e-9
          and abs(COCO_THRESHOLDS[-1] - 0.95) < 1e-9)
    check("the mean tolerance sits between the 0.5 and 0.95 extremes",
          shift_tolerance(50, 0.95) < mean_tolerance(50)
          < shift_tolerance(50, 0.50))

    check("a whole-frame box is flagged", 0.9 > WHOLE_FRAME)
    check("duplicate detection is stricter than conflict detection",
          DUP_IOU > CONFLICT_IOU)

    print(f"\n{ok} passed, {fail} failed")
    return 1 if fail else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="/home/user/rf/idx8")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    return run(a.index, a.limit)


if __name__ == "__main__":
    sys.exit(main())
