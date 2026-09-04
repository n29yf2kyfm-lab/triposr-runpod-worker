"""Assemble the seven-class corpus COCO: recovered labels in, junk out.

WHAT GOES IN

The six-class COCO under merged640 (plus the CarDD one beneath it) is the
starting point. On top of it, reingest_annotations.py's output is merged:
every box that the original merge deleted because its class string mapped to
nothing, re-attached to the image it belongs to by content hash.

Those boxes are in the EXPORT's pixel frame, not the corpus's. merge_coco_source
capped every image at 640px but kept the original file's sha as its identity,
so the hash join succeeds while the dimensions differ (29,182 of 101,365 rows:
an 800x800 export against a 640x640 corpus file). Each box is therefore scaled
by corpus/export before use, and clipped to the frame.

A recovered box is dropped when a box of the same class already covers it at
IoU >= 0.5. The recovery re-derives the whole label set under the new class
map, so most of what it produces is already present; only the remainder is new.

WHAT COMES OUT

    watermarks    every file the OCR detector flagged, and every other file in
                  its perceptual-hash cluster, since they are the same
                  photograph. The detector has zero false positives on a
                  hand-labelled check, so this is safe to apply unreviewed.
                  It also has 35% recall, so this is a floor, not a clean bill.
    degraded      mean chroma < 1 (a greyscale copy left by a source's
                  augmentation) or pixel roughness > 32 (grey static). Both
                  thresholds were calibrated on 192 hand-read images.
    duplicates    one file per photograph. Within each pHash cluster the copy
                  with the most boxes is kept, colour preferred over grey.
                  Clusters over 150 members are left alone: inspection found
                  the largest to be unrelated close-ups of smooth panels that
                  dHash cannot tell apart, and build_train_index ignores them
                  for the same reason.

The result is written to a NEW root with symlinks to the pixels, so the
original corpus is untouched and build_train_index --coco can pool it without
also pooling the six-class file it replaces.
"""
import argparse
import collections
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import class_map as CM                                   # noqa: E402

# Fine type (prepare_data.CLASS_MAP values) -> FINAL_CLASSES name. Follows the
# roboflow lists in class_map.FINAL_CLASSES: "Flat Tire" sits with lamps,
# "Paint Damage" with rust, "Crack" with glass. missing_part joins structural
# because that is where ECC's broken_part already scores against it.
FINE_TO_FINAL = {
    "scratch": "scratch_scuff",
    "dent": "dent",
    "crack": "crack_glass", "shattered_glass": "crack_glass",
    "lamp_damage": "lamp_wheel", "tire_damage": "lamp_wheel",
    "rust": "rust_paint", "paint_chip": "rust_paint",
    "deformation": "structural", "missing_part": "structural",
    "panel_gap": "panel_gap",
}
CHROMA_FLOOR = 1.0
ROUGH_CEIL = 32.0
MAX_CLUSTER = 150
IOU_DUP = 0.5


def iou(a, b):
    ax2, ay2 = a[0] + a[2], a[1] + a[3]
    bx2, by2 = b[0] + b[2], b[1] + b[3]
    iw = max(0.0, min(ax2, bx2) - max(a[0], b[0]))
    ih = max(0.0, min(ay2, by2) - max(a[1], b[1]))
    inter = iw * ih
    if inter <= 0:
        return 0.0
    return inter / (a[2] * a[3] + b[2] * b[3] - inter)


def load_corpus(root, sha_lookup=None):
    """-> {sha: rec}; rec.file is root-relative ("images/x.jpg",
    "cardd/images/x.jpg"), rec.boxes is [(final_name, [x,y,w,h])].

    The CarDD COCO carries no sha field. An earlier index already joined
    those files to their shas, so sha_lookup ({root-relative file: sha})
    fills the gap; without it 2,816 images silently vanished."""
    sha_lookup = sha_lookup or {}
    recs = {}
    for coco, prefix in ((os.path.join(root, "_annotations.coco.json"), ""),
                         (os.path.join(root, "cardd", "_annotations.coco.json"),
                          "cardd/")):
        doc = json.load(open(coco))
        cat = {c["id"]: c["name"] for c in doc["categories"]}
        by_img = collections.defaultdict(list)
        for a in doc["annotations"]:
            by_img[a["image_id"]].append((cat[a["category_id"]], list(a["bbox"])))
        for im in doc["images"]:
            fn = im["file_name"]
            rel = prefix + ("images/" + fn if "/" not in fn else fn)
            sha = im.get("sha") or sha_lookup.get(rel)
            if not sha:
                continue
            recs[sha] = {"sha": sha, "file": rel, "width": im["width"],
                         "height": im["height"], "boxes": by_img.get(im["id"], [])}
    return recs


def merge_recovered(recs, path, st):
    for line in open(path):
        r = json.loads(line)
        rec = recs.get(r["sha"])
        if rec is None:
            st["recovered_rows_unmatched"] += 1
            continue
        sx = rec["width"] / r["width"]
        sy = rec["height"] / r["height"]
        for b in r["boxes"]:
            final = FINE_TO_FINAL.get(b["cls"])
            if not final:
                st["recovered_boxes_unmapped_fine"] += 1
                continue
            x, y, w, h = b["bbox"]
            x, y, w, h = x * sx, y * sy, w * sx, h * sy
            x2 = min(rec["width"], x + w)
            y2 = min(rec["height"], y + h)
            x, y = max(0.0, x), max(0.0, y)
            w, h = x2 - x, y2 - y
            if w < 2 or h < 2:
                st["recovered_boxes_degenerate"] += 1
                continue
            box = [round(x, 2), round(y, 2), round(w, 2), round(h, 2)]
            if any(c == final and iou(box, ob) >= IOU_DUP
                   for c, ob in rec["boxes"]):
                st["recovered_boxes_already_present"] += 1
                continue
            rec["boxes"].append((final, box))
            st["recovered_boxes_added"] += 1
            st["added_by_class"][final] += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="/home/user/rf/merged640")
    ap.add_argument("--recovered", default="/home/user/rf/reingest.jsonl")
    ap.add_argument("--clusters", required=True,
                    help="audit CSV with file, cluster_id, cluster_size")
    ap.add_argument("--chroma", help="chroma_scan.py output jsonl")
    ap.add_argument("--watermarks", nargs="*", default=[],
                    help="find_watermarks.py output jsonl files")
    ap.add_argument("--sha-lookup", default="/home/user/rf/idx16/images.jsonl",
                    help="jsonl with file+sha, for COCO files lacking sha")
    ap.add_argument("--out", default="/home/user/rf/corpus7")
    a = ap.parse_args()

    st = collections.Counter()
    st["added_by_class"] = collections.Counter()
    sha_lookup = {}
    if a.sha_lookup:
        for line in open(a.sha_lookup):
            r = json.loads(line)
            sha_lookup[r["file"]] = r["sha"]
    recs = load_corpus(a.corpus, sha_lookup)
    st["images_in"] = len(recs)
    st["boxes_in"] = sum(len(r["boxes"]) for r in recs.values())
    print(f"loaded {st['images_in']:,} images, {st['boxes_in']:,} boxes")

    merge_recovered(recs, a.recovered, st)
    print(f"recovered: +{st['recovered_boxes_added']:,} boxes, "
          f"{st['recovered_boxes_already_present']:,} already present")

    # --- clusters -------------------------------------------------------
    by_file = {r["file"]: r for r in recs.values()}
    cluster_of, size_of = {}, {}
    for row in csv.DictReader(open(a.clusters)):
        cluster_of[row["file"]] = row["cluster_id"]
        size_of[row["cluster_id"]] = int(row["cluster_size"])
    members = collections.defaultdict(list)
    for f, c in cluster_of.items():
        if f in by_file:
            members[c].append(f)

    # --- degraded ---------------------------------------------------------
    drop = {}                                            # file -> reason
    if a.chroma:
        for line in open(a.chroma):
            r = json.loads(line)
            rel = os.path.relpath(r["file"], a.corpus)
            if rel not in by_file or "error" in r:
                continue
            if r["chroma"] < CHROMA_FLOOR:
                drop.setdefault(rel, "greyscale")
            elif r["rough"] > ROUGH_CEIL:
                drop.setdefault(rel, "static")
        chroma_by_file = {os.path.relpath(json.loads(l)["file"], a.corpus):
                          json.loads(l).get("chroma", 99) for l in open(a.chroma)}
    else:
        chroma_by_file = {}

    # --- watermarks, propagated through the cluster -----------------------
    hit_files = set()
    for path in a.watermarks:
        for line in open(path):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("hits"):
                hit_files.add(os.path.relpath(r["file"], a.corpus))
    st["watermark_hits_direct"] = len(hit_files & set(by_file))
    for f in list(hit_files):
        c = cluster_of.get(f)
        if c and size_of.get(c, 1) <= MAX_CLUSTER:
            for m in members[c]:
                drop[m] = "watermark"
        elif f in by_file:
            drop[f] = "watermark"

    # --- one file per photograph ------------------------------------------
    # Copies of a photograph often come from DIFFERENT projects, and each
    # project boxed what it cared about: one the scratch, another the dent.
    # Keeping only the richest copy would throw the other's labels away, so
    # boxes are first pooled across every same-frame copy (aspect ratio
    # within 1%, so normalised coordinates transfer) onto the keeper, with
    # the same IoU dedup used for the recovered boxes. A crop has a different
    # aspect and keeps its boxes to itself.
    for c, fs in members.items():
        if size_of.get(c, 1) > MAX_CLUSTER or len(fs) < 2:
            continue
        live = [f for f in fs if f not in drop]
        if not live:
            continue
        keep = max(live, key=lambda f: (len(by_file[f]["boxes"]),
                                        chroma_by_file.get(f, 99) >= CHROMA_FLOOR,
                                        f))
        K = by_file[keep]
        kw, kh = K["width"], K["height"]
        for f in live:
            if f == keep:
                continue
            drop[f] = "duplicate"
            S = by_file[f]
            if abs(S["width"] / S["height"] - kw / kh) > 0.01 * (kw / kh):
                st["copies_not_pooled_different_frame"] += 1
                continue
            sx, sy = kw / S["width"], kh / S["height"]
            for cname, b in S["boxes"]:
                nb = [round(b[0] * sx, 2), round(b[1] * sy, 2),
                      round(b[2] * sx, 2), round(b[3] * sy, 2)]
                if any(cn == cname and iou(nb, ob) >= IOU_DUP
                       for cn, ob in K["boxes"]):
                    continue
                K["boxes"].append((cname, nb))
                st["boxes_pooled_from_copies"] += 1

    for f, why in drop.items():
        st["dropped_" + why] += 1
    kept = [r for r in recs.values() if r["file"] not in drop]
    st["images_out"] = len(kept)
    st["boxes_out"] = sum(len(r["boxes"]) for r in kept)
    st["boxes_lost_with_dropped_files"] = st["boxes_in"] + st["recovered_boxes_added"] - st["boxes_out"]

    # --- write ----------------------------------------------------------------
    os.makedirs(a.out, exist_ok=True)
    for sub in ("images", "cardd"):
        link = os.path.join(a.out, sub)
        if not os.path.lexists(link):
            os.symlink(os.path.join(a.corpus, sub), link)
    names = sorted(CM.FINAL_CLASSES)                     # matches CM.class_index
    cid = {n: i for i, n in enumerate(names, start=1)}
    images, anns = [], []
    per_class = collections.Counter()
    for i, r in enumerate(sorted(kept, key=lambda r: r["file"]), start=1):
        images.append({"id": i, "file_name": r["file"], "width": r["width"],
                       "height": r["height"], "sha": r["sha"]})
        for cname, b in r["boxes"]:
            anns.append({"id": len(anns) + 1, "image_id": i,
                         "category_id": cid[cname], "bbox": b,
                         "area": round(b[2] * b[3], 1), "iscrowd": 0,
                         "cls": cname})
            per_class[cname] += 1
    doc = {"categories": [{"id": 0, "name": "_placeholder_", "supercategory": "none"}]
           + [{"id": cid[n], "name": n, "supercategory": "damage"} for n in names],
           "images": images, "annotations": anns}
    with open(os.path.join(a.out, "_annotations.coco.json"), "w") as f:
        json.dump(doc, f)
    st["boxes_by_class_out"] = dict(per_class)
    st["added_by_class"] = dict(st["added_by_class"])
    with open(os.path.join(a.out, "build_report.json"), "w") as f:
        json.dump(st, f, indent=1, sort_keys=True)
    print(json.dumps(st, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
