"""Run the SHIPPED ONNX through the SHIPPED code path and prove findings come out.

WHY A SMOKE TEST AND NOT ANOTHER UNIT TEST
------------------------------------------
The unit suite had 255 passing tests while the detector returned nothing at
all in production. Every one of them fed a label that happened to be mapped,
so none of them exercised the actual contract: real weights, real class ids,
real environment. Three independent faults hid behind that gap --

  * five of the six trained class names were absent from DAMAGE_CLASS_MAP, and
    an unmapped label is DROPPED, not flagged
  * class names came only from DAMAGE_DETECTOR_LABELS, unset by default, so
    every id resolved to its own number and matched nothing
  * RF-DETR emits 1-based ids and they were indexed into a 0-based list

and a fourth that only appeared when this was first run end to end: the
non-tiled branch of detector_backend never passed the resolved input size, so
a fixed-shape 560 export rejected the 640 tensor outright.

Any of those makes the product report "no damage found" on a damaged car. None
of them is visible from a mock. So this loads the real artefact and asserts the
only thing that finally matters: damaged pixels in, findings out, on BOTH the
tiled and untiled paths, with the environment left at its defaults.

    python smoke_detect.py --model /home/user/rfdetr-base.onnx --images DIR
"""
import argparse
import glob
import json
import os
import sys


def run(model, image_dir, limit):
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)

    imgs = sorted(glob.glob(os.path.join(image_dir, "*.jpg")))[:limit]
    if not imgs:
        print(f"no images under {image_dir}")
        return 1
    os.environ["DAMAGE_DETECTOR_MODEL"] = model
    # DELIBERATELY UNSET. This is the default deployment, and the default is
    # what was broken: names must come from the model's own classes.json.
    os.environ.pop("DAMAGE_DETECTOR_LABELS", None)
    os.environ["DAMAGE_GRADE"] = "0"       # grading is enrichment, not the contract

    import detect
    ok = fail = 0

    def check(name, cond, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"  ok   {name}")
        else:
            fail += 1
            print(f"  FAIL {name} {detail}")

    labels = detect._labels_beside_model(model)
    check("class names resolve from the model, with no env var set",
          bool(labels), "no classes.json beside the model")
    if labels:
        check("names are keyed by the 1-based ids RF-DETR emits",
              min(labels) == 1, f"lowest id {min(labels)}")

    seen = {}
    for tiled in ("0", "1"):
        os.environ["DAMAGE_TILED"] = tiled
        out = detect.detector_backend()("", imgs)
        doc = json.loads(out) if isinstance(out, str) else out
        found = doc.get("findings") or []
        kinds = sorted({f["damage_type"] for f in found})
        seen[tiled] = (len(found), kinds)
        label = "tiled" if tiled == "1" else "whole-frame"
        print(f"\n  [{label}] {len(imgs)} images -> {len(found)} findings "
              f"{kinds}")
        check(f"{label}: the detector returns findings at all", found,
              "ZERO findings — the failure this file exists to catch")
        check(f"{label}: every finding names a real damage type",
              all(f.get("damage_type") for f in found))
        check(f"{label}: every finding carries a box",
              all(f.get("bbox") and len(f["bbox"]) == 4 for f in found))
        check(f"{label}: boxes are normalised into the unit square",
              all(0.0 <= v <= 1.0 for f in found for v in f["bbox"]),
              str([f["bbox"] for f in found][:2]))
        check(f"{label}: confidences are probabilities",
              all(0.0 <= f.get("confidence", -1) <= 1.0 for f in found))

    # More than one class must appear across the sample, or the run is the
    # old failure wearing a disguise: dent alone survived the class-map gap.
    allkinds = sorted(set(seen["0"][1]) | set(seen["1"][1]))
    check("more than one damage type is produced", len(allkinds) > 1,
          str(allkinds))
    check("the surviving types are not just dent", allkinds != ["dent"],
          str(allkinds))

    print(f"\n{ok} passed, {fail} failed")
    return 1 if fail else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="/home/user/rfdetr-base.onnx")
    ap.add_argument("--images",
                    default="/home/user/rf/merged640/cardd/images")
    ap.add_argument("--limit", type=int, default=5)
    a = ap.parse_args()
    return run(a.model, a.images, a.limit)


if __name__ == "__main__":
    sys.exit(main())
