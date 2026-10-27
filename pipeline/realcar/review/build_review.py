"""build_review.py: the build review agents' tools. Every car and van's build
is looked at beside its real photo and judged; the verdicts go to
build_review.json, each with the build and the photo it judged, so a verdict
on an older build or photo is seen as stale (check.py).

    python3 build_review.py sheet OUT.jpg KEY ... [--batch NAME] [--gold N]
    python3 build_review.py info KEY
    python3 build_review.py verdict KEY ok
    python3 build_review.py verdict KEY bad "fault, fault" "what is wrong, in a few words"
    python3 build_review.py verdict KEY bad "roof" "what is wrong" --roof body|FAMILY
    python3 build_review.py roof KEY same|body|FAMILY ["note"]       # the roof pass: the roof alone

Faults (one or more, comma separated):
  body        another body style (an estate for a hatch, an SUV for a saloon, a panel van for a pickup)
  generation  another generation of the car (a 2008 shape for a 2020 car)
  kind        a stand-in of another kind of vehicle (an MPV for a sports car, a van for an SUV)
  proportions stretched, squashed, too tall or too low (a high-roof van for a low-roof one)
  colour      the colour is clearly not the photo's
  broken      holes, torn or crumpled panels, blotches, parts missing or floating, wheels out of place,
              a panel or the wheels left in the model's own colour
  side        seen from the other side or end than the photo
  roof        the build's roof is not the photo's: --roof body when the photo's roof is the body's colour
              (a donor's black roof on a one-colour car), --roof FAMILY (white, black ...) when the photo's
              roof is another colour than its body (the Captur's white one): rebuilt with it painted
  photo       the photo itself is wrong (only after replacing it: web_photo.py choose)

A verdict is refused, with the reason, when it cannot be right: a key with no
build, "ok" with faults, "bad" with none or with no note, "photo" when the
photo was not replaced, or a wrong answer on a pair that was checked by hand.
"""
import os
import sys

import cv2
import numpy as np

import gold
import paths

FAULTS = {"body", "generation", "kind", "proportions", "colour", "broken", "side", "roof", "photo"}


def OUT():
    return paths.f("build_review.json")


def info(key, rows=None):
    r = (rows if rows is not None else paths.rows()[0]).get(key) or {}
    ph = (paths.load(paths.f("car_photos.json")).get(key) or {}).get("photo") or {}
    return {"request": r.get("request"), "built_as": r.get("title"), "status": r.get("status"), "built_at": r.get("built_at"),
            "from_model": r.get("source") if r.get("status") == "built" else (r.get("credit") or {}).get("title"),
            "stand_in": r.get("status") == "standin", "paint": r.get("paint"),
            "photo_generation": ph.get("generation"), "photo_years": ph.get("years"), "photo": ph.get("file")}


def cell(path, W, H):
    c = np.full((H, W, 3), 255, np.uint8)
    im = cv2.imread(path, cv2.IMREAD_UNCHANGED) if path else None
    if im is None:
        cv2.putText(c, "none", (W // 2 - 20, H // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 200), 1)
        return c
    if im.ndim == 3 and im.shape[2] == 4:
        ys, xs = np.nonzero(im[:, :, 3] > 10)
        if len(ys):
            im = im[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        a = im[:, :, 3:4] / 255.0
        im = (im[:, :, :3] * a + 236 * (1 - a)).astype(np.uint8)
    s = min(W / im.shape[1], H / im.shape[0])
    im = cv2.resize(im, (max(1, int(im.shape[1] * s)), max(1, int(im.shape[0] * s))))
    y, x = (H - im.shape[0]) // 2, (W - im.shape[1]) // 2
    c[y:y + im.shape[0], x:x + im.shape[1]] = im
    return c


def sheet(out, keys, batch=None, n_gold=0, kind="build"):
    keys = gold.mix(keys, kind, n_gold, out, batch) if n_gold else list(keys)
    if not n_gold:
        gold.note_sheet(out, batch, keys, [])
    rows = paths.rows()[0]
    W, H, cells = 420, 260, []
    for k in keys:
        i = info(k, rows)
        row = np.full((H + 34, 2 * W + 10, 3), 255, np.uint8)
        row[34:, :W] = cell(paths.photo(k), W, H)
        row[34:, W + 10:] = cell(paths.picture(k), W, H)
        tag = ("STAND-IN from " if i["stand_in"] else "own model: ") + str(i["from_model"] or "?")[:40]
        cv2.putText(row, f"{k}  |  {str(i['built_as'] or i['request'])[:46]}", (3, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 150), 1)
        cv2.putText(row, tag, (3, 29), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)
        cells.append(row)
    while len(cells) % 2:
        cells.append(np.full_like(cells[0], 255))
    grid = np.vstack([np.hstack([cells[i], np.full((cells[i].shape[0], 16, 3), 200, np.uint8), cells[i + 1]])
                      for i in range(0, len(cells), 2)])
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    cv2.imwrite(out, grid, [cv2.IMWRITE_JPEG_QUALITY, 82])
    print("wrote", out, f"({len(keys)} pairs: give each one a verdict)")


class Refused(Exception):
    """A verdict that cannot be right: not recorded."""


def check(key, verdict, faults, note, rows=None, roof=None):
    """The reason a verdict cannot stand, or None."""
    r = (rows if rows is not None else paths.rows()[0]).get(key)
    if not r:
        return f"{key} is not a key of this run: copy it exactly from the red line on the sheet"
    if r.get("status") not in ("built", "standin"):
        return f"{key} was not built ({r.get('status')}): it has no build to judge"
    if verdict not in ("ok", "bad"):
        return "the verdict is ok or bad"
    bad = [x for x in faults if x not in FAULTS]
    if bad:
        return f"unknown fault {bad}: use only {sorted(FAULTS)}"
    if verdict == "ok" and faults:
        return "an ok build has no faults: if something is wrong it is bad"
    if verdict == "bad" and not faults:
        return "a bad build names at least one fault"
    if verdict == "bad" and len(note.split()) < 3:
        return "say what is wrong in a few words (the note): the next person fixes it from that"
    if ("roof" in faults) != bool(roof):
        return ("a roof fault says what the photo's roof is: --roof body (the body's colour) or --roof FAMILY "
                "(white, black, ...)" if "roof" in faults else "--roof goes with the fault 'roof'")
    if roof:
        from paint_label import FAMILY
        if roof != "body" and roof not in FAMILY:
            return f"--roof is body or a colour family: {' '.join(FAMILY)}"
    if "photo" in faults:
        rv = paths.load(paths.f("photo_review.json")).get(key) or {}
        if not rv.get("replaced_at") or (r.get("built_at") and rv["replaced_at"] < r["built_at"]):
            return ("'photo' is only for a photo you replaced (web_photo.py choose ...). If the photo is right, "
                    "judge the build against it; if it is wrong, replace it first")
    return None


def verdict(key, v, faults, note, roof=None):
    rows = paths.rows()[0]
    why = check(key, v, faults, note, rows, roof)
    if why:
        raise Refused(why)
    g = gold.judge("build", key, v, faults)
    if g is not None:
        gold.log("build", key, v + (f" ({', '.join(faults)})" if faults else ""), g["right"])
        if not g["right"]:
            raise Refused(f"not recorded: this pair was checked by hand and is {g['expected']}: {g['why']}. "
                          "Look at it again, then at every pair you have judged on this sheet, against the "
                          "fault list in your instructions, before you go on; then record this one again.")
    r = rows[key]
    with paths.lock("build_review"):
        d = paths.load(OUT())
        d[key] = {"verdict": v, "faults": faults, "note": note, "at": paths.now(), "built_at": r.get("built_at"),
                  "photo_sha": paths.sha(paths.photo(key))}
        paths.save(OUT(), d)
    if "roof" in faults:
        # the photo's roof is the body's colour: the rebuild paints the
        # build's (fleet.py asks for it from roof_label.json)
        with paths.lock("roof_label"):
            rl = paths.load(paths.f("roof_label.json"))
            rl[key] = {"roof": roof, "by": "build review", "at": paths.now()}
            paths.save(paths.f("roof_label.json"), rl)
        paths.queue_rebuild(key, "its roof in the body's colour, as the photo's" if roof == "body"
                            else f"its roof {roof}, as the photo's")
    if "side" in faults or "colour" in faults:
        # the side and the colour are named by eye (view_label.py, paint_label.py):
        # one the build shows wrong is named again before it is rebuilt
        with paths.lock("needs_label"):
            q = paths.load(paths.f("needs_label.json"))
            for what in ("side", "colour"):
                if what in faults:
                    q.setdefault(what, {})[key] = paths.now()
            paths.save(paths.f("needs_label.json"), q)


def roof(key, answer, note=""):
    """The roof pass: the build's roof against the photo's. "same" (as the
    photo's: one colour, or both two-tone alike), "body" (the photo's roof is
    the body's colour, the build's is not) or a colour family (the photo's
    roof is that colour, the build's is not). Anything but "same" asks the
    rebuild for the photo's roof."""
    from paint_label import FAMILY
    rows = paths.rows()[0]
    r = rows.get(key)
    if not r:
        raise Refused(f"{key} is not a key of this run: copy it exactly from the red line on the sheet")
    if r.get("status") not in ("built", "standin"):
        raise Refused(f"{key} was not built ({r.get('status')}): it has no build to judge")
    if answer not in ("same", "body") and answer not in FAMILY:
        raise Refused(f"the roof is same, body or a colour family: {' '.join(FAMILY)}")
    g = gold.judge("roof", key, answer)
    if g is not None:
        gold.log("roof", key, answer, g["right"])
        if not g["right"]:
            raise Refused(f"not recorded: this roof was checked by hand and is {g['expected']}: {g['why']}. "
                          "Look at it again, then at every roof you have answered on this sheet, before you go on; "
                          "then answer this one again.")
    with paths.lock("roof_check"):
        d = paths.load(paths.f("roof_check.json"))
        d[key] = {"answer": answer, "note": note, "at": paths.now(), "built_at": r.get("built_at"),
                  "photo_sha": paths.sha(paths.photo(key))}
        paths.save(paths.f("roof_check.json"), d)
    if answer != "same":
        with paths.lock("roof_label"):
            rl = paths.load(paths.f("roof_label.json"))
            rl[key] = {"roof": answer, "by": "roof pass", "at": paths.now()}
            paths.save(paths.f("roof_label.json"), rl)
        paths.queue_rebuild(key, "its roof in the body's colour, as the photo's" if answer == "body"
                            else f"its roof {answer}, as the photo's")


def main():
    a = sys.argv[1:]
    if a[:1] == ["roof"] and len(a) >= 3:
        try:
            roof(a[1], a[2], a[3] if len(a) > 3 else "")
        except Refused as e:
            print("REFUSED:", e)
            raise SystemExit(2)
        return print("recorded roof", a[1], a[2])
    if not a:
        raise SystemExit(__doc__)
    if a[0] == "sheet":
        batch = a[a.index("--batch") + 1] if "--batch" in a else None
        n = int(a[a.index("--gold") + 1]) if "--gold" in a else 0
        keys = [x for i, x in enumerate(a[2:], 2) if not x.startswith("--") and a[i - 1] not in ("--batch", "--gold")]
        return sheet(a[1], keys, batch, n)
    if a[0] == "info":
        import json
        return print(json.dumps(info(a[1]), indent=1))
    if a[0] == "verdict":
        if len(a) < 3:
            raise SystemExit(__doc__)
        roof = a[a.index("--roof") + 1] if "--roof" in a and a.index("--roof") + 1 < len(a) else None
        a = [x for i, x in enumerate(a) if x != "--roof" and (i == 0 or a[i - 1] != "--roof")]
        faults = [x.strip() for x in (a[3] if len(a) > 3 else "").split(",") if x.strip()]
        try:
            verdict(a[1], a[2], faults, a[4] if len(a) > 4 else "", roof)
        except Refused as e:
            print("REFUSED:", e)
            raise SystemExit(2)
        return print("recorded", a[1], a[2])
    raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
