"""
corpus7 -> corpus8: keep only what the clean pass kept, and fold panel_gap
into structural.

Two changes, both from the audit in audit/project_verdicts.md:

  1. Every image whose clean_verdict is not "keep" is dropped -- the five junk
     source projects, plus the per-image noise / credit-bar / seam / duplicate
     flags. 25,190 of corpus7's 80,097 images go.

  2. panel_gap merges into structural. The class was documented as shut-line
     misalignment, but reading its images showed collision damage: of 20
     frames, 3 showed a gap and 14 showed wrecks. idx17 confirmed it
     independently from the other end -- it flagged panel_gap as needing 48.8x
     repetition to reach the box target, i.e. cloning rather than balancing.

This filters the existing COCO rather than re-deriving one, so every other
decision baked into corpus7 (chroma, watermark OCR, cluster dedup, box
recovery) is preserved exactly as it was.

    python3 apply_clean_verdicts.py
"""
import csv, json, os, collections

VERDICTS = "/home/user/rf/audit/clean_verdicts.csv"
SRC = "/home/user/rf/corpus7"
DST = "/home/user/rf/corpus9"
# panel_gap is NOT folded. The fold rested on "3 of 20 frames showed a gap",
# but that sample was drawn from the 78 images whose PRIMARY class is
# panel_gap -- 7.5% of the 1,036 images carrying the boxes, and selected on
# the one variable that guarantees multi-panel wrecks -- and then judged the
# whole image rather than the box. A random draw of 20 BOXES from all 1,567
# put roughly 16 on a genuine seam, shut line or panel separation. It is a
# real, scarce class; the index builder's 15x repeat cap handles scarcity
# honestly, and folding 1,455 tight seam boxes into structural would have
# taught structural to fire on shut lines.
FOLD = {}


def main():
    verdicts = list(csv.DictReader(open(VERDICTS)))
    unscored = sum(1 for r in verdicts if r["clean_verdict"] == "unscored")
    if unscored:
        raise SystemExit(f"REFUSING: {VERDICTS} has {unscored:,} unscored rows -- finish scoring first")
    keep = {r["image"] for r in verdicts if r["clean_verdict"] == "keep"}
    known = {r["image"] for r in verdicts}
    c = json.load(open(os.path.join(SRC, "_annotations.coco.json")))
    unmatched = [i["file_name"] for i in c["images"] if i["file_name"] not in known]
    if unmatched:
        print(f"  note: {len(unmatched):,} corpus images have NO row in the verdicts file (dropped): {unmatched[:3]}")
    old_cat = {x["id"]: x["name"] for x in c["categories"]}

    # categories, minus anything folded away; ids are reassigned densely
    names = [x["name"] for x in c["categories"] if x["name"] not in FOLD]
    new_id = {n: i for i, n in enumerate(names)}
    cats = [{"id": new_id[n], "name": n, "supercategory": "damage"} for n in names]

    images = [i for i in c["images"] if i["file_name"] in keep]
    live = {i["id"] for i in images}
    anns, folded = [], 0
    for a in c["annotations"]:
        if a["image_id"] not in live:
            continue
        name = old_cat[a["category_id"]]
        if name in FOLD:
            name = FOLD[name]; folded += 1
        b = dict(a); b["category_id"] = new_id[name]; b["cls"] = name
        anns.append(b)

    # images that lost every box are no longer training signal
    with_box = {a["image_id"] for a in anns}
    dropped_empty = [i for i in images if i["id"] not in with_box]
    images = [i for i in images if i["id"] in with_box]
    anns = [a for a in anns if a["image_id"] in with_box]

    os.makedirs(DST, exist_ok=True)
    for link in ("images", "cardd"):
        dst = os.path.join(DST, link)
        if not os.path.islink(dst):
            os.symlink(os.path.realpath(os.path.join(SRC, link)), dst)
    with open(os.path.join(DST, "_annotations.coco.json"), "w") as f:
        json.dump({"images": images, "annotations": anns, "categories": cats}, f)

    by = collections.Counter(a["cls"] for a in anns)
    report = {"images_in": len(c["images"]), "images_out": len(images),
              "images_dropped_by_verdict": len(c["images"]) - len(images) - len(dropped_empty),
              "images_dropped_no_box_left": len(dropped_empty),
              "boxes_in": len(c["annotations"]), "boxes_out": len(anns),
              "boxes_folded_panel_gap": folded, "boxes_by_class": dict(by),
              "classes": names}
    with open(os.path.join(DST, "build_report.json"), "w") as f:
        json.dump(report, f, indent=1)
    for k, v in report.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
