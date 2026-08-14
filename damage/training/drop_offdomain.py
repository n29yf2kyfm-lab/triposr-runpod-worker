"""Remove non-automotive imagery from the merged corpus.

A visual check of twelve random images — the first time anyone actually LOOKED
at this corpus rather than validating its structure — found two that were not
cars at all: a building interior with people holding a camera, and a close-up
of metal mesh. Both were labelled Rust / corrosion. Structural checks had all
passed: no orphaned annotations, no boxes outside their frames, no duplicate
hashes. None of that can tell you the picture is of a fence.

The class-name filter could never have caught these. OFF_MATERIAL rejects
"copper corrosion" because the LABEL says copper, but these projects label
industrial corrosion as plain "rust" and "corrosion" — correct for their own
domain, wrong for ours. The signal is the project, not the word.

Quantified across the corpus: identified industrial-corrosion projects are
18,837 images and 92,391 boxes, 17.9% of all annotations, of which 82,377 are
rust_paint. Add the pre-tracking rust_paint boxes (rust-detection-38s6e was the
only rust source among the ten projects ingested before `src` existed) and
roughly 90% of the rust class is not automotive.

This matters more than the raw count suggests. Modern cars rarely rust — the
real-world findings are paint mismatch, bad repair work, panel gaps and scuffs.
So the rust class was simultaneously the most contaminated AND the least useful,
and training on it would teach the detector that patina on a steel fence is car
damage while doing nothing for the defects an inspection actually finds.

    python drop_offdomain.py --merged DIR [--dry-run]
"""
import argparse
import json
import os

# Projects whose subject is industrial or aeronautical corrosion/defects, not
# vehicles. Matched as substrings of the recorded `src`.
OFF_DOMAIN_SRC = (
    "rust-detection",                     # graded corrosion, has a "car" class
    "labeler-projects/rust-and-corrosion",
    "oumaima-6jfwk/rust",
    "corrosion-l4cqs",
    "godson-alsjh/corrosion",
    "psm-lzkq8/corrosion",
    "yilmaz/corrosion",
    "scaledge-ztihl/corrosion",
    "kushal-mujral",
    "surface-defects",                    # NEU-DET steel benchmark
    "metallic-surface-defect",
    "lemi-debele/aircraft-surface-damage",  # aircraft skin, not cars
)

# The ten projects merged before `src` was recorded contained exactly one rust
# source (rust-detection-38s6e), so an untracked rust_paint box is industrial
# with high confidence. Dropping the class for those images only — their dent
# and scratch boxes are from car projects and stay.
PRE_TRACKING = ("", None, "(pre-tracking)", "?")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merged", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep-untracked-rust", action="store_true",
                    help="do not drop rust_paint from pre-tracking images")
    args = ap.parse_args()

    p = os.path.join(args.merged, "_annotations.coco.json")
    with open(p) as f:
        d = json.load(f)
    imgs, anns = d["images"], d["annotations"]

    drop_img = set()
    for i in imgs:
        s = str(i.get("src") or "")
        if s and any(k in s for k in OFF_DOMAIN_SRC):
            drop_img.add(i["id"])
    untracked = {i["id"] for i in imgs if (i.get("src") or "") in PRE_TRACKING}

    keep_imgs = [i for i in imgs if i["id"] not in drop_img]
    keep_anns = []
    dropped_rust = 0
    for a in anns:
        if a["image_id"] in drop_img:
            continue
        if (not args.keep_untracked_rust and a.get("cls") == "rust_paint"
                and a["image_id"] in untracked):
            dropped_rust += 1
            continue
        keep_anns.append(a)

    # An image left with no boxes is no longer trainable for detection.
    with_boxes = {a["image_id"] for a in keep_anns}
    keep_imgs = [i for i in keep_imgs if i["id"] in with_boxes]
    final_ids = {i["id"] for i in keep_imgs}
    keep_anns = [a for a in keep_anns if a["image_id"] in final_ids]

    from collections import Counter
    print(f"off-domain projects matched : {len(drop_img):,} images")
    print(f"untracked rust_paint dropped: {dropped_rust:,} boxes")
    print(f"\nbefore: {len(imgs):,} images, {len(anns):,} boxes")
    print(f"after : {len(keep_imgs):,} images, {len(keep_anns):,} boxes")
    print(f"removed: {len(imgs)-len(keep_imgs):,} images, "
          f"{len(anns)-len(keep_anns):,} boxes")
    print("\nresulting class mix:")
    for c, n in Counter(a.get("cls") for a in keep_anns).most_common():
        print(f"    {str(c):16s} {n:>9,}")

    if args.dry_run:
        print("\n(dry run — nothing written)")
        return

    idir = os.path.join(args.merged, "images")
    gone = 0
    for i in imgs:
        if i["id"] not in final_ids:
            try:
                os.remove(os.path.join(idir, i["file_name"]))
                gone += 1
            except OSError:
                pass
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"images": keep_imgs, "annotations": keep_anns,
                   "categories": d.get("categories", [])}, f)
    os.replace(tmp, p)
    print(f"\ndeleted {gone:,} image files; corpus rewritten")


if __name__ == "__main__":
    main()
