"""Pre-annotate the Drive photos: folder says WHAT, detector says WHERE.

WHAT THIS IS, AND WHAT IT IS NOT

The 22,318 Drive photographs carry a class per folder and no boxes, so a
detector cannot train on them. This writes a COCO of candidate boxes for a
human to correct, which is a much smaller job than drawing them from nothing.

IT IS NOT ANNOTATION. Every box here was proposed by a model measured at 26%
per-damage recall on an independent set. Boxes it did not draw are damage the
reviewer must still add, and that is the majority of them. Training on this
file unreviewed would teach the detector what it already believes -- the boxes
it finds easily, in the places it already looks -- and the corpus's real
problem is label DENSITY: our sources box a median of one damage per car
against the external benchmark's nine. Self-training on sparse pseudo-labels
makes that worse, not better. The output is therefore written with
`reviewed: false` on every image and build_train_index is not pointed at it.

WHY THE FOLDER MAKES THIS WORTH DOING ANYWAY

Unconstrained auto-labelling on this corpus would be near-useless: the model
confuses paint_chip with scratch, and dent with structural, at exactly the
rates the confusion table shows. But the folder name is a human judgement
about what is in the picture, so the class is already known and only the
box is in question. Detections whose class contradicts the folder are
dropped rather than trusted, which removes the model's worst failure mode
and leaves it doing the one thing it is genuinely good at: finding where
on the panel something is wrong.

A NOTE ON dent_major AND FRIENDS

The folders encode severity as well as type (dent_minor/medium/major/severe).
That grading is a real human signal this project has nowhere else, so it is
carried through to the output as `severity_folder` even though no class uses
it yet. Discarding it here would mean re-deriving it later from a folder
listing that may not survive.
"""
import argparse
import collections
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DAMAGE = os.path.dirname(HERE)
for _p in (HERE, DAMAGE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import class_map as CM                                     # noqa: E402
import detect as DET                                       # noqa: E402

# The detector ships six classes; the corpus now has seven. A detection is
# kept only when its class matches the folder's, so this maps the model's
# label space onto FINAL_CLASSES. panel_gap has no detector class at all --
# the model has never been trained on it -- so those 60 images get no
# proposals and are flagged for annotation from scratch.
SEVERITY_FOLDERS = ("minor", "medium", "major", "severe", "deep", "faint",
                    "light", "thin", "normal", "thick")


CHROMA_FLOOR = 1.0        # a greyscale copy left behind by augmentation
ROUGH_CEIL = 32.0         # grey static; both calibrated on 192 hand-read images


def quality(path):
    """-> (verdict, chroma, rough). Cheap: decodes at 1/4 scale, ~5ms."""
    import numpy as np
    from PIL import Image
    try:
        im = Image.open(path)
        im.draft("RGB", (160, 160))
        a = np.asarray(im.convert("RGB").resize((160, 160))).astype("float32")
    except Exception as e:
        return f"scrap_unreadable:{type(e).__name__}", None, None
    chroma = float(np.mean(np.max(a, 2) - np.min(a, 2)))
    g = a.mean(2)
    rough = float(np.mean(np.abs(g[1:, 1:] - g[:-1, :-1])))
    if chroma < CHROMA_FLOOR:
        return "scrap_greyscale", chroma, rough
    if rough > ROUGH_CEIL:
        return "scrap_static", chroma, rough
    return "pass", chroma, rough


def severity_from_folder(folder):
    for s in SEVERITY_FOLDERS:
        if folder.endswith("_" + s):
            return s
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drive", default="/home/user/drive_images")
    ap.add_argument("--model", default="/home/user/rfdetr-base.onnx")
    ap.add_argument("--out", default="/home/user/rf/drive_preannot.json")
    ap.add_argument("--min-confidence", type=float, default=0.20,
                    help="0.20 is the measured F1 optimum for RECALL-leaning "
                         "review: a reviewer deletes a wrong box faster than "
                         "they draw a missing one")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--resume", action="store_true")
    a = ap.parse_args()

    labels = None
    side = os.path.join(os.path.dirname(a.model), "rfdetr-base.classes.json")
    if os.path.exists(side):
        doc = json.load(open(side))
        idx = doc.get("index_to_name") or {}
        labels = {int(k): v for k, v in idx.items()}

    import onnxruntime
    sess = onnxruntime.InferenceSession(
        a.model, providers=["CPUExecutionProvider"])
    size = DET._input_size(sess) or 560

    jobs = []
    for folder in sorted(os.listdir(a.drive)):
        d = os.path.join(a.drive, folder)
        if not os.path.isdir(d):
            continue
        final = CM._FROM_DRIVE.get(folder)
        for f in sorted(os.listdir(d)):
            if f.lower().endswith((".jpg", ".jpeg", ".png")):
                jobs.append((folder, final, os.path.join(d, f)))
    if a.limit:
        jobs = jobs[:a.limit]

    done = set()
    if a.resume and os.path.exists(a.out + ".partial"):
        for line in open(a.out + ".partial"):
            try:
                done.add(json.loads(line)["file"])
            except Exception:
                pass
        print(f"resuming: {len(done):,} already done")

    st = collections.Counter()
    mode = "a" if done else "w"
    with open(a.out + ".partial", mode) as pf:
        for n, (folder, final, path) in enumerate(jobs):
            if path in done:
                continue
            verdict, chroma, rough = quality(path)
            rec = {"file": path, "folder": folder, "final_class": final,
                   "severity_folder": severity_from_folder(folder),
                   "quality": verdict, "chroma": None if chroma is None
                   else round(chroma, 2),
                   "rough": None if rough is None else round(rough, 2),
                   "reviewed": False, "boxes": []}
            if verdict != "pass":
                st[verdict] += 1
            elif final is None:
                rec["quality"] = "scrap_unmapped_folder"
                st["scrap_unmapped_folder"] += 1
            elif final not in (labels or {}).values():
                # panel_gap: the detector has no such class, so there is
                # nothing to propose. Recorded, not silently emptied.
                rec["needs_annotation_from_scratch"] = True
                st["no_detector_class"] += 1
            else:
                try:
                    dets = DET.onnx_detect(path, session=sess, input_size=size,
                                           labels=labels,
                                           min_confidence=a.min_confidence)
                    st["images_run"] += 1
                    for d in dets:
                        if d.get("label") == final:
                            rec["boxes"].append(
                                {"cls": final, "box": [round(v, 2) for v in
                                                       d["box"]],
                                 "score": round(float(d["score"]), 4)})
                            st["boxes_kept"] += 1
                        else:
                            st["boxes_dropped_class_mismatch"] += 1
                    if not rec["boxes"]:
                        st["images_with_no_proposal"] += 1
                except Exception as e:
                    rec["error"] = f"{type(e).__name__}: {e}"
                    st["errors"] += 1
            pf.write(json.dumps(rec) + "\n")
            pf.flush()
            if (n + 1) % 200 == 0:
                print(f"  {n+1:,}/{len(jobs):,}  kept {st['boxes_kept']:,}",
                      flush=True)

    rows = [json.loads(l) for l in open(a.out + ".partial")]
    st["images_total"] = len(rows)
    st["images_with_boxes"] = sum(1 for r in rows if r["boxes"])
    json.dump({"stats": dict(st), "images": rows}, open(a.out, "w"))

    # THE CHART: one row per class, so what survives per class is visible at a
    # glance rather than buried in 22,318 json rows.
    chart = collections.defaultdict(collections.Counter)
    for r in rows:
        c = chart[r["final_class"] or "(unmapped)"]
        c["total"] += 1
        c[r["quality"]] += 1
        if r["quality"] == "pass":
            c["boxes"] += len(r["boxes"])
            if r["boxes"]:
                c["with_boxes"] += 1
            elif r.get("needs_annotation_from_scratch"):
                c["needs_scratch"] += 1
            else:
                c["no_proposal"] += 1
    csv_path = os.path.splitext(a.out)[0] + "_chart.csv"
    cols = ["class", "total", "pass", "with_boxes", "boxes", "no_proposal",
            "needs_scratch", "scrap_greyscale", "scrap_static",
            "scrap_unreadable", "scrap_unmapped_folder"]
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for cls in sorted(chart, key=lambda k: -chart[k]["total"]):
            c = chart[cls]
            w.writerow([cls] + [c.get(k, 0) for k in cols[1:]])
    hdr = ("class", "total", "pass", "boxed", "boxes", "scrap")
    print("\n%-16s%7s%7s%7s%8s%7s" % hdr)
    for cls in sorted(chart, key=lambda k: -chart[k]["total"]):
        c = chart[cls]
        scrap = sum(v for k, v in c.items() if k.startswith("scrap"))
        print(f"{str(cls):16}{c['total']:7,}{c.get('pass',0):7,}"
              f"{c.get('with_boxes',0):7,}{c.get('boxes',0):8,}{scrap:7,}")
    print(json.dumps(dict(st), indent=1, sort_keys=True))
    print(f"wrote {a.out} and {csv_path}")


if __name__ == "__main__":
    main()
