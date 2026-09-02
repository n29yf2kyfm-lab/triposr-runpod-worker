"""One row per image, every dataset, with its class and whether it survived.

WHY THIS EXISTS

The images in this project live in six places that each answer a different
question: a COCO with the boxes, an audit CSV with the perceptual hashes and
splits, a chroma scan with the quality metrics, a re-ingest with the recovered
labels, an OCR pass with the watermark hits, and a folder tree with no boxes
at all. Asking "what do I actually have, per class, and what got thrown away"
meant joining all six by hand every time, so nobody asked.

This joins them once, keyed on the image, and writes two files:

    master.csv   one row per image: class, source, boxes, quality, watermark,
                 duplicate cluster, split, and the verdict with its reason
    chart.csv    one row per class: totals, what passed, what was scrapped and
                 why, so the per-class question is answerable at a glance

VERDICTS, IN PRECEDENCE ORDER

    scrap_unreadable    the file will not decode
    scrap_greyscale     mean chroma < 1: a greyscale copy left by a source's
                        augmentation, not a photograph anyone took
    scrap_static        pixel roughness > 32: augmentation reduced it to noise
    scrap_watermark     a stock-agency credit line was READ off it, or off
                        another copy of the same photograph
    scrap_duplicate     another file is the same photograph and was kept
    scrap_unlabelled    no boxes and no folder class: nothing to train on
    keep                everything else

The thresholds come from 192 hand-read images, and the watermark detector has
zero false positives on that set but only 35% recall -- so scrap_watermark is
a floor, and `keep` is not a promise that an image is watermark-free.

NOTHING IS DELETED. A verdict is a column, so a threshold can be revisited
without re-deriving anything, and an image scrapped for one reason can be
found again when that reason changes.
"""
import argparse
import collections
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import class_map as CM                                     # noqa: E402

CHROMA_FLOOR = 1.0
ROUGH_CEIL = 32.0
CORPUS_ROOT = "/home/user/rf/merged640"


def load_jsonl(path, key=None):
    out = {} if key else []
    if not path or not os.path.exists(path):
        return out
    for line in open(path):
        try:
            r = json.loads(line)
        except ValueError:
            continue                      # a torn final line from a live run
        if key:
            out[r[key]] = r
        else:
            out.append(r)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", required=True, help="01_images_master.csv")
    ap.add_argument("--chroma", required=True, help="chroma jsonl")
    ap.add_argument("--recovered", default="/home/user/rf/reingest.jsonl")
    ap.add_argument("--corpus7", default="/home/user/rf/corpus7")
    ap.add_argument("--watermarks", nargs="*", default=[])
    ap.add_argument("--drive", default="/home/user/rf/drive_preannot.json.partial")
    ap.add_argument("--out", default="/home/user/rf/master")
    a = ap.parse_args()

    # --- quality, keyed on absolute path ---------------------------------
    qual = {}
    for r in load_jsonl(a.chroma):
        qual[r["file"]] = r

    # --- watermark hits, propagated across the photograph ------------------
    hit_files = set()
    for p in a.watermarks:
        for r in load_jsonl(p):
            if r.get("hits"):
                hit_files.add(r["file"])

    # --- recovered boxes per sha ------------------------------------------
    recovered = collections.Counter()
    for r in load_jsonl(a.recovered):
        recovered[r["sha"]] += len(r.get("boxes") or [])

    # --- what survived into the seven-class corpus -------------------------
    kept7, boxes7 = set(), {}
    c7 = os.path.join(a.corpus7, "_annotations.coco.json")
    if os.path.exists(c7):
        doc = json.load(open(c7))
        cat = {c["id"]: c["name"] for c in doc["categories"]}
        per = collections.Counter()
        cls_of = collections.defaultdict(collections.Counter)
        for an in doc["annotations"]:
            per[an["image_id"]] += 1
            cls_of[an["image_id"]][cat[an["category_id"]]] += 1
        for im in doc["images"]:
            kept7.add(im["sha"])
            boxes7[im["sha"]] = (per.get(im["id"], 0),
                                 cls_of.get(im["id"]) or collections.Counter())

    rows = []
    wm_clusters = set()

    # --- pass 1 over the corpus: find every cluster holding a watermark hit -
    audit = list(csv.DictReader(open(a.audit)))
    for r in audit:
        if os.path.join(CORPUS_ROOT, r["file"]) in hit_files:
            wm_clusters.add(r["cluster_id"])

    # --- pass 2: one row per corpus image ---------------------------------
    for r in audit:
        path = os.path.join(CORPUS_ROOT, r["file"])
        q = qual.get(path, {})
        chroma, rough = q.get("chroma"), q.get("rough")
        sha = r["sha"]
        n7, cls7 = boxes7.get(sha, (0, collections.Counter()))
        # The class a row is CHARTED under: its DOMINANT class, meaning the
        # one holding the most boxes on that image. An image carrying four
        # scratches and one dent is a scratch image for charting purposes.
        # The audit CSV pipe-separates the classes an image carries and does
        # not say how many of each, so where the seven-class corpus has the
        # real counts they win, and the CSV is only a fallback for images
        # that did not survive into it. Charting the raw field instead would
        # invent a class per COMBINATION -- "crack_glass|dent|rust_paint" --
        # and scatter one real class across dozens of rows.
        if cls7:
            cls = cls7.most_common(1)[0][0]
            all_classes = "|".join(sorted(cls7))
        else:
            names = [c for c in (r.get("classes") or "").split("|") if c]
            cls = names[0] if names else None
            all_classes = r.get("classes") or ""

        if "error" in q or (chroma is None and path not in qual):
            verdict, why = "scrap_unreadable", "no quality reading"
        elif chroma is not None and chroma < CHROMA_FLOOR:
            verdict, why = "scrap_greyscale", f"chroma {chroma}"
        elif rough is not None and rough > ROUGH_CEIL:
            verdict, why = "scrap_static", f"roughness {rough}"
        elif path in hit_files:
            verdict, why = "scrap_watermark", "credit line read on this file"
        elif r["cluster_id"] in wm_clusters:
            verdict, why = "scrap_watermark", "same photograph as a hit"
        elif sha in kept7:
            verdict, why = "keep", ""
        elif r.get("drop_reason"):
            verdict, why = "scrap_duplicate", r["drop_reason"]
        elif not cls:
            verdict, why = "scrap_unlabelled", "no boxes"
        else:
            verdict, why = "scrap_duplicate", "not in the seven-class corpus"

        rows.append({
            "image": r["file"], "sha": sha[:16], "all_classes": all_classes,
            "dataset":
                "cardd" if r["file"].startswith("cardd/") else "roboflow",
            "class": cls or "", "boxes": n7 or r.get("n_boxes") or 0,
            "boxes_recovered": recovered.get(sha, 0),
            "chroma": chroma, "rough": rough,
            "cluster": r["cluster_id"], "cluster_size": r["cluster_size"],
            "split": r.get("split_new") or "", "verdict": verdict,
            "reason": why, "reviewed": "yes" if verdict == "keep" else "",
        })

    # --- pass 3: the Drive tree, which has folder classes and no boxes -----
    for r in load_jsonl(a.drive):
        q = r.get("quality", "")
        verdict = "keep" if q == "pass" else (
            q if q.startswith("scrap") else "scrap_unreadable")
        if verdict == "keep" and not r.get("boxes") and not r.get(
                "needs_annotation_from_scratch"):
            verdict, why = "keep", "no box proposed - needs annotation"
        else:
            why = "" if verdict == "keep" else q
        rows.append({
            "image": os.path.relpath(r["file"], "/home/user"),
            "sha": "", "all_classes": r.get("final_class") or "",
            "dataset": "drive",
            "class": r.get("final_class") or "",
            "boxes": len(r.get("boxes") or []), "boxes_recovered": 0,
            "chroma": r.get("chroma"), "rough": r.get("rough"),
            "cluster": "", "cluster_size": "", "split": "",
            "verdict": verdict,
            "reason": why or ("needs annotation from scratch"
                              if r.get("needs_annotation_from_scratch") else ""),
            "reviewed": "",           # every Drive box is a PROPOSAL
        })

    # --- write ------------------------------------------------------------
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    cols = ["image", "sha", "dataset", "class", "all_classes", "boxes",
            "boxes_recovered",
            "chroma", "rough", "cluster", "cluster_size", "split", "verdict",
            "reason", "reviewed"]
    with open(a.out + ".csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    chart = collections.defaultdict(collections.Counter)
    for r in rows:
        c = chart[r["class"] or "(no class)"]
        c["total"] += 1
        c[r["verdict"]] += 1
        c["boxes"] += int(r["boxes"] or 0)
        c["dataset_" + r["dataset"]] += 1
    verdicts = ["keep", "scrap_duplicate", "scrap_greyscale", "scrap_static",
                "scrap_watermark", "scrap_unlabelled", "scrap_unreadable"]
    with open(a.out + "_chart.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["class", "total", "boxes", "roboflow", "cardd", "drive"]
                   + verdicts)
        for cls in sorted(chart, key=lambda k: -chart[k]["total"]):
            c = chart[cls]
            w.writerow([cls, c["total"], c["boxes"], c["dataset_roboflow"],
                        c["dataset_cardd"], c["dataset_drive"]]
                       + [c.get(v, 0) for v in verdicts])

    print("%-16s%9s%9s%9s%9s" % ("class", "total", "keep", "scrap", "boxes"))
    tot = collections.Counter()
    for cls in sorted(chart, key=lambda k: -chart[k]["total"]):
        c = chart[cls]
        scrap = sum(v for k, v in c.items() if k.startswith("scrap"))
        print("%-16s%9s%9s%9s%9s" % (cls, f"{c['total']:,}", f"{c['keep']:,}",
                                     f"{scrap:,}", f"{c['boxes']:,}"))
        tot.update({"total": c["total"], "keep": c["keep"], "scrap": scrap,
                    "boxes": c["boxes"]})
    print("%-16s%9s%9s%9s%9s" % ("ALL", f"{tot['total']:,}", f"{tot['keep']:,}",
                                 f"{tot['scrap']:,}", f"{tot['boxes']:,}"))
    print(f"\nwrote {a.out}.csv ({len(rows):,} rows) and {a.out}_chart.csv")


if __name__ == "__main__":
    main()
