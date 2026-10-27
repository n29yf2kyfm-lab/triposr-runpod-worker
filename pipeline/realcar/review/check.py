"""check.py: the run's records checked against each other before anything is
published. Every check here is a mistake that was made once:

  results     a line that is not a whole record (a full disk cut one short)
  photo       a built car with no photo
  paint       its paint read from an older photo (a photo replaced, the paint not read again: the 300C)
  colour      its photo's colour never named by eye
  built       built in another colour than its photo's paint now
  side        its photo's side never named by eye, or its picture taken from the other side
  picture     no studio picture of the build
  verdict     no verdict, or one on an older build or an older photo
  queue       a rebuild queued (a new photo, colour or side) and not yet done
  label       a side or colour a verdict said was wrong, not yet named again
  gold        a batch that answered a checked item wrongly: its sheets are looked at again
  disk        under 2 GB free: the next run would stop part-way

    python3 check.py            # the summary; exit 1 when anything blocks publishing
    python3 check.py --lists    # and todo_*.txt for each kind, one key a line

Nothing is changed by it.
"""
import os
import shutil
import sys
from collections import defaultdict

import gold
import paths
import view_label

BLOCKING = ("results", "photo", "paint", "colour", "built", "side", "picture", "verdict", "queue", "label", "gold")


def run():
    rows, bad = paths.rows()
    found = defaultdict(list)
    if bad:
        found["results"].append(f"{bad} line(s) are not whole records (read past; those targets are built again by fleet.py build)")
    targets = [t for t in paths.load(paths.f("targets.json"), []) if t.get("class") in ("car", "van")]
    pp, plab = paths.load(paths.f("photo_paint.json")), paths.load(paths.f("paint_label.json"))
    vlab, taken = paths.load(paths.f("view_label.json")), view_label.taken()
    rev = paths.load(paths.f("build_review.json"))
    for t in targets:
        k = t["key"]
        r = rows.get(k)
        if not r:
            found["results"].append(f"{k}: not built yet")
            continue
        if r.get("status") not in ("built", "standin"):
            continue
        ph = paths.photo(k)
        if not ph:
            found["photo"].append(k)
            continue
        sha = paths.sha(ph)
        p = pp.get(k) or {}
        if p.get("photo_sha") and p["photo_sha"] != sha:
            found["paint"].append(f"{k}: paint read from an older photo")
        elif not p.get("hex"):
            found["paint"].append(f"{k}: no paint read")
        if not plab.get(k):
            found["colour"].append(k)
        if r.get("paint") and p.get("hex") and r["paint"] != p["hex"]:
            found["built"].append(f"{k}: built {r['paint']}, its photo's paint is {p['hex']}")
        if not vlab.get(k):
            found["side"].append(f"{k}: side never named")
        elif (taken.get(k) or "left") != vlab[k]:
            found["side"].append(f"{k}: pictured from the {taken.get(k) or 'left'}, its photo points {vlab[k]}")
        if not paths.picture(k):
            found["picture"].append(k)
        v = rev.get(k)
        if not v:
            found["verdict"].append(f"{k}: no verdict")
        elif not v.get("built_at") or v["built_at"] != r.get("built_at"):
            found["verdict"].append(f"{k}: verdict on an older build" if v.get("built_at") else f"{k}: verdict with no record of the build it judged")
        elif v.get("photo_sha") and v["photo_sha"] != sha:
            found["verdict"].append(f"{k}: verdict on an older photo")
    for k, q in paths.load(paths.f("needs_rebuild.json")).items():
        if (rows.get(k) or {}).get("built_at", "") < q["at"]:
            found["queue"].append(f"{k}: {q['why']}")
    for what, keys in paths.load(paths.f("needs_label.json")).items():
        for k in keys:
            found["label"].append(f"{k}: its {what} was said to be wrong; name it again ({what})")
    for b, s in gold.scores().items():
        if s["missed"] and not s.get("resolved"):
            found["gold"].append(f"batch {b}: missed {s['missed']} of {s['answered']} checked items ({'; '.join(s['misses'][:3])})")
    if shutil.disk_usage(paths.home()).free < 2e9:
        found["disk"].append(f"{shutil.disk_usage(paths.home()).free / 1e9:.1f} GB free")
    return found


def main():
    found = run()
    lists = "--lists" in sys.argv[1:]
    if not any(found.values()):
        print("all clear: every built car and van has its photo, paint, colour, side, picture and a current verdict")
        return
    for kind in BLOCKING + ("disk",):
        items = found.get(kind) or []
        if not items:
            continue
        print(f"{kind:8s} {len(items):4d}  " + "; ".join(items[:4]) + (" ..." if len(items) > 4 else ""))
        if lists:
            with open(paths.f(f"todo_{kind}.txt"), "w") as fh:
                fh.write("\n".join(i.split(":")[0] for i in items) + "\n")
    blocked = [k for k in BLOCKING if found.get(k)]
    if blocked:
        print("NOT READY to publish:", ", ".join(blocked))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
