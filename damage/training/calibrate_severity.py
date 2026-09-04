"""Fit severity cut points to the Drive folders, instead of choosing them.

WHY THIS DATA AND NOT THE TRAINING CORPUS
-----------------------------------------
The boxed corpus has 375,291 annotations and not one of them carries a
severity, because no public dataset labels one. The Drive corpus is the
opposite: no boxes at all, but its folders ARE severity labels, sorted by hand.

    scratch_faint       64      dent_minor      764
    scratch_medium     134      dent_medium   2,554
    scratch_deep     1,807      dent_major    8,979
    scratch_severe      60      dent_severe   2,774

Sixty-four faint scratches is nowhere near enough to train anything — which is
why these folders were set aside earlier as unlabelled. But severity.py does
not need training. It needs THREE NUMBERS: the cut points on a one-dimensional
score that was derived from the physics of paint layers. Two thousand ordered
examples is a great deal of data for fitting three numbers, and this is the
only place in the project where those labels can be used for what they are.

WHAT IS FITTED, AND WHAT IS NOT
-------------------------------
Only the cuts. The score itself is not fitted, tuned, or reweighted here. That
is the point: the score is a physical measurement, and if it does not order the
folders correctly then adjusting weights until it does would be fitting 2,065
images with enough freedom to memorise them. So this script reports the
ordering the raw score already achieves — Spearman rank correlation against the
folder order — BEFORE it fits anything. A weak correlation means the
measurement is wrong and no choice of cut points will save it; that is a result
worth seeing, not one worth optimising away.

THE BOX PROBLEM, AND WHY --centre DOES NOT WORK
-----------------------------------------------
The measurement needs a box: it compares the damage inside one against the
undamaged paint in a ring outside it. These images have no boxes, so the first
version assumed the damage was central and measured the middle 50% of the
frame. That assumption is WRONG for this corpus, and the run said so rather
than producing a plausible number:

    Spearman rank correlation, centre box:      -0.059   (n=1158)

The diagnosis is in the reference itself. If the ring were paint, the
undamaged pixels inside the box would sit 2-4 dE from it. Measured:

    folder            damage-vs-ref dE    background-vs-ref dE
    no_damage              43.9                  16.7
    scratch_faint          40.7                  11.4
    scratch_deep           49.6                  12.2
    scratch_severe         32.7                  14.6

A background 16.7 dE from its own reference is not paint. These are whole-car
and roadside photographs, not damage close-ups, so the ring contains sky, road
and trim, and the "damage" Otsu finds inside the box is frequently just the
next part of the scene. It shows up most clearly at the severe end, where the
damage fills the frame and the ring has no undamaged paint in it at all —
which is why scratch_severe scored LOWEST for separability, below no_damage.

So the centre box cannot calibrate this and the physics defaults stand. That
is a real result: a fitted number from this data would have been noise wearing
a decimal point.

--boxes-from-detector IS THE FIX, and it costs nothing extra. The detector
being trained on the six-class index produces exactly the boxes this is
missing. Run it over the same folders, keep the highest-scoring damage box per
image, and the folder name is still the severity label. Same 2,065 ordered
scratches, but measured where the damage actually is.

    python calibrate_severity.py --drive /home/user/drive_images
    python calibrate_severity.py --drive ... --boxes-from-detector
    python calibrate_severity.py --drive ... --measure-only   # cache, no fit
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from damage import severity_grade as severity  # noqa: E402

# Folder -> ordinal rank. The gaps are meaningful: scratch_light does not exist
# in the Drive corpus, so the ladder has a hole in it and the fit must not
# invent a cut where there is no data. Ranks are the position in the tier
# tuple, not 0..n-1, so a missing tier stays missing.
SCRATCH_FOLDERS = {"scratch_faint": 0, "scratch_medium": 2,
                   "scratch_deep": 3, "scratch_severe": 4}
DENT_FOLDERS = {"dent_minor": 0, "dent_medium": 1,
                "dent_major": 2, "dent_severe": 3}

CENTRE_FRAC = 0.5

# Long side the calibration images are reduced to before measuring. The Drive
# folders hold everything from 460px thumbnails to 4160px originals, and an
# 8-megapixel Lab conversion takes over a second — 2,000 scratches would be
# most of an hour. Reducing is safe HERE and only here: every quantity the
# score is built from is a ratio (chroma against the surrounding paint,
# curvature against the same panel's baseline, box area against frame area)
# and none of them changes with scale. It also makes the folders comparable to
# each other, which they otherwise are not. Inference does NOT do this — there
# the whole point is native resolution.
MAX_SIDE = 1200


def centre_box(size, frac=CENTRE_FRAC):
    w, h = size
    return (w * (1 - frac) / 2, h * (1 - frac) / 2, w * frac, h * frac)


def spearman(xs, ys):
    """Rank correlation, written out to avoid a scipy dependency.

    Ties are averaged, which matters here because the folder labels are hugely
    tied — every image in scratch_deep has the same rank.
    """
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    n = len(xs)
    if n < 3:
        return 0.0
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx) ** 0.5
    dy = sum((b - my) ** 2 for b in ry) ** 0.5
    return num / (dx * dy) if dx and dy else 0.0


def detector_box(img, kind, session, labels, size):
    """Highest-scoring damage box of the right family, or None.

    The folder already states what KIND of damage is in the picture, so the
    detector is only being asked where — a much easier question than the one
    it was trained on, and one it can answer even when its class is wrong.
    A scratch folder therefore accepts any surface-family box.
    """
    import sys as _sys
    _sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
    from detect import onnx_detect_image
    want = ({"scratch_scuff", "rust_paint", "scratch", "surface"}
            if kind == "scratch"
            else {"dent", "structural", "deformation"})
    dets = [d for d in onnx_detect_image(img, session=session, labels=labels,
                                         input_size=size, min_confidence=0.15)
            if str(d.get("label", "")).lower() in want]
    if not dets:
        return None
    d = max(dets, key=lambda d: d["score"])
    x1, y1, x2, y2 = d["box"]
    if x2 - x1 < 8 or y2 - y1 < 8:
        return None
    return (x1, y1, x2 - x1, y2 - y1)


def measure_folder(root, folder, limit, kind, max_side=MAX_SIDE,
                   detector=None):
    """Score every image in one severity folder. Returns (scores, rejected)."""
    from PIL import Image
    d = os.path.join(root, folder)
    if not os.path.isdir(d):
        return [], 0
    names = sorted(os.listdir(d))[:limit] if limit else sorted(os.listdir(d))
    out, rejected = [], 0
    print(f"  measuring {folder} ({len(names)} images) ...", flush=True)
    for i, n in enumerate(names):
        if i and i % 250 == 0:
            print(f"    {i}/{len(names)}", flush=True)
        p = os.path.join(d, n)
        try:
            with Image.open(p) as im:
                im = im.convert("RGB")
                if max(im.size) > max_side:
                    k = max_side / float(max(im.size))
                    im = im.resize((max(8, int(im.size[0] * k)),
                                    max(8, int(im.size[1] * k))))
                if detector is not None:
                    box = detector_box(im, kind, *detector)
                    if box is None:
                        rejected += 1
                        continue
                else:
                    box = centre_box(im.size)
                m = severity.measure(im, box)
                if m is None:
                    rejected += 1
                    continue
                if kind == "scratch":
                    s, basis = severity.depth_score(m)
                    if basis == "none":
                        rejected += 1
                        continue
                else:
                    s, _ = severity.deform_score(m)
                    if m.get("curv_ratio") is None:
                        rejected += 1
                        continue
                out.append(s)
        except Exception:
            rejected += 1
    return out, rejected


def fit_cuts(samples, tier_names, ranks):
    """Choose cut points that maximise agreement with the folder ranks.

    Exhaustive over a grid rather than gradient-based: there are at most three
    cuts on a bounded score, the objective is a step function with no useful
    gradient, and a grid over 0-1 in hundredths is 10^6 evaluations at worst —
    which is nothing, and is guaranteed to find the optimum rather than a
    local one.

    samples: [(score, rank)]. Only cuts BETWEEN observed ranks are fitted, so
    a tier with no images in the Drive corpus keeps its default rather than
    being assigned a boundary invented from neighbouring tiers.
    """
    present = sorted({r for _, r in samples})
    if len(present) < 2:
        return None, 0.0
    # A cut sits between consecutive PRESENT ranks. Each maps to the tier name
    # that the cut ends.
    boundaries = []
    for a, b in zip(present, present[1:]):
        boundaries.append((tier_names[a], a, b))

    grid = [i / 100.0 for i in range(1, 100)]
    best, best_acc = None, -1.0

    def accuracy(cuts):
        hit = 0
        for score, rank in samples:
            # Which band does the score fall in, counting cuts passed?
            band = 0
            for c in cuts:
                if score >= c:
                    band += 1
            if present[band] == rank:
                hit += 1
        return hit / len(samples)

    def search(i, chosen):
        nonlocal best, best_acc
        if i == len(boundaries):
            a = accuracy(chosen)
            if a > best_acc:
                best_acc, best = a, list(chosen)
            return
        lo = chosen[-1] if chosen else 0.0
        for g in grid:
            if g <= lo:
                continue
            search(i + 1, chosen + [g])

    search(0, [])
    if best is None:
        return None, 0.0
    return {boundaries[i][0]: best[i] for i in range(len(boundaries))}, best_acc


def open_detector():
    """(session, labels, size) for the exported ONNX, or raise with the reason."""
    try:
        import onnxruntime
    except ImportError:
        raise SystemExit("--boxes-from-detector needs onnxruntime: "
                         "pip install onnxruntime")
    model = os.environ.get("DAMAGE_DETECTOR_MODEL")
    if not model or not os.path.exists(model):
        raise SystemExit(
            "--boxes-from-detector needs DAMAGE_DETECTOR_MODEL pointing at the "
            "exported ONNX. Until the six-class run finishes there is no such "
            "file, and the centre-box mode cannot substitute for it — see this "
            "module's docstring for why.")
    labels = [s.strip() for s in
              os.environ.get("DAMAGE_DETECTOR_LABELS", "").split(",")
              if s.strip()] or None
    size = int(os.environ.get("DAMAGE_DETECTOR_SIZE", "728"))
    sess = onnxruntime.InferenceSession(model,
                                        providers=["CPUExecutionProvider"])
    print(f"detector {model} at {size}px, labels {labels}")
    return sess, labels, size


def run(root, limit, out_path, measure_only, max_side=MAX_SIDE,
        detector=None):
    report = {}
    for kind, folders in (("scratch", SCRATCH_FOLDERS),
                          ("dent", DENT_FOLDERS)):
        tiers = (severity.SCRATCH_TIERS if kind == "scratch"
                 else severity.DENT_TIERS)
        samples, lines = [], []
        for folder, rank in sorted(folders.items(), key=lambda kv: kv[1]):
            scores, rejected = measure_folder(root, folder, limit, kind,
                                              max_side, detector)
            n = len(scores)
            if n:
                scores_sorted = sorted(scores)
                med = scores_sorted[n // 2]
                lines.append(f"  {folder:18s} n={n:5d} rejected={rejected:5d} "
                             f"median={med:.3f}  "
                             f"p25={scores_sorted[n // 4]:.3f} "
                             f"p75={scores_sorted[3 * n // 4]:.3f}")
            else:
                lines.append(f"  {folder:18s} n=0 rejected={rejected}")
            samples += [(s, rank) for s in scores]

        print(f"\n{kind.upper()} — score by folder (folders are the labels)")
        for ln in lines:
            print(ln)
        if not samples:
            print("  no measurable images; nothing to fit")
            continue

        rho = spearman([s for s, _ in samples], [r for _, r in samples])
        print(f"  Spearman rank correlation of the RAW score with the folder "
              f"order: {rho:+.3f}   (n={len(samples)})")
        report[kind] = {"spearman": round(rho, 4), "n": len(samples)}

        if rho < 0.15:
            print("  ! the measurement does not order these folders. Fitting "
                  "cut points to it would be fitting noise — defaults kept.")
            continue

        cuts, acc = fit_cuts(samples, tiers, None)
        if cuts is None:
            print("  ! not enough distinct ranks present to fit cuts")
            continue
        base = (severity.SCRATCH_CUTS if kind == "scratch"
                else severity.DENT_CUTS)
        merged = dict(base)
        merged.update(cuts)
        print(f"  fitted cuts {cuts}   exact-tier accuracy {acc:.3f}")
        kept = {k: v for k, v in merged.items() if k not in cuts}
        if kept:
            print(f"  kept defaults for tiers absent from the corpus: {kept}")
        report[kind] = dict(report[kind], cuts=merged, accuracy=round(acc, 4))

    if measure_only:
        print("\n--measure-only: nothing written")
        return report
    payload = {k: v["cuts"] for k, v in report.items() if "cuts" in v}
    if not payload:
        print("\nnothing fitted; severity_cuts.json not written")
        return report
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=1, sort_keys=True)
    print(f"\nwrote {out_path}")
    return report


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

    check("spearman is 1 on a perfect ordering",
          abs(spearman([1, 2, 3, 4], [1, 2, 3, 4]) - 1.0) < 1e-9)
    check("spearman is -1 on a reversed ordering",
          abs(spearman([1, 2, 3, 4], [4, 3, 2, 1]) + 1.0) < 1e-9)
    check("spearman handles ties without dividing by zero",
          abs(spearman([1, 1, 2, 2], [0, 0, 1, 1]) - 1.0) < 1e-9)
    check("spearman is near zero on unrelated data",
          abs(spearman([1, 2, 3, 4, 5, 6], [3, 1, 5, 2, 6, 4])) < 0.7)

    # Perfectly separable sample: the fit must find a cut in the gap.
    samples = ([(0.10, 0), (0.12, 0), (0.15, 0)]
               + [(0.60, 2), (0.62, 2), (0.65, 2)])
    cuts, acc = fit_cuts(samples, severity.SCRATCH_TIERS, None)
    check("a separable sample fits with perfect accuracy", acc == 1.0,
          f"{acc}")
    check("the cut lands in the gap", 0.15 < cuts["faint"] <= 0.60,
          str(cuts))
    check("only the observed boundary is fitted", set(cuts) == {"faint"},
          str(cuts))

    # Overlapping sample: accuracy must be reported as imperfect, not forced.
    mixed = [(0.4, 0), (0.5, 0), (0.45, 2), (0.55, 2)]
    _, acc2 = fit_cuts(mixed, severity.SCRATCH_TIERS, None)
    check("an overlapping sample reports accuracy below 1", acc2 < 1.0,
          f"{acc2}")

    # A single rank cannot define a boundary.
    one, _ = fit_cuts([(0.3, 1), (0.4, 1)], severity.SCRATCH_TIERS, None)
    check("a single rank fits nothing", one is None)

    # The centre box must be inside the frame and half its size.
    b = centre_box((800, 600))
    check("centre box is centred and half-size",
          b == (200.0, 150.0, 400.0, 300.0), str(b))

    print(f"\n{ok} passed, {fail} failed")
    return 1 if fail else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drive", default="/home/user/drive_images")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap images per folder (0 = all)")
    ap.add_argument("--out", default=severity.CALIBRATION_FILE)
    ap.add_argument("--max-side", type=int, default=MAX_SIDE)
    ap.add_argument("--boxes-from-detector", action="store_true",
                    help="take the box from the trained detector instead of "
                         "assuming the damage is central. The centre-box "
                         "assumption measured -0.059 rank correlation on this "
                         "corpus; see the module docstring")
    ap.add_argument("--measure-only", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    if not os.path.isdir(a.drive):
        raise SystemExit(f"no such directory: {a.drive}")
    det = open_detector() if a.boxes_from_detector else None
    run(a.drive, a.limit, a.out, a.measure_only, a.max_side, det)
    return 0


if __name__ == "__main__":
    sys.exit(main())
