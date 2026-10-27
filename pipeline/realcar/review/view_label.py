"""view_label.py: the way each photo's car points, named by eye (the side
agents), so its build is pictured from the same side. The outline fit
(photo_paint.py --view) read about one front three-quarter photo in ten the
wrong way round: mirrored, the two outlines are nearly alike. A label here
wins over it in photo_view.json.

    python3 view_label.py sheet OUT.jpg KEY ... [--batch NAME] [--gold N]   # photos, 12 a sheet
    python3 view_label.py label "KEY=left KEY=right ..."   # left: the car's front points to the picture's left edge
    python3 view_label.py changed                          # keys pictured from another side than their label

A key whose label differs from the side its picture was taken from goes to
the rebuild queue at once. A sheet's labels are refused together when one is
wrong on a photo checked by hand, with the reason.
"""
import json
import os
import sys

import gold
import paint_label
import paths


def LABELS():
    return paths.f("view_label.json")


def taken():
    """The side each picture now on the cards was taken from: the renderer's
    log (rendered.jsonl, the last line of a key wins), else the snapshot kept
    before labels existed (view_taken.json); a key with neither was taken
    nose-left."""
    out = dict(paths.load(paths.f("view_taken.json")))
    if os.path.exists(paths.f("rendered.jsonl")):
        for line in open(paths.f("rendered.jsonl")):
            try:
                e = json.loads(line)
                out[e["key"]] = e.get("nose")
            except (ValueError, KeyError):
                continue
    return out


def label(pairs):
    got, bad = paint_label.parse(pairs, ("left", "right"))
    if bad:
        raise SystemExit(f"not recorded: {bad}: each label is KEY=left or KEY=right")
    rows = paths.rows()[0]
    unknown = [k for k in got if k not in rows]
    if unknown:
        raise SystemExit(f"not recorded: {unknown} are no keys of this run (copy them exactly from the sheet)")
    miss = paint_label.gold_misses("side", got)
    if miss:
        print("REFUSED (none of these labels recorded):\n  " + "\n  ".join(miss) +
              "\nThe rule: left means the car's FRONT (headlights, grille) is towards the picture's LEFT edge and its "
              "side trails away to the right; right is the mirror of that. Look again at every photo on this sheet, "
              "then record the sheet's labels again.")
        raise SystemExit(2)
    with paths.lock("view_label"):
        lab, view = paths.load(LABELS()), paths.load(paths.f("photo_view.json"))
        lab.update(got)
        view.update(got)
        paths.save(LABELS(), lab, indent=0)
        paths.save(paths.f("photo_view.json"), view, indent=0)
    paths.labelled("side", list(got))
    t = taken()
    for k, v in got.items():
        if (t.get(k) or "left") != v and rows[k].get("status") in ("built", "standin"):
            paths.queue_rebuild(k, f"pictured from the {t.get(k) or 'left'}, its photo points {v}")
    print(f"{len(got)} labelled")


def changed():
    lab, t = paths.load(LABELS()), taken()
    return sorted(k for k, v in lab.items() if (t.get(k) or "left") != v)


def main():
    a = sys.argv[1:]
    if a and a[0] == "sheet":
        batch = a[a.index("--batch") + 1] if "--batch" in a else None
        n = int(a[a.index("--gold") + 1]) if "--gold" in a else 0
        keys = [x for i, x in enumerate(a[2:], 2) if not x.startswith("--") and a[i - 1] not in ("--batch", "--gold")]
        return paint_label.sheet(a[1], keys, batch, n, kind="side", ask="name the way each car points")
    if a and a[0] == "label":
        return label(" ".join(a[1:]))
    if a and a[0] == "changed":
        ks = changed()
        return print(len(ks), "pictures to retake:", " ".join(ks))
    raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
